"""Crash-consistent content-addressed storage for derived Loop artifacts.

New derived files retain their historical facade paths while their bytes live
in an immutable SHA-256 object store.  Facades are hard links, so identical
payloads occupy one inode.  Existing ordinary files remain readable and are
only converted when a later runtime write touches them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


DIGEST_RE = re.compile(r"[a-f0-9]{64}\Z")


class ContentAddressingError(ValueError):
    """Raised when an object, facade, or index violates the store contract."""


@dataclass(frozen=True)
class ContentReference:
    digest: str
    size: int
    object_path: str
    facade_path: str
    category: str

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "digest": self.digest,
            "facade_path": self.facade_path,
            "object_path": self.object_path,
            "size": self.size,
        }


class ContentAddressedStore:
    """Immutable object store rooted below a Loop control directory."""

    def __init__(self, control_dir: Path) -> None:
        self.control_dir = control_dir
        self.root = control_dir / "content-addressed"
        self.objects = self.root / "objects"
        self.index = self.root / "index.jsonl"

    @staticmethod
    def digest_bytes(payload: bytes) -> str:
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        return hashlib.sha256(payload).hexdigest()

    def ensure_layout(self) -> None:
        for path in (self.root, self.objects):
            if path.is_symlink():
                raise ContentAddressingError("CONTENT_STORE_SYMLINK")
            path.mkdir(mode=0o700, parents=False, exist_ok=True)

    def replace_facade(
        self,
        facade: Path,
        payload: bytes,
        *,
        category: str,
        transaction_id: str,
        final_mode: int = 0o600,
        inject: Callable[[str], None] | None = None,
    ) -> ContentReference:
        """Atomically replace ``facade`` with a link to immutable bytes."""

        if not isinstance(category, str) or not category:
            raise ContentAddressingError("CONTENT_CATEGORY_INVALID")
        self.ensure_layout()
        if facade.is_symlink() or facade.parent.is_symlink():
            raise ContentAddressingError("CONTENT_FACADE_SYMLINK")
        try:
            relative = facade.relative_to(self.control_dir).as_posix()
        except ValueError as exc:
            raise ContentAddressingError("CONTENT_FACADE_OUTSIDE_CONTROL_DIR") from exc
        digest = self.digest_bytes(payload)
        mode_dir = self.objects / f"{final_mode:04o}"
        if mode_dir.is_symlink():
            raise ContentAddressingError("CONTENT_STORE_SYMLINK")
        mode_dir.mkdir(mode=0o700, exist_ok=True)
        object_path = mode_dir / digest
        if object_path.exists():
            self._verify_object(object_path, digest, len(payload))
        else:
            temp = mode_dir / f".{digest}.{transaction_id}.tmp"
            self._write_new(temp, payload, final_mode)
            try:
                os.link(temp, object_path, follow_symlinks=False)
            except FileExistsError:
                self._verify_object(object_path, digest, len(payload))
            finally:
                temp.unlink(missing_ok=True)
            self._fsync_dir(mode_dir)
        facade.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temp_facade = facade.parent / f".{facade.name}.{transaction_id}.{category}.link"
        temp_facade.unlink(missing_ok=True)
        os.link(object_path, temp_facade, follow_symlinks=False)
        if inject is not None:
            inject(f"{category}_TEMP_FSYNCED")
        os.replace(temp_facade, facade)
        if inject is not None:
            inject(f"{category}_REPLACED")
        self._fsync_dir(facade.parent)
        if inject is not None:
            inject(f"{category}_DIR_FSYNCED")
        reference = ContentReference(
            digest=digest,
            size=len(payload),
            object_path=object_path.relative_to(self.control_dir).as_posix(),
            facade_path=relative,
            category=category,
        )
        self._append_index(reference)
        return reference

    def read(self, reference: ContentReference) -> bytes:
        if DIGEST_RE.fullmatch(reference.digest) is None:
            raise ContentAddressingError("CONTENT_DIGEST_INVALID")
        path = self.control_dir / reference.object_path
        self._verify_object(path, reference.digest, reference.size)
        return path.read_bytes()

    def _verify_object(self, path: Path, digest: str, size: int) -> None:
        if path.is_symlink():
            raise ContentAddressingError("CONTENT_OBJECT_SYMLINK")
        try:
            metadata = path.stat(follow_symlinks=False)
            payload = path.read_bytes()
        except OSError as exc:
            raise ContentAddressingError("CONTENT_OBJECT_UNAVAILABLE") from exc
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_size != size
            or self.digest_bytes(payload) != digest
        ):
            raise ContentAddressingError("CONTENT_OBJECT_IDENTITY_MISMATCH")

    @staticmethod
    def _write_new(path: Path, payload: bytes, mode: int) -> None:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            view = memoryview(payload)
            offset = 0
            while offset < len(view):
                written = os.write(descriptor, view[offset:])
                if written <= 0:
                    raise OSError("short content-addressed write")
                offset += written
            os.fchmod(descriptor, mode)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _append_index(self, reference: ContentReference) -> None:
        line = (
            json.dumps(
                reference.to_dict(),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        descriptor = os.open(
            self.index,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            if os.write(descriptor, line) != len(line):
                raise OSError("short content index write")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self._fsync_dir(self.root)

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


__all__ = [
    "ContentAddressedStore",
    "ContentAddressingError",
    "ContentReference",
]
