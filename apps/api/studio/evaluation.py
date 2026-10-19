"""Offline regression evaluation. Exercises the actual runtime, not canned scores."""
import time

CASES = [
    {'name': '算术工具', 'question': '计算 128 * 16', 'expected': '2048', 'tool': 'calculator'},
    {'name': 'RAG 引用', 'question': 'RAG 分块检索', 'expected': 'rag:0', 'tool': 'search_knowledge'},
    {'name': '上下文工程', 'question': '上下文工程', 'expected': 'memory:0', 'tool': 'search_knowledge'},
    {'name': '无证据拒答', 'question': 'zzzxxyy', 'expected': '没有匹配证据', 'tool': 'search_knowledge'},
]


async def evaluate(runtime, top_k):
    results = []
    for case in CASES:
        start = time.perf_counter()
        events = [e async for e in runtime.execute({
            'session_id': '__eval__', 'messages': [{'role': 'user', 'content': case['question']}],
            'top_k': top_k,
        })]
        answer = ''.join(e['text'] for e in events if e['type'] == 'token')
        tools = [e['name'] for e in events if e['type'] == 'tool_start']
        results.append(dict(case, answer=answer, passed=case['expected'] in answer and case['tool'] in tools,
                            latency_ms=round((time.perf_counter() - start) * 1000, 2)))
    return {'top_k': top_k, 'pass_rate': sum(r['passed'] for r in results) / len(results), 'cases': results}
