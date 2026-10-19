"""Tool calling checks run without PostgreSQL, Redis, or live model credentials."""
import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from studio import game, game_tools


def call(arguments='{"query":"礼包库存"}', name='search_knowledge'):
    return {'id': 'call_1', 'type': 'function', 'function': {'name': name, 'arguments': arguments}}


def gateway(monkeypatch, calls):
    requests = []
    real_client = httpx.AsyncClient
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {
            'role': 'assistant', 'content': None, 'reasoning_content': 'plan', 'tool_calls': calls}}]})
    monkeypatch.setattr(game_tools.httpx, 'AsyncClient', lambda **kwargs: real_client(
        transport=httpx.MockTransport(handler), **kwargs))
    return requests


CONFIG = {'base_url': 'https://example.invalid/v1', 'model': 'test', 'key': ''}


def test_tool_protocol(monkeypatch):
    requests = gateway(monkeypatch, [call()])
    assistant, call_id, query = asyncio.run(game_tools.plan_search(CONFIG, [{'role': 'user', 'content': '礼包'}]))
    assert requests[0]['tools'][0]['function']['name'] == 'search_knowledge'
    assert query == '礼包库存'
    assert assistant['reasoning_content'] == 'plan'
    result = game_tools.tool_result(call_id, [{'id': 'doc:0', 'content': '库存'}])
    assert result['tool_call_id'] == assistant['tool_calls'][0]['id']
    assert json.loads(result['content'])['sources'][0]['citation'] == 1


@pytest.mark.parametrize('calls', [[], [call(), call()], [call(name='delete_document')],
    [call('not json')], [call('{"query":" "}')], [call('{"query":123}')],
    [call('{"query":"礼包","sql":"DROP TABLE documents"}')]])
def test_invalid_calls_rejected(monkeypatch, calls):
    gateway(monkeypatch, calls)
    with pytest.raises(RuntimeError, match='有效'):
        asyncio.run(game_tools.plan_search(CONFIG, []))


@pytest.mark.parametrize('has_sources', [True, False])
@pytest.mark.parametrize('tool_calling', [True, False])
def test_chat_tool_roundtrip(monkeypatch, has_sources, tool_calling):
    sources = [{'id': 'gift:0', 'title': '礼包', 'content': '检查库存'}] if has_sources else []
    class Repo:
        saved = None
        unlocked = False
        def initialize(self, seeds): pass
        def conversation(self, *args): return {}
        def lock(self, *args): return 'lock'
        def start(self, *args): return {'id': 'turn'}, False
        def context(self, *args): return []
        def search(self, query):
            assert query == '礼包库存'
            return sources
        def finish(self, *args):
            self.saved = args
            return True
        def unlock(self, *args): self.unlocked = True
        def close(self): pass
    repo = Repo()
    monkeypatch.setattr(game, 'GameStorage', lambda: repo)
    monkeypatch.setattr(game, 'model_config', lambda: CONFIG)
    gateway(monkeypatch, [call()])
    seen = []
    async def model(config, messages):
        seen.extend(messages)
        yield '检查库存。[1]'
    monkeypatch.setattr(game, 'model_tokens', model)
    app = FastAPI()
    app.include_router(game.create_game_router())
    with TestClient(app) as client:
        response = client.post('/api/game/chat', json={'conversation_id': str(uuid4()),
            'request_id': str(uuid4()), 'message': '礼包库存', 'tool_calling': tool_calling})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert [e['type'] for e in events if e['type'].startswith('tool_')] == (['tool_call', 'tool_result'] if tool_calling else [])
    if tool_calling:
        assert next(e for e in events if e['type'] == 'tool_result')['count'] == len(sources)
    assert events[-1]['type'] == 'done'
    assert repo.saved[1] == 'completed' and repo.unlocked
    if has_sources:
        assert '检查库存' in seen[0]['content']
        if tool_calling:
            assert seen[-2]['role'] == 'assistant'
            assert seen[-1]['role'] == 'tool' and seen[-1]['tool_call_id'] == 'call_1'
        else:
            assert seen[-1]['role'] == 'user'
    else:
        assert seen == []
        assert '暂无足够依据' in repo.saved[2]
