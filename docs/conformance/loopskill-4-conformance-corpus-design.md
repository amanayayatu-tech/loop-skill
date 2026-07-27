# LoopSkill 4.0 conformance corpus design

- Status: Governing local implementation through an RC candidate; public release remains unauthorized
- Date: 2026-07-27
- Governing decision: `docs/adr/0011-loopskill-4-compatible-kernel-refactor.md`
- Corpus draft version: `1.0.0-alpha-design.2`

## Purpose and boundary

The corpus defines public, deterministic protocol input and expected output. It
prevents authority, replay, revision, Delivery/Result, closure-assurance, and
compatibility semantics from drifting between a protocol manifest, reducer,
store, libraries, and future Host Adapters.

It contains no private Oracle, hidden test, personal prompt, chat, user data, or
paper effectiveness data. It is not a product-success benchmark, recovery
service, Supervisor, second writer, workflow engine, release authorization, or
evidence that a real Host/provider/artifact/migration path exists.

Each phase may implement only its authorized gate set. The bounded alpha slice
was synthetic and in-memory; later local phases add SQLite, artifact libraries,
the Codex Adapter, the public facade, fixture-only v3 compatibility, and isolated
RC validation without authorizing public release or real-loop migration.

## Decision owners

Every instance has one primary decision owner:

| Owner | Decides | Must not decide |
| --- | --- | --- |
| kernel reducer | authority, command legality, revisions, subject chain, transitions, closure eligibility | Host/provider/filesystem truth |
| store | per-loop CAS, operation/rejection idempotency, atomic commit, event order, crash recovery | business transition meaning |
| artifact library | capture identity, path confinement, stale/mismatch classification | lifecycle or assurance policy |
| Host Adapter | capability, receipt trust/readback, provider invocation and uncertainty | canonical mutation or invented Host guarantees |
| policy | optional repair/roadmap/reviewer selection and explicit terminal disposition | receipt authority, direct writes, retries after consumed Attempt |

No instance may pass through a new Supervisor, replacement writer, hidden
state, or natural-language recollection.

## Case record format

Each future case file is one canonical JSON object with these required fields:

| Field | Meaning |
| --- | --- |
| `corpus_version` | corpus semantic version |
| `family_id` / `instance_id` | stable family and independently reportable atomic/parameterized instance identity |
| `title` / `purpose` | public property under test |
| `provenance[]` | synthetic declaration or exact SHA/path/symbol/test identity |
| `phase_gate` | `alpha-slice`, `alpha`, `alpha.2`, `beta`, `rc`, or `stable` |
| `primary_owner` / `supporting_owners[]` | explicit decision responsibility |
| `capability_profile` | exact capability statuses, provenance, constraints, and trust roots |
| `authority_registry` | immutable Actor/Grant fixture; never semantic input |
| `receipt_registry` | immutable bounded receipt fixture when applicable |
| `precondition` | exact loop snapshot/revisions and store idempotency/rejection state |
| `stimulus_kind` | `KERNEL_COMMAND`, `ENTRY_ACTION`, `LIBRARY_CALL`, `ADAPTER_CALL`, or `STATIC_CHECK` |
| `command` | exact machine-constructed command envelope for `KERNEL_COMMAND`; otherwise null with `not_applicable_reason` |
| `entry_action` / `library_call` / `adapter_call` / `static_check` | exact owner-specific stimulus; all non-selected fields are null with one reason |
| `fault_fixture` | exact crash/provider/parser observation, otherwise absent |
| `expected_acceptance` | only `ACCEPT` or `REJECT` |
| `expected_error` | stable error for rejection, otherwise absent |
| `expected_delivery_state` | `PREPARED`, `ATTEMPT_COMMITTED`, `OBSERVED`, `UNKNOWN`, `UNVERIFIABLE`, or absent |
| `expected_attempt_state` | `COMMITTED`, `OBSERVED`, `UNKNOWN`, `UNVERIFIABLE`, or absent |
| `expected_result_state` | `STAGED`, `ACKNOWLEDGED`, `STALE`, or absent |
| `expected_execution` | state and optional terminal disposition |
| `expected_assurance` | `NONE`, `LOCAL`, `COOPERATIVE`, or `STRICT` |
| `expected_events[]` | exact ordered typed-manifest event objects; empty for non-canonical cases |
| `expected_snapshot` / `expected_snapshot_digest` | exact post-case canonical snapshot/digest, or both null when no Loop exists/canonical state is untouched, with `not_applicable_reason` |
| `expected_output` | exact Entry/library/Adapter/static result when the case is not a Kernel mutation |
| `expected_counts` | exact canonical commits/events/rejections, logical local store reads/writes, local filesystem reads/writes, Host/provider calls, Git process calls, network calls, user-workspace writes, and heartbeat creation |
| `replay_expectation` | exact accepted/rejected replay and conflict behavior |

`UNKNOWN` and `UNVERIFIABLE` are never acceptance values. An instance can be
`ACCEPT` with Delivery `UNKNOWN`, Result `ACKNOWLEDGED`, execution
`TERMINAL/LIMITATION`, and assurance `LOCAL` or `COOPERATIVE`.

## Command and authority fixture rules

Each Kernel mutation uses the ADR's machine envelope:

```text
operation_id, command_type, protocol_version, actor_ref, authority_grant_ref,
subject, expected_loop_revision, expected_subject_revisions,
issued_at, machine_bindings, semantic_payload, request_digest
```

`request_digest` is
`SHA-256(UTF8("loopskill-command-v1\n") || canonical_command_without_digest)`.

`machine_bindings` is a closed object with `resolved_refs`, `allocate_refs`, and
`receipt_refs`. The fixture constructor, not user/LLM input, supplies every
field except the command-specific semantic payload. Semantic schemas are closed. Reserved keys
at any structured semantic level produce `CONTROL_FIELD_INJECTION`; text that
merely mentions an ID remains ordinary text and grants no authority.

Authority validation binds trusted issuer, Actor, Grant, validity interval,
command, loop, subject kind/exact reference, and current subject revisions.
Receipt validation separately binds issuer/trust, validity/freshness, action,
loop, subject, Attempt, provider request digest/idempotency key, and outcome.

## Revision, idempotency, and rejection replay

- `expected_loop_revision` is the sole write CAS.
- Every accepted mutation increments `loop_revision` once.
- Each touched aggregate revision increments once in that mutation.
- `expected_subject_revisions` are freshness guards, not write CAS.
- Store commit sequence is diagnostic only and is absent from canonical data.
- Exact accepted replay returns the original result with zero new commit/event/
  handle/effect even after later loop revisions.
- Same `(loop_ref, operation_id)` with a different digest is
  `IDEMPOTENCY_CONFLICT`.
- Rejection records are deduplicated by loop, operation ID, and request digest.
  Exact rejection replay returns the original rejection with zero new record;
  changed content conflicts. A retry after conditions change uses a new ID.

## Canonical encoder specification

Canonical JSON is UTF-8 with no BOM, insignificant whitespace, or trailing
newline. It has these language-independent rules:

1. input bytes decode with strict UTF-8; invalid bytes and unpaired surrogates
   are rejected;
2. object keys are unique strings and sort by Unicode scalar-value sequence;
3. strings are not NFC/NFD normalized; composed and decomposed forms remain
   distinct;
4. emit literal Unicode except required JSON escapes; emit `\"`, `\\`,
   `\b`, `\f`, `\n`, `\r`, `\t`, and lowercase `\u00xx` for remaining C0
   controls; `/` is not escaped;
5. arrays retain declared order;
6. numbers are signed 64-bit integers only; reject `-0`, decimal, exponent,
   NaN, and infinities;
7. booleans and null use JSON literals; and
8. raw Host payloads, secrets, prompts, process IDs, database row IDs, and wall
   clock values not supplied by the trusted fixture are excluded.

Aggregate revision advances once per accepted command touching it, regardless
of how many events that command emits.

Snapshot digest:
`SHA-256(UTF8("loopskill-snapshot-v1\n") || canonical_snapshot_bytes)`.

Event, subject-chain, command, case, report, and provider-request digests use
their corresponding `loopskill-<kind>-v1\n` domains.

### Cross-language golden vectors

Valid canonical bytes are shown exactly; digest domain is
`loopskill-canonical-vector-v1\n`.

| Instance | Canonical bytes | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| `ENC-001-a` | `{"a":1,"b":"x"}` | 15 | `72b469858b6fc86a27886bd3a124d2f786cbd13b49f832066bfdd02a8e29e5c9` |
| `ENC-001-b` | `{"a":"é","文本":"循环"}` | 28 | `0c1a46d9b0f72a73d77d1eb258162f91abace9bd8f9b02f12c55de628aa715f9` |
| `ENC-001-c` | `{"s":"é"}` | 10 | `5e82ac250d21f269ef0533ef3d3f666d63cc4a38f189b1bd9726e387155560e3` |
| `ENC-001-d` | `{"s":"é"}` (`e` plus U+0301) | 11 | `57722ecfcbc5a2f3702e509f9f9650ac5ed391c711b7ea311b48fbf675929afd` |
| `ENC-001-e` | `{"s":"\"\b\f\n\r\t\\"}` | 22 | `007f283d289bc702edf5a6819a4e9a6ac52a06061862edcee10dceec775825e5` |
| `ENC-001-f` | `{"A":1,"é":2,"中":3,"":4}` | 30 | `be4430d368dbd602ae91ae7e69c40ac01145d2172b5fbfb02228cd5271790ad1` |

Reject independently: `ENC-001-g` invalid UTF-8, `ENC-001-h` duplicate keys,
`ENC-001-i` decimal/exponent numbers, and `ENC-001-j` `-0`/out-of-int64.
No family PASS may be claimed unless all ten instances pass.

## Atomic and parameterized instance catalog

Every listed parameter expands to a separately named, independently reported
instance with its own expected fields. A family PASS is the conjunction of all
its instances; running one parameter never passes a family. Cartesian notation
is normative and expands before execution.

<!-- INSTANCE-CATALOG-BEGIN -->

### Kernel, authority, encoder, and bounds

| Family | Atomic/parameterized instances | Gate | Count |
| --- | --- | --- | ---: |
| `K-001` | `a` corrected strict closed vertical | alpha-slice | 1 |
| `K-002` | `a` stale loop revision; `b` stale subject revision | alpha-slice | 2 |
| `K-003` | `op01..op11` exact replay after each accepted vertical operation | alpha-slice | 11 |
| `K-004` | `a` changed semantic payload; `b` changed subject; `c` changed expected revision under same operation ID | alpha-slice (`a`), alpha (`b,c`) | 3 |
| `K-005` | `a` malformed ref; `b` wrong kind; `c` unknown ref; `d` cross-loop ref | alpha-slice (`b,d`), alpha (`a,c`) | 4 |
| `K-006` | `a` result ack before stage; `b` review before result ack; `c` finalization before eligible chain | alpha | 3 |
| `K-007` | `a` valid pause/resume; `b` invalid resume | alpha | 2 |
| `K-008` | `a` unknown command; `b` manually divergent event/error enum | alpha | 2 |
| `K-009` | `a` status; `b` Delivery; `c` capabilities; `d` export query read-only | alpha | 4 |
| `AUTH-001` | semantic injection of `a` handle; `b` receipt; `c` actor; `d` grant; `e` timestamp; `f` protocol version; `g` expected revision; `h` command type | alpha-slice | 8 |
| `AUTH-002` | `a` forged Actor; `b` Actor issuer untrusted | alpha-slice | 2 |
| `AUTH-003` | `a` expired Grant; `b` not-yet-valid Grant | alpha-slice | 2 |
| `AUTH-004` | `a` cross-loop subject; `b` cross-loop handle; `c` cross-loop Grant | alpha-slice | 3 |
| `AUTH-005` | Grant wrong `a` command scope; `b` subject-kind scope; `c` exact-subject scope | alpha-slice | 3 |
| `AUTH-006` | receipt `a` issuer untrusted; `b` stale/expired; `c` wrong subject/Attempt; `d` wrong action/request digest | alpha-slice | 4 |
| `RES-001` | exceed `a` command bytes; `b` semantic string; `c` collection count; `d` receipt bytes; `e` emitted-event count | alpha | 5 |
| `ENC-001` | `a..f` valid golden vectors; `g` invalid UTF-8; `h` duplicate keys; `i` decimal/exponent; `j` `-0`/int64 | alpha-slice | 10 |
| `REJ-001` | `a` exact rejection replay deduplicates; `b` same ID changed digest conflicts | alpha-slice | 2 |

### Store and external-effect windows

| Family | Atomic/parameterized instances | Gate | Count |
| --- | --- | --- | ---: |
| `S-001` | operations `op01..op11` × boundaries `a` before reducer; `b` after reducer/before commit; `c` after atomic commit/before response | alpha-slice | 33 |
| `S-002` | `a` PrepareRoute response lost, exact replay | alpha | 1 |
| `S-003` | `a` StageResult response lost, exact replay | alpha | 1 |
| `S-004` | clone/restore with `a` quiescent store; `b` active reader | alpha | 2 |
| `S-005` | competing writers `a` same loop; `b` different loops | alpha-slice (`a`), alpha (`b`) | 2 |
| `S-006` | `a` canonical manual export; `b` corruption detection | alpha | 2 |
| `XFX-001` | `a` crash before BeginEffectDelivery commit leaves budget available and no Attempt | alpha-slice | 1 |
| `XFX-002` | `a` crash after Attempt commit/before provider invocation consumes budget and forbids resend | alpha-slice | 1 |
| `XFX-003` | `a` provider accepted/response lost then authoritative readback | alpha.2 | 1 |
| `XFX-004` | `a` provider returned/crash before local observation then readback | alpha.2 | 1 |
| `XFX-005` | late readback `a` exact UNKNOWN→OBSERVED; `b` identity conflict rejected | alpha-slice | 2 |
| `XFX-006` | cooperative observation `a` UNVERIFIABLE; `b` later exact strict readback | alpha-slice | 2 |
| `XFX-007` | `a` second Begin command; `b` automatic resend request after consumed budget | alpha-slice | 2 |
| `XFX-008` | `a` UNKNOWN with no Result; `b` UNKNOWN with acknowledged Result; `c` UNVERIFIABLE with acknowledged Result | alpha | 3 |

### Host Adapter contracts

| Family | Atomic/parameterized instances | Gate | Count |
| --- | --- | --- | ---: |
| `H-001` | `a` strict observed delivery | alpha.2 | 1 |
| `H-002` | `a` missing authoritative readback yields UNKNOWN/no resend | alpha.2 | 1 |
| `H-003` | eventual indexing `a` binds exact resource; `b` exhausts readback to UNKNOWN | alpha.2 | 2 |
| `H-004` | strict receipt `a` valid; `b` subject mismatch | alpha.2 | 2 |
| `H-005` | cooperative receipt `a` limited closure; `b` strict claim rejected | alpha.2 | 2 |
| `H-006` | memory capability `a` unavailable; `b` unverifiable | alpha.2 | 2 |
| `H-007` | schema drift `a` mapped; `b` unknown enum; `c` missing required field | alpha.2 | 3 |
| `H-008` | final readback `a` strict; `b` missing/inconclusive | alpha.2 | 2 |
| `H-009` | `a` trust; `b` sandbox; `c` model/turn identity absent or mismatched | alpha.2 | 3 |
| `H-010` | effectively-once `a` both prerequisites; `b` one prerequisite missing | alpha.2 | 2 |
| `H-011` | startup ExternalEffect `a` atomically committed with Attempt/outbox; `b` exact strict observation binds reserved HostResource; `c` missing readback is UNKNOWN with no bind/resend; `d` cooperative UNVERIFIABLE later becomes OBSERVED only on the same exact Attempt | alpha.2 | 4 |

### Artifact libraries

| Family | Atomic/parameterized instances | Gate | Count |
| --- | --- | --- | ---: |
| `A-001` | `a` stale artifact; `b` mismatched Result/route | alpha.2 | 2 |
| `A-GIT-001` | `a` binary capture | alpha.2 | 1 |
| `A-GIT-002` | untracked `a` included in scope; `b` control/out-of-scope excluded | alpha.2 | 2 |
| `A-GIT-003` | `a` explicit empty diff | alpha.2 | 1 |
| `A-NONGIT-001` | manifest delta `a` add; `b` modify; `c` delete | alpha.2 | 3 |
| `A-NONGIT-002` | `a` no-diff requires before/after receipts | alpha.2 | 1 |
| `A-NEWGIT-001` | `a` full authorized init/baseline/result/review/closure | alpha.2 | 1 |
| `A-PATH-001` | `a` symlink; `b` traversal; `c` case-fold alias; `d` special file; `e` post-check race | alpha.2 | 5 |

### Result, review, and finalization

| Family | Atomic/parameterized instances | Gate | Count |
| --- | --- | --- | ---: |
| `R-001` | `a` PASS exact current Result/Report/Artifact chain | alpha-slice | 1 |
| `R-002` | `a` REPAIR preserves prior evidence | alpha | 1 |
| `R-003` | `a` LIMITATION cannot upgrade at close | alpha-slice | 1 |
| `R-004` | mismatch `a` Report identity; `b` content digest; `c` author Actor | alpha | 3 |
| `F-001` | `a` strict execution close plus StrictFinalizationAcknowledged | alpha-slice | 1 |
| `F-002` | duplicate close `a` exact replay; `b` changed receipt/chain conflict | alpha | 2 |
| `F-003` | terminal LIMITATION with `a` Delivery UNKNOWN; `b` UNVERIFIABLE | alpha-slice | 2 |
| `F-004` | late assurance `a` exact chain strengthens; `b` changed chain rejected | alpha | 2 |

### Compatibility, policy, liveness, and cost

| Family | Atomic/parameterized instances | Gate | Count |
| --- | --- | --- | ---: |
| `M-001` | `a` safe-point dry run, no write | beta | 1 |
| `M-002` | `a` import new store; `b` exact replay | beta | 2 |
| `M-003` | `a` rollback readability without reverse conversion | beta | 1 |
| `M-004` | reject `a` active lease; `b` live outbox; `c` non-paused source; `d` nonempty destination | beta | 4 |
| `M-005` | `a` dual write forbidden | beta | 1 |
| `P-001` | `a` REPAIR policy proposes one authorized new route | beta | 1 |
| `P-002` | explicit BLOCKED by `a` repair exhaustion; `b` user stop | beta | 2 |
| `P-003` | `a` explicit SUPERSEDED preserves predecessor | beta | 1 |
| `P-004` | `a` authorized StopLoop closes execution with preserved evidence; `b` exact replay is idempotent; reject `c` stale revision; `d` forged/wrong-loop grant; boundary `e` unresolved Attempt stays UNKNOWN and is never presented as cancelled | beta | 5 |
| `L-001` | seven frozen nonterminal snapshots: `a` prepared; `b` attempt committed; `c` unknown; `d` unverifiable; `e` result staged; `f` repair; `g` finalization prepared | beta | 7 |
| `L-002` | measure `a` Pack bytes; `b` Host interactions; `c` protocol calls; `d` local writes; `e` latency; `f` unresolved outcomes | beta | 6 |

### User-experience compatibility

These cases exercise the future public facade, not alpha kernel commands. A
"public entry action" is one invocation or one accepted input-file launch; its
internal protocol calls do not count as additional user actions.

| Family | Atomic/parameterized instances | Gate | Count |
| --- | --- | --- | ---: |
| `UX-001` | fresh minimal goal via `a` one input-file action; `b` one main-command action enters the same-session INTAKE→PREPARE→CONFIRM→START flow and pauses for explicit confirmation before external effect | P5.1-before-P6 | 2 |
| `UX-002` | `a` default startup requires exactly zero user-provided control identities | beta | 1 |
| `UX-003` | `a` minimal startup requires no policy pack installation, selection, or knowledge | beta | 1 |
| `UX-004` | invalid `a` malformed input; `b` missing goal; `c` unsupported public option returns stable user error without handle/schema leakage | beta | 3 |
| `UX-005` | visible `a` UNKNOWN; `b` UNVERIFIABLE explains limitation/action and performs no automatic resend | beta | 2 |
| `UX-006` | v3 import `a` preview; `b` cancel preserves exact v3 bytes and leaves new v4 store absent or empty | beta | 2 |
| `UX-007` | `a` default status hides internal receipt/identity; `b` explicit diagnostics/export reveals bounded authorized diagnostics | beta | 2 |
| `UX-008` | same scenario measures `a` user-visible action count; `b` Pack/entry-artifact bytes against pre-observation frozen beta budget | beta | 2 |
| `UX-009` | `a` RC real non-research, private-data-free new-user canary proves intake zero effect → prepare zero Host effect → explicit digest-bound confirmation → one machine-owned start/readback without manual control identity | rc | 1 |
| `UX-010` | atomic intake outcomes `a` READY_FOR_LOOP; `b` NEEDS_CLARIFICATION; `c` BLOCKED; `d` DIRECT_TASK_RECOMMENDED, each with stable seven-section projection and at most three deduplicated questions | P5.1-before-P6 | 4 |
| `UX-011` | `a` intake is strictly read-only: 0 loop/task/heartbeat/provider/external effect | P5.1-before-P6 | 1 |
| `UX-012` | prepare `a` writes exactly five owner-only local artifacts (manifest, boundary, plan, Chinese guide, bundle) and 0 canonical/Host/execution effects; `b` readback verifies all digests with 0 writes; confirm `c` writes exactly one digest-bound local confirmation receipt and 0 canonical/Host effects | P5.1-before-P6 | 3 |
| `UX-013` | START rejects `a` absent confirmation; `b` expired confirmation; `c` changed manifest/boundary digest; `d` forged/wrong-scope receipt, each with 0 startup Attempt/Host call | P5.1-before-P6 | 4 |
| `UX-014` | `a` valid confirmation commits exactly one canonical startup Attempt with 0 Host calls; `b` identical replay returns the same result with no second commit/Attempt/Host call; Adapter `c` invokes once and authoritative readback binds machine Host identity; `d` missing readback yields UNKNOWN with no bind/resend | P5.1-before-P6 | 4 |
| `UX-015` | `a` DIRECT_TASK_RECOMMENDED creates 0 loop; `b` legacy Skill intake/prepare compatibility fixture remains behavior-equivalent; `c` user/LLM control identity count is exactly 0 | P5.1-before-P6 | 3 |
| `UX-016` | `a` high-impact automation without pre-signed digest-bound authority cannot use `--yes`, defaults, or noninteractive fallback to bypass confirmation | P5.1-before-P6 | 1 |

P5.1 case files use the full record format above. Their nonzero boundaries are
frozen separately so “zero Host effect” is never confused with “zero local
write”:

| Instance | Stimulus | Canonical commit/events | Local filesystem writes | Host/provider calls | Required typed events |
| --- | --- | --- | ---: | ---: | --- |
| `UX-011-a` | `ENTRY_ACTION intake` | 0 / 0 | 0 | 0 / 0 | none |
| `UX-012-a` | `ENTRY_ACTION prepare` with an existing owner-only empty output directory | 0 / 0 | 5 | 0 / 0 | none |
| `UX-012-b` | `ENTRY_ACTION load_prepared` | 0 / 0 | 0 | 0 / 0 | none |
| `UX-012-c` | `ENTRY_ACTION confirm` | 0 / 0 | 1 | 0 / 0 | none |
| `UX-014-a` | confirmed `KERNEL_COMMAND CreateLoop` | 1 / 5 | 0 | 0 / 0 | `LoopCreated`, `GoalRegistered`, `GoalActivated`, `StartAuthorized`, `ExternalEffectPrepared` |
| `UX-014-b` | exact CreateLoop replay | 0 / 0 | 0 | 0 / 0 | none; returns prior result |
| `UX-014-c` | `ADAPTER_CALL` invoke + strict readback, then observation command | 1 / 2 | 0 | 1 / 1 | `ExternalEffectObserved`, `HostResourceBound` |
| `UX-014-d` | `ADAPTER_CALL` invoke + missing readback, then observation command | 1 / 1 | 0 | 1 / 1 | `ExternalEffectUnknown`; no bind/resend |

“Local filesystem writes” counts preparation artifacts, not SQLite page/WAL
internals. “Canonical commit” is one logical Store transaction, and logical
local store reads/writes remain separately populated in each case's
`expected_counts`. Exact event objects and post-snapshot digests are generated
from the typed manifest/reducer fixture; event-name strings not declared by the
manifest are rejected by conformance validation.

### v3.3.8 product-capability preservation

These families are atomic preservation gates, not claims that v3 internal state
shape is a v4 contract. The machine-readable preservation registry contains
capability claims and exact case references only. The independent exact case
catalog below declares which references exist; executable case files, added at
the stage that owns each case, contain provenance, precondition, stimulus,
acceptance, effect state, ordered events, canonical expected-snapshot digest,
exact side-effect counts, and replay expectation. A binding index is never an
instance-existence authority, and a prose branch is never counted as an
instance.

| Family | New atomic instances and existing case aliases | Gate | New count |
| --- | --- | --- | ---: |
| `CAP-INTAKE` | new: `CAP-INTAKE-G01..G10`, four `CAP-INTAKE-STATUS-*`, seven `CAP-INTAKE-REPORT-01..07`, `CAP-INTAKE-QUESTIONS`; alias: `UX-011-a` | P5.1-before-P6 | 22 |
| `CAP-ENTRY` | aliases: `UX-001-a..b`, `UX-012-a..c`, `UX-013-a..d`, `UX-014-a..d`, `UX-015-a..c`, `UX-016-a` | P5.1-before-P6 | 0 |
| `CAP-MODES` | new: `CAP-MODES-DIRECT`, `CAP-MODES-STANDARD`, `CAP-MODES-ADAPTIVE`, `CAP-MODES-REJECT`, `CAP-MODES-BOUNDARY`, `CAP-MODES-ZERO` | beta | 6 |
| `CAP-ROLES` | new: `CAP-ROLES-WORKER`, `CAP-ROLES-REVIEWER`, `CAP-ROLES-LOCAL-VERIFIER`, `CAP-ROLES-WRONG-ROLE`, `CAP-ROLES-STALE-ARTIFACT`, `CAP-ROLES-ZERO`; aliases: `R-001-a`, `R-002-a`, `R-003-a` | beta | 6 |
| `CAP-HUMAN` | aliases: `K-007-a..b`, `P-002-b`, `P-004-a..e`, `UX-013-a..d`, `UX-014-a..b` | beta | 0 |
| `CAP-REPAIR` | aliases: `P-001-a`, `P-002-a`, `P-003-a`, `P-004-e` | beta | 0 |
| `CAP-OPERABILITY` | new: doctor pass/drift, compile pass/reject, canary pass/reject, lifecycle boundary, and zero-effect check under exact `CAP-OPERABILITY-*` IDs | rc | 8 |
| `CAP-AUDIT` | new: rejection, index, status, archive, tamper, legacy-boundary, next-action, and zero-writer projection under exact `CAP-AUDIT-*` IDs | beta | 8 |
| `CAP-PRIVACY` | new: scan/export pass, secret/PII/raw-log reject, stale allowlist, category boundary, and zero-effect under exact `CAP-PRIVACY-*` IDs | beta | 8 |
| `CAP-COMPAT` | new: legacy intake/generate/Pack-repair, compact/full/minimal-patch, sunset, and zero-effect under exact `CAP-COMPAT-*` IDs; alias: `UX-015-b` | beta | 8 |
| `CAP-DISTRIBUTION` | new: install, conflict, rollback, runtime identity, MCP, uninstall, drift, and zero-effect under exact `CAP-DISTRIBUTION-*` IDs | rc | 8 |
| `CAP-DOCS` | new: Chinese/English/minimal/Standard/Adaptive/migration, stale reject, and zero-effect under exact `CAP-DOCS-*` IDs | rc | 8 |
| `CAP-RELEASE` | new: SHA, manifest, compatibility CI, canary, SBOM, license, secret, artifact, failure, candidate drift, no-public-effect, and author packet under exact `CAP-RELEASE-*` IDs; aliases: `UX-009-a`, `F-001-a` | rc | 12 |
| `CAP-ARTIFACT` | aliases: all atomic `A-001`, `A-GIT-*`, `A-NONGIT-*`, `A-NEWGIT-*`, and `A-PATH-*` instances | beta | 0 |
| `CAP-ARCHITECTURE` | new: `CAP-ARCHITECTURE-ONE-WRITER`, `CAP-ARCHITECTURE-FORBIDDEN-IMPORT`, `CAP-ARCHITECTURE-MINIMAL-ISOLATION`, `CAP-ARCHITECTURE-NO-LEGACY-BRANCHES` | P5.1-before-P6 | 4 |

The following catalog is the independent existence authority for the 343
atomic case identities declared by this design. `parameterized_families`
machine-expands an existing family row as `<family>-<parameter>`;
`preservation_declarations` names each new `CAP-*` case explicitly. The
preservation registry and binding index may only refer to this catalog; neither
can create a case by adding a plausible suffix.

<!-- CORPUS-EXACT-CASE-CATALOG-BEGIN -->
```json
{
  "schema_version": "loopskill-v4-exact-case-catalog-v1",
  "parameterized_families": {
    "K-001": ["a"],
    "K-002": ["a", "b"],
    "K-003": ["op01", "op02", "op03", "op04", "op05", "op06", "op07", "op08", "op09", "op10", "op11"],
    "K-004": ["a", "b", "c"],
    "K-005": ["a", "b", "c", "d"],
    "K-006": ["a", "b", "c"],
    "K-007": ["a", "b"],
    "K-008": ["a", "b"],
    "K-009": ["a", "b", "c", "d"],
    "AUTH-001": ["a", "b", "c", "d", "e", "f", "g", "h"],
    "AUTH-002": ["a", "b"],
    "AUTH-003": ["a", "b"],
    "AUTH-004": ["a", "b", "c"],
    "AUTH-005": ["a", "b", "c"],
    "AUTH-006": ["a", "b", "c", "d"],
    "RES-001": ["a", "b", "c", "d", "e"],
    "ENC-001": ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"],
    "REJ-001": ["a", "b"],
    "S-001": ["op01-a", "op01-b", "op01-c", "op02-a", "op02-b", "op02-c", "op03-a", "op03-b", "op03-c", "op04-a", "op04-b", "op04-c", "op05-a", "op05-b", "op05-c", "op06-a", "op06-b", "op06-c", "op07-a", "op07-b", "op07-c", "op08-a", "op08-b", "op08-c", "op09-a", "op09-b", "op09-c", "op10-a", "op10-b", "op10-c", "op11-a", "op11-b", "op11-c"],
    "S-002": ["a"],
    "S-003": ["a"],
    "S-004": ["a", "b"],
    "S-005": ["a", "b"],
    "S-006": ["a", "b"],
    "XFX-001": ["a"],
    "XFX-002": ["a"],
    "XFX-003": ["a"],
    "XFX-004": ["a"],
    "XFX-005": ["a", "b"],
    "XFX-006": ["a", "b"],
    "XFX-007": ["a", "b"],
    "XFX-008": ["a", "b", "c"],
    "H-001": ["a"],
    "H-002": ["a"],
    "H-003": ["a", "b"],
    "H-004": ["a", "b"],
    "H-005": ["a", "b"],
    "H-006": ["a", "b"],
    "H-007": ["a", "b", "c"],
    "H-008": ["a", "b"],
    "H-009": ["a", "b", "c"],
    "H-010": ["a", "b"],
    "H-011": ["a", "b", "c", "d"],
    "A-001": ["a", "b"],
    "A-GIT-001": ["a"],
    "A-GIT-002": ["a", "b"],
    "A-GIT-003": ["a"],
    "A-NONGIT-001": ["a", "b", "c"],
    "A-NONGIT-002": ["a"],
    "A-NEWGIT-001": ["a"],
    "A-PATH-001": ["a", "b", "c", "d", "e"],
    "R-001": ["a"],
    "R-002": ["a"],
    "R-003": ["a"],
    "R-004": ["a", "b", "c"],
    "F-001": ["a"],
    "F-002": ["a", "b"],
    "F-003": ["a", "b"],
    "F-004": ["a", "b"],
    "M-001": ["a"],
    "M-002": ["a", "b"],
    "M-003": ["a"],
    "M-004": ["a", "b", "c", "d"],
    "M-005": ["a"],
    "P-001": ["a"],
    "P-002": ["a", "b"],
    "P-003": ["a"],
    "P-004": ["a", "b", "c", "d", "e"],
    "L-001": ["a", "b", "c", "d", "e", "f", "g"],
    "L-002": ["a", "b", "c", "d", "e", "f"],
    "UX-001": ["a", "b"],
    "UX-002": ["a"],
    "UX-003": ["a"],
    "UX-004": ["a", "b", "c"],
    "UX-005": ["a", "b"],
    "UX-006": ["a", "b"],
    "UX-007": ["a", "b"],
    "UX-008": ["a", "b"],
    "UX-009": ["a"],
    "UX-010": ["a", "b", "c", "d"],
    "UX-011": ["a"],
    "UX-012": ["a", "b", "c"],
    "UX-013": ["a", "b", "c", "d"],
    "UX-014": ["a", "b", "c", "d"],
    "UX-015": ["a", "b", "c"],
    "UX-016": ["a"]
  },
  "preservation_declarations": [
    "CAP-INTAKE-G01", "CAP-INTAKE-G02", "CAP-INTAKE-G03", "CAP-INTAKE-G04", "CAP-INTAKE-G05", "CAP-INTAKE-G06", "CAP-INTAKE-G07", "CAP-INTAKE-G08", "CAP-INTAKE-G09", "CAP-INTAKE-G10",
    "CAP-INTAKE-STATUS-READY", "CAP-INTAKE-STATUS-CLARIFICATION", "CAP-INTAKE-STATUS-BLOCKED", "CAP-INTAKE-STATUS-DIRECT",
    "CAP-INTAKE-REPORT-01", "CAP-INTAKE-REPORT-02", "CAP-INTAKE-REPORT-03", "CAP-INTAKE-REPORT-04", "CAP-INTAKE-REPORT-05", "CAP-INTAKE-REPORT-06", "CAP-INTAKE-REPORT-07", "CAP-INTAKE-QUESTIONS",
    "CAP-MODES-DIRECT", "CAP-MODES-STANDARD", "CAP-MODES-ADAPTIVE", "CAP-MODES-REJECT", "CAP-MODES-BOUNDARY", "CAP-MODES-ZERO",
    "CAP-ROLES-WORKER", "CAP-ROLES-REVIEWER", "CAP-ROLES-LOCAL-VERIFIER", "CAP-ROLES-WRONG-ROLE", "CAP-ROLES-STALE-ARTIFACT", "CAP-ROLES-ZERO",
    "CAP-OPERABILITY-DOCTOR-PASS", "CAP-OPERABILITY-DOCTOR-DRIFT", "CAP-OPERABILITY-COMPILE-PASS", "CAP-OPERABILITY-COMPILE-REJECT", "CAP-OPERABILITY-CANARY-PASS", "CAP-OPERABILITY-CANARY-REJECT", "CAP-OPERABILITY-LIFECYCLE-BOUNDARY", "CAP-OPERABILITY-ZERO",
    "CAP-AUDIT-REJECTION", "CAP-AUDIT-INDEX", "CAP-AUDIT-STATUS", "CAP-AUDIT-ARCHIVE", "CAP-AUDIT-TAMPER", "CAP-AUDIT-LEGACY-BOUNDARY", "CAP-AUDIT-NEXT-ACTION", "CAP-AUDIT-ZERO",
    "CAP-PRIVACY-SCAN-PASS", "CAP-PRIVACY-EXPORT-PASS", "CAP-PRIVACY-SECRET-REJECT", "CAP-PRIVACY-PII-REJECT", "CAP-PRIVACY-RAW-LOG-REJECT", "CAP-PRIVACY-ALLOWLIST-STALE", "CAP-PRIVACY-CATEGORY-BOUNDARY", "CAP-PRIVACY-ZERO",
    "CAP-COMPAT-INTAKE", "CAP-COMPAT-GENERATE", "CAP-COMPAT-PACK-REPAIR", "CAP-COMPAT-COMPACT", "CAP-COMPAT-FULL", "CAP-COMPAT-MINIMAL-PATCH", "CAP-COMPAT-SUNSET", "CAP-COMPAT-ZERO",
    "CAP-DISTRIBUTION-INSTALL", "CAP-DISTRIBUTION-CONFLICT", "CAP-DISTRIBUTION-ROLLBACK", "CAP-DISTRIBUTION-RUNTIME-ID", "CAP-DISTRIBUTION-MCP", "CAP-DISTRIBUTION-UNINSTALL", "CAP-DISTRIBUTION-DRIFT", "CAP-DISTRIBUTION-ZERO",
    "CAP-DOCS-ZH-QUICKSTART", "CAP-DOCS-EN-QUICKSTART", "CAP-DOCS-MINIMAL", "CAP-DOCS-STANDARD", "CAP-DOCS-ADAPTIVE", "CAP-DOCS-MIGRATION", "CAP-DOCS-STALE-REJECT", "CAP-DOCS-ZERO",
    "CAP-RELEASE-SHA", "CAP-RELEASE-MANIFEST", "CAP-RELEASE-COMPAT-CI", "CAP-RELEASE-CANARY", "CAP-RELEASE-SBOM", "CAP-RELEASE-LICENSE", "CAP-RELEASE-SECRET", "CAP-RELEASE-ARTIFACT", "CAP-RELEASE-FAILURE", "CAP-RELEASE-CANDIDATE-DRIFT", "CAP-RELEASE-NO-PUBLIC-EFFECT", "CAP-RELEASE-AUTHOR-PACKET",
    "CAP-ARCHITECTURE-ONE-WRITER", "CAP-ARCHITECTURE-FORBIDDEN-IMPORT", "CAP-ARCHITECTURE-MINIMAL-ISOLATION", "CAP-ARCHITECTURE-NO-LEGACY-BRANCHES"
  ]
}
```
<!-- CORPUS-EXACT-CASE-CATALOG-END -->

The canonical expansion below is the exact preservation binding index. It
contains no duplicate test case; aliases point to an instance already counted
in its original family. The 98 new `CAP-*` IDs are counted above, while every
other entry is an existing atomic corpus ID.

<!-- PRESERVATION-CASE-BINDING-INDEX-BEGIN -->
```json
[
  "A-001-a",
  "A-001-b",
  "A-GIT-001-a",
  "A-GIT-002-a",
  "A-GIT-002-b",
  "A-GIT-003-a",
  "A-NEWGIT-001-a",
  "A-NONGIT-001-a",
  "A-NONGIT-001-b",
  "A-NONGIT-001-c",
  "A-NONGIT-002-a",
  "A-PATH-001-a",
  "A-PATH-001-b",
  "A-PATH-001-c",
  "A-PATH-001-d",
  "A-PATH-001-e",
  "AUTH-001-a",
  "AUTH-001-b",
  "AUTH-001-c",
  "AUTH-001-d",
  "AUTH-001-e",
  "AUTH-001-f",
  "AUTH-001-g",
  "AUTH-001-h",
  "AUTH-002-a",
  "AUTH-002-b",
  "AUTH-003-a",
  "AUTH-003-b",
  "AUTH-004-a",
  "AUTH-004-b",
  "AUTH-004-c",
  "AUTH-005-a",
  "AUTH-005-b",
  "AUTH-005-c",
  "AUTH-006-a",
  "AUTH-006-b",
  "AUTH-006-c",
  "AUTH-006-d",
  "CAP-ARCHITECTURE-FORBIDDEN-IMPORT",
  "CAP-ARCHITECTURE-MINIMAL-ISOLATION",
  "CAP-ARCHITECTURE-NO-LEGACY-BRANCHES",
  "CAP-ARCHITECTURE-ONE-WRITER",
  "CAP-AUDIT-ARCHIVE",
  "CAP-AUDIT-INDEX",
  "CAP-AUDIT-LEGACY-BOUNDARY",
  "CAP-AUDIT-NEXT-ACTION",
  "CAP-AUDIT-REJECTION",
  "CAP-AUDIT-STATUS",
  "CAP-AUDIT-TAMPER",
  "CAP-AUDIT-ZERO",
  "CAP-COMPAT-COMPACT",
  "CAP-COMPAT-FULL",
  "CAP-COMPAT-GENERATE",
  "CAP-COMPAT-INTAKE",
  "CAP-COMPAT-MINIMAL-PATCH",
  "CAP-COMPAT-PACK-REPAIR",
  "CAP-COMPAT-SUNSET",
  "CAP-COMPAT-ZERO",
  "CAP-DISTRIBUTION-CONFLICT",
  "CAP-DISTRIBUTION-DRIFT",
  "CAP-DISTRIBUTION-INSTALL",
  "CAP-DISTRIBUTION-MCP",
  "CAP-DISTRIBUTION-ROLLBACK",
  "CAP-DISTRIBUTION-RUNTIME-ID",
  "CAP-DISTRIBUTION-UNINSTALL",
  "CAP-DISTRIBUTION-ZERO",
  "CAP-DOCS-ADAPTIVE",
  "CAP-DOCS-EN-QUICKSTART",
  "CAP-DOCS-MIGRATION",
  "CAP-DOCS-MINIMAL",
  "CAP-DOCS-STALE-REJECT",
  "CAP-DOCS-STANDARD",
  "CAP-DOCS-ZERO",
  "CAP-DOCS-ZH-QUICKSTART",
  "CAP-INTAKE-G01",
  "CAP-INTAKE-G02",
  "CAP-INTAKE-G03",
  "CAP-INTAKE-G04",
  "CAP-INTAKE-G05",
  "CAP-INTAKE-G06",
  "CAP-INTAKE-G07",
  "CAP-INTAKE-G08",
  "CAP-INTAKE-G09",
  "CAP-INTAKE-G10",
  "CAP-INTAKE-QUESTIONS",
  "CAP-INTAKE-REPORT-01",
  "CAP-INTAKE-REPORT-02",
  "CAP-INTAKE-REPORT-03",
  "CAP-INTAKE-REPORT-04",
  "CAP-INTAKE-REPORT-05",
  "CAP-INTAKE-REPORT-06",
  "CAP-INTAKE-REPORT-07",
  "CAP-INTAKE-STATUS-BLOCKED",
  "CAP-INTAKE-STATUS-CLARIFICATION",
  "CAP-INTAKE-STATUS-DIRECT",
  "CAP-INTAKE-STATUS-READY",
  "CAP-MODES-ADAPTIVE",
  "CAP-MODES-BOUNDARY",
  "CAP-MODES-DIRECT",
  "CAP-MODES-REJECT",
  "CAP-MODES-STANDARD",
  "CAP-MODES-ZERO",
  "CAP-OPERABILITY-CANARY-PASS",
  "CAP-OPERABILITY-CANARY-REJECT",
  "CAP-OPERABILITY-COMPILE-PASS",
  "CAP-OPERABILITY-COMPILE-REJECT",
  "CAP-OPERABILITY-DOCTOR-DRIFT",
  "CAP-OPERABILITY-DOCTOR-PASS",
  "CAP-OPERABILITY-LIFECYCLE-BOUNDARY",
  "CAP-OPERABILITY-ZERO",
  "CAP-PRIVACY-ALLOWLIST-STALE",
  "CAP-PRIVACY-CATEGORY-BOUNDARY",
  "CAP-PRIVACY-EXPORT-PASS",
  "CAP-PRIVACY-PII-REJECT",
  "CAP-PRIVACY-RAW-LOG-REJECT",
  "CAP-PRIVACY-SCAN-PASS",
  "CAP-PRIVACY-SECRET-REJECT",
  "CAP-PRIVACY-ZERO",
  "CAP-RELEASE-ARTIFACT",
  "CAP-RELEASE-AUTHOR-PACKET",
  "CAP-RELEASE-CANARY",
  "CAP-RELEASE-CANDIDATE-DRIFT",
  "CAP-RELEASE-COMPAT-CI",
  "CAP-RELEASE-FAILURE",
  "CAP-RELEASE-LICENSE",
  "CAP-RELEASE-MANIFEST",
  "CAP-RELEASE-NO-PUBLIC-EFFECT",
  "CAP-RELEASE-SBOM",
  "CAP-RELEASE-SECRET",
  "CAP-RELEASE-SHA",
  "CAP-ROLES-LOCAL-VERIFIER",
  "CAP-ROLES-REVIEWER",
  "CAP-ROLES-STALE-ARTIFACT",
  "CAP-ROLES-WORKER",
  "CAP-ROLES-WRONG-ROLE",
  "CAP-ROLES-ZERO",
  "ENC-001-a",
  "ENC-001-b",
  "ENC-001-c",
  "ENC-001-d",
  "ENC-001-e",
  "ENC-001-f",
  "ENC-001-g",
  "ENC-001-h",
  "ENC-001-i",
  "ENC-001-j",
  "F-001-a",
  "F-002-a",
  "F-002-b",
  "F-003-a",
  "F-003-b",
  "F-004-a",
  "F-004-b",
  "H-001-a",
  "H-002-a",
  "H-003-a",
  "H-003-b",
  "H-004-a",
  "H-004-b",
  "H-005-a",
  "H-005-b",
  "H-006-a",
  "H-006-b",
  "H-007-a",
  "H-007-b",
  "H-007-c",
  "H-008-a",
  "H-008-b",
  "H-009-a",
  "H-009-b",
  "H-009-c",
  "H-010-a",
  "H-010-b",
  "H-011-a",
  "H-011-b",
  "H-011-c",
  "H-011-d",
  "K-001-a",
  "K-002-a",
  "K-002-b",
  "K-003-op01",
  "K-003-op02",
  "K-003-op03",
  "K-003-op04",
  "K-003-op05",
  "K-003-op06",
  "K-003-op07",
  "K-003-op08",
  "K-003-op09",
  "K-003-op10",
  "K-003-op11",
  "K-004-a",
  "K-004-b",
  "K-004-c",
  "K-005-a",
  "K-005-b",
  "K-005-c",
  "K-005-d",
  "K-006-a",
  "K-006-b",
  "K-006-c",
  "K-007-a",
  "K-007-b",
  "K-008-a",
  "K-008-b",
  "K-009-a",
  "K-009-b",
  "K-009-c",
  "K-009-d",
  "L-002-a",
  "L-002-b",
  "L-002-c",
  "L-002-d",
  "L-002-e",
  "L-002-f",
  "M-001-a",
  "M-002-a",
  "M-002-b",
  "M-003-a",
  "M-004-a",
  "M-004-b",
  "M-004-c",
  "M-004-d",
  "M-005-a",
  "P-001-a",
  "P-002-a",
  "P-002-b",
  "P-003-a",
  "P-004-a",
  "P-004-b",
  "P-004-c",
  "P-004-d",
  "P-004-e",
  "R-001-a",
  "R-002-a",
  "R-003-a",
  "R-004-a",
  "R-004-b",
  "R-004-c",
  "REJ-001-a",
  "REJ-001-b",
  "RES-001-a",
  "RES-001-b",
  "RES-001-c",
  "RES-001-d",
  "RES-001-e",
  "S-001-op01-a",
  "S-001-op01-b",
  "S-001-op01-c",
  "S-001-op02-a",
  "S-001-op02-b",
  "S-001-op02-c",
  "S-001-op03-a",
  "S-001-op03-b",
  "S-001-op03-c",
  "S-001-op04-a",
  "S-001-op04-b",
  "S-001-op04-c",
  "S-001-op05-a",
  "S-001-op05-b",
  "S-001-op05-c",
  "S-001-op06-a",
  "S-001-op06-b",
  "S-001-op06-c",
  "S-001-op07-a",
  "S-001-op07-b",
  "S-001-op07-c",
  "S-001-op08-a",
  "S-001-op08-b",
  "S-001-op08-c",
  "S-001-op09-a",
  "S-001-op09-b",
  "S-001-op09-c",
  "S-001-op10-a",
  "S-001-op10-b",
  "S-001-op10-c",
  "S-001-op11-a",
  "S-001-op11-b",
  "S-001-op11-c",
  "S-002-a",
  "S-003-a",
  "S-005-a",
  "S-005-b",
  "UX-001-a",
  "UX-001-b",
  "UX-006-a",
  "UX-006-b",
  "UX-009-a",
  "UX-011-a",
  "UX-012-a",
  "UX-012-b",
  "UX-012-c",
  "UX-013-a",
  "UX-013-b",
  "UX-013-c",
  "UX-013-d",
  "UX-014-a",
  "UX-014-b",
  "UX-014-c",
  "UX-014-d",
  "UX-015-a",
  "UX-015-b",
  "UX-015-c",
  "UX-016-a",
  "XFX-001-a",
  "XFX-002-a",
  "XFX-003-a",
  "XFX-004-a",
  "XFX-005-a",
  "XFX-005-b",
  "XFX-006-a",
  "XFX-006-b",
  "XFX-007-a",
  "XFX-007-b",
  "XFX-008-a",
  "XFX-008-b",
  "XFX-008-c"
]
```
<!-- PRESERVATION-CASE-BINDING-INDEX-END -->

<!-- INSTANCE-CATALOG-END -->

The catalog contains exactly **101 families and 343 independently reportable
instances**. Counts are machine-recomputed during readiness review; they are
not inferred from prose.

## External-effect fault semantics

The instance expectations for the executor windows are fixed:

| Window | Acceptance | Subject/Attempt | Provider calls | Automatic budget |
| --- | --- | --- | ---: | --- |
| before local Attempt commit | crash/no acceptance | PREPARED / absent | 0 | available |
| after commit, before invocation | accepted commit then crash | ATTEMPT_COMMITTED / COMMITTED | 0 | consumed |
| provider accepted, response lost | local Attempt already committed | remains COMMITTED until readback | 1 | consumed |
| provider response, pre-observation crash | local Attempt already committed | remains COMMITTED until readback | 1 | consumed |
| readback unavailable/inconclusive | ACCEPT observation command | UNKNOWN / UNKNOWN | no new call | consumed |
| cooperative response | ACCEPT | UNVERIFIABLE / UNVERIFIABLE | no new call | consumed |
| exact late authoritative readback | ACCEPT | OBSERVED / OBSERVED | no new call | consumed |

Late observation requires exact original loop, typed subject kind/ref
(`DeliveryRef` or `ExternalEffectRef`), AttemptRef, target, action, provider
request digest/idempotency key, trusted issuer, and freshness.
It never creates an Attempt, resends, restages Result, reopens execution, or
changes terminal disposition. A separate exact-chain command may strengthen
assurance.

## Store fault boundaries

The reference in-memory store declares exactly three injectable boundaries per
mutation:

1. `before_reduce`: no tentative post-state exists;
2. `after_reduce_before_commit`: tentative result/events exist only in an
   isolated copy; crash discards them; and
3. `after_commit_before_response`: snapshot, events, and operation result are
   atomically committed; crash loses only response delivery and replay returns
   that result.

No boundary exists between idempotency result, events, and snapshot because
they are one commit object. Adding a boundary later expands `S-001` before any
claim. For 11 operations × 3 boundaries, `S-001` has 33 instances.

## v3 provenance mapping

Mappings preserve safety semantics, not v3's state shape.

Public baseline commit:
`843945d9d34e7f065b65d9172ea4a2df66c0f2e3`.

- local CAS/crash: `codex-loop-prompt-architect/scripts/loop_architect/state_runtime.py::AdaptiveStateRuntime`; `tests/test_state_runtime_recovery.py::test_schema_v3_gateway_send_artifact_crash_recovers_without_duplicate_route`;
- Git binary/path: `state_runtime.py::capture_complete_diff`; `tests/test_state_runtime_io.py::test_runtime_captures_binary_diff_without_model_patch_transport`; `::test_complete_diff_rejects_symlinked_control_capture_paths_without_outside_write`;
- replay/receipt identity: `tests/test_control_plane_reliability_baseline.py::test_exact_route_replay_is_read_only_without_second_attestation`; `::test_external_receipt_requires_canonical_route_and_provider_identity`;
- finalization separation: `docs/adr/0008-finalization-acked.md`; and
- typed boundary/Gateway: `docs/adr/0009-typed-mcp-runtime-codec.md`, `docs/adr/0010-mcp-state-gateway.md`.

Treatment/reference commit:
`54442e22c3ce483823c911dfa8d03a52c85922e6`.

- prepared replay: `tests/test_prepare_route_replay_recovery.py::test_discarded_prepare_response_recovers_and_follows_full_route_closure`;
- non-Git algorithm: `codex-loop-prompt-architect/scripts/loop_architect/state_runtime.py::_capture_prepared_manifest_baseline_locked` and `::capture_manifest_delta`;
- non-Git vertical: `tests/test_non_git_manifest_pipeline.py::test_official_non_git_pack_reaches_reviewable_pass_without_git_capture`;
- crash stages: `tests/test_state_runtime_recovery.py::test_crash_injection_every_persistent_stage_recovers_once`; and
- Report identity: `codex-loop-prompt-architect/scripts/loop_architect/report_contract.py::stage_report_request_schema`; `tests/test_state_runtime_reports.py::test_role_authored_report_exact_bytes_define_runtime_identity`.

Every frozen case later records full SHA, full object path, test/symbol identity,
and content digest. A tag name alone is insufficient. Treatment provenance does
not imply public release.

## Corpus versioning

- patch: metadata clarification with no input/output/digest/gate change;
- minor: additive family/instance/profile;
- major: changed canonicalization, existing expectation, command/event/error
  semantics, or gate meaning.

Frozen instance IDs are immutable. A correction creates a superseding ID and
preserves the predecessor. The corpus has one manifest, immutable cases, and
embedded provenance only—no runtime state, heartbeat, retry, Supervisor,
approval engine, or independent finalization process.

## Corrected pure-kernel vertical trace

### Why the event count changes

The operation count remains 11. The earlier 16-event trace overloaded Delivery
with Result acceptance and omitted final Result/Report bindings. The corrected
trace emits 18 events: separate `ReportStaged`, `ReportAccepted`,
`ResultAcknowledged`, and strict-assurance evidence replace the overloaded
`EffectAcknowledged`/`LoopCompleted` representation. This is the minimum change
needed to eliminate the semantic contradiction; no hidden state is introduced.

### Fixed profile, actors, grants, and receipts

- case: `K-001-a` / `K-001-VERTICAL-002`;
- protocol: `4.0-draft.2`;
- synthetic time: step `N` uses `2026-07-27T00:00:(N-1)Z`, `00` through `10`;
- provider/network/Git/filesystem calls: exactly `0`;
- all “strict” receipts are `conformance-fixture` inputs and prove reducer logic
  only, never real Host conformance.

Authority registry:

| Actor / Grant | Exact scope |
| --- | --- |
| `actor-author-0001` / `grant-create-0001` | trusted fixture issuer; `CreateLoop`; namespace `loop-0001` |
| `actor-system-0001` / `grant-system-0001` | loop `loop-0001`; `BindHostResource`, `CloseExecution`; exact relevant subjects |
| `actor-author-0001` / `grant-author-0001` | loop `loop-0001`; `PrepareRoute`, `AcknowledgeResult`, `AdvanceGoal`, `PrepareFinalization` |
| `actor-executor-0001` / `grant-executor-0001` | loop `loop-0001`; `BeginEffectDelivery`, `RecordEffectObservation`; Delivery `delivery-0001` |
| `actor-worker-0001` / `grant-worker-0001` | loop `loop-0001`; `StageResult`; route `route-0001` |
| `actor-reviewer-0001` / `grant-reviewer-0001` | loop `loop-0001`; `RecordReview`; Result `result-0001` |

All grants are fixture-trusted from `2026-07-27T00:00:00Z` through
`2026-07-27T00:01:00Z` and have unique nonces/digests.

Receipt registry:

| Receipt | Exact binding |
| --- | --- |
| `receipt-bind-0001` | trusted fixture; bind logical worker to `host-target-0001` |
| `receipt-delivery-0001` | trusted fixture; send; loop/Delivery/Attempt/target; provider key `effect-0001`; exact provider-request digest; outcome observed |
| `receipt-artifact-0001` | local fixture; verify Artifact `artifact-0001` for Result `result-0001`; exact content digest |
| `receipt-finalize-0001` | trusted fixture authoritative lifecycle readback for exact `finalization-0001` and unchanged chain |

Fixed derived digests:

- Goal objective: `353bd5cb07f8fc0496eace49934e6b13238fb34cd287c31a04897b9d22a5f8ec`;
- Route intent: `4f8294df9f9485909e7d478819bcfb0aae91c3685864946c1bdea3c0451148b3`;
- provider request: `fce45c1a21cfc670d0007e468a04d665c96620e2027208fcaa70061c9544663d`;
- Report content: `261f2ba50f8d3a03e41d86837f4dcba8b580b2629bd2e9726c641ed50c8ec74a`;
- Artifact content: `52f71f6c1d592908c2902907fc674a225f3d04030ef6d9b4dedd9ede4b677fe7`;
- Review subject chain: `c8a7794089c17bfbacb33ea413bc3f22bb81c7646336bf5bec8dddd05303b94b`;
- Finalization chain: `ff690e9ec52836b8c5d657fc0d5c71d94a83498a20ee4f10f354f34c4e907062`.

### Exact commands

Every row is a closed machine envelope with the shown Actor/Grant, subject,
expected loop revision, subject revisions, `machine_bindings`, and semantic
payload. IDs/times/revisions/references/allocations/receipts are machine fields.

| Step | Operation; Actor/Grant | Subject and expected revisions | Semantic payload / allocation |
| --- | --- | --- | --- |
| 1 | `op-0001 CreateLoop`; author/create | new `loop-0001`; loop `0`; no subject revisions | objective `conformance bounded change`; allocate Goal `goal-0001` |
| 2 | `op-0002 BindHostResource`; system/system | loop; loop `1`; execution `1` | role `worker`; allocate `host-target-0001`; machine receipt bind |
| 3 | `op-0003 PrepareRoute`; author/author | Goal `goal-0001`; loop `2`; Goal `1`, HostResource `1` | intent `produce bounded result`; allocate Route `route-0001`, Delivery `delivery-0001` |
| 4 | `op-0004 BeginEffectDelivery`; executor/executor | Delivery; loop `3`; Route `1`, Delivery `1`, HostResource `1` | none; allocate Attempt `attempt-0001`, consume ordinal/budget `1` |
| 5 | `op-0005 RecordEffectObservation`; executor/executor | Attempt; loop `4`; Delivery `2`, Attempt `1` | none; machine receipt delivery |
| 6 | `op-0006 StageResult`; worker/worker | Route; loop `5`; Route `1`, Delivery `3`, Attempt `2` | outcome `PASS`, summary `bounded result complete`; allocate Result `result-0001`, Report `report-0001` |
| 7 | `op-0007 AcknowledgeResult`; author/author | Result; loop `6`; Result `1`, Report `1`, Delivery `3`, Attempt `2` | none; allocate Artifact `artifact-0001`; machine Artifact receipt |
| 8 | `op-0008 RecordReview`; reviewer/reviewer | Result; loop `7`; Result `2`, Report `2`, Artifact `1` | verdict `PASS`; allocate Review `review-0001` |
| 9 | `op-0009 AdvanceGoal`; author/author | Goal; loop `8`; Goal `1`, Review `1` | disposition `DONE` |
| 10 | `op-0010 PrepareFinalization`; author/author | loop; loop `9`; exact Goal/Route/Delivery/Attempt/Result/Report/Artifact/Review revisions | disposition `SUCCEEDED`; allocate `finalization-0001` |
| 11 | `op-0011 CloseExecution`; system/system | Finalization; loop `10`; Finalization `1` plus unchanged chain | none; machine final readback receipt |

### Exact outputs and ordered events

| Step | Loop revision; aggregate result | Events |
| --- | --- | --- |
| 1 | `1`; execution ACTIVE rev1, Goal ACTIVE rev1 | `1 LoopCreated`, `2 GoalRegistered`, `3 GoalActivated` |
| 2 | `2`; HostResource BOUND rev1 | `4 HostResourceBound` |
| 3 | `3`; Route rev1, Delivery PREPARED rev1 | `5 RoutePrepared` |
| 4 | `4`; Delivery ATTEMPT_COMMITTED rev2, Attempt COMMITTED rev1 | `6 DeliveryAttemptCommitted` |
| 5 | `5`; Delivery OBSERVED rev3, Attempt OBSERVED rev2 | `7 DeliveryObserved` |
| 6 | `6`; Result STAGED rev1, Report STAGED rev1 | `8 ResultStaged`, `9 ReportStaged` |
| 7 | `7`; Artifact VERIFIED rev1, Report ACCEPTED rev2, Result ACKNOWLEDGED rev2 | `10 ArtifactCaptured`, `11 ArtifactVerified`, `12 ReportAccepted`, `13 ResultAcknowledged` |
| 8 | `8`; Review PASS rev1 | `14 ReviewRecorded` |
| 9 | `9`; Goal DONE rev2 | `15 GoalAdvanced` |
| 10 | `10`; execution FINALIZING rev2, Finalization PREPARED rev1 | `16 FinalizationPrepared` |
| 11 | `11`; execution TERMINAL/SUCCEEDED rev3, Finalization CLOSED rev2, assurance STRICT rev1 | `17 ExecutionFinalized`, `18 StrictFinalizationAcknowledged` |

### Exact final canonical snapshot

The following is one UTF-8 line with no trailing newline:

```json
{"artifacts":{"artifact-0001":{"content_digest":"52f71f6c1d592908c2902907fc674a225f3d04030ef6d9b4dedd9ede4b677fe7","receipt_ref":"receipt-artifact-0001","result_ref":"result-0001","revision":1,"state":"VERIFIED"}},"attempts":{"attempt-0001":{"automatic_budget_consumed":true,"delivery_ref":"delivery-0001","executor_actor_ref":"actor-executor-0001","executor_grant_ref":"grant-executor-0001","observation_receipt_ref":"receipt-delivery-0001","ordinal":1,"provider_idempotency_key":"effect-0001","provider_request_digest":"fce45c1a21cfc670d0007e468a04d665c96620e2027208fcaa70061c9544663d","revision":2,"state":"OBSERVED","target_ref":"host-target-0001"}},"closure_assurance":{"finalization_ref":"finalization-0001","receipt_ref":"receipt-finalize-0001","revision":1,"strength":"STRICT"},"deliveries":{"delivery-0001":{"attempt_ref":"attempt-0001","automatic_attempt_budget":1,"automatic_attempts_consumed":1,"revision":3,"route_ref":"route-0001","state":"OBSERVED","target_ref":"host-target-0001"}},"execution":{"disposition":"SUCCEEDED","revision":3,"state":"TERMINAL"},"finalizations":{"finalization-0001":{"artifact_ref":"artifact-0001","assurance_strength":"STRICT","attempt_ref":"attempt-0001","delivery_ref":"delivery-0001","disposition":"SUCCEEDED","goal_ref":"goal-0001","report_ref":"report-0001","result_ref":"result-0001","review_ref":"review-0001","revision":2,"route_ref":"route-0001","state":"EXECUTION_CLOSED","subject_chain_digest":"ff690e9ec52836b8c5d657fc0d5c71d94a83498a20ee4f10f354f34c4e907062"}},"goals":{"goal-0001":{"objective_digest":"353bd5cb07f8fc0496eace49934e6b13238fb34cd287c31a04897b9d22a5f8ec","revision":2,"state":"DONE"}},"host_resources":{"host-target-0001":{"receipt_ref":"receipt-bind-0001","revision":1,"state":"BOUND"}},"loop_ref":"loop-0001","loop_revision":11,"reports":{"report-0001":{"author_actor_ref":"actor-worker-0001","content_digest":"261f2ba50f8d3a03e41d86837f4dcba8b580b2629bd2e9726c641ed50c8ec74a","result_ref":"result-0001","revision":2,"state":"ACCEPTED"}},"results":{"result-0001":{"artifact_ref":"artifact-0001","attempt_ref":"attempt-0001","delivery_ref":"delivery-0001","outcome":"PASS","report_ref":"report-0001","revision":2,"route_ref":"route-0001","state":"ACKNOWLEDGED"}},"reviews":{"review-0001":{"artifact_ref":"artifact-0001","report_ref":"report-0001","result_ref":"result-0001","reviewer_actor_ref":"actor-reviewer-0001","revision":1,"state":"PASS","subject_chain_digest":"c8a7794089c17bfbacb33ea413bc3f22bb81c7646336bf5bec8dddd05303b94b"}},"routes":{"route-0001":{"delivery_ref":"delivery-0001","goal_ref":"goal-0001","intent_digest":"4f8294df9f9485909e7d478819bcfb0aae91c3685864946c1bdea3c0451148b3","revision":1,"target_ref":"host-target-0001"}}}
```

- canonical snapshot bytes: `2715`;
- domain-separated snapshot digest:
  `8037bcb1cddd1686869c4743e6210e6f2d99e8120b1197b863fa38a5f241bd3f`;
- accepted mutations/atomic commits: `11`;
- ordered events: `18`;
- real provider/network/Git/artifact filesystem/Host effects: `0`.

Result `result-0001`, Report `report-0001`, Artifact `artifact-0001`, Review
`review-0001`, and Finalization `finalization-0001` remain explicitly bound in
the final snapshot. There is no `store_version`; loop CAS is revision `11`.

### Corrected vertical acceptance

The slice passes only if:

1. all 11 exact envelopes produce the stated revisions, 18 event order, 2715
   bytes, and exact digest;
2. replay of every operation produces no second commit/event/handle/effect;
3. same operation ID with changed request conflicts;
4. stale loop/subject revision, foreign/wrong-kind ref, and invalid authority
   are pure rejections;
5. all 33 in-memory transaction fault instances recover to exact pre-state or
   committed post-state;
6. consumed Attempt budget never permits resend; exact late readback is the only
   UNKNOWN/UNVERIFIABLE→OBSERVED path;
7. cooperative fixtures can close execution with LIMITATION but never emit
   `StrictFinalizationAcknowledged` or assurance STRICT;
8. encoder vectors and forbidden dependency scan pass; and
9. no result is described as Host conformance, effectiveness, migration,
   SQLite, artifact, or release evidence.

## Phase gates

### Authorized alpha-slice blocking set

`K-001-a`, `K-002-a..b`, `K-003-op01..op11`, `K-004-a`, `K-005-b,d`,
all `AUTH-001..006`, all `ENC-001`, all `REJ-001`, all 33 `S-001`,
`S-005-a`, `XFX-001`, `XFX-002`, all `XFX-005..007`, `R-001-a`,
`R-003-a`, `F-001-a`, all `F-003`, the dependency scan, and the corrected
vertical snapshot/digest.

The implementation report must distinguish the instances actually executed.
Passing this set means only bounded pure-kernel alpha-slice conformance.

### Authorized local phase gates

- full alpha: all remaining alpha instances;
- alpha.2: all Host/artifact instances including `H-011`; any real integration
  remains disposable, isolated, non-research, and claim-limited;
- P5.1-before-P6: all `UX-001`, `UX-010..016`, `CAP-INTAKE`, `CAP-ENTRY`,
  and `CAP-ARCHITECTURE` instances, including minimal-profile isolation with
  optional policy and v3 compatibility modules unavailable;
- beta: all migration/policy/liveness/cost instances, same-scenario v3 baseline,
  all remaining `UX-001..008`, `UX-010..016`, `CAP-MODES`, `CAP-ROLES`,
  `CAP-HUMAN`, `CAP-REPAIR`, `CAP-AUDIT`, `CAP-PRIVACY`, and `CAP-ARTIFACT`,
  and thresholds frozen before observing v4 performance;
- rc: full fault matrix, isolated install/rollback, exact-candidate real App
  evidence, independent review, `UX-009`, `CAP-OPERABILITY`,
  `CAP-DISTRIBUTION`, `CAP-DOCS`, and `CAP-RELEASE`, real new-user usability
  canary, fixed candidate SHA, and preserved failures/UNKNOWN;
- stable/public release: always requires separate author approval and is not
  implied by an RC-ready result.

32 KiB Pack and at least 50% control-interaction reduction are candidate beta
targets, not alpha correctness gates.

Before either target becomes blocking, the measurement receipt freezes the
same user scenario, v3.3.8 SHA, measurement-code digest, and counting boundary.
It reports user start actions and mandatory authorization confirmations
separately from internal control interactions. Only then may Pack ≤32 KiB and
internal control-interaction reduction ≥50% become beta/RC thresholds. No v4
result may be read before that freeze, and no LOC/module/command ceiling is
invented as a substitute.

The P5.1/default-path anti-bloat receipt reports exact HEAD and document/code
digests, loaded modules and dependency edges, manifest command/event/error
counts, user start actions, confirmation count, Host interactions, protocol
calls, local writes, entry/Pack bytes, latency, UNKNOWN count, and human
intervention. PASS additionally requires a cycle-free import graph, Kernel
forbidden-dependency scan, single-writer scan, and the optional-policy/v3-compat
unavailable minimal profile. This receipt is build evidence only, never a
runtime authority.

The P5.1 frozen synthetic observation is: 13 loaded v4 modules, 17 internal
dependency edges, 16/33/40 manifest command/event/error literals, one public
start action, one separately counted authorization confirmation, zero Host
interactions, one protocol mutation, one canonical commit, five PREPARE files,
one CONFIRM file, five startup events, one Attempt, 11,125 entry bytes, and a
627-byte human Controller Plan view. `UNKNOWN=0` on the no-Host-call default
sample; the isolation case separately forces exact UNKNOWN with no resend.
Latency is a nonblocking single-sample diagnostic until the P7 measurement
fixture and v3 baseline are frozen. Any later default-path increase must cite a
registry capability and an already accepted ADR decision.

## Implementation-readiness checklist

| Requirement | Frozen design evidence |
| --- | --- |
| A1 orthogonal state | separate Delivery, Attempt, Result, Report, Artifact, Review, Finalization, execution, assurance; coexistence matrix; final snapshot retains every chain ref |
| A2 machine authority | ActorRef/AuthorityGrantRef, closed machine envelope, per-field ownership, injection/forgery/expiry/cross-loop/scope instances |
| A3 effect executor | commit-before-call contract, AttemptRef/budget/executor ownership, all crash windows, no resend, exact late readback |
| A4 liveness/assurance | TERMINAL disposition is independent from assurance; cooperative limited closure is legal; strict claim still requires authoritative readback |
| A5 CAS unit | per-loop revision is sole write CAS; subject revisions are guards; no store version in snapshot |
| A6 executable corpus | acceptance and subject state separated; 101 families expand to 343 instances; 15 preservation mapping families bind 317 unique exact case IDs without duplicating fake snapshots; bounds/rejection/authority/encoder/UX/preservation windows explicit |
| A7 vertical trace | 11 operations, 18 events, full subject bindings, loop/aggregate revisions, 2715 bytes, exact domain digest |

There is no unresolved semantic decision that blocks the bounded pure-kernel
slice. Any implementation need for an unlisted command, hidden state, second
writer, provider call, filesystem capture, or relaxed authority is a design
failure and must stop implementation.

## ADR consistency map

| ADR commitment | Corpus instances/gate |
| --- | --- |
| machine-only control authority | `AUTH-001..006`, `K-005`, `REJ-001` |
| one per-loop CAS unit | `K-002`, `S-005`, vertical revisions |
| local exactly-once acceptance | `K-003`, `K-004`, `S-002`, `S-003` |
| crash-deterministic atomic store | all `S-001`, `S-004..006` |
| external Attempt and no resend | `XFX-001..008` |
| machine-owned startup effect | `H-011`, `UX-001..003`, `UX-005` |
| intake→prepare→confirm→start authorization | `UX-001`, `UX-010..016`, `CAP-INTAKE`, `CAP-ENTRY`; P5.1-before-P6 |
| UNKNOWN/UNVERIFIABLE independent from Result | `XFX-005..008`, `F-003` |
| terminality independent from assurance | `F-001`, `F-003`, `F-004`, cooperative substitution |
| Result/Report/Artifact/Review chain | `R-001..004`, `F-001`, corrected snapshot |
| canonical encoder across languages | `ENC-001-a..j` |
| bounds and fail-closed rejection | `RES-001`, `K-005..008`, `REJ-001` |
| no Host/Git/SQLite/migration dependency | forbidden-import scan and hard side-effect counts |
| one manifest, one writer, independent ports, acyclic graph | `CAP-ARCHITECTURE-ONE-WRITER`, `CAP-ARCHITECTURE-FORBIDDEN-IMPORT`; architecture-fitness validator |
| policy/compat isolation and deletability | `CAP-ARCHITECTURE-MINIMAL-ISOLATION`, `CAP-ARCHITECTURE-NO-LEGACY-BRANCHES`; minimal profile makes both module sets unavailable |
| authorized stop without fabricated cancellation | `P-002`, `P-004` |
| v3 compatibility without shape copy | `M-001..005` and exact provenance mapping |
| one-entry, explicit-confirmation, zero-control-identity UX | `UX-001..003`, `UX-010..016`; blocking P5.1 before P6 |
| non-leaking status and honest uncertainty | `UX-004`, `UX-005`, `UX-007` |
| explicit safe migration UX | `UX-006` |
| frozen UX cost budget and real usability | `UX-008`, `UX-009` |
| complete v3 product-asset preservation | all 14 `CAP-*` families; 24 semantic capability groups; exact registry/error-ownership/closed-set validator |
| resolved author decisions | phase gates and ADR OD table; no open semantic for slice |
| corpus is not governance | immutable cases only; no writer/retry/Supervisor |
