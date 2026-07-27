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
                side_effect=lambda case_id, family, test_id: {
                    "assertion_test_id": f"{case_id}::{test_id}",
                    "case_id": case_id,
                    "family": family,
                    "result_digest": hashlib.sha256(
                        runner.rc._canonical(
                            {
                                "assertion_test_id": f"{case_id}::{test_id}",
                                "case_id": case_id,
                                "family": family,
                                "status": "PASS",
                                "target_test_id": test_id,
                                "tests_run": 1,
                            }
                        )
                    ).hexdigest(),
                    "status": "PASS",
                    "target_test_id": test_id,
                    "tests_run": 1,
                },
            ):
                receipt = runner.run(ROOT, candidate, path)
        self.assertEqual(receipt["case_count"], 349)
        self.assertEqual(receipt["passed"], 349)
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
            all(item["assertion_count"] == 1 for item in receipt["case_results"])
        )
        runner.rc.validate_conformance_receipt(receipt, candidate, ROOT)

    def test_single_method_execution_requires_exactly_one_real_test(self) -> None:
        test_id = runner.FAMILY_TEST_BINDINGS["CAP-ARCHITECTURE"]
        result = runner._run_test(test_id)
        self.assertEqual(result["assertion_test_id"], test_id)
        self.assertEqual(result["tests_run"], 1)
        with self.assertRaisesRegex(RuntimeError, "CONFORMANCE_TEST_(?:ID_INVALID|FAILED)"):
            runner._run_test("test_v4_preservation_register.DoesNotExist.test_missing")
        atomic = runner._run_case("CAP-ARCHITECTURE-ONE-WRITER", "CAP-ARCHITECTURE", test_id)
        self.assertEqual(atomic["case_id"], "CAP-ARCHITECTURE-ONE-WRITER")
        self.assertEqual(atomic["target_test_id"], test_id)

    def test_hosted_run_executes_all_bindings_without_faking_app_receipt(self) -> None:
        candidate = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        with mock.patch.object(
            runner,
            "_run_case",
            side_effect=lambda case_id, family, test_id: {
                "assertion_test_id": f"{case_id}::{test_id}",
                "case_id": case_id,
                "family": family,
                "result_digest": "d" * 64,
                "status": "PASS",
                "target_test_id": test_id,
                "tests_run": 1,
            },
        ) as executed:
            receipt = runner.hosted_run(ROOT, candidate)
        self.assertEqual(receipt["case_count"], 349)
        self.assertEqual(receipt["real_external_effects"], 0)
        self.assertEqual(receipt["status"], "PASS_LOCAL_APP_GATE_REQUIRED")
        self.assertEqual(
            receipt["local_exact_sha_app_case_ids"],
            ["CAP-RELEASE-CANARY", "UX-009-a"],
        )
        self.assertEqual(executed.call_count, receipt["deterministic_assertion_method_count"])


if __name__ == "__main__":
    unittest.main()
