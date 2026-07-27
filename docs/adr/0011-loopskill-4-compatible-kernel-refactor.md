# ADR 0011: LoopSkill 4.0 compatible kernel refactor

- Status: Accepted for the bounded alpha pure-kernel slice; all other implementation remains unauthorized
- Date: 2026-07-27
- Decision scope: LoopSkill 4.0 architecture, authority boundary, recovery semantics, compatibility, and gates
- Conformance design: `docs/conformance/loopskill-4-conformance-corpus-design.md`

## Authorization and source identities

The author selects route B: replace the protocol kernel, persistence model, and
Host boundary while reusing provenance-bound v3 safety assets. This ADR now
authorizes only the disposable alpha pure-kernel slice described below, and
only after the conformance design passes its implementation-readiness checks.

This authorization excludes SQLite implementation or selection, a Codex Host
Adapter, provider or network calls, Git/filesystem artifact capture, v3 import,
Pack/MCP/CLI work, installation, release, tag, push, PR, real-loop migration,
and real App canaries.

The identities below are separate products/evidence sources:

| Identity | Exact object | Role |
| --- | --- | --- |
| Public maintenance baseline | `origin/main` and `v3.3.8` at `843945d9d34e7f065b65d9172ea4a2df66c0f2e3` | Public v3 maintenance and future alpha branch base |
| Paper treatment/reference | peeled commit `54442e22c3ce483823c911dfa8d03a52c85922e6` from annotated tag `paper-treatment-v3.3.12` | Read-only conformance source; not a public release |
| Review carrier | detached HEAD `a69ba0b0b77818740934daec07dba8c799246ffe` | Documentation carrier only; never a development base |

Future implementation starts from a newly verified clean `origin/main` in an
isolated worktree. Only the exact two design documents are carried from the
review carrier. Treatment assets are selected by full SHA/path/symbol
provenance; the treatment commit is not promoted or merged wholesale.

## Context and evidence strength

### Confirmed by repository code or history

- Protocol meaning is manually mirrored across runtime, MCP, schema, scaffold,
  Pack prose, tests, and documentation.
- v3.3.9 through v3.3.12 required cross-surface fixes for repository mode,
  report staging, heartbeat enum, and prepared-route replay behavior.
- Cooperative paths can still accept Controller-carried host identity fields
  when stronger Host action receipts are absent.
- Codex project/task/thread/heartbeat/trust/model/readback details cross the
  present core boundary.
- Local CAS/journal recovery is stronger than recovery of external App effects;
  the local store and provider cannot commit atomically.
- Git and non-Git capture algorithms are distinct, while their exposed mode is
  coarser than the actual capabilities.
- v3 uses a large state/control surface with several route, outbox, artifact,
  report, review, projection, and recovery records.

### Strong risks, not yet confirmed defects

- A compatibility translator could leak v3 shape or Host assumptions into v4.
- A temporary dual stack could become permanent.
- `new_git` lacks evidence equivalent to a full existing-Git/non-Git vertical
  path.
- A new store could reduce manual inspectability or introduce backup and
  concurrency faults.
- An over-minimal reducer could erase necessary delivery, result, report,
  artifact, review, and finalization identities.

### Unconfirmed hypotheses

- LLM copying is the sole cause of closure failures.
- Host memory contamination caused the observed failures.
- State-field count alone causes runtime failure.
- A clean-slate rewrite automatically improves liveness.
- One JSON Schema can express transitions, provenance, races, and distributed
  effect semantics.
- Fail-closed behavior alone proves architectural superiority.

The exploratory observation that 0 of 19 scored B3 workflows reached
`FINALIZATION_ACKED` is an architecture-review signal only. Administrative
post-interim truncation makes it exploratory/nonconfirmatory; it is not a causal
or superiority conclusion.

## Decision and rejected routes

LoopSkill 4.0 uses a typed protocol manifest, deterministic reducer,
transactional store contract, explicit authority grants, orthogonal subject
aggregates, artifact ports, and Host anti-corruption adapters. It reuses v3
algorithms and fault traces selectively rather than retaining v3 canonical
shape.

Rejected:

- **v3 patches renamed 4.0**: preserves manual mirrors, Host leakage, and
  multi-ledger verification cost. v3.3.8 receives bounded safety maintenance
  only.
- **clean-slate without migration/conformance**: discards proven identity,
  replay, path, artifact, and crash evidence and creates an unverified rewrite.

## Product and dependency boundary

### Core owns

- typed command/event/reference/receipt/capability/error declarations;
- deterministic reducer invariants;
- machine authority evaluation;
- per-loop CAS, operation idempotency, ordered event append, and effect outbox
  semantics;
- Delivery, Attempt, Result, Report, Artifact, Review, Finalization, execution
  disposition, and closure-assurance identities; and
- local recovery and finalization eligibility.

### Optional policy packs own

Roadmaps, defect families, complex repair/reviewer matrices, Decision Cards,
P1 governance, and experiment apparatus classification. A policy pack may
submit authorized semantic commands. It cannot become a writer, receipt issuer,
recovery Supervisor, or invariant bypass.

### Libraries and ports own

Canonical JSON/hash, content addressing, Git/non-Git/new-Git artifact capture,
path confinement, immutable blobs, report/evidence normalization, and store
implementations.

### Codex Host Adapter owns

Project/task/thread/turn identity, create/read/send, heartbeat/schedule,
trust/sandbox/model receipts, memory capability, App enums/schema negotiation,
eventual indexing, lifecycle readback, provider invocation, and translation to
bounded protocol receipts.

The Adapter reports unavailable/unverifiable capabilities honestly. It cannot
fabricate a receipt, make the Host transactional, or mutate canonical state.

### Kernel import prohibition

The kernel must not import or invoke Codex/App modules, Host enums, Git,
`subprocess`, filesystem mutation, Pack/prompt rendering, SQLite, network
clients, v3 migration, or paper/Oracle/apparatus code. Alpha tests enforce this
as a blocking dependency scan.

## User-experience compatibility requirement

The v4 internals may change, but the default user entry model is a normative
compatibility boundary:

- a fresh user supplies one goal/input file **or** invokes one public main
  command, and that single public action creates and starts one loop; the final
  command name is deferred to CLI design, but multi-step control-plane
  choreography is forbidden on the happy path;
- the number of control identities an ordinary user must provide is exactly
  zero. Users do not fill in or relay thread/task/route/effect/artifact/review/
  finalization IDs, SHAs, receipts, Pack identities, Gateway schemas, Host
  enums, heartbeat/readback/retry controls, or Git/non-Git capture algorithms;
- operation IDs, handles, Actor/Grant references, revisions, receipts, content
  digests, and Host identities are generated, resolved, or injected by trusted
  machine components. Model/user text containing such a value never grants it
  authority;
- the minimal path requires no policy-pack installation, selection, or
  understanding. Roadmap, repair, and reviewer policies are opt-in advanced
  features;
- default status presents only goal, progress, result, limitations, and
  actionable recovery choices. Internal identities and receipts appear only in
  explicit diagnostics/export mode;
- v3-to-v4 use requires explicit preview and confirmation, is cancellable, and
  leaves the v3 bytes readable and unchanged. A v3 user-entry compatibility
  facade remains for one major cycle, but it is not a canonical dual writer;
- UNKNOWN and UNVERIFIABLE are intentionally visible outcomes. They must not be
  rendered as success or trigger a blind automatic resend; and
- compatibility does not promise byte-identical Controller Packs, every old
  CLI flag, or old wording. It promises no increase in default startup action
  complexity, no control-plane leakage, and no implicit v3 migration.

The future public entry is a facade over Kernel/Adapter machine authority, not
a Supervisor, second writer, or second control plane. These requirements are
reserved in alpha, become blocking in beta, and require a real disposable
new-user usability canary at RC.

## Protocol authority

“Single protocol source” has three deliberately separate authorities:

1. **typed protocol manifest** owns command, event, reference, receipt,
   capability, error, and wire shape;
2. **reducer invariants** own legal transitions, subject chain, revision and
   finalization rules; and
3. **adapter/library contracts** own provider provenance, readback,
   filesystem/Git races, and external effects.

Generated JSON Schema validates shape only. It cannot express reducer
transitions, authority provenance, filesystem races, or distributed atomicity.

## Machine authority boundary

### Actor and grant

`ActorRef` is an opaque machine-resolved identity with `loop_namespace`,
`actor_kind`, immutable identity digest, and issuer provenance.

`AuthorityGrantRef` resolves to an immutable grant containing:

- issuer and grantee `ActorRef`;
- allowed command types;
- exact loop or create-loop namespace scope;
- allowed subject kinds and optional exact subject references;
- `not_before` and `expires_at` from the trusted machine clock;
- grant nonce and canonical digest; and
- issuer trust class.

The authority registry is immutable input to the reducer/store boundary. It is
not supplied in semantic payload and is not inferred from conversation text.

### Machine-constructed mutation envelope

Every mutation command has exactly:

```text
operation_id
command_type
protocol_version
actor_ref
authority_grant_ref
subject { loop_ref, subject_kind, subject_ref? }
expected_loop_revision
expected_subject_revisions { subject_ref: revision }
issued_at
machine_bindings { resolved_refs, allocate_refs, receipt_refs }
semantic_payload
request_digest
```

Ownership:

- the machine allocates `operation_id`, selects the manifest `command_type`,
  resolves actor/grant/subject references, reads revisions, sets time/version,
  constructs closed `machine_bindings` for
  resolved references, newly allocated references, and receipt references,
  validates the semantic schema, and computes `request_digest` over the
  canonical envelope excluding the digest;
- user/LLM input may populate only command-specific `semantic_payload` fields;
  the machine may normalize bounded text but may not invent its meaning; and
- receipt references, allocated/resolved handles, actor/grant, time, protocol
  version, revisions, and request digest copied from model text have no
  authority. Structured attempts to place them in semantic payload fail with
  `CONTROL_FIELD_INJECTION`.

A textual sentence may mention an ID. Authority is never derived from that
text. Unknown semantic keys are rejected; reserved control keys are never
promoted.

Authorization checks bind actor, grant issuer/trust, validity interval, command
type, loop, subject kind/reference, and current subject revisions. Forged,
expired, future, cross-loop, wrong-kind, or wrong-scope values fail closed with
zero canonical mutation and zero external effect.

## CAS, revision, and replay units

The only write-CAS unit is **per-loop revision**:

- each accepted mutation touching one loop increments `loop_revision` exactly
  once;
- `expected_loop_revision` is required for every mutation, including
  `CreateLoop` with expected revision `0`;
- a command may touch only one loop in alpha;
- each touched aggregate has its own revision incremented once by the same
  accepted command;
- `expected_subject_revisions` are freshness/invariant guards, not independent
  write CAS units; and
- a store commit counter may exist as diagnostics but is absent from protocol
  responses, canonical snapshots, and command CAS.

Idempotency lookup uses `(loop_ref, operation_id)` and canonical request digest:

1. exact accepted replay returns the original result/events/snapshot digest
   without rechecking current revisions or causing another commit/effect;
2. same operation ID with a different digest returns
   `IDEMPOTENCY_CONFLICT`;
3. a first-time command then checks authority and CAS; and
4. a rejected operation is deduplicated in a separate rejection record. Exact
   rejection replay returns the original rejection without another record;
   retry after changed conditions requires a new operation ID.

## Orthogonal canonical subjects

### LoopExecution

- state: `CREATED`, `ACTIVE`, `PAUSED`, `FINALIZING`, `TERMINAL`;
- terminal disposition, set only at `TERMINAL`: `SUCCEEDED`, `LIMITATION`, or
  `BLOCKED`.

Execution terminality is independent from closure assurance. Terminal execution
never reopens; later evidence can strengthen assurance without changing work or
the recorded disposition.

### ClosureAssurance

Monotonic strength: `NONE`, `LOCAL`, `COOPERATIVE`, `STRICT`.

- `LOCAL`: only local reducer/store/artifact evidence is verified;
- `COOPERATIVE`: bounded Host/provider observation exists but is not
  authoritative;
- `STRICT`: every Host-dependent subject in the current finalization chain has
  exact trusted issuer, identity, freshness, and authoritative readback.

`STRICT` is an assurance claim, not a synonym for terminal execution.

### Goal

State: `READY`, `ACTIVE`, `DONE`, `BLOCKED`, `SUPERSEDED`. Goal identity and
objective digest are core; roadmap and reprioritization policy are not.

### Route

Route is an immutable subject binding the current Goal, target resource,
semantic intent digest, and DeliveryRef. The reducer stores the intent digest so
provider request identity is derived from canonical state rather than event
history, model memory, or a hidden fixture map.

### Delivery and Attempt

Delivery state: `PREPARED`, `ATTEMPT_COMMITTED`, `OBSERVED`, `UNKNOWN`,
`UNVERIFIABLE`.

Each Delivery has at most one automatic `AttemptRef` in alpha. Attempt records
bind loop, delivery, target resource, executor actor/grant, ordinal, provider
request digest, provider idempotency key when available, budget consumption,
and observation receipt. Attempt state is `COMMITTED`, `OBSERVED`, `UNKNOWN`,
or `UNVERIFIABLE`.

Delivery observation never represents Result acceptance.

### Result

State: `STAGED`, `ACKNOWLEDGED`, `STALE`. Result binds route, Delivery,
Attempt, producing Actor, semantic outcome digest, `ReportRef`, and after
acknowledgement the current `ArtifactRef`.

### Report

State: `STAGED`, `ACCEPTED`, `STALE`. Report binds exact Result, author Actor,
bounded normalized bytes/digest, and source receipt/provenance.

### Artifact

State: `CAPTURED`, `VERIFIED`, `STALE`. Artifact binds exact Result, capture
algorithm/capability, before/after identity, content digest, and receipt.

### Review

State/verdict: `PENDING`, `PASS`, `REPAIR`, `LIMITATION`. Review binds the
current Result, Report, Artifact, their revisions, reviewer Actor/grant, and
the canonical subject-chain digest. A LIMITATION cannot become PASS during
finalization.

### Finalization

State: `PREPARED`, `EXECUTION_CLOSED`. Finalization binds exact Goal, Route,
Delivery, Attempt, Result, Report, Artifact, Review, all current revisions,
requested terminal disposition, closure-assurance basis, and subject-chain
digest.

Closing execution appends `ExecutionFinalized`. If exact strict readback is
also present, the same command may append `StrictFinalizationAcknowledged` and
set assurance `STRICT`. Otherwise execution can still terminate honestly with
`LIMITATION` and `LOCAL`/`COOPERATIVE` assurance.

Later authoritative evidence may change Delivery/Attempt from `UNKNOWN` or
`UNVERIFIABLE` to `OBSERVED` only under the exact original Attempt identity. A
separate authorized `StrengthenClosureAssurance` may then raise assurance for
the unchanged finalization chain. It never reopens execution, changes the
terminal disposition, replaces evidence, or creates a new attempt.

### Coexistence rules

| Delivery | Result | Permitted meaning |
| --- | --- | --- |
| `OBSERVED` | `STAGED`/`ACKNOWLEDGED` | Provider action is authoritatively observed; Result remains independently validated |
| `UNKNOWN` | absent | Attempt consumed; outcome unresolved; explicit limited/blocked closure is allowed |
| `UNKNOWN` | `STAGED`/`ACKNOWLEDGED` | Result arrived through independently bound evidence; work may close with limitation, never strict Host claim |
| `UNVERIFIABLE` | `STAGED`/`ACKNOWLEDGED` | Cooperative evidence may support limited closure; strict assurance forbidden |
| `OBSERVED` after late readback | existing Result | No resend/reexecution; assurance may be strengthened for the unchanged chain |

No state infers provider delivery from Result existence or Result acceptance
from delivery observation.

## Minimal command/event/error catalog

### Mutation commands

`CreateLoop`, `BindHostResource`, `PrepareRoute`, `BeginEffectDelivery`,
`RecordEffectObservation`, `StageResult`, `AcknowledgeResult`, `RecordReview`,
`AdvanceGoal`, `PauseLoop`, `ResumeLoop`, `PrepareFinalization`,
`CloseExecution`, `StrengthenClosureAssurance`, and later
`ImportV3Snapshot`.

Queries (`ReadStatus`, `ReadDelivery`, `ReadResult`, `ReadCapabilities`, export)
are read-only and have no operation/CAS side effects.

### Events

`LoopCreated`, `GoalRegistered`, `GoalActivated`, `HostResourceBound`,
`RoutePrepared`, `DeliveryAttemptCommitted`, `DeliveryObserved`,
`DeliveryUnknown`, `DeliveryUnverifiable`, `LateDeliveryObserved`,
`ResultStaged`, `ReportStaged`, `ArtifactCaptured`, `ArtifactVerified`,
`ArtifactStale`, `ReportAccepted`, `ResultAcknowledged`, `ReviewRecorded`,
`GoalAdvanced`, `LoopPaused`, `LoopResumed`, `FinalizationPrepared`,
`ExecutionFinalized`, `StrictFinalizationAcknowledged`,
`ClosureAssuranceStrengthened`, `V3SnapshotImported`, and
`OperationRejected`.

### References

`LoopRef`, `ActorRef`, `AuthorityGrantRef`, `GoalRef`, `HostResourceRef`,
`RouteRef`, `DeliveryRef`, `AttemptRef`, `ResultRef`, `ReportRef`,
`ArtifactRef`, `ReviewRef`, `FinalizationRef`, and `ReceiptRef`.

### Stable alpha errors

`INVALID_COMMAND`, `UNSUPPORTED_PROTOCOL_VERSION`, `RESOURCE_LIMIT_EXCEEDED`,
`INVALID_UTF8`, `CONTROL_FIELD_INJECTION`, `INVALID_AUTHORITY`,
`AUTHORITY_EXPIRED`, `AUTHORITY_SCOPE_MISMATCH`, `STALE_LOOP_REVISION`,
`STALE_SUBJECT_REVISION`, `IDEMPOTENCY_CONFLICT`, `FOREIGN_REFERENCE`,
`WRONG_REFERENCE_KIND`, `INVALID_TRANSITION`, `CAPABILITY_UNAVAILABLE`,
`CAPABILITY_UNVERIFIABLE`, `RECEIPT_REQUIRED`,
`RECEIPT_ISSUER_UNTRUSTED`, `RECEIPT_EXPIRED`,
`RECEIPT_IDENTITY_MISMATCH`, `ATTEMPT_ALREADY_CONSUMED`,
`ADAPTER_SCHEMA_DRIFT`, `ARTIFACT_IDENTITY_MISMATCH`, `ARTIFACT_STALE`,
`REPORT_IDENTITY_MISMATCH`, `PATH_CONFINEMENT_VIOLATION`,
`FINALIZATION_PRECONDITION_FAILED`, `MIGRATION_NOT_QUIESCENT`,
`DUAL_WRITE_FORBIDDEN`, `STORE_RECOVERY_REQUIRED`, and
`INTERNAL_INVARIANT_VIOLATION`.

`UNKNOWN` and `UNVERIFIABLE` are Delivery/Attempt states, never acceptance or
error values.

## External-effect executor contract

`PrepareRoute` creates Delivery `PREPARED` with automatic-attempt budget `1`.
`BeginEffectDelivery` is the only command that obtains execution authority:

1. validate executor Actor/grant, current target, route/delivery revisions, and
   remaining budget;
2. atomically allocate `AttemptRef`, bind exact provider request digest and
   optional provider idempotency key, set Delivery `ATTEMPT_COMMITTED`, and
   consume the budget;
3. commit and return the immutable invocation descriptor; and only then
4. permit the external executor to call the provider.

The automatic budget is consumed at local commit, not at provider response.
After that commit no automatic resend is permitted, even if the process dies
before calling the provider. Recovery uses only exact Attempt readback.

| Window | Canonical state after recovery | Permitted next action |
| --- | --- | --- |
| before `BeginEffectDelivery` commit | Delivery `PREPARED`; no Attempt; budget available | retry the same command or issue a new valid operation |
| after commit, before provider invocation | Attempt `COMMITTED`; budget consumed | authoritative readback by exact Attempt/idempotency identity; never resend automatically |
| provider accepted, response lost | Attempt `COMMITTED`; budget consumed | authoritative readback; then OBSERVED or UNKNOWN |
| provider returned, crash before local observation | Attempt `COMMITTED`; budget consumed | same authoritative readback; never use model memory as receipt |
| readback inconclusive/unavailable | Delivery/Attempt `UNKNOWN` | close with limitation/block, or await a late exact readback; no resend |
| cooperative response only | Delivery/Attempt `UNVERIFIABLE` | limited closure or later strict readback |
| late authoritative readback | exact UNKNOWN/UNVERIFIABLE Attempt becomes `OBSERVED` | optionally strengthen assurance; no new Attempt/result/reexecution |

A late observation is accepted only when issuer trust, action, loop, Delivery,
Attempt, target, provider request digest/idempotency key, and freshness all
match. A conflicting observation is rejected and preserved; it never rewrites
the first accepted observation.

No Supervisor, second writer, replacement route, timeout inference, or natural
language recollection may reconstruct the first response or restore the budget.

## Execution terminality and assurance

Execution may terminate as:

- `SUCCEEDED`: required product/result/review chain passes;
- `LIMITATION`: bounded work is honestly closed with missing/unverifiable Host
  evidence, Review LIMITATION, or another declared assurance limitation; or
- `BLOCKED`: an explicit authorized decision states that the goal cannot
  continue.

These dispositions do not imply assurance strength. A cooperative run can
reach `TERMINAL/LIMITATION` instead of remaining indefinitely PAUSED. It may
state local artifact/result facts and the exact limitation, but cannot claim
strict Host-attested completion.

Strict Host completion language requires `ClosureAssurance.STRICT`, which in
turn requires authoritative final lifecycle readback and strict evidence for
every Host-dependent subject in the unchanged finalization chain. Synthetic
strict fixtures validate reducer logic only and cannot support product claims.

## Recovery and guarantee vocabulary

Allowed guarantees:

- exactly-once local acceptance for one `(loop_ref, operation_id,
  request_digest)`;
- one canonical acceptance for an exact Result/Report/Artifact/Review subject
  revision;
- deterministic local recovery of operation result, loop snapshot, event order,
  outbox/Attempt state, and rejection deduplication; and
- deterministic read-only replay.

With provider idempotency key **and** authoritative readback, language may say
`effectively-once`. Otherwise: `at-most-one automatic attempt; outcome may be
UNKNOWN`.

Forbidden guarantees:

- end-to-end exactly-once across store/Codex/Git/network;
- successful delivery from Controller prose or absence of an error;
- Host memory isolation without an explicit capability; or
- scientific/product superiority from alpha correctness.

## Persistence and compatibility

The technology-neutral store atomically commits operation result, loop revision,
touched aggregate revisions, ordered events, and Attempt/outbox changes.

The alpha reference store is in-memory and disposable. SQLite is authorized
only as a later persistence **candidate spike**. It is not preferred or selected
in advance. Selection requires crash, backup/restore, concurrent-reader/writer,
manual-inspection/export, corruption, and supported-filesystem evidence.

Compatibility decisions:

- v3.3.8 remains public maintenance;
- treatment commit `54442e22...` remains a reference only;
- v4 uses a new root/store and never modifies a v3 loop in place;
- read/shadow/import compatibility is approved for one major cycle;
- import has an explicit preview/confirm boundary and cancel leaves the source
  bytes unchanged and the destination absent or empty;
- a one-major-cycle v3 public-entry facade preserves the one-action default
  experience without canonical dual write;
- import requires paused, lease-free, outbox-quiescent dry-run and exact source
  digest;
- dual write and reverse conversion are forbidden;
- rollback means the unchanged v3 loop remains readable by its v3 runtime; and
- v4 does not preserve v3's 97-field canonical write shape.

## Author decisions resolved

| ID | Resolved decision |
| --- | --- |
| `OD-1` | Only a later SQLite persistence spike is authorized as candidate evaluation; no final store is preselected |
| `OD-2` | Execution terminality and assurance are orthogonal; strict Host claim remains strict-only; cooperative work may terminate with limitation |
| `OD-3` | v3 read/shadow/import lasts one major cycle; no dual write or in-place conversion |
| `OD-4` | Measurement definitions are approved; 32 KiB Pack and at least 50% interaction reduction remain candidate beta targets. Same-scenario v3 baseline and final thresholds must be frozen before observing v4 performance; they are not alpha correctness gates |
| `OD-5` | First release supports only a Codex Adapter; kernel remains Host-neutral; no multi-host claim before a second real Adapter passes conformance |

No unresolved product semantic blocks the bounded alpha pure-kernel slice.

## Phases and gates

### Alpha: authorized bounded slice

Allowed only:

- the manifest subset required by the corrected vertical trace;
- deterministic reducer;
- reference in-memory transactional store and fault fixture;
- exact vertical fixture/runner/tests; and
- forbidden-import/dependency conformance checks.

Alpha blocks on the corpus's required alpha instance set, exact replay/conflict,
authority/reference/CAS rejection, declared in-memory fault boundaries,
cooperative non-strict behavior, canonical encoder vectors, and exact final
snapshot digest.

### Alpha.2: not authorized

Codex Adapter and existing-Git/non-Git/new-Git capability profiles, artifact
filesystem implementation, and disposable App canaries require a later
authorization.

### Beta: not authorized

Safe-point importer/shadow read and liveness/cost measurements require a later
authorization. Measurement definitions are accepted, while 32 KiB and 50%
remain candidate targets until the v3 baseline and final thresholds are frozen
before any v4 performance observation. Beta additionally blocks on the UX
corpus: one-action startup, zero user-supplied control identities, no required
policy pack, stable non-leaking errors/status, import preview/cancel safety,
diagnostics opt-in, and frozen same-scenario action/entry-byte budgets.

### RC/stable: not authorized

Install/uninstall/rollback, full Host/artifact fault matrix, real App canary,
independent release review, fixed-SHA `StrictFinalizationAcknowledged`, tag,
release, and migration remain outside this authorization. Every failure and
UNKNOWN must remain preserved; release requires a separate author decision.
RC requires one real, non-research, private-data-free new-user usability canary
from installation instructions or an existing installation through starting a
minimal disposable loop, with no manual transcription of control identity.
Stable retains all UX gates and the one-action default contract.

## Non-goals and safeguards

4.0 alpha does not promise patch success, long-horizon superiority, multi-host
support, Byzantine resistance, Host memory isolation, SQLite suitability,
Codex conformance, artifact correctness, migration readiness, or release
readiness.

| Failure mode | Safeguard |
| --- | --- |
| v3 semantics leak through compatibility | exact anti-corruption mapping; no v3 state shape in kernel |
| dual stack becomes permanent | no dual writes; one-major-cycle compatibility sunset |
| store becomes opaque | later inspection/export/backup gates before selection |
| Adapter invents transactions | explicit Attempt/UNKNOWN/UNVERIFIABLE and receipt trust |
| state is over-minimized | separate Delivery, Attempt, Result, Report, Artifact, Review, Finalization, Assurance |
| LLM regains control authority | machine envelope and fail-closed actor/grant/reference tests |
| safety recreates non-closure | terminal disposition independent from assurance strength |
| corpus becomes governance | immutable fixtures only; no writer, heartbeat, retry, or Supervisor |
| alpha PASS is overclaimed | report only pure reducer/store conformance, never Host/product/release evidence |

## Consequences

The corrected model adds explicit Result, Report, Attempt, authority, and
assurance subjects compared with the earlier draft. This is intentional: it
removes semantic overloading rather than adding governance. The first vertical
trace remains 11 operations but emits more events and a larger snapshot because
Result/Report acceptance and strict assurance are now separately observable.

The compatible-refactor route remains reversible: v3 sources stay immutable,
the alpha store is disposable, and no persistence or Host choice is locked by
the slice.
