"""Append-only, privacy-minimized rejection journal."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


REJECTION_JOURNAL_VERSION = "loop-rejection-v1"
GENESIS_DIGEST = "sha256:" + "0" * 64


class RejectionJournalError(OSError):
    """Raised when the rejection journal cannot be safely extended."""


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def request_digest(request: Any) -> str:
    """Digest a request without persisting request bytes or repr text."""

    try:
        payload = _json_bytes(request)
    except (TypeError, ValueError):
        payload = (type(request).__name__ + ":" + repr(request)).encode(
            "utf-8", errors="backslashreplace"
        )
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _entry_digest(entry: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_json_bytes(entry)).hexdigest()


def _read_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    previous = GENESIS_DIGEST
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.endswith("\n"):
                    raise RejectionJournalError(
                        f"truncated rejection journal line {line_number}"
                    )
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise RejectionJournalError(
                        f"invalid rejection journal line {line_number}"
                    )
                digest = value.pop("entry_digest", None)
                if value.get("previous_entry_digest") != previous:
                    raise RejectionJournalError(
                        f"rejection journal chain mismatch at line {line_number}"
                    )
                expected = _entry_digest(value)
                if digest != expected:
                    raise RejectionJournalError(
                        f"rejection journal digest mismatch at line {line_number}"
                    )
                value["entry_digest"] = digest
                entries.append(value)
                previous = digest
    except (OSError, json.JSONDecodeError) as exc:
        if isinstance(exc, RejectionJournalError):
            raise
        raise RejectionJournalError("rejection journal unreadable") from exc
    return entries


def append_rejection(
    path: Path,
    *,
    state_version: int,
    request: Any,
    error_code: str,
    error_path: str,
    recovery: Mapping[str, Any],
) -> dict[str, Any]:
    """Append and fsync one sanitized rejection entry.

    The caller owns cross-process serialization.  No request body, error
    details, prompt, chat, credential, task id, or thread id is stored.
    """

    if path.parent.is_symlink() or path.is_symlink():
        raise RejectionJournalError("rejection journal symlink is forbidden")
    entries = _read_entries(path)
    previous_entry = entries[-1] if entries else None
    actor = request.get("actor") if isinstance(request, dict) else None
    mutation = request.get("mutation") if isinstance(request, dict) else None
    operation = None
    if isinstance(mutation, dict):
        operation = mutation.get("operation") or mutation.get("type")
    entry: dict[str, Any] = {
        "schema_version": REJECTION_JOURNAL_VERSION,
        "sequence": previous_entry["sequence"] + 1 if previous_entry else 1,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "state_version": state_version,
        "actor_kind": actor if isinstance(actor, str) else "UNKNOWN",
        "operation": operation if isinstance(operation, str) else "UNKNOWN",
        "request_digest": request_digest(request),
        "error_code": error_code,
        "error_path": error_path,
        "side_effects": {
            "canonical": "NONE",
            "product": "NONE",
            "external": "NONE",
            "audit": "REJECTION_JOURNAL_APPEND",
        },
        "recovery_operation": recovery["operation"],
        "previous_entry_digest": (
            previous_entry["entry_digest"] if previous_entry else GENESIS_DIGEST
        ),
    }
    entry["entry_digest"] = _entry_digest(entry)
    line = _json_bytes(entry) + b"\n"
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise RejectionJournalError("rejection journal directory invalid")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        view = memoryview(line)
        offset = 0
        while offset < len(view):
            written = os.write(descriptor, view[offset:])
            if written <= 0:
                raise RejectionJournalError("short rejection journal append")
            offset += written
        os.fsync(descriptor)
    except OSError as exc:
        raise RejectionJournalError("rejection journal append failed") from exc
    finally:
        os.close(descriptor)
    directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return entry


def read_rejections(path: Path) -> list[dict[str, Any]]:
    """Read and validate the complete rejection hash chain."""

    return _read_entries(path)
