# Human Steering And Convergence Contract

Read this reference for Adaptive loops and whenever a user asks to query,
pause, resume, constrain, correct, or review an active loop. The deterministic
runtime and public schemas remain authoritative when prose differs.

## Scope

This version adds exactly nine capabilities: fuzzy intake, Minimal Steering,
derived `STATUS.md`, Decision Cards, optional review surfaces, failure
fingerprints, Validation Matrix, Context Freshness, and Reviewer Evidence
Hierarchy. It does not add a Steering Agent, pattern engine, multi-model debate,
parallel writers, deployment platform, or general cron system.

## Fuzzy Intake

Pre-generation readiness and clarification are defined only by
[loop-intake-gate.md](loop-intake-gate.md). This reference does not maintain a
second intake rule set. The sections below govern Steering after an Adaptive
loop exists; they cannot upgrade an intake status or bypass the Intake Gate.

## Minimal Steering

Accepted classes are `STATUS_QUERY`, `PAUSE`, `RESUME`, `CONSTRAINT`,
`CORRECTION`, and `DECISION_RESPONSE`.

- Bind each durable Steering item to a stable message item id, or to a
  recoverable Controller turn cursor plus normalized digest.
- If neither identity exists, return `STEERING_IDENTITY_UNRESOLVED` with zero
  side effects. This disables only that Steering item, not the existing loop.
- `STATUS_QUERY` is read-only by default. It does not acquire a routing lease,
  change state, consume repair budget, or create a task.
- Record Steering before routing. State-Writer ACK is required before it may
  affect the next action.
- Never mutate a SENT payload. A conflicting correction or constraint is
  deferred to a safe point or becomes a scoped conflict.
- `PAUSE` and `RESUME` can only be resolved through `SET_RUN_CONTROL` and its
  safe-point lifecycle. `RESOLVE_STEERING` is limited to `CONSTRAINT` and
  `CORRECTION`; it cannot mark run-control instructions handled.
- Steering cannot expand budget, side effects, claim boundary, approval, merge,
  deploy, production, or secrets access.

`human_steering_policy=disabled`, `status_projection=disabled`, and
`decision_card_policy=disabled` are canonical UX choices. The runtime rejects
their corresponding mutations or projection writes. Failure fingerprint,
Context Freshness, and deterministic evidence gates are safety controls and
cannot be disabled in Adaptive input. A required review surface is invalid when
Decision Cards are disabled.

Pause lifecycle:

```text
RUNNING -> PAUSE_REQUESTED -> PAUSED_AT_SAFE_POINT
PAUSED_AT_SAFE_POINT -> RUNNING (requested_status=RESUME)
```

If a Worker is active and the App cannot prove interruption, stop new routing
and remain `PAUSE_REQUESTED`. Never claim the Worker stopped. Resume reuses the
same tasks, ledgers, budgets, heartbeat, failure history, and evidence.
An acquired lease or any PREPARED/SENT outbox is also an active route. Pause
must first release an idle lease or finish/cancel the existing route; the
runtime rejects new lease acquisition, prepare, send, roadmap, and finalization
actions while run control is not `RUNNING`.

## STATUS Projection

`.codex-loop/STATUS.md` is a deterministic human projection, never a second
state source. Canonical state commits first. Canonical metadata records only the
target path, state version, projected-content digest, and render contract version. An
independent projection journal records `PREPARED/APPLIED` and readback digest.

The projection uses `What's done / What's next / Any blockers`, identifies the
loop, milestone, Goal, task, lease, outbox, pending Steering/decisions,
validation gate, next action, reports/artifacts, state/roadmap versions, state
confirmation time, last task observation, and freshness. If projection recovery
is pending, report both canonical and projected versions. Do not treat stale
content as current fact or expose secrets and authenticated URLs.

## Decision Cards

Create a card only for a real user gate. It has a stable decision id, context
digest, valid state-version range, two or three mutually exclusive options,
scope, recommendation, default no-decision behavior, and explicit exclusions.
Each option maps to one preauthorized capability. A response must bind decision
id, option id, current context digest, and stable message/turn Steering identity.
`RECORD_DECISION_RESPONSE` atomically archives that applied identity before the
Controller may act on its returned option effect. Changed scope, SHA, artifact,
validation, blocker, or state range returns `DECISION_STALE` with zero side
effects. A Decision Card cannot mint authority.
In schema v3, call only the public Gateway operations. `REGISTER_DECISION`
derives source version and context digest from canonical; after a real user
response, `RECORD_DECISION_RESPONSE` derives the current host-attested turn
cursor and normalized response digest. Legacy mutation calls remain rejected.
Repair exhaustion is a deterministic special case. Register one stable card
whose only effects are `STOP_LOOP_CONFIRMED` and `WAIT`, then pause the exact
heartbeat. STOP binds the applied card, current context digest, and exact
response Steering into `STOP_LOOP(stop_basis=USER_DECISION)`. WAIT keeps the
loop paused for a later scoped `CORRECTION` and never authorizes an additional
repair. The hard cap is not itself a selectable option.
Additional `FRESH` checks and deterministically `CHANGED_IRRELEVANT` observations
for the same artifact do not stale an otherwise unchanged card. `RELOAD_SAFE`,
`SCOPE_CONFLICT`, `HARD_BLOCK`, or any changed scope, artifact, validation,
authorization, blocker, or state-range identity still requires a newly derived
context and response.
Review-surface acceptance additionally binds `scope.goal_id`, the exact latest
Worker dispatch and `artifact_digest`, and the configured artifact path or local
preview URL. Registration rejects an incomplete or mismatched binding before a
user response can be recorded.
When a configured local preview port is occupied, scope may bind an observed
port only for the same explicit loopback host, scheme and path with no
credentials, query or fragment. A host, scheme or path change is never treated
as the same review surface.
An unrelated Decision cannot unlock finalization. When a later Worker artifact
changes that identity, runtime marks the prior card `STALE`; the same stable
decision id may be registered again only with the newly derived context and a
new explicit response. A relevant validation, failure, freshness, roadmap, or
artifact mutation proactively marks pending/applied cards stale so legacy
incomplete cards cannot permanently occupy the fixed gate id.

## Review Surface

`review_surface` is optional Goal metadata for `browser_preview`, `screenshot`,
`markdown`, `tabular_data`, `pdf`, `slides`, `diff`, `other_artifact`, or an
explained `NOT_APPLICABLE`. Confine artifact paths to the Goal scope and reject
traversal, symlink escape, credential URLs, secret query parameters, and
unauthorized external hosts. A preview is not deployment evidence. User
feedback enters `CORRECTION`; user acceptance unlocks work only through a valid
Decision Card. A review surface never replaces code review.

## Failure Fingerprint

Use the deterministic generic-v1 normalizer. Remove timestamps, random ports,
PIDs, temporary paths, and secrets. Persist digests and bounded identities, not
raw sensitive logs. Unknown language-specific error class/location stays
`UNKNOWN`.

Classify progress as `PROGRESSING`, `SAME_FAILURE_NEW_STRATEGY`,
`THRASHING_DETECTED`, `POSSIBLE_STRATEGY_REPEAT`,
`REGRESSION_INTRODUCED`, or `STRATEGY_EXHAUSTED`. The materialized same-strategy
threshold is 2 by default and may be 2-3, never above the initial-attempt-plus-
repair observation window. Deterministic thrashing requires the same diff and
changed-files identity; a similar failure after a different diff is only a
possible repeat.
New Worker, dispatch, resume, or recovery does not clear history. Model-judged
semantic similarity is only `POSSIBLE_STRATEGY_REPEAT`; it is not a
deterministic thrashing fact.

## Validation Matrix

Every Adaptive Goal materializes functional, regression, static quality,
compatibility, security, performance, user experience, and change-impact
dimensions. Each dimension is required with commands/evidence, or not required
with a reason. Auth/permission/secret/crypto changes require security; public
API/schema/CLI/generator changes require compatibility; UI changes require UX
evidence and a review surface; hot query/cache/loop/batch paths require
performance consideration.

The runtime stores requirements, results, one archived evidence artifact, and
the exact latest Worker artifact identity. Worker reports derive that identity
as the literal `sha256:` prefix followed by `after_snapshot_sha256`; a content-changing repair cannot reuse the
prior artifact digest. A later Worker artifact invalidates
the prior result until that exact artifact is revalidated. A failed, missing,
stale, or unacknowledged required dimension blocks full PASS. Users may
tighten the matrix but cannot silently disable a risk-triggered requirement.
Reviewer prose and LLM scores cannot override the gate.
Retired Goals remain durable history but are excluded from completion
validation and review-surface acceptance.

## Context Freshness

Check and bind goal, deterministic identity digest, and exact dispatch/artifact
identity before Goal dispatch, Worker recovery, repair, affected
Steering, each review, and final audit. Record repo/worktree/root, branch,
base/head SHA, dirty boundary, source digest, lock/config identity, exact
artifact/report/diff identity, and connector timestamp when relevant.
The runtime also stores a recomputable context-state digest over the Goal
definition, authorization, latest Worker artifact, validation evidence,
applicable Steering/Decisions, and failure history. Any relevant canonical
mutation after the check invalidates it; lease renewal and assurance outbox
bookkeeping do not. The observed identity object is closed: it includes explicit
Git or non-Git identity, root and boundary digests, source/scope/interface/lock
and config digests, nullable Worker/report/artifact/diff identity, changed
paths, and every defined change flag. The latest applicable checkpoint record
wins; a later blocker cannot fall back to an older positive record.

Classifications are `FRESH`, `CHANGED_IRRELEVANT`, `RELOAD_SAFE`,
`SCOPE_CONFLICT`, `HARD_BLOCK`, and `JUDGMENT_REQUIRED`. Automatically classify
irrelevant only when deterministic realpath/scope checks prove non-overlap and
all relevant identities remain unaffected. A Reviewer never reviews an obsolete
artifact. `FRESH` requires the complete deterministic identity shape, no
changed paths, and no positive change flag; `RELOAD_SAFE` requires a completed
deterministic reload.

## Evidence Hierarchy

Deterministic tests/invariants/contracts, static/security checks, golden
fixtures, reproducible runtime evidence, exact-artifact independent review,
LLM judgment, and Builder self-assessment form a default trust order, not a
single total ranking across quality dimensions. A lower layer cannot override a
failed required hard gate. Contradictory hard evidence becomes
`EVIDENCE_CONFLICT`; investigate the oracle, fixture, environment, and artifact
identity. Updating a baseline or fixture must be explicit and independently
reviewed.

## Turn Order

Recover transaction and projection journals; read state/tasks/lease/outboxes;
record new Steering idempotently; answer read-only status queries; arbitrate the
lease; apply pending Steering at a safe point; process ACK/outbox state; bind
Context Freshness; route at most one action; recover/refresh STATUS. A lease
prevents a second router but does not block idempotent Steering intake.
