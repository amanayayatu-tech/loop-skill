#!/usr/bin/env python3
"""Generate/check the explicit recovery registry from runtime error literals."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
SOURCES = (
    PROJECT_DIR / "scripts" / "loop_architect" / "state_runtime.py",
    PROJECT_DIR / "scripts" / "adaptive_state_mcp.py",
    PROJECT_DIR / "scripts" / "adaptive_state_runtime.py",
)
OUTPUT = PROJECT_DIR / "references" / "recovery-registry-v1.json"
CALLS = {
    "RuntimeRejection",
    "McpBridgeError",
    "_runtime_error",
    # The MCP bridge deliberately funnels public Gateway failures through
    # this helper.  Omitting it made literal bridge codes invisible to the
    # coverage gate even though they were reachable in the real App path.
    "_gateway_error",
}
EXTRA_DYNAMIC_CODES = {
    "INTERNAL_ERROR",
    "PERSISTENCE_ERROR",
    "RECOVERY_REQUIRED",
    "REQUEST_SCHEMA_INVALID",
    "CANONICAL_STATE_SCHEMA_INVALID",
}


def extract_codes() -> set[str]:
    codes: set[str] = set(EXTRA_DYNAMIC_CODES)
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            first = node.args[0]
            if (
                name in CALLS
                and isinstance(first, ast.Constant)
                and isinstance(first.value, str)
            ):
                codes.add(first.value)
    return codes


def descriptor(code: str) -> dict[str, Any]:
    human_markers = (
        "APP_", "HUMAN_", "DECISION_", "AUTHORIZATION_", "CAPABILITY_",
        "ATTESTATION", "HEARTBEAT_ACTIVE_READBACK_REQUIRED",
        "HEARTBEAT_PAUSED_READBACK_REQUIRED",
    )
    terminal_markers = (
        "BUDGET_EXHAUSTED", "CONVERGENCE_BLOCKED", "LOOP_ALREADY_TERMINAL",
        "FINALIZE_UNEXECUTED_GOALS", "FINALIZE_UNRESOLVED_MILESTONE",
    )
    non_retryable_markers = (
        "_UNSUPPORTED", "_FORBIDDEN", "_VIOLATION", "_TOO_LARGE",
        "UNSAFE_ID", "SYMLINK_NOT_ALLOWED", "ROOT_NOT_DIRECTORY",
    )
    if code == "STATE_GATEWAY_HEARTBEAT_UNREGISTERED":
        classification = "RECOVERABLE"
        operation = "REGISTER_HEARTBEAT_FROM_APP_READBACK"
        preconditions = (
            "Read the existing App heartbeat and submit its exact ACTIVE "
            "identity through REGISTER_HEARTBEAT."
        )
        identity = "Reuse the existing App automation identity and normalized prompt digest."
        stop = "Stop if the App heartbeat cannot be read back or its identity has drifted."
    elif code == "RECOVERY_REQUIRED":
        classification = "RECOVERABLE"
        operation = "RECOVER_TRANSACTIONS"
        preconditions = "Use the same canonical root and do not rebuild artifacts."
        identity = "Reuse the original transaction and request identities."
        stop = "Stop if recovery cannot prove one durable outcome."
    elif any(marker in code for marker in human_markers):
        classification = "HUMAN_GATED"
        operation = "PROVIDE_HOST_OR_HUMAN_RECEIPT"
        preconditions = "Obtain a fresh receipt from the authoritative host or human gate."
        identity = "Reuse the rejected intent; never self-attest role or model identity."
        stop = "Stop when the required authority or observation is unavailable."
    elif any(marker in code for marker in terminal_markers):
        classification = "TERMINAL"
        operation = "STOP_WITH_LIMITATION"
        preconditions = "Preserve accepted and rejected evidence before stopping."
        identity = "Do not create a replacement request for the same exhausted route."
        stop = "This condition terminates the current route or narrows its claim."
    elif any(marker in code for marker in non_retryable_markers):
        classification = "NON_RETRYABLE"
        operation = "SUBMIT_NEW_CORRECTED_INTENT"
        preconditions = "Correct the unsupported or unsafe input before a new request."
        identity = "Use a new request identity; retain the rejected digest as history."
        stop = "Stop if correction would expand authority or weaken an invariant."
    elif code in {"STATE_VERSION_CONFLICT", "ROADMAP_VERSION_CONFLICT"}:
        classification = "RECOVERABLE"
        operation = "READ_CANONICAL_AND_RETRY"
        preconditions = "Read current canonical state and revalidate the unchanged intent."
        identity = "Use a new CAS request identity bound to the current state version."
        stop = "Stop if the refreshed state makes the intent stale or unauthorized."
    elif code in {"PERSISTENCE_ERROR", "INTERNAL_ERROR"}:
        classification = "RECOVERABLE"
        operation = "RETRY_SAME_REQUEST"
        preconditions = "Verify no transaction journal became visible before retrying."
        identity = "Reuse the original request identity only when no durable write exists."
        stop = "Stop and recover transactions if any durable journal is present."
    else:
        classification = "RECOVERABLE"
        operation = "RESUBMIT_CORRECTED_REQUEST"
        preconditions = "Read the error path and canonical state before correction."
        identity = "Preserve artifact and outbox identities unless the registry says otherwise."
        stop = "Stop if correction requires broader authority or cannot preserve identity."
    return {
        "classification": classification,
        "operation": operation,
        "preconditions": preconditions,
        "identity_reuse": identity,
        "side_effect_boundary": "Rejection audit append only until recovery preconditions hold.",
        "stop_condition": stop,
        "next_operation": {
            "operation": operation,
            "arguments": {"error_code": code, "use_original_evidence": True},
        },
    }


def rendered() -> str:
    document = {
        "schema_version": "recovery-registry-v1",
        "entries": {code: descriptor(code) for code in sorted(extract_codes())},
    }
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--emit", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    expected = rendered()
    current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else None
    ok = current == expected
    if args.emit:
        OUTPUT.write_text(expected, encoding="utf-8")
        ok = True
    result = {
        "ok": ok,
        "status": "RECOVERY_REGISTRY_CURRENT" if ok else "RECOVERY_REGISTRY_STALE",
        "entry_count": len(extract_codes()),
        "path": str(OUTPUT),
    }
    if args.json:
        print(json.dumps(result, sort_keys=True))
    elif not ok or not args.check:
        print(result["status"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
