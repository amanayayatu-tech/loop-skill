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
FORBIDDEN_EVIDENCE_KEYS = {
    "host_id",
    "projectless_root",
    "readback",
    "thread_id",
    "turn_id",
    "worktree",
}
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


def _dependency_inventory() -> list[dict[str, Any]]:
    installed = {
        (distribution.metadata.get("Name") or "").lower(): distribution
        for distribution in importlib.metadata.distributions()
        if distribution.metadata.get("Name")
    }
    for name in REQUIRED_DISTRIBUTIONS:
        try:
            distribution = installed[name.lower()]
        except KeyError as exc:
            raise RcValidationError(f"RC_DEPENDENCY_UNAVAILABLE: {name}") from exc
        if not distribution.version:
            raise RcValidationError(f"RC_DEPENDENCY_VERSION_UNAVAILABLE: {name}")
    rows = []
    for distribution in installed.values():
        metadata = distribution.metadata
        name = metadata["Name"]
        version = distribution.version
        license_value = metadata.get("License-Expression") or metadata.get("License")
        if not license_value:
            classifiers = metadata.get_all("Classifier") or []
            license_value = ";".join(
                item for item in classifiers if item.startswith("License ::")
            )
        if not license_value:
            raise RcValidationError(f"RC_DEPENDENCY_LICENSE_UNAVAILABLE: {name}")
        rows.append(
            {
                "distribution": name,
                "license": license_value,
                "requires": sorted(distribution.requires or []),
                "version": version,
            }
        )
    return sorted(rows, key=lambda item: item["distribution"].lower())


def _evidence_privacy_findings(entries: list[dict[str, Any]], root: Path, candidate: str) -> list[dict[str, str]]:
    findings = []

    def visit(value: Any, file_digest: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in FORBIDDEN_EVIDENCE_KEYS:
                    findings.append({"file_digest": file_digest, "rule": "raw_identity_key"})
                visit(item, file_digest)
        elif isinstance(value, list):
            for item in value:
                visit(item, file_digest)
        elif isinstance(value, str) and value.startswith("/Users/"):
            findings.append({"file_digest": file_digest, "rule": "absolute_user_path"})

    for entry in entries:
        path = entry["path"]
        if not path.startswith("evidence/v4-development/") or not path.endswith(".json"):
            continue
        payload = _run(root, "git", "show", f"{candidate}:{path}")
        try:
            value = json.loads(payload.decode("utf-8", "strict"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            findings.append(
                {"file_digest": hashlib.sha256(path.encode()).hexdigest(), "rule": "invalid_json"}
            )
            continue
        visit(value, hashlib.sha256(path.encode()).hexdigest())
    return findings


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
    evidence_privacy = _evidence_privacy_findings(entries, root, candidate)
    if evidence_privacy:
        raise RcValidationError("RC_EVIDENCE_PRIVACY_SCAN_FAILED")
    license_payload = (root / "LICENSE").read_bytes()
    if b"MIT License" not in license_payload:
        raise RcValidationError("RC_PROJECT_LICENSE_INVALID")
    dependencies = _dependency_inventory()
    protocol = json.loads((root / "protocol/v4/loopskill-v4.protocol.json").read_text(encoding="utf-8"))
    body = {
        "artifact": "loopskill-v4-rc-static-receipt-v1",
        "candidate_sha": candidate,
        "dependency_inventory": dependencies,
        "dependency_inventory_scope": "all distributions installed in the exact bound Python runtime",
        "evidence_privacy_findings": evidence_privacy,
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
        "rc_ready": False,
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


def validate_conformance_receipt(value: dict[str, Any], candidate: str) -> None:
    if (
        value.get("artifact") != "loopskill-v4-conformance-execution-v1"
        or value.get("candidate_sha") != candidate
        or value.get("status") != "PASS"
        or value.get("case_count") != 343
        or value.get("passed") != 343
        or value.get("failed") != 0
        or value.get("real_external_effects") != 1
        or value.get("canonical_case_ids") is not True
    ):
        raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
    results = value.get("case_results")
    if not isinstance(results, list) or len(results) != 343:
        raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
    ids = [item.get("case_id") for item in results if isinstance(item, dict)]
    if len(ids) != 343 or ids != sorted(set(ids)):
        raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
    if any(item.get("status") != "PASS" for item in results):
        raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
    claimed = value.get("case_results_digest")
    if claimed != hashlib.sha256(_canonical(results)).hexdigest():
        raise RcValidationError("RC_CONFORMANCE_RECEIPT_DIGEST_INVALID")


def validate_author_packet(value: dict[str, Any], candidate: str, root: Path) -> None:
    if (
        value.get("artifact") != "loopskill-v4-rc-author-packet-v1"
        or value.get("candidate_sha") != candidate
        or value.get("status") != "READY_FOR_AUTHOR_APPROVAL"
        or value.get("public_release_effects") != 0
        or value.get("real_v3_loop_migrations") != 0
    ):
        raise RcValidationError("RC_AUTHOR_PACKET_INVALID")
    files = value.get("files")
    if not isinstance(files, dict) or len(files) < 12:
        raise RcValidationError("RC_AUTHOR_PACKET_INCOMPLETE")
    for relative, expected in files.items():
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as exc:
            raise RcValidationError("RC_AUTHOR_PACKET_PATH_INVALID") from exc
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RcValidationError(f"RC_AUTHOR_PACKET_FILE_DRIFT: {relative}")


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--canary-receipt", type=Path)
    parser.add_argument("--conformance-receipt", type=Path)
    parser.add_argument("--author-packet", type=Path)
    parser.add_argument("--static-only", action="store_true")
    parser.add_argument("--allow-non-head", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        receipt = static_receipt(
            args.root, args.candidate, require_clean_head=not args.allow_non_head
        )
        if args.static_only:
            if args.canary_receipt or args.conformance_receipt or args.author_packet:
                raise RcValidationError("RC_STATIC_ONLY_WITH_FINAL_RECEIPT")
            receipt["gate_status"] = "PRE_CANARY_STATIC_ONLY"
        else:
            if not args.canary_receipt or not args.conformance_receipt or not args.author_packet:
                raise RcValidationError("RC_FINAL_RECEIPTS_REQUIRED")
            canary = json.loads(args.canary_receipt.read_text(encoding="utf-8"))
            validate_canary_receipt(canary, args.candidate)
            receipt["canary_receipt_digest"] = hashlib.sha256(
                _canonical(canary)
            ).hexdigest()
            conformance = json.loads(args.conformance_receipt.read_text(encoding="utf-8"))
            validate_conformance_receipt(conformance, args.candidate)
            receipt["conformance_receipt_digest"] = hashlib.sha256(
                _canonical(conformance)
            ).hexdigest()
            packet = json.loads(args.author_packet.read_text(encoding="utf-8"))
            validate_author_packet(packet, args.candidate, args.root)
            receipt["author_packet_digest"] = hashlib.sha256(
                _canonical(packet)
            ).hexdigest()
            receipt["gate_status"] = "LOOPSKILL_4_0_RC_READY_FOR_AUTHOR_APPROVAL"
            receipt["rc_ready"] = True
        receipt.pop("receipt_digest", None)
        receipt["receipt_digest"] = hashlib.sha256(_canonical(receipt)).hexdigest()
        if args.output:
            args.output.write_bytes(_canonical(receipt) + b"\n")
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RcValidationError) as exc:
        print(f"RC_VALIDATION_FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
