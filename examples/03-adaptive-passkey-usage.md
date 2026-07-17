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
4. 先对生成的 Controller Pack 本地文件计算精确 byte length 和 SHA-256；在同一条初始 Controller launch input 中附上 `PACK_IDENTITY_ATTESTATION`（绝对路径、byte length、SHA-256、parent create_thread observation），再发送完整 `.md`。Controller 必须从该本地路径独立复算，禁止 hash/decode `codex_delegation`、XML/HTML entities、UI 或 read_thread wrapper；缺失/不匹配时在创建任何子任务前停止。
5. 先确认当前 Codex App 能注入受保护的 `x-codex-app-action-receipt-v1`，覆盖 `THREAD_CREATE_OR_READ`、`AUTOMATION_OBSERVATION`、`SEND_MESSAGE_TO_THREAD`、`APP_TRANSPORT_OBSERVATION` 与 `AUTOMATION_UPDATE`。当前 App 缺少该能力时，在创建/读取 Worker 或 heartbeat 前以 `APP_ACTION_RECEIPT_ATTESTATION_UNAVAILABLE` 零副作用停止；不能用 transcript、参数或 Supervisor 绕过。
6. 能力存在时，Controller 仅通过 `state_gateway INITIALIZE` 建立 schema v3 canonical state；随后以 App 回执注册唯一当前 Worker/heartbeat（`REGISTER_TASK` / `REGISTER_HEARTBEAT`），不创建 State-Writer 或 native Goal。
7. 每条产品路线只用 `PREPARE_ROUTE -> runtime_codec MATERIALIZE_DISPATCH -> 一次 App send -> RECORD_ROUTE_SENT -> target STAGE_REPORT -> ACK_ROUTE_RESULT`。所有 lease、freshness、matrix、artifact 与 payload 由 Gateway 从 canonical state 原子生成，Controller 不复制。
8. Reviewer 不在启动时预创建；Worker 报告已写入且存在可审 diff 后再即时创建。worktree Reviewer 优先用 `fork_thread(... same-directory)`，否则传递可验证的绝对 worktree 路径和完整 diff。
9. 每次 Worker/Reviewer 只通过目标角色的 `runtime_codec STAGE_REPORT` stage 报告，再由 Gateway `ACK_ROUTE_RESULT` 或 `REPORT_RECOVERY` ACK 原 outbox；不得等待或伪造 `STATE_WRITE_APPLIED`。
10. 宿主具备受保护回执后，唯一业务 heartbeat 才能每 15 分钟观察一次；同一失败最多记录两次自然 heartbeat 或累计 15 分钟，然后进入 `WAITING_TRANSPORT_RECOVERY`。未获 App 暂停回执前不得宣称 PAUSED。
11. Goal Queue 全部通过后做完整 FINAL_AUDIT；只经 `PREPARE_FINALIZATION -> App-owned PAUSED receipt -> ACK_FINALIZATION` 到达 `FINALIZATION_ACKED`，不使用 native Goal 或 `LOOP_COMPLETE` 代称。

## 怎么回查 loop

- 控制线程：看 Pack identity、真实 Controller/Worker identity、Gateway route ledger、原 outbox、当前 Goal、派生 metrics 和下一动作；当前 App 无 receipt carrier 时只应看到零副作用能力阻断。
- 实现线程：看 worktree_path、Git 或 snapshot identity、changed_files、diff_summary、diff_sha256 和带 exit_code 的验证结果。
- 审查线程：看 severity-first 的 file/line findings、reviewed artifact identity 和 test gaps。
- 状态线程：看 Gateway request_id、event_id、state_version_before/after、route ledger 与 transaction journal，确认没有重复事件或半事务。
- heartbeat 卡片：看经 App `AUTOMATION_OBSERVATION` 证明的 automation id、ACTIVE/PAUSED、rrule、目标 Controller 任务和 transport recovery；缺回执时不是 ACTIVE 证据。
- `/workspace/adaptive-passkey-app/.codex-loop/LOOP_STATE.md`：schema-v3 canonical roadmap、Goal/route ledger、一个路线 outbox、lease、receipt-bound heartbeat、transport recovery、预算、审批与 finalization receipt；它没有 State-Writer/Goal outbox 身份。
- `/workspace/adaptive-passkey-app/.codex-loop/LOOP_EVENTS.jsonl`：按 event_id 记录的派发、ACK、重试、审查、停止流水。
- `/workspace/adaptive-passkey-app/.codex-loop/TRIAGE.md`：TRIAGE_ACTIONABLE/TRIAGE_NO_ACTION 发现及其证据和后续 Goal。
- `/workspace/adaptive-passkey-app/.codex-loop/reports/`：Worker、Reviewer 和 FINAL_AUDIT 报告归档。
- `/workspace/adaptive-passkey-app/.codex-loop/transactions/`：Gateway runtime 的 PREPARED/APPLIED 恢复日志；用于判断中断后缺哪一步，不能当作第二份 canonical state。
- `/workspace/adaptive-passkey-app/.codex-loop/sources/CONTROLLER_PACK.md`：初始化时归档的精确 Controller Pack；heartbeat 校验 PACK_SHA256 后用它抵抗长对话压缩。

正常信号：Gateway `GATEWAY_LOOP_INITIALIZED` 后，App receipt-bound `REGISTER_TASK` / `REGISTER_HEARTBEAT` 各登记一次；每个 Goal 只保留同一 route/outbox，报告仅由目标角色 stage 后 ACK；最终出现 `PREPARE_FINALIZATION`、已验证 heartbeat PAUSED receipt 与 `FINALIZATION_ACKED`。

异常信号：同一 BOOTSTRAP_MARKER 出现多个未归档任务、重复 heartbeat、未替换的 `MATERIALIZE_*` 运行时 token、重复 dispatch_id、状态版本倒退、Reviewer 看不到 worktree、Worker active 时 heartbeat 被暂停、state update 与下一 Goal 同时发送。

## 你只需要介入

- `MISSING_PROJECT_WORKSPACE`、`MISSING_SOURCE_ARTIFACT`、`THREAD_TOOLS_UNAVAILABLE`、`THREAD_BUDGET_EXHAUSTED`、`AUTOMATION_TOOLS_UNAVAILABLE`、`AUTOMATION_IDENTITY_UNRESOLVED`、`MISSING_CONNECTOR`。
- `DIRTY_WORKTREE_CONFLICT`、`WORKTREE_BOOTSTRAP_BLOCKED`、`WORKTREE_INTEGRATION_PLAN_MISSING`、`PATH_SCOPE_ESCAPE`、`THREAD_IDENTITY_UNRESOLVED`、`REVIEW_ARTIFACT_UNAVAILABLE`。
- `BLOCKED_COST_CAP`、`BLOCKED_USAGE_METADATA`、`AWAITING_HUMAN_APPROVAL`、`PHASE_PERMISSION_CONFLICT`。
- `APP_ACTION_RECEIPT_ATTESTATION_UNAVAILABLE`、`RUNTIME_CODEC_TOOL_UNAVAILABLE`、`RUNTIME_DEPENDENCY_BLOCKED`、`VALIDATION_BLOCKED`、`REPAIR_BUDGET_EXHAUSTED`、`WAITING_TRANSPORT_RECOVERY`、无法调和的 `STATE_VERSION_CONFLICT`/`RECOVERY_REQUIRED`、`ROUTING_BUDGET_EXHAUSTED`、`HARD_BLOCK`。

## 手动降级

当前 Codex App 缺少受保护 action-result receipt 时，不存在可安全的手动降级：记录 `APP_ACTION_RECEIPT_ATTESTATION_UNAVAILABLE` 并停止；不要以 State-Writer、参数、transcript 或 Supervisor 替代 Gateway 证据。


## Adaptive 模式怎么回查

- 发布状态：`beta/experimental`。Gateway、生成器、测试和安装检查只证明本地协议行为；真实 Codex App canary 与正式 Release 仍是单独的验收层。
- 本次运行策略：schema v3 `MCP_CANONICAL_WRITER`。实际角色只有 Controller、当前 Worker、可复用 Reviewer、按需 Local Verifier 和唯一业务 heartbeat；MCP State Gateway 是安装服务，不是一个 State-Writer 任务，Supervisor 也不是产品角色。
- `/workspace/adaptive-passkey-app/.codex-loop/LOOP_STATE.md` 是唯一 canonical source；`GOALS.md`、`STATUS.md` 和 `LOOP_METRICS.json` 都是派生观察面。状态投影滞后或语义冲突时，以 canonical state 和终态 receipt 为准。
- `/workspace/adaptive-passkey-app/.codex-loop/progress-dashboard.html`：只读进度看板，由 Gateway canonical state 派生。
- 正常慢：同一个 SENT outbox 有活跃 Worker/Reviewer 或新证据；只观察，不重复派发。传输退化：只有 App-owned `APP_TRANSPORT_OBSERVATION` 能记录同一指纹、outbox、时间和自然-heartbeat 身份；两次自然 heartbeat 或累计 15 分钟后进入 `WAITING_TRANSPORT_RECOVERY`，仅在 App 自身验证暂停回执后才投影 heartbeat PAUSED 并通知用户一次。真正终态：只有 `FINALIZATION_ACKED` 或经证据支持的 `LOOP_BLOCKED`，旧终态不可复活。
- 每条产品路线固定为 `PREPARE_ROUTE -> runtime_codec MATERIALIZE_DISPATCH -> 一次 App send -> RECORD_ROUTE_SENT -> 角色 STAGE_REPORT -> ACK_ROUTE_RESULT`。丢失 stdout/任务索引但已有 staged report 时，用 `REPORT_RECOVERY` ACK 原 outbox；绝不为补报告创建第二个产品 dispatch。
- Worker PASS 后的顺序是 Code Review、必要 Local Verification、Roadmap Audit；最终候选还需 Final Audit、`PREPARE_FINALIZATION`、App-owned heartbeat PAUSED receipt 和 `ACK_FINALIZATION` 才到达 `FINALIZATION_ACKED`。Gateway 只接纳同一 Goal、当前 Worker dispatch、当前 artifact 和 PASS 正式报告的三重绑定。
- `CAPTURE_COMPLETE_DIFF` 由 runtime 原样读取/反向校验 Git binary diff；模型不应在消息里搬运 patch bytes。`LOOP_METRICS.json` 可显示每 Goal 的总时长、已观测 Worker 窗口、控制面等待、拒绝和消息故障，但不是第二 canonical。
- schema v1/v2 State-Writer 仅兼容读取；迁移到 v3 必须在暂停且静默安全点显式 `MIGRATE_V2_TO_V3`。从已终态 predecessor 继续时，在全新 root 使用 `INITIALIZE_SUCCESSOR`，保留 predecessor 原样。
- 需要用户决定时只回复 Decision Card 中的 decision id 和 option id。卡片的批准仅覆盖列出的预授权动作，不包含 exclusions。
