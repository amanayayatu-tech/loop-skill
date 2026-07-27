"""Typed protocol manifest and canonical encoding for the v4 alpha slice."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping

from .generated_protocol import (
    ASSURANCE_STRENGTHS,
    CAPABILITY_NAMES,
    COMMAND_TYPES,
    DELIVERY_STATES,
    ERROR_CODES,
    EVENT_TYPES,
    MANIFEST_SHA256,
    PROTOCOL_VERSION,
    REFERENCE_KINDS,
    RESULT_STATES,
    SEMANTIC_PAYLOAD_SPECS,
    WRITE_CAS,
    ActorRef,
    ApplyResult,
    AuthorityGrant,
    CapabilityRecord,
    CommandEnvelope,
    EffectAttempt,
    Receipt,
    Reference,
)

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
MAX_COMMAND_BYTES = 16_384
MAX_SEMANTIC_STRING_BYTES = 4_096
MAX_COLLECTION_ITEMS = 128
MAX_RECEIPT_BYTES = 8_192
MAX_EVENTS_PER_COMMAND = 16

PROTOCOL_MANIFEST = {
    "assurance_strengths": ASSURANCE_STRENGTHS,
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


def authority_grant_digest(grant: AuthorityGrant) -> str:
    value = dict(grant.__dict__)
    value.pop("canonical_digest")
    return domain_digest("loopskill-authority-grant-v1\n", value)


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


def validate_command(command: CommandEnvelope) -> None:
    if command.protocol_version != PROTOCOL_VERSION:
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
    if set(command.semantic_payload) != set(payload_spec):
        raise ProtocolRejection("INVALID_COMMAND", "semantic payload shape drift")
    for name, specification in payload_spec.items():
        value = command.semantic_payload[name]
        if specification["type"] == "string" and not isinstance(value, str):
            raise ProtocolRejection("INVALID_COMMAND", f"{name} must be string")
        if "enum" in specification and value not in specification["enum"]:
            raise ProtocolRejection("INVALID_COMMAND", f"{name} enum drift")
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
