from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "codex-loop-prompt-architect" / "scripts"
RUNTIME = SCRIPTS / "adaptive_state_runtime.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from loop_architect.state_runtime import AdaptiveStateRuntime, process_request  # noqa: E402
from loop_architect.rejection_journal import read_rejections  # noqa: E402


class NativeGoalRecoveryUnavailableTests(unittest.TestCase):
    def _run(self, root: Path, payload: dict[str, object], *flags: str) -> dict[str, object]:
        result = subprocess.run(
            [sys.executable, str(RUNTIME), "--root", str(root), *flags],
            input=json.dumps(payload, separators=(",", ":")),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def test_legacy_observer_cli_is_an_unavailable_tombstone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = sorted(path.relative_to(root) for path in root.rglob("*"))
            response = self._run(root, {}, "--native-goal-observe")
            self.assertEqual(
                response["status"],
                "NATIVE_GOAL_GENERATION_RECOVERY_UNAVAILABLE",
            )
            self.assertEqual(
                response["error"]["details"],
                {
                    "availability": "DEFERRED_UNAVAILABLE",
                    "side_effects": "NONE",
                },
            )
            self.assertEqual(
                before,
                sorted(path.relative_to(root) for path in root.rglob("*")),
            )

    def test_legacy_observer_cli_needs_no_input_frame(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(RUNTIME),
                    "--root",
                    str(root),
                    "--native-goal-observe",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(process.wait(timeout=2), 1)
                assert process.stdout is not None
                assert process.stderr is not None
                response = json.loads(process.stdout.read())
                self.assertEqual(
                    response["status"],
                    "NATIVE_GOAL_GENERATION_RECOVERY_UNAVAILABLE",
                )
                self.assertEqual(process.stderr.read(), "")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if process.stdin is not None:
                    process.stdin.close()
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()

    def test_legacy_recovery_mutations_are_rejected_before_state_creation(self) -> None:
        mutation_types = (
            "PREPARE_NATIVE_GOAL_GENERATION_MIGRATION",
            "COMMIT_NATIVE_GOAL_GENERATION_MIGRATION",
            "ROLLBACK_NATIVE_GOAL_GENERATION_MIGRATION",
        )
        for mutation_type in mutation_types:
            with self.subTest(mutation_type=mutation_type), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                response = self._run(
                    root,
                    {"mutation": {"type": mutation_type}},
                )
                self.assertEqual(
                    response["status"],
                    "NATIVE_GOAL_GENERATION_RECOVERY_UNAVAILABLE",
                )
                self.assertFalse((root / ".codex-loop").exists())

    def test_legacy_recovery_lease_scope_is_rejected_before_state_creation(self) -> None:
        scopes = (
            "NATIVE_GOAL_GENERATION_PREPARE",
            "NATIVE_GOAL_GENERATION_COMMIT",
            "NATIVE_GOAL_GENERATION_ROLLBACK",
        )
        for scope in scopes:
            with self.subTest(scope=scope), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                response = self._run(
                    root,
                    {
                        "mutation": {
                            "type": "ACQUIRE_LEASE",
                            "recovery_scope": scope,
                        }
                    },
                )
                self.assertEqual(
                    response["status"],
                    "NATIVE_GOAL_GENERATION_RECOVERY_UNAVAILABLE",
                )
                self.assertFalse((root / ".codex-loop").exists())

    def test_core_runtime_and_convenience_api_have_no_recovery_bypass(self) -> None:
        requests = [
            {"mutation": {"type": mutation_type}}
            for mutation_type in (
                "PREPARE_NATIVE_GOAL_GENERATION_MIGRATION",
                "COMMIT_NATIVE_GOAL_GENERATION_MIGRATION",
                "ROLLBACK_NATIVE_GOAL_GENERATION_MIGRATION",
            )
        ]
        requests.extend(
            {
                "mutation": {
                    "type": "ACQUIRE_LEASE",
                    "recovery_scope": scope,
                }
            }
            for scope in (
                "NATIVE_GOAL_GENERATION_PREPARE",
                "NATIVE_GOAL_GENERATION_COMMIT",
                "NATIVE_GOAL_GENERATION_ROLLBACK",
            )
        )
        for request in requests:
            with self.subTest(request=request), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                for apply_request in (
                    AdaptiveStateRuntime(root).apply,
                    lambda value: process_request(root, value),
                ):
                    response = apply_request(request)
                    self.assertEqual(
                        response["status"],
                        "NATIVE_GOAL_GENERATION_RECOVERY_UNAVAILABLE",
                    )
                    self.assertEqual(
                        response["error"]["details"]["side_effects"],
                        "NONE",
                    )
                    journal = root / ".codex-loop" / "LOOP_REJECTIONS.jsonl"
                    self.assertTrue(journal.is_file())
                    self.assertGreaterEqual(len(read_rejections(journal)), 1)
                    self.assertFalse((root / ".codex-loop" / "LOOP_STATE.md").exists())


if __name__ == "__main__":
    unittest.main()
