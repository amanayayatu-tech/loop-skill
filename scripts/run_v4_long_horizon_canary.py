#!/usr/bin/env python3
"""Run the deterministic LoopSkill 4.2 long-horizon release canary."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence


ARTIFACT = "loopskill-v4.2-long-horizon-canary-v1"
TESTS = (
    "tests.test_v4_single_entry_ux.V4SingleEntryUXTests.test_v2_optional_capability_skip_advances_and_finishes_with_limitations",
    "tests.test_v4_single_entry_ux.V4SingleEntryUXTests.test_v2_human_gate_waits_without_host_then_accepts_bound_approval",
    "tests.test_v4_single_entry_ux.V4SingleEntryUXTests.test_v2_failure_wait_policy_pauses_instead_of_terminalizing",
    "tests.test_v4_single_entry_ux.V4SingleEntryUXTests.test_v2_budget_preflight_extends_and_resumes_without_a_blocked_host_call",
    "tests.test_v4_single_entry_ux.V4SingleEntryUXTests.test_v2_repair_stays_in_same_loop_and_can_succeed",
    "tests.test_v4_single_entry_ux.V4SingleEntryUXTests.test_v2_repeated_repair_fingerprint_waits_after_second_attempt",
    "tests.test_v4_single_entry_ux.V4SingleEntryUXTests.test_v2_time_gate_uses_real_clock_and_never_calls_host",
    "tests.test_v4_single_entry_ux.V4SingleEntryUXTests.test_public_cli_discovers_and_requires_selection_for_multiple_loops",
    "tests.test_v4_artifact_capabilities.V4ArtifactCapabilityTests.test_exact_argv_command_verifier_runs_independently",
    "tests.test_v4_artifact_capabilities.V4ArtifactCapabilityTests.test_loopback_http_verifier_starts_checks_and_reaps_service",
    "tests.test_v4_exec_provider.ExecProviderTests.test_persistent_terminal_attempt_survives_provider_restart",
    "tests.test_v4_exec_provider.ExecProviderTests.test_incomplete_persisted_session_uses_one_recorded_resume",
)


class CanaryError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", *args),
        cwd=root,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode:
        raise CanaryError("LONG_CANARY_GIT_READ_FAILED")
    return completed.stdout.strip()


def _validate_candidate(root: Path, candidate: str) -> None:
    if len(candidate) != 40 or any(ch not in "0123456789abcdef" for ch in candidate):
        raise CanaryError("LONG_CANARY_CANDIDATE_INVALID")
    if _git(root, "rev-parse", "HEAD") != candidate:
        raise CanaryError("LONG_CANARY_NOT_EXACT_HEAD")
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise CanaryError("LONG_CANARY_WORKTREE_NOT_CLEAN")


def _write_private(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def run(root: Path, candidate: str, output: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    _validate_candidate(root, candidate)
    env = {
        **os.environ,
        "PYTHONPATH": str(root / "codex-loop-prompt-architect" / "scripts"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(
        (sys.executable, "-B", "-W", "error", "-m", "unittest", "-v", *TESTS),
        cwd=root,
        env=env,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    suite_bytes = completed.stdout + b"\0" + completed.stderr
    if completed.returncode:
        sys.stderr.buffer.write(completed.stdout)
        sys.stderr.buffer.write(completed.stderr)
        raise CanaryError("LONG_CANARY_SCENARIO_FAILED")
    receipt: dict[str, object] = {
        "artifact": ARTIFACT,
        "budget_wait_count": 1,
        "candidate_sha": candidate,
        "command_verifier_count": 1,
        "http_route_count": 4,
        "human_wait_count": 1,
        "multi_loop_selection_count": 1,
        "optional_skip_count": 1,
        "provider_resend_count": 0,
        "same_loop_repair_count": 1,
        "scenario_count": len(TESTS),
        "session_resume_count": 1,
        "status": "PASS",
        "suite_sha256": hashlib.sha256(suite_bytes).hexdigest(),
        "time_wait_count": 1,
    }
    _write_private(output, _canonical(receipt))
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = run(args.root, args.candidate, args.output)
    except (CanaryError, OSError) as exc:
        print(f"LONG_CANARY_FAILED: {exc}", file=sys.stderr)
        return 1
    print(_canonical(receipt).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
