"""SQLite candidate implementing the LoopSkill 4 transactional store port."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from pathlib import Path
from typing import Any

from loop_architect.v4_alpha.kernel import AuthorityContext, reduce_command
from loop_architect.v4_alpha.protocol import (
    ApplyResult,
    CommandEnvelope,
    InjectedCrash,
    ProtocolRejection,
    canonical_bytes,
    command_digest,
    raw_domain_digest,
    snapshot_digest,
    validate_command,
)


SCHEMA_VERSION = 1
DURABLE_FAULT_BOUNDARIES = (
    "before_begin",
    "after_begin",
    "after_reduce_before_write",
    "after_operation_write",
    "after_events_write",
    "after_snapshot_write",
    "after_outbox_write",
    "before_commit",
    "after_commit_before_response",
)


class PersistenceError(RuntimeError):
    """Base error for the candidate persistence implementation."""


class PersistenceBusy(PersistenceError):
    """A bounded writer could not acquire SQLite's write transaction."""


class PersistenceCorruption(PersistenceError):
    """Durable bytes fail structural, canonical, or digest verification."""


def _decode_canonical(raw: bytes, label: str) -> Any:
    try:
        value = json.loads(raw.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersistenceCorruption(f"invalid canonical JSON: {label}") from exc
    if canonical_bytes(value) != raw:
        raise PersistenceCorruption(f"non-canonical JSON: {label}")
    return value


def _result_payload(result: ApplyResult) -> dict[str, Any]:
    return {
        "event_types": list(result.event_types),
        "loop_ref": result.loop_ref,
        "loop_revision": result.loop_revision,
        "operation_id": result.operation_id,
        "response": dict(result.response),
        "snapshot_digest": result.snapshot_digest,
    }


def _apply_result(value: dict[str, Any], *, replayed: bool) -> ApplyResult:
    return ApplyResult(
        operation_id=value["operation_id"],
        loop_ref=value["loop_ref"],
        loop_revision=value["loop_revision"],
        event_types=tuple(value["event_types"]),
        response=value["response"],
        snapshot_digest=value["snapshot_digest"],
        replayed=replayed,
    )


class SQLiteStore:
    """Single canonical writer backed by one SQLite transaction per operation."""

    def __init__(
        self,
        path: Path | str,
        authority: AuthorityContext,
        *,
        busy_timeout_ms: int = 1_000,
    ) -> None:
        self.path = Path(path)
        self.authority = authority
        self.busy_timeout_ms = busy_timeout_ms
        self._closed = False
        self._prepare_path()
        try:
            self._connection = sqlite3.connect(
                self.path,
                isolation_level=None,
                timeout=busy_timeout_ms / 1_000,
            )
            self._connection.row_factory = sqlite3.Row
            self._configure()
            self._initialize_schema()
        except sqlite3.DatabaseError as exc:
            raise PersistenceCorruption(f"cannot open SQLite store: {self.path}") from exc

    def _prepare_path(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise PersistenceError("SQLite store path must not be a symlink")
        if self.path.exists():
            metadata = self.path.stat()
            if not stat.S_ISREG(metadata.st_mode):
                raise PersistenceError("SQLite store path must be a regular file")
            if metadata.st_mode & 0o077:
                raise PersistenceError("SQLite store permissions must be owner-only")
        else:
            descriptor = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_RDWR,
                0o600,
            )
            os.close(descriptor)

    def _configure(self) -> None:
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        journal_mode = self._connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if str(journal_mode).lower() != "wal":
            raise PersistenceError("SQLite WAL mode unavailable")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._connection.execute("PRAGMA temp_store = MEMORY")
        self._connection.execute("PRAGMA trusted_schema = OFF")

    def _initialize_schema(self) -> None:
        self._connection.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            ) STRICT;
            CREATE TABLE IF NOT EXISTS loops (
                loop_ref TEXT PRIMARY KEY,
                loop_revision INTEGER NOT NULL,
                snapshot_json BLOB NOT NULL,
                snapshot_digest TEXT NOT NULL
            ) STRICT;
            CREATE TABLE IF NOT EXISTS operations (
                loop_ref TEXT NOT NULL,
                operation_id TEXT NOT NULL,
                request_digest TEXT NOT NULL,
                accepted INTEGER NOT NULL CHECK (accepted IN (0, 1)),
                outcome_json BLOB NOT NULL,
                PRIMARY KEY (loop_ref, operation_id)
            ) STRICT;
            CREATE TABLE IF NOT EXISTS events (
                loop_ref TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                operation_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_json BLOB NOT NULL,
                PRIMARY KEY (loop_ref, sequence),
                FOREIGN KEY (loop_ref, operation_id)
                    REFERENCES operations(loop_ref, operation_id)
            ) STRICT;
            CREATE TABLE IF NOT EXISTS outbox (
                attempt_ref TEXT PRIMARY KEY,
                loop_ref TEXT NOT NULL,
                delivery_ref TEXT NOT NULL,
                provider_idempotency_key TEXT NOT NULL UNIQUE,
                provider_request_digest TEXT NOT NULL,
                automatic_budget_consumed INTEGER NOT NULL CHECK (
                    automatic_budget_consumed IN (0, 1)
                ),
                attempt_revision INTEGER NOT NULL,
                attempt_state TEXT NOT NULL,
                FOREIGN KEY (loop_ref) REFERENCES loops(loop_ref)
            ) STRICT;
            CREATE TABLE IF NOT EXISTS immutable_blobs (
                blob_digest TEXT PRIMARY KEY,
                content BLOB NOT NULL,
                content_bytes INTEGER NOT NULL
            ) STRICT;
            INSERT OR IGNORE INTO metadata(key, value)
                VALUES ('schema_version', '1');
            COMMIT;
            """
        )
        row = self._connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        if row is None or int(row[0]) != SCHEMA_VERSION:
            raise PersistenceCorruption("unsupported SQLite schema version")

    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            self._closed = True

    def __enter__(self) -> "SQLiteStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def commit_count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM operations WHERE accepted = 1"
        ).fetchone()
        return int(row[0])

    @property
    def rejection_count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM operations WHERE accepted = 0"
        ).fetchone()
        return int(row[0])

    def _begin(self) -> None:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                raise PersistenceBusy("bounded SQLite writer contention") from exc
            raise

    def _existing_operation(
        self, loop_ref: str, operation_id: str
    ) -> sqlite3.Row | None:
        return self._connection.execute(
            """
            SELECT request_digest, accepted, outcome_json
              FROM operations
             WHERE loop_ref = ? AND operation_id = ?
            """,
            (loop_ref, operation_id),
        ).fetchone()

    def _snapshot_in_transaction(self, loop_ref: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT snapshot_json FROM loops WHERE loop_ref = ?", (loop_ref,)
        ).fetchone()
        if row is None:
            return None
        value = _decode_canonical(bytes(row[0]), f"snapshot:{loop_ref}")
        if not isinstance(value, dict):
            raise PersistenceCorruption(f"snapshot is not an object: {loop_ref}")
        return value

    def snapshot(self, loop_ref: str) -> dict[str, Any] | None:
        return self._snapshot_in_transaction(loop_ref)

    def events(self, loop_ref: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT sequence, event_json FROM events
             WHERE loop_ref = ? ORDER BY sequence
            """,
            (loop_ref,),
        ).fetchall()
        events = []
        for row in rows:
            event = _decode_canonical(
                bytes(row["event_json"]), f"event:{loop_ref}:{row['sequence']}"
            )
            if not isinstance(event, dict):
                raise PersistenceCorruption("event is not an object")
            events.append(event)
        return events

    def _record_rejection_in_transaction(
        self,
        command: CommandEnvelope,
        calculated_digest: str,
        rejection: ProtocolRejection,
    ) -> None:
        loop_ref = str(command.subject.get("loop_ref", ""))
        self._connection.execute(
            """
            INSERT INTO operations(
                loop_ref, operation_id, request_digest, accepted, outcome_json
            ) VALUES (?, ?, ?, 0, ?)
            """,
            (
                loop_ref,
                command.operation_id,
                calculated_digest,
                canonical_bytes(rejection.as_dict()),
            ),
        )

    def apply(
        self,
        command: CommandEnvelope,
        *,
        fault_at: str | None = None,
    ) -> ApplyResult:
        if fault_at not in {None, *DURABLE_FAULT_BOUNDARIES}:
            raise ValueError(f"unknown durable fault boundary: {fault_at}")
        loop_ref = str(command.subject.get("loop_ref", ""))
        calculated_digest = command_digest(command)
        if fault_at == "before_begin":
            raise InjectedCrash(fault_at)
        self._begin()
        committed = False
        try:
            if fault_at == "after_begin":
                raise InjectedCrash(fault_at)
            existing = self._existing_operation(loop_ref, command.operation_id)
            if existing is not None:
                stored_digest = str(existing["request_digest"])
                if (
                    stored_digest != calculated_digest
                    or command.request_digest != calculated_digest
                ):
                    self._connection.rollback()
                    raise ProtocolRejection(
                        "IDEMPOTENCY_CONFLICT", "operation digest changed"
                    )
                outcome = _decode_canonical(
                    bytes(existing["outcome_json"]),
                    f"operation:{loop_ref}:{command.operation_id}",
                )
                self._connection.commit()
                if int(existing["accepted"]):
                    return _apply_result(outcome, replayed=True)
                raise ProtocolRejection(outcome["code"], outcome["detail"])

            validate_command(command)
            current = self._snapshot_in_transaction(loop_ref)
            actual_revision = 0 if current is None else current["loop_revision"]
            if actual_revision != command.expected_loop_revision:
                raise ProtocolRejection(
                    "STALE_LOOP_REVISION",
                    f"expected {command.expected_loop_revision}, actual {actual_revision}",
                )
            candidate, pending_events, response = reduce_command(
                current, command, self.authority
            )
            if fault_at == "after_reduce_before_write":
                raise InjectedCrash(fault_at)

            event_start = self._connection.execute(
                "SELECT COUNT(*) FROM events WHERE loop_ref = ?", (loop_ref,)
            ).fetchone()[0]
            sequenced = [
                {**event, "sequence": event_start + index + 1}
                for index, event in enumerate(pending_events)
            ]
            digest = snapshot_digest(candidate)
            result = ApplyResult(
                operation_id=command.operation_id,
                loop_ref=loop_ref,
                loop_revision=candidate["loop_revision"],
                event_types=tuple(event["type"] for event in sequenced),
                response=response,
                snapshot_digest=digest,
            )
            self._connection.execute(
                """
                INSERT INTO operations(
                    loop_ref, operation_id, request_digest, accepted, outcome_json
                ) VALUES (?, ?, ?, 1, ?)
                """,
                (
                    loop_ref,
                    command.operation_id,
                    calculated_digest,
                    canonical_bytes(_result_payload(result)),
                ),
            )
            if fault_at == "after_operation_write":
                raise InjectedCrash(fault_at)

            for event in sequenced:
                self._connection.execute(
                    """
                    INSERT INTO events(
                        loop_ref, sequence, operation_id, event_type, event_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        loop_ref,
                        event["sequence"],
                        command.operation_id,
                        event["type"],
                        canonical_bytes(event),
                    ),
                )
            if fault_at == "after_events_write":
                raise InjectedCrash(fault_at)

            self._connection.execute(
                """
                INSERT INTO loops(
                    loop_ref, loop_revision, snapshot_json, snapshot_digest
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(loop_ref) DO UPDATE SET
                    loop_revision = excluded.loop_revision,
                    snapshot_json = excluded.snapshot_json,
                    snapshot_digest = excluded.snapshot_digest
                """,
                (
                    loop_ref,
                    candidate["loop_revision"],
                    canonical_bytes(candidate),
                    digest,
                ),
            )
            if fault_at == "after_snapshot_write":
                raise InjectedCrash(fault_at)

            self._sync_outbox(loop_ref, candidate)
            if fault_at == "after_outbox_write":
                raise InjectedCrash(fault_at)
            if fault_at == "before_commit":
                raise InjectedCrash(fault_at)
            self._connection.commit()
            committed = True
            if fault_at == "after_commit_before_response":
                raise InjectedCrash(fault_at)
            return result
        except InjectedCrash:
            if not committed:
                self._connection.rollback()
            raise
        except ProtocolRejection as exc:
            if self._connection.in_transaction:
                if exc.code == "IDEMPOTENCY_CONFLICT":
                    self._connection.rollback()
                else:
                    self._record_rejection_in_transaction(
                        command, calculated_digest, exc
                    )
                    self._connection.commit()
            raise
        except sqlite3.DatabaseError as exc:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise PersistenceCorruption("SQLite operation failed") from exc

    def _sync_outbox(self, loop_ref: str, snapshot: dict[str, Any]) -> None:
        expected_attempts = set(snapshot["attempts"])
        for attempt_ref, attempt in sorted(snapshot["attempts"].items()):
            self._connection.execute(
                """
                INSERT INTO outbox(
                    attempt_ref, loop_ref, delivery_ref,
                    provider_idempotency_key, provider_request_digest,
                    automatic_budget_consumed, attempt_revision, attempt_state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(attempt_ref) DO UPDATE SET
                    delivery_ref = excluded.delivery_ref,
                    provider_idempotency_key = excluded.provider_idempotency_key,
                    provider_request_digest = excluded.provider_request_digest,
                    automatic_budget_consumed = excluded.automatic_budget_consumed,
                    attempt_revision = excluded.attempt_revision,
                    attempt_state = excluded.attempt_state
                """,
                (
                    attempt_ref,
                    loop_ref,
                    attempt["delivery_ref"],
                    attempt["provider_idempotency_key"],
                    attempt["provider_request_digest"],
                    int(attempt["automatic_budget_consumed"]),
                    attempt["revision"],
                    attempt["state"],
                ),
            )
        rows = self._connection.execute(
            "SELECT attempt_ref FROM outbox WHERE loop_ref = ?", (loop_ref,)
        ).fetchall()
        unexpected = {str(row[0]) for row in rows} - expected_attempts
        if unexpected:
            raise PersistenceCorruption("outbox contains an attempt absent from snapshot")

    def put_blob(self, content: bytes) -> str:
        digest = raw_domain_digest("loopskill-blob-v1\n", content)
        self._begin()
        try:
            row = self._connection.execute(
                "SELECT content FROM immutable_blobs WHERE blob_digest = ?", (digest,)
            ).fetchone()
            if row is None:
                self._connection.execute(
                    """
                    INSERT INTO immutable_blobs(blob_digest, content, content_bytes)
                    VALUES (?, ?, ?)
                    """,
                    (digest, content, len(content)),
                )
            elif bytes(row[0]) != content:
                raise PersistenceCorruption("immutable blob digest collision")
            self._connection.commit()
            return digest
        except Exception:
            self._connection.rollback()
            raise

    def get_blob(self, digest: str) -> bytes | None:
        row = self._connection.execute(
            "SELECT content FROM immutable_blobs WHERE blob_digest = ?", (digest,)
        ).fetchone()
        return None if row is None else bytes(row[0])

    def canonical_export(self) -> bytes:
        loops = []
        for row in self._connection.execute(
            "SELECT * FROM loops ORDER BY loop_ref"
        ):
            loops.append(
                {
                    "loop_ref": row["loop_ref"],
                    "loop_revision": row["loop_revision"],
                    "snapshot": _decode_canonical(
                        bytes(row["snapshot_json"]), f"snapshot:{row['loop_ref']}"
                    ),
                    "snapshot_digest": row["snapshot_digest"],
                }
            )
        events = [
            _decode_canonical(
                bytes(row["event_json"]),
                f"event:{row['loop_ref']}:{row['sequence']}",
            )
            for row in self._connection.execute(
                "SELECT * FROM events ORDER BY loop_ref, sequence"
            )
        ]
        operations = [
            {
                "accepted": bool(row["accepted"]),
                "loop_ref": row["loop_ref"],
                "operation_id": row["operation_id"],
                "outcome": _decode_canonical(
                    bytes(row["outcome_json"]),
                    f"operation:{row['loop_ref']}:{row['operation_id']}",
                ),
                "request_digest": row["request_digest"],
            }
            for row in self._connection.execute(
                "SELECT * FROM operations ORDER BY loop_ref, operation_id"
            )
        ]
        outbox = [
            dict(row)
            for row in self._connection.execute(
                "SELECT * FROM outbox ORDER BY attempt_ref"
            )
        ]
        blobs = [
            {"blob_digest": row["blob_digest"], "content_bytes": row["content_bytes"]}
            for row in self._connection.execute(
                "SELECT blob_digest, content_bytes FROM immutable_blobs ORDER BY blob_digest"
            )
        ]
        return canonical_bytes(
            {
                "blobs": blobs,
                "events": events,
                "loops": loops,
                "operations": operations,
                "outbox": outbox,
                "schema_version": SCHEMA_VERSION,
            }
        )

    def backup_to(self, destination: Path | str) -> None:
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if destination_path.exists():
            raise PersistenceError("backup destination already exists")
        descriptor = os.open(
            destination_path,
            os.O_CREAT | os.O_EXCL | os.O_RDWR,
            0o600,
        )
        os.close(descriptor)
        target = sqlite3.connect(destination_path, isolation_level=None)
        try:
            self._connection.backup(target)
        finally:
            target.close()

    def verify_integrity(self) -> None:
        try:
            quick_check = self._connection.execute("PRAGMA quick_check").fetchone()[0]
            if quick_check != "ok":
                raise PersistenceCorruption(f"SQLite quick_check: {quick_check}")
            for row in self._connection.execute("SELECT * FROM loops"):
                snapshot = _decode_canonical(
                    bytes(row["snapshot_json"]), f"snapshot:{row['loop_ref']}"
                )
                if snapshot_digest(snapshot) != row["snapshot_digest"]:
                    raise PersistenceCorruption("snapshot digest mismatch")
                if snapshot["loop_revision"] != row["loop_revision"]:
                    raise PersistenceCorruption("snapshot revision mismatch")
                accepted = self._connection.execute(
                    """
                    SELECT COUNT(*) FROM operations
                     WHERE loop_ref = ? AND accepted = 1
                    """,
                    (row["loop_ref"],),
                ).fetchone()[0]
                if accepted != row["loop_revision"]:
                    raise PersistenceCorruption("accepted operation/revision mismatch")
                events = self.events(str(row["loop_ref"]))
                if [event["sequence"] for event in events] != list(
                    range(1, len(events) + 1)
                ):
                    raise PersistenceCorruption("event sequence gap")
                expected_outbox = {
                    (
                        attempt_ref,
                        attempt["delivery_ref"],
                        attempt["provider_idempotency_key"],
                        attempt["provider_request_digest"],
                        int(attempt["automatic_budget_consumed"]),
                        attempt["revision"],
                        attempt["state"],
                    )
                    for attempt_ref, attempt in snapshot["attempts"].items()
                }
                actual_outbox = {
                    (
                        outbox["attempt_ref"],
                        outbox["delivery_ref"],
                        outbox["provider_idempotency_key"],
                        outbox["provider_request_digest"],
                        outbox["automatic_budget_consumed"],
                        outbox["attempt_revision"],
                        outbox["attempt_state"],
                    )
                    for outbox in self._connection.execute(
                        "SELECT * FROM outbox WHERE loop_ref = ?", (row["loop_ref"],)
                    )
                }
                if actual_outbox != expected_outbox:
                    raise PersistenceCorruption("snapshot/outbox mismatch")
            for row in self._connection.execute("SELECT * FROM operations"):
                _decode_canonical(
                    bytes(row["outcome_json"]),
                    f"operation:{row['loop_ref']}:{row['operation_id']}",
                )
            for row in self._connection.execute("SELECT * FROM immutable_blobs"):
                content = bytes(row["content"])
                if len(content) != row["content_bytes"]:
                    raise PersistenceCorruption("blob byte count mismatch")
                if raw_domain_digest("loopskill-blob-v1\n", content) != row["blob_digest"]:
                    raise PersistenceCorruption("blob digest mismatch")
        except sqlite3.DatabaseError as exc:
            raise PersistenceCorruption("SQLite integrity read failed") from exc
