"""Byte-compatible Standard rendering primitives and user guide."""

from __future__ import annotations

from typing import Any


def _table_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_goal_queue_table(
    goals: list[dict[str, Any]],
    adaptive: bool = False,
    active_milestone_id: str | None = None,
) -> str:
    if adaptive:
        rows = [
            "| Order | Goal ID | Milestone ID | Initial Roadmap Version | Initial Queue Status | Worker | Depends On | Dispatch When |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        ready_assigned = False
        for index, goal in enumerate(goals, 1):
            depends = ", ".join(goal["depends_on"]) or "none"
            queue_status = "PLANNED"
            if (
                not ready_assigned
                and goal.get("milestone_id") == active_milestone_id
                and not goal["depends_on"]
            ):
                queue_status = "READY"
                ready_assigned = True
            rows.append(
                f"| {index} | {_table_cell(goal['goal_id'])} | {_table_cell(goal.get('milestone_id'))} | 1 | {queue_status} | "
                f"{_table_cell(goal['worker_role'])} | {_table_cell(depends)} | {_table_cell(goal['dispatch_when'])} |"
            )
        return "\n".join(rows)
    rows = ["| Order | Goal ID | Worker | Depends On | Dispatch When |", "| --- | --- | --- | --- | --- |"]
    for index, goal in enumerate(goals, 1):
        depends = ", ".join(goal["depends_on"]) or "none"
        rows.append(
            f"| {index} | {_table_cell(goal['goal_id'])} | {_table_cell(goal['worker_role'])} | "
            f"{_table_cell(depends)} | {_table_cell(goal['dispatch_when'])} |"
        )
    return "\n".join(rows)


def render_full_mode_sections(
    data: dict[str, Any], goals: list[dict[str, Any]], errors: list[str]
) -> str:
    test_goal = goals[0]["goal_id"] if goals else "G1"
    gateway_v3 = (
        data.get("coordination_mode") == "adaptive"
        and data.get("state_gateway_mode", "MCP_CANONICAL_WRITER")
        == "MCP_CANONICAL_WRITER"
    )
    law_status = "PASS" if not errors else "BLOCKED"
    score_line = (
        "Loop Integrity Score: 12/12 for the generated contract. Runtime conformance still requires a Codex App smoke run."
        if not errors
        else f"Loop Integrity Score: 0/12. NON_DISPATCHABLE_DRAFT validation errors: {', '.join(errors)}"
    )
    adaptive_flow = (
        "  -> required Local Verifier evidence -> same Reviewer ROADMAP_AUDIT ACK\n"
        "  -> Gateway ADVANCE_ROADMAP over unchanged registry\n"
        "  -> final candidate -> same Reviewer FINAL_AUDIT ACK -> PREPARE_FINALIZATION\n"
        if gateway_v3
        else
        "  -> required Local Verifier evidence -> same Reviewer ROADMAP_AUDIT ACK\n"
        "  -> in-envelope roadmap CAS update -> GOALS/dashboard projection ACK\n"
        "  -> complete/recover native Controller Goal -> activate one next milestone\n"
        "  -> final candidate -> same Reviewer FINAL_AUDIT ACK -> FINALIZE_LOOP ACK\n"
        if data.get("coordination_mode") == "adaptive"
        else ""
    )
    completion_flow = (
        "  -> actual heartbeat PAUSED readback -> ACK_FINALIZATION -> FINALIZATION_ACKED"
        if gateway_v3
        else
        "  -> exact Goal COMPLETE + exact heartbeat PAUSED readbacks\n"
        "  -> ACK_FINALIZATION -> FINALIZATION_ACKED"
        if data.get("coordination_mode") == "adaptive"
        else "  -> next queued goal OR final integrated review\n"
        "  -> terminal state ACK -> pause heartbeat"
    )
    termination_fix = (
        "Repair, runtime retry, shared routing-turn, and active-stale budgets are bounded."
        if data.get("coordination_mode") == "adaptive"
        else "Repair, runtime retry, wake, idle, and stale-active budgets are bounded."
    )
    durable_state_fix = (
        "Gateway-owned versioned runtime state, recovery journal, route outboxes, queue, heartbeat, and ledgers are included."
        if gateway_v3
        else
        "Versioned runtime state, recovery journal, generic outboxes, queue, heartbeat, and ledgers are included."
        if data.get("coordination_mode") == "adaptive"
        else "Versioned single-writer state, recovery journal, creation/dispatch outboxes, queue, heartbeat, and ledgers are included."
    )
    heartbeat_change = (
        "Goal/heartbeat competition could duplicate routing"
        if data.get("coordination_mode") == "adaptive"
        else "active work could become terminal NOOP"
    )
    heartbeat_control = (
        "one fenced lease per counted routing turn; WAITING_ACTIVE never routes twice"
        if data.get("coordination_mode") == "adaptive"
        else "WAITING_ACTIVE, idle budget, total wake budget, terminal-only pause"
    )
    outbox_control = (
        "Gateway host-cooperative registrations plus one canonical route outbox with exact identities"
        if gateway_v3
        else
        "generic THREAD/AUTOMATION/GOAL/DISPATCH outboxes with exact identities"
        if data.get("coordination_mode") == "adaptive"
        else "deterministic markers plus thread, automation, and dispatch outboxes"
    )
    startup_flow = (
        "  -> MCP State Gateway INITIALIZE -> no State-Writer task\n"
        "  -> real App task/heartbeat return/readback -> REGISTER_TASK/REGISTER_HEARTBEAT\n"
        if gateway_v3
        else
        "  -> State-Writer recovery/create -> full LOOP_INITIALIZED + GOALS projection ACK\n"
        "  -> startup Controller lease ACK\n"
        "  -> THREAD outbox PREPARED -> create/reconcile once -> SENT -> ACKED\n"
        "  -> AUTOMATION outbox PREPARED -> create/reconcile once -> SENT -> ACKED\n"
        "  -> GOAL outbox PREPARED -> native SENT/ACKED or emulated direct ACK\n"
        if data.get("coordination_mode") == "adaptive"
        else "  -> State-Writer recovery/create -> State init ACK\n"
        "  -> THREAD_CREATE_PREPARED -> current Worker THREAD_REGISTERED ACK\n"
        "  -> AUTOMATION_CREATE_PREPARED -> heartbeat reconcile/create -> REGISTERED ACK\n"
    )
    dispatch_flow = (
        "  -> Gateway PREPARE_ROUTE -> runtime_codec payload -> one App send/RECORD_ROUTE_SENT\n"
        "  -> target-owned staged report -> ACK_ROUTE_RESULT"
        if gateway_v3
        else
        "  -> DISPATCH outbox PREPARED -> materialized WORKER_DISPATCH + state snapshot -> send once -> SENT\n"
        "  -> strict JSON Worker report archive -> ACK_OUTBOX -> COMPLETED"
        if data.get("coordination_mode") == "adaptive"
        else "  -> DISPATCH_PREPARED ACK -> materialized /goal + state snapshot -> DISPATCH_SENT ACK"
    )
    report_ack = "Gateway ACK_ROUTE_RESULT" if gateway_v3 else "State ACK"
    review_ack = (
        "exact-artifact review route -> Gateway ACK_ROUTE_RESULT"
        if gateway_v3
        else "exact-artifact /review with diff_sha256 -> Review ACK"
    )
    return f"""
## Loop Diagnosis

| Law | Status | Generated Fix |
| --- | --- | --- |
| L1 Role Isolation | {law_status} | Controller routes; scoped Workers execute; {"MCP State Gateway owns canonical files" if gateway_v3 else "State-Writer owns audit files"}. |
| L2 Addressing | {law_status} | Real threadId/worktree materialization is required before dispatch. |
| L3 Atomic Goals | {law_status} | Goal Queue contains identified dependency-ordered goals. |
| L4 Acceptance First | {law_status} | Every goal embeds success criteria before execution details. |
| L5 Forbidden Zones | {law_status} | Forbidden paths/actions and side-effect permissions are explicit. |
| L6 Termination | {law_status} | {termination_fix} |
| L7 Side Effects | {law_status} | Goal-specific permission matrix controls commits, deploys, and external writes. |
| L8 Structured Status | {law_status} | Reports carry goal/dispatch/thread/worktree/diff/validation identity. |
| L9 Self-Contained Context | {law_status} | Each queued goal is a complete materializable template. |
| L10 Evidence Boundary | {law_status} | Evidence and claim layers are explicit. |
| L11 Durable State | {law_status} | {durable_state_fix} |
| L12 Review Gate | {law_status} | Exact-artifact per-goal and final integrated review are required. |

{score_line}

## Changelog

| Change | Original Risk | Revised Control | Law |
| --- | --- | --- | --- |
| Materialized IDs | Placeholder routing | Real thread_id and dispatch_id before send | L2/L8 |
| Versioned state | Duplicate dispatch/state races | CAS state_version plus event/request idempotency | L6/L11 |
| Worktree review | Reviewer could inspect wrong checkout | same-directory Reviewer or exact absolute artifact mapping | L12 |
| Heartbeat lifecycle | {heartbeat_change} | {heartbeat_control} | L6/L11 |
| Goal queue | vague next goal | dependency-ordered queue and triage transitions | L3/L11 |
| Bootstrap/outboxes | duplicate task or heartbeat after interruption | {outbox_control} | L2/L6/L11 |
| Crash recovery | torn state/event/report writes | PREPARED/APPLIED state-write journal and reconciliation | L8/L11 |

## Flow Map

```text
Controller preflight -> deterministic loop/bootstrap identity
{startup_flow}{dispatch_flow}
  -> Worker report -> {report_ack}
  -> {review_ack}
{adaptive_flow}{completion_flow}
```

## Test Goals

- Normal progress: {test_goal} -> Worker report -> {report_ack} -> review -> next queue/final audit.
- Hard blocker: missing source/cost/connector/worktree evidence stops before side effects.
- Idempotency: replay the same event_id/state_request_id and verify no duplicate event or dispatch.
- Creation recovery: interrupt after task/automation create but before registration and verify exact adoption without duplicates.
- Crash consistency: interrupt each state journal step and verify recovery performs only the missing write.
- Active heartbeat: wake while Worker is active and verify WAITING_ACTIVE without archive or duplicate goal.
- Compaction safety: dispatch a later queued goal using only its materialized block plus canonical state snapshot.

## Final Next Step

Send this complete Markdown file to one Controller thread inside the declared Codex Project. Do not paste individual blocks. The Controller must materialize runtime placeholders before dispatch.
"""


def render_standard_user_guide(
    runtime: Any,
    data: dict[str, Any],
    controller_pack_path: str | None,
) -> str:
    workers = runtime.normalize_workers(data)
    validation = runtime.parse_commands(data.get("validation"))
    repo = str(data.get("repo", "PLACEHOLDER"))
    repo_mode = str(data.get("repo_mode", "PLACEHOLDER"))
    project_name = str(data.get("project_name") or runtime.project_name_from_repo(repo))
    project_root = str(data.get("project_root") or repo)
    workspace_selection_line = (
        f"1. 在 Codex App 左侧选择或创建项目工作区：`{project_name}`，项目根目录必须是 `{project_root}`。目标工作目录是 `{repo}`。"
        if project_root != repo
        else f"1. 在 Codex App 左侧选择或创建项目工作区：`{project_name}`，根目录必须是 `{repo}`。"
    )
    source_artifacts = runtime.parse_csv_items(data.get("source_artifacts"))
    state = str(data.get("state", ".codex-loop/LOOP_STATE.md"))
    triage = str(data.get("triage_output", ".codex-loop/TRIAGE.md"))
    audit_paths = runtime.loop_audit_paths(repo, state, triage)
    heartbeat_interval = runtime.int_value(data, "heartbeat_interval_minutes", 15)
    max_wakeups = runtime.int_value(data, "max_wakeups", 192)
    max_idle = runtime.int_value(data, "max_idle_wakeups", 8)
    errors = runtime.validation_errors(data)
    adaptive = data.get("coordination_mode") == "adaptive"
    gateway_v3 = (
        adaptive
        and data.get("state_gateway_mode", "MCP_CANONICAL_WRITER")
        == "MCP_CANONICAL_WRITER"
    )
    controller_launch_step = (
        "4. 先对生成的 Controller Pack 本地文件计算精确 byte length 和 SHA-256；在同一条初始 Controller launch input 中附上 `PACK_IDENTITY_ATTESTATION`（绝对路径、byte length、SHA-256、parent create_thread observation），再发送完整 `.md`。Controller 必须从该本地路径独立复算，禁止 hash/decode `codex_delegation`、XML/HTML entities、UI 或 read_thread wrapper；缺失/不匹配时在创建任何子任务前停止。"
        if adaptive
        else "4. 在这个工作区中新建一个“控制线程”，发送生成的 Controller Pack `.md` 文件。"
    )
    task_setup_steps = (
        "5. 控制线程使用 `list_projects`、`list_threads`、`create_thread`、`read_thread`、`send_message_to_thread` 创建和恢复真实项目任务，禁止用 sub-agent 冒充；Adaptive 必须先以 `THREAD` outbox 的 `PREPARED -> SENT -> ACKED` 登记真实 threadId，才能派发。\n"
        "6. 控制线程先通过确定性 runtime 完成 `INITIALIZE`，收到 `LOOP_INITIALIZED`；再以独立 lease 执行 `AUTOMATION` outbox 的 `PREPARED -> SENT -> ACKED`，核对本机记录后只创建或认领一个 heartbeat。\n"
        "7. 所有 `MATERIALIZE_*` token 必须替换为真实 `threadId`、dispatch identity、lease claim 和 canonical state snapshot；Worker 派发使用 `DISPATCH` outbox：`PREPARED -> 发送一次 -> SENT -> strict JSON report -> COMPLETED`。"
        if adaptive
        else "5. 控制线程使用 `list_projects`、`list_threads`、`create_thread`、`read_thread`、`send_message_to_thread` 创建和恢复真实项目线程，禁止用 sub-agent 冒充；先看到 `THREAD_REGISTERED` 才能派发。\n"
        "6. 控制线程先初始化版本化状态，收到 State-Writer ACK，再写 `AUTOMATION_CREATE_PREPARED`；核对本机已有 automation 后，仅在没有精确匹配时用准确的 `automation_update(mode=\"create\", kind=\"heartbeat\", destination=\"thread\", rrule=...)` 创建一次，并写 `AUTOMATION_REGISTERED`。\n"
        "7. 所有 `MATERIALIZE_*` 运行时 token 必须替换为真实 `threadId`、`dispatch_id` 和 state snapshot；先写 `DISPATCH_PREPARED` 并等 ACK，发送一次，再写 `DISPATCH_SENT`。"
    )
    controller_check = (
        "- 控制线程：看 PACK_SHA256/LOOP_ID、真实 threadId、routing turn/lease、generic outbox、Goal Queue、runtime ACK 和下一动作。"
        if adaptive
        else "- 控制线程：看 PACK_SHA256/LOOP_ID、`THREAD_REGISTERED`、真实 threadId、dispatch_id、Goal Queue、状态 ACK 和下一动作。"
    )
    heartbeat_check = (
        "- heartbeat 卡片：看 automation id、ACTIVE/PAUSED、rrule、目标控制任务和 canonical `routing_turn_count`。"
        if adaptive
        else "- heartbeat 卡片：看 automation id、ACTIVE/PAUSED、rrule、目标控制线程和 wake 计数。"
    )
    state_check = (
        f"- `{audit_paths['state']}`：版本化 canonical roadmap、Goal 定义/执行 ledger、thread/automation/Goal/dispatch/assurance/local/delegation outbox、lease、预算、审批和 finalization receipt。"
        if adaptive
        else f"- `{audit_paths['state']}`：版本化当前快照、Goal Queue、thread-creation/automation/dispatch outbox、inflight dispatch、线程登记、预算和审批 ledger。"
    )
    normal_signal = (
        "正常信号：`LOOP_INITIALIZED` 后只出现一个当前 Worker 的 `THREAD_OUTBOX_ACKED` 和唯一 heartbeat 的 `AUTOMATION_OUTBOX_ACKED`；active 工作保持原 `SENT` identity 并按需续租，不会重发；Worker strict JSON 报告绑定后 `DISPATCH_OUTBOX_ACKED`/COMPLETED；三类 assurance 独立 ACK；最终出现 `FINALIZE_LOOP_APPLIED` 与 `FINALIZATION_ACKED`。"
        if adaptive
        else "正常信号：State-Writer 后出现恰好一个当前 Worker 的 `THREAD_REGISTERED`，再出现唯一的 `AUTOMATION_REGISTERED`；`WAITING_ACTIVE` 不会关闭 heartbeat；新任务依次出现 `DISPATCH_PREPARED` 和 `DISPATCH_SENT`；`STATE_WRITE_APPLIED` 后才继续；`REVIEW_PASS` 后准确派发一个已解锁 Goal；队列结束后出现 FINAL_AUDIT。"
    )
    runtime_blockers = (
        "- `RUNTIME_DEPENDENCY_BLOCKED`、`VALIDATION_BLOCKED`、`REPAIR_BUDGET_EXHAUSTED`、无法调和的 `STATE_VERSION_CONFLICT`/`RECOVERY_REQUIRED`、`ROUTING_BUDGET_EXHAUSTED`、`HARD_BLOCK`。"
        if adaptive
        else "- `RUNTIME_DEPENDENCY_BLOCKED`、`VALIDATION_BLOCKED`、`REPAIR_BUDGET_EXHAUSTED`、`STATE_VERSION_CONFLICT` 无法自动调和、`HEARTBEAT_BUDGET_EXHAUSTED`、`HEARTBEAT_IDLE_BUDGET_EXHAUSTED`、`HARD_BLOCK`。"
    )
    guide_steps = (
        "9. 每次 Worker/Reviewer 只通过目标角色的 `runtime_codec STAGE_REPORT` stage 报告，再由 Gateway `ACK_ROUTE_RESULT` 或 `REPORT_RECOVERY` ACK 原 outbox；不得等待或伪造 `STATE_WRITE_APPLIED`。\n"
        f"10. 唯一业务 heartbeat 每 {heartbeat_interval} 分钟最多观察一次；同一失败最多记录两次自然 heartbeat 或累计 15 分钟，然后进入 `WAITING_TRANSPORT_RECOVERY`。未获真实 pause 后的 PAUSED readback 前不得宣称 PAUSED。\n"
        "11. Goal Queue 全部通过后做完整 FINAL_AUDIT；只经 `PREPARE_FINALIZATION -> PAUSED readback -> ACK_FINALIZATION` 到达 `FINALIZATION_ACKED`，不使用 native Goal 或 `LOOP_COMPLETE` 代称。"
        if gateway_v3
        else "9. 每次 Worker/Reviewer 回报先写状态并等待 `STATE_WRITE_APPLIED`，再进入 review、repair 或下一 Goal。\n"
        f"10. heartbeat 每 {heartbeat_interval} 分钟唤醒，最多 {max_wakeups} 次；Worker 正在运行时记录 `WAITING_ACTIVE`，不能 NOOP 关闭。只有终态或无 inflight/queue 且连续 {max_idle} 次 idle 才允许暂停。\n"
        "11. Goal Queue 全部通过后还要做一次完整 Git base-to-head 或 non_git before-to-after snapshot FINAL_AUDIT，最终状态写入成功后才是 `LOOP_COMPLETE`。"
    )
    state_observer = (
        "Gateway request_id、event_id、state_version_before/after、route ledger 与 transaction journal"
        if gateway_v3
        else "state_request_id、event_id、state_version_before/after、transaction journal"
    )
    transaction_observer = (
        f"- `{audit_paths['transactions']}`：Gateway runtime 的 PREPARED/APPLIED 恢复日志；用于判断中断后缺哪一步，不能当作第二份 canonical state。"
        if gateway_v3
        else f"- `{audit_paths['transactions']}`：State-Writer 的 PREPARED/APPLIED 恢复日志；用于判断中断后缺哪一步，不能当作第二份 canonical state。"
    )
    manual_boundary = (
        "schema v3 使用宿主协作证据：真实 App 返回或 readback 绑定当前宿主认证 turn、唯一 outbox 与 heartbeat 身份。它不声称能抵御可伪造所有 App 调用的恶意 Controller；可选 `x-codex-app-action-receipt-v1` 仅增强而非前置条件。不要以 State-Writer、手写 canonical 或 Supervisor 替代 Gateway。"
        if gateway_v3
        else "只有真实 Codex App 线程或 heartbeat 工具不可用时才使用。手动模式仍需真实项目线程、版本化单写者状态、精确 worktree 审查和相同停止条件。"
    )
    if gateway_v3:
        task_setup_steps = (
            "5. 先通过 `state_gateway INITIALIZE` 建立 schema v3 canonical state。真实 create/read 的 task/threadId、automation create/readback、send 返回 target threadId 与 PAUSED readback 是宿主协作 operation evidence；它们各自绑定当前 host-attested turn 和 Gateway 已准备的对象，不能只报 route id、标题或 transcript。\n"
            "6. Controller 以真实 App 返回注册唯一当前 Worker/heartbeat（`REGISTER_TASK` / `REGISTER_HEARTBEAT`），不创建 State-Writer 或 native Goal。当前 App 缺少可选 `x-codex-app-action-receipt-v1` 不阻断该路径；若存在则 Gateway 额外严格校验。\n"
            "7. 每条产品路线只用 `PREPARE_ROUTE -> runtime_codec MATERIALIZE_DISPATCH -> 一次 App send -> RECORD_ROUTE_SENT -> target STAGE_REPORT -> ACK_ROUTE_RESULT`。所有 lease、freshness、matrix、artifact 与 payload 由 Gateway 从 canonical state 原子生成，Controller 不复制。"
        )
        controller_check = "- 控制线程：看 Pack identity、真实 Controller/Worker identity、Gateway route ledger、原 outbox、当前 Goal、派生 metrics 和下一动作；send/automation evidence 必须绑定当前 turn 与对应 prepared 对象。"
        heartbeat_check = "- heartbeat 卡片：看真实 automation create/readback 的 automation id、ACTIVE/PAUSED、rrule、目标 Controller 任务和 transport recovery；终态必须有 pause 成功后的 PAUSED readback。"
        state_check = f"- `{audit_paths['state']}`：schema-v3 canonical roadmap、Goal/route ledger、一个路线 outbox、lease、host-cooperative heartbeat、transport recovery、预算、审批与 finalization receipt；它没有 State-Writer/Goal outbox 身份。"
        normal_signal = "正常信号：Gateway `GATEWAY_LOOP_INITIALIZED` 后，真实返回绑定的 `REGISTER_TASK` / `REGISTER_HEARTBEAT` 各登记一次；每个 Goal 只保留同一 route/outbox，报告仅由目标角色 stage 后 ACK；最终出现 `PREPARE_FINALIZATION`、已验证 heartbeat PAUSED readback 与 `FINALIZATION_ACKED`。"
        runtime_blockers = "- `RUNTIME_CODEC_TOOL_UNAVAILABLE`、`RUNTIME_DEPENDENCY_BLOCKED`、`VALIDATION_BLOCKED`、`REPAIR_BUDGET_EXHAUSTED`、`WAITING_TRANSPORT_RECOVERY`、无法调和的 `STATE_VERSION_CONFLICT`/`RECOVERY_REQUIRED`、`ROUTING_BUDGET_EXHAUSTED`、`HARD_BLOCK`。"
    pack_line = (
        f"已生成 Controller Pack：`{controller_pack_path}`。"
        if controller_pack_path
        else "Controller Pack 已输出到 stdout；建议使用 --controller-pack-output 直接生成 `.md` 文件。"
    )
    draft_warning = ""
    if errors:
        draft_warning = (
            "\n\n## 不可投递草稿\n\n"
            f"当前存在校验错误：{', '.join(errors)}。不要把这个草稿发送给控制线程；补齐后重新生成。"
        )
    return f"""## 生成文件

{pack_line}
这个 Markdown 文件是发给控制线程的唯一材料，不需要拆分复制内部段落。{draft_warning}

{runtime.runtime_forecast_block(data, workers)}

{runtime.time_estimate_block(data, workers, validation)}

{runtime.cost_usage_user_block(data, workers)}

## 你应该怎么用

{workspace_selection_line}
2. 当前 repo_mode 是 `{repo_mode}`：`existing_git` 先检查现有 git/worktree/脏文件；`new_git` 第一阶段先用 local Worker，且只有 Goal 的 `git_init/branch_create` 为 true 才初始化；`non_git` 不执行分支/worktree 检查。
3. 把资料放进工作区或提供子线程可读的绝对路径：{', '.join(source_artifacts)}。只附在控制聊天里的文件不会自动传给新线程。
{controller_launch_step}
{task_setup_steps}
8. Reviewer 不在启动时预创建；Worker 报告已写入且存在可审 diff 后再即时创建。worktree Reviewer 优先用 `fork_thread(... same-directory)`，否则传递可验证的绝对 worktree 路径和完整 diff。
{guide_steps}

## 怎么回查 loop

{controller_check}
- 实现线程：看 worktree_path、Git 或 snapshot identity、changed_files、diff_summary、diff_sha256 和带 exit_code 的验证结果。
- 审查线程：看 severity-first 的 file/line findings、reviewed artifact identity 和 test gaps。
- 状态线程：看 {state_observer}，确认没有重复事件或半事务。
{heartbeat_check}
{state_check}
- `{audit_paths['events']}`：按 event_id 记录的派发、ACK、重试、审查、停止流水。
- `{audit_paths['triage']}`：TRIAGE_ACTIONABLE/TRIAGE_NO_ACTION 发现及其证据和后续 Goal。
- `{audit_paths['reports']}`：Worker、Reviewer 和 FINAL_AUDIT 报告归档。
{transaction_observer}
- `{audit_paths['sources']}CONTROLLER_PACK.md`：初始化时归档的精确 Controller Pack；heartbeat 校验 PACK_SHA256 后用它抵抗长对话压缩。

{normal_signal}

异常信号：同一 BOOTSTRAP_MARKER 出现多个未归档任务、重复 heartbeat、未替换的 `MATERIALIZE_*` 运行时 token、重复 dispatch_id、状态版本倒退、Reviewer 看不到 worktree、Worker active 时 heartbeat 被暂停、state update 与下一 Goal 同时发送。

## 你只需要介入

- `MISSING_PROJECT_WORKSPACE`、`MISSING_SOURCE_ARTIFACT`、`THREAD_TOOLS_UNAVAILABLE`、`THREAD_BUDGET_EXHAUSTED`、`AUTOMATION_TOOLS_UNAVAILABLE`、`AUTOMATION_IDENTITY_UNRESOLVED`、`MISSING_CONNECTOR`。
- `DIRTY_WORKTREE_CONFLICT`、`WORKTREE_BOOTSTRAP_BLOCKED`、`WORKTREE_INTEGRATION_PLAN_MISSING`、`PATH_SCOPE_ESCAPE`、`THREAD_IDENTITY_UNRESOLVED`、`REVIEW_ARTIFACT_UNAVAILABLE`。
- `BLOCKED_COST_CAP`、`BLOCKED_USAGE_METADATA`、`AWAITING_HUMAN_APPROVAL`、`PHASE_PERMISSION_CONFLICT`。
{runtime_blockers}

## 手动降级

{manual_boundary}
"""
