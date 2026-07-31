# Releasing LoopSkill 4

This is the v4-only release runbook. It cannot rewrite or delete any v3 tag,
GitHub Release, or Git history; it cannot migrate real v3 data or overwrite a
user installation. A release operator must stop on secret/private-evidence
exposure, unresolved deterministic gates, or identity drift.

## Release identity

- version file: `VERSION` = `4.1.0`;
- release tag: annotated `v4.1.0`;
- public repository: `amanayayatu-tech/loop-skill`;
- default branch: `main`;
- historical fallback: [v3.3.8](https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8);
- supported Host: Codex only;
- release artifact: reproducible tagged source unless a reviewed asset is
  explicitly listed with SHA-256.

No evidence from a different commit may be used as exact-SHA evidence. A merge
or squash creates a new candidate identity and requires the corresponding
release-identity checks and real foreground Codex exec canary on the merged SHA.

## Before Gate 1: freeze candidate truth

Development, RC validation, both real canaries, and review must keep candidate
wording. Gate 1 starts from that exact clean candidate. Only after separate
author release authorization may an operator make one deliberate release-truth
commit that changes exactly these six candidate/support surfaces together:

1. `README.md`: candidate notice to the approved Chinese stable notice;
2. `README.en.md`: candidate notice to the approved English stable notice;
3. `docs/v4/quickstart.zh-CN.md`: candidate notice to the matching Chinese
   stable notice;
4. `docs/v4/quickstart.en.md`: candidate notice to the matching English stable
   notice;
5. `SECURITY.md`: future support wording to “LoopSkill 4.1.0 is the currently
   supported public line.”;
6. `CHANGELOG.md`: the final `4.1.0` release date and release-link identity.

`VERSION` is already `4.1.0` and remains a separately validated version truth;
it is not a seventh candidate-to-stable text switch. Before that authorized
commit, English copy must say “awaiting author release authorization” and must
not claim public support. The truth switch creates a new candidate SHA, so all
RC-ready receipts from its predecessor are superseded: Gate 1 and every later
exact-SHA gate must run again before publication. If any of the six surfaces
changes afterward, create another candidate SHA and repeat the full exact-SHA
chain; do not transplant predecessor evidence.

## Gate 1: candidate structure and deterministic checks

Run focused checks while changing code. On the final clean candidate, create one
disposable validation environment, run exactly one complete v4 suite under
branch coverage, and keep every raw log outside the repository. Candidate mode
is used for RC readiness; release mode is reserved for the separately authorized
truth-switch SHA:

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
"$PY" scripts/check_v4_docs.py --candidate --smoke
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

## Gate 2: exact-SHA local foreground Codex exec canary

After freezing the candidate SHA, run exactly two new non-scored, non-research,
disposable routes through the public source-tree entry from that exact clean
commit: a fresh 2-Goal route, then only after it passes, a fresh 8-Goal
route. Together they authorize at most 10 Host invocations and two hours.
Install, uninstall, config-integrity, and independent-v3 sentinel checks use a
new isolated `CODEX_HOME`. The authenticated model turns use
the operator's already-authenticated official Codex Host context without
copying, linking, or rewriting credentials. Its config and auth files are only
hashed before and after the turn; the canary never inspects the operator's real
v3 installation or data. The evidence root must not already exist. The command
stops for the exact interactive phrase
`START THIS LOOP` once for each route before constructing its first provider.
Each Goal uses one fresh one-invocation Provider. The release invocations use
the candidate's own `loopskill4 canary` entry and bind its live module path,
commit tree, and clean-worktree state before any Host effect. The separately
required distribution gate still proves the isolated installed entry.

The exact candidate must first prove that preflight requires the official
`--output-schema` and `--output-last-message` flags. The private schema and
result paths are identity/digest-bound, outside the artifact workspace, and
cleaned. JSONL is lifecycle-only; the result file is the sole semantic source.
Bounded stderr is diagnostic and cannot alone veto success, while overflow
fails closed. The private provider diagnostic retains byte counts/digests,
the safe terminal classification, and the schema-valid bounded semantic
outcome/summary needed to explain a non-PASS result. Public evidence binds only
the diagnostic digest and exposes no raw Host transcript, result text, path, or
identity.

```bash
set -euo pipefail
umask 077
CANARY_CODEX_HOME="$RELEASE_TMP/canary-codex-home"
CANARY_ROOT_2="$RELEASE_TMP/exec-canary-2-goal"
CANARY_ROOT_8="$RELEASE_TMP/exec-canary-8-goal"
CANDIDATE_ROOT="$(pwd -P)"
HOST_CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
HOST_CONFIG="$HOST_CODEX_HOME/config.toml"
HOST_AUTH="$HOST_CODEX_HOME/auth.json"
mkdir -p "$CANARY_CODEX_HOME/skills/codex-loop-prompt-architect"
printf '%s\n' '# isolated LoopSkill 4 canary config' >"$CANARY_CODEX_HOME/config.toml"
printf '%s\n' 'synthetic-v3-sentinel' >"$CANARY_CODEX_HOME/skills/codex-loop-prompt-architect/PRESERVE"
test ! -e "$CANARY_ROOT_2"
test ! -e "$CANARY_ROOT_8"

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
CODEX_HOME="$HOST_CODEX_HOME" codex login status 2>&1 | grep -F 'Logged in' >/dev/null
export CODEX_HOME="$CANARY_CODEX_HOME"
LOOP_RELEASE_COMMIT="$CANDIDATE" PYTHON="$PY" bash scripts/install.sh \
  >"$RELEASE_TMP/canary-install.log"
CANARY_ENTRY="$CANDIDATE_ROOT/codex-loop-prompt-architect/scripts/loopskill4"
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
  --candidate-root "$CANDIDATE_ROOT" \
  --goals 2 \
  --evidence-root "$CANARY_ROOT_2"

CODEX_HOME="$HOST_CODEX_HOME" "$CANARY_ENTRY" canary \
  --candidate "$CANDIDATE" \
  --candidate-root "$CANDIDATE_ROOT" \
  --goals 8 \
  --evidence-root "$CANARY_ROOT_8"

UNINSTALL_FIRST="$("$PY" "$CANARY_UNINSTALL" --codex-home "$CANARY_CODEX_HOME")"
grep -F '"status":"UNINSTALLED"' <<<"$UNINSTALL_FIRST" >/dev/null
UNINSTALL_REPLAY="$("$PY" "$CANARY_UNINSTALL" --codex-home "$CANARY_CODEX_HOME")"
grep -F '"status":"ALREADY_UNINSTALLED"' <<<"$UNINSTALL_REPLAY" >/dev/null
trap - EXIT

test ! -e "$CANARY_CODEX_HOME/skills/loopskill4"
CONFIG_AFTER="$(snapshot_path "$CANARY_CODEX_HOME/config.toml")"
V3_AFTER="$(snapshot_path "$CANARY_CODEX_HOME/skills/codex-loop-prompt-architect")"
HOST_CONFIG_AFTER="$(snapshot_path "$HOST_CONFIG")"
HOST_AUTH_AFTER="$(snapshot_path "$HOST_AUTH")"
test "$CONFIG_BEFORE" = "$CONFIG_AFTER"
test "$V3_BEFORE" = "$V3_AFTER"
test "$HOST_AUTH_BEFORE" = "$HOST_AUTH_AFTER"
! grep -Eq '^[[:space:]]*\[mcp_servers\.' "$CANARY_CODEX_HOME/config.toml"
"$PY" - "$CANDIDATE" "$CONFIG_BEFORE" "$CONFIG_AFTER" \
  "$V3_BEFORE" "$V3_AFTER" "$HOST_CONFIG_BEFORE" "$HOST_CONFIG_AFTER" \
  "$HOST_AUTH_BEFORE" "$HOST_AUTH_AFTER" \
  "$CANARY_ROOT_2/canary-receipt.json" \
  "$CANARY_ROOT_8/canary-receipt.json" \
  "$EVIDENCE/canary-environment-integrity.json" <<'PY'
from pathlib import Path
import hashlib
import json
import sys

candidate = sys.argv[1]
values = sys.argv[2:10]
receipt_paths = (Path(sys.argv[10]), Path(sys.argv[11]))
output = sys.argv[12]
labels = ("isolated_config", "v3_sentinel", "host_config", "host_auth")
pairs = {
    label: {"before": values[index * 2], "after": values[index * 2 + 1]}
    for index, label in enumerate(labels)
}
receipts = [json.loads(path.read_text(encoding="utf-8")) for path in receipt_paths]
for receipt, expected in zip(receipts, (2, 8)):
    if (
        receipt.get("candidate_sha") != candidate
        or receipt.get("status") != "PASS"
        or receipt.get("host_task_create_count") != expected
        or receipt.get("host_task_readback_count") != expected
        or receipt.get("host_terminal_wait_readback_count") != expected
        or receipt.get("provider_resend_count") != 0
        or receipt.get("unexpected_changed_input_count") != 0
        or receipt.get("observed_host_auth_changed_bytes") != 0
    ):
        raise SystemExit("canary route receipt invalid")
host_config_changed = pairs["host_config"]["before"] != pairs["host_config"]["after"]
unexpected_changed_input_count = sum(
    pairs[label]["before"] != pairs[label]["after"]
    for label in ("isolated_config", "v3_sentinel", "host_auth")
)
allowed_total = sum(item["allowed_host_managed_delta_count"] for item in receipts)
observed_total = sum(item["observed_host_config_changed_bytes"] for item in receipts)
host_delta_matches = (
    all(item["host_config_delta_kind"] in {"NONE", "CODEX_WORKSPACE_TRUST_APPEND_V1"} for item in receipts)
    and host_config_changed == (observed_total > 0)
    and allowed_total == sum(item["host_config_delta_kind"] == "CODEX_WORKSPACE_TRUST_APPEND_V1" for item in receipts)
)
unexpected_changed_input_count += int(not host_delta_matches)
if unexpected_changed_input_count:
    raise SystemExit("canary environment integrity changed")
body = {
    "artifact": "loopskill-v4-canary-environment-integrity-v1",
    "allowed_host_managed_delta_count": allowed_total,
    "candidate_sha": candidate,
    "host_config_delta_kind": "PER_ROUTE_VALIDATED",
    "measurements": pairs,
    "observed_host_config_changed_bytes": observed_total,
    "route_goal_counts": [2, 8],
    "route_receipt_sha256": [hashlib.sha256(path.read_bytes()).hexdigest() for path in receipt_paths],
    "status": "PASS",
    "unexpected_changed_input_count": unexpected_changed_input_count,
}
body["measurement_digest"] = hashlib.sha256(
    b"loopskill.v4.canary-environment-integrity.v1\0"
    + json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()
Path(output).write_text(
    json.dumps(body, sort_keys=True, separators=(",", ":")),
    encoding="utf-8",
)
PY
```

It must show:

1. intake with 0 loop/task/heartbeat/external effects;
2. prepare with 0 Host effects and digest-bound human views;
3. explicit confirmation of the unchanged boundary;
4. exactly 2 then 8 machine-owned, cwd-bound foreground `codex exec --json`
   invocations, one fresh Provider per Goal;
5. directly captured terminal JSONL for every Goal without hand-copied control
   identity;
6. minimal artifact, review, report, and finalization evidence;
7. no LoopSkill MCP, no LoopSkill-required App restart, no provider resend,
   and no access to real v3 installs, user repositories, private experiments,
   or personal data.

The install readback must be `READY`; the first uninstall must be `UNINSTALLED`
and the identical public command must then return `ALREADY_UNINSTALLED`.
The installed entry persists domain-separated before/after Host config/auth
measurements inside the private canary evidence root and derives the minimized
public changed-byte/count fields from them. Host auth, isolated `config.toml`,
and the synthetic independent-v3 sentinel must remain byte-identical. Host
config may either remain byte-identical or differ only by one EOF-appended,
LF-terminated `[projects."<exact canonical disposable workspace>"]` stanza
whose sole value is `trust_level = "trusted"`. The validator recomputes the
workspace and stanza digests, prefix equality, exact length, and 0/1 key counts;
all other config changes fail closed. The observed nonzero byte count remains
in the receipt. This is an official Codex Host-owned trust-registry effect, not
an installer write: the installer and uninstaller still never modify Codex
config or register MCP. Authentication material is never copied into the
isolated install home. The
foreground Codex process group must be reaped on success, failure, timeout, or
interruption. A canary or cleanup failure is a HOLD with preserved evidence,
never permission to rerun the provider action. The exact canary process scope
must prove zero descendants after the installed entry exits; a global
process-name search is not sufficient evidence. Its 300-second foreground
terminal stream window is not a task budget. On timeout it must preserve
`UNKNOWN`, make no lifecycle claim, and must not resend or resume.

The Codex Desktop folder-open → `list_projects` → `projectId` → `create_thread`
route has separate historical provisioning receipts, but it is not wired into
the 4.1.0 Provider. The gate validates only the cwd-bound foreground exec
route and makes no Desktop-visible saved project/task claim.

If the outcome is `UNKNOWN`/`UNVERIFIABLE`, retain it honestly. Do not retry the
provider action or reconstruct identity. The minimized receipt contains only
candidate SHA, safe categories, counts, statuses, and digests—never task/thread/
turn IDs, absolute private paths, App transcripts, prompts, secrets, or raw logs.
The final local validator receives the disposable v4 store path and recomputes
the closed Result/Artifact/Review/Finalization bindings and domain-separated
same-process attestation. It must not start another Host process or claim a
post-process readback. A locally constructed receipt JSON alone cannot
substitute for the bound store/artifact evidence. The disposable store and raw
Host identity remain outside the repository and release packet.

After both PASS receipts exist, bind `UX-009-a` to the 2-Goal receipt and
`CAP-RELEASE-CANARY` to the 8-Goal receipt. The RC evidence index separately
binds both routes. This remains profile A: 349 semantic mappings to 74 unique
executed assertion methods, not 349 independent observations.

```bash
set -euo pipefail
"$PY" scripts/run_v4_conformance.py \
  --candidate "$CANDIDATE" \
  --canary-2-receipt "$CANARY_ROOT_2/canary-receipt.json" \
  --canary-8-receipt "$CANARY_ROOT_8/canary-receipt.json" \
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
test -z "$(git tag --list v4.1.0)"
REMOTE_TAG_READBACK="$(git ls-remote --tags origin refs/tags/v4.1.0 'refs/tags/v4.1.0^{}')"
test -z "$REMOTE_TAG_READBACK"
set +e
GH_RELEASE_READBACK="$(gh api --include repos/amanayayatu-tech/loop-skill/releases/tags/v4.1.0 2>&1)"
GH_RELEASE_STATUS=$?
set -e
if [[ "$GH_RELEASE_STATUS" -eq 0 ]]; then
  echo "v4.1.0 GitHub Release already exists" >&2
  exit 1
fi
if ! grep -Eq '^HTTP/[^ ]+ 404 ' <<<"$GH_RELEASE_READBACK"; then
  echo "GitHub Release absence could not be authoritatively read" >&2
  exit 1
fi
```

Also read GitHub state and confirm no existing v4.1.0 Release. If `origin/main`
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
  --evidence "exec_canary_2_goal=$CANARY_ROOT_2/canary-receipt.json" \
  --evidence "exec_canary_8_goal=$CANARY_ROOT_8/canary-receipt.json" \
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
  --canary-2-receipt "$CANARY_ROOT_2/canary-receipt.json" \
  --canary-2-store "$CANARY_ROOT_2/store" \
  --canary-8-receipt "$CANARY_ROOT_8/canary-receipt.json" \
  --canary-8-store "$CANARY_ROOT_8/store" \
  --conformance-receipt "$EVIDENCE/final-conformance.json" \
  --author-packet "$EVIDENCE/author-packet.json" \
  --evidence "exec_canary_2_goal=$CANARY_ROOT_2/canary-receipt.json" \
  --evidence "exec_canary_8_goal=$CANARY_ROOT_8/canary-receipt.json" \
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
   suite, Gate 2 installed-entry exec canary, Gate 3 review, and Gate 4 identity
   checks; regenerate all nine receipts, the author packet, and final validation
   for that merged SHA even when its tree is byte-identical. If the tree differs,
   include every affected code gate in that rerun rather than inheriting feature-
   branch evidence.
6. Confirm every v4 main CI job is green and all version/docs/release-note
   surfaces say 4.1.0 consistently.

## Gate 6: tag and GitHub Release

Create annotated `v4.1.0` on the verified merged-main SHA and push only that
tag. Wait for all v4 tag CI jobs to pass. Then create public GitHub Release
4.1.0 from the exact tag, mark it latest and non-prerelease, and use
`docs/v4/release-notes-v4.1.md` after final truth review.

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
