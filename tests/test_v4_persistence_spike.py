from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "codex-loop-prompt-architect" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from loop_architect.v4_alpha.protocol import (  # noqa: E402
    InjectedCrash,
    ProtocolRejection,
    canonical_bytes,
    command_digest,
)
from loop_architect.v4_alpha.store import InMemoryStore  # noqa: E402
from loop_architect.v4_alpha.vertical import (  # noqa: E402
    EXPECTED_CANONICAL_SNAPSHOT,
    EXPECTED_EVENT_TYPES,
    EXPECTED_SNAPSHOT_DIGEST,
    LOOP_REF,
    fixture_authority,
    vertical_commands,
)
from loop_architect.v4_persistence.sqlite_store import (  # noqa: E402
    DURABLE_FAULT_BOUNDARIES,
    PersistenceBusy,
    PersistenceCorruption,
    PersistenceError,
    SQLiteStore,
)


class V4PersistenceSpikeTests(unittest.TestCase):
    def run_prefix(self, store, count):
        for command in vertical_commands()[:count]:
            store.apply(command)

    def assert_vertical_state(self, store):
        self.assertEqual(canonical_bytes(store.snapshot(LOOP_REF)), EXPECTED_CANONICAL_SNAPSHOT)
        self.assertEqual(
            tuple(event["type"] for event in store.events(LOOP_REF)),
            EXPECTED_EVENT_TYPES,
        )
        self.assertEqual(store.commit_count, 11)
        store.verify_integrity()

    def test_sqlite_matches_in_memory_semantic_oracle(self):
        authority = fixture_authority()
        memory = InMemoryStore(authority)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "loopskill-v4.sqlite3"
            with SQLiteStore(path, authority) as durable:
                for command in vertical_commands():
                    expected = memory.apply(command)
                    actual = durable.apply(command)
                    self.assertEqual(actual, expected)
                    self.assertEqual(
                        durable.snapshot(LOOP_REF), memory.snapshot(LOOP_REF)
                    )
                    self.assertEqual(durable.events(LOOP_REF), memory.events(LOOP_REF))
                self.assert_vertical_state(durable)
                export = durable.canonical_export()
                self.assertEqual(canonical_bytes(json.loads(export)), export)
                self.assertEqual(durable.apply(vertical_commands()[-1]).replayed, True)
                self.assertEqual(durable.commit_count, 11)
            with SQLiteStore(path, authority) as reopened:
                self.assert_vertical_state(reopened)
                self.assertEqual(reopened.canonical_export(), export)

    def test_all_99_operation_by_durable_boundary_crashes_are_atomic(self):
        commands = vertical_commands()
        for index, command in enumerate(commands):
            for boundary in DURABLE_FAULT_BOUNDARIES:
                with self.subTest(operation=command.operation_id, boundary=boundary):
                    with tempfile.TemporaryDirectory() as temporary:
                        root = Path(temporary)
                        path = root / "subject.sqlite3"
                        clean_path = root / "clean.sqlite3"
                        authority = fixture_authority()
                        with SQLiteStore(path, authority) as store:
                            self.run_prefix(store, index)
                            exact_pre = store.canonical_export()
                        with SQLiteStore(clean_path, authority) as clean:
                            self.run_prefix(clean, index)
                            expected_result = clean.apply(command)
                            exact_post = clean.canonical_export()

                        with SQLiteStore(path, authority) as store:
                            with self.assertRaises(InjectedCrash):
                                store.apply(command, fault_at=boundary)

                        with SQLiteStore(path, authority) as recovered:
                            if boundary == "after_commit_before_response":
                                self.assertEqual(recovered.canonical_export(), exact_post)
                                replay = recovered.apply(command)
                                self.assertTrue(replay.replayed)
                                self.assertEqual(
                                    replay.snapshot_digest,
                                    expected_result.snapshot_digest,
                                )
                                self.assertEqual(recovered.canonical_export(), exact_post)
                            else:
                                self.assertEqual(recovered.canonical_export(), exact_pre)
                                result = recovered.apply(command)
                                self.assertEqual(
                                    result.snapshot_digest,
                                    expected_result.snapshot_digest,
                                )
                                self.assertEqual(recovered.canonical_export(), exact_post)
                            recovered.verify_integrity()

    def test_attempt_snapshot_operation_events_and_outbox_commit_together(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "atomic.sqlite3"
            authority = fixture_authority()
            with SQLiteStore(path, authority) as store:
                self.run_prefix(store, 3)
                pre = store.canonical_export()
                with self.assertRaises(InjectedCrash):
                    store.apply(
                        vertical_commands()[3], fault_at="after_outbox_write"
                    )
                self.assertEqual(store.canonical_export(), pre)
                store.apply(vertical_commands()[3])
                exported = json.loads(store.canonical_export())
                self.assertEqual(len(exported["outbox"]), 1)
                self.assertEqual(exported["outbox"][0]["attempt_ref"], "attempt-0001")
                self.assertEqual(exported["outbox"][0]["attempt_state"], "COMMITTED")
                self.assertEqual(exported["loops"][0]["loop_revision"], 4)
                self.assertEqual(len(exported["operations"]), 4)
                self.assertEqual(len(exported["events"]), 6)

    def test_backup_restore_is_exact_and_source_remains_live(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "source.sqlite3"
            backup_path = root / "backup.sqlite3"
            authority = fixture_authority()
            with SQLiteStore(source_path, authority) as source:
                self.run_prefix(source, 6)
                blob_digest = source.put_blob(b"immutable-persistence-fixture")
                expected = source.canonical_export()
                source.backup_to(backup_path)
                source.apply(vertical_commands()[6])
                self.assertNotEqual(source.canonical_export(), expected)
            with SQLiteStore(backup_path, authority) as restored:
                self.assertEqual(restored.canonical_export(), expected)
                self.assertEqual(
                    restored.get_blob(blob_digest), b"immutable-persistence-fixture"
                )
                restored.verify_integrity()

    def test_wal_active_reader_observes_stable_snapshot_while_writer_commits(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "reader.sqlite3"
            authority = fixture_authority()
            with SQLiteStore(path, authority) as writer:
                self.run_prefix(writer, 2)
                reader = sqlite3.connect(path, isolation_level=None)
                try:
                    reader.execute("BEGIN")
                    before = reader.execute(
                        "SELECT loop_revision FROM loops WHERE loop_ref = ?", (LOOP_REF,)
                    ).fetchone()[0]
                    self.assertEqual(before, 2)
                    writer.apply(vertical_commands()[2])
                    during = reader.execute(
                        "SELECT loop_revision FROM loops WHERE loop_ref = ?", (LOOP_REF,)
                    ).fetchone()[0]
                    self.assertEqual(during, 2)
                    reader.commit()
                    after = reader.execute(
                        "SELECT loop_revision FROM loops WHERE loop_ref = ?", (LOOP_REF,)
                    ).fetchone()[0]
                    self.assertEqual(after, 3)
                finally:
                    reader.close()

    def test_bounded_writer_contention_has_no_partial_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "writers.sqlite3"
            authority = fixture_authority()
            with SQLiteStore(path, authority) as first:
                first.apply(vertical_commands()[0])
                exact_pre = first.canonical_export()
                with SQLiteStore(path, authority, busy_timeout_ms=25) as second:
                    first._connection.execute("BEGIN IMMEDIATE")
                    try:
                        with self.assertRaises(PersistenceBusy):
                            second.apply(vertical_commands()[1])
                    finally:
                        first._connection.rollback()
                    self.assertEqual(second.canonical_export(), exact_pre)
                    second.apply(vertical_commands()[1])
                    self.assertEqual(second.snapshot(LOOP_REF)["loop_revision"], 2)
                    second.verify_integrity()

    def test_rejection_replay_and_changed_request_survive_reopen(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rejections.sqlite3"
            authority = fixture_authority()
            command = vertical_commands()[1]
            with SQLiteStore(path, authority) as store:
                store.apply(vertical_commands()[0])
                stale = command.__class__(
                    **{**command.__dict__, "expected_loop_revision": 0, "request_digest": ""}
                )
                stale = stale.__class__(
                    **{**stale.__dict__, "request_digest": command_digest(stale)}
                )
                with self.assertRaisesRegex(ProtocolRejection, "STALE_LOOP_REVISION"):
                    store.apply(stale)
                self.assertEqual(store.rejection_count, 1)
            with SQLiteStore(path, authority) as reopened:
                with self.assertRaisesRegex(ProtocolRejection, "STALE_LOOP_REVISION"):
                    reopened.apply(stale)
                self.assertEqual(reopened.rejection_count, 1)
                changed = stale.__class__(
                    **{**stale.__dict__, "semantic_payload": {"role": "changed"}, "request_digest": ""}
                )
                changed = changed.__class__(
                    **{**changed.__dict__, "request_digest": command_digest(changed)}
                )
                with self.assertRaisesRegex(ProtocolRejection, "IDEMPOTENCY_CONFLICT"):
                    reopened.apply(changed)

    def test_manual_export_and_immutable_blob_are_canonical_and_stable(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "export.sqlite3"
            with SQLiteStore(path, fixture_authority()) as store:
                digest = store.put_blob(b"same bytes")
                self.assertEqual(store.put_blob(b"same bytes"), digest)
                self.assertEqual(store.get_blob(digest), b"same bytes")
                store.apply(vertical_commands()[0])
                first = store.canonical_export()
                second = store.canonical_export()
                self.assertEqual(first, second)
                self.assertEqual(canonical_bytes(json.loads(first)), first)
                store.verify_integrity()

    def test_logical_and_physical_corruption_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            logical_path = root / "logical.sqlite3"
            with SQLiteStore(logical_path, fixture_authority()) as store:
                store.apply(vertical_commands()[0])
                store._connection.execute(
                    "UPDATE loops SET snapshot_digest = 'tampered' WHERE loop_ref = ?",
                    (LOOP_REF,),
                )
                self.assertRaises(PersistenceCorruption, store.verify_integrity)

            physical_path = root / "physical.sqlite3"
            physical_path.write_bytes(b"not-a-sqlite-database")
            physical_path.chmod(0o600)
            with self.assertRaises(PersistenceCorruption):
                SQLiteStore(physical_path, fixture_authority())

    def test_macos_safe_file_and_reopen_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "循环-store.sqlite3"
            authority = fixture_authority()
            with SQLiteStore(path, authority) as store:
                store.apply(vertical_commands()[0])
                mode = path.stat().st_mode & 0o777
                self.assertEqual(mode, 0o600)
                journal = store._connection.execute("PRAGMA journal_mode").fetchone()[0]
                synchronous = store._connection.execute("PRAGMA synchronous").fetchone()[0]
                self.assertEqual(str(journal).lower(), "wal")
                self.assertEqual(synchronous, 2)
                if sys.platform == "darwin":
                    self.assertEqual(path.stat().st_dev, path.parent.stat().st_dev)
            with SQLiteStore(path, authority) as reopened:
                self.assertEqual(reopened.snapshot(LOOP_REF)["loop_revision"], 1)
                reopened.verify_integrity()

            link = Path(temporary) / "linked.sqlite3"
            os.symlink(path, link)
            with self.assertRaises(PersistenceError):
                SQLiteStore(link, authority)


if __name__ == "__main__":
    unittest.main()
