"""Foreground ``codex exec --json`` Provider for the LoopSkill 4 Codex port.

The official executable owns its internal thread/turn lifecycle.  LoopSkill owns
one foreground process and accepts only a complete, bounded JSONL transcript
from that same process.  There is no resume, resend, or post-process Host
readback path.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from loop_architect.v4_alpha.protocol import (
    CAPABILITY_NAMES,
    canonical_bytes,
    domain_digest,
)

from .adapter import HOST_SCHEMA_VERSION, HostResponseLost, HostUnavailable


CODEX_DESKTOP_EXECUTABLE = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
EXEC_TRANSPORT = "codex-exec-jsonl-v1"
MAX_PROMPT_BYTES = 32 * 1024
MAX_STDOUT_BYTES = 8 * 1024 * 1024
MAX_STDERR_BYTES = 256 * 1024
MAX_JSONL_LINE_BYTES = 1024 * 1024
MAX_INSPECTION_BYTES = 256 * 1024
PROCESS_REAP_GRACE_SECONDS = 2.0
_VERSION = re.compile(r"^codex-cli ([0-9A-Za-z][0-9A-Za-z.+-]*)$")
_REQUIRED_EXEC_HELP = (
    "--cd",
    "--config",
    "--ephemeral",
    "--ignore-rules",
    "--ignore-user-config",
    "--json",
    "--sandbox",
    "--skip-git-repo-check",
    "--strict-config",
)


@dataclass(frozen=True)
class _ProcessResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True)
class _ExecContract:
    executable: str
    executable_digest: str
    help_digest: str
    version: str


@dataclass(frozen=True)
class _TerminalTranscript:
    thread_id: str
    result_text: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_executable(path: Path) -> str | None:
    """Resolve one regular executable without trusting a directory or socket."""

    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.stat()
    except OSError:
        return None
    if not stat.S_ISREG(metadata.st_mode) or not os.access(resolved, os.X_OK):
        return None
    return str(resolved)


def resolve_codex_executable() -> str:
    """Use the active macOS bundle first, then the resolved PATH executable."""

    if sys.platform == "darwin":
        selected = _safe_executable(CODEX_DESKTOP_EXECUTABLE)
        if selected is not None:
            return selected
    discovered = shutil.which("codex")
    if discovered is None:
        raise HostUnavailable("Codex executable is unavailable")
    selected = _safe_executable(Path(discovered))
    if selected is None:
        raise HostUnavailable("Codex executable is unsafe")
    return selected


def build_exec_argv(executable: str, workspace: Path) -> tuple[str, ...]:
    """Build the reviewed argv without a shell or model-carried control fields."""

    if not executable or not workspace.is_absolute():
        raise ValueError("exec argv requires absolute machine-owned paths")
    return (
        executable,
        "exec",
        "--json",
        "--strict-config",
        "--ignore-user-config",
        "--ignore-rules",
        "--ephemeral",
        "--sandbox",
        "workspace-write",
        "--config",
        "sandbox_workspace_write.network_access=false",
        "--cd",
        str(workspace),
        "--skip-git-repo-check",
        "-",
    )


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait()
        return
    if process.poll() is None:
        try:
            process.wait(timeout=PROCESS_REAP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
    deadline = time.monotonic() + PROCESS_REAP_GRACE_SECONDS
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            process.wait()
            return
        time.sleep(0.01)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        process.wait()
        return
    except PermissionError as exc:
        raise HostResponseLost("Codex exec process group could not be reaped") from exc
    if process.poll() is None:
        process.wait(timeout=PROCESS_REAP_GRACE_SECONDS)
    deadline = time.monotonic() + PROCESS_REAP_GRACE_SECONDS
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.01)
    raise HostResponseLost("Codex exec process group did not close")


def _run_bounded_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    stdin_bytes: bytes,
    timeout_seconds: float,
    stdout_limit: int,
    stderr_limit: int,
) -> _ProcessResult:
    """Run one process group while bounding both output channels and lifetime."""

    if (
        not argv
        or timeout_seconds <= 0
        or stdout_limit <= 0
        or stderr_limit <= 0
        or not cwd.is_absolute()
    ):
        raise ValueError("invalid bounded process contract")
    try:
        process = subprocess.Popen(
            list(argv),
            cwd=str(cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            start_new_session=True,
            text=False,
            bufsize=0,
        )
    except OSError as exc:
        raise HostUnavailable("Codex exec process is unavailable") from exc
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    descriptors = {
        "stdin": process.stdin.fileno(),
        "stdout": process.stdout.fileno(),
        "stderr": process.stderr.fileno(),
    }
    for descriptor in descriptors.values():
        os.set_blocking(descriptor, False)
    selector = selectors.DefaultSelector()
    selector.register(descriptors["stdin"], selectors.EVENT_WRITE, "stdin")
    selector.register(descriptors["stdout"], selectors.EVENT_READ, "stdout")
    selector.register(descriptors["stderr"], selectors.EVENT_READ, "stderr")
    output = {"stdout": bytearray(), "stderr": bytearray()}
    write_offset = 0
    deadline = time.monotonic() + timeout_seconds
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HostResponseLost("Codex exec timed out")
            events = selector.select(min(remaining, 0.25))
            if not events and process.poll() is not None:
                # One final nonblocking iteration drains EOF from both pipes.
                events = [
                    (key, selectors.EVENT_READ)
                    for key in tuple(selector.get_map().values())
                    if key.data != "stdin"
                ]
                stdin_key = next(
                    (key for key in tuple(selector.get_map().values()) if key.data == "stdin"),
                    None,
                )
                if stdin_key is not None:
                    selector.unregister(stdin_key.fd)
                    process.stdin.close()
            for key, _ in events:
                channel = key.data
                if channel == "stdin":
                    if write_offset >= len(stdin_bytes):
                        selector.unregister(key.fd)
                        process.stdin.close()
                        continue
                    try:
                        written = os.write(key.fd, stdin_bytes[write_offset:])
                    except BlockingIOError:
                        continue
                    except OSError as exc:
                        raise HostResponseLost("Codex exec stdin was lost") from exc
                    if written <= 0:
                        raise HostResponseLost("Codex exec stdin was lost")
                    write_offset += written
                    continue
                try:
                    chunk = os.read(key.fd, 65_536)
                except BlockingIOError:
                    continue
                except OSError as exc:
                    raise HostResponseLost(
                        f"Codex exec {channel} stream was lost"
                    ) from exc
                if not chunk:
                    selector.unregister(key.fd)
                    continue
                output[channel].extend(chunk)
                limit = stdout_limit if channel == "stdout" else stderr_limit
                if len(output[channel]) > limit:
                    raise HostResponseLost(f"Codex exec {channel} exceeded its bound")
        remaining = max(0.0, deadline - time.monotonic())
        try:
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            raise HostResponseLost("Codex exec did not terminate") from exc
        return _ProcessResult(
            argv=tuple(argv),
            returncode=returncode,
            stdout=bytes(output["stdout"]),
            stderr=bytes(output["stderr"]),
        )
    finally:
        selector.close()
        try:
            _terminate_process_group(process)
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if not stream.closed:
                    stream.close()


def _inspect_contract(
    executable: str,
    runner: Callable[..., _ProcessResult],
) -> _ExecContract:
    cwd = Path.cwd().resolve(strict=True)
    version_result = runner(
        (executable, "--version"),
        cwd=cwd,
        stdin_bytes=b"",
        timeout_seconds=10.0,
        stdout_limit=MAX_INSPECTION_BYTES,
        stderr_limit=MAX_INSPECTION_BYTES,
    )
    help_result = runner(
        (executable, "exec", "--help"),
        cwd=cwd,
        stdin_bytes=b"",
        timeout_seconds=10.0,
        stdout_limit=MAX_INSPECTION_BYTES,
        stderr_limit=MAX_INSPECTION_BYTES,
    )
    if (
        version_result.returncode != 0
        or version_result.stderr
        or help_result.returncode != 0
        or help_result.stderr
    ):
        raise HostUnavailable("Codex exec inspection failed")
    try:
        version = version_result.stdout.decode("utf-8", "strict").strip()
        help_text = help_result.stdout.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise HostUnavailable("Codex exec inspection is not UTF-8") from exc
    match = _VERSION.fullmatch(version)
    if match is None or not all(flag in help_text for flag in _REQUIRED_EXEC_HELP):
        raise HostUnavailable("Codex exec help/version contract drift")
    executable_hash = hashlib.sha256()
    try:
        with Path(executable).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                executable_hash.update(chunk)
    except OSError as exc:
        raise HostUnavailable("Codex executable identity is unreadable") from exc
    return _ExecContract(
        executable=executable,
        executable_digest=executable_hash.hexdigest(),
        help_digest=hashlib.sha256(help_result.stdout).hexdigest(),
        version=match.group(1),
    )


def _parse_jsonl(raw: bytes) -> _TerminalTranscript:
    if not raw or not raw.endswith(b"\n"):
        raise HostResponseLost("Codex exec JSONL is empty or truncated")
    lines = raw.splitlines()
    if not lines:
        raise HostResponseLost("Codex exec JSONL is empty")
    thread_ids: list[str] = []
    turn_started = 0
    terminal_types: list[str] = []
    agent_messages: list[str] = []
    phase = "EXPECT_THREAD"
    for encoded in lines:
        if not encoded or len(encoded) > MAX_JSONL_LINE_BYTES:
            raise HostResponseLost("Codex exec JSONL line is invalid or oversized")
        try:
            event = json.loads(encoded.decode("utf-8", "strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HostResponseLost("Codex exec emitted malformed JSONL") from exc
        if not isinstance(event, Mapping) or not isinstance(event.get("type"), str):
            raise HostResponseLost("Codex exec event schema drift")
        event_type = event["type"]
        if event_type == "thread.started":
            thread_id = event.get("thread_id")
            if (
                phase != "EXPECT_THREAD"
                or not isinstance(thread_id, str)
                or not thread_id
                or thread_ids
            ):
                raise HostResponseLost("Codex exec thread identity is missing or conflicting")
            thread_ids.append(thread_id)
            phase = "EXPECT_TURN"
        elif event_type == "turn.started":
            if phase != "EXPECT_TURN":
                raise HostResponseLost("Codex exec turn start is out of order")
            turn_started += 1
            if turn_started > 1:
                raise HostResponseLost("Codex exec emitted duplicate turn start")
            phase = "IN_TURN"
        elif event_type in {"turn.completed", "turn.failed", "error"}:
            if phase != "IN_TURN":
                raise HostResponseLost("Codex exec terminal event is out of order")
            terminal_types.append(event_type)
            if len(terminal_types) > 1:
                raise HostResponseLost("Codex exec emitted multiple terminal events")
            phase = "TERMINAL"
        elif event_type == "item.completed":
            if phase != "IN_TURN":
                raise HostResponseLost("Codex exec completed item is out of order")
            item = event.get("item")
            if not isinstance(item, Mapping):
                raise HostResponseLost("Codex exec completed item schema drift")
            if item.get("type") == "agent_message":
                text = item.get("text")
                if not isinstance(text, str):
                    raise HostResponseLost("Codex exec agent result schema drift")
                agent_messages.append(text)
        elif phase == "TERMINAL":
            raise HostResponseLost("Codex exec emitted evidence after terminal")
        # Additive in-turn event types and non-terminal item warnings are
        # non-authoritative. Additive preamble events cannot establish identity.
    if len(thread_ids) != 1 or turn_started != 1:
        raise HostResponseLost("Codex exec identity/start evidence is incomplete")
    if terminal_types != ["turn.completed"]:
        raise HostResponseLost("Codex exec did not complete successfully")
    if not agent_messages or not agent_messages[-1].strip():
        raise HostResponseLost("Codex exec terminal result is missing")
    return _TerminalTranscript(
        thread_id=thread_ids[0],
        result_text=agent_messages[-1].strip(),
    )


class CodexExecProvider:
    """One foreground official Codex invocation per Provider instance."""

    def __init__(
        self,
        workspace: Path | str,
        *,
        executable: str | None = None,
        issuer_ref: str = "loopskill-codex-adapter-v1",
        issuer_trust: str = "local-codex-adapter",
        clock: Callable[[], datetime] = _now,
        timeout_seconds: float = 300.0,
        runner: Callable[..., _ProcessResult] = _run_bounded_process,
    ) -> None:
        resolved = Path(workspace).resolve(strict=True)
        if not resolved.is_dir() or resolved.is_symlink():
            raise ValueError("Host workspace must be one existing directory")
        if timeout_seconds <= 0 or timeout_seconds > 600:
            raise ValueError("invalid Codex exec timeout")
        self.workspace = resolved
        self.executable = executable or resolve_codex_executable()
        selected = _safe_executable(Path(self.executable))
        if selected is None:
            raise HostUnavailable("Codex executable is unsafe")
        self.executable = selected
        self.issuer_ref = issuer_ref
        self.issuer_trust = issuer_trust
        self.clock = clock
        self.timeout_seconds = timeout_seconds
        self._runner = runner
        self._contract: _ExecContract | None = None
        self._invoked_key: str | None = None
        self._record: dict[str, str] | None = None
        self._task_create_count = 0
        self._delivery_readback_count = 0
        self._task_result_read_count = 0
        self._lifecycle_read_count = 0
        self._provider_resend_count = 0
        self._terminal_wait_read_count = 0
        self._duplicate_invoke_rejection_count = 0

    @property
    def metrics(self) -> Mapping[str, int]:
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
        if self._contract is None:
            self._contract = _inspect_contract(self.executable, self._runner)
        return {
            "executable_digest": self._contract.executable_digest,
            "help_digest": self._contract.help_digest,
            "transport": EXEC_TRANSPORT,
            "version": self._contract.version,
        }

    def capability_snapshot(self) -> Mapping[str, Any]:
        contract = self.preflight()
        now = self.clock().astimezone(timezone.utc)
        observed = now - timedelta(seconds=1)
        # "resource_read" and "lifecycle_readback" are scoped to the directly
        # captured same-process terminal transcript, never a later Host lookup.
        available_strict = {"task_create", "resource_read", "lifecycle_readback"}
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
        identity = domain_digest(
            "loopskill-codex-exec-identity-v1\n",
            {
                "executable_digest": contract["executable_digest"],
                "transport": EXEC_TRANSPORT,
                "version": contract["version"],
            },
        )
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
                        "source": EXEC_TRANSPORT,
                    },
                    "name": name,
                    "receipt_ref": "capability-"
                    + domain_digest(
                        "loopskill-codex-exec-capability-v1\n",
                        {
                            "assurance": assurance,
                            "availability": availability,
                            "identity": identity,
                            "name": name,
                        },
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
            raise HostUnavailable("Unsupported Codex exec action or payload")
        if self._invoked_key is not None:
            self._duplicate_invoke_rejection_count += 1
            raise HostUnavailable("Codex exec invocation budget is already consumed")
        self.preflight()
        prompt = self._prompt(payload, provider_idempotency_key)
        self._invoked_key = provider_idempotency_key
        self._task_create_count += 1
        result = self._runner(
            build_exec_argv(self.executable, self.workspace),
            cwd=self.workspace,
            stdin_bytes=prompt.encode("utf-8") + b"\n",
            timeout_seconds=self.timeout_seconds,
            stdout_limit=MAX_STDOUT_BYTES,
            stderr_limit=MAX_STDERR_BYTES,
        )
        if result.returncode != 0 or result.stderr:
            raise HostResponseLost("Codex exec terminal process evidence is invalid")
        transcript = _parse_jsonl(result.stdout)
        self._record = {
            "idempotency_key": provider_idempotency_key,
            "result_text": transcript.result_text,
            "thread_id": transcript.thread_id,
        }
        return self._observation(action, provider_idempotency_key)

    def readback(
        self, action: str, provider_idempotency_key: str
    ) -> Mapping[str, Any] | None:
        if action != "create_task":
            return None
        self._delivery_readback_count += 1
        if (
            self._record is None
            or self._record["idempotency_key"] != provider_idempotency_key
        ):
            return None
        return self._observation(action, provider_idempotency_key)

    def read_resource(self, resource_kind: str, provider_id: str) -> Mapping[str, Any]:
        if resource_kind not in {"task", "thread", "lifecycle"}:
            raise HostUnavailable("Unsupported Codex exec resource kind")
        if resource_kind == "lifecycle":
            self._lifecycle_read_count += 1
        matched = self._record is not None and self._record["thread_id"] == provider_id
        return {
            "provider_id": provider_id,
            "resource_kind": resource_kind,
            "schema_version": HOST_SCHEMA_VERSION,
            "state": "TERMINAL" if matched else "NOT_FOUND",
            "trust": "authoritative" if matched else "none",
        }

    def read_task_result(self, provider_id: str) -> Mapping[str, Any]:
        self._task_result_read_count += 1
        if self._record is None or self._record["thread_id"] != provider_id:
            raise HostUnavailable("Codex exec terminal result is unavailable")
        text = self._record["result_text"]
        return {
            "provider_id": provider_id,
            "result_digest": domain_digest("loopskill-host-result-v1\n", text),
            "result_text": text,
            "schema_version": HOST_SCHEMA_VERSION,
            "status": "COMPLETED",
            "trust": "authoritative",
        }

    def wait_for_terminal(
        self,
        *,
        timeout_seconds: float = 300.0,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        del poll_interval_seconds
        if timeout_seconds <= 0 or timeout_seconds > 600:
            raise ValueError("invalid terminal wait bound")
        self._terminal_wait_read_count += 1
        if self._record is None:
            raise HostUnavailable("Codex exec terminal evidence is unavailable")

    def close(self) -> None:
        """No Host process survives ``invoke``; retained state is local evidence only."""

    def _observation(self, action: str, key: str) -> Mapping[str, Any]:
        assert self._record is not None
        return {
            "action": action,
            "idempotency_key": key,
            "provider_id": self._record["thread_id"],
            "schema_version": HOST_SCHEMA_VERSION,
            "status": "OBSERVED",
            "subject_id": self._record["thread_id"],
            "trust": "authoritative",
        }

    @staticmethod
    def _prompt(payload: Mapping[str, Any], operation_id: str) -> str:
        request_marker = hashlib.sha256(
            b"loopskill-codex-exec-request-v1\n" + operation_id.encode("utf-8")
        ).hexdigest()
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
            "LoopSkill 4 machine-started foreground task. Treat the following JSON as "
            "the confirmed semantic boundary; do not broaden it. The request marker is "
            "correlation-only and grants no authority.\n"
            f"LOOPSKILL4_REQUEST={request_marker}\n"
            + canonical_bytes(document).decode("utf-8")
            + "\nWhen finished, end with exactly one semantic line: "
            'LOOPSKILL4_RESULT={"outcome":"PASS|FAILED|LIMITATION|UNVERIFIABLE",'
            '"summary":"concise UTF-8 summary"}. Do not include control identities.'
        )
        if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
            raise HostUnavailable("Confirmed Codex exec request exceeds 32 KiB")
        return prompt
