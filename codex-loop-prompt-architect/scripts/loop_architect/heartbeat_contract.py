"""Canonical rendered-Pack heartbeat extraction and validation."""

from __future__ import annotations

import hashlib
import re


HEARTBEAT_PROMPT_BEGIN = "HEARTBEAT_PROMPT_BEGIN"
HEARTBEAT_PROMPT_END = "HEARTBEAT_PROMPT_END"
APP_HEARTBEAT_CREATE_CONTRACT_BEGIN = "APP_HEARTBEAT_CREATE_CONTRACT_BEGIN"
APP_HEARTBEAT_CREATE_CONTRACT_END = "APP_HEARTBEAT_CREATE_CONTRACT_END"
APP_GATEWAY_HEARTBEAT_ENUM_BOUNDARY = (
    'Heartbeat enum boundary: App automation_update uses kind="heartbeat" and '
    'destination="thread"; Gateway REGISTER_HEARTBEAT and heartbeat receipts use '
    "kind=HEARTBEAT. Never copy the Gateway enum into the App call."
)
APP_HEARTBEAT_PROMPT_BINDING = (
    "- Pass that exact body string as automation_update.prompt and compute prompt_digest "
    "from the same UTF-8 bytes. Do not trim, append a newline, reserialize, or hash the "
    "delimiters."
)
APP_HEARTBEAT_CREATE_CALL_RE = re.compile(
    r'^automation_update\(mode="create", kind="heartbeat", destination="thread", '
    r'status="ACTIVE", rrule="FREQ=MINUTELY;INTERVAL=([1-9][0-9]*)", '
    r'name=HEARTBEAT_AUTOMATION_NAME, prompt=HEARTBEAT_PROMPT, '
    r'targetThreadId=CONTROLLER_THREAD_ID\)$'
)
PACK_HEARTBEAT_INTERVAL_RE = re.compile(
    r"(?m)^- heartbeat_interval_minutes: ([1-9][0-9]*)$"
)
PACK_HEARTBEAT_NAME_PROMPT_BINDING_RE = re.compile(
    r"(?m)^- HEARTBEAT_AUTOMATION_NAME is the exact string "
    r"`[^`\r\n]+ loop heartbeat ` plus loop_id from canonical state\. "
    r"Its prompt digest is SHA-256 of the exact HEARTBEAT_PROMPT text\.$"
)
CONTROLLER_THREAD_ID_BINDING = "CONTROLLER_THREAD_ID is that real threadId."
APP_HEARTBEAT_CREATE_PREFIX = 'automation_update(mode="create"'

GATEWAY_HEARTBEAT_REQUIRED_MARKERS = (
    "state_gateway",
    "PREPARE_ROUTE",
    "RECORD_ROUTE_SENT",
    "ACK_ROUTE_RESULT",
    "PREPARE_FINALIZATION",
    "ACK_FINALIZATION",
    "FINALIZATION_ACKED",
)

GATEWAY_HEARTBEAT_LEGACY_TOKENS = (
    "State-Writer",
    "state-writer",
    "ACQUIRE_LEASE",
    "RENEW_LEASE",
    "TAKEOVER_LEASE",
    "RELEASE_LEASE",
    "PREPARE_OUTBOX",
    "CANCEL_OUTBOX",
    "MARK_OUTBOX_SENT",
    "ACK_OUTBOX",
    "FINALIZE_LOOP",
    "guessed state",
    "guess the state",
    "infer state from",
)


def normalize_heartbeat_prompt_readback(text: str) -> str:
    """Normalize transport line endings without trimming identity bytes."""

    if not isinstance(text, str):
        raise TypeError("heartbeat prompt must be a string")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def extract_heartbeat_prompt_body(text: str) -> str:
    """Extract the canonical body while excluding delimiter-adjacent newlines."""

    normalized = normalize_heartbeat_prompt_readback(text)
    begin = f"{HEARTBEAT_PROMPT_BEGIN}\n"
    end = f"\n{HEARTBEAT_PROMPT_END}"
    if normalized.count(begin) != 1 or normalized.count(end) != 1:
        raise ValueError("heartbeat prompt delimiters must appear exactly once")
    body = normalized.split(begin, 1)[1].split(end, 1)[0]
    if not body or body.endswith("\n"):
        raise ValueError("heartbeat prompt body must be nonempty and have no trailing newline")
    return body


def heartbeat_prompt_digest(prompt: str) -> str:
    normalized = normalize_heartbeat_prompt_readback(prompt)
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def app_heartbeat_create_call(interval_minutes: int) -> str:
    """Return the exact App call, distinct from Gateway receipt enums."""

    if isinstance(interval_minutes, bool) or not isinstance(interval_minutes, int) or interval_minutes <= 0:
        raise ValueError("heartbeat interval must be a positive integer")
    return (
        'automation_update(mode="create", kind="heartbeat", destination="thread", '
        f'status="ACTIVE", rrule="FREQ=MINUTELY;INTERVAL={interval_minutes}", '
        'name=HEARTBEAT_AUTOMATION_NAME, prompt=HEARTBEAT_PROMPT, '
        'targetThreadId=CONTROLLER_THREAD_ID)'
    )


def app_heartbeat_create_contract(interval_minutes: int) -> str:
    """Render the self-contained App/Gateway heartbeat boundary for a Pack."""

    return (
        f"{APP_HEARTBEAT_CREATE_CONTRACT_BEGIN}\n"
        f"{app_heartbeat_create_call(interval_minutes)}\n"
        f"{APP_HEARTBEAT_CREATE_CONTRACT_END}\n"
        f"{APP_GATEWAY_HEARTBEAT_ENUM_BOUNDARY}"
    )


def extract_app_heartbeat_create_call(pack: str) -> str:
    """Extract exactly one App create call from its closed Pack contract block."""

    normalized = normalize_heartbeat_prompt_readback(pack)
    begin = f"{APP_HEARTBEAT_CREATE_CONTRACT_BEGIN}\n"
    end = f"\n{APP_HEARTBEAT_CREATE_CONTRACT_END}"
    if normalized.count(begin) != 1 or normalized.count(end) != 1:
        raise ValueError("App heartbeat create contract delimiters must appear exactly once")
    call = normalized.split(begin, 1)[1].split(end, 1)[0]
    if "\n" in call or not call:
        raise ValueError("App heartbeat create contract must contain exactly one nonempty line")
    return call


def validate_gateway_heartbeat_pack(pack: str) -> list[str]:
    """Validate one concrete schema-v3 Gateway heartbeat and its byte identity."""

    try:
        body = extract_heartbeat_prompt_body(pack)
    except (TypeError, ValueError) as exc:
        return [f"gateway_heartbeat_prompt_invalid:{exc}"]
    errors: list[str] = []
    normalized_pack = normalize_heartbeat_prompt_readback(pack)
    digest = heartbeat_prompt_digest(body)
    if pack.count(f"Canonical Prompt Digest: {digest}") != 1:
        errors.append("gateway_heartbeat_prompt_digest_missing_or_ambiguous")
    for marker in GATEWAY_HEARTBEAT_REQUIRED_MARKERS:
        if marker not in body:
            errors.append(f"gateway_heartbeat_prompt_marker_missing:{marker}")
    for token in GATEWAY_HEARTBEAT_LEGACY_TOKENS:
        if token in body:
            errors.append(f"gateway_heartbeat_prompt_legacy_token:{token}")
    interval_matches = PACK_HEARTBEAT_INTERVAL_RE.findall(normalized_pack)
    declared_interval = int(interval_matches[0]) if len(interval_matches) == 1 else None
    if declared_interval is None:
        errors.append("gateway_app_heartbeat_interval_declaration_missing_or_ambiguous")
    if normalized_pack.count(CONTROLLER_THREAD_ID_BINDING) != 1:
        errors.append("gateway_app_heartbeat_controller_binding_missing_or_ambiguous")
    if len(PACK_HEARTBEAT_NAME_PROMPT_BINDING_RE.findall(normalized_pack)) != 1:
        errors.append("gateway_app_heartbeat_name_prompt_binding_missing_or_ambiguous")
    if normalized_pack.count(APP_HEARTBEAT_PROMPT_BINDING) != 1:
        errors.append("gateway_app_heartbeat_prompt_binding_missing_or_ambiguous")

    app_create_lines = [
        line for line in normalized_pack.splitlines() if APP_HEARTBEAT_CREATE_PREFIX in line
    ]
    if len(app_create_lines) != 1:
        errors.append("gateway_app_heartbeat_create_call_missing_or_ambiguous")

    try:
        app_call = extract_app_heartbeat_create_call(pack)
    except (TypeError, ValueError) as exc:
        errors.append(f"gateway_app_heartbeat_create_contract_invalid:{exc}")
    else:
        match = APP_HEARTBEAT_CREATE_CALL_RE.fullmatch(app_call)
        if match is None:
            errors.append("gateway_app_heartbeat_create_call_schema_invalid")
        else:
            call_interval = int(match.group(1))
            if app_call != app_heartbeat_create_call(call_interval):
                errors.append("gateway_app_heartbeat_create_call_not_canonical")
            if declared_interval is not None and call_interval != declared_interval:
                errors.append("gateway_app_heartbeat_interval_mismatch")
            if len(app_create_lines) == 1 and app_create_lines[0] != app_call:
                errors.append("gateway_app_heartbeat_create_call_outside_contract")
    if normalized_pack.count(APP_GATEWAY_HEARTBEAT_ENUM_BOUNDARY) != 1:
        errors.append("gateway_app_heartbeat_enum_boundary_missing_or_ambiguous")
    return errors
