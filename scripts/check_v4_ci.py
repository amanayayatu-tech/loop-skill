#!/usr/bin/env python3
"""Static fail-closed contract for the sole v4 GitHub Actions workflow."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - dependency gate reports this explicitly
    yaml = None


CHECKOUT = "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
SETUP = "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"
UPLOAD = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
REQUIRED_JOBS = (
    "protocol-architecture-docs",
    "unit",
    "coverage",
    "distribution",
    "release-hygiene",
)
REQUIRED_COMMANDS = (
    "scripts/generate_v4_protocol.py --check",
    "scripts/validate_v4_preservation.py --root . --json",
    "scripts/check_v4_docs.py",
    "scripts/check_v4_docs.py --smoke",
    "scripts/check_v4_ci.py",
    "test_v4*.py",
    "coverage report --fail-under=80",
    "tests.test_v4_rc_distribution",
    "scripts/validate_v4_rc.py",
    "scripts/check_release_identity.py",
    "--main-ref refs/remotes/origin/main",
    "--hosted-unit-only",
)


class CiError(ValueError):
    pass


def _workflow_structure(text: str) -> dict[str, object]:
    if yaml is None:
        raise CiError("CI_YAML_PARSER_UNAVAILABLE")
    try:
        value = yaml.load(text, Loader=yaml.BaseLoader)
    except yaml.YAMLError as exc:
        raise CiError("CI_WORKFLOW_YAML_INVALID") from exc
    if not isinstance(value, dict):
        raise CiError("CI_WORKFLOW_STRUCTURE_INVALID")
    return value


def _job_steps(jobs: dict[str, object], name: str) -> list[dict[str, object]]:
    job = jobs.get(name)
    if not isinstance(job, dict) or not isinstance(job.get("steps"), list):
        raise CiError(f"CI_JOB_STRUCTURE_INVALID:{name}")
    steps = job["steps"]
    if not all(isinstance(step, dict) for step in steps):
        raise CiError(f"CI_STEP_STRUCTURE_INVALID:{name}")
    return steps


def _runs(steps: list[dict[str, object]]) -> str:
    return "\n".join(
        str(step["run"]) for step in steps if isinstance(step.get("run"), str)
    )


def validate(root: Path) -> dict[str, object]:
    root = root.resolve()
    workflow_root = root / ".github/workflows"
    workflows = sorted(path.name for path in workflow_root.glob("*.y*ml"))
    if workflows != ["v4-release.yml"]:
        raise CiError(f"CI_WORKFLOW_SET_INVALID:{','.join(workflows)}")
    legacy_ci = root / ".github/ci"
    if legacy_ci.exists() and any(path.is_file() for path in legacy_ci.rglob("*")):
        raise CiError("CI_LEGACY_PLANNER_PRESENT")
    text = (workflow_root / "v4-release.yml").read_text(encoding="utf-8")
    workflow = _workflow_structure(text)
    triggers = workflow.get("on")
    permissions = workflow.get("permissions")
    jobs = workflow.get("jobs")
    if not isinstance(triggers, dict) or not {
        "pull_request",
        "push",
        "workflow_dispatch",
    } <= set(triggers):
        raise CiError("CI_TRIGGER_STRUCTURE_INVALID")
    push = triggers.get("push")
    if (
        not isinstance(push, dict)
        or push.get("branches") != ["main"]
        or push.get("tags") != ["v4.0.0"]
    ):
        raise CiError("CI_PUSH_SCOPE_INVALID")
    if permissions != {"contents": "read"}:
        raise CiError("CI_PERMISSIONS_INVALID")
    if not isinstance(jobs, dict) or set(jobs) != set(REQUIRED_JOBS):
        raise CiError("CI_JOB_SET_INVALID")

    structured_steps = {name: _job_steps(jobs, name) for name in REQUIRED_JOBS}
    unit = jobs["unit"]
    distribution = jobs["distribution"]
    assert isinstance(unit, dict) and isinstance(distribution, dict)
    unit_matrix = unit.get("strategy", {}).get("matrix") if isinstance(unit.get("strategy"), dict) else None
    distribution_matrix = (
        distribution.get("strategy", {}).get("matrix")
        if isinstance(distribution.get("strategy"), dict)
        else None
    )
    expected_python = ["3.11", "3.12", "3.13", "3.14"]
    if not isinstance(unit_matrix, dict) or unit_matrix.get("python") != expected_python:
        raise CiError("CI_UNIT_PYTHON_MATRIX_INVALID")
    if (
        not isinstance(distribution_matrix, dict)
        or distribution_matrix.get("os") != ["ubuntu-latest", "macos-latest"]
        or distribution_matrix.get("python") != expected_python
    ):
        raise CiError("CI_DISTRIBUTION_MATRIX_INVALID")

    required_by_job = {
        "protocol-architecture-docs": (
            "scripts/generate_v4_protocol.py --check",
            "scripts/check_v4_docs.py --smoke",
            "scripts/check_v4_ci.py",
            "--hosted-unit-only",
        ),
        "unit": ("unittest discover", "test_v4*.py"),
        "coverage": ("coverage run", "coverage report --fail-under=80"),
        "distribution": ("bash -n scripts/install.sh", "tests.test_v4_rc_distribution"),
        "release-hygiene": (
            "scripts/validate_v4_rc.py",
            "scripts/check_v4_docs.py --release",
            "scripts/check_release_identity.py",
        ),
    }
    for job, commands in required_by_job.items():
        run_text = _runs(structured_steps[job])
        for command in commands:
            if command not in run_text:
                raise CiError(f"CI_COMMAND_WRONG_JOB:{job}:{command}")
    tag_condition = "github.ref == 'refs/tags/v4.0.0'"
    release_steps = structured_steps["release-hygiene"]
    for needle in ("scripts/check_v4_docs.py --release", "scripts/check_release_identity.py"):
        matches = [step for step in release_steps if needle in str(step.get("run", ""))]
        if len(matches) != 1 or matches[0].get("if") != tag_condition:
            raise CiError(f"CI_TAG_CONDITION_INVALID:{needle}")

    for name, steps in structured_steps.items():
        for step in steps:
            uses = step.get("uses")
            if uses is None:
                continue
            if not isinstance(uses, str) or not re.fullmatch(
                r"actions/[A-Za-z0-9_.-]+@[0-9a-f]{40}", uses
            ):
                raise CiError(f"CI_ACTION_NOT_FULL_SHA_PINNED:{name}")
            if uses.startswith("actions/checkout@"):
                options = step.get("with")
                if not isinstance(options, dict) or options.get("persist-credentials") != "false":
                    raise CiError(f"CI_CHECKOUT_CREDENTIALS_INVALID:{name}")
                if name in {
                    "protocol-architecture-docs",
                    "unit",
                    "coverage",
                    "release-hygiene",
                } and options.get("fetch-depth") not in {0, "0"}:
                    raise CiError(f"CI_PROVENANCE_HISTORY_UNAVAILABLE:{name}")
    for literal in (
        "name: LoopSkill 4 Release CI",
        "pull_request:",
        "branches: [main]",
        "tags: [v4.0.0]",
        "workflow_dispatch:",
        "permissions:\n  contents: read",
        CHECKOUT,
        SETUP,
        UPLOAD,
        'python: ["3.11", "3.12", "3.13", "3.14"]',
        "os: [ubuntu-latest, macos-latest]",
        "persist-credentials: false",
        "TESTED_SHA:",
    ):
        if literal not in text:
            raise CiError(f"CI_REQUIRED_LITERAL_MISSING:{literal}")
    for job in REQUIRED_JOBS:
        if not re.search(rf"^  {re.escape(job)}:$", text, re.MULTILINE):
            raise CiError(f"CI_REQUIRED_JOB_MISSING:{job}")
    for command in REQUIRED_COMMANDS:
        if command not in text:
            raise CiError(f"CI_REQUIRED_COMMAND_MISSING:{command}")
    if re.search(r"uses:\s*[^\s]+@(v\d+|main|master)\b", text):
        raise CiError("CI_ACTION_NOT_FULL_SHA_PINNED")
    for forbidden in (
        "Compatibility CI",
        "Compatibility Shadow Replay",
        "shadow-replay",
        "schedule:",
        "contents: write",
        "pull-requests: write",
        "persist-credentials: true",
        "gh release",
        "git push",
        "codex-loop-state",
    ):
        if forbidden in text:
            raise CiError(f"CI_FORBIDDEN_SURFACE:{forbidden}")
    if "real foreground Codex exec canary is an exact-SHA local release gate" not in text:
        raise CiError("CI_LOCAL_CANARY_BOUNDARY_MISSING")
    return {
        "action_pin_count": len(re.findall(r"uses: actions/[^@\s]+@[0-9a-f]{40}", text)),
        "job_count": len(REQUIRED_JOBS),
        "status": "PASS",
        "workflow": "v4-release.yml",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = validate(args.root)
    except (OSError, UnicodeDecodeError, CiError) as exc:
        print(f"V4_CI_FAIL:{exc}", file=sys.stderr)
        return 1
    print("V4_CI_PASS " + " ".join(f"{key}={value}" for key, value in sorted(result.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
