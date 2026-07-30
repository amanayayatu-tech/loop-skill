"""Single test adapter for the exact persisted v4.0 EAGER fixture."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

from loop_architect.v4_alpha.kernel import AuthorityContext
from loop_architect.v4_alpha.protocol import (
    ActorRef,
    ApplyResult,
    AuthorityGrant,
    CommandEnvelope,
    Receipt,
    canonical_bytes,
    parse_json_bytes,
)
from loop_architect.v4_alpha.vertical import vertical_commands


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v4_0_eager" / "eager-store.json"
FIXTURE_SHA256 = "a7bd3d03529de67e0e0a336f1004ce436a544bd2405e26c867ab8d4031845a09"
BASELINE_COMMIT = "f7b62cb2fd9bd6ab4b038a8384bced4b7e74cbd9"
BASELINE_TAG_OBJECT = "eb42b904b6973cab5ad0ed586aa4137a8c20943b"


def eager_fixture() -> dict:
    raw = FIXTURE_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256:
        raise RuntimeError("EAGER_V4_0_FIXTURE_DRIFT")
    fixture = json.loads(raw.decode("utf-8"))
    if (
        fixture.get("baseline_commit") != BASELINE_COMMIT
        or fixture.get("baseline_tag_object") != BASELINE_TAG_OBJECT
        or fixture.get("checkpoint_loop_revision") != 5
    ):
        raise RuntimeError("EAGER_V4_0_FIXTURE_PROVENANCE_DRIFT")
    expected = tuple(
        canonical_bytes(value) for value in fixture["continuation_commands"]
    )
    actual = tuple(
        canonical_bytes(command.__dict__) for command in vertical_commands()[5:]
    )
    if actual != expected:
        raise RuntimeError("EAGER_V4_0_CONTINUATION_DRIFT")
    return fixture


def eager_authority() -> AuthorityContext:
    value = eager_fixture()["authority"]
    grants = {}
    for item in value["grants"]:
        fields = dict(item)
        fields["allowed_commands"] = tuple(fields["allowed_commands"])
        fields["subject_kinds"] = tuple(fields["subject_kinds"])
        fields["exact_subjects"] = tuple(fields["exact_subjects"])
        grant = AuthorityGrant(**fields)
        grants[grant.grant_ref] = grant
    return AuthorityContext(
        actors={item["actor_ref"]: ActorRef(**item) for item in value["actors"]},
        grants=grants,
        receipts={
            item["receipt_ref"]: Receipt(**item) for item in value["receipts"]
        },
        trusted_actor_issuers=dict(value["trusted_actor_issuers"]),
        trusted_grant_issuers=dict(value["trusted_grant_issuers"]),
        trusted_receipt_issuers=dict(value["trusted_receipt_issuers"]),
    )


def eager_continuation_commands() -> tuple[CommandEnvelope, ...]:
    return tuple(
        CommandEnvelope(**value)
        for value in eager_fixture()["continuation_commands"]
    )


def seed_eager_memory(store) -> None:
    if store.commit_count != 0 or store.snapshot(eager_fixture()["loop_ref"]) is not None:
        raise ValueError("fixture target must be empty")
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(eager_fixture()["sqlite_logical_dump"])
        for loop_ref, snapshot_raw in connection.execute(
            "SELECT loop_ref, snapshot_json FROM loops"
        ):
            store._snapshots[str(loop_ref)] = parse_json_bytes(bytes(snapshot_raw))
        for loop_ref, event_raw in connection.execute(
            "SELECT loop_ref, event_json FROM events ORDER BY loop_ref, sequence"
        ):
            store._events.setdefault(str(loop_ref), []).append(
                parse_json_bytes(bytes(event_raw))
            )
        accepted_count = 0
        for loop_ref, operation_id, request_digest, accepted, outcome_raw in (
            connection.execute(
                "SELECT loop_ref, operation_id, request_digest, accepted, outcome_json "
                "FROM operations ORDER BY loop_ref, operation_id"
            )
        ):
            outcome = parse_json_bytes(bytes(outcome_raw))
            key = (str(loop_ref), str(operation_id))
            if int(accepted):
                store._accepted[key] = (
                    str(request_digest),
                    ApplyResult(
                        operation_id=str(outcome["operation_id"]),
                        loop_ref=str(outcome["loop_ref"]),
                        loop_revision=int(outcome["loop_revision"]),
                        event_types=tuple(outcome["event_types"]),
                        response=dict(outcome["response"]),
                        snapshot_digest=str(outcome["snapshot_digest"]),
                    ),
                )
                accepted_count += 1
            else:
                store._rejected[key] = (str(request_digest), dict(outcome))
        for digest, content in connection.execute(
            "SELECT blob_digest, content FROM immutable_blobs"
        ):
            store._blobs[str(digest)] = bytes(content)
        store.commit_count = accepted_count
    finally:
        connection.close()
    store.verify_integrity()


def seed_eager_sqlite(store) -> None:
    fixture = eager_fixture()
    if store.commit_count != 0 or store.snapshot(fixture["loop_ref"]) is not None:
        raise ValueError("fixture target must be empty")
    inserts: dict[str, list[str]] = {}
    for statement in fixture["sqlite_logical_dump"].splitlines():
        match = re.match(r'INSERT INTO ["`]?([^"` ]+)', statement)
        if match and match.group(1) != "metadata":
            inserts.setdefault(match.group(1), []).append(statement)
    order = (
        "loops",
        "loop_descriptors",
        "operations",
        "events",
        "outbox",
        "immutable_blobs",
        "authority_actors",
        "authority_grants",
        "authority_receipts",
        "authority_trust_roots",
    )
    connection = store._connection
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        for table in order:
            for statement in inserts.get(table, ()):
                connection.execute(statement)
        connection.commit()
    finally:
        connection.execute("PRAGMA foreign_keys = ON")
    store.verify_integrity()
