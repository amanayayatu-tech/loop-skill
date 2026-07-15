#!/usr/bin/env python3
"""JSON-only command line adapter for the Adaptive state runtime."""

from __future__ import annotations

import json
import os
import select
import stat
import sys
import time
from typing import Any

from loop_architect.state_runtime import (
    CRASH_STAGES,
    AdaptiveStateRuntime,
    InjectedCrash,
    RuntimeRejection,
    materialize_dispatch_payload,
    verify_dispatch_payload_against_state,
)
from loop_architect.human_control import build_failure_fingerprint


INPUT_TRANSPORT_TIMEOUT_SECONDS = 30.0
INPUT_TRANSPORT_MAX_BYTES = 4_000_000
INPUT_TRANSPORT_CHUNK_BYTES = 64 * 1024


class InputTransportError(ValueError):
    """Fail-closed error raised while receiving one bounded stdin frame."""

    def __init__(self, code: str, *, bytes_received: int) -> None:
        super().__init__(code)
        self.code = code
        self.details = {"bytes_received": bytes_received}


def _decode_transport(data: bytes, *, final: bool) -> str | None:
    try:
        return data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        if not final and exc.reason == "unexpected end of data" and exc.end == len(data):
            return None
        raise InputTransportError(
            "INPUT_TRANSPORT_UTF8_INVALID", bytes_received=len(data)
        ) from exc


def _json_frame_complete(payload: str, *, payload_verify: bool) -> bool:
    candidate = payload
    if payload_verify:
        separator = candidate.find("\n")
        if separator < 0:
            return False
        candidate = candidate[separator + 1 :]
    stripped = candidate.lstrip()
    if not stripped:
        return payload.endswith("\n") and not payload_verify
    try:
        _, end = json.JSONDecoder().raw_decode(stripped)
    except json.JSONDecodeError:
        return payload.endswith("\n")
    # A complete top-level JSON value is one frame. Any already-buffered
    # trailing bytes are returned too so the strict parser can reject them.
    return end > 0


def _read_regular_stdin(fd: int, *, max_bytes: int) -> str:
    chunks: list[bytes] = []
    received = 0
    while True:
        chunk = os.read(fd, INPUT_TRANSPORT_CHUNK_BYTES)
        if not chunk:
            break
        received += len(chunk)
        if received > max_bytes:
            raise InputTransportError(
                "INPUT_TRANSPORT_TOO_LARGE", bytes_received=received
            )
        chunks.append(chunk)
    decoded = _decode_transport(b"".join(chunks), final=True)
    assert decoded is not None
    return decoded


def _read_bounded_stdin(
    mode: str,
    *,
    timeout_seconds: float = INPUT_TRANSPORT_TIMEOUT_SECONDS,
    max_bytes: int = INPUT_TRANSPORT_MAX_BYTES,
) -> str:
    """Read one complete request frame without requiring the writer to close stdin."""

    fd = sys.stdin.fileno()
    if stat.S_ISREG(os.fstat(fd).st_mode):
        return _read_regular_stdin(fd, max_bytes=max_bytes)

    deadline = time.monotonic() + timeout_seconds
    data = bytearray()
    while True:
        decoded = _decode_transport(bytes(data), final=False)
        if decoded is not None and _json_frame_complete(
            decoded, payload_verify=mode == "payload-verify"
        ):
            return decoded
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise InputTransportError(
                "INPUT_TRANSPORT_TIMEOUT", bytes_received=len(data)
            )
        readable, _, _ = select.select([fd], [], [], remaining)
        if not readable:
            raise InputTransportError(
                "INPUT_TRANSPORT_TIMEOUT", bytes_received=len(data)
            )
        chunk = os.read(fd, INPUT_TRANSPORT_CHUNK_BYTES)
        if not chunk:
            decoded = _decode_transport(bytes(data), final=True)
            assert decoded is not None
            return decoded
        data.extend(chunk)
        if len(data) > max_bytes:
            raise InputTransportError(
                "INPUT_TRANSPORT_TOO_LARGE", bytes_received=len(data)
            )


def _response(code: str, path: str = "/", details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "status": code,
        "error": {"code": code, "path": path, "details": details or {}},
        "state_version": 0,
        "evidence_paths": [],
        "external_actions": [],
        "external_action_count": 0,
    }


def _parse_args(argv: list[str]) -> tuple[str | None, str, str | None]:
    root: str | None = None
    mode = "apply"
    crash_at: str | None = None
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--root" and index + 1 < len(argv):
            root = argv[index + 1]
            index += 2
        elif token == "--recover":
            if mode != "apply":
                raise ValueError(token)
            mode = "recover"
            index += 1
        elif token == "--payload-materialize":
            if mode != "apply":
                raise ValueError(token)
            mode = "payload-materialize"
            index += 1
        elif token == "--payload-verify":
            if mode != "apply":
                raise ValueError(token)
            mode = "payload-verify"
            index += 1
        elif token == "--report-stage":
            if mode != "apply":
                raise ValueError(token)
            mode = "report-stage"
            index += 1
        elif token == "--external-receipt-stage":
            if mode != "apply":
                raise ValueError(token)
            mode = "external-receipt-stage"
            index += 1
        elif token == "--fingerprint-normalize":
            if mode != "apply":
                raise ValueError(token)
            mode = "fingerprint-normalize"
            index += 1
        elif token == "--crash-at" and index + 1 < len(argv):
            crash_at = argv[index + 1]
            index += 2
        else:
            raise ValueError(token)
    if mode in {
        "apply",
        "recover",
        "payload-verify",
        "report-stage",
        "external-receipt-stage",
    } and root is None:
        raise ValueError("--root")
    if mode in {"payload-materialize", "fingerprint-normalize"} and root is not None:
        raise ValueError("--root")
    if crash_at is not None and crash_at not in CRASH_STAGES:
        raise ValueError("--crash-at")
    if (
        mode.startswith("payload-")
        or mode in {
            "fingerprint-normalize",
            "report-stage",
            "external-receipt-stage",
        }
    ) and crash_at is not None:
        raise ValueError("--crash-at")
    return root, mode, crash_at


def _load_request(payload: str) -> Any:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    def reject_non_finite(value: str) -> None:
        raise ValueError(f"NON_FINITE_JSON_NUMBER:{value}")

    return json.loads(
        payload,
        object_pairs_hook=no_duplicates,
        parse_constant=reject_non_finite,
    )


def _emit(response: dict[str, Any]) -> None:
    payload = json.dumps(
        response,
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    )
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace(
        "&", "\\u0026"
    )
    sys.stdout.write(payload + "\n")


def main(argv: list[str] | None = None) -> int:
    try:
        root, mode, crash_at = _parse_args(list(sys.argv[1:] if argv is None else argv))
    except ValueError as exc:
        _emit(_response("CLI_ARGUMENT_INVALID", "/argv", {"argument": str(exc)}))
        return 2

    try:
        payload = "" if mode == "recover" else _read_bounded_stdin(mode)
        if mode == "payload-materialize":
            if not payload.strip():
                response = _response("DISPATCH_MATERIALIZATION_INPUT_INVALID", "/")
            else:
                try:
                    specification = _load_request(payload)
                    response = materialize_dispatch_payload(specification)
                except (json.JSONDecodeError, ValueError) as exc:
                    response = _response(
                        "DISPATCH_MATERIALIZATION_INPUT_INVALID",
                        "/",
                        {"error_type": type(exc).__name__},
                    )
        elif mode == "fingerprint-normalize":
            try:
                value = _load_request(payload)
                if not isinstance(value, dict):
                    raise ValueError("object required")
                fingerprint = build_failure_fingerprint(**value)
                response = {
                    "ok": True,
                    "status": "FAILURE_FINGERPRINT_NORMALIZED",
                    "fingerprint": fingerprint,
                    "external_actions": [],
                    "external_action_count": 0,
                }
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                response = _response(
                    "FAILURE_FINGERPRINT_INPUT_INVALID",
                    "/",
                    {"error_type": type(exc).__name__},
                )
        elif mode == "payload-verify":
            assert root is not None
            response = verify_dispatch_payload_against_state(root, payload)
        elif mode == "report-stage":
            assert root is not None
            try:
                request = _load_request(payload)
            except (json.JSONDecodeError, ValueError) as exc:
                response = _response(
                    "FORMAL_REPORT_STAGE_INPUT_INVALID",
                    "/",
                    {"error_type": type(exc).__name__},
                )
            else:
                response = AdaptiveStateRuntime(root).stage_formal_report(request)
        elif mode == "external-receipt-stage":
            assert root is not None
            try:
                request = _load_request(payload)
            except (json.JSONDecodeError, ValueError) as exc:
                response = _response(
                    "EXTERNAL_RECEIPT_INPUT_INVALID",
                    "/",
                    {"error_type": type(exc).__name__},
                )
            else:
                response = AdaptiveStateRuntime(root).stage_external_receipt(request)
        else:
            assert root is not None
            runtime = AdaptiveStateRuntime(root, crash_at=crash_at)
            if mode == "recover":
                response = runtime.recover()
            elif not payload.strip():
                response = _response("REQUEST_JSON_INVALID", "/")
            else:
                try:
                    request = _load_request(payload)
                except (json.JSONDecodeError, ValueError) as exc:
                    response = _response(
                        "REQUEST_JSON_INVALID",
                        "/",
                        {"error_type": type(exc).__name__},
                    )
                else:
                    response = runtime.apply(request)
    except InputTransportError as exc:
        response = _response(exc.code, "/stdin", exc.details)
    except RuntimeRejection as exc:
        response = _response(exc.code, exc.path, exc.details)
    except InjectedCrash as exc:
        response = _response("INJECTED_CRASH", "/", {"stage": exc.stage})
    except Exception as exc:
        response = _response(
            "INTERNAL_ERROR",
            "/",
            {"error_type": type(exc).__name__},
        )
    _emit(response)
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
