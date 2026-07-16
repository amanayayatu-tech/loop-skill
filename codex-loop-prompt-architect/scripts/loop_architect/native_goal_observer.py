"""Bounded, read-only Codex rollout observations for native Goal recovery.

The observer never mutates Codex App state or its rollout.  It emits only a
sanitized structural receipt that the canonical state runtime can recompute
from the same stable rollout snapshot before accepting a recovery mutation.
"""

from __future__ import annotations

import hashlib
import errno
import json
import os
import re
import stat
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


MAX_ROLLOUT_BYTES = 128 * 1024 * 1024
MAX_OBSERVE_SECONDS = 15.0
CREATE_GOAL_TEMPLATE_RE = re.compile(
    r"\A\s*const\s+result\s*=\s*await\s+tools\.create_goal\s*"
    r"\((\{.*\})\)\s*;\s*text\s*\(\s*(?:JSON\.stringify\s*"
    r"\(\s*result\s*\)|result)\s*\)\s*;\s*\Z",
    re.DOTALL,
)
GET_GOAL_TEMPLATE_RE = re.compile(
    r"\A\s*const\s+result\s*=\s*await\s+tools\.get_goal\s*"
    r"\(\s*\{\s*\}\s*\)\s*;\s*text\s*\(\s*(?:JSON\.stringify\s*"
    r"\(\s*result\s*\)|result)\s*\)\s*;\s*\Z",
    re.DOTALL,
)
CONTROL_TOOL_TEMPLATE_RE = re.compile(
    r"\A\s*const\s+result\s*=\s*await\s+tools\.([A-Za-z0-9_]+)\s*"
    r"\((\{.*\})\)\s*;\s*text\s*\(\s*(?:JSON\.stringify\s*"
    r"\(\s*result\s*\)|result)\s*\)\s*;\s*\Z",
    re.DOTALL,
)
ROUTE_CONTROL_TOOLS = frozenset(
    {"route_state_mutation", "mcp__codex_loop_state__route_state_mutation"}
)
SEND_CONTROL_TOOLS = frozenset(
    {
        "send_message_to_thread",
        "codex_app__send_message_to_thread",
        "mcp__codex_app__send_message_to_thread",
    }
)
ALLOWED_POST_READBACK_CONTROL_TOOLS = ROUTE_CONTROL_TOOLS | SEND_CONTROL_TOOLS
NATIVE_GOAL_HANDOFF_FIELDS = frozenset(
    {
        "goal_observation_path",
        "lease_claim",
        "migration_id",
        "null_observation_paths",
        "observed_at",
        "rollback_reason",
        "rollout_observation_path",
        "type",
    }
)


class NativeGoalObservationError(Exception):
    """Fail-closed observer error with a stable public classification."""

    def __init__(self, code: str, details: dict[str, Any] | None = None):
        super().__init__(code)
        self.code = code
        self.details = details or {}


def default_trusted_rollout_roots() -> tuple[Path, ...]:
    """Return the only production roots from which Codex rollouts may be read."""

    codex_home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    return (codex_home / "sessions", codex_home / "archived_sessions")


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _native_goal_handoff_payload(request: Any) -> dict[str, Any] | None:
    if not isinstance(request, dict) or not isinstance(
        request.get("mutation"), dict
    ):
        return None
    mutation = request["mutation"]
    identity = {
        key: mutation[key]
        for key in sorted(NATIVE_GOAL_HANDOFF_FIELDS)
        if key in mutation
    }
    if identity.get("type") not in {
        "COMMIT_NATIVE_GOAL_GENERATION_MIGRATION",
        "ROLLBACK_NATIVE_GOAL_GENERATION_MIGRATION",
    }:
        return None
    return {"mutation": identity}


def native_goal_handoff_digest(request: Any) -> str | None:
    """Digest the Controller-authored recovery handoff identity."""

    payload = _native_goal_handoff_payload(request)
    return _sha256_bytes(_canonical_bytes(payload)) if payload else None


def _sanitized_control_action(
    tool_name: str,
    arguments: dict[str, Any],
    turn_id: str | None,
) -> dict[str, Any] | None:
    if tool_name in ROUTE_CONTROL_TOOLS:
        if set(arguments) != {"root", "request"}:
            return None
        root = arguments.get("root")
        request = arguments.get("request")
        mutation = request.get("mutation") if isinstance(request, dict) else None
        if (
            not isinstance(root, str)
            or not isinstance(mutation, dict)
            or mutation.get("type") != "ACQUIRE_LEASE"
            or mutation.get("controller_turn_id") is not None
        ):
            return None
        required = (
            "authorization_digest",
            "authorization_steering_id",
            "controller_pack_digest",
            "migration_id",
            "recovery_scope",
            "routing_turn_id",
            "lease_id",
            "state_writer_thread_id",
        )
        if any(not isinstance(mutation.get(key), str) for key in required):
            return None
        return {
            "action_kind": "ROUTE_RECOVERY_LEASE",
            "turn_id": turn_id,
            "root_digest": _sha256_bytes(root.encode("utf-8")),
            **{key: mutation[key] for key in required},
        }
    schemas = (
        ("threadId", "prompt"),
        ("target", "message"),
    )
    selected = next(
        (schema for schema in schemas if set(arguments) == set(schema)),
        None,
    )
    if selected is None:
        return None
    target = arguments.get(selected[0])
    prompt = arguments.get(selected[1])
    if not isinstance(target, str) or not isinstance(prompt, str):
        return None
    try:
        handoff = _strict_json(prompt, "NATIVE_GOAL_CONTROL_SUFFIX_INVALID")
    except NativeGoalObservationError:
        return None
    handoff_digest = native_goal_handoff_digest(handoff)
    normalized_handoff = _native_goal_handoff_payload(handoff)
    if (
        handoff_digest is None
        or normalized_handoff is None
        or prompt.encode("utf-8") != _canonical_bytes(normalized_handoff)
    ):
        return None
    return {
        "action_kind": "SEND_STATE_WRITER_HANDOFF",
        "turn_id": turn_id,
        "target_thread_digest": _sha256_bytes(target.encode("utf-8")),
        "handoff_digest": handoff_digest,
        "prompt_bytes_digest": handoff_digest,
    }


def _strict_json(payload: str, code: str) -> Any:
    def no_duplicates(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise NativeGoalObservationError(
                    code, {"reason": "DUPLICATE_JSON_KEY"}
                )
            result[key] = value
        return result

    try:
        return json.loads(payload, object_pairs_hook=no_duplicates)
    except NativeGoalObservationError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise NativeGoalObservationError(
            code, {"reason": "JSON_PARSE_FAILED"}
        ) from exc


def _safe_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def runtime_manifest_digest() -> str:
    here = Path(__file__).resolve()
    state_runtime = here.with_name("state_runtime.py")
    cli_adapter = here.parent.parent / "adaptive_state_runtime.py"
    entries = []
    for path in sorted(
        (here, state_runtime, cli_adapter), key=lambda item: item.name
    ):
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise NativeGoalObservationError(
                "NATIVE_GOAL_OBSERVER_RUNTIME_MANIFEST_UNAVAILABLE"
            ) from exc
        entries.append({"name": path.name, "digest": _sha256_bytes(payload)})
    return _sha256_bytes(_canonical_bytes(entries))


@dataclass(frozen=True)
class StableRollout:
    path: Path
    payload: bytes
    stat_result: os.stat_result
    snapshot_digest: str
    file_identity_digest: str


def _stable_rollout(
    path: Path,
    trusted_rollout_roots: tuple[Path, ...] | None,
) -> StableRollout:
    started = time.monotonic()
    if not path.is_absolute():
        raise NativeGoalObservationError(
            "NATIVE_GOAL_ROLLOUT_PATH_INVALID", {"reason": "NOT_ABSOLUTE"}
        )
    absolute_path = Path(os.path.abspath(os.fspath(path)))
    try:
        secure_path = absolute_path.parent.resolve(strict=True) / absolute_path.name
    except OSError as exc:
        raise NativeGoalObservationError(
            "NATIVE_GOAL_ROLLOUT_UNAVAILABLE"
        ) from exc
    trusted_roots = tuple(
        Path(os.path.abspath(os.fspath(root.expanduser()))).resolve(strict=False)
        for root in (
            trusted_rollout_roots
            if trusted_rollout_roots is not None
            else default_trusted_rollout_roots()
        )
    )
    lexical_root = next(
        (root for root in trusted_roots if secure_path.is_relative_to(root)),
        None,
    )
    if lexical_root is None:
        raise NativeGoalObservationError(
            "NATIVE_GOAL_ROLLOUT_PATH_INVALID",
            {"reason": "PATH_ESCAPE_OR_SYMLINK"},
        )
    relative_parts = secure_path.relative_to(lexical_root).parts
    if not relative_parts:
        raise NativeGoalObservationError(
            "NATIVE_GOAL_ROLLOUT_PATH_INVALID", {"reason": "NOT_A_FILE"}
        )
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        # Walk from the filesystem root with openat-style dir_fd calls. No
        # component is ever followed after a separate path check.
        directory_fd = os.open("/", directory_flags)
        for component in lexical_root.parts[1:]:
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        for component in relative_parts[:-1]:
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(relative_parts[-1], file_flags, dir_fd=directory_fd)
        before = os.fstat(file_fd)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise NativeGoalObservationError(
                "NATIVE_GOAL_ROLLOUT_PATH_INVALID",
                {"reason": "PATH_ESCAPE_OR_SYMLINK"},
            ) from exc
        raise NativeGoalObservationError(
            "NATIVE_GOAL_ROLLOUT_UNAVAILABLE"
        ) from exc
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
    if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid():
        assert file_fd is not None
        os.close(file_fd)
        file_fd = None
        raise NativeGoalObservationError(
            "NATIVE_GOAL_ROLLOUT_IDENTITY_INVALID",
            {"reason": "OWNER_OR_TYPE_INVALID"},
        )
    if before.st_size > MAX_ROLLOUT_BYTES:
        assert file_fd is not None
        os.close(file_fd)
        file_fd = None
        raise NativeGoalObservationError(
            "NATIVE_GOAL_ROLLOUT_TOO_LARGE",
            {"max_bytes": MAX_ROLLOUT_BYTES},
        )
    try:
        assert file_fd is not None
        with os.fdopen(file_fd, "rb", buffering=0) as handle:
            file_fd = None
            payload = handle.read(MAX_ROLLOUT_BYTES + 1)
            if handle.read(1):
                raise NativeGoalObservationError(
                    "NATIVE_GOAL_ROLLOUT_TOO_LARGE",
                    {"max_bytes": MAX_ROLLOUT_BYTES},
                )
            after_open = os.fstat(handle.fileno())
    except NativeGoalObservationError:
        raise
    except OSError as exc:
        raise NativeGoalObservationError(
            "NATIVE_GOAL_ROLLOUT_UNAVAILABLE"
        ) from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(
        getattr(before, field) != getattr(after_open, field)
        for field in stable_fields
    ):
        raise NativeGoalObservationError(
            "NATIVE_GOAL_ROLLOUT_CONCURRENT_CHANGE"
        )
    if len(payload) != before.st_size or (payload and not payload.endswith(b"\n")):
        raise NativeGoalObservationError(
            "NATIVE_GOAL_ROLLOUT_PARSE_INCOMPLETE"
        )
    if time.monotonic() - started > MAX_OBSERVE_SECONDS:
        raise NativeGoalObservationError(
            "NATIVE_GOAL_ROLLOUT_OBSERVE_TIMEOUT"
        )
    identity = {
        "device": before.st_dev,
        "inode": before.st_ino,
        "uid": before.st_uid,
        "mode": stat.S_IMODE(before.st_mode),
        "path_digest": _sha256_bytes(os.fsencode(str(secure_path))),
    }
    return StableRollout(
        path=secure_path,
        payload=payload,
        stat_result=before,
        snapshot_digest=_sha256_bytes(payload),
        file_identity_digest=_sha256_bytes(_canonical_bytes(identity)),
    )


def _tool_output_object(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, list):
        return None
    parsed: dict[str, Any] | None = None
    for block in value:
        if not isinstance(block, dict) or block.get("type") != "input_text":
            continue
        text = block.get("text")
        if not isinstance(text, str):
            continue
        try:
            candidate = _strict_json(text, "NATIVE_GOAL_TOOL_RESULT_INVALID")
        except NativeGoalObservationError:
            continue
        if isinstance(candidate, dict):
            parsed = candidate
    return parsed


def _objective_identity(objective: str) -> dict[str, Any] | None:
    if not objective or objective.endswith("\n") or "\n" not in objective:
        return None
    body, marker = objective.rsplit("\n", 1)
    return {
        "objective_digest": _sha256_bytes(body.encode("utf-8")),
        "objective_bytes_digest": _sha256_bytes(objective.encode("utf-8")),
        "marker_digest": _sha256_bytes(marker.encode("utf-8")),
    }


def _sanitized_goal(goal: Any) -> dict[str, Any] | None:
    if goal is None:
        return None
    if not isinstance(goal, dict):
        raise NativeGoalObservationError("NATIVE_GOAL_TOOL_RESULT_INVALID")
    objective = goal.get("objective")
    identity = _objective_identity(objective) if isinstance(objective, str) else None
    if identity is None:
        raise NativeGoalObservationError("NATIVE_GOAL_TOOL_RESULT_INVALID")
    result = {
        "thread_id": goal.get("threadId"),
        "status": goal.get("status"),
        "created_at": goal.get("createdAt"),
        "updated_at": goal.get("updatedAt"),
        "tokens_used": goal.get("tokensUsed"),
        "time_used_seconds": goal.get("timeUsedSeconds"),
        **identity,
    }
    if (
        not isinstance(result["thread_id"], str)
        or not isinstance(result["status"], str)
        or not isinstance(result["created_at"], int)
        or not isinstance(result["updated_at"], int)
    ):
        raise NativeGoalObservationError("NATIVE_GOAL_TOOL_RESULT_INVALID")
    return result


def _parse_rollout_events(
    snapshot: StableRollout,
    controller_thread_id: str,
) -> list[tuple[int, dict[str, Any]]]:
    events: list[tuple[int, dict[str, Any]]] = []
    session_ids: set[str] = set()
    offset = 0
    started = time.monotonic()
    for raw in snapshot.payload.splitlines(keepends=True):
        line_start = offset
        offset += len(raw)
        if time.monotonic() - started > MAX_OBSERVE_SECONDS:
            raise NativeGoalObservationError(
                "NATIVE_GOAL_ROLLOUT_OBSERVE_TIMEOUT"
            )
        try:
            text = raw[:-1].decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise NativeGoalObservationError(
                "NATIVE_GOAL_ROLLOUT_UTF8_INVALID"
            ) from exc
        event = _strict_json(text, "NATIVE_GOAL_ROLLOUT_PARSE_INCOMPLETE")
        if not isinstance(event, dict) or not isinstance(event.get("payload"), dict):
            raise NativeGoalObservationError(
                "NATIVE_GOAL_ROLLOUT_PARSE_INCOMPLETE"
            )
        payload = event["payload"]
        if event.get("type") == "session_meta":
            session_id = payload.get("id")
            if isinstance(session_id, str):
                session_ids.add(session_id)
        events.append((line_start, event))
    if session_ids != {controller_thread_id}:
        raise NativeGoalObservationError(
            "NATIVE_GOAL_ROLLOUT_THREAD_IDENTITY_INVALID",
            {"session_identity_count": len(session_ids)},
        )
    return events


def observe_native_goal_rollout(
    *,
    rollout_path: Path,
    controller_thread_id: str,
    mode: str,
    scan_start_offset: int = 0,
    scan_end_offset: int | None = None,
    historical_replay_snapshot_digest: str | None = None,
    control_suffix_start_offset: int | None = None,
    expected_objective_digest: str | None = None,
    expected_objective_bytes_digest: str | None = None,
    observed_at: str | None = None,
    trusted_rollout_roots: tuple[Path, ...] | None = None,
) -> dict[str, Any]:
    if mode not in {"GET_GOAL", "CREATE_GOAL"}:
        raise NativeGoalObservationError(
            "NATIVE_GOAL_OBSERVER_MODE_INVALID"
        )
    snapshot = _stable_rollout(rollout_path, trusted_rollout_roots)
    end_offset = (
        len(snapshot.payload) if scan_end_offset is None else scan_end_offset
    )
    if (
        scan_end_offset is not None
        and scan_end_offset != len(snapshot.payload)
        and historical_replay_snapshot_digest is None
    ):
        raise NativeGoalObservationError(
            "NATIVE_GOAL_ROLLOUT_HISTORICAL_CUTOFF_FORBIDDEN"
        )
    if (
        scan_start_offset < 0
        or end_offset < scan_start_offset
        or end_offset > len(snapshot.payload)
        or (
            control_suffix_start_offset is not None
            and (
                not isinstance(control_suffix_start_offset, int)
                or isinstance(control_suffix_start_offset, bool)
                or control_suffix_start_offset < scan_start_offset
                or control_suffix_start_offset > end_offset
            )
        )
        or (
            scan_start_offset > 0
            and snapshot.payload[scan_start_offset - 1 : scan_start_offset]
            != b"\n"
        )
        or (
            end_offset > 0
            and snapshot.payload[end_offset - 1 : end_offset] != b"\n"
        )
    ):
        raise NativeGoalObservationError(
            "NATIVE_GOAL_ROLLOUT_HIGH_WATERMARK_INVALID"
        )
    observed_payload = snapshot.payload[:end_offset]
    observed_snapshot_digest = _sha256_bytes(observed_payload)
    if (
        historical_replay_snapshot_digest is not None
        and historical_replay_snapshot_digest != observed_snapshot_digest
    ):
        raise NativeGoalObservationError(
            "NATIVE_GOAL_ROLLOUT_APPEND_ONLY_CONTINUITY_INVALID"
        )
    observed_snapshot = StableRollout(
        path=snapshot.path,
        payload=observed_payload,
        stat_result=snapshot.stat_result,
        snapshot_digest=observed_snapshot_digest,
        file_identity_digest=snapshot.file_identity_digest,
    )
    events = _parse_rollout_events(observed_snapshot, controller_thread_id)
    current_turn: str | None = None
    calls: dict[str, dict[str, Any]] = {}
    outputs: dict[str, Any] = {}
    tool_call_counts: dict[str | None, int] = {}
    turn_start_offsets: dict[str, int] = {}
    turn_end_offsets: dict[str, int] = {}
    control_actions: list[dict[str, Any]] = []
    ambiguous_create = False
    for offset, event in events:
        payload = event["payload"]
        event_type = payload.get("type")
        if event_type == "task_started" and isinstance(payload.get("turn_id"), str):
            current_turn = payload["turn_id"]
            turn_start_offsets[current_turn] = offset
        elif event_type in {"task_complete", "turn_aborted"}:
            if isinstance(payload.get("turn_id"), str):
                turn_end_offsets[payload["turn_id"]] = offset
            current_turn = None
        if offset < scan_start_offset:
            continue
        if event_type == "custom_tool_call" and isinstance(
            payload.get("call_id"), str
        ):
            tool_call_counts[current_turn] = (
                tool_call_counts.get(current_turn, 0) + 1
            )
        if (
            event_type == "custom_tool_call"
            and payload.get("name") == "exec"
            and isinstance(payload.get("call_id"), str)
            and isinstance(payload.get("input"), str)
        ):
            source = payload["input"]
            call_id = payload["call_id"]
            match = CREATE_GOAL_TEMPLATE_RE.fullmatch(source)
            if match is not None:
                arguments = _strict_json(
                    match.group(1), "NATIVE_GOAL_CREATE_INVOCATION_INVALID"
                )
                if (
                    not isinstance(arguments, dict)
                    or set(arguments) != {"objective"}
                    or not isinstance(arguments.get("objective"), str)
                ):
                    ambiguous_create = True
                    continue
                identity = _objective_identity(arguments["objective"])
                if identity is None:
                    ambiguous_create = True
                    continue
                calls[call_id] = {
                    "tool_name": "create_goal",
                    "turn_id": current_turn,
                    **identity,
                }
            elif GET_GOAL_TEMPLATE_RE.fullmatch(source) is not None:
                calls[call_id] = {
                    "tool_name": "get_goal",
                    "turn_id": current_turn,
                }
            else:
                control_match = CONTROL_TOOL_TEMPLATE_RE.fullmatch(source)
                if (
                    control_suffix_start_offset is not None
                    and offset >= control_suffix_start_offset
                    and control_match is not None
                    and control_match.group(1)
                    in ALLOWED_POST_READBACK_CONTROL_TOOLS
                ):
                    arguments = _strict_json(
                        control_match.group(2),
                        "NATIVE_GOAL_CONTROL_SUFFIX_INVALID",
                    )
                    action = (
                        _sanitized_control_action(
                            control_match.group(1), arguments, current_turn
                        )
                        if isinstance(arguments, dict)
                        else None
                    )
                    if action is None:
                        ambiguous_create = True
                    else:
                        control_actions.append(action)
                else:
                    # The recovery window permits only exact Goal wrappers and
                    # the two strict post-readback control wrappers above.
                    ambiguous_create = True
        elif event_type == "custom_tool_call":
            tool_name = payload.get("name")
            allowed_control = (
                control_suffix_start_offset is not None
                and offset >= control_suffix_start_offset
                and isinstance(tool_name, str)
                and tool_name in ALLOWED_POST_READBACK_CONTROL_TOOLS
            )
            if allowed_control:
                direct_arguments = payload.get("input")
                if isinstance(direct_arguments, str):
                    try:
                        direct_arguments = _strict_json(
                            direct_arguments,
                            "NATIVE_GOAL_CONTROL_SUFFIX_INVALID",
                        )
                    except NativeGoalObservationError:
                        ambiguous_create = True
                        continue
                action = (
                    _sanitized_control_action(
                        tool_name, direct_arguments, current_turn
                    )
                    if isinstance(direct_arguments, dict)
                    else None
                )
                if action is None:
                    ambiguous_create = True
                else:
                    control_actions.append(action)
            else:
                # Native goal calls are valid recovery evidence only when
                # nested in an exact exec wrapper. Other calls fail closed
                # outside the bounded post-readback control suffix.
                ambiguous_create = True
        elif (
            event_type == "custom_tool_call_output"
            and isinstance(payload.get("call_id"), str)
        ):
            outputs[payload["call_id"]] = payload.get("output")

    base = {
        "observation_contract_version": 1,
        "controller_thread_digest": _sha256_bytes(
            controller_thread_id.encode("utf-8")
        ),
        "rollout_path": str(snapshot.path),
        "rollout_file_identity_digest": snapshot.file_identity_digest,
        "snapshot_digest": observed_snapshot.snapshot_digest,
        "scan_start_offset": scan_start_offset,
        "scan_end_offset": end_offset,
        "capture_boundary": "CURRENT_STABLE_EOF",
        "stable_eof": True,
        "observed_at": observed_at or _safe_iso_now(),
        "runtime_manifest_digest": runtime_manifest_digest(),
    }
    if control_suffix_start_offset is not None:
        base["control_suffix_start_offset"] = control_suffix_start_offset

    def create_window() -> dict[str, Any]:
        matching: list[dict[str, Any]] = []
        window_ambiguous = ambiguous_create
        for call_id, record in calls.items():
            if record["tool_name"] != "create_goal":
                continue
            if (
                expected_objective_digest is not None
                and record["objective_digest"] != expected_objective_digest
            ) or (
                expected_objective_bytes_digest is not None
                and record["objective_bytes_digest"]
                != expected_objective_bytes_digest
            ):
                # An exact create_goal wrapper with the wrong objective is
                # still a create attempt. It must never collapse to NONE.
                window_ambiguous = True
                continue
            output = outputs.get(call_id)
            result = _tool_output_object(output) if output is not None else None
            status = "STARTED_UNKNOWN"
            created_goal = None
            if isinstance(result, dict) and "goal" in result:
                created_goal = _sanitized_goal(result.get("goal"))
                status = "COMPLETED"
            matching.append(
                {
                    "turn_id": record["turn_id"],
                    "call_id_digest": _sha256_bytes(call_id.encode("utf-8")),
                    "status": status,
                    "objective_digest": record["objective_digest"],
                    "objective_bytes_digest": record[
                        "objective_bytes_digest"
                    ],
                    "created_goal": created_goal,
                }
            )
            if (
                not isinstance(record["turn_id"], str)
                or tool_call_counts.get(record["turn_id"]) != 1
            ):
                window_ambiguous = True
        if window_ambiguous:
            invocation_state = "AMBIGUOUS"
        elif any(item["status"] != "COMPLETED" for item in matching):
            invocation_state = "STARTED_UNKNOWN"
        elif matching:
            invocation_state = "COMPLETED"
        else:
            invocation_state = "NONE"
        return {
            "expected_objective_digest": expected_objective_digest,
            "expected_objective_bytes_digest": expected_objective_bytes_digest,
            "matching_invocation_count": len(matching),
            "invocation_state": invocation_state,
            "invocations": matching,
        }

    if mode == "GET_GOAL":
        candidates = [
            (call_id, record)
            for call_id, record in calls.items()
            if record["tool_name"] == "get_goal"
            and call_id in outputs
            and isinstance(record["turn_id"], str)
            and record["turn_id"] in turn_end_offsets
            and tool_call_counts.get(record["turn_id"]) == 1
        ]
        if not candidates:
            raise NativeGoalObservationError(
                "NATIVE_GOAL_GET_GOAL_OBSERVATION_UNAVAILABLE"
            )
        call_id, record = candidates[-1]
        result = _tool_output_object(outputs[call_id])
        if not isinstance(result, dict) or "goal" not in result:
            raise NativeGoalObservationError(
                "NATIVE_GOAL_TOOL_RESULT_INVALID"
            )
        result_receipt = {
            **base,
            "observation_kind": "NATIVE_GOAL_GET_GOAL_V1",
            "turn_id": record["turn_id"],
            "turn_start_offset": turn_start_offsets.get(record["turn_id"]),
            "turn_end_offset": turn_end_offsets.get(record["turn_id"]),
            "tool_name": "get_goal",
            "call_id_digest": _sha256_bytes(call_id.encode("utf-8")),
            "goal": _sanitized_goal(result.get("goal")),
            "control_actions": control_actions,
        }
        if (
            expected_objective_digest is not None
            and expected_objective_bytes_digest is not None
        ):
            # Goal readback and the full create window are derived from the
            # same stable bytes. The runtime must not reopen the rollout
            # between identity readback and exactly-once classification.
            result_receipt["expected_objective_digest"] = (
                expected_objective_digest
            )
            result_receipt["expected_objective_bytes_digest"] = (
                expected_objective_bytes_digest
            )
            result_receipt["create_window"] = create_window()
        return result_receipt

    return {
        **base,
        "observation_kind": "NATIVE_GOAL_CREATE_ROLLOUT_V1",
        "tool_name": "create_goal",
        **create_window(),
    }


def write_observation(
    *,
    root: Path,
    relative_path: str,
    observation: dict[str, Any],
) -> tuple[Path, str]:
    if not re.fullmatch(
        r"\.codex-loop/reports/[A-Za-z0-9._-]+\.json", relative_path
    ):
        raise NativeGoalObservationError(
            "NATIVE_GOAL_OBSERVATION_PATH_INVALID"
        )
    root = root.resolve()
    target = root / relative_path
    reports = root / ".codex-loop" / "reports"
    reports.mkdir(mode=0o700, parents=True, exist_ok=True)
    if reports.is_symlink() or target.is_symlink():
        raise NativeGoalObservationError(
            "NATIVE_GOAL_OBSERVATION_PATH_INVALID"
        )
    if target.parent.resolve() != reports.resolve():
        raise NativeGoalObservationError(
            "NATIVE_GOAL_OBSERVATION_PATH_INVALID"
        )
    payload = _canonical_bytes(observation) + b"\n"
    temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
        os.chmod(target, 0o600)
    finally:
        if temp.exists():
            temp.unlink()
    return target, _sha256_bytes(payload)
