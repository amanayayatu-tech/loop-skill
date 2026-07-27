from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_v4_docs.py"
SPEC = importlib.util.spec_from_file_location("check_v4_docs", SCRIPT)
assert SPEC and SPEC.loader
docs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(docs)


class V4DocsTests(unittest.TestCase):
    def test_public_docs_pass_parity_commands_links_and_claims(self) -> None:
        result = docs.validate(ROOT)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["section_count"], 16)
        self.assertGreaterEqual(result["bash_command_blocks"], 6)

    def test_section_command_link_and_stale_wording_drift_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                "README.md",
                "README.en.md",
                "VERSION",
                "LICENSE",
                "SECURITY.md",
            ):
                source = ROOT / relative
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
            for relative in (
                "docs/v4/quickstart.zh-CN.md",
                "docs/v4/quickstart.en.md",
                "docs/v4/known-limitations.md",
                "docs/v4/architecture-map.md",
                "docs/v4/release-notes.md",
                "docs/RELEASING.md",
                "docs/adr/0011-loopskill-4-compatible-kernel-refactor.md",
                "protocol/v4/README.md",
            ):
                source = ROOT / relative
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
            readme = root / "README.md"
            readme.write_text(
                readme.read_text(encoding="utf-8") + "\nUse $codex-loop-prompt-architect\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(docs.DocsError, "DOC_STALE_V3_CURRENT_PRODUCT"):
                docs.validate(root)

    def test_release_mode_rejects_candidate_wording(self) -> None:
        with self.assertRaisesRegex(docs.DocsError, "DOC_RELEASE_STATUS_NOT_STABLE"):
            docs.validate(ROOT, release=True)


if __name__ == "__main__":
    unittest.main()
