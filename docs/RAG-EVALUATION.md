# 运营检索实验室

在主应用左侧打开「检索实验室」。无需配置新的模型服务。词法评测不调用模型；向量评测使用本机 ONNX Embedding，不调用远程模型 API。

## 当前交付

- **单题检查**：对当前 PostgreSQL 知识库检索，可选择 BM25、运营同义词扩展 BM25、向量检索或 RRF 混合检索，设置 K、最低 BM25 分数与最低向量相似度，查看真实片段、文档 ID、命中词、扩展后的查询、知识版本与缓存状态。
- **批量对比**：支持本地扫描与 PostgreSQL pgvector 两种后端；同一语料快照、同一题集与阈值下比较勾选的词法 / 向量策略；报告可导出 JSON。
- **固定开发集**：8 篇演示文档、13 题（10 道有答案、3 道无答案）；词法或本地扫描不依赖 PostgreSQL / Redis，pgvector 评测需要已迁移的数据库。
- **业务题集**：选择当前知识库，粘贴人工标注 JSON；不存在的文档 ID、重复题号、空题集和非法参数返回 422。
- **线上共用实现**：运营问答与实验室使用 `RetrievalIndex`。正式问答默认 BM25、K=4，可通过 `GAME_RETRIEVAL_STRATEGY=vector|hybrid` 切换；评测不会自动修改配置。

同义词扩展是显式领域词表；向量策略才使用真实 Embedding。内置题目和词表同时用于开发，不能用它们的分数声称业务泛化效果。请另外建立不参与调参的测试集。

## 运行

```bash
.venv/bin/python scripts/evaluate-game-rag.py --top-k 4 --output data/rag-evaluation.json
# 对比更小 K 或提高阈值；不要只优化召回而忽略误召回
.venv/bin/python scripts/evaluate-game-rag.py --top-k 1 --min-score 1 --output data/rag-evaluation-k1.json
```

固定题集在 `apps/api/studio/datasets/game_rag_v1.json`，维护时提交代码评审。正式验收应另建不参与词表调整、Prompt 优化或阈值调参的测试集。

当前知识库的标注格式：

```json
[
  {"id":"gift-1","query":"礼包领取失败怎么处理","relevant":{"game-gift":3}},
  {"id":"no-answer-1","query":"火星天气预报","relevant":{}}
]
```

`relevant` 的键是文档 ID（不是分块 ID），值为 1–3 的相关性等级，3 为最相关。一个问题可标注多个文档，无答案题为空对象。页面可查看当前文档 ID。删掉被标注文档后应显式更新题集，系统不会静默忽略失效标注。

## 指标定义

K 是返回的**片段数**；取前 K 个片段后按文档 ID 去重，保留首次出现顺序，再计算文档级排序指标。重复片段占用 K 配额，不会重复加分。文档级 MRR/nDCG 使用去重后的排名。

| 指标 | 定义 |
| --- | --- |
| Recall@K | 找回的相关文档数 / 全部标注相关文档数 |
| MRR | 首个相关文档在去重结果中排名的倒数；未命中为 0 |
| nDCG@K | DCG / 理想 DCG，增益为 `2^grade - 1`，折扣为 `log2(rank + 1)` |
| 无答案误召回率 | 无答案题中返回任意片段的比例 |
| P95 search ms | nearest-rank P95，索引构建完成后各题检索的本机耗时 |

Recall、MRR、nDCG 仅在有答案题上宏平均；无答案误召回率仅使用无答案题。没有对应题目时返回 null（页面显示 —），不能用 0 冒充测量结果。

这不是答案正确率或引用忠实度评测。空检索也不等于 LLM 已正确拒答。单次小样本 P95 不适合做容量承诺：它排除了词法索引构建、文档向量准备与答案生成；pgvector 模式的检索耗时包含数据库往返，向量策略的 `search_ms` 包含查询向量获取；批量评测统一预热文档和所有问题向量，避免先跑的向量策略承担冷启动而后跑的混合策略命中缓存。报告另列 `index_build_ms`、`vector_warmup_ms` 和逐题 `vector_prepare_ms`；缓存命中时 trace 中耗时是原始计算记录。

## 可复现性与缓存

报告包含策略版本、语料 SHA256、题集 SHA256、K、阈值、UTC 时间、知识版本以及逐题证据。语料哈希不受输入文档顺序影响。评分相同时以片段 ID 排序。修改排序算法、分块策略或同义词表时必须同步升级 `game_retrieval.VERSION`。

当前语料和知识版本在同一 PostgreSQL 语句中读取，避免分别读取带来的版本错配。Redis 缓存键包含知识版本、策略版本、查询、策略、K、两类阈值、候选数及 Embedding 指纹；文档导入和删除后旧版本不会命中。评测直接使用一个不可变快照，不经过 Redis 缓存，不写入业务知识或会话。pgvector 评测会持久化独立语料快照的派生向量。

## API

- `POST /api/game/retrieval/search`：`query`、`strategy`、`top_k`、`min_score`。
- `GET /api/game/retrieval/dataset`：固定开发语料与题集。
- `POST /api/game/retrieval/evaluate`：`corpus=fixture|current`、`top_k`、`min_score`、可选 `cases`；current 必须提供 cases。

最多 200 题，问题最多 1000 字，K 范围 1–20，阈值为非负有限数。候选数范围 20–200，向量相似度范围 -1–1。当前仍继承项目单运营身份边界；评测不是新增用户鉴权机制。检索仍在进程内构建词法索引，大规模语料需要独立索引服务与资源限额。


## 本地向量模型与混合检索

```bash
.venv/bin/pip install -r apps/api/requirements.txt
.venv/bin/python scripts/prepare-game-embeddings.py
.venv/bin/python scripts/evaluate-game-rag.py --with-vectors --output data/rag-vectors.json
```

使用 FastEmbed 0.7.4 / ONNX Runtime，模型为 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`，输出 384 维。下载源固定为 Qdrant 的量化 ONNX 仓库及提交 `faf4aa4225822f3bc6376869cb1164e8e3feedd0`。首次准备需下载约 220 MB 权重和分词器，正常检索仅加载本地文件；缺少或损坏模型时明确返回 503，不伪装成 BM25 成功。

下载脚本使用标准 HTTP、支持续传，业务文本只在本机计算。模型缓存默认 `data/embeddings/models`；设置 `GAME_EMBEDDING_CACHE_DIR` 时，请在准备脚本与服务进程使用同一目录（独立 Python 脚本不会自动读取 `.env`）。

该模型实际分词器限制 128 token。输入按最多 120 token、步长 104 切窗，逐窗编码后归一化并平均，再次归一化；因此片段尾部也参与计算。这个聚合策略包含在模型指纹中，并不是训练新的 Embedding 模型。长问题也使用相同处理。

向量以余弦相似度排序；默认阈值 0.35 只是起始参数，不是正确性保证。混合策略分别取 BM25 与向量前 `candidate_k=40` 个达标候选，以 `1 / (60 + rank)` 累加 RRF 分数。候选可以只被其中一路召回；提高向量阈值不会排除被 BM25 召回的文档。BM25 原始分数、cosine、RRF 的量纲不同，不能比较大小。

文档仍以 PostgreSQL 为准。派生向量缓存保存在本地 `vectors.sqlite3`，键包含真实模型文件指纹、FastEmbed 版本、聚合策略、文本哈希与 query/document 类型。内容不变可复用；修改内容或模型会重新计算。知识删除后旧向量不会出现在当前语料候选中；缓存文件不会自动物理清除旧条目，需要清理时停止服务再删除派生缓存文件，重启后自动重建。

当前已支持 **PostgreSQL pgvector**。API 的向量检索默认使用数据库精确扫描，可选择 HNSW 近似模式；原本地扫描保留为离线评测对照。详见下节。

正式问答启用混合检索：

```dotenv
GAME_RETRIEVAL_STRATEGY=hybrid
GAME_MIN_SIMILARITY=0.35
GAME_EMBEDDING_CACHE_DIR=data/embeddings
```

先准备模型再重启 API；普通问答与 Tool Calling 都通过相同仓库检索方法使用配置。默认 `bm25` 保证未下载模型时原问答仍可运行。

Compose 中缓存位于持久卷 `/data/embeddings`，首次运行 `docker compose exec api python scripts/prepare-game-embeddings.py`；再通过 `.env` 设置策略并重建 API 容器配置。模型下载与 Docker 部署需在目标环境单独验证。

API 检索支持 `strategy=vector|hybrid`、`min_similarity`、`candidate_k`；评测支持 `strategies=["bm25","expanded_bm25","vector","hybrid"]`。不传 strategies 仍只跑原先两种词法策略，便于离线回归不依赖模型文件。报告的逐题 trace 包含模型指纹、维度、分数类型和向量准备耗时。


## pgvector 接入与迁移

要求 PostgreSQL 已安装 pgvector >= 0.8.0（扩展位于 `public` schema）。项目 Compose 与 CI 使用 `pgvector/pgvector:0.8.2-pg16`，保持 PostgreSQL 16 主版本；不要将旧数据库卷直接挂到不同 PostgreSQL 主版本。

```bash
# 自动读取项目 .env；重复运行安全，不删除原有数据
npm run migrate:vector
# 可选：提前向量化当前知识库，避免首个请求承担建索引耗时
npm run migrate:vector -- --build-index
# 使用固定开发集分别评测数据库精确查询、HNSW 查询
npm run eval:rag -- --with-vectors --backend pgvector --search-mode exact --output data/rag-pgvector-exact.json
npm run eval:rag -- --with-vectors --backend pgvector --search-mode hnsw --output data/rag-pgvector-hnsw.json
```

迁移新增 `rag_vector_sets`、`rag_vectors`，向量列为 `public.vector(384)`，HNSW 使用 `vector_cosine_ops`，参数 `m=16`、`ef_construction=64`。使用 psycopg 参数绑定传递向量字面量，不拼接用户 SQL。`CREATE EXTENSION` 需要足够数据库权限；正式环境建议由迁移账号执行，运行账号仅负责数据读写。缺少扩展或表时返回明确的 503，不自动退回本地检索。

```dotenv
GAME_RETRIEVAL_STRATEGY=hybrid
GAME_VECTOR_BACKEND=pgvector
GAME_VECTOR_SEARCH_MODE=exact
```

将 `GAME_VECTOR_SEARCH_MODE` 改为 `hnsw` 可允许近似检索；可通过 `GAME_VECTOR_BACKEND=local` 显式使用原本地扫描。API 请求中的 `vector_backend` / `vector_search_mode` 与环境配置独立，实验室选择不自动修改正式问答配置。

- **精确模式**：事务内禁用 index scan，按 `<=>` 余弦距离排序，并用 chunk ID 稳定处理同分；这是检索质量对照基线。
- **HNSW 模式**：按距离算子排序，启用 `hnsw.iterative_scan=strict_order`，`ef_search=max(100,candidate_k)`。小表可能被优化器选择顺序扫描；模式名称不是实际执行计划保证。集成测试使用 EXPLAIN 验证 HNSW 索引可用。
- **近似召回限制**：HNSW 使用快照过滤后，即使启用迭代扫描仍受扫描预算影响，可能少于 K 或漏召回。不要把小样例上与精确结果一致当成生产召回保证。

索引快照 ID 由检索版本、语料内容哈希和模型指纹计算。构建事务一次写入完整快照，事务锁避免并发重复发布；推理失败不留下半成品。每个查询都使用完整快照 ID 过滤，禁止在不同模型或语料间混搜。文档更新或删除后产生新快照，因此原向量不参与当前知识检索。Redis 缓存也包含后端和查询模式，切换不会复用错误结果。

SQLite 现在仅是本地 Embedding 计算缓存；pgvector 模式的排名计算与持久化向量位于 PostgreSQL。旧 PostgreSQL 快照保留以便回归对照，**删除知识文档不会物理清除旧快照中的正文与向量**。需要彻底清除或控制容量时，停用相关评测后由管理员按保留策略删除旧 `rag_vector_sets`，其子向量级联删除；不要删除仍用于在途请求或保留评测的快照。当前没有自动垃圾回收任务。

Compose 启动后执行 `docker compose exec api python scripts/migrate-game-pgvector.py --build-index`（模型必须先准备）。本轮已在本机 PostgreSQL 验证迁移、真实模型建索引、精确和 HNSW 查询；容器和远程 CI 仍需在目标环境运行。
