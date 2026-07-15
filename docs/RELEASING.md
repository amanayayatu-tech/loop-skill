# Release process

`VERSION` is the package version source of truth. The root-owned/read-only
Mac mini attestation is the authoritative repository gate. GitHub Actions is a
compatibility mirror only: a green GitHub check is never release acceptance.
Ubuntu `loop-ci` evidence is historical only and must not be reused for a new
candidate.

## Evidence layers

Keep these claims separate:

1. local checks: targeted tests, compile, schema, installer syntax;
2. Mac mini CI: exact-SHA quick, full, generator fuzz 5000, state fuzz 5000,
   all-shipped branch coverage, isolated install/rollback, source/install
   drift, security/risky-artifact and release lanes;
3. primary-Mac App smoke: the same exact SHA, tracked tree and installed
   manifest under one real, identified Codex App build;
4. merge/main attestation, annotated tag and public GitHub Release.

The repository can mitigate and fail closed around app-server behavior. It
does not claim to repair app-server process reaping or metadata delivery.

## Candidate sequence

1. Update `VERSION`, `CHANGELOG.md`, both READMEs and intentionally changed
   examples. Keep the release worktree clean and scan risky artifacts.
2. Run local targeted checks, then one full local gate at the release-candidate
   commit:

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

3. Submit exactly one candidate SHA to the unattended Mac mini runner. Record
   the exact commit, tracked-tree SHA-256, pipeline-config digest, root-owned
   attestation path, attestation/manifest digest, start/end time and verdict.
   Do not submit a newer candidate while any required lane for the current
   identity is active. Do not push the candidate to Ubuntu `loop-ci`.
4. Let every Mac mini lane not requiring an App receipt finish. A release lane
   that remains `BLOCKED` solely because the same-SHA App receipt is absent is
   the expected pre-canary state, not PASS.
5. Install into an isolated macOS `CODEX_HOME`. `scripts/install.sh` atomically
   registers `codex-loop-state`, preserves prior config bytes, rejects a
   conflicting registration, writes an install manifest, and verifies zero
   source/install drift. Validate the resulting manifest with the installed
   `verify_installation.py`.
6. On that exact SHA and installed manifest, run the real Codex App canary. The
   receipt must reach the canary's own canonical `FINALIZATION_ACKED`; synthetic
   MCP tests, a Node REPL observation, source reading, or a tool-list screenshot
   are only prerequisites.
7. Bind the minimized, non-secret App receipt to the same Mac mini attestation
   by its trusted out-of-band mechanism and finalize/re-run only the combined
   release lane for the same SHA. If the runner lacks such an interface,
   report the CI contract gap; do not commit raw local logs, user state or
   secrets to bypass it.
8. Merge only after the exact candidate has Mac mini PASS plus real App PASS.
   Submit the exact merge commit to the Mac mini `main` lane and obtain a new main
   attestation. Only then create an annotated tag on that precise commit and a
   matching GitHub Release.
9. Back up the real `CODEX_HOME`, install the exact release package, validate
   its manifest and registration readback, and re-check source/install drift.
   Pack migration and heartbeat resume are later paused-safe-point operations;
   installation alone never authorizes them.

## Real App receipt identity

The schema is
`codex-loop-prompt-architect/references/app-canary-receipt.schema.json`; validate
it with `validate_app_canary_receipt.py`. A PASS receipt binds:

- exact repo commit, tracked-tree SHA-256, Pack digest and
  installed-manifest digest;
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
  second send, Pack/same-heartbeat reconciliation, and `FINALIZATION_ACKED`;
- Asia/Shanghai start/end times and an exact error classification on failure.

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

Upgrade any pin in a separate reviewable change and rerun the authoritative
quick/full/fuzz/coverage/install/App gates. Floating tags, branches and
unpinned Docker image tags are forbidden in release-required jobs.

## Risky artifact gate

Before commit, merge, tag and installation, reject unscoped validation logs,
`REVIEW_BUNDLE`, `SMOKE_FINDINGS`, `FIX_REPORT`, run environments, API keys,
Authorization values, `*.tar.gz`, `*.bundle`, SQLite/DB files, real
`.codex-loop/**`, generated Controller Packs and user evidence. A clean local
tree or compatibility workflow is not a substitute for the root-owned Mac mini
attestation and same-SHA App receipt.
