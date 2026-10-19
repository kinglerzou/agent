"""Local multilingual ONNX embeddings with a content-addressed SQLite vector cache.

No game text is sent to a provider. Model downloads are an explicit setup step.
PostgreSQL remains the authority for documents; this file only caches derived vectors.
"""
import hashlib
import json
import math
import os
import sqlite3
import threading
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path

MODEL = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
MODEL_REPO = 'qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q'
MODEL_REVISION = 'faf4aa4225822f3bc6376869cb1164e8e3feedd0'
MODEL_FILES = ['config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json', 'model_optimized.onnx']
DIMENSION = 384
_LOCK = threading.RLock()


class EmbeddingUnavailable(RuntimeError):
    pass


def normalize(vector):
    values = [float(v) for v in vector]
    if not values or any(not math.isfinite(v) for v in values):
        raise EmbeddingUnavailable('Embedding 返回了空向量或非有限数值')
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0:
        raise EmbeddingUnavailable('Embedding 返回了零向量')
    return [v / norm for v in values]


def settings():
    root = Path(os.getenv('GAME_EMBEDDING_CACHE_DIR', 'data/embeddings')).resolve()
    return root


class LocalEmbeddings:
    def __init__(self, root, download=False):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise EmbeddingUnavailable('缺少 FastEmbed，请安装 apps/api/requirements.txt') from exc
        try:
            from huggingface_hub import snapshot_download
            from tokenizers import Tokenizer
            model_dir = Path(snapshot_download(MODEL_REPO, revision=MODEL_REVISION,
                                              cache_dir=str(self.root / 'models'), allow_patterns=MODEL_FILES,
                                              local_files_only=not download, token=False))
            if any(not (model_dir / name).is_file() for name in MODEL_FILES):
                raise FileNotFoundError('Incomplete model snapshot')
            self.model = TextEmbedding(model_name=MODEL, cache_dir=str(self.root / 'models'),
                                       threads=2, local_files_only=True, specific_model_path=str(model_dir))
            self.tokenizer = Tokenizer.from_file(str(model_dir / 'tokenizer.json'))
            self.tokenizer.no_truncation()
            self.tokenizer.no_padding()
        except Exception as exc:
            raise EmbeddingUnavailable('本地向量模型不可用，请先运行 .venv/bin/python scripts/prepare-game-embeddings.py') from exc
        # Include actual weights/tokenizer bytes, not only a mutable model name.
        digest = hashlib.sha256()
        for path in sorted(model_dir.rglob('*')):
            if path.is_file() and path.suffix in ('.onnx', '.json', '.txt', '.model'):
                digest.update(str(path.relative_to(model_dir)).encode())
                with path.open('rb') as source:
                    for block in iter(lambda: source.read(1024 * 1024), b''):
                        digest.update(block)
        self.identity = f'{MODEL}:fastembed-{version("fastembed")}:token-window-120-stride104-mean-v2:{digest.hexdigest()}'
        self.db_path = self.root / 'vectors.sqlite3'
        with sqlite3.connect(self.db_path, timeout=30) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('''CREATE TABLE IF NOT EXISTS vectors (
                model TEXT NOT NULL, digest TEXT NOT NULL, vector TEXT NOT NULL,
                PRIMARY KEY(model, digest))''')

    def segments(self, text):
        # This model's tokenizer truncates at 128. Cover every token of a 360-char
        # evidence chunk instead of silently dropping its tail.
        encoded = self.tokenizer.encode(text, add_special_tokens=False)
        if len(encoded.ids) <= 120:
            return [text]
        return [text[encoded.offsets[start][0]:encoded.offsets[min(start + 120, len(encoded.ids)) - 1][1]]
                for start in range(0, len(encoded.ids), 104)]

    def encode(self, texts, kind='document'):
        if not texts:
            return []
        if kind not in ('document', 'query'):
            raise ValueError('Invalid embedding kind')
        keys = [hashlib.sha256((kind + '\0' + text).encode()).hexdigest() for text in texts]
        # Guard ONNX inference and the read/compute/write cycle in this process.
        with _LOCK, sqlite3.connect(self.db_path, timeout=30) as db:
            found = {}
            for key in dict.fromkeys(keys):
                row = db.execute('SELECT vector FROM vectors WHERE model=? AND digest=?', (self.identity, key)).fetchone()
                if row:
                    try:
                        vector = json.loads(row[0])
                        if len(vector) != DIMENSION:
                            raise ValueError('dimension')
                        found[key] = normalize(vector)
                    except (ValueError, TypeError, EmbeddingUnavailable):
                        db.execute('DELETE FROM vectors WHERE model=? AND digest=?', (self.identity, key))
            pending = list(dict((key, text) for key, text in zip(keys, texts) if key not in found).items())
            for start in range(0, len(pending), 32):
                batch = pending[start:start + 32]
                try:
                    groups = [self.segments(text) for _, text in batch]
                    inputs = [part for group in groups for part in group]
                    vectors = list(self.model.query_embed(inputs, batch_size=32) if kind == 'query' else self.model.embed(inputs, batch_size=32))
                    if len(vectors) != len(inputs):
                        raise EmbeddingUnavailable('Embedding 返回数量不匹配')
                    offset = 0
                    for (key, _), group in zip(batch, groups):
                        parts = [normalize(vector) for vector in vectors[offset:offset + len(group)]]
                        offset += len(group)
                        if any(len(part) != DIMENSION for part in parts):
                            raise EmbeddingUnavailable('Embedding 维度不匹配')
                        normalized = normalize([sum(part[i] for part in parts) / len(parts) for i in range(DIMENSION)])
                        if len(normalized) != DIMENSION:
                            raise EmbeddingUnavailable('Embedding 维度不匹配')
                        found[key] = normalized
                        db.execute('INSERT OR REPLACE INTO vectors VALUES(?,?,?)',
                                   (self.identity, key, json.dumps(normalized)))
                except EmbeddingUnavailable:
                    raise
                except Exception as exc:
                    raise EmbeddingUnavailable('本地向量计算失败，请检查模型文件与缓存目录权限') from exc
            return [found[key] for key in keys]


@lru_cache(maxsize=2)
def _backend(root):
    with _LOCK:
        return LocalEmbeddings(root)


def get_embeddings():
    return _backend(str(settings()))
