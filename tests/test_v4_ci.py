from __future__ import annotations

import importlib.util
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_v4_ci.py"
SPEC = importlib.util.spec_from_file_location("check_v4_ci", SCRIPT)
assert SPEC and SPEC.loader
ci = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ci)


class V4CiTests(unittest.TestCase):
    def test_coverage_binds_shipped_v4_runtime_and_omits_archive_aliases(self) -> None:
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(
            config["tool"]["coverage"]["run"]["omit"],
            [
                "codex-loop-prompt-architect/scripts/loop_architect/human_control.py",
                "codex-loop-prompt-architect/scripts/loop_architect/schema.py",
            ],
        )
        self.assertEqual(config["tool"]["coverage"]["report"]["fail_under"], 80)
        self.assertEqual(
            config["tool"]["coverage"]["report"]["include"],
            [
                "codex-loop-prompt-architect/scripts/loop_architect/v4_*/*",
                "codex-loop-prompt-architect/scripts/loopskill4",
            ],
        )
        self.assertEqual(
            config["tool"]["coverage"]["report"]["omit"],
            config["tool"]["coverage"]["run"]["omit"],
        )

    def test_v4_release_workflow_is_the_only_ci_and_passes_contract(self) -> None:
        result = ci.validate(ROOT)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["job_count"], 5)
        self.assertGreaterEqual(result["action_pin_count"], 10)

    def test_unpinned_action_and_legacy_workflow_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github/workflows/v4-release.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_bytes((ROOT / ".github/workflows/v4-release.yml").read_bytes())
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(ci.CHECKOUT, "actions/checkout@v7"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ci.CiError, "CI_ACTION_NOT_FULL_SHA_PINNED"):
                ci.validate(root)
            workflow.write_bytes((ROOT / ".github/workflows/v4-release.yml").read_bytes())
            legacy = root / ".github/workflows/compatibility.yml"
            legacy.write_text("name: Compatibility CI\n", encoding="utf-8")
            with self.assertRaisesRegex(ci.CiError, "CI_WORKFLOW_SET_INVALID"):
                ci.validate(root)

    def test_structural_scope_and_tag_conditions_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github/workflows/v4-release.yml"
            workflow.parent.mkdir(parents=True)
            source = (ROOT / ".github/workflows/v4-release.yml").read_text(
                encoding="utf-8"
            )
            workflow.write_text(
                source.replace("tags: [v4.0.0]", "tags: [v4.0.1]"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ci.CiError, "CI_PUSH_SCOPE_INVALID"):
                ci.validate(root)
            workflow.write_text(
                source.replace(
                    "if: github.ref == 'refs/tags/v4.0.0'",
                    "if: always()",
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ci.CiError, "CI_TAG_CONDITION_INVALID"):
                ci.validate(root)


if __name__ == "__main__":
    unittest.main()
