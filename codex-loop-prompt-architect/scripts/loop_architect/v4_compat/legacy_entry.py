"""One-major-cycle facade for public v3 intake/generate and Pack repair inputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from loop_architect.v4_alpha.protocol import (
    LoopIntakeDecision,
    LoopIntakeInput,
    raw_domain_digest,
)
from loop_architect.v4_entry.preparation import PreparedContext, intake, prepare


_OUTPUT_DETAILS = {"compact", "full", "minimal_patch"}
_HIGH_IMPACT_ACTIONS = {
    "commit",
    "push",
    "publish",
    "deploy",
}
_MAX_EXISTING_PACK_BYTES = 256 * 1024


class LegacyEntryError(ValueError):
    pass


@dataclass(frozen=True)
class LegacyPreparedView:
    coordination_mode: str
    output_detail: str
    prepared: PreparedContext
    export_bytes: bytes
    existing_pack_digest: str | None


def _string_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise LegacyEntryError(f"{field} must be a non-empty string list")
    return tuple(item.strip() for item in value)


def map_legacy_input(value: Mapping[str, Any]) -> LoopIntakeInput:
    """Map the stable public v3 input surface without preserving its control IDs."""

    objective = value.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        raise LegacyEntryError("objective is required")
    mode = value.get("coordination_mode", "standard")
    if mode not in {"standard", "adaptive"}:
        raise LegacyEntryError("coordination_mode must be standard or adaptive")
    allowed = _string_list(value.get("allowed", []), "allowed")
    acceptance = _string_list(
        value.get("acceptance_criteria", value.get("validation", [])),
        "acceptance_criteria",
    )
    forbidden = value.get("forbidden", ["stop on authorization boundary"])
    stop_conditions = _string_list(forbidden, "forbidden")
    budget_value = value.get("time_typical", value.get("budget", "bounded by user confirmation"))
    if not isinstance(budget_value, str) or not budget_value.strip():
        raise LegacyEntryError("budget/time_typical is required")
    permissions = value.get("phase_permissions", {})
    if not isinstance(permissions, Mapping):
        permissions = {}
    external_actions = tuple(
        action
        for action in sorted(_HIGH_IMPACT_ACTIONS)
        if permissions.get(action) is True
    )
    return LoopIntakeInput(
        goal=objective.strip(),
        task_horizon="adaptive" if mode == "adaptive" else "standard",
        write_scope=allowed,
        budget=budget_value.strip(),
        external_actions=external_actions,
        acceptance_criteria=acceptance,
        stop_conditions=stop_conditions,
        authorization_boundaries=(),
    )


def legacy_intake(value: Mapping[str, Any]) -> LoopIntakeDecision:
    """Behavior-equivalent intake-only entry; it performs no writes."""

    return intake(map_legacy_input(value))


def _existing_pack_digest(existing_pack_bytes: bytes | None) -> str | None:
    if existing_pack_bytes is None:
        return None
    if len(existing_pack_bytes) > _MAX_EXISTING_PACK_BYTES:
        raise LegacyEntryError("existing Pack exceeds the compatibility byte bound")
    try:
        text = existing_pack_bytes.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise LegacyEntryError("existing Pack is not strict UTF-8") from exc
    if not text.startswith("# ") or "Controller" not in text:
        raise LegacyEntryError("existing Pack does not expose the stable review surface")
    return raw_domain_digest("loopskill-v3-existing-pack-v1\n", existing_pack_bytes)


def _render_view(
    prepared: PreparedContext,
    *,
    mode: str,
    detail: str,
    existing_pack_digest: str | None,
) -> bytes:
    manifest = prepared.manifest
    heading = (
        "# LoopSkill 4 legacy Pack repair preview"
        if existing_pack_digest is not None
        else "# LoopSkill 4 compatibility Controller Plan"
    )
    lines = [
        heading,
        "",
        f"- Goal: {manifest.goal}",
        f"- Coordination: {mode}",
        f"- Output detail: {detail}",
        "- Machine truth: typed prepared manifest",
        "- Host/execution effects: 0",
    ]
    if detail == "full":
        lines.extend(
            [
                f"- Write scope: {', '.join(manifest.write_scope)}",
                f"- Budget: {manifest.budget}",
                f"- Acceptance: {'; '.join(manifest.acceptance_criteria)}",
                f"- Stop: {'; '.join(manifest.stop_conditions)}",
            ]
        )
    elif detail == "minimal_patch":
        if existing_pack_digest is None:
            raise LegacyEntryError("minimal_patch requires an existing Pack")
        lines.extend(
            [
                f"- Existing Pack digest: {existing_pack_digest}",
                "- Repair: replace machine-control fields with the typed manifest; preserve the human plan as an export view.",
                "- Source Pack mutation: none",
            ]
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def legacy_prepare(
    value: Mapping[str, Any],
    output_directory: Path | str,
    *,
    output_detail: str = "compact",
    existing_pack_bytes: bytes | None = None,
) -> LegacyPreparedView:
    """Prepare v4 artifacts plus a human compatibility view, without starting."""

    if output_detail not in _OUTPUT_DETAILS:
        raise LegacyEntryError("output_detail must be compact, full, or minimal_patch")
    request = map_legacy_input(value)
    decision = intake(request)
    if decision.disposition != "READY_FOR_LOOP":
        raise LegacyEntryError(f"legacy input is not ready: {decision.disposition}")
    pack_digest = _existing_pack_digest(existing_pack_bytes)
    prepared = prepare(request, output_directory)
    mode = "adaptive" if decision.route == "ADAPTIVE_LOOP" else "standard"
    return LegacyPreparedView(
        coordination_mode=mode,
        output_detail=output_detail,
        prepared=prepared,
        export_bytes=_render_view(
            prepared,
            mode=mode,
            detail=output_detail,
            existing_pack_digest=pack_digest,
        ),
        existing_pack_digest=pack_digest,
    )
