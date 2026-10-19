<template>
  <div class="app-shell">
    <aside class="sidebar">
      <a
        class="brand"
        href="/"
        aria-label="Agent Studio 首页"
      >
        <span class="brand-mark"><layers :size="21" /></span>
        agent
        <span>studio</span>
        <span class="brand-dot">.</span>
      </a>
      <div class="workspace">
        <div class="workspace-avatar">
          A
        </div>
        <div>
          个人工作空间
          <small>Personal workspace</small>
        </div>
        <chevron-right :size="14" />
      </div>
      <button
        class="new-chat"
        :disabled="busy"
        @click="newSession"
      >
        <plus :size="17" />
        新建对话
        <kbd>＋</kbd>
      </button>
      <div class="nav-label">
        工作空间
      </div>
      <button
        :class="['nav-item', { active: page === 'chat' }]"
        @click="page = 'chat'"
      >
        <message-square :size="17" />
        Agent 对话
        <span class="tiny-label">BETA</span>
      </button>
      <button
        :class="['nav-item', { active: page === 'knowledge' }]"
        @click="page = 'knowledge'"
      >
        <book-open :size="17" />
        知识库
        <span class="count">{{ docs.length }}</span>
      </button>
      <button
        :class="['nav-item', { active: page === 'settings' }]"
        @click="page = 'settings'"
      >
        <settings2 :size="17" />
        模型与工具
      </button>
      <button
        :class="['nav-item', { active: page === 'lab' }]"
        @click="page = 'lab'"
      >
        <layers :size="17" />
        工程实验室
      </button>
      <div class="nav-label history-heading">
        最近对话
        <span>{{ sessions.length }}</span>
      </div>
      <div class="session-list">
        <div
          v-for="session in sessions"
          :key="session.id"
          :class="['session', { selected: currentId === session.id && page === 'chat' }]"
        >
          <button
            :disabled="busy"
            @click="select(session.id)"
          >
            <message-square :size="14" />
            <span>{{ session.title }}</span>
          </button>
          <button
            class="delete"
            :disabled="busy"
            aria-label="删除会话"
            @click="remove(session.id)"
          >
            <trash2 :size="13" />
          </button>
        </div>
        <p
          v-if="!sessions.length"
          class="empty-history"
        >
          你的探索，将从这里开始
        </p>
      </div>
      <div class="sidebar-bottom">
        <div class="local-note">
          <span class="green-dot" />
          本地开发环境
          <span>v0.1</span>
        </div>
        <div class="profile">
          <div class="profile-avatar">
            D
          </div>
          <div>
            Developer
            <small>把想法变成行动</small>
          </div>
          <settings2
            :size="16"
            @click="page = 'settings'"
          />
        </div>
      </div>
    </aside>
    <main>
      <header>
        <div>
          <panel-left-close :size="18" />
          <span class="divider" />
          <span>工作空间</span>
          <chevron-right :size="14" />
          <strong>
            {{
              page === 'chat'
                ? 'Agent 对话'
                : page === 'knowledge'
                  ? '知识库'
                  : page === 'lab'
                    ? '工程实验室'
                    : '模型与工具'
            }}
          </strong>
        </div>
        <div class="environment">
          <span class="green-dot" />
          {{
            health.provider === 'mock'
              ? 'Mock 模式'
              : health.provider === 'openai'
                ? 'OpenAI 模式'
                : '服务未连接'
          }}
        </div>
      </header>
      <template v-if="page === 'chat'">
        <div class="chat-layout">
          <section class="conversation">
            <div
              ref="scrollArea"
              class="messages-scroll"
            >
              <div
                v-if="!current?.messages.length"
                class="welcome"
              >
                <div class="eyebrow">
                  <span />
                  YOUR IDEAS. IN ACTION.
                </div>
                <h1>
                  不止回答，
                  <br>
                  让想法
                  <span class="serif">发生。</span>
                  <sparkles
                    class="hero-spark"
                    :size="30"
                  />
                </h1>
                <p class="intro">
                  你的 AI Agent 工作台。连接知识、调用工具，
                  <br>
                  从一个问题开始，探索智能协作的更多可能。
                </p>
                <div class="suggestions">
                  <button
                    v-for="p in prompts"
                    :key="p.title"
                    @click="send(p.text)"
                  >
                    <div class="suggestion-top">
                      <component
                        :is="p.icon"
                        :size="20"
                      />
                      <arrow-up-right :size="16" />
                    </div>
                    <strong>{{ p.title }}</strong>
                    <span>{{ p.tag }}</span>
                  </button>
                </div>
                <div class="capabilities">
                  <span>
                    <check :size="13" />
                    多轮记忆
                  </span>
                  <span>
                    <check :size="13" />
                    工具调用
                  </span>
                  <span>
                    <check :size="13" />
                    知识检索
                  </span>
                </div>
              </div>
              <div
                v-else
                class="message-list"
              >
                <div class="conversation-heading">
                  {{ current.title }}
                  <span>SESSION / {{ current.id.slice(0, 6) }}</span>
                </div>
                <article
                  v-for="m in current.messages"
                  :key="m.id"
                  :class="['message', m.role]"
                >
                  <div class="message-avatar">
                    <sparkles
                      v-if="m.role === 'assistant'"
                      :size="16"
                    />
                    <span v-else>D</span>
                  </div>
                  <div class="message-body">
                    <div class="message-author">
                      {{ m.role === 'user' ? '你' : 'Studio Agent' }}
                      <span v-if="m.role === 'assistant'">{{ health.provider }}</span>
                    </div>
                    <div class="message-text">
                      {{ m.content || (busy ? '正在处理…' : '未生成回答') }}
                    </div>
                    <div
                      v-if="m.sources?.length"
                      class="sources"
                    >
                      <details
                        v-for="source in m.sources"
                        :key="source.id"
                      >
                        <summary>
                          <book-open :size="12" />
                          {{ source.title }}
                          <span>[{{ source.id }}]</span>
                        </summary>
                        <p>{{ source.content }}</p>
                      </details>
                    </div>
                    <small
                      v-if="m.failed"
                      class="failed"
                    >此回答未完成，不会用于后续上下文</small>
                  </div>
                </article>
              </div>
            </div>
            <div class="composer-wrap">
              <div
                v-if="error || persistenceError"
                class="error"
                role="alert"
              >
                {{ error || persistenceError }}
              </div>
              <form
                class="composer"
                @submit.prevent="send()"
              >
                <textarea
                  v-model="input"
                  aria-label="消息"
                  placeholder="有什么想法？交给 Agent 一起完成…"
                  rows="2"
                  maxlength="8000"
                  :disabled="busy"
                  @keydown.enter.exact="
                    (e) => {
                      if (!e.isComposing) {
                        e.preventDefault();
                        send();
                      }
                    }
                  "
                />
                <div class="composer-bottom">
                  <span class="model-chip">
                    <span class="green-dot" />
                    {{ health.model }}
                    <chevron-right :size="12" />
                  </span>
                  <select
                    v-model="agentMode"
                    aria-label="编排模式"
                    :disabled="busy"
                  >
                    <option value="react">
                      ReAct
                    </option>
                    <option value="plan">
                      Plan-and-Execute
                    </option>
                    <option value="multi">
                      多角色协作
                    </option>
                  </select>
                  <span class="input-hint">Enter 发送 · Shift + Enter 换行</span>
                  <button
                    v-if="busy"
                    type="button"
                    class="send"
                    aria-label="停止生成"
                    @click="controller?.abort()"
                  >
                    <square :size="16" />
                  </button>
                  <button
                    v-else
                    class="send"
                    :disabled="!input.trim()"
                    aria-label="发送消息"
                  >
                    <arrow-up :size="19" />
                  </button>
                </div>
              </form>
              <p class="disclaimer">
                {{
                  health.provider === 'mock'
                    ? '当前为本地模拟体验，不调用模型 API。工具会真实执行。'
                    : 'AI 生成内容可能不准确，请核对重要信息。'
                }}
              </p>
            </div>
          </section>
          <aside class="inspector">
            <div class="inspector-title">
              <span>
                <layers :size="16" />
                运行面板
              </span>
              <span class="live">{{ busy ? 'RUNNING' : 'READY' }}</span>
            </div>
            <p class="inspector-caption">
              每一步，都清晰可见
            </p>
            <div class="agent-card">
              <div class="agent-symbol">
                <sparkles :size="23" />
              </div>
              <strong>Studio Agent</strong>
              <span>通用智能助手</span>
              <div class="agent-status">
                <span class="green-dot" />
                {{ busy ? '执行中' : '已就绪' }}
              </div>
            </div>
            <div class="section-label">
              已连接的能力
              <span>02</span>
            </div>
            <div class="tool-row">
              <div><book-open :size="17" /></div>
              <span>
                知识库检索
                <small>本地 BM25 检索</small>
              </span>
              <span class="green-dot" />
            </div>
            <div class="tool-row">
              <div><wrench :size="17" /></div>
              <span>
                计算器
                <small>结构化工具调用</small>
              </span>
              <span class="green-dot" />
            </div>
            <div class="section-label trace-heading">
              执行记录
              <span>{{ trace.length.toString().padStart(2, '0') }}</span>
            </div>
            <div
              v-if="!trace.length"
              class="trace-empty"
            >
              <span class="trace-line" />
              <p>等待一个新想法</p>
              <small>
                发送消息后，工具调用过程
                <br>
                将在这里实时呈现
              </small>
            </div>
            <details
              v-for="(t, i) in trace"
              :key="i"
              class="trace-event"
            >
              <summary>
                <check
                  v-if="t.done"
                  :size="14"
                />
                <span
                  v-else
                  class="green-dot"
                />
                {{ t.title }}
              </summary>
              <pre v-if="t.detail">{{ t.detail }}</pre>
            </details>
            <div class="inspector-note">
              <span>BUILT TO EXPLORE</span>
              <p>
                小小的起点，
                <br>
                无限的可能。
              </p>
              <arrow-up-right :size="22" />
            </div>
          </aside>
        </div>
      </template>
      <section
        v-else-if="page === 'knowledge'"
        class="content-page"
      >
        <div class="eyebrow">
          KNOWLEDGE BASE
        </div>
        <h2>给回答，一点依据。</h2>
        <p>内置 {{ docs.length }} 篇项目文档 · 本地 BM25 检索 · 无外部 API 调用</p>
        <div class="document-grid">
          <article
            v-for="doc in docs"
            :key="doc.id"
          >
            <book-open :size="22" />
            <small>{{ doc.id.toUpperCase() }}</small>
            <h3>{{ doc.title }}</h3>
            <p>{{ doc.content }}</p>
            <button
              @click="
                page = 'chat';
                send(doc.title);
              "
            >
              向 Agent 提问
              <arrow-up-right :size="15" />
            </button>
          </article>
        </div>
      </section>
      <engineering-lab v-else-if="page === 'lab'" />
      <section
        v-else
        class="content-page"
      >
        <div class="eyebrow">
          CONFIGURATION
        </div>
        <h2>简单起步，逐步扩展。</h2>
        <p>配置由后端环境变量管理，密钥不会传入浏览器。</p>
        <div class="config-card">
          <h3>
            模型运行时
            <span class="badge">{{ health.provider || '离线' }}</span>
          </h3>
          <dl>
            <dt>当前模型</dt>
            <dd>{{ health.model }}</dd>
            <dt>Agent 编排</dt>
            <dd>
              {{ health.provider === 'mock' ? 'Python 有界 Agent Loop' : 'Python Agent Runtime' }}
            </dd>
            <dt>会话记忆</dt>
            <dd>浏览器短期历史 + SQLite 持久化长期记忆</dd>
            <dt>知识检索</dt>
            <dd>分块 + BM25 排序 + LRU 缓存（非向量检索）</dd>
          </dl>
        </div>
        <div class="config-card">
          <h3>工程学习路线</h3>
          <p>在「工程实验室」提交后台任务、导入文档、查看追踪、注入工具故障并运行回归评测。</p>
          <p>
            模型默认 Mock，无需 API Key。运行时通过 Model 接口隔离模型决策；真实模型适配尚未接入。
          </p>
          <p>
            聊天输入「记住：我喜欢 Python」测试长期记忆。会话 ID：{{ currentId || '请先新建对话' }}
          </p>
        </div>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import {
  ArrowUp,
  Plus,
  MessageSquare,
  BookOpen,
  Settings2,
  PanelLeftClose,
  Sparkles,
  ArrowUpRight,
  Square,
  Check,
  Wrench,
  ChevronRight,
  Layers,
  Trash2,
} from 'lucide-vue-next';
import type { AgentEvent, Message, Source } from '@studio/shared';
import EngineeringLab from './EngineeringLab.vue';

type ChatMessage = Message & { id: string; sources?: Source[]; failed?: boolean };
type Session = { id: string; title: string; messages: ChatMessage[] };
const sessions = ref<Session[]>([]);

try {
  const saved = JSON.parse(localStorage.getItem('agent-studio-v1') || '[]');
  if (Array.isArray(saved))
    sessions.value = saved.filter(
      (s) =>
        typeof s.id === 'string' &&
        typeof s.title === 'string' &&
        Array.isArray(s.messages) &&
        s.messages.every(
          (m: ChatMessage) =>
            ['user', 'assistant'].includes(m.role) && typeof m.content === 'string',
        ),
    );
} catch {
  /* 损坏的数据不影响启动 */
}

const currentId = ref(sessions.value[0]?.id || '');
const current = computed(() => sessions.value.find((s) => s.id === currentId.value));
const page = ref('chat');
const input = ref('');
const agentMode = ref('react');
const busy = ref(false);
const error = ref('');
const persistenceError = ref('');
const trace = ref<{ title: string; detail: string; done: boolean }[]>([]);
const health = ref({ provider: '', model: '连接中…' });
const docs = ref<{ id: string; title: string; content: string }[]>([]);
const scrollArea = ref<HTMLElement>();
let controller: AbortController | undefined;

const prompts = [
  {
    icon: Layers,
    title: '理解 Agent 架构',
    text: '介绍项目架构和 Agent 工作原理',
    tag: '从这里开始',
  },
  {
    icon: BookOpen,
    title: '探索知识库',
    text: '什么是 RAG？它的工作流程是什么？',
    tag: '检索增强',
  },
  { icon: Wrench, title: '让工具完成任务', text: '计算 128 * 16', tag: '工具调用' },
];

function newSession() {
  if (busy.value) return;
  const session = { id: crypto.randomUUID(), title: '新对话', messages: [] };

  sessions.value.unshift(session);
  currentId.value = session.id;
  page.value = 'chat';
  trace.value = [];
  error.value = '';
}

function select(id: string) {
  if (busy.value) return;
  currentId.value = id;
  page.value = 'chat';
  trace.value = [];
  error.value = '';
}

function remove(id: string) {
  if (busy.value) return;
  sessions.value = sessions.value.filter((s) => s.id !== id);
  if (currentId.value === id) currentId.value = sessions.value[0]?.id || '';
}

watch(
  sessions,
  () => {
    try {
      localStorage.setItem('agent-studio-v1', JSON.stringify(sessions.value));
    } catch {
      persistenceError.value = '浏览器存储已满，当前对话暂未保存。请删除旧会话。';
    }
  },
  { deep: true },
);
watch(page, async (value) => {
  if (value !== 'knowledge') return;
  try {
    const response = await fetch('/api/knowledge');
    if (!response.ok) throw Error('知识库刷新失败');
    docs.value = await response.json();
  } catch {
    error.value = '知识库刷新失败，请检查后端连接';
  }
});
onMounted(async () => {
  try {
    const [h, d] = await Promise.all([fetch('/api/health'), fetch('/api/knowledge')]);
    if (!h.ok || !d.ok) throw Error();
    health.value = await h.json();
    docs.value = await d.json();
  } catch {
    error.value = '无法连接后端，请确认 API 服务已启动。';
    health.value.model = '未连接';
  }
});

async function send(text = input.value) {
  if (busy.value || !text.trim()) return;
  if (!current.value) newSession();
  const session = current.value!;
  const message = text.trim();

  if (message.length > 8000) {
    error.value = '消息不能超过 8000 字符';

    return;
  }
  if (!session.messages.length) session.title = message.slice(0, 22);
  session.messages.push({ id: crypto.randomUUID(), role: 'user', content: message });

  const history = session.messages
    .filter((m) => !m.failed && m.content)
    .slice(-20)
    .map(({ role, content }) => ({ role, content }));

  const answer: ChatMessage = { id: crypto.randomUUID(), role: 'assistant', content: '' };

  session.messages.push(answer);

  const target = session.messages.at(-1)!;

  input.value = '';
  busy.value = true;
  error.value = '';
  trace.value = [];
  controller = new AbortController();
  let completed = false;
  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: history, session_id: session.id, mode: agentMode.value }),
      signal: controller.signal,
    });

    if (!response.ok) {
      const data = await response.json();
      throw Error(data.error || '请求失败');
    }
    if (!response.body) throw Error('浏览器不支持流式响应');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    const handle = (event: AgentEvent) => {
      if (event.type === 'token') target.content += event.text;
      if (event.type === 'sources') target.sources = event.sources;
      if (event.type === 'status')
        trace.value.push({ title: event.message, detail: '', done: true });
      if (event.type === 'tool_start')
        trace.value.push({
          title: event.name,
          detail: JSON.stringify(event.input, null, 2),
          done: false,
        });
      if (event.type === 'tool_end') {
        const item = trace.value.findLast((t) => t.title === event.name);

        if (item) {
          item.done = true;
          item.detail += '\n\n' + event.output;
        }
      }
      if (event.type === 'error') throw Error(event.message);
      if (event.type === 'done') completed = true;
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let end: number;
      while ((end = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, end);

        buffer = buffer.slice(end + 2);
        if (frame.startsWith('data: ')) handle(JSON.parse(frame.slice(6)));
      }
      await nextTick();
      scrollArea.value?.scrollTo({ top: scrollArea.value.scrollHeight });
    }
    if (!completed) throw Error('连接提前中断，请重试');
  } catch (e) {
    target.failed = true;
    error.value = controller.signal.aborted
      ? '已停止生成'
      : e instanceof Error
        ? e.message
        : '请求失败';
  } finally {
    busy.value = false;
    controller = undefined;
  }
}
</script>
