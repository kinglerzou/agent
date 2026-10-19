import json
import pytest
from fastapi.testclient import TestClient

from studio.main import create_app
from studio.runtime_demo import Conflict, DemoRuntime
from studio.runtime_demo.model import MockModel


@pytest.fixture
def runtime(tmp_path):
    return DemoRuntime(tmp_path / 'demo.sqlite3')


def advance(runtime, run):
    for _ in range(20):
        if run['status'] != 'ready':
            return run
        run = runtime.mutate(run['id'], 'step', version=run['version'])
    pytest.fail('run did not stop')


def test_loop_approval_restart_and_idempotent_event(runtime):
    run = advance(runtime, runtime.create(reason='不合适'))
    assert run['status'] == 'waiting_approval'
    assert [m['name'] for m in run['messages'] if m['role'] == 'tool'] == ['get_order', 'search_policy']
    with runtime.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM demo_returns').fetchone()[0] == 0
    restarted = DemoRuntime(runtime.path)
    approved = restarted.mutate(run['id'], 'approve', version=run['version'], event_id='approval-1')
    duplicated = restarted.mutate(run['id'], 'approve', version=run['version'], event_id='approval-1')
    assert duplicated == approved
    final = advance(restarted, approved)
    assert final['status'] == 'completed'
    assert 'RET-' in final['answer']
    assert final['rounds'] == 4
    calls = [call['id'] for m in final['messages'] for call in m.get('tool_calls', [])]
    results = [m['tool_call_id'] for m in final['messages'] if m['role'] == 'tool']
    assert calls == results
    second = advance(runtime, runtime.create(reason='第二次申请'))
    second = advance(runtime, runtime.mutate(second['id'], 'approve'))
    assert second['status'] == 'completed'
    with runtime.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM demo_returns').fetchone()[0] == 1


def test_missing_input_and_pause_cancel(runtime):
    run = advance(runtime, runtime.create())
    assert run['status'] == 'waiting_input'
    run = runtime.mutate(run['id'], 'input', value='尺寸不合适')
    run = runtime.mutate(run['id'], 'pause')
    with pytest.raises(Conflict):
        runtime.mutate(run['id'], 'step')
    run = runtime.mutate(run['id'], 'resume')
    run = advance(runtime, run)
    assert run['pending']['arguments']['reason'] == '尺寸不合适'
    runtime.mutate(run['id'], 'cancel')
    with pytest.raises(Conflict):
        runtime.mutate(run['id'], 'approve')


def test_fault_recovery_stays_at_tool(runtime):
    run = advance(runtime, runtime.create(reason='测试', fault=True))
    assert run['status'] == 'failed'
    assert run['phase'] == 'tool'
    assert run['rounds'] == 1
    recovered = DemoRuntime(runtime.path)
    run = recovered.mutate(run['id'], 'retry')
    run = recovered.mutate(run['id'], 'step')
    assert run['rounds'] == 1
    assert run['messages'][-1]['role'] == 'tool'


@pytest.mark.parametrize('order', ['A124', 'B999'])
def test_ineligible_and_foreign_orders_never_write(runtime, order):
    run = advance(runtime, runtime.create(order_id=order, reason='测试'))
    assert run['status'] == 'completed'
    assert not any(e['type'] == 'approval_required' for e in run['events'])
    with runtime.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM demo_returns').fetchone()[0] == 0


def test_stale_event_and_api_validation(tmp_path):
    with TestClient(create_app(tmp_path / 'studio.sqlite3')) as client:
        assert client.get('/runtime-demo').status_code == 200
        assert client.post('/api/runtime-demo/runs', json={'reason': 'x' * 501}).status_code == 422
        run = client.post('/api/runtime-demo/runs', json={'reason': '测试'}).json()
        path = '/api/runtime-demo/runs/' + run['id'] + '/actions'
        assert client.post(path, json={'action': 'step', 'version': 0, 'event_id': 'one'}).status_code == 200
        assert client.post(path, json={'action': 'cancel', 'version': 0, 'event_id': 'two'}).status_code == 409
        assert client.get('/api/runtime-demo/runs/missing').status_code == 404


def test_unregistered_tool_rejected(runtime):
    class BadModel:
        def generate(self, messages, tools):
            return MockModel.call('shell', {'command': 'anything'})
    runtime.model = BadModel()
    run = advance(runtime, runtime.create())
    assert run['status'] == 'failed'
    assert '未注册' in run['error']


def test_approval_bound_to_exact_arguments(runtime):
    run = advance(runtime, runtime.create(reason='测试'))
    run = runtime.mutate(run['id'], 'approve')
    # Simulate a corrupted/stale plan after approval; runtime must not authorize it.
    run['pending']['arguments']['reason'] = '已更改的方案'
    with runtime.connect() as db:
        db.execute('UPDATE demo_runs SET state=? WHERE id=?', (json.dumps(run), run['id']))
    run = runtime.mutate(run['id'], 'step')
    assert run['status'] == 'failed'
    assert '审批' in run['error']


def test_round_budget(runtime):
    class LoopModel:
        def generate(self, messages, tools):
            result = MockModel.call('get_order', {'order_id': 'A123'})
            result['tool_calls'][0]['id'] = str(len(messages))
            return result
    runtime.model = LoopModel()
    run = advance(runtime, runtime.create())
    assert run['status'] == 'failed'
    assert run['rounds'] == 8
    with pytest.raises(Conflict):
        runtime.mutate(run['id'], 'retry')
