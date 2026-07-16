from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_whitespace_range.py"
SPEC = importlib.util.spec_from_file_location("check_whitespace_range", SCRIPT)
assert SPEC and SPEC.loader
whitespace_range = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(whitespace_range)


class WhitespaceRangeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo = Path(self.tempdir.name)
        self._git("init", "-q")
        self._git("config", "user.name", "Loop Test")
        self._git("config", "user.email", "loop@example.invalid")
        self.base = self._commit("artifact.txt", "base\n", "base")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()

    def _commit(self, relative: str, content: str, message: str) -> str:
        (self.repo / relative).write_text(content, encoding="utf-8")
        self._git("add", relative)
        self._git("commit", "-q", "-m", message)
        return self._git("rev-parse", "HEAD")

    def _run(self, event_name: str, event: dict[str, object], head: str | None = None) -> SimpleNamespace:
        event_path = self.repo / "event.json"
        event_path.write_text(json.dumps(event), encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()
        argv = [
            "--repo",
            str(self.repo),
            "--event-name",
            event_name,
            "--event-path",
            str(event_path),
            "--github-sha",
            head or self._git("rev-parse", "HEAD"),
        ]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            returncode = whitespace_range.main(argv)
        return SimpleNamespace(
            returncode=returncode,
            stdout=stdout.getvalue(),
            stderr=stderr.getvalue(),
        )

    def test_pull_request_checks_non_tip_commit_even_when_tip_is_clean(self) -> None:
        dirty = self._commit("artifact.txt", "dirty trailing space \n", "dirty")
        clean = self._commit("artifact.txt", "clean\n", "clean tip")
        result = self._run(
            "pull_request",
            {"pull_request": {"base": {"sha": self.base}, "head": {"sha": clean}}},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(dirty, result.stdout + result.stderr)
        self.assertIn("whitespace error", result.stderr)

    def test_force_push_uses_before_to_after_commit_set(self) -> None:
        old = self._commit("old.txt", "old\n", "old branch")
        self._git("checkout", "-q", "--detach", self.base)
        new = self._commit("new.txt", "new\n", "force replacement")
        result = self._run("push", {"before": old, "after": new, "ref": "refs/heads/main"}, new)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"{old}..{new}", result.stdout)
        self.assertIn("commit_count=1", result.stdout)

    def test_zero_before_fallback_is_deterministic_and_checks_full_history(self) -> None:
        dirty = self._commit("dirty.txt", "bad \n", "dirty history")
        head = self._commit("clean.txt", "clean\n", "clean head")
        result = self._run(
            "push",
            {"before": "0" * 40, "after": head, "ref": "refs/heads/new"},
            head,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fallback-full-history:zero-before:refs/heads/new", result.stdout)
        self.assertIn(dirty, result.stdout + result.stderr)

    def test_unavailable_push_baseline_falls_back_without_skipping(self) -> None:
        head = self._commit("clean.txt", "clean\n", "head")
        result = self._run(
            "push",
            {"before": "1" * 40, "after": head, "ref": "refs/heads/main"},
            head,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fallback-full-history:push-before-unavailable:refs/heads/main", result.stdout)
        self.assertRegex(result.stdout, r"commit_count=[1-9]")

    def test_tag_push_checks_reachable_history(self) -> None:
        head = self._commit("release.txt", "release\n", "release")
        result = self._run(
            "push",
            {"before": "0" * 40, "after": head, "ref": "refs/tags/v9.9.9"},
            head,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fallback-full-history:tag-push:refs/tags/v9.9.9", result.stdout)

    def test_manual_and_schedule_ranges_are_explicit(self) -> None:
        head = self._commit("manual.txt", "manual\n", "manual")
        manual = self._run("workflow_dispatch", {}, head)
        self.assertEqual(manual.returncode, 0, manual.stderr)
        self.assertIn("fallback-full-history:workflow-dispatch", manual.stdout)
        scheduled = self._run("schedule", {}, head)
        self.assertEqual(scheduled.returncode, 0, scheduled.stderr)
        self.assertIn(f"schedule:{head}:no-new-commits", scheduled.stdout)
        self.assertIn("commit_count=0", scheduled.stdout)

    def test_push_deletion_is_explicit_no_new_object_check(self) -> None:
        result = self._run(
            "push",
            {"before": self.base, "after": "0" * 40, "ref": "refs/tags/old"},
            self.base,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("push-deletion:refs/tags/old:no-new-objects", result.stdout)
        self.assertIn("commit_count=0", result.stdout)

    def test_malformed_ref_fails_closed(self) -> None:
        result = self._run(
            "push",
            {"before": self.base, "after": self.base, "ref": "refs/heads/main bad"},
            self.base,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("safe heads/tags ref", result.stderr)


if __name__ == "__main__":
    unittest.main()
