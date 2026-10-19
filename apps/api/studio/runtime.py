"""Bounded, observable mock Agent Loop and specialist handoffs."""
import asyncio
import re
from typing import Protocol
from .sandbox import calculate


class Model(Protocol):
    def plan(self, question: str) -> list: ...
    def next_action(self, question: str, observations: list): ...


class MockModel:
    def plan(self, question):
        expressions = re.findall(r'[\d().+*/%\s-]+', question)
        expression = next((part.strip() for part in expressions
                           if re.search(r'\d', part) and re.search(r'[+*/%-]', part)), None)
        if expression:
            actions = [('calculator', expression)]
            if any(word in question.lower() for word in ('rag', '上下文', '知识', '架构')):
                actions.insert(0, ('search_knowledge', question))
            return actions
        if question.startswith('记住：') or question.startswith('记住:'):
            return [('remember', question[3:].strip())]
        if '记住了什么' in question or '我的偏好' in question:
            return [('recall', '')]
        return [('search_knowledge', question)]

    def next_action(self, question, observations):
        # ReAct mock re-enters model decision after each tool observation.
        completed = {item['name'] for item in observations}
        return next((action for action in self.plan(question) if action[0] not in completed), None)


def pack_context(messages, memories, budget=4000):
    # Newest request always wins. No silent loss of the actual user task.
    current = messages[-1]['content']
    if len(current) > budget:
        raise ValueError('当前问题超过上下文预算')
    remaining = budget - len(current)
    facts = '\n'.join(memories)[:min(800, remaining)]
    remaining -= len(facts)
    history = []
    for message in reversed(messages[:-1]):
        if len(message['content']) > remaining:
            break
        history.insert(0, message)
        remaining -= len(message['content'])
    return {'current': current, 'memory': facts, 'history': history,
            'used_chars': budget - remaining, 'dropped_messages': len(messages) - 1 - len(history)}


class Runtime:
    def __init__(self, store, knowledge):
        self.store, self.knowledge = store, knowledge
        self.model = MockModel()

    async def execute(self, payload):
        session = payload['session_id']
        context = pack_context(payload['messages'], self.store.memories(session), payload.get('context_budget', 12000))
        question = context['current']
        yield {'type': 'status', 'message': f"上下文已装配 · {context['used_chars']} 字符 · 裁剪 {context['dropped_messages']} 条历史"}
        actions = self.model.plan(question)
        mode = payload.get('mode', 'react')
        if mode == 'plan':
            yield {'type': 'status', 'message': 'Planner → 计划：' + ' → '.join(a[0] for a in actions) + ' → 汇总 → 校验'}
        if mode == 'multi':
            yield {'type': 'status', 'message': 'Coordinator → Researcher：委派证据收集任务'}
            if not any(name == 'search_knowledge' for name, _ in actions):
                actions = [('search_knowledge', question)] + actions
        if len(actions) > payload.get('max_steps', 6):
            raise ValueError('工具步骤预算不足')
        outputs, sources = [], []
        observations = []
        step = 0
        while True:
            action = (self.model.next_action(question, observations) if mode == 'react'
                      else actions[step] if step < len(actions) else None)
            if action is None:
                break
            if step >= payload.get('max_steps', 6):
                raise ValueError('工具步骤预算不足')
            name, argument = action
            step += 1
            yield {'type': 'tool_start', 'name': name, 'input': {'value': argument}}
            await asyncio.sleep(.02)
            if payload.get('fault') == 'tool_error':
                raise RuntimeError('故障注入：工具不可用')
            if name == 'calculator':
                output = calculate(argument)
            elif name == 'remember':
                if not argument:
                    raise ValueError('记忆内容不能为空')
                self.store.remember(session, argument)
                output = '已记住：' + argument
            elif name == 'recall':
                output = context['memory'] or '当前会话没有长期记忆。使用「记住：偏好内容」保存。'
            else:
                sources = self.knowledge.search(argument, payload.get('top_k', 3))
                yield {'type': 'sources', 'sources': sources}
                output = '\n\n'.join(f"[{s['id']}] {s['title']}\n{s['content']}" for s in sources) or '知识库没有匹配证据；请导入相关文档或换个问题。'
            outputs.append(output)
            observations.append({'name': name, 'output': output})
            yield {'type': 'tool_end', 'name': name, 'output': output}
        if '上一条' in question:
            users = [m['content'] for m in context['history'] if m['role'] == 'user']
            outputs = [users[-1] if users else '当前上下文没有上一条用户消息。']
        if mode == 'multi':
            # Reviewer is a deterministic validation role, not another LLM.
            valid = bool(outputs) and all(s['content'] for s in sources)
            yield {'type': 'status', 'message': f"Researcher → Reviewer → Coordinator：证据结构校验{'通过' if valid else '失败'}（Mock 角色协作）"}
        answer = '\n\n'.join(outputs)
        for offset in range(0, len(answer), 36):
            yield {'type': 'token', 'text': answer[offset:offset + 36]}
            await asyncio.sleep(.01)
        yield {'type': 'done'}
