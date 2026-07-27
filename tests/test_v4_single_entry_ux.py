from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "codex-loop-prompt-architect" / "scripts"
ENTRY = SCRIPTS / "loopskill4"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from loop_architect.v4_alpha.kernel import AuthorityContext  # noqa: E402
from loop_architect.v4_alpha.protocol import InjectedCrash, LoopStartInput  # noqa: E402
from loop_architect.v4_alpha.vertical import (  # noqa: E402
    LOOP_REF,
    fixture_authority,
    vertical_commands,
)
from loop_architect.v4_entry import EntryError, diagnostics, start_loop, status  # noqa: E402
from loop_architect.v4_entry.service import STORE_FILENAME, _machine_bootstrap  # noqa: E402
from loop_architect.v4_persistence.sqlite_store import SQLiteStore  # noqa: E402
from loop_architect.v4_persistence.sqlite_store import PersistenceCorruption  # noqa: E402
from loop_architect.v4_persistence.sqlite_store import DURABLE_FAULT_BOUNDARIES  # noqa: E402


NOW = datetime(2026, 7, 27, 1, 0, 0, tzinfo=timezone.utc)


def fixed_tokens():
    values = iter(
        (
            "000000000000000000000001",
            "000000000000000000000002",
            "000000000000000000000003",
            "000000000000000000000004",
            "000000000000000000000005",
            "000000000000000000000006",
            "000000000000000000000007",
        )
    )
    return lambda: next(values)


def changed_authority_with_delivery(*, outcome, trust_class):
    base = fixture_authority()
    receipts = dict(base.receipts)
    receipts["receipt-delivery-0001"] = replace(
        receipts["receipt-delivery-0001"],
        outcome=outcome,
        trust_class=trust_class,
    )
    return AuthorityContext(
        actors=base.actors,
        grants=base.grants,
        receipts=receipts,
        trusted_actor_issuers=base.trusted_actor_issuers,
        trusted_grant_issuers=base.trusted_grant_issuers,
        trusted_receipt_issuers=base.trusted_receipt_issuers,
    )


class V4SingleEntryUXTests(unittest.TestCase):
    def run_entry(self, *arguments):
        return subprocess.run(
            [str(ENTRY), *map(str, arguments)],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    def test_one_literal_command_creates_and_starts_without_control_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            status_view = start_loop(
                LoopStartInput(goal="Ship a bounded public change"),
                root=temporary,
                clock=lambda: NOW,
                token_factory=fixed_tokens(),
            )
            self.assertEqual(status_view.goal, "Ship a bounded public change")
            self.assertEqual(status_view.progress, "Starting")
            self.assertEqual(status_view.result, "Pending")
            self.assertTrue((Path(temporary) / STORE_FILENAME).is_file())
            self.assertEqual(Path(temporary).stat().st_mode & 0o777, 0o700)

            reopened = status(root=temporary)
            self.assertEqual(reopened, status_view)
            with SQLiteStore(Path(temporary) / STORE_FILENAME) as store:
                descriptors = store.loop_descriptors()
                self.assertEqual(len(descriptors), 1)
                loop_ref = descriptors[0]["loop_ref"]
                self.assertEqual(store.snapshot(loop_ref)["execution"]["state"], "ACTIVE")
                self.assertEqual(store.commit_count, 1)
                self.assertEqual(len(store.authority.actors), 2)
                self.assertEqual(len(store.authority.grants), 2)
                self.assertEqual(len(store.ready_effect_attempts()), 1)
                self.assertEqual(store.ready_effect_attempts()[0].action, "create_task")
                self.assertNotIn("Ship a bounded public change", store.authority.actors)

    def test_one_input_file_action_and_one_main_command_action(self):
        for extension, content in (
            (".json", '{"goal":"Start from one JSON file"}'),
            (".txt", "Start from one text file\n"),
        ):
            with self.subTest(extension=extension):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    source = root / f"goal{extension}"
                    source.write_text(content, encoding="utf-8")
                    data = root / "data"
                    result = self.run_entry("start", source, "--root", data)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("Progress: Starting", result.stdout)
                    self.assertTrue((data / STORE_FILENAME).is_file())

        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_entry(
                "start",
                "Start from one command",
                "--root",
                temporary,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Goal: "Start from one command"', result.stdout)

    def test_default_path_has_zero_control_fields_and_no_policy_pack(self):
        help_result = self.run_entry("start", "--help")
        self.assertEqual(help_result.returncode, 0)
        for forbidden in (
            "thread-id",
            "task-id",
            "actor",
            "grant",
            "receipt",
            "version",
            "policy-pack",
            "heartbeat",
            "retry",
        ):
            self.assertNotIn(forbidden, help_result.stdout.lower())

        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_entry(
                "start",
                "threadId=from-model does not grant authority",
                "--root",
                temporary,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            view = diagnostics(root=temporary)
            self.assertNotIn("from-model", view["loop_ref"])

    def test_invalid_inputs_are_stable_non_leaking_and_leave_no_store(self):
        instances = (
            ("missing.json", None),
            ("bad.json", "{"),
            ("missing-goal.json", '{"other":"value"}'),
        )
        for name, content in instances:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    source = root / name
                    if content is not None:
                        source.write_text(content, encoding="utf-8")
                    data = root / "data"
                    result = self.run_entry("start", source, "--root", data)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("USER_INPUT_INVALID", result.stderr)
                    self.assertNotIn("loop-", result.stderr)
                    self.assertNotIn("receipt", result.stderr.lower())
                    self.assertNotIn("schema", result.stderr.lower())
                    self.assertFalse((data / STORE_FILENAME).exists())

        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_entry(
                "start",
                "goal",
                "--thread-id",
                "forged",
                "--root",
                temporary,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("USER_INPUT_INVALID", result.stderr)
            self.assertNotIn("forged", result.stderr)

    def test_default_status_hides_internal_identity_diagnostics_is_opt_in(self):
        with tempfile.TemporaryDirectory() as temporary:
            started = self.run_entry("start", "Visible goal", "--root", temporary)
            self.assertEqual(started.returncode, 0, started.stderr)
            for hidden in ("loop-", "receipt", "snapshot_digest", "schema"):
                self.assertNotIn(hidden, started.stdout.lower())

            ordinary = self.run_entry("status", "--root", temporary)
            self.assertEqual(ordinary.returncode, 0, ordinary.stderr)
            self.assertNotIn("loop-", ordinary.stdout)
            self.assertNotIn("snapshot_digest", ordinary.stdout)

            diagnostic = self.run_entry(
                "status", "--root", temporary, "--diagnostics"
            )
            self.assertEqual(diagnostic.returncode, 0, diagnostic.stderr)
            self.assertIn("Diagnostics:", diagnostic.stdout)
            self.assertIn('"loop_ref":"loop-', diagnostic.stdout)
            self.assertIn('"snapshot_digest":', diagnostic.stdout)

    def test_unknown_and_unverifiable_are_visible_without_resend_controls(self):
        for outcome, trust_class, word in (
            ("unknown", "cooperative", "unknown"),
            ("responded", "cooperative", "cannot be verified"),
        ):
            with self.subTest(outcome=outcome):
                with tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / STORE_FILENAME
                    authority = changed_authority_with_delivery(
                        outcome=outcome, trust_class=trust_class
                    )
                    with SQLiteStore(path, authority) as store:
                        for command in vertical_commands()[:5]:
                            store.apply(command)
                    view = status(root=temporary)
                    self.assertEqual(view.progress, "Needs attention")
                    self.assertIn(word, view.limitations[0].lower())
                    self.assertNotIn("resend", " ".join(view.next_actions).lower())

    def test_duplicate_start_is_safe_and_does_not_create_a_second_loop(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = self.run_entry("start", "First goal", "--root", temporary)
            self.assertEqual(first.returncode, 0, first.stderr)
            replay = self.run_entry("start", "First goal", "--root", temporary)
            self.assertEqual(replay.returncode, 0, replay.stderr)
            self.assertIn("Progress: Starting", replay.stdout)
            second = self.run_entry("start", "Second goal", "--root", temporary)
            self.assertEqual(second.returncode, 2)
            self.assertIn("USER_LOOP_EXISTS", second.stderr)
            with SQLiteStore(Path(temporary) / STORE_FILENAME) as store:
                self.assertEqual(store.commit_count, 1)
                self.assertEqual(len(store.loop_descriptors()), 1)
                self.assertEqual(store.loop_descriptors()[0]["goal"], "First goal")

    def test_symlinked_data_root_fails_before_store_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.mkdir()
            linked = root / "linked"
            linked.symlink_to(target, target_is_directory=True)
            with self.assertRaises(EntryError) as caught:
                start_loop(
                    LoopStartInput(goal="safe goal"),
                    root=linked,
                    clock=lambda: NOW,
                    token_factory=fixed_tokens(),
                )
            self.assertEqual(caught.exception.code, "USER_STORE_UNAVAILABLE")
            self.assertFalse((target / STORE_FILENAME).exists())

    def test_status_and_diagnostics_never_create_an_absent_store(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "absent"
            with self.assertRaises(EntryError):
                status(root=root)
            with self.assertRaises(EntryError):
                diagnostics(root=root)
            self.assertFalse(root.exists())

    def test_goal_and_authority_registry_corruption_fail_closed(self):
        for target in ("goal", "actor"):
            with self.subTest(target=target):
                with tempfile.TemporaryDirectory() as temporary:
                    start_loop(
                        LoopStartInput(goal="Integrity-bound goal"),
                        root=temporary,
                        clock=lambda: NOW,
                        token_factory=fixed_tokens(),
                    )
                    path = Path(temporary) / STORE_FILENAME
                    with SQLiteStore(path) as store:
                        if target == "goal":
                            store._connection.execute(
                                "UPDATE loop_descriptors SET goal_digest = 'tampered'"
                            )
                        else:
                            row = store._connection.execute(
                                "SELECT actor_ref, actor_json FROM authority_actors LIMIT 1"
                            ).fetchone()
                            raw = bytes(row["actor_json"]).replace(
                                row["actor_ref"].encode(), b"actor-forged-identity"
                            )
                            store._connection.execute(
                                "UPDATE authority_actors SET actor_json = ? WHERE actor_ref = ?",
                                (raw, row["actor_ref"]),
                            )
                        with self.assertRaises(PersistenceCorruption):
                            store.verify_integrity()

    def test_entry_dependency_graph_has_no_v3_or_uncontrolled_side_effect_modules(self):
        files = (
            SCRIPTS / "loopskill4",
            SCRIPTS / "loop_architect" / "v4_entry" / "service.py",
        )
        forbidden = {
            "git",
            "requests",
            "subprocess",
            "loop_architect.state_runtime",
            "loop_architect.v4_artifacts",
        }
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            } | {
                node.module or ""
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
            }
            self.assertFalse(
                any(
                    imported == denied or imported.startswith(denied + ".")
                    for imported in imports
                    for denied in forbidden
                ),
                path,
            )

    def test_startup_effect_all_durable_boundaries_are_atomic(self):
        _, authority, command = _machine_bootstrap(
            LoopStartInput(goal="Atomic startup effect"),
            now=NOW,
            token_factory=lambda: "cccccccccccccccccccccccc",
            receipt_trust_roots={},
        )
        for boundary in DURABLE_FAULT_BOUNDARIES:
            with self.subTest(boundary=boundary):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    path = root / "subject.sqlite3"
                    clean_path = root / "clean.sqlite3"
                    with SQLiteStore(path, authority) as subject:
                        exact_pre = subject.canonical_export()
                    with SQLiteStore(clean_path, authority) as clean:
                        clean.apply(command)
                        exact_post = clean.canonical_export()
                    with SQLiteStore(path, authority) as subject:
                        with self.assertRaises(InjectedCrash):
                            subject.apply(command, fault_at=boundary)
                    with SQLiteStore(path, authority) as recovered:
                        if boundary == "after_commit_before_response":
                            self.assertEqual(recovered.canonical_export(), exact_post)
                            self.assertTrue(recovered.apply(command).replayed)
                        else:
                            self.assertEqual(recovered.canonical_export(), exact_pre)
                            recovered.apply(command)
                        self.assertEqual(recovered.canonical_export(), exact_post)
                        self.assertEqual(len(recovered.ready_effect_attempts()), 1)
                        recovered.verify_integrity()


if __name__ == "__main__":
    unittest.main()
