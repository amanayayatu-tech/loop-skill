"""Single source of truth for exact STAGE_REPORT evidence staging."""

from __future__ import annotations

import copy
import json
from typing import Any


STAGE_REPORT_REQUIRED_KEYS = frozenset({"outbox_id", "result", "report_text"})
STAGE_REPORT_OPTIONAL_KEYS = frozenset(
    {"provided_report_digest", "evidence_sources"}
)
EVIDENCE_SOURCE_REQUIRED_KEYS = frozenset(
    {"path", "source_path", "digest", "media_type"}
)
EVIDENCE_MEDIA_TYPE_SUFFIXES = {
    "application/json": ".json",
    "text/markdown": ".md",
    "text/plain": ".txt",
}
SHA256_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
SAFE_OUTBOX_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
MAX_EVIDENCE_SOURCES = 15


def _digest_schema() -> dict[str, Any]:
    return {"type": "string", "pattern": SHA256_DIGEST_PATTERN}


def _evidence_source_variant(media_type: str, suffix: str) -> dict[str, Any]:
    escaped_suffix = suffix.replace(".", r"\.")
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["path", "source_path", "digest", "media_type"],
        "properties": {
            "path": {
                "type": "string",
                "pattern": rf"^\.codex-loop/reports/[^/\\]+{escaped_suffix}$",
            },
            "source_path": {"type": "string", "pattern": r"^/"},
            "digest": _digest_schema(),
            "media_type": {"const": media_type},
        },
    }


def evidence_source_schema() -> dict[str, Any]:
    """Return the closed evidence source item schema."""

    return {
        "oneOf": [
            _evidence_source_variant(media_type, suffix)
            for media_type, suffix in EVIDENCE_MEDIA_TYPE_SUFFIXES.items()
        ]
    }


def stage_report_request_schema() -> dict[str, Any]:
    """Return a fresh exact-bytes STAGE_REPORT request schema."""

    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["outbox_id", "result", "report_text"],
        "properties": {
            "outbox_id": {
                "type": "string",
                "pattern": SAFE_OUTBOX_ID_PATTERN,
            },
            "result": {
                "type": "object",
                "additionalProperties": False,
                "required": ["status", "artifact_digest"],
                "properties": {
                    "status": {"type": "string", "minLength": 1},
                    "artifact_digest": _digest_schema(),
                    "execution_started": {"type": "boolean"},
                    "blocker_code": {"type": "string", "minLength": 1},
                },
            },
            "report_text": {"type": "string"},
            "provided_report_digest": _digest_schema(),
            "evidence_sources": {
                "type": "array",
                "maxItems": MAX_EVIDENCE_SOURCES,
                "items": evidence_source_schema(),
            },
        },
    }
    return copy.deepcopy(schema)


def stage_report_contract_prompt() -> str:
    """Render the normative, copyable contract used in generated role prompts."""

    example = {
        "outbox_id": "<received_outbox_id>",
        "result": {
            "status": "PASS",
            "artifact_digest": "sha256:<64_lowercase_hex>",
        },
        "report_text": "<exact_strict_JSON_report_text>",
        "evidence_sources": [
            {
                "path": ".codex-loop/reports/<single_level_name>.txt",
                "source_path": "<absolute_registered_target_worktree_file_outside_.codex-loop>",
                "digest": "sha256:<64_lowercase_hex_matching_source_bytes>",
                "media_type": "text/plain",
            }
        ],
    }
    compact_example = json.dumps(
        example,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return (
        "Exact STAGE_REPORT contract: request requires exactly outbox_id, result, "
        "and report_text; only provided_report_digest and evidence_sources are optional. "
        "Each evidence_sources item has exactly path, source_path, digest, and media_type "
        "with no additional keys. path must be a single-level filename under "
        ".codex-loop/reports/ and end in .json for application/json, .md for "
        "text/markdown, or .txt for text/plain. source_path must be an absolute regular "
        "non-symlink file inside the registered target worktree and outside every "
        ".codex-loop path. digest must be sha256: plus 64 lowercase hex characters and "
        "must match the exact source bytes. The report evidence_artifacts entry must use "
        "the same path, digest, and media_type and, when size_bytes is present, the exact "
        "source byte count. "
        f"Copyable minimal PASS example: {compact_example}"
    )


STAGE_REPORT_CONTRACT_PROMPT = stage_report_contract_prompt()
