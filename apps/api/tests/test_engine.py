import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient
from studio.main import create_app
from studio.runtime import pack_context
from studio.sandbox import calculate
from studio.store import Store
from studio.knowledge import Knowledge


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / 'studio.db')) as client:
        yield client


def payload(question='计算 128 * 16', **extra):
    return dict(messages=[{'role': 'user', 'content': question}], session_id='test', **extra)


def wait_run(client, run_id):
    for _ in range(100):
        result = client.get('/api/runs/' + run_id).json()
        if result['status'] not in ('queued', 'running'):
            return result
        time.sleep(.03)
    pytest.fail('worker did not finish')


@pytest.mark.parametrize('expression', ['__import__("os")', '(1).__class__', '2**99999', 'True', '[1]', '1/0', '9'*201, '1e300'])
def test_sandbox_denies(expression):
    with pytest.raises((ValueError, SyntaxError, ZeroDivisionError)):
        calculate(expression)


def test_sandbox_arithmetic():
    assert calculate('(128 + 2) * 16') == '2080'
    assert calculate('-2 * 3') == '-6'


def test_context_budget():
    messages = [{'role': 'user', 'content': 'x'*900}, {'role': 'user', 'content': 'current'}]
    packed = pack_context(messages, ['memory'], 30)
    assert packed['current'] == 'current'
    assert packed['used_chars'] <= 30
    assert packed['dropped_messages'] == 1
    with pytest.raises(ValueError):
        pack_context(messages, [], 2)


def test_rag_cache_invalidation(tmp_path):
    knowledge = Knowledge(Store(tmp_path / 'db'))
    assert knowledge.search('RAG')[0]['id'].startswith('rag:')
    assert knowledge.search('specialuniqueword') == []
    knowledge.add('custom', 'specialuniqueword ' + 'a' * 500)
    hits = knowledge.search('specialuniqueword')
    assert hits and len(hits[0]['content']) <= 360


def test_chat_sse(client):
    response = client.post('/api/chat', json=payload())
    assert response.status_code == 200
    events = [json.loads(frame[6:]) for frame in response.text.strip().split('\n\n')]
    assert ''.join(e['text'] for e in events if e['type'] == 'token') == '2048'
    assert events[-1]['type'] == 'done'
    assert client.get('/api/runs/' + response.headers['x-run-id']).json()['status'] == 'completed'


def test_validation(client):
    assert client.post('/api/chat', json={'messages': []}).status_code == 422
    assert client.post('/api/runs', json=payload(' ')).status_code == 422
    assert client.post('/api/runs', json=payload(mode='invalid')).status_code == 422
    assert client.post('/api/runs', content='x' * 220001).status_code == 413


def test_failure_retry_feedback(client):
    run_id = client.post('/api/runs', json=payload(fault='tool_error')).json()['id']
    assert wait_run(client, run_id)['status'] == 'failed'
    retry_id = client.post('/api/runs/' + run_id + '/retry').json()['id']
    assert wait_run(client, retry_id)['answer'] == '2048'
    assert client.post('/api/runs/' + retry_id + '/feedback', json={'score': -1}).status_code == 200
    assert len(client.get('/api/improvements').json()) == 2
    assert client.post('/api/runs/missing/cancel').status_code == 404


def test_cancel_queued(client):
    run_id = client.post('/api/runs', json=payload()).json()['id']
    assert client.post('/api/runs/' + run_id + '/cancel').status_code == 200
    time.sleep(.1)
    assert client.get('/api/runs/' + run_id).json()['status'] == 'cancelled'


def test_memory_isolation_and_delete(client):
    response = client.post('/api/chat', json=payload('记住：我喜欢 Python'))
    assert response.status_code == 200
    assert client.get('/api/memory/test').json() == ['我喜欢 Python']
    assert client.get('/api/memory/other').json() == []
    client.delete('/api/memory/test')
    assert client.get('/api/memory/test').json() == []


def test_multirole_and_budget(client):
    result = client.post('/api/chat', json=payload('RAG 计算 2 * 3', mode='multi')).text
    assert 'Reviewer' in result and 'calculator' in result and 'search_knowledge' in result
    run_id = client.post('/api/runs', json=payload('RAG 计算 2 * 3', mode='multi', max_steps=1)).json()['id']
    assert wait_run(client, run_id)['status'] == 'failed'


def test_mcp(client):
    base = {'jsonrpc': '2.0', 'id': 1}
    tools = client.post('/api/mcp', json=dict(base, method='tools/list')).json()
    assert tools['result']['tools'][0]['name'] == 'calculator'
    result = client.post('/api/mcp', json=dict(base, method='tools/call', params={'name': 'calculator', 'arguments': {'expression': '128*16'}})).json()
    assert result['result']['content'][0]['text'] == '2048'
    assert client.post('/api/mcp', json=[]).json()['error']['code'] == -32600
    result = client.post('/api/mcp', json=dict(base, method='tools/call', params={'name': 'calculator', 'arguments': {'expression': '__import__("os")'}})).json()
    assert result['result']['isError']


def test_evaluation(client):
    result = client.post('/api/evaluations').json()
    assert result['candidate']['pass_rate'] == 1
    assert len(result['baseline']['cases']) == 4


def test_crash_recovery_and_persistence(tmp_path):
    path = tmp_path / 'db'
    store = Store(path)
    run_id = store.create(payload())
    assert store.claim()['id'] == run_id
    store.remember('test', 'persisted')
    with TestClient(create_app(path)) as client:
        assert wait_run(client, run_id)['status'] == 'completed'
        assert client.get('/api/memory/test').json() == ['persisted']


def test_queue_capacity_and_claim(tmp_path):
    store = Store(tmp_path / 'db')
    store.create(payload())
    assert store.claim() is not None
    assert store.claim() is None


def test_parenthesized_expression_over_http(client):
    result = client.post('/api/chat', json=payload('计算 (128 + 2) * 16')).text
    assert '2080' in result and '"type": "done"' in result


def test_react_reenters_model(client):
    calls = []
    model = client.app.state.runtime.model
    original = model.next_action
    def tracked(question, observations):
        calls.append(len(observations))
        return original(question, observations)
    model.next_action = tracked
    result = client.post('/api/chat', json=payload('RAG 并计算 2 * 3')).text
    assert calls == [0, 1, 2]
    assert 'search_knowledge' in result and 'calculator' in result


def test_capacity_returns_429(tmp_path):
    app = create_app(tmp_path / 'db')
    # Without lifespan, worker does not drain the queue during capacity verification.
    client = TestClient(app)
    for _ in range(32):
        assert client.post('/api/runs', json=payload()).status_code == 202
    assert client.post('/api/runs', json=payload()).status_code == 429


def test_cancel_running_preserves_terminal_state(tmp_path):
    store = Store(tmp_path / 'db')
    run_id = store.create(payload())
    store.claim()
    store.finish(run_id, 'cancelled')
    store.finish(run_id, 'completed', answer='must not overwrite')
    assert store.get(run_id)['status'] == 'cancelled'
    assert store.get(run_id)['answer'] == ''


def test_skill_discovery(client):
    assert any(skill['name'] == 'incident-review' for skill in client.get('/api/skills').json())
