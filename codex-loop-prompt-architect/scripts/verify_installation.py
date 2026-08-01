#!/usr/bin/env python3
"""Verify one v4-only installation without reading or changing Codex config."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path


class VerificationError(ValueError):
    pass


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _ignored(relative: Path) -> bool:
    return (
        "__pycache__" in relative.parts
        or relative.suffix == ".pyc"
        or relative.name == ".DS_Store"
    )


def file_inventory(root: Path) -> list[dict[str, object]]:
    if not root.is_dir() or root.is_symlink():
        raise VerificationError("V4_INSTALL_ROOT_INVALID")
    result: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if _ignored(relative):
            continue
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise VerificationError("V4_INSTALL_SYMLINK_FORBIDDEN")
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
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        else:
            raise VerificationError("V4_INSTALL_SPECIAL_FILE_FORBIDDEN")
    return result


def legacy_file_inventory(
    entries: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Keep the v4 doctor projection stable while deletion uses typed entries."""
    return [
        {
            "executable": entry["executable"],
            "path": entry["path"],
            "sha256": entry["sha256"],
        }
        for entry in entries
        if entry["kind"] == "file"
    ]


def verify(
    source: Path,
    installed: Path,
    *,
    version: str,
    repo_commit: str,
    management_uninstaller_sha256: str,
    config_before_sha256: str,
    config_after_sha256: str,
    config_existed: bool,
) -> dict[str, object]:
    source_entries = file_inventory(source)
    installed_entries = file_inventory(installed)
    if source_entries != installed_entries:
        raise VerificationError("V4_SOURCE_INSTALL_DRIFT")
    if config_before_sha256 != config_after_sha256:
        raise VerificationError("V4_CODEX_CONFIG_MUTATED")
    if version != "4.2.0":
        raise VerificationError("V4_VERSION_INVALID")
    if repo_commit != "SOURCE_ARCHIVE" and (
        len(repo_commit) != 40
        or any(character not in "0123456789abcdef" for character in repo_commit)
    ):
        raise VerificationError("V4_SOURCE_COMMIT_INVALID")
    if (
        len(management_uninstaller_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in management_uninstaller_sha256
        )
    ):
        raise VerificationError("V4_MANAGEMENT_UNINSTALLER_DIGEST_INVALID")
    manifest_digest = digest(installed_entries)
    return {
        "artifact": "loopskill4-install-receipt-v1",
        "config_after_sha256": config_after_sha256,
        "config_before_sha256": config_before_sha256,
        "config_existed": config_existed,
        "entries": installed_entries,
        "files": legacy_file_inventory(installed_entries),
        "installed_manifest_digest": manifest_digest,
        "management_uninstaller_sha256": management_uninstaller_sha256,
        "mcp_entries_added": 0,
        "mcp_processes_created": 0,
        "product": "LoopSkill 4",
        "repo_commit": repo_commit,
        "restart_required_by_loopskill": False,
        "source_install_drift": [],
        "source_manifest_digest": manifest_digest,
        "status": "INSTALLED",
        "version": version,
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--installed", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--repo-commit", required=True)
    parser.add_argument("--management-uninstaller-sha256", required=True)
    parser.add_argument("--config-before-sha256", required=True)
    parser.add_argument("--config-after-sha256", required=True)
    parser.add_argument("--config-existed", choices=("0", "1"), required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        receipt = verify(
            args.source,
            args.installed,
            version=args.version,
            repo_commit=args.repo_commit,
            management_uninstaller_sha256=args.management_uninstaller_sha256,
            config_before_sha256=args.config_before_sha256,
            config_after_sha256=args.config_after_sha256,
            config_existed=args.config_existed == "1",
        )
        if args.output.is_symlink() or args.output.exists():
            raise VerificationError("V4_RECEIPT_OUTPUT_CONFLICT")
        if not args.output.parent.is_dir() or args.output.parent.is_symlink():
            raise VerificationError("V4_RECEIPT_OUTPUT_PARENT_INVALID")
        payload = canonical(receipt) + b"\n"
        descriptor = os.open(
            args.output,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short receipt write")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except (OSError, VerificationError) as exc:
        print(json.dumps({"ok": False, "status": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "manifest_digest": receipt["installed_manifest_digest"]}, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
