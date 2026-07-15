from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "codex-loop-prompt-architect" / "scripts" / "loop_prompt_scaffold.py"
SPEC = importlib.util.spec_from_file_location("loop_prompt_scaffold_runtime_python", SCRIPT)
assert SPEC and SPEC.loader
scaffold = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scaffold
SPEC.loader.exec_module(scaffold)

class RuntimePythonBindingTests(unittest.TestCase):
    def pack(self) -> str:
        input_path = ROOT / "examples" / "03-adaptive-passkey-input.json"
        args = scaffold.build_parser().parse_args(["--input", str(input_path)])
        return scaffold.render_controller_pack(scaffold.load_payload(args), "full")

    def test_pack_binds_runtime_to_installed_mcp_interpreter(self) -> None:
        pack = self.pack()
        for marker in (
            "`RUNTIME_PYTHON`",
            "`[mcp_servers.codex-loop-state]`",
            "never fall back to ambient `python3`",
            '[RUNTIME_PYTHON, RUNTIME_PATH, "--root"',
            '[RUNTIME_PYTHON, RUNTIME_PATH, "--payload-materialize"]',
            "bridge and `RUNTIME_PATH` to share the installed skill root",
            "STATE_RUNTIME_UNAVAILABLE",
        ):
            self.assertIn(marker, pack)
        self.assertNotIn('["python3", RUNTIME_PATH', pack)
        self.assertNotIn("['python3', RUNTIME_PATH", pack)

    def test_semantic_validator_rejects_ambient_python_regression(self) -> None:
        pack = self.pack()
        weakened = pack.replace(
            '[RUNTIME_PYTHON, RUNTIME_PATH, "--payload-materialize"]',
            '["python3", RUNTIME_PATH, "--payload-materialize"]',
            1,
        )
        errors = scaffold.validate_adaptive_pack_transport_contract(weakened)
        self.assertIn("adaptive_transport_contract:unsafe_ambient_python", errors)


if __name__ == "__main__":
    unittest.main()
