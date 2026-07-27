#!/usr/bin/env python3
"""Fail-closed uninstall for an explicitly selected isolated LoopSkill root.

The v4 RC gate invokes this only against a disposable CODEX_HOME.  The
uninstaller consumes the install receipt and the installer's byte-for-byte
backup instead of trying to reverse-edit TOML.  It is not a migration tool and
never touches loop stores.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Callable, Sequence


class UninstallError(ValueError):
    pass


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_receipt(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UninstallError("UNINSTALL_RECEIPT_INVALID") from exc
    if not isinstance(value, dict):
        raise UninstallError("UNINSTALL_RECEIPT_INVALID")
    required = {"files", "mcp_registration", "source_install_drift"}
    if not required <= set(value) or value["source_install_drift"] != []:
        raise UninstallError("UNINSTALL_RECEIPT_INVALID")
    return value


def _installed_files(root: Path) -> list[dict]:
    if not root.is_dir() or root.is_symlink():
        raise UninstallError("UNINSTALL_INSTALL_ROOT_INVALID")
    result = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or path.suffix == ".pyc" or path.name == ".DS_Store":
            continue
        if path.is_symlink():
            raise UninstallError("UNINSTALL_SYMLINK_FORBIDDEN")
        if path.is_file():
            result.append(
                {
                    "path": relative.as_posix(),
                    "sha256": _sha256(path.read_bytes()),
                    "executable": bool(path.stat().st_mode & 0o111),
                }
            )
    return result


def uninstall(
    codex_home: Path,
    receipt_path: Path,
    *,
    fault: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Uninstall one exact receipt, restoring prior bytes on any exception."""

    codex_home = codex_home.resolve()
    receipt_path = receipt_path.resolve()
    if not codex_home.is_dir() or codex_home.is_symlink():
        raise UninstallError("UNINSTALL_CODEX_HOME_INVALID")
    receipt_root = (codex_home / "install-receipts/codex-loop-prompt-architect").resolve()
    if receipt_path.parent != receipt_root or receipt_path.suffix != ".json":
        raise UninstallError("UNINSTALL_RECEIPT_OUTSIDE_ROOT")
    receipt = _load_receipt(receipt_path)
    stamp = receipt_path.stem
    target = codex_home / "skills/codex-loop-prompt-architect"
    config = codex_home / "config.toml"
    backup = codex_home / "skill-backups/codex-loop-prompt-architect" / stamp
    prior_skill = backup / "skill"
    prior_config = backup / "config.toml.before"
    prior_absent = backup / "config.toml.absent"
    if not backup.is_dir() or (prior_config.exists() == prior_absent.exists()):
        raise UninstallError("UNINSTALL_BACKUP_INVALID")
    if _installed_files(target) != receipt["files"]:
        raise UninstallError("UNINSTALL_INSTALL_DRIFT")
    registration = receipt["mcp_registration"]
    if not isinstance(registration, dict) or not isinstance(registration.get("config_sha256"), str):
        raise UninstallError("UNINSTALL_RECEIPT_INVALID")
    config_payload = config.read_bytes() if config.exists() else b""
    if _sha256(config_payload) != registration["config_sha256"]:
        raise UninstallError("UNINSTALL_CONFIG_DRIFT")

    transaction = codex_home / "uninstall-staging" / stamp
    if transaction.exists():
        raise UninstallError("UNINSTALL_TRANSACTION_CONFLICT")
    transaction.mkdir(parents=True)
    removed_skill = transaction / "installed-skill"
    live_config = transaction / "installed-config.toml"
    restored_prior_skill = False
    restored_prior_config = False
    try:
        os.replace(target, removed_skill)
        if fault:
            fault("after_skill_withdrawn")
        if config.exists():
            os.replace(config, live_config)
        if prior_config.exists():
            shutil.copy2(prior_config, config)
            restored_prior_config = True
        if fault:
            fault("after_config_restored")
        if prior_skill.exists():
            os.replace(prior_skill, target)
            restored_prior_skill = True
        if fault:
            fault("after_prior_skill_restored")
    except Exception:
        if restored_prior_skill and target.exists() and not prior_skill.exists():
            os.replace(target, prior_skill)
        if restored_prior_config and config.exists():
            config.unlink()
        if live_config.exists():
            os.replace(live_config, config)
        if removed_skill.exists() and not target.exists():
            os.replace(removed_skill, target)
        shutil.rmtree(transaction, ignore_errors=True)
        raise

    shutil.rmtree(transaction)
    return {
        "status": "UNINSTALLED",
        "receipt": receipt_path.name,
        "prior_skill_restored": restored_prior_skill,
        "prior_config_restored": restored_prior_config,
        "loop_store_mutations": 0,
        "public_release_effects": 0,
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
