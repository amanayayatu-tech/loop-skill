# Changelog

All notable changes to this project are documented here. The project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/amanayayatu-tech/loop-skill/compare/v3.2.0...HEAD
[3.2.0]: https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.2.0
