from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts/run_v4_conformance.py"
SPEC = importlib.util.spec_from_file_location("run_v4_conformance", PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def canary(
    candidate: str,
    *,
    goal_count: int,
    route_digit: str,
    issued: datetime,
) -> dict:
    issued = issued.replace(microsecond=0)
    issued_text = issued.isoformat().replace("+00:00", "Z")
    fresh_text = (issued + timedelta(minutes=60)).isoformat().replace("+00:00", "Z")
    result = b'{"outcome":"PASS","summary":"complete"}'
    empty = hashlib.sha256(b"").hexdigest()
    diagnostic = {
        "artifact": "loopskill-codex-exec-terminal-diagnostic-v1",
        "code": "PASS",
        "primary_code": None,
        "result_bytes": len(result),
        "result_control_digest": hashlib.sha256(result).hexdigest(),
        "result_sha256": hashlib.sha256(result).hexdigest(),
        "returncode_class": "ZERO",
        "schema_control_digest": "6" * 64,
        "semantic_outcome": "PASS",
        "semantic_summary": "complete",
        "stderr_bytes": 0,
        "stderr_sha256": empty,
        "stdout_bytes": 100,
        "stdout_sha256": "7" * 64,
        "terminal_event_count": 1,
        "terminal_event_type": "turn.completed",
    }
    candidate_provenance = {
        "candidate_execution_mode": "CLEAN_GIT_WORKTREE",
        "candidate_sha": candidate,
        "candidate_tree_sha": candidate,
    }
    value = {
        "artifact": runner.rc.CANARY_ARTIFACT,
        **candidate_provenance,
        "candidate_provenance_digest": runner.rc._domain_digest(
            runner.rc.CANARY_CANDIDATE_PROVENANCE_DOMAIN,
            candidate_provenance,
        ),
        "candidate_goal_digest": "e" * 64,
        "canary_output_sha256": runner.rc.CANARY_OUTPUT_SHA256,
        "confirmation_count": 1,
        "confirmation_digest_bound": True,
        "allowed_host_managed_delta_count": 0,
        "canary_workspace_identity_digest": route_digit * 64,
        "entry": "loopskill4",
        "finalization": "ACKNOWLEDGED",
        "fresh_until": fresh_text,
        "host_auth_after_digest": "1" * 64,
        "host_auth_before_digest": "1" * 64,
        "host_config_after_digest": "2" * 64,
        "host_config_before_digest": "2" * 64,
        "host_config_delta_kind": runner.rc.HOST_CONFIG_DELTA_NONE,
        "host_receipt_issuer": runner.rc.CANARY_ISSUER,
        "host_receipt_trust": runner.rc.CANARY_TRUST,
        "host_create_readback_count": goal_count,
        "host_lifecycle_readback_count": 1,
        "host_result_digest": "b" * 64,
        "host_task_create_count": goal_count,
        "host_task_identity_digest": route_digit * 64,
        "host_task_readback_count": goal_count,
        "host_terminal_wait_readback_count": goal_count,
        "host_total_read_count": 3 * goal_count + 1,
        "intake_external_effects": 0,
        "intake_heartbeat_count": 0,
        "intake_host_task_count": 0,
        "intake_loop_count": 0,
        "issued_at": issued_text,
        "integrity_measurement_digest": "4" * 64,
        "loopskill_mcp_registration_count": 0,
        "machine_owned_identity": True,
        "manual_control_identity_count": 0,
        "observed_at": issued_text,
        "observed_host_auth_changed_bytes": 0,
        "observed_host_config_changed_bytes": 0,
        "app_restart_count": 0,
        "prepare_delivery_count": 0,
        "prepare_heartbeat_count": 0,
        "prepare_host_effects": 0,
        "prepare_host_task_count": 0,
        "private_data_used": False,
        "provider_resend_count": 0,
        "provider_terminal_diagnostic_digest": runner.rc._domain_digest(
            runner.rc.CANARY_PROVIDER_DIAGNOSTIC_DOMAIN,
            [diagnostic for _ in range(goal_count)],
        ),
        "research_scored": False,
        "result": "ACKNOWLEDGED",
        "review": "PASS",
        "status": "PASS",
        "thread_content_retained": False,
        "unknown_preserved": True,
        "unexpected_changed_input_count": 0,
        "v3_bytes_changed": 0,
    }
    value["provenance_digest"] = runner.rc._domain_digest(
        runner.rc.CANARY_PROVENANCE_DOMAIN, value
    )
    value["host_receipt_digest"] = "d" * 64
    return value


def mock_target(test_id):
    deterministic = {
        "assertion_test_id": test_id,
        "status": "PASS",
        "tests_run": 1,
    }
    return {
        **deterministic,
        "result_digest": hashlib.sha256(runner.rc._canonical(deterministic)).hexdigest(),
    }


def mock_execution(case_id, family, test_id, contract, target_result=None):
    target = mock_target(test_id) if target_result is None else target_result
    mapping = {
        "assertion_test_id": test_id,
        "case_id": case_id,
        "case_contract_digest": hashlib.sha256(
            runner.rc._canonical(contract)
        ).hexdigest(),
        "coverage_status": "COVERED_BY_PASSING_TEST",
        "family": family,
        "fixture_selector": contract["fixture_selector"],
        "target_test_id": test_id,
        "target_test_result_digest": target["result_digest"],
    }
    return {
        **mapping,
        "result_digest": hashlib.sha256(
            runner.rc._canonical(mapping)
        ).hexdigest(),
        "target_test_result": target,
    }


class V4ConformanceRunnerTests(unittest.TestCase):
    def test_all_349_semantic_mappings_bind_to_an_executed_gate(self) -> None:
        candidate = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        with tempfile.TemporaryDirectory() as directory:
            issued = datetime.now(timezone.utc).replace(microsecond=0)
            path_2 = Path(directory) / "canary-2.json"
            path_8 = Path(directory) / "canary-8.json"
            path_2.write_bytes(
                runner.rc._canonical(
                    canary(
                        candidate,
                        goal_count=2,
                        route_digit="2",
                        issued=issued,
                    )
                )
            )
            path_8.write_bytes(
                runner.rc._canonical(
                    canary(
                        candidate,
                        goal_count=8,
                        route_digit="8",
                        issued=issued + timedelta(minutes=1),
                    )
                )
            )
            canary_digests = {
                2: hashlib.sha256(path_2.read_bytes()).hexdigest(),
                8: hashlib.sha256(path_8.read_bytes()).hexdigest(),
            }
            with mock.patch.object(
                runner,
                "_run_case",
                side_effect=mock_execution,
            ):
                receipt = runner.run(ROOT, candidate, path_2, path_8)
        self.assertEqual(receipt["case_count"], 349)
        self.assertEqual(receipt["mapped"], 349)
        self.assertEqual(receipt["semantic_coverage_mapping_count"], 349)
        self.assertEqual(receipt["test_method_count"], 74)
        self.assertEqual(
            receipt["evidence_profile"],
            "SEMANTIC_MAPPINGS_TO_UNIQUE_EXECUTED_ASSERTIONS",
        )
        self.assertIs(receipt["independent_case_observation_claimed"], False)
        self.assertEqual(receipt["failed"], 0)
        self.assertEqual(
            [item["case_id"] for item in receipt["case_results"]],
            sorted({item["case_id"] for item in receipt["case_results"]}),
        )
        real = {
            item["case_id"]: item
            for item in receipt["case_results"]
            if "REAL_APP_RECEIPT" in item["evidence_kind"]
        }
        self.assertEqual(set(real), {"CAP-RELEASE-CANARY", "UX-009-a"})
        self.assertGreater(receipt["test_method_count"], 1)
        self.assertTrue(
            all(item["coverage_mapping_count"] == 1 for item in receipt["case_results"])
        )
        runner.rc.validate_conformance_receipt(
            receipt,
            candidate,
            ROOT,
            expected_canary_sha256=canary_digests,
        )
        with self.assertRaisesRegex(
            runner.rc.RcValidationError, "RC_CONFORMANCE_RECEIPT_INVALID"
        ):
            runner.rc.validate_conformance_receipt(
                receipt,
                candidate,
                ROOT,
                expected_canary_sha256={2: "f" * 64, 8: "f" * 64},
            )

    def test_single_method_execution_requires_exactly_one_real_test(self) -> None:
        test_id = runner.FAMILY_TEST_BINDINGS["CAP-ARCHITECTURE"]
        result = runner._run_test(test_id)
        self.assertEqual(result["assertion_test_id"], test_id)
        self.assertEqual(result["tests_run"], 1)
        with self.assertRaisesRegex(RuntimeError, "CONFORMANCE_TEST_(?:ID_INVALID|FAILED)"):
            runner._run_test("test_v4_preservation_register.DoesNotExist.test_missing")
        candidate = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        _, _, bindings = runner._catalog_and_bindings(ROOT, candidate)
        family, bound_test, contract = bindings["CAP-ARCHITECTURE-ONE-WRITER"]
        self.assertEqual(bound_test, test_id)
        atomic = runner._run_case(
            "CAP-ARCHITECTURE-ONE-WRITER", family, test_id, contract
        )
        self.assertEqual(atomic["case_id"], "CAP-ARCHITECTURE-ONE-WRITER")
        self.assertEqual(atomic["target_test_id"], test_id)
        with self.assertRaisesRegex(RuntimeError, "CONFORMANCE_CASE_CONTRACT_INVALID"):
            runner._run_case(
                "CAP-ARCHITECTURE-NOT-IN-CORPUS",
                "CAP-ARCHITECTURE",
                test_id,
                None,
            )
        changed = dict(contract)
        changed["expected_acceptance"] = (
            "REJECT" if contract["expected_acceptance"] == "ACCEPT" else "ACCEPT"
        )
        with self.assertRaisesRegex(RuntimeError, "CONFORMANCE_CASE_CONTRACT_INVALID"):
            runner._run_case(
                "CAP-ARCHITECTURE-ONE-WRITER", family, test_id, changed
            )
        intake_family, intake_test, intake_contract = bindings["CAP-INTAKE-G01"]
        self_consistent_wrong = dict(intake_contract)
        self_consistent_wrong["expected_acceptance"] = "REJECT"
        original = runner._ACTIVE_CASE_CONTRACTS["CAP-INTAKE-G01"]
        runner._ACTIVE_CASE_CONTRACTS["CAP-INTAKE-G01"] = self_consistent_wrong
        try:
            with self.assertRaisesRegex(RuntimeError, "CONFORMANCE_CASE_CONTRACT_INVALID"):
                runner._run_case(
                    "CAP-INTAKE-G01",
                    intake_family,
                    intake_test,
                    self_consistent_wrong,
                )
        finally:
            runner._ACTIVE_CASE_CONTRACTS["CAP-INTAKE-G01"] = original
        unrelated = runner.FAMILY_TEST_BINDINGS["CAP-ARCHITECTURE"]
        wrong_target = dict(intake_contract)
        wrong_target["target_test_id"] = unrelated
        runner._ACTIVE_CASE_CONTRACTS["CAP-INTAKE-G01"] = wrong_target
        try:
            with self.assertRaisesRegex(RuntimeError, "CONFORMANCE_CASE_CONTRACT_INVALID"):
                runner._run_case(
                    "CAP-INTAKE-G01", intake_family, unrelated, wrong_target
                )
        finally:
            runner._ACTIVE_CASE_CONTRACTS["CAP-INTAKE-G01"] = original
        changed = dict(contract)
        changed["expected_side_effect_counts"] = {
            **contract["expected_side_effect_counts"],
            "canonical_commits": 999,
        }
        with self.assertRaisesRegex(RuntimeError, "CONFORMANCE_CASE_CONTRACT_INVALID"):
            runner._run_case(
                "CAP-ARCHITECTURE-ONE-WRITER", family, test_id, changed
            )

    def test_hosted_run_executes_all_bindings_without_faking_exec_receipt(self) -> None:
        candidate = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        with mock.patch.object(runner, "_run_test", side_effect=mock_target) as targets:
            with mock.patch.object(
                runner,
                "_run_case",
                side_effect=mock_execution,
            ) as executed:
                receipt = runner.hosted_run(ROOT, candidate)
        self.assertEqual(receipt["case_count"], 349)
        self.assertEqual(receipt["deterministic_assertion_method_count"], 74)
        self.assertEqual(
            receipt["evidence_profile"],
            "SEMANTIC_MAPPINGS_TO_UNIQUE_EXECUTED_ASSERTIONS",
        )
        self.assertIs(receipt["independent_case_observation_claimed"], False)
        self.assertEqual(receipt["real_external_effects"], 0)
        self.assertEqual(receipt["status"], "PASS_LOCAL_APP_GATE_REQUIRED")
        self.assertEqual(
            receipt["local_exact_sha_app_case_ids"],
            ["CAP-RELEASE-CANARY", "UX-009-a"],
        )
        self.assertEqual(targets.call_count, receipt["deterministic_assertion_method_count"])
        self.assertEqual(executed.call_count, receipt["semantic_coverage_mapping_count"])


if __name__ == "__main__":
    unittest.main()
