<template>
  <div class="ops-shell">
    <aside class="ops-sidebar">
      <a
        class="ops-brand"
        href="/"
      >
        <span class="ops-logo"><gamepad2 :size="23" /></span>
        <span>
          游戏中心
          <small>运营智能助手</small>
        </span>
      </a>
      <button
        class="ops-new"
        :disabled="busy"
        @click="newChat"
      >
        <plus :size="17" />
        发起新咨询
        <span>↗</span>
      </button>
      <nav>
        <button
          :class="{ active: tab === 'chat' }"
          @click="tab = 'chat'"
        >
          <message-square :size="18" />
          智能问答
        </button>
        <button
          :class="{ active: tab === 'knowledge' }"
          @click="tab = 'knowledge'"
        >
          <book-open :size="18" />
          运营知识库
          <small>{{ docs.length }}</small>
        </button>
      </nav>
      <div class="ops-history-label">
        最近咨询
        <span>服务端保存</span>
      </div>
      <div class="ops-history">
        <div
          v-for="session in sessions"
          :key="session.id"
          class="ops-history-row"
          :class="{ selected: selected === session.id }"
        >
          <button
            class="ops-history-select"
            :disabled="busy"
            :title="session.title"
            @click="selectSession(session.id)"
          >
            <message-square :size="14" />
            <span>{{ session.title }}</span>
          </button>
          <button
            class="ops-history-delete"
            :disabled="busy"
            :aria-label="`删除咨询：${session.title}`"
            title="删除咨询"
            @click="deleteChat(session.id)"
          >
            <trash2 :size="14" />
          </button>
        </div>
      </div>
      <div class="ops-sidebar-bottom">
        <shield-check :size="17" />
        <span>基于知识库 · 回答可溯源</span>
      </div>
      <button
        class="ops-settings"
        @click="tab = 'settings'"
      >
        <settings2 :size="17" />
        模型与服务
        <span :class="['ops-dot', { online: model.configured }]" />
      </button>
    </aside>
    <main class="ops-main">
      <header class="ops-header">
        <div>
          <span>工作空间</span>
          <chevron-right :size="14" />
          <b>
            {{ tab === 'chat' ? '智能问答' : tab === 'knowledge' ? '运营知识库' : '模型与服务' }}
          </b>
        </div>
        <span class="ops-status">
          <span :class="['ops-dot', { online: model.configured }]" />
          {{ model.configured ? model.model : '模型待配置' }}
        </span>
      </header>
      <div
        v-if="notice"
        class="ops-notice"
        role="alert"
      >
        {{ notice }}
        <button
          aria-label="关闭提示"
          @click="notice = ''"
        >
          <x :size="16" />
        </button>
      </div>
      <template v-if="tab === 'chat'">
        <div
          ref="feed"
          class="ops-feed"
          aria-live="polite"
        >
          <section
            v-if="!current?.messages.length"
            class="ops-welcome"
          >
            <div class="ops-eyebrow">
              <span />
              GAME CENTER · OPERATIONS COPILOT
            </div>
            <div class="ops-hero-icon">
              <gamepad2 :size="35" />
            </div>
            <h1>配置有疑问，先问运营助手</h1>
            <p>从活动上线到礼包配置，让每个问题都有据可循。</p>
            <div class="ops-capabilities">
              <span>
                <search :size="14" />
                检索业务知识
              </span>
              <span>
                <message-square :size="14" />
                支持连续追问
              </span>
              <span>
                <book-open :size="14" />
                附带参考来源
              </span>
            </div>
            <div class="ops-suggestions-label">
              从一个常见问题开始
              <span>示例场景</span>
            </div>
            <div class="ops-prompts">
              <button
                v-for="(prompt, index) in prompts"
                :key="prompt"
                @click="send(prompt)"
              >
                <span class="ops-prompt-number">0{{ index + 1 }}</span>
                <b>{{ ['资源位配置', '礼包与奖励', '活动发布', '渠道与灰度'][index] }}</b>
                <p>{{ prompt }}</p>
                <chevron-right :size="17" />
              </button>
            </div>
            <div class="ops-demo-note">
              <circle-help :size="15" />
              当前内置演示知识，请导入内部文档以获得真实业务依据。
            </div>
          </section>
          <div
            v-else
            class="ops-messages"
          >
            <article
              v-for="(message, index) in current.messages"
              :key="index"
              :class="['ops-message', message.role]"
            >
              <div class="ops-avatar">
                {{ message.role === 'user' ? '你' : 'AI' }}
              </div>
              <div class="ops-message-body">
                <b>{{ message.role === 'user' ? '我' : '运营助手' }}</b>
                <div class="ops-answer">
                  {{ message.content }}
                </div>
                <div
                  v-if="busy && index === current.messages.length - 1"
                  class="ops-generating"
                >
                  <loader-circle
                    class="ops-spin"
                    :size="14"
                  />
                  {{ status }}
                </div>
                <div
                  v-if="message.error"
                  class="ops-error"
                >
                  {{ message.error }}
                </div>
                <div
                  v-if="message.toolTrace?.length"
                  class="ops-sources"
                >
                  <small>工具调用 · 本次请求</small>
                  <div
                    v-for="(step, stepIndex) in message.toolTrace"
                    :key="stepIndex"
                  >
                    {{ step }}
                  </div>
                </div>
                <div
                  v-if="message.sources?.length"
                  class="ops-sources"
                >
                  <small>参考知识 · {{ message.sources.length }} 条</small>
                  <button
                    v-for="(source, sourceIndex) in message.sources"
                    :key="source.id"
                    @click="detail = source"
                  >
                    <book-open :size="13" />
                    [{{ sourceIndex + 1 }}] {{ source.title }}
                  </button>
                </div>
                <small
                  v-if="message.complete"
                  class="ops-complete"
                >
                  <check :size="12" />
                  回答完成
                </small>
              </div>
            </article>
          </div>
        </div>
        <div class="ops-composer-wrap">
          <label>
            <input
              v-model="toolCalling"
              type="checkbox"
              :disabled="busy"
            >
            Tool Calling · 由模型调用知识检索
          </label>
          <form
            class="ops-composer"
            @submit.prevent="send()"
          >
            <textarea
              v-model="input"
              aria-label="输入运营问题"
              placeholder="描述你的配置问题，例如：活动已发布，为什么首页看不到？"
              maxlength="6000"
              :disabled="busy"
              @keydown.enter.exact.prevent="send()"
            />
            <div>
              <span>Enter 发送 · Shift + Enter 换行</span>
              <button
                v-if="busy"
                type="button"
                aria-label="停止生成"
                @click="controller?.abort()"
              >
                <square :size="17" />
              </button>
              <button
                v-else
                type="submit"
                aria-label="发送问题"
                :disabled="!input.trim()"
              >
                <arrow-up :size="20" />
              </button>
            </div>
          </form>
          <small class="ops-footer-note">
            回答基于知识库生成，请结合实际配置核验。请勿输入密钥或用户个人信息。
          </small>
        </div>
      </template>
      <section
        v-else-if="tab === 'knowledge'"
        class="ops-page"
      >
        <div class="ops-page-heading">
          <div>
            <h1>让业务经验成为共同知识</h1>
            <p>导入运营规范和配置说明，为每次回答提供可靠依据。</p>
          </div>
          <button
            class="ops-primary"
            @click="showImport = true"
          >
            <plus :size="16" />
            导入文档
          </button>
        </div>
        <label class="ops-search">
          <search :size="17" />
          <input
            v-model="query"
            placeholder="搜索文档标题或内容"
          >
        </label>
        <div class="ops-docs">
          <button
            v-for="doc in filtered"
            :key="doc.id"
            @click="detail = doc"
          >
            <book-open :size="23" />
            <h3>{{ doc.title }}</h3>
            <p>{{ doc.content.slice(0, 110) }}…</p>
            <small>{{ doc.content.length }} 字 · 查看全文 →</small>
          </button>
        </div>
        <p v-if="!filtered.length">
          暂无匹配文档，试试其他关键词或导入新文档。
        </p>
      </section>
      <section
        v-else
        class="ops-page ops-config"
      >
        <h1>模型与服务</h1>
        <p>使用你已有的模型网关，支持 OpenAI Chat Completions 兼容协议。</p>
        <div>
          <b>连接状态</b>
          <p>
            {{
              model.configured
                ? `已配置：${model.model}（实际连通性以请求结果为准）`
                : '尚未配置模型，真实问答暂不可用。'
            }}
          </p>
          <b>服务端环境变量</b>
          <pre>
GAME_LLM_BASE_URL=https://你的网关/v1
GAME_LLM_MODEL=已有模型名称
GAME_LLM_API_KEY=在本地服务端配置</pre>
          <p>环境变量生效后重启 API。密钥仅保留在服务端，不在浏览器填写或存储。</p>
          <button
            class="ops-primary"
            @click="refresh"
          >
            刷新状态
          </button>
        </div>
        <p>
          Redis：{{ model.redis }} · 知识检索：中文分词 + BM25 · 会话与知识：PostgreSQL ·
          上下文缓存与并发锁：Redis
        </p>
        <a href="/?studio=1">打开原工程工作台 ↗</a>
      </section>
    </main>
    <div
      v-if="showImport || detail"
      class="ops-overlay"
      @click.self="
        showImport = false;
        detail = null;
      "
    >
      <section class="ops-modal">
        <button
          class="ops-close"
          aria-label="关闭"
          @click="
            showImport = false;
            detail = null;
          "
        >
          <x :size="20" />
        </button>
        <template v-if="detail">
          <book-open :size="25" />
          <h2>{{ detail.title }}</h2>
          <div class="ops-doc-content">
            {{ detail.content }}
          </div>
          <button
            v-if="docs.some((d) => d.id === detail?.id)"
            class="ops-delete"
            @click="removeDoc(detail)"
          >
            <trash2 :size="15" />
            删除文档
          </button>
        </template>
        <template v-else>
          <h2>导入运营知识</h2>
          <p>支持粘贴正文或读取 .md / .txt 文件，最多 20000 字。</p>
          <input
            type="file"
            accept=".md,.txt"
            @change="upload"
          >
          <label>
            文档标题
            <input
              v-model="title"
              maxlength="100"
              placeholder="例如：游戏中心活动上线规范"
            >
          </label>
          <label>
            文档正文
            <textarea
              v-model="content"
              maxlength="20000"
              rows="10"
              placeholder="粘贴已审核的业务操作说明…"
            />
          </label>
          <button
            class="ops-primary"
            :disabled="importing || !title.trim() || !content.trim()"
            @click="importDoc"
          >
            {{ importing ? '正在导入…' : '导入知识库' }}
          </button>
        </template>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue';
import {
  ArrowUp,
  BookOpen,
  Check,
  ChevronRight,
  CircleHelp,
  Gamepad2,
  LoaderCircle,
  MessageSquare,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  Square,
  Trash2,
  X,
} from 'lucide-vue-next';
import { consumeStream } from './gameStream';

type Source = { id: string; title: string; content: string; score?: number };
type Message = {
  role: 'user' | 'assistant';
  content: string;
  sources?: Source[];
  toolTrace?: string[];
  error?: string;
  complete?: boolean;
};
type Session = { id: string; title: string; messages: Message[] };
const sessions = ref<Session[]>([]);
const selected = ref('');
const tab = ref('chat');
const input = ref('');
const busy = ref(false);
const toolCalling = ref(false);
const status = ref('');
const notice = ref('');
const model = ref({ configured: false, model: '', documents: 0, redis: '' });
const docs = ref<Source[]>([]);
const query = ref('');
const title = ref('');
const content = ref('');
const importing = ref(false);
const showImport = ref(false);
const detail = ref<Source | null>(null);
const feed = ref<HTMLElement>();
let controller: AbortController | undefined;
const current = computed(() => sessions.value.find((s) => s.id === selected.value));

const filtered = computed(() =>
  docs.value.filter((d) => (d.title + d.content).includes(query.value)),
);

const prompts = [
  '首页 Banner 配置后不展示，怎么排查？',
  '礼包领取失败需要检查哪些配置？',
  '活动上线前需要检查什么？',
  '渠道和灰度人群配置如何排查？',
];

async function api<T>(path: string, options?: Parameters<typeof fetch>[1]): Promise<T> {
  const response = await fetch('/api/game' + path, options);

  if (!response.ok) {
    const body = (await response.json()) as { detail?: unknown };
    throw new Error(typeof body.detail === 'string' ? body.detail : '操作失败，请稍后重试');
  }

  return (await response.json()) as T;
}

async function newChat() {
  if (busy.value) return;
  busy.value = true;
  try {
    const session = await api<Session>('/conversations', { method: 'POST' });

    sessions.value.unshift(session);
    selected.value = session.id;
    input.value = '';
    tab.value = 'chat';
  } catch (error) {
    notice.value = requestError(error);
  } finally {
    busy.value = false;
  }
}

async function selectSession(id: string) {
  if (busy.value) return;
  busy.value = true;
  try {
    const session = await api<Session>(`/conversations/${id}`);

    sessions.value = sessions.value.map((item) => (item.id === id ? session : item));
    selected.value = id;
    input.value = '';
    tab.value = 'chat';
    await scroll();
  } catch (error) {
    notice.value = requestError(error);
  } finally {
    busy.value = false;
  }
}

async function deleteChat(id: string) {
  if (busy.value) return;
  const session = sessions.value.find((item) => item.id === id);
  if (!session || !window.confirm(`删除咨询「${session.title}」及其全部消息？此操作无法撤销。`))
    return;
  busy.value = true;
  try {
    await api(`/conversations/${id}`, { method: 'DELETE' });
    sessions.value = sessions.value.filter((item) => item.id !== id);
  } catch (error) {
    notice.value = requestError(error);
    busy.value = false;

    return;
  }
  busy.value = false;
  if (selected.value !== id) return;
  if (sessions.value.length) await selectSession(sessions.value[0]!.id);
  else await newChat();
}

async function migrateLocalChats() {
  const raw = localStorage.getItem('game-ops-chats');
  if (!raw) return;
  const saved = JSON.parse(raw) as Session[];
  if (!Array.isArray(saved)) throw new Error('旧咨询格式错误，已保留浏览器原始记录');
  for (const session of saved) {
    await api('/conversations/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(session),
    });
  }
  // Retain a local backup, but never automatically import it again after deletion.
  localStorage.setItem('game-ops-chats-backup-v1', raw);
  localStorage.removeItem('game-ops-chats');
}

async function loadConversations() {
  try {
    await migrateLocalChats();
  } catch {
    notice.value = '旧咨询未能全部迁移，原记录已保留；恢复连接后刷新页面可重试。';
  }
  try {
    const rows = await api<Session[]>('/conversations');

    sessions.value = rows.map((row) => ({ ...row, messages: [] }));
    if (sessions.value.length) await selectSession(sessions.value[0]!.id);
    else await newChat();
  } catch (error) {
    notice.value = requestError(error);
  }
}

async function refresh() {
  try {
    const responses = await Promise.all([fetch('/api/game/status'), fetch('/api/game/knowledge')]);
    if (responses.some((r) => !r.ok)) throw new Error('加载失败');
    model.value = (await responses[0]!.json()) as typeof model.value;
    docs.value = (await responses[1]!.json()) as Source[];
  } catch {
    notice.value = '无法连接后端，请确认 API 服务已启动。';
  }
}

async function scroll() {
  await nextTick();
  feed.value?.scrollTo({ top: feed.value.scrollHeight, behavior: 'smooth' });
}

function applyToolEvent(event: { type: string; name?: string; query?: string; count?: number }, answer: Message) {
  if (event.type === 'tool_call') {
    answer.toolTrace = [`${event.name}(${JSON.stringify({ query: event.query })})`];
  }
  if (event.type === 'tool_result') answer.toolTrace?.push(`检索完成：命中 ${event.count ?? 0} 个知识片段`);
}

function applyEvent(data: string, answer: Message) {
  const event = JSON.parse(data) as {
    type: string;
    text?: string;
    message?: string;
    sources?: Source[];
    name?: string;
    query?: string;
    count?: number;
  };

  applyToolEvent(event, answer);
  if (event.type === 'token') answer.content += event.text ?? '';
  if (event.type === 'sources') answer.sources = event.sources ?? [];
  if (event.type === 'status') status.value = event.message ?? '';
  if (event.type === 'error') throw new Error(event.message ?? '生成失败');
  if (event.type === 'done') answer.complete = true;
  void scroll();
}

function requestError(error: unknown) {
  if (!(error instanceof Error)) return '请求失败';

  return error.name === 'AbortError' ? '已停止生成' : error.message;
}

async function send(text = input.value) {
  if (busy.value || !text.trim() || !current.value) return;
  const conversation = current.value;
  const question = text.trim();

  if (question.length > 6000) {
    notice.value = '问题请控制在 6000 字以内。';

    return;
  }
  conversation.messages.push({ role: 'user', content: question });
  conversation.title = question.slice(0, 24);

  conversation.messages.push({ role: 'assistant', content: '', sources: [] });

  const answer = conversation.messages[conversation.messages.length - 1]!;

  input.value = '';
  busy.value = true;
  status.value = '正在连接';
  controller = new AbortController();
  await scroll();
  try {
    const response = await fetch('/api/game/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        conversation_id: conversation.id,
        request_id: crypto.randomUUID(),
        message: question,
        tool_calling: toolCalling.value,
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      const error = (await response.json()) as { detail?: unknown };
      throw new Error(typeof error.detail === 'string' ? error.detail : '请求失败，请稍后重试');
    }
    if (!response.body) throw new Error('浏览器不支持流式响应');
    await consumeStream(response.body, (data) => applyEvent(data, answer));
    if (!answer.complete) throw new Error('连接中断，请重新提问');
  } catch (error) {
    answer.error = requestError(error);
  } finally {
    busy.value = false;
    status.value = '';
    await scroll();
  }
}

async function importDoc() {
  if (!title.value.trim() || !content.value.trim() || importing.value) return;
  importing.value = true;
  try {
    const response = await fetch('/api/game/knowledge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: title.value, content: content.value }),
    });

    if (!response.ok) throw new Error('导入失败，请检查内容长度');
    title.value = '';
    content.value = '';
    showImport.value = false;
    await refresh();
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '导入失败';
  } finally {
    importing.value = false;
  }
}

async function upload(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  if (file.size > 80000) {
    notice.value = '文件过大，请导入不超过 20000 字的 Markdown 或文本。';

    return;
  }
  content.value = await file.text();
  title.value = file.name.replace(/\.(md|txt)$/i, '');
}

async function removeDoc(doc: Source) {
  if (!window.confirm(`删除「${doc.title}」？`)) return;
  try {
    const response = await fetch(`/api/game/knowledge/${encodeURIComponent(doc.id)}`, {
      method: 'DELETE',
    });

    if (!response.ok) throw new Error('删除失败');
    detail.value = null;
    await refresh();
  } catch {
    notice.value = '删除失败，请重试。';
  }
}

onMounted(() => {
  void refresh();
  void loadConversations();
});
</script>
