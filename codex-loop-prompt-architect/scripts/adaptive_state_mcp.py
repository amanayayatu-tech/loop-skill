#!/usr/bin/env python3
"""Trusted Codex MCP bridge for Adaptive route-lease mutations.

The model controls ``arguments`` but cannot populate the top-level MCP request
``_meta`` that Codex app-server attaches after tool selection.  This process
also verifies that its direct parent is the OpenAI-signed Codex app-server
binary.  Ordinary CLI execution therefore remains fail-closed.
"""

from __future__ import annotations

import copy
import ctypes
import hashlib
import json
import os
import re
import select
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from adaptive_state_runtime import execute_runtime_codec

from loop_architect.state_runtime import (
    OPENAI_CODE_SIGN_IDENTIFIER,
    OPENAI_CODE_SIGN_TEAM_ID,
    TRUSTED_HOST_BOUNDARY,
    TRUSTED_TURN_SOURCE,
    AdaptiveStateRuntime,
    RuntimeRejection,
    TrustedHostAttestation,
    TrustedTurnMetadata,
)


MCP_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2024-11-05")
MCP_SERVER_NAME = "codex-loop-state"
MCP_SERVER_VERSION = "1.4.0"
MCP_TOOL_NAME = "route_state_mutation"
MCP_RUNTIME_CODEC_TOOL_NAME = "runtime_codec"
MCP_STATE_GATEWAY_TOOL_NAME = "state_gateway"
MCP_TURN_META_KEY = "x-codex-turn-metadata"
MCP_THREAD_META_KEY = "threadId"
# This reserved top-level metadata field is intentionally not an MCP tool
# argument.  A future Codex App/app-server integration may provide it as a
# stronger, completed-subtool attestation.  Current hosts are cooperative, not
# Byzantine: they bind real App return values and readback to the host-attested
# Controller turn, but do not claim a provider-signed result that the App does
# not expose.
MCP_APP_ACTION_RECEIPT_META_KEY = "x-codex-app-action-receipt-v1"
MCP_INPUT_MAX_BYTES = 4_000_000
MCP_PARTIAL_FRAME_TIMEOUT_SECONDS = 30.0
MCP_READ_CHUNK_BYTES = 64 * 1024
MCP_STATE_GATEWAY_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
NATIVE_GOAL_GENERATION_RECOVERY_SCOPES = {
    "NATIVE_GOAL_GENERATION_PREPARE",
    "NATIVE_GOAL_GENERATION_COMMIT",
    "NATIVE_GOAL_GENERATION_ROLLBACK",
}
NATIVE_GOAL_GENERATION_RECOVERY_MUTATIONS = {
    "PREPARE_NATIVE_GOAL_GENERATION_MIGRATION",
    "COMMIT_NATIVE_GOAL_GENERATION_MIGRATION",
    "ROLLBACK_NATIVE_GOAL_GENERATION_MIGRATION",
}
CDHASH_RE = re.compile(r"^CDHash=([a-f0-9]{40,64})$", re.MULTILINE)
IDENTIFIER_RE = re.compile(r"Identifier=([^\n]+)", re.MULTILINE)
TEAM_ID_RE = re.compile(r"TeamIdentifier=([^\n]+)", re.MULTILINE)


class McpBridgeError(ValueError):
    """Structured fail-closed bridge error."""

    def __init__(
        self,
        code: str,
        path: str = "/",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.path = path
        self.details = details or {}


def _runtime_error(
    code: str,
    path: str = "/",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "status": code,
        "error": {"code": code, "path": path, "details": details or {}},
        "state_version": 0,
        "evidence_paths": [],
        "external_actions": [],
        "external_action_count": 0,
    }


def _strict_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _strict_json_loads(payload: str) -> Any:
    return json.loads(
        payload,
        object_pairs_hook=_strict_object_pairs,
        parse_constant=_reject_json_constant,
    )


class McpFrameReader:
    """Read bounded newline-delimited MCP frames.

    An idle MCP server waits indefinitely before the first byte.  Once a frame
    starts, it must terminate within the bounded partial-frame deadline.
    """

    def __init__(
        self,
        stream: BinaryIO,
        *,
        max_bytes: int = MCP_INPUT_MAX_BYTES,
        partial_timeout_seconds: float = MCP_PARTIAL_FRAME_TIMEOUT_SECONDS,
    ) -> None:
        self.stream = stream
        self.max_bytes = max_bytes
        self.partial_timeout_seconds = partial_timeout_seconds
        self.buffer = bytearray()

    def _buffered_frame(self) -> bytes | None:
        newline = self.buffer.find(b"\n")
        if newline < 0:
            return None
        frame = bytes(self.buffer[:newline])
        del self.buffer[: newline + 1]
        return frame

    def read(self) -> dict[str, Any] | None:
        frame = self._buffered_frame()
        if frame is None:
            frame = self._read_frame_bytes()
        if frame is None:
            return None
        if not frame:
            raise McpBridgeError("MCP_INPUT_JSON_INVALID", "/stdin")
        try:
            payload = frame.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise McpBridgeError(
                "MCP_INPUT_UTF8_INVALID",
                "/stdin",
                {"bytes_received": len(frame)},
            ) from exc
        try:
            value = _strict_json_loads(payload)
        except (json.JSONDecodeError, ValueError) as exc:
            raise McpBridgeError(
                "MCP_INPUT_JSON_INVALID",
                "/stdin",
                {"error_type": type(exc).__name__},
            ) from exc
        if not isinstance(value, dict):
            raise McpBridgeError("MCP_INPUT_JSON_INVALID", "/stdin")
        return value

    def _read_frame_bytes(self) -> bytes | None:
        try:
            fd = self.stream.fileno()
        except (AttributeError, OSError):
            frame = self.stream.readline(self.max_bytes + 2)
            if not frame:
                return None
            if len(frame) > self.max_bytes + 1 or (
                len(frame) > self.max_bytes and not frame.endswith(b"\n")
            ):
                raise McpBridgeError(
                    "MCP_INPUT_TOO_LARGE",
                    "/stdin",
                    {"bytes_received": len(frame)},
                )
            return frame[:-1] if frame.endswith(b"\n") else frame

        started_at: float | None = None
        while True:
            frame = self._buffered_frame()
            if frame is not None:
                if len(frame) > self.max_bytes:
                    raise McpBridgeError(
                        "MCP_INPUT_TOO_LARGE",
                        "/stdin",
                        {"bytes_received": len(frame)},
                    )
                return frame
            if len(self.buffer) > self.max_bytes:
                raise McpBridgeError(
                    "MCP_INPUT_TOO_LARGE",
                    "/stdin",
                    {"bytes_received": len(self.buffer)},
                )
            timeout = None
            if self.buffer:
                if started_at is None:
                    started_at = time.monotonic()
                timeout = self.partial_timeout_seconds - (
                    time.monotonic() - started_at
                )
                if timeout <= 0:
                    raise McpBridgeError(
                        "MCP_INPUT_TIMEOUT",
                        "/stdin",
                        {"bytes_received": len(self.buffer)},
                    )
            readable, _, _ = select.select([fd], [], [], timeout)
            if not readable:
                raise McpBridgeError(
                    "MCP_INPUT_TIMEOUT",
                    "/stdin",
                    {"bytes_received": len(self.buffer)},
                )
            chunk = os.read(fd, MCP_READ_CHUNK_BYTES)
            if not chunk:
                if not self.buffer:
                    return None
                frame = bytes(self.buffer)
                self.buffer.clear()
                return frame
            self.buffer.extend(chunk)


def _macos_process_path(pid: int) -> str:
    try:
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    except OSError as exc:
        raise McpBridgeError("APP_PARENT_ATTESTATION_UNAVAILABLE") from exc
    buffer = ctypes.create_string_buffer(4096)
    proc_pidpath = libproc.proc_pidpath
    proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    proc_pidpath.restype = ctypes.c_int
    result = proc_pidpath(pid, buffer, ctypes.sizeof(buffer))
    if result <= 0:
        raise McpBridgeError(
            "APP_PARENT_ATTESTATION_UNAVAILABLE",
            "/parent_pid",
            {"parent_pid": pid},
        )
    return os.fsdecode(buffer.value)


def attest_codex_mcp_parent() -> TrustedHostAttestation:
    """Attest the direct OpenAI-signed Codex app-server parent on macOS."""

    if sys.platform != "darwin":
        raise McpBridgeError(
            "APP_PARENT_ATTESTATION_UNSUPPORTED",
            "/platform",
            {"platform": sys.platform},
        )
    parent_pid = os.getppid()
    if parent_pid <= 1:
        raise McpBridgeError("APP_PARENT_ATTESTATION_INVALID", "/parent_pid")
    executable = _macos_process_path(parent_pid)
    command = subprocess.run(
        ["/bin/ps", "-ww", "-p", str(parent_pid), "-o", "command="],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    if command.returncode != 0 or "app-server" not in command.stdout.split():
        raise McpBridgeError(
            "APP_PARENT_ATTESTATION_INVALID",
            "/parent_command",
        )
    verified = subprocess.run(
        ["/usr/bin/codesign", "--verify", "--strict", executable],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if verified.returncode != 0:
        raise McpBridgeError(
            "APP_PARENT_CODE_SIGNATURE_INVALID",
            "/parent_executable",
        )
    details = subprocess.run(
        ["/usr/bin/codesign", "-dv", "--verbose=4", executable],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    output = details.stdout + details.stderr
    identifier_match = IDENTIFIER_RE.search(output)
    team_match = TEAM_ID_RE.search(output)
    cdhash_match = CDHASH_RE.search(output)
    identifier = identifier_match.group(1).strip() if identifier_match else ""
    team_id = team_match.group(1).strip() if team_match else ""
    cdhash = cdhash_match.group(1) if cdhash_match else ""
    if (
        details.returncode != 0
        or identifier != OPENAI_CODE_SIGN_IDENTIFIER
        or team_id != OPENAI_CODE_SIGN_TEAM_ID
        or not cdhash
    ):
        raise McpBridgeError(
            "APP_PARENT_CODE_SIGNATURE_INVALID",
            "/parent_executable",
        )
    # State runtime uses a single digest grammar. Expand the signed CDHash to a
    # deterministic SHA-256-sized identity without claiming it is a file hash.
    normalized_cdhash = hashlib.sha256(
        f"codesign-cdhash:{cdhash}".encode("ascii")
    ).hexdigest()
    return TrustedHostAttestation(
        boundary=TRUSTED_HOST_BOUNDARY,
        parent_pid=parent_pid,
        parent_executable=executable,
        parent_identifier=identifier,
        parent_team_id=team_id,
        parent_cdhash=normalized_cdhash,
    )


def _extract_turn_metadata(
    params: dict[str, Any],
    host_attestation: TrustedHostAttestation,
) -> TrustedTurnMetadata:
    meta = params.get("_meta")
    if not isinstance(meta, dict):
        raise McpBridgeError(
            "BLOCKED_BY_APP_ATTESTATION",
            "/params/_meta",
        )
    raw_turn_meta = meta.get(MCP_TURN_META_KEY)
    if isinstance(raw_turn_meta, str):
        try:
            raw_turn_meta = _strict_json_loads(raw_turn_meta)
        except (json.JSONDecodeError, ValueError) as exc:
            raise McpBridgeError(
                "APP_TURN_ATTESTATION_INVALID",
                f"/params/_meta/{MCP_TURN_META_KEY}",
            ) from exc
    if not isinstance(raw_turn_meta, dict):
        raise McpBridgeError(
            "BLOCKED_BY_APP_ATTESTATION",
            f"/params/_meta/{MCP_TURN_META_KEY}",
        )
    thread_id = raw_turn_meta.get("thread_id")
    session_id = raw_turn_meta.get("session_id")
    turn_id = raw_turn_meta.get("turn_id")
    outer_thread_id = meta.get(MCP_THREAD_META_KEY)
    if (
        not isinstance(thread_id, str)
        or not isinstance(session_id, str)
        or not isinstance(turn_id, str)
        or not isinstance(outer_thread_id, str)
        or not thread_id
        or not session_id
        or not turn_id
        or not outer_thread_id
        or thread_id != outer_thread_id
    ):
        raise McpBridgeError(
            "APP_TURN_ATTESTATION_INVALID",
            f"/params/_meta/{MCP_TURN_META_KEY}",
        )
    return TrustedTurnMetadata(
        session_id=session_id,
        thread_id=thread_id,
        turn_id=turn_id,
        source=TRUSTED_TURN_SOURCE,
        host_attestation=host_attestation,
    )


def _extract_app_action_result(
    params: dict[str, Any],
    metadata: TrustedTurnMetadata,
    *,
    action: str,
    result_fields: set[str],
) -> dict[str, Any]:
    """Read an App-owned completed-action receipt, never a tool argument.

    Turn metadata establishes who is calling this MCP tool.  It does not
    establish that a different App subtool completed earlier in the turn.  The
    latter requires a separately App-injected receipt.  Until the desktop
    protocol supplies one, missing metadata is an explicit, zero-side-effect
    capability block rather than an invitation to accept model-provided JSON.
    """

    meta = params.get("_meta")
    if not isinstance(meta, dict):
        raise McpBridgeError("BLOCKED_BY_APP_ATTESTATION", "/params/_meta")
    raw = meta.get(MCP_APP_ACTION_RECEIPT_META_KEY)
    if raw is None:
        raise McpBridgeError(
            "APP_ACTION_RECEIPT_ATTESTATION_UNAVAILABLE",
            f"/params/_meta/{MCP_APP_ACTION_RECEIPT_META_KEY}",
            {"required_action": action, "side_effects": "NONE"},
        )
    if isinstance(raw, str):
        try:
            raw = _strict_json_loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise McpBridgeError(
                "APP_ACTION_RECEIPT_ATTESTATION_INVALID",
                f"/params/_meta/{MCP_APP_ACTION_RECEIPT_META_KEY}",
            ) from exc
    required = {
        "schema_version", "action", "source_thread_id", "source_turn_id", "result",
    }
    if (
        not isinstance(raw, dict)
        or set(raw) != required
        or raw.get("schema_version") != 1
        or raw.get("action") != action
        or raw.get("source_thread_id") != metadata.thread_id
        or raw.get("source_turn_id") != metadata.turn_id
        or not isinstance(raw.get("result"), dict)
        or set(raw["result"]) != result_fields
    ):
        raise McpBridgeError(
            "APP_ACTION_RECEIPT_ATTESTATION_INVALID",
            f"/params/_meta/{MCP_APP_ACTION_RECEIPT_META_KEY}",
        )
    return copy.deepcopy(raw["result"])


def _optional_app_action_result(
    params: dict[str, Any],
    metadata: TrustedTurnMetadata,
    *,
    action: str,
    result_fields: set[str],
) -> dict[str, Any] | None:
    """Return a future App attestation when present, otherwise use host evidence.

    The absent-carrier branch is deliberately *not* an error.  Schema-v3
    protects against operational faults (crashes, duplication, stale or
    mismatched evidence) on today's cooperative Codex host; it does not claim
    Byzantine resistance against a Controller that can forge every App call.
    When a future App injects the reserved result carrier, retain its stricter
    validation rather than widening the accepted result shape.
    """

    meta = params.get("_meta")
    if not isinstance(meta, dict) or MCP_APP_ACTION_RECEIPT_META_KEY not in meta:
        return None
    return _extract_app_action_result(
        params,
        metadata,
        action=action,
        result_fields=result_fields,
    )


@dataclass
class AdaptiveStateMcpServer:
    host_attestation: TrustedHostAttestation | None
    host_error: McpBridgeError | None = None
    initialized: bool = False

    @classmethod
    def from_current_process(cls) -> "AdaptiveStateMcpServer":
        try:
            attestation = attest_codex_mcp_parent()
        except McpBridgeError as exc:
            return cls(host_attestation=None, host_error=exc)
        return cls(host_attestation=attestation)

    def _tool_result(self, response: dict[str, Any]) -> dict[str, Any]:
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        response,
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            ],
            "structuredContent": response,
            "isError": not response.get("ok", False),
        }

    @staticmethod
    def _transport_recovery_fail_safe(
        response: dict[str, Any], operation: Any, post_state: Any = None
    ) -> dict[str, Any]:
        """Expose the external rollback required after a rejected resume ACK."""

        if operation == "ACK_TRANSPORT_RECOVERY" and not response.get("ok", False):
            response = copy.deepcopy(response)
            waiting = (
                isinstance(post_state, dict)
                and post_state.get("transport_recovery", {}).get("status")
                == "WAITING_TRANSPORT_RECOVERY"
                and post_state.get("run_control", {}).get("status")
                == "PAUSED_AT_SAFE_POINT"
            )
            recovered = (
                isinstance(post_state, dict)
                and post_state.get("transport_recovery", {}).get("status") == "HEALTHY"
                and post_state.get("run_control", {}).get("status") == "RUNNING"
            )
            response["next_action_code"] = (
                "PAUSE_SAME_HEARTBEAT_AND_READBACK"
                if waiting
                else "READ_STATE_ALREADY_RECOVERED"
                if recovered
                else "READ_STATE_AND_RECONCILE_HEARTBEAT"
            )
            response["routing_permitted"] = False
        return response

    def _call_route_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        if self.host_attestation is None:
            error = self.host_error or McpBridgeError(
                "BLOCKED_BY_APP_ATTESTATION"
            )
            return self._tool_result(
                _runtime_error(error.code, error.path, error.details)
            )
        try:
            metadata = _extract_turn_metadata(params, self.host_attestation)
            arguments = params.get("arguments")
            if not isinstance(arguments, dict):
                raise McpBridgeError("MCP_ARGUMENTS_INVALID", "/params/arguments")
            root = arguments.get("root")
            request = arguments.get("request")
            if not isinstance(root, str) or not Path(root).is_absolute():
                raise McpBridgeError("MCP_ROOT_INVALID", "/params/arguments/root")
            if not isinstance(request, dict):
                raise McpBridgeError(
                    "MCP_ARGUMENTS_INVALID",
                    "/params/arguments/request",
                )
            request = copy.deepcopy(request)
            mutation = request.get("mutation")
            if isinstance(mutation, dict) and (
                mutation.get("type")
                in NATIVE_GOAL_GENERATION_RECOVERY_MUTATIONS
                or mutation.get("recovery_scope")
                in NATIVE_GOAL_GENERATION_RECOVERY_SCOPES
            ):
                raise McpBridgeError(
                    "NATIVE_GOAL_GENERATION_RECOVERY_UNAVAILABLE",
                    "/native_goal_generation_recovery",
                    {
                        "availability": "DEFERRED_UNAVAILABLE",
                        "side_effects": "NONE",
                    },
                )
            if not isinstance(mutation, dict) or mutation.get("type") not in {
                "ACQUIRE_LEASE",
                "TAKEOVER_LEASE",
            }:
                raise McpBridgeError(
                    "MCP_ROUTE_MUTATION_TYPE_INVALID",
                    "/params/arguments/request/mutation/type",
                )
            claimed_turn_id = mutation.get("controller_turn_id")
            if claimed_turn_id is None:
                mutation["controller_turn_id"] = metadata.turn_id
            elif claimed_turn_id != metadata.turn_id:
                raise McpBridgeError(
                    "CONTROLLER_TURN_ATTESTATION_MISMATCH",
                    "/params/arguments/request/mutation/controller_turn_id",
                    {
                        "claimed_turn_id": claimed_turn_id,
                        "attested_turn_id": metadata.turn_id,
                    },
                )
            response = AdaptiveStateRuntime(root).apply(
                request,
                trusted_turn_metadata=metadata,
            )
        except McpBridgeError as exc:
            response = _runtime_error(exc.code, exc.path, exc.details)
        return self._tool_result(response)

    def _call_runtime_codec(self, params: dict[str, Any]) -> dict[str, Any]:
        if self.host_attestation is None:
            error = self.host_error or McpBridgeError(
                "BLOCKED_BY_APP_ATTESTATION"
            )
            return self._tool_result(
                _runtime_error(error.code, error.path, error.details)
            )
        try:
            metadata = _extract_turn_metadata(params, self.host_attestation)
            arguments = params.get("arguments")
            if not isinstance(arguments, dict):
                raise McpBridgeError("MCP_ARGUMENTS_INVALID", "/params/arguments")
            operation = arguments.get("operation")
            allowed_keys = {
                "MATERIALIZE_DISPATCH": {"operation", "request"},
                "VERIFY_DISPATCH": {"operation", "root", "transport_text"},
                "STAGE_REPORT": {"operation", "root", "request"},
                "STAGE_EXTERNAL_RECEIPT": {"operation", "root", "request"},
                "NORMALIZE_FINGERPRINT": {"operation", "request"},
                "CAPTURE_COMPLETE_DIFF": {"operation", "root", "request"},
            }
            if operation not in allowed_keys or set(arguments) != allowed_keys[operation]:
                raise McpBridgeError(
                    "RUNTIME_CODEC_ARGUMENTS_INVALID", "/params/arguments"
                )
            root = arguments.get("root")
            if root is not None and (
                not isinstance(root, str) or not Path(root).is_absolute()
            ):
                raise McpBridgeError(
                    "MCP_ROOT_INVALID", "/params/arguments/root"
                )
            request = arguments.get("request")
            if request is not None and not isinstance(request, dict):
                raise McpBridgeError(
                    "RUNTIME_CODEC_ARGUMENTS_INVALID", "/params/arguments/request"
                )
            transport_text = arguments.get("transport_text")
            if transport_text is not None and not isinstance(transport_text, str):
                raise McpBridgeError(
                    "RUNTIME_CODEC_ARGUMENTS_INVALID",
                    "/params/arguments/transport_text",
                )
            # Authorization that protects a persistent codec operation must
            # happen before the codec runs.  Binding a caller after staging a
            # report or receipt would still leave attacker-controlled bytes in
            # the control plane when the later check rejects the request.
            if root is not None:
                self._authorize_codec_caller(
                    operation,
                    root,
                    request=request,
                    metadata=metadata,
                )
            response = execute_runtime_codec(
                operation,
                root=root,
                request=request,
                transport_text=transport_text,
            )
            if response.get("ok") and root is not None:
                self._bind_codec_caller(
                    operation,
                    root,
                    request=request,
                    transport_text=transport_text,
                    response=response,
                    metadata=metadata,
                )
        except McpBridgeError as exc:
            response = _runtime_error(exc.code, exc.path, exc.details)
        return self._tool_result(response)

    @staticmethod
    def _codec_outbox_record(
        state: dict[str, Any], outbox_id: str
    ) -> tuple[str, dict[str, Any]]:
        matches = [
            (kind, state[field][outbox_id])
            for kind, field in (
                ("DISPATCH", "dispatch_outbox"),
                ("ASSURANCE", "assurance_dispatch_outbox"),
                ("LOCAL", "local_verification_outbox"),
            )
            if outbox_id in state.get(field, {})
        ]
        if len(matches) != 1:
            raise McpBridgeError("CODEC_OUTBOX_NOT_FOUND", "/request/outbox_id")
        return matches[0]

    def _bind_codec_caller(
        self,
        operation: str,
        root: str,
        *,
        request: dict[str, Any] | None,
        transport_text: str | None,
        response: dict[str, Any],
        metadata: TrustedTurnMetadata,
    ) -> None:
        """Bind role-authored codec operations to an App-attested task.

        The Controller may route and ACK, but cannot stage a Worker/Reviewer
        report itself.  The target's validated identity is persisted as an
        immutable runtime sidecar after report staging, so the Controller's
        separate MCP bridge can recover the original outbox without product
        redispatch.
        """

        state = AdaptiveStateRuntime(root).read_state()
        if state is None or state.get("schema_version") != 3:
            return
        registry = state.get("thread_registry", {})
        caller = registry.get(metadata.thread_id)
        if not isinstance(caller, dict) or caller.get("status") != "REGISTERED":
            raise McpBridgeError("CODEC_CALLER_THREAD_UNREGISTERED", "/params/_meta")
        if operation == "VERIFY_DISPATCH":
            target_id = response.get("target_thread_id")
            expected_role = response.get("target_role")
            if (
                target_id != metadata.thread_id
                or caller.get("role_kind") != expected_role
            ):
                raise McpBridgeError("CODEC_DISPATCH_TARGET_ATTESTATION_MISMATCH", "/params/_meta")
            return
        if operation == "STAGE_REPORT":
            if not isinstance(request, dict) or not isinstance(request.get("outbox_id"), str):
                raise McpBridgeError("CODEC_REPORT_REQUEST_INVALID", "/request/outbox_id")
            kind, record = self._codec_outbox_record(state, request["outbox_id"])
            expected_role = {
                "DISPATCH": "WORKER", "ASSURANCE": "REVIEWER", "LOCAL": "LOCAL_VERIFIER",
            }[kind]
            if (
                record.get("status") != "SENT"
                or record.get("target_id") != metadata.thread_id
                or caller.get("role_kind") != expected_role
            ):
                raise McpBridgeError("CODEC_REPORT_TARGET_ATTESTATION_MISMATCH", "/params/_meta")
            report_digest = response.get("report_digest")
            if not isinstance(report_digest, str):
                raise McpBridgeError("CODEC_REPORT_STAGE_INVALID", "/result/report_digest")
            attestation = {
                "thread_id": metadata.thread_id,
                "turn_id": metadata.turn_id,
                "role_kind": expected_role,
                "outbox_id": request["outbox_id"],
                "report_digest": report_digest,
            }
            try:
                persisted = AdaptiveStateRuntime(root).stage_codec_report_attestation(
                    attestation
                )
            except RuntimeRejection as exc:
                # Staging has already completed, but its target-bound durable
                # proof has not.  Return a structured failure so the same role
                # can safely re-stage the exact report; never leak a bridge
                # exception or let the Controller ACK without this proof.
                raise McpBridgeError(exc.code, exc.path, exc.details) from exc
            response["codec_report_attestation"] = copy.deepcopy(
                persisted["attestation"]
            )
            response["codec_report_attestation_source_path"] = persisted[
                "source_path"
            ]
            response["codec_report_attestation_digest"] = persisted[
                "attestation_digest"
            ]
            return
        if operation == "STAGE_EXTERNAL_RECEIPT":
            if (
                not isinstance(request, dict)
                or request.get("target_thread_id") != metadata.thread_id
                or caller.get("role_kind") != "LOCAL_VERIFIER"
            ):
                raise McpBridgeError("CODEC_EXTERNAL_RECEIPT_TARGET_ATTESTATION_MISMATCH", "/params/_meta")
            return
        if operation == "CAPTURE_COMPLETE_DIFF" and caller.get("role_kind") not in {"CONTROLLER", "WORKER"}:
            raise McpBridgeError("CODEC_DIFF_CALLER_ROLE_INVALID", "/params/_meta")

    def _authorize_codec_caller(
        self,
        operation: str,
        root: str,
        *,
        request: dict[str, Any] | None,
        metadata: TrustedTurnMetadata,
    ) -> None:
        """Reject an unauthorized persistent codec call before it can write.

        ``VERIFY_DISPATCH`` is read-only and needs its decoded payload to
        learn the route target, so its target check stays in the post-execute
        binder.  Every operation that can create a spool file, report stage or
        diff capture is authorized here first.
        """

        if operation not in {
            "STAGE_REPORT", "STAGE_EXTERNAL_RECEIPT", "CAPTURE_COMPLETE_DIFF"
        }:
            return
        state = AdaptiveStateRuntime(root).read_state()
        if state is None or state.get("schema_version") != 3:
            return
        registry = state.get("thread_registry", {})
        caller = registry.get(metadata.thread_id)
        if not isinstance(caller, dict) or caller.get("status") != "REGISTERED":
            raise McpBridgeError("CODEC_CALLER_THREAD_UNREGISTERED", "/params/_meta")
        if operation == "STAGE_REPORT":
            if not isinstance(request, dict) or not isinstance(request.get("outbox_id"), str):
                raise McpBridgeError("CODEC_REPORT_REQUEST_INVALID", "/request/outbox_id")
            kind, record = self._codec_outbox_record(state, request["outbox_id"])
            expected_role = {
                "DISPATCH": "WORKER", "ASSURANCE": "REVIEWER", "LOCAL": "LOCAL_VERIFIER",
            }[kind]
            if (
                record.get("status") != "SENT"
                or record.get("target_id") != metadata.thread_id
                or caller.get("role_kind") != expected_role
            ):
                raise McpBridgeError("CODEC_REPORT_TARGET_ATTESTATION_MISMATCH", "/params/_meta")
            return
        if operation == "STAGE_EXTERNAL_RECEIPT":
            if (
                not isinstance(request, dict)
                or request.get("target_thread_id") != metadata.thread_id
                or caller.get("role_kind") != "LOCAL_VERIFIER"
            ):
                raise McpBridgeError("CODEC_EXTERNAL_RECEIPT_TARGET_ATTESTATION_MISMATCH", "/params/_meta")
            return
        if caller.get("role_kind") not in {"CONTROLLER", "WORKER"}:
            raise McpBridgeError("CODEC_DIFF_CALLER_ROLE_INVALID", "/params/_meta")

    @staticmethod
    def _gateway_error(code: str, path: str = "/") -> None:
        raise McpBridgeError(code, path)

    @staticmethod
    def _gateway_heartbeat_locator(*components: str) -> str:
        """Return a bounded deterministic locator for canonical heartbeat data."""

        return hashlib.sha256("\x00".join(components).encode("utf-8")).hexdigest()

    @staticmethod
    def _gateway_request_locator(request_id: str) -> str:
        """Map a public request ID to portable canonical journal identifiers."""

        return hashlib.sha256(request_id.encode("utf-8")).hexdigest()

    @staticmethod
    def _gateway_public_request_digest(public: dict[str, Any]) -> str:
        """Bind a public request independently of its optimistic state version."""

        content = json.dumps(
            public, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()

    @classmethod
    def _gateway_heartbeat_evidence_path(
        cls, observation: dict[str, Any], digest: str
    ) -> str:
        """Return a bounded, deterministic report name for a heartbeat observation.

        Automation identifiers are valid state identifiers up to 128 bytes, so
        they cannot be interpolated together with a full SHA-256 digest into a
        report basename.  The report content still carries the full identity
        and its content digest remains the canonical binding; this filename is
        only a bounded deterministic locator.
        """

        locator = cls._gateway_heartbeat_locator(
            str(observation["automation_id"]), digest
        )
        return f".codex-loop/reports/gateway-heartbeat-{locator}.json"

    def _gateway_automation_artifacts(
        self,
        state: dict[str, Any],
        automation_receipt: Any,
        metadata: TrustedTurnMetadata,
        *,
        stem: str,
        required_status: str,
        parameter_name: str,
        evidence_model: str = "HOST_COOPERATIVE",
    ) -> tuple[dict[str, Any], list[dict[str, str]], dict[str, str]]:
        required = {
            "automation_id", "status", "automation_name", "kind",
            "target_thread_id", "rrule", "prompt_digest",
            "prompt_normalization", "observed_at", "source_turn_id",
        }
        parameter_path = f"/params/arguments/request/parameters/{parameter_name}"
        if not isinstance(automation_receipt, dict) or set(automation_receipt) != required:
            self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", parameter_path)
        if automation_receipt.get("source_turn_id") != metadata.turn_id:
            self._gateway_error("APP_AUTOMATION_RECEIPT_TURN_MISMATCH", f"{parameter_path}/source_turn_id")
        identity = state.get("heartbeat_prompt_identity")
        if not isinstance(identity, dict):
            self._gateway_error("STATE_GATEWAY_HEARTBEAT_UNREGISTERED", "/params/arguments/request")
        heartbeat_observation = {
            **copy.deepcopy(identity),
            "automation_id": automation_receipt["automation_id"],
            "status": automation_receipt["status"],
            "observed_at": automation_receipt["observed_at"],
        }
        if (
            automation_receipt.get("status") != required_status
            or any(
                automation_receipt.get(key) != heartbeat_observation.get(key)
                for key in (
                    "automation_id", "automation_name", "kind", "target_thread_id",
                    "rrule", "prompt_digest", "prompt_normalization", "observed_at",
                )
            )
        ):
            self._gateway_error("APP_AUTOMATION_RECEIPT_IDENTITY_MISMATCH", parameter_path)
        heartbeat_content = json.dumps(heartbeat_observation, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        heartbeat_digest = "sha256:" + hashlib.sha256(heartbeat_content.encode("utf-8")).hexdigest()
        heartbeat_path = f".codex-loop/reports/{stem}-heartbeat-{heartbeat_digest.removeprefix('sha256:')}.json"
        app_receipt = {
            "observation_kind": "HOST_COOPERATIVE_AUTOMATION_UPDATE_OBSERVATION",
            "evidence_model": evidence_model,
            "controller_thread_id": metadata.thread_id,
            "controller_turn_id": metadata.turn_id,
            "automation": copy.deepcopy(automation_receipt),
        }
        app_content = json.dumps(app_receipt, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        app_digest = "sha256:" + hashlib.sha256(app_content.encode("utf-8")).hexdigest()
        app_path = f".codex-loop/reports/{stem}-app-automation-{app_digest.removeprefix('sha256:')}.json"
        return heartbeat_observation, [
            {"path": heartbeat_path, "content": heartbeat_content, "digest": heartbeat_digest, "media_type": "application/json"},
            {"path": app_path, "content": app_content, "digest": app_digest, "media_type": "application/json"},
        ], {
            "automation_observation_path": heartbeat_path,
            "automation_observation_digest": heartbeat_digest,
            "app_automation_receipt_path": app_path,
            "app_automation_receipt_digest": app_digest,
        }

    def _call_state_gateway(self, params: dict[str, Any]) -> dict[str, Any]:
        """Translate a strict public gateway request into one runtime CAS.

        The public shape deliberately excludes leases, freshness objects, and
        outbox identities.  Those values are created from canonical state in
        the runtime, so Controller cannot copy a stale matrix or handoff.
        """

        arguments_hint = params.get("arguments")
        public_hint = (
            arguments_hint.get("request")
            if isinstance(arguments_hint, dict)
            else None
        )
        operation_hint = (
            public_hint.get("operation") if isinstance(public_hint, dict) else None
        )
        if self.host_attestation is None:
            error = self.host_error or McpBridgeError("BLOCKED_BY_APP_ATTESTATION")
            response = _runtime_error(error.code, error.path, error.details)
            return self._tool_result(
                self._transport_recovery_fail_safe(response, operation_hint)
            )
        runtime: AdaptiveStateRuntime | None = None
        state: dict[str, Any] | None = None
        try:
            metadata = _extract_turn_metadata(params, self.host_attestation)
            arguments = params.get("arguments")
            if not isinstance(arguments, dict) or set(arguments) != {"root", "request"}:
                self._gateway_error("STATE_GATEWAY_ARGUMENTS_INVALID", "/params/arguments")
            root = arguments["root"]
            public = arguments["request"]
            if not isinstance(root, str) or not Path(root).is_absolute():
                self._gateway_error("MCP_ROOT_INVALID", "/params/arguments/root")
            if not isinstance(public, dict) or set(public) != {"request_id", "operation", "occurred_at", "parameters"}:
                self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request")
            request_id = public["request_id"]
            operation = public["operation"]
            occurred_at = public["occurred_at"]
            payload = public["parameters"]
            if (
                not isinstance(request_id, str)
                or MCP_STATE_GATEWAY_REQUEST_ID_RE.fullmatch(request_id) is None
            ):
                self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/request_id")
            if not isinstance(occurred_at, str) or not occurred_at:
                self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/occurred_at")
            if not isinstance(payload, dict):
                self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters")
            runtime = AdaptiveStateRuntime(root)
            state = runtime.read_state()
            request_locator = self._gateway_request_locator(request_id)
            state_request_id = f"gateway-request-{request_locator}"
            gateway_public_request_digest = self._gateway_public_request_digest(public)
            existing_gateway_request = (
                state.get("request_ledger", {}).get(state_request_id)
                if state is not None
                else None
            )
            bootstrap_replay = bool(
                isinstance(existing_gateway_request, dict)
                and existing_gateway_request.get("gateway_public_request_digest")
                == gateway_public_request_digest
            )
            if operation == "MIGRATE_V2_TO_V3":
                if set(payload) != {"source_state_digest"}:
                    self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters")
                mutation: dict[str, Any] = {
                    "type": "MIGRATE_V2_TO_V3",
                    "source_state_digest": payload["source_state_digest"],
                }
                artifacts: list[dict[str, Any]] = []
            elif operation == "INITIALIZE":
                if state is not None:
                    if existing_gateway_request is not None and not bootstrap_replay:
                        self._gateway_error("STATE_REQUEST_ID_CONFLICT", "/params/arguments/request/request_id")
                    if not bootstrap_replay:
                        self._gateway_error("STATE_GATEWAY_ROOT_NOT_EMPTY", "/params/arguments/root")
                required = {"initialize_mutation", "controller_pack_source_path"}
                if set(payload) != required or not isinstance(payload["initialize_mutation"], dict):
                    self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters")
                source = payload["controller_pack_source_path"]
                if not isinstance(source, str) or not Path(source).is_absolute():
                    self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters/controller_pack_source_path")
                source_path = Path(source).resolve(strict=False)
                try:
                    source_path.relative_to(Path(root).resolve(strict=False))
                    content = source_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError, ValueError):
                    self._gateway_error("STATE_GATEWAY_PACK_SOURCE_INVALID", "/params/arguments/request/parameters/controller_pack_source_path")
                digest = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
                initialize_mutation = copy.deepcopy(payload["initialize_mutation"])
                if initialize_mutation.get("controller_pack_digest") != digest:
                    self._gateway_error("STATE_GATEWAY_PACK_SOURCE_DIGEST_MISMATCH", "/params/arguments/request/parameters/initialize_mutation/controller_pack_digest")
                artifacts = [{
                    "path": ".codex-loop/sources/CONTROLLER_PACK.md",
                    "source_path": str(source_path), "digest": digest,
                    "media_type": "text/markdown",
                }]
                mutation = {
                    "type": "STATE_GATEWAY",
                    "operation": operation,
                    "gateway_request": {"initialize_mutation": initialize_mutation},
                }
            elif operation == "INITIALIZE_SUCCESSOR":
                if state is not None:
                    if existing_gateway_request is not None and not bootstrap_replay:
                        self._gateway_error("STATE_REQUEST_ID_CONFLICT", "/params/arguments/request/request_id")
                    if not bootstrap_replay:
                        self._gateway_error("STATE_GATEWAY_SUCCESSOR_ROOT_NOT_EMPTY", "/params/arguments/root")
                required = {
                    "predecessor_root", "predecessor_finalization_digest",
                    "predecessor_root_digest", "successor_context",
                    "initialize_mutation", "controller_pack_source_path",
                }
                if set(payload) != required or not isinstance(payload["initialize_mutation"], dict):
                    self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters")
                source = payload["controller_pack_source_path"]
                if not isinstance(source, str) or not Path(source).is_absolute():
                    self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters/controller_pack_source_path")
                source_path = Path(source).resolve(strict=False)
                try:
                    source_path.relative_to(Path(root).resolve(strict=False))
                    content = source_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError, ValueError):
                    self._gateway_error("STATE_GATEWAY_PACK_SOURCE_INVALID", "/params/arguments/request/parameters/controller_pack_source_path")
                digest = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
                initialize_mutation = copy.deepcopy(payload["initialize_mutation"])
                if initialize_mutation.get("controller_pack_digest") != digest:
                    self._gateway_error("STATE_GATEWAY_PACK_SOURCE_DIGEST_MISMATCH", "/params/arguments/request/parameters/initialize_mutation/controller_pack_digest")
                artifacts = [{
                    "path": ".codex-loop/sources/CONTROLLER_PACK.md",
                    "source_path": str(source_path), "digest": digest,
                    "media_type": "text/markdown",
                }]
                gateway_payload = {
                    "predecessor_root": payload["predecessor_root"],
                    "predecessor_finalization_digest": payload["predecessor_finalization_digest"],
                    "predecessor_root_digest": payload["predecessor_root_digest"],
                    "successor_context": copy.deepcopy(payload["successor_context"]),
                    "initialize_mutation": initialize_mutation,
                }
                mutation = {"type": "STATE_GATEWAY", "operation": operation, "gateway_request": gateway_payload}
            else:
                if state is None:
                    self._gateway_error("STATE_NOT_INITIALIZED", "/params/arguments/root")
                if operation == "PREPARE_ROUTE":
                    if set(payload) != {"route_id", "goal_id", "route_kind", "target_thread_id", "observed_at"}:
                        self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters")
                    gateway_payload = copy.deepcopy(payload)
                    artifacts = []
                elif operation == "REGISTER_TASK":
                    result_fields = {
                        "thread_id", "role_kind", "bootstrap_role_kind",
                        "bootstrap_prompt_digest", "worktree_path",
                    }
                    attested = _optional_app_action_result(
                        params,
                        metadata,
                        action="THREAD_CREATE_OR_READ",
                        result_fields=result_fields,
                    )
                    if attested is not None:
                        if payload:
                            self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters")
                        gateway_payload = attested
                    else:
                        if set(payload) != result_fields:
                            self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters")
                        gateway_payload = copy.deepcopy(payload)
                    artifacts = []
                elif operation in {"REGISTER_HEARTBEAT", "RECORD_HEARTBEAT_OBSERVATION"}:
                    required_observation = {
                        "automation_id", "status", "automation_name", "kind",
                        "target_thread_id", "rrule", "prompt_digest",
                        "prompt_normalization", "observed_at",
                    }
                    attested = _optional_app_action_result(
                        params,
                        metadata,
                        action="AUTOMATION_OBSERVATION",
                        result_fields=required_observation,
                    )
                    if attested is not None:
                        if payload:
                            self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters")
                        observation = attested
                    elif operation == "REGISTER_HEARTBEAT":
                        required_direct = {
                            "automation_id", "automation_name", "rrule", "prompt_digest",
                            "status", "observed_at",
                        }
                        if set(payload) != required_direct:
                            self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters")
                        observation = {
                            "automation_id": payload["automation_id"],
                            "status": payload["status"],
                            "automation_name": payload["automation_name"],
                            "kind": "HEARTBEAT",
                            "target_thread_id": metadata.thread_id,
                            "rrule": payload["rrule"],
                            "prompt_digest": payload["prompt_digest"],
                            "prompt_normalization": "LF_NORMALIZED_NO_TRAILING_NEWLINE",
                            "observed_at": payload["observed_at"],
                        }
                    else:
                        required_direct = {"automation_id", "status", "observed_at"}
                        if set(payload) != required_direct:
                            self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters")
                        identity = state.get("heartbeat_prompt_identity")
                        if not isinstance(identity, dict):
                            self._gateway_error("STATE_GATEWAY_HEARTBEAT_UNREGISTERED", "/params/arguments/request")
                        observation = {
                            **copy.deepcopy(identity),
                            "automation_id": payload["automation_id"],
                            "status": payload["status"],
                            "observed_at": payload["observed_at"],
                        }
                    if operation == "REGISTER_HEARTBEAT":
                        controller = state.get("thread_registry", {}).get(metadata.thread_id, {})
                        if controller.get("role_kind") != "CONTROLLER":
                            self._gateway_error("STEERING_ACTOR_INVALID", "/params/arguments/request")
                    content = json.dumps(observation, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                    digest = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
                    evidence_path = self._gateway_heartbeat_evidence_path(
                        observation, digest
                    )
                    artifacts = [{
                        "path": evidence_path, "content": content,
                        "digest": digest, "media_type": "application/json",
                    }]
                    gateway_payload = {
                        "heartbeat_observation": observation,
                        "automation_observation_path": evidence_path,
                        "automation_observation_digest": digest,
                    }
                elif operation == "RECORD_ROUTE_SENT":
                    required_receipt = {
                        "message_id", "target_thread_id", "observed_at", "payload_digest",
                    }
                    attested = _optional_app_action_result(
                        params,
                        metadata,
                        action="SEND_MESSAGE_TO_THREAD",
                        result_fields=required_receipt,
                    )
                    if attested is not None:
                        if set(payload) != {"route_id"}:
                            self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters")
                        route_id = payload["route_id"]
                        returned_thread_id = attested["target_thread_id"]
                        provider_observation_id: str | None = attested["message_id"]
                        observed_at = attested["observed_at"]
                        supplied_payload_digest = attested["payload_digest"]
                    else:
                        required_direct = {"route_id", "returned_thread_id", "observed_at"}
                        legacy_direct = {
                            "route_id", "message_id", "target_thread_id", "observed_at",
                        }
                        if set(payload) != required_direct and set(payload) != legacy_direct:
                            self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters")
                        route_id = payload["route_id"]
                        returned_thread_id = payload.get("returned_thread_id", payload.get("target_thread_id"))
                        provider_observation_id = payload.get("message_id")
                        observed_at = payload["observed_at"]
                        supplied_payload_digest = None
                    route = state.get("gateway_route_ledger", {}).get(route_id, {})
                    outbox_field = {
                        "DISPATCH": "dispatch_outbox",
                        "ASSURANCE": "assurance_dispatch_outbox",
                        "LOCAL": "local_verification_outbox",
                    }.get(route.get("outbox_kind"))
                    outbox = (
                        state.get(outbox_field, {}).get(route_id, {})
                        if outbox_field is not None
                        else {}
                    )
                    if (
                        supplied_payload_digest is not None
                        and supplied_payload_digest != outbox.get("payload_digest")
                    ):
                        self._gateway_error(
                            "APP_SEND_RECEIPT_PAYLOAD_MISMATCH",
                            f"/params/_meta/{MCP_APP_ACTION_RECEIPT_META_KEY}/result/payload_digest",
                        )
                    if returned_thread_id != outbox.get("target_id"):
                        self._gateway_error(
                            "OUTBOX_TARGET_MISMATCH",
                            "/params/arguments/request/parameters/returned_thread_id",
                        )
                    observation = {
                        "observation_kind": "HOST_COOPERATIVE_SEND_OBSERVATION",
                        "outbox_id": route_id,
                        "payload_digest": outbox["payload_digest"],
                        "target_thread_id": outbox["target_id"],
                        "returned_thread_id": returned_thread_id,
                        "provider_observation_id": provider_observation_id,
                        "observed_at": observed_at,
                        "source_thread_id": metadata.thread_id,
                        "source_turn_id": metadata.turn_id,
                    }
                    content = json.dumps(observation, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                    evidence_path = f".codex-loop/reports/{route_id}-send.json"
                    digest = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
                    artifacts = [{"path": evidence_path, "content": content, "digest": digest, "media_type": "application/json"}]
                    gateway_payload = {
                        "route_id": route_id,
                        "send_observation": {
                            "returned_thread_id": returned_thread_id,
                            "provider_observation_id": provider_observation_id,
                            "target_thread_id": outbox["target_id"],
                            "payload_digest": outbox["payload_digest"],
                            "observed_at": observed_at,
                            "source_thread_id": metadata.thread_id,
                            "source_turn_id": metadata.turn_id,
                            "evidence_path": evidence_path,
                            "evidence_digest": digest,
                        },
                    }
                elif operation in {"ACK_ROUTE_RESULT", "REPORT_RECOVERY"}:
                    key = "route_id" if operation == "ACK_ROUTE_RESULT" else "outbox_id"
                    if set(payload) != {key, "staged_report"} or not isinstance(payload["staged_report"], dict):
                        self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters")
                    staged = copy.deepcopy(payload["staged_report"])
                    required_stage = {"path", "source_path", "digest", "media_type", "result"}
                    if frozenset(staged) not in {
                        frozenset(required_stage),
                        frozenset(required_stage | {"evidence_artifacts"}),
                    }:
                        self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters/staged_report")
                    source = Path(staged["source_path"]).resolve(strict=False)
                    staging_root = (Path(root) / ".codex-loop" / "report-staging").resolve(strict=False)
                    expected_name = (
                        f"{payload[key]}.{str(staged['digest']).removeprefix('sha256:')}.json"
                    )
                    try:
                        source.relative_to(staging_root)
                        if source.name != expected_name:
                            raise ValueError("unexpected staged report name")
                        content = source.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError, ValueError):
                        self._gateway_error(
                            "STATE_GATEWAY_STAGED_REPORT_UNAVAILABLE",
                            "/params/arguments/request/parameters/staged_report/source_path",
                        )
                    content_digest = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
                    if content_digest != staged["digest"]:
                        self._gateway_error(
                            "STATE_GATEWAY_STAGED_REPORT_DIGEST_MISMATCH",
                            "/params/arguments/request/parameters/staged_report/digest",
                        )
                    route_id = payload[key]
                    route = state.get("gateway_route_ledger", {}).get(route_id, {})
                    if not isinstance(route, dict):
                        self._gateway_error("STATE_GATEWAY_ROUTE_NOT_SENT", "/params/arguments/request/parameters")
                    try:
                        report_attestation = runtime.read_codec_report_attestation(
                            route_id, staged["digest"]
                        )
                    except RuntimeRejection as exc:
                        if exc.code == "CODEC_REPORT_ATTESTATION_UNAVAILABLE":
                            self._gateway_error(
                                "STATE_GATEWAY_REPORT_TARGET_ATTESTATION_MISSING",
                                "/params/arguments/request/parameters/staged_report",
                            )
                        self._gateway_error(
                            "STATE_GATEWAY_REPORT_TARGET_ATTESTATION_INVALID",
                            "/params/arguments/request/parameters/staged_report",
                        )
                    expected_role = {
                        "DISPATCH": "WORKER", "ASSURANCE": "REVIEWER", "LOCAL": "LOCAL_VERIFIER",
                    }.get(route.get("outbox_kind"))
                    if (
                        not isinstance(report_attestation, dict)
                        or report_attestation.get("outbox_id") != route_id
                        or report_attestation.get("report_digest") != staged["digest"]
                        or report_attestation.get("thread_id") != route.get("target_thread_id")
                        or report_attestation.get("role_kind") != expected_role
                    ):
                        self._gateway_error(
                            "STATE_GATEWAY_REPORT_TARGET_ATTESTATION_MISSING",
                            "/params/arguments/request/parameters/staged_report",
                        )
                    artifacts = [{
                        "path": staged["path"], "content": content,
                        "digest": staged["digest"], "media_type": staged["media_type"],
                    }]
                    staged_evidence = staged.get("evidence_artifacts", [])
                    if not isinstance(staged_evidence, list):
                        self._gateway_error(
                            "STATE_GATEWAY_REQUEST_INVALID",
                            "/params/arguments/request/parameters/staged_report/evidence_artifacts",
                        )
                    seen_evidence_paths: set[str] = set()
                    for index, evidence in enumerate(staged_evidence):
                        evidence_path = (
                            "/params/arguments/request/parameters/staged_report/"
                            f"evidence_artifacts/{index}"
                        )
                        if (
                            not isinstance(evidence, dict)
                            or set(evidence)
                            != {"path", "source_path", "digest", "media_type"}
                            or evidence.get("path") in seen_evidence_paths
                        ):
                            self._gateway_error(
                                "STATE_GATEWAY_REQUEST_INVALID", evidence_path
                            )
                        media_suffix = {
                            "application/json": ".json",
                            "text/markdown": ".md",
                            "text/plain": ".txt",
                        }.get(evidence["media_type"])
                        destination = Path(evidence["path"])
                        if (
                            media_suffix is None
                            or destination.parent.as_posix() != ".codex-loop/reports"
                            or destination.suffix != media_suffix
                        ):
                            self._gateway_error(
                                "STATE_GATEWAY_STAGED_EVIDENCE_INVALID",
                                f"{evidence_path}/path",
                            )
                        evidence_source = Path(evidence["source_path"]).resolve(
                            strict=False
                        )
                        path_locator = hashlib.sha256(
                            evidence["path"].encode("utf-8")
                        ).hexdigest()[:16]
                        expected_evidence_name = (
                            f"{route_id}."
                            f"{str(evidence['digest']).removeprefix('sha256:')}"
                            f".evidence-{path_locator}{media_suffix}"
                        )
                        try:
                            evidence_source.relative_to(staging_root)
                            if evidence_source.name != expected_evidence_name:
                                raise ValueError("unexpected staged evidence name")
                            evidence_content = evidence_source.read_text(
                                encoding="utf-8"
                            )
                        except (OSError, UnicodeDecodeError, ValueError):
                            self._gateway_error(
                                "STATE_GATEWAY_STAGED_EVIDENCE_UNAVAILABLE",
                                f"{evidence_path}/source_path",
                            )
                        evidence_digest = "sha256:" + hashlib.sha256(
                            evidence_content.encode("utf-8")
                        ).hexdigest()
                        if evidence_digest != evidence["digest"]:
                            self._gateway_error(
                                "STATE_GATEWAY_STAGED_EVIDENCE_DIGEST_MISMATCH",
                                f"{evidence_path}/digest",
                            )
                        if evidence["media_type"] == "application/json":
                            try:
                                json.loads(evidence_content)
                            except (TypeError, ValueError):
                                self._gateway_error(
                                    "STATE_GATEWAY_STAGED_EVIDENCE_INVALID",
                                    f"{evidence_path}/source_path",
                                )
                        seen_evidence_paths.add(evidence["path"])
                        artifacts.append(
                            {
                                "path": evidence["path"],
                                "content": evidence_content,
                                "digest": evidence["digest"],
                                "media_type": evidence["media_type"],
                            }
                        )
                    gateway_payload = {
                        key: route_id,
                        "staged_report": staged,
                        "codec_report_attestation": copy.deepcopy(report_attestation),
                    }
                elif operation == "RECORD_TRANSPORT_OBSERVATION":
                    required_observation = {
                        "fingerprint", "outbox_id", "observed_at",
                        "natural_heartbeat", "heartbeat_automation_id",
                    }
                    attested = _optional_app_action_result(
                        params,
                        metadata,
                        action="APP_TRANSPORT_OBSERVATION",
                        result_fields=required_observation,
                    )
                    if attested is not None:
                        if payload:
                            self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters")
                        gateway_payload = attested
                    else:
                        required_direct = {
                            "fingerprint", "outbox_id", "observed_at", "natural_heartbeat",
                        }
                        if set(payload) != required_direct:
                            self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters")
                        identity = state.get("heartbeat_prompt_identity")
                        if payload["natural_heartbeat"] and not isinstance(identity, dict):
                            self._gateway_error("STATE_GATEWAY_HEARTBEAT_UNREGISTERED", "/params/arguments/request")
                        gateway_payload = {
                            **copy.deepcopy(payload),
                            "heartbeat_automation_id": (
                                identity["automation_id"] if payload["natural_heartbeat"] else None
                            ),
                        }
                    artifacts = []
                elif operation in {"ACK_TRANSPORT_PAUSE", "ACK_TRANSPORT_RECOVERY"}:
                    receipt_field = (
                        "paused_automation_receipt"
                        if operation == "ACK_TRANSPORT_PAUSE"
                        else "active_automation_receipt"
                    )
                    required_status = (
                        "PAUSED" if operation == "ACK_TRANSPORT_PAUSE" else "ACTIVE"
                    )
                    required_receipt = {
                        "automation_id", "status", "automation_name", "kind",
                        "target_thread_id", "rrule", "prompt_digest",
                        "prompt_normalization", "observed_at",
                    }
                    attested = _optional_app_action_result(
                        params,
                        metadata,
                        action="AUTOMATION_UPDATE",
                        result_fields=required_receipt,
                    )
                    if attested is not None:
                        if payload:
                            self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters")
                        paused_receipt = copy.deepcopy(attested)
                        evidence_model = "APP_ACTION_ATTESTED"
                    else:
                        if set(payload) != {receipt_field}:
                            self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters")
                        paused_receipt = copy.deepcopy(payload[receipt_field])
                        if (
                            not isinstance(paused_receipt, dict)
                            or (
                                set(paused_receipt) != required_receipt
                                and set(paused_receipt) != required_receipt | {"source_turn_id"}
                            )
                        ):
                            self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", f"/params/arguments/request/parameters/{receipt_field}")
                        if (
                            paused_receipt.get("source_turn_id") is not None
                            and paused_receipt["source_turn_id"] != metadata.turn_id
                        ):
                            self._gateway_error("APP_AUTOMATION_RECEIPT_TURN_MISMATCH", f"/params/arguments/request/parameters/{receipt_field}/source_turn_id")
                        evidence_model = "HOST_COOPERATIVE"
                    paused_receipt["source_turn_id"] = metadata.turn_id
                    heartbeat_observation, artifacts, pause_receipt = self._gateway_automation_artifacts(
                        state,
                        paused_receipt,
                        metadata,
                        stem=(
                            "gateway-transport"
                            if operation == "ACK_TRANSPORT_PAUSE"
                            else "gateway-transport-recovery"
                        ),
                        required_status=required_status,
                        parameter_name=receipt_field,
                        evidence_model=evidence_model,
                    )
                    gateway_payload = {
                        "heartbeat_observation": heartbeat_observation,
                        **pause_receipt,
                    }
                elif operation == "ADVANCE_ROADMAP":
                    if set(payload) != {"goal_id", "roadmap_audit_id", "observed_at"}:
                        self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters")
                    gateway_payload = copy.deepcopy(payload)
                    artifacts = []
                elif operation == "PREPARE_FINALIZATION":
                    if set(payload) != {"finalization_id", "goal_id", "final_audit_id", "observed_at"}:
                        self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters")
                    gateway_payload = copy.deepcopy(payload)
                    artifacts = []
                elif operation == "ACK_FINALIZATION":
                    required_receipt = {
                        "automation_id", "status", "automation_name", "kind",
                        "target_thread_id", "rrule", "prompt_digest",
                        "prompt_normalization", "observed_at",
                    }
                    attested = _optional_app_action_result(
                        params,
                        metadata,
                        action="AUTOMATION_UPDATE",
                        result_fields=required_receipt,
                    )
                    if attested is not None:
                        if set(payload) != {"finalization_id"}:
                            self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters")
                        paused_receipt = copy.deepcopy(attested)
                        evidence_model = "APP_ACTION_ATTESTED"
                    else:
                        if set(payload) != {"finalization_id", "paused_automation_receipt"}:
                            self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters")
                        paused_receipt = copy.deepcopy(payload["paused_automation_receipt"])
                        if (
                            not isinstance(paused_receipt, dict)
                            or (
                                set(paused_receipt) != required_receipt
                                and set(paused_receipt) != required_receipt | {"source_turn_id"}
                            )
                        ):
                            self._gateway_error("STATE_GATEWAY_REQUEST_INVALID", "/params/arguments/request/parameters/paused_automation_receipt")
                        if (
                            paused_receipt.get("source_turn_id") is not None
                            and paused_receipt["source_turn_id"] != metadata.turn_id
                        ):
                            self._gateway_error("APP_AUTOMATION_RECEIPT_TURN_MISMATCH", "/params/arguments/request/parameters/paused_automation_receipt/source_turn_id")
                        evidence_model = "HOST_COOPERATIVE"
                    paused_receipt["source_turn_id"] = metadata.turn_id
                    identity = state.get("heartbeat_prompt_identity")
                    if not isinstance(identity, dict):
                        self._gateway_error("STATE_GATEWAY_HEARTBEAT_UNREGISTERED", "/params/arguments/request")
                    heartbeat_observation = {
                        **copy.deepcopy(identity),
                        "automation_id": paused_receipt["automation_id"],
                        "status": paused_receipt["status"],
                        "observed_at": paused_receipt["observed_at"],
                    }
                    if (
                        paused_receipt.get("status") != "PAUSED"
                        or any(
                            paused_receipt.get(key) != heartbeat_observation.get(key)
                            for key in (
                                "automation_id", "automation_name", "kind",
                                "target_thread_id", "rrule", "prompt_digest",
                                "prompt_normalization", "observed_at",
                            )
                        )
                    ):
                        self._gateway_error("APP_AUTOMATION_RECEIPT_IDENTITY_MISMATCH", "/params/arguments/request/parameters/paused_automation_receipt")
                    heartbeat_content = json.dumps(heartbeat_observation, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                    heartbeat_digest = "sha256:" + hashlib.sha256(heartbeat_content.encode("utf-8")).hexdigest()
                    heartbeat_path = (
                        ".codex-loop/reports/gateway-final-heartbeat-"
                        f"{heartbeat_digest.removeprefix('sha256:')}.json"
                    )
                    goal_observation = {
                        "goal_id": "GATEWAY_NO_NATIVE_GOAL",
                        "status": "COMPLETE",
                        "observation_kind": "NATIVE_GOAL_NOT_USED",
                    }
                    goal_content = json.dumps(goal_observation, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                    goal_digest = "sha256:" + hashlib.sha256(goal_content.encode("utf-8")).hexdigest()
                    goal_path = (
                        ".codex-loop/reports/gateway-final-native-goal-"
                        f"{goal_digest.removeprefix('sha256:')}.json"
                    )
                    app_receipt = {
                        "observation_kind": "HOST_COOPERATIVE_AUTOMATION_UPDATE_OBSERVATION",
                        "evidence_model": evidence_model,
                        "controller_thread_id": metadata.thread_id,
                        "controller_turn_id": metadata.turn_id,
                        "automation": copy.deepcopy(paused_receipt),
                    }
                    app_content = json.dumps(app_receipt, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                    app_digest = "sha256:" + hashlib.sha256(app_content.encode("utf-8")).hexdigest()
                    app_path = (
                        ".codex-loop/reports/gateway-final-app-automation-"
                        f"{app_digest.removeprefix('sha256:')}.json"
                    )
                    artifacts = [
                        {"path": goal_path, "content": goal_content, "digest": goal_digest, "media_type": "application/json"},
                        {"path": heartbeat_path, "content": heartbeat_content, "digest": heartbeat_digest, "media_type": "application/json"},
                        {"path": app_path, "content": app_content, "digest": app_digest, "media_type": "application/json"},
                    ]
                    gateway_payload = {
                        "finalization_id": payload["finalization_id"],
                        "automation_id": paused_receipt["automation_id"],
                        "controller_goal_observation_path": goal_path,
                        "controller_goal_observation_digest": goal_digest,
                        "heartbeat_observation": heartbeat_observation,
                        "automation_observation_path": heartbeat_path,
                        "automation_observation_digest": heartbeat_digest,
                        "app_automation_receipt_path": app_path,
                        "app_automation_receipt_digest": app_digest,
                    }
                else:
                    self._gateway_error("STATE_GATEWAY_OPERATION_INVALID", "/params/arguments/request/operation")
                mutation = {"type": "STATE_GATEWAY", "operation": operation, "gateway_request": gateway_payload}
            expected_version = 0 if state is None else state["state_version"]
            runtime_request = {
                "controller_approved": True,
                "state_request_id": state_request_id,
                "event_id": f"gateway-event-{request_locator}",
                "gateway_public_request_digest": gateway_public_request_digest,
                "expected_state_version": expected_version,
                "actor": "MCP_STATE_GATEWAY",
                "thread_id": metadata.thread_id,
                "occurred_at": occurred_at,
                "evidence_paths": [artifact["path"] for artifact in artifacts],
                "artifacts": artifacts,
                "mutation": mutation,
            }
            pack_digest = (
                state.get("controller_pack_identity", {}).get("digest")
                if state is not None
                else mutation.get("gateway_request", {})
                .get("initialize_mutation", {})
                .get("controller_pack_digest")
            )
            if isinstance(pack_digest, str):
                runtime_request["controller_pack_digest"] = pack_digest
            response = runtime.apply(runtime_request, trusted_turn_metadata=metadata)
        except McpBridgeError as exc:
            response = _runtime_error(exc.code, exc.path, exc.details)
        post_state = state
        if runtime is not None:
            try:
                post_state = runtime.read_state()
            except (OSError, RuntimeRejection):
                post_state = None
        return self._tool_result(
            self._transport_recovery_fail_safe(response, operation_hint, post_state)
        )

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        request_id = message.get("id")
        method = message.get("method")
        if message.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return self._jsonrpc_error(request_id, -32600, "Invalid Request")
        if request_id is None:
            if method == "notifications/initialized":
                self.initialized = True
            return None
        params = message.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return self._jsonrpc_error(request_id, -32602, "Invalid params")
        if method == "initialize":
            requested = params.get("protocolVersion")
            protocol_version = (
                requested
                if requested in MCP_PROTOCOL_VERSIONS
                else MCP_PROTOCOL_VERSIONS[0]
            )
            self.initialized = True
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": protocol_version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {
                        "name": MCP_SERVER_NAME,
                        "version": MCP_SERVER_VERSION,
                    },
                },
            }
        if not self.initialized:
            return self._jsonrpc_error(request_id, -32002, "Not initialized")
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": [
                        {
                            "name": MCP_TOOL_NAME,
                            "description": (
                                "Apply exactly one ACQUIRE_LEASE or "
                                "TAKEOVER_LEASE using Codex host-injected "
                                "turn metadata. State-Writer mutations do not "
                                "cross this route bridge, and model arguments "
                                "cannot supply the trusted identity. Native "
                                "Goal generation recovery is unavailable."
                            ),
                            "inputSchema": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["root", "request"],
                                "properties": {
                                    "root": {"type": "string"},
                                    "request": {"type": "object"},
                                },
                            },
                            "annotations": {
                                "readOnlyHint": False,
                                "destructiveHint": False,
                                "idempotentHint": True,
                                "openWorldHint": False,
                            },
                        }
                        ,
                        {
                            "name": MCP_RUNTIME_CODEC_TOOL_NAME,
                            "description": (
                                "Materialize or verify exact dispatch payloads, stage "
                                "formal reports or external receipts, and normalize "
                                "failure fingerprints without a shell stdin session."
                            ),
                            "inputSchema": {
                                "oneOf": [
                                    {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["operation", "request"],
                                        "properties": {
                                            "operation": {"const": "MATERIALIZE_DISPATCH"},
                                            "request": {"type": "object"},
                                        },
                                    },
                                    {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["operation", "root", "transport_text"],
                                        "properties": {
                                            "operation": {"const": "VERIFY_DISPATCH"},
                                            "root": {"type": "string"},
                                            "transport_text": {"type": "string"},
                                        },
                                    },
                                    {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["operation", "root", "request"],
                                        "properties": {
                                            "operation": {"const": "STAGE_REPORT"},
                                            "root": {"type": "string"},
                                            "request": {"type": "object"},
                                        },
                                    },
                                    {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["operation", "root", "request"],
                                        "properties": {
                                            "operation": {"const": "STAGE_EXTERNAL_RECEIPT"},
                                            "root": {"type": "string"},
                                            "request": {"type": "object"},
                                        },
                                    },
                                    {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["operation", "request"],
                                        "properties": {
                                            "operation": {"const": "NORMALIZE_FINGERPRINT"},
                                            "request": {"type": "object"},
                                        },
                                    },
                                    {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["operation", "root", "request"],
                                        "properties": {
                                            "operation": {"const": "CAPTURE_COMPLETE_DIFF"},
                                            "root": {"type": "string"},
                                            "request": {"type": "object"},
                                        },
                                    },
                                ]
                            },
                            "annotations": {
                                "readOnlyHint": False,
                                "destructiveHint": False,
                                "idempotentHint": True,
                                "openWorldHint": False,
                            },
                        },
                        {
                            "name": MCP_STATE_GATEWAY_TOOL_NAME,
                            "description": (
                                "The schema v3 canonical writer. Atomically prepares "
                                "a route, records one App send observation, acknowledges "
                                "a staged report on the original outbox, registers bootstrap "
                                "tasks and the sole heartbeat, advances an unchanged roadmap, "
                                "finalizes a v3 loop, initializes a fresh loop or successor, "
                                "records bounded transport degradation, or atomically resumes "
                                "after the retained outbox and same heartbeat recover. "
                                "It derives leases, freshness, validation and artifact "
                                "identities from canonical state; callers cannot supply them."
                            ),
                            "inputSchema": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["root", "request"],
                                "properties": {
                                    "root": {"type": "string"},
                                    "request": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["request_id", "operation", "occurred_at", "parameters"],
                                        "properties": {
                                            "request_id": {
                                                "type": "string",
                                                "minLength": 1,
                                                "maxLength": 128,
                                                "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]*$",
                                            },
                                            "operation": {
                                                "enum": [
                                                    "INITIALIZE", "MIGRATE_V2_TO_V3", "PREPARE_ROUTE",
                                                    "REGISTER_TASK", "REGISTER_HEARTBEAT",
                                                    "RECORD_HEARTBEAT_OBSERVATION", "RECORD_ROUTE_SENT",
                                                    "ACK_ROUTE_RESULT", "REPORT_RECOVERY", "ADVANCE_ROADMAP",
                                                    "PREPARE_FINALIZATION", "ACK_FINALIZATION",
                                                    "INITIALIZE_SUCCESSOR", "RECORD_TRANSPORT_OBSERVATION",
                                                    "ACK_TRANSPORT_PAUSE", "ACK_TRANSPORT_RECOVERY"
                                                ]
                                            },
                                            "occurred_at": {"type": "string"},
                                            "parameters": {"type": "object"}
                                        }
                                    }
                                }
                            },
                            "annotations": {
                                "readOnlyHint": False,
                                "destructiveHint": False,
                                "idempotentHint": True,
                                "openWorldHint": False,
                            },
                        }
                    ]
                },
            }
        if method == "tools/call":
            tool_name = params.get("name")
            if tool_name not in {
                MCP_TOOL_NAME,
                MCP_RUNTIME_CODEC_TOOL_NAME,
                MCP_STATE_GATEWAY_TOOL_NAME,
            }:
                return self._jsonrpc_error(request_id, -32602, "Unknown tool")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": (
                    self._call_route_tool(params)
                    if tool_name == MCP_TOOL_NAME
                    else self._call_runtime_codec(params)
                    if tool_name == MCP_RUNTIME_CODEC_TOOL_NAME
                    else self._call_state_gateway(params)
                ),
            }
        return self._jsonrpc_error(request_id, -32601, "Method not found")

    @staticmethod
    def _jsonrpc_error(
        request_id: Any,
        code: int,
        message: str,
    ) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }


def serve(
    input_stream: BinaryIO,
    output_stream: BinaryIO,
    *,
    server: AdaptiveStateMcpServer | None = None,
) -> int:
    active_server = server or AdaptiveStateMcpServer.from_current_process()
    reader = McpFrameReader(input_stream)
    while True:
        try:
            message = reader.read()
        except McpBridgeError as exc:
            response = AdaptiveStateMcpServer._jsonrpc_error(
                None,
                -32700,
                exc.code,
            )
            output_stream.write(
                json.dumps(response, separators=(",", ":")).encode("utf-8")
                + b"\n"
            )
            output_stream.flush()
            return 1
        if message is None:
            return 0
        response = active_server.handle(message)
        if response is None:
            continue
        output_stream.write(
            json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n"
        )
        output_stream.flush()


def main() -> int:
    return serve(sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    raise SystemExit(main())
