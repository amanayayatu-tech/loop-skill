from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "loopskill5"
EXPECTED_BLOBS = {
    "SKILL.md": "cc8fe9230f489992dd962a0eb958815bf899a8d3",
    "agents/openai.yaml": "6295d897c694e67785f25c04987ce2a5b1914d86",
}
PRESERVED_V4_BLOBS = {
    "VERSION": "6aba2b245a847cc30a9b9dc009fc9d2522fff998",
    "scripts/install.sh": "55b70774039d857ddb3f2e4f27303c75e027af55",
    ".github/workflows/v4-release.yml": "8c7f73cdae4504a6e289a498b4d97c57040b3cb0",
}


def blob_id(raw: bytes) -> str:
    return hashlib.sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()


def inventory(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): blob_id(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative + b"\0")
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


class LoopSkill5DistributionTest(unittest.TestCase):
    def test_public_payload_and_multi_product_docs_are_exact(self) -> None:
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8"), "4.2.0\n")
        for relative, expected in PRESERVED_V4_BLOBS.items():
            self.assertEqual(blob_id((ROOT / relative).read_bytes()), expected)
        self.assertFalse(any(path.is_symlink() for path in SKILL_ROOT.rglob("*")))
        self.assertEqual(inventory(SKILL_ROOT), EXPECTED_BLOBS)

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        quickstart_zh = (ROOT / "docs/v5/quickstart.zh-CN.md").read_text(
            encoding="utf-8"
        )
        quickstart_en = (ROOT / "docs/v5/quickstart.en.md").read_text(
            encoding="utf-8"
        )
        releasing = (ROOT / "docs/v5/RELEASING.md").read_text(encoding="utf-8")
        release_notes = (ROOT / "docs/v5/release-notes-v5.0.0.md").read_text(
            encoding="utf-8"
        )
        installer_url = (
            "https://github.com/amanayayatu-tech/loop-skill/"
            "tree/v5.0.0/loopskill5"
        )
        for text in (readme, quickstart_zh, quickstart_en):
            self.assertIn(installer_url, text)
        self.assertIn("目标已存在时，系统 installer 会拒绝覆盖", quickstart_zh)
        self.assertIn("installer refuses to overwrite an existing destination", quickstart_en)
        self.assertIn("annotated `v5.0.0`", releasing)
        self.assertIn("run for at least 60 minutes", releasing)
        self.assertIn("at least two Host-native same-thread reentries", releasing)
        self.assertIn("Multiday endurance remains post-release validation", releasing)
        self.assertIn("root `VERSION=4.2.0`", release_notes)
        self.assertNotIn("rm -rf", quickstart_zh)
        self.assertNotIn("rm -rf", quickstart_en)
        zh_bash = re.findall(r"```bash\n(.*?)\n```", quickstart_zh, re.DOTALL)
        en_bash = re.findall(r"```bash\n(.*?)\n```", quickstart_en, re.DOTALL)
        self.assertEqual(zh_bash, en_bash)
        self.assertEqual(len(zh_bash), 1)
        syntax = subprocess.run(
            ["bash", "-n"],
            input=zh_bash[0],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

        workflow = (ROOT / ".github/workflows/v5-release.yml").read_text(
            encoding="utf-8"
        )
        for literal in (
            "name: LoopSkill 5 Release CI",
            "name: v5 surface and privacy",
            "name: v5 distribution (ubuntu)",
            "name: v5 distribution (macOS)",
            "tests.test_v5_skill_surface",
            "tests.test_v5_privacy",
            "tests.test_v5_distribution",
            "permissions:\n  contents: read",
            "fetch-depth: 0",
            "persist-credentials: false",
            "tags: [v5.0.0]",
        ):
            self.assertIn(literal, workflow)
        tag_gate = """      - name: Require an annotated v5 release tag
        if: github.ref == 'refs/tags/v5.0.0'
        run: |
          test "$(git cat-file -t refs/tags/v5.0.0)" = tag
          test "$(git rev-parse 'refs/tags/v5.0.0^{commit}')" = "$TESTED_SHA"
          test "$(git rev-parse 'refs/remotes/origin/main^{commit}')" = "$TESTED_SHA"
"""
        self.assertIn(tag_gate, workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("git push", workflow)
        self.assertNotIn("gh release", workflow)

    def test_isolated_install_refuses_overwrite_and_uninstalls_recoverably(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private_root = Path(directory)
            skills = private_root / "skills"
            backups = private_root / "uninstalled-skills"
            v4 = skills / "loopskill4"
            v4.mkdir(parents=True)
            (v4 / "PRESERVE.txt").write_text("v4 remains independent\n", encoding="utf-8")
            v4_before = tree_digest(v4)

            destination = skills / "loopskill5"
            shutil.copytree(SKILL_ROOT, destination)
            self.assertEqual(inventory(destination), EXPECTED_BLOBS)

            before_refusal = tree_digest(destination)
            with self.assertRaises(FileExistsError):
                shutil.copytree(SKILL_ROOT, destination)
            self.assertEqual(tree_digest(destination), before_refusal)
            self.assertEqual(tree_digest(v4), v4_before)

            backups.mkdir(mode=0o700)
            backup = backups / "loopskill5-test-backup"
            destination.replace(backup)
            self.assertFalse(destination.exists())
            self.assertEqual(inventory(backup), EXPECTED_BLOBS)
            self.assertEqual(tree_digest(v4), v4_before)


if __name__ == "__main__":
    unittest.main()
