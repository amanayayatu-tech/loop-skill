#!/usr/bin/env python3
"""Static fail-closed contract for the sole v4 GitHub Actions workflow."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


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
    "scripts/check_v4_ci.py",
    "test_v4*.py",
    "coverage report --fail-under=80",
    "tests.test_v4_rc_distribution",
    "scripts/validate_v4_rc.py",
    "scripts/check_release_identity.py",
    "--hosted-unit-only",
)


class CiError(ValueError):
    pass


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
    if "real Codex App canary is an exact-SHA local release gate" not in text:
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
