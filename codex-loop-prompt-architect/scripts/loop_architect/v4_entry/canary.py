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
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from loop_architect.v4_adapters.codex.exec_provider import CodexExecProvider
from loop_architect.v4_adapters.codex.adapter import HostUnavailable
from loop_architect.v4_alpha.protocol import (
    LoopIntakeInput,
    ProtocolRejection,
    canonical_bytes,
    snapshot_digest,
    validate_result_payload,
)
from loop_architect.v4_alpha.plan_codec import canonicalize_plan
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
CANARY_INTEGRITY_MEASUREMENT_DOMAIN = (
    b"loopskill.v4.exec-canary.integrity-measurement.v1\0"
)
CANARY_CONFIG_PREFIX_DOMAIN = b"loopskill.v4.exec-canary.config-prefix.v1\0"
CANARY_CONFIG_DELTA_DOMAIN = b"loopskill.v4.exec-canary.config-delta.v1\0"
CANARY_WORKSPACE_DOMAIN = b"loopskill.v4.exec-canary.workspace.v1\0"
CANARY_PROVIDER_DIAGNOSTIC_DOMAIN = (
    b"loopskill.v4.exec-canary.provider-diagnostic.v1\0"
)
CANARY_CANDIDATE_PROVENANCE_DOMAIN = (
    b"loopskill.v4.exec-canary.candidate-provenance.v1\0"
)

HOST_CONFIG_DELTA_NONE = "NONE"
HOST_CONFIG_DELTA_TRUST_APPEND = "CODEX_WORKSPACE_TRUST_APPEND_V1"
HOST_CONFIG_DELTA_UNEXPECTED = "UNEXPECTED"

CANARY_RECEIPT_FILENAME = "canary-receipt.json"
CANARY_INTEGRITY_BEFORE_FILENAME = "canary-integrity-before.json"
CANARY_INTEGRITY_FILENAME = "canary-integrity.json"
CANARY_PROVIDER_DIAGNOSTIC_FILENAME = "canary-provider-diagnostic.json"
CANARY_OUTPUT_FILENAME = "canary-output.txt"
CANARY_OUTPUT_BYTES = b"LOOPSKILL4_CANARY_OK\n"
CANARY_OUTPUT_SHA256 = "8d23b5e88d9fb86f366700a6267f29b46bcca5cd45a59ed27afbbd04860eb638"
CANARY_GOAL = (
    f"In this workspace, create exactly one regular file named {CANARY_OUTPUT_FILENAME} "
    "with UTF-8 content 'LOOPSKILL4_CANARY_OK' followed by exactly one LF byte. "
    "Then check locally that the workspace contains no other entries, that the file "
    f"exists, and that its SHA-256 is {CANARY_OUTPUT_SHA256}. Return PASS only when "
    "all of those local checks succeed; return FAILED when a completed check does not "
    "match; use LIMITATION or UNVERIFIABLE only when one of those local checks cannot "
    "actually be performed."
)

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


def _bytes_digest(domain: bytes, value: bytes) -> str:
    return hashlib.sha256(domain + value).hexdigest()


def _canonical_workspace(workspace: Path | str) -> Path:
    path = Path(workspace)
    try:
        canonical = path.resolve(strict=True)
        metadata = canonical.stat()
    except OSError as exc:
        raise CanaryError("CANARY_WORKSPACE_IDENTITY_INVALID") from exc
    text = str(canonical)
    if (
        not path.is_absolute()
        or path != canonical
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or '"' in text
        or "\\" in text
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in text)
    ):
        raise CanaryError("CANARY_WORKSPACE_IDENTITY_INVALID")
    return canonical


def _workspace_identity_digest(workspace: Path | str) -> str:
    return _domain_digest(CANARY_WORKSPACE_DOMAIN, str(_canonical_workspace(workspace)))


def _canonical_workspace_trust_stanza(workspace: Path | str) -> bytes:
    canonical = _canonical_workspace(workspace)
    return (
        f'\n[projects."{canonical}"]\ntrust_level = "trusted"\n'.encode("utf-8")
    )


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
    workspace: Path | str,
) -> dict[str, Any]:
    changed = {
        label: _changed_bytes(before[label]["raw"], after[label]["raw"])
        for label in sorted(_INTEGRITY_LABELS)
    }
    before_auth = before["host_auth"]["raw"]
    after_auth = after["host_auth"]["raw"]
    before_config = before["host_config"]["raw"]
    after_config = after["host_config"]["raw"]
    stanza = _canonical_workspace_trust_stanza(workspace)
    header = stanza.split(b"\n", 2)[1] + b"\n"
    workspace_digest = _workspace_identity_digest(workspace)
    before_key_count = 0 if before_config is None else before_config.count(header)
    after_key_count = 0 if after_config is None else after_config.count(header)
    config_unchanged = before_config == after_config
    exact_trust_append = (
        before_config is not None
        and after_config is not None
        and before_key_count == 0
        and after_key_count == 1
        and after_config == before_config + stanza
    )
    if config_unchanged and before_key_count == 0:
        kind = HOST_CONFIG_DELTA_NONE
        allowed_delta_count = 0
        config_unexpected = 0
        after_prefix = after_config or b""
        observed_delta = b""
    elif exact_trust_append:
        kind = HOST_CONFIG_DELTA_TRUST_APPEND
        allowed_delta_count = 1
        config_unexpected = 0
        after_prefix = after_config[: len(before_config)]
        observed_delta = after_config[len(before_config) :]
    else:
        kind = HOST_CONFIG_DELTA_UNEXPECTED
        allowed_delta_count = 0
        config_unexpected = 1
        before_length = 0 if before_config is None else len(before_config)
        after_bytes = b"" if after_config is None else after_config
        after_prefix = after_bytes[:before_length]
        observed_delta = after_bytes[before_length:]
    auth_unexpected = int(before_auth != after_auth)
    classification = {
        "after_prefix_digest": _bytes_digest(
            CANARY_CONFIG_PREFIX_DOMAIN, after_prefix
        ),
        "after_workspace_key_count": after_key_count,
        "allowed_host_managed_delta_count": allowed_delta_count,
        "before_prefix_digest": _bytes_digest(
            CANARY_CONFIG_PREFIX_DOMAIN, before_config or b""
        ),
        "before_workspace_key_count": before_key_count,
        "delta_kind": kind,
        "observed_delta_bytes": len(observed_delta),
        "observed_delta_digest": _bytes_digest(
            CANARY_CONFIG_DELTA_DOMAIN, observed_delta
        ),
        "unexpected_changed_input_count": config_unexpected + auth_unexpected,
        "workspace_identity_digest": workspace_digest,
    }
    body = {
        "after": _integrity_public(after),
        "artifact": "loopskill-v4-canary-integrity-measurement-v1",
        "before": _integrity_public(before),
        "candidate_sha": candidate_sha,
        "changed_bytes": changed,
        "changed_input_count": sum(value > 0 for value in changed.values()),
        "host_config_delta": classification,
        "observed_at": _iso(observed_at),
        "total_changed_bytes": sum(changed.values()),
    }
    body["measurement_digest"] = _domain_digest(
        CANARY_INTEGRITY_MEASUREMENT_DOMAIN, body
    )
    return body


def _validate_candidate(candidate_sha: str) -> str:
    if not isinstance(candidate_sha, str) or _SHA_RE.fullmatch(candidate_sha) is None:
        raise CanaryError("CANARY_CANDIDATE_SHA_INVALID")
    return candidate_sha


def _candidate_provenance(
    candidate_sha: str,
    candidate_root: Path | str | None,
    *,
    runtime_source: Path | str | None = None,
) -> dict[str, str]:
    if candidate_root is None:
        raise CanaryError("CANARY_CANDIDATE_ROOT_INVALID")
    supplied_root = Path(candidate_root)
    try:
        root = supplied_root.resolve(strict=True)
        metadata = root.stat()
        if (
            not supplied_root.is_absolute()
            or supplied_root != root
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
        ):
            raise OSError("unsafe candidate root")
        top = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        ).stdout.strip()
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        ).stdout.strip()
        tree = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD^{tree}"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise CanaryError("CANARY_CANDIDATE_ROOT_INVALID") from exc
    if Path(top).resolve() != root:
        raise CanaryError("CANARY_CANDIDATE_ROOT_INVALID")
    if head != candidate_sha:
        raise CanaryError("CANARY_CANDIDATE_HEAD_MISMATCH")
    if status:
        raise CanaryError("CANARY_CANDIDATE_WORKTREE_DIRTY")
    source = Path(__file__ if runtime_source is None else runtime_source).resolve()
    expected_source = (
        root
        / "codex-loop-prompt-architect"
        / "scripts"
        / "loop_architect"
        / "v4_entry"
        / "canary.py"
    ).resolve()
    if source != expected_source or not source.is_file():
        raise CanaryError("CANARY_RUNTIME_PAYLOAD_MISMATCH")
    body = {
        "candidate_execution_mode": "CLEAN_GIT_WORKTREE",
        "candidate_sha": candidate_sha,
        "candidate_tree_sha": tree,
    }
    body["candidate_provenance_digest"] = _domain_digest(
        CANARY_CANDIDATE_PROVENANCE_DOMAIN, body
    )
    return body


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


def _canary_filenames(goal_count: int) -> tuple[str, ...]:
    if goal_count not in {1, 2, 8}:
        raise CanaryError("CANARY_GOAL_COUNT_INVALID")
    if goal_count == 1:
        return (CANARY_OUTPUT_FILENAME,)
    return tuple(f"canary-output-{index:02d}.txt" for index in range(1, goal_count + 1))


def _canary_goal(filename: str) -> str:
    return (
        f"In this workspace, create exactly one new regular file named {filename} "
        "with UTF-8 content 'LOOPSKILL4_CANARY_OK' followed by exactly one LF byte. "
        "Preserve any already-created canary output files and create no other entries. "
        f"Then check locally that {filename} exists and that its SHA-256 is "
        f"{CANARY_OUTPUT_SHA256}. Return PASS only when all of those local checks "
        "succeed; return FAILED when a completed check does not match; use LIMITATION "
        "or UNVERIFIABLE only when one of those local checks cannot actually be performed."
    )


def _request(goal_count: int = 1) -> LoopIntakeInput:
    if goal_count == 1:
        return LoopIntakeInput(
            goal=CANARY_GOAL,
            goal_plan=(CANARY_GOAL,),
            task_horizon="long",
            write_scope=(CANARY_OUTPUT_FILENAME,),
            budget="Complete only the stated local file operation and local checks.",
            external_actions=(),
            acceptance_criteria=(
                "artifact-changed",
                f"file-exists:{CANARY_OUTPUT_FILENAME}",
                f"file-sha256:{CANARY_OUTPUT_FILENAME}={CANARY_OUTPUT_SHA256}",
            ),
            stop_conditions=(
                "Stop after the stated local file and workspace checks are complete.",
            ),
            authorization_boundaries=(
                f"Write only {CANARY_OUTPUT_FILENAME} inside this workspace.",
                "Do not read or write outside this workspace.",
                "Do not use the network or perform commit, push, publish, or deploy actions.",
            ),
        )
    filenames = _canary_filenames(goal_count)
    goals = tuple(_canary_goal(filename) for filename in filenames)
    source_digest = hashlib.sha256(
        f"loopskill-v4.2-capacity-canary:{goal_count}".encode("ascii")
    ).hexdigest()
    plan = canonicalize_plan(
        {
            "boundaries": {
                "destructive_actions_allowed": False,
                "external_actions": [],
                "forbidden_actions": [
                    "Do not read or write outside this workspace.",
                    "Do not use the network or perform commit, push, publish, or deploy actions.",
                ],
                "forbidden_paths": [],
                "write_scope": list(filenames),
            },
            "budget": {
                "currency": None,
                "max_cost_minor_units": 0,
                "max_host_invocations": goal_count,
                "wall_clock_seconds": 7_200,
            },
            "completion_evidence": [
                f"file-sha256:{filename}={CANARY_OUTPUT_SHA256}"
                for filename in filenames
            ],
            "goals": [
                {
                    "acceptance_criteria": [
                        "artifact-changed",
                        f"file-exists:{filename}",
                        f"file-sha256:{filename}={CANARY_OUTPUT_SHA256}",
                    ],
                    "goal_id": f"g{index:03d}",
                    "objective": objective,
                }
                for index, (filename, objective) in enumerate(zip(filenames, goals))
            ],
            "objective": goals[0],
            "roadmap_policy": {"max_reorders": 0, "mode": "STANDARD"},
            "schema": "loopskill-plan-v1",
            "source": {
                "kind": "expert_semantic_json",
                "source_content_retained": False,
                "source_digest": source_digest,
            },
            "stop_conditions": [
                "Stop after the current local file and workspace checks are complete.",
                "Stop on any uncertain Host outcome; never resend an invocation.",
            ],
        }
    )
    return LoopIntakeInput(
        goal=goals[0],
        goal_plan=goals,
        task_horizon="long",
        write_scope=filenames,
        budget=f"At most {goal_count} Host invocations and two hours; no paid service.",
        external_actions=(),
        acceptance_criteria=tuple(plan["completion_evidence"]),
        stop_conditions=tuple(plan["stop_conditions"]),
        authorization_boundaries=tuple(plan["boundaries"]["forbidden_actions"]),
        canonical_plan=plan,
        source_kind="expert_semantic_json",
        source_digest=source_digest,
        source_bytes=0,
    )


def _default_wait(provider: Any, workspace: Path, *, timeout_seconds: float = 30_000.0) -> None:
    """Wait read-only for the unique invocation; never use file timing as closure."""

    del workspace
    waiter = getattr(provider, "wait_for_terminal", None)
    if not callable(waiter):
        raise CanaryError("CANARY_TERMINAL_WAIT_UNAVAILABLE")
    try:
        waiter(timeout_seconds=timeout_seconds)
    except HostUnavailable as exc:
        code = getattr(exc, "provider_code", None)
        if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", code):
            raise CanaryError(f"CANARY_PROVIDER_{code}") from exc
        raise CanaryError("CANARY_TERMINAL_EVIDENCE_UNCLASSIFIED") from exc
    except ValueError as exc:
        raise CanaryError("CANARY_TERMINAL_WAIT_CONTRACT_INVALID") from exc


def _verify_workspace(workspace: Path, goal_count: int = 1) -> None:
    expected_names = set(_canary_filenames(goal_count))
    try:
        entries = list(workspace.iterdir())
        if len(entries) != goal_count or {entry.name for entry in entries} != expected_names:
            raise OSError("unexpected workspace surface")
        for output in entries:
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
                    or raw != CANARY_OUTPUT_BYTES
                    or hashlib.sha256(raw).hexdigest() != CANARY_OUTPUT_SHA256
                ):
                    raise OSError("output changed or invalid")
            finally:
                os.close(descriptor)
    except OSError as exc:
        raise CanaryError("CANARY_OUTPUT_INVALID") from exc


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


def _aggregate_provider_metrics(
    providers: tuple[Any, ...], goal_count: int
) -> dict[str, int]:
    if len(providers) != goal_count:
        raise CanaryError("CANARY_PROVIDER_METRICS_INVALID")
    values = {name: 0 for name in _SAFE_PROVIDER_METRICS}
    for provider in providers:
        raw = getattr(provider, "metrics", None)
        raw = raw() if callable(raw) else raw
        if not isinstance(raw, Mapping) or not _SAFE_PROVIDER_METRICS <= set(raw):
            raise CanaryError("CANARY_PROVIDER_METRICS_UNAVAILABLE")
        for name in _SAFE_PROVIDER_METRICS:
            current = raw[name]
            if isinstance(current, bool) or not isinstance(current, int) or current < 0:
                raise CanaryError("CANARY_PROVIDER_METRICS_INVALID")
            values[name] += current
    if (
        values["delivery_readback_count"] < goal_count
        or values["delivery_readback_count"] > 3 * goal_count
        or values["duplicate_invoke_rejection_count"] != 0
        or values["lifecycle_read_count"] != 1
        or values["provider_resend_count"] != 0
        or values["task_create_count"] != goal_count
        or values["task_result_read_count"] != goal_count
        or values["terminal_wait_read_count"] != goal_count
    ):
        raise CanaryError("CANARY_PROVIDER_METRICS_INVALID")
    return values


def _provider_terminal_diagnostic(provider: Any) -> dict[str, Any]:
    reader = getattr(provider, "terminal_diagnostic", None)
    raw = reader() if callable(reader) else None
    required = {
        "artifact",
        "code",
        "primary_code",
        "result_bytes",
        "result_control_digest",
        "result_sha256",
        "returncode_class",
        "schema_control_digest",
        "semantic_outcome",
        "semantic_summary",
        "stderr_bytes",
        "stderr_sha256",
        "stdout_bytes",
        "stdout_sha256",
        "terminal_event_count",
        "terminal_event_type",
    }
    if not isinstance(raw, Mapping) or set(raw) != required:
        raise CanaryError("CANARY_PROVIDER_DIAGNOSTIC_UNAVAILABLE")
    value = dict(raw)
    if (
        value["artifact"] != "loopskill-codex-exec-terminal-diagnostic-v1"
        or not isinstance(value["code"], str)
        or not re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", value["code"])
        or (
            value["primary_code"] is not None
            and (
                not isinstance(value["primary_code"], str)
                or not re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", value["primary_code"])
            )
        )
        or value["returncode_class"] not in {"ZERO", "NONZERO", "UNAVAILABLE"}
        or value["terminal_event_type"] not in {None, "turn.completed", "turn.failed", "error"}
    ):
        raise CanaryError("CANARY_PROVIDER_DIAGNOSTIC_INVALID")
    for name in (
        "result_bytes",
        "stderr_bytes",
        "stdout_bytes",
        "terminal_event_count",
    ):
        if isinstance(value[name], bool) or not isinstance(value[name], int) or value[name] < 0:
            raise CanaryError("CANARY_PROVIDER_DIAGNOSTIC_INVALID")
    for name in (
        "result_control_digest",
        "result_sha256",
        "schema_control_digest",
        "stderr_sha256",
        "stdout_sha256",
    ):
        if not isinstance(value[name], str) or not re.fullmatch(r"[0-9a-f]{64}", value[name]):
            raise CanaryError("CANARY_PROVIDER_DIAGNOSTIC_INVALID")
    semantic = {
        "outcome": value["semantic_outcome"],
        "summary": value["semantic_summary"],
    }
    if semantic == {"outcome": None, "summary": None}:
        if value["code"] == "PASS":
            raise CanaryError("CANARY_PROVIDER_DIAGNOSTIC_INVALID")
    else:
        try:
            validate_result_payload(semantic)
        except ProtocolRejection as exc:
            raise CanaryError("CANARY_PROVIDER_DIAGNOSTIC_INVALID") from exc
    return value


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
    goal_count: int = 1,
) -> tuple[dict[str, Any], str]:
    _verify_workspace(workspace, goal_count)
    path = store_root / STORE_FILENAME
    with SQLiteStore(path) as store:
        store.verify_integrity()
        descriptors = store.loop_descriptors()
        if len(descriptors) != 1 or descriptors[0]["goal"] != _request(goal_count).goal:
            raise CanaryError("CANARY_CANDIDATE_BINDING_INVALID")
        snapshot = store.snapshot(descriptors[0]["loop_ref"])
        if snapshot is None:
            raise CanaryError("CANARY_CLOSURE_INVALID")
        effects = tuple(snapshot.get("external_effects", {}).values())
        results = tuple(snapshot.get("results", {}).values())
        reports = tuple(snapshot.get("reports", {}).values())
        artifacts = tuple(snapshot.get("artifacts", {}).values())
        reviews = tuple(snapshot.get("reviews", {}).values())
        finalization = _single(
            snapshot.get("finalizations", {}), "CANARY_CLOSURE_INVALID"
        )
        if (
            len(effects) != goal_count
            or len(results) != goal_count
            or len(reports) != goal_count
            or len(artifacts) != goal_count
            or len(reviews) != goal_count
            or any(
                result.get("state") != "ACKNOWLEDGED"
                or result.get("outcome") != "PASS"
                or not isinstance(result.get("source_observation_digest"), str)
                for result in results
            )
            or any(report.get("state") != "ACCEPTED" for report in reports)
            or any(artifact.get("state") != "VERIFIED" for artifact in artifacts)
            or any(review.get("state") != "PASS" for review in reviews)
            or finalization.get("state") != "EXECUTION_CLOSED"
            or snapshot.get("execution", {}).get("state") != "TERMINAL"
            or snapshot.get("execution", {}).get("disposition") != "SUCCEEDED"
            or snapshot.get("closure_assurance", {}).get("strength") != "STRICT"
        ):
            raise CanaryError("CANARY_CLOSURE_INVALID")
        provider_ids: list[str] = []
        for effect in effects:
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
            provider_ids.append(provider_id)
        result_digests = [str(result["source_observation_digest"]) for result in results]
        host_identity_digest = (
            _domain_digest(CANARY_HOST_ID_DOMAIN, provider_ids[0])
            if goal_count == 1
            else _domain_digest(CANARY_HOST_ID_DOMAIN, provider_ids)
        )
        result_digest = (
            result_digests[0]
            if goal_count == 1
            else _domain_digest(CANARY_LIVE_DOMAIN, result_digests)
        )
        live = {
            "artifact_state": "VERIFIED",
            "assurance": snapshot["closure_assurance"]["strength"],
            "canary_output_sha256": CANARY_OUTPUT_SHA256,
            "candidate_goal_digest": descriptors[0]["goal_digest"],
            "candidate_sha": candidate_sha,
            "execution_disposition": snapshot["execution"]["disposition"],
            "execution_state": snapshot["execution"]["state"],
            "finalization_state": finalization["state"],
            "host_task_identity_digest": host_identity_digest,
            "lifecycle_state": "TERMINAL",
            "result_digest": result_digest,
            "result_outcome": "PASS",
            "result_state": "ACKNOWLEDGED",
            "report_state": "ACCEPTED",
            "review_state": "PASS",
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
    provider_diagnostic: Any,
    candidate_provenance: Mapping[str, str],
    goal_count: int = 1,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "artifact": CANARY_ARTIFACT,
        "candidate_execution_mode": candidate_provenance[
            "candidate_execution_mode"
        ],
        "candidate_provenance_digest": candidate_provenance[
            "candidate_provenance_digest"
        ],
        "candidate_sha": candidate_sha,
        "candidate_tree_sha": candidate_provenance["candidate_tree_sha"],
        "candidate_goal_digest": live["candidate_goal_digest"],
        "canary_output_sha256": live["canary_output_sha256"],
        "confirmation_count": 1,
        "confirmation_digest_bound": True,
        "allowed_host_managed_delta_count": integrity["host_config_delta"][
            "allowed_host_managed_delta_count"
        ],
        "canary_workspace_identity_digest": integrity["host_config_delta"][
            "workspace_identity_digest"
        ],
        "entry": "loopskill4",
        "finalization": "ACKNOWLEDGED",
        "fresh_until": _iso(
            issued_at + timedelta(minutes=10 if goal_count == 1 else 120)
        ),
        "host_auth_after_digest": integrity["after"]["host_auth"]["digest"],
        "host_auth_before_digest": integrity["before"]["host_auth"]["digest"],
        "host_config_after_digest": integrity["after"]["host_config"]["digest"],
        "host_config_before_digest": integrity["before"]["host_config"]["digest"],
        "host_config_delta_kind": integrity["host_config_delta"]["delta_kind"],
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
        "observed_host_auth_changed_bytes": integrity["changed_bytes"]["host_auth"],
        "observed_host_config_changed_bytes": integrity["changed_bytes"][
            "host_config"
        ],
        "app_restart_count": 0,
        "prepare_delivery_count": 0,
        "prepare_heartbeat_count": 0,
        "prepare_host_effects": 0,
        "prepare_host_task_count": 0,
        "private_data_used": False,
        "provider_resend_count": metrics["provider_resend_count"],
        "provider_terminal_diagnostic_digest": _domain_digest(
            CANARY_PROVIDER_DIAGNOSTIC_DOMAIN, provider_diagnostic
        ),
        "research_scored": False,
        "result": "ACKNOWLEDGED",
        "review": "PASS",
        "status": "PASS",
        "thread_content_retained": False,
        "integrity_measurement_digest": integrity["measurement_digest"],
        "unknown_preserved": True,
        "unexpected_changed_input_count": integrity["host_config_delta"][
            "unexpected_changed_input_count"
        ],
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
    candidate_root: Path | str | None = None,
    confirmation_callback: Callable[[Mapping[str, Any]], bool],
    goal_count: int = 1,
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
    candidate_provenance = _candidate_provenance(candidate, candidate_root)
    root = _ensure_empty_private_root(evidence_root).resolve(strict=True)
    workspace = root / "workspace"
    workspace.mkdir(mode=0o700)
    workspace = _canonical_workspace(workspace)
    prepared_root = root / "prepared"
    store_root = root / "store"

    _canary_filenames(goal_count)
    request = _request(goal_count)
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
            **candidate_provenance,
            "candidate_sha": candidate,
            "inputs": _integrity_public(before_integrity),
            "issued_at": _iso(issued_at),
            "workspace_identity_digest": _workspace_identity_digest(workspace),
        },
    )

    providers: list[Any] = []
    provider_diagnostics: list[Mapping[str, Any]] = []
    after_integrity = None
    integrity_observed_at = None
    final_view = None
    try:
        for index in range(goal_count):
            if provider_factory is None:
                provider = CodexExecProvider(
                    workspace,
                    issuer_ref=CANARY_ISSUER,
                    issuer_trust=CANARY_TRUST,
                    clock=clock,
                )
            else:
                provider = provider_factory(workspace)
            providers.append(provider)
            try:
                preflight = getattr(provider, "preflight", None)
                if not callable(preflight):
                    raise CanaryError("CANARY_HOST_PROTOCOL_PREFLIGHT_UNAVAILABLE")
                try:
                    preflight()
                except HostUnavailable as exc:
                    raise CanaryError("CANARY_HOST_PROTOCOL_INCOMPATIBLE") from exc

                if index == 0:
                    # Exactly one public START. No exception path re-enters it.
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
                    final_view = sync_loop(
                        root=store_root,
                        host_provider=provider,
                        host_issuer_ref=CANARY_ISSUER,
                        host_issuer_trust=CANARY_TRUST,
                        clock=clock,
                        workspace_root=workspace,
                    )
                else:
                    # A fresh one-invocation Provider owns each already-committed
                    # next-Goal Attempt; no Provider instance is reused.
                    final_view = sync_loop(
                        root=store_root,
                        host_provider=provider,
                        host_issuer_ref=CANARY_ISSUER,
                        host_issuer_trust=CANARY_TRUST,
                        clock=clock,
                        workspace_root=workspace,
                    )
                    (wait_callback or _default_wait)(provider, workspace)
            finally:
                close = getattr(provider, "close", None)
                if callable(close):
                    close()
                try:
                    diagnostic = _provider_terminal_diagnostic(provider)
                except CanaryError:
                    diagnostic = None
                if diagnostic is not None:
                    provider_diagnostics.append(diagnostic)
                    filename = (
                        CANARY_PROVIDER_DIAGNOSTIC_FILENAME
                        if goal_count == 1
                        else f"canary-provider-diagnostic-{index + 1:02d}.json"
                    )
                    _write_canonical_once(root, filename, diagnostic)
    finally:
        after_integrity = _integrity_snapshot(integrity_inputs)
        integrity_observed_at = clock()
        comparison = _integrity_comparison(
            candidate,
            before_integrity,
            after_integrity,
            integrity_observed_at,
            workspace,
        )
        _write_canonical_once(root, CANARY_INTEGRITY_FILENAME, comparison)
    if comparison["host_config_delta"]["unexpected_changed_input_count"] != 0:
        raise CanaryError("CANARY_HOST_INTEGRITY_CHANGED")
    if final_view is None or final_view.progress != "Finished" or final_view.result != "SUCCEEDED":
        raise CanaryError("CANARY_OUTCOME_NOT_PASS")

    _verify_workspace(workspace, goal_count)
    assert integrity_observed_at is not None
    provider_tuple = tuple(providers)
    metrics = (
        _provider_metrics(provider_tuple[0])
        if goal_count == 1
        else _aggregate_provider_metrics(provider_tuple, goal_count)
    )
    if (
        len(provider_diagnostics) != goal_count
        or any(item.get("code") != "PASS" for item in provider_diagnostics)
    ):
        raise CanaryError("CANARY_PROVIDER_DIAGNOSTIC_INVALID")
    live, _ = _live_summary(candidate, store_root, workspace, goal_count)
    diagnostic_evidence: Any = (
        provider_diagnostics[0] if goal_count == 1 else provider_diagnostics
    )
    receipt = _receipt(
        candidate,
        live,
        metrics,
        comparison,
        issued_at,
        integrity_observed_at,
        diagnostic_evidence,
        candidate_provenance,
        goal_count,
    )
    _write_receipt(root, receipt)
    return receipt
