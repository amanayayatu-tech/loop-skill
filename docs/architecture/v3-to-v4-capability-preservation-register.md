# LoopSkill v3.3.8 → v4 capability preservation register

- Status: architecture direction accepted; preservation gate passed at checkpoint `a00f9e6`; P8 exact-candidate review is a separate blocking gate
- Public source: tag `v3.3.8`, commit `843945d9d34e7f065b65d9172ea4a2df66c0f2e3`
- Paper reference: peeled `paper-treatment-v3.3.12` commit `54442e22c3ce483823c911dfa8d03a52c85922e6`; read-only provenance, never the public baseline
- Machine registry: `docs/architecture/v3-to-v4-capability-preservation-register.json`
- Validator: `scripts/validate_v4_preservation.py`

## Purpose and authority

This register is a versioned migration and RC acceptance checklist. It answers
which v3 user value and safety semantics must survive, where each item belongs
in v4, how it is tested, and when compatibility ends. It is not a protocol
manifest, runtime writer, heartbeat, recovery process, policy engine, or second
canonical ledger. The v4 typed protocol manifest remains wire-shape authority;
the reducer owns transitions; Adapter/library contracts own Host and filesystem
facts.

The machine registry is authoritative for enumeration, provenance, disposition,
and conformance linkage. This document is its human decision view. A registry
change requires the same review as the affected ADR/corpus gate, but never
authorizes a runtime action.

## Closed source inventory

The validator reads the exact Git objects at the public commit and refuses
count or digest drift:

| Inventory | Count | Sorted identity SHA-256 |
| --- | ---: | --- |
| Reference files | 10 | `f86371eebd7d3214ea47d24a5f7d352964aee64cde3cb0536753589449387a98` |
| `loop_architect` Python modules | 27 | `b9e69f2fe78d2730a4ec33fbe1e9e4b7e6024b8595b4173c7b39ceca3c402b49` |
| Product test files | 38 | `623c77babe430d8343e8991f4c4cbb27ca106d09569f791488d80c27685f2509` |
| Exact test methods | 771 | `599dd3cff5809f011c43bb08fc6055af57f6b0ed3475b2011c2f2e415e2bf88d` |
| SPEC invariant entries | 19 | `a6d790148577890908543ffe9685ea37d423e4b079be513a93f1309481e95e21` |
| Public `loopctl` commands | 7 | `7a51e3ec8e89638c21d441348352523e82ecbd0a9cdd65bded652c846a6a0200` |
| Recovery error codes | 705 | `1bd044f5e1e62d3c5e43c5f10a704d1c5fddce37e9949d03825dafa0ae701d79` |
| Public schema enum/const symbols | 922 | `1ef81b7610e2936a7e72e7f4ef8e674bcf52737277166727d98987936a3263ef` |
| Public user flows | 18 | `b35373d127958a24c546da9ac447cda034811c9212d24fd13e4b6c34081c3121` |
| Public schemas | 8 | `082d9946ff263b0d5d31234277a243cd34e7f897a8183e911e1182d933b15570` |
| Release/install contracts | 12 | `3c7c4ef5a09a6a14e6fc681a1be2053262ec2bbbe4386e36c83961b41521e79a` |

The 38-test count deliberately excludes the CI compatibility test, fixture
builder, and test-support module; all 771 `test_*` identities inside the 38
product files are enumerated through Python AST. Public schemas include the
input schema, Adaptive mutation/state schemas, canary/install/defect schemas,
recovery registry, and README workflow specification. The validator executes
the exact v3 `human_control.py` and `schema.py` bytes inside an isolated
in-memory module namespace to enumerate dynamic `INPUT_SCHEMA` enum/const
values, then combines them with the five static JSON schemas. It additionally
enumerates every recovery code rather than sampling either surface.

The initial static-schema pass produced 1,640 required identities. Independent
review found the dynamic `INPUT_SCHEMA` omission; the corrected closed set is
1,766. Every one of the 705 legacy recovery codes now has one explicit semantic
capability owner in the JSON registry. That ownership is migration evidence,
not a requirement that v4 reproduce 705 runtime error literals.

## Disposition rules

- `RETAIN_CORE`: a Host-neutral deterministic invariant remains in Kernel.
- `RETAIN_ENTRY`: a user-facing entry/operability/distribution contract remains.
- `RETAIN_LIBRARY`: a reusable codec, artifact, evidence, privacy, audit, or
  measurement capability remains below Core through a port.
- `MOVE_TO_ADAPTER`: Codex/App/provider facts move behind the Codex Host Adapter.
- `MOVE_TO_POLICY`: optional coordination and human-governance behavior moves
  above Core without becoming a writer.
- `COMPAT_ONLY`: one-major-cycle read/facade/import behavior; no v4 canonical
  write compatibility and no dual write.
- `DEPRECATE`: no new v4-loop surface; the replacement and preserved user value
  are explicit.

Every active invariant, public flow, public command, public schema, schema
enum/const, recovery error, and release/install contract must match exactly one
registry coverage rule. Zero matches, two matches, stale placeholder text, an
unknown test identity, or an RC-blocking item without conformance fails the
validator.

## Product capability decisions

| Capability | Level | Disposition | v4 owner | Blocking conformance | User-visible decision |
| --- | --- | --- | --- | --- | --- |
| `PRES-INTAKE` | public stable | `RETAIN_ENTRY` | Intake evaluator | `CAP-INTAKE` | Preserve G1–G10, four outcomes, seven sections, 1–3 deduplicated questions, and zero execution effects. |
| `PRES-ENTRY` | public stable | `RETAIN_ENTRY` | Single-entry UX service | `CAP-ENTRY` | Preserve prepare/confirm/start; one command may orchestrate them but never skip explicit authorization. |
| `PRES-MODES` | public stable | `MOVE_TO_POLICY` | Standard/Adaptive policies | `CAP-MODES` | Direct, fixed Goal Queue, and bounded roadmap routes remain; minimal tasks need no policy selection. |
| `PRES-ROLES` | public stable | `MOVE_TO_POLICY` | Review policy + Host task port | `CAP-ROLES` | Worker, JIT Reviewer, and JIT Local Verifier stay distinct and exact-artifact bound. |
| `PRES-HUMAN` | public stable | `MOVE_TO_POLICY` | Human-control policy | `CAP-HUMAN` | Pause/resume/Decision/review-surface responses bind current context and cannot mint authority. |
| `PRES-REPAIR` | public stable | `MOVE_TO_POLICY` | Bounded repair policy | `CAP-REPAIR` | Preserve attempt history, same-failure detection, exhaustion, wait/decision/stop, and immutable successor history. |
| `PRES-KERNEL` | public stable | `RETAIN_CORE` | Reducer + canonical store port | `CAP-ARCHITECTURE` | Preserve CAS/idempotency/single-writer/fail-closed semantics, not the v3 giant state shape. |
| `PRES-TRANSPORT` | public stable | `RETAIN_LIBRARY` | Codec library | `CAP-ARCHITECTURE` | Keep bounded strict UTF-8 one-frame compatibility; hide framing from ordinary users. |
| `PRES-RECOVERY` | public stable | `RETAIN_LIBRARY` | Attempt/Outbox + generated recovery projection | `CAP-AUDIT` | Keep lost-response recovery and one next action; remove blind resend and independent recovery governance. |
| `PRES-FINALIZATION` | public stable | `RETAIN_CORE` | Orthogonal Kernel aggregates | `CAP-ROLES`, `CAP-RELEASE` | Keep Result/Report/Artifact/Review/Finalization and assurance separate; only acknowledged finalization closes. |
| `PRES-ARTIFACT` | public stable | `RETAIN_LIBRARY` | Artifact libraries | `CAP-ARTIFACT` | Preserve existing-Git/non-Git/new-Git exact capture and path/race safety. |
| `PRES-EVIDENCE` | public stable | `RETAIN_LIBRARY` | Evidence normalization + Kernel bindings | `CAP-ROLES`, `CAP-RELEASE` | Stale artifact/dispatch/report evidence never becomes PASS. |
| `PRES-HOST` | public stable | `MOVE_TO_ADAPTER` | Codex Host Adapter | `CAP-OPERABILITY` | Move all task/thread/heartbeat/App/trust/model/memory/readback facts out of Core; unavailable remains visible. |
| `PRES-OPERABILITY` | public stable | `RETAIN_ENTRY` | Operability commands | `CAP-OPERABILITY` | Preserve doctor/compile/canary with concise default output and diagnostics-only identity. |
| `PRES-AUDIT` | public stable | `RETAIN_LIBRARY` | Read-only projections/archive | `CAP-AUDIT` | Preserve rejection history, audit/status/archive/next action as rebuildable views, never writers. |
| `PRES-PRIVACY` | public stable | `RETAIN_LIBRARY` | Risk scan and privacy export | `CAP-PRIVACY` | Keep category/digest evidence; never export prompt/chat/task/thread/path/PII/secret/raw log. |
| `PRES-METRICS` | public stable | `RETAIN_LIBRARY` | Metrics projection | `CAP-AUDIT` | Keep liveness/cost counters and explicit `UNMETERED`; metrics never authorize routing. |
| `PRES-COMPAT` | public stable | `COMPAT_ONLY` | One-major-cycle facade | `CAP-COMPAT` | Preserve legacy intake/generate/repair, Pack views, and compact/full/minimal_patch behavior without byte promises. |
| `PRES-MIGRATION` | public stable | `COMPAT_ONLY` | Shadow reader/importer | `CAP-DISTRIBUTION` | Explicit safe-point preview/confirm/cancel/import only; original v3 bytes remain unchanged. |
| `PRES-DISTRIBUTION` | public stable | `RETAIN_ENTRY` | Isolated install/uninstall/rollback | `CAP-DISTRIBUTION` | Preserve conflict fail-closed, absolute runtime, single registration, byte-exact rollback; add isolated uninstall. |
| `PRES-DOCS` | public stable | `RETAIN_ENTRY` | Docs/examples | `CAP-DOCS` | Preserve Chinese/English quickstarts and Standard/Adaptive examples with the four-phase v4 entry. |
| `PRES-RELEASE` | public stable | `RETAIN_ENTRY` | RC validator/author packet | `CAP-RELEASE` | Exact candidate SHA and real disposable App receipt remain mandatory; CI/synthetic history is not release authority. |
| `PRES-DEPRECATIONS` | public stable | `DEPRECATE` | Dependency/compatibility validator | `CAP-ARCHITECTURE` | No new State-Writer, native Goal recovery, Supervisor, 97-field write, model authority, Pack truth, dual write, or blind retry. |
| `PRES-PUBLIC-SCHEMA-COMPAT` | public stable | `COMPAT_ONLY` | Read-only v3 decoder | `CAP-DISTRIBUTION` | Inventory and decode v3 closed schemas for shadow/preview only; never write them canonically from v4. |

The machine registry contains, for every row, exact source anchors and test
method identities, v4 API/schema owner, migration and rollback behavior,
acceptance evidence, exact atomic case IDs, and unique coverage expressions.
Each acceptance claim binds one or more exact corpus case IDs. The register does
not fabricate a second snapshot/event fixture: executable case files use the
corpus record format, typed-manifest literals, and actual canonical snapshots;
non-canonical Entry/library/static cases carry null snapshot fields plus exact
owner-specific output and side-effect counts.
The 15 preservation mapping families bind 317 unique case identities. Every
family separately identifies a normal, reject, boundary/drift, and zero-product-
effect case; one case may satisfy two labels only when its exact counts justify
both (for example, a rejected static import scan has no runtime effect).

## Anti-bloat and dependency gate

Entry is the composition root; Kernel depends only on generated typed protocol
and ports. Transactional Store, Artifact libraries, and one Codex Adapter
separately implement ports. Store does not call Host, and neither Artifact nor
Adapter writes canonical state. One canonical store may contain orthogonal
aggregates/event streams without a giant enum or single physical stream.

The 24 capability groups compress old public value into owners and
compatibility/deprecation boundaries. They are not 24 required runtime
services, and the 1,766 source identities are not branches. The validator holds
if a preservation mapping would copy a legacy error/schema/runtime mechanism
instead of retaining its user value or safety invariant.

`CAP-ARCHITECTURE` blocks on one manifest authority, one writer, acyclic import
graph, Kernel forbidden-dependency scan, and minimal-profile isolation. In the
minimal profile, optional policy and v3 compatibility imports are unavailable,
yet the default intake→prepare→confirm→start/status/UNKNOWN path must run. After
P5.1, an evidence receipt freezes actual loaded modules/dependency edges,
command/event/error counts, user start actions and confirmation count, Host and
protocol calls, local writes, bytes, latency, UNKNOWN, and human intervention.
No arbitrary LOC ceiling is used.

The P5.1 no-Host synthetic receipt records 13 loaded v4 modules/17 dependency
edges, 16 commands/33 events/40 errors, one start action plus one confirmation,
zero Host interactions, one protocol mutation and canonical commit, 5+1 local
preparation/confirmation writes, 11,125 entry bytes, and a 627-byte human Plan.
These are regression observations, not new size ceilings or beta performance
PASS. P6/P7 may add default-path cost only for a mapped capability and existing
ADR decision; the two candidate beta thresholds remain locked only after the
pre-observation v3 baseline procedure.

P6 binds `PRES-COMPAT` and `PRES-MIGRATION` to
`tests/test_v4_compatibility_import.py`. The compatibility facade consumes the
exact public Standard/Adaptive example inputs but emits a typed v4 PREPARE
bundle plus optional human view; it never loads on the default path. The
stateful importer is deliberately narrower: public v3.3.8 schema-v3, one READY
Goal, paused/lease-free/outbox-empty, copied or synthetic fixtures only. It
uses a disjoint new v4 root, preserves source bytes, rejects terminal revival,
and maps the source to one paused v4 Goal without copying the v3 state shape.
This is fixture conformance, not authorization to migrate real loops.

## Deprecation replacements

| Deprecated v3 mechanism | v4 replacement | Preserved user value |
| --- | --- | --- |
| Session State-Writer and multiple canonical ledgers | Transactional canonical store behind the Kernel port | Durable CAS, events, auditability, crash recovery |
| Native Goal generation recovery | Honest unavailable/UNKNOWN plus same-identity Host readback | No fabricated replacement Goal or duplicate execution |
| Supervisor and third governance layer | Kernel next-command invariant plus optional bounded policy | Liveness diagnosis and bounded repair without a second router |
| 97-field canonical write API | Minimal typed command/event manifest and orthogonal aggregates | Closed validation and deterministic transitions |
| Model/LLM-carried IDs, SHA, receipt, enum, argv | Machine envelope, Adapter receipt, and capability resolution | Zero user control-identity entry and exact routing |
| Markdown Pack as execution truth | Typed manifest; Pack remains review/export/emergency view | Familiar human-readable plan and emergency portability |
| Blind retry and dual canonical write | At-most-one automatic attempt, readback, UNKNOWN, one writer | Crash safety without duplicate external action |

## Compatibility window and sunset

The v3.3.8 public maintenance line remains available and unchanged. For one v4
major cycle, v4 retains behavior-equivalent natural-language intake/generate,
existing-Pack repair, human Pack export, compact/full/minimal_patch views,
public `loopctl` command coverage, v3 read/shadow/preview/import, and old-runtime
rollback readability. This is not a promise that every v3 flag, sentence, Pack
byte, error wording, or 97-field write shape remains identical.

Sunset is allowed only after one full major cycle and requires usage evidence,
a documented replacement for every affected public flow, migration/rollback
evidence, an ADR amendment, conformance removal in a major-version corpus
change, and separate author approval. Stable v3 data readability cannot be
silently sunset with the facade.

## Preservation gate

Before P5.1 implementation resumes and before P6 begins:

1. exact inventory and one-disposition validation pass;
2. every `CAP-*` family has normal, reject, boundary/drift, and zero-effect
   atomic instances;
3. ADR 0011 contains every capability decision and the same sunset boundary;
4. stale/placeholder/duplicate scans pass;
5. an independent read-only Reviewer binds exact HEAD plus register/ADR/corpus
   digests and reports no omitted public capability or unresolved required fix.

Passing this register proves coverage of declared v3 product assets. It does
not prove v4 implementation, Host conformance, product effectiveness, release
readiness, or stable publication.
