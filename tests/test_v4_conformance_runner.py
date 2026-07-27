from __future__ import annotations

import importlib.util
import json
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
    return {
        "artifact": "loopskill-v4-disposable-app-canary-v1",
        "candidate_sha": candidate,
        "confirmation_count": 1,
        "finalization": "ACKNOWLEDGED",
        "host_receipt_digest": "a" * 64,
        "host_task_create_count": 1,
        "host_task_readback_count": 1,
        "intake_external_effects": 0,
        "machine_owned_identity": True,
        "manual_control_identity_count": 0,
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


class V4ConformanceRunnerTests(unittest.TestCase):
    def test_all_343_instances_bind_to_an_executed_gate(self) -> None:
        candidate = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canary.json"
            path.write_text(json.dumps(canary(candidate)), encoding="utf-8")
            with mock.patch.object(
                runner,
                "_run_module",
                side_effect=lambda root, module: {
                    "module": module,
                    "output_sha256": "b" * 64,
                    "status": "PASS",
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
        runner.rc.validate_conformance_receipt(receipt, candidate)


if __name__ == "__main__":
    unittest.main()
