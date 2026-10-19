<template>
  <section class="ops-page rag-lab">
    <div class="ops-page-heading">
      <div>
        <h1>检索实验室</h1>
        <p>用同一份标注比较检索策略，查看命中证据与失败案例。</p>
      </div>
      <button
        class="ops-primary"
        :disabled="!report"
        @click="download"
      >
        导出报告 JSON
      </button>
    </div>
    <p class="rag-note">
      支持词法、同义词扩展、本地向量与混合检索。向量分数是余弦相似度，混合分数是 RRF；
      不同策略分数不能直接比较，评测结果也不代表答案准确率。
    </p>
    <div class="rag-controls">
      <label>
        返回片段 K
        <input
          v-model.number="topK"
          type="number"
          min="1"
          max="20"
        >
      </label>
      <label>
        最低 BM25 分数
        <input
          v-model.number="minScore"
          type="number"
          min="0"
          step="0.1"
        >
      </label>
      <label>
        最低向量相似度
        <input
          v-model.number="minSimilarity"
          type="number"
          min="-1"
          max="1"
          step="0.05"
        >
      </label>
      <label>
        向量存储
        <select v-model="vectorBackend">
          <option value="pgvector">PostgreSQL · pgvector</option>
          <option value="local">本地扫描 · 对照基线</option>
        </select>
      </label>
      <label v-if="vectorBackend === 'pgvector'">
        向量查询模式
        <select v-model="vectorSearchMode">
          <option value="exact">精确检索</option>
          <option value="hnsw">HNSW 近似检索</option>
        </select>
      </label>
    </div>
    <section class="rag-card">
      <h2>单题检索 · 当前知识库</h2>
      <form
        class="rag-controls"
        @submit.prevent="search"
      >
        <label class="rag-grow">
          问题
          <input
            v-model="query"
            required
            maxlength="1000"
            placeholder="例如：奖励没到账"
          >
        </label>
        <label>
          策略
          <select v-model="strategy">
            <option value="bm25">BM25 基线</option>
            <option value="expanded_bm25">同义词扩展 BM25</option>
            <option value="vector">向量检索</option>
            <option value="hybrid">混合检索 · BM25 + 向量</option>
          </select>
        </label>
        <button
          class="ops-primary"
          :disabled="busy || !query.trim()"
        >
          {{ busy ? '运行中…' : '检索证据' }}
        </button>
      </form>
      <template v-if="searchResult">
        <p>
          知识版本 {{ searchResult.trace.revision }} · {{ searchResult.trace.chunk_count }} 个片段 ·
          {{ searchResult.trace.candidate_count }} 个候选 ·
          {{ searchResult.trace.cache_hit ? '缓存命中（耗时为原检索记录）' : '本次计算' }}
        </p>
        <p>实际检索词：{{ searchResult.trace.expanded_query }}</p>
        <p v-if="searchResult.trace.embedding_model">
          本地模型：{{ searchResult.trace.embedding_model.split(':')[0] }} ·
          {{ searchResult.trace.embedding_dimension }} 维 · 分数类型
          {{ searchResult.trace.score_type }}
        </p>
        <p v-if="searchResult.trace.vector_backend">
          检索后端：{{ searchResult.trace.vector_backend }} · 模式：{{
            searchResult.trace.vector_search_mode
          }}
        </p>
        <p v-if="!searchResult.sources.length">
          没有达到阈值的证据。请补充条件或导入资料。
        </p>
        <details
          v-for="source in searchResult.sources"
          :key="source.id"
        >
          <summary>{{ source.title }} · {{ source.id }} · 分数 {{ source.score }}</summary>
          <p>{{ source.content }}</p>
          <small v-if="source.matched_terms.length">
            命中词：{{ source.matched_terms.join('、') }}
          </small>
          <p v-if="source.vector_score !== undefined">
            向量相似度：{{ source.vector_score }}
          </p>
          <p v-if="source.bm25_rank !== undefined">
            BM25 排名 {{ source.bm25_rank ?? '未召回' }} · 向量排名
            {{ source.vector_rank ?? '未召回' }}
          </p>
        </details>
      </template>
    </section>
    <section class="rag-card">
      <h2>批量对比评测</h2>
      <div class="rag-controls">
        <label>
          评测数据
          <select v-model="corpus">
            <option value="fixture">固定演示语料与题集</option>
            <option value="current">当前知识库 + 自定义标注</option>
          </select>
        </label>
        <button
          class="ops-primary"
          :disabled="busy"
          @click="evaluate"
        >
          {{ busy ? '运行中…' : includeVectors ? '运行四种策略' : '运行词法对比' }}
        </button>
      </div>
      <label class="rag-checkbox">
        <input
          v-model="includeVectors"
          type="checkbox"
        >
        加入向量与混合检索（需先准备本地模型）
      </label>
      <p>相似度阈值需通过业务题集校准；混合检索保留任一路达标的候选，再按 RRF 融合排序。</p>
      <p v-if="corpus === 'fixture'">
        内置 13
        题是开发样例，含同义表达、多文档与无答案问题。请另建未参与调参的业务测试集验证泛化效果。
      </p>
      <template v-else>
        <p>
          填写 JSON 数组。relevant 的键为文档 ID，值为相关性等级 1–3；无答案用
          {}。删除标注文档后需更新题集。
        </p>
        <label>
          人工标注题集
          <textarea
            v-model="caseJson"
            rows="7"
            spellcheck="false"
          />
        </label>
        <details>
          <summary>查看当前文档 ID</summary>
          <p
            v-for="doc in documents"
            :key="doc.id"
          >
            <code>{{ doc.id }}</code>
            — {{ doc.title }}
          </p>
        </details>
      </template>
      <p
        v-if="error"
        role="alert"
        class="rag-error"
      >
        {{ error }}
      </p>
    </section>
    <section
      v-if="report"
      class="rag-card"
      aria-live="polite"
    >
      <h2>评测结果 · K={{ report.top_k }}</h2>
      <p>{{ report.scope }}</p>
      <p>向量后端 {{ report.vector_backend }} · 查询模式 {{ report.vector_search_mode }}</p>
      <p>BM25 阈值 {{ report.min_score }} · 向量阈值 {{ report.min_similarity }}</p>
      <p>
        {{ report.document_count }} 篇文档 · {{ report.chunk_count }} 个片段 ·
        {{ report.dataset_name }} · {{ report.created_at }}
      </p>
      <div class="rag-table-wrap">
        <table>
          <thead>
            <tr>
              <th>策略</th>
              <th>Recall@K ↑</th>
              <th>MRR ↑</th>
              <th>nDCG@K ↑</th>
              <th>无答案误召回率 ↓</th>
              <th>P95 检索 ms</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="run in report.reports"
              :key="run.strategy"
            >
              <td>{{ strategyName(run.strategy) }}</td>
              <td>{{ percent(run.summary.recall) }}</td>
              <td>{{ percent(run.summary.mrr) }}</td>
              <td>{{ percent(run.summary.ndcg) }}</td>
              <td>{{ percent(run.summary.false_positive_rate) }}</td>
              <td>{{ run.summary.p95_search_ms }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p>
        相关文档按 ID 去重；同一文档的重复片段仍占 K 配额。无答案题不计入 Recall / MRR / nDCG。—
        表示没有适用样本。
      </p>
      <details>
        <summary>指标口径与可复现标识</summary>
        <p>
          Recall：找回的相关文档比例。MRR：首个相关文档排名倒数。nDCG：考虑相关性等级的排序质量。误召回：无答案题仍返回片段的比例。耗时仅为本机检索微基准。
        </p>
        <p>策略版本：{{ report.version }}</p>
        <p>语料 SHA256：{{ report.corpus_hash }}</p>
        <p>题集 SHA256：{{ report.dataset_hash }}</p>
      </details>
      <div
        v-for="run in report.reports"
        :key="run.strategy"
      >
        <h3>{{ strategyName(run.strategy) }} · 逐题证据</h3>
        <details
          v-for="row in run.cases"
          :key="row.id"
        >
          <summary>
            {{ row.query }} ·
            {{
              row.metrics.recall === null
                ? row.metrics.false_positive
                  ? '无答案误召回'
                  : '正确空召回'
                : `Recall ${percent(row.metrics.recall)}`
            }}
          </summary>
          <p>
            标注：{{ JSON.stringify(row.relevant) }} · 实际：{{
              row.metrics.retrieved_document_ids.join('、') || '无'
            }}
          </p>
          <p>检索词：{{ row.trace.expanded_query }}</p>
          <div
            v-for="source in row.sources"
            :key="source.id"
            class="rag-evidence"
          >
            <b>{{ source.title }} · {{ source.id }} · {{ source.score }}</b>
            <p>{{ source.content }}</p>
          </div>
        </details>
      </div>
    </section>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue';

defineProps<{ documents: { id: string; title: string }[] }>();
type Source = {
  id: string;
  title: string;
  content: string;
  score: number;
  matched_terms: string[];
  vector_score?: number;
  bm25_rank?: number | null;
  vector_rank?: number | null;
};
type SearchResult = {
  sources: Source[];
  trace: {
    revision?: number;
    chunk_count: number;
    candidate_count: number;
    cache_hit?: boolean;
    expanded_query: string;
    embedding_model?: string;
    embedding_dimension?: number;
    score_type?: string;
    vector_backend?: string;
    vector_search_mode?: string;
  };
};
type CaseResult = SearchResult & {
  id: string;
  query: string;
  relevant: Record<string, number>;
  metrics: {
    recall: number | null;
    false_positive: boolean | null;
    retrieved_document_ids: string[];
  };
};
type Report = {
  top_k: number;
  min_score: number;
  min_similarity: number;
  vector_backend: string;
  vector_search_mode: string;
  scope: string;
  document_count: number;
  chunk_count: number;
  dataset_name: string;
  created_at: string;
  version: string;
  corpus_hash: string;
  dataset_hash: string;
  reports: {
    strategy: string;
    summary: {
      recall: number | null;
      mrr: number | null;
      ndcg: number | null;
      false_positive_rate: number | null;
      p95_search_ms: number;
    };
    cases: CaseResult[];
  }[];
};
const topK = ref(4);
const minScore = ref(0);
const minSimilarity = ref(0.35);
const includeVectors = ref(true);
const vectorBackend = ref('pgvector');
const vectorSearchMode = ref('exact');
const query = ref('轮播图看不到');
const strategy = ref('bm25');
const corpus = ref('fixture');
const busy = ref(false);
const error = ref('');
const searchResult = ref<SearchResult | null>(null);
const report = ref<Report | null>(null);

const caseJson = ref(
  '[\n  {"id":"gift-1","query":"礼包领取失败","relevant":{"game-gift":3}},\n  {"id":"unknown-1","query":"火星天气预报","relevant":{}}\n]',
);

const percent = (value: number | null) => (value === null ? '—' : `${(value * 100).toFixed(1)}%`);

const strategyName = (value: string) =>
  ({
    bm25: 'BM25 基线',
    expanded_bm25: '同义词扩展 BM25',
    vector: '向量检索',
    hybrid: '混合检索 · RRF',
  })[value] || value;

async function request(path: string, body: unknown) {
  const response = await fetch(`/api/game/retrieval/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  const result = await response.json();
  if (!response.ok)
    throw new Error(
      typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail || result),
    );

  return result;
}

async function runAction(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  error.value = '';
  try {
    await action();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '请求失败';
  } finally {
    busy.value = false;
  }
}

async function search() {
  searchResult.value = null;
  await runAction(async () => {
    searchResult.value = await request('search', {
      query: query.value,
      strategy: strategy.value,
      top_k: topK.value,
      min_score: minScore.value,
      min_similarity: minSimilarity.value,
      vector_backend: vectorBackend.value,
      vector_search_mode: vectorBackend.value === 'local' ? 'exact' : vectorSearchMode.value,
    });
  });
}

async function evaluate() {
  report.value = null;
  await runAction(async () => {
    const cases = corpus.value === 'current' ? JSON.parse(caseJson.value) : undefined;

    report.value = await request('evaluate', {
      corpus: corpus.value,
      top_k: topK.value,
      min_score: minScore.value,
      min_similarity: minSimilarity.value,
      vector_backend: vectorBackend.value,
      vector_search_mode: vectorBackend.value === 'local' ? 'exact' : vectorSearchMode.value,
      cases,
      strategies: includeVectors.value
        ? ['bm25', 'expanded_bm25', 'vector', 'hybrid']
        : ['bm25', 'expanded_bm25'],
    });
  });
}

function download() {
  if (!report.value) return;

  const url = URL.createObjectURL(
    new Blob([JSON.stringify(report.value, null, 2)], { type: 'application/json' }),
  );

  const link = document.createElement('a');

  link.href = url;
  link.download = `rag-evaluation-${report.value.created_at.replace(/[:.]/g, '-')}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
</script>

<style scoped>
.rag-lab {
  overflow-y: auto;
}
.rag-note {
  color: #526375;
  line-height: 1.7;
}
.rag-card {
  background: white;
  border: 1px solid #dce4ec;
  padding: 24px;
  border-radius: 16px;
  margin: 20px 0;
}
.rag-card h2 {
  margin-top: 0;
  font-size: 19px;
}
.rag-card p {
  line-height: 1.7;
  overflow-wrap: anywhere;
}
.rag-controls {
  display: flex;
  align-items: end;
  gap: 16px;
  flex-wrap: wrap;
}
.rag-grow {
  flex: 1;
  min-width: 200px;
}
label {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 14px;
}
input,
select,
textarea {
  border: 1px solid #c6d2df;
  border-radius: 8px;
  padding: 10px;
  font: inherit;
  background: white;
  color: #203348;
}
textarea {
  width: 100%;
  box-sizing: border-box;
}
input[type='number'] {
  width: 125px;
}
.rag-table-wrap {
  overflow-x: auto;
}
table {
  border-collapse: collapse;
  width: 100%;
  white-space: nowrap;
}
th,
td {
  text-align: left;
  padding: 14px;
  border-bottom: 1px solid #e0e6ed;
}
th {
  background: #f3f7fb;
  font-size: 13px;
}
details {
  padding: 12px 0;
  border-bottom: 1px solid #e0e6ed;
}
summary {
  cursor: pointer;
  line-height: 1.7;
}
.rag-evidence {
  padding: 12px;
  margin: 8px 0;
  border-radius: 8px;
  background: #f3f7fb;
}
.rag-checkbox {
  flex-direction: row;
  margin-top: 16px;
  align-items: center;
}
.rag-error {
  color: #ad2430;
}
button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
