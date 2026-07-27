from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "measure_v4_beta.py"
SPEC = importlib.util.spec_from_file_location("measure_v4_beta", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
measurement = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(measurement)
RUNNER_PATH = ROOT / "scripts" / "run_v4_beta_fixture.py"
RUNNER_SPEC = importlib.util.spec_from_file_location("run_v4_beta_fixture", RUNNER_PATH)
assert RUNNER_SPEC is not None and RUNNER_SPEC.loader is not None
runner = importlib.util.module_from_spec(RUNNER_SPEC)
RUNNER_SPEC.loader.exec_module(runner)


class V4BetaMeasurementTests(unittest.TestCase):
    def test_v3_baseline_is_exact_and_precomparison(self) -> None:
        result = measurement.freeze_v3(measurement.DEFAULT_SCENARIO)
        self.assertEqual(result["status"], "BASELINE_FROZEN_PRE_V4_COMPARISON")
        self.assertEqual(
            result["v3_source_commit"],
            "843945d9d34e7f065b65d9172ea4a2df66c0f2e3",
        )
        self.assertEqual(result["v3_input_bytes"], 3784)
        self.assertEqual(result["v3_pack_bytes"], 70805)
        self.assertEqual(result["v3_guide_bytes"], 7079)
        self.assertEqual(result["v3_internal_control_interactions"], 19)
        self.assertEqual(
            result["blocking_thresholds"],
            {
                "v4_pack_bytes_max": 32768,
                "v4_internal_control_interactions_max": 9,
                "internal_control_interaction_reduction_min": "1/2",
            },
        )
        self.assertEqual(result["real_external_effects"], 0)

    def test_comparison_identity_and_both_thresholds_fail_closed(self) -> None:
        baseline = measurement.freeze_v3(measurement.DEFAULT_SCENARIO)
        scenario = measurement._strict_json(measurement.DEFAULT_SCENARIO)
        identity = {
            "artifact": "loopskill-v4-p7-comparison-input-v1",
            "scenario_sha256": baseline["scenario_sha256"],
            "measurement_code_sha256": baseline["measurement_code_sha256"],
        }
        good_metrics = {
            "pack_bytes": 32768,
            "internal_control_interactions": 9,
            "user_start_actions": 1,
            "authorization_confirmations": 1,
            "host_interactions": 5,
            "protocol_calls": 11,
            "local_writes": 12,
            "latency_ns": 1,
            "unknown_count": 0,
            "human_interventions": 1,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline_path = root / "baseline.json"
            receipt_path = root / "receipt.json"
            baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
            receipt_path.write_text(
                json.dumps({**identity, "metrics": good_metrics}), encoding="utf-8"
            )
            accepted = measurement.compare_v4(
                measurement.DEFAULT_SCENARIO, baseline_path, receipt_path
            )
            self.assertEqual(accepted["status"], "PASS")
            for changed in (
                {**good_metrics, "pack_bytes": 32769},
                {**good_metrics, "internal_control_interactions": 10},
            ):
                receipt_path.write_text(
                    json.dumps({**identity, "metrics": changed}), encoding="utf-8"
                )
                rejected = measurement.compare_v4(
                    measurement.DEFAULT_SCENARIO, baseline_path, receipt_path
                )
                self.assertEqual(rejected["status"], "FAIL")

    def test_real_local_v4_fixture_passes_frozen_comparator(self) -> None:
        receipt = runner.run_fixture()
        self.assertEqual(receipt["real_external_effects"], 0)
        self.assertEqual(receipt["canonical_commits"], 11)
        self.assertEqual(receipt["event_count"], 18)
        self.assertEqual(receipt["execution_disposition"], "SUCCEEDED")
        self.assertEqual(receipt["closure_assurance"], "STRICT")
        self.assertEqual(receipt["metrics"]["protocol_calls"], 11)
        self.assertEqual(receipt["metrics"]["host_interactions"], 3)
        self.assertEqual(receipt["metrics"]["internal_control_interactions"], 3)
        with tempfile.TemporaryDirectory() as temporary:
            receipt_path = Path(temporary) / "receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            result = measurement.compare_v4(
                measurement.DEFAULT_SCENARIO,
                runner.BASELINE,
                receipt_path,
            )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["pack_gate"], "PASS")
        self.assertEqual(result["internal_control_interaction_gate"], "PASS")


if __name__ == "__main__":
    unittest.main()
