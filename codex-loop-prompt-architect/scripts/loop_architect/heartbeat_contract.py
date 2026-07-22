"""Canonical rendered-Pack heartbeat extraction and validation."""

from __future__ import annotations

import hashlib


HEARTBEAT_PROMPT_BEGIN = "HEARTBEAT_PROMPT_BEGIN"
HEARTBEAT_PROMPT_END = "HEARTBEAT_PROMPT_END"

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


def validate_gateway_heartbeat_pack(pack: str) -> list[str]:
    """Validate one concrete schema-v3 Gateway heartbeat and its byte identity."""

    try:
        body = extract_heartbeat_prompt_body(pack)
    except (TypeError, ValueError) as exc:
        return [f"gateway_heartbeat_prompt_invalid:{exc}"]
    errors: list[str] = []
    digest = heartbeat_prompt_digest(body)
    if pack.count(f"Canonical Prompt Digest: {digest}") != 1:
        errors.append("gateway_heartbeat_prompt_digest_missing_or_ambiguous")
    for marker in GATEWAY_HEARTBEAT_REQUIRED_MARKERS:
        if marker not in body:
            errors.append(f"gateway_heartbeat_prompt_marker_missing:{marker}")
    for token in GATEWAY_HEARTBEAT_LEGACY_TOKENS:
        if token in body:
            errors.append(f"gateway_heartbeat_prompt_legacy_token:{token}")
    return errors
