from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install.sh"
UNINSTALLER_PATH = ROOT / "scripts/uninstall_v4.py"
SPEC = importlib.util.spec_from_file_location("uninstall_v4", UNINSTALLER_PATH)
assert SPEC and SPEC.loader
uninstall_v4 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(uninstall_v4)


def tree_bytes(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class V4RcDistributionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.codex_home = Path(self.tempdir.name) / "isolated-codex-home"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @property
    def target(self) -> Path:
        return self.codex_home / "skills/loopskill4"

    @property
    def legacy_target(self) -> Path:
        return self.codex_home / "skills/codex-loop-prompt-architect"

    def _install(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(INSTALLER)],
            cwd=ROOT,
            env={
                **os.environ,
                "CODEX_HOME": str(self.codex_home),
                "PYTHON": sys.executable,
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def _receipts(self) -> list[Path]:
        root = self.codex_home / "install-receipts/loopskill4"
        return sorted(root.glob("*.json")) if root.is_dir() else []

    def _latest_receipt(self) -> Path:
        values = self._receipts()
        self.assertTrue(values)
        return values[-1]

    def _seed_config_and_v3(self) -> tuple[bytes, dict[str, bytes]]:
        self.codex_home.mkdir(parents=True, exist_ok=True)
        config = (
            b'model = "keep"\n\n'
            b'[mcp_servers.unrelated]\ncommand = "leave-me-alone"\n'
        )
        (self.codex_home / "config.toml").write_bytes(config)
        self.legacy_target.mkdir(parents=True)
        (self.legacy_target / "OLD").write_bytes(b"independent v3 bytes\n")
        return config, tree_bytes(self.legacy_target)

    def test_isolated_install_is_v4_only_and_config_byte_identical(self) -> None:
        original_config, original_v3 = self._seed_config_and_v3()
        result = self._install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.target / "scripts/loopskill4").is_file())
        self.assertTrue((self.target / "protocol/v4/loopskill-v4.protocol.json").is_file())
        self.assertFalse((self.target / "scripts/loop_architect/v4_compat").exists())
        self.assertFalse((self.target / "scripts/configure_mcp.py").exists())
        self.assertEqual((self.codex_home / "config.toml").read_bytes(), original_config)
        self.assertEqual(tree_bytes(self.legacy_target), original_v3)

        receipt = json.loads(self._latest_receipt().read_text(encoding="utf-8"))
        self.assertEqual(receipt["artifact"], "loopskill4-install-receipt-v1")
        self.assertEqual(receipt["version"], "4.0.0")
        self.assertEqual(receipt["source_install_drift"], [])
        self.assertEqual(
            receipt["source_manifest_digest"], receipt["installed_manifest_digest"]
        )
        self.assertEqual(receipt["config_before_sha256"], receipt["config_after_sha256"])
        self.assertEqual(receipt["mcp_entries_added"], 0)
        self.assertEqual(receipt["mcp_processes_created"], 0)
        self.assertFalse(receipt["restart_required_by_loopskill"])
        self.assertIn("no MCP entry was registered", result.stdout)
        self.assertIn("does not require a Codex App restart", result.stdout)

        smoke = subprocess.run(
            [str(self.target / "scripts/loopskill4"), "intake", "fix one typo"],
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(smoke.returncode, 0, smoke.stderr)
        self.assertIn("NEEDS_CLARIFICATION", smoke.stdout)
        doctor = subprocess.run(
            [str(self.target / "scripts/loopskill4"), "doctor", "--diagnostics"],
            env={
                **os.environ,
                "CODEX_HOME": str(self.codex_home),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        value = json.loads(doctor.stdout)
        self.assertEqual(value["status"], "READY")
        self.assertEqual(
            value["diagnostics"]["capabilities"]["install_receipt"], "AVAILABLE"
        )

    def test_second_install_is_an_exact_idempotent_noop(self) -> None:
        config, legacy = self._seed_config_and_v3()
        first = self._install()
        self.assertEqual(first.returncode, 0, first.stderr)
        before_target = tree_bytes(self.target)
        before_receipts = tree_bytes(self.codex_home / "install-receipts/loopskill4")
        second = self._install()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("already installed", second.stdout)
        self.assertEqual(tree_bytes(self.target), before_target)
        self.assertEqual(
            tree_bytes(self.codex_home / "install-receipts/loopskill4"),
            before_receipts,
        )
        self.assertEqual((self.codex_home / "config.toml").read_bytes(), config)
        self.assertEqual(tree_bytes(self.legacy_target), legacy)

    def test_conflicting_v4_target_fails_without_config_or_v3_mutation(self) -> None:
        config, legacy = self._seed_config_and_v3()
        self.target.mkdir(parents=True)
        (self.target / "FOREIGN").write_bytes(b"not managed by LoopSkill\n")
        target_before = tree_bytes(self.target)
        result = self._install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("V4_INSTALL_CONFLICT", result.stderr)
        self.assertEqual(tree_bytes(self.target), target_before)
        self.assertEqual((self.codex_home / "config.toml").read_bytes(), config)
        self.assertEqual(tree_bytes(self.legacy_target), legacy)
        self.assertEqual(self._receipts(), [])

    def test_uninstall_removes_only_receipt_bound_v4_install(self) -> None:
        config, legacy = self._seed_config_and_v3()
        installed = self._install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        receipt = self._latest_receipt()
        result = uninstall_v4.uninstall(self.codex_home, receipt)
        self.assertEqual(result["status"], "UNINSTALLED")
        self.assertFalse(self.target.exists())
        self.assertEqual((self.codex_home / "config.toml").read_bytes(), config)
        self.assertEqual(tree_bytes(self.legacy_target), legacy)
        self.assertEqual(result["loop_store_mutations"], 0)
        self.assertEqual(result["mcp_entries_removed"], 0)
        again = uninstall_v4.uninstall(self.codex_home, receipt)
        self.assertEqual(again["status"], "ALREADY_UNINSTALLED")

    def test_uninstall_precommit_faults_restore_exact_installed_state(self) -> None:
        for boundary in ("after_skill_withdrawn", "after_config_verified"):
            with self.subTest(boundary=boundary):
                self.codex_home = Path(self.tempdir.name) / boundary
                config, legacy = self._seed_config_and_v3()
                installed = self._install()
                self.assertEqual(installed.returncode, 0, installed.stderr)
                receipt = self._latest_receipt()
                target_before = tree_bytes(self.target)

                def fail(name: str) -> None:
                    if name == boundary:
                        raise RuntimeError(boundary)

                with self.assertRaisesRegex(RuntimeError, boundary):
                    uninstall_v4.uninstall(self.codex_home, receipt, fault=fail)
                self.assertEqual(tree_bytes(self.target), target_before)
                self.assertEqual((self.codex_home / "config.toml").read_bytes(), config)
                self.assertEqual(tree_bytes(self.legacy_target), legacy)

    def test_uninstall_postcommit_fault_has_exact_committed_state(self) -> None:
        config, legacy = self._seed_config_and_v3()
        installed = self._install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        receipt = self._latest_receipt()

        def fail(name: str) -> None:
            if name == "after_commit":
                raise RuntimeError(name)

        with self.assertRaisesRegex(RuntimeError, "after_commit"):
            uninstall_v4.uninstall(self.codex_home, receipt, fault=fail)
        self.assertFalse(self.target.exists())
        self.assertEqual((self.codex_home / "config.toml").read_bytes(), config)
        self.assertEqual(tree_bytes(self.legacy_target), legacy)
        self.assertEqual(
            uninstall_v4.uninstall(self.codex_home, receipt)["status"],
            "ALREADY_UNINSTALLED",
        )

    def test_uninstall_drift_and_outside_receipt_fail_before_mutation(self) -> None:
        config, legacy = self._seed_config_and_v3()
        installed = self._install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        receipt = self._latest_receipt()
        marker = self.target / "DRIFT"
        marker.write_bytes(b"drift")
        with self.assertRaisesRegex(
            uninstall_v4.UninstallError, "V4_UNINSTALL_INSTALL_DRIFT"
        ):
            uninstall_v4.uninstall(self.codex_home, receipt)
        self.assertEqual(marker.read_bytes(), b"drift")
        self.assertEqual((self.codex_home / "config.toml").read_bytes(), config)
        self.assertEqual(tree_bytes(self.legacy_target), legacy)

        outside = Path(self.tempdir.name) / "outside.json"
        outside.write_bytes(receipt.read_bytes())
        with self.assertRaisesRegex(
            uninstall_v4.UninstallError, "V4_UNINSTALL_RECEIPT_OUTSIDE_ROOT"
        ):
            uninstall_v4.uninstall(self.codex_home, outside)


if __name__ == "__main__":
    unittest.main()
