# LangGraph 人工审核

主入口问答默认勾选「人工审核」。普通检索和 Tool Calling 都支持审核；取消勾选可沿用直接完成的问答模式。审核针对回答内容，不会修改线上游戏配置。

## 使用流程

1. 提问后生成回答草稿，查看引用的知识片段。
2. 草稿保存后显示审核面板；此时不能在同一个咨询内继续提问，可以切换其他咨询。
3. 选择「通过审核」，或勾选「修改草稿后通过」编辑正文；选择「驳回」必须填写原因。
4. 审核通过后，最终正文进入后续对话上下文。待审核和驳回的回答均不进入上下文。
5. 刷新页面或重启 API 后，打开原咨询即可继续审核。界面保留审核人、时间、意见及修改前草稿。

现有检索与模型流式生成保持原实现，生成后的审核子流程使用真正的 LangGraph StateGraph：

```text
检索 → 模型生成草稿 → draft_ready → human_review（interrupt 暂停）
                                      ↓ Command(resume=审核决定)
                            ┌─────────┴─────────┐
                    approve / edit            reject
                            ↓                    ↓
                         publish               reject
                            ↓                    ↓
                     completed → END      rejected → END
```

`game_review.py` 定义状态、节点和分支。`game_storage.py` 用官方 `PostgresSaver` 保存检查点，`thread_id` 为回答轮次 ID。恢复时重新构造图，不重新检索或调用模型。

检查点变更和业务回答状态使用同一个 PostgreSQL 连接事务提交。审核时先锁咨询行再锁回答行，保证并发决定只有一个生效；完全相同的重复提交返回已保存结果，不同决定返回 409。审核失败回滚检查点和业务状态，可以重试。删除咨询时也删除对应检查点。

## API

`POST /api/game/chat` 增加 `human_review: true`。为兼容已有调用方，API 字段默认 `false`，网页默认开启。流式 token 是待审核草稿；持久化暂停后发送 `pending_review` 事件及 `turn_id`，此时不发送 `done`。同一请求 ID 重放保留审核状态。

```json
{ "type": "pending_review", "turn_id": "回答轮次 UUID" }
```

`GET /api/game/conversations/{conversation_id}` 的助手消息包含 `turn_id`、`status`、`draft`、`review` 和 `complete`。

`POST /api/game/conversations/{conversation_id}/turns/{turn_id}/review`：

```json
{ "action": "approve", "comment": "引用与步骤核对无误" }
```

```json
{ "action": "edit", "answer": "修订后的完整回答 [1]", "comment": "调整操作顺序" }
```

```json
{ "action": "reject", "comment": "依据不足，请补充内部规则后重新提问" }
```

接口返回更新后的助手消息。非法输入返回 422，不属于当前操作者的咨询返回 404，状态冲突返回 409。审核意见最多 2000 字，修改后的正文最多 24000 字。

## 安装与边界

运行 `npm run setup:api` 安装新增依赖后重启 API。首次初始化自动执行 `003_game_review.sql` 和官方 checkpointer 建表迁移；数据库账号需要对应 schema 的建表/改表权限。依赖版本兼容本项目 Python 3.9 与 langchain-core 0.3。

当前仍为本地单操作者模式，审核人来自服务端 `GAME_OWNER_ID`，不是独立审核员账号。若部署多人系统，需要接入可信登录身份和审核角色授权。草稿在操作者页面可见，审核控制的是「正式完成及进入上下文」，不是对操作者隐藏草稿。审核可选，不是强制的生产发布审批。

参考：[LangGraph interrupt 官方说明](https://reference.langchain.com/python/langgraph/types/interrupt)。

## 验证

- `test_game_review.py`：暂停、通过、编辑、驳回、重建图后恢复、非法审核输入。
- `test_game.py`：PostgreSQL 检查点恢复、请求重放、上下文隔离、权限隔离、并发决定、重复提交、事务失败回滚及删除清理。
- 集成测试使用独立随机 schema；通过 `REQUIRE_GAME_STORAGE_TESTS=1` 要求 PostgreSQL/Redis 必须可用，避免缺少服务时静默跳过。
