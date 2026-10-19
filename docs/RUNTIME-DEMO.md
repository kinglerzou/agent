# 可恢复的 Agent Loop 演示

## 启动

在仓库根目录运行 `npm run dev:api`，打开 <http://127.0.0.1:3001/runtime-demo>。
页面直接由 FastAPI 提供，无需启动前端构建。缺少 Python 环境时先运行 `npm run setup:api`。
本模块始终使用确定性 Mock，不读取模型密钥，不发起模型或其他外部网络请求。

## 演示路径

1. 选择 A123，填写退货原因，创建任务。连续点击“下一步”，观察模型请求工具、工具结果、模型再次决策。
2. 第三轮模型请求 `submit_return` 时自动暂停；审查具体参数后批准，再执行下一步。审批本身不会执行写操作。
3. 留空原因可体验补充信息；A124 展示业务拒绝；B999 展示服务端数据权限拒绝。
4. 勾选故障注入，首个工具执行前会失败。点击重试，再执行下一步，模型轮数不增加，继续原工具。
5. 执行中停止并重新启动 API，在最近任务中选择原任务，继续检查点。自动模式任务重启后由 Worker 继续。
6. 手动暂停或取消后不会调度后续步骤。取消不会撤销已提交的本地退货申请。

所有任务共享本地演示订单；A123 多次申请会返回已有申请编号。需要清空演示数据时，在关闭 API 后自行删除 `data/runtime-demo.sqlite3` 及其 WAL/SHM 文件。

## 结构

- `apps/api/studio/runtime_demo/model.py`：Model 协议、工具 Schema、MockModel。模型根据历史工具结果决定下一步。
- `apps/api/studio/runtime_demo/__init__.py`：执行循环、状态机、SQLite 检查点、工具校验、审批绑定、幂等写入。
- `apps/api/studio/runtime_demo/api.py`：创建、查询、动作 API；动作需携带状态版本和事件 ID。
- `apps/api/studio/runtime_demo/index.html`：操作页面、消息历史、执行时间线。
- `apps/api/studio/main.py`：独立 Worker，每次推进一个步骤，步骤间允许暂停或取消。
- `apps/api/tests/test_runtime_demo.py`：回归测试。

## 状态与消息

`phase` 为 `model` 或 `tool`，记录下一步做什么。`status` 为 `ready`、`waiting_input`、`waiting_approval`、`paused`、`failed`、`completed` 或 `cancelled`。

每次模型输出保留 assistant 消息，包括 tool_calls。工具结果保留 role=tool 和对应 tool_call_id。每轮把这些消息传给模型，形成真正的模型调用边界；只是当前模型决策由确定性规则模拟。

每次状态变化增加 version，旧版本操作返回 HTTP 409。已处理的 event_id 重放直接返回当前状态，不重复批准或执行。审批保存工具 ID、名称和完整参数的副本，执行前再次比较。

本地工具写入、工具结果、检查点在同一 SQLite 事务中提交；进程崩溃时要么全部提交，要么全部回滚。订单唯一约束防止重复申请。恢复不会从头重放已提交步骤。

## 后续接真实模型

实现 `Model.generate(messages, tools) -> dict`，通过 `DemoRuntime(path, model=YourAdapter())` 注入。
返回统一的 assistant 消息：`content`、`tool_calls`，每个调用包含唯一 `id`、白名单 `name`、已解析的 `arguments`。
需要澄清时返回 `needs_input=True`；实际提供商协议应由适配层转换。

目前不提供真实 SDK/密钥配置，也不会伪装成已完成真实模型接入。接真实模型前需要：

1. 将远程调用移出 SQLite 写事务，使用异步 I/O；领取步骤后提交租约，完成后按版本提交结果，处理取消与过期响应。
2. 处理提供商的拒绝、截断、超时及多工具调用。本演示每轮明确只支持一个工具请求，多请求会失败。
3. 将示例的固定澄清字段替换为结构化待补充字段；增加真实 token 预算与上下文组装。
4. 为远程写工具提供业务幂等键及结果查询。本地事务不能保证外部 API 的 exactly-once。

## 边界

这是单机、单用户、本地教学服务，使用一个 Uvicorn worker；没有生产认证、分布式租约或容器沙箱。权限演示为服务端固定订单白名单。
政策检索只有一条本地词法匹配资料，不是向量 RAG。Trace 保存可见消息与工具结果，没有内部思维链或真实 token/费用指标。
后台调度上限每批 32 个任务，列表展示最近 100 个任务。模型最多 8 轮。状态和事件以 JSON 保存，适合小规模教学数据。

## 验证

`npm test` 运行全部后端回归测试；专项运行 `.venv/bin/python -m pytest apps/api/tests/test_runtime_demo.py -q`。
