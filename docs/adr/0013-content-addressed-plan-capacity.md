# ADR 0013: Conversational intake and content-addressed plan capacity

- Status: Accepted
- Baseline: public v4.0.0 peeled commit `f7b62cb2fd9bd6ab4b038a8384bced4b7e74cbd9`
- Compatibility: v4.0 snapshots remain readable and resumable; no migration or dual write

## Context

The v4.0 eager representation places the full Goal plan and future runtime
references in `CreateLoop`. Long plans can therefore reach the fixed command
capacity before the first Attempt exists. At the same time, the expert JSON
entry is too demanding for ordinary users who begin with a sentence or PRD.
The v4.1 change must solve both constraints without adding a second state
writer, migrating existing stores, or weakening explicit confirmation.

## Decision

New loops use `CONTENT_ADDRESSED_V1`. PREPARE canonicalizes one closed
`loopskill-plan-v1` document and a `loopskill-plan-index-v1`, writes both only
to an owner-only preparation bundle, and reports capacity using the same
encoder and prompt materializer used at START. START writes the exact plan and
index bytes through `StorePort.put_blob`, reads them back through
`StorePort.get_blob`, and then submits one compact `CreateLoop`.

The compact snapshot stores plan identity, current order, current index, and
only materialized runtime objects. `AdvanceGoal` remains the sole transition
that completes one Goal and atomically activates the next Goal with one durable
Attempt and outbox descriptor. The Kernel never reads files or blobs.

Plan-bound authority uses immutable `AuthorityGrantV2` grants with the closed
`PLAN_DERIVED_V1` selector. Runtime references are derived from loop identity,
plan digest, stable Goal ID, Goal slice digest, and reference kind. Grants are
persisted only by `CreateLoop`; no grant mutation, renewal process, reconciler,
daemon, supervisor, second Store, or second writer is introduced.

Adaptive mode may only create a new immutable PlanIndex that reorders pending
members of the already confirmed Goal set. Scope, budget, permission,
acceptance, stop-condition, or Goal-content changes require a new
INTAKE/PREPARE/CONFIRM cycle.

## Capacity contract

The one authoritative capacity contract lives in
`protocol/v4/loopskill-v4.protocol.json` and generates Python constants, JSON
schema, API summary, and identity fixtures. v4.1 admits 1–32 Goals, a 256 KiB
text/Markdown source, and a 128 KiB canonical plan. Release admission blocks a
CreateLoop above 8 KiB or 64 collection members and a materialized Host prompt
above 24 KiB. Existing 16 KiB, 128-member, and 32 KiB hard limits remain
fail-closed backstops, not product targets.

## Compatibility boundary

Snapshots without `goal_plan.storage_mode` are interpreted only as
`EAGER_V4_0`. Their status, private export, and original reducer continuation
remain available for one v4 major cycle. v4.1 never creates, migrates, rewrites,
or dual-writes that representation. Removal requires a v5 ADR and explicit
authorization.

## Consequences

An immutable plan blob written before a failed CreateLoop may remain as a safe,
unreferenced local orphan. It is not deleted automatically. Public projections
exclude source digest, source path, raw PRD, and blob content; explicit private
backup retains the complete canonical Store. The conversational compiler is a
candidate generator, while closed schema, capacity admission, user
confirmation, Entry, Kernel, Store, and Adapter remain the trusted controls.

## Evolution

The capacity values and schema version may evolve only through the single
protocol manifest and regenerated artifacts. Any change to Goal membership,
authority, confirmation, compatibility, or hard limits requires a subsequent
reviewed ADR. Removing `EAGER_V4_0` continuation remains a v5 decision; it is
not an implicit v4.1 cleanup.
