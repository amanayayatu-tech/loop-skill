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
  │    └─ task/create/read/send/readback and capability receipts
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

## State and evidence

Local operation acceptance is exactly-once for the same operation ID and
request bytes. Per-loop CAS rejects stale revisions. Snapshot, events,
operation receipt, outbox, and current Result/Report/finalization bindings
commit atomically. Artifact correctness, workflow terminality, Host assurance,
and public release are distinct claims with distinct evidence.
