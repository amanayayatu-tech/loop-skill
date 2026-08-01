"""Independent, artifact-bound local verification for explicit safe criteria."""

from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from loop_architect.v4_alpha.protocol import canonical_bytes, domain_digest

from .capture import ArtifactCapture
from .paths import ArtifactCaptureError, normalize_relative_path


_SHA256_RE = re.compile(r"^file-sha256:([^=]+)=([0-9a-f]{64})$")
_COMMAND_PREFIX = "command-json:"
_HTTP_PREFIX = "http-json:"
_INHERITED_ENV_ALLOWLIST = frozenset({"LANG", "LC_ALL", "PATH", "TMPDIR"})
_MAX_VERIFIER_OUTPUT = 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


def _valid_loopback_route(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("/")
        and not value.startswith("//")
        and "\r" not in value
        and "\n" not in value
        and "#" not in value
        and len(value.encode("utf-8")) <= 2048
    )


@dataclass(frozen=True)
class LocalVerification:
    state: str
    evidence_digest: str
    checked_criteria: tuple[str, ...]
    reason: str


def verifier_capability(criterion: str) -> str | None:
    """Validate one verifier declaration without executing it."""

    if not isinstance(criterion, str):
        return None
    value = criterion.strip()
    if value in {"artifact-changed", "no-file-change"}:
        return "artifact-capture"
    if value.startswith("file-exists:"):
        normalize_relative_path(value[len("file-exists:") :])
        return "artifact-capture"
    match = _SHA256_RE.fullmatch(value)
    if match:
        normalize_relative_path(match.group(1))
        return "artifact-capture"
    if value.startswith(_COMMAND_PREFIX):
        document = _verifier_document(
            value[len(_COMMAND_PREFIX) :],
            frozenset({"argv", "cwd", "env", "expected_exit", "timeout_seconds"}),
        )
        _verifier_argv(document["argv"])
        _validate_relative_cwd(document["cwd"])
        _verifier_environment(document["env"])
        expected_exit = document["expected_exit"]
        timeout_seconds = document["timeout_seconds"]
        if (
            isinstance(expected_exit, bool)
            or not isinstance(expected_exit, int)
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not 1 <= timeout_seconds <= 600
        ):
            raise ValueError("invalid command verifier bound")
        return "local-command"
    if value.startswith(_HTTP_PREFIX):
        document = _verifier_document(
            value[len(_HTTP_PREFIX) :],
            frozenset(
                {
                    "cwd",
                    "env",
                    "port",
                    "routes",
                    "start_argv",
                    "startup_timeout_seconds",
                }
            ),
        )
        _validate_relative_cwd(document["cwd"])
        _verifier_argv(document["start_argv"])
        _verifier_environment(document["env"])
        port = document["port"]
        startup_timeout = document["startup_timeout_seconds"]
        routes = document["routes"]
        if (
            isinstance(port, bool)
            or not isinstance(port, int)
            or not 1024 <= port <= 65535
            or isinstance(startup_timeout, bool)
            or not isinstance(startup_timeout, int)
            or not 1 <= startup_timeout <= 60
            or not isinstance(routes, list)
            or not 1 <= len(routes) <= 16
        ):
            raise ValueError("invalid HTTP verifier bound")
        for route in routes:
            if (
                not isinstance(route, dict)
                or set(route) != {"contains", "path", "status"}
                or not _valid_loopback_route(route["path"])
                or not isinstance(route["contains"], str)
                or isinstance(route["status"], bool)
                or not isinstance(route["status"], int)
            ):
                raise ValueError("invalid HTTP route verifier")
        return "local-http"
    if value == "human-approval":
        return "human-gate"
    if value.startswith("time-after:"):
        timestamp = value[len("time-after:") :]
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("time verifier lacks timezone")
        return "time-gate"
    return None


def verify_artifact(
    store: Any,
    capture: ArtifactCapture,
    acceptance_criteria: Sequence[str],
    *,
    workspace_root: Path | str | None = None,
) -> LocalVerification:
    """Verify only declared, deterministic local facts; prose stays UNVERIFIABLE."""
    if store.get_blob(capture.bundle_blob_digest) is None:
        raise ArtifactCaptureError(
            "ARTIFACT_IDENTITY_MISMATCH", "artifact bundle blob is absent"
        )
    entries = {str(item["path"]): item for item in capture.manifest}
    checked: list[str] = []
    failures: list[str] = []
    unsupported: list[str] = []
    verifier_evidence: list[Mapping[str, Any]] = []
    for raw in acceptance_criteria:
        criterion = raw.strip()
        if criterion == "artifact-changed":
            checked.append(criterion)
            if capture.empty:
                failures.append(criterion)
            continue
        if criterion == "no-file-change":
            checked.append(criterion)
            if not capture.empty:
                failures.append(criterion)
            continue
        if criterion.startswith("file-exists:"):
            try:
                path = normalize_relative_path(criterion[len("file-exists:") :])
            except ArtifactCaptureError:
                failures.append(criterion)
                continue
            checked.append(criterion)
            item = entries.get(path)
            if item is None or item.get("after_digest") is None:
                failures.append(criterion)
            continue
        match = _SHA256_RE.fullmatch(criterion)
        if match:
            try:
                path = normalize_relative_path(match.group(1))
            except ArtifactCaptureError:
                failures.append(criterion)
                continue
            checked.append(criterion)
            item = entries.get(path)
            blob_digest = None if item is None else item.get("after_digest")
            blob = None if not isinstance(blob_digest, str) else store.get_blob(blob_digest)
            if blob is None or hashlib.sha256(blob).hexdigest() != match.group(2):
                failures.append(criterion)
            continue
        if criterion.startswith(_COMMAND_PREFIX):
            checked.append(criterion)
            if workspace_root is None:
                failures.append(criterion)
                continue
            try:
                evidence = _verify_command(
                    Path(workspace_root), criterion[len(_COMMAND_PREFIX) :]
                )
            except (ArtifactCaptureError, OSError, ValueError):
                failures.append(criterion)
                continue
            verifier_evidence.append(evidence)
            if evidence["state"] != "PASS":
                failures.append(criterion)
            continue
        if criterion.startswith(_HTTP_PREFIX):
            checked.append(criterion)
            if workspace_root is None:
                failures.append(criterion)
                continue
            try:
                evidence = _verify_http(
                    Path(workspace_root), criterion[len(_HTTP_PREFIX) :]
                )
            except (ArtifactCaptureError, OSError, ValueError):
                failures.append(criterion)
                continue
            verifier_evidence.append(evidence)
            if evidence["state"] != "PASS":
                failures.append(criterion)
            continue
        unsupported.append(criterion)
    if failures:
        state = "FAILED"
        reason = "One or more explicit local artifact criteria failed."
    elif unsupported or not checked:
        state = "UNVERIFIABLE"
        reason = "The acceptance criteria require an independent verifier not available locally."
    else:
        state = "VERIFIED"
        reason = "All explicit local artifact criteria were verified."
    evidence: Mapping[str, Any] = {
        "artifact_digest": capture.artifact_digest,
        "checked_criteria": checked,
        "failed_criteria": failures,
        "state": state,
        "unsupported_count": len(unsupported),
        "verifier_evidence": verifier_evidence,
    }
    return LocalVerification(
        state=state,
        evidence_digest=domain_digest("loopskill-local-verification-v1\n", evidence),
        checked_criteria=tuple(checked),
        reason=reason,
    )


def _verifier_document(raw: str, expected: frozenset[str]) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid verifier JSON") from exc
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("invalid verifier shape")
    return value


def _verifier_cwd(root: Path, value: Any) -> Path:
    relative = _validate_relative_cwd(value)
    resolved_root = root.resolve(strict=True)
    if relative is None:
        candidate = resolved_root
    else:
        candidate = (root / relative).resolve(strict=True)
    if (
        candidate != resolved_root
        and resolved_root not in candidate.parents
    ) or not candidate.is_dir() or candidate.is_symlink():
        raise ArtifactCaptureError(
            "PATH_CONFINEMENT_VIOLATION", "verifier cwd escapes workspace"
        )
    return candidate


def _validate_relative_cwd(value: Any) -> str | None:
    if not isinstance(value, str):
        raise ValueError("invalid verifier cwd")
    return None if value == "." else normalize_relative_path(value)


def _verifier_argv(value: Any) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= 32
        or not all(
            isinstance(item, str)
            and item
            and "\x00" not in item
            and len(item.encode("utf-8")) <= 1024
            for item in value
        )
    ):
        raise ValueError("invalid verifier argv")
    return tuple(value)


def _verifier_environment(value: Any) -> dict[str, str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise ValueError("invalid verifier environment")
    names = set(value)
    if len(names) != len(value) or not names <= _INHERITED_ENV_ALLOWLIST:
        raise ValueError("unsafe verifier environment")
    return {name: os.environ[name] for name in sorted(names) if name in os.environ}


def _run_verifier_process(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: int,
) -> tuple[int, bytes, bytes, int]:
    started = time.monotonic_ns()
    process = subprocess.Popen(
        list(argv),
        cwd=str(cwd),
        env=dict(environment),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        start_new_session=True,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    streams = {"stdout": process.stdout, "stderr": process.stderr}
    selector = selectors.DefaultSelector()
    output = {"stdout": bytearray(), "stderr": bytearray()}
    for channel, stream in streams.items():
        os.set_blocking(stream.fileno(), False)
        selector.register(stream.fileno(), selectors.EVENT_READ, channel)
    deadline = time.monotonic() + timeout_seconds
    timed_out = False
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            events = selector.select(min(remaining, 0.25))
            if not events and process.poll() is not None:
                events = [
                    (key, selectors.EVENT_READ)
                    for key in tuple(selector.get_map().values())
                ]
            for key, _mask in events:
                try:
                    chunk = os.read(key.fd, 65_536)
                except BlockingIOError:
                    continue
                except OSError as exc:
                    raise ValueError("verifier output stream failed") from exc
                if not chunk:
                    selector.unregister(key.fd)
                    continue
                channel = str(key.data)
                output[channel].extend(chunk)
                if len(output[channel]) > _MAX_VERIFIER_OUTPUT:
                    raise ValueError("verifier output exceeded bound")
        if not timed_out:
            try:
                process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
    except BaseException:
        _stop_verifier_process(process)
        raise
    finally:
        selector.close()
        for stream in streams.values():
            if not stream.closed:
                stream.close()
    if timed_out:
        _stop_verifier_process(process)
        returncode = -signal.SIGTERM
    else:
        returncode = int(process.returncode)
        _stop_verifier_process(process)
    elapsed_ms = (time.monotonic_ns() - started) // 1_000_000
    stdout = bytes(output["stdout"])
    stderr = bytes(output["stderr"])
    return returncode, stdout, stderr, elapsed_ms


def _stop_verifier_process(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait()
        return
    if process.poll() is None:
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            process.wait()
            return
        except PermissionError:
            pass
        time.sleep(0.01)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        process.wait()
        return
    if process.poll() is None:
        process.wait(timeout=2)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            pass
        time.sleep(0.01)
    raise ValueError("verifier process group did not close")


def _verify_command(root: Path, raw: str) -> Mapping[str, Any]:
    value = _verifier_document(
        raw,
        frozenset({"argv", "cwd", "env", "expected_exit", "timeout_seconds"}),
    )
    argv = _verifier_argv(value["argv"])
    cwd = _verifier_cwd(root, value["cwd"])
    environment = _verifier_environment(value["env"])
    expected_exit = value["expected_exit"]
    timeout_seconds = value["timeout_seconds"]
    if (
        isinstance(expected_exit, bool)
        or not isinstance(expected_exit, int)
        or isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not 1 <= timeout_seconds <= 600
    ):
        raise ValueError("invalid command verifier bound")
    returncode, stdout, stderr, elapsed_ms = _run_verifier_process(
        argv,
        cwd=cwd,
        environment=environment,
        timeout_seconds=timeout_seconds,
    )
    return {
        "argv_digest": domain_digest("loopskill-verifier-argv-v1\n", list(argv)),
        "elapsed_ms": elapsed_ms,
        "returncode": returncode,
        "state": "PASS" if returncode == expected_exit else "FAILED",
        "stderr_bytes": len(stderr),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "stdout_bytes": len(stdout),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "type": "command",
    }


def _verify_http(root: Path, raw: str) -> Mapping[str, Any]:
    value = _verifier_document(
        raw,
        frozenset(
            {
                "cwd",
                "env",
                "port",
                "routes",
                "start_argv",
                "startup_timeout_seconds",
            }
        ),
    )
    cwd = _verifier_cwd(root, value["cwd"])
    argv = _verifier_argv(value["start_argv"])
    environment = _verifier_environment(value["env"])
    port = value["port"]
    startup_timeout = value["startup_timeout_seconds"]
    routes = value["routes"]
    if (
        isinstance(port, bool)
        or not isinstance(port, int)
        or not 1024 <= port <= 65535
        or isinstance(startup_timeout, bool)
        or not isinstance(startup_timeout, int)
        or not 1 <= startup_timeout <= 60
        or not isinstance(routes, list)
        or not 1 <= len(routes) <= 16
    ):
        raise ValueError("invalid HTTP verifier bound")
    normalized_routes = []
    for route in routes:
        if (
            not isinstance(route, dict)
            or set(route) != {"contains", "path", "status"}
            or not _valid_loopback_route(route["path"])
            or not isinstance(route["contains"], str)
            or isinstance(route["status"], bool)
            or not isinstance(route["status"], int)
        ):
            raise ValueError("invalid HTTP route verifier")
        normalized_routes.append(route)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", port))
    except OSError as exc:
        raise ValueError("HTTP verifier port is already in use") from exc
    process = subprocess.Popen(
        list(argv),
        cwd=str(cwd),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
        start_new_session=True,
    )
    responses: list[Mapping[str, Any]] = []
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirect()
    )
    deadline = time.monotonic() + startup_timeout
    try:
        for route in normalized_routes:
            response_body = None
            response_status = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                try:
                    with opener.open(
                        f"http://127.0.0.1:{port}{route['path']}", timeout=1
                    ) as response:
                        response_body = response.read(256 * 1024)
                        response_status = response.status
                    break
                except urllib.error.HTTPError as response:
                    try:
                        response_body = response.read(256 * 1024)
                        response_status = response.code
                    finally:
                        response.close()
                    break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.05)
            passed = (
                response_status == route["status"]
                and response_body is not None
                and route["contains"].encode("utf-8") in response_body
                and process.poll() is None
            )
            responses.append(
                {
                    "body_sha256": (
                        None
                        if response_body is None
                        else hashlib.sha256(response_body).hexdigest()
                    ),
                    "path": route["path"],
                    "state": "PASS" if passed else "FAILED",
                    "status": response_status,
                }
            )
    finally:
        _stop_verifier_process(process)
    stdout = b""
    stderr = b""
    return {
        "argv_digest": domain_digest("loopskill-verifier-argv-v1\n", list(argv)),
        "process_returncode": process.returncode,
        "responses": responses,
        "state": (
            "PASS"
            if responses and all(item["state"] == "PASS" for item in responses)
            else "FAILED"
        ),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "type": "http",
    }
