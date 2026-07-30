"""Technology-neutral store port for LoopSkill 4 local state."""

from __future__ import annotations

from typing import Any, Protocol

from .protocol import ApplyResult, CommandEnvelope


class StorePort(Protocol):
    @property
    def commit_count(self) -> int: ...

    @property
    def rejection_count(self) -> int: ...

    def apply(
        self, command: CommandEnvelope, *, fault_at: str | None = None
    ) -> ApplyResult: ...

    def snapshot(self, loop_ref: str) -> dict[str, Any] | None: ...

    def events(self, loop_ref: str) -> list[dict[str, Any]]: ...

    def put_blob(self, content: bytes) -> str: ...

    def get_blob(self, digest: str) -> bytes | None: ...

    def canonical_export(self) -> bytes: ...

    def verify_integrity(self) -> None: ...
