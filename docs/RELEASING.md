# Release process

`VERSION` is the package version source of truth. The current main Mac is the
only release authority. GitHub Actions is a
compatibility mirror only: a green GitHub check is never release acceptance.
Historical Linux-server, Mac-mini, remote-CI, and remote-attestation results are
superseded context and must not be reused for a new candidate.

## Evidence layers

Keep these claims separate:

1. local main-Mac pre-canary gate: exact-SHA targeted and full tests, all-shipped
   branch coverage, both 5000-case fuzz lanes, isolated install/rollback,
   source/install drift and security/risky-artifact checks;
2. local main-Mac App smoke: the same exact SHA, tracked tree and installed
   manifest under one real, identified Codex App build;
3. local release gate, exact merge/main re-verification, annotated tag and
   public GitHub Release;
4. final local installation with source/install zero drift, followed separately
   by any explicitly authorized real-Loop migration.

The repository can mitigate and fail closed around app-server behavior. It
does not claim to repair app-server process reaping or metadata delivery.

## Candidate sequence

1. Update `VERSION`, `CHANGELOG.md`, both READMEs and intentionally changed
   examples. Keep the release worktree clean and scan risky artifacts.
2. Run targeted checks on the current main Mac, then one complete local gate
   at the release-candidate commit:

   ```bash
   python3 -m pip install -r requirements-test.txt
   python3 -W error -m compileall -q codex-loop-prompt-architect/scripts scripts tests
   python3 codex-loop-prompt-architect/scripts/validate_skill.py
   bash -n scripts/install.sh
   python3 -W error -m unittest discover -s tests -v
   ADAPTIVE_FUZZ_CASES=5000 python3 -W error -m unittest \
     tests.test_adaptive_fuzz.AdaptiveMalformedInputFuzzTests.test_malformed_nested_values_never_crash_validation_or_render -v
   ADAPTIVE_STATE_FUZZ_CASES=5000 python3 -W error -m unittest \
     tests.test_adaptive_state_runtime.AdaptiveStateRuntimeTests.test_malformed_and_random_sequences_never_mutate_or_corrupt -v
   coverage run -m unittest discover -s tests
   coverage report
   ```

3. Record the complete-gate result as a minimized structured local receipt with
   `evidence_layer=local-main-mac`. It binds the exact commit and tracked-tree
   digest and must not claim independent-host, remote, or cross-host proof.
4. Install into an isolated macOS `CODEX_HOME`. `scripts/install.sh` atomically
   registers `codex-loop-state`, preserves prior config bytes, rejects a
   conflicting registration, writes an install manifest, and verifies zero
   source/install drift. Validate the resulting manifest with the installed
   `verify_installation.py`.
5. On that exact SHA and installed manifest, run the real Codex App canary. The
   receipt must reach the canary's own canonical `FINALIZATION_ACKED`; synthetic
   MCP tests, a Node REPL observation, source reading, or a tool-list screenshot
   are only prerequisites. The canary must record
   `native_goal_generation_recovery_status=DEFERRED_UNAVAILABLE` and prove the
   legacy CLI and MCP recovery surfaces reject before side effects. It must not
   create or retry a disposable or real native Goal.
6. Bind the local complete-gate result and minimized non-secret same-SHA App receipt in
   the local release receipt for the same SHA. PASS requires
   `release_eligible == true`, `reasons == []`, exact commit/tree/
   installed-manifest identities, real App PASS, and disposable canonical
   `FINALIZATION_ACKED`; a standalone `verdict=PASS` is insufficient.
7. Merge only after that exact candidate passes the local release gate. Rerun
   the complete local gate and real App compatibility check as required on the
   exact merge commit. Only then create an annotated tag on that precise commit
   and a matching GitHub Release.
8. Back up the real `CODEX_HOME`, install the exact release package, validate
   its manifest and registration readback, and re-check source/install drift.
   Pack migration and heartbeat resume are later paused-safe-point operations;
   installation alone never authorizes them.

## Real App receipt identity

The schema is
`codex-loop-prompt-architect/references/app-canary-receipt.schema.json`; validate
it with `validate_app_canary_receipt.py`. A PASS receipt binds:

- exact repo commit, tracked-tree SHA-256, Pack digest and
  installed-manifest digest;
- `evidence_layer=local-main-mac` and the complete targeted/full/branch-
  coverage/double-5000-fuzz/install-rollback/security/zero-drift pre-canary gate;
- Codex/ChatGPT App version, build and bundle identifier;
- app-server executable path, verified signature, Identifier, TeamIdentifier
  and non-secret CDHash;
- MCP protocol version, config schema, observed outer requestMeta keys and
  turn-metadata key set;
- semantic results for session/thread/turn relationships without storing raw
  ids or user content;
- installed server name, absolute Python, installed script path/SHA, config
  readback, zero drift, and whether an App refresh or restart occurred;
- first route, same-turn pre-side-effect rejection, next-turn success, partial
  frame cleanup, control-plane responsiveness, lost-stdout recovery without a
  second send, Pack/same-heartbeat reconciliation, explicit
  `DEFERRED_UNAVAILABLE` native Goal generation recovery status with zero-effect
  CLI/MCP rejection, and `FINALIZATION_ACKED` through a supported non-recovery
  fixture;
- Asia/Shanghai start/end times and an exact error classification on failure.

Native Goal generation recovery is outside this release scope. Preserve the
existing upstream blocker receipt as historical BLOCKED evidence; do not rerun
its A/B/C/D canary, create another Goal, or reinterpret the blocker as PASS.
Release proof covers only the supported non-recovery surface and the explicit
zero-effect unavailable contract.

App version/build, bundle id, executable/signature/CDHash, MCP protocol/config
schema, requestMeta shape, or registration identity changes invalidate the old
compatibility digest. The release gate passes the currently observed
compatibility digest, exact Pack digest, repo commit, tracked-tree SHA-256 and
install-manifest digest as validator expectations; a self-consistent old
receipt is insufficient. The next release must obtain a new real receipt. Receipts
must not contain prompts, raw responses, Authorization, API keys, raw
session/thread/turn ids, secrets or canonical user content.

## CI compatibility workflow security

The GitHub workflow checks every introduced commit, not only `HEAD`. Pull
requests use merge-base through head; pushes use `before..after`; force pushes,
zero-before, missing shallow baselines, tags and manual dispatch have explicit
full-history fallbacks. Every checked range/commit is logged, while refs and
object ids are shape-validated and passed as argv.

All Actions are immutable full-SHA pins. Current identities were verified from
the official repositories/tags on 2026-07-15:

- [`actions/checkout` v7.0.0](https://github.com/actions/checkout/releases/tag/v7.0.0):
  `9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0`;
- [`actions/setup-python` v6.3.0](https://github.com/actions/setup-python/releases/tag/v6.3.0):
  `ece7cb06caefa5fff74198d8649806c4678c61a1`;
- [`actions/upload-artifact` v7.0.1](https://github.com/actions/upload-artifact/releases/tag/v7.0.1):
  `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`;
- [`actions/download-artifact` v8.0.1](https://github.com/actions/download-artifact/releases/tag/v8.0.1):
  `3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c`.

Upgrade any pin in a separate reviewable change and rerun the local authoritative
quick/full/fuzz/coverage/install/App gates. Floating tags, branches and
unpinned Docker image tags are forbidden in release-required jobs.

## Risky artifact gate

Before commit, merge, tag and installation, reject unscoped validation logs,
`REVIEW_BUNDLE`, `SMOKE_FINDINGS`, `FIX_REPORT`, run environments, API keys,
Authorization values, `*.tar.gz`, `*.bundle`, SQLite/DB files, real
`.codex-loop/**`, generated Controller Packs and user evidence. A clean local
tree or compatibility workflow is not a substitute for the complete local
main-Mac gate and same-SHA real App receipt.
