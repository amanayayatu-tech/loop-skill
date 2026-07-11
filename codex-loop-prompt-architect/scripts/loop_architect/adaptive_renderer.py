"""Adaptive Controller Pack and user-guide rendering."""

from __future__ import annotations

import json
from typing import Any

from .forecast import dashboard_required, estimate_confidence
from .schema import (
    ADAPTIVE_OUTBOX_KINDS,
    ADAPTIVE_REVIEW_DECISIONS,
    ADAPTIVE_RUNTIME_MUTATIONS,
    ADAPTIVE_RUNTIME_SUCCESS_CODES,
    ADAPTIVE_STATE_SCHEMA_TYPES,
    ROADMAP_OPERATIONS,
)
from .validation import normalize_milestones


def adaptive_state_schema_block() -> str:
    lines = ["Adaptive required top-level keys and types:"]
    lines.extend(f"- {key}: {value}" for key, value in ADAPTIVE_STATE_SCHEMA_TYPES.items())
    lines.append("These keys extend the canonical closed schema; they are not optional unknown fields in Adaptive Mode.")
    return "\n".join(lines)


def roadmap_projection_contract(goals_path: str, dashboard_path: str, dashboard: bool) -> str:
    dashboard_line = (
        f"- Render {dashboard_path} after every material roadmap change."
        if dashboard
        else "- Dashboard generation is disabled for this pack; do not create an HTML status surface."
    )
    return f"""Roadmap Projection Contract:
- Canonical roadmap data lives only in LOOP_STATE.md. {goals_path} is a derived human-readable projection, never a second source of truth.
- GOALS.md format is deterministic: title; state_version; roadmap_version; roadmap_sha256; generated_at; Active Milestone; then one section per milestone with Status, Outcome, Scope, Decisions, Blockers, Required Evidence, Dependencies, References, and Last Change Reason.
- Every projection contains exactly one Active milestone while nonterminal and links only to acknowledged evidence/reports.
- State-Writer updates canonical state first inside the crash-recovery transaction, atomically refreshes the projection, verifies its digest, appends the event, then marks the transaction APPLIED.
- On recovery, regenerate a missing/stale projection from canonical state; never infer canonical state from edited projection prose.
{dashboard_line}
- The dashboard is one UTF-8 static HTML file with state_version and roadmap_sha256 meta values, current milestone, milestone status table, evidence links, blockers, decisions, estimates, recent events, and required user decisions.
- Escape every repository/report string as untrusted text. Use no scripts, forms, external assets, network requests, mutation controls, deploy step, or inline secrets. Embed canonical state/roadmap versions and digests so recovery can detect and atomically rewrite a missing or mismatched copy.
- The dashboard is derived from canonical state and the GOALS projection. It cannot accept edits, approvals, or status mutations."""


def reviewer_adaptive_protocol() -> str:
    return """Adaptive Assurance Protocol:
- Reuse this same real read-only Reviewer task for separate CODE_REVIEW, ROADMAP_AUDIT, and final FINAL_AUDIT dispatches. Never infer one decision from another report.
- Before every review send, persist an assurance_dispatch_outbox PREPARED record binding review kind, review dispatch id, current Worker dispatch/report, latest artifact digest, target Reviewer threadId, payload digest, roadmap version, and full lease claim; wait for the PREPARE mutation response, send once, then persist SENT. ACK_OUTBOX attaches the canonical JSON report and a result containing exactly the report decision/status, archived report digest, and source artifact digest; runtime parses and identity-binds it before advancing SENT to ACKED. Only the later RECORD_REVIEW transaction advances ACKED to COMPLETED. A report cannot skip either transition.
- The send ACK must carry the exact lease_claim stored on that PREPARED record. A later lease cannot send it until an explicit same-owner renewal or evidence-backed takeover CAS rebinds the record and consumes the recovered route action.
- Every /review is a closed tagged union with common fields: review_kind, typed decision, milestone_id, roadmap_version, review_dispatch_id, full controller lease_claim, source Worker dispatch id, source Worker report digest, source Worker threadId, source artifact digest, target Reviewer threadId, payload digest, and evidence refs. The strict Reviewer report repeats those source identities at top level; nested copies do not count.
- CODE_REVIEW is rejected unless the source Worker dispatch is the Goal ledger's latest durably COMPLETED/PASS dispatch and its report digest, artifact digest, Goal id, milestone id, and roadmap version all match. A repaired Goal permanently invalidates assurance over every older artifact. It also requires exact worktree/snapshot identity, changed_files, diff_sha256, complete diff/patch reference, and validation results. A read-only/no-diff milestone still sends CODE_REVIEW with artifact_kind=NO_DIFF and the exact source report digest; it does not skip the assurance sequence.
- CODE_REVIEW may return REVIEW_PASS, REVIEW_PASS_WITH_LIMITATION, REVIEW_NEEDS_REPAIR, or REVIEW_ARTIFACT_UNAVAILABLE. All four are ACKable typed decisions. REVIEW_PASS_WITH_LIMITATION is a pass only when every limitation is explicit, evidence-bounded, and contains no unresolved required fix; preserve it through later assurance and final claim boundaries. REVIEW_ARTIFACT_UNAVAILABLE closes the outbox as a non-PASS blocker, never as review success. Its report repeats review_kind=CODE_REVIEW, milestone_id, roadmap_version, review_dispatch_id, source Worker dispatch/report, source artifact digest, findings, and decision.
- Required order is CODE_REVIEW report ACK, then every required Local Verification PASS ACK for that exact artifact, then ROADMAP_AUDIT. ROADMAP_AUDIT requires the acknowledged CODE_REVIEW report digest, the same source artifact digest, current Local Verification ACK identity when required, canonical roadmap/Goal Queue versions, authorization envelope, original objective, and current estimates.
- ROADMAP_AUDIT returns ROADMAP_AUDIT_PASS only for an in-envelope typed transition proposal, ROADMAP_CHANGE_PROPOSED only for an out-of-envelope proposal that requires approval, or ROADMAP_AUDIT_PASS_FINAL_CANDIDATE when no future execution milestone remains. Each non-final report contains one closed `roadmap_proposal`, its canonical digest, proposal/audit ids, base roadmap version, typed operations, component digests for milestones/queue/definitions/authorization/estimate, next Goal, reason, and `within_authorized_envelope`. ROADMAP_AUDIT_PASS requires true; ROADMAP_CHANGE_PROPOSED requires false and cannot enter ROADMAP_REVISION.
- FINAL_AUDIT is a third tagged dispatch only for the final candidate. It binds the acknowledged CODE_REVIEW and ROADMAP_AUDIT report digests, required Local Verification ACK identity, exact full Git base-to-head or non_git baseline-to-current artifact, all Goal reports, validation evidence, forbidden-artifact scan, state/event consistency, evidence layer, claim boundary, and approval ledger. It returns FINAL_REVIEW_PASS, FINAL_REVIEW_PASS_WITH_LIMITATION, or a repair/blocker decision with the same identities.
- State-Writer ACK keys are (review_kind, milestone_id, roadmap_version, review_dispatch_id, source artifact digest). An ACK from another milestone, revision, dispatch, or artifact is stale and cannot route.
- Never write product files, state, GOALS.md, or dashboard. Never treat Worker prose as completion evidence.
- Any proposal that expands objective, write scope, side-effect permissions, budget, connectors, claim boundary, production access, or secrets must set within_authorized_envelope=false and route to ROADMAP_CHANGE_REQUIRES_APPROVAL."""


def state_writer_adaptive_protocol(
    repo_root: str,
    goals_path: str,
    dashboard_path: str,
    dashboard: bool,
) -> str:
    repo_root_json = json.dumps(repo_root, ensure_ascii=False)
    return f"""Adaptive State-Writer Protocol:
- Deterministic runtime gate: accept only a `STATE_MUTATION` line followed by one strict JSON request matching `references/adaptive-mutation.schema.json`. Do not accept a legacy slash-form state command.
- Resolve the runtime path from `CODEX_HOME` (falling back to `~/.codex`) and invoke it as an argv array, never through interpolated shell text: `["python3", RUNTIME_PATH, "--root", {repo_root_json}]`. Provide the exact request JSON on stdin. Never interpolate request fields, repository paths, or artifact names into shell syntax.
- The runtime is the only writer for canonical Adaptive state, events, transaction journals, `GOALS.md`, immutable Controller Pack/report artifacts, leases, outboxes, roadmap revisions, and finalization. Do not manually create, patch, append, or rewrite those files, even when the requested change appears simple.
- Return the runtime's single structured JSON object unchanged as the state result. Exit status 1 with a structured rejection is a normal rejected mutation, not permission to retry with hand-written files. `DEPENDENCY_MISSING`, `SCHEMA_UNAVAILABLE`, `SCHEMA_INVALID`, or an unavailable runtime returns `STATE_RUNTIME_UNAVAILABLE` to Controller and performs no fallback write.
- Ordinary mutation application is read-only with respect to an earlier incomplete transaction and returns `RECOVERY_REQUIRED`; it never auto-recovers that transaction. Before a recovered Controller submits another mutation after interruption, invoke the same CLI as `['python3', RUNTIME_PATH, '--root', {repo_root_json}, '--recover']`, relay its structured result, then reread canonical state. Never infer recovery from prose.
- The runtime performs no Codex App action. Controller alone reconciles and invokes task, Goal, automation, or message tools after a matching PREPARED result; later external observations return through a new typed mutation.
- External-action identities are closed. THREAD binds project_id, task_kind=PROJECT_TASK, the exact generated `bootstrap_role_kind`, its deterministic `formal_role_kind`, bootstrap_prompt_digest, and environment_kind; its ACK repeats those fields plus thread_id/worktree_path. Runtime enforces the lifetime child-task budget, one registered task per formal/bootstrap role key, the canonical project id, and worktree confinement to the repo or an explicit `control_plane_limits.allowed_external_worktree_roots` entry. The only child-role mapping is implementation|triage|explorer -> WORKER, code_reviewer -> REVIEWER, and local_verifier -> LOCAL_VERIFIER; display titles and keyword guesses never participate. AUTOMATION binds name, kind=HEARTBEAT, real Controller target_thread_id, rrule, exact prompt_digest, and prompt_normalization=LF_NORMALIZED_NO_TRAILING_NEWLINE; only one non-cancelled business heartbeat may exist. GOAL binds action, loop/Pack/milestone/objective digests and exact marker; UPDATE also binds goal_id and target_status. DELEGATION binds exploration/attempt ids, prompt/scope digests, source Goal/roadmap version, and max_depth=1. Native THREAD/AUTOMATION/GOAL ACKs require one immutable strict JSON Codex tool-result observation binding outbox kind/id, payload, target, and exact result; emulated Goal ACKs require the equivalent GOAL_TOOL_UNAVAILABLE observation. Reject extra, missing, or changed result fields before canonical mutation.
- Own canonical Adaptive keys, the roadmap change outbox, artifact ledger, {goals_path}, and the optional derived dashboard under .codex-loop/**.
- The pre-state creation/recovery of this one State-Writer task is the only external-action exception before canonical state. `INITIALIZE` is the only state-creation mutation and returns `LOOP_INITIALIZED`; it embeds real Controller/State-Writer ids, canonical authorization, milestones, complete immutable Goal definitions, the closed Goal Queue, and the exact Pack artifact bundle. The runtime computes and writes the initial `GOALS.md` projection.
- `ACQUIRE_LEASE` atomically creates the never-reused routing turn and increments the one shared Goal/heartbeat routing budget. No separate wake-start mutation exists. Every later mutation and outbox carries the exact lease_claim whose owner_identity is the registered real Controller threadId, never source_thread_id, a title, LOOP_ID, parent id, or fallback.
- One lease reserves exactly one route action. A control/dispatch/local outbox terminal ACK consumes it; an assurance claim is consumed by `RECORD_REVIEW`; `ROADMAP_REVISION`, `FINALIZE_LOOP`, and `STOP_LOOP` consume their own claims. `RELEASE_LEASE` consumes an observation-only claim for `WAITING_ACTIVE`, `WAITING_QUOTA_RECOVERY`, or another explicit no-action reason and rejects any reserved route or active outbox.
- Optional request artifacts are closed to the Controller Pack snapshot and safe report filenames. Validate exact UTF-8 digest and media type, enforce immutability, journal their bytes, and record them in artifact_ledger. Missing or conflicting artifact bytes are a rejection, never permission for a manual write.
- Every formal DISPATCH, ASSURANCE, or LOCAL ACK_OUTBOX result contains status, archived report_digest, and artifact_digest and binds exactly one archived `application/json` report artifact named in its evidence paths; DELEGATION keeps its own typed result contract. Runtime parses formal reports before ACK and binds top-level dispatch, Goal, milestone, roadmap, target task, payload, artifact, decision, and source identities to the current SENT outbox. Every RECORD_REVIEW revalidates the same report and requires its decision/report/artifact tuple to equal the prior ACK result; completed assurance outboxes and the assurance ledger are a one-to-one invariant. `REPORT_ARTIFACT_UNBOUND`, malformed JSON, a missing top-level identity, or a mismatch is a pure rejection that leaves the outbox SENT. Upgrade compatibility is limited to an already-ACKED legacy assurance whose result is exactly null/empty: RECORD_REVIEW derives the three fields from its own typed mutation, validates the same report, and atomically stores them; a nonempty invalid result is never repaired. Formal roles return `PENDING_CONTROLLER_ARCHIVE`; Controller alone canonicalizes and hashes the strict JSON before the State-Writer call.
- Validate event/request ids and all mutation inputs before changing canonical state. A replayed event_id must match its original immutable domain identity and return without changing state, counters, ledgers, or budget; a different payload/turn under that id is a conflict. Apply every mutation transactionally; any rejection restores the complete prior state, outboxes, counters, and lease. A failed request can never consume a lease or leave a partial terminal status.
- Only an acknowledged ROADMAP_AUDIT_PASS is input to ROADMAP_REVISION. The mutation carries the exact audited proposal/report digests; runtime recomputes every proposed component digest, verifies typed operations equal the actual milestone diff, independently enforces the immutable authorization envelope, and rejects a swapped or Controller-invented proposal. ROADMAP_CHANGE_PROPOSED routes only to ROADMAP_CHANGE_REQUIRES_APPROVAL.
- Before ROADMAP_REVISION, cancel each obsolete PREPARED Worker/assurance/Local outbox through its own `CANCEL_OUTBOX` transaction and ACK, then acquire a fresh lease. ROADMAP_REVISION rejects every remaining PREPARED, SENT, ACKED-assurance, or in-progress versioned outbox; it never silently cancels work inside the revision CAS. The revision atomically updates milestones, the complete future Goal Queue, immutable Goal definitions/execution ledger, roadmap version, projection metadata, and estimate history.
- A milestone may contain multiple dependency-ordered Goals. Completing one Goal while the milestone remains ACTIVE retires only that evidenced Goal and may unlock its READY sibling; reject unexecuted siblings only when a revision attempts to mark their milestone COMPLETE.
- The future Goal Queue schema is closed to goal_id, milestone_id, roadmap_version, status=READY|PLANNED, and depends_on. On initialization it contains every non-retired Goal definition for every ACTIVE/PLANNED milestone exactly once. Every entry resolves to a complete immutable Goal definition containing display worker role, exact worker_role_kind, objective, success criteria, validation, safe in-repo scope with no `..` or `.codex-loop`, phase permissions, dependencies, dispatch condition, and full payload-template digest. Reject missing/mutated definitions, unknown/retired/rebound ids, unknown dependencies, cycles, non-routable milestone references, or a nonterminal revision without at least one dependency-satisfied READY Goal for its single ACTIVE milestone.
- Preserve exactly one ACTIVE milestone. Reject a transition that creates zero or multiple active milestones while nonterminal. A normal RoadmapRevision is never a terminal transition.
- FINALIZE_LOOP is a separate CAS transaction. Accept it only after a completed Worker PASS dispatch plus exact CODE_REVIEW, required Local Verification, ROADMAP_AUDIT_PASS_FINAL_CANDIDATE, and FINAL_AUDIT report ACKs for the final artifact, with no PREPARED/SENT/IN_PROGRESS Worker, assurance, or Local Verifier outbox. Reconcile the complete Goal definition registry and execution ledger, not only the current queue; reject every non-retired, non-superseded Goal that was never executed and assured. Never mark the remaining queue complete in bulk. Then complete only the evidenced final Goal/milestone, empty/retire the already-resolved queue, refresh projections, set terminal status, and create one PREPARED finalization_outbox binding finalization_id, controller_goal_id, automation_id, and finalized_state_version.
- After FINALIZE_LOOP ACK, Controller completes the exact native Goal and pauses the exact registered heartbeat in the same Controller turn. It archives two distinct `application/json` UTF-8 observations whose parsed objects are exactly `{{"goal_id": <canonical goal id>, "status": "COMPLETE"}}` and `{{"automation_id": <canonical automation id>, "status": "PAUSED"}}`, then sends ACK_FINALIZATION with their separate paths and SHA-256 digests. Runtime accepts no other post-terminal mutation. Loop closeout is not complete until FINALIZATION_ACKED and finalization_receipt are canonical.
- STOP_LOOP is the only hard-block terminal mutation. It requires one immutable strict JSON blocker report plus exactly three distinct artifact-bound observations for the last three genuine consecutive completed Goal turns, all with the same blocker code, fingerprint, and Controller Goal identity. All three turns must have `route_action=null`, `release_reason_code=HARD_BLOCK_OBSERVATION_ONLY`, and an observation artifact archived at that release's exact state version. STOP_LOOP runs on the next dedicated Goal turn; it never counts its own route as an observation. The runtime rejects fewer, late-backfilled, repeated, nonconsecutive, action-bearing, or fabricated turns with zero side effects. It also requires no active outbox and the exact Controller Goal/business-heartbeat identities. Do not manufacture wakeups. STOP_LOOP sets LOOP_BLOCKED and prepares BLOCKED closeout; Controller then marks the exact Goal BLOCKED and pauses that exact heartbeat, and ACK_FINALIZATION binds distinct Goal=BLOCKED and automation=PAUSED observations.
- ROADMAP_CHANGE_REQUIRES_APPROVAL is a blocker record, never an applied mutation.
- controller_lease acquisition/release is CAS-protected and idempotent. Missing, consumed, or mismatched claims are rejected as `STALE_OR_MISSING_CONTROLLER_LEASE`; failed claim/time probes are pure rejections and cannot advance logical time. A competing owner receives WAITING_CONTROLLER_LEASE. Expired takeover requires trustworthy current time plus structured read_thread evidence containing the exact owner task, last activity time, read digest, and STALE decision; only then may CAS replace the full claim and increment the epoch. A fresh route uses a fresh lease rather than bundling multiple startup or recovery actions.
- A still-active exact same owner may proactively renew or recover an expired claim with one bound `application/json` observation whose parsed object exactly matches the ACTIVE_SAME_OWNER evidence fields, the same routing_turn_id, and a new lease_id/epoch. Takeover likewise requires one exact bound JSON STALE observation. Renewal may cross the one exact matching PREPARED/SENT/ACKED external record: it atomically rotates only the canonical outbox lease claim, while the immutable payload digest continues to bind the original embedded dispatch claim; payload/dispatch/report identity and status do not change and the action is never resent. Reject a mismatched owner, changed route identity, unrelated active record, or ambiguous multi-route recovery; never fabricate STALE evidence.
- A ROADMAP_AUDIT report ACK is the durable structured proposal. Controller validates that acknowledged proposal, acquires a dedicated fresh lease, and submits one ROADMAP_REVISION CAS. If that lease expires before the CAS, renew/take over only the lease and reuse the same acknowledged audit identity.
- Dispatch recovery matches dispatch_id, payload_digest, target_thread_id, immutable Goal definition digest, exact `worker_role_kind`, and the stored lease route. The target task's registered `bootstrap_role_kind` must equal the Goal definition and payload role kind; sharing formal WORKER does not authorize implementation/triage/explorer substitution. Permit only one PREPARED/SENT/IN_PROGRESS Worker dispatch across roadmap revisions. A selected Goal must itself be READY with completed dependencies. Worker PASS closes eligibility for redispatch. An acknowledged Worker FAIL plus CODE_REVIEW, Local Verification, ROADMAP_AUDIT, and FINAL_AUDIT repair decisions form one closed failure-source union and consume the same per-Goal repair budget.
- Native Goal creation/transition uses the generic controller_goal_outbox lifecycle. Native CREATE/UPDATE is `PREPARED -> external tool call once -> SENT -> ACKED`; UPDATE binds the source Goal and target complete/blocked status. Persist before get/create/update, reconcile the actual Goal after a crash, and ACK before replacing the mapping or pausing heartbeat. Every returned Goal status, including complete, must first pass exact loop/pack/milestone/objective marker validation plus canonical/outbox identity.
- If Goal tools are unavailable, attach one immutable `application/json` unavailability/transition observation and ACK the exact PREPARED GOAL outbox directly as `EMULATED_SINGLE_ACTIVE_MILESTONE` (or its later target status). Do not mark it SENT and do not claim a native call occurred.
- Every optional sidecar uses a generic DELEGATION outbox before spawn: `PREPARED -> spawn once -> SENT -> ACKED`. ACK requires one immutable `application/json` result artifact whose digest is the canonical report_digest. Only a COMPLETED, archived, ACKED result may influence routing; interrupted/dropped attempts are terminal evidence only. agent_id never enters thread_registry.

{roadmap_projection_contract(goals_path, dashboard_path, dashboard)}"""


def local_verifier_protocol() -> str:
    return """Local Verifier Protocol:
- This is a real Codex App project task created just in time, never an internal subagent and never a code-writing Worker.
- Verify the exact branch/commit/worktree/snapshot identity supplied in the dispatch using the declared local browser, account, permission, simulator, device, or hardware surface.
- Accept a dispatch only after the exact source artifact has an acknowledged CODE_REVIEW. Every dispatch/report carries milestone_id, roadmap_version, Goal ID, verification_id, source artifact digest, local dispatch_id, real target threadId, payload digest, and full current lease_claim. Return PASS, FAIL, or BLOCKED with those identities plus exact steps, expected/actual result, screenshot/log/console refs, reproduction steps, blocker, and next action.
- Before send, State-Writer must return an applied PREPARED result for the exact local_verification_outbox; after the one external send, MARK_OUTBOX_SENT makes it SENT. No PASS/FAIL/BLOCKED report may be accepted without that matching SENT record, and ACK_OUTBOX with the bound report closes it as COMPLETED.
- Do not expose credentials, cookies, tokens, personal data, or sensitive screenshots to remote Workers or reports.
- FAIL returns the same verification_id to the implementation Worker for repair and requires a retest of that exact item. If repair changes the artifact digest, the repaired artifact needs a new CODE_REVIEW ACK before retest. Worker prose cannot replace either gate.
- BLOCKED becomes LOCAL_VERIFICATION_BLOCKED or LOCAL_VERIFICATION_PENDING according to the declared policy; never claim verification passed."""


def adaptive_controller_protocol(data: dict[str, Any], audit_paths: dict[str, str]) -> str:
    milestones = normalize_milestones(data.get("milestones"))
    active = next((item for item in milestones if item["status"] == "ACTIVE"), None)
    dashboard = dashboard_required(data, len(milestones))
    goals_path = f"{audit_paths['root']}GOALS.md"
    dashboard_path = f"{audit_paths['root']}progress-dashboard.html"
    delegation = data.get("delegation_policy", "disabled")
    max_subagents = data.get("max_read_only_subagents", 0)
    max_subagent_runs = data.get("max_read_only_subagent_runs", 0)
    subagent_retry_limit = data.get("subagent_retry_limit", 0)
    subagent_input_policy = data.get("subagent_input_policy")
    controller_goal_budget = data.get("controller_goal_token_budget")
    controller_goal_budget_text = (
        str(controller_goal_budget)
        if isinstance(controller_goal_budget, int) and not isinstance(controller_goal_budget, bool)
        else "OMIT_TOKEN_BUDGET_ARGUMENT"
    )
    active_id = active["milestone_id"] if active else "INVALID_NO_SINGLE_ACTIVE_MILESTONE"
    active_outcome = active["outcome"] if active else "INVALID"
    milestone_lines = "\n".join(
        f"- {item['milestone_id']}: {item['status']} | {item['outcome']}"
        for item in milestones
    )
    milestone_registry_json = json.dumps(
        milestones,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if delegation == "disabled":
        delegation_block = """Read-Only Subagent Delegation:
- policy: disabled; no internal subagent is authorized by this pack.
- Continue through real project tasks. Do not infer delegation permission from Adaptive mode itself."""
    else:
        delegation_block = f"""Read-Only Subagent Delegation:
- policy: {delegation}; authorization_concurrency_ceiling: {max_subagents}; max_lifetime_runs: {max_subagent_runs}; retry_limit_per_exploration: {subagent_retry_limit}; max_depth: 1.
- input policy: {subagent_input_policy}
- These nonzero limits were explicitly supplied in the validated Adaptive input. Sending this pack authorizes only those bounded one-shot read-only sidecars for code search, log grouping, test-failure triage, or summarization when materially useful.
- Inspect the actually exposed collaboration/subagent tool name and schema before calling it; do not assume a fixed tool name or parameter set. Use only declared fields. If the current schema exposes agent_type/fork_context, use agent_type=\"explorer\", fork_context=false, and no model override; otherwise express the same one-shot read-only semantics with that build's actual fields. The bounded request contains exploration_id, read-only scope, evidence boundary, allowed input paths, and required concise result. Never request nested delegation.
- Subagents never replace Controller, implementation Worker, Reviewer, State-Writer, or Local Verifier; never write files; never approve, dispatch, mutate state/roadmap, call paid/external services, or create nested agents.
- Give every delegation a stable exploration_id and attempt_id. The concurrency field is an authorization ceiling, not a promise of simultaneous execution: the deterministic router serializes one active DELEGATION outbox per lease. Before spawning, acquire a fresh route lease and PREPARE_OUTBOX(kind=DELEGATION) with prompt/scope digests, source Goal/roadmap version, max_depth=1, and the configured budget. Spawn exactly once, MARK_OUTBOX_SENT with the returned ephemeral agent identity evidence, then ACK_OUTBOX only while attaching the canonical immutable `application/json` result artifact. Every attempt and retry consumes the lifetime run budget. Only status=COMPLETED plus archived report_digest plus runtime ACK may affect evidence or routing; interrupted/dropped attempts remain non-authoritative terminal evidence. agent_id never enters thread_registry.
- If subagent tools are absent or a sidecar fails, record optional SUBAGENT_TOOLS_UNAVAILABLE/SUBAGENT_RESULT_DROPPED evidence and continue through the Controller or real Reviewer; never block the formal loop solely for an optional sidecar."""

    return f"""Adaptive Coordination Mode:
- coordination_mode: adaptive
- adaptive_reason: {data.get('adaptive_reason')}
- initial_active_milestone_id: {active_id}
- initial_active_outcome: {active_outcome}
- Goal Queue is an atomic execution queue, not an immutable project roadmap.
- Queued task compatibility: a create/fork result may expose pendingWorktreeId or clientThreadId depending on the App build. Both are temporary creation identities only; keep the generic THREAD outbox PREPARED and reconcile either one to a real threadId before MARK_OUTBOX_SENT, ACK_OUTBOX, or dispatch.

Initial Milestones:
{milestone_lines}

Canonical Initial Milestone Registry (INITIALIZE must use this exact parsed array, not the summary above):
MILESTONE_REGISTRY_JSON_BEGIN
{milestone_registry_json}
MILESTONE_REGISTRY_JSON_END

Single Active Milestone And Native Goal:
- Canonical state must contain exactly one ACTIVE milestone until terminal completion.
- The user's act of sending this Adaptive pack explicitly requests use of create_goal/get_goal/update_goal for the Controller's current milestone when those tools are exposed.
- Acquire the fenced controller lease before get_goal/create_goal/update_goal. Goal tool calls are routing actions and may not happen outside the lease.
- Build the native objective with the stable final-line marker `[CODEX_LOOP_MILESTONE loop_id=<LOOP_ID> pack_sha256=<FULL_64_HEX_SHA256> milestone_id=<ID> objective_sha256=<FULL_64_HEX_SHA256>]`; the marker must be the final line, with no trailing prose. Canonical controller_goal and controller_goal_outbox store the same loop, pack, milestone, objective, digest, and marker identities. Persist PREPARE_OUTBOX(kind=GOAL, action=CREATE) before get_goal/create_goal. Recover an existing active or blocked goal only when the returned objective ends with that exact marker and either canonical mapping or the matching PREPARED/SENT/ACKED GOAL outbox exists. A marker alone is untrusted and a cross-loop/pack collision is CONTROLLER_GOAL_CONFLICT. A matching blocked Goal is recovered for blocker handling, never treated as permission to create a second Goal. Do not expect Goal tools to return custom fields.
- Use get_goal({{}}), create_goal(objective=CONTROLLER_MILESTONE_OBJECTIVE, token_budget={controller_goal_budget_text} only when this is an integer), and update_goal(status="complete" or status="blocked") exactly as exposed. When the value is OMIT_TOKEN_BUDGET_ARGUMENT, omit the argument entirely. Do not invent goal ids or pause/resume arguments.
- Create the Controller goal from the active milestone outcome, constraints, required evidence, and completion criteria. Pass token_budget only when `controller_goal_token_budget` was explicitly supplied; the global metered-runtime `token_cap` is ledger-wide and must never be copied into each milestone Goal.
- Goal tools may create/read and mark a goal complete or genuinely blocked. Do not claim they can programmatically pause, resume, edit, or clear the UI Goal row. Use blocked only after STOP_LOOP validates three artifact-bound consecutive Goal-turn observations for the same blocker fingerprint; transient waits stay nonterminal in canonical state.
- Native Goal calls use the generic GOAL outbox lifecycle `PREPARED -> call once -> SENT -> ACKED`. When native tools are unavailable, attach a strict JSON unavailability observation and direct-ACK the exact PREPARED GOAL outbox as EMULATED_SINGLE_ACTIVE_MILESTONE without marking SENT or claiming a native call.
- Complete the current native or emulated goal only after an applied cross-milestone ROADMAP_REVISION proves every Goal in its old milestone COMPLETE/RETIRED, or after FINALIZE_LOOP/STOP_LOOP prepares the exact closeout target. Runtime rejects a same-milestone or otherwise early GOAL UPDATE. Prepare a source-bound GOAL UPDATE outbox, call update_goal once and use SENT -> ACKED when native, or direct-ACK PREPARED with an emulated tool observation when emulated.
- Runtime rejects Worker DISPATCH unless canonical `controller_goal` is ACTIVE or EMULATED and names that exact Active milestone. When a nonterminal ROADMAP_REVISION changes the Active milestone it returns `COMPLETE_CURRENT_CONTROLLER_GOAL`; complete the old Goal, ACK its transition, create/ACK the new Active-milestone Goal, and only then dispatch the next Worker. A same-milestone sibling keeps the existing Controller Goal and returns `PREPARE_NEXT_GOAL_OUTBOX`. FINALIZE_LOOP enforces the same final-milestone Goal binding.

Canonical Dispatch Payload Identity:
- Every Worker, Reviewer, and Local Verifier dispatch is one closed JSON payload containing `dispatch_payload_digest` and the full lease claim including `routing_turn_id`. Freeze the bounded state snapshot and materialize every other runtime field before computing it.
- Construct exactly `{{"envelope_type": "WORKER_DISPATCH|REVIEW_DISPATCH|LOCAL_VERIFY_DISPATCH", "payload": {{...}}}}`; the payload digest value must be the literal `PAYLOAD_DIGEST_PLACEHOLDER`. Pass that strict JSON on stdin to `["python3", RUNTIME_PATH, "--payload-materialize"]`. Only `PAYLOAD_MATERIALIZED` is sendable. Persist its returned digest in PREPARE_OUTBOX, then send its returned `transport_text` unchanged as the exact task-message body. Never manually replace text, retain a `sha256:` prefix, add angle brackets, normalize whitespace, reserialize the returned body, or hash a UI/XML wrapper.
- A receiver passes the exact received `codexDelegation.input` body unchanged to `["python3", RUNTIME_PATH, "--root", CANONICAL_REPO_ROOT, "--payload-verify"]` and acts only on `PAYLOAD_VERIFIED`. `PAYLOAD_BYTES_VERIFIED` is an internal byte check and is not execution permission. The verification scope is that body, not the visible `<codex_delegation>` wrapper or rendered conversation text. Missing, duplicated, malformed, noncanonical, or canonical-state/SENT-outbox-mismatched digest/lease/target/dispatch/Goal-definition identity is a typed rejection, never permission to execute or review.
- The bounded state snapshot is intentionally frozen immediately before PREPARE_OUTBOX. PREPARE and MARK_OUTBOX_SENT then advance canonical state, so the receiver must not require snapshot.state_version to equal the latest state_version. It verifies that the matching outbox has `prepared_state_version == snapshot.state_version + 1`, is now SENT, and still has the same roadmap, Goal, lease, target, payload, and definition/artifact identities. A later unrelated version increase is acceptable only while those identities remain unchanged.

Controller Lease:
- Goal-mode turns and heartbeat wakes both acquire controller_lease by State-Writer CAS before any routing decision.
- Every Goal-mode continuation and every heartbeat wake increments the same canonical routing-turn counter and consumes the same `max_wakeups` budget before lease acquisition. Native Goal turns cannot bypass heartbeat limits. When the combined budget is exhausted, record ROUTING_BUDGET_EXHAUSTED and stop external routing; never silently keep Goal Mode spinning.
- Lease identity contains monotonically increasing lease_epoch, a never-reused lease_id, owner_kind (GOAL_TURN or HEARTBEAT), owner_turn/task identity, acquired_at, expires_at, and intended_transition=ROUTE_ONE_TRANSITION. The mutation claim is the exact tuple (lease_epoch, lease_id, owner_kind, owner identity, intended_transition); reusing only an epoch or lease id is invalid.
- Every state request and every external action/outbox carries that full lease_claim plus trustworthy observed_at. State-Writer rejects missing, expired, consumed, released, superseded, wrong-purpose, or mismatched claims. A competing owner returns WAITING_CONTROLLER_LEASE and sends no state, task, review, Goal, or automation message. Expired takeover requires observed_at from a trustworthy clock plus structured exact-owner read_thread evidence. One lease reserves exactly one route action: one native Goal action, one external outbox, one ROADMAP_REVISION, FINALIZE_LOOP, or STOP_LOOP. Its terminal ACK/CAS consumes the lease; a later action always acquires a fresh counted lease.
- If this same active Controller task approaches or crosses expiry before send or while the one reserved external action is PREPARED/SENT/ACKED, use SAME_OWNER_LEASE_RENEWED with current-task ACTIVE_SAME_OWNER evidence, the same routing_turn_id, and a new lease id/epoch. Do not label the live owner STALE. Rebind only the exact matching unfinished record, preserve its immutable identity/status, do not resend it, and ACK a completed target with the renewed claim. While the target remains active, renew before TTL exhaustion and keep WAITING_ACTIVE nonterminal.
- Release the lease only after an observation-only turn or after its chosen route is durably complete. Reject release while a matching Worker/review/local/delegation or Goal PREPARED/SENT/ACKED record still depends on the claim.

Roadmap Audit Transaction:
- Required sequence per milestone: Worker report ACK -> CODE_REVIEW dispatch/report ACK -> required Local Verifier dispatch/report ACK -> ROADMAP_AUDIT dispatch/report ACK -> Controller envelope validation -> one dedicated ROADMAP_REVISION CAS (or approval blocker) -> GOALS/dashboard projection ACK -> Controller Goal transition -> next Worker dispatch.
- Reviewer is reused for ROADMAP_AUDIT and final FINAL_AUDIT; do not create a permanent Auditor task.
- ROADMAP_CHANGE_PROPOSED and non-final ROADMAP_AUDIT_PASS must contain one canonical `roadmap_proposal` and digest, proposal/audit identity, source Worker/code/local identities, base roadmap version, typed operations, complete future queue/definitions, reasons, evidence and estimate revision. The proposal carries component digests for milestones, queue, definitions, authorization and estimate. ROADMAP_AUDIT_PASS asserts `within_authorized_envelope=true`; ROADMAP_CHANGE_PROPOSED asserts false and stops for approval.
- State-Writer computes the result against immutable canonical authorization_envelope. It independently checks every proposed milestone scope, Goal write scope, phase permission, budget cap, connector, side effect, evidence policy, claim boundary, production flag, and secrets flag. Caller booleans are assertions only; disagreement is rejected rather than trusted.
- The only operation enum is: {', '.join(sorted(ROADMAP_OPERATIONS))}. Lowercase aliases are invalid. Operations may not rewrite completed/active dispatch history, reuse a retired goal_id/milestone_id, or delete evidence.
- Every future Goal Queue entry has exactly goal_id, milestone_id, roadmap_version, status=READY|PLANNED, and depends_on, and resolves through goal_definition_registry to a complete executable immutable payload template/digest. Initial state includes every routable definition exactly once. State-Writer rejects unknown dependencies, cycles, missing/mutated definitions, unsafe/traversing scopes, unstable id rebinding, or an Active milestone with no dependency-satisfied READY Goal.
- Controller must cancel obsolete PREPARED Worker/review/local outboxes with separate CANCEL_OUTBOX ACKs before the revision. State-Writer refuses ROADMAP_REVISION while any versioned outbox remains active, then applies the exact audited proposal, milestones, future Goal Queue, definitions/execution ledger, roadmap version, projection digest and estimate in one CAS. Every future Goal carries milestone_id and the new roadmap_version.
- If the current milestone remains ACTIVE, the revision may complete the evidenced Goal and unlock a dependency-ready sibling Goal in that same milestone. Unexecuted siblings block only an attempted milestone COMPLETE transition.
- Any expansion persists ROADMAP_CHANGE_REQUIRES_APPROVAL and pauses routing after blocker ACK. It never mutates the roadmap or inherits approval from unrelated phases. An approved proposal applies once under roadmap_version CAS and gives every newly materialized future Goal a never-reused stable goal_id.

Finalization:
- When ROADMAP_AUDIT returns ROADMAP_AUDIT_PASS_FINAL_CANDIDATE, dispatch tagged FINAL_AUDIT to the same Reviewer over the exact integrated artifact. Do not complete the milestone, native Goal, state, or heartbeat first.
- After FINAL_AUDIT report ACK, State-Writer applies one separate FINALIZE_LOOP CAS transaction that verifies every required Goal actually executed, completes only the final evidenced Goal/milestone, retires/empties the resolved Goal Queue, increments roadmap/projection versions, sets the evidence-bounded terminal status, and prepares the final external-action receipt identity.
- Only after FINALIZE_LOOP ACK may Controller call update_goal(status="complete") and pause the registered heartbeat. It must then submit ACK_FINALIZATION with the actual Goal id/status and automation id/status, and wait for FINALIZATION_ACKED before reporting completion. FINAL_AUDIT failure returns repair/blocker routing and cannot be converted to a RoadmapRevision terminal shortcut.
- A real unrecoverable blocker is first observed nonterminally on three natural Goal turns. Each observation-only RELEASE_LEASE has `route_action=null`, `release_reason_code=HARD_BLOCK_OBSERVATION_ONLY`, and archives its artifact at that release's exact state version. Only on the next dedicated Goal turn may Controller submit the separate `STOP_LOOP` CAS with those three already archived immutable observations and one aggregate strict JSON blocker report. `STOP_LOOP_APPLIED` sets `LOOP_BLOCKED` and prepares the exact Goal/heartbeat closeout; it is not FINALIZE_LOOP and never claims PASS. In that dedicated STOP turn, call `update_goal(status="blocked")`, pause the registered business heartbeat, and submit ACK_FINALIZATION with two distinct JSON observations. Never manufacture wakeups, attach or backfill an observation in STOP_LOOP, submit STOP_LOOP early, return from an applied hard blocker with the heartbeat ACTIVE, or defer its pause to a future heartbeat wake.

Local Verification:
- policy: {data.get('local_verification_policy')}
- Create a real Local Verifier task only when a milestone requires an authenticated browser, local credentials, macOS permission, extension, Xcode/simulator, physical device, hardware, or other evidence unavailable to the Worker/Reviewer checkout.
- For a worktree artifact, prefer a just-in-time same-directory fork of the Worker after its report ACK; otherwise prove access to the exact absolute worktree/snapshot. For machine/account UI state that is independent of checkout, use a local task in the same Codex Project and still pass exact artifact identity.
- WORKER_FAIL, REVIEW_NEEDS_REPAIR, LOCAL_VERIFICATION_FAIL, ROADMAP_AUDIT_NEEDS_REPAIR, and FINAL_REVIEW_NEEDS_REPAIR each return repair to the same implementation Worker through one bounded repair authorization ledger. LOCAL_VERIFICATION_FAIL preserves verification_id. A changed artifact digest invalidates the earlier CODE_REVIEW ACK; run CODE_REVIEW again on the repaired artifact, then retest the same verification_id before Roadmap Audit.

{delegation_block}

Human Status Contract:
- After a material state change, output only three concise sections: What's done, What's next, Any blockers.
- Do not expose canonical JSON, recovery journals, or long task transcripts unless the user asks for diagnosis.
- After every Roadmap Audit, append a min/typical/max estimate revision, confidence={estimate_confidence(data)}, assumptions, and excluded external waiting time to estimate_history.

{adaptive_state_schema_block()}

{roadmap_projection_contract(goals_path, dashboard_path, dashboard)}

Deterministic Runtime Protocol Vocabulary:
- accepted mutation.type values: {' | '.join(ADAPTIVE_RUNTIME_MUTATIONS)}
- accepted outbox_kind values: {' | '.join(ADAPTIVE_OUTBOX_KINDS)}
- persisted generic outbox states: PREPARED | SENT | ACKED | COMPLETED | CANCELLED. Follow the kind-specific lifecycle above; do not apply every state to every kind.
- every outbox kind has only the safe cancellation branch PREPARED -> CANCELLED; SENT/ACKED/COMPLETED work cannot be cancelled.
- review report decisions: {' | '.join(ADAPTIVE_REVIEW_DECISIONS)}
- fixed successful operation_status values: {' | '.join(ADAPTIVE_RUNTIME_SUCCESS_CODES)}
- kind-derived successful operation_status values are exactly `<OUTBOX_KIND>_OUTBOX_PREPARED`, `<OUTBOX_KIND>_OUTBOX_SENT`, `<OUTBOX_KIND>_OUTBOX_ACKED`, `<OUTBOX_KIND>_OUTBOX_CANCELLED`, and `<REVIEW_KIND>_ACKED` as emitted by `state_runtime.py`.
- Rejection codes come only from `state_runtime.py` after JSON Schema validation. Prose labels, report decisions, and next_action_code values are not mutation types or persisted outbox states."""


def adaptive_user_guide_block(data: dict[str, Any], audit_paths: dict[str, str]) -> str:
    milestones = normalize_milestones(data.get("milestones"))
    dashboard = dashboard_required(data, len(milestones))
    dashboard_line = (
        f"- `{audit_paths['root']}progress-dashboard.html`：只读进度看板，由状态生成。"
        if dashboard
        else "- 本次没有触发 HTML 看板；路线图仍可在 `GOALS.md` 查看。"
    )
    return f"""## Adaptive 模式怎么回查

- 发布状态：`beta/experimental`。确定性 runtime、生成器、测试和安装检查只证明本地协议行为；不能据此声称所有 Codex App 环境都能自动循环到终态。
- 本次运行策略：`adaptive`。输出详略模式与它独立，不影响一份 Pack 启动方式。
- Adaptive 的实际启动顺序：唯一 State-Writer -> `INITIALIZE`/GOALS/Pack 归档 ACK -> 当前 Worker、heartbeat、Controller Goal、First Goal 各自使用一轮独立的 `ACQUIRE_LEASE -> outbox -> 外部动作 -> ACK`。前一轮 lease 消费后才开始下一轮，不能复用同一个启动 lease。
- `{audit_paths['root']}GOALS.md`：当前里程碑、为什么这样排序、需要什么证据、最近为何改计划；它是 `LOOP_STATE.md` 的只读投影。
{dashboard_line}
- `{audit_paths['state']}` 还应能回查 `goal_definition_registry`、`goal_execution_ledger`、`controller_goal_outbox`、`controller_lease`/已消费 lease id 和三阶段 assurance identity；缺少这些不是完整 Adaptive 初始化。
- 长任务超过 lease TTL 时，应看到 `SAME_OWNER_LEASE_RENEWED`、原 `SENT` outbox 的新 claim 和未变化的 dispatch/payload identity；不应出现第二次发送。
- Worker/Reviewer/Local 回报归档后，canonical `report_digest` 必须等于 `.codex-loop/reports/` 中对应 `application/json` 文件的实际 SHA-256；`PENDING_CONTROLLER_ARCHIVE` 不能直接进入状态。State-Writer 必须让 runtime 在 ACK 前解析报告并把顶层 dispatch/Goal/milestone/roadmap/target/payload/artifact/decision/source identity 与当前 SENT outbox 精确绑定；嵌套字段不能补齐缺失的顶层身份。
- 代码审查、路线图审计和最终完整审查复用一个只读审查任务，但会显示为独立派发和独立报告。
- Local Verifier 只在需要真实浏览器、本机权限、模拟器、设备或账号状态时创建。
- 自动只读子代理策略为 `{data.get('delegation_policy', 'disabled')}`；配置上限为 {data.get('max_read_only_subagents', 0)} 个、全程最多 {data.get('max_read_only_subagent_runs', 0)} 次运行。当前确定性路由每个 lease 只串行运行一个 sidecar，不承诺同时并发；它们只做短时搜索/归类，正式角色仍是同一项目下可回查的真实任务。
- 正常顺序：实现报告 ACK -> 代码审查 ACK -> 必要的本机验证 ACK -> 路线图审计 ACK -> GOALS 投影 ACK -> 切换唯一 Active milestone；最后一个里程碑还要经过最终完整审查 ACK 和独立终态写入 ACK。
- `ROADMAP_CHANGE_REQUIRES_APPROVAL` 表示新计划扩大了原始授权；`CONTROLLER_GOAL_CONFLICT` 表示当前任务已有不匹配的 Goal；`WAITING_CONTROLLER_LEASE` 表示另一个 Goal/heartbeat 回合正在安全路由。
- 每次状态变化只看 `What's done / What's next / Any blockers`；需要底层排障时再查看事件、事务和任务报告。"""
