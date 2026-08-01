# LoopSkill 4 architecture map

Release boundary: v4-only. There is no v3 importer, legacy Pack runtime, MCP
State Gateway, State-Writer, Supervisor, or canonical dual write.

```text
Entry / composition root
  ├─ conversational Intake → owner-only Prepare → Confirm → Start
  ├─ deterministic Kernel
  │    └─ typed protocol + Store/Artifact/Host ports only
  ├─ SQLite Store + immutable content-addressed plan blobs
  │    └─ one canonical transactional writer and outbox truth
  ├─ Artifact / review / finalization libraries
  │    └─ existing-Git, non-Git, new-Git capability implementations
  ├─ Codex Host Adapter
  │    └─ one foreground official `codex exec --json` invocation per activated Goal and honest capability rows
  ├─ optional Policy
  │    └─ Standard, Adaptive, roles, decisions, bounded repair
  └─ rebuildable projections
       └─ status, Doctor, audit, archive, privacy, metrics
```

## Dependency rules

- Kernel imports only protocol and port abstractions. It cannot import Codex,
  App enums, policy, UI/CLI, Git/subprocess, filesystem mutation, SQLite
  concrete code, Pack rendering, installer, or research apparatus.
- Store never calls Host. Host and Artifact implementations never write
  canonical state. Entry composes them and submits typed semantic commands.
- One canonical authority may keep orthogonal aggregate and event streams. It
  does not collapse Lifecycle, Goal, Result/Report, Artifact, Review,
  Finalization, Delivery, and Assurance into one giant enum.
- Optional policy is removable: the minimal entry still performs the complete
  four-phase path and honest `UNKNOWN`/`UNVERIFIABLE` handling without it.
- Projections are rebuildable and read-only. They cannot authorize recovery or
  become another ledger.
- PlanCodec canonicalizes the confirmed 1–128 Goal PlanDocument outside the
  Kernel. The Kernel independently validates plan/index/digest/selector
  identities but never reads arbitrary files or networks. CreateLoop registers
  only the current Goal; the existing `AdvanceGoal` transaction completes it,
  creates the next Goal/Attempt, and writes one compact outbox descriptor.

## External effects

The Store durably records one `AttemptRef` before execution ownership is
claimed. Invocation and observed active-compute budgets are checked before the
Host call. Provider idempotency is not assumed: one provider key maps to one
owner-only Attempt directory, and recovery may only read its terminal evidence,
wait on its recorded live PID plus process-start identity, or use its one bound
session resume. Interrupted active compute is conservatively charged from the
persisted start time up to the Attempt bound. A late
authoritative observation can strengthen the same subject identity but cannot
invent a new Goal Attempt or rewrite workflow history.
Budget exhaustion pauses before the Adapter invokes the Host. A digest-bound
`budget-extend` may only increase the current invocation and active-compute
limits; `ResumeLoop` records `BudgetExtended` without changing immutable Plan
scope or requirements.

The public composition root constructs `CodexExecProvider` only after explicit
confirmation. It sends the digest-bound semantic boundary on stdin, not
user/model control identity. It derives one closed outcome/summary JSON Schema
from the typed manifest, passes it through the official `--output-schema`
option, and supplies one private `--output-last-message` path as the sole
semantic-result byte source. Both controls remain outside the artifact workspace
and are removed from their transient machine-controlled locations after the
process. Plan v2 also persists digest-bound copies outside the artifact
workspace. The Provider owns one foreground process group and accepts one
bounded complete JSONL lifecycle plus one schema-valid result file. It has no
`agent_message`/text-marker fallback or provider-side idempotency assumption.

The per-Attempt bound is at most 30000 seconds and is not the whole-Loop budget.
The official executable owns its internal thread/turn lifecycle; LoopSkill
reaps the process group on every owned exit path. A new Provider can read a
completed persistent Attempt. If an interrupted Plan v2 Attempt captured a
session, replay-safe recovery may issue exactly one recorded
`codex exec resume`; non-replayable work waits for human confirmation.

Codex Desktop's folder-open → `list_projects` → `projectId` → `create_thread`
route has historical verified provisioning receipts. That evidence establishes
the Desktop provisioning route, not a capability in the v4.2 Provider. The 4.2
default is a foreground cwd-bound `codex exec` invocation and does not promise
a Desktop-visible saved project/task. Optional saved-project convenience is
outside the current release boundary.

After exact task readback, Entry submits the generated
`StageExternalResult` command and the existing Result/Artifact/Review/
Finalization commands. Each local operation is independently transactional and
replay-safe; every committed intermediate state has one deterministic successor.
If a crash follows the local Attempt commit but precedes its provider call,
`run`/`continue` may claim that Attempt and execute its first call. After Host
start, recovery is restricted to the persistent PID/session/result evidence
above. The directly captured Host-result digest remains in the canonical Result
binding so changed local evidence fails closed.

Public `list`, `status`, policy, and diagnostics views open SQLite in read-only
mode. Repair ordinals, attempt limits, and repeated-failure fingerprints are
scoped to the active Goal, so one Goal cannot consume another Goal's repair
budget.

## State and evidence

Local operation acceptance is exactly-once for the same operation ID and
request bytes. Per-loop CAS rejects stale revisions. Snapshot, events,
operation receipt, outbox, and current Result/Report/finalization bindings
commit atomically. Artifact correctness, workflow terminality, Host assurance,
and public release are distinct claims with distinct evidence.

The 4.2.0 release support claim is gated by the eight-lane Linux/macOS × Python
3.11, 3.12, 3.13, and 3.14 runtime/distribution matrix, v1 compatibility plus
v2 128-Goal capacity boundaries, upgrade rollback injection, long-horizon
state-machine tests, and three canary layers on one exact candidate. A local
result from one Python runtime is focused evidence, not a substitute for that matrix.
