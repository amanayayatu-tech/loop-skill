from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseContractTests(unittest.TestCase):
    def test_trusted_route_bridge_is_shipped_and_installed(self) -> None:
        bridge = ROOT / "codex-loop-prompt-architect" / "scripts" / "adaptive_state_mcp.py"
        self.assertTrue(bridge.is_file())
        installer = (ROOT / "scripts" / "install.sh").read_text()
        self.assertIn('STATE_MCP="$SOURCE_DIR/scripts/adaptive_state_mcp.py"', installer)
        self.assertIn('chmod +x "$STAGING_DIR/scripts/adaptive_state_mcp.py"', installer)

    def test_version_and_changelog_share_the_formal_release(self) -> None:
        version = (ROOT / "VERSION").read_text().strip()
        self.assertRegex(version, r"^[0-9]+\.[0-9]+\.[0-9]+$")
        changelog = (ROOT / "CHANGELOG.md").read_text()
        self.assertIn(f"## [{version}]", changelog)
        self.assertIn(f"/releases/tag/v{version}", changelog)

    def test_readmes_link_both_languages_and_release_documents(self) -> None:
        chinese = (ROOT / "README.md").read_text()
        english = (ROOT / "README.en.md").read_text()
        self.assertIn("[English](README.en.md)", chinese)
        self.assertIn("[简体中文](README.md)", english)
        for relative_path in ("CHANGELOG.md", "docs/RELEASING.md", "evidence/README.md"):
            self.assertTrue((ROOT / relative_path).is_file())
            self.assertIn(relative_path, chinese)
            self.assertIn(relative_path, english)

    def test_evidence_index_links_only_existing_records(self) -> None:
        index_path = ROOT / "evidence" / "README.md"
        targets = re.findall(r"\[[^]]+\]\(([^)]+\.md)\)", index_path.read_text())
        self.assertGreaterEqual(len(targets), 9)
        for target in targets:
            with self.subTest(target=target):
                self.assertTrue((index_path.parent / target).is_file())

    def test_ci_has_fast_full_coverage_and_macos_lanes(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text()
        for job in ("quick:", "full-fuzz:", "coverage:", "macos-install:"):
            self.assertIn(job, workflow)
        self.assertIn('ADAPTIVE_FUZZ_CASES: "5000"', workflow)
        self.assertIn('ADAPTIVE_STATE_FUZZ_CASES: "5000"', workflow)
        self.assertIn("github.event_name == 'pull_request'", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("branches:\n      - main", workflow)
        self.assertIn('tags:\n      - "v*"', workflow)
        self.assertIn("github.event.pull_request.head.ref || github.ref_name", workflow)
        self.assertIn("actions/checkout@v7", workflow)
        self.assertIn("actions/setup-python@v6", workflow)
        self.assertIn("actions/upload-artifact@v7", workflow)
        self.assertNotIn("actions/checkout@v4", workflow)
        self.assertNotIn("actions/setup-python@v5", workflow)

    def test_coverage_baseline_is_branch_aware_and_bounded(self) -> None:
        config = (ROOT / "pyproject.toml").read_text()
        self.assertIn("branch = true", config)
        match = re.search(r"fail_under\s*=\s*([0-9]+)", config)
        self.assertIsNotNone(match)
        self.assertGreaterEqual(int(match.group(1)), 80)

    def test_state_runtime_tests_are_split_without_method_loss(self) -> None:
        self.assertFalse((ROOT / "tests" / "test_adaptive_state_runtime.py").exists())
        modules = sorted((ROOT / "tests").glob("test_state_runtime_*.py"))
        self.assertEqual(len(modules), 5)
        names: list[str] = []
        for path in modules:
            self.assertLess(len(path.read_text().splitlines()), 2500)
            tree = ast.parse(path.read_text())
            names.extend(
                node.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
            )
        self.assertEqual(len(names), 87)
        self.assertEqual(len(set(names)), 87)
        self.assertTrue((ROOT / "tests" / "state_runtime_support.py").is_file())


if __name__ == "__main__":
    unittest.main()
