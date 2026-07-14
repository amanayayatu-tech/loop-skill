from __future__ import annotations

from state_runtime_support import *  # noqa: F403


class AdaptiveStateRuntimeFinalizationTests(AdaptiveStateRuntimeTestCase):  # noqa: F405
    def test_three_review_kinds_final_chain_and_separate_finalize_cas(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            harness.register_control_result(
                "GOAL",
                "controller-goal-create",
                "controller-1",
                {"action": "CREATE", "marker_digest": digest("goal-marker")},
                {"goal_id": "native-goal-1", "status": "ACTIVE"},
            )
            harness.register_control_result(
                "AUTOMATION",
                "automation-create",
                "controller-1",
                {"action": "CREATE", "config_digest": digest("automation-config")},
                {"automation_id": "heartbeat-1", "status": "ACTIVE"},
            )
            worker = harness.worker_pass()
            code_review = harness.review("CODE_REVIEW", "REVIEW_PASS", worker)

            claim = harness.acquire()
            before = persisted_snapshot(root)
            premature, _ = harness.prepare_outbox(
                claim,
                "ASSURANCE",
                "final-audit-premature",
                {
                    "review_kind": "FINAL_AUDIT",
                    "goal_id": "g1",
                    "worker_dispatch_id": worker["dispatch_id"],
                    "worker_report_digest": worker["report_digest"],
                    "artifact_digest": worker["artifact_digest"],
                    "code_review_id": code_review,
                    "roadmap_audit_id": "missing-roadmap-audit",
                },
                target_id="reviewer-1",
            )
            self.assertEqual(premature["status"], "REVIEW_CHAIN_INVALID")
            self.assertEqual(persisted_snapshot(root), before)

            roadmap_audit = harness.review(
                "ROADMAP_AUDIT",
                "ROADMAP_AUDIT_PASS_FINAL_CANDIDATE",
                worker,
                code_review_id=code_review,
                claim=claim,
            )
            final_audit = harness.review(
                "FINAL_AUDIT",
                "FINAL_REVIEW_PASS",
                worker,
                code_review_id=code_review,
                roadmap_audit_id=roadmap_audit,
            )
            version_after_final_audit = harness.version()
            finalize_claim = harness.acquire()
            wrong = {
                "type": "FINALIZE_LOOP",
                "lease_claim": finalize_claim,
                "observed_at": T1,
                "base_roadmap_version": 1,
                "final_goal_id": "g1",
                "worker_dispatch_id": worker["dispatch_id"],
                "artifact_digest": worker["artifact_digest"],
                "code_review_id": code_review,
                "roadmap_audit_id": roadmap_audit,
                "final_audit_id": final_audit,
                "terminal_status": "LOOP_COMPLETE_WITH_LIMITATION",
                "projection_digest": digest("terminal-projection"),
                "finalization_id": "finalization-1",
                "controller_goal_id": "native-goal-1",
                "automation_id": "heartbeat-1",
            }
            before = persisted_snapshot(root)
            self.assertEqual(
                harness.apply(wrong)["status"], "TERMINAL_STATUS_EVIDENCE_MISMATCH"
            )
            self.assertEqual(persisted_snapshot(root), before)
            correct = {**wrong, "terminal_status": "LOOP_COMPLETE"}
            bad_projection = {
                **correct,
                "projection_digest": "sha256:" + "0" * 64,
            }
            before_bad_projection = persisted_snapshot(root)
            rejected_projection = harness.apply(bad_projection)
            self.assertEqual(
                rejected_projection["status"], "PROJECTION_DIGEST_MISMATCH"
            )
            self.assertEqual(
                persisted_snapshot(root), before_bad_projection
            )
            correct["projection_digest"] = expected_projection_digest(
                harness.state(), correct
            )
            finalized = harness.apply(correct)
            self.assertEqual(finalized["operation_status"], "FINALIZE_LOOP_APPLIED")
            self.assertGreater(finalized["state_version_after"], version_after_final_audit)
            state = harness.state()
            self.assertEqual(state["terminal_status"], "LOOP_COMPLETE")
            self.assertEqual(state["goal_queue"], [])
            self.assertIsNone(state["active_milestone_id"])
            self.assertEqual(state["finalization_outbox"]["status"], "PREPARED")
            legacy_prepared = copy.deepcopy(state)
            legacy_prepared["finalization_outbox"].pop("native_goal_policy")
            legacy_prepared["finalization_outbox"].pop("closeout_capability")
            _, state_validator = harness.runtime._load_validators()
            harness.runtime._validate_canonical_state(
                legacy_prepared, state_validator
            )
            with self.assertRaisesRegex(
                state_runtime_module.RuntimeRejection,
                "FINALIZATION_CAPABILITY_MIGRATION_REQUIRED",
            ):
                harness.runtime._ack_finalization(
                    legacy_prepared,
                    {"observed_at": T1},
                    {},
                    [],
                    legacy_prepared["state_version"] + 1,
                )
            goal_observation = read_evidence_artifact(
                "final-goal-observation", '{"goal_id":"native-goal-1","status":"COMPLETE"}'
            )
            automation_observation = read_evidence_artifact(
                "final-automation-observation", '{"automation_id":"heartbeat-1","status":"PAUSED"}'
            )
            finalization_mutation = {
                "type": "ACK_FINALIZATION",
                "observed_at": T1,
                "finalization_id": "finalization-1",
                "finalized_state_version": finalized["state_version_after"],
                "controller_goal_id": "native-goal-1",
                "native_goal_policy": state["finalization_outbox"][
                    "native_goal_policy"
                ],
                "closeout_capability": state["finalization_outbox"][
                    "closeout_capability"
                ],
                "controller_goal_status": "COMPLETE",
                "controller_goal_observation_path": goal_observation["path"],
                "controller_goal_observation_digest": goal_observation["digest"],
                "automation_id": "heartbeat-1",
                "automation_status": "PAUSED",
                "automation_observation_path": automation_observation["path"],
                "automation_observation_digest": automation_observation["digest"],
            }
            same_observation = read_evidence_artifact(
                "same-final-observation",
                '{"goal_id":"native-goal-1","status":"COMPLETE"}',
            )
            same_mutation = {
                **finalization_mutation,
                "controller_goal_observation_path": same_observation["path"],
                "controller_goal_observation_digest": same_observation["digest"],
                "automation_observation_path": same_observation["path"],
                "automation_observation_digest": same_observation["digest"],
            }
            capability_mismatch = {
                **finalization_mutation,
                "closeout_capability": "sha256:" + "0" * 64,
            }
            before_capability = persisted_snapshot(root)
            capability_rejected = harness.apply(
                capability_mismatch,
                artifacts=[goal_observation, automation_observation],
            )
            self.assertEqual(
                capability_rejected["status"],
                "FINALIZATION_CAPABILITY_MISMATCH",
            )
            self.assertEqual(persisted_snapshot(root), before_capability)
            before_same = persisted_snapshot(root)
            same_rejected = harness.apply(
                same_mutation,
                artifacts=[same_observation],
            )
            self.assertEqual(
                same_rejected["status"],
                "FINALIZATION_OBSERVATIONS_NOT_DISTINCT",
            )
            self.assertEqual(persisted_snapshot(root), before_same)

            wrong_automation = read_evidence_artifact(
                "wrong-final-automation-observation",
                '{"automation_id":"other-heartbeat","status":"PAUSED"}',
            )
            mismatched_mutation = {
                **finalization_mutation,
                "automation_observation_path": wrong_automation["path"],
                "automation_observation_digest": wrong_automation["digest"],
            }
            before_mismatch = persisted_snapshot(root)
            mismatched = harness.apply(
                mismatched_mutation,
                artifacts=[goal_observation, wrong_automation],
            )
            self.assertEqual(
                mismatched["status"], "OBSERVATION_ARTIFACT_MISMATCH"
            )
            self.assertEqual(persisted_snapshot(root), before_mismatch)

            before_unbound = persisted_snapshot(root)
            unbound = harness.apply(finalization_mutation)
            self.assertEqual(unbound["status"], "OBSERVATION_ARTIFACT_UNBOUND")
            self.assertEqual(persisted_snapshot(root), before_unbound)
            finalization_ack = harness.apply(
                finalization_mutation,
                artifacts=[goal_observation, automation_observation],
            )
            self.assertEqual(
                finalization_ack["operation_status"], "FINALIZATION_ACKED"
            )
            state = harness.state()
            self.assertEqual(state["finalization_outbox"]["status"], "ACKED")
            self.assertEqual(
                state["finalization_receipt"]["automation_status"], "PAUSED"
            )
            legacy_acked = copy.deepcopy(state)
            for field in ("native_goal_policy", "closeout_capability"):
                legacy_acked["finalization_outbox"].pop(field)
                legacy_acked["finalization_receipt"].pop(field)
            harness.runtime._validate_canonical_state(
                legacy_acked, state_validator
            )
            terminal_before = persisted_snapshot(root)
            self.assertEqual(
                harness.apply(
                    {
                        "type": "ACQUIRE_LEASE",
                        "routing_turn_id": "after-terminal-turn",
                        "lease_id": "after-terminal-lease",
                        "owner_kind": "HEARTBEAT",
                        "owner_identity": "controller-1",
                        "observed_at": T1,
                        "expires_at": T4,
                    }
                )["status"],
                "LOOP_ALREADY_TERMINAL",
            )
            self.assertEqual(persisted_snapshot(root), terminal_before)

    def test_stop_loop_blocks_goal_pauses_heartbeat_and_acks_finalization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            definitions = {
                "g1": goal("g1", "m1"),
                "g2": goal("g2", "m2", depends_on=["g1"]),
            }
            milestones = [
                milestone("m1", "ACTIVE"),
                milestone("m2", "PLANNED", depends_on=["m1"]),
            ]
            harness.initialize(
                milestones=milestones,
                definitions=definitions,
                queue=[
                    queue_entry("g1", "m1", "READY", 1),
                    queue_entry("g2", "m2", "PLANNED", 1, depends_on=["g1"]),
                ],
            )
            harness.register_control_result(
                "GOAL",
                "controller-goal-create",
                "controller-1",
                {"action": "CREATE"},
                {"goal_id": "native-goal-1", "status": "ACTIVE"},
            )
            harness.register_control_result(
                "AUTOMATION",
                "automation-create",
                "controller-1",
                {},
                {"automation_id": "heartbeat-1", "status": "ACTIVE"},
            )
            blocker_fingerprint = digest("PAYLOAD_DIGEST_MISMATCH:stable")
            blocker_observations: list[dict[str, Any]] = []
            blocker_observation_artifacts: list[dict[str, str]] = []

            def make_observation(
                index: int, turn_id: str, observed_at: str
            ) -> tuple[dict[str, Any], dict[str, str]]:
                content = json.dumps(
                    {
                        "blocker_code": "PAYLOAD_DIGEST_MISMATCH",
                        "blocker_fingerprint": blocker_fingerprint,
                        "controller_goal_id": "native-goal-1",
                        "goal_turn_id": turn_id,
                        "observed_at": observed_at,
                        "status": "HARD_BLOCK",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                artifact = read_evidence_artifact(
                    f"hard-block-observation-{index}", content
                )
                return (
                    {
                        "goal_turn_id": turn_id,
                        "observed_at": observed_at,
                        "blocker_code": "PAYLOAD_DIGEST_MISMATCH",
                        "blocker_fingerprint": blocker_fingerprint,
                        "controller_goal_id": "native-goal-1",
                        "report_path": artifact["path"],
                        "report_digest": artifact["digest"],
                    },
                    artifact,
                )

            for index, observed_at in enumerate((T1, T2, T3), start=1):
                observation_claim = harness.acquire(observed_at=observed_at)
                observation, artifact = make_observation(
                    index,
                    observation_claim["routing_turn_id"],
                    observed_at,
                )
                blocker_observations.append(observation)
                blocker_observation_artifacts.append(artifact)
                release_request = harness.make_request(
                    {
                        "type": "RELEASE_LEASE",
                        "lease_claim": observation_claim,
                        "observed_at": observed_at,
                        "reason_code": "HARD_BLOCK_OBSERVATION_ONLY",
                    },
                    evidence_paths=[artifact["path"]],
                    artifacts=[artifact],
                )
                released = harness.runtime.apply(release_request)
                self.assertEqual(
                    released["operation_status"], "CONTROLLER_LEASE_RELEASED"
                )

            observation_turn_ids = [
                item["goal_turn_id"] for item in blocker_observations
            ]
            blocker_content = json.dumps(
                {
                    "blocker_code": "PAYLOAD_DIGEST_MISMATCH",
                    "blocker_fingerprint": blocker_fingerprint,
                    "controller_goal_id": "native-goal-1",
                    "observation_turn_ids": observation_turn_ids,
                    "stop_basis": "THREE_OBSERVATIONS",
                    "status": "HARD_BLOCK",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            blocker = read_evidence_artifact("hard-block", blocker_content)
            heartbeat_claim = harness.acquire(
                owner_kind="HEARTBEAT",
                observed_at=T4,
                expires_at="2026-01-01T02:00:00Z",
            )
            mutation = {
                "type": "STOP_LOOP",
                "lease_claim": heartbeat_claim,
                "observed_at": T4,
                "terminal_status": "LOOP_BLOCKED",
                "stop_basis": "THREE_OBSERVATIONS",
                "blocker_code": "PAYLOAD_DIGEST_MISMATCH",
                "blocker_fingerprint": blocker_fingerprint,
                "blocker_observations": blocker_observations,
                "blocker_report_path": blocker["path"],
                "blocker_report_digest": blocker["digest"],
                "finalization_id": "blocked-finalization-1",
                "controller_goal_id": "native-goal-1",
                "automation_id": "heartbeat-1",
            }
            full_evidence_paths = [
                *[item["path"] for item in blocker_observation_artifacts],
                blocker["path"],
            ]
            before_heartbeat_stop = persisted_snapshot(root)
            heartbeat_stop = harness.runtime.apply(
                harness.make_request(
                    mutation,
                    evidence_paths=full_evidence_paths,
                    artifacts=[blocker],
                )
            )
            self.assertEqual(
                heartbeat_stop["status"], "STOP_LOOP_REQUIRES_NEW_GOAL_TURN"
            )
            self.assertEqual(persisted_snapshot(root), before_heartbeat_stop)
            released_heartbeat = harness.apply(
                {
                    "type": "RELEASE_LEASE",
                    "lease_claim": heartbeat_claim,
                    "observed_at": T4,
                    "reason_code": "WAITING_ACTIVE",
                }
            )
            self.assertTrue(released_heartbeat["ok"], released_heartbeat)

            claim = harness.acquire(
                observed_at=T4,
                expires_at="2026-01-01T02:00:00Z",
            )
            mutation["lease_claim"] = claim
            before = persisted_snapshot(root)
            stop_artifacts = [blocker]
            missing = harness.apply(mutation, artifacts=stop_artifacts)
            self.assertEqual(
                missing["status"], "GOAL_BLOCKER_OBSERVATION_IDENTITY_MISMATCH"
            )
            self.assertEqual(persisted_snapshot(root), before)

            insufficient = copy.deepcopy(mutation)
            insufficient["blocker_observations"] = blocker_observations[:1]
            rejected = harness.apply(
                insufficient,
                artifacts=stop_artifacts,
            )
            self.assertEqual(rejected["status"], "REQUEST_SCHEMA_INVALID")
            self.assertEqual(persisted_snapshot(root), before)

            request = harness.make_request(
                mutation,
                evidence_paths=full_evidence_paths,
                artifacts=stop_artifacts,
            )
            stopped = harness.runtime.apply(request)
            self.assertEqual(stopped["operation_status"], "STOP_LOOP_APPLIED")
            state = harness.state()
            self.assertEqual(state["terminal_status"], "LOOP_BLOCKED")
            self.assertIsNone(state["active_milestone_id"])
            self.assertEqual(state["goal_queue"], [])
            self.assertEqual(
                [item["status"] for item in state["milestones"]],
                ["BLOCKED", "SUPERSEDED"],
            )
            self.assertEqual(
                {item["status"] for item in state["goal_execution_ledger"].values()},
                {"RETIRED"},
            )
            finalization = state["finalization_outbox"]
            self.assertEqual(finalization["outcome_kind"], "BLOCKED")
            self.assertEqual(finalization["controller_goal_target_status"], "BLOCKED")
            self.assertEqual(finalization["automation_target_status"], "PAUSED")

            goal_observation = read_evidence_artifact(
                "blocked-goal-observation",
                '{"goal_id":"native-goal-1","status":"BLOCKED"}',
            )
            automation_observation = read_evidence_artifact(
                "blocked-automation-observation",
                '{"automation_id":"heartbeat-1","status":"PAUSED"}',
            )
            ack = {
                "type": "ACK_FINALIZATION",
                "observed_at": T4,
                "finalization_id": "blocked-finalization-1",
                "finalized_state_version": stopped["state_version_after"],
                "controller_goal_id": "native-goal-1",
                "native_goal_policy": finalization["native_goal_policy"],
                "closeout_capability": finalization["closeout_capability"],
                "controller_goal_status": "BLOCKED",
                "controller_goal_observation_path": goal_observation["path"],
                "controller_goal_observation_digest": goal_observation["digest"],
                "automation_id": "heartbeat-1",
                "automation_status": "PAUSED",
                "automation_observation_path": automation_observation["path"],
                "automation_observation_digest": automation_observation["digest"],
            }
            wrong = {**ack, "controller_goal_status": "COMPLETE"}
            terminal_before = persisted_snapshot(root)
            rejected = harness.apply(
                wrong,
                artifacts=[goal_observation, automation_observation],
            )
            self.assertEqual(rejected["status"], "FINALIZATION_TARGET_STATUS_MISMATCH")
            self.assertEqual(persisted_snapshot(root), terminal_before)

            acknowledged = harness.apply(
                ack,
                artifacts=[goal_observation, automation_observation],
            )
            self.assertEqual(acknowledged["operation_status"], "FINALIZATION_ACKED")
            state = harness.state()
            self.assertEqual(state["controller_goal"]["status"], "BLOCKED")
            self.assertEqual(state["finalization_receipt"]["outcome_kind"], "BLOCKED")
            self.assertEqual(
                state["finalization_receipt"]["blocker_code"],
                "PAYLOAD_DIGEST_MISMATCH",
            )
            state_path = root / ".codex-loop" / "LOOP_STATE.md"
            for name, mutate in (
                (
                    "receipt-identity",
                    lambda candidate: candidate["finalization_receipt"].update(
                        {"finalization_id": "different-finalization"}
                    ),
                ),
                (
                    "controller-goal",
                    lambda candidate: candidate["controller_goal"].update(
                        {"status": "ACTIVE"}
                    ),
                ),
            ):
                with self.subTest(tamper=name):
                    tampered = copy.deepcopy(state)
                    mutate(tampered)
                    state_path.write_bytes(harness.runtime._render_state(tampered))
                    with self.assertRaisesRegex(
                        state_runtime_module.RuntimeRejection,
                        "FINALIZATION_STATE_INCONSISTENT",
                    ):
                        harness.runtime.read_state()
            state_path.write_bytes(harness.runtime._render_state(state))

    def test_required_local_verification_blocks_then_unlocks_assurance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            definitions = {"g1": goal("g1", "m1")}
            harness.initialize(
                definitions=definitions,
                local_required_goal_ids=["g1"],
            )
            worker = harness.worker_pass()
            code_review = harness.review("CODE_REVIEW", "REVIEW_PASS", worker)
            claim = harness.acquire()
            before = persisted_snapshot(root)
            blocked, _ = harness.prepare_outbox(
                claim,
                "ASSURANCE",
                "roadmap-before-local",
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
            self.assertEqual(blocked["status"], "LOCAL_VERIFICATION_REQUIRED")
            self.assertEqual(persisted_snapshot(root), before)
            harness.local_pass(worker, code_review, claim=claim)
            roadmap = harness.review(
                "ROADMAP_AUDIT",
                "ROADMAP_AUDIT_PASS_FINAL_CANDIDATE",
                worker,
                code_review_id=code_review,
            )
            final = harness.review(
                "FINAL_AUDIT",
                "FINAL_REVIEW_PASS_WITH_LIMITATION",
                worker,
                code_review_id=code_review,
                roadmap_audit_id=roadmap,
            )
            self.assertEqual(harness.state()["assurance_ledger"][final]["review_kind"], "FINAL_AUDIT")

    def test_explicit_authorization_caps_deny_missing_or_borrowed_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            definitions = {
                "g1": goal(
                    "g1",
                    "m1",
                    phase_permissions={"local_commit": True},
                )
            }
            milestones = [
                milestone("m1", "ACTIVE"),
                milestone("m2", "PLANNED"),
            ]
            missing_envelope = harness.make_request(
                {
                    "type": "INITIALIZE",
                    "loop_id": "loop-auth-missing",
                    "controller_thread_id": "controller-1",
                    "state_writer_thread_id": "state-writer-1",
                    "milestones": milestones,
                    "goal_definition_registry": definitions,
                    "goal_queue": [queue_entry("g1", "m1", "READY", 1)],
                },
                expected=0,
            )
            self.assertEqual(
                harness.runtime.apply(missing_envelope)["status"],
                "REQUEST_SCHEMA_INVALID",
            )
            self.assertEqual(persisted_snapshot(root), {})

            borrowed = authorization_envelope(definitions, milestones)
            borrowed["phase_permission_caps"]["by_milestone"]["m1"][
                "local_commit"
            ] = False
            borrowed["phase_permission_caps"]["by_milestone"]["m2"][
                "local_commit"
            ] = True
            response, _ = harness.initialize(
                milestones=milestones,
                definitions=definitions,
                queue=[queue_entry("g1", "m1", "READY", 1)],
                authorization=borrowed,
            )
            self.assertEqual(response["status"], "AUTHORIZATION_BOUNDARY_VIOLATION")
            self.assertEqual(persisted_snapshot(root), {})

            missing_goal_field = authorization_envelope(definitions, milestones)
            del missing_goal_field["phase_permission_caps"]["by_goal"]["g1"][
                "phase_permissions"
            ]["local_commit"]
            response, _ = harness.initialize(
                milestones=milestones,
                definitions=definitions,
                queue=[queue_entry("g1", "m1", "READY", 1)],
                authorization=missing_goal_field,
            )
            self.assertEqual(response["status"], "REQUEST_SCHEMA_INVALID")
            self.assertEqual(persisted_snapshot(root), {})

            valid = authorization_envelope(definitions, milestones)
            response, _ = harness.initialize(
                milestones=milestones,
                definitions=definitions,
                queue=[queue_entry("g1", "m1", "READY", 1)],
                authorization=valid,
            )
            self.assertTrue(response["ok"], response)

    def test_goal_digest_uses_utf8_non_ascii_and_roadmap_rejects_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            chinese = goal("g1", "m1", objective="修复支付流程")
            correct_digest = chinese["payload_template_digest"]
            self.assertEqual(goal_definition_payload_digest(chinese), correct_digest)
            ascii_digest = goal_definition_digest(chinese, ensure_ascii=True)
            self.assertNotEqual(correct_digest, ascii_digest)
            chinese["payload_template_digest"] = ascii_digest
            response, _ = harness.initialize(
                definitions={"g1": chinese},
                authorization=authorization_envelope(
                    {"g1": chinese}, [milestone("m1", "ACTIVE")]
                ),
            )
            self.assertEqual(response["status"], "GOAL_DEFINITION_DIGEST_MISMATCH")
            self.assertEqual(persisted_snapshot(root), {})
            chinese["payload_template_digest"] = correct_digest
            response, _ = harness.initialize(
                definitions={"g1": chinese},
                authorization=authorization_envelope(
                    {"g1": chinese}, [milestone("m1", "ACTIVE")]
                ),
            )
            self.assertTrue(response["ok"], response)
            self.assertEqual(
                harness.state()["goal_definition_registry"]["g1"][
                    "payload_template_digest"
                ],
                correct_digest,
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            initial_goal = goal(
                "g1",
                "m1",
                phase_permissions={"push": True},
            )
            initial_definitions = {"g1": initial_goal}
            initial_milestones = [
                milestone("m1", "ACTIVE"),
                milestone("m2", "PLANNED", depends_on=["m1"]),
            ]
            harness.initialize(
                milestones=initial_milestones,
                definitions=initial_definitions,
                queue=[queue_entry("g1", "m1", "READY", 1)],
            )
            worker = harness.worker_pass("g1")
            code_review = harness.review("CODE_REVIEW", "REVIEW_PASS", worker)
            next_milestones = [
                milestone("m1", "COMPLETE"),
                milestone("m2", "ACTIVE", depends_on=["m1"]),
            ]
            expanded_goal = goal(
                "g2",
                "m2",
                objective="新增发布目标",
                depends_on=["g1"],
                phase_permissions={"push": True},
            )
            expanded_definitions = {**initial_definitions, "g2": expanded_goal}
            expanded_authorization = copy.deepcopy(harness.authorization)
            expanded_authorization["phase_permission_caps"]["by_goal"]["g2"] = {
                "milestone_id": "m2",
                "phase_permissions": {
                    **{permission: False for permission in PERMISSION_FIELDS},
                    "push": True,
                },
            }
            next_queue = [
                queue_entry("g2", "m2", "READY", 2, depends_on=["g1"])
            ]
            operations = [
                {
                    "operation": "UPDATE_MILESTONE",
                    "milestone_id": "m1",
                    "reason": "Complete the source milestone",
                },
                {
                    "operation": "UPDATE_MILESTONE",
                    "milestone_id": "m2",
                    "reason": "Activate the next milestone",
                },
            ]
            roadmap_audit = harness.review(
                "ROADMAP_AUDIT",
                "ROADMAP_AUDIT_PASS",
                worker,
                code_review_id=code_review,
                roadmap_plan=roadmap_plan(
                    proposal_id="expanded-authorization-proposal",
                    operations=operations,
                    milestones=next_milestones,
                    goal_definition_registry=expanded_definitions,
                    goal_queue=next_queue,
                    authorization_envelope=expanded_authorization,
                    next_goal_id="g2",
                    reason_code="ADD_G2",
                ),
            )
            claim = harness.acquire()
            revision = {
                "type": "ROADMAP_REVISION",
                "lease_claim": claim,
                "observed_at": T1,
                "base_roadmap_version": 1,
                "source_goal_id": "g1",
                "worker_dispatch_id": worker["dispatch_id"],
                "artifact_digest": worker["artifact_digest"],
                "code_review_id": code_review,
                "roadmap_audit_id": roadmap_audit,
                "milestones": next_milestones,
                "goal_definition_registry": expanded_definitions,
                "goal_queue": next_queue,
                "authorization_envelope": expanded_authorization,
                "next_goal_id": "g2",
                "projection_digest": digest("projection-expanded"),
                "reason_code": "ADD_G2",
            }
            harness.bind_roadmap_revision(revision, roadmap_audit)
            before = persisted_snapshot(root)
            response = harness.apply(revision)
            self.assertEqual(response["status"], "AUTHORIZATION_BOUNDARY_VIOLATION")
            self.assertEqual(persisted_snapshot(root), before)
            self.assertTrue(
                harness.apply(
                    {
                        "type": "RELEASE_LEASE",
                        "lease_claim": claim,
                        "observed_at": T1,
                        "reason_code": "NEGATIVE_AUTHORIZATION_TEST_COMPLETE",
                    }
                )["ok"]
            )

            bad_digest_goal = goal(
                "g2",
                "m2",
                objective="新增中文目标",
                depends_on=["g1"],
                phase_permissions={},
            )
            bad_digest_goal["payload_template_digest"] = goal_definition_digest(
                bad_digest_goal, ensure_ascii=True
            )
            self.assertNotEqual(
                bad_digest_goal["payload_template_digest"],
                goal_definition_digest(bad_digest_goal),
            )
            bounded_authorization = copy.deepcopy(harness.authorization)
            bounded_authorization["phase_permission_caps"]["by_goal"]["g2"] = {
                "milestone_id": "m2",
                "phase_permissions": {
                    permission: False for permission in PERMISSION_FIELDS
                },
            }
            bad_definitions = {
                **initial_definitions,
                "g2": bad_digest_goal,
            }
            digest_audit = harness.review(
                "ROADMAP_AUDIT",
                "ROADMAP_AUDIT_PASS",
                worker,
                code_review_id=code_review,
                roadmap_plan=roadmap_plan(
                    proposal_id="bad-digest-proposal",
                    operations=operations,
                    milestones=next_milestones,
                    goal_definition_registry=bad_definitions,
                    goal_queue=next_queue,
                    authorization_envelope=bounded_authorization,
                    next_goal_id="g2",
                    reason_code="ADD_G2_DIGEST_CHECK",
                ),
            )
            digest_claim = harness.acquire()
            digest_revision = {
                **revision,
                "lease_claim": digest_claim,
                "roadmap_audit_id": digest_audit,
                "goal_definition_registry": bad_definitions,
                "authorization_envelope": bounded_authorization,
                "reason_code": "ADD_G2_DIGEST_CHECK",
            }
            harness.bind_roadmap_revision(digest_revision, digest_audit)
            digest_revision["projection_digest"] = expected_projection_digest(
                harness.state(), digest_revision
            )
            before_digest = persisted_snapshot(root)
            response = harness.apply(digest_revision)
            self.assertEqual(response["status"], "GOAL_DEFINITION_DIGEST_MISMATCH")
            self.assertEqual(persisted_snapshot(root), before_digest)

    def test_out_of_envelope_roadmap_proposal_routes_to_approval_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            definitions = {
                "g1": goal("g1", "m1"),
                "g2": goal("g2", "m2", depends_on=["g1"]),
            }
            harness.initialize(
                milestones=[
                    milestone("m1", "ACTIVE"),
                    milestone("m2", "PLANNED", depends_on=["m1"]),
                ],
                definitions=definitions,
                queue=[
                    queue_entry("g1", "m1", "READY", 1),
                    queue_entry("g2", "m2", "PLANNED", 1, depends_on=["g1"]),
                ],
                dashboard_required=True,
            )
            worker = harness.worker_pass("g1")
            code_review = harness.review("CODE_REVIEW", "REVIEW_PASS", worker)
            next_milestones = [
                milestone("m1", "COMPLETE"),
                milestone("m2", "ACTIVE", depends_on=["m1"]),
            ]
            next_queue = [queue_entry("g2", "m2", "READY", 2, depends_on=["g1"])]
            operations = [
                {
                    "operation": "UPDATE_MILESTONE",
                    "milestone_id": "m1",
                    "reason": "Complete M1",
                },
                {
                    "operation": "UPDATE_MILESTONE",
                    "milestone_id": "m2",
                    "reason": "Activate M2",
                },
            ]
            audit = harness.review(
                "ROADMAP_AUDIT",
                "ROADMAP_CHANGE_PROPOSED",
                worker,
                code_review_id=code_review,
                roadmap_plan=roadmap_plan(
                    proposal_id="approval-only-proposal",
                    operations=operations,
                    milestones=next_milestones,
                    goal_definition_registry=definitions,
                    goal_queue=next_queue,
                    authorization_envelope=harness.authorization,
                    next_goal_id="g2",
                    reason_code="REQUIRES_SCOPE_APPROVAL",
                ),
                within_authorized_envelope=False,
            )
            self.assertEqual(
                event_lines(root)[-1]["next_action_code"],
                "ROADMAP_CHANGE_REQUIRES_APPROVAL",
            )
            self.assertFalse(
                harness.state()["assurance_ledger"][audit]["roadmap_proposal"][
                    "within_authorized_envelope"
                ]
            )
            dashboard = (
                root / ".codex-loop" / "progress-dashboard.html"
            ).read_text(encoding="utf-8")
            self.assertIn("<h2>Required user decisions</h2>", dashboard)
            self.assertIn(audit, dashboard)
            self.assertIn("ROADMAP_CHANGE_PROPOSED", dashboard)
            claim = harness.acquire()
            revision = {
                "type": "ROADMAP_REVISION",
                "lease_claim": claim,
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
                "authorization_envelope": harness.authorization,
                "next_goal_id": "g2",
                "projection_digest": digest("approval-only-projection"),
                "reason_code": "REQUIRES_SCOPE_APPROVAL",
            }
            harness.bind_roadmap_revision(revision, audit)
            before = persisted_snapshot(root)
            rejected = harness.apply(revision)
            self.assertEqual(rejected["status"], "REQUEST_SCHEMA_INVALID")
            self.assertEqual(persisted_snapshot(root), before)

    def test_roadmap_revision_changes_next_goal_and_checks_roadmap_cas(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            definitions = {
                "g1": goal("g1", "m1"),
                "g2": goal("g2", "m2", depends_on=["g1"]),
            }
            harness.initialize(
                milestones=[
                    milestone("m1", "ACTIVE"),
                    milestone("m2", "PLANNED", depends_on=["m1"]),
                ],
                definitions=definitions,
                queue=[
                    queue_entry("g1", "m1", "READY", 1),
                    queue_entry("g2", "m2", "PLANNED", 1, depends_on=["g1"]),
                ],
            )
            worker = harness.worker_pass("g1")
            code_review = harness.review("CODE_REVIEW", "REVIEW_PASS", worker)
            next_milestones = [
                milestone("m1", "COMPLETE"),
                milestone("m2", "ACTIVE", depends_on=["m1"]),
            ]
            next_queue = [
                queue_entry("g2", "m2", "READY", 2, depends_on=["g1"])
            ]
            roadmap_audit = harness.review(
                "ROADMAP_AUDIT",
                "ROADMAP_AUDIT_PASS",
                worker,
                code_review_id=code_review,
                roadmap_plan=roadmap_plan(
                    proposal_id="m1-to-m2-proposal",
                    operations=[
                        {
                            "operation": "UPDATE_MILESTONE",
                            "milestone_id": "m1",
                            "reason": "Complete M1",
                        },
                        {
                            "operation": "UPDATE_MILESTONE",
                            "milestone_id": "m2",
                            "reason": "Activate M2",
                        },
                    ],
                    milestones=next_milestones,
                    goal_definition_registry=definitions,
                    goal_queue=next_queue,
                    authorization_envelope=harness.authorization,
                    next_goal_id="g2",
                    reason_code="M1_COMPLETE",
                ),
            )
            claim = harness.acquire()
            revision = {
                "type": "ROADMAP_REVISION",
                "lease_claim": claim,
                "observed_at": T1,
                "base_roadmap_version": 1,
                "source_goal_id": "g1",
                "worker_dispatch_id": worker["dispatch_id"],
                "artifact_digest": worker["artifact_digest"],
                "code_review_id": code_review,
                "roadmap_audit_id": roadmap_audit,
                "milestones": next_milestones,
                "goal_definition_registry": definitions,
                "goal_queue": next_queue,
                "authorization_envelope": harness.authorization,
                "next_goal_id": "g2",
                "projection_digest": digest("projection:2"),
                "reason_code": "M1_COMPLETE",
            }
            harness.bind_roadmap_revision(revision, roadmap_audit)
            revision["projection_digest"] = expected_projection_digest(
                harness.state(), revision
            )
            shape_changed = copy.deepcopy(revision)
            del shape_changed["authorization_envelope"]["delegation_policy"]
            before = persisted_snapshot(root)
            rejected = harness.apply(shape_changed)
            self.assertEqual(rejected["status"], "REQUEST_SCHEMA_INVALID")
            self.assertEqual(persisted_snapshot(root), before)
            applied = harness.apply(revision)
            self.assertEqual(applied["operation_status"], "ROADMAP_REVISION_APPLIED")
            self.assertEqual(
                event_lines(root)[-1]["next_action_code"],
                "COMPLETE_CURRENT_CONTROLLER_GOAL",
            )
            state = harness.state()
            self.assertEqual(state["roadmap_version"], 2)
            self.assertEqual(state["active_milestone_id"], "m2")
            self.assertEqual(state["goal_queue"][0]["goal_id"], "g2")
            self.assertEqual(state["goal_execution_ledger"]["g1"]["status"], "COMPLETE")

            worker_thread = state["thread_registry"]["worker-1"]
            self.assertEqual(worker_thread["role_kind"], "WORKER")
            mismatched_goal_claim = harness.acquire()
            before = persisted_snapshot(root)
            rejected, _ = harness.prepare_outbox(
                mismatched_goal_claim,
                "DISPATCH",
                "g2-before-controller-goal-transition",
                {
                    "goal_id": "g2",
                    "goal_definition_digest": definitions["g2"][
                        "payload_template_digest"
                    ],
                },
                target_id="worker-1",
            )
            self.assertEqual(
                rejected["status"], "CONTROLLER_GOAL_MILESTONE_NOT_ACTIVE"
            )
            self.assertEqual(persisted_snapshot(root), before)
            self.assertTrue(
                harness.apply(
                    {
                        "type": "RELEASE_LEASE",
                        "lease_claim": mismatched_goal_claim,
                        "observed_at": T1,
                        "reason_code": "GOAL_TRANSITION_REQUIRED",
                    }
                )["ok"]
            )

            harness.complete_controller_goal()
            harness.ensure_controller_goal("m2")
            transitioned = harness.state()["controller_goal"]
            self.assertEqual(transitioned["milestone_id"], "m2")
            self.assertEqual(transitioned["status"], "ACTIVE")

            next_dispatch_claim = harness.acquire()
            prepared, payload = harness.prepare_outbox(
                next_dispatch_claim,
                "DISPATCH",
                "g2-after-controller-goal-transition",
                {
                    "goal_id": "g2",
                    "goal_definition_digest": definitions["g2"][
                        "payload_template_digest"
                    ],
                },
                target_id="worker-1",
            )
            self.assertTrue(prepared["ok"], prepared)
            cancelled = harness.apply(
                {
                    "type": "CANCEL_OUTBOX",
                    "lease_claim": next_dispatch_claim,
                    "observed_at": T1,
                    "outbox_kind": "DISPATCH",
                    "outbox_id": "g2-after-controller-goal-transition",
                    "payload_digest": payload,
                    "target_id": "worker-1",
                    "cancel_reason_code": "NEGATIVE_TEST_COMPLETE",
                    "recovery_evidence_paths": ["evidence/g2-dispatch-cancel.json"],
                }
            )
            self.assertTrue(cancelled["ok"], cancelled)

            new_claim = harness.acquire()
            stale_revision = {**revision, "lease_claim": new_claim}
            before = persisted_snapshot(root)
            rejected = harness.apply(stale_revision)
            self.assertEqual(rejected["status"], "ROADMAP_VERSION_CONFLICT")
            self.assertEqual(persisted_snapshot(root), before)

    def test_same_milestone_sibling_keeps_controller_goal_active(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            definitions = {
                "g1": goal("g1", "m1"),
                "g2": goal("g2", "m1", depends_on=["g1"]),
            }
            harness.initialize(
                milestones=[milestone("m1", "ACTIVE")],
                definitions=definitions,
                queue=[
                    queue_entry("g1", "m1", "READY", 1),
                    queue_entry("g2", "m1", "PLANNED", 1, depends_on=["g1"]),
                ],
            )
            worker = harness.worker_pass("g1")
            original_controller_goal = copy.deepcopy(
                harness.state()["controller_goal"]
            )
            code_review = harness.review("CODE_REVIEW", "REVIEW_PASS", worker)
            next_milestones = [milestone("m1", "ACTIVE")]
            next_queue = [
                queue_entry("g2", "m1", "READY", 2, depends_on=["g1"])
            ]
            roadmap_audit = harness.review(
                "ROADMAP_AUDIT",
                "ROADMAP_AUDIT_PASS",
                worker,
                code_review_id=code_review,
                roadmap_plan=roadmap_plan(
                    proposal_id="same-milestone-proposal",
                    operations=[
                        {
                            "operation": "UPDATE_MILESTONE",
                            "milestone_id": "m1",
                            "reason": "Unlock the dependency-ready sibling",
                        }
                    ],
                    milestones=next_milestones,
                    goal_definition_registry=definitions,
                    goal_queue=next_queue,
                    authorization_envelope=harness.authorization,
                    next_goal_id="g2",
                    reason_code="UNLOCK_SIBLING",
                ),
            )
            claim = harness.acquire()
            revision = {
                "type": "ROADMAP_REVISION",
                "lease_claim": claim,
                "observed_at": T1,
                "base_roadmap_version": 1,
                "source_goal_id": "g1",
                "worker_dispatch_id": worker["dispatch_id"],
                "artifact_digest": worker["artifact_digest"],
                "code_review_id": code_review,
                "roadmap_audit_id": roadmap_audit,
                "milestones": next_milestones,
                "goal_definition_registry": definitions,
                "goal_queue": next_queue,
                "authorization_envelope": harness.authorization,
                "next_goal_id": "g2",
                "projection_digest": digest("same-milestone-projection"),
                "reason_code": "UNLOCK_SIBLING",
            }
            harness.bind_roadmap_revision(revision, roadmap_audit)
            revision["projection_digest"] = expected_projection_digest(
                harness.state(), revision
            )
            applied = harness.apply(revision)
            self.assertTrue(applied["ok"], applied)
            self.assertEqual(
                event_lines(root)[-1]["next_action_code"],
                "PREPARE_NEXT_GOAL_OUTBOX",
            )
            self.assertEqual(
                harness.state()["controller_goal"], original_controller_goal
            )

            dispatch_claim = harness.acquire()
            prepared, _ = harness.prepare_outbox(
                dispatch_claim,
                "DISPATCH",
                "same-milestone-g2-dispatch",
                {
                    "goal_id": "g2",
                    "goal_definition_digest": definitions["g2"][
                        "payload_template_digest"
                    ],
                },
                target_id="worker-1",
            )
            self.assertTrue(prepared["ok"], prepared)

    def test_roadmap_revision_can_add_bounded_milestone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            worker = harness.worker_pass("g1")
            code_review = harness.review("CODE_REVIEW", "REVIEW_PASS", worker)
            g2 = goal("g2", "m2", depends_on=["g1"])
            g2["validation_matrix"] = {
                "functional": {"required": True, "evidence": ["pytest"]},
                "regression": {"required": False, "reason": "bounded test"},
                "static_quality": {"required": False, "reason": "bounded test"},
                "compatibility": {"required": False, "reason": "bounded test"},
                "security": {"required": False, "reason": "bounded test"},
                "performance": {"required": False, "reason": "bounded test"},
                "user_experience": {"required": False, "reason": "bounded test"},
                "change_impact": {"required": False, "reason": "bounded test"},
            }
            g2["payload_template_digest"] = goal_definition_digest(g2)
            definitions = {**harness.definitions, "g2": g2}
            proposed_authorization = copy.deepcopy(harness.authorization)
            proposed_authorization["phase_permission_caps"]["by_milestone"]["m2"] = {
                **{permission: False for permission in PERMISSION_FIELDS},
                "local_commit": True,
            }
            proposed_authorization["phase_permission_caps"]["by_goal"]["g2"] = {
                "milestone_id": "m2",
                "phase_permissions": copy.deepcopy(g2["phase_permissions"]),
            }
            next_milestones = [
                milestone("m1", "COMPLETE"),
                milestone("m2", "ACTIVE", depends_on=["m1"]),
            ]
            next_queue = [
                queue_entry("g2", "m2", "READY", 2, depends_on=["g1"])
            ]
            roadmap_audit = harness.review(
                "ROADMAP_AUDIT",
                "ROADMAP_AUDIT_PASS",
                worker,
                code_review_id=code_review,
                roadmap_plan=roadmap_plan(
                    proposal_id="bounded-m2-proposal",
                    operations=[
                        {
                            "operation": "UPDATE_MILESTONE",
                            "milestone_id": "m1",
                            "reason": "Complete M1",
                        },
                        {
                            "operation": "ADD_MILESTONE",
                            "milestone_id": "m2",
                            "reason": "Add bounded M2 from new evidence",
                        },
                    ],
                    milestones=next_milestones,
                    goal_definition_registry=definitions,
                    goal_queue=next_queue,
                    authorization_envelope=proposed_authorization,
                    next_goal_id="g2",
                    reason_code="NEW_EVIDENCE_ADDS_M2",
                ),
            )
            claim = harness.acquire()
            revision = {
                    "type": "ROADMAP_REVISION",
                    "lease_claim": claim,
                    "observed_at": T1,
                    "base_roadmap_version": 1,
                    "source_goal_id": "g1",
                    "worker_dispatch_id": worker["dispatch_id"],
                    "artifact_digest": worker["artifact_digest"],
                    "code_review_id": code_review,
                    "roadmap_audit_id": roadmap_audit,
                    "milestones": next_milestones,
                    "goal_definition_registry": definitions,
                    "goal_queue": next_queue,
                    "authorization_envelope": proposed_authorization,
                    "next_goal_id": "g2",
                    "projection_digest": digest("bounded-new-milestone"),
                    "reason_code": "NEW_EVIDENCE_ADDS_M2",
                }
            harness.bind_roadmap_revision(revision, roadmap_audit)
            revision["projection_digest"] = expected_projection_digest(
                harness.state(), revision
            )
            response = harness.apply(revision)
            self.assertEqual(response["operation_status"], "ROADMAP_REVISION_APPLIED")
            state = harness.state()
            self.assertEqual(state["active_milestone_id"], "m2")
            self.assertEqual(state["goal_queue"][0]["goal_id"], "g2")
            self.assertEqual(state["validation_gate_status"], "PENDING")

    def test_current_chain_limitation_cannot_be_upgraded_at_finalize(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            harness.register_control_result(
                "GOAL",
                "limitation-controller-goal",
                "controller-1",
                {"action": "CREATE", "marker_digest": digest("limitation-goal-marker")},
                {"goal_id": "limitation-native-goal", "status": "ACTIVE"},
            )
            harness.register_control_result(
                "AUTOMATION",
                "limitation-automation",
                "controller-1",
                {"action": "CREATE", "config_digest": digest("limitation-automation")},
                {"automation_id": "limitation-heartbeat", "status": "ACTIVE"},
            )
            worker = harness.worker_pass()
            code_review = harness.review(
                "CODE_REVIEW", "REVIEW_PASS_WITH_LIMITATION", worker
            )
            roadmap_audit = harness.review(
                "ROADMAP_AUDIT",
                "ROADMAP_AUDIT_PASS_FINAL_CANDIDATE",
                worker,
                code_review_id=code_review,
            )
            final_audit = harness.review(
                "FINAL_AUDIT",
                "FINAL_REVIEW_PASS",
                worker,
                code_review_id=code_review,
                roadmap_audit_id=roadmap_audit,
            )
            claim = harness.acquire()
            mutation = {
                "type": "FINALIZE_LOOP",
                "lease_claim": claim,
                "observed_at": T1,
                "base_roadmap_version": 1,
                "final_goal_id": "g1",
                "worker_dispatch_id": worker["dispatch_id"],
                "artifact_digest": worker["artifact_digest"],
                "code_review_id": code_review,
                "roadmap_audit_id": roadmap_audit,
                "final_audit_id": final_audit,
                "terminal_status": "LOOP_COMPLETE",
                "projection_digest": digest("limitation-terminal"),
                "finalization_id": "limitation-finalization",
                "controller_goal_id": "limitation-native-goal",
                "automation_id": "limitation-heartbeat",
            }
            before = persisted_snapshot(root)
            rejected = harness.apply(mutation)
            self.assertEqual(rejected["status"], "TERMINAL_STATUS_EVIDENCE_MISMATCH")
            self.assertEqual(persisted_snapshot(root), before)
            accepted = harness.apply(
                {
                    **mutation,
                    "terminal_status": "LOOP_COMPLETE_WITH_LIMITATION",
                    "projection_digest": expected_projection_digest(
                        harness.state(),
                        {
                            **mutation,
                            "terminal_status": "LOOP_COMPLETE_WITH_LIMITATION",
                        },
                    ),
                }
            )
            self.assertEqual(accepted["operation_status"], "FINALIZE_LOOP_APPLIED")

    def test_dashboard_recovery_uses_state_version_event_order_and_stable_root_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize(dashboard_required=True)
            acquire_request = harness.make_request(
                {
                    "type": "ACQUIRE_LEASE",
                    "routing_turn_id": "z-routing-turn",
                    "lease_id": "z-routing-lease",
                    "owner_kind": "GOAL_TURN",
                    "owner_identity": "controller-1",
                    "observed_at": T1,
                    "expires_at": T4,
                },
                request_id="z-acquire-request",
                event_id="z-acquire-event",
            )
            acquired = harness.runtime.apply(acquire_request)
            self.assertTrue(acquired["ok"], acquired)
            released = harness.runtime.apply(
                harness.make_request(
                    {
                        "type": "RELEASE_LEASE",
                        "lease_claim": acquired["result"]["lease_claim"],
                        "observed_at": T1,
                        "reason_code": "WAITING_ACTIVE",
                    },
                    request_id="a-release-request",
                    event_id="a-release-event",
                )
            )
            self.assertTrue(released["ok"], released)
            recovered = harness.runtime.recover()
            self.assertTrue(recovered["ok"], recovered)
            dashboard = (
                root / ".codex-loop" / "progress-dashboard.html"
            ).read_text(encoding="utf-8")
            self.assertLess(
                dashboard.index("z-acquire-event"),
                dashboard.index("a-release-event"),
            )
            self.assertFalse(
                (root / ".codex-loop" / ".state-runtime.lock").exists()
            )

    def test_controller_goal_cannot_end_before_same_milestone_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            definitions = {
                "g1": goal("g1", "m1"),
                "g2": goal("g2", "m1", depends_on=["g1"]),
            }
            harness.initialize(
                definitions=definitions,
                queue=[
                    queue_entry("g1", "m1", "READY", 1),
                    queue_entry("g2", "m1", "PLANNED", 1, depends_on=["g1"]),
                ],
            )
            current = harness.ensure_controller_goal("m1")
            claim = harness.acquire()
            before = persisted_snapshot(root)
            rejected, _ = harness.prepare_outbox(
                claim,
                "GOAL",
                "early-controller-goal-close",
                {
                    "action": "UPDATE",
                    "goal_id": current["goal_id"],
                    "milestone_id": "m1",
                    "objective_digest": current["objective_digest"],
                    "marker": current["marker"],
                    "target_status": "COMPLETE",
                },
                target_id="controller-1",
            )
            self.assertEqual(
                rejected["status"], "CONTROLLER_GOAL_EARLY_TERMINATION"
            )
            self.assertEqual(persisted_snapshot(root), before)

    def test_control_ack_requires_bound_tool_observation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            claim = harness.acquire()
            prepared, payload = harness.prepare_outbox(
                claim,
                "THREAD",
                "unobserved-worker-thread",
                {"role_kind": "WORKER"},
                target_id="controller-1",
            )
            self.assertTrue(prepared["ok"], prepared)
            self.assertTrue(
                harness.mark_sent(
                    claim,
                    "THREAD",
                    "unobserved-worker-thread",
                    payload,
                    target_id="controller-1",
                )["ok"]
            )
            identity = harness.state()["thread_creation_outbox"][
                "unobserved-worker-thread"
            ]["identity"]
            result = {
                "thread_id": "worker-unobserved",
                **identity,
                "worktree_path": ".",
            }
            observation_path = ".codex-loop/reports/unobserved-tool-result.json"
            request = harness.make_request(
                {
                    "type": "ACK_OUTBOX",
                    "lease_claim": claim,
                    "observed_at": T1,
                    "outbox_kind": "THREAD",
                    "outbox_id": "unobserved-worker-thread",
                    "payload_digest": payload,
                    "target_id": "controller-1",
                    "ack_evidence_paths": [observation_path],
                    "result": result,
                },
                evidence_paths=[observation_path],
            )
            before = persisted_snapshot(root)
            rejected = harness.runtime.apply(request)
            self.assertEqual(
                rejected["status"], "CONTROL_TOOL_OBSERVATION_UNBOUND"
            )
            self.assertEqual(persisted_snapshot(root), before)

    def test_external_codex_worktree_requires_explicit_authorized_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            external_root = root.parent / "authorized-codex-worktrees"
            harness = Harness(root)
            definitions = {"g1": goal("g1", "m1")}
            milestones = [milestone("m1", "ACTIVE")]
            authorization = authorization_envelope(definitions, milestones)
            authorization["control_plane_limits"][
                "allowed_external_worktree_roots"
            ] = [str(external_root.resolve(strict=False))]
            harness.initialize(
                definitions=definitions,
                milestones=milestones,
                authorization=authorization,
            )
            worker_path = external_root / "worker-1"
            harness.register_control_result(
                "THREAD",
                "external-worker-thread",
                "controller-1",
                {
                    "role_kind": "WORKER",
                    "environment_kind": "WORKTREE",
                },
                {
                    "thread_id": "external-worker-1",
                    "worktree_path": str(worker_path),
                },
            )
            self.assertEqual(
                harness.state()["thread_registry"]["external-worker-1"][
                    "worktree_path"
                ],
                str(worker_path.resolve(strict=False)),
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            claim = harness.acquire()
            prepared, payload = harness.prepare_outbox(
                claim,
                "THREAD",
                "unauthorized-external-worker",
                {
                    "role_kind": "WORKER",
                    "environment_kind": "WORKTREE",
                },
                target_id="controller-1",
            )
            self.assertTrue(prepared["ok"], prepared)
            self.assertTrue(
                harness.mark_sent(
                    claim,
                    "THREAD",
                    "unauthorized-external-worker",
                    payload,
                    target_id="controller-1",
                )["ok"]
            )
            before = persisted_snapshot(root)
            rejected = harness.ack_outbox(
                claim,
                "THREAD",
                "unauthorized-external-worker",
                payload,
                target_id="controller-1",
                result={
                    "thread_id": "unauthorized-worker-1",
                    "project_id": "test-project",
                    "task_kind": "PROJECT_TASK",
                    "bootstrap_role_kind": "implementation",
                    "formal_role_kind": "WORKER",
                    "bootstrap_prompt_digest": digest("bootstrap:implementation"),
                    "environment_kind": "WORKTREE",
                    "worktree_path": "/tmp/not-authorized/worker-1",
                },
            )
            self.assertEqual(rejected["status"], "PATH_SCOPE_ESCAPE")
            self.assertEqual(persisted_snapshot(root), before)

    def test_thread_budget_role_and_business_heartbeat_are_runtime_singletons(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            definitions = {"g1": goal("g1", "m1")}
            milestones = [milestone("m1", "ACTIVE")]
            authorization = authorization_envelope(definitions, milestones)
            authorization["control_plane_limits"]["max_child_threads"] = 1
            harness.initialize(authorization=authorization)
            claim = harness.acquire()
            before = persisted_snapshot(root)
            rejected, _ = harness.prepare_outbox(
                claim,
                "THREAD",
                "over-budget-worker",
                {"role_kind": "WORKER"},
                target_id="controller-1",
            )
            self.assertEqual(rejected["status"], "THREAD_BUDGET_EXHAUSTED")
            self.assertEqual(persisted_snapshot(root), before)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            harness.register_control_result(
                "THREAD",
                "singleton-worker",
                "controller-1",
                {"role_kind": "WORKER"},
                {"thread_id": "worker-singleton", "worktree_path": "."},
            )
            duplicate_claim = harness.acquire()
            before_duplicate = persisted_snapshot(root)
            duplicate, _ = harness.prepare_outbox(
                duplicate_claim,
                "THREAD",
                "duplicate-worker",
                {"role_kind": "WORKER"},
                target_id="controller-1",
            )
            self.assertEqual(
                duplicate["status"], "THREAD_ROLE_ALREADY_REGISTERED"
            )
            self.assertEqual(persisted_snapshot(root), before_duplicate)
            self.assertTrue(
                harness.apply(
                    {
                        "type": "RELEASE_LEASE",
                        "lease_claim": duplicate_claim,
                        "observed_at": T1,
                        "reason_code": "DUPLICATE_THREAD_REJECTED",
                    }
                )["ok"]
            )
            harness.register_control_result(
                "AUTOMATION",
                "singleton-heartbeat",
                "controller-1",
                {},
                {"automation_id": "heartbeat-singleton", "status": "ACTIVE"},
            )
            heartbeat_claim = harness.acquire()
            before_heartbeat = persisted_snapshot(root)
            duplicate_heartbeat, _ = harness.prepare_outbox(
                heartbeat_claim,
                "AUTOMATION",
                "duplicate-heartbeat",
                {},
                target_id="controller-1",
            )
            self.assertEqual(
                duplicate_heartbeat["status"],
                "BUSINESS_HEARTBEAT_ALREADY_REGISTERED",
            )
            self.assertEqual(persisted_snapshot(root), before_heartbeat)

    def test_malformed_and_random_sequences_never_mutate_or_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            generator = random.Random(20260711)
            operation_names = [
                "ACQUIRE_LEASE",
                "RECORD_STEERING",
                "REGISTER_DECISION",
                "RECORD_FAILURE",
                "RECORD_VALIDATION",
                "RECORD_CONTEXT_FRESHNESS",
                "PREPARE_OUTBOX",
                "ACK_OUTBOX",
                "RECORD_REVIEW",
                "ROADMAP_REVISION",
                "FINALIZE_LOOP",
                "STOP_LOOP",
                "ACK_FINALIZATION",
            ]
            case_count = int(os.environ.get("ADAPTIVE_STATE_FUZZ_CASES", "100"))
            batch_size = 50
            for batch_start in range(0, case_count, batch_size):
                acquire = harness.make_request(
                    {
                        "type": "ACQUIRE_LEASE",
                        "routing_turn_id": f"fuzz-turn-{batch_start}",
                        "lease_id": f"fuzz-lease-{batch_start}",
                        "owner_kind": generator.choice(["GOAL_TURN", "HEARTBEAT"]),
                        "owner_identity": "controller-1",
                        "observed_at": T1,
                        "expires_at": T4,
                    },
                    request_id=f"fuzz-acquire-request-{batch_start}",
                    event_id=f"fuzz-acquire-event-{batch_start}",
                )
                acquired = harness.runtime.apply(acquire)
                self.assertTrue(acquired["ok"])
                acquired_version = acquired["state_version_after"]
                replayed_acquire = harness.runtime.apply(copy.deepcopy(acquire))
                self.assertTrue(replayed_acquire["ok"])
                self.assertEqual(
                    replayed_acquire["state_version_after"], acquired_version
                )

                claim = acquired["result"]["lease_claim"]
                release = harness.make_request(
                    {
                        "type": "RELEASE_LEASE",
                        "lease_claim": claim,
                        "observed_at": T1,
                        "reason_code": generator.choice(
                            ["WAITING_ACTIVE", "WAITING_QUOTA_RECOVERY"]
                        ),
                    },
                    request_id=f"fuzz-release-request-{batch_start}",
                    event_id=f"fuzz-release-event-{batch_start}",
                )
                released = harness.runtime.apply(release)
                self.assertTrue(released["ok"])
                released_version = released["state_version_after"]
                replayed_release = harness.runtime.apply(copy.deepcopy(release))
                self.assertTrue(replayed_release["ok"])
                self.assertEqual(
                    replayed_release["state_version_after"], released_version
                )

                baseline = runtime_surface_fingerprint(root)
                for index in range(
                    batch_start,
                    min(batch_start + batch_size, case_count),
                ):
                    operation = generator.choice(operation_names)
                    fake_claim = {
                        "lease_epoch": index + 1000,
                        "lease_id": f"fuzz-missing-lease-{index}",
                        "routing_turn_id": f"fuzz-missing-turn-{index}",
                        "owner_kind": "HEARTBEAT",
                        "owner_identity": "controller-1",
                        "intended_transition": "ROUTE_ONE_TRANSITION",
                    }
                    current = harness.state()
                    proposal = {
                        "proposal_id": f"fuzz-proposal-{index}",
                        "roadmap_audit_dispatch_id": f"fuzz-roadmap-dispatch-{index}",
                        "base_roadmap_version": current["roadmap_version"],
                        "operations": [
                            {
                                "operation": "UPDATE_MILESTONE",
                                "milestone_id": "m1",
                                "reason": "Fuzz a schema-valid semantic boundary",
                            }
                        ],
                        "milestones_digest": json_digest(current["milestones"]),
                        "goal_queue_digest": json_digest(current["goal_queue"]),
                        "goal_definition_registry_digest": json_digest(
                            current["goal_definition_registry"]
                        ),
                        "authorization_envelope_digest": json_digest(
                            current["authorization_envelope"]
                        ),
                        "estimate_digest": None,
                        "next_goal_id": "g1",
                        "reason_code": "FUZZ_SEMANTIC_BOUNDARY",
                        "within_authorized_envelope": True,
                    }
                    mutations: dict[str, dict[str, Any]] = {
                        "ACQUIRE_LEASE": {
                            "type": "ACQUIRE_LEASE",
                            "routing_turn_id": f"fuzz-invalid-owner-turn-{index}",
                            "lease_id": f"fuzz-invalid-owner-lease-{index}",
                            "owner_kind": "GOAL_TURN",
                            "owner_identity": "unknown-controller",
                            "observed_at": T1,
                            "expires_at": T4,
                        },
                        "RECORD_STEERING": {
                            "type": "RECORD_STEERING",
                            "steering_id": f"fuzz-steering-{index}",
                            "steering_type": "CORRECTION",
                            "normalized_digest": digest(f"fuzz-steering-{index}"),
                            "identity_algorithm": "message-item-v1",
                            "message_item_id": f"fuzz-message-{index}",
                            "summary": "schema-valid correction with unknown target",
                            "classification_reason": "fuzz semantic boundary",
                            "target_goal_id": f"unknown-goal-{index}",
                        },
                        "REGISTER_DECISION": {
                            "type": "REGISTER_DECISION",
                            "decision_id": f"fuzz-decision-{index}",
                            "decision_context_digest": digest(f"wrong-context-{index}"),
                            "source_state_version": current["state_version"],
                            "valid_through_state_version": current["state_version"] + 1,
                            "options": [
                                {"option_id": "continue", "option_effect": "CONTINUE", "preauthorized_capability": "none"},
                                {"option_id": "wait", "option_effect": "WAIT", "preauthorized_capability": "none"},
                            ],
                            "scope": {"goal_id": "g1"},
                            "exclusions": ["merge", "deploy"],
                        },
                        "RECORD_FAILURE": {
                            "type": "RECORD_FAILURE",
                            "goal_id": f"unknown-goal-{index}",
                            "fingerprint": {
                                "command_digest": digest("pytest"),
                                "exit_code": 1,
                                "normalized_lines_digest": digest("failed"),
                                "failing_test_ids": ["test_fuzz"],
                                "adapter": "generic-v1",
                                "error_class": "UNKNOWN",
                                "error_location": "UNKNOWN",
                                "changed_files": ["src/fuzz.py"],
                                "diff_digest": digest(f"diff-{index}"),
                                "strategy_id": "fuzz-strategy",
                                "hypothesis_digest": digest("fuzz-hypothesis"),
                                "raw_log_digest": digest(f"raw-{index}"),
                                "previously_passing_tests_regressed": [],
                            },
                        },
                        "RECORD_VALIDATION": {
                            "type": "RECORD_VALIDATION",
                            "goal_id": f"unknown-goal-{index}",
                            "dimension": "functional",
                            "status": "PASS",
                            "evidence_digest": digest(f"evidence-{index}"),
                            "artifact_digest": digest(f"artifact-{index}"),
                        },
                        "RECORD_CONTEXT_FRESHNESS": {
                            "type": "RECORD_CONTEXT_FRESHNESS",
                            "checkpoint_id": f"fuzz-freshness-{index}",
                            "checkpoint": "GOAL_DISPATCH",
                            "goal_id": f"unknown-goal-{index}",
                            "observed_identity_delta": context_identity_delta(),
                            "observed_identity_digest": json_digest(
                                context_identity_delta()
                            ),
                            "classification": "FRESH",
                            "classification_source": "DETERMINISTIC_IDENTITY",
                        },
                        "PREPARE_OUTBOX": {
                            "type": "PREPARE_OUTBOX",
                            "lease_claim": fake_claim,
                            "observed_at": T1,
                            "outbox_kind": "AUTOMATION",
                            "outbox_id": f"fuzz-prepare-{index}",
                            "payload_digest": digest(f"fuzz-prepare-{index}"),
                            "target_id": "controller-1",
                            "identity": {
                                "automation_name": "fuzz-heartbeat",
                                "kind": "HEARTBEAT",
                                "target_thread_id": "controller-1",
                                "rrule": "FREQ=MINUTELY;INTERVAL=10",
                                "prompt_digest": digest("fuzz-heartbeat-prompt"),
                                "prompt_normalization": "LF_NORMALIZED_NO_TRAILING_NEWLINE",
                            },
                        },
                        "ACK_OUTBOX": {
                            "type": "ACK_OUTBOX",
                            "lease_claim": fake_claim,
                            "observed_at": T1,
                            "outbox_kind": "AUTOMATION",
                            "outbox_id": f"fuzz-ack-{index}",
                            "payload_digest": digest(f"fuzz-ack-{index}"),
                            "target_id": "controller-1",
                            "ack_evidence_paths": [
                                f".codex-loop/reports/fuzz-ack-{index}.json"
                            ],
                            "result": {},
                        },
                        "RECORD_REVIEW": {
                            "type": "RECORD_REVIEW",
                            "lease_claim": fake_claim,
                            "observed_at": T1,
                            "review_id": f"fuzz-review-{index}",
                            "review_kind": "CODE_REVIEW",
                            "review_dispatch_id": f"fuzz-review-dispatch-{index}",
                            "goal_id": "g1",
                            "worker_dispatch_id": f"fuzz-worker-{index}",
                            "worker_report_digest": digest(f"fuzz-worker-report-{index}"),
                            "reviewer_thread_id": "reviewer-1",
                            "roadmap_version": current["roadmap_version"],
                            "artifact_digest": digest(f"fuzz-artifact-{index}"),
                            "report_digest": digest(f"fuzz-review-report-{index}"),
                            "decision": "REVIEW_PASS",
                            "review_evidence_paths": [
                                f".codex-loop/reports/fuzz-review-{index}.json"
                            ],
                        },
                        "ROADMAP_REVISION": {
                            "type": "ROADMAP_REVISION",
                            "lease_claim": fake_claim,
                            "observed_at": T1,
                            "base_roadmap_version": current["roadmap_version"],
                            "source_goal_id": "g1",
                            "worker_dispatch_id": f"fuzz-worker-{index}",
                            "artifact_digest": digest(f"fuzz-artifact-{index}"),
                            "code_review_id": f"fuzz-code-review-{index}",
                            "roadmap_audit_id": f"fuzz-roadmap-review-{index}",
                            "roadmap_audit_report_digest": digest(
                                f"fuzz-roadmap-report-{index}"
                            ),
                            "roadmap_proposal": proposal,
                            "roadmap_proposal_digest": json_digest(proposal),
                            "milestones": copy.deepcopy(current["milestones"]),
                            "goal_definition_registry": copy.deepcopy(
                                current["goal_definition_registry"]
                            ),
                            "goal_queue": copy.deepcopy(current["goal_queue"]),
                            "authorization_envelope": copy.deepcopy(
                                current["authorization_envelope"]
                            ),
                            "next_goal_id": "g1",
                            "projection_digest": digest(f"fuzz-projection-{index}"),
                            "reason_code": "FUZZ_SEMANTIC_BOUNDARY",
                        },
                        "FINALIZE_LOOP": {
                            "type": "FINALIZE_LOOP",
                            "lease_claim": fake_claim,
                            "observed_at": T1,
                            "base_roadmap_version": current["roadmap_version"],
                            "final_goal_id": "g1",
                            "worker_dispatch_id": f"fuzz-worker-{index}",
                            "artifact_digest": digest(f"fuzz-artifact-{index}"),
                            "code_review_id": f"fuzz-code-review-{index}",
                            "roadmap_audit_id": f"fuzz-roadmap-review-{index}",
                            "final_audit_id": f"fuzz-final-review-{index}",
                            "terminal_status": "LOOP_COMPLETE",
                            "projection_digest": digest(f"fuzz-final-projection-{index}"),
                            "finalization_id": f"fuzz-finalization-{index}",
                            "controller_goal_id": f"fuzz-controller-goal-{index}",
                            "automation_id": f"fuzz-heartbeat-{index}",
                        },
                        "STOP_LOOP": {
                            "type": "STOP_LOOP",
                            "lease_claim": fake_claim,
                            "observed_at": T4,
                            "terminal_status": "LOOP_BLOCKED",
                            "stop_basis": "THREE_OBSERVATIONS",
                            "blocker_code": "FUZZ_BLOCKER",
                            "blocker_fingerprint": digest(f"fuzz-blocker-{index}"),
                            "blocker_observations": [
                                {
                                    "goal_turn_id": f"fuzz-observation-turn-{index}-{offset}",
                                    "observed_at": observed_at,
                                    "blocker_code": "FUZZ_BLOCKER",
                                    "blocker_fingerprint": digest(f"fuzz-blocker-{index}"),
                                    "controller_goal_id": f"fuzz-controller-goal-{index}",
                                    "report_path": f".codex-loop/reports/fuzz-observation-{index}-{offset}.json",
                                    "report_digest": digest(f"fuzz-observation-{index}-{offset}"),
                                }
                                for offset, observed_at in enumerate((T1, T2, T3), start=1)
                            ],
                            "blocker_report_path": f".codex-loop/reports/fuzz-blocker-{index}.json",
                            "blocker_report_digest": digest(f"fuzz-blocker-report-{index}"),
                            "finalization_id": f"fuzz-stop-finalization-{index}",
                            "controller_goal_id": f"fuzz-controller-goal-{index}",
                            "automation_id": f"fuzz-heartbeat-{index}",
                        },
                        "ACK_FINALIZATION": {
                            "type": "ACK_FINALIZATION",
                            "observed_at": T1,
                            "finalization_id": f"fuzz-ack-finalization-{index}",
                            "finalized_state_version": current["state_version"],
                            "controller_goal_id": f"fuzz-controller-goal-{index}",
                            "native_goal_policy": "required",
                            "closeout_capability": digest(
                                f"fuzz-closeout-capability-{index}"
                            ),
                            "controller_goal_status": "COMPLETE",
                            "controller_goal_observation_path": f".codex-loop/reports/fuzz-goal-observation-{index}.json",
                            "controller_goal_observation_digest": digest(f"fuzz-goal-observation-{index}"),
                            "automation_id": f"fuzz-heartbeat-{index}",
                            "automation_status": "PAUSED",
                            "automation_observation_path": f".codex-loop/reports/fuzz-automation-observation-{index}.json",
                            "automation_observation_digest": digest(f"fuzz-automation-observation-{index}"),
                        },
                    }
                    near_valid = harness.make_request(
                        mutations[operation],
                        request_id=f"malformed-request-{index}",
                        event_id=f"malformed-event-{index}",
                        expected=released_version,
                    )
                    response = harness.runtime.apply(near_valid)
                    self.assertFalse(response["ok"])
                    self.assertNotEqual(response["status"], "REQUEST_SCHEMA_INVALID")
                self.assertEqual(runtime_surface_fingerprint(root), baseline)

            fake_claim = {
                "lease_epoch": 99,
                "lease_id": "missing-lease",
                "routing_turn_id": "missing-turn",
                "owner_kind": "HEARTBEAT",
                "owner_identity": "controller-1",
                "intended_transition": "ROUTE_ONE_TRANSITION",
            }
            for index in range(max(25, case_count // 20)):
                response = harness.apply(
                    {
                        "type": "ACK_OUTBOX",
                        "lease_claim": fake_claim,
                        "observed_at": T1,
                        "outbox_kind": "DISPATCH",
                        "outbox_id": f"missing-outbox-{index}",
                        "payload_digest": digest(f"missing-payload-{index}"),
                        "target_id": "worker-1",
                        "ack_evidence_paths": [f"evidence/missing-{index}.json"],
                        "result": {
                            "status": "PASS",
                            "report_digest": digest(f"missing-report-{index}"),
                            "artifact_digest": digest(f"missing-artifact-{index}"),
                        },
                    },
                    expected=released_version,
                )
                self.assertEqual(response["status"], "STALE_OR_MISSING_CONTROLLER_LEASE")
            self.assertEqual(runtime_surface_fingerprint(root), baseline)
            self.assertEqual(
                harness.state()["routing_turn_count"],
                (case_count + batch_size - 1) // batch_size,
            )
