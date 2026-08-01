#!/usr/bin/env python3
"""Validate Nepha in a disposable Chinese-path copy without touching its source."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Sequence


ARTIFACT = "loopskill-v4.2-nepha-copy-canary-v1"
PORT = 4317
ROUTES = ("today", "inbox", "content", "settings")
EXCLUDED = {".git", "node_modules", ".DS_Store", "coverage", "dist", "build"}


class CanaryError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", *args), cwd=root, check=False, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if completed.returncode:
        raise CanaryError("NEPHA_CANARY_GIT_READ_FAILED")
    return completed.stdout.strip()


def _validate_candidate(root: Path, candidate: str) -> None:
    if len(candidate) != 40 or any(ch not in "0123456789abcdef" for ch in candidate):
        raise CanaryError("NEPHA_CANARY_CANDIDATE_INVALID")
    if _git(root, "rev-parse", "HEAD") != candidate:
        raise CanaryError("NEPHA_CANARY_NOT_EXACT_HEAD")
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise CanaryError("NEPHA_CANARY_WORKTREE_NOT_CLEAN")


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
        relative = path.relative_to(root)
        if any(part in EXCLUDED for part in relative.parts):
            continue
        if path.is_symlink():
            digest.update(b"L\0" + relative.as_posix().encode("utf-8") + b"\0")
            digest.update(os.readlink(path).encode("utf-8") + b"\0")
        elif path.is_file():
            digest.update(b"F\0" + relative.as_posix().encode("utf-8") + b"\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
    return digest.hexdigest()


def _run(argv: tuple[str, ...], *, cwd: Path, timeout: int) -> bytes:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        env={**os.environ, "NO_COLOR": "1"},
    )
    if completed.returncode:
        raise CanaryError("NEPHA_CANARY_COMMAND_FAILED")
    return completed.stdout


def _port_available() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", PORT))
        except OSError:
            return False
    return True


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=3)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)


def _write_private(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def run(root: Path, candidate: str, source: Path, output: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    source = source.resolve(strict=True)
    _validate_candidate(root, candidate)
    if not source.is_dir() or source.is_symlink():
        raise CanaryError("NEPHA_CANARY_SOURCE_INVALID")
    if not _port_available():
        raise CanaryError("NEPHA_CANARY_PORT_IN_USE")
    source_before = _tree_digest(source)
    with tempfile.TemporaryDirectory(prefix="loopskill4-nepha-copy-") as temporary:
        chinese_root = Path(temporary) / "中文路径"
        chinese_root.mkdir(mode=0o700)
        copy = chinese_root / "nepha-content-os"
        shutil.copytree(
            source,
            copy,
            symlinks=True,
            ignore=shutil.ignore_patterns(*EXCLUDED),
        )
        _run(("npm", "test"), cwd=copy, timeout=120)
        child_output = _run(("npm", "run", "codex:smoke"), cwd=copy, timeout=300)
        if b'"outcome":"PASS"' not in child_output.replace(b" ", b""):
            raise CanaryError("NEPHA_CANARY_CHILD_CAPABILITY_FAILED")
        process = subprocess.Popen(
            ("npm", "start"),
            cwd=copy,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 20
            last_error: BaseException | None = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise CanaryError("NEPHA_CANARY_SERVER_EXITED")
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{PORT}/?view=today", timeout=1
                    ) as response:
                        if response.status == 200:
                            break
                except OSError as exc:
                    last_error = exc
                    time.sleep(0.1)
            else:
                raise CanaryError("NEPHA_CANARY_LISTENER_TIMEOUT") from last_error
            for route in ROUTES:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{PORT}/?view={route}", timeout=2
                ) as response:
                    body = response.read(1024 * 1024)
                    if response.status != 200 or not body:
                        raise CanaryError("NEPHA_CANARY_ROUTE_FAILED")
        finally:
            _stop(process)
        copy_after = _tree_digest(copy)
    source_after = _tree_digest(source)
    if source_after != source_before:
        raise CanaryError("NEPHA_CANARY_SOURCE_CHANGED")
    receipt: dict[str, object] = {
        "artifact": ARTIFACT,
        "candidate_sha": candidate,
        "chinese_path_supported": True,
        "copy_tree_sha256": copy_after,
        "host_child_separation_verified": True,
        "http_route_count": len(ROUTES),
        "listener_count": 1,
        "main_project_bytes_changed": 0,
        "provider_resend_count": 0,
        "public_release_effects": 0,
        "source_tree_sha256": source_before,
        "status": "PASS",
        "test_command_count": 1,
    }
    _write_private(output, _canonical(receipt))
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = run(args.root, args.candidate, args.source, args.output)
    except (CanaryError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"NEPHA_CANARY_FAILED: {exc}", file=sys.stderr)
        return 1
    print(_canonical(receipt).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
