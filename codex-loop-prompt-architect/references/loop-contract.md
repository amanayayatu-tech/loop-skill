# Codex Loop Contract

Read this reference for Full Mode, automated/multi-round loops, worktree-based
review, paid runtime, or formal scoring. The scaffold script implements these
contracts and its test suite guards the critical invariants.

This file is the Standard execution-control contract. When
`coordination_mode=adaptive`, also read
[adaptive-loop-contract.md](adaptive-loop-contract.md). Adaptive extends this
contract; it never weakens identity, state, review, budget, or permission gates.

## Table Of Contents

- Full Output Contract
- Scoring Anchors
- Structured Input Contract
- Goal Queue And Message Contract
- Durable State And Idempotency Contract
- Thread, Repo, And Worktree Contract
- Review/Audit Contract
- Heartbeat Automation Contract
- Runtime Retry Contract
- Cost, Approval, And Source Contract
- Dispatch Contract
- Flow Map

## Full Output Contract

Full Mode must produce, not merely request, these sections:

1. `Loop Diagnosis`
   - `Law | Status | Issue | Fix`
   - `Loop Integrity Score: X/12`
   - no more than three top hard risks
2. `Revised Codex Loop Prompt Set`
   - Controller Prompt
   - Worker/Reviewer/State-Writer prompts
   - dependency-ordered Goal Queue and First Goal
3. `Runtime And Automation Plan`
   - exact Codex App tool arguments
   - state acknowledgement and heartbeat lifecycle
   - worktree/reviewer artifact mapping
4. `Changelog`
5. `Flow Map`
6. `Test Goals`
   - normal progress
   - hard blocker
   - idempotent replay
   - active Worker heartbeat wake
   - context-compaction-safe later goal
7. `Final Next Step`
   - send the complete Markdown file to one Controller thread
   - do not ask the user to paste individual internal blocks

## Scoring Anchors

Start at 12 and subtract one for each materially violated law. Diagnose every
affected law, but do not double-count one root defect unless it creates separate
operational risks.

| Law | Deduct when |
| --- | --- |
| L1 Role Isolation | Controller writes product/state files, a read-only role writes, or a triage Worker dispatches implementation itself. |
| L2 Addressing | Dispatch uses title, branch, `pendingWorktreeId`, `agentId`, or unresolved placeholder instead of real `threadId` and verified worktree identity. |
| L3 Atomic Goals | Goal lacks a stable id, combines unrelated phases, or no dependency-ordered queue exists for multi-role work. |
| L4 Acceptance First | Goal lacks explicit success criteria or validation before execution instructions. |
| L5 Forbidden Zones | Paths, secrets, side effects, or pre-existing dirty files are not bounded. |
| L6 Termination | Repair, retry, active-stale, wake, or idle paths are unbounded or can stop active work silently. |
| L7 Side Effects | Goal lacks explicit true/false permissions for commit, PR, push, merge, deploy, source promotion, git hygiene, or external writes. |
| L8 Structured Status | Reports omit `goal_id`, `dispatch_id`, real thread/worktree identity, diff identity, exit codes, or next action. |
| L9 Self-Contained Context | A later goal depends on chat history rather than its materialized template and canonical state snapshot. |
| L10 Evidence Boundary | Prompt permits claims above the declared local/smoke/formal/public evidence layer. |
| L11 Durable State | State lacks versioning, queue, inflight dispatch, idempotency keys, ledgers, automation identity, ACK gates, or reconciliation. |
| L12 Review Gate | Reviewer cannot inspect the exact Worker checkout/diff, findings lack file/line evidence, or no final integrated review exists. |

## Structured Input Contract

Ready-to-send output requires these facts:

- objective and acceptance criteria
- repo/root and `repo_mode`: `existing_git`, `new_git`, or `non_git`
- Worker roles, explicit permissions, role-specific ownership, allowed paths
- forbidden paths/actions and pre-existing dirty-worktree boundary
- validation commands as arrays when commands contain shell operators
- evidence layer and claim boundary
- source artifacts as workspace or absolute local paths
- canonical state path
- explicit Goal Queue for more than one dispatch Worker
- review policy
- heartbeat, per-goal repair, and runtime retry limits

Adaptive input additionally requires an explicit reason, structured
`role_kind`, milestones with exactly one Active item, Goal-to-milestone mapping,
and Local Verifier/subagent/dashboard policies. Output detail mode remains
independent from coordination mode.
- cost/call/token policy when metered runtime is requested

Reject, rather than silently normalize:

- duplicate role names
- more than one `state_write_only` role
- writable Reviewer/Judge roles
- permission entries for unknown roles
- invalid or non-positive numeric limits
- unknown structured-input fields
- unsupported evidence or repo modes
- multi-dispatch-worker input without explicit goals
- dependency references to later or missing goals
- relative repo roots, control paths outside repo `.codex-loop/`, writable
  scopes escaping repo, and prose masquerading as a source path

Use JSON arrays for workers, validation commands, acceptance criteria, source
artifacts, and goals. Legacy command strings may split on unquoted semicolons,
but must preserve pipes, `||`, and quoted semicolons.
Reject duplicate JSON keys at any depth instead of accepting last-key-wins
permission, review, or budget changes.
Placeholder-only objective, claim, branch, approval, validation, acceptance,
source, or Goal values are validation errors, not assumptions.

Chinese inputs must trigger the same risk detection as English inputs. Words
such as `fake`, `mock`, or `placeholder` in an objective are not a paid-runtime
policy. Only an explicit positive cap or a bounded `metered_runtime_policy`
authorizes or defers metered work. A policy must defer/forbid execution or name
a positive call/request, token, or dollar bound. Duration alone does not bound
spend. `unlimited` and equivalent wording are invalid.

## Goal Queue And Message Contract

Every goal has:

- `goal_id`
- runtime `dispatch_id`
- phase
- real target `threadId`
- Worker role and permission
- one atomic objective
- success criteria
- validation commands
- allowed write scope
- dependencies and `dispatch_when`
- side-effect permission matrix
- forbidden actions
- evidence and claim boundaries
- stop conditions
- bounded materialized canonical-state snapshot: version, repo/worktree,
  dependencies, approval/budget slices, counters, dirty boundary, claim limits

The permission matrix distinguishes `git_init` and `branch_create` from stage
and commit. A new repository may not infer either permission from a target
branch name.

Controller materializes runtime placeholders before send. Only concrete tokens
use angle brackets; generic families are written as `MATERIALIZE_*`. A Worker
must reject a goal that still contains a runtime materialization token.

Child prompts cannot refer vaguely to rules that exist only in Controller
context. Executable Worker embeds retry policy; Reviewer embeds artifact/review
policy; State-Writer embeds schemas, CAS, idempotency, and recovery journal.

The queue is authoritative:

- dispatch no goal until dependencies and gates pass
- dispatch at most one goal while a state write is unacknowledged
- `TRIAGE_ACTIONABLE` unlocks only matching conditional repair goals
- `TRIAGE_NO_ACTION` skips conditional repair goals without fake review
- a read-only PASS with no diff advances queue directly after state ACK
- queue exhaustion starts `FINAL_AUDIT`, not immediate completion

Minimum Worker completion report:

- status, `goal_id`, `dispatch_id`
- `thread_id`, title, `worktree_path`
- current branch, `base_sha`, `head_sha` when applicable
- before/after snapshot SHA-256 identities when Git SHAs are unavailable
- changed files, `diff_summary`, and `diff_sha256`
- validation items with command, cwd, timestamps, exit code, and log reference
- evidence artifacts
- state change request
- blockers and next action

Minimum Reviewer report:

- all identity fields above
- findings ordered by severity
- title, file, line, evidence, required fix per finding
- reviewed base/head SHA and worktree path
- test gaps and forbidden artifacts
- decision

## Durable State And Idempotency Contract

Use one canonical control-plane location. Relative `.codex-loop/` paths inside a
Worker worktree are not canonical.

Minimum state fields:

- `loop_id`, `state_version`
- repo identity and source artifacts
- current phase
- Goal Queue and status by id
- active goal and inflight dispatch
- baseline/current artifact identity and integration worktree path
- dispatch outbox with target thread, stable payload digest, and
  `PREPARED`/`SENT` lifecycle
- thread-creation outbox with role, environment, bootstrap marker, prompt
  digest, and registered real thread id
- thread registry with real thread ids and worktree paths
- completed/failed goals and blockers
- evidence artifacts
- last processed event and state request ids
- last committed transaction id and PREPARED/APPLIED recovery journals
- repair and runtime retry counters by goal
- wake and consecutive-idle counters
- automation id/status/rrule/last wake
- automation creation outbox, deterministic name, target, and prompt digest
- exact Controller Pack snapshot identity and trusted
  `.codex-loop/sources/CONTROLLER_PACK.md` path
- budget ledger
- approval ledger
- next action and terminal status

`LOOP_STATE.md` contains one canonical strict JSON object between literal
`STATE_JSON_BEGIN` and `STATE_JSON_END` markers. All required keys are present,
unknown top-level keys are rejected, and prose outside the markers is
noncanonical. `LOOP_EVENTS.jsonl` contains exactly one complete JSON object per
line with no Markdown fences or multiline records.
During `LOOP_INITIALIZED`, State-Writer atomically archives the exact Controller
Pack under `.codex-loop/sources/CONTROLLER_PACK.md` and records its SHA-256 in
`controller_pack_identity`. Heartbeat verifies and reads this snapshot after
context compaction; chat history is corroboration, not the sole contract source.

Only State-Writer writes canonical `LOOP_STATE.md`, `LOOP_EVENTS.jsonl`,
`TRIAGE.md`, and `.codex-loop/reports/`. "State-Writer" means the complete
control-plane audit surface, not only one state file.

For crash consistency, State-Writer first atomically writes
`.codex-loop/transactions/STATE_REQUEST_ID.json` as PREPARED with expected
version, event id, and mutation digest. It writes immutable artifacts, atomically
replaces state, appends the event once, then marks the journal APPLIED. Recovery
reconciles state, JSONL, and artifacts and performs only the missing step.

Every `/state_update` contains:

- `controller_approved=true`
- unique `state_request_id`
- unique `event_id`
- `expected_state_version`
- goal/dispatch ids where applicable
- exactly one serialized mutation
- evidence references

Absent canonical state has version 0. Only a `LOOP_INITIALIZED` mutation with
`expected_state_version=0` may create version 1 after confirming no matching
active state exists. Existing state must be reconciled, never overwritten.
Controller-generated request, event, and dispatch ids must match
`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`; State-Writer rejects unsafe identifiers
before using them in journal or report paths.

State-Writer uses compare-and-swap:

- matching version: apply once, increment exactly once, return
  `STATE_WRITE_APPLIED`
- duplicate event/request: write nothing, return
  `STATE_WRITE_ALREADY_APPLIED`
- version mismatch: write nothing, return `STATE_VERSION_CONFLICT`

`last_processed_event_id` and `last_state_request_id` are fast-path cursors,
not a complete dedupe set. Older replays must be checked against retained
request journals and the event JSONL/index before apply.

Controller waits for ACK before review, next goal, final closeout, or another
state mutation. Single-writer policy alone is not enough; event and dispatch
idempotency are mandatory.

Dispatch is a transactional outbox protocol:

1. persist `DISPATCH_PREPARED` with dispatch id, target thread, and payload
   digest; wait for ACK
2. send the exact payload once
3. persist `DISPATCH_SENT`; wait for ACK
4. after interruption at PREPARED, inspect the target thread for that dispatch
   id before deciding whether a resend is needed; page `read_thread` with
   cursors back to the registered bootstrap boundary rather than checking only
   the latest turn
5. a Worker receiving a duplicate dispatch returns the existing report and
   never re-executes the goal

Repair counters are keyed by Goal and survive task replacement. Exhaustion is
`REPAIR_BUDGET_EXHAUSTED`; creating a new Worker cannot reset it.

Event JSONL requires `event_id`, timestamp, actor, real `thread_id`, optional
title, goal/dispatch ids, event type, status, state versions, evidence refs,
state request id, and next action. Title is never a durable identifier.

## Thread, Repo, And Worktree Contract

Use real Codex App project threads:

- `list_projects` to resolve `projectId`
- `list_threads(query=BOOTSTRAP_MARKER)` and `read_thread` to recover a task
  before create/fork
- `create_thread(prompt=BOOTSTRAP_PROMPT, target={type:"project", projectId:PROJECT_ID,
  environment:{type:"local"}})`
- for a worktree, set `target.environment={type:"worktree",
  startingState:{type:"branch", branchName:VERIFIED_BASE_BRANCH}}`
- `read_thread` and `send_message_to_thread` for routing
- `set_thread_archived(threadId=..., archived=true)` only after report/state ACK
- no `multi_agent_v1.spawn_agent`, `agent_type`, `fork_context`, internal
  "智能体", or `agentId` substitution

Compute `PACK_SHA256`, a stable `LOOP_ID`, and role-specific
`BOOTSTRAP_MARKER` values before child creation. Recover or create State-Writer
first and initialize canonical state. Every later Worker/Reviewer uses
`THREAD_CREATE_PREPARED -> THREAD_CREATED/BOOTSTRAPPED -> THREAD_REGISTERED`.
`BOOTSTRAP_PROMPT` is the exact role prompt plus marker and `BOOTSTRAP_ONLY`; it
never contains First Goal. Reconcile list/read results before another create or
fork.
If Controller thread id is unavailable, derive LOOP_ID from project id,
canonical repo, and pack digest. Random fallback ids are forbidden because they
break crash recovery before canonical state is written.

`fork_thread` is permitted for a real Reviewer thread in the same Worker
checkout. It is not `fork_context` and must still produce a durable `threadId`.

Repo modes:

- `existing_git`: record git root, status, HEAD/base SHA, branch, remotes, and
  worktree list before creation; preserve unrelated dirty/untracked files; if
  target differs from base, first writing goal authorizes `branch_create`
- `new_git`: begin with local Worker; do not verify refs or create a worktree
  before git and an initial branch exist; `git_init` and `branch_create` require
  separate explicit permissions in the first writing goal
- `non_git`: use local threads and no branch/ref/worktree requirements; exact
  review identity uses before/after manifests, content SHA-256, and diff SHA-256

For existing git worktrees, verify an existing base ref before using
`startingState.type="branch"`. Otherwise use an approved working-tree start.
Never assume a proposed target branch exists.

Reconcile `pendingWorktreeId` to real `threadId` and `worktree_path` before
dispatch. Materialize all runtime placeholders. Stop with exact evidence on
`DIRTY_WORKTREE_CONFLICT`, `WORKTREE_BOOTSTRAP_BLOCKED`, or
`THREAD_IDENTITY_UNRESOLVED`.

Resolve repo/worktree/source/write targets to canonical real paths before any
write. Symlink or target escape stops `PATH_SCOPE_ESCAPE`.
`.codex-loop/**` is a reserved State-Writer control-plane scope and is invalid
for product Worker/Goal writes.
Fully read-only/no-diff loops may use an empty global `allowed` array; any
`workspace_write` Worker requires a nonempty repo-contained global scope.

Canonical state remains in the control-plane checkout. Controller passes the
needed snapshot to worktree Workers; Workers do not write a parallel state copy.

Use one integration worktree for sequential writing goals and at most one active
writer. Reuse a compatible Worker; a genuinely different execution role may be
created just in time with `fork_thread(..., environment={type:"same-directory"})`
only after the prior writer is idle and its report/state are acknowledged, then
receives the new full bootstrap prompt once. Separate writing worktrees require
an explicit promotion/merge goal and permission; otherwise
`WORKTREE_INTEGRATION_PLAN_MISSING`. Archive completed non-reusable tasks only
after report and state ACK; keep State-Writer available through final ACK.
`max_child_threads` is a lifetime cap excluding Controller and including archived
tasks. At the cap, reuse or stop `THREAD_BUDGET_EXHAUSTED`.

## Review/Audit Contract

Review any code, config, CI/CD, deploy, migration, PR-state, or public-content
diff before PASS.
`workspace_write` and `review not required` are incompatible structured input;
reject the pack. Only a fully read-only no-diff loop may omit code review.

Use the strongest available surfaces:

- dedicated Codex code-review capability when exposed
- exact-artifact read-only Reviewer thread
- GitHub review/status tools when a PR exists and tool-driven operation is in
  scope
- manual diff review only in explicit manual fallback

Artifact mapping:

- never create Reviewer at startup; create it just in time only after a
  reviewable Worker report is durably acknowledged
- local Worker: Reviewer may then use the same project checkout with exact SHAs
- worktree Worker: prefer
  `fork_thread(threadId=WORKER_THREAD_ID, environment={type:"same-directory"})`
- fallback Reviewer: only after proving access to the absolute Worker worktree
  and receiving complete diff identity
- non-git/uncommitted artifact: require before/after manifests, snapshot
  SHA-256, complete patch, and `diff_sha256`; product digest excludes
  `.codex-loop`, declared unrelated pre-existing files, and caches, with a
  separate exclusion manifest; Git SHAs are `NOT_APPLICABLE`
- no exact artifact: `REVIEW_ARTIFACT_UNAVAILABLE`, never report-only PASS

After all per-goal reviews, run `FINAL_AUDIT` over the complete Git base-to-head
or non-git before-to-after snapshot diff, all validation evidence, forbidden
artifacts, unresolved comments, state/event consistency, budget and approval
ledgers, evidence layer, and claim boundary. Only `FINAL_REVIEW_PASS` plus final
state ACK may produce `LOOP_COMPLETE`. A
`FINAL_REVIEW_PASS_WITH_LIMITATION` plus final ACK may produce
`LOOP_COMPLETE_WITH_LIMITATION` only when limitations are explicit,
evidence-bounded, and contain no unresolved required fix.

## Heartbeat Automation Contract

A heartbeat advances one active Controller loop. It is not a substitute for a
long-lived daily/weekly cron. A separate cron requires an exact schedule,
workspace, self-contained prompt, execution environment, activation/stop
policy, and budget; clarify those fields rather than silently folding the intent
into heartbeat.

Use the current Codex App schema explicitly:

```text
automation_update(
  mode="create",
  kind="heartbeat",
  destination="thread",
  status="ACTIVE",
  rrule="FREQ=MINUTELY;INTERVAL=<minutes>" or `FREQ=HOURLY[;INTERVAL=<hours>]`,
  name=HEARTBEAT_AUTOMATION_NAME,
  prompt=HEARTBEAT_PROMPT
)
```

The pack must contain exact `HEARTBEAT_PROMPT_BEGIN/END` text covering state ACK,
dispatch outbox recovery, active/stale handling, queue routing, final audit, and
terminal pause. Controller passes it verbatim.

Omit `targetThreadId` for the current Controller or use its real thread id. Do
not invent `target` or `interval` arguments. Persist the returned automation id
and full configuration before First Goal.

Default budgets:

- interval: 15 minutes
- total wakeups: 192, approximately 48 hours
- consecutive idle wakeups: 8
- active stale threshold: 60 minutes

Custom values override every generated occurrence; never leave a hidden
hardcoded wake limit.

Heartbeat states:

- each wake first reconciles prior pending state, then writes one idempotent
  `HEARTBEAT_WAKE` CAS event derived from automation id and next wake count;
  routing waits for ACK and replay cannot increment twice
- active Worker with recent progress: `WAITING_ACTIVE`, keep heartbeat active,
  no duplicate goal, no idle increment
- active Worker past stale threshold: inspect thread and terminal/process
  evidence, record `STALLED_ACTIVE`, send at most one status probe
- pending state ACK: `WAITING_STATE_ACK`, send nothing else
- no immediate action but inflight/queued work: `WAITING_NO_ACTION`, keep active
- no work and nonterminal: increment idle count; pause only at idle limit
- terminal completion: persist terminal state, then update heartbeat to PAUSED
- total wake budget exhausted before terminal: persist
  `HEARTBEAT_BUDGET_EXHAUSTED`; never silently claim completion

NOOP is not terminal while inflight or queued work exists.

Every STOP is durable: persist the exact non-complete blocker, wait for ACK, and
pause the registered heartbeat. Later matching user evidence/approval clears
only that blocker and reactivates the same automation id with preserved fields.
Never create a replacement heartbeat or broaden the approval.

Heartbeat creation is idempotent. Persist `AUTOMATION_CREATE_PREPARED`, then
inspect canonical state and `$CODEX_HOME/automations/*/automation.toml` for the
deterministic name (`project + loop_id`), Controller target, rrule, and prompt
digest. Adopt one exact match or create once, then persist
`AUTOMATION_REGISTERED`. Pause duplicate exact matches after state ACK. If
`automation_update` is unavailable before First Goal, stop
`AUTOMATION_TOOLS_UNAVAILABLE`; automatic mode cannot run without heartbeat.
If a PREPARED create cannot be reconciled because registry evidence is
inaccessible or ambiguous, stop `AUTOMATION_IDENTITY_UNRESOLVED` and preserve
the outbox; never issue a speculative second create.

## Runtime Retry Contract

Transient dependency retries need four bounds:

- retry cap after initial attempt, default 10; total attempt cap 11
- total elapsed cap, default 180 minutes; it must fit all configured attempt
  timeouts
- hard per-attempt timeout, default 12 minutes
- per-attempt no-progress timeout, default 6 minutes
- each backoff is at most 5 minutes and remains inside the total cap

Each attempt has a hard command timeout and no-progress watchdog. Honor
`Retry-After` only within the remaining total budget; otherwise use bounded
exponential backoff with jitter.

Retry ladder:

1. exact command with captured logs
2. supported fetch/retry flags and lower concurrency
3. package-supported resumable/range/chunked fetch or package-store warming
4. allowlisted alternate public source with integrity evidence
5. project-scoped partial cleanup
6. package-supported browser/native download host

Preserve tracked lockfiles. Remove one only when the current loop created an
untracked partial lockfile and the goal owns it. Never delete global caches,
persist global registry changes, add private credentials, or use paid mirrors
without approval.

## Cost, Approval, And Source Contract

Metered runtime needs a positive cost/call/token cap or explicit policy. Track
caps and cumulative usage in `budget_ledger`. A missing optional cap does not
block when another explicit policy safely bounds the call. Unmeasurable usage is
`BLOCKED_USAGE_METADATA`.

Approval is scope-specific and durable:

- local code/tests/config inside an explicitly allowed scope may be
  pre-authorized
- production deploy, merge, secrets, user-data deletion, DB migration, real
  external writes, and claims beyond evidence remain human gates unless the
  approval ledger explicitly covers that action and scope
- do not re-ask for an approval already recorded and still applicable
- do not reuse an approval for a broader phase

Source files must resolve to workspace or absolute local paths readable by the
target child thread. Files attached only to the Controller conversation are not
automatically inherited by `create_thread` or `send_message_to_thread`. Resolve
or promote them before dispatch, otherwise `MISSING_SOURCE_ARTIFACT`.

## Dispatch Contract

The user sends one self-contained Controller Pack Markdown file to one
Controller thread inside the target Codex Project. Controller:

Sending the pack is explicit authorization for its bounded control-plane task
creation/recovery/messaging/archival and single heartbeat. Do not re-ask. It is
not authorization for Controller product edits or undeclared deploy, merge,
secret, production-write, or claim side effects.

1. validates project, repo mode, sources, queue, permissions, cost, and approval
2. creates/continues current Worker and State-Writer
3. does not create Reviewer yet; every Reviewer is just-in-time after a
   reviewable Worker report and exact artifact mapping exist
4. initializes canonical state and waits for ACK
5. creates heartbeat with exact arguments, persists automation id, waits for ACK
6. materializes First Goal, persists `DISPATCH_PREPARED`, waits for ACK, sends
   once, then persists `DISPATCH_SENT` and waits for ACK
7. routes Worker -> state ACK -> exact review -> state ACK -> next goal
8. runs final integrated review and persists terminal state
9. pauses heartbeat

Manual fallback is allowed only when real thread/automation tools are
unavailable or the user explicitly asks for it. It preserves all state,
idempotency, review, evidence, and stop rules.

## Flow Map

```text
Controller read-only preflight
  -> repo/project/source validation
  -> current Worker + State-Writer bootstrap
  -> canonical state init -> STATE_WRITE_APPLIED
  -> heartbeat create -> persist automation -> STATE_WRITE_APPLIED
  -> materialized /goal with goal_id + dispatch_id
  -> DISPATCH_PREPARED ACK -> send once -> DISPATCH_SENT ACK
Worker
  -> IN_PROGRESS / TRIAGE_* / READY_FOR_REVIEW / blocker
Controller
  -> persist report -> wait for state ACK
  -> exact-artifact Reviewer when diff exists
Reviewer
  -> severity-first findings and decision
Controller
  -> persist review -> wait for state ACK
  -> repair or exactly one unlocked goal
Queue empty
  -> FINAL_AUDIT
  -> final state ACK
  -> LOOP_COMPLETE
  -> heartbeat PAUSED
```
