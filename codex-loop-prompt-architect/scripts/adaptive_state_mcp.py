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

from loop_architect.state_runtime import (
    OPENAI_CODE_SIGN_IDENTIFIER,
    OPENAI_CODE_SIGN_TEAM_ID,
    TRUSTED_HOST_BOUNDARY,
    TRUSTED_TURN_SOURCE,
    AdaptiveStateRuntime,
    TrustedHostAttestation,
    TrustedTurnMetadata,
)


MCP_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2024-11-05")
MCP_SERVER_NAME = "codex-loop-state"
MCP_SERVER_VERSION = "1.1.0"
MCP_TOOL_NAME = "route_state_mutation"
MCP_TURN_META_KEY = "x-codex-turn-metadata"
MCP_THREAD_META_KEY = "threadId"
MCP_INPUT_MAX_BYTES = 4_000_000
MCP_PARTIAL_FRAME_TIMEOUT_SECONDS = 30.0
MCP_READ_CHUNK_BYTES = 64 * 1024
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
                    ]
                },
            }
        if method == "tools/call":
            if params.get("name") != MCP_TOOL_NAME:
                return self._jsonrpc_error(request_id, -32602, "Unknown tool")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": self._call_route_tool(params),
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
