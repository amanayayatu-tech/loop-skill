"""Fixture-safe v3.3.8 reader and one-way v4 import anti-corruption layer."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from loop_architect.v4_alpha.kernel import AuthorityContext
from loop_architect.v4_alpha.protocol import (
    ActorRef,
    AuthorityGrant,
    CommandEnvelope,
    ERROR_CODES,
    ProtocolRejection,
    V3ImportPreview,
    V3ImportResult,
    authority_grant_digest,
    build_command,
    domain_digest,
    snapshot_digest,
)
from loop_architect.v4_persistence.sqlite_store import (
    PersistenceError,
    SQLiteStore,
)


PUBLIC_V3_BASE_SHA = "843945d9d34e7f065b65d9172ea4a2df66c0f2e3"
PUBLIC_V3_PRODUCT_VERSION = "v3.3.8"
V3_RUNTIME_BLOB_SHA = "450375ada1a28125143bda2084ccc11419453182"
V3_STATE_SCHEMA_BLOB_SHA = "96540acf071b2fa3bd0926b34622340777fba501"
V3_MUTATION_SCHEMA_BLOB_SHA = "8bb328582226270e697632850d7b09c901360e13"
V3_STATE_RELATIVE_PATH = Path(".codex-loop") / "LOOP_STATE.md"
STORE_FILENAME = "loopskill-v4.sqlite3"
IMPORT_AUTHORITY_ISSUER = "loopskill-v3-import-authority-v1"
IMPORT_AUTHORITY_TRUST = "local-v3-import"
MAX_V3_STATE_BYTES = 4 * 1024 * 1024
_OUTBOX_FIELDS = (
    "dispatch_outbox",
    "automation_outbox",
    "controller_goal_outbox",
    "thread_creation_outbox",
    "assurance_dispatch_outbox",
    "local_verification_outbox",
    "roadmap_change_outbox",
    "delegation_ledger",
)


class V3CompatibilityError(RuntimeError):
    """A stable manifest-owned rejection from the read/import boundary."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in ERROR_CODES or not (
            code.startswith("MIGRATION_") or code == "DUAL_WRITE_FORBIDDEN"
        ):
            raise ValueError("compatibility error code is not manifest-owned")
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class V3ImportPlan:
    """Machine-held preview; callers never transcribe its control identity."""

    preview: V3ImportPreview
    source_goal_id: str
    source_root: Path
    destination_root: Path
    issued_at: str


@dataclass(frozen=True)
class _SourceProjection:
    source_loop_id: str
    source_schema_version: int
    source_state_version: int
    source_state_digest: str
    source_goal_id: str
    goal: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _reject_constant(_: str) -> Any:
    raise ValueError("non-finite JSON number")


def _reject_float(_: str) -> Any:
    raise ValueError("floating-point JSON number")


def _closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _decode_v3_state(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise V3CompatibilityError(
            "MIGRATION_SOURCE_INVALID", "v3 state is not strict UTF-8"
        ) from exc
    prefix = "STATE_JSON_BEGIN\n"
    suffix = "\nSTATE_JSON_END\n"
    if not text.startswith(prefix) or not text.endswith(suffix):
        raise V3CompatibilityError(
            "MIGRATION_SOURCE_INVALID", "v3 state fence is invalid"
        )
    payload = text[len(prefix) : -len(suffix)]
    try:
        state = json.loads(
            payload,
            object_pairs_hook=_closed_object,
            parse_constant=_reject_constant,
            parse_float=_reject_float,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise V3CompatibilityError(
            "MIGRATION_SOURCE_INVALID", "v3 state JSON is invalid"
        ) from exc
    if not isinstance(state, dict):
        raise V3CompatibilityError(
            "MIGRATION_SOURCE_INVALID", "v3 state is not an object"
        )
    canonical = json.dumps(
        state,
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
        indent=2,
    )
    if f"{prefix}{canonical}{suffix}".encode("utf-8") != raw:
        raise V3CompatibilityError(
            "MIGRATION_SOURCE_INVALID", "v3 state encoding is noncanonical"
        )
    return state


@contextlib.contextmanager
def _source_lock(source_root: Path) -> Iterator[None]:
    descriptor: int | None = None
    try:
        metadata = source_root.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise OSError("unsafe source root")
        descriptor = os.open(
            source_root,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise V3CompatibilityError(
            "MIGRATION_SOURCE_INVALID", "v3 source layout is unavailable"
        ) from exc
    try:
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _read_source_bytes(source_root: Path) -> bytes:
    try:
        source_meta = source_root.lstat()
        control = source_root / ".codex-loop"
        control_meta = control.lstat()
        state_path = source_root / V3_STATE_RELATIVE_PATH
        before_path = state_path.lstat()
    except OSError as exc:
        raise V3CompatibilityError(
            "MIGRATION_SOURCE_INVALID", "v3 source layout is unavailable"
        ) from exc
    if (
        stat.S_ISLNK(source_meta.st_mode)
        or not stat.S_ISDIR(source_meta.st_mode)
        or stat.S_ISLNK(control_meta.st_mode)
        or not stat.S_ISDIR(control_meta.st_mode)
        or stat.S_ISLNK(before_path.st_mode)
        or not stat.S_ISREG(before_path.st_mode)
    ):
        raise V3CompatibilityError(
            "MIGRATION_SOURCE_INVALID", "v3 source contains an unsafe path"
        )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(state_path, flags)
        try:
            before_fd = os.fstat(descriptor)
            chunks: list[bytes] = []
            remaining = MAX_V3_STATE_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(65_536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            after_fd = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after_path = state_path.lstat()
    except OSError as exc:
        raise V3CompatibilityError(
            "MIGRATION_SOURCE_CHANGED", "v3 source changed during read"
        ) from exc
    identity_before = (
        before_path.st_dev,
        before_path.st_ino,
        before_path.st_size,
        before_path.st_mtime_ns,
    )
    identity_fd_before = (
        before_fd.st_dev,
        before_fd.st_ino,
        before_fd.st_size,
        before_fd.st_mtime_ns,
    )
    identity_fd_after = (
        after_fd.st_dev,
        after_fd.st_ino,
        after_fd.st_size,
        after_fd.st_mtime_ns,
    )
    identity_after = (
        after_path.st_dev,
        after_path.st_ino,
        after_path.st_size,
        after_path.st_mtime_ns,
    )
    if not (
        identity_before
        == identity_fd_before
        == identity_fd_after
        == identity_after
    ):
        raise V3CompatibilityError(
            "MIGRATION_SOURCE_CHANGED", "v3 source changed during read"
        )
    raw = b"".join(chunks)
    if len(raw) > MAX_V3_STATE_BYTES:
        raise V3CompatibilityError(
            "MIGRATION_SOURCE_INVALID", "v3 state exceeds the import byte bound"
        )
    return raw


def _source_projection_locked(source_root: Path) -> _SourceProjection:
    raw = _read_source_bytes(source_root)
    state = _decode_v3_state(raw)
    try:
        resolved_root = str(source_root.resolve(strict=True))
    except OSError as exc:
        raise V3CompatibilityError(
            "MIGRATION_SOURCE_INVALID", "v3 source root is unavailable"
        ) from exc
    if state.get("root") != resolved_root:
        raise V3CompatibilityError(
            "MIGRATION_SOURCE_INVALID", "v3 canonical root does not match source"
        )
    if state.get("terminal_status") is not None:
        raise V3CompatibilityError(
            "MIGRATION_TERMINAL_REVIVAL_FORBIDDEN",
            "terminal v3 loops remain readable but cannot be revived",
        )
    if state.get("schema_version") != 3 or state.get("state_gateway_mode") != "MCP_CANONICAL_WRITER":
        raise V3CompatibilityError(
            "MIGRATION_SOURCE_INVALID", "only public v3.3.8 schema-v3 sources are supported"
        )
    run_control = state.get("run_control")
    if not isinstance(run_control, dict) or run_control.get("status") != "PAUSED_AT_SAFE_POINT":
        raise V3CompatibilityError(
            "MIGRATION_NOT_QUIESCENT", "v3 loop is not paused at a safe point"
        )
    if state.get("controller_lease") is not None:
        raise V3CompatibilityError(
            "MIGRATION_NOT_QUIESCENT", "v3 loop has an active controller lease"
        )
    for field in _OUTBOX_FIELDS:
        value = state.get(field)
        if not isinstance(value, (dict, list)) or value:
            raise V3CompatibilityError(
                "MIGRATION_NOT_QUIESCENT", "v3 loop has non-quiescent outbox state"
            )
    if state.get("finalization_outbox") is not None:
        raise V3CompatibilityError(
            "MIGRATION_NOT_QUIESCENT", "v3 loop has pending finalization"
        )
    queue = state.get("goal_queue")
    registry = state.get("goal_definition_registry")
    ready = (
        [item for item in queue if isinstance(item, dict) and item.get("status") == "READY"]
        if isinstance(queue, list)
        else []
    )
    if len(ready) != 1 or not isinstance(registry, dict):
        raise V3CompatibilityError(
            "MIGRATION_SOURCE_INVALID", "v3 import requires one READY Goal"
        )
    source_goal_id = ready[0].get("goal_id")
    definition = registry.get(source_goal_id)
    objective = definition.get("objective") if isinstance(definition, dict) else None
    source_loop_id = state.get("loop_id")
    source_state_version = state.get("state_version")
    if (
        not isinstance(source_goal_id, str)
        or not source_goal_id
        or not isinstance(objective, str)
        or not objective.strip()
        or len(objective.strip().encode("utf-8")) > 4096
        or not isinstance(source_loop_id, str)
        or not source_loop_id
        or isinstance(source_state_version, bool)
        or not isinstance(source_state_version, int)
        or source_state_version < 1
    ):
        raise V3CompatibilityError(
            "MIGRATION_SOURCE_INVALID", "v3 Goal projection is invalid"
        )
    return _SourceProjection(
        source_loop_id=source_loop_id,
        source_schema_version=3,
        source_state_version=source_state_version,
        source_state_digest="sha256:" + hashlib.sha256(raw).hexdigest(),
        source_goal_id=source_goal_id,
        goal=objective.strip(),
    )


def _source_projection(source_root: Path) -> _SourceProjection:
    with _source_lock(source_root):
        return _source_projection_locked(source_root)


def _resolved(path: Path, *, strict: bool) -> Path:
    try:
        return path.resolve(strict=strict)
    except OSError as exc:
        raise V3CompatibilityError(
            "MIGRATION_SOURCE_INVALID", "migration root cannot be resolved"
        ) from exc


def _validate_separate_roots(source_root: Path, destination_root: Path) -> None:
    source = _resolved(source_root, strict=True)
    destination = _resolved(destination_root, strict=False)
    if source == destination or source in destination.parents or destination in source.parents:
        raise V3CompatibilityError(
            "DUAL_WRITE_FORBIDDEN", "v3 source and v4 destination must be disjoint"
        )


def _destination_entries(destination_root: Path) -> tuple[Path, ...]:
    if not destination_root.exists():
        return ()
    try:
        metadata = destination_root.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise OSError("unsafe destination")
        return tuple(destination_root.iterdir())
    except OSError as exc:
        raise V3CompatibilityError(
            "MIGRATION_DESTINATION_NOT_EMPTY", "v4 destination is unavailable"
        ) from exc


def preview_import(
    source_root: Path | str,
    destination_root: Path | str,
    *,
    clock: Callable[[], datetime] = _now,
) -> V3ImportPlan:
    source = Path(source_root)
    destination = Path(destination_root)
    _validate_separate_roots(source, destination)
    if _destination_entries(destination):
        raise V3CompatibilityError(
            "MIGRATION_DESTINATION_NOT_EMPTY", "v4 destination is not empty"
        )
    projection = _source_projection(source)
    preview_payload = {
        "destination_root_digest": domain_digest(
            "loopskill-v3-import-destination-v1\n",
            str(_resolved(destination, strict=False)),
        ),
        "goal": projection.goal,
        "source_loop_id": projection.source_loop_id,
        "source_schema_version": projection.source_schema_version,
        "source_state_digest": projection.source_state_digest,
        "source_state_version": projection.source_state_version,
    }
    preview = V3ImportPreview(
        source_loop_id=projection.source_loop_id,
        source_schema_version=projection.source_schema_version,
        source_state_version=projection.source_state_version,
        source_state_digest=projection.source_state_digest,
        goal=projection.goal,
        preview_digest=domain_digest(
            "loopskill-v3-import-preview-v1\n", preview_payload
        ),
    )
    return V3ImportPlan(
        preview=preview,
        source_goal_id=projection.source_goal_id,
        source_root=source,
        destination_root=destination,
        issued_at=_iso(clock()),
    )


def shadow_read(
    source_root: Path | str,
    destination_root: Path | str,
    *,
    clock: Callable[[], datetime] = _now,
) -> V3ImportPlan:
    """Read and validate a source without creating destination bytes."""

    return preview_import(source_root, destination_root, clock=clock)


def _with_digest(grant: AuthorityGrant) -> AuthorityGrant:
    values = dict(grant.__dict__)
    values["canonical_digest"] = authority_grant_digest(grant)
    return AuthorityGrant(**values)


def _import_command(
    plan: V3ImportPlan,
) -> tuple[str, AuthorityContext, CommandEnvelope]:
    namespace = plan.preview.preview_digest[:24]
    loop_ref = f"loop-import-{namespace}"
    goal_ref = "goal-import-" + domain_digest(
        "loopskill-v3-import-goal-ref-v1\n", plan.preview.preview_digest
    )[:24]
    actor_ref = f"actor-import-{namespace}"
    issuer_ref = f"actor-import-issuer-{namespace}"
    grant_ref = f"grant-import-{namespace}"
    operation_id = f"operation-import-{namespace}"
    actors = {
        actor_ref: ActorRef(
            actor_ref=actor_ref,
            loop_namespace=loop_ref,
            actor_kind="compat-importer",
            identity_digest=domain_digest(
                "loopskill-v3-import-actor-v1\n", {"actor_ref": actor_ref}
            ),
            issuer_ref=IMPORT_AUTHORITY_ISSUER,
            issuer_trust=IMPORT_AUTHORITY_TRUST,
        ),
        issuer_ref: ActorRef(
            actor_ref=issuer_ref,
            loop_namespace=loop_ref,
            actor_kind="system",
            identity_digest=domain_digest(
                "loopskill-v3-import-actor-v1\n", {"actor_ref": issuer_ref}
            ),
            issuer_ref=IMPORT_AUTHORITY_ISSUER,
            issuer_trust=IMPORT_AUTHORITY_TRUST,
        ),
    }
    issued = datetime.fromisoformat(plan.issued_at.replace("Z", "+00:00"))
    grant = _with_digest(
        AuthorityGrant(
            grant_ref=grant_ref,
            actor_ref=actor_ref,
            issuer_actor_ref=issuer_ref,
            issuer_trust=IMPORT_AUTHORITY_TRUST,
            allowed_commands=("ImportV3Snapshot",),
            loop_scope=loop_ref,
            subject_kinds=("LoopRef",),
            exact_subjects=(loop_ref,),
            not_before=plan.issued_at,
            expires_at=_iso(issued + timedelta(minutes=30)),
            nonce=f"nonce-import-{namespace}",
            canonical_digest="",
        )
    )
    authority = AuthorityContext(
        actors=actors,
        grants={grant_ref: grant},
        receipts={},
        trusted_actor_issuers={IMPORT_AUTHORITY_ISSUER: IMPORT_AUTHORITY_TRUST},
        trusted_grant_issuers={issuer_ref: IMPORT_AUTHORITY_TRUST},
        trusted_receipt_issuers={},
    )
    command = build_command(
        operation_id=operation_id,
        command_type="ImportV3Snapshot",
        actor_ref=actor_ref,
        authority_grant_ref=grant_ref,
        subject={
            "loop_ref": loop_ref,
            "subject_kind": "LoopRef",
            "subject_ref": loop_ref,
        },
        expected_loop_revision=0,
        expected_subject_revisions={},
        issued_at=plan.issued_at,
        machine_bindings={
            "allocate_refs": {"new_goal_ref": goal_ref},
            "receipt_refs": {},
            "resolved_refs": {},
        },
        semantic_payload={
            "objective": plan.preview.goal,
            "source_goal_id": plan.source_goal_id,
            "source_loop_id": plan.preview.source_loop_id,
            "source_product_version": PUBLIC_V3_PRODUCT_VERSION,
            "source_schema_version": plan.preview.source_schema_version,
            "source_state_digest": plan.preview.source_state_digest,
            "source_state_version": plan.preview.source_state_version,
        },
    )
    return loop_ref, authority, command


def _same_projection_locked(plan: V3ImportPlan) -> _SourceProjection:
    current = _source_projection_locked(plan.source_root)
    preview_payload = {
        "destination_root_digest": domain_digest(
            "loopskill-v3-import-destination-v1\n",
            str(_resolved(plan.destination_root, strict=False)),
        ),
        "goal": current.goal,
        "source_loop_id": current.source_loop_id,
        "source_schema_version": current.source_schema_version,
        "source_state_digest": current.source_state_digest,
        "source_state_version": current.source_state_version,
    }
    current_preview_digest = domain_digest(
        "loopskill-v3-import-preview-v1\n", preview_payload
    )
    if (
        current.source_loop_id != plan.preview.source_loop_id
        or current.source_schema_version != plan.preview.source_schema_version
        or current.source_state_version != plan.preview.source_state_version
        or current.source_state_digest != plan.preview.source_state_digest
        or current.source_goal_id != plan.source_goal_id
        or current.goal != plan.preview.goal
        or current_preview_digest != plan.preview.preview_digest
    ):
        raise V3CompatibilityError(
            "MIGRATION_SOURCE_CHANGED", "v3 source changed after preview"
        )
    return current


def cancel_import(plan: V3ImportPlan) -> V3ImportPreview:
    _validate_separate_roots(plan.source_root, plan.destination_root)
    with _source_lock(plan.source_root):
        _same_projection_locked(plan)
    if _destination_entries(plan.destination_root):
        raise V3CompatibilityError(
            "MIGRATION_DESTINATION_NOT_EMPTY", "cancel target is not empty"
        )
    return plan.preview


def _existing_import(plan: V3ImportPlan, path: Path) -> V3ImportResult | None:
    entries = _destination_entries(plan.destination_root)
    if not entries:
        return None
    if {item.name for item in entries} != {STORE_FILENAME} or path.is_symlink():
        raise V3CompatibilityError(
            "MIGRATION_DESTINATION_NOT_EMPTY", "v4 destination is not empty"
        )
    try:
        with SQLiteStore(path) as store:
            descriptors = store.loop_descriptors()
            if not descriptors:
                if store.commit_count or store.rejection_count:
                    raise V3CompatibilityError(
                        "MIGRATION_DESTINATION_NOT_EMPTY",
                        "v4 destination contains non-import operations",
                    )
                return None
            if len(descriptors) != 1:
                raise V3CompatibilityError(
                    "MIGRATION_DESTINATION_NOT_EMPTY",
                    "v4 destination does not contain one imported loop",
                )
            loop_ref = descriptors[0]["loop_ref"]
            snapshot = store.snapshot(loop_ref)
            if (
                snapshot is None
                or snapshot.get("import_provenance", {}).get("source_state_digest")
                != plan.preview.source_state_digest
            ):
                raise V3CompatibilityError(
                    "MIGRATION_DESTINATION_NOT_EMPTY",
                    "v4 destination belongs to another source",
                )
            return V3ImportResult(
                loop_ref=loop_ref,
                source_state_digest=plan.preview.source_state_digest,
                snapshot_digest=snapshot_digest(snapshot),
                replayed=True,
            )
    except V3CompatibilityError:
        raise
    except (OSError, PersistenceError, ProtocolRejection) as exc:
        raise V3CompatibilityError(
            "MIGRATION_DESTINATION_NOT_EMPTY", "v4 destination is unreadable"
        ) from exc


def confirm_import(plan: V3ImportPlan) -> V3ImportResult:
    """Commit one confirmed preview; exact replay returns the original result."""

    _validate_separate_roots(plan.source_root, plan.destination_root)
    with _source_lock(plan.source_root):
        _same_projection_locked(plan)
        path = plan.destination_root / STORE_FILENAME
        existing = _existing_import(plan, path)
        if existing is not None:
            return existing
        try:
            plan.destination_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            metadata = plan.destination_root.lstat()
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or metadata.st_mode & 0o077
            ):
                raise V3CompatibilityError(
                    "MIGRATION_DESTINATION_NOT_EMPTY",
                    "v4 destination is not owner-only",
                )
            loop_ref, authority, command = _import_command(plan)
            with SQLiteStore(path, authority) as store:
                result = store.apply(command)
                store.verify_integrity()
                snapshot = store.snapshot(loop_ref)
                if snapshot is None:
                    raise V3CompatibilityError(
                        "MIGRATION_SOURCE_INVALID", "imported snapshot is absent"
                    )
                if store.ready_effect_attempts():
                    raise V3CompatibilityError(
                        "MIGRATION_SOURCE_INVALID",
                        "import created an external effect",
                    )
                _same_projection_locked(plan)
                return V3ImportResult(
                    loop_ref=loop_ref,
                    source_state_digest=plan.preview.source_state_digest,
                    snapshot_digest=result.snapshot_digest,
                    replayed=result.replayed,
                )
        except V3CompatibilityError:
            raise
        except (OSError, PersistenceError, ProtocolRejection) as exc:
            raise V3CompatibilityError(
                "MIGRATION_SOURCE_INVALID", "v3 import could not commit safely"
            ) from exc
