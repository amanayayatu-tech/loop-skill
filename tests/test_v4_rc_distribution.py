from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install.sh"
UNINSTALLER_PATH = ROOT / "scripts/uninstall_v4.py"
SPEC = importlib.util.spec_from_file_location("uninstall_v4", UNINSTALLER_PATH)
assert SPEC and SPEC.loader
uninstall_v4 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(uninstall_v4)


def tree_bytes(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def tree_state(root: Path) -> tuple[object, ...]:
    """Capture durable bytes, modes, types, and symlink text without following links."""
    if not os.path.lexists(root):
        return ((".", "absent", 0, b""),)
    values: list[tuple[str, str, int, bytes]] = []

    def record(path: Path) -> None:
        metadata = path.lstat()
        relative = "." if path == root else path.relative_to(root).as_posix()
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISLNK(metadata.st_mode):
            values.append((relative, "symlink", mode, os.readlink(path).encode()))
        elif stat.S_ISDIR(metadata.st_mode):
            values.append((relative, "directory", mode, b""))
        elif stat.S_ISREG(metadata.st_mode):
            values.append((relative, "file", mode, path.read_bytes()))
        else:
            values.append((relative, "special", mode, b""))

    record(root)
    if root.is_dir() and not root.is_symlink():
        for directory, names, files in os.walk(root, followlinks=False):
            parent = Path(directory)
            for name in sorted(names):
                record(parent / name)
            for name in sorted(files):
                record(parent / name)
    return tuple(sorted(values))


class V4RcDistributionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.tempdir.name).resolve()
        self.codex_home = self.temp_root / "isolated-codex-home"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @property
    def target(self) -> Path:
        return self.codex_home / "skills/loopskill4"

    @property
    def legacy_target(self) -> Path:
        return self.codex_home / "skills/codex-loop-prompt-architect"

    @property
    def management_uninstaller(self) -> Path:
        return self.codex_home / "install-receipts/loopskill4/uninstall_v4.py"

    def _install(
        self, *, extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(INSTALLER)],
            cwd=ROOT,
            env={
                **os.environ,
                "CODEX_HOME": str(self.codex_home),
                "PYTHON": sys.executable,
                "PYTHONDONTWRITEBYTECODE": "1",
                **(extra_env or {}),
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def _receipts(self) -> list[Path]:
        root = self.codex_home / "install-receipts/loopskill4"
        return sorted(root.glob("*.json")) if root.is_dir() else []

    def _latest_receipt(self) -> Path:
        values = self._receipts()
        self.assertTrue(values)
        return values[-1]

    def _seed_config_and_v3(self) -> tuple[bytes, dict[str, bytes]]:
        self.codex_home.mkdir(parents=True, exist_ok=True)
        config = (
            b'model = "keep"\n\n'
            b'[mcp_servers.unrelated]\ncommand = "leave-me-alone"\n'
        )
        (self.codex_home / "config.toml").write_bytes(config)
        self.legacy_target.mkdir(parents=True)
        (self.legacy_target / "OLD").write_bytes(b"independent v3 bytes\n")
        return config, tree_bytes(self.legacy_target)

    def test_isolated_install_is_v4_only_and_config_byte_identical(self) -> None:
        original_config, original_v3 = self._seed_config_and_v3()
        result = self._install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.target / "scripts/loopskill4").is_file())
        self.assertFalse((self.target / "scripts/uninstall_v4.py").exists())
        self.assertTrue(self.management_uninstaller.is_file())
        self.assertTrue((self.target / "protocol/v4/loopskill-v4.protocol.json").is_file())
        self.assertFalse((self.target / "scripts/loop_architect/v4_compat").exists())
        self.assertFalse((self.target / "scripts/configure_mcp.py").exists())
        self.assertEqual((self.codex_home / "config.toml").read_bytes(), original_config)
        self.assertEqual(tree_bytes(self.legacy_target), original_v3)

        receipt = json.loads(self._latest_receipt().read_text(encoding="utf-8"))
        self.assertEqual(receipt["artifact"], "loopskill4-install-receipt-v1")
        self.assertEqual(receipt["version"], "4.0.0")
        self.assertEqual(receipt["source_install_drift"], [])
        self.assertEqual(
            receipt["source_manifest_digest"], receipt["installed_manifest_digest"]
        )
        self.assertEqual(receipt["config_before_sha256"], receipt["config_after_sha256"])
        self.assertEqual(receipt["mcp_entries_added"], 0)
        self.assertEqual(receipt["mcp_processes_created"], 0)
        self.assertEqual(
            receipt["management_uninstaller_sha256"],
            hashlib.sha256(self.management_uninstaller.read_bytes()).hexdigest(),
        )
        self.assertFalse(receipt["restart_required_by_loopskill"])
        self.assertIn("no MCP entry was registered", result.stdout)
        self.assertIn("does not require a Codex App restart", result.stdout)

        smoke = subprocess.run(
            [str(self.target / "scripts/loopskill4"), "intake", "fix one typo"],
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(smoke.returncode, 0, smoke.stderr)
        self.assertIn("NEEDS_CLARIFICATION", smoke.stdout)
        doctor = subprocess.run(
            [str(self.target / "scripts/loopskill4"), "doctor", "--diagnostics"],
            env={
                **os.environ,
                "CODEX_HOME": str(self.codex_home),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        value = json.loads(doctor.stdout)
        self.assertEqual(value["status"], "READY")
        self.assertEqual(
            value["diagnostics"]["capabilities"]["install_receipt"], "AVAILABLE"
        )

    def test_second_install_is_an_exact_idempotent_noop(self) -> None:
        config, legacy = self._seed_config_and_v3()
        first = self._install()
        self.assertEqual(first.returncode, 0, first.stderr)
        before_target = tree_bytes(self.target)
        before_receipts = tree_bytes(self.codex_home / "install-receipts/loopskill4")
        second = self._install()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("already installed", second.stdout)
        self.assertEqual(tree_bytes(self.target), before_target)
        self.assertEqual(
            tree_bytes(self.codex_home / "install-receipts/loopskill4"),
            before_receipts,
        )
        self.assertEqual((self.codex_home / "config.toml").read_bytes(), config)
        self.assertEqual(tree_bytes(self.legacy_target), legacy)

    def test_management_lock_serializes_install_and_uninstall(self) -> None:
        config, legacy = self._seed_config_and_v3()
        environment = {
            **os.environ,
            "CODEX_HOME": str(self.codex_home),
            "PYTHON": sys.executable,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        installers = [
            subprocess.Popen(
                [str(INSTALLER)], cwd=ROOT, env=environment, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True
            )
            for _ in range(2)
        ]
        results = [process.communicate() + (process.returncode,) for process in installers]
        self.assertEqual([result[2] for result in results], [0, 0], results)
        self.assertEqual(len(self._receipts()), 1)
        manager = self.management_uninstaller
        install = subprocess.Popen(
            [str(INSTALLER)], cwd=ROOT, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True
        )
        uninstall = subprocess.Popen(
            [sys.executable, str(manager), "--codex-home", str(self.codex_home)],
            cwd=ROOT, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True
        )
        concurrent = [install.communicate() + (install.returncode,), uninstall.communicate() + (uninstall.returncode,)]
        self.assertEqual([result[2] for result in concurrent], [0, 0], concurrent)
        check = subprocess.run(
            [sys.executable, str(manager), "--codex-home", str(self.codex_home), "--check"],
            env=environment, capture_output=True, text=True
        )
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertFalse((self.codex_home / "install-receipts/loopskill4/active-transaction.json").exists())
        self.assertEqual(list((self.codex_home / "install-staging").glob("loopskill4.*")), [])
        self.assertEqual(list((self.codex_home / "uninstall-staging").glob("loopskill4-*")), [])
        self.assertEqual((self.codex_home / "config.toml").read_bytes(), config)
        self.assertEqual(tree_bytes(self.legacy_target), legacy)

    def test_install_sigkill_boundaries_recover_on_next_run(self) -> None:
        for boundary in ("after_target", "after_manager", "after_receipt", "after_pointer"):
            with self.subTest(boundary=boundary):
                self.codex_home = self.temp_root / f"crash-{boundary}"
                config, legacy = self._seed_config_and_v3()
                crashed = self._install(
                    extra_env={"LOOPSKILL4_TEST_INSTALL_FAULT": f"crash_{boundary}"}
                )
                self.assertNotEqual(crashed.returncode, 0)
                replay = self._install()
                self.assertEqual(replay.returncode, 0, replay.stderr)
                self.assertTrue(self.target.is_dir())
                self.assertEqual(len(self._receipts()), 1)
                self.assertFalse((self.codex_home / "install-receipts/loopskill4/active-transaction.json").exists())
                self.assertEqual(list((self.codex_home / "install-staging").glob("loopskill4.*")), [])
                self.assertEqual((self.codex_home / "config.toml").read_bytes(), config)
                self.assertEqual(tree_bytes(self.legacy_target), legacy)

    def test_uninstall_sigkill_after_rename_finishes_forward_gc_on_check(self) -> None:
        config, legacy = self._seed_config_and_v3()
        installed = self._install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        killer = "\n".join(
            (
                "import importlib.util, os, signal, sys",
                "from pathlib import Path",
                "spec = importlib.util.spec_from_file_location('uninstall_v4', sys.argv[1])",
                "assert spec and spec.loader",
                "module = importlib.util.module_from_spec(spec)",
                "spec.loader.exec_module(module)",
                "def fault(name):",
                "    if name == 'after_skill_withdrawn':",
                "        os.kill(os.getpid(), signal.SIGKILL)",
                "module.uninstall(Path(sys.argv[2]), fault=fault)",
            )
        )
        crashed = subprocess.run(
            [sys.executable, "-c", killer, str(UNINSTALLER_PATH), str(self.codex_home)],
            cwd=ROOT,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(crashed.returncode, -signal.SIGKILL, crashed.stderr)
        self.assertFalse(os.path.lexists(self.target))
        journal = (
            self.codex_home
            / "install-receipts/loopskill4/active-transaction.json"
        )
        self.assertTrue(journal.is_file())
        self.assertEqual(
            len(list((self.codex_home / "uninstall-staging").glob("loopskill4-*"))),
            1,
        )

        checked = subprocess.run(
            [
                sys.executable,
                str(self.management_uninstaller),
                "--codex-home",
                str(self.codex_home),
                "--check",
            ],
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(json.loads(checked.stdout)["status"], "ALREADY_UNINSTALLED")
        self.assertFalse(journal.exists())
        self.assertEqual(
            list((self.codex_home / "uninstall-staging").glob("loopskill4-*")), []
        )
        self.assertEqual((self.codex_home / "config.toml").read_bytes(), config)
        self.assertEqual(tree_bytes(self.legacy_target), legacy)

    def test_config_changes_after_install_do_not_block_noop_or_uninstall(self) -> None:
        self.codex_home.mkdir()
        config = self.codex_home / "config.toml"
        config.write_bytes(b'model = "before"\n')
        installed = self._install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        changed = b'model = "after"\n[mcp_servers.unrelated]\ncommand = "keep"\n'
        config.write_bytes(changed)
        replay = self._install()
        self.assertEqual(replay.returncode, 0, replay.stderr)
        removed = uninstall_v4.uninstall(self.codex_home)
        self.assertEqual(removed["status"], "UNINSTALLED")
        self.assertEqual(config.read_bytes(), changed)

    def test_conflicting_v4_target_fails_without_config_or_v3_mutation(self) -> None:
        config, legacy = self._seed_config_and_v3()
        self.target.mkdir(parents=True)
        (self.target / "FOREIGN").write_bytes(b"not managed by LoopSkill\n")
        target_before = tree_bytes(self.target)
        result = self._install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("V4_INSTALL_CONFLICT", result.stderr)
        self.assertEqual(tree_bytes(self.target), target_before)
        self.assertEqual((self.codex_home / "config.toml").read_bytes(), config)
        self.assertEqual(tree_bytes(self.legacy_target), legacy)
        self.assertEqual(self._receipts(), [])

    def test_install_fault_boundaries_restore_exact_pre_state(self) -> None:
        for boundary in (
            "after_target",
            "after_manager",
            "after_receipt",
        ):
            with self.subTest(boundary=boundary):
                self.codex_home = self.temp_root / f"fault-{boundary}"
                self._seed_config_and_v3()
                before = tree_state(self.codex_home)
                result = self._install(
                    extra_env={"LOOPSKILL4_TEST_INSTALL_FAULT": boundary}
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"V4_INSTALL_TEST_FAULT: {boundary}", result.stderr)
                self.assertEqual(tree_state(self.codex_home), before)
                self.assertFalse(self.target.exists())
                self.assertEqual(self._receipts(), [])

    def test_install_fault_after_pointer_keeps_exact_committed_state(self) -> None:
        self._seed_config_and_v3()
        result = self._install(
            extra_env={"LOOPSKILL4_TEST_INSTALL_FAULT": "after_pointer"}
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.target.is_dir())
        self.assertEqual(len(self._receipts()), 1)
        self.assertFalse(
            (self.codex_home / "install-receipts/loopskill4/active-transaction.json").exists()
        )
        replay = self._install()
        self.assertEqual(replay.returncode, 0, replay.stderr)
        self.assertIn("already installed", replay.stdout)

    def test_reinstall_pointer_failure_commits_one_new_install(self) -> None:
        self._seed_config_and_v3()
        installed = self._install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        removed = uninstall_v4.uninstall(self.codex_home)
        self.assertEqual(removed["status"], "UNINSTALLED")
        failed = self._install(
            extra_env={"LOOPSKILL4_TEST_INSTALL_FAULT": "after_pointer"}
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("V4_INSTALL_TEST_FAULT: after_pointer", failed.stderr)
        self.assertTrue(self.target.is_dir())
        self.assertEqual(len(self._receipts()), 2)
        self.assertFalse(
            (self.codex_home / "install-receipts/loopskill4/active-transaction.json").exists()
        )

    def test_install_rejects_symlink_owned_paths_without_external_write(self) -> None:
        cases = (
            "codex-home",
            "codex-home-ancestor",
            "codex-home-parent",
            "config",
            "skills",
            "target",
            "install-staging",
            "install-receipts",
            "receipt-root",
            "uninstall-staging",
            "management-uninstaller",
            "active-pointer",
        )
        for case in cases:
            with self.subTest(case=case):
                case_root = self.temp_root / f"symlink-{case}"
                outside = case_root / "outside"
                outside.mkdir(parents=True)
                (outside / "marker").write_bytes(b"outside must not change\n")
                self.codex_home = case_root / "codex-home"
                if case == "codex-home":
                    self.codex_home.symlink_to(outside, target_is_directory=True)
                elif case == "codex-home-ancestor":
                    (outside / "nested").mkdir()
                    ancestor = case_root / "ancestor-link"
                    ancestor.symlink_to(outside, target_is_directory=True)
                    self.codex_home = ancestor / "nested/codex-home"
                elif case == "codex-home-parent":
                    (outside / "codex-home").mkdir()
                    parent_link = case_root / "parent-link"
                    parent_link.symlink_to(outside, target_is_directory=True)
                    self.codex_home = parent_link / "codex-home"
                else:
                    self.codex_home.mkdir()
                    config = self.codex_home / "config.toml"
                    if case == "config":
                        config.symlink_to(outside / "marker")
                    else:
                        config.write_bytes(b"keep = true\n")
                    if case == "skills":
                        (self.codex_home / "skills").symlink_to(
                            outside, target_is_directory=True
                        )
                    elif case == "target":
                        (self.codex_home / "skills").mkdir()
                        self.target.symlink_to(outside, target_is_directory=True)
                    elif case == "install-staging":
                        (self.codex_home / "install-staging").symlink_to(
                            outside, target_is_directory=True
                        )
                    elif case == "install-receipts":
                        (self.codex_home / "install-receipts").symlink_to(
                            outside, target_is_directory=True
                        )
                    elif case == "receipt-root":
                        (self.codex_home / "install-receipts").mkdir()
                        (self.codex_home / "install-receipts/loopskill4").symlink_to(
                            outside, target_is_directory=True
                        )
                    elif case == "uninstall-staging":
                        (self.codex_home / "uninstall-staging").symlink_to(
                            outside, target_is_directory=True
                        )
                    elif case in ("management-uninstaller", "active-pointer"):
                        receipt_root = (
                            self.codex_home / "install-receipts/loopskill4"
                        )
                        receipt_root.mkdir(parents=True)
                        name = (
                            "uninstall_v4.py"
                            if case == "management-uninstaller"
                            else "active-receipt"
                        )
                        (receipt_root / name).symlink_to(outside / "marker")
                home_before = tree_state(self.codex_home)
                outside_before = tree_state(outside)
                result = self._install()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(tree_state(self.codex_home), home_before)
                self.assertEqual(tree_state(outside), outside_before)

    def test_install_rejects_unsafe_owned_directory_modes_without_mutation(self) -> None:
        cases = (
            "codex-home",
            "skills",
            "install-staging",
            "receipt-root",
            "uninstall-staging",
        )
        for case in cases:
            with self.subTest(case=case):
                self.codex_home = self.temp_root / f"unsafe-{case}"
                self.codex_home.mkdir()
                (self.codex_home / "config.toml").write_bytes(b"keep = true\n")
                if case == "codex-home":
                    unsafe = self.codex_home
                elif case == "skills":
                    unsafe = self.codex_home / "skills"
                    unsafe.mkdir()
                elif case == "install-staging":
                    unsafe = self.codex_home / "install-staging"
                    unsafe.mkdir()
                elif case == "receipt-root":
                    unsafe = self.codex_home / "install-receipts/loopskill4"
                    unsafe.mkdir(parents=True)
                else:
                    unsafe = self.codex_home / "uninstall-staging"
                    unsafe.mkdir()
                unsafe.chmod(0o777)
                before = tree_state(self.codex_home)
                result = self._install()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(tree_state(self.codex_home), before)

    def test_install_rejects_non_file_active_pointer_without_orphan_receipt(self) -> None:
        self.codex_home.mkdir()
        pointer = self.codex_home / "install-receipts/loopskill4/active-receipt"
        pointer.mkdir(parents=True)
        before = tree_state(self.codex_home)
        result = self._install()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(tree_state(self.codex_home), before)
        self.assertEqual(self._receipts(), [])

    def test_uninstall_removes_only_receipt_bound_v4_install(self) -> None:
        config, legacy = self._seed_config_and_v3()
        installed = self._install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        receipt = self._latest_receipt()
        active = self.codex_home / "install-receipts/loopskill4/active-receipt"
        self.assertTrue(active.is_file())
        self.assertIn(receipt.name, active.read_text(encoding="utf-8"))
        public_argv = [
            sys.executable,
            str(self.management_uninstaller),
            "--codex-home",
            str(self.codex_home),
        ]
        uninstalled = subprocess.run(
            public_argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        self.assertEqual(uninstalled.returncode, 0, uninstalled.stderr)
        result = json.loads(uninstalled.stdout)
        self.assertEqual(result["status"], "UNINSTALLED")
        self.assertFalse(self.target.exists())
        self.assertEqual((self.codex_home / "config.toml").read_bytes(), config)
        self.assertEqual(tree_bytes(self.legacy_target), legacy)
        self.assertEqual(result["loop_store_mutations"], 0)
        self.assertEqual(result["mcp_entries_removed"], 0)
        self.assertTrue(self.management_uninstaller.is_file())
        again = subprocess.run(
            public_argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(json.loads(again.stdout)["status"], "ALREADY_UNINSTALLED")

    def test_uninstall_machine_resolves_one_digest_bound_active_receipt(self) -> None:
        config, legacy = self._seed_config_and_v3()
        installed = self._install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        pointer = self.codex_home / "install-receipts/loopskill4/active-receipt"
        original = pointer.read_bytes()
        pointer.write_text('{"receipt":"missing.json","sha256":"' + "0" * 64 + '"}')
        with self.assertRaisesRegex(
            uninstall_v4.UninstallError, "V4_UNINSTALL_ACTIVE_RECEIPT_INVALID"
        ):
            uninstall_v4.uninstall(self.codex_home)
        repeated_install = self._install()
        self.assertNotEqual(repeated_install.returncode, 0)
        self.assertIn("V4_INSTALL_ACTIVE_RECEIPT_INVALID", repeated_install.stderr)
        self.assertTrue(self.target.is_dir())
        self.assertEqual((self.codex_home / "config.toml").read_bytes(), config)
        self.assertEqual(tree_bytes(self.legacy_target), legacy)
        pointer.write_bytes(original)

    def test_stale_receipt_cannot_uninstall_reinstalled_instance(self) -> None:
        installed = self._install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        stale = self._latest_receipt()
        self.assertEqual(uninstall_v4.uninstall(self.codex_home)["status"], "UNINSTALLED")
        reinstalled = self._install()
        self.assertEqual(reinstalled.returncode, 0, reinstalled.stderr)
        with self.assertRaisesRegex(
            uninstall_v4.UninstallError, "V4_UNINSTALL_RECEIPT_NOT_ACTIVE"
        ):
            uninstall_v4.uninstall(self.codex_home, stale)
        self.assertTrue(self.target.is_dir())

    def test_uninstall_rejects_unreceipted_empty_directory(self) -> None:
        installed = self._install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        foreign = self.target / "foreign-empty-directory"
        foreign.mkdir()
        with self.assertRaisesRegex(
            uninstall_v4.UninstallError, "V4_UNINSTALL_INSTALL_DRIFT"
        ):
            uninstall_v4.uninstall(self.codex_home)
        self.assertTrue(foreign.is_dir())

    def test_uninstall_rejects_management_entry_digest_drift(self) -> None:
        config, legacy = self._seed_config_and_v3()
        installed = self._install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        target_before = tree_state(self.target)
        self.management_uninstaller.write_bytes(
            self.management_uninstaller.read_bytes() + b"\n# drift\n"
        )
        result = subprocess.run(
            [
                sys.executable,
                str(self.management_uninstaller),
                "--codex-home",
                str(self.codex_home),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("V4_UNINSTALL_MANAGEMENT_ENTRY_INVALID", result.stderr)
        self.assertEqual(tree_state(self.target), target_before)
        self.assertEqual((self.codex_home / "config.toml").read_bytes(), config)
        self.assertEqual(tree_bytes(self.legacy_target), legacy)
        repeated_install = self._install()
        self.assertNotEqual(repeated_install.returncode, 0)
        self.assertIn("V4_INSTALL_MANAGEMENT_UNINSTALLER_DRIFT", repeated_install.stderr)

    def test_uninstall_rejects_symlink_owned_parent_without_external_write(self) -> None:
        cases = (
            ("skills", "V4_UNINSTALL_SKILLS_ROOT_INVALID"),
            ("install-staging", "V4_UNINSTALL_INSTALL_STAGING_INVALID"),
            ("receipt-root", "V4_UNINSTALL_RECEIPT_ROOT_INVALID"),
            ("uninstall-staging", "V4_UNINSTALL_STAGING_INVALID"),
        )
        for case, expected in cases:
            with self.subTest(case=case):
                self.codex_home = self.temp_root / f"uninstall-{case}"
                installed = self._install()
                self.assertEqual(installed.returncode, 0, installed.stderr)
                outside = self.temp_root / f"uninstall-{case}-outside"
                outside.mkdir()
                (outside / "marker").write_bytes(b"outside must not change\n")
                if case == "receipt-root":
                    path = self.codex_home / "install-receipts/loopskill4"
                else:
                    path = self.codex_home / case
                retained = path.with_name(path.name + "-retained")
                path.rename(retained)
                path.symlink_to(outside, target_is_directory=True)
                home_before = tree_state(self.codex_home)
                outside_before = tree_state(outside)
                with self.assertRaisesRegex(uninstall_v4.UninstallError, expected):
                    uninstall_v4.uninstall(self.codex_home)
                self.assertEqual(tree_state(self.codex_home), home_before)
                self.assertEqual(tree_state(outside), outside_before)

    def test_uninstall_rejects_symlink_config_without_external_write(self) -> None:
        _config, legacy = self._seed_config_and_v3()
        installed = self._install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        outside = self.temp_root / "outside-config"
        outside.write_bytes(b"outside config must not change\n")
        (self.codex_home / "config.toml").unlink()
        (self.codex_home / "config.toml").symlink_to(outside)
        home_before = tree_state(self.codex_home)
        outside_before = outside.read_bytes()
        with self.assertRaisesRegex(
            uninstall_v4.UninstallError, "V4_UNINSTALL_CONFIG_INVALID"
        ):
            uninstall_v4.uninstall(self.codex_home)
        self.assertEqual(tree_state(self.codex_home), home_before)
        self.assertEqual(outside.read_bytes(), outside_before)
        self.assertEqual(tree_bytes(self.legacy_target), legacy)

    def test_absent_config_stays_absent_across_install_and_uninstall(self) -> None:
        installed = self._install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        config = self.codex_home / "config.toml"
        self.assertFalse(config.exists())
        argv = [
            sys.executable,
            str(self.management_uninstaller),
            "--codex-home",
            str(self.codex_home),
        ]
        first = subprocess.run(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(first.stdout)["status"], "UNINSTALLED")
        self.assertFalse(config.exists())
        second = subprocess.run(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)["status"], "ALREADY_UNINSTALLED")
        self.assertFalse(config.exists())

    def test_uninstall_precommit_fault_restores_exact_installed_state(self) -> None:
        config, legacy = self._seed_config_and_v3()
        installed = self._install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        receipt = self._latest_receipt()
        target_before = tree_bytes(self.target)

        def fail(name: str) -> None:
            if name == "before_skill_withdrawn":
                raise RuntimeError(name)

        with self.assertRaisesRegex(RuntimeError, "before_skill_withdrawn"):
            uninstall_v4.uninstall(self.codex_home, receipt, fault=fail)
        self.assertEqual(tree_bytes(self.target), target_before)
        self.assertEqual((self.codex_home / "config.toml").read_bytes(), config)
        self.assertEqual(tree_bytes(self.legacy_target), legacy)

    def test_uninstall_postcommit_fault_has_exact_committed_state(self) -> None:
        for boundary in (
            "after_skill_withdrawn",
            "after_config_verified",
            "after_commit",
        ):
            with self.subTest(boundary=boundary):
                self.codex_home = self.temp_root / boundary
                config, legacy = self._seed_config_and_v3()
                installed = self._install()
                self.assertEqual(installed.returncode, 0, installed.stderr)
                receipt = self._latest_receipt()

                def fail(name: str) -> None:
                    if name == boundary:
                        raise RuntimeError(name)

                with self.assertRaisesRegex(RuntimeError, boundary):
                    uninstall_v4.uninstall(self.codex_home, receipt, fault=fail)
                self.assertFalse(self.target.exists())
                self.assertEqual(
                    (self.codex_home / "config.toml").read_bytes(), config
                )
                self.assertEqual(tree_bytes(self.legacy_target), legacy)
                self.assertEqual(
                    uninstall_v4.uninstall(self.codex_home, receipt)["status"],
                    "ALREADY_UNINSTALLED",
                )

    def test_uninstall_drift_and_outside_receipt_fail_before_mutation(self) -> None:
        config, legacy = self._seed_config_and_v3()
        installed = self._install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        receipt = self._latest_receipt()
        marker = self.target / "DRIFT"
        marker.write_bytes(b"drift")
        with self.assertRaisesRegex(
            uninstall_v4.UninstallError, "V4_UNINSTALL_INSTALL_DRIFT"
        ):
            uninstall_v4.uninstall(self.codex_home, receipt)
        self.assertEqual(marker.read_bytes(), b"drift")
        self.assertEqual((self.codex_home / "config.toml").read_bytes(), config)
        self.assertEqual(tree_bytes(self.legacy_target), legacy)

        outside = self.temp_root / "outside.json"
        outside.write_bytes(receipt.read_bytes())
        with self.assertRaisesRegex(
            uninstall_v4.UninstallError, "V4_UNINSTALL_RECEIPT_OUTSIDE_ROOT"
        ):
            uninstall_v4.uninstall(self.codex_home, outside)


if __name__ == "__main__":
    unittest.main()
