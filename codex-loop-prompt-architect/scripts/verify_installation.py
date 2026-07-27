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


def file_inventory(root: Path) -> list[dict[str, object]]:
    if not root.is_dir() or root.is_symlink():
        raise VerificationError("V4_INSTALL_ROOT_INVALID")
    result: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or path.suffix == ".pyc" or path.name == ".DS_Store":
            continue
        if path.is_symlink():
            raise VerificationError("V4_INSTALL_SYMLINK_FORBIDDEN")
        if path.is_file():
            result.append(
                {
                    "executable": bool(path.stat().st_mode & stat.S_IXUSR),
                    "path": relative.as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    return result


def verify(
    source: Path,
    installed: Path,
    *,
    version: str,
    repo_commit: str,
    config_before_sha256: str,
    config_after_sha256: str,
    config_existed: bool,
) -> dict[str, object]:
    source_files = file_inventory(source)
    installed_files = file_inventory(installed)
    if source_files != installed_files:
        raise VerificationError("V4_SOURCE_INSTALL_DRIFT")
    if config_before_sha256 != config_after_sha256:
        raise VerificationError("V4_CODEX_CONFIG_MUTATED")
    if version != "4.0.0":
        raise VerificationError("V4_VERSION_INVALID")
    if repo_commit != "SOURCE_ARCHIVE" and (
        len(repo_commit) != 40
        or any(character not in "0123456789abcdef" for character in repo_commit)
    ):
        raise VerificationError("V4_SOURCE_COMMIT_INVALID")
    manifest_digest = digest(installed_files)
    return {
        "artifact": "loopskill4-install-receipt-v1",
        "config_after_sha256": config_after_sha256,
        "config_before_sha256": config_before_sha256,
        "config_existed": config_existed,
        "files": installed_files,
        "installed_manifest_digest": manifest_digest,
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
            config_before_sha256=args.config_before_sha256,
            config_after_sha256=args.config_after_sha256,
            config_existed=args.config_existed == "1",
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_bytes(canonical(receipt) + b"\n")
        os.replace(temporary, args.output)
    except (OSError, VerificationError) as exc:
        print(json.dumps({"ok": False, "status": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "manifest_digest": receipt["installed_manifest_digest"]}, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
