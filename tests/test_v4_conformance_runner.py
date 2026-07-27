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
        "canary_output_sha256": "b" * 64,
        "confirmation_count": 1,
        "finalization": "ACKNOWLEDGED",
        "fresh_until": "2026-07-27T13:22:46Z",
        "host_receipt_issuer": runner.rc.CANARY_ISSUER,
        "host_receipt_trust": runner.rc.CANARY_TRUST,
        "host_task_create_count": 1,
        "host_task_identity_digest": "c" * 64,
        "host_task_readback_count": 1,
        "intake_external_effects": 0,
        "issued_at": "2026-07-27T13:12:46Z",
        "machine_owned_identity": True,
        "manual_control_identity_count": 0,
        "observed_at": "2026-07-27T13:12:46Z",
        "prepare_host_effects": 0,
        "private_data_used": False,
        "provider_resend_count": 0,
        "research_scored": False,
        "result": "ACKNOWLEDGED",
        "review": "PASS",
        "status": "PASS",
        "thread_content_retained": False,
        "unknown_preserved": True,
    }
    value["provenance_digest"] = runner.rc._domain_digest(
        runner.rc.CANARY_PROVENANCE_DOMAIN, value
    )
    value["host_receipt_digest"] = value["provenance_digest"]
    return value


class V4ConformanceRunnerTests(unittest.TestCase):
    def test_all_343_instances_bind_to_an_executed_gate(self) -> None:
        candidate = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canary.json"
            path.write_text(json.dumps(canary(candidate)), encoding="utf-8")
            with mock.patch.object(
                runner,
                "_run_test",
                side_effect=lambda test_id: {
                    "assertion_test_id": test_id,
                    "result_digest": hashlib.sha256(
                        runner.rc._canonical(
                            {"assertion_test_id": test_id, "status": "PASS", "tests_run": 1}
                        )
                    ).hexdigest(),
                    "status": "PASS",
                    "tests_run": 1,
                },
            ):
                receipt = runner.run(ROOT, candidate, path)
        self.assertEqual(receipt["case_count"], 343)
        self.assertEqual(receipt["passed"], 343)
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


if __name__ == "__main__":
    unittest.main()
