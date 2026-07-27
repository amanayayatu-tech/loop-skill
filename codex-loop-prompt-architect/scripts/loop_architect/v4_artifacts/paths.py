"""Race-aware path confinement shared by artifact capability profiles."""

from __future__ import annotations

import os
import stat
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable


MAX_CAPTURE_FILES = 4_096
MAX_CAPTURE_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 16 * 1024 * 1024
CONTROL_PREFIXES = (".codex-loop", ".git")


class ArtifactCaptureError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def normalize_relative_path(relative: str) -> str:
    if not isinstance(relative, str) or not relative or "\x00" in relative:
        raise ArtifactCaptureError("PATH_CONFINEMENT_VIOLATION", "invalid path")
    if "\\" in relative:
        raise ArtifactCaptureError(
            "PATH_CONFINEMENT_VIOLATION", "platform-ambiguous separator"
        )
    candidate = PurePosixPath(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ArtifactCaptureError("PATH_CONFINEMENT_VIOLATION", relative)
    normalized = candidate.as_posix()
    if normalized in {"", "."} or normalized.startswith("./"):
        raise ArtifactCaptureError("PATH_CONFINEMENT_VIOLATION", relative)
    if candidate.parts[0] in CONTROL_PREFIXES:
        raise ArtifactCaptureError("PATH_CONFINEMENT_VIOLATION", relative)
    return normalized


def reject_casefold_collisions(paths: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(sorted(normalize_relative_path(path) for path in paths))
    folded: dict[str, str] = {}
    for path in normalized:
        key = path.casefold()
        previous = folded.get(key)
        if previous is not None and previous != path:
            raise ArtifactCaptureError(
                "PATH_CONFINEMENT_VIOLATION",
                f"casefold collision: {previous} / {path}",
            )
        folded[key] = path
    if len(normalized) != len(set(normalized)):
        raise ArtifactCaptureError("PATH_CONFINEMENT_VIOLATION", "duplicate path")
    return normalized


def _stat_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def secure_read_regular(
    root: Path | str,
    relative: str,
    *,
    after_open: Callable[[], None] | None = None,
) -> bytes:
    """Read one confined regular file without following path symlinks."""

    normalized = normalize_relative_path(relative)
    root_path = Path(root)
    if root_path.is_symlink() or not root_path.is_dir():
        raise ArtifactCaptureError("PATH_CONFINEMENT_VIOLATION", "invalid root")
    flags_directory = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
        os, "O_NOFOLLOW", 0
    )
    descriptors = []
    try:
        directory_fd = os.open(root_path, flags_directory)
        descriptors.append(directory_fd)
        parts = PurePosixPath(normalized).parts
        for component in parts[:-1]:
            directory_fd = os.open(component, flags_directory, dir_fd=directory_fd)
            descriptors.append(directory_fd)
        file_fd = os.open(
            parts[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
        descriptors.append(file_fd)
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):
            raise ArtifactCaptureError(
                "PATH_CONFINEMENT_VIOLATION", f"not a regular file: {normalized}"
            )
        if before.st_size > MAX_FILE_BYTES:
            raise ArtifactCaptureError(
                "ARTIFACT_IDENTITY_MISMATCH", f"file exceeds bound: {normalized}"
            )
        if after_open is not None:
            after_open()
        chunks = []
        remaining = MAX_FILE_BYTES + 1
        while remaining:
            chunk = os.read(file_fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(file_fd)
        if len(content) > MAX_FILE_BYTES:
            raise ArtifactCaptureError(
                "ARTIFACT_IDENTITY_MISMATCH", f"file exceeds bound: {normalized}"
            )
        if _stat_identity(before) != _stat_identity(after):
            raise ArtifactCaptureError(
                "ARTIFACT_STALE", f"file changed during capture: {normalized}"
            )
        return content
    except ArtifactCaptureError:
        raise
    except OSError as exc:
        raise ArtifactCaptureError(
            "PATH_CONFINEMENT_VIOLATION", f"unsafe path: {normalized}"
        ) from exc
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def enumerate_regular_files(root: Path | str) -> tuple[str, ...]:
    root_path = Path(root)
    if root_path.is_symlink() or not root_path.is_dir():
        raise ArtifactCaptureError("PATH_CONFINEMENT_VIOLATION", "invalid root")
    discovered = []
    for directory, names, files in os.walk(root_path, topdown=True, followlinks=False):
        directory_path = Path(directory)
        kept = []
        for name in sorted(names):
            candidate = directory_path / name
            relative = candidate.relative_to(root_path).as_posix()
            if candidate.is_symlink():
                raise ArtifactCaptureError(
                    "PATH_CONFINEMENT_VIOLATION", f"symlink directory: {relative}"
                )
            if name in CONTROL_PREFIXES and directory_path == root_path:
                continue
            kept.append(name)
        names[:] = kept
        for name in sorted(files):
            candidate = directory_path / name
            relative = candidate.relative_to(root_path).as_posix()
            if candidate.is_symlink():
                raise ArtifactCaptureError(
                    "PATH_CONFINEMENT_VIOLATION", f"symlink file: {relative}"
                )
            metadata = candidate.stat(follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode):
                raise ArtifactCaptureError(
                    "PATH_CONFINEMENT_VIOLATION", f"special file: {relative}"
                )
            discovered.append(normalize_relative_path(relative))
            if len(discovered) > MAX_CAPTURE_FILES:
                raise ArtifactCaptureError(
                    "ARTIFACT_IDENTITY_MISMATCH", "file-count bound exceeded"
                )
    return reject_casefold_collisions(discovered)
