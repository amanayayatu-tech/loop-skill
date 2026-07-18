from __future__ import annotations

import ast
import importlib.util
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseContractTests(unittest.TestCase):
    def test_installer_dependencies_are_complete_and_exactly_pinned(self) -> None:
        requirements = (ROOT / "requirements-test.txt").read_text(encoding="utf-8")
        self.assertIn("PyYAML==6.0.3", requirements.splitlines())
        installer = (ROOT / "scripts/install.sh").read_text(encoding="utf-8")
        self.assertIn("import jsonschema, yaml", installer)
        self.assertIn("jsonschema, PyYAML, and a TOML reader", installer)

    def test_skill_validator_runs_as_a_covered_library_entrypoint(self) -> None:
        path = ROOT / "codex-loop-prompt-architect/scripts/validate_skill.py"
        scripts_dir = str(path.parent)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        spec = importlib.util.spec_from_file_location("validate_skill_release_contract", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.validate(ROOT / "codex-loop-prompt-architect"), [])

    def test_trusted_route_bridge_is_shipped_and_installed(self) -> None:
        bridge = ROOT / "codex-loop-prompt-architect" / "scripts" / "adaptive_state_mcp.py"
        self.assertTrue(bridge.is_file())
        installer = (ROOT / "scripts" / "install.sh").read_text()
        self.assertIn('STATE_MCP="$SOURCE_DIR/scripts/adaptive_state_mcp.py"', installer)
        self.assertIn('chmod +x "$STAGING_DIR/scripts/adaptive_state_mcp.py"', installer)
        self.assertIn('MCP_CONFIG_HELPER="$SOURCE_DIR/scripts/configure_mcp.py"', installer)
        self.assertIn('INSTALL_VERIFY="$SOURCE_DIR/scripts/verify_installation.py"', installer)
        self.assertIn("--check >/dev/null", installer)
        self.assertIn("install-receipts/codex-loop-prompt-architect", installer)
        for relative in (
            "references/install-manifest.schema.json",
            "references/app-canary-receipt.schema.json",
            "scripts/configure_mcp.py",
            "scripts/verify_installation.py",
            "scripts/validate_app_canary_receipt.py",
        ):
            self.assertTrue((ROOT / "codex-loop-prompt-architect" / relative).is_file())
        canary_validator = (
            ROOT
            / "codex-loop-prompt-architect/scripts/validate_app_canary_receipt.py"
        ).read_text(encoding="utf-8")
        for option in (
            "--expected-commit",
            "--expected-tracked-tree-digest",
            "--expected-manifest-digest",
            "--expected-pack-digest",
            "--expected-compatibility-identity-digest",
            "--expected-app-version",
            "--expected-app-build",
            "--expected-bundle-identifier",
        ):
            self.assertIn(option, canary_validator)

    def test_version_and_changelog_share_a_formal_release_or_explicit_candidate_boundary(
        self,
    ) -> None:
        version = (ROOT / "VERSION").read_text().strip()
        self.assertRegex(version, r"^[0-9]+\.[0-9]+\.[0-9]+$")
        changelog = (ROOT / "CHANGELOG.md").read_text()
        candidate_header = f"## [{version}-candidate]"
        if candidate_header in changelog:
            self.assertIn("### Release boundary", changelog)
            self.assertIn("not released until", changelog)
            self.assertIn("fail closed", changelog)
            self.assertNotIn(f"/releases/tag/v{version}", changelog)
        else:
            self.assertIn(f"## [{version}]", changelog)
            self.assertIn(f"/releases/tag/v{version}", changelog)
        for readme in ("README.md", "README.en.md"):
            self.assertIn(f"v{version}", (ROOT / readme).read_text())

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
        workflow_dir = ROOT / ".github" / "workflows"
        workflow = (workflow_dir / "compatibility.yml").read_text()
        self.assertFalse((workflow_dir / "test.yml").exists())
        for job in (
            "quick:",
            "full:",
            "fuzz-generator:",
            "fuzz-state:",
            "coverage:",
            "install-linux:",
            "macos-install:",
            "tag-identity:",
            "final-gate:",
        ):
            self.assertIn(job, workflow)
        self.assertIn('ADAPTIVE_FUZZ_CASES: "5000"', workflow)
        self.assertIn('ADAPTIVE_STATE_FUZZ_CASES: "5000"', workflow)
        self.assertIn("pull_request:", workflow)
        self.assertIn("branches:\n      - main", workflow)
        self.assertIn('tags:\n      - "v*"', workflow)
        self.assertIn("github.event.pull_request.number || github.run_id", workflow)
        self.assertIn("github.event_name == 'pull_request'", workflow)
        self.assertIn("current main Mac's complete", workflow)
        self.assertIn("Main push repeats", workflow)
        self.assertIn("coverage run --parallel-mode", workflow)
        self.assertIn("coverage combine", workflow)
        self.assertIn("verify-gate", workflow)
        self.assertIn("if: always()", workflow)
        self.assertNotIn("full-fuzz:", workflow)
        uses = re.findall(r"^\s*- uses:\s*([^\s#]+)", workflow, re.MULTILINE)
        self.assertGreaterEqual(len(uses), 9)
        for action in uses:
            with self.subTest(action=action):
                self.assertRegex(action, r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")
        self.assertIn("scripts/check_whitespace_range.py", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertNotIn("git show --check --format= HEAD", workflow)
        expected_actions = {
            "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0": "# v7.0.0",
            "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1": "# v6.3.0",
            "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a": "# v7.0.1",
            "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c": "# v8.0.1",
        }
        for action, version_comment in expected_actions.items():
            self.assertIn(f"{action} {version_comment}", workflow)

    def test_coverage_baseline_is_branch_aware_and_bounded(self) -> None:
        config = (ROOT / "pyproject.toml").read_text()
        self.assertIn("branch = true", config)
        self.assertIn('source = ["codex-loop-prompt-architect/scripts", "scripts"]', config)
        match = re.search(r"fail_under\s*=\s*([0-9]+)", config)
        self.assertIsNotNone(match)
        self.assertGreaterEqual(int(match.group(1)), 80)

    def test_current_main_mac_is_the_only_release_authority(self) -> None:
        releasing = (ROOT / "docs/RELEASING.md").read_text(encoding="utf-8")
        self.assertIn("current main Mac is the\nonly release authority", releasing)
        self.assertIn("local main-Mac pre-canary gate", releasing)
        self.assertIn("evidence_layer=local-main-mac", releasing)
        self.assertIn("release_eligible == true", releasing)
        self.assertIn("reasons == []", releasing)
        self.assertIn("GitHub Actions is a\ncompatibility mirror only", releasing)
        self.assertIn("same-SHA App receipt", releasing)
        self.assertIn("tracked-tree SHA-256", releasing)
        self.assertIn("FINALIZATION_ACKED", releasing)
        self.assertIn("app-canary-receipt.schema.json", releasing)
        self.assertIn("native Goal generation recovery status", releasing)
        self.assertIn("DEFERRED_UNAVAILABLE", releasing)
        self.assertIn("zero-effect unavailable contract", releasing)
        self.assertIn("negotiated_protocol_version_status=UNAVAILABLE_BY_HOST", releasing)
        self.assertIn("negotiated_protocol_version=null", releasing)
        self.assertIn("is not evidence of a verified negotiated version", releasing)
        self.assertIn("not by itself a release blocker", releasing)
        self.assertIn("server-declared supported set is an\nobservation", releasing)
        self.assertNotIn("required GitHub Actions checks pass", releasing)
        self.assertNotIn("Mac mini witness", releasing)
        self.assertNotIn("root-owned/read-only", releasing)
        self.assertNotIn("combined release", releasing)

    def test_state_runtime_tests_are_split_without_method_loss(self) -> None:
        compatibility = ROOT / "tests" / "test_adaptive_state_runtime.py"
        self.assertTrue(compatibility.is_file())
        self.assertLess(len(compatibility.read_text().splitlines()), 30)
        self.assertIn("Stable CI entrypoint", compatibility.read_text())
        modules = sorted((ROOT / "tests").glob("test_state_runtime_*.py"))
        self.assertEqual(len(modules), 6)
        names: list[str] = []
        for path in modules:
            self.assertLess(len(path.read_text().splitlines()), 3000)
            tree = ast.parse(path.read_text())
            names.extend(
                node.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
            )
        self.assertEqual(len(names), 122)
        self.assertEqual(len(set(names)), 122)
        self.assertTrue((ROOT / "tests" / "state_runtime_support.py").is_file())


if __name__ == "__main__":
    unittest.main()
