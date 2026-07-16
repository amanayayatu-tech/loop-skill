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

- bounded direct non-PTY input and strict framing;
- one business route per real host turn with host attestation;
- durable outboxes, receipts, replay, and lost-output recovery;
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
