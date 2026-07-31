from __future__ import annotations

import importlib.util
import re
import shutil
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
        self.assertEqual(result["readme_asset_count"], 2)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        active_mode = (
            "candidate"
            if docs.README_CANDIDATE_STATUS_ZH in readme
            else "release"
        )
        inactive_mode = "release" if active_mode == "candidate" else "candidate"
        self.assertEqual(docs.validate(ROOT, mode=active_mode)["status"], "PASS")
        with self.assertRaisesRegex(docs.DocsError, "DOC_RELEASE_STATUS_PARITY_DRIFT"):
            docs.validate(ROOT, mode=inactive_mode)
        smoke = docs.smoke_public_commands(ROOT)
        self.assertEqual(smoke["status"], "PASS")
        self.assertEqual(smoke["command_count"], 5)
        self.assertEqual(smoke["external_effect_count"], 0)

    def test_section_command_link_and_stale_wording_drift_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                "README.md",
                "README.en.md",
                "CHANGELOG.md",
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
                "docs/v4/release-notes-v4.1.md",
                "docs/readme-assets/durable-handoff.png",
                "docs/readme-assets/evidence-before-closure.png",
                "docs/RELEASING.md",
                "docs/adr/0011-loopskill-4-compatible-kernel-refactor.md",
                "docs/adr/0013-content-addressed-plan-capacity.md",
                "docs/v4/compatibility-matrix-v4.1.md",
                "protocol/v4/README.md",
                "examples/v4-standard-input.json",
                "codex-loop-prompt-architect/scripts/loop_architect/v4_entry/canary.py",
                "scripts/validate_v4_rc.py",
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

    def test_release_mode_uses_durable_status_without_premature_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(
                ROOT,
                root,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(".git", "__pycache__"),
            )
            candidate_replacements = (
                (docs.QUICKSTART_RELEASE_STATUS_ZH, docs.QUICKSTART_CANDIDATE_STATUS_ZH),
                (docs.QUICKSTART_RELEASE_STATUS_EN, docs.QUICKSTART_CANDIDATE_STATUS_EN),
                (docs.README_RELEASE_STATUS_ZH, docs.README_CANDIDATE_STATUS_ZH),
                (docs.README_RELEASE_STATUS_EN, docs.README_CANDIDATE_STATUS_EN),
                (docs.SECURITY_RELEASE_STATUS, docs.SECURITY_CANDIDATE_STATUS),
            )
            for relative in (
                "README.md",
                "README.en.md",
                "docs/v4/quickstart.zh-CN.md",
                "docs/v4/quickstart.en.md",
                "SECURITY.md",
                "CHANGELOG.md",
            ):
                path = root / relative
                text = path.read_text(encoding="utf-8")
                for old, new in candidate_replacements:
                    text = text.replace(old, new)
                text = re.sub(
                    r"^## \[4\.1\.0\] - 20[0-9]{2}-[0-9]{2}-[0-9]{2}$",
                    "## [4.1.0] - Unreleased",
                    text,
                    count=1,
                    flags=re.MULTILINE,
                )
                path.write_text(text, encoding="utf-8")
            self.assertEqual(docs.validate(root)["status"], "PASS")
            self.assertEqual(docs.validate(root, mode="candidate")["status"], "PASS")
            with self.assertRaisesRegex(
                docs.DocsError, "DOC_RELEASE_STATUS_PARITY_DRIFT"
            ):
                docs.validate(root, mode="release")
            replacements = {
                docs.README_CANDIDATE_STATUS_ZH: docs.README_RELEASE_STATUS_ZH,
                docs.README_CANDIDATE_STATUS_EN: docs.README_RELEASE_STATUS_EN,
                docs.QUICKSTART_CANDIDATE_STATUS_ZH: docs.QUICKSTART_RELEASE_STATUS_ZH,
                docs.QUICKSTART_CANDIDATE_STATUS_EN: docs.QUICKSTART_RELEASE_STATUS_EN,
                docs.SECURITY_CANDIDATE_STATUS: docs.SECURITY_RELEASE_STATUS,
                "## [4.1.0] - Unreleased": "## [4.1.0] - 2026-07-30",
            }
            for relative in (
                "README.md",
                "README.en.md",
                "docs/v4/quickstart.zh-CN.md",
                "docs/v4/quickstart.en.md",
                "SECURITY.md",
                "CHANGELOG.md",
            ):
                path = root / relative
                text = path.read_text(encoding="utf-8")
                for old, new in replacements.items():
                    text = text.replace(old, new)
                path.write_text(text, encoding="utf-8")
            self.assertEqual(docs.validate(root, mode="release")["status"], "PASS")
            stale_zh = root / "README.md"
            stale_zh.write_text(
                stale_zh.read_text(encoding="utf-8") + "\n此源码树是稳定发行\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                docs.DocsError, "DOC_RELEASE_STATUS_PREMATURE_OR_AMBIGUOUS"
            ):
                docs.validate(root, mode="release")


if __name__ == "__main__":
    unittest.main()
