"""Provider-neutral messages. This demo never makes model/network requests."""
import json
from typing import Protocol


TOOLS = [
    {'name': 'get_order', 'description': '查询当前演示用户的订单',
     'parameters': {'type': 'object', 'properties': {'order_id': {'type': 'string'}},
                    'required': ['order_id'], 'additionalProperties': False}},
    {'name': 'search_policy', 'description': '检索本地演示退货政策',
     'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}},
                    'required': ['query'], 'additionalProperties': False}},
    {'name': 'submit_return', 'description': '申请退货，需要用户审批；运行时校验资格',
     'parameters': {'type': 'object', 'properties': {
         'order_id': {'type': 'string'}, 'reason': {'type': 'string'}},
         'required': ['order_id', 'reason'], 'additionalProperties': False}},
]


class Model(Protocol):
    def generate(self, messages: list, tools: list) -> dict:
        """Return assistant {content, tool_calls:[{id,name,arguments}]}."""
        ...


class MockModel:
    """Deterministic decisions based on tool observations, not a real LLM."""

    def generate(self, messages, tools):
        request = json.loads(messages[1]['content'])
        results = {m['name']: json.loads(m['content']) for m in messages if m['role'] == 'tool'}
        if 'get_order' not in results:
            return self.call('get_order', {'order_id': request['order_id']})
        if not results['get_order']['ok']:
            return self.final('无法查询该订单：' + results['get_order']['error'])
        if 'search_policy' not in results:
            return self.call('search_policy', {'query': '签收 7 天 内 未使用 退货'})
        if not results['search_policy']['ok']:
            return self.final('未获得政策证据，无法继续申请。')
        if not results['get_order']['data']['eligible']:
            return self.final('该订单不符合演示政策的退货条件。[returns-v1]')
        if not request['reason'].strip():
            return {'role': 'assistant', 'content': '请补充退货原因。',
                    'tool_calls': [], 'needs_input': True}
        if 'submit_return' not in results:
            return self.call('submit_return', {'order_id': request['order_id'], 'reason': request['reason']})
        result = results['submit_return']
        if result['ok']:
            return self.final('退货申请已创建：' + result['data']['application_id'] + '。[returns-v1]')
        return self.final('申请未完成：' + result['error'])

    @staticmethod
    def call(name, arguments):
        return {'role': 'assistant', 'content': '', 'tool_calls': [
            {'id': 'call_' + name, 'name': name, 'arguments': arguments}]}

    @staticmethod
    def final(content):
        return {'role': 'assistant', 'content': content, 'tool_calls': []}
