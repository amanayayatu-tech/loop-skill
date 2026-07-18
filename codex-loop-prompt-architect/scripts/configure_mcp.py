#!/usr/bin/env python3
"""Atomically register the installed Adaptive state MCP server in config.toml."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

try:  # Python 3.11+
    import tomllib  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - selected only on older interpreters
    import tomli as tomllib  # type: ignore[no-redef]


MCP_SERVER_NAME = "codex-loop-state"


class RegistrationError(ValueError):
    pass


def _load_config(payload: bytes) -> dict[str, Any]:
    if not payload:
        return {}
    try:
        result = tomllib.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise RegistrationError(f"MCP_CONFIG_INVALID: {type(exc).__name__}") from exc
    if not isinstance(result, dict):
        raise RegistrationError("MCP_CONFIG_INVALID: root is not a table")
    return result


def _registration(config: Mapping[str, Any], server_name: str) -> Mapping[str, Any] | None:
    servers = config.get("mcp_servers")
    if servers is None:
        return None
    if not isinstance(servers, Mapping):
        raise RegistrationError("MCP_CONFIG_INVALID: mcp_servers is not a table")
    value = servers.get(server_name)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise RegistrationError(f"MCP_CONFIG_INVALID: mcp_servers.{server_name} is not a table")
    return value


def _expected(command: Path, script: Path) -> dict[str, Any]:
    return {"command": str(command), "args": [str(script)]}


def _assert_exact(existing: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    unexpected = sorted(set(existing) - {"command", "args"})
    if unexpected:
        raise RegistrationError("MCP_REGISTRATION_IDENTITY_CONFLICT: " + ",".join(unexpected))
    if existing.get("command") != expected["command"] or existing.get("args") != expected["args"]:
        raise RegistrationError("MCP_REGISTRATION_IDENTITY_CONFLICT")


def _managed_existing_command(existing: Mapping[str, Any], expected: Mapping[str, Any]) -> Path:
    """Return a previous managed runtime only for the same installed bridge.

    The live skill directory is atomically replaced before registration.  A
    prior installer can therefore legitimately leave the same bridge path but
    a different absolute Python runtime.  Preserve that explicit runtime
    choice; never reinterpret a different script or extra execution setting
    as a managed upgrade.
    """
    unexpected = sorted(set(existing) - {"command", "args"})
    if unexpected or existing.get("args") != expected["args"]:
        suffix = (": " + ",".join(unexpected)) if unexpected else ""
        raise RegistrationError("MCP_REGISTRATION_IDENTITY_CONFLICT" + suffix)
    value = existing.get("command")
    if not isinstance(value, str):
        raise RegistrationError("MCP_REGISTRATION_IDENTITY_CONFLICT")
    command = Path(value)
    if not command.is_absolute() or not command.is_file() or not os.access(command, os.X_OK):
        raise RegistrationError("MCP_PYTHON_EXECUTABLE_INVALID")
    try:
        probe = subprocess.run(
            [
                str(command),
                "-c",
                "import jsonschema, yaml; import importlib.util; "
                "assert importlib.util.find_spec('tomllib') or importlib.util.find_spec('tomli'); "
                "print('LOOPSKILL_PYTHON_RUNTIME_OK_V1')",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RegistrationError("MCP_PYTHON_RUNTIME_INVALID") from exc
    if probe.returncode != 0 or probe.stdout != "LOOPSKILL_PYTHON_RUNTIME_OK_V1\n":
        raise RegistrationError("MCP_PYTHON_RUNTIME_INVALID")
    return command


def _toml_string(value: str) -> str:
    # JSON string escaping is valid TOML basic-string escaping for these paths.
    return json.dumps(value, ensure_ascii=True)


def _block(server_name: str, command: Path, script: Path) -> bytes:
    return (
        f"[mcp_servers.{server_name}]\n"
        f"command = {_toml_string(str(command))}\n"
        f"args = [{_toml_string(str(script))}]\n"
    ).encode("utf-8")


def _atomic_replace(path: Path, before: bytes, after: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    current = path.read_bytes() if path.exists() else b""
    if current != before:
        raise RegistrationError("MCP_CONFIG_CHANGED_DURING_INSTALL")
    temporary = path.parent / f".{path.name}.loop-install-{os.getpid()}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(temporary, flags, mode)
    try:
        # os.open applies the process umask even when replacing an existing
        # config. Restore the already-authorized mode before publication so a
        # restrictive CI/App umask cannot silently change user permissions.
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def registration_identity(config_path: Path, command: Path, script: Path, server_name: str = MCP_SERVER_NAME) -> dict[str, Any]:
    payload = config_path.read_bytes() if config_path.exists() else b""
    config = _load_config(payload)
    existing = _registration(config, server_name)
    expected = _expected(command, script)
    if existing is None:
        raise RegistrationError("MCP_REGISTRATION_MISSING")
    _assert_exact(existing, expected)
    if not command.is_absolute() or not script.is_absolute():
        raise RegistrationError("MCP_REGISTRATION_PATH_NOT_ABSOLUTE")
    if not command.is_file() or not os.access(command, os.X_OK):
        raise RegistrationError("MCP_PYTHON_EXECUTABLE_INVALID")
    if not script.is_file() or not os.access(script, os.X_OK):
        raise RegistrationError("MCP_SCRIPT_EXECUTABLE_INVALID")
    script_digest = hashlib.sha256(script.read_bytes()).hexdigest()
    return {
        "server_name": server_name,
        "command": str(command),
        "args": [str(script)],
        "installed_script_path": str(script),
        "installed_script_sha256": script_digest,
        "config_path": str(config_path),
        "config_sha256": hashlib.sha256(payload).hexdigest(),
        "config_readback": True,
    }


def register(
    config_path: Path,
    command: Path,
    script: Path,
    server_name: str = MCP_SERVER_NAME,
    *,
    allow_existing_managed_command: bool = False,
) -> tuple[bool, dict[str, Any]]:
    if not command.is_absolute() or not script.is_absolute():
        raise RegistrationError("MCP_REGISTRATION_PATH_NOT_ABSOLUTE")
    if not command.is_file() or not os.access(command, os.X_OK):
        raise RegistrationError("MCP_PYTHON_EXECUTABLE_INVALID")
    if not script.is_file() or not os.access(script, os.X_OK):
        raise RegistrationError("MCP_SCRIPT_EXECUTABLE_INVALID")
    if config_path.is_symlink():
        raise RegistrationError("MCP_CONFIG_SYMLINK_FORBIDDEN")
    before = config_path.read_bytes() if config_path.exists() else b""
    config = _load_config(before)
    existing = _registration(config, server_name)
    expected = _expected(command, script)
    changed = False
    effective_command = command
    if existing is not None:
        if existing.get("command") != expected["command"] and allow_existing_managed_command:
            effective_command = _managed_existing_command(existing, expected)
        else:
            _assert_exact(existing, expected)
    else:
        separator = b"" if not before or before.endswith(b"\n\n") else (b"\n" if before.endswith(b"\n") else b"\n\n")
        mode = stat.S_IMODE(config_path.stat().st_mode) if config_path.exists() else 0o600
        _atomic_replace(config_path, before, before + separator + _block(server_name, command, script), mode)
        changed = True
    return changed, registration_identity(config_path, effective_command, script, server_name)


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--script", required=True, type=Path)
    parser.add_argument("--server-name", default=MCP_SERVER_NAME)
    parser.add_argument("--allow-existing-managed-command", action="store_true")
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.check:
            identity = registration_identity(args.config, args.python, args.script, args.server_name)
            changed = False
        else:
            changed, identity = register(
                args.config,
                args.python,
                args.script,
                args.server_name,
                allow_existing_managed_command=args.allow_existing_managed_command,
            )
        print(json.dumps({"ok": True, "changed": changed, "registration": identity}, sort_keys=True, separators=(",", ":")))
    except (OSError, RegistrationError) as exc:
        print(json.dumps({"ok": False, "status": str(exc)}, sort_keys=True, separators=(",", ":")), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
