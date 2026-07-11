"""Crash-consistent deterministic runtime for Adaptive loop state.

The runtime owns only the local control-plane files under ``.codex-loop``.  It
records external intents in outboxes but never calls Codex App or other
external APIs.
"""

from __future__ import annotations

import contextlib
import copy
import fcntl
import hashlib
import html
import importlib
import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator, Mapping


STATE_BEGIN = "STATE_JSON_BEGIN"
STATE_END = "STATE_JSON_END"
SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
DIGEST_RE = re.compile(r"sha256:[a-f0-9]{64}\Z")
INTENDED_TRANSITION = "ROUTE_ONE_TRANSITION"
PAYLOAD_DIGEST_FIELD = "dispatch_payload_digest"
PAYLOAD_DIGEST_PLACEHOLDER = "PAYLOAD_DIGEST_PLACEHOLDER"
DISPATCH_ENVELOPE_TYPES = (
    "WORKER_DISPATCH",
    "REVIEW_DISPATCH",
    "LOCAL_VERIFY_DISPATCH",
)
DISPATCH_PAYLOAD_KEYS = {
    "WORKER_DISPATCH": {
        "acceptance_criteria",
        "allowed_write_scope",
        "artifact_identity_rule",
        "canonical_state_path",
        "canonical_state_snapshot",
        "claim_boundary",
        "depends_on",
        "dispatch_id",
        "dispatch_lease_claim",
        "dispatch_payload_digest",
        "dispatch_when",
        "evidence_layer",
        "forbidden",
        "goal_definition_digest",
        "goal_id",
        "idempotency_rule",
        "milestone_id",
        "objective",
        "parent_dispatch_id",
        "phase",
        "phase_permissions",
        "prompt_injection_boundary",
        "repo_mode",
        "repo_root",
        "required_report_fields",
        "review_gate",
        "roadmap_version",
        "source_artifacts",
        "state_rule",
        "stop_conditions",
        "target_branch",
        "target_thread_id",
        "validation_commands",
        "worker_permission",
        "worker_role",
        "worker_role_kind",
    },
    "REVIEW_DISPATCH": {
        "artifact_identity",
        "canonical_state_snapshot",
        "code_review_id",
        "decision_contract",
        "dispatch_lease_claim",
        "dispatch_payload_digest",
        "evidence_refs",
        "goal_id",
        "local_verification_ack_identity",
        "milestone_id",
        "review_dispatch_id",
        "review_kind",
        "roadmap_audit_id",
        "roadmap_version",
        "source_artifact_digest",
        "source_worker_dispatch_id",
        "source_worker_report_digest",
        "target_thread_id",
    },
    "LOCAL_VERIFY_DISPATCH": {
        "artifact_identity",
        "canonical_state_snapshot",
        "code_review_id",
        "dispatch_lease_claim",
        "dispatch_payload_digest",
        "evidence_capture_rules",
        "expected_result",
        "goal_id",
        "local_dispatch_id",
        "milestone_id",
        "prerequisites",
        "privacy_boundary",
        "roadmap_version",
        "source_artifact_digest",
        "source_worker_dispatch_id",
        "steps",
        "stop_conditions",
        "target_thread_id",
        "verification_id",
    },
}
PHASE_PERMISSION_FIELDS = (
    "git_init",
    "branch_create",
    "local_commit",
    "stage",
    "pr_create",
    "push",
    "merge",
    "deploy",
    "source_promotion",
    "gitignore_hygiene",
    "external_write",
)

BOOTSTRAP_ROLE_TO_FORMAL_ROLE = {
    "implementation": "WORKER",
    "triage": "WORKER",
    "explorer": "WORKER",
    "code_reviewer": "REVIEWER",
    "local_verifier": "LOCAL_VERIFIER",
}

OUTBOX_FIELDS = {
    "DISPATCH": "dispatch_outbox",
    "AUTOMATION": "automation_outbox",
    "GOAL": "controller_goal_outbox",
    "THREAD": "thread_creation_outbox",
    "ASSURANCE": "assurance_dispatch_outbox",
    "LOCAL": "local_verification_outbox",
    "DELEGATION": "delegation_ledger",
}
ACTIVE_OUTBOX_STATUSES = {"PREPARED", "SENT"}
REVIEW_DECISIONS = {
    "CODE_REVIEW": {
        "REVIEW_PASS",
        "REVIEW_PASS_WITH_LIMITATION",
        "REVIEW_NEEDS_REPAIR",
        "REVIEW_ARTIFACT_UNAVAILABLE",
    },
    "ROADMAP_AUDIT": {
        "ROADMAP_AUDIT_PASS",
        "ROADMAP_CHANGE_PROPOSED",
        "ROADMAP_AUDIT_PASS_FINAL_CANDIDATE",
        "ROADMAP_AUDIT_NEEDS_REPAIR",
    },
    "FINAL_AUDIT": {
        "FINAL_REVIEW_PASS",
        "FINAL_REVIEW_PASS_WITH_LIMITATION",
        "FINAL_REVIEW_NEEDS_REPAIR",
    },
}
CODE_REVIEW_PASS = {"REVIEW_PASS", "REVIEW_PASS_WITH_LIMITATION"}
ROADMAP_REVISION_PASS = {"ROADMAP_AUDIT_PASS"}
FINAL_PASS = {"FINAL_REVIEW_PASS", "FINAL_REVIEW_PASS_WITH_LIMITATION"}
ROADMAP_OPERATION_TYPES = {
    "ADD_MILESTONE",
    "UPDATE_MILESTONE",
    "REORDER_FUTURE_MILESTONES",
    "SUPERSEDE_MILESTONE",
}
ROADMAP_PROPOSAL_KEYS = {
    "proposal_id",
    "roadmap_audit_dispatch_id",
    "base_roadmap_version",
    "operations",
    "milestones_digest",
    "goal_queue_digest",
    "goal_definition_registry_digest",
    "authorization_envelope_digest",
    "estimate_digest",
    "next_goal_id",
    "reason_code",
    "within_authorized_envelope",
}

PERSISTENT_STAGES = (
    "PREPARED_JOURNAL_TEMP_FSYNCED",
    "PREPARED_JOURNAL_REPLACED",
    "PREPARED_JOURNAL_DIR_FSYNCED",
    "STATE_TEMP_FSYNCED",
    "STATE_REPLACED",
    "STATE_DIR_FSYNCED",
    "GOALS_TEMP_FSYNCED",
    "GOALS_REPLACED",
    "GOALS_DIR_FSYNCED",
    "DASHBOARD_TEMP_FSYNCED",
    "DASHBOARD_REPLACED",
    "DASHBOARD_DIR_FSYNCED",
    "EVENT_APPENDED_FSYNCED",
    "EVENT_DIR_FSYNCED",
    "APPLIED_JOURNAL_TEMP_FSYNCED",
    "APPLIED_JOURNAL_REPLACED",
    "APPLIED_JOURNAL_DIR_FSYNCED",
)
ARTIFACT_STAGES = (
    "ARTIFACT_TEMP_FSYNCED",
    "ARTIFACT_REPLACED",
    "ARTIFACT_DIR_FSYNCED",
)
CRASH_STAGES = PERSISTENT_STAGES + ARTIFACT_STAGES

_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


class InjectedCrash(RuntimeError):
    """Raised after a selected durable-write stage for deterministic tests."""

    def __init__(self, stage: str):
        super().__init__(stage)
        self.stage = stage


class RuntimeRejection(Exception):
    def __init__(
        self,
        code: str,
        path: str = "/",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.path = path
        self.details = dict(details or {})


def _import_jsonschema() -> Any:
    return importlib.import_module("jsonschema")


def _canonical_json(value: Any, *, indent: int | None = None) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":") if indent is None else None,
        indent=indent,
    )


def _digest(value: Any) -> str:
    payload = _canonical_json(value).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _bytes_digest(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _goal_definition_digest(definition: Mapping[str, Any]) -> str:
    payload = {
        key: copy.deepcopy(value)
        for key, value in definition.items()
        if key != "payload_template_digest"
    }
    try:
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RuntimeRejection(
            "GOAL_DEFINITION_JSON_INVALID", "/goal_definition_registry"
        ) from exc
    return f"sha256:{hashlib.sha256(serialized).hexdigest()}"


def goal_definition_payload_digest(definition: Mapping[str, Any]) -> str:
    """Return the generator-compatible digest for one closed Goal definition."""

    return _goal_definition_digest(definition)


def _strict_json_loads(payload: str, *, code: str, path: str) -> Any:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise RuntimeRejection(code, path, {"reason": "DUPLICATE_JSON_KEY", "key": key})
            result[key] = value
        return result

    def no_non_finite(value: str) -> Any:
        raise RuntimeRejection(
            code,
            path,
            {"reason": "NON_FINITE_JSON_NUMBER", "value": value},
        )

    try:
        return json.loads(
            payload,
            object_pairs_hook=no_duplicates,
            parse_constant=no_non_finite,
        )
    except RuntimeRejection:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RuntimeRejection(
            code,
            path,
            {"reason": "INVALID_JSON", "error_type": type(exc).__name__},
        ) from exc


def _dispatch_payload_text(envelope_type: str, payload: Mapping[str, Any]) -> str:
    if envelope_type not in DISPATCH_ENVELOPE_TYPES:
        raise RuntimeRejection(
            "DISPATCH_ENVELOPE_TYPE_INVALID",
            "/envelope_type",
            {"allowed": list(DISPATCH_ENVELOPE_TYPES)},
        )
    try:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeRejection(
            "DISPATCH_PAYLOAD_JSON_INVALID",
            "/payload",
            {"error_type": type(exc).__name__},
        ) from exc
    return f"{envelope_type}\n{body}"


def _dispatch_payload_rejection(code: str, field: str, details: Any = None) -> None:
    raise RuntimeRejection(code, f"/payload/{field}", details)


def _require_safe_dispatch_id(payload: Mapping[str, Any], field: str, *, nullable: bool = False) -> None:
    value = payload.get(field)
    if nullable and value is None:
        return
    if not isinstance(value, str) or SAFE_ID_RE.fullmatch(value) is None:
        _dispatch_payload_rejection("DISPATCH_PAYLOAD_FIELD_INVALID", field)


def _require_dispatch_string_list(payload: Mapping[str, Any], field: str) -> None:
    value = payload.get(field)
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        _dispatch_payload_rejection("DISPATCH_PAYLOAD_FIELD_INVALID", field)


def _require_dispatch_string(payload: Mapping[str, Any], field: str) -> None:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        _dispatch_payload_rejection("DISPATCH_PAYLOAD_FIELD_INVALID", field)


def _validate_dispatch_payload_shape(envelope_type: str, payload: Mapping[str, Any]) -> None:
    required = DISPATCH_PAYLOAD_KEYS.get(envelope_type)
    if required is None:
        raise RuntimeRejection(
            "DISPATCH_ENVELOPE_TYPE_INVALID",
            "/envelope_type",
            {"allowed": list(DISPATCH_ENVELOPE_TYPES)},
        )
    if set(payload) != required:
        raise RuntimeRejection(
            "DISPATCH_PAYLOAD_SCHEMA_INVALID",
            "/payload",
            {
                "missing": sorted(required.difference(payload)),
                "unexpected": sorted(set(payload).difference(required)),
            },
        )
    digest_value = payload.get(PAYLOAD_DIGEST_FIELD)
    if digest_value != PAYLOAD_DIGEST_PLACEHOLDER and (
        not isinstance(digest_value, str) or DIGEST_RE.fullmatch(digest_value) is None
    ):
        _dispatch_payload_rejection(
            "DISPATCH_PAYLOAD_DIGEST_INVALID", PAYLOAD_DIGEST_FIELD
        )

    def reject_unresolved(value: Any, path: str) -> None:
        if isinstance(value, str) and "MATERIALIZE_" in value:
            raise RuntimeRejection(
                "DISPATCH_PAYLOAD_UNRESOLVED_TOKEN",
                path,
            )
        if isinstance(value, dict):
            for key, child in value.items():
                reject_unresolved(child, f"{path}/{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                reject_unresolved(child, f"{path}/{index}")

    reject_unresolved(payload, "/payload")
    for field in ("goal_id", "milestone_id", "target_thread_id"):
        _require_safe_dispatch_id(payload, field)
    roadmap_version = payload.get("roadmap_version")
    if isinstance(roadmap_version, bool) or not isinstance(roadmap_version, int) or roadmap_version < 1:
        _dispatch_payload_rejection("DISPATCH_PAYLOAD_FIELD_INVALID", "roadmap_version")
    claim = payload.get("dispatch_lease_claim")
    claim_keys = {
        "lease_epoch",
        "lease_id",
        "routing_turn_id",
        "owner_kind",
        "owner_identity",
        "intended_transition",
    }
    if not isinstance(claim, dict) or set(claim) != claim_keys:
        _dispatch_payload_rejection("DISPATCH_PAYLOAD_LEASE_INVALID", "dispatch_lease_claim")
    if (
        isinstance(claim["lease_epoch"], bool)
        or not isinstance(claim["lease_epoch"], int)
        or claim["lease_epoch"] < 1
        or claim["owner_kind"] not in {"GOAL_TURN", "HEARTBEAT"}
        or claim["intended_transition"] != INTENDED_TRANSITION
    ):
        _dispatch_payload_rejection("DISPATCH_PAYLOAD_LEASE_INVALID", "dispatch_lease_claim")
    for field in ("lease_id", "routing_turn_id", "owner_identity"):
        if not isinstance(claim[field], str) or SAFE_ID_RE.fullmatch(claim[field]) is None:
            _dispatch_payload_rejection("DISPATCH_PAYLOAD_LEASE_INVALID", "dispatch_lease_claim")
    snapshot = payload.get("canonical_state_snapshot")
    snapshot_keys = {
        "loop_id",
        "state_version",
        "roadmap_version",
        "active_milestone_id",
        "controller_lease",
    }
    if not isinstance(snapshot, dict) or set(snapshot) != snapshot_keys:
        _dispatch_payload_rejection("DISPATCH_SNAPSHOT_SCHEMA_INVALID", "canonical_state_snapshot")
    snapshot_lease = snapshot.get("controller_lease")
    lease_state_keys = {
        "claim",
        "routing_turn_id",
        "acquired_at",
        "expires_at",
        "route_action",
    }
    if (
        not isinstance(snapshot["loop_id"], str)
        or SAFE_ID_RE.fullmatch(snapshot["loop_id"]) is None
        or isinstance(snapshot["state_version"], bool)
        or not isinstance(snapshot["state_version"], int)
        or snapshot["state_version"] < 1
        or snapshot["roadmap_version"] != roadmap_version
        or snapshot["active_milestone_id"] != payload["milestone_id"]
        or not isinstance(snapshot_lease, dict)
        or set(snapshot_lease) != lease_state_keys
        or snapshot_lease["claim"] != claim
        or snapshot_lease["routing_turn_id"] != claim["routing_turn_id"]
        or snapshot_lease["route_action"] is not None
    ):
        _dispatch_payload_rejection("DISPATCH_SNAPSHOT_IDENTITY_INVALID", "canonical_state_snapshot")
    _parse_time(
        snapshot_lease["acquired_at"],
        "/payload/canonical_state_snapshot/controller_lease/acquired_at",
    )
    _parse_time(
        snapshot_lease["expires_at"],
        "/payload/canonical_state_snapshot/controller_lease/expires_at",
    )
    if envelope_type == "WORKER_DISPATCH":
        _require_safe_dispatch_id(payload, "dispatch_id")
        _require_safe_dispatch_id(payload, "parent_dispatch_id", nullable=True)
        if not isinstance(payload["goal_definition_digest"], str) or DIGEST_RE.fullmatch(
            payload["goal_definition_digest"]
        ) is None:
            _dispatch_payload_rejection("DISPATCH_PAYLOAD_FIELD_INVALID", "goal_definition_digest")
        if payload["worker_permission"] not in {"read_only", "workspace_write"}:
            _dispatch_payload_rejection("DISPATCH_PAYLOAD_FIELD_INVALID", "worker_permission")
        if payload["worker_role_kind"] not in {"implementation", "triage", "explorer"}:
            _dispatch_payload_rejection("DISPATCH_PAYLOAD_FIELD_INVALID", "worker_role_kind")
        if payload["repo_mode"] not in {"existing_git", "new_git", "non_git"}:
            _dispatch_payload_rejection("DISPATCH_PAYLOAD_FIELD_INVALID", "repo_mode")
        permissions = payload["phase_permissions"]
        if (
            not isinstance(permissions, dict)
            or set(permissions) != set(PHASE_PERMISSION_FIELDS)
            or any(not isinstance(value, bool) for value in permissions.values())
        ):
            _dispatch_payload_rejection("DISPATCH_PAYLOAD_FIELD_INVALID", "phase_permissions")
        for field in (
            "acceptance_criteria",
            "allowed_write_scope",
            "depends_on",
            "forbidden",
            "required_report_fields",
            "source_artifacts",
            "stop_conditions",
            "validation_commands",
        ):
            _require_dispatch_string_list(payload, field)
        for field in (
            "artifact_identity_rule",
            "canonical_state_path",
            "claim_boundary",
            "dispatch_when",
            "evidence_layer",
            "idempotency_rule",
            "objective",
            "phase",
            "prompt_injection_boundary",
            "repo_root",
            "review_gate",
            "state_rule",
            "target_branch",
            "worker_role",
        ):
            _require_dispatch_string(payload, field)
    elif envelope_type == "REVIEW_DISPATCH":
        _require_safe_dispatch_id(payload, "review_dispatch_id")
        _require_safe_dispatch_id(payload, "source_worker_dispatch_id")
        _require_safe_dispatch_id(payload, "code_review_id", nullable=True)
        _require_safe_dispatch_id(payload, "roadmap_audit_id", nullable=True)
        if payload["review_kind"] not in REVIEW_DECISIONS:
            _dispatch_payload_rejection("DISPATCH_PAYLOAD_FIELD_INVALID", "review_kind")
        if (
            payload["review_kind"] == "CODE_REVIEW"
            and (
                payload["code_review_id"] is not None
                or payload["roadmap_audit_id"] is not None
            )
        ) or (
            payload["review_kind"] == "ROADMAP_AUDIT"
            and (
                payload["code_review_id"] is None
                or payload["roadmap_audit_id"] is not None
            )
        ) or (
            payload["review_kind"] == "FINAL_AUDIT"
            and (
                payload["code_review_id"] is None
                or payload["roadmap_audit_id"] is None
            )
        ):
            _dispatch_payload_rejection(
                "DISPATCH_REVIEW_CHAIN_INVALID", "review_kind"
            )
        for field in ("source_worker_report_digest", "source_artifact_digest"):
            if not isinstance(payload[field], str) or DIGEST_RE.fullmatch(payload[field]) is None:
                _dispatch_payload_rejection("DISPATCH_PAYLOAD_FIELD_INVALID", field)
        if not isinstance(payload["decision_contract"], dict) or not isinstance(
            payload["artifact_identity"], dict
        ):
            _dispatch_payload_rejection("DISPATCH_PAYLOAD_FIELD_INVALID", "decision_contract")
        if payload["local_verification_ack_identity"] is not None and not isinstance(
            payload["local_verification_ack_identity"], dict
        ):
            _dispatch_payload_rejection(
                "DISPATCH_PAYLOAD_FIELD_INVALID", "local_verification_ack_identity"
            )
        _require_dispatch_string_list(payload, "evidence_refs")
    else:
        for field in (
            "local_dispatch_id",
            "verification_id",
            "source_worker_dispatch_id",
            "code_review_id",
        ):
            _require_safe_dispatch_id(payload, field)
        if not isinstance(payload["source_artifact_digest"], str) or DIGEST_RE.fullmatch(
            payload["source_artifact_digest"]
        ) is None:
            _dispatch_payload_rejection("DISPATCH_PAYLOAD_FIELD_INVALID", "source_artifact_digest")
        if not isinstance(payload["artifact_identity"], dict):
            _dispatch_payload_rejection("DISPATCH_PAYLOAD_FIELD_INVALID", "artifact_identity")
        for field in ("expected_result", "privacy_boundary"):
            _require_dispatch_string(payload, field)
        for field in (
            "evidence_capture_rules",
            "prerequisites",
            "steps",
            "stop_conditions",
        ):
            _require_dispatch_string_list(payload, field)


def materialize_dispatch_payload(specification: Any) -> dict[str, Any]:
    """Build one canonical Adaptive dispatch and its self-authenticating digest."""

    if not isinstance(specification, Mapping) or set(specification) != {
        "envelope_type",
        "payload",
    }:
        raise RuntimeRejection(
            "DISPATCH_MATERIALIZATION_INPUT_INVALID",
            "/",
            {"required_keys": ["envelope_type", "payload"]},
        )
    envelope_type = specification["envelope_type"]
    payload = specification["payload"]
    if not isinstance(payload, Mapping):
        raise RuntimeRejection("DISPATCH_PAYLOAD_JSON_INVALID", "/payload")
    if payload.get(PAYLOAD_DIGEST_FIELD) != PAYLOAD_DIGEST_PLACEHOLDER:
        raise RuntimeRejection(
            "DISPATCH_PAYLOAD_PLACEHOLDER_INVALID",
            f"/payload/{PAYLOAD_DIGEST_FIELD}",
            {"expected": PAYLOAD_DIGEST_PLACEHOLDER},
        )
    canonical_payload = copy.deepcopy(dict(payload))
    _validate_dispatch_payload_shape(envelope_type, canonical_payload)
    canonical_text = _dispatch_payload_text(envelope_type, canonical_payload)
    payload_digest = _bytes_digest(canonical_text.encode("utf-8"))
    materialized_payload = copy.deepcopy(canonical_payload)
    materialized_payload[PAYLOAD_DIGEST_FIELD] = payload_digest
    transport_text = _dispatch_payload_text(envelope_type, materialized_payload)
    return {
        "ok": True,
        "status": "PAYLOAD_MATERIALIZED",
        "envelope_type": envelope_type,
        "payload_digest": payload_digest,
        "canonical_byte_count": len(canonical_text.encode("utf-8")),
        "transport_byte_count": len(transport_text.encode("utf-8")),
        "transport_text": transport_text,
        "external_actions": [],
        "external_action_count": 0,
    }


def verify_dispatch_payload(transport_text: Any) -> dict[str, Any]:
    """Verify canonical dispatch bytes and digest without consulting loop state."""

    if not isinstance(transport_text, str) or not transport_text:
        raise RuntimeRejection("DISPATCH_PAYLOAD_TEXT_INVALID", "/")
    if "\r" in transport_text or transport_text.endswith("\n"):
        raise RuntimeRejection(
            "DISPATCH_PAYLOAD_NONCANONICAL",
            "/",
            {"reason": "LF_ONLY_WITH_NO_TRAILING_NEWLINE_REQUIRED"},
        )
    if "\n" not in transport_text:
        raise RuntimeRejection(
            "DISPATCH_PAYLOAD_TEXT_INVALID",
            "/",
            {"reason": "MISSING_ENVELOPE_SEPARATOR"},
        )
    envelope_type, payload_text = transport_text.split("\n", 1)
    payload = _strict_json_loads(
        payload_text,
        code="DISPATCH_PAYLOAD_JSON_INVALID",
        path="/payload",
    )
    if not isinstance(payload, dict):
        raise RuntimeRejection("DISPATCH_PAYLOAD_JSON_INVALID", "/payload")
    _validate_dispatch_payload_shape(envelope_type, payload)
    actual_digest = payload.get(PAYLOAD_DIGEST_FIELD)
    if not isinstance(actual_digest, str) or DIGEST_RE.fullmatch(actual_digest) is None:
        raise RuntimeRejection(
            "DISPATCH_PAYLOAD_DIGEST_INVALID",
            f"/payload/{PAYLOAD_DIGEST_FIELD}",
        )
    if _dispatch_payload_text(envelope_type, payload) != transport_text:
        raise RuntimeRejection(
            "DISPATCH_PAYLOAD_NONCANONICAL",
            "/payload",
            {"reason": "SORTED_COMPACT_UTF8_JSON_REQUIRED"},
        )
    canonical_payload = copy.deepcopy(payload)
    canonical_payload[PAYLOAD_DIGEST_FIELD] = PAYLOAD_DIGEST_PLACEHOLDER
    canonical_text = _dispatch_payload_text(envelope_type, canonical_payload)
    expected_digest = _bytes_digest(canonical_text.encode("utf-8"))
    if actual_digest != expected_digest:
        raise RuntimeRejection(
            "DISPATCH_PAYLOAD_DIGEST_MISMATCH",
            f"/payload/{PAYLOAD_DIGEST_FIELD}",
            {"expected": expected_digest, "actual": actual_digest},
        )
    return {
        "ok": True,
        "status": "PAYLOAD_BYTES_VERIFIED",
        "envelope_type": envelope_type,
        "payload_digest": actual_digest,
        "canonical_byte_count": len(canonical_text.encode("utf-8")),
        "transport_byte_count": len(transport_text.encode("utf-8")),
        "external_actions": [],
        "external_action_count": 0,
    }


def _dispatch_claim_matches_record(
    payload_claim: Mapping[str, Any],
    record_claim: Mapping[str, Any],
    state: Mapping[str, Any],
) -> bool:
    if payload_claim == record_claim:
        return True
    stable_fields = (
        "routing_turn_id",
        "owner_kind",
        "owner_identity",
        "intended_transition",
    )
    return bool(
        all(payload_claim.get(field) == record_claim.get(field) for field in stable_fields)
        and isinstance(payload_claim.get("lease_epoch"), int)
        and isinstance(record_claim.get("lease_epoch"), int)
        and record_claim["lease_epoch"] > payload_claim["lease_epoch"]
        and payload_claim.get("lease_id") in state["consumed_controller_lease_ids"]
    )


def verify_dispatch_payload_against_state(
    root: str | os.PathLike[str], transport_text: Any
) -> dict[str, Any]:
    """Verify dispatch bytes plus the exact canonical SENT outbox identity."""

    byte_result = verify_dispatch_payload(transport_text)
    envelope_type, payload_text = transport_text.split("\n", 1)
    payload = _strict_json_loads(
        payload_text,
        code="DISPATCH_PAYLOAD_JSON_INVALID",
        path="/payload",
    )
    assert isinstance(payload, dict)
    runtime = AdaptiveStateRuntime(root)
    state = runtime.read_state()
    if state is None:
        raise RuntimeRejection("DISPATCH_CANONICAL_STATE_MISSING", "/")
    if state["terminal_status"] is not None:
        raise RuntimeRejection(
            "DISPATCH_LOOP_ALREADY_TERMINAL", "/terminal_status"
        )

    outbox_field, outbox_kind, id_field, formal_role = {
        "WORKER_DISPATCH": (
            "dispatch_outbox",
            "DISPATCH",
            "dispatch_id",
            "WORKER",
        ),
        "REVIEW_DISPATCH": (
            "assurance_dispatch_outbox",
            "ASSURANCE",
            "review_dispatch_id",
            "REVIEWER",
        ),
        "LOCAL_VERIFY_DISPATCH": (
            "local_verification_outbox",
            "LOCAL",
            "local_dispatch_id",
            "LOCAL_VERIFIER",
        ),
    }[envelope_type]
    outbox_id = payload[id_field]
    record = state[outbox_field].get(outbox_id)
    if record is None or record.get("outbox_kind") != outbox_kind:
        raise RuntimeRejection(
            "DISPATCH_SENT_OUTBOX_NOT_FOUND", f"/{outbox_field}/{outbox_id}"
        )
    if record["status"] != "SENT":
        raise RuntimeRejection(
            "DISPATCH_OUTBOX_NOT_SENT",
            f"/{outbox_field}/{outbox_id}/status",
            {"actual": record["status"]},
        )
    if (
        record["payload_digest"] != byte_result["payload_digest"]
        or record["target_id"] != payload["target_thread_id"]
        or record["roadmap_version"] != payload["roadmap_version"]
    ):
        raise RuntimeRejection(
            "DISPATCH_OUTBOX_IDENTITY_MISMATCH",
            f"/{outbox_field}/{outbox_id}",
        )

    snapshot = payload["canonical_state_snapshot"]
    if (
        snapshot["loop_id"] != state["loop_id"]
        or snapshot["roadmap_version"] != record["roadmap_version"]
        or snapshot["active_milestone_id"] != payload["milestone_id"]
        or record["prepared_state_version"] != snapshot["state_version"] + 1
        or state["state_version"] < record["prepared_state_version"]
        or state["roadmap_version"] != snapshot["roadmap_version"]
        or state["active_milestone_id"] != snapshot["active_milestone_id"]
    ):
        raise RuntimeRejection(
            "DISPATCH_CANONICAL_SNAPSHOT_MISMATCH",
            "/payload/canonical_state_snapshot",
        )
    payload_claim = payload["dispatch_lease_claim"]
    if not _dispatch_claim_matches_record(payload_claim, record["lease_claim"], state):
        raise RuntimeRejection(
            "DISPATCH_LEASE_IDENTITY_MISMATCH",
            "/payload/dispatch_lease_claim",
        )

    target = state["thread_registry"].get(payload["target_thread_id"])
    if (
        target is None
        or target["status"] != "REGISTERED"
        or target["role_kind"] != formal_role
    ):
        raise RuntimeRejection(
            "DISPATCH_TARGET_THREAD_MISMATCH",
            "/payload/target_thread_id",
        )
    identity = record["identity"]
    if envelope_type == "WORKER_DISPATCH":
        definition = state["goal_definition_registry"].get(payload["goal_id"])
        expected = {
            "dispatch_id": payload["dispatch_id"],
            "goal_id": payload["goal_id"],
            "goal_definition_digest": payload["goal_definition_digest"],
            "payload_digest": byte_result["payload_digest"],
            "target_thread_id": payload["target_thread_id"],
            "worker_role_kind": payload["worker_role_kind"],
        }
        if (
            identity != expected
            or definition is None
            or definition["payload_template_digest"]
            != payload["goal_definition_digest"]
            or definition["worker_role_kind"] != payload["worker_role_kind"]
            or target["bootstrap_role_kind"] != payload["worker_role_kind"]
        ):
            raise RuntimeRejection(
                "DISPATCH_GOAL_IDENTITY_MISMATCH", "/payload/goal_id"
            )
    elif envelope_type == "REVIEW_DISPATCH":
        expected = {
            "review_dispatch_id": payload["review_dispatch_id"],
            "review_kind": payload["review_kind"],
            "goal_id": payload["goal_id"],
            "milestone_id": payload["milestone_id"],
            "roadmap_version": payload["roadmap_version"],
            "target_reviewer_thread_id": payload["target_thread_id"],
            "payload_digest": byte_result["payload_digest"],
            "worker_dispatch_id": payload["source_worker_dispatch_id"],
            "worker_report_digest": payload["source_worker_report_digest"],
            "artifact_digest": payload["source_artifact_digest"],
        }
        if payload["code_review_id"] is not None:
            expected["code_review_id"] = payload["code_review_id"]
        if payload["roadmap_audit_id"] is not None:
            expected["roadmap_audit_id"] = payload["roadmap_audit_id"]
        if identity != expected:
            raise RuntimeRejection(
                "DISPATCH_REVIEW_IDENTITY_MISMATCH", "/payload"
            )
    else:
        expected = {
            "local_dispatch_id": payload["local_dispatch_id"],
            "verification_id": payload["verification_id"],
            "goal_id": payload["goal_id"],
            "milestone_id": payload["milestone_id"],
            "roadmap_version": payload["roadmap_version"],
            "target_thread_id": payload["target_thread_id"],
            "payload_digest": byte_result["payload_digest"],
            "worker_dispatch_id": payload["source_worker_dispatch_id"],
            "artifact_digest": payload["source_artifact_digest"],
            "code_review_id": payload["code_review_id"],
        }
        if identity != expected:
            raise RuntimeRejection(
                "DISPATCH_LOCAL_IDENTITY_MISMATCH", "/payload"
            )
    return {
        **byte_result,
        "status": "PAYLOAD_VERIFIED",
        "state_version": state["state_version"],
        "outbox_id": outbox_id,
        "target_thread_id": payload["target_thread_id"],
    }


def _json_pointer(parts: Any) -> str:
    encoded = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(encoded) if encoded else "/"


def _parse_time(value: str, path: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise RuntimeRejection("TIMESTAMP_INVALID", path) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeRejection("TIMESTAMP_TIMEZONE_REQUIRED", path)
    return parsed


def _process_lock(path: Path) -> threading.RLock:
    key = str(path)
    with _PROCESS_LOCKS_GUARD:
        lock = _PROCESS_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PROCESS_LOCKS[key] = lock
        return lock


class AdaptiveStateRuntime:
    """Apply one validated mutation per crash-consistent CAS transaction."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        crash_at: str | None = None,
        crash_injector: Callable[[str], None] | None = None,
        jsonschema_loader: Callable[[], Any] = _import_jsonschema,
    ) -> None:
        self.root = Path(root).expanduser().resolve(strict=False)
        self.control_dir = self.root / ".codex-loop"
        self.state_path = self.control_dir / "LOOP_STATE.md"
        self.events_path = self.control_dir / "LOOP_EVENTS.jsonl"
        self.goals_path = self.control_dir / "GOALS.md"
        self.dashboard_path = self.control_dir / "progress-dashboard.html"
        self.transactions_dir = self.control_dir / "transactions"
        self.reports_dir = self.control_dir / "reports"
        self.sources_dir = self.control_dir / "sources"
        # Lock the stable project-root inode. A lock file that is deleted during
        # virgin-layout cleanup can split writers across old and new inodes.
        self.lock_path = self.root
        self.schema_dir = Path(__file__).resolve().parents[2] / "references"
        self.state_schema_path = self.schema_dir / "adaptive-state.schema.json"
        self.mutation_schema_path = self.schema_dir / "adaptive-mutation.schema.json"
        self.crash_at = crash_at
        self.crash_injector = crash_injector
        self.jsonschema_loader = jsonschema_loader
        self._triggered_crashes: set[str] = set()
        self._validators: tuple[Any, Any] | None = None

    def apply(self, request: Any) -> dict[str, Any]:
        """Validate and apply a request, returning structured JSON-compatible data."""

        try:
            mutation_validator, state_validator = self._load_validators()
        except RuntimeRejection as rejection:
            return self._rejection_response(rejection, state_version=0)

        try:
            self._ensure_json_value(request, "/")
            self._validate_schema(mutation_validator, request, "REQUEST_SCHEMA_INVALID")
            normalized = self._normalize_request(copy.deepcopy(request))
            request_digest = _digest(normalized)
        except RuntimeRejection as rejection:
            return self._rejection_response(rejection, state_version=0)
        except (TypeError, ValueError) as exc:
            rejection = RuntimeRejection(
                "REQUEST_JSON_INVALID",
                "/",
                {"error_type": type(exc).__name__},
            )
            return self._rejection_response(rejection, state_version=0)

        state_version = 0
        journal_written = False
        control_preexisting = True
        try:
            self._require_root()
            with self._exclusive_lock():
                control_preexisting = (
                    self.control_dir.exists() or self.control_dir.is_symlink()
                )
                self._ensure_layout()
                state = self._read_state_locked(state_validator)
                state_version = state["state_version"] if state is not None else 0
                recovery_ids = self._recovery_required_locked(
                    state_validator,
                    state,
                )
                if recovery_ids:
                    raise RuntimeRejection(
                        "RECOVERY_REQUIRED",
                        "/transactions",
                        {"state_request_ids": recovery_ids},
                    )

                duplicate = self._check_idempotency_locked(
                    normalized, request_digest, state
                )
                if duplicate is not None:
                    return duplicate

                expected = normalized["expected_state_version"]
                if expected != state_version:
                    raise RuntimeRejection(
                        "STATE_VERSION_CONFLICT",
                        "/expected_state_version",
                        {"expected": expected, "actual": state_version},
                    )

                mutation_type = normalized["mutation"]["type"]
                if state is None and mutation_type != "INITIALIZE":
                    raise RuntimeRejection("STATE_NOT_INITIALIZED", "/mutation/type")
                if state is not None and mutation_type == "INITIALIZE":
                    raise RuntimeRejection("STATE_ALREADY_INITIALIZED", "/mutation/type")

                after_version = 1 if state is None else state_version + 1
                next_state, operation_result = self._apply_mutation(
                    state,
                    normalized,
                    after_version,
                )
                next_state["state_version"] = after_version
                supplied_projection = normalized["mutation"].get(
                    "projection_digest"
                )
                if (
                    supplied_projection is not None
                    and supplied_projection
                    != _digest(self._roadmap_digest_payload(next_state))
                ):
                    raise RuntimeRejection(
                        "PROJECTION_DIGEST_MISMATCH",
                        "/mutation/projection_digest",
                    )
                self._record_idempotency(
                    next_state,
                    normalized,
                    request_digest,
                    after_version,
                )
                self._record_artifacts(next_state, normalized["artifacts"], after_version)
                self._refresh_roadmap_projection(next_state)
                self._validate_canonical_state(next_state, state_validator)
                self._validate_artifact_targets_locked(normalized["artifacts"])

                event = self._build_event(
                    normalized,
                    request_digest,
                    state_version,
                    after_version,
                    next_state,
                    operation_result,
                )
                journal = self._build_journal(
                    normalized,
                    request_digest,
                    state,
                    next_state,
                    event,
                )
                journal_path = self._journal_path(normalized["state_request_id"])
                self._write_journal_locked(journal_path, journal, phase="PREPARED")
                journal_written = True
                self._write_artifacts_locked(
                    normalized["artifacts"], normalized["state_request_id"]
                )
                self._write_state_locked(next_state, normalized["state_request_id"])
                self._write_goals_locked(next_state, normalized["state_request_id"])
                self._write_dashboard_locked(next_state, normalized["state_request_id"])
                self._append_event_locked(event)
                journal["status"] = "APPLIED"
                journal["applied_state_digest"] = journal["after_state_digest"]
                self._write_journal_locked(journal_path, journal, phase="APPLIED")
                self._cleanup_temps_locked()

                return self._applied_response(
                    normalized,
                    state_version,
                    after_version,
                    next_state,
                    operation_result,
                )
        except InjectedCrash:
            raise
        except RuntimeRejection as rejection:
            if not control_preexisting and not journal_written:
                self._cleanup_virgin_layout()
            return self._rejection_response(
                rejection,
                state_version=state_version,
                request=normalized,
            )
        except OSError as exc:
            code = "RECOVERY_REQUIRED" if journal_written else "PERSISTENCE_ERROR"
            rejection = RuntimeRejection(
                code,
                "/",
                {"errno": exc.errno, "error_type": type(exc).__name__},
            )
            if not control_preexisting and not journal_written:
                self._cleanup_virgin_layout()
            return self._rejection_response(
                rejection,
                state_version=state_version,
                request=normalized,
            )
        except Exception as exc:  # Defensive boundary for State-Writer callers.
            code = "RECOVERY_REQUIRED" if journal_written else "INTERNAL_ERROR"
            rejection = RuntimeRejection(
                code,
                "/",
                {"error_type": type(exc).__name__},
            )
            if not control_preexisting and not journal_written:
                self._cleanup_virgin_layout()
            return self._rejection_response(
                rejection,
                state_version=state_version,
                request=normalized,
            )

    def recover(self) -> dict[str, Any]:
        """Recover every visible journal and return a structured result."""

        try:
            _, state_validator = self._load_validators()
            self._require_root()
            with self._exclusive_lock():
                self._ensure_layout()
                recovered = self._recover_all_locked(state_validator)
                state = self._read_state_locked(state_validator)
                if state is not None:
                    self._ensure_projections_locked(state)
                self._cleanup_temps_locked()
            version = state["state_version"] if state is not None else 0
            return {
                "ok": True,
                "status": "RECOVERY_COMPLETE",
                "state_version": version,
                "recovered_transactions": recovered,
                "evidence_paths": self._base_evidence_paths(),
                "external_actions": [],
                "external_action_count": 0,
            }
        except InjectedCrash:
            raise
        except RuntimeRejection as rejection:
            return self._rejection_response(rejection, state_version=0)
        except OSError as exc:
            return self._rejection_response(
                RuntimeRejection(
                    "PERSISTENCE_ERROR",
                    "/",
                    {"errno": exc.errno, "error_type": type(exc).__name__},
                ),
                state_version=0,
            )
        except Exception as exc:
            return self._rejection_response(
                RuntimeRejection(
                    "RECOVERY_REQUIRED",
                    "/",
                    {"error_type": type(exc).__name__},
                ),
                state_version=0,
            )

    def read_state(self) -> dict[str, Any] | None:
        """Read and validate canonical state under the same exclusive lock."""

        _, state_validator = self._load_validators()
        self._require_root()
        with self._exclusive_lock():
            if not self.control_dir.exists():
                return None
            self._ensure_layout()
            return self._read_state_locked(state_validator)

    def _load_validators(self) -> tuple[Any, Any]:
        if self._validators is not None:
            return self._validators
        try:
            jsonschema = self.jsonschema_loader()
        except (ImportError, ModuleNotFoundError) as exc:
            raise RuntimeRejection(
                "DEPENDENCY_MISSING",
                "/",
                {"dependency": "jsonschema"},
            ) from exc
        if jsonschema is None:
            raise RuntimeRejection(
                "DEPENDENCY_MISSING",
                "/",
                {"dependency": "jsonschema"},
            )
        try:
            state_schema = _strict_json_loads(
                self.state_schema_path.read_text(encoding="utf-8"),
                code="SCHEMA_INVALID",
                path=str(self.state_schema_path),
            )
            mutation_schema = _strict_json_loads(
                self.mutation_schema_path.read_text(encoding="utf-8"),
                code="SCHEMA_INVALID",
                path=str(self.mutation_schema_path),
            )
            validator_class = jsonschema.Draft202012Validator
            validator_class.check_schema(state_schema)
            validator_class.check_schema(mutation_schema)
            format_checker = jsonschema.FormatChecker()
            self._validators = (
                validator_class(mutation_schema, format_checker=format_checker),
                validator_class(state_schema, format_checker=format_checker),
            )
            return self._validators
        except FileNotFoundError as exc:
            raise RuntimeRejection(
                "SCHEMA_UNAVAILABLE",
                "/",
                {"schema_path": str(exc.filename)},
            ) from exc
        except RuntimeRejection:
            raise
        except Exception as exc:
            raise RuntimeRejection(
                "SCHEMA_INVALID",
                "/",
                {"error_type": type(exc).__name__},
            ) from exc

    @staticmethod
    def _validate_schema(validator: Any, value: Any, code: str) -> None:
        errors = list(validator.iter_errors(value))
        if not errors:
            return

        expanded: list[Any] = []

        def collect(error: Any) -> None:
            expanded.append(error)
            for child in error.context:
                collect(child)

        for error in errors:
            collect(error)
        error = sorted(
            expanded,
            key=lambda item: (-len(item.absolute_path), _json_pointer(item.absolute_path)),
        )[0]
        raise RuntimeRejection(
            code,
            _json_pointer(error.absolute_path),
            {"validator": str(error.validator)},
        )

    @staticmethod
    def _ensure_json_value(value: Any, path: str) -> None:
        try:
            _canonical_json(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeRejection(
                "REQUEST_JSON_INVALID",
                path,
                {"error_type": type(exc).__name__},
            ) from exc

    def _require_root(self) -> None:
        if not self.root.exists():
            raise RuntimeRejection("ROOT_NOT_FOUND", "/root")
        if not self.root.is_dir():
            raise RuntimeRejection("ROOT_NOT_DIRECTORY", "/root")

    def _ensure_layout(self) -> None:
        for path in (
            self.control_dir,
            self.transactions_dir,
            self.reports_dir,
            self.sources_dir,
        ):
            self._reject_symlink(path, "/layout")
        self._assert_confined(self.control_dir, self.root, "/root")
        self._assert_confined(self.transactions_dir, self.control_dir, "/transactions")
        self._assert_confined(self.reports_dir, self.control_dir, "/reports")
        self._assert_confined(self.sources_dir, self.control_dir, "/sources")
        self.control_dir.mkdir(mode=0o700, parents=False, exist_ok=True)
        self.transactions_dir.mkdir(mode=0o700, parents=False, exist_ok=True)
        self.reports_dir.mkdir(mode=0o700, parents=False, exist_ok=True)
        self.sources_dir.mkdir(mode=0o700, parents=False, exist_ok=True)

    def _cleanup_virgin_layout(self) -> None:
        try:
            with self._exclusive_lock():
                if not self.control_dir.exists() or self.control_dir.is_symlink():
                    return
                protected = (
                    self.state_path,
                    self.events_path,
                    self.goals_path,
                    self.dashboard_path,
                )
                if any(path.exists() or path.is_symlink() for path in protected):
                    return
                for directory in (
                    self.transactions_dir,
                    self.reports_dir,
                    self.sources_dir,
                ):
                    if directory.exists() and any(directory.iterdir()):
                        return
                for directory in (
                    self.transactions_dir,
                    self.reports_dir,
                    self.sources_dir,
                ):
                    if directory.exists():
                        directory.rmdir()
                self.control_dir.rmdir()
                self._fsync_dir(self.root)
        except (OSError, RuntimeRejection):
            return

    @contextlib.contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        process_lock = _process_lock(self.lock_path)
        with process_lock:
            self._require_root()
            self._reject_symlink(self.root, "/root")
            descriptor = os.open(
                self.root,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    @staticmethod
    def _assert_confined(path: Path, parent: Path, json_path: str) -> None:
        AdaptiveStateRuntime._reject_symlink(path, json_path)
        candidate = path.resolve(strict=False)
        boundary = parent.resolve(strict=False)
        if not AdaptiveStateRuntime._path_is_within(candidate, boundary):
            raise RuntimeRejection("PATH_SCOPE_ESCAPE", json_path)

    @staticmethod
    def _path_is_within(path: Path, parent: Path) -> bool:
        try:
            common = Path(os.path.commonpath([str(path), str(parent)]))
        except ValueError:
            return False
        return common == parent

    def _assert_authorized_worktree(
        self,
        state: dict[str, Any],
        path: Path,
        json_path: str,
    ) -> Path:
        self._reject_symlink(path, json_path)
        candidate = path.resolve(strict=False)
        boundaries = [self.root]
        boundaries.extend(
            Path(item).expanduser().resolve(strict=False)
            for item in state["authorization_envelope"]["control_plane_limits"][
                "allowed_external_worktree_roots"
            ]
        )
        if not any(self._path_is_within(candidate, boundary) for boundary in boundaries):
            raise RuntimeRejection(
                "PATH_SCOPE_ESCAPE",
                json_path,
                {"allowed_worktree_roots": [str(item) for item in boundaries]},
            )
        return candidate

    @staticmethod
    def _reject_symlink(path: Path, json_path: str) -> None:
        if path.is_symlink():
            raise RuntimeRejection("SYMLINK_NOT_ALLOWED", json_path)

    def _normalize_request(self, request: dict[str, Any]) -> dict[str, Any]:
        request.setdefault("artifacts", [])
        request["evidence_paths"] = self._normalize_evidence_paths(
            request["evidence_paths"], "/evidence_paths"
        )
        mutation = request["mutation"]
        for key in (
            "send_evidence_paths",
            "ack_evidence_paths",
            "review_evidence_paths",
            "recovery_evidence_paths",
        ):
            if key in mutation:
                mutation[key] = self._normalize_evidence_paths(
                    mutation[key], f"/mutation/{key}"
                )
        self._normalize_nested_path_fields(mutation, "/mutation")
        request["artifacts"] = self._normalize_artifacts(request["artifacts"])
        return request

    def _normalize_artifacts(self, artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, artifact in enumerate(artifacts):
            path = artifact["path"]
            if path in seen:
                raise RuntimeRejection("ARTIFACT_PATH_CONFLICT", f"/artifacts/{index}/path")
            seen.add(path)
            self._reject_symlink(self.control_dir, f"/artifacts/{index}/path")
            raw_target = self.root / path
            self._reject_symlink(raw_target, f"/artifacts/{index}/path")
            target = raw_target.resolve(strict=False)
            self._assert_confined(target, self.control_dir, f"/artifacts/{index}/path")
            relative = target.relative_to(self.root).as_posix()
            allowed = (
                relative == ".codex-loop/sources/CONTROLLER_PACK.md"
                or (
                    target.parent == self.reports_dir
                    and target.suffix in {".md", ".json", ".txt"}
                )
            )
            if not allowed:
                raise RuntimeRejection("ARTIFACT_PATH_INVALID", f"/artifacts/{index}/path")
            payload = artifact["content"].encode("utf-8")
            actual_digest = _bytes_digest(payload)
            if artifact["digest"] != actual_digest:
                raise RuntimeRejection(
                    "ARTIFACT_DIGEST_MISMATCH",
                    f"/artifacts/{index}/digest",
                    {"expected": actual_digest, "actual": artifact["digest"]},
                )
            normalized.append({**artifact, "path": relative})
        return sorted(normalized, key=lambda item: item["path"])

    def _normalize_nested_path_fields(self, value: Any, path: str) -> None:
        if not isinstance(value, dict):
            return
        for key, child in list(value.items()):
            child_path = f"{path}/{key}"
            if key == "worktree_path" and isinstance(child, str):
                if not child or "\x00" in child or child.startswith("~"):
                    raise RuntimeRejection("EVIDENCE_PATH_INVALID", child_path)
            elif key.endswith("_path") and isinstance(child, str):
                value[key] = self._normalize_evidence_path(
                    child, child_path
                )
            elif key.endswith("_paths") and isinstance(child, list):
                value[key] = self._normalize_evidence_paths(child, child_path)
            elif isinstance(child, dict):
                self._normalize_nested_path_fields(child, child_path)
            elif isinstance(child, list):
                for index, item in enumerate(child):
                    if isinstance(item, dict):
                        self._normalize_nested_path_fields(item, f"{child_path}/{index}")

    def _normalize_evidence_paths(self, values: list[str], path: str) -> list[str]:
        return [
            self._normalize_evidence_path(value, f"{path}/{index}")
            for index, value in enumerate(values)
        ]

    def _normalize_evidence_path(self, value: str, path: str) -> str:
        raw = Path(value).expanduser()
        candidate = raw if raw.is_absolute() else self.root / raw
        candidate = candidate.resolve(strict=False)
        self._assert_confined(candidate, self.root, path)
        relative = candidate.relative_to(self.root)
        if not relative.parts:
            raise RuntimeRejection("EVIDENCE_PATH_INVALID", path)
        return relative.as_posix()

    def _journal_path(self, state_request_id: str) -> Path:
        if SAFE_ID_RE.fullmatch(state_request_id) is None:
            raise RuntimeRejection("UNSAFE_ID", "/state_request_id")
        path = self.transactions_dir / f"{state_request_id}.json"
        self._assert_confined(path, self.transactions_dir, "/state_request_id")
        return path

    def _inject(self, stage: str) -> None:
        if self.crash_injector is not None:
            self.crash_injector(stage)
        if self.crash_at == stage and stage not in self._triggered_crashes:
            self._triggered_crashes.add(stage)
            raise InjectedCrash(stage)

    def _render_state(self, state: dict[str, Any]) -> bytes:
        payload = _canonical_json(state, indent=2)
        return f"{STATE_BEGIN}\n{payload}\n{STATE_END}\n".encode("utf-8")

    @staticmethod
    def _roadmap_digest_payload(state: dict[str, Any]) -> dict[str, Any]:
        return {
            "roadmap_version": state["roadmap_version"],
            "active_milestone_id": state["active_milestone_id"],
            "milestones": state["milestones"],
            "goal_queue": state["goal_queue"],
            "goal_definition_registry": state["goal_definition_registry"],
        }

    def _refresh_roadmap_projection(self, state: dict[str, Any]) -> None:
        state["roadmap_projection"] = {
            "roadmap_version": state["roadmap_version"],
            "projection_digest": _digest(self._roadmap_digest_payload(state)),
        }

    def _render_goals(self, state: dict[str, Any]) -> bytes:
        projection = state["roadmap_projection"]
        lines = [
            "# Adaptive Loop Goals",
            "",
            f"state_version: {state['state_version']}",
            f"roadmap_version: {state['roadmap_version']}",
            f"roadmap_sha256: {projection['projection_digest']}",
            f"generated_at: {state['logical_time']}",
            f"terminal_status: {_canonical_json(state['terminal_status'])}",
            "",
            "## Active Milestone",
            "",
            _canonical_json(state["active_milestone_id"]),
        ]
        for milestone in state["milestones"]:
            lines.extend(
                [
                    "",
                    f"## Milestone {milestone['milestone_id']}",
                    "",
                    f"- Status: {_canonical_json(milestone['status'])}",
                    f"- Outcome: {_canonical_json(milestone['outcome'])}",
                    f"- Scope: {_canonical_json(milestone['scope'])}",
                    f"- Decisions: {_canonical_json(milestone['decisions'])}",
                    f"- Blockers: {_canonical_json(milestone['blockers'])}",
                    f"- Required Evidence: {_canonical_json(milestone['required_evidence'])}",
                    f"- Dependencies: {_canonical_json(milestone['depends_on'])}",
                    f"- References: {_canonical_json(milestone['references'])}",
                    f"- Last Change Reason: {_canonical_json(milestone.get('last_change_reason'))}",
                ]
            )
        lines.extend(
            [
                "",
                "## Goal Queue",
                "",
                "```json",
                _canonical_json(state["goal_queue"], indent=2),
                "```",
                "",
            ]
        )
        return "\n".join(lines).encode("utf-8")

    def _render_dashboard(self, state: dict[str, Any]) -> bytes | None:
        if not state["dashboard_required"]:
            return None
        projection = state["roadmap_projection"]
        rows = "".join(
            "<tr>"
            f"<td>{html.escape(item['milestone_id'])}</td>"
            f"<td>{html.escape(item['status'])}</td>"
            f"<td>{html.escape(item['outcome'])}</td>"
            f"<td><code>{html.escape(_canonical_json(item['decisions']))}</code></td>"
            f"<td><code>{html.escape(_canonical_json(item['blockers']))}</code></td>"
            f"<td><code>{html.escape(_canonical_json(item['required_evidence']))}</code></td>"
            "</tr>"
            for item in state["milestones"]
        )
        evidence_items = "".join(
            "<li>"
            f'<a href="{html.escape(path.removeprefix(".codex-loop/"), quote=True)}">'
            f"{html.escape(path)}</a> "
            f"<code>{html.escape(record['digest'])}</code>"
            "</li>"
            for path, record in sorted(state["artifact_ledger"].items())
        ) or "<li>None</li>"
        required_decision_items = "".join(
            "<li>"
            f"Review <code>{html.escape(review_id)}</code> for Goal "
            f"<code>{html.escape(record['goal_id'])}</code>: "
            f"<code>{html.escape(record['decision'])}</code>"
            "</li>"
            for review_id, record in sorted(state["assurance_ledger"].items())
            if record["decision"] == "ROADMAP_CHANGE_PROPOSED"
        ) or "<li>None</li>"
        ordered_events = sorted(
            state["event_ledger"].items(),
            key=lambda item: (item[1]["applied_state_version"], item[0]),
        )
        event_items = "".join(
            f"<li><code>{html.escape(event_id)}</code></li>"
            for event_id, _ in ordered_events[-12:]
        )
        payload = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="codex-loop-state-version" content="{state['state_version']}">
<meta name="codex-loop-roadmap-digest" content="{html.escape(projection['projection_digest'])}">
<title>Adaptive Loop Progress</title>
<style>body{{font-family:system-ui,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;color:#171717;background:#fff}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccc;padding:8px;text-align:left;vertical-align:top}}code{{white-space:pre-wrap;overflow-wrap:anywhere}}.status{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}}@media(max-width:720px){{.status{{grid-template-columns:1fr}}}}</style>
</head>
<body>
<h1>Adaptive Loop Progress</h1>
<div class="status"><p><strong>State version</strong><br>{state['state_version']}</p><p><strong>Roadmap version</strong><br>{state['roadmap_version']}</p><p><strong>Active milestone</strong><br>{html.escape(str(state['active_milestone_id']))}</p></div>
<p><strong>Terminal status:</strong> {html.escape(str(state['terminal_status']))}</p>
<table><thead><tr><th>Milestone</th><th>Status</th><th>Outcome</th><th>Decisions</th><th>Blockers</th><th>Required evidence</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Goal queue</h2><pre><code>{html.escape(_canonical_json(state['goal_queue'], indent=2))}</code></pre>
<h2>Estimate history</h2><pre><code>{html.escape(_canonical_json(state['estimate_history'], indent=2))}</code></pre>
<h2>Evidence</h2><ul>{evidence_items}</ul>
<h2>Required user decisions</h2><ul>{required_decision_items}</ul>
<h2>Recent events</h2><ul>{event_items}</ul>
<p>Generated from canonical state at {html.escape(state['logical_time'])}. This file is read-only.</p>
</body>
</html>
"""
        return payload.encode("utf-8")

    def _record_artifacts(
        self,
        state: dict[str, Any],
        artifacts: list[dict[str, Any]],
        after_version: int,
    ) -> None:
        ledger = state["artifact_ledger"]
        for artifact in artifacts:
            record = {
                "path": artifact["path"],
                "digest": artifact["digest"],
                "media_type": artifact["media_type"],
                "archived_state_version": after_version,
            }
            existing = ledger.get(artifact["path"])
            if existing is not None and (
                existing["digest"] != artifact["digest"]
                or existing["media_type"] != artifact["media_type"]
            ):
                raise RuntimeRejection("ARTIFACT_IMMUTABILITY_CONFLICT", "/artifacts")
            ledger[artifact["path"]] = existing or record

    def _artifact_target(self, path: str) -> Path:
        raw_target = self.root / path
        self._reject_symlink(raw_target, "/artifacts/path")
        target = raw_target.resolve(strict=False)
        self._assert_confined(target, self.control_dir, "/artifacts/path")
        return target

    def _validate_artifact_targets_locked(
        self, artifacts: list[dict[str, Any]]
    ) -> None:
        for artifact in artifacts:
            target = self._artifact_target(artifact["path"])
            if target.exists() and _bytes_digest(target.read_bytes()) != artifact["digest"]:
                raise RuntimeRejection(
                    "ARTIFACT_IMMUTABILITY_CONFLICT",
                    "/artifacts",
                    {"path": artifact["path"]},
                )

    def _write_artifacts_locked(
        self,
        artifacts: list[dict[str, Any]],
        transaction_id: str,
    ) -> None:
        for artifact in artifacts:
            target = self._artifact_target(artifact["path"])
            payload = artifact["content"].encode("utf-8")
            if target.exists():
                if target.read_bytes() != payload:
                    raise RuntimeRejection(
                        "ARTIFACT_IMMUTABILITY_CONFLICT",
                        "/artifacts",
                        {"path": artifact["path"]},
                    )
                continue
            self._atomic_replace_bytes(
                target,
                payload,
                transaction_id,
                "ARTIFACT",
            )

    def _read_state_locked(self, state_validator: Any) -> dict[str, Any] | None:
        if not self.state_path.exists():
            return None
        self._reject_symlink(self.state_path, "/state")
        try:
            raw = self.state_path.read_bytes()
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeRejection("CANONICAL_STATE_INVALID", "/state") from exc
        prefix = f"{STATE_BEGIN}\n"
        suffix = f"\n{STATE_END}\n"
        if not text.startswith(prefix) or not text.endswith(suffix):
            raise RuntimeRejection(
                "CANONICAL_STATE_INVALID",
                "/state",
                {"reason": "STATE_FENCE_INVALID"},
            )
        json_payload = text[len(prefix) : -len(suffix)]
        state = _strict_json_loads(
            json_payload,
            code="CANONICAL_STATE_INVALID",
            path="/state",
        )
        self._validate_canonical_state(state, state_validator)
        if self._render_state(state) != raw:
            raise RuntimeRejection(
                "CANONICAL_STATE_INVALID",
                "/state",
                {"reason": "NONCANONICAL_ENCODING"},
            )
        return state

    def _validate_canonical_state(self, state: Any, state_validator: Any) -> None:
        self._validate_schema(state_validator, state, "CANONICAL_STATE_SCHEMA_INVALID")
        if state["root"] != str(self.root):
            raise RuntimeRejection(
                "CANONICAL_ROOT_MISMATCH",
                "/root",
                {"expected": str(self.root), "actual": state["root"]},
            )
        self._validate_milestones(state)
        self._validate_goal_graph(state)
        self._validate_controller_goal_identity(state)
        self._validate_authorization_boundary(
            state["goal_definition_registry"],
            state["milestones"],
            state["authorization_envelope"],
            "/authorization_envelope",
        )
        self._validate_thread_registry(state)
        pack_identity = state["controller_pack_identity"]
        pack_record = state["artifact_ledger"].get(pack_identity["path"])
        if (
            pack_record is None
            or pack_record["digest"] != pack_identity["digest"]
            or pack_record["media_type"] != pack_identity["media_type"]
        ):
            raise RuntimeRejection(
                "CONTROLLER_PACK_IDENTITY_MISMATCH",
                "/controller_pack_identity",
            )
        self._validate_outboxes(state)
        self._validate_assurance_consistency(state)
        self._validate_finalization_state(state)
        self._validate_lease_state(state)
        if state["external_action_count"] != 0:
            raise RuntimeRejection(
                "RUNTIME_EXTERNAL_ACTION_VIOLATION", "/external_action_count"
            )

    def _validate_milestones(self, state: dict[str, Any]) -> None:
        milestones = state["milestones"]
        ids = [item["milestone_id"] for item in milestones]
        if len(ids) != len(set(ids)):
            raise RuntimeRejection("MILESTONE_ID_CONFLICT", "/milestones")
        known = set(ids)
        dependencies: dict[str, list[str]] = {}
        statuses: dict[str, str] = {}
        for index, item in enumerate(milestones):
            milestone_id = item["milestone_id"]
            dependencies[milestone_id] = item["depends_on"]
            statuses[milestone_id] = item["status"]
            if milestone_id in item["depends_on"] or not set(item["depends_on"]).issubset(known):
                raise RuntimeRejection(
                    "MILESTONE_DEPENDENCY_INVALID", f"/milestones/{index}/depends_on"
                )
            for scope_index, scope in enumerate(item["scope"]):
                self._validate_scope(scope, f"/milestones/{index}/scope/{scope_index}")
        self._reject_cycles(dependencies, "MILESTONE_DEPENDENCY_CYCLE", "/milestones")
        active = [item["milestone_id"] for item in milestones if item["status"] == "ACTIVE"]
        if state["terminal_status"] is None:
            if len(active) != 1 or state["active_milestone_id"] != active[0]:
                raise RuntimeRejection("ACTIVE_MILESTONE_INVALID", "/active_milestone_id")
            if any(statuses[dependency] != "COMPLETE" for dependency in dependencies[active[0]]):
                raise RuntimeRejection("ACTIVE_MILESTONE_DEPENDENCY_INCOMPLETE", "/milestones")
        elif state["terminal_status"] in {"LOOP_COMPLETE", "LOOP_COMPLETE_WITH_LIMITATION"}:
            if active or state["active_milestone_id"] is not None:
                raise RuntimeRejection("TERMINAL_ACTIVE_MILESTONE", "/active_milestone_id")
            if any(status not in {"COMPLETE", "SUPERSEDED"} for status in statuses.values()):
                raise RuntimeRejection("TERMINAL_MILESTONE_INCOMPLETE", "/milestones")
        else:
            if active or state["active_milestone_id"] is not None:
                raise RuntimeRejection("TERMINAL_ACTIVE_MILESTONE", "/active_milestone_id")
            if any(
                status not in {"BLOCKED", "COMPLETE", "SUPERSEDED"}
                for status in statuses.values()
            ):
                raise RuntimeRejection("TERMINAL_MILESTONE_INVALID", "/milestones")

    def _validate_goal_graph(self, state: dict[str, Any]) -> None:
        definitions = state["goal_definition_registry"]
        ledger = state["goal_execution_ledger"]
        milestone_ids = {item["milestone_id"] for item in state["milestones"]}
        if set(definitions) != set(ledger):
            raise RuntimeRejection("GOAL_LEDGER_COVERAGE_INVALID", "/goal_execution_ledger")
        dependencies: dict[str, list[str]] = {}
        for goal_id, definition in definitions.items():
            if goal_id != definition["goal_id"]:
                raise RuntimeRejection(
                    "GOAL_ID_CONFLICT", f"/goal_definition_registry/{goal_id}/goal_id"
                )
            if definition["milestone_id"] not in milestone_ids:
                raise RuntimeRejection(
                    "GOAL_MILESTONE_UNKNOWN",
                    f"/goal_definition_registry/{goal_id}/milestone_id",
                )
            if goal_id in definition["depends_on"]:
                raise RuntimeRejection(
                    "GOAL_DEPENDENCY_INVALID",
                    f"/goal_definition_registry/{goal_id}/depends_on",
                )
            dependencies[goal_id] = definition["depends_on"]
            expected_digest = _goal_definition_digest(definition)
            if definition["payload_template_digest"] != expected_digest:
                raise RuntimeRejection(
                    "GOAL_DEFINITION_DIGEST_MISMATCH",
                    f"/goal_definition_registry/{goal_id}/payload_template_digest",
                    {
                        "expected": expected_digest,
                        "actual": definition["payload_template_digest"],
                    },
                )
            for index, scope in enumerate(definition["allowed_write_scope"]):
                self._validate_scope(
                    scope,
                    f"/goal_definition_registry/{goal_id}/allowed_write_scope/{index}",
                )
            record = ledger[goal_id]
            if (
                record["goal_id"] != goal_id
                or record["milestone_id"] != definition["milestone_id"]
                or record["definition_digest"] != definition["payload_template_digest"]
            ):
                raise RuntimeRejection(
                    "GOAL_LEDGER_IDENTITY_INVALID", f"/goal_execution_ledger/{goal_id}"
                )
        known = set(definitions)
        if any(
            dependency not in known
            for values in dependencies.values()
            for dependency in values
        ):
            raise RuntimeRejection("GOAL_DEPENDENCY_UNKNOWN", "/goal_definition_registry")
        self._reject_cycles(dependencies, "GOAL_DEPENDENCY_CYCLE", "/goal_definition_registry")

        queue = state["goal_queue"]
        queue_ids = [item["goal_id"] for item in queue]
        if len(queue_ids) != len(set(queue_ids)):
            raise RuntimeRejection("GOAL_QUEUE_ID_CONFLICT", "/goal_queue")
        milestone_status = {
            item["milestone_id"]: item["status"] for item in state["milestones"]
        }
        completed = {
            goal_id
            for goal_id, record in ledger.items()
            if record["status"] in {"COMPLETE", "RETIRED"}
        }
        for index, entry in enumerate(queue):
            goal_id = entry["goal_id"]
            definition = definitions.get(goal_id)
            if definition is None:
                raise RuntimeRejection("GOAL_QUEUE_DEFINITION_MISSING", f"/goal_queue/{index}")
            if (
                entry["milestone_id"] != definition["milestone_id"]
                or entry["depends_on"] != definition["depends_on"]
                or entry["roadmap_version"] != state["roadmap_version"]
                or goal_id in completed
            ):
                raise RuntimeRejection("GOAL_QUEUE_IDENTITY_INVALID", f"/goal_queue/{index}")
            if milestone_status[entry["milestone_id"]] not in {"ACTIVE", "PLANNED"}:
                raise RuntimeRejection("GOAL_QUEUE_MILESTONE_INVALID", f"/goal_queue/{index}")
            if (
                milestone_status[entry["milestone_id"]] == "PLANNED"
                and entry["status"] != "PLANNED"
            ):
                raise RuntimeRejection(
                    "PLANNED_MILESTONE_GOAL_NOT_PLANNED",
                    f"/goal_queue/{index}/status",
                )
            if entry["status"] == "READY" and not set(entry["depends_on"]).issubset(completed):
                raise RuntimeRejection("GOAL_QUEUE_DEPENDENCY_INCOMPLETE", f"/goal_queue/{index}")

        expected_queue = {
            goal_id
            for goal_id, definition in definitions.items()
            if milestone_status[definition["milestone_id"]] in {"ACTIVE", "PLANNED"}
            and ledger[goal_id]["status"] not in {"COMPLETE", "RETIRED"}
        }
        if set(queue_ids) != expected_queue:
            raise RuntimeRejection("GOAL_QUEUE_COVERAGE_INVALID", "/goal_queue")
        if state["terminal_status"] is not None:
            if queue:
                raise RuntimeRejection("TERMINAL_GOAL_QUEUE_NOT_EMPTY", "/goal_queue")
            if any(record["status"] not in {"COMPLETE", "RETIRED"} for record in ledger.values()):
                raise RuntimeRejection("TERMINAL_GOAL_UNRESOLVED", "/goal_execution_ledger")
        else:
            ready = [
                entry
                for entry in queue
                if entry["milestone_id"] == state["active_milestone_id"]
                and entry["status"] == "READY"
            ]
            if not ready:
                raise RuntimeRejection("ACTIVE_GOAL_NOT_READY", "/goal_queue")
        required_local = set(state["local_verification_required_goal_ids"])
        if not required_local.issubset(definitions):
            raise RuntimeRejection(
                "LOCAL_VERIFICATION_GOAL_UNKNOWN",
                "/local_verification_required_goal_ids",
            )

    @staticmethod
    def _validate_controller_goal_identity(state: dict[str, Any]) -> None:
        controller_goal = state["controller_goal"]
        if controller_goal is None:
            return
        expected_marker = (
            "[CODEX_LOOP_MILESTONE "
            f"loop_id={controller_goal['loop_id']} "
            f"pack_sha256={controller_goal['pack_digest'].removeprefix('sha256:')} "
            f"milestone_id={controller_goal['milestone_id']} "
            f"objective_sha256={controller_goal['objective_digest'].removeprefix('sha256:')}]"
        )
        milestone_ids = {item["milestone_id"] for item in state["milestones"]}
        if (
            controller_goal["loop_id"] != state["loop_id"]
            or controller_goal["pack_digest"]
            != state["controller_pack_identity"]["digest"]
            or controller_goal["milestone_id"] not in milestone_ids
            or controller_goal["marker"] != expected_marker
        ):
            raise RuntimeRejection(
                "CONTROLLER_GOAL_STATE_IDENTITY_INVALID",
                "/controller_goal",
            )

    def _validate_authorization_boundary(
        self,
        definitions: dict[str, dict[str, Any]],
        milestones: list[dict[str, Any]],
        envelope: dict[str, Any],
        path: str,
    ) -> None:
        caps = envelope["phase_permission_caps"]
        milestone_caps = caps["by_milestone"]
        goal_caps = caps["by_goal"]
        milestone_ids = {item["milestone_id"] for item in milestones}
        if set(milestone_caps) != milestone_ids:
            raise RuntimeRejection(
                "AUTHORIZATION_BOUNDARY_VIOLATION",
                f"{path}/phase_permission_caps/by_milestone",
                {"reason": "MILESTONE_CAP_COVERAGE"},
            )
        if set(goal_caps) != set(definitions):
            raise RuntimeRejection(
                "AUTHORIZATION_BOUNDARY_VIOLATION",
                f"{path}/phase_permission_caps/by_goal",
                {"reason": "GOAL_CAP_COVERAGE"},
            )
        top_level = envelope["phase_permissions"]
        global_scopes = envelope["allowed_write_scope"]
        delegation = envelope.get(
            "delegation_policy",
            {
                "mode": "disabled",
                "max_concurrent": 0,
                "max_lifetime_runs": 0,
                "retry_limit_per_exploration": 0,
                "max_depth": 1,
            },
        )
        enabled = delegation["mode"] in {
            "explicit_read_only",
            "auto_read_only",
        }
        repair_limit = envelope["repair_policy"][
            "max_repair_attempts_per_goal"
        ]
        if (
            delegation["max_depth"] != 1
            or (
                not enabled
                and any(
                    delegation[field] != 0
                    for field in (
                        "max_concurrent",
                        "max_lifetime_runs",
                        "retry_limit_per_exploration",
                    )
                )
            )
            or (
                enabled
                and (
                    delegation["max_concurrent"] not in {1, 2}
                    or delegation["max_lifetime_runs"]
                    < delegation["max_concurrent"]
                )
            )
        ):
            raise RuntimeRejection(
                "AUTHORIZATION_BOUNDARY_VIOLATION",
                f"{path}/delegation_policy",
                {"reason": "DELEGATION_POLICY_INVALID"},
            )
        if (
            type(repair_limit) is not int
            or repair_limit < 0
            or repair_limit > 20
        ):
            raise RuntimeRejection(
                "AUTHORIZATION_BOUNDARY_VIOLATION",
                f"{path}/repair_policy/max_repair_attempts_per_goal",
                {"reason": "REPAIR_POLICY_INVALID"},
            )
        for milestone_id, permission_cap in milestone_caps.items():
            for permission in PHASE_PERMISSION_FIELDS:
                if permission_cap.get(permission) is True and top_level.get(permission) is not True:
                    raise RuntimeRejection(
                        "AUTHORIZATION_BOUNDARY_VIOLATION",
                        f"{path}/phase_permission_caps/by_milestone/{milestone_id}/{permission}",
                        {"reason": "MILESTONE_CAP_EXCEEDS_TOP_LEVEL"},
                    )
        for goal_id, definition in definitions.items():
            milestone_id = definition["milestone_id"]
            goal_cap = goal_caps.get(goal_id)
            if goal_cap is None or goal_cap.get("milestone_id") != milestone_id:
                raise RuntimeRejection(
                    "AUTHORIZATION_BOUNDARY_VIOLATION",
                    f"{path}/phase_permission_caps/by_goal/{goal_id}",
                    {"reason": "GOAL_MILESTONE_CAP_MISMATCH"},
                )
            milestone_cap = milestone_caps.get(milestone_id, {})
            goal_permissions = goal_cap.get("phase_permissions", {})
            for scope_index, scope in enumerate(definition["allowed_write_scope"]):
                if not any(
                    self._scope_contains(allowed_scope, scope)
                    for allowed_scope in global_scopes
                ):
                    raise RuntimeRejection(
                        "AUTHORIZATION_BOUNDARY_VIOLATION",
                        f"/goal_definition_registry/{goal_id}/allowed_write_scope/{scope_index}",
                        {"reason": "GOAL_SCOPE_EXCEEDS_GLOBAL_SCOPE"},
                    )
            for permission in PHASE_PERMISSION_FIELDS:
                requested = definition["phase_permissions"].get(permission) is True
                top_allowed = top_level.get(permission) is True
                milestone_allowed = milestone_cap.get(permission) is True
                goal_allowed = goal_permissions.get(permission) is True
                if goal_allowed and (not top_allowed or not milestone_allowed):
                    raise RuntimeRejection(
                        "AUTHORIZATION_BOUNDARY_VIOLATION",
                        f"{path}/phase_permission_caps/by_goal/{goal_id}/phase_permissions/{permission}",
                        {"reason": "GOAL_CAP_EXCEEDS_PARENT_CAP"},
                    )
                if requested and not (top_allowed and milestone_allowed and goal_allowed):
                    raise RuntimeRejection(
                        "AUTHORIZATION_BOUNDARY_VIOLATION",
                        f"/goal_definition_registry/{goal_id}/phase_permissions/{permission}",
                        {"reason": "GOAL_PERMISSION_DENIED"},
                    )

    def _validate_roadmap_authorization(
        self,
        current: dict[str, Any],
        proposed: dict[str, Any],
        proposed_definitions: dict[str, dict[str, Any]],
        proposed_milestones: list[dict[str, Any]],
    ) -> None:
        if set(proposed) != set(current):
            raise RuntimeRejection(
                "AUTHORIZATION_BOUNDARY_VIOLATION",
                "/mutation/authorization_envelope",
                {"reason": "TOP_LEVEL_AUTHORIZATION_SHAPE_CHANGED"},
            )
        immutable_fields = set(current) - {"phase_permission_caps"}
        if any(proposed.get(field) != current[field] for field in immutable_fields):
            raise RuntimeRejection(
                "AUTHORIZATION_BOUNDARY_VIOLATION",
                "/mutation/authorization_envelope",
                {"reason": "TOP_LEVEL_AUTHORIZATION_CHANGED"},
            )
        current_caps = current["phase_permission_caps"]
        proposed_caps = proposed["phase_permission_caps"]
        for milestone_id, cap in current_caps["by_milestone"].items():
            if proposed_caps["by_milestone"].get(milestone_id) != cap:
                raise RuntimeRejection(
                    "AUTHORIZATION_BOUNDARY_VIOLATION",
                    f"/mutation/authorization_envelope/phase_permission_caps/by_milestone/{milestone_id}",
                    {"reason": "EXISTING_MILESTONE_CAP_CHANGED"},
                )
        for goal_id, cap in current_caps["by_goal"].items():
            if proposed_caps["by_goal"].get(goal_id) != cap:
                raise RuntimeRejection(
                    "AUTHORIZATION_BOUNDARY_VIOLATION",
                    f"/mutation/authorization_envelope/phase_permission_caps/by_goal/{goal_id}",
                    {"reason": "EXISTING_GOAL_CAP_CHANGED"},
                )
        self._validate_authorization_boundary(
            proposed_definitions,
            proposed_milestones,
            proposed,
            "/mutation/authorization_envelope",
        )

    @staticmethod
    def _reject_cycles(graph: dict[str, list[str]], code: str, path: str) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visited:
                return
            if node in visiting:
                raise RuntimeRejection(code, path)
            visiting.add(node)
            for dependency in graph[node]:
                visit(dependency)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)

    @staticmethod
    def _validate_scope(scope: str, path: str) -> None:
        if (
            not scope
            or "\x00" in scope
            or "\\" in scope
            or scope.startswith(("/", "http://", "https://"))
        ):
            raise RuntimeRejection("PATH_SCOPE_ESCAPE", path)
        parts = PurePosixPath(scope).parts
        if ".." in parts or ".codex-loop" in parts:
            raise RuntimeRejection("PATH_SCOPE_ESCAPE", path)

    @staticmethod
    def _scope_contains(parent: str, child: str) -> bool:
        if parent == child or parent == "**":
            return True
        if parent.endswith("/**"):
            prefix = parent[:-3].rstrip("/")
            return child == prefix or child.startswith(prefix + "/")
        if parent.endswith("/*") and not child.endswith(("/*", "/**")):
            prefix = parent[:-2].rstrip("/")
            relative = child[len(prefix) + 1 :] if child.startswith(prefix + "/") else ""
            return bool(relative) and "/" not in relative
        return False

    def _validate_thread_registry(self, state: dict[str, Any]) -> None:
        controllers = 0
        state_writers = 0
        project_ids: set[str] = set()
        active_role_keys: set[tuple[str, str]] = set()
        for key, record in state["thread_registry"].items():
            if key != record["thread_id"]:
                raise RuntimeRejection("THREAD_IDENTITY_INVALID", f"/thread_registry/{key}")
            controllers += record["role_kind"] == "CONTROLLER" and record["status"] == "REGISTERED"
            state_writers += record["role_kind"] == "STATE_WRITER" and record["status"] == "REGISTERED"
            project_ids.add(record["project_id"])
            if record["task_kind"] != "PROJECT_TASK":
                raise RuntimeRejection("THREAD_TASK_KIND_INVALID", f"/thread_registry/{key}")
            bootstrap_role_kind = record["bootstrap_role_kind"]
            expected_formal_role = {
                "controller": "CONTROLLER",
                "state_writer": "STATE_WRITER",
                **BOOTSTRAP_ROLE_TO_FORMAL_ROLE,
            }.get(bootstrap_role_kind)
            if expected_formal_role != record["role_kind"]:
                raise RuntimeRejection(
                    "THREAD_ROLE_MAPPING_INVALID", f"/thread_registry/{key}"
                )
            if (
                record["status"] == "REGISTERED"
                and record["role_kind"] not in {"CONTROLLER", "STATE_WRITER"}
            ):
                role_key = (record["role_kind"], record["bootstrap_role_kind"])
                if role_key in active_role_keys:
                    raise RuntimeRejection(
                        "THREAD_ROLE_ALREADY_REGISTERED",
                        f"/thread_registry/{key}",
                    )
                active_role_keys.add(role_key)
            worktree_path = record["worktree_path"]
            if worktree_path is not None:
                self._assert_authorized_worktree(
                    state,
                    Path(worktree_path),
                    f"/thread_registry/{key}/worktree_path",
                )
        if controllers != 1 or state_writers != 1:
            raise RuntimeRejection("CORE_THREAD_REGISTRY_INVALID", "/thread_registry")
        if len(project_ids) != 1:
            raise RuntimeRejection("THREAD_PROJECT_IDENTITY_CONFLICT", "/thread_registry")
        child_count = sum(
            record["role_kind"] != "CONTROLLER"
            for record in state["thread_registry"].values()
        )
        max_children = state["authorization_envelope"]["control_plane_limits"][
            "max_child_threads"
        ]
        if child_count > max_children:
            raise RuntimeRejection(
                "THREAD_BUDGET_EXHAUSTED",
                "/thread_registry",
                {"child_count": child_count, "max_child_threads": max_children},
            )

    def _validate_outboxes(self, state: dict[str, Any]) -> None:
        seen: dict[str, str] = {}
        thread_semantic_keys: set[tuple[Any, ...]] = set()
        active_thread_outboxes = 0
        business_automations = 0
        for kind, field in OUTBOX_FIELDS.items():
            for outbox_id, record in state[field].items():
                if outbox_id != record["outbox_id"] or record["outbox_kind"] != kind:
                    raise RuntimeRejection("OUTBOX_IDENTITY_INVALID", f"/{field}/{outbox_id}")
                other = seen.get(outbox_id)
                if other is not None and other != kind:
                    raise RuntimeRejection("OUTBOX_ID_CONFLICT", f"/{field}/{outbox_id}")
                seen[outbox_id] = kind
                self._validate_nested_paths(
                    state, record["identity"], f"/{field}/{outbox_id}/identity"
                )
                if record["result"] is not None:
                    self._validate_nested_paths(
                        state, record["result"], f"/{field}/{outbox_id}/result"
                    )
                if kind == "THREAD" and record["status"] != "CANCELLED":
                    identity = record["identity"]
                    semantic_key = (
                        identity.get("project_id"),
                        identity.get("bootstrap_role_kind"),
                        identity.get("formal_role_kind"),
                    )
                    if semantic_key in thread_semantic_keys:
                        raise RuntimeRejection(
                            "THREAD_ACTION_DUPLICATE",
                            f"/{field}/{outbox_id}",
                        )
                    thread_semantic_keys.add(semantic_key)
                    if record["status"] in ACTIVE_OUTBOX_STATUSES:
                        active_thread_outboxes += 1
                elif kind == "AUTOMATION" and record["status"] != "CANCELLED":
                    business_automations += 1
        limits = state["authorization_envelope"]["control_plane_limits"]
        registered_children = sum(
            record["role_kind"] != "CONTROLLER"
            for record in state["thread_registry"].values()
        )
        if registered_children + active_thread_outboxes > limits["max_child_threads"]:
            raise RuntimeRejection(
                "THREAD_BUDGET_EXHAUSTED",
                "/thread_creation_outbox",
            )
        if business_automations > limits["max_business_heartbeats"]:
            raise RuntimeRejection(
                "BUSINESS_HEARTBEAT_ALREADY_REGISTERED",
                "/automation_outbox",
            )

    @staticmethod
    def _validate_assurance_consistency(state: dict[str, Any]) -> None:
        by_dispatch: dict[str, dict[str, Any]] = {}
        for review_id, review in state["assurance_ledger"].items():
            dispatch_id = review["review_dispatch_id"]
            if dispatch_id in by_dispatch:
                raise RuntimeRejection(
                    "ASSURANCE_LEDGER_DISPATCH_CONFLICT",
                    f"/assurance_ledger/{review_id}/review_dispatch_id",
                )
            by_dispatch[dispatch_id] = review

        for dispatch_id, outbox in state["assurance_dispatch_outbox"].items():
            review = by_dispatch.pop(dispatch_id, None)
            if outbox["status"] != "COMPLETED":
                if review is not None:
                    raise RuntimeRejection(
                        "ASSURANCE_STATE_INCONSISTENT",
                        f"/assurance_dispatch_outbox/{dispatch_id}",
                        {"reason": "LEDGER_WITHOUT_COMPLETED_OUTBOX"},
                    )
                continue
            result = outbox.get("result")
            expected = (
                {
                    "status": review["decision"],
                    "report_digest": review["report_digest"],
                    "artifact_digest": review["artifact_digest"],
                }
                if review is not None
                else None
            )
            if review is None or result != expected:
                raise RuntimeRejection(
                    "ASSURANCE_STATE_INCONSISTENT",
                    f"/assurance_dispatch_outbox/{dispatch_id}",
                    {"reason": "ACK_RESULT_LEDGER_MISMATCH"},
                )
        if by_dispatch:
            dispatch_id = sorted(by_dispatch)[0]
            raise RuntimeRejection(
                "ASSURANCE_STATE_INCONSISTENT",
                f"/assurance_ledger/{by_dispatch[dispatch_id]['review_id']}",
                {"reason": "LEDGER_OUTBOX_MISSING"},
            )

    def _validate_finalization_state(self, state: dict[str, Any]) -> None:
        terminal = state["terminal_status"]
        outbox = state["finalization_outbox"]
        receipt = state["finalization_receipt"]
        if terminal is None:
            if outbox is not None or receipt is not None:
                raise RuntimeRejection(
                    "FINALIZATION_STATE_INCONSISTENT",
                    "/finalization_outbox",
                    {"reason": "NONTERMINAL_WITH_FINALIZATION"},
                )
            return
        if not isinstance(outbox, dict):
            raise RuntimeRejection(
                "FINALIZATION_STATE_INCONSISTENT",
                "/finalization_outbox",
                {"reason": "TERMINAL_WITHOUT_OUTBOX"},
            )
        outcome = outbox["outcome_kind"]
        blocker_fields = (
            outbox["blocker_code"],
            outbox["blocker_fingerprint"],
            outbox["blocker_report_path"],
            outbox["blocker_report_digest"],
        )
        if outcome == "SUCCESS":
            if (
                terminal not in {"LOOP_COMPLETE", "LOOP_COMPLETE_WITH_LIMITATION"}
                or outbox["controller_goal_target_status"] != "COMPLETE"
                or any(value is not None for value in blocker_fields)
                or outbox["blocker_observations"] != []
            ):
                raise RuntimeRejection(
                    "FINALIZATION_STATE_INCONSISTENT",
                    "/finalization_outbox",
                    {"reason": "SUCCESS_OUTCOME_MISMATCH"},
                )
        elif (
            outcome != "BLOCKED"
            or terminal != "LOOP_BLOCKED"
            or outbox["controller_goal_target_status"] != "BLOCKED"
            or any(not isinstance(value, str) or not value for value in blocker_fields)
            or len(outbox["blocker_observations"]) != 3
        ):
            raise RuntimeRejection(
                "FINALIZATION_STATE_INCONSISTENT",
                "/finalization_outbox",
                {"reason": "BLOCKED_OUTCOME_MISMATCH"},
            )
        if outbox["automation_target_status"] != "PAUSED":
            raise RuntimeRejection(
                "FINALIZATION_STATE_INCONSISTENT",
                "/finalization_outbox/automation_target_status",
            )
        if (outbox["status"] == "ACKED") != (receipt is not None):
            raise RuntimeRejection(
                "FINALIZATION_STATE_INCONSISTENT",
                "/finalization_receipt",
                {"reason": "OUTBOX_RECEIPT_STATUS_MISMATCH"},
            )
        if receipt is None:
            return
        receipt_matches = {
            "finalization_id": outbox["finalization_id"],
            "controller_goal_id": outbox["controller_goal_id"],
            "controller_goal_status": outbox["controller_goal_target_status"],
            "automation_id": outbox["automation_id"],
            "automation_status": outbox["automation_target_status"],
            "outcome_kind": outbox["outcome_kind"],
            "blocker_code": outbox["blocker_code"],
            "blocker_fingerprint": outbox["blocker_fingerprint"],
            "blocker_observations": outbox["blocker_observations"],
            "blocker_report_path": outbox["blocker_report_path"],
            "blocker_report_digest": outbox["blocker_report_digest"],
        }
        if any(receipt.get(key) != value for key, value in receipt_matches.items()):
            raise RuntimeRejection(
                "FINALIZATION_STATE_INCONSISTENT",
                "/finalization_receipt",
                {"reason": "RECEIPT_IDENTITY_MISMATCH"},
            )
        controller_goal = state["controller_goal"]
        if (
            not isinstance(controller_goal, dict)
            or controller_goal.get("goal_id") != outbox["controller_goal_id"]
            or controller_goal.get("status") != outbox["controller_goal_target_status"]
        ):
            raise RuntimeRejection(
                "FINALIZATION_STATE_INCONSISTENT",
                "/controller_goal",
                {"reason": "CONTROLLER_GOAL_RECEIPT_MISMATCH"},
            )
        automation_matches = [
            record
            for record in state["automation_outbox"].values()
            if record["status"] == "ACKED"
            and isinstance(record.get("result"), dict)
            and record["result"].get("automation_id") == outbox["automation_id"]
        ]
        if (
            len(automation_matches) != 1
            or automation_matches[0]["result"].get("status") != "PAUSED"
        ):
            raise RuntimeRejection(
                "FINALIZATION_STATE_INCONSISTENT",
                "/automation_outbox",
                {"reason": "AUTOMATION_RECEIPT_MISMATCH"},
            )

    def _validate_nested_paths(
        self, state: dict[str, Any], value: Any, path: str
    ) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}/{key}"
                if key == "worktree_path" and isinstance(child, str):
                    candidate = self.root / child if not Path(child).is_absolute() else Path(child)
                    self._assert_authorized_worktree(state, candidate, child_path)
                elif key.endswith("_path") and isinstance(child, str):
                    candidate = self.root / child if not Path(child).is_absolute() else Path(child)
                    self._assert_confined(candidate, self.root, child_path)
                elif key.endswith("_paths") and isinstance(child, list):
                    for index, item in enumerate(child):
                        if not isinstance(item, str):
                            raise RuntimeRejection("EVIDENCE_PATH_INVALID", f"{child_path}/{index}")
                        candidate = self.root / item if not Path(item).is_absolute() else Path(item)
                        self._assert_confined(candidate, self.root, f"{child_path}/{index}")
                else:
                    self._validate_nested_paths(state, child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self._validate_nested_paths(state, child, f"{path}/{index}")

    def _validate_lease_state(self, state: dict[str, Any]) -> None:
        lease = state["controller_lease"]
        consumed = state["consumed_controller_lease_ids"]
        if len(consumed) != len(set(consumed)):
            raise RuntimeRejection("CONSUMED_LEASE_ID_CONFLICT", "/consumed_controller_lease_ids")
        if state["routing_turn_count"] != len(state["routing_turn_ledger"]):
            raise RuntimeRejection("ROUTING_TURN_COUNT_INVALID", "/routing_turn_count")
        if state["routing_turn_count"] > state["max_routing_turns"]:
            raise RuntimeRejection("ROUTING_BUDGET_EXHAUSTED", "/routing_turn_count")
        active_outboxes = [
            record
            for kind, field in OUTBOX_FIELDS.items()
            for record in state[field].values()
            if record["status"] in ACTIVE_OUTBOX_STATUSES
            or (kind == "ASSURANCE" and record["status"] == "ACKED")
        ]
        if lease is None:
            if active_outboxes:
                raise RuntimeRejection(
                    "ACTIVE_OUTBOX_LEASE_INVALID",
                    "/controller_lease",
                )
            return
        claim = lease["claim"]
        if claim["lease_id"] in consumed:
            raise RuntimeRejection("ACTIVE_LEASE_ALREADY_CONSUMED", "/controller_lease")
        if claim["lease_epoch"] > state["lease_epoch_counter"]:
            raise RuntimeRejection("LEASE_EPOCH_INVALID", "/controller_lease/claim/lease_epoch")
        turn = state["routing_turn_ledger"].get(lease["routing_turn_id"])
        if (
            turn is None
            or turn["lease_id"] != claim["lease_id"]
            or turn["owner_kind"] != claim["owner_kind"]
            or turn["owner_identity"] != claim["owner_identity"]
            or turn["status"] != "LEASE_ACQUIRED"
        ):
            raise RuntimeRejection("LEASE_ROUTING_TURN_INVALID", "/controller_lease")
        matching = [
            record
            for record in active_outboxes
            if record["lease_claim"] == claim
        ]
        if len(matching) != len(active_outboxes) or len(matching) > 1:
            raise RuntimeRejection(
                "LEASE_ACTIVE_OUTBOX_AMBIGUOUS",
                "/controller_lease",
            )
        if matching and lease["route_action"] != {
            "action_type": "OUTBOX",
            "action_id": matching[0]["outbox_id"],
        }:
            raise RuntimeRejection(
                "LEASE_RECOVERY_ACTION_MISMATCH",
                "/controller_lease/route_action",
            )

    def _event_index_locked(
        self, *, repair_incomplete_tail: bool = False
    ) -> dict[str, dict[str, Any]]:
        if not self.events_path.exists():
            return {}
        self._reject_symlink(self.events_path, "/events")
        payload = self.events_path.read_bytes()
        if payload and not payload.endswith(b"\n"):
            if not repair_incomplete_tail:
                raise RuntimeRejection(
                    "RECOVERY_REQUIRED",
                    "/events",
                    {"reason": "INCOMPLETE_EVENT_TAIL"},
                )
            split = payload.rfind(b"\n")
            head = payload[: split + 1] if split >= 0 else b""
            tail = payload[split + 1 :]
            try:
                tail_text = tail.decode("utf-8")
                _strict_json_loads(tail_text, code="EVENT_LOG_INVALID", path="/events")
            except (UnicodeDecodeError, RuntimeRejection):
                with self.events_path.open("r+b") as handle:
                    handle.truncate(len(head))
                    handle.flush()
                    os.fsync(handle.fileno())
                self._fsync_dir(self.control_dir)
                payload = head
            else:
                with self.events_path.open("ab") as handle:
                    handle.write(b"\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                payload += b"\n"
        index: dict[str, dict[str, Any]] = {}
        for line_number, raw_line in enumerate(payload.splitlines(), start=1):
            if not raw_line:
                raise RuntimeRejection("EVENT_LOG_INVALID", f"/events/{line_number}")
            try:
                text = raw_line.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise RuntimeRejection("EVENT_LOG_INVALID", f"/events/{line_number}") from exc
            event = _strict_json_loads(
                text,
                code="EVENT_LOG_INVALID",
                path=f"/events/{line_number}",
            )
            event_id = event.get("event_id") if isinstance(event, dict) else None
            if not isinstance(event_id, str) or SAFE_ID_RE.fullmatch(event_id) is None:
                raise RuntimeRejection("EVENT_LOG_INVALID", f"/events/{line_number}/event_id")
            if event_id in index:
                raise RuntimeRejection("EVENT_LOG_DUPLICATE_ID", f"/events/{line_number}/event_id")
            index[event_id] = event
        return index

    def _append_event_locked(self, event: dict[str, Any]) -> None:
        index = self._event_index_locked()
        existing = index.get(event["event_id"])
        if existing is not None:
            if existing != event:
                raise RuntimeRejection("EVENT_ID_CONFLICT", "/event_id")
            return
        line = (_canonical_json(event) + "\n").encode("utf-8")
        self._assert_confined(self.events_path, self.control_dir, "/events")
        self._reject_symlink(self.events_path, "/events")
        descriptor = os.open(
            self.events_path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_APPEND
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            written = os.write(descriptor, line)
            if written != len(line):
                raise OSError("short append")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self._inject("EVENT_APPENDED_FSYNCED")
        self._fsync_dir(self.control_dir)
        self._inject("EVENT_DIR_FSYNCED")

    def _write_state_locked(self, state: dict[str, Any], transaction_id: str) -> None:
        self._atomic_replace_bytes(
            self.state_path,
            self._render_state(state),
            transaction_id,
            "STATE",
        )

    def _write_goals_locked(self, state: dict[str, Any], transaction_id: str) -> None:
        self._atomic_replace_bytes(
            self.goals_path,
            self._render_goals(state),
            transaction_id,
            "GOALS",
        )

    def _write_dashboard_locked(self, state: dict[str, Any], transaction_id: str) -> None:
        payload = self._render_dashboard(state)
        if payload is None:
            if self.dashboard_path.exists() or self.dashboard_path.is_symlink():
                raise RuntimeRejection("UNEXPECTED_DASHBOARD_ARTIFACT", "/dashboard_required")
            return
        self._atomic_replace_bytes(
            self.dashboard_path,
            payload,
            transaction_id,
            "DASHBOARD",
        )

    def _ensure_projections_locked(self, state: dict[str, Any]) -> None:
        expected = self._render_goals(state)
        if not self.goals_path.exists() or self.goals_path.read_bytes() != expected:
            self._write_goals_locked(state, "projection-recovery")
        dashboard = self._render_dashboard(state)
        if dashboard is None:
            if self.dashboard_path.exists() or self.dashboard_path.is_symlink():
                raise RuntimeRejection("UNEXPECTED_DASHBOARD_ARTIFACT", "/dashboard_required")
        elif not self.dashboard_path.exists() or self.dashboard_path.read_bytes() != dashboard:
            self._write_dashboard_locked(state, "projection-recovery")

    def _write_journal_locked(
        self,
        path: Path,
        journal: dict[str, Any],
        *,
        phase: str,
    ) -> None:
        payload = (_canonical_json(journal, indent=2) + "\n").encode("utf-8")
        self._atomic_replace_bytes(
            path,
            payload,
            journal["transaction_id"],
            f"{phase}_JOURNAL",
        )

    def _atomic_replace_bytes(
        self,
        path: Path,
        payload: bytes,
        transaction_id: str,
        stage_prefix: str,
    ) -> None:
        self._reject_symlink(path.parent, f"/{stage_prefix.lower()}/parent")
        self._reject_symlink(path, f"/{stage_prefix.lower()}")
        self._assert_confined(path, path.parent, f"/{stage_prefix.lower()}")
        temp_path = path.parent / f".{path.name}.{transaction_id}.{stage_prefix}.tmp"
        self._reject_symlink(temp_path, f"/{stage_prefix.lower()}/temp")
        self._assert_confined(temp_path, path.parent, f"/{stage_prefix.lower()}/temp")
        descriptor = os.open(
            temp_path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_TRUNC
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            view = memoryview(payload)
            offset = 0
            while offset < len(view):
                written = os.write(descriptor, view[offset:])
                if written <= 0:
                    raise OSError("short replace write")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self._inject(f"{stage_prefix}_TEMP_FSYNCED")
        os.replace(temp_path, path)
        self._inject(f"{stage_prefix}_REPLACED")
        self._fsync_dir(path.parent)
        self._inject(f"{stage_prefix}_DIR_FSYNCED")

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _cleanup_temps_locked(self) -> None:
        changed: set[Path] = set()
        patterns = {
            self.control_dir: (
                ".LOOP_STATE.md.*.STATE.tmp",
                ".GOALS.md.*.GOALS.tmp",
                ".progress-dashboard.html.*.DASHBOARD.tmp",
            ),
            self.transactions_dir: (
                ".*.PREPARED_JOURNAL.tmp",
                ".*.APPLIED_JOURNAL.tmp",
            ),
            self.reports_dir: (".*.ARTIFACT.tmp",),
            self.sources_dir: (".*.ARTIFACT.tmp",),
        }
        for directory, directory_patterns in patterns.items():
            if not directory.exists():
                continue
            for pattern in directory_patterns:
                for path in directory.glob(pattern):
                    self._assert_confined(path, directory, "/temp")
                    path.unlink(missing_ok=True)
                    changed.add(directory)
        for directory in changed:
            self._fsync_dir(directory)

    def _recover_all_locked(self, state_validator: Any) -> int:
        self._cleanup_temps_locked()
        journals: list[tuple[int, str, Path, dict[str, Any]]] = []
        for path in self.transactions_dir.glob("*.json"):
            self._assert_confined(path, self.transactions_dir, "/transactions")
            journal = self._read_journal(path)
            journals.append(
                (
                    journal["expected_state_version"],
                    journal["state_request_id"],
                    path,
                    journal,
                )
            )
        recovered = 0
        event_index = self._event_index_locked(repair_incomplete_tail=True)
        state = self._read_state_locked(state_validator)
        for _, _, path, journal in sorted(journals):
            if self._journal_needs_recovery_locked(journal, state, event_index):
                self._recover_journal_locked(path, journal, state_validator)
                state = self._read_state_locked(state_validator)
                event_index = self._event_index_locked(
                    repair_incomplete_tail=True
                )
                recovered += 1
        return recovered

    def _recovery_required_locked(
        self,
        state_validator: Any,
        state: dict[str, Any] | None = None,
    ) -> list[str]:
        journals: list[dict[str, Any]] = []
        for path in self.transactions_dir.glob("*.json"):
            self._assert_confined(path, self.transactions_dir, "/transactions")
            journals.append(self._read_journal(path))
        event_index = self._event_index_locked()
        current = state if state is not None else self._read_state_locked(state_validator)
        required = [
            journal["state_request_id"]
            for journal in sorted(
                journals,
                key=lambda item: (
                    item["expected_state_version"],
                    item["state_request_id"],
                ),
            )
            if self._journal_needs_recovery_locked(journal, current, event_index)
        ]
        if self._projections_need_recovery_locked(current):
            required.append("PROJECTIONS")
        return sorted(set(required))

    def _journal_needs_recovery_locked(
        self,
        journal: dict[str, Any],
        state: dict[str, Any] | None,
        event_index: dict[str, dict[str, Any]],
    ) -> bool:
        if journal["status"] != "APPLIED":
            return True
        if journal.get("applied_state_digest") != journal["after_state_digest"]:
            return True
        if state is None:
            return True
        next_version = journal["next_state"]["state_version"]
        request_record = state.get("request_ledger", {}).get(
            journal["state_request_id"]
        )
        event_record = state.get("event_ledger", {}).get(journal["event_id"])
        state_includes = bool(
            request_record
            and request_record.get("request_digest") == journal["request_digest"]
            and request_record.get("event_id") == journal["event_id"]
            and request_record.get("mutation_type") == journal["mutation_type"]
            and request_record.get("applied_state_version") == next_version
            and event_record
            and event_record.get("state_request_id") == journal["state_request_id"]
            and event_record.get("request_digest") == journal["request_digest"]
            and event_record.get("mutation_type") == journal["mutation_type"]
            and event_record.get("applied_state_version") == next_version
            and state["state_version"] >= next_version
        )
        if not state_includes:
            return True
        if event_index.get(journal["event_id"]) != journal["event"]:
            return True
        return any(
            not self._artifact_target(artifact["path"]).exists()
            or _bytes_digest(self._artifact_target(artifact["path"]).read_bytes())
            != artifact["digest"]
            for artifact in journal["artifacts"]
        )

    def _projections_need_recovery_locked(
        self, state: dict[str, Any] | None
    ) -> bool:
        if state is None:
            return False
        if (
            not self.goals_path.exists()
            or self.goals_path.read_bytes() != self._render_goals(state)
        ):
            return True
        dashboard = self._render_dashboard(state)
        if dashboard is None:
            return self.dashboard_path.exists()
        return (
            not self.dashboard_path.exists()
            or self.dashboard_path.read_bytes() != dashboard
        )

    def _read_journal(self, path: Path) -> dict[str, Any]:
        self._reject_symlink(path, "/transactions")
        try:
            payload = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeRejection("JOURNAL_INVALID", "/transactions") from exc
        journal = _strict_json_loads(
            payload,
            code="JOURNAL_INVALID",
            path=f"/transactions/{path.name}",
        )
        required = {
            "journal_version",
            "transaction_id",
            "state_request_id",
            "event_id",
            "status",
            "request_digest",
            "mutation_digest",
            "mutation_type",
            "expected_state_version",
            "before_state_digest",
            "after_state_digest",
            "prepared_at",
            "next_state",
            "event",
            "artifacts",
            "goals_projection",
            "goals_projection_digest",
            "dashboard_projection",
            "dashboard_projection_digest",
        }
        optional = {"applied_state_digest"}
        if not isinstance(journal, dict) or not required.issubset(journal) or not set(journal).issubset(required | optional):
            raise RuntimeRejection("JOURNAL_INVALID", f"/transactions/{path.name}")
        if journal["journal_version"] != 2 or journal["status"] not in {"PREPARED", "APPLIED"}:
            raise RuntimeRejection("JOURNAL_INVALID", f"/transactions/{path.name}/status")
        if (
            journal["status"] == "APPLIED"
            and journal.get("applied_state_digest") != journal["after_state_digest"]
        ):
            raise RuntimeRejection(
                "JOURNAL_DIGEST_CONFLICT",
                f"/transactions/{path.name}/applied_state_digest",
            )
        for key in ("transaction_id", "state_request_id", "event_id", "mutation_type"):
            value = journal[key]
            if not isinstance(value, str) or SAFE_ID_RE.fullmatch(value) is None:
                raise RuntimeRejection("JOURNAL_INVALID", f"/transactions/{path.name}/{key}")
        if (
            journal["transaction_id"] != journal["state_request_id"]
            or path.name != f"{journal['state_request_id']}.json"
        ):
            raise RuntimeRejection("JOURNAL_IDENTITY_CONFLICT", f"/transactions/{path.name}")
        for key in ("request_digest", "mutation_digest", "after_state_digest"):
            if not isinstance(journal[key], str) or DIGEST_RE.fullmatch(journal[key]) is None:
                raise RuntimeRejection("JOURNAL_INVALID", f"/transactions/{path.name}/{key}")
        before_digest = journal["before_state_digest"]
        if before_digest is not None and (
            not isinstance(before_digest, str) or DIGEST_RE.fullmatch(before_digest) is None
        ):
            raise RuntimeRejection("JOURNAL_INVALID", f"/transactions/{path.name}/before_state_digest")
        if not isinstance(journal["expected_state_version"], int) or isinstance(
            journal["expected_state_version"], bool
        ):
            raise RuntimeRejection("JOURNAL_INVALID", f"/transactions/{path.name}/expected_state_version")
        if _bytes_digest(self._render_state(journal["next_state"])) != journal["after_state_digest"]:
            raise RuntimeRejection("JOURNAL_DIGEST_CONFLICT", f"/transactions/{path.name}/next_state")
        goals_projection = journal["goals_projection"]
        if (
            not isinstance(goals_projection, str)
            or not isinstance(journal["goals_projection_digest"], str)
            or DIGEST_RE.fullmatch(journal["goals_projection_digest"]) is None
            or _bytes_digest(goals_projection.encode("utf-8"))
            != journal["goals_projection_digest"]
            or goals_projection.encode("utf-8") != self._render_goals(journal["next_state"])
        ):
            raise RuntimeRejection(
                "JOURNAL_DIGEST_CONFLICT",
                f"/transactions/{path.name}/goals_projection",
            )
        dashboard_projection = journal["dashboard_projection"]
        dashboard_digest = journal["dashboard_projection_digest"]
        expected_dashboard = self._render_dashboard(journal["next_state"])
        if expected_dashboard is None:
            if dashboard_projection is not None or dashboard_digest is not None:
                raise RuntimeRejection(
                    "JOURNAL_DIGEST_CONFLICT",
                    f"/transactions/{path.name}/dashboard_projection",
                )
        elif (
            not isinstance(dashboard_projection, str)
            or not isinstance(dashboard_digest, str)
            or DIGEST_RE.fullmatch(dashboard_digest) is None
            or _bytes_digest(dashboard_projection.encode("utf-8")) != dashboard_digest
            or dashboard_projection.encode("utf-8") != expected_dashboard
        ):
            raise RuntimeRejection(
                "JOURNAL_DIGEST_CONFLICT",
                f"/transactions/{path.name}/dashboard_projection",
            )
        artifacts = journal["artifacts"]
        if not isinstance(artifacts, list):
            raise RuntimeRejection("JOURNAL_INVALID", f"/transactions/{path.name}/artifacts")
        for index, artifact in enumerate(artifacts):
            if (
                not isinstance(artifact, dict)
                or set(artifact) != {"path", "content", "digest", "media_type"}
                or not isinstance(artifact["content"], str)
                or _bytes_digest(artifact["content"].encode("utf-8")) != artifact["digest"]
            ):
                raise RuntimeRejection(
                    "JOURNAL_INVALID",
                    f"/transactions/{path.name}/artifacts/{index}",
                )
        if self._normalize_artifacts(copy.deepcopy(artifacts)) != artifacts:
            raise RuntimeRejection(
                "JOURNAL_INVALID",
                f"/transactions/{path.name}/artifacts",
            )
        event = journal["event"]
        if (
            not isinstance(event, dict)
            or event.get("event_id") != journal["event_id"]
            or event.get("state_request_id") != journal["state_request_id"]
            or event.get("request_digest") != journal["request_digest"]
        ):
            raise RuntimeRejection("JOURNAL_EVENT_CONFLICT", f"/transactions/{path.name}/event")
        return journal

    def _recover_journal_locked(
        self,
        path: Path,
        journal: dict[str, Any],
        state_validator: Any,
    ) -> None:
        next_state = journal["next_state"]
        self._validate_canonical_state(next_state, state_validator)
        current = self._read_state_locked(state_validator)
        current_version = current["state_version"] if current is not None else 0
        current_digest = (
            _bytes_digest(self._render_state(current)) if current is not None else None
        )
        request_record = (
            current.get("request_ledger", {}).get(journal["state_request_id"])
            if current is not None
            else None
        )
        event_record = (
            current.get("event_ledger", {}).get(journal["event_id"])
            if current is not None
            else None
        )
        next_version = next_state["state_version"]
        already_contains = bool(
            request_record
            and request_record.get("request_digest") == journal["request_digest"]
            and request_record.get("event_id") == journal["event_id"]
            and request_record.get("mutation_type") == journal["mutation_type"]
            and request_record.get("applied_state_version") == next_version
            and event_record
            and event_record.get("state_request_id") == journal["state_request_id"]
            and event_record.get("request_digest") == journal["request_digest"]
            and event_record.get("mutation_type") == journal["mutation_type"]
            and event_record.get("applied_state_version") == next_version
            and current_version >= next_version
        )
        state_matches_journal = current_digest == journal["after_state_digest"]
        if not state_matches_journal and not already_contains:
            if current_version != journal["expected_state_version"]:
                raise RuntimeRejection(
                    "JOURNAL_RECOVERY_STATE_CONFLICT",
                    f"/transactions/{path.name}",
                    {
                        "expected": journal["expected_state_version"],
                        "actual": current_version,
                    },
                )
            self._write_artifacts_locked(journal["artifacts"], journal["transaction_id"])
            self._write_state_locked(next_state, journal["transaction_id"])
            state_matches_journal = True
        else:
            self._write_artifacts_locked(journal["artifacts"], journal["transaction_id"])
        if state_matches_journal:
            self._write_goals_locked(next_state, journal["transaction_id"])
            self._write_dashboard_locked(next_state, journal["transaction_id"])
        self._append_event_locked(journal["event"])
        if journal["status"] != "APPLIED":
            journal["status"] = "APPLIED"
            journal["applied_state_digest"] = journal["after_state_digest"]
            self._write_journal_locked(path, journal, phase="APPLIED")

    def _build_journal(
        self,
        request: dict[str, Any],
        request_digest: str,
        before_state: dict[str, Any] | None,
        next_state: dict[str, Any],
        event: dict[str, Any],
    ) -> dict[str, Any]:
        before_digest = (
            _bytes_digest(self._render_state(before_state)) if before_state is not None else None
        )
        dashboard = self._render_dashboard(next_state)
        return {
            "journal_version": 2,
            "transaction_id": request["state_request_id"],
            "state_request_id": request["state_request_id"],
            "event_id": request["event_id"],
            "status": "PREPARED",
            "request_digest": request_digest,
            "mutation_digest": _digest(request["mutation"]),
            "mutation_type": request["mutation"]["type"],
            "expected_state_version": request["expected_state_version"],
            "before_state_digest": before_digest,
            "after_state_digest": _bytes_digest(self._render_state(next_state)),
            "prepared_at": request["occurred_at"],
            "next_state": copy.deepcopy(next_state),
            "event": copy.deepcopy(event),
            "artifacts": copy.deepcopy(request["artifacts"]),
            "goals_projection": self._render_goals(next_state).decode("utf-8"),
            "goals_projection_digest": _bytes_digest(self._render_goals(next_state)),
            "dashboard_projection": dashboard.decode("utf-8") if dashboard is not None else None,
            "dashboard_projection_digest": _bytes_digest(dashboard) if dashboard is not None else None,
        }

    def _build_event(
        self,
        request: dict[str, Any],
        request_digest: str,
        before_version: int,
        after_version: int,
        state: dict[str, Any],
        operation_result: dict[str, Any],
    ) -> dict[str, Any]:
        mutation = request["mutation"]
        event: dict[str, Any] = {
            "event_id": request["event_id"],
            "timestamp": request["occurred_at"],
            "actor": request["actor"],
            "thread_id": request["thread_id"],
            "event_type": mutation["type"],
            "status_code": operation_result["code"],
            "state_version_before": before_version,
            "state_version_after": after_version,
            "roadmap_version": state["roadmap_version"],
            "state_request_id": request["state_request_id"],
            "transaction_id": request["state_request_id"],
            "request_digest": request_digest,
            "mutation_digest": _digest(mutation),
            "evidence_paths": request["evidence_paths"],
            "next_action_code": operation_result.get("next_action_code", "NONE"),
        }
        if "outbox_id" in mutation:
            event["outbox_id"] = mutation["outbox_id"]
        if "goal_id" in mutation:
            event["goal_id"] = mutation["goal_id"]
        elif "source_goal_id" in mutation:
            event["goal_id"] = mutation["source_goal_id"]
        elif "final_goal_id" in mutation:
            event["goal_id"] = mutation["final_goal_id"]
        return event

    def _record_idempotency(
        self,
        state: dict[str, Any],
        request: dict[str, Any],
        request_digest: str,
        after_version: int,
    ) -> None:
        request_id = request["state_request_id"]
        event_id = request["event_id"]
        mutation_type = request["mutation"]["type"]
        state["request_ledger"][request_id] = {
            "request_digest": request_digest,
            "event_id": event_id,
            "mutation_type": mutation_type,
            "applied_state_version": after_version,
        }
        state["event_ledger"][event_id] = {
            "state_request_id": request_id,
            "request_digest": request_digest,
            "mutation_type": mutation_type,
            "applied_state_version": after_version,
        }
        state["last_state_request_id"] = request_id
        state["last_event_id"] = event_id
        state["last_transaction_id"] = request_id

    def _check_idempotency_locked(
        self,
        request: dict[str, Any],
        request_digest: str,
        state: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        request_id = request["state_request_id"]
        event_id = request["event_id"]
        journal_path = self._journal_path(request_id)
        journal = self._read_journal(journal_path) if journal_path.exists() else None
        state_request = state.get("request_ledger", {}).get(request_id) if state else None
        state_event = state.get("event_ledger", {}).get(event_id) if state else None
        event_record = self._event_index_locked().get(event_id)

        applied_version = state["state_version"] if state else 0
        if journal is not None and journal["request_digest"] != request_digest:
            raise RuntimeRejection(
                "STATE_REQUEST_ID_CONFLICT",
                "/state_request_id",
                {"state_request_id": request_id},
            )
        if state_request is not None:
            if state_request["request_digest"] != request_digest:
                raise RuntimeRejection(
                    "STATE_REQUEST_ID_CONFLICT",
                    "/state_request_id",
                    {"state_request_id": request_id},
                )
            applied_version = state_request["applied_state_version"]
            if (
                journal is None
                or journal["status"] != "APPLIED"
                or journal["next_state"]["state_version"] != applied_version
                or state_request.get("event_id") != event_id
                or state_event is None
                or state_event.get("state_request_id") != request_id
                or state_event.get("request_digest") != request_digest
                or state_event.get("applied_state_version") != applied_version
                or event_record != journal["event"]
            ):
                raise RuntimeRejection(
                    "RECOVERY_REQUIRED",
                    "/transactions",
                    {"state_request_id": request_id},
                )
            return self._already_applied_response(request, applied_version)
        if journal is not None:
            raise RuntimeRejection(
                "RECOVERY_REQUIRED",
                "/transactions",
                {"state_request_id": request_id},
            )

        if state_event is not None:
            raise RuntimeRejection(
                "EVENT_ID_CONFLICT",
                "/event_id",
                {"event_id": event_id},
            )
        if event_record is not None:
            raise RuntimeRejection(
                "RECOVERY_REQUIRED",
                "/events",
                {"event_id": event_id},
            )
        return None

    def _applied_response(
        self,
        request: dict[str, Any],
        before_version: int,
        after_version: int,
        state: dict[str, Any],
        operation_result: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "STATE_WRITE_APPLIED",
            "operation_status": operation_result["code"],
            "state_request_id": request["state_request_id"],
            "event_id": request["event_id"],
            "state_version_before": before_version,
            "state_version_after": after_version,
            "roadmap_version": state["roadmap_version"],
            "terminal_status": state["terminal_status"],
            "result": operation_result.get("result", {}),
            "evidence_paths": self._transaction_evidence_paths(
                request["state_request_id"], request.get("artifacts", [])
            ),
            "external_actions": [],
            "external_action_count": 0,
        }

    def _already_applied_response(
        self, request: dict[str, Any], applied_version: int
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "STATE_WRITE_ALREADY_APPLIED",
            "operation_status": "IDEMPOTENT_REPLAY",
            "state_request_id": request["state_request_id"],
            "event_id": request["event_id"],
            "state_version_after": applied_version,
            "evidence_paths": self._transaction_evidence_paths(
                request["state_request_id"], request.get("artifacts", [])
            ),
            "external_actions": [],
            "external_action_count": 0,
        }

    def _rejection_response(
        self,
        rejection: RuntimeRejection,
        *,
        state_version: int,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response: dict[str, Any] = {
            "ok": False,
            "status": rejection.code,
            "error": {
                "code": rejection.code,
                "path": rejection.path,
                "details": rejection.details,
            },
            "state_version": state_version,
            "evidence_paths": self._existing_evidence_paths(),
            "external_actions": [],
            "external_action_count": 0,
        }
        if request is not None:
            response["state_request_id"] = request.get("state_request_id")
            response["event_id"] = request.get("event_id")
        return response

    @staticmethod
    def _relative_control_path(name: str) -> str:
        return f".codex-loop/{name}"

    def _base_evidence_paths(self) -> list[str]:
        paths = [
            self._relative_control_path("LOOP_STATE.md"),
            self._relative_control_path("LOOP_EVENTS.jsonl"),
            self._relative_control_path("GOALS.md"),
        ]
        if self.dashboard_path.exists():
            paths.append(self._relative_control_path("progress-dashboard.html"))
        return paths

    def _existing_evidence_paths(self) -> list[str]:
        paths: list[str] = []
        if self.state_path.exists():
            paths.append(self._relative_control_path("LOOP_STATE.md"))
        if self.events_path.exists():
            paths.append(self._relative_control_path("LOOP_EVENTS.jsonl"))
        if self.goals_path.exists():
            paths.append(self._relative_control_path("GOALS.md"))
        if self.dashboard_path.exists():
            paths.append(self._relative_control_path("progress-dashboard.html"))
        return paths

    def _transaction_evidence_paths(
        self,
        request_id: str,
        artifacts: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        return [
            *self._base_evidence_paths(),
            *(artifact["path"] for artifact in artifacts or []),
            self._relative_control_path(f"transactions/{request_id}.json"),
        ]

    def _apply_mutation(
        self,
        state: dict[str, Any] | None,
        request: dict[str, Any],
        after_version: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        mutation = request["mutation"]
        mutation_type = mutation["type"]
        if mutation_type == "INITIALIZE":
            return self._initialize_state(request, mutation), {
                "code": "LOOP_INITIALIZED",
                "next_action_code": "ACQUIRE_LEASE",
            }
        if state is None:
            raise RuntimeRejection("STATE_NOT_INITIALIZED", "/mutation/type")
        if state["terminal_status"] is not None and mutation_type != "ACK_FINALIZATION":
            raise RuntimeRejection("LOOP_ALREADY_TERMINAL", "/mutation/type")
        if state["terminal_status"] is None and mutation_type == "ACK_FINALIZATION":
            raise RuntimeRejection("LOOP_NOT_FINALIZED", "/mutation/type")

        candidate = copy.deepcopy(state)
        if mutation_type == "ACQUIRE_LEASE":
            result = self._acquire_lease(candidate, request, mutation)
        elif mutation_type == "RELEASE_LEASE":
            result = self._release_lease(candidate, mutation, after_version)
        elif mutation_type == "RENEW_LEASE":
            result = self._renew_lease(candidate, request, mutation)
        elif mutation_type == "TAKEOVER_LEASE":
            result = self._takeover_lease(candidate, request, mutation)
        elif mutation_type == "PREPARE_OUTBOX":
            result = self._prepare_outbox(candidate, mutation, after_version)
        elif mutation_type == "CANCEL_OUTBOX":
            result = self._cancel_outbox(candidate, mutation, after_version)
        elif mutation_type == "MARK_OUTBOX_SENT":
            result = self._mark_outbox_sent(candidate, mutation)
        elif mutation_type == "ACK_OUTBOX":
            result = self._ack_outbox(candidate, request, mutation, after_version)
        elif mutation_type == "RECORD_REVIEW":
            result = self._record_review(candidate, request, mutation, after_version)
        elif mutation_type == "ROADMAP_REVISION":
            result = self._roadmap_revision(
                candidate,
                mutation,
                request["state_request_id"],
                request["evidence_paths"],
                after_version,
            )
        elif mutation_type == "FINALIZE_LOOP":
            result = self._finalize_loop(candidate, mutation, after_version)
        elif mutation_type == "STOP_LOOP":
            result = self._stop_loop(candidate, mutation, request, after_version)
        elif mutation_type == "ACK_FINALIZATION":
            result = self._ack_finalization(
                candidate,
                mutation,
                request,
                request["evidence_paths"],
                after_version,
            )
        else:
            raise RuntimeRejection("MUTATION_TYPE_UNSUPPORTED", "/mutation/type")
        return candidate, result

    def _initialize_state(
        self,
        request: dict[str, Any],
        mutation: dict[str, Any],
    ) -> dict[str, Any]:
        pack_artifacts = [
            artifact
            for artifact in request["artifacts"]
            if artifact["path"] == ".codex-loop/sources/CONTROLLER_PACK.md"
        ]
        if len(pack_artifacts) != 1 or len(request["artifacts"]) != 1:
            raise RuntimeRejection(
                "CONTROLLER_PACK_ARTIFACT_REQUIRED",
                "/artifacts",
            )
        pack_artifact = pack_artifacts[0]
        if (
            pack_artifact["digest"] != mutation["controller_pack_digest"]
            or pack_artifact["media_type"] != "text/markdown"
        ):
            raise RuntimeRejection(
                "CONTROLLER_PACK_IDENTITY_MISMATCH",
                "/mutation/controller_pack_digest",
            )
        roadmap_version = 1
        definitions = copy.deepcopy(mutation["goal_definition_registry"])
        queue = copy.deepcopy(mutation["goal_queue"])
        for entry in queue:
            if entry["roadmap_version"] != roadmap_version:
                raise RuntimeRejection(
                    "ROADMAP_VERSION_CONFLICT", "/mutation/goal_queue"
                )
        queue_by_goal = {entry["goal_id"]: entry for entry in queue}
        goal_ledger: dict[str, dict[str, Any]] = {}
        for goal_id, definition in definitions.items():
            entry = queue_by_goal.get(goal_id)
            status = entry["status"] if entry is not None else "PLANNED"
            goal_ledger[goal_id] = {
                "goal_id": goal_id,
                "milestone_id": definition["milestone_id"],
                "definition_digest": definition["payload_template_digest"],
                "status": status,
                "attempts": [],
                "latest_worker": None,
                "completed_roadmap_version": None,
            }
        authorization = copy.deepcopy(mutation["authorization_envelope"])
        active = [
            item["milestone_id"]
            for item in mutation["milestones"]
            if item["status"] == "ACTIVE"
        ]
        active_id = active[0] if len(active) == 1 else None
        controller_id = mutation["controller_thread_id"]
        state_writer_id = mutation["state_writer_thread_id"]
        if controller_id == state_writer_id:
            raise RuntimeRejection("CORE_THREAD_ID_CONFLICT", "/mutation/state_writer_thread_id")
        projection = None
        if "projection_digest" in mutation:
            projection = {
                "roadmap_version": roadmap_version,
                "projection_digest": mutation["projection_digest"],
            }
        return {
            "schema_version": 1,
            "loop_id": mutation["loop_id"],
            "root": str(self.root),
            "controller_pack_identity": {
                "path": pack_artifact["path"],
                "digest": pack_artifact["digest"],
                "media_type": pack_artifact["media_type"],
            },
            "dashboard_required": mutation["dashboard_required"],
            "state_version": 1,
            "roadmap_version": roadmap_version,
            "terminal_status": None,
            "logical_time": request["occurred_at"],
            "active_milestone_id": active_id,
            "milestones": copy.deepcopy(mutation["milestones"]),
            "goal_queue": queue,
            "goal_definition_registry": definitions,
            "goal_execution_ledger": goal_ledger,
            "local_verification_required_goal_ids": sorted(
                mutation.get("local_verification_required_goal_ids", [])
            ),
            "authorization_envelope": copy.deepcopy(authorization),
            "thread_registry": {
                controller_id: {
                    "thread_id": controller_id,
                    "project_id": mutation["project_id"],
                    "task_kind": "PROJECT_TASK",
                    "bootstrap_role_kind": "controller",
                    "role_kind": "CONTROLLER",
                    "bootstrap_prompt_digest": mutation[
                        "controller_bootstrap_prompt_digest"
                    ],
                    "status": "REGISTERED",
                    "worktree_path": str(self.root),
                },
                state_writer_id: {
                    "thread_id": state_writer_id,
                    "project_id": mutation["project_id"],
                    "task_kind": "PROJECT_TASK",
                    "bootstrap_role_kind": "state_writer",
                    "role_kind": "STATE_WRITER",
                    "bootstrap_prompt_digest": mutation[
                        "state_writer_bootstrap_prompt_digest"
                    ],
                    "status": "REGISTERED",
                    "worktree_path": str(self.root),
                },
            },
            "controller_goal": None,
            "controller_lease": None,
            "lease_epoch_counter": 0,
            "consumed_controller_lease_ids": [],
            "routing_turn_count": 0,
            "max_routing_turns": mutation.get("max_routing_turns", 192),
            "routing_turn_ledger": {},
            "routing_action_ledger": {},
            "dispatch_outbox": {},
            "automation_outbox": {},
            "controller_goal_outbox": {},
            "thread_creation_outbox": {},
            "assurance_dispatch_outbox": {},
            "local_verification_outbox": {},
            "roadmap_change_outbox": {},
            "assurance_ledger": {},
            "local_verification_queue": [],
            "local_verification_ledger": {},
            "goal_queue_history": [],
            "roadmap_projection": projection,
            "estimate_history": [],
            "delegation_ledger": {},
            "subagent_attempt_ledger": {},
            "artifact_ledger": {},
            "finalization_outbox": None,
            "finalization_receipt": None,
            "request_ledger": {},
            "event_ledger": {},
            "last_state_request_id": None,
            "last_event_id": None,
            "last_transaction_id": None,
            "external_action_count": 0,
        }

    def _registered_controller(self, state: dict[str, Any], thread_id: str) -> bool:
        record = state["thread_registry"].get(thread_id)
        return bool(
            record
            and record["role_kind"] == "CONTROLLER"
            and record["status"] == "REGISTERED"
        )

    def _observe_time(self, state: dict[str, Any], observed_at: str, path: str) -> datetime:
        observed = _parse_time(observed_at, path)
        current = _parse_time(state["logical_time"], "/logical_time")
        if observed < current:
            raise RuntimeRejection(
                "LOGICAL_TIME_REGRESSION",
                path,
                {"logical_time": state["logical_time"], "observed_at": observed_at},
            )
        state["logical_time"] = observed_at
        return observed

    @staticmethod
    def _claim_from_lease(lease: dict[str, Any]) -> dict[str, Any]:
        return copy.deepcopy(lease["claim"])

    def _acquire_lease(
        self,
        state: dict[str, Any],
        request: dict[str, Any],
        mutation: dict[str, Any],
    ) -> dict[str, Any]:
        observed = self._observe_time(state, mutation["observed_at"], "/mutation/observed_at")
        expires = _parse_time(mutation["expires_at"], "/mutation/expires_at")
        if expires <= observed:
            raise RuntimeRejection("LEASE_EXPIRY_INVALID", "/mutation/expires_at")
        if not self._registered_controller(state, mutation["owner_identity"]):
            raise RuntimeRejection(
                "CONTROLLER_IDENTITY_MISMATCH", "/mutation/owner_identity"
            )
        if state["controller_lease"] is not None:
            current_expiry = _parse_time(
                state["controller_lease"]["expires_at"], "/controller_lease/expires_at"
            )
            code = (
                "WAITING_CONTROLLER_LEASE"
                if observed < current_expiry
                else "CONTROLLER_LEASE_EXPIRED_TAKEOVER_REQUIRED"
            )
            raise RuntimeRejection(code, "/controller_lease")
        routing_turn_id = mutation["routing_turn_id"]
        lease_id = mutation["lease_id"]
        if routing_turn_id in state["routing_turn_ledger"]:
            raise RuntimeRejection("ROUTING_TURN_ID_CONFLICT", "/mutation/routing_turn_id")
        if (
            lease_id in state["consumed_controller_lease_ids"]
            or lease_id in state["routing_action_ledger"]
            or any(
                item["lease_id"] == lease_id
                for item in state["routing_turn_ledger"].values()
            )
        ):
            raise RuntimeRejection("LEASE_ID_CONFLICT", "/mutation/lease_id")
        if state["routing_turn_count"] >= state["max_routing_turns"]:
            raise RuntimeRejection("ROUTING_BUDGET_EXHAUSTED", "/routing_turn_count")
        state["routing_turn_count"] += 1
        state["lease_epoch_counter"] += 1
        claim = {
            "lease_epoch": state["lease_epoch_counter"],
            "lease_id": lease_id,
            "routing_turn_id": routing_turn_id,
            "owner_kind": mutation["owner_kind"],
            "owner_identity": mutation["owner_identity"],
            "intended_transition": mutation.get(
                "intended_transition", INTENDED_TRANSITION
            ),
        }
        state["controller_lease"] = {
            "claim": claim,
            "routing_turn_id": routing_turn_id,
            "acquired_at": mutation["observed_at"],
            "expires_at": mutation["expires_at"],
            "route_action": None,
        }
        state["routing_turn_ledger"][routing_turn_id] = {
            "routing_turn_id": routing_turn_id,
            "event_id": request["event_id"],
            "owner_kind": mutation["owner_kind"],
            "owner_identity": mutation["owner_identity"],
            "lease_id": lease_id,
            "status": "LEASE_ACQUIRED",
        }
        return {
            "code": "CONTROLLER_LEASE_ACQUIRED",
            "next_action_code": "ROUTE_ONE_TRANSITION",
            "result": {"lease_claim": copy.deepcopy(claim)},
        }

    def _require_exact_lease(
        self,
        state: dict[str, Any],
        claim: dict[str, Any],
        observed_at: str,
        *,
        allow_expired: bool = False,
    ) -> dict[str, Any]:
        lease = state["controller_lease"]
        if lease is None or lease["claim"] != claim:
            raise RuntimeRejection("STALE_OR_MISSING_CONTROLLER_LEASE", "/mutation/lease_claim")
        if claim["lease_id"] in state["consumed_controller_lease_ids"]:
            raise RuntimeRejection("STALE_OR_MISSING_CONTROLLER_LEASE", "/mutation/lease_claim")
        if claim["intended_transition"] != INTENDED_TRANSITION:
            raise RuntimeRejection("LEASE_PURPOSE_MISMATCH", "/mutation/lease_claim")
        observed = self._observe_time(state, observed_at, "/mutation/observed_at")
        if not allow_expired and observed >= _parse_time(lease["expires_at"], "/controller_lease/expires_at"):
            raise RuntimeRejection("CONTROLLER_LEASE_EXPIRED", "/mutation/observed_at")
        return lease

    def _reserve_route(
        self,
        lease: dict[str, Any],
        action_type: str,
        action_id: str,
    ) -> None:
        action = {"action_type": action_type, "action_id": action_id}
        current = lease["route_action"]
        if current is None:
            lease["route_action"] = action
            return
        if current != action:
            raise RuntimeRejection(
                "ROUTING_ACTION_ALREADY_USED",
                "/controller_lease/route_action",
                {"action_type": current["action_type"], "action_id": current["action_id"]},
            )

    def _finish_route(
        self,
        state: dict[str, Any],
        claim: dict[str, Any],
        after_version: int,
    ) -> None:
        lease = state["controller_lease"]
        if lease is None or lease["claim"] != claim:
            raise RuntimeRejection("STALE_OR_MISSING_CONTROLLER_LEASE", "/mutation/lease_claim")
        lease_id = claim["lease_id"]
        state["consumed_controller_lease_ids"].append(lease_id)
        state["consumed_controller_lease_ids"] = sorted(
            set(state["consumed_controller_lease_ids"])
        )
        state["routing_action_ledger"][lease_id] = {
            "lease_id": lease_id,
            "routing_turn_id": lease["routing_turn_id"],
            "route_action": copy.deepcopy(lease["route_action"]),
            "completed_state_version": after_version,
        }
        state["routing_turn_ledger"][lease["routing_turn_id"]]["status"] = "COMPLETED"
        state["controller_lease"] = None

    def _active_outboxes_for_claim(
        self, state: dict[str, Any], claim: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return [
            record
            for kind, field in OUTBOX_FIELDS.items()
            for record in state[field].values()
            if (
                record["status"] in ACTIVE_OUTBOX_STATUSES
                or (kind == "ASSURANCE" and record["status"] == "ACKED")
            )
            and record["lease_claim"] == claim
        ]

    def _release_lease(
        self,
        state: dict[str, Any],
        mutation: dict[str, Any],
        after_version: int,
    ) -> dict[str, Any]:
        claim = mutation["lease_claim"]
        lease = self._require_exact_lease(
            state,
            claim,
            mutation["observed_at"],
        )
        if lease["route_action"] is not None:
            raise RuntimeRejection(
                "LEASE_RELEASE_ROUTE_RESERVED",
                "/controller_lease/route_action",
            )
        if self._active_outboxes_for_claim(state, claim):
            raise RuntimeRejection(
                "LEASE_RELEASE_ACTIVE_OUTBOX",
                "/mutation/lease_claim",
            )
        self._finish_route(state, claim, after_version)
        lease_id = claim["lease_id"]
        state["routing_action_ledger"][lease_id]["release_reason_code"] = mutation[
            "reason_code"
        ]
        return {
            "code": "CONTROLLER_LEASE_RELEASED",
            "next_action_code": mutation["reason_code"],
            "result": {
                "lease_id": lease_id,
                "reason_code": mutation["reason_code"],
            },
        }

    def _renew_lease(
        self,
        state: dict[str, Any],
        request: dict[str, Any],
        mutation: dict[str, Any],
    ) -> dict[str, Any]:
        old_claim = mutation["lease_claim"]
        lease = self._require_exact_lease(
            state, old_claim, mutation["observed_at"], allow_expired=True
        )
        evidence = mutation["owner_evidence"]
        if (
            evidence["thread_id"] != old_claim["owner_identity"]
            or evidence["routing_turn_id"] != lease["routing_turn_id"]
        ):
            raise RuntimeRejection("SAME_OWNER_EVIDENCE_MISMATCH", "/mutation/owner_evidence")
        observed = _parse_time(mutation["observed_at"], "/mutation/observed_at")
        if _parse_time(evidence["last_activity_at"], "/mutation/owner_evidence/last_activity_at") > observed:
            raise RuntimeRejection(
                "OWNER_EVIDENCE_FROM_FUTURE",
                "/mutation/owner_evidence/last_activity_at",
            )
        self._require_attached_read_evidence(request, evidence, "/mutation/owner_evidence")
        expires = _parse_time(mutation["expires_at"], "/mutation/expires_at")
        if expires <= observed:
            raise RuntimeRejection("LEASE_EXPIRY_INVALID", "/mutation/expires_at")
        new_id = mutation["new_lease_id"]
        if (
            new_id == old_claim["lease_id"]
            or new_id in state["consumed_controller_lease_ids"]
            or any(item["lease_id"] == new_id for item in state["routing_turn_ledger"].values())
        ):
            raise RuntimeRejection("LEASE_ID_CONFLICT", "/mutation/new_lease_id")
        active = self._active_outboxes_for_claim(state, old_claim)
        state["lease_epoch_counter"] += 1
        new_claim = {
            **old_claim,
            "lease_epoch": state["lease_epoch_counter"],
            "lease_id": new_id,
        }
        state["consumed_controller_lease_ids"].append(old_claim["lease_id"])
        state["consumed_controller_lease_ids"] = sorted(
            set(state["consumed_controller_lease_ids"])
        )
        lease["claim"] = new_claim
        lease["acquired_at"] = mutation["observed_at"]
        lease["expires_at"] = mutation["expires_at"]
        for record in active:
            record["lease_claim"] = copy.deepcopy(new_claim)
        state["routing_turn_ledger"][lease["routing_turn_id"]]["lease_id"] = new_id
        return {
            "code": "SAME_OWNER_LEASE_RENEWED",
            "next_action_code": "RESUME_RESERVED_ROUTE" if lease["route_action"] else "ROUTE_ONE_TRANSITION",
            "result": {"lease_claim": copy.deepcopy(new_claim)},
        }

    def _takeover_lease(
        self,
        state: dict[str, Any],
        request: dict[str, Any],
        mutation: dict[str, Any],
    ) -> dict[str, Any]:
        old_claim = mutation["lease_claim"]
        lease = state["controller_lease"]
        if lease is None or lease["claim"] != old_claim:
            raise RuntimeRejection("STALE_OR_MISSING_CONTROLLER_LEASE", "/mutation/lease_claim")
        observed = self._observe_time(state, mutation["observed_at"], "/mutation/observed_at")
        if observed < _parse_time(lease["expires_at"], "/controller_lease/expires_at"):
            raise RuntimeRejection("CONTROLLER_LEASE_NOT_EXPIRED", "/mutation/observed_at")
        evidence = mutation["takeover_evidence"]
        if evidence["thread_id"] != old_claim["owner_identity"]:
            raise RuntimeRejection("TAKEOVER_EVIDENCE_OWNER_MISMATCH", "/mutation/takeover_evidence/thread_id")
        if _parse_time(evidence["last_activity_at"], "/mutation/takeover_evidence/last_activity_at") > observed:
            raise RuntimeRejection(
                "TAKEOVER_EVIDENCE_FROM_FUTURE",
                "/mutation/takeover_evidence/last_activity_at",
            )
        self._require_attached_read_evidence(request, evidence, "/mutation/takeover_evidence")
        if not self._registered_controller(state, mutation["new_owner_identity"]):
            raise RuntimeRejection("CONTROLLER_IDENTITY_MISMATCH", "/mutation/new_owner_identity")
        expires = _parse_time(mutation["expires_at"], "/mutation/expires_at")
        if expires <= observed:
            raise RuntimeRejection("LEASE_EXPIRY_INVALID", "/mutation/expires_at")
        routing_turn_id = mutation["routing_turn_id"]
        new_id = mutation["new_lease_id"]
        if routing_turn_id in state["routing_turn_ledger"]:
            raise RuntimeRejection("ROUTING_TURN_ID_CONFLICT", "/mutation/routing_turn_id")
        if (
            new_id == old_claim["lease_id"]
            or new_id in state["consumed_controller_lease_ids"]
            or any(item["lease_id"] == new_id for item in state["routing_turn_ledger"].values())
        ):
            raise RuntimeRejection("LEASE_ID_CONFLICT", "/mutation/new_lease_id")
        if state["routing_turn_count"] >= state["max_routing_turns"]:
            raise RuntimeRejection("ROUTING_BUDGET_EXHAUSTED", "/routing_turn_count")
        active = self._active_outboxes_for_claim(state, old_claim)
        if len(active) > 1:
            raise RuntimeRejection("LEASE_RECOVERY_MULTIPLE_ACTIONS", "/controller_lease")
        route_action = copy.deepcopy(lease["route_action"])
        if route_action is not None:
            if (
                route_action["action_type"] != "OUTBOX"
                or len(active) != 1
                or active[0]["outbox_id"] != route_action["action_id"]
            ):
                raise RuntimeRejection("LEASE_RECOVERY_ACTION_MISMATCH", "/controller_lease")
        state["lease_epoch_counter"] += 1
        new_claim = {
            "lease_epoch": state["lease_epoch_counter"],
            "lease_id": new_id,
            "routing_turn_id": routing_turn_id,
            "owner_kind": mutation["new_owner_kind"],
            "owner_identity": mutation["new_owner_identity"],
            "intended_transition": INTENDED_TRANSITION,
        }
        for record in active:
            record["lease_claim"] = copy.deepcopy(new_claim)
        state["consumed_controller_lease_ids"].append(old_claim["lease_id"])
        state["consumed_controller_lease_ids"] = sorted(
            set(state["consumed_controller_lease_ids"])
        )
        state["routing_turn_ledger"][lease["routing_turn_id"]]["status"] = "TAKEN_OVER"
        state["routing_turn_count"] += 1
        state["routing_turn_ledger"][routing_turn_id] = {
            "routing_turn_id": routing_turn_id,
            "event_id": request["event_id"],
            "owner_kind": mutation["new_owner_kind"],
            "owner_identity": mutation["new_owner_identity"],
            "lease_id": new_id,
            "status": "LEASE_ACQUIRED",
        }
        state["controller_lease"] = {
            "claim": new_claim,
            "routing_turn_id": routing_turn_id,
            "acquired_at": mutation["observed_at"],
            "expires_at": mutation["expires_at"],
            "route_action": route_action,
        }
        return {
            "code": "EXPIRED_LEASE_TAKEN_OVER",
            "next_action_code": "RESUME_RESERVED_ROUTE" if route_action else "ROUTE_ONE_TRANSITION",
            "result": {"lease_claim": copy.deepcopy(new_claim)},
        }

    @staticmethod
    def _require_attached_read_evidence(
        request: dict[str, Any],
        evidence: dict[str, Any],
        path: str,
    ) -> None:
        evidence_path = evidence["read_evidence_path"]
        read_digest = evidence["read_digest"]
        matches = [
            artifact
            for artifact in request["artifacts"]
            if artifact["path"] == evidence_path
            and artifact["digest"] == read_digest
            and artifact["media_type"] == "application/json"
        ]
        if len(matches) != 1:
            raise RuntimeRejection(
                "OWNER_READ_EVIDENCE_UNBOUND",
                f"{path}/read_digest",
                {"read_evidence_path": evidence_path},
            )
        expected = {
            key: value
            for key, value in evidence.items()
            if key not in {"read_digest", "read_evidence_path"}
        }
        observed = _strict_json_loads(
            matches[0]["content"],
            code="OWNER_READ_EVIDENCE_INVALID",
            path=path,
        )
        if observed != expected:
            raise RuntimeRejection(
                "OWNER_READ_EVIDENCE_MISMATCH",
                path,
            )

    @staticmethod
    def _require_json_observation_artifact(
        request: dict[str, Any],
        path: str,
        digest: str,
        expected: dict[str, Any],
        json_path: str,
    ) -> None:
        matches = [
            artifact
            for artifact in request["artifacts"]
            if artifact["path"] == path
            and artifact["digest"] == digest
            and artifact["media_type"] == "application/json"
        ]
        if len(matches) != 1:
            raise RuntimeRejection(
                "OBSERVATION_ARTIFACT_UNBOUND",
                json_path,
                {"path": path, "digest": digest},
            )
        observed = _strict_json_loads(
            matches[0]["content"],
            code="OBSERVATION_ARTIFACT_INVALID",
            path=json_path,
        )
        if observed != expected:
            raise RuntimeRejection(
                "OBSERVATION_ARTIFACT_MISMATCH",
                json_path,
            )

    def _require_existing_json_observation_artifact(
        self,
        state: dict[str, Any],
        path: str,
        digest: str,
        expected: dict[str, Any],
        archived_state_version: int,
        json_path: str,
    ) -> None:
        record = state["artifact_ledger"].get(path)
        if (
            record is None
            or record["digest"] != digest
            or record["media_type"] != "application/json"
            or record["archived_state_version"] != archived_state_version
        ):
            raise RuntimeRejection(
                "GOAL_BLOCKER_OBSERVATION_NOT_PREVIOUSLY_ARCHIVED",
                json_path,
                {"path": path, "archived_state_version": archived_state_version},
            )
        artifact_path = self.root / path
        self._assert_confined(artifact_path, self.control_dir, json_path)
        try:
            content = artifact_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise RuntimeRejection(
                "OBSERVATION_ARTIFACT_INVALID", json_path
            ) from exc
        if _bytes_digest(content.encode("utf-8")) != digest:
            raise RuntimeRejection("ARTIFACT_DIGEST_MISMATCH", json_path)
        observed = _strict_json_loads(
            content,
            code="OBSERVATION_ARTIFACT_INVALID",
            path=json_path,
        )
        if observed != expected:
            raise RuntimeRejection("OBSERVATION_ARTIFACT_MISMATCH", json_path)

    @staticmethod
    def _identity_value(
        identity: dict[str, Any], key: str, path: str
    ) -> Any:
        if key not in identity:
            raise RuntimeRejection("OUTBOX_IDENTITY_INCOMPLETE", f"{path}/{key}")
        return identity[key]

    @staticmethod
    def _require_exact_keys(
        value: dict[str, Any], required: set[str], path: str
    ) -> None:
        if set(value) != required:
            raise RuntimeRejection(
                "OUTBOX_IDENTITY_SHAPE_INVALID",
                path,
                {
                    "missing": sorted(required - set(value)),
                    "unexpected": sorted(set(value) - required),
                },
            )

    @staticmethod
    def _project_id(state: dict[str, Any]) -> str:
        controller = next(
            record
            for record in state["thread_registry"].values()
            if record["role_kind"] == "CONTROLLER"
        )
        return controller["project_id"]

    def _validate_identity_tokens(self, value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}/{key}"
                if key == "project_id":
                    if (
                        not isinstance(child, str)
                        or not child
                        or len(child) > 1024
                        or any(ord(character) < 32 or ord(character) == 127 for character in child)
                    ):
                        raise RuntimeRejection("PROJECT_ID_INVALID", child_path)
                elif key.endswith("_id"):
                    if not isinstance(child, str) or SAFE_ID_RE.fullmatch(child) is None:
                        raise RuntimeRejection("UNSAFE_ID", child_path)
                elif key.endswith("_digest"):
                    if not isinstance(child, str) or DIGEST_RE.fullmatch(child) is None:
                        raise RuntimeRejection("DIGEST_INVALID", child_path)
                else:
                    self._validate_identity_tokens(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self._validate_identity_tokens(child, f"{path}/{index}")

    def _find_outbox_any_kind(
        self, state: dict[str, Any], outbox_id: str
    ) -> tuple[str, dict[str, Any]] | None:
        found = [
            (kind, state[field][outbox_id])
            for kind, field in OUTBOX_FIELDS.items()
            if outbox_id in state[field]
        ]
        if len(found) > 1:
            raise RuntimeRejection("OUTBOX_ID_CONFLICT", "/mutation/outbox_id")
        return found[0] if found else None

    def _require_outbox(
        self,
        state: dict[str, Any],
        mutation: dict[str, Any],
    ) -> dict[str, Any]:
        kind = mutation["outbox_kind"]
        field = OUTBOX_FIELDS[kind]
        record = state[field].get(mutation["outbox_id"])
        if record is None:
            raise RuntimeRejection("OUTBOX_NOT_FOUND", "/mutation/outbox_id")
        if (
            record["outbox_kind"] != kind
            or record["payload_digest"] != mutation["payload_digest"]
            or record["target_id"] != mutation["target_id"]
        ):
            raise RuntimeRejection("OUTBOX_IDENTITY_CONFLICT", "/mutation/outbox_id")
        if record["lease_claim"] != mutation["lease_claim"]:
            raise RuntimeRejection("OUTBOX_LEASE_MISMATCH", "/mutation/lease_claim")
        return record

    def _goal_queue_entry(
        self, state: dict[str, Any], goal_id: str
    ) -> dict[str, Any] | None:
        return next((entry for entry in state["goal_queue"] if entry["goal_id"] == goal_id), None)

    def _prepare_outbox(
        self,
        state: dict[str, Any],
        mutation: dict[str, Any],
        after_version: int,
    ) -> dict[str, Any]:
        claim = mutation["lease_claim"]
        lease = self._require_exact_lease(state, claim, mutation["observed_at"])
        kind = mutation["outbox_kind"]
        outbox_id = mutation["outbox_id"]
        identity = copy.deepcopy(mutation["identity"])
        self._validate_identity_tokens(identity, "/mutation/identity")
        self._reserve_route(lease, "OUTBOX", outbox_id)

        existing_any = self._find_outbox_any_kind(state, outbox_id)
        immutable = {
            "outbox_id": outbox_id,
            "outbox_kind": kind,
            "payload_digest": mutation["payload_digest"],
            "target_id": mutation["target_id"],
            "identity": identity,
            "roadmap_version": state["roadmap_version"],
        }
        if existing_any is not None:
            existing_kind, existing = existing_any
            if existing_kind != kind or any(
                existing[key] != value for key, value in immutable.items()
            ):
                raise RuntimeRejection("OUTBOX_IDENTITY_CONFLICT", "/mutation/outbox_id")
            if existing["lease_claim"] != claim:
                raise RuntimeRejection("OUTBOX_LEASE_MISMATCH", "/mutation/lease_claim")
            return {
                "code": "OUTBOX_ALREADY_PREPARED",
                "next_action_code": self._next_outbox_action(existing["status"]),
                "result": {
                    "outbox_id": outbox_id,
                    "outbox_kind": kind,
                    "outbox_status": existing["status"],
                },
            }

        self._validate_outbox_prepare_semantics(
            state,
            kind,
            identity,
            mutation["target_id"],
            outbox_id,
            mutation["payload_digest"],
        )
        record = {
            **immutable,
            "status": "PREPARED",
            "lease_claim": copy.deepcopy(claim),
            "prepared_state_version": after_version,
            "sent_evidence_paths": [],
            "ack_evidence_paths": [],
            "result": None,
        }
        state[OUTBOX_FIELDS[kind]][outbox_id] = record
        if kind == "DISPATCH":
            goal_id = identity["goal_id"]
            state["goal_execution_ledger"][goal_id]["status"] = "IN_PROGRESS"
        elif kind == "DELEGATION":
            exploration_id = identity["exploration_id"]
            state["subagent_attempt_ledger"].setdefault(exploration_id, []).append(
                {
                    "attempt_id": identity["attempt_id"],
                    "outbox_id": outbox_id,
                    "payload_digest": mutation["payload_digest"],
                    "status": "PREPARED",
                    "report_digest": None,
                    "agent_id": None,
                }
            )
        return {
            "code": f"{kind}_OUTBOX_PREPARED",
            "next_action_code": "PERFORM_EXTERNAL_ACTION",
            "result": {
                "outbox_id": outbox_id,
                "outbox_kind": kind,
                "outbox_status": "PREPARED",
            },
        }

    @staticmethod
    def _next_outbox_action(status: str) -> str:
        return {
            "PREPARED": "RECONCILE_BEFORE_SEND",
            "SENT": "ACK_OUTBOX",
            "ACKED": "RECORD_REVIEW",
            "COMPLETED": "NONE",
            "CANCELLED": "NONE",
        }[status]

    def _cancel_outbox(
        self,
        state: dict[str, Any],
        mutation: dict[str, Any],
        after_version: int,
    ) -> dict[str, Any]:
        claim = mutation["lease_claim"]
        lease = self._require_exact_lease(state, claim, mutation["observed_at"])
        self._reserve_route(lease, "OUTBOX", mutation["outbox_id"])
        record = self._require_outbox(state, mutation)
        if record["status"] != "PREPARED":
            raise RuntimeRejection(
                "OUTBOX_CANCELLATION_NOT_SAFE",
                "/mutation/outbox_id",
                {"status": record["status"]},
            )
        record["status"] = "CANCELLED"
        record["cancel_reason_code"] = mutation["cancel_reason_code"]
        record["cancel_evidence_paths"] = list(mutation["recovery_evidence_paths"])
        record["cancelled_state_version"] = after_version
        if mutation["outbox_kind"] == "DISPATCH":
            goal_id = record["identity"]["goal_id"]
            ledger = state["goal_execution_ledger"][goal_id]
            entry = self._goal_queue_entry(state, goal_id)
            if entry is not None:
                ledger["status"] = entry["status"]
        elif mutation["outbox_kind"] == "DELEGATION":
            self._delegation_attempt(state, record)["status"] = "CANCELLED"
        self._finish_route(state, claim, after_version)
        return {
            "code": f"{mutation['outbox_kind']}_OUTBOX_CANCELLED",
            "next_action_code": "RECONCILE_OR_PREPARE_NEW_ROUTE",
            "result": {
                "outbox_id": mutation["outbox_id"],
                "outbox_kind": mutation["outbox_kind"],
                "outbox_status": "CANCELLED",
                "cancel_reason_code": mutation["cancel_reason_code"],
            },
        }

    def _validate_controller_goal_update_transition(
        self,
        state: dict[str, Any],
        identity: dict[str, Any],
    ) -> None:
        current = state["controller_goal"]
        finalization = state["finalization_outbox"]
        if isinstance(finalization, dict) and finalization["status"] == "PREPARED":
            if (
                finalization["controller_goal_id"] == identity["goal_id"]
                and finalization["controller_goal_target_status"]
                == identity["target_status"]
            ):
                return
            raise RuntimeRejection(
                "CONTROLLER_GOAL_FINALIZATION_MISMATCH",
                "/mutation/identity",
            )

        if identity["target_status"] != "COMPLETE":
            raise RuntimeRejection(
                "CONTROLLER_GOAL_EARLY_TERMINATION",
                "/mutation/identity/target_status",
            )
        milestone_id = current["milestone_id"]
        milestone_record = next(
            (
                item
                for item in state["milestones"]
                if item["milestone_id"] == milestone_id
            ),
            None,
        )
        milestone_goals = [
            record
            for record in state["goal_execution_ledger"].values()
            if record["milestone_id"] == milestone_id
        ]
        revision_applied = any(
            record.get("status") == "APPLIED"
            and record.get("new_roadmap_version") == state["roadmap_version"]
            and state["goal_definition_registry"]
            .get(record.get("source_goal_id"), {})
            .get("milestone_id")
            == milestone_id
            for record in state["roadmap_change_outbox"].values()
        )
        if (
            milestone_record is None
            or milestone_record["status"] not in {"COMPLETE", "SUPERSEDED"}
            or state["active_milestone_id"] == milestone_id
            or not milestone_goals
            or any(
                record["status"] not in {"COMPLETE", "RETIRED"}
                for record in milestone_goals
            )
            or not revision_applied
        ):
            raise RuntimeRejection(
                "CONTROLLER_GOAL_EARLY_TERMINATION",
                "/mutation/identity",
                {"milestone_id": milestone_id},
            )

    def _validate_outbox_prepare_semantics(
        self,
        state: dict[str, Any],
        kind: str,
        identity: dict[str, Any],
        target_id: str,
        outbox_id: str,
        payload_digest: str,
    ) -> None:
        control_caps = state["authorization_envelope"]["control_plane_caps"]
        required_cap = {
            "THREAD": "thread_create",
            "AUTOMATION": "automation_manage",
            "GOAL": "goal_manage",
            "DISPATCH": "message_send",
            "ASSURANCE": "message_send",
            "LOCAL": "message_send",
            "DELEGATION": "message_send",
        }[kind]
        if control_caps[required_cap] is not True:
            raise RuntimeRejection(
                "AUTHORIZATION_BOUNDARY_VIOLATION",
                f"/authorization_envelope/control_plane_caps/{required_cap}",
                {"reason": "CONTROL_PLANE_ACTION_DENIED", "outbox_kind": kind},
            )
        if kind == "DISPATCH":
            self._require_exact_keys(
                identity,
                {
                    "dispatch_id",
                    "goal_id",
                    "goal_definition_digest",
                    "payload_digest",
                    "target_thread_id",
                    "worker_role_kind",
                },
                "/mutation/identity",
            )
            if (
                identity["dispatch_id"] != outbox_id
                or identity["payload_digest"] != payload_digest
                or identity["target_thread_id"] != target_id
            ):
                raise RuntimeRejection(
                    "DISPATCH_OUTBOX_IDENTITY_MISMATCH", "/mutation/identity"
                )
            worker_thread = state["thread_registry"].get(target_id)
            if (
                worker_thread is None
                or worker_thread["role_kind"] != "WORKER"
                or worker_thread["status"] != "REGISTERED"
            ):
                raise RuntimeRejection(
                    "WORKER_IDENTITY_MISMATCH",
                    "/mutation/target_id",
                )
            goal_id = self._identity_value(identity, "goal_id", "/mutation/identity")
            definition_digest = self._identity_value(
                identity, "goal_definition_digest", "/mutation/identity"
            )
            definition = state["goal_definition_registry"].get(goal_id)
            entry = self._goal_queue_entry(state, goal_id)
            ledger = state["goal_execution_ledger"].get(goal_id)
            controller_goal = state.get("controller_goal")
            if (
                definition is None
                or ledger is None
                or definition["payload_template_digest"] != definition_digest
                or definition["worker_role_kind"] != identity["worker_role_kind"]
                or worker_thread["bootstrap_role_kind"]
                != identity["worker_role_kind"]
                or entry is None
                or entry["status"] != "READY"
                or entry["roadmap_version"] != state["roadmap_version"]
                or entry["milestone_id"] != state["active_milestone_id"]
            ):
                raise RuntimeRejection("DISPATCH_GOAL_IDENTITY_INVALID", "/mutation/identity")
            if (
                not isinstance(controller_goal, dict)
                or controller_goal.get("status")
                not in {"ACTIVE", "EMULATED_SINGLE_ACTIVE_MILESTONE"}
                or controller_goal.get("milestone_id") != definition["milestone_id"]
            ):
                raise RuntimeRejection(
                    "CONTROLLER_GOAL_MILESTONE_NOT_ACTIVE",
                    "/controller_goal",
                    {
                        "required_milestone_id": definition["milestone_id"],
                        "actual_milestone_id": (
                            controller_goal.get("milestone_id")
                            if isinstance(controller_goal, dict)
                            else None
                        ),
                    },
                )
            completed = {
                candidate
                for candidate, record in state["goal_execution_ledger"].items()
                if record["status"] in {"COMPLETE", "RETIRED"}
            }
            if not set(entry["depends_on"]).issubset(completed):
                raise RuntimeRejection("DISPATCH_DEPENDENCY_INCOMPLETE", "/mutation/identity/goal_id")
            if ledger["status"] in {
                "WORKER_PASS",
                "CODE_REVIEW_PASS",
                "LOCAL_VERIFICATION_PASS",
                "FINAL_CANDIDATE",
                "FINAL_AUDIT_PASS",
                "COMPLETE",
                "RETIRED",
            }:
                raise RuntimeRejection("DISPATCH_GOAL_ALREADY_SATISFIED", "/mutation/identity/goal_id")
            if any(
                record["status"] in {"PREPARED", "SENT"}
                for record in state["dispatch_outbox"].values()
            ):
                raise RuntimeRejection("WORKER_DISPATCH_ALREADY_ACTIVE", "/dispatch_outbox")
            repair_limit = state["authorization_envelope"]["repair_policy"][
                "max_repair_attempts_per_goal"
            ]
            if len(ledger["attempts"]) >= 1 + repair_limit:
                raise RuntimeRejection(
                    "REPAIR_BUDGET_EXHAUSTED",
                    f"/goal_execution_ledger/{goal_id}/attempts",
                    {
                        "completed_attempts": len(ledger["attempts"]),
                        "max_repair_attempts_per_goal": repair_limit,
                    },
                )
        elif kind == "THREAD":
            self._require_exact_keys(
                identity,
                {
                    "project_id",
                    "task_kind",
                    "bootstrap_role_kind",
                    "formal_role_kind",
                    "bootstrap_prompt_digest",
                    "environment_kind",
                },
                "/mutation/identity",
            )
            bootstrap_role_kind = self._identity_value(
                identity,
                "bootstrap_role_kind",
                "/mutation/identity",
            )
            formal_role_kind = self._identity_value(
                identity,
                "formal_role_kind",
                "/mutation/identity",
            )
            if (
                bootstrap_role_kind not in BOOTSTRAP_ROLE_TO_FORMAL_ROLE
                or BOOTSTRAP_ROLE_TO_FORMAL_ROLE[bootstrap_role_kind]
                != formal_role_kind
            ):
                raise RuntimeRejection(
                    "THREAD_ROLE_MAPPING_INVALID", "/mutation/identity"
                )
            if (
                identity["project_id"] != self._project_id(state)
                or identity["task_kind"] != "PROJECT_TASK"
                or identity["environment_kind"] not in {"LOCAL", "WORKTREE"}
            ):
                raise RuntimeRejection("THREAD_IDENTITY_INVALID", "/mutation/identity")
            if (
                formal_role_kind == "LOCAL_VERIFIER"
                and control_caps["local_verifier"] is not True
            ):
                raise RuntimeRejection(
                    "AUTHORIZATION_BOUNDARY_VIOLATION",
                    "/authorization_envelope/control_plane_caps/local_verifier",
                    {"reason": "LOCAL_VERIFIER_DENIED"},
                )
            limits = state["authorization_envelope"]["control_plane_limits"]
            registered_children = sum(
                record["role_kind"] != "CONTROLLER"
                for record in state["thread_registry"].values()
            )
            pending_threads = sum(
                record["status"] in ACTIVE_OUTBOX_STATUSES
                for record in state["thread_creation_outbox"].values()
            )
            if registered_children + pending_threads >= limits["max_child_threads"]:
                raise RuntimeRejection(
                    "THREAD_BUDGET_EXHAUSTED",
                    "/thread_registry",
                    {
                        "child_count": registered_children + pending_threads,
                        "max_child_threads": limits["max_child_threads"],
                    },
                )
            if any(
                record["status"] == "REGISTERED"
                and record["role_kind"] == formal_role_kind
                and record["bootstrap_role_kind"] == bootstrap_role_kind
                for record in state["thread_registry"].values()
            ):
                raise RuntimeRejection(
                    "THREAD_ROLE_ALREADY_REGISTERED",
                    "/mutation/identity/bootstrap_role_kind",
                )
            if any(
                record["status"] != "CANCELLED"
                and record["identity"].get("project_id") == identity["project_id"]
                and record["identity"].get("bootstrap_role_kind")
                == bootstrap_role_kind
                and record["identity"].get("formal_role_kind") == formal_role_kind
                for record in state["thread_creation_outbox"].values()
            ):
                raise RuntimeRejection(
                    "THREAD_ACTION_DUPLICATE",
                    "/thread_creation_outbox",
                )
        elif kind == "AUTOMATION":
            self._require_exact_keys(
                identity,
                {
                    "automation_name",
                    "kind",
                    "target_thread_id",
                    "rrule",
                    "prompt_digest",
                    "prompt_normalization",
                },
                "/mutation/identity",
            )
            controller = next(
                record
                for record in state["thread_registry"].values()
                if record["role_kind"] == "CONTROLLER"
            )
            if (
                identity["kind"] != "HEARTBEAT"
                or identity["target_thread_id"] != controller["thread_id"]
                or identity["prompt_normalization"]
                != "LF_NORMALIZED_NO_TRAILING_NEWLINE"
                or not isinstance(identity["automation_name"], str)
                or not identity["automation_name"]
                or not isinstance(identity["rrule"], str)
                or not identity["rrule"].startswith("FREQ=MINUTELY;INTERVAL=")
            ):
                raise RuntimeRejection("AUTOMATION_IDENTITY_INVALID", "/mutation/identity")
            if any(
                record["status"] != "CANCELLED"
                for record in state["automation_outbox"].values()
            ):
                raise RuntimeRejection(
                    "BUSINESS_HEARTBEAT_ALREADY_REGISTERED",
                    "/automation_outbox",
                )
        elif kind == "GOAL":
            required = {
                "action",
                "loop_id",
                "pack_digest",
                "milestone_id",
                "objective_digest",
                "marker",
            }
            if identity.get("action") == "UPDATE":
                required |= {"goal_id", "target_status"}
            self._require_exact_keys(identity, required, "/mutation/identity")
            action = identity["action"]
            current_goal = state["controller_goal"]
            expected_marker = (
                "[CODEX_LOOP_MILESTONE "
                f"loop_id={identity['loop_id']} "
                f"pack_sha256={identity['pack_digest'].removeprefix('sha256:')} "
                f"milestone_id={identity['milestone_id']} "
                f"objective_sha256={identity['objective_digest'].removeprefix('sha256:')}]"
            )
            if (
                action not in {"CREATE", "UPDATE"}
                or identity["loop_id"] != state["loop_id"]
                or identity["pack_digest"] != state["controller_pack_identity"]["digest"]
                or identity["marker"] != expected_marker
            ):
                raise RuntimeRejection("CONTROLLER_GOAL_IDENTITY_INVALID", "/mutation/identity")
            if action == "CREATE":
                if identity["milestone_id"] != state["active_milestone_id"]:
                    raise RuntimeRejection(
                        "CONTROLLER_GOAL_IDENTITY_INVALID",
                        "/mutation/identity/milestone_id",
                    )
                if current_goal is not None and current_goal.get("status") != "COMPLETE":
                    raise RuntimeRejection(
                        "CONTROLLER_GOAL_ALREADY_EXISTS",
                        "/controller_goal",
                    )
                if (
                    current_goal is not None
                    and current_goal.get("milestone_id") == identity["milestone_id"]
                ):
                    raise RuntimeRejection(
                        "CONTROLLER_GOAL_ALREADY_EXISTS",
                        "/controller_goal",
                    )
            else:
                if (
                    identity["target_status"] not in {"COMPLETE", "BLOCKED"}
                    or not isinstance(current_goal, dict)
                    or current_goal.get("status")
                    not in {"ACTIVE", "EMULATED_SINGLE_ACTIVE_MILESTONE"}
                    or any(
                        identity.get(key) != current_goal.get(key)
                        for key in (
                            "loop_id",
                            "pack_digest",
                            "milestone_id",
                            "objective_digest",
                            "marker",
                            "goal_id",
                        )
                    )
                ):
                    raise RuntimeRejection(
                        "CONTROLLER_GOAL_SOURCE_MISMATCH",
                        "/mutation/identity",
                    )
                self._validate_controller_goal_update_transition(state, identity)
        elif kind == "ASSURANCE":
            review_kind = self._identity_value(
                identity, "review_kind", "/mutation/identity"
            )
            required = {
                "review_dispatch_id",
                "review_kind",
                "goal_id",
                "milestone_id",
                "roadmap_version",
                "target_reviewer_thread_id",
                "payload_digest",
                "worker_dispatch_id",
                "worker_report_digest",
                "artifact_digest",
            }
            if review_kind in {"ROADMAP_AUDIT", "FINAL_AUDIT"}:
                required.add("code_review_id")
            if review_kind == "FINAL_AUDIT":
                required.add("roadmap_audit_id")
            self._require_exact_keys(identity, required, "/mutation/identity")
            if (
                identity["review_dispatch_id"] != outbox_id
                or identity["payload_digest"] != payload_digest
                or identity["target_reviewer_thread_id"] != target_id
                or identity["roadmap_version"] != state["roadmap_version"]
                or identity["milestone_id"] != state["active_milestone_id"]
            ):
                raise RuntimeRejection(
                    "ASSURANCE_OUTBOX_IDENTITY_MISMATCH", "/mutation/identity"
                )
            reviewer = state["thread_registry"].get(target_id)
            if (
                reviewer is None
                or reviewer["role_kind"] != "REVIEWER"
                or reviewer["status"] != "REGISTERED"
            ):
                raise RuntimeRejection(
                    "REVIEWER_IDENTITY_MISMATCH",
                    "/mutation/target_id",
                )
            self._assert_assurance_ready(state, identity, target_id)
        elif kind == "LOCAL":
            self._require_exact_keys(
                identity,
                {
                    "local_dispatch_id",
                    "verification_id",
                    "goal_id",
                    "milestone_id",
                    "roadmap_version",
                    "target_thread_id",
                    "payload_digest",
                    "worker_dispatch_id",
                    "artifact_digest",
                    "code_review_id",
                },
                "/mutation/identity",
            )
            if (
                identity["local_dispatch_id"] != outbox_id
                or identity["payload_digest"] != payload_digest
                or identity["target_thread_id"] != target_id
                or identity["roadmap_version"] != state["roadmap_version"]
                or identity["milestone_id"] != state["active_milestone_id"]
            ):
                raise RuntimeRejection(
                    "LOCAL_OUTBOX_IDENTITY_MISMATCH", "/mutation/identity"
                )
            if control_caps["local_verifier"] is not True:
                raise RuntimeRejection(
                    "AUTHORIZATION_BOUNDARY_VIOLATION",
                    "/authorization_envelope/control_plane_caps/local_verifier",
                    {"reason": "LOCAL_VERIFIER_DENIED"},
                )
            local_verifier = state["thread_registry"].get(target_id)
            if (
                local_verifier is None
                or local_verifier["role_kind"] != "LOCAL_VERIFIER"
                or local_verifier["status"] != "REGISTERED"
            ):
                raise RuntimeRejection(
                    "LOCAL_VERIFIER_IDENTITY_MISMATCH",
                    "/mutation/target_id",
                )
            goal_id = self._identity_value(identity, "goal_id", "/mutation/identity")
            worker_dispatch_id = self._identity_value(
                identity, "worker_dispatch_id", "/mutation/identity"
            )
            artifact_digest = self._identity_value(
                identity, "artifact_digest", "/mutation/identity"
            )
            self._identity_value(identity, "verification_id", "/mutation/identity")
            worker = self._latest_worker_exact(
                state, goal_id, worker_dispatch_id, artifact_digest
            )
            code_review_id = self._identity_value(
                identity, "code_review_id", "/mutation/identity"
            )
            self._require_review(
                state,
                code_review_id,
                "CODE_REVIEW",
                goal_id,
                worker["dispatch_id"],
                artifact_digest,
                CODE_REVIEW_PASS,
            )
        elif kind == "DELEGATION":
            self._validate_delegation_prepare(state, identity, target_id)

    def _mark_outbox_sent(
        self, state: dict[str, Any], mutation: dict[str, Any]
    ) -> dict[str, Any]:
        claim = mutation["lease_claim"]
        lease = self._require_exact_lease(state, claim, mutation["observed_at"])
        self._reserve_route(lease, "OUTBOX", mutation["outbox_id"])
        record = self._require_outbox(state, mutation)
        if record["status"] == "PREPARED":
            record["status"] = "SENT"
            record["sent_evidence_paths"] = list(mutation["send_evidence_paths"])
            if mutation["outbox_kind"] == "DELEGATION":
                self._delegation_attempt(state, record)["status"] = "RUNNING"
            code = f"{mutation['outbox_kind']}_OUTBOX_SENT"
        elif record["status"] == "SENT":
            if record["sent_evidence_paths"] != mutation["send_evidence_paths"]:
                raise RuntimeRejection("OUTBOX_SEND_EVIDENCE_CONFLICT", "/mutation/send_evidence_paths")
            code = "OUTBOX_ALREADY_SENT"
        else:
            raise RuntimeRejection("OUTBOX_NOT_PREPARED", "/mutation/outbox_id")
        return {
            "code": code,
            "next_action_code": "ACK_OUTBOX",
            "result": {
                "outbox_id": record["outbox_id"],
                "outbox_kind": record["outbox_kind"],
                "outbox_status": record["status"],
            },
        }

    def _ack_outbox(
        self,
        state: dict[str, Any],
        request: dict[str, Any],
        mutation: dict[str, Any],
        after_version: int,
    ) -> dict[str, Any]:
        claim = mutation["lease_claim"]
        lease = self._require_exact_lease(state, claim, mutation["observed_at"])
        self._reserve_route(lease, "OUTBOX", mutation["outbox_id"])
        record = self._require_outbox(state, mutation)
        result = copy.deepcopy(mutation.get("result", {}))
        kind = mutation["outbox_kind"]
        emulated_goal_create = bool(
            kind == "GOAL"
            and record["status"] == "PREPARED"
            and record["identity"].get("action") == "CREATE"
            and result.get("status") == "EMULATED_SINGLE_ACTIVE_MILESTONE"
        )
        emulated_goal_update = bool(
            kind == "GOAL"
            and record["status"] == "PREPARED"
            and record["identity"].get("action") == "UPDATE"
            and state.get("controller_goal", {}).get("status")
            == "EMULATED_SINGLE_ACTIVE_MILESTONE"
        )
        if record["status"] != "SENT" and not (
            emulated_goal_create or emulated_goal_update
        ):
            raise RuntimeRejection("OUTBOX_NOT_SENT", "/mutation/outbox_id")
        self._validate_identity_tokens(result, "/mutation/result")
        if kind in {"DISPATCH", "ASSURANCE", "LOCAL"}:
            missing_result = sorted(
                {"status", "report_digest", "artifact_digest"} - set(result)
            )
            if missing_result:
                raise RuntimeRejection(
                    "FORMAL_REPORT_RESULT_FIELD_MISSING",
                    "/mutation/result",
                    {"fields": missing_result},
                )
            report = self._require_bound_json_report_artifact(
                request,
                mutation["ack_evidence_paths"],
                result.get("report_digest"),
                "/mutation/result/report_digest",
            )
            self._validate_formal_report(state, record, result, report)
        if emulated_goal_create or emulated_goal_update:
            self._require_single_json_evidence_artifact(
                request,
                mutation["ack_evidence_paths"],
                "/mutation/ack_evidence_paths",
            )
        record["ack_evidence_paths"] = list(mutation["ack_evidence_paths"])
        record["result"] = result
        if kind == "DISPATCH":
            self._require_bound_report_artifact(
                request,
                mutation["ack_evidence_paths"],
                result.get("report_digest"),
                "/mutation/result/report_digest",
            )
            self._record_worker_result(state, record, result)
            record["status"] = "COMPLETED"
            self._finish_route(state, claim, after_version)
            next_action = "PREPARE_CODE_REVIEW" if result["status"] == "PASS" else "REPAIR_REQUIRED"
        elif kind == "LOCAL":
            self._require_bound_report_artifact(
                request,
                mutation["ack_evidence_paths"],
                result.get("report_digest"),
                "/mutation/result/report_digest",
            )
            self._record_local_result(state, record, result)
            record["status"] = "COMPLETED"
            self._finish_route(state, claim, after_version)
            next_action = "PREPARE_ROADMAP_AUDIT" if result["status"] == "PASS" else "REPAIR_REQUIRED"
        elif kind == "ASSURANCE":
            record["status"] = "ACKED"
            next_action = "RECORD_REVIEW"
        elif kind == "DELEGATION":
            self._record_delegation_result(state, request, record, result)
            record["status"] = "ACKED"
            self._finish_route(state, claim, after_version)
            next_action = (
                "DELEGATION_RESULT_AVAILABLE"
                if result["status"] == "COMPLETED"
                else "OPTIONAL_DELEGATION_DROPPED"
            )
        else:
            self._require_control_outbox_observation(
                request,
                record,
                result,
                mutation["ack_evidence_paths"],
            )
            self._record_control_outbox_result(state, record, result)
            record["status"] = "ACKED"
            self._finish_route(state, claim, after_version)
            next_action = "NONE"
        return {
            "code": f"{kind}_OUTBOX_ACKED",
            "next_action_code": next_action,
            "result": {
                "outbox_id": record["outbox_id"],
                "outbox_kind": kind,
                "outbox_status": record["status"],
            },
        }

    @staticmethod
    def _require_control_outbox_observation(
        request: dict[str, Any],
        record: dict[str, Any],
        result: dict[str, Any],
        evidence_paths: list[str],
    ) -> None:
        matches = [
            artifact
            for artifact in request["artifacts"]
            if artifact["path"] in evidence_paths
            and artifact["media_type"] == "application/json"
        ]
        if len(matches) != 1:
            raise RuntimeRejection(
                "CONTROL_TOOL_OBSERVATION_UNBOUND",
                "/mutation/ack_evidence_paths",
            )
        expected = {
            "observation_kind": (
                "GOAL_TOOL_UNAVAILABLE"
                if record["outbox_kind"] == "GOAL"
                and record["status"] == "PREPARED"
                else "CODEX_TOOL_RESULT"
            ),
            "outbox_kind": record["outbox_kind"],
            "outbox_id": record["outbox_id"],
            "payload_digest": record["payload_digest"],
            "target_id": record["target_id"],
            "result": result,
        }
        AdaptiveStateRuntime._require_json_observation_artifact(
            request,
            matches[0]["path"],
            matches[0]["digest"],
            expected,
            "/mutation/ack_evidence_paths",
        )

    def _record_worker_result(
        self,
        state: dict[str, Any],
        record: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        required = {"status", "report_digest", "artifact_digest"}
        if not required.issubset(result) or result["status"] not in {"PASS", "FAIL", "BLOCKED"}:
            raise RuntimeRejection("WORKER_RESULT_INVALID", "/mutation/result")
        for key in ("report_digest", "artifact_digest"):
            if not isinstance(result[key], str) or DIGEST_RE.fullmatch(result[key]) is None:
                raise RuntimeRejection("DIGEST_INVALID", f"/mutation/result/{key}")
        goal_id = record["identity"]["goal_id"]
        worker = {
            "dispatch_id": record["outbox_id"],
            "status": result["status"],
            "report_digest": result["report_digest"],
            "artifact_digest": result["artifact_digest"],
            "roadmap_version": record["roadmap_version"],
            "evidence_paths": list(record["ack_evidence_paths"]),
        }
        ledger = state["goal_execution_ledger"][goal_id]
        ledger["attempts"].append(copy.deepcopy(worker))
        ledger["latest_worker"] = worker
        ledger["status"] = "WORKER_PASS" if result["status"] == "PASS" else "REPAIR_REQUIRED"

    def _record_local_result(
        self,
        state: dict[str, Any],
        record: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        required = {"status", "report_digest", "artifact_digest"}
        if not required.issubset(result) or result["status"] not in {"PASS", "FAIL", "BLOCKED"}:
            raise RuntimeRejection("LOCAL_RESULT_INVALID", "/mutation/result")
        for key in ("report_digest", "artifact_digest"):
            if not isinstance(result[key], str) or DIGEST_RE.fullmatch(result[key]) is None:
                raise RuntimeRejection("DIGEST_INVALID", f"/mutation/result/{key}")
        identity = record["identity"]
        if result["artifact_digest"] != identity["artifact_digest"]:
            raise RuntimeRejection("LOCAL_ARTIFACT_IDENTITY_CONFLICT", "/mutation/result/artifact_digest")
        local_record = {
            "local_dispatch_id": record["outbox_id"],
            "verification_id": identity["verification_id"],
            "goal_id": identity["goal_id"],
            "worker_dispatch_id": identity["worker_dispatch_id"],
            "artifact_digest": result["artifact_digest"],
            "report_digest": result["report_digest"],
            "status": result["status"],
            "roadmap_version": record["roadmap_version"],
            "evidence_paths": list(record["ack_evidence_paths"]),
        }
        state["local_verification_ledger"][record["outbox_id"]] = local_record
        goal = state["goal_execution_ledger"][identity["goal_id"]]
        goal["status"] = "LOCAL_VERIFICATION_PASS" if result["status"] == "PASS" else "REPAIR_REQUIRED"

    def _record_control_outbox_result(
        self,
        state: dict[str, Any],
        record: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        kind = record["outbox_kind"]
        identity = record["identity"]
        if kind == "THREAD":
            required = {
                "thread_id",
                "project_id",
                "task_kind",
                "bootstrap_role_kind",
                "formal_role_kind",
                "bootstrap_prompt_digest",
                "environment_kind",
                "worktree_path",
            }
            if set(result) != required:
                raise RuntimeRejection("THREAD_RESULT_INVALID", "/mutation/result")
            thread_id = result["thread_id"]
            if not isinstance(thread_id, str) or SAFE_ID_RE.fullmatch(thread_id) is None:
                raise RuntimeRejection("UNSAFE_ID", "/mutation/result/thread_id")
            if (
                result["bootstrap_role_kind"] not in BOOTSTRAP_ROLE_TO_FORMAL_ROLE
                or BOOTSTRAP_ROLE_TO_FORMAL_ROLE[result["bootstrap_role_kind"]]
                != result["formal_role_kind"]
            ):
                raise RuntimeRejection(
                    "THREAD_ROLE_MAPPING_INVALID", "/mutation/result"
                )
            for key in (
                "project_id",
                "task_kind",
                "bootstrap_role_kind",
                "formal_role_kind",
                "bootstrap_prompt_digest",
                "environment_kind",
            ):
                if result[key] != identity[key]:
                    raise RuntimeRejection("THREAD_IDENTITY_CONFLICT", f"/mutation/result/{key}")
            worktree = result["worktree_path"]
            candidate = self.root / worktree if not Path(worktree).is_absolute() else Path(worktree)
            candidate = self._assert_authorized_worktree(
                state,
                candidate,
                "/mutation/result/worktree_path",
            )
            existing = state["thread_registry"].get(thread_id)
            thread_record = {
                "thread_id": thread_id,
                "project_id": result["project_id"],
                "task_kind": result["task_kind"],
                "bootstrap_role_kind": result["bootstrap_role_kind"],
                "role_kind": result["formal_role_kind"],
                "bootstrap_prompt_digest": result["bootstrap_prompt_digest"],
                "status": "REGISTERED",
                "worktree_path": str(candidate.resolve(strict=False)),
            }
            if existing is not None and existing != thread_record:
                raise RuntimeRejection("THREAD_IDENTITY_CONFLICT", "/mutation/result/thread_id")
            state["thread_registry"][thread_id] = thread_record
        elif kind == "AUTOMATION":
            required = {
                *identity,
                "automation_id",
                "status",
            }
            if set(result) != required or any(result[key] != value for key, value in identity.items()):
                raise RuntimeRejection("AUTOMATION_RESULT_INVALID", "/mutation/result")
            if result["status"] != "ACTIVE":
                raise RuntimeRejection("AUTOMATION_RESULT_INVALID", "/mutation/result/status")
        elif kind == "GOAL":
            required = {*identity, "goal_id", "status"}
            if set(result) != required or any(result[key] != value for key, value in identity.items()):
                raise RuntimeRejection("CONTROLLER_GOAL_RESULT_INVALID", "/mutation/result")
            expected_statuses = (
                {"ACTIVE"}
                if identity["action"] == "CREATE" and record["status"] == "SENT"
                else {"EMULATED_SINGLE_ACTIVE_MILESTONE"}
                if identity["action"] == "CREATE"
                else {identity["target_status"]}
            )
            if result["status"] not in expected_statuses:
                raise RuntimeRejection("CONTROLLER_GOAL_RESULT_INVALID", "/mutation/result/status")
            state["controller_goal"] = copy.deepcopy(result)

    @staticmethod
    def _delegation_policy(state: dict[str, Any]) -> dict[str, Any]:
        return copy.deepcopy(
            state["authorization_envelope"].get(
                "delegation_policy",
                {
                    "mode": "disabled",
                    "max_concurrent": 0,
                    "max_lifetime_runs": 0,
                    "retry_limit_per_exploration": 0,
                    "max_depth": 1,
                },
            )
        )

    def _validate_delegation_prepare(
        self,
        state: dict[str, Any],
        identity: dict[str, Any],
        target_id: str,
    ) -> None:
        required = {
            "exploration_id",
            "attempt_id",
            "prompt_digest",
            "scope_digest",
            "source_goal_id",
            "source_roadmap_version",
            "max_depth",
        }
        self._require_exact_keys(identity, required, "/mutation/identity")
        policy = self._delegation_policy(state)
        if policy["mode"] not in {"explicit_read_only", "auto_read_only"}:
            raise RuntimeRejection(
                "DELEGATION_NOT_AUTHORIZED",
                "/authorization_envelope/delegation_policy/mode",
            )
        if (
            target_id != identity["exploration_id"]
            or identity["max_depth"] != 1
            or identity["max_depth"] != policy["max_depth"]
            or identity["source_roadmap_version"] != state["roadmap_version"]
            or identity["source_goal_id"] not in state["goal_definition_registry"]
        ):
            raise RuntimeRejection("DELEGATION_IDENTITY_INVALID", "/mutation/identity")
        attempts = state["subagent_attempt_ledger"].get(identity["exploration_id"], [])
        if any(attempt["status"] == "COMPLETED" for attempt in attempts):
            raise RuntimeRejection(
                "DELEGATION_ALREADY_COMPLETED",
                "/mutation/identity/exploration_id",
            )
        if attempts and attempts[-1]["status"] in {"PREPARED", "RUNNING"}:
            raise RuntimeRejection(
                "DELEGATION_ATTEMPT_ACTIVE",
                "/mutation/identity/exploration_id",
            )
        if len(attempts) >= 1 + policy["retry_limit_per_exploration"]:
            raise RuntimeRejection(
                "DELEGATION_RETRY_BUDGET_EXHAUSTED",
                "/mutation/identity/attempt_id",
            )
        if sum(len(items) for items in state["subagent_attempt_ledger"].values()) >= policy[
            "max_lifetime_runs"
        ]:
            raise RuntimeRejection(
                "DELEGATION_RUN_BUDGET_EXHAUSTED", "/delegation_ledger"
            )
        active = sum(
            record["status"] in {"PREPARED", "SENT"}
            for record in state["delegation_ledger"].values()
        )
        if active >= policy["max_concurrent"]:
            raise RuntimeRejection(
                "DELEGATION_CONCURRENCY_LIMIT", "/delegation_ledger"
            )
        if any(
            attempt["attempt_id"] == identity["attempt_id"]
            for items in state["subagent_attempt_ledger"].values()
            for attempt in items
        ):
            raise RuntimeRejection(
                "DELEGATION_ATTEMPT_ID_CONFLICT",
                "/mutation/identity/attempt_id",
            )

    @staticmethod
    def _delegation_attempt(
        state: dict[str, Any], record: dict[str, Any]
    ) -> dict[str, Any]:
        identity = record["identity"]
        matches = [
            attempt
            for attempt in state["subagent_attempt_ledger"].get(
                identity["exploration_id"], []
            )
            if attempt["attempt_id"] == identity["attempt_id"]
            and attempt["outbox_id"] == record["outbox_id"]
        ]
        if len(matches) != 1:
            raise RuntimeRejection(
                "DELEGATION_ATTEMPT_IDENTITY_MISMATCH",
                "/subagent_attempt_ledger",
            )
        return matches[0]

    def _record_delegation_result(
        self,
        state: dict[str, Any],
        request: dict[str, Any],
        record: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        identity = record["identity"]
        required = {*identity, "agent_id", "status", "report_digest"}
        if set(result) != required or any(
            result[key] != value for key, value in identity.items()
        ):
            raise RuntimeRejection("DELEGATION_RESULT_INVALID", "/mutation/result")
        if result["status"] not in {"COMPLETED", "INTERRUPTED", "DROPPED"}:
            raise RuntimeRejection(
                "DELEGATION_RESULT_INVALID", "/mutation/result/status"
            )
        self._require_bound_report_artifact(
            request,
            record["ack_evidence_paths"],
            result["report_digest"],
            "/mutation/result/report_digest",
        )
        attempt = self._delegation_attempt(state, record)
        if attempt["status"] != "RUNNING":
            raise RuntimeRejection(
                "DELEGATION_ATTEMPT_NOT_RUNNING", "/subagent_attempt_ledger"
            )
        attempt.update(
            {
                "status": result["status"],
                "report_digest": result["report_digest"],
                "agent_id": result["agent_id"],
            }
        )

    def _latest_worker_exact(
        self,
        state: dict[str, Any],
        goal_id: str,
        dispatch_id: str,
        artifact_digest: str,
    ) -> dict[str, Any]:
        ledger = state["goal_execution_ledger"].get(goal_id)
        worker = ledger.get("latest_worker") if ledger else None
        if (
            worker is None
            or worker["status"] != "PASS"
            or worker["dispatch_id"] != dispatch_id
            or worker["artifact_digest"] != artifact_digest
            or worker["roadmap_version"] != state["roadmap_version"]
        ):
            raise RuntimeRejection("WORKER_IDENTITY_MISMATCH", "/mutation")
        return worker

    def _require_review(
        self,
        state: dict[str, Any],
        review_id: str,
        review_kind: str,
        goal_id: str,
        worker_dispatch_id: str,
        artifact_digest: str,
        allowed_decisions: set[str],
    ) -> dict[str, Any]:
        review = state["assurance_ledger"].get(review_id)
        if (
            review is None
            or review["review_kind"] != review_kind
            or review["goal_id"] != goal_id
            or review["worker_dispatch_id"] != worker_dispatch_id
            or review["artifact_digest"] != artifact_digest
            or review["roadmap_version"] != state["roadmap_version"]
            or review["decision"] not in allowed_decisions
        ):
            raise RuntimeRejection("REVIEW_CHAIN_INVALID", f"/assurance_ledger/{review_id}")
        return review

    def _local_pass_exists(
        self,
        state: dict[str, Any],
        goal_id: str,
        worker_dispatch_id: str,
        artifact_digest: str,
    ) -> bool:
        return any(
            record.get("goal_id") == goal_id
            and record.get("worker_dispatch_id") == worker_dispatch_id
            and record.get("artifact_digest") == artifact_digest
            and record.get("roadmap_version") == state["roadmap_version"]
            and record.get("status") == "PASS"
            for record in state["local_verification_ledger"].values()
        )

    def _assert_assurance_ready(
        self,
        state: dict[str, Any],
        identity: dict[str, Any],
        reviewer_thread_id: str,
    ) -> None:
        reviewer = state["thread_registry"].get(reviewer_thread_id)
        if (
            reviewer is None
            or reviewer["role_kind"] != "REVIEWER"
            or reviewer["status"] != "REGISTERED"
        ):
            raise RuntimeRejection("REVIEWER_IDENTITY_MISMATCH", "/mutation/target_id")
        review_kind = self._identity_value(identity, "review_kind", "/mutation/identity")
        if review_kind not in REVIEW_DECISIONS:
            raise RuntimeRejection("REVIEW_KIND_INVALID", "/mutation/identity/review_kind")
        goal_id = self._identity_value(identity, "goal_id", "/mutation/identity")
        worker_dispatch_id = self._identity_value(
            identity, "worker_dispatch_id", "/mutation/identity"
        )
        artifact_digest = self._identity_value(
            identity, "artifact_digest", "/mutation/identity"
        )
        worker = self._latest_worker_exact(
            state, goal_id, worker_dispatch_id, artifact_digest
        )
        worker_report_digest = self._identity_value(
            identity,
            "worker_report_digest",
            "/mutation/identity",
        )
        if worker["report_digest"] != worker_report_digest:
            raise RuntimeRejection(
                "WORKER_REPORT_IDENTITY_MISMATCH",
                "/mutation/identity/worker_report_digest",
            )
        if review_kind in {"ROADMAP_AUDIT", "FINAL_AUDIT"}:
            code_review_id = self._identity_value(
                identity, "code_review_id", "/mutation/identity"
            )
            self._require_review(
                state,
                code_review_id,
                "CODE_REVIEW",
                goal_id,
                worker_dispatch_id,
                artifact_digest,
                CODE_REVIEW_PASS,
            )
            if goal_id in state["local_verification_required_goal_ids"] and not self._local_pass_exists(
                state, goal_id, worker_dispatch_id, artifact_digest
            ):
                raise RuntimeRejection("LOCAL_VERIFICATION_REQUIRED", "/mutation/identity")
        if review_kind == "FINAL_AUDIT":
            roadmap_audit_id = self._identity_value(
                identity, "roadmap_audit_id", "/mutation/identity"
            )
            self._require_review(
                state,
                roadmap_audit_id,
                "ROADMAP_AUDIT",
                goal_id,
                worker_dispatch_id,
                artifact_digest,
                {"ROADMAP_AUDIT_PASS_FINAL_CANDIDATE"},
            )

    def _record_review(
        self,
        state: dict[str, Any],
        request: dict[str, Any],
        mutation: dict[str, Any],
        after_version: int,
    ) -> dict[str, Any]:
        claim = mutation["lease_claim"]
        lease = self._require_exact_lease(state, claim, mutation["observed_at"])
        self._reserve_route(lease, "OUTBOX", mutation["review_dispatch_id"])
        outbox = state["assurance_dispatch_outbox"].get(mutation["review_dispatch_id"])
        if outbox is None or outbox["status"] != "ACKED":
            raise RuntimeRejection(
                "ASSURANCE_OUTBOX_NOT_ACKED", "/mutation/review_dispatch_id"
            )
        if outbox["lease_claim"] != claim:
            raise RuntimeRejection("OUTBOX_LEASE_MISMATCH", "/mutation/lease_claim")
        identity = outbox["identity"]
        expected_identity = {
            "review_kind": mutation["review_kind"],
            "goal_id": mutation["goal_id"],
            "worker_dispatch_id": mutation["worker_dispatch_id"],
            "worker_report_digest": mutation["worker_report_digest"],
            "artifact_digest": mutation["artifact_digest"],
        }
        if any(identity.get(key) != value for key, value in expected_identity.items()):
            raise RuntimeRejection("REVIEW_OUTBOX_IDENTITY_CONFLICT", "/mutation")
        if mutation["roadmap_version"] != state["roadmap_version"]:
            raise RuntimeRejection("ROADMAP_VERSION_CONFLICT", "/mutation/roadmap_version")
        if mutation["decision"] not in REVIEW_DECISIONS[mutation["review_kind"]]:
            raise RuntimeRejection("REVIEW_DECISION_INVALID", "/mutation/decision")
        report = self._require_bound_json_report_artifact(
            request,
            mutation["review_evidence_paths"],
            mutation["report_digest"],
            "/mutation/report_digest",
        )
        ack_result = outbox.get("result")
        legacy_empty_result = ack_result in ({}, None)
        if legacy_empty_result:
            ack_result = {
                "status": mutation["decision"],
                "report_digest": mutation["report_digest"],
                "artifact_digest": mutation["artifact_digest"],
            }
        elif ack_result != {
            "status": mutation["decision"],
            "report_digest": mutation["report_digest"],
            "artifact_digest": mutation["artifact_digest"],
        }:
            raise RuntimeRejection(
                "REVIEW_ACK_RESULT_MISMATCH",
                "/mutation",
            )
        self._validate_formal_report(state, outbox, ack_result, report)
        if legacy_empty_result:
            outbox["result"] = copy.deepcopy(ack_result)
        if (
            outbox["target_id"] != mutation["reviewer_thread_id"]
            or mutation["reviewer_thread_id"] not in state["thread_registry"]
        ):
            raise RuntimeRejection(
                "REVIEWER_IDENTITY_MISMATCH",
                "/mutation/reviewer_thread_id",
            )
        self._assert_assurance_ready(
            state,
            identity,
            mutation["reviewer_thread_id"],
        )
        review_id = mutation["review_id"]
        record = {
            "review_id": review_id,
            "review_kind": mutation["review_kind"],
            "review_dispatch_id": mutation["review_dispatch_id"],
            "goal_id": mutation["goal_id"],
            "worker_dispatch_id": mutation["worker_dispatch_id"],
            "worker_report_digest": mutation["worker_report_digest"],
            "reviewer_thread_id": mutation["reviewer_thread_id"],
            "roadmap_version": mutation["roadmap_version"],
            "artifact_digest": mutation["artifact_digest"],
            "report_digest": mutation["report_digest"],
            "decision": mutation["decision"],
            "roadmap_proposal_digest": report.get("roadmap_proposal_digest"),
            "roadmap_proposal": copy.deepcopy(report.get("roadmap_proposal")),
            "evidence_paths": list(mutation["review_evidence_paths"]),
        }
        existing = state["assurance_ledger"].get(review_id)
        if existing is not None and existing != record:
            raise RuntimeRejection("REVIEW_ID_CONFLICT", "/mutation/review_id")
        if existing is not None:
            raise RuntimeRejection("REVIEW_ALREADY_RECORDED", "/mutation/review_id")
        state["assurance_ledger"][review_id] = record
        outbox["status"] = "COMPLETED"
        goal = state["goal_execution_ledger"][mutation["goal_id"]]
        kind = mutation["review_kind"]
        decision = mutation["decision"]
        if kind == "CODE_REVIEW":
            goal["status"] = "CODE_REVIEW_PASS" if decision in CODE_REVIEW_PASS else "REPAIR_REQUIRED"
            next_action = (
                "PREPARE_LOCAL_VERIFICATION"
                if decision in CODE_REVIEW_PASS
                and mutation["goal_id"] in state["local_verification_required_goal_ids"]
                else "PREPARE_ROADMAP_AUDIT"
                if decision in CODE_REVIEW_PASS
                else "REPAIR_REQUIRED"
            )
        elif kind == "ROADMAP_AUDIT":
            if decision == "ROADMAP_AUDIT_PASS_FINAL_CANDIDATE":
                goal["status"] = "FINAL_CANDIDATE"
                next_action = "PREPARE_FINAL_AUDIT"
            elif decision == "ROADMAP_AUDIT_PASS":
                goal["status"] = "CODE_REVIEW_PASS"
                next_action = "ROADMAP_REVISION"
            elif decision == "ROADMAP_CHANGE_PROPOSED":
                goal["status"] = "CODE_REVIEW_PASS"
                next_action = "ROADMAP_CHANGE_REQUIRES_APPROVAL"
            else:
                goal["status"] = "REPAIR_REQUIRED"
                next_action = "REPAIR_REQUIRED"
        else:
            goal["status"] = "FINAL_AUDIT_PASS" if decision in FINAL_PASS else "REPAIR_REQUIRED"
            next_action = "FINALIZE_LOOP" if decision in FINAL_PASS else "REPAIR_REQUIRED"
        self._finish_route(state, claim, after_version)
        return {
            "code": f"{kind}_ACKED",
            "next_action_code": next_action,
            "result": {
                "review_id": review_id,
                "review_kind": kind,
                "decision": decision,
            },
        }

    @staticmethod
    def _require_bound_report_artifact(
        request: dict[str, Any],
        evidence_paths: list[str],
        report_digest: Any,
        path: str,
    ) -> None:
        if not isinstance(report_digest, str) or DIGEST_RE.fullmatch(report_digest) is None:
            raise RuntimeRejection("DIGEST_INVALID", path)
        matches = [
            artifact
            for artifact in request["artifacts"]
            if artifact["path"] in evidence_paths
            and artifact["digest"] == report_digest
            and artifact["media_type"] == "application/json"
        ]
        if len(matches) != 1:
            raise RuntimeRejection(
                "REPORT_ARTIFACT_UNBOUND",
                path,
                {"report_digest": report_digest},
            )

    @staticmethod
    def _require_bound_json_report_artifact(
        request: dict[str, Any],
        evidence_paths: list[str],
        report_digest: Any,
        path: str,
    ) -> dict[str, Any]:
        AdaptiveStateRuntime._require_bound_report_artifact(
            request, evidence_paths, report_digest, path
        )
        matches = [
            artifact
            for artifact in request["artifacts"]
            if artifact["path"] in evidence_paths
            and artifact["digest"] == report_digest
            and artifact["media_type"] == "application/json"
        ]
        report = _strict_json_loads(
            matches[0]["content"],
            code="FORMAL_REPORT_JSON_INVALID",
            path=path,
        )
        if not isinstance(report, dict):
            raise RuntimeRejection("FORMAL_REPORT_NOT_OBJECT", path)
        canonical = json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if matches[0]["content"] != canonical:
            raise RuntimeRejection("FORMAL_REPORT_NOT_CANONICAL", path)
        return report

    @staticmethod
    def _validate_roadmap_proposal_value(
        proposal: Any,
        proposal_digest: Any,
        path: str,
        *,
        required_authorization_value: bool | None = None,
    ) -> None:
        if not isinstance(proposal, dict) or set(proposal) != ROADMAP_PROPOSAL_KEYS:
            raise RuntimeRejection("ROADMAP_PROPOSAL_INVALID", path)
        if not isinstance(proposal_digest, str) or DIGEST_RE.fullmatch(proposal_digest) is None:
            raise RuntimeRejection("DIGEST_INVALID", f"{path}_digest")
        if _digest(proposal) != proposal_digest:
            raise RuntimeRejection("ROADMAP_PROPOSAL_DIGEST_MISMATCH", f"{path}_digest")
        for key in (
            "proposal_id",
            "roadmap_audit_dispatch_id",
            "next_goal_id",
            "reason_code",
        ):
            if not isinstance(proposal[key], str) or SAFE_ID_RE.fullmatch(proposal[key]) is None:
                raise RuntimeRejection("ROADMAP_PROPOSAL_INVALID", f"{path}/{key}")
        if (
            not isinstance(proposal["base_roadmap_version"], int)
            or isinstance(proposal["base_roadmap_version"], bool)
            or proposal["base_roadmap_version"] < 1
            or not isinstance(proposal["within_authorized_envelope"], bool)
        ):
            raise RuntimeRejection("ROADMAP_PROPOSAL_INVALID", path)
        if (
            required_authorization_value is not None
            and proposal["within_authorized_envelope"]
            is not required_authorization_value
        ):
            raise RuntimeRejection(
                "ROADMAP_PROPOSAL_AUTHORIZATION_ASSERTION_INVALID",
                f"{path}/within_authorized_envelope",
            )
        for key in (
            "milestones_digest",
            "goal_queue_digest",
            "goal_definition_registry_digest",
            "authorization_envelope_digest",
        ):
            if not isinstance(proposal[key], str) or DIGEST_RE.fullmatch(proposal[key]) is None:
                raise RuntimeRejection("ROADMAP_PROPOSAL_INVALID", f"{path}/{key}")
        estimate_digest = proposal["estimate_digest"]
        if estimate_digest is not None and (
            not isinstance(estimate_digest, str)
            or DIGEST_RE.fullmatch(estimate_digest) is None
        ):
            raise RuntimeRejection("ROADMAP_PROPOSAL_INVALID", f"{path}/estimate_digest")
        operations = proposal["operations"]
        if not isinstance(operations, list) or not operations:
            raise RuntimeRejection("ROADMAP_PROPOSAL_INVALID", f"{path}/operations")
        for index, operation in enumerate(operations):
            operation_path = f"{path}/operations/{index}"
            if not isinstance(operation, dict):
                raise RuntimeRejection("ROADMAP_PROPOSAL_INVALID", operation_path)
            operation_type = operation.get("operation")
            if operation_type not in ROADMAP_OPERATION_TYPES:
                raise RuntimeRejection("ROADMAP_PROPOSAL_INVALID", operation_path)
            expected_keys = (
                {"operation", "ordered_milestone_ids", "reason"}
                if operation_type == "REORDER_FUTURE_MILESTONES"
                else {"operation", "milestone_id", "reason"}
            )
            if set(operation) != expected_keys:
                raise RuntimeRejection("ROADMAP_PROPOSAL_INVALID", operation_path)
            if not isinstance(operation["reason"], str) or not operation["reason"]:
                raise RuntimeRejection("ROADMAP_PROPOSAL_INVALID", f"{operation_path}/reason")
            if operation_type == "REORDER_FUTURE_MILESTONES":
                ordered = operation["ordered_milestone_ids"]
                if (
                    not isinstance(ordered, list)
                    or not ordered
                    or len(ordered) != len(set(ordered))
                    or any(
                        not isinstance(item, str) or SAFE_ID_RE.fullmatch(item) is None
                        for item in ordered
                    )
                ):
                    raise RuntimeRejection(
                        "ROADMAP_PROPOSAL_INVALID",
                        f"{operation_path}/ordered_milestone_ids",
                    )
            else:
                milestone_id = operation["milestone_id"]
                if not isinstance(milestone_id, str) or SAFE_ID_RE.fullmatch(milestone_id) is None:
                    raise RuntimeRejection(
                        "ROADMAP_PROPOSAL_INVALID",
                        f"{operation_path}/milestone_id",
                    )

    def _validate_formal_report(
        self,
        state: dict[str, Any],
        record: dict[str, Any],
        result: dict[str, Any],
        report: dict[str, Any],
    ) -> None:
        kind = record["outbox_kind"]
        identity = record["identity"]
        required_result = {"status", "report_digest", "artifact_digest"}
        missing_result = sorted(required_result - set(result))
        if missing_result:
            raise RuntimeRejection(
                "FORMAL_REPORT_RESULT_FIELD_MISSING",
                "/mutation/result",
                {"fields": missing_result},
            )
        extra_result = sorted(set(result) - required_result)
        if extra_result:
            raise RuntimeRejection(
                "FORMAL_REPORT_RESULT_FIELD_UNEXPECTED",
                "/mutation/result",
                {"fields": extra_result},
            )

        goal_id = identity["goal_id"]
        if kind == "DISPATCH":
            definition = state["goal_definition_registry"][goal_id]
            milestone_id = definition["milestone_id"]
            expected = {
                "source_goal_definition_digest_or_none": identity[
                    "goal_definition_digest"
                ],
                "source_artifact_digest": result["artifact_digest"],
            }
            allowed_statuses = {"PASS", "FAIL", "BLOCKED"}
        elif kind == "LOCAL":
            milestone_id = identity["milestone_id"]
            expected = {
                "source_worker_dispatch_id": identity["worker_dispatch_id"],
                "source_artifact_digest": identity["artifact_digest"],
                "verification_id": identity["verification_id"],
            }
            allowed_statuses = {"PASS", "FAIL", "BLOCKED"}
        elif kind == "ASSURANCE":
            milestone_id = identity["milestone_id"]
            worker_outbox = state["dispatch_outbox"].get(
                identity["worker_dispatch_id"]
            )
            if worker_outbox is None:
                raise RuntimeRejection(
                    "SOURCE_WORKER_OUTBOX_MISSING",
                    "/mutation/outbox_id",
                )
            expected = {
                "review_kind": identity["review_kind"],
                "review_dispatch_id": record["outbox_id"],
                "review_decision": result["status"],
                "source_worker_dispatch_id": identity["worker_dispatch_id"],
                "source_worker_report_digest": identity["worker_report_digest"],
                "worker_thread_id": worker_outbox["target_id"],
                "source_artifact_digest": identity["artifact_digest"],
            }
            allowed_statuses = REVIEW_DECISIONS[identity["review_kind"]]
        else:  # pragma: no cover - guarded by caller
            raise RuntimeRejection("FORMAL_REPORT_KIND_INVALID", "/mutation/outbox_kind")

        if result["status"] not in allowed_statuses:
            raise RuntimeRejection(
                "FORMAL_REPORT_DECISION_INVALID",
                "/mutation/result/status",
            )
        if result["artifact_digest"] != expected["source_artifact_digest"]:
            raise RuntimeRejection(
                "FORMAL_REPORT_ARTIFACT_RESULT_MISMATCH",
                "/mutation/result/artifact_digest",
            )

        expected.update(
            {
                "status": result["status"],
                "report_digest": "PENDING_CONTROLLER_ARCHIVE",
                "goal_id": goal_id,
                "dispatch_id": record["outbox_id"],
                "milestone_id": milestone_id,
                "roadmap_version": record["roadmap_version"],
                "target_thread_id": record["target_id"],
                "thread_id": record["target_id"],
                "dispatch_payload_digest": record["payload_digest"],
            }
        )
        missing = sorted(set(expected) - set(report))
        if missing:
            raise RuntimeRejection(
                "FORMAL_REPORT_REQUIRED_FIELD_MISSING",
                "/artifacts/report",
                {"fields": missing},
            )
        mismatched = sorted(
            field for field, value in expected.items() if report[field] != value
        )
        if mismatched:
            raise RuntimeRejection(
                "FORMAL_REPORT_IDENTITY_MISMATCH",
                "/artifacts/report",
                {"fields": mismatched},
            )
        proposal_required = bool(
            kind == "ASSURANCE"
            and identity["review_kind"] == "ROADMAP_AUDIT"
            and result["status"]
            in {"ROADMAP_AUDIT_PASS", "ROADMAP_CHANGE_PROPOSED"}
        )
        proposal_present = (
            "roadmap_proposal" in report
            or "roadmap_proposal_digest" in report
        )
        if proposal_required:
            if not {
                "roadmap_proposal",
                "roadmap_proposal_digest",
            }.issubset(report):
                raise RuntimeRejection(
                    "ROADMAP_PROPOSAL_REQUIRED",
                    "/artifacts/report",
                )
            self._validate_roadmap_proposal_value(
                report["roadmap_proposal"],
                report["roadmap_proposal_digest"],
                "/artifacts/report/roadmap_proposal",
                required_authorization_value=(
                    result["status"] == "ROADMAP_AUDIT_PASS"
                ),
            )
            if (
                report["roadmap_proposal"]["roadmap_audit_dispatch_id"]
                != record["outbox_id"]
                or report["roadmap_proposal"]["base_roadmap_version"]
                != record["roadmap_version"]
            ):
                raise RuntimeRejection(
                    "ROADMAP_PROPOSAL_IDENTITY_MISMATCH",
                    "/artifacts/report/roadmap_proposal",
                )
        elif proposal_present:
            raise RuntimeRejection(
                "ROADMAP_PROPOSAL_UNEXPECTED",
                "/artifacts/report/roadmap_proposal",
            )

    @staticmethod
    def _require_single_json_evidence_artifact(
        request: dict[str, Any],
        evidence_paths: list[str],
        path: str,
    ) -> None:
        matches = [
            artifact
            for artifact in request["artifacts"]
            if artifact["path"] in evidence_paths
            and artifact["media_type"] == "application/json"
        ]
        if len(matches) != 1:
            raise RuntimeRejection("EMULATED_GOAL_EVIDENCE_UNBOUND", path)

    @staticmethod
    def _active_versioned_outboxes(state: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            record
            for kind, field in (
                ("DISPATCH", "dispatch_outbox"),
                ("ASSURANCE", "assurance_dispatch_outbox"),
                ("LOCAL", "local_verification_outbox"),
                ("DELEGATION", "delegation_ledger"),
            )
            for record in state[field].values()
            if record["status"] in ACTIVE_OUTBOX_STATUSES
            or (kind == "ASSURANCE" and record["status"] == "ACKED")
        ]

    @staticmethod
    def _unfinished_finalization_outboxes(
        state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return [
            record
            for kind, field in OUTBOX_FIELDS.items()
            for record in state[field].values()
            if record["status"] in {"PREPARED", "SENT"}
            or (kind == "ASSURANCE" and record["status"] == "ACKED")
        ]

    @staticmethod
    def _validate_roadmap_operations(
        current_milestones: list[dict[str, Any]],
        proposed_milestones: list[dict[str, Any]],
        source_milestone_id: str,
        operations: list[dict[str, Any]],
    ) -> None:
        current_by_id = {
            item["milestone_id"]: item for item in current_milestones
        }
        proposed_by_id = {
            item["milestone_id"]: item for item in proposed_milestones
        }
        removed = sorted(set(current_by_id) - set(proposed_by_id))
        if removed:
            raise RuntimeRejection(
                "ROADMAP_EVIDENCE_DELETION_FORBIDDEN",
                "/mutation/milestones",
                {"milestone_ids": removed},
            )

        expected: set[tuple[str, tuple[str, ...]]] = set()
        for milestone_id in sorted(set(proposed_by_id) - set(current_by_id)):
            expected.add(("ADD_MILESTONE", (milestone_id,)))
        for milestone_id in sorted(set(current_by_id) & set(proposed_by_id)):
            current = current_by_id[milestone_id]
            proposed = proposed_by_id[milestone_id]
            if current != proposed:
                operation = (
                    "SUPERSEDE_MILESTONE"
                    if proposed["status"] == "SUPERSEDED"
                    and current["status"] != "SUPERSEDED"
                    else "UPDATE_MILESTONE"
                )
                expected.add((operation, (milestone_id,)))
        if not expected:
            expected.add(("UPDATE_MILESTONE", (source_milestone_id,)))

        current_existing_order = [
            item["milestone_id"] for item in current_milestones
        ]
        proposed_existing_order = [
            item["milestone_id"]
            for item in proposed_milestones
            if item["milestone_id"] in current_by_id
        ]
        if proposed_existing_order != current_existing_order:
            expected.add(
                (
                    "REORDER_FUTURE_MILESTONES",
                    tuple(item["milestone_id"] for item in proposed_milestones),
                )
            )

        actual: set[tuple[str, tuple[str, ...]]] = set()
        for operation in operations:
            operation_type = operation["operation"]
            identity = (
                tuple(operation["ordered_milestone_ids"])
                if operation_type == "REORDER_FUTURE_MILESTONES"
                else (operation["milestone_id"],)
            )
            key = (operation_type, identity)
            if key in actual:
                raise RuntimeRejection(
                    "ROADMAP_OPERATION_DUPLICATE",
                    "/mutation/roadmap_proposal/operations",
                )
            actual.add(key)
        if actual != expected:
            raise RuntimeRejection(
                "ROADMAP_OPERATION_MISMATCH",
                "/mutation/roadmap_proposal/operations",
                {
                    "expected": [
                        [operation, list(identity)]
                        for operation, identity in sorted(expected)
                    ],
                    "actual": [
                        [operation, list(identity)]
                        for operation, identity in sorted(actual)
                    ],
                },
            )

    def _validate_roadmap_proposal_binding(
        self,
        state: dict[str, Any],
        mutation: dict[str, Any],
        source_milestone_id: str,
        audit: dict[str, Any],
    ) -> None:
        proposal = mutation["roadmap_proposal"]
        proposal_digest = mutation["roadmap_proposal_digest"]
        self._validate_roadmap_proposal_value(
            proposal,
            proposal_digest,
            "/mutation/roadmap_proposal",
            required_authorization_value=True,
        )
        if (
            audit["report_digest"] != mutation["roadmap_audit_report_digest"]
            or audit.get("roadmap_proposal_digest") != proposal_digest
            or audit.get("roadmap_proposal") != proposal
            or proposal["roadmap_audit_dispatch_id"]
            != audit["review_dispatch_id"]
            or proposal["base_roadmap_version"]
            != mutation["base_roadmap_version"]
            or proposal["next_goal_id"] != mutation["next_goal_id"]
            or proposal["reason_code"] != mutation["reason_code"]
        ):
            raise RuntimeRejection(
                "ROADMAP_PROPOSAL_IDENTITY_MISMATCH",
                "/mutation/roadmap_proposal",
            )
        expected_component_digests = {
            "milestones_digest": _digest(mutation["milestones"]),
            "goal_queue_digest": _digest(mutation["goal_queue"]),
            "goal_definition_registry_digest": _digest(
                mutation["goal_definition_registry"]
            ),
            "authorization_envelope_digest": _digest(
                mutation["authorization_envelope"]
            ),
            "estimate_digest": (
                _digest(mutation["estimate"])
                if "estimate" in mutation
                else None
            ),
        }
        mismatched = sorted(
            key
            for key, value in expected_component_digests.items()
            if proposal[key] != value
        )
        if mismatched:
            raise RuntimeRejection(
                "ROADMAP_PROPOSAL_COMPONENT_MISMATCH",
                "/mutation/roadmap_proposal",
                {"fields": mismatched},
            )
        self._validate_roadmap_operations(
            state["milestones"],
            mutation["milestones"],
            source_milestone_id,
            proposal["operations"],
        )

    def _roadmap_revision(
        self,
        state: dict[str, Any],
        mutation: dict[str, Any],
        state_request_id: str,
        evidence_paths: list[str],
        after_version: int,
    ) -> dict[str, Any]:
        claim = mutation["lease_claim"]
        lease = self._require_exact_lease(state, claim, mutation["observed_at"])
        self._reserve_route(lease, "ROADMAP_REVISION", state_request_id)
        base = mutation["base_roadmap_version"]
        if base != state["roadmap_version"]:
            raise RuntimeRejection(
                "ROADMAP_VERSION_CONFLICT",
                "/mutation/base_roadmap_version",
                {"expected": base, "actual": state["roadmap_version"]},
            )
        if self._active_versioned_outboxes(state):
            raise RuntimeRejection(
                "ROADMAP_REVISION_ACTIVE_OUTBOX",
                "/mutation",
                {"required_action": "CANCEL_PREPARED_OUTBOX_FIRST"},
            )
        worker = self._latest_worker_exact(
            state,
            mutation["source_goal_id"],
            mutation["worker_dispatch_id"],
            mutation["artifact_digest"],
        )
        self._require_review(
            state,
            mutation["code_review_id"],
            "CODE_REVIEW",
            mutation["source_goal_id"],
            worker["dispatch_id"],
            mutation["artifact_digest"],
            CODE_REVIEW_PASS,
        )
        roadmap_audit = self._require_review(
            state,
            mutation["roadmap_audit_id"],
            "ROADMAP_AUDIT",
            mutation["source_goal_id"],
            worker["dispatch_id"],
            mutation["artifact_digest"],
            ROADMAP_REVISION_PASS,
        )
        old_definitions = state["goal_definition_registry"]
        source_definition = old_definitions[mutation["source_goal_id"]]
        self._validate_roadmap_proposal_binding(
            state,
            mutation,
            source_definition["milestone_id"],
            roadmap_audit,
        )
        controller_goal = state.get("controller_goal")
        if (
            not isinstance(controller_goal, dict)
            or controller_goal.get("status")
            not in {"ACTIVE", "EMULATED_SINGLE_ACTIVE_MILESTONE"}
            or controller_goal.get("milestone_id")
            != source_definition["milestone_id"]
        ):
            raise RuntimeRejection(
                "CONTROLLER_GOAL_MILESTONE_NOT_ACTIVE",
                "/controller_goal",
                {
                    "required_milestone_id": source_definition["milestone_id"],
                    "actual_milestone_id": (
                        controller_goal.get("milestone_id")
                        if isinstance(controller_goal, dict)
                        else None
                    ),
                },
            )
        proposed_definitions = copy.deepcopy(mutation["goal_definition_registry"])
        proposed_authorization = copy.deepcopy(mutation["authorization_envelope"])
        self._validate_roadmap_authorization(
            state["authorization_envelope"],
            proposed_authorization,
            proposed_definitions,
            mutation["milestones"],
        )
        for goal_id, definition in old_definitions.items():
            if proposed_definitions.get(goal_id) != definition:
                raise RuntimeRejection(
                    "IMMUTABLE_GOAL_DEFINITION_CONFLICT",
                    f"/mutation/goal_definition_registry/{goal_id}",
                )
        new_version = base + 1
        proposed_queue = copy.deepcopy(mutation["goal_queue"])
        if any(entry["roadmap_version"] != new_version for entry in proposed_queue):
            raise RuntimeRejection("ROADMAP_VERSION_CONFLICT", "/mutation/goal_queue")
        source_goal_id = mutation["source_goal_id"]
        if any(entry["goal_id"] == source_goal_id for entry in proposed_queue):
            raise RuntimeRejection("COMPLETED_GOAL_REQUEUED", "/mutation/goal_queue")
        next_entry = next(
            (entry for entry in proposed_queue if entry["goal_id"] == mutation["next_goal_id"]),
            None,
        )
        if next_entry is None or next_entry["status"] != "READY":
            raise RuntimeRejection("NEXT_GOAL_NOT_READY", "/mutation/next_goal_id")
        proposed_active = [
            item["milestone_id"]
            for item in mutation["milestones"]
            if item["status"] == "ACTIVE"
        ]
        if len(proposed_active) != 1 or next_entry["milestone_id"] != proposed_active[0]:
            raise RuntimeRejection(
                "NEXT_GOAL_NOT_IN_ACTIVE_MILESTONE",
                "/mutation/next_goal_id",
            )

        old_queue = copy.deepcopy(state["goal_queue"])
        state["goal_queue_history"].append(
            {"roadmap_version": base, "goal_queue": old_queue}
        )
        state["milestones"] = copy.deepcopy(mutation["milestones"])
        state["goal_definition_registry"] = proposed_definitions
        state["authorization_envelope"] = proposed_authorization
        state["goal_queue"] = proposed_queue
        state["roadmap_version"] = new_version
        active = [
            item["milestone_id"]
            for item in state["milestones"]
            if item["status"] == "ACTIVE"
        ]
        state["active_milestone_id"] = active[0] if len(active) == 1 else None
        state["roadmap_projection"] = {
            "roadmap_version": new_version,
            "projection_digest": mutation["projection_digest"],
        }
        if "estimate" in mutation:
            state["estimate_history"].append(copy.deepcopy(mutation["estimate"]))

        existing_ledger = state["goal_execution_ledger"]
        existing_ledger[source_goal_id]["status"] = "COMPLETE"
        existing_ledger[source_goal_id]["completed_roadmap_version"] = new_version
        queue_by_id = {entry["goal_id"]: entry for entry in proposed_queue}
        milestone_status = {
            item["milestone_id"]: item["status"] for item in state["milestones"]
        }
        for goal_id, definition in proposed_definitions.items():
            if goal_id not in existing_ledger:
                entry = queue_by_id.get(goal_id)
                existing_ledger[goal_id] = {
                    "goal_id": goal_id,
                    "milestone_id": definition["milestone_id"],
                    "definition_digest": definition["payload_template_digest"],
                    "status": entry["status"] if entry is not None else "PLANNED",
                    "attempts": [],
                    "latest_worker": None,
                    "completed_roadmap_version": None,
                }
            elif goal_id in queue_by_id and existing_ledger[goal_id]["status"] not in {
                "COMPLETE",
                "RETIRED",
            }:
                existing_ledger[goal_id]["status"] = queue_by_id[goal_id]["status"]
            elif (
                goal_id not in queue_by_id
                and existing_ledger[goal_id]["status"] not in {"COMPLETE", "RETIRED"}
                and milestone_status[definition["milestone_id"]] == "SUPERSEDED"
            ):
                existing_ledger[goal_id]["status"] = "RETIRED"
                existing_ledger[goal_id]["completed_roadmap_version"] = new_version
        state["roadmap_change_outbox"][state_request_id] = {
            "proposal_id": mutation["roadmap_proposal"]["proposal_id"],
            "status": "APPLIED",
            "base_roadmap_version": base,
            "new_roadmap_version": new_version,
            "source_goal_id": source_goal_id,
            "next_goal_id": mutation["next_goal_id"],
            "reason_code": mutation["reason_code"],
            "roadmap_audit_id": mutation["roadmap_audit_id"],
            "roadmap_audit_report_digest": mutation[
                "roadmap_audit_report_digest"
            ],
            "roadmap_proposal": copy.deepcopy(mutation["roadmap_proposal"]),
            "roadmap_proposal_digest": mutation["roadmap_proposal_digest"],
            "lease_claim": copy.deepcopy(claim),
            "evidence_paths": list(evidence_paths),
        }
        self._finish_route(state, claim, after_version)
        next_action = (
            "PREPARE_NEXT_GOAL_OUTBOX"
            if state["active_milestone_id"] == source_definition["milestone_id"]
            else "COMPLETE_CURRENT_CONTROLLER_GOAL"
        )
        return {
            "code": "ROADMAP_REVISION_APPLIED",
            "next_action_code": next_action,
            "result": {
                "roadmap_version": new_version,
                "next_goal_id": mutation["next_goal_id"],
            },
        }

    def _finalize_loop(
        self,
        state: dict[str, Any],
        mutation: dict[str, Any],
        after_version: int,
    ) -> dict[str, Any]:
        claim = mutation["lease_claim"]
        lease = self._require_exact_lease(state, claim, mutation["observed_at"])
        self._reserve_route(lease, "FINALIZE_LOOP", mutation["final_audit_id"])
        base = mutation["base_roadmap_version"]
        if base != state["roadmap_version"]:
            raise RuntimeRejection(
                "ROADMAP_VERSION_CONFLICT",
                "/mutation/base_roadmap_version",
                {"expected": base, "actual": state["roadmap_version"]},
            )
        if self._unfinished_finalization_outboxes(state):
            raise RuntimeRejection("FINALIZE_ACTIVE_OUTBOX", "/mutation")
        goal_id = mutation["final_goal_id"]
        worker = self._latest_worker_exact(
            state,
            goal_id,
            mutation["worker_dispatch_id"],
            mutation["artifact_digest"],
        )
        self._require_review(
            state,
            mutation["code_review_id"],
            "CODE_REVIEW",
            goal_id,
            worker["dispatch_id"],
            mutation["artifact_digest"],
            CODE_REVIEW_PASS,
        )
        self._require_review(
            state,
            mutation["roadmap_audit_id"],
            "ROADMAP_AUDIT",
            goal_id,
            worker["dispatch_id"],
            mutation["artifact_digest"],
            {"ROADMAP_AUDIT_PASS_FINAL_CANDIDATE"},
        )
        final_review = self._require_review(
            state,
            mutation["final_audit_id"],
            "FINAL_AUDIT",
            goal_id,
            worker["dispatch_id"],
            mutation["artifact_digest"],
            FINAL_PASS,
        )
        current_chain_has_limitation = any(
            review["worker_dispatch_id"] == worker["dispatch_id"]
            and review["artifact_digest"] == mutation["artifact_digest"]
            and review["decision"]
            in {"REVIEW_PASS_WITH_LIMITATION", "FINAL_REVIEW_PASS_WITH_LIMITATION"}
            for review in state["assurance_ledger"].values()
        )
        expected_terminal = (
            "LOOP_COMPLETE_WITH_LIMITATION"
            if current_chain_has_limitation
            else "LOOP_COMPLETE"
        )
        if mutation["terminal_status"] != expected_terminal:
            raise RuntimeRejection("TERMINAL_STATUS_EVIDENCE_MISMATCH", "/mutation/terminal_status")
        controller_goal = state["controller_goal"]
        definition = state["goal_definition_registry"].get(goal_id)
        if (
            not isinstance(controller_goal, dict)
            or controller_goal.get("goal_id") != mutation["controller_goal_id"]
            or controller_goal.get("status")
            not in {"ACTIVE", "EMULATED_SINGLE_ACTIVE_MILESTONE"}
            or definition is None
            or controller_goal.get("milestone_id") != definition["milestone_id"]
        ):
            raise RuntimeRejection(
                "FINALIZATION_GOAL_IDENTITY_MISMATCH",
                "/mutation/controller_goal_id",
            )
        automation_matches = [
            record
            for record in state["automation_outbox"].values()
            if record["status"] == "ACKED"
            and isinstance(record.get("result"), dict)
            and record["result"].get("automation_id") == mutation["automation_id"]
        ]
        if len(automation_matches) != 1:
            raise RuntimeRejection(
                "FINALIZATION_AUTOMATION_IDENTITY_MISMATCH",
                "/mutation/automation_id",
            )
        if state["finalization_outbox"] is not None:
            raise RuntimeRejection("FINALIZATION_ALREADY_PREPARED", "/finalization_outbox")
        if definition is None or definition["milestone_id"] != state["active_milestone_id"]:
            raise RuntimeRejection("FINAL_GOAL_NOT_ACTIVE", "/mutation/final_goal_id")
        if goal_id in state["local_verification_required_goal_ids"] and not self._local_pass_exists(
            state, goal_id, worker["dispatch_id"], mutation["artifact_digest"]
        ):
            raise RuntimeRejection("LOCAL_VERIFICATION_REQUIRED", "/mutation/final_goal_id")
        unresolved = [
            candidate
            for candidate, record in state["goal_execution_ledger"].items()
            if candidate != goal_id and record["status"] not in {"COMPLETE", "RETIRED"}
        ]
        if unresolved:
            raise RuntimeRejection(
                "FINALIZE_UNEXECUTED_GOALS",
                "/goal_execution_ledger",
                {"goal_ids": sorted(unresolved)},
            )
        for milestone in state["milestones"]:
            if milestone["milestone_id"] == state["active_milestone_id"]:
                continue
            if milestone["status"] not in {"COMPLETE", "SUPERSEDED"}:
                raise RuntimeRejection(
                    "FINALIZE_UNRESOLVED_MILESTONE",
                    "/milestones",
                    {"milestone_id": milestone["milestone_id"]},
                )
        state["goal_execution_ledger"][goal_id]["status"] = "COMPLETE"
        state["goal_execution_ledger"][goal_id]["completed_roadmap_version"] = base + 1
        for milestone in state["milestones"]:
            if milestone["milestone_id"] == state["active_milestone_id"]:
                milestone["status"] = "COMPLETE"
        state["goal_queue_history"].append(
            {"roadmap_version": base, "goal_queue": copy.deepcopy(state["goal_queue"])}
        )
        state["goal_queue"] = []
        state["active_milestone_id"] = None
        state["roadmap_version"] = base + 1
        state["roadmap_projection"] = {
            "roadmap_version": base + 1,
            "projection_digest": mutation["projection_digest"],
        }
        state["terminal_status"] = mutation["terminal_status"]
        state["finalization_outbox"] = {
            "finalization_id": mutation["finalization_id"],
            "status": "PREPARED",
            "finalized_state_version": after_version,
            "controller_goal_id": mutation["controller_goal_id"],
            "automation_id": mutation["automation_id"],
            "outcome_kind": "SUCCESS",
            "controller_goal_target_status": "COMPLETE",
            "automation_target_status": "PAUSED",
            "blocker_code": None,
            "blocker_fingerprint": None,
            "blocker_observations": [],
            "blocker_report_path": None,
            "blocker_report_digest": None,
        }
        self._finish_route(state, claim, after_version)
        return {
            "code": "FINALIZE_LOOP_APPLIED",
            "next_action_code": "COMPLETE_GOAL_AND_PAUSE_HEARTBEAT",
            "result": {
                "terminal_status": mutation["terminal_status"],
                "roadmap_version": base + 1,
                "finalization_id": mutation["finalization_id"],
                "controller_goal_id": mutation["controller_goal_id"],
                "automation_id": mutation["automation_id"],
            },
        }

    def _validate_blocker_observations(
        self,
        state: dict[str, Any],
        mutation: dict[str, Any],
        request: dict[str, Any],
    ) -> list[dict[str, Any]]:
        completed_actions = {
            record["routing_turn_id"]: record
            for record in state["routing_action_ledger"].values()
        }
        ordered_goal_turns = sorted(
            (
                completed_actions[turn_id]["completed_state_version"],
                turn_id,
            )
            for turn_id, turn in state["routing_turn_ledger"].items()
            if turn["owner_kind"] == "GOAL_TURN"
            and turn["status"] == "COMPLETED"
            and turn_id in completed_actions
        )
        eligible_turn_ids = [turn_id for _, turn_id in ordered_goal_turns]
        expected_turn_ids = eligible_turn_ids[-3:]
        observations = copy.deepcopy(mutation["blocker_observations"])
        if (
            len(expected_turn_ids) != 3
            or [item["goal_turn_id"] for item in observations]
            != expected_turn_ids
        ):
            raise RuntimeRejection(
                "GOAL_BLOCKER_OBSERVATIONS_INSUFFICIENT",
                "/mutation/blocker_observations",
                {"expected_goal_turn_ids": expected_turn_ids},
            )
        invalid_turns = [
            turn_id
            for turn_id in expected_turn_ids
            if completed_actions[turn_id]["route_action"] is not None
            or completed_actions[turn_id].get("release_reason_code")
            != "HARD_BLOCK_OBSERVATION_ONLY"
        ]
        if invalid_turns:
            raise RuntimeRejection(
                "GOAL_BLOCKER_OBSERVATIONS_NOT_OBSERVATION_ONLY",
                "/mutation/blocker_observations",
                {"goal_turn_ids": invalid_turns},
            )
        if (
            len({item["report_path"] for item in observations}) != 3
            or len({item["report_digest"] for item in observations}) != 3
        ):
            raise RuntimeRejection(
                "GOAL_BLOCKER_OBSERVATIONS_NOT_DISTINCT",
                "/mutation/blocker_observations",
            )
        observed_times = [
            _parse_time(item["observed_at"], f"/mutation/blocker_observations/{index}/observed_at")
            for index, item in enumerate(observations)
        ]
        if any(
            later <= earlier
            for earlier, later in zip(observed_times, observed_times[1:])
        ) or observed_times[-1] > _parse_time(
            mutation["observed_at"], "/mutation/observed_at"
        ):
            raise RuntimeRejection(
                "GOAL_BLOCKER_OBSERVATION_TIME_INVALID",
                "/mutation/blocker_observations",
            )
        for index, observation in enumerate(observations):
            if (
                observation["blocker_code"] != mutation["blocker_code"]
                or observation["blocker_fingerprint"]
                != mutation["blocker_fingerprint"]
                or observation["controller_goal_id"]
                != mutation["controller_goal_id"]
                or observation["report_path"] not in request["evidence_paths"]
            ):
                raise RuntimeRejection(
                    "GOAL_BLOCKER_OBSERVATION_IDENTITY_MISMATCH",
                    f"/mutation/blocker_observations/{index}",
                )
            expected = {
                "blocker_code": observation["blocker_code"],
                "blocker_fingerprint": observation["blocker_fingerprint"],
                "controller_goal_id": observation["controller_goal_id"],
                "goal_turn_id": observation["goal_turn_id"],
                "observed_at": observation["observed_at"],
                "status": "HARD_BLOCK",
            }
            completed_state_version = completed_actions[
                observation["goal_turn_id"]
            ]["completed_state_version"]
            self._require_existing_json_observation_artifact(
                state,
                observation["report_path"],
                observation["report_digest"],
                expected,
                completed_state_version,
                f"/mutation/blocker_observations/{index}/report_digest",
            )
        return observations

    def _stop_loop(
        self,
        state: dict[str, Any],
        mutation: dict[str, Any],
        request: dict[str, Any],
        after_version: int,
    ) -> dict[str, Any]:
        claim = mutation["lease_claim"]
        lease = self._require_exact_lease(state, claim, mutation["observed_at"])
        turn = state["routing_turn_ledger"].get(claim["routing_turn_id"])
        if (
            claim["owner_kind"] != "GOAL_TURN"
            or not isinstance(turn, dict)
            or turn.get("owner_kind") != "GOAL_TURN"
            or turn.get("owner_identity") != claim["owner_identity"]
            or turn.get("lease_id") != claim["lease_id"]
            or turn.get("status") != "LEASE_ACQUIRED"
        ):
            raise RuntimeRejection(
                "STOP_LOOP_REQUIRES_NEW_GOAL_TURN",
                "/mutation/lease_claim",
            )
        self._reserve_route(lease, "STOP_LOOP", mutation["finalization_id"])
        if self._unfinished_finalization_outboxes(state):
            raise RuntimeRejection("STOP_LOOP_ACTIVE_OUTBOX", "/mutation")
        if state["finalization_outbox"] is not None:
            raise RuntimeRejection("FINALIZATION_ALREADY_PREPARED", "/finalization_outbox")
        controller_goal = state["controller_goal"]
        if (
            not isinstance(controller_goal, dict)
            or controller_goal.get("goal_id") != mutation["controller_goal_id"]
            or controller_goal.get("status")
            not in {"ACTIVE", "EMULATED_SINGLE_ACTIVE_MILESTONE"}
            or controller_goal.get("milestone_id") != state["active_milestone_id"]
        ):
            raise RuntimeRejection(
                "FINALIZATION_GOAL_IDENTITY_MISMATCH",
                "/mutation/controller_goal_id",
            )
        automation_matches = [
            record
            for record in state["automation_outbox"].values()
            if record["status"] == "ACKED"
            and isinstance(record.get("result"), dict)
            and record["result"].get("automation_id") == mutation["automation_id"]
        ]
        if len(automation_matches) != 1:
            raise RuntimeRejection(
                "FINALIZATION_AUTOMATION_IDENTITY_MISMATCH",
                "/mutation/automation_id",
            )
        observations = self._validate_blocker_observations(
            state, mutation, request
        )
        blocker_path = mutation["blocker_report_path"]
        if blocker_path not in request["evidence_paths"]:
            raise RuntimeRejection(
                "BLOCKER_REPORT_NOT_EVIDENCE",
                "/mutation/blocker_report_path",
            )
        self._require_json_observation_artifact(
            request,
            blocker_path,
            mutation["blocker_report_digest"],
            {
                "blocker_code": mutation["blocker_code"],
                "blocker_fingerprint": mutation["blocker_fingerprint"],
                "controller_goal_id": mutation["controller_goal_id"],
                "observation_turn_ids": [
                    item["goal_turn_id"] for item in observations
                ],
                "status": "HARD_BLOCK",
            },
            "/mutation/blocker_report_digest",
        )
        base = state["roadmap_version"]
        state["goal_queue_history"].append(
            {"roadmap_version": base, "goal_queue": copy.deepcopy(state["goal_queue"])}
        )
        for milestone in state["milestones"]:
            if milestone["status"] == "ACTIVE":
                milestone["status"] = "BLOCKED"
                if mutation["blocker_code"] not in milestone["blockers"]:
                    milestone["blockers"].append(mutation["blocker_code"])
            elif milestone["status"] == "PLANNED":
                milestone["status"] = "SUPERSEDED"
        for record in state["goal_execution_ledger"].values():
            if record["status"] != "COMPLETE":
                record["status"] = "RETIRED"
                record["completed_roadmap_version"] = base + 1
        state["goal_queue"] = []
        state["active_milestone_id"] = None
        state["roadmap_version"] = base + 1
        state["terminal_status"] = "LOOP_BLOCKED"
        state["finalization_outbox"] = {
            "finalization_id": mutation["finalization_id"],
            "status": "PREPARED",
            "finalized_state_version": after_version,
            "controller_goal_id": mutation["controller_goal_id"],
            "automation_id": mutation["automation_id"],
            "outcome_kind": "BLOCKED",
            "controller_goal_target_status": "BLOCKED",
            "automation_target_status": "PAUSED",
            "blocker_code": mutation["blocker_code"],
            "blocker_fingerprint": mutation["blocker_fingerprint"],
            "blocker_observations": observations,
            "blocker_report_path": blocker_path,
            "blocker_report_digest": mutation["blocker_report_digest"],
        }
        self._finish_route(state, claim, after_version)
        return {
            "code": "STOP_LOOP_APPLIED",
            "next_action_code": "BLOCK_GOAL_AND_PAUSE_HEARTBEAT",
            "result": {
                "terminal_status": "LOOP_BLOCKED",
                "roadmap_version": base + 1,
                "finalization_id": mutation["finalization_id"],
                "controller_goal_id": mutation["controller_goal_id"],
                "controller_goal_target_status": "BLOCKED",
                "automation_id": mutation["automation_id"],
                "automation_target_status": "PAUSED",
                "blocker_code": mutation["blocker_code"],
                "blocker_fingerprint": mutation["blocker_fingerprint"],
                "blocker_observation_turn_ids": [
                    item["goal_turn_id"] for item in observations
                ],
            },
        }

    def _ack_finalization(
        self,
        state: dict[str, Any],
        mutation: dict[str, Any],
        request: dict[str, Any],
        evidence_paths: list[str],
        after_version: int,
    ) -> dict[str, Any]:
        self._observe_time(state, mutation["observed_at"], "/mutation/observed_at")
        outbox = state["finalization_outbox"]
        if outbox is None or outbox["status"] != "PREPARED":
            raise RuntimeRejection("FINALIZATION_NOT_PREPARED", "/finalization_outbox")
        expected = {
            "finalization_id": mutation["finalization_id"],
            "finalized_state_version": mutation["finalized_state_version"],
            "controller_goal_id": mutation["controller_goal_id"],
            "automation_id": mutation["automation_id"],
        }
        if any(outbox[key] != value for key, value in expected.items()):
            raise RuntimeRejection("FINALIZATION_IDENTITY_MISMATCH", "/mutation")
        if (
            mutation["controller_goal_status"]
            != outbox["controller_goal_target_status"]
            or mutation["automation_status"] != outbox["automation_target_status"]
        ):
            raise RuntimeRejection(
                "FINALIZATION_TARGET_STATUS_MISMATCH",
                "/mutation",
            )
        if mutation["finalized_state_version"] >= after_version:
            raise RuntimeRejection(
                "FINALIZATION_VERSION_INVALID",
                "/mutation/finalized_state_version",
            )
        if (
            mutation["controller_goal_observation_path"]
            == mutation["automation_observation_path"]
            or mutation["controller_goal_observation_digest"]
            == mutation["automation_observation_digest"]
        ):
            raise RuntimeRejection(
                "FINALIZATION_OBSERVATIONS_NOT_DISTINCT",
                "/mutation",
            )
        self._require_json_observation_artifact(
            request,
            mutation["controller_goal_observation_path"],
            mutation["controller_goal_observation_digest"],
            {
                "goal_id": mutation["controller_goal_id"],
                "status": mutation["controller_goal_status"],
            },
            "/mutation/controller_goal_observation_digest",
        )
        self._require_json_observation_artifact(
            request,
            mutation["automation_observation_path"],
            mutation["automation_observation_digest"],
            {
                "automation_id": mutation["automation_id"],
                "status": mutation["automation_status"],
            },
            "/mutation/automation_observation_digest",
        )
        receipt = {
            "finalization_id": mutation["finalization_id"],
            "controller_goal_id": mutation["controller_goal_id"],
            "controller_goal_status": mutation["controller_goal_status"],
            "controller_goal_observation_path": mutation[
                "controller_goal_observation_path"
            ],
            "controller_goal_observation_digest": mutation[
                "controller_goal_observation_digest"
            ],
            "automation_id": mutation["automation_id"],
            "automation_status": mutation["automation_status"],
            "automation_observation_path": mutation["automation_observation_path"],
            "automation_observation_digest": mutation[
                "automation_observation_digest"
            ],
            "outcome_kind": outbox["outcome_kind"],
            "blocker_code": outbox["blocker_code"],
            "blocker_fingerprint": outbox["blocker_fingerprint"],
            "blocker_observations": copy.deepcopy(outbox["blocker_observations"]),
            "blocker_report_path": outbox["blocker_report_path"],
            "blocker_report_digest": outbox["blocker_report_digest"],
            "ack_state_version": after_version,
            "evidence_paths": list(evidence_paths),
        }
        state["controller_goal"] = {
            **state["controller_goal"],
            "status": mutation["controller_goal_status"],
        }
        automation_records = [
            record
            for record in state["automation_outbox"].values()
            if record["status"] == "ACKED"
            and isinstance(record.get("result"), dict)
            and record["result"].get("automation_id") == mutation["automation_id"]
        ]
        if len(automation_records) != 1:
            raise RuntimeRejection(
                "FINALIZATION_AUTOMATION_IDENTITY_MISMATCH",
                "/mutation/automation_id",
            )
        automation_records[0]["result"] = {
            **automation_records[0]["result"],
            "status": mutation["automation_status"],
        }
        state["finalization_outbox"] = {**outbox, "status": "ACKED"}
        state["finalization_receipt"] = receipt
        return {
            "code": "FINALIZATION_ACKED",
            "next_action_code": "NONE",
            "result": copy.deepcopy(receipt),
        }


def process_request(
    root: str | os.PathLike[str],
    request: Any,
    *,
    crash_at: str | None = None,
) -> dict[str, Any]:
    """Convenience entry point for callers that do not need a runtime object."""

    return AdaptiveStateRuntime(root, crash_at=crash_at).apply(request)


__all__ = [
    "AdaptiveStateRuntime",
    "CRASH_STAGES",
    "DISPATCH_ENVELOPE_TYPES",
    "InjectedCrash",
    "PAYLOAD_DIGEST_FIELD",
    "PAYLOAD_DIGEST_PLACEHOLDER",
    "PERSISTENT_STAGES",
    "RuntimeRejection",
    "goal_definition_payload_digest",
    "materialize_dispatch_payload",
    "process_request",
    "verify_dispatch_payload",
    "verify_dispatch_payload_against_state",
]
