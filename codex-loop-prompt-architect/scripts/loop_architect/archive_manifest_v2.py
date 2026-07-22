"""Unified, privacy-labelled archive manifest with legacy read support."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "archive-manifest-v2"
DIGEST_RE = re.compile(r"sha256:[a-f0-9]{64}\Z")
PRIVACY_CLASSES = frozenset({"PUBLIC", "INTERNAL", "PRIVATE", "RESTRICTED"})
REQUIRED = frozenset(
    {
        "schema_version", "reason", "root", "git", "state", "events",
        "outboxes", "roles", "heartbeat", "files", "privacy_classification",
    }
)


class ArchiveManifestError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def validate_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != REQUIRED | {"manifest_digest"}:
        raise ArchiveManifestError("ARCHIVE_MANIFEST_FIELDS_INVALID")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ArchiveManifestError("ARCHIVE_MANIFEST_VERSION_INVALID")
    if not isinstance(value.get("reason"), str) or not value["reason"]:
        raise ArchiveManifestError("ARCHIVE_REASON_INVALID")
    if not isinstance(value.get("root"), str) or not value["root"]:
        raise ArchiveManifestError("ARCHIVE_ROOT_INVALID")
    for field in ("git", "state", "heartbeat"):
        if not isinstance(value.get(field), dict):
            raise ArchiveManifestError(f"ARCHIVE_{field.upper()}_INVALID")
    for field in ("events", "outboxes", "roles"):
        if not isinstance(value.get(field), list):
            raise ArchiveManifestError(f"ARCHIVE_{field.upper()}_INVALID")
    files = value.get("files")
    if not isinstance(files, list) or any(
        not isinstance(item, dict)
        or set(item) != {"digest", "path", "privacy_classification", "size"}
        or DIGEST_RE.fullmatch(str(item.get("digest"))) is None
        or not isinstance(item.get("size"), int)
        or isinstance(item.get("size"), bool)
        or item["size"] < 0
        or item.get("privacy_classification") not in PRIVACY_CLASSES
        for item in files
    ):
        raise ArchiveManifestError("ARCHIVE_FILES_INVALID")
    if value.get("privacy_classification") not in PRIVACY_CLASSES:
        raise ArchiveManifestError("ARCHIVE_PRIVACY_CLASS_INVALID")
    body = dict(value)
    claimed = body.pop("manifest_digest")
    expected = "sha256:" + hashlib.sha256(canonical_bytes(body)).hexdigest()
    if claimed != expected:
        raise ArchiveManifestError("ARCHIVE_DIGEST_MISMATCH")
    return value


def build_manifest(
    *, reason: str, root: str, git: Mapping[str, Any], state: Mapping[str, Any],
    events: list[dict[str, Any]], outboxes: list[dict[str, Any]],
    roles: list[dict[str, Any]], heartbeat: Mapping[str, Any],
    files: list[dict[str, Any]], privacy_classification: str = "PRIVATE",
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "events": events, "files": files, "git": dict(git),
        "heartbeat": dict(heartbeat), "outboxes": outboxes,
        "privacy_classification": privacy_classification, "reason": reason,
        "roles": roles, "root": root, "schema_version": SCHEMA_VERSION,
        "state": dict(state),
    }
    value["manifest_digest"] = "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()
    return validate_manifest(value)


def read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArchiveManifestError("ARCHIVE_MANIFEST_UNREADABLE") from exc
    if isinstance(value, dict) and value.get("schema_version") == SCHEMA_VERSION:
        return validate_manifest(value)
    if isinstance(value, dict) and isinstance(value.get("context"), dict):
        return {"legacy_shape": "CONTEXT_WRAPPED", "payload": value}
    if isinstance(value, dict) and "root" in value and "reason" in value:
        return {"legacy_shape": "FLAT", "payload": value}
    raise ArchiveManifestError("ARCHIVE_LEGACY_SHAPE_UNKNOWN")


def write_manifest(path: Path, value: dict[str, Any]) -> None:
    try:
        validate_manifest(value)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = canonical_bytes(value) + b"\n"
        legacy_temporary = path.parent / f".{path.name}.tmp"
        if os.path.lexists(legacy_temporary):
            metadata = os.lstat(legacy_temporary)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise ArchiveManifestError("ARCHIVE_TEMP_INVALID")
            if legacy_temporary.read_bytes() == payload:
                os.replace(legacy_temporary, path)
                _fsync_directory(path.parent)
                return
            legacy_temporary.unlink()
        temporary = path.parent / (
            f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        )
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            try:
                if os.write(descriptor, payload) != len(payload):
                    raise OSError("short archive manifest write")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(temporary, path)
            _fsync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)
    except ArchiveManifestError:
        raise
    except OSError as exc:
        raise ArchiveManifestError("ARCHIVE_MANIFEST_WRITE_FAILED") from exc


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "ArchiveManifestError", "PRIVACY_CLASSES", "SCHEMA_VERSION",
    "build_manifest", "read_manifest", "validate_manifest", "write_manifest",
]
