"""Deterministic route orchestrator (P1-4).

The orchestrator collapses a Controller's three-step route hand-off
(``PREPARE_ROUTE`` -> send -> ``RECORD_ROUTE_SENT``) and the
``ACK_ROUTE_RESULT`` -> next-route hand-off into a single deterministic
turn. External calls remain individual receipts; only the *sequencing*
is collapsed. The orchestrator never invents a network-level atomic
transaction. A Controller turn can resume after its last acknowledged
step with one merged receipt; every external action retains its own
identity and a replay resumes from, rather than repeats, that boundary.

The module is intentionally minimal: it accepts a sequence of
``OrchestrationStep`` objects and a write callback, runs them in
order, and records one merged receipt. It does not import from
``state_runtime`` so the dependency surface stays one-way.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

#: Status outcomes the orchestrator may produce. The list mirrors the
#: statuses the existing ``adaptive_state_mcp`` reports so the
#: downstream parser needs no new branch.
STATUS_COMPLETED = "ORCHESTRATION_COMPLETED"
STATUS_FAILED = "ORCHESTRATION_FAILED"
STATUS_ABORTED = "ORCHESTRATION_ABORTED"

#: A sentinel the writer callback returns when the underlying
#: canonical writer refuses to mutate. The orchestrator does not
#: retry; the parent turn is responsible for deciding whether to
#: fall back to per-step hand-off.
REFUSED_SENTINEL: str = "__orchestration_refused__"


class RouteOrchestrationError(RuntimeError):
    """Raised on validation or sequencing failure. The orchestrator
    does not raise during normal operation; it only raises when the
    caller passes an invalid step list."""


@dataclass(frozen=True)
class OrchestrationStep:
    """One step in an orchestrated sequence.

    Attributes:
        operation: the public state-gateway operation name (for
            example ``PREPARE_ROUTE``).
        payload: the JSON-stable payload the step will write.
        requires_external_call: when True, the step expects the
            caller to have already made the external App call; the
            step's role is to record the receipt only.
    """

    operation: str
    payload: Mapping[str, Any]
    requires_external_call: bool = False
    external_receipt_digest: str = ""

    def canonical(self) -> bytes:
        """Return the canonical byte form used for receipt digests."""
        return json.dumps(
            {
                "operation": self.operation,
                "payload": dict(self.payload),
                "requires_external_call": self.requires_external_call,
                "external_receipt_digest": self.external_receipt_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()


@dataclass
class OrchestrationReceipt:
    """One merged receipt for a complete orchestration."""

    turn_id: str
    steps: tuple[OrchestrationStep, ...]
    step_receipts: tuple[Mapping[str, Any], ...]
    status: str
    started_at: float
    completed_at: float
    failure_operation: str = ""
    failure_reason: str = ""
    digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "turn_id": self.turn_id,
            "steps": [
                {
                    "operation": step.operation,
                    "payload_digest": hashlib.sha256(step.canonical()).hexdigest(),
                    "requires_external_call": step.requires_external_call,
                }
                for step in self.steps
            ],
            "step_receipts": [dict(receipt) for receipt in self.step_receipts],
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "digest": self.digest,
        }
        if self.failure_operation:
            result["failure_operation"] = self.failure_operation
        if self.failure_reason:
            result["failure_reason"] = self.failure_reason
        return result


WriteCallback = Callable[[OrchestrationStep], Mapping[str, Any]]


def orchestrate(
    turn_id: str,
    steps: Sequence[OrchestrationStep],
    write: WriteCallback,
    *,
    clock: Callable[[], float] = time.monotonic,
    completed_step_receipts: Sequence[Mapping[str, Any]] = (),
) -> OrchestrationReceipt:
    """Run ``steps`` under one merged receipt.

    Args:
        turn_id: the App turn identity the orchestrator is bound to.
            The orchestrator does not validate the identity, but the
            parent turn must pass the same identity the existing
            TRUSTED_TURN_SOURCE contract expects.
        steps: the deterministic sequence of steps. ``None`` or an
            empty sequence is rejected.
        write: the canonical writer callback. The callback is invoked
            once per step; the orchestrator does not retry.

    Returns:
        An :class:`OrchestrationReceipt`. On success ``status`` is
        :data:`STATUS_COMPLETED`; on the first failure ``status`` is
        :data:`STATUS_FAILED` and the failure is recorded; if the
        writer returns :data:`REFUSED_SENTINEL` the orchestration is
        aborted and the parent turn is told to fall back to per-step
        hand-off.
    """
    if not steps:
        raise RouteOrchestrationError("orchestration requires at least one step")
    if not turn_id:
        raise RouteOrchestrationError("turn_id is required")
    if len(completed_step_receipts) > len(steps):
        raise RouteOrchestrationError("completed receipts exceed step count")
    started = clock()
    receipts: list[Mapping[str, Any]] = [dict(item) for item in completed_step_receipts]
    for step in steps[len(receipts):]:
        receipt = write(step)
        if receipt is None:
            completed = clock()
            return _make_receipt(
                turn_id=turn_id,
                steps=steps,
                receipts=tuple(receipts),
                status=STATUS_FAILED,
                started_at=started,
                completed_at=completed,
                failure_operation=step.operation,
                failure_reason="write callback returned None",
            )
        if isinstance(receipt, Mapping) and receipt.get("status") == REFUSED_SENTINEL:
            completed = clock()
            return _make_receipt(
                turn_id=turn_id,
                steps=steps,
                receipts=tuple(receipts),
                status=STATUS_ABORTED,
                started_at=started,
                completed_at=completed,
                failure_operation=step.operation,
                failure_reason="writer refused mutation",
            )
        receipts.append(receipt)
    completed = clock()
    return _make_receipt(
        turn_id=turn_id,
        steps=steps,
        receipts=tuple(receipts),
        status=STATUS_COMPLETED,
        started_at=started,
        completed_at=completed,
    )


def _make_receipt(
    *,
    turn_id: str,
    steps: Sequence[OrchestrationStep],
    receipts: tuple[Mapping[str, Any], ...],
    status: str,
    started_at: float,
    completed_at: float,
    failure_operation: str = "",
    failure_reason: str = "",
) -> OrchestrationReceipt:
    canonical = json.dumps(
        {
            "turn_id": turn_id,
            "step_digests": [
                hashlib.sha256(step.canonical()).hexdigest() for step in steps
            ],
            "step_receipt_digests": [
                hashlib.sha256(
                    json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                for receipt in receipts
            ],
            "status": status,
            "started_at": started_at,
            "completed_at": completed_at,
            "failure_operation": failure_operation,
            "failure_reason": failure_reason,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return OrchestrationReceipt(
        turn_id=turn_id,
        steps=tuple(steps),
        step_receipts=receipts,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        failure_operation=failure_operation,
        failure_reason=failure_reason,
        digest=hashlib.sha256(canonical).hexdigest(),
    )


def fold_legacy_three_step(
    *,
    prepare_payload: Mapping[str, Any],
    send_receipt: Mapping[str, Any],
    record_payload: Mapping[str, Any],
) -> tuple[OrchestrationStep, ...]:
    """Fold the canonical three-step route hand-off into one
    orchestration sequence. Provided as a convenience so callers do
    not duplicate the step ordering.
    """
    send_receipt_digest = hashlib.sha256(
        json.dumps(send_receipt, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return (
        OrchestrationStep(
            operation="PREPARE_ROUTE",
            payload=prepare_payload,
        ),
        OrchestrationStep(
            operation="RECORD_ROUTE_SENT",
            payload=record_payload,
            requires_external_call=True,
            external_receipt_digest=send_receipt_digest,
        ),
    )


__all__ = [
    "OrchestrationReceipt",
    "OrchestrationStep",
    "REFUSED_SENTINEL",
    "RouteOrchestrationError",
    "STATUS_ABORTED",
    "STATUS_COMPLETED",
    "STATUS_FAILED",
    "fold_legacy_three_step",
    "orchestrate",
]
