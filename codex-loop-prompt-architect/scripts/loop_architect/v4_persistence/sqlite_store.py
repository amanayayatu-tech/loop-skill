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
    ActorRef,
    AuthorityGrant,
    CommandEnvelope,
    EffectAttempt,
    Receipt,
    InjectedCrash,
    ProtocolRejection,
    canonical_bytes,
    authority_grant_digest,
    command_digest,
    domain_digest,
    raw_domain_digest,
    snapshot_digest,
    validate_command,
)


SCHEMA_VERSION = 4
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
        authority: AuthorityContext | None = None,
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
            if self.authority is None:
                self.authority = self._load_authority()
        except sqlite3.DatabaseError as exc:
            if hasattr(self, "_connection"):
                self._connection.close()
            raise PersistenceCorruption(f"cannot open SQLite store: {self.path}") from exc
        except Exception:
            if hasattr(self, "_connection"):
                self._connection.close()
            raise

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
                subject_kind TEXT NOT NULL,
                subject_ref TEXT NOT NULL,
                target_ref TEXT NOT NULL,
                action TEXT NOT NULL,
                payload_json BLOB NOT NULL,
                provider_idempotency_key TEXT NOT NULL UNIQUE,
                provider_request_digest TEXT NOT NULL,
                automatic_budget_consumed INTEGER NOT NULL CHECK (
                    automatic_budget_consumed IN (0, 1)
                ),
                attempt_revision INTEGER NOT NULL,
                attempt_state TEXT NOT NULL,
                invocation_state TEXT NOT NULL DEFAULT 'READY',
                executor_ref TEXT,
                observation_receipt_ref TEXT,
                FOREIGN KEY (loop_ref) REFERENCES loops(loop_ref)
            ) STRICT;
            CREATE TABLE IF NOT EXISTS immutable_blobs (
                blob_digest TEXT PRIMARY KEY,
                content BLOB NOT NULL,
                content_bytes INTEGER NOT NULL
            ) STRICT;
            CREATE TABLE IF NOT EXISTS loop_descriptors (
                loop_ref TEXT PRIMARY KEY,
                goal_text BLOB NOT NULL,
                goal_digest TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (loop_ref) REFERENCES loops(loop_ref)
            ) STRICT;
            CREATE TABLE IF NOT EXISTS authority_actors (
                actor_ref TEXT PRIMARY KEY,
                loop_ref TEXT NOT NULL,
                actor_json BLOB NOT NULL,
                FOREIGN KEY (loop_ref) REFERENCES loops(loop_ref)
            ) STRICT;
            CREATE TABLE IF NOT EXISTS authority_grants (
                grant_ref TEXT PRIMARY KEY,
                loop_ref TEXT NOT NULL,
                grant_json BLOB NOT NULL,
                FOREIGN KEY (loop_ref) REFERENCES loops(loop_ref)
            ) STRICT;
            CREATE TABLE IF NOT EXISTS authority_receipts (
                receipt_ref TEXT PRIMARY KEY,
                loop_ref TEXT NOT NULL,
                receipt_json BLOB NOT NULL,
                FOREIGN KEY (loop_ref) REFERENCES loops(loop_ref)
            ) STRICT;
            CREATE TABLE IF NOT EXISTS authority_trust_roots (
                loop_ref TEXT NOT NULL,
                trust_kind TEXT NOT NULL CHECK (
                    trust_kind IN ('actor', 'grant', 'receipt')
                ),
                issuer_ref TEXT NOT NULL,
                issuer_trust TEXT NOT NULL,
                PRIMARY KEY (loop_ref, trust_kind, issuer_ref),
                FOREIGN KEY (loop_ref) REFERENCES loops(loop_ref)
            ) STRICT;
            INSERT OR IGNORE INTO metadata(key, value)
                VALUES ('schema_version', '4');
            COMMIT;
            """
        )
        row = self._connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        if row is not None and int(row[0]) == 1:
            self._migrate_v1_to_v2()
            row = self._connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
        if row is not None and int(row[0]) == 2:
            self._migrate_v2_to_v3()
            row = self._connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
        if row is not None and int(row[0]) == 3:
            self._migrate_v3_to_v4()
            row = self._connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
        if row is None or int(row[0]) != SCHEMA_VERSION:
            raise PersistenceCorruption("unsupported SQLite schema version")

    def _migrate_v1_to_v2(self) -> None:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._connection.execute(
                "ALTER TABLE outbox ADD COLUMN invocation_state TEXT NOT NULL DEFAULT 'READY'"
            )
            self._connection.execute("ALTER TABLE outbox ADD COLUMN executor_ref TEXT")
            self._connection.execute(
                "ALTER TABLE outbox ADD COLUMN observation_receipt_ref TEXT"
            )
            self._connection.execute("ALTER TABLE outbox ADD COLUMN target_ref TEXT")
            for row in self._connection.execute("SELECT loop_ref, snapshot_json FROM loops"):
                snapshot = _decode_canonical(
                    bytes(row["snapshot_json"]), f"v1-migration:{row['loop_ref']}"
                )
                for attempt_ref, attempt in snapshot["attempts"].items():
                    self._connection.execute(
                        "UPDATE outbox SET target_ref = ? WHERE attempt_ref = ?",
                        (attempt["target_ref"], attempt_ref),
                    )
            missing = self._connection.execute(
                "SELECT COUNT(*) FROM outbox WHERE target_ref IS NULL"
            ).fetchone()[0]
            if missing:
                raise PersistenceCorruption("v1 outbox target migration incomplete")
            self._connection.execute(
                "UPDATE metadata SET value = '2' WHERE key = 'schema_version'"
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def _migrate_v2_to_v3(self) -> None:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._connection.execute(
                "UPDATE metadata SET value = '3' WHERE key = 'schema_version'"
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def _migrate_v3_to_v4(self) -> None:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._connection.execute("ALTER TABLE outbox ADD COLUMN subject_kind TEXT")
            self._connection.execute("ALTER TABLE outbox ADD COLUMN subject_ref TEXT")
            self._connection.execute("ALTER TABLE outbox ADD COLUMN action TEXT")
            self._connection.execute("ALTER TABLE outbox ADD COLUMN payload_json BLOB")
            for row in self._connection.execute("SELECT loop_ref, snapshot_json FROM loops"):
                snapshot = _decode_canonical(
                    bytes(row["snapshot_json"]), f"v3-migration:{row['loop_ref']}"
                )
                for attempt_ref, attempt in snapshot["attempts"].items():
                    wire = self._attempt_wire(snapshot, attempt_ref, attempt)
                    self._connection.execute(
                        """
                        UPDATE outbox
                           SET subject_kind = ?, subject_ref = ?, action = ?, payload_json = ?
                         WHERE attempt_ref = ?
                        """,
                        (
                            wire.subject_kind,
                            wire.subject_ref,
                            wire.action,
                            canonical_bytes(wire.payload),
                            attempt_ref,
                        ),
                    )
            missing = self._connection.execute(
                """
                SELECT COUNT(*) FROM outbox
                 WHERE subject_kind IS NULL OR subject_ref IS NULL
                    OR action IS NULL OR payload_json IS NULL
                """
            ).fetchone()[0]
            if missing:
                raise PersistenceCorruption("v3 outbox subject migration incomplete")
            self._connection.execute(
                "UPDATE metadata SET value = '4' WHERE key = 'schema_version'"
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def _load_authority(self) -> AuthorityContext:
        actors: dict[str, ActorRef] = {}
        grants: dict[str, AuthorityGrant] = {}
        receipts: dict[str, Receipt] = {}
        for row in self._connection.execute(
            "SELECT actor_ref, loop_ref, actor_json FROM authority_actors ORDER BY actor_ref"
        ):
            value = _decode_canonical(
                bytes(row["actor_json"]), f"actor:{row['actor_ref']}"
            )
            actor = ActorRef(**value)
            if actor.actor_ref != row["actor_ref"] or actor.loop_namespace != row["loop_ref"]:
                raise PersistenceCorruption("authority Actor identity mismatch")
            actors[row["actor_ref"]] = actor
        for row in self._connection.execute(
            "SELECT grant_ref, loop_ref, grant_json FROM authority_grants ORDER BY grant_ref"
        ):
            value = _decode_canonical(
                bytes(row["grant_json"]), f"grant:{row['grant_ref']}"
            )
            value["allowed_commands"] = tuple(value["allowed_commands"])
            value["subject_kinds"] = tuple(value["subject_kinds"])
            value["exact_subjects"] = tuple(value["exact_subjects"])
            grant = AuthorityGrant(**value)
            if (
                grant.grant_ref != row["grant_ref"]
                or grant.loop_scope != row["loop_ref"]
                or grant.canonical_digest != authority_grant_digest(grant)
            ):
                raise PersistenceCorruption("authority Grant identity mismatch")
            grants[row["grant_ref"]] = grant
        for row in self._connection.execute(
            """
            SELECT receipt_ref, loop_ref, receipt_json
              FROM authority_receipts ORDER BY receipt_ref
            """
        ):
            value = _decode_canonical(
                bytes(row["receipt_json"]), f"receipt:{row['receipt_ref']}"
            )
            receipt = Receipt(**value)
            if (
                receipt.receipt_ref != row["receipt_ref"]
                or receipt.loop_ref != row["loop_ref"]
            ):
                raise PersistenceCorruption("authority Receipt identity mismatch")
            receipts[row["receipt_ref"]] = receipt
        trust = {"actor": {}, "grant": {}, "receipt": {}}
        for row in self._connection.execute(
            """
            SELECT trust_kind, issuer_ref, issuer_trust
              FROM authority_trust_roots
             ORDER BY trust_kind, issuer_ref
            """
        ):
            trust[row["trust_kind"]][row["issuer_ref"]] = row["issuer_trust"]
        context = AuthorityContext(
            actors=actors,
            grants=grants,
            receipts=receipts,
            trusted_actor_issuers=trust["actor"],
            trusted_grant_issuers=trust["grant"],
            trusted_receipt_issuers=trust["receipt"],
        )
        for actor in actors.values():
            if context.trusted_actor_issuers.get(actor.issuer_ref) != actor.issuer_trust:
                raise PersistenceCorruption("authority Actor trust mismatch")
        for grant in grants.values():
            if grant.actor_ref not in actors or grant.issuer_actor_ref not in actors:
                raise PersistenceCorruption("authority Grant actor is absent")
            if (
                context.trusted_grant_issuers.get(grant.issuer_actor_ref)
                != grant.issuer_trust
            ):
                raise PersistenceCorruption("authority Grant trust mismatch")
        for receipt in receipts.values():
            if (
                context.trusted_receipt_issuers.get(receipt.issuer_ref)
                != receipt.issuer_trust
            ):
                raise PersistenceCorruption("authority Receipt trust mismatch")
        return context

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
            if command.command_type == "CreateLoop":
                self._sync_loop_identity(command)
            self._sync_receipts(command)
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

    def _sync_loop_identity(self, command: CommandEnvelope) -> None:
        if self.authority is None:
            raise PersistenceCorruption("CreateLoop authority is absent")
        loop_ref = str(command.subject["loop_ref"])
        objective = str(command.semantic_payload["objective"])
        self._connection.execute(
            """
            INSERT INTO loop_descriptors(
                loop_ref, goal_text, goal_digest, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (
                loop_ref,
                objective.encode("utf-8", "strict"),
                domain_digest("loopskill-goal-objective-v1\n", objective),
                command.issued_at,
            ),
        )
        actors = {
            ref: actor
            for ref, actor in self.authority.actors.items()
            if actor.loop_namespace == loop_ref
        }
        grants = {
            ref: grant
            for ref, grant in self.authority.grants.items()
            if grant.loop_scope == loop_ref
        }
        if command.actor_ref not in actors or command.authority_grant_ref not in grants:
            raise PersistenceCorruption("CreateLoop authority binding is incomplete")
        for actor_ref, actor in sorted(actors.items()):
            self._connection.execute(
                """
                INSERT INTO authority_actors(actor_ref, loop_ref, actor_json)
                VALUES (?, ?, ?)
                """,
                (actor_ref, loop_ref, canonical_bytes(actor.__dict__)),
            )
        for grant_ref, grant in sorted(grants.items()):
            self._connection.execute(
                """
                INSERT INTO authority_grants(grant_ref, loop_ref, grant_json)
                VALUES (?, ?, ?)
                """,
                (grant_ref, loop_ref, canonical_bytes(grant.__dict__)),
            )
        roots = (
            ("actor", self.authority.trusted_actor_issuers),
            ("grant", self.authority.trusted_grant_issuers),
            ("receipt", self.authority.trusted_receipt_issuers),
        )
        for trust_kind, values in roots:
            for issuer_ref, issuer_trust in sorted(values.items()):
                self._connection.execute(
                    """
                    INSERT INTO authority_trust_roots(
                        loop_ref, trust_kind, issuer_ref, issuer_trust
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (loop_ref, trust_kind, issuer_ref, issuer_trust),
                )

    def _sync_receipts(self, command: CommandEnvelope) -> None:
        if self.authority is None:
            raise PersistenceCorruption("receipt authority is absent")
        loop_ref = str(command.subject["loop_ref"])
        for receipt_ref in sorted(command.machine_bindings["receipt_refs"].values()):
            receipt = self.authority.receipts.get(receipt_ref)
            if receipt is None or receipt.loop_ref != loop_ref:
                raise PersistenceCorruption("command receipt is absent from authority")
            raw = canonical_bytes(receipt.__dict__)
            existing = self._connection.execute(
                "SELECT receipt_json FROM authority_receipts WHERE receipt_ref = ?",
                (receipt_ref,),
            ).fetchone()
            if existing is None:
                self._connection.execute(
                    """
                    INSERT INTO authority_receipts(receipt_ref, loop_ref, receipt_json)
                    VALUES (?, ?, ?)
                    """,
                    (receipt_ref, loop_ref, raw),
                )
            elif bytes(existing["receipt_json"]) != raw:
                raise PersistenceCorruption("immutable receipt identity conflict")

    def loop_descriptor(self, loop_ref: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM loop_descriptors WHERE loop_ref = ?", (loop_ref,)
        ).fetchone()
        if row is None:
            return None
        try:
            goal = bytes(row["goal_text"]).decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise PersistenceCorruption("loop goal is not strict UTF-8") from exc
        if domain_digest("loopskill-goal-objective-v1\n", goal) != row["goal_digest"]:
            raise PersistenceCorruption("loop goal digest mismatch")
        return {
            "created_at": row["created_at"],
            "goal": goal,
            "goal_digest": row["goal_digest"],
            "loop_ref": row["loop_ref"],
        }

    def loop_descriptors(self) -> list[dict[str, Any]]:
        refs = [
            str(row[0])
            for row in self._connection.execute(
                "SELECT loop_ref FROM loop_descriptors ORDER BY loop_ref"
            )
        ]
        descriptors = []
        for loop_ref in refs:
            descriptor = self.loop_descriptor(loop_ref)
            if descriptor is None:
                raise PersistenceCorruption("loop descriptor index mismatch")
            descriptors.append(descriptor)
        return descriptors

    @staticmethod
    def _attempt_wire(
        snapshot: dict[str, Any], attempt_ref: str, attempt: dict[str, Any]
    ) -> EffectAttempt:
        delivery_ref = attempt.get("delivery_ref")
        if "external_effect_ref" in attempt:
            subject_kind = "ExternalEffectRef"
            subject_ref = attempt["external_effect_ref"]
            action = attempt["action"]
            payload = attempt["provider_request"]
        else:
            subject_kind = "DeliveryRef"
            subject_ref = delivery_ref
            delivery = snapshot["deliveries"][delivery_ref]
            route = snapshot["routes"][delivery["route_ref"]]
            action = "send"
            payload = {
                "intent_digest": route["intent_digest"],
                "target_ref": attempt["target_ref"],
            }
        return EffectAttempt(
            attempt_ref=attempt_ref,
            loop_ref=snapshot["loop_ref"],
            subject_kind=subject_kind,
            subject_ref=subject_ref,
            delivery_ref=delivery_ref,
            target_ref=attempt["target_ref"],
            provider_idempotency_key=attempt["provider_idempotency_key"],
            provider_request_digest=attempt["provider_request_digest"],
            action=action,
            payload=payload,
        )

    def _sync_outbox(self, loop_ref: str, snapshot: dict[str, Any]) -> None:
        expected_attempts = set(snapshot["attempts"])
        for attempt_ref, attempt in sorted(snapshot["attempts"].items()):
            wire = self._attempt_wire(snapshot, attempt_ref, attempt)
            self._connection.execute(
                """
                INSERT INTO outbox(
                    attempt_ref, loop_ref, delivery_ref, subject_kind, subject_ref,
                    target_ref, action, payload_json,
                    provider_idempotency_key, provider_request_digest,
                    automatic_budget_consumed, attempt_revision, attempt_state,
                    invocation_state, observation_receipt_ref
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(attempt_ref) DO UPDATE SET
                    delivery_ref = excluded.delivery_ref,
                    subject_kind = excluded.subject_kind,
                    subject_ref = excluded.subject_ref,
                    target_ref = excluded.target_ref,
                    action = excluded.action,
                    payload_json = excluded.payload_json,
                    provider_idempotency_key = excluded.provider_idempotency_key,
                    provider_request_digest = excluded.provider_request_digest,
                    automatic_budget_consumed = excluded.automatic_budget_consumed,
                    attempt_revision = excluded.attempt_revision,
                    attempt_state = excluded.attempt_state,
                    invocation_state = CASE
                        WHEN excluded.attempt_state = 'OBSERVED' THEN 'OBSERVED'
                        WHEN excluded.attempt_state = 'UNKNOWN' THEN 'UNKNOWN'
                        WHEN excluded.attempt_state = 'UNVERIFIABLE' THEN 'UNVERIFIABLE'
                        ELSE outbox.invocation_state
                    END,
                    observation_receipt_ref = CASE
                        WHEN excluded.attempt_state IN ('OBSERVED', 'UNKNOWN', 'UNVERIFIABLE')
                        THEN excluded.observation_receipt_ref
                        ELSE outbox.observation_receipt_ref
                    END
                """,
                (
                    attempt_ref,
                    loop_ref,
                    wire.delivery_ref or "",
                    wire.subject_kind,
                    wire.subject_ref,
                    wire.target_ref,
                    wire.action,
                    canonical_bytes(wire.payload),
                    wire.provider_idempotency_key,
                    wire.provider_request_digest,
                    int(attempt["automatic_budget_consumed"]),
                    attempt["revision"],
                    attempt["state"],
                    (
                        attempt["state"]
                        if attempt["state"] in {"OBSERVED", "UNKNOWN", "UNVERIFIABLE"}
                        else "READY"
                    ),
                    attempt.get("observation_receipt_ref"),
                ),
            )
        rows = self._connection.execute(
            "SELECT attempt_ref FROM outbox WHERE loop_ref = ?", (loop_ref,)
        ).fetchall()
        unexpected = {str(row[0]) for row in rows} - expected_attempts
        if unexpected:
            raise PersistenceCorruption("outbox contains an attempt absent from snapshot")

    def effect_attempt(self, attempt_ref: str) -> EffectAttempt | None:
        row = self._connection.execute(
            "SELECT * FROM outbox WHERE attempt_ref = ?", (attempt_ref,)
        ).fetchone()
        if row is None:
            return None
        payload = _decode_canonical(
            bytes(row["payload_json"]), f"attempt-payload:{attempt_ref}"
        )
        if not isinstance(payload, dict):
            raise PersistenceCorruption("Attempt provider payload is not an object")
        return EffectAttempt(
            attempt_ref=row["attempt_ref"],
            loop_ref=row["loop_ref"],
            subject_kind=row["subject_kind"],
            subject_ref=row["subject_ref"],
            delivery_ref=row["delivery_ref"] or None,
            target_ref=row["target_ref"],
            provider_idempotency_key=row["provider_idempotency_key"],
            provider_request_digest=row["provider_request_digest"],
            action=row["action"],
            payload=payload,
        )

    def ready_effect_attempts(self) -> tuple[EffectAttempt, ...]:
        refs = [
            str(row[0])
            for row in self._connection.execute(
                """
                SELECT attempt_ref FROM outbox
                 WHERE attempt_state = 'COMMITTED' AND invocation_state = 'READY'
                 ORDER BY attempt_ref
                """
            )
        ]
        attempts = []
        for attempt_ref in refs:
            attempt = self.effect_attempt(attempt_ref)
            if attempt is None:
                raise PersistenceCorruption("ready Attempt index mismatch")
            attempts.append(attempt)
        return tuple(attempts)

    def claim_attempt(self, attempt_ref: str, executor_ref: str) -> bool:
        """Atomically consume execution ownership without invoking a provider."""
        self._begin()
        try:
            row = self._connection.execute(
                "SELECT attempt_state, invocation_state FROM outbox WHERE attempt_ref = ?",
                (attempt_ref,),
            ).fetchone()
            if row is None:
                raise PersistenceCorruption("Attempt outbox record is absent")
            if row["attempt_state"] != "COMMITTED":
                self._connection.commit()
                return False
            if row["invocation_state"] != "READY":
                self._connection.commit()
                return False
            changed = self._connection.execute(
                """
                UPDATE outbox
                   SET invocation_state = 'STARTED', executor_ref = ?
                 WHERE attempt_ref = ?
                   AND attempt_state = 'COMMITTED'
                   AND invocation_state = 'READY'
                """,
                (executor_ref, attempt_ref),
            ).rowcount
            self._connection.commit()
            return changed == 1
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def outbox_attempt(self, attempt_ref: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM outbox WHERE attempt_ref = ?", (attempt_ref,)
        ).fetchone()
        return None if row is None else dict(row)

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
        outbox = []
        for row in self._connection.execute(
            "SELECT * FROM outbox ORDER BY attempt_ref"
        ):
            value = dict(row)
            value["payload"] = _decode_canonical(
                bytes(value.pop("payload_json")),
                f"attempt-payload:{row['attempt_ref']}",
            )
            outbox.append(value)
        blobs = [
            {"blob_digest": row["blob_digest"], "content_bytes": row["content_bytes"]}
            for row in self._connection.execute(
                "SELECT blob_digest, content_bytes FROM immutable_blobs ORDER BY blob_digest"
            )
        ]
        descriptors = self.loop_descriptors()
        authority = {
            "actors": [
                _decode_canonical(
                    bytes(row["actor_json"]), f"actor:{row['actor_ref']}"
                )
                for row in self._connection.execute(
                    "SELECT * FROM authority_actors ORDER BY actor_ref"
                )
            ],
            "grants": [
                _decode_canonical(
                    bytes(row["grant_json"]), f"grant:{row['grant_ref']}"
                )
                for row in self._connection.execute(
                    "SELECT * FROM authority_grants ORDER BY grant_ref"
                )
            ],
            "receipts": [
                _decode_canonical(
                    bytes(row["receipt_json"]), f"receipt:{row['receipt_ref']}"
                )
                for row in self._connection.execute(
                    "SELECT * FROM authority_receipts ORDER BY receipt_ref"
                )
            ],
            "trust_roots": [
                {
                    "issuer_ref": row["issuer_ref"],
                    "issuer_trust": row["issuer_trust"],
                    "loop_ref": row["loop_ref"],
                    "trust_kind": row["trust_kind"],
                }
                for row in self._connection.execute(
                    """
                    SELECT * FROM authority_trust_roots
                     ORDER BY loop_ref, trust_kind, issuer_ref
                    """
                )
            ],
        }
        return canonical_bytes(
            {
                "authority": authority,
                "blobs": blobs,
                "descriptors": descriptors,
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
                descriptor = self.loop_descriptor(str(row["loop_ref"]))
                if descriptor is None:
                    raise PersistenceCorruption("loop descriptor is absent")
                if descriptor["goal_digest"] not in {
                    goal["objective_digest"] for goal in snapshot["goals"].values()
                }:
                    raise PersistenceCorruption("loop descriptor goal mismatch")
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
                expected_outbox = set()
                for attempt_ref, attempt in snapshot["attempts"].items():
                    wire = self._attempt_wire(snapshot, attempt_ref, attempt)
                    expected_outbox.add(
                        (
                            attempt_ref,
                            wire.delivery_ref or "",
                            wire.subject_kind,
                            wire.subject_ref,
                            wire.target_ref,
                            wire.action,
                            canonical_bytes(wire.payload),
                            wire.provider_idempotency_key,
                            wire.provider_request_digest,
                            int(attempt["automatic_budget_consumed"]),
                            attempt["revision"],
                            attempt["state"],
                        )
                    )
                actual_outbox = {
                    (
                        outbox["attempt_ref"],
                        outbox["delivery_ref"],
                        outbox["subject_kind"],
                        outbox["subject_ref"],
                        outbox["target_ref"],
                        outbox["action"],
                        bytes(outbox["payload_json"]),
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
                for outbox in self._connection.execute(
                    "SELECT * FROM outbox WHERE loop_ref = ?", (row["loop_ref"],)
                ):
                    attempt = snapshot["attempts"][outbox["attempt_ref"]]
                    if attempt["state"] in {"OBSERVED", "UNKNOWN", "UNVERIFIABLE"}:
                        if outbox["invocation_state"] != attempt["state"]:
                            raise PersistenceCorruption(
                                "snapshot/outbox invocation state mismatch"
                            )
                        if (
                            outbox["observation_receipt_ref"]
                            != attempt["observation_receipt_ref"]
                        ):
                            raise PersistenceCorruption(
                                "snapshot/outbox observation receipt mismatch"
                            )
                    elif outbox["invocation_state"] not in {"READY", "STARTED"}:
                        raise PersistenceCorruption("invalid pending invocation state")
            for row in self._connection.execute("SELECT * FROM operations"):
                _decode_canonical(
                    bytes(row["outcome_json"]),
                    f"operation:{row['loop_ref']}:{row['operation_id']}",
                )
            self._load_authority()
            for row in self._connection.execute("SELECT * FROM immutable_blobs"):
                content = bytes(row["content"])
                if len(content) != row["content_bytes"]:
                    raise PersistenceCorruption("blob byte count mismatch")
                if raw_domain_digest("loopskill-blob-v1\n", content) != row["blob_digest"]:
                    raise PersistenceCorruption("blob digest mismatch")
        except sqlite3.DatabaseError as exc:
            raise PersistenceCorruption("SQLite integrity read failed") from exc
