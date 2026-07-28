from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "codex-loop-prompt-architect" / "scripts"
ENTRY = SCRIPTS / "loopskill4"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from loop_architect.v4_alpha.generated_protocol import (  # noqa: E402
    COMMAND_TYPES,
    ERROR_CODES,
    EVENT_TYPES,
)
from loop_architect.v4_entry import EntryError  # noqa: E402
from loop_architect.v4_entry.legacy_boundary import (  # noqa: E402
    LEGACY_ERROR_CODE,
    V3_RELEASE_URL,
    is_legacy_input,
)


def load_cli_module():
    loader = importlib.machinery.SourceFileLoader("loopskill4_legacy_test", str(ENTRY))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class V4LegacyBoundaryTests(unittest.TestCase):
    def test_public_protocol_has_one_legacy_error_and_no_import_surface(self) -> None:
        self.assertIn(LEGACY_ERROR_CODE, ERROR_CODES)
        self.assertNotIn("ImportV3Snapshot", COMMAND_TYPES)
        for path in (
            ROOT / "protocol/v4/loopskill-v4.protocol.json",
            ROOT / "protocol/v4/generated/api-summary.json",
            ROOT / "protocol/v4/generated/loopskill-v4.schema.json",
            SCRIPTS / "loop_architect/v4_alpha/generated_protocol.py",
            SCRIPTS / "loop_architect/v4_alpha/protocol.py",
        ):
            self.assertNotIn("V3Import", path.read_text(encoding="utf-8"), path)
        self.assertNotIn("V3SnapshotImported", EVENT_TYPES)
        self.assertFalse(any(code.startswith("MIGRATION_") for code in ERROR_CODES))
        self.assertNotIn("DUAL_WRITE_FORBIDDEN", ERROR_CODES)

    def test_stable_external_v3_release_reference(self) -> None:
        self.assertEqual(
            V3_RELEASE_URL,
            "https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8",
        )

    def test_v3_root_detection_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / ".codex-loop"
            legacy.mkdir()
            (legacy / "LOOP_STATE.md").write_text('{"schema_version":3}\n')
            before = tree_bytes(root)
            self.assertTrue(is_legacy_input(root))
            self.assertEqual(tree_bytes(root), before)

    def test_v3_pack_detection_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack = root / "controller.md"
            payload = b"# Codex Loop Controller Pack\n\nlegacy instructions\n"
            pack.write_bytes(payload)
            self.assertTrue(is_legacy_input(pack, payload))
            self.assertEqual(pack.read_bytes(), payload)

    def test_native_goal_is_not_classified_as_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            goal = root / "goal.json"
            payload = json.dumps({"goal": "Ship one bounded change"}).encode()
            goal.write_bytes(payload)
            self.assertFalse(is_legacy_input(goal, payload))

    def test_cli_rejects_legacy_pack_with_stable_error_and_zero_writes(self) -> None:
        cli = load_cli_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack = root / "controller.md"
            pack.write_text("# Codex Loop Controller Pack\n", encoding="utf-8")
            before = tree_bytes(root)
            with self.assertRaises(EntryError) as raised:
                cli.read_intake_input(str(pack))
            self.assertEqual(raised.exception.code, LEGACY_ERROR_CODE)
            self.assertIn(V3_RELEASE_URL, raised.exception.next_action)
            self.assertEqual(tree_bytes(root), before)

    def test_cli_rejects_legacy_root_without_creating_v4_store(self) -> None:
        cli = load_cli_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "legacy"
            (legacy / ".codex-loop").mkdir(parents=True)
            (legacy / ".codex-loop" / "LOOP_STATE.md").write_text("{}\n")
            before = tree_bytes(root)
            with self.assertRaises(EntryError) as raised:
                cli.read_intake_input(str(legacy))
            self.assertEqual(raised.exception.code, LEGACY_ERROR_CODE)
            self.assertEqual(tree_bytes(root), before)
            self.assertFalse((root / "loopskill-v4.sqlite3").exists())

    def test_all_legacy_state_classes_share_one_zero_write_rejection(self) -> None:
        cli = load_cli_module()
        legacy_states = (
            '{"status":"RUNNING","lease":{"owner":"legacy"}}\n',
            '{"status":"PAUSED","outbox":[{"state":"PENDING"}]}\n',
            '{"status":"SUCCEEDED","finalization":"ACKNOWLEDGED"}\n',
            '{"status":"READY","schema_version":1}\n',
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, content in enumerate(legacy_states):
                legacy = root / f"legacy-{index}"
                (legacy / ".codex-loop").mkdir(parents=True)
                state = legacy / ".codex-loop" / "LOOP_STATE.md"
                state.write_text(content, encoding="utf-8")
                before = tree_bytes(legacy)
                with self.assertRaises(EntryError) as raised:
                    cli.read_intake_input(str(legacy))
                self.assertEqual(raised.exception.code, LEGACY_ERROR_CODE)
                self.assertEqual(tree_bytes(legacy), before)
            self.assertFalse((root / "loopskill-v4.sqlite3").exists())

    def test_rejection_replay_and_changed_pack_remain_zero_write(self) -> None:
        cli = load_cli_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack = root / "controller.md"
            codes = []
            for suffix in ("first", "first", "changed"):
                pack.write_text(
                    f"# Codex Loop Controller Pack\n\n{suffix}\n", encoding="utf-8"
                )
                before = tree_bytes(root)
                with self.assertRaises(EntryError) as raised:
                    cli.read_intake_input(str(pack))
                codes.append(raised.exception.code)
                self.assertEqual(tree_bytes(root), before)
            self.assertEqual(codes, [LEGACY_ERROR_CODE] * 3)
            self.assertEqual(list(root.glob("*.sqlite3")), [])

    def test_production_tree_contains_no_v4_compat_package(self) -> None:
        package = SCRIPTS / "loop_architect"
        self.assertFalse((package / "v4_compat").exists())

    def test_shipped_runtime_has_no_retired_v3_literals(self) -> None:
        forbidden = (
            "ImportV3Snapshot",
            "V3SnapshotImported",
            "MIGRATION_",
            "[mcp_servers.",
            "adaptive_state_mcp",
            "configure_mcp",
            "codex-loop-state",
            "loop_architect.v4_compat",
            "State-Writer",
        )
        allow = {
            SCRIPTS / "validate_skill.py",
            SCRIPTS / "loop_architect/v4_entry/legacy_boundary.py",
        }
        for source in sorted(SCRIPTS.rglob("*.py")):
            if source in allow:
                continue
            text = source.read_text(encoding="utf-8")
            self.assertFalse(
                [literal for literal in forbidden if literal in text], source
            )


if __name__ == "__main__":
    unittest.main()
