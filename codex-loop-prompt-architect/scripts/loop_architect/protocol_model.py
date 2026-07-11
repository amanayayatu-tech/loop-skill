"""Read-only protocol catalog derived from the Adaptive runtime and schemas.

This module deliberately contains no mutable loop state machine.  The
deterministic runtime and the two public JSON Schemas are the only execution
semantics.  Renderers and tests use this catalog to detect protocol drift.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import (
    ADAPTIVE_OUTBOX_KINDS,
    ADAPTIVE_REVIEW_DECISIONS,
    ADAPTIVE_RUNTIME_MUTATIONS,
    ADAPTIVE_RUNTIME_SUCCESS_CODES,
)
from .state_runtime import ACTIVE_OUTBOX_STATUSES, OUTBOX_FIELDS, REVIEW_DECISIONS


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
STATE_SCHEMA_PATH = PACKAGE_ROOT / "references" / "adaptive-state.schema.json"
MUTATION_SCHEMA_PATH = PACKAGE_ROOT / "references" / "adaptive-mutation.schema.json"

OUTBOX_LIFECYCLES: dict[str, tuple[str, ...]] = {
    "DISPATCH": ("PREPARED", "SENT", "COMPLETED"),
    "AUTOMATION": ("PREPARED", "SENT", "ACKED"),
    "GOAL": ("PREPARED", "SENT", "ACKED"),
    "THREAD": ("PREPARED", "SENT", "ACKED"),
    "ASSURANCE": ("PREPARED", "SENT", "ACKED", "COMPLETED"),
    "LOCAL": ("PREPARED", "SENT", "COMPLETED"),
    "DELEGATION": ("PREPARED", "SENT", "ACKED"),
}

OUTBOX_CANCELLATION_LIFECYCLES: dict[str, tuple[str, ...]] = {
    kind: ("PREPARED", "CANCELLED") for kind in OUTBOX_LIFECYCLES
}

EMULATED_GOAL_LIFECYCLE = ("PREPARED", "ACKED")

FORBIDDEN_ADAPTIVE_PROTOCOL_TOKENS = (
    "THREAD_CREATE_PREPARED",
    "THREAD_CREATED",
    "THREAD_REGISTERED",
    "AUTOMATION_CREATE_PREPARED",
    "AUTOMATION_REGISTERED",
    "DISPATCH_PREPARED",
    "DISPATCH_SENT",
    "ROADMAP_CHANGE_PREPARED",
    "ROADMAP_CHANGE_APPLIED",
    "PENDING_ARCHIVE",
    "PENDING_ACK",
    "inflight_dispatch",
    "wake_count",
    "consecutive_idle_wakeups",
    "repair_attempts_by_goal",
    "HEARTBEAT_IDLE_BUDGET_EXHAUSTED",
)


class ProtocolDriftError(ValueError):
    """Raised when a renderer or schema diverges from runtime semantics."""


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProtocolDriftError(f"schema must be an object: {path}")
    return value


def mutation_schema() -> dict[str, Any]:
    return _load(MUTATION_SCHEMA_PATH)


def state_schema() -> dict[str, Any]:
    return _load(STATE_SCHEMA_PATH)


def accepted_mutation_types() -> tuple[str, ...]:
    schema = mutation_schema()
    values: list[str] = []
    for branch in schema["properties"]["mutation"]["oneOf"]:
        name = branch["$ref"].rsplit("/", 1)[-1]
        values.append(schema["$defs"][name]["properties"]["type"]["const"])
    return tuple(values)


def accepted_outbox_kinds() -> tuple[str, ...]:
    schema = mutation_schema()
    return tuple(schema["$defs"]["prepareOutbox"]["properties"]["outbox_kind"]["enum"])


def accepted_review_decisions() -> tuple[str, ...]:
    schema = mutation_schema()
    return tuple(schema["$defs"]["recordReview"]["properties"]["decision"]["enum"])


def authorization_fields() -> tuple[str, ...]:
    schema = state_schema()
    return tuple(schema["$defs"]["authorizationEnvelope"]["required"])


def runtime_success_codes() -> tuple[str, ...]:
    kind_codes = [
        f"{kind}_{suffix}"
        for kind in OUTBOX_FIELDS
        for suffix in (
            "OUTBOX_PREPARED",
            "OUTBOX_SENT",
            "OUTBOX_ACKED",
            "OUTBOX_CANCELLED",
        )
    ]
    review_codes = [f"{kind}_ACKED" for kind in REVIEW_DECISIONS]
    return tuple(dict.fromkeys((*ADAPTIVE_RUNTIME_SUCCESS_CODES, *kind_codes, *review_codes)))


def validate_protocol_sources() -> list[str]:
    """Return deterministic drift findings; an empty list means aligned."""

    findings: list[str] = []
    if accepted_mutation_types() != ADAPTIVE_RUNTIME_MUTATIONS:
        findings.append("mutation schema and renderer mutation catalog differ")
    if accepted_outbox_kinds() != ADAPTIVE_OUTBOX_KINDS:
        findings.append("mutation schema and renderer outbox-kind catalog differ")
    if set(accepted_outbox_kinds()) != set(OUTBOX_FIELDS):
        findings.append("mutation schema and runtime outbox kinds differ")
    if accepted_review_decisions() != ADAPTIVE_REVIEW_DECISIONS:
        findings.append("mutation schema and renderer review-decision catalog differ")
    runtime_decisions = {
        decision for values in REVIEW_DECISIONS.values() for decision in values
    }
    if set(accepted_review_decisions()) != runtime_decisions:
        findings.append("mutation schema and runtime review decisions differ")
    if ACTIVE_OUTBOX_STATUSES != {"PREPARED", "SENT"}:
        findings.append("runtime active outbox states differ from the documented fence")
    if set(OUTBOX_LIFECYCLES) != set(OUTBOX_FIELDS):
        findings.append("one or more runtime outbox kinds lack a documented lifecycle")
    if set(OUTBOX_CANCELLATION_LIFECYCLES) != set(OUTBOX_FIELDS) or any(
        lifecycle != ("PREPARED", "CANCELLED")
        for lifecycle in OUTBOX_CANCELLATION_LIFECYCLES.values()
    ):
        findings.append("one or more runtime outbox kinds lack PREPARED cancellation")
    if EMULATED_GOAL_LIFECYCLE != ("PREPARED", "ACKED"):
        findings.append("emulated Goal lifecycle must direct-ACK PREPARED")
    return findings


def assert_protocol_sources_aligned() -> None:
    findings = validate_protocol_sources()
    if findings:
        raise ProtocolDriftError("; ".join(findings))


def forbidden_rendered_tokens(text: str) -> tuple[str, ...]:
    return tuple(token for token in FORBIDDEN_ADAPTIVE_PROTOCOL_TOKENS if token in text)


def assert_rendered_pack_aligned(text: str) -> None:
    found = forbidden_rendered_tokens(text)
    if found:
        raise ProtocolDriftError(
            "Adaptive renderer emitted non-runtime protocol tokens: " + ", ".join(found)
        )
