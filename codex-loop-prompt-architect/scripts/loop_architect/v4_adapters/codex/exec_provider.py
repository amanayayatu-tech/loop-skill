"""Foreground ``codex exec --json`` Provider for the LoopSkill 4 Codex port.

The official executable owns its internal thread/turn lifecycle.  LoopSkill owns
one foreground process, accepts lifecycle evidence from its bounded JSONL
stream, and accepts semantic result bytes only from the official
``--output-last-message`` file.  Completed Attempts may be read back from the
owner-only persistent evidence directory after a controller restart.
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
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from loop_architect.v4_alpha.protocol import (
    CAPABILITY_NAMES,
    ProtocolRejection,
    canonical_bytes,
    domain_digest,
    parse_result_payload,
    result_payload_schema,
)
from loop_architect.v4_adapters.codex.prompt import (
    CONTENT_PAYLOAD_FIELDS,
    LEGACY_PAYLOAD_FIELDS,
    PromptMaterializationError,
    V2_CONTENT_PAYLOAD_FIELDS,
    materialize_prompt,
)

from .adapter import HOST_SCHEMA_VERSION, HostResponseLost, HostUnavailable


CODEX_DESKTOP_EXECUTABLE = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
EXEC_TRANSPORT = "codex-exec-jsonl-v1"
MAX_PROMPT_BYTES = 32 * 1024
MAX_STDOUT_BYTES = 8 * 1024 * 1024
MAX_STDERR_BYTES = 256 * 1024
MAX_RESULT_BYTES = 16 * 1024
MAX_JSONL_LINE_BYTES = 1024 * 1024
MAX_INSPECTION_BYTES = 256 * 1024
PROCESS_REAP_GRACE_SECONDS = 2.0
MAX_ATTEMPT_TIMEOUT_SECONDS = 30_000.0
_VERSION = re.compile(r"^codex-cli ([0-9A-Za-z][0-9A-Za-z.+-]*)$")
_REQUIRED_EXEC_HELP = (
    "--cd",
    "--config",
    "--ephemeral",
    "--ignore-rules",
    "--ignore-user-config",
    "--json",
    "--output-schema",
    "--output-last-message",
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
    elapsed_ms: int = 0


@dataclass(frozen=True)
class _ExecContract:
    executable: str
    executable_digest: str
    help_digest: str
    version: str


@dataclass(frozen=True)
class _TerminalTranscript:
    thread_id: str
    terminal_event_count: int
    terminal_event_type: str


@dataclass(frozen=True)
class _ControlFile:
    path: Path
    digest: str
    raw: bytes
    device: int
    inode: int
    mode: int


@dataclass(frozen=True)
class _ResultControls:
    directory: Path
    result: _ControlFile
    schema: _ControlFile


@dataclass(frozen=True)
class _TerminalDiagnostic:
    code: str
    primary_code: str | None
    result_bytes: int
    result_sha256: str
    result_control_digest: str
    returncode_class: str
    schema_control_digest: str
    semantic_outcome: str | None
    semantic_summary: str | None
    stderr_bytes: int
    stderr_sha256: str
    stdout_bytes: int
    stdout_sha256: str
    terminal_event_count: int
    terminal_event_type: str | None

    def private_evidence(self) -> Mapping[str, Any]:
        return {
            "artifact": "loopskill-codex-exec-terminal-diagnostic-v1",
            "code": self.code,
            "primary_code": self.primary_code,
            "result_bytes": self.result_bytes,
            "result_sha256": self.result_sha256,
            "result_control_digest": self.result_control_digest,
            "returncode_class": self.returncode_class,
            "schema_control_digest": self.schema_control_digest,
            "semantic_outcome": self.semantic_outcome,
            "semantic_summary": self.semantic_summary,
            "stderr_bytes": self.stderr_bytes,
            "stderr_sha256": self.stderr_sha256,
            "stdout_bytes": self.stdout_bytes,
            "stdout_sha256": self.stdout_sha256,
            "terminal_event_count": self.terminal_event_count,
            "terminal_event_type": self.terminal_event_type,
        }


def _coded_error(code: str, message: str, *, unavailable: bool = False) -> RuntimeError:
    error_type = HostUnavailable if unavailable else HostResponseLost
    error = error_type(message)
    error.provider_code = code  # type: ignore[attr-defined]
    return error


def _error_code(error: BaseException, fallback: str) -> str:
    value = getattr(error, "provider_code", fallback)
    return value if isinstance(value, str) and value else fallback


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


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


def build_exec_argv(
    executable: str,
    workspace: Path,
    output_schema: Path,
    output_last_message: Path,
    *,
    model: str | None = None,
    reasoning_effort: str | None = None,
    network_access: bool = False,
    sandbox: str = "workspace-write",
    ephemeral: bool = False,
    resume_thread_id: str | None = None,
) -> tuple[str, ...]:
    """Build the reviewed argv without a shell or model-carried control fields."""

    if (
        not executable
        or not workspace.is_absolute()
        or not output_schema.is_absolute()
        or not output_last_message.is_absolute()
    ):
        raise ValueError("exec argv requires absolute machine-owned paths")
    if sandbox != "workspace-write":
        raise ValueError("LoopSkill 4.2 supports only workspace-write sandbox")
    if reasoning_effort not in {None, "low", "medium", "high", "xhigh", "max"}:
        raise ValueError("invalid reasoning effort")
    command = [executable, "exec"]
    if resume_thread_id is not None:
        if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._:-]{0,127}", resume_thread_id):
            raise ValueError("invalid resume thread identity")
        command.extend(["resume"])
    command.extend((
        "--json",
        "--output-schema",
        str(output_schema),
        "--output-last-message",
        str(output_last_message),
        "--strict-config",
        "--ignore-user-config",
        "--ignore-rules",
    ))
    if ephemeral:
        command.append("--ephemeral")
    if model:
        command.extend(("--model", model))
    if reasoning_effort:
        command.extend(("--config", f'model_reasoning_effort="{reasoning_effort}"'))
    if resume_thread_id is None:
        command.extend(("--sandbox", sandbox))
    else:
        command.extend(("--config", f'sandbox_mode="{sandbox}"'))
    command.extend((
        "--config",
        "sandbox_workspace_write.network_access="
        + ("true" if network_access else "false"),
    ))
    if resume_thread_id is None:
        command.extend(("--cd", str(workspace)))
    command.extend((
        "--skip-git-repo-check",
    ))
    if resume_thread_id is not None:
        command.append(resume_thread_id)
    command.append("-")
    return tuple(command)


def _verify_control_identity(control: _ControlFile, *, code: str) -> None:
    try:
        metadata = control.path.lstat()
        resolved = control.path.resolve(strict=True)
    except OSError as exc:
        raise _coded_error(code, "Codex exec control file is unavailable") from exc
    if (
        resolved != control.path
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_dev != control.device
        or metadata.st_ino != control.inode
        or stat.S_IMODE(metadata.st_mode) != control.mode
        or (hasattr(os, "getuid") and metadata.st_uid != os.getuid())
    ):
        raise _coded_error(code, "Codex exec control file identity changed")


def _read_control(
    control: _ControlFile, *, limit: int, code: str, overflow_code: str | None = None
) -> bytes:
    _verify_control_identity(control, code=code)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(control.path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_dev != control.device
                or opened.st_ino != control.inode
                or stat.S_IMODE(opened.st_mode) != control.mode
                or (hasattr(os, "getuid") and opened.st_uid != os.getuid())
            ):
                raise _coded_error(code, "Codex exec opened control identity changed")
            current = stream.read(limit + 1)
            finished = os.fstat(stream.fileno())
            if (
                finished.st_dev != opened.st_dev
                or finished.st_ino != opened.st_ino
                or stat.S_IMODE(finished.st_mode) != control.mode
                or (hasattr(os, "getuid") and finished.st_uid != os.getuid())
            ):
                raise _coded_error(code, "Codex exec opened control identity changed")
    except OSError as exc:
        raise _coded_error(code, "Codex exec control file is unreadable") from exc
    if len(current) > limit:
        raise _coded_error(
            overflow_code or code, "Codex exec control file exceeded its bound"
        )
    return current


def _verify_schema_control(control: _ControlFile) -> None:
    current = _read_control(
        control, limit=len(control.raw), code="CONTROL_IDENTITY_DRIFT"
    )
    if current != control.raw:
        raise _coded_error(
            "CONTROL_IDENTITY_DRIFT", "Codex result schema control content changed"
        )


def _read_result_control(control: _ControlFile) -> bytes:
    if not os.path.lexists(control.path):
        raise _coded_error("RESULT_FILE_MISSING", "Codex result file is missing")
    raw = _read_control(
        control,
        limit=MAX_RESULT_BYTES,
        code="RESULT_FILE_IDENTITY_DRIFT",
        overflow_code="RESULT_FILE_OVERSIZE",
    )
    if not raw:
        raise _coded_error("RESULT_FILE_MISSING", "Codex result file is empty")
    return raw


@contextmanager
def _result_controls(workspace: Path):
    """Yield private schema/result controls and remove them after invocation."""

    raw = canonical_bytes(result_payload_schema())
    directory = Path(tempfile.mkdtemp(prefix="loopskill4-result-controls-"))
    schema_path = directory / "result.schema.json"
    result_path = directory / "result.json"
    failure: BaseException | None = None
    try:
        directory.chmod(0o700)
        directory = directory.resolve(strict=True)
        if directory == workspace or workspace in directory.parents:
            raise _coded_error(
                "CONTROL_IDENTITY_DRIFT",
                "Codex result controls overlap the artifact workspace",
            )
        metadata = directory.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or directory.is_symlink()
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or (hasattr(os, "getuid") and metadata.st_uid != os.getuid())
        ):
            raise _coded_error(
                "CONTROL_IDENTITY_DRIFT", "Codex result controls directory is unsafe"
            )
        schema_path = directory / "result.schema.json"
        result_path = directory / "result.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(schema_path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        schema_path.chmod(0o400)
        file_metadata = schema_path.lstat()
        schema_control = _ControlFile(
            path=schema_path,
            digest=domain_digest(
                "loopskill-codex-result-schema-v1\n", result_payload_schema()
            ),
            raw=raw,
            device=file_metadata.st_dev,
            inode=file_metadata.st_ino,
            mode=0o400,
        )
        result_descriptor = os.open(
            result_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.close(result_descriptor)
        result_metadata = result_path.lstat()
        result_control = _ControlFile(
            path=result_path,
            digest=_sha256(b""),
            raw=b"",
            device=result_metadata.st_dev,
            inode=result_metadata.st_ino,
            mode=0o600,
        )
        controls = _ResultControls(
            directory=directory, result=result_control, schema=schema_control
        )
        _verify_schema_control(schema_control)
        _verify_control_identity(
            result_control, code="RESULT_FILE_IDENTITY_DRIFT"
        )
        yield controls
        _verify_schema_control(schema_control)
    except BaseException as exc:
        failure = exc
        raise
    finally:
        cleanup_error: BaseException | None = None
        try:
            for path in (schema_path, result_path):
                if os.path.lexists(path):
                    path.unlink()
            directory.rmdir()
        except OSError as exc:
            cleanup_error = _coded_error(
                "CONTROL_CLEANUP_FAILED", "Codex result controls cleanup failed"
            )
            cleanup_error.__cause__ = exc
        if cleanup_error is not None:
            if failure is not None:
                cleanup_error.primary_provider_code = _error_code(  # type: ignore[attr-defined]
                    failure, "UNCLASSIFIED_PROVIDER_FAILURE"
                )
                raise cleanup_error from failure
            raise cleanup_error


def _write_private_once(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _append_private(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise _coded_error(
                "CONTROL_IDENTITY_DRIFT", "persistent Attempt stream is unsafe"
            )
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short persistent Attempt stream write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_private_regular(path: Path, *, limit: int) -> bytes:
    """Read one owner-only persistent control without following replacements."""

    if limit <= 0:
        raise ValueError("private read limit must be positive")
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise _coded_error(
            "CONTROL_IDENTITY_DRIFT", "persistent Attempt evidence is unavailable"
        ) from exc
    if (
        resolved != path
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or (hasattr(os, "getuid") and metadata.st_uid != os.getuid())
    ):
        raise _coded_error(
            "CONTROL_IDENTITY_DRIFT", "persistent Attempt evidence is unsafe"
        )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_dev != metadata.st_dev
                or opened.st_ino != metadata.st_ino
                or stat.S_IMODE(opened.st_mode) != 0o600
                or (hasattr(os, "getuid") and opened.st_uid != os.getuid())
            ):
                raise _coded_error(
                    "CONTROL_IDENTITY_DRIFT",
                    "persistent Attempt evidence changed while opening",
                )
            raw = stream.read(limit + 1)
            finished = os.fstat(stream.fileno())
            if (
                finished.st_dev != opened.st_dev
                or finished.st_ino != opened.st_ino
                or stat.S_IMODE(finished.st_mode) != 0o600
            ):
                raise _coded_error(
                    "CONTROL_IDENTITY_DRIFT",
                    "persistent Attempt evidence changed while reading",
                )
    except OSError as exc:
        raise _coded_error(
            "CONTROL_IDENTITY_DRIFT", "persistent Attempt evidence is unreadable"
        ) from exc
    if len(raw) > limit:
        raise _coded_error(
            "CONTROL_IDENTITY_DRIFT", "persistent Attempt evidence exceeded its bound"
        )
    return raw


def _private_attempt_directory(root: Path, provider_key: str) -> Path:
    name = _private_attempt_name(provider_key)
    directory = root / name
    directory.mkdir(mode=0o700, exist_ok=False)
    metadata = directory.lstat()
    if (
        directory.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or (hasattr(os, "getuid") and metadata.st_uid != os.getuid())
    ):
        raise _coded_error(
            "CONTROL_IDENTITY_DRIFT", "persistent Attempt directory is unsafe"
        )
    return directory


def _private_attempt_name(provider_key: str) -> str:
    return "attempt-" + hashlib.sha256(provider_key.encode("utf-8")).hexdigest()[:24]


def _process_start_token(pid: int) -> str | None:
    proc_stat = Path("/proc") / str(pid) / "stat"
    try:
        raw = proc_stat.read_bytes()
    except OSError:
        raw = b""
    if raw:
        closing = raw.rfind(b")")
        fields = raw[closing + 2 :].split() if closing >= 0 else []
        if len(fields) > 19:
            return _sha256(b"proc-start-v1\0" + fields[19])
    ps = next(
        (
            candidate
            for candidate in ("/bin/ps", "/usr/bin/ps")
            if _safe_executable(Path(candidate)) is not None
        ),
        None,
    )
    if ps is None:
        return None
    try:
        completed = subprocess.run(
            (ps, "-o", "lstart=", "-p", str(pid)),
            check=False,
            env={"LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    start = completed.stdout.strip()
    return None if completed.returncode or not start else _sha256(b"ps-start-v1\0" + start)


def _process_identity_alive(path: Path) -> bool:
    if not os.path.lexists(path):
        return False
    try:
        value = json.loads(
            _read_private_regular(path, limit=1024).decode("utf-8", "strict")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _coded_error(
            "CONTROL_IDENTITY_DRIFT", "persistent process identity is invalid"
        ) from exc
    if not isinstance(value, Mapping) or set(value) != {"pid", "start_token"}:
        raise _coded_error(
            "CONTROL_IDENTITY_DRIFT", "persistent process identity is invalid"
        )
    pid = value["pid"]
    start_token = value["start_token"]
    if (
        isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 1
        or not isinstance(start_token, str)
        or len(start_token) != 64
        or any(character not in "0123456789abcdef" for character in start_token)
    ):
        raise _coded_error(
            "CONTROL_IDENTITY_DRIFT", "persistent process identity is invalid"
        )
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    observed = _process_start_token(pid)
    if observed is None:
        raise _coded_error(
            "PROCESS_IDENTITY_UNVERIFIABLE",
            "The persisted process identity cannot be rebound safely; it was not resent.",
            unavailable=True,
        )
    return observed == start_token


def _active_compute_window(
    directory: Path, *, resumed: bool
) -> tuple[int, datetime, int]:
    path = directory / ("resume.json" if resumed else "intent.json")
    try:
        value = json.loads(
            _read_private_regular(path, limit=4096).decode("utf-8", "strict")
        )
        if not isinstance(value, Mapping):
            raise TypeError("active-compute evidence must be an object")
        started = datetime.fromisoformat(
            str(value["started_at"]).replace("Z", "+00:00")
        )
        bound = value["attempt_timeout_milliseconds"]
        prior = value["prior_active_compute_ms"] if resumed else 0
    except (
        KeyError,
        TypeError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        raise _coded_error(
            "BUDGET_EVIDENCE_INVALID",
            "resume budget evidence is invalid"
            if resumed
            else "Attempt active-compute evidence is invalid",
        ) from exc
    if (
        started.tzinfo is None
        or isinstance(bound, bool)
        or not isinstance(bound, int)
        or bound < 1
        or isinstance(prior, bool)
        or not isinstance(prior, int)
        or prior < 0
    ):
        raise _coded_error(
            "BUDGET_EVIDENCE_INVALID",
            "resume budget evidence is invalid"
            if resumed
            else "Attempt active-compute evidence is invalid",
        )
    return prior, started, bound


def _elapsed_active_compute_ms(started: datetime, bound: int, now: datetime) -> int:
    delta = (
        now.astimezone(timezone.utc) - started.astimezone(timezone.utc)
    ).total_seconds()
    if delta < 0:
        return bound
    elapsed = int(delta * 1000)
    return min(bound, elapsed)


def _prior_active_compute_ms(
    directory: Path,
    now: datetime,
    *,
    include_current_resume: bool = True,
) -> int:
    resumed = os.path.lexists(directory / "resume.json")
    prior, started, bound = _active_compute_window(directory, resumed=resumed)
    current = (
        _elapsed_active_compute_ms(started, bound, now)
        if not resumed or include_current_resume
        else 0
    )
    return prior + current


def _remaining_attempt_seconds(
    directory: Path, now: datetime, *, resumed: bool
) -> float:
    _prior, started, bound = _active_compute_window(directory, resumed=resumed)
    used = _elapsed_active_compute_ms(started, bound, now)
    return max(0.0, (bound - used) / 1000)


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
        except PermissionError:
            # Darwin may transiently retain an unsignalable orphan/zombie
            # process-group identity after the session leader exits.  EPERM is
            # not closure evidence; only bounded ESRCH is accepted.
            pass
        time.sleep(0.01)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        process.wait()
        return
    except PermissionError:
        # Continue to the same bounded ESRCH proof below.  If the identity does
        # not disappear, the invocation remains failed/ambiguous.
        pass
    if process.poll() is None:
        process.wait(timeout=PROCESS_REAP_GRACE_SECONDS)
    deadline = time.monotonic() + PROCESS_REAP_GRACE_SECONDS
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            pass
        time.sleep(0.01)
    raise _coded_error(
        "PROCESS_REAP_FAILED", "Codex exec process group did not close"
    )


def _run_bounded_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    stdin_bytes: bytes,
    timeout_seconds: float,
    stdout_limit: int,
    stderr_limit: int,
    process_observer: Callable[[int], None] | None = None,
    stdout_observer: Callable[[bytes], None] | None = None,
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
    started_ns = time.monotonic_ns()
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
        raise _coded_error(
            "PROCESS_SPAWN_FAILED",
            "Codex exec process is unavailable",
            unavailable=True,
        ) from exc
    if process_observer is not None:
        try:
            process_observer(process.pid)
        except BaseException:
            _terminate_process_group(process)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
            raise
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
                raise _coded_error("PROCESS_TIMEOUT", "Codex exec timed out")
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
                        raise _coded_error(
                            "PROCESS_STDIN_FAILED", "Codex exec stdin was lost"
                        ) from exc
                    if written <= 0:
                        raise _coded_error(
                            "PROCESS_STDIN_FAILED", "Codex exec stdin was lost"
                        )
                    write_offset += written
                    continue
                try:
                    chunk = os.read(key.fd, 65_536)
                except BlockingIOError:
                    continue
                except OSError as exc:
                    code = (
                        "STDOUT_JSONL_INVALID"
                        if channel == "stdout"
                        else "STDERR_DIAGNOSTIC_INVALID"
                    )
                    raise _coded_error(
                        code, f"Codex exec {channel} stream was lost"
                    ) from exc
                if not chunk:
                    selector.unregister(key.fd)
                    continue
                output[channel].extend(chunk)
                if channel == "stdout" and stdout_observer is not None:
                    stdout_observer(chunk)
                limit = stdout_limit if channel == "stdout" else stderr_limit
                if len(output[channel]) > limit:
                    code = (
                        "STDOUT_JSONL_INVALID"
                        if channel == "stdout"
                        else "STDERR_DIAGNOSTIC_OVERFLOW"
                    )
                    raise _coded_error(
                        code, f"Codex exec {channel} exceeded its bound"
                    )
        remaining = max(0.0, deadline - time.monotonic())
        try:
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            raise _coded_error(
                "PROCESS_TIMEOUT", "Codex exec did not terminate"
            ) from exc
        return _ProcessResult(
            argv=tuple(argv),
            returncode=returncode,
            stdout=bytes(output["stdout"]),
            stderr=bytes(output["stderr"]),
            elapsed_ms=(time.monotonic_ns() - started_ns) // 1_000_000,
        )
    except KeyboardInterrupt as exc:
        raise _coded_error(
            "PROCESS_INTERRUPTED", "Codex exec was interrupted"
        ) from exc
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
        raise _coded_error(
            "STDOUT_JSONL_INVALID", "Codex exec JSONL is empty or truncated"
        )
    lines = raw.splitlines()
    if not lines:
        raise _coded_error("STDOUT_JSONL_INVALID", "Codex exec JSONL is empty")
    thread_ids: list[str] = []
    turn_started = 0
    terminal_types: list[str] = []
    phase = "EXPECT_THREAD"
    for encoded in lines:
        if not encoded or len(encoded) > MAX_JSONL_LINE_BYTES:
            raise _coded_error(
                "STDOUT_JSONL_INVALID", "Codex exec JSONL line is invalid or oversized"
            )
        try:
            event = json.loads(encoded.decode("utf-8", "strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _coded_error(
                "STDOUT_JSONL_INVALID", "Codex exec emitted malformed JSONL"
            ) from exc
        if not isinstance(event, Mapping) or not isinstance(event.get("type"), str):
            raise _coded_error(
                "STDOUT_JSONL_INVALID", "Codex exec event schema drift"
            )
        event_type = event["type"]
        if event_type == "thread.started":
            thread_id = event.get("thread_id")
            if (
                phase != "EXPECT_THREAD"
                or not isinstance(thread_id, str)
                or not thread_id
                or thread_ids
            ):
                raise _coded_error(
                    "THREAD_IDENTITY_INVALID",
                    "Codex exec thread identity is missing or conflicting",
                )
            thread_ids.append(thread_id)
            phase = "EXPECT_TURN"
        elif event_type == "turn.started":
            if phase != "EXPECT_TURN":
                raise _coded_error(
                    "TURN_TERMINAL_FAILED", "Codex exec turn start is out of order"
                )
            turn_started += 1
            if turn_started > 1:
                raise _coded_error(
                    "TURN_TERMINAL_FAILED", "Codex exec emitted duplicate turn start"
                )
            phase = "IN_TURN"
        elif event_type in {"turn.completed", "turn.failed", "error"}:
            if phase != "IN_TURN":
                raise _coded_error(
                    "TURN_TERMINAL_FAILED", "Codex exec terminal event is out of order"
                )
            terminal_types.append(event_type)
            if len(terminal_types) > 1:
                raise _coded_error(
                    "TURN_TERMINAL_FAILED", "Codex exec emitted multiple terminal events"
                )
            phase = "TERMINAL"
        elif event_type == "item.completed":
            if phase != "IN_TURN":
                raise _coded_error(
                    "TURN_TERMINAL_FAILED", "Codex exec completed item is out of order"
                )
            item = event.get("item")
            if not isinstance(item, Mapping):
                raise _coded_error(
                    "STDOUT_JSONL_INVALID", "Codex exec completed item schema drift"
                )
        elif phase == "TERMINAL":
            raise _coded_error(
                "TURN_TERMINAL_FAILED", "Codex exec emitted evidence after terminal"
            )
        # Additive in-turn event types and non-terminal item warnings are
        # non-authoritative. Additive preamble events cannot establish identity.
    if len(thread_ids) != 1 or turn_started != 1:
        code = "THREAD_IDENTITY_INVALID" if len(thread_ids) != 1 else "TURN_TERMINAL_FAILED"
        raise _coded_error(code, "Codex exec identity/start evidence is incomplete")
    if terminal_types != ["turn.completed"]:
        raise _coded_error(
            "TURN_TERMINAL_FAILED", "Codex exec did not complete successfully"
        )
    return _TerminalTranscript(
        thread_id=thread_ids[0],
        terminal_event_count=len(terminal_types),
        terminal_event_type=terminal_types[0],
    )


def _terminal_summary(raw: bytes) -> tuple[int, str | None]:
    """Extract only safe terminal counts from possibly invalid diagnostic JSONL."""

    terminal_types: list[str] = []
    for encoded in raw.splitlines():
        if not encoded or len(encoded) > MAX_JSONL_LINE_BYTES:
            continue
        try:
            event = json.loads(encoded.decode("utf-8", "strict"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(event, Mapping) and event.get("type") in {
            "turn.completed",
            "turn.failed",
            "error",
        }:
            terminal_types.append(event["type"])
    return (
        len(terminal_types),
        terminal_types[0] if len(terminal_types) == 1 else None,
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
        timeout_seconds: float = MAX_ATTEMPT_TIMEOUT_SECONDS,
        model: str | None = None,
        reasoning_effort: str | None = None,
        network_access: bool = False,
        sandbox: str = "workspace-write",
        ephemeral: bool = False,
        attempt_root: Path | str | None = None,
        resume_thread_id: str | None = None,
        budget_override: Mapping[str, Any] | None = None,
        runner: Callable[..., _ProcessResult] = _run_bounded_process,
    ) -> None:
        resolved = Path(workspace).resolve(strict=True)
        if not resolved.is_dir() or resolved.is_symlink():
            raise ValueError("Host workspace must be one existing directory")
        if timeout_seconds <= 0 or timeout_seconds > MAX_ATTEMPT_TIMEOUT_SECONDS:
            raise ValueError("invalid Codex exec timeout")
        if sandbox != "workspace-write":
            raise ValueError("invalid Codex exec sandbox")
        if reasoning_effort not in {None, "low", "medium", "high", "xhigh", "max"}:
            raise ValueError("invalid Codex exec reasoning effort")
        if model is not None and (not model.strip() or len(model.encode("utf-8")) > 128):
            raise ValueError("invalid Codex exec model")
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
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.network_access = network_access
        self.sandbox = sandbox
        self.ephemeral = ephemeral
        self.resume_thread_id = resume_thread_id
        self.budget_override: dict[str, Any] | None = None
        if budget_override is not None:
            maximum_calls = budget_override.get("max_host_invocations")
            wall_seconds = budget_override.get("wall_clock_seconds")
            if (
                isinstance(maximum_calls, bool)
                or not isinstance(maximum_calls, int)
                or maximum_calls < 1
                or isinstance(wall_seconds, bool)
                or not isinstance(wall_seconds, int)
                or wall_seconds < 1
            ):
                raise ValueError("invalid runtime budget override")
            self.budget_override = {
                "max_host_invocations": maximum_calls,
                "wall_clock_seconds": wall_seconds,
            }
        self.attempt_root: Path | None = None
        if attempt_root is not None:
            candidate = Path(attempt_root)
            candidate.mkdir(parents=True, exist_ok=True, mode=0o700)
            candidate = candidate.resolve(strict=True)
            metadata = candidate.lstat()
            if (
                candidate == self.workspace
                or self.workspace in candidate.parents
                or candidate in self.workspace.parents
                or candidate.is_symlink()
                or not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_mode & 0o077
                or (hasattr(os, "getuid") and metadata.st_uid != os.getuid())
            ):
                raise ValueError("invalid persistent Attempt root")
            self.attempt_root = candidate
        self._runner = runner
        self._contract: _ExecContract | None = None
        self._invoked_key: str | None = None
        self._record: dict[str, Any] | None = None
        self._terminal_diagnostic: _TerminalDiagnostic | None = None
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
        return self._invoke(
            action,
            payload,
            provider_idempotency_key,
            recovery_only=False,
        )

    def recover(
        self,
        action: str,
        payload: Mapping[str, Any],
        provider_idempotency_key: str,
    ) -> Mapping[str, Any]:
        """Recover one already-started durable Attempt without creating a new one."""

        return self._invoke(
            action,
            payload,
            provider_idempotency_key,
            recovery_only=True,
        )

    def _invoke(
        self,
        action: str,
        payload: Mapping[str, Any],
        provider_idempotency_key: str,
        *,
        recovery_only: bool,
    ) -> Mapping[str, Any]:
        if action != "create_task" or set(payload) not in {
            LEGACY_PAYLOAD_FIELDS,
            CONTENT_PAYLOAD_FIELDS,
            V2_CONTENT_PAYLOAD_FIELDS,
        }:
            raise HostUnavailable("Unsupported Codex exec action or payload")
        if self._invoked_key is not None:
            self._duplicate_invoke_rejection_count += 1
            raise HostUnavailable("Codex exec invocation budget is already consumed")
        self.preflight()
        prompt = self._prompt(payload, provider_idempotency_key)
        self._invoked_key = provider_idempotency_key
        if self._restore_persistent_record(provider_idempotency_key):
            return self._observation(action, provider_idempotency_key)
        attempt_directory: Path | None = None
        resumed = False
        if self.attempt_root is not None:
            attempt_directory = self.attempt_root / _private_attempt_name(
                provider_idempotency_key
            )
            if attempt_directory.exists():
                recovered = self._recover_incomplete_attempt(
                    attempt_directory,
                    payload=payload,
                    provider_key=provider_idempotency_key,
                    authorize_resume=False,
                )
                if recovered is not None:
                    return recovered
                resumed = True
            else:
                if recovery_only:
                    raise _coded_error(
                        "ATTEMPT_EVIDENCE_MISSING",
                        "The claimed Attempt has no persistent Provider evidence; it was not resent.",
                        unavailable=True,
                    )
        elif recovery_only:
            raise _coded_error(
                "ATTEMPT_EVIDENCE_MISSING",
                "Recovery requires a persistent Attempt root; it was not resent.",
                unavailable=True,
            )
        budget_reason = self._budget_block_reason(payload)
        if budget_reason is not None:
            return self._local_wait_observation(
                payload,
                provider_idempotency_key,
                budget_reason,
            )
        self._task_create_count += 1
        if self.attempt_root is not None:
            assert attempt_directory is not None
            if resumed:
                assert self.resume_thread_id is not None
                resume_started = self.clock()
                _write_private_once(
                    attempt_directory / "resume.json",
                    canonical_bytes(
                        {
                            "attempt_timeout_milliseconds": int(
                                self.timeout_seconds * 1000
                            ),
                            "prior_active_compute_ms": _prior_active_compute_ms(
                                attempt_directory, resume_started
                            ),
                            "started_at": _iso(resume_started),
                            "thread_id": self.resume_thread_id,
                        }
                    ),
                )
            else:
                attempt_directory = _private_attempt_directory(
                    self.attempt_root, provider_idempotency_key
                )
                _write_private_once(
                    attempt_directory / "intent.json",
                    canonical_bytes(
                        {
                            "attempt_timeout_milliseconds": int(
                                self.timeout_seconds * 1000
                            ),
                            "input_sha256": _sha256(prompt.encode("utf-8") + b"\n"),
                            "provider_idempotency_key_digest": hashlib.sha256(
                                provider_idempotency_key.encode("utf-8")
                            ).hexdigest(),
                            "replay_safety": (
                                payload.get("goal_policy", {}).get("replay_safety")
                                if isinstance(payload.get("goal_policy"), Mapping)
                                else None
                            ),
                            "recovery_policy": (
                                payload.get("goal_policy", {}).get("recovery_policy")
                                if isinstance(payload.get("goal_policy"), Mapping)
                                else None
                            ),
                            "started_at": _iso(self.clock()),
                            "transport": EXEC_TRANSPORT,
                        }
                    ),
                )
        stream_buffer = bytearray()

        def observe_process(pid: int) -> None:
            if attempt_directory is None:
                return
            start_token = _process_start_token(pid)
            if start_token is None:
                raise _coded_error(
                    "PROCESS_IDENTITY_UNVERIFIABLE",
                    "The spawned process identity could not be bound safely.",
                    unavailable=True,
                )
            name = "resume-process.json" if resumed else "process.json"
            _write_private_once(
                attempt_directory / name,
                canonical_bytes({"pid": pid, "start_token": start_token}),
            )

        def observe_stdout(chunk: bytes) -> None:
            if attempt_directory is None:
                return
            name = "resume-transcript.partial.jsonl" if resumed else "transcript.partial.jsonl"
            _append_private(attempt_directory / name, chunk)
            stream_buffer.extend(chunk)
            while b"\n" in stream_buffer:
                encoded, _, remaining = stream_buffer.partition(b"\n")
                stream_buffer[:] = remaining
                if not encoded or (attempt_directory / "session.json").exists():
                    continue
                try:
                    event = json.loads(encoded.decode("utf-8", "strict"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                thread_id = event.get("thread_id") if isinstance(event, Mapping) else None
                if (
                    isinstance(event, Mapping)
                    and event.get("type") == "thread.started"
                    and isinstance(thread_id, str)
                ):
                    _write_private_once(
                        attempt_directory / "session.json",
                        canonical_bytes({"thread_id": thread_id}),
                    )
        process_result: _ProcessResult | None = None
        transcript: _TerminalTranscript | None = None
        result_raw = b""
        result_payload: dict[str, str] | None = None
        schema_digest = _sha256(b"")
        try:
            with _result_controls(self.workspace) as controls:
                schema_digest = controls.schema.digest
                process_result = self._runner(
                    build_exec_argv(
                        self.executable,
                        self.workspace,
                        controls.schema.path,
                        controls.result.path,
                        model=self.model,
                        reasoning_effort=self.reasoning_effort,
                        network_access=self.network_access,
                        sandbox=self.sandbox,
                        ephemeral=self.ephemeral,
                        resume_thread_id=self.resume_thread_id,
                    ),
                    cwd=self.workspace,
                    stdin_bytes=prompt.encode("utf-8") + b"\n",
                    timeout_seconds=self.timeout_seconds,
                    stdout_limit=MAX_STDOUT_BYTES,
                    stderr_limit=MAX_STDERR_BYTES,
                    process_observer=observe_process,
                    stdout_observer=observe_stdout,
                )
                if process_result.returncode != 0:
                    raise _coded_error(
                        "PROCESS_EXIT_NONZERO",
                        "Codex exec exited without successful terminal evidence",
                    )
                transcript = _parse_jsonl(process_result.stdout)
                result_raw = _read_result_control(controls.result)
                try:
                    result_payload = parse_result_payload(result_raw)
                except ProtocolRejection as exc:
                    raise _coded_error(
                        "RESULT_SCHEMA_INVALID",
                        "Codex exec result file contract drift",
                    ) from exc
                if attempt_directory is not None:
                    session_path = attempt_directory / "session.json"
                    if not session_path.exists():
                        _write_private_once(
                            session_path,
                            canonical_bytes({"thread_id": transcript.thread_id}),
                        )
                    _write_private_once(
                        attempt_directory / "result.schema.json", controls.schema.raw
                    )
                    _write_private_once(
                        attempt_directory / "result.json", result_raw
                    )
                    _write_private_once(
                        attempt_directory / "transcript.jsonl", process_result.stdout
                    )
                    _write_private_once(
                        attempt_directory / "attempt.json",
                        canonical_bytes(
                            {
                                "argv_digest": domain_digest(
                                    "loopskill-codex-argv-v1\n",
                                    list(process_result.argv),
                                ),
                                "executable_digest": self._contract.executable_digest,
                                "model": self.model,
                                "network_access": self.network_access,
                                "elapsed_ms": process_result.elapsed_ms,
                                "provider_idempotency_key_digest": hashlib.sha256(
                                    provider_idempotency_key.encode("utf-8")
                                ).hexdigest(),
                                "reasoning_effort": self.reasoning_effort,
                                "resumed": resumed,
                                "result_sha256": _sha256(result_raw),
                                "sandbox": self.sandbox,
                                "schema_digest": controls.schema.digest,
                                "thread_id": transcript.thread_id,
                                "transcript_sha256": _sha256(process_result.stdout),
                                "transport": EXEC_TRANSPORT,
                            }
                        ),
                    )
        except Exception as exc:
            code = _error_code(exc, "UNCLASSIFIED_PROVIDER_FAILURE")
            if attempt_directory is not None and not (
                attempt_directory / "failure.json"
            ).exists():
                _write_private_once(
                    attempt_directory / "failure.json",
                    canonical_bytes({"code": code}),
                )
            self._terminal_diagnostic = self._diagnostic(
                code=code,
                primary_code=getattr(exc, "primary_provider_code", None),
                process_result=process_result,
                result_raw=result_raw,
                result_payload=result_payload,
                schema_digest=schema_digest,
                transcript=transcript,
            )
            if isinstance(exc, (HostResponseLost, HostUnavailable)):
                raise
            raise _coded_error(
                code, "Codex exec terminal evidence failed"
            ) from exc
        assert process_result is not None
        assert transcript is not None
        self._terminal_diagnostic = self._diagnostic(
            code="PASS",
            primary_code=None,
            process_result=process_result,
            result_raw=result_raw,
            result_payload=result_payload,
            schema_digest=schema_digest,
            transcript=transcript,
        )
        self._record = {
            "idempotency_key": provider_idempotency_key,
            "result": dict(result_payload),
            "result_schema_digest": schema_digest,
            "thread_id": transcript.thread_id,
        }
        return self._observation(action, provider_idempotency_key)

    def _recover_incomplete_attempt(
        self,
        directory: Path,
        *,
        payload: Mapping[str, Any],
        provider_key: str,
        authorize_resume: bool = True,
    ) -> Mapping[str, Any] | None:
        if directory.is_symlink() or not directory.is_dir():
            raise _coded_error(
                "CONTROL_IDENTITY_DRIFT", "persistent Attempt directory is unsafe"
            )
        policy = payload.get("goal_policy")
        replay_safety = (
            policy.get("replay_safety") if isinstance(policy, Mapping) else None
        )
        recovery_policy = (
            policy.get("recovery_policy") if isinstance(policy, Mapping) else None
        )

        def reconcile_or_wait(summary: str) -> Mapping[str, Any]:
            if replay_safety == "file_local" and recovery_policy in {
                "reconcile",
                "resume",
            }:
                return self._local_wait_observation(
                    payload,
                    provider_key,
                    "RECONCILE_WORKSPACE: " + summary,
                    outcome="PASS",
                )
            return self._local_wait_observation(payload, provider_key, summary)

        key_digest = hashlib.sha256(provider_key.encode("utf-8")).hexdigest()
        if os.path.lexists(directory / "attempt.json"):
            if self._restore_persistent_directory(
                directory,
                expected_key_digest=key_digest,
                provider_key=provider_key,
            ):
                return self._observation("create_task", provider_key)
            raise _coded_error(
                "CONTROL_IDENTITY_DRIFT",
                "persistent terminal Attempt evidence is inconsistent",
            )
        if (directory / "failure.json").exists():
            return reconcile_or_wait(
                "the prior Host Attempt ended without terminal evidence; verify current local artifacts before repair."
            )
        process_paths = tuple(
            directory / name for name in ("resume-process.json", "process.json")
        )
        active_processes = tuple(
            path for path in process_paths if _process_identity_alive(path)
        )
        if len(active_processes) > 1:
            raise _coded_error(
                "CONTROL_IDENTITY_DRIFT",
                "multiple persistent Host process identities are live",
            )
        deadline = time.monotonic() + (
            0.0
            if not active_processes
            else _remaining_attempt_seconds(
                directory,
                self.clock(),
                resumed=active_processes[0].name == "resume-process.json",
            )
        )
        while active_processes:
            if os.path.lexists(directory / "attempt.json"):
                if self._restore_persistent_directory(
                    directory,
                    expected_key_digest=key_digest,
                    provider_key=provider_key,
                ):
                    return self._observation("create_task", provider_key)
                raise _coded_error(
                    "CONTROL_IDENTITY_DRIFT",
                    "persistent terminal Attempt evidence is inconsistent",
                )
            if (directory / "failure.json").exists():
                return reconcile_or_wait(
                    "the prior Host Attempt ended without terminal evidence; verify current local artifacts before repair."
                )
            if time.monotonic() >= deadline:
                raise _coded_error(
                    "PROCESS_STILL_RUNNING",
                    "The prior Codex exec process remained active through its bound; it was not resent.",
                    unavailable=True,
                )
            time.sleep(0.25)
            active_processes = tuple(
                path for path in process_paths if _process_identity_alive(path)
            )
            if len(active_processes) > 1:
                raise _coded_error(
                    "CONTROL_IDENTITY_DRIFT",
                    "multiple persistent Host process identities are live",
                )
        session_path = directory / "session.json"
        if not os.path.lexists(session_path):
            return reconcile_or_wait(
                "no Host session identity was captured; verify current local artifacts before repair."
            )
        if (directory / "resume.json").exists():
            return reconcile_or_wait(
                "the Host session already consumed its single automatic resume; verify current local artifacts before repair."
            )
        try:
            session = json.loads(
                _read_private_regular(session_path, limit=1024).decode(
                    "utf-8", "strict"
                )
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _coded_error(
                "THREAD_IDENTITY_INVALID", "persistent Host session identity is invalid"
            ) from exc
        thread_id = session.get("thread_id") if isinstance(session, Mapping) else None
        if not isinstance(thread_id, str) or not thread_id:
            raise _coded_error(
                "THREAD_IDENTITY_INVALID", "persistent Host session identity is invalid"
            )
        if replay_safety == "non_replayable":
            return self._local_wait_observation(
                payload,
                provider_key,
                "Human confirmation is required before recovering a non-replayable action.",
            )
        if recovery_policy == "human":
            return self._local_wait_observation(
                payload,
                provider_key,
                "Human confirmation is required by the Goal recovery policy.",
            )
        if recovery_policy == "reconcile":
            return reconcile_or_wait(
                "the Goal requires local artifact reconciliation before another Host action."
            )
        if recovery_policy != "resume":
            return self._local_wait_observation(
                payload,
                provider_key,
                "The Goal recovery policy is unavailable; the Host action was not resent.",
            )
        if authorize_resume:
            resume_started = self.clock()
            _write_private_once(
                directory / "resume.json",
                canonical_bytes(
                    {
                        "attempt_timeout_milliseconds": int(
                            self.timeout_seconds * 1000
                        ),
                        "prior_active_compute_ms": _prior_active_compute_ms(
                            directory, resume_started
                        ),
                        "started_at": _iso(resume_started),
                        "thread_id": thread_id,
                    }
                ),
            )
        self.resume_thread_id = thread_id
        return None

    def _local_wait_observation(
        self,
        payload: Mapping[str, Any],
        provider_key: str,
        summary: str,
        *,
        outcome: str = "LIMITATION",
    ) -> Mapping[str, Any]:
        del payload
        schema_digest = domain_digest(
            "loopskill-codex-result-schema-v1\n", result_payload_schema()
        )
        self._record = {
            "idempotency_key": provider_key,
            "result": {"outcome": outcome, "summary": summary},
            "result_schema_digest": schema_digest,
            "thread_id": "waiting-"
            + hashlib.sha256(provider_key.encode("utf-8")).hexdigest()[:24],
        }
        return self._observation("create_task", provider_key)

    def _budget_block_reason(self, payload: Mapping[str, Any]) -> str | None:
        budget = self.budget_override or payload.get("budget")
        if not isinstance(budget, Mapping) or self.attempt_root is None:
            return None
        maximum_calls = budget.get("max_host_invocations")
        wall_seconds = budget.get("wall_clock_seconds")
        if (
            isinstance(maximum_calls, bool)
            or not isinstance(maximum_calls, int)
            or isinstance(wall_seconds, bool)
            or not isinstance(wall_seconds, int)
        ):
            return "The Plan-bound runtime budget is invalid."
        used_calls = 0
        used_milliseconds = 0
        for directory in self.attempt_root.iterdir():
            record = directory / "attempt.json"
            intent = directory / "intent.json"
            if not directory.is_dir() or directory.is_symlink():
                continue
            if not intent.is_file() and not record.is_file():
                continue
            used_calls += 1
            if (directory / "resume.json").is_file():
                used_calls += 1
            if not record.is_file():
                try:
                    used_milliseconds += _prior_active_compute_ms(
                        directory, self.clock()
                    )
                except (HostResponseLost, HostUnavailable, OSError, ValueError):
                    return "The persisted active-compute budget evidence is unverifiable."
                continue
            try:
                raw = _read_private_regular(record, limit=MAX_INSPECTION_BYTES)
                value = json.loads(raw.decode("utf-8", "strict"))
            except (HostResponseLost, UnicodeDecodeError, json.JSONDecodeError):
                return "The persisted active-compute budget evidence is unverifiable."
            if not isinstance(value, Mapping):
                return "The persisted active-compute budget evidence is unverifiable."
            elapsed = value.get("elapsed_ms")
            if isinstance(elapsed, bool) or not isinstance(elapsed, int) or elapsed < 0:
                return "The persisted active-compute budget evidence is unverifiable."
            used_milliseconds += elapsed
            if value.get("resumed") is True:
                try:
                    used_milliseconds += _prior_active_compute_ms(
                        directory,
                        self.clock(),
                        include_current_resume=False,
                    )
                except (HostResponseLost, HostUnavailable, OSError, ValueError):
                    return "The persisted active-compute budget evidence is unverifiable."
        if used_calls >= maximum_calls:
            return "The Plan-bound Host invocation budget is exhausted."
        if used_milliseconds >= wall_seconds * 1000:
            return "The Plan-bound active-compute budget is exhausted."
        self.timeout_seconds = min(
            self.timeout_seconds,
            max(0.001, wall_seconds - used_milliseconds / 1000),
        )
        return None

    def budget_block_reason(self, payload: Mapping[str, Any]) -> str | None:
        """Read persisted usage before the Adapter commits a provider side effect."""

        return self._budget_block_reason(payload)

    def recovery_budget_block_reason(
        self,
        payload: Mapping[str, Any],
        provider_idempotency_key: str,
    ) -> str | None:
        """Check budget only when recovery would spawn one recorded session resume."""

        if self.attempt_root is None:
            return None
        directory = self.attempt_root / _private_attempt_name(
            provider_idempotency_key
        )
        if (
            not directory.is_dir()
            or directory.is_symlink()
            or (directory / "attempt.json").exists()
            or (directory / "failure.json").exists()
            or (directory / "resume.json").exists()
            or not (directory / "session.json").exists()
        ):
            return None
        try:
            if any(
                _process_identity_alive(directory / name)
                for name in ("resume-process.json", "process.json")
            ):
                return None
        except (HostResponseLost, HostUnavailable):
            return None
        policy = payload.get("goal_policy")
        if not isinstance(policy, Mapping):
            return None
        if (
            policy.get("recovery_policy") != "resume"
            or policy.get("replay_safety") == "non_replayable"
        ):
            return None
        return self._budget_block_reason(payload)

    def readback(
        self, action: str, provider_idempotency_key: str
    ) -> Mapping[str, Any] | None:
        if action != "create_task":
            return None
        self._delivery_readback_count += 1
        if self._record is None:
            self._restore_persistent_record(provider_idempotency_key)
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
        if self._record is None:
            self._restore_persistent_thread(provider_id)
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
        if self._record is None:
            self._restore_persistent_thread(provider_id)
        if self._record is None or self._record["thread_id"] != provider_id:
            raise HostUnavailable("Codex exec terminal result is unavailable")
        result = self._record["result"]
        schema_digest = self._record["result_schema_digest"]
        return {
            "provider_id": provider_id,
            "result": dict(result),
            "result_digest": domain_digest(
                "loopskill-host-result-v1\n",
                {"result": result, "result_schema_digest": schema_digest},
            ),
            "result_schema_digest": schema_digest,
            "schema_version": HOST_SCHEMA_VERSION,
            "status": "COMPLETED",
            "trust": "authoritative",
        }

    def wait_for_terminal(
        self,
        *,
        timeout_seconds: float = MAX_ATTEMPT_TIMEOUT_SECONDS,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        del poll_interval_seconds
        if timeout_seconds <= 0 or timeout_seconds > MAX_ATTEMPT_TIMEOUT_SECONDS:
            raise ValueError("invalid terminal wait bound")
        self._terminal_wait_read_count += 1
        if self._record is None:
            code = (
                "TERMINAL_EVIDENCE_UNAVAILABLE"
                if self._terminal_diagnostic is None
                else self._terminal_diagnostic.code
            )
            raise _coded_error(
                code,
                "Codex exec terminal evidence is unavailable",
                unavailable=True,
            )

    def terminal_diagnostic(self) -> Mapping[str, Any] | None:
        """Return bounded private same-process transport and semantic evidence."""

        if self._terminal_diagnostic is None:
            return None
        return dict(self._terminal_diagnostic.private_evidence())

    def close(self) -> None:
        """No Host process survives ``invoke``; retained state is local evidence only."""

    def _restore_persistent_thread(self, thread_id: str) -> bool:
        if self.attempt_root is None:
            return False
        for directory in sorted(self.attempt_root.iterdir()):
            manifest = directory / "attempt.json"
            if (
                not directory.is_dir()
                or directory.is_symlink()
                or not os.path.lexists(manifest)
            ):
                continue
            try:
                value = json.loads(
                    _read_private_regular(manifest, limit=MAX_INSPECTION_BYTES).decode(
                        "utf-8", "strict"
                    )
                )
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise _coded_error(
                    "CONTROL_IDENTITY_DRIFT",
                    "persistent terminal Attempt manifest is invalid",
                ) from exc
            if isinstance(value, Mapping) and value.get("thread_id") == thread_id:
                key_digest = value.get("provider_idempotency_key_digest")
                if not isinstance(key_digest, str):
                    return False
                return self._restore_persistent_directory(
                    directory, expected_key_digest=key_digest
                )
        return False

    def _restore_persistent_record(self, provider_key: str) -> bool:
        if self.attempt_root is None:
            return False
        directory = self.attempt_root / _private_attempt_name(provider_key)
        if not directory.is_dir() or directory.is_symlink():
            return False
        if not os.path.lexists(directory / "attempt.json"):
            return False
        return self._restore_persistent_directory(
            directory,
            expected_key_digest=hashlib.sha256(
                provider_key.encode("utf-8")
            ).hexdigest(),
            provider_key=provider_key,
        )

    def _restore_persistent_directory(
        self,
        directory: Path,
        *,
        expected_key_digest: str,
        provider_key: str | None = None,
    ) -> bool:
        if directory.is_symlink() or not directory.is_dir():
            raise _coded_error(
                "CONTROL_IDENTITY_DRIFT", "persistent Attempt directory is unsafe"
            )
        try:
            manifest_raw = _read_private_regular(
                directory / "attempt.json", limit=MAX_INSPECTION_BYTES
            )
            manifest = json.loads(manifest_raw.decode("utf-8", "strict"))
            result_raw = _read_private_regular(
                directory / "result.json", limit=MAX_RESULT_BYTES
            )
            schema_raw = _read_private_regular(
                directory / "result.schema.json", limit=MAX_INSPECTION_BYTES
            )
            transcript_raw = _read_private_regular(
                directory / "transcript.jsonl", limit=MAX_STDOUT_BYTES
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        expected_schema_digest = domain_digest(
            "loopskill-codex-result-schema-v1\n", result_payload_schema()
        )
        if (
            not isinstance(manifest, Mapping)
            or manifest.get("provider_idempotency_key_digest") != expected_key_digest
            or manifest.get("result_sha256") != _sha256(result_raw)
            or manifest.get("transcript_sha256") != _sha256(transcript_raw)
            or manifest.get("schema_digest") != expected_schema_digest
            or manifest.get("transport") != EXEC_TRANSPORT
            or schema_raw != canonical_bytes(result_payload_schema())
        ):
            return False
        try:
            transcript = _parse_jsonl(transcript_raw)
            result = parse_result_payload(result_raw)
        except (ProtocolRejection, RuntimeError):
            return False
        if transcript.thread_id != manifest.get("thread_id"):
            return False
        if provider_key is None:
            provider_key = "restored-" + expected_key_digest
        self._record = {
            "idempotency_key": provider_key,
            "result": result,
            "result_schema_digest": domain_digest(
                "loopskill-codex-result-schema-v1\n", result_payload_schema()
            ),
            "thread_id": transcript.thread_id,
        }
        return True

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
    def _diagnostic(
        *,
        code: str,
        primary_code: str | None,
        process_result: _ProcessResult | None,
        result_raw: bytes,
        result_payload: Mapping[str, str] | None,
        schema_digest: str,
        transcript: _TerminalTranscript | None,
    ) -> _TerminalDiagnostic:
        stdout = b"" if process_result is None else process_result.stdout
        stderr = b"" if process_result is None else process_result.stderr
        if process_result is None:
            returncode_class = "UNAVAILABLE"
        elif process_result.returncode == 0:
            returncode_class = "ZERO"
        else:
            returncode_class = "NONZERO"
        terminal_event_count, terminal_event_type = _terminal_summary(stdout)
        if transcript is not None:
            terminal_event_count = transcript.terminal_event_count
            terminal_event_type = transcript.terminal_event_type
        return _TerminalDiagnostic(
            code=code,
            primary_code=primary_code,
            result_bytes=len(result_raw),
            result_sha256=_sha256(result_raw),
            result_control_digest=_sha256(result_raw),
            returncode_class=returncode_class,
            schema_control_digest=schema_digest,
            semantic_outcome=(
                None if result_payload is None else result_payload["outcome"]
            ),
            semantic_summary=(
                None if result_payload is None else result_payload["summary"]
            ),
            stderr_bytes=len(stderr),
            stderr_sha256=_sha256(stderr),
            stdout_bytes=len(stdout),
            stdout_sha256=_sha256(stdout),
            terminal_event_count=terminal_event_count,
            terminal_event_type=terminal_event_type,
        )

    @staticmethod
    def _prompt(payload: Mapping[str, Any], operation_id: str) -> str:
        try:
            return materialize_prompt(payload, operation_id)
        except PromptMaterializationError as exc:
            raise HostUnavailable("Confirmed Codex exec request exceeds 32 KiB") from exc
