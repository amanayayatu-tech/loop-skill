from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "codex-loop-prompt-architect" / "scripts" / "configure_mcp.py"
SPEC = importlib.util.spec_from_file_location("configure_mcp", MODULE_PATH)
assert SPEC and SPEC.loader
configure_mcp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(configure_mcp)


class McpRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.config = self.root / "config.toml"
        self.python = self.root / "stable-python"
        self.script = self.root / "skills/codex-loop-prompt-architect/scripts/adaptive_state_mcp.py"
        self.python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.script.parent.mkdir(parents=True)
        self.script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        self.python.chmod(0o755)
        self.script.chmod(0o755)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_registers_exact_cli_observed_shape_and_readback(self) -> None:
        changed, identity = configure_mcp.register(self.config, self.python, self.script)
        self.assertTrue(changed)
        self.assertEqual(
            self.config.read_text(encoding="utf-8"),
            "[mcp_servers.codex-loop-state]\n"
            f'command = {json.dumps(str(self.python))}\n'
            f'args = [{json.dumps(str(self.script))}]\n',
        )
        self.assertTrue(identity["config_readback"])
        self.assertEqual(identity["installed_script_sha256"], hashlib.sha256(self.script.read_bytes()).hexdigest())
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)

    def test_existing_user_bytes_are_preserved_and_repeat_is_idempotent(self) -> None:
        original = b'model = "gpt-5"\n\n[mcp_servers.existing]\ncommand = "/usr/bin/existing"\nargs = []\n'
        self.config.write_bytes(original)
        self.config.chmod(0o640)
        first_changed, _ = configure_mcp.register(self.config, self.python, self.script)
        after_first = self.config.read_bytes()
        second_changed, _ = configure_mcp.register(self.config, self.python, self.script)
        self.assertTrue(first_changed)
        self.assertFalse(second_changed)
        self.assertTrue(after_first.startswith(original))
        self.assertEqual(self.config.read_bytes(), after_first)
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o640)

    def test_existing_mode_is_preserved_under_restrictive_umask(self) -> None:
        original = b'model = "gpt-5"\n'
        self.config.write_bytes(original)
        self.config.chmod(0o640)
        previous_umask = os.umask(0o077)
        try:
            changed, _ = configure_mcp.register(self.config, self.python, self.script)
        finally:
            os.umask(previous_umask)
        self.assertTrue(changed)
        self.assertTrue(self.config.read_bytes().startswith(original))
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o640)

    def test_conflicting_registration_is_zero_effect(self) -> None:
        original = b'[mcp_servers.codex-loop-state]\ncommand = "/other/python"\nargs = ["/other/server.py"]\n'
        self.config.write_bytes(original)
        with self.assertRaisesRegex(configure_mcp.RegistrationError, "MCP_REGISTRATION_IDENTITY_CONFLICT"):
            configure_mcp.register(self.config, self.python, self.script)
        self.assertEqual(self.config.read_bytes(), original)

    def test_registration_with_extra_execution_semantics_is_rejected(self) -> None:
        for field in ('enabled = false', 'cwd = "/tmp"', 'env = { TOKEN = "not-used" }'):
            with self.subTest(field=field):
                original = (
                    f'[mcp_servers.codex-loop-state]\n'
                    f'command = {json.dumps(str(self.python))}\n'
                    f'args = [{json.dumps(str(self.script))}]\n'
                    f'{field}\n'
                ).encode("utf-8")
                self.config.write_bytes(original)
                with self.assertRaisesRegex(configure_mcp.RegistrationError, "MCP_REGISTRATION_IDENTITY_CONFLICT"):
                    configure_mcp.register(self.config, self.python, self.script)
                self.assertEqual(self.config.read_bytes(), original)

    def test_invalid_toml_and_symlink_are_zero_effect(self) -> None:
        self.config.write_text("[broken\n", encoding="utf-8")
        before = self.config.read_bytes()
        with self.assertRaisesRegex(configure_mcp.RegistrationError, "MCP_CONFIG_INVALID"):
            configure_mcp.register(self.config, self.python, self.script)
        self.assertEqual(self.config.read_bytes(), before)
        self.config.unlink()
        target = self.root / "outside.toml"
        target.write_text("", encoding="utf-8")
        self.config.symlink_to(target)
        with self.assertRaisesRegex(configure_mcp.RegistrationError, "MCP_CONFIG_SYMLINK_FORBIDDEN"):
            configure_mcp.register(self.config, self.python, self.script)
        self.assertEqual(target.read_bytes(), b"")

    def test_changed_during_atomic_replace_is_rejected(self) -> None:
        self.config.write_text('model = "one"\n', encoding="utf-8")
        before = self.config.read_bytes()
        self.config.write_text('model = "two"\n', encoding="utf-8")
        with self.assertRaisesRegex(configure_mcp.RegistrationError, "MCP_CONFIG_CHANGED_DURING_INSTALL"):
            configure_mcp._atomic_replace(self.config, before, b"replacement", 0o600)
        self.assertEqual(self.config.read_text(encoding="utf-8"), 'model = "two"\n')


if __name__ == "__main__":
    unittest.main()
