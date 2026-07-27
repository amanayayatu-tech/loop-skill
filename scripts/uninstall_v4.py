#!/usr/bin/env python3
"""Transactional removal of one receipt-bound LoopSkill 4 installation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import Callable, Sequence


class UninstallError(ValueError):
    pass


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _config_digest(codex_home: Path) -> str:
    config = codex_home / "config.toml"
    return _sha256(config.read_bytes() if config.is_file() else b"")


def _load_receipt(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UninstallError("V4_UNINSTALL_RECEIPT_INVALID") from exc
    required = {
        "artifact",
        "config_after_sha256",
        "config_before_sha256",
        "files",
        "mcp_entries_added",
        "mcp_processes_created",
        "source_install_drift",
        "version",
    }
    if (
        not isinstance(value, dict)
        or not required <= set(value)
        or value["artifact"] != "loopskill4-install-receipt-v1"
        or value["version"] != "4.0.0"
        or value["source_install_drift"] != []
        or value["mcp_entries_added"] != 0
        or value["mcp_processes_created"] != 0
        or value["config_before_sha256"] != value["config_after_sha256"]
    ):
        raise UninstallError("V4_UNINSTALL_RECEIPT_INVALID")
    return value


def _installed_files(root: Path) -> list[dict[str, object]]:
    if not root.is_dir() or root.is_symlink():
        raise UninstallError("V4_UNINSTALL_INSTALL_ROOT_INVALID")
    result: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or path.suffix == ".pyc" or path.name == ".DS_Store":
            continue
        if path.is_symlink():
            raise UninstallError("V4_UNINSTALL_SYMLINK_FORBIDDEN")
        if path.is_file():
            result.append(
                {
                    "executable": bool(path.stat().st_mode & stat.S_IXUSR),
                    "path": relative.as_posix(),
                    "sha256": _sha256(path.read_bytes()),
                }
            )
    return result


def uninstall(
    codex_home: Path,
    receipt_path: Path,
    *,
    fault: Callable[[str], None] | None = None,
) -> dict[str, object]:
    codex_home = codex_home.resolve()
    receipt_path = receipt_path.resolve()
    if not codex_home.is_dir() or codex_home.is_symlink():
        raise UninstallError("V4_UNINSTALL_CODEX_HOME_INVALID")
    receipt_root = (codex_home / "install-receipts/loopskill4").resolve()
    if receipt_path.parent != receipt_root or receipt_path.suffix != ".json":
        raise UninstallError("V4_UNINSTALL_RECEIPT_OUTSIDE_ROOT")
    receipt = _load_receipt(receipt_path)
    if _config_digest(codex_home) != receipt["config_after_sha256"]:
        raise UninstallError("V4_UNINSTALL_CONFIG_DRIFT")
    target = codex_home / "skills/loopskill4"
    if not target.exists():
        return {
            "config_unchanged": True,
            "loop_store_mutations": 0,
            "mcp_entries_removed": 0,
            "status": "ALREADY_UNINSTALLED",
        }
    if _installed_files(target) != receipt["files"]:
        raise UninstallError("V4_UNINSTALL_INSTALL_DRIFT")

    transaction = codex_home / "uninstall-staging" / f"loopskill4-{receipt_path.stem}"
    if transaction.exists():
        raise UninstallError("V4_UNINSTALL_TRANSACTION_CONFLICT")
    transaction.parent.mkdir(parents=True, exist_ok=True)
    transaction.mkdir()
    withdrawn = transaction / "installed"
    committed = False
    try:
        os.replace(target, withdrawn)
        if fault:
            fault("after_skill_withdrawn")
        if _config_digest(codex_home) != receipt["config_before_sha256"]:
            raise UninstallError("V4_UNINSTALL_CONFIG_DRIFT")
        if fault:
            fault("after_config_verified")
        shutil.rmtree(withdrawn)
        committed = True
        if fault:
            fault("after_commit")
    except Exception:
        if not committed and withdrawn.exists() and not target.exists():
            os.replace(withdrawn, target)
        shutil.rmtree(transaction, ignore_errors=True)
        raise
    shutil.rmtree(transaction)
    return {
        "config_unchanged": True,
        "loop_store_mutations": 0,
        "mcp_entries_removed": 0,
        "status": "UNINSTALLED",
    }


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex-home", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = uninstall(args.codex_home, args.receipt)
    except (OSError, UninstallError) as exc:
        print(json.dumps({"ok": False, "status": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **result}, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
