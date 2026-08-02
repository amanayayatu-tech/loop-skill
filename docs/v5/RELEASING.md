# Releasing LoopSkill 5

This runbook releases the independent two-file LoopSkill 5 Skill product. It must not change the root `VERSION=4.2.0`, `scripts/install.sh`, the v4 runtime, old tags/Releases, or any v3/v4 installation or data.

## Release identity

- public version: `v5.0.0`;
- tag: annotated `v5.0.0`;
- product payload: `loopskill5/SKILL.md` and `loopskill5/agents/openai.yaml` only;
- installer: the existing system Codex Skill Installer pointed at the exact tagged `loopskill5` path;
- public artifact: reproducible tagged source unless a separately reviewed, privacy-safe asset has an exact SHA-256;
- supported Host: local, single-user Codex Host.

The branch, DEVELOPMENT journeys, a local install, PR, merge, or tag alone is not publication.

## Gate 0: freeze public truth

Start from a clean branch based on current `origin/main`. Confirm:

1. the Skill inventory is exactly two regular files and zero symlinks;
2. the root v4 `VERSION`, installer/runtime, workflow, old tags, and v4 release notes are unchanged; existing v4 checks remain in force, and any shared-validator adjustment only admits the authorized v5 docs/workflow without weakening a v4 assertion;
3. no DEVELOPMENT harness or Phase 2–4 raw run evidence entered the branch;
4. tracked files contain no local home path, LoopSkill scratch path, Codex task/thread/session identity, real credential, private transcript, or private evidence;
5. README, quickstarts, CHANGELOG, SECURITY, this runbook, release notes, and CI describe one consistent two-file identity.

Any truth-changing commit creates a new candidate SHA and supersedes prior exact-SHA validation.

## Gate 1: deterministic and distribution checks

On one exact clean candidate:

- run the v5 surface, distribution, and privacy tests;
- run the existing v4 CI suite without weakening or skipping a job;
- validate `loopskill5` with the current Skill validator;
- use an isolated destination and the actual system Skill Installer with the exact candidate ref;
- prove a second install refuses to overwrite and leaves installed blobs unchanged;
- perform the documented recoverable uninstall and prove only `loopskill5` moved;
- build an isolated environment from public v3/v4 tag/installer bytes, install/uninstall v5, and prove the old installation and data digests are unchanged.

The last item is the IB-14 release regression. A synthetic old directory is not a substitute for public old-tag bytes.

## Gate 2: formal product journeys

Formal journeys require separate authorization bound to the exact clean candidate. DEVELOPMENT evidence remains supporting evidence only.

- GJ-1: natural-language repository delivery, one START, zero technical intervention, real business smoke, and one recoverable verifier/process fault.
- GJ-2: the complete four-package Nepha journey through exact-version fixture approvals, first real HTTP exports, repeated-export identity, restart/new Session readback, final Owner publication Gate, and zero PublicationRecord unless explicitly approved.
- GJ-3: at least 48 continuous hours across two natural days and at least two Host-native same-thread reentries; A is written once, B cites A's exact digest, and no resident Worker/Controller/daemon waits.

IB-08 remains an explicit review item because v5 has no PAUSED/Active user projection; absence of that surface must not be mislabeled as reproduction PASS. IB-13 closes only with the formal 48-hour journey and its exact machine-time evidence.

## Gate 3: privacy, secrets, and independent review

- Run the direct tracked-file privacy/secret scan and review every candidate diff.
- Keep raw private evidence outside the repository and release assets.
- Obtain an independent read-only review of product behavior, two-file distribution, v4 preservation, CI, claim limits, privacy, and reverse-deletion boundaries.
- Stop on an unknown secret, unexplained artifact, identity drift, or any proposed history rewrite.

## Gate 4: PR and required checks

Push only the clean candidate branch and open a PR to `main`. Wait for every existing v4 and new v5 named check to succeed. Red, cancelled, skipped, or missing checks are not evidence.

Only after the names have appeared and passed may the authorized operator configure the minimal `main` ruleset: PR required, the named v4/v5 checks required, no approving review required for the single-user repository, force-push disabled, and branch deletion disabled. Do not bypass the ruleset.

Merge through the PR without rewriting history. Treat the exact merged-main SHA as a new candidate and repeat Gates 1–3 plus all three formal journeys. Even a byte-identical merge does not inherit candidate identity.

## Gate 5: tag and GitHub Release

After an explicit Owner release decision on the exact verified merged-main SHA:

1. create annotated `v5.0.0` on that SHA;
2. push only the tag and wait for all v5 tag CI;
3. peel the remote tag and require the exact merged-main SHA;
4. create GitHub Release `v5.0.0`, latest and non-prerelease, from the reviewed release notes;
5. attach no binary or private evidence unless it has an approved name, size, and SHA-256.

## Gate 6: public readback

Read back remote `main`, the annotated and peeled tag, main/tag CI, latest/non-prerelease Release status, public README/quickstarts/release notes, and the tagged two-file install identity. Confirm v4.2.0 and historical tags/Releases remain unchanged.

Only this readback establishes publication.
