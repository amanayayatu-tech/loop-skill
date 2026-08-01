"""Native INTAKE -> PREPARE -> CONFIRM boundary for the v4 public entry."""

from __future__ import annotations

import json
import os
import secrets
import stat
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from loop_architect.v4_alpha.protocol import (
    CAPACITY_CONTRACT,
    MANIFEST_SHA256,
    PLAN_SOURCE_KINDS,
    LoopIntakeDecision,
    LoopIntakeInput,
    PlanCapacityReport,
    PreparedLoopBundle,
    PreparedLoopManifest,
    Receipt,
    canonical_bytes,
    domain_digest,
    raw_domain_digest,
    command_without_digest,
)
from loop_architect.v4_alpha.plan_codec import (
    CONTENT_STORAGE_MODE,
    CompiledPlan,
    PlanCodecError,
    authority_binding_digest,
    canonicalize_plan,
    compile_plan,
    content_create_command,
    goal_chain,
    materialize_provider_request,
    max_collection_members,
    parse_plan_bytes,
    plan_digest,
    validate_plan_index,
)
from loop_architect.v4_adapters.codex.prompt import (
    PromptMaterializationError,
    prompt_bytes,
)
from loop_architect.v4_artifacts import (
    ArtifactCaptureError,
    detect_artifact_profile,
    verifier_capability,
    workspace_identity,
)


MANIFEST_FILENAME = "loop-manifest.json"
BOUNDARY_FILENAME = "boundary-summary.json"
PLAN_FILENAME = "CONTROLLER_PLAN.md"
PLAN_DOCUMENT_FILENAME = "plan-document.json"
PLAN_INDEX_FILENAME = "plan-index.json"
CAPACITY_FILENAME = "capacity-report.json"
CAPABILITY_FILENAME = "capability-feasibility.json"
INSTRUCTIONS_FILENAME = "使用说明.md"
BUNDLE_FILENAME = "prepared-bundle.json"
CONFIRMATION_FILENAME = "start-confirmation.json"
MANIFEST_VERSION = "loopskill-prepared-loop-v3"
PRODUCT_VERSION = "4.2.0"
CONFIRMATION_ISSUER = "loopskill-local-confirmation-v1"
CONFIRMATION_TRUST = "local-explicit-confirmation"
_MAX_PREPARED_FILE_BYTES = 520 * 1024
_TUPLE_FIELDS = (
    "goal_plan",
    "write_scope",
    "external_actions",
    "acceptance_criteria",
    "stop_conditions",
    "authorization_boundaries",
)


class PreparationError(Exception):
    """Public-safe preparation error transported by the entry service."""

    def __init__(self, code: str, message: str, next_action: str) -> None:
        self.code = code
        self.message = message
        self.next_action = next_action
        super().__init__(code)


@dataclass(frozen=True)
class PreparedContext:
    directory: Path
    manifest: PreparedLoopManifest
    bundle: PreparedLoopBundle
    boundary: Mapping[str, Any]
    plan: Mapping[str, Any]
    plan_index: Mapping[str, Any]
    capacity_report: Mapping[str, Any]
    capability_report: Mapping[str, Any] | None
    confirmation: Receipt | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _token() -> str:
    return secrets.token_hex(12)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PreparationError(
            "USER_PREPARATION_INVALID",
            "The prepared timestamp is invalid.",
            "Run prepare again in a new empty directory.",
        ) from exc


def intake(request: LoopIntakeInput) -> LoopIntakeDecision:
    """Classify one request without writing state or invoking any provider."""
    canonical_plan = None
    if request.canonical_plan is not None:
        try:
            canonical_plan = canonicalize_plan(request.canonical_plan)
        except PlanCodecError as exc:
            return LoopIntakeDecision(
                disposition="BLOCKED",
                route="UNDETERMINED",
                reason=f"The canonical plan is invalid ({exc.reason}).",
                questions=(),
            )
    goal = (
        str(canonical_plan["objective"])
        if canonical_plan is not None
        else request.goal.strip() if isinstance(request.goal, str) else ""
    )
    if not goal:
        return LoopIntakeDecision(
            disposition="NEEDS_CLARIFICATION",
            route="UNDETERMINED",
            reason="The intended outcome is missing.",
            questions=("What observable outcome should the work produce?",),
        )
    plan = (
        tuple(str(item["objective"]) for item in canonical_plan["goals"])
        if canonical_plan is not None
        else tuple(item.strip() for item in request.goal_plan if item.strip())
    )
    if (
        not plan
        or plan[0] != goal
        or len(plan) > int(CAPACITY_CONTRACT["goal_count_max"])
        or (canonical_plan is None and len(set(plan)) != len(plan))
    ):
        return LoopIntakeDecision(
            disposition="NEEDS_CLARIFICATION",
            route="UNDETERMINED",
            reason=(
                "The Goal plan must contain 1–"
                + str(CAPACITY_CONTRACT["goal_count_max"])
                + " Goals and start with the primary Goal."
            ),
            questions=("Provide an ordered Goal plan whose first item is the primary Goal.",),
        )
    horizon = (
        str(canonical_plan["roadmap_policy"]["mode"]).lower()
        if canonical_plan is not None
        else request.task_horizon.strip().lower()
    )
    external_actions = (
        tuple(canonical_plan["boundaries"]["external_actions"])
        if canonical_plan is not None
        else request.external_actions
    )
    if horizon in {"one_off", "short", "single_step"} and not external_actions:
        return LoopIntakeDecision(
            disposition="DIRECT_TASK_RECOMMENDED",
            route="DIRECT_TASK",
            reason="This is a bounded one-step task without durable coordination needs.",
            questions=(),
        )
    boundaries = {item.strip().lower() for item in request.authorization_boundaries}
    high_impact = {
        action.strip().lower()
        for action in external_actions
        if action.strip().lower() in {"commit", "push", "publish", "deploy"}
    }
    missing_authority = sorted(
        action for action in high_impact if f"{action}:allowed" not in boundaries
    )
    if missing_authority:
        return LoopIntakeDecision(
            disposition="BLOCKED",
            route="UNDETERMINED",
            reason="High-impact actions lack an explicit authorization boundary: "
            + ", ".join(missing_authority),
            questions=(),
        )
    questions: list[str] = []
    write_scope = (
        tuple(canonical_plan["boundaries"]["write_scope"])
        if canonical_plan is not None
        else request.write_scope
    )
    completion = (
        tuple(canonical_plan["completion_evidence"])
        if canonical_plan is not None
        else request.acceptance_criteria
    )
    stops = (
        tuple(canonical_plan["stop_conditions"])
        if canonical_plan is not None
        else request.stop_conditions
    )
    if not write_scope:
        questions.append("What exact paths or surfaces may the loop modify?")
    if canonical_plan is None and not request.budget.strip():
        questions.append("What time, call, token, or cost budget applies?")
    if not completion or not stops:
        questions.append(
            "What observable acceptance criteria and stop conditions must be used?"
        )
    if questions:
        return LoopIntakeDecision(
            disposition="NEEDS_CLARIFICATION",
            route="UNDETERMINED",
            reason="One or more safety-critical preparation fields are missing.",
            questions=tuple(questions[:3]),
        )
    route = "ADAPTIVE_LOOP" if horizon == "adaptive" else "STANDARD_LOOP"
    selection = (
        "Adaptive was explicitly requested for bounded roadmap revision."
        if route == "ADAPTIVE_LOOP"
        else "Standard is the default fixed, dependency-ordered Goal Queue."
    )
    return LoopIntakeDecision(
        disposition="READY_FOR_LOOP",
        route=route,
        reason=(
            "Goal, scope, budget, effects, acceptance, and stop boundaries are explicit. "
            + selection
        ),
        questions=(),
    )


def intake_report(request: LoopIntakeInput) -> Mapping[str, Any]:
    """Stable seven-section, read-only intake projection without control identity."""
    decision = intake(request)
    matrix = (
        f"goal={'PASS' if request.goal.strip() else 'MISSING'}",
        f"write_scope={'PASS' if request.write_scope else 'MISSING'}",
        f"budget={'PASS' if request.budget.strip() else 'MISSING'}",
        f"acceptance={'PASS' if request.acceptance_criteria else 'MISSING'}",
        f"stop_conditions={'PASS' if request.stop_conditions else 'MISSING'}",
    )
    blockers = (decision.reason,) if decision.disposition == "BLOCKED" else ()
    return {
        "1 最终判定": {
            "disposition": decision.disposition,
            "reason": decision.reason,
            "route": decision.route,
        },
        "2 质量闸矩阵": matrix,
        "3 阻断项": blockers,
        "4 必须澄清的问题": decision.questions,
        "5 风险与待确认假设": {
            "Confirmed Facts": ("Only the supplied semantic request was evaluated.",),
            "UNKNOWN": () if decision.disposition == "READY_FOR_LOOP" else (decision.reason,),
            "PROPOSED—REQUIRES_CONFIRMATION": tuple(request.external_actions),
            "Permissions and side effects": tuple(request.authorization_boundaries),
            "Requires current verification": (),
        },
        "6 规范化需求": {
            "acceptance_criteria": tuple(request.acceptance_criteria),
            "budget": request.budget.strip(),
            "external_actions": tuple(request.external_actions),
            "goal": request.goal.strip(),
            "goal_plan": tuple(item.strip() for item in request.goal_plan),
            "stop_conditions": tuple(request.stop_conditions),
            "write_scope": tuple(request.write_scope),
        },
        "7 Loop 输入结果": {
            "ready": decision.disposition == "READY_FOR_LOOP",
            "route": decision.route,
        },
    }


def _ensure_output_directory(path: Path) -> None:
    if path.exists():
        try:
            metadata = path.lstat()
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISDIR(metadata.st_mode)
                or any(path.iterdir())
            ):
                raise OSError("unsafe or nonempty output")
        except OSError as exc:
            raise PreparationError(
                "USER_PREPARATION_INVALID",
                "The preparation output must be a private empty directory.",
                "Choose a new empty local output directory.",
            ) from exc
    else:
        try:
            path.mkdir(parents=True, mode=0o700)
        except OSError as exc:
            raise PreparationError(
                "USER_PREPARATION_INVALID",
                "The preparation output could not be created.",
                "Choose a writable local output directory.",
            ) from exc
    metadata = path.stat()
    if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise PreparationError(
            "USER_PREPARATION_INVALID",
            "The preparation output is not owner-only.",
            "Use an owner-only local directory.",
        )


def _write_once(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
        try:
            written = os.write(descriptor, content)
            if written != len(content):
                raise OSError("short write")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise PreparationError(
            "USER_PREPARATION_INVALID",
            "A prepared artifact could not be written immutably.",
            "Preserve the directory and prepare again in a new location.",
        ) from exc


def _read_prepared_bytes(path: Path, *, maximum: int = _MAX_PREPARED_FILE_BYTES) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_mode & 0o077
            or before.st_size > maximum
        ):
            raise OSError("unsafe prepared file")
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                or not stat.S_ISREG(opened.st_mode)
            ):
                raise OSError("prepared file identity changed")
            chunks: list[bytes] = []
            remaining = maximum + 1
            while remaining:
                chunk = os.read(descriptor, min(65_536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            after = os.fstat(descriptor)
            if (
                len(raw) > maximum
                or (after.st_dev, after.st_ino, after.st_size)
                != (opened.st_dev, opened.st_ino, opened.st_size)
            ):
                raise OSError("prepared file changed while reading")
            return raw
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise PreparationError(
            "USER_PREPARATION_INVALID",
            "A prepared artifact is missing, unsafe, or changed while reading.",
            "Preserve the directory and prepare again in a new location.",
        ) from exc


def _manifest_value(manifest: PreparedLoopManifest) -> dict[str, Any]:
    return asdict(manifest)


def _boundary_value(
    manifest: PreparedLoopManifest,
    plan: Mapping[str, Any],
    index: Mapping[str, Any],
) -> dict[str, Any]:
    plan_boundaries = plan["boundaries"]
    return {
        "acceptance_criteria": list(manifest.acceptance_criteria),
        "authorization_boundaries": list(manifest.authorization_boundaries),
        "artifact_profile": manifest.artifact_profile,
        "budget": manifest.budget,
        "external_actions": list(manifest.external_actions),
        "execution_mode": manifest.execution_mode,
        "max_roadmap_revisions": manifest.max_roadmap_revisions,
        "goal": manifest.goal,
        "goal_plan": list(manifest.goal_plan),
        "plan_digest": manifest.plan_digest,
        "plan_index_digest": manifest.plan_index_digest,
        "plan_storage_mode": manifest.plan_storage_mode,
        "capacity_contract_version": manifest.capacity_contract_version,
        "destructive_actions_allowed": plan_boundaries[
            "destructive_actions_allowed"
        ],
        "forbidden_actions": list(plan_boundaries["forbidden_actions"]),
        "forbidden_paths": list(plan_boundaries["forbidden_paths"]),
        "plan_revision": index["revision"],
        "product_version": manifest.product_version,
        "protocol_manifest_digest": manifest.protocol_manifest_digest,
        "selection_reason": manifest.selection_reason,
        "stop_conditions": list(manifest.stop_conditions),
        "write_scope": list(manifest.write_scope),
        "workspace_identity_digest": manifest.workspace_identity_digest,
    }


def _render_plan(
    manifest: PreparedLoopManifest,
    manifest_digest: str,
    boundary_digest: str,
    plan: Mapping[str, Any],
    index: Mapping[str, Any],
    capability_report_digest: str | None = None,
) -> bytes:
    def lines(values: tuple[str, ...] | list[str]) -> str:
        return "\n".join(f"- {value}" for value in values) or "- None"

    plan_boundaries = plan["boundaries"]

    text = f"""# LoopSkill 4.2 任务卡

This is a human review/export view. `loop-manifest.json` is the machine source.

## Goal

{manifest.goal}

## Goal plan

{lines(manifest.goal_plan)}

## Write scope

{lines(manifest.write_scope)}

## Budget

{manifest.budget}

## Execution mode

- {manifest.execution_mode}: {manifest.selection_reason}
- Maximum canonical roadmap revisions: {manifest.max_roadmap_revisions}

## External actions

{lines(manifest.external_actions)}

## Acceptance criteria

{lines(manifest.acceptance_criteria)}

## Stop conditions

{lines(manifest.stop_conditions)}

## Authorization boundaries

{lines(manifest.authorization_boundaries)}

## Forbidden paths

{lines(plan_boundaries["forbidden_paths"])}

## Destructive actions

- Allowed: {str(plan_boundaries["destructive_actions_allowed"]).lower()}

## Machine binding

- Manifest digest: `{manifest_digest}`
- Boundary digest: `{boundary_digest}`
- Plan digest: `{manifest.plan_digest}`
- PlanIndex digest: `{manifest.plan_index_digest}`
- Plan revision: `{index["revision"]}`
- Workspace identity: `{manifest.workspace_identity_digest}`
- Capacity contract: `{manifest.capacity_contract_version}`
{('- Capability report digest: `' + capability_report_digest + '`') if capability_report_digest else ''}
- No Host task, heartbeat, delivery, or execution was created by this plan.
"""
    return text.encode("utf-8")


def _render_instructions() -> bytes:
    return (
        "# LoopSkill 4.2 使用说明\n\n"
        "1. 先审阅 Controller Plan 中的 Goal、写入范围、预算、外部动作、验收和停止条件。\n"
        "2. 只有内容准确时才执行显式确认；准备阶段不会创建任何 Host task 或 heartbeat。\n"
        "3. 任一准备文件变化都会使旧确认失效；请重新 prepare/confirm。\n"
        "4. 容量报告必须为 PASS；普通用户无需填写 thread、task、route、receipt、SHA 或 Host 参数。\n"
    ).encode("utf-8")


def _request_source_bytes(request: LoopIntakeInput) -> int:
    if request.source_bytes:
        if isinstance(request.source_bytes, bool) or request.source_bytes < 0:
            raise PreparationError(
                "USER_INPUT_INVALID",
                "The admitted source byte count is invalid.",
                "Provide the source again through the supported intake path.",
            )
        return request.source_bytes
    if request.canonical_plan is not None:
        return len(canonical_bytes(request.canonical_plan))
    return len(
        canonical_bytes(
            {
                "acceptance_criteria": list(request.acceptance_criteria),
                "authorization_boundaries": list(request.authorization_boundaries),
                "budget": request.budget,
                "external_actions": list(request.external_actions),
                "goal": request.goal,
                "goal_plan": list(request.goal_plan),
                "stop_conditions": list(request.stop_conditions),
                "task_horizon": request.task_horizon,
                "write_scope": list(request.write_scope),
            }
        )
    )


def _compiled_from_bytes(plan_raw: bytes, index_raw: bytes) -> CompiledPlan:
    plan = parse_plan_bytes(plan_raw)
    try:
        index_value = json.loads(index_raw.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreparationError(
            "USER_PREPARATION_INVALID",
            "The prepared PlanIndex is invalid.",
            "Preserve the directory and prepare again.",
        ) from exc
    index = validate_plan_index(index_value, plan)
    if canonical_bytes(index) != index_raw:
        raise PreparationError(
            "USER_PREPARATION_INVALID",
            "The prepared PlanIndex is not canonical.",
            "Preserve the directory and prepare again.",
        )
    return CompiledPlan(
        plan=plan,
        plan_bytes=plan_raw,
        plan_digest=plan_digest(plan_raw),
        goal_slice_digests=tuple(index["ordered_goal_slice_digests"]),
        index=index,
        index_bytes=index_raw,
        index_digest=plan_digest(index_raw),
    )


def _capacity_report(
    compiled: CompiledPlan,
    *,
    namespace: str,
    loop_ref: str,
    issued_at: str,
    artifact_profile: str,
    source_bytes: int,
) -> dict[str, Any]:
    placeholder_digest = "0" * 64
    command = content_create_command(
        namespace=namespace,
        loop_ref=loop_ref,
        compiled=compiled,
        issued_at=issued_at,
        confirmation_receipt_ref="receipt-confirm-" + "0" * 24,
        manifest_digest=placeholder_digest,
        boundary_digest=placeholder_digest,
        bundle_digest=placeholder_digest,
        artifact_profile=artifact_profile,
        artifact_baseline_blob_digest=(
            None if artifact_profile == "UNBOUND" else placeholder_digest
        ),
    )
    command_value = command_without_digest(command)
    command_bytes = len(canonical_bytes(command_value))
    collection_members = max_collection_members(command_value)
    prompt_sizes: list[int] = []
    hard_prompt_failure = False
    for position, (goal_id, slice_digest) in enumerate(
        zip(
            compiled.index["ordered_goal_ids"],
            compiled.index["ordered_goal_slice_digests"],
        )
    ):
        chain = goal_chain(
            loop_ref,
            compiled.plan_digest,
            str(goal_id),
            str(slice_digest),
        )
        payload = materialize_provider_request(
            compiled.plan,
            compiled.index,
            position,
            target_ref=chain["provider_target"],
            artifact_digest=placeholder_digest,
            prior_disposition="" if position == 0 else "DONE",
        )
        try:
            prompt_sizes.append(prompt_bytes(payload, chain["provider_key"]))
        except PromptMaterializationError:
            prompt_sizes.append(int(CAPACITY_CONTRACT["host_prompt_hard_bytes"]) + 1)
            hard_prompt_failure = True
    maximum_prompt = max(prompt_sizes)
    maximum_position = prompt_sizes.index(maximum_prompt)
    reasons = []
    if source_bytes > (
        int(CAPACITY_CONTRACT["source_text_max_bytes"])
        if compiled.plan["source"]["kind"]
        in set(PLAN_SOURCE_KINDS) - {"expert_semantic_json", "canonical_plan_json"}
        else int(CAPACITY_CONTRACT["expert_json_max_bytes"])
    ):
        reasons.append("source_bytes")
    if len(compiled.plan_bytes) > int(CAPACITY_CONTRACT["canonical_plan_max_bytes"]):
        reasons.append("canonical_plan_bytes")
    if command_bytes > int(CAPACITY_CONTRACT["create_loop_target_bytes"]):
        reasons.append("create_loop_target_bytes")
    if collection_members > int(
        CAPACITY_CONTRACT["create_loop_target_collection_members"]
    ):
        reasons.append("create_loop_target_collection_members")
    if maximum_prompt > int(CAPACITY_CONTRACT["host_prompt_target_bytes"]):
        reasons.append("host_prompt_target_bytes")
    if hard_prompt_failure:
        reasons.append("host_prompt_hard_bytes")
    if int(compiled.plan["budget"]["max_host_invocations"]) < len(
        compiled.plan["goals"]
    ):
        reasons.append("budget_host_invocations_below_goal_count")
    report = PlanCapacityReport(
        source_kind=str(compiled.plan["source"]["kind"]),
        source_bytes=source_bytes,
        source_digest=str(compiled.plan["source"]["source_digest"]),
        goal_count=len(compiled.plan["goals"]),
        plan_bytes=len(compiled.plan_bytes),
        plan_digest=compiled.plan_digest,
        plan_index_digest=compiled.index_digest,
        create_loop_command_bytes=command_bytes,
        create_loop_max_collection_members=collection_members,
        max_materialized_goal_prompt_bytes=maximum_prompt,
        max_materialized_goal_id=str(
            compiled.index["ordered_goal_ids"][maximum_position]
        ),
        create_loop_byte_headroom=int(
            CAPACITY_CONTRACT["create_loop_target_bytes"]
        )
        - command_bytes,
        create_loop_collection_headroom=int(
            CAPACITY_CONTRACT["create_loop_target_collection_members"]
        )
        - collection_members,
        provider_prompt_headroom=int(CAPACITY_CONTRACT["host_prompt_target_bytes"])
        - maximum_prompt,
        capacity_contract_version=str(CAPACITY_CONTRACT["version"]),
        capacity_status="PASS" if not reasons else "BLOCKED",
        blocking_reason=",".join(reasons),
        materialized_goal_prompt_bytes=tuple(prompt_sizes),
    )
    return asdict(report)


def _capability_report(
    compiled: CompiledPlan,
    *,
    artifact_profile: str,
) -> dict[str, Any] | None:
    """Preflight Plan v2 capabilities and verifier declarations without effects."""

    if compiled.plan.get("schema") != "loopskill-plan-v2":
        return None
    profile = compiled.plan["worker_profile"]
    available = {"workspace-write"}
    if artifact_profile != "UNBOUND":
        available.add("artifact-capture")
    if artifact_profile in {"existing_git", "new_git"}:
        available.add("git")
    if profile["network_access"]:
        available.add("network")
    if profile["local_verification"]:
        available.update({"local-command", "local-http"})
    rows = []
    blocked = []
    budget_blocked = bool(compiled.plan["budget"]["max_cost_minor_units"])
    for goal in compiled.plan["goals"]:
        verifier_capabilities: set[str] = set()
        unsupported_verifiers = 0
        for verifier in goal["verifiers"]:
            try:
                capability = verifier_capability(verifier)
            except (ArtifactCaptureError, ValueError):
                capability = None
            if capability is None:
                unsupported_verifiers += 1
            else:
                verifier_capabilities.add(capability)
        unavailable = sorted(
            (set(goal["capabilities"]) | verifier_capabilities) - available
        )
        if goal["gate"] in {"human", "time"}:
            gate_capability = goal["gate"] + "-gate"
            unavailable = sorted(
                item
                for item in unavailable
                if item != gate_capability
            )
        unavailable_evidence = bool(unavailable or unsupported_verifiers)
        state = (
            "BLOCKED"
            if unavailable_evidence and goal["requirement"] == "required"
            else "OPTIONAL_UNAVAILABLE"
            if unavailable_evidence
            else "READY"
        )
        if state == "BLOCKED":
            blocked.append(goal["goal_id"])
        rows.append(
            {
                "gate": goal["gate"],
                "goal_id": goal["goal_id"],
                "requirement": goal["requirement"],
                "state": state,
                "unavailable_capabilities": unavailable,
                "unsupported_verifier_count": unsupported_verifiers,
            }
        )
    return {
        "available_capabilities": sorted(available),
        "blocked_required_goals": blocked,
        "goals": rows,
        "plan_digest": compiled.plan_digest,
        "schema": "loopskill-capability-feasibility-v1",
        "unsupported_budget": (
            "positive-cost-accounting"
            if budget_blocked
            else None
        ),
        "status": "BLOCKED" if blocked or budget_blocked else "PASS",
    }


def prepare(
    request: LoopIntakeInput,
    output_directory: Path | str,
    *,
    clock: Callable[[], datetime] = _now,
    token_factory: Callable[[], str] = _token,
    workspace_root: Path | str | None = None,
) -> PreparedContext:
    if request.canonical_plan is not None:
        try:
            canonicalize_plan(request.canonical_plan)
        except PlanCodecError as exc:
            raise PreparationError(
                exc.code,
                "The execution plan does not satisfy the closed v4.2 plan contract.",
                f"Revise the request and prepare again ({exc.reason}).",
            ) from exc
    elif len(request.goal_plan) > int(CAPACITY_CONTRACT["goal_count_max"]):
        raise PreparationError(
            "RESOURCE_LIMIT_EXCEEDED",
            "The Goal plan exceeds the v4.2 capacity contract.",
            "Split the work into a plan with at most "
            + str(CAPACITY_CONTRACT["goal_count_max"])
            + " Goals.",
        )
    decision = intake(request)
    if decision.disposition == "DIRECT_TASK_RECOMMENDED":
        raise PreparationError(
            "USER_DIRECT_TASK_RECOMMENDED",
            decision.reason,
            "Run the task directly in Codex; no loop was created.",
        )
    if decision.disposition != "READY_FOR_LOOP":
        code = (
            "USER_CLARIFICATION_REQUIRED"
            if decision.disposition == "NEEDS_CLARIFICATION"
            else "USER_PREPARATION_INVALID"
        )
        raise PreparationError(
            code,
            decision.reason,
            "Resolve the intake blockers before preparing a loop.",
        )
    namespace = token_factory()
    if (
        not isinstance(namespace, str)
        or len(namespace) != 24
        or any(character not in "0123456789abcdef" for character in namespace)
    ):
        raise PreparationError(
            "USER_INTERNAL_ERROR",
            "LoopSkill could not allocate a preparation identity.",
            "Retry in a new empty output directory.",
        )
    loop_ref = f"loop-{namespace}"
    if workspace_root is None:
        artifact_profile = "UNBOUND"
        workspace_identity_digest = domain_digest(
            "loopskill-workspace-identity-v1\n", {"profile": "UNBOUND"}
        )
    else:
        try:
            artifact_profile = detect_artifact_profile(workspace_root)
            workspace_identity_digest = workspace_identity(
                workspace_root, artifact_profile
            )
        except ArtifactCaptureError as exc:
            raise PreparationError(
                "USER_PREPARATION_INVALID",
                "The selected workspace cannot be safely bound for artifact capture.",
                "Choose one confined regular workspace and prepare again.",
            ) from exc
    prepared_at = _iso(clock())
    try:
        compiled = compile_plan(
            request,
            loop_ref=loop_ref,
            workspace_binding=workspace_identity_digest,
        )
        source_bytes = _request_source_bytes(request)
        capacity = _capacity_report(
            compiled,
            namespace=namespace,
            loop_ref=loop_ref,
            issued_at=prepared_at,
            artifact_profile=artifact_profile,
            source_bytes=source_bytes,
        )
        capability = _capability_report(
            compiled,
            artifact_profile=artifact_profile,
        )
    except PlanCodecError as exc:
        raise PreparationError(
            exc.code,
            "The execution plan does not satisfy the closed v4.2 plan contract.",
            f"Revise the request and prepare again ({exc.reason}).",
        ) from exc
    if capacity["capacity_status"] != "PASS":
        raise PreparationError(
            "RESOURCE_LIMIT_EXCEEDED",
            "The prepared loop exceeds the v4.2 release capacity target.",
            "Reduce or split the indicated Goal or boundary, then prepare again: "
            + str(capacity["blocking_reason"]),
        )
    if capability is not None and capability["status"] != "PASS":
        raise PreparationError(
            "USER_CAPABILITY_UNAVAILABLE",
            "One or more required Goals cannot be independently verified with the prepared worker profile.",
            "Revise the blocked Goal capabilities or verifiers, then prepare again: "
            + ",".join(capability["blocked_required_goals"]),
        )
    capacity_bytes = canonical_bytes(capacity)
    capacity_digest = raw_domain_digest(
        "loopskill-prepared-artifact-v1\n", capacity_bytes
    )
    manifest = PreparedLoopManifest(
        manifest_version=MANIFEST_VERSION,
        control_namespace=namespace,
        loop_ref=loop_ref,
        goal=str(compiled.plan["objective"]),
        goal_plan=tuple(
            str(goal["objective"]) for goal in compiled.plan["goals"]
        ),
        task_horizon=str(compiled.plan["roadmap_policy"]["mode"]).lower(),
        execution_mode=str(compiled.plan["roadmap_policy"]["mode"]),
        max_roadmap_revisions=(
            int(compiled.plan["roadmap_policy"]["max_reorders"]) + 1
        ),
        selection_reason=decision.reason,
        write_scope=tuple(compiled.plan["boundaries"]["write_scope"]),
        budget=canonical_bytes(compiled.plan["budget"]).decode("utf-8"),
        external_actions=tuple(compiled.plan["boundaries"]["external_actions"]),
        acceptance_criteria=tuple(compiled.plan["completion_evidence"]),
        stop_conditions=tuple(compiled.plan["stop_conditions"]),
        authorization_boundaries=(
            tuple(request.authorization_boundaries)
            or tuple(compiled.plan["boundaries"]["forbidden_actions"])
        ),
        artifact_profile=artifact_profile,
        workspace_identity_digest=workspace_identity_digest,
        prepared_at=prepared_at,
        plan_storage_mode=CONTENT_STORAGE_MODE,
        plan_digest=compiled.plan_digest,
        plan_index_digest=compiled.index_digest,
        capacity_report_digest=capacity_digest,
        capacity_contract_version=str(CAPACITY_CONTRACT["version"]),
        source_digest=str(compiled.plan["source"]["source_digest"]),
        product_version=PRODUCT_VERSION,
        protocol_manifest_digest=MANIFEST_SHA256,
    )
    manifest_value = _manifest_value(manifest)
    boundary = _boundary_value(manifest, compiled.plan, compiled.index)
    manifest_bytes = canonical_bytes(manifest_value)
    boundary_bytes = canonical_bytes(boundary)
    manifest_digest = domain_digest(
        "loopskill-prepared-manifest-v1\n", manifest_value
    )
    boundary_digest = domain_digest(
        "loopskill-prepared-boundary-v1\n", boundary
    )
    capability_bytes = None if capability is None else canonical_bytes(capability)
    capability_digest = (
        None
        if capability_bytes is None
        else raw_domain_digest("loopskill-prepared-artifact-v1\n", capability_bytes)
    )
    plan_bytes = _render_plan(
        manifest,
        manifest_digest,
        boundary_digest,
        compiled.plan,
        compiled.index,
        capability_digest,
    )
    instructions_bytes = _render_instructions()
    bundle_base = {
        "boundary_digest": boundary_digest,
        "capacity_report_digest": capacity_digest,
        "controller_plan_digest": raw_domain_digest(
            "loopskill-prepared-artifact-v1\n", plan_bytes
        ),
        "instructions_digest": raw_domain_digest(
            "loopskill-prepared-artifact-v1\n", instructions_bytes
        ),
        "manifest_digest": manifest_digest,
        "plan_digest": compiled.plan_digest,
        "plan_index_digest": compiled.index_digest,
    }
    bundle = PreparedLoopBundle(
        bundle_digest=domain_digest(
            "loopskill-prepared-bundle-v1\n", bundle_base
        ),
        **bundle_base,
    )
    output = Path(output_directory)
    _ensure_output_directory(output)
    _write_once(output / MANIFEST_FILENAME, manifest_bytes)
    _write_once(output / BOUNDARY_FILENAME, boundary_bytes)
    _write_once(output / PLAN_FILENAME, plan_bytes)
    _write_once(output / PLAN_DOCUMENT_FILENAME, compiled.plan_bytes)
    _write_once(output / PLAN_INDEX_FILENAME, compiled.index_bytes)
    _write_once(output / CAPACITY_FILENAME, capacity_bytes)
    if capability_bytes is not None:
        _write_once(output / CAPABILITY_FILENAME, capability_bytes)
    _write_once(output / INSTRUCTIONS_FILENAME, instructions_bytes)
    _write_once(output / BUNDLE_FILENAME, canonical_bytes(asdict(bundle)))
    directory_fd = os.open(output, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return PreparedContext(
        directory=output,
        manifest=manifest,
        bundle=bundle,
        boundary=boundary,
        plan=compiled.plan,
        plan_index=compiled.index,
        capacity_report=capacity,
        capability_report=capability,
        confirmation=None,
    )


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        raw = _read_prepared_bytes(path)
        value = json.loads(raw.decode("utf-8", "strict"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PreparationError(
            "USER_PREPARATION_INVALID",
            "A prepared artifact is missing or invalid.",
            "Run prepare again in a new empty directory.",
        ) from exc
    if not isinstance(value, dict) or canonical_bytes(value) != raw:
        raise PreparationError(
            "USER_PREPARATION_INVALID",
            "A prepared artifact is not canonical.",
            "Run prepare again in a new empty directory.",
        )
    return value


def _manifest_from_value(value: Mapping[str, Any]) -> PreparedLoopManifest:
    expected = {field.name for field in PreparedLoopManifest.__dataclass_fields__.values()}
    if set(value) != expected:
        raise PreparationError(
            "USER_PREPARATION_INVALID",
            "The prepared manifest shape is invalid.",
            "Run prepare again in a new empty directory.",
        )
    converted = dict(value)
    for field in _TUPLE_FIELDS:
        item = converted.get(field)
        if not isinstance(item, list) or not all(isinstance(part, str) for part in item):
            raise PreparationError(
                "USER_PREPARATION_INVALID",
                "The prepared manifest contains invalid boundary values.",
                "Run prepare again in a new empty directory.",
            )
        converted[field] = tuple(item)
    try:
        manifest = PreparedLoopManifest(**converted)
    except TypeError as exc:
        raise PreparationError(
            "USER_PREPARATION_INVALID",
            "The prepared manifest shape is invalid.",
            "Run prepare again in a new empty directory.",
        ) from exc
    if (
        manifest.manifest_version != MANIFEST_VERSION
        or not manifest.loop_ref.startswith("loop-")
        or manifest.loop_ref != f"loop-{manifest.control_namespace}"
    ):
        raise PreparationError(
            "USER_PREPARATION_INVALID",
            "The prepared manifest identity is invalid.",
            "Run prepare again in a new empty directory.",
        )
    return manifest


def load_prepared(
    directory: Path | str,
    *,
    require_confirmation: bool = False,
    clock: Callable[[], datetime] = _now,
) -> PreparedContext:
    root = Path(directory)
    try:
        metadata = root.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o077
        ):
            raise OSError("unsafe prepared directory")
        entries = {item.name for item in root.iterdir()}
    except OSError as exc:
        raise PreparationError(
            "USER_PREPARATION_INVALID",
            "The prepared directory is unavailable or unsafe.",
            "Use the original owner-only preparation directory.",
        ) from exc
    required = {
        MANIFEST_FILENAME,
        BOUNDARY_FILENAME,
        PLAN_FILENAME,
        PLAN_DOCUMENT_FILENAME,
        PLAN_INDEX_FILENAME,
        CAPACITY_FILENAME,
        INSTRUCTIONS_FILENAME,
        BUNDLE_FILENAME,
    }
    allowed = required | {CAPABILITY_FILENAME, CONFIRMATION_FILENAME}
    if not required <= entries or not entries <= allowed:
        raise PreparationError(
            "USER_PREPARATION_INVALID",
            "The prepared directory contains missing or unexpected files.",
            "Preserve it for diagnostics and prepare again.",
        )
    manifest_value = _load_json(root / MANIFEST_FILENAME)
    boundary = _load_json(root / BOUNDARY_FILENAME)
    bundle_value = _load_json(root / BUNDLE_FILENAME)
    plan_raw = _read_prepared_bytes(root / PLAN_DOCUMENT_FILENAME)
    index_raw = _read_prepared_bytes(root / PLAN_INDEX_FILENAME)
    capacity = _load_json(root / CAPACITY_FILENAME)
    try:
        compiled = _compiled_from_bytes(plan_raw, index_raw)
    except PlanCodecError as exc:
        raise PreparationError(
            "USER_PREPARATION_INVALID",
            "The prepared plan identity is invalid.",
            f"Preserve the directory and prepare again ({exc.reason}).",
        ) from exc
    has_capability_report = CAPABILITY_FILENAME in entries
    expects_capability_report = compiled.plan.get("schema") == "loopskill-plan-v2"
    if has_capability_report != expects_capability_report:
        raise PreparationError(
            "USER_PREPARATION_INVALID",
            "The prepared capability report set does not match the Plan version.",
            "Preserve the directory and prepare again.",
        )
    capability = (
        _load_json(root / CAPABILITY_FILENAME)
        if has_capability_report
        else None
    )
    try:
        bundle = PreparedLoopBundle(**bundle_value)
    except TypeError as exc:
        raise PreparationError(
            "USER_PREPARATION_INVALID",
            "The prepared bundle shape is invalid.",
            "Run prepare again in a new empty directory.",
        ) from exc
    manifest = _manifest_from_value(manifest_value)
    expected_authority = authority_binding_digest(
        loop_ref=manifest.loop_ref,
        plan_identity=compiled.plan_digest,
        goal_count=len(compiled.plan["goals"]),
        workspace_binding=manifest.workspace_identity_digest,
        roadmap_mode=manifest.execution_mode,
    )
    if compiled.index["authority_digest"] != expected_authority:
        raise PreparationError(
            "USER_PREPARATION_INVALID",
            "The prepared authority binding is invalid.",
            "Preserve the directory and prepare again.",
        )
    expected_capacity = _capacity_report(
        compiled,
        namespace=manifest.control_namespace,
        loop_ref=manifest.loop_ref,
        issued_at=manifest.prepared_at,
        artifact_profile=manifest.artifact_profile,
        source_bytes=int(capacity.get("source_bytes", -1)),
    )
    expected_capability = _capability_report(
        compiled,
        artifact_profile=manifest.artifact_profile,
    )
    expected_base = {
        "boundary_digest": domain_digest(
            "loopskill-prepared-boundary-v1\n", boundary
        ),
        "controller_plan_digest": raw_domain_digest(
            "loopskill-prepared-artifact-v1\n",
            _read_prepared_bytes(root / PLAN_FILENAME),
        ),
        "instructions_digest": raw_domain_digest(
            "loopskill-prepared-artifact-v1\n",
            _read_prepared_bytes(root / INSTRUCTIONS_FILENAME),
        ),
        "manifest_digest": domain_digest(
            "loopskill-prepared-manifest-v1\n", manifest_value
        ),
        "capacity_report_digest": raw_domain_digest(
            "loopskill-prepared-artifact-v1\n",
            canonical_bytes(capacity),
        ),
        "plan_digest": compiled.plan_digest,
        "plan_index_digest": compiled.index_digest,
    }
    expected_bundle = PreparedLoopBundle(
        bundle_digest=domain_digest(
            "loopskill-prepared-bundle-v1\n", expected_base
        ),
        **expected_base,
    )
    identities_match = (
        manifest.plan_storage_mode == CONTENT_STORAGE_MODE
        and manifest.plan_digest == compiled.plan_digest
        and manifest.plan_index_digest == compiled.index_digest
        and manifest.capacity_report_digest == expected_base["capacity_report_digest"]
        and manifest.capacity_contract_version == CAPACITY_CONTRACT["version"]
        and manifest.product_version == PRODUCT_VERSION
        and manifest.protocol_manifest_digest == MANIFEST_SHA256
        and manifest.source_digest == compiled.plan["source"]["source_digest"]
        and manifest.workspace_identity_digest == compiled.index["workspace_binding"]
    )
    if (
        bundle != expected_bundle
        or boundary != _boundary_value(manifest, compiled.plan, compiled.index)
        or canonical_bytes(capacity) != canonical_bytes(expected_capacity)
        or (
            None if capability is None else canonical_bytes(capability)
        )
        != (
            None
            if expected_capability is None
            else canonical_bytes(expected_capability)
        )
        or capacity.get("capacity_status") != "PASS"
        or (
            capability is not None
            and capability.get("status") != "PASS"
        )
        or not identities_match
    ):
        code = (
            "USER_CONFIRMATION_STALE"
            if CONFIRMATION_FILENAME in entries
            else "USER_PREPARATION_INVALID"
        )
        raise PreparationError(
            code,
            "The prepared content no longer matches its machine digest.",
            "Run prepare and explicit confirmation again.",
        )
    confirmation = None
    if CONFIRMATION_FILENAME in entries:
        value = _load_json(root / CONFIRMATION_FILENAME)
        try:
            confirmation = Receipt(**value)
        except TypeError as exc:
            raise PreparationError(
                "USER_CONFIRMATION_STALE",
                "The start confirmation shape is invalid.",
                "Confirm the unchanged preparation again.",
            ) from exc
        valid = (
            confirmation.issuer_ref == CONFIRMATION_ISSUER
            and confirmation.issuer_trust == CONFIRMATION_TRUST
            and confirmation.trust_class == "strict"
            and confirmation.action == "confirm_start"
            and confirmation.loop_ref == manifest.loop_ref
            and confirmation.subject_ref == manifest.loop_ref
            and confirmation.attempt_ref is None
            and confirmation.target_ref == bundle.boundary_digest
            and confirmation.request_digest == bundle.manifest_digest
            and confirmation.provider_idempotency_key is None
            and confirmation.outcome == "observed"
            and confirmation.evidence_digest == bundle.bundle_digest
            and _parse_time(confirmation.issued_at) <= clock()
            and clock() <= _parse_time(confirmation.expires_at)
        )
        if not valid:
            raise PreparationError(
                "USER_CONFIRMATION_STALE",
                "The start confirmation is stale or does not bind this preparation.",
                "Review the current boundaries and confirm again.",
            )
    if require_confirmation and confirmation is None:
        raise PreparationError(
            "USER_CONFIRMATION_REQUIRED",
            "Explicit confirmation is required before starting.",
            "Review the boundary summary and run confirm.",
        )
    return PreparedContext(
        directory=root,
        manifest=manifest,
        bundle=bundle,
        boundary=boundary,
        plan=compiled.plan,
        plan_index=compiled.index,
        capacity_report=capacity,
        capability_report=capability,
        confirmation=confirmation,
    )


def confirm_prepared(
    directory: Path | str,
    *,
    confirmed: bool,
    clock: Callable[[], datetime] = _now,
) -> PreparedContext:
    context = load_prepared(directory, clock=clock)
    if context.confirmation is not None:
        return context
    if not confirmed:
        raise PreparationError(
            "USER_CONFIRMATION_REQUIRED",
            "The prepared boundaries were not explicitly confirmed.",
            "Review every boundary and confirm explicitly.",
        )
    issued = clock()
    receipt = Receipt(
        receipt_ref=f"receipt-confirm-{context.bundle.bundle_digest[:24]}",
        issuer_ref=CONFIRMATION_ISSUER,
        issuer_trust=CONFIRMATION_TRUST,
        trust_class="strict",
        action="confirm_start",
        loop_ref=context.manifest.loop_ref,
        subject_ref=context.manifest.loop_ref,
        attempt_ref=None,
        target_ref=context.bundle.boundary_digest,
        request_digest=context.bundle.manifest_digest,
        provider_idempotency_key=None,
        provider_resource_ref=None,
        outcome="observed",
        issued_at=_iso(issued),
        expires_at=_iso(issued + timedelta(minutes=30)),
        evidence_digest=context.bundle.bundle_digest,
    )
    _write_once(context.directory / CONFIRMATION_FILENAME, canonical_bytes(asdict(receipt)))
    return load_prepared(context.directory, require_confirmation=True, clock=clock)


def boundary_display(context: PreparedContext) -> Mapping[str, Any]:
    """Return only the human authorization boundary, never control identity."""
    return {
        "acceptance_criteria": context.manifest.acceptance_criteria,
        "authorization_boundaries": context.manifest.authorization_boundaries,
        "budget": context.manifest.budget,
        "destructive_actions_allowed": context.boundary[
            "destructive_actions_allowed"
        ],
        "capacity": {
            key: context.capacity_report[key]
            for key in (
                "capacity_status",
                "goal_count",
                "plan_bytes",
                "create_loop_command_bytes",
                "create_loop_max_collection_members",
                "max_materialized_goal_prompt_bytes",
                "capacity_contract_version",
            )
        },
        "external_actions": context.manifest.external_actions,
        "execution_mode": context.manifest.execution_mode,
        "forbidden_actions": tuple(context.boundary["forbidden_actions"]),
        "forbidden_paths": tuple(context.boundary["forbidden_paths"]),
        "goal": context.manifest.goal,
        "goal_count": context.capacity_report["goal_count"],
        "plan_revision": context.boundary["plan_revision"],
        "selection_reason": context.manifest.selection_reason,
        "stop_conditions": context.manifest.stop_conditions,
        "write_scope": context.manifest.write_scope,
        "workspace_identity_digest": context.manifest.workspace_identity_digest,
    }
