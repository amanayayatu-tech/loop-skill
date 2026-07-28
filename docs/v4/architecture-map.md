# LoopSkill 4 architecture map

Release boundary: v4-only. There is no v3 importer, legacy Pack runtime, MCP
State Gateway, State-Writer, Supervisor, or canonical dual write.

```text
Entry / composition root
  ├─ Intake → Prepare → Confirm → Start
  ├─ deterministic Kernel
  │    └─ typed protocol + Store/Artifact/Host ports only
  ├─ SQLite Store
  │    └─ one canonical transactional writer and outbox truth
  ├─ Artifact / review / finalization libraries
  │    └─ existing-Git, non-Git, new-Git capability implementations
  ├─ Codex Host Adapter
  │    └─ local Codex app-server composite task create, readback, and honest capability rows
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

## External effects

The Store durably records one `AttemptRef` before execution ownership is
claimed. The automatic attempt budget is consumed immediately before the Host
call. Provider idempotency plus authoritative readback supports only an
effectively-once statement. Without both, the contract is at-most-one automatic
attempt and the outcome may be `UNKNOWN`; the system does not resend. A late
authoritative observation can strengthen the same subject identity but cannot
invent a new attempt or rewrite workflow history.

The public composition root constructs the production app-server provider only
after explicit confirmation. It sends the digest-bound semantic boundary, not
user/model control identity. The Host provider exposes no create idempotency
key; after a crash it may perform only exact machine-marker readback. Missing or
ambiguous readback becomes `UNKNOWN`, never another create.

When an ordinary `start` invocation itself creates the one task, Entry performs
bounded foreground terminal readback for at most 300 seconds. The provider and
its temporary `app-server` session close in a `finally` path on success, error,
or timeout. This is an observation window, not the task budget. Timeout is an
honest user-visible limitation and makes no claim that the Host task completed,
failed, or continues running. The machine-bound Attempt remains available to
`status --refresh`, and Entry does not resend. This does not change refresh
semantics or grant refresh another attempt budget.

Codex Desktop's folder-open → `list_projects` → `projectId` → `create_thread`
route has 23/23 verified provisioning receipts. That evidence establishes the
Desktop provisioning route, not a capability in the v4.0 Provider: app-server
0.144.4 exposes no project methods. The 4.0 default therefore uses a cwd-bound
thread/start. Optional saved-project convenience is deferred to 4.0.x/4.1.

After exact task readback, Entry submits the generated
`StageExternalResult` command and the existing Result/Artifact/Review/
Finalization commands. Each local operation is independently transactional and
replay-safe; every committed intermediate state has one deterministic successor.
If a crash follows the local Attempt commit but precedes its provider call,
`status --refresh` may claim that Attempt and execute its one first call.
Otherwise refresh only reads the existing Host task and continues the local
chain. It can never perform a second create or resend. The Host-result digest
remains in the canonical Result binding so changed readback fails closed.

## State and evidence

Local operation acceptance is exactly-once for the same operation ID and
request bytes. Per-loop CAS rejects stale revisions. Snapshot, events,
operation receipt, outbox, and current Result/Report/finalization bindings
commit atomically. Artifact correctness, workflow terminality, Host assurance,
and public release are distinct claims with distinct evidence.

The 4.0.0 release support claim is gated by the eight-lane Linux/macOS × Python
3.11, 3.12, 3.13, and 3.14 runtime/distribution matrix. A local result from one
Python runtime is useful focused evidence, not a substitute for that matrix.
