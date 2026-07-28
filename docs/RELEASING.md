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

## Before Gate 1: freeze release truth once

Development and review commits must keep candidate wording. Immediately before
Gate 1, make one deliberate release-truth commit that changes exactly these six
candidate/support surfaces together:

1. `README.md`: candidate notice to the approved Chinese stable notice;
2. `README.en.md`: candidate notice to the approved English stable notice;
3. `docs/v4/quickstart.zh-CN.md`: candidate notice to the matching Chinese
   stable notice;
4. `docs/v4/quickstart.en.md`: candidate notice to the matching English stable
   notice;
5. `SECURITY.md`: future support wording to “LoopSkill 4.0.0 is the currently
   supported public line.”;
6. `CHANGELOG.md`: the final `4.0.0` release date and release-link identity.

`VERSION` is already `4.0.0` and remains a separately validated version truth;
it is not a seventh candidate-to-stable text switch. Before that one commit,
English candidate copy must say “undergoing release validation” and must not
claim a gate result before evidence exists. After the commit, set its new `HEAD`
as `CANDIDATE`. All receipts from the predecessor SHA are superseded: Gate 1 and
every later exact-SHA gate start again from this new clean commit. If any of the
six surfaces changes afterward, create a new candidate SHA and repeat the full
exact-SHA chain; do not transplant predecessor evidence.

## Gate 1: candidate structure and deterministic checks

Run focused checks while changing code. Gate 1 begins only after the six-surface
release-truth transition above. On that final clean candidate, create one
disposable validation environment, run exactly one complete v4 suite under
branch coverage, and keep every raw log outside the repository:

```bash
set -euo pipefail
RELEASE_TMP="$(mktemp -d)"
python3 -m venv "$RELEASE_TMP/venv"
PY="$RELEASE_TMP/venv/bin/python"
"$PY" -m pip install --disable-pip-version-check -r requirements-test.txt
EVIDENCE="$RELEASE_TMP/evidence"
mkdir -p "$EVIDENCE"
CANDIDATE="$(git rev-parse HEAD)"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
export COVERAGE_FILE="$RELEASE_TMP/.coverage"
export PYTHONDONTWRITEBYTECODE=1

"$PY" scripts/generate_v4_protocol.py --check
"$PY" scripts/validate_spec.py --root .
"$PY" scripts/validate_v4_preservation.py --root . --json
"$PY" scripts/check_v4_docs.py --release --smoke
"$PY" scripts/check_v4_ci.py
"$PY" codex-loop-prompt-architect/scripts/validate_skill.py codex-loop-prompt-architect
"$PY" -m coverage erase
"$PY" -B -W error -m coverage run -m unittest discover -s tests -p 'test_v4*.py' -v 2>&1 | tee "$RELEASE_TMP/full-suite.log"
"$PY" -m coverage report --fail-under=80
"$PY" -m coverage json -o "$RELEASE_TMP/coverage-raw.json"
"$PY" scripts/run_v4_conformance.py --candidate "$CANDIDATE" --hosted-unit-only --output "$EVIDENCE/hosted-conformance.json"
"$PY" scripts/validate_v4_rc.py --candidate "$CANDIDATE" --static-only --output "$EVIDENCE/static-validation.json"
"$PY" -B -W error -m unittest -v tests.test_v4_rc_distribution 2>&1 | tee "$RELEASE_TMP/distribution.log"
```

The full-suite command above is the sole clean full-suite execution. The
focused distribution rerun is the separately required install/uninstall gate,
not a second full suite. Convert the raw coverage/test outputs to the three
small candidate-bound receipts used by the author packet:

```bash
"$PY" - "$CANDIDATE" "$RELEASE_TMP/coverage-raw.json" "$RELEASE_TMP/full-suite.log" "$RELEASE_TMP/distribution.log" "$EVIDENCE" <<'PY'
from pathlib import Path
import hashlib
import json
import re
import sys

sys.path.insert(0, "codex-loop-prompt-architect/scripts")
from loop_architect.v4_alpha.store import FAULT_BOUNDARIES
from loop_architect.v4_alpha.vertical import vertical_commands
from loop_architect.v4_persistence.sqlite_store import DURABLE_FAULT_BOUNDARIES

candidate, coverage_path, suite_path, distribution_path, output_root = sys.argv[1:]
output = Path(output_root)
coverage = json.loads(Path(coverage_path).read_text(encoding="utf-8"))

def write(name, value):
    (output / name).write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

suite = Path(suite_path).read_bytes()
distribution = Path(distribution_path).read_bytes()
suite_match = re.findall(rb"Ran ([0-9]+) tests?", suite)
distribution_match = re.findall(rb"Ran ([0-9]+) tests?", distribution)
if (
    not suite_match
    or not distribution_match
    or b"\nOK\n" not in suite
    or b"\nOK\n" not in distribution
    or b"FAILED" in suite
    or b"FAILED" in distribution
):
    raise SystemExit("release tests did not finish with an exact PASS")
totals = coverage.get("totals")
if (
    not isinstance(totals, dict)
    or totals.get("percent_covered", 0) < 80
    or not isinstance(totals.get("num_branches"), int)
    or not 0 <= totals.get("covered_branches", -1) <= totals["num_branches"]
):
    raise SystemExit("branch coverage receipt is not a PASS")
write("coverage.json", {
    "artifact": "loopskill-v4-coverage-receipt-v1",
    "candidate_sha": candidate,
    "covered_branches": totals["covered_branches"],
    "line_and_branch_percent": totals["percent_covered"],
    "num_branches": totals["num_branches"],
    "status": "PASS",
})
operations = len(vertical_commands())
write("test-fault-matrix.json", {
    "artifact": "loopskill-v4-test-fault-matrix-receipt-v1",
    "candidate_sha": candidate,
    "full_test_count": int(suite_match[-1]),
    "in_memory_boundary_count": len(FAULT_BOUNDARIES),
    "sqlite_boundary_count": len(DURABLE_FAULT_BOUNDARIES),
    "status": "PASS",
    "suite_log_sha256": hashlib.sha256(suite).hexdigest(),
    "vertical_fault_instance_count": len(FAULT_BOUNDARIES) * operations,
    "vertical_operation_count": operations,
})
write("distribution.json", {
    "artifact": "loopskill-v4-distribution-receipt-v1",
    "candidate_sha": candidate,
    "config_bytes_changed": 0,
    "distribution_log_sha256": hashlib.sha256(distribution).hexdigest(),
    "mcp_entries_added": 0,
    "real_v3_loop_migrations": 0,
    "status": "PASS",
    "test_count": int(distribution_match[-1]),
})
PY
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
- all eight release-CI runtime/distribution lanes: Python 3.11, 3.12, 3.13, and
  3.14 crossed with Linux and macOS. One local Python run cannot substitute for
  this 2-by-4 matrix;
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
disposable canary through the receipt-bound public entry installed from that
exact commit. Install, uninstall, config-integrity, and independent-v3 sentinel
checks use a new isolated `CODEX_HOME`. The one authenticated model turn uses
the operator's already-authenticated official Codex Host context without
copying, linking, or rewriting credentials. Its config and auth files are only
hashed before and after the turn; the canary never inspects the operator's real
v3 installation or data. The evidence root must not already exist. The command
stops for the exact interactive phrase
`RUN THIS CANARY` before constructing the provider. In other words, the release
invocation is the installed, receipt-checked `loopskill4 canary`, not the source-
tree entry:

```bash
set -euo pipefail
umask 077
CANARY_CODEX_HOME="$RELEASE_TMP/canary-codex-home"
CANARY_ROOT="$RELEASE_TMP/app-canary"
HOST_CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
HOST_CONFIG="$HOST_CODEX_HOME/config.toml"
HOST_AUTH="$HOST_CODEX_HOME/auth.json"
mkdir -p "$CANARY_CODEX_HOME/skills/codex-loop-prompt-architect"
printf '%s\n' '# isolated LoopSkill 4 canary config' >"$CANARY_CODEX_HOME/config.toml"
printf '%s\n' 'synthetic-v3-sentinel' >"$CANARY_CODEX_HOME/skills/codex-loop-prompt-architect/PRESERVE"
test ! -e "$CANARY_ROOT"

snapshot_path() {
  "$PY" - "$1" <<'PY'
from pathlib import Path
import hashlib
import json
import os
import sys

root = Path(sys.argv[1])
if root.is_symlink():
    value = [[".", "symlink", os.readlink(root)]]
elif root.is_file():
    value = [[".", "file", hashlib.sha256(root.read_bytes()).hexdigest()]]
elif not root.exists():
    value = [[".", "absent"]]
else:
    value = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            value.append([relative, "symlink", os.readlink(path)])
        elif path.is_dir():
            value.append([relative, "directory"])
        elif path.is_file():
            value.append([relative, "file", hashlib.sha256(path.read_bytes()).hexdigest()])
        else:
            raise SystemExit("unsafe snapshot entry")
raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
print(hashlib.sha256(raw).hexdigest())
PY
}

CONFIG_BEFORE="$(snapshot_path "$CANARY_CODEX_HOME/config.toml")"
V3_BEFORE="$(snapshot_path "$CANARY_CODEX_HOME/skills/codex-loop-prompt-architect")"
HOST_CONFIG_BEFORE="$(snapshot_path "$HOST_CONFIG")"
HOST_AUTH_BEFORE="$(snapshot_path "$HOST_AUTH")"
CODEX_HOME="$HOST_CODEX_HOME" codex login status | grep -F 'Logged in' >/dev/null
export CODEX_HOME="$CANARY_CODEX_HOME"
LOOP_RELEASE_COMMIT="$CANDIDATE" PYTHON="$PY" bash scripts/install.sh \
  >"$RELEASE_TMP/canary-install.log"
CANARY_ENTRY="$CANARY_CODEX_HOME/skills/loopskill4/scripts/loopskill4"
CANARY_UNINSTALL="$CANARY_CODEX_HOME/install-receipts/loopskill4/uninstall_v4.py"
INSTALL_READBACK="$("$PY" "$CANARY_UNINSTALL" --codex-home "$CANARY_CODEX_HOME" --check)"
printf '%s\n' "$INSTALL_READBACK" >"$RELEASE_TMP/canary-install-readback.json"
grep -F '"status":"READY"' <<<"$INSTALL_READBACK" >/dev/null

cleanup_canary_install() {
  if [[ -x "$CANARY_UNINSTALL" ]]; then
    "$PY" "$CANARY_UNINSTALL" --codex-home "$CANARY_CODEX_HOME" \
      >>"$RELEASE_TMP/canary-uninstall-cleanup.log"
  fi
}
trap cleanup_canary_install EXIT

CODEX_HOME="$HOST_CODEX_HOME" "$CANARY_ENTRY" canary \
  --candidate "$CANDIDATE" \
  --evidence-root "$CANARY_ROOT"

UNINSTALL_FIRST="$("$PY" "$CANARY_UNINSTALL" --codex-home "$CANARY_CODEX_HOME")"
grep -F '"status":"UNINSTALLED"' <<<"$UNINSTALL_FIRST" >/dev/null
UNINSTALL_REPLAY="$("$PY" "$CANARY_UNINSTALL" --codex-home "$CANARY_CODEX_HOME")"
grep -F '"status":"ALREADY_UNINSTALLED"' <<<"$UNINSTALL_REPLAY" >/dev/null
trap - EXIT

test ! -e "$CANARY_CODEX_HOME/skills/loopskill4"
test "$CONFIG_BEFORE" = "$(snapshot_path "$CANARY_CODEX_HOME/config.toml")"
test "$V3_BEFORE" = "$(snapshot_path "$CANARY_CODEX_HOME/skills/codex-loop-prompt-architect")"
test "$HOST_CONFIG_BEFORE" = "$(snapshot_path "$HOST_CONFIG")"
test "$HOST_AUTH_BEFORE" = "$(snapshot_path "$HOST_AUTH")"
! grep -Eq '^[[:space:]]*\[mcp_servers\.' "$CANARY_CODEX_HOME/config.toml"
```

It must show:

1. intake with 0 loop/task/heartbeat/external effects;
2. prepare with 0 Host effects and digest-bound human views;
3. explicit confirmation of the unchanged boundary;
4. one machine-owned, cwd-bound start and at most one created App task;
5. authoritative readback without hand-copied control identity;
6. minimal artifact, review, report, and finalization evidence;
7. no LoopSkill MCP, no LoopSkill-required App restart, no provider resend,
   and no access to real v3 installs, user repositories, private experiments,
   or personal data.

The install readback must be `READY`; the first uninstall must be `UNINSTALLED`
and the identical public command must then return `ALREADY_UNINSTALLED`.
The isolated `config.toml`, authenticated Host config/auth files, and synthetic
independent-v3 sentinel tree must have identical before/after digests, and no
LoopSkill MCP entry or process may be created. Authentication material is never
copied into the isolated install home. The
temporary Codex `app-server` provider used by the Host Adapter must close in a
`finally` path on success, failure, or timeout. A canary or cleanup failure is a
HOLD with preserved evidence, never permission to rerun the provider action.
The exact canary process scope must also prove zero live provider/app-server
children after the installed entry exits; a global process-name search is not
sufficient evidence. Its 300-second foreground terminal readback is an
observation window, not a task budget. On timeout it must make no claim that the
Host task continues and must not resend.

The Codex Desktop folder-open → `list_projects` → `projectId` → `create_thread`
route has separate 23/23 verified provisioning receipts. App-server 0.144.4,
which backs the v4.0 Provider, exposes no project methods; therefore the 4.0.0
gate validates the cwd-bound route only. Saved-project convenience is deferred
to 4.0.x/4.1 and must not be inferred from the Desktop provisioning evidence.

If the outcome is `UNKNOWN`/`UNVERIFIABLE`, retain it honestly. Do not retry the
provider action or reconstruct identity. The minimized receipt contains only
candidate SHA, safe categories, counts, statuses, and digests—never task/thread/
turn IDs, absolute private paths, App transcripts, prompts, secrets, or raw logs.
The final local validator also receives the disposable v4 store path and must
perform one fresh authoritative readback itself; a locally constructed receipt
JSON cannot substitute for that live gate. Only the domain-separated minimized
attestation is retained. The disposable store and its raw Host identity remain
outside the repository and release packet.

After the PASS receipt exists, bind the two real-App corpus mappings to that
receipt. This remains profile A: 349 semantic mappings to 74 unique executed
assertion methods, not 349 independent observations.

```bash
set -euo pipefail
"$PY" scripts/run_v4_conformance.py \
  --candidate "$CANDIDATE" \
  --canary-receipt "$CANARY_ROOT/canary-receipt.json" \
  --output "$EVIDENCE/final-conformance.json"
```

## Gate 3: independent review

Bind a read-only review to the exact candidate SHA and document digests. Review
architecture, UX, installer/uninstaller, CI, privacy, artifact boundaries,
version/release identity, preservation-by-redesign, and README truthfulness.
The reviewer cannot change product files. Findings are resolved on a new SHA;
affected gates are rerun.

Keep the privacy-reviewed textual report outside the repository. The reviewer,
not the release operator, must emit the following minimized typed receipt after
closing every finding. It contains the report digest and aggregate verdict but
no raw report, identity, path, transcript, or log. Do not synthesize `PASS` from
an arbitrary text file.

```bash
set -euo pipefail
REVIEW_RECEIPT="$EVIDENCE/independent-review.json"
"$PY" - "$CANDIDATE" "$REVIEW_RECEIPT" <<'PY'
import json
import sys
from pathlib import Path

candidate, source = sys.argv[1:]
value = json.loads(Path(source).read_text(encoding="utf-8"))
if set(value) != {
    "artifact", "candidate_sha", "open_finding_count", "report_digest",
    "review_scope_count", "status",
}:
    raise SystemExit("independent review receipt shape invalid")
if (
    value["artifact"] != "loopskill-v4-independent-review-receipt-v1"
    or value["candidate_sha"] != candidate
    or value["open_finding_count"] != 0
    or value["review_scope_count"] != 8
    or value["status"] != "PASS"
    or not isinstance(value["report_digest"], str)
    or len(value["report_digest"]) != 64
    or any(ch not in "0123456789abcdef" for ch in value["report_digest"])
):
    raise SystemExit("independent review did not PASS")
PY
```

## Gate 4: pre-publication readback

Immediately before the first external Git write:

```bash
set -euo pipefail
git fetch origin --tags
test -z "$(git status --porcelain=v1 --untracked-files=all)"
test "$(git rev-parse HEAD)" = "$CANDIDATE"
git rev-parse origin/main >/dev/null
git merge-base --is-ancestor origin/main HEAD
test -z "$(git tag --list v4.0.0)"
REMOTE_TAG_READBACK="$(git ls-remote --tags origin refs/tags/v4.0.0 'refs/tags/v4.0.0^{}')"
test -z "$REMOTE_TAG_READBACK"
set +e
GH_RELEASE_READBACK="$(gh api --include repos/amanayayatu-tech/loop-skill/releases/tags/v4.0.0 2>&1)"
GH_RELEASE_STATUS=$?
set -e
if [[ "$GH_RELEASE_STATUS" -eq 0 ]]; then
  echo "v4.0.0 GitHub Release already exists" >&2
  exit 1
fi
if ! grep -Eq '^HTTP/[^ ]+ 404 ' <<<"$GH_RELEASE_READBACK"; then
  echo "GitHub Release absence could not be authoritatively read" >&2
  exit 1
fi
```

Also read GitHub state and confirm no existing v4.0.0 Release. If `origin/main`
drifted, integrate it non-destructively and rerun all affected release gates.
Verify the intended diff, branch ancestry, secrets/private paths, large files,
and predecessor evidence exclusion. Never force-push.

Freeze that readback and build the closed author packet. Every evidence value
is a SHA-256 of a candidate-bound, privacy-checked JSON receipt; raw logs and
Host identity remain outside the packet.

```bash
set -euo pipefail
ORIGIN_MAIN="$(git rev-parse origin/main)"
V3_BASELINE="$(git rev-parse 'v3.3.8^{commit}')"
PAPER_REFERENCE="$(git rev-parse 'paper-treatment-v3.3.12^{commit}')"
"$PY" - "$CANDIDATE" "$ORIGIN_MAIN" "$V3_BASELINE" "$PAPER_REFERENCE" "$EVIDENCE/release-identity-preflight.json" <<'PY'
from pathlib import Path
import json
import sys

candidate, origin_main, v3, paper, output = sys.argv[1:]
if any(
    len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value)
    for value in (candidate, origin_main, v3, paper)
):
    raise SystemExit("release identity SHA invalid")
receipt = {
    "artifact": "loopskill-v4-release-identity-preflight-v1",
    "candidate_sha": candidate,
    "feature_contains_origin_main": True,
    "origin_main_commit": origin_main,
    "paper_reference_commit": paper,
    "public_release_effects": 0,
    "status": "PASS",
    "v3_baseline_commit": v3,
    "v4_release_exists": False,
    "v4_tag_exists": False,
}
Path(output).write_text(
    json.dumps(receipt, sort_keys=True, separators=(",", ":")),
    encoding="utf-8",
)
PY

"$PY" scripts/build_v4_author_packet.py \
  --root . --candidate "$CANDIDATE" \
  --evidence "app_canary=$CANARY_ROOT/canary-receipt.json" \
  --evidence "coverage=$EVIDENCE/coverage.json" \
  --evidence "distribution=$EVIDENCE/distribution.json" \
  --evidence "final_conformance=$EVIDENCE/final-conformance.json" \
  --evidence "hosted_conformance=$EVIDENCE/hosted-conformance.json" \
  --evidence "independent_review=$EVIDENCE/independent-review.json" \
  --evidence "release_identity_preflight=$EVIDENCE/release-identity-preflight.json" \
  --evidence "static_validation=$EVIDENCE/static-validation.json" \
  --evidence "test_fault_matrix=$EVIDENCE/test-fault-matrix.json" \
  --output "$EVIDENCE/author-packet.json"

"$PY" scripts/validate_v4_rc.py \
  --candidate "$CANDIDATE" \
  --canary-receipt "$CANARY_ROOT/canary-receipt.json" \
  --canary-store "$CANARY_ROOT/store" \
  --conformance-receipt "$EVIDENCE/final-conformance.json" \
  --author-packet "$EVIDENCE/author-packet.json" \
  --evidence "app_canary=$CANARY_ROOT/canary-receipt.json" \
  --evidence "coverage=$EVIDENCE/coverage.json" \
  --evidence "distribution=$EVIDENCE/distribution.json" \
  --evidence "final_conformance=$EVIDENCE/final-conformance.json" \
  --evidence "hosted_conformance=$EVIDENCE/hosted-conformance.json" \
  --evidence "independent_review=$EVIDENCE/independent-review.json" \
  --evidence "release_identity_preflight=$EVIDENCE/release-identity-preflight.json" \
  --evidence "static_validation=$EVIDENCE/static-validation.json" \
  --evidence "test_fault_matrix=$EVIDENCE/test-fault-matrix.json" \
  --output "$EVIDENCE/final-publication-validation.json"
```

## Gate 5: pull request and main

1. Push the candidate feature branch.
2. Open a pull request describing the v4-only break, exact validations,
   README/CI changes, and v3.3.8 fallback.
3. Wait for every required v4 PR job to pass. Red, cancelled, or skipped
   required jobs are not evidence.
4. Merge through the pull request without force or history rewriting.
5. Fetch the exact merged `main` SHA and treat it as a new candidate identity.
   Because every receipt is candidate-bound, rerun the Gate 1 deterministic
   suite, Gate 2 installed-entry App canary, Gate 3 review, and Gate 4 identity
   checks; regenerate all nine receipts, the author packet, and final validation
   for that merged SHA even when its tree is byte-identical. If the tree differs,
   include every affected code gate in that rerun rather than inheriting feature-
   branch evidence.
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
