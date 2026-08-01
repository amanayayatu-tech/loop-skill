#!/usr/bin/env python3
"""Transactional removal of one receipt-bound LoopSkill 4 installation."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import Callable, Iterator, Sequence


class UninstallError(ValueError):
    pass


ACTIVE_RECEIPT_POINTER = "active-receipt"
MANAGEMENT_UNINSTALLER = "uninstall_v4.py"
LOCK_FD_ENV = "LOOPSKILL4_MANAGEMENT_LOCK_FD"
ACTIVE_TRANSACTION = "active-transaction.json"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _reject_symlink_components(path: Path, error: str) -> None:
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        cursor /= part
        if not _lexists(cursor):
            break
        try:
            if stat.S_ISLNK(cursor.lstat().st_mode):
                raise UninstallError(error)
        except OSError as exc:
            raise UninstallError(error) from exc


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextlib.contextmanager
def _management_lock(codex_home: Path) -> Iterator[None]:
    if not codex_home.is_absolute() or ".." in codex_home.parts:
        raise UninstallError("V4_UNINSTALL_CODEX_HOME_INVALID")
    _reject_symlink_components(codex_home.parent, "V4_UNINSTALL_CODEX_HOME_INVALID")
    try:
        parent_metadata = codex_home.parent.lstat()
    except OSError as exc:
        raise UninstallError("V4_UNINSTALL_CODEX_HOME_INVALID") from exc
    if (
        not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != os.getuid()
        or parent_metadata.st_mode & 0o022
    ):
        raise UninstallError("V4_UNINSTALL_CODEX_HOME_INVALID")

    inherited = os.environ.get(LOCK_FD_ENV)
    close_descriptor = inherited is None
    if inherited is None:
        descriptor = os.open(
            codex_home.parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    else:
        try:
            descriptor = int(inherited)
            descriptor_metadata = os.fstat(descriptor)
        except (OSError, ValueError) as exc:
            raise UninstallError("V4_UNINSTALL_LOCK_INVALID") from exc
        if (
            not stat.S_ISDIR(descriptor_metadata.st_mode)
            or (
                descriptor_metadata.st_dev,
                descriptor_metadata.st_ino,
            )
            != (parent_metadata.st_dev, parent_metadata.st_ino)
        ):
            raise UninstallError("V4_UNINSTALL_LOCK_INVALID")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        if close_descriptor:
            os.close(descriptor)


def _secure_home(path: Path) -> Path:
    if not path.is_absolute() or ".." in path.parts or path == Path(path.anchor):
        raise UninstallError("V4_UNINSTALL_CODEX_HOME_INVALID")
    _reject_symlink_components(path, "V4_UNINSTALL_CODEX_HOME_INVALID")
    try:
        parent_metadata = path.parent.lstat()
        metadata = path.lstat()
    except OSError as exc:
        raise UninstallError("V4_UNINSTALL_CODEX_HOME_INVALID") from exc
    if (
        stat.S_ISLNK(parent_metadata.st_mode)
        or not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != os.getuid()
        or parent_metadata.st_mode & 0o022
        or stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o022
    ):
        raise UninstallError("V4_UNINSTALL_CODEX_HOME_INVALID")
    return path.resolve(strict=True)


def _secure_owned_dir(path: Path, codex_home: Path, error: str) -> Path:
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
        resolved.relative_to(codex_home)
    except (OSError, ValueError) as exc:
        raise UninstallError(error) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o022
    ):
        raise UninstallError(error)
    return resolved


def _secure_regular_file(path: Path, parent: Path, error: str) -> Path:
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise UninstallError(error) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o022
        or resolved.parent != parent
    ):
        raise UninstallError(error)
    return resolved


def _owned_layout(codex_home: Path) -> tuple[Path, Path, Path, Path]:
    home = _secure_home(codex_home)
    skills = _secure_owned_dir(home / "skills", home, "V4_UNINSTALL_SKILLS_ROOT_INVALID")
    _secure_owned_dir(
        home / "install-staging", home, "V4_UNINSTALL_INSTALL_STAGING_INVALID"
    )
    receipt_parent = _secure_owned_dir(
        home / "install-receipts", home, "V4_UNINSTALL_RECEIPT_ROOT_INVALID"
    )
    receipt_root = _secure_owned_dir(
        receipt_parent / "loopskill4", home, "V4_UNINSTALL_RECEIPT_ROOT_INVALID"
    )
    uninstall_staging = _secure_owned_dir(
        home / "uninstall-staging", home, "V4_UNINSTALL_STAGING_INVALID"
    )
    return home, skills, receipt_root, uninstall_staging


def _config_state(codex_home: Path) -> tuple[bool, str]:
    config = codex_home / "config.toml"
    if not _lexists(config):
        return False, _sha256(b"")
    try:
        metadata = config.lstat()
    except OSError as exc:
        raise UninstallError("V4_UNINSTALL_CONFIG_INVALID") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise UninstallError("V4_UNINSTALL_CONFIG_INVALID")
    return True, _sha256(config.read_bytes())


def _load_receipt(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UninstallError("V4_UNINSTALL_RECEIPT_INVALID") from exc
    required = {
        "artifact",
        "config_after_sha256",
        "config_before_sha256",
        "config_existed",
        "entries",
        "files",
        "management_uninstaller_sha256",
        "mcp_entries_added",
        "mcp_processes_created",
        "source_install_drift",
        "version",
    }
    if (
        not isinstance(value, dict)
        or not required <= set(value)
        or value["artifact"] != "loopskill4-install-receipt-v1"
        or value["version"] not in {"4.0.0", "4.1.0", "4.1.1", "4.2.0"}
        or value["source_install_drift"] != []
        or value["mcp_entries_added"] != 0
        or value["mcp_processes_created"] != 0
        or value["config_before_sha256"] != value["config_after_sha256"]
        or not isinstance(value["config_existed"], bool)
        or not isinstance(value["management_uninstaller_sha256"], str)
        or len(value["management_uninstaller_sha256"]) != 64
        or any(
            character not in "0123456789abcdef"
            for character in value["management_uninstaller_sha256"]
        )
    ):
        raise UninstallError("V4_UNINSTALL_RECEIPT_INVALID")
    return value


def _active_receipt(receipt_root: Path) -> Path:
    pointer_path = receipt_root / ACTIVE_RECEIPT_POINTER
    try:
        pointer = _secure_regular_file(
            pointer_path, receipt_root, "V4_UNINSTALL_ACTIVE_RECEIPT_INVALID"
        )
        value = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, UninstallError) as exc:
        raise UninstallError("V4_UNINSTALL_ACTIVE_RECEIPT_INVALID") from exc
    if not isinstance(value, dict) or set(value) != {"receipt", "sha256"}:
        raise UninstallError("V4_UNINSTALL_ACTIVE_RECEIPT_INVALID")
    name = value.get("receipt")
    digest = value.get("sha256")
    if (
        not isinstance(name, str)
        or Path(name).name != name
        or not name.endswith(".json")
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise UninstallError("V4_UNINSTALL_ACTIVE_RECEIPT_INVALID")
    receipt_path = receipt_root / name
    try:
        receipt = _secure_regular_file(
            receipt_path, receipt_root, "V4_UNINSTALL_ACTIVE_RECEIPT_INVALID"
        )
        if _sha256(receipt.read_bytes()) != digest:
            raise OSError("active receipt drift")
    except (OSError, UninstallError) as exc:
        raise UninstallError("V4_UNINSTALL_ACTIVE_RECEIPT_INVALID") from exc
    return receipt


def _ignored(relative: Path) -> bool:
    return (
        "__pycache__" in relative.parts
        or relative.suffix == ".pyc"
        or relative.name == ".DS_Store"
    )


def _installed_inventory(root: Path) -> list[dict[str, object]]:
    try:
        root_metadata = root.lstat()
    except OSError as exc:
        raise UninstallError("V4_UNINSTALL_INSTALL_ROOT_INVALID") from exc
    if (
        stat.S_ISLNK(root_metadata.st_mode)
        or not stat.S_ISDIR(root_metadata.st_mode)
        or root_metadata.st_uid != os.getuid()
        or root_metadata.st_mode & 0o022
    ):
        raise UninstallError("V4_UNINSTALL_INSTALL_ROOT_INVALID")
    result: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if _ignored(relative):
            continue
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise UninstallError("V4_UNINSTALL_SYMLINK_FORBIDDEN")
        if metadata.st_uid != os.getuid() or metadata.st_mode & 0o022:
            raise UninstallError("V4_UNINSTALL_INSTALL_ROOT_INVALID")
        if stat.S_ISDIR(metadata.st_mode):
            result.append(
                {
                    "kind": "directory",
                    "path": relative.as_posix(),
                }
            )
        elif stat.S_ISREG(metadata.st_mode):
            result.append(
                {
                    "executable": bool(metadata.st_mode & stat.S_IXUSR),
                    "kind": "file",
                    "path": relative.as_posix(),
                    "sha256": _sha256(path.read_bytes()),
                }
            )
        else:
            raise UninstallError("V4_UNINSTALL_SPECIAL_FILE_FORBIDDEN")
    return result


def _atomic_json(path: Path, value: object) -> None:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short journal write")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def validate_managed_install(
    codex_home: Path,
    receipt_path: Path | None = None,
) -> tuple[Path, dict, Path, bool]:
    codex_home, skills_root, receipt_root, _uninstall_staging = _owned_layout(
        codex_home
    )
    active_receipt = _active_receipt(receipt_root)
    if receipt_path is not None:
        if not receipt_path.is_absolute() or ".." in receipt_path.parts:
            raise UninstallError("V4_UNINSTALL_RECEIPT_OUTSIDE_ROOT")
        try:
            resolved_receipt = receipt_path.resolve(strict=True)
        except OSError as exc:
            raise UninstallError("V4_UNINSTALL_RECEIPT_INVALID") from exc
        if resolved_receipt.parent != receipt_root or resolved_receipt.suffix != ".json":
            raise UninstallError("V4_UNINSTALL_RECEIPT_OUTSIDE_ROOT")
        receipt_path = _secure_regular_file(
            receipt_path, receipt_root, "V4_UNINSTALL_RECEIPT_INVALID"
        )
        if receipt_path != active_receipt:
            raise UninstallError("V4_UNINSTALL_RECEIPT_NOT_ACTIVE")
    else:
        receipt_path = active_receipt
    if receipt_path.parent != receipt_root or receipt_path.suffix != ".json":
        raise UninstallError("V4_UNINSTALL_RECEIPT_OUTSIDE_ROOT")
    receipt = _load_receipt(receipt_path)
    manager = _secure_regular_file(
        receipt_root / MANAGEMENT_UNINSTALLER,
        receipt_root,
        "V4_UNINSTALL_MANAGEMENT_ENTRY_INVALID",
    )
    if (
        not (manager.stat().st_mode & stat.S_IXUSR)
        or _sha256(manager.read_bytes()) != receipt["management_uninstaller_sha256"]
    ):
        raise UninstallError("V4_UNINSTALL_MANAGEMENT_ENTRY_INVALID")
    _config_state(codex_home)
    target = skills_root / "loopskill4"
    if not _lexists(target):
        return receipt_path, receipt, target, False
    if _installed_inventory(target) != receipt["entries"]:
        raise UninstallError("V4_UNINSTALL_INSTALL_DRIFT")
    return receipt_path, receipt, target, True


def _load_uninstall_journal(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UninstallError("V4_UNINSTALL_JOURNAL_INVALID") from exc
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "artifact",
            "config_before_sha256",
            "config_existed",
            "kind",
            "receipt",
            "receipt_sha256",
            "transaction",
        }
        or value["artifact"] != "loopskill4-distribution-transaction-v1"
        or value["kind"] != "UNINSTALL"
        or not isinstance(value["config_existed"], bool)
        or not isinstance(value["config_before_sha256"], str)
        or len(value["config_before_sha256"]) != 64
        or not isinstance(value["receipt"], str)
        or Path(value["receipt"]).name != value["receipt"]
        or not str(value["receipt"]).endswith(".json")
        or not isinstance(value["receipt_sha256"], str)
        or len(value["receipt_sha256"]) != 64
        or not isinstance(value["transaction"], str)
        or Path(value["transaction"]).name != value["transaction"]
        or not str(value["transaction"]).startswith("loopskill4-")
    ):
        raise UninstallError("V4_UNINSTALL_JOURNAL_INVALID")
    return value


def _recover_uninstall_transaction(
    codex_home: Path,
    receipt_root: Path,
    uninstall_staging: Path,
) -> int:
    journal_path = receipt_root / ACTIVE_TRANSACTION
    transactions = sorted(
        path
        for path in uninstall_staging.iterdir()
        if path.name.startswith("loopskill4-")
    )
    if not _lexists(journal_path):
        if transactions:
            raise UninstallError("V4_UNINSTALL_JOURNAL_MISSING")
        return 0
    _secure_regular_file(
        journal_path, receipt_root, "V4_UNINSTALL_JOURNAL_INVALID"
    )
    try:
        raw = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UninstallError("V4_UNINSTALL_JOURNAL_INVALID") from exc
    if not isinstance(raw, dict) or raw.get("kind") != "UNINSTALL":
        raise UninstallError("V4_UNINSTALL_OTHER_TRANSACTION_ACTIVE")
    journal = _load_uninstall_journal(journal_path)
    active = _active_receipt(receipt_root)
    if (
        journal["receipt"] != active.name
        or journal["receipt_sha256"] != _sha256(active.read_bytes())
    ):
        raise UninstallError("V4_UNINSTALL_JOURNAL_RECEIPT_MISMATCH")

    target = codex_home / "skills/loopskill4"
    transaction = uninstall_staging / str(journal["transaction"])
    if transactions not in ([], [transaction]):
        raise UninstallError("V4_UNINSTALL_TRANSACTION_AMBIGUOUS")
    if _lexists(transaction):
        metadata = transaction.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o022
            or transaction.resolve(strict=True).parent != uninstall_staging
        ):
            raise UninstallError("V4_UNINSTALL_TRANSACTION_INVALID")

    withdrawn = transaction / "installed"
    target_exists = _lexists(target)
    withdrawn_exists = _lexists(withdrawn)
    if target_exists and withdrawn_exists:
        raise UninstallError("V4_UNINSTALL_TRANSACTION_AMBIGUOUS")
    if withdrawn_exists:
        withdrawn_metadata = withdrawn.lstat()
        if (
            stat.S_ISLNK(withdrawn_metadata.st_mode)
            or not stat.S_ISDIR(withdrawn_metadata.st_mode)
            or withdrawn.resolve(strict=True).parent != transaction
        ):
            raise UninstallError("V4_UNINSTALL_TRANSACTION_INVALID")

    if target_exists:
        # No rename occurred: exact pre-state remains authoritative.
        if _lexists(transaction):
            if any(transaction.iterdir()):
                raise UninstallError("V4_UNINSTALL_TRANSACTION_AMBIGUOUS")
            transaction.rmdir()
        journal_path.unlink()
        _fsync_directory(receipt_root)
        _fsync_directory(uninstall_staging)
        return 1

    # Target absence proves the atomic rename committed. Deletion is retryable GC.
    if withdrawn_exists:
        try:
            shutil.rmtree(withdrawn)
        except OSError as exc:
            raise UninstallError("V4_UNINSTALL_GC_PENDING") from exc
    if _lexists(transaction):
        if any(transaction.iterdir()):
            raise UninstallError("V4_UNINSTALL_TRANSACTION_AMBIGUOUS")
        transaction.rmdir()
    journal_path.unlink()
    _fsync_directory(receipt_root)
    _fsync_directory(uninstall_staging)
    return 1


def uninstall(
    codex_home: Path,
    receipt_path: Path | None = None,
    *,
    fault: Callable[[str], None] | None = None,
) -> dict[str, object]:
    with _management_lock(codex_home):
        codex_home, _skills, receipt_root, uninstall_staging = _owned_layout(
            codex_home
        )
        _recover_uninstall_transaction(codex_home, receipt_root, uninstall_staging)
        receipt_path, _receipt, target, installed = validate_managed_install(
            codex_home, receipt_path
        )
        if not installed:
            return {
                "config_unchanged": True,
                "loop_store_mutations": 0,
                "mcp_entries_removed": 0,
                "status": "ALREADY_UNINSTALLED",
            }

        config_existed, config_digest = _config_state(codex_home)
        transaction_name = f"loopskill4-{receipt_path.stem}"
        transaction = uninstall_staging / transaction_name
        if _lexists(transaction):
            raise UninstallError("V4_UNINSTALL_TRANSACTION_CONFLICT")
        journal_path = receipt_root / ACTIVE_TRANSACTION
        if _lexists(journal_path):
            raise UninstallError("V4_UNINSTALL_TRANSACTION_CONFLICT")
        _atomic_json(
            journal_path,
            {
                "artifact": "loopskill4-distribution-transaction-v1",
                "config_before_sha256": config_digest,
                "config_existed": config_existed,
                "kind": "UNINSTALL",
                "receipt": receipt_path.name,
                "receipt_sha256": _sha256(receipt_path.read_bytes()),
                "transaction": transaction_name,
            },
        )
        transaction.mkdir(mode=0o700)
        _fsync_directory(uninstall_staging)
        withdrawn = transaction / "installed"
        committed = False
        try:
            if fault:
                fault("before_skill_withdrawn")
            os.replace(target, withdrawn)
            committed = True
            _fsync_directory(target.parent)
            _fsync_directory(transaction)
            if fault:
                fault("after_skill_withdrawn")
            if _config_state(codex_home) != (config_existed, config_digest):
                raise UninstallError("V4_UNINSTALL_CONFIG_CHANGED_DURING_OPERATION")
            if fault:
                fault("after_config_verified")
            try:
                shutil.rmtree(withdrawn)
            except OSError as exc:
                raise UninstallError("V4_UNINSTALL_GC_PENDING") from exc
            if fault:
                fault("after_commit")
            if _config_state(codex_home) != (config_existed, config_digest):
                raise UninstallError("V4_UNINSTALL_CONFIG_CHANGED_DURING_OPERATION")
        except Exception:
            if not committed:
                if _lexists(transaction):
                    if any(transaction.iterdir()):
                        raise UninstallError(
                            "V4_UNINSTALL_TRANSACTION_AMBIGUOUS"
                        )
                    transaction.rmdir()
                journal_path.unlink()
                _fsync_directory(receipt_root)
                _fsync_directory(uninstall_staging)
            # After rename the absence of target is the committed state. Recovery
            # only completes GC and never restores a partly deleted tree.
            raise
        transaction.rmdir()
        journal_path.unlink()
        _fsync_directory(receipt_root)
        _fsync_directory(uninstall_staging)
        return {
            "config_unchanged": True,
            "loop_store_mutations": 0,
            "mcp_entries_removed": 0,
            "status": "UNINSTALLED",
        }


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex-home", required=True, type=Path)
    parser.add_argument(
        "--receipt",
        type=Path,
        help="check-only diagnostic selector; mutation always resolves the active receipt",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the machine-bound installation without removing it",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.receipt is not None and not args.check:
            raise UninstallError("V4_UNINSTALL_RECEIPT_OVERRIDE_CHECK_ONLY")
        if args.check:
            with _management_lock(args.codex_home):
                codex_home, _skills, receipt_root, uninstall_staging = _owned_layout(
                    args.codex_home
                )
                _recover_uninstall_transaction(
                    codex_home, receipt_root, uninstall_staging
                )
                _receipt, _value, _target, installed = validate_managed_install(
                    codex_home, args.receipt
                )
            result = {
                "config_unchanged": True,
                "loop_store_mutations": 0,
                "mcp_entries_removed": 0,
                "status": "READY" if installed else "ALREADY_UNINSTALLED",
            }
        else:
            result = uninstall(args.codex_home, args.receipt)
    except (OSError, UninstallError) as exc:
        print(json.dumps({"ok": False, "status": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **result}, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
