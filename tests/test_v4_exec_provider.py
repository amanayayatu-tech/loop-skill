from __future__ import annotations

import hashlib
import json
import os
import stat
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
from loop_architect.v4_alpha.protocol import (  # noqa: E402
    ProtocolRejection,
    canonical_bytes,
    result_payload_schema,
)
from loop_architect.v4_entry import canary  # noqa: E402


NOW = datetime(2026, 7, 28, tzinfo=timezone.utc)
KEY = "machine-operation-key"
RESULT = {"outcome": "PASS", "summary": "complete"}
RESULT_TEXT = canonical_bytes(RESULT).decode("utf-8")


def fake_candidate_provenance(candidate):
    body = {
        "candidate_execution_mode": "CLEAN_GIT_WORKTREE",
        "candidate_sha": candidate,
        "candidate_tree_sha": "c" * 40,
    }
    body["candidate_provenance_digest"] = canary._domain_digest(
        canary.CANARY_CANDIDATE_PROVENANCE_DOMAIN, body
    )
    return body


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


def success_jsonl(*, thread_id="thread-machine", result=RESULT_TEXT, extra=()):
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
    def __init__(self, exec_result=None, exec_error=None, result_bytes=canonical_bytes(RESULT)):
        self.calls = []
        self.exec_result = exec_result or _ProcessResult(
            argv=("codex", "exec"), returncode=0, stdout=success_jsonl(), stderr=b""
        )
        self.exec_error = exec_error
        self.schema_snapshots = []
        self.result_bytes = result_bytes
        self.result_snapshots = []
        self.result_identities = []

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
                    "--output-schema",
                    "--output-last-message",
                    "--sandbox",
                    "--skip-git-repo-check",
                    "--strict-config",
                )
            )
            return _ProcessResult(tuple(argv), 0, flags.encode(), b"")
        if self.exec_error is not None:
            raise self.exec_error
        schema_path = Path(argv[tuple(argv).index("--output-schema") + 1])
        result_path = Path(argv[tuple(argv).index("--output-last-message") + 1])
        self.schema_snapshots.append((schema_path, schema_path.read_bytes()))
        before = result_path.lstat()
        if self.result_bytes is not None:
            result_path.write_bytes(self.result_bytes)
        after = result_path.lstat()
        self.result_identities.append(
            (
                before.st_dev,
                before.st_ino,
                stat.S_IMODE(before.st_mode),
                after.st_dev,
                after.st_ino,
                stat.S_IMODE(after.st_mode),
                stat.S_IMODE(result_path.parent.stat().st_mode),
            )
        )
        self.result_snapshots.append((result_path, result_path.read_bytes()))
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


class StreamingFakeRunner(FakeRunner):
    def __call__(self, argv, **kwargs):
        if tuple(argv)[-1:] == ("-",):
            observer = kwargs.get("process_observer")
            if observer is not None:
                observer(os.getpid())
            stdout_observer = kwargs.get("stdout_observer")
            if stdout_observer is not None:
                stdout_observer(b"not-json\n\n")
                stdout_observer(
                    b'{"thread_id":"thread-machine","type":"thread.started"}\n'
                )
        return super().__call__(argv, **kwargs)


class ExecProviderTests(unittest.TestCase):
    def provider(self, root, runner):
        return CodexExecProvider(
            root,
            executable=sys.executable,
            clock=lambda: NOW,
            runner=runner,
        )

    @staticmethod
    def v2_payload(*, maximum_calls=3, wall_seconds=3600):
        return {
            **payload(),
            "artifact_digest": "a" * 64,
            "capabilities": [],
            "goal_id": "g000",
            "goal_policy": {
                "max_attempts": 3,
                "on_blocked": "wait",
                "on_failure": "repair",
                "recovery_policy": "resume",
                "replay_safety": "file_local",
                "requirement": "required",
            },
            "prior_disposition": "",
            "requirements": [],
            "verifiers": ["no-file-change"],
            "worker_profile": {
                "attempt_timeout_seconds": 30_000,
                "local_verification": True,
                "model": "gpt-5.6-sol",
                "network_access": True,
                "reasoning_effort": "medium",
                "sandbox": "workspace-write",
            },
            "workspace_digest": "b" * 64,
            "budget": {
                "currency": None,
                "max_cost_minor_units": 0,
                "max_host_invocations": maximum_calls,
                "wall_clock_seconds": wall_seconds,
            },
        }

    def test_persistent_terminal_attempt_survives_provider_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = root / "workspace"
            workspace.mkdir()
            attempts = root / "attempts"
            first = CodexExecProvider(
                workspace,
                executable=sys.executable,
                clock=lambda: NOW,
                attempt_root=attempts,
                runner=FakeRunner(),
            )
            observation = first.invoke("create_task", payload(), KEY)
            self.assertEqual(observation["provider_id"], "thread-machine")

            restored = CodexExecProvider(
                workspace,
                executable=sys.executable,
                clock=lambda: NOW,
                attempt_root=attempts,
                runner=FakeRunner(),
            )
            self.assertEqual(
                restored.readback("create_task", KEY)["provider_id"],
                "thread-machine",
            )
            self.assertEqual(
                restored.read_task_result("thread-machine")["result"], RESULT
            )
            attempt_directories = tuple(attempts.iterdir())
            self.assertEqual(len(attempt_directories), 1)
            self.assertEqual(attempt_directories[0].stat().st_mode & 0o777, 0o700)
            self.assertTrue(
                all(path.stat().st_mode & 0o777 == 0o600 for path in attempt_directories[0].iterdir())
            )

    def test_persistent_stream_binds_process_and_session_before_terminal_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = root / "workspace"
            workspace.mkdir()
            attempts = root / "attempts"
            provider = CodexExecProvider(
                workspace,
                executable=sys.executable,
                clock=lambda: NOW,
                attempt_root=attempts,
                runner=StreamingFakeRunner(),
            )
            provider.invoke("create_task", payload(), KEY)
            attempt = next(attempts.iterdir())
            self.assertEqual(
                json.loads((attempt / "process.json").read_text()),
                {
                    "pid": os.getpid(),
                    "start_token": exec_provider._process_start_token(os.getpid()),
                },
            )
            self.assertEqual(
                json.loads((attempt / "session.json").read_text()),
                {"thread_id": "thread-machine"},
            )
            self.assertIn(b"thread.started", (attempt / "transcript.partial.jsonl").read_bytes())

            no_persistence = CodexExecProvider(
                workspace,
                executable=sys.executable,
                clock=lambda: NOW,
                runner=StreamingFakeRunner(),
            )
            no_persistence.invoke("create_task", payload(), "no-persistence")

    def test_private_persistent_reader_rejects_missing_symlink_and_oversize(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with self.assertRaises(ValueError):
                exec_provider._read_private_regular(root / "missing", limit=0)
            with self.assertRaises(HostResponseLost) as missing:
                exec_provider._read_private_regular(root / "missing", limit=10)
            self.assertEqual(missing.exception.provider_code, "CONTROL_IDENTITY_DRIFT")
            target = root / "target"
            target.write_bytes(b"safe")
            target.chmod(0o600)
            self.assertEqual(
                exec_provider._read_private_regular(target, limit=4), b"safe"
            )
            with self.assertRaises(HostResponseLost) as oversized:
                exec_provider._read_private_regular(target, limit=3)
            self.assertEqual(oversized.exception.provider_code, "CONTROL_IDENTITY_DRIFT")
            link = root / "link"
            link.symlink_to(target)
            with self.assertRaises(HostResponseLost) as symlink:
                exec_provider._read_private_regular(link, limit=10)
            self.assertEqual(symlink.exception.provider_code, "CONTROL_IDENTITY_DRIFT")

    def test_persistent_terminal_readback_rejects_owner_visible_mode_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = root / "workspace"
            workspace.mkdir()
            attempts = root / "attempts"
            first = CodexExecProvider(
                workspace,
                executable=sys.executable,
                clock=lambda: NOW,
                attempt_root=attempts,
                runner=FakeRunner(),
            )
            first.invoke("create_task", payload(), KEY)
            attempt = next(attempts.iterdir())
            (attempt / "result.json").chmod(0o644)

            restored = CodexExecProvider(
                workspace,
                executable=sys.executable,
                clock=lambda: NOW,
                attempt_root=attempts,
                runner=FakeRunner(),
            )
            with self.assertRaises(HostResponseLost) as drift:
                restored.readback("create_task", KEY)
            self.assertEqual(drift.exception.provider_code, "CONTROL_IDENTITY_DRIFT")

    def test_incomplete_attempt_rejects_invalid_process_identity_without_resend(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = root / "workspace"
            workspace.mkdir()
            attempts = root / "attempts"
            attempts.mkdir(mode=0o700)
            key = "invalid-process-key"
            attempt = attempts / exec_provider._private_attempt_name(key)
            attempt.mkdir(mode=0o700)
            for name, value in (
                ("intent.json", {}),
                ("process.json", {"pid": "not-a-pid"}),
                ("session.json", {"thread_id": "thread-machine"}),
            ):
                path = attempt / name
                path.write_bytes(canonical_bytes(value))
                path.chmod(0o600)
            runner = FakeRunner()
            provider = CodexExecProvider(
                workspace,
                executable=sys.executable,
                clock=lambda: NOW,
                attempt_root=attempts,
                runner=runner,
            )
            with self.assertRaises(HostResponseLost) as drift:
                provider.invoke("create_task", self.v2_payload(maximum_calls=3), key)
            self.assertEqual(drift.exception.provider_code, "CONTROL_IDENTITY_DRIFT")
            self.assertEqual(len(runner.calls), 2)  # version/help preflight only

    def test_pid_reuse_identity_mismatch_does_not_wait_for_unrelated_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = root / "workspace"
            workspace.mkdir()
            attempts = root / "attempts"
            attempts.mkdir(mode=0o700)
            key = "pid-reuse-key"
            attempt = attempts / exec_provider._private_attempt_name(key)
            attempt.mkdir(mode=0o700)
            for name, value in (
                (
                    "intent.json",
                    {
                        "attempt_timeout_milliseconds": 30_000_000,
                        "started_at": NOW.isoformat().replace("+00:00", "Z"),
                    },
                ),
                ("process.json", {"pid": os.getpid(), "start_token": "0" * 64}),
                ("session.json", {"thread_id": "thread-machine"}),
            ):
                path = attempt / name
                path.write_bytes(canonical_bytes(value))
                path.chmod(0o600)
            runner = FakeRunner()
            provider = CodexExecProvider(
                workspace,
                executable=sys.executable,
                clock=lambda: NOW,
                attempt_root=attempts,
                runner=runner,
            )
            observation = provider.invoke(
                "create_task", self.v2_payload(maximum_calls=3), key
            )
            self.assertEqual(observation["provider_id"], "thread-machine")
            self.assertEqual(runner.calls[-1][0][:3], (provider.executable, "exec", "resume"))

    def test_recovery_budget_blocks_only_a_new_session_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = root / "workspace"
            workspace.mkdir()
            attempts = root / "attempts"
            attempts.mkdir(mode=0o700)
            key = "resume-budget-key"
            attempt = attempts / exec_provider._private_attempt_name(key)
            attempt.mkdir(mode=0o700)
            for name, value in (
                (
                    "intent.json",
                    {
                        "attempt_timeout_milliseconds": 30_000_000,
                        "started_at": NOW.isoformat().replace("+00:00", "Z"),
                    },
                ),
                ("session.json", {"thread_id": "thread-machine"}),
            ):
                path = attempt / name
                path.write_bytes(canonical_bytes(value))
                path.chmod(0o600)
            provider = CodexExecProvider(
                workspace,
                executable=sys.executable,
                clock=lambda: NOW,
                attempt_root=attempts,
                runner=FakeRunner(),
            )
            reason = provider.recovery_budget_block_reason(
                self.v2_payload(maximum_calls=1), key
            )
            self.assertIn("invocation budget is exhausted", reason)
            self.assertFalse((attempt / "resume.json").exists())
            self.assertIsNone(
                provider.recovery_budget_block_reason(
                    self.v2_payload(maximum_calls=2), key
                )
            )

    def test_persisted_invocation_budget_blocks_before_a_second_exec(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = root / "workspace"
            workspace.mkdir()
            attempts = root / "attempts"
            first = CodexExecProvider(
                workspace,
                executable=sys.executable,
                clock=lambda: NOW,
                attempt_root=attempts,
                runner=FakeRunner(),
            )
            first.invoke(
                "create_task", self.v2_payload(maximum_calls=1), "first-key"
            )
            runner = FakeRunner()
            second = CodexExecProvider(
                workspace,
                executable=sys.executable,
                clock=lambda: NOW,
                attempt_root=attempts,
                runner=runner,
            )
            observation = second.invoke(
                "create_task", self.v2_payload(maximum_calls=1), "second-key"
            )
            result = second.read_task_result(observation["provider_id"])
            self.assertEqual(result["result"]["outcome"], "LIMITATION")
            self.assertIn("invocation budget is exhausted", result["result"]["summary"])
            self.assertEqual(len(runner.calls), 2)

    def test_budget_override_and_active_compute_preflight_are_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = root / "workspace"
            workspace.mkdir()
            attempts = root / "attempts"
            with self.assertRaises(ValueError):
                CodexExecProvider(
                    workspace,
                    executable=sys.executable,
                    budget_override={
                        "max_host_invocations": True,
                        "wall_clock_seconds": 3600,
                    },
                )

            no_store = CodexExecProvider(
                workspace,
                executable=sys.executable,
                runner=FakeRunner(),
            )
            self.assertIsNone(no_store.budget_block_reason(self.v2_payload()))

            attempts.mkdir(mode=0o700)
            invalid = CodexExecProvider(
                workspace,
                executable=sys.executable,
                attempt_root=attempts,
                runner=FakeRunner(),
            )
            self.assertIn(
                "budget is invalid",
                invalid.budget_block_reason(
                    self.v2_payload(maximum_calls=True)
                ),
            )

            spent = attempts / "spent"
            spent.mkdir(mode=0o700)
            intent = spent / "intent.json"
            intent.write_bytes(canonical_bytes({}))
            intent.chmod(0o600)
            record = spent / "attempt.json"
            record.write_bytes(canonical_bytes({"elapsed_ms": 5000}))
            record.chmod(0o600)
            exhausted = CodexExecProvider(
                workspace,
                executable=sys.executable,
                attempt_root=attempts,
                runner=FakeRunner(),
            )
            self.assertIn(
                "active-compute budget is exhausted",
                exhausted.budget_block_reason(
                    self.v2_payload(maximum_calls=3, wall_seconds=5)
                ),
            )

            record.write_bytes(canonical_bytes({"elapsed_ms": 1}))
            override = CodexExecProvider(
                workspace,
                executable=sys.executable,
                attempt_root=attempts,
                budget_override={
                    "max_host_invocations": 2,
                    "wall_clock_seconds": 3600,
                },
                runner=FakeRunner(),
            )
            self.assertIsNone(
                override.budget_block_reason(self.v2_payload(maximum_calls=1))
            )

    def test_incomplete_persisted_session_uses_one_recorded_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = root / "workspace"
            workspace.mkdir()
            attempts = root / "attempts"
            attempts.mkdir(mode=0o700)
            key = "resume-key"
            attempt = attempts / exec_provider._private_attempt_name(key)
            attempt.mkdir(mode=0o700)
            for name, value in (
                (
                    "intent.json",
                    {
                        "attempt_timeout_milliseconds": 30_000_000,
                        "started_at": NOW.isoformat().replace("+00:00", "Z"),
                    },
                ),
                ("session.json", {"thread_id": "thread-machine"}),
            ):
                path = attempt / name
                path.write_bytes(canonical_bytes(value))
                path.chmod(0o600)
            runner = FakeRunner()
            provider = CodexExecProvider(
                workspace,
                executable=sys.executable,
                clock=lambda: NOW,
                attempt_root=attempts,
                runner=runner,
            )
            observation = provider.invoke(
                "create_task", self.v2_payload(maximum_calls=3), key
            )
            self.assertEqual(observation["provider_id"], "thread-machine")
            argv = runner.calls[-1][0]
            self.assertEqual(argv[:3], (provider.executable, "exec", "resume"))
            self.assertIn("thread-machine", argv)
            self.assertTrue((attempt / "resume.json").is_file())
            self.assertTrue((attempt / "attempt.json").is_file())

            no_second_exec = FakeRunner()
            restored = CodexExecProvider(
                workspace,
                executable=sys.executable,
                clock=lambda: NOW,
                attempt_root=attempts,
                runner=no_second_exec,
            )
            self.assertEqual(
                restored.readback("create_task", key)["provider_id"],
                "thread-machine",
            )
            self.assertEqual(no_second_exec.calls, [])

    def test_incomplete_attempt_recovery_routes_to_specific_wait_without_resend(self):
        cases = (
            (
                "failure",
                {"failure.json": {"code": "PROCESS_TIMEOUT"}},
                "RECONCILE_WORKSPACE",
                "PASS",
            ),
            (
                "reconcile",
                {"session.json": {"thread_id": "thread-machine"}},
                "RECONCILE_WORKSPACE",
                "PASS",
            ),
            (
                "resume-consumed",
                {
                    "session.json": {"thread_id": "thread-machine"},
                    "resume.json": {"thread_id": "thread-machine"},
                },
                "already consumed",
                "PASS",
            ),
            (
                "non-replayable",
                {"session.json": {"thread_id": "thread-machine"}},
                "Human confirmation",
                "LIMITATION",
            ),
        )
        for label, files, expected, expected_outcome in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                workspace = root / "workspace"
                workspace.mkdir()
                attempts = root / "attempts"
                attempts.mkdir(mode=0o700)
                key = f"recovery-{label}"
                attempt = attempts / exec_provider._private_attempt_name(key)
                attempt.mkdir(mode=0o700)
                for name, value in {"intent.json": {}, **files}.items():
                    path = attempt / name
                    path.write_bytes(canonical_bytes(value))
                    path.chmod(0o600)
                runner = FakeRunner()
                provider = CodexExecProvider(
                    workspace,
                    executable=sys.executable,
                    clock=lambda: NOW,
                    attempt_root=attempts,
                    runner=runner,
                )
                selected_payload = self.v2_payload(maximum_calls=3)
                if label == "non-replayable":
                    selected_payload = {
                        **selected_payload,
                        "goal_policy": {
                            **selected_payload["goal_policy"],
                            "replay_safety": "non_replayable",
                        },
                    }
                elif label == "reconcile":
                    selected_payload = {
                        **selected_payload,
                        "goal_policy": {
                            **selected_payload["goal_policy"],
                            "recovery_policy": "reconcile",
                        },
                    }
                observation = provider.invoke("create_task", selected_payload, key)
                result = provider.read_task_result(observation["provider_id"])
                self.assertEqual(result["result"]["outcome"], expected_outcome)
                self.assertIn(expected, result["result"]["summary"])
                self.assertEqual(len(runner.calls), 2)  # version/help only

    def test_pure_argv_is_exact_shell_free_contract_for_non_git_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            self.assertFalse((root / ".git").exists())
            self.assertEqual(
                build_exec_argv(
                    "/safe/codex",
                    root,
                    root / "schema.json",
                    root / "result.json",
                ),
                (
                    "/safe/codex",
                    "exec",
                    "--json",
                    "--output-schema",
                    str(root / "schema.json"),
                    "--output-last-message",
                    str(root / "result.json"),
                    "--strict-config",
                    "--ignore-user-config",
                    "--ignore-rules",
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
            schema_path = Path(argv[argv.index("--output-schema") + 1])
            result_path = Path(argv[argv.index("--output-last-message") + 1])
            self.assertEqual(
                argv,
                build_exec_argv(provider.executable, root, schema_path, result_path),
            )
            self.assertFalse(schema_path.exists())
            self.assertFalse(schema_path.parent.exists())
            self.assertFalse(result_path.exists())
            self.assertNotIn(root, schema_path.parents)
            self.assertEqual(
                runner.schema_snapshots,
                [(schema_path, canonical_bytes(result_payload_schema()))],
            )
            self.assertEqual(runner.result_snapshots, [(result_path, canonical_bytes(RESULT))])
            before_dev, before_ino, before_mode, after_dev, after_ino, after_mode, directory_mode = runner.result_identities[0]
            self.assertEqual((before_dev, before_ino), (after_dev, after_ino))
            self.assertEqual((before_mode, after_mode, directory_mode), (0o600, 0o600, 0o700))
            self.assertEqual(kwargs["cwd"], root)
            self.assertTrue(kwargs["stdin_bytes"].endswith(b"\n"))
            prompt = kwargs["stdin_bytes"].decode("utf-8")
            self.assertIn('"goal":"Complete one disposable task"', prompt)
            self.assertNotIn(KEY, prompt)
            self.assertNotIn("semantic line matching", prompt)
            self.assertIn("machine-supplied output schema is authoritative", prompt)
            self.assertEqual(observation["status"], "OBSERVED")
            self.assertEqual(observation["trust"], "authoritative")
            self.assertEqual(
                provider.readback("create_task", KEY), observation
            )
            result = provider.read_task_result("thread-machine")
            self.assertEqual(result["status"], "COMPLETED")
            self.assertEqual(result["result"], RESULT)
            expected_schema_digest = domain_digest(
                "loopskill-codex-result-schema-v1\n", result_payload_schema()
            )
            self.assertEqual(result["result_schema_digest"], expected_schema_digest)
            self.assertEqual(
                result["result_digest"],
                domain_digest(
                    "loopskill-host-result-v1\n",
                    {
                        "result": RESULT,
                        "result_schema_digest": expected_schema_digest,
                    },
                ),
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
            schema_path = Path(
                runner.calls[-1][0][runner.calls[-1][0].index("--output-schema") + 1]
            )
            self.assertFalse(schema_path.exists())
            self.assertFalse(schema_path.parent.exists())
            with self.assertRaises(HostUnavailable):
                provider.invoke("create_task", payload(), KEY)
            self.assertEqual(len(runner.calls), calls_after_loss)
            self.assertIsNone(provider.readback("create_task", KEY))
            self.assertEqual(provider.metrics["task_create_count"], 1)
            self.assertEqual(provider.metrics["duplicate_invoke_rejection_count"], 1)
            self.assertEqual(provider.metrics["provider_resend_count"], 0)

    def test_nonzero_fails_but_bounded_stderr_is_diagnostic_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(
                Path(temporary),
                FakeRunner(
                    exec_result=_ProcessResult(("codex",), 9, success_jsonl(), b"notice")
                ),
            )
            with self.assertRaises(HostResponseLost) as caught:
                provider.invoke("create_task", payload(), KEY)
            self.assertEqual(caught.exception.provider_code, "PROCESS_EXIT_NONZERO")
            self.assertEqual(provider.terminal_diagnostic()["stderr_bytes"], 6)
            self.assertIsNone(provider.terminal_diagnostic()["semantic_outcome"])
            self.assertIsNone(provider.terminal_diagnostic()["semantic_summary"])
            self.assertIsNone(provider.readback("create_task", KEY))
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(
                Path(temporary),
                FakeRunner(
                    exec_result=_ProcessResult(("codex",), 0, success_jsonl(), b"progress\n")
                ),
            )
            provider.invoke("create_task", payload(), KEY)
            diagnostic = provider.terminal_diagnostic()
            self.assertEqual(diagnostic["code"], "PASS")
            self.assertEqual(diagnostic["semantic_outcome"], "PASS")
            self.assertEqual(diagnostic["semantic_summary"], "complete")
            self.assertEqual(diagnostic["stderr_bytes"], len(b"progress\n"))
            self.assertEqual(diagnostic["stderr_sha256"], hashlib.sha256(b"progress\n").hexdigest())

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
        self.assertEqual(transcript.terminal_event_type, "turn.completed")
        self.assertEqual(transcript.terminal_event_count, 1)

    def test_jsonl_failure_matrix_is_fail_closed(self):
        valid = [
            {"thread_id": "thread-machine", "type": "thread.started"},
            {"type": "turn.started"},
            {
                "item": {"id": "message", "text": RESULT_TEXT, "type": "agent_message"},
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
            "oversized_line": b"{" + b"x" * (1024 * 1024) + b"}\n",
        }
        for name, raw in cases.items():
            with self.subTest(name=name), self.assertRaises(HostResponseLost):
                _parse_jsonl(raw)

    def test_jsonl_failure_classification_is_specific_and_privacy_safe(self):
        cases = (
            (b"{bad}\n", "STDOUT_JSONL_INVALID"),
            (
                event_bytes(
                    {"thread_id": "one", "type": "thread.started"},
                    {"thread_id": "two", "type": "thread.started"},
                ),
                "THREAD_IDENTITY_INVALID",
            ),
            (
                event_bytes(
                    {"thread_id": "one", "type": "thread.started"},
                    {"type": "turn.started"},
                    {"type": "turn.failed"},
                ),
                "TURN_TERMINAL_FAILED",
            ),
        )
        for raw, code in cases:
            with self.subTest(code=code), self.assertRaises(HostResponseLost) as caught:
                _parse_jsonl(raw)
            self.assertEqual(caught.exception.provider_code, code)

        failed_jsonl = event_bytes(
            {"thread_id": "one", "type": "thread.started"},
            {"type": "turn.started"},
            {"type": "turn.failed"},
        )
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(
                Path(temporary),
                FakeRunner(
                    exec_result=_ProcessResult(("codex",), 0, failed_jsonl, b"")
                ),
            )
            with self.assertRaises(HostResponseLost):
                provider.invoke("create_task", payload(), KEY)
            diagnostic = provider.terminal_diagnostic()
            self.assertEqual(diagnostic["terminal_event_count"], 1)
            self.assertEqual(diagnostic["terminal_event_type"], "turn.failed")

    def test_structured_result_accepts_exactly_the_four_manifest_enums(self):
        schema = result_payload_schema()
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["required"], ["outcome", "summary"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            schema["properties"]["outcome"]["enum"],
            ["PASS", "FAILED", "LIMITATION", "UNVERIFIABLE"],
        )
        self.assertEqual(schema["properties"]["summary"]["minLength"], 1)
        self.assertEqual(schema["properties"]["summary"]["maxLength"], 4096)
        for outcome in ("PASS", "FAILED", "LIMITATION", "UNVERIFIABLE"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as temporary:
                value = {"outcome": outcome, "summary": "bounded evidence"}
                provider = self.provider(
                    Path(temporary), FakeRunner(result_bytes=canonical_bytes(value))
                )
                provider.invoke("create_task", payload(), KEY)
                self.assertEqual(provider.read_task_result("thread-machine")["result"], value)
                diagnostic = provider.terminal_diagnostic()
                self.assertEqual(diagnostic["semantic_outcome"], outcome)
                self.assertEqual(diagnostic["semantic_summary"], "bounded evidence")

    def test_structured_result_rejects_shape_type_encoding_and_size_drift(self):
        invalid = {
            "additional": '{"extra":1,"outcome":"PASS","summary":"ok"}',
            "missing": '{"outcome":"PASS"}',
            "wrong_type": '{"outcome":"PASS","summary":7}',
            "unknown_enum": '{"outcome":"PASS|FAILED|LIMITATION|UNVERIFIABLE","summary":"ok"}',
            "blank": '{"outcome":"PASS","summary":"   "}',
            "oversized": json.dumps(
                {"outcome": "PASS", "summary": "é" * 4096}, ensure_ascii=False
            ),
            "malformed": '{"outcome":"PASS","summary":',
        }
        for name, result in invalid.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                provider = self.provider(
                    Path(temporary), FakeRunner(result_bytes=result.encode("utf-8"))
                )
                with self.assertRaises(HostResponseLost) as caught:
                    provider.invoke("create_task", payload(), KEY)
                self.assertEqual(caught.exception.provider_code, "RESULT_SCHEMA_INVALID")

    def test_schema_path_replacement_fails_closed_and_is_cleaned(self):
        class ReplacingRunner(FakeRunner):
            def __call__(self, argv, **kwargs):
                result = super().__call__(argv, **kwargs)
                if tuple(argv)[-1:] == ("-",):
                    schema_path = Path(argv[tuple(argv).index("--output-schema") + 1])
                    schema_path.unlink()
                    schema_path.symlink_to(Path("/dev/null"))
                return result

        with tempfile.TemporaryDirectory() as temporary:
            runner = ReplacingRunner()
            provider = self.provider(Path(temporary), runner)
            with self.assertRaisesRegex(HostResponseLost, "control file identity"):
                provider.invoke("create_task", payload(), KEY)
            schema_path = runner.schema_snapshots[0][0]
            self.assertFalse(schema_path.exists())
            self.assertFalse(schema_path.parent.exists())
            self.assertEqual(provider.metrics["task_create_count"], 1)
            self.assertEqual(provider.metrics["provider_resend_count"], 0)

    def test_schema_content_race_fails_closed_and_is_cleaned(self):
        class MutatingRunner(FakeRunner):
            def __call__(self, argv, **kwargs):
                result = super().__call__(argv, **kwargs)
                if tuple(argv)[-1:] == ("-",):
                    schema_path = Path(argv[tuple(argv).index("--output-schema") + 1])
                    schema_path.chmod(0o600)
                    schema_path.write_bytes(b"{}")
                    schema_path.chmod(0o400)
                return result

        with tempfile.TemporaryDirectory() as temporary:
            runner = MutatingRunner()
            provider = self.provider(Path(temporary), runner)
            with self.assertRaisesRegex(HostResponseLost, "schema control content"):
                provider.invoke("create_task", payload(), KEY)
            schema_path = runner.schema_snapshots[0][0]
            self.assertFalse(schema_path.exists())
            self.assertFalse(schema_path.parent.exists())

    def test_control_cleanup_failure_has_exact_classification(self):
        class BlockingCleanupRunner(FakeRunner):
            blocker = None

            def __call__(self, argv, **kwargs):
                result = super().__call__(argv, **kwargs)
                if tuple(argv)[-1:] == ("-",):
                    result_path = Path(
                        argv[tuple(argv).index("--output-last-message") + 1]
                    )
                    self.blocker = result_path.parent / "foreign"
                    self.blocker.write_bytes(b"block cleanup")
                return result

        with tempfile.TemporaryDirectory() as temporary:
            runner = BlockingCleanupRunner()
            provider = self.provider(Path(temporary), runner)
            with self.assertRaises(HostResponseLost) as caught:
                provider.invoke("create_task", payload(), KEY)
            self.assertEqual(caught.exception.provider_code, "CONTROL_CLEANUP_FAILED")
            self.assertEqual(
                provider.terminal_diagnostic()["code"], "CONTROL_CLEANUP_FAILED"
            )
            self.assertIsNone(provider.terminal_diagnostic()["primary_code"])
            assert runner.blocker is not None
            directory = runner.blocker.parent
            runner.blocker.unlink()
            directory.rmdir()

    def test_primary_failure_is_preserved_when_cleanup_also_fails(self):
        class InvalidBlockingRunner(FakeRunner):
            blocker = None

            def __init__(self):
                super().__init__(result_bytes=b'{"outcome":"PASS"}')

            def __call__(self, argv, **kwargs):
                result = super().__call__(argv, **kwargs)
                if tuple(argv)[-1:] == ("-",):
                    result_path = Path(
                        argv[tuple(argv).index("--output-last-message") + 1]
                    )
                    self.blocker = result_path.parent / "foreign"
                    self.blocker.write_bytes(b"block cleanup")
                return result

        with tempfile.TemporaryDirectory() as temporary:
            runner = InvalidBlockingRunner()
            provider = self.provider(Path(temporary), runner)
            with self.assertRaises(HostResponseLost) as caught:
                provider.invoke("create_task", payload(), KEY)
            self.assertEqual(caught.exception.provider_code, "CONTROL_CLEANUP_FAILED")
            diagnostic = provider.terminal_diagnostic()
            self.assertEqual(diagnostic["code"], "CONTROL_CLEANUP_FAILED")
            self.assertEqual(diagnostic["primary_code"], "RESULT_SCHEMA_INVALID")
            assert runner.blocker is not None
            directory = runner.blocker.parent
            runner.blocker.unlink()
            directory.rmdir()

    def test_unclassified_runner_failure_is_not_mislabeled_as_cleanup(self):
        class UnexpectedRunner(FakeRunner):
            def __call__(self, argv, **kwargs):
                result = super().__call__(argv, **kwargs)
                if tuple(argv)[-1:] == ("-",):
                    raise RuntimeError("synthetic unexpected runner failure")
                return result

        with tempfile.TemporaryDirectory() as temporary:
            runner = UnexpectedRunner()
            provider = self.provider(Path(temporary), runner)
            with self.assertRaises(HostResponseLost) as caught:
                provider.invoke("create_task", payload(), KEY)
            self.assertEqual(
                caught.exception.provider_code, "UNCLASSIFIED_PROVIDER_FAILURE"
            )
            self.assertEqual(
                provider.terminal_diagnostic()["code"],
                "UNCLASSIFIED_PROVIDER_FAILURE",
            )
            self.assertIsNone(provider.terminal_diagnostic()["primary_code"])

    def test_opened_fd_identity_rejects_regular_file_swap_after_path_check(self):
        original_open = os.open
        swapped = False

        def racing_open(path, flags, *args, **kwargs):
            nonlocal swapped
            candidate = Path(path)
            access_mode = flags & os.O_ACCMODE
            if (
                not swapped
                and candidate.name == "result.json"
                and access_mode == os.O_RDONLY
            ):
                swapped = True
                replacement = candidate.with_name("replacement.json")
                descriptor = original_open(
                    replacement,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                try:
                    os.write(descriptor, canonical_bytes(RESULT))
                finally:
                    os.close(descriptor)
                candidate.unlink()
                os.replace(replacement, candidate)
            return original_open(path, flags, *args, **kwargs)

        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            exec_provider.os, "open", side_effect=racing_open
        ):
            provider = self.provider(Path(temporary), FakeRunner())
            with self.assertRaises(HostResponseLost) as caught:
                provider.invoke("create_task", payload(), KEY)
            self.assertTrue(swapped)
            self.assertEqual(caught.exception.provider_code, "RESULT_FILE_IDENTITY_DRIFT")
            self.assertEqual(
                provider.terminal_diagnostic()["code"],
                "RESULT_FILE_IDENTITY_DRIFT",
            )

    def test_result_missing_replacement_and_oversize_fail_with_exact_codes(self):
        class ReplacingResultRunner(FakeRunner):
            def __call__(self, argv, **kwargs):
                result = super().__call__(argv, **kwargs)
                if tuple(argv)[-1:] == ("-",):
                    result_path = Path(
                        argv[tuple(argv).index("--output-last-message") + 1]
                    )
                    result_path.unlink()
                    result_path.symlink_to(Path("/dev/null"))
                return result

        variants = (
            (FakeRunner(result_bytes=None), "RESULT_FILE_MISSING"),
            (ReplacingResultRunner(), "RESULT_FILE_IDENTITY_DRIFT"),
            (FakeRunner(result_bytes=b"x" * (16 * 1024 + 1)), "RESULT_FILE_OVERSIZE"),
        )
        for runner, code in variants:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as temporary:
                provider = self.provider(Path(temporary), runner)
                with self.assertRaises(HostResponseLost) as caught:
                    provider.invoke("create_task", payload(), KEY)
                self.assertEqual(caught.exception.provider_code, code)
                diagnostic = provider.terminal_diagnostic()
                self.assertEqual(diagnostic["code"], code)
                result_path = runner.result_snapshots[0][0]
                self.assertFalse(result_path.exists())
                self.assertFalse(result_path.parent.exists())

    def test_preflight_rejects_missing_output_schema_capability(self):
        class MissingSchemaRunner(FakeRunner):
            def __call__(self, argv, **kwargs):
                result = super().__call__(argv, **kwargs)
                if tuple(argv)[-2:] == ("exec", "--help"):
                    return _ProcessResult(
                        tuple(argv), 0, result.stdout.replace(b"--output-schema", b""), b""
                    )
                return result

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(HostUnavailable):
                self.provider(Path(temporary), MissingSchemaRunner()).preflight()

    def test_preflight_rejects_missing_output_last_message_capability(self):
        class MissingResultRunner(FakeRunner):
            def __call__(self, argv, **kwargs):
                result = super().__call__(argv, **kwargs)
                if tuple(argv)[-2:] == ("exec", "--help"):
                    return _ProcessResult(
                        tuple(argv),
                        0,
                        result.stdout.replace(b"--output-last-message", b""),
                        b"",
                    )
                return result

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(HostUnavailable):
                self.provider(Path(temporary), MissingResultRunner()).preflight()

    def test_adapter_rejects_self_consistent_result_bound_to_foreign_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary), FakeRunner())
            provider.invoke("create_task", payload(), KEY)
            assert provider._record is not None
            provider._record["result_schema_digest"] = "0" * 64
            adapter = CodexHostAdapter(
                provider,
                object(),
                executor_ref="machine-executor",
                issuer_ref=provider.issuer_ref,
                issuer_trust=provider.issuer_trust,
                clock=lambda: NOW,
            )
            with self.assertRaisesRegex(ProtocolRejection, "task result digest"):
                adapter.read_task_result("thread-machine")

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
            with self.assertRaises(HostResponseLost) as stderr:
                _run_bounded_process(
                    (sys.executable, "-c", "import sys; sys.stderr.write('x' * 1000)"),
                    cwd=root,
                    stdin_bytes=b"",
                    timeout_seconds=3,
                    stdout_limit=100,
                    stderr_limit=100,
                )
            self.assertEqual(
                stderr.exception.provider_code, "STDERR_DIAGNOSTIC_OVERFLOW"
            )

    def test_bounded_runner_classifies_spawn_timeout_and_reap_failures(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with self.assertRaises(HostUnavailable) as spawn:
                _run_bounded_process(
                    (str(root / "missing-executable"),),
                    cwd=root,
                    stdin_bytes=b"",
                    timeout_seconds=1,
                    stdout_limit=100,
                    stderr_limit=100,
                )
            self.assertEqual(spawn.exception.provider_code, "PROCESS_SPAWN_FAILED")
            with self.assertRaises(HostResponseLost) as timeout:
                _run_bounded_process(
                    (sys.executable, "-c", "import time; time.sleep(5)"),
                    cwd=root,
                    stdin_bytes=b"",
                    timeout_seconds=0.1,
                    stdout_limit=100,
                    stderr_limit=100,
                )
            self.assertEqual(timeout.exception.provider_code, "PROCESS_TIMEOUT")
            reap_error = exec_provider._coded_error(
                "PROCESS_REAP_FAILED", "synthetic reap failure"
            )
            with mock.patch.object(
                exec_provider, "_terminate_process_group", side_effect=reap_error
            ), self.assertRaises(HostResponseLost) as reap:
                _run_bounded_process(
                    (sys.executable, "-c", "pass"),
                    cwd=root,
                    stdin_bytes=b"",
                    timeout_seconds=1,
                    stdout_limit=100,
                    stderr_limit=100,
                )
            self.assertEqual(reap.exception.provider_code, "PROCESS_REAP_FAILED")

    def test_canary_persists_exact_private_provider_failure_without_pass_receipt(self):
        class InvalidArtifactRunner(ArtifactRunner):
            def __init__(self, workspace):
                super().__init__(workspace)
                self.result_bytes = b'{"outcome":"PASS"}'

        candidate = "b" * 40
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            canary, "_validate_candidate", return_value=candidate
        ), mock.patch.object(
            canary,
            "_candidate_provenance",
            return_value=fake_candidate_provenance(candidate),
        ):
            root = Path(temporary)
            inputs = root / "host-inputs"
            inputs.mkdir()
            config = inputs / "config.toml"
            auth = inputs / "auth.json"
            config.write_bytes(b"synthetic config\n")
            auth.write_bytes(b"synthetic auth\n")
            evidence = root / "evidence"
            with self.assertRaisesRegex(
                canary.CanaryError, "CANARY_PROVIDER_RESULT_SCHEMA_INVALID"
            ):
                canary.run_canary(
                    candidate,
                    evidence,
                    confirmation_callback=lambda boundary: bool(boundary),
                    integrity_inputs={
                        "host_auth": auth.resolve(),
                        "host_config": config.resolve(),
                    },
                    provider_factory=lambda workspace: CodexExecProvider(
                        workspace,
                        executable=sys.executable,
                        issuer_ref=canary.CANARY_ISSUER,
                        issuer_trust=canary.CANARY_TRUST,
                        clock=lambda: NOW,
                        runner=InvalidArtifactRunner(workspace),
                    ),
                    clock=lambda: NOW,
                    token_factory=lambda: "000000000000000000000098",
                )
            diagnostic = json.loads(
                (evidence / canary.CANARY_PROVIDER_DIAGNOSTIC_FILENAME).read_text()
            )
            self.assertEqual(diagnostic["code"], "RESULT_SCHEMA_INVALID")
            self.assertEqual(diagnostic["returncode_class"], "ZERO")
            self.assertGreater(diagnostic["result_bytes"], 0)
            self.assertIsNone(diagnostic["semantic_outcome"])
            self.assertIsNone(diagnostic["semantic_summary"])
            serialized = json.dumps(diagnostic, sort_keys=True)
            self.assertNotIn(str(root), serialized)
            self.assertNotIn("thread-machine", serialized)
            self.assertNotIn('"outcome"', serialized)
            self.assertFalse((evidence / canary.CANARY_RECEIPT_FILENAME).exists())

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
            with self.assertRaises(HostResponseLost) as interrupted:
                _run_bounded_process(
                    (sys.executable, "-c", "import time; time.sleep(60)"),
                    cwd=Path(temporary).resolve(),
                    stdin_bytes=b"",
                    timeout_seconds=3,
                    stdout_limit=100,
                    stderr_limit=100,
                )
            self.assertEqual(interrupted.exception.provider_code, "PROCESS_INTERRUPTED")
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
        ), mock.patch.object(
            canary,
            "_candidate_provenance",
            return_value=fake_candidate_provenance(candidate),
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
        exec_calls = [call for call in calls if call[0][-1:] == ("-",)]
        self.assertEqual(len(exec_calls), 1)
        stdin = exec_calls[0][1]["stdin_bytes"]
        self.assertIn(canary.CANARY_GOAL.encode("utf-8"), stdin)
        self.assertNotIn(candidate.encode("ascii"), stdin)
        for forbidden in (
            b"candidate_sha",
            b"commit_sha",
            b"thread_id",
            b"task_id",
            b"receipt_ref",
            b"control_namespace",
        ):
            self.assertNotIn(forbidden, stdin)


if __name__ == "__main__":
    unittest.main()
