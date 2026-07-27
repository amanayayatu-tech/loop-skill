"""Typed protocol manifest and canonical encoding for the v4 alpha slice."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping


PROTOCOL_VERSION = "4.0-draft.2"
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
MAX_COMMAND_BYTES = 16_384
MAX_SEMANTIC_STRING_BYTES = 4_096
MAX_COLLECTION_ITEMS = 128
MAX_RECEIPT_BYTES = 8_192
MAX_EVENTS_PER_COMMAND = 16

COMMAND_TYPES = (
    "CreateLoop",
    "BindHostResource",
    "PrepareRoute",
    "BeginEffectDelivery",
    "RecordEffectObservation",
    "StageResult",
    "AcknowledgeResult",
    "RecordReview",
    "AdvanceGoal",
    "PrepareFinalization",
    "CloseExecution",
)

EVENT_TYPES = (
    "LoopCreated",
    "GoalRegistered",
    "GoalActivated",
    "HostResourceBound",
    "RoutePrepared",
    "DeliveryAttemptCommitted",
    "DeliveryObserved",
    "DeliveryUnknown",
    "DeliveryUnverifiable",
    "LateDeliveryObserved",
    "ResultStaged",
    "ReportStaged",
    "ArtifactCaptured",
    "ArtifactVerified",
    "ReportAccepted",
    "ResultAcknowledged",
    "ReviewRecorded",
    "GoalAdvanced",
    "FinalizationPrepared",
    "ExecutionFinalized",
    "StrictFinalizationAcknowledged",
)

REFERENCE_KINDS = (
    "LoopRef",
    "ActorRef",
    "AuthorityGrantRef",
    "GoalRef",
    "HostResourceRef",
    "RouteRef",
    "DeliveryRef",
    "AttemptRef",
    "ResultRef",
    "ReportRef",
    "ArtifactRef",
    "ReviewRef",
    "FinalizationRef",
    "ReceiptRef",
)

ERROR_CODES = (
    "INVALID_COMMAND",
    "UNSUPPORTED_PROTOCOL_VERSION",
    "RESOURCE_LIMIT_EXCEEDED",
    "INVALID_UTF8",
    "CONTROL_FIELD_INJECTION",
    "INVALID_AUTHORITY",
    "AUTHORITY_EXPIRED",
    "AUTHORITY_SCOPE_MISMATCH",
    "STALE_LOOP_REVISION",
    "STALE_SUBJECT_REVISION",
    "IDEMPOTENCY_CONFLICT",
    "FOREIGN_REFERENCE",
    "WRONG_REFERENCE_KIND",
    "INVALID_TRANSITION",
    "CAPABILITY_UNAVAILABLE",
    "CAPABILITY_UNVERIFIABLE",
    "RECEIPT_REQUIRED",
    "RECEIPT_ISSUER_UNTRUSTED",
    "RECEIPT_EXPIRED",
    "RECEIPT_IDENTITY_MISMATCH",
    "ATTEMPT_ALREADY_CONSUMED",
    "FINALIZATION_PRECONDITION_FAILED",
    "INTERNAL_INVARIANT_VIOLATION",
)

PROTOCOL_MANIFEST = {
    "protocol_version": PROTOCOL_VERSION,
    "commands": COMMAND_TYPES,
    "events": EVENT_TYPES,
    "reference_kinds": REFERENCE_KINDS,
    "errors": ERROR_CODES,
    "delivery_states": (
        "PREPARED",
        "ATTEMPT_COMMITTED",
        "OBSERVED",
        "UNKNOWN",
        "UNVERIFIABLE",
    ),
    "result_states": ("STAGED", "ACKNOWLEDGED", "STALE"),
    "assurance_strengths": ("NONE", "LOCAL", "COOPERATIVE", "STRICT"),
    "write_cas": "per_loop_revision",
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


def raw_domain_digest(domain: str, raw: bytes) -> str:
    return hashlib.sha256(domain.encode("utf-8") + raw).hexdigest()


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


@dataclass(frozen=True)
class CommandEnvelope:
    operation_id: str
    command_type: str
    protocol_version: str
    actor_ref: str
    authority_grant_ref: str
    subject: Mapping[str, Any]
    expected_loop_revision: int
    expected_subject_revisions: Mapping[str, int]
    issued_at: str
    machine_bindings: Mapping[str, Mapping[str, str]]
    semantic_payload: Mapping[str, Any]
    request_digest: str

    def without_digest(self) -> dict[str, Any]:
        return {
            "actor_ref": self.actor_ref,
            "authority_grant_ref": self.authority_grant_ref,
            "command_type": self.command_type,
            "expected_loop_revision": self.expected_loop_revision,
            "expected_subject_revisions": dict(self.expected_subject_revisions),
            "issued_at": self.issued_at,
            "machine_bindings": {
                key: dict(value) for key, value in self.machine_bindings.items()
            },
            "operation_id": self.operation_id,
            "protocol_version": self.protocol_version,
            "semantic_payload": dict(self.semantic_payload),
            "subject": dict(self.subject),
        }

    def calculated_digest(self) -> str:
        return domain_digest("loopskill-command-v1\n", self.without_digest())

    def validate_shape(self) -> None:
        if self.protocol_version != PROTOCOL_VERSION:
            raise ProtocolRejection(
                "UNSUPPORTED_PROTOCOL_VERSION", self.protocol_version
            )
        if self.command_type not in COMMAND_TYPES:
            raise ProtocolRejection("INVALID_COMMAND", "unknown command_type")
        if not self.operation_id or len(self.operation_id.encode("utf-8")) > 128:
            raise ProtocolRejection("INVALID_COMMAND", "invalid operation_id")
        if set(self.machine_bindings) != {
            "resolved_refs",
            "allocate_refs",
            "receipt_refs",
        }:
            raise ProtocolRejection("INVALID_COMMAND", "machine_bindings is not closed")
        injection = _find_control_injection(self.semantic_payload)
        if injection:
            raise ProtocolRejection("CONTROL_FIELD_INJECTION", injection)
        raw = canonical_bytes(self.without_digest())
        if len(raw) > MAX_COMMAND_BYTES:
            raise ProtocolRejection(
                "RESOURCE_LIMIT_EXCEEDED", "command exceeds byte limit"
            )
        if self.request_digest != self.calculated_digest():
            raise ProtocolRejection("INVALID_COMMAND", "request digest mismatch")


@dataclass(frozen=True)
class ActorRef:
    actor_ref: str
    loop_namespace: str
    actor_kind: str
    identity_digest: str
    issuer_ref: str
    issuer_trust: str


@dataclass(frozen=True)
class AuthorityGrant:
    grant_ref: str
    actor_ref: str
    issuer_actor_ref: str
    issuer_trust: str
    allowed_commands: tuple[str, ...]
    loop_scope: str
    subject_kinds: tuple[str, ...]
    exact_subjects: tuple[str, ...]
    not_before: str
    expires_at: str
    nonce: str
    canonical_digest: str

    def calculated_digest(self) -> str:
        value = dict(self.__dict__)
        value.pop("canonical_digest")
        return domain_digest("loopskill-authority-grant-v1\n", value)


@dataclass(frozen=True)
class Receipt:
    receipt_ref: str
    issuer_ref: str
    issuer_trust: str
    trust_class: str
    action: str
    loop_ref: str
    subject_ref: str
    attempt_ref: str | None
    target_ref: str | None
    request_digest: str | None
    provider_idempotency_key: str | None
    outcome: str
    issued_at: str
    expires_at: str
    evidence_digest: str

    def validate_size(self) -> None:
        if len(canonical_bytes(self.__dict__)) > MAX_RECEIPT_BYTES:
            raise ProtocolRejection(
                "RESOURCE_LIMIT_EXCEEDED", "receipt exceeds byte limit"
            )


@dataclass(frozen=True)
class ApplyResult:
    operation_id: str
    loop_ref: str
    loop_revision: int
    event_types: tuple[str, ...]
    response: Mapping[str, Any]
    snapshot_digest: str
    replayed: bool = False


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
) -> CommandEnvelope:
    provisional = CommandEnvelope(
        operation_id=operation_id,
        command_type=command_type,
        protocol_version=PROTOCOL_VERSION,
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
            "request_digest": provisional.calculated_digest(),
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
    values["request_digest"] = provisional.calculated_digest()
    return CommandEnvelope(**values)
