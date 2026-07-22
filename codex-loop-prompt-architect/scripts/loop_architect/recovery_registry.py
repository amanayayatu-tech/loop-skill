"""Schema-backed recovery registry for every public runtime rejection.

The registry is generated from literal rejection codes in the runtime and MCP
bridge.  Production code never silently invents a recovery for a newly added
code: the checked-in registry must be regenerated and reviewed first.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping


RECOVERY_REGISTRY_VERSION = "recovery-registry-v1"
RECOVERY_CLASSES = {"RECOVERABLE", "HUMAN_GATED", "TERMINAL", "NON_RETRYABLE"}
REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "references"
    / "recovery-registry-v1.json"
)


class RecoveryRegistryError(ValueError):
    """Raised when the checked-in registry is missing or internally invalid."""


def _validate_descriptor(code: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RecoveryRegistryError(f"recovery descriptor is not an object: {code}")
    required = {
        "classification",
        "operation",
        "preconditions",
        "identity_reuse",
        "side_effect_boundary",
        "stop_condition",
        "next_operation",
    }
    if set(value) != required:
        raise RecoveryRegistryError(f"recovery descriptor fields invalid: {code}")
    if value["classification"] not in RECOVERY_CLASSES:
        raise RecoveryRegistryError(f"recovery classification invalid: {code}")
    operation = value["operation"]
    if not isinstance(operation, str) or not operation or operation == "WAIT":
        raise RecoveryRegistryError(f"recovery operation invalid: {code}")
    next_operation = value["next_operation"]
    if (
        not isinstance(next_operation, dict)
        or next_operation.get("operation") != operation
        or not isinstance(next_operation.get("arguments"), dict)
    ):
        raise RecoveryRegistryError(f"next-operation template invalid: {code}")
    for field in (
        "preconditions",
        "identity_reuse",
        "side_effect_boundary",
        "stop_condition",
    ):
        if not isinstance(value[field], str) or not value[field]:
            raise RecoveryRegistryError(f"recovery field invalid: {code}/{field}")
    return dict(value)


@lru_cache(maxsize=1)
def load_recovery_registry() -> dict[str, dict[str, Any]]:
    try:
        document = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryRegistryError("recovery registry unavailable") from exc
    if not isinstance(document, dict) or document.get("schema_version") != RECOVERY_REGISTRY_VERSION:
        raise RecoveryRegistryError("recovery registry schema invalid")
    entries = document.get("entries")
    if not isinstance(entries, dict) or not entries:
        raise RecoveryRegistryError("recovery registry entries missing")
    return {
        code: _validate_descriptor(code, descriptor)
        for code, descriptor in entries.items()
        if isinstance(code, str) and code
    }


def recovery_for(code: str) -> dict[str, Any]:
    """Return one reviewed recovery descriptor, failing closed when absent."""

    descriptor = load_recovery_registry().get(code)
    if descriptor is None:
        return {
            "classification": "NON_RETRYABLE",
            "operation": "STOP_AND_REGISTER_RECOVERY",
            "preconditions": "No canonical mutation may proceed.",
            "identity_reuse": "Preserve the rejected request digest as evidence.",
            "side_effect_boundary": "Audit journal only.",
            "stop_condition": "Stop until this code is added to the reviewed registry.",
            "next_operation": {
                "operation": "STOP_AND_REGISTER_RECOVERY",
                "arguments": {"error_code": code},
            },
            "registered": False,
        }
    return {**descriptor, "registered": True}


def registry_document() -> Mapping[str, Any]:
    return {
        "schema_version": RECOVERY_REGISTRY_VERSION,
        "entries": load_recovery_registry(),
    }
