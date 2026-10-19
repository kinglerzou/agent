# 游戏中心运营问答助手 · Agent Engineering Studio

基于 **Vue 3 + TypeScript + FastAPI + LangChain + PostgreSQL + Redis** 的全栈 Agent 实战项目。主应用面向游戏运营知识问答，已接入真实的 **OpenAI 兼容 Chat Completions 模型 API**，支持知识导入、多轮对话、引用溯源、SSE 流式回答，以及由模型发起的知识检索工具调用。

项目同时保留工程教学工作台与可恢复 Runtime，用于学习任务编排、上下文管理、工具安全、人工审批、故障恢复与评测。三个入口共享 FastAPI 服务，但模型实现和存储边界不同。

## 三个入口

| 入口                       | 用途                                             | 模型与存储                                                        |
| -------------------------- | ------------------------------------------------ | ----------------------------------------------------------------- |
| `/`                        | 游戏中心运营问答助手，项目主入口                 | 真实模型 API；PostgreSQL 保存会话、回答、知识；Redis 缓存与生成锁 |
| `/?studio=1`               | 工程工作台：编排、任务、记忆、追踪、评测         | 确定性 Mock；`data/studio.sqlite3`                                |
| API 服务的 `/runtime-demo` | 退货场景：逐步执行、审批、暂停、取消、检查点恢复 | `MockModel`；`data/runtime-demo.sqlite3`                          |

真实模型接入位于 `apps/api/studio/game.py` 与 `game_tools.py`。Runtime 的消息结构包含 `assistant.tool_calls` 和 `role: tool`，但目前没有远程模型适配器。工程工作台的多角色协作由代码模拟。

## 核心能力

- **可衡量检索**：主应用「检索实验室」提供 BM25 / 同义词扩展 / pgvector 向量 / RRF 混合检索对比、逐题证据、Recall/MRR/nDCG 与无答案误召回率，支持当前知识库人工标注评测及 JSON 导出。
- **知识问答与来源引用**：导入运营资料，按窗口分块，以中英文分词和 BM25 检索，返回可查看的来源片段；内置资料为演示内容。
- **真实模型流式生成**：后端请求兼容接口，向浏览器转发 SSE；支持停止生成、错误提示和失败状态保存，没有伪造答案的 Mock 降级。
- **Tool Calling**：开启后由真实模型生成 `search_knowledge` 参数，经白名单和 Pydantic 校验后执行检索，再将工具结果回传模型生成答案。
- **LangChain 编排**：自定义 Retriever、LCEL 检索链、StructuredTool 和 PromptTemplate 复用现有存储与模型网关。
- **服务端多轮上下文**：从 PostgreSQL 读取完整历史轮次，在字符预算内组装；Redis 缓存近期上下文与检索结果。
- **可靠性与持久化**：请求 ID 去重、会话生成锁、取消/失败归档、知识版本失效和旧数据迁移。
- **工程学习环境**：独立演示任务队列、工具追踪、长期记忆、固定回归评测、MCP 教学子集，以及带人工审批的可恢复执行循环。

普通问答：问题 → 服务端历史 → LangChain / BM25 检索 → 真实模型 → SSE → 保存回答与引用。

工具问答：问题与历史 → 真实模型选择检索工具 → 校验并执行 → 工具结果回传 → 真实模型流式回答。当前限制一次工具调用，不是无限自主循环。

## 快速启动

要求 Node.js 22.12+、Python 3.9+（部署推荐 3.12）；运营助手还需要可连接的 PostgreSQL 与 Redis。Compose 模板使用 PostgreSQL 16、Redis 7。

```bash
npm install --ignore-scripts
npm run setup:api
# 仅首次创建配置；已有 .env 时不要覆盖
cp -n .env.example .env
```

编辑根目录 `.env`，填写数据库、Redis 和模型配置：

```dotenv
GAME_DATABASE_URL=postgresql://localhost/game_ops
GAME_DB_SCHEMA=game_ops
GAME_REDIS_URL=redis://127.0.0.1:6379/0
GAME_REDIS_PREFIX=game-ops
GAME_OWNER_ID=local-operator
GAME_LLM_BASE_URL=https://api.deepseek.com
GAME_LLM_MODEL=填写服务商支持且账号可用的模型名称
GAME_LLM_API_KEY=填写模型服务密钥
```

网关会在 `GAME_LLM_BASE_URL` 后追加 `/chat/completions`，不要填完整请求路径；如服务商要求 `/v1` 前缀，应将它包含在 base URL 中。Tool Calling 需要所选模型支持工具调用。兼容 API 格式不代表必须使用 OpenAI 服务，仓库示例使用 DeepSeek 地址。

密钥仅由后端读取，不要使用 `VITE_` 前缀或提交 `.env`。进程环境变量优先于 `.env`；修改配置后重启 API。

```bash
# PostgreSQL 服务启动后，首次创建数据库；已有数据库则跳过
createdb game_ops
# 确保 Redis 已启动，然后初始化表并迁移旧知识
npm run migrate:game
npm run dev
```

数据库用户需有目标 schema 的建表权限。`createdb` 默认使用本地 PostgreSQL 身份；远程数据库或自定义账号请由对应管理员预先创建，并调整连接串。没有旧 SQLite 数据时也可执行迁移。

| 地址                                    | 内容                             |
| --------------------------------------- | -------------------------------- |
| <http://127.0.0.1:5173/>                | 运营助手                         |
| <http://127.0.0.1:5173/?studio=1>       | 工程工作台                       |
| <http://127.0.0.1:3001/runtime-demo>    | Runtime 演示，无需前端开发服务   |
| <http://127.0.0.1:3001/docs>            | Swagger API 文档                 |
| <http://127.0.0.1:3001/api/health>      | API 健康检查                     |
| <http://127.0.0.1:3001/api/game/status> | 模型配置状态、文档数、Redis 状态 |

`/api/health` 不代表模型、数据库和 Redis 均可用；`/api/game/status` 的 `configured` 只检查模型地址和名称，不能证明密钥有效或调用成功。

Windows 可用 `python -m venv .venv` 与 `.venv\Scripts\python -m pip install -r apps/api/requirements.txt` 安装 Python 依赖，再使用 `npm run dev`；`setup:api` 和 `npm test` 采用 macOS/Linux 路径。

## 推荐体验路径

1. 打开运营助手，确认模型配置和 Redis 状态，查看内置示例知识。
2. 导入带唯一关键词的测试资料，针对其中内容提问，检查流式回答与引用片段。
3. 继续追问，刷新页面，确认会话和回答由服务端恢复。
4. 勾选 **Tool Calling · 由模型调用知识检索**，观察工具参数、检索结果和答案；工具过程当前不会随历史一起恢复。
5. 停止一条生成中的回答，检查取消状态；缺少检索证据时应提示依据不足。
6. 打开 Runtime，体验退货订单 A123 的人工审批、故障注入、重试和检查点恢复，详见 [Runtime 文档](docs/RUNTIME-DEMO.md)。

以上运营问答在有依据并进入生成阶段时会请求真实模型，可能产生服务商费用；自动化模型测试使用替身。

## 工程工作台体验路径

1. **Agent 对话**：输入 `计算 (128 + 2) * 16`，看到真实工具输入、输出与流式结果。
2. **编排模式**：选择多角色协作，输入 `解释 RAG，并计算 128 * 16`，观察 Researcher、工具和 Reviewer 的交接事件。角色由确定性代码模拟，不是多个真实 LLM。
3. **上下文与记忆**：输入 `记住：我喜欢 Python`，再输入 `我的偏好是什么`。设置页显示会话 ID，可在实验室查看或删除该会话长期记忆。
4. **知识引擎**：在「工程实验室 → 知识引擎」导入带唯一关键词的文档，再搜索该词，查看分块编号与 BM25 分数。
5. **故障与恢复**：创建任务并开启「工具异常」，查看失败 trace；点击重试，新 run 关闭故障注入，保留原 run 的审计记录。
6. **评测与改进**：给任务负反馈，查看改进候选；运行固定测试集，比较 top_k=1 与 top_k=3 的真实结果和延迟。
7. **协议与扩展**：查看 Skills 指南，点击 MCP tools/call 按钮执行受限算术工具。

## 代码与文档导航

| 路径                                                            | 说明                                                   |
| --------------------------------------------------------------- | ------------------------------------------------------ |
| `apps/api/studio/game.py`                                       | 运营 API、真实模型 HTTP/SSE 网关、上下文和问答生命周期 |
| `apps/api/studio/game_tools.py`                                 | 模型工具规划、参数校验和结果回传                       |
| `apps/api/studio/game_langchain.py`                             | Retriever、LCEL、StructuredTool、提示词模板            |
| `apps/api/studio/game_storage.py`                               | PostgreSQL、Redis、迁移、会话与知识持久化              |
| `apps/api/studio/runtime_demo/`                                 | 可恢复 Runtime、状态机、审批与独立演示页面             |
| `apps/api/studio/main.py`                                       | FastAPI 入口、教学任务 worker、指标和 MCP 子集         |
| `apps/api/studio/runtime.py` / `store.py`                       | 教学 Mock 编排、SQLite 队列、记忆与事件                |
| `apps/api/studio/knowledge.py` / `sandbox.py` / `evaluation.py` | BM25、受限算术 DSL、固定评测                           |
| `apps/web/src/`                                                 | Vue 运营页面、工程工作台和流式交互                     |
| `apps/api/tests/` / `scripts/load_test.py`                      | 后端回归与教学接口负载脚本                             |
| `apps/server/` / `packages/shared/`                             | 保留的 Node 历史示例与共享类型                         |
| `compose.yaml` / `infra/k8s/`                                   | 容器与部署模板                                         |

- [检索评测说明](docs/RAG-EVALUATION.md)：指标口径、固定开发集、业务标注、报告导出与复现。
- [运营助手使用与运维](docs/GAME-OPS.md)：配置、存储、迁移、接口、Tool Calling、LangChain。
- [架构与设计决策](docs/ARCHITECTURE.md)：三条链路、持久化和安全边界。
- [Runtime 使用与架构](docs/RUNTIME-DEMO.md)：状态、审批、幂等与恢复。
- [能力与学习地图](docs/JD-MAP.md)：代码落点、练习和进阶方向。
- [验证说明](docs/VERIFICATION.md)：检查命令、外部依赖与历史记录。

## 开发与验证

```bash
npm run check          # ESLint、TypeScript、pytest、前端生产构建
npm test               # 后端回归
npm run build          # 前端生产构建
npm run test:legacy    # 可选：历史 Node 示例测试
python3 scripts/load_test.py --requests 30 --concurrency 4
```

负载脚本需先启动 API，针对教学 Mock 接口，结果不能代表真实模型吞吐。存储集成测试需要 PostgreSQL 和 Redis；可配置 `TEST_GAME_DATABASE_URL`、`TEST_GAME_REDIS_URL`，用 `REQUIRE_GAME_STORAGE_TESTS=1` 禁止服务不可用时跳过。模型测试不验证真实供应商连通性，手工验收需另行检查完整回答与引用。

默认后端为 Python。历史 Node 服务同样使用 3001 端口，请勿同时启动。

## 部署

配置根目录 `.env` 后运行：

```bash
docker compose up --build
# 打开 http://localhost:8080
```

Compose 包含 API、前端、PostgreSQL 和 Redis；数据库采用独立数据卷，不复用本机 `game_ops`。前端端口仅绑定 loopback。默认数据库口令仅供本地开发，正式部署应替换凭据。`GAME_CONTAINER_DATABASE_URL` 可覆盖容器数据库地址。

Kubernetes 模板仅为 API 与持久卷示例，承载运营助手前需补齐 PostgreSQL、Redis 与模型配置/Secret。Docker、集群部署和远程 CI 的历史验证范围见验证文档。

## 当前边界

- 当前是本地单运营身份：`GAME_OWNER_ID` 不是用户认证，同一部署浏览器共享身份；对外部署需补充鉴权、租户授权和数据访问控制。
- 真实模型用于运营助手；工程工作台与 Runtime 仍为 Mock。检索实验室评估真实词法检索，但不评估生成答案质量；内置开发集不能代表业务泛化效果。
- 检索支持 BM25、本地多语言 Embedding 与 RRF 混合检索；向量支持 PostgreSQL pgvector 精确/HNSW 查询，本地扫描保留为对照；尚未接入模型重排。上下文仍按字符预算裁剪。
- 运营问答只调用知识检索工具，不自动修改真实游戏配置；Runtime 写入仅限本地演示订单。
- 整体应用仍需单 Uvicorn worker、单 API 副本。教学任务重启从任务起点重放，Runtime 从已提交检查点继续，运营问答的过期运行记录标记失败，不自动重发模型请求。
- 算术沙箱是受限 AST DSL；MCP 为 HTTP JSON-RPC 教学子集；Skills 为可阅读指南；均不等同于通用隔离容器、完整协议兼容或自动执行平台。
- 反馈闭环为收集失败候选、固定回归与人工决策，不自动训练或发布策略。
