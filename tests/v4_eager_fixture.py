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
    snapshot_digest,
)
from loop_architect.v4_alpha.vertical import vertical_commands


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v4_0_eager" / "eager-store.json"
FIXTURE_SHA256 = "3d28e26dddc861115437ea1231d36f747e2f01d8c58e443bcfdb31efca3586e8"
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
    policy = fixture.get("policy_checkpoint")
    public = fixture.get("public_start_checkpoint")
    eager_plan = fixture.get("eager_plan_checkpoint")
    if (
        not isinstance(policy, dict)
        or policy.get("base_checkpoint_snapshot_digest")
        != fixture["checkpoint_snapshot_digest"]
        or policy.get("checkpoint_loop_revision") != 6
        or snapshot_digest(policy.get("checkpoint_snapshot", {}))
        != policy.get("checkpoint_snapshot_digest")
        or policy.get("operation_command", {}).get("command_type")
        != "RecordPolicyDecision"
        or "policy" not in policy.get("checkpoint_snapshot", {})
        or not isinstance(public, dict)
        or public.get("schema")
        != "loopskill-v4.0.0-public-start-fixture-v1"
        or public.get("checkpoint_loop_revision") != 1
        or not isinstance(public.get("sqlite_logical_dump"), str)
        or not isinstance(eager_plan, dict)
        or eager_plan.get("schema")
        != "loopskill-v4.0.0-public-eager-plan-fixture-v1"
        or eager_plan.get("checkpoint_loop_revision") != 1
        or snapshot_digest(eager_plan.get("checkpoint_snapshot", {}))
        != eager_plan.get("checkpoint_snapshot_digest")
        or eager_plan.get("checkpoint_snapshot", {}).get("goal_plan", {}).get(
            "storage_mode"
        )
        is not None
    ):
        raise RuntimeError("EAGER_V4_0_FIXTURE_VARIANT_DRIFT")
    expected = tuple(
        canonical_bytes(value) for value in fixture["continuation_commands"]
    )
    actual = tuple(
        canonical_bytes(command.__dict__) for command in vertical_commands()[5:]
    )
    if actual != expected:
        raise RuntimeError("EAGER_V4_0_CONTINUATION_DRIFT")
    return fixture


def eager_authority(*, policy: bool = False) -> AuthorityContext:
    value = eager_fixture()["authority"]
    grants = {}
    items = list(value["grants"])
    if policy:
        items.append(eager_fixture()["policy_checkpoint"]["authority_grant"])
    for item in items:
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


def eager_continuation_commands(*, policy: bool = False) -> tuple[CommandEnvelope, ...]:
    key = "policy_checkpoint" if policy else None
    values = (
        eager_fixture()[key]["continuation_commands"]
        if key is not None
        else eager_fixture()["continuation_commands"]
    )
    return tuple(
        CommandEnvelope(**value)
        for value in values
    )


def seed_eager_memory(store, *, policy: bool = False) -> None:
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
    if policy:
        variant = eager_fixture()["policy_checkpoint"]
        command = variant["operation_command"]
        outcome = variant["operation_result"]
        if command["authority_grant_ref"] not in store.authority.grants:
            raise ValueError("policy fixture authority is absent")
        loop_ref = str(command["subject"]["loop_ref"])
        store._snapshots[loop_ref] = parse_json_bytes(
            canonical_bytes(variant["checkpoint_snapshot"])
        )
        store._events.setdefault(loop_ref, []).append(
            parse_json_bytes(canonical_bytes(variant["operation_event"]))
        )
        store._accepted[(loop_ref, str(command["operation_id"]))] = (
            str(command["request_digest"]),
            ApplyResult(
                operation_id=str(outcome["operation_id"]),
                loop_ref=str(outcome["loop_ref"]),
                loop_revision=int(outcome["loop_revision"]),
                event_types=tuple(outcome["event_types"]),
                response=dict(outcome["response"]),
                snapshot_digest=str(outcome["snapshot_digest"]),
            ),
        )
        store.commit_count += 1
    store.verify_integrity()


def seed_eager_sqlite(store, *, policy: bool = False) -> None:
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
        if policy:
            variant = fixture["policy_checkpoint"]
            grant = variant["authority_grant"]
            command = variant["operation_command"]
            outcome = {
                key: value
                for key, value in variant["operation_result"].items()
                if key != "replayed"
            }
            event = variant["operation_event"]
            if grant["grant_ref"] not in store.authority.grants:
                raise ValueError("policy fixture authority is absent")
            connection.execute(
                "INSERT INTO authority_grants(grant_ref, loop_ref, grant_json) "
                "VALUES (?, ?, ?)",
                (
                    grant["grant_ref"],
                    command["subject"]["loop_ref"],
                    canonical_bytes(grant),
                ),
            )
            connection.execute(
                "UPDATE loops SET loop_revision = ?, snapshot_json = ?, "
                "snapshot_digest = ? WHERE loop_ref = ?",
                (
                    variant["checkpoint_loop_revision"],
                    canonical_bytes(variant["checkpoint_snapshot"]),
                    variant["checkpoint_snapshot_digest"],
                    command["subject"]["loop_ref"],
                ),
            )
            connection.execute(
                "INSERT INTO operations(loop_ref, operation_id, request_digest, "
                "accepted, outcome_json) VALUES (?, ?, ?, 1, ?)",
                (
                    command["subject"]["loop_ref"],
                    command["operation_id"],
                    command["request_digest"],
                    canonical_bytes(outcome),
                ),
            )
            connection.execute(
                "INSERT INTO events(loop_ref, sequence, operation_id, event_type, "
                "event_json) VALUES (?, ?, ?, ?, ?)",
                (
                    command["subject"]["loop_ref"],
                    event["sequence"],
                    command["operation_id"],
                    event["type"],
                    canonical_bytes(event),
                ),
            )
        connection.commit()
    finally:
        connection.execute("PRAGMA foreign_keys = ON")
    store.verify_integrity()
