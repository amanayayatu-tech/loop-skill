"""Thin UX facade over machine authority, Kernel, and the canonical store."""

from __future__ import annotations

import os
import secrets
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from loop_architect.v4_alpha.kernel import AuthorityContext, policy_context
from loop_architect.v4_adapters.codex import CodexHostAdapter, HostUnavailable
from loop_architect.v4_adapters.codex.contract import CodexProviderPort
from loop_architect.v4_artifacts import (
    ArtifactCaptureError,
    capture_artifact_transition,
    load_artifact_baseline,
    persist_baseline_blobs,
    persist_capture_blobs,
    prepare_artifact_baseline,
    verify_artifact,
    workspace_identity,
)
from loop_architect.v4_alpha.protocol import (
    ActorRef,
    AuthorityGrant,
    CommandEnvelope,
    ERROR_CODES,
    LoopIntakeDecision,
    LoopIntakeInput,
    ProtocolRejection,
    Receipt,
    UserFacingError,
    UserFacingStatus,
    authority_grant_digest,
    build_command,
    domain_digest,
    parse_json_bytes,
    snapshot_digest,
)
from loop_architect.v4_entry.preparation import (
    CONFIRMATION_ISSUER,
    CONFIRMATION_TRUST,
    PreparedContext,
    PreparationError,
    confirm_prepared,
    intake,
    intake_report,
    load_prepared,
    prepare,
)
from loop_architect.v4_persistence.sqlite_store import (
    PersistenceError,
    SCHEMA_VERSION,
    SQLiteStore,
)


LOCAL_AUTHORITY_ISSUER = "loopskill-local-authority-v1"
LOCAL_AUTHORITY_TRUST = "local-machine"
DEFAULT_CODEX_RECEIPT_ISSUER = "loopskill-codex-adapter-v1"
DEFAULT_CODEX_RECEIPT_TRUST = "local-codex-adapter"
LOCAL_ARTIFACT_ISSUER = "loopskill-local-artifact-verifier-v1"
LOCAL_ARTIFACT_TRUST = "local-artifact-capability"
STORE_FILENAME = "loopskill-v4.sqlite3"


class EntryError(Exception):
    """Exception transport around the manifest-generated public error shape."""

    def __init__(self, code: str, message: str, next_action: str) -> None:
        if code not in ERROR_CODES or not code.startswith("USER_"):
            raise ValueError("public error code is absent from typed manifest")
        self.view = UserFacingError(
            code=code, message=message, next_action=next_action
        )
        super().__init__(code)

    @property
    def code(self) -> str:
        return self.view.code

    @property
    def message(self) -> str:
        return self.view.message

    @property
    def next_action(self) -> str:
        return self.view.next_action

    def __str__(self) -> str:
        return self.code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _token() -> str:
    return secrets.token_hex(12)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _with_digest(grant: AuthorityGrant) -> AuthorityGrant:
    values = dict(grant.__dict__)
    values["canonical_digest"] = authority_grant_digest(grant)
    return AuthorityGrant(**values)


def _machine_bootstrap(
    prepared: PreparedContext,
    *,
    now: datetime,
    receipt_trust_roots: Mapping[str, str],
    artifact_profile: str | None = None,
    artifact_baseline_blob_digest: str | None = None,
    workspace_identity_digest: str | None = None,
) -> tuple[str, AuthorityContext, CommandEnvelope]:
    namespace = prepared.manifest.control_namespace
    if len(namespace) != 24 or any(
        character not in "0123456789abcdef" for character in namespace
    ):
        raise EntryError(
            "USER_INTERNAL_ERROR",
            "LoopSkill could not allocate a local identity.",
            "Retry after checking the local runtime.",
        )
    def identity(label: str) -> str:
        return domain_digest(
            "loopskill-local-control-id-v1\n",
            {"label": label, "namespace": namespace},
        )[:24]

    loop_ref = prepared.manifest.loop_ref
    if loop_ref != f"loop-{namespace}" or prepared.confirmation is None:
        raise EntryError(
            "USER_CONFIRMATION_REQUIRED",
            "A valid prepared confirmation is required before starting.",
            "Review the current boundary summary and confirm it explicitly.",
        )
    objectives = tuple(prepared.manifest.goal_plan)
    if not objectives or objectives[0] != prepared.manifest.goal:
        raise EntryError(
            "USER_PREPARATION_INVALID",
            "The prepared Goal plan no longer matches its primary Goal.",
            "Prepare and confirm the loop again.",
        )

    def chain_identity(kind: str, index: int) -> str:
        label = kind if index == 0 else f"{kind}-{index:03d}"
        return identity(label)

    goal_chains = []
    for index, objective in enumerate(objectives):
        goal_chains.append(
            {
                "artifact_ref": f"artifact-{chain_identity('startup-artifact', index)}",
                "attempt_ref": f"attempt-{chain_identity('startup-attempt', index)}",
                "external_effect_ref": f"external-effect-{chain_identity('startup-effect', index)}",
                "goal_ref": f"goal-{chain_identity('goal', index)}",
                "host_resource_ref": f"host-target-{chain_identity('primary-host-resource', index)}",
                "objective": objective,
                "provider_key": f"effect-{chain_identity('provider-idempotency', index)}",
                "provider_target": f"codex-bootstrap-{chain_identity('provider-target', index)}",
                "report_ref": f"report-{chain_identity('startup-report', index)}",
                "result_ref": f"result-{chain_identity('startup-result', index)}",
                "review_ref": f"review-{chain_identity('startup-review', index)}",
            }
        )
    primary_chain = goal_chains[0]
    goal_ref = primary_chain["goal_ref"]
    author_ref = f"actor-author-{identity('author')}"
    system_ref = f"actor-system-{identity('system')}"
    verifier_ref = f"actor-verifier-{identity('verifier')}"
    reviewer_ref = f"actor-reviewer-{identity('reviewer')}"
    create_grant_ref = f"grant-create-{identity('create-grant')}"
    observe_grant_ref = f"grant-observe-{identity('observe-grant')}"
    worker_grant_ref = f"grant-worker-{identity('worker-grant')}"
    reviewer_grant_ref = f"grant-reviewer-{identity('reviewer-grant')}"
    lifecycle_grant_ref = f"grant-lifecycle-{identity('lifecycle-grant')}"
    operation_id = f"operation-create-{identity('create-operation')}"
    external_effect_ref = primary_chain["external_effect_ref"]
    attempt_ref = primary_chain["attempt_ref"]
    host_resource_ref = primary_chain["host_resource_ref"]
    provider_key = primary_chain["provider_key"]
    provider_target = primary_chain["provider_target"]
    result_ref = primary_chain["result_ref"]
    report_ref = primary_chain["report_ref"]
    artifact_ref = primary_chain["artifact_ref"]
    review_ref = primary_chain["review_ref"]
    finalization_ref = f"finalization-{identity('startup-finalization')}"
    actors = {
        author_ref: ActorRef(
            actor_ref=author_ref,
            loop_namespace=loop_ref,
            actor_kind="author",
            identity_digest=domain_digest(
                "loopskill-local-actor-v1\n",
                {"actor_ref": author_ref, "loop_ref": loop_ref},
            ),
            issuer_ref=LOCAL_AUTHORITY_ISSUER,
            issuer_trust=LOCAL_AUTHORITY_TRUST,
        ),
        system_ref: ActorRef(
            actor_ref=system_ref,
            loop_namespace=loop_ref,
            actor_kind="system",
            identity_digest=domain_digest(
                "loopskill-local-actor-v1\n",
                {"actor_ref": system_ref, "loop_ref": loop_ref},
            ),
            issuer_ref=LOCAL_AUTHORITY_ISSUER,
            issuer_trust=LOCAL_AUTHORITY_TRUST,
        ),
        verifier_ref: ActorRef(
            actor_ref=verifier_ref,
            loop_namespace=loop_ref,
            actor_kind="local_verifier",
            identity_digest=domain_digest(
                "loopskill-local-actor-v1\n",
                {"actor_ref": verifier_ref, "loop_ref": loop_ref},
            ),
            issuer_ref=LOCAL_AUTHORITY_ISSUER,
            issuer_trust=LOCAL_AUTHORITY_TRUST,
        ),
        reviewer_ref: ActorRef(
            actor_ref=reviewer_ref,
            loop_namespace=loop_ref,
            actor_kind="reviewer",
            identity_digest=domain_digest(
                "loopskill-local-actor-v1\n",
                {"actor_ref": reviewer_ref, "loop_ref": loop_ref},
            ),
            issuer_ref=LOCAL_AUTHORITY_ISSUER,
            issuer_trust=LOCAL_AUTHORITY_TRUST,
        ),
    }
    issued_at = _iso(now)
    create_grant = _with_digest(
        AuthorityGrant(
            grant_ref=create_grant_ref,
            actor_ref=author_ref,
            issuer_actor_ref=system_ref,
            issuer_trust=LOCAL_AUTHORITY_TRUST,
            allowed_commands=("CreateLoop",),
            loop_scope=loop_ref,
            subject_kinds=("LoopRef",),
            exact_subjects=(loop_ref,),
            not_before=issued_at,
            expires_at=_iso(now + timedelta(minutes=5)),
            nonce=f"nonce-{identity('create-nonce')}",
            canonical_digest="",
        )
    )
    observe_grant = _with_digest(
        AuthorityGrant(
            grant_ref=observe_grant_ref,
            actor_ref=system_ref,
            issuer_actor_ref=system_ref,
            issuer_trust=LOCAL_AUTHORITY_TRUST,
            allowed_commands=("RecordExternalEffectObservation",),
            loop_scope=loop_ref,
            subject_kinds=("ExternalEffectRef",),
            exact_subjects=tuple(chain["external_effect_ref"] for chain in goal_chains),
            not_before=issued_at,
            expires_at=_iso(now + timedelta(days=30)),
            nonce=f"nonce-{identity('observe-nonce')}",
            canonical_digest="",
        )
    )
    worker_grant = _with_digest(
        AuthorityGrant(
            grant_ref=worker_grant_ref,
            actor_ref=system_ref,
            issuer_actor_ref=system_ref,
            issuer_trust=LOCAL_AUTHORITY_TRUST,
            allowed_commands=("StageExternalResult",),
            loop_scope=loop_ref,
            subject_kinds=("ExternalEffectRef",),
            exact_subjects=tuple(chain["external_effect_ref"] for chain in goal_chains),
            not_before=issued_at,
            expires_at=_iso(now + timedelta(days=30)),
            nonce=f"nonce-{identity('worker-nonce')}",
            canonical_digest="",
        )
    )
    reviewer_grant = _with_digest(
        AuthorityGrant(
            grant_ref=reviewer_grant_ref,
            actor_ref=reviewer_ref,
            issuer_actor_ref=system_ref,
            issuer_trust=LOCAL_AUTHORITY_TRUST,
            allowed_commands=("RecordReview",),
            loop_scope=loop_ref,
            subject_kinds=("ResultRef",),
            exact_subjects=tuple(chain["result_ref"] for chain in goal_chains),
            not_before=issued_at,
            expires_at=_iso(now + timedelta(days=30)),
            nonce=f"nonce-{identity('reviewer-nonce')}",
            canonical_digest="",
        )
    )
    artifact_grant_ref = f"grant-artifact-{identity('artifact-grant')}"
    artifact_grant = _with_digest(
        AuthorityGrant(
            grant_ref=artifact_grant_ref,
            actor_ref=verifier_ref,
            issuer_actor_ref=system_ref,
            issuer_trust=LOCAL_AUTHORITY_TRUST,
            allowed_commands=("AcknowledgeResult",),
            loop_scope=loop_ref,
            subject_kinds=("ResultRef",),
            exact_subjects=tuple(chain["result_ref"] for chain in goal_chains),
            not_before=issued_at,
            expires_at=_iso(now + timedelta(days=30)),
            nonce=f"nonce-{identity('artifact-nonce')}",
            canonical_digest="",
        )
    )
    lifecycle_grant = _with_digest(
        AuthorityGrant(
            grant_ref=lifecycle_grant_ref,
            actor_ref=author_ref,
            issuer_actor_ref=system_ref,
            issuer_trust=LOCAL_AUTHORITY_TRUST,
            allowed_commands=(
                "AdvanceGoal",
                "PauseLoop",
                "PrepareFinalization",
                "RecordPolicyDecision",
                "ResumeLoop",
                "ReviseGoalPlan",
                "StopLoop",
            ),
            loop_scope=loop_ref,
            subject_kinds=("ResultRef", "GoalRef", "LoopRef"),
            exact_subjects=tuple(
                ref
                for chain in goal_chains
                for ref in (
                    chain["result_ref"],
                    chain["report_ref"],
                    chain["artifact_ref"],
                    chain["review_ref"],
                    chain["goal_ref"],
                )
            ) + (loop_ref,),
            not_before=issued_at,
            expires_at=_iso(now + timedelta(days=30)),
            nonce=f"nonce-{identity('lifecycle-nonce')}",
            canonical_digest="",
        )
    )
    close_grant_ref = f"grant-close-{identity('close-grant')}"
    close_grant = _with_digest(
        AuthorityGrant(
            grant_ref=close_grant_ref,
            actor_ref=system_ref,
            issuer_actor_ref=system_ref,
            issuer_trust=LOCAL_AUTHORITY_TRUST,
            allowed_commands=("CloseExecution", "StrengthenClosureAssurance"),
            loop_scope=loop_ref,
            subject_kinds=("FinalizationRef",),
            exact_subjects=(finalization_ref,),
            not_before=issued_at,
            expires_at=_iso(now + timedelta(days=30)),
            nonce=f"nonce-{identity('close-nonce')}",
            canonical_digest="",
        )
    )
    trusted_receipts = dict(receipt_trust_roots)
    existing_confirmation_trust = trusted_receipts.get(CONFIRMATION_ISSUER)
    if existing_confirmation_trust not in (None, CONFIRMATION_TRUST):
        raise EntryError(
            "USER_CONFIRMATION_STALE",
            "The local confirmation trust root conflicts with this preparation.",
            "Preserve the preparation and inspect the local runtime.",
        )
    trusted_receipts[CONFIRMATION_ISSUER] = CONFIRMATION_TRUST
    existing_artifact_trust = trusted_receipts.get(LOCAL_ARTIFACT_ISSUER)
    if existing_artifact_trust not in (None, LOCAL_ARTIFACT_TRUST):
        raise EntryError(
            "USER_INTERNAL_ERROR",
            "The local artifact verifier trust root conflicts with this start.",
            "Preserve the preparation and inspect the local runtime.",
        )
    trusted_receipts[LOCAL_ARTIFACT_ISSUER] = LOCAL_ARTIFACT_TRUST
    authority = AuthorityContext(
        actors=actors,
        grants={
            create_grant_ref: create_grant,
            observe_grant_ref: observe_grant,
            worker_grant_ref: worker_grant,
            reviewer_grant_ref: reviewer_grant,
            artifact_grant_ref: artifact_grant,
            lifecycle_grant_ref: lifecycle_grant,
            close_grant_ref: close_grant,
        },
        receipts={prepared.confirmation.receipt_ref: prepared.confirmation},
        trusted_actor_issuers={LOCAL_AUTHORITY_ISSUER: LOCAL_AUTHORITY_TRUST},
        trusted_grant_issuers={system_ref: LOCAL_AUTHORITY_TRUST},
        trusted_receipt_issuers=trusted_receipts,
    )
    command = build_command(
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
                "new_attempt_ref": attempt_ref,
                "new_external_effect_ref": external_effect_ref,
                "new_goal_ref": goal_ref,
                "new_host_resource_ref": host_resource_ref,
                "provider_idempotency_key": provider_key,
                **{
                    f"goal_chain_{index:03d}_{name}": value
                    for index, chain in enumerate(goal_chains)
                    for name, value in chain.items()
                    if name != "objective"
                },
            },
            "receipt_refs": {"receipt": prepared.confirmation.receipt_ref},
            "resolved_refs": {
                "boundary_digest": prepared.bundle.boundary_digest,
                "prepared_bundle_digest": prepared.bundle.bundle_digest,
                "prepared_manifest_digest": prepared.bundle.manifest_digest,
                "provider_action": "create_task",
                "target_ref": provider_target,
                **(
                    {
                        "artifact_baseline_blob_digest": artifact_baseline_blob_digest,
                        "artifact_profile": artifact_profile,
                        "workspace_identity_digest": workspace_identity_digest,
                    }
                    if artifact_profile
                    and artifact_baseline_blob_digest
                    and workspace_identity_digest
                    else {}
                ),
            },
        },
        semantic_payload={
            "acceptance_criteria": prepared.manifest.acceptance_criteria,
            "authorization_boundaries": prepared.manifest.authorization_boundaries,
            "budget": prepared.manifest.budget,
            "execution_mode": prepared.manifest.execution_mode,
            "goal_plan": prepared.manifest.goal_plan,
            "max_roadmap_revisions": prepared.manifest.max_roadmap_revisions,
            "external_actions": prepared.manifest.external_actions,
            "objective": prepared.manifest.goal,
            "stop_conditions": prepared.manifest.stop_conditions,
            "write_scope": prepared.manifest.write_scope,
        },
    )
    return loop_ref, authority, command


def _raise_preparation_error(exc: PreparationError) -> None:
    raise EntryError(exc.code, exc.message, exc.next_action) from exc


def intake_loop(request: LoopIntakeInput) -> LoopIntakeDecision:
    return intake(request)


def intake_report_loop(request: LoopIntakeInput) -> Mapping[str, Any]:
    return intake_report(request)


def prepare_loop(
    request: LoopIntakeInput,
    output_directory: Path | str,
    *,
    clock: Callable[[], datetime] = _now,
    token_factory: Callable[[], str] = _token,
    workspace_root: Path | str | None = None,
) -> PreparedContext:
    try:
        return prepare(
            request,
            output_directory,
            clock=clock,
            token_factory=token_factory,
            workspace_root=workspace_root,
        )
    except PreparationError as exc:
        _raise_preparation_error(exc)


def confirm_loop(
    prepared_directory: Path | str,
    *,
    confirmed: bool,
    clock: Callable[[], datetime] = _now,
) -> PreparedContext:
    try:
        return confirm_prepared(
            prepared_directory,
            confirmed=confirmed,
            clock=clock,
        )
    except PreparationError as exc:
        _raise_preparation_error(exc)


def review_prepared(
    prepared_directory: Path | str,
    *,
    clock: Callable[[], datetime] = _now,
) -> PreparedContext:
    """Read and verify preparation for human display without confirming it."""
    try:
        return load_prepared(prepared_directory, clock=clock)
    except PreparationError as exc:
        _raise_preparation_error(exc)


def _store_path(root: Path | str) -> Path:
    root_path = Path(root)
    created = not root_path.exists()
    if root_path.exists() and (root_path.is_symlink() or not root_path.is_dir()):
        raise EntryError(
            "USER_STORE_UNAVAILABLE",
            "The LoopSkill data location is unavailable.",
            "Choose a private writable directory and try again.",
        )
    try:
        root_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if created:
            root_path.chmod(0o700)
        metadata = root_path.stat()
    except OSError as exc:
        raise EntryError(
            "USER_STORE_UNAVAILABLE",
            "The LoopSkill data location is unavailable.",
            "Choose a private writable directory and try again.",
        ) from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o077
    ):
        raise EntryError(
            "USER_STORE_UNAVAILABLE",
            "The LoopSkill data location is not private.",
            "Choose an owner-only directory and try again.",
        )
    return root_path / STORE_FILENAME


def _existing_store_path(root: Path | str) -> Path:
    root_path = Path(root)
    if root_path.is_symlink() or not root_path.is_dir():
        raise EntryError(
            "USER_STORE_UNAVAILABLE",
            "No readable LoopSkill loop was found.",
            "Check the selected data location.",
        )
    try:
        metadata = root_path.stat()
    except OSError as exc:
        raise EntryError(
            "USER_STORE_UNAVAILABLE",
            "No readable LoopSkill loop was found.",
            "Check the selected data location.",
        ) from exc
    if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise EntryError(
            "USER_STORE_UNAVAILABLE",
            "The LoopSkill data location is not private.",
            "Use an owner-only data location.",
        )
    path = root_path / STORE_FILENAME
    if not path.is_file() or path.is_symlink():
        raise EntryError(
            "USER_STORE_UNAVAILABLE",
            "No readable LoopSkill loop was found.",
            "Check the selected data location.",
        )
    return path


def start_loop(
    prepared: PreparedContext | Path | str,
    *,
    root: Path | str,
    clock: Callable[[], datetime] = _now,
    receipt_trust_roots: Mapping[str, str] | None = None,
    host_provider: CodexProviderPort | None = None,
    host_issuer_ref: str = DEFAULT_CODEX_RECEIPT_ISSUER,
    host_issuer_trust: str = DEFAULT_CODEX_RECEIPT_TRUST,
    workspace_root: Path | str | None = None,
) -> UserFacingStatus:
    prepared_directory = prepared.directory if isinstance(prepared, PreparedContext) else prepared
    try:
        prepared_context = load_prepared(
            prepared_directory,
            require_confirmation=True,
            clock=clock,
        )
    except PreparationError as exc:
        _raise_preparation_error(exc)
    goal = prepared_context.manifest.goal
    if receipt_trust_roots is None:
        receipt_trust_roots = {host_issuer_ref: host_issuer_trust}
    start_time = clock()
    if host_provider is not None and (
        workspace_root is None or prepared_context.manifest.artifact_profile == "UNBOUND"
    ):
        raise EntryError(
            "USER_PREPARATION_INVALID",
            "The prepared loop does not bind one artifact workspace.",
            "Prepare again from the intended workspace before starting.",
        )
    path = _store_path(root)
    try:
        with SQLiteStore(path) as store:
            descriptors = store.loop_descriptors()
            if descriptors:
                if len(descriptors) != 1 or descriptors[0]["goal"] != goal:
                    raise EntryError(
                        "USER_LOOP_EXISTS",
                        "A different loop already exists in this data location.",
                        "Run status, or choose a new data location.",
                    )
                loop_ref = descriptors[0]["loop_ref"]
            else:
                baseline = None
                baseline_digest = None
                if workspace_root is not None:
                    baseline = prepare_artifact_baseline(
                        workspace_root,
                        expected_profile=prepared_context.manifest.artifact_profile,
                        expected_workspace_identity_digest=(
                            prepared_context.manifest.workspace_identity_digest
                        ),
                    )
                    baseline_digest = persist_baseline_blobs(store, baseline)
                loop_ref, authority, command = _machine_bootstrap(
                    prepared_context,
                    now=start_time,
                    receipt_trust_roots=receipt_trust_roots,
                    artifact_profile=(None if baseline is None else baseline.profile),
                    artifact_baseline_blob_digest=baseline_digest,
                    workspace_identity_digest=(
                        None if baseline is None else baseline.workspace_identity_digest
                    ),
                )
                store.authority = authority
                store.apply(command)
                store.verify_integrity()
        if host_provider is not None:
            return _run_startup_provider(
                path,
                host_provider,
                issuer_ref=host_issuer_ref,
                issuer_trust=host_issuer_trust,
                clock=clock,
                workspace_root=workspace_root,
            )
        return status(root=root)
    except EntryError:
        raise
    except (ArtifactCaptureError, OSError, PersistenceError, ProtocolRejection) as exc:
        raise EntryError(
            "USER_STORE_UNAVAILABLE",
            "LoopSkill could not safely start the loop.",
            "Check the local data location, then retry or inspect diagnostics.",
        ) from exc


def _run_startup_provider(
    path: Path,
    provider: CodexProviderPort,
    *,
    issuer_ref: str,
    issuer_trust: str,
    clock: Callable[[], datetime],
    workspace_root: Path | str | None,
) -> UserFacingStatus:
    with SQLiteStore(path) as store:
        descriptors = store.loop_descriptors()
        if len(descriptors) != 1:
            raise EntryError(
                "USER_STORE_UNAVAILABLE",
                "The startup state is not a single-loop store.",
                "Inspect diagnostics and preserve the store.",
            )
        loop_ref = descriptors[0]["loop_ref"]
        snapshot = store.snapshot(loop_ref)
        if snapshot is None:
            raise EntryError(
                "USER_STORE_UNAVAILABLE",
                "The startup state is unavailable.",
                "Inspect diagnostics and preserve the store.",
            )
        effects = snapshot.get("external_effects", {})
        if len(effects) != 1:
            raise EntryError(
                "USER_STORE_UNAVAILABLE",
                "The startup effect is unavailable.",
                "Inspect diagnostics and preserve the store.",
            )
        effect_ref, effect = next(iter(effects.items()))
        expected_workspace = effect.get("workspace_identity_digest")
        expected_profile = effect.get("artifact_profile")
        if (
            workspace_root is None
            or not isinstance(expected_workspace, str)
            or not isinstance(expected_profile, str)
            or workspace_identity(workspace_root, expected_profile) != expected_workspace
            or store.get_blob(str(effect.get("artifact_baseline_blob_digest"))) is None
        ):
            raise EntryError(
                "USER_STORE_UNAVAILABLE",
                "The startup artifact workspace no longer matches the confirmed boundary.",
                "Preserve the store and inspect the prepared workspace binding.",
            )
        if effect["state"] == "OBSERVED":
            return _status_from_store(store, loop_ref)
        attempt = store.effect_attempt(effect["attempt_ref"])
        if attempt is None:
            raise EntryError(
                "USER_STORE_UNAVAILABLE",
                "The startup Attempt is unavailable.",
                "Inspect diagnostics and preserve the store.",
            )
        receipt = CodexHostAdapter(
            provider,
            store,
            executor_ref="loopskill-entry-executor-v1",
            issuer_ref=issuer_ref,
            issuer_trust=issuer_trust,
            clock=clock,
        ).execute(attempt)
        if (
            effect["state"] == "UNKNOWN" and receipt.outcome == "unknown"
        ) or (
            effect["state"] == "UNVERIFIABLE"
            and receipt.trust_class == "cooperative"
            and receipt.outcome != "observed"
        ):
            return _status_from_store(store, loop_ref)
    return record_external_observation(receipt, root=path.parent)


def _status_from_store(store: SQLiteStore, loop_ref: str) -> UserFacingStatus:
    descriptor = store.loop_descriptor(loop_ref)
    snapshot = store.snapshot(loop_ref)
    if descriptor is None or snapshot is None:
        raise EntryError(
            "USER_STORE_UNAVAILABLE",
            "No readable LoopSkill loop was found.",
            "Check the selected data location.",
        )
    delivery_states = {
        delivery["state"] for delivery in snapshot["deliveries"].values()
    }
    external_effect_states = {
        effect["state"] for effect in snapshot.get("external_effects", {}).values()
    }
    limitations: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = (
        "No action required; Codex Host startup is pending.",
    )
    progress = "Starting" if "ATTEMPT_COMMITTED" in external_effect_states else "Active"
    result = "Pending"
    if snapshot["execution"]["state"] == "PAUSED":
        progress = "Paused"
        next_actions = ("Resume or stop the loop after reviewing its boundary.",)
    if "UNKNOWN" in delivery_states or "UNKNOWN" in external_effect_states:
        progress = "Needs attention"
        limitations = ("An external outcome is unknown.",)
        next_actions = (
            "Wait for authoritative readback or close with a limitation.",
        )
    elif "UNVERIFIABLE" in delivery_states or "UNVERIFIABLE" in external_effect_states:
        progress = "Needs attention"
        limitations = ("An external outcome cannot be verified.",)
        next_actions = (
            "Wait for authoritative readback or close with a limitation.",
        )
    reviews = list(snapshot.get("reviews", {}).values())
    if reviews and reviews[-1].get("state") == "REPAIR":
        progress = "Needs attention"
        result = "Repair required"
        limitations = ("The verified acceptance criterion was not satisfied.",)
        next_actions = (
            "Choose a bounded repair successor, wait, or stop.",
        )
    if snapshot["execution"]["state"] == "TERMINAL":
        progress = "Finished"
        result = snapshot["execution"]["disposition"] or "Unknown"
        next_actions = ()
        if result == "LIMITATION":
            limitations = (
                "The work closed honestly without strict task-success evidence.",
            )
        elif result == "FAILED":
            limitations = ("The Host task reported a failed result.",)
    return UserFacingStatus(
        goal=descriptor["goal"],
        progress=progress,
        result=result,
        limitations=limitations,
        next_actions=next_actions,
    )


def status(*, root: Path | str) -> UserFacingStatus:
    path = _existing_store_path(root)
    try:
        with SQLiteStore(path) as store:
            descriptors = store.loop_descriptors()
            if len(descriptors) != 1:
                raise EntryError(
                    "USER_STORE_UNAVAILABLE",
                    "The LoopSkill data location is not a single-loop store.",
                    "Use diagnostics to inspect the selected data location.",
                )
            return _status_from_store(store, descriptors[0]["loop_ref"])
    except EntryError:
        raise
    except (OSError, PersistenceError, ProtocolRejection) as exc:
        raise EntryError(
            "USER_STORE_UNAVAILABLE",
            "The LoopSkill state could not be read safely.",
            "Use diagnostics or restore a verified backup.",
        ) from exc


def control_loop(
    action: str,
    *,
    root: Path | str,
    reason: str = "User requested lifecycle control.",
    clock: Callable[[], datetime] = _now,
) -> UserFacingStatus:
    """Submit one machine-authorized lifecycle command; the user supplies semantics only."""
    command_type = {
        "pause": "PauseLoop",
        "resume": "ResumeLoop",
        "stop": "StopLoop",
    }.get(action)
    if command_type is None:
        raise EntryError(
            "USER_INPUT_INVALID",
            "The lifecycle action is unsupported.",
            "Choose pause, resume, or stop.",
        )
    path = _existing_store_path(root)
    try:
        with SQLiteStore(path) as store:
            descriptors = store.loop_descriptors()
            if len(descriptors) != 1:
                raise EntryError(
                    "USER_STORE_UNAVAILABLE",
                    "The LoopSkill data location is not a single-loop store.",
                    "Preserve the store and inspect diagnostics.",
                )
            loop_ref = descriptors[0]["loop_ref"]
            snapshot = store.snapshot(loop_ref)
            if snapshot is None:
                raise EntryError(
                    "USER_STORE_UNAVAILABLE",
                    "The loop state is unavailable.",
                    "Preserve the store and inspect diagnostics.",
                )
            execution_state = snapshot["execution"]["state"]
            if (
                (command_type == "PauseLoop" and execution_state == "PAUSED")
                or (command_type == "ResumeLoop" and execution_state == "ACTIVE")
                or (command_type == "StopLoop" and execution_state == "TERMINAL")
            ):
                return _status_from_store(store, loop_ref)
            semantic_payload = {"reason": reason.strip()} if command_type != "ResumeLoop" else {}
            store.apply(
                _machine_command(
                    store,
                    snapshot,
                    command_type=command_type,
                    operation_label=f"{action}-{snapshot['loop_revision']}",
                    subject_kind="LoopRef",
                    subject_ref=loop_ref,
                    expected_subject_revisions={},
                    machine_bindings={
                        "allocate_refs": {},
                        "receipt_refs": {},
                        "resolved_refs": {},
                    },
                    semantic_payload=semantic_payload,
                    clock=clock,
                )
            )
            store.verify_integrity()
            return _status_from_store(store, loop_ref)
    except EntryError:
        raise
    except (OSError, PersistenceError, ProtocolRejection) as exc:
        raise EntryError(
            "USER_STORE_UNAVAILABLE",
            "LoopSkill could not safely apply the lifecycle action.",
            "Preserve the store and inspect diagnostics.",
        ) from exc


def policy_view(*, root: Path | str) -> Mapping[str, Any]:
    """Read the optional policy projection without granting it write authority."""
    from loop_architect.v4_policy import (
        AdaptiveRoadmap,
        GoalSpec,
        PolicyEnvelope,
        build_adaptive_roadmap,
        build_standard_queue,
        next_action,
        role_requirements,
    )

    path = _existing_store_path(root)
    with SQLiteStore(path) as store:
        descriptors = store.loop_descriptors()
        if len(descriptors) != 1:
            raise EntryError(
                "USER_STORE_UNAVAILABLE",
                "The LoopSkill data location is not a single-loop store.",
                "Preserve the store and inspect diagnostics.",
            )
        descriptor = descriptors[0]
        snapshot = store.snapshot(descriptor["loop_ref"])
        if snapshot is None:
            raise EntryError(
                "USER_STORE_UNAVAILABLE",
                "The loop state is unavailable.",
                "Preserve the store and inspect diagnostics.",
            )
        plan = snapshot.get("goal_plan")
        ordered_refs = (
            tuple(plan["ordered_goal_refs"])
            if isinstance(plan, Mapping)
            else tuple(snapshot["goals"])
        )
        goals = tuple(
            GoalSpec(
                goal_ref,
                snapshot["goals"][goal_ref]["objective_digest"],
                (() if snapshot["goals"][goal_ref].get("depends_on") is None else (
                    snapshot["goals"][goal_ref]["depends_on"],
                )),
            )
            for goal_ref in ordered_refs
        )
        envelope = PolicyEnvelope(
            allowed_goal_ids=ordered_refs,
            max_roadmap_revisions=(
                4
                if not isinstance(plan, Mapping)
                else int(plan.get("max_roadmap_revisions", 1))
            ),
        )
        attempt = next(iter(snapshot.get("attempts", {}).values()), None)
        mode = (
            str(plan["mode"])
            if isinstance(plan, Mapping)
            else "STANDARD"
            if attempt is None
            else str(attempt.get("provider_request", {}).get("execution_mode", "STANDARD"))
        )
        if mode == "ADAPTIVE":
            roadmap: AdaptiveRoadmap = build_adaptive_roadmap(
                goals,
                envelope,
                revision=(1 if not isinstance(plan, Mapping) else int(plan["revision"])),
                active_goal_id=(
                    ordered_refs[0]
                    if not isinstance(plan, Mapping)
                    else str(plan["active_goal_ref"])
                ),
            )
            policy_shape = {
                "active_goal_count": 1,
                "goal_count": len(roadmap.goals),
                "kind": "ADAPTIVE",
                "revision": roadmap.revision,
            }
        else:
            queue = build_standard_queue(goals, envelope)
            policy_shape = {
                "goal_count": len(queue),
                "kind": "STANDARD",
                "ordered_states": tuple(
                    snapshot["goals"][goal.goal_id]["state"] for goal in queue
                ),
            }
        action = next_action(snapshot)
        roles = role_requirements(
            snapshot,
            local_verification_required=any(
                artifact.get("state") != "VERIFIED"
                for artifact in snapshot.get("artifacts", {}).values()
            ),
        )
        return {
            "decision_options": _policy_options(snapshot),
            "next_action": {"kind": action.kind, "reason": action.reason},
            "policy": policy_shape,
            "repair": dict(snapshot.get("policy", {})),
            "roles": tuple(requirement.role for requirement in roles),
        }


def revise_goal_plan(
    objective_order: tuple[str, ...],
    *,
    root: Path | str,
    reason: str,
    clock: Callable[[], datetime] = _now,
) -> Mapping[str, Any]:
    """Submit one bounded Adaptive revision without exposing Goal identities."""
    normalized = tuple(item.strip() for item in objective_order if item.strip())
    if not normalized or not reason.strip():
        raise EntryError(
            "USER_INPUT_INVALID",
            "The roadmap revision requires an ordered Goal list and reason.",
            "Provide the complete prepared Goal envelope in the intended order.",
        )
    path = _existing_store_path(root)
    try:
        with SQLiteStore(path) as store:
            descriptors = store.loop_descriptors()
            if len(descriptors) != 1:
                raise EntryError(
                    "USER_STORE_UNAVAILABLE",
                    "The LoopSkill data location is not a single-loop store.",
                    "Preserve the store and inspect diagnostics.",
                )
            loop_ref = descriptors[0]["loop_ref"]
            snapshot = store.snapshot(loop_ref)
            if snapshot is None or not isinstance(snapshot.get("goal_plan"), Mapping):
                raise EntryError(
                    "USER_INPUT_INVALID",
                    "This loop has no revisable Adaptive roadmap.",
                    "Use policy status to inspect the current mode.",
                )
            plan = snapshot["goal_plan"]
            store.apply(
                _machine_command(
                    store,
                    snapshot,
                    command_type="ReviseGoalPlan",
                    operation_label=f"revise-goal-plan-{plan['revision']}",
                    subject_kind="LoopRef",
                    subject_ref=loop_ref,
                    expected_subject_revisions={"goal_plan": int(plan["revision"])},
                    machine_bindings={
                        "allocate_refs": {},
                        "receipt_refs": {},
                        "resolved_refs": {},
                    },
                    semantic_payload={
                        "objective_order": list(normalized),
                        "reason": reason.strip(),
                    },
                    clock=clock,
                )
            )
            store.verify_integrity()
        return policy_view(root=root)
    except EntryError:
        raise
    except (OSError, PersistenceError, ProtocolRejection) as exc:
        raise EntryError(
            "USER_INPUT_INVALID",
            "The roadmap revision is outside the confirmed policy envelope.",
            "Keep the active Goal first and reorder only prepared pending Goals.",
        ) from exc


def _policy_options(snapshot: Mapping[str, Any]) -> tuple[str, ...]:
    state = snapshot["execution"]["state"]
    if state == "TERMINAL":
        return ()
    options = ["STOP"]
    if state == "ACTIVE":
        options.insert(0, "WAIT")
    reviews = list(snapshot.get("reviews", {}).values())
    if (
        reviews
        and reviews[-1].get("state") == "REPAIR"
        and snapshot.get("policy", {}).get("state") != "EXHAUSTED"
    ):
        options.insert(0, "CONTINUE_REPAIR")
    return tuple(options)


def steer_loop(
    choice: str,
    *,
    root: Path | str,
    failure_fingerprint: str = "",
    clock: Callable[[], datetime] = _now,
) -> UserFacingStatus:
    """Bind one human choice to the current context without exposing control refs."""
    from loop_architect.v4_policy import (
        DecisionResponse,
        apply_decision_response,
        build_decision_card,
    )

    normalized = choice.strip().upper().replace("-", "_")
    path = _existing_store_path(root)
    try:
        with SQLiteStore(path) as store:
            descriptor = store.loop_descriptors()
            if len(descriptor) != 1:
                raise EntryError(
                    "USER_STORE_UNAVAILABLE",
                    "The LoopSkill data location is not a single-loop store.",
                    "Preserve the store and inspect diagnostics.",
                )
            loop_ref = descriptor[0]["loop_ref"]
            snapshot = store.snapshot(loop_ref)
            if snapshot is None or normalized not in _policy_options(snapshot):
                raise EntryError(
                    "USER_INPUT_INVALID",
                    "The steering choice is not valid for the current loop state.",
                    "Run policy status and choose one currently offered action.",
                )
            current = policy_context(snapshot)
            now = clock()
            goal_ref = next(iter(snapshot["goals"]))
            artifacts = tuple(snapshot.get("artifacts", {}))
            card_ref = "decision-" + domain_digest(
                "loopskill-decision-ref-v1\n", current
            )[:24]
            card = build_decision_card(
                card_ref=card_ref,
                goal_ref=goal_ref,
                artifact_ref=artifacts[-1] if artifacts else None,
                options=_policy_options(snapshot),
                current_context=current,
                expires_at=_iso(now + timedelta(minutes=5)),
            )
            response = DecisionResponse(
                card_ref=card.card_ref,
                selected_option=normalized,
                context_digest=card.context_digest,
                card_digest=card.card_digest,
                responded_at=_iso(now),
            )
            apply_decision_response(
                card,
                response,
                current_context=current,
                now=_iso(now),
            )
            result = store.apply(
                _machine_command(
                    store,
                    snapshot,
                    command_type="RecordPolicyDecision",
                    operation_label="decision-" + card.card_digest[:12],
                    subject_kind="LoopRef",
                    subject_ref=loop_ref,
                    expected_subject_revisions={
                        "execution": snapshot["execution"]["revision"]
                    },
                    machine_bindings={
                        "allocate_refs": {},
                        "receipt_refs": {},
                        "resolved_refs": {
                            "context_digest": card.context_digest,
                            "decision_card_digest": card.card_digest,
                            "repair_budget": "3",
                            "same_failure_budget": "2",
                        },
                    },
                    semantic_payload={
                        "decision": normalized,
                        "failure_fingerprint": failure_fingerprint.strip(),
                    },
                    clock=clock,
                )
            )
            store.verify_integrity()
            if normalized == "CONTINUE_REPAIR":
                authorized = bool(result.response.get("repair_authorized"))
                base = _status_from_store(store, loop_ref)
                return UserFacingStatus(
                    goal=base.goal,
                    progress="Needs attention",
                    result="Repair authorized" if authorized else "Repair exhausted",
                    limitations=(
                        "No automatic retry was sent; a separately confirmed successor is required.",
                    ),
                    next_actions=(
                        "Prepare a scoped successor or stop the loop."
                        if authorized
                        else "Wait for a user decision or stop the loop."
                    ,),
                )
        return control_loop(
            "pause" if normalized == "WAIT" else "stop",
            root=root,
            reason="Human steering decision.",
            clock=clock,
        )
    except EntryError:
        raise
    except (OSError, PersistenceError, ProtocolRejection) as exc:
        raise EntryError(
            "USER_STORE_UNAVAILABLE",
            "LoopSkill could not safely apply the human steering decision.",
            "Preserve the store and inspect diagnostics.",
        ) from exc


def record_external_observation(
    receipt: Receipt, *, root: Path | str
) -> UserFacingStatus:
    """Apply one Adapter receipt through a machine-constructed command."""
    path = _existing_store_path(root)
    try:
        with SQLiteStore(path) as store:
            snapshot = store.snapshot(receipt.loop_ref)
            if snapshot is None:
                raise EntryError(
                    "USER_STORE_UNAVAILABLE",
                    "The external observation does not match this loop.",
                    "Inspect diagnostics and the Adapter receipt source.",
                )
            effect = snapshot.get("external_effects", {}).get(receipt.subject_ref)
            if effect is None or effect["attempt_ref"] != receipt.attempt_ref:
                raise EntryError(
                    "USER_STORE_UNAVAILABLE",
                    "The external observation does not match this loop.",
                    "Inspect diagnostics and the Adapter receipt source.",
                )
            grants = [
                grant
                for grant in store.authority.grants.values()
                if grant.actor_ref in store.authority.actors
                and "RecordExternalEffectObservation" in grant.allowed_commands
                and receipt.subject_ref in grant.exact_subjects
            ]
            if len(grants) != 1:
                raise EntryError(
                    "USER_STORE_UNAVAILABLE",
                    "The startup observation authority is unavailable.",
                    "Inspect diagnostics or restore a verified backup.",
                )
            grant = grants[0]
            authority = AuthorityContext(
                actors=store.authority.actors,
                grants=store.authority.grants,
                receipts={**store.authority.receipts, receipt.receipt_ref: receipt},
                trusted_actor_issuers=store.authority.trusted_actor_issuers,
                trusted_grant_issuers=store.authority.trusted_grant_issuers,
                trusted_receipt_issuers=store.authority.trusted_receipt_issuers,
            )
            store.authority = authority
            operation_id = "operation-observe-" + domain_digest(
                "loopskill-observation-operation-v1\n",
                {
                    "effect_ref": receipt.subject_ref,
                    "receipt_ref": receipt.receipt_ref,
                },
            )[:24]
            command = build_command(
                operation_id=operation_id,
                command_type="RecordExternalEffectObservation",
                actor_ref=grant.actor_ref,
                authority_grant_ref=grant.grant_ref,
                subject={
                    "loop_ref": receipt.loop_ref,
                    "subject_kind": "ExternalEffectRef",
                    "subject_ref": receipt.subject_ref,
                },
                expected_loop_revision=snapshot["loop_revision"],
                expected_subject_revisions={
                    receipt.attempt_ref: snapshot["attempts"][receipt.attempt_ref][
                        "revision"
                    ],
                    receipt.subject_ref: effect["revision"],
                },
                issued_at=receipt.issued_at,
                machine_bindings={
                    "allocate_refs": {},
                    "receipt_refs": {"receipt": receipt.receipt_ref},
                    "resolved_refs": {},
                },
                semantic_payload={},
            )
            store.apply(command)
            store.verify_integrity()
            return _status_from_store(store, receipt.loop_ref)
    except EntryError:
        raise
    except (OSError, PersistenceError, ProtocolRejection) as exc:
        raise EntryError(
            "USER_STORE_UNAVAILABLE",
            "LoopSkill could not safely record the external observation.",
            "Inspect diagnostics and preserve the Adapter receipt.",
        ) from exc


def _grant_for(store: SQLiteStore, command_type: str, subject_ref: str) -> AuthorityGrant:
    matches = [
        grant
        for grant in store.authority.grants.values()
        if command_type in grant.allowed_commands
        and (not grant.exact_subjects or subject_ref in grant.exact_subjects)
    ]
    if len(matches) != 1:
        raise EntryError(
            "USER_STORE_UNAVAILABLE",
            "The machine authority for this transition is unavailable.",
            "Preserve the store and inspect diagnostics.",
        )
    return matches[0]


def _result_semantics(observation: Mapping[str, Any]) -> tuple[str, str]:
    text = observation["result_text"]
    marker = "LOOPSKILL4_RESULT="
    candidates = [line[len(marker) :] for line in text.splitlines() if line.startswith(marker)]
    if observation["status"] == "PENDING":
        raise ValueError("pending")
    if observation["status"] == "FAILED":
        return "FAILED", "Codex task ended without a valid semantic result."
    if len(candidates) == 1:
        try:
            value = parse_json_bytes(candidates[0].encode("utf-8"))
        except ProtocolRejection:
            value = None
        if (
            isinstance(value, Mapping)
            and set(value) == {"outcome", "summary"}
            and value["outcome"] in {"PASS", "FAILED", "LIMITATION", "UNVERIFIABLE"}
            and isinstance(value["summary"], str)
            and value["summary"].strip()
            and len(value["summary"]) <= 4096
        ):
            return str(value["outcome"]), value["summary"].strip()
    return "UNVERIFIABLE", "Codex output lacked one valid semantic result envelope."


def _allocated_subjects(
    store: SQLiteStore,
    snapshot: Mapping[str, Any] | None = None,
    goal_ref: str | None = None,
) -> dict[str, str]:
    if snapshot is not None and goal_ref is not None:
        chain = snapshot["goals"].get(goal_ref, {}).get("chain_refs")
        if isinstance(chain, Mapping):
            required = {"artifact_ref", "report_ref", "result_ref", "review_ref"}
            if required <= set(chain):
                values = {
                    kind: str(chain[f"{kind}_ref"])
                    for kind in ("result", "report", "artifact", "review")
                }
                finalizations = {
                    subject
                    for grant in store.authority.grants.values()
                    for subject in grant.exact_subjects
                    if subject.startswith("finalization-")
                }
                if len(finalizations) != 1:
                    raise EntryError(
                        "USER_STORE_UNAVAILABLE",
                        "The machine-owned finalization identity is unavailable.",
                        "Preserve the store and inspect diagnostics.",
                    )
                values["finalization"] = finalizations.pop()
                return values
    values: dict[str, str] = {}
    for kind in ("result", "report", "artifact", "review", "finalization"):
        matches = {
            subject
            for grant in store.authority.grants.values()
            for subject in grant.exact_subjects
            if subject.startswith(kind + "-")
        }
        if len(matches) != 1:
            raise EntryError(
                "USER_STORE_UNAVAILABLE",
                "The machine-owned result identity is unavailable.",
                "Preserve the store and inspect diagnostics.",
            )
        values[kind] = matches.pop()
    return values


def _machine_command(
    store: SQLiteStore,
    snapshot: Mapping[str, Any],
    *,
    command_type: str,
    operation_label: str,
    subject_kind: str,
    subject_ref: str,
    expected_subject_revisions: Mapping[str, int],
    machine_bindings: Mapping[str, Mapping[str, str]],
    semantic_payload: Mapping[str, Any],
    clock: Callable[[], datetime],
) -> CommandEnvelope:
    grant = _grant_for(store, command_type, subject_ref)
    return build_command(
        operation_id=f"operation-{operation_label}-{subject_ref.split('-', 1)[-1]}",
        command_type=command_type,
        actor_ref=grant.actor_ref,
        authority_grant_ref=grant.grant_ref,
        subject={
            "loop_ref": snapshot["loop_ref"],
            "subject_kind": subject_kind,
            "subject_ref": subject_ref,
        },
        expected_loop_revision=snapshot["loop_revision"],
        expected_subject_revisions=expected_subject_revisions,
        issued_at=_iso(clock()),
        machine_bindings=machine_bindings,
        semantic_payload=semantic_payload,
    )


def _with_receipt(store: SQLiteStore, receipt: Receipt) -> None:
    store.authority = AuthorityContext(
        actors=store.authority.actors,
        grants=store.authority.grants,
        receipts={**store.authority.receipts, receipt.receipt_ref: receipt},
        trusted_actor_issuers=store.authority.trusted_actor_issuers,
        trusted_grant_issuers=store.authority.trusted_grant_issuers,
        trusted_receipt_issuers=store.authority.trusted_receipt_issuers,
    )


def _local_artifact_receipt(
    store: SQLiteStore,
    *,
    effect: Mapping[str, Any],
    artifact_ref: str,
    loop_ref: str,
    provider_id: str,
    workspace_root: Path | str | None,
    acceptance_criteria: tuple[str, ...],
    clock: Callable[[], datetime],
) -> tuple[Receipt, Mapping[str, str], str]:
    """Capture independently of Host text and issue one artifact-bound receipt."""
    profile = str(effect.get("artifact_profile", "UNAVAILABLE"))
    baseline_digest = effect.get("artifact_baseline_blob_digest")
    capture_state = "UNAVAILABLE"
    artifact_digest = domain_digest(
        "loopskill-artifact-unavailable-v1\n",
        {"effect_ref": effect["attempt_ref"], "profile": profile},
    )
    manifest_digest = domain_digest("loopskill-artifact-manifest-v1\n", [])
    verification_digest = domain_digest(
        "loopskill-local-verification-v1\n",
        {"artifact_digest": artifact_digest, "state": "UNVERIFIABLE"},
    )
    verification_state = "UNVERIFIABLE"
    if workspace_root is not None and isinstance(baseline_digest, str):
        try:
            raw = store.get_blob(baseline_digest)
            if raw is None:
                raise ArtifactCaptureError(
                    "ARTIFACT_IDENTITY_MISMATCH", "baseline descriptor is absent"
                )
            baseline = load_artifact_baseline(raw)
            if (
                baseline.profile != profile
                or baseline.workspace_identity_digest
                != effect.get("workspace_identity_digest")
            ):
                raise ArtifactCaptureError(
                    "ARTIFACT_IDENTITY_MISMATCH", "baseline binding mismatch"
                )
            capture = capture_artifact_transition(workspace_root, baseline)
            persist_capture_blobs(store, capture)
            verification = verify_artifact(store, capture, acceptance_criteria)
            capture_state = "CAPTURED"
            artifact_digest = capture.artifact_digest
            manifest_digest = capture.manifest_digest
            verification_digest = verification.evidence_digest
            verification_state = verification.state
        except ArtifactCaptureError:
            # Absence or drift is retained as explicit UNVERIFIABLE evidence.
            pass
    strict = capture_state == "CAPTURED" and verification_state == "VERIFIED"
    now = clock()
    receipt = Receipt(
        receipt_ref="receipt-artifact-" + domain_digest(
            "loopskill-artifact-receipt-ref-v1\n",
            {
                "artifact_digest": artifact_digest,
                "artifact_ref": artifact_ref,
                "verification_digest": verification_digest,
            },
        )[:24],
        issuer_ref=LOCAL_ARTIFACT_ISSUER,
        issuer_trust=LOCAL_ARTIFACT_TRUST,
        trust_class="strict" if strict else "cooperative",
        action="verify-artifact",
        loop_ref=loop_ref,
        subject_ref=artifact_ref,
        attempt_ref=str(effect["attempt_ref"]),
        target_ref=str(effect["target_ref"]),
        request_digest=verification_digest,
        provider_idempotency_key=None,
        provider_resource_ref=provider_id,
        outcome="observed" if strict else "unverifiable",
        issued_at=_iso(now),
        expires_at=_iso(now + timedelta(minutes=5)),
        evidence_digest=artifact_digest,
    )
    return receipt, {
        "artifact_digest": artifact_digest,
        "artifact_profile": profile,
        "capture_state": capture_state,
        "manifest_digest": manifest_digest,
        "verification_digest": verification_digest,
        "verification_state": verification_state,
    }, verification_state


def sync_loop(
    *,
    root: Path | str,
    host_provider: CodexProviderPort,
    host_issuer_ref: str = DEFAULT_CODEX_RECEIPT_ISSUER,
    host_issuer_trust: str = DEFAULT_CODEX_RECEIPT_TRUST,
    clock: Callable[[], datetime] = _now,
    workspace_root: Path | str | None = None,
) -> UserFacingStatus:
    """Advance the exact Host-result chain; every local step is replay-safe."""
    path = _existing_store_path(root)
    pending_receipt = None
    with SQLiteStore(path) as store:
        descriptors = store.loop_descriptors()
        if len(descriptors) == 1:
            pending_snapshot = store.snapshot(descriptors[0]["loop_ref"])
            if pending_snapshot is not None:
                committed = [
                    effect
                    for effect in pending_snapshot.get("external_effects", {}).values()
                    if effect.get("state") == "ATTEMPT_COMMITTED"
                ]
                if len(committed) == 1:
                    pending_effect = committed[0]
                    attempt = store.effect_attempt(pending_effect["attempt_ref"])
                    if attempt is None:
                        raise EntryError(
                            "USER_STORE_UNAVAILABLE",
                            "The current Host Attempt is unavailable.",
                            "Preserve the store and inspect diagnostics.",
                        )
                    pending_receipt = CodexHostAdapter(
                        host_provider,
                        store,
                        executor_ref="loopskill-entry-executor-v1",
                        issuer_ref=host_issuer_ref,
                        issuer_trust=host_issuer_trust,
                        clock=clock,
                    ).execute(attempt)
                elif len(committed) > 1:
                    raise EntryError(
                        "USER_STORE_UNAVAILABLE",
                        "More than one Host Attempt is ready.",
                        "Preserve the store and inspect diagnostics.",
                    )
    if pending_receipt is not None:
        record_external_observation(pending_receipt, root=path.parent)
    try:
        with SQLiteStore(path) as store:
            descriptors = store.loop_descriptors()
            if len(descriptors) != 1:
                raise EntryError(
                    "USER_STORE_UNAVAILABLE",
                    "The LoopSkill data location is not a single-loop store.",
                    "Preserve the store and inspect diagnostics.",
                )
            loop_ref = descriptors[0]["loop_ref"]
            snapshot = store.snapshot(loop_ref)
            if snapshot is None:
                raise EntryError(
                    "USER_STORE_UNAVAILABLE",
                    "The loop state is unavailable.",
                    "Preserve the store and inspect diagnostics.",
                )
            if snapshot["execution"]["state"] == "TERMINAL":
                return _status_from_store(store, loop_ref)
            active_goals = [
                goal_ref
                for goal_ref, goal in snapshot["goals"].items()
                if goal.get("state") == "ACTIVE"
            ]
            if len(active_goals) == 1:
                goal_ref = active_goals[0]
                chain = snapshot["goals"][goal_ref].get("chain_refs")
                effect_ref = (
                    str(chain["external_effect_ref"])
                    if isinstance(chain, Mapping)
                    else next(iter(snapshot["external_effects"]))
                )
            elif len(active_goals) == 0 and isinstance(
                snapshot.get("current_result_ref"), str
            ):
                current_result = snapshot["results"][snapshot["current_result_ref"]]
                goal_ref = str(current_result["goal_ref"])
                effect_ref = str(current_result["external_effect_ref"])
            elif (
                len(active_goals) == 0
                and len(snapshot["goals"]) == 1
                and len(snapshot["external_effects"]) == 1
            ):
                goal_ref = next(iter(snapshot["goals"]))
                effect_ref = next(iter(snapshot["external_effects"]))
            else:
                raise EntryError(
                    "USER_STORE_UNAVAILABLE",
                    "The current Goal chain is unavailable.",
                    "Preserve the store and inspect diagnostics.",
                )
            effect = snapshot["external_effects"].get(effect_ref)
            if effect is None:
                raise EntryError(
                    "USER_STORE_UNAVAILABLE",
                    "The current Host subject is unavailable.",
                    "Preserve the store and inspect diagnostics.",
                )
            if effect["state"] != "OBSERVED":
                return _status_from_store(store, loop_ref)
            host_resource = snapshot["host_resources"].get(effect["host_resource_ref"])
            provider_id = None if host_resource is None else host_resource.get(
                "provider_resource_ref"
            )
            if not provider_id:
                raise EntryError(
                    "USER_STORE_UNAVAILABLE",
                    "The Host resource identity is unavailable.",
                    "Preserve the store and inspect diagnostics.",
                )
            adapter = CodexHostAdapter(
                host_provider,
                store,
                executor_ref="loopskill-entry-executor-v1",
                issuer_ref=host_issuer_ref,
                issuer_trust=host_issuer_trust,
                clock=clock,
            )
            allocated = _allocated_subjects(store, snapshot, goal_ref)
            result_ref = allocated["result"]
            artifact_ref = allocated["artifact"]
            report_ref = allocated["report"]
            review_ref = allocated["review"]
            finalization_ref = allocated["finalization"]
            observation = None
            if result_ref not in snapshot["results"] or snapshot["results"][result_ref]["state"] == "STAGED":
                observation = adapter.read_task_result(provider_id)
                if observation["status"] == "PENDING":
                    if result_ref in snapshot["results"]:
                        raise HostUnavailable("Codex task result regressed after staging")
                    return _status_from_store(store, loop_ref)
                outcome, summary = _result_semantics(observation)
                if result_ref in snapshot["results"]:
                    if (
                        snapshot["results"][result_ref].get("source_observation_digest")
                        != observation["result_digest"]
                    ):
                        raise ProtocolRejection(
                            "RECEIPT_IDENTITY_MISMATCH",
                            "Host result changed after local staging",
                        )
                else:
                    store.apply(
                        _machine_command(
                            store,
                            snapshot,
                            command_type="StageExternalResult",
                            operation_label="stage",
                            subject_kind="ExternalEffectRef",
                            subject_ref=effect_ref,
                            expected_subject_revisions={effect_ref: effect["revision"]},
                            machine_bindings={
                                "allocate_refs": {
                                    "new_report_ref": report_ref,
                                    "new_result_ref": result_ref,
                                },
                                "receipt_refs": {},
                                "resolved_refs": {
                                    "source_observation_digest": observation[
                                        "result_digest"
                                    ]
                                },
                            },
                            semantic_payload={"outcome": outcome, "summary": summary},
                            clock=clock,
                        )
                    )
                    snapshot = store.snapshot(loop_ref)
                    assert snapshot is not None

            result = snapshot["results"][result_ref]
            outcome = result["outcome"]
            if result["state"] == "STAGED":
                attempt = snapshot["attempts"][effect["attempt_ref"]]
                criteria = tuple(attempt["provider_request"]["acceptance_criteria"])
                artifact_receipt, artifact_bindings, _ = _local_artifact_receipt(
                    store,
                    effect=effect,
                    artifact_ref=artifact_ref,
                    loop_ref=loop_ref,
                    provider_id=provider_id,
                    workspace_root=workspace_root,
                    acceptance_criteria=criteria,
                    clock=clock,
                )
                _with_receipt(store, artifact_receipt)
                store.apply(
                    _machine_command(
                        store,
                        snapshot,
                        command_type="AcknowledgeResult",
                        operation_label="ack",
                        subject_kind="ResultRef",
                        subject_ref=result_ref,
                        expected_subject_revisions={
                            result_ref: result["revision"],
                            report_ref: snapshot["reports"][report_ref]["revision"],
                        },
                        machine_bindings={
                            "allocate_refs": {"new_artifact_ref": artifact_ref},
                            "receipt_refs": {"receipt": artifact_receipt.receipt_ref},
                            "resolved_refs": dict(artifact_bindings),
                        },
                        semantic_payload={},
                        clock=clock,
                    )
                )
                snapshot = store.snapshot(loop_ref)
                assert snapshot is not None

            if review_ref not in snapshot["reviews"]:
                artifact = snapshot["artifacts"][artifact_ref]
                verdict = (
                    "PASS"
                    if outcome == "PASS" and artifact["state"] == "VERIFIED"
                    else "REPAIR"
                    if outcome == "PASS"
                    and artifact.get("verification_state") == "FAILED"
                    else "LIMITATION"
                )
                store.apply(
                    _machine_command(
                        store,
                        snapshot,
                        command_type="RecordReview",
                        operation_label="review",
                        subject_kind="ResultRef",
                        subject_ref=result_ref,
                        expected_subject_revisions={
                            artifact_ref: snapshot["artifacts"][artifact_ref]["revision"],
                            result_ref: snapshot["results"][result_ref]["revision"],
                            report_ref: snapshot["reports"][report_ref]["revision"],
                        },
                        machine_bindings={
                            "allocate_refs": {"new_review_ref": review_ref},
                            "receipt_refs": {},
                            "resolved_refs": {},
                        },
                        semantic_payload={"verdict": verdict},
                        clock=clock,
                    )
                )
                snapshot = store.snapshot(loop_ref)
                assert snapshot is not None
                if verdict == "REPAIR":
                    return _status_from_store(store, loop_ref)

            if snapshot["goals"][goal_ref]["state"] == "ACTIVE":
                review_state = snapshot["reviews"][review_ref]["state"]
                goal_disposition = (
                    "DONE"
                    if outcome == "PASS" and review_state == "PASS"
                    else "FAILED"
                    if outcome == "FAILED"
                    else "LIMITATION"
                )
                next_baseline_bindings = {}
                plan = snapshot.get("goal_plan")
                if isinstance(plan, Mapping):
                    ordered = list(plan["ordered_goal_refs"])
                    if ordered.index(goal_ref) + 1 < len(ordered):
                        if workspace_root is None:
                            raise EntryError(
                                "USER_STORE_UNAVAILABLE",
                                "The next Goal artifact workspace is unavailable.",
                                "Preserve the loop and restore its confirmed workspace.",
                            )
                        next_baseline = prepare_artifact_baseline(
                            workspace_root,
                            expected_profile=str(effect["artifact_profile"]),
                            expected_workspace_identity_digest=str(
                                effect["workspace_identity_digest"]
                            ),
                        )
                        next_baseline_bindings = {
                            "artifact_baseline_blob_digest": persist_baseline_blobs(
                                store, next_baseline
                            ),
                            "artifact_profile": next_baseline.profile,
                            "workspace_identity_digest": next_baseline.workspace_identity_digest,
                        }
                store.apply(
                    _machine_command(
                        store,
                        snapshot,
                        command_type="AdvanceGoal",
                        operation_label="advance",
                        subject_kind="GoalRef",
                        subject_ref=goal_ref,
                        expected_subject_revisions={
                            goal_ref: snapshot["goals"][goal_ref]["revision"],
                            review_ref: snapshot["reviews"][review_ref]["revision"],
                        },
                        machine_bindings={
                            "allocate_refs": {},
                            "receipt_refs": {},
                            "resolved_refs": {
                                "review_ref": review_ref,
                                **next_baseline_bindings,
                            },
                        },
                        semantic_payload={"disposition": goal_disposition},
                        clock=clock,
                    )
                )
                snapshot = store.snapshot(loop_ref)
                assert snapshot is not None

            if any(
                goal.get("state") == "ACTIVE"
                for goal in snapshot["goals"].values()
            ):
                return _status_from_store(store, loop_ref)

            review_state = snapshot["reviews"][review_ref]["state"]
            final_disposition = (
                "SUCCEEDED"
                if outcome == "PASS" and review_state == "PASS"
                else "FAILED"
                if outcome == "FAILED"
                else "LIMITATION"
            )
            if not snapshot["finalizations"]:
                store.apply(
                    _machine_command(
                        store,
                        snapshot,
                        command_type="PrepareFinalization",
                        operation_label="finalize",
                        subject_kind="LoopRef",
                        subject_ref=loop_ref,
                        expected_subject_revisions={},
                        machine_bindings={
                            "allocate_refs": {"new_finalization_ref": finalization_ref},
                            "receipt_refs": {},
                            "resolved_refs": {},
                        },
                        semantic_payload={"disposition": final_disposition},
                        clock=clock,
                    )
                )
                snapshot = store.snapshot(loop_ref)
                assert snapshot is not None

            finalization = snapshot["finalizations"][finalization_ref]
            lifecycle_receipt = adapter.observe_finalization(
                loop_ref=loop_ref,
                finalization_ref=finalization_ref,
                provider_id=provider_id,
                subject_chain_digest=finalization["subject_chain_digest"],
            )
            _with_receipt(store, lifecycle_receipt)
            store.apply(
                _machine_command(
                    store,
                    snapshot,
                    command_type="CloseExecution",
                    operation_label="close",
                    subject_kind="FinalizationRef",
                    subject_ref=finalization_ref,
                    expected_subject_revisions={
                        finalization_ref: finalization["revision"]
                    },
                    machine_bindings={
                        "allocate_refs": {},
                        "receipt_refs": {"receipt": lifecycle_receipt.receipt_ref},
                        "resolved_refs": {},
                    },
                    semantic_payload={},
                    clock=clock,
                )
            )
            store.verify_integrity()
            return _status_from_store(store, loop_ref)
    except EntryError:
        raise
    except (
        OSError,
        PersistenceError,
        ProtocolRejection,
        HostUnavailable,
        StopIteration,
        ValueError,
    ) as exc:
        raise EntryError(
            "USER_STORE_UNAVAILABLE",
            "LoopSkill could not safely synchronize the Host result.",
            "Wait for readback or inspect diagnostics; do not restart the task.",
        ) from exc


def diagnostics(*, root: Path | str) -> dict[str, Any]:
    path = _existing_store_path(root)
    try:
        with SQLiteStore(path) as store:
            descriptors = store.loop_descriptors()
            if len(descriptors) != 1:
                raise EntryError(
                    "USER_STORE_UNAVAILABLE",
                    "The LoopSkill data location is not a single-loop store.",
                    "Check the selected data location.",
                )
            loop_ref = descriptors[0]["loop_ref"]
            snapshot = store.snapshot(loop_ref)
            if snapshot is None:
                raise EntryError(
                    "USER_STORE_UNAVAILABLE",
                    "No readable LoopSkill loop was found.",
                    "Check the selected data location.",
                )
            return {
                "events": len(store.events(loop_ref)),
                "loop_ref": loop_ref,
                "loop_revision": snapshot["loop_revision"],
                "snapshot_digest": snapshot_digest(snapshot),
                "store_schema": SCHEMA_VERSION,
            }
    except EntryError:
        raise
    except (OSError, PersistenceError, ProtocolRejection) as exc:
        raise EntryError(
            "USER_STORE_UNAVAILABLE",
            "The LoopSkill diagnostics could not be read safely.",
            "Restore a verified backup or choose a new data location.",
        ) from exc
