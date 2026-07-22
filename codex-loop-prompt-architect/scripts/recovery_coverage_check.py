#!/usr/bin/env python3
"""Fail CI unless every reachable runtime/CLI/codec code has one recovery."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import build_recovery_registry


def check(registry_path: Path = build_recovery_registry.OUTPUT) -> dict[str, Any]:
    expected = build_recovery_registry.extract_codes()
    try:
        document = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "status": "RECOVERY_COVERAGE_REGISTRY_INVALID",
            "failures": [type(exc).__name__],
        }
    entries = document.get("entries") if isinstance(document, dict) else None
    if not isinstance(entries, dict):
        return {
            "ok": False,
            "status": "RECOVERY_COVERAGE_REGISTRY_INVALID",
            "failures": ["entries must be an object"],
        }
    failures: list[str] = []
    missing = sorted(expected - set(entries))
    stale = sorted(set(entries) - expected)
    if missing:
        failures.append("missing:" + ",".join(missing))
    if stale:
        failures.append("stale:" + ",".join(stale))
    for code, descriptor in sorted(entries.items()):
        if not isinstance(descriptor, dict):
            failures.append(f"{code}:descriptor-not-object")
            continue
        operation = descriptor.get("operation")
        next_operation = descriptor.get("next_operation")
        if (
            descriptor.get("classification")
            not in {"RECOVERABLE", "HUMAN_GATED", "TERMINAL", "NON_RETRYABLE"}
            or not isinstance(operation, str)
            or not operation
            or operation == "WAIT"
            or not isinstance(next_operation, dict)
            or next_operation.get("operation") != operation
        ):
            failures.append(f"{code}:invalid-or-wait-only-recovery")
    return {
        "ok": not failures,
        "status": (
            "RECOVERY_COVERAGE_COMPLETE"
            if not failures
            else "RECOVERY_COVERAGE_INCOMPLETE"
        ),
        "code_count": len(expected),
        "registry_entry_count": len(entries),
        "source_count": len(build_recovery_registry.SOURCES),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=build_recovery_registry.OUTPUT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = check(args.registry)
    print(json.dumps(result, sort_keys=True) if args.json else result["status"])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
