#!/usr/bin/env python3
"""Verify source/install byte identity and emit a schema-checked receipt."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Sequence

import jsonschema

from configure_mcp import RegistrationError, registration_identity


IGNORED_NAMES = {".DS_Store", "__pycache__"}
SHA_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


class InstallVerificationError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _files(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir() or root.is_symlink():
        raise InstallVerificationError(f"INSTALL_ROOT_INVALID: {root}")
    result: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in IGNORED_NAMES for part in relative.parts) or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise InstallVerificationError(f"INSTALL_SYMLINK_FORBIDDEN: {relative.as_posix()}")
        if not path.is_file():
            continue
        result.append(
            {
                "path": relative.as_posix(),
                "sha256": _digest(path.read_bytes()),
                "executable": bool(stat.S_IMODE(path.stat().st_mode) & 0o111),
            }
        )
    if not result:
        raise InstallVerificationError("INSTALL_MANIFEST_EMPTY")
    return result


def build_manifest(
    *,
    source: Path,
    installed: Path,
    config: Path,
    python: Path,
    script: Path,
    schema: Path,
    version: str,
    repo_commit: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    source_files = _files(source)
    installed_files = _files(installed)
    drift: list[str] = []
    source_by_path = {item["path"]: item for item in source_files}
    installed_by_path = {item["path"]: item for item in installed_files}
    for relative in sorted(set(source_by_path) | set(installed_by_path)):
        if source_by_path.get(relative) != installed_by_path.get(relative):
            drift.append(relative)
    if drift:
        raise InstallVerificationError("SOURCE_INSTALL_DRIFT: " + ",".join(drift))
    if repo_commit != "UNVERIFIED_SOURCE" and not SHA_RE.fullmatch(repo_commit):
        raise InstallVerificationError("INSTALL_REPO_COMMIT_INVALID")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise InstallVerificationError("INSTALL_VERSION_INVALID")
    try:
        registration = registration_identity(config, python, script)
    except RegistrationError as exc:
        raise InstallVerificationError(str(exc)) from exc
    now = created_at or dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    body: dict[str, Any] = {
        "schema_version": "install-manifest-v1",
        "skill_name": "codex-loop-prompt-architect",
        "skill_version": version,
        "repo_commit": repo_commit,
        "created_at": now,
        "source_manifest_digest": _digest(_canonical(source_files)),
        "installed_manifest_digest": _digest(_canonical(installed_files)),
        "source_install_drift": [],
        "files": installed_files,
        "mcp_registration": registration,
    }
    body["manifest_digest"] = _digest(_canonical(body))
    schema_value = json.loads(schema.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema_value, format_checker=jsonschema.FormatChecker()).validate(body)
    return body


def validate_manifest(path: Path, schema: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    schema_value = json.loads(schema.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema_value, format_checker=jsonschema.FormatChecker()).validate(value)
    if not isinstance(value, dict):
        raise InstallVerificationError("INSTALL_MANIFEST_INVALID")
    claimed = value.get("manifest_digest")
    body = dict(value)
    body.pop("manifest_digest", None)
    if claimed != _digest(_canonical(body)):
        raise InstallVerificationError("INSTALL_MANIFEST_DIGEST_MISMATCH")
    return value


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp-{os.getpid()}"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(_canonical(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--installed", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--script", type=Path)
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--version")
    parser.add_argument("--repo-commit")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-manifest", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.check_manifest:
            manifest = validate_manifest(args.check_manifest, args.schema)
        else:
            required = (args.source, args.installed, args.config, args.python, args.script, args.version, args.repo_commit, args.output)
            if any(value is None for value in required):
                raise InstallVerificationError("INSTALL_MANIFEST_ARGUMENTS_MISSING")
            manifest = build_manifest(
                source=args.source,
                installed=args.installed,
                config=args.config,
                python=args.python,
                script=args.script,
                schema=args.schema,
                version=args.version,
                repo_commit=args.repo_commit,
            )
            _atomic_write(args.output, manifest)
        print(json.dumps({"ok": True, "manifest_digest": manifest["manifest_digest"]}, sort_keys=True, separators=(",", ":")))
    except (OSError, ValueError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
        print(json.dumps({"ok": False, "status": str(exc)}, sort_keys=True, separators=(",", ":")), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
