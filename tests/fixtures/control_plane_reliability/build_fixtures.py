#!/usr/bin/env python3
"""Build deterministic, sanitized fixtures for control-plane regressions."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


BASELINE_COMMIT = "f83e5f0ba590792ac00afb463b8628afaf7ca8c1"
BASELINE_TREE = "499be9b3699c8956f980b111dbec970e9eb0cd2c"
BASELINE_VERSION = "3.2.4"
BASELINE_PACKAGE_MANIFEST_SHA256 = (
    "34834831f4124405df91771049b31edf21e2efda9b7c7046b8a51df3a375f3fc"
)
REMEDIATION_PLAN_SHA256 = (
    "eae91502e3c3634eff45616f01bbce414df6c173ac7a84acd14a73b0d895354e"
)
PACKAGE_ROOT = "codex-loop-prompt-architect"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _git(repo_root: Path, *args: str, text: bool = False) -> bytes | str:
    return subprocess.check_output(
        ["git", "-C", str(repo_root), *args],
        text=text,
    )


def _transport_fixture() -> dict[str, Any]:
    frame = {"incident_id": "transport-8265", "payload": ""}
    empty_size = len(_canonical_bytes(frame))
    frame["payload"] = "x" * (8265 - empty_size)
    payload = _canonical_bytes(frame)
    if len(payload) != 8265:
        raise AssertionError(f"transport fixture is {len(payload)} bytes")
    return {
        "schema_version": 1,
        "fixture_kind": "BOUNDED_STDIN_TRANSPORT",
        "frame_encoding": "utf-8",
        "frame_size_bytes": len(payload),
        "frame_sha256": _sha256(payload),
        "frame": payload.decode("utf-8"),
        "variants": [
            {"name": "complete-pipe-open", "close_stdin": False, "newline": False},
            {"name": "partial-pipe-open", "bytes_sent": 4132, "close_stdin": False},
            {"name": "pty-no-newline", "close_stdin": False, "newline": False},
        ],
    }


def _attempt_fixture() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "fixture_kind": "ATTEMPT_RECONCILIATION",
        "loop_id": "fixture-loop",
        "goal_id": "fixture-goal",
        "events": [
            {
                "dispatch_id": "initial-product",
                "classification": "PRODUCT_EXECUTION",
                "execution_started": True,
                "counts_as_repair": False,
            },
            {
                "dispatch_id": "freshness-rejection",
                "classification": "CONTROL_PLANE_REJECTION",
                "execution_started": False,
                "blocker_code": "DISPATCH_FRESHNESS_SNAPSHOT_MISMATCH",
                "counts_as_repair": False,
            },
            {
                "dispatch_id": "transport-rejection",
                "classification": "CONTROL_PLANE_REJECTION",
                "execution_started": False,
                "blocker_code": "INPUT_TRANSPORT_TIMEOUT",
                "counts_as_repair": False,
            },
            {
                "dispatch_id": "repair-1",
                "classification": "PRODUCT_EXECUTION",
                "execution_started": True,
                "counts_as_repair": True,
            },
            {
                "dispatch_id": "repair-2",
                "classification": "PRODUCT_EXECUTION",
                "execution_started": True,
                "counts_as_repair": True,
            },
        ],
        "expected": {"product_attempts": 3, "repairs_consumed": 2},
    }


def _review_fixture() -> dict[str, Any]:
    history = [
        {
            "event_id": f"history-{index:02d}",
            "state_version": index,
            "event_type": "SYNTHETIC_HISTORY",
        }
        for index in range(1, 33)
    ]
    return {
        "schema_version": 1,
        "fixture_kind": "REVIEW_CLOSEOUT_RECOVERY",
        "repo_root": "fixture/\u9879\u76ee",
        "pack": {
            "path": ".codex-loop/sources/CONTROLLER_PACK.fixture.md",
            "digest": "sha256:" + "2" * 64,
        },
        "worker": {
            "dispatch_id": "fixture-worker-dispatch",
            "artifact_digest": "sha256:" + "3" * 64,
            "report_digest": "sha256:" + "4" * 64,
        },
        "validation_projection": {
            "artifact_digest": "sha256:" + "1" * 64,
            "classification": "STALE_OLD_ARTIFACT",
        },
        "assurance_outbox": {
            "outbox_id": "fixture-review-outbox",
            "status": "ACKED",
            "lease_id": "fixture-review-lease",
        },
        "freshness": {"classification": "STALE"},
        "external_usage": {"complete": False, "total_tokens": None},
        "history": history,
    }


def _heartbeat_fixture() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "fixture_kind": "PACK_HEARTBEAT_SPLIT",
        "automation_id": "fixture-heartbeat",
        "canonical": {
            "run_control": "PAUSED_AT_SAFE_POINT",
            "pack_path": ".codex-loop/sources/CONTROLLER_PACK.versioned.md",
            "pack_digest": "sha256:" + "5" * 64,
        },
        "automation": {
            "live_status": "PAUSED",
            "prompt_pack_path": ".codex-loop/sources/CONTROLLER_PACK.md",
            "prompt_digest": "sha256:" + "6" * 64,
        },
        "identities": {
            "controller": "fixture-controller",
            "state_writer": "fixture-state-writer",
            "worker": "fixture-worker",
            "reviewer": "fixture-reviewer",
            "local_verifier": "fixture-local-verifier",
        },
        "active_lease": None,
        "route_reserving_outboxes": [],
    }


def _source_baseline(repo_root: Path) -> dict[str, Any]:
    names = str(
        _git(
            repo_root,
            "ls-tree",
            "-r",
            "--name-only",
            BASELINE_COMMIT,
            "--",
            PACKAGE_ROOT,
            text=True,
        )
    ).splitlines()
    files: list[dict[str, Any]] = []
    manifest_lines: list[str] = []
    prefix = f"{PACKAGE_ROOT}/"
    for name in names:
        payload = bytes(_git(repo_root, "show", f"{BASELINE_COMMIT}:{name}"))
        relative = name.removeprefix(prefix)
        digest = _sha256(payload)
        files.append(
            {
                "path": relative,
                "sha256": digest,
                "size_bytes": len(payload),
            }
        )
        manifest_lines.append(f"{digest}  ./{relative}\n")
    aggregate = _sha256("".join(manifest_lines).encode("utf-8"))
    if aggregate != BASELINE_PACKAGE_MANIFEST_SHA256:
        raise AssertionError(
            f"baseline package manifest drift: {aggregate}"
        )
    return {
        "schema_version": 1,
        "fixture_kind": "SOURCE_INSTALL_BASELINE",
        "source_commit": BASELINE_COMMIT,
        "source_tree": BASELINE_TREE,
        "package_version": BASELINE_VERSION,
        "installer_contract_version": 1,
        "package_root": PACKAGE_ROOT,
        "file_count": len(files),
        "manifest_sha256": aggregate,
        "remediation_plan_sha256": REMEDIATION_PLAN_SHA256,
        "files": files,
    }


def build(repo_root: Path) -> dict[str, dict[str, Any]]:
    return {
        "attempt-reconciliation.json": _attempt_fixture(),
        "pack-heartbeat-split.json": _heartbeat_fixture(),
        "review-closeout-recovery.json": _review_fixture(),
        "source-v3.2.4-baseline.json": _source_baseline(repo_root),
        "transport-8265.json": _transport_fixture(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output_dir = Path(__file__).resolve().parent
    repo_root = output_dir.parents[2]
    generated = build(repo_root)
    mismatches: list[str] = []
    for name, value in generated.items():
        target = output_dir / name
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8") + b"\n"
        if args.check:
            if not target.is_file() or target.read_bytes() != payload:
                mismatches.append(name)
        else:
            target.write_bytes(payload)
    if mismatches:
        print("fixture drift: " + ", ".join(mismatches))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
