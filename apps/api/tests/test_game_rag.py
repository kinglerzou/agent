import math

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from studio.game_rag import attach_rag_routes
from studio.game_rag_eval import EvalRequest, evaluate, metrics
from studio.game_retrieval import RetrievalIndex, RetrievalOptions
from studio.knowledge import Knowledge


DOCS = [
    {'id': 'a', 'title': 'Banner', 'content': '首页 Banner 不展示请检查素材审核。'},
    {'id': 'b', 'title': '礼包', 'content': '礼包库存不足请等待补货。'},
]


def test_baseline_matches_existing_ranker():
    old = object.__new__(Knowledge)
    old.cache = {}
    old.documents = lambda: DOCS
    index = RetrievalIndex(DOCS)
    for query in ('Banner', '礼包库存不足', '审核', '火星天气'):
        actual = index.search(query)['sources']
        expected = old.search(query, 4)
        assert [r['id'] for r in actual] == [r['id'] for r in expected]
        assert [r['score'] for r in actual] == pytest.approx([r['score'] for r in expected], abs=.0001)


def test_expansion_and_versioned_trace():
    index = RetrievalIndex(DOCS)
    assert index.search('轮播图看不到')['sources'] == []
    result = index.search('轮播图看不到', RetrievalOptions(strategy='expanded_bm25'))
    assert result['sources'][0]['document_id'] == 'a'
    assert 'Banner' in result['trace']['expanded_query']
    assert result['sources'][0]['offset'] == 0
    assert result['sources'][0]['matched_terms']
    assert index.search('Banner', RetrievalOptions(min_score=100))['sources'] == []
    assert RetrievalIndex(list(reversed(DOCS))).corpus_hash == index.corpus_hash
    assert RetrievalIndex(DOCS[:1]).corpus_hash != index.corpus_hash
    assert RetrievalIndex([]).search('Banner')['sources'] == []


def test_metrics_rank_grades_duplicates_and_no_answer():
    sources = [{'document_id': key} for key in ('x', 'a', 'a', 'b')]
    result = metrics(sources, {'a': 3, 'b': 1}, 3)
    assert result['recall'] == .5
    assert result['mrr'] == .5
    assert result['ndcg'] == pytest.approx((7 / math.log2(3)) / (7 + 1 / math.log2(3)))
    assert result['retrieved_document_ids'] == ['x', 'a']
    assert metrics([], {}, 4)['false_positive'] is False
    assert metrics(sources, {}, 4)['false_positive'] is True
    assert metrics([], {}, 4)['recall'] is None
    assert metrics([], {'a': 3}, 4)['recall'] == 0


def test_evaluation_reproducibility_and_validation():
    request = EvalRequest()
    first, second = evaluate(request), evaluate(request)
    assert first['dataset_hash'] == second['dataset_hash']
    assert first['corpus_hash'] == second['corpus_hash']
    # Do not use synthetic near-perfect scores as a quality gate.
    assert first['reports'][0]['summary']['answerable_count'] == 10
    assert first['reports'][0]['summary']['unanswerable_count'] == 3
    with pytest.raises(ValueError, match='不存在'):
        evaluate(EvalRequest(corpus='current', cases=[{'id': 'a', 'query': 'x', 'relevant': {'missing': 3}}]), DOCS)
    for body in ({'corpus': 'current'}, {'top_k': 0}, {'min_score': float('nan')}, {'cases': []},
                 {'cases': [{'id': 'a', 'query': ' ', 'relevant': {}}]},
                 {'cases': [{'id': 'a', 'query': 'x', 'relevant': {'a': 4}}]}):
        with pytest.raises(ValidationError):
            EvalRequest(**body)
    negatives = evaluate(EvalRequest(cases=[{'id': 'x', 'query': 'unseen', 'relevant': {}}]))
    assert negatives['reports'][0]['summary']['recall'] is None


def test_api_fixture_independent_of_database_and_current_snapshot():
    class Repo:
        def knowledge_snapshot(self):
            return 7, DOCS

        def retrieve(self, query, options):
            return RetrievalIndex(DOCS).search(query, options)

    calls = []
    def repository():
        calls.append(True)
        return Repo()

    app = FastAPI()
    router = APIRouter(prefix='/api/game')
    attach_rag_routes(router, repository)
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get('/api/game/retrieval/dataset').status_code == 200
        assert client.post('/api/game/retrieval/evaluate', json={}).status_code == 200
        assert not calls
        response = client.post('/api/game/retrieval/search', json={'query': 'Banner'})
        assert response.json()['sources'][0]['document_id'] == 'a'
        assert client.post('/api/game/retrieval/search', json={'query': ' '}).status_code == 422
        response = client.post('/api/game/retrieval/evaluate', json={'corpus': 'current', 'cases': [
            {'id': 'banner', 'query': 'Banner', 'relevant': {'a': 3}}]})
        assert response.json()['revision'] == 7
        assert response.json()['reports'][0]['summary']['recall'] == 1
        response = client.post('/api/game/retrieval/evaluate', json={'corpus': 'current', 'cases': [
            {'id': 'missing', 'query': 'Banner', 'relevant': {'deleted': 3}}]})
        assert response.status_code == 422
