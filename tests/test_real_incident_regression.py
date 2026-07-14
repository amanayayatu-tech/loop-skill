from __future__ import annotations

from state_runtime_support import *  # noqa: F403


class RealIncidentRepairAccountingTests(AdaptiveStateRuntimeTestCase):  # noqa: F405
    def _ack_worker(
        self,
        harness: Harness,
        definition: dict[str, Any],
        index: int,
        *,
        execution_started: bool,
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
            result["blocker_code"] = "DISPATCH_FRESHNESS_SNAPSHOT_MISMATCH"
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
                    "blocker_code": "DISPATCH_FRESHNESS_SNAPSHOT_MISMATCH",
                    "reason": "formal report proved execution never started",
                }
            )
            self.assertTrue(reconciled["ok"], reconciled)
            corrected = harness.state()["goal_execution_ledger"]["g1"]
            self.assertEqual(len(corrected["attempts"]), 1)
            self.assertIs(corrected["attempts"][0]["execution_started"], False)
            self.assertEqual(
                corrected["attempts"][0]["blocker_code"],
                "DISPATCH_FRESHNESS_SNAPSHOT_MISMATCH",
            )
            self.assertIs(corrected["latest_worker"]["execution_started"], False)


class DurableExternalReceiptTests(AdaptiveStateRuntimeTestCase):  # noqa: F405
    def test_completed_receipt_survives_lost_stdout_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            runtime = harness.runtime
            started_request = {
                "receipt_id": "minimax-g03-real-001",
                "phase": "STARTED",
                "action_kind": "EXTERNAL_MODEL_CALL",
                "request_digest": digest("sanitized-g03-request"),
                "observed_at": T1,
                "calls_consumed": 1,
                "model": "MiniMax-M2.5",
            }
            started = runtime.stage_external_receipt(started_request)
            self.assertTrue(started["ok"], started)
            completed_request = {
                **started_request,
                "phase": "COMPLETED",
                "observed_at": T2,
                "started_receipt_digest": started["receipt_digest"],
                "result_status": "BLOCKED",
                "artifact_digest": digest("sanitized-g03-result"),
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
            self.assertEqual(replayed["status"], "EXTERNAL_CALL_RECEIPT_STAGED")

    def test_cli_completed_receipt_is_recoverable_when_stdout_is_discarded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            cli = SCRIPTS / "adaptive_state_runtime.py"
            started_request = {
                "receipt_id": "cli-lost-stdout-001",
                "phase": "STARTED",
                "action_kind": "LOCAL_VERIFICATION",
                "request_digest": digest("cli-local-verification"),
                "observed_at": T1,
                "calls_consumed": 1,
            }
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
            completed_request = {
                **started_request,
                "phase": "COMPLETED",
                "observed_at": T2,
                "started_receipt_digest": started["receipt_digest"],
                "result_status": "BLOCKED",
                "artifact_digest": digest("cli-local-result"),
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

            self._pause_at_safe_point(harness)
            content = "# Controller Pack\n\nreal incident protocol revision\n"
            target_digest = digest(content)
            target_path = (
                ".codex-loop/sources/CONTROLLER_PACK."
                f"{target_digest.removeprefix('sha256:')}.md"
            )
            artifact = {
                "path": target_path,
                "content": content,
                "digest": target_digest,
                "media_type": "text/markdown",
            }
            migrated = harness.apply(
                {
                    "type": "MIGRATE_CONTROLLER_PACK",
                    "source_pack_digest": old_digest,
                    "target_pack_digest": target_digest,
                    "target_pack_path": target_path,
                    "migration_reason": "real incident transport and receipt remediation",
                },
                artifacts=[artifact],
            )
            self.assertTrue(migrated["ok"], migrated)
            state = harness.state()
            self.assertEqual(state["controller_pack_identity"]["digest"], target_digest)
            self.assertEqual(state["controller_pack_revision"], 2)
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
            old_digest = harness.state()["controller_pack_identity"]["digest"]

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
            self._pause_at_safe_point(harness)

            legacy = harness.state()
            legacy.pop("controller_pack_history")
            legacy.pop("controller_pack_revision")
            legacy.pop("pack_identity_enforced")
            legacy.pop("controller_turn_enforcement")
            legacy.pop("consumed_controller_turn_ids")
            for routing_turn in legacy["routing_turn_ledger"].values():
                routing_turn.pop("controller_turn_id")
            harness.runtime._write_state_locked(legacy, "legacy-pack-fixture")
            self.assertNotIn(
                "consumed_controller_turn_ids", harness.runtime.read_state()
            )

            content = "# Controller Pack\n\nlegacy route migration regression\n"
            target_digest = digest(content)
            target_path = (
                ".codex-loop/sources/CONTROLLER_PACK."
                f"{target_digest.removeprefix('sha256:')}.md"
            )
            migrated = harness.apply(
                {
                    "type": "MIGRATE_CONTROLLER_PACK",
                    "source_pack_digest": old_digest,
                    "target_pack_digest": target_digest,
                    "target_pack_path": target_path,
                    "migration_reason": "backfill legacy routing turn identities",
                },
                artifacts=[
                    {
                        "path": target_path,
                        "content": content,
                        "digest": target_digest,
                        "media_type": "text/markdown",
                    }
                ],
            )
            self.assertTrue(migrated["ok"], migrated)
            self.assertEqual(
                migrated["result"]["legacy_routing_turns_backfilled"], 2
            )
            state = harness.state()
            routed_ids = sorted(
                item["controller_turn_id"]
                for item in state["routing_turn_ledger"].values()
            )
            self.assertEqual(state["consumed_controller_turn_ids"], routed_ids)
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
