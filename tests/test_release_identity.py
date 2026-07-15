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
release_identity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_identity)


class ReleaseIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo = Path(self.tempdir.name)
        self._git("init", "-q")
        self._git("config", "user.name", "Release Test")
        self._git("config", "user.email", "release@example.invalid")
        (self.repo / "VERSION").write_text("9.8.7\n", encoding="utf-8")
        (self.repo / "CHANGELOG.md").write_text(
            "## [9.8.7]\nhttps://github.com/example/repo/releases/tag/v9.8.7\n",
            encoding="utf-8",
        )
        self._git("add", "VERSION", "CHANGELOG.md")
        self._git("commit", "-q", "-m", "release")
        self.commit = self._git("rev-parse", "HEAD")
        self._git("tag", "-a", "v9.8.7", "-m", "v9.8.7")
        self._git("update-ref", "refs/remotes/origin/main", self.commit)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.repo, check=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout.strip()

    def test_exact_annotated_tag_on_main_passes(self) -> None:
        result = release_identity.check_release_identity(
            self.repo, self.commit, "v9.8.7", "refs/remotes/origin/main"
        )
        self.assertEqual(result["commit"], self.commit)

    def test_tag_commit_version_and_main_mismatches_fail_closed(self) -> None:
        (self.repo / "other").write_text("other\n", encoding="utf-8")
        self._git("add", "other")
        self._git("commit", "-q", "-m", "other")
        other = self._git("rev-parse", "HEAD")
        with self.assertRaisesRegex(release_identity.ReleaseIdentityError, "RELEASE_TAG_COMMIT_MISMATCH"):
            release_identity.check_release_identity(
                self.repo, other, "v9.8.7", "refs/remotes/origin/main"
            )
        self._git("update-ref", "refs/remotes/origin/main", other)
        with self.assertRaisesRegex(release_identity.ReleaseIdentityError, "RELEASE_VERSION_TAG_MISMATCH"):
            self._git("tag", "-a", "v9.8.8", other, "-m", "v9.8.8")
            release_identity.check_release_identity(
                self.repo, other, "v9.8.8", "refs/remotes/origin/main"
            )


if __name__ == "__main__":
    unittest.main()
