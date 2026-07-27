"""Thin UX facade over machine authority, Kernel, and the canonical store."""

from __future__ import annotations

import os
import secrets
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from loop_architect.v4_alpha.kernel import AuthorityContext
from loop_architect.v4_adapters.codex import CodexHostAdapter, HostUnavailable
from loop_architect.v4_adapters.codex.contract import CodexProviderPort
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
    goal_ref = f"goal-{identity('goal')}"
    author_ref = f"actor-author-{identity('author')}"
    system_ref = f"actor-system-{identity('system')}"
    create_grant_ref = f"grant-create-{identity('create-grant')}"
    observe_grant_ref = f"grant-observe-{identity('observe-grant')}"
    worker_grant_ref = f"grant-worker-{identity('worker-grant')}"
    reviewer_grant_ref = f"grant-reviewer-{identity('reviewer-grant')}"
    lifecycle_grant_ref = f"grant-lifecycle-{identity('lifecycle-grant')}"
    operation_id = f"operation-create-{identity('create-operation')}"
    external_effect_ref = f"external-effect-{identity('startup-effect')}"
    attempt_ref = f"attempt-{identity('startup-attempt')}"
    host_resource_ref = f"host-target-{identity('primary-host-resource')}"
    provider_key = f"effect-{identity('provider-idempotency')}"
    provider_target = f"codex-bootstrap-{identity('provider-target')}"
    result_ref = f"result-{identity('startup-result')}"
    report_ref = f"report-{identity('startup-report')}"
    artifact_ref = f"artifact-{identity('startup-artifact')}"
    review_ref = f"review-{identity('startup-review')}"
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
            exact_subjects=(external_effect_ref,),
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
            exact_subjects=(external_effect_ref,),
            not_before=issued_at,
            expires_at=_iso(now + timedelta(days=30)),
            nonce=f"nonce-{identity('worker-nonce')}",
            canonical_digest="",
        )
    )
    reviewer_grant = _with_digest(
        AuthorityGrant(
            grant_ref=reviewer_grant_ref,
            actor_ref=system_ref,
            issuer_actor_ref=system_ref,
            issuer_trust=LOCAL_AUTHORITY_TRUST,
            allowed_commands=("RecordReview",),
            loop_scope=loop_ref,
            subject_kinds=("ResultRef",),
            exact_subjects=(result_ref,),
            not_before=issued_at,
            expires_at=_iso(now + timedelta(days=30)),
            nonce=f"nonce-{identity('reviewer-nonce')}",
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
                "AcknowledgeResult",
                "AdvanceGoal",
                "PrepareFinalization",
                "StopLoop",
            ),
            loop_scope=loop_ref,
            subject_kinds=("ResultRef", "GoalRef", "LoopRef"),
            exact_subjects=(
                result_ref,
                report_ref,
                artifact_ref,
                review_ref,
                goal_ref,
                loop_ref,
            ),
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
    authority = AuthorityContext(
        actors=actors,
        grants={
            create_grant_ref: create_grant,
            observe_grant_ref: observe_grant,
            worker_grant_ref: worker_grant,
            reviewer_grant_ref: reviewer_grant,
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
            },
            "receipt_refs": {"receipt": prepared.confirmation.receipt_ref},
            "resolved_refs": {
                "boundary_digest": prepared.bundle.boundary_digest,
                "prepared_bundle_digest": prepared.bundle.bundle_digest,
                "prepared_manifest_digest": prepared.bundle.manifest_digest,
                "provider_action": "create_task",
                "target_ref": provider_target,
            },
        },
        semantic_payload={
            "acceptance_criteria": prepared.manifest.acceptance_criteria,
            "authorization_boundaries": prepared.manifest.authorization_boundaries,
            "budget": prepared.manifest.budget,
            "execution_mode": prepared.manifest.execution_mode,
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
) -> PreparedContext:
    try:
        return prepare(
            request,
            output_directory,
            clock=clock,
            token_factory=token_factory,
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
    loop_ref, authority, command = _machine_bootstrap(
        prepared_context,
        now=start_time,
        receipt_trust_roots=receipt_trust_roots,
    )
    path = _store_path(root)
    try:
        with SQLiteStore(path, authority) as store:
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
                store.apply(command)
                store.verify_integrity()
        if host_provider is not None:
            return _run_startup_provider(
                path,
                host_provider,
                issuer_ref=host_issuer_ref,
                issuer_trust=host_issuer_trust,
                clock=clock,
            )
        return status(root=root)
    except EntryError:
        raise
    except (OSError, PersistenceError, ProtocolRejection) as exc:
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
    if observation["status"] == "FAILED":
        return "FAILED", "Codex task ended without a valid semantic result."
    return "UNVERIFIABLE", "Codex output lacked one valid semantic result envelope."


def _allocated_subjects(store: SQLiteStore) -> dict[str, str]:
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


def sync_loop(
    *,
    root: Path | str,
    host_provider: CodexProviderPort,
    host_issuer_ref: str = DEFAULT_CODEX_RECEIPT_ISSUER,
    host_issuer_trust: str = DEFAULT_CODEX_RECEIPT_TRUST,
    clock: Callable[[], datetime] = _now,
) -> UserFacingStatus:
    """Advance the exact Host-result chain; every local step is replay-safe."""
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
            if snapshot["execution"]["state"] == "TERMINAL":
                return _status_from_store(store, loop_ref)
            if len(snapshot["external_effects"]) != 1:
                raise EntryError(
                    "USER_STORE_UNAVAILABLE",
                    "The startup Host subject is unavailable.",
                    "Preserve the store and inspect diagnostics.",
                )
            effect_ref, effect = next(iter(snapshot["external_effects"].items()))
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
            allocated = _allocated_subjects(store)
            result_ref = allocated["result"]
            artifact_ref = allocated["artifact"]
            report_ref = allocated["report"]
            review_ref = allocated["review"]
            finalization_ref = allocated["finalization"]
            observation = None
            if not snapshot["results"] or snapshot["results"][result_ref]["state"] == "STAGED":
                observation = adapter.read_task_result(provider_id)
                if observation["status"] == "PENDING":
                    if snapshot["results"]:
                        raise HostUnavailable("Codex task result regressed after staging")
                    return _status_from_store(store, loop_ref)
                outcome, summary = _result_semantics(observation)
                if snapshot["results"]:
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
                assert observation is not None
                now = clock()
                artifact_receipt = Receipt(
                    receipt_ref="receipt-artifact-" + observation["result_digest"][:24],
                    issuer_ref=host_issuer_ref,
                    issuer_trust=host_issuer_trust,
                    trust_class="strict",
                    action="verify-artifact",
                    loop_ref=loop_ref,
                    subject_ref=artifact_ref,
                    attempt_ref=effect["attempt_ref"],
                    target_ref=effect["target_ref"],
                    request_digest=observation["result_digest"],
                    provider_idempotency_key=None,
                    provider_resource_ref=provider_id,
                    outcome="observed",
                    issued_at=_iso(now),
                    expires_at=_iso(now + timedelta(minutes=5)),
                    evidence_digest=observation["result_digest"],
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
                            "resolved_refs": {},
                        },
                        semantic_payload={},
                        clock=clock,
                    )
                )
                snapshot = store.snapshot(loop_ref)
                assert snapshot is not None

            if not snapshot["reviews"]:
                verdict = "PASS" if outcome == "PASS" else "LIMITATION"
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

            goal_ref = next(iter(snapshot["goals"]))
            if snapshot["goals"][goal_ref]["state"] == "ACTIVE":
                goal_disposition = {
                    "PASS": "DONE",
                    "FAILED": "FAILED",
                    "LIMITATION": "LIMITATION",
                    "UNVERIFIABLE": "LIMITATION",
                }[outcome]
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
                            "resolved_refs": {"review_ref": review_ref},
                        },
                        semantic_payload={"disposition": goal_disposition},
                        clock=clock,
                    )
                )
                snapshot = store.snapshot(loop_ref)
                assert snapshot is not None

            final_disposition = {"PASS": "SUCCEEDED", "FAILED": "FAILED"}.get(
                outcome, "LIMITATION"
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
