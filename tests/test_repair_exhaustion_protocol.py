from __future__ import annotations

from state_runtime_support import *  # noqa: F403


class RepairExhaustionProtocolTests(AdaptiveStateRuntimeTestCase):  # noqa: F405
    def _exhausted_harness(
        self, root: Path, *, decision_cards_enabled: bool
    ) -> tuple[Harness, dict[str, Any]]:
        harness = Harness(root)
        definitions = {"g1": goal("g1", "m1")}
        milestones = [milestone("m1", "ACTIVE")]
        authorization = authorization_envelope(definitions, milestones)
        authorization["repair_policy"]["max_repair_attempts_per_goal"] = 1
        initialized, _ = harness.initialize(
            definitions=definitions,
            milestones=milestones,
            authorization=authorization,
            human_control_policy={
                "human_steering_enabled": True,
                "status_projection_enabled": True,
                "decision_cards_enabled": decision_cards_enabled,
                "failure_fingerprint_enabled": True,
                "context_freshness_required": True,
                "review_evidence_policy": "deterministic_first",
            },
        )
        self.assertTrue(initialized["ok"], initialized)
        harness.ensure_controller_goal()
        harness.register_control_result(
            "AUTOMATION",
            "repair-heartbeat-create",
            "controller-1",
            {},
            {"automation_id": "repair-heartbeat", "status": "ACTIVE"},
        )
        harness.register_control_result(
            "THREAD",
            "repair-worker-create",
            "controller-1",
            {"role_kind": "WORKER"},
            {
                "thread_id": "repair-worker",
                "role_kind": "WORKER",
                "worktree_path": ".",
            },
        )
        for index in (1, 2):
            claim = harness.acquire()
            outbox_id = f"repair-dispatch-{index}"
            prepared, payload = harness.prepare_outbox(
                claim,
                "DISPATCH",
                outbox_id,
                {
                    "goal_id": "g1",
                    "goal_definition_digest": definitions["g1"][
                        "payload_template_digest"
                    ],
                },
                target_id="repair-worker",
            )
            self.assertTrue(prepared["ok"], prepared)
            self.assertTrue(
                harness.mark_sent(
                    claim,
                    "DISPATCH",
                    outbox_id,
                    payload,
                    target_id="repair-worker",
                )["ok"]
            )
            result = {
                "status": "FAIL" if index == 1 else "BLOCKED",
                "artifact_digest": digest(f"repair-artifact-{index}"),
            }
            report_content = harness.formal_report_content(
                "DISPATCH", outbox_id, result
            )
            acked = harness.ack_outbox(
                claim,
                "DISPATCH",
                outbox_id,
                payload,
                target_id="repair-worker",
                result={**result, "report_digest": digest(report_content)},
                report_content=report_content,
            )
            self.assertTrue(acked["ok"], acked)
        exhausted_claim = harness.acquire()
        before = persisted_snapshot(root)
        exhausted, _ = harness.prepare_outbox(
            exhausted_claim,
            "DISPATCH",
            "repair-dispatch-3",
            {
                "goal_id": "g1",
                "goal_definition_digest": definitions["g1"][
                    "payload_template_digest"
                ],
            },
            target_id="repair-worker",
        )
        self.assertEqual(exhausted["status"], "REPAIR_BUDGET_EXHAUSTED")
        self.assertEqual(persisted_snapshot(root), before)
        released = harness.apply(
            {
                "type": "RELEASE_LEASE",
                "lease_claim": exhausted_claim,
                "observed_at": T1,
                "reason_code": "REPAIR_BUDGET_EXHAUSTED",
            }
        )
        self.assertTrue(released["ok"], released)
        return harness, definitions["g1"]

    @staticmethod
    def _decision(harness: Harness) -> dict[str, Any]:
        state = harness.state()
        card = {
            "type": "REGISTER_DECISION",
            "decision_id": "repair-exhausted-g1",
            "decision_context_digest": digest("placeholder"),
            "source_state_version": state["state_version"],
            "valid_through_state_version": state["state_version"] + 20,
            "options": [
                {
                    "option_id": "stop",
                    "option_effect": "STOP_LOOP_CONFIRMED",
                    "preauthorized_capability": "none",
                },
                {
                    "option_id": "wait-correction",
                    "option_effect": "WAIT",
                    "preauthorized_capability": "none",
                },
            ],
            "scope": {"goal_id": "g1"},
            "exclusions": ["additional repair", "repair counter reset"],
        }
        card["decision_context_digest"] = harness.runtime._decision_context_digest(
            state, card
        )
        return card

    def _stop_mutation(
        self,
        harness: Harness,
        *,
        stop_basis: str,
        decision: dict[str, Any] | None = None,
        steering_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        fingerprint = digest("REPAIR_BUDGET_EXHAUSTED:g1")
        report = {
            "blocker_code": "REPAIR_BUDGET_EXHAUSTED",
            "blocker_fingerprint": fingerprint,
            "controller_goal_id": "native-goal-m1",
            "stop_basis": stop_basis,
            "blocked_goal_id": "g1",
            "completed_attempts": 2,
            "max_repair_attempts_per_goal": 1,
            "status": "HARD_BLOCK",
        }
        mutation = {
            "type": "STOP_LOOP",
            "lease_claim": harness.acquire(),
            "observed_at": T1,
            "terminal_status": "LOOP_BLOCKED",
            "stop_basis": stop_basis,
            "blocker_code": "REPAIR_BUDGET_EXHAUSTED",
            "blocker_fingerprint": fingerprint,
            "blocked_goal_id": "g1",
            "finalization_id": f"repair-stop-{stop_basis.lower()}",
            "controller_goal_id": "native-goal-m1",
            "automation_id": "repair-heartbeat",
        }
        if decision is not None:
            report.update(
                {
                    "decision_id": decision["decision_id"],
                    "decision_context_digest": decision[
                        "decision_context_digest"
                    ],
                    "decision_response_steering_id": steering_id,
                }
            )
            mutation.update(
                {
                    "decision_id": decision["decision_id"],
                    "decision_context_digest": decision[
                        "decision_context_digest"
                    ],
                    "decision_response_steering_id": steering_id,
                }
            )
        artifact = read_evidence_artifact(
            f"repair-stop-{stop_basis.lower()}",
            json.dumps(report, sort_keys=True, separators=(",", ":")),
        )
        mutation["blocker_report_path"] = artifact["path"]
        mutation["blocker_report_digest"] = artifact["digest"]
        return mutation, artifact

    def test_decision_card_is_stable_waits_and_never_dispatches_again(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness, definition = self._exhausted_harness(
                root, decision_cards_enabled=True
            )
            card = self._decision(harness)
            registered = harness.apply(card)
            self.assertEqual(registered["operation_status"], "DECISION_REGISTERED")
            replayed = harness.apply(card)
            self.assertEqual(
                replayed["operation_status"], "DECISION_ALREADY_REGISTERED"
            )
            response = harness.apply(
                {
                    "type": "RECORD_DECISION_RESPONSE",
                    "steering_id": "wait-for-correction",
                    "normalized_digest": digest("wait for scoped correction"),
                    "identity_algorithm": "message-item-v1",
                    "message_item_id": "wait-message",
                    "summary": "wait for scoped correction",
                    "classification_reason": "explicit decision response",
                    "decision_id": card["decision_id"],
                    "option_id": "wait-correction",
                    "decision_context_digest": card["decision_context_digest"],
                }
            )
            self.assertEqual(response["next_action_code"], "WAIT")
            claim = harness.acquire()
            before = persisted_snapshot(root)
            rejected, _ = harness.prepare_outbox(
                claim,
                "DISPATCH",
                "forbidden-extra-repair",
                {
                    "goal_id": "g1",
                    "goal_definition_digest": definition[
                        "payload_template_digest"
                    ],
                },
                target_id="repair-worker",
            )
            self.assertEqual(rejected["status"], "REPAIR_BUDGET_EXHAUSTED")
            self.assertEqual(persisted_snapshot(root), before)

    def test_user_decision_stop_binds_card_steering_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness, _ = self._exhausted_harness(
                root, decision_cards_enabled=True
            )
            card = self._decision(harness)
            self.assertTrue(harness.apply(card)["ok"])
            steering_id = "stop-decision-response"
            decision_response = {
                "type": "RECORD_DECISION_RESPONSE",
                "steering_id": steering_id,
                "normalized_digest": digest("stop on current evidence"),
                "identity_algorithm": "message-item-v1",
                "message_item_id": "stop-message",
                "summary": "stop on current evidence",
                "classification_reason": "explicit decision response",
                "decision_id": card["decision_id"],
                "option_id": "stop",
                "decision_context_digest": card["decision_context_digest"],
            }
            applied = harness.apply(decision_response)
            self.assertEqual(applied["next_action_code"], "STOP_LOOP_CONFIRMED")
            replayed = harness.apply(decision_response)
            self.assertEqual(
                replayed["operation_status"], "DECISION_RESPONSE_ALREADY_APPLIED"
            )
            mutation, artifact = self._stop_mutation(
                harness,
                stop_basis="USER_DECISION",
                decision=card,
                steering_id=steering_id,
            )
            wrong = copy.deepcopy(mutation)
            wrong["decision_response_steering_id"] = "wrong-steering"
            before = persisted_snapshot(root)
            denied = harness.apply(wrong, artifacts=[artifact])
            self.assertEqual(denied["status"], "STOP_LOOP_USER_DECISION_INVALID")
            self.assertEqual(persisted_snapshot(root), before)
            request = harness.make_request(
                mutation,
                evidence_paths=[artifact["path"]],
                artifacts=[artifact],
            )
            stopped = harness.runtime.apply(request)
            self.assertTrue(stopped["ok"], stopped)
            self.assertEqual(stopped["operation_status"], "STOP_LOOP_APPLIED")
            replayed_stop = harness.runtime.apply(request)
            self.assertEqual(
                replayed_stop["operation_status"], "IDEMPOTENT_REPLAY"
            )
            self.assertTrue(replayed_stop["ok"], replayed_stop)
            outbox = harness.state()["finalization_outbox"]
            self.assertEqual(outbox["stop_basis"], "USER_DECISION")
            self.assertEqual(outbox["decision_id"], card["decision_id"])

    def test_decision_disabled_uses_deterministic_fast_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness, _ = self._exhausted_harness(
                root, decision_cards_enabled=False
            )
            mutation, artifact = self._stop_mutation(
                harness, stop_basis="DETERMINISTIC_REPAIR_BUDGET"
            )
            stopped = harness.runtime.apply(
                harness.make_request(
                    mutation,
                    evidence_paths=[artifact["path"]],
                    artifacts=[artifact],
                )
            )
            self.assertTrue(stopped["ok"], stopped)
            self.assertEqual(stopped["operation_status"], "STOP_LOOP_APPLIED")
            self.assertEqual(
                harness.state()["finalization_outbox"]["blocker_observations"],
                [],
            )
            finalization = harness.state()["finalization_outbox"]
            goal_observation = read_evidence_artifact(
                "repair-budget-goal-observation",
                '{"goal_id":"native-goal-m1","status":"BLOCKED"}',
            )
            automation_observation = read_evidence_artifact(
                "repair-budget-automation-observation",
                '{"automation_id":"repair-heartbeat","status":"PAUSED"}',
            )
            acknowledged = harness.apply(
                {
                    "type": "ACK_FINALIZATION",
                    "observed_at": T1,
                    "finalization_id": mutation["finalization_id"],
                    "finalized_state_version": stopped["state_version_after"],
                    "controller_goal_id": mutation["controller_goal_id"],
                    "native_goal_policy": finalization["native_goal_policy"],
                    "closeout_capability": finalization["closeout_capability"],
                    "controller_goal_status": "BLOCKED",
                    "controller_goal_observation_path": goal_observation["path"],
                    "controller_goal_observation_digest": goal_observation["digest"],
                    "automation_id": mutation["automation_id"],
                    "automation_status": "PAUSED",
                    "automation_observation_path": automation_observation["path"],
                    "automation_observation_digest": automation_observation["digest"],
                },
                artifacts=[goal_observation, automation_observation],
            )
            self.assertEqual(
                acknowledged["operation_status"], "FINALIZATION_ACKED"
            )
            self.assertEqual(
                harness.state()["finalization_receipt"]["stop_basis"],
                "DETERMINISTIC_REPAIR_BUDGET",
            )

    def test_scoped_correction_roadmap_revision_uses_new_goal_and_keeps_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness, _ = self._exhausted_harness(
                root, decision_cards_enabled=True
            )
            correction = {
                "type": "RECORD_STEERING",
                "steering_id": "scoped-correction-g1",
                "steering_type": "CORRECTION",
                "normalized_digest": digest("replace exhausted g1 with scoped g2"),
                "identity_algorithm": "message-item-v1",
                "message_item_id": "scoped-correction-message",
                "summary": "replace exhausted g1 with scoped g2",
                "classification_reason": "explicit scoped correction",
                "target_goal_id": "g1",
            }
            self.assertEqual(
                harness.apply(correction)["operation_status"],
                "STEERING_CLASSIFIED",
            )
            self.assertTrue(
                harness.apply(
                    {
                        "type": "RESOLVE_STEERING",
                        "steering_id": correction["steering_id"],
                        "resolution_status": "APPLIED",
                        "resolution": "audit a replacement Goal without reusing g1",
                        "next_action_code": "ROADMAP_REVISION",
                    }
                )["ok"]
            )
            state = harness.state()
            worker = copy.deepcopy(
                state["goal_execution_ledger"]["g1"]["latest_worker"]
            )
            worker["goal_id"] = "g1"
            code_review = harness.review("CODE_REVIEW", "REVIEW_PASS", worker)
            replacement = goal("g2", "m1", depends_on=["g1"])
            definitions = {
                **harness.state()["goal_definition_registry"],
                "g2": replacement,
            }
            proposed_authorization = copy.deepcopy(harness.authorization)
            proposed_authorization["phase_permission_caps"]["by_goal"]["g2"] = {
                "milestone_id": "m1",
                "phase_permissions": copy.deepcopy(
                    proposed_authorization["phase_permission_caps"]["by_goal"][
                        "g1"
                    ]["phase_permissions"]
                ),
            }
            next_milestones = [milestone("m1", "ACTIVE")]
            next_queue = [queue_entry("g2", "m1", "READY", 2, depends_on=["g1"])]
            operations = [
                {
                    "operation": "UPDATE_MILESTONE",
                    "milestone_id": "m1",
                    "reason": "Apply scoped correction",
                }
            ]
            audit = harness.review(
                "ROADMAP_AUDIT",
                "ROADMAP_AUDIT_PASS",
                worker,
                code_review_id=code_review,
                roadmap_plan=roadmap_plan(
                    proposal_id="scoped-correction-proposal",
                    operations=operations,
                    milestones=next_milestones,
                    goal_definition_registry=definitions,
                    goal_queue=next_queue,
                    authorization_envelope=proposed_authorization,
                    next_goal_id="g2",
                    reason_code="SCOPED_CORRECTION",
                ),
            )
            revision = {
                "type": "ROADMAP_REVISION",
                "lease_claim": harness.acquire(),
                "observed_at": T1,
                "base_roadmap_version": 1,
                "source_goal_id": "g1",
                "worker_dispatch_id": worker["dispatch_id"],
                "artifact_digest": worker["artifact_digest"],
                "code_review_id": code_review,
                "roadmap_audit_id": audit,
                "milestones": next_milestones,
                "goal_definition_registry": definitions,
                "goal_queue": next_queue,
                "authorization_envelope": proposed_authorization,
                "next_goal_id": "g2",
                "projection_digest": digest("placeholder"),
                "reason_code": "SCOPED_CORRECTION",
            }
            harness.bind_roadmap_revision(revision, audit)
            revision["projection_digest"] = expected_projection_digest(
                harness.state(), revision
            )
            applied = harness.apply(revision)
            self.assertEqual(
                applied["operation_status"], "ROADMAP_REVISION_APPLIED"
            )
            state = harness.state()
            self.assertEqual(
                state["goal_execution_ledger"]["g1"]["status"], "RETIRED"
            )
            self.assertEqual(
                len(state["goal_execution_ledger"]["g1"]["attempts"]), 2
            )
            self.assertEqual(state["goal_execution_ledger"]["g2"]["attempts"], [])
            self.assertIn("g1", state["goal_definition_registry"])
            self.assertIn("g2", state["goal_definition_registry"])


if __name__ == "__main__":
    unittest.main()
