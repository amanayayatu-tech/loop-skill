"""One-shot, privacy-minimized LoopSkill 4 foreground exec canary service.

The service deliberately uses the public INTAKE -> PREPARE -> CONFIRM -> START
path.  It never retries START, never serializes a Host identity, and emits a
receipt only after the canonical store proves strict, successful closure.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from loop_architect.v4_adapters.codex.exec_provider import CodexExecProvider
from loop_architect.v4_adapters.codex.adapter import HostUnavailable
from loop_architect.v4_alpha.protocol import (
    LoopIntakeInput,
    canonical_bytes,
    snapshot_digest,
)
from loop_architect.v4_persistence.sqlite_store import SQLiteStore

from .service import (
    STORE_FILENAME,
    confirm_loop,
    intake_report_loop,
    prepare_loop,
    start_loop,
    sync_loop,
)


CANARY_ARTIFACT = "loopskill-v4-disposable-codex-exec-canary-v1"
CANARY_ISSUER = "codex-exec-jsonl-v1"
CANARY_TRUST = "same-process-terminal-observed"
CANARY_PROVENANCE_DOMAIN = b"loopskill.v4.exec-canary.provenance.v1\0"
CANARY_LIVE_DOMAIN = b"loopskill.v4.exec-canary.live-observation.v1\0"
CANARY_HOST_ID_DOMAIN = b"loopskill.v4.exec-canary.host-identity.v1\0"
CANARY_INTEGRITY_DOMAIN = b"loopskill.v4.exec-canary.integrity.v1\0"

CANARY_RECEIPT_FILENAME = "canary-receipt.json"
CANARY_INTEGRITY_BEFORE_FILENAME = "canary-integrity-before.json"
CANARY_INTEGRITY_FILENAME = "canary-integrity.json"
CANARY_OUTPUT_FILENAME = "canary-output.txt"
CANARY_OUTPUT_BYTES = b"LOOPSKILL4_CANARY_OK\n"
CANARY_OUTPUT_SHA256 = "8d23b5e88d9fb86f366700a6267f29b46bcca5cd45a59ed27afbbd04860eb638"

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_INTEGRITY_LABELS = frozenset({"host_auth", "host_config"})
_MAX_INTEGRITY_INPUT_BYTES = 2 * 1024 * 1024
_SAFE_PROVIDER_METRICS = frozenset(
    {
        "delivery_readback_count",
        "duplicate_invoke_rejection_count",
        "lifecycle_read_count",
        "provider_resend_count",
        "task_create_count",
        "task_result_read_count",
        "terminal_wait_read_count",
    }
)


class CanaryError(RuntimeError):
    """Stable local failure without embedding paths or Host identities."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _token() -> str:
    return os.urandom(12).hex()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _domain_digest(domain: bytes, value: Any) -> str:
    return hashlib.sha256(domain + canonical_bytes(value)).hexdigest()


def _integrity_snapshot(inputs: Mapping[str, Path | str]) -> dict[str, Any]:
    """Measure exact scoped inputs without persisting their paths or contents."""

    if set(inputs) != _INTEGRITY_LABELS:
        raise CanaryError("CANARY_INTEGRITY_INPUTS_MISSING")
    result: dict[str, Any] = {}
    for label in sorted(_INTEGRITY_LABELS):
        path = Path(inputs[label])
        try:
            if not path.is_absolute():
                raise OSError("integrity path is not absolute")
            if path.is_symlink():
                raise OSError("unsafe integrity input")
            if not path.exists():
                state = {"presence": "ABSENT", "size": 0}
                raw = None
            else:
                metadata = path.lstat()
                if (
                    stat.S_ISLNK(metadata.st_mode)
                    or not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_uid != os.getuid()
                    or metadata.st_size > _MAX_INTEGRITY_INPUT_BYTES
                ):
                    raise OSError("unsafe integrity input")
                descriptor = os.open(
                    path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                )
                try:
                    opened = os.fstat(descriptor)
                    chunks = []
                    remaining = _MAX_INTEGRITY_INPUT_BYTES + 1
                    while remaining:
                        chunk = os.read(descriptor, min(65_536, remaining))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        remaining -= len(chunk)
                    raw = b"".join(chunks)
                    if (
                        len(raw) > _MAX_INTEGRITY_INPUT_BYTES
                        or not stat.S_ISREG(opened.st_mode)
                        or (opened.st_dev, opened.st_ino)
                        != (metadata.st_dev, metadata.st_ino)
                        or opened.st_size != len(raw)
                    ):
                        raise OSError("integrity input changed during read")
                finally:
                    os.close(descriptor)
                state = {
                    "content_sha256": hashlib.sha256(raw).hexdigest(),
                    "presence": "FILE",
                    "size": len(raw),
                }
        except OSError as exc:
            raise CanaryError("CANARY_INTEGRITY_INPUT_INVALID") from exc
        result[label] = {
            "digest": _domain_digest(
                CANARY_INTEGRITY_DOMAIN,
                {"label": label, "state": state},
            ),
            "raw": raw,
            "state": state,
        }
    return result


def _integrity_public(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        label: {
            "digest": snapshot[label]["digest"],
            "presence": snapshot[label]["state"]["presence"],
            "size": snapshot[label]["state"]["size"],
        }
        for label in sorted(_INTEGRITY_LABELS)
    }


def _changed_bytes(before: bytes | None, after: bytes | None) -> int:
    left = b"" if before is None else before
    right = b"" if after is None else after
    return sum(a != b for a, b in zip(left, right)) + abs(len(left) - len(right))


def _integrity_comparison(
    candidate_sha: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    observed_at: datetime,
) -> dict[str, Any]:
    changed = {
        label: _changed_bytes(before[label]["raw"], after[label]["raw"])
        for label in sorted(_INTEGRITY_LABELS)
    }
    return {
        "after": _integrity_public(after),
        "artifact": "loopskill-v4-canary-integrity-measurement-v1",
        "before": _integrity_public(before),
        "candidate_sha": candidate_sha,
        "changed_bytes": changed,
        "changed_input_count": sum(value > 0 for value in changed.values()),
        "observed_at": _iso(observed_at),
        "total_changed_bytes": sum(changed.values()),
    }


def _validate_candidate(candidate_sha: str) -> str:
    if not isinstance(candidate_sha, str) or _SHA_RE.fullmatch(candidate_sha) is None:
        raise CanaryError("CANARY_CANDIDATE_SHA_INVALID")
    return candidate_sha


def _ensure_empty_private_root(path: Path | str) -> Path:
    root = Path(path)
    if root.exists():
        try:
            metadata = root.lstat()
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or metadata.st_mode & 0o077
                or any(root.iterdir())
            ):
                raise OSError("unsafe evidence root")
        except OSError as exc:
            raise CanaryError("CANARY_EVIDENCE_ROOT_INVALID") from exc
    else:
        try:
            root.mkdir(mode=0o700)
        except OSError as exc:
            raise CanaryError("CANARY_EVIDENCE_ROOT_INVALID") from exc
        metadata = root.stat()
        if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            raise CanaryError("CANARY_EVIDENCE_ROOT_INVALID")
    return root


def _request(candidate_sha: str) -> LoopIntakeInput:
    quoted = CANARY_OUTPUT_BYTES.decode("utf-8").rstrip("\n")
    goal = (
        f"Verify LoopSkill 4 candidate {candidate_sha} in this disposable workspace: "
        f"create exactly {CANARY_OUTPUT_FILENAME} with UTF-8 content {quoted!r} "
        "followed by exactly one LF byte, then "
        "return the required LoopSkill 4 PASS result envelope."
    )
    return LoopIntakeInput(
        goal=goal,
        goal_plan=(goal,),
        task_horizon="long",
        write_scope=(CANARY_OUTPUT_FILENAME,),
        budget="One foreground Codex invocation; one automatic attempt; no resend.",
        external_actions=(
            "Run one disposable foreground Codex invocation after explicit confirmation.",
        ),
        acceptance_criteria=(
            "artifact-changed",
            f"file-exists:{CANARY_OUTPUT_FILENAME}",
            f"file-sha256:{CANARY_OUTPUT_FILENAME}={CANARY_OUTPUT_SHA256}",
        ),
        stop_conditions=(
            "Stop after one START and one synchronization.",
            "Preserve UNKNOWN or UNVERIFIABLE without resend.",
        ),
        authorization_boundaries=(
            f"Write only {CANARY_OUTPUT_FILENAME} in the disposable workspace.",
            "No commit, push, publish, deploy, installation, migration, or v3 access.",
            "No private data or research scoring.",
        ),
    )


def _default_wait(provider: Any, workspace: Path, *, timeout_seconds: float = 300.0) -> None:
    """Wait read-only for the unique invocation; never use file timing as closure."""

    del workspace
    waiter = getattr(provider, "wait_for_terminal", None)
    if not callable(waiter):
        raise CanaryError("CANARY_TERMINAL_WAIT_UNAVAILABLE")
    try:
        waiter(timeout_seconds=timeout_seconds)
    except (HostUnavailable, ValueError) as exc:
        raise CanaryError("CANARY_TERMINAL_WAIT_FAILED") from exc


def _verify_workspace(workspace: Path) -> None:
    try:
        entries = list(workspace.iterdir())
        if len(entries) != 1 or entries[0].name != CANARY_OUTPUT_FILENAME:
            raise OSError("unexpected workspace surface")
        output = entries[0]
        metadata = output.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise OSError("unsafe output")
        descriptor = os.open(output, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(descriptor)
            raw = os.read(descriptor, len(CANARY_OUTPUT_BYTES) + 1)
            if (
                not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
            ):
                raise OSError("output changed during read")
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise CanaryError("CANARY_OUTPUT_INVALID") from exc
    if raw != CANARY_OUTPUT_BYTES or hashlib.sha256(raw).hexdigest() != CANARY_OUTPUT_SHA256:
        raise CanaryError("CANARY_OUTPUT_INVALID")


def _provider_metrics(provider: Any) -> dict[str, int]:
    raw = getattr(provider, "metrics", None)
    if callable(raw):
        raw = raw()
    if not isinstance(raw, Mapping) or not _SAFE_PROVIDER_METRICS <= set(raw):
        raise CanaryError("CANARY_PROVIDER_METRICS_UNAVAILABLE")
    metrics: dict[str, int] = {}
    for name in _SAFE_PROVIDER_METRICS:
        value = raw[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CanaryError("CANARY_PROVIDER_METRICS_INVALID")
        metrics[name] = value
    if (
        metrics["delivery_readback_count"] not in {1, 2, 3}
        or metrics["duplicate_invoke_rejection_count"] != 0
        or metrics["lifecycle_read_count"] != 1
        or metrics["provider_resend_count"] != 0
        or metrics["task_create_count"] != 1
        or metrics["task_result_read_count"] != 1
        or metrics["terminal_wait_read_count"] < 1
        or metrics["terminal_wait_read_count"] > 1_200
    ):
        raise CanaryError("CANARY_PROVIDER_METRICS_INVALID")
    return metrics


def _single(values: Mapping[str, Any], code: str) -> Mapping[str, Any]:
    if len(values) != 1:
        raise CanaryError(code)
    value = next(iter(values.values()))
    if not isinstance(value, Mapping):
        raise CanaryError(code)
    return value


def _live_summary(
    candidate_sha: str,
    store_root: Path,
    workspace: Path,
) -> tuple[dict[str, Any], str]:
    _verify_workspace(workspace)
    path = store_root / STORE_FILENAME
    with SQLiteStore(path) as store:
        store.verify_integrity()
        descriptors = store.loop_descriptors()
        if len(descriptors) != 1 or candidate_sha not in descriptors[0]["goal"]:
            raise CanaryError("CANARY_CANDIDATE_BINDING_INVALID")
        snapshot = store.snapshot(descriptors[0]["loop_ref"])
        if snapshot is None:
            raise CanaryError("CANARY_CLOSURE_INVALID")
        effect = _single(snapshot.get("external_effects", {}), "CANARY_CLOSURE_INVALID")
        result = _single(snapshot.get("results", {}), "CANARY_CLOSURE_INVALID")
        report = _single(snapshot.get("reports", {}), "CANARY_CLOSURE_INVALID")
        artifact = _single(snapshot.get("artifacts", {}), "CANARY_CLOSURE_INVALID")
        review = _single(snapshot.get("reviews", {}), "CANARY_CLOSURE_INVALID")
        finalization = _single(
            snapshot.get("finalizations", {}), "CANARY_CLOSURE_INVALID"
        )
        host_resource = snapshot.get("host_resources", {}).get(
            effect.get("host_resource_ref")
        )
        provider_id = (
            None
            if not isinstance(host_resource, Mapping)
            else host_resource.get("provider_resource_ref")
        )
        if not isinstance(provider_id, str) or not provider_id:
            raise CanaryError("CANARY_HOST_IDENTITY_INVALID")
        if (
            result.get("state") != "ACKNOWLEDGED"
            or result.get("outcome") != "PASS"
            or not isinstance(result.get("source_observation_digest"), str)
            or report.get("state") != "ACCEPTED"
            or artifact.get("state") != "VERIFIED"
            or review.get("state") != "PASS"
            or finalization.get("state") != "EXECUTION_CLOSED"
            or snapshot.get("execution", {}).get("state") != "TERMINAL"
            or snapshot.get("execution", {}).get("disposition") != "SUCCEEDED"
            or snapshot.get("closure_assurance", {}).get("strength") != "STRICT"
        ):
            raise CanaryError("CANARY_CLOSURE_INVALID")
        live = {
            "artifact_state": artifact["state"],
            "assurance": snapshot["closure_assurance"]["strength"],
            "canary_output_sha256": CANARY_OUTPUT_SHA256,
            "candidate_goal_digest": descriptors[0]["goal_digest"],
            "candidate_sha": candidate_sha,
            "execution_disposition": snapshot["execution"]["disposition"],
            "execution_state": snapshot["execution"]["state"],
            "finalization_state": finalization["state"],
            "host_task_identity_digest": _domain_digest(
                CANARY_HOST_ID_DOMAIN, provider_id
            ),
            "lifecycle_state": "TERMINAL",
            "result_digest": result["source_observation_digest"],
            "result_outcome": result["outcome"],
            "result_state": result["state"],
            "report_state": report["state"],
            "review_state": review["state"],
            "snapshot_digest": snapshot_digest(snapshot),
        }
        return live, descriptors[0]["goal_digest"]


def _receipt(
    candidate_sha: str,
    live: Mapping[str, Any],
    metrics: Mapping[str, int],
    integrity: Mapping[str, Any],
    issued_at: datetime,
    observed_at: datetime,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "artifact": CANARY_ARTIFACT,
        "candidate_sha": candidate_sha,
        "candidate_goal_digest": live["candidate_goal_digest"],
        "canary_output_sha256": live["canary_output_sha256"],
        "confirmation_count": 1,
        "confirmation_digest_bound": True,
        "config_bytes_changed": integrity["changed_bytes"]["host_config"],
        "entry": "loopskill4",
        "finalization": "ACKNOWLEDGED",
        "fresh_until": _iso(issued_at + timedelta(minutes=10)),
        "host_auth_after_digest": integrity["after"]["host_auth"]["digest"],
        "host_auth_before_digest": integrity["before"]["host_auth"]["digest"],
        "host_config_after_digest": integrity["after"]["host_config"]["digest"],
        "host_config_before_digest": integrity["before"]["host_config"]["digest"],
        "host_integrity_changed_input_count": integrity["changed_input_count"],
        "host_receipt_issuer": CANARY_ISSUER,
        "host_receipt_trust": CANARY_TRUST,
        "host_create_readback_count": metrics["delivery_readback_count"],
        "host_lifecycle_readback_count": metrics["lifecycle_read_count"],
        "host_result_digest": live["result_digest"],
        "host_task_create_count": metrics["task_create_count"],
        "host_task_identity_digest": live["host_task_identity_digest"],
        "host_task_readback_count": metrics["task_result_read_count"],
        "host_terminal_wait_readback_count": metrics["terminal_wait_read_count"],
        "host_total_read_count": (
            metrics["delivery_readback_count"]
            + metrics["terminal_wait_read_count"]
            + metrics["task_result_read_count"]
            + metrics["lifecycle_read_count"]
        ),
        "intake_external_effects": 0,
        "intake_heartbeat_count": 0,
        "intake_host_task_count": 0,
        "intake_loop_count": 0,
        "issued_at": _iso(issued_at),
        "loopskill_mcp_registration_count": 0,
        "machine_owned_identity": True,
        "manual_control_identity_count": 0,
        "observed_at": _iso(observed_at),
        "app_restart_count": 0,
        "prepare_delivery_count": 0,
        "prepare_heartbeat_count": 0,
        "prepare_host_effects": 0,
        "prepare_host_task_count": 0,
        "private_data_used": False,
        "provider_resend_count": metrics["provider_resend_count"],
        "research_scored": False,
        "result": "ACKNOWLEDGED",
        "review": "PASS",
        "status": "PASS",
        "thread_content_retained": False,
        "unknown_preserved": True,
        "v3_bytes_changed": 0,
    }
    body["provenance_digest"] = _domain_digest(CANARY_PROVENANCE_DOMAIN, body)
    body["host_receipt_digest"] = _domain_digest(CANARY_LIVE_DOMAIN, live)
    return body


def _write_receipt(root: Path, receipt: Mapping[str, Any]) -> None:
    _write_canonical_once(root, CANARY_RECEIPT_FILENAME, receipt)


def _write_canonical_once(
    root: Path, filename: str, value: Mapping[str, Any]
) -> None:
    destination = root / filename
    temporary = root / f".{filename}.tmp"
    raw = canonical_bytes(value)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(temporary, flags, 0o600)
        try:
            view = memoryview(raw)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short receipt write")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if destination.exists():
            raise OSError("receipt already exists")
        os.replace(temporary, destination)
        directory = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        raise CanaryError("CANARY_EVIDENCE_WRITE_FAILED") from exc


def run_canary(
    candidate_sha: str,
    evidence_root: Path | str,
    *,
    confirmation_callback: Callable[[Mapping[str, Any]], bool],
    integrity_inputs: Mapping[str, Path | str] | None = None,
    provider_factory: Callable[[Path], Any] | None = None,
    wait_callback: Callable[[Any, Path], None] | None = None,
    clock: Callable[[], datetime] = _now,
    token_factory: Callable[[], str] = _token,
) -> Mapping[str, Any]:
    """Run one exact candidate canary and return its closed receipt.

    Any decline, UNKNOWN, UNVERIFIABLE, failed task, invalid output, or missing
    safe provider metrics raises without deleting the evidence root and without
    producing ``canary-receipt.json``.
    """
    candidate = _validate_candidate(candidate_sha)
    root = _ensure_empty_private_root(evidence_root)
    workspace = root / "workspace"
    workspace.mkdir(mode=0o700)
    prepared_root = root / "prepared"
    store_root = root / "store"

    request = _request(candidate)
    intake_report = intake_report_loop(request)
    if intake_report["1 最终判定"]["disposition"] != "READY_FOR_LOOP":
        raise CanaryError("CANARY_INTAKE_NOT_READY")
    prepared = prepare_loop(
        request,
        prepared_root,
        clock=clock,
        token_factory=token_factory,
        workspace_root=workspace,
    )
    if confirmation_callback(dict(prepared.boundary)) is not True:
        raise CanaryError("CANARY_CONFIRMATION_DECLINED")
    confirmed = confirm_loop(prepared.directory, confirmed=True, clock=clock)

    if integrity_inputs is None:
        raise CanaryError("CANARY_INTEGRITY_INPUTS_MISSING")
    issued_at = clock()
    before_integrity = _integrity_snapshot(integrity_inputs)
    _write_canonical_once(
        root,
        CANARY_INTEGRITY_BEFORE_FILENAME,
        {
            "artifact": "loopskill-v4-canary-integrity-before-v1",
            "candidate_sha": candidate,
            "inputs": _integrity_public(before_integrity),
            "issued_at": _iso(issued_at),
        },
    )

    provider = None
    after_integrity = None
    integrity_observed_at = None
    try:
        if provider_factory is None:
            provider = CodexExecProvider(
                workspace,
                issuer_ref=CANARY_ISSUER,
                issuer_trust=CANARY_TRUST,
                clock=clock,
            )
        else:
            provider = provider_factory(workspace)

        preflight = getattr(provider, "preflight", None)
        if not callable(preflight):
            raise CanaryError("CANARY_HOST_PROTOCOL_PREFLIGHT_UNAVAILABLE")
        try:
            preflight()
        except HostUnavailable as exc:
            raise CanaryError("CANARY_HOST_PROTOCOL_INCOMPATIBLE") from exc

        # Exactly one public START.  No exception path re-enters this call.
        start_loop(
            confirmed,
            root=store_root,
            clock=clock,
            host_provider=provider,
            host_issuer_ref=CANARY_ISSUER,
            host_issuer_trust=CANARY_TRUST,
            workspace_root=workspace,
        )
        (wait_callback or _default_wait)(provider, workspace)
        # Exactly one synchronization.  UNKNOWN/UNVERIFIABLE remains canonical.
        final_view = sync_loop(
            root=store_root,
            host_provider=provider,
            host_issuer_ref=CANARY_ISSUER,
            host_issuer_trust=CANARY_TRUST,
            clock=clock,
            workspace_root=workspace,
        )
    finally:
        close = None if provider is None else getattr(provider, "close", None)
        if callable(close):
            close()
        after_integrity = _integrity_snapshot(integrity_inputs)
        integrity_observed_at = clock()
        comparison = _integrity_comparison(
            candidate, before_integrity, after_integrity, integrity_observed_at
        )
        _write_canonical_once(root, CANARY_INTEGRITY_FILENAME, comparison)
    if comparison["changed_input_count"] != 0:
        raise CanaryError("CANARY_HOST_INTEGRITY_CHANGED")
    if final_view.progress != "Finished" or final_view.result != "SUCCEEDED":
        raise CanaryError("CANARY_OUTCOME_NOT_PASS")

    _verify_workspace(workspace)
    assert provider is not None
    assert integrity_observed_at is not None
    metrics = _provider_metrics(provider)
    live, _ = _live_summary(candidate, store_root, workspace)
    receipt = _receipt(
        candidate,
        live,
        metrics,
        comparison,
        issued_at,
        integrity_observed_at,
    )
    _write_receipt(root, receipt)
    return receipt
