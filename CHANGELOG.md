# Changelog

All notable changes to this project are documented here. The project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [3.2.2] - 2026-07-14

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

[Unreleased]: https://github.com/amanayayatu-tech/loop-skill/compare/v3.2.2...HEAD
[3.2.2]: https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.2.2
[3.2.1]: https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.2.1
[3.2.0]: https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.2.0
