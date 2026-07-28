from __future__ import annotations

import json
import os
import selectors
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "codex-loop-prompt-architect" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from loop_architect.v4_adapters.codex.app_server_provider import (  # noqa: E402
    CodexAppServerProvider,
    HostResponseLost,
    HostUnavailable,
    _AppServerSession,
    _AppServerProtocolContract,
    _protocol_contract_from_schemas,
    _request_marker,
)
import loop_architect.v4_adapters.codex.app_server_provider as provider_module  # noqa: E402
from loop_architect.v4_alpha.protocol import domain_digest  # noqa: E402


NOW = datetime(2026, 7, 27, tzinfo=timezone.utc)
KEY = "effect-machine-owned-0001"


def protocol_contract(
    *,
    thread_id_path: tuple[str, ...] = ("thread", "id"),
    turn_id_path: tuple[str, ...] = ("turnId",),
) -> _AppServerProtocolContract:
    return _AppServerProtocolContract(
        schema_digest="f" * 64,
        thread_id_path=thread_id_path,
        turn_id_path=turn_id_path,
    )


def protocol_schemas(
    *, thread_direct: bool = False, turn_direct: bool = False
):
    thread_response = {
        "title": "ThreadStartResponse",
        "type": "object",
        "required": ["threadId" if thread_direct else "thread"],
        "properties": (
            {"threadId": {"type": "string"}}
            if thread_direct
            else {"thread": {"$ref": "#/definitions/Thread"}}
        ),
        "definitions": {
            "Thread": {
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "string"}},
            }
        },
    }
    turn_response = {
        "title": "TurnStartResponse",
        "type": "object",
        "required": ["turnId" if turn_direct else "turn"],
        "properties": (
            {"turnId": {"type": "string"}}
            if turn_direct
            else {"turn": {"$ref": "#/definitions/Turn"}}
        ),
        "definitions": {
            "Turn": {
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "string"}},
            }
        },
    }
    return {
        "thread_start_params": {
            "title": "ThreadStartParams",
            "type": "object",
            "properties": {
                "approvalPolicy": {"enum": ["on-request"]},
                "cwd": {"type": ["string", "null"]},
                "ephemeral": {"type": ["boolean", "null"]},
                "sandbox": {"enum": ["workspace-write"]},
                "threadSource": {"type": ["string", "null"]},
            },
        },
        "thread_start_response": thread_response,
        "turn_start_params": {
            "title": "TurnStartParams",
            "type": "object",
            "required": ["input", "threadId"],
            "properties": {
                "clientUserMessageId": {"type": ["string", "null"]},
                "cwd": {"type": ["string", "null"]},
                "input": {
                    "type": "array",
                    "items": {
                        "oneOf": [
                            {
                                "type": "object",
                                "required": ["text", "type"],
                                "properties": {
                                    "text": {"type": "string"},
                                    "type": {"enum": ["text"]},
                                },
                            }
                        ]
                    },
                },
                "threadId": {"type": "string"},
            },
        },
        "turn_start_response": turn_response,
    }


def payload():
    return {
        "acceptance_criteria": ["one authoritative readback"],
        "authorization_boundaries": ["no publish"],
        "budget": "one automatic create attempt",
        "execution_mode": "STANDARD",
        "external_actions": [],
        "goal": "Create one bounded disposable task",
        "stop_conditions": ["stop on UNKNOWN"],
        "target_ref": "host-target-machine-owned",
        "write_scope": ["synthetic workspace"],
    }


class FakeSession:
    def __init__(self, replies):
        self.replies = replies
        self.calls = []
        self.closed = False

    def request(self, method, params):
        self.calls.append((method, dict(params)))
        reply = self.replies[method]
        return reply() if callable(reply) else reply

    def close(self):
        self.closed = True


class AppServerProviderTests(unittest.TestCase):
    def test_session_initialization_failure_closes_spawned_process(self):
        child_stdin, parent_stdin = os.pipe()
        parent_stdout, child_stdout = os.pipe()

        class Process:
            def __init__(self):
                self.stdin = os.fdopen(parent_stdin, "wb", buffering=0)
                self.stdout = os.fdopen(parent_stdout, "rb", buffering=0)
                self.wait = mock.Mock(return_value=0)
                self.terminate = mock.Mock()
                self.kill = mock.Mock()

        process = Process()
        try:
            with mock.patch.object(
                provider_module.subprocess, "Popen", return_value=process
            ), mock.patch.object(
                _AppServerSession,
                "_initialize",
                side_effect=HostUnavailable("synthetic initialize failure"),
            ), self.assertRaisesRegex(HostUnavailable, "synthetic initialize failure"):
                _AppServerSession(
                    ("synthetic-codex", "app-server", "--stdio"),
                    timeout_seconds=0.05,
                )
            self.assertTrue(process.stdin.closed)
            self.assertTrue(process.stdout.closed)
            process.wait.assert_called_once_with(timeout=2)
            process.terminate.assert_not_called()
            process.kill.assert_not_called()
        finally:
            os.close(child_stdin)
            os.close(child_stdout)

    def test_host_wire_allows_text_above_core_4k_within_32k_bound(self):
        read_fd, write_fd = os.pipe()
        session = object.__new__(_AppServerSession)
        session._stdin_fd = write_fd
        session._timeout_seconds = 0.2
        try:
            os.set_blocking(write_fd, False)
            text = "x" * 5_000
            session._write({"input": [{"text": text, "type": "text"}]})
            raw = os.read(read_fd, 8_192)
            self.assertTrue(raw.endswith(b"\n"))
            self.assertEqual(json.loads(raw)["input"][0]["text"], text)
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_host_wire_write_timeout_is_bounded(self):
        read_fd, write_fd = os.pipe()
        session = object.__new__(_AppServerSession)
        session._stdin_fd = write_fd
        session._timeout_seconds = 0.05
        try:
            os.set_blocking(write_fd, False)
            while True:
                try:
                    os.write(write_fd, b"x" * 65_536)
                except BlockingIOError:
                    break
            started = time.monotonic()
            with self.assertRaisesRegex(HostResponseLost, "request timed out"):
                session._write({"method": "bounded"})
            self.assertLess(time.monotonic() - started, 0.5)
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_partial_json_frame_cannot_defeat_response_timeout(self):
        read_fd, write_fd = os.pipe()
        stream = os.fdopen(read_fd, "rb", buffering=0)
        selector = selectors.DefaultSelector()
        selector.register(stream, selectors.EVENT_READ)
        session = object.__new__(_AppServerSession)
        session._stdout_fd = read_fd
        session._read_buffer = bytearray()
        try:
            os.set_blocking(read_fd, False)
            os.write(write_fd, b'{"partial":')
            started = time.monotonic()
            with self.assertRaisesRegex(HostResponseLost, "timed out"):
                session._read_frame(selector, started + 0.05)
            self.assertLess(time.monotonic() - started, 0.5)
        finally:
            selector.close()
            stream.close()
            os.close(write_fd)

    def test_buffered_host_frames_are_split_without_loss(self):
        read_fd, write_fd = os.pipe()
        stream = os.fdopen(read_fd, "rb", buffering=0)
        selector = selectors.DefaultSelector()
        selector.register(stream, selectors.EVENT_READ)
        session = object.__new__(_AppServerSession)
        session._stdout_fd = read_fd
        session._read_buffer = bytearray()
        try:
            os.set_blocking(read_fd, False)
            os.write(write_fd, b'{"id":1}\n{"id":2}\n')
            deadline = time.monotonic() + 1.0
            self.assertEqual(session._read_frame(selector, deadline), b'{"id":1}\n')
            self.assertEqual(session._read_frame(selector, deadline), b'{"id":2}\n')
        finally:
            selector.close()
            stream.close()
            os.close(write_fd)

    def provider(
        self,
        root,
        sessions,
        *,
        contract=None,
        protocol_probe=None,
        monotonic=None,
        sleeper=None,
    ):
        selected_contract = contract or protocol_contract()
        probe = protocol_probe or (lambda command, timeout: selected_contract)
        kwargs = {
            "command": ("synthetic-codex", "app-server", "--stdio"),
            "clock": lambda: NOW,
            "protocol_probe": probe,
        }
        if monotonic is not None:
            kwargs["monotonic"] = monotonic
        if sleeper is not None:
            kwargs["sleeper"] = sleeper
        provider = CodexAppServerProvider(
            root,
            **kwargs,
        )
        provider._open_session = lambda: sessions.pop(0)
        provider._session = lambda: _SessionContext(sessions.pop(0))
        return provider

    def test_capabilities_are_honest_about_missing_provider_idempotency(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary), [])
            snapshot = provider.capability_snapshot()
        rows = {item["name"]: item for item in snapshot["capabilities"]}
        self.assertEqual(rows["task_create"]["assurance"], "STRICT")
        self.assertEqual(rows["resource_read"]["assurance"], "STRICT")
        self.assertEqual(rows["lifecycle_readback"]["assurance"], "STRICT")
        self.assertEqual(rows["project_registration"]["availability"], "UNAVAILABLE")
        self.assertEqual(rows["thread_create"]["availability"], "UNAVAILABLE")
        self.assertEqual(rows["message_send"]["availability"], "UNAVAILABLE")
        self.assertEqual(rows["heartbeat"]["availability"], "UNAVAILABLE")
        self.assertEqual(rows["provider_idempotency"]["availability"], "UNAVAILABLE")
        self.assertEqual(rows["sandbox_receipt"]["availability"], "UNVERIFIABLE")
        self.assertEqual(rows["trust_receipt"]["availability"], "UNVERIFIABLE")
        self.assertEqual(rows["model_receipt"]["availability"], "UNVERIFIABLE")
        self.assertEqual(rows["memory"]["availability"], "UNVERIFIABLE")
        self.assertEqual(
            provider.metrics,
            {
                "delivery_readback_count": 0,
                "duplicate_invoke_rejection_count": 0,
                "lifecycle_read_count": 0,
                "provider_resend_count": 0,
                "task_create_count": 0,
                "task_result_read_count": 0,
                "terminal_wait_read_count": 0,
            },
        )

    def test_protocol_schema_contract_accepts_exact_known_response_profiles(self):
        nested = _protocol_contract_from_schemas(protocol_schemas())
        self.assertEqual(nested.thread_id_path, ("thread", "id"))
        self.assertEqual(nested.turn_id_path, ("turn", "id"))
        direct = _protocol_contract_from_schemas(
            protocol_schemas(thread_direct=True, turn_direct=True)
        )
        self.assertEqual(direct.thread_id_path, ("threadId",))
        self.assertEqual(direct.turn_id_path, ("turnId",))
        self.assertRegex(direct.schema_digest, r"^[0-9a-f]{64}$")

    def test_protocol_schema_drift_fails_before_any_host_session_or_create_count(self):
        drift = protocol_schemas()
        drift["turn_start_response"] = {
            "title": "TurnStartResponse",
            "type": "object",
            "required": ["futureTurn"],
            "properties": {"futureTurn": {"type": "string"}},
        }
        with self.assertRaisesRegex(HostUnavailable, "response shape drift"):
            _protocol_contract_from_schemas(drift)

        probe = mock.Mock(side_effect=HostUnavailable("synthetic schema drift"))
        with tempfile.TemporaryDirectory() as temporary:
            provider = CodexAppServerProvider(
                Path(temporary),
                command=("synthetic-codex", "app-server", "--stdio"),
                clock=lambda: NOW,
                protocol_probe=probe,
            )
            provider._open_session = mock.Mock(
                side_effect=AssertionError("Host session must not start")
            )
            with self.assertRaisesRegex(HostUnavailable, "synthetic schema drift"):
                provider.invoke("create_task", payload(), KEY)
        probe.assert_called_once()
        provider._open_session.assert_not_called()
        self.assertEqual(provider.metrics["task_create_count"], 0)
        self.assertEqual(provider.metrics["provider_resend_count"], 0)
        self.assertEqual(provider.metrics["duplicate_invoke_rejection_count"], 0)

    def test_response_parser_uses_preflight_paths_instead_of_version_literals(self):
        invoke = FakeSession(
            {
                "thread/start": {"threadId": "host-thread-direct"},
                "turn/start": {"turn": {"id": "host-turn-nested"}},
            }
        )
        probe = mock.Mock(
            return_value=protocol_contract(
                thread_id_path=("threadId",), turn_id_path=("turn", "id")
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(
                Path(temporary), [invoke], protocol_probe=probe
            )
            accepted = provider.invoke("create_task", payload(), KEY)
            provider.preflight()
        self.assertEqual(accepted["provider_id"], "host-thread-direct")
        self.assertEqual(provider.metrics["task_create_count"], 1)
        probe.assert_called_once()

    def test_create_and_authoritative_readback_bind_machine_marker(self):
        marker = _request_marker(KEY)
        invoke = FakeSession(
            {
                "thread/start": {"thread": {"id": "host-thread-1"}},
                "turn/start": {"turnId": "host-turn-1"},
            }
        )
        readback = FakeSession(
            {
                "thread/read": {
                    "thread": {
                        "id": "host-thread-1",
                        "preview": f"bounded task\n{marker}",
                        "status": {"type": "active", "activeFlags": []},
                    }
                }
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary), [invoke, readback])
            accepted = provider.invoke("create_task", payload(), KEY)
            observed = provider.readback("create_task", KEY)
        self.assertEqual(accepted["status"], "ACCEPTED")
        self.assertEqual(observed["status"], "OBSERVED")
        self.assertEqual(observed["trust"], "authoritative")
        self.assertEqual(invoke.calls[0][0], "thread/start")
        turn_payload = invoke.calls[1][1]
        self.assertEqual(turn_payload["clientUserMessageId"], KEY)
        prompt = turn_payload["input"][0]["text"]
        self.assertIn(marker, prompt)
        self.assertIn('"authorization_boundaries":["no publish"]', prompt)
        self.assertNotIn("host-target-machine-owned", prompt)
        self.assertEqual(provider.metrics["task_create_count"], 1)
        self.assertEqual(provider.metrics["delivery_readback_count"], 1)

    def test_any_second_create_is_rejected_before_a_second_host_session(self):
        invoke = FakeSession(
            {
                "thread/start": {"thread": {"id": "host-thread-1"}},
                "turn/start": {"turnId": "host-turn-1"},
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary), [invoke])
            provider.invoke("create_task", payload(), KEY)
            with self.assertRaisesRegex(HostUnavailable, "budget"):
                provider.invoke("create_task", payload(), KEY)
            with self.assertRaisesRegex(HostUnavailable, "budget"):
                provider.invoke("create_task", payload(), KEY + "-different")
            provider.close()
        self.assertEqual(provider.metrics["task_create_count"], 1)
        self.assertEqual(provider.metrics["provider_resend_count"], 0)
        self.assertEqual(provider.metrics["duplicate_invoke_rejection_count"], 2)
        self.assertTrue(invoke.closed)

    def test_invoke_preserves_original_failure_when_session_close_also_fails(self):
        class BrokenSession(FakeSession):
            def request(self, method, params):
                del method, params
                raise HostUnavailable("original Host failure")

            def close(self):
                raise RuntimeError("synthetic close failure")

        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary), [BrokenSession({})])
            with self.assertRaisesRegex(HostUnavailable, "original Host failure"):
                provider.invoke("create_task", payload(), KEY)
        self.assertEqual(provider.metrics["task_create_count"], 1)
        self.assertEqual(provider.metrics["provider_resend_count"], 0)

    def test_terminal_wait_polls_only_the_exact_created_turn_without_resend(self):
        marker = _request_marker(KEY)
        invoke = FakeSession(
            {
                "thread/start": {"thread": {"id": "host-thread-1"}},
                "turn/start": {"turnId": "host-turn-1"},
            }
        )
        observations = iter(
            [
                {
                    "thread": {
                        "id": "host-thread-1",
                        "preview": marker,
                        "status": {"type": "active"},
                        "turns": [{"id": "host-turn-1", "status": "inProgress"}],
                    }
                },
                {
                    "thread": {
                        "id": "host-thread-1",
                        "preview": marker,
                        "status": {"type": "idle"},
                        "turns": [{"id": "host-turn-1", "status": "completed"}],
                    }
                },
            ]
        )
        invoke.replies["thread/read"] = lambda: next(observations)
        sleeper = mock.Mock()
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(
                Path(temporary), [invoke], sleeper=sleeper
            )
            provider.invoke("create_task", payload(), KEY)
            provider.wait_for_terminal(
                timeout_seconds=1.0, poll_interval_seconds=0.01
            )
        self.assertEqual(
            [method for method, _ in invoke.calls],
            ["thread/start", "turn/start", "thread/read", "thread/read"],
        )
        self.assertTrue(invoke.closed)
        sleeper.assert_called_once_with(0.01)
        self.assertEqual(provider.metrics["terminal_wait_read_count"], 2)
        self.assertEqual(provider.metrics["task_create_count"], 1)
        self.assertEqual(provider.metrics["provider_resend_count"], 0)

    def test_terminal_wait_is_bounded_and_never_creates_again(self):
        marker = _request_marker(KEY)
        invoke = FakeSession(
            {
                "thread/start": {"thread": {"id": "host-thread-1"}},
                "turn/start": {"turnId": "host-turn-1"},
            }
        )
        invoke.replies["thread/read"] = {
            "thread": {
                "id": "host-thread-1",
                "preview": marker,
                "status": {"type": "active"},
                "turns": [{"id": "host-turn-1", "status": "inProgress"}],
            }
        }
        ticks = iter((0.0, 0.0, 1.0))
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(
                Path(temporary),
                [invoke],
                monotonic=lambda: next(ticks),
                sleeper=mock.Mock(),
            )
            provider.invoke("create_task", payload(), KEY)
            with self.assertRaisesRegex(HostUnavailable, "timed out"):
                provider.wait_for_terminal(
                    timeout_seconds=0.5, poll_interval_seconds=0.01
                )
        self.assertEqual(
            [method for method, _ in invoke.calls],
            ["thread/start", "turn/start", "thread/read"],
        )
        self.assertTrue(invoke.closed)
        self.assertEqual(provider.metrics["terminal_wait_read_count"], 1)
        self.assertEqual(provider.metrics["task_create_count"], 1)
        self.assertEqual(provider.metrics["provider_resend_count"], 0)

    def test_terminal_wait_reopens_read_only_session_after_lost_create_response(self):
        marker = _request_marker(KEY)
        recovered = FakeSession(
            {
                "thread/read": {
                    "thread": {
                        "id": "host-thread-recovered",
                        "preview": marker,
                        "status": {"type": "idle"},
                        "turns": [
                            {"id": "host-turn-recovered", "status": "completed"}
                        ],
                    }
                }
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary), [recovered])
            provider._records[KEY] = {
                "marker": marker,
                "target_ref": "",
                "thread_id": "host-thread-recovered",
                "turn_id": "",
            }
            provider.wait_for_terminal(timeout_seconds=1.0)
        self.assertTrue(recovered.closed)
        self.assertEqual(provider._records[KEY]["turn_id"], "host-turn-recovered")
        self.assertEqual(provider.metrics["task_create_count"], 0)
        self.assertEqual(provider.metrics["provider_resend_count"], 0)

    def test_crash_recovery_is_readback_only_and_ambiguous_identity_fails(self):
        marker = _request_marker(KEY)
        with tempfile.TemporaryDirectory() as temporary:
            workspace = str(Path(temporary).resolve())
            unique = FakeSession(
                {
                    "thread/list": {
                        "data": [
                            {
                                "cwd": workspace,
                                "id": "host-thread-recovered",
                                "preview": marker,
                                "status": {"type": "idle"},
                            }
                        ]
                    }
                }
            )
            ambiguous = FakeSession(
                {
                    "thread/list": {
                        "data": [
                            {"cwd": workspace, "id": "one", "preview": marker},
                            {"cwd": workspace, "id": "two", "preview": marker},
                        ]
                    }
                }
            )
            provider = self.provider(Path(temporary), [unique])
            recovered = provider.readback("create_task", KEY)
            self.assertEqual(recovered["provider_id"], "host-thread-recovered")
            provider = self.provider(Path(temporary), [ambiguous])
            with self.assertRaisesRegex(HostUnavailable, "ambiguous"):
                provider.readback("create_task", KEY)
        self.assertEqual([call[0] for call in unique.calls], ["thread/list"])

    def test_crash_readback_consumes_all_cursor_pages_before_zero_or_one(self):
        marker = _request_marker(KEY)
        with tempfile.TemporaryDirectory() as temporary:
            workspace = str(Path(temporary).resolve())
            pages = iter(
                (
                    {
                        "data": [
                            {
                                "cwd": workspace,
                                "id": "unrelated",
                                "preview": "not-the-marker",
                            }
                        ],
                        "nextCursor": "page-2",
                    },
                    {
                        "data": [
                            {
                                "cwd": workspace,
                                "id": "host-thread-page-2",
                                "preview": marker,
                                "status": {"type": "idle"},
                            }
                        ],
                        "nextCursor": None,
                    },
                )
            )
            listed = FakeSession({"thread/list": lambda: next(pages)})
            provider = self.provider(Path(temporary), [listed])
            recovered = provider.readback("create_task", KEY)
        self.assertEqual(recovered["provider_id"], "host-thread-page-2")
        self.assertNotIn("cursor", listed.calls[0][1])
        self.assertEqual(listed.calls[1][1]["cursor"], "page-2")
        self.assertTrue(all(call[1]["cwd"] == workspace for call in listed.calls))

    def test_cross_page_duplicate_marker_is_ambiguous(self):
        marker = _request_marker(KEY)
        with tempfile.TemporaryDirectory() as temporary:
            workspace = str(Path(temporary).resolve())
            pages = iter(
                (
                    {
                        "data": [
                            {"cwd": workspace, "id": "same", "preview": marker}
                        ],
                        "nextCursor": "again",
                    },
                    {
                        "data": [
                            {"cwd": workspace, "id": "same", "preview": marker}
                        ],
                        "nextCursor": None,
                    },
                )
            )
            provider = self.provider(
                Path(temporary), [FakeSession({"thread/list": lambda: next(pages)})]
            )
            with self.assertRaisesRegex(HostUnavailable, "ambiguous"):
                provider.readback("create_task", KEY)

    def test_thread_list_bad_cursor_loop_and_page_bound_fail_closed(self):
        marker = _request_marker(KEY)
        with tempfile.TemporaryDirectory() as temporary:
            workspace = str(Path(temporary).resolve())
            cases = (
                iter(({"data": [], "nextCursor": 1},)),
                iter(
                    (
                        {"data": [], "nextCursor": "same"},
                        {"data": [], "nextCursor": "same"},
                    )
                ),
                iter(
                    (
                        {"data": [], "nextCursor": "one"},
                        {"data": [], "nextCursor": "two"},
                    )
                ),
            )
            expected = ("cursor drift", "cursor drift", "bound exceeded")
            for index, (pages, message) in enumerate(zip(cases, expected)):
                with self.subTest(index=index):
                    session = FakeSession({"thread/list": lambda: next(pages)})
                    provider = self.provider(Path(temporary), [session])
                    limit = 2 if index == 2 else provider_module.MAX_THREAD_LIST_PAGES
                    with mock.patch.object(
                        provider_module, "MAX_THREAD_LIST_PAGES", limit
                    ), self.assertRaisesRegex(HostUnavailable, message):
                        provider.readback("create_task", KEY)
            foreign = FakeSession(
                {
                    "thread/list": {
                        "data": [
                            {
                                "cwd": workspace + "-foreign",
                                "id": "foreign",
                                "preview": marker,
                            }
                        ],
                        "nextCursor": None,
                    }
                }
            )
            provider = self.provider(Path(temporary), [foreign])
            with self.assertRaisesRegex(HostUnavailable, "cwd/schema drift"):
                provider.readback("create_task", KEY)
            malformed_preview = FakeSession(
                {
                    "thread/list": {
                        "data": [
                            {
                                "cwd": workspace,
                                "id": "malformed-preview",
                                "preview": {"nested": marker},
                            }
                        ],
                        "nextCursor": None,
                    }
                }
            )
            provider = self.provider(Path(temporary), [malformed_preview])
            with self.assertRaisesRegex(HostUnavailable, "preview schema drift"):
                provider.readback("create_task", KEY)
            overlong_marker = FakeSession(
                {
                    "thread/list": {
                        "data": [
                            {
                                "cwd": workspace,
                                "id": "overlong-marker",
                                "preview": marker + "a",
                                "status": {"type": "idle"},
                            }
                        ],
                        "nextCursor": None,
                    }
                }
            )
            provider = self.provider(Path(temporary), [overlong_marker])
            with self.assertRaisesRegex(HostUnavailable, "ambiguous"):
                provider.readback("create_task", KEY)

    def test_task_result_readback_binds_exact_thread_status_and_digest(self):
        text = (
            'LOOPSKILL4_RESULT={"outcome":"PASS",'
            '"summary":"synthetic result"}'
        )
        completed = FakeSession(
            {
                "thread/read": {
                    "thread": {
                        "id": "host-thread-result",
                        "preview": _request_marker(KEY),
                        "status": {"type": "idle"},
                        "turns": [
                            {
                                "id": "host-turn-result",
                                "items": [
                                    {"type": "agentMessage", "text": text}
                                ],
                                "status": "completed",
                            }
                        ],
                    }
                }
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary), [completed])
            result = provider.read_task_result("host-thread-result")
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["trust"], "authoritative")
        self.assertEqual(result["result_text"], text)
        self.assertEqual(
            result["result_digest"],
            domain_digest("loopskill-host-result-v1\n", text),
        )
        self.assertEqual(
            completed.calls,
            [
                (
                    "thread/read",
                    {"includeTurns": True, "threadId": "host-thread-result"},
                )
            ],
        )
        self.assertEqual(provider.metrics["task_result_read_count"], 1)

    def test_task_result_readback_rejects_foreign_identity_and_status_drift(self):
        foreign = FakeSession(
            {"thread/read": {"thread": {"id": "foreign", "turns": []}}}
        )
        drift = FakeSession(
            {
                "thread/read": {
                    "thread": {
                        "id": "host-thread-result",
                        "preview": _request_marker(KEY),
                        "status": {"type": "active"},
                        "turns": [
                            {"id": "host-turn-result", "items": [], "status": "queued"}
                        ],
                    }
                }
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary), [foreign, drift])
            with self.assertRaisesRegex(HostUnavailable, "identity mismatch"):
                provider.read_task_result("host-thread-result")
            with self.assertRaisesRegex(HostUnavailable, "status drift"):
                provider.read_task_result("host-thread-result")

    def test_task_result_uses_exact_created_turn_and_rejects_ambiguous_recovery(self):
        marker = _request_marker(KEY)
        intended = 'LOOPSKILL4_RESULT={"outcome":"PASS","summary":"intended"}'
        foreign = 'LOOPSKILL4_RESULT={"outcome":"PASS","summary":"foreign"}'
        exact = FakeSession(
            {
                "thread/read": {
                    "thread": {
                        "id": "host-thread-result",
                        "preview": marker,
                        "status": {"type": "idle"},
                        "turns": [
                            {
                                "id": "created-turn",
                                "items": [{"type": "agentMessage", "text": intended}],
                                "status": "completed",
                            },
                            {
                                "id": "foreign-later-turn",
                                "items": [{"type": "agentMessage", "text": foreign}],
                                "status": "completed",
                            },
                        ],
                    }
                }
            }
        )
        ambiguous = FakeSession(exact.replies)
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary), [exact])
            provider._records[KEY] = {
                "marker": marker,
                "target_ref": "synthetic-target",
                "thread_id": "host-thread-result",
                "turn_id": "created-turn",
            }
            result = provider.read_task_result("host-thread-result")
            self.assertEqual(result["result_text"], intended)

            recovered = self.provider(Path(temporary), [ambiguous])
            with self.assertRaisesRegex(HostUnavailable, "turn identity is ambiguous"):
                recovered.read_task_result("host-thread-result")

    def test_resource_readback_maps_host_lifecycle_without_becoming_a_writer(self):
        expected = {
            "active": "ACTIVE",
            "idle": "TERMINAL",
            "notLoaded": "PAUSED",
            "systemError": "TERMINAL",
        }
        sessions = [
            FakeSession(
                {
                    "thread/read": {
                        "thread": {
                            "id": "host-thread-resource",
                            "status": {"type": host_status},
                        }
                    }
                }
            )
            for host_status in expected
        ]
        sessions.extend(
            [
                FakeSession(
                    {"thread/read": {"thread": {"id": "foreign-thread"}}}
                ),
                FakeSession(
                    {
                        "thread/read": {
                            "thread": {
                                "id": "host-thread-resource",
                                "status": {"type": "future-status"},
                            }
                        }
                    }
                ),
                FakeSession(
                    {
                        "thread/read": lambda: (_ for _ in ()).throw(
                            HostUnavailable("synthetic absence")
                        )
                    }
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary), sessions)
            for host_status, lifecycle in expected.items():
                with self.subTest(host_status=host_status):
                    resource = provider.read_resource(
                        "task", "host-thread-resource"
                    )
                    self.assertEqual(resource["state"], lifecycle)
                    self.assertEqual(resource["trust"], "authoritative")
            missing = provider.read_resource("task", "host-thread-resource")
            self.assertEqual(missing["state"], "NOT_FOUND")
            self.assertEqual(missing["trust"], "none")
            with self.assertRaisesRegex(HostUnavailable, "status schema drift"):
                provider.read_resource("task", "host-thread-resource")
            unavailable = provider.read_resource("task", "host-thread-resource")
            self.assertEqual(unavailable["state"], "NOT_FOUND")

    def test_resource_readback_rejects_unexposed_project_and_message_kinds(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary), [])
            for resource_kind in ("project", "message"):
                with self.subTest(resource_kind=resource_kind), self.assertRaisesRegex(
                    HostUnavailable, "resource readback kind"
                ):
                    provider.read_resource(resource_kind, "foreign-resource")

    def test_task_result_maps_pending_and_terminal_host_states(self):
        sessions = [
            FakeSession(
                {
                    "thread/read": {
                        "thread": {
                            "id": "host-thread-result",
                            "preview": _request_marker(KEY),
                            "status": {"type": "active"},
                            "turns": [],
                        }
                    }
                }
            )
        ]
        for host_status in ("failed", "interrupted", "inProgress"):
            sessions.append(
                FakeSession(
                    {
                        "thread/read": {
                            "thread": {
                                "id": "host-thread-result",
                                "preview": _request_marker(KEY),
                                "status": {
                                    "type": "active"
                                    if host_status == "inProgress"
                                    else "idle"
                                },
                                "turns": [
                                    {
                                        "id": "host-turn-result",
                                        "items": [
                                            {"type": "tool", "text": "ignored"},
                                            {
                                                "type": "agentMessage",
                                                "text": host_status,
                                            },
                                        ],
                                        "status": host_status,
                                    }
                                ],
                            }
                        }
                    }
                )
            )
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary), sessions)
            pending = provider.read_task_result("host-thread-result")
            self.assertEqual((pending["status"], pending["result_text"]), ("PENDING", ""))
            self.assertEqual(
                provider.read_task_result("host-thread-result")["status"], "FAILED"
            )
            self.assertEqual(
                provider.read_task_result("host-thread-result")["status"], "FAILED"
            )
            in_progress = provider.read_task_result("host-thread-result")
            self.assertEqual(in_progress["status"], "PENDING")
            self.assertEqual(in_progress["result_text"], "inProgress")

    def test_readback_absence_schema_drift_and_unsupported_action_are_explicit(self):
        empty = FakeSession({"thread/list": {"data": []}})
        drift = FakeSession({"thread/list": {"data": {"not": "a list"}}})
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary), [empty, drift])
            self.assertIsNone(provider.readback("unsupported", KEY))
            self.assertIsNone(provider.readback("create_task", KEY))
            with self.assertRaisesRegex(HostUnavailable, "thread/list schema drift"):
                provider.readback("create_task", KEY)

    def test_provider_rejects_unknown_payload_and_oversized_confirmed_prompt(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary), [])
            with self.assertRaisesRegex(HostUnavailable, "Unsupported"):
                provider.invoke("future-action", payload(), KEY)
            changed = payload()
            changed["future"] = "field"
            with self.assertRaisesRegex(HostUnavailable, "Unsupported"):
                provider.invoke("create_task", changed, KEY)
            oversized = payload()
            oversized["acceptance_criteria"] = ["g" * 4_000] * 10
            with self.assertRaisesRegex(HostUnavailable, "32 KiB"):
                provider._prompt(oversized, _request_marker(KEY))

    def test_provider_rejects_known_but_unexposed_actions_before_host_session(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary), [])
            for action in ("register_project", "create_thread", "send", "heartbeat"):
                with self.subTest(action=action), self.assertRaisesRegex(
                    HostUnavailable, "Unsupported"
                ):
                    provider.invoke(action, payload(), KEY)
                self.assertIsNone(provider.readback(action, KEY))

    def test_authoritative_thread_validator_rejects_identity_and_status_drift(self):
        marker = _request_marker(KEY)
        with self.assertRaisesRegex(HostUnavailable, "identity mismatch"):
            CodexAppServerProvider._validate_thread({"id": "host"}, marker)
        with self.assertRaisesRegex(HostUnavailable, "identity mismatch"):
            CodexAppServerProvider._validate_thread(
                {"id": "", "preview": marker, "status": {"type": "idle"}},
                marker,
            )
        with self.assertRaisesRegex(HostUnavailable, "status drift"):
            CodexAppServerProvider._validate_thread(
                {
                    "id": "host",
                    "preview": marker,
                    "status": {"type": "future-status"},
                },
                marker,
            )

    def test_public_cli_constructs_provider_only_after_explicit_confirmation(self):
        import importlib.machinery
        import importlib.util

        entry = SCRIPTS / "loopskill4"
        loader = importlib.machinery.SourceFileLoader("loopskill4_provider_test", str(entry))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = root / "prepared"
            prepared.mkdir()
            args = type(
                "Args",
                (),
                {
                    "goal_file_or_prepared_directory": str(prepared),
                    "prepared_output": None,
                    "root": root / "data",
                },
            )()
            class OwnedProvider:
                metrics = {"task_create_count": 0}

                def __init__(self):
                    self.close_count = 0

                def close(self):
                    self.close_count += 1

            sentinel = OwnedProvider()
            with mock.patch.object(module, "is_legacy_input", return_value=False), mock.patch.object(
                module, "CodexAppServerProvider", return_value=sentinel
            ) as constructor, mock.patch.object(module, "start_loop", return_value="started") as start:
                self.assertEqual(module._interactive_start(args), "started")
            constructor.assert_called_once_with(Path.cwd())
            self.assertIs(start.call_args.kwargs["host_provider"], sentinel)
            self.assertEqual(sentinel.close_count, 1)

    def test_public_cli_waits_for_its_one_created_task_then_closes_provider(self):
        import importlib.machinery
        import importlib.util

        entry = SCRIPTS / "loopskill4"
        loader = importlib.machinery.SourceFileLoader("loopskill4_owned_provider_test", str(entry))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)

        class OwnedProvider:
            metrics = {"task_create_count": 1, "provider_resend_count": 0}

            def __init__(self):
                self.close_count = 0
                self.waits = []

            def wait_for_terminal(self, *, timeout_seconds):
                self.waits.append(timeout_seconds)

            def close(self):
                self.close_count += 1

        provider = OwnedProvider()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = root / "prepared"
            prepared.mkdir()
            args = type(
                "Args",
                (),
                {
                    "goal_file_or_prepared_directory": str(prepared),
                    "prepared_output": None,
                    "root": root / "data",
                },
            )()
            with mock.patch.object(module, "is_legacy_input", return_value=False), mock.patch.object(
                module, "CodexAppServerProvider", return_value=provider
            ), mock.patch.object(module, "start_loop", return_value="active"), mock.patch.object(
                module, "sync_loop", return_value="finished"
            ) as sync:
                self.assertEqual(module._interactive_start(args), "finished")
            self.assertEqual(provider.waits, [300.0])
            self.assertEqual(provider.close_count, 1)
            self.assertEqual(sync.call_count, 1)
            self.assertIs(sync.call_args.kwargs["host_provider"], provider)
            self.assertEqual(sync.call_args.kwargs["root"], root / "data")

    def test_public_cli_closes_provider_when_terminal_readback_fails(self):
        import importlib.machinery
        import importlib.util

        entry = SCRIPTS / "loopskill4"
        loader = importlib.machinery.SourceFileLoader("loopskill4_owned_provider_failure_test", str(entry))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)

        class FailingProvider:
            metrics = {"task_create_count": 1, "provider_resend_count": 0}

            def __init__(self):
                self.close_count = 0

            def wait_for_terminal(self, *, timeout_seconds):
                raise module.HostUnavailable("terminal readback lost")

            def close(self):
                self.close_count += 1

        provider = FailingProvider()
        with mock.patch.object(module, "CodexAppServerProvider", return_value=provider), mock.patch.object(
            module, "sync_loop", return_value="active"
        ):
            with self.assertRaises(module.EntryError) as caught:
                module._refresh_with_owned_provider(root=Path("synthetic-store"))
        self.assertEqual(caught.exception.code, "USER_INTERNAL_ERROR")
        self.assertIn("not resent", caught.exception.message)
        self.assertEqual(provider.close_count, 1)


class _SessionContext:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *_):
        self.session.close()


if __name__ == "__main__":
    unittest.main()
