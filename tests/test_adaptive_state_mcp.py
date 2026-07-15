from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from state_runtime_support import *  # noqa: F403

import adaptive_state_mcp as mcp  # noqa: E402


def synthetic_host_attestation() -> TrustedHostAttestation:  # noqa: F405
    return TrustedHostAttestation(  # noqa: F405
        boundary=TRUSTED_HOST_BOUNDARY,  # noqa: F405
        parent_pid=4242,
        parent_executable=(
            "/Applications/ChatGPT.app/Contents/Resources/codex"
        ),
        parent_identifier=OPENAI_CODE_SIGN_IDENTIFIER,  # noqa: F405
        parent_team_id=OPENAI_CODE_SIGN_TEAM_ID,  # noqa: F405
        parent_cdhash="b" * 64,
    )


class McpHarness:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.state = Harness(root)  # noqa: F405
        initialized, _ = self.state.initialize()
        if not initialized["ok"]:
            raise AssertionError(initialized)
        self.server = mcp.AdaptiveStateMcpServer(synthetic_host_attestation())
        response = self.server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            }
        )
        if response is None or "result" not in response:
            raise AssertionError(response)

    @staticmethod
    def metadata(
        *,
        turn_id: str = "real-app-turn-1",
        session_id: str = "controller-1",
    ) -> dict[str, object]:
        return {
            "threadId": "controller-1",
            "x-codex-turn-metadata": {
                "session_id": session_id,
                "thread_id": "controller-1",
                "turn_id": turn_id,
            },
        }

    def route_request(
        self,
        suffix: str,
        *,
        claimed_turn_id: str | None = None,
    ) -> dict[str, object]:
        mutation: dict[str, object] = {
            "type": "ACQUIRE_LEASE",
            "routing_turn_id": f"route-{suffix}",
            "lease_id": f"lease-{suffix}",
            "owner_kind": "GOAL_TURN",
            "owner_identity": "controller-1",
            "observed_at": T1,  # noqa: F405
            "expires_at": T4,  # noqa: F405
        }
        if claimed_turn_id is not None:
            mutation["controller_turn_id"] = claimed_turn_id
        request = self.state.make_request(mutation)
        if claimed_turn_id is None:
            request["mutation"].pop("controller_turn_id", None)
        return request

    def call(
        self,
        request: dict[str, object],
        *,
        meta: dict[str, object] | None = None,
        arguments_extra: dict[str, object] | None = None,
    ) -> dict[str, object]:
        arguments: dict[str, object] = {
            "root": str(self.root),
            "request": request,
        }
        arguments.update(arguments_extra or {})
        params: dict[str, object] = {
            "name": mcp.MCP_TOOL_NAME,
            "arguments": arguments,
        }
        if meta is not None:
            params["_meta"] = meta
        response = self.server.handle(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": params,
            }
        )
        if response is None:
            raise AssertionError("missing MCP response")
        return response["result"]["structuredContent"]


class AdaptiveStateMcpTests(unittest.TestCase):
    def test_codesign_cdhash_parser_does_not_require_last_output_line(self) -> None:
        cdhash = "1" * 40
        details = f"Executable=/Applications/Codex\nCDHash={cdhash}\nSignature size=1\n"
        match = mcp.CDHASH_RE.search(details)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), cdhash)

    def test_initialize_and_tool_schema(self) -> None:
        server = mcp.AdaptiveStateMcpServer(synthetic_host_attestation())
        initialized = server.handle(
            {
                "jsonrpc": "2.0",
                "id": "init",
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            }
        )
        self.assertEqual(initialized["result"]["protocolVersion"], "2025-06-18")
        listed = server.handle(
            {"jsonrpc": "2.0", "id": "list", "method": "tools/list"}
        )
        tool = listed["result"]["tools"][0]
        self.assertEqual(tool["name"], mcp.MCP_TOOL_NAME)
        self.assertEqual(tool["inputSchema"]["required"], ["root", "request"])

    def test_forged_argument_metadata_cannot_cross_host_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = McpHarness(Path(temporary))
            request = harness.route_request("forged")
            before = persisted_snapshot(Path(temporary))  # noqa: F405
            response = harness.call(
                request,
                arguments_extra={"_meta": harness.metadata()},
            )
            self.assertEqual(response["status"], "BLOCKED_BY_APP_ATTESTATION")
            self.assertEqual(before, persisted_snapshot(Path(temporary)))  # noqa: F405

    def test_bridge_injects_real_turn_and_rejects_second_route(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = McpHarness(Path(temporary))
            turn_meta = harness.metadata(turn_id="real-app-turn-shared")
            first = harness.call(harness.route_request("first"), meta=turn_meta)
            self.assertTrue(first["ok"], first)
            lease_claim = first["result"]["lease_claim"]
            state = harness.state.state()
            self.assertIn(
                "real-app-turn-shared",
                state["consumed_controller_turn_ids"],
            )

            released = harness.state.apply(
                {
                    "type": "RELEASE_LEASE",
                    "lease_claim": lease_claim,
                    "observed_at": T1,  # noqa: F405
                    "reason_code": "NO_ROUTE_READY",
                }
            )
            self.assertTrue(released["ok"], released)
            before = persisted_snapshot(Path(temporary))  # noqa: F405
            second = harness.call(harness.route_request("second"), meta=turn_meta)
            self.assertEqual(second["status"], "CONTROLLER_TURN_ALREADY_ROUTED")
            self.assertEqual(before, persisted_snapshot(Path(temporary)))  # noqa: F405

    def test_model_claim_must_match_host_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = McpHarness(Path(temporary))
            request = harness.route_request(
                "claim-mismatch",
                claimed_turn_id="model-invented-turn",
            )
            before = persisted_snapshot(Path(temporary))  # noqa: F405
            response = harness.call(
                request,
                meta=harness.metadata(turn_id="real-app-turn"),
            )
            self.assertEqual(
                response["status"], "CONTROLLER_TURN_ATTESTATION_MISMATCH"
            )
            self.assertEqual(before, persisted_snapshot(Path(temporary)))  # noqa: F405

    def test_outer_thread_mismatch_is_rejected_without_state_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = McpHarness(Path(temporary))
            meta = harness.metadata()
            meta["threadId"] = "different-thread"
            before = persisted_snapshot(Path(temporary))  # noqa: F405
            response = harness.call(harness.route_request("thread"), meta=meta)
            self.assertEqual(response["status"], "APP_TURN_ATTESTATION_INVALID")
            self.assertEqual(before, persisted_snapshot(Path(temporary)))  # noqa: F405

    def test_fork_session_identity_may_differ_from_thread_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = McpHarness(Path(temporary))
            meta = harness.metadata(
                turn_id="forked-app-turn",
                session_id="root-session-tree",
            )
            response = harness.call(harness.route_request("fork"), meta=meta)
            self.assertTrue(response["ok"], response)
            self.assertIn(
                "forked-app-turn",
                harness.state.state()["consumed_controller_turn_ids"],
            )

    def test_missing_or_malformed_host_turn_fields_are_zero_effect(self) -> None:
        scenarios = {
            "missing-session": ("session_id", None),
            "missing-turn": ("turn_id", None),
            "non-string-thread": ("thread_id", ["controller-1"]),
            "empty-session": ("session_id", ""),
        }
        for name, (field, replacement) in scenarios.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                harness = McpHarness(root)
                meta = harness.metadata()
                turn_meta = meta["x-codex-turn-metadata"]
                assert isinstance(turn_meta, dict)
                if replacement is None:
                    turn_meta.pop(field)
                else:
                    turn_meta[field] = replacement
                before = persisted_snapshot(root)  # noqa: F405
                response = harness.call(harness.route_request(name), meta=meta)
                self.assertEqual(response["status"], "APP_TURN_ATTESTATION_INVALID")
                self.assertEqual(before, persisted_snapshot(root))  # noqa: F405

    def test_non_route_mutation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = McpHarness(Path(temporary))
            request = harness.state.make_request(
                {
                    "type": "SET_RUN_CONTROL",
                    "run_control": "PAUSE",
                    "observed_at": T1,  # noqa: F405
                }
            )
            before = persisted_snapshot(Path(temporary))  # noqa: F405
            response = harness.call(request, meta=harness.metadata())
            self.assertEqual(response["status"], "MCP_ROUTE_MUTATION_TYPE_INVALID")
            self.assertEqual(before, persisted_snapshot(Path(temporary)))  # noqa: F405

    def test_unattested_server_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = McpHarness(Path(temporary))
            harness.server.host_attestation = None
            harness.server.host_error = mcp.McpBridgeError(
                "APP_PARENT_ATTESTATION_INVALID",
                "/parent_command",
            )
            before = persisted_snapshot(Path(temporary))  # noqa: F405
            response = harness.call(
                harness.route_request("host"),
                meta=harness.metadata(),
            )
            self.assertEqual(response["status"], "APP_PARENT_ATTESTATION_INVALID")
            self.assertEqual(before, persisted_snapshot(Path(temporary)))  # noqa: F405

    def test_exact_replay_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = McpHarness(Path(temporary))
            request = harness.route_request("replay")
            meta = harness.metadata(turn_id="real-app-turn-replay")
            first = harness.call(request, meta=meta)
            self.assertTrue(first["ok"], first)
            before = persisted_snapshot(Path(temporary))  # noqa: F405
            replay = harness.call(request, meta=meta)
            self.assertEqual(replay["status"], "STATE_WRITE_ALREADY_APPLIED")
            self.assertEqual(before, persisted_snapshot(Path(temporary)))  # noqa: F405

    def test_direct_shell_launch_cannot_attest_as_codex_app_server(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = Harness(root)  # noqa: F405
            initialized, _ = state.initialize()
            self.assertTrue(initialized["ok"], initialized)
            request = state.make_request(
                {
                    "type": "ACQUIRE_LEASE",
                    "routing_turn_id": "direct-shell-route",
                    "lease_id": "direct-shell-lease",
                    "owner_kind": "GOAL_TURN",
                    "owner_identity": "controller-1",
                    "observed_at": T1,  # noqa: F405
                    "expires_at": T4,  # noqa: F405
                }
            )
            request["mutation"].pop("controller_turn_id", None)
            before = persisted_snapshot(root)  # noqa: F405
            messages = [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"},
                },
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": mcp.MCP_TOOL_NAME,
                        "arguments": {"root": str(root), "request": request},
                        "_meta": McpHarness.metadata(),
                    },
                },
            ]
            completed = subprocess.run(
                [sys.executable, str(SCRIPTS / "adaptive_state_mcp.py")],  # noqa: F405
                input="".join(
                    json.dumps(item, separators=(",", ":")) + "\n"
                    for item in messages
                ),
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            responses = [json.loads(line) for line in completed.stdout.splitlines()]
            result = responses[1]["result"]["structuredContent"]
            self.assertIn(
                result["status"],
                {
                    "APP_PARENT_ATTESTATION_INVALID",
                    "APP_PARENT_ATTESTATION_UNAVAILABLE",
                    "APP_PARENT_ATTESTATION_UNSUPPORTED",
                },
            )
            self.assertEqual(before, persisted_snapshot(root))  # noqa: F405


class McpFrameReaderTests(unittest.TestCase):
    def test_multiple_frames_and_eof_compatibility(self) -> None:
        stream = io.BytesIO(b'{"id":1}\n{"id":2}')
        reader = mcp.McpFrameReader(stream)
        self.assertEqual(reader.read(), {"id": 1})
        self.assertEqual(reader.read(), {"id": 2})
        self.assertIsNone(reader.read())

    def test_duplicate_key_and_invalid_utf8_are_rejected(self) -> None:
        for payload, status in (
            (b'{"id":1,"id":2}\n', "MCP_INPUT_JSON_INVALID"),
            (b'{"id":"\xff"}\n', "MCP_INPUT_UTF8_INVALID"),
        ):
            with self.subTest(status=status):
                with self.assertRaises(mcp.McpBridgeError) as context:
                    mcp.McpFrameReader(io.BytesIO(payload)).read()
                self.assertEqual(context.exception.code, status)

    def test_oversized_frame_is_rejected(self) -> None:
        with self.assertRaises(mcp.McpBridgeError) as context:
            mcp.McpFrameReader(io.BytesIO(b"x" * 9 + b"\n"), max_bytes=8).read()
        self.assertEqual(context.exception.code, "MCP_INPUT_TOO_LARGE")

    def test_partial_pipe_times_out_and_leaves_no_reader_process(self) -> None:
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, b'{"jsonrpc":')
            started = time.monotonic()
            with os.fdopen(read_fd, "rb", closefd=False) as stream:
                with self.assertRaises(mcp.McpBridgeError) as context:
                    mcp.McpFrameReader(
                        stream,
                        partial_timeout_seconds=0.05,
                    ).read()
            self.assertEqual(context.exception.code, "MCP_INPUT_TIMEOUT")
            self.assertLess(time.monotonic() - started, 1.0)
        finally:
            os.close(read_fd)
            os.close(write_fd)


if __name__ == "__main__":
    unittest.main()
