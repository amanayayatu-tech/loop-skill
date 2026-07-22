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
    if not isinstance(value, dict) or set(value) != keys:
        raise P1RuntimeError("P1_EXACT_OBJECT_INVALID", path)
    return value


def _safe_text(value: Any, path: str) -> str:
    if type(value) is not str or not value:
        raise P1RuntimeError("P1_EXACT_TYPE_INVALID", path)
    return value


def _digest_or_unmetered(value: Any, path: str) -> str:
    text = _safe_text(value, path)
    if text != UNMETERED and (
        not text.startswith("sha256:")
        or len(text) != 71
        or any(character not in "0123456789abcdef" for character in text[7:])
    ):
        raise P1RuntimeError("P1_DIGEST_INVALID", path)
    return text


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

    if type(enabled) is not bool:
        raise P1RuntimeError("P1_EXACT_TYPE_INVALID", "/p1_runtime_enabled")
    if initialization_class not in {"DISPOSABLE", "FORMAL", "LEGACY_COMPATIBLE"}:
        raise P1RuntimeError("P1_INITIALIZATION_CLASS_INVALID", "/initialization_class")
    if not isinstance(goal_definitions, dict):
        raise P1RuntimeError("P1_GOAL_REGISTRY_INVALID", "/goal_definition_registry")
    runtime_digest = _digest_or_unmetered(runtime_digest, "/runtime_digest")
    config_digest = _digest_or_unmetered(config_digest, "/config_digest")
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
    if enabled and supervisor_capabilities is None:
        raise P1RuntimeError(
            "P1_SUPERVISOR_CAPABILITY_REQUIRED", "/supervisor_capabilities"
        )
    if supervisor_capabilities is not None:
        try:
            envelope = CapabilityEnvelope.from_dict(supervisor_capabilities)
        except (KeyError, TypeError, ValueError) as exc:
            raise P1RuntimeError(
                "P1_SUPERVISOR_CAPABILITY_INVALID", "/supervisor_capabilities"
            ) from exc
        capability_value = envelope.to_dict()
        capability_digest = "sha256:" + envelope.digest()

    if model_canaries is not None and not isinstance(model_canaries, dict):
        raise P1RuntimeError("P1_MODEL_CANARY_INVALID", "/model_canaries")
    canaries = copy.deepcopy(dict(model_canaries or {}))
    if set(canaries) - {"CONTROLLER", "WORKER", "REVIEWER"}:
        raise P1RuntimeError("P1_MODEL_CANARY_INVALID", "/model_canaries")
    if enabled:
        for role in ("CONTROLLER", "WORKER", "REVIEWER"):
            record = canaries.get(role, {"status": UNMETERED})
            if (
                not isinstance(record, dict)
                or set(record) not in (
                    {"status"},
                    {"status", "task_digest", "result_digest"},
                )
                or record.get("status") not in {"PASS", "FAIL", UNMETERED}
            ):
                raise P1RuntimeError("P1_MODEL_CANARY_INVALID", f"/model_canaries/{role}")
            if set(record) == {"status", "task_digest", "result_digest"}:
                _digest_or_unmetered(record["task_digest"], f"/model_canaries/{role}/task_digest")
                _digest_or_unmetered(record["result_digest"], f"/model_canaries/{role}/result_digest")
            if initialization_class == "FORMAL" and (
                set(record) != {"status", "task_digest", "result_digest"}
                or record["status"] != "PASS"
            ):
                raise P1RuntimeError(
                    "P1_MODEL_CANARY_REQUIRED", f"/model_canaries/{role}"
                )
            canaries[role] = copy.deepcopy(record)

    result = {
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
    if enabled:
        result["metrics"]["model_digest"] = _digest(canaries)
    return result


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


def authorize_supervisor(
    state: dict[str, Any], *, operation: str, scope_prefix: str
) -> None:
    runtime = ensure_compatible(state)
    if not runtime["enabled"]:
        return
    _safe_text(operation, "/operation")
    _safe_text(scope_prefix, "/scope_prefix")
    raw = runtime.get("supervisor_capability")
    try:
        envelope = CapabilityEnvelope.from_dict(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise P1RuntimeError(
            "P1_SUPERVISOR_CAPABILITY_INVALID", "/p1_runtime/supervisor_capability"
        ) from exc
    if not envelope.authorize(operation, scope_prefix=scope_prefix):
        raise P1RuntimeError(
            "P1_SUPERVISOR_CAPABILITY_DENIED", "/p1_runtime/supervisor_capability"
        )


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
    for key in required:
        _safe_text(item[key], f"/heartbeat_observation/{key}")
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
    runtime["metrics"]["heartbeat_latency_ms"].append(
        UNMETERED
        if existing is None
        else _latency_ms(existing.get("observed_at"), item["observed_at"])
    )
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
    _safe_text(route_id, "/route_id")
    _safe_text(route_kind, "/route_kind")
    _safe_text(observed_at, "/observed_at")
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
    _safe_text(route_id, "/route_id")
    _safe_text(observed_at, "/observed_at")
    _digest_or_unmetered(receipt_digest, "/receipt_digest")
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
    state: dict[str, Any], *, route_id: str, observed_at: str, accepted: bool,
    recovery: bool = False,
) -> None:
    runtime = ensure_compatible(state)
    if not runtime["enabled"]:
        return
    _safe_text(route_id, "/route_id")
    _safe_text(observed_at, "/observed_at")
    if type(accepted) is not bool:
        raise P1RuntimeError("P1_EXACT_TYPE_INVALID", "/accepted")
    if type(recovery) is not bool:
        raise P1RuntimeError("P1_EXACT_TYPE_INVALID", "/recovery")
    record = runtime["route_orchestrations"].get(route_id)
    if not isinstance(record, dict) or record.get("status") != "SENT":
        raise P1RuntimeError("P1_ROUTE_ORCHESTRATION_NOT_SENT", "/route_id")
    record.update(status="ACKED", acked_at=observed_at)
    latency = _latency_ms(record.get("prepared_at"), observed_at)
    runtime["metrics"]["route_latency_ms"].append(latency)
    if recovery:
        runtime["metrics"]["recovery_latency_ms"].append(
            _latency_ms(record.get("sent_at"), observed_at)
        )
    counter = "accepted_count" if accepted else "rejected_count"
    runtime["metrics"][counter] += 1


def record_review_disclosure(
    state: dict[str, Any], *, goal_id: str, review_status: str,
    result: Mapping[str, Any], evidence_paths: list[str]
) -> dict[str, Any] | None:
    """Validate and persist mandatory same-family disclosure for P1 Loops."""

    runtime = ensure_compatible(state)
    if not runtime["enabled"]:
        return None
    _safe_text(goal_id, "/goal_id")
    _safe_text(review_status, "/review_status")
    if not isinstance(result, dict):
        raise P1RuntimeError("P1_EXACT_OBJECT_INVALID", "/result")
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
    prior_returns = runtime["reviewer_returns"].get(family_id, 0)
    if type(prior_returns) is not int or prior_returns < 0:
        raise P1RuntimeError("P1_RUNTIME_STATE_INVALID", "/p1_runtime/reviewer_returns")
    verdict = item["verdict"]
    if (
        ("PASS" in review_status and verdict != "PASS")
        or ("NEEDS_REPAIR" in review_status and verdict == "PASS")
    ):
        raise P1RuntimeError(
            "P1_REVIEWER_DISCLOSURE_DECISION_MISMATCH",
            "/result/reviewer_disclosure/verdict",
        )
    if verdict == "PASS":
        if family.closure_status not in {"CONTAINED", "CLOSED"}:
            raise P1RuntimeError(
                "P1_DEFECT_FAMILY_CLOSURE_INVALID",
                "/result/reviewer_disclosure/defect_family/closure_status",
            )
        return_number = max(1, prior_returns)
    else:
        if (
            verdict == "POINT_REPAIR" and family.closure_status != "OPEN"
        ) or (
            verdict in ESCALATION_ACTIONS and family.closure_status != "ESCALATED"
        ):
            raise P1RuntimeError(
                "P1_DEFECT_FAMILY_CLOSURE_INVALID",
                "/result/reviewer_disclosure/defect_family/closure_status",
            )
        return_number = prior_returns + 1
    try:
        envelope = build_envelope(
            verdict=verdict,
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
    if verdict != "PASS":
        runtime["reviewer_returns"][family_id] = return_number
    runtime["defect_families"][family_id] = {
        "goal_id": goal_id,
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
    _safe_text(goal_id, "/goal_id")
    matches = [
        value for value in runtime["defect_families"].values()
        if value.get("goal_id") == goal_id
        and value.get("reviewer_envelope", {}).get("verdict")
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
    "authorize_supervisor", "ensure_compatible", "initial_state", "privacy_safe_export",
    "record_heartbeat", "record_review_disclosure", "record_route_acked",
    "record_route_prepared", "record_route_sent", "repair_context",
]
