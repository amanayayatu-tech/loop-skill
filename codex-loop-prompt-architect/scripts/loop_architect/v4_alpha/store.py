"""Reference in-memory transactional store for the v4 alpha slice."""

from __future__ import annotations

import base64
import copy
from dataclasses import replace
from typing import Any

from .kernel import AuthorityContext, reduce_command
from .protocol import (
    ApplyResult,
    CommandEnvelope,
    InjectedCrash,
    ProtocolRejection,
    command_digest,
    snapshot_digest,
    canonical_bytes,
    validate_command,
    raw_domain_digest,
)


FAULT_BOUNDARIES = (
    "before_reduce",
    "after_reduce_before_commit",
    "after_commit_before_response",
)


def _outbox_entry(loop_ref, attempt_ref, attempt):
    if "external_effect_ref" in attempt:
        return {
            "action": attempt["action"],
            "attempt_ref": attempt_ref,
            "automatic_budget_consumed": attempt["automatic_budget_consumed"],
            "loop_ref": loop_ref,
            "provider_idempotency_key": attempt["provider_idempotency_key"],
            "provider_request": copy.deepcopy(attempt["provider_request"]),
            "provider_request_digest": attempt["provider_request_digest"],
            "revision": attempt["revision"],
            "state": attempt["state"],
            "subject_kind": attempt["subject_kind"],
            "subject_ref": attempt["subject_ref"],
            "target_ref": attempt["target_ref"],
        }
    return {
        "attempt_ref": attempt_ref,
        "automatic_budget_consumed": attempt["automatic_budget_consumed"],
        "delivery_ref": attempt["delivery_ref"],
        "loop_ref": loop_ref,
        "provider_idempotency_key": attempt["provider_idempotency_key"],
        "provider_request_digest": attempt["provider_request_digest"],
        "revision": attempt["revision"],
        "state": attempt["state"],
    }


class InMemoryStore:
    """Single-process reference store with one atomic commit object per loop."""

    def __init__(self, authority: AuthorityContext) -> None:
        self.authority = authority
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._accepted: dict[tuple[str, str], tuple[str, ApplyResult]] = {}
        self._rejected: dict[
            tuple[str, str], tuple[str, dict[str, str]]
        ] = {}
        self._blobs: dict[str, bytes] = {}
        self.commit_count = 0

    def snapshot(self, loop_ref: str) -> dict[str, Any] | None:
        value = self._snapshots.get(loop_ref)
        return copy.deepcopy(value) if value is not None else None

    def events(self, loop_ref: str) -> list[dict[str, Any]]:
        return copy.deepcopy(self._events.get(loop_ref, []))

    def put_blob(self, content: bytes) -> str:
        if not isinstance(content, bytes):
            raise TypeError("blob content must be bytes")
        digest = raw_domain_digest("loopskill-blob-v1\n", content)
        existing = self._blobs.get(digest)
        if existing is not None and existing != content:
            raise ProtocolRejection(
                "INTERNAL_INVARIANT_VIOLATION", "immutable blob digest collision"
            )
        self._blobs[digest] = content
        return digest

    def get_blob(self, digest: str) -> bytes | None:
        value = self._blobs.get(digest)
        return None if value is None else bytes(value)

    @property
    def rejection_count(self) -> int:
        return len(self._rejected)

    def canonical_export(self) -> bytes:
        return canonical_bytes(
            {
                "accepted": [
                    {
                        "loop_ref": loop_ref,
                        "operation_id": operation_id,
                        "request_digest": request_digest,
                        "result": {
                            "event_types": list(result.event_types),
                            "loop_ref": result.loop_ref,
                            "loop_revision": result.loop_revision,
                            "operation_id": result.operation_id,
                            "response": dict(result.response),
                            "snapshot_digest": result.snapshot_digest,
                        },
                    }
                    for (loop_ref, operation_id), (
                        request_digest,
                        result,
                    ) in sorted(self._accepted.items())
                ],
                "blobs": [
                    {
                        "blob_digest": digest,
                        "content_base64": base64.b64encode(content).decode("ascii"),
                        "content_bytes": len(content),
                    }
                    for digest, content in sorted(self._blobs.items())
                ],
                "events": {
                    loop_ref: copy.deepcopy(events)
                    for loop_ref, events in sorted(self._events.items())
                },
                "outbox": [
                    _outbox_entry(loop_ref, attempt_ref, attempt)
                    for loop_ref, snapshot in sorted(self._snapshots.items())
                    for attempt_ref, attempt in sorted(snapshot["attempts"].items())
                ],
                "rejected": [
                    {
                        "error": dict(error),
                        "loop_ref": loop_ref,
                        "operation_id": operation_id,
                        "request_digest": request_digest,
                    }
                    for (loop_ref, operation_id), (
                        request_digest,
                        error,
                    ) in sorted(self._rejected.items())
                ],
                "schema_version": 1,
                "snapshots": {
                    loop_ref: copy.deepcopy(snapshot)
                    for loop_ref, snapshot in sorted(self._snapshots.items())
                },
            }
        )

    def verify_integrity(self) -> None:
        for digest, content in self._blobs.items():
            if raw_domain_digest("loopskill-blob-v1\n", content) != digest:
                raise ProtocolRejection(
                    "INTERNAL_INVARIANT_VIOLATION", "blob digest mismatch"
                )
        for loop_ref, snapshot in self._snapshots.items():
            expected_sequence = list(range(1, len(self._events.get(loop_ref, [])) + 1))
            actual_sequence = [
                event["sequence"] for event in self._events.get(loop_ref, [])
            ]
            if actual_sequence != expected_sequence:
                raise ProtocolRejection(
                    "INTERNAL_INVARIANT_VIOLATION", "event sequence is not contiguous"
                )
            accepted = sum(
                1 for accepted_loop, _ in self._accepted if accepted_loop == loop_ref
            )
            if snapshot["loop_revision"] != accepted:
                raise ProtocolRejection(
                    "INTERNAL_INVARIANT_VIOLATION", "loop revision/operation mismatch"
                )
            snapshot_digest(snapshot)

    def apply(
        self,
        command: CommandEnvelope,
        *,
        fault_at: str | None = None,
    ) -> ApplyResult:
        loop_ref = str(command.subject.get("loop_ref", ""))
        key = (loop_ref, command.operation_id)
        calculated_digest = command_digest(command)
        accepted = self._accepted.get(key)
        if accepted is not None:
            request_digest, result = accepted
            if (
                request_digest != calculated_digest
                or command.request_digest != calculated_digest
            ):
                raise ProtocolRejection(
                    "IDEMPOTENCY_CONFLICT", "accepted operation digest changed"
                )
            return replace(result, replayed=True)
        rejected = self._rejected.get(key)
        if rejected is not None:
            request_digest, error = rejected
            if (
                request_digest != calculated_digest
                or command.request_digest != calculated_digest
            ):
                raise ProtocolRejection(
                    "IDEMPOTENCY_CONFLICT", "rejected operation digest changed"
                )
            raise ProtocolRejection(error["code"], error["detail"])

        try:
            validate_command(command)
            current = self._snapshots.get(loop_ref)
            actual_revision = 0 if current is None else current["loop_revision"]
            if actual_revision != command.expected_loop_revision:
                raise ProtocolRejection(
                    "STALE_LOOP_REVISION",
                    f"expected {command.expected_loop_revision}, actual {actual_revision}",
                )
            if fault_at == "before_reduce":
                raise InjectedCrash(fault_at)
            candidate, pending_events, response = reduce_command(
                current, command, self.authority
            )
            if fault_at == "after_reduce_before_commit":
                raise InjectedCrash(fault_at)

            existing_events = self._events.get(loop_ref, [])
            sequenced = [
                {**event, "sequence": len(existing_events) + index + 1}
                for index, event in enumerate(pending_events)
            ]
            all_events = copy.deepcopy(existing_events) + sequenced
            digest = snapshot_digest(candidate)
            result = ApplyResult(
                operation_id=command.operation_id,
                loop_ref=loop_ref,
                loop_revision=candidate["loop_revision"],
                event_types=tuple(event["type"] for event in sequenced),
                response=copy.deepcopy(response),
                snapshot_digest=digest,
            )

            # The snapshot, ordered events, and idempotency result are one
            # atomic in-memory commit object for this reference implementation.
            self._snapshots[loop_ref] = copy.deepcopy(candidate)
            self._events[loop_ref] = all_events
            self._accepted[key] = (calculated_digest, result)
            self.commit_count += 1
            if fault_at == "after_commit_before_response":
                raise InjectedCrash(fault_at)
            return result
        except InjectedCrash:
            raise
        except ProtocolRejection as exc:
            self._rejected[key] = (calculated_digest, exc.as_dict())
            raise
