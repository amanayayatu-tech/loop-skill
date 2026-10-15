from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "loopskill5"
QUICKSTARTS = ("docs/v5/quickstart.zh-CN.md", "docs/v5/quickstart.en.md")
EXPECTED_BLOBS = {
    "SKILL.md": "fe098768f85e2023a551aa700d1b4e5f4daa17f5",
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
        mode = path.lstat().st_mode
        digest.update(str(mode).encode("ascii") + b"\0")
        if stat.S_ISREG(mode):
            digest.update(path.read_bytes())
        elif stat.S_ISLNK(mode):
            digest.update(os.readlink(path).encode("utf-8"))
    return digest.hexdigest()


def run_documented_uninstall(
    doc: str, fixture_home: Path, source: Path | str | None, backups: Path | str | None,
    *, command_path: str = "/usr/bin:/bin:/usr/sbin:/sbin",
) -> subprocess.CompletedProcess[str]:
    blocks = re.findall(r"```bash\n(.*?)\n```", (ROOT / doc).read_text(), re.DOTALL)
    if len(blocks) != 1:
        raise AssertionError("Expected one documented uninstall Bash block")
    # Bind the historical command to the fixture without changing HOME or CODEX_HOME.
    script = blocks[0].replace(
        'loopskill5_home="${CODEX_HOME:-$HOME/.codex}"', 'loopskill5_home="$1"'
    )
    if "$HOME" in script or "$CODEX_HOME" in script:
        raise AssertionError("Uninstall fixture must not access the real Codex home")
    environment = {"PATH": command_path}
    if source is not None:
        environment["LOOPSKILL5_INSTALL_DIR"] = str(source)
    if backups is not None:
        environment["LOOPSKILL5_BACKUP_ROOT"] = str(backups)
    return subprocess.run(
        ["/bin/bash", "-c", script, "loopskill5-uninstall-fixture", str(fixture_home)],
        cwd=fixture_home,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )


class LoopSkill5DistributionTest(unittest.TestCase):
    def test_documented_uninstall_rejects_root_installation_parent(self) -> None:
        for doc in QUICKSTARTS:
            with self.subTest(doc=doc), tempfile.TemporaryDirectory() as directory:
                script = re.findall(
                    r"```bash\n(.*?)\n```", (ROOT / doc).read_text(), re.DOTALL
                )[0]
                gate = next(line for line in script.splitlines() if line.startswith(
                    'case "$loopskill5_backup_root/" in '
                ))
                result = subprocess.run(
                    ["/bin/bash", "-c", gate],
                    env={"loopskill5_skills_root": "/", "loopskill5_backup_root": directory},
                    capture_output=True, text=True, timeout=10,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_documented_uninstall_rejects_each_find_failure_without_changes(self) -> None:
        for doc in QUICKSTARTS:
            for failed_arguments in ("-type:f", "-type:d", "!:-type"):
                with self.subTest(doc=doc, failed_arguments=failed_arguments), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    home = root / "home"
                    source = home / "skills/loopskill5"
                    shutil.copytree(SKILL_ROOT, source)
                    commands = root / "bin"
                    commands.mkdir()
                    fake_find = commands / "find"
                    fake_find.write_text(
                        '#!/bin/sh\n/usr/bin/find "$@" || exit "$?"\n'
                        f'case "$2:$3" in "{failed_arguments}") exit 1 ;; esac\n'
                    )
                    fake_find.chmod(0o700)
                    before = tree_digest(root)

                    result = run_documented_uninstall(
                        doc, home, source, root / "backups",
                        command_path=f"{commands}:/usr/bin:/bin:/usr/sbin:/sbin",
                    )

                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(tree_digest(root), before)

    def test_documented_uninstall_preserves_newline_paths(self) -> None:
        for doc in QUICKSTARTS:
            for case in ("install-parent", "backup-parent", "backup-parent-alias"):
                with self.subTest(doc=doc, case=case), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    home = root / "home"
                    source = home / ("skills\n/loopskill5" if case == "install-parent" else "skills/loopskill5")
                    shutil.copytree(SKILL_ROOT, source)
                    expected = tree_digest(source)
                    backup_parent = root / "backup-parent\n"
                    backup_parent.mkdir()
                    wrong_parent = root / "backup-parent"
                    wrong_parent.mkdir()
                    (wrong_parent / "PRESERVE.txt").write_text("leave this sibling alone\n")
                    control_before = tree_digest(wrong_parent)
                    backups = backup_parent / "saved"
                    if case == "backup-parent-alias":
                        alias = root / "backup-alias"
                        alias.symlink_to(backup_parent, target_is_directory=True)
                        backups = alias / "saved"

                    result = run_documented_uninstall(doc, home, source, backups)

                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertFalse(source.exists())
                    self.assertTrue((backup_parent / "saved").is_dir())
                    moved = list((backup_parent / "saved").iterdir())
                    self.assertEqual(len(moved), 1)
                    self.assertEqual(tree_digest(moved[0]), expected)
                    self.assertEqual(tree_digest(wrong_parent), control_before)

    def test_isolated_install_refuses_overwrite_and_uninstalls_recoverably(self) -> None:
        for doc in QUICKSTARTS:
            for installation in ("default", "custom"):
                with self.subTest(doc=doc, installation=installation), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    home = root / "global"
                    default = home / "skills/loopskill5"
                    shutil.copytree(SKILL_ROOT, default)
                    source = default
                    if installation == "custom":
                        source = root / "custom/skills/loopskill5"
                        shutil.copytree(SKILL_ROOT, source)
                    control = home / "skills/loopskill4"
                    control.mkdir()
                    (control / "PRESERVE.txt").write_text("leave this installation alone\n")
                    control_before = tree_digest(control)
                    default_before = tree_digest(default)
                    expected = tree_digest(source)
                    self.assertEqual(inventory(source), EXPECTED_BLOBS)
                    with self.assertRaises(FileExistsError):
                        shutil.copytree(SKILL_ROOT, source)
                    self.assertEqual(tree_digest(source), expected)
                    backups = home / "uninstalled-skills"

                    result = run_documented_uninstall(doc, home, source, backups)

                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertFalse(source.exists())
                    moved = list(backups.iterdir())
                    self.assertEqual(len(moved), 1)
                    self.assertEqual(tree_digest(moved[0]), expected)
                    self.assertEqual(stat.S_IMODE(backups.stat().st_mode), 0o700)
                    self.assertEqual(tree_digest(control), control_before)
                    if installation == "custom":
                        self.assertEqual(tree_digest(default), default_before)

    def test_documented_uninstall_rejects_extra_entries_without_changes(self) -> None:
        for doc in QUICKSTARTS:
            for entry in ("fifo", "file", "symlink"):
                with self.subTest(doc=doc, entry=entry), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    home = root / "home"
                    source = home / "skills/loopskill5"
                    shutil.copytree(SKILL_ROOT, source)
                    extra = source / "extra"
                    if entry == "fifo":
                        os.mkfifo(extra)
                    elif entry == "file":
                        extra.write_text("preserve unexpected material\n")
                    else:
                        extra.symlink_to("SKILL.md")
                    before = tree_digest(root)

                    result = run_documented_uninstall(doc, home, source, root / "backups")

                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(tree_digest(root), before)

    def test_documented_uninstall_rejects_invalid_paths_without_changes(self) -> None:
        cases = (
            "missing-install", "missing-backup", "relative-install", "relative-backup",
            "backup-in-skill", "backup-in-skills", "backup-in-skills-via-alias",
            "backup-in-newline-skills-via-alias",
        )
        for doc in QUICKSTARTS:
            for case in cases:
                with self.subTest(doc=doc, case=case), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    home = root / "home"
                    source = home / "skills/loopskill5"
                    shutil.copytree(SKILL_ROOT, source)
                    selected_source: Path | str | None = source
                    backups: Path | str | None = home / "uninstalled-skills"
                    if case == "missing-install":
                        selected_source = None
                    elif case == "missing-backup":
                        backups = None
                    elif case == "relative-install":
                        selected_source = "skills/loopskill5"
                    elif case == "relative-backup":
                        backups = "uninstalled-skills"
                    elif case == "backup-in-skill":
                        backups = source / "backups"
                    elif case == "backup-in-skills":
                        backups = source.parent / "backups"
                    elif case == "backup-in-skills-via-alias":
                        alias = root / "skills-alias"
                        alias.symlink_to(source.parent, target_is_directory=True)
                        backups = alias / "backups"
                    else:
                        source.rename(home / "loopskill5")
                        source = home / "skills\n/loopskill5"
                        source.parent.mkdir()
                        (home / "loopskill5").rename(source)
                        alias = root / "skills-alias"
                        alias.symlink_to(source.parent, target_is_directory=True)
                        selected_source = alias / "loopskill5"
                        staging = source.parent / "staging"
                        staging.mkdir()
                        backups = staging / "backups"
                    before = tree_digest(root)

                    result = run_documented_uninstall(doc, home, selected_source, backups)

                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(tree_digest(root), before)

    def test_public_payload_and_v5_docs_are_exact(self) -> None:
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8"), "4.2.0\n")
        for relative, expected in PRESERVED_V4_BLOBS.items():
            self.assertEqual(blob_id((ROOT / relative).read_bytes()), expected)
        self.assertFalse(any(path.is_symlink() for path in SKILL_ROOT.rglob("*")))
        self.assertEqual(inventory(SKILL_ROOT), EXPECTED_BLOBS)

        readme_zh = (ROOT / "README.md").read_text(encoding="utf-8")
        readme_en = (ROOT / "README.en.md").read_text(encoding="utf-8")
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
        for text in (readme_zh, readme_en, quickstart_zh, quickstart_en):
            self.assertIn(installer_url, text)
        for text in (readme_zh, readme_en):
            self.assertEqual(text.splitlines()[0], "# LoopSkill 5")
            for literal in (
                "$skill-installer",
                "$loopskill5",
                "Launch Contract",
                "START",
                "scripts/install.sh",
                "agents/openai.yaml",
            ):
                self.assertIn(literal, text)
            for target in (
                "docs/v5/quickstart.zh-CN.md",
                "docs/v5/quickstart.en.md",
                "docs/v5/release-notes-v5.0.0.md",
                "loopskill5/SKILL.md",
                "SECURITY.md",
                "LICENSE",
            ):
                self.assertIn(f"]({target})", text)
            for stale in (
                "<!-- parity:",
                "$LOOPSKILL4",
                "v4 Release CI",
                "LoopSkill 4",
                "docs/v4/",
                "v3.3.8",
                "git clone --branch v4.2.0",
                "EAGER_V4_0",
                "CONTENT_ADDRESSED_V1",
                "USER_UNSUPPORTED_LEGACY_VERSION",
                "scripts/generate_v4_protocol.py --check",
                "docs/readme-assets/",
                "bash scripts/install.sh",
            ):
                self.assertNotIn(stale, text)
        self.assertIn(
            "不要运行仓库根目录的 `scripts/install.sh`；它不是 LoopSkill 5 安装器。",
            readme_zh,
        )
        self.assertIn(
            "只有新的价值判断或授权扩张",
            readme_zh,
        )
        self.assertIn(
            "才会再次向你询问决策",
            readme_zh,
        )
        self.assertIn(
            "Do not run the repository-root `scripts/install.sh`; "
            "it is not the LoopSkill 5 installer.",
            readme_en,
        )
        self.assertIn(
            "It asks you for a decision only when a new value judgment "
            "or authority expansion is required",
            readme_en,
        )
        self.assertIn("](README.en.md)", readme_zh)
        self.assertIn("](README.md)", readme_en)
        self.assertIn("目标已存在时，系统 installer 会拒绝覆盖", quickstart_zh)
        self.assertIn("installer refuses to overwrite an existing destination", quickstart_en)
        self.assertIn("annotated `v5.0.0`", releasing)
        self.assertIn("run for at least 60 minutes", releasing)
        self.assertIn("at least two Host-native same-thread reentries", releasing)
        self.assertIn("Host-native bounded or automatically expiring heartbeat", releasing)
        self.assertIn("covers the second eligible reentry, final business readback, and measured scheduling jitter", releasing)
        self.assertIn("persisted `next_run_at=NULL`", releasing)
        self.assertIn("Physical identity deletion is best-effort housekeeping", releasing)
        self.assertIn("Keep Host control calls serialized", releasing)
        self.assertIn("Multiday endurance remains post-release validation", releasing)
        self.assertIn("root `VERSION=4.2.0`", release_notes)
        for text in (readme_zh, readme_en, quickstart_zh, quickstart_en):
            self.assertNotIn("rm -rf", text)
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

if __name__ == "__main__":
    unittest.main()
