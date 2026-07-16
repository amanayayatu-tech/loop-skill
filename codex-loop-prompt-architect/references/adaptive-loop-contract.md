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
- `controller_pack_history`, `controller_pack_revision`, and Pack enforcement
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
- `controller_turn_enforcement` and `consumed_controller_turn_ids`
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
- `run_control`, `steering_queue`, `steering_ledger`, and `active_steering_id`
- `pending_decisions`, `failure_history`, and `failure_policy`
- `context_freshness_ledger`
- `validation_requirements`, `validation_results`, and exact evidence identity
- `validation_gate_status` and `status_projection_target`

`schema_version: 2` is the current format. Existing v1 state changes only
through `MIGRATE_V1_TO_V2` with its exact source digest. The migration is a
locked, journaled, CAS-protected transaction with no external actions; ordinary
reads do not migrate. Repeating an applied migration is idempotent, while an
unknown version or changed source digest is a zero-side-effect rejection.

Every post-initialize request attests the active `controller_pack_digest`.
Different Pack bytes use a journaled `PREPARE_CONTROLLER_PACK_MIGRATION` then
`MIGRATE_CONTROLLER_PACK` protocol. Prepare requires `PAUSED_AT_SAFE_POINT`, no
lease or route-reserving PREPARED/SENT/ACKED outbox, all five role identities,
and an exact PAUSED readback of the registered heartbeat. The target prompt is
a root-confined regular source file archived at the runtime-derived
`HEARTBEAT_PROMPT.<target-pack-sha>.txt` path; the runtime computes its digest
from strict UTF-8, LF-only bytes with no trailing newline. A caller-supplied
prompt digest is forbidden. Prepare records both Pack identities, the prompt
path/digest contract, source routing-gate value, role-registry digest, and the
same automation id before any external update. Commit accepts only a second PAUSED
readback of that same automation id, target Controller, schedule, and target
prompt digest; it then archives the digest-versioned Pack, appends immutable
predecessor history, and records a completion receipt. A mismatch stays paused
and must either converge to the target or use
`ROLLBACK_CONTROLLER_PACK_MIGRATION` after readback proves the old prompt was
restored. Migration never rewrites the historical ACKED automation outbox;
rollback restores the journaled source routing-gate value exactly. No
replacement heartbeat is allowed.

`RECORD_HEARTBEAT_OBSERVATION` binds exact readback JSON into canonical state.
STATUS v3 uses only this live observation; absence is
`UNKNOWN_NOT_OBSERVED`. Canonical PAUSED plus live ACTIVE is a safety fault,
while canonical RUNNING plus PAUSED is an intentional reconciliation gap.
After a committed migration, RESUME requires target PAUSED readback and routing
remains blocked until the same heartbeat has a target ACTIVE readback. The
native Controller Goal keeps its launch identity in Pack history; changed but
unmigrated bytes have no routing authority.

### Native Controller Goal generation recovery — DEFERRED/UNAVAILABLE

This release does not expose lost native Goal generation recovery. Generated Packs, the standalone runtime CLI, and the MCP route bridge fail closed as `NATIVE_GOAL_GENERATION_RECOVERY_UNAVAILABLE` with `side_effects=NONE`. Legacy recovery fields remain readable only so historical canonical state and blocker receipts are not destroyed or reinterpreted.

When required-mode reconciliation finds `NATIVE_CONTROLLER_GOAL_IDENTITY_LOST`, keep canonical state unchanged, keep the exact heartbeat PAUSED, send no business route, and do not create or substitute a Goal, Controller, thread, session, State-Writer, or heartbeat. Existing BLOCKED receipts remain BLOCKED evidence; they are never a release PASS.

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

Every stdin mode uses one bounded frame reader: 30 seconds of wall-clock time,
a 4 MB byte ceiling, and strict UTF-8. JSON/state/report modes return as soon as
one complete top-level object is available, without waiting for EOF; payload
verification accepts its existing envelope-plus-JSON framing. Closed-pipe EOF
remains compatible. Strict JSON rejects duplicate keys, non-finite numbers,
multiple frames, and trailing garbage. Timeout, size, and encoding failures return structured
`INPUT_TRANSPORT_TIMEOUT`, `INPUT_TRANSPORT_TOO_LARGE`, and
`INPUT_TRANSPORT_UTF8_INVALID` responses with nonzero exit status.

The App invocation contract applies to every mode, not only materialization:
launch the runtime itself by direct argv with `tty:false`, then write one compact
JSON frame exactly once (or no stdin for `--recover`). Never start a stdin
helper, PTY configurator, fixed-byte reader, heredoc, or shell pipeline first.
A yielded session may only be polled by its same id; success requires process
exit, no live session, and one JSON response. Pack validation evaluates each
executable clause: a negative phrase cannot mask a later affirmative unsafe
command, and only an explicitly `non-executable` code fence is excluded.

#### Resource-bounded observation and validation

Observation is projection-first. Before reparsing unchanged canonical bytes,
Controller compares the canonical `LOOP_STATE.md` mtime/size and projected
`STATUS.md` state version. It parses canonical state after an observed change,
when an expected artifact remains unresolved, and before every mutation.
`STATUS.md` is a derived observation surface and never mutation authority.

After a send, the observation order is canonical mtime/version, expected
artifact, compact projected fields, then a compact State-Writer task read only
if unresolved. Controller itself is read only for phase completion, a blocker,
or a Decision. Each target permits one in-flight
`read_thread(threadId=..., turnLimit=1, includeOutputs=false)` call. Tool results
are reduced internally to status, timestamps, item types, and the final bounded
agent message; raw results and long transcripts are not forwarded. Unchanged
work uses 30/60/120-second backoff, reset only on an observed change. Aggressive
fixed polling and shell busy waits are invalid.

Validation evidence is reusable only when artifact digest, command,
environment/toolchain identity, and relevant config/lockfile digest all match.
Narrow changes run narrow tests. Full fuzz, coverage, and install run once for
the final artifact; an equivalent full local gate is not duplicated while CI
is already running for the same commit.

Runtime and external processes retain the direct non-PTY, same-session
contract. Stdin modes must use an exposed process API that launches direct argv
and supplies a writable non-PTY stdin pipe; a native child-process spawn meets
that requirement. A shell execution API that closes stdin before the same-session
write is ineligible, and temporary-file redirection is not a substitute. A local
child owned by the current turn is cleaned up with bounded
TERM, wait, KILL, and waitpid steps, followed by a residual-process check. A
completed external result whose stdout was lost is recovered from its durable
receipt; stdout loss never authorizes another external call. These constraints
change no storage, schema, state, migration, repair-limit, or public completion
semantics.

The same runtime is also the only dispatch payload codec. Controller submits one
strict JSON object with exactly `envelope_type` and `payload` to
`adaptive_state_runtime.py --payload-materialize`; the payload contains one
`dispatch_payload_digest` whose value is the literal
`PAYLOAD_DIGEST_PLACEHOLDER`. Invoke the runtime directly with `tty:false`,
write one compact JSON frame once, and never interpose `dd`, `stty`, a fixed-byte
reader, heredoc, or shell pipeline. Success requires `exit_code=0`, no remaining
`session_id`, and stdout containing exactly one `PAYLOAD_MATERIALIZED` object.
If a session is yielded, poll only that session until completion; never start a
substitute. At deadline, wait for the bounded runtime to fail closed and map the
result to `PAYLOAD_MATERIALIZATION_TRANSPORT_TIMEOUT`. Only a successful
`PAYLOAD_MATERIALIZED` may be persisted and sent. Its `transport_text` is the
exact task-message body. A receiver passes the
exact received `codexDelegation.input` unchanged to
`--root <absolute repo root> --payload-verify` and acts only on
`PAYLOAD_VERIFIED`. Runtime alone may normalize CRLF to LF and remove at most
one trailing newline before strict JSON parsing and semantic canonicalization.
The digest survives those transport-framing differences, while HTML/XML entity
substitution or any field/value change still fails. `PAYLOAD_BYTES_VERIFIED`
proves only canonical bytes; the
public verify path additionally requires the matching canonical SENT outbox,
pre-PREPARE state snapshot, lease route, target task, and Goal/review/local
identity. Neither side manually replaces substrings, preserves
a `sha256:` prefix, adds angle brackets, reserializes transport, or hashes a UI,
XML, or `<codex_delegation>` wrapper.

State-Writer must not hand-write canonical state/events/journals. It resolves
the runtime interpreter only from the exact installed
`[mcp_servers.codex-loop-state]` command/args readback, verifies that the bridge
and runtime share the installed skill root, and never falls back to ambient
`python3`. Missing runtime, interpreter identity, schema, or `jsonschema` yields
`STATE_RUNTIME_UNAVAILABLE`; a structured
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
set, explicit `native_goal_policy`, and empty ledgers/outboxes. The policy enum
is `disabled|advisory|required`; new inputs default to `required`, and an omitted
legacy state value is interpreted as `required`. After `LOOP_INITIALIZED`, every startup action
uses a fresh `ACQUIRE_LEASE`; it atomically counts the routing turn and returns
the one-route claim. No separate wake-start mutation exists.
Historical ACKED terminal states without nested capability fields remain readable.
A historical PREPARED finalization without them fails closed as
`FINALIZATION_CAPABILITY_MIGRATION_REQUIRED` and cannot authorize an adapter call.

The `INITIALIZE` Controller Pack artifact uses `source_path` to the frozen local
Pack file inside the canonical root plus its attested digest. The runtime reads
and archives those bytes directly after rejecting symlinks, path escape,
non-UTF-8 data, or digest mismatch. Never transport the Pack as inline artifact
`content`, Base64, wrapper text, or decoded HTML/XML entities. Other immutable
formal report artifacts must not use inline `content`. The exact specification
`{"outbox_id":ID,"result":{"status":STATUS,"artifact_digest":DIGEST},"report_text":EXACT_JSON_TEXT}`
is constructed and sent by Worker/Reviewer/Local inside its own target task to
installed `adaptive_state_runtime.py --root CANONICAL_ROOT --report-stage`
before its final App reply. Only
`FORMAL_REPORT_STAGED` is usable. Runtime infers the canonical SENT outbox,
validates strict UTF-8/JSON framing without reserialization, and returns the
runtime-computed exact-byte digest, byte count, media type,
ACK-ready result, and a regular non-symlink read-only `source_path` under the
root-confined non-canonical staging directory `.codex-loop/report-staging/`.
State-Writer accepts only such helper-produced files and runtime archives them
under `.codex-loop/reports/`. The formal role returns only the ASCII-safe handle;
Controller only forwards it and never reads, copies, parses, or transports
REPORT bytes. The same outbox identity may be restaged after
an archive failure without re-executing product work.

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
Every `MARK_OUTBOX_SENT` binds at least one immutable `application/json` send
observation already archived or atomically archived by that mutation; empty,
duplicate, unarchived, or digest-mismatched evidence is rejected.
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

Before any child task, native Goal, heartbeat, or state mutation, the initial
Controller launch input must carry one launcher-supplied
`PACK_IDENTITY_ATTESTATION` binding the absolute on-disk Pack path, exact byte
length, lowercase SHA-256, and parent `create_thread` observation. Controller
independently hashes that local file. `codex_delegation.input`, XML/HTML entity
forms, UI/read-thread previews, and transport wrappers are never Pack bytes and
must not be hashed or decoded as an identity workaround. A missing or mismatched
attestation stops `PACK_IDENTITY_ATTESTATION_REQUIRED` or
`CONTROLLER_PACK_TRANSPORT_IDENTITY_UNRESOLVED` with zero child-task, Goal,
heartbeat, and canonical-state side effects.

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

## Native Controller Goal Adapter

The Controller's persistent milestone Goal is an external adapter distinct from
canonical execution truth and Worker Dispatch Goals. `native_goal_policy`
controls it: `required` uses the exact native Goal lifecycle and requires its
receipt for final closeout; `disabled` and `advisory` use the existing
`EMULATED_SINGLE_ACTIVE_MILESTONE` control-plane representation and make no Goal
tool call. Neither policy may be silently promoted or downgraded.

When policy is `required` and `get_goal`, `create_goal`, and `update_goal` are exposed:

1. For create/read and nonterminal milestone transitions, acquire the fenced
   Controller lease. After FINALIZE/STOP, do not acquire another lease: the exact
   returned terminal closeout capability is the fence and authorization.
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
   `PREPARED -> create once -> SENT -> ACKED`. In required mode, unavailable
   tools leave external sync pending and cannot be promoted to
   `FINALIZATION_ACKED`. Disabled/advisory direct-ACK PREPARED as
   `EMULATED_SINGLE_ACTIVE_MILESTONE`; never mark that path SENT.
6. A cross-milestone `ROADMAP_REVISION` may transition the old Goal only after
   all Goals in that milestone are `COMPLETE`/`RETIRED`; a same-milestone sibling
   never closes it. This nonterminal transition uses a source-bound GOAL UPDATE
   outbox: native is `PREPARED -> update once -> SENT -> ACKED`, while emulated
   direct-ACKs PREPARED without a Goal call. After
   `FINALIZE_LOOP_APPLIED`/`STOP_LOOP_APPLIED`, terminal state accepts only
   `ACK_FINALIZATION`: do not prepare a GOAL UPDATE. Required policy calls
   `update_goal` once under the returned one-use capability; disabled/advisory
   make no Goal call; both return that capability plus Goal/heartbeat
   observations to `ACK_FINALIZATION`.
7. Runtime rejects every Worker dispatch unless canonical `controller_goal` is
   `ACTIVE` or `EMULATED_SINGLE_ACTIVE_MILESTONE` for that exact Active
   milestone. When `ROADMAP_REVISION` changes the Active milestone, obey
   `COMPLETE_CURRENT_CONTROLLER_GOAL`: ACK old Goal completion, create/ACK the
   new milestone Goal, then dispatch. A same-milestone sibling returns
   `PREPARE_NEXT_GOAL_OUTBOX` and retains the existing Goal. `FINALIZE_LOOP`
   enforces the same binding.
8. Use `blocked` only after runtime `STOP_LOOP` validates its declared basis:
   three distinct observations for a general blocker, deterministic repair
   exhaustion when Decision Cards are disabled, or an applied user stop
   Decision bound to exact response Steering.
   Task read, indexing, message-send, or transport timeouts while a
   PREPARED/SENT outbox reserves the route are recoverable
   `WAITING_ACTIVE`/`WAITING_QUOTA_RECOVERY`, never hard-block observations and
   never grounds for `update_goal(status=blocked)`. Only the exact one-use
   closeout capability returned by `STOP_LOOP_APPLIED` authorizes that external
   action. Poll the same task in the
   same active turn, or same-owner renew and rebind only that exact outbox when
   TTL requires it.
9. A required human Decision in `PENDING` is expected waiting, not a hard
   blocker. When `REGISTER_DECISION` returns `WAIT_DECISION`, pause the exact
   heartbeat, preserve the native Goal unchanged, and end the turn. Resume the
   heartbeat only after one real matching `DECISION_RESPONSE` is durably
   applied. Never call `update_goal(status=blocked)` for Decision waiting;
   native Goal blocking requires `STOP_LOOP_APPLIED` plus its matching one-use
   BLOCKED closeout capability.
10. In required mode, reconcile native Goal identity before every resume or new
    route. `goal:null` or unacknowledged `COMPLETE` is
    `NATIVE_CONTROLLER_GOAL_IDENTITY_LOST`. An asynchronous same-identity
    `blocked` readback may continue only through one
    `RECORD_CONTROLLER_GOAL_RESUME` for that current Goal: a fresh Goal-turn
    lease atomically binds strict pre-blocked readback, later explicit user
    `SAME_GOAL_RESUME`, and post-resume same-identity `blocked` readback in the
    order pre < authorization <= post. It records
    `controller_goal_resume_receipt`, consumes the lease, and changes no Goal,
    outbox, or external-action state. It never calls or implies create/update,
    ACTIVE, a new attempt, or a new milestone. Duplicate receipts fail; ACKing a
    later milestone's valid Goal CREATE clears the prior receipt. Without that
    exact three-artifact receipt, pause the heartbeat and send nothing.

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
Adaptive generation also computes a terminal-reachability floor from the
routable Goals and milestones, declared repair limit, just-in-time formal
tasks, required Local Verification, CODE_REVIEW/ROADMAP_AUDIT/FINAL_AUDIT, and
FINALIZE_LOOP. `max_wakeups` below that floor is non-dispatchable even when its
wall-clock heartbeat coverage would otherwise be long enough. The floor covers
the declared bounded repair path; it does not authorize extra work or side
effects.
The lease records a monotonically increasing `lease_epoch`, never-reused id, owner kind,
owner task/turn identity, acquisition/expiry time, and intended transition.
Reusing the same id with another owner does not transfer ownership. A competing
turn returns `WAITING_CONTROLLER_LEASE` and sends nothing. Expired takeover
requires trustworthy current time plus structured `read_thread` evidence for
the exact owner task, increments the epoch, and fences every old action.
Controller sends acquisition and takeover only through the configured
`route_state_mutation` MCP tool and omits `controller_turn_id` from model
arguments. The bridge verifies that its direct parent is the OpenAI-signed Codex
app-server, reads Codex-owned top-level MCP `params._meta` outside tool
arguments, parses `x-codex-turn-metadata`, requires metadata `thread_id` to
equal outer request `threadId`, and only then injects the real `turn_id`.
Metadata `session_id` is required as the trusted
session-tree identity but may legitimately differ from `thread_id` after a fork
or resume; it never substitutes for `turn_id`. State-Writer, direct CLI, shell, inline Python, JSON,
argv, environment variables, task titles, timestamps, and model-generated UUIDs
are not route-attestation channels. Runtime indexes the canonical ledger by the
attested turn and rejects a second lease from that same App turn even after
completion or voluntary release. Missing or invalid host metadata returns
`BLOCKED_BY_APP_ATTESTATION` with zero canonical side effects. All non-route
mutations continue through the existing State-Writer. Repository tests prove
the bridge boundary synthetically; release claims still require the real App
two-route canary.

Installation atomically registers exactly one `codex-loop-state` stdio server.
Its command is a stable absolute Python executable and its sole argument is the
installed `adaptive_state_mcp.py`; shell wrappers, source-worktree paths,
temporary paths, env/cwd overrides, disabled registrations, duplicates, and
identity conflicts fail closed. The installer preserves the previous TOML
bytes, restores config and the prior skill after interruption/failure, and
emits a schema-validated manifest binding the installed bridge SHA, config
readback, exact repo identity when the source is clean, and zero source/install
drift. A dirty source is `UNVERIFIED_SOURCE`, never the current HEAD by proxy.

Release acceptance is local to the current main Mac. It binds one exact SHA and
tracked-tree digest to targeted/full tests, all-shipped branch coverage, both
5000-case fuzz lanes, isolated install/rollback, security/risky-artifact checks,
zero source/install drift, and the real Codex App receipt. The structured
receipt uses `evidence_layer=local-main-mac`; it never claims independent-host,
remote-attestation, or cross-host proof. Historical remote results are not
inherited by a new candidate.
The receipt binds App version/build/bundle, app-server executable/signature/
CDHash, MCP protocol/config/requestMeta shape, registration identity, same-turn
second-route rejection before side effects, next-turn success, partial-frame
cleanup, lost-stdout no-retry recovery, Pack/same-heartbeat reconciliation, and
canonical `FINALIZATION_ACKED`. Any compatibility identity change invalidates
the old receipt. GitHub Actions and synthetic tests are compatibility evidence,
not this local release gate; the repository does not claim to repair app-server
process reaping upstream.

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
An applied scoped correction may bypass the Local PASS prerequisite only for a
`ROADMAP_AUDIT` that proposes a never-reused replacement Goal, and only when the
same Goal, Worker dispatch, artifact digest, and roadmap version already have an
acknowledged Local `FAIL` or `BLOCKED` record. Roadmap Revision then preserves
the original attempts and marks the source Goal `RETIRED`; it never upgrades the
old Goal or Local result to PASS. Without that exact non-PASS evidence, the
ordinary Local PASS gate remains mandatory.
Before a metered external call or Local Verification, the canonical SENT LOCAL
outbox must carry one `external_call_authorization`: `receipt_id`, action kind,
provider, model, request digest, call index, and a confined result artifact path.
Both receipt phases additionally
bind loop, active Pack, Goal, local dispatch/outbox, lease/routing turn, target
role/thread, and start time. `COMPLETED` also binds completion time, exact
STARTED digest, result status, process exit code, immutable read-only artifact
path/digest, and usage. Runtime rejects a missing/mismatched route, provider,
model, request, call index, target, artifact, or Pack without writing a receipt.
Stage `STARTED` before provider send and `COMPLETED` before stdout. A replayed
COMPLETED is recovered without provider retry. A lone/replayed STARTED returns
`EXTERNAL_CALL_OUTCOME_UNKNOWN`, conservatively consumes one call, and forbids
retry. PASS requires exit 0; token arithmetic must agree, and unknown tokens
remain null with `complete=false`. Receipts contain no prompt, response, key,
Authorization value, or secret. Pre-contract historical receipts remain
immutable legacy/unverified audit evidence and cannot prove PASS, exact usage,
or retry permission.

Digest mismatch errors have a closed provenance contract and never use the
ambiguous `expected` / `actual` pair. Caller assertions use
`provided_digest` / `computed_digest`; artifact-ledger readback uses
`ledger_digest` / `computed_file_digest`; canonical-state comparisons use
`state_digest` / `mutation_digest`; and Pack comparisons use
`canonical_pack_digest` / `loaded_pack_digest`. Every such error also contains
`algorithm=sha256`, `encoding=UTF-8`, the exact `byte_length` hashed, and
`side_effects=NONE`. Callers must interpret those named sources literally and
must not reverse them based on error-code wording.
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

Every Roadmap Audit report carries a closed min/typical/max estimate revision,
confidence, assumptions, and excluded external waits. `RECORD_REVIEW` validates
and stores it on the assurance record while appending it to `estimate_history`
in the same transaction, including on the final-candidate path where no
`ROADMAP_REVISION` follows. A schema-v2 FINAL_AUDIT is not dispatchable unless
that exact estimate is the latest history entry and every required review
surface has a current artifact-bound user response. Its assurance record stores
the exact CODE_REVIEW and ROADMAP_AUDIT ids plus a digest over current
validation, required Decision, estimate history, freshness, Worker, and review
identities. `FINALIZE_LOOP` requires the same upstream ids and recomputes that
digest, rejecting cross-chain or post-audit context changes with zero effects.

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
runtime alone may normalize CRLF to LF and remove at most one trailing newline
before strict JSON semantic canonicalization; entity or field changes still fail.
The byte-only helper status is not execution permission. Outbox, sent envelope, receiver report, and assurance identity
repeat the runtime-returned digest; model prose never implements the algorithm.
If only local capture or CLI framing is uncertain, keep the same SENT outbox and
return `PAYLOAD_VERIFICATION_RETRY_REQUIRED`. Retry verification locally in the
same target/task/dispatch/payload identity, renewing only that exact same-owner
route when TTL requires it. Do not execute, stage a business BLOCKED report,
ACK, consume repair, resend, or create a new dispatch. Only after proving the
exact App-delivered semantic payload is invalid and `execution_started=false`
may the target task self-stage a zero-effect BLOCKED formal report to close the
SENT outbox. If product work completed but report staging/archive failed,
self-restage the same report identity and ACK the new handle; never re-execute
work or MARK_OUTBOX_SENT twice.
The bounded state snapshot is frozen immediately before `PREPARE_OUTBOX`.
PREPARE and SENT advance canonical state, so a receiver validates
`prepared_state_version == snapshot.state_version + 1`, current SENT status, and
unchanged roadmap/Goal/lease/target/payload/definition or artifact identity. It
does not require the embedded snapshot version to equal the later latest state.
For `non_git`, report `current_branch`, `base_sha`, and `head_sha` as the exact
string `NOT_APPLICABLE`, never null or empty. `changed_files` uses repo-relative
POSIX paths; before/after manifests and `diff_sha256` carry artifact identity.
Every Worker `PASS` report also carries one machine-replayable
`complete_diff_reference`. `MANIFEST_DELTA_V1` is UTF-8 text containing exactly
`STATUS<TAB>repo-relative-path<TAB>size_bytes<TAB>file_sha256` per line, with
`A`, `M`, or `D` status, unique path ordering, and one final LF. Its SHA-256
must equal `diff_sha256`, and every non-deleted file entry must match the
current regular non-symlink file. `NO_DIFF` uses the SHA-256 of empty bytes,
empty `changed_files`, and equal before/after snapshots. `PATCH_FILE_V1` names
a root-confined regular non-symlink diff artifact whose bytes hash to
`diff_sha256`. `FAIL` and `BLOCKED` reports remain archivable without this
review handoff so a zero-effect failure can still close a SENT outbox.
Worker, Reviewer, and Local Verifier build one strict JSON `report_text` inside the
target task, without fences or trailing prose, whose `report_digest` value is
the literal `PENDING_CONTROLLER_ARCHIVE`. That same role invokes
`--report-stage` before replying and returns only the ASCII-safe
`FORMAL_REPORT_STAGED` handle. Only its helper-produced
`.codex-loop/report-staging/` source path, digest, media type, and ACK-ready
result may be supplied to State-Writer. Controller never reads or transports
REPORT bytes, writes staging bytes, or computes its SHA-256. Formal
report key order, whitespace, CRLF/LF, and Unicode bytes remain unchanged;
`provided_report_digest`, when supplied, is only a checked assertion. Formal
DISPATCH/ASSURANCE/LOCAL `ACK_OUTBOX` results
contain status, archived report digest, and artifact digest. Each ACK rejects
unless exactly one evidence-path artifact has that digest and media type.

For a new or explicitly migrated Pack, a Worker `PASS` report carries exactly
one closed `validation_results` item for every Validation Matrix dimension with
`required=true`. Each item contains `dimension`, `status=PASS`, the current
`worker_dispatch_id` and `artifact_digest`, plus `evidence_path`,
`evidence_digest`, and `evidence_media_type`. The evidence must already exist in
the immutable artifact ledger and appear in the report evidence set. The Worker
ACK atomically replaces that Goal's validation results and evidence identities,
refreshes the gate, completes the outbox, and consumes the route. Missing,
duplicate, unknown, non-required, stale-artifact, or unarchived evidence rejects
the complete ACK with no canonical side effect. `RECORD_VALIDATION` remains for
legacy Pack compatibility and independent validation performed after Worker ACK;
it is not part of the new Pack's normal Worker PASS route.
Reviewer `ACK_OUTBOX` and review acceptance remain separate facts. The ACK makes
the exact report durable and leaves the assurance route reserved. The following
`RECORD_REVIEW` may carry one closed `freshness_observation`; runtime derives its
checkpoint/Goal/dispatch/artifact binding from the review mutation, validates
the observation, reopens the canonical report, checks the required validation
gate, and commits freshness, assurance ledger, Goal projection, outbox
completion, and lease consumption in one journal transaction. A failure at any
stage commits none of them. A different request id with the same completed
review/report/artifact returns the existing closeout receipt without another
event; changed identity returns `REVIEW_ID_CONFLICT` with no side effect.
`RECORD_REVIEW` carries zero artifacts and repeats the exact sole canonical ACK
report path; runtime reopens that immutable artifact through `artifact_ledger`,
rechecks its bytes/digest/media type, and parses it again without Controller
reading or retransmitting report bytes.
The runtime parses every formal report before ACK. It binds the top-level
dispatch, Goal, milestone, roadmap, target task, payload, artifact, decision,
and source identities to the current SENT outbox. For Reviewer reports,
`source_worker_dispatch_id`, `source_worker_report_digest`, `worker_thread_id`,
and `source_artifact_digest` are mandatory top-level fields; a matching value
only inside `state_change_request`, findings, or evidence metadata is not a
substitute. A malformed or mismatched report is a zero-side-effect rejection and
cannot move an assurance outbox to ACKED. For a Worker `PASS`, the runtime
validates `complete_diff_reference`, current file state, validation results, and
evidence paths before staging and again before ACK. Every `.codex-loop/**`
evidence ref must already exist byte-identically in `artifact_ledger` with its
matching record path and an explicit canonical media type. The ACK stores a safe
`latest_worker.review_handoff` projection containing the exact artifact
identity, complete reference, validation results, evidence refs, and its
canonical projection digest. The projection contains no formal report bytes.
A `CODE_REVIEW` payload must copy `artifact_identity` and `evidence_refs` from
this projection unchanged; payload verification rejects a missing projection,
substitution, or digest mismatch.
`RECORD_REVIEW` must repeat the exact decision, report digest, and artifact
digest accepted by `ACK_OUTBOX`. A completed assurance outbox and its one
assurance-ledger entry must remain one-to-one and identity-consistent;
canonical state with a conflicting pair is rejected before any mutation.
Worker payload materialization uses the latest applicable freshness record's
`context_state_digest` for `context_freshness_snapshot`, never its
`observed_identity_digest`. Review payloads reuse canonical
`latest_worker.review_handoff` unchanged; Controller never opens the report or
substitutes a newly computed content/prose digest.
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
That union includes Worker FAIL or product-execution BLOCKED, code-review repair, Local Verification FAIL,
Roadmap Audit repair, and Final Audit repair; all consume the same per-Goal
budget.
Every new Worker result records `execution_started`. A deterministic
control-plane BLOCKED closure may set it false only with a runtime-approved
top-level `blocker_code`. Report staging binds both fields into the ACK-ready
result even if the caller omitted them there. Such a closure remains in immutable attempt history but consumes
no initial or repair slot. Historical results without the field keep legacy
counting semantics.

The deterministic zero-execution blocker set is closed and machine-checked
against runtime plus both public schemas:

<!-- ZERO_EXECUTION_BLOCKER_CODES_START -->
- `DISPATCH_FRESHNESS_SNAPSHOT_MISMATCH`
- `DISPATCH_VALIDATION_MATRIX_MISMATCH`
- `INPUT_TRANSPORT_TIMEOUT`
- `INPUT_TRANSPORT_TOO_LARGE`
- `INPUT_TRANSPORT_UTF8_INVALID`
- `PAYLOAD_MATERIALIZATION_TRANSPORT_TIMEOUT`
- `PAYLOAD_VERIFY_FAILED`
- `REPORT_STAGING_FAILED`
<!-- ZERO_EXECUTION_BLOCKER_CODES_END -->
If an older ACK dropped a report's explicit zero-execution classification,
`RECONCILE_WORKER_EXECUTION_CLASSIFICATION` is allowed only at
`PAUSED_AT_SAFE_POINT` with no lease or active outbox. It re-reads the exact
canonical report path and digest, validates the approved blocker code, and
corrects only the existing attempt/latest-worker classification without
deleting history, clearing counters, or changing Controller Pack identity.
The state machine enforces `max_repair_attempts_per_goal` and emits
`REPAIR_BUDGET_EXHAUSTED` at the limit. The generated default is five repairs
beyond the initial execution; explicit inputs remain bounded to 0–20. Once the
limit is reached, no additional Worker dispatch is valid. With Decision Cards
enabled, Controller registers one stable card containing only stop-on-current-
evidence and remain-paused-for-scoped-correction, then pauses the exact
heartbeat. Without Decision Cards, the next dedicated Goal turn may use
`stop_basis=DETERMINISTIC_REPAIR_BUDGET` directly. A scoped correction must be
recorded as applied Steering and audited through `ROADMAP_REVISION`; it retires
the exhausted Goal, uses a new Goal id, and preserves the old definition,
attempt ledger, and repair counter.
Roadmap revisions replace the canonical Validation Matrix for the revised Goal
set, discard results whose requirements changed, and recompute the global
validation gate after retirement status is applied and before routing the next
Goal. Retired Goals do not block validation or review-surface acceptance.

Adaptive completion still requires an actual Worker PASS plus per-Goal
CODE_REVIEW, required local verification,
`ROADMAP_AUDIT_PASS_FINAL_CANDIDATE`, and tagged FINAL_AUDIT. State-Writer then
applies a separate `FINALIZE_LOOP` CAS that reconciles the complete registry and
execution ledger and rejects every unexecuted non-retired/non-superseded Goal,
rejects any PREPARED/SENT/IN_PROGRESS Worker, assurance, or Local Verifier outbox,
completes only the final evidenced Goal/milestone, retires the resolved queue,
refreshes projections, sets terminal status, and writes a PREPARED
`finalization_outbox` and returns the only one-use capability that may authorize
the external Goal COMPLETE action. Controller applies `native_goal_policy`,
pauses the exact heartbeat, and submits `ACK_FINALIZATION` with the observations
required by runtime. `CORE_FINALIZATION_ACKED` denotes deterministic core
closeout only; `FINALIZATION_PENDING_EXTERNAL_SYNC` denotes an outstanding
adapter receipt. Neither is release success. Runtime binds exact observation
digests to `finalization_receipt`; `FINALIZATION_ACKED`, not FINALIZE_LOOP or
either intermediate status, remains the closeout gate.
`FINAL_REVIEW_PASS_WITH_LIMITATION` maps only to
`LOOP_COMPLETE_WITH_LIMITATION`; it cannot be upgraded to full completion.
If the exact native Goal is absent or terminal without an ACKED canonical Goal
transition, the Controller must stop before `FINALIZE_LOOP`. A prepared
finalization outbox never authorizes Goal recreation or a fabricated
`{"status":"COMPLETE"}` observation.

An unrecoverable blocker follows a different terminal transaction. Every
`STOP_LOOP` declares one `stop_basis`. `THREE_OBSERVATIONS` preserves the
general hard-block safeguard: on each natural Goal turn, Controller archives
one strict observation in that turn's observation-only `RELEASE_LEASE`
transaction. Runtime accepts this basis only when exactly three distinct
artifacts already bind the three immediately preceding genuine consecutive
completed Goal turns at each release's exact state version. None can be
attached to or backfilled by the STOP request. `DETERMINISTIC_REPAIR_BUDGET`
requires a runtime-proven exhausted Goal and Decision Cards disabled.
`USER_DECISION` requires the same exhausted Goal plus one applied
`STOP_LOOP_CONFIRMED` option, its context digest, and the exact response
Steering. These deterministic bases do not spend three observation turns and
cannot authorize another repair. Fewer, repeated, mismatched, or fabricated
identities are pure rejection. Controller submits STOP on a dedicated Goal
turn with a fresh lease only after every external outbox is closed.
Runtime sets `LOOP_BLOCKED`, blocks the active milestone, supersedes future work,
retires unresolved Goals, and prepares a BLOCKED finalization outbox without any
PASS claim. On that dedicated STOP turn, only the exact one-use capability
returned by `STOP_LOOP_APPLIED` may authorize marking the required-mode native
Goal BLOCKED; disabled/advisory use the emulated transition. Controller then
pauses the exact business heartbeat and never deletes it before evidence-bound
ACK. Before eligibility it releases nonterminally and never manufactures wakeups.
Once Goal=BLOCKED and
automation=PAUSED are both exact observations, `ACK_FINALIZATION` records the
blocked receipt. Until then the receipt remains pending, but the business
heartbeat must not remain ACTIVE.

Queued worktree creation may return `pendingWorktreeId` or `clientThreadId`
depending on the App build. Both must be reconciled to a durable `threadId`.
Read-only subagent calls must use the actually exposed tool schema rather than
hard-coded arguments from another App version.
