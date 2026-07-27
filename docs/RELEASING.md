# Releasing LoopSkill 4

This is the v4-only release runbook. It cannot rewrite or delete any v3 tag,
GitHub Release, or Git history; it cannot migrate real v3 data or overwrite a
user installation. A release operator must stop on secret/private-evidence
exposure, unresolved deterministic gates, or identity drift.

## Release identity

- version file: `VERSION` = `4.0.0`;
- release tag: annotated `v4.0.0`;
- public repository: `amanayayatu-tech/loop-skill`;
- default branch: `main`;
- historical fallback: [v3.3.8](https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8);
- supported Host: Codex only;
- release artifact: reproducible tagged source unless a reviewed asset is
  explicitly listed with SHA-256.

No evidence from a different commit may be used as exact-SHA evidence. A merge
or squash creates a new candidate identity and requires the corresponding
release-identity checks and real App canary on the merged SHA.

## Gate 1: candidate structure and deterministic checks

Run focused checks while changing code. On the final clean candidate, run one
complete local suite and record only privacy-minimized summaries:

```bash
python3 scripts/generate_v4_protocol.py --check
python3 scripts/validate_v4_preservation.py --root . --json
python3 scripts/check_v4_docs.py
PYTHONDONTWRITEBYTECODE=1 python3 -B -W error -m unittest discover -s tests -p 'test_v4*.py' -v
coverage run -m unittest discover -s tests -p 'test_v4*.py'
coverage report
```

The release validator must additionally pass:

- one typed protocol authority and generated drift;
- acyclic dependency graph, Kernel import ban, one Store writer, and removable
  optional-policy isolation;
- all frozen corpus instances and all declared fault windows;
- stale production scan for v3 importer/runtime/MCP/config mutation/Pack/
  State-Writer/Supervisor/current-version claims;
- Linux and macOS isolated install/uninstall, exact config hash, conflict and
  rollback windows;
- README zh/en parity, command smoke, links, version, changelog, and release
  identity;
- secret, private-path, raw Host ID/transcript, large-artifact, dependency,
  license, and SBOM checks;
- frozen anti-bloat thresholds and default-path structure/cost receipt.

Historical docs or synthetic fixtures containing retired terms must be exact
allowlisted, non-installed, and non-importable by production. Old raw P8 logs
are predecessor evidence, not release artifacts.

## Gate 2: exact-SHA local Codex App canary

After freezing the candidate SHA, run one new non-scored, non-research,
disposable canary. It must use the public `loopskill4` entry and show:

1. intake with 0 loop/task/heartbeat/external effects;
2. prepare with 0 Host effects and digest-bound human views;
3. explicit confirmation of the unchanged boundary;
4. one machine-owned start and at most one created App task;
5. authoritative readback without hand-copied control identity;
6. minimal artifact, review, report, and finalization evidence;
7. no LoopSkill MCP, no LoopSkill-required App restart, no provider resend,
   and no access to real v3 installs, user repositories, private experiments,
   or personal data.

If the outcome is `UNKNOWN`/`UNVERIFIABLE`, retain it honestly. Do not retry the
provider action or reconstruct identity. The minimized receipt contains only
candidate SHA, safe categories, counts, statuses, and digests—never task/thread/
turn IDs, absolute private paths, App transcripts, prompts, secrets, or raw logs.
The final local validator also receives the disposable v4 store path and must
perform one fresh authoritative readback itself; a locally constructed receipt
JSON cannot substitute for that live gate. Only the domain-separated minimized
attestation is retained. The disposable store and its raw Host identity remain
outside the repository and release packet.

## Gate 3: independent review

Bind a read-only review to the exact candidate SHA and document digests. Review
architecture, UX, installer/uninstaller, CI, privacy, artifact boundaries,
version/release identity, preservation-by-redesign, and README truthfulness.
The reviewer cannot change product files. Findings are resolved on a new SHA;
affected gates are rerun.

## Gate 4: pre-publication readback

Immediately before the first external Git write:

```bash
git fetch origin --tags
git status --short
git rev-parse HEAD
git rev-parse origin/main
git merge-base --is-ancestor origin/main HEAD
git tag --list v4.0.0
```

Also read GitHub state and confirm no existing v4.0.0 Release. If `origin/main`
drifted, integrate it non-destructively and rerun all affected release gates.
Verify the intended diff, branch ancestry, secrets/private paths, large files,
and predecessor evidence exclusion. Never force-push.

## Gate 5: pull request and main

1. Push the candidate feature branch.
2. Open a pull request describing the v4-only break, exact validations,
   README/CI changes, and v3.3.8 fallback.
3. Wait for every required v4 PR job to pass. Red, cancelled, or skipped
   required jobs are not evidence.
4. Merge through the pull request without force or history rewriting.
5. Fetch the exact merged `main` SHA. Run release identity and the exact-SHA App
   canary again on that commit. If the tree differs, rerun all affected gates.
6. Confirm every v4 main CI job is green and all version/docs/release-note
   surfaces say 4.0.0 consistently.

## Gate 6: tag and GitHub Release

Create annotated `v4.0.0` on the verified merged-main SHA and push only that
tag. Wait for all v4 tag CI jobs to pass. Then create public GitHub Release
4.0.0 from the exact tag, mark it latest and non-prerelease, and use
`docs/v4/release-notes.md` after final truth review.

Release notes must prominently state:

- v4-only hard break and no v3 import/automatic migration;
- no MCP registration or App restart required by LoopSkill 4 itself;
- direct v3.3.8 fallback link;
- preserved four-phase UX and safety properties;
- no cross-system exactly-once, multi-host, patch-success, or long-horizon
  superiority claim.

Do not invent a binary asset. Attach only reproducible, reviewed,
privacy-safe files with recorded SHA-256.

## Gate 7: public readback

Verify through Git and GitHub:

- Release URL is public, latest, and non-prerelease;
- annotated tag object peels to the verified merged-main commit;
- tag CI and the corresponding main CI are green;
- attached asset names, sizes, and SHA-256 match the reviewed manifest;
- default branch remains `main`;
- v3.3.8 and paper-treatment-v3.3.12 tags/releases are unchanged.

Only this readback closes publication. Local tests, an RC packet, a pushed
branch, merged main, or a tag alone is not a public-release claim.
