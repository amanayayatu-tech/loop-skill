from __future__ import annotations

import copy
import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "codex-loop-prompt-architect" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from loop_architect.v4_alpha.kernel import AuthorityContext  # noqa: E402
from loop_architect.v4_alpha.protocol import (  # noqa: E402
    ProtocolRejection,
    build_command,
    with_command_change,
)
from loop_architect.v4_alpha.store import InMemoryStore  # noqa: E402
from loop_architect.v4_alpha.vertical import (  # noqa: E402
    LOOP_REF,
    fixture_authority,
    replace_grant_digest,
    vertical_commands,
)
from loop_architect.v4_operability import (  # noqa: E402
    archive_manifest,
    audit_index,
    doctor_projection,
    metrics_projection,
    privacy_export,
    risk_scan,
    status_projection,
)
from loop_architect.v4_policy import (  # noqa: E402
    DecisionResponse,
    GoalSpec,
    PolicyEnvelope,
    PolicyError,
    RepairObservation,
    apply_decision_response,
    build_adaptive_roadmap,
    build_decision_card,
    build_standard_queue,
    next_action,
    repair_disposition,
    role_requirements,
    validate_manifest_mode,
)
from tests.v4_eager_fixture import seed_eager_memory  # noqa: E402


def _authority_with_commands(*commands: str, cooperative_close: bool = False):
    base = fixture_authority()
    grants = dict(base.grants)
    author = grants["grant-author-0001"]
    grants[author.grant_ref] = replace_grant_digest(
        replace(
            author,
            allowed_commands=tuple(sorted(set(author.allowed_commands) | set(commands))),
            canonical_digest="",
        )
    )
    system = grants["grant-system-0001"]
    grants[system.grant_ref] = replace_grant_digest(
        replace(
            system,
            allowed_commands=tuple(sorted(set(system.allowed_commands) | set(commands))),
            canonical_digest="",
        )
    )
    receipts = dict(base.receipts)
    if cooperative_close:
        receipts["receipt-finalize-0001"] = replace(
            receipts["receipt-finalize-0001"], trust_class="cooperative"
        )
        receipts["receipt-finalize-late-0001"] = replace(
            base.receipts["receipt-finalize-0001"],
            receipt_ref="receipt-finalize-late-0001",
        )
    return AuthorityContext(
        actors=base.actors,
        grants=grants,
        receipts=receipts,
        trusted_actor_issuers=base.trusted_actor_issuers,
        trusted_grant_issuers=base.trusted_grant_issuers,
        trusted_receipt_issuers=base.trusted_receipt_issuers,
    )


def _rebuild(command, *, semantic_payload=None, receipt_ref=None):
    bindings = {
        group: dict(values) for group, values in command.machine_bindings.items()
    }
    if receipt_ref is not None:
        bindings["receipt_refs"]["receipt"] = receipt_ref
    return with_command_change(
        command,
        lambda values: values.update(
            machine_bindings=bindings,
            semantic_payload=(
                dict(command.semantic_payload)
                if semantic_payload is None
                else semantic_payload
            ),
        ),
    )


def _legacy_build_command(**values):
    command = build_command(**values)
    return with_command_change(
        command,
        lambda wire: wire.update(protocol_version="4.0.0"),
    )


class V4ProductPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.envelope = PolicyEnvelope(
            allowed_goal_ids=("g1", "g2", "g3"),
            max_goals=3,
            max_roadmap_revisions=3,
            max_repair_attempts=3,
            max_same_failure=2,
        )

    def test_standard_is_fixed_dependency_order_and_adaptive_is_bounded(self):
        goals = (
            GoalSpec("g1", "first"),
            GoalSpec("g2", "second", depends_on=("g1",), milestone_id="m2"),
        )
        self.assertEqual(build_standard_queue(goals, self.envelope), goals)
        with self.assertRaisesRegex(PolicyError, "dependency ordered"):
            build_standard_queue(tuple(reversed(goals)), self.envelope)
        first = build_adaptive_roadmap(
            goals, self.envelope, revision=1, active_goal_id="g1"
        )
        second = build_adaptive_roadmap(
            (*goals, GoalSpec("g3", "third", depends_on=("g2",), milestone_id="m3")),
            self.envelope,
            revision=2,
            active_goal_id="g2",
            previous=first,
        )
        self.assertNotEqual(first.roadmap_digest, second.roadmap_digest)
        with self.assertRaisesRegex(PolicyError, "rewrote"):
            build_adaptive_roadmap(
                (GoalSpec("g1", "changed"), goals[1]),
                self.envelope,
                revision=2,
                active_goal_id="g2",
                previous=first,
            )

    def test_manifest_mode_requires_explicit_adaptive_request(self):
        self.assertEqual(validate_manifest_mode("STANDARD", "long"), "STANDARD")
        self.assertEqual(validate_manifest_mode("ADAPTIVE", "adaptive"), "ADAPTIVE")
        with self.assertRaisesRegex(PolicyError, "Intake decision"):
            validate_manifest_mode("ADAPTIVE", "long")

    def test_roles_are_jit_and_bind_the_current_artifact(self):
        empty = {"execution": {"state": "ACTIVE"}, "results": {}, "reviews": {}}
        self.assertEqual(role_requirements(empty, local_verification_required=False)[0].role, "WORKER")
        acknowledged = {
            "execution": {"state": "ACTIVE"},
            "results": {"result-1": {"state": "ACKNOWLEDGED", "artifact_ref": "artifact-1"}},
            "reviews": {},
        }
        verifier = role_requirements(
            acknowledged, local_verification_required=True
        )[0]
        self.assertEqual((verifier.role, verifier.artifact_ref), ("LOCAL_VERIFIER", "artifact-1"))
        reviewer = role_requirements(
            {**acknowledged, "local_verification": {"artifact-1": {"state": "PASS"}}},
            local_verification_required=True,
        )[0]
        self.assertEqual((reviewer.role, reviewer.artifact_ref), ("REVIEWER", "artifact-1"))

    def test_decision_card_binds_context_and_rejects_replay_after_change(self):
        context = {"goal_ref": "goal-1", "artifact_ref": "artifact-1", "revision": 4}
        card = build_decision_card(
            card_ref="decision-1",
            goal_ref="goal-1",
            artifact_ref="artifact-1",
            options=("CONTINUE_REPAIR", "WAIT", "STOP"),
            current_context=context,
            expires_at="2026-07-27T01:10:00Z",
        )
        response = DecisionResponse(
            card_ref=card.card_ref,
            selected_option="STOP",
            context_digest=card.context_digest,
            card_digest=card.card_digest,
            responded_at="2026-07-27T01:05:00Z",
        )
        self.assertEqual(
            apply_decision_response(
                card, response, current_context=context, now="2026-07-27T01:06:00Z"
            ),
            "STOP",
        )
        with self.assertRaisesRegex(PolicyError, "stale or mismatched"):
            apply_decision_response(
                card,
                response,
                current_context={**context, "revision": 5},
                now="2026-07-27T01:06:00Z",
            )

    def test_repair_is_bounded_and_same_failure_routes_to_human(self):
        one = (RepairObservation("attempt-1", "failure-a"),)
        repeated = (*one, RepairObservation("attempt-2", "failure-a"))
        exhausted = (*repeated, RepairObservation("attempt-3", "failure-b"))
        self.assertEqual(repair_disposition(one, self.envelope), "REPAIR")
        self.assertEqual(repair_disposition(repeated, self.envelope), "USER_DECISION")
        self.assertEqual(repair_disposition(exhausted, self.envelope), "USER_DECISION")

    def test_every_vertical_nonterminal_snapshot_has_one_next_action_class(self):
        store = InMemoryStore(fixture_authority())
        seed_eager_memory(store)
        expected = (
            ("COMMAND", "StageResult"),
            ("COMMAND", "AcknowledgeResult"),
            ("POLICY_DECISION", "RecordReview"),
            ("COMMAND", "AdvanceGoal"),
            ("COMMAND", "PrepareFinalization"),
            ("EXTERNAL_WAIT", "CloseExecution"),
            ("TERMINAL", None),
        )
        action = next_action(store.snapshot(LOOP_REF))
        self.assertEqual((action.kind, action.command_type), expected[0])
        for command, expected_action in zip(vertical_commands()[5:], expected[1:]):
            store.apply(command)
            action = next_action(store.snapshot(LOOP_REF))
            self.assertEqual((action.kind, action.command_type), expected_action)

    def test_pause_resume_are_cas_mutations_without_raw_reason(self):
        authority = _authority_with_commands("PauseLoop", "ResumeLoop")
        store = InMemoryStore(authority)
        seed_eager_memory(store)
        pause = _legacy_build_command(
            operation_id="op-pause-0001",
            command_type="PauseLoop",
            actor_ref="actor-author-0001",
            authority_grant_ref="grant-author-0001",
            subject={"loop_ref": LOOP_REF, "subject_kind": "LoopRef", "subject_ref": LOOP_REF},
            expected_loop_revision=5,
            expected_subject_revisions={"execution": 1},
            issued_at="2026-07-27T00:00:20Z",
            machine_bindings={"allocate_refs": {}, "receipt_refs": {}, "resolved_refs": {}},
            semantic_payload={"reason": "wait for author boundary"},
        )
        paused = store.apply(pause)
        snapshot = store.snapshot(LOOP_REF)
        self.assertEqual((paused.event_types, snapshot["execution"]["state"]), (("LoopPaused",), "PAUSED"))
        self.assertNotIn("wait for author boundary", str(snapshot))
        resume = _legacy_build_command(
            operation_id="op-resume-0001",
            command_type="ResumeLoop",
            actor_ref="actor-author-0001",
            authority_grant_ref="grant-author-0001",
            subject={"loop_ref": LOOP_REF, "subject_kind": "LoopRef", "subject_ref": LOOP_REF},
            expected_loop_revision=6,
            expected_subject_revisions={"execution": 2},
            issued_at="2026-07-27T00:00:21Z",
            machine_bindings={"allocate_refs": {}, "receipt_refs": {}, "resolved_refs": {}},
            semantic_payload={},
        )
        store.apply(resume)
        self.assertEqual(store.snapshot(LOOP_REF)["execution"], {"disposition": None, "revision": 3, "state": "ACTIVE"})

    def test_uncertain_repair_paused_and_cooperative_states_are_not_dead(self):
        store = InMemoryStore(fixture_authority())
        seed_eager_memory(store)
        snapshots = [store.snapshot(LOOP_REF)]
        for command in vertical_commands()[5:]:
            store.apply(command)
            snapshots.append(store.snapshot(LOOP_REF))

        unknown = copy.deepcopy(snapshots[0])
        unknown["attempts"]["attempt-0001"]["state"] = "UNKNOWN"
        unknown["deliveries"]["delivery-0001"]["state"] = "UNKNOWN"
        self.assertEqual(next_action(unknown).kind, "EXTERNAL_WAIT")

        unverifiable = copy.deepcopy(unknown)
        unverifiable["attempts"]["attempt-0001"]["state"] = "UNVERIFIABLE"
        unverifiable["deliveries"]["delivery-0001"]["state"] = "UNVERIFIABLE"
        self.assertEqual(next_action(unverifiable).kind, "EXTERNAL_WAIT")

        paused = copy.deepcopy(snapshots[0])
        paused["execution"]["state"] = "PAUSED"
        self.assertEqual(next_action(paused).kind, "USER_DECISION")

        repair = copy.deepcopy(snapshots[3])
        repair["reviews"]["review-0001"]["state"] = "REPAIR"
        self.assertEqual(next_action(repair).kind, "POLICY_DECISION")

        cooperative = copy.deepcopy(snapshots[-1])
        cooperative["closure_assurance"]["strength"] = "COOPERATIVE"
        cooperative["finalizations"]["finalization-0001"][
            "assurance_strength"
        ] = "COOPERATIVE"
        action = next_action(cooperative)
        self.assertEqual(
            (action.kind, action.command_type),
            ("EXTERNAL_WAIT", "StrengthenClosureAssurance"),
        )

    def test_late_strict_readback_strengthens_terminal_assurance_only(self):
        authority = _authority_with_commands(
            "StrengthenClosureAssurance", cooperative_close=True
        )
        store = InMemoryStore(authority)
        seed_eager_memory(store)
        commands = list(vertical_commands())
        commands[9] = _rebuild(
            commands[9], semantic_payload={"disposition": "LIMITATION"}
        )
        for command in commands[5:]:
            store.apply(command)
        snapshot = store.snapshot(LOOP_REF)
        self.assertEqual(snapshot["closure_assurance"]["strength"], "COOPERATIVE")
        strengthen = _legacy_build_command(
            operation_id="op-strengthen-0001",
            command_type="StrengthenClosureAssurance",
            actor_ref="actor-system-0001",
            authority_grant_ref="grant-system-0001",
            subject={"loop_ref": LOOP_REF, "subject_kind": "FinalizationRef", "subject_ref": "finalization-0001"},
            expected_loop_revision=11,
            expected_subject_revisions={"closure_assurance": 1, "finalization-0001": 2},
            issued_at="2026-07-27T00:00:20Z",
            machine_bindings={
                "allocate_refs": {},
                "receipt_refs": {"receipt": "receipt-finalize-late-0001"},
                "resolved_refs": {},
            },
            semantic_payload={},
        )
        result = store.apply(strengthen)
        self.assertEqual(result.response["assurance"], "STRICT")
        self.assertEqual(store.snapshot(LOOP_REF)["closure_assurance"]["strength"], "STRICT")
        self.assertEqual(store.snapshot(LOOP_REF)["execution"]["disposition"], "LIMITATION")


class V4OperabilityProjectionTests(unittest.TestCase):
    def _store_with_rejection(self):
        store = InMemoryStore(fixture_authority())
        seed_eager_memory(store)
        stale = _rebuild(vertical_commands()[5])
        stale = _legacy_build_command(
            operation_id="op-stale-audit",
            command_type=stale.command_type,
            actor_ref=stale.actor_ref,
            authority_grant_ref=stale.authority_grant_ref,
            subject=stale.subject,
            expected_loop_revision=4,
            expected_subject_revisions=stale.expected_subject_revisions,
            issued_at=stale.issued_at,
            machine_bindings=stale.machine_bindings,
            semantic_payload=stale.semantic_payload,
        )
        with self.assertRaises(ProtocolRejection):
            store.apply(stale)
        return store

    def test_audit_archive_and_status_are_deterministic_read_only_views(self):
        store = self._store_with_rejection()
        before = store.canonical_export()
        audit = audit_index(before)
        archive = archive_manifest(before)
        self.assertEqual(audit, audit_index(before))
        self.assertEqual(archive, archive_manifest(before))
        self.assertEqual(len(audit["entries"]), 6)
        self.assertFalse(audit["runtime_authority"])
        self.assertFalse(archive["runtime_authority"])
        self.assertEqual(before, store.canonical_export())
        self.assertEqual(status_projection(store.snapshot(LOOP_REF))["progress"], "Active")

    def test_privacy_export_is_aggregate_and_omits_raw_identity(self):
        store = self._store_with_rejection()
        value = privacy_export(store.canonical_export())
        serialized = str(value)
        for forbidden in (
            "actor-author",
            "op-stale",
            "loop-0001",
            "thread-0001",
            "raw prompt content",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(value["loop_count"], 1)
        self.assertEqual(value["rejected_operation_count"], 1)

    def test_risk_scan_emits_only_category_and_digests(self):
        secret = b"token=" + b"ghp_" + (b"a" * 32) + b"\nuser=a@example.com"
        result = risk_scan({"synthetic/config.txt": secret})
        self.assertEqual(result["finding_count"], 2)
        self.assertFalse(result["raw_values_included"])
        serialized = str(result)
        self.assertNotIn("ghp_", serialized)
        self.assertNotIn("a@example.com", serialized)
        self.assertNotIn("synthetic/config.txt", serialized)

    def test_metrics_use_unmetered_and_never_authorize_routing(self):
        result = metrics_projection(({"protocol_calls": 2}, {"protocol_calls": 3},))
        self.assertEqual(result["totals"]["protocol_calls"], 5)
        self.assertEqual(result["totals"]["host_interactions"], "UNMETERED")
        self.assertFalse(result["routing_authority"])

    def test_doctor_hides_identity_unless_diagnostics_are_requested(self):
        normal = doctor_projection(
            source_identity="source-a",
            installed_identity="installed-b",
            capabilities={"memory": "UNVERIFIABLE", "heartbeat": "AVAILABLE"},
        )
        self.assertEqual(normal["status"], "BLOCKED")
        self.assertNotIn("diagnostics", normal)
        detailed = doctor_projection(
            source_identity="source-a",
            installed_identity="source-a",
            capabilities={"memory": "UNAVAILABLE"},
            diagnostics=True,
        )
        self.assertEqual(detailed["status"], "READY")
        self.assertEqual(detailed["diagnostics"]["capabilities"]["memory"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
