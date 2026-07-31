"""Typed protocol manifest and canonical encoding for the v4 alpha slice."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping

from .generated_protocol import (
    ASSURANCE_STRENGTHS,
    CAPACITY_CONTRACT,
    CAPABILITY_NAMES,
    COMMAND_TYPES,
    DELIVERY_STATES,
    ERROR_CODES,
    EVENT_TYPES,
    MANIFEST_SHA256,
    PLAN_SOURCE_KINDS,
    PROTOCOL_VERSION,
    REFERENCE_KINDS,
    RESULT_STATES,
    SEMANTIC_PAYLOAD_SPECS,
    WRITE_CAS,
    ActorRef,
    ApplyResult,
    AuthorityGrant,
    AuthorityGrantV2,
    CapabilityRecord,
    CommandEnvelope,
    EffectAttempt,
    LoopIntakeDecision,
    LoopIntakeInput,
    LoopStartInput,
    PlanCapacityReport,
    PlanDocument,
    PlanIndex,
    PreparedLoopBundle,
    PreparedLoopManifest,
    Receipt,
    Reference,
    UserFacingError,
    UserFacingStatus,
)

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
MAX_COMMAND_BYTES = 16_384
MAX_SEMANTIC_STRING_BYTES = 4_096
MAX_COLLECTION_ITEMS = 128
MAX_RECEIPT_BYTES = 8_192
MAX_EVENTS_PER_COMMAND = 16
CREATE_LOOP_TARGET_BYTES = int(CAPACITY_CONTRACT["create_loop_target_bytes"])
CREATE_LOOP_TARGET_COLLECTION_MEMBERS = int(
    CAPACITY_CONTRACT["create_loop_target_collection_members"]
)
HOST_PROMPT_TARGET_BYTES = int(CAPACITY_CONTRACT["host_prompt_target_bytes"])
CONTENT_STORAGE_MODE = "CONTENT_ADDRESSED_V1"
EAGER_STORAGE_MODE = "EAGER_V4_0"
LEGACY_ABSENT_STORAGE_MODE = "LEGACY_ABSENT"
MALFORMED_STORAGE_MODE = "MALFORMED"
EAGER_PROTOCOL_VERSION = "4.0.0"

PROTOCOL_MANIFEST = {
    "assurance_strengths": ASSURANCE_STRENGTHS,
    "capacity_contract": CAPACITY_CONTRACT,
    "capabilities": CAPABILITY_NAMES,
    "commands": COMMAND_TYPES,
    "delivery_states": DELIVERY_STATES,
    "errors": ERROR_CODES,
    "events": EVENT_TYPES,
    "manifest_sha256": MANIFEST_SHA256,
    "protocol_version": PROTOCOL_VERSION,
    "reference_kinds": REFERENCE_KINDS,
    "result_states": RESULT_STATES,
    "semantic_payload_specs": SEMANTIC_PAYLOAD_SPECS,
    "write_cas": WRITE_CAS,
}

CONTROL_FIELDS = frozenset(
    {
        "operation_id",
        "command_type",
        "protocol_version",
        "actor_ref",
        "authority_grant_ref",
        "subject",
        "expected_loop_revision",
        "expected_subject_revisions",
        "issued_at",
        "machine_bindings",
        "request_digest",
        "handle",
        "receipt_ref",
        "timestamp",
        "version",
    }
)


class ProtocolRejection(Exception):
    """A deterministic fail-closed protocol rejection."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unknown protocol error: {code}")
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


class InjectedCrash(RuntimeError):
    """Synthetic process crash at a declared in-memory boundary."""

    def __init__(self, boundary: str) -> None:
        super().__init__(f"injected crash at {boundary}")
        self.boundary = boundary


def classify_persisted_storage_mode(snapshot: Mapping[str, Any] | None) -> str:
    """Purely select the one persisted/new-loop reducer route."""

    if snapshot is None:
        return CONTENT_STORAGE_MODE
    if not isinstance(snapshot, Mapping):
        return MALFORMED_STORAGE_MODE

    required_sections = {
        "artifacts",
        "attempts",
        "closure_assurance",
        "deliveries",
        "execution",
        "finalizations",
        "goals",
        "host_resources",
        "loop_ref",
        "loop_revision",
        "reports",
        "results",
        "reviews",
        "routes",
    }
    optional_sections = {
        "current_result_ref",
        "external_effects",
        "goal_plan",
        "policy",
        "start_authorization",
    }
    mapping_sections = required_sections - {"loop_ref", "loop_revision"}
    common_shape = (
        required_sections <= set(snapshot)
        and set(snapshot) <= required_sections | optional_sections
        and isinstance(snapshot.get("loop_ref"), str)
        and bool(snapshot["loop_ref"])
        and not isinstance(snapshot.get("loop_revision"), bool)
        and isinstance(snapshot.get("loop_revision"), int)
        and snapshot["loop_revision"] >= 1
        and all(
            isinstance(snapshot.get(section), Mapping)
            for section in mapping_sections
        )
        and all(
            section not in snapshot or isinstance(snapshot[section], Mapping)
            for section in ("external_effects", "policy", "start_authorization")
        )
        and (
            "current_result_ref" not in snapshot
            or (
                isinstance(snapshot["current_result_ref"], str)
                and bool(snapshot["current_result_ref"])
            )
        )
    )
    if not common_shape:
        return MALFORMED_STORAGE_MODE

    goals = snapshot["goals"]
    if "goal_plan" not in snapshot:
        legacy_goal_keys = {"objective_digest", "revision", "state"}
        exact_single_goal = (
            len(goals) == 1
            and all(
                isinstance(goal, Mapping)
                and set(goal) == legacy_goal_keys
                for goal in goals.values()
            )
        )
        return (
            LEGACY_ABSENT_STORAGE_MODE
            if exact_single_goal
            else MALFORMED_STORAGE_MODE
        )

    plan = snapshot["goal_plan"]
    if not isinstance(plan, Mapping):
        return MALFORMED_STORAGE_MODE
    mode = plan.get("storage_mode", LEGACY_ABSENT_STORAGE_MODE)

    legacy_plan_keys = {
        "active_goal_ref",
        "envelope_digest",
        "max_roadmap_revisions",
        "mode",
        "ordered_goal_refs",
        "plan_digest",
        "revision",
    }
    content_plan_discriminants = {
        "active_goal_ref",
        "active_index",
        "goal_count",
        "ordered_goal_ids",
        "ordered_goal_slice_digests",
        "plan_digest",
        "plan_index_digest",
        "storage_mode",
    }
    legacy_goal_keys = {
        "chain_refs",
        "depends_on",
        "objective",
        "objective_digest",
        "order",
        "revision",
        "state",
    }
    content_goal_discriminants = {
        "chain_refs",
        "depends_on",
        "goal_id",
        "goal_slice_digest",
        "objective_digest",
        "order",
        "revision",
        "state",
    }

    if mode == CONTENT_STORAGE_MODE:
        ordered_ids = plan.get("ordered_goal_ids")
        ordered_digests = plan.get("ordered_goal_slice_digests")
        goal_count = plan.get("goal_count")
        active_index = plan.get("active_index")
        if (
            not content_plan_discriminants <= set(plan)
            or {"ordered_goal_refs", "envelope_digest"} & set(plan)
            or not isinstance(ordered_ids, (list, tuple))
            or not isinstance(ordered_digests, (list, tuple))
            or isinstance(goal_count, bool)
            or not isinstance(goal_count, int)
            or isinstance(active_index, bool)
            or not isinstance(active_index, int)
            or goal_count < 1
            or not 0 <= active_index < goal_count
            or len(ordered_ids) != goal_count
            or len(ordered_digests) != goal_count
            or not all(isinstance(value, str) and value for value in ordered_ids)
            or not all(
                isinstance(value, str) and value for value in ordered_digests
            )
            or len(set(ordered_ids)) != goal_count
            or len(goals) != active_index + 1
        ):
            return MALFORMED_STORAGE_MODE

        by_order: dict[int, tuple[str, Mapping[str, Any]]] = {}
        for goal_ref, goal in goals.items():
            chain = goal.get("chain_refs") if isinstance(goal, Mapping) else None
            order = goal.get("order") if isinstance(goal, Mapping) else None
            if (
                not isinstance(goal, Mapping)
                or not content_goal_discriminants <= set(goal)
                or {"ordered_goal_refs", "envelope_digest"} & set(goal)
                or isinstance(order, bool)
                or not isinstance(order, int)
                or not isinstance(chain, Mapping)
                or chain.get("goal_ref") != goal_ref
                or not isinstance(goal.get("goal_id"), str)
                or not isinstance(goal.get("goal_slice_digest"), str)
                or order in by_order
            ):
                return MALFORMED_STORAGE_MODE
            by_order[order] = (str(goal_ref), goal)
        if set(by_order) != set(range(active_index + 1)):
            return MALFORMED_STORAGE_MODE
        for index in range(active_index + 1):
            _, goal = by_order[index]
            if (
                goal["goal_id"] != ordered_ids[index]
                or goal["goal_slice_digest"] != ordered_digests[index]
            ):
                return MALFORMED_STORAGE_MODE
        active_goal_ref, _ = by_order[active_index]
        return (
            CONTENT_STORAGE_MODE
            if plan.get("active_goal_ref") == active_goal_ref
            else MALFORMED_STORAGE_MODE
        )

    if mode not in (LEGACY_ABSENT_STORAGE_MODE, EAGER_STORAGE_MODE):
        return MALFORMED_STORAGE_MODE
    expected_plan_keys = (
        legacy_plan_keys
        if "storage_mode" not in plan
        else legacy_plan_keys | {"storage_mode"}
    )
    ordered_refs = plan.get("ordered_goal_refs")
    legacy_only_discriminants = {
        "envelope_digest",
        "ordered_goal_refs",
    }
    content_only_discriminants = {
        "active_index",
        "goal_count",
        "ordered_goal_ids",
        "ordered_goal_slice_digests",
        "plan_index_digest",
    }
    if (
        set(plan) != expected_plan_keys
        or not legacy_only_discriminants <= set(plan)
        or content_only_discriminants & set(plan)
        or not isinstance(ordered_refs, (list, tuple))
        or len(ordered_refs) < 2
        or not all(
            isinstance(reference, str) and reference
            for reference in ordered_refs
        )
        or len(set(ordered_refs)) != len(ordered_refs)
        or set(ordered_refs) != set(goals)
        or plan.get("active_goal_ref") not in ordered_refs
    ):
        return MALFORMED_STORAGE_MODE
    for index, goal_ref in enumerate(ordered_refs):
        goal = goals.get(goal_ref)
        chain = goal.get("chain_refs") if isinstance(goal, Mapping) else None
        if (
            not isinstance(goal, Mapping)
            or set(goal) != legacy_goal_keys
            or {"goal_id", "goal_slice_digest"} & set(goal)
            or goal.get("order") != index
            or not isinstance(chain, Mapping)
            or chain.get("goal_ref") != goal_ref
        ):
            return MALFORMED_STORAGE_MODE
    return EAGER_STORAGE_MODE


def _validate_value(value: Any) -> None:
    if value is None or isinstance(value, (bool, str)):
        if isinstance(value, str):
            try:
                encoded = value.encode("utf-8", "strict")
            except UnicodeEncodeError as exc:
                raise ProtocolRejection("INVALID_UTF8", "unpaired surrogate") from exc
            if len(encoded) > MAX_SEMANTIC_STRING_BYTES:
                raise ProtocolRejection(
                    "RESOURCE_LIMIT_EXCEEDED", "string exceeds byte limit"
                )
        return
    if isinstance(value, int):
        if value < INT64_MIN or value > INT64_MAX:
            raise ProtocolRejection("RESOURCE_LIMIT_EXCEEDED", "integer out of int64")
        return
    if isinstance(value, float):
        raise ProtocolRejection("INVALID_COMMAND", "floating-point numbers forbidden")
    if isinstance(value, list) or isinstance(value, tuple):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise ProtocolRejection(
                "RESOURCE_LIMIT_EXCEEDED", "collection exceeds item limit"
            )
        for item in value:
            _validate_value(item)
        return
    if isinstance(value, Mapping):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise ProtocolRejection(
                "RESOURCE_LIMIT_EXCEEDED", "object exceeds member limit"
            )
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProtocolRejection("INVALID_COMMAND", "object key is not string")
            _validate_value(key)
            _validate_value(item)
        return
    raise ProtocolRejection("INVALID_COMMAND", f"unsupported value type {type(value)!r}")


def canonical_bytes(value: Any) -> bytes:
    _validate_value(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def parse_json_bytes(raw: bytes) -> Any:
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise ProtocolRejection("INVALID_UTF8", "input is not strict UTF-8") from exc

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ProtocolRejection("INVALID_COMMAND", "duplicate object key")
            result[key] = value
        return result

    def integer(token: str) -> int:
        if token == "-0":
            raise ProtocolRejection("INVALID_COMMAND", "negative zero forbidden")
        value = int(token)
        if value < INT64_MIN or value > INT64_MAX:
            raise ProtocolRejection("RESOURCE_LIMIT_EXCEEDED", "integer out of int64")
        return value

    def floating(_: str) -> Any:
        raise ProtocolRejection("INVALID_COMMAND", "decimal/exponent forbidden")

    def constant(_: str) -> Any:
        raise ProtocolRejection("INVALID_COMMAND", "non-finite number forbidden")

    try:
        value = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_int=integer,
            parse_float=floating,
            parse_constant=constant,
        )
    except ProtocolRejection:
        raise
    except (ValueError, json.JSONDecodeError) as exc:
        raise ProtocolRejection("INVALID_COMMAND", "malformed JSON") from exc
    _validate_value(value)
    return value


def domain_digest(domain: str, value: Any) -> str:
    return hashlib.sha256(domain.encode("utf-8") + canonical_bytes(value)).hexdigest()


def result_payload_schema() -> dict[str, Any]:
    """Derive the one Host final-result schema from the typed manifest."""

    external = SEMANTIC_PAYLOAD_SPECS["StageExternalResult"]["semantic_payload"]
    staged = SEMANTIC_PAYLOAD_SPECS["StageResult"]["semantic_payload"]
    if external != staged:
        raise RuntimeError("StageExternalResult and StageResult contract drift")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "properties": {name: dict(specification) for name, specification in external.items()},
        "required": sorted(external),
        "type": "object",
    }


def validate_result_payload(value: Any) -> dict[str, str]:
    """Validate one closed semantic result without a text-marker fallback."""

    specification = SEMANTIC_PAYLOAD_SPECS["StageExternalResult"]["semantic_payload"]
    if not isinstance(value, Mapping) or set(value) != set(specification):
        raise ProtocolRejection("INVALID_COMMAND", "result payload shape drift")
    outcome = value["outcome"]
    summary = value["summary"]
    if not isinstance(outcome, str) or outcome not in specification["outcome"]["enum"]:
        raise ProtocolRejection("INVALID_COMMAND", "result outcome enum drift")
    if not isinstance(summary, str):
        raise ProtocolRejection("INVALID_COMMAND", "result summary must be string")
    try:
        encoded = summary.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise ProtocolRejection("INVALID_UTF8", "result summary is not UTF-8") from exc
    summary_spec = specification["summary"]
    if (
        not summary.strip()
        or len(summary) < summary_spec["minLength"]
        or len(summary) > summary_spec["maxLength"]
        or len(encoded) > MAX_SEMANTIC_STRING_BYTES
    ):
        raise ProtocolRejection("RESOURCE_LIMIT_EXCEEDED", "result summary bound")
    return {"outcome": outcome, "summary": summary}


def parse_result_payload(raw: bytes) -> dict[str, str]:
    return validate_result_payload(parse_json_bytes(raw))


def raw_domain_digest(domain: str, raw: bytes) -> str:
    return hashlib.sha256(domain.encode("utf-8") + raw).hexdigest()


_PLAN_REFERENCE_PREFIXES = {
    "ArtifactRef": "artifact-",
    "AttemptRef": "attempt-",
    "ExternalEffectRef": "external-effect-",
    "GoalRef": "goal-",
    "HostResourceRef": "host-target-",
    "ReportRef": "report-",
    "ResultRef": "result-",
    "ReviewRef": "review-",
}


def derive_plan_ref(
    loop_ref: str,
    plan_identity: str,
    goal_id: str,
    slice_digest: str,
    reference_kind: str,
) -> str:
    try:
        prefix = _PLAN_REFERENCE_PREFIXES[reference_kind]
    except KeyError as exc:
        raise ValueError("unsupported plan-derived reference kind") from exc
    suffix = raw_domain_digest(
        "loopskill-plan-derived-ref-v1\n",
        canonical_bytes(
            {
                "goal_id": goal_id,
                "goal_slice_digest": slice_digest,
                "loop_ref": loop_ref,
                "plan_digest": plan_identity,
                "reference_kind": reference_kind,
            }
        ),
    )[:24]
    return prefix + suffix


def derive_loop_plan_ref(
    loop_ref: str, plan_identity: str, reference_kind: str
) -> str:
    if reference_kind != "FinalizationRef":
        raise ValueError("unsupported loop-derived reference kind")
    return "finalization-" + raw_domain_digest(
        "loopskill-plan-loop-ref-v1\n",
        canonical_bytes(
            {
                "loop_ref": loop_ref,
                "plan_digest": plan_identity,
                "reference_kind": reference_kind,
            }
        ),
    )[:24]


def goal_chain(
    loop_ref: str,
    plan_identity: str,
    goal_id: str,
    slice_digest: str,
) -> dict[str, str]:
    result = {
        "artifact_ref": derive_plan_ref(
            loop_ref, plan_identity, goal_id, slice_digest, "ArtifactRef"
        ),
        "attempt_ref": derive_plan_ref(
            loop_ref, plan_identity, goal_id, slice_digest, "AttemptRef"
        ),
        "external_effect_ref": derive_plan_ref(
            loop_ref, plan_identity, goal_id, slice_digest, "ExternalEffectRef"
        ),
        "goal_ref": derive_plan_ref(
            loop_ref, plan_identity, goal_id, slice_digest, "GoalRef"
        ),
        "host_resource_ref": derive_plan_ref(
            loop_ref, plan_identity, goal_id, slice_digest, "HostResourceRef"
        ),
        "report_ref": derive_plan_ref(
            loop_ref, plan_identity, goal_id, slice_digest, "ReportRef"
        ),
        "result_ref": derive_plan_ref(
            loop_ref, plan_identity, goal_id, slice_digest, "ResultRef"
        ),
        "review_ref": derive_plan_ref(
            loop_ref, plan_identity, goal_id, slice_digest, "ReviewRef"
        ),
    }
    identity = {
        "goal_id": goal_id,
        "goal_slice_digest": slice_digest,
        "loop_ref": loop_ref,
        "plan_digest": plan_identity,
    }
    result["provider_key"] = "effect-" + raw_domain_digest(
        "loopskill-plan-provider-key-v1\n", canonical_bytes(identity)
    )[:24]
    result["provider_target"] = "codex-bootstrap-" + raw_domain_digest(
        "loopskill-plan-provider-target-v1\n", canonical_bytes(identity)
    )[:24]
    return result


def snapshot_digest(snapshot: Mapping[str, Any]) -> str:
    return domain_digest("loopskill-snapshot-v1\n", snapshot)


def _find_control_injection(value: Any, path: str = "semantic_payload") -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in CONTROL_FIELDS:
                return f"{path}.{key}"
            found = _find_control_injection(item, f"{path}.{key}")
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found = _find_control_injection(item, f"{path}[{index}]")
            if found:
                return found
    return None


def command_without_digest(command: CommandEnvelope) -> dict[str, Any]:
    return {
        "actor_ref": command.actor_ref,
        "authority_grant_ref": command.authority_grant_ref,
        "command_type": command.command_type,
        "expected_loop_revision": command.expected_loop_revision,
        "expected_subject_revisions": dict(command.expected_subject_revisions),
        "issued_at": command.issued_at,
        "machine_bindings": {
            key: dict(value) for key, value in command.machine_bindings.items()
        },
        "operation_id": command.operation_id,
        "protocol_version": command.protocol_version,
        "semantic_payload": dict(command.semantic_payload),
        "subject": dict(command.subject),
    }


def command_digest(command: CommandEnvelope) -> str:
    return domain_digest("loopskill-command-v1\n", command_without_digest(command))


def authority_grant_digest(grant: AuthorityGrant | AuthorityGrantV2) -> str:
    value = dict(grant.__dict__)
    value.pop("canonical_digest")
    domain = (
        "loopskill-authority-grant-v2\n"
        if isinstance(grant, AuthorityGrantV2)
        else "loopskill-authority-grant-v1\n"
    )
    return domain_digest(domain, value)


def validate_receipt_size(receipt: Receipt) -> None:
    if len(canonical_bytes(receipt.__dict__)) > MAX_RECEIPT_BYTES:
        raise ProtocolRejection("RESOURCE_LIMIT_EXCEEDED", "receipt exceeds byte limit")


def validate_event_type(event_type: str) -> None:
    if event_type not in EVENT_TYPES:
        raise ProtocolRejection("INVALID_COMMAND", "unknown event type")


def validate_reference(reference: Reference) -> None:
    if reference.kind not in REFERENCE_KINDS:
        raise ProtocolRejection("WRONG_REFERENCE_KIND", reference.kind)
    if not reference.value or not reference.loop_ref:
        raise ProtocolRejection("FOREIGN_REFERENCE", "empty reference identity")


def validate_capability_record(capability: CapabilityRecord) -> None:
    if capability.capability not in CAPABILITY_NAMES:
        raise ProtocolRejection("CAPABILITY_UNAVAILABLE", "unknown capability")
    if capability.availability not in {"AVAILABLE", "UNAVAILABLE", "UNVERIFIABLE"}:
        raise ProtocolRejection("CAPABILITY_UNVERIFIABLE", "invalid availability")
    if capability.assurance not in ASSURANCE_STRENGTHS:
        raise ProtocolRejection("CAPABILITY_UNVERIFIABLE", "invalid assurance")


def validate_command(
    command: CommandEnvelope,
    *,
    expected_protocol_version: str = PROTOCOL_VERSION,
) -> None:
    if command.protocol_version != expected_protocol_version:
        raise ProtocolRejection(
            "UNSUPPORTED_PROTOCOL_VERSION", command.protocol_version
        )
    if command.command_type not in COMMAND_TYPES:
        raise ProtocolRejection("INVALID_COMMAND", "unknown command_type")
    if not command.operation_id or len(command.operation_id.encode("utf-8")) > 128:
        raise ProtocolRejection("INVALID_COMMAND", "invalid operation_id")
    if set(command.subject) != {"loop_ref", "subject_kind", "subject_ref"}:
        raise ProtocolRejection("INVALID_COMMAND", "subject shape is not closed")
    if command.subject["subject_kind"] not in REFERENCE_KINDS:
        raise ProtocolRejection("WRONG_REFERENCE_KIND", "unknown subject kind")
    if not isinstance(command.expected_loop_revision, int) or command.expected_loop_revision < 0:
        raise ProtocolRejection("INVALID_COMMAND", "invalid loop revision")
    if any(
        not isinstance(key, str) or not isinstance(value, int) or value < 0
        for key, value in command.expected_subject_revisions.items()
    ):
        raise ProtocolRejection("INVALID_COMMAND", "invalid subject revision map")
    if set(command.machine_bindings) != {
        "resolved_refs",
        "allocate_refs",
        "receipt_refs",
    }:
        raise ProtocolRejection("INVALID_COMMAND", "machine_bindings is not closed")
    if any(
        not isinstance(key, str) or not isinstance(value, str)
        for group in command.machine_bindings.values()
        for key, value in group.items()
    ):
        raise ProtocolRejection("INVALID_COMMAND", "invalid machine binding")
    injection = _find_control_injection(command.semantic_payload)
    if injection:
        raise ProtocolRejection("CONTROL_FIELD_INJECTION", injection)
    payload_spec = SEMANTIC_PAYLOAD_SPECS[command.command_type]["semantic_payload"]
    required = {
        name
        for name, specification in payload_spec.items()
        if specification.get("required", True)
    }
    if not required <= set(command.semantic_payload) or not set(
        command.semantic_payload
    ) <= set(payload_spec):
        raise ProtocolRejection("INVALID_COMMAND", "semantic payload shape drift")
    for name, value in command.semantic_payload.items():
        specification = payload_spec[name]
        if specification["type"] == "string" and not isinstance(value, str):
            raise ProtocolRejection("INVALID_COMMAND", f"{name} must be string")
        if specification["type"] == "integer" and (
            isinstance(value, bool) or not isinstance(value, int)
        ):
            raise ProtocolRejection("INVALID_COMMAND", f"{name} must be integer")
        if specification["type"] == "array" and (
            not isinstance(value, (list, tuple))
            or not all(isinstance(item, str) for item in value)
        ):
            raise ProtocolRejection("INVALID_COMMAND", f"{name} must be a string array")
        if "enum" in specification and value not in specification["enum"]:
            raise ProtocolRejection("INVALID_COMMAND", f"{name} enum drift")
        if specification["type"] == "string" and "minLength" in specification:
            if len(value) < specification["minLength"] or not value.strip():
                raise ProtocolRejection("INVALID_COMMAND", f"{name} is empty")
        if specification["type"] == "string" and "maxLength" in specification:
            if len(value) > specification["maxLength"]:
                raise ProtocolRejection("RESOURCE_LIMIT_EXCEEDED", f"{name} is oversized")
    raw = canonical_bytes(command_without_digest(command))
    if len(raw) > MAX_COMMAND_BYTES:
        raise ProtocolRejection("RESOURCE_LIMIT_EXCEEDED", "command exceeds byte limit")
    if command.request_digest != command_digest(command):
        raise ProtocolRejection("INVALID_COMMAND", "request digest mismatch")


def build_command(
    *,
    operation_id: str,
    command_type: str,
    actor_ref: str,
    authority_grant_ref: str,
    subject: Mapping[str, Any],
    expected_loop_revision: int,
    expected_subject_revisions: Mapping[str, int],
    issued_at: str,
    machine_bindings: Mapping[str, Mapping[str, str]],
    semantic_payload: Mapping[str, Any],
    persisted_storage_mode: str = CONTENT_STORAGE_MODE,
) -> CommandEnvelope:
    if persisted_storage_mode == CONTENT_STORAGE_MODE:
        protocol_version = PROTOCOL_VERSION
    elif persisted_storage_mode in {
        EAGER_STORAGE_MODE,
        LEGACY_ABSENT_STORAGE_MODE,
    }:
        protocol_version = EAGER_PROTOCOL_VERSION
    else:
        raise ProtocolRejection(
            "INTERNAL_INVARIANT_VIOLATION",
            "persisted storage mode is malformed",
        )
    provisional = CommandEnvelope(
        operation_id=operation_id,
        command_type=command_type,
        protocol_version=protocol_version,
        actor_ref=actor_ref,
        authority_grant_ref=authority_grant_ref,
        subject=dict(subject),
        expected_loop_revision=expected_loop_revision,
        expected_subject_revisions=dict(expected_subject_revisions),
        issued_at=issued_at,
        machine_bindings={key: dict(value) for key, value in machine_bindings.items()},
        semantic_payload=dict(semantic_payload),
        request_digest="",
    )
    return CommandEnvelope(
        **{
            **provisional.__dict__,
            "request_digest": command_digest(provisional),
        }
    )


def with_command_change(
    command: CommandEnvelope,
    change: Callable[[dict[str, Any]], None],
) -> CommandEnvelope:
    values = dict(command.__dict__)
    change(values)
    values["request_digest"] = ""
    provisional = CommandEnvelope(**values)
    values["request_digest"] = command_digest(provisional)
    return CommandEnvelope(**values)
