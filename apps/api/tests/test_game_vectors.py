import hashlib
import json
import sqlite3

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from studio import game_embeddings
from studio.game_embeddings import EmbeddingUnavailable, LocalEmbeddings, normalize
from studio.game_rag import attach_rag_routes
from studio.game_rag_eval import EvalRequest, evaluate
from studio.game_retrieval import RetrievalIndex, RetrievalOptions, reciprocal_rank_fusion


DOCS = [
    {'id': 'banner', 'title': '首页', 'content': '横幅不可见时检查投放时间'},
    {'id': 'gift', 'title': '礼包', 'content': '领取失败检查库存'},
]


class Vectors:
    identity = 'test-only-embedding-v1'

    def encode(self, texts, kind='document'):
        # Deterministic test double, never exposed as production embedding.
        return [[1., 0.] if ('横幅' in t or '轮播图' in t) else [0., 1.] for t in texts]


def test_vector_recalls_without_lexical_overlap_and_filters():
    index = RetrievalIndex(DOCS, Vectors())
    assert index.search('轮播图')['sources'] == []
    result = index.search('轮播图', RetrievalOptions(strategy='vector', min_similarity=.9))
    assert [row['document_id'] for row in result['sources']] == ['banner']
    assert result['sources'][0]['vector_score'] == pytest.approx(1)
    assert result['trace']['embedding_model'] == Vectors.identity
    assert result['trace']['score_type'] == 'cosine'
    assert result['trace']['embedding_dimension'] == 2
    changed = RetrievalIndex(DOCS[1:], Vectors())
    assert changed.search('轮播图', RetrievalOptions(strategy='vector'))['sources'] == []
    assert RetrievalIndex([], Vectors()).search('轮播图', RetrievalOptions(strategy='vector'))['sources'] == []


def test_hybrid_rrf_scores_and_both_candidate_routes():
    lexical = [{'id': 'a', 'score': 20}, {'id': 'b', 'score': 10}]
    dense = [{'id': 'b', 'score': .8}, {'id': 'c', 'score': .7}]
    fused = reciprocal_rank_fusion(lexical, dense)
    assert [r['id'] for r in fused] == ['b', 'a', 'c']
    assert fused[0]['score'] == pytest.approx(1 / 62 + 1 / 61)
    assert fused[0]['bm25_score'] == 10
    assert fused[0]['vector_score'] == .8
    assert fused[0]['bm25_rank'] == 2
    index = RetrievalIndex(DOCS, Vectors())
    result = index.search('轮播图 礼包', RetrievalOptions(strategy='hybrid'))
    assert {row['document_id'] for row in result['sources']} == {'gift', 'banner'}
    assert result['trace']['score_type'] == 'rrf'


def test_bad_vectors_fail_explicitly():
    for vector in ([], [0., 0.], [float('nan')], [float('inf')]):
        with pytest.raises(EmbeddingUnavailable):
            normalize(vector)
    class Mismatch(Vectors):
        def encode(self, texts, kind='document'):
            return [[1., 0., 0.] if kind == 'query' else [1., 0.] for _ in texts]
    with pytest.raises(EmbeddingUnavailable, match='维度'):
        RetrievalIndex(DOCS, Mismatch()).search('x', RetrievalOptions(strategy='vector'))
    for body in ({'min_similarity': 1.1}, {'candidate_k': 500}, {'strategies': ['vector', 'vector']}):
        with pytest.raises(ValidationError):
            EvalRequest(**body)


def test_vector_cache_reuse_content_identity_and_corruption(tmp_path):
    backend = object.__new__(LocalEmbeddings)
    backend.identity = 'model-a'
    backend.db_path = tmp_path / 'vectors.sqlite3'
    with sqlite3.connect(backend.db_path) as db:
        db.execute('CREATE TABLE vectors (model TEXT, digest TEXT, vector TEXT, PRIMARY KEY(model,digest))')
    class Model:
        count = 0
        def embed(self, texts, **kwargs):
            self.count += len(texts)
            return [[1.] + [0.] * 383 for _ in texts]
        query_embed = embed
    backend.model = Model()
    backend.segments = lambda text: [text]
    assert len(backend.encode(['a', 'a', 'b'])) == 3
    assert backend.model.count == 2
    backend.encode(['a', 'b'])
    assert backend.model.count == 2
    backend.encode(['a'], kind='query')
    assert backend.model.count == 3
    backend.encode(['changed'])
    assert backend.model.count == 4
    backend.identity = 'model-b'
    backend.encode(['a'])
    assert backend.model.count == 5
    key = hashlib.sha256(b'document\0a').hexdigest()
    with sqlite3.connect(backend.db_path) as db:
        db.execute('UPDATE vectors SET vector=? WHERE digest=?', (json.dumps([0.] * 384), key))
    backend.encode(['a'])
    assert backend.model.count == 6


def test_four_strategy_evaluation_and_missing_model_error(monkeypatch):
    request = EvalRequest(corpus='current', strategies=['bm25', 'expanded_bm25', 'vector', 'hybrid'],
                          cases=[{'id': 'q', 'query': '轮播图', 'relevant': {'banner': 3}}])
    report = evaluate(request, DOCS, revision=3, embeddings=Vectors())
    assert len(report['reports']) == 4
    assert report['reports'][0]['summary']['recall'] == 0
    assert report['reports'][2]['summary']['recall'] == 1
    def unavailable():
        raise EmbeddingUnavailable('test-model-unavailable')
    monkeypatch.setattr(game_embeddings, 'get_embeddings', unavailable)
    app = FastAPI()
    router = APIRouter()
    attach_rag_routes(router, lambda: None)
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post('/retrieval/evaluate', json={'strategies': ['vector']})
        assert response.status_code == 503
        assert response.json()['detail'] == 'test-model-unavailable'
        assert client.post('/retrieval/evaluate', json={}).status_code == 200


def test_token_windows_cover_tail_without_truncation():
    from types import SimpleNamespace
    backend = object.__new__(LocalEmbeddings)
    class Tokenizer:
        def encode(self, text, **kwargs):
            return SimpleNamespace(ids=list(range(len(text))), offsets=[(i, i + 1) for i in range(len(text))])
    backend.tokenizer = Tokenizer()
    text = '甲' * 400 + '尾部关键证据'
    parts = backend.segments(text)
    assert len(parts) > 1
    assert all(len(part) <= 120 for part in parts)
    assert parts[-1].endswith('尾部关键证据')
