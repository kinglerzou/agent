# 游戏中心运营问答助手

Vue 3 + FastAPI + PostgreSQL + Redis。默认页面为运营助手，原工程工作台在 `/?studio=1`，Runtime Demo 在 `/runtime-demo`。此次迁移针对 `/api/game` 运营助手，原教学工作台和 Runtime Demo 的 SQLite 数据库保持原有用途。

## 本地配置和启动

首次从 `.env.example` 创建根目录 `.env`，按实际环境填写数据库、Redis 和真实模型 API 配置（文件被 Git 忽略，勿提交密钥）：

```dotenv
GAME_DATABASE_URL=postgresql://localhost/game_ops
GAME_DB_SCHEMA=game_ops
GAME_REDIS_URL=redis://127.0.0.1:6379/0
GAME_REDIS_PREFIX=game-ops
GAME_OWNER_ID=local-operator
GAME_LLM_BASE_URL=https://api.deepseek.com
GAME_LLM_MODEL=填写账号可用的模型名称
GAME_LLM_API_KEY=在本地填写
```

若数据库需要密码，使用 `postgresql://用户名:URL编码后的密码@127.0.0.1:5432/game_ops`；Redis 如有认证，在 Redis URL 中配置。进程环境变量优先于 `.env`。模型名称沿用用户配置，存储测试不调用真实模型。

```bash
npm run setup:api     # 安装新增 PostgreSQL / Redis 驱动
npm run migrate:game  # 初始化表并复制旧知识，重复执行不会重复导入
npm run dev
```

PostgreSQL 数据库须预先创建并授予应用用户访问权限，不要假设新环境已存在 `game_ops`。启动时首次访问运营接口会事务化创建 `game_ops` schema 内的表，跨进程通过数据库 advisory lock 串行执行迁移。应用需要该 schema 的建表权限。生产建议由部署迁移账号完成 DDL，再给运行账号较小权限。

页面：<http://127.0.0.1:5173/>。Redis 必须运行。可使用已有 Redis 服务管理方式，或在本地开发时执行 `redis-server --bind 127.0.0.1 --port 6379 --save '' --appendonly no`。Redis 只存可重建数据。

## 数据放在哪里

完整字段说明、表关联、Redis 键结构与查询示例见 [运营助手存储字典](GAME-STORAGE.md)，包含基础业务表和 pgvector 向量表。

| 数据                                      | 存储                                                              | 行为                                                      |
| ----------------------------------------- | ----------------------------------------------------------------- | --------------------------------------------------------- |
| 会话 ID、标题、归属、版本、时间           | PostgreSQL `conversations`                                        | 服务端权威记录；浏览器不再保存新咨询                      |
| 问题、回答、来源快照、请求 ID、状态、错误 | PostgreSQL `turns`                                                | 一轮问答作为一条记录，失败/取消状态保留；删除会话级联删除 |
| 运营知识原文                              | PostgreSQL `documents`                                            | 保留文档 ID；导入/删除在事务内更新知识版本                |
| 知识版本、迁移记录                        | PostgreSQL `knowledge_state` / `schema_versions` / `data_imports` | 控制缓存失效和重复迁移                                    |
| 最近 10 轮完整上下文                      | Redis `game-ops:game_ops:context:{conversation_id}:{revision}`    | TTL 15 分钟；未命中回查 PostgreSQL                        |
| 检索结果                                  | Redis `…:search:{knowledge_revision}:{query_hash}`                | TTL 5 分钟；文档变更后旧版本不再命中                      |
| 会话生成锁                                | Redis `…:lock:{conversation_id}`                                  | NX + 120 秒租约；Lua 校验持有者后释放                     |

数据库连接池每进程最多 8 条连接，数据库操作在线程池执行，避免阻塞 SSE 事件循环。缓存键带应用前缀和 schema，不清空 Redis、不操作其他项目的键。Redis 缓存失败时可回查 PostgreSQL；生成锁不可用时拒绝开启新生成，避免重复请求。

## 请求与上下文

前端只提交当前问题，历史来自服务端。最近 10 轮已完成问答按完整轮次装入 12000 字符历史预算，失败/中断回答不进入模型上下文。短追问结合最近一次已完成用户问题检索；知识检索仍使用中文双字分词 + BM25，返回最多 4 个片段。

```json
{
  "conversation_id": "服务端创建的 UUID",
  "request_id": "本次请求的 UUID",
  "message": "礼包领取失败怎么排查？"
}
```

系统指令、检索证据和近期对话发送到真实 OpenAI 兼容模型 `/chat/completions`。SSE 事件仍为 `status`、`sources`、`token`、`done`、`error`。回答提交 PostgreSQL 成功后才发送 `done`。

- 同一请求 ID 重试：已完成则重放已保存回答，不再次调用模型；问题内容不一致返回 409。
- 同一会话并发：Redis 租约和 PostgreSQL 会话行锁共同控制；数据库再次检查运行任务。
- 页面断线/停止：取消上游，保存已生成文本并标记 cancelled，释放租约。
- 崩溃：running 记录超过 120 秒，在读取会话或开始下一请求时标记失败，不自动重新调用模型。
- 回答正文上限 24000 字；模型生成期限 90 秒，连接 10 秒、读取 45 秒超时。
- 删除会话：生成中返回 409；否则事务级联删除消息并清理对应上下文缓存。即使 Redis 暂时不可用，后续读取也须先通过数据库存在性/归属检查，遗留缓存会到期。

## 旧数据迁移

1. `npm run migrate:game` 只读读取 `data/game.sqlite3` 的知识文档，复制到 PostgreSQL；原文件保留。可用 `GAME_LEGACY_DB` 指定其他源文件。迁移标记避免重复导入，文档冲突时保留目标数据库内容。
2. 页面首次加载时，逐会话上传原 `localStorage.game-ops-chats`。全部成功后删除旧活动键，并保留本地备份 `game-ops-chats-backup-v1`。备份不会自动再次导入。
3. 部分失败时保留原键；刷新重试由 `(owner_id, legacy_id)` 唯一约束去重。旧记录过大或格式不合法时会提示迁移未完成，不静默丢弃。
4. 新咨询不再写 localStorage。会话删除针对服务端数据；迁移备份与原 SQLite 文件是独立备份，需要彻底清除历史时也需处理备份。

会话列表返回最近 100 个会话；详情返回最近 100 轮，完整历史仍在数据库。当前未提供较旧记录的分页 UI。

## 接口

- `GET /api/game/status`：模型配置、文档数量和 Redis 连接状态，不返回密钥。
- `GET/POST /api/game/conversations`：列表和新建。
- `GET/DELETE /api/game/conversations/{id}`：读取、删除。
- `POST /api/game/conversations/import`：幂等迁移旧咨询。
- `GET/POST /api/game/knowledge`、`DELETE /api/game/knowledge/{id}`：知识管理。
- `POST /api/game/chat`：服务端上下文流式问答。

## 验证与部署边界

`npm run check` 执行 ESLint、类型检查、后端测试和构建。存储集成测试使用随机 `test_game_*` schema 和独立 Redis 前缀，仅清理自身测试数据。指定 `TEST_GAME_DATABASE_URL` / `TEST_GAME_REDIS_URL` 可更换测试服务；设置 `REQUIRE_GAME_STORAGE_TESTS=1` 时服务不可达会失败，避免 CI 静默跳过。GitHub Actions 配置了 PostgreSQL 与 Redis 服务容器。模型流式测试使用 HTTP transport / 测试生成器，不产生模型费用。

Compose 包含独立 PostgreSQL 数据卷及 Redis，不复用本机数据库。默认口令 `local-development-only` 只用于本地开发且数据库端口不发布；生产应配置受保护的数据库和凭据。`GAME_CONTAINER_DATABASE_URL` 可覆盖容器使用的数据库地址。Docker 和 Kubernetes 未在此次本机验证；原 K8s 模板需补充数据库/Redis Secret 才能承载运营接口。

当前仍是本地单运营身份，服务端从 `GAME_OWNER_ID` 取归属，不接受客户端任意指定 owner。**尚无 SSO，也不提供真实多用户鉴权**；同一部署的浏览器共用该身份。对外或多用户上线必须用已验证身份替换 owner dependency，并增加知识访问权限。原教学任务 worker 仍依赖 SQLite 单进程恢复，因此整体应用不要直接扩成多 worker。

目前没有自动摘要、长期用户记忆或 Token 精算；上下文仍是字符预算。内置知识均明确标注示例，不代表内部业务规则。

驱动连接池和缓存实现参考 [Psycopg 连接池文档](https://www.psycopg.org/psycopg3/docs/advanced/pool.html) 与 [Redis Python 客户端文档](https://redis.io/docs/latest/develop/clients/redis-py/)。

## Tool Calling 演示

在聊天输入框上方勾选 **Tool Calling · 由模型调用知识检索**，例如提问“礼包领取失败需要检查什么？”。不开启时仍使用原有直接检索流程。

开启后，请求携带 `tool_calling: true`：

1. 后端把 `search_knowledge(query)` 的 JSON Schema 和近期对话发给现有模型（`tools`、`tool_choice: auto`）。指令要求模型调用一次工具，由模型补全追问并生成检索词。
2. 后端只接受一个白名单调用，校验 JSON、参数类型、长度和额外字段，再执行已有 BM25 检索。未知工具和无效参数直接报错，不执行任意代码。
3. SSE 返回 `tool_call`（名称、query）、`tool_result`（命中数量）和 `sources`；页面在本次回答下展示调用过程。
4. 有结果时，把模型原始 `assistant.tool_calls` 与匹配 `tool_call_id` 的 `role: tool` 结果回传模型，流式生成带引用的回答。无结果时返回“暂无足够依据”，不额外调用模型生成业务结论。

这是一次工具调用、一次答案生成的有界演示；规划最长 30 秒，计入原有 90 秒模型流程预算。模型需支持 Chat Completions 工具调用；不支持或未返回调用时会明确报错，可关闭开关使用基础 RAG。接口协议参考 [DeepSeek Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)。

答案和来源仍持久化；工具过程仅在当前请求页面展示，刷新或请求重放不恢复过程。测试 `apps/api/tests/test_game_tools.py` 使用模拟模型和内存仓库，无需数据库或真实 API 密钥。

## LangChain 应用

游戏中心的两条问答路径现在都使用 `studio/game_langchain.py` 中的组件：

- **自定义 Retriever**：`GameKnowledgeRetriever` 把已有 `repo.search()` 的 BM25 结果转成 LangChain `Document`，保留片段 ID、标题、分数；继续使用 PostgreSQL 和带版本号的 Redis 缓存。
- **LCEL 检索链**：`retriever | RunnableLambda(source_records)`，通过 `ainvoke` 执行，数据库检索在线程中运行。输出仍兼容前端引用和会话持久化格式。
- **StructuredTool**：`search_knowledge` 由同一个 Pydantic 参数模型生成工具定义并校验执行参数，开启 Tool Calling 时真正通过 `StructuredTool.ainvoke` 执行检索。模型选择工具的协议及次数限制保持不变。
- **PromptTemplate**：统一答案系统提示词和编号证据，文档内容作为模板变量传入，不会把文档中的花括号当成模板代码。

依赖固定为 `langchain-core==0.3.86`，兼容当前本机 Python 3.9。其他开发环境运行 `npm run setup:api` 安装依赖，然后重启 `npm run dev`。普通问答自动走检索链；勾选 Tool Calling 可体验结构化工具，接口 `/api/game/status` 的 `orchestration` 返回 `LangChain`。

模型 HTTP/SSE 网关、服务端历史、生成锁和持久化仍由项目现有实现负责。这次没有引入 LangGraph 自主循环、向量检索或额外的模型服务，也没有配置 LangSmith 云端追踪。

参考：[BaseRetriever](https://reference.langchain.com/python/langchain-core/retrievers/BaseRetriever)、[StructuredTool](https://reference.langchain.com/python/langchain-core/tools/structured/StructuredTool)。

## 常见问题

| 现象                       | 检查方式                                                                                            |
| -------------------------- | --------------------------------------------------------------------------------------------------- |
| 页面显示模型未配置         | 检查根目录 `.env` 的模型地址与名称，修改后重启 `npm run dev`；直接启动 Uvicorn 时需自行注入环境变量 |
| 模型返回 401 / 403 / 429   | 检查服务商密钥、模型权限、额度或限流；状态接口不验证这些条件                                        |
| 模型返回 404               | 网关追加 `/chat/completions`，确认 base URL 是否需要 `/v1`，避免重复填写路径                        |
| 数据库连接或初始化失败     | 确认 PostgreSQL 已启动、数据库存在、连接串和 schema 权限正确，再运行迁移                            |
| Redis 不可用，无法开始生成 | 检查 `GAME_REDIS_URL`、认证和服务状态；生成锁失败不会降级为无锁调用                                 |
| Tool Calling 报错          | 确认模型支持工具协议且返回一个合法调用；可关闭开关体验普通检索问答                                  |
| 回答提示依据不足           | 导入相关资料，使用资料中的关键词重试；BM25 是词法匹配，不是语义向量召回                             |
| HTTP 409                   | 检查是否同会话正在生成、复用了请求 ID 却修改问题，或删除了生成中的会话                              |

`GET /api/game/status` 的 `configured` 仅检查模型地址和名称是否非空。完整验收需提问一条有知识依据的问题，看到流式答案与 `done`，刷新后确认答案和引用已保存。真实调用可能产生服务商费用；不要把本地配置成功等同于供应商可用性验证。
