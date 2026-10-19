# 游戏中心运营问答助手

新增 **可恢复的 Agent Runtime Demo**：运行 `npm run dev:api` 后打开 <http://127.0.0.1:3001/runtime-demo>。演示模型 → 工具循环、逐步执行、人工审批、暂停/取消、故障重试和持久化恢复；全部使用本地 Mock，无需 API Key。详见 [Runtime Demo 使用与架构](docs/RUNTIME-DEMO.md)。

运营助手使用 **PostgreSQL 保存会话、问答与知识，Redis 缓存上下文并控制并发**。本地启动前配置 `.env`，首次升级执行 `npm run migrate:game`；浏览器旧咨询在页面加载时自动迁移。

默认页面已升级为游戏中心运营助手，支持知识导入、BM25 检索、多轮上下文、引用溯源与已有模型 SSE 流式问答。模型通过 `GAME_LLM_BASE_URL`、`GAME_LLM_MODEL`、`GAME_LLM_API_KEY` 配置。完整启动说明见 [运营助手使用文档](docs/GAME-OPS.md)。原工程工作台仍可通过 `/?studio=1` 访问，以下内容介绍原教学工作台。

# Agent Engineering Studio

面向 **Agent 开发工程师** 的全栈实战工程。Python FastAPI 后端 + Vue 3 / TypeScript / ESLint 前端。默认确定性 Mock 模型，**无需 API Key，无外部模型请求**。通过可运行的工具、检索、持久化和追踪学习 JD 中的系统工程能力。

已有 Node 示例保留在 `apps/server` 作为历史参考；默认开发、构建和测试入口已切换到 Python。不要同时启动两个后端，它们都使用 3001 端口。

## 快速启动

要求 Python 3.9+（部署推荐 3.12）、Node.js 22.12+。

```bash
npm install --ignore-scripts
npm run setup:api
npm run dev
```

- 工作台：<http://localhost:5173>
- Python API / Swagger：<http://127.0.0.1:3001/docs>
- 健康检查：<http://127.0.0.1:3001/api/health>
- 默认数据库：`data/studio.sqlite3`，已加入 Git 忽略。

Windows 可直接使用 `.venv\Scripts\python -m uvicorn studio.main:create_app --factory --app-dir apps/api --port 3001` 启动 API，然后 `npm run dev -w @studio/web`。根目录脚本采用 macOS/Linux 路径。

## 建议体验顺序

1. **Agent 对话**：输入 `计算 (128 + 2) * 16`，看到真实工具输入、输出与流式结果。
2. **编排模式**：选择多角色协作，输入 `解释 RAG，并计算 128 * 16`，观察 Researcher、工具和 Reviewer 的交接事件。角色由确定性代码模拟，不是多个真实 LLM。
3. **上下文与记忆**：输入 `记住：我喜欢 Python`，再输入 `我的偏好是什么`。设置页显示会话 ID，可在实验室查看或删除该会话长期记忆。
4. **知识引擎**：在「工程实验室 → 知识引擎」导入带唯一关键词的文档，再搜索该词，查看分块编号与 BM25 分数。
5. **故障与恢复**：创建任务并开启「工具异常」，查看失败 trace；点击重试，新 run 关闭故障注入，保留原 run 的审计记录。
6. **评测与改进**：给任务负反馈，查看改进候选；运行固定测试集，比较 top_k=1 与 top_k=3 的真实结果和延迟。
7. **协议与扩展**：查看 Skills 指南，点击 MCP tools/call 按钮执行受限算术工具。

## 目录与 JD 覆盖

| 路径 | 实现 |
| --- | --- |
| `apps/api/studio/main.py` | FastAPI、输入校验、SSE、任务 worker、取消/重试、指标、MCP 教学端点 |
| `apps/api/studio/runtime.py` | Model 接口、Mock 决策、有限步骤执行、三种编排模式、上下文裁剪、多角色交接 |
| `apps/api/studio/knowledge.py` | 导入、重叠分块、中英文分词、BM25、LRU 缓存与失效 |
| `apps/api/studio/store.py` | SQLite WAL、事务领取、任务恢复、事件序号、长期记忆与反馈 |
| `apps/api/studio/sandbox.py` | 受限 AST 算术解释器、输入/节点/数值预算、能力白名单 |
| `apps/api/studio/evaluation.py` | 离线固定任务集、答案与工具断言、基线/候选对比 |
| `apps/web/src/App.vue` | Vue 3 聊天、流式消费、会话、引用与执行面板 |
| `apps/web/src/EngineeringLab.vue` | 任务队列、追踪、知识、记忆、评测、反馈与 MCP 交互 |
| `apps/api/tests` | API 集成、安全、恢复、隔离、预算与故障回归测试 |
| `scripts/load_test.py` | 并发压测、成功率、P50/P95、状态码统计 |
| `skills/incident-review/SKILL.md` | 故障排查工作流示例，可在 UI 阅读 |
| `compose.yaml` / `infra/k8s` | 容器、反向代理、持久化、探针与资源预算模板 |
| `docs/JD-MAP.md` | JD 逐项映射、学习练习、生产扩展边界 |
| `docs/ARCHITECTURE.md` | 架构决策、数据流、协议、并发与安全约束 |

## 校验

```bash
npm run check          # ESLint + TypeScript + pytest + 前端生产构建
npm run lint:fix       # 保留既有 ESLint 配置并自动修复
npm test              # Python 测试
npm run test:legacy   # 可选：旧 Node 示例测试
python3 scripts/load_test.py --requests 30 --concurrency 4
```

负载脚本需要先启动 API。对工具错误的故障注入包含在自动化测试中；手动终止并重启 API 可以观察未完成后台任务的恢复。GitHub Actions 已配置同一质量检查链。原有 ESLint 严格规则保留，既有复杂编排和数字常量仍会报告 warning。

## API 示例

```bash
curl -N http://127.0.0.1:3001/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"demo","mode":"multi","messages":[{"role":"user","content":"介绍 RAG 并计算 128 * 16"}]}'
```

SSE 事件：`status`、`tool_start`、`tool_end`、`sources`、`token`、`done`、`error`。持久化事件附带 `run_id`、`seq` 和时间戳。聊天断开会取消未结束的任务；`POST /api/runs` 提交的后台任务独立于页面生命周期。

其他接口可在 Swagger 中探索：`/api/runs`、`/api/knowledge`、`/api/search`、`/api/memory/{session}`、`/api/evaluations`、`/api/improvements`、`/api/skills`、`/api/metrics`、`/api/mcp`。

## 部署

```bash
docker compose up --build
# 浏览器打开 http://localhost:8080
```

Compose 只将前端绑定到宿主机 loopback，API 在内部网络提供服务。Kubernetes 示例只部署 API 与持久卷：先构建并载入 `agent-studio-api:local` 镜像，应用 `infra/k8s/api.yaml`，再通过 `kubectl port-forward service/api 3001:3001` 访问。容器和 K8s 模板需要在有 Docker/集群的环境进一步验证。

## 明确边界

- session_id 是逻辑分区而非身份凭证；API 可读取所有本地任务，部署到公网前必须加认证和租户授权。
- Python 路径仅 Mock。Model 接口展示模型边界，尚无真实模型适配器；不把固定规则描述成真实推理或模型质量评测。
- RAG 是词法 BM25，不含 Embedding/向量数据库。上下文预算按字符计量，历史裁剪不冒充模型摘要。检索输出单独限定 top_k 和分块长度。
- SQLite 持久队列是单机事务示例，**只允许一个 Uvicorn worker / 一个 API 副本**。恢复从任务起点重放，不是断点继续；只内置只读或幂等工具，新增外部写操作前必须设计幂等键与审批。
- 沙箱仅接受有限算术语法，不执行 Python 源码，不是 OS/容器级通用沙箱。
- MCP 实现无状态 HTTP JSON-RPC 教学子集，不宣称完整 MCP 传输兼容。Skills 目前展示操作指南，Mock 不自动执行其内容。
- 改进闭环为反馈 → 失败候选 → 固定回归评测 → 人工发布决策；不会自动训练、自动部署或修改策略。
- Docker、K8s、CI 配置提供可审查的工程入口；多机分布式队列、OpenTelemetry、真实模型评测和生产 SLO 留作进阶扩展，详见学习地图。
