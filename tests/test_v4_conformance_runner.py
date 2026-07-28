from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts/run_v4_conformance.py"
SPEC = importlib.util.spec_from_file_location("run_v4_conformance", PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def canary(candidate: str) -> dict:
    value = {
        "artifact": "loopskill-v4-disposable-app-canary-v1",
        "candidate_sha": candidate,
        "candidate_goal_digest": "e" * 64,
        "canary_output_sha256": "b" * 64,
        "confirmation_count": 1,
        "confirmation_digest_bound": True,
        "config_bytes_changed": 0,
        "entry": "loopskill4",
        "finalization": "ACKNOWLEDGED",
        "fresh_until": "2026-07-27T13:22:46Z",
        "host_receipt_issuer": runner.rc.CANARY_ISSUER,
        "host_receipt_trust": runner.rc.CANARY_TRUST,
        "host_task_create_count": 1,
        "host_task_identity_digest": "c" * 64,
        "host_task_readback_count": 1,
        "intake_external_effects": 0,
        "intake_heartbeat_count": 0,
        "intake_host_task_count": 0,
        "intake_loop_count": 0,
        "issued_at": "2026-07-27T13:12:46Z",
        "loopskill_mcp_registration_count": 0,
        "machine_owned_identity": True,
        "manual_control_identity_count": 0,
        "observed_at": "2026-07-27T13:12:46Z",
        "app_restart_count": 0,
        "prepare_delivery_count": 0,
        "prepare_heartbeat_count": 0,
        "prepare_host_effects": 0,
        "prepare_host_task_count": 0,
        "private_data_used": False,
        "provider_resend_count": 0,
        "research_scored": False,
        "result": "ACKNOWLEDGED",
        "review": "PASS",
        "status": "PASS",
        "thread_content_retained": False,
        "unknown_preserved": True,
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
    def test_all_349_instances_bind_to_an_executed_gate(self) -> None:
        candidate = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canary.json"
            path.write_text(json.dumps(canary(candidate)), encoding="utf-8")
            with mock.patch.object(
                runner,
                "_run_case",
                side_effect=mock_execution,
            ):
                receipt = runner.run(ROOT, candidate, path)
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
        runner.rc.validate_conformance_receipt(receipt, candidate, ROOT)

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

    def test_hosted_run_executes_all_bindings_without_faking_app_receipt(self) -> None:
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
