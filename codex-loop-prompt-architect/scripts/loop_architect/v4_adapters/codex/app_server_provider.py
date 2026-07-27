"""Production Codex app-server provider for the v4 Host Adapter port.

The provider owns Host-specific JSON-RPC literals.  It never writes the
canonical LoopSkill store and never retries a create.  Recovery performs only
authoritative readback by a machine-derived request marker.
"""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import shutil
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from loop_architect.v4_alpha.protocol import CAPABILITY_NAMES, canonical_bytes

from .adapter import HOST_SCHEMA_VERSION, HostResponseLost, HostUnavailable


APP_SERVER_PROTOCOL = "codex-app-server-v2"
MAX_HOST_FRAME_BYTES = 1_048_576
MAX_HOST_PROMPT_BYTES = 32 * 1024


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _request_marker(provider_key: str) -> str:
    digest = hashlib.sha256(
        b"loopskill-app-server-request-v1\n" + provider_key.encode("utf-8")
    ).hexdigest()
    return f"LOOPSKILL4_REQUEST={digest}"


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
        self._next_id = 1
        self._initialize()

    def _write(self, value: Mapping[str, Any]) -> None:
        raw = canonical_bytes(value) + b"\n"
        if len(raw) > MAX_HOST_FRAME_BYTES:
            raise HostUnavailable("Codex app-server request exceeds the frame bound")
        try:
            assert self._process.stdin is not None
            self._process.stdin.write(raw)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise HostResponseLost("Codex app-server response channel was lost") from exc

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
                ready = selector.select(max(0.0, deadline - time.monotonic()))
                if not ready:
                    break
                raw = self._process.stdout.readline(MAX_HOST_FRAME_BYTES + 1)
                if not raw:
                    raise HostResponseLost("Codex app-server closed before response")
                if len(raw) > MAX_HOST_FRAME_BYTES or not raw.endswith(b"\n"):
                    raise HostUnavailable("Codex app-server frame bound/schema drift")
                try:
                    message = json.loads(raw.decode("utf-8", "strict"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise HostUnavailable("Codex app-server returned invalid JSON") from exc
                if not isinstance(message, Mapping):
                    raise HostUnavailable("Codex app-server response schema drift")
                if message.get("id") != request_id:
                    if "id" in message and "method" in message:
                        raise HostUnavailable(
                            "Codex app-server requested unsupported interactive input"
                        )
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
        if process.stdin is not None and not process.stdin.closed:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


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
    ) -> None:
        resolved = Path(workspace).resolve(strict=True)
        if not resolved.is_dir() or resolved.is_symlink():
            raise ValueError("Host workspace must be one existing directory")
        executable = shutil.which("codex") if command is None else None
        selected = tuple(command or ((executable or "codex"), "app-server", "--stdio"))
        if not selected:
            raise ValueError("Codex app-server command is empty")
        self.workspace = resolved
        self.command = selected
        self.issuer_ref = issuer_ref
        self.issuer_trust = issuer_trust
        self.clock = clock
        self.timeout_seconds = timeout_seconds
        self._records: dict[str, dict[str, str]] = {}

    @contextmanager
    def _session(self) -> Iterator[_AppServerSession]:
        session = _AppServerSession(self.command, timeout_seconds=self.timeout_seconds)
        try:
            yield session
        finally:
            session.close()

    def capability_snapshot(self) -> Mapping[str, Any]:
        now = self.clock().astimezone(timezone.utc)
        observed = now - timedelta(seconds=1)
        available_strict = {
            "task_create",
            "thread_create",
            "resource_read",
            "message_send",
            "eventual_indexing",
            "lifecycle_readback",
            "sandbox_receipt",
            "trust_receipt",
            "model_receipt",
        }
        unavailable = {
            "project_registration",
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
        marker = _request_marker(provider_idempotency_key)
        prompt = self._prompt(payload, marker)
        try:
            with self._session() as session:
                started = session.request(
                    "thread/start",
                    {
                        "approvalPolicy": "on-request",
                        "cwd": str(self.workspace),
                        "ephemeral": False,
                        "sandbox": "workspace-write",
                        "threadSource": "loopskill4",
                    },
                )
                thread = started.get("thread")
                if not isinstance(thread, Mapping) or not isinstance(thread.get("id"), str):
                    raise HostUnavailable("Codex thread/start schema drift")
                thread_id = thread["id"]
                turn = session.request(
                    "turn/start",
                    {
                        "clientUserMessageId": provider_idempotency_key,
                        "cwd": str(self.workspace),
                        "input": [{"text": prompt, "type": "text"}],
                        "threadId": thread_id,
                    },
                ).get("turn")
                if not isinstance(turn, Mapping) or not isinstance(turn.get("id"), str):
                    raise HostUnavailable("Codex turn/start schema drift")
        except HostUnavailable:
            raise
        except HostResponseLost:
            raise
        self._records[provider_idempotency_key] = {
            "marker": marker,
            "target_ref": str(payload["target_ref"]),
            "thread_id": thread_id,
        }
        return self._observation(
            action, provider_idempotency_key, thread_id, marker, "ACCEPTED", "cooperative"
        )

    def readback(
        self, action: str, provider_idempotency_key: str
    ) -> Mapping[str, Any] | None:
        if action != "create_task":
            return None
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
                listed = session.request(
                    "thread/list",
                    {
                        "archived": False,
                        "cwd": str(self.workspace),
                        "limit": 100,
                        "useStateDbOnly": True,
                    },
                ).get("data")
                if not isinstance(listed, list):
                    raise HostUnavailable("Codex thread/list schema drift")
                matches = [
                    item
                    for item in listed
                    if isinstance(item, Mapping)
                    and marker in str(item.get("preview", ""))
                ]
                if len(matches) > 1:
                    raise HostUnavailable("Codex readback identity is ambiguous")
                thread = matches[0] if matches else None
            if thread is None:
                return None
            self._validate_thread(thread, marker)
            thread_id = str(thread["id"])
        return self._observation(
            action, provider_idempotency_key, thread_id, marker, "OBSERVED", "authoritative"
        )

    def read_resource(self, resource_kind: str, provider_id: str) -> Mapping[str, Any]:
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
        )
        if len(prompt.encode("utf-8")) > MAX_HOST_PROMPT_BYTES:
            raise HostUnavailable("Confirmed Host request exceeds 32 KiB")
        return prompt

    @staticmethod
    def _validate_thread(thread: Mapping[str, Any], marker: str) -> None:
        if not isinstance(thread.get("id"), str) or marker not in str(
            thread.get("preview", "")
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
