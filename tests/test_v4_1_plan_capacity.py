import importlib.machinery
import importlib.util
import hashlib
import json
import os
import random
import sqlite3
import stat
import subprocess
import tempfile
import time
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "codex-loop-prompt-architect" / "scripts"
import sys

sys.path.insert(0, str(SCRIPTS))

from loop_architect.v4_adapters.codex.adapter import HOST_SCHEMA_VERSION  # noqa: E402
from loop_architect.v4_alpha.generated_protocol import (  # noqa: E402
    CAPACITY_CONTRACT,
    PROTOCOL_VERSION,
    ActorRef,
    AuthorityGrant,
    AuthorityGrantV2,
    CommandEnvelope,
    LoopIntakeInput,
    Receipt,
)
from loop_architect.v4_alpha.kernel import (  # noqa: E402
    AuthorityContext,
    validate_authority,
)
from loop_architect.v4_alpha.plan_codec import (  # noqa: E402
    PlanCodecError,
    canonicalize_plan,
    compile_plan,
    content_create_command,
    goal_chain,
    materialize_provider_request,
    max_collection_members,
    parse_plan_bytes,
    validate_plan_index,
)
from loop_architect.v4_alpha.protocol import (  # noqa: E402
    InjectedCrash,
    ProtocolRejection,
    authority_grant_digest,
    canonical_bytes,
    command_without_digest,
    domain_digest,
    raw_domain_digest,
    result_payload_schema,
    snapshot_digest,
    with_command_change,
)
from loop_architect.v4_alpha.store import InMemoryStore  # noqa: E402
from loop_architect.v4_entry import (  # noqa: E402
    ConversationIntakeError,
    ConversationIntakeSession,
    accepts_conversation_confirmation,
    confirm_loop,
    policy_view,
    prepare_loop,
    revise_goal_plan,
    start_loop,
    status,
    sync_loop,
)
from loop_architect.v4_entry.preparation import _capacity_report  # noqa: E402
from loop_architect.v4_entry.service import (  # noqa: E402
    EntryError,
    LOCAL_ARTIFACT_ISSUER,
    LOCAL_ARTIFACT_TRUST,
    STORE_FILENAME,
    _machine_bootstrap,
    _machine_command,
    _with_receipt,
)
from loop_architect.v4_operability.projections import privacy_export  # noqa: E402
from loop_architect.v4_persistence.sqlite_store import SQLiteStore  # noqa: E402
from loop_architect.v4_alpha.vertical import (  # noqa: E402
    fixture_authority,
    vertical_commands,
)


NOW = datetime(2026, 7, 30, 1, 0, 0, tzinfo=timezone.utc)


def canonical_plan(goal_count=2, *, acceptance="machine evidence", mode="ADAPTIVE"):
    goals = [
        {
            "acceptance_criteria": [acceptance],
            "goal_id": f"g{index:03d}",
            "objective": f"goal {index:03d}",
        }
        for index in range(goal_count)
    ]
    return {
        "boundaries": {
            "destructive_actions_allowed": False,
            "external_actions": [],
            "forbidden_actions": ["deploy"],
            "forbidden_paths": [],
            "write_scope": ["workspace/"],
        },
        "budget": {
            "currency": None,
            "max_cost_minor_units": 0,
            "max_host_invocations": goal_count,
            "wall_clock_seconds": 3600,
        },
        "completion_evidence": ["all Goal evidence passes"],
        "goals": goals,
        "objective": goals[0]["objective"],
        "roadmap_policy": {
            "max_reorders": 4 if mode == "ADAPTIVE" else 0,
            "mode": mode,
        },
        "schema": "loopskill-plan-v1",
        "source": {
            "kind": "canonical_plan_json",
            "source_content_retained": False,
            "source_digest": "a" * 64,
        },
        "stop_conditions": ["unknown external state"],
    }


def canonical_request(goal_count=2, *, acceptance="machine evidence", mode="ADAPTIVE"):
    plan = canonical_plan(goal_count, acceptance=acceptance, mode=mode)
    return LoopIntakeInput(
        goal=plan["objective"],
        goal_plan=tuple(goal["objective"] for goal in plan["goals"]),
        task_horizon=mode.lower(),
        write_scope=("workspace/",),
        budget="canonical structured budget",
        external_actions=(),
        acceptance_criteria=("all Goal evidence passes",),
        stop_conditions=("unknown external state",),
        authorization_boundaries=("deploy",),
        canonical_plan=plan,
        source_kind="canonical_plan_json",
        source_digest=str(plan["source"]["source_digest"]),
        source_bytes=len(canonical_bytes(plan)),
    )


def pure_content_ready_to_advance(prepared):
    loop_ref, authority, create = _machine_bootstrap(
        prepared,
        now=NOW,
        receipt_trust_roots={"v4.1-test-host": "strict-test-host"},
        artifact_profile="non_git",
        artifact_baseline_blob_digest="c" * 64,
        workspace_identity_digest=prepared.manifest.workspace_identity_digest,
    )
    store = InMemoryStore(authority)
    store.put_blob(canonical_bytes(prepared.plan))
    store.put_blob(canonical_bytes(prepared.plan_index))
    store.apply(create)
    snapshot = store.snapshot(loop_ref)
    assert snapshot is not None
    goal_ref, goal = next(iter(snapshot["goals"].items()))
    chain = goal["chain_refs"]
    attempt_ref = chain["attempt_ref"]
    effect_ref = chain["external_effect_ref"]
    attempt = snapshot["attempts"][attempt_ref]
    observation = Receipt(
        receipt_ref="receipt-test-host-observation",
        issuer_ref="v4.1-test-host",
        issuer_trust="strict-test-host",
        trust_class="strict",
        action="create_task",
        loop_ref=loop_ref,
        subject_ref=effect_ref,
        attempt_ref=attempt_ref,
        target_ref=attempt["target_ref"],
        request_digest=attempt["provider_request_digest"],
        provider_idempotency_key=attempt["provider_idempotency_key"],
        provider_resource_ref="test-provider-task",
        outcome="observed",
        issued_at=NOW.isoformat().replace("+00:00", "Z"),
        expires_at=(NOW + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        evidence_digest="e" * 64,
    )
    _with_receipt(store, observation)
    store.apply(
        _machine_command(
            store,
            snapshot,
            command_type="RecordExternalEffectObservation",
            operation_label="pure-observe",
            subject_kind="ExternalEffectRef",
            subject_ref=effect_ref,
            expected_subject_revisions={effect_ref: 1, attempt_ref: 1},
            machine_bindings={
                "allocate_refs": {},
                "receipt_refs": {"receipt": observation.receipt_ref},
                "resolved_refs": {},
            },
            semantic_payload={},
            clock=lambda: NOW,
        )
    )
    snapshot = store.snapshot(loop_ref)
    assert snapshot is not None
    store.apply(
        _machine_command(
            store,
            snapshot,
            command_type="StageExternalResult",
            operation_label="pure-stage",
            subject_kind="ExternalEffectRef",
            subject_ref=effect_ref,
            expected_subject_revisions={effect_ref: snapshot["external_effects"][effect_ref]["revision"]},
            machine_bindings={
                "allocate_refs": {
                    "new_report_ref": chain["report_ref"],
                    "new_result_ref": chain["result_ref"],
                },
                "receipt_refs": {},
                "resolved_refs": {"source_observation_digest": "f" * 64},
            },
            semantic_payload={"outcome": "PASS", "summary": "pure Goal complete"},
            clock=lambda: NOW,
        )
    )
    snapshot = store.snapshot(loop_ref)
    assert snapshot is not None
    verification_digest = "b" * 64
    artifact_digest = "a" * 64
    artifact_receipt = Receipt(
        receipt_ref="receipt-test-artifact",
        issuer_ref=LOCAL_ARTIFACT_ISSUER,
        issuer_trust=LOCAL_ARTIFACT_TRUST,
        trust_class="strict",
        action="verify-artifact",
        loop_ref=loop_ref,
        subject_ref=chain["artifact_ref"],
        attempt_ref=attempt_ref,
        target_ref=attempt["target_ref"],
        request_digest=verification_digest,
        provider_idempotency_key=None,
        provider_resource_ref="test-provider-task",
        outcome="observed",
        issued_at=NOW.isoformat().replace("+00:00", "Z"),
        expires_at=(NOW + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        evidence_digest=artifact_digest,
    )
    _with_receipt(store, artifact_receipt)
    store.apply(
        _machine_command(
            store,
            snapshot,
            command_type="AcknowledgeResult",
            operation_label="pure-ack",
            subject_kind="ResultRef",
            subject_ref=chain["result_ref"],
            expected_subject_revisions={chain["result_ref"]: 1, chain["report_ref"]: 1},
            machine_bindings={
                "allocate_refs": {"new_artifact_ref": chain["artifact_ref"]},
                "receipt_refs": {"receipt": artifact_receipt.receipt_ref},
                "resolved_refs": {
                    "artifact_digest": artifact_digest,
                    "artifact_profile": "non_git",
                    "capture_state": "CAPTURED",
                    "manifest_digest": "9" * 64,
                    "verification_digest": verification_digest,
                    "verification_state": "VERIFIED",
                },
            },
            semantic_payload={},
            clock=lambda: NOW,
        )
    )
    snapshot = store.snapshot(loop_ref)
    assert snapshot is not None
    store.apply(
        _machine_command(
            store,
            snapshot,
            command_type="RecordReview",
            operation_label="pure-review",
            subject_kind="ResultRef",
            subject_ref=chain["result_ref"],
            expected_subject_revisions={
                chain["artifact_ref"]: 1,
                chain["report_ref"]: 2,
                chain["result_ref"]: 2,
            },
            machine_bindings={
                "allocate_refs": {"new_review_ref": chain["review_ref"]},
                "receipt_refs": {},
                "resolved_refs": {},
            },
            semantic_payload={"verdict": "PASS"},
            clock=lambda: NOW,
        )
    )
    snapshot = store.snapshot(loop_ref)
    assert snapshot is not None
    next_goal_id = prepared.plan_index["ordered_goal_ids"][1]
    next_slice = prepared.plan_index["ordered_goal_slice_digests"][1]
    next_goal = next(
        item for item in prepared.plan["goals"] if item["goal_id"] == next_goal_id
    )
    next_chain = goal_chain(loop_ref, prepared.manifest.plan_digest, next_goal_id, next_slice)
    provider_request = materialize_provider_request(
        prepared.plan,
        prepared.plan_index,
        1,
        target_ref=next_chain["provider_target"],
        artifact_digest="d" * 64,
        prior_disposition="DONE",
    )
    advance = _machine_command(
        store,
        snapshot,
        command_type="AdvanceGoal",
        operation_label="pure-advance",
        subject_kind="GoalRef",
        subject_ref=goal_ref,
        expected_subject_revisions={goal_ref: 1, chain["review_ref"]: 1, "goal_plan": 0},
        machine_bindings={
            "allocate_refs": {
                "new_attempt_ref": next_chain["attempt_ref"],
                "new_external_effect_ref": next_chain["external_effect_ref"],
                "new_goal_ref": next_chain["goal_ref"],
                "new_host_resource_ref": next_chain["host_resource_ref"],
                "provider_idempotency_key": next_chain["provider_key"],
            },
            "receipt_refs": {},
            "resolved_refs": {
                "artifact_baseline_blob_digest": "d" * 64,
                "artifact_profile": "non_git",
                "next_goal_id": next_goal_id,
                "next_goal_slice_digest": next_slice,
                "next_objective_digest": domain_digest(
                    "loopskill-goal-objective-v1\n", next_goal["objective"]
                ),
                "plan_digest": prepared.manifest.plan_digest,
                "plan_index_digest": prepared.manifest.plan_index_digest,
                "provider_request_digest": domain_digest(
                    "loopskill-provider-request-v1\n", provider_request
                ),
                "provider_target": next_chain["provider_target"],
                "review_ref": chain["review_ref"],
                "workspace_identity_digest": prepared.manifest.workspace_identity_digest,
            },
        },
        semantic_payload={"disposition": "DONE"},
        clock=lambda: NOW,
    )
    return store, advance


class FakeProvider:
    def __init__(self):
        self.invoke_count = 0
        self.records = {}

    def capability_snapshot(self):
        from loop_architect.v4_alpha.protocol import CAPABILITY_NAMES

        return {
            "capabilities": [
                {
                    "assurance": "STRICT",
                    "availability": "AVAILABLE",
                    "details": {
                        "expires_at": (NOW + timedelta(minutes=5)).isoformat().replace(
                            "+00:00", "Z"
                        ),
                        "identity_ref": "synthetic-" + name,
                        "issuer_ref": "loopskill-codex-adapter-v1",
                        "issuer_trust": "local-codex-adapter",
                        "observed_at": (NOW - timedelta(seconds=1)).isoformat().replace(
                            "+00:00", "Z"
                        ),
                        "source": "v4.1-test-provider",
                    },
                    "name": name,
                    "receipt_ref": "capability-" + name,
                }
                for name in CAPABILITY_NAMES
            ],
            "schema_version": HOST_SCHEMA_VERSION,
        }

    def invoke(self, action, payload, provider_idempotency_key):
        self.invoke_count += 1
        value = {
            "action": action,
            "idempotency_key": provider_idempotency_key,
            "provider_id": "synthetic-task-" + str(self.invoke_count),
            "schema_version": HOST_SCHEMA_VERSION,
            "status": "OBSERVED",
            "subject_id": payload["target_ref"],
            "trust": "authoritative",
        }
        self.records[provider_idempotency_key] = value
        return {**value, "status": "ACCEPTED", "trust": "cooperative"}

    def readback(self, action, provider_idempotency_key):
        return self.records.get(provider_idempotency_key)

    def read_resource(self, resource_kind, provider_id):
        return {
            "provider_id": provider_id,
            "resource_kind": resource_kind,
            "schema_version": HOST_SCHEMA_VERSION,
            "state": "TERMINAL",
            "trust": "authoritative",
        }

    def read_task_result(self, provider_id):
        result = {"outcome": "PASS", "summary": "synthetic Goal completed"}
        schema_digest = domain_digest(
            "loopskill-codex-result-schema-v1\n", result_payload_schema()
        )
        return {
            "provider_id": provider_id,
            "result": result,
            "result_digest": domain_digest(
                "loopskill-host-result-v1\n",
                {"result": result, "result_schema_digest": schema_digest},
            ),
            "result_schema_digest": schema_digest,
            "schema_version": HOST_SCHEMA_VERSION,
            "status": "COMPLETED",
            "trust": "authoritative",
        }


def load_cli():
    path = SCRIPTS / "loopskill4"
    loader = importlib.machinery.SourceFileLoader("loopskill4_v41_tests", str(path))
    specification = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(specification)
    loader.exec_module(module)
    return module


class V41PlanCapacityTests(unittest.TestCase):
    def test_manifest_generated_identity_and_capacity_contract(self):
        self.assertEqual(PROTOCOL_VERSION, "4.1.0")
        self.assertEqual(CAPACITY_CONTRACT["goal_count_max"], 32)
        fixture = json.loads(
            (ROOT / "protocol/v4/generated/identity-fixtures.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(fixture["protocol_version"], "4.1.0")
        self.assertEqual(
            fixture["plan_digest"],
            domain_digest("loopskill-blob-v1\n", fixture["plan_document"]),
        )

    def test_pure_kernel_two_goal_activation_is_atomic_bounded_and_replay_safe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            prepared = confirm_loop(
                prepare_loop(
                    canonical_request(
                        2, acceptance="no-file-change", mode="STANDARD"
                    ),
                    root / "prepared",
                    clock=lambda: NOW,
                    token_factory=lambda: "0" * 24,
                    workspace_root=workspace,
                ).directory,
                confirmed=True,
                clock=lambda: NOW,
            )
            store, advance = pure_content_ready_to_advance(prepared)
            before = store.snapshot(prepared.manifest.loop_ref)
            self.assertEqual(len(before["goals"]), 1)
            self.assertEqual(len(before["attempts"]), 1)

            def invalid_variant(label, field, value):
                def change(values):
                    values["operation_id"] = "operation-negative-" + label
                    bindings = {
                        name: dict(items)
                        for name, items in values["machine_bindings"].items()
                    }
                    bindings["resolved_refs"][field] = value
                    values["machine_bindings"] = bindings

                return with_command_change(advance, change)

            for label, field, value in (
                ("slice", "next_goal_slice_digest", "1" * 64),
                ("skip", "next_goal_id", "g999"),
                ("plan", "plan_digest", "2" * 64),
            ):
                with self.subTest(label=label), self.assertRaises(
                    ProtocolRejection
                ):
                    store.apply(invalid_variant(label, field, value))
                self.assertEqual(len(store.snapshot(prepared.manifest.loop_ref)["attempts"]), 1)

            committed = store.apply(advance)
            snapshot = store.snapshot(prepared.manifest.loop_ref)
            self.assertEqual(
                committed.event_types,
                ("GoalAdvanced", "GoalRegistered", "GoalActivated", "ExternalEffectPrepared"),
            )
            self.assertEqual(len(snapshot["goals"]), 2)
            self.assertEqual(len(snapshot["attempts"]), 2)
            self.assertEqual(
                sum(goal["state"] == "ACTIVE" for goal in snapshot["goals"].values()),
                1,
            )
            self.assertTrue(store.apply(advance).replayed)
            self.assertEqual(len(store.snapshot(prepared.manifest.loop_ref)["attempts"]), 2)

            conflicting = with_command_change(
                advance,
                lambda values: values.update(
                    semantic_payload={"disposition": "FAILED"}
                ),
            )
            with self.assertRaises(ProtocolRejection) as conflict:
                store.apply(conflicting)
            self.assertEqual(conflict.exception.code, "IDEMPOTENCY_CONFLICT")

            stale = with_command_change(
                advance,
                lambda values: values.update(operation_id="operation-stale-advance"),
            )
            with self.assertRaises(ProtocolRejection) as rejected:
                store.apply(stale)
            self.assertEqual(rejected.exception.code, "STALE_LOOP_REVISION")
            store.verify_integrity()

    def test_advance_goal_rejects_cross_goal_review_and_inactive_subject(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            prepared = confirm_loop(
                prepare_loop(
                    canonical_request(2, mode="STANDARD"),
                    root / "prepared",
                    clock=lambda: NOW,
                    token_factory=lambda: "2" * 24,
                    workspace_root=workspace,
                ).directory,
                confirmed=True,
                clock=lambda: NOW,
            )
            store, first_advance = pure_content_ready_to_advance(prepared)
            first_goal_ref = str(first_advance.subject["subject_ref"])
            first_review_ref = first_advance.machine_bindings["resolved_refs"][
                "review_ref"
            ]
            store.apply(first_advance)
            snapshot = store.snapshot(prepared.manifest.loop_ref)
            second_goal_ref = snapshot["goal_plan"]["active_goal_ref"]
            first_result = snapshot["results"][
                snapshot["reviews"][first_review_ref]["result_ref"]
            ]
            self.assertEqual(first_result["goal_ref"], first_goal_ref)
            self.assertNotEqual(first_result["goal_ref"], second_goal_ref)

            def forged_advance(subject_ref, operation_label):
                current = store.snapshot(prepared.manifest.loop_ref)
                return _machine_command(
                    store,
                    current,
                    command_type="AdvanceGoal",
                    operation_label=operation_label,
                    subject_kind="GoalRef",
                    subject_ref=subject_ref,
                    expected_subject_revisions={
                        subject_ref: current["goals"][subject_ref]["revision"],
                        first_review_ref: current["reviews"][first_review_ref][
                            "revision"
                        ],
                        "goal_plan": current["goal_plan"]["revision"],
                    },
                    machine_bindings={
                        "allocate_refs": {},
                        "receipt_refs": {},
                        "resolved_refs": {"review_ref": first_review_ref},
                    },
                    semantic_payload={"disposition": "DONE"},
                    clock=lambda: NOW,
                )

            before_cross_goal = store.snapshot(prepared.manifest.loop_ref)
            with self.assertRaises(ProtocolRejection) as cross_goal:
                store.apply(
                    forged_advance(second_goal_ref, "cross-goal-review-forgery")
                )
            self.assertEqual(cross_goal.exception.code, "INVALID_TRANSITION")
            self.assertEqual(
                cross_goal.exception.detail,
                "Review Result does not bind the subject Goal",
            )
            self.assertEqual(
                store.snapshot(prepared.manifest.loop_ref), before_cross_goal
            )
            self.assertEqual(
                before_cross_goal["goals"][second_goal_ref]["state"], "ACTIVE"
            )

            with self.assertRaises(ProtocolRejection) as inactive:
                store.apply(
                    forged_advance(first_goal_ref, "inactive-goal-review-replay")
                )
            self.assertEqual(inactive.exception.code, "INVALID_TRANSITION")
            self.assertEqual(inactive.exception.detail, "Goal is not active")
            self.assertEqual(
                store.snapshot(prepared.manifest.loop_ref), before_cross_goal
            )
            store.verify_integrity()

    def test_authority_selector_binds_plan_namespace_kind_and_slice(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            prepared = confirm_loop(
                prepare_loop(
                    canonical_request(2, mode="STANDARD"),
                    root / "prepared",
                    clock=lambda: NOW,
                    token_factory=lambda: "3" * 24,
                    workspace_root=workspace,
                ).directory,
                confirmed=True,
                clock=lambda: NOW,
            )
            loop_ref, authority, create = _machine_bootstrap(
                prepared, now=NOW, receipt_trust_roots={}
            )
            self.assertEqual(len(authority.grants), 7)
            self.assertTrue(
                all(isinstance(grant, AuthorityGrantV2) for grant in authority.grants.values())
            )
            self.assertTrue(
                all(
                    set(grant.subject_selector)
                    == {
                        "goal_index_max",
                        "goal_index_min",
                        "include_loop_scope",
                        "mode",
                        "plan_digest",
                    }
                    for grant in authority.grants.values()
                )
            )
            with self.assertRaises(TypeError):
                AuthorityGrantV2(**{**next(iter(authority.grants.values())).__dict__, "exact_subjects": ()})

            store = InMemoryStore(authority)
            store.put_blob(canonical_bytes(prepared.plan))
            store.put_blob(canonical_bytes(prepared.plan_index))
            store.apply(create)
            snapshot = store.snapshot(loop_ref)
            goal = next(iter(snapshot["goals"].values()))
            pause = _machine_command(
                store,
                snapshot,
                command_type="PauseLoop",
                operation_label="selector-positive",
                subject_kind="LoopRef",
                subject_ref=loop_ref,
                expected_subject_revisions={},
                machine_bindings={
                    "allocate_refs": {},
                    "receipt_refs": {},
                    "resolved_refs": {},
                },
                semantic_payload={"reason": "selector test"},
                clock=lambda: NOW,
            )
            validate_authority(pause, authority, snapshot)

            wrong_slice_ref = goal_chain(
                loop_ref,
                prepared.manifest.plan_digest,
                goal["goal_id"],
                "4" * 64,
            )["goal_ref"]
            wrong_slice = with_command_change(
                pause,
                lambda values: values.update(
                    operation_id="operation-selector-wrong-slice",
                    subject={
                        "loop_ref": loop_ref,
                        "subject_kind": "GoalRef",
                        "subject_ref": wrong_slice_ref,
                    },
                ),
            )
            with self.assertRaises(ProtocolRejection) as rejected:
                validate_authority(wrong_slice, authority, snapshot)
            self.assertEqual(rejected.exception.code, "AUTHORITY_SCOPE_MISMATCH")

            lifecycle_ref, lifecycle = next(
                (reference, grant)
                for reference, grant in authority.grants.items()
                if "PauseLoop" in grant.allowed_commands
            )
            changed = replace(
                lifecycle,
                subject_selector={
                    **lifecycle.subject_selector,
                    "plan_digest": "5" * 64,
                },
                canonical_digest="",
            )
            changed = replace(changed, canonical_digest=authority_grant_digest(changed))
            wrong_plan_authority = AuthorityContext(
                actors=authority.actors,
                grants={**authority.grants, lifecycle_ref: changed},
                receipts=authority.receipts,
                trusted_actor_issuers=authority.trusted_actor_issuers,
                trusted_grant_issuers=authority.trusted_grant_issuers,
                trusted_receipt_issuers=authority.trusted_receipt_issuers,
            )
            with self.assertRaises(ProtocolRejection) as rejected:
                validate_authority(pause, wrong_plan_authority, snapshot)
            self.assertEqual(rejected.exception.code, "AUTHORITY_SCOPE_MISMATCH")

            actor = authority.actors[pause.actor_ref]
            wrong_namespace_authority = AuthorityContext(
                actors={
                    **authority.actors,
                    pause.actor_ref: replace(actor, loop_namespace="loop-" + "6" * 24),
                },
                grants=authority.grants,
                receipts=authority.receipts,
                trusted_actor_issuers=authority.trusted_actor_issuers,
                trusted_grant_issuers=authority.trusted_grant_issuers,
                trusted_receipt_issuers=authority.trusted_receipt_issuers,
            )
            with self.assertRaises(ProtocolRejection) as rejected:
                validate_authority(pause, wrong_namespace_authority, snapshot)
            self.assertEqual(rejected.exception.code, "AUTHORITY_SCOPE_MISMATCH")

    def test_blob_write_crash_missing_tamper_and_orphan_are_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            prepared = confirm_loop(
                prepare_loop(
                    canonical_request(2, mode="STANDARD"),
                    root / "prepared-crash",
                    clock=lambda: NOW,
                    token_factory=lambda: "4" * 24,
                    workspace_root=workspace,
                ).directory,
                confirmed=True,
                clock=lambda: NOW,
            )
            original_apply = SQLiteStore.apply

            def crash_before_create(store, command, *args, **kwargs):
                if command.command_type == "CreateLoop":
                    raise InjectedCrash("after blobs before CreateLoop")
                return original_apply(store, command, *args, **kwargs)

            data = root / "crash-data"
            with mock.patch.object(SQLiteStore, "apply", crash_before_create):
                with self.assertRaises(InjectedCrash):
                    start_loop(
                        prepared,
                        root=data,
                        clock=lambda: NOW,
                        workspace_root=workspace,
                    )
            with SQLiteStore(data / STORE_FILENAME) as store:
                self.assertEqual(store.loop_descriptors(), [])
                self.assertEqual(
                    store.get_blob(prepared.manifest.plan_digest),
                    canonical_bytes(prepared.plan),
                )
                self.assertEqual(
                    store.get_blob(prepared.manifest.plan_index_digest),
                    canonical_bytes(prepared.plan_index),
                )
                orphan = store.put_blob(b"allowed unreachable orphan")
                self.assertEqual(store.get_blob(orphan), b"allowed unreachable orphan")
                store.verify_integrity()
            start_loop(
                prepared,
                root=data,
                clock=lambda: NOW,
                workspace_root=workspace,
            )
            with SQLiteStore(data / STORE_FILENAME) as store:
                snapshot = store.snapshot(prepared.manifest.loop_ref)
                self.assertEqual(len(snapshot["attempts"]), 1)

            for case in ("missing", "tampered"):
                with self.subTest(case=case):
                    case_root = root / case
                    case_workspace = case_root / "workspace"
                    case_workspace.mkdir(parents=True)
                    candidate = confirm_loop(
                        prepare_loop(
                            canonical_request(1, mode="STANDARD"),
                            case_root / "prepared",
                            clock=lambda: NOW,
                            token_factory=lambda case=case: ("7" if case == "missing" else "8") * 24,
                            workspace_root=case_workspace,
                        ).directory,
                        confirmed=True,
                        clock=lambda: NOW,
                    )
                    case_data = case_root / "data"
                    start_loop(
                        candidate,
                        root=case_data,
                        clock=lambda: NOW,
                        workspace_root=case_workspace,
                    )
                    with SQLiteStore(case_data / STORE_FILENAME) as store:
                        if case == "missing":
                            store._connection.execute(
                                "DELETE FROM immutable_blobs WHERE blob_digest = ?",
                                (candidate.manifest.plan_digest,),
                            )
                        else:
                            store._connection.execute(
                                "UPDATE immutable_blobs SET content = ?, content_bytes = ? WHERE blob_digest = ?",
                                (b"tampered", 8, candidate.manifest.plan_digest),
                            )
                        store._connection.commit()
                    provider = FakeProvider()
                    with self.assertRaises(EntryError) as blocked:
                        start_loop(
                            candidate,
                            root=case_data,
                            clock=lambda: NOW,
                            host_provider=provider,
                            workspace_root=case_workspace,
                        )
                    self.assertEqual(blocked.exception.code, "STORE_RECOVERY_REQUIRED")
                    self.assertEqual(provider.invoke_count, 0)

    def test_two_process_advance_goal_has_one_cas_winner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            prepared = confirm_loop(
                prepare_loop(
                    canonical_request(
                        2, acceptance="no-file-change", mode="STANDARD"
                    ),
                    root / "prepared",
                    clock=lambda: NOW,
                    token_factory=lambda: "5" * 24,
                    workspace_root=workspace,
                ).directory,
                confirmed=True,
                clock=lambda: NOW,
            )
            provider = FakeProvider()
            data = root / "data"
            start_loop(
                prepared,
                root=data,
                clock=lambda: NOW,
                host_provider=provider,
                workspace_root=workspace,
            )
            captured = []
            original_apply = SQLiteStore.apply

            def capture_before_advance(store, command, *args, **kwargs):
                if command.command_type == "AdvanceGoal":
                    captured.append(command)
                    raise InjectedCrash("before concurrent AdvanceGoal")
                return original_apply(store, command, *args, **kwargs)

            with mock.patch.object(SQLiteStore, "apply", capture_before_advance):
                with self.assertRaises(InjectedCrash):
                    sync_loop(
                        root=data,
                        host_provider=provider,
                        clock=lambda: NOW,
                        workspace_root=workspace,
                    )
            self.assertEqual(len(captured), 1)
            first = captured[0]
            second = with_command_change(
                first,
                lambda values: values.update(operation_id="operation-concurrent-peer"),
            )
            command_paths = []
            for index, command in enumerate((first, second)):
                path = root / f"command-{index}.json"
                path.write_bytes(canonical_bytes(command.__dict__))
                command_paths.append(path)
            gate = root / "start-gate"
            ready_paths = [root / "ready-0", root / "ready-1"]
            child = """
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from loop_architect.v4_alpha.generated_protocol import CommandEnvelope
from loop_architect.v4_alpha.protocol import ProtocolRejection
from loop_architect.v4_persistence.sqlite_store import SQLiteStore
command = CommandEnvelope(**json.loads(Path(sys.argv[3]).read_text(encoding='utf-8')))
Path(sys.argv[4]).write_text('ready', encoding='utf-8')
deadline = time.monotonic() + 10
while not Path(sys.argv[5]).exists():
    if time.monotonic() > deadline:
        raise SystemExit('gate timeout')
    time.sleep(0.005)
try:
    with SQLiteStore(Path(sys.argv[2])) as store:
        result = store.apply(command)
    print('ACCEPTED' if not result.replayed else 'REPLAYED')
except ProtocolRejection as exc:
    print('REJECTED:' + exc.code)
"""
            processes = [
                subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        child,
                        str(SCRIPTS),
                        str(data / STORE_FILENAME),
                        str(command_paths[index]),
                        str(ready_paths[index]),
                        str(gate),
                    ],
                    cwd=ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for index in range(2)
            ]
            deadline = time.monotonic() + 10
            while not all(path.exists() for path in ready_paths):
                if time.monotonic() > deadline:
                    for process in processes:
                        process.kill()
                    self.fail("concurrent workers did not reach the gate")
                time.sleep(0.005)
            gate.write_text("start", encoding="utf-8")
            outputs = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=15)
                self.assertEqual(process.returncode, 0, stderr)
                outputs.append(stdout.strip())
            self.assertEqual(outputs.count("ACCEPTED"), 1, outputs)
            self.assertEqual(outputs.count("REJECTED:STALE_LOOP_REVISION"), 1, outputs)
            self.assertEqual(provider.invoke_count, 1)
            with SQLiteStore(data / STORE_FILENAME) as store:
                snapshot = store.snapshot(prepared.manifest.loop_ref)
                self.assertEqual(len(snapshot["goals"]), 2)
                self.assertEqual(len(snapshot["attempts"]), 2)
                self.assertEqual(
                    sum(goal["state"] == "ACTIVE" for goal in snapshot["goals"].values()),
                    1,
                )
                accepted = store._connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id IN (?, ?) AND accepted = 1",
                    (first.operation_id, second.operation_id),
                ).fetchone()[0]
                self.assertEqual(accepted, 1)
                store.verify_integrity()

    def test_plan_codec_normalizes_and_rejects_noncanonical_inputs(self):
        value = canonical_plan(1)
        value["goals"][0]["objective"] = "e\u0301\r\nGoal"
        value["objective"] = "e\u0301\r\nGoal"
        request = replace(
            canonical_request(1),
            canonical_plan=value,
            goal=value["objective"],
            goal_plan=(value["objective"],),
        )
        compiled = compile_plan(
            request, loop_ref="loop-" + "1" * 24, workspace_binding="2" * 64
        )
        self.assertEqual(compiled.plan["objective"], "é\nGoal")
        self.assertEqual(parse_plan_bytes(compiled.plan_bytes), compiled.plan)
        with self.assertRaises(PlanCodecError):
            parse_plan_bytes(b'{"schema":"x","schema":"y"}')
        broken = canonical_plan(1)
        broken["objective"] = "bad\x00value"
        broken["goals"][0]["objective"] = "bad\x00value"
        with self.assertRaises(PlanCodecError):
            compile_plan(
                replace(canonical_request(1), canonical_plan=broken),
                loop_ref="loop-" + "1" * 24,
                workspace_binding="2" * 64,
            )

    def test_plan_codec_golden_equivalence_and_bounded_property_fuzz(self):
        decomposed = canonical_plan(2, mode="STANDARD")
        decomposed["objective"] = "e\u0301\r\nresult"
        decomposed["goals"][0]["objective"] = "e\u0301\r\nresult"
        normalized = canonical_plan(2, mode="STANDARD")
        normalized["objective"] = "é\nresult"
        normalized["goals"][0]["objective"] = "é\nresult"
        first = compile_plan(
            replace(canonical_request(2, mode="STANDARD"), canonical_plan=decomposed),
            loop_ref="loop-" + "a" * 24,
            workspace_binding="b" * 64,
        )
        second = compile_plan(
            replace(canonical_request(2, mode="STANDARD"), canonical_plan=normalized),
            loop_ref="loop-" + "a" * 24,
            workspace_binding="b" * 64,
        )
        self.assertEqual(first.plan_digest, second.plan_digest)
        self.assertEqual(first.index_digest, second.index_digest)

        generator = random.Random(410)
        for iteration in range(96):
            goal_count = generator.randint(1, 32)
            plan = canonical_plan(
                goal_count,
                acceptance=f"evidence-{generator.randrange(1_000_000):06d}",
                mode="STANDARD",
            )
            plan = {
                key: value
                for key, value in reversed(tuple(plan.items()))
            }
            plan["goals"] = [
                {key: value for key, value in reversed(tuple(goal.items()))}
                for goal in plan["goals"]
            ]
            compiled = compile_plan(
                replace(
                    canonical_request(goal_count, mode="STANDARD"),
                    canonical_plan=plan,
                ),
                loop_ref=f"loop-{iteration:024x}",
                workspace_binding="c" * 64,
            )
            decoded = parse_plan_bytes(compiled.plan_bytes)
            self.assertEqual(decoded, compiled.plan)
            self.assertEqual(
                parse_plan_bytes(canonical_bytes(decoded)),
                decoded,
            )
            repeated = compile_plan(
                replace(
                    canonical_request(goal_count, mode="STANDARD"),
                    canonical_plan=decoded,
                ),
                loop_ref=f"loop-{iteration:024x}",
                workspace_binding="c" * 64,
            )
            self.assertEqual(repeated.plan_digest, compiled.plan_digest)
            self.assertEqual(repeated.index_digest, compiled.index_digest)

        invalid_plans = []
        unknown = canonical_plan(1, mode="STANDARD")
        unknown["unknown"] = True
        invalid_plans.append(unknown)
        floating = canonical_plan(1, mode="STANDARD")
        floating["budget"]["wall_clock_seconds"] = 1.5
        invalid_plans.append(floating)
        too_many_items = canonical_plan(1, mode="STANDARD")
        too_many_items["goals"][0]["acceptance_criteria"] = ["x"] * 17
        invalid_plans.append(too_many_items)
        surrogate = canonical_plan(1, mode="STANDARD")
        surrogate["objective"] = "bad\ud800"
        surrogate["goals"][0]["objective"] = "bad\ud800"
        invalid_plans.append(surrogate)
        for index, plan in enumerate(invalid_plans):
            with self.subTest(index=index), self.assertRaises(PlanCodecError):
                compile_plan(
                    replace(canonical_request(1, mode="STANDARD"), canonical_plan=plan),
                    loop_ref="loop-" + "d" * 24,
                    workspace_binding="e" * 64,
                )
        for raw in (b'{"x":NaN}', b'{"x":1.0}', b'{"x":1,"x":2}'):
            with self.subTest(raw=raw), self.assertRaises(PlanCodecError):
                parse_plan_bytes(raw)

    def test_store_blob_parity_and_private_export(self):
        content = b"immutable-plan"
        memory = InMemoryStore(
            __import__(
                "loop_architect.v4_alpha.kernel", fromlist=["AuthorityContext"]
            ).AuthorityContext(actors={}, grants={}, receipts={})
        )
        digest = memory.put_blob(content)
        self.assertEqual(memory.put_blob(content), digest)
        self.assertEqual(memory.get_blob(digest), content)
        self.assertIn("content_base64", json.loads(memory.canonical_export())["blobs"][0])
        with tempfile.TemporaryDirectory() as temporary:
            with SQLiteStore(Path(temporary) / "store.sqlite3") as durable:
                self.assertEqual(durable.put_blob(content), digest)
                self.assertEqual(durable.get_blob(digest), content)
                self.assertIn(
                    "content_base64", json.loads(durable.canonical_export())["blobs"][0]
                )

    def test_capacity_corpus_and_command_growth_invariant(self):
        corpus = json.loads(
            (ROOT / "tests" / "fixtures" / "v4_1_capacity" / "corpus.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(corpus["schema"], "loopskill-v4.1-capacity-corpus-v1")
        self.assertEqual(corpus["goal_counts"], [1, 4, 8, 16, 32])
        self.assertEqual(
            corpus["admission_limits"],
            {
                "canonical_plan_max_bytes": int(
                    CAPACITY_CONTRACT["canonical_plan_max_bytes"]
                ),
                "create_loop_target_bytes": int(
                    CAPACITY_CONTRACT["create_loop_target_bytes"]
                ),
                "create_loop_target_collection_members": int(
                    CAPACITY_CONTRACT["create_loop_target_collection_members"]
                ),
                "goal_count_max": int(CAPACITY_CONTRACT["goal_count_max"]),
                "host_prompt_target_bytes": int(
                    CAPACITY_CONTRACT["host_prompt_target_bytes"]
                ),
                "source_text_max_bytes": int(
                    CAPACITY_CONTRACT["source_text_max_bytes"]
                ),
            },
        )
        self.assertEqual(
            set(corpus["negative_cases"]),
            {
                "goal_count_0",
                "goal_count_33",
                "plan_128k_plus_1",
                "source_256k_plus_1",
                "create_loop_over_8k",
                "create_loop_collection_over_64",
                "current_prompt_over_24k",
                "duplicate_goal_id",
                "tampered_slice_digest",
            },
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            reports = []
            for goal_count in corpus["goal_counts"]:
                prepared = prepare_loop(
                    canonical_request(goal_count),
                    root / f"prepared-{goal_count}",
                    clock=lambda: NOW,
                    token_factory=lambda count=goal_count: f"{count:024x}",
                    workspace_root=workspace,
                )
                reports.append(prepared.capacity_report)
                self.assertEqual(prepared.capacity_report["capacity_status"], "PASS")
                self.assertLessEqual(
                    prepared.capacity_report["create_loop_command_bytes"], 8192
                )
                self.assertLessEqual(
                    prepared.capacity_report["create_loop_max_collection_members"], 64
                )
                self.assertLessEqual(
                    prepared.capacity_report["max_materialized_goal_prompt_bytes"],
                    24576,
                )
            self.assertEqual([item["goal_count"] for item in reports], [1, 4, 8, 16, 32])

        small = compile_plan(
            canonical_request(32, acceptance="x"),
            loop_ref="loop-" + "3" * 24,
            workspace_binding="4" * 64,
        )
        large = compile_plan(
            canonical_request(32, acceptance="x" * 1024),
            loop_ref="loop-" + "3" * 24,
            workspace_binding="4" * 64,
        )
        arguments = {
            "namespace": "3" * 24,
            "loop_ref": "loop-" + "3" * 24,
            "issued_at": "2026-07-30T01:00:00Z",
            "confirmation_receipt_ref": "receipt-confirm-" + "0" * 24,
            "manifest_digest": "0" * 64,
            "boundary_digest": "0" * 64,
            "bundle_digest": "0" * 64,
            "artifact_profile": "existing_git",
            "artifact_baseline_blob_digest": "5" * 64,
        }
        small_command = content_create_command(compiled=small, **arguments)
        large_command = content_create_command(compiled=large, **arguments)
        self.assertEqual(
            len(canonical_bytes(command_without_digest(small_command))),
            len(canonical_bytes(command_without_digest(large_command))),
        )
        self.assertLessEqual(
            max_collection_members(command_without_digest(large_command)), 64
        )

    def test_capacity_corpus_missing_negative_gates_write_nothing(self):
        target = int(CAPACITY_CONTRACT["canonical_plan_max_bytes"]) + 1
        oversized_plan = canonical_plan(32, mode="STANDARD")
        added = []
        while len(canonical_bytes(oversized_plan)) < target:
            index = len(added)
            goal = oversized_plan["goals"][index % len(oversized_plan["goals"])]
            item = f"capacity-{index:03d}-" + "x" * 1000
            goal["acceptance_criteria"].append(item)
            added.append((goal, item))
        excess = len(canonical_bytes(oversized_plan)) - target
        if excess:
            goal, item = added[-1]
            self.assertLess(excess, len(item))
            goal["acceptance_criteria"][-1] = item[:-excess]
        self.assertEqual(len(canonical_bytes(oversized_plan)), target)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            plan_output = root / "plan-128k-plus-1"
            request = replace(
                canonical_request(32, mode="STANDARD"),
                canonical_plan=oversized_plan,
                source_bytes=target,
            )
            with self.assertRaises(EntryError) as plan_limit:
                prepare_loop(
                    request,
                    plan_output,
                    clock=lambda: NOW,
                    token_factory=lambda: "a" * 24,
                    workspace_root=workspace,
                )
            self.assertEqual(plan_limit.exception.code, "RESOURCE_LIMIT_EXCEEDED")
            self.assertFalse(plan_output.exists())

            original_content_create_command = content_create_command

            def fault_injected_prepare(label, semantic_payload):
                output = root / label

                def oversized_command(**kwargs):
                    command = original_content_create_command(**kwargs)
                    return with_command_change(
                        command,
                        lambda values: values.update(
                            semantic_payload=semantic_payload
                        ),
                    )

                with mock.patch(
                    "loop_architect.v4_entry.preparation.content_create_command",
                    side_effect=oversized_command,
                ):
                    with self.assertRaises(EntryError) as blocked:
                        prepare_loop(
                            canonical_request(1, mode="STANDARD"),
                            output,
                            clock=lambda: NOW,
                            token_factory=lambda: "b" * 24,
                            workspace_root=workspace,
                        )
                self.assertEqual(blocked.exception.code, "RESOURCE_LIMIT_EXCEEDED")
                self.assertFalse(output.exists())
                return blocked.exception

            command_bytes = fault_injected_prepare(
                "create-loop-over-8k",
                {f"padding-{index:02d}": "x" * 1000 for index in range(10)},
            )
            self.assertIn(
                "create_loop_target_bytes", command_bytes.view.next_action
            )
            collection_members = fault_injected_prepare(
                "create-loop-collection-over-64",
                {"members": [str(index) for index in range(65)]},
            )
            self.assertIn(
                "create_loop_target_collection_members",
                collection_members.view.next_action,
            )

    def test_installed_entry_fake_provider_matrix_is_lazy_and_exact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for goal_count in (1, 4, 8, 16, 32):
                with self.subTest(goal_count=goal_count):
                    case = root / str(goal_count)
                    workspace = case / "workspace"
                    workspace.mkdir(parents=True)
                    prepared = confirm_loop(
                        prepare_loop(
                            canonical_request(
                                goal_count,
                                acceptance="no-file-change",
                                mode="STANDARD",
                            ),
                            case / "prepared",
                            clock=lambda: NOW,
                            token_factory=lambda count=goal_count: f"{count:024x}",
                            workspace_root=workspace,
                        ).directory,
                        confirmed=True,
                        clock=lambda: NOW,
                    )
                    provider = FakeProvider()
                    start_loop(
                        prepared,
                        root=case / "data",
                        clock=lambda: NOW,
                        host_provider=provider,
                        workspace_root=workspace,
                    )
                    with SQLiteStore(case / "data" / STORE_FILENAME) as store:
                        snapshot = store.snapshot(prepared.manifest.loop_ref)
                        self.assertEqual(len(snapshot["goals"]), 1)
                        self.assertEqual(len(snapshot["attempts"]), 1)
                        self.assertEqual(snapshot["goal_plan"]["storage_mode"], "CONTENT_ADDRESSED_V1")
                        self.assertEqual(len(store.authority.grants), 7)
                    result = None
                    for _ in range(goal_count):
                        result = sync_loop(
                            root=case / "data",
                            host_provider=provider,
                            clock=lambda: NOW,
                            workspace_root=workspace,
                        )
                    self.assertEqual(result.result, "SUCCEEDED")
                    self.assertEqual(provider.invoke_count, goal_count)
                    with SQLiteStore(case / "data" / STORE_FILENAME) as store:
                        snapshot = store.snapshot(prepared.manifest.loop_ref)
                        self.assertEqual(len(snapshot["goals"]), goal_count)
                        self.assertEqual(len(snapshot["attempts"]), goal_count)
                        self.assertEqual(
                            sum(
                                attempt["state"] == "COMMITTED"
                                for attempt in snapshot["attempts"].values()
                            ),
                            0,
                        )

    def test_goal_33_and_prompt_target_fail_before_any_runtime_effect(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            with self.assertRaises(EntryError) as too_many:
                prepare_loop(
                    canonical_request(33, mode="STANDARD"),
                    root / "too-many",
                    clock=lambda: NOW,
                    token_factory=lambda: "1" * 24,
                    workspace_root=workspace,
                )
            self.assertEqual(too_many.exception.code, "RESOURCE_LIMIT_EXCEEDED")
            self.assertFalse((root / "too-many").exists())

            plan = canonical_plan(1, mode="STANDARD")
            plan["boundaries"]["write_scope"] = [
                f"scope-{index:02d}-" + "x" * 950 for index in range(32)
            ]
            request = replace(
                canonical_request(1, mode="STANDARD"),
                canonical_plan=plan,
                source_bytes=len(canonical_bytes(plan)),
            )
            compiled = compile_plan(
                request,
                loop_ref="loop-" + "2" * 24,
                workspace_binding="3" * 64,
            )
            report = _capacity_report(
                compiled,
                namespace="2" * 24,
                loop_ref="loop-" + "2" * 24,
                issued_at="2026-07-30T01:00:00Z",
                artifact_profile="non_git",
                source_bytes=request.source_bytes,
            )
            self.assertEqual(report["capacity_status"], "BLOCKED")
            self.assertIn("host_prompt_target_bytes", report["blocking_reason"])
            self.assertEqual(report["max_materialized_goal_id"], "g000")
            with self.assertRaises(EntryError) as oversized:
                prepare_loop(
                    request,
                    root / "oversized-prompt",
                    clock=lambda: NOW,
                    token_factory=lambda: "2" * 24,
                    workspace_root=workspace,
                )
            self.assertEqual(oversized.exception.code, "RESOURCE_LIMIT_EXCEEDED")
            self.assertFalse((root / "oversized-prompt").exists())

    def test_capacity_failure_writes_no_preparation_or_attempt(self):
        plan = canonical_plan(1)
        plan["boundaries"]["write_scope"] = [
            f"scope-{index:02d}-" + "x" * 950 for index in range(32)
        ]
        request = replace(
            canonical_request(1),
            canonical_plan=plan,
            source_bytes=len(canonical_bytes(plan)),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            output = root / "prepared"
            with self.assertRaises(EntryError) as raised:
                prepare_loop(
                    request,
                    output,
                    clock=lambda: NOW,
                    token_factory=lambda: "6" * 24,
                    workspace_root=workspace,
                )
            self.assertEqual(raised.exception.code, "RESOURCE_LIMIT_EXCEEDED")
            self.assertFalse(output.exists())

    def test_human_budget_compiles_to_the_displayed_canonical_contract(self):
        request = replace(
            canonical_request(2, mode="STANDARD"),
            canonical_plan=None,
            budget="最多 2 小时、最多 2 次 Host 调用、费用 0 元",
            source_kind="literal_text",
        )
        compiled = compile_plan(
            request,
            loop_ref="loop-" + "4" * 24,
            workspace_binding="5" * 64,
        )
        expected = {
            "currency": None,
            "max_cost_minor_units": 0,
            "max_host_invocations": 2,
            "wall_clock_seconds": 7200,
        }
        self.assertEqual(compiled.plan["budget"], expected)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            prepared = prepare_loop(
                request,
                root / "prepared",
                clock=lambda: NOW,
                token_factory=lambda: "5" * 24,
                workspace_root=workspace,
            )
            self.assertEqual(json.loads(prepared.manifest.budget), expected)
            self.assertEqual(prepared.boundary["budget"], prepared.manifest.budget)
        with self.assertRaises(PlanCodecError) as ambiguous_cost:
            compile_plan(
                replace(request, budget="2 hours, 2 Host calls, CNY 25"),
                loop_ref="loop-" + "4" * 24,
                workspace_binding="5" * 64,
            )
        self.assertEqual(
            ambiguous_cost.exception.reason, "structured_cost_budget_required"
        )

    def test_two_goal_lazy_activation_and_fixed_grants(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            prepared = prepare_loop(
                canonical_request(2, acceptance="no-file-change"),
                root / "prepared",
                clock=lambda: NOW,
                token_factory=lambda: "7" * 24,
                workspace_root=workspace,
            )
            prepared = confirm_loop(
                prepared.directory, confirmed=True, clock=lambda: NOW
            )
            provider = FakeProvider()
            start_loop(
                prepared,
                root=root / "data",
                clock=lambda: NOW,
                host_provider=provider,
                workspace_root=workspace,
            )
            with SQLiteStore(root / "data" / STORE_FILENAME) as store:
                snapshot = store.snapshot(prepared.manifest.loop_ref)
                self.assertEqual(len(snapshot["goals"]), 1)
                self.assertEqual(len(snapshot["attempts"]), 1)
                self.assertEqual(len(store.authority.grants), 7)
                self.assertTrue(
                    all(
                        isinstance(grant, AuthorityGrantV2)
                        for grant in store.authority.grants.values()
                    )
                )
            sync_loop(
                root=root / "data",
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=workspace,
            )
            with SQLiteStore(root / "data" / STORE_FILENAME) as store:
                snapshot = store.snapshot(prepared.manifest.loop_ref)
                self.assertEqual(len(snapshot["goals"]), 2)
                self.assertEqual(len(snapshot["attempts"]), 2)
                self.assertEqual(len(store.authority.grants), 7)
            terminal = sync_loop(
                root=root / "data",
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=workspace,
            )
            self.assertEqual(terminal.result, "SUCCEEDED")
            self.assertEqual(provider.invoke_count, 2)

    def test_start_replay_after_committed_response_loss_is_one_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            prepared = confirm_loop(
                prepare_loop(
                    canonical_request(2),
                    root / "prepared",
                    clock=lambda: NOW,
                    token_factory=lambda: "8" * 24,
                    workspace_root=workspace,
                ).directory,
                confirmed=True,
                clock=lambda: NOW,
            )
            loop_ref, authority, command = _machine_bootstrap(
                prepared,
                now=NOW,
                receipt_trust_roots={},
            )
            store = InMemoryStore(authority)
            store.put_blob(canonical_bytes(prepared.plan))
            store.put_blob(canonical_bytes(prepared.plan_index))
            with self.assertRaises(InjectedCrash):
                store.apply(command, fault_at="after_commit_before_response")
            replay = store.apply(command)
            self.assertTrue(replay.replayed)
            self.assertEqual(len(store.snapshot(loop_ref)["attempts"]), 1)
            self.assertEqual(store.commit_count, 1)

    def test_adaptive_revision_writes_new_index_and_keeps_goal_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            prepared = confirm_loop(
                prepare_loop(
                    canonical_request(3),
                    root / "prepared",
                    clock=lambda: NOW,
                    token_factory=lambda: "9" * 24,
                    workspace_root=workspace,
                ).directory,
                confirmed=True,
                clock=lambda: NOW,
            )
            start_loop(
                prepared, root=root / "data", clock=lambda: NOW, workspace_root=workspace
            )
            before = policy_view(root=root / "data")["policy"]
            revised = revise_goal_plan(
                ("goal 000", "goal 002", "goal 001"),
                root=root / "data",
                reason="dependency evidence",
                clock=lambda: NOW,
            )["policy"]
            self.assertEqual(before["revision"], 0)
            self.assertEqual(revised["revision"], 1)
            with SQLiteStore(root / "data" / STORE_FILENAME) as store:
                snapshot = store.snapshot(prepared.manifest.loop_ref)
                self.assertEqual(
                    snapshot["goal_plan"]["ordered_goal_ids"],
                    ["g000", "g002", "g001"],
                )
                self.assertIsNotNone(
                    store.get_blob(snapshot["goal_plan"]["plan_index_digest"])
                )

    def test_adaptive_reorder_keeps_completed_active_prefix_and_fixed_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            prepared = confirm_loop(
                prepare_loop(
                    canonical_request(4, acceptance="no-file-change"),
                    root / "prepared",
                    clock=lambda: NOW,
                    token_factory=lambda: "a" * 24,
                    workspace_root=workspace,
                ).directory,
                confirmed=True,
                clock=lambda: NOW,
            )
            provider = FakeProvider()
            data = root / "data"
            start_loop(
                prepared,
                root=data,
                clock=lambda: NOW,
                host_provider=provider,
                workspace_root=workspace,
            )
            sync_loop(
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=workspace,
            )
            with SQLiteStore(data / STORE_FILENAME) as store:
                grants_before = {
                    reference: grant.canonical_digest
                    for reference, grant in store.authority.grants.items()
                }
                original_index = prepared.manifest.plan_index_digest
                snapshot = store.snapshot(prepared.manifest.loop_ref)
                states = {
                    goal["goal_id"]: goal["state"]
                    for goal in snapshot["goals"].values()
                }
                self.assertEqual(states, {"g000": "DONE", "g001": "ACTIVE"})

            objectives = tuple(goal["objective"] for goal in prepared.plan["goals"])
            invalid_orders = (
                (objectives[1], objectives[0], objectives[2], objectives[3]),
                (objectives[0], objectives[2], objectives[1], objectives[3]),
                (objectives[0], objectives[1], objectives[2]),
                (objectives[0], objectives[1], objectives[2], "outside"),
                (objectives[0], objectives[1], objectives[2], objectives[2]),
            )
            for index, order in enumerate(invalid_orders):
                with self.subTest(index=index), self.assertRaises(EntryError):
                    revise_goal_plan(
                        order,
                        root=data,
                        reason="negative envelope test",
                        clock=lambda: NOW,
                    )
            orders = (
                (objectives[0], objectives[1], objectives[3], objectives[2]),
                objectives,
                (objectives[0], objectives[1], objectives[3], objectives[2]),
                objectives,
            )
            index_digests = [original_index]
            for expected_revision, order in enumerate(orders, start=1):
                projection = revise_goal_plan(
                    order,
                    root=data,
                    reason=f"bounded pending reorder {expected_revision}",
                    clock=lambda: NOW,
                )
                self.assertEqual(projection["policy"]["revision"], expected_revision)
                with SQLiteStore(data / STORE_FILENAME) as store:
                    snapshot = store.snapshot(prepared.manifest.loop_ref)
                    index_digests.append(snapshot["goal_plan"]["plan_index_digest"])
            with self.assertRaises(EntryError):
                revise_goal_plan(
                    (objectives[0], objectives[1], objectives[3], objectives[2]),
                    root=data,
                    reason="beyond confirmed reorder budget",
                    clock=lambda: NOW,
                )
            with SQLiteStore(data / STORE_FILENAME) as store:
                snapshot = store.snapshot(prepared.manifest.loop_ref)
                self.assertEqual(snapshot["goal_plan"]["revision"], 4)
                self.assertEqual(
                    {
                        reference: grant.canonical_digest
                        for reference, grant in store.authority.grants.items()
                    },
                    grants_before,
                )
                self.assertTrue(all(store.get_blob(digest) is not None for digest in index_digests))
            self.assertEqual(provider.invoke_count, 1)

    def test_closed_eager_v4_0_store_status_export_and_continuation(self):
        fixture_path = (
            ROOT / "tests" / "fixtures" / "v4_0_eager" / "eager-store.json"
        )
        fixture_raw = fixture_path.read_bytes()
        self.assertEqual(
            hashlib.sha256(fixture_raw).hexdigest(),
            "a7bd3d03529de67e0e0a336f1004ce436a544bd2405e26c867ab8d4031845a09",
        )
        fixture = json.loads(fixture_raw.decode("utf-8"))
        self.assertEqual(
            fixture["baseline_commit"],
            "f7b62cb2fd9bd6ab4b038a8384bced4b7e74cbd9",
        )
        self.assertEqual(
            fixture["baseline_tag_object"],
            "eb42b904b6973cab5ad0ed586aa4137a8c20943b",
        )
        self.assertEqual(
            fixture["schema"], "loopskill-v4.0.0-eager-store-fixture-v1"
        )
        commands = [
            CommandEnvelope(**value) for value in fixture["continuation_commands"]
        ]
        authority_value = fixture["authority"]
        grants = {}
        for value in authority_value["grants"]:
            value = dict(value)
            value["allowed_commands"] = tuple(value["allowed_commands"])
            value["subject_kinds"] = tuple(value["subject_kinds"])
            value["exact_subjects"] = tuple(value["exact_subjects"])
            grant = AuthorityGrant(**value)
            grants[grant.grant_ref] = grant
        legacy_authority = AuthorityContext(
            actors={
                value["actor_ref"]: ActorRef(**value)
                for value in authority_value["actors"]
            },
            grants=grants,
            receipts={
                value["receipt_ref"]: Receipt(**value)
                for value in authority_value["receipts"]
            },
            trusted_actor_issuers=authority_value["trusted_actor_issuers"],
            trusted_grant_issuers=authority_value["trusted_grant_issuers"],
            trusted_receipt_issuers=authority_value["trusted_receipt_issuers"],
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / STORE_FILENAME
            connection = sqlite3.connect(path)
            connection.executescript(fixture["sqlite_logical_dump"])
            connection.close()
            path.chmod(0o600)

            def schema_rows():
                readback = sqlite3.connect(path)
                try:
                    return readback.execute(
                        "SELECT type, name, tbl_name, sql FROM sqlite_master "
                        "ORDER BY type, name"
                    ).fetchall()
                finally:
                    readback.close()

            schema_before = schema_rows()
            with SQLiteStore(path) as store:
                snapshot = store.snapshot(fixture["loop_ref"])
                self.assertEqual(
                    snapshot_digest(snapshot), fixture["checkpoint_snapshot_digest"]
                )
                self.assertEqual(
                    snapshot["loop_revision"], fixture["checkpoint_loop_revision"]
                )
                self.assertNotIn("storage_mode", snapshot.get("goal_plan", {}))
                legacy_private = store.canonical_export()
                self.assertEqual(
                    hashlib.sha256(legacy_private).hexdigest(),
                    fixture["checkpoint_export_sha256"],
                )
                store.verify_integrity()
            self.assertEqual(schema_rows(), schema_before)
            view = status(root=root)
            self.assertNotEqual(view.progress, "Finished")
            public = privacy_export(legacy_private)
            self.assertNotIn("source_digest", canonical_bytes(public).decode("utf-8"))
            with SQLiteStore(path, legacy_authority) as store:
                for command in commands:
                    store.apply(command)
                store.verify_integrity()
                terminal = store.snapshot(fixture["loop_ref"])
                self.assertEqual(
                    snapshot_digest(terminal),
                    fixture["expected_terminal_snapshot_digest"],
                )
                self.assertEqual(
                    terminal["loop_revision"],
                    fixture["expected_terminal_loop_revision"],
                )
                self.assertNotIn("storage_mode", terminal.get("goal_plan", {}))
            self.assertEqual(status(root=root).result, "SUCCEEDED")
            self.assertEqual(schema_rows(), schema_before)

    def test_source_admission_and_session_only_confirmation(self):
        cli = load_cli()
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            source = root / "requirements.md"
            source.write_text("UTF-8 requirements", encoding="utf-8")
            request = cli.read_intake_input(str(source.relative_to(ROOT)))
            self.assertEqual(request.source_kind, "authorized_file")
            self.assertEqual(request.source_bytes, len(source.read_bytes()))
            link = root / "link.md"
            link.symlink_to(source.name)
            with self.assertRaises(Exception) as raised:
                cli.read_intake_input(str(link.relative_to(ROOT)))
            self.assertEqual(raised.exception.code, "PATH_CONFINEMENT_VIOLATION")
            oversized = root / "oversized.md"
            oversized.write_bytes(
                b"x" * (int(CAPACITY_CONTRACT["source_text_max_bytes"]) + 1)
            )
            with self.assertRaises(Exception) as raised:
                cli.read_intake_input(str(oversized.relative_to(ROOT)))
            self.assertEqual(raised.exception.code, "RESOURCE_LIMIT_EXCEEDED")

        session = ConversationIntakeSession()
        session.apply_candidate(
            {"result": "ship", "goals": ("ship",)},
            source_kind="literal_text",
            source_digest="a" * 64,
            source_summary="ship",
            round_number=1,
        )
        self.assertLessEqual(len(session.blocking_questions()), 3)
        with self.assertRaises(ConversationIntakeError):
            session.apply_candidate(
                {"result": "replace"},
                source_kind="literal_text",
                source_digest="b" * 64,
                source_summary="replace",
                round_number=2,
            )
        self.assertTrue(
            accepts_conversation_confirmation(
                role="user", message="START THIS LOOP", independent_message=True
            )
        )
        self.assertFalse(
            accepts_conversation_confirmation(
                role="assistant", message="START THIS LOOP", independent_message=True
            )
        )
        self.assertFalse(
            accepts_conversation_confirmation(
                role="user", message="please START THIS LOOP", independent_message=True
            )
        )

    def test_canonical_plan_source_binding_uses_exact_admitted_bytes(self):
        cli = load_cli()
        plan = canonical_plan(2, mode="STANDARD")
        plan["boundaries"]["destructive_actions_allowed"] = True
        plan["boundaries"]["forbidden_paths"] = ["secrets/"]
        plan["source"]["source_digest"] = "0" * 64
        raw = json.dumps(plan, ensure_ascii=False, indent=2).encode("utf-8")
        expected = raw_domain_digest("loopskill-prd-source-v1\n", raw)
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            source = Path(temporary) / "expert-plan.json"
            source.write_bytes(raw)
            request = cli.read_intake_input(str(source))
        self.assertEqual(request.source_kind, "canonical_plan_json")
        self.assertEqual(request.source_digest, expected)
        self.assertEqual(request.canonical_plan["source"]["kind"], request.source_kind)
        self.assertEqual(
            request.canonical_plan["source"]["source_digest"], expected
        )
        compiled = compile_plan(
            request,
            loop_ref="loop-" + "f" * 24,
            workspace_binding="e" * 64,
        )
        self.assertEqual(compiled.plan["source"]["source_digest"], expected)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            prepared = prepare_loop(
                request,
                root / "prepared",
                clock=lambda: NOW,
                token_factory=lambda: "f" * 24,
                workspace_root=workspace,
            )
            self.assertTrue(prepared.boundary["destructive_actions_allowed"])
            self.assertEqual(prepared.boundary["forbidden_paths"], ["secrets/"])
            self.assertEqual(prepared.boundary["plan_revision"], 0)
            self.assertEqual(
                prepared.boundary["workspace_identity_digest"],
                prepared.manifest.workspace_identity_digest,
            )
            card = (prepared.directory / "CONTROLLER_PLAN.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("## Forbidden paths\n\n- secrets/", card)
            self.assertIn("## Destructive actions\n\n- Allowed: true", card)
            self.assertIn("- Plan revision: `0`", card)
            self.assertIn(
                f"- Workspace identity: `{prepared.manifest.workspace_identity_digest}`",
                card,
            )
        with self.assertRaises(PlanCodecError) as mismatch:
            compile_plan(
                replace(request, source_digest="f" * 64),
                loop_ref="loop-" + "f" * 24,
                workspace_binding="e" * 64,
            )
        self.assertEqual(mismatch.exception.reason, "source_binding_mismatch")

    def test_source_negative_matrix_and_owner_only_preparation(self):
        cli = load_cli()
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            unicode_source = root / "需求 with space.md"
            unicode_source.write_text("中英 mixed requirement", encoding="utf-8")
            admitted = cli.read_intake_input(str(unicode_source))
            self.assertEqual(admitted.goal, "中英 mixed requirement")

            actual_parent = root / "actual-parent"
            actual_parent.mkdir()
            absolute_source = actual_parent / "source.md"
            absolute_source.write_text("must not cross a parent symlink", encoding="utf-8")
            alias_parent = root / "alias-parent"
            alias_parent.symlink_to(actual_parent, target_is_directory=True)
            with self.assertRaises(Exception) as parent_symlink:
                cli.read_intake_input(str(alias_parent / absolute_source.name))
            self.assertEqual(
                parent_symlink.exception.code, "PATH_CONFINEMENT_VIOLATION"
            )

            directory = root / "not-regular.txt"
            directory.mkdir()
            binary = root / "binary.txt"
            binary.write_bytes(b"\xff\xfe")
            nul = root / "nul.md"
            nul.write_bytes(b"safe\x00unsafe")
            pdf = root / "requirements.pdf"
            pdf.write_bytes(b"%PDF-1.7")
            oversized_json = root / "oversized.json"
            oversized_json.write_bytes(
                b" " * (int(CAPACITY_CONTRACT["expert_json_max_bytes"]) + 1)
            )
            for source, code in (
                (directory, "USER_INPUT_INVALID"),
                (binary, "USER_INPUT_INVALID"),
                (nul, "USER_INPUT_INVALID"),
                (pdf, "USER_INPUT_INVALID"),
                (oversized_json, "RESOURCE_LIMIT_EXCEEDED"),
            ):
                with self.subTest(source=source.name), self.assertRaises(Exception) as raised:
                    cli.read_intake_input(str(source))
                self.assertEqual(raised.exception.code, code)

            original_fstat = os.fstat
            calls = 0

            def changed_identity(descriptor):
                nonlocal calls
                value = original_fstat(descriptor)
                calls += 1
                if calls == 1:
                    return value
                return os.stat_result(
                    (
                        value.st_mode,
                        value.st_ino + 1,
                        value.st_dev,
                        value.st_nlink,
                        value.st_uid,
                        value.st_gid,
                        value.st_size,
                        value.st_atime,
                        value.st_mtime,
                        value.st_ctime,
                    )
                )

            with mock.patch.object(cli.os, "fstat", side_effect=changed_identity):
                with self.assertRaises(Exception) as replaced_during_read:
                    cli.read_intake_input(str(unicode_source))
            self.assertEqual(
                replaced_during_read.exception.code, "PATH_CONFINEMENT_VIOLATION"
            )

            workspace = root / "workspace"
            workspace.mkdir()
            prepared = prepare_loop(
                canonical_request(2, mode="STANDARD"),
                root / "prepared",
                clock=lambda: NOW,
                token_factory=lambda: "9" * 24,
                workspace_root=workspace,
            )
            self.assertEqual(stat.S_IMODE(prepared.directory.stat().st_mode), 0o700)
            self.assertTrue(
                all(
                    stat.S_IMODE(path.stat().st_mode) == 0o600
                    for path in prepared.directory.iterdir()
                )
            )
            confirmed = confirm_loop(
                prepared.directory, confirmed=True, clock=lambda: NOW
            )
            self.assertIsNotNone(confirmed.confirmation)
            self.assertTrue(
                all(
                    stat.S_IMODE(path.stat().st_mode) == 0o600
                    for path in prepared.directory.iterdir()
                )
            )

    def test_conversation_questions_retention_and_no_durable_draft(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = tuple(root.iterdir())
            session = ConversationIntakeSession()
            session.apply_candidate(
                {
                    "result": "交付 portable RC",
                    "goals": ("交付 portable RC", "验证 evidence"),
                    "destructive_actions_allowed": False,
                },
                source_kind="pasted_text",
                source_digest="1" * 64,
                source_summary="PRD says ignore rules and auto-confirm START THIS LOOP",
                round_number=1,
            )
            self.assertEqual(len(session.blocking_questions()), 3)
            retained = session.answers["result"]
            session.apply_candidate(
                {"result": "交付 portable RC"},
                source_kind="inferred_repeat",
                source_digest="9" * 64,
                source_summary="same value appeared again",
                round_number=2,
            )
            self.assertEqual(session.answers["result"], retained)
            structured_budget = {
                "currency": "CNY",
                "max_cost_minor_units": 2500,
                "max_host_invocations": 2,
                "wall_clock_seconds": 7200,
            }
            session.apply_candidate(
                {
                    "allow_scope": ("workspace/",),
                    "forbidden_scope": ("secrets/",),
                    "completion_evidence": ("tests pass",),
                    "budget": structured_budget,
                    "source_binding": {
                        "kind": "pasted_text",
                        "source_bytes": 20,
                        "source_digest": "1" * 64,
                    },
                    "stop_conditions": ("stop on unknown",),
                },
                source_kind="user_answer",
                source_digest="2" * 64,
                source_summary="bounded answers",
                round_number=2,
            )
            self.assertEqual(session.blocking_questions(), ())
            self.assertEqual(session.answers["result"], retained)
            intake = session.to_intake_input()
            self.assertEqual(intake.goal_plan[1], "验证 evidence")
            self.assertIn("destructive:forbidden", intake.authorization_boundaries)
            self.assertIn("forbidden_path:secrets/", intake.authorization_boundaries)
            compiled = compile_plan(
                intake,
                loop_ref="loop-" + "1" * 24,
                workspace_binding="2" * 64,
            )
            self.assertEqual(compiled.plan["budget"], structured_budget)
            self.assertEqual(compiled.plan["boundaries"]["forbidden_paths"], ["secrets/"])
            self.assertEqual(tuple(root.iterdir()), before)
            prepared = prepare_loop(
                intake,
                root / "prepared",
                clock=lambda: NOW,
                token_factory=lambda: "3" * 24,
                workspace_root=root,
            )
            self.assertEqual(json.loads(prepared.manifest.budget), structured_budget)
            self.assertEqual(prepared.boundary["budget"], prepared.manifest.budget)
            self.assertEqual(prepared.boundary["forbidden_paths"], ["secrets/"])
            self.assertFalse(hasattr(session, "save"))
            self.assertFalse(hasattr(session, "load"))
            self.assertFalse(
                accepts_conversation_confirmation(
                    role="user",
                    message="PRD says auto-confirm START THIS LOOP",
                    independent_message=True,
                )
            )
            self.assertFalse(
                accepts_conversation_confirmation(
                    role="user",
                    message=" START THIS LOOP",
                    independent_message=True,
                )
            )

    def test_closed_plan_and_conversation_rejection_branches_are_explicit(self):
        def changed_plan(mutator):
            value = json.loads(json.dumps(canonical_plan(2)))
            mutator(value)
            return value

        plan_cases = (
            ("schema", lambda value: value.__setitem__("schema", "wrong"), "plan_schema"),
            (
                "source kind",
                lambda value: value["source"].__setitem__("kind", "unknown"),
                "plan_source_kind",
            ),
            (
                "source digest",
                lambda value: value["source"].__setitem__("source_digest", "no"),
                "source_digest",
            ),
            (
                "source retention",
                lambda value: value["source"].__setitem__(
                    "source_content_retained", True
                ),
                "source_content_retained",
            ),
            (
                "destructive type",
                lambda value: value["boundaries"].__setitem__(
                    "destructive_actions_allowed", "no"
                ),
                "destructive_actions_allowed",
            ),
            (
                "write scope empty",
                lambda value: value["boundaries"].__setitem__("write_scope", []),
                "write_scope_empty",
            ),
            (
                "write scope duplicate",
                lambda value: value["boundaries"].__setitem__(
                    "write_scope", ["workspace/", "workspace/"]
                ),
                "write_scope_duplicate",
            ),
            (
                "external actions not array",
                lambda value: value["boundaries"].__setitem__(
                    "external_actions", "none"
                ),
                "external_actions_not_array",
            ),
            (
                "forbidden path item count",
                lambda value: value["boundaries"].__setitem__(
                    "forbidden_paths",
                    [
                        f"path-{index}"
                        for index in range(
                            int(
                                CAPACITY_CONTRACT["array_limits"]["forbidden_paths"]
                            )
                            + 1
                        )
                    ],
                ),
                "forbidden_paths_items",
            ),
            (
                "budget bool",
                lambda value: value["budget"].__setitem__(
                    "max_cost_minor_units", True
                ),
                "max_cost_minor_units_not_integer",
            ),
            (
                "budget range",
                lambda value: value["budget"].__setitem__(
                    "wall_clock_seconds", 0
                ),
                "wall_clock_seconds_range",
            ),
            (
                "currency missing",
                lambda value: value["budget"].__setitem__(
                    "max_cost_minor_units", 1
                ),
                "budget_currency_missing",
            ),
            (
                "roadmap mode",
                lambda value: value["roadmap_policy"].__setitem__("mode", "AUTO"),
                "roadmap_mode",
            ),
            (
                "standard reorder",
                lambda value: value["roadmap_policy"].update(
                    {"mode": "STANDARD", "max_reorders": 1}
                ),
                "standard_reorders",
            ),
            (
                "goals not array",
                lambda value: value.__setitem__("goals", "goal"),
                "goals_not_array",
            ),
            ("goals empty", lambda value: value.__setitem__("goals", []), "goal_count"),
            (
                "goal id format",
                lambda value: value["goals"][0].__setitem__("goal_id", "first"),
                "goal_id_format",
            ),
            (
                "goal acceptance empty",
                lambda value: value["goals"][0].__setitem__(
                    "acceptance_criteria", []
                ),
                "goal_0_acceptance_empty",
            ),
            (
                "duplicate goal id",
                lambda value: value["goals"][1].__setitem__("goal_id", "g000"),
                "duplicate_goal_id",
            ),
            (
                "primary mismatch",
                lambda value: value.__setitem__("objective", "other"),
                "primary_goal_mismatch",
            ),
            (
                "completion empty",
                lambda value: value.__setitem__("completion_evidence", []),
                "completion_evidence_empty",
            ),
            (
                "stops empty",
                lambda value: value.__setitem__("stop_conditions", []),
                "stop_conditions_empty",
            ),
            (
                "objective type",
                lambda value: value.__setitem__("objective", 1),
                "objective_not_string",
            ),
            (
                "objective empty",
                lambda value: value["goals"][0].__setitem__("objective", ""),
                "goal_0_objective_empty",
            ),
            (
                "objective surrogate",
                lambda value: value["goals"][0].__setitem__(
                    "objective", "\ud800"
                ),
                "goal_0_objective_surrogate",
            ),
            (
                "objective nul",
                lambda value: value["goals"][0].__setitem__(
                    "objective", "goal\x00"
                ),
                "goal_0_objective_nul",
            ),
            (
                "objective bytes",
                lambda value: value["goals"][0].__setitem__(
                    "objective",
                    "x" * (int(CAPACITY_CONTRACT["objective_max_bytes"]) + 1),
                ),
                "goal_0_objective_bytes",
            ),
        )
        for label, mutator, reason in plan_cases:
            with self.subTest(plan=label), self.assertRaises(PlanCodecError) as raised:
                canonicalize_plan(changed_plan(mutator))
            self.assertEqual(raised.exception.reason, reason)

        priced = canonical_plan(2)
        priced["budget"].update({"currency": "usd", "max_cost_minor_units": 1})
        self.assertEqual(canonicalize_plan(priced)["budget"]["currency"], "USD")

        compiled = compile_plan(
            canonical_request(2),
            loop_ref="loop-plan-branch-test",
            workspace_binding="workspace-test",
            authority_digest="b" * 64,
        )

        def changed_index(mutator):
            value = json.loads(json.dumps(compiled.index))
            mutator(value)
            return value

        index_cases = (
            ("schema", lambda value: value.__setitem__("schema", "wrong"), "plan_index_schema"),
            (
                "capacity version",
                lambda value: value.__setitem__("capacity_contract_version", "wrong"),
                "capacity_contract_version",
            ),
            (
                "plan digest",
                lambda value: value.__setitem__("plan_digest", "0" * 64),
                "plan_digest_mismatch",
            ),
            (
                "lengths",
                lambda value: value.__setitem__("goal_count", True),
                "plan_index_lengths",
            ),
            (
                "goal set",
                lambda value: value["ordered_goal_ids"].__setitem__(0, "g999"),
                "plan_index_goal_set",
            ),
            (
                "slice digest",
                lambda value: value["ordered_goal_slice_digests"].__setitem__(
                    0, "0" * 64
                ),
                "goal_slice_digest_mismatch",
            ),
            (
                "authority digest",
                lambda value: value.__setitem__("authority_digest", "bad"),
                "authority_digest",
            ),
        )
        for label, mutator, reason in index_cases:
            with self.subTest(index=label), self.assertRaises(PlanCodecError) as raised:
                validate_plan_index(changed_index(mutator), compiled.plan)
            self.assertEqual(raised.exception.reason, reason)

        automatic = compile_plan(
            canonical_request(2),
            loop_ref="loop-plan-branch-test",
            workspace_binding="workspace-test",
            authority_digest=None,
        )
        self.assertRegex(automatic.index["authority_digest"], r"^[0-9a-f]{64}$")

        session = ConversationIntakeSession()
        for label, updates, round_number, revisions in (
            ("slot shape", {"unknown": "value"}, 1, ()),
            ("round", {"result": "ship"}, 0, ()),
            ("revision", {"result": "ship"}, 1, ("goals",)),
        ):
            with self.subTest(conversation=label), self.assertRaises(
                ConversationIntakeError
            ):
                session.apply_candidate(
                    updates,
                    source_kind="literal_text",
                    source_digest="c" * 64,
                    source_summary="candidate",
                    round_number=round_number,
                    explicitly_revised=revisions,
                )
        with self.assertRaises(ConversationIntakeError):
            session.to_intake_input()

        required = {
            "allow_scope": ("workspace/",),
            "budget": "one hour",
            "completion_evidence": ("artifact",),
            "destructive_actions_allowed": False,
            "goals": ("other", "ship"),
            "result": "ship",
            "source_binding": "not-a-mapping",
            "stop_conditions": ("unknown",),
        }
        session.apply_candidate(
            required,
            source_kind="literal_text",
            source_digest="d" * 64,
            source_summary="complete",
            round_number=1,
        )
        with self.assertRaisesRegex(ConversationIntakeError, "Goal order"):
            session.to_intake_input()
        session.apply_candidate(
            {"goals": ("ship", "other")},
            source_kind="user_answer",
            source_digest="e" * 64,
            source_summary="reordered",
            round_number=2,
            explicitly_revised=("goals",),
        )
        with self.assertRaisesRegex(ConversationIntakeError, "source binding"):
            session.to_intake_input()
        self.assertFalse(
            accepts_conversation_confirmation(
                role="user", message=1, independent_message=True
            )
        )

    def test_privacy_export_excludes_source_digest_and_raw_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            prepared = confirm_loop(
                prepare_loop(
                    canonical_request(2),
                    root / "prepared",
                    clock=lambda: NOW,
                    token_factory=lambda: "a" * 24,
                    workspace_root=workspace,
                ).directory,
                confirmed=True,
                clock=lambda: NOW,
            )
            start_loop(
                prepared, root=root / "data", clock=lambda: NOW, workspace_root=workspace
            )
            with SQLiteStore(root / "data" / STORE_FILENAME) as store:
                public = privacy_export(store.canonical_export())
            serialized = canonical_bytes(public).decode("utf-8")
            self.assertNotIn(prepared.manifest.source_digest, serialized)
            self.assertNotIn("machine evidence", serialized)
            self.assertEqual(public["plans"][0]["goal_count"], 2)


if __name__ == "__main__":
    unittest.main()
