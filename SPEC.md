# LoopSkill 4 specification

This file is the short normative product entry for LoopSkill 4. Exact wire
shapes come only from `protocol/v4/loopskill-v4.protocol.json`; reducer
invariants, filesystem race defenses, and Host effect contracts remain
separate implementation authorities for their own domains. No JSON Schema can
express all state transitions, provenance, filesystem races, or external
transactions.

## Normative levels

- `CORE_INVARIANT`: violation can corrupt authority, state, evidence, or
  finalization.
- `PUBLIC_CONTRACT`: stable user-visible behavior or supported interface.
- `PROVISIONAL`: direction that is not independently a release claim.
- `IMPLEMENTATION_NOTE`: replaceable mechanism.
- `DEFERRED`: deliberately unavailable and fail-closed where surfaced.

The machine-readable index is
[`docs/spec/invariants.yaml`](docs/spec/invariants.yaml). It indexes safety
properties; it is not a wire schema, runtime writer, recovery registry, or
second governance system.

## Authority

For each question, use the source designed to answer it:

1. typed protocol manifest for command/event/reference/receipt/capability/error
   wire literals and fields;
2. Kernel reducer for legal transitions and aggregate invariants;
3. Store port/implementation for transaction, CAS, idempotency, outbox, backup,
   and canonical export semantics;
4. Artifact libraries for capture, path confinement, immutable blob identity,
   and filesystem races;
5. Codex Host Adapter contract for Host capability, receipt provenance,
   create/read/send/readback, and external-effect execution;
6. Entry and optional policy contracts for user interaction, planning, roles,
   bounded repair, and human decisions;
7. accepted ADRs for durable decisions and this SPEC for active safety
   properties.

Generated schemas, API summaries, CLI types, and conformance fixtures consume
the manifest; they cannot define parallel wire literals. README and examples
explain the product but cannot grant authority.

## Product boundary

The default composition is:

`Entry → Kernel + one SQLite Store + Artifact libraries + one Codex Host Adapter`

Entry is the composition root. Kernel depends only on the typed protocol and
ports. Store never controls Host; Host and Artifact implementations never write
canonical state. One transactional authority may maintain orthogonal aggregate
and event streams without collapsing them into one giant enum.

Kernel must not import Codex/App, Host enums, policy, compatibility/importer,
UI/CLI, Git/subprocess, filesystem mutation, SQLite concrete code, Pack
rendering, installer, or paper/Oracle apparatus. The v4 import graph is
acyclic. Standard/Adaptive and advanced roles/repair/decision surfaces are
optional policy and are removable from the minimal profile.

## Entry and authority boundary

The ordinary flow is `INTAKE → PREPARE → CONFIRM → START`.

- Intake is read-only and creates no loop, Host task, heartbeat, or effect. It
  returns exactly `READY_FOR_LOOP`, `NEEDS_CLARIFICATION`, `BLOCKED`, or
  `DIRECT_TASK_RECOMMENDED` with the stable seven-section report.
- Prepare writes only local typed manifest and human review artifacts. It has
  zero Host/execution effects.
- Confirm displays Goal, write scope, budget, external actions, acceptance,
  stop, and publication boundaries. Authority binds every prepared digest;
  content or boundary change invalidates it.
- Start requires a valid unchanged confirmation before one canonical startup
  Attempt. Noninteractive fallback cannot bypass confirmation.

Operation ID, protocol version, Actor/Grant, subject references, expected
revision, receipt, digest, timestamp, and Host identity are machine-constructed,
parsed, or verified. User/model input supplies semantic payload only. A control
identity copied from model text receives no authority.

## State and concurrency

Concurrency uses per-loop revision CAS. Each accepted operation atomically
commits operation receipt, snapshot, ordered events, and any outbox/Attempt
record. Identical replay produces no second commit/event/handle/effect; the
same operation ID with changed request bytes is an idempotency conflict.

Lifecycle, Delivery/ExternalEffect, Goal, Result/Report, Artifact, Review,
Finalization, and Assurance are orthogonal subjects. Canonical snapshots retain
current Result, Report, and finalization subject bindings. `UNKNOWN` or
`UNVERIFIABLE` assurance may coexist with a staged or acknowledged local Result;
it cannot be relabeled strict completion.

Terminal evidence is immutable. A successor may reference but never rewrite
its predecessor. Pause/resume/stop and bounded repair are explicit CAS
transitions; repair exhaustion leads to an external wait, human decision,
honest limitation, or stop—never an unbounded Supervisor loop.

## External effects and guarantees

One durable `AttemptRef` owns one automatic attempt. Execution ownership and
budget are committed before the provider call; after invocation starts, blind
resend is forbidden. Crash windows distinguish local commit, provider invoke,
lost response, local observation, and late authoritative readback.

LoopSkill may claim:

- exactly-once local acceptance for one operation ID and request;
- deterministic local Store/outbox recovery after crash;
- effectively-once external effect only when provider idempotency and
  authoritative readback both apply;
- otherwise at-most-one automatic attempt, with outcome possibly `UNKNOWN`.

It does not claim an exactly-once transaction across SQLite, Codex, Git, or
network boundaries. A late authoritative observation may strengthen the same
Attempt/subject identity. It cannot authorize resend or fabricate history.

Execution terminality and assurance are orthogonal. Cooperative work may
honestly terminate with `LIMITATION`/`UNVERIFIABLE`; strict Host-attested claims
still require authoritative readback.

## Artifact, review, and finalization

Canonical JSON/hash, content addressing, immutable blobs, report/evidence
normalization, and Git/non-Git/new-Git capture are libraries behind ports.
Capture rejects traversal, symlink, case-fold aliases, special files,
unbounded input, and open/read races. Binary, untracked, empty-diff, add/modify/
delete, and before/after identity remain explicit.

Artifact correctness, workflow closure, Host assurance, external-effect
finalization, empirical result, and public release are separate claims. Review
PASS/REPAIR/LIMITATION binds the exact current artifact/dispatch/report chain.
Finalization preparation, readback, and acknowledgement preserve that chain;
duplicate finalization is idempotent.

## Projections and privacy

Status, Doctor, audit index, rejection view, summaries, business timeline,
archive, risk scan, privacy export, and metrics are rebuildable read-only
projections. They cannot become a second ledger, writer, retry authority, or
recovery registry. Actionable recovery text derives from typed errors and
capabilities.

Privacy-safe export excludes prompts, chat, raw Host task/thread/turn identity,
private paths, PII, secrets, and raw logs. Risk scan exports categories and
digests, not credential bytes.

## v3 hard break

LoopSkill 4 preserves v3 safety semantics by redesign, not runtime
compatibility. It ships no v3 importer, repair, read/shadow path, Pack runtime,
legacy CLI alias, MCP State Gateway, State-Writer, 97-field write API, dual
write, or automatic migration. A recognized v3 root/state/Pack receives stable
`USER_UNSUPPORTED_LEGACY_VERSION`, a direct v3.3.8 link, and zero writes.

The independent v3.3.8 tag/Release and historical evidence remain unchanged.
Old P6 compatibility implementation/evidence is predecessor evidence and is
excluded from v4 release acceptance.

## Distribution and release

v4 installs under a distinct receipt-bound identity. Install/uninstall never
add, change, or remove `[mcp_servers.*]`, preserve existing Codex `config.toml`
bytes, require no LoopSkill-specific App restart, and never overwrite an
independent v3 install. Conflict and drift fail before mutation; bounded
process-fault windows recover to exact pre-state or exact committed post-state.

A public release requires deterministic tests, full corpus and fault gates,
architecture/anti-bloat/preservation validators, Linux/macOS isolated install,
documentation parity, privacy/security/dependency/SBOM checks, exact-SHA local
Codex App canary, independent review, green PR/main/tag CI, annotated tag, and
public GitHub Release readback. No single gate implies patch-success or
long-horizon efficacy.

## Safe evolution

Fix implementation and tests when behavior violates an active contract. Fix
the specification as well when evidence shows the written rule is unsafe.
Changing stable wire shape, user authority, v3 data safety, or public claim
boundary requires an explicit reviewed product decision. Never change metrics,
fixtures, exclusions, or expected results to obtain a preferred PASS.
