"""Canonical P1 governance adapter.

This module is the single integration point between the P1 helper modules and
schema-v3 canonical state.  It deliberately stores only bounded structured
records: no prompts, task identifiers, paths, chat text, or raw App results.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from typing import Any, Mapping

from .capability_envelope import CapabilityEnvelope
from .defect_family import DefectFamily, DefectFamilyError
from .goal_registry_rules import GoalRegistry, GoalRegistryError
from .manifest_compiler import CompiledManifest
from .reviewer_envelope import ReviewerEnvelopeError, build_envelope


P1_CONTRACT_VERSION = 1
UNMETERED = "UNMETERED"
ESCALATION_ACTIONS = frozenset(
    {"REFACTOR", "GOAL_SPLIT", "CLAIM_NARROWING", "LIMITATION"}
)


class P1RuntimeError(ValueError):
    def __init__(self, code: str, path: str = "/p1_runtime") -> None:
        super().__init__(code)
        self.code = code
        self.path = path


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _exact_mapping(value: Any, keys: set[str], path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise P1RuntimeError("P1_EXACT_OBJECT_INVALID", path)
    return value


def initial_state(
    *,
    enabled: bool,
    initialization_class: str,
    goal_definitions: Mapping[str, Mapping[str, Any]],
    supervisor_capabilities: Mapping[str, Any] | None = None,
    model_canaries: Mapping[str, Any] | None = None,
    runtime_digest: str = UNMETERED,
    config_digest: str = UNMETERED,
) -> dict[str, Any]:
    """Return the canonical P1 subdocument for a new Loop."""

    mode = "DISPOSABLE" if initialization_class == "DISPOSABLE" else "FORMAL"
    registry = GoalRegistry(disposable=mode == "DISPOSABLE")
    if enabled:
        try:
            registry.initialize(
                [
                    {
                        "goal_id": goal_id,
                        "objective": definition["objective"],
                        "required_completion_class": definition.get(
                            "required_completion_class", "COMPLETE_ARTIFACT"
                        ),
                        "depends_on": list(definition.get("depends_on", [])),
                    }
                    for goal_id, definition in goal_definitions.items()
                ]
            )
        except (KeyError, GoalRegistryError) as exc:
            raise P1RuntimeError("P1_GOAL_REGISTRY_INVALID", "/goal_definition_registry") from exc

    capability_value: dict[str, Any] | None = None
    capability_digest: str | None = None
    if supervisor_capabilities is not None:
        try:
            envelope = CapabilityEnvelope.from_dict(supervisor_capabilities)
        except (KeyError, TypeError, ValueError) as exc:
            raise P1RuntimeError(
                "P1_SUPERVISOR_CAPABILITY_INVALID", "/supervisor_capabilities"
            ) from exc
        capability_value = envelope.to_dict()
        capability_digest = "sha256:" + envelope.digest()

    canaries = copy.deepcopy(dict(model_canaries or {}))
    if enabled:
        for role in ("CONTROLLER", "WORKER", "REVIEWER"):
            record = canaries.get(role, {"status": UNMETERED})
            if not isinstance(record, dict) or record.get("status") not in {
                "PASS", "FAIL", UNMETERED
            }:
                raise P1RuntimeError("P1_MODEL_CANARY_INVALID", f"/model_canaries/{role}")
            canaries[role] = copy.deepcopy(record)

    return {
        "contract_version": P1_CONTRACT_VERSION,
        "enabled": bool(enabled),
        "defect_families": {},
        "reviewer_returns": {},
        "heartbeat_registry": {},
        "route_orchestrations": {},
        "metrics": {
            "accepted_count": 0,
            "rejected_count": 0,
            "human_intervention_count": 0,
            "supervisor_intervention_count": 0,
            "route_latency_ms": [],
            "heartbeat_latency_ms": [],
            "recovery_latency_ms": [],
            "token_estimate": UNMETERED,
            "cost_estimate_usd": UNMETERED,
            "runtime_digest": runtime_digest,
            "config_digest": config_digest,
            "model_digest": UNMETERED,
        },
        "supervisor_capability": capability_value,
        "supervisor_capability_digest": capability_digest,
        "model_canaries": canaries,
        "goal_registry": {
            "mode": mode,
            "goal_ids": sorted(goal_definitions),
            "digest": _digest(
                {
                    key: goal_definitions[key]
                    for key in sorted(goal_definitions)
                }
            ),
            "migration_status": "LOCKED_UNTIL_SAFE_POINT",
        },
    }


def ensure_compatible(state: dict[str, Any]) -> dict[str, Any]:
    value = state.get("p1_runtime")
    if value is None:
        value = initial_state(
            enabled=False,
            initialization_class=state.get("initialization_class", "LEGACY_COMPATIBLE"),
            goal_definitions=state.get("goal_definition_registry", {}),
        )
        state["p1_runtime"] = value
    if not isinstance(value, dict) or value.get("contract_version") != P1_CONTRACT_VERSION:
        raise P1RuntimeError("P1_RUNTIME_STATE_INVALID")
    return value


def record_heartbeat(state: dict[str, Any], observation: Mapping[str, Any]) -> None:
    runtime = ensure_compatible(state)
    if not runtime["enabled"]:
        return
    required = {
        "automation_id", "status", "automation_name", "kind",
        "target_thread_id", "rrule", "prompt_digest",
        "prompt_normalization", "observed_at",
    }
    item = _exact_mapping(observation, required, "/heartbeat_observation")
    identity = {
        key: item[key]
        for key in (
            "automation_id", "automation_name", "kind", "target_thread_id",
            "rrule", "prompt_digest", "prompt_normalization",
        )
    }
    existing = runtime["heartbeat_registry"].get(item["automation_id"])
    if existing is not None and existing["identity"] != identity:
        raise P1RuntimeError("P1_HEARTBEAT_REGISTRY_DRIFT", "/heartbeat_observation")
    sequence = 1 if existing is None else existing["sequence"] + 1
    runtime["heartbeat_registry"][item["automation_id"]] = {
        "identity": copy.deepcopy(identity),
        "status": item["status"],
        "sequence": sequence,
        "observed_at": item["observed_at"],
        "digest": _digest({**identity, "status": item["status"], "sequence": sequence}),
    }


def record_route_prepared(
    state: dict[str, Any], *, route_id: str, route_kind: str, observed_at: str
) -> None:
    runtime = ensure_compatible(state)
    if not runtime["enabled"]:
        return
    if route_id in runtime["route_orchestrations"]:
        raise P1RuntimeError("P1_ROUTE_ORCHESTRATION_CONFLICT", "/route_id")
    runtime["route_orchestrations"][route_id] = {
        "status": "PREPARED",
        "route_kind": route_kind,
        "prepared_at": observed_at,
        "sent_at": None,
        "acked_at": None,
        "external_receipt": None,
    }


def record_route_sent(
    state: dict[str, Any], *, route_id: str, observed_at: str, receipt_digest: str
) -> None:
    runtime = ensure_compatible(state)
    if not runtime["enabled"]:
        return
    record = runtime["route_orchestrations"].get(route_id)
    if not isinstance(record, dict) or record.get("status") != "PREPARED":
        raise P1RuntimeError("P1_ROUTE_ORCHESTRATION_NOT_PREPARED", "/route_id")
    record.update(
        status="SENT", sent_at=observed_at, external_receipt=receipt_digest
    )


def _latency_ms(start: str | None, end: str | None) -> int | str:
    if not start or not end:
        return UNMETERED
    try:
        first = datetime.fromisoformat(start.replace("Z", "+00:00"))
        second = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return UNMETERED
    return max(0, int((second - first).total_seconds() * 1000))


def record_route_acked(
    state: dict[str, Any], *, route_id: str, observed_at: str, accepted: bool
) -> None:
    runtime = ensure_compatible(state)
    if not runtime["enabled"]:
        return
    record = runtime["route_orchestrations"].get(route_id)
    if not isinstance(record, dict) or record.get("status") != "SENT":
        raise P1RuntimeError("P1_ROUTE_ORCHESTRATION_NOT_SENT", "/route_id")
    record.update(status="ACKED", acked_at=observed_at)
    latency = _latency_ms(record.get("prepared_at"), observed_at)
    runtime["metrics"]["route_latency_ms"].append(latency)
    counter = "accepted_count" if accepted else "rejected_count"
    runtime["metrics"][counter] += 1


def record_review_disclosure(
    state: dict[str, Any], *, result: Mapping[str, Any], evidence_paths: list[str]
) -> dict[str, Any] | None:
    """Validate and persist mandatory same-family disclosure for P1 Loops."""

    runtime = ensure_compatible(state)
    if not runtime["enabled"]:
        return None
    disclosure = result.get("reviewer_disclosure")
    if not isinstance(disclosure, Mapping):
        raise P1RuntimeError("P1_REVIEWER_DISCLOSURE_REQUIRED", "/result/reviewer_disclosure")
    required = {
        "verdict", "defect_family", "searched_files", "searched_patterns",
        "unchecked_surfaces", "siblings", "remediation",
    }
    item = _exact_mapping(disclosure, required, "/result/reviewer_disclosure")
    try:
        family = DefectFamily.from_dict(item["defect_family"])
    except (DefectFamilyError, KeyError, TypeError, ValueError) as exc:
        raise P1RuntimeError("P1_DEFECT_FAMILY_INVALID", "/result/reviewer_disclosure/defect_family") from exc
    family_id = family.family_id
    return_number = int(runtime["reviewer_returns"].get(family_id, 0)) + 1
    try:
        envelope = build_envelope(
            verdict=item["verdict"],
            defect_family_id=family_id,
            defect_family_digest=family.digest(),
            searched_files=item["searched_files"],
            searched_patterns=item["searched_patterns"],
            unchecked_surfaces=item["unchecked_surfaces"],
            siblings=item["siblings"],
            return_number=return_number,
            remediation=item["remediation"],
            evidence_paths=evidence_paths,
        )
    except (ReviewerEnvelopeError, TypeError, ValueError) as exc:
        raise P1RuntimeError("P1_REVIEWER_DISCLOSURE_INVALID", "/result/reviewer_disclosure") from exc
    runtime["reviewer_returns"][family_id] = return_number
    runtime["defect_families"][family_id] = {
        "family": family.to_dict(),
        "family_digest": "sha256:" + family.digest(),
        "return_number": return_number,
        "reviewer_envelope": envelope.to_dict(),
        "closure_status": family.closure_status,
    }
    return copy.deepcopy(runtime["defect_families"][family_id])


def repair_context(state: dict[str, Any], goal_id: str) -> dict[str, Any] | None:
    runtime = ensure_compatible(state)
    if not runtime["enabled"]:
        return None
    matches = [
        value for value in runtime["defect_families"].values()
        if value.get("reviewer_envelope", {}).get("verdict")
        in {"POINT_REPAIR", *ESCALATION_ACTIONS}
    ]
    if not matches:
        return None
    return copy.deepcopy(sorted(matches, key=lambda value: value["return_number"])[-1])


def privacy_safe_export(state: Mapping[str, Any]) -> dict[str, Any]:
    runtime = state.get("p1_runtime", {})
    metrics = runtime.get("metrics", {}) if isinstance(runtime, Mapping) else {}
    result = {
        "schema_version": "privacy-safe-measurement-export-v1",
        "accepted_count": metrics.get("accepted_count", 0),
        "rejected_count": metrics.get("rejected_count", 0),
        "human_intervention_count": metrics.get("human_intervention_count", 0),
        "supervisor_intervention_count": metrics.get("supervisor_intervention_count", 0),
        "route_latency_ms": copy.deepcopy(metrics.get("route_latency_ms", [])),
        "heartbeat_latency_ms": copy.deepcopy(metrics.get("heartbeat_latency_ms", [])),
        "recovery_latency_ms": copy.deepcopy(metrics.get("recovery_latency_ms", [])),
        "token_estimate": metrics.get("token_estimate", UNMETERED),
        "cost_estimate_usd": metrics.get("cost_estimate_usd", UNMETERED),
        "runtime_digest": metrics.get("runtime_digest", UNMETERED),
        "config_digest": metrics.get("config_digest", UNMETERED),
        "model_digest": metrics.get("model_digest", UNMETERED),
    }
    result["export_digest"] = _digest(result)
    return result


__all__ = [
    "P1_CONTRACT_VERSION", "P1RuntimeError", "UNMETERED",
    "ensure_compatible", "initial_state", "privacy_safe_export",
    "record_heartbeat", "record_review_disclosure", "record_route_acked",
    "record_route_prepared", "record_route_sent", "repair_context",
]
