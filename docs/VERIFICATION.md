# 验证范围与复现方式

运营助手已实现真实模型 API 接入；自动化测试使用模型替身，不能据此判断真实服务商连通性、答案质量或费用。下方历史记录保留原始范围，不作为当前测试数量或全部功能验收结论。

## 自动化检查

```bash
npm run check
# 仅检查模型工具与 LangChain 集成
.venv/bin/python -m pytest apps/api/tests/test_game_tools.py apps/api/tests/test_game_langchain.py -q
# 仅检查 Runtime 状态机与恢复
.venv/bin/python -m pytest apps/api/tests/test_runtime_demo.py -q
```

完整存储测试依赖 PostgreSQL 与 Redis，可通过 `TEST_GAME_DATABASE_URL` 和 `TEST_GAME_REDIS_URL` 指定测试服务。设置 `REQUIRE_GAME_STORAGE_TESTS=1` 时依赖不可用会失败；否则可能跳过，报告结果时应同时记录 passed、failed、skipped。测试使用独立 schema 和 Redis 前缀。

## 手工验收

1. 配置真实模型与存储，启动服务，检查 `/api/game/status`；该接口不会实际请求模型。
2. 使用已导入资料提问，检查 SSE 文本、引用与最终完成状态，刷新确认持久化。
3. 开启 Tool Calling，检查检索参数、工具结果和引用；再检查无依据问题的行为。
4. 检查多轮追问、停止生成、重复请求 ID、会话删除及依赖不可用时的提示。
5. 在 Runtime 验证审批、重试与重启恢复；在工程工作台验证工具、队列与评测。

真实调用验收应记录模型名称、日期、场景和结果，避免记录密钥。Mock 压测与固定评测不能替代供应商性能、真实模型质量或生产容量评估。

---

# 历史基线记录（工程工作台阶段）

- `npm run check`：通过（ESLint、TypeScript、pytest、Vue 生产构建）。
- pytest：26 项通过；包含恶意 AST 输入、上下文预算、检索缓存失效、SSE、故障重试、会话记忆、MCP、评测、重启恢复、队列容量和取消终态保护。
- ESLint：0 errors，35 warnings；主要来自保留的旧 Node 示例和聊天编排复杂度/数字常量。
- 浏览器：已验证工程实验室提交多角色任务，任务 completed，显示检索引用、calculator 输出 2048 与有序 trace；检查页面布局。
- 小规模本机探测：12 请求、4 并发、12 成功；P50 230.86 ms，P95 317.52 ms。仅为本地 Mock 小样本，不是生产容量或 SLO 承诺。
- Docker 镜像构建、Kubernetes 部署和远程 GitHub Actions 尚未实际运行；配置已提供。
- 该阶段验证未调用真实模型或使用 API Key；此项不代表当前运营助手没有真实模型接入。
