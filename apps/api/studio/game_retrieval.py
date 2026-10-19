"""Versioned lexical, local dense and RRF hybrid retrieval shared by serving and evaluation."""
import hashlib
import json
import math
import time
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .knowledge import terms

VERSION = 'game-retrieval-v3'
Strategy = Literal['bm25', 'expanded_bm25', 'vector', 'hybrid']
VECTOR_STRATEGIES = ('vector', 'hybrid')
SYNONYMS = (
    ('奖励没到账', '奖励未到账', '发奖失败', '奖励发放'),
    ('礼包', '福利包', '新手福利'),
    ('Banner', 'banner', '横幅', '轮播图'),
    ('不展示', '看不到', '不显示'),
    ('库存耗尽', '领完了', '库存不足'),
    ('兑换失败', '兑换不了', '激活失败'),
    ('下线回滚', '撤回活动', '暂停投放'),
    ('灰度人群', '部分用户', '测试白名单'),
)


class RetrievalOptions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    strategy: Strategy = 'bm25'
    top_k: int = Field(default=4, ge=1, le=20)
    min_score: float = Field(default=0, ge=0, allow_inf_nan=False)
    min_similarity: float = Field(default=.35, ge=-1, le=1, allow_inf_nan=False)
    candidate_k: int = Field(default=40, ge=20, le=200)
    vector_backend: Literal['local', 'pgvector'] = 'pgvector'
    vector_search_mode: Literal['exact', 'hnsw'] = 'exact'


class SearchRequest(RetrievalOptions):
    query: str = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def nonempty(self):
        self.query = self.query.strip()
        if not self.query:
            raise ValueError('问题不能为空')
        return self


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


class RetrievalIndex:
    def __init__(self, documents, embeddings=None, vector_store=None):
        started = time.perf_counter()
        self.documents = sorted(documents, key=lambda d: d['id'])
        self.corpus_hash = fingerprint(self.documents)
        self.chunks = []
        for doc in self.documents:
            for start in range(0, len(doc['content']), 280):
                self.chunks.append(dict(doc, document_id=doc['id'], id=f"{doc['id']}:{start // 280}",
                                        offset=start, content=doc['content'][start:start + 360]))
        self.tokens = [Counter(terms(d['title'] + ' ' + d['content'])) for d in self.chunks]
        self.lengths = [sum(t.values()) for t in self.tokens]
        self.average = sum(self.lengths) / max(len(self.lengths), 1)
        self.df = Counter(term for counts in self.tokens for term in counts)
        self.embeddings = embeddings
        self.vector_store = vector_store
        self.vector_set_id = None
        self.vector_index = None
        self.build_ms = (time.perf_counter() - started) * 1000

    def search(self, query, options=None):
        options = options or RetrievalOptions()
        if options.strategy in VECTOR_STRATEGIES:
            return self.vector_search(query, options)
        started = time.perf_counter()
        expanded = query
        matched = []
        if options.strategy == 'expanded_bm25':
            for group in SYNONYMS:
                if any(word.lower() in query.lower() for word in group):
                    matched.extend(group)
            expanded = query + ' ' + ' '.join(dict.fromkeys(matched))
        query_terms = set(terms(expanded))
        results = []
        for doc, counts, length in zip(self.chunks, self.tokens, self.lengths):
            score = 0.0
            for term in sorted(query_terms):
                frequency = counts[term]
                if not frequency:
                    continue
                idf = math.log(1 + (len(self.tokens) - self.df[term] + .5) / (self.df[term] + .5))
                score += idf * frequency * 2.5 / (frequency + 1.5 * (.25 + .75 * length / max(self.average, 1)))
            if score > 0 and score >= options.min_score:
                results.append(dict(doc, score=round(score, 6),
                                    matched_terms=sorted(query_terms.intersection(counts))))
        results.sort(key=lambda d: (-d['score'], d['id']))
        return {'sources': results[:options.top_k], 'trace': {
            'version': VERSION, 'strategy': options.strategy, 'query': query,
            'expanded_query': expanded.strip(), 'top_k': options.top_k, 'min_score': options.min_score,
            'document_count': len(self.documents), 'chunk_count': len(self.chunks),
            'candidate_count': len(results), 'corpus_hash': self.corpus_hash,
            'search_ms': round((time.perf_counter() - started) * 1000, 3),
            'index_build_ms': round(self.build_ms, 3),
        }}

    def prepare_vectors(self):
        from .game_embeddings import get_embeddings, normalize, EmbeddingUnavailable
        backend = self.embeddings or get_embeddings()
        self.embeddings = backend
        if self.vector_store:
            if self.vector_set_id is None:
                self.vector_set_id = self.vector_store.ensure(self, backend)
            return backend
        # Normalize even injected backends: cosine scores must remain comparable.
        if self.vector_index is None:
            vectors = backend.encode([d['title'] + '\n' + d['content'] for d in self.chunks])
            if len(vectors) != len(self.chunks):
                raise EmbeddingUnavailable('Embedding 返回数量不匹配')
            self.vector_index = [normalize(vector) for vector in vectors]
        return backend

    def vector_search(self, query, options):
        from .game_embeddings import normalize, EmbeddingUnavailable
        started = time.perf_counter()
        backend = self.prepare_vectors()
        vector_ready_ms = (time.perf_counter() - started) * 1000
        search_started = time.perf_counter()
        query_vector = normalize(backend.encode([query], kind='query')[0])
        candidates = []
        if self.vector_store:
            candidates = self.vector_store.search(self.vector_set_id, query_vector, options)
        for doc, vector in zip(self.chunks, self.vector_index or []):
            if len(vector) != len(query_vector):
                raise EmbeddingUnavailable('查询与文档 Embedding 维度不一致')
            similarity = max(-1., min(1., sum(a * b for a, b in zip(query_vector, vector))))
            if similarity >= options.min_similarity:
                candidates.append(dict(doc, score=round(similarity, 6),
                                       vector_score=round(similarity, 6), matched_terms=[]))
        candidates.sort(key=lambda d: (-d['score'], d['id']))
        dense = candidates[:options.candidate_k]
        if options.strategy == 'hybrid':
            # Public K limits returned context; fusion uses a separate candidate budget.
            internal = RetrievalOptions().model_copy(update={
                'top_k': options.candidate_k, 'min_score': options.min_score})
            lexical = self.search(query, internal)['sources']
            candidates = reciprocal_rank_fusion(lexical, dense)
        return {'sources': candidates[:options.top_k], 'trace': {
            'version': VERSION, 'strategy': options.strategy, 'query': query, 'expanded_query': query,
            'top_k': options.top_k, 'min_score': options.min_score, 'min_similarity': options.min_similarity,
            'candidate_k': options.candidate_k, 'rrf_k': 60 if options.strategy == 'hybrid' else None,
            'score_type': 'rrf' if options.strategy == 'hybrid' else 'cosine',
            'vector_backend': 'pgvector' if self.vector_store else 'local',
            'vector_search_mode': options.vector_search_mode if self.vector_store else 'exact',
            'vector_set_id': self.vector_set_id,
            'embedding_model': backend.identity, 'embedding_dimension': len(query_vector),
            'document_count': len(self.documents), 'chunk_count': len(self.chunks),
            'candidate_count': len(candidates), 'corpus_hash': self.corpus_hash,
            'search_ms': round((time.perf_counter() - search_started) * 1000, 3),
            'vector_prepare_ms': round(vector_ready_ms, 3),
            'index_build_ms': round(self.build_ms, 3),
        }}


def reciprocal_rank_fusion(lexical, dense, rank_constant=60):
    fused = {}
    for name, sources in (('bm25', lexical), ('vector', dense)):
        for rank, source in enumerate(sources, 1):
            record = fused.setdefault(source['id'], dict(source, score=0., bm25_rank=None, vector_rank=None))
            record['score'] += 1 / (rank_constant + rank)
            record[name + '_rank'] = rank
            record[name + '_score'] = source['score']
    return sorted(fused.values(), key=lambda row: (-row['score'], row['id']))
