#!/usr/bin/env python3
"""JSON-only command line adapter for the Adaptive state runtime."""

from __future__ import annotations

import json
import sys
from typing import Any

from loop_architect.state_runtime import (
    CRASH_STAGES,
    AdaptiveStateRuntime,
    InjectedCrash,
    RuntimeRejection,
    materialize_dispatch_payload,
    verify_dispatch_payload_against_state,
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
        elif token == "--crash-at" and index + 1 < len(argv):
            crash_at = argv[index + 1]
            index += 2
        else:
            raise ValueError(token)
    if mode in {"apply", "recover", "payload-verify"} and root is None:
        raise ValueError("--root")
    if mode == "payload-materialize" and root is not None:
        raise ValueError("--root")
    if crash_at is not None and crash_at not in CRASH_STAGES:
        raise ValueError("--crash-at")
    if mode.startswith("payload-") and crash_at is not None:
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

    return json.loads(payload, object_pairs_hook=no_duplicates)


def _emit(response: dict[str, Any]) -> None:
    sys.stdout.write(
        json.dumps(
            response,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        )
        + "\n"
    )


def main(argv: list[str] | None = None) -> int:
    try:
        root, mode, crash_at = _parse_args(list(sys.argv[1:] if argv is None else argv))
    except ValueError as exc:
        _emit(_response("CLI_ARGUMENT_INVALID", "/argv", {"argument": str(exc)}))
        return 2

    try:
        payload = sys.stdin.read()
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
        elif mode == "payload-verify":
            assert root is not None
            response = verify_dispatch_payload_against_state(root, payload)
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
