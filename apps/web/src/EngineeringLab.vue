<template>
  <section class="content-page lab-page">
    <div class="eyebrow">
      AGENT ENGINEERING / LAB
    </div>
    <h2>从一次运行，到持续改进。</h2>
    <p>真实本地工具与持久化数据 · 确定性 Mock 编排 · Python / SQLite</p>
    <div class="lab-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        :class="{ chosen: active === tab.id }"
        @click="active = tab.id"
      >
        {{ tab.label }}
      </button>
      <button
        :disabled="loading"
        @click="refresh"
      >
        刷新数据
      </button>
    </div>
    <p
      v-if="error"
      class="error"
      role="alert"
    >
      {{ error }}
    </p>
    <p
      v-if="notice"
      role="status"
    >
      {{ notice }}
    </p>
    <template v-if="active === 'runs'">
      <form
        class="config-card lab-form"
        @submit.prevent="submit"
      >
        <h3>创建后台任务</h3>
        <label>
          任务目标
          <textarea
            v-model="question"
            required
            maxlength="8000"
          />
        </label>
        <div class="lab-controls">
          <label>
            编排模式
            <select v-model="mode">
              <option value="react">ReAct / 逐步执行</option>
              <option value="plan">Plan-and-Execute</option>
              <option value="multi">多角色协作</option>
            </select>
          </label>
          <label>
            故障注入
            <select v-model="fault">
              <option value="none">关闭</option>
              <option value="tool_error">工具异常</option>
            </select>
          </label>
          <button
            :disabled="loading"
            type="submit"
          >
            提交任务 →
          </button>
        </div>
      </form>
      <div class="lab-split">
        <div class="config-card">
          <h3>
            任务队列
            <span class="badge">{{ runs.length }}</span>
          </h3>
          <p v-if="!runs.length">
            尚无任务，提交第一个目标开始。
          </p>
          <button
            v-for="run in runs"
            :key="run.id"
            class="run-row"
            @click="inspect(run.id)"
          >
            <span>
              {{ run.id.slice(0, 8) }}
              <small>{{ new Date(run.created * 1000).toLocaleString() }}</small>
            </span>
            <span :class="['run-status', run.status]">{{ run.status }}</span>
          </button>
        </div>
        <div class="config-card">
          <h3>执行追踪</h3>
          <template v-if="selected">
            <p>{{ selected.id }}</p>
            <div class="lab-controls">
              <button
                v-if="['queued', 'running'].includes(selected.status)"
                @click="act('cancel')"
              >
                取消任务
              </button>
              <button
                v-if="['failed', 'cancelled'].includes(selected.status)"
                @click="act('retry')"
              >
                关闭故障并重试
              </button>
              <button @click="feedback(1)">
                有帮助 +1
              </button>
              <button @click="feedback(-1)">
                需改进 −1
              </button>
            </div>
            <p
              v-if="selected.error"
              class="error"
            >
              {{ selected.error }}
            </p>
            <pre class="lab-answer">{{ selected.answer }}</pre>
            <details
              v-for="event in selected.events"
              :key="event.seq"
              class="trace-event"
            >
              <summary>
                #{{ event.seq }} · {{ event.type }} · {{ event.name || event.message || '' }}
              </summary>
              <pre>{{ JSON.stringify(event, null, 2) }}</pre>
            </details>
          </template>
          <p v-else>
            选择任务，查看事件序号、工具参数、结果与错误。
          </p>
        </div>
      </div>
    </template>
    <template v-if="active === 'knowledge'">
      <form
        class="config-card lab-form"
        @submit.prevent="importDocument"
      >
        <h3>导入知识文档</h3>
        <label>
          标题
          <input
            v-model="title"
            required
            maxlength="100"
          >
        </label>
        <label>
          内容
          <textarea
            v-model="content"
            required
            maxlength="20000"
          />
        </label>
        <button :disabled="loading">
          导入并更新索引
        </button>
      </form>
      <form
        class="config-card lab-form"
        @submit.prevent="search"
      >
        <h3>检索调试</h3>
        <label>
          查询
          <input
            v-model="query"
            required
          >
        </label>
        <button :disabled="loading">
          执行 BM25 检索
        </button>
        <article
          v-for="source in sources"
          :key="source.id"
        >
          <h4>{{ source.title }} · {{ source.id }}</h4>
          <small>BM25 {{ source.score }}</small>
          <p>{{ source.content }}</p>
        </article>
      </form>
    </template>
    <template v-if="active === 'eval'">
      <div class="config-card">
        <h3>回归评测 / 策略对比</h3>
        <p>
          相同固定任务集比较 top_k=1 与 top_k=3。检查真实输出和工具调用；不代表模型智能或生产质量。
        </p>
        <button
          :disabled="loading"
          @click="evaluate"
        >
          {{ loading ? '评测执行中…' : '运行基线与候选评测' }}
        </button>
        <div
          v-if="evaluation"
          class="lab-split"
        >
          <article
            v-for="result in [evaluation.baseline, evaluation.candidate]"
            :key="result.top_k"
          >
            <h3>Top K = {{ result.top_k }} · 通过率 {{ Math.round(result.pass_rate * 100) }}%</h3>
            <details
              v-for="item in result.cases"
              :key="item.name"
            >
              <summary>
                {{ item.passed ? '✓' : '×' }} {{ item.name }} · {{ item.latency_ms }} ms
              </summary>
              <pre>{{ item.answer }}</pre>
            </details>
          </article>
        </div>
      </div>
      <div class="config-card">
        <h3>改进候选</h3>
        <p v-if="!improvements.length">
          尚无失败或负反馈案例。
        </p>
        <p
          v-for="item in improvements"
          :key="item.run_id"
        >
          {{ item.run_id.slice(0, 8) }} · {{ item.reason }} → {{ item.action }}
        </p>
      </div>
    </template>
    <template v-if="active === 'memory'">
      <div class="config-card lab-form">
        <h3>长期记忆</h3>
        <p>聊天输入「记住：我喜欢 Python」保存；这里按会话查看和删除。</p>
        <label>
          会话 ID
          <input v-model="memorySession">
        </label>
        <div class="lab-controls">
          <button @click="loadMemory">
            读取
          </button>
          <button @click="clearMemory">
            清空此会话记忆
          </button>
        </div>
        <p
          v-for="fact in memories"
          :key="fact"
        >
          {{ fact }}
        </p>
        <p v-if="!memories.length">
          当前没有已读取的记忆。
        </p>
      </div>
    </template>
    <template v-if="active === 'skills'">
      <div
        v-for="skill in skills"
        :key="skill.name"
        class="config-card"
      >
        <h3>{{ skill.name }}</h3>
        <pre>{{ skill.content }}</pre>
      </div>
      <div class="config-card">
        <h3>MCP 协议实验</h3>
        <p>本地 JSON-RPC 教学子集：initialize → tools/list → tools/call。只开放受限算术工具。</p>
        <button
          :disabled="loading"
          @click="testMcp"
        >
          执行 tools/call：128 * 16
        </button>
        <pre>{{ mcpResult }}</pre>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue';
import type { Source } from '@studio/shared';

type Run = { id: string; status: string; created: number; answer: string; error: string };
type Trace = { seq: number; type: string; name?: string; message?: string };
type Detail = Run & { events: Trace[] };
type EvalResult = {
  top_k: number;
  pass_rate: number;
  cases: { name: string; passed: boolean; latency_ms: number; answer: string }[];
};

const tabs = [
  { id: 'runs', label: '任务与追踪' },
  { id: 'knowledge', label: '知识引擎' },
  { id: 'eval', label: '评测与改进' },
  { id: 'memory', label: '长期记忆' },
  { id: 'skills', label: 'Skills / MCP' },
];

const active = ref('runs');
const loading = ref(false);
const error = ref('');
const notice = ref('');
const question = ref('解释 RAG 与上下文工程，并计算 128 * 16');
const mode = ref('multi');
const fault = ref('none');
const runs = ref<Run[]>([]);
const selected = ref<Detail>();
const title = ref('');
const content = ref('');
const query = ref('RAG');
const sources = ref<Source[]>([]);
const evaluation = ref<{ baseline: EvalResult; candidate: EvalResult }>();
const improvements = ref<{ run_id: string; reason: string; action: string }[]>([]);
const skills = ref<{ name: string; content: string }[]>([]);
const memories = ref<string[]>([]);
const memorySession = ref('lab');
const mcpResult = ref('');
let timer: ReturnType<typeof setInterval> | undefined;

async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch('/api' + path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) throw new Error(`请求失败 (${response.status})：${await response.text()}`);

  return response.json();
}

async function perform(action: () => Promise<void>) {
  if (loading.value) return;
  loading.value = true;
  error.value = '';
  notice.value = '';
  try {
    await action();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '请求失败';
  } finally {
    loading.value = false;
  }
}

async function refreshData() {
  const [list, candidates, guides] = await Promise.all([
    api<Run[]>('/runs'),
    api<typeof improvements.value>('/improvements'),
    api<typeof skills.value>('/skills'),
  ]);

  runs.value = list;
  improvements.value = candidates;
  skills.value = guides;
  if (selected.value) selected.value = await api<Detail>('/runs/' + selected.value.id);
}

function refresh() {
  return perform(refreshData);
}

function inspect(id: string) {
  return perform(async () => {
    selected.value = await api<Detail>('/runs/' + id);
  });
}

function submit() {
  return perform(async () => {
    const result = await api<{ id: string }>('/runs', 'POST', {
      session_id: 'lab',
      mode: mode.value,
      fault: fault.value,
      messages: [{ role: 'user', content: question.value }],
    });

    selected.value = await api<Detail>('/runs/' + result.id);
    await refreshData();
  });
}

function act(action: string) {
  return perform(async () => {
    if (!selected.value) return;
    const result = await api<{ id?: string }>('/runs/' + selected.value.id + '/' + action, 'POST');
    if (result.id) selected.value = await api<Detail>('/runs/' + result.id);
    await refreshData();
  });
}

function feedback(score: number) {
  return perform(async () => {
    if (!selected.value) return;
    await api('/runs/' + selected.value.id + '/feedback', 'POST', { score });
    notice.value = '反馈已保存';
    await refreshData();
  });
}

function importDocument() {
  return perform(async () => {
    await api('/knowledge', 'POST', { title: title.value, content: content.value });
    title.value = '';
    content.value = '';
    notice.value = '文档已持久化，检索缓存已失效';
  });
}

function search() {
  return perform(async () => {
    sources.value = await api<Source[]>('/search?q=' + encodeURIComponent(query.value));
  });
}

function evaluate() {
  return perform(async () => {
    evaluation.value = await api('/evaluations', 'POST');
  });
}

function loadMemory() {
  return perform(async () => {
    memories.value = await api('/memory/' + encodeURIComponent(memorySession.value));
  });
}

function clearMemory() {
  return perform(async () => {
    await api('/memory/' + encodeURIComponent(memorySession.value), 'DELETE');
    memories.value = [];
    notice.value = '记忆已删除';
  });
}

function testMcp() {
  return perform(async () => {
    mcpResult.value = JSON.stringify(
      await api('/mcp', 'POST', {
        jsonrpc: '2.0',
        id: 1,
        method: 'tools/call',
        params: { name: 'calculator', arguments: { expression: '128 * 16' } },
      }),
      null,
      2,
    );
  });
}

onMounted(() => {
  void refresh();
  timer = setInterval(() => {
    if (runs.value.some((run) => ['queued', 'running'].includes(run.status))) void refresh();
  }, 1500);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
});
</script>

<style scoped>
.lab-page {
  overflow-y: auto;
}
.lab-tabs,
.lab-controls {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin: 18px 0;
  align-items: end;
}
button {
  cursor: pointer;
  border: 1px solid #d8ddd8;
  background: #fff;
  padding: 10px 14px;
  border-radius: 8px;
  color: #33473d;
}
button:hover,
.chosen {
  background: #e9f0e9;
}
button:disabled {
  opacity: 0.5;
  cursor: wait;
}
.lab-form label {
  display: grid;
  gap: 8px;
  font-size: 13px;
  margin: 12px 0;
}
input,
textarea,
select {
  border: 1px solid #d8ddd8;
  padding: 12px;
  border-radius: 8px;
  font: inherit;
  background: #fff;
  color: #25362c;
}
textarea {
  min-height: 90px;
  resize: vertical;
}
.lab-split {
  display: grid;
  grid-template-columns: 1fr 1.25fr;
  gap: 20px;
}
.config-card {
  max-width: none;
  min-width: 0;
}
.run-row {
  display: flex;
  width: 100%;
  justify-content: space-between;
  text-align: left;
  margin: 8px 0;
}
.run-row small {
  display: block;
  color: #7c847e;
  margin-top: 6px;
}
.run-status {
  font-size: 11px;
  align-self: center;
}
.completed {
  color: #237147;
}
.failed {
  color: #ad4937;
}
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 12px;
  line-height: 1.8;
}
.lab-answer {
  max-height: 300px;
  overflow: auto;
}
@media (max-width: 1100px) {
  .lab-split {
    grid-template-columns: 1fr;
  }
}
</style>
