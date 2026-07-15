#!/usr/bin/env python3
"""Validate a real Codex App canary receipt without accepting synthetic proof."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import jsonschema


SENSITIVE_KEYS = {
    "prompt",
    "raw_response",
    "authorization",
    "api_key",
    "secret",
    "canonical_content",
    "session_id",
    "thread_id",
    "turn_id",
}


class CanaryReceiptError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def compatibility_identity(receipt: Mapping[str, Any]) -> dict[str, Any]:
    mcp = receipt["mcp"]
    return {
        "app": receipt["app"],
        "app_server": receipt["app_server"],
        "mcp_protocol_version": mcp["protocol_version"],
        "mcp_config_schema_version": mcp["config_schema_version"],
        "request_meta_shape": mcp["request_meta_shape"],
        "registration": mcp["registration"],
    }


def _walk_for_secrets(value: object, path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in SENSITIVE_KEYS:
                raise CanaryReceiptError(f"CANARY_RECEIPT_SENSITIVE_FIELD: {path}/{key}")
            _walk_for_secrets(child, f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_for_secrets(child, f"{path}/{index}")
    elif isinstance(value, str) and re.search(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+", value):
        raise CanaryReceiptError(f"CANARY_RECEIPT_AUTHORIZATION_VALUE: {path}")


def _timestamp(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CanaryReceiptError("CANARY_RECEIPT_TIME_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(hours=8):
        raise CanaryReceiptError("CANARY_RECEIPT_TIMEZONE_OFFSET_INVALID")
    return parsed


def validate_receipt(
    path: Path,
    schema: Path,
    *,
    expected_commit: str | None = None,
    expected_tracked_tree_digest: str | None = None,
    expected_manifest_digest: str | None = None,
    expected_pack_digest: str | None = None,
    expected_compatibility_identity_digest: str | None = None,
    expected_app_version: str | None = None,
    expected_app_build: str | None = None,
    expected_bundle_identifier: str | None = None,
) -> dict[str, Any]:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    schema_value = json.loads(schema.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema_value, format_checker=jsonschema.FormatChecker()).validate(receipt)
    if not isinstance(receipt, dict):
        raise CanaryReceiptError("CANARY_RECEIPT_INVALID")
    _walk_for_secrets(receipt)
    started = _timestamp(receipt["started_at"])
    finished = _timestamp(receipt["finished_at"])
    if finished < started:
        raise CanaryReceiptError("CANARY_RECEIPT_TIME_ORDER_INVALID")
    expected_identity_digest = _digest(compatibility_identity(receipt))
    if receipt["compatibility_identity_digest"] != expected_identity_digest:
        raise CanaryReceiptError("CANARY_COMPATIBILITY_IDENTITY_MISMATCH")
    body = dict(receipt)
    claimed_receipt_digest = body.pop("receipt_digest")
    if claimed_receipt_digest != _digest(body):
        raise CanaryReceiptError("CANARY_RECEIPT_DIGEST_MISMATCH")
    if expected_commit is not None and receipt["repo_commit"] != expected_commit:
        raise CanaryReceiptError("CANARY_REPO_COMMIT_MISMATCH")
    if (
        expected_tracked_tree_digest is not None
        and receipt["tracked_tree_digest"] != expected_tracked_tree_digest
    ):
        raise CanaryReceiptError("CANARY_TRACKED_TREE_MISMATCH")
    if expected_manifest_digest is not None and receipt["installed_manifest_digest"] != expected_manifest_digest:
        raise CanaryReceiptError("CANARY_INSTALL_MANIFEST_MISMATCH")
    if expected_pack_digest is not None and receipt["pack_digest"] != expected_pack_digest:
        raise CanaryReceiptError("CANARY_PACK_DIGEST_MISMATCH")
    if (
        expected_compatibility_identity_digest is not None
        and receipt["compatibility_identity_digest"]
        != expected_compatibility_identity_digest
    ):
        raise CanaryReceiptError("CANARY_CURRENT_APP_IDENTITY_MISMATCH")
    app = receipt["app"]
    for actual, expected, code in (
        (app["version"], expected_app_version, "CANARY_APP_VERSION_MISMATCH"),
        (app["build"], expected_app_build, "CANARY_APP_BUILD_MISMATCH"),
        (app["bundle_identifier"], expected_bundle_identifier, "CANARY_APP_BUNDLE_MISMATCH"),
    ):
        if expected is not None and actual != expected:
            raise CanaryReceiptError(code)
    if receipt["status"] == "PASS":
        if receipt["error_classification"] is not None or not all(receipt["checks"].values()):
            raise CanaryReceiptError("CANARY_PASS_INCOMPLETE")
    elif receipt["error_classification"] is None:
        raise CanaryReceiptError("CANARY_FAILURE_CLASSIFICATION_MISSING")
    return receipt


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--expected-commit")
    parser.add_argument("--expected-tracked-tree-digest")
    parser.add_argument("--expected-manifest-digest")
    parser.add_argument("--expected-pack-digest")
    parser.add_argument("--expected-compatibility-identity-digest")
    parser.add_argument("--expected-app-version")
    parser.add_argument("--expected-app-build")
    parser.add_argument("--expected-bundle-identifier")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        receipt = validate_receipt(
            args.receipt,
            args.schema,
            expected_commit=args.expected_commit,
            expected_tracked_tree_digest=args.expected_tracked_tree_digest,
            expected_manifest_digest=args.expected_manifest_digest,
            expected_pack_digest=args.expected_pack_digest,
            expected_compatibility_identity_digest=args.expected_compatibility_identity_digest,
            expected_app_version=args.expected_app_version,
            expected_app_build=args.expected_app_build,
            expected_bundle_identifier=args.expected_bundle_identifier,
        )
        print(json.dumps({"ok": True, "receipt_digest": receipt["receipt_digest"]}, sort_keys=True, separators=(",", ":")))
    except (OSError, ValueError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
        print(json.dumps({"ok": False, "status": str(exc)}, sort_keys=True, separators=(",", ":")), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
