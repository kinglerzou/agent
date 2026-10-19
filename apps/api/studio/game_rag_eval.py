"""Retrieval-only evaluation: document-level judgments, deduplicated chunk results."""
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
import json

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .game_retrieval import RetrievalIndex, RetrievalOptions, VERSION, fingerprint, Strategy, VECTOR_STRATEGIES

DATASET = Path(__file__).parent / 'datasets/game_rag_v1.json'


class EvalCase(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=100)
    query: str = Field(min_length=1, max_length=1000)
    relevant: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode='after')
    def valid(self):
        if not self.query.strip() or not self.id.strip():
            raise ValueError('题目 ID 与问题不能为空')
        if any(not key or type(value) is not int or not 1 <= value <= 3 for key, value in self.relevant.items()):
            raise ValueError('相关性等级必须为 1–3；无答案使用空对象')
        return self


class EvalRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    corpus: Literal['fixture', 'current'] = 'fixture'
    top_k: int = Field(default=4, ge=1, le=20)
    min_score: float = Field(default=0, ge=0, allow_inf_nan=False)
    min_similarity: float = Field(default=.35, ge=-1, le=1, allow_inf_nan=False)
    candidate_k: int = Field(default=40, ge=20, le=200)
    vector_backend: Literal['local', 'pgvector'] = 'local'
    vector_search_mode: Literal['exact', 'hnsw'] = 'exact'
    strategies: list[Strategy] = Field(default_factory=lambda: ['bm25', 'expanded_bm25'], min_length=1, max_length=4)
    cases: Optional[list[EvalCase]] = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode='after')
    def labeled(self):
        if len(set(self.strategies)) != len(self.strategies):
            raise ValueError('策略不能重复')
        if self.corpus == 'current' and not self.cases:
            raise ValueError('当前知识库需要提供人工标注题集')
        if self.cases and len({c.id for c in self.cases}) != len(self.cases):
            raise ValueError('题目 ID 不能重复')
        return self


def fixture():
    return json.loads(DATASET.read_text())


def metrics(sources, relevant, k):
    # Cut off at k chunks BEFORE deduplication: repeated chunks consume context budget.
    ranked = list(dict.fromkeys(s['document_id'] for s in sources[:k]))
    gains = [relevant.get(doc, 0) for doc in ranked]
    hits = sum(g > 0 for g in gains)
    dcg = sum((2 ** grade - 1) / math.log2(rank + 2) for rank, grade in enumerate(gains))
    ideal = sum((2 ** grade - 1) / math.log2(rank + 2)
                for rank, grade in enumerate(sorted(relevant.values(), reverse=True)[:k]))
    return {'recall': hits / len(relevant) if relevant else None,
            'mrr': next((1 / (i + 1) for i, g in enumerate(gains) if g), 0) if relevant else None,
            'ndcg': dcg / ideal if ideal else None,
            'false_positive': bool(ranked) if not relevant else None,
            'retrieved_document_ids': ranked}


def evaluate(request, documents=None, revision=None, embeddings=None, vector_store=None):
    data = fixture()
    documents = data['documents'] if request.corpus == 'fixture' else documents
    cases = request.cases or [EvalCase.model_validate(c) for c in data['cases']]
    known = {d['id'] for d in documents}
    missing = sorted({doc for case in cases for doc in case.relevant if doc not in known})
    if missing:
        raise ValueError('标注文档不存在：' + ', '.join(missing))
    if request.vector_backend == 'pgvector' and any(s in VECTOR_STRATEGIES for s in request.strategies) and vector_store is None:
        raise ValueError('pgvector 评测需要数据库向量存储')
    index = RetrievalIndex(documents, embeddings=embeddings, vector_store=vector_store)
    warmup_ms = 0.
    uses_vectors = any(strategy in VECTOR_STRATEGIES for strategy in request.strategies)
    if uses_vectors:
        warmup_started = time.perf_counter()
        backend = index.prepare_vectors()
        backend.encode([case.query for case in cases], kind='query')
        warmup_ms = (time.perf_counter() - warmup_started) * 1000
    reports = []
    for strategy in request.strategies:
        rows = []
        for case in cases:
            result = index.search(case.query, RetrievalOptions(strategy=strategy, top_k=request.top_k,
                                                               min_score=request.min_score, min_similarity=request.min_similarity,
                                                               candidate_k=request.candidate_k, vector_backend=request.vector_backend,
                                                               vector_search_mode=request.vector_search_mode))
            rows.append(dict(case.model_dump(), **result,
                             metrics=metrics(result['sources'], case.relevant, request.top_k)))
        positive = [r for r in rows if r['relevant']]
        negative = [r for r in rows if not r['relevant']]
        latencies = sorted(r['trace']['search_ms'] for r in rows)
        summary = {name: sum(r['metrics'][name] for r in positive) / len(positive) if positive else None
                   for name in ('recall', 'mrr', 'ndcg')}
        summary.update(false_positive_rate=sum(r['metrics']['false_positive'] for r in negative) / len(negative) if negative else None,
                       p95_search_ms=latencies[math.ceil(.95 * len(latencies)) - 1],
                       answerable_count=len(positive), unanswerable_count=len(negative))
        reports.append({'strategy': strategy, 'summary': summary, 'cases': rows})
    return {'version': VERSION, 'created_at': datetime.now(timezone.utc).isoformat(),
            'corpus': request.corpus, 'revision': revision if request.corpus == 'current' else None,
            'corpus_hash': index.corpus_hash, 'dataset_hash': fingerprint([c.model_dump() for c in cases]),
            'dataset_name': data['name'] if request.cases is None else 'custom',
            'top_k': request.top_k, 'min_score': request.min_score,
            'min_similarity': request.min_similarity, 'candidate_k': request.candidate_k, 'vector_backend': request.vector_backend,
            'vector_search_mode': request.vector_search_mode,
            'vector_warmup_ms': round(warmup_ms, 3), 'embedding_cache_state': 'prewarmed' if uses_vectors else 'not_used', 'index_build_ms': round(index.build_ms, 3),
            'document_count': len(documents), 'chunk_count': len(index.chunks), 'reports': reports,
            'scope': '检索评测；不是答案准确率。向量已统一预热，检索耗时包含缓存向量读取，不含预热与答案生成；pgvector 检索包含数据库查询。内置题集仅为开发样例。'}
