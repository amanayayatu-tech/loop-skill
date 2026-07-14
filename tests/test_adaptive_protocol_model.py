from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "codex-loop-prompt-architect" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from loop_architect.protocol_model import (  # noqa: E402
    ADAPTIVE_OUTBOX_KINDS,
    ADAPTIVE_REVIEW_DECISIONS,
    ADAPTIVE_RUNTIME_MUTATIONS,
    EMULATED_GOAL_LIFECYCLE,
    FORBIDDEN_ADAPTIVE_PROTOCOL_TOKENS,
    OUTBOX_CANCELLATION_LIFECYCLES,
    OUTBOX_LIFECYCLES,
    ProtocolDriftError,
    accepted_mutation_types,
    accepted_outbox_kinds,
    accepted_review_decisions,
    assert_protocol_sources_aligned,
    assert_rendered_pack_aligned,
    authorization_fields,
    forbidden_rendered_tokens,
    mutation_zero_execution_blocker_codes,
    runtime_success_codes,
    state_zero_execution_blocker_codes,
    state_schema,
    validate_protocol_sources,
)
from loop_architect.state_runtime import ZERO_EXECUTION_BLOCKER_CODES  # noqa: E402


class AdaptiveProtocolCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pack_path = ROOT / "examples" / "03-adaptive-passkey-controller-pack.md"
        cls.pack = cls.pack_path.read_text(encoding="utf-8")
        cls.usage = (
            ROOT / "examples" / "03-adaptive-passkey-usage.md"
        ).read_text(encoding="utf-8")

    def test_all_protocol_sources_are_aligned(self) -> None:
        self.assertEqual(validate_protocol_sources(), [])
        assert_protocol_sources_aligned()

    def test_zero_execution_blocker_contract_is_identical_everywhere(self) -> None:
        runtime_codes = set(ZERO_EXECUTION_BLOCKER_CODES)
        self.assertEqual(set(state_zero_execution_blocker_codes()), runtime_codes)
        self.assertEqual(set(mutation_zero_execution_blocker_codes()), runtime_codes)

        contract = (
            ROOT
            / "codex-loop-prompt-architect"
            / "references"
            / "adaptive-loop-contract.md"
        ).read_text(encoding="utf-8")
        public_block = contract.split(
            "<!-- ZERO_EXECUTION_BLOCKER_CODES_START -->", 1
        )[1].split("<!-- ZERO_EXECUTION_BLOCKER_CODES_END -->", 1)[0]
        documented = {
            line.strip()[3:-1]
            for line in public_block.splitlines()
            if line.strip().startswith("- `") and line.strip().endswith("`")
        }
        self.assertEqual(documented, runtime_codes)
        for code in runtime_codes:
            self.assertIn(f"`{code}`", self.pack)

    def test_zero_execution_blocker_drift_is_a_release_gate_failure(self) -> None:
        with mock.patch(
            "loop_architect.protocol_model.state_zero_execution_blocker_codes",
            return_value=("SCHEMA_DRIFT",),
        ):
            self.assertIn(
                "state schema and runtime zero-execution blockers differ",
                validate_protocol_sources(),
            )
        with mock.patch(
            "loop_architect.protocol_model.mutation_zero_execution_blocker_codes",
            return_value=("MUTATION_DRIFT",),
        ):
            self.assertIn(
                "mutation schema and runtime zero-execution blockers differ",
                validate_protocol_sources(),
            )

    def test_mutation_types_come_from_public_schema(self) -> None:
        self.assertEqual(accepted_mutation_types(), ADAPTIVE_RUNTIME_MUTATIONS)
        self.assertEqual(
            accepted_mutation_types(),
            (
                "INITIALIZE",
                "MIGRATE_V1_TO_V2",
                "MIGRATE_CONTROLLER_PACK",
                "RECONCILE_WORKER_EXECUTION_CLASSIFICATION",
                "RECORD_STEERING",
                "RESOLVE_STEERING",
                "SET_RUN_CONTROL",
                "REGISTER_DECISION",
                "RECORD_DECISION_RESPONSE",
                "RECORD_FAILURE",
                "RECORD_VALIDATION",
                "RECORD_CONTEXT_FRESHNESS",
                "RECORD_CONTROLLER_GOAL_RESUME",
                "ACQUIRE_LEASE",
                "RELEASE_LEASE",
                "RENEW_LEASE",
                "TAKEOVER_LEASE",
                "PREPARE_OUTBOX",
                "CANCEL_OUTBOX",
                "MARK_OUTBOX_SENT",
                "ACK_OUTBOX",
                "RECORD_REVIEW",
                "ROADMAP_REVISION",
                "FINALIZE_LOOP",
                "STOP_LOOP",
                "ACK_FINALIZATION",
            ),
        )

    def test_outbox_kinds_come_from_public_schema(self) -> None:
        self.assertEqual(accepted_outbox_kinds(), ADAPTIVE_OUTBOX_KINDS)
        self.assertEqual(set(OUTBOX_LIFECYCLES), set(accepted_outbox_kinds()))
        self.assertEqual(
            set(OUTBOX_CANCELLATION_LIFECYCLES), set(accepted_outbox_kinds())
        )

    def test_review_decisions_come_from_public_schema(self) -> None:
        self.assertEqual(accepted_review_decisions(), ADAPTIVE_REVIEW_DECISIONS)

    def test_authorization_fields_include_all_runtime_caps(self) -> None:
        fields = set(authorization_fields())
        self.assertTrue(
            {
                "phase_permission_caps",
                "control_plane_caps",
                "delegation_policy",
                "repair_policy",
            }.issubset(fields)
        )

    def test_controller_goal_and_thread_role_state_are_closed(self) -> None:
        schema = state_schema()
        controller_goal = schema["$defs"]["controllerGoal"]
        self.assertFalse(controller_goal["additionalProperties"])
        self.assertIn("goal_id", controller_goal["required"])
        self.assertIn("status", controller_goal["required"])
        thread_record = schema["$defs"]["threadRecord"]
        self.assertIn("bootstrap_role_kind", thread_record["required"])
        self.assertIn("role_kind", thread_record["required"])

    def test_kind_specific_lifecycles_match_runtime_contract(self) -> None:
        self.assertEqual(OUTBOX_LIFECYCLES["DISPATCH"], ("PREPARED", "SENT", "COMPLETED"))
        self.assertEqual(OUTBOX_LIFECYCLES["LOCAL"], ("PREPARED", "SENT", "COMPLETED"))
        self.assertEqual(
            OUTBOX_LIFECYCLES["ASSURANCE"],
            ("PREPARED", "SENT", "ACKED", "COMPLETED"),
        )
        self.assertEqual(OUTBOX_LIFECYCLES["GOAL"], ("PREPARED", "SENT", "ACKED"))
        self.assertEqual(OUTBOX_LIFECYCLES["DELEGATION"], ("PREPARED", "SENT", "ACKED"))
        self.assertEqual(EMULATED_GOAL_LIFECYCLE, ("PREPARED", "ACKED"))
        self.assertTrue(
            all(
                lifecycle == ("PREPARED", "CANCELLED")
                for lifecycle in OUTBOX_CANCELLATION_LIFECYCLES.values()
            )
        )

    def test_runtime_success_codes_are_derived_not_handwritten_transitions(self) -> None:
        codes = set(runtime_success_codes())
        self.assertIn("DISPATCH_OUTBOX_PREPARED", codes)
        self.assertIn("DISPATCH_OUTBOX_CANCELLED", codes)
        self.assertIn("ASSURANCE_OUTBOX_ACKED", codes)
        self.assertIn("ROADMAP_AUDIT_ACKED", codes)
        self.assertIn("ROADMAP_REVISION_APPLIED", codes)
        self.assertIn("STOP_LOOP_APPLIED", codes)
        self.assertIn("FINALIZATION_ACKED", codes)
        self.assertIn("IDEMPOTENT_REPLAY", codes)
        self.assertTrue(
            {
                "STEERING_APPLIED",
                "STEERING_DEFERRED",
                "STEERING_CONFLICT",
                "PAUSE_REQUESTED",
                "PAUSED_AT_SAFE_POINT",
                "RUNNING",
            }.issubset(codes)
        )

    def test_adaptive_example_contains_no_non_runtime_protocol_tokens(self) -> None:
        self.assertEqual(forbidden_rendered_tokens(self.pack), ())
        assert_rendered_pack_aligned(self.pack)
        self.assertEqual(forbidden_rendered_tokens(self.usage), ())
        assert_rendered_pack_aligned(self.usage)

    def test_forbidden_token_scan_is_closed_and_actionable(self) -> None:
        for token in FORBIDDEN_ADAPTIVE_PROTOCOL_TOKENS:
            with self.subTest(token=token):
                self.assertEqual(forbidden_rendered_tokens(f"before {token} after"), (token,))
                with self.assertRaises(ProtocolDriftError):
                    assert_rendered_pack_aligned(f"before {token} after")

    def test_example_input_declares_adaptive_mode(self) -> None:
        payload = json.loads(
            (ROOT / "examples" / "03-adaptive-passkey-input.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(payload["coordination_mode"], "adaptive")


if __name__ == "__main__":
    unittest.main()
