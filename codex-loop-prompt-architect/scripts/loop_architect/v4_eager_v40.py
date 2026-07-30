"""Closed, removable continuation adapter for persisted LoopSkill v4.0 loops."""

from __future__ import annotations

from typing import Any, Mapping

from .v4_alpha.kernel import AuthorityContext, reduce_command
from .v4_alpha.protocol import (
    CommandEnvelope,
    EAGER_STORAGE_MODE,
    EAGER_PROTOCOL_VERSION,
    LEGACY_ABSENT_STORAGE_MODE,
    MALFORMED_STORAGE_MODE,
    ProtocolRejection,
    classify_persisted_storage_mode,
)


def reduce_eager_command(
    snapshot: Mapping[str, Any] | None,
    command: CommandEnvelope,
    context: AuthorityContext,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Continue one existing v4.0 snapshot without migration or dual write."""

    storage_mode = classify_persisted_storage_mode(snapshot)
    if storage_mode == MALFORMED_STORAGE_MODE:
        raise ProtocolRejection(
            "INTERNAL_INVARIANT_VIOLATION",
            "persisted storage mode is malformed",
        )
    if (
        storage_mode
        not in {LEGACY_ABSENT_STORAGE_MODE, EAGER_STORAGE_MODE}
        or command.protocol_version != EAGER_PROTOCOL_VERSION
    ):
        raise ProtocolRejection(
            "UNSUPPORTED_PROTOCOL_VERSION", command.protocol_version
        )
    if command.command_type == "CreateLoop":
        raise ProtocolRejection(
            "UNSUPPORTED_PROTOCOL_VERSION", command.protocol_version
        )
    if command.command_type == "ReviseGoalPlan" and set(
        command.semantic_payload
    ) != {"objective_order", "reason"}:
        raise ProtocolRejection(
            "INVALID_COMMAND", "v4.0 Goal-plan revision shape changed"
        )
    return reduce_command(
        snapshot,
        command,
        context,
        expected_protocol_version=EAGER_PROTOCOL_VERSION,
        persisted_storage_mode=storage_mode,
    )
