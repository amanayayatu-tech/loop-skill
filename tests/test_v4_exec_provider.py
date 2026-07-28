from __future__ import annotations

import json
import os
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

from loop_architect.v4_adapters.codex.adapter import (  # noqa: E402
    CodexHostAdapter,
    HOST_SCHEMA_VERSION,
    HostResponseLost,
    HostUnavailable,
)
from loop_architect.v4_adapters.codex.exec_provider import (  # noqa: E402
    EXEC_TRANSPORT,
    CodexExecProvider,
    _ProcessResult,
    _parse_jsonl,
    _run_bounded_process,
    build_exec_argv,
)
import loop_architect.v4_adapters.codex.exec_provider as exec_provider  # noqa: E402
from loop_architect.v4_alpha.protocol import CAPABILITY_NAMES, domain_digest  # noqa: E402
from loop_architect.v4_entry import canary  # noqa: E402


NOW = datetime(2026, 7, 28, tzinfo=timezone.utc)
KEY = "machine-operation-key"
RESULT = 'LOOPSKILL4_RESULT={"outcome":"PASS","summary":"complete"}'


def payload():
    return {
        "acceptance_criteria": ["one file"],
        "authorization_boundaries": ["no publish"],
        "budget": "one foreground invocation",
        "execution_mode": "STANDARD",
        "external_actions": [],
        "goal": "Complete one disposable task",
        "stop_conditions": ["stop after terminal"],
        "target_ref": "machine-target",
        "write_scope": ["output.txt"],
    }


def event_bytes(*events):
    return b"".join(
        json.dumps(event, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        for event in events
    )


def success_jsonl(*, thread_id="thread-machine", result=RESULT, extra=()):
    return event_bytes(
        {"thread_id": thread_id, "type": "thread.started"},
        {"type": "turn.started"},
        *extra,
        {
            "item": {"id": "item-machine", "text": result, "type": "agent_message"},
            "type": "item.completed",
        },
        {"type": "turn.completed", "usage": {}},
    )


class FakeRunner:
    def __init__(self, exec_result=None, exec_error=None):
        self.calls = []
        self.exec_result = exec_result or _ProcessResult(
            argv=("codex", "exec"), returncode=0, stdout=success_jsonl(), stderr=b""
        )
        self.exec_error = exec_error

    def __call__(self, argv, **kwargs):
        self.calls.append((tuple(argv), dict(kwargs)))
        if tuple(argv)[-1:] == ("--version",):
            return _ProcessResult(tuple(argv), 0, b"codex-cli 0.146.0-alpha.3.1\n", b"")
        if tuple(argv)[-2:] == ("exec", "--help"):
            flags = " ".join(
                (
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
            )
            return _ProcessResult(tuple(argv), 0, flags.encode(), b"")
        if self.exec_error is not None:
            raise self.exec_error
        return _ProcessResult(
            tuple(argv),
            self.exec_result.returncode,
            self.exec_result.stdout,
            self.exec_result.stderr,
        )


class ArtifactRunner(FakeRunner):
    def __init__(self, workspace):
        super().__init__()
        self.workspace = workspace

    def __call__(self, argv, **kwargs):
        result = super().__call__(argv, **kwargs)
        if tuple(argv)[-1:] == ("-",):
            (self.workspace / canary.CANARY_OUTPUT_FILENAME).write_bytes(
                canary.CANARY_OUTPUT_BYTES
            )
        return result


class ExecProviderTests(unittest.TestCase):
    def provider(self, root, runner):
        return CodexExecProvider(
            root,
            executable=sys.executable,
            clock=lambda: NOW,
            runner=runner,
        )

    def test_pure_argv_is_exact_shell_free_contract_for_non_git_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            self.assertFalse((root / ".git").exists())
            self.assertEqual(
                build_exec_argv("/safe/codex", root),
                (
                    "/safe/codex",
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
                    str(root),
                    "--skip-git-repo-check",
                    "-",
                ),
            )

    def test_binary_resolution_prefers_safe_bundle_then_resolved_path_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle-codex"
            fallback = root / "fallback-codex"
            bundle.write_bytes(b"bundle")
            fallback.write_bytes(b"fallback")
            bundle.chmod(0o755)
            fallback.chmod(0o755)
            with mock.patch.object(exec_provider.sys, "platform", "darwin"), mock.patch.object(
                exec_provider, "CODEX_DESKTOP_EXECUTABLE", bundle
            ), mock.patch.object(exec_provider.shutil, "which", return_value=str(fallback)):
                self.assertEqual(exec_provider.resolve_codex_executable(), str(bundle.resolve()))
            bundle.unlink()
            bundle.symlink_to(root / "missing")
            with mock.patch.object(exec_provider.sys, "platform", "darwin"), mock.patch.object(
                exec_provider, "CODEX_DESKTOP_EXECUTABLE", bundle
            ), mock.patch.object(exec_provider.shutil, "which", return_value=str(fallback)):
                self.assertEqual(exec_provider.resolve_codex_executable(), str(fallback.resolve()))

    def test_preflight_only_inspects_version_help_and_never_invokes_exec(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner = FakeRunner()
            provider = self.provider(Path(temporary), runner)
            receipt = provider.preflight()
            self.assertEqual(receipt["transport"], EXEC_TRANSPORT)
            self.assertEqual(receipt["version"], "0.146.0-alpha.3.1")
            self.assertEqual(len(runner.calls), 2)
            self.assertEqual(runner.calls[0][0][-1], "--version")
            self.assertEqual(runner.calls[1][0][-2:], ("exec", "--help"))
            self.assertEqual(provider.metrics["task_create_count"], 0)

    def test_success_binds_exact_stdin_argv_terminal_result_and_same_process_reads(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            runner = FakeRunner()
            provider = self.provider(root, runner)
            observation = provider.invoke("create_task", payload(), KEY)
            self.assertEqual(len(runner.calls), 3)
            argv, kwargs = runner.calls[-1]
            self.assertEqual(argv, build_exec_argv(provider.executable, root))
            self.assertEqual(kwargs["cwd"], root)
            self.assertTrue(kwargs["stdin_bytes"].endswith(b"\n"))
            prompt = kwargs["stdin_bytes"].decode("utf-8")
            self.assertIn('"goal":"Complete one disposable task"', prompt)
            self.assertNotIn(KEY, prompt)
            self.assertEqual(observation["status"], "OBSERVED")
            self.assertEqual(observation["trust"], "authoritative")
            self.assertEqual(
                provider.readback("create_task", KEY), observation
            )
            result = provider.read_task_result("thread-machine")
            self.assertEqual(result["status"], "COMPLETED")
            self.assertEqual(result["result_text"], RESULT)
            self.assertEqual(
                result["result_digest"],
                domain_digest("loopskill-host-result-v1\n", RESULT),
            )
            lifecycle = provider.read_resource("lifecycle", "thread-machine")
            self.assertEqual(lifecycle["state"], "TERMINAL")
            self.assertEqual(lifecycle["trust"], "authoritative")
            provider.wait_for_terminal(timeout_seconds=1)
            self.assertEqual(provider.metrics["task_create_count"], 1)
            self.assertEqual(provider.metrics["provider_resend_count"], 0)

    def test_capabilities_scope_strict_rows_to_same_process_and_profile_cooperative(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary), FakeRunner())
            value = provider.capability_snapshot()
            self.assertEqual(value["schema_version"], HOST_SCHEMA_VERSION)
            rows = {row["name"]: row for row in value["capabilities"]}
            self.assertEqual(set(rows), set(CAPABILITY_NAMES))
            for name in ("task_create", "resource_read", "lifecycle_readback"):
                self.assertEqual(rows[name]["availability"], "AVAILABLE")
                self.assertEqual(rows[name]["assurance"], "STRICT")
                self.assertEqual(rows[name]["details"]["source"], EXEC_TRANSPORT)
            for name in (
                "project_registration",
                "thread_create",
                "message_send",
                "heartbeat",
                "provider_idempotency",
            ):
                self.assertEqual(rows[name]["availability"], "UNAVAILABLE")
            adapter = CodexHostAdapter(
                provider,
                object(),
                executor_ref="machine-executor",
                issuer_ref=provider.issuer_ref,
                issuer_trust=provider.issuer_trust,
                clock=lambda: NOW,
            )
            self.assertEqual(adapter.assurance_tier(), "COOPERATIVE")
            self.assertEqual(
                adapter.guarantee_vocabulary(),
                "at-most-one automatic attempt; outcome may be UNKNOWN",
            )

    def test_lost_evidence_consumes_only_spawn_and_duplicate_is_rejected_before_runner(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner = FakeRunner(exec_error=HostResponseLost("lost"))
            provider = self.provider(Path(temporary), runner)
            with self.assertRaises(HostResponseLost):
                provider.invoke("create_task", payload(), KEY)
            calls_after_loss = len(runner.calls)
            with self.assertRaises(HostUnavailable):
                provider.invoke("create_task", payload(), KEY)
            self.assertEqual(len(runner.calls), calls_after_loss)
            self.assertIsNone(provider.readback("create_task", KEY))
            self.assertEqual(provider.metrics["task_create_count"], 1)
            self.assertEqual(provider.metrics["duplicate_invoke_rejection_count"], 1)
            self.assertEqual(provider.metrics["provider_resend_count"], 0)

    def test_nonzero_and_stderr_fail_closed_after_one_spawn(self):
        variants = (
            _ProcessResult(("codex",), 9, success_jsonl(), b""),
            _ProcessResult(("codex",), 0, success_jsonl(), b"warning"),
        )
        for result in variants:
            with self.subTest(returncode=result.returncode, stderr=bool(result.stderr)):
                with tempfile.TemporaryDirectory() as temporary:
                    provider = self.provider(Path(temporary), FakeRunner(exec_result=result))
                    with self.assertRaises(HostResponseLost):
                        provider.invoke("create_task", payload(), KEY)
                    self.assertEqual(provider.metrics["task_create_count"], 1)
                    self.assertIsNone(provider.readback("create_task", KEY))

    def test_jsonl_success_ignores_additive_events_and_item_warning(self):
        transcript = _parse_jsonl(
            success_jsonl(
                extra=(
                    {"future": True, "type": "future.additive"},
                    {
                        "item": {"id": "warning", "message": "notice", "type": "error"},
                        "type": "item.completed",
                    },
                )
            )
        )
        self.assertEqual(transcript.thread_id, "thread-machine")
        self.assertEqual(transcript.result_text, RESULT)

    def test_jsonl_failure_matrix_is_fail_closed(self):
        valid = [
            {"thread_id": "thread-machine", "type": "thread.started"},
            {"type": "turn.started"},
            {
                "item": {"id": "message", "text": RESULT, "type": "agent_message"},
                "type": "item.completed",
            },
            {"type": "turn.completed", "usage": {}},
        ]
        cases = {
            "empty": b"",
            "truncated": event_bytes(*valid)[:-1],
            "malformed": b"{bad}\n",
            "invalid_utf8": b"\xff\n",
            "missing_thread": event_bytes(*valid[1:]),
            "duplicate_thread": event_bytes(valid[0], valid[0], *valid[1:]),
            "conflicting_thread": event_bytes(
                valid[0], {"thread_id": "foreign", "type": "thread.started"}, *valid[1:]
            ),
            "missing_turn_start": event_bytes(valid[0], *valid[2:]),
            "missing_terminal": event_bytes(*valid[:-1]),
            "terminal_failure": event_bytes(*valid[:-1], {"type": "turn.failed"}),
            "top_error": event_bytes(*valid[:-1], {"message": "failure", "type": "error"}),
            "multiple_terminal": event_bytes(*valid, valid[-1]),
            "turn_before_thread": event_bytes(valid[1], valid[0], *valid[2:]),
            "result_before_turn": event_bytes(valid[0], valid[2], valid[1], valid[3]),
            "result_after_terminal": event_bytes(*valid, valid[2]),
            "additive_after_terminal": event_bytes(*valid, {"type": "future.additive"}),
            "missing_result": event_bytes(valid[0], valid[1], valid[-1]),
            "oversized_line": b"{" + b"x" * (1024 * 1024) + b"}\n",
        }
        for name, raw in cases.items():
            with self.subTest(name=name), self.assertRaises(HostResponseLost):
                _parse_jsonl(raw)

    def test_bounded_runner_rejects_oversized_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with self.assertRaises(HostResponseLost):
                _run_bounded_process(
                    (sys.executable, "-c", "print('x' * 1000)"),
                    cwd=root,
                    stdin_bytes=b"",
                    timeout_seconds=3,
                    stdout_limit=100,
                    stderr_limit=100,
                )

    def test_timeout_reaps_process_group_and_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            pid_path = root / "child.pid"
            code = (
                "import pathlib,subprocess,sys,time;"
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']);"
                "pathlib.Path(sys.argv[1]).write_text(str(p.pid));"
                "time.sleep(60)"
            )
            with self.assertRaises(HostResponseLost):
                _run_bounded_process(
                    (sys.executable, "-c", code, str(pid_path)),
                    cwd=root,
                    stdin_bytes=b"",
                    timeout_seconds=0.5,
                    stdout_limit=100,
                    stderr_limit=100,
                )
            child_pid = int(pid_path.read_text())
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.02)
            else:
                self.fail("Codex exec descendant survived process-group cleanup")

    def test_success_reaps_detached_output_child_in_same_process_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            pid_path = root / "child.pid"
            code = (
                "import os,pathlib,subprocess,sys;"
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],"
                "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
                "pathlib.Path(sys.argv[1]).write_text(str(p.pid));"
                "print('done')"
            )
            result = _run_bounded_process(
                (sys.executable, "-c", code, str(pid_path)),
                cwd=root,
                stdin_bytes=b"",
                timeout_seconds=3,
                stdout_limit=100,
                stderr_limit=100,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"done\n")
            child_pid = int(pid_path.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)

    def test_interruption_routes_through_process_group_reaper(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            exec_provider.selectors.DefaultSelector,
            "select",
            side_effect=KeyboardInterrupt,
        ), mock.patch.object(
            exec_provider,
            "_terminate_process_group",
            wraps=exec_provider._terminate_process_group,
        ) as terminate:
            with self.assertRaises(KeyboardInterrupt):
                _run_bounded_process(
                    (sys.executable, "-c", "import time; time.sleep(60)"),
                    cwd=Path(temporary).resolve(),
                    stdin_bytes=b"",
                    timeout_seconds=3,
                    stdout_limit=100,
                    stderr_limit=100,
                )
            terminate.assert_called_once()

    def test_installed_entry_vertical_closes_result_artifact_review_and_finalization(self):
        candidate = "a" * 40
        providers = []

        def factory(workspace):
            provider = CodexExecProvider(
                workspace,
                executable=sys.executable,
                issuer_ref=canary.CANARY_ISSUER,
                issuer_trust=canary.CANARY_TRUST,
                clock=lambda: NOW,
                runner=ArtifactRunner(workspace),
            )
            providers.append(provider)
            return provider

        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            canary, "_validate_candidate", return_value=candidate
        ):
            host_inputs = Path(temporary) / "host-inputs"
            host_inputs.mkdir()
            config = host_inputs / "config.toml"
            auth = host_inputs / "auth.json"
            config.write_bytes(b"synthetic config\n")
            auth.write_bytes(b"synthetic auth\n")
            receipt = canary.run_canary(
                candidate,
                Path(temporary) / "evidence",
                confirmation_callback=lambda boundary: bool(boundary),
                integrity_inputs={
                    "host_auth": auth.resolve(),
                    "host_config": config.resolve(),
                },
                provider_factory=factory,
                clock=lambda: NOW,
                token_factory=lambda: "000000000000000000000099",
            )
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["host_task_create_count"], 1)
        self.assertEqual(receipt["provider_resend_count"], 0)
        self.assertEqual(len(providers), 1)
        calls = providers[0]._runner.calls
        self.assertEqual(sum(call[0][-1:] == ("-",) for call in calls), 1)


if __name__ == "__main__":
    unittest.main()
