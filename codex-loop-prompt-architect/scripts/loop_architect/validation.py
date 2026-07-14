"""Adaptive input normalization and validation."""

from __future__ import annotations

import fnmatch
import re
from pathlib import PurePosixPath
from typing import Any

from .forecast import duration_minutes, local_verifier_needed
from .schema import (
    COORDINATION_MODES,
    DASHBOARD_POLICIES,
    DELEGATION_POLICIES,
    LOCAL_VERIFICATION_POLICIES,
    MILESTONE_FIELDS,
    MILESTONE_STATUSES,
    NATIVE_GOAL_POLICIES,
    ROLE_KINDS,
    SAFE_GOAL_ID_PATTERN,
    SAFE_MILESTONE_ID_PATTERN,
)


SAFE_GOAL_ID_RE = re.compile(SAFE_GOAL_ID_PATTERN)
SAFE_MILESTONE_ID_RE = re.compile(SAFE_MILESTONE_ID_PATTERN)
SAFE_ID_RE = SAFE_MILESTONE_ID_RE

ADAPTIVE_TRANSPORT_CONTRACT_MARKERS = (
    "Universal runtime transport contract",
    "every `adaptive_state_runtime.py` mode",
    "`tty:false`",
    "launch the runtime itself first",
    "Never place a stdin helper, shell wrapper, pipeline, heredoc, `dd`, `stty`, or fixed-byte reader before the runtime process.",
    "write one compact JSON frame exactly once",
    "`exit_code=0`",
    "no longer returns `session_id`",
    "single `PAYLOAD_MATERIALIZED`",
    "Do not use `dd`, `stty`, fixed-byte readers, heredocs, or any extra shell pipeline.",
    "`PAYLOAD_MATERIALIZATION_TRANSPORT_TIMEOUT`",
)


def validate_adaptive_pack_transport_contract(pack: str) -> list[str]:
    """Reject an Adaptive Pack that weakens any runtime transport contract."""

    errors = [
        f"adaptive_transport_contract:missing:{marker}"
        for marker in ADAPTIVE_TRANSPORT_CONTRACT_MARKERS
        if marker not in pack
    ]
    unsafe_patterns = (
        r"\btty\s*:\s*true\b",
        r"\bstty\s+-",
        r"\bdd\s+[^\n]*\bbs\s*=",
        r"stdin\.buffer\.read\s*\(\s*[1-9]",
        r"<<\s*['\"]?[A-Za-z_][A-Za-z0-9_]*",
        r"\|\s*(?:python3?\s+)?[^\n]*adaptive_state_runtime\.py",
    )
    for line in pack.splitlines():
        lowered = line.lower()
        if not (
            any(token in lowered for token in ("`dd`", "`stty`", "heredoc"))
            or any(re.search(pattern, lowered) for pattern in unsafe_patterns)
        ):
            continue
        if not any(
            guard in lowered
            for guard in (
                "do not use",
                "never use",
                "never place",
                "禁止",
                "不得",
            )
        ):
            errors.append("adaptive_transport_contract:unsafe_shell_transport")
            break
    return errors


def _role_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9㐀-鿿]+", "", str(value).lower())


def _permission_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        _role_key(role): permission
        for role, permission in value.items()
        if isinstance(permission, str)
    }


def _string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _clean_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def infer_legacy_role_kind(role: str, permission: str = "") -> str:
    """Infer only for backwards compatibility; Adaptive input stays explicit."""

    key = re.sub(r"[^a-z0-9\u3400-\u9fff]+", "-", role.lower()).strip("-")
    if permission == "state_write_only" or any(term in key for term in ("state-writer", "statewriter", "状态")):
        return "state_writer"
    if any(term in key for term in ("local-verifier", "local-verification", "本机验证", "真实环境验证")):
        return "local_verifier"
    if any(term in key for term in ("reviewer", "verifier", "auditor", "code-review", "审查", "评审", "审核", "裁判")):
        return "code_reviewer"
    if any(term in key for term in ("triage", "分诊")):
        return "triage"
    if any(term in key for term in ("explorer", "discovery", "探索", "发现")):
        return "explorer"
    return "implementation"


def normalize_milestones(value: Any) -> list[dict[str, Any]]:
    """Normalize already-validated milestones without stringifying invalid objects."""

    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        result.append(
            {
                "milestone_id": _clean_string(raw.get("milestone_id")),
                "outcome": _clean_string(raw.get("outcome")),
                "scope": _string_list(raw.get("scope")),
                "decisions": _string_list(raw.get("decisions")),
                "blockers": _string_list(raw.get("blockers")),
                "required_evidence": _string_list(raw.get("required_evidence")),
                "status": _clean_string(raw.get("status")) or "PLANNED",
                "depends_on": _string_list(raw.get("depends_on")),
                "references": _string_list(raw.get("references")),
            }
        )
    return result


def _has_dependency_cycle(milestones: list[dict[str, Any]]) -> bool:
    graph = {item["milestone_id"]: set(item["depends_on"]) for item in milestones if item["milestone_id"]}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for dependency in graph.get(node, set()):
            if dependency in graph and visit(dependency):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def _string_list_is_valid(
    value: Any,
    *,
    allow_string: bool,
    allow_empty: bool = False,
) -> bool:
    if allow_string and isinstance(value, str):
        return bool(value.strip())
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _repo_relative_scope(repo: str, value: str) -> str | None:
    if not repo or not PurePosixPath(repo).is_absolute() or not value.strip():
        return None
    candidate = PurePosixPath(value.strip())
    if ".." in candidate.parts:
        return None
    if candidate.is_absolute():
        try:
            candidate = candidate.relative_to(PurePosixPath(repo))
        except ValueError:
            return None
    if not candidate.parts or candidate.parts[0] == ".codex-loop":
        return None
    return candidate.as_posix().removeprefix("./")


def _scope_is_within(repo: str, child: str, parent: str) -> bool:
    child_scope = _repo_relative_scope(repo, child)
    parent_scope = _repo_relative_scope(repo, parent)
    if not child_scope or not parent_scope:
        return False
    if parent_scope in {".", "**", "**/*"}:
        return True
    if parent_scope.endswith("/**"):
        base = parent_scope[:-3].rstrip("/")
        return child_scope == base or child_scope.startswith(f"{base}/")
    if any(char in parent_scope for char in "*?["):
        if any(char in child_scope for char in "*?["):
            return child_scope == parent_scope
        child_parts = PurePosixPath(child_scope).parts
        parent_parts = PurePosixPath(parent_scope).parts
        return len(child_parts) == len(parent_parts) and all(
            fnmatch.fnmatchcase(child_part, parent_part)
            for child_part, parent_part in zip(child_parts, parent_parts)
        )
    return child_scope == parent_scope or child_scope.startswith(f"{parent_scope}/")


def _bounded_int(value: Any, minimum: int, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum


def _integer_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def minimum_adaptive_routing_turns(data: dict[str, Any]) -> int | None:
    """Return the bounded route capacity needed to exercise declared repair limits.

    This counts external route actions, not state-only mutations. Invalid or
    incomplete Adaptive input is left to the surrounding schema validation.
    """

    raw_goals = data.get("goals")
    raw_milestones = data.get("milestones")
    max_repairs = _integer_value(data.get("max_repair_attempts_per_goal", 5))
    if (
        not isinstance(raw_goals, list)
        or not raw_goals
        or any(not isinstance(goal, dict) for goal in raw_goals)
        or not isinstance(raw_milestones, list)
        or not raw_milestones
        or any(not isinstance(milestone, dict) for milestone in raw_milestones)
        or max_repairs is None
        or max_repairs < 0
    ):
        return None

    routable_milestone_ids: set[str] = set()
    for milestone in raw_milestones:
        milestone_id = milestone.get("milestone_id")
        status = milestone.get("status")
        if not isinstance(milestone_id, str) or not isinstance(status, str):
            return None
        if status in {"ACTIVE", "PLANNED"} and milestone_id:
            routable_milestone_ids.add(milestone_id)

    routable_goals: list[dict[str, Any]] = []
    worker_roles: set[str] = set()
    for goal in raw_goals:
        milestone_id = goal.get("milestone_id")
        worker_role = goal.get("worker_role") or goal.get("role")
        if not isinstance(milestone_id, str) or not isinstance(worker_role, str):
            return None
        if milestone_id in routable_milestone_ids:
            routable_goals.append(goal)
            role = _role_key(worker_role)
            if not role:
                return None
            worker_roles.add(role)
    goal_count = len(routable_goals)
    milestone_count = len(routable_milestone_ids)
    if not goal_count or not milestone_count or not worker_roles:
        return None

    try:
        needs_local_verifier = local_verifier_needed(data)
    except (TypeError, ValueError):
        return None

    # JIT formal tasks: execution role(s), one Reviewer, and optional Local Verifier.
    task_routes = len(worker_roles) + 1 + int(needs_local_verifier)
    # One business heartbeat plus the initial native Controller Goal.
    bootstrap_routes = 2
    # Each later milestone completes the old native Goal and creates the new one.
    milestone_goal_routes = 2 * (milestone_count - 1)
    # Every initial/repair Worker dispatch is followed by CODE_REVIEW. Local
    # verification repeats for the same item after repair when it is required.
    attempt_count = goal_count * (1 + max_repairs)
    goal_routes = attempt_count * (2 + int(needs_local_verifier))
    # One ROADMAP_AUDIT per milestone, then FINAL_AUDIT and FINALIZE_LOOP.
    # A bounded repair triggered by ROADMAP_AUDIT or FINAL_AUDIT must rerun
    # that exact assurance stage after Worker repair and CODE_REVIEW.
    assurance_routes = milestone_count + 2 + (2 * goal_count * max_repairs)
    return (
        task_routes
        + bootstrap_routes
        + milestone_goal_routes
        + goal_routes
        + assurance_routes
    )


def adaptive_validation_errors(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    mode = data.get("coordination_mode", "standard")
    if not isinstance(mode, str) or mode not in COORDINATION_MODES:
        return ["coordination_mode:must_be_standard_or_adaptive"]
    if mode != "adaptive":
        return errors

    reason = data.get("adaptive_reason")
    if not isinstance(reason, str) or not reason.strip():
        errors.append("adaptive_reason:required_for_adaptive")

    raw_workers = data.get("workers")
    top_level_permissions = _permission_map(data.get("permissions"))
    role_kinds_by_role: dict[str, str] = {}
    if not isinstance(raw_workers, list) or not raw_workers or any(not isinstance(worker, dict) for worker in raw_workers):
        errors.append("workers:structured_objects_required_for_adaptive")
    else:
        for index, worker in enumerate(raw_workers, 1):
            role_kind = worker.get("role_kind")
            if not isinstance(role_kind, str) or role_kind not in ROLE_KINDS:
                errors.append(f"workers:{index}:role_kind_required_for_adaptive")
                continue
            role_kinds_by_role[_role_key(worker.get("role"))] = role_kind
            permission = (
                worker.get("permission")
                or worker.get("sandbox")
                or top_level_permissions.get(_role_key(worker.get("role")))
            )
            if not permission:
                permission = (
                    "state_write_only"
                    if role_kind == "state_writer"
                    else "read_only"
                    if role_kind in {"code_reviewer", "local_verifier", "triage", "explorer"}
                    else "workspace_write"
                )
            if role_kind in {"code_reviewer", "local_verifier", "triage", "explorer"} and permission not in {None, "", "read_only"}:
                errors.append(f"workers:{index}:{role_kind}_must_be_read_only")
            if role_kind == "state_writer" and permission not in {None, "", "state_write_only"}:
                errors.append(f"workers:{index}:state_writer_must_be_state_write_only")
            if role_kind != "state_writer" and permission == "state_write_only":
                errors.append(f"workers:{index}:state_write_only_reserved_for_state_writer")

    raw_milestones = data.get("milestones")
    if not isinstance(raw_milestones, list) or not raw_milestones:
        errors.append("milestones:nonempty_array_required_for_adaptive")
        return errors

    repo = data.get("repo") if isinstance(data.get("repo"), str) else ""
    global_scopes = _string_list(data.get("allowed"))
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_milestones, 1):
        if not isinstance(raw, dict):
            errors.append(f"milestones:{index}:must_be_object")
            continue
        for key in sorted(set(raw) - MILESTONE_FIELDS):
            errors.append(f"milestones:{index}:unknown_field:{key}")
        for key in ("milestone_id", "outcome", "status"):
            if not isinstance(raw.get(key), str) or not raw[key].strip():
                errors.append(f"milestones:{index}:{key}:must_be_nonempty_string")
        for key in ("scope", "required_evidence"):
            if not _string_list_is_valid(raw.get(key), allow_string=True):
                errors.append(f"milestones:{index}:{key}:must_be_string_or_string_array")
        for key in ("decisions", "blockers", "depends_on", "references"):
            if key in raw and not _string_list_is_valid(
                raw.get(key), allow_string=False, allow_empty=True
            ):
                errors.append(f"milestones:{index}:{key}:must_be_string_array")
        for key in ("depends_on", "references"):
            values = _string_list(raw.get(key))
            if len(values) != len(set(values)):
                errors.append(f"milestones:{index}:{key}:duplicates_not_allowed")
        if isinstance(raw.get("status"), str) and raw["status"] not in MILESTONE_STATUSES:
            errors.append(f"milestones:{index}:invalid_status")
        milestone_id = raw.get("milestone_id")
        if isinstance(milestone_id, str) and not SAFE_MILESTONE_ID_RE.fullmatch(milestone_id):
            errors.append(f"milestones:{index}:unsafe_milestone_id")
        for scope in _string_list(raw.get("scope")):
            if not _repo_relative_scope(repo, scope):
                errors.append(f"milestones:{index}:scope_outside_repo:{scope}")
            elif global_scopes and not any(
                _scope_is_within(repo, scope, parent) for parent in global_scopes
            ):
                errors.append(f"milestones:{index}:scope_expands_global:{scope}")
        normalized.append(
            {
                "milestone_id": milestone_id if isinstance(milestone_id, str) else "",
                "outcome": raw.get("outcome") if isinstance(raw.get("outcome"), str) else "",
                "scope": _string_list(raw.get("scope")),
                "required_evidence": _string_list(raw.get("required_evidence")),
                "status": raw.get("status") if isinstance(raw.get("status"), str) else "",
                "depends_on": _string_list(raw.get("depends_on")),
            }
        )

    ids = [item["milestone_id"] for item in normalized if item["milestone_id"]]
    if len(ids) != len(set(ids)):
        errors.append("milestones:duplicate_milestone_id")
    known_ids = set(ids)
    status_by_id = {item["milestone_id"]: item["status"] for item in normalized if item["milestone_id"]}
    for item in normalized:
        milestone_id = item["milestone_id"] or "INVALID"
        for dependency in item["depends_on"]:
            if dependency not in known_ids:
                errors.append(f"milestones:{milestone_id}:unknown_dependency:{dependency}")
            if dependency == item["milestone_id"]:
                errors.append(f"milestones:{milestone_id}:self_dependency")
            if item["status"] == "ACTIVE" and status_by_id.get(dependency) != "COMPLETE":
                errors.append(f"milestones:{milestone_id}:active_dependency_not_complete:{dependency}")
    if _has_dependency_cycle(normalized):
        errors.append("milestones:dependency_cycle")
    active = [item for item in normalized if item["status"] == "ACTIVE"]
    if len(active) != 1:
        errors.append("milestones:exactly_one_active_required")

    raw_goals = data.get("goals")
    goal_milestone_ids: set[str] = set()
    active_milestone_id = active[0]["milestone_id"] if len(active) == 1 else None
    active_dispatchable_goal = False
    if not isinstance(raw_goals, list) or not raw_goals:
        errors.append("goals:nonempty_array_required_for_adaptive")
    else:
        for index, goal in enumerate(raw_goals, 1):
            if not isinstance(goal, dict):
                errors.append(f"goals:{index}:must_be_object_for_adaptive")
                continue
            milestone_id = goal.get("milestone_id")
            worker_role = goal.get("worker_role") or goal.get("role")
            goal_role_kind = role_kinds_by_role.get(_role_key(worker_role))
            if goal_role_kind in {"code_reviewer", "state_writer", "local_verifier"}:
                errors.append(
                    f"goals:{index}:invalid_adaptive_execution_role_kind:{goal_role_kind}"
                )
            if not isinstance(milestone_id, str) or milestone_id not in known_ids:
                errors.append(f"goals:{index}:valid_milestone_id_required_for_adaptive")
            else:
                goal_milestone_ids.add(milestone_id)
                if status_by_id.get(milestone_id) not in {"ACTIVE", "PLANNED"}:
                    errors.append(f"goals:{index}:milestone_not_routable_for_adaptive")
                if milestone_id == active_milestone_id and not _string_list(goal.get("depends_on")):
                    active_dispatchable_goal = True
    routable_milestones = {
        item["milestone_id"] for item in normalized if item["status"] in {"ACTIVE", "PLANNED"}
    }
    for milestone_id in sorted(routable_milestones - goal_milestone_ids):
        errors.append(f"milestones:{milestone_id}:missing_goal")
    if active_milestone_id and not active_dispatchable_goal:
        errors.append(f"milestones:{active_milestone_id}:no_initial_dependency_free_goal")

    delegation = data.get("delegation_policy", "disabled")
    if not isinstance(delegation, str) or delegation not in DELEGATION_POLICIES:
        errors.append("delegation_policy:unsupported")
        delegation = "disabled"
    max_subagents = data.get("max_read_only_subagents", 0)
    max_runs = data.get("max_read_only_subagent_runs", 0)
    retry_limit = data.get("subagent_retry_limit", 0)
    if not _bounded_int(max_subagents, 0, 2):
        errors.append("max_read_only_subagents:must_be_integer_0_to_2")
    if not _bounded_int(max_runs, 0, 16):
        errors.append("max_read_only_subagent_runs:must_be_integer_0_to_16")
    if not _bounded_int(retry_limit, 0, 2):
        errors.append("subagent_retry_limit:must_be_integer_0_to_2")
    depth = data.get("subagent_max_depth", 1)
    if depth != 1:
        errors.append("subagent_max_depth:must_equal_1")
    provided = set(data.get("_provided_keys", [])) if isinstance(data.get("_provided_keys"), list) else set()
    if delegation == "disabled":
        if max_subagents != 0 or max_runs != 0 or retry_limit != 0:
            errors.append("subagent_limits:must_be_0_when_delegation_disabled")
    else:
        if "delegation_policy" not in provided:
            errors.append("delegation_policy:explicit_authorization_required")
        if not _bounded_int(max_subagents, 1, 2):
            errors.append("max_read_only_subagents:must_be_integer_1_to_2_when_enabled")
        if not _bounded_int(max_runs, 1, 16) or (
            isinstance(max_subagents, int) and isinstance(max_runs, int) and max_runs < max_subagents
        ):
            errors.append("max_read_only_subagent_runs:must_cover_concurrency_when_enabled")
        input_policy = data.get("subagent_input_policy")
        if "subagent_input_policy" not in provided or not isinstance(input_policy, str) or not input_policy.strip():
            errors.append("subagent_input_policy:explicit_nonempty_policy_required")

    local_policy = data.get("local_verification_policy", "not_required")
    if not isinstance(local_policy, str) or local_policy not in LOCAL_VERIFICATION_POLICIES:
        errors.append("local_verification_policy:unsupported")
    dashboard_policy = data.get("dashboard_policy", "auto")
    if not isinstance(dashboard_policy, str) or dashboard_policy not in DASHBOARD_POLICIES:
        errors.append("dashboard_policy:unsupported")
    native_goal_policy = data.get("native_goal_policy", "required")
    if not isinstance(native_goal_policy, str) or native_goal_policy not in NATIVE_GOAL_POLICIES:
        errors.append("native_goal_policy:unsupported")
    threshold = data.get("dashboard_threshold_hours", 12)
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold <= 0:
        errors.append("dashboard_threshold_hours:must_be_positive_integer")
    heartbeat_interval = _integer_value(data.get("heartbeat_interval_minutes", 15))
    max_wakeups = _integer_value(data.get("max_wakeups", 192))
    maximum_minutes = duration_minutes(data.get("time_max"))
    if (
        heartbeat_interval is not None
        and heartbeat_interval > 0
        and max_wakeups is not None
        and max_wakeups > 0
        and maximum_minutes is not None
        and heartbeat_interval * max_wakeups < maximum_minutes
    ):
        errors.append("heartbeat:coverage_below_time_max")
    minimum_routes = minimum_adaptive_routing_turns(data)
    if (
        max_wakeups is not None
        and max_wakeups > 0
        and minimum_routes is not None
        and max_wakeups < minimum_routes
    ):
        errors.append(
            f"max_wakeups:below_adaptive_minimum_routing_turns:{minimum_routes}"
        )
    return errors
