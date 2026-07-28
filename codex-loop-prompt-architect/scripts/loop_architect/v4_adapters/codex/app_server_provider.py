"""Production Codex app-server provider for the v4 Host Adapter port.

The provider owns Host-specific JSON-RPC literals.  It never writes the
canonical LoopSkill store and never retries a create.  Recovery performs only
authoritative readback by a machine-derived request marker.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from loop_architect.v4_alpha.protocol import CAPABILITY_NAMES, canonical_bytes

from .adapter import HOST_SCHEMA_VERSION, HostResponseLost, HostUnavailable


APP_SERVER_PROTOCOL = "codex-app-server-v2"
MAX_HOST_FRAME_BYTES = 1_048_576
MAX_HOST_PROMPT_BYTES = 32 * 1024
MAX_PROTOCOL_SCHEMA_BYTES = 4 * 1024 * 1024
THREAD_LIST_PAGE_SIZE = 100
MAX_THREAD_LIST_PAGES = 64
MAX_THREAD_LIST_CURSOR_BYTES = 4_096
_MACHINE_MARKER = re.compile(r"LOOPSKILL4_REQUEST=[0-9a-f]{64}(?![0-9a-f])")
CODEX_DESKTOP_EXECUTABLE = Path("/Applications/ChatGPT.app/Contents/Resources/codex")

_PROTOCOL_SCHEMA_FILES = {
    "thread_start_params": "v2/ThreadStartParams.json",
    "thread_start_response": "v2/ThreadStartResponse.json",
    "turn_start_params": "v2/TurnStartParams.json",
    "turn_start_response": "v2/TurnStartResponse.json",
}


@dataclass(frozen=True)
class _AppServerProtocolContract:
    """Pre-effect wire contract derived from the installed Codex executable."""

    schema_digest: str
    thread_id_path: tuple[str, ...]
    turn_id_path: tuple[str, ...]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _request_marker(provider_key: str) -> str:
    digest = hashlib.sha256(
        b"loopskill-app-server-request-v1\n" + provider_key.encode("utf-8")
    ).hexdigest()
    return f"LOOPSKILL4_REQUEST={digest}"


def _codex_executable() -> str:
    """Prefer the active Desktop Host binary over a shadowing CLI on macOS."""

    if sys.platform == "darwin":
        try:
            metadata = CODEX_DESKTOP_EXECUTABLE.lstat()
            if (
                stat.S_ISREG(metadata.st_mode)
                and not CODEX_DESKTOP_EXECUTABLE.is_symlink()
                and metadata.st_mode & 0o111
                and metadata.st_size > 0
            ):
                return str(CODEX_DESKTOP_EXECUTABLE)
        except OSError:
            pass
    return shutil.which("codex") or "codex"


def _reject_json_constant(constant: str) -> None:
    raise ValueError(f"non-finite JSON number: {constant}")


def _resolve_local_ref(document: Mapping[str, Any], node: Any) -> Any:
    seen: set[str] = set()
    current = node
    while isinstance(current, Mapping) and isinstance(current.get("$ref"), str):
        reference = current["$ref"]
        if not reference.startswith("#/definitions/") or reference in seen:
            raise HostUnavailable("Codex app-server protocol schema drift")
        seen.add(reference)
        name = reference.removeprefix("#/definitions/")
        definitions = document.get("definitions")
        if not isinstance(definitions, Mapping) or name not in definitions:
            raise HostUnavailable("Codex app-server protocol schema drift")
        current = definitions[name]
    return current


def _schema_accepts_literal(
    document: Mapping[str, Any], node: Any, value: Any
) -> bool:
    try:
        resolved = _resolve_local_ref(document, node)
    except HostUnavailable:
        return False
    if not isinstance(resolved, Mapping):
        return False
    if "enum" in resolved:
        enum = resolved["enum"]
        return isinstance(enum, list) and value in enum
    for keyword in ("anyOf", "oneOf"):
        choices = resolved.get(keyword)
        if isinstance(choices, list):
            return any(_schema_accepts_literal(document, choice, value) for choice in choices)
    combined = resolved.get("allOf")
    if isinstance(combined, list):
        return bool(combined) and all(
            _schema_accepts_literal(document, choice, value) for choice in combined
        )
    schema_type = resolved.get("type")
    allowed = {schema_type} if isinstance(schema_type, str) else set(schema_type or ())
    if isinstance(value, str):
        return "string" in allowed
    if isinstance(value, bool):
        return "boolean" in allowed
    if value is None:
        return "null" in allowed
    if isinstance(value, Mapping):
        properties = resolved.get("properties")
        required = resolved.get("required", [])
        if (
            "object" not in allowed
            or not isinstance(properties, Mapping)
            or not isinstance(required, list)
            or not set(required) <= set(value)
            or (
                resolved.get("additionalProperties") is False
                and not set(value) <= set(properties)
            )
        ):
            return False
        return all(
            key in properties
            and _schema_accepts_literal(document, properties[key], item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        items = resolved.get("items")
        return (
            "array" in allowed
            and items is not None
            and all(_schema_accepts_literal(document, items, item) for item in value)
        )
    return False


def _response_identity_path(
    document: Mapping[str, Any],
    *,
    title: str,
    container_name: str,
    direct_name: str,
) -> tuple[str, ...]:
    if document.get("title") != title or document.get("type") != "object":
        raise HostUnavailable("Codex app-server protocol schema drift")
    properties = document.get("properties")
    required = document.get("required")
    if not isinstance(properties, Mapping) or not isinstance(required, list):
        raise HostUnavailable("Codex app-server protocol schema drift")
    candidates: list[tuple[str, ...]] = []
    if direct_name in required and _schema_accepts_literal(
        document, properties.get(direct_name), "identity"
    ):
        candidates.append((direct_name,))
    if container_name in required and container_name in properties:
        container = _resolve_local_ref(document, properties[container_name])
        if isinstance(container, Mapping):
            nested_properties = container.get("properties")
            nested_required = container.get("required")
            if (
                isinstance(nested_properties, Mapping)
                and isinstance(nested_required, list)
                and "id" in nested_required
                and _schema_accepts_literal(
                    document, nested_properties.get("id"), "identity"
                )
            ):
                candidates.append((container_name, "id"))
    if len(candidates) != 1:
        raise HostUnavailable("Codex app-server protocol response shape drift")
    return candidates[0]


def _supports_text_input(document: Mapping[str, Any], node: Any) -> bool:
    resolved = _resolve_local_ref(document, node)
    if not isinstance(resolved, Mapping) or resolved.get("type") != "array":
        return False
    items = _resolve_local_ref(document, resolved.get("items"))
    if not isinstance(items, Mapping):
        return False
    choices = items.get("oneOf") or items.get("anyOf")
    if not isinstance(choices, list):
        choices = [items]
    for choice in choices:
        variant = _resolve_local_ref(document, choice)
        if not isinstance(variant, Mapping):
            continue
        properties = variant.get("properties")
        required = variant.get("required")
        if (
            isinstance(properties, Mapping)
            and isinstance(required, list)
            and {"text", "type"} <= set(required)
            and _schema_accepts_literal(document, properties.get("type"), "text")
            and _schema_accepts_literal(document, properties.get("text"), "content")
        ):
            return True
    return False


def _protocol_contract_from_schemas(
    schemas: Mapping[str, Mapping[str, Any]],
) -> _AppServerProtocolContract:
    """Validate only wire fields used by this provider and derive ID paths."""

    if set(schemas) != set(_PROTOCOL_SCHEMA_FILES):
        raise HostUnavailable("Codex app-server protocol schema set drift")
    thread_params = schemas["thread_start_params"]
    turn_params = schemas["turn_start_params"]
    if (
        thread_params.get("title") != "ThreadStartParams"
        or thread_params.get("type") != "object"
        or turn_params.get("title") != "TurnStartParams"
        or turn_params.get("type") != "object"
    ):
        raise HostUnavailable("Codex app-server protocol request shape drift")
    thread_properties = thread_params.get("properties")
    turn_properties = turn_params.get("properties")
    thread_required = thread_params.get("required", [])
    turn_required = turn_params.get("required", [])
    thread_fields = {
        "approvalPolicy",
        "cwd",
        "ephemeral",
        "sandbox",
        "threadSource",
    }
    turn_fields = {
        "approvalPolicy",
        "clientUserMessageId",
        "cwd",
        "input",
        "sandboxPolicy",
        "threadId",
    }
    representative_workspace_policy = {
        "excludeSlashTmp": True,
        "excludeTmpdirEnvVar": True,
        "networkAccess": False,
        "type": "workspaceWrite",
        "writableRoots": ["/workspace"],
    }
    if (
        not isinstance(thread_properties, Mapping)
        or not isinstance(turn_properties, Mapping)
        or not isinstance(thread_required, list)
        or not isinstance(turn_required, list)
        or not thread_fields <= set(thread_properties)
        or not turn_fields <= set(turn_properties)
        or not set(thread_required) <= thread_fields
        or not set(turn_required) <= turn_fields
        or not _schema_accepts_literal(
            thread_params, thread_properties["approvalPolicy"], "on-request"
        )
        or not _schema_accepts_literal(
            thread_params, thread_properties["sandbox"], "read-only"
        )
        or not _schema_accepts_literal(
            thread_params, thread_properties["threadSource"], "loopskill4"
        )
        or not _schema_accepts_literal(
            thread_params, thread_properties["ephemeral"], False
        )
        or not _schema_accepts_literal(
            turn_params, turn_properties["clientUserMessageId"], "operation-id"
        )
        or not _schema_accepts_literal(
            turn_params, turn_properties["threadId"], "thread-id"
        )
        or not _schema_accepts_literal(
            turn_params, turn_properties["approvalPolicy"], "on-request"
        )
        or not _schema_accepts_literal(
            turn_params,
            turn_properties["sandboxPolicy"],
            representative_workspace_policy,
        )
        or not _supports_text_input(turn_params, turn_properties["input"])
    ):
        raise HostUnavailable("Codex app-server protocol request shape drift")
    thread_id_path = _response_identity_path(
        schemas["thread_start_response"],
        title="ThreadStartResponse",
        container_name="thread",
        direct_name="threadId",
    )
    turn_id_path = _response_identity_path(
        schemas["turn_start_response"],
        title="TurnStartResponse",
        container_name="turn",
        direct_name="turnId",
    )
    schema_bytes = json.dumps(
        schemas,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _AppServerProtocolContract(
        schema_digest=hashlib.sha256(schema_bytes).hexdigest(),
        thread_id_path=thread_id_path,
        turn_id_path=turn_id_path,
    )


def _read_protocol_schema(path: Path) -> Mapping[str, Any]:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not path.is_file() or metadata.st_size > MAX_PROTOCOL_SCHEMA_BYTES:
            raise OSError("unsafe protocol schema")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(descriptor)
            chunks: list[bytes] = []
            remaining = MAX_PROTOCOL_SCHEMA_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            if (
                not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
                or len(raw) != metadata.st_size
            ):
                raise OSError("protocol schema changed during read")
        finally:
            os.close(descriptor)
        value = json.loads(
            raw.decode("utf-8", "strict"),
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise HostUnavailable("Codex app-server protocol schema unavailable") from exc
    if not isinstance(value, Mapping):
        raise HostUnavailable("Codex app-server protocol schema drift")
    return value


def _probe_protocol_contract(
    command: Sequence[str], timeout_seconds: float
) -> _AppServerProtocolContract:
    """Generate and inspect local schemas without starting a Host task/thread."""

    selected = tuple(command)
    if len(selected) < 3 or selected[-2:] != ("app-server", "--stdio"):
        raise HostUnavailable("Codex app-server protocol probe command is unavailable")
    with tempfile.TemporaryDirectory(prefix="loopskill-codex-schema-") as temporary:
        output = Path(temporary)
        generator = (
            *selected[:-1],
            "generate-json-schema",
            "--out",
            str(output),
        )
        try:
            subprocess.run(
                generator,
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=min(timeout_seconds, 30.0),
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise HostUnavailable("Codex app-server protocol probe failed") from exc
        schemas = {
            name: _read_protocol_schema(output / relative)
            for name, relative in _PROTOCOL_SCHEMA_FILES.items()
        }
    return _protocol_contract_from_schemas(schemas)


class _AppServerSession:
    def __init__(self, command: Sequence[str], *, timeout_seconds: float) -> None:
        if not command or timeout_seconds <= 0 or timeout_seconds > 120:
            raise ValueError("invalid app-server session configuration")
        self._timeout_seconds = timeout_seconds
        try:
            self._process = subprocess.Popen(
                list(command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=False,
                bufsize=0,
                close_fds=True,
            )
        except OSError as exc:
            raise HostUnavailable("Codex app-server is unavailable") from exc
        if self._process.stdin is None or self._process.stdout is None:
            self.close()
            raise HostUnavailable("Codex app-server pipes are unavailable")
        try:
            self._stdin_fd = self._process.stdin.fileno()
            self._stdout_fd = self._process.stdout.fileno()
            os.set_blocking(self._stdin_fd, False)
            os.set_blocking(self._stdout_fd, False)
            self._read_buffer = bytearray()
            self._next_id = 1
            self._initialize()
        except BaseException:
            try:
                self.close()
            except Exception:
                pass
            raise

    def _write(self, value: Mapping[str, Any]) -> None:
        try:
            raw = (
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8", "strict")
                + b"\n"
            )
        except (TypeError, ValueError, UnicodeEncodeError) as exc:
            raise HostUnavailable("Codex app-server request is not strict JSON") from exc
        if len(raw) > MAX_HOST_FRAME_BYTES:
            raise HostUnavailable("Codex app-server request exceeds the frame bound")
        selector = selectors.DefaultSelector()
        selector.register(self._stdin_fd, selectors.EVENT_WRITE)
        deadline = time.monotonic() + self._timeout_seconds
        offset = 0
        try:
            while offset < len(raw):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise HostResponseLost("Codex app-server request timed out")
                try:
                    written = os.write(self._stdin_fd, raw[offset:])
                except BlockingIOError:
                    continue
                if written <= 0:
                    raise HostResponseLost("Codex app-server request channel was lost")
                offset += written
        except (BrokenPipeError, OSError) as exc:
            raise HostResponseLost("Codex app-server request channel was lost") from exc
        finally:
            selector.close()

    def _initialize(self) -> None:
        result = self.request(
            "initialize",
            {
                "capabilities": {"experimentalApi": False},
                "clientInfo": {"name": "loopskill4", "version": "4.0.0"},
            },
        )
        if not isinstance(result, Mapping) or not all(
            isinstance(result.get(key), str)
            for key in ("codexHome", "platformFamily", "platformOs", "userAgent")
        ):
            raise HostUnavailable("Codex app-server initialize schema drift")
        self._write({"jsonrpc": "2.0", "method": "initialized", "params": {}})

    def _read_frame(
        self,
        selector: selectors.BaseSelector,
        deadline: float,
    ) -> bytes:
        """Read one newline frame without letting a partial frame defeat timeout."""

        while True:
            newline = self._read_buffer.find(b"\n")
            if newline >= 0:
                frame_size = newline + 1
                if frame_size > MAX_HOST_FRAME_BYTES:
                    raise HostUnavailable("Codex app-server frame bound/schema drift")
                raw = bytes(self._read_buffer[:frame_size])
                del self._read_buffer[:frame_size]
                return raw
            if len(self._read_buffer) >= MAX_HOST_FRAME_BYTES:
                raise HostUnavailable("Codex app-server frame bound/schema drift")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HostResponseLost("Codex app-server response timed out")
            if not selector.select(remaining):
                raise HostResponseLost("Codex app-server response timed out")
            try:
                chunk = os.read(
                    self._stdout_fd,
                    min(65_536, MAX_HOST_FRAME_BYTES - len(self._read_buffer)),
                )
            except BlockingIOError:
                continue
            if not chunk:
                raise HostResponseLost("Codex app-server closed before response")
            self._read_buffer.extend(chunk)

    def request(self, method: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._write(
            {
                "id": request_id,
                "jsonrpc": "2.0",
                "method": method,
                "params": dict(params),
            }
        )
        selector = selectors.DefaultSelector()
        assert self._process.stdout is not None
        selector.register(self._process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + self._timeout_seconds
        try:
            while time.monotonic() < deadline:
                raw = self._read_frame(selector, deadline)
                try:
                    message = json.loads(raw.decode("utf-8", "strict"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise HostUnavailable("Codex app-server returned invalid JSON") from exc
                if not isinstance(message, Mapping):
                    raise HostUnavailable("Codex app-server response schema drift")
                if "id" in message and "method" in message:
                    self._write(
                        {
                            "error": {
                                "code": -32601,
                                "message": "LoopSkill client request unsupported",
                            },
                            "id": message["id"],
                            "jsonrpc": "2.0",
                        }
                    )
                    continue
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    raise HostUnavailable("Codex app-server rejected the request")
                result = message.get("result")
                if not isinstance(result, Mapping):
                    raise HostUnavailable("Codex app-server result schema drift")
                return result
        finally:
            selector.close()
        raise HostResponseLost("Codex app-server response timed out")

    def close(self) -> None:
        process = getattr(self, "_process", None)
        if process is None:
            return
        self._process = None
        if process.stdin is not None and not process.stdin.closed:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        finally:
            if process.stdout is not None and not process.stdout.closed:
                try:
                    process.stdout.close()
                except OSError:
                    pass


class CodexAppServerProvider:
    """Concrete production provider using the local Codex app-server protocol."""

    def __init__(
        self,
        workspace: Path | str,
        *,
        command: Sequence[str] | None = None,
        issuer_ref: str = "loopskill-codex-adapter-v1",
        issuer_trust: str = "local-codex-adapter",
        clock: Callable[[], datetime] = _now,
        timeout_seconds: float = 30.0,
        protocol_probe: Callable[
            [Sequence[str], float], _AppServerProtocolContract
        ] = _probe_protocol_contract,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        resolved = Path(workspace).resolve(strict=True)
        if not resolved.is_dir() or resolved.is_symlink():
            raise ValueError("Host workspace must be one existing directory")
        executable = _codex_executable() if command is None else None
        selected = tuple(command or ((executable or "codex"), "app-server", "--stdio"))
        if not selected:
            raise ValueError("Codex app-server command is empty")
        self.workspace = resolved
        self.command = selected
        self.issuer_ref = issuer_ref
        self.issuer_trust = issuer_trust
        self.clock = clock
        self.timeout_seconds = timeout_seconds
        self._protocol_probe = protocol_probe
        self._protocol_contract: _AppServerProtocolContract | None = None
        self._monotonic = monotonic
        self._sleeper = sleeper
        self._active_session: _AppServerSession | None = None
        self._records: dict[str, dict[str, str]] = {}
        self._invoked_keys: set[str] = set()
        self._task_create_count = 0
        self._delivery_readback_count = 0
        self._task_result_read_count = 0
        self._lifecycle_read_count = 0
        self._provider_resend_count = 0
        self._terminal_wait_read_count = 0
        self._duplicate_invoke_rejection_count = 0

    @property
    def metrics(self) -> Mapping[str, int]:
        """Return privacy-safe provider-port counts, never Host identities."""
        return {
            "delivery_readback_count": self._delivery_readback_count,
            "duplicate_invoke_rejection_count": self._duplicate_invoke_rejection_count,
            "lifecycle_read_count": self._lifecycle_read_count,
            "provider_resend_count": self._provider_resend_count,
            "task_create_count": self._task_create_count,
            "task_result_read_count": self._task_result_read_count,
            "terminal_wait_read_count": self._terminal_wait_read_count,
        }

    def preflight(self) -> Mapping[str, Any]:
        """Bind the installed protocol shape before any Host create request."""

        if self._protocol_contract is None:
            contract = self._protocol_probe(self.command, self.timeout_seconds)
            if not isinstance(contract, _AppServerProtocolContract):
                raise HostUnavailable("Codex app-server protocol probe contract drift")
            self._protocol_contract = contract
        return {
            "schema_digest": self._protocol_contract.schema_digest,
            "thread_id_path": self._protocol_contract.thread_id_path,
            "turn_id_path": self._protocol_contract.turn_id_path,
        }

    def _contract(self) -> _AppServerProtocolContract:
        self.preflight()
        assert self._protocol_contract is not None
        return self._protocol_contract

    def _open_session(self) -> _AppServerSession:
        return _AppServerSession(self.command, timeout_seconds=self.timeout_seconds)

    @contextmanager
    def _session(self) -> Iterator[_AppServerSession]:
        session = self._open_session()
        try:
            yield session
        finally:
            session.close()

    def close(self) -> None:
        """Close the task-owning app-server session, if one is still active."""

        session = self._active_session
        self._active_session = None
        if session is not None:
            session.close()

    def capability_snapshot(self) -> Mapping[str, Any]:
        self.preflight()
        now = self.clock().astimezone(timezone.utc)
        observed = now - timedelta(seconds=1)
        available_strict = {
            "task_create",
            "resource_read",
            "eventual_indexing",
            "lifecycle_readback",
        }
        unavailable = {
            "project_registration",
            "thread_create",
            "message_send",
            "heartbeat",
            "provider_idempotency",
            "artifact_existing_git",
            "artifact_non_git",
            "artifact_new_git",
        }
        identity = hashlib.sha256(
            (APP_SERVER_PROTOCOL + "\0" + os.path.realpath(self.command[0])).encode()
        ).hexdigest()
        rows = []
        for name in CAPABILITY_NAMES:
            if name in available_strict:
                availability, assurance = "AVAILABLE", "STRICT"
            elif name in unavailable:
                availability, assurance = "UNAVAILABLE", "NONE"
            else:
                availability, assurance = "UNVERIFIABLE", "COOPERATIVE"
            rows.append(
                {
                    "assurance": assurance,
                    "availability": availability,
                    "details": {
                        "expires_at": _iso(now + timedelta(minutes=5)),
                        "identity_ref": identity if availability == "AVAILABLE" else None,
                        "issuer_ref": self.issuer_ref,
                        "issuer_trust": self.issuer_trust,
                        "observed_at": _iso(observed),
                        "source": APP_SERVER_PROTOCOL,
                    },
                    "name": name,
                    "receipt_ref": "capability-" + hashlib.sha256(
                        f"{identity}\0{name}\0{availability}\0{assurance}".encode()
                    ).hexdigest()[:24],
                }
            )
        return {"capabilities": rows, "schema_version": HOST_SCHEMA_VERSION}

    def invoke(
        self,
        action: str,
        payload: Mapping[str, Any],
        provider_idempotency_key: str,
    ) -> Mapping[str, Any]:
        expected = {
            "acceptance_criteria",
            "authorization_boundaries",
            "budget",
            "execution_mode",
            "external_actions",
            "goal",
            "stop_conditions",
            "target_ref",
            "write_scope",
        }
        if action != "create_task" or set(payload) != expected:
            raise HostUnavailable("Unsupported Codex app-server action or payload")
        prompt = self._prompt(payload, _request_marker(provider_idempotency_key))
        contract = self._contract()
        if self._invoked_keys:
            self._duplicate_invoke_rejection_count += 1
            raise HostUnavailable("Codex Provider create budget is already consumed")
        self._invoked_keys.add(provider_idempotency_key)
        marker = _request_marker(provider_idempotency_key)
        session = self._open_session()
        try:
            self._task_create_count += 1
            started = session.request(
                "thread/start",
                {
                    "approvalPolicy": "on-request",
                    "cwd": str(self.workspace),
                    "ephemeral": False,
                    "sandbox": "read-only",
                    "threadSource": "loopskill4",
                },
            )
            thread_id = self._response_identity(
                started, contract.thread_id_path, "thread/start"
            )
            turn_started = session.request(
                "turn/start",
                {
                    "approvalPolicy": "on-request",
                    "clientUserMessageId": provider_idempotency_key,
                    "cwd": str(self.workspace),
                    "input": [{"text": prompt, "type": "text"}],
                    "sandboxPolicy": {
                        "excludeSlashTmp": True,
                        "excludeTmpdirEnvVar": True,
                        "networkAccess": False,
                        "type": "workspaceWrite",
                        "writableRoots": [str(self.workspace)],
                    },
                    "threadId": thread_id,
                },
            )
            turn_id = self._response_identity(
                turn_started, contract.turn_id_path, "turn/start"
            )
        except BaseException:
            try:
                session.close()
            except Exception:
                pass
            raise
        self._active_session = session
        self._records[provider_idempotency_key] = {
            "marker": marker,
            "target_ref": str(payload["target_ref"]),
            "thread_id": thread_id,
            "turn_id": turn_id,
        }
        return self._observation(
            action, provider_idempotency_key, thread_id, marker, "ACCEPTED", "cooperative"
        )

    def readback(
        self, action: str, provider_idempotency_key: str
    ) -> Mapping[str, Any] | None:
        if action != "create_task":
            return None
        self.preflight()
        self._delivery_readback_count += 1
        marker = _request_marker(provider_idempotency_key)
        record = self._records.get(provider_idempotency_key)
        with self._session() as session:
            thread = None
            if record is not None:
                response = session.request(
                    "thread/read",
                    {"includeTurns": True, "threadId": record["thread_id"]},
                )
                thread = response.get("thread")
            else:
                matches = self._listed_marker_matches(session, marker)
                if len(matches) > 1:
                    raise HostUnavailable("Codex readback identity is ambiguous")
                thread = matches[0] if matches else None
            if thread is None:
                return None
            self._validate_thread(thread, marker)
            thread_id = str(thread["id"])
            if record is None:
                self._records[provider_idempotency_key] = {
                    "marker": marker,
                    "target_ref": "",
                    "thread_id": thread_id,
                    "turn_id": "",
                }
        return self._observation(
            action, provider_idempotency_key, thread_id, marker, "OBSERVED", "authoritative"
        )

    def _listed_marker_matches(
        self,
        session: _AppServerSession,
        marker: str,
    ) -> list[Mapping[str, Any]]:
        """Consume the bounded forward cursor before deciding marker cardinality."""

        cursor: str | None = None
        seen_cursors: set[str] = set()
        matches: list[Mapping[str, Any]] = []
        workspace = str(self.workspace)
        for _ in range(MAX_THREAD_LIST_PAGES):
            params: dict[str, Any] = {
                "archived": False,
                "cwd": workspace,
                "limit": THREAD_LIST_PAGE_SIZE,
                "useStateDbOnly": True,
            }
            if cursor is not None:
                params["cursor"] = cursor
            response = session.request("thread/list", params)
            listed = response.get("data")
            if not isinstance(listed, list) or len(listed) > THREAD_LIST_PAGE_SIZE:
                raise HostUnavailable("Codex thread/list schema drift")
            for item in listed:
                if not isinstance(item, Mapping) or item.get("cwd") != workspace:
                    raise HostUnavailable("Codex thread/list cwd/schema drift")
                preview = item.get("preview")
                if not isinstance(preview, str):
                    raise HostUnavailable("Codex thread/list preview schema drift")
                if marker in preview:
                    if _MACHINE_MARKER.findall(preview) != [marker]:
                        raise HostUnavailable("Codex readback identity is ambiguous")
                    matches.append(item)
                    if len(matches) > 1:
                        raise HostUnavailable("Codex readback identity is ambiguous")
            next_cursor = response.get("nextCursor")
            if next_cursor is None:
                return matches
            if (
                not isinstance(next_cursor, str)
                or not next_cursor
                or len(next_cursor.encode("utf-8")) > MAX_THREAD_LIST_CURSOR_BYTES
                or next_cursor in seen_cursors
            ):
                raise HostUnavailable("Codex thread/list cursor drift")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        raise HostUnavailable("Codex thread/list pagination bound exceeded")

    def read_resource(self, resource_kind: str, provider_id: str) -> Mapping[str, Any]:
        if resource_kind not in {"task", "thread", "lifecycle"}:
            raise HostUnavailable(
                "Unsupported Codex app-server resource readback kind"
            )
        self.preflight()
        if resource_kind == "lifecycle":
            self._lifecycle_read_count += 1
        with self._session() as session:
            try:
                thread = session.request(
                    "thread/read",
                    {"includeTurns": True, "threadId": provider_id},
                ).get("thread")
            except HostUnavailable:
                return self._resource(resource_kind, provider_id, "NOT_FOUND", "none")
        if not isinstance(thread, Mapping) or thread.get("id") != provider_id:
            return self._resource(resource_kind, provider_id, "NOT_FOUND", "none")
        status = thread.get("status")
        if not isinstance(status, Mapping) or status.get("type") not in {
            "active",
            "idle",
            "notLoaded",
            "systemError",
        }:
            raise HostUnavailable("Codex thread status schema drift")
        state = {
            "active": "ACTIVE",
            "idle": "TERMINAL",
            "notLoaded": "PAUSED",
            "systemError": "TERMINAL",
        }[status["type"]]
        return self._resource(resource_kind, provider_id, state, "authoritative")

    def read_task_result(self, provider_id: str) -> Mapping[str, Any]:
        self.preflight()
        self._task_result_read_count += 1
        with self._session() as session:
            thread = session.request(
                "thread/read", {"includeTurns": True, "threadId": provider_id}
            ).get("thread")
        if not isinstance(thread, Mapping) or thread.get("id") != provider_id:
            raise HostUnavailable("Codex task result identity mismatch")
        records = [
            record
            for record in self._records.values()
            if record.get("thread_id") == provider_id
        ]
        if len(records) > 1:
            raise HostUnavailable("Codex task result identity is ambiguous")
        if records:
            record = records[0]
            marker = record["marker"]
            expected_turn_id = record["turn_id"]
        else:
            preview = thread.get("preview")
            markers = _MACHINE_MARKER.findall(preview) if isinstance(preview, str) else []
            if len(markers) != 1:
                raise HostUnavailable("Codex task result marker identity mismatch")
            marker = markers[0]
            expected_turn_id = ""
        self._validate_thread(thread, marker)
        binding = records[0] if records else {"turn_id": expected_turn_id}
        selected = self._bound_turn(
            thread,
            binding,
            label="Codex task result turn",
        )
        if selected is None:
            status, text = "PENDING", ""
        else:
            if selected.get("status") not in {
                "completed",
                "failed",
                "inProgress",
                "interrupted",
            }:
                raise HostUnavailable("Codex task result status drift")
            texts = [
                item["text"]
                for item in selected.get("items", [])
                if isinstance(item, Mapping)
                and item.get("type") == "agentMessage"
                and isinstance(item.get("text"), str)
            ]
            text = "\n".join(texts).strip()
            status = {
                "completed": "COMPLETED",
                "failed": "FAILED",
                "interrupted": "FAILED",
                "inProgress": "PENDING",
            }[selected["status"]]
        from loop_architect.v4_alpha.protocol import domain_digest

        return {
            "provider_id": provider_id,
            "result_digest": domain_digest("loopskill-host-result-v1\n", text),
            "result_text": text,
            "schema_version": HOST_SCHEMA_VERSION,
            "status": status,
            "trust": "authoritative",
        }

    def wait_for_terminal(
        self,
        *,
        timeout_seconds: float = 300.0,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        """Wait read-only for the one machine-created turn; never resend/create."""

        self.preflight()
        if (
            timeout_seconds <= 0
            or timeout_seconds > 600
            or poll_interval_seconds <= 0
            or poll_interval_seconds > 5
        ):
            raise ValueError("invalid terminal wait bound")
        if len(self._records) != 1:
            raise HostUnavailable("Codex terminal wait task identity is unavailable")
        record = next(iter(self._records.values()))
        thread_id = record["thread_id"]
        marker = record["marker"]
        deadline = self._monotonic() + timeout_seconds
        session = self._active_session
        if session is None:
            session = self._open_session()
            self._active_session = session
        try:
            while True:
                if self._monotonic() >= deadline:
                    raise HostUnavailable("Codex task terminal wait timed out")
                self._terminal_wait_read_count += 1
                response = session.request(
                    "thread/read",
                    {"includeTurns": True, "threadId": thread_id},
                )
                thread = response.get("thread")
                if not isinstance(thread, Mapping) or thread.get("id") != thread_id:
                    raise HostUnavailable("Codex terminal wait identity mismatch")
                self._validate_thread(thread, marker)
                turn = self._bound_turn(
                    thread,
                    record,
                    label="Codex terminal wait turn",
                )
                if turn is not None:
                    status = turn.get("status")
                    if status in {"completed", "failed", "interrupted"}:
                        return
                    if status != "inProgress":
                        raise HostUnavailable("Codex terminal wait status drift")
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    raise HostUnavailable("Codex task terminal wait timed out")
                self._sleeper(min(poll_interval_seconds, remaining))
        finally:
            self.close()

    @staticmethod
    def _bound_turn(
        thread: Mapping[str, Any],
        binding: dict[str, str],
        *,
        label: str,
    ) -> Mapping[str, Any] | None:
        turns = thread.get("turns")
        if not isinstance(turns, list):
            raise HostUnavailable(f"{label} schema drift")
        for turn in turns:
            if (
                not isinstance(turn, Mapping)
                or not isinstance(turn.get("id"), str)
                or not turn["id"]
            ):
                raise HostUnavailable(f"{label} schema drift")
        expected_turn_id = binding.get("turn_id", "")
        if expected_turn_id:
            matches = [turn for turn in turns if turn["id"] == expected_turn_id]
            if len(matches) > 1:
                raise HostUnavailable(f"{label} identity is ambiguous")
            if not matches and turns:
                raise HostUnavailable(f"{label} identity mismatch")
            return matches[0] if matches else None
        if len(turns) > 1:
            raise HostUnavailable(f"{label} identity is ambiguous")
        selected = turns[0] if turns else None
        if selected is not None:
            binding["turn_id"] = selected["id"]
        return selected

    @staticmethod
    def _prompt(payload: Mapping[str, Any], marker: str) -> str:
        document = {
            "acceptance_criteria": list(payload["acceptance_criteria"]),
            "authorization_boundaries": list(payload["authorization_boundaries"]),
            "budget": payload["budget"],
            "execution_mode": payload["execution_mode"],
            "external_actions": list(payload["external_actions"]),
            "goal": payload["goal"],
            "stop_conditions": list(payload["stop_conditions"]),
            "write_scope": list(payload["write_scope"]),
        }
        prompt = (
            "LoopSkill 4 machine-started task. Treat the following JSON as the confirmed "
            "semantic boundary; do not broaden it. The request marker is correlation-only "
            "and grants no authority.\n"
            + marker
            + "\n"
            + canonical_bytes(document).decode("utf-8")
            + "\nWhen finished, end with exactly one semantic line: "
            'LOOPSKILL4_RESULT={"outcome":"PASS|FAILED|LIMITATION|UNVERIFIABLE",'
            '"summary":"concise UTF-8 summary"}. Do not include control identities.'
        )
        if len(prompt.encode("utf-8")) > MAX_HOST_PROMPT_BYTES:
            raise HostUnavailable("Confirmed Host request exceeds 32 KiB")
        return prompt

    @staticmethod
    def _response_identity(
        response: Mapping[str, Any], path: tuple[str, ...], method: str
    ) -> str:
        value: Any = response
        for element in path:
            if not isinstance(value, Mapping) or element not in value:
                raise HostUnavailable(f"Codex {method} schema drift")
            value = value[element]
        if not isinstance(value, str) or not value:
            raise HostUnavailable(f"Codex {method} schema drift")
        return value

    @staticmethod
    def _validate_thread(thread: Mapping[str, Any], marker: str) -> None:
        preview = thread.get("preview")
        if (
            not isinstance(thread.get("id"), str)
            or not thread["id"]
            or not isinstance(preview, str)
            or _MACHINE_MARKER.findall(preview) != [marker]
        ):
            raise HostUnavailable("Codex authoritative readback identity mismatch")
        status = thread.get("status")
        if not isinstance(status, Mapping) or status.get("type") not in {
            "active",
            "idle",
            "notLoaded",
            "systemError",
        }:
            raise HostUnavailable("Codex authoritative readback status drift")

    @staticmethod
    def _observation(
        action: str,
        provider_key: str,
        thread_id: str,
        marker: str,
        status: str,
        trust: str,
    ) -> Mapping[str, Any]:
        return {
            "action": action,
            "idempotency_key": provider_key,
            "provider_id": thread_id,
            "schema_version": HOST_SCHEMA_VERSION,
            "status": status,
            "subject_id": hashlib.sha256(marker.encode()).hexdigest(),
            "trust": trust,
        }

    @staticmethod
    def _resource(
        resource_kind: str, provider_id: str, state: str, trust: str
    ) -> Mapping[str, Any]:
        return {
            "provider_id": provider_id,
            "resource_kind": resource_kind,
            "schema_version": HOST_SCHEMA_VERSION,
            "state": state,
            "trust": trust,
        }
