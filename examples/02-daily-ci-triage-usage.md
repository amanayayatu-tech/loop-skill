## 生成文件

已生成 Controller Pack：`examples/02-daily-ci-triage-controller-pack.md`。
这个 Markdown 文件是发给控制线程的唯一材料，不需要拆分复制内部段落。

## 运行中卡点预估

前提：工作区、repo_mode、源文件、验收、权限、Goal Queue、验证和审查门已经齐全。

运行准备度：READY_WITH_EXPECTED_GATES

可能显著延长、自动重试或最终需要你介入的阶段：
1. 阶段：依赖安装 / 本地验证环境
为什么会停：registry、native binary、浏览器依赖或 package store 可能波动
触发状态：RUNTIME_DEPENDENCY_RETRYING；预算耗尽后 RUNTIME_DEPENDENCY_BLOCKED
自动处理：按超时、无进展 watchdog、退避、续传、预取、安全备用源和项目内清理的梯队重试
你会被问什么：只有重试预算耗尽或下一步需要凭证/全局改动时才会询问

2. 阶段：验证与独立审查修复
为什么会停：测试或 Reviewer 可能发现真实缺口
触发状态：NEEDS_REPAIR | REVIEW_NEEDS_REPAIR
自动处理：在修复预算内自动回派同一 Worker，状态写入确认后再复审
你会被问什么：只有修复预算耗尽或范围需要扩大时才会询问

## 预计耗时

前提：启动前校验已经通过。这是 wall-clock 规划估算，不是 SLA。

最短时间 min：30-60 分钟主动设置
典型时间：1-2 小时完成首轮，之后每次 wakeup 约 10-30 分钟
最大时间 max：半天，若 CI/connector 不稳定会更长

当前 heartbeat 总预算覆盖约 12 小时（15 分钟 x 48 次）；预计任务超过该范围时必须在启动前提高 max_wakeups。

不计入：等待凭证、deploy/merge 批准、真人验收和外部服务恢复的时间。

可能拉长时间的因素：
- GitHub connector availability
- CI log quality
- local test runtime
- repair round count



## 你应该怎么用

1. 在 Codex App 左侧选择或创建项目工作区：`product-app`，根目录必须是 `/workspace/product-app`。
2. 当前 repo_mode 是 `existing_git`：`existing_git` 先检查现有 git/worktree/脏文件；`new_git` 第一阶段先用 local Worker，且只有 Goal 的 `git_init/branch_create` 为 true 才初始化；`non_git` 不执行分支/worktree 检查。
3. 把资料放进工作区或提供子线程可读的绝对路径：/workspace/product-app/docs/ci-evidence/。只附在控制聊天里的文件不会自动传给新线程。
4. 在这个工作区中新建一个“控制线程”，发送生成的 Controller Pack `.md` 文件。
5. 控制线程使用 `list_projects`、`list_threads`、`create_thread`、`read_thread`、`send_message_to_thread` 创建和恢复真实项目线程，禁止用 sub-agent 冒充；先看到 `THREAD_REGISTERED` 才能派发。
6. 控制线程先初始化版本化状态，收到 State-Writer ACK，再写 `AUTOMATION_CREATE_PREPARED`；核对本机已有 automation 后，仅在没有精确匹配时用准确的 `automation_update(mode="create", kind="heartbeat", destination="thread", rrule=...)` 创建一次，并写 `AUTOMATION_REGISTERED`。
7. 所有 `MATERIALIZE_*` 运行时 token 必须替换为真实 `threadId`、`dispatch_id` 和 state snapshot；先写 `DISPATCH_PREPARED` 并等 ACK，发送一次，再写 `DISPATCH_SENT`。
8. Reviewer 不在启动时预创建；Worker 报告已写入且存在可审 diff 后再即时创建。worktree Reviewer 优先用 `fork_thread(... same-directory)`，否则传递可验证的绝对 worktree 路径和完整 diff。
9. 每次 Worker/Reviewer 回报先写状态并等待 `STATE_WRITE_APPLIED`，再进入 review、repair 或下一 Goal。
10. heartbeat 每 15 分钟唤醒，最多 48 次；Worker 正在运行时记录 `WAITING_ACTIVE`，不能 NOOP 关闭。只有终态或无 inflight/queue 且连续 8 次 idle 才允许暂停。
11. Goal Queue 全部通过后还要做一次完整 Git base-to-head 或 non_git before-to-after snapshot FINAL_AUDIT，最终状态写入成功后才是 `LOOP_COMPLETE`。

## 怎么回查 loop

- 控制线程：看 PACK_SHA256/LOOP_ID、`THREAD_REGISTERED`、真实 threadId、dispatch_id、Goal Queue、状态 ACK 和下一动作。
- 实现线程：看 worktree_path、Git 或 snapshot identity、changed_files、diff_summary、diff_sha256 和带 exit_code 的验证结果。
- 审查线程：看 severity-first 的 file/line findings、reviewed artifact identity 和 test gaps。
- 状态线程：看 state_request_id、event_id、state_version_before/after、transaction journal，确认没有重复事件或半事务。
- heartbeat 卡片：看 automation id、ACTIVE/PAUSED、rrule、目标控制线程和 wake 计数。
- `/workspace/product-app/.codex-loop/LOOP_STATE.md`：版本化当前快照、Goal Queue、thread-creation/automation/dispatch outbox、inflight dispatch、线程登记、预算和审批 ledger。
- `/workspace/product-app/.codex-loop/LOOP_EVENTS.jsonl`：按 event_id 记录的派发、ACK、重试、审查、停止流水。
- `/workspace/product-app/.codex-loop/TRIAGE.md`：TRIAGE_ACTIONABLE/TRIAGE_NO_ACTION 发现及其证据和后续 Goal。
- `/workspace/product-app/.codex-loop/reports/`：Worker、Reviewer 和 FINAL_AUDIT 报告归档。
- `/workspace/product-app/.codex-loop/transactions/`：State-Writer 的 PREPARED/APPLIED 恢复日志；用于判断中断后缺哪一步，不能当作第二份 canonical state。
- `/workspace/product-app/.codex-loop/sources/CONTROLLER_PACK.md`：初始化时归档的精确 Controller Pack；heartbeat 校验 PACK_SHA256 后用它抵抗长对话压缩。

正常信号：State-Writer 后出现恰好一个当前 Worker 的 `THREAD_REGISTERED`，再出现唯一的 `AUTOMATION_REGISTERED`；`WAITING_ACTIVE` 不会关闭 heartbeat；新任务依次出现 `DISPATCH_PREPARED` 和 `DISPATCH_SENT`；`STATE_WRITE_APPLIED` 后才继续；`REVIEW_PASS` 后准确派发一个已解锁 Goal；队列结束后出现 FINAL_AUDIT。

异常信号：同一 BOOTSTRAP_MARKER 出现多个未归档任务、重复 heartbeat、未替换的 `MATERIALIZE_*` 运行时 token、重复 dispatch_id、状态版本倒退、Reviewer 看不到 worktree、Worker active 时 heartbeat 被暂停、state update 与下一 Goal 同时发送。

## 你只需要介入

- `MISSING_PROJECT_WORKSPACE`、`MISSING_SOURCE_ARTIFACT`、`THREAD_TOOLS_UNAVAILABLE`、`THREAD_BUDGET_EXHAUSTED`、`AUTOMATION_TOOLS_UNAVAILABLE`、`AUTOMATION_IDENTITY_UNRESOLVED`、`MISSING_CONNECTOR`。
- `DIRTY_WORKTREE_CONFLICT`、`WORKTREE_BOOTSTRAP_BLOCKED`、`WORKTREE_INTEGRATION_PLAN_MISSING`、`PATH_SCOPE_ESCAPE`、`THREAD_IDENTITY_UNRESOLVED`、`REVIEW_ARTIFACT_UNAVAILABLE`。
- `BLOCKED_COST_CAP`、`BLOCKED_USAGE_METADATA`、`AWAITING_HUMAN_APPROVAL`、`PHASE_PERMISSION_CONFLICT`。
- `RUNTIME_DEPENDENCY_BLOCKED`、`VALIDATION_BLOCKED`、`REPAIR_BUDGET_EXHAUSTED`、`STATE_VERSION_CONFLICT` 无法自动调和、`HEARTBEAT_BUDGET_EXHAUSTED`、`HEARTBEAT_IDLE_BUDGET_EXHAUSTED`、`HARD_BLOCK`。

## 手动降级

只有真实 Codex App 线程或 heartbeat 工具不可用时才使用。手动模式仍需真实项目线程、版本化单写者状态、精确 worktree 审查和相同停止条件。
