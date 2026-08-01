"""Closed v4.1/v4.2 plan codecs and current-Goal materializer."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .generated_protocol import CAPACITY_CONTRACT, PLAN_SOURCE_KINDS
from .protocol import (
    CONTENT_STORAGE_MODE,
    EAGER_STORAGE_MODE,
    CommandEnvelope,
    build_command,
    canonical_bytes,
    domain_digest,
    derive_loop_plan_ref as _derive_loop_plan_ref,
    derive_plan_ref as _derive_plan_ref,
    goal_chain as _goal_chain,
    parse_json_bytes,
    raw_domain_digest,
)


PLAN_SCHEMA = "loopskill-plan-v1"
PLAN_INDEX_SCHEMA = "loopskill-plan-index-v1"
PLAN_SCHEMA_V2 = "loopskill-plan-v2"
PLAN_INDEX_SCHEMA_V2 = "loopskill-plan-index-v2"
V1_PLAN_MAX_BYTES = 128 * 1024
V1_GOAL_COUNT_MAX = 32
V1_OBJECTIVE_MAX_BYTES = 2 * 1024
SOURCE_KINDS = frozenset(PLAN_SOURCE_KINDS)
PLAN_FIELDS = frozenset(
    {
        "schema",
        "source",
        "objective",
        "boundaries",
        "budget",
        "roadmap_policy",
        "completion_evidence",
        "stop_conditions",
        "goals",
    }
)
SOURCE_FIELDS = frozenset({"kind", "source_digest", "source_content_retained"})
BOUNDARY_FIELDS = frozenset(
    {
        "write_scope",
        "forbidden_paths",
        "forbidden_actions",
        "external_actions",
        "destructive_actions_allowed",
    }
)
BUDGET_FIELDS = frozenset(
    {
        "wall_clock_seconds",
        "max_host_invocations",
        "max_cost_minor_units",
        "currency",
    }
)
ROADMAP_FIELDS = frozenset({"mode", "max_reorders"})
GOAL_FIELDS = frozenset({"goal_id", "objective", "acceptance_criteria"})
PLAN_V2_FIELDS = PLAN_FIELDS | frozenset({"requirements", "worker_profile"})
WORKER_PROFILE_FIELDS = frozenset(
    {
        "attempt_timeout_seconds",
        "local_verification",
        "model",
        "network_access",
        "reasoning_effort",
        "sandbox",
    }
)
GOAL_V2_FIELDS = frozenset(
    {
        "acceptance_criteria",
        "capabilities",
        "gate",
        "goal_id",
        "max_attempts",
        "objective",
        "on_blocked",
        "on_failure",
        "recovery_policy",
        "replay_safety",
        "requirement",
        "requirement_refs",
        "verifiers",
    }
)
INDEX_FIELDS = frozenset(
    {
        "schema",
        "plan_digest",
        "goal_count",
        "ordered_goal_ids",
        "ordered_goal_slice_digests",
        "revision",
        "workspace_binding",
        "authority_digest",
        "capacity_contract_version",
    }
)


class PlanCodecError(ValueError):
    """Typed, public-safe plan admission failure."""

    def __init__(self, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(f"{code}: {reason}")


@dataclass(frozen=True)
class CompiledPlan:
    plan: Mapping[str, Any]
    plan_bytes: bytes
    plan_digest: str
    goal_slice_digests: tuple[str, ...]
    index: Mapping[str, Any]
    index_bytes: bytes
    index_digest: str


def _text(value: Any, label: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise PlanCodecError("USER_PREPARATION_INVALID", f"{label}_not_string")
    try:
        normalized = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n")).strip()
        raw = normalized.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise PlanCodecError("USER_PREPARATION_INVALID", f"{label}_surrogate") from exc
    if not normalized:
        raise PlanCodecError("USER_PREPARATION_INVALID", f"{label}_empty")
    if "\x00" in normalized:
        raise PlanCodecError("USER_PREPARATION_INVALID", f"{label}_nul")
    if len(raw) > maximum:
        raise PlanCodecError("RESOURCE_LIMIT_EXCEEDED", f"{label}_bytes")
    return normalized


def _optional_text(value: Any, label: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise PlanCodecError("USER_PREPARATION_INVALID", f"{label}_not_string")
    try:
        normalized = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n")).strip()
        raw = normalized.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise PlanCodecError("USER_PREPARATION_INVALID", f"{label}_surrogate") from exc
    if "\x00" in normalized:
        raise PlanCodecError("USER_PREPARATION_INVALID", f"{label}_nul")
    if len(raw) > maximum:
        raise PlanCodecError("RESOURCE_LIMIT_EXCEEDED", f"{label}_bytes")
    return normalized


def _string_array(
    value: Any,
    label: str,
    *,
    maximum_items: int,
    allow_empty: bool = True,
    item_maximum: int | None = None,
) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise PlanCodecError("USER_PREPARATION_INVALID", f"{label}_not_array")
    if len(value) > maximum_items:
        raise PlanCodecError("RESOURCE_LIMIT_EXCEEDED", f"{label}_items")
    if not allow_empty and not value:
        raise PlanCodecError("USER_PREPARATION_INVALID", f"{label}_empty")
    maximum = (
        int(CAPACITY_CONTRACT["item_max_bytes"])
        if item_maximum is None
        else item_maximum
    )
    result = [_text(item, f"{label}_item", maximum=maximum) for item in value]
    if len(result) != len(set(result)):
        raise PlanCodecError("USER_PREPARATION_INVALID", f"{label}_duplicate")
    return result


def _closed(value: Any, expected: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PlanCodecError("USER_PREPARATION_INVALID", f"{label}_shape")
    return dict(value)


def _integer(value: Any, label: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlanCodecError("USER_PREPARATION_INVALID", f"{label}_not_integer")
    if value < minimum or value > maximum:
        raise PlanCodecError("RESOURCE_LIMIT_EXCEEDED", f"{label}_range")
    return value


def _canonicalize_plan_v1(value: Any) -> dict[str, Any]:
    """Validate the closed PlanDocument v1 shape and normalize semantic strings."""

    plan = _closed(value, PLAN_FIELDS, "plan")
    if plan["schema"] != PLAN_SCHEMA:
        raise PlanCodecError("USER_PREPARATION_INVALID", "plan_schema")
    source = _closed(plan["source"], SOURCE_FIELDS, "source")
    kind = source["kind"]
    if kind not in SOURCE_KINDS:
        raise PlanCodecError("USER_INPUT_INVALID", "plan_source_kind")
    source_digest = _text(source["source_digest"], "source_digest", maximum=64)
    if not re.fullmatch(r"[0-9a-f]{64}", source_digest):
        raise PlanCodecError("USER_PREPARATION_INVALID", "source_digest")
    if source["source_content_retained"] is not False:
        raise PlanCodecError("USER_PREPARATION_INVALID", "source_content_retained")

    boundaries = _closed(plan["boundaries"], BOUNDARY_FIELDS, "boundaries")
    if not isinstance(boundaries["destructive_actions_allowed"], bool):
        raise PlanCodecError(
            "USER_PREPARATION_INVALID", "destructive_actions_allowed"
        )
    limits = CAPACITY_CONTRACT["array_limits"]
    canonical_boundaries = {
        "destructive_actions_allowed": boundaries["destructive_actions_allowed"],
        "external_actions": _string_array(
            boundaries["external_actions"],
            "external_actions",
            maximum_items=int(limits["external_actions"]),
        ),
        "forbidden_actions": _string_array(
            boundaries["forbidden_actions"],
            "forbidden_actions",
            maximum_items=int(limits["forbidden_actions"]),
        ),
        "forbidden_paths": _string_array(
            boundaries["forbidden_paths"],
            "forbidden_paths",
            maximum_items=int(limits["forbidden_paths"]),
        ),
        "write_scope": _string_array(
            boundaries["write_scope"],
            "write_scope",
            maximum_items=int(limits["write_scope"]),
            allow_empty=False,
        ),
    }

    budget = _closed(plan["budget"], BUDGET_FIELDS, "budget")
    currency = budget["currency"]
    if currency is not None:
        currency = _text(currency, "currency", maximum=16).upper()
    canonical_budget = {
        "currency": currency,
        "max_cost_minor_units": _integer(
            budget["max_cost_minor_units"],
            "max_cost_minor_units",
            minimum=0,
            maximum=2**63 - 1,
        ),
        "max_host_invocations": _integer(
            budget["max_host_invocations"],
            "max_host_invocations",
            minimum=0,
            maximum=1_000_000,
        ),
        "wall_clock_seconds": _integer(
            budget["wall_clock_seconds"],
            "wall_clock_seconds",
            minimum=1,
            maximum=31_536_000,
        ),
    }
    if canonical_budget["max_cost_minor_units"] and currency is None:
        raise PlanCodecError("USER_PREPARATION_INVALID", "budget_currency_missing")

    roadmap = _closed(plan["roadmap_policy"], ROADMAP_FIELDS, "roadmap_policy")
    if roadmap["mode"] not in {"STANDARD", "ADAPTIVE"}:
        raise PlanCodecError("USER_PREPARATION_INVALID", "roadmap_mode")
    max_reorders = _integer(
        roadmap["max_reorders"], "max_reorders", minimum=0, maximum=16
    )
    if roadmap["mode"] == "STANDARD" and max_reorders != 0:
        raise PlanCodecError("USER_PREPARATION_INVALID", "standard_reorders")

    raw_goals = plan["goals"]
    if not isinstance(raw_goals, (list, tuple)):
        raise PlanCodecError("USER_PREPARATION_INVALID", "goals_not_array")
    goal_min = int(CAPACITY_CONTRACT["goal_count_min"])
    goal_max = V1_GOAL_COUNT_MAX
    if not goal_min <= len(raw_goals) <= goal_max:
        raise PlanCodecError("RESOURCE_LIMIT_EXCEEDED", "goal_count")
    goals: list[dict[str, Any]] = []
    for index, raw_goal in enumerate(raw_goals):
        goal = _closed(raw_goal, GOAL_FIELDS, f"goal_{index}")
        goal_id = _text(goal["goal_id"], f"goal_{index}_id", maximum=16)
        if not re.fullmatch(r"g[0-9]{3}", goal_id):
            raise PlanCodecError("USER_PREPARATION_INVALID", "goal_id_format")
        goals.append(
            {
                "acceptance_criteria": _string_array(
                    goal["acceptance_criteria"],
                    f"goal_{index}_acceptance",
                    maximum_items=int(limits["goal_acceptance_criteria"]),
                    allow_empty=False,
                ),
                "goal_id": goal_id,
                "objective": _text(
                    goal["objective"],
                    f"goal_{index}_objective",
                    maximum=V1_OBJECTIVE_MAX_BYTES,
                ),
            }
        )
    goal_ids = [goal["goal_id"] for goal in goals]
    if len(goal_ids) != len(set(goal_ids)):
        raise PlanCodecError("USER_PREPARATION_INVALID", "duplicate_goal_id")
    objective = _text(
        plan["objective"],
        "objective",
        maximum=V1_OBJECTIVE_MAX_BYTES,
    )
    if objective != goals[0]["objective"]:
        raise PlanCodecError("USER_PREPARATION_INVALID", "primary_goal_mismatch")
    completion = _string_array(
        plan["completion_evidence"],
        "completion_evidence",
        maximum_items=int(limits["completion_evidence"]),
        allow_empty=False,
    )
    stops = _string_array(
        plan["stop_conditions"],
        "stop_conditions",
        maximum_items=int(limits["stop_conditions"]),
        allow_empty=False,
    )
    normalized = {
        "boundaries": canonical_boundaries,
        "budget": canonical_budget,
        "completion_evidence": completion,
        "goals": goals,
        "objective": objective,
        "roadmap_policy": {"max_reorders": max_reorders, "mode": roadmap["mode"]},
        "schema": PLAN_SCHEMA,
        "source": {
            "kind": kind,
            "source_content_retained": False,
            "source_digest": source_digest,
        },
        "stop_conditions": stops,
    }
    raw = canonical_bytes(normalized)
    if len(raw) > V1_PLAN_MAX_BYTES:
        raise PlanCodecError("RESOURCE_LIMIT_EXCEEDED", "canonical_plan_bytes")
    if canonical_bytes(normalized) != raw:
        raise AssertionError("canonical encoder drift")
    return normalized


def _canonicalize_plan_v2(value: Any) -> dict[str, Any]:
    plan = _closed(value, PLAN_V2_FIELDS, "plan")
    if plan["schema"] != PLAN_SCHEMA_V2:
        raise PlanCodecError("USER_PREPARATION_INVALID", "plan_schema")

    source = _closed(plan["source"], SOURCE_FIELDS, "source")
    kind = source["kind"]
    if kind not in SOURCE_KINDS:
        raise PlanCodecError("USER_INPUT_INVALID", "plan_source_kind")
    source_digest = _text(source["source_digest"], "source_digest", maximum=64)
    if not re.fullmatch(r"[0-9a-f]{64}", source_digest):
        raise PlanCodecError("USER_PREPARATION_INVALID", "source_digest")
    if source["source_content_retained"] is not False:
        raise PlanCodecError("USER_PREPARATION_INVALID", "source_content_retained")

    boundaries = _closed(plan["boundaries"], BOUNDARY_FIELDS, "boundaries")
    if not isinstance(boundaries["destructive_actions_allowed"], bool):
        raise PlanCodecError(
            "USER_PREPARATION_INVALID", "destructive_actions_allowed"
        )
    limits = CAPACITY_CONTRACT["array_limits"]
    canonical_boundaries = {
        "destructive_actions_allowed": boundaries["destructive_actions_allowed"],
        "external_actions": _string_array(
            boundaries["external_actions"],
            "external_actions",
            maximum_items=int(limits["external_actions"]),
        ),
        "forbidden_actions": _string_array(
            boundaries["forbidden_actions"],
            "forbidden_actions",
            maximum_items=int(limits["forbidden_actions"]),
        ),
        "forbidden_paths": _string_array(
            boundaries["forbidden_paths"],
            "forbidden_paths",
            maximum_items=int(limits["forbidden_paths"]),
        ),
        "write_scope": _string_array(
            boundaries["write_scope"],
            "write_scope",
            maximum_items=int(limits["write_scope"]),
            allow_empty=False,
        ),
    }

    budget = _closed(plan["budget"], BUDGET_FIELDS, "budget")
    currency = budget["currency"]
    if currency is not None:
        currency = _text(currency, "currency", maximum=16).upper()
    canonical_budget = {
        "currency": currency,
        "max_cost_minor_units": _integer(
            budget["max_cost_minor_units"],
            "max_cost_minor_units",
            minimum=0,
            maximum=2**63 - 1,
        ),
        "max_host_invocations": _integer(
            budget["max_host_invocations"],
            "max_host_invocations",
            minimum=1,
            maximum=1_000_000,
        ),
        "wall_clock_seconds": _integer(
            budget["wall_clock_seconds"],
            "wall_clock_seconds",
            minimum=1,
            maximum=31_536_000,
        ),
    }
    if canonical_budget["max_cost_minor_units"] and currency is None:
        raise PlanCodecError("USER_PREPARATION_INVALID", "budget_currency_missing")

    roadmap = _closed(plan["roadmap_policy"], ROADMAP_FIELDS, "roadmap_policy")
    if roadmap["mode"] not in {"STANDARD", "ADAPTIVE"}:
        raise PlanCodecError("USER_PREPARATION_INVALID", "roadmap_mode")
    max_reorders = _integer(
        roadmap["max_reorders"], "max_reorders", minimum=0, maximum=16
    )
    if roadmap["mode"] == "STANDARD" and max_reorders != 0:
        raise PlanCodecError("USER_PREPARATION_INVALID", "standard_reorders")

    raw_requirements = plan["requirements"]
    if not isinstance(raw_requirements, Mapping) or len(raw_requirements) > int(
        limits["requirements"]
    ):
        raise PlanCodecError("RESOURCE_LIMIT_EXCEEDED", "requirements")
    requirements: dict[str, str] = {}
    for requirement_id, requirement_text in sorted(raw_requirements.items()):
        if not isinstance(requirement_id, str) or not re.fullmatch(
            r"r[0-9]{3}", requirement_id
        ):
            raise PlanCodecError("USER_PREPARATION_INVALID", "requirement_id")
        requirements[requirement_id] = _text(
            requirement_text,
            f"requirement_{requirement_id}",
            maximum=int(CAPACITY_CONTRACT["objective_max_bytes"]),
        )

    profile = _closed(plan["worker_profile"], WORKER_PROFILE_FIELDS, "worker_profile")
    if profile["sandbox"] != "workspace-write":
        raise PlanCodecError("USER_PREPARATION_INVALID", "worker_sandbox")
    if profile["reasoning_effort"] not in {"low", "medium", "high", "xhigh", "max"}:
        raise PlanCodecError("USER_PREPARATION_INVALID", "reasoning_effort")
    if not isinstance(profile["network_access"], bool) or not isinstance(
        profile["local_verification"], bool
    ):
        raise PlanCodecError("USER_PREPARATION_INVALID", "worker_boolean")
    worker_profile = {
        "attempt_timeout_seconds": _integer(
            profile["attempt_timeout_seconds"],
            "attempt_timeout_seconds",
            minimum=1,
            maximum=30_000,
        ),
        "local_verification": profile["local_verification"],
        "model": _text(profile["model"], "model", maximum=128),
        "network_access": profile["network_access"],
        "reasoning_effort": profile["reasoning_effort"],
        "sandbox": "workspace-write",
    }

    raw_goals = plan["goals"]
    if not isinstance(raw_goals, (list, tuple)) or not int(
        CAPACITY_CONTRACT["goal_count_min"]
    ) <= len(raw_goals) <= int(CAPACITY_CONTRACT["goal_count_max"]):
        raise PlanCodecError("RESOURCE_LIMIT_EXCEEDED", "goal_count")
    goals: list[dict[str, Any]] = []
    for index, raw_goal in enumerate(raw_goals):
        goal = _closed(raw_goal, GOAL_V2_FIELDS, f"goal_{index}")
        goal_id = _text(goal["goal_id"], f"goal_{index}_id", maximum=16)
        if not re.fullmatch(r"g[0-9]{3}", goal_id):
            raise PlanCodecError("USER_PREPARATION_INVALID", "goal_id_format")
        requirement_refs = _string_array(
            goal["requirement_refs"],
            f"goal_{index}_requirement_refs",
            maximum_items=int(limits["goal_requirement_refs"]),
        )
        if any(reference not in requirements for reference in requirement_refs):
            raise PlanCodecError(
                "USER_PREPARATION_INVALID", "unknown_requirement_ref"
            )
        requirement = goal["requirement"]
        gate = goal["gate"]
        on_failure = goal["on_failure"]
        on_blocked = goal["on_blocked"]
        recovery = goal["recovery_policy"]
        replay = goal["replay_safety"]
        if requirement not in {"required", "optional"}:
            raise PlanCodecError("USER_PREPARATION_INVALID", "goal_requirement")
        if gate not in {"worker", "human", "time"}:
            raise PlanCodecError("USER_PREPARATION_INVALID", "goal_gate")
        if on_failure not in {"repair", "wait", "fail"}:
            raise PlanCodecError("USER_PREPARATION_INVALID", "goal_on_failure")
        if on_blocked not in {"wait", "skip"}:
            raise PlanCodecError("USER_PREPARATION_INVALID", "goal_on_blocked")
        if requirement == "required" and on_blocked == "skip":
            raise PlanCodecError("USER_PREPARATION_INVALID", "required_goal_skip")
        if recovery not in {"resume", "reconcile", "human"}:
            raise PlanCodecError("USER_PREPARATION_INVALID", "goal_recovery_policy")
        if replay not in {"file_local", "idempotent", "non_replayable"}:
            raise PlanCodecError("USER_PREPARATION_INVALID", "goal_replay_safety")
        if gate != "worker" and recovery != "human":
            raise PlanCodecError("USER_PREPARATION_INVALID", "gate_recovery_policy")
        goals.append(
            {
                "acceptance_criteria": _string_array(
                    goal["acceptance_criteria"],
                    f"goal_{index}_acceptance",
                    maximum_items=int(limits["goal_acceptance_criteria"]),
                    allow_empty=False,
                ),
                "capabilities": _string_array(
                    goal["capabilities"],
                    f"goal_{index}_capabilities",
                    maximum_items=int(limits["goal_capabilities"]),
                ),
                "gate": gate,
                "goal_id": goal_id,
                "max_attempts": _integer(
                    goal["max_attempts"],
                    f"goal_{index}_max_attempts",
                    minimum=1,
                    maximum=3,
                ),
                "objective": _text(
                    goal["objective"],
                    f"goal_{index}_objective",
                    maximum=int(CAPACITY_CONTRACT["objective_max_bytes"]),
                ),
                "on_blocked": on_blocked,
                "on_failure": on_failure,
                "recovery_policy": recovery,
                "replay_safety": replay,
                "requirement": requirement,
                "requirement_refs": requirement_refs,
                "verifiers": _string_array(
                    goal["verifiers"],
                    f"goal_{index}_verifiers",
                    maximum_items=int(limits["goal_verifiers"]),
                    allow_empty=gate != "worker",
                    item_maximum=4096,
                ),
            }
        )
    goal_ids = [goal["goal_id"] for goal in goals]
    if len(goal_ids) != len(set(goal_ids)):
        raise PlanCodecError("USER_PREPARATION_INVALID", "duplicate_goal_id")
    if canonical_budget["max_host_invocations"] < sum(
        goal["max_attempts"] for goal in goals if goal["gate"] == "worker"
    ):
        raise PlanCodecError("USER_PREPARATION_INVALID", "host_budget_too_small")

    objective = _text(
        plan["objective"],
        "objective",
        maximum=int(CAPACITY_CONTRACT["objective_max_bytes"]),
    )
    if objective != goals[0]["objective"]:
        raise PlanCodecError("USER_PREPARATION_INVALID", "primary_goal_mismatch")
    normalized = {
        "boundaries": canonical_boundaries,
        "budget": canonical_budget,
        "completion_evidence": _string_array(
            plan["completion_evidence"],
            "completion_evidence",
            maximum_items=int(limits["completion_evidence"]),
            allow_empty=False,
        ),
        "goals": goals,
        "objective": objective,
        "requirements": requirements,
        "roadmap_policy": {"max_reorders": max_reorders, "mode": roadmap["mode"]},
        "schema": PLAN_SCHEMA_V2,
        "source": {
            "kind": kind,
            "source_content_retained": False,
            "source_digest": source_digest,
        },
        "stop_conditions": _string_array(
            plan["stop_conditions"],
            "stop_conditions",
            maximum_items=int(limits["stop_conditions"]),
            allow_empty=False,
        ),
        "worker_profile": worker_profile,
    }
    raw = canonical_bytes(normalized)
    if len(raw) > int(CAPACITY_CONTRACT["canonical_plan_max_bytes"]):
        raise PlanCodecError("RESOURCE_LIMIT_EXCEEDED", "canonical_plan_bytes")
    return normalized


def canonicalize_plan(value: Any) -> dict[str, Any]:
    """Validate a closed PlanDocument v1 or v2 without lossy migration."""

    if not isinstance(value, Mapping):
        raise PlanCodecError("USER_PREPARATION_INVALID", "plan_shape")
    schema = value.get("schema")
    if schema == PLAN_SCHEMA:
        return _canonicalize_plan_v1(value)
    if schema == PLAN_SCHEMA_V2:
        return _canonicalize_plan_v2(value)
    raise PlanCodecError("USER_PREPARATION_INVALID", "plan_schema")


def parse_plan_bytes(raw: bytes) -> dict[str, Any]:
    if len(raw) > int(CAPACITY_CONTRACT["canonical_plan_max_bytes"]):
        raise PlanCodecError("RESOURCE_LIMIT_EXCEEDED", "canonical_plan_bytes")
    try:
        value = parse_json_bytes(raw)
    except Exception as exc:
        raise PlanCodecError("USER_PREPARATION_INVALID", "plan_json") from exc
    normalized = canonicalize_plan(value)
    if canonical_bytes(normalized) != raw:
        raise PlanCodecError("USER_PREPARATION_INVALID", "plan_not_canonical")
    return normalized


def _legacy_budget(text: str, goal_count: int) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            value = parse_json_bytes(stripped.encode("utf-8"))
        except Exception as exc:
            raise PlanCodecError(
                "USER_CLARIFICATION_REQUIRED", "structured_budget_json"
            ) from exc
        if not isinstance(value, Mapping) or set(value) != BUDGET_FIELDS:
            raise PlanCodecError(
                "USER_CLARIFICATION_REQUIRED", "structured_budget_shape"
            )
        return dict(value)

    lower = stripped.casefold()
    number_words = {"one": 1, "two": 2, "three": 3, "four": 4}
    wall = 3600
    match = re.search(
        r"\b(\d+|one|two|three|four)\s*(minutes?|mins?|hours?|hrs?|days?)\b",
        lower,
    )
    if match:
        token = match.group(1)
        amount = int(token) if token.isdigit() else number_words[token]
        unit = match.group(2)
        wall = amount * (86_400 if unit.startswith("day") else 3_600 if unit.startswith(("hour", "hr")) else 60)
    else:
        match = re.search(r"(\d+)\s*(分钟|小时|天)", stripped)
        if match:
            amount = int(match.group(1))
            unit = match.group(2)
            wall = amount * (86_400 if unit == "天" else 3_600 if unit == "小时" else 60)
    invocations = goal_count
    match = re.search(
        r"\b(\d+|one|two|three|four)\s+(?:host\s+)?(?:invocations?|turns?|attempts?|calls?)\b",
        lower,
    )
    if match:
        token = match.group(1)
        invocations = int(token) if token.isdigit() else number_words[token]
    else:
        match = re.search(r"(?:最多|至多|不超过)?\s*(\d+)\s*次?\s*(?:Host|主机)\s*(?:调用|运行)", stripped, re.IGNORECASE)
        if match:
            invocations = int(match.group(1))
    positive_cost = re.search(
        r"(?:USD|CNY|RMB|[$¥￥])\s*[1-9]|[1-9][0-9]*(?:\.[0-9]+)?\s*(?:元|美元|人民币)",
        stripped,
        re.IGNORECASE,
    )
    if positive_cost:
        raise PlanCodecError(
            "USER_CLARIFICATION_REQUIRED", "structured_cost_budget_required"
        )
    return {
        "currency": None,
        "max_cost_minor_units": 0,
        "max_host_invocations": invocations,
        "wall_clock_seconds": max(1, wall),
    }


def legacy_plan_from_request(request: Any) -> dict[str, Any]:
    goals = [str(item) for item in request.goal_plan]
    source_value = {
        "acceptance_criteria": list(request.acceptance_criteria),
        "authorization_boundaries": list(request.authorization_boundaries),
        "budget": request.budget,
        "external_actions": list(request.external_actions),
        "goal": request.goal,
        "goal_plan": goals,
        "stop_conditions": list(request.stop_conditions),
        "task_horizon": request.task_horizon,
        "write_scope": list(request.write_scope),
    }
    source_digest = request.source_digest
    if not isinstance(source_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", source_digest):
        source_digest = raw_domain_digest(
            "loopskill-prd-source-v1\n", canonical_bytes(source_value)
        )
    mode = "ADAPTIVE" if str(request.task_horizon).strip().casefold() == "adaptive" else "STANDARD"
    acceptance = list(request.acceptance_criteria)
    boundary_values = [str(item) for item in request.authorization_boundaries]
    forbidden_paths = [
        item.split(":", 1)[1]
        for item in boundary_values
        if item.casefold().startswith("forbidden_path:")
    ]
    forbidden_actions = [
        item
        for item in boundary_values
        if not item.casefold().startswith(("forbidden_path:", "destructive:"))
    ]
    plan = {
        "boundaries": {
            "destructive_actions_allowed": any(
                "destructive:allowed" in str(item).casefold()
                for item in request.authorization_boundaries
            ),
            "external_actions": list(request.external_actions),
            "forbidden_actions": forbidden_actions,
            "forbidden_paths": forbidden_paths,
            "write_scope": list(request.write_scope),
        },
        "budget": _legacy_budget(str(request.budget), len(goals)),
        "completion_evidence": acceptance,
        "goals": [
            {
                "acceptance_criteria": acceptance,
                "goal_id": f"g{index:03d}",
                "objective": objective,
            }
            for index, objective in enumerate(goals)
        ],
        "objective": request.goal,
        "roadmap_policy": {"max_reorders": 4 if mode == "ADAPTIVE" else 0, "mode": mode},
        "schema": PLAN_SCHEMA,
        "source": {
            "kind": request.source_kind,
            "source_content_retained": False,
            "source_digest": source_digest,
        },
        "stop_conditions": list(request.stop_conditions),
    }
    return canonicalize_plan(plan)


def goal_slice_digest(goal: Mapping[str, Any]) -> str:
    expected = GOAL_V2_FIELDS if set(goal) == GOAL_V2_FIELDS else GOAL_FIELDS
    closed = _closed(goal, expected, "goal_slice")
    return raw_domain_digest(
        (
            "loopskill-goal-slice-v2\n"
            if expected == GOAL_V2_FIELDS
            else "loopskill-goal-slice-v1\n"
        ),
        canonical_bytes(closed),
    )


def plan_digest(plan_bytes: bytes) -> str:
    return raw_domain_digest("loopskill-blob-v1\n", plan_bytes)


def build_plan_index(
    plan: Mapping[str, Any],
    *,
    plan_identity: str,
    workspace_binding: str,
    authority_digest: str,
    revision: int = 0,
    ordered_goal_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    goals = {str(goal["goal_id"]): dict(goal) for goal in plan["goals"]}
    order = list(goals) if ordered_goal_ids is None else list(ordered_goal_ids)
    if len(order) != len(goals) or len(set(order)) != len(order) or set(order) != set(goals):
        raise PlanCodecError("USER_PREPARATION_INVALID", "plan_index_goal_set")
    value = {
        "authority_digest": _text(authority_digest, "authority_digest", maximum=64),
        "capacity_contract_version": (
            CAPACITY_CONTRACT["version"]
            if plan["schema"] == PLAN_SCHEMA_V2
            else "loopskill-capacity-v1"
        ),
        "goal_count": len(order),
        "ordered_goal_ids": order,
        "ordered_goal_slice_digests": [goal_slice_digest(goals[item]) for item in order],
        "plan_digest": _text(plan_identity, "plan_digest", maximum=64),
        "revision": _integer(revision, "plan_revision", minimum=0, maximum=2**31 - 1),
        "schema": (
            PLAN_INDEX_SCHEMA_V2
            if plan["schema"] == PLAN_SCHEMA_V2
            else PLAN_INDEX_SCHEMA
        ),
        "workspace_binding": _text(
            workspace_binding, "workspace_binding", maximum=256
        ),
    }
    validate_plan_index(value, plan)
    return value


def validate_plan_index(index: Any, plan: Mapping[str, Any]) -> dict[str, Any]:
    value = _closed(index, INDEX_FIELDS, "plan_index")
    expected_schema = (
        PLAN_INDEX_SCHEMA_V2
        if plan.get("schema") == PLAN_SCHEMA_V2
        else PLAN_INDEX_SCHEMA
    )
    expected_capacity = (
        CAPACITY_CONTRACT["version"]
        if plan.get("schema") == PLAN_SCHEMA_V2
        else "loopskill-capacity-v1"
    )
    if value["schema"] != expected_schema:
        raise PlanCodecError("USER_PREPARATION_INVALID", "plan_index_schema")
    if value["capacity_contract_version"] != expected_capacity:
        raise PlanCodecError("USER_PREPARATION_INVALID", "capacity_contract_version")
    plan_raw = canonical_bytes(canonicalize_plan(plan))
    if value["plan_digest"] != plan_digest(plan_raw):
        raise PlanCodecError("USER_PREPARATION_INVALID", "plan_digest_mismatch")
    ids = value["ordered_goal_ids"]
    digests = value["ordered_goal_slice_digests"]
    count = value["goal_count"]
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or not isinstance(ids, (list, tuple))
        or not isinstance(digests, (list, tuple))
        or len(ids) != count
        or len(digests) != count
        or len(set(ids)) != count
    ):
        raise PlanCodecError("USER_PREPARATION_INVALID", "plan_index_lengths")
    goals = {goal["goal_id"]: goal for goal in plan["goals"]}
    if set(ids) != set(goals):
        raise PlanCodecError("USER_PREPARATION_INVALID", "plan_index_goal_set")
    expected = [goal_slice_digest(goals[goal_id]) for goal_id in ids]
    if list(digests) != expected:
        raise PlanCodecError("USER_PREPARATION_INVALID", "goal_slice_digest_mismatch")
    _integer(value["revision"], "plan_revision", minimum=0, maximum=2**31 - 1)
    _text(value["workspace_binding"], "workspace_binding", maximum=256)
    for name in ("plan_digest", "authority_digest"):
        digest = _text(value[name], name, maximum=64)
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise PlanCodecError("USER_PREPARATION_INVALID", name)
    return {
        "authority_digest": value["authority_digest"],
        "capacity_contract_version": value["capacity_contract_version"],
        "goal_count": count,
        "ordered_goal_ids": list(ids),
        "ordered_goal_slice_digests": list(digests),
        "plan_digest": value["plan_digest"],
        "revision": value["revision"],
        "schema": value["schema"],
        "workspace_binding": value["workspace_binding"],
    }


def compile_plan(
    request: Any,
    *,
    loop_ref: str,
    workspace_binding: str,
    authority_digest: str | None = None,
) -> CompiledPlan:
    if request.canonical_plan is None:
        plan = legacy_plan_from_request(request)
    else:
        plan = canonicalize_plan(request.canonical_plan)
        source = plan["source"]
        if (
            source["kind"] != request.source_kind
            or source["source_digest"] != request.source_digest
        ):
            raise PlanCodecError(
                "USER_PREPARATION_INVALID", "source_binding_mismatch"
            )
    raw = canonical_bytes(plan)
    identity = plan_digest(raw)
    if authority_digest is None:
        authority_digest = authority_binding_digest(
            loop_ref=loop_ref,
            plan_identity=identity,
            goal_count=len(plan["goals"]),
            workspace_binding=workspace_binding,
            roadmap_mode=str(plan["roadmap_policy"]["mode"]),
        )
    slices = tuple(goal_slice_digest(goal) for goal in plan["goals"])
    index = build_plan_index(
        plan,
        plan_identity=identity,
        workspace_binding=workspace_binding,
        authority_digest=authority_digest,
    )
    index_raw = canonical_bytes(index)
    return CompiledPlan(
        plan=plan,
        plan_bytes=raw,
        plan_digest=identity,
        goal_slice_digests=slices,
        index=index,
        index_bytes=index_raw,
        index_digest=plan_digest(index_raw),
    )


def authority_binding_digest(
    *,
    loop_ref: str,
    plan_identity: str,
    goal_count: int,
    workspace_binding: str,
    roadmap_mode: str,
) -> str:
    """Bind the complete immutable v4.1 actor/grant policy before confirmation."""

    roles = authority_role_policy()
    return domain_digest(
        "loopskill-authority-context-v1\n",
        {
            "goal_count": goal_count,
            "issuer": "loopskill-local-authority-v1",
            "loop_ref": loop_ref,
            "plan_digest": plan_identity,
            "roadmap_mode": roadmap_mode,
            "roles": roles,
            "selector": {
                "goal_index_max": goal_count - 1,
                "goal_index_min": 0,
                "include_loop_scope": True,
                "mode": "PLAN_DERIVED_V1",
                "plan_digest": plan_identity,
            },
            "workspace_binding": workspace_binding,
        },
    )


def authority_role_policy() -> dict[str, dict[str, Any]]:
    return {
        "artifact": {
            "actor": "verifier",
            "commands": ("AcknowledgeResult",),
            "include_loop_scope": False,
            "kinds": ("ResultRef",),
        },
        "close": {
            "actor": "system",
            "commands": ("CloseExecution", "StrengthenClosureAssurance"),
            "include_loop_scope": True,
            "kinds": ("FinalizationRef",),
        },
        "create": {
            "actor": "author",
            "commands": ("CreateLoop",),
            "include_loop_scope": True,
            "kinds": ("LoopRef",),
        },
        "lifecycle": {
            "actor": "author",
            "commands": (
                "AdvanceGoal",
                "PauseLoop",
                "PrepareFinalization",
                "RecordPolicyDecision",
                "ResumeLoop",
                "ReviseGoalPlan",
                "StopLoop",
            ),
            "include_loop_scope": True,
            "kinds": ("ResultRef", "GoalRef", "LoopRef"),
        },
        "observe": {
            "actor": "system",
            "commands": ("RecordExternalEffectObservation",),
            "include_loop_scope": False,
            "kinds": ("ExternalEffectRef",),
        },
        "reviewer": {
            "actor": "reviewer",
            "commands": ("RecordReview",),
            "include_loop_scope": False,
            "kinds": ("ResultRef",),
        },
        "worker": {
            "actor": "system",
            "commands": ("StageExternalResult",),
            "include_loop_scope": False,
            "kinds": ("ExternalEffectRef",),
        },
    }


def control_identity(namespace: str, label: str) -> str:
    return domain_digest(
        "loopskill-local-control-id-v1\n",
        {"label": label, "namespace": namespace},
    )[:24]


def content_create_payload(
    plan: Mapping[str, Any], index: Mapping[str, Any], index_digest: str
) -> dict[str, Any]:
    verified = validate_plan_index(index, plan)
    first_id = verified["ordered_goal_ids"][0]
    first = next(goal for goal in plan["goals"] if goal["goal_id"] == first_id)
    budget = plan["budget"]
    payload = {
        "acceptance_criteria": [],
        "active_index": 0,
        "authority_digest": verified["authority_digest"],
        "authorization_boundaries": [],
        "budget": domain_digest("loopskill-plan-budget-v1\n", budget),
        "execution_mode": plan["roadmap_policy"]["mode"],
        "external_actions": [],
        "capacity_contract_version": CAPACITY_CONTRACT["version"],
        "goal_count": verified["goal_count"],
        "goal_id": first_id,
        "goal_plan": [first["objective"]],
        "goal_slice_digest": verified["ordered_goal_slice_digests"][0],
        "max_roadmap_revisions": int(plan["roadmap_policy"]["max_reorders"]) + 1,
        "max_cost_minor_units": int(budget["max_cost_minor_units"]),
        "max_host_invocations": int(budget["max_host_invocations"]),
        "objective": first["objective"],
        "ordered_goal_ids": list(verified["ordered_goal_ids"]),
        "ordered_goal_slice_digests": list(
            verified["ordered_goal_slice_digests"]
        ),
        "plan_digest": verified["plan_digest"],
        "plan_index_digest": index_digest,
        "plan_revision": verified["revision"],
        "stop_conditions": [],
        "stop_policy_digest": domain_digest(
            "loopskill-plan-stop-policy-v1\n", plan["stop_conditions"]
        ),
        "storage_mode": CONTENT_STORAGE_MODE,
        "wall_clock_seconds": int(budget["wall_clock_seconds"]),
        "workspace_binding": verified["workspace_binding"],
        "write_scope": [],
    }
    if plan["schema"] == PLAN_SCHEMA_V2:
        payload.update(
            {
                "goal_requirement": first["requirement"],
                "max_attempts": int(first["max_attempts"]),
            }
        )
    return payload


def content_create_command(
    *,
    namespace: str,
    loop_ref: str,
    compiled: CompiledPlan,
    issued_at: str,
    confirmation_receipt_ref: str,
    manifest_digest: str,
    boundary_digest: str,
    bundle_digest: str,
    artifact_profile: str,
    artifact_baseline_blob_digest: str | None,
) -> CommandEnvelope:
    first_id = str(compiled.index["ordered_goal_ids"][0])
    first_slice = str(compiled.index["ordered_goal_slice_digests"][0])
    chain = goal_chain(loop_ref, compiled.plan_digest, first_id, first_slice)
    author_ref = f"actor-author-{control_identity(namespace, 'author')}"
    create_grant_ref = f"grant-create-{control_identity(namespace, 'create-grant')}"
    operation_id = "operation-create-" + control_identity(namespace, "create-operation")
    provider_request = materialize_provider_request(
        compiled.plan,
        compiled.index,
        0,
        target_ref=chain["provider_target"],
        artifact_digest=artifact_baseline_blob_digest or "UNBOUND",
        prior_disposition="",
    )
    provider_request_digest = domain_digest(
        "loopskill-provider-request-v1\n", provider_request
    )
    return build_command(
        operation_id=operation_id,
        command_type="CreateLoop",
        actor_ref=author_ref,
        authority_grant_ref=create_grant_ref,
        subject={
            "loop_ref": loop_ref,
            "subject_kind": "LoopRef",
            "subject_ref": loop_ref,
        },
        expected_loop_revision=0,
        expected_subject_revisions={},
        issued_at=issued_at,
        machine_bindings={
            "allocate_refs": {
                "new_attempt_ref": chain["attempt_ref"],
                "new_external_effect_ref": chain["external_effect_ref"],
                "new_goal_ref": chain["goal_ref"],
                "new_host_resource_ref": chain["host_resource_ref"],
                "provider_idempotency_key": chain["provider_key"],
            },
            "receipt_refs": {"receipt": confirmation_receipt_ref},
            "resolved_refs": {
                "boundary_digest": boundary_digest,
                "plan_digest": compiled.plan_digest,
                "plan_index_digest": compiled.index_digest,
                "prepared_bundle_digest": bundle_digest,
                "prepared_manifest_digest": manifest_digest,
                "provider_action": "create_task",
                "provider_request_digest": provider_request_digest,
                "target_ref": chain["provider_target"],
                **(
                    {
                        "artifact_baseline_blob_digest": artifact_baseline_blob_digest,
                        "artifact_profile": artifact_profile,
                        "workspace_identity_digest": str(
                            compiled.index["workspace_binding"]
                        ),
                    }
                    if artifact_baseline_blob_digest is not None
                    else {}
                ),
            },
        },
        semantic_payload=content_create_payload(
            compiled.plan, compiled.index, compiled.index_digest
        ),
    )


def derive_plan_ref(
    loop_ref: str,
    plan_identity: str,
    goal_id: str,
    slice_digest: str,
    reference_kind: str,
) -> str:
    try:
        return _derive_plan_ref(
            loop_ref, plan_identity, goal_id, slice_digest, reference_kind
        )
    except ValueError as exc:
        raise PlanCodecError("USER_PREPARATION_INVALID", "reference_kind") from exc


def derive_loop_plan_ref(loop_ref: str, plan_identity: str, reference_kind: str) -> str:
    try:
        return _derive_loop_plan_ref(loop_ref, plan_identity, reference_kind)
    except ValueError as exc:
        raise PlanCodecError("USER_PREPARATION_INVALID", "loop_reference_kind") from exc


def goal_chain(
    loop_ref: str,
    plan_identity: str,
    goal_id: str,
    slice_digest: str,
) -> dict[str, str]:
    return _goal_chain(loop_ref, plan_identity, goal_id, slice_digest)


def repair_chain(
    loop_ref: str,
    plan_identity: str,
    goal_ref: str,
    goal_id: str,
    repair_ordinal: int,
) -> dict[str, str]:
    """Derive one non-colliding, plan-bound repair chain for an active Goal."""

    if repair_ordinal < 1 or repair_ordinal > 2:
        raise PlanCodecError("RESOURCE_LIMIT_EXCEEDED", "repair_ordinal")
    identity = domain_digest(
        "loopskill-repair-chain-v1\n",
        {
            "goal_id": goal_id,
            "goal_ref": goal_ref,
            "loop_ref": loop_ref,
            "plan_digest": plan_identity,
            "repair_ordinal": repair_ordinal,
        },
    )
    suffix = identity[:24]
    return {
        "artifact_ref": f"artifact-{suffix}",
        "attempt_ref": f"attempt-{suffix}",
        "external_effect_ref": f"external-effect-{suffix}",
        "goal_ref": goal_ref,
        "host_resource_ref": f"host-target-{suffix}",
        "provider_key": domain_digest(
            "loopskill-provider-idempotency-v1\n", {"repair_chain": identity}
        ),
        "provider_target": f"host-target-{suffix}",
        "report_ref": f"report-{suffix}",
        "result_ref": f"result-{suffix}",
        "review_ref": f"review-{suffix}",
    }


def materialize_provider_request(
    plan: Mapping[str, Any],
    index: Mapping[str, Any],
    goal_index: int,
    *,
    target_ref: str,
    artifact_digest: str,
    prior_disposition: str,
) -> dict[str, Any]:
    verified_index = validate_plan_index(index, plan)
    if goal_index < 0 or goal_index >= verified_index["goal_count"]:
        raise PlanCodecError("USER_PREPARATION_INVALID", "active_index")
    goal_id = verified_index["ordered_goal_ids"][goal_index]
    goals = {goal["goal_id"]: goal for goal in plan["goals"]}
    goal = goals[goal_id]
    boundaries = plan["boundaries"]
    request = {
        "acceptance_criteria": list(goal["acceptance_criteria"]),
        "artifact_digest": artifact_digest,
        "authorization_boundaries": {
            "destructive_actions_allowed": boundaries["destructive_actions_allowed"],
            "forbidden_actions": list(boundaries["forbidden_actions"]),
            "forbidden_paths": list(boundaries["forbidden_paths"]),
        },
        "budget": dict(plan["budget"]),
        "execution_mode": plan["roadmap_policy"]["mode"],
        "external_actions": list(boundaries["external_actions"]),
        "goal": goal["objective"],
        "goal_id": goal_id,
        "prior_disposition": prior_disposition,
        "stop_conditions": list(plan["stop_conditions"]),
        "target_ref": target_ref,
        "workspace_digest": verified_index["workspace_binding"],
        "write_scope": list(boundaries["write_scope"]),
    }
    if plan["schema"] == PLAN_SCHEMA_V2:
        requirement_refs = list(goal["requirement_refs"])
        request.update(
            {
                "capabilities": list(goal["capabilities"]),
                "goal_policy": {
                    "gate": goal["gate"],
                    "max_attempts": goal["max_attempts"],
                    "on_blocked": goal["on_blocked"],
                    "on_failure": goal["on_failure"],
                    "recovery_policy": goal["recovery_policy"],
                    "replay_safety": goal["replay_safety"],
                    "requirement": goal["requirement"],
                },
                "requirements": [
                    {"requirement_id": reference, "text": plan["requirements"][reference]}
                    for reference in requirement_refs
                ],
                "verifiers": list(goal["verifiers"]),
                "worker_profile": dict(plan["worker_profile"]),
            }
        )
    return request


def max_collection_members(value: Any) -> int:
    if isinstance(value, Mapping):
        return max([len(value), *(max_collection_members(item) for item in value.values())])
    if isinstance(value, (list, tuple)):
        return max([len(value), *(max_collection_members(item) for item in value)], default=0)
    return 0
