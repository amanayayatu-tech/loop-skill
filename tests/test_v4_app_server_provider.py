from __future__ import annotations

import sys
import tempfile
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
    HostUnavailable,
    _request_marker,
)
from loop_architect.v4_alpha.protocol import domain_digest  # noqa: E402


NOW = datetime(2026, 7, 27, tzinfo=timezone.utc)
KEY = "effect-machine-owned-0001"


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

    def request(self, method, params):
        self.calls.append((method, dict(params)))
        reply = self.replies[method]
        return reply() if callable(reply) else reply

    def close(self):
        return None


class AppServerProviderTests(unittest.TestCase):
    def provider(self, root, sessions):
        provider = CodexAppServerProvider(
            root,
            command=("synthetic-codex", "app-server", "--stdio"),
            clock=lambda: NOW,
        )
        provider._session = lambda: _SessionContext(sessions.pop(0))
        return provider

    def test_capabilities_are_honest_about_missing_provider_idempotency(self):
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = self.provider(Path(temporary), []).capability_snapshot()
        rows = {item["name"]: item for item in snapshot["capabilities"]}
        self.assertEqual(rows["task_create"]["assurance"], "STRICT")
        self.assertEqual(rows["provider_idempotency"]["availability"], "UNAVAILABLE")
        self.assertEqual(rows["memory"]["availability"], "UNVERIFIABLE")

    def test_create_and_authoritative_readback_bind_machine_marker(self):
        marker = _request_marker(KEY)
        invoke = FakeSession(
            {
                "thread/start": {"thread": {"id": "host-thread-1"}},
                "turn/start": {"turn": {"id": "host-turn-1"}},
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

    def test_crash_recovery_is_readback_only_and_ambiguous_identity_fails(self):
        marker = _request_marker(KEY)
        unique = FakeSession(
            {
                "thread/list": {
                    "data": [
                        {
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
                        {"id": "one", "preview": marker},
                        {"id": "two", "preview": marker},
                    ]
                }
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary), [unique, ambiguous])
            recovered = provider.readback("create_task", KEY)
            self.assertEqual(recovered["provider_id"], "host-thread-recovered")
            with self.assertRaisesRegex(HostUnavailable, "ambiguous"):
                provider.readback("create_task", KEY)
        self.assertEqual([call[0] for call in unique.calls], ["thread/list"])

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
                        "turns": [
                            {
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

    def test_task_result_readback_rejects_foreign_identity_and_status_drift(self):
        foreign = FakeSession(
            {"thread/read": {"thread": {"id": "foreign", "turns": []}}}
        )
        drift = FakeSession(
            {
                "thread/read": {
                    "thread": {
                        "id": "host-thread-result",
                        "turns": [{"items": [], "status": "queued"}],
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
            sentinel = object()
            with mock.patch.object(module, "is_legacy_input", return_value=False), mock.patch.object(
                module, "CodexAppServerProvider", return_value=sentinel
            ) as constructor, mock.patch.object(module, "start_loop", return_value="started") as start:
                self.assertEqual(module._interactive_start(args), "started")
            constructor.assert_called_once_with(Path.cwd())
            self.assertIs(start.call_args.kwargs["host_provider"], sentinel)


class _SessionContext:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *_):
        self.session.close()


if __name__ == "__main__":
    unittest.main()
