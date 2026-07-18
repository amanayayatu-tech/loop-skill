from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install.sh"
SKILL = ROOT / "codex-loop-prompt-architect"


def _manifest(root: Path) -> dict[str, tuple[str, bool]]:
    import hashlib

    result: dict[str, tuple[str, bool]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or path.suffix == ".pyc" or path.name == ".DS_Store":
            continue
        if path.is_file():
            result[relative.as_posix()] = (
                hashlib.sha256(path.read_bytes()).hexdigest(),
                bool(path.stat().st_mode & 0o111),
            )
    return result


class InstallerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.codex_home = Path(self.tempdir.name) / "codex-home"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _run(self, python: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(INSTALLER)],
            cwd=ROOT,
            env={
                **os.environ,
                "CODEX_HOME": str(self.codex_home),
                "PYTHON": python or sys.executable,
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_missing_declared_dependencies_fail_before_install_mutation(self) -> None:
        fake_python = Path(self.tempdir.name) / "python-without-dependencies"
        fake_python.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        fake_python.chmod(0o755)
        result = subprocess.run(
            [str(INSTALLER)],
            cwd=ROOT,
            env={
                **os.environ,
                "CODEX_HOME": str(self.codex_home),
                "PYTHON": str(fake_python),
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("jsonschema, PyYAML, and a TOML reader", result.stderr)
        self.assertFalse(self.codex_home.exists())

    def test_isolated_install_registers_exact_identity_and_is_idempotent(self) -> None:
        first = self._run()
        self.assertEqual(first.returncode, 0, first.stderr)
        installed = self.codex_home / "skills/codex-loop-prompt-architect"
        self.assertEqual(_manifest(SKILL), _manifest(installed))
        config_after_first = (self.codex_home / "config.toml").read_bytes()
        second = self._run()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual((self.codex_home / "config.toml").read_bytes(), config_after_first)
        receipts = sorted((self.codex_home / "install-receipts/codex-loop-prompt-architect").glob("*.json"))
        self.assertEqual(len(receipts), 2)
        latest = json.loads(receipts[-1].read_text(encoding="utf-8"))
        self.assertEqual(latest["source_install_drift"], [])
        self.assertEqual(latest["source_manifest_digest"], latest["installed_manifest_digest"])
        self.assertTrue(latest["mcp_registration"]["config_readback"])

    def test_registration_conflict_restores_config_and_previous_skill(self) -> None:
        self.codex_home.mkdir(parents=True)
        config = self.codex_home / "config.toml"
        original_config = (
            b'model = "keep-me"\n\n'
            b'[mcp_servers.codex-loop-state]\n'
            b'command = "/other/python"\n'
            b'args = ["/other/server.py"]\n'
        )
        config.write_bytes(original_config)
        old_skill = self.codex_home / "skills/codex-loop-prompt-architect"
        old_skill.mkdir(parents=True)
        marker = old_skill / "USER_OLD_SKILL.txt"
        marker.write_text("preserve\n", encoding="utf-8")
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MCP_REGISTRATION_IDENTITY_CONFLICT", result.stderr)
        self.assertEqual(config.read_bytes(), original_config)
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve\n")
        self.assertFalse((old_skill / "SKILL.md").exists())

    def test_managed_same_bridge_upgrade_preserves_prior_runtime_and_replaces_skill(self) -> None:
        first = self._run()
        self.assertEqual(first.returncode, 0, first.stderr)
        config = self.codex_home / "config.toml"
        before = config.read_bytes()
        replacement_python = Path(sys.executable).parent / f".loop-skill-upgrade-{os.getpid()}"
        replacement_python.symlink_to(Path(sys.executable).name)

        try:
            second = self._run(str(replacement_python))
        finally:
            replacement_python.unlink(missing_ok=True)

        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(config.read_bytes(), before)
        receipts = sorted((self.codex_home / "install-receipts/codex-loop-prompt-architect").glob("*.json"))
        latest = json.loads(receipts[-1].read_text(encoding="utf-8"))
        self.assertEqual(latest["mcp_registration"]["command"], sys.executable)
        self.assertEqual(_manifest(SKILL), _manifest(self.codex_home / "skills/codex-loop-prompt-architect"))

    def test_managed_same_bridge_non_python_runtime_restores_config_and_skill(self) -> None:
        first = self._run()
        self.assertEqual(first.returncode, 0, first.stderr)
        config = self.codex_home / "config.toml"
        non_python = Path(self.tempdir.name) / "non-python-runtime"
        non_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        non_python.chmod(0o755)
        original_config = config.read_bytes().replace(
            f'command = {json.dumps(sys.executable)}'.encode("utf-8"),
            f'command = {json.dumps(str(non_python))}'.encode("utf-8"),
        )
        self.assertNotEqual(original_config, config.read_bytes())
        config.write_bytes(original_config)
        installed = self.codex_home / "skills/codex-loop-prompt-architect"
        marker = installed / "USER_OLD_SKILL.txt"
        marker.write_text("preserve\n", encoding="utf-8")

        second = self._run()

        self.assertNotEqual(second.returncode, 0)
        self.assertIn("MCP_PYTHON_RUNTIME_INVALID", second.stderr)
        self.assertEqual(config.read_bytes(), original_config)
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve\n")

    def test_managed_probe_spoof_without_verifier_receipt_restores_config_and_skill(self) -> None:
        first = self._run()
        self.assertEqual(first.returncode, 0, first.stderr)
        config = self.codex_home / "config.toml"
        spoof = Path(self.tempdir.name) / "probe-spoof-runtime"
        spoof.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"-c\" ]; then\n"
            "  printf '%s\\n' LOOPSKILL_PYTHON_RUNTIME_OK_V1\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        spoof.chmod(0o755)
        original_config = config.read_bytes().replace(
            f'command = {json.dumps(sys.executable)}'.encode("utf-8"),
            f'command = {json.dumps(str(spoof))}'.encode("utf-8"),
        )
        self.assertNotEqual(original_config, config.read_bytes())
        config.write_bytes(original_config)
        installed = self.codex_home / "skills/codex-loop-prompt-architect"
        marker = installed / "USER_OLD_SKILL.txt"
        marker.write_text("preserve\n", encoding="utf-8")

        second = self._run()

        self.assertNotEqual(second.returncode, 0)
        self.assertIn("MCP_MANAGED_RUNTIME_VERIFICATION_INVALID", second.stderr)
        self.assertEqual(config.read_bytes(), original_config)
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve\n")


if __name__ == "__main__":
    unittest.main()
