# Changelog

All notable changes to this project are documented here. The project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [3.3.2] - 2026-07-19

### Fixed

- Added the schema-v3 `ACK_TRANSPORT_RECOVERY` Gateway operation. After the
  retained outbox has been completed or recovered, the earlier heartbeat pause
  was acknowledged, and the same registered heartbeat has a real ACTIVE App
  update/readback, Gateway atomically clears the transient transport blocker
  and restores `run_control=RUNNING`.
- Recovery cannot create a PASS, dispatch or repair attempt. An unresolved or
  foreign outbox, missing pause receipt, wrong heartbeat identity/status,
  active outbox, stale observation or replay with changed identity rejects with
  zero canonical side effect. The historical fault remains in the event ledger
  and the derived failure count is retained.
- Generated Packs freeze the exact public `active_automation_receipt` field set.
  A rejected ACTIVE ACK derives its fail-safe from post-call canonical state,
  so a still-paused loop re-pauses the same heartbeat while an already-recovered
  loop never does. App canary receipt v6 makes both paths and the no-new-attempt
  guarantee mandatory release evidence.
- Closed the long-run state where a successful v3.3.1 `REPORT_RECOVERY` left
  `WAITING_TRANSPORT_RECOVERY / PAUSED_AT_SAFE_POINT` permanently blocking the
  next Reviewer route even though the original G06 outbox was already safely
  recovered.

## [3.3.1] - 2026-07-18

### Fixed

- Closed the first-Worker-report validation-evidence cycle exposed by the
  life-blueprint G06 long run. A target-owned `STAGE_REPORT` may now capture
  exact UTF-8 validation files from the registered target worktree into
  immutable runtime staging. `ACK_ROUTE_RESULT` or `REPORT_RECOVERY` archives
  those same bytes atomically with the formal report on the original outbox.
- Validation evidence is bound to the report path, digest, media type, current
  dispatch, current artifact and target-role MCP attestation. Missing, foreign,
  stale, symlinked, wrong-digest or unreferenced evidence rejects with no
  canonical side effect; the Controller neither authors nor transports the
  evidence content. Staging is capped at 15 evidence files, size-checked before
  bounded reading, and rejects case-insensitive `.codex-loop/**` aliases.
- Added independent-process Worker-stage to Controller-ACK coverage and crash
  recovery at every immutable evidence-staging write boundary.
- Restored the documented zero-repair policy for schema-v3 loops. A validation
  matrix may initialize with `max_repair_attempts_per_goal=0`; the first failed
  product attempt then exhausts the strategy directly instead of being rejected
  during initialization by the two-sample same-strategy threshold.

- Made schema-v3 target-report attestation durable across independent Codex
  App MCP bridge processes. After an attested Worker, Reviewer, or Local
  Verifier stages exact report bytes, the runtime now writes an immutable,
  identity-bound sidecar derived from the SENT outbox and report digest. A
  Controller Gateway derives and validates that sidecar itself for ACK or
  REPORT_RECOVERY; it never accepts a Controller-supplied attestation.
- Bounded direct `REGISTER_HEARTBEAT` derived identifiers. Legal real App
  automation identifiers can be up to the canonical identifier limit, so both
  the evidence locator and its internal automation-outbox key now use
  deterministic hashes rather than concatenating that identifier with other
  values. The complete identity remains in the report content and is still
  bound by its full digest.
- Declared and enforced a 48-character schema-v3 Gateway route-ID bound before
  state mutation. This is the portable limit for its derived report, staging,
  lease, freshness, and verification identifiers; oversized route IDs reject
  fail-closed with no canonical side effects.
- Mapped Gateway public request IDs to deterministic bounded transaction and
  event locators, so a valid request ID cannot exceed the portable filesystem
  basename limit when persisted as a journal receipt.
- Restored Gateway public-request replay: its separately persisted public
  request digest makes a lost response replay return the original applied
  transaction despite a later canonical state version, while reusing the same
  request ID with changed public parameters still rejects as an ID conflict.

## [3.3.0-candidate] - 2026-07-17

### Added

- Added schema-v3 `state_gateway` as the canonical writer for new Adaptive
  Packs. It initializes fresh roots without a session State-Writer and provides
  atomic `PREPARE_ROUTE`, `RECORD_ROUTE_SENT`, `ACK_ROUTE_RESULT`, original
  outbox `REPORT_RECOVERY`, bootstrap task/heartbeat receipts, static
  `ADVANCE_ROADMAP`, Gateway finalization/ACK without a native Goal, successor
  initialization, and bounded transport observation.
- Added Gateway-derived route payloads: current repository snapshot/freshness,
  validation matrix, review handoff, artifact identity, virtual lease and
  outbox are no longer Controller-copied fields.
- Added runtime-owned `CAPTURE_COMPLETE_DIFF` for raw binary Git diff capture,
  confined untracked paths, reverse-apply verification and a manifest; added
  derived `LOOP_METRICS.json` for route/control-plane timing and counts.

### Fixed

- The installer now recognizes a managed in-place `codex-loop-state` upgrade
  when the existing registration has exactly the same installed bridge and no
  extra execution semantics. It retains the prior absolute Python runtime only
  after a bounded dependency-capability probe plus verifier receipt/write/
  readback, instead of treating an ordinary runtime-path change as an
  external registration conflict; foreign bridges, extra fields and invalid
  prior runtimes still fail closed and restore the previous installation.

- A PASS projection now requires the same Goal's current artifact, current
  Worker dispatch and matching PASS formal report. BLOCKED, stale artifact,
  stale dispatch and foreign reports have no PASS side effect.
- A staged report with lost stdout/task indexing is ACKed on its original
  outbox; recovery cannot create a report-only product dispatch or consume a
  new repair attempt.
- Repeated matching transport failures no longer spin indefinitely: the first
  observation retains the outbox, while two natural heartbeats or fifteen
  minutes move to `WAITING_TRANSPORT_RECOVERY`, require a real App pause plus
  matching PAUSED readback before projecting the business heartbeat PAUSED, and request one
  user notification.
- `PREPARE_FINALIZATION` now remains explicitly nonterminal in schema v3:
  it renders `WAITING_FINALIZATION_ACK`, keeps `terminal_status=null`, and
  locks routing until the pause/readback acknowledgement reaches
  `ACK_FINALIZATION`.
- `RECORD_ROUTE_SENT` now requires the real returned target thread to equal the
  PREPARED outbox; Gateway supplies the exact materialized `payload_digest`
  from that canonical outbox. A wrong target or a present stronger receipt for
  a different payload rejects with zero side effects.
- `PREPARE_ROUTE` now stops at the transport safe point, while the retained
  failed outbox remains eligible only for its recovery/ACK path. Metrics now
  keep Worker, Reviewer, and Local Verifier active windows separate.
- A Worker PASS can consume a runtime-owned digest-addressed binary
  `CAPTURED_GIT_DIFF_V1` capture. Reports contain neither raw patch bytes nor
  a model-chosen `.codex-loop` path.

### Changed

- New generated Adaptive Packs default to `MCP_CANONICAL_WRITER` and contain no
  State-Writer task. Schema v1/v2 and `route_state_mutation` remain
  compatibility-only; `MIGRATE_V2_TO_V3` is explicit, paused and quiescent.
  Schema-v3 runtime rejects legacy canonical mutations with
  `STATE_GATEWAY_REQUIRED`; migration is available only through the Gateway's
  explicit safe-point operation.
- A terminal predecessor is immutable incident evidence. Continuation uses
  `INITIALIZE_SUCCESSOR` in a fresh root and records a predecessor handoff.
- Updated Chinese and English README files, the Adaptive contract, SPEC,
  invariants, ADR 0010 and release guidance for the v3 architecture.
- Replaced the unavailable private App action-receipt hard gate with an explicit
  host-cooperative evidence model. Optional `x-codex-app-action-receipt-v1`
  remains stricter when present; normal task/heartbeat registration, send,
  transport pause and finalization bind real App returns/readback to the
  host-attested turn and canonical route/heartbeat identity instead.

### Release boundary

v3.3.0 is not released until the exact protected-main merge SHA passes the
same-SHA real Codex App Gateway canary, is installed with zero drift, has an
independent P0/P1/P2=0 review, and is then tagged and published as a GitHub
Release. The real canary records host-cooperative task/heartbeat/send/report/
successor/pause observations on that SHA; an optional private App receipt is
not a release precondition. Repository tests and CI remain prerequisite
evidence, not a release claim.

## [3.2.8] - 2026-07-17

### Fixed

- Replaced generated Pack dependence on a long-lived non-PTY process stdin with
  the installed MCP `runtime_codec` tool for dispatch materialization and
  verification, formal-report and external-receipt staging, and failure
  fingerprint normalization. The retained CLI is a compatibility surface, not
  the generated Pack's only legal transport.
- Classified an empty transport before the first frame as
  `INPUT_TRANSPORT_EOF_BEFORE_FRAME`, distinct from malformed JSON and payload
  content errors. A missing codec fails closed as
  `RUNTIME_CODEC_TOOL_UNAVAILABLE` with no side effects.
- Made terminal projections agree on lifecycle, heartbeat, validation, blocked
  Goal, remaining Goal count, and next action. A finalized blocked Loop now
  renders `TERMINAL_BLOCKED`, `PAUSED`,
  `NOT_APPLICABLE_TERMINAL_BLOCKED`, and `NONE_TERMINAL`; `RESUME` clears the
  resolved transient reason while history remains in the event ledger.

### Changed

- Retired the dormant executable native Goal generation recovery implementation,
  observer, and positive recovery suite. Historical schema fields remain
  readable, while every legacy recovery request continues to return
  `NATIVE_GOAL_GENERATION_RECOVERY_UNAVAILABLE` with `side_effects=NONE`.
- Rebased the compatibility shadow-coverage identity to 80.06% after that
  intentional suite and implementation retirement. The independent all-shipped
  branch-coverage release floor remains unchanged at 80%.
- Reframed `INV-INPUT-001` around one bounded, strict-UTF-8, single-frame,
  non-PTY-safe, fail-closed transport contract rather than a host-specific
  promise that a non-PTY stdin pipe stays writable after process launch.

### Release lineage

v3.2.7 was merged into repository `main` through PR #11, but it never received
a Git tag or GitHub Release. Its supported unavailable contract is preserved;
its deferred executable recovery code is superseded and closed by v3.2.8. Git
history is not rewritten and v3.2.7 must not be represented as a formal release.

### Evidence boundary

Repository checks establish the codec, EOF classification, terminal projection,
and unavailable-recovery contracts. Formal release still requires the exact
protected-main merge SHA to pass the real Codex App codec canary before its
annotated tag and GitHub Release are created.

## [3.2.7] - 2026-07-16

### Changed

- Deferred lost native Goal generation recovery because the current Codex App has no create-paused, resume, restore, or rebind interface that permits the recovery transaction to commit before automatic Goal dispatch.
- Removed the recovery procedure from generated Packs and release canaries. Standalone runtime and MCP entrypoints now return `NATIVE_GOAL_GENERATION_RECOVERY_UNAVAILABLE` with zero side effects for every legacy recovery request. Historical state remains readable for audit only.
- Preserved the real App blocker receipt and upstream requirement as BLOCKED evidence. They are not rewritten, deleted, or promoted to release PASS.
- Replaced the ambiguous single MCP protocol-version receipt field with an
  explicit negotiated-version status/value and separately sourced client and
  installed-server observations. `UNAVAILABLE_BY_HOST` keeps the negotiated
  value null and unknown; it is not a verified negotiation and is not, by
  itself, a release blocker when every behavioral and identity gate passes.

### Evidence boundary

Repository tests prove the explicit unavailable contracts and the remaining deterministic control-plane behavior. They do not infer an MCP negotiated version that the host does not expose. Native Goal generation recovery is outside the supported release surface; this package does not claim to repair Codex App Goal persistence.

## [3.2.6] - 2026-07-16

### Fixed

- Bound every generated Adaptive runtime invocation to the dedicated Python
  executable in the exact installed `codex-loop-state` MCP registration. Packs
  now fail closed instead of falling back to an ambient `python3` that may lack
  the shipped runtime dependencies.

## [3.2.5] - 2026-07-15

### Fixed

- Declared and preflighted the PyYAML dependency used by Codex's optional
  system `quick_validate.py`, so a real `CODEX_HOME` install either validates
  successfully or fails before changing the installed skill or MCP config.

- Replaced syntactic transport checks with one bounded semantic reader across
  every shipped stdin mode. Complete frames finish without EOF; partial,
  oversized and invalid UTF-8 input fails closed without a retained process.
- Bound route acquisition to Codex-owned MCP `params._meta`, the real App turn,
  and an OpenAI-signed direct app-server parent. A second route in the same real
  turn is rejected before canonical or external side effects, while a forked
  session may legitimately differ from its thread identity.
- Bound durable external-call receipts to the canonical route, provider,
  request, call order, result semantics, usage and artifact bytes. Lost stdout
  recovers the immutable COMPLETED receipt and never authorizes another send.
- Made runtime-generated bytes, Worker validation projection, review closeout,
  Pack migration and same-heartbeat reconciliation atomic and replay-safe.
  Migration prompt identity now comes from runtime-verified canonical bytes,
  leaves historical ACKED automation identity immutable, and journals the
  exact source routing gate for rollback.

### Changed

- The installer now atomically registers the installed `codex-loop-state` MCP
  server with an absolute Python executable and installed bridge path. It
  preserves prior config bytes, rejects conflicting execution semantics,
  restores config/skill on failure, and emits a schema-validated zero-drift
  install manifest.
- Release enforcement now covers all shipped Python at a branch baseline of at
  least 80%, separates full tests from the two 5000-case fuzz lanes, checks the
  complete reviewed whitespace range, pins every Action to a full commit, and
  verifies exact protected-main tag identity.
- The v3.2.5 process used a Mac mini attestation while Ubuntu CI and GitHub
  Actions were non-authoritative. That historical cross-host policy is
  superseded for v3.2.7 and later. The real Codex App receipt still binds the
  same exact commit, tracked-tree SHA-256, installed manifest and current
  App/MCP/signature identity, ending at canonical `FINALIZATION_ACKED`.

### Evidence boundary

Repository tests and the then-current historical CI record remained separate
from the real macOS App canary. This release validates, mitigates and fails closed around app-server
behavior; it does not claim to fix app-server process-group cleanup upstream.

## [3.2.4] - 2026-07-14

### Fixed

- Added `DISPATCH_VALIDATION_MATRIX_MISMATCH` to both persisted Worker-result
  and mutation-schema blocker enums. v3.2.3 accepted this deterministic
  zero-execution classification in runtime logic but rejected its canonical
  projection during paused-safe-point reconciliation.
- Changed the positive real-incident reconciliation regression to exercise the
  exact validation-matrix blocker, so runtime and both public schemas can no
  longer drift independently without failing the suite.

### Evidence boundary

This schema correction enables the already bounded v3.2.3 reconciliation. It
does not alter repair limits, authorize a provider retry, or turn a failed
Local Verification into PASS.

## [3.2.3] - 2026-07-14

### Fixed

- Worker formal-report staging now binds top-level `execution_started` and
  `blocker_code` into the ACK-ready result. A target that omits those fields
  from the small transport handle can no longer silently default a proven
  control-plane rejection to product execution.
- Added a paused-safe-point reconciliation mutation for already archived
  misclassifications. It re-verifies the exact canonical report path and digest
  and corrects only the existing attempt/latest-worker classification without
  deleting history, clearing repair counters, or changing Controller Pack
  identity.
- Added `DISPATCH_VALIDATION_MATRIX_MISMATCH` to the bounded deterministic
  zero-execution blocker set and regression coverage derived from the real Loop
  failure that exposed the dropped classification.

### Evidence boundary

The reconciliation repairs repository runtime state accounting only. It does
not turn a failed Local Verification into PASS, retry a provider call, or claim
to fix Codex app-server process cleanup.

## [3.2.2] - 2026-07-14

### Changed

- Generated Adaptive Packs now use projection-first canonical observation,
  compact one-in-flight task reads with 30/60/120-second backoff, exact
  validation-identity deduplication, and bounded child-process/session cleanup.
  The validator rejects aggressive fixed polling, raw task-output forwarding,
  shell busy waits, and external retries after stdout loss. This is a
  non-functional control-resource constraint and changes no state schema,
  migration, repair limit, or public completion behavior.
- Clarified that stdin modes need an exposed direct-argv process API with a
  writable non-PTY pipe. An execution tool that closes stdin at launch is
  ineligible; temporary-file redirection is not a compliant substitute.

### Fixed

- Extended the direct non-PTY, bounded-frame transport contract to every
  `adaptive_state_runtime.py` mode and reject pre-runtime stdin helpers,
  `tty:true`, fixed-byte readers, heredocs, and shell pipelines in generated
  Adaptive Packs.
- Added immutable sanitized `STARTED`/`COMPLETED` external-call receipts so a
  completed Local Verification remains recoverable when deferred execution
  loses stdout; a lone `STARTED` receipt conservatively consumes one call and
  forbids an automatic retry.
- Split Worker history from repair consumption. Deterministic control-plane
  closures with `execution_started=false` remain auditable without consuming a
  product repair slot; legacy unclassified attempts retain their old meaning.
- Added atomic `MIGRATE_CONTROLLER_PACK`, immutable Pack revision history, and
  post-initialize Pack-digest attestation. A changed Pack cannot route until
  canonical identity has migrated at a paused safe point. Migration now also
  backfills deterministic legacy turn identities before enabling the new
  one-route-per-App-turn invariant.
- Bound route acquisition and takeover to a real Controller App turn identity;
  the same turn cannot obtain a second route lease after completion or release.
- Preserve explicit scoped-correction identity for reviewed Goals even before
  repair exhaustion, so Roadmap Revision retires rather than falsely completes
  the superseded Goal while retaining its full attempt history.
- Permit a scoped-correction Roadmap Audit to replace an old artifact only when
  the same Worker artifact already has an acknowledged Local `FAIL`/`BLOCKED`
  result; without that exact evidence the normal Local PASS gate still applies.

### Evidence boundary

The new regression fixture is derived from one stopped real-project incident
and covers the repository runtime/Pack protocol. It does not claim to repair
Codex app-server process-group cleanup or prove cross-version App behavior.

## [3.2.1] - 2026-07-14

### Changed

- New Adaptive Packs default to five repair attempts beyond the initial
  execution; explicit values remain bounded to 0–20.
- Payload materialization now has a mandatory direct non-PTY session contract:
  one compact JSON frame, no shell framing pipeline, and exact completion
  checks before a dispatch becomes sendable.
- `STOP_LOOP` now requires an explicit `stop_basis` and separately validates
  general three-observation blockers, deterministic repair exhaustion, and a
  user stop Decision bound to its response Steering.

### Fixed

- Replaced unbounded stdin reads with a 30-second, 4 MB, strict-UTF-8 frame
  reader that completes on a full top-level JSON object without waiting for EOF.
- Prevented repair-exhausted Goals from dispatching again or mechanically
  spending three empty observation turns. Decision-enabled Packs pause on one
  stable stop-or-correction card; Decision-disabled Packs can fail closed on
  the next dedicated Goal turn.
- Scoped corrections now preserve the exhausted Goal definition, attempts, and
  repair counter while requiring a new Goal id through audited Roadmap Revision.

### Evidence boundary

The repository tests and Codex App canary cover this skill's runtime and Pack
protocol. They do not prove that Codex app-server itself now reaps orphaned
process groups; that remains an upstream issue documented separately.

## [3.2.0] - 2026-07-13

First formally versioned public release.

### Added

- Intake Gate with `READY_FOR_LOOP`, `NEEDS_CLARIFICATION`, `BLOCKED`, and
  `DIRECT_TASK_RECOMMENDED` outcomes.
- Adaptive milestone orchestration, deterministic state runtime, closed JSON
  schemas, human steering, convergence controls, and bounded read-only sidecars.
- Transactional installer, deterministic fixtures, semantic regression tests,
  dual fuzz lanes, coverage reporting, and macOS installation smoke checks.
- English quick-start documentation and a chronological evidence index.

### Changed

- CI now provides a fast branch signal while retaining full 5000-case fuzz on
  pull requests and `main`.
- Dense operational rules in `SKILL.md` are expressed as atomic invariants;
  authoritative protocol detail remains in the linked references.
- State-runtime tests are split by responsibility without changing test logic.

### Fixed

- Review-surface confinement now rejects symlink loops and dangling symlink
  components consistently across Python 3.9 and 3.13.

### Evidence boundary

The archived Codex App run proves only the bounded environment described in its
evidence file. It is not production, long-run, cross-version, formal, science,
or public acceptance.

[Unreleased]: https://github.com/amanayayatu-tech/loop-skill/compare/v3.3.2...HEAD
[3.3.2]: https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.2
[3.3.1]: https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.1
[3.3.0]: https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.0
[3.3.0-candidate]: https://github.com/amanayayatu-tech/loop-skill/compare/v3.2.8...HEAD
[3.2.8]: https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.2.8
[3.2.7]: https://github.com/amanayayatu-tech/loop-skill/pull/11
[3.2.6]: https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.2.6
[3.2.5]: https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.2.5
[3.2.4]: https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.2.4
[3.2.3]: https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.2.3
[3.2.2]: https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.2.2
[3.2.1]: https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.2.1
[3.2.0]: https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.2.0
