from __future__ import annotations

import copy
import json

from state_runtime_support import *  # noqa: F403


class RealIncidentRepairAccountingTests(AdaptiveStateRuntimeTestCase):  # noqa: F405
    @staticmethod
    def _v208_fixture() -> dict[str, Any]:
        path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "v208-worker-classification-incident.json"
        )
        return json.loads(path.read_text(encoding="utf-8"))

    def _ack_worker(
        self,
        harness: Harness,
        definition: dict[str, Any],
        index: int,
        *,
        execution_started: bool,
        blocker_code: str = "DISPATCH_FRESHNESS_SNAPSHOT_MISMATCH",
    ) -> dict[str, Any]:
        claim = harness.acquire()
        outbox_id = f"incident-dispatch-{index}"
        prepared, payload = harness.prepare_outbox(
            claim,
            "DISPATCH",
            outbox_id,
            {
                "goal_id": "g1",
                "goal_definition_digest": definition["payload_template_digest"],
            },
            target_id="incident-worker",
        )
        self.assertTrue(prepared["ok"], prepared)
        sent = harness.mark_sent(
            claim,
            "DISPATCH",
            outbox_id,
            payload,
            target_id="incident-worker",
        )
        self.assertTrue(sent["ok"], sent)
        result: dict[str, Any] = {
            "status": "BLOCKED" if not execution_started else "FAIL",
            "artifact_digest": digest(f"incident-artifact-{index}"),
            "execution_started": execution_started,
        }
        if not execution_started:
            result["blocker_code"] = blocker_code
        report_content = harness.formal_report_content(
            "DISPATCH", outbox_id, result
        )
        acked = harness.ack_outbox(
            claim,
            "DISPATCH",
            outbox_id,
            payload,
            target_id="incident-worker",
            result={**result, "report_digest": digest(report_content)},
            report_content=report_content,
        )
        self.assertTrue(acked["ok"], acked)
        return acked

    def _build_v208_incident(
        self, root: Path
    ) -> tuple[Harness, dict[str, Any], dict[str, Any]]:
        fixture = self._v208_fixture()
        definition = goal(fixture["goal_id"], fixture["milestone_id"])
        definitions = {fixture["goal_id"]: definition}
        milestones = [milestone(fixture["milestone_id"], "ACTIVE")]
        harness = Harness(root)
        initialized, _ = harness.initialize(
            definitions=definitions,
            milestones=milestones,
            queue=[
                queue_entry(
                    fixture["goal_id"], fixture["milestone_id"], "READY", 1
                )
            ],
            authorization=authorization_envelope(definitions, milestones),
        )
        self.assertTrue(initialized["ok"], initialized)
        harness.ensure_controller_goal()
        harness.register_control_result(
            "THREAD",
            "v208-worker-create",
            "controller-1",
            {"role_kind": "WORKER"},
            {
                "thread_id": fixture["worker_thread_id"],
                "role_kind": "WORKER",
                "worktree_path": ".",
            },
        )

        def ack(dispatch_id: str, status: str, execution_started: bool) -> None:
            claim = harness.acquire()
            prepared, payload = harness.prepare_outbox(
                claim,
                "DISPATCH",
                dispatch_id,
                {
                    "goal_id": fixture["goal_id"],
                    "goal_definition_digest": definition["payload_template_digest"],
                },
                target_id=fixture["worker_thread_id"],
            )
            self.assertTrue(prepared["ok"], prepared)
            self.assertTrue(
                harness.mark_sent(
                    claim,
                    "DISPATCH",
                    dispatch_id,
                    payload,
                    target_id=fixture["worker_thread_id"],
                )["ok"]
            )
            result: dict[str, Any] = {
                "status": status,
                "artifact_digest": fixture["shared_artifact_digest"],
                "execution_started": execution_started,
            }
            extra_fields = None
            if not execution_started:
                result["blocker_code"] = fixture["blocker_code"]
                extra_fields = fixture["report_shape"]
            report_content = harness.formal_report_content(
                "DISPATCH", dispatch_id, result, extra_fields=extra_fields
            )
            staged = harness.runtime.stage_formal_report(
                {
                    "outbox_id": dispatch_id,
                    "result": result,
                    "report_text": report_content,
                }
            )
            acked = harness.ack_outbox(
                claim,
                "DISPATCH",
                dispatch_id,
                payload,
                target_id=fixture["worker_thread_id"],
                result={**result, "report_digest": staged["report_digest"]},
                report_content=report_content,
            )
            self.assertTrue(acked["ok"], acked)

        # A first product execution opens a legal repair route. The fixture
        # then projects it as the unchanged historical PASS seen at real v208.
        ack(fixture["initial_dispatch_id"], "FAIL", True)
        ack(fixture["rejected_dispatch_id"], "BLOCKED", False)

        state = harness.state()
        ledger = state["goal_execution_ledger"][fixture["goal_id"]]
        initial, rejected = ledger["attempts"]
        initial["status"] = "PASS"

        # Recreate the pre-v3.2.3 ACK projection loss while preserving the
        # immutable archived report and its bounded blocker evidence.
        report_path = rejected["evidence_paths"][0]
        archived_digest = rejected["report_digest"]
        rejected["execution_started"] = True
        rejected.pop("blocker_code", None)
        ledger["latest_worker"] = copy.deepcopy(rejected)
        harness.runtime._write_state_locked(state, "sanitized-real-v208-fixture")

        steering_id = "v208-fixture-pause"
        recorded = harness.apply(
            {
                "type": "RECORD_STEERING",
                "steering_id": steering_id,
                "steering_type": "PAUSE",
                "normalized_digest": digest("v208 fixture pause"),
                "identity_algorithm": "message-item-v1",
                "message_item_id": "v208-fixture-message",
                "summary": "pause for fixture reconciliation",
                "classification_reason": "real incident regression",
            }
        )
        self.assertTrue(recorded["ok"], recorded)
        paused = harness.apply(
            {
                "type": "SET_RUN_CONTROL",
                "steering_id": steering_id,
                "requested_status": "PAUSE",
                "reason": "real incident reconciliation fixture",
            }
        )
        self.assertTrue(paused["ok"], paused)
        mutation = {
            "type": "RECONCILE_WORKER_EXECUTION_CLASSIFICATION",
            "goal_id": fixture["goal_id"],
            "dispatch_id": fixture["rejected_dispatch_id"],
            "report_path": report_path,
            "report_digest": archived_digest,
            "blocker_code": fixture["blocker_code"],
            "reason": "archived report proves validation rejected before execution",
        }
        return harness, fixture, mutation

    def test_freshness_blocked_does_not_consume_repair_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = Harness(Path(temporary))
            definitions = {"g1": goal("g1", "m1")}
            milestones = [milestone("m1", "ACTIVE")]
            authorization = authorization_envelope(definitions, milestones)
            authorization["repair_policy"]["max_repair_attempts_per_goal"] = 5
            initialized, _ = harness.initialize(
                definitions=definitions,
                milestones=milestones,
                authorization=authorization,
            )
            self.assertTrue(initialized["ok"], initialized)
            harness.ensure_controller_goal()
            harness.register_control_result(
                "THREAD",
                "incident-worker-create",
                "controller-1",
                {"role_kind": "WORKER"},
                {
                    "thread_id": "incident-worker",
                    "role_kind": "WORKER",
                    "worktree_path": ".",
                },
            )

            # Initial execution + three real repairs consume four product slots.
            for index in range(1, 5):
                self._ack_worker(
                    harness, definitions["g1"], index, execution_started=True
                )
            # Two control-plane closures remain durable history but consume zero.
            for index in range(5, 7):
                self._ack_worker(
                    harness, definitions["g1"], index, execution_started=False
                )

            # The next two real repairs are still legal despite the two closures.
            for index in range(7, 9):
                self._ack_worker(
                    harness, definitions["g1"], index, execution_started=True
                )

            state = harness.state()
            attempts = state["goal_execution_ledger"]["g1"]["attempts"]
            self.assertEqual(len(attempts), 8)
            self.assertEqual(
                sum(item.get("execution_started", True) for item in attempts), 6
            )
            claim = harness.acquire()
            rejected, _ = harness.prepare_outbox(
                claim,
                "DISPATCH",
                "incident-dispatch-9",
                {
                    "goal_id": "g1",
                    "goal_definition_digest": definitions["g1"][
                        "payload_template_digest"
                    ],
                },
                target_id="incident-worker",
            )
            self.assertEqual(rejected["status"], "REPAIR_BUDGET_EXHAUSTED")
            self.assertEqual(rejected["error"]["details"]["completed_attempts"], 6)

    def test_zero_execution_requires_bounded_control_plane_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = Harness(Path(temporary))
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            harness.ensure_controller_goal()
            harness.register_control_result(
                "THREAD",
                "worker-create",
                "controller-1",
                {"role_kind": "WORKER"},
                {"thread_id": "worker-1", "role_kind": "WORKER", "worktree_path": "."},
            )
            claim = harness.acquire()
            definition = harness.definitions["g1"]
            prepared, payload = harness.prepare_outbox(
                claim,
                "DISPATCH",
                "bad-zero-execution",
                {
                    "goal_id": "g1",
                    "goal_definition_digest": definition["payload_template_digest"],
                },
                target_id="worker-1",
            )
            self.assertTrue(prepared["ok"], prepared)
            self.assertTrue(
                harness.mark_sent(
                    claim,
                    "DISPATCH",
                    "bad-zero-execution",
                    payload,
                    target_id="worker-1",
                )["ok"]
            )
            result = {
                "status": "BLOCKED",
                "artifact_digest": digest("bad-zero-artifact"),
                "execution_started": False,
                "blocker_code": "UNBOUNDED_MODEL_JUDGMENT",
            }
            report = harness.formal_report_content(
                "DISPATCH", "bad-zero-execution", result
            )
            before = persisted_snapshot(Path(temporary))
            response = harness.ack_outbox(
                claim,
                "DISPATCH",
                "bad-zero-execution",
                payload,
                target_id="worker-1",
                result={**result, "report_digest": digest(report)},
                report_content=report,
            )
            self.assertFalse(response["ok"])
            self.assertEqual(
                response["status"], "WORKER_ZERO_EXECUTION_BLOCKER_INVALID"
            )
            self.assertEqual(before, persisted_snapshot(Path(temporary)))

    def test_staging_binds_report_classification_when_handle_result_omits_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = Harness(Path(temporary))
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            harness.ensure_controller_goal()
            harness.register_control_result(
                "THREAD",
                "worker-create",
                "controller-1",
                {"role_kind": "WORKER"},
                {"thread_id": "worker-1", "role_kind": "WORKER", "worktree_path": "."},
            )
            claim = harness.acquire()
            definition = harness.definitions["g1"]
            prepared, payload = harness.prepare_outbox(
                claim,
                "DISPATCH",
                "validation-matrix-rejected",
                {
                    "goal_id": "g1",
                    "goal_definition_digest": definition["payload_template_digest"],
                },
                target_id="worker-1",
            )
            self.assertTrue(prepared["ok"], prepared)
            self.assertTrue(
                harness.mark_sent(
                    claim,
                    "DISPATCH",
                    "validation-matrix-rejected",
                    payload,
                    target_id="worker-1",
                )["ok"]
            )
            artifact_digest = digest("unchanged-artifact")
            report = json.loads(
                harness.formal_report_content(
                    "DISPATCH",
                    "validation-matrix-rejected",
                    {"status": "BLOCKED", "artifact_digest": artifact_digest},
                    extra_fields={
                        "execution_started": False,
                        "risks_or_blockers": [
                            {
                                "code": "DISPATCH_VALIDATION_MATRIX_MISMATCH",
                                "path": "/payload/validation_matrix",
                            }
                        ],
                    },
                )
            )
            staged = harness.runtime.stage_formal_report(
                {
                    "outbox_id": "validation-matrix-rejected",
                    "result": {
                        "status": "BLOCKED",
                        "artifact_digest": artifact_digest,
                    },
                    "report": report,
                }
            )
            self.assertEqual(staged["result"]["execution_started"], False)
            self.assertEqual(
                staged["result"]["blocker_code"],
                "DISPATCH_VALIDATION_MATRIX_MISMATCH",
            )
            normalized_report = json.loads(Path(staged["source_path"]).read_text())
            self.assertEqual(
                normalized_report["blocker_code"],
                "DISPATCH_VALIDATION_MATRIX_MISMATCH",
            )

    def test_staging_rejects_conflicting_report_classification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = Harness(Path(temporary))
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            before = persisted_snapshot(Path(temporary))
            with self.assertRaises(
                state_runtime_module.RuntimeRejection
            ) as context:
                harness.runtime.stage_formal_report(
                    {
                        "outbox_id": "classification-conflict",
                        "result": {
                            "status": "BLOCKED",
                            "artifact_digest": digest("unchanged-artifact"),
                            "execution_started": True,
                        },
                        "report": {
                            "status": "BLOCKED",
                            "execution_started": False,
                            "risks_or_blockers": [
                                {
                                    "code": "DISPATCH_VALIDATION_MATRIX_MISMATCH",
                                    "path": "/payload/validation_matrix",
                                }
                            ],
                        },
                    }
                )
            self.assertEqual(
                context.exception.code,
                "WORKER_EXECUTION_CLASSIFICATION_MISMATCH",
            )
            self.assertEqual(before, persisted_snapshot(Path(temporary)))

    def test_staging_does_not_overwrite_unapproved_top_level_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            before = persisted_snapshot(root)
            with self.assertRaises(
                state_runtime_module.RuntimeRejection
            ) as context:
                harness.runtime.stage_formal_report(
                    {
                        "outbox_id": "unapproved-top-level-blocker",
                        "result": {
                            "status": "BLOCKED",
                            "artifact_digest": digest("unchanged-artifact"),
                        },
                        "report": {
                            "status": "BLOCKED",
                            "execution_started": False,
                            "blocker_code": "UNBOUNDED_MODEL_JUDGMENT",
                            "risks_or_blockers": [
                                {
                                    "code": "DISPATCH_VALIDATION_MATRIX_MISMATCH",
                                    "path": "/payload/validation_matrix",
                                }
                            ],
                        },
                    }
                )
            self.assertEqual(
                context.exception.code,
                "WORKER_ZERO_EXECUTION_BLOCKER_INVALID",
            )
            self.assertEqual(before, persisted_snapshot(root))

    def test_reconciliation_rejects_unsafe_point_and_wrong_report_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            harness.ensure_controller_goal()
            harness.register_control_result(
                "THREAD",
                "worker-create-negative",
                "controller-1",
                {"role_kind": "WORKER"},
                {
                    "thread_id": "incident-worker",
                    "role_kind": "WORKER",
                    "worktree_path": ".",
                },
            )
            self._ack_worker(
                harness,
                harness.definitions["g1"],
                1,
                execution_started=False,
            )
            corrupted = harness.state()
            attempt = corrupted["goal_execution_ledger"]["g1"]["attempts"][0]
            latest = corrupted["goal_execution_ledger"]["g1"]["latest_worker"]
            attempt["execution_started"] = True
            attempt.pop("blocker_code")
            latest["execution_started"] = True
            latest.pop("blocker_code")
            harness.runtime._write_state_locked(corrupted, "negative-misclassified-fixture")
            report_path = attempt["evidence_paths"][0]
            mutation = {
                "type": "RECONCILE_WORKER_EXECUTION_CLASSIFICATION",
                "goal_id": "g1",
                "dispatch_id": attempt["dispatch_id"],
                "report_path": report_path,
                "report_digest": attempt["report_digest"],
                "blocker_code": "DISPATCH_FRESHNESS_SNAPSHOT_MISMATCH",
                "reason": "formal report proved execution never started",
            }

            before = persisted_snapshot(root)
            unsafe = harness.apply(mutation)
            self.assertFalse(unsafe["ok"], unsafe)
            self.assertEqual(
                unsafe["status"],
                "WORKER_CLASSIFICATION_RECONCILIATION_REQUIRES_PAUSED_SAFE_POINT",
            )
            self.assertEqual(before, persisted_snapshot(root))

            steering_id = "classification-reconciliation-negative-pause"
            self.assertTrue(
                harness.apply(
                    {
                        "type": "RECORD_STEERING",
                        "steering_id": steering_id,
                        "steering_type": "PAUSE",
                        "normalized_digest": digest("negative reconciliation pause"),
                        "identity_algorithm": "message-item-v1",
                        "message_item_id": "negative-reconciliation-message",
                        "summary": "pause before negative reconciliation checks",
                        "classification_reason": "canonical repair safety gate",
                    }
                )["ok"]
            )
            self.assertTrue(
                harness.apply(
                    {
                        "type": "SET_RUN_CONTROL",
                        "steering_id": steering_id,
                        "requested_status": "PAUSE",
                        "reason": "negative reconciliation checks",
                    }
                )["ok"]
            )

            before = persisted_snapshot(root)
            wrong_digest = harness.apply(
                {**mutation, "report_digest": digest("wrong-report")}
            )
            self.assertFalse(wrong_digest["ok"], wrong_digest)
            self.assertEqual(
                wrong_digest["status"],
                "WORKER_CLASSIFICATION_RECONCILIATION_STATE_MISMATCH",
            )
            self.assertEqual(before, persisted_snapshot(root))

            wrong_path = harness.apply(
                {**mutation, "report_path": ".codex-loop/reports/wrong-report.json"}
            )
            self.assertFalse(wrong_path["ok"], wrong_path)
            self.assertEqual(
                wrong_path["status"],
                "WORKER_CLASSIFICATION_RECONCILIATION_REPORT_MISMATCH",
            )
            self.assertEqual(before, persisted_snapshot(root))

    def test_reconcile_misclassified_archived_worker_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            harness.ensure_controller_goal()
            harness.register_control_result(
                "THREAD",
                "worker-create",
                "controller-1",
                {"role_kind": "WORKER"},
                {"thread_id": "incident-worker", "role_kind": "WORKER", "worktree_path": "."},
            )
            self._ack_worker(
                harness,
                harness.definitions["g1"],
                1,
                execution_started=False,
                blocker_code="DISPATCH_VALIDATION_MATRIX_MISMATCH",
            )
            corrupted = harness.state()
            attempt = corrupted["goal_execution_ledger"]["g1"]["attempts"][0]
            latest = corrupted["goal_execution_ledger"]["g1"]["latest_worker"]
            attempt["execution_started"] = True
            attempt.pop("blocker_code")
            latest["execution_started"] = True
            latest.pop("blocker_code")
            harness.runtime._write_state_locked(corrupted, "misclassified-fixture")

            steering_id = "classification-reconciliation-pause"
            self.assertTrue(
                harness.apply(
                    {
                        "type": "RECORD_STEERING",
                        "steering_id": steering_id,
                        "steering_type": "PAUSE",
                        "normalized_digest": digest("pause for classification repair"),
                        "identity_algorithm": "message-item-v1",
                        "message_item_id": "classification-reconciliation-message",
                        "summary": "pause for classification repair",
                        "classification_reason": "canonical repair safety gate",
                    }
                )["ok"]
            )
            self.assertTrue(
                harness.apply(
                    {
                        "type": "SET_RUN_CONTROL",
                        "steering_id": steering_id,
                        "requested_status": "PAUSE",
                        "reason": "reconcile dropped Worker classification",
                    }
                )["ok"]
            )
            attempt = harness.state()["goal_execution_ledger"]["g1"]["attempts"][0]
            report_path = attempt["evidence_paths"][0]
            reconciled = harness.apply(
                {
                    "type": "RECONCILE_WORKER_EXECUTION_CLASSIFICATION",
                    "goal_id": "g1",
                    "dispatch_id": attempt["dispatch_id"],
                    "report_path": report_path,
                    "report_digest": attempt["report_digest"],
                    "blocker_code": "DISPATCH_VALIDATION_MATRIX_MISMATCH",
                    "reason": "formal report proved execution never started",
                }
            )
            self.assertTrue(reconciled["ok"], reconciled)
            corrected = harness.state()["goal_execution_ledger"]["g1"]
            self.assertEqual(len(corrected["attempts"]), 1)
            self.assertIs(corrected["attempts"][0]["execution_started"], False)
            self.assertEqual(
                corrected["attempts"][0]["blocker_code"],
                "DISPATCH_VALIDATION_MATRIX_MISMATCH",
            )
            self.assertIs(corrected["latest_worker"]["execution_started"], False)

    def test_sanitized_v208_fixture_reconciles_atomically_and_rebuilds_projections(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness, fixture, mutation = self._build_v208_incident(root)
            before = harness.state()
            ledger_before = before["goal_execution_ledger"][fixture["goal_id"]]
            first_before = copy.deepcopy(ledger_before["attempts"][0])
            self.assertEqual(before["run_control"]["status"], fixture["run_control_status"])
            self.assertEqual(len(ledger_before["attempts"]), 2)
            self.assertEqual(
                sum(
                    item.get("execution_started", True)
                    for item in ledger_before["attempts"]
                ),
                fixture["expected"]["product_attempts_before"],
            )
            receipts_dir = root / ".codex-loop" / "external-receipts"
            receipts_before = sorted(
                (path.name, path.read_bytes())
                for path in receipts_dir.glob("*")
                if path.is_file()
            )

            reconciled = harness.apply(mutation)
            self.assertTrue(reconciled["ok"], reconciled)
            self.assertEqual(
                reconciled["operation_status"],
                "WORKER_EXECUTION_CLASSIFICATION_RECONCILED",
            )

            # Re-read from canonical bytes after the transactional commit.
            after = Harness(root).state()
            self.assertEqual(after["state_version"], before["state_version"] + 1)
            ledger_after = after["goal_execution_ledger"][fixture["goal_id"]]
            self.assertEqual(
                len(ledger_after["attempts"]), fixture["expected"]["attempt_count"]
            )
            self.assertEqual(ledger_after["attempts"][0], first_before)
            target = ledger_after["attempts"][1]
            self.assertEqual(target["status"], "BLOCKED")
            self.assertIs(target["execution_started"], False)
            self.assertEqual(target["blocker_code"], fixture["blocker_code"])
            self.assertEqual(ledger_after["latest_worker"], target)
            self.assertEqual(
                sum(
                    item.get("execution_started", True)
                    for item in ledger_after["attempts"]
                ),
                fixture["expected"]["product_attempts_after"],
            )
            self.assertEqual(
                after["controller_pack_identity"], before["controller_pack_identity"]
            )
            self.assertEqual(after["thread_registry"], before["thread_registry"])
            self.assertEqual(
                sorted(
                    (path.name, path.read_bytes())
                    for path in receipts_dir.glob("*")
                    if path.is_file()
                ),
                receipts_before,
            )
            self.assertIsNone(after["controller_lease"])
            status_text = (root / ".codex-loop" / "STATUS.md").read_text(
                encoding="utf-8"
            )
            goals_text = (root / ".codex-loop" / "GOALS.md").read_text(
                encoding="utf-8"
            )
            self.assertIn(f"State version: `{after['state_version']}`", status_text)
            self.assertIn(f"state_version: {after['state_version']}", goals_text)
            transactions = list((root / ".codex-loop" / "transactions").glob("*.json"))
            self.assertTrue(transactions)
            self.assertTrue(
                all(
                    json.loads(path.read_text(encoding="utf-8"))["status"]
                    == "APPLIED"
                    for path in transactions
                )
            )

    def test_v208_reconciliation_identity_guards_are_zero_effect(self) -> None:
        overrides = {
            "report_path": ".codex-loop/reports/wrong.json",
            "report_digest": digest("wrong-report"),
            "dispatch_id": "wrong-dispatch",
            "goal_id": "wrong-goal",
            "blocker_code": "REPORT_STAGING_FAILED",
        }
        for field, value in overrides.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                harness, _, mutation = self._build_v208_incident(root)
                before = persisted_snapshot(root)
                rejected = harness.apply({**mutation, field: value})
                self.assertFalse(rejected["ok"], rejected)
                self.assertEqual(before, persisted_snapshot(root))

        # Artifact identity is bound independently of report path and digest.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness, fixture, mutation = self._build_v208_incident(root)
            corrupted = harness.state()
            target = corrupted["goal_execution_ledger"][fixture["goal_id"]][
                "attempts"
            ][1]
            target["artifact_digest"] = digest("wrong-artifact")
            corrupted["goal_execution_ledger"][fixture["goal_id"]][
                "latest_worker"
            ]["artifact_digest"] = target["artifact_digest"]
            harness.runtime._write_state_locked(corrupted, "artifact-mismatch-fixture")
            before = persisted_snapshot(root)
            rejected = harness.apply(mutation)
            self.assertFalse(rejected["ok"], rejected)
            self.assertEqual(before, persisted_snapshot(root))

        # A code outside the closed enum is rejected by the mutation schema.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness, _, mutation = self._build_v208_incident(root)
            before = persisted_snapshot(root)
            rejected = harness.apply({**mutation, "blocker_code": "UNBOUNDED_CODE"})
            self.assertFalse(rejected["ok"], rejected)
            self.assertEqual(before, persisted_snapshot(root))

    def test_v208_reconciliation_rejects_lease_and_active_outbox_zero_effect(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness, _, mutation = self._build_v208_incident(root)
            def persist_fixture_state(state: dict[str, Any], label: str) -> None:
                harness.runtime._refresh_status_projection_target(state)
                harness.runtime._write_state_locked(state, label)
                harness.runtime._write_status_projection_locked(state)

            state = harness.state()
            state["run_control"] = {
                "status": "RUNNING",
                "reason": "synthetic setup for active-lease guard fixture",
                "effective_state_version": state["state_version"],
            }
            persist_fixture_state(state, "active-lease-setup")
            claim = harness.acquire()
            state = harness.state()
            state["run_control"] = {
                "status": "PAUSED_AT_SAFE_POINT",
                "reason": "synthetic active-lease guard fixture",
                "effective_state_version": state["state_version"],
            }
            persist_fixture_state(state, "active-lease-fixture")
            before = persisted_snapshot(root)
            rejected = harness.apply(mutation)
            self.assertEqual(
                rejected["status"],
                "WORKER_CLASSIFICATION_RECONCILIATION_ACTIVE_LEASE",
            )
            self.assertEqual(before, persisted_snapshot(root))

            state = harness.state()
            state["run_control"] = {
                "status": "RUNNING",
                "reason": "synthetic setup for active-outbox guard fixture",
                "effective_state_version": state["state_version"],
            }
            persist_fixture_state(state, "active-outbox-setup")
            definition = next(iter(harness.definitions.values()))
            prepared, _ = harness.prepare_outbox(
                claim,
                "DISPATCH",
                "active-route-fixture",
                {
                    "goal_id": definition["goal_id"],
                    "goal_definition_digest": definition["payload_template_digest"],
                },
                target_id="sanitized-existing-worker",
            )
            self.assertTrue(prepared["ok"], prepared)
            request = harness.make_request(mutation)
            state = harness.state()
            state["controller_lease"] = None
            state["run_control"] = {
                "status": "PAUSED_AT_SAFE_POINT",
                "reason": "synthetic active-outbox guard fixture",
                "effective_state_version": state["state_version"],
            }
            before = copy.deepcopy(state)
            with self.assertRaises(
                state_runtime_module.RuntimeRejection
            ) as context:
                harness.runtime._reconcile_worker_execution_classification(
                    state, request, mutation
                )
            self.assertEqual(
                context.exception.code,
                "WORKER_CLASSIFICATION_RECONCILIATION_ACTIVE_OUTBOX",
            )
            self.assertEqual(before, state)


class DurableExternalReceiptTests(AdaptiveStateRuntimeTestCase):  # noqa: F405
    @staticmethod
    def _write_receipt_artifact(
        root: Path,
        name: str,
        content: str = '{"status":"BLOCKED"}',
    ) -> tuple[str, str]:
        artifact_path = root / "evidence" / name
        artifact_path.parent.mkdir(exist_ok=True)
        artifact_path.write_text(content, encoding="utf-8")
        artifact_path.chmod(0o444)
        return f"evidence/{name}", digest(content)

    @staticmethod
    def _completed_request(
        started_request: dict[str, Any],
        started: dict[str, Any],
        artifact_path: str,
        artifact_digest: str,
        *,
        usage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            **started_request,
            "phase": "COMPLETED",
            "completed_at": T2,
            "started_receipt_digest": started["receipt_digest"],
            "result_status": "BLOCKED",
            "artifact_path": artifact_path,
            "artifact_digest": artifact_digest,
            "process_exit_code": 0,
            "usage": usage
            or {
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
                "complete": False,
            },
        }

    def test_completed_receipt_survives_lost_stdout_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            runtime = harness.runtime
            started_request = harness.prepare_local_external_call(
                receipt_id="minimax-g03-real-001",
                request_digest=digest("sanitized-g03-request"),
                artifact_path="evidence/minimax-g03-result.json",
            )
            started = runtime.stage_external_receipt(started_request)
            self.assertTrue(started["ok"], started)
            artifact_path = root / "evidence" / "minimax-g03-result.json"
            artifact_path.parent.mkdir()
            artifact_content = '{"status":"BLOCKED"}'
            artifact_path.write_text(artifact_content, encoding="utf-8")
            artifact_path.chmod(0o444)
            completed_request = {
                **started_request,
                "phase": "COMPLETED",
                "completed_at": T2,
                "started_receipt_digest": started["receipt_digest"],
                "result_status": "BLOCKED",
                "artifact_path": "evidence/minimax-g03-result.json",
                "artifact_digest": digest(artifact_content),
                "process_exit_code": 0,
                "usage": {
                    "prompt_tokens": None,
                    "completion_tokens": None,
                    "total_tokens": None,
                    "complete": False,
                },
            }
            # Simulate deferred-exec output loss: ignore the returned handle.
            runtime.stage_external_receipt(completed_request)
            receipt_path = (
                root
                / ".codex-loop/external-receipts/minimax-g03-real-001.completed.json"
            )
            self.assertTrue(receipt_path.is_file())
            self.assertEqual(receipt_path.stat().st_mode & 0o222, 0)
            recovered = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(recovered["result_status"], "BLOCKED")
            self.assertEqual(recovered["calls_consumed"], 1)
            replayed = runtime.stage_external_receipt(completed_request)
            self.assertEqual(replayed["status"], "EXTERNAL_CALL_RECEIPT_RECOVERED")
            self.assertEqual(
                replayed["next_action_code"],
                "RECOVER_RESULT_WITHOUT_PROVIDER_RETRY",
            )

    def test_cli_completed_receipt_is_recoverable_when_stdout_is_discarded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            cli = SCRIPTS / "adaptive_state_runtime.py"
            started_request = harness.prepare_local_external_call(
                receipt_id="cli-lost-stdout-001",
                action_kind="LOCAL_VERIFICATION",
                provider="local-process",
                model="NOT_APPLICABLE",
                request_digest=digest("cli-local-verification"),
                artifact_path="evidence/cli-local-result.json",
            )
            started_run = subprocess.run(
                [
                    sys.executable,
                    str(cli),
                    "--root",
                    str(root),
                    "--external-receipt-stage",
                ],
                input=json.dumps(started_request, separators=(",", ":")),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(started_run.returncode, 0, started_run.stdout)
            started = json.loads(started_run.stdout)
            artifact_path = root / "evidence" / "cli-local-result.json"
            artifact_path.parent.mkdir()
            artifact_content = '{"status":"BLOCKED"}'
            artifact_path.write_text(artifact_content, encoding="utf-8")
            artifact_path.chmod(0o444)
            completed_request = {
                **started_request,
                "phase": "COMPLETED",
                "completed_at": T2,
                "started_receipt_digest": started["receipt_digest"],
                "result_status": "BLOCKED",
                "artifact_path": "evidence/cli-local-result.json",
                "artifact_digest": digest(artifact_content),
                "process_exit_code": 0,
                "usage": {
                    "prompt_tokens": None,
                    "completion_tokens": None,
                    "total_tokens": None,
                    "complete": False,
                },
            }
            completed_run = subprocess.run(
                [
                    sys.executable,
                    str(cli),
                    "--root",
                    str(root),
                    "--external-receipt-stage",
                ],
                input=json.dumps(completed_request, separators=(",", ":")),
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(completed_run.returncode, 0, completed_run.stderr)
            receipt = json.loads(
                (
                    root
                    / ".codex-loop/external-receipts/cli-lost-stdout-001.completed.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(receipt["result_status"], "BLOCKED")
            self.assertFalse(receipt["usage"]["complete"])

    def test_started_recovery_is_conservative_and_forbids_provider_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            request = harness.prepare_local_external_call(
                receipt_id="started-only-crash-001"
            )
            first = harness.runtime.stage_external_receipt(request)
            self.assertEqual(first["next_action_code"], "PERFORM_EXTERNAL_CALL_ONCE")
            before = persisted_snapshot(root)
            recovered = harness.runtime.stage_external_receipt(request)
            self.assertEqual(recovered["status"], "EXTERNAL_CALL_OUTCOME_UNKNOWN")
            self.assertEqual(recovered["next_action_code"], "DO_NOT_RETRY_PROVIDER")
            self.assertEqual(before, persisted_snapshot(root))

    def test_started_receipt_recovers_each_atomic_replace_crash_boundary(self) -> None:
        for stage in state_runtime_module.EXTERNAL_RECEIPT_STAGES:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                harness = Harness(root)
                initialized, _ = harness.initialize()
                self.assertTrue(initialized["ok"], initialized)
                request = harness.prepare_local_external_call(
                    receipt_id="started-crash-boundary-001"
                )
                crashing = state_runtime_module.AdaptiveStateRuntime(
                    root, crash_at=stage
                )
                with self.assertRaises(state_runtime_module.InjectedCrash):
                    crashing.stage_external_receipt(request)

                recovered = state_runtime_module.AdaptiveStateRuntime(root)
                result = recovered.stage_external_receipt(request)
                source = Path(result["source_path"])
                self.assertEqual(source.stat().st_mode & 0o222, 0)
                self.assertEqual(
                    json.loads(source.read_text(encoding="utf-8"))["phase"],
                    "STARTED",
                )
                self.assertFalse(list(source.parent.glob("*.EXTERNAL_RECEIPT.tmp")))
                if stage == "EXTERNAL_RECEIPT_TEMP_FSYNCED":
                    self.assertEqual(result["next_action_code"], "PERFORM_EXTERNAL_CALL_ONCE")
                else:
                    self.assertEqual(result["next_action_code"], "DO_NOT_RETRY_PROVIDER")

    def test_completed_receipt_recovers_each_atomic_replace_crash_boundary(self) -> None:
        for stage in state_runtime_module.EXTERNAL_RECEIPT_STAGES:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                harness = Harness(root)
                initialized, _ = harness.initialize()
                self.assertTrue(initialized["ok"], initialized)
                started_request = harness.prepare_local_external_call(
                    receipt_id="completed-crash-boundary-001",
                    artifact_path="evidence/completed-crash-boundary.json",
                )
                started = harness.runtime.stage_external_receipt(started_request)
                artifact_path, artifact_digest = self._write_receipt_artifact(
                    root, "completed-crash-boundary.json"
                )
                request = self._completed_request(
                    started_request,
                    started,
                    artifact_path,
                    artifact_digest,
                )
                crashing = state_runtime_module.AdaptiveStateRuntime(
                    root, crash_at=stage
                )
                with self.assertRaises(state_runtime_module.InjectedCrash):
                    crashing.stage_external_receipt(request)

                recovered = state_runtime_module.AdaptiveStateRuntime(root)
                result = recovered.stage_external_receipt(request)
                source = Path(result["source_path"])
                self.assertEqual(source.stat().st_mode & 0o222, 0)
                self.assertEqual(
                    json.loads(source.read_text(encoding="utf-8"))["phase"],
                    "COMPLETED",
                )
                self.assertFalse(list(source.parent.glob("*.EXTERNAL_RECEIPT.tmp")))
                if stage == "EXTERNAL_RECEIPT_TEMP_FSYNCED":
                    self.assertEqual(result["next_action_code"], "STAGE_TARGET_REPORT")
                else:
                    self.assertEqual(
                        result["next_action_code"],
                        "RECOVER_RESULT_WITHOUT_PROVIDER_RETRY",
                    )

    def test_completion_without_started_receipt_has_zero_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            request = harness.prepare_local_external_call(
                receipt_id="missing-started-001",
                artifact_path="evidence/missing-started.json",
            )
            artifact_path, artifact_digest = self._write_receipt_artifact(
                root, "missing-started.json"
            )
            fake_started = {"receipt_digest": digest("missing-started")}
            completed = self._completed_request(
                request,
                fake_started,
                artifact_path,
                artifact_digest,
            )
            before = persisted_snapshot(root)
            with self.assertRaises(state_runtime_module.RuntimeRejection) as context:
                harness.runtime.stage_external_receipt(completed)
            self.assertEqual(context.exception.code, "EXTERNAL_RECEIPT_STARTED_NOT_FOUND")
            self.assertEqual(before, persisted_snapshot(root))

    def test_route_identity_fields_are_all_bound(self) -> None:
        mutations = {
            "controller_pack_digest": digest("wrong-pack"),
            "goal_id": "wrong-goal",
            "outbox_id": "wrong-outbox",
            "dispatch_id": "wrong-dispatch",
            "lease_id": "wrong-lease",
            "routing_turn_id": "wrong-routing-turn",
            "target_thread_id": "wrong-target",
            "provider": "wrong-provider",
            "model": "wrong-model",
            "request_digest": digest("wrong-request"),
            "call_index": 2,
            "artifact_path": "evidence/wrong-artifact.json",
        }
        for field, wrong_value in mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                harness = Harness(root)
                initialized, _ = harness.initialize()
                self.assertTrue(initialized["ok"], initialized)
                request = harness.prepare_local_external_call(
                    receipt_id=f"wrong-{field.replace('_', '-')}-001"
                )
                request[field] = wrong_value
                before = persisted_snapshot(root)
                with self.assertRaises(state_runtime_module.RuntimeRejection) as context:
                    harness.runtime.stage_external_receipt(request)
                expected_code = (
                    "EXTERNAL_RECEIPT_ROUTE_NOT_FOUND"
                    if field == "outbox_id"
                    else "EXTERNAL_RECEIPT_IDENTITY_CONFLICT"
                )
                self.assertEqual(context.exception.code, expected_code)
                self.assertEqual(before, persisted_snapshot(root))

    def test_completed_artifact_must_exist_be_read_only_and_match_digest(self) -> None:
        cases = ("missing", "writable", "digest")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                harness = Harness(root)
                initialized, _ = harness.initialize()
                self.assertTrue(initialized["ok"], initialized)
                request = harness.prepare_local_external_call(
                    receipt_id=f"artifact-{case}-001",
                    artifact_path=(
                        "evidence/missing.json"
                        if case == "missing"
                        else f"evidence/artifact-{case}.json"
                    ),
                )
                started = harness.runtime.stage_external_receipt(request)
                if case == "missing":
                    artifact_path = "evidence/missing.json"
                    artifact_digest = digest("missing")
                else:
                    artifact_path, artifact_digest = self._write_receipt_artifact(
                        root, f"artifact-{case}.json"
                    )
                    if case == "writable":
                        (root / artifact_path).chmod(0o644)
                    else:
                        artifact_digest = digest("wrong-digest")
                completed = self._completed_request(
                    request,
                    started,
                    artifact_path,
                    artifact_digest,
                )
                before = persisted_snapshot(root)
                with self.assertRaises(state_runtime_module.RuntimeRejection) as context:
                    harness.runtime.stage_external_receipt(completed)
                self.assertEqual(context.exception.code, "EXTERNAL_RECEIPT_ARTIFACT_INVALID")
                self.assertEqual(before, persisted_snapshot(root))

    def test_unknown_usage_is_explicit_and_complete_usage_is_arithmetic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            request = harness.prepare_local_external_call(
                receipt_id="usage-unknown-001",
                artifact_path="evidence/usage-unknown.json",
            )
            started = harness.runtime.stage_external_receipt(request)
            artifact_path, artifact_digest = self._write_receipt_artifact(
                root, "usage-unknown.json"
            )
            completed = self._completed_request(
                request,
                started,
                artifact_path,
                artifact_digest,
                usage={
                    "prompt_tokens": 10,
                    "completion_tokens": None,
                    "total_tokens": None,
                    "complete": False,
                },
            )
            response = harness.runtime.stage_external_receipt(completed)
            self.assertTrue(response["ok"], response)
            receipt = json.loads(Path(response["source_path"]).read_text())
            self.assertIsNone(receipt["usage"]["completion_tokens"])
            self.assertFalse(receipt["usage"]["complete"])
            invalid = copy.deepcopy(completed)
            invalid["usage"]["complete"] = True
            before = persisted_snapshot(root)
            with self.assertRaises(state_runtime_module.RuntimeRejection) as context:
                harness.runtime.stage_external_receipt(invalid)
            self.assertEqual(context.exception.code, "EXTERNAL_RECEIPT_USAGE_INVALID")
            self.assertEqual(before, persisted_snapshot(root))

    def test_runtime_generated_receipt_uses_canonical_utf8_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            request = harness.prepare_local_external_call(
                receipt_id="utf8-runtime-receipt-001",
                provider="本地验证😀",
                model="组合字符-e\u0301",
            )
            staged = harness.runtime.stage_external_receipt(request)
            payload = Path(staged["source_path"]).read_bytes()
            self.assertIn("本地验证😀".encode("utf-8"), payload)
            self.assertIn("组合字符-e\u0301".encode("utf-8"), payload)
            self.assertNotIn(b"\\u672c\\u5730", payload)
            self.assertFalse(payload.endswith(b"\n"))
            parsed = json.loads(payload.decode("utf-8"))
            expected = json.dumps(
                parsed,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            self.assertEqual(payload, expected)
            self.assertEqual(staged["receipt_digest"], digest(payload.decode("utf-8")))


class PackMigrationAndTurnLeaseTests(AdaptiveStateRuntimeTestCase):  # noqa: F405
    @staticmethod
    def _pause_at_safe_point(harness: Harness) -> None:
        steering_id = "pack-migration-pause"
        recorded = harness.apply(
            {
                "type": "RECORD_STEERING",
                "steering_id": steering_id,
                "steering_type": "PAUSE",
                "normalized_digest": digest("pause for pack migration"),
                "identity_algorithm": "message-item-v1",
                "message_item_id": "pack-migration-pause-message",
                "summary": "pause for pack migration",
                "classification_reason": "explicit migration safety gate",
            }
        )
        assert recorded["ok"], recorded
        paused = harness.apply(
            {
                "type": "SET_RUN_CONTROL",
                "steering_id": steering_id,
                "requested_status": "PAUSE",
                "reason": "pack identity migration",
            }
        )
        assert paused["ok"], paused
        assert paused["operation_status"] == "PAUSED_AT_SAFE_POINT", paused

    def test_pack_digest_change_requires_atomic_canonical_migration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            old_digest = harness.state()["controller_pack_identity"]["digest"]

            mismatched = harness.make_request(
                {
                    "type": "ACQUIRE_LEASE",
                    "routing_turn_id": "unmigrated-route",
                    "lease_id": "unmigrated-lease",
                    "owner_kind": "HEARTBEAT",
                    "owner_identity": "controller-1",
                    "observed_at": T1,
                    "expires_at": T4,
                    "controller_turn_id": "unmigrated-app-turn",
                }
            )
            mismatched["controller_pack_digest"] = digest("unmigrated-pack")
            before = persisted_snapshot(root)
            denied = harness.runtime.apply(mismatched)
            self.assertEqual(denied["status"], "CONTROLLER_PACK_MIGRATION_REQUIRED")
            self.assertEqual(before, persisted_snapshot(root))

            content = "# Controller Pack\n\nreal incident protocol revision\n"
            target_digest = digest(content)
            harness.ensure_all_roles()
            harness.ensure_heartbeat()
            self._pause_at_safe_point(harness)
            prepared = harness.prepare_pack_migration(
                content=content,
                target_prompt_digest=digest("dynamic canonical Pack heartbeat"),
                migration_id="real-incident-pack-migration",
                reason="real incident transport and receipt remediation",
            )
            self.assertTrue(prepared["response"]["ok"], prepared["response"])
            migrated = harness.commit_pack_migration(prepared)
            self.assertTrue(migrated["ok"], migrated)
            state = harness.state()
            self.assertEqual(state["controller_pack_identity"]["digest"], target_digest)
            self.assertEqual(state["controller_pack_revision"], 2)
            self.assertEqual(
                state["worker_validation_projection_contract_version"], 1
            )
            self.assertEqual(
                [item["digest"] for item in state["controller_pack_history"]],
                [old_digest, target_digest],
            )

    def test_pack_migration_backfills_legacy_routes_before_turn_enforcement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            harness.ensure_all_roles()
            harness.ensure_heartbeat()

            for _ in range(2):
                claim = harness.acquire()
                released = harness.apply(
                    {
                        "type": "RELEASE_LEASE",
                        "lease_claim": claim,
                        "observed_at": T1,
                        "reason_code": "NO_ROUTE_READY",
                    }
                )
                self.assertTrue(released["ok"], released)
            expected_backfilled = len(harness.state()["routing_turn_ledger"])
            self._pause_at_safe_point(harness)

            legacy = harness.state()
            legacy.pop("controller_pack_history")
            legacy.pop("controller_pack_revision")
            legacy.pop("pack_identity_enforced")
            legacy.pop("controller_turn_enforcement")
            legacy.pop("consumed_controller_turn_ids")
            legacy.pop("worker_validation_projection_contract_version")
            legacy.pop("controller_pack_migration_contract_version")
            legacy.pop("controller_pack_migration")
            legacy.pop("controller_pack_migration_history")
            legacy.pop("heartbeat_prompt_identity")
            legacy.pop("heartbeat_live_observation")
            legacy.pop("heartbeat_routing_gate_enforced")
            for routing_turn in legacy["routing_turn_ledger"].values():
                routing_turn.pop("controller_turn_id")
            harness.runtime._write_state_locked(legacy, "legacy-pack-fixture")
            self.assertNotIn(
                "consumed_controller_turn_ids", harness.runtime.read_state()
            )
            before_unmigrated_write = persisted_snapshot(root)
            blocked_write = harness.apply(
                {
                    "type": "RECORD_STEERING",
                    "steering_id": "legacy-contract-write",
                    "steering_type": "STATUS_QUERY",
                    "normalized_digest": digest("legacy contract write"),
                    "identity_algorithm": "message-item-v1",
                    "message_item_id": "legacy-contract-write-message",
                    "summary": "must migrate contract before writing",
                    "classification_reason": "projection contract missing",
                }
            )
            self.assertEqual(
                blocked_write["status"],
                "WORKER_VALIDATION_CONTRACT_MIGRATION_REQUIRED",
            )
            self.assertEqual(before_unmigrated_write, persisted_snapshot(root))

            content = "# Controller Pack\n\nlegacy route migration regression\n"
            target_digest = digest(content)
            prepared = harness.prepare_pack_migration(
                content=content,
                target_prompt_digest=digest("legacy migration heartbeat prompt"),
                migration_id="legacy-route-pack-migration",
                reason="backfill legacy routing turn identities",
            )
            self.assertTrue(prepared["response"]["ok"], prepared["response"])
            migrated = harness.commit_pack_migration(prepared)
            self.assertTrue(migrated["ok"], migrated)
            self.assertEqual(
                migrated["result"]["legacy_routing_turns_backfilled"],
                expected_backfilled,
            )
            state = harness.state()
            routed_ids = sorted(
                item["controller_turn_id"]
                for item in state["routing_turn_ledger"].values()
            )
            self.assertEqual(state["consumed_controller_turn_ids"], routed_ids)
            self.assertEqual(
                state["worker_validation_projection_contract_version"], 1
            )
            self.assertTrue(
                all(item.startswith("legacy-turn-") for item in routed_ids)
            )

    def test_one_real_app_turn_cannot_acquire_a_second_route_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = Harness(Path(temporary))
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            app_turn_id = "codex-app-turn-019f5e27-incident"
            first = harness.apply(
                {
                    "type": "ACQUIRE_LEASE",
                    "routing_turn_id": "route-first",
                    "lease_id": "lease-first",
                    "owner_kind": "HEARTBEAT",
                    "owner_identity": "controller-1",
                    "observed_at": T1,
                    "expires_at": T4,
                    "controller_turn_id": app_turn_id,
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
            before = persisted_snapshot(Path(temporary))
            second = harness.apply(
                {
                    "type": "ACQUIRE_LEASE",
                    "routing_turn_id": "route-second",
                    "lease_id": "lease-second",
                    "owner_kind": "HEARTBEAT",
                    "owner_identity": "controller-1",
                    "observed_at": T1,
                    "expires_at": T4,
                    "controller_turn_id": app_turn_id,
                }
            )
            self.assertEqual(second["status"], "CONTROLLER_TURN_ALREADY_ROUTED")
            self.assertEqual(before, persisted_snapshot(Path(temporary)))


class ScopedCorrectionIdentityTests(AdaptiveStateRuntimeTestCase):  # noqa: F405
    def test_applied_correction_recognizes_a_non_exhausted_goal(self) -> None:
        state = {
            "steering_ledger": {
                "real-incident-g03-correction": {
                    "steering_type": "CORRECTION",
                    "status": "APPLIED",
                    "target_goal_id": "G03_AI_WEIGHT_ENGINE",
                    "applied_state_version": 165,
                }
            }
        }
        self.assertTrue(
            AdaptiveStateRuntime._applied_scoped_correction(
                state, "G03_AI_WEIGHT_ENGINE"
            )
        )
        self.assertFalse(
            AdaptiveStateRuntime._applied_scoped_correction(
                state, "G03_SECURITY_RECEIPT_CORRECTION"
            )
        )

    def test_acknowledged_local_blocked_allows_only_scoped_correction_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = Harness(Path(temporary))
            harness.initialize(local_required_goal_ids=["g1"])
            worker = harness.worker_pass("g1")
            code_review = harness.review("CODE_REVIEW", "REVIEW_PASS", worker)
            harness.register_control_result(
                "THREAD",
                "local-verifier-thread-create",
                "controller-1",
                {"role_kind": "LOCAL_VERIFIER"},
                {
                    "thread_id": "local-verifier-1",
                    "role_kind": "LOCAL_VERIFIER",
                    "worktree_path": ".",
                },
            )
            local_claim = harness.acquire()
            local_id = "local-blocked-real-incident"
            local_identity = {
                "goal_id": "g1",
                "worker_dispatch_id": worker["dispatch_id"],
                "artifact_digest": worker["artifact_digest"],
                "verification_id": "verification-real-incident",
                "code_review_id": code_review,
            }
            prepared, payload = harness.prepare_outbox(
                local_claim,
                "LOCAL",
                local_id,
                local_identity,
                target_id="local-verifier-1",
            )
            self.assertTrue(prepared["ok"], prepared)
            self.assertTrue(
                harness.mark_sent(
                    local_claim,
                    "LOCAL",
                    local_id,
                    payload,
                    target_id="local-verifier-1",
                )["ok"]
            )
            local_result = {
                "status": "BLOCKED",
                "artifact_digest": worker["artifact_digest"],
            }
            local_content = harness.formal_report_content(
                "LOCAL", local_id, local_result
            )
            acknowledged = harness.ack_outbox(
                local_claim,
                "LOCAL",
                local_id,
                payload,
                target_id="local-verifier-1",
                result={
                    **local_result,
                    "report_digest": digest(local_content),
                },
                report_content=local_content,
            )
            self.assertTrue(acknowledged["ok"], acknowledged)

            correction = {
                "type": "RECORD_STEERING",
                "steering_id": "real-incident-local-blocked-correction",
                "steering_type": "CORRECTION",
                "normalized_digest": digest("replace locally blocked g1"),
                "identity_algorithm": "message-item-v1",
                "message_item_id": "real-incident-correction-message",
                "summary": "replace locally blocked g1",
                "classification_reason": "explicit scoped correction",
                "target_goal_id": "g1",
            }
            self.assertTrue(harness.apply(correction)["ok"])
            self.assertTrue(
                harness.apply(
                    {
                        "type": "RESOLVE_STEERING",
                        "steering_id": correction["steering_id"],
                        "resolution_status": "APPLIED",
                        "resolution": "audit a new Goal without completing g1",
                        "next_action_code": "ROADMAP_REVISION",
                    }
                )["ok"]
            )
            audit_claim = harness.acquire()
            audit, _ = harness.prepare_outbox(
                audit_claim,
                "ASSURANCE",
                "roadmap-audit-local-blocked-correction",
                {
                    "review_kind": "ROADMAP_AUDIT",
                    "goal_id": "g1",
                    "worker_dispatch_id": worker["dispatch_id"],
                    "worker_report_digest": worker["report_digest"],
                    "artifact_digest": worker["artifact_digest"],
                    "code_review_id": code_review,
                },
                target_id="reviewer-1",
            )
            self.assertTrue(audit["ok"], audit)
            self.assertEqual(
                audit["operation_status"], "ASSURANCE_OUTBOX_PREPARED"
            )
