import type { Source } from '@studio/shared';

export const documents = [
  {
    id: 'agent',
    title: 'Agent 工作原理',
    content:
      'AI Agent 由大语言模型、工具、记忆和执行循环组成。模型根据任务选择工具，读取工具结果，再决定继续调用还是生成最终回答。LangChain createAgent 基于 LangGraph 运行，可设置递归上限防止无限循环。',
  },
  {
    id: 'rag',
    title: 'RAG · 检索增强生成',
    content:
      'RAG 流程是文档加载、分块、Embedding 向量化、向量数据库检索、结合上下文生成带来源的答案。生产环境可以使用 PostgreSQL + pgvector 或 Qdrant。当前示例用本地关键词检索，无 Embedding 调用，支持中文双字切分。',
  },
  {
    id: 'memory',
    title: 'Memory · 会话记忆',
    content:
      '短期记忆保存对话上下文，长期记忆保存用户偏好和跨会话事实。LangGraph Checkpointer 可持久化图状态。当前项目把会话保存在浏览器 localStorage，每次请求携带最近 20 条消息；生产环境需迁移至数据库并按用户隔离。',
  },
  {
    id: 'tools',
    title: 'Tools · 工具调用',
    content:
      '使用 LangChain tool 和 Zod 定义工具输入。此项目包含知识库检索与四则运算工具。模型只可调用已注册工具。生产写操作需权限检查、人工审批和审计记录，工具输出应当作为不可信数据处理。',
  },
  {
    id: 'architecture',
    title: '全栈架构与可观测性',
    content:
      '前端使用 Vue 3、TypeScript、Vite；后端使用 Node.js、Express、LangChain 和 Zod。通过 POST + SSE 流式推送文本、工具事件和引用来源。可选接入 LangSmith 追踪模型与工具调用。密钥仅在服务端读取。',
  },
];

function terms(text: string) {
  const normalized = text.toLowerCase();
  const latin = normalized.match(/[a-z0-9]+/g) ?? [];

  const chinese = (normalized.match(/[\u4e00-\u9fff]+/g) ?? []).flatMap((run) =>
    Array.from({ length: Math.max(0, run.length - 1) }, (_, i) => run.slice(i, i + 2)),
  );

  return [...new Set([...latin, ...chinese])];
}

function matches(content: string, term: string) {
  const normalized = content.toLowerCase();
  const words: string[] = normalized.match(/[a-z0-9]+/g) ?? [];

  return /^[a-z0-9]+$/.test(term) ? words.includes(term) : normalized.includes(term);
}

export function searchKnowledge(query: string): Source[] {
  const tokens = terms(query);

  return documents
    .map((doc) => ({
      ...doc,
      score: tokens.reduce((n, t) => n + (matches(`${doc.title} ${doc.content}`, t) ? 1 : 0), 0),
    }))
    .filter((d) => d.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 3);
}
