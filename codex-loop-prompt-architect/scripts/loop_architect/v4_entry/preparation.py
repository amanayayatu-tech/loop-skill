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
    LoopIntakeDecision,
    LoopIntakeInput,
    PreparedLoopBundle,
    PreparedLoopManifest,
    Receipt,
    canonical_bytes,
    domain_digest,
    raw_domain_digest,
)
from loop_architect.v4_artifacts import (
    ArtifactCaptureError,
    detect_artifact_profile,
    workspace_identity,
)


MANIFEST_FILENAME = "loop-manifest.json"
BOUNDARY_FILENAME = "boundary-summary.json"
PLAN_FILENAME = "CONTROLLER_PLAN.md"
INSTRUCTIONS_FILENAME = "使用说明.md"
BUNDLE_FILENAME = "prepared-bundle.json"
CONFIRMATION_FILENAME = "start-confirmation.json"
MANIFEST_VERSION = "loopskill-prepared-loop-v1"
CONFIRMATION_ISSUER = "loopskill-local-confirmation-v1"
CONFIRMATION_TRUST = "local-explicit-confirmation"
_MAX_PREPARED_FILE_BYTES = 64 * 1024
_TUPLE_FIELDS = (
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
    goal = request.goal.strip() if isinstance(request.goal, str) else ""
    if not goal:
        return LoopIntakeDecision(
            disposition="NEEDS_CLARIFICATION",
            route="UNDETERMINED",
            reason="The intended outcome is missing.",
            questions=("What observable outcome should the work produce?",),
        )
    horizon = request.task_horizon.strip().lower()
    if horizon in {"one_off", "short", "single_step"} and not request.external_actions:
        return LoopIntakeDecision(
            disposition="DIRECT_TASK_RECOMMENDED",
            route="DIRECT_TASK",
            reason="This is a bounded one-step task without durable coordination needs.",
            questions=(),
        )
    boundaries = {item.strip().lower() for item in request.authorization_boundaries}
    high_impact = {
        action.strip().lower()
        for action in request.external_actions
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
    if not request.write_scope:
        questions.append("What exact paths or surfaces may the loop modify?")
    if not request.budget.strip():
        questions.append("What time, call, token, or cost budget applies?")
    if not request.acceptance_criteria or not request.stop_conditions:
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


def _manifest_value(manifest: PreparedLoopManifest) -> dict[str, Any]:
    return asdict(manifest)


def _boundary_value(manifest: PreparedLoopManifest) -> dict[str, Any]:
    return {
        "acceptance_criteria": list(manifest.acceptance_criteria),
        "authorization_boundaries": list(manifest.authorization_boundaries),
        "artifact_profile": manifest.artifact_profile,
        "budget": manifest.budget,
        "external_actions": list(manifest.external_actions),
        "execution_mode": manifest.execution_mode,
        "goal": manifest.goal,
        "selection_reason": manifest.selection_reason,
        "stop_conditions": list(manifest.stop_conditions),
        "write_scope": list(manifest.write_scope),
    }


def _render_plan(manifest: PreparedLoopManifest, manifest_digest: str, boundary_digest: str) -> bytes:
    def lines(values: tuple[str, ...]) -> str:
        return "\n".join(f"- {value}" for value in values) or "- None"

    text = f"""# LoopSkill 4 Controller Plan

This is a human review/export view. `loop-manifest.json` is the machine source.

## Goal

{manifest.goal}

## Write scope

{lines(manifest.write_scope)}

## Budget

{manifest.budget}

## Execution mode

- {manifest.execution_mode}: {manifest.selection_reason}

## External actions

{lines(manifest.external_actions)}

## Acceptance criteria

{lines(manifest.acceptance_criteria)}

## Stop conditions

{lines(manifest.stop_conditions)}

## Authorization boundaries

{lines(manifest.authorization_boundaries)}

## Machine binding

- Manifest digest: `{manifest_digest}`
- Boundary digest: `{boundary_digest}`
- No Host task, heartbeat, delivery, or execution was created by this plan.
"""
    return text.encode("utf-8")


def _render_instructions() -> bytes:
    return (
        "# LoopSkill 4 使用说明\n\n"
        "1. 先审阅 Controller Plan 中的 Goal、写入范围、预算、外部动作、验收和停止条件。\n"
        "2. 只有内容准确时才执行显式确认；准备阶段不会创建任何 Host task 或 heartbeat。\n"
        "3. 任一准备文件变化都会使旧确认失效；请重新 prepare/confirm。\n"
        "4. 普通用户无需填写 thread、task、route、receipt、SHA 或 Host 参数。\n"
    ).encode("utf-8")


def prepare(
    request: LoopIntakeInput,
    output_directory: Path | str,
    *,
    clock: Callable[[], datetime] = _now,
    token_factory: Callable[[], str] = _token,
    workspace_root: Path | str | None = None,
) -> PreparedContext:
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
    output = Path(output_directory)
    _ensure_output_directory(output)
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
    manifest = PreparedLoopManifest(
        manifest_version=MANIFEST_VERSION,
        control_namespace=namespace,
        loop_ref=f"loop-{namespace}",
        goal=request.goal.strip(),
        task_horizon=request.task_horizon.strip().lower(),
        execution_mode=(
            "ADAPTIVE" if decision.route == "ADAPTIVE_LOOP" else "STANDARD"
        ),
        selection_reason=decision.reason,
        write_scope=tuple(request.write_scope),
        budget=request.budget.strip(),
        external_actions=tuple(request.external_actions),
        acceptance_criteria=tuple(request.acceptance_criteria),
        stop_conditions=tuple(request.stop_conditions),
        authorization_boundaries=tuple(request.authorization_boundaries),
        artifact_profile=artifact_profile,
        workspace_identity_digest=workspace_identity_digest,
        prepared_at=_iso(clock()),
    )
    manifest_value = _manifest_value(manifest)
    boundary = _boundary_value(manifest)
    manifest_bytes = canonical_bytes(manifest_value)
    boundary_bytes = canonical_bytes(boundary)
    manifest_digest = domain_digest(
        "loopskill-prepared-manifest-v1\n", manifest_value
    )
    boundary_digest = domain_digest(
        "loopskill-prepared-boundary-v1\n", boundary
    )
    plan_bytes = _render_plan(manifest, manifest_digest, boundary_digest)
    instructions_bytes = _render_instructions()
    bundle_base = {
        "boundary_digest": boundary_digest,
        "controller_plan_digest": raw_domain_digest(
            "loopskill-prepared-artifact-v1\n", plan_bytes
        ),
        "instructions_digest": raw_domain_digest(
            "loopskill-prepared-artifact-v1\n", instructions_bytes
        ),
        "manifest_digest": manifest_digest,
    }
    bundle = PreparedLoopBundle(
        **bundle_base,
        bundle_digest=domain_digest(
            "loopskill-prepared-bundle-v1\n", bundle_base
        ),
    )
    _write_once(output / MANIFEST_FILENAME, manifest_bytes)
    _write_once(output / BOUNDARY_FILENAME, boundary_bytes)
    _write_once(output / PLAN_FILENAME, plan_bytes)
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
        confirmation=None,
    )


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
        if len(raw) > _MAX_PREPARED_FILE_BYTES:
            raise ValueError("file bound")
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
        INSTRUCTIONS_FILENAME,
        BUNDLE_FILENAME,
    }
    allowed = required | {CONFIRMATION_FILENAME}
    if not required <= entries or not entries <= allowed:
        raise PreparationError(
            "USER_PREPARATION_INVALID",
            "The prepared directory contains missing or unexpected files.",
            "Preserve it for diagnostics and prepare again.",
        )
    manifest_value = _load_json(root / MANIFEST_FILENAME)
    boundary = _load_json(root / BOUNDARY_FILENAME)
    bundle_value = _load_json(root / BUNDLE_FILENAME)
    try:
        bundle = PreparedLoopBundle(**bundle_value)
    except TypeError as exc:
        raise PreparationError(
            "USER_PREPARATION_INVALID",
            "The prepared bundle shape is invalid.",
            "Run prepare again in a new empty directory.",
        ) from exc
    manifest = _manifest_from_value(manifest_value)
    expected_base = {
        "boundary_digest": domain_digest(
            "loopskill-prepared-boundary-v1\n", boundary
        ),
        "controller_plan_digest": raw_domain_digest(
            "loopskill-prepared-artifact-v1\n", (root / PLAN_FILENAME).read_bytes()
        ),
        "instructions_digest": raw_domain_digest(
            "loopskill-prepared-artifact-v1\n",
            (root / INSTRUCTIONS_FILENAME).read_bytes(),
        ),
        "manifest_digest": domain_digest(
            "loopskill-prepared-manifest-v1\n", manifest_value
        ),
    }
    expected_bundle = PreparedLoopBundle(
        **expected_base,
        bundle_digest=domain_digest(
            "loopskill-prepared-bundle-v1\n", expected_base
        ),
    )
    if bundle != expected_bundle or boundary != _boundary_value(manifest):
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
        "external_actions": context.manifest.external_actions,
        "execution_mode": context.manifest.execution_mode,
        "goal": context.manifest.goal,
        "selection_reason": context.manifest.selection_reason,
        "stop_conditions": context.manifest.stop_conditions,
        "write_scope": context.manifest.write_scope,
    }
