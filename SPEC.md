# loop-skill Specification

This file is the short, normative entry point for loop-skill. It defines how
the project preserves safety while its implementation, schemas, tests, and App
integration evolve. Detailed protocol shapes remain in the linked public
schemas and contracts; this file does not duplicate the state machine.

## What this specification does not freeze

The specification protects observable safety properties, not today's function
names, modules, algorithms, file layout, prose, or tests. Current behavior is
evidence, not proof that the behavior is correct. Current tests are executable
checks, not an automatic source of truth. A bug fix may correct code, a stale
test, and a mistaken specification statement in the same reviewed change.

README files, examples, generated Packs, and marketing copy explain the
project. They are not normative unless a normative source explicitly adopts a
particular value or shape.

## Normative levels

- `CORE_INVARIANT`: a safety property whose violation can corrupt identity,
  state, routing, evidence, or completion.
- `PUBLIC_CONTRACT`: a stable externally observable schema, status, error, or
  interface commitment.
- `PROVISIONAL`: an intended direction that may change with evidence and is not
  a release hard gate.
- `IMPLEMENTATION_NOTE`: a current mechanism or design aid; equivalent safe
  implementations are allowed.
- `DEFERRED`: an intentionally unavailable capability or unresolved design;
  it must fail closed where a public surface exists.

Only active `CORE_INVARIANT` and stable `PUBLIC_CONTRACT` entries may be used as
release hard gates. A provisional, implementation-note, or deferred entry may
inform review, but cannot independently block an urgent repair or release.

The machine-readable index is
[`docs/spec/invariants.yaml`](docs/spec/invariants.yaml). It maps each property
to its rationale, allowed evolution, sources, implementation surfaces, schemas,
tests, evidence, and ADRs.

## Authority and conflict resolution

For the question each source is designed to answer, use this order:

1. Active core semantics in this SPEC and the invariant index.
2. Public schemas and explicitly stable public errors/statuses for wire and
   persisted shape.
3. The Standard, Adaptive, and human-steering contracts for detailed protocol
   semantics.
4. Accepted ADRs for the reason and evolution boundary of a decision.
5. Runtime implementation.
6. Executable tests.
7. README files, examples, generated output, and marketing material.

This is not a rule that higher text is infallible. When evidence shows a higher
source is unsafe, incomplete, or stale, fix that source and all affected lower
surfaces together. Do not make code conform to a known specification bug.
Public schemas remain authoritative for the exact data shape they publish;
this SPEC remains authoritative for the semantic safety property. A conflict
must be resolved explicitly in the change that discovers it.

## Core contract families

The active contract is organized by invariant family rather than by current
module:

- bounded single-frame structured transport and strict UTF-8 framing;
- one business route per real host turn with host attestation;
- schema-v3 MCP State Gateway as the sole canonical writer for new Adaptive
  Packs, with explicit-only v1/v2 migration;
- durable outboxes, receipts, replay, and lost-output recovery;
- current-artifact, current-dispatch, PASS-report evidence binding;
- bounded transport degradation and immutable successor handoff;
- fenced leases and identity-preserving Pack migration;
- bounded repair and fail-closed rejection with zero side effects;
- evidence claims bound to the exact artifact and environment;
- real-Loop isolation;
- completion only at canonical `FINALIZATION_ACKED`.

The index gives the exact normative statements and source mappings. It is an
index, not a second state schema.

## Safe evolution

An implementation may be replaced without an ADR when the active invariant and
public contract remain true. Normal refactors may move functions, rename
private symbols, reorganize modules, or replace tests. They update the index
only when a referenced surface changes.

Use an ADR when changing a durable design decision, its trade-off, or its
replacement boundary. An ADR records why; it does not override an active core
invariant by itself. Replace a decision with a new ADR, mark the old ADR
`Superseded`, and update affected index entries in the same change. Do not edit
accepted history to imply the new decision always existed.

Changing a stable public shape or error requires the normal compatibility and
release process. Adding a new capability starts as `PROVISIONAL` or `DEFERRED`
until its safety boundary and evidence are established. Promotion to
`CORE_INVARIANT` or `PUBLIC_CONTRACT` requires a normative statement, an
authoritative source, an executable test, and review of migration and backward
compatibility.

## Bug classification and fast path

Classify a discovered problem before deciding which artifacts to change:

- **A — implementation bug:** behavior violates an active core invariant or
  stable public contract. Fix implementation and tests; update docs only when
  they are stale.
- **B — specification bug:** the written rule would require unsafe or
  demonstrably wrong behavior. Fix the specification, affected tests, and code
  together; never preserve a bad rule merely because it is written here.
- **C — compatible evolution:** core semantics and public contracts remain
  true. Treat the work as a refactor or implementation change, not a protocol
  migration.
- **D — capability or contract change:** the proposal adds behavior or changes
  an external commitment. Give it an explicit level, compatibility analysis,
  and, when it changes a durable decision, an ADR.

P0/P1 safety and correctness fixes use a fast path. They do not wait for a
large SPEC rewrite, a new ADR number, or unrelated documentation cleanup. The
same pull request may correct the smallest affected SPEC/index statement and
stale tests. The fast path never waives identity, side-effect, exact-artifact,
review, or evidence gates.

## Validation boundary

`scripts/validate_spec.py` performs structural checks only: required fields,
legal enums, unique identifiers, valid repository references, core test/source
coverage, ADR existence, duplicate mappings, and simple reference cycles. It
does not judge runtime behavior, bind line numbers or function names, require
ADRs for normal refactors, freeze current tests, or block P0/P1 work on
noncritical documentation.

Behavioral correctness remains the responsibility of focused tests, exact
artifact review, and the evidence process in [`docs/RELEASING.md`](docs/RELEASING.md).

## Schema-v3 State Gateway boundary

For a new Adaptive Pack, the installed MCP `state_gateway` is the only writer
of canonical control-plane state. Controller, Worker, Reviewer, Local Verifier,
and any external Supervisor have no authority to patch `.codex-loop/**` or
create a session State-Writer. The public route sequence is `INITIALIZE` or
`INITIALIZE_SUCCESSOR`, narrow host-cooperative bootstrap `REGISTER_TASK` /
`REGISTER_HEARTBEAT`,
`PREPARE_ROUTE`, `RECORD_ROUTE_SENT`, and `ACK_ROUTE_RESULT`; `REPORT_RECOVERY`
may ACK the same existing outbox after a lost task index or stdout, but cannot
create another product dispatch. `ADVANCE_ROADMAP` derives a nonfinal next Goal
from the unchanged canonical registry. `PREPARE_FINALIZATION` followed by an
actual `automation_update` pause and readback, bound to the host-attested
Controller turn, and `ACK_FINALIZATION` is the schema-v3 finalization path.
`PREPARE_FINALIZATION` leaves `terminal_status` null and creates only a
PREPARED finalization outbox; only the pause/readback-bound ACK creates the
terminal projection. Schema v3 is host-cooperative rather than Byzantine: it
binds real App return values and readback to the current host-attested
Controller turn, but does not claim a provider-signed subtool result which the
App does not expose. A future `x-codex-app-action-receipt-v1` carrier is an
optional stronger attestation; its absence is not a normal-path blocker.
For `RECORD_ROUTE_SENT`, the Controller submits only the returned target thread
id and observation time from one real send. Gateway compares that target to the
single PREPARED outbox and supplies the canonical exact materialized
`payload_digest`; a bare route id, wrong returned target, stale outbox, or a
present-but-mismatched stronger receipt leaves the route unchanged. Send
observation never itself creates PASS.
`RECORD_TRANSPORT_OBSERVATION` likewise binds a real registered-heartbeat
observation to the active heartbeat identity, fingerprint, outbox and observed
time. It cannot fabricate a natural observation without that registered
identity; the optional stronger receipt is validated when present.
Once that threshold reaches `WAITING_TRANSPORT_RECOVERY`, every
`PREPARE_ROUTE` rejects with zero side effects. Existing staged reports and the
original failed outbox remain available only to their bounded recovery/ACK
operations; no new product or report-only dispatch is created. After that
retained outbox is completed/ACKed and its route is recovered/ACKed,
`ACK_TRANSPORT_RECOVERY` requires an ACTIVE update/readback for the same
registered heartbeat and atomically restores `RUNNING`. It preserves the
historical failure count and cannot create PASS, a dispatch, or a repair
attempt; an unresolved/foreign outbox or wrong heartbeat receipt is zero-effect.
Its public `parameters` are exactly
`{active_automation_receipt:{automation_id,status,automation_name,kind,target_thread_id,rrule,prompt_digest,prompt_normalization,observed_at}}`;
`status` is `ACTIVE`, `kind` is `HEARTBEAT`, and every identity field must match
the registered heartbeat. The Gateway derives the current source turn; Pack
callers do not copy it.
Because the App update necessarily precedes the Gateway ACK, a rejection is
classified from the post-call canonical state with `routing_permitted=false`.
If canonical is still WAITING/PAUSED, it returns
`PAUSE_SAME_HEARTBEAT_AND_READBACK` and the host immediately performs that
rollback. If a concurrent/idempotent recovery already left canonical
HEALTHY/RUNNING, it returns `READ_STATE_ALREADY_RECOVERED` and the host must not
pause. If canonical cannot be read, it returns
`READ_STATE_AND_RECONCILE_HEARTBEAT`; no route is legal before reconciliation.
Target role reports likewise require the target's MCP-attested `STAGE_REPORT`
call before the Controller can ACK them. A Worker PASS may bind exact validation
files through `evidence_sources`; runtime reads them only from the registered
target worktree, stages immutable bytes, and the Gateway archives those bytes
atomically with the report on the original outbox. An unarchived, unreferenced,
wrong-digest, wrong-thread, or stale evidence file has no canonical side effect.
One report may introduce at most 15 evidence files so the report plus evidence
bundle remains within the canonical 16-artifact transaction bound; every file
is size-checked before bounded reading, and any case-insensitive alias of a
`.codex-loop/**` source is forbidden.
v3 disables native Goal adapters and
records `GATEWAY_NO_NATIVE_GOAL` as a local sentinel, never an external
Goal-tool receipt.

The Gateway, rather than Controller-assembled payloads, derives current
freshness, validation, review handoff, artifact identity, route lease and
outbox. A PASS projection is valid only for the same Goal's current artifact,
current Worker dispatch and PASS formal report. `BLOCKED`, stale artifact, or
stale dispatch evidence is non-PASS.

Schema v1/v2 State-Writer state remains readable for audit and can move to v3
only by an explicit paused/quiescent `MIGRATE_V2_TO_V3`. A terminal predecessor
is immutable evidence; a continuation has a new root and uses
`INITIALIZE_SUCCESSOR`. The exact additional invariants and their executable
surfaces are in the index and ADR 0010.
