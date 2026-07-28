from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_release_identity.py"
SPEC = importlib.util.spec_from_file_location("check_release_identity", SCRIPT)
assert SPEC and SPEC.loader
identity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(identity)


class V4ReleaseIdentityTests(unittest.TestCase):
    def _repo(self, root: Path) -> tuple[str, str]:
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "fixture@example.invalid"],
            cwd=root,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Fixture"], cwd=root, check=True
        )
        (root / "VERSION").write_text("4.0.0\n", encoding="utf-8")
        (root / "CHANGELOG.md").write_text(
            "## [4.0.0]\nhttps://github.com/amanayayatu-tech/loop-skill/releases/tag/v4.0.0\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "release"], cwd=root, check=True)
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip()
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/main", commit],
            cwd=root,
            check=True,
        )
        return commit, "refs/remotes/origin/main"

    def test_annotated_tag_must_equal_exact_main_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            commit, main_ref = self._repo(repo)
            subprocess.run(
                ["git", "tag", "-a", "v4.0.0", "-m", "LoopSkill 4.0.0"],
                cwd=repo,
                check=True,
            )
            result = identity.check_release_identity(
                repo, commit, "v4.0.0", main_ref
            )
            self.assertEqual(result["commit"], commit)
            self.assertEqual(result["main_commit"], commit)

    def test_lightweight_tag_and_nonexact_main_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            commit, main_ref = self._repo(repo)
            subprocess.run(["git", "tag", "v4.0.0"], cwd=repo, check=True)
            with self.assertRaisesRegex(
                identity.ReleaseIdentityError, "RELEASE_TAG_NOT_ANNOTATED"
            ):
                identity.check_release_identity(repo, commit, "v4.0.0", main_ref)
            subprocess.run(["git", "tag", "-d", "v4.0.0"], cwd=repo, check=True)
            subprocess.run(
                ["git", "tag", "-a", "v4.0.0", "-m", "LoopSkill 4.0.0"],
                cwd=repo,
                check=True,
            )
            (repo / "later").write_text("later\n", encoding="utf-8")
            subprocess.run(["git", "add", "later"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "later"], cwd=repo, check=True)
            later = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            subprocess.run(
                ["git", "update-ref", main_ref, later], cwd=repo, check=True
            )
            with self.assertRaisesRegex(
                identity.ReleaseIdentityError, "RELEASE_COMMIT_NOT_EXACT_MAIN"
            ):
                identity.check_release_identity(repo, commit, "v4.0.0", main_ref)


if __name__ == "__main__":
    unittest.main()
