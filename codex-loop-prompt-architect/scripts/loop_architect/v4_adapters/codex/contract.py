"""Ports consumed by the Codex Host Adapter."""

from __future__ import annotations

from typing import Any, Mapping, Protocol


class AttemptClaimPort(Protocol):
    def claim_attempt(self, attempt_ref: str, executor_ref: str) -> bool: ...

    def outbox_attempt(self, attempt_ref: str) -> dict[str, Any] | None: ...


class CodexProviderPort(Protocol):
    def capability_snapshot(self) -> Mapping[str, Any]: ...

    def invoke(
        self,
        action: str,
        payload: Mapping[str, Any],
        provider_idempotency_key: str,
    ) -> Mapping[str, Any]: ...

    def readback(
        self, action: str, provider_idempotency_key: str
    ) -> Mapping[str, Any] | None: ...

    def read_resource(
        self, resource_kind: str, provider_id: str
    ) -> Mapping[str, Any]: ...

    def read_task_result(self, provider_id: str) -> Mapping[str, Any]: ...
