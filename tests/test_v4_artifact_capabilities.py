from __future__ import annotations

import os
import hashlib
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "codex-loop-prompt-architect" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from loop_architect.v4_alpha.vertical import fixture_authority  # noqa: E402
from loop_architect.v4_artifacts import (  # noqa: E402
    ArtifactCaptureError,
    capture_existing_git,
    capture_non_git_baseline,
    capture_non_git_delta,
    initialize_new_git,
    persist_capture_blobs,
)
from loop_architect.v4_artifacts.paths import (  # noqa: E402
    MAX_FILE_BYTES,
    normalize_relative_path,
    reject_casefold_collisions,
    secure_read_regular,
)
from loop_architect.v4_artifacts.verifier import verify_artifact  # noqa: E402
import loop_architect.v4_artifacts.verifier as artifact_verifier  # noqa: E402
from loop_architect.v4_persistence.sqlite_store import SQLiteStore  # noqa: E402


def git(root: Path, *arguments: str, input_bytes: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env={
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "LC_ALL": "C",
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
    )
    if result.returncode:
        raise AssertionError(result.stderr.decode(errors="replace"))
    return result.stdout


def initialize_existing_git(root: Path) -> str:
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "artifact-fixture@example.invalid")
    git(root, "config", "user.name", "Artifact Fixture")
    git(root, "add", "--all")
    git(root, "commit", "-q", "--no-gpg-sign", "-m", "baseline")
    return git(root, "rev-parse", "HEAD").decode().strip()


class V4ArtifactCapabilityTests(unittest.TestCase):
    def assert_artifact_error(self, code, callable_):
        with self.assertRaises(ArtifactCaptureError) as caught:
            callable_()
        self.assertEqual(caught.exception.code, code)

    def test_existing_git_binary_untracked_and_control_exclusion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "binary.bin").write_bytes(b"\x00before\xff")
            (root / "tracked.txt").write_text("before\n", encoding="utf-8")
            (root / ".codex-loop").mkdir()
            (root / ".codex-loop" / "control.txt").write_text(
                "control baseline\n", encoding="utf-8"
            )
            base = initialize_existing_git(root)
            (root / "binary.bin").write_bytes(b"\x00after\xfe\x01")
            (root / "tracked.txt").write_text("after\n", encoding="utf-8")
            (root / "untracked.dat").write_bytes(b"\x89PNG\r\n\x1a\n\x00fixture")
            (root / ".codex-loop" / "control.txt").write_text(
                "must stay excluded\n", encoding="utf-8"
            )
            capture = capture_existing_git(
                root,
                base_ref=base,
                allowed_untracked_paths=("untracked.dat",),
            )
            self.assertEqual(capture.profile, "existing_git")
            self.assertFalse(capture.empty)
            manifest = {entry["path"]: entry for entry in capture.manifest}
            self.assertEqual(set(manifest), {"binary.bin", "tracked.txt", "untracked.dat"})
            self.assertEqual(manifest["untracked.dat"]["status"], "A")
            self.assertNotIn(".codex-loop/control.txt", manifest)
            self.assertTrue(any(b"GIT binary patch" in blob for blob in capture.blobs.values()))

    def test_existing_git_empty_diff_is_explicit_and_stable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "stable.txt").write_text("stable\n", encoding="utf-8")
            base = initialize_existing_git(root)
            first = capture_existing_git(
                root, base_ref=base, allowed_untracked_paths=()
            )
            second = capture_existing_git(
                root, base_ref=base, allowed_untracked_paths=()
            )
            self.assertTrue(first.empty)
            self.assertEqual(first.manifest, ())
            self.assertEqual(first.artifact_digest, second.artifact_digest)
            self.assertEqual(set(first.blobs), {first.bundle_blob_digest})

    def test_existing_git_untracked_boundary_is_exact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "base.txt").write_text("base\n", encoding="utf-8")
            base = initialize_existing_git(root)
            (root / "new.txt").write_text("new\n", encoding="utf-8")
            self.assert_artifact_error(
                "ARTIFACT_IDENTITY_MISMATCH",
                lambda: capture_existing_git(
                    root, base_ref=base, allowed_untracked_paths=()
                ),
            )

    def test_non_git_manifest_delta_add_modify_delete_and_empty(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "modify.txt").write_text("before\n", encoding="utf-8")
            (root / "delete.txt").write_bytes(b"delete me")
            baseline = capture_non_git_baseline(root)
            empty = capture_non_git_delta(root, baseline)
            self.assertTrue(empty.empty)
            (root / "modify.txt").write_text("after\n", encoding="utf-8")
            (root / "delete.txt").unlink()
            (root / "added.bin").write_bytes(b"\x00added\xff")
            delta = capture_non_git_delta(root, baseline)
            self.assertFalse(delta.empty)
            self.assertEqual(
                [(entry["path"], entry["status"]) for entry in delta.manifest],
                [("added.bin", "A"), ("delete.txt", "D"), ("modify.txt", "M")],
            )
            deleted = next(entry for entry in delta.manifest if entry["status"] == "D")
            self.assertIsNone(deleted["after_digest"])
            self.assertEqual(len(delta.blobs), 3)
            self.assertIn(delta.bundle_blob_digest, delta.blobs)

    def test_new_git_full_vertical_requires_grants_and_captures_delta(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "keep.txt").write_text("before\n", encoding="utf-8")
            (root / "delete.txt").write_text("delete\n", encoding="utf-8")
            self.assert_artifact_error(
                "CAPABILITY_UNAVAILABLE",
                lambda: initialize_new_git(
                    root, allow_init=False, allow_branch_create=True
                ),
            )
            initialized = initialize_new_git(
                root,
                allow_init=True,
                allow_branch_create=True,
                branch="loopskill-v4",
            )
            self.assertEqual(initialized.branch, "loopskill-v4")
            self.assertEqual(len(initialized.base_commit), 40)
            (root / "keep.txt").write_text("after\n", encoding="utf-8")
            (root / "delete.txt").unlink()
            (root / "new.bin").write_bytes(b"\x00new-git\xff")
            capture = capture_existing_git(
                root,
                base_ref=initialized.base_commit,
                allowed_untracked_paths=("new.bin",),
            )
            self.assertEqual(
                [(entry["path"], entry["status"]) for entry in capture.manifest],
                [("delete.txt", "D"), ("keep.txt", "M"), ("new.bin", "A")],
            )

    def test_path_traversal_absolute_backslash_and_control_paths_reject(self):
        for path in (
            "../escape",
            "/absolute",
            "nested/../../escape",
            "nested\\escape",
            ".codex-loop/state.json",
            ".git/config",
        ):
            with self.subTest(path=path):
                self.assert_artifact_error(
                    "PATH_CONFINEMENT_VIOLATION",
                    lambda path=path: normalize_relative_path(path),
                )

    def test_symlink_casefold_special_file_and_size_reject(self):
        self.assert_artifact_error(
            "PATH_CONFINEMENT_VIOLATION",
            lambda: reject_casefold_collisions(("A.txt", "a.txt")),
        )
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside:
            root = Path(temporary)
            outside_path = Path(outside) / "secret.txt"
            outside_path.write_text("secret\n", encoding="utf-8")
            (root / "escape").symlink_to(outside_path)
            self.assert_artifact_error(
                "PATH_CONFINEMENT_VIOLATION",
                lambda: secure_read_regular(root, "escape"),
            )
            fifo = root / "pipe"
            os.mkfifo(fifo)
            self.assert_artifact_error(
                "PATH_CONFINEMENT_VIOLATION",
                lambda: capture_non_git_baseline(root),
            )
            fifo.unlink()
            large = root / "large.bin"
            with large.open("wb") as handle:
                handle.truncate(MAX_FILE_BYTES + 1)
            self.assert_artifact_error(
                "ARTIFACT_IDENTITY_MISMATCH",
                lambda: secure_read_regular(root, "large.bin"),
            )

    def test_open_read_race_rejects_stale_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "race.txt"
            target.write_text("before\n", encoding="utf-8")

            def mutate():
                target.write_text("after with different bytes\n", encoding="utf-8")

            self.assert_artifact_error(
                "ARTIFACT_STALE",
                lambda: secure_read_regular(root, "race.txt", after_open=mutate),
            )

    def test_capture_blobs_are_immutable_in_selected_store(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = root / "work"
            work.mkdir()
            (work / "file.txt").write_text("before\n", encoding="utf-8")
            baseline = capture_non_git_baseline(work)
            (work / "file.txt").write_text("after\n", encoding="utf-8")
            capture = capture_non_git_delta(work, baseline)
            with SQLiteStore(root / "store.sqlite3", fixture_authority()) as store:
                persisted = persist_capture_blobs(store, capture)
                self.assertEqual(persisted, tuple(sorted(capture.blobs)))
                for digest, expected in capture.blobs.items():
                    self.assertEqual(store.get_blob(digest), expected)
                self.assertEqual(persist_capture_blobs(store, capture), persisted)
                store.verify_integrity()

    def test_exact_argv_command_verifier_runs_independently(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = capture_non_git_baseline(root)
            capture = capture_non_git_delta(root, baseline)
            criterion = "command-json:" + json.dumps(
                {
                    "argv": [sys.executable, "-c", "print('verified')"],
                    "cwd": ".",
                    "env": [],
                    "expected_exit": 0,
                    "timeout_seconds": 10,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            with SQLiteStore(root / "store.sqlite3", fixture_authority()) as store:
                persist_capture_blobs(store, capture)
                result = verify_artifact(
                    store, capture, (criterion,), workspace_root=root
                )
            self.assertEqual(result.state, "VERIFIED")
            self.assertEqual(result.checked_criteria, (criterion,))

    def test_loopback_http_verifier_starts_checks_and_reaps_service(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "index.html").write_text("loopskill-http-ready\n", encoding="utf-8")
            baseline = capture_non_git_baseline(root)
            capture = capture_non_git_delta(root, baseline)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            criterion = "http-json:" + json.dumps(
                {
                    "cwd": ".",
                    "env": [],
                    "port": port,
                    "routes": [
                        {"contains": "loopskill-http-ready", "path": "/", "status": 200}
                    ],
                    "start_argv": [
                        sys.executable,
                        "-m",
                        "http.server",
                        str(port),
                        "--bind",
                        "127.0.0.1",
                    ],
                    "startup_timeout_seconds": 10,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            with SQLiteStore(root / "store.sqlite3", fixture_authority()) as store:
                persist_capture_blobs(store, capture)
                result = verify_artifact(
                    store, capture, (criterion,), workspace_root=root
                )
            self.assertEqual(result.state, "VERIFIED")
            with socket.socket() as closed:
                self.assertNotEqual(closed.connect_ex(("127.0.0.1", port)), 0)

    def test_verifier_declarations_reject_unsafe_shapes_and_accept_local_gates(self):
        self.assertEqual(
            artifact_verifier.verifier_capability("human-approval"), "human-gate"
        )
        self.assertEqual(
            artifact_verifier.verifier_capability(
                "time-after:2026-08-02T00:00:00Z"
            ),
            "time-gate",
        )
        self.assertEqual(
            artifact_verifier.verifier_capability("file-exists:result.txt"),
            "artifact-capture",
        )
        self.assertIsNone(artifact_verifier.verifier_capability(42))
        self.assertIsNone(artifact_verifier.verifier_capability("natural language"))
        invalid_documents = (
            "command-json:not-json",
            "command-json:{}",
            "command-json:" + json.dumps(
                {"argv": [], "cwd": ".", "env": [], "expected_exit": 0, "timeout_seconds": 1}
            ),
            "command-json:" + json.dumps(
                {"argv": [sys.executable], "cwd": 1, "env": [], "expected_exit": 0, "timeout_seconds": 1}
            ),
            "command-json:" + json.dumps(
                {"argv": [sys.executable], "cwd": ".", "env": ["SECRET"], "expected_exit": 0, "timeout_seconds": 1}
            ),
            "command-json:" + json.dumps(
                {"argv": [sys.executable], "cwd": ".", "env": [], "expected_exit": True, "timeout_seconds": 1}
            ),
            "http-json:" + json.dumps(
                {"cwd": ".", "env": [], "port": 80, "routes": [], "start_argv": [sys.executable], "startup_timeout_seconds": 1}
            ),
            "http-json:" + json.dumps(
                {"cwd": ".", "env": [], "port": 4317, "routes": [{"contains": "x", "path": "relative", "status": 200}], "start_argv": [sys.executable], "startup_timeout_seconds": 1}
            ),
            "time-after:2026-08-02T00:00:00",
        )
        for criterion in invalid_documents:
            with self.subTest(criterion=criterion), self.assertRaises(
                (ValueError, ArtifactCaptureError)
            ):
                artifact_verifier.verifier_capability(criterion)

    def test_verifier_failure_matrix_is_independently_evidenced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = capture_non_git_baseline(root)
            (root / "result.txt").write_text("actual\n", encoding="utf-8")
            capture = capture_non_git_delta(root, baseline)
            correct = hashlib.sha256(b"actual\n").hexdigest()
            command = "command-json:" + json.dumps(
                {
                    "argv": [sys.executable, "-c", "raise SystemExit(7)"],
                    "cwd": ".",
                    "env": [],
                    "expected_exit": 0,
                    "timeout_seconds": 10,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            criteria = (
                "artifact-changed",
                "no-file-change",
                "file-exists:result.txt",
                "file-exists:missing.txt",
                f"file-sha256:result.txt={correct}",
                "file-sha256:result.txt=" + "0" * 64,
                command,
                "unsupported-natural-language",
            )
            with SQLiteStore(root / "store.sqlite3", fixture_authority()) as store:
                persist_capture_blobs(store, capture)
                without_workspace = verify_artifact(store, capture, (command,))
                result = verify_artifact(
                    store, capture, criteria, workspace_root=root
                )
            self.assertEqual(without_workspace.state, "FAILED")
            self.assertEqual(result.state, "FAILED")
            self.assertEqual(len(result.checked_criteria), 7)

    def test_command_timeout_and_failed_http_route_are_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = capture_non_git_baseline(root)
            capture = capture_non_git_delta(root, baseline)
            timeout_criterion = "command-json:" + json.dumps(
                {
                    "argv": [sys.executable, "-c", "import time; time.sleep(5)"],
                    "cwd": ".",
                    "env": [],
                    "expected_exit": 0,
                    "timeout_seconds": 1,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            http_criterion = "http-json:" + json.dumps(
                {
                    "cwd": ".",
                    "env": [],
                    "port": port,
                    "routes": [{"contains": "never", "path": "/", "status": 200}],
                    "start_argv": [sys.executable, "-c", "raise SystemExit(0)"],
                    "startup_timeout_seconds": 1,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            with SQLiteStore(root / "store.sqlite3", fixture_authority()) as store:
                persist_capture_blobs(store, capture)
                timed_out = verify_artifact(
                    store, capture, (timeout_criterion,), workspace_root=root
                )
                http_failed = verify_artifact(
                    store, capture, (http_criterion,), workspace_root=root
                )
            self.assertEqual(timed_out.state, "FAILED")
            self.assertEqual(http_failed.state, "FAILED")


if __name__ == "__main__":
    unittest.main()
