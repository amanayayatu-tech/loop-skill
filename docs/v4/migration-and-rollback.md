# LoopSkill 4 migration and rollback boundary

This document is normative for the local 4.0 RC candidate.

## Installation rollback

- RC acceptance installs only under an explicitly created disposable
  `CODEX_HOME`; it never overwrites the current user installation.
- The installer stages the complete Skill, validates it, backs up prior Skill
  and config bytes outside the scan root, atomically publishes the staged
  directory, registers one exact absolute Python/MCP bridge, and verifies
  source/install byte identity.
- A registration conflict or interrupted process restores the prior Skill and
  config. The P8 uninstaller consumes the exact install receipt and backup;
  drift fails before mutation. It does not edit TOML by heuristic reversal.
- Filesystem power-loss atomicity across both directory and config publication
  is not claimed. The supported claim is bounded process-failure rollback with
  exact pre/post readback on the tested macOS filesystem.

The registered v3 MCP bridge is a one-major-cycle compatibility facade for old
loops. It is not the v4 machine protocol truth, a v4 Kernel dependency, or a
second v4 writer.

## v3 data migration

Only copied public or synthetic fixtures may be used before author approval:

1. dry-run and shadow-read old bytes;
2. require paused, lease-free, outbox-quiescent safe point;
3. present preview and obtain explicit digest-bound confirmation;
4. write a new v4 store/root once;
5. leave the v3 bytes unchanged and readable by the v3 runtime.

Cancel, a non-empty destination, active lease/outbox, dual-write request, or
terminal revival fails closed. Rollback means using the untouched v3 bytes and
runtime; v4 does not reverse-convert its state into the v3 97-field write API.

Compatibility read/shadow/import and the legacy natural-language entry remain
for one major cycle. Their sunset requires separate author approval and usage
evidence. No real v3 loop is implicitly discovered, modified, or migrated.
