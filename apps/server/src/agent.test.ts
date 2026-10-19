import test from 'node:test';
import assert from 'node:assert/strict';
import type { AgentEvent } from '@studio/shared';
import { createApp } from './app.js';
import { calculate, runAgent } from './agent.js';
import { searchKnowledge } from './knowledge.js';

void test('检索只返回匹配文档，并按分数降序', () => {
  const result = searchKnowledge('RAG 向量数据库');

  assert.ok(result.some((d) => d.id === 'rag'));
  assert.equal(searchKnowledge('zzzzunknown').length, 0);
  assert.deepEqual(
    searchKnowledge('RAG').map((d) => d.id),
    ['rag'],
  );
  assert.ok(result.every((d, i) => i === 0 || result[i - 1].score >= d.score));
});
void test('计算器覆盖操作、零除和溢出', () => {
  assert.equal(calculate(128, 16, 'multiply'), 2048);
  assert.equal(calculate(3, 2, 'add'), 5);
  assert.equal(calculate(3, 2, 'subtract'), 1);
  assert.equal(calculate(3, 2, 'divide'), 1.5);
  assert.throws(() => calculate(1, 0, 'divide'));
  assert.throws(() => calculate(1e308, 1e308, 'multiply'));
});
void test('Mock 实际调用工具，发送有序事件且无需密钥', async () => {
  const events: AgentEvent[] = [];

  await runAgent(
    [{ role: 'user', content: '计算 128 * 16' }],
    (e) => events.push(e),
    new AbortController().signal,
    'mock',
  );
  assert.ok(events.some((e) => e.type === 'tool_start' && e.name === 'calculator'));
  assert.ok(events.some((e) => e.type === 'tool_end' && e.output === '2048'));
  assert.equal(events.at(-1)?.type, 'done');
  assert.match(
    events
      .filter((e) => e.type === 'token')
      .map((e) => e.text)
      .join(''),
    /2048/,
  );
});
void test('Mock 支持取消且不会正常结束', async () => {
  const controller = new AbortController();

  controller.abort();

  const events: AgentEvent[] = [];

  await assert.rejects(
    runAgent([{ role: 'user', content: 'RAG' }], (e) => events.push(e), controller.signal, 'mock'),
  );
  assert.ok(!events.some((e) => e.type === 'done'));
});
void test('HTTP 校验和 SSE 响应', async () => {
  const server = createApp('mock').listen(0, '127.0.0.1');

  await new Promise<void>((resolve) => server.once('listening', resolve));

  const address = server.address();

  assert.ok(address && typeof address !== 'string');

  const base = `http://127.0.0.1:${address.port}`;

  try {
    const health = await fetch(`${base}/api/health`);

    assert.equal(((await health.json()) as { provider: string }).provider, 'mock');

    const invalid = await fetch(`${base}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: [] }),
    });

    assert.equal(invalid.status, 400);

    const malformed = await fetch(`${base}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{',
    });

    assert.equal(malformed.status, 400);

    const response = await fetch(`${base}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: [{ role: 'user', content: '计算 1 + 2' }] }),
    });

    assert.match(response.headers.get('content-type') || '', /text\/event-stream/);

    const text = await response.text();

    assert.match(text, /tool_start/);
    assert.match(text, /"type":"done"/);
  } finally {
    await new Promise<void>((resolve, reject) => server.close((e) => (e ? reject(e) : resolve())));
  }
});
void test('多轮 Mock 使用上次用户消息', async () => {
  const events: AgentEvent[] = [];

  await runAgent(
    [
      { role: 'user', content: '我想学习 Vue' },
      { role: 'assistant', content: '好的' },
      { role: 'user', content: '我上一条说了什么？' },
    ],
    (e) => events.push(e),
    new AbortController().signal,
    'mock',
  );
  assert.match(
    events
      .filter((e) => e.type === 'token')
      .map((e) => e.text)
      .join(''),
    /我想学习 Vue/,
  );
});
