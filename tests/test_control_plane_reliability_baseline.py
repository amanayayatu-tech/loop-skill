from __future__ import annotations

import json
import os
import subprocess

from state_runtime_support import *  # noqa: F403


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "control_plane_reliability"
BASELINE_BUGS_MUST_FAIL = os.environ.get("LOOP_BASELINE_BUGS_MUST_FAIL") == "1"


def baseline_expected_failure(test):
    return test if BASELINE_BUGS_MUST_FAIL else unittest.expectedFailure(test)


class ControlPlaneFixtureTests(unittest.TestCase):
    def test_fixture_builder_is_deterministic(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(FIXTURE_DIR / "build_fixtures.py"),
                "--check",
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_transport_fixture_is_exactly_8265_bytes(self) -> None:
        fixture = json.loads((FIXTURE_DIR / "transport-8265.json").read_text())
        payload = fixture["frame"].encode("utf-8")
        self.assertEqual(len(payload), 8265)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), fixture["frame_sha256"])

    def test_source_baseline_matches_v324_release_identity(self) -> None:
        fixture = json.loads(
            (FIXTURE_DIR / "source-v3.2.4-baseline.json").read_text()
        )
        self.assertEqual(
            fixture["source_commit"],
            "f83e5f0ba590792ac00afb463b8628afaf7ca8c1",
        )
        self.assertEqual(fixture["file_count"], 20)
        self.assertEqual(
            fixture["manifest_sha256"],
            "34834831f4124405df91771049b31edf21e2efda9b7c7046b8a51df3a375f3fc",
        )


class UnclosedControlPlaneFindingTests(AdaptiveStateRuntimeTestCase):  # noqa: F405
    @baseline_expected_failure
    def test_same_real_turn_cannot_route_twice_with_different_claimed_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            first = harness.apply(
                {
                    "type": "ACQUIRE_LEASE",
                    "routing_turn_id": "same-real-turn-route-a",
                    "lease_id": "same-real-turn-lease-a",
                    "owner_kind": "GOAL_TURN",
                    "owner_identity": "controller-1",
                    "observed_at": T1,
                    "expires_at": T4,
                    "controller_turn_id": "model-claim-a",
                }
            )
            self.assertTrue(first["ok"], first)
            released = harness.apply(
                {
                    "type": "RELEASE_LEASE",
                    "lease_claim": first["result"]["lease_claim"],
                    "observed_at": T1,
                    "reason_code": "NO_ROUTE_READY",
                }
            )
            self.assertTrue(released["ok"], released)
            before = persisted_snapshot(root)
            second = harness.apply(
                {
                    "type": "ACQUIRE_LEASE",
                    "routing_turn_id": "same-real-turn-route-b",
                    "lease_id": "same-real-turn-lease-b",
                    "owner_kind": "GOAL_TURN",
                    "owner_identity": "controller-1",
                    "observed_at": T1,
                    "expires_at": T4,
                    "controller_turn_id": "model-claim-b",
                }
            )
            self.assertFalse(second["ok"], second)
            self.assertEqual(before, persisted_snapshot(root))

    @baseline_expected_failure
    def test_external_receipt_requires_canonical_route_and_provider_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = Harness(Path(temporary))
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            before = persisted_snapshot(Path(temporary))
            with self.assertRaises(state_runtime_module.RuntimeRejection) as context:
                harness.runtime.stage_external_receipt(
                    {
                        "receipt_id": "underbound-receipt",
                        "phase": "STARTED",
                        "action_kind": "LOCAL_VERIFICATION",
                        "request_digest": digest("underbound-request"),
                        "observed_at": T1,
                        "calls_consumed": 1,
                    }
                )
            self.assertEqual(context.exception.code, "EXTERNAL_RECEIPT_IDENTITY_INCOMPLETE")
            self.assertEqual(before, persisted_snapshot(Path(temporary)))

    @baseline_expected_failure
    def test_external_receipt_rejects_completion_before_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = Harness(Path(temporary))
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            started_request = {
                "receipt_id": "time-order-receipt",
                "phase": "STARTED",
                "action_kind": "EXTERNAL_MODEL_CALL",
                "request_digest": digest("time-order-request"),
                "observed_at": T2,
                "calls_consumed": 1,
            }
            started = harness.runtime.stage_external_receipt(started_request)
            before = persisted_snapshot(Path(temporary))
            with self.assertRaises(state_runtime_module.RuntimeRejection) as context:
                harness.runtime.stage_external_receipt(
                    {
                        **started_request,
                        "phase": "COMPLETED",
                        "observed_at": T1,
                        "started_receipt_digest": started["receipt_digest"],
                        "result_status": "BLOCKED",
                        "artifact_digest": digest("time-order-artifact"),
                        "process_exit_code": 0,
                        "usage": {
                            "prompt_tokens": None,
                            "completion_tokens": None,
                            "total_tokens": None,
                            "complete": False,
                        },
                    }
                )
            self.assertEqual(context.exception.code, "EXTERNAL_RECEIPT_TIME_ORDER_INVALID")
            self.assertEqual(before, persisted_snapshot(Path(temporary)))

    @baseline_expected_failure
    def test_external_receipt_rejects_pass_with_nonzero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = Harness(Path(temporary))
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            started_request = {
                "receipt_id": "exit-status-receipt",
                "phase": "STARTED",
                "action_kind": "EXTERNAL_MODEL_CALL",
                "request_digest": digest("exit-status-request"),
                "observed_at": T1,
                "calls_consumed": 1,
            }
            started = harness.runtime.stage_external_receipt(started_request)
            before = persisted_snapshot(Path(temporary))
            with self.assertRaises(state_runtime_module.RuntimeRejection) as context:
                harness.runtime.stage_external_receipt(
                    {
                        **started_request,
                        "phase": "COMPLETED",
                        "observed_at": T2,
                        "started_receipt_digest": started["receipt_digest"],
                        "result_status": "PASS",
                        "artifact_digest": digest("exit-status-artifact"),
                        "process_exit_code": 137,
                        "usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 5,
                            "total_tokens": 15,
                            "complete": True,
                        },
                    }
                )
            self.assertEqual(context.exception.code, "EXTERNAL_RECEIPT_RESULT_INCONSISTENT")
            self.assertEqual(before, persisted_snapshot(Path(temporary)))

    @baseline_expected_failure
    def test_external_receipt_rejects_invalid_usage_arithmetic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = Harness(Path(temporary))
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            started_request = {
                "receipt_id": "usage-arithmetic-receipt",
                "phase": "STARTED",
                "action_kind": "EXTERNAL_MODEL_CALL",
                "request_digest": digest("usage-arithmetic-request"),
                "observed_at": T1,
                "calls_consumed": 1,
            }
            started = harness.runtime.stage_external_receipt(started_request)
            before = persisted_snapshot(Path(temporary))
            with self.assertRaises(state_runtime_module.RuntimeRejection) as context:
                harness.runtime.stage_external_receipt(
                    {
                        **started_request,
                        "phase": "COMPLETED",
                        "observed_at": T2,
                        "started_receipt_digest": started["receipt_digest"],
                        "result_status": "PASS",
                        "artifact_digest": digest("usage-arithmetic-artifact"),
                        "process_exit_code": 0,
                        "usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 5,
                            "total_tokens": 99,
                            "complete": True,
                        },
                    }
                )
            self.assertEqual(context.exception.code, "EXTERNAL_RECEIPT_USAGE_INVALID")
            self.assertEqual(before, persisted_snapshot(Path(temporary)))

    @baseline_expected_failure
    def test_worker_ack_projects_current_artifact_validations_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            harness.ensure_controller_goal()
            harness.register_control_result(
                "THREAD",
                "projection-worker-create",
                "controller-1",
                {"role_kind": "WORKER"},
                {"thread_id": "projection-worker", "role_kind": "WORKER", "worktree_path": "."},
            )
            claim = harness.acquire()
            definition = harness.definitions["g1"]
            prepared, payload = harness.prepare_outbox(
                claim,
                "DISPATCH",
                "projection-dispatch",
                {
                    "goal_id": "g1",
                    "goal_definition_digest": definition["payload_template_digest"],
                },
                target_id="projection-worker",
            )
            self.assertTrue(prepared["ok"], prepared)
            sent = harness.mark_sent(
                claim,
                "DISPATCH",
                "projection-dispatch",
                payload,
                target_id="projection-worker",
            )
            self.assertTrue(sent["ok"], sent)
            artifact_digest = digest("projection-current-artifact")
            result = {"status": "PASS", "artifact_digest": artifact_digest}
            report_content = harness.formal_report_content(
                "DISPATCH",
                "projection-dispatch",
                result,
                extra_fields={
                    "validation_results": [
                        {
                            "dimension": "functional",
                            "status": "PASS",
                            "artifact_digest": artifact_digest,
                            "evidence_paths": [],
                        }
                    ]
                },
            )
            acked = harness.ack_outbox(
                claim,
                "DISPATCH",
                "projection-dispatch",
                payload,
                target_id="projection-worker",
                result={
                    **result,
                    "report_digest": digest(report_content),
                },
                report_content=report_content,
            )
            self.assertTrue(acked["ok"], acked)
            state = harness.state()
            self.assertEqual(state["validation_results"]["g1"]["functional"], "PASS")
            self.assertEqual(
                state["validation_evidence_identity"]["g1"]["functional"]["artifact_digest"],
                artifact_digest,
            )


if __name__ == "__main__":
    unittest.main()
