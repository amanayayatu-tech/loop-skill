"""Thin UX facade over machine authority, Kernel, and the canonical store."""

from __future__ import annotations

import os
import secrets
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from loop_architect.v4_alpha.kernel import (
    AuthorityContext,
    policy_context,
    policy_context_digest,
)
from loop_architect.v4_adapters.codex import CodexHostAdapter, HostUnavailable
from loop_architect.v4_adapters.codex.adapter import HOST_SCHEMA_VERSION
from loop_architect.v4_adapters.codex.contract import CodexProviderPort
from loop_architect.v4_artifacts import (
    ArtifactCaptureError,
    capture_artifact_transition,
    load_artifact_baseline,
    persist_baseline_blobs,
    persist_capture_blobs,
    prepare_artifact_baseline,
    verifier_capability,
    verify_artifact,
    workspace_identity,
)
from loop_architect.v4_alpha.protocol import (
    ActorRef,
    AuthorityGrant,
    AuthorityGrantV2,
    CAPABILITY_NAMES,
    CAPACITY_CONTRACT,
    CommandEnvelope,
    classify_persisted_storage_mode,
    ERROR_CODES,
    LoopIntakeDecision,
    LoopIntakeInput,
    ProtocolRejection,
    Receipt,
    UserFacingError,
    UserFacingStatus,
    authority_grant_digest,
    build_command,
    canonical_bytes,
    command_without_digest,
    domain_digest,
    parse_json_bytes,
    snapshot_digest,
    result_payload_schema,
    validate_result_payload,
)
from loop_architect.v4_alpha.plan_codec import (
    CompiledPlan,
    PlanCodecError,
    authority_binding_digest,
    authority_role_policy,
    build_plan_index,
    content_create_command,
    control_identity,
    derive_loop_plan_ref,
    goal_chain,
    materialize_provider_request,
    max_collection_members,
    parse_plan_bytes,
    plan_digest,
    repair_chain,
    validate_plan_index,
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


class _LocalGateProvider:
    """Strict process-local evidence adapter for an already-authorized controller gate."""

    def __init__(
        self,
        gate_digest: str,
        *,
        clock: Callable[[], datetime],
        outcome: str = "PASS",
    ) -> None:
        self.gate_digest = gate_digest
        self.clock = clock
        self.outcome = outcome
        self.record: dict[str, Any] | None = None

    def capability_snapshot(self) -> Mapping[str, Any]:
        now = self.clock()
        rows = []
        for name in CAPABILITY_NAMES:
            rows.append(
                {
                    "assurance": "STRICT",
                    "availability": "AVAILABLE",
                    "details": {
                        "expires_at": _iso(now + timedelta(minutes=5)),
                        "identity_ref": "local-gate-" + self.gate_digest[:24],
                        "issuer_ref": DEFAULT_CODEX_RECEIPT_ISSUER,
                        "issuer_trust": DEFAULT_CODEX_RECEIPT_TRUST,
                        "observed_at": _iso(now - timedelta(seconds=1)),
                        "source": "loopskill-local-gate-v1",
                    },
                    "name": name,
                    "receipt_ref": "capability-gate-"
                    + domain_digest(
                        "loopskill-local-gate-capability-v1\n",
                        {"gate_digest": self.gate_digest, "name": name},
                    )[:24],
                }
            )
        return {"capabilities": rows, "schema_version": HOST_SCHEMA_VERSION}

    def invoke(
        self,
        action: str,
        payload: Mapping[str, Any],
        provider_idempotency_key: str,
    ) -> Mapping[str, Any]:
        provider_id = "local-gate-" + self.gate_digest[:24]
        self.record = {
            "action": action,
            "idempotency_key": provider_idempotency_key,
            "provider_id": provider_id,
            "schema_version": HOST_SCHEMA_VERSION,
            "status": "OBSERVED",
            "subject_id": payload["target_ref"],
            "trust": "authoritative",
        }
        return {**self.record, "status": "ACCEPTED", "trust": "cooperative"}

    def readback(
        self, action: str, provider_idempotency_key: str
    ) -> Mapping[str, Any] | None:
        if (
            self.record is None
            or self.record["action"] != action
            or self.record["idempotency_key"] != provider_idempotency_key
        ):
            return None
        return dict(self.record)

    def read_resource(self, resource_kind: str, provider_id: str) -> Mapping[str, Any]:
        matched = self.record is not None and self.record["provider_id"] == provider_id
        return {
            "provider_id": provider_id,
            "resource_kind": resource_kind,
            "schema_version": HOST_SCHEMA_VERSION,
            "state": "TERMINAL" if matched else "NOT_FOUND",
            "trust": "authoritative" if matched else "none",
        }

    def read_task_result(self, provider_id: str) -> Mapping[str, Any]:
        if self.record is None or self.record["provider_id"] != provider_id:
            raise HostUnavailable("Local gate evidence is unavailable")
        result = {
            "outcome": self.outcome,
            "summary": (
                "The bound controller gate was satisfied."
                if self.outcome == "PASS"
                else "The optional capability is unavailable in the prepared profile."
            ),
        }
        schema_digest = domain_digest(
            "loopskill-codex-result-schema-v1\n", result_payload_schema()
        )
        return {
            "provider_id": provider_id,
            "result": result,
            "result_digest": domain_digest(
                "loopskill-host-result-v1\n",
                {"result": result, "result_schema_digest": schema_digest},
            ),
            "result_schema_digest": schema_digest,
            "schema_version": HOST_SCHEMA_VERSION,
            "status": "COMPLETED",
            "trust": "authoritative",
        }


class EntryError(Exception):
    """Exception transport around the manifest-generated public error shape."""

    def __init__(self, code: str, message: str, next_action: str) -> None:
        public_codes = {
            "PATH_CONFINEMENT_VIOLATION",
            "RESOURCE_LIMIT_EXCEEDED",
            "STORE_RECOVERY_REQUIRED",
            *(item for item in ERROR_CODES if item.startswith("USER_")),
        }
        if code not in public_codes:
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


def _with_digest(
    grant: AuthorityGrant | AuthorityGrantV2,
) -> AuthorityGrant | AuthorityGrantV2:
    values = dict(grant.__dict__)
    values["canonical_digest"] = authority_grant_digest(grant)
    return type(grant)(**values)


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
    loop_ref = prepared.manifest.loop_ref
    if loop_ref != f"loop-{namespace}" or prepared.confirmation is None:
        raise EntryError(
            "USER_CONFIRMATION_REQUIRED",
            "A valid prepared confirmation is required before starting.",
            "Review the current boundary summary and confirm it explicitly.",
        )
    plan_raw = canonical_bytes(prepared.plan)
    index_raw = canonical_bytes(prepared.plan_index)
    compiled = CompiledPlan(
        plan=prepared.plan,
        plan_bytes=plan_raw,
        plan_digest=plan_digest(plan_raw),
        goal_slice_digests=tuple(
            str(item) for item in prepared.plan_index["ordered_goal_slice_digests"]
        ),
        index=prepared.plan_index,
        index_bytes=index_raw,
        index_digest=plan_digest(index_raw),
    )
    if (
        compiled.plan_digest != prepared.manifest.plan_digest
        or compiled.index_digest != prepared.manifest.plan_index_digest
        or prepared.plan_index["workspace_binding"]
        != prepared.manifest.workspace_identity_digest
    ):
        raise EntryError(
            "USER_PREPARATION_INVALID",
            "The prepared plan identity no longer matches its confirmation.",
            "Prepare and confirm the loop again.",
        )
    expected_authority_digest = authority_binding_digest(
        loop_ref=loop_ref,
        plan_identity=compiled.plan_digest,
        goal_count=len(compiled.plan["goals"]),
        workspace_binding=prepared.manifest.workspace_identity_digest,
        roadmap_mode=prepared.manifest.execution_mode,
    )
    if prepared.plan_index["authority_digest"] != expected_authority_digest:
        raise EntryError(
            "USER_CONFIRMATION_STALE",
            "The prepared authority binding no longer matches this plan.",
            "Prepare and confirm the loop again.",
        )

    def identity(label: str) -> str:
        return control_identity(namespace, label)

    author_ref = f"actor-author-{identity('author')}"
    system_ref = f"actor-system-{identity('system')}"
    verifier_ref = f"actor-verifier-{identity('verifier')}"
    reviewer_ref = f"actor-reviewer-{identity('reviewer')}"
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
    issued_at = prepared.manifest.prepared_at
    try:
        issued_time = datetime.fromisoformat(issued_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EntryError(
            "USER_PREPARATION_INVALID",
            "The prepared authority timestamp is invalid.",
            "Prepare and confirm the loop again.",
        ) from exc
    selector_base = {
        "goal_index_max": len(compiled.plan["goals"]) - 1,
        "goal_index_min": 0,
        "mode": "PLAN_DERIVED_V1",
        "plan_digest": compiled.plan_digest,
    }

    def grant(
        role: str,
        actor_ref: str,
        commands: tuple[str, ...],
        kinds: tuple[str, ...],
        *,
        include_loop_scope: bool,
    ) -> AuthorityGrantV2:
        value = AuthorityGrantV2(
            schema="loopskill-authority-grant-v2",
            grant_ref=f"grant-{role}-{identity(role + '-grant')}",
            actor_ref=actor_ref,
            issuer_actor_ref=system_ref,
            issuer_trust=LOCAL_AUTHORITY_TRUST,
            allowed_commands=commands,
            loop_scope=loop_ref,
            subject_kinds=kinds,
            subject_selector={
                **selector_base,
                "include_loop_scope": include_loop_scope,
            },
            not_before=issued_at,
            expires_at=_iso(issued_time + timedelta(days=30)),
            nonce=f"nonce-{identity(role + '-nonce')}",
            canonical_digest="",
        )
        result = _with_digest(value)
        assert isinstance(result, AuthorityGrantV2)
        return result

    actor_roles = {
        "author": author_ref,
        "reviewer": reviewer_ref,
        "system": system_ref,
        "verifier": verifier_ref,
    }
    grants_by_role = {
        role: grant(
            role,
            actor_roles[str(policy["actor"])],
            tuple(policy["commands"]),
            tuple(policy["kinds"]),
            include_loop_scope=bool(policy["include_loop_scope"]),
        )
        for role, policy in authority_role_policy().items()
    }
    create_grant = grants_by_role["create"]
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
            item.grant_ref: item for item in grants_by_role.values()
        },
        receipts={prepared.confirmation.receipt_ref: prepared.confirmation},
        trusted_actor_issuers={LOCAL_AUTHORITY_ISSUER: LOCAL_AUTHORITY_TRUST},
        trusted_grant_issuers={system_ref: LOCAL_AUTHORITY_TRUST},
        trusted_receipt_issuers=trusted_receipts,
    )
    command = content_create_command(
        namespace=namespace,
        loop_ref=loop_ref,
        compiled=compiled,
        issued_at=_iso(now),
        confirmation_receipt_ref=prepared.confirmation.receipt_ref,
        manifest_digest=prepared.bundle.manifest_digest,
        boundary_digest=prepared.bundle.boundary_digest,
        bundle_digest=prepared.bundle.bundle_digest,
        artifact_profile=artifact_profile or "UNBOUND",
        artifact_baseline_blob_digest=artifact_baseline_blob_digest,
    )
    raw_command = command_without_digest(command)
    if (
        len(canonical_bytes(raw_command))
        > int(CAPACITY_CONTRACT["create_loop_target_bytes"])
        or max_collection_members(raw_command)
        > int(CAPACITY_CONTRACT["create_loop_target_collection_members"])
    ):
        raise EntryError(
            "RESOURCE_LIMIT_EXCEEDED",
            "The exact START command exceeds the confirmed release target.",
            "Preserve the preparation and report this preparation drift.",
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
                if (
                    len(descriptors) != 1
                    or descriptors[0]["goal"] != goal
                    or descriptors[0]["loop_ref"]
                    != prepared_context.manifest.loop_ref
                ):
                    raise EntryError(
                        "USER_LOOP_EXISTS",
                        "A different loop already exists in this data location.",
                        "Run status, or choose a new data location.",
                    )
                loop_ref = descriptors[0]["loop_ref"]
                existing = store.snapshot(loop_ref)
                plan_state = None if existing is None else existing.get("goal_plan")
                if (
                    not isinstance(plan_state, Mapping)
                    or plan_state.get("plan_digest")
                    != prepared_context.manifest.plan_digest
                    or plan_state.get("storage_mode") != "CONTENT_ADDRESSED_V1"
                    or plan_state.get("workspace_binding")
                    != prepared_context.manifest.workspace_identity_digest
                    or plan_state.get("authority_digest")
                    != prepared_context.plan_index["authority_digest"]
                    or set(plan_state.get("ordered_goal_ids", ()))
                    != set(prepared_context.plan_index["ordered_goal_ids"])
                    or store.get_blob(prepared_context.manifest.plan_digest)
                    != canonical_bytes(prepared_context.plan)
                    or store.get_blob(prepared_context.manifest.plan_index_digest)
                    != canonical_bytes(prepared_context.plan_index)
                ):
                    raise EntryError(
                        "STORE_RECOVERY_REQUIRED",
                        "The existing loop cannot read back its confirmed plan blobs.",
                        "Preserve the store and restore an exact private backup.",
                    )
                store.verify_integrity()
            else:
                plan_raw = canonical_bytes(prepared_context.plan)
                index_raw = canonical_bytes(prepared_context.plan_index)
                stored_plan = store.put_blob(plan_raw)
                stored_index = store.put_blob(index_raw)
                if (
                    stored_plan != prepared_context.manifest.plan_digest
                    or stored_index != prepared_context.manifest.plan_index_digest
                    or store.get_blob(stored_plan) != plan_raw
                    or store.get_blob(stored_index) != index_raw
                ):
                    raise EntryError(
                        "STORE_RECOVERY_REQUIRED",
                        "The runtime Store could not verify the confirmed plan blobs.",
                        "Preserve the store and inspect local storage integrity.",
                    )
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


def _pause_for_provider_budget(
    store: SQLiteStore,
    snapshot: Mapping[str, Any],
    *,
    loop_ref: str,
    provider: CodexProviderPort,
    attempt: Any,
    clock: Callable[[], datetime],
) -> UserFacingStatus | None:
    checker = getattr(provider, "budget_block_reason", None)
    if not callable(checker):
        return None
    reason = checker(attempt.payload)
    if reason is None:
        return None
    if not isinstance(reason, str) or not reason:
        raise EntryError(
            "USER_INTERNAL_ERROR",
            "The runtime budget preflight returned invalid evidence.",
            "Preserve the Loop and inspect the Provider budget evidence.",
        )
    if snapshot["execution"]["state"] == "ACTIVE":
        store.apply(
            _machine_command(
                store,
                snapshot,
                command_type="PauseLoop",
                operation_label="budget-wait-" + str(snapshot["loop_revision"]),
                subject_kind="LoopRef",
                subject_ref=loop_ref,
                expected_subject_revisions={
                    "execution": snapshot["execution"]["revision"]
                },
                machine_bindings={
                    "allocate_refs": {},
                    "receipt_refs": {},
                    "resolved_refs": {},
                },
                semantic_payload={
                    "reason": "Plan-bound runtime budget requires an extension.",
                    "wait_kind": "BUDGET",
                },
                clock=clock,
            )
        )
        store.verify_integrity()
    return _status_from_store(store, loop_ref)


def _run_startup_provider(
    path: Path,
    provider: CodexProviderPort,
    *,
    issuer_ref: str,
    issuer_trust: str,
    clock: Callable[[], datetime],
    workspace_root: Path | str | None,
    allow_gate_execution: bool = False,
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
        active_goals = [
            goal_ref
            for goal_ref, goal_state in snapshot["goals"].items()
            if goal_state.get("state") == "ACTIVE"
        ]
        if len(active_goals) == 1:
            content = _content_goal(store, snapshot, active_goals[0])
            if (
                not allow_gate_execution
                and
                content is not None
                and content[0].get("schema") == "loopskill-plan-v2"
                and content[2].get("gate") in {"human", "time"}
            ):
                if snapshot["execution"]["state"] == "ACTIVE":
                    store.apply(
                        _machine_command(
                            store,
                            snapshot,
                            command_type="PauseLoop",
                            operation_label="wait-gate-" + content[2]["goal_id"],
                            subject_kind="LoopRef",
                            subject_ref=loop_ref,
                            expected_subject_revisions={},
                            machine_bindings={
                                "allocate_refs": {},
                                "receipt_refs": {},
                                "resolved_refs": {},
                            },
                            semantic_payload={
                                "reason": "Controller gate requires bound evidence.",
                                "wait_kind": content[2]["gate"].upper(),
                            },
                            clock=clock,
                        )
                    )
                return _status_from_store(store, loop_ref)
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
        optional_provider = _optional_skip_provider(
            store, snapshot, effect=effect, clock=clock
        )
        effective_provider = optional_provider or provider
        if optional_provider is None:
            budget_wait = _pause_for_provider_budget(
                store,
                snapshot,
                loop_ref=loop_ref,
                provider=provider,
                attempt=attempt,
                clock=clock,
            )
            if budget_wait is not None:
                return budget_wait
        receipt = CodexHostAdapter(
            effective_provider,
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
    view = record_external_observation(receipt, root=path.parent)
    if optional_provider is not None:
        return sync_loop(
            root=path.parent,
            host_provider=optional_provider,
            workspace_root=workspace_root,
            clock=clock,
        )
    return view


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
        wait_kind = snapshot["execution"].get("wait_kind")
        next_actions = ("Resume or stop the loop after reviewing its boundary.",)
        active = [
            goal_ref
            for goal_ref, goal_state in snapshot["goals"].items()
            if goal_state.get("state") == "ACTIVE"
        ]
        if len(active) == 1:
            content = _content_goal(store, snapshot, active[0])
            gate = None if content is None else content[2].get("gate")
            if gate == "human":
                progress = "Waiting"
                result = "WAITING_HUMAN"
                next_actions = (
                    "Record one digest-bound human approval, then continue this Loop.",
                )
            elif gate == "time":
                progress = "Waiting"
                result = "WAITING_TIME"
                next_actions = ("Continue after the declared real-time boundary.",)
        if wait_kind in {"BLOCKED", "FAILURE"}:
            progress = "Waiting"
            result = "WAITING"
            next_actions = (
                "Resolve the recorded blocker, then continue this Loop.",
            )
        elif wait_kind == "BUDGET":
            progress = "Waiting"
            result = "WAITING_BUDGET"
            next_actions = (
                "Authorize a digest-bound budget extension before continuing.",
            )
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
        repair_state = snapshot.get("policy", {}).get("state")
        if repair_state == "REPAIR_SCHEDULED":
            progress = "Active"
            result = "Repair scheduled"
            limitations = ()
            next_actions = ("Continue the current Loop to run its bounded repair.",)
        else:
            progress = (
                "Waiting"
                if snapshot["execution"]["state"] == "PAUSED"
                else "Needs attention"
            )
            result = (
                "WAITING_REPAIR"
                if snapshot["execution"]["state"] == "PAUSED"
                else "Repair required"
            )
            limitations = ("The verified acceptance criterion was not satisfied.",)
            next_actions = ("Resume after reviewing the bounded repair evidence.",)
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
        elif result == "SUCCEEDED_WITH_LIMITATIONS":
            limitations = (
                "The required Goals passed; at least one optional Goal was skipped with evidence.",
            )
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


def extend_budget(
    *,
    root: Path | str,
    new_max_host_invocations: int,
    new_wall_clock_seconds: int,
    reason: str,
    clock: Callable[[], datetime] = _now,
) -> UserFacingStatus:
    """Resume one budget-waiting Plan v2 Loop with a digest-bound increase."""

    if (
        isinstance(new_max_host_invocations, bool)
        or not isinstance(new_max_host_invocations, int)
        or isinstance(new_wall_clock_seconds, bool)
        or not isinstance(new_wall_clock_seconds, int)
        or not reason.strip()
        or len(reason) > 512
    ):
        raise EntryError(
            "USER_INPUT_INVALID",
            "The runtime budget extension is invalid.",
            "Provide larger bounded invocation and active-compute limits with a reason.",
        )
    path = _existing_store_path(root)
    try:
        with SQLiteStore(path) as store:
            descriptors = store.loop_descriptors()
            if len(descriptors) != 1:
                raise EntryError(
                    "USER_STORE_UNAVAILABLE",
                    "The selected data location is not one Loop.",
                    "Select one exact Loop and try again.",
                )
            loop_ref = descriptors[0]["loop_ref"]
            snapshot = store.snapshot(loop_ref)
            if (
                snapshot is None
                or snapshot["execution"].get("state") != "PAUSED"
                or snapshot["execution"].get("wait_kind") != "BUDGET"
                or not isinstance(snapshot.get("goal_plan"), Mapping)
                or not isinstance(snapshot["goal_plan"].get("budget"), Mapping)
            ):
                raise EntryError(
                    "USER_INPUT_INVALID",
                    "This Loop is not waiting for a runtime budget extension.",
                    "Inspect status and extend only the current budget-bound wait.",
                )
            budget = snapshot["goal_plan"]["budget"]
            prior_budget_digest = domain_digest(
                "loopskill-runtime-budget-v1\n",
                {
                    "max_host_invocations": budget["max_host_invocations"],
                    "wall_clock_seconds": budget["wall_clock_seconds"],
                },
            )
            reason_digest = domain_digest(
                "loopskill-budget-extension-reason-v1\n", reason.strip()
            )
            extension_request_digest = domain_digest(
                "loopskill-budget-extension-request-v1\n",
                {
                    "new_max_host_invocations": new_max_host_invocations,
                    "new_wall_clock_seconds": new_wall_clock_seconds,
                    "prior_budget_digest": prior_budget_digest,
                    "reason_digest": reason_digest,
                },
            )
            store.apply(
                _machine_command(
                    store,
                    snapshot,
                    command_type="ResumeLoop",
                    operation_label="extend-budget-" + extension_request_digest[:16],
                    subject_kind="LoopRef",
                    subject_ref=loop_ref,
                    expected_subject_revisions={
                        "execution": snapshot["execution"]["revision"]
                    },
                    machine_bindings={
                        "allocate_refs": {},
                        "receipt_refs": {},
                        "resolved_refs": {},
                    },
                    semantic_payload={
                        "new_max_host_invocations": new_max_host_invocations,
                        "new_wall_clock_seconds": new_wall_clock_seconds,
                        "prior_budget_digest": prior_budget_digest,
                        "reason_digest": reason_digest,
                    },
                    clock=clock,
                )
            )
            store.verify_integrity()
            return _status_from_store(store, loop_ref)
    except EntryError:
        raise
    except (OSError, PersistenceError, ProtocolRejection) as exc:
        raise EntryError(
            "USER_INPUT_INVALID",
            "LoopSkill rejected the runtime budget extension.",
            "Increase only the current limits and keep the confirmed task scope unchanged.",
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
        if (
            isinstance(plan, Mapping)
            and plan.get("storage_mode") == "CONTENT_ADDRESSED_V1"
        ):
            registered = {
                str(goal.get("goal_id")): str(goal.get("state"))
                for goal in snapshot["goals"].values()
            }
            ordered_states = tuple(
                registered.get(str(goal_id), "PENDING")
                for goal_id in plan["ordered_goal_ids"]
            )
            if plan["mode"] == "ADAPTIVE":
                policy_shape = {
                    "active_goal_count": sum(
                        state == "ACTIVE" for state in ordered_states
                    ),
                    "goal_count": int(plan["goal_count"]),
                    "kind": "ADAPTIVE",
                    "revision": int(plan["revision"]),
                }
            else:
                policy_shape = {
                    "goal_count": int(plan["goal_count"]),
                    "kind": "STANDARD",
                    "ordered_states": ordered_states,
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
            if plan.get("storage_mode") == "CONTENT_ADDRESSED_V1":
                plan_raw = store.get_blob(str(plan["plan_digest"]))
                index_raw = store.get_blob(str(plan["plan_index_digest"]))
                if plan_raw is None or index_raw is None:
                    raise EntryError(
                        "STORE_RECOVERY_REQUIRED",
                        "The Adaptive plan blobs are unavailable.",
                        "Preserve the Store and restore an exact private backup.",
                    )
                plan_document = parse_plan_bytes(plan_raw)
                current_index = validate_plan_index(
                    parse_json_bytes(index_raw), plan_document
                )
                objective_to_id: dict[str, str] = {}
                for goal in plan_document["goals"]:
                    objective = str(goal["objective"])
                    if objective in objective_to_id:
                        raise EntryError(
                            "USER_INPUT_INVALID",
                            "Objective text is ambiguous in this plan.",
                            "Use distinct Goal objectives before preparing the loop.",
                        )
                    objective_to_id[objective] = str(goal["goal_id"])
                try:
                    ordered_ids = [objective_to_id[item] for item in normalized]
                except KeyError as exc:
                    raise EntryError(
                        "USER_INPUT_INVALID",
                        "The revision contains a Goal outside the confirmed plan.",
                        "Reorder only the complete confirmed Goal set.",
                    ) from exc
                next_revision = int(plan["revision"]) + 1
                revised_index = build_plan_index(
                    plan_document,
                    plan_identity=str(plan["plan_digest"]),
                    workspace_binding=str(plan["workspace_binding"]),
                    authority_digest=str(plan["authority_digest"]),
                    revision=next_revision,
                    ordered_goal_ids=ordered_ids,
                )
                revised_raw = canonical_bytes(revised_index)
                revised_digest = store.put_blob(revised_raw)
                if store.get_blob(revised_digest) != revised_raw:
                    raise EntryError(
                        "STORE_RECOVERY_REQUIRED",
                        "The revised PlanIndex failed immutable readback.",
                        "Preserve the Store and inspect local storage integrity.",
                    )
                semantic_payload = {
                    "ordered_goal_ids": list(revised_index["ordered_goal_ids"]),
                    "ordered_goal_slice_digests": list(
                        revised_index["ordered_goal_slice_digests"]
                    ),
                    "plan_index_digest": revised_digest,
                    "plan_revision": next_revision,
                    "reason": reason.strip(),
                }
                operation_label = "revise-goal-plan-" + domain_digest(
                    "loopskill-plan-index-revision-operation-v1\n",
                    {
                        "from_index_digest": str(plan["plan_index_digest"]),
                        "loop_ref": loop_ref,
                        "to_index_digest": revised_digest,
                    },
                )[:24]
            else:
                semantic_payload = {
                    "objective_order": list(normalized),
                    "reason": reason.strip(),
                }
                operation_label = f"revise-goal-plan-{plan['revision']}"
            store.apply(
                _machine_command(
                    store,
                    snapshot,
                    command_type="ReviseGoalPlan",
                    operation_label=operation_label,
                    subject_kind="LoopRef",
                    subject_ref=loop_ref,
                    expected_subject_revisions={"goal_plan": int(plan["revision"])},
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
        return policy_view(root=root)
    except EntryError:
        raise
    except (OSError, PersistenceError, PlanCodecError, ProtocolRejection) as exc:
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
                and (
                    isinstance(grant, AuthorityGrantV2)
                    or receipt.subject_ref in grant.exact_subjects
                )
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
                persisted_storage_mode=classify_persisted_storage_mode(snapshot),
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


def _grant_for(
    store: SQLiteStore, command_type: str, subject_ref: str
) -> AuthorityGrant | AuthorityGrantV2:
    matches = [
        grant
        for grant in store.authority.grants.values()
        if command_type in grant.allowed_commands
        and (
            isinstance(grant, AuthorityGrantV2)
            or not grant.exact_subjects
            or subject_ref in grant.exact_subjects
        )
    ]
    if len(matches) != 1:
        raise EntryError(
            "USER_STORE_UNAVAILABLE",
            "The machine authority for this transition is unavailable.",
            "Preserve the store and inspect diagnostics.",
        )
    return matches[0]


def _result_semantics(observation: Mapping[str, Any]) -> tuple[str, str]:
    if observation["status"] == "PENDING":
        raise ValueError("pending")
    if observation["status"] == "FAILED":
        return "FAILED", "Codex task ended without a valid semantic result."
    try:
        value = validate_result_payload(observation["result"])
    except (KeyError, ProtocolRejection):
        return "UNVERIFIABLE", "Codex output lacked one valid structured result."
    return value["outcome"], value["summary"]


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
                plan = snapshot.get("goal_plan")
                if (
                    isinstance(plan, Mapping)
                    and plan.get("storage_mode") == "CONTENT_ADDRESSED_V1"
                ):
                    values["finalization"] = derive_loop_plan_ref(
                        str(snapshot["loop_ref"]),
                        str(plan["plan_digest"]),
                        "FinalizationRef",
                    )
                else:
                    finalizations = {
                        subject
                        for grant in store.authority.grants.values()
                        if isinstance(grant, AuthorityGrant)
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
            if isinstance(grant, AuthorityGrant)
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
        persisted_storage_mode=classify_persisted_storage_mode(snapshot),
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
            verification = verify_artifact(
                store,
                capture,
                acceptance_criteria,
                workspace_root=workspace_root,
            )
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


def _content_goal(
    store: SQLiteStore,
    snapshot: Mapping[str, Any],
    goal_ref: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]] | None:
    plan_state = snapshot.get("goal_plan")
    if (
        not isinstance(plan_state, Mapping)
        or plan_state.get("storage_mode") != "CONTENT_ADDRESSED_V1"
    ):
        return None
    plan_raw = store.get_blob(str(plan_state["plan_digest"]))
    index_raw = store.get_blob(str(plan_state["plan_index_digest"]))
    if plan_raw is None or index_raw is None:
        raise EntryError(
            "STORE_RECOVERY_REQUIRED",
            "The current Goal plan blobs are unavailable.",
            "Preserve the Store and restore an exact private backup.",
        )
    plan_document = parse_plan_bytes(plan_raw)
    index_document = validate_plan_index(parse_json_bytes(index_raw), plan_document)
    goal_state = snapshot["goals"].get(goal_ref)
    if not isinstance(goal_state, Mapping):
        raise EntryError(
            "STORE_RECOVERY_REQUIRED",
            "The active Goal descriptor is unavailable.",
            "Preserve the Store and inspect its immutable evidence.",
        )
    goal_id = str(goal_state.get("goal_id", ""))
    goal_document = next(
        (goal for goal in plan_document["goals"] if goal["goal_id"] == goal_id),
        None,
    )
    if goal_document is None:
        raise EntryError(
            "STORE_RECOVERY_REQUIRED",
            "The active Goal is absent from the immutable plan.",
            "Preserve the Store and inspect its immutable evidence.",
        )
    return plan_document, index_document, goal_document


def _unavailable_goal_capabilities(
    plan: Mapping[str, Any],
    goal: Mapping[str, Any],
    *,
    artifact_profile: str,
) -> tuple[str, ...]:
    profile = plan["worker_profile"]
    available = {"workspace-write"}
    if artifact_profile != "UNBOUND":
        available.add("artifact-capture")
    if artifact_profile in {"existing_git", "new_git"}:
        available.add("git")
    if profile["network_access"]:
        available.add("network")
    if profile["local_verification"]:
        available.update({"local-command", "local-http"})
    declared = set(goal["capabilities"])
    for verifier in goal["verifiers"]:
        try:
            capability = verifier_capability(verifier)
        except (ArtifactCaptureError, ValueError):
            capability = None
        if capability is None:
            declared.add("unsupported-verifier")
        else:
            declared.add(capability)
    if goal["gate"] in {"human", "time"}:
        declared.discard(goal["gate"] + "-gate")
    return tuple(sorted(declared - available))


def _optional_skip_provider(
    store: SQLiteStore,
    snapshot: Mapping[str, Any],
    *,
    effect: Mapping[str, Any],
    clock: Callable[[], datetime],
) -> _LocalGateProvider | None:
    active = [
        goal_ref
        for goal_ref, value in snapshot["goals"].items()
        if value.get("state") == "ACTIVE"
    ]
    if len(active) != 1:
        return None
    content = _content_goal(store, snapshot, active[0])
    if content is None or content[0].get("schema") != "loopskill-plan-v2":
        return None
    plan, _, goal = content
    if goal["requirement"] != "optional" or goal["gate"] != "worker":
        return None
    unavailable = _unavailable_goal_capabilities(
        plan,
        goal,
        artifact_profile=str(effect.get("artifact_profile", "UNBOUND")),
    )
    if not unavailable:
        return None
    digest = domain_digest(
        "loopskill-optional-capability-skip-v1\n",
        {
            "goal_id": goal["goal_id"],
            "loop_ref": snapshot["loop_ref"],
            "plan_digest": snapshot["goal_plan"]["plan_digest"],
            "unavailable": list(unavailable),
        },
    )
    return _LocalGateProvider(digest, clock=clock, outcome="LIMITATION")


def satisfy_gate(
    *,
    root: Path | str,
    workspace_root: Path | str,
    approval_digest: str | None = None,
    clock: Callable[[], datetime] = _now,
) -> UserFacingStatus:
    """Satisfy one paused Plan v2 human/time gate with bound local evidence."""

    path = _existing_store_path(root)
    with SQLiteStore(path) as store:
        descriptors = store.loop_descriptors()
        if len(descriptors) != 1:
            raise EntryError(
                "USER_STORE_UNAVAILABLE",
                "The selected data location is not a single Loop.",
                "Select one exact Loop and try again.",
            )
        loop_ref = descriptors[0]["loop_ref"]
        snapshot = store.snapshot(loop_ref)
        active = [] if snapshot is None else [
            goal_ref
            for goal_ref, value in snapshot["goals"].items()
            if value.get("state") == "ACTIVE"
        ]
        if (
            snapshot is None
            or snapshot["execution"]["state"] != "PAUSED"
            or len(active) != 1
        ):
            raise EntryError(
                "USER_INPUT_INVALID",
                "The Loop is not waiting at one controller gate.",
                "Read status before supplying gate evidence.",
            )
        content = _content_goal(store, snapshot, active[0])
        if content is None or content[0].get("schema") != "loopskill-plan-v2":
            raise EntryError(
                "USER_INPUT_INVALID",
                "The active Goal has no Plan v2 controller gate.",
                "Read status and continue through the available action.",
            )
        goal = content[2]
        gate = goal["gate"]
        if gate == "human":
            if (
                not isinstance(approval_digest, str)
                or len(approval_digest) != 64
                or any(character not in "0123456789abcdef" for character in approval_digest)
            ):
                raise EntryError(
                    "USER_INPUT_INVALID",
                    "A human gate requires one lowercase SHA-256 approval digest.",
                    "Bind the approval to the reviewed Goal and artifact summary.",
                )
            evidence = {"approval_digest": approval_digest, "gate": gate}
        elif gate == "time":
            declarations = [
                value[len("time-after:") :]
                for value in goal["verifiers"]
                if value.startswith("time-after:")
            ]
            if len(declarations) != 1:
                raise EntryError(
                    "USER_PREPARATION_INVALID",
                    "The time gate lacks one exact time-after verifier.",
                    "Prepare a successor with one timezone-aware real-time boundary.",
                )
            due = datetime.fromisoformat(declarations[0].replace("Z", "+00:00"))
            if clock().astimezone(timezone.utc) < due.astimezone(timezone.utc):
                return _status_from_store(store, loop_ref)
            evidence = {"gate": gate, "time_after": _iso(due)}
        else:
            raise EntryError(
                "USER_INPUT_INVALID",
                "The active Goal is not a human or time gate.",
                "Continue the worker Goal normally.",
            )
        gate_digest = domain_digest(
            "loopskill-controller-gate-v1\n",
            {
                **evidence,
                "goal_id": goal["goal_id"],
                "goal_slice_digest": snapshot["goals"][active[0]]["goal_slice_digest"],
                "loop_ref": loop_ref,
                "plan_digest": content[1]["plan_digest"],
            },
        )
    control_loop("resume", root=root, clock=clock)
    provider = _LocalGateProvider(gate_digest, clock=clock)
    _run_startup_provider(
        path,
        provider,
        issuer_ref=DEFAULT_CODEX_RECEIPT_ISSUER,
        issuer_trust=DEFAULT_CODEX_RECEIPT_TRUST,
        clock=clock,
        workspace_root=workspace_root,
        allow_gate_execution=True,
    )
    return sync_loop(
        root=root,
        host_provider=provider,
        workspace_root=workspace_root,
        clock=clock,
    )


def _schedule_repair_attempt(
    store: SQLiteStore,
    snapshot: Mapping[str, Any],
    *,
    goal_ref: str,
    workspace_root: Path | str,
    failure_fingerprint: str,
    clock: Callable[[], datetime],
) -> bool:
    content = _content_goal(store, snapshot, goal_ref)
    if content is None:
        return False
    plan_document, index_document, goal_document = content
    if plan_document.get("schema") != "loopskill-plan-v2":
        return False
    if goal_document["on_failure"] != "repair":
        return False
    policy = snapshot.get("policy", {})
    repair_attempts = int(policy.get("repair_attempts", 0))
    repair_budget = int(goal_document["max_attempts"]) - 1
    if repair_budget < 1 or repair_attempts >= repair_budget:
        return False
    plan_state = snapshot["goal_plan"]
    if len(snapshot["attempts"]) >= int(plan_state["budget"]["max_host_invocations"]):
        return False
    baseline = prepare_artifact_baseline(
        workspace_root,
        expected_profile=str(
            snapshot["external_effects"][
                snapshot["goals"][goal_ref]["chain_refs"]["external_effect_ref"]
            ]["artifact_profile"]
        ),
        expected_workspace_identity_digest=str(plan_state["workspace_binding"]),
    )
    baseline_digest = persist_baseline_blobs(store, baseline)
    repair_ordinal = repair_attempts + 1
    chain = repair_chain(
        str(snapshot["loop_ref"]),
        str(plan_state["plan_digest"]),
        goal_ref,
        str(goal_document["goal_id"]),
        repair_ordinal,
    )
    provider_request = materialize_provider_request(
        plan_document,
        index_document,
        int(plan_state["active_index"]),
        target_ref=chain["provider_target"],
        artifact_digest=baseline_digest,
        prior_disposition="REPAIR",
    )
    result = store.apply(
        _machine_command(
            store,
            snapshot,
            command_type="RecordPolicyDecision",
            operation_label=f"repair-{repair_ordinal}",
            subject_kind="LoopRef",
            subject_ref=str(snapshot["loop_ref"]),
            expected_subject_revisions={
                "execution": snapshot["execution"]["revision"]
            },
            machine_bindings={
                "allocate_refs": {
                    "new_artifact_ref": chain["artifact_ref"],
                    "new_attempt_ref": chain["attempt_ref"],
                    "new_external_effect_ref": chain["external_effect_ref"],
                    "new_host_resource_ref": chain["host_resource_ref"],
                    "new_report_ref": chain["report_ref"],
                    "new_result_ref": chain["result_ref"],
                    "new_review_ref": chain["review_ref"],
                    "provider_idempotency_key": chain["provider_key"],
                },
                "receipt_refs": {},
                "resolved_refs": {
                    "artifact_baseline_blob_digest": baseline_digest,
                    "artifact_profile": baseline.profile,
                    "context_digest": policy_context_digest(snapshot),
                    "decision_card_digest": domain_digest(
                        "loopskill-automatic-repair-card-v1\n",
                        {
                            "failure_fingerprint": failure_fingerprint,
                            "goal_ref": goal_ref,
                            "loop_revision": snapshot["loop_revision"],
                            "repair_ordinal": repair_ordinal,
                        },
                    ),
                    "provider_request_digest": domain_digest(
                        "loopskill-provider-request-v1\n", provider_request
                    ),
                    "repair_budget": str(repair_budget),
                    "same_failure_budget": "2",
                    "target_ref": chain["provider_target"],
                    "workspace_identity_digest": baseline.workspace_identity_digest,
                },
            },
            semantic_payload={
                "decision": "CONTINUE_REPAIR",
                "failure_fingerprint": failure_fingerprint,
            },
            clock=clock,
        )
    )
    store.verify_integrity()
    return bool(result.response.get("repair_authorized")) and bool(
        result.response.get("repair_state") == "REPAIR_SCHEDULED"
    )


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
    effective_host_provider = host_provider
    with SQLiteStore(path) as store:
        descriptors = store.loop_descriptors()
        if len(descriptors) == 1:
            pending_snapshot = store.snapshot(descriptors[0]["loop_ref"])
            if pending_snapshot is not None:
                if pending_snapshot["execution"]["state"] == "PAUSED":
                    return _status_from_store(store, descriptors[0]["loop_ref"])
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
                    optional_provider = _optional_skip_provider(
                        store,
                        pending_snapshot,
                        effect=pending_effect,
                        clock=clock,
                    )
                    if optional_provider is not None:
                        effective_host_provider = optional_provider
                    else:
                        budget_wait = _pause_for_provider_budget(
                            store,
                            pending_snapshot,
                            loop_ref=descriptors[0]["loop_ref"],
                            provider=effective_host_provider,
                            attempt=attempt,
                            clock=clock,
                        )
                        if budget_wait is not None:
                            return budget_wait
                    pending_receipt = CodexHostAdapter(
                        effective_host_provider,
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
                effective_host_provider,
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
            summary = ""
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
                materialized_attempt = store.effect_attempt(effect["attempt_ref"])
                if materialized_attempt is None:
                    raise EntryError(
                        "STORE_RECOVERY_REQUIRED",
                        "The current Goal request cannot be materialized.",
                        "Preserve the Store and restore its exact plan blobs.",
                    )
                current_content = _content_goal(store, snapshot, goal_ref)
                current_goal_document = (
                    None if current_content is None else current_content[2]
                )
                criteria = tuple(
                    ("no-file-change",)
                    if current_goal_document is not None
                    and current_goal_document.get("gate") in {"human", "time"}
                    else current_goal_document["verifiers"]
                    if current_goal_document is not None
                    and "verifiers" in current_goal_document
                    else materialized_attempt.payload["acceptance_criteria"]
                )
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
                current_content = _content_goal(store, snapshot, goal_ref)
                current_goal_document = (
                    None if current_content is None else current_content[2]
                )
                is_v2_goal = bool(
                    current_content is not None
                    and current_content[0].get("schema") == "loopskill-plan-v2"
                )
                repair_requested = (
                    is_v2_goal
                    and current_goal_document is not None
                    and current_goal_document.get("on_failure") == "repair"
                    and outcome in {"FAILED"}
                )
                verdict = (
                    "PASS"
                    if outcome == "PASS" and artifact["state"] == "VERIFIED"
                    else "REPAIR"
                    if repair_requested
                    or (
                        outcome == "PASS"
                        and (
                            (
                                not is_v2_goal
                                and artifact.get("verification_state") == "FAILED"
                            )
                            or (
                                is_v2_goal
                                and artifact.get("verification_state")
                                in {"FAILED", "UNVERIFIABLE"}
                                and current_goal_document is not None
                                and current_goal_document.get("on_failure") == "repair"
                            )
                        )
                    )
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
                    fingerprint = domain_digest(
                        "loopskill-repair-failure-v1\n",
                        {
                            "goal_ref": goal_ref,
                            "outcome": outcome,
                            "verification_digest": snapshot["artifacts"][artifact_ref][
                                "verification_digest"
                            ],
                        },
                    )
                    scheduled = (
                        workspace_root is not None
                        and _schedule_repair_attempt(
                            store,
                            snapshot,
                            goal_ref=goal_ref,
                            workspace_root=workspace_root,
                            failure_fingerprint=fingerprint,
                            clock=clock,
                        )
                    )
                    if scheduled:
                        return _status_from_store(store, loop_ref)
                    if is_v2_goal:
                        snapshot = store.snapshot(loop_ref)
                        assert snapshot is not None
                        store.apply(
                            _machine_command(
                                store,
                                snapshot,
                                command_type="PauseLoop",
                                operation_label="repair-wait",
                                subject_kind="LoopRef",
                                subject_ref=loop_ref,
                                expected_subject_revisions={},
                                machine_bindings={
                                    "allocate_refs": {},
                                    "receipt_refs": {},
                                    "resolved_refs": {},
                                },
                                semantic_payload={
                                    "reason": "Repair budget exhausted or repeated failure.",
                                    "wait_kind": "REPAIR",
                                },
                                clock=clock,
                            )
                        )
                    return _status_from_store(store, loop_ref)

            if snapshot["goals"][goal_ref]["state"] == "ACTIVE":
                review_state = snapshot["reviews"][review_ref]["state"]
                current_content = _content_goal(store, snapshot, goal_ref)
                current_goal_document = (
                    None if current_content is None else current_content[2]
                )
                blocked_wait = (
                    current_goal_document is not None
                    and review_state == "LIMITATION"
                    and outcome in {"BLOCKED", "LIMITATION", "UNVERIFIABLE"}
                    and current_goal_document.get("on_blocked") == "wait"
                )
                failure_wait = (
                    current_goal_document is not None
                    and outcome == "FAILED"
                    and current_goal_document.get("on_failure") == "wait"
                )
                if blocked_wait or failure_wait:
                    if blocked_wait and not summary:
                        try:
                            replayed_observation = adapter.read_task_result(provider_id)
                            if (
                                replayed_observation.get("status") == "COMPLETED"
                                and replayed_observation.get("result_digest")
                                == result.get("source_observation_digest")
                            ):
                                _, summary = _result_semantics(replayed_observation)
                        except HostUnavailable:
                            # The Loop can still stop safely at a generic wait.  A
                            # missing readback must never trigger another Host call.
                            summary = ""
                    budget_wait = blocked_wait and "budget" in summary.casefold()
                    store.apply(
                        _machine_command(
                            store,
                            snapshot,
                            command_type="PauseLoop",
                            operation_label=(
                                "failure-wait" if failure_wait else "blocked-wait"
                            ),
                            subject_kind="LoopRef",
                            subject_ref=loop_ref,
                            expected_subject_revisions={},
                            machine_bindings={
                                "allocate_refs": {},
                                "receipt_refs": {},
                                "resolved_refs": {},
                            },
                            semantic_payload={
                                "reason": (
                                    "Goal failed and awaits a safe recovery decision."
                                    if failure_wait
                                    else "Goal is blocked and awaits a safe recovery decision."
                                ),
                                "wait_kind": (
                                    "FAILURE"
                                    if failure_wait
                                    else "BUDGET"
                                    if budget_wait
                                    else "BLOCKED"
                                ),
                            },
                            clock=clock,
                        )
                    )
                    return _status_from_store(store, loop_ref)
                goal_disposition = (
                    "DONE"
                    if outcome == "PASS" and review_state == "PASS"
                    else "SKIPPED"
                    if current_goal_document is not None
                    and current_goal_document.get("requirement") == "optional"
                    and current_goal_document.get("on_blocked") == "skip"
                    and review_state == "LIMITATION"
                    and outcome in {"BLOCKED", "LIMITATION", "UNVERIFIABLE"}
                    else "FAILED"
                    if outcome == "FAILED"
                    else "LIMITATION"
                )
                next_allocate: dict[str, str] = {}
                next_resolved: dict[str, str] = {"review_ref": review_ref}
                advance_operation_label = "advance"
                expected_plan_revision: dict[str, int] = {}
                plan = snapshot.get("goal_plan")
                if (
                    goal_disposition in {"DONE", "SKIPPED"}
                    and isinstance(plan, Mapping)
                    and plan.get("storage_mode") == "CONTENT_ADDRESSED_V1"
                ):
                    active_index = int(plan["active_index"])
                    next_index = active_index + 1
                    ordered_ids = list(plan["ordered_goal_ids"])
                    if next_index < len(ordered_ids):
                        if workspace_root is None:
                            raise EntryError(
                                "USER_STORE_UNAVAILABLE",
                                "The next Goal artifact workspace is unavailable.",
                                "Preserve the loop and restore its confirmed workspace.",
                            )
                        plan_raw = store.get_blob(str(plan["plan_digest"]))
                        index_raw = store.get_blob(str(plan["plan_index_digest"]))
                        if plan_raw is None or index_raw is None:
                            raise EntryError(
                                "STORE_RECOVERY_REQUIRED",
                                "The next Goal plan blobs are unavailable.",
                                "Preserve the Store and restore an exact private backup.",
                            )
                        plan_document = parse_plan_bytes(plan_raw)
                        index_document = validate_plan_index(
                            parse_json_bytes(index_raw), plan_document
                        )
                        if (
                            index_document["revision"] != plan["revision"]
                            or index_document["ordered_goal_ids"]
                            != list(plan["ordered_goal_ids"])
                            or index_document["ordered_goal_slice_digests"]
                            != list(plan["ordered_goal_slice_digests"])
                        ):
                            raise EntryError(
                                "STORE_RECOVERY_REQUIRED",
                                "The active PlanIndex does not match the canonical snapshot.",
                                "Preserve the Store and inspect its immutable evidence.",
                            )
                        next_goal_id = str(ordered_ids[next_index])
                        next_slice_digest = str(
                            index_document["ordered_goal_slice_digests"][next_index]
                        )
                        next_goal = next(
                            item
                            for item in plan_document["goals"]
                            if item["goal_id"] == next_goal_id
                        )
                        next_chain = goal_chain(
                            loop_ref,
                            str(plan["plan_digest"]),
                            next_goal_id,
                            next_slice_digest,
                        )
                        next_baseline = prepare_artifact_baseline(
                            workspace_root,
                            expected_profile=str(effect["artifact_profile"]),
                            expected_workspace_identity_digest=str(
                                effect["workspace_identity_digest"]
                            ),
                        )
                        next_baseline_digest = persist_baseline_blobs(
                            store, next_baseline
                        )
                        provider_request = materialize_provider_request(
                            plan_document,
                            index_document,
                            next_index,
                            target_ref=next_chain["provider_target"],
                            artifact_digest=next_baseline_digest,
                            prior_disposition=goal_disposition,
                        )
                        next_allocate = {
                            "new_attempt_ref": next_chain["attempt_ref"],
                            "new_external_effect_ref": next_chain[
                                "external_effect_ref"
                            ],
                            "new_goal_ref": next_chain["goal_ref"],
                            "new_host_resource_ref": next_chain[
                                "host_resource_ref"
                            ],
                            "provider_idempotency_key": next_chain["provider_key"],
                        }
                        next_resolved.update(
                            {
                                "artifact_baseline_blob_digest": next_baseline_digest,
                                "artifact_profile": next_baseline.profile,
                                "next_goal_id": next_goal_id,
                                "next_goal_slice_digest": next_slice_digest,
                                "next_objective_digest": domain_digest(
                                    "loopskill-goal-objective-v1\n",
                                    next_goal["objective"],
                                ),
                                "plan_digest": str(plan["plan_digest"]),
                                "plan_index_digest": str(
                                    plan["plan_index_digest"]
                                ),
                                "provider_request_digest": domain_digest(
                                    "loopskill-provider-request-v1\n",
                                    provider_request,
                                ),
                                "provider_target": next_chain["provider_target"],
                                "workspace_identity_digest": (
                                    next_baseline.workspace_identity_digest
                                ),
                            }
                        )
                        if plan_document.get("schema") == "loopskill-plan-v2":
                            next_resolved.update(
                                {
                                    "next_goal_requirement": str(
                                        next_goal["requirement"]
                                    ),
                                    "next_max_attempts": str(
                                        next_goal["max_attempts"]
                                    ),
                                }
                            )
                    expected_plan_revision = {"goal_plan": int(plan["revision"])}
                    advance_operation_label = "advance-" + domain_digest(
                        "loopskill-advance-operation-v1\n",
                        {
                            "current_goal_ref": goal_ref,
                            "loop_ref": loop_ref,
                            "next_goal_ref": next_allocate.get("new_goal_ref"),
                            "plan_digest": plan["plan_digest"],
                            "plan_index_digest": plan["plan_index_digest"],
                            "plan_revision": plan["revision"],
                        },
                    )[:24]
                elif goal_disposition == "DONE" and isinstance(plan, Mapping):
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
                        next_resolved.update({
                            "artifact_baseline_blob_digest": persist_baseline_blobs(
                                store, next_baseline
                            ),
                            "artifact_profile": next_baseline.profile,
                            "workspace_identity_digest": next_baseline.workspace_identity_digest,
                        })
                store.apply(
                    _machine_command(
                        store,
                        snapshot,
                        command_type="AdvanceGoal",
                        operation_label=advance_operation_label,
                        subject_kind="GoalRef",
                        subject_ref=goal_ref,
                        expected_subject_revisions={
                            goal_ref: snapshot["goals"][goal_ref]["revision"],
                            review_ref: snapshot["reviews"][review_ref]["revision"],
                            **expected_plan_revision,
                        },
                        machine_bindings={
                            "allocate_refs": next_allocate,
                            "receipt_refs": {},
                            "resolved_refs": next_resolved,
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
            goal_states = {
                goal.get("state") for goal in snapshot["goals"].values()
            }
            final_disposition = (
                "FAILED"
                if "FAILED" in goal_states
                else "SUCCEEDED_WITH_LIMITATIONS"
                if "SKIPPED" in goal_states
                and goal_states <= {"DONE", "SKIPPED"}
                else "SUCCEEDED"
                if outcome == "PASS" and review_state == "PASS"
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


def worker_profile(*, root: Path | str) -> Mapping[str, Any]:
    """Read the active Plan-bound worker profile without exposing plan content."""

    path = _existing_store_path(root)
    try:
        with SQLiteStore(path) as store:
            descriptors = store.loop_descriptors()
            if len(descriptors) != 1:
                raise EntryError(
                    "USER_STORE_UNAVAILABLE",
                    "The selected data location is not one Loop.",
                    "Select one Loop and try again.",
                )
            snapshot = store.snapshot(descriptors[0]["loop_ref"])
            if snapshot is None:
                raise EntryError(
                    "USER_STORE_UNAVAILABLE",
                    "The Loop state is unavailable.",
                    "Preserve the Store and inspect diagnostics.",
                )
            plan_state = snapshot.get("goal_plan")
            if isinstance(plan_state, Mapping):
                raw = store.get_blob(str(plan_state.get("plan_digest", "")))
                if raw is not None:
                    plan = parse_plan_bytes(raw)
                    if plan.get("schema") == "loopskill-plan-v2":
                        profile = dict(plan["worker_profile"])
                        runtime_budget = plan_state.get("budget")
                        if isinstance(runtime_budget, Mapping):
                            profile["budget_override"] = {
                                "max_host_invocations": runtime_budget[
                                    "max_host_invocations"
                                ],
                                "wall_clock_seconds": runtime_budget[
                                    "wall_clock_seconds"
                                ],
                            }
                        return profile
            return {
                "attempt_timeout_seconds": 30_000,
                "local_verification": True,
                "model": None,
                "network_access": False,
                "reasoning_effort": None,
                "sandbox": "workspace-write",
            }
    except EntryError:
        raise
    except (OSError, PersistenceError, PlanCodecError, ProtocolRejection) as exc:
        raise EntryError(
            "USER_STORE_UNAVAILABLE",
            "The Plan-bound worker profile is unavailable.",
            "Preserve the Store and inspect diagnostics.",
        ) from exc
