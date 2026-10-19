import asyncio
import json
import os
import uuid

import psycopg
import pytest
from psycopg import sql
from redis import Redis

import httpx
from fastapi.testclient import TestClient

from studio.main import create_app
from studio import game


@pytest.fixture(autouse=True)
def isolated_storage(monkeypatch):
    url = os.getenv('TEST_GAME_DATABASE_URL', 'postgresql://localhost/game_ops')
    redis_url = os.getenv('TEST_GAME_REDIS_URL', 'redis://127.0.0.1:6379/0')
    schema = 'test_game_' + uuid.uuid4().hex
    try:
        with psycopg.connect(url, connect_timeout=2):
            pass
        redis = Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        redis.ping()
    except Exception:
        if os.getenv('REQUIRE_GAME_STORAGE_TESTS') == '1':
            pytest.fail('Required PostgreSQL/Redis test services are unavailable')
        pytest.skip('Storage integration tests require local PostgreSQL and Redis')
    monkeypatch.setenv('GAME_DATABASE_URL', url)
    monkeypatch.setenv('GAME_REDIS_URL', redis_url)
    monkeypatch.setenv('GAME_DB_SCHEMA', schema)
    monkeypatch.setenv('GAME_REDIS_PREFIX', 'test-game')
    monkeypatch.setenv('GAME_OWNER_ID', 'test-owner')
    yield
    with psycopg.connect(url, autocommit=True) as db:
        db.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))
    for key in redis.scan_iter(match='test-game:' + schema + ':*'):
        redis.delete(key)
    redis.close()


def new_conversation(client):
    response = client.post('/api/game/conversations')
    assert response.status_code == 201, response.text
    return response.json()['id']


def ask(client, conversation_id, question, request_id=None):
    return client.post('/api/game/chat', json={'conversation_id': conversation_id,
        'request_id': request_id or str(uuid.uuid4()), 'message': question})


def events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]


def configured(monkeypatch):
    monkeypatch.setenv('GAME_LLM_BASE_URL', 'https://example.invalid/v1')
    monkeypatch.setenv('GAME_LLM_MODEL', 'existing-model')


def test_missing_config_and_document_lifecycle(tmp_path, monkeypatch):
    monkeypatch.delenv('GAME_LLM_BASE_URL', raising=False)
    monkeypatch.delenv('GAME_LLM_MODEL', raising=False)
    with TestClient(create_app(tmp_path / 'studio.db')) as client:
        assert client.get('/api/game/status').json()['configured'] is False
        assert ask(client, new_conversation(client), '礼包').status_code == 503
        assert client.post('/api/game/knowledge', json={'title': ' ', 'content': ' '}).status_code == 422
        doc = client.post('/api/game/knowledge', json={'title': '内部说明', 'content': '金色海豚配置需要审核。'})
        assert doc.status_code == 201
        assert any(d['title'] == '内部说明' for d in client.get('/api/game/knowledge').json())
        assert client.delete('/api/game/knowledge/' + doc.json()['id']).status_code == 200
        assert client.delete('/api/game/knowledge/' + doc.json()['id']).status_code == 404


def test_retrieval_stream_and_followup(tmp_path, monkeypatch):
    configured(monkeypatch)
    captured = []
    async def fake(config, messages):
        captured.extend(messages)
        yield '检查礼包库存'
        yield '和有效期。[1]'
    monkeypatch.setattr(game, 'model_tokens', fake)
    with TestClient(create_app(tmp_path / 'studio.db')) as client:
        cid = new_conversation(client)
        ask(client, cid, '礼包领取失败')
        captured.clear()
        response = ask(client, cid, '还需要检查什么？')
        data = events(response)
        assert response.headers['content-type'].startswith('text/event-stream')
        assert next(e for e in data if e['type'] == 'sources')['sources'][0]['title'].startswith('【示例】礼包')
        assert ''.join(e['text'] for e in data if e['type'] == 'token') == '检查礼包库存和有效期。[1]'
        assert data[-1]['type'] == 'done'
        assert captured[-1]['content'] == '还需要检查什么？'
        assert '不可信数据' in captured[0]['content']
        assert len(captured) == 4


def test_no_evidence_and_model_failure(tmp_path, monkeypatch):
    configured(monkeypatch)
    async def fail(config, messages):
        raise httpx.ConnectError('secret upstream details')
        yield ''
    monkeypatch.setattr(game, 'model_tokens', fail)
    with TestClient(create_app(tmp_path / 'studio.db')) as client:
        cid = new_conversation(client)
        unknown = events(ask(client, cid, 'xyzzyquux'))
        assert unknown[-1]['type'] == 'done'
        assert '暂无足够依据' in unknown[-2]['text']
        failed = events(ask(client, cid, '礼包领取失败'))
        assert failed[-1]['type'] == 'error'
        assert 'secret' not in str(failed)


def test_gateway_protocol(monkeypatch):
    real_client = httpx.AsyncClient
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        assert str(request.url) == 'https://example.invalid/v1/chat/completions'
        assert request.headers['Authorization'] == 'Bearer test-only'
        return httpx.Response(200, text=': ping\n\ndata: {"choices":[{"delta":{"content":"你好"}}]}\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(game.httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    async def collect():
        return [x async for x in game.model_tokens({'base_url': 'https://example.invalid/v1', 'model': 'existing', 'key': 'test-only'}, [{'role': 'user', 'content': '你好'}])]
    assert asyncio.run(collect()) == ['你好']
    assert seen[0]['stream'] is True


def test_gateway_truncation(monkeypatch):
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text='data: {"choices": [{"delta": {"content": "partial"}}]}\n\n'))
    monkeypatch.setattr(game.httpx, 'AsyncClient', lambda **kwargs: real_client(transport=transport, **kwargs))
    async def collect():
        try:
            return [x async for x in game.model_tokens({'base_url': 'https://example.invalid/v1', 'model': 'existing', 'key': ''}, [])]
        except RuntimeError as e:
            assert '提前结束' in str(e)
    assert asyncio.run(collect()) is None


def test_deleted_seeds_do_not_return_after_restart(tmp_path):
    path = tmp_path / 'studio.db'
    with TestClient(create_app(path)) as client:
        for doc in client.get('/api/game/knowledge').json():
            assert client.delete('/api/game/knowledge/' + doc['id']).status_code == 200
    with TestClient(create_app(path)) as client:
        assert client.get('/api/game/knowledge').json() == []


def test_persistence_replay_and_delete(tmp_path, monkeypatch):
    configured(monkeypatch)
    calls = []
    async def fake(config, messages):
        calls.append(messages)
        yield '确认库存。[1]'
    monkeypatch.setattr(game, 'model_tokens', fake)
    path = tmp_path / 'studio.db'
    rid = str(uuid.uuid4())
    with TestClient(create_app(path)) as client:
        cid = new_conversation(client)
        assert events(ask(client, cid, '礼包领取失败', rid))[-1]['type'] == 'done'
        assert events(ask(client, cid, '礼包领取失败', rid))[-1]['type'] == 'done'
        assert len(calls) == 1
        assert ask(client, cid, '另一个问题', rid).status_code == 409
    with TestClient(create_app(path)) as client:
        messages = client.get('/api/game/conversations/' + cid).json()['messages']
        assert len(messages) == 2
        assert messages[-1]['complete']
        assert messages[-1]['content'] == '确认库存。[1]'
        assert messages[-1]['sources']
        assert client.delete('/api/game/conversations/' + cid).status_code == 200
        assert client.get('/api/game/conversations/' + cid).status_code == 404


def test_owner_and_import_idempotency(tmp_path, monkeypatch):
    with TestClient(create_app(tmp_path / 'studio.db')) as client:
        payload = {'id': 'browser-old-session', 'title': '旧咨询', 'messages': [
            {'role': 'user', 'content': '礼包库存'},
            {'role': 'assistant', 'content': '检查库存', 'complete': True}]}
        assert client.post('/api/game/conversations/import', json=payload).json()['imported']
        assert not client.post('/api/game/conversations/import', json=payload).json()['imported']
        rows = client.get('/api/game/conversations').json()
        assert len(rows) == 1
        assert len(client.get('/api/game/conversations/' + rows[0]['id']).json()['messages']) == 2
        monkeypatch.setenv('GAME_OWNER_ID', 'another-owner')
        assert client.get('/api/game/conversations').json() == []
        assert client.get('/api/game/conversations/' + rows[0]['id']).status_code == 404
        assert client.delete('/api/game/conversations/' + rows[0]['id']).status_code == 404


def test_cache_version_lock_and_failed_history(monkeypatch):
    from studio.game_storage import GameStorage
    from fastapi import HTTPException
    from redis import RedisError
    repo = GameStorage()
    repo.initialize(game.SEEDS)
    try:
        cid = repo.new_conversation('owner')['id']
        token = repo.lock(cid)
        with pytest.raises(HTTPException) as busy:
            repo.lock(cid)
        assert busy.value.status_code == 409
        repo.unlock(cid, 'wrong-token')
        assert repo.redis.get(repo.prefix + 'lock:' + str(cid)) == token
        repo.unlock(cid, token)
        first, _ = repo.start('owner', cid, uuid.uuid4(), '礼包库存')
        with pytest.raises(HTTPException):
            repo.start('owner', cid, uuid.uuid4(), '并发')
        repo.finish(first['id'], 'completed', '检查库存', [])
        assert repo.context('owner', cid)[0][1]['content'] == '检查库存'
        assert list(repo.redis.scan_iter(match=repo.prefix+'context:*'))
        second, _ = repo.start('owner', cid, uuid.uuid4(), '失败问题')
        repo.finish(second['id'], 'failed', '不完整', [], 'timeout')
        assert len(repo.context('owner', cid)) == 1
        doc_id = repo.add_document('唯一知识', 'uniqueknowledgezebra')
        assert repo.search('uniqueknowledgezebra')[0]['id'].startswith(doc_id)
        repo.delete_document(doc_id)
        assert repo.search('uniqueknowledgezebra') == []
        monkeypatch.setattr(repo.redis, 'get', lambda *a, **kw: (_ for _ in ()).throw(RedisError('offline')))
        assert len(repo.context('owner', cid)) == 1
        monkeypatch.setattr(repo.redis, 'set', lambda *a, **kw: (_ for _ in ()).throw(RedisError('offline')))
        with pytest.raises(HTTPException) as offline:
            repo.lock(cid)
        assert offline.value.status_code == 503
    finally:
        repo.close()


def test_expired_generation_recovers(monkeypatch):
    from studio.game_storage import GameStorage
    repo = GameStorage()
    repo.initialize([])
    try:
        cid = repo.new_conversation('owner')['id']
        turn, _ = repo.start('owner', cid, uuid.uuid4(), '旧请求')
        with repo.connection() as db:
            db.execute("UPDATE turns SET deadline=now()-interval '1 second' WHERE id=%s", (turn['id'],))
        messages = repo.conversation('owner', cid)['messages']
        assert messages[-1]['status'] == 'failed'
        repo.start('owner', cid, uuid.uuid4(), '新请求')
    finally:
        repo.close()


def test_disconnect_persists_partial_answer_and_releases_lock(tmp_path, monkeypatch):
    configured(monkeypatch)
    async def slow_model(config, messages):
        yield 'partial answer'
        await asyncio.sleep(60)
        yield 'should not arrive'
    monkeypatch.setattr(game, 'model_tokens', slow_model)
    app = create_app(tmp_path / 'studio.db')
    with TestClient(app) as client:
        cid = new_conversation(client)
        payload = json.dumps({'conversation_id': cid, 'request_id': str(uuid.uuid4()), 'message': '礼包领取失败'}).encode()
        async def disconnect_after_token():
            sent = False
            token_received = asyncio.Event()
            async def receive():
                nonlocal sent
                if not sent:
                    sent = True
                    return {'type': 'http.request', 'body': payload, 'more_body': False}
                await token_received.wait()
                return {'type': 'http.disconnect'}
            async def send(message):
                if b'partial answer' in message.get('body', b''):
                    token_received.set()
            scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
                     'method': 'POST', 'scheme': 'http', 'path': '/api/game/chat',
                     'raw_path': b'/api/game/chat', 'query_string': b'', 'root_path': '',
                     'headers': [(b'content-type', b'application/json')],
                     'client': ('127.0.0.1', 1234), 'server': ('testserver', 80)}
            await asyncio.wait_for(app(scope, receive, send), timeout=5)
        asyncio.run(disconnect_after_token())
        answer = client.get('/api/game/conversations/' + cid).json()['messages'][-1]
        assert answer['status'] == 'cancelled'
        assert answer['content'] == 'partial answer'
        from studio.game_storage import GameStorage
        repo = GameStorage()
        try:
            assert repo.redis.get(repo.prefix + 'lock:' + cid) is None
        finally:
            repo.close()


def test_retrieval_cache_revision_and_strategy_isolation(tmp_path):
    with TestClient(create_app(tmp_path / 'studio.db')) as client:
        endpoint = '/api/game/retrieval/search'
        body = {'query': '翠玉彗星', 'top_k': 1}
        before = client.post(endpoint, json=body).json()
        assert before['sources'] == []
        assert client.post(endpoint, json=body).json()['trace']['cache_hit'] is True
        doc = client.post('/api/game/knowledge', json={'title': '翠玉彗星', 'content': '翠玉彗星唯一测试资料'}).json()
        after = client.post(endpoint, json=body).json()
        assert after['trace']['revision'] > before['trace']['revision']
        assert after['trace']['cache_hit'] is False
        assert after['sources'][0]['document_id'] == doc['id']
        candidate = client.post(endpoint, json=dict(body, strategy='expanded_bm25')).json()
        assert candidate['trace']['cache_hit'] is False
        assert candidate['trace']['strategy'] == 'expanded_bm25'
        client.delete('/api/game/knowledge/' + doc['id'])
        assert client.post(endpoint, json=body).json()['sources'] == []


def test_vector_cache_model_and_threshold_isolation(tmp_path, monkeypatch):
    from studio import game_embeddings
    class Vectors:
        identity = 'test-embedding-a'
        def encode(self, texts, kind='document'):
            return [[1., 0.] for _ in texts]
    backend = Vectors()
    monkeypatch.setattr(game_embeddings, 'get_embeddings', lambda: backend)
    with TestClient(create_app(tmp_path / 'studio.db')) as client:
        endpoint = '/api/game/retrieval/search'
        body = {'query': '向量模型隔离测试', 'strategy': 'vector', 'vector_backend': 'local'}
        result = client.post(endpoint, json=body).json()
        assert result['trace']['cache_hit'] is False
        assert client.post(endpoint, json=body).json()['trace']['cache_hit'] is True
        backend.identity = 'test-embedding-b'
        changed = client.post(endpoint, json=body).json()
        assert changed['trace']['cache_hit'] is False
        assert changed['trace']['embedding_model'] == backend.identity
        threshold = client.post(endpoint, json=dict(body, min_similarity=.8)).json()
        assert threshold['trace']['cache_hit'] is False
        doc = client.post('/api/game/knowledge', json={'title': '向量新增资料', 'content': '测试知识更新'}).json()
        refreshed = client.post(endpoint, json=body).json()
        assert refreshed['trace']['revision'] > changed['trace']['revision']
        client.delete('/api/game/knowledge/' + doc['id'])
        assert all(s['document_id'] != doc['id'] for s in client.post(endpoint, json=body).json()['sources'])


@pytest.fixture
def vector_repository():
    from pathlib import Path
    from studio.game_storage import GameStorage
    repo = GameStorage()
    repo.initialize([])
    with repo.connection() as db:
        db.execute('CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public')
        db.execute((Path(game.__file__).parent / 'migrations/002_game_vectors.sql').read_text())
    yield repo
    repo.close()


class PgTestEmbeddings:
    identity = 'pgvector-test-model-v1'
    calls = 0

    def encode(self, texts, kind='document'):
        self.calls += 1
        return [([1., 0.] if kind == 'query' or '礼包' in text else [0., 1.]) + [0.] * 382 for text in texts]


def test_pgvector_matches_local_and_reuses_snapshot(vector_repository):
    from studio.game_retrieval import RetrievalIndex, RetrievalOptions
    from studio.game_pgvector import PgVectorStore
    documents = [{'id': 'gift', 'title': '礼包', 'content': '领取检查库存'},
                 {'id': 'banner', 'title': 'Banner', 'content': '检查素材'}]
    embeddings = PgTestEmbeddings()
    store = PgVectorStore(vector_repository)
    local = RetrievalIndex(documents, embeddings)
    postgres = RetrievalIndex(documents, embeddings, store)
    options = RetrievalOptions(strategy='vector', min_similarity=.5)
    actual = postgres.search('礼包', options)
    expected = local.search('礼包', options)
    assert [s['id'] for s in actual['sources']] == [s['id'] for s in expected['sources']]
    assert actual['sources'][0]['score'] == pytest.approx(expected['sources'][0]['score'])
    assert actual['trace']['vector_backend'] == 'pgvector'
    calls = embeddings.calls
    assert store.ensure(postgres, embeddings) == postgres.vector_set_id
    assert embeddings.calls == calls
    with vector_repository.connection() as db:
        assert db.execute('SELECT count(*) AS n FROM rag_vectors').fetchone()['n'] == 2
    ann = postgres.search('礼包', options.model_copy(update={'vector_search_mode': 'hnsw'}))
    assert ann['sources'][0]['document_id'] == 'gift'
    assert ann['trace']['vector_search_mode'] == 'hnsw'


def test_pgvector_corpus_model_isolation_and_atomic_failure(vector_repository):
    from studio.game_retrieval import RetrievalIndex, RetrievalOptions
    from studio.game_pgvector import PgVectorStore, PgVectorUnavailable
    store = PgVectorStore(vector_repository)
    embeddings = PgTestEmbeddings()
    docs = [{'id': 'a', 'title': '礼包', 'content': '旧规则'}, {'id': 'b', 'title': '其他', 'content': '保留'}]
    old = RetrievalIndex(docs, embeddings, store)
    old.prepare_vectors()
    updated = RetrievalIndex(docs[1:], embeddings, store)
    assert updated.search('礼包', RetrievalOptions(strategy='vector', min_similarity=.5))['sources'] == []
    assert old.vector_set_id != updated.vector_set_id
    embeddings.identity = 'pgvector-test-model-v2'
    rebuilt = RetrievalIndex(docs, embeddings, store)
    rebuilt.prepare_vectors()
    assert rebuilt.vector_set_id != old.vector_set_id
    assert RetrievalIndex([], embeddings, store).search('礼包', RetrievalOptions(strategy='vector'))['sources'] == []
    class Broken(PgTestEmbeddings):
        identity = 'broken-model'
        def encode(self, texts, kind='document'):
            return [[1., 0.] for _ in texts]
    with pytest.raises(PgVectorUnavailable, match='384'):
        RetrievalIndex(docs, Broken(), store).prepare_vectors()
    with vector_repository.connection() as db:
        assert db.execute("SELECT count(*) AS n FROM rag_vector_sets WHERE model_identity='broken-model'").fetchone()['n'] == 0


def test_pgvector_eval_and_hnsw_index_plan(vector_repository):
    from studio.game_rag_eval import EvalRequest, evaluate
    from studio.game_pgvector import PgVectorStore, vector_literal
    from studio.game_retrieval import RetrievalIndex
    documents = [{'id': str(i), 'title': '礼包' if i == 0 else '其他', 'content': str(i)} for i in range(80)]
    embeddings = PgTestEmbeddings()
    store = PgVectorStore(vector_repository)
    index = RetrievalIndex(documents, embeddings, store)
    index.prepare_vectors()
    query = vector_literal(embeddings.encode(['礼包'], kind='query')[0])
    with vector_repository.connection() as db:
        db.execute('SET LOCAL enable_seqscan=off')
        db.execute('SET LOCAL enable_sort=off')
        plan = db.execute('''EXPLAIN (FORMAT JSON) SELECT chunk_id FROM rag_vectors
            WHERE set_id=%s ORDER BY embedding OPERATOR(public.<=>) %s::public.vector LIMIT 4''',
                          (index.vector_set_id, query)).fetchone()
        assert 'rag_vectors_cosine_hnsw' in json.dumps(plan)
    report = evaluate(EvalRequest(corpus='current', vector_backend='pgvector', strategies=['vector','hybrid'],
                                 cases=[{'id':'gift','query':'礼包','relevant':{'0':3}}]),
                      documents, revision=9, embeddings=embeddings, vector_store=store)
    assert report['reports'][0]['summary']['recall'] == 1
    assert report['reports'][1]['cases'][0]['trace']['vector_backend'] == 'pgvector'


def test_missing_pgvector_migration_is_explicit_503(tmp_path, monkeypatch):
    from studio import game_embeddings
    monkeypatch.setattr(game_embeddings, 'get_embeddings', lambda: PgTestEmbeddings())
    with TestClient(create_app(tmp_path / 'studio.db')) as client:
        response = client.post('/api/game/retrieval/search', json={
            'query': '礼包', 'strategy': 'vector', 'vector_backend': 'pgvector'})
        assert response.status_code == 503
        assert 'migrate:vector' in response.json()['detail']
        local = client.post('/api/game/retrieval/search', json={
            'query': '礼包', 'strategy': 'vector', 'vector_backend': 'local'})
        assert local.status_code == 200
        assert local.json()['trace']['vector_backend'] == 'local'
