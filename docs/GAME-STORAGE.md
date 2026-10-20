# 游戏中心运营助手存储字典

本文按当前仓库实现整理，覆盖 `/api/game` 的 **8 张 PostgreSQL 表和 3 类 Redis 键**。这是代码层面的结构说明，不代表已经检查某个运行环境的实际数据库。基础迁移创建 6 张表；另外 2 张向量表需要显式执行向量迁移。

PostgreSQL 保存正式数据，Redis 保存可重建的缓存和临时生成锁。Redis 没有关系型数据库的“表”，下文按键类别说明。

## 查阅目录

- [存储总览与关联](#存储总览与关联)
- [conversations：咨询会话](#conversations咨询会话)
- [turns：每轮问答](#turns每轮问答)
- [documents：知识原文](#documents知识原文)
- [knowledge_state：知识版本](#knowledge_state知识版本)
- [schema_versions：数据库结构版本](#schema_versions数据库结构版本)
- [data_imports：数据导入标记](#data_imports数据导入标记)
- [rag_vector_sets：向量快照元数据](#rag_vector_sets向量快照元数据)
- [rag_vectors：知识分块向量](#rag_vectors知识分块向量)
- [Redis 键字典](#redis-键字典)
- [一轮问答的读写流程](#一轮问答的读写流程)
- [常用只读查询](#常用只读查询)
- [代码索引与范围说明](#代码索引与范围说明)

## 存储总览与关联

默认数据库连接指向 `game_ops` 数据库，业务 schema 默认也是 `game_ops`，分别由 `GAME_DATABASE_URL` 和 `GAME_DB_SCHEMA` 配置。数据库名和 schema 名是两个独立概念。下文 SQL 使用默认 schema，其他环境需替换。

| 存储对象          | 每条记录代表什么           | 主要用途                         |
| ----------------- | -------------------------- | -------------------------------- |
| `conversations`   | 一个咨询会话               | 会话列表、归属、标题、上下文版本 |
| `turns`           | 一次提问及对应回答         | 历史、状态、请求去重、答案回放   |
| `documents`       | 一份知识文档               | 检索的权威原文                   |
| `knowledge_state` | 全局知识版本，固定一行     | 检索缓存失效                     |
| `schema_versions` | 一个已应用的结构版本       | 标记迁移版本                     |
| `data_imports`    | 一次具名导入的标记         | 防止重复导入种子或旧知识         |
| `rag_vector_sets` | 一个不可变的向量快照       | 区分语料、模型与检索版本         |
| `rag_vectors`     | 某个快照中的一个知识分块   | 保存分块正文和 384 维向量        |
| Redis `context:*` | 某会话某版本的最近完整问答 | 减少历史查询                     |
| Redis `search:*`  | 某知识版本下的一次检索结果 | 减少重复检索                     |
| Redis `lock:*`    | 某会话的一把生成租约锁     | 阻止同会话并发生成               |

关联关系：

- `conversations.id` → `turns.conversation_id`：一对多，有外键，删除会话级联删除问答。
- `rag_vector_sets.id` → `rag_vectors.set_id`：一对多，有外键，删除快照级联删除该快照的向量。
- `documents.id` → `rag_vectors.document_id`：逻辑关联，**没有外键**。向量表保存创建快照时的原文副本。
- `turns.sources` 保存引用快照，**没有指向 documents 的外键**。知识删除后，历史回答仍保留当时的引用。
- `conversations.revision` 与 `knowledge_state.revision` 是两套独立版本，分别用于上下文缓存和检索缓存。

下列表格中，“无默认值”表示插入时须由代码提供；主键均隐含非空。所有 `timestamptz` 字段表示带时区时间点，显示时区取决于数据库会话配置。

## conversations：咨询会话

一个会话可以有多轮问答。该表只保存会话信息，正文在 `turns` 中。

| 字段         | 类型          | 可空 / 默认值      | 用途                                        |
| ------------ | ------------- | ------------------ | ------------------------------------------- |
| `id`         | `uuid`        | 主键，无默认值     | 应用生成的会话 ID                           |
| `owner_id`   | `text`        | 非空，无默认值     | 会话归属；当前由服务端 `GAME_OWNER_ID` 提供 |
| `title`      | `text`        | 非空，`'新的咨询'` | 新请求开始时更新为问题的前 24 个字符        |
| `revision`   | `bigint`      | 非空，`0`          | 上下文版本；`finish()` 成功更新问答时递增   |
| `legacy_id`  | `text`        | 可空               | 从浏览器迁移的旧会话 ID；新会话一般为空     |
| `created_at` | `timestamptz` | 非空，`now()`      | 创建时间                                    |
| `updated_at` | `timestamptz` | 非空，`now()`      | 开始新问答或完成状态更新时刷新              |

约束和索引：

- 主键：`id`。
- 唯一约束：`(owner_id, legacy_id)`，用于旧会话导入去重；普通新会话的 `legacy_id` 为空，不会因此互相冲突。
- 索引：`conversations_owner_updated(owner_id, updated_at DESC)`，支持按归属查询最近会话。

主要读写方法：`new_conversation()`、`conversations()`、`require()`、`start()`、`finish()`、`import_conversation()`、`delete_conversation()`。

列表接口最多返回最近 100 个会话。删除前会检查是否仍有运行中的问答，有则返回 409；成功删除会级联删除 `turns`，并尝试清理该会话的上下文缓存。

## turns：每轮问答

**一条记录 = 一个用户问题 + 一个助手回答 + 这次生成的状态。** 同一会话问三个问题，通常就有三条记录。它不是逐 token 日志，也不是一条消息一行。

| 字段              | 类型          | 可空 / 默认值  | 用途                                                  |
| ----------------- | ------------- | -------------- | ----------------------------------------------------- |
| `id`              | `uuid`        | 主键，无默认值 | 本轮问答 ID                                           |
| `conversation_id` | `uuid`        | 非空，无默认值 | 所属会话，外键关联 `conversations.id`                 |
| `request_id`      | `uuid`        | 非空，无默认值 | 客户端请求标识，用于幂等和回放                        |
| `question`        | `text`        | 非空，无默认值 | 用户问题原文                                          |
| `answer`          | `text`        | 非空，`''`     | 最终回答，或失败/取消时已生成的部分正文               |
| `sources`         | `jsonb`       | 非空，`[]`     | 回答引用的知识片段快照                                |
| `status`          | `text`        | 非空，无默认值 | 限定为 `running/completed/failed/cancelled`           |
| `error`           | `text`        | 非空，`''`     | 失败或取消说明                                        |
| `deadline`        | `timestamptz` | 可空           | 新生成设置为数据库当前时间加 120 秒；旧数据导入不设置 |
| `created_at`      | `timestamptz` | 非空，`now()`  | 问答创建时间                                          |
| `finished_at`     | `timestamptz` | 可空           | 完成、失败、取消或超时处理的时间                      |

约束和索引：

- 主键：`id`。
- 唯一约束：`(conversation_id, request_id)`；请求去重限定在一个会话内。
- 外键：`conversation_id`，`ON DELETE CASCADE`。
- 索引：`turns_conversation_created(conversation_id, created_at, id)`，支持按会话读取历史。
- 数据库检查约束限定状态的四个取值；状态流转规则由应用控制。

### 状态与持久化时机

| 状态        | 含义                     | 写入位置                      |
| ----------- | ------------------------ | ----------------------------- |
| `running`   | 已受理，正在生成         | `start()`                     |
| `completed` | 回答已成功保存           | `finish()`；完整旧问答导入    |
| `failed`    | 生成报错，或运行记录超时 | `finish()` / `expire_turns()` |
| `cancelled` | 客户端停止或连接取消     | `finish()`；不完整旧问答导入  |

`finish()` 只更新仍为 `running` 的记录，并递增会话 `revision`。流式生成的 token 先累积在进程内存中，结束或清理时保存，不会逐 token 写数据库。因此进程直接崩溃时，内存中的部分正文可能尚未落库。

`expire_turns()` 在读取会话、开始请求、删除会话时，将超过 `deadline` 的 `running` 记录改为 `failed`；没有独立的后台定时扫描。该方法不递增会话版本，但运行中的问答本就不属于完整上下文。

### request_id 与 replay

`replay` 是 `start()` 的返回标志，**不是数据库字段，也不是固定为 False**：

| 数据库情况                                  | 结果                                        |
| ------------------------------------------- | ------------------------------------------- |
| 找不到该会话下的 `request_id`，且无运行任务 | 插入 `running` 记录，返回 `(row, False)`    |
| 找到相同请求、问题一致且已 `completed`      | 返回 `(existing, True)`，直接回放答案和引用 |
| 相同请求 ID，但问题不同                     | 返回 409                                    |
| 相同请求 ID，但状态不是 `completed`         | 返回 409；重新提问需要新的请求 ID           |
| 新请求 ID，但会话已有 `running` 记录        | 返回 409                                    |

### sources 的内容

`sources` 是 JSON 数组，通常包含片段 `id`、`document_id`、`title`、`content`、`offset`、`score`、`matched_terms`，具体检索策略还可能附带向量分数等字段。数据库没有进一步限制 JSON 的字段结构；旧数据导入的来源结构也可能不同。

会话详情将每条 `turns` 展开成两条消息，最多返回最近 100 轮。模型上下文只选最近 10 轮 `completed` 记录，随后再按字符预算裁剪。Tool Calling 的中间调用过程不持久化在本表。

## documents：知识原文

| 字段         | 类型          | 可空 / 默认值  | 用途                                                  |
| ------------ | ------------- | -------------- | ----------------------------------------------------- |
| `id`         | `text`        | 主键，无默认值 | 文档 ID；新增通常为 UUID 字符串，也兼容种子/旧文档 ID |
| `title`      | `text`        | 非空，无默认值 | 知识标题                                              |
| `content`    | `text`        | 非空，无默认值 | 完整知识正文                                          |
| `created_at` | `timestamptz` | 非空，`now()`  | 写入时间                                              |

除主键外无额外索引。`documents()` / `knowledge_snapshot()` 读取知识，`add_document()` / `delete_document()` 修改知识。增加、删除知识时，在同一事务内递增 `knowledge_state.revision`。

当前接口提供新增和删除，没有独立更新接口。表中没有 `owner_id`，知识库在当前部署中共享。删除原文不会删除历史问答的 `sources`，也不会自动删除旧向量快照。

## knowledge_state：知识版本

| 字段       | 类型      | 可空 / 默认值     | 用途                   |
| ---------- | --------- | ----------------- | ---------------------- |
| `id`       | `integer` | 主键，限定 `id=1` | 唯一的全局知识状态记录 |
| `revision` | `bigint`  | 非空，`0`         | 知识变更时递增的版本号 |

基础迁移插入 `id=1`。种子导入、旧 SQLite 知识迁移、新增/删除知识会递增版本。`knowledge_snapshot()` 用一条 SQL 同时读取版本和全部文档，保证二者来自同一个数据库快照。

检索缓存键包含此版本：版本变化后使用新键，旧缓存等待 TTL 到期，不需要全量删除 Redis 键。直接手工改 `documents` 而不更新此版本，会绕过应用的缓存失效机制。

## schema_versions：数据库结构版本

| 字段      | 类型      | 可空 / 默认值  | 用途               |
| --------- | --------- | -------------- | ------------------ |
| `version` | `integer` | 主键，无默认值 | 已应用的结构版本号 |

- `1`：基础会话、问答、知识及辅助表迁移。
- `2`：向量快照和分块表迁移。

迁移用 `ON CONFLICT DO NOTHING` 写入版本标记。本表没有迁移时间、脚本校验和或执行日志。当前代码通过幂等 DDL 执行迁移，版本表不是通用迁移调度器。

## data_imports：数据导入标记

| 字段          | 类型          | 可空 / 默认值  | 用途               |
| ------------- | ------------- | -------------- | ------------------ |
| `name`        | `text`        | 主键，无默认值 | 导入任务的固定名称 |
| `imported_at` | `timestamptz` | 非空，`now()`  | 标记创建时间       |

| 已使用的名称          | 写入位置                          | 作用                           |
| --------------------- | --------------------------------- | ------------------------------ |
| `seeds-v1`            | `GameStorage.initialize()`        | 防止每次启动都重新插入示例知识 |
| `sqlite-knowledge-v1` | `scripts/migrate-game-storage.py` | 防止重复迁移旧 SQLite 知识     |

标记记录的是导入流程已处理，不代表导入文档数大于零；当前流程即使源数据为空，也可能写入标记。旧浏览器会话的去重不使用本表，而使用 `conversations(owner_id, legacy_id)`。

## rag_vector_sets：向量快照元数据

运行 `npm run migrate:vector` 后创建。使用 PostgreSQL 向量检索时，`PgVectorStore.ensure()` 按需写入数据；仅执行迁移不一定会产生快照记录。

| 字段                | 类型          | 可空 / 默认值  | 用途                                                |
| ------------------- | ------------- | -------------- | --------------------------------------------------- |
| `id`                | `text`        | 主键，无默认值 | 检索版本、语料哈希、模型身份共同生成的 SHA-256 指纹 |
| `corpus_hash`       | `text`        | 非空，无默认值 | 按文档 ID 排序后的文档集合指纹                      |
| `model_identity`    | `text`        | 非空，无默认值 | 模型、运行库版本、编码方式及模型文件摘要等身份信息  |
| `retrieval_version` | `text`        | 非空，无默认值 | 检索实现版本，当前代码为 `game-retrieval-v3`        |
| `chunk_count`       | `integer`     | 非空，无默认值 | 本快照的知识分块数量                                |
| `created_at`        | `timestamptz` | 非空，`now()`  | 快照创建时间                                        |

语料、模型身份或检索版本变化会产生新快照 ID。相同 ID 直接复用。快照元数据和全部分块在同一事务内写入，并通过事务 advisory lock 协调并发创建，避免读到半成品。

当前没有自动清理旧快照的任务，也没有“当前快照”字段；查询根据当前输入计算快照 ID。

## rag_vectors：知识分块向量

| 字段           | 类型                 | 可空 / 默认值  | 用途                                       |
| -------------- | -------------------- | -------------- | ------------------------------------------ |
| `set_id`       | `text`               | 非空，无默认值 | 所属快照，外键关联 `rag_vector_sets.id`    |
| `chunk_id`     | `text`               | 非空，无默认值 | 分块 ID，形式为 `{document_id}:{分块序号}` |
| `document_id`  | `text`               | 非空，无默认值 | 来源文档 ID，仅逻辑关联                    |
| `title`        | `text`               | 非空，无默认值 | 快照中的文档标题                           |
| `content`      | `text`               | 非空，无默认值 | 本分块的正文                               |
| `chunk_offset` | `integer`            | 非空，无默认值 | 分块在原文中的字符起始位置，从 0 开始      |
| `embedding`    | `public.vector(384)` | 非空，无默认值 | 归一化后的 384 维向量                      |

约束和索引：

- 复合主键：`(set_id, chunk_id)`。
- `set_id` 外键使用 `ON DELETE CASCADE`。
- HNSW 索引：`rag_vectors_cosine_hnsw`，使用 `public.vector_cosine_ops`，参数 `m=16`、`ef_construction=64`。

当前分块长度最多 360 个字符、步长 280 个字符，相邻完整分块重叠 80 个字符。编码输入是标题、换行和分块正文。

`PgVectorStore.search()` 每次按 `set_id` 过滤。`exact` 模式禁用索引扫描作为精确基线；`hnsw` 模式使用近似检索相关设置，实际执行计划由数据库决定。相似度按 `1 - 余弦距离` 计算。迁移要求 `vector` 扩展位于 `public` schema，版本至少为 0.8.0。

## Redis 键字典

连接由 `GAME_REDIS_URL` 指定，默认使用 Redis 的逻辑数据库 `0`。统一前缀：

```text
{GAME_REDIS_PREFIX}:{GAME_DB_SCHEMA}:
默认：game-ops:game_ops:
```

三类键的 Redis 类型都是 **String**。上下文和检索结果是 JSON 字符串；生成锁是 UUID 字符串。以下 `{...}` 表示占位符，不是实际键中的花括号。

| 键模式（省略统一前缀）                     | 值                                     | 写入时 TTL       | 主要方法              |
| ------------------------------------------ | -------------------------------------- | ---------------- | --------------------- |
| `context:{conversation_id}:{revision}`     | 最近 10 轮完整问答的 JSON 数组         | 900 秒 / 15 分钟 | `context()`           |
| `search:{knowledge_revision}:{query_hash}` | 包含 `sources` 和 `trace` 的 JSON 对象 | 300 秒 / 5 分钟  | `retrieve()`          |
| `lock:{conversation_id}`                   | 本次持有者的随机 UUID token            | 120 秒           | `lock()` / `unlock()` |

### context：历史上下文缓存

`revision` 来自 `conversations.revision`。值的结构示例：

```json
[
  [
    { "role": "user", "content": "礼包领取失败如何排查？" },
    { "role": "assistant", "content": "先检查库存与领取条件。" }
  ]
]
```

读取前先在 PostgreSQL 校验会话存在性和归属。缓存未命中时，读取最近 10 轮已完成问答并按时间正序组装。此缓存只包含角色和正文，不包含引用或错误状态。

`finish()` 更新版本后，新请求读取新版本键；旧版本自然过期。删除会话时使用 `SCAN` 模式匹配该会话的上下文键并尝试删除。读缓存不续期。

### search：检索结果缓存

`knowledge_revision` 来自 `knowledge_state.revision`。`query_hash` 是以下内容序列化后的 SHA-256：

```text
[检索实现 VERSION, query, 完整 RetrievalOptions, Embedding 模型身份或 null]
```

因此即使问题一样，只要检索策略、数量、阈值、向量后端、搜索模式或模型身份不同，也会使用不同的键。

值包含检索片段 `sources` 和诊断信息 `trace`，例如策略、检索版本、知识版本及缓存命中情况。命中时返回结果的 `trace.cache_hit` 被设为 `true`；不会因此重新写入缓存或延长 TTL。

知识变化后旧键等待过期。该缓存不按用户或会话隔离，与当前共享知识库设计一致。

### lock：会话生成锁

获取时执行等价于 `SET key token NX EX 120` 的操作。键已存在返回 409；Redis 不可用返回 503，不开启无锁生成。

释放时用 Lua 原子比较 token，仅持有者匹配才删除，防止旧请求删掉新请求的锁。当前无续租逻辑；未正常释放时依靠 120 秒 TTL 到期。

Redis 锁之外，`start()` 还会锁定 PostgreSQL 的会话行并检查是否已有运行任务。Redis 租约和数据库 `turns.deadline` 是两种不同机制，即使当前都使用 120 秒，也不应视为同一状态。

缓存读写遇到 Redis 错误时可以回退到 PostgreSQL / 重新计算；锁获取失败会阻止新生成。不要在问答运行中随意清理锁键。

## 一轮问答的读写流程

1. 新建咨询：向 `conversations` 插入一行。
2. 提交问题：检查会话归属，取得 Redis 生成锁。
3. `start()`：锁定会话行、处理超时记录、检查 `request_id`；新请求写入 `turns`，已完成请求则回放。
4. 新生成读取 `context` 缓存；未命中时回查已完成的 `turns`。
5. 读取知识版本和文档，查 `search` 缓存；未命中则检索，pgvector 路径按需建立或复用向量快照。
6. 流式输出回答，结束时 `finish()` 保存正文、引用及状态，同时更新会话版本。
7. 数据库保存成功后发送 `done`，最后释放 Redis 锁；异常或取消时尝试保存对应状态。

保留规则：PostgreSQL 历史和向量快照目前没有自动到期机制；Redis 缓存和锁按 TTL 到期。删除原文、删除会话、删除向量快照是不同动作，不会互相全部联动。

## 常用只读查询

以下 SQL 在已连接目标数据库的查询工具或 `psql` 中执行，使用默认 `game_ops` schema。UUID 占位值请替换为实际 ID。

```sql
-- 当前 schema 的表
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'game_ops' AND table_type = 'BASE TABLE'
ORDER BY table_name;

-- 已记录的迁移版本
SELECT * FROM game_ops.schema_versions ORDER BY version;

-- 最近会话
SELECT id, owner_id, title, revision, created_at, updated_at
FROM game_ops.conversations
ORDER BY updated_at DESC LIMIT 20;

-- 某会话的问答与请求 ID
SELECT id, request_id, question, status, error, created_at, finished_at
FROM game_ops.turns
WHERE conversation_id = '替换为会话UUID'::uuid
ORDER BY created_at, id;

-- 尚未被应用处理的超时任务
SELECT id, conversation_id, deadline
FROM game_ops.turns
WHERE status = 'running' AND deadline < now();

-- 知识版本与文档数
SELECT revision, (SELECT count(*) FROM game_ops.documents) AS document_count
FROM game_ops.knowledge_state WHERE id = 1;

-- 导入标记
SELECT * FROM game_ops.data_imports ORDER BY imported_at DESC;

-- 向量快照及实际分块数量（执行向量迁移后可用）
SELECT s.id, s.chunk_count, count(v.chunk_id) AS actual_chunks, s.created_at
FROM game_ops.rag_vector_sets s
LEFT JOIN game_ops.rag_vectors v ON v.set_id = s.id
GROUP BY s.id
ORDER BY s.created_at DESC;
```

本地默认 Redis 连接的查询示例；其他环境调整主机、端口、逻辑数据库和前缀：

```bash
redis-cli -h 127.0.0.1 -p 6379 -n 0 --scan --pattern 'game-ops:game_ops:*'
redis-cli -h 127.0.0.1 -p 6379 -n 0 TYPE '替换为完整键名'
redis-cli -h 127.0.0.1 -p 6379 -n 0 TTL '替换为完整键名'
redis-cli -h 127.0.0.1 -p 6379 -n 0 GET '替换为完整键名'
```

`TTL` 返回剩余秒数；`-2` 表示键不存在，`-1` 表示未设置过期时间。应用正常写入的三类键都有过期时间。`GET` 可能包含完整问答或知识片段，排查时按业务数据管理。

## 代码索引与范围说明

| 内容                             | 实现位置                                                                   |
| -------------------------------- | -------------------------------------------------------------------------- |
| 6 张基础表、约束与索引           | [001_game.sql](../apps/api/studio/migrations/001_game.sql)                 |
| 2 张向量表、HNSW 索引            | [002_game_vectors.sql](../apps/api/studio/migrations/002_game_vectors.sql) |
| 会话、问答、知识、Redis 缓存和锁 | [game_storage.py](../apps/api/studio/game_storage.py)                      |
| 请求流程、SSE、回放与清理        | [game.py](../apps/api/studio/game.py)                                      |
| 快照创建与向量查询               | [game_pgvector.py](../apps/api/studio/game_pgvector.py)                    |
| 分块、检索参数及版本             | [game_retrieval.py](../apps/api/studio/game_retrieval.py)                  |
| 本地 Embedding 缓存              | [game_embeddings.py](../apps/api/studio/game_embeddings.py)                |
| 旧知识迁移                       | [migrate-game-storage.py](../scripts/migrate-game-storage.py)              |
| 向量迁移                         | [migrate-game-pgvector.py](../scripts/migrate-game-pgvector.py)            |

此外，Embedding 实现会在 `GAME_EMBEDDING_CACHE_DIR`（默认 `data/embeddings`）下创建 `vectors.sqlite3`，其中 `vectors(model, digest, vector)` 以 `(model, digest)` 为主键缓存编码结果。这是可重建的本地派生缓存，不属于 PostgreSQL 或 Redis，也不是知识原文的权威存储。

原教学工作台、Runtime Demo 的 SQLite 表不在本文范围内。部署与启动方式见 [运营助手文档](GAME-OPS.md)，检索评测见 [检索评测说明](RAG-EVALUATION.md)。
