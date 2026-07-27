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


class V4RcDistributionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.codex_home = Path(self.tempdir.name) / "isolated-codex-home"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

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

    def _latest_receipt(self) -> Path:
        values = sorted(
            (self.codex_home / "install-receipts/codex-loop-prompt-architect").glob("*.json")
        )
        self.assertTrue(values)
        return values[-1]

    def test_isolated_install_contains_v4_entry_and_zero_drift(self) -> None:
        result = self._install()
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.codex_home / "skills/codex-loop-prompt-architect"
        self.assertTrue((installed / "scripts/loopskill4").is_file())
        receipt = json.loads(self._latest_receipt().read_text(encoding="utf-8"))
        self.assertEqual(receipt["source_install_drift"], [])
        self.assertEqual(
            receipt["source_manifest_digest"], receipt["installed_manifest_digest"]
        )
        self.assertTrue(receipt["mcp_registration"]["config_readback"])
        smoke = subprocess.run(
            [str(installed / "scripts/loopskill4"), "intake", "fix one typo"],
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(smoke.returncode, 0, smoke.stderr)
        self.assertIn("NEEDS_CLARIFICATION", smoke.stdout)
        doctor = subprocess.run(
            [str(installed / "scripts/loopskill4"), "doctor", "--diagnostics"],
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
        doctor_value = json.loads(doctor.stdout)
        self.assertEqual(doctor_value["status"], "READY")
        self.assertEqual(doctor_value["diagnostics"]["capabilities"]["install_receipt"], "AVAILABLE")
        prepared = Path(self.tempdir.name) / "prepared"
        prepare = subprocess.run(
            [
                str(installed / "scripts/loopskill4"),
                "prepare",
                str(ROOT / "examples/v4-standard-input.json"),
                "--output",
                str(prepared),
            ],
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(prepare.returncode, 0, prepare.stderr)
        compile_result = subprocess.run(
            [str(installed / "scripts/loopskill4"), "compile", str(prepared)],
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
        self.assertEqual(json.loads(compile_result.stdout)["host_effects"], 0)
        broken_compile = subprocess.run(
            [str(installed / "scripts/loopskill4"), "compile", str(prepared / "missing")],
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(broken_compile.returncode, 2)
        self.assertIn("USER_PREPARATION_INVALID", broken_compile.stderr)

        (installed / "SKILL.md").write_bytes(b"drift\n")
        drift_doctor = subprocess.run(
            [str(installed / "scripts/loopskill4"), "doctor"],
            env={
                **os.environ,
                "CODEX_HOME": str(self.codex_home),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(drift_doctor.returncode, 0, drift_doctor.stderr)
        self.assertEqual(json.loads(drift_doctor.stdout)["status"], "BLOCKED")

    def test_uninstall_restores_exact_prior_skill_and_config(self) -> None:
        self.codex_home.mkdir(parents=True)
        original_config = b'model = "keep"\n'
        (self.codex_home / "config.toml").write_bytes(original_config)
        old = self.codex_home / "skills/codex-loop-prompt-architect"
        old.mkdir(parents=True)
        (old / "OLD").write_bytes(b"previous skill bytes\n")
        self.assertEqual(self._install().returncode, 0)
        result = uninstall_v4.uninstall(self.codex_home, self._latest_receipt())
        self.assertEqual(result["status"], "UNINSTALLED")
        self.assertEqual((self.codex_home / "config.toml").read_bytes(), original_config)
        self.assertEqual((old / "OLD").read_bytes(), b"previous skill bytes\n")
        self.assertEqual(result["loop_store_mutations"], 0)

    def test_uninstall_fault_windows_restore_exact_installed_state(self) -> None:
        for boundary in (
            "after_skill_withdrawn",
            "after_config_restored",
            "after_prior_skill_restored",
        ):
            with self.subTest(boundary=boundary):
                self.codex_home = Path(self.tempdir.name) / boundary
                self.assertEqual(self._install().returncode, 0)
                receipt_path = self._latest_receipt()
                target = self.codex_home / "skills/codex-loop-prompt-architect"
                before_files = uninstall_v4._installed_files(target)
                before_config = (self.codex_home / "config.toml").read_bytes()

                def fail(name: str) -> None:
                    if name == boundary:
                        raise RuntimeError(boundary)

                with self.assertRaisesRegex(RuntimeError, boundary):
                    uninstall_v4.uninstall(
                        self.codex_home, receipt_path, fault=fail
                    )
                self.assertEqual(uninstall_v4._installed_files(target), before_files)
                self.assertEqual(
                    (self.codex_home / "config.toml").read_bytes(), before_config
                )

    def test_drift_and_outside_receipt_fail_before_mutation(self) -> None:
        self.assertEqual(self._install().returncode, 0)
        receipt_path = self._latest_receipt()
        target = self.codex_home / "skills/codex-loop-prompt-architect"
        marker = target / "DRIFT"
        marker.write_bytes(b"drift")
        config_before = (self.codex_home / "config.toml").read_bytes()
        with self.assertRaisesRegex(
            uninstall_v4.UninstallError, "UNINSTALL_INSTALL_DRIFT"
        ):
            uninstall_v4.uninstall(self.codex_home, receipt_path)
        self.assertEqual(marker.read_bytes(), b"drift")
        self.assertEqual((self.codex_home / "config.toml").read_bytes(), config_before)
        outside = Path(self.tempdir.name) / "outside.json"
        outside.write_bytes(receipt_path.read_bytes())
        with self.assertRaisesRegex(
            uninstall_v4.UninstallError, "UNINSTALL_RECEIPT_OUTSIDE_ROOT"
        ):
            uninstall_v4.uninstall(self.codex_home, outside)


if __name__ == "__main__":
    unittest.main()
