# ADR 0012: Select SQLite for the LoopSkill 4 local canonical store

- Status: Accepted for LoopSkill 4 local development
- Date: 2026-07-27
- Amends: ADR 0011 OD-1 candidate decision
- Scope: local operation acceptance, reducer snapshot, events, outbox, and immutable blob index

## Context

ADR 0011 authorized SQLite only as a candidate spike. Selection required the
same reducer semantics as the in-memory oracle plus evidence for transaction
atomicity, crash recovery, backup/restore, active readers, bounded writer
contention, manual canonical export, corruption detection, and macOS filesystem
behavior. Those gates have now passed on public synthetic fixtures.

## Decision

LoopSkill 4 selects SQLite as its local canonical transactional store. The
in-memory implementation remains a disposable semantic oracle and fault
fixture, not a second production writer.

One `BEGIN IMMEDIATE` transaction owns each accepted or rejected operation.
For an accepted mutation it atomically commits:

- operation ID, request digest, and exact result;
- ordered events and their contiguous sequence;
- canonical reducer snapshot, per-loop revision, and snapshot digest; and
- the Attempt/outbox projection required for effect recovery.

The implementation uses WAL mode, `synchronous=FULL`, foreign keys, bounded
busy timeout, owner-only database files, strict tables, explicit schema
version, canonical JSON bytes, and digest verification. An immutable blob table
is content-addressed; manual export exposes only its digest and byte count while
backup preserves the bytes.

Exactly one SQLite database is the canonical local writer for a v4 root. Dual
write, a reconciler database, a Supervisor, or an independent outbox writer are
forbidden. A busy writer fails within the configured bound without partial
state. A rejected operation is recorded in the same write transaction and its
exact replay is deterministic.

## Recovery and guarantee boundary

SQLite provides atomic durable local acceptance and deterministic recovery
across the database tables above. A crash before commit restores the exact
pre-state. A crash after commit but before response restores the exact committed
post-state and exact operation replay returns the original result.

This decision does **not** make SQLite, Codex, Git, a provider, and the network
one transaction. External delivery remains at-most-one automatic attempt and
may be UNKNOWN. Only provider idempotency plus authoritative readback may be
described as effectively-once.

## Backup, inspection, and corruption

- backup uses SQLite's online backup API into a new owner-only destination;
- restore is opening the backup as a normal v4 store and passing full integrity
  verification;
- canonical export is deterministic and manually readable without becoming a
  second writable format;
- integrity verification combines SQLite `quick_check`, canonical decoding,
  snapshot/revision/event/outbox consistency, and blob digest/length checks;
- malformed database bytes, noncanonical JSON, digest mismatch, or projection
  mismatch fail closed; and
- rollback does not reverse-convert v4 data. Existing v3 roots remain separate
  and unchanged.

## Evidence and limitations

The P1 evidence covers 11 operations across nine durable boundaries (99 crash
cases), semantic equality with the in-memory oracle, active WAL reader behavior,
bounded writer contention, exact backup/restore, deterministic export,
immutable blobs, logical/physical corruption, Unicode paths, owner-only modes,
symlink rejection, and close/reopen on macOS.

This is local persistence conformance, not Host Adapter conformance, migration
readiness, effectiveness evidence, or release approval. Schema migration policy
and long-running production performance remain later gates; incompatible schema
changes require an explicit store-version migration, never silent reinterpretation.
