# Adaptive Codex Loop Contract

Use this reference only when `coordination_mode=adaptive`. Standard Mode keeps
the existing fixed Goal Queue contract and generated fixture behavior.

## Contents

1. Mode boundary
2. Roadmap and canonical state
3. Native Controller Goal
4. Controller lease
5. Review and roadmap audit
6. Local verification
7. Read-only subagents
8. Human status and dashboard
9. Recovery and completion

## Mode Boundary

Output mode (`compact`, `full`, `minimal_patch`) and coordination mode
(`standard`, `adaptive`) are independent.

Adaptive input requires:

- an explicit reason
- structured Workers with `role_kind`
- one or more structured milestones
- exactly one `ACTIVE` milestone
- every executable Goal mapped to a `milestone_id`
- at least one dependency-free Goal for the initial `ACTIVE` milestone
- Local Verifier, subagent, and dashboard policies

Role kinds are `implementation`, `code_reviewer`, `state_writer`,
`local_verifier`, `triage`, and `explorer`. A Local Verifier or generic Auditor
must never accidentally satisfy the code-review gate.
Auto-injected formal roles use deterministic collision-free names. Revalidate
both normalized role names and thread placeholder slugs after injection.

## Roadmap And Canonical State

`LOOP_STATE.md` remains the only canonical state. Adaptive state adds:

- `controller_pack_identity`
- `dashboard_required`
- `roadmap_version`
- `milestones`
- `active_milestone_id`
- `goal_definition_registry`
- `goal_execution_ledger`
- `authorization_envelope`
- `roadmap_change_outbox`
- `controller_goal`
- `controller_goal_outbox`
- `controller_lease`
- `routing_turn_count`
- `routing_turn_ledger`
- `lease_epoch_counter`
- `consumed_controller_lease_ids`
- `assurance_ledger`
- `assurance_dispatch_outbox`
- `goal_queue_history`
- `roadmap_projection`
- `local_verification_queue`
- `local_verification_outbox`
- `estimate_history`
- `delegation_ledger`
- `subagent_attempt_ledger`
- `artifact_ledger`
- `finalization_outbox`
- `finalization_receipt`

### Deterministic State Runtime

Adaptive Controller emits `STATE_MUTATION` plus one strict JSON request. The
State-Writer passes those exact bytes on stdin to the installed
`scripts/adaptive_state_runtime.py --root <absolute repo root>` and relays the
single JSON response unchanged. Request and canonical state are validated by
`adaptive-mutation.schema.json` and `adaptive-state.schema.json`.

The runtime, not model prose, owns state-version CAS, request/event idempotency,
the file lock, temp-file/fsync/atomic-rename sequence, append-only events,
PREPARED/APPLIED journals, crash recovery, leases, outboxes, `GOALS.md`, the
conditional dashboard, immutable Pack/report artifacts, `ROADMAP_REVISION`,
`FINALIZE_LOOP`, `STOP_LOOP`, and `ACK_FINALIZATION`. It never invokes external App tools.
Controller performs a prepared external action only after an applied runtime
response and returns the observation through a new typed mutation.

The same runtime is also the only dispatch payload codec. Controller submits one
strict JSON object with exactly `envelope_type` and `payload` to
`adaptive_state_runtime.py --payload-materialize`; the payload contains one
`dispatch_payload_digest` whose value is the literal
`PAYLOAD_DIGEST_PLACEHOLDER`. Only `PAYLOAD_MATERIALIZED` may be persisted and
sent. Its `transport_text` is the exact task-message body. A receiver passes the
exact received `codexDelegation.input` unchanged to
`--root <absolute repo root> --payload-verify` and acts only on
`PAYLOAD_VERIFIED`. `PAYLOAD_BYTES_VERIFIED` proves only canonical bytes; the
public verify path additionally requires the matching canonical SENT outbox,
pre-PREPARE state snapshot, lease route, target task, and Goal/review/local
identity. Neither side manually replaces substrings, preserves
a `sha256:` prefix, adds angle brackets, reserializes transport, or hashes a UI,
XML, or `<codex_delegation>` wrapper.

State-Writer must not hand-write canonical state/events/journals. Missing
runtime, schema, or `jsonschema` yields `STATE_RUNTIME_UNAVAILABLE`; a structured
rejection never authorizes a prose fallback. A rejected request leaves state,
events, journals, outboxes, and external-action count unchanged.
Normal apply is also forbidden from recovering an earlier incomplete
transaction as a side effect: it returns `RECOVERY_REQUIRED`. State-Writer must
invoke the explicit `--recover` path, relay that structured result, reread
canonical state, and only then accept the next mutation.

Bootstrap is ordered and crash-recoverable: deterministically recover/create the
one State-Writer before state exists; apply one `INITIALIZE` CAS containing the
exact parsed milestone array, Goal definition registry/queue, closed
authorization envelope, project id, Pack digest/artifact, real Controller and
State-Writer ids plus bootstrap digests, dashboard policy, local-verification
set, and empty ledgers/outboxes. After `LOOP_INITIALIZED`, every startup action
uses a fresh `ACQUIRE_LEASE`; it atomically counts the routing turn and returns
the one-route claim. No separate wake-start mutation exists.

Heartbeat identity uses the exact UTF-8 body between its BEGIN/END delimiter
lines, excluding the LF adjacent to each delimiter. That same no-trailing-LF
string is passed to `automation_update.prompt` and hashed for the PREPARED
outbox. Persisted readback may normalize CRLF/CR to LF only; trimming or adding
another newline is an identity conflict.

Every control-plane outbox uses a closed identity. A task binds `project_id`,
`task_kind=PROJECT_TASK`, the exact generated `bootstrap_role_kind`, its
deterministic `formal_role_kind`, exact bootstrap prompt digest, and
local/worktree environment; its ACK repeats those values and adds the real
`thread_id` and `worktree_path`. Runtime accepts that path only under the
canonical repo or one explicit
`authorization_envelope.control_plane_limits.allowed_external_worktree_roots`
entry. It also enforces the lifetime `max_child_threads` cap and one registered
task per formal/bootstrap role key. The mapping is closed:
`implementation|triage|explorer -> WORKER`, `code_reviewer -> REVIEWER`, and
`local_verifier -> LOCAL_VERIFIER`. Titles and keyword inference are never
runtime identity. A heartbeat binds deterministic name,
`kind=HEARTBEAT`, real Controller target, rrule, prompt digest, and
`LF_NORMALIZED_NO_TRAILING_NEWLINE`; its ACK repeats them and adds the real
automation id with `ACTIVE`; runtime allows at most one non-cancelled business
heartbeat. A native Goal binds action, loop/Pack/milestone/objective identities
and the exact marker; update also binds Goal id and target status. Native
Thread, Automation, and Goal ACKs attach exactly one immutable strict JSON
`CODEX_TOOL_RESULT` observation binding outbox kind/id, payload digest, target
id, and the complete exact tool result. Emulated Goal ACKs instead require the
corresponding `GOAL_TOOL_UNAVAILABLE` observation. Missing, extra, or changed
observation fields are pure rejections.

Outbox lifecycles are kind-specific: Worker and Local are
`PREPARED -> SENT -> COMPLETED`; Assurance is
`PREPARED -> SENT -> ACKED -> RECORD_REVIEW -> COMPLETED`; native Goal,
Automation, Thread, and Delegation are `PREPARED -> SENT -> ACKED`; an emulated
Goal direct-ACKs `PREPARED` and never claims SENT. Every kind also has the one
safe cancellation branch `PREPARED -> CANCELLED`; SENT work is never cancelled.
`IDEMPOTENT_REPLAY` is a successful no-change runtime response, not a new state.

Every formal task bootstrap is identity-bearing input. `ROLE_KIND` is the exact
literal from its generated `Role Kind:` line; never infer it from display Role,
title, slug, or hyphen/underscore conversion. Marker value is exactly
`LOOP_ID|ROLE_KIND|PACK_SHA256`. `ROLE_PROMPT_TEXT` is the exact UTF-8 text
inside the matching `ROLE_PROMPT_BEGIN/END` Markdown fence. `BOOTSTRAP_PROMPT`
is exactly `ROLE_PROMPT_TEXT + "\n\nBOOTSTRAP_MARKER: " + marker_value +
"\nBOOTSTRAP_ONLY"` with no trailing LF. A Pack path, heading, line range,
excerpt, summary, or loader instruction cannot replace it. Its digest is lowercase
`sha256:<64 hex>` over the exact bytes; truncated hashes are invalid. If
Controller creates a task with a nonconforming prompt before state exists, that
loop identity stops as `E2E_PROTOCOL_VIOLATION` without sending `STATE_MUTATION`
or creating a replacement task.

`create_thread` success remains the pending identity if an immediate
`read_thread` returns not found. Codex App task indexing may be eventually
consistent, so Controller retries the same returned `threadId` after 1, 2, 4,
8, and 16 seconds and reconciles the marker between attempts. It never creates
a replacement during that window. A readable identity mismatch is
`E2E_PROTOCOL_VIOLATION`; an id still unreadable after the full window is
`THREAD_IDENTITY_PROPAGATION_TIMEOUT` and remains unresolved for later recovery.

That timeout covers only an unreadable/not-found task id. If `read_thread`
already resolves the expected project/cwd but the initial turn is still
active/pending with no materialized prompt or READY reply, the task is
`WAITING_BOOTSTRAP_ACTIVE`, or `WAITING_QUOTA_RECOVERY` when quota/service
capacity is indicated. Controller keeps the same id nonterminal, polls with
backoff, does not count idle, and neither writes state nor creates a replacement.
Only a completed/error/shutdown turn whose bootstrap cannot be verified becomes
`THREAD_BOOTSTRAP_FAILED`.

The Controller must also resolve its own real project-task `threadId` before
State-Writer creation. A `codex_delegation` `source_thread_id` is the upstream
parent task, never the current Controller. Reconcile recent project tasks using
the exact Pack digest, canonical repo path, and matching launch payload; zero or
multiple exact candidates stop as `CONTROLLER_THREAD_ID_UNRESOLVED`. Canonical
`thread_registry` records both Controller and State-Writer. Every routing turn,
lease, native Goal mapping, heartbeat target, and takeover read binds
`owner_identity` to that exact Controller `threadId` string. A deterministic
loop-id fallback can aid search but cannot act as a recoverable lease owner.

`.codex-loop/GOALS.md` is a derived projection with state and roadmap versions,
digest, timestamp, Active milestone, and one section per milestone. State-Writer
regenerates it from canonical state after a CAS mutation; edits to the Markdown
never mutate canonical state.

Milestones contain id, outcome, scope, decisions, blockers, required evidence,
status, dependencies, and references. While nonterminal, exactly one milestone
is Active.

Roadmap changes begin with an acknowledged `ROADMAP_AUDIT` report and then use a
separate `ROADMAP_REVISION` mutation; no roadmap PREPARED mutation or outbox
exists. A non-final `ROADMAP_AUDIT_PASS` or `ROADMAP_CHANGE_PROPOSED` report
contains one closed `roadmap_proposal` plus its canonical digest. The proposal
binds proposal/audit ids, base roadmap version, typed operations, next Goal,
reason, `within_authorized_envelope`, and component digests for the complete
proposed milestones, future Goal Queue, Goal definitions, authorization
envelope, and estimate. The report separately binds source Worker/code/local
identities and immutable report/artifact digests. `ROADMAP_AUDIT_PASS` asserts
`within_authorized_envelope=true`; `ROADMAP_CHANGE_PROPOSED` asserts false and
routes to `ROADMAP_CHANGE_REQUIRES_APPROVAL`, never directly to a revision.
State-Writer recomputes every component digest, typed operation diff, and the
authorization check against canonical state; caller booleans and digests are
assertions, not authority. The only operation enum is
`ADD_MILESTONE`, `UPDATE_MILESTONE`, `REORDER_FUTURE_MILESTONES`, and
`SUPERSEDE_MILESTONE`; lowercase aliases are invalid.

Every future Goal Queue entry has exactly `goal_id`, `milestone_id`,
`roadmap_version`, `status` (`READY` or `PLANNED`), and `depends_on`. Reject
unknown or cyclic dependencies, retired/rebound ids, and a nonterminal revision
without a dependency-satisfied `READY` Goal for the one Active milestone.

The queue is routing data, not an executable payload by itself. Every entry must
resolve through `goal_definition_registry` to an immutable definition containing
worker role plus exact `worker_role_kind`, objective, success criteria, validation, write scope, phase
permissions, dependencies, dispatch condition, and a full SHA-256 template
digest. New Goal ids require complete definitions; existing definitions cannot be
silently rewritten.
At initialization, every non-retired definition for an ACTIVE or PLANNED
milestone appears exactly once in the queue. Definition scopes reject `..`,
`.codex-loop`, URLs, and traversal before any dispatch can be prepared.

State-Writer rechecks the frozen Worker/code/local/audit identities immediately
before applying. A newer Local Verification FAIL/BLOCKED invalidates a pending
proposal. Before revision, Controller cancels every obsolete prior-version
`PREPARED` Worker, Assurance, or Local Verifier outbox through its own
`CANCEL_OUTBOX` transaction and ACK. `ROADMAP_REVISION` rejects any remaining
versioned `PREPARED`, `SENT`, ACKED Assurance, or in-progress record with
`CANCEL_PREPARED_OUTBOX_FIRST` or the corresponding active-work code; it never
silently cancels an outbox inside the revision CAS. After those separate
cancellations, State-Writer applies the exact audited milestones, future Goal
Queue, Goal definitions and execution ledger, roadmap version, estimate, and
projection digest in one CAS transaction. Completed dispatch history and
evidence remain immutable.
A normal RoadmapRevision cannot set terminal status.

One milestone may contain multiple dependency-ordered Goals. A revision may
complete the evidenced Goal and unlock a sibling while keeping the milestone
Active. Unexecuted siblings block only an attempted milestone completion.

Any objective, path, permission, connector, budget, production, secret,
evidence, or claim expansion becomes `ROADMAP_CHANGE_REQUIRES_APPROVAL` before
mutation. Approval is phase-specific and cannot be inferred from unrelated
ledger entries.

## Native Controller Goal

The Controller's persistent milestone Goal is distinct from Worker Dispatch
Goals.

When `get_goal`, `create_goal`, and `update_goal` are exposed:

1. Acquire the fenced Controller lease.
2. Read the existing Goal.
3. Build and recognize the stable objective marker
   `[CODEX_LOOP_MILESTONE loop_id=<LOOP_ID> pack_sha256=<FULL_64_HEX_SHA256> milestone_id=<ID> objective_sha256=<FULL_64_HEX_SHA256>]`
   as the final line with no trailing prose.
4. Persist `PREPARE_OUTBOX(kind=GOAL, action=CREATE)` with that identity before
   the tool call. Recover an Active or blocked Goal only when the real objective
   marker and either canonical mapping or the exact PREPARED/SENT/ACKED outbox match. The
   marker alone is not recovery authority. A cross-loop/pack marker is a
   conflict. Do not expect Goal tools to return custom fields.
5. Create a Goal only when no unfinished Goal exists. Native registration uses
   `PREPARED -> create once -> SENT -> ACKED`. If tools are unavailable, attach
   one immutable JSON observation and direct-ACK PREPARED as
   `EMULATED_SINGLE_ACTIVE_MILESTONE`; never mark that path SENT.
6. Complete it only after an applied cross-milestone `ROADMAP_REVISION` proves
   every Goal in the old milestone `COMPLETE` or `RETIRED`, or after
   `FINALIZE_LOOP`/`STOP_LOOP` prepares the exact terminal closeout target. A
   same-milestone sibling never closes the Controller Goal. Persist a
   source-bound GOAL UPDATE outbox before `update_goal`: native transitions use
   `PREPARED -> update once -> SENT -> ACKED` and include the strict tool-result
   observation; emulated transitions direct-ACK PREPARED with the strict
   unavailability/transition observation. Only then replace the canonical
   mapping or create the next Goal.
7. Runtime rejects every Worker dispatch unless canonical `controller_goal` is
   `ACTIVE` or `EMULATED_SINGLE_ACTIVE_MILESTONE` for that exact Active
   milestone. When `ROADMAP_REVISION` changes the Active milestone, obey
   `COMPLETE_CURRENT_CONTROLLER_GOAL`: ACK old Goal completion, create/ACK the
   new milestone Goal, then dispatch. A same-milestone sibling returns
   `PREPARE_NEXT_GOAL_OUTBOX` and retains the existing Goal. `FINALIZE_LOOP`
   enforces the same binding.
8. Use `blocked` only after runtime `STOP_LOOP` validates three distinct
   evidence artifacts for the last three genuine consecutive Goal turns with
   one exact blocker code/fingerprint and Controller Goal identity.

Marker and canonical/outbox identity validation precede recovery for every
returned Goal status, including `complete`; an ACKED transition cannot
authenticate an unrelated completed Goal.

The tools do not imply programmatic UI pause, resume, edit, or clear support.
When tools are absent, use `EMULATED_SINGLE_ACTIVE_MILESTONE` and never claim
native Goal Mode.

`controller_goal_token_budget` is the only value that may become
`create_goal(token_budget=...)`. The global metered-runtime `token_cap` remains
one loop-wide budget and is never duplicated across milestones.

## Controller Lease

Goal turns and heartbeat wakes first consume one shared, bounded routing-turn
counter, then share one CAS-protected `controller_lease`. Native Goal
continuations therefore cannot bypass `max_wakeups`; exhaustion records
`ROUTING_BUDGET_EXHAUSTED` and stops external routing.
The lease records a monotonically increasing `lease_epoch`, never-reused id, owner kind,
owner task/turn identity, acquisition/expiry time, and intended transition.
Reusing the same id with another owner does not transfer ownership. A competing
turn returns `WAITING_CONTROLLER_LEASE` and sends nothing. Expired takeover
requires trustworthy current time plus structured `read_thread` evidence for
the exact owner task, increments the epoch, and fences every old action.

Except for initialization, counted routing-turn creation, and lease
acquisition/takeover itself, every Adaptive
state request and external-action outbox carries the full claim:
`lease_epoch + lease_id + owner_kind + owner identity + intended_transition`.
It also carries trustworthy `observed_at`; the transition is exactly
`ROUTE_ONE_TRANSITION`. Epoch-only, wrong-purpose, expired, consumed, released,
or mismatched claims are rejected. One lease reserves exactly one route action:
one native Goal action, one external outbox, one `ROADMAP_REVISION`, or
`FINALIZE_LOOP` or `STOP_LOOP`. Its terminal ACK/CAS consumes the lease; every later action
acquires a fresh counted lease. Recovery may rebind only that one unfinished
route and never combines Goal plus dispatch actions.
Failed identity/time probes do not mutate logical time. A PREPARED send ACK
must carry the claim stored on that record. Takeover/renewal rebinds the exact
unfinished record and reserves its route before sending; voluntary release is
rejected while any matching PREPARED/SENT route or assurance ACK awaiting
RECORD_REVIEW remains.
Every mutation also carries a fresh trustworthy `observed_at`. Validate all ids
and inputs before mutation and roll back the complete state on rejection. A
`ROADMAP_AUDIT` report ACK is the durable structured proposal. Controller
validates that acknowledged proposal and submits one dedicated
`ROADMAP_REVISION` CAS. If its lease expires
before the CAS, renew or take over only the lease and reuse the same audit
identity instead of inventing another proposal state.
If the exact same Controller task is still Active but its transaction approaches
or crosses TTL, `SAME_OWNER_LEASE_RENEWED` uses `ACTIVE_SAME_OWNER` evidence,
keeps the routing turn, and rotates to a new lease id/epoch. It may atomically
rebind the one exact matching `PREPARED`, `SENT`, or assurance-`ACKED` record,
including a long-running Worker/review/local dispatch. Renewal changes only the
routing authorization claim: payload, target, dispatch/report identity, status,
and the original dispatch claim embedded in the immutable identity remain
unchanged, and no external action is resent. Reject mismatched ownership,
changed canonical claims, unrelated records, or ambiguous multi-route recovery.
It never fabricates `STALE`.
Renewal and takeover evidence must each bind exactly one `application/json`
artifact. Its parsed object must exactly equal the mutation evidence fields
other than its path and digest; prose, summaries, and partial thread-id matches
are rejected.
Each routing-turn record binds its original `event_id`. Exact replay changes no
counter, ledger, version, or budget; reuse for another turn is rejected before
mutation.

## Review And Roadmap Audit

Reuse one real read-only Reviewer task. Do not create a permanent Auditor.

Per milestone order:

1. Worker PASS dispatch/report/artifact and State-Writer ACK
2. `CODE_REVIEW` dispatch, report, and ACK
3. required Local Verifier dispatch, report, and ACK
4. `ROADMAP_AUDIT` dispatch to the same Reviewer, report, and ACK
5. roadmap change or no-change decision and ACK
6. GOALS/dashboard projection and ACK
7. Controller Goal completion/activation
8. one next Worker dispatch, or tagged `FINAL_AUDIT` for the final candidate

CODE_REVIEW must name the completed source Worker dispatch and exact Worker
report digest; it must be the Goal ledger's latest Worker PASS artifact, so any
repair invalidates older assurance. Each review first uses an exact
`assurance_dispatch_outbox` PREPARED/SENT record; without it the report cannot
be ACKED, and its send uses the claim stored on that outbox. Code review checks
the exact diff. `REVIEW_PASS_WITH_LIMITATION` is a typed pass only when every
limitation is explicit, evidence-bounded, and leaves no unresolved required
fix; preserve it through later assurance and claim boundaries.
`REVIEW_ARTIFACT_UNAVAILABLE` is an ACKable non-PASS blocker.
Roadmap Audit checks whether the milestone is
really complete, whether its evidence definition still holds, and whether the
next milestone remains correct. Neither may pass from Worker prose alone.
All three assurance stages use a tagged `/review` union and separate reports.
`FINAL_AUDIT` is dispatched to the same Reviewer only after the final
`ROADMAP_AUDIT_PASS_FINAL_CANDIDATE`. State ACK identity is
`review_kind + milestone_id + roadmap_version + review_dispatch_id + source
artifact digest`; no field may be reused across a changed revision or artifact.
Read-only/no-diff milestones still use `CODE_REVIEW` with `artifact_kind=NO_DIFF`
before the independent Roadmap Audit and final audit.
Review lookup binds the current Worker dispatch and report as well as the
artifact digest, so a same-digest repair cannot reuse an older PASS.

## Local Verification

Create a real Local Verifier task just in time only for evidence unavailable to
the checkout, such as authenticated browsers, extensions, local credentials,
macOS permissions, Xcode/simulators, physical devices, or hardware.

Bind every dispatch to exact artifact identity and a stable verification id,
persist an exact `local_verification_outbox` PREPARED/SENT record, and send it
only after matching CODE_REVIEW ACK. Reports also bind milestone
id, roadmap version, Goal id, local dispatch id, real target task id, report
digest, full lease claim, and source artifact digest. FAIL returns to the implementation Worker and must
retest the same verification id. If repair changes the artifact digest, the old
CODE_REVIEW ACK is stale: review the repaired artifact, then retest. Never send
credentials or sensitive local evidence to remote Workers.
`REVIEW_NEEDS_REPAIR`, Local Verification FAIL,
`ROADMAP_AUDIT_NEEDS_REPAIR`, and `FINAL_REVIEW_NEEDS_REPAIR` share one closed
repair-source union and the same per-Goal repair budget.

## Read-Only Subagents

Delegation defaults to `disabled`. Only an input that explicitly supplies a
non-disabled policy, concurrency ceiling, lifetime run cap, retry cap, and input
exposure policy may authorize it. The ceiling may be at most two, but the
deterministic router currently serializes one active `DELEGATION` outbox per
lease. It does not promise simultaneous execution. These depth-one explorer
sidecars are only for disposable search, log grouping, test-failure triage, or
summarization within those limits.

This authorization belongs only to the Controller. State-Writer,
implementation Worker, Reviewer, and Local Verifier tasks must do their formal
work directly and must never spawn subagents or create, fork, or message other
formal tasks. A sidecar cannot delegate further. A formal role that cannot
finish directly returns exact blocker evidence to the Controller.

Discover the current App's collaboration/subagent tool name and schema at
runtime. Use only fields it actually exposes; do not hardcode a tool name or
copy `agent_type`/`fork_context` from another App build.

They cannot write, approve, dispatch, mutate state/roadmap, call paid/external
services, or replace formal project tasks. Each has stable exploration and
attempt ids. Before spawning, Controller acquires one fresh lease and prepares
`outbox_kind=DELEGATION` with prompt/scope digests, source Goal/roadmap identity,
and max depth 1. After exactly one spawn it marks that outbox SENT. State-Writer
ACKs it only while atomically archiving one immutable `application/json` result
whose digest equals `report_digest`. Only a COMPLETED and ACKED result may become
evidence; INTERRUPTED/DROPPED reports are terminal diagnostics. The attempt
ledger enforces concurrency, lifetime-run, and retry caps. `agent_id` never
enters `thread_registry`.
Missing subagent tools are not a formal-loop
blocker; continue without the optional sidecar.

## Human Status And Dashboard

After material changes, Controller outputs only:

- What's done
- What's next
- Any blockers

Generate `.codex-loop/progress-dashboard.html` when required by policy, when
there are more than three milestones, or when the maximum estimate exceeds the
configured threshold. It is derived, static, escaped, script-free, and has no
mutation controls or external assets. Embedded state/roadmap identities make a
stale copy detectable, and runtime recovery rewrites a missing or stale file.

After every Roadmap Audit, append min/typical/max, confidence, assumptions, and
excluded external waits to `estimate_history`.

## Recovery And Completion

Heartbeat reads the trusted pack snapshot, canonical state, GOALS digest, and
registered tasks. Its `ACQUIRE_LEASE` request is the shared counted routing turn
and lease acquisition. Replays use
stable event/request/dispatch/proposal ids and never increment or apply twice.

Every Worker, Reviewer, and Local Verifier envelope carries a canonical
`payload_digest` plus the full claim including `routing_turn_id`. After every
other runtime field is typed and materialized, Controller invokes
`--payload-materialize`, persists the returned digest, and sends the returned
`transport_text` unchanged. The receiver invokes
`--root <absolute repo root> --payload-verify` on the exact received body. The
byte-only helper status is not execution permission. Outbox, sent envelope, receiver report, and assurance identity
repeat the runtime-returned digest; model prose never implements the algorithm.
The bounded state snapshot is frozen immediately before `PREPARE_OUTBOX`.
PREPARE and SENT advance canonical state, so a receiver validates
`prepared_state_version == snapshot.state_version + 1`, current SENT status, and
unchanged roadmap/Goal/lease/target/payload/definition or artifact identity. It
does not require the embedded snapshot version to equal the later latest state.
For `non_git`, report `current_branch`, `base_sha`, and `head_sha` as the exact
string `NOT_APPLICABLE`, never null or empty. `changed_files` uses repo-relative
POSIX paths; before/after manifests and `diff_sha256` carry artifact identity.
Worker, Reviewer, and Local Verifier final answers are one strict JSON object,
without fences or trailing prose, whose `report_digest` value is the literal
`PENDING_CONTROLLER_ARCHIVE`. Controller validates required fields and duplicate
keys, serializes sorted-key compact UTF-8 JSON (`ensure_ascii=false`, no trailing
newline), archives that exact `application/json` artifact, and supplies its real
SHA-256 to State-Writer. Formal DISPATCH/ASSURANCE/LOCAL `ACK_OUTBOX` results
contain status, archived report digest, and artifact digest; each ACK and every
`RECORD_REVIEW` reject unless exactly one evidence-path artifact has that digest
and media type.
The runtime parses every formal report before ACK. It binds the top-level
dispatch, Goal, milestone, roadmap, target task, payload, artifact, decision,
and source identities to the current SENT outbox. For Reviewer reports,
`source_worker_dispatch_id`, `source_worker_report_digest`, `worker_thread_id`,
and `source_artifact_digest` are mandatory top-level fields; a matching value
only inside `state_change_request`, findings, or evidence metadata is not a
substitute. A malformed or mismatched report is a zero-side-effect rejection and
cannot move an assurance outbox to ACKED.
`RECORD_REVIEW` must repeat the exact decision, report digest, and artifact
digest accepted by `ACK_OUTBOX`. A completed assurance outbox and its one
assurance-ledger entry must remain one-to-one and identity-consistent;
canonical state with a conflicting pair is rejected before any mutation.
For upgrade compatibility only, `RECORD_REVIEW` may migrate an older already-
ACKED assurance whose `result` is exactly null or empty. It derives the three
result fields from the typed review mutation, validates the same report and
outbox identities, and stores the result in that transaction. Any nonempty
invalid result remains a rejection.

Dispatch recovery matches `dispatch_id + payload_digest + target_thread_id +
Goal definition digest + worker_role_kind`. The target task's registered
`bootstrap_role_kind` must equal the immutable Goal definition and payload role;
formal `WORKER` alone cannot substitute implementation, triage, or explorer.
The loop may have only one nonterminal Worker
dispatch across revisions. A selected Goal must itself be `READY` with completed
dependencies. Worker PASS closes it to redispatch; only a matching
acknowledged failure from the closed repair-source union may authorize a bounded
repair attempt.
That union includes Worker FAIL or BLOCKED, code-review repair, Local Verification FAIL,
Roadmap Audit repair, and Final Audit repair; all consume the same per-Goal
budget.
The state machine enforces `max_repair_attempts_per_goal` and emits
`REPAIR_BUDGET_EXHAUSTED` at the limit.

Adaptive completion still requires an actual Worker PASS plus per-Goal
CODE_REVIEW, required local verification,
`ROADMAP_AUDIT_PASS_FINAL_CANDIDATE`, and tagged FINAL_AUDIT. State-Writer then
applies a separate `FINALIZE_LOOP` CAS that reconciles the complete registry and
execution ledger and rejects every unexecuted non-retired/non-superseded Goal,
rejects any PREPARED/SENT/IN_PROGRESS Worker, assurance, or Local Verifier outbox,
completes only the final evidenced Goal/milestone, retires the resolved queue,
refreshes projections, sets terminal status, and writes a PREPARED
`finalization_outbox`. After its ACK, Controller completes the exact native Goal,
pauses the exact heartbeat, archives two distinct `application/json` observations
whose parsed objects are exactly `{\"goal_id\": <canonical id>, \"status\":
\"COMPLETE\"}` and `{\"automation_id\": <canonical id>, \"status\":
\"PAUSED\"}`, and submits `ACK_FINALIZATION`. Runtime binds those digests to `finalization_receipt`;
`FINALIZATION_ACKED`, not FINALIZE_LOOP alone, is the closeout gate.
`FINAL_REVIEW_PASS_WITH_LIMITATION` maps only to
`LOOP_COMPLETE_WITH_LIMITATION`; it cannot be upgraded to full completion.

An unrecoverable blocker follows a different terminal transaction. On each
natural Goal turn, Controller archives one strict observation in that turn's
observation-only `RELEASE_LEASE` transaction containing the
Goal turn id, observed time, blocker code/fingerprint, exact Controller Goal id,
`status="HARD_BLOCK"`, `route_action=null`, and
`release_reason_code="HARD_BLOCK_OBSERVATION_ONLY"`. Runtime accepts
`STOP_LOOP` only when exactly three distinct artifacts already bind the three
immediately preceding genuine consecutive completed Goal turns at each
release's exact state version. None can be attached to, or backfilled by, the
STOP request. An aggregate blocker report binds those prior turn ids. Fewer,
repeated, nonconsecutive, action-bearing, late, or mismatched observations are
pure rejection. Controller submits the eligible `STOP_LOOP` on the next
dedicated Goal turn and a fresh lease, only after every external outbox is
closed.
Runtime sets `LOOP_BLOCKED`, blocks the active milestone, supersedes future work,
retires unresolved Goals, and prepares a BLOCKED finalization outbox without any
PASS claim. On that dedicated STOP turn Controller marks the exact Goal BLOCKED,
pauses the exact business heartbeat, and never deletes it before evidence-bound
ACK. Before eligibility it releases nonterminally and never manufactures wakeups.
Once Goal=BLOCKED and
automation=PAUSED are both exact observations, `ACK_FINALIZATION` records the
blocked receipt. Until then the receipt remains pending, but the business
heartbeat must not remain ACTIVE.

Queued worktree creation may return `pendingWorktreeId` or `clientThreadId`
depending on the App build. Both must be reconciled to a durable `threadId`.
Read-only subagent calls must use the actually exposed tool schema rather than
hard-coded arguments from another App version.
