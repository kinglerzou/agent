"""Chunked lexical RAG: Chinese bigrams + BM25, bounded revision-aware LRU cache."""
import math
import re
from collections import Counter, OrderedDict

SEEDS = [
    ('agent', 'Agent Loop 与编排', 'Agent Loop 循环执行：选择动作、校验工具参数、执行工具、读取 observation，直到完成或达到预算。ReAct 逐步选择动作；Plan-and-Execute 先生成计划再执行。Mock 使用确定性规则，不是模型推理。'),
    ('rag', 'RAG 知识引擎', 'RAG 包含文档导入、分块、检索、上下文拼装和引用生成。本工程用中文双字分词与 BM25 排序，缓存带知识版本失效。不调用 Embedding；向量检索可扩展为 pgvector，混合检索通过 RRF 融合。'),
    ('memory', '上下文工程与记忆', '上下文工程按优先级分配预算：系统规则、当前问题、长期记忆、检索证据和最近历史。短期记忆是对话历史，长期记忆保存明确要求记住的事实。记忆按 session 隔离并允许删除；字符预算只是 token 预算的保守近似。'),
    ('sandbox', '工具、Skills 与沙箱', '工具必须验证输入并执行白名单策略。沙箱用受限 AST 解释算术表达式，禁止导入、属性访问、函数调用和文件网络访问；它不执行任意 Python。Skills 是带元数据的任务操作指南。运行任意代码需要独立容器、资源配额和网络隔离。'),
    ('mcp', 'MCP 工具协议', 'MCP 使用 JSON-RPC 2.0 连接模型应用与工具服务。此工程实现 initialize、notifications/initialized、tools/list 和 tools/call 的无状态 HTTP 教学子集；不是完整 MCP 客户端或完整传输实现。工具输出始终是不可信数据。'),
    ('observability', '可观测性与评测闭环', 'Trace 记录 run_id、事件序号、时间、工具输入输出与执行状态。评测使用固定任务集测量答案、检索引用、工具准确率和延迟。反馈归档失败案例，比较基线与候选策略，人工决定发布，禁止自动把低质量反馈写进系统提示词。'),
    ('distributed', '分布式系统与可靠性', '任务队列将请求接收与执行解耦。SQLite 事务领取任务、持久化检查点和崩溃恢复只适合单机 worker。生产采用消息队列、幂等键、租约、心跳、重试退避、死信队列和共享数据库。缓存必须考虑一致性、容量和失效策略。'),
    ('engineering', '全栈工程与质量保障', 'Python FastAPI 提供 API 和 SSE，Vue3 TypeScript 提供交互，ESLint 执行代码检查。pytest 覆盖工具安全、上下文、RAG、HTTP 和取消。Docker、Kubernetes、CI、性能压测与故障注入用于交付；生产还需鉴权、租户隔离、监控告警和容量规划。'),
]


def terms(text):
    words = re.findall(r'[a-z0-9]+', text.lower())
    for group in re.findall(r'[\u4e00-\u9fff]+', text):
        words.extend(group[i:i + 2] for i in range(len(group) - 1))
    return words


class Knowledge:
    def __init__(self, store, seeds=None):
        self.store = store
        self.cache = OrderedDict()
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS knowledge_meta (key TEXT PRIMARY KEY)')
            if not db.execute("SELECT 1 FROM knowledge_meta WHERE key='seeded'").fetchone():
                db.executemany('INSERT OR IGNORE INTO documents VALUES(?,?,?)', SEEDS if seeds is None else seeds)
                db.execute("INSERT INTO knowledge_meta VALUES('seeded')")

    def documents(self):
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM documents ORDER BY id')]

    def add(self, title, content):
        import uuid
        doc_id = str(uuid.uuid4())[:8]
        with self.store.connect() as db:
            db.execute('INSERT INTO documents VALUES(?,?,?)', (doc_id, title, content))
        self.cache.clear()
        return doc_id

    def search(self, query, top_k=3):
        key = (query, top_k)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        chunks = []
        for doc in self.documents():
            for start in range(0, len(doc['content']), 280):
                chunks.append(dict(doc, id=f"{doc['id']}:{start // 280}", content=doc['content'][start:start + 360]))
        tokens = [Counter(terms(d['title'] + ' ' + d['content'])) for d in chunks]
        avg = sum(sum(t.values()) for t in tokens) / max(len(tokens), 1)
        result = []
        for doc, counts in zip(chunks, tokens):
            score = 0.0
            for term in set(terms(query)):
                frequency = counts[term]
                df = sum(term in t for t in tokens)
                idf = math.log(1 + (len(tokens) - df + .5) / (df + .5))
                score += idf * frequency * 2.5 / (frequency + 1.5 * (.25 + .75 * sum(counts.values()) / max(avg, 1)))
            if score > 0:
                result.append(dict(doc, score=round(score, 4)))
        result.sort(key=lambda d: (-d['score'], d['id']))
        self.cache[key] = result[:top_k]
        if len(self.cache) > 128:
            self.cache.popitem(last=False)
        return self.cache[key]
