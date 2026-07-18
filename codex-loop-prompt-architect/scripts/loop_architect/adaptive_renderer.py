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
from .state_runtime import ZERO_EXECUTION_BLOCKER_CODES


_DEFERRED_NATIVE_GOAL_RECOVERY_MUTATIONS = {
    "PREPARE_NATIVE_GOAL_GENERATION_MIGRATION",
    "COMMIT_NATIVE_GOAL_GENERATION_MIGRATION",
    "ROLLBACK_NATIVE_GOAL_GENERATION_MIGRATION",
}
_PUBLIC_ADAPTIVE_RUNTIME_MUTATIONS = tuple(
    mutation
    for mutation in ADAPTIVE_RUNTIME_MUTATIONS
    if mutation not in _DEFERRED_NATIVE_GOAL_RECOVERY_MUTATIONS
)


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
- Before every review send, persist an assurance_dispatch_outbox PREPARED record binding review kind, review dispatch id, current Worker dispatch/report, latest artifact digest, target Reviewer threadId, payload digest, roadmap version, and full lease claim; wait for the PREPARE mutation response, send once, then persist SENT. ACK_OUTBOX attaches the runtime-staged exact report bytes and a result containing exactly the report decision/status, runtime-computed report digest, and source artifact digest; runtime parses and identity-binds it before advancing SENT to ACKED. Only zero-artifact RECORD_REVIEW from its ACK path advances ACKED to COMPLETED.
- The send ACK must carry the exact lease_claim stored on that PREPARED record. A later lease cannot send it until an explicit same-owner renewal or evidence-backed takeover CAS rebinds the record and consumes the recovered route action.
- Every /review is a closed tagged union with common fields: review_kind, typed decision, milestone_id, roadmap_version, review_dispatch_id, full controller lease_claim, source Worker dispatch id, source Worker report digest, source Worker threadId, source artifact digest, target Reviewer threadId, payload digest, and evidence refs. The strict Reviewer report repeats those source identities at top level; nested copies do not count.
- CODE_REVIEW requires the latest durably COMPLETED/PASS Worker identity and canonical latest_worker.review_handoff. Worker PASS staging validates complete_diff_reference; ACK projects its worktree/snapshots/files/diff/reference/validation/evidence. The review payload copies artifact_identity/evidence_refs exactly; Controller never reads or recomputes the report. Repaired artifacts invalidate older assurance.
- CODE_REVIEW may return REVIEW_PASS, REVIEW_PASS_WITH_LIMITATION, REVIEW_NEEDS_REPAIR, or REVIEW_ARTIFACT_UNAVAILABLE. All four are ACKable typed decisions. REVIEW_PASS_WITH_LIMITATION is a pass only when every limitation is explicit, evidence-bounded, and contains no unresolved required fix; preserve it through later assurance and final claim boundaries. REVIEW_ARTIFACT_UNAVAILABLE closes the outbox as a non-PASS blocker, never as review success. Its report repeats review_kind=CODE_REVIEW, milestone_id, roadmap_version, review_dispatch_id, source Worker dispatch/report, source artifact digest, findings, and decision.
- Required order is CODE_REVIEW report ACK, then every required Local Verification PASS ACK for that exact artifact, then ROADMAP_AUDIT. ROADMAP_AUDIT requires the acknowledged CODE_REVIEW report digest, the same source artifact digest, current Local Verification ACK identity when required, canonical roadmap/Goal Queue versions, authorization envelope, original objective, and current estimates.
- ROADMAP_AUDIT returns ROADMAP_AUDIT_PASS only for an in-envelope typed transition proposal, ROADMAP_CHANGE_PROPOSED only for an out-of-envelope proposal that requires approval, or ROADMAP_AUDIT_PASS_FINAL_CANDIDATE when no future execution milestone remains. Each non-final report contains one closed `roadmap_proposal`, its canonical digest, proposal/audit ids, base roadmap version, typed operations, component digests for milestones/queue/definitions/authorization/estimate, next Goal, reason, and `within_authorized_envelope`. ROADMAP_AUDIT_PASS requires true; ROADMAP_CHANGE_PROPOSED requires false and cannot enter ROADMAP_REVISION.
- FINAL_AUDIT is a third tagged dispatch only for the final candidate. Runtime rejects its dispatch until the ROADMAP_AUDIT assurance record's estimate revision is the latest estimate_history entry and every required review surface has a current artifact-bound user response. Its assurance record persists the exact CODE_REVIEW/ROADMAP_AUDIT ids and a digest over current validation, Decision, estimate, freshness, Worker, and review identities; FINALIZE_LOOP requires the same chain and recomputed digest. It binds the acknowledged CODE_REVIEW and ROADMAP_AUDIT report digests, required Local Verification ACK identity, exact full Git base-to-head or non_git baseline-to-current artifact, all Goal reports, validation evidence, forbidden-artifact scan, state/event consistency, evidence layer, claim boundary, and approval ledger. It returns FINAL_REVIEW_PASS, FINAL_REVIEW_PASS_WITH_LIMITATION, or a repair/blocker decision with the same identities.
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
    zero_execution_blockers = ", ".join(
        f"`{code}`" for code in sorted(ZERO_EXECUTION_BLOCKER_CODES)
    )
    return f"""Adaptive State-Writer Protocol:
- Deterministic runtime gate: accept only a `STATE_MUTATION` line followed by one strict JSON request matching `references/adaptive-mutation.schema.json`. Do not accept a legacy slash-form state command.
- Resolve `RUNTIME_PATH` under `CODEX_HOME`/`~/.codex` and `RUNTIME_PYTHON` from the exact installed `[mcp_servers.codex-loop-state]` command. Its sole arg must be sibling `adaptive_state_mcp.py`; require the bridge and `RUNTIME_PATH` to share the installed skill root and that Python to load shipped dependencies. Any mismatch is zero-effect `STATE_RUNTIME_UNAVAILABLE`; never fall back to ambient `python3`. Directly invoke `[RUNTIME_PYTHON, RUNTIME_PATH, "--root", {repo_root_json}]` with exact JSON stdin; no shell interpolation.
- The runtime is the only writer for canonical Adaptive state, events, transaction journals, `GOALS.md`, immutable Controller Pack/report artifacts, leases, outboxes, roadmap revisions, and finalization. Do not manually create, patch, append, or rewrite those files, even when the requested change appears simple.
- Return the runtime's single structured JSON object unchanged as the state result. Exit status 1 with a structured rejection is a normal rejected mutation, not permission to retry with hand-written files. `DEPENDENCY_MISSING`, `SCHEMA_UNAVAILABLE`, `SCHEMA_INVALID`, or an unavailable runtime returns `STATE_RUNTIME_UNAVAILABLE` to Controller and performs no fallback write.
- Ordinary mutation application is read-only with respect to an earlier incomplete transaction and returns `RECOVERY_REQUIRED`; it never auto-recovers that transaction. Before a recovered Controller submits another mutation after interruption, invoke the same CLI as `[RUNTIME_PYTHON, RUNTIME_PATH, "--root", {repo_root_json}, "--recover"]`, relay its structured result, then reread canonical state. Never infer recovery from prose.
- The runtime performs no Codex App action. Controller alone reconciles and invokes task, Goal, automation, or message tools after a matching PREPARED result; later external observations return through a new typed mutation.
- External-action identities are closed. THREAD binds project_id, task_kind=PROJECT_TASK, the exact generated `bootstrap_role_kind`, its deterministic `formal_role_kind`, bootstrap_prompt_digest, and environment_kind; its ACK repeats those fields plus thread_id/worktree_path. Runtime enforces the lifetime child-task budget, one registered task per formal/bootstrap role key, the canonical project id, and worktree confinement to the repo or an explicit `control_plane_limits.allowed_external_worktree_roots` entry. The only child-role mapping is implementation|triage|explorer -> WORKER, code_reviewer -> REVIEWER, and local_verifier -> LOCAL_VERIFIER; display titles and keyword guesses never participate. AUTOMATION binds name, kind=HEARTBEAT, real Controller target_thread_id, rrule, exact prompt_digest, and prompt_normalization=LF_NORMALIZED_NO_TRAILING_NEWLINE; only one non-cancelled business heartbeat may exist. GOAL binds action, loop/Pack/milestone/objective digests and exact marker; UPDATE also binds goal_id and target_status. DELEGATION binds exploration/attempt ids, prompt/scope digests, source Goal/roadmap version, and max_depth=1. Native THREAD/AUTOMATION/GOAL ACKs require one immutable strict JSON Codex tool-result observation binding outbox kind/id, payload, target, and exact result; emulated Goal ACKs require the equivalent GOAL_TOOL_UNAVAILABLE observation. Reject extra, missing, or changed result fields before canonical mutation.
- Own canonical Adaptive keys, the roadmap change outbox, artifact ledger, {goals_path}, and the optional derived dashboard under .codex-loop/**.
- The pre-state creation/recovery of this one State-Writer task is the only external-action exception before canonical state. `INITIALIZE` is the only state-creation mutation and returns `LOOP_INITIALIZED`; it embeds real Controller/State-Writer ids, canonical authorization, milestones, complete immutable Goal definitions, the closed Goal Queue, and the exact Pack artifact bundle. The runtime computes and writes the initial `GOALS.md` projection.
- `ACQUIRE_LEASE` atomically creates the never-reused routing turn and increments the one shared Goal/heartbeat routing budget. No separate wake-start mutation exists. Every later mutation and outbox carries the exact lease_claim whose owner_identity is the registered real Controller threadId, never source_thread_id, a title, LOOP_ID, parent id, or fallback.
- One lease reserves exactly one route action. A control/dispatch/local outbox terminal ACK consumes it; an assurance claim is consumed by `RECORD_REVIEW`; `ROADMAP_REVISION`, `FINALIZE_LOOP`, and `STOP_LOOP` consume their own claims. `RELEASE_LEASE` consumes an observation-only claim for `WAITING_ACTIVE`, `WAITING_QUOTA_RECOVERY`, or another explicit no-action reason and rejects any reserved route or active outbox.
- Optional request artifacts are closed to the Controller Pack snapshot and safe report filenames. Validate exact UTF-8 digest and media type, enforce immutability, journal their bytes, and record them in artifact_ledger. Missing or conflicting artifact bytes are a rejection, never permission for a manual write.
- Formal DISPATCH/ASSURANCE/LOCAL ACKs bind status, report_digest, artifact_digest, and one JSON report. Before replying, the role calls installed MCP `runtime_codec` operation `STAGE_REPORT` with root plus outbox_id/result/exact report_text and returns only `FORMAL_REPORT_STAGED`; runtime hashes and archives those exact bytes without reserialization. A Worker PASS with new validation files supplies exact `evidence_sources` from its registered worktree; runtime stages and Gateway atomically archives them with the original-outbox report. Send evidence is never validation evidence. Controller forwards only the confined 0444 handles and never transports report or validation bytes or computes their digests. Worker artifact digest is `sha256:` plus after_snapshot_sha256. PASS additionally requires a replayable complete_diff_reference consistent with files/diff and is projected as review_handoff; FAIL/BLOCKED remain closable. RECORD_REVIEW has zero artifacts and reuses only its canonical ACK report.
- Validate event/request ids and all mutation inputs before changing canonical state. A replayed event_id must match its original immutable domain identity and return without changing state, counters, ledgers, or budget; a different payload/turn under that id is a conflict. Apply every mutation transactionally; any rejection restores the complete prior state, outboxes, counters, and lease. A failed request can never consume a lease or leave a partial terminal status.
- Only an acknowledged ROADMAP_AUDIT_PASS is input to ROADMAP_REVISION. The mutation carries the exact audited proposal/report digests; runtime recomputes every proposed component digest, verifies typed operations equal the actual milestone diff, independently enforces the immutable authorization envelope, and rejects a swapped or Controller-invented proposal. ROADMAP_CHANGE_PROPOSED routes only to ROADMAP_CHANGE_REQUIRES_APPROVAL.
- Before ROADMAP_REVISION, cancel each obsolete PREPARED Worker/assurance/Local outbox through its own `CANCEL_OUTBOX` transaction and ACK, then acquire a fresh lease. ROADMAP_REVISION rejects every remaining PREPARED, SENT, ACKED-assurance, or in-progress versioned outbox; it never silently cancels work inside the revision CAS. The revision atomically updates milestones, the complete future Goal Queue, immutable Goal definitions/execution ledger, roadmap version, projection metadata, and estimate history.
- A milestone may contain multiple dependency-ordered Goals. Completing one Goal while the milestone remains ACTIVE retires only that evidenced Goal and may unlock its READY sibling; reject unexecuted siblings only when a revision attempts to mark their milestone COMPLETE.
- The future Goal Queue schema is closed to goal_id, milestone_id, roadmap_version, status=READY|PLANNED, and depends_on. On initialization it contains every non-retired Goal definition for every ACTIVE/PLANNED milestone exactly once. Every entry resolves to a complete immutable Goal definition containing display worker role, exact worker_role_kind, objective, success criteria, validation, safe in-repo scope with no `..` or `.codex-loop`, phase permissions, dependencies, dispatch condition, and full payload-template digest. Reject missing/mutated definitions, unknown/retired/rebound ids, unknown dependencies, cycles, non-routable milestone references, or a nonterminal revision without at least one dependency-satisfied READY Goal for its single ACTIVE milestone.
- Preserve exactly one ACTIVE milestone. Reject a transition that creates zero or multiple active milestones while nonterminal. A normal RoadmapRevision is never a terminal transition.
- FINALIZE_LOOP is a separate CAS transaction. Accept it only after a completed Worker PASS dispatch plus exact CODE_REVIEW, required Local Verification, ROADMAP_AUDIT_PASS_FINAL_CANDIDATE, and FINAL_AUDIT report ACKs for the final artifact, with no PREPARED/SENT/IN_PROGRESS Worker, assurance, or Local Verifier outbox. Reconcile the complete Goal definition registry and execution ledger, not only the current queue; reject every non-retired, non-superseded Goal that was never executed and assured. Never mark the remaining queue complete in bulk. Then complete only the evidenced final Goal/milestone, empty/retire the already-resolved queue, refresh projections, set terminal status, and create one PREPARED finalization_outbox binding finalization_id, controller_goal_id, automation_id, and finalized_state_version.
- Native Goal is an external adapter governed by canonical `native_goal_policy=disabled|advisory|required`, with omitted legacy state interpreted as `required`. `FINALIZE_LOOP_APPLIED` or `STOP_LOOP_APPLIED` is the only runtime response that may carry a one-use closeout capability for the exact Goal target. Never call `update_goal` from a wait, timeout, missing task read, heuristic blocker, or model judgment.
- After FINALIZE_LOOP ACK, Controller uses the returned closeout capability according to native_goal_policy, pauses the exact registered heartbeat in the same Controller turn, and submits ACK_FINALIZATION with the exact external observations required by runtime. `CORE_FINALIZATION_ACKED` means deterministic core closeout only; `FINALIZATION_PENDING_EXTERNAL_SYNC` means the native adapter still lacks its exact observation. Neither is the existing release-success gate. Loop closeout is not complete until exact `FINALIZATION_ACKED` and finalization_receipt are canonical.
- STOP_LOOP is the only hard-block terminal mutation and must declare `stop_basis`. `THREE_OBSERVATIONS` retains the three distinct artifact-bound observations for the last three genuine consecutive Goal turns. `DETERMINISTIC_REPAIR_BUDGET` is valid only for runtime-proven `REPAIR_BUDGET_EXHAUSTED` and may STOP on the next dedicated Goal turn when Decision Cards are disabled. `USER_DECISION` additionally binds one APPLIED `STOP_LOOP_CONFIRMED` Decision option, its context digest, and the exact Decision-response Steering. The latter two bases require no observation-only spins. Runtime rejects mismatched cards, counters, goal ids, late/backfilled observations, or fabricated turns with zero side effects. No basis bypasses the repair cap.
- At repair exhaustion, dispatch no more Worker attempts and pause the exact heartbeat after registering one stable two-option Decision Card: stop on current evidence, or remain paused for a scoped correction. The WAIT option authorizes no repair. A later scoped `CORRECTION` may enter an audited `ROADMAP_REVISION` that retires the exhausted Goal and introduces a new Goal id; it preserves the original definition, attempt ledger, and repair counter. Only matching `STOP_LOOP_APPLIED` may authorize native Goal BLOCKED, followed by heartbeat pause and evidence-bound ACK_FINALIZATION. Other hard blockers still use `THREE_OBSERVATIONS`; waits and timeouts never authorize Goal BLOCKED.
- Worker repair accounting is execution-aware. Every new DISPATCH report states top-level execution_started. PASS/FAIL are executions. BLOCKED with execution_started=false also states a top-level runtime-approved deterministic control-plane blocker_code; runtime_codec `STAGE_REPORT` binds both fields into its ACK-ready result even if the caller omits them there. The closed allowed set is: {zero_execution_blockers}. The closure remains immutable history but consumes no initial/repair slot. Never relabel product failure as control-plane rejection.
- If an already archived Worker report proves execution_started=false but an older ACK projected true, pause at a canonical safe point and use RECONCILE_WORKER_EXECUTION_CLASSIFICATION with the exact Goal, dispatch, report path/digest, and approved blocker code. Runtime re-reads the immutable canonical report and corrects only that classification; it never deletes the attempt, clears history, changes Pack identity, or runs while a lease/outbox is active.
- ROADMAP_CHANGE_REQUIRES_APPROVAL is a blocker record, never an applied mutation.
- controller_lease acquisition/release is CAS-protected and idempotent. Missing, consumed, or mismatched claims are rejected as `STALE_OR_MISSING_CONTROLLER_LEASE`; failed claim/time probes are pure rejections and cannot advance logical time. A competing owner receives WAITING_CONTROLLER_LEASE. Expired takeover requires trustworthy current time plus structured read_thread evidence containing the exact owner task, last activity time, read digest, and STALE decision; only then may CAS replace the full claim and increment the epoch. A fresh route uses a fresh lease rather than bundling multiple startup or recovery actions.
- A still-active exact same owner may proactively renew or recover an expired claim with one bound `application/json` observation whose parsed object exactly matches the ACTIVE_SAME_OWNER evidence fields, the same routing_turn_id, and a new lease_id/epoch. Takeover likewise requires one exact bound JSON STALE observation. Renewal may cross the one exact matching PREPARED/SENT/ACKED external record: it atomically rotates only the canonical outbox lease claim, while the immutable payload digest continues to bind the original embedded dispatch claim; payload/dispatch/report identity and status do not change and the action is never resent. Reject a mismatched owner, changed route identity, unrelated active record, or ambiguous multi-route recovery; never fabricate STALE evidence.
- A ROADMAP_AUDIT report ACK is the durable structured proposal. Controller validates that acknowledged proposal, acquires a dedicated fresh lease, and submits one ROADMAP_REVISION CAS. If that lease expires before the CAS, renew/take over only the lease and reuse the same acknowledged audit identity.
- Dispatch recovery matches dispatch_id, payload_digest, target_thread_id, immutable Goal definition digest, exact `worker_role_kind`, and the stored lease route. The target task's registered `bootstrap_role_kind` must equal the Goal definition and payload role kind; sharing formal WORKER does not authorize implementation/triage/explorer substitution. Permit only one PREPARED/SENT/IN_PROGRESS Worker dispatch across roadmap revisions. A selected Goal must itself be READY with completed dependencies. Worker PASS closes eligibility for redispatch. An acknowledged Worker FAIL plus CODE_REVIEW, Local Verification, ROADMAP_AUDIT, and FINAL_AUDIT repair decisions form one closed failure-source union and consume the same per-Goal repair budget.
- Native Goal creation and nonterminal cross-milestone transition use controller_goal_outbox: `PREPARED -> call once -> SENT -> ACKED`; UPDATE binds source Goal and target status. Terminal FINALIZE/STOP instead returns a one-use closeout capability because terminal state permits only ACK_FINALIZATION: required mode calls update_goal directly under that capability, while disabled/advisory make no Goal call; ACK_FINALIZATION binds the resulting Goal/heartbeat observations. Validate exact loop/pack/milestone/objective marker and canonical identity before accepting any native status.
- If Goal tools are unavailable, attach one immutable `application/json` unavailability/transition observation and ACK the exact PREPARED GOAL outbox directly as `EMULATED_SINGLE_ACTIVE_MILESTONE` (or its later target status). Do not mark it SENT and do not claim a native call occurred.
- Every optional sidecar uses a generic DELEGATION outbox before spawn: `PREPARED -> spawn once -> SENT -> ACKED`. ACK requires one immutable `application/json` result artifact whose digest is the canonical report_digest. Only a COMPLETED, archived, ACKED result may influence routing; interrupted/dropped attempts are terminal evidence only. agent_id never enters thread_registry.

{roadmap_projection_contract(goals_path, dashboard_path, dashboard)}"""


def local_verifier_protocol(state_gateway: bool = False) -> str:
    if state_gateway:
        return """Local Verifier Protocol (schema v3):
- This is a real Codex App project task created just in time, never an internal subagent and never a code-writing Worker.
- Verify the exact branch/commit/worktree/snapshot identity supplied in the Gateway-derived dispatch using the declared local browser, account, permission, simulator, device, or hardware surface.
- Accept a dispatch only after the exact source artifact has an acknowledged CODE_REVIEW. Every dispatch/report carries milestone_id, roadmap_version, Goal ID, verification_id, source artifact digest, local dispatch_id, real target threadId, payload digest, and Gateway-derived route identity. Return PASS, FAIL, or BLOCKED with those identities plus exact steps, expected/actual result, screenshot/log/console refs, reproduction steps, blocker, and next action.
- Before send, `state_gateway(PREPARE_ROUTE)` must return the exact PREPARED local route; after the one external send, `RECORD_ROUTE_SENT` makes it SENT. Stage the report through runtime_codec, then close only that route through `ACK_ROUTE_RESULT`. No PASS/FAIL/BLOCKED report may be accepted without that matching SENT route.
- Do not expose credentials, cookies, tokens, personal data, or sensitive screenshots to remote Workers or reports.
- FAIL returns the same verification_id to the implementation Worker for repair and requires a retest of that exact item. If repair changes the artifact digest, the repaired artifact needs a new CODE_REVIEW ACK before retest. Worker prose cannot replace either gate.
- BLOCKED becomes LOCAL_VERIFICATION_BLOCKED or LOCAL_VERIFICATION_PENDING according to the declared policy; never claim verification passed."""
    return """Local Verifier Protocol:
- This is a real Codex App project task created just in time, never an internal subagent and never a code-writing Worker.
- Verify the exact branch/commit/worktree/snapshot identity supplied in the dispatch using the declared local browser, account, permission, simulator, device, or hardware surface.
- Accept a dispatch only after the exact source artifact has an acknowledged CODE_REVIEW. Every dispatch/report carries milestone_id, roadmap_version, Goal ID, verification_id, source artifact digest, local dispatch_id, real target threadId, payload digest, and full current lease_claim. Return PASS, FAIL, or BLOCKED with those identities plus exact steps, expected/actual result, screenshot/log/console refs, reproduction steps, blocker, and next action.
- Before send, State-Writer must return an applied PREPARED result for the exact local_verification_outbox; after the one external send, MARK_OUTBOX_SENT makes it SENT. No PASS/FAIL/BLOCKED report may be accepted without that matching SENT record, and ACK_OUTBOX with the bound report closes it as COMPLETED.
- Do not expose credentials, cookies, tokens, personal data, or sensitive screenshots to remote Workers or reports.
- FAIL returns the same verification_id to the implementation Worker for repair and requires a retest of that exact item. If repair changes the artifact digest, the repaired artifact needs a new CODE_REVIEW ACK before retest. Worker prose cannot replace either gate.
- BLOCKED becomes LOCAL_VERIFICATION_BLOCKED or LOCAL_VERIFICATION_PENDING according to the declared policy; never claim verification passed."""


def state_gateway_protocol(repo_root: str, goals_path: str, dashboard_path: str, dashboard: bool) -> str:
    """Protocol emitted for new schema-v3 Packs.

    This intentionally does not describe the legacy session State-Writer.  The
    installed MCP server is the only canonical writer in a new Pack; retaining
    old instructions here would recreate the single-message wakeup dependency
    that v3 removes.
    """

    zero_execution_blockers = ", ".join(
        f"`{code}`" for code in sorted(ZERO_EXECUTION_BLOCKER_CODES)
    )
    return f"""Adaptive v3 MCP State Gateway Protocol:
- Canonical writer: the installed `codex-loop-state` MCP tool `state_gateway({{root, request}})`. It is the only writer for `LOOP_STATE.md`, events, journals, report archive, {goals_path}, {dashboard_path}, leases, outboxes, route ledger, and terminal receipt. Controller, Worker, Reviewer, Local Verifier, and any Supervisor must never create a State-Writer task or hand-edit `.codex-loop/**`.
- A public request has exactly `request_id`, `operation`, `occurred_at`, and `parameters`. `request_id` is a safe ID of at most 128 characters and is deterministically mapped to bounded journal/event locators. A schema-v3 `route_id` is a safe ID of at most 48 characters because it is reused in portable report, staging, lease, freshness and verification identifiers. The App-attested current Controller turn is mandatory. The controller may provide only its Goal, route kind, target task and direct external observation; it must not copy a lease, freshness object, validation matrix, review handoff, artifact identity, roadmap version, or payload digest.
- Schema v3 is host-cooperative, not Byzantine: bind real App task/automation return values and readback to the current host-attested turn, but never claim a provider-signed subtool receipt the host does not expose. `REGISTER_TASK` accepts the returned task identity; `REGISTER_HEARTBEAT` and `RECORD_HEARTBEAT_OBSERVATION` bind actual automation create/readback; `RECORD_ROUTE_SENT` accepts the returned target thread; and `ACK_TRANSPORT_PAUSE` / `ACK_FINALIZATION` require an actual PAUSED automation readback. A future non-argument `x-codex-app-action-receipt-v1` carrier is optional stronger evidence and is strictly verified when present, but its absence is not a normal-path blocker. Never invent a return value from a transcript, and never claim Byzantine resistance to a Controller able to forge every App call.
- `INITIALIZE` creates a fresh schema-v3 canonical state from an exact Pack source inside the new root, with no State-Writer identity. `INITIALIZE_SUCCESSOR` additionally binds an immutable terminal predecessor receipt and root digest; neither operation can overwrite an existing canonical root. `REGISTER_TASK` records only one host-bound reconciled Worker, Reviewer, or Local Verifier identity; it is the narrow bootstrap observation, never a product dispatch.
- `REGISTER_HEARTBEAT` binds the one real ACTIVE business heartbeat and its exact observation. `RECORD_HEARTBEAT_OBSERVATION` records only a later bound readback, including PAUSED terminal readback. Neither may create a second heartbeat. `PREPARE_ROUTE` atomically attests the Controller turn, captures the current repository identity, builds the canonical payload and one PREPARED outbox. `RECORD_ROUTE_SENT` requires the real returned target thread to equal that outbox; Gateway supplies its canonical exact materialized payload digest. It does not fabricate SEND from a bare route id, and a send observation never creates PASS. After the exact target role stages a report, its bridge persists one immutable, root-confined target attestation derived from that SENT outbox and report digest; the Controller derives and verifies it, never supplies it. `ACK_ROUTE_RESULT` consumes only that runtime-staged report for the same SENT outbox. `REPORT_RECOVERY` ACKs that original outbox when stdout/task indexing was lost; it never creates a report-only product dispatch or increments a repair attempt.
- `MATERIALIZE_DISPATCH`, `VERIFY_DISPATCH`, `STAGE_REPORT`, `STAGE_EXTERNAL_RECEIPT`, `NORMALIZE_FINGERPRINT`, and `CAPTURE_COMPLETE_DIFF` use `runtime_codec`; no codec operation may be implemented through a shell session stdin. The codec is bounded, one-frame, strict UTF-8 and fail-closed. Missing codec support returns `RUNTIME_CODEC_TOOL_UNAVAILABLE` with zero side effects.
- Runtime binding is installation-owned: resolve `RUNTIME_PATH` and `RUNTIME_PYTHON` from the exact installed `[mcp_servers.codex-loop-state]` registration. Require the bridge and `RUNTIME_PATH` to share the installed skill root, and its internal launcher is `[RUNTIME_PYTHON, RUNTIME_PATH, "--root", <canonical root>]`; never fall back to ambient `python3`. A mismatch is `STATE_RUNTIME_UNAVAILABLE` with zero side effects. Controller/roles still invoke only `runtime_codec` and never run that launcher through a shell.
- A report may close with `execution_started=false` only for the closed runtime zero-execution blocker set: {zero_execution_blockers}. Any other pre-execution BLOCKED result is rejected rather than consuming or bypassing a repair attempt.
- The Gateway derives review handoff, validation matrix, freshness, current artifact and roadmap data from canonical state. PASS projection requires all three current identities: current Goal artifact, current Worker dispatch, and a PASS formal report. BLOCKED, stale dispatches, stale artifacts, or reports from another outbox cannot enter a PASS projection.
- `CAPTURE_COMPLETE_DIFF` reads raw Git bytes itself, includes only allowed untracked paths, rejects control-plane/path escapes, verifies reverse binary application, and stores a manifest. A Worker PASS may use only its digest-addressed `CAPTURED_GIT_DIFF_V1` reference; runtime derives and rechecks the capture path. Models never carry binary patch bytes or a control-plane path in message strings.
- `ADVANCE_ROADMAP` consumes only a current `ROADMAP_AUDIT_PASS` and advances the unchanged canonical Goal registry; it cannot add, delete, reorder, or re-materialize Goal definitions. `PREPARE_FINALIZATION` requires a current Final Audit PASS and all prior Goals complete; `ACK_FINALIZATION` then records only the actual, bound PAUSED-heartbeat readback. Schema v3 disables native Goal adapters, so the record explicitly says `GATEWAY_NO_NATIVE_GOAL` rather than faking a Goal completion.
- `MIGRATE_V2_TO_V3` is explicit-only, requires a paused quiescent v2 state, and archives the historical State-Writer identity. It is never an automatic recovery action. `INITIALIZE_SUCCESSOR` initializes a fresh root from a terminal predecessor handoff and cannot alter that predecessor.
- `LOOP_METRICS.json` is derived only: it records route/control waiting windows, dispatch/review/rejection counts, transport failures, Steering and available token measurements. It is neither canonical state nor permission to route.
- For one matching transport fingerprint/outbox, the first real registered-heartbeat observation retains that outbox and waits. Gateway binds its fingerprint, time and heartbeat identity. Two natural heartbeat observations or fifteen minutes enter `WAITING_TRANSPORT_RECOVERY`, stop canonical routing, and require one user notification. Controller may submit `ACK_TRANSPORT_PAUSE` only after a real pause and matching PAUSED readback; before that, never claim the business heartbeat is PAUSED. Do not keep retrying every ten minutes; do not use an outer Supervisor as a second routing channel.
- Legacy schema-v1/v2 State-Writer and `route_state_mutation` requests remain compatibility-only. A schema-v3 Pack must not use either path."""


def state_gateway_reviewer_protocol() -> str:
    return """Adaptive v3 Assurance Protocol:
- This real read-only Reviewer is reused for CODE_REVIEW, ROADMAP_AUDIT and FINAL_AUDIT, but each is a separately prepared Gateway route and a separate exact report.
- Accept only a runtime-verified review payload. Its source Worker dispatch, report digest, current artifact digest, Code Review/Local ACK chain where required, roadmap version and target thread identity are Gateway-derived and immutable.
- Stage the formal JSON report through `runtime_codec(operation=STAGE_REPORT)` before replying. Return only the staged handle. The Controller forwards that handle to `state_gateway(operation=ACK_ROUTE_RESULT)`; neither actor reads, copies, hashes or reconstructs report bytes.
- A CODE_REVIEW PASS applies only to the current Worker artifact. A required Local Verification PASS is bound into the subsequent Roadmap/Final audit payload. BLOCKED, needs-repair, a different artifact, or a different Worker dispatch is non-PASS evidence and cannot advance the Goal.
- Review findings remain severity-first with exact file/line evidence, required fixes and test gaps. Do not write product files, canonical state, projections, dashboard, or reports by hand."""


def state_gateway_controller_protocol(data: dict[str, Any], audit_paths: dict[str, str]) -> str:
    return f"""Adaptive v3 Controller Routing Protocol:
- This Controller is read-only. New v3 topology is Controller + just-in-time Worker + reusable Reviewer + optional Local Verifier + one business heartbeat. There is no State-Writer task and no external Supervisor role.
- Bootstrap the Controller identity and archive the exact Pack through Gateway initialization. Reconcile/create a formal task only when needed, then record its actual returned identity through `REGISTER_TASK` before routing it. Create Reviewer only after a current Worker PASS; create Local Verifier only when the Goal requires real local evidence.
- Every route is `PREPARE_ROUTE`; materialize through `runtime_codec`; send returned transport text once; record the real returned target through `RECORD_ROUTE_SENT`; then wait for a role-owned staged report and call `ACK_ROUTE_RESULT`. Gateway derives the payload digest and route context rather than accepting Controller copies. A lost report index/stdout uses `REPORT_RECOVERY` for the existing outbox, never a second product dispatch. An optional stronger action receipt may be supplied if the host exposes it, but is never required.
- The Gateway, not Controller prose, chooses current validation/review/artifact/freshness context. A Worker PASS flows CODE_REVIEW -> required LOCAL_VERIFICATION -> ROADMAP_AUDIT. A nonfinal `ROADMAP_AUDIT_PASS` uses `ADVANCE_ROADMAP`; a final candidate then flows FINAL_AUDIT -> PREPARE_FINALIZATION -> real heartbeat pause plus PAUSED readback -> ACK_FINALIZATION. Native Goal adapters are disabled in schema v3.
- At a matching transport fault, retain the same outbox. After the Gateway returns `WAITING_TRANSPORT_RECOVERY`, use the real App to pause the one business heartbeat, submit `ACK_TRANSPORT_PAUSE`, and notify the user once; do not reactivate it, restart Codex, or create a parallel Supervisor workaround.
- Native Goal adapters are disabled in schema v3 and cannot replace canonical Gateway finalization. `FINALIZATION_ACKED` is the only completion state; a terminal predecessor remains immutable and a continuation uses `INITIALIZE_SUCCESSOR` in a fresh root.
- `STATUS.md`, `{audit_paths['root']}GOALS.md`, and `LOOP_METRICS.json` are derived observation surfaces. Read canonical state before a route; never use a projection or a task title as mutation authority.

Human Steering And Convergence:
- Schema-v3 preserves human-control evidence but does not reinterpret prior-schema mutation vocabulary as Gateway operations. Historical v1/v2 records remain readable through compatibility code; new v3 state may cross only the explicit paused-safe-point `MIGRATE_V2_TO_V3` boundary.
- `STATUS_QUERY` is read-only: it reads canonical state plus derived `STATUS.md`, `GOALS.md`, and metrics, creates no route and cannot spend a route budget. A user pause is a safety request, not a Controller assertion: `PAUSE_REQUESTED` is historical run-control vocabulary, while v3 may project a heartbeat PAUSED only after a real pause and matching PAUSED readback.
- Decision Cards are limited to real, user-owned gates. Their decision id, option id, scope and context digest must bind the exact current canonical state; a stale card has no authority. `review_surface` is confined user-artifact guidance, not evidence that promotes a product route.
- The Gateway derives the current Validation Matrix and context freshness itself. `RECORD_CONTEXT_FRESHNESS` is a v2 compatibility label, never a schema-v3 Controller request. Repeated failure evidence can be diagnosed as `THRASHING_DETECTED`, but does not authorize a retry outside the bounded repair policy. Conflicting hard evidence is `EVIDENCE_CONFLICT` and fails closed."""


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
    native_goal_policy = data.get("native_goal_policy", "required")
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
    human_control_policy = {
        "human_steering_enabled": data.get("human_steering_policy", "auto")
        != "disabled",
        "status_projection_enabled": data.get("status_projection", "enabled")
        != "disabled",
        "decision_cards_enabled": data.get("decision_card_policy", "on_real_gate")
        != "disabled",
        "failure_fingerprint_enabled": True,
        "context_freshness_required": True,
        "review_evidence_policy": "deterministic_first",
    }
    human_control_policy_json = json.dumps(
        human_control_policy, ensure_ascii=False, indent=2, sort_keys=True
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

Canonical Human-Control Policy (INITIALIZE must use this exact object):
HUMAN_CONTROL_POLICY_JSON_BEGIN
{human_control_policy_json}
HUMAN_CONTROL_POLICY_JSON_END
- Obey this canonical policy before routing: disabled Steering or Decision UX must not be attempted, disabled STATUS writes remain absent, and the mandatory failure-fingerprint, freshness, and deterministic-evidence safety fields can never be weakened by prose or a later roadmap revision.

Canonical Native-Goal Adapter Policy:
- native_goal_policy: {native_goal_policy}
- Persist this value in INITIALIZE. Native Goal is an external adapter, never the canonical source of execution truth. An omitted value in legacy canonical state is interpreted as `required` for compatibility.

Single Active Milestone And Native Goal:
- Canonical state must contain exactly one ACTIVE milestone until terminal completion.
- Apply only native_goal_policy `{native_goal_policy}`. `disabled` and `advisory` use only the emulated canonical control-plane record and forbid get/create/update Goal calls; `required` uses only the native adapter and requires its exact receipt before the existing FINALIZATION_ACKED gate. Never silently promote disabled/advisory to native or required to emulated success.
- In `required` mode, get/create and nonterminal update Goal calls require the fenced lease. After FINALIZE/STOP, acquire no new lease: its exact closeout capability is the fence for the one terminal update before ACK_FINALIZATION. Disabled/advisory use only `EMULATED_SINGLE_ACTIVE_MILESTONE` and make no Goal call.
- Native objective ends with exact final-line marker `[CODEX_LOOP_MILESTONE loop_id=<LOOP_ID> pack_sha256=<FULL_64_HEX_SHA256> milestone_id=<ID> objective_sha256=<FULL_64_HEX_SHA256>]`. `PREPARE_OUTBOX(kind=GOAL, action=CREATE)` before get/create; marker alone is untrusted and cross-loop recovery is forbidden.
- Same-goal BLOCKED after user resume needs fresh-lease `RECORD_CONTROLLER_GOAL_RESUME` binding ordered pre-BLOCKED/`SAME_GOAL_RESUME`/post-BLOCKED JSON. Its receipt changes no Goal/outbox and never implies ACTIVE; no action/attempt/milestone. Null/COMPLETE is `NATIVE_CONTROLLER_GOAL_IDENTITY_LOST`.
- Only in `required` mode use get_goal({{}}), create_goal(objective=CONTROLLER_MILESTONE_OBJECTIVE, token_budget={controller_goal_budget_text} only when this is an integer), and capability-authorized update_goal(status="complete" or status="blocked") exactly as exposed. When the value is OMIT_TOKEN_BUDGET_ARGUMENT, omit the argument entirely. Do not invent goal ids or pause/resume arguments.
- Create the Controller goal from the active milestone outcome, constraints, required evidence, and completion criteria. Pass token_budget only when `controller_goal_token_budget` was explicitly supplied; the global metered-runtime `token_cap` is ledger-wide and must never be copied into each milestone Goal.
- Goal tools may create/read and mark a goal complete or genuinely blocked when policy permits. Do not claim they can programmatically pause, resume, edit, or clear the UI Goal row. `update_goal(status="complete")` is permitted only by the one-use matching closeout capability returned with FINALIZE_LOOP_APPLIED; `update_goal(status="blocked")` is permitted only by the one-use matching closeout capability returned with STOP_LOOP_APPLIED. Transient waits, task-read/index/message timeouts, missing transport observations, quota recovery, and human Decisions stay nonterminal and never update the Goal.
- Controller invokes ACQUIRE_LEASE/TAKEOVER_LEASE only through the configured `route_state_mutation` MCP tool, never through State-Writer, CLI, shell, or inline Python. In model arguments omit controller_turn_id; the signed Codex MCP bridge injects the host-owned real App turn id after validating request metadata and the direct app-server parent. Runtime consumes that identity on the first route and rejects a second lease from the same App turn after completion or release. All other mutations still go through the existing State-Writer.
- Pack bytes change only through the journaled same-heartbeat PREPARE/MIGRATE/ROLLBACK protocol below; unmigrated bytes have no authority. Native Goal launch identity remains in immutable Pack history.
- Metered calls use canonical LOCAL `external_call_authorization` and immutable `.codex-loop/external-receipts/` STARTED-before-send/COMPLETED-before-stdout. They bind route/Pack/Goal/lease/turn/target, provider/model, request/call, artifact, status/exit, and usage. COMPLETED replay recovers without retry; STARTED-only returns EXTERNAL_CALL_OUTCOME_UNKNOWN and forbids retry. Unknown tokens stay null/complete=false; exclude prompts, responses, credentials, and secrets.
- Creation and nonterminal cross-milestone transitions use GOAL outboxes: required is `PREPARED -> call once -> SENT -> ACKED`; disabled/advisory direct-ACK the exact PREPARED GOAL outbox as EMULATED without a Goal call. After FINALIZE_LOOP_APPLIED/STOP_LOOP_APPLIED, terminal state allows only ACK_FINALIZATION, so do not prepare a GOAL UPDATE: required calls update_goal once under the returned capability, disabled/advisory make no Goal call, and both submit the exact capability plus Goal/heartbeat observations to ACK_FINALIZATION. Tool unavailability is `FINALIZATION_PENDING_EXTERNAL_SYNC`, never success.
- Runtime rejects Worker DISPATCH unless canonical `controller_goal` is ACTIVE or EMULATED and names that exact Active milestone. When a nonterminal ROADMAP_REVISION changes the Active milestone it returns `COMPLETE_CURRENT_CONTROLLER_GOAL`; complete the old Goal, ACK its transition, create/ACK the new Active-milestone Goal, and only then dispatch the next Worker. A same-milestone sibling keeps the existing Controller Goal and returns `PREPARE_NEXT_GOAL_OUTBOX`. FINALIZE_LOOP enforces the same final-milestone Goal binding.

Canonical Dispatch Payload Identity:
- Every Worker, Reviewer, and Local Verifier dispatch is one closed JSON payload containing `dispatch_payload_digest` and the full lease claim including `routing_turn_id`. Freeze the bounded state snapshot and materialize every other runtime field before computing it.
- Construct exactly `{{"envelope_type": "WORKER_DISPATCH|REVIEW_DISPATCH|LOCAL_VERIFY_DISPATCH", "payload": {{...}}}}` with literal `PAYLOAD_DIGEST_PLACEHOLDER`. Send that structured object to installed MCP `runtime_codec` operation `MATERIALIZE_DISPATCH`. Do not start a shell process or depend on a session stdin. Missing tool stops as `RUNTIME_CODEC_TOOL_UNAVAILABLE` with zero side effects.
- Materialization succeeds only when runtime_codec returns one structured `PAYLOAD_MATERIALIZED` result. Persist its returned digest in PREPARE_OUTBOX, then send its returned `transport_text` unchanged as the exact task-message body. Never manually replace text, retain a `sha256:` prefix, add angle brackets, normalize whitespace, reserialize the returned body, or hash a UI/XML wrapper.
- Receiver passes CANONICAL_REPO_ROOT and exact `codexDelegation.input` string to runtime_codec operation `VERIFY_DISPATCH` and acts only on `PAYLOAD_VERIFIED`. Runtime alone maps CRLF to LF, removes at most one trailing newline, strictly parses/canonicalizes JSON, and verifies semantic digest plus SENT identity; entities, duplicates, NaN, other framing, or field changes fail. UI/delegation wrappers and `PAYLOAD_BYTES_VERIFIED` are not execution permission.
- Capture/framing uncertainty returns `PAYLOAD_VERIFICATION_RETRY_REQUIRED` on the same SENT/task/dispatch/payload: retry locally, renew only for TTL, and do not execute/ACK/resend/consume repair. Proven invalid App payload with `execution_started=false` may self-stage one zero-effect BLOCKED report; completed work with staging/archive failure restages the same report and ACKs without reexecution or another MARK_SENT.
- The bounded state snapshot is intentionally frozen immediately before PREPARE_OUTBOX. PREPARE and MARK_OUTBOX_SENT then advance canonical state, so the receiver must not require snapshot.state_version to equal the latest state_version. It verifies that the matching outbox has `prepared_state_version == snapshot.state_version + 1`, is now SENT, and still has the same roadmap, Goal, lease, target, payload, and definition/artifact identities. A later unrelated version increase is acceptable only while those identities remain unchanged.

Resource-Bounded Observation And Validation:
- Projection-first observation contract: compare canonical `LOOP_STATE.md` mtime/size and projected `STATUS.md` state version before reparsing unchanged canonical bytes. `STATUS.md` is observation-only and never mutation authority; read canonical state before every mutation and whenever the projection changed, is stale, or cannot answer the expected transition.
- After a send, observe canonical mtime/version and the expected artifact first. State-Writer observation order is canonical mtime/version, expected artifact, compact projected fields, then a compact State-Writer task read only if still unresolved. Read Controller only for phase completion, a blocker, or a Decision.
- Compact task observation uses `read_thread(threadId=..., turnLimit=1, includeOutputs=false)`. Parse tool results internally and retain only status, timestamps, item types, and the final bounded agent message. Never forward raw `read_thread` output or long task transcripts.
- Allow one in-flight read per target. Poll unresolved work with 30/60/120-second backoff and reset the sequence only after an observed change; never use aggressive fixed polling or a shell busy-wait loop.
- Validation identity dedupe keys evidence by exact artifact digest, command, environment/toolchain identity, and relevant config/lockfile digest. Reuse only an exact match; run narrow tests after narrow changes, and run full fuzz/coverage/install once for the final artifact. Do not duplicate a local full gate while equivalent CI is already running for that exact commit.
- Runtime transport contract: codec operations use the installed MCP `runtime_codec` bounded typed channel and never require a shell session stdin. Legacy CLI integrations still use bounded strict UTF-8 framing and report EOF-before-frame separately. Bound cleanup of optional local child processes owned by the current turn as TERM -> bounded wait -> KILL -> waitpid, and confirm no residual child/session remains. Recover a completed external result from its durable receipt; lost stdout never authorizes an external retry.

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
- Only the one-use exact closeout capability returned by FINALIZE_LOOP_APPLIED authorizes `update_goal(status="complete")`; apply policy `{native_goal_policy}`, pause heartbeat, and ACK_FINALIZATION with required observations. `CORE_FINALIZATION_ACKED`/`FINALIZATION_PENDING_EXTERNAL_SYNC` are not release success; wait for exact FINALIZATION_ACKED. FINAL_AUDIT failure routes repair/blocker only.
- A hard blocker needs three prior natural observation-only Goal turns with distinct immutable artifacts, identical blocker/Goal identity, `route_action=null`, and `HARD_BLOCK_OBSERVATION_ONLY`. The next Goal turn may STOP_LOOP with those observations plus aggregate report. Only its returned one-use exact closeout capability may authorize `update_goal(status="blocked")` when policy permits; then pause heartbeat and ACK_FINALIZATION. Never fabricate/backfill turns, stop early, update Goal from wait/timeout, or leave heartbeat ACTIVE.

Local Verification:
- policy: {data.get('local_verification_policy')}
- Create a real Local Verifier task only when a milestone requires an authenticated browser, local credentials, macOS permission, extension, Xcode/simulator, physical device, hardware, or other evidence unavailable to the Worker/Reviewer checkout.
- For a worktree artifact, prefer a just-in-time same-directory fork of the Worker after its report ACK; otherwise prove access to the exact absolute worktree/snapshot. For machine/account UI state that is independent of checkout, use a local task in the same Codex Project and still pass exact artifact identity.
- WORKER_FAIL, REVIEW_NEEDS_REPAIR, LOCAL_VERIFICATION_FAIL, ROADMAP_AUDIT_NEEDS_REPAIR, and FINAL_REVIEW_NEEDS_REPAIR each return repair to the same implementation Worker through one bounded repair authorization ledger. LOCAL_VERIFICATION_FAIL preserves verification_id. A changed artifact digest invalidates the earlier CODE_REVIEW ACK; run CODE_REVIEW again on the repaired artifact, then retest the same verification_id before Roadmap Audit.

{delegation_block}

Human Steering And Convergence:
- schema_version=2; legacy v1 changes only through source-bound MIGRATE_V1_TO_V2. Recover state/STATUS journals first, then record stable message-item or turn-cursor Steering identity before routing; unresolved identity rejects only that item.
- STATUS_QUERY only reads canonical state and derived journaled `.codex-loop/STATUS.md`; it acquires no lease, changes no state, spends no budget, and creates no task. Accepted Steering: STATUS_QUERY, PAUSE, RESUME, CONSTRAINT, CORRECTION, DECISION_RESPONSE.
- PAUSE is RUNNING -> PAUSE_REQUESTED -> PAUSED_AT_SAFE_POINT and cannot complete over SENT work without interrupt/safe-point evidence. RESUME preserves every task, ledger, budget, failure, heartbeat, and evidence identity.
- CONSTRAINT/CORRECTION is ACKed before effect, never rewrites SENT payloads, and uses a safe point or authorized ROADMAP_REVISION; Steering never expands permissions, budget, side effects, claims, merge/deploy, production, or secrets.
- Decision Cards exist only for real gates and bind id, context digest/version range, 2-3 exclusive options, scope, exclusions, and preauthorized capability. RECORD_DECISION_RESPONSE also binds/archives its message Steering identity; changed context is DECISION_STALE and no card creates authority.
- Optional review_surface is confined user-artifact guidance, not code/deploy evidence; acceptance needs valid DECISION_RESPONSE and feedback is CORRECTION.
- RECORD_FAILURE uses generic-v1 normalization and immutable history. Threshold 2 matching strategy+diff+changed-files failures may yield THRASHING_DETECTED; different diff/model similarity is POSSIBLE_STRATEGY_REPEAT; exhausted repair authorization is STRATEGY_EXHAUSTED.
- New-Pack Worker PASS ACK atomically projects required Validation Matrix items bound to current dispatch/artifact and archived evidence. Invalid sets reject the whole ACK. RECORD_VALIDATION is legacy/post-ACK only; Reviewer prose cannot override the gate.
- RECORD_CONTEXT_FRESHNESS precedes dispatch/recovery/repair/affected Steering and all assurance, binding closed repo/worktree/branch/base/head, dirty/untracked, source/scope/interface/lockfile/config, Worker/report/artifact/diff/paths and change flags. Replace the Worker payload's bootstrap sentinel with the latest GOAL_DISPATCH context digest. Only FRESH, proven CHANGED_IRRELEVANT, or completed RELOAD_SAFE continues; latest HARD_BLOCK wins.
- Evidence priority: deterministic gates, static/security, fixtures, reproducible runtime, exact-artifact review, LLM judgment, Builder self-assessment. Conflicting hard evidence is EVIDENCE_CONFLICT.

Human Status Contract:
- After a material state change, output only three concise sections: What's done, What's next, Any blockers.
- Do not expose canonical JSON, recovery journals, or long task transcripts unless the user asks for diagnosis.
- Every ROADMAP_AUDIT report includes one closed min/typical/max estimate revision, confidence={estimate_confidence(data)}, assumptions, and excluded external waiting time. RECORD_REVIEW validates and appends it to estimate_history in the same transaction; ROADMAP_REVISION must not be required merely to persist a final-candidate estimate.
- Show `.codex-loop/STATUS.md`, pending Steering/Decision identity, validation gate, projection freshness, and exact review_surface paths when present.

{adaptive_state_schema_block()}

{roadmap_projection_contract(goals_path, dashboard_path, dashboard)}

Deterministic Runtime Protocol Vocabulary:
- accepted mutation.type values: {' | '.join(_PUBLIC_ADAPTIVE_RUNTIME_MUTATIONS)}
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
    if data.get("state_gateway_mode", "MCP_CANONICAL_WRITER") == "MCP_CANONICAL_WRITER":
        dashboard_line = (
            f"- `{audit_paths['root']}progress-dashboard.html`：只读进度看板，由 Gateway canonical state 派生。"
            if dashboard
            else "- 本次没有触发 HTML 看板；路线图仍可在 `GOALS.md` 查看。"
        )
        return f"""## Adaptive 模式怎么回查

- 发布状态：`beta/experimental`。Gateway、生成器、测试和安装检查只证明本地协议行为；真实 Codex App canary 与正式 Release 仍是单独的验收层。
- 本次运行策略：schema v3 `MCP_CANONICAL_WRITER`。实际角色只有 Controller、当前 Worker、可复用 Reviewer、按需 Local Verifier 和唯一业务 heartbeat；MCP State Gateway 是安装服务，不是一个 State-Writer 任务，Supervisor 也不是产品角色。
- `{audit_paths['state']}` 是唯一 canonical source；`GOALS.md`、`STATUS.md` 和 `LOOP_METRICS.json` 都是派生观察面。状态投影滞后或语义冲突时，以 canonical state 和终态 receipt 为准。
{dashboard_line}
- 正常慢：同一个 SENT outbox 有活跃 Worker/Reviewer 或新证据；只观察，不重复派发。传输退化：绑定当前 host turn 和已登记 heartbeat 的真实 observation 记录同一指纹、outbox、时间和自然-heartbeat 身份；两次自然 heartbeat 或累计 15 分钟后进入 `WAITING_TRANSPORT_RECOVERY`，仅在真实 pause 后读回 PAUSED 才投影 heartbeat PAUSED 并通知用户一次。真正终态：只有 `FINALIZATION_ACKED` 或经证据支持的 `LOOP_BLOCKED`，旧终态不可复活。
- 每条产品路线固定为 `PREPARE_ROUTE -> runtime_codec MATERIALIZE_DISPATCH -> 一次 App send -> RECORD_ROUTE_SENT -> 角色 STAGE_REPORT -> ACK_ROUTE_RESULT`。目标角色 stage 后，bridge 会按同一 SENT outbox 和报告 digest 固化只读、root-confined 的目标身份 attestation；Controller 只能派生并校验，不能作为 Gateway 参数提供。丢失 stdout/任务索引但已有 staged report 时，用 `REPORT_RECOVERY` ACK 原 outbox；绝不为补报告创建第二个产品 dispatch。
- Worker PASS 后的顺序是 Code Review、必要 Local Verification、Roadmap Audit；最终候选还需 Final Audit、`PREPARE_FINALIZATION`、真实 heartbeat PAUSED readback 和 `ACK_FINALIZATION` 才到达 `FINALIZATION_ACKED`。Gateway 只接纳同一 Goal、当前 Worker dispatch、当前 artifact 和 PASS 正式报告的三重绑定。
- `CAPTURE_COMPLETE_DIFF` 由 runtime 原样读取/反向校验 Git binary diff；模型不应在消息里搬运 patch bytes。`LOOP_METRICS.json` 可显示每 Goal 的总时长、已观测 Worker 窗口、控制面等待、拒绝和消息故障，但不是第二 canonical。
- schema v1/v2 State-Writer 仅兼容读取；迁移到 v3 必须在暂停且静默安全点显式 `MIGRATE_V2_TO_V3`。从已终态 predecessor 继续时，在全新 root 使用 `INITIALIZE_SUCCESSOR`，保留 predecessor 原样。
- 需要用户决定时只回复 Decision Card 中的 decision id 和 option id。卡片的批准仅覆盖列出的预授权动作，不包含 exclusions。"""
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
- `{audit_paths['root']}STATUS.md`：普通用户状态页，只看 What's done / What's next / Any blockers、state version、最近任务观察、待处理 Steering/Decision 和验证缺口；它落后时以 `LOOP_STATE.md` 为准。
{dashboard_line}
- `{audit_paths['state']}` 还应能回查 `goal_definition_registry`、`goal_execution_ledger`、`controller_goal_outbox`、`controller_lease`/已消费 lease id 和三阶段 assurance identity；缺少这些不是完整 Adaptive 初始化。
- 长任务超过 lease TTL 时，应看到 `SAME_OWNER_LEASE_RENEWED`、原 `SENT` outbox 的新 claim 和未变化的 dispatch/payload identity；不应出现第二次发送。
- Worker/Reviewer/Local 必须在自己的目标任务内、最终回复穿过 App transport 前，把报告交给 installed MCP `runtime_codec` operation `STAGE_REPORT`。Worker PASS 的新验证文件还必须以 `evidence_sources` 绑定已登记 worktree 内的精确 source path、目标 path、digest 与 media type；不得用 send evidence 代替验证。最终只返回 ASCII-safe `FORMAL_REPORT_STAGED` handle；Controller 只原样转发其中 `.codex-loop/report-staging/` 只读 regular non-symlink 报告/证据 handle、真实 digest、media type 和 ACK-ready result，永不读取或搬运 REPORT/验证 bytes。不得 inline 搬运、手写 staging 文件或自行计算 digest。归档后 canonical `report_digest` 必须等于 `.codex-loop/reports/` 中对应 `application/json` 文件的实际 SHA-256；`PENDING_CONTROLLER_ARCHIVE` 不能直接进入状态。State-Writer 必须让 runtime 在 ACK 前解析报告并把顶层 dispatch/Goal/milestone/roadmap/target/payload/artifact/decision/source identity 与当前 SENT outbox 精确绑定；嵌套字段不能补齐缺失的顶层身份。
- 代码审查、路线图审计和最终完整审查复用一个只读审查任务，但会显示为独立派发和独立报告。
- Local Verifier 只在需要真实浏览器、本机权限、模拟器、设备或账号状态时创建。
- 自动只读子代理策略为 `{data.get('delegation_policy', 'disabled')}`；配置上限为 {data.get('max_read_only_subagents', 0)} 个、全程最多 {data.get('max_read_only_subagent_runs', 0)} 次运行。当前确定性路由每个 lease 只串行运行一个 sidecar，不承诺同时并发；它们只做短时搜索/归类，正式角色仍是同一项目下可回查的真实任务。
- 正常顺序：实现报告 ACK -> 代码审查 ACK -> 必要的本机验证 ACK -> 路线图审计 ACK -> GOALS 投影 ACK -> 切换唯一 Active milestone；最后一个里程碑还要经过最终完整审查 ACK 和独立终态写入 ACK。
- `ROADMAP_CHANGE_REQUIRES_APPROVAL` 表示新计划扩大了原始授权；`CONTROLLER_GOAL_CONFLICT` 表示当前任务已有不匹配的 Goal；`WAITING_CONTROLLER_LEASE` 表示另一个 Goal/heartbeat 回合正在安全路由。
- 每次状态变化只看 `What's done / What's next / Any blockers`；需要底层排障时再查看事件、事务和任务报告。
- 运行中可直接说“现在做到哪了”“先暂停”“恢复同一个 loop”“新增约束：...”“纠正：...”。状态查询不改变任务；暂停只在可验证安全点完成；约束和纠正不会静默修改已发送的 Worker payload。
- 需要用户决定时只回复 Decision Card 中的 decision id 和 option id。卡片的批准仅覆盖列出的预授权动作，不包含 exclusions。
- 如果 Goal 声明 review_surface，按 STATUS 中的路径/本地预览和问题检查；它只证明所列用户产物，不替代代码审查、部署或生产验收。"""
