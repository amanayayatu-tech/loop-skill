# ADR 0011: LoopSkill 4.0 kernel refactor

- Status: Accepted
- Implementation boundary: v4-only implementation and public GitHub 4.0.0 release authorized after all frozen gates pass
- Date: 2026-07-27
- Decision scope: LoopSkill 4.0 architecture, authority boundary, recovery semantics, compatibility, and gates
- Conformance design: `docs/conformance/loopskill-4-conformance-corpus-design.md`

## Authorization and source identities

The author selects route B: replace the protocol kernel, persistence model, and
Host boundary while reusing provenance-bound v3 safety assets. Successive
author decisions expanded the boundary from a disposable alpha slice to a
v4-only public 4.0.0 release. External Git writes remain gated on a clean new
candidate, full local acceptance, a new exact-SHA App canary, independent
review, and secret/privacy checks. Real v3-loop migration, private research
data, force pushes, and unsupported efficacy claims remain forbidden.

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

## Context

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

## Decision

LoopSkill 4.0 uses a typed protocol manifest, deterministic reducer,
transactional store contract, explicit authority grants, orthogonal subject
aggregates, artifact ports, and Host anti-corruption adapters. It reuses v3
algorithms and fault traces selectively rather than retaining v3 canonical
shape.

Rejected:

- **v3 patches renamed 4.0**: preserves manual mirrors, Host leakage, and
  multi-ledger verification cost. v3.3.8 receives bounded safety maintenance
  only.
- **clean-slate without preservation/conformance**: discards proven identity,
  replay, path, artifact, and crash evidence and creates an unverified rewrite.

## Decision addendum: semantic preservation, runtime hard break

**Accepted 2026-07-27; this subsection supersedes only the earlier runtime/data/
CLI/Pack/MCP compatibility direction.** LoopSkill 4 preserves proven v3 safety
principles and user value through smaller v4 invariants and conformance cases,
but ships no v3 runtime, importer, repair path, Pack execution path, State
Gateway, State-Writer, MCP registration, CLI alias, or canonical schema
compatibility. The immutable `v3.3.8` tag and GitHub Release remain the sole
supported product line for opening, repairing, or running v3 loops and Packs.

Consequences:

- `PRESERVE`/`REDESIGN` capabilities remain v4 RC/release gates; old mechanisms
  are never copied merely to satisfy the preservation inventory.
- `COMPAT_ONLY` runtime dispositions are replaced by `EXTERNAL_V3_LINE` or
  `DEPRECATED_NOT_SHIPPED`. The 24 capability groups remain semantic mappings,
  not 1,766 runtime branches.
- A v4 entry that detects a v3 root/state/Pack performs zero writes and returns
  one stable `USER_UNSUPPORTED_LEGACY_VERSION` error with a direct v3.3.8 release
  reference. It does not import, repair, mutate, partially activate, or propose
  automatic migration.
- v4 owns a distinct root, installation identity, and SQLite store. Its
  installer never reads or edits `[mcp_servers.*]`, never requires a LoopSkill
  App restart, and never replaces a v3 installation.
- The ordinary flow remains `INTAKE → PREPARE → CONFIRM → START`; the hard break
  removes manual control-plane transport, not the human authorization boundary.
- P6 compatibility code/tests/evidence and candidate `5d3d671da11ea5795a629b3df50ff6eb57252432`
  remain immutable predecessor evidence and are excluded from v4-only release
  acceptance. A new candidate SHA must pass new install, documentation, CI,
  conformance, App-canary, privacy, and release-identity gates.
- After those gates pass, the author has authorized a non-force feature-branch
  push, PR, CI-gated merge, annotated `v4.0.0` tag, and public non-prerelease
  GitHub Release. No v3 tag/release/history may be rewritten or deleted.

Any later compatibility restoration requires a new ADR; it cannot enter through
an importer, wrapper, daemon, Supervisor, dual writer, or Pack-as-truth escape
hatch. Earlier compatibility-sunset, importer, registered-v3-MCP, and
RC-ready-only passages below are retained as decision history and are
normatively superseded by this addendum.

## v3.3.8 product-capability preservation decision

Route B is not permission to retain only the Kernel-shaped assets that are
convenient to reimplement. The authoritative human and machine registers are:

- `docs/architecture/v3-to-v4-capability-preservation-register.md`; and
- `docs/architecture/v3-to-v4-capability-preservation-register.json`.

They bind the exact public `v3.3.8` commit and machine-enumerate 10 reference
files, 27 architecture modules, 38 product test files with 771 exact test
methods, 19 SPEC invariant entries, seven public `loopctl` commands, 705
recovery errors, and 922 public schema enum/const symbols, including the
dynamic v3 `INPUT_SCHEMA`. The preservation
validator requires every active invariant, public flow, command, schema,
stable symbol/error, and release/install contract to have exactly one
disposition and an executable conformance gate. The register is a migration/RC
checklist only; it is not a protocol authority, writer, heartbeat, recovery
process, or third governance layer.

| Capability | Decision | v4 boundary |
| --- | --- | --- |
| `PRES-INTAKE` | retain | Entry owns G1–G10, four readiness outcomes, seven-section intake-only output, clarification priority/deduplication, and zero effects. |
| `PRES-ENTRY` | retain | Entry owns native `INTAKE → PREPARE → CONFIRM → START`; one command may orchestrate it but cannot skip confirmation. |
| `PRES-MODES` | move | Optional policy owns direct/Standard/Adaptive selection, fixed queues, and bounded roadmaps. |
| `PRES-ROLES` | move | Optional review policy owns JIT Worker/Reviewer/Local Verifier requirements; Host creation remains an Adapter effect. |
| `PRES-HUMAN` | move | Optional human-control policy owns pause/resume, Decision Cards, review surfaces, and freshness; Kernel validates authority receipts. |
| `PRES-REPAIR` | move | Optional bounded-repair policy uses immutable Kernel attempt history and cannot create a Supervisor. |
| `PRES-KERNEL` | retain | Core keeps per-loop CAS, idempotency, single-writer state, attempts/outbox, and fail-closed transitions without v3 state shape. |
| `PRES-TRANSPORT` | lower | Codec library keeps bounded strict-UTF-8 structured framing and duplicate-key rejection. |
| `PRES-RECOVERY` | lower | Attempt/outbox plus typed-error projection keeps lost-response recovery and one next action; no blind resend or independent recovery writer. |
| `PRES-FINALIZATION` | retain | Core keeps orthogonal Goal/Result/Report/Artifact/Review/Finalization and closure/assurance separation. |
| `PRES-ARTIFACT` | lower | Libraries keep existing-Git/non-Git/new-Git capture, binary/untracked/empty identity, confinement, symlink/casefold/special/race rejection. |
| `PRES-EVIDENCE` | lower | Evidence normalization plus Core subject bindings keep current artifact/dispatch/report/review identity. |
| `PRES-HOST` | move | Codex Adapter owns every project/task/thread/turn/heartbeat/trust/sandbox/model/memory/App enum/lifecycle/readback fact. |
| `PRES-OPERABILITY` | retain | Entry commands keep doctor, compile, and disposable canary with diagnostics-only internal identity. |
| `PRES-AUDIT` | lower | Hash-chained rejection history, audit/status/archive/business timeline and next-action views are read-only rebuildable projections. |
| `PRES-PRIVACY` | lower | Libraries keep risky-artifact classification and aggregate export with no prompt/chat/task/thread/path/PII/secret/raw-log disclosure. |
| `PRES-METRICS` | lower | Read-only metrics retain counts, latency and explicit `UNMETERED`; they never authorize progress. |
| `PRES-COMPAT` | compatibility only | One-major-cycle facade preserves intake/generate, existing-Pack repair, Markdown views and compact/full/minimal_patch behavior, not exact bytes. |
| `PRES-MIGRATION` | compatibility only | Safe-point read/shadow/dry-run/preview/confirm/cancel/import keeps original v3 bytes and forbids dual write. |
| `PRES-DISTRIBUTION` | retain | Isolated install/uninstall/rollback keeps conflict fail-closed, absolute runtime identity, one registration and byte-exact recovery. |
| `PRES-DOCS` | retain | Chinese/English quickstarts and Standard/Adaptive examples remain RC-blocking public assets. |
| `PRES-RELEASE` | retain | Exact candidate SHA, local acceptance, compatibility CI separation, App canary, security and artifact gates remain mandatory. |
| `PRES-DEPRECATIONS` | deprecate | New v4 loops have no session State-Writer, native Goal generation recovery, Supervisor, 97-field write API, model authority, Pack truth, blind retry, or dual writer. |
| `PRES-PUBLIC-SCHEMA-COMPAT` | compatibility only | Closed v3 schemas remain readable for diagnostics/shadow/import preview; v4 never writes their giant shape canonically. |

### Compatibility sunset

The facade and v3 schema reader remain for one complete v4 major cycle. The
window preserves user workflows and rollback readability, not every old flag,
wording, Pack byte, error sentence, or canonical-write field. Sunset requires
usage evidence, a documented replacement for every affected public flow,
migration and rollback evidence, a major corpus version, an ADR amendment, and
separate author approval. Original v3 data readability and the public v3.3.8
maintenance line are not implicitly sunset with the facade.

P5.1 implementation validation and every P6 change are gated on the register,
ADR/corpus consistency, stale/duplicate scans, and an independent read-only
architecture/product review bound to the exact document digests.

### Preservation is semantic compression, not mechanism replication

The first inventory pass counted 1,640 required identities. Independent review
found that it omitted 126 enum/const symbols generated by v3's dynamic
`INPUT_SCHEMA`; the corrected closed inventory therefore contains **1,766**
required identities, including 705 recovery codes and 922 schema symbols. This
larger count improves omission detection but does not enlarge v4 Core. The 24
capability groups are semantic dispositions: legacy errors are assigned to one
owner or deprecation path, legacy schemas are read/translated at the
compatibility edge, and neither becomes a branch-per-item runtime contract.

The preservation validator must HOLD if preserving a legacy item would require
literal duplication of the old error catalog, schema, State-Writer,
Supervisor, recovery registry, or monolithic state shape. It must instead bind
the item to a retained semantic invariant, compatibility mapping, or explicit
deprecation with replacement.

### Anti-bloat structural and execution gates

- one manifest owns wire literals; one transactional authority/writer owns
  operation idempotency, per-loop CAS, canonical events/snapshots, and outbox;
- read-only projection, audit, archive, export, policy, Artifact, Adapter, and
  compatibility code cannot sign receipts or mutate the canonical store;
- the minimal profile makes optional policy and v3 compatibility modules
  unavailable and proves that intake, prepare, confirm, start, status, and
  honest UNKNOWN/UNVERIFIABLE still work without importing them;
- after P5.1, evidence freezes default-path loaded modules and dependency edges,
  command/event/error counts, user start actions, authorization confirmations,
  Host interactions, protocol calls, local writes, entry/Pack bytes, latency,
  UNKNOWN count, and human interventions; and
- no arbitrary LOC/module/command ceiling is added. P6/P7 default-path cost
  increases require a mapped capability plus an existing ADR decision.

The 32 KiB Pack and at least 50% reduction in internal control interactions
were candidate targets. P7 has now frozen them as beta/RC blocking thresholds
before consuming a P7 v4 comparison receipt. The frozen scenario is one
existing-Git passkey Goal through one Worker result, one artifact-bound review,
and finalization acknowledgement or an honest terminal limitation. Its exact
v3.3.8 (`843945d9d34e7f065b65d9172ea4a2df66c0f2e3`) compact Pack is 70,805 bytes
and its enumerated model/process/Host-boundary control ledger has 19
interactions. Therefore v4 must emit a Pack of at most 32,768 bytes and at most
9 comparable internal control interactions. Necessary human confirmation is
reported separately, as are in-process Kernel protocol calls. The frozen
scenario digest is
`e6b5be9e97b42a47f17978c82fbe20725430042e0c66ae5a02e78a963798ecbe` and
measurement-code digest is
`c35a07740bed3ceafda49b40c646ab77eb2999763854a2a5b81c90a6f3870e5a`.
If the units cannot be compared honestly, the result is a product decision,
not a manufactured PASS.

The historical P5.1 minimal-profile observation freezes the metric names and counting
boundary, not the beta performance thresholds. In the synthetic no-Host
scenario it loads 13 `loop_architect.v4_*` modules over 17 internal dependency
edges; its then-current manifest declared 16 commands, 33 events, and 40 errors. One public
start action contains one separately reported human confirmation, then one
Kernel mutation/canonical commit emitting five events and one startup Attempt;
INTAKE writes 0 files, PREPARE writes 5, CONFIRM writes 1, and Host interactions
are 0. The source entry is 11,125 bytes and the generated Controller Plan view
is 627 bytes for the frozen synthetic request. One latency sample is recorded
only as diagnostic evidence, never as a gate. P7 must freeze the same-scenario
v3 baseline, measurement-code digest, units, and final thresholds before
reading the comparison result. That freeze is now recorded in
`evidence/v4-development/p7-v3-baseline-freeze.json`; the earlier P5.1 number
remains explicitly disclosed as a nonblocking diagnostic and was not used to
tune either author-fixed threshold.

## Product and dependency boundary

### Composition and ports

Entry is the composition root. It may call Kernel and the public query/services
needed to present a user flow. Kernel depends only on the generated typed
protocol and declared ports. Transactional Store, Artifact capability, and the
single Codex Host Adapter independently implement those ports:

```text
Entry/composition root ──> Kernel ──> typed protocol + ports
                              ^
             ┌────────────────┼────────────────┐
 transactional Store     Artifact library   Codex Adapter
       implements port    implements port    implements port
```

Store never calls or controls Host. Artifact and Host components never write
canonical state. One transactional authority may persist several orthogonal
aggregate/event streams; “one authority” does not collapse them into one giant
enum or require one physical event stream.

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

The kernel must not import or invoke Codex/App modules, Host enums, policy,
compat/importer, UI/CLI, Git, `subprocess`, filesystem mutation, concrete
SQLite, Pack/prompt rendering, network clients, v3 migration, or
paper/Oracle/apparatus code. A fail-closed AST/import-graph gate enforces the
ban and requires the complete v4 import graph to be acyclic.

The typed protocol manifest is the only declaration authority for command,
event, reference, receipt, capability, and error wire literals. Reducer
invariants, filesystem-race checks, and Host-effect contracts remain separate
code authorities, but cannot redefine those literals. Generated schema, CLI
types, Pack API summaries, error tables, and corpus fixtures must consume or
strictly validate the manifest.

## User-experience compatibility requirement

The v4 internals may change, but the default user entry model is a normative
compatibility boundary:

- a fresh user supplies one goal/input file **or** invokes one public main
  command, and that single public action enters a same-session
  `INTAKE → PREPARE → CONFIRM → START` flow. It must pause at an explicit human
  confirmation before any Host/execution effect; “single entry” never means
  silent start or skipped authorization. The final command name is deferred to
  CLI design, and manual control-plane choreography is forbidden;
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

The future public entry is a composition facade over Kernel/Adapter machine
authority, not a Supervisor, second writer, or second control plane. The
four-phase authorization contract is P5.1-blocking before P6; broader UX cost,
documentation, migration, and usability gates remain beta/RC gates.
An explicit v4 or `loopskill4` invocation must route to this native entry before
the one-major-cycle legacy Skill facade. It must not run the legacy v3 Doctor,
scaffold, Pack, State-Writer, Gateway, heartbeat, policy, or importer before v4
INTAKE/PREPARE. Legacy natural-language intake/generate and repair remain
explicit compatibility modes; merely invoking the installed Skill does not
select them.

### Native four-phase entry contract

1. **INTAKE** is strictly read-only. It returns exactly
   `READY_FOR_LOOP`, `NEEDS_CLARIFICATION`, `BLOCKED`, or
   `DIRECT_TASK_RECOMMENDED`, renders the stable seven-section intake report,
   and asks at most three highest-priority deduplicated questions. It creates
   no loop, role, task, heartbeat, delivery, or external effect.
2. **PREPARE** writes only to an explicit local preparation output. It creates
   one typed Loop Manifest, a human Controller Plan/Pack, Chinese instructions,
   and a minimal boundary summary. Canonical manifest and human views have
   machine-bound digests. PREPARE creates no Host task, heartbeat, delivery, or
   treatment execution; Markdown is a review/export/compatibility view, never
   machine truth.
3. **CONFIRM** shows Goal, write scope, budget, external actions, acceptance
   criteria, stop conditions, and commit/push/publish/deploy boundaries. A
   machine-issued receipt binds actor/grant, manifest digest, human-view digest,
   boundary digest, scope, and validity. Any bound change or expiry invalidates
   it. High-impact work cannot use `--yes`, defaults, vague “continue”, or a
   noninteractive fallback; automation must consume a pre-signed bound grant.
4. **START** accepts only a valid current confirmation. It commits exactly one
   canonical startup Attempt; the Adapter may then create/read back one Host
   resource under the existing at-most-one automatic-attempt rules. Missing
   authoritative readback yields UNKNOWN, never a resend. User/model-provided
   control identity remains zero.

`DIRECT_TASK_RECOMMENDED` does not create a Loop. Explicit `intake`, `prepare`,
and `start prepared-manifest` commands may coexist with the one-session main
entry. The legacy Skill's intake/generate behavior remains available for one
major cycle through a behavior-equivalent facade.

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

### Delivery, ExternalEffect, and Attempt

Delivery state: `PREPARED`, `ATTEMPT_COMMITTED`, `OBSERVED`, `UNKNOWN`,
`UNVERIFIABLE`.

Each Delivery has at most one automatic `AttemptRef` in alpha. Attempt records
bind loop, delivery, target resource, executor actor/grant, ordinal, provider
request digest, provider idempotency key when available, budget consumption,
and observation receipt. Attempt state is `COMMITTED`, `OBSERVED`, `UNKNOWN`,
or `UNVERIFIABLE`.

Delivery observation never represents Result acceptance.

Host bootstrap is a generic `ExternalEffect`, not an implicit Adapter side
effect. After a valid digest-bound confirmation, the one-entry CreateLoop path may atomically add one startup
ExternalEffect and its Attempt/outbox descriptor in the same local transaction.
The canonical subject is `ExternalEffectRef`; the Adapter never invents it.
`RecordExternalEffectObservation` maps strict/cooperative/missing readback to
OBSERVED/UNVERIFIABLE/UNKNOWN, and only OBSERVED may bind the reserved
HostResourceRef. This additive path preserves the original 11-operation alpha
vertical bytes because that fixture does not request a startup ExternalEffect.

### Result

State: `STAGED`, `ACKNOWLEDGED`, `STALE`. Result binds either the Route /
Delivery subject chain or the startup `ExternalEffectRef`, plus the exact
Attempt, producing Actor, semantic outcome, normalized `ReportRef`, source
observation digest, and after acknowledgement the current `ArtifactRef`.
Delivery observation and startup-effect observation remain independent from
Result acceptance.

### Report

State: `STAGED`, `ACCEPTED`, `STALE`. Report binds exact Result, author Actor,
bounded normalized bytes/digest, and source receipt/provenance.

### Artifact

State: `CAPTURED`, `VERIFIED`, `UNVERIFIABLE`, `STALE`. Artifact binds exact Result, capture
algorithm/capability, before/after identity, content digest, and receipt.
Host result text is never an Artifact receipt. Before the one provider attempt,
Entry binds the confirmed workspace identity/profile and persists an immutable
pre-effect baseline in the same canonical store. After readback, the artifact
library performs an exact existing-Git/non-Git/new-Git capability capture and
the JIT Local Verifier issues the only `verify-artifact` receipt. Missing,
drifted, or unsupported local evidence yields Artifact `UNVERIFIABLE` and can
close as LIMITATION; it cannot produce Review PASS or execution SUCCEEDED.

### Review

State/verdict: `PENDING`, `PASS`, `REPAIR`, `LIMITATION`. Review binds the
current Result, Report, Artifact, their revisions, reviewer Actor/grant, and
the canonical subject-chain digest. A LIMITATION cannot become PASS during
finalization.

### Finalization

State: `PREPARED`, `EXECUTION_CLOSED`. Finalization binds exact Goal, Attempt,
Result, Report, Artifact, Review and either Route/Delivery or ExternalEffect,
all current revisions, requested terminal disposition, closure-assurance
basis, and subject-chain digest.

Closing execution appends `ExecutionFinalized`. If exact strict readback is
also present, the same command may append `StrictFinalizationAcknowledged` and
set assurance `STRICT`. Otherwise execution can still terminate honestly with
`LIMITATION` and `LOCAL`/`COOPERATIVE` assurance.

Later authoritative evidence may change a Delivery or ExternalEffect and its
Attempt from `UNKNOWN` or `UNVERIFIABLE` to `OBSERVED` only under the exact
original typed subject and Attempt identity. For a finalized Delivery chain, a
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

`CreateLoop`, `RegisterGoalPlan`, `ReviseGoalPlan`, `BindHostResource`, `PrepareRoute`, `BeginEffectDelivery`,
`RecordEffectObservation`, `RecordExternalEffectObservation`, `StageResult`,
`StageExternalResult`, `AcknowledgeResult`, `RecordReview`,
`AdvanceGoal`, `RecordPolicyDecision`, `PauseLoop`, `ResumeLoop`, `StopLoop`, `PrepareFinalization`,
`CloseExecution`, and `StrengthenClosureAssurance`.

Queries (`ReadStatus`, `ReadDelivery`, `ReadResult`, `ReadCapabilities`, export)
are read-only and have no operation/CAS side effects.

### Events

`LoopCreated`, `GoalRegistered`, `GoalPlanRegistered`, `RoadmapRevised`, `GoalActivated`, `StartAuthorized`, `HostResourceBound`,
`ExternalEffectPrepared`, `ExternalEffectObserved`, `ExternalEffectUnknown`,
`ExternalEffectUnverifiable`, `LateExternalEffectObserved`,
`RoutePrepared`, `DeliveryAttemptCommitted`, `DeliveryObserved`,
`DeliveryUnknown`, `DeliveryUnverifiable`, `LateDeliveryObserved`,
`ResultStaged`, `ReportStaged`, `ArtifactCaptured`, `ArtifactVerified`,
`ArtifactUnverifiable`, `ArtifactStale`, `ReportAccepted`, `ResultAcknowledged`,
`ReviewRecorded`, `HumanDecisionRecorded`, `RepairAuthorized`, `RepairExhausted`,
`GoalAdvanced`, `LoopPaused`, `LoopResumed`, `LoopStopped`, `FinalizationPrepared`,
`ExecutionFinalized`, `StrictFinalizationAcknowledged`,
`ClosureAssuranceStrengthened`, and `OperationRejected`.

### References

`LoopRef`, `ActorRef`, `AuthorityGrantRef`, `GoalRef`, `HostResourceRef`, `ExternalEffectRef`,
`RouteRef`, `DeliveryRef`, `AttemptRef`, `ResultRef`, `ReportRef`,
`ArtifactRef`, `ReviewRef`, `FinalizationRef`, and `ReceiptRef`.

### Stable protocol and public-entry errors

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
`FINALIZATION_PRECONDITION_FAILED`, `STORE_RECOVERY_REQUIRED`, and
`INTERNAL_INVARIANT_VIOLATION`.

The manifest also owns the bounded public-entry errors `USER_INPUT_INVALID`,
`USER_LOOP_EXISTS`, `USER_STORE_UNAVAILABLE`, and `USER_INTERNAL_ERROR`.
Their normal text must not expose internal handles, receipts, schema, or a
traceback.

`UNKNOWN` and `UNVERIFIABLE` are Delivery or ExternalEffect/Attempt states,
never acceptance or error values.

### Stop semantics

`StopLoop` is a machine-envelope mutation with a fresh operation ID, protocol
version, trusted Actor/Grant scoped to the exact loop and command, expected
per-loop revision, and semantic stop reason. It never accepts a model-carried
handle or grant as authority. On acceptance it emits `LoopStopped`, sets the
active Goal and execution to `STOPPED`, records only LOCAL assurance, prevents
new product attempts, and preserves every accepted result/effect unchanged.
It does not fabricate a Result, PASS review, or Host finalization receipt.

An unresolved committed Attempt is not rewritten as cancelled: it remains
`UNKNOWN` or `UNVERIFIABLE`, forbids automatic resend, and limits closure
assurance. Exact command replay returns the prior result without another event
or effect; a changed request conflicts; stale revision, forged/wrong-loop
authority, or invalid subject fails closed with zero canonical/external effect.

## External-effect executor contract

`PrepareRoute` creates Delivery `PREPARED` with automatic-attempt budget `1`.
`BeginEffectDelivery` is the only command that obtains execution authority:

The startup exception is not an untracked side effect: when requested by the
single-entry machine envelope carrying a valid current confirmation, `CreateLoop` itself atomically commits one
ExternalEffect, Attempt, provider request digest, and outbox row. It does not
call the provider. Both Delivery and startup ExternalEffect then use the same
claim/readback/UNKNOWN rules below.

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

Once the startup ExternalEffect is OBSERVED, Entry may read the exact Host
result and submit the machine-owned sequence `StageExternalResult` →
`AcknowledgeResult` → `RecordReview` → `AdvanceGoal` →
`PrepareFinalization` → `CloseExecution`. Each accepted command is one
operation-idempotent/CAS transaction and each intermediate snapshot has one
deterministic successor command. A crash at any durable boundary resumes from
the committed stage; it never creates or resends the Host task. The staged
Result stores the authoritative Host-result digest, so a changed or regressed
readback fails closed. Final lifecycle acknowledgement is a separate
authoritative readback after `FinalizationPrepared` and may yield honest
cooperative/limited closure instead of a strict success claim.

`AcknowledgeResult` does not treat the Host Result as artifact proof. It
consumes a Local-Verifier receipt bound to the exact capture digest, manifest
digest, verification evidence and workspace profile. `RecordReview` uses a
distinct JIT Reviewer Actor. Host PASS plus absent local capture/verifier is a
tested LIMITATION path. Only Host PASS plus a captured Artifact and an
independently verified local criterion can produce Review PASS and SUCCEEDED.

The optional policy surface is reachable through Entry without becoming a
writer. Standard/Adaptive projections remain removable from the minimal path;
pause/resume/stop submit ordinary machine-authorized Kernel commands.
For a multi-Goal prepared manifest, Entry submits `RegisterGoalPlan` before any
provider call. The Kernel alone allocates Goal references, stores a fixed
dependency order, and activates exactly one Goal. `ReviseGoalPlan` accepts only
an Adaptive semantic reordering of already-authorized pending objectives,
requires the current plan revision, preserves the active Goal first, and emits
one contiguous `RoadmapRevised`; an objective outside the prepared author
envelope fails closed. Neither command creates a Host task or gives policy
writer authority.
`RecordPolicyDecision` records a digest-bound current-context choice and a
bounded repair authorization/exhaustion fact. It never invokes Host, retries an
Attempt, or manufactures a successor. A repair authorization explicitly
requires a separately prepared and confirmed successor, preserving predecessor
evidence and the no-blind-resend rule.
| readback inconclusive/unavailable | typed subject/Attempt `UNKNOWN` | close with limitation/block, or await a late exact readback; no resend |
| cooperative response only | typed subject/Attempt `UNVERIFIABLE` | limited closure or later strict readback |
| late authoritative readback | exact UNKNOWN/UNVERIFIABLE Attempt becomes `OBSERVED` | optionally strengthen assurance; no new Attempt/result/reexecution |

A late observation is accepted only when issuer trust, action, loop, typed
subject kind/ref, Attempt, target, provider request digest/idempotency key, and
freshness all match. A conflicting observation is rejected and preserved; it
never rewrites the first accepted observation.

No Supervisor, second writer, replacement route, timeout inference, or natural
language recollection may reconstruct the first response or restore the budget.

## Execution terminality and assurance

Execution may terminate as:

- `SUCCEEDED`: required product/result/review chain passes;
- `LIMITATION`: bounded work is honestly closed with missing/unverifiable Host
  evidence, Review LIMITATION, or another declared assurance limitation; or
- `FAILED`: the acknowledged Result reports failure and review accepts that
  evidence without converting it to PASS;
- `STOPPED`: an authorized stop terminates locally without fabricating a
  Result or Host acknowledgement.

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

The alpha reference store remains an in-memory semantic oracle and fault
fixture. The authorized SQLite candidate spike passed crash, backup/restore,
concurrent-reader/writer, manual-inspection/export, corruption, and macOS
filesystem gates. ADR 0012 therefore selects SQLite as the sole local canonical
store for continued v4 development. This does not make external Host/provider
effects transactional with SQLite and does not authorize a second writer.

Compatibility decisions:

- v3.3.8 remains public maintenance;
- treatment commit `54442e22...` remains a reference only;
- v4 uses a new root/store and never modifies a v3 loop in place;
- read/shadow/import compatibility is approved for one major cycle;
- import has an explicit preview/confirm boundary and cancel leaves the source
  bytes unchanged and the destination absent or empty;
- a one-major-cycle v3 public-entry facade preserves the one-entry default
  experience and explicit human confirmation without canonical dual write;
- import requires paused, lease-free, outbox-quiescent dry-run and exact source
  digest;
- dual write and reverse conversion are forbidden;
- rollback means the unchanged v3 loop remains readable by its v3 runtime; and
- v4 does not preserve v3's 97-field canonical write shape.

## Author decisions resolved

| ID | Resolved decision |
| --- | --- |
| `OD-1` | Candidate evaluation was authorized without preselection; ADR 0012 subsequently selected SQLite for the v4 local canonical store after all frozen spike gates passed |
| `OD-2` | Execution terminality and assurance are orthogonal; strict Host claim remains strict-only; cooperative work may terminate with limitation |
| `OD-3` | v3 read/shadow/import lasts one major cycle; no dual write or in-place conversion |
| `OD-4` | Measurement definitions are approved; 32 KiB Pack and at least 50% interaction reduction remain candidate beta targets. Same-scenario v3 baseline and final thresholds must be frozen before observing v4 performance; they are not alpha correctness gates |
| `OD-5` | First release supports only a Codex Adapter; kernel remains Host-neutral; no multi-host claim before a second real Adapter passes conformance |

No unresolved product semantic blocks the fixture-only P6 compatibility slice.

## Phases and gates

### Alpha: completed bounded slice

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

The exact 11-operation/18-event/2,715-byte vertical and its bounded fault set
passed and were locked at the P0 checkpoint.

### Alpha.2: completed local capability slices

SQLite persistence, manifest authority, existing-Git/non-Git/new-Git artifact
profiles, and the Codex Adapter passed their frozen local synthetic gates. One
separate projectless disposable App readback was retained as limited P4
evidence; it is not the exact-RC installed usability canary. Current-tree P4
evidence retains only domain-separated digests for project root, Host/task/turn
identity and readback content; raw values remain only in historical Git
provenance and must not be copied into an RC packet.

### P5.1 before P6: native entry authorization gate

The public facade must pass the complete four-phase contract and
`UX-001`, `UX-010..016`, `CAP-INTAKE`, `CAP-ENTRY`, and
`CAP-ARCHITECTURE` before any P6 work. A valid confirmation permits one
`CreateLoop` transaction to create one typed startup ExternalEffect, Attempt,
and outbox record; only the Adapter may execute that machine-owned request.
Direct start without the bound confirmation is forbidden. The facade is not a
Supervisor or retry layer.

### P6: fixture-only compatibility and one-way import

P6 implements compatibility only at the anti-corruption boundary. The reader
is bound to public `v3.3.8` commit
`843945d9d34e7f065b65d9172ea4a2df66c0f2e3` and exact Git objects for the v3
runtime and state/mutation schemas. It does not import v3 code into Kernel and
does not accept paper-treatment or private fixtures as migration authority.

The stateful import slice accepts only a copied/synthetic public schema-v3
Adaptive fixture with exactly one READY Goal at a paused, lease-free,
outbox-empty safe point. This intentionally narrow first importer proves the
one-way boundary; it is not evidence that arbitrary historical state can be
imported. Running, leased, pending-outbox, terminal, changed-source,
noncanonical, unsafe-path, overlapping-root, and nonempty-destination inputs
fail closed. In particular, terminal v3 loops remain readable by v3 and cannot
be revived in v4.

`shadow_read` and preview are read-only. Cancel leaves both source and
destination unchanged. Confirm holds the same advisory root lock used by v3,
revalidates the exact source digest, then commits one `ImportV3Snapshot`
operation into a disjoint owner-only v4 root. Exact replay returns the original
result. The import creates a paused Goal and four events, zero Attempts/outbox
records, and zero Host/provider/Git effects. Rollback is the unchanged v3
source; there is no reverse conversion or canonical dual write.

Standard/Adaptive selection, old intake/generate entry, compact/full export,
and existing-Pack `minimal_patch` review behavior are retained through an
optional compatibility facade. That facade produces the same typed PREPARE
bundle used by the native entry and a human export view; it never makes Pack
Markdown machine truth and never starts a loop. Policy execution semantics
remain P7-owned.

The P6 checkpoint is blocked by `M-001..005`, `UX-006`, and `CAP-COMPAT`
fixture evidence plus all prior v4 regressions. It does not authorize real-loop
migration, installed compatibility, or the removal of the one-major-cycle
facade.

### P7: optional policy and rebuildable operability

Entry now freezes `STANDARD` or `ADAPTIVE` plus the selection reason inside the
typed prepared manifest and digest-bound confirmation. Standard is the default
for a ready durable task; Adaptive requires the explicit `adaptive` horizon.
The minimal path still imports no policy module and requires no policy pack.

The optional policy package is pure: Standard validates one fixed,
dependency-ordered Goal Queue; Adaptive permits one active Goal and contiguous,
bounded roadmap revisions inside the author envelope. JIT Worker, Reviewer, and
Local Verifier requirements bind the current Artifact. Decision Cards bind
Goal, Artifact, options, context digest, and expiry. Replayed or stale context
fails closed. Repair selection has independent total-attempt and
same-fingerprint bounds, after which it returns a human decision instead of
dispatching again. Policy can name only a command declared by the typed
manifest; it cannot write Store state, sign receipts, call Host, consume an
Attempt, or retry.

Kernel now implements the previously reserved `PauseLoop`, `ResumeLoop`, and
`StrengthenClosureAssurance` transitions under the existing per-loop CAS and
machine authority rules. A pause stores a reason digest rather than raw prose.
Late authoritative readback may strengthen a terminal cooperative assurance to
strict without changing the already honest execution disposition.

Audit index, status, archive, privacy aggregate, risk scan, metrics, and Doctor
views are deterministic, rebuildable projections. They are not ledgers or
writers. Privacy output contains aggregate counts/digests only; risk findings
contain categories and digests, never the matched secret, raw path, prompt,
chat, task/thread identity, PII, or raw log. Missing metrics remain
`UNMETERED`. The exact implementation binding is
`tests/test_v4_product_policy_operability.py`.

### Beta: local implementation authorized; gates remain blocking

Policy/liveness/cost work follows in P7 after the fixture-only P6 import gate.
Measurement definitions and the same-scenario v3 baseline are frozen. Pack
size at most 32 KiB and at least 50% fewer comparable internal control
interactions are now blocking; the exact baseline permits at most 9 v4
interactions against 19 v3 interactions. Beta blocks on all
remaining `UX-001..008`, `UX-010..016`, the preservation subset assigned to
beta, and minimal-profile isolation.

### Historical RC-only boundary (superseded by the v4-only release addendum)

Local isolated install/uninstall/rollback, the full Host/artifact fault matrix,
one exact-candidate disposable App canary, independent read-only review, fixed
candidate SHA, and an author approval packet are authorized. Every failure and
UNKNOWN must remain preserved. RC requires one real, non-research,
private-data-free new-user usability canary from the isolated installation
through starting a minimal disposable loop, with no manual transcription of
control identity. This paragraph recorded the earlier RC-only authorization and
is not the current release boundary. The hard-break addendum now authorizes
push, PR, merge, annotated tag, and a public GitHub 4.0.0 Release only after the
exact-SHA local, CI, canary, review, and readback gates pass. Automatic
migration of real v3 loops remains forbidden. Stable retains all UX gates and
the one-entry plus explicit-confirmation contract.

That predecessor P8 distribution path and its v3 MCP facade are superseded
evidence and excluded from current acceptance. The v4-only installer owns a
distinct installation root, never edits `config.toml`, never registers MCP,
never requires a LoopSkill-driven App restart, and never overwrites v3. Its
supported atomicity claim is bounded process-failure recovery with exact
filesystem readback, not one transaction spanning arbitrary power loss.

The candidate static gate records exact commit/tree, Python runtime, generated
protocol counts, the complete installed-distribution SBOM and license inventory
for that exact Python runtime, secret scan, tracked
large-artifact scan and zero public effect. The App receipt stores only a digest
of the machine-returned Host observation, never raw thread/task identity or
content. The JSON receipt alone is insufficient: the final local validator must
open the disposable canonical store and perform a fresh authoritative Host
result/lifecycle readback, then bind its minimized live attestation to the
candidate goal, hashed Host identity, result, snapshot, Review, and
Finalization digests. The raw store and Host identity are not published. These
receipts are build evidence, not runtime authority.

`scripts/validate_v4_rc.py` defaults to the final fail-closed mode: canary,
349-instance conformance, and privacy-minimized publication-packet receipts are
all mandatory. The explicit `--static-only` mode is a pre-canary diagnostic and
always records `publication_ready=false`; it cannot satisfy the publication
candidate gate. `scripts/run_v4_conformance.py`
expands the frozen exact catalog, executes every bound module, emits one result
record for each of the 349 canonical case IDs, and additionally binds the two
real-App cases to the exact canary receipt. Each local record must first consume
a machine-derived per-case contract covering precondition, stimulus,
acceptance, effect state, event order, side-effect count, replay, capability,
selector, and target assertion. After the concrete target passes, a test-side
observation oracle that is independent of the supplied expected contract emits
the observed acceptance, effect state, event order, bounded side-effect counts,
and replay class for that selector. The runner compares observed and expected
values and binds the observed-result digest. Unknown IDs, a self-consistent
mutation of the active expected contract, or a repeated family-level unittest
result without the selector-specific observation fails closed.

## Non-goals and safeguards

4.0 local development does not promise patch success, long-horizon superiority,
multi-host support, Byzantine resistance, Host memory isolation, real-user
migration safety, installed-product effectiveness, or release readiness.

| Failure mode | Safeguard |
| --- | --- |
| v3 semantics leak through compatibility | exact anti-corruption mapping; no v3 state shape in kernel |
| dual stack becomes permanent | no dual writes; one-major-cycle compatibility sunset |
| store becomes opaque | selected SQLite retains canonical export, integrity, backup, and corruption gates |
| Adapter invents transactions | explicit Attempt/UNKNOWN/UNVERIFIABLE and receipt trust |
| state is over-minimized | separate Delivery, Attempt, Result, Report, Artifact, Review, Finalization, Assurance |
| LLM regains control authority | machine envelope and fail-closed actor/grant/reference tests |
| safety recreates non-closure | terminal disposition independent from assurance strength |
| corpus becomes governance | immutable fixtures only; no writer, heartbeat, retry, or Supervisor |
| phase PASS is overclaimed | bind each claim to its checkpoint SHA and exact gate; never infer effectiveness or release readiness |

## Evolution

Evolution is allowed only through the frozen conformance and capability
preservation gates. It may simplify internal implementation, replace a port
implementation, or remove a compatibility facade after its one-major-cycle
sunset, but cannot introduce a second writer, dual write, model-carried control
authority, blind retry, implicit real-v3 migration, or a public-release claim
without a separate author decision.

## Consequences

The corrected model adds explicit Result, Report, Attempt, authority, and
assurance subjects compared with the earlier draft. This is intentional: it
removes semantic overloading rather than adding governance. The first vertical
trace remains 11 operations but emits more events and a larger snapshot because
Result/Report acceptance and strict assurance are now separately observable.

The compatible-refactor route remains reversible: v3 sources stay immutable,
v4 uses a separate root, no dual write exists, and local SQLite/Host choices do
not authorize migration or public replacement of v3.
