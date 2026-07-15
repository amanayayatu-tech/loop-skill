from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "codex-loop-prompt-architect" / "scripts"
SCHEMA = ROOT / "codex-loop-prompt-architect" / "references" / "install-manifest.schema.json"
sys.path.insert(0, str(SCRIPTS))


def _load(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


configure_mcp = _load("configure_mcp")
verify_installation = _load("verify_installation")


class InstallManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.source = self.root / "source"
        self.installed = self.root / "installed"
        for directory in (self.source, self.installed):
            (directory / "scripts").mkdir(parents=True)
            (directory / "SKILL.md").write_text("skill\n", encoding="utf-8")
            bridge = directory / "scripts/adaptive_state_mcp.py"
            bridge.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            bridge.chmod(0o755)
        self.python = self.root / "python"
        self.python.write_text("#!/bin/sh\n", encoding="utf-8")
        self.python.chmod(0o755)
        self.config = self.root / "config.toml"
        configure_mcp.register(
            self.config,
            self.python,
            self.installed / "scripts/adaptive_state_mcp.py",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _manifest(self):
        return verify_installation.build_manifest(
            source=self.source,
            installed=self.installed,
            config=self.config,
            python=self.python,
            script=self.installed / "scripts/adaptive_state_mcp.py",
            schema=SCHEMA,
            version="9.9.9",
            repo_commit="a" * 40,
            created_at="2026-07-15T15:00:00+08:00",
        )

    def test_manifest_binds_zero_drift_and_mcp_identity(self) -> None:
        manifest = self._manifest()
        self.assertEqual(manifest["source_manifest_digest"], manifest["installed_manifest_digest"])
        self.assertEqual(manifest["source_install_drift"], [])
        self.assertEqual(manifest["mcp_registration"]["server_name"], "codex-loop-state")
        output = self.root / "manifest.json"
        verify_installation._atomic_write(output, manifest)
        self.assertEqual(verify_installation.validate_manifest(output, SCHEMA), manifest)

    def test_drift_is_fail_closed(self) -> None:
        (self.installed / "SKILL.md").write_text("tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(verify_installation.InstallVerificationError, "SOURCE_INSTALL_DRIFT"):
            self._manifest()

    def test_manifest_digest_tamper_is_rejected(self) -> None:
        manifest = self._manifest()
        manifest["skill_version"] = "9.9.8"
        output = self.root / "manifest.json"
        output.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(verify_installation.InstallVerificationError, "INSTALL_MANIFEST_DIGEST_MISMATCH"):
            verify_installation.validate_manifest(output, SCHEMA)


if __name__ == "__main__":
    unittest.main()
