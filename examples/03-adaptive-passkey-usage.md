## 生成文件

已生成 Controller Pack：`examples/03-adaptive-passkey-controller-pack.md`。
这个 Markdown 文件是发给控制线程的唯一材料，不需要拆分复制内部段落。

## 运行中卡点预估

前提：工作区、repo_mode、源文件、验收、权限、Goal Queue、验证和审查门已经齐全。

运行准备度：READY_BUT_LIKELY_REVIEW_REPAIRS

可能显著延长、自动重试或最终需要你介入的阶段：
1. First dependency install may require bounded registry retries

2. Authenticated browser state may be unavailable

3. Browser evidence may require another implementation/retest cycle

## 预计耗时

前提：启动前校验已经通过。这是 wall-clock 规划估算，不是 SLA。

最短时间 min：6 hours
典型时间：14 hours
最大时间 max：2 days

当前 heartbeat 总预算覆盖约 2 天（15 分钟 x 192 次）；预计任务超过该范围时必须在启动前提高 max_wakeups。

不计入：等待凭证、deploy/merge 批准、真人验收和外部服务恢复的时间。

可能拉长时间的因素：
- Dependency cache availability
- Number of browser-discovered repair rounds
- Availability of an authenticated local browser profile

## 成本/付费调用闸

- cost_cap_usd：`UNSPECIFIED`
- call_cap：`UNSPECIFIED`
- token_cap：`UNSPECIFIED`
- metered_runtime_policy：`Real paid LLM/provider calls are deferred; local deterministic implementation and browser verification only`

控制线程必须维护 budget_ledger；明确 deferred/forbidden 时只完成本地阶段。

## 你应该怎么用

1. 在 Codex App 左侧选择或创建项目工作区：`adaptive-passkey-app`，根目录必须是 `/workspace/adaptive-passkey-app`。
2. 当前 repo_mode 是 `existing_git`：`existing_git` 先检查现有 git/worktree/脏文件；`new_git` 第一阶段先用 local Worker，且只有 Goal 的 `git_init/branch_create` 为 true 才初始化；`non_git` 不执行分支/worktree 检查。
3. 把资料放进工作区或提供子线程可读的绝对路径：SELF_CONTAINED。只附在控制聊天里的文件不会自动传给新线程。
4. 在这个工作区中新建一个“控制线程”，发送生成的 Controller Pack `.md` 文件。
5. 控制线程使用 `list_projects`、`list_threads`、`create_thread`、`read_thread`、`send_message_to_thread` 创建和恢复真实项目任务，禁止用 sub-agent 冒充；Adaptive 必须先以 `THREAD` outbox 的 `PREPARED -> SENT -> ACKED` 登记真实 threadId，才能派发。
6. 控制线程先通过确定性 runtime 完成 `INITIALIZE`，收到 `LOOP_INITIALIZED`；再以独立 lease 执行 `AUTOMATION` outbox 的 `PREPARED -> SENT -> ACKED`，核对本机记录后只创建或认领一个 heartbeat。
7. 所有 `MATERIALIZE_*` token 必须替换为真实 `threadId`、dispatch identity、lease claim 和 canonical state snapshot；Worker 派发使用 `DISPATCH` outbox：`PREPARED -> 发送一次 -> SENT -> strict JSON report -> COMPLETED`。
8. Reviewer 不在启动时预创建；Worker 报告已写入且存在可审 diff 后再即时创建。worktree Reviewer 优先用 `fork_thread(... same-directory)`，否则传递可验证的绝对 worktree 路径和完整 diff。
9. 每次 Worker/Reviewer 回报先写状态并等待 `STATE_WRITE_APPLIED`，再进入 review、repair 或下一 Goal。
10. heartbeat 每 15 分钟唤醒，最多 192 次；Worker 正在运行时记录 `WAITING_ACTIVE`，不能 NOOP 关闭。只有终态或无 inflight/queue 且连续 8 次 idle 才允许暂停。
11. Goal Queue 全部通过后还要做一次完整 Git base-to-head 或 non_git before-to-after snapshot FINAL_AUDIT，最终状态写入成功后才是 `LOOP_COMPLETE`。

## 怎么回查 loop

- 控制线程：看 PACK_SHA256/LOOP_ID、真实 threadId、routing turn/lease、generic outbox、Goal Queue、runtime ACK 和下一动作。
- 实现线程：看 worktree_path、Git 或 snapshot identity、changed_files、diff_summary、diff_sha256 和带 exit_code 的验证结果。
- 审查线程：看 severity-first 的 file/line findings、reviewed artifact identity 和 test gaps。
- 状态线程：看 state_request_id、event_id、state_version_before/after、transaction journal，确认没有重复事件或半事务。
- heartbeat 卡片：看 automation id、ACTIVE/PAUSED、rrule、目标控制任务和 canonical `routing_turn_count`。
- `/workspace/adaptive-passkey-app/.codex-loop/LOOP_STATE.md`：版本化 canonical roadmap、Goal 定义/执行 ledger、thread/automation/Goal/dispatch/assurance/local/delegation outbox、lease、预算、审批和 finalization receipt。
- `/workspace/adaptive-passkey-app/.codex-loop/LOOP_EVENTS.jsonl`：按 event_id 记录的派发、ACK、重试、审查、停止流水。
- `/workspace/adaptive-passkey-app/.codex-loop/TRIAGE.md`：TRIAGE_ACTIONABLE/TRIAGE_NO_ACTION 发现及其证据和后续 Goal。
- `/workspace/adaptive-passkey-app/.codex-loop/reports/`：Worker、Reviewer 和 FINAL_AUDIT 报告归档。
- `/workspace/adaptive-passkey-app/.codex-loop/transactions/`：State-Writer 的 PREPARED/APPLIED 恢复日志；用于判断中断后缺哪一步，不能当作第二份 canonical state。
- `/workspace/adaptive-passkey-app/.codex-loop/sources/CONTROLLER_PACK.md`：初始化时归档的精确 Controller Pack；heartbeat 校验 PACK_SHA256 后用它抵抗长对话压缩。

正常信号：`LOOP_INITIALIZED` 后只出现一个当前 Worker 的 `THREAD_OUTBOX_ACKED` 和唯一 heartbeat 的 `AUTOMATION_OUTBOX_ACKED`；active 工作保持原 `SENT` identity 并按需续租，不会重发；Worker strict JSON 报告绑定后 `DISPATCH_OUTBOX_ACKED`/COMPLETED；三类 assurance 独立 ACK；最终出现 `FINALIZE_LOOP_APPLIED` 与 `FINALIZATION_ACKED`。

异常信号：同一 BOOTSTRAP_MARKER 出现多个未归档任务、重复 heartbeat、未替换的 `MATERIALIZE_*` 运行时 token、重复 dispatch_id、状态版本倒退、Reviewer 看不到 worktree、Worker active 时 heartbeat 被暂停、state update 与下一 Goal 同时发送。

## 你只需要介入

- `MISSING_PROJECT_WORKSPACE`、`MISSING_SOURCE_ARTIFACT`、`THREAD_TOOLS_UNAVAILABLE`、`THREAD_BUDGET_EXHAUSTED`、`AUTOMATION_TOOLS_UNAVAILABLE`、`AUTOMATION_IDENTITY_UNRESOLVED`、`MISSING_CONNECTOR`。
- `DIRTY_WORKTREE_CONFLICT`、`WORKTREE_BOOTSTRAP_BLOCKED`、`WORKTREE_INTEGRATION_PLAN_MISSING`、`PATH_SCOPE_ESCAPE`、`THREAD_IDENTITY_UNRESOLVED`、`REVIEW_ARTIFACT_UNAVAILABLE`。
- `BLOCKED_COST_CAP`、`BLOCKED_USAGE_METADATA`、`AWAITING_HUMAN_APPROVAL`、`PHASE_PERMISSION_CONFLICT`。
- `RUNTIME_DEPENDENCY_BLOCKED`、`VALIDATION_BLOCKED`、`REPAIR_BUDGET_EXHAUSTED`、无法调和的 `STATE_VERSION_CONFLICT`/`RECOVERY_REQUIRED`、`ROUTING_BUDGET_EXHAUSTED`、`HARD_BLOCK`。

## 手动降级

只有真实 Codex App 线程或 heartbeat 工具不可用时才使用。手动模式仍需真实项目线程、版本化单写者状态、精确 worktree 审查和相同停止条件。


## Adaptive 模式怎么回查

- 发布状态：`beta/experimental`。确定性 runtime、生成器、测试和安装检查只证明本地协议行为；不能据此声称所有 Codex App 环境都能自动循环到终态。
- 本次运行策略：`adaptive`。输出详略模式与它独立，不影响一份 Pack 启动方式。
- Adaptive 的实际启动顺序：唯一 State-Writer -> `INITIALIZE`/GOALS/Pack 归档 ACK -> 当前 Worker、heartbeat、Controller Goal、First Goal 各自使用一轮独立的 `ACQUIRE_LEASE -> outbox -> 外部动作 -> ACK`。前一轮 lease 消费后才开始下一轮，不能复用同一个启动 lease。
- `/workspace/adaptive-passkey-app/.codex-loop/GOALS.md`：当前里程碑、为什么这样排序、需要什么证据、最近为何改计划；它是 `LOOP_STATE.md` 的只读投影。
- `/workspace/adaptive-passkey-app/.codex-loop/progress-dashboard.html`：只读进度看板，由状态生成。
- `/workspace/adaptive-passkey-app/.codex-loop/LOOP_STATE.md` 还应能回查 `goal_definition_registry`、`goal_execution_ledger`、`controller_goal_outbox`、`controller_lease`/已消费 lease id 和三阶段 assurance identity；缺少这些不是完整 Adaptive 初始化。
- 长任务超过 lease TTL 时，应看到 `SAME_OWNER_LEASE_RENEWED`、原 `SENT` outbox 的新 claim 和未变化的 dispatch/payload identity；不应出现第二次发送。
- Worker/Reviewer/Local 回报归档后，canonical `report_digest` 必须等于 `.codex-loop/reports/` 中对应 `application/json` 文件的实际 SHA-256；`PENDING_CONTROLLER_ARCHIVE` 不能直接进入状态。State-Writer 必须让 runtime 在 ACK 前解析报告并把顶层 dispatch/Goal/milestone/roadmap/target/payload/artifact/decision/source identity 与当前 SENT outbox 精确绑定；嵌套字段不能补齐缺失的顶层身份。
- 代码审查、路线图审计和最终完整审查复用一个只读审查任务，但会显示为独立派发和独立报告。
- Local Verifier 只在需要真实浏览器、本机权限、模拟器、设备或账号状态时创建。
- 自动只读子代理策略为 `auto_read_only`；配置上限为 2 个、全程最多 4 次运行。当前确定性路由每个 lease 只串行运行一个 sidecar，不承诺同时并发；它们只做短时搜索/归类，正式角色仍是同一项目下可回查的真实任务。
- 正常顺序：实现报告 ACK -> 代码审查 ACK -> 必要的本机验证 ACK -> 路线图审计 ACK -> GOALS 投影 ACK -> 切换唯一 Active milestone；最后一个里程碑还要经过最终完整审查 ACK 和独立终态写入 ACK。
- `ROADMAP_CHANGE_REQUIRES_APPROVAL` 表示新计划扩大了原始授权；`CONTROLLER_GOAL_CONFLICT` 表示当前任务已有不匹配的 Goal；`WAITING_CONTROLLER_LEASE` 表示另一个 Goal/heartbeat 回合正在安全路由。
- 每次状态变化只看 `What's done / What's next / Any blockers`；需要底层排障时再查看事件、事务和任务报告。
