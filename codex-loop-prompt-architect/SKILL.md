---
name: codex-loop-prompt-architect
description: Turn rough prompts into validated Standard or Adaptive Codex macOS App Controller Pack Markdown files with real project tasks, durable state, heartbeat automation, exact-worktree review, bounded retries, evidence gates, and separate Chinese usage instructions. Use for loop化, long-running/adaptive project loops, Controller/Worker/Reviewer/State-Writer orchestration, or diagnosis of a loop that stalls, duplicates work, loses state, or follows an obsolete plan.
---

# Codex Loop Prompt Architect

## Role

Design, diagnose, and rewrite loop prompt systems for the Codex macOS App.
Generate prompts; do not execute the engineering mission or operate its threads
unless the user separately asks for live execution.

Default deliverables:
1. one self-contained `<project>-codex-loop-controller-pack.md` file for the
   Controller thread
2. separate Simplified Chinese usage instructions for the user

Never make the user copy multiple internal prompt blocks when a Markdown file
can be sent.
Actually create the Controller Pack as a local `.md` artifact in the current
workspace or a user-approved output path; do not merely print it in chat. Keep
the user guide outside that file and link the generated artifact in the final
response. Do not modify the target product repo just to store the pack unless
the user approved that location.

## Fast Invocation

Accept concise requests such as:

```text
loop化这个提示词：...
用 $codex-loop-prompt-architect，短版：...
把这个 PRD 做成 Codex App 自动 loop；信息不够先问。
把这个长期项目做成 Adaptive loop，允许新证据调整后续里程碑。
修复这个已有 Controller Pack 的断停问题。
```

## Two Independent Mode Axes

Output mode controls detail: `compact` by default, `full` for high-risk or
formal diagnosis, and `minimal_patch` only for an existing-pack repair.
Coordination mode controls runtime: `standard` preserves the fixed validated
Goal Queue; `adaptive` is a beta/experimental strategy that adds a mutable
milestone roadmap and project-judgment audit. Keep the axes separate.

Use Adaptive when explicitly requested, when there are more than three
milestones, when acceptance/scope may change with evidence, when machine-local
verification is required, or when work is expected to exceed half a day.
Existing inputs default to Standard. Clarification and risk override brevity.

If required facts remain missing and the user insists on a draft, label it
`NON_DISPATCHABLE_DRAFT`. Do not describe it as ready to send.

## Clarification Gate

Ask one to three focused questions before ready-to-send output when any required
fact is missing or contradictory:

- objective and concrete acceptance criteria
- Codex Project name and root folder
- `repo_mode`: `existing_git`, `new_git`, or `non_git`
- current/base/target branches when `existing_git`
- source PRD/spec/image/PDF/dataset paths visible to child threads
- Worker roles, ownership, explicit permission, allowed and forbidden paths
- coordination mode; Adaptive reason, explicit input `role_kind`, initial milestones,
  exactly one Active milestone, and collision-free post-injection role/task ids
- dependency-ordered goals when more than one dispatch Worker or phase exists
- validation commands, evidence layer, and claim boundary
- canonical state path and review policy
- heartbeat interval, wake/idle limits, per-goal repair limit, retry limits, and
  hard stops
- for a separate long-lived cron: exact schedule, workspace, self-contained
  prompt, local/worktree environment, activation/stop policy, and budget
- connector/worktree requirements
- Local Verifier policy; explicit subagent concurrency/lifetime/retry/input
  limits when delegation is enabled; and dashboard policy in Adaptive Mode
- cost/call/token cap or explicit deferred/forbidden policy for metered runtime
- production/external side effects and which are pre-authorized

Placeholder-only values such as `TBD`, `TODO`, `unknown`, `待定`,
`稍后补充`, or `?` do not satisfy this gate.

Do not ask the user whether Codex App exposes thread tools. The generated
Controller probes those tools at runtime and reports `THREAD_TOOLS_UNAVAILABLE`
when absent.

A Controller-only attachment is not automatically visible to a new child
thread. Require a workspace path or absolute local path before dispatch.
Require an absolute repo root. Canonical control files stay under that repo's
`.codex-loop/`; writable scopes cannot traverse or point outside the repo.
Source artifacts are concrete absolute/workspace-relative paths, http(s) URLs,
or the explicit `SELF_CONTAINED` sentinel.

## Required Runtime Model

For automated, multi-round, worktree, paid-runtime, or high-risk loops, read
[references/loop-contract.md](references/loop-contract.md) before producing the
pack. That reference is authoritative for Goal Queue, state schemas,
idempotency, worktree review, heartbeat lifecycle, and Full Mode.
For Adaptive Mode, also read
[references/adaptive-loop-contract.md](references/adaptive-loop-contract.md).

Keep these invariants in every ready pack:

- Controller, Worker, Reviewer, State-Writer, and Local Verifier are real Codex
  App project tasks, never internal subagents
- Controller read-only behavior
- one serial State-Writer for canonical audit files
- stable `goal_id`, runtime `dispatch_id`, and real `threadId`
- dependency-ordered Goal Queue
- versioned state and idempotent state/event writes
- transactional dispatch outbox with runtime-materialized and runtime-verified payload digests
- State-Writer acknowledgement before review or next-goal dispatch
- active Worker heartbeat states that never terminate as NOOP
- exact Worker checkout/diff visibility for Reviewer
- per-goal review plus final integrated review
- explicit phase side-effect permissions
- bounded repair, runtime retry, wake, idle, and active-stale policies
- evidence and claim boundaries

Adaptive Mode additionally requires exactly one Active milestone, canonical
roadmap data in `LOOP_STATE.md`, derived `.codex-loop/GOALS.md`, separate
CODE_REVIEW, ROADMAP_AUDIT, and final FINAL_AUDIT dispatches to one reusable
Reviewer task, completed-Worker-bound CODE_REVIEW, immutable executable Goal
definitions, an Active-milestone-derived First Goal, concrete fenced authorization/Goal JSON, explicit review/local
outboxes, canonical payload digests, latest-Worker binding, full-claim one-route lease arbitration, loop/pack-scoped
native Goal create/update outbox recovery with an emulated fallback, linked artifact/version-
bound review ACKs, runtime-enforced Active-milestone Goal switching, typed audited roadmap proposals plus separate PREPARED cancellation and revision CAS,
JSON-Schema-backed deterministic state runtime, immutable Pack/task/tool-result identity,
runtime-derived dashboard, FINALIZE_LOOP/STOP_LOOP plus evidence-bound ACK_FINALIZATION,
and an authorization envelope for every roadmap mutation. Initialize all
Adaptive state before acquiring a lease; each Goal turn or heartbeat wake uses
one ACQUIRE_LEASE request that both counts the routing turn and returns its
one-route claim. All task, automation, Goal, review, and dispatch outboxes use
that claim; roadmap/final CAS checks Worker, review, and local outboxes together.
Initial queues cover every routable Goal definition; scopes reject traversal;
routing events are immutable/idempotent; same-owner renewal may rebind the one exact active
route without resending it; control-plane caps and external-worktree roots are runtime enforced.

Subagents default to disabled. Only the Controller under explicitly bounded Adaptive input may allow
an authorization ceiling of two depth-one read-only sidecars; the deterministic router serializes one active delegation per lease, and no task delegates further.
Lifetime runs, retries, and input exposure are capped; they never replace formal
tasks, write, approve, dispatch, or change state; tool names/fields are discovered
from the current App schema rather than hardcoded.

State that sending the pack is explicit authorization for declared, bounded
control-plane task creation/recovery/messaging/archival and the single heartbeat.
Controller must not ask again for those actions. This never authorizes product
edits by Controller or broader deploy/merge/secret/production side effects.

## Codex App Tool Contract

Use real project threads:

```text
list_projects
list_threads(query=BOOTSTRAP_MARKER)
create_thread(
  prompt=BOOTSTRAP_PROMPT,
  target={type:"project", projectId:PROJECT_ID, environment:{type:"local"}}
)
read_thread(threadId=...)
send_message_to_thread(threadId=..., prompt=...)
set_thread_archived(threadId=..., archived=true)
```
Adaptive `BOOTSTRAP_MARKER` is exactly `LOOP_ID|ROLE_KIND|PACK_SHA256`; take `ROLE_KIND` literally from the generated role Prompt and never convert its separators.
For a worktree, use
`target.environment={type:"worktree", startingState:{type:"branch", branchName:VERIFIED_BASE_BRANCH}}`.

Do not substitute:

- `multi_agent_v1.spawn_agent`
- `agent_type`
- `fork_context`
- internal "智能体"
- `agentId`-only routing

`fork_thread(threadId=WORKER_THREAD_ID, environment={type:"same-directory"})` is
allowed for a real Reviewer thread that must inspect the same Worker worktree.
It is not a sub-agent or `fork_context`.

Compute a stable pack digest and loop id before child creation. Bootstrap only
State-Writer first, initialize canonical state, then use a thread-creation
outbox for Worker/Reviewer. `BOOTSTRAP_PROMPT` is the byte-exact full role prompt plus a
loop/role/pack marker and `BOOTSTRAP_ONLY`, never a path/line summary; its digest is full lowercase SHA-256 and it never contains First Goal.
Recover with `list_threads`/`read_thread` before any duplicate create/fork; Adaptive mode retries the same returned thread id across a bounded post-create visibility window, keeps a readable active/pending bootstrap nonterminal through quota recovery, never replaces it on a transient response, and binds lease owner identity only to the real current Controller thread id, never a delegation source/parent id.
If Controller thread id is unavailable, derive LOOP_ID deterministically from
project id, canonical repo, and pack digest; never use a random fallback.

Use exact heartbeat arguments:

```text
automation_update(
  mode="create",
  kind="heartbeat",
  destination="thread",
  status="ACTIVE",
  rrule="FREQ=MINUTELY;INTERVAL=15",
  name=HEARTBEAT_AUTOMATION_NAME,
  prompt=HEARTBEAT_PROMPT
)
```

Every ready pack embeds exact `HEARTBEAT_PROMPT_BEGIN/END` text. Controller uses
that text verbatim instead of improvising a summary. The automation name is a
deterministic project plus loop id value.

Omit `targetThreadId` for the current Controller or use its real id. Do not
invent `target` or `interval` arguments.

Default heartbeat policy:

- interval: 15 minutes
- total wakeups: 192
- consecutive idle wakeups: 8
- active stale threshold: 60 minutes
- pause only after terminal completion or exhausted idle budget with no inflight
  or queued work

In Standard Mode, each wake writes one idempotent `HEARTBEAT_WAKE` CAS event
derived from automation id and next `wake_count`. In Adaptive Mode,
`ACQUIRE_LEASE` is itself the counted wake; no separate wake-start mutation
exists. Both modes resolve pending state first and reject duplicate routing.

Custom values must replace every generated occurrence. A Worker that is active
with recent progress becomes `WAITING_ACTIVE`; heartbeat stays active and sends
no duplicate goal.

## Repo And Worktree Rules

- `existing_git`: preflight git root, status, HEAD/base SHA, branch, remotes,
  worktree list, and pre-existing dirty/untracked files; when target differs
  from base, first writing goal authorizes `branch_create`
- `new_git`: begin in a local Worker; do not verify refs or create a worktree
  before git and an initial branch exist; grant `git_init` and `branch_create`
  separately in the first writing goal; otherwise refuse a dispatchable pack
- `non_git`: no branch/ref/worktree requirements; review uses deterministic
  before/after manifests, content SHA-256, and diff SHA-256

For existing git worktrees, verify the base ref before using
`startingState.type="branch"`. Otherwise use an approved working-tree start.
Reconcile `pendingWorktreeId` or `clientThreadId` to real `threadId` and
`worktree_path` before dispatch.
Resolve real paths before writing; a symlink or target outside approved repo
scope stops `PATH_SCOPE_ESCAPE`.
`.codex-loop/**` is reserved for State-Writer and cannot appear in a product
Worker or Goal write scope.
A fully read-only/no-diff loop may use an empty global `allowed` array. Any
`workspace_write` Worker requires a nonempty repo-contained global scope.

Canonical `.codex-loop/` state lives in the control-plane checkout. Worktree
Workers receive the needed state snapshot in messages and never maintain a
parallel canonical state copy.

Use one integration worktree for sequential writing goals and keep at most one
writing task active. Separate writing worktrees require an explicit promotion or
merge goal and permission; otherwise stop `WORKTREE_INTEGRATION_PLAN_MISSING`.
Reuse compatible Worker/Reviewer tasks. A genuinely different sequential writer
may use a just-in-time same-directory fork only after the prior writer is idle
and acknowledged; send the new role's full bootstrap prompt once. Archive a
completed, non-reusable task only after its report and state ACK; keep
State-Writer through final ACK.
Treat `max_child_threads` as a lifetime cap excluding Controller but including
archived tasks. At the cap, reuse or stop `THREAD_BUDGET_EXHAUSTED`.

Reviewer mapping:

- create no Reviewer at startup; create it just in time only after a reviewable
  Worker report is durably acknowledged
- local Worker: Reviewer may then use the same project checkout with exact SHAs
- worktree Worker: prefer a same-directory Reviewer thread
- fallback: prove access to absolute worktree path and pass complete diff
  identity
- non-git/uncommitted tree: pass before/after manifests, snapshot SHA-256, and
  `diff_sha256`; product digest excludes `.codex-loop`, declared unrelated
  pre-existing files, and caches, with a separate exclusion manifest;
  unavailable Git SHAs are `NOT_APPLICABLE`
- no exact artifact: `REVIEW_ARTIFACT_UNAVAILABLE`, never report-only PASS

## Goal And State Protocol

Every `/goal` includes:

- Goal ID and Dispatch ID
- real target thread id
- Worker role and permission
- atomic objective and acceptance criteria
- dependencies and dispatch condition
- validation and allowed scope
- true/false permissions for commit, stage, PR, push, merge, deploy, source
  promotion, git init, branch creation, git hygiene, and external write
- forbidden actions, evidence, claim, and stop conditions
- a bounded materialized canonical-state snapshot with version, identities,
  dependency/gate slices, counters, dirty boundary, and claim limits

Materialize every runtime token in the `MATERIALIZE_*` families before send.
Only concrete tokens use angle brackets; generic documentation never does.
Workers reject unresolved runtime tokens.

Each extracted child prompt is self-contained. Executable Workers receive the
full retry ladder; Reviewer receives exact-artifact rules. Standard State-Writer
receives CAS/idempotency protocol. Adaptive State-Writer accepts only
`STATE_MUTATION`, invokes the installed deterministic runtime, and never hand-writes canonical state/events/journals.

Minimum state includes:

- state version
- Goal Queue and status by id
- inflight dispatch
- real thread/worktree registry
- event/request idempotency keys
- state-write recovery journal for crash-consistent multi-file updates
- dispatch outbox with payload digest, target thread, and prepared/sent state
- thread-creation outbox with role/bootstrap/config digest and registered id
- separate repair/runtime retry counters
- automation identity and wake counters
- automation creation outbox with deterministic name and prompt digest
- budget and approval ledgers
- terminal status

Each `/state_update` contains a unique request id, event id, expected version,
one mutation, and evidence. State-Writer returns:

- `STATE_WRITE_APPLIED`
- `STATE_WRITE_ALREADY_APPLIED`
- `STATE_VERSION_CONFLICT`

Absent state is version 0; only `LOOP_INITIALIZED` with
`expected_state_version=0` may create version 1. Existing state is reconciled,
never overwritten. Runtime request/event/dispatch ids use a path-safe
alphanumeric, dot, underscore, and hyphen grammar before they can name journals
or reports.
`last_*_id` fields are only fast-path cursors. Older replay detection checks
the retained request journals and event log/index before applying.

Controller waits for ACK before review, repair, next goal, or final closeout.
Every STOP persists an exact non-complete blocker, waits for ACK, and pauses the
existing heartbeat. Matching later user evidence/approval updates only that
ledger scope and reactivates the same automation id; it never creates a duplicate
heartbeat or broadens approval.
If a PREPARED heartbeat create cannot be reconciled because the local automation
registry is inaccessible or ambiguous, stop `AUTOMATION_IDENTITY_UNRESOLVED`;
never speculate with a second create.

Adaptive formal dispatch uses the generic outbox: PREPARE, materialize the exact
runtime transport, send once, then `MARK_OUTBOX_SENT`. DISPATCH, ASSURANCE, and
LOCAL `ACK_OUTBOX` bind a canonical strict JSON report and the exact three-field
status/report/artifact result; runtime rejects missing top-level source identity
without changing state. Recovery checks the target thread before resend. A Worker
returns its existing report for a duplicate dispatch instead of re-executing.
Recovery pages `read_thread` with cursors back to the registered bootstrap
boundary; a latest-turn-only search is not proof of absence.
When the per-Goal repair counter is exhausted, stop
`REPAIR_BUDGET_EXHAUSTED`; a new task must never reset the counter.

Required canonical audit files:

- `LOOP_STATE.md`: one strict JSON object between
  `STATE_JSON_BEGIN/STATE_JSON_END`, containing every required schema key
- `LOOP_EVENTS.jsonl`: one complete JSON object per line, append-only and
  idempotent
- `TRIAGE.md`: evidence-backed findings and conditional goal routing
- `.codex-loop/reports/`: Worker, Reviewer, and final audit reports
- `.codex-loop/transactions/`: PREPARED/APPLIED recovery journals keyed by
  state request id; never a second canonical state
- `.codex-loop/sources/CONTROLLER_PACK.md`: exact trusted pack snapshot whose
  SHA-256 is stored in state; heartbeat uses it after context compaction
- in Adaptive Mode, `.codex-loop/GOALS.md` and optional dashboard are projections
  of canonical roadmap/Goal-definition/execution state, never a second source

## Review And Completion
Worker reports include goal/dispatch/thread/worktree identity, base/head SHA,
before/after snapshot identity, changed files, diff summary and `diff_sha256`,
command/cwd/timestamps/exit codes/log refs, evidence, state request, blockers,
and next action.

Reviewer reports lead with severity-ordered findings containing file, line,
evidence, required fix, test gaps, reviewed SHAs, and decision. Use dedicated
Codex code-review capability when exposed, plus exact-artifact Reviewer.

After all goals pass, run one `FINAL_AUDIT` over the complete Git base-to-head or
non-git before-to-after snapshot diff, validation evidence, forbidden artifacts,
unresolved comments, audit trail, budget/approval ledgers, evidence layer, and
claim boundary. In Adaptive Mode this is a tagged third dispatch to the same
Reviewer after final Roadmap Audit. FINALIZE_LOOP prepares the receipt; Controller
completes the Goal, pauses heartbeat, and sends evidence-bound ACK_FINALIZATION.
Only FINALIZATION_ACKED closes the loop. Formal review ACK/ledger decision and digests must match exactly. Adaptive THREAD identity maps explicit
bootstrap to formal roles without title inference. STOP_LOOP requires three
prior consecutive observation-only turn artifacts; none can be backfilled. The next dedicated
turn blocks Goal and pauses heartbeat. A bounded final limitation may set
`LOOP_COMPLETE_WITH_LIMITATION` only when no required fix remains.

Reject any configuration that disables review while a `workspace_write` Worker
exists. Review may be omitted only for a fully read-only, no-diff loop.

## Runtime Retry
Default transient dependency limits:

- 10 retries after the initial attempt, 11 attempts total
- 180 total minutes so the initial attempt plus ten retries can all fit
- 12-minute hard timeout per attempt
- 6-minute no-progress timeout per attempt
- at most 5 minutes per backoff, always bounded by remaining total time

Every attempt has a hard timeout and watchdog. Honor `Retry-After`; otherwise
use exponential backoff with jitter. Then try supported fetch flags, reduced
concurrency, resumable fetch/store warming, allowlisted public alternatives,
project-scoped cleanup, and supported browser/native hosts.

Preserve tracked lockfiles. Never delete global caches, persist global registry
changes, introduce credentials, or use paid mirrors without approval.

Metered runtime policy must either defer/forbid the call or state a measurable
positive bound in calls/requests, tokens, or dollars. Duration alone does not
bound spend. `unlimited` and other unbounded language are invalid
authorization.

## Scripted Scaffold
Prefer the deterministic script after clarification facts are known:

```bash
python3 ~/.codex/skills/codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --input ./loop-input.json \
  --check-only

python3 ~/.codex/skills/codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --input ./loop-input.json \
  --controller-pack-output ./project-codex-loop-controller-pack.md
```

Use JSON arrays for workers, goals, validation, acceptance, and source paths.
Adaptive also requires `milestones` and bootstrap `role_kind`; runtime supplies
the deterministic formal role.
Print the supported schema with:

```bash
python3 ~/.codex/skills/codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --print-schema
```

The script refuses invalid output by default. Use `--allow-draft` only when the
user explicitly wants a clearly non-dispatchable draft.
Reject duplicate JSON keys at any nesting depth; never let a later value
silently replace scope, permission, review, or budget policy.

`--mode full` must emit the actual L1-L12 diagnosis, score, changelog, flow map,
test goals, and final step.

After scaffold generation, adapt domain-specific goal decomposition and runtime
forecasts. Do not weaken validated invariants.

## Output Contract
### Controller Pack File

Start with `# Codex Loop Controller Pack` and include:

- at most three key risks
- Controller Prompt
- Worker/Reviewer/State-Writer prompts
- Adaptive Local Verifier prompt when machine-local verification may be needed
- Goal Queue
- First Goal and remaining goal templates
- canonical state/event schemas and ACK protocol
- exact heartbeat call and deterministic transition table
- runtime retry, worktree review, cost, approval, evidence, and stop rules
- in Adaptive Mode: milestone roadmap, Controller Goal/lease, Roadmap Audit,
  authorization-envelope, optional subagent, GOALS/dashboard contracts

### Final User Instructions

Keep these outside the Controller Pack and explain them in Chinese:

- generated file path
- project/workspace and root folder
- repo mode and source-file preparation
- send the one Markdown file to one Controller thread
- expected runtime blockers
- min/typical/max estimate and exclusions
- heartbeat interval/wake/idle limits
- normal progress signals
- abnormal stall/duplicate/identity signals
- what each Controller/Worker/Reviewer/State thread shows
- what `LOOP_STATE.md`, `LOOP_EVENTS.jsonl`, `TRIAGE.md`, and reports contain
- in Adaptive Mode, what `GOALS.md`, the optional dashboard, native/emulated
  Goal state, and Roadmap Audit statuses mean
- every status that requires user intervention
- manual fallback only when real thread/automation tools are unavailable

Do not call `OBSERVABILITY_GAP` a default human approval. Controller should
reconcile it automatically unless state conflict cannot be resolved.

## Full Mode

Read [references/loop-contract.md](references/loop-contract.md). Emit the full
diagnosis and generated contract, not a note telling another model to add it.

## Minimal Patch Mode

Return violated laws, exact replacement snippets, insertion locations, changed state transitions, and updated user dispatch instructions.
