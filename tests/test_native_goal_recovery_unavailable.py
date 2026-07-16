from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (
    ROOT
    / "codex-loop-prompt-architect"
    / "scripts"
    / "adaptive_state_runtime.py"
)


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


if __name__ == "__main__":
    unittest.main()
