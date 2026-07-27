#!/usr/bin/env python3
"""Static exact-SHA gate and privacy-minimized receipt helpers for v4 RC."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_TRACKED_ARTIFACT_BYTES = 5 * 1024 * 1024
SECRET_PATTERNS = (
    ("private_key", re.compile(rb"(?m)^-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----$")),
    ("aws_access_key", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("github_token", re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("openai_token", re.compile(rb"sk-[A-Za-z0-9]{20,}")),
)
REQUIRED_DISTRIBUTIONS = ("jsonschema", "coverage", "PyYAML")


class RcValidationError(ValueError):
    pass


def _run(root: Path, *argv: str) -> bytes:
    try:
        return subprocess.run(
            argv,
            cwd=root,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise RcValidationError(
            "RC_COMMAND_FAILED: " + " ".join(argv) + ": " + exc.stderr.decode("utf-8", "replace").strip()
        ) from exc


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _tree_entries(root: Path, candidate: str) -> list[dict[str, Any]]:
    payload = _run(root, "git", "ls-tree", "-rlz", "--full-tree", candidate)
    result = []
    for row in payload.split(b"\0"):
        if not row:
            continue
        metadata, path_bytes = row.split(b"\t", 1)
        mode, kind, object_id, size = metadata.decode("ascii").split()
        path = path_bytes.decode("utf-8", "strict")
        if kind != "blob":
            continue
        result.append(
            {
                "mode": mode,
                "object": object_id,
                "path": path,
                "size": int(size),
            }
        )
    return result


def _dependency_inventory() -> list[dict[str, str]]:
    rows = []
    for name in REQUIRED_DISTRIBUTIONS:
        try:
            metadata = importlib.metadata.metadata(name)
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise RcValidationError(f"RC_DEPENDENCY_UNAVAILABLE: {name}") from exc
        license_value = metadata.get("License-Expression") or metadata.get("License")
        if not license_value:
            classifiers = metadata.get_all("Classifier") or []
            license_value = ";".join(
                item for item in classifiers if item.startswith("License ::")
            )
        if not license_value:
            raise RcValidationError(f"RC_DEPENDENCY_LICENSE_UNAVAILABLE: {name}")
        rows.append(
            {"distribution": name, "license": license_value, "version": version}
        )
    return sorted(rows, key=lambda item: item["distribution"].lower())


def static_receipt(root: Path, candidate: str, *, require_clean_head: bool = True) -> dict[str, Any]:
    root = root.resolve()
    if not SHA_RE.fullmatch(candidate):
        raise RcValidationError("RC_CANDIDATE_SHA_INVALID")
    resolved = _run(root, "git", "rev-parse", f"{candidate}^{{commit}}").decode("ascii").strip()
    if resolved != candidate:
        raise RcValidationError("RC_CANDIDATE_SHA_MISMATCH")
    if require_clean_head:
        head = _run(root, "git", "rev-parse", "HEAD").decode("ascii").strip()
        status = _run(root, "git", "status", "--porcelain=v1", "--untracked-files=all")
        if head != candidate or status:
            raise RcValidationError("RC_CANDIDATE_WORKTREE_NOT_EXACT_CLEAN_HEAD")
    entries = _tree_entries(root, candidate)
    oversized = [
        {"path_digest": hashlib.sha256(item["path"].encode()).hexdigest(), "size": item["size"]}
        for item in entries
        if item["size"] > MAX_TRACKED_ARTIFACT_BYTES
    ]
    findings = []
    for item in entries:
        payload = _run(root, "git", "show", f"{candidate}:{item['path']}")
        for rule, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(payload):
                findings.append(
                    {
                        "file_digest": hashlib.sha256(item["path"].encode()).hexdigest(),
                        "finding_digest": hashlib.sha256(match.group(0)).hexdigest(),
                        "rule": rule,
                    }
                )
    if findings:
        raise RcValidationError("RC_SECRET_SCAN_FAILED")
    if oversized:
        raise RcValidationError("RC_LARGE_ARTIFACT_SCAN_FAILED")
    license_payload = (root / "LICENSE").read_bytes()
    if b"MIT License" not in license_payload:
        raise RcValidationError("RC_PROJECT_LICENSE_INVALID")
    dependencies = _dependency_inventory()
    protocol = json.loads((root / "protocol/v4/loopskill-v4.protocol.json").read_text(encoding="utf-8"))
    body = {
        "artifact": "loopskill-v4-rc-static-receipt-v1",
        "candidate_sha": candidate,
        "dependency_inventory": dependencies,
        "large_artifact_findings": oversized,
        "max_tracked_artifact_bytes": MAX_TRACKED_ARTIFACT_BYTES,
        "project_license": "MIT",
        "protocol_counts": {
            "capabilities": len(protocol["capability_names"]),
            "commands": len(protocol["commands"]),
            "errors": len(protocol["errors"]),
            "events": len(protocol["events"]),
        },
        "public_effects": 0,
        "python_executable": str(Path(sys.executable).resolve()),
        "secret_findings": findings,
        "tracked_blob_count": len(entries),
        "tracked_tree_digest": hashlib.sha256(_canonical(entries)).hexdigest(),
    }
    body["receipt_digest"] = hashlib.sha256(_canonical(body)).hexdigest()
    return body


def validate_canary_receipt(value: dict[str, Any], candidate: str) -> None:
    expected_keys = {
        "artifact",
        "candidate_sha",
        "confirmation_count",
        "finalization",
        "host_receipt_digest",
        "host_task_create_count",
        "host_task_readback_count",
        "intake_external_effects",
        "machine_owned_identity",
        "manual_control_identity_count",
        "prepare_host_effects",
        "private_data_used",
        "provider_resend_count",
        "research_scored",
        "result",
        "review",
        "status",
        "thread_content_retained",
        "unknown_preserved",
    }
    if set(value) != expected_keys:
        raise RcValidationError("RC_CANARY_RECEIPT_SHAPE_INVALID")
    required = {
        "artifact": "loopskill-v4-disposable-app-canary-v1",
        "candidate_sha": candidate,
        "confirmation_count": 1,
        "finalization": "ACKNOWLEDGED",
        "host_task_create_count": 1,
        "host_task_readback_count": 1,
        "intake_external_effects": 0,
        "machine_owned_identity": True,
        "manual_control_identity_count": 0,
        "prepare_host_effects": 0,
        "private_data_used": False,
        "provider_resend_count": 0,
        "research_scored": False,
        "result": "ACKNOWLEDGED",
        "review": "PASS",
        "status": "PASS",
        "thread_content_retained": False,
        "unknown_preserved": True,
    }
    for key, expected in required.items():
        if value.get(key) != expected:
            raise RcValidationError(f"RC_CANARY_RECEIPT_INVALID: {key}")
    digest = value.get("host_receipt_digest")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise RcValidationError("RC_CANARY_RECEIPT_INVALID: host_receipt_digest")


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--canary-receipt", type=Path)
    parser.add_argument("--allow-non-head", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        receipt = static_receipt(
            args.root, args.candidate, require_clean_head=not args.allow_non_head
        )
        if args.canary_receipt:
            canary = json.loads(args.canary_receipt.read_text(encoding="utf-8"))
            validate_canary_receipt(canary, args.candidate)
            receipt["canary_receipt_digest"] = hashlib.sha256(
                _canonical(canary)
            ).hexdigest()
        if args.output:
            args.output.write_bytes(_canonical(receipt) + b"\n")
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RcValidationError) as exc:
        print(f"RC_VALIDATION_FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
