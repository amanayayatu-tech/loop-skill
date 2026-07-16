from __future__ import annotations

from state_runtime_support import *  # noqa: F403


class AdaptiveStateRuntimeControlTests(AdaptiveStateRuntimeTestCase):  # noqa: F405
    def test_concurrent_writer_cas_race(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            barrier = threading.Barrier(2)

            def writer(index: int) -> dict[str, Any]:
                runtime = AdaptiveStateRuntime(root)
                request = {
                    "controller_approved": True,
                    "state_request_id": f"race-request-{index}",
                    "event_id": f"race-event-{index}",
                    "expected_state_version": 1,
                    "actor": "CONTROLLER",
                    "thread_id": "controller-1",
                    "occurred_at": T0,
                    "evidence_paths": [f"evidence/race-{index}.json"],
                    "controller_pack_digest": controller_pack_artifact()["digest"],
                    "mutation": {
                        "type": "ACQUIRE_LEASE",
                        "routing_turn_id": f"race-turn-{index}",
                        "lease_id": f"race-lease-{index}",
                        "owner_kind": "HEARTBEAT",
                        "owner_identity": "controller-1",
                        "observed_at": T1,
                        "expires_at": T4,
                        "controller_turn_id": f"race-app-turn-{index}",
                    },
                }
                barrier.wait()
                return runtime.apply(
                    request,
                    trusted_turn_metadata=trusted_metadata_for_request(request),
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(writer, (1, 2)))
            self.assertEqual(
                sorted(result["status"] for result in results),
                ["STATE_VERSION_CONFLICT", "STATE_WRITE_APPLIED"],
            )
            state = harness.state()
            self.assertEqual(state["routing_turn_count"], 1)
            self.assertEqual(len(state["routing_turn_ledger"]), 1)

    def test_rejected_virgin_cleanup_cannot_delete_locked_initialization_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cleanup_entered = threading.Event()
            allow_cleanup = threading.Event()
            cleanup_finished = threading.Event()
            initializer_holds_lock = threading.Event()
            allow_initializer = threading.Event()

            class DelayedCleanupRuntime(AdaptiveStateRuntime):
                def _cleanup_virgin_layout(self) -> None:
                    cleanup_entered.set()
                    if not allow_cleanup.wait(timeout=5):
                        raise AssertionError("cleanup barrier timed out")
                    super()._cleanup_virgin_layout()
                    cleanup_finished.set()

            class BlockingInitializerRuntime(AdaptiveStateRuntime):
                def _ensure_layout(self) -> None:
                    super()._ensure_layout()
                    initializer_holds_lock.set()
                    if not allow_initializer.wait(timeout=5):
                        raise AssertionError("initializer barrier timed out")

            builder = Harness(root)
            invalid_request = builder.make_request(
                {
                    "type": "ACQUIRE_LEASE",
                    "routing_turn_id": "virgin-reject-turn",
                    "lease_id": "virgin-reject-lease",
                    "owner_kind": "HEARTBEAT",
                    "owner_identity": "controller-1",
                    "observed_at": T1,
                    "expires_at": T4,
                },
                expected=0,
                request_id="virgin-reject-request",
                event_id="virgin-reject-event",
            )
            definitions = {"g1": goal("g1", "m1")}
            milestones = [milestone("m1", "ACTIVE")]
            pack = controller_pack_artifact()
            initialize_request = builder.make_request(
                {
                    "type": "INITIALIZE",
                    "loop_id": "virgin-race-loop",
                    "project_id": "test-project",
                    "controller_pack_digest": pack["digest"],
                    "controller_thread_id": "controller-1",
                    "controller_bootstrap_prompt_digest": digest("controller-bootstrap"),
                    "state_writer_thread_id": "state-writer-1",
                    "state_writer_bootstrap_prompt_digest": digest("state-writer-bootstrap"),
                    "dashboard_required": False,
                    "milestones": milestones,
                    "goal_definition_registry": definitions,
                    "goal_queue": [queue_entry("g1", "m1", "READY", 1)],
                    "authorization_envelope": authorization_envelope(
                        definitions, milestones
                    ),
                    "local_verification_required_goal_ids": [],
                },
                expected=0,
                request_id="virgin-init-request",
                event_id="virgin-init-event",
                artifacts=[pack],
            )

            with ThreadPoolExecutor(max_workers=2) as executor:
                rejected_future = executor.submit(
                    DelayedCleanupRuntime(root).apply, invalid_request
                )
                self.assertTrue(cleanup_entered.wait(timeout=5))
                initialize_future = executor.submit(
                    BlockingInitializerRuntime(root).apply, initialize_request
                )
                self.assertTrue(initializer_holds_lock.wait(timeout=5))
                allow_cleanup.set()
                self.assertFalse(cleanup_finished.wait(timeout=0.1))
                allow_initializer.set()
                initialized = initialize_future.result(timeout=10)
                rejected = rejected_future.result(timeout=10)

            self.assertEqual(rejected["status"], "STATE_NOT_INITIALIZED")
            self.assertEqual(initialized["operation_status"], "LOOP_INITIALIZED")
            self.assertTrue(cleanup_finished.is_set())
            state = AdaptiveStateRuntime(root).read_state()
            assert state is not None
            self.assertEqual(state["loop_id"], "virgin-race-loop")
            self.assertEqual(state["state_version"], 1)

    def test_goal_and_heartbeat_concurrent_wake_routes_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            Harness(root).initialize()
            barrier = threading.Barrier(2)

            def wake(owner_kind: str) -> dict[str, Any]:
                suffix = owner_kind.lower()
                request = {
                    "controller_approved": True,
                    "state_request_id": f"wake-request-{suffix}",
                    "event_id": f"wake-event-{suffix}",
                    "expected_state_version": 1,
                    "actor": "CONTROLLER",
                    "thread_id": "controller-1",
                    "occurred_at": T0,
                    "evidence_paths": [f"evidence/{suffix}.json"],
                    "controller_pack_digest": controller_pack_artifact()["digest"],
                    "mutation": {
                        "type": "ACQUIRE_LEASE",
                        "routing_turn_id": f"wake-turn-{suffix}",
                        "lease_id": f"wake-lease-{suffix}",
                        "owner_kind": owner_kind,
                        "owner_identity": "controller-1",
                        "observed_at": T1,
                        "expires_at": T4,
                        "controller_turn_id": f"wake-app-turn-{suffix}",
                    },
                }
                barrier.wait()
                return AdaptiveStateRuntime(root).apply(
                    request,
                    trusted_turn_metadata=trusted_metadata_for_request(request),
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(wake, ("GOAL_TURN", "HEARTBEAT")))
            self.assertEqual(sum(result["ok"] for result in results), 1)
            state = AdaptiveStateRuntime(root).read_state()
            assert state is not None
            self.assertEqual(state["routing_turn_count"], 1)
            self.assertIsNotNone(state["controller_lease"])

    def test_release_idle_lease_allows_next_counted_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            claim = harness.acquire(owner_kind="HEARTBEAT")
            response = harness.apply(
                {
                    "type": "RELEASE_LEASE",
                    "lease_claim": claim,
                    "observed_at": T1,
                    "reason_code": "WAITING_ACTIVE",
                }
            )
            self.assertEqual(response["operation_status"], "CONTROLLER_LEASE_RELEASED")
            state = harness.state()
            self.assertIsNone(state["controller_lease"])
            self.assertIn(claim["lease_id"], state["consumed_controller_lease_ids"])
            self.assertEqual(
                state["routing_action_ledger"][claim["lease_id"]][
                    "release_reason_code"
                ],
                "WAITING_ACTIVE",
            )
            next_claim = harness.acquire(owner_kind="GOAL_TURN")
            self.assertNotEqual(next_claim["lease_id"], claim["lease_id"])
            self.assertEqual(harness.state()["routing_turn_count"], 2)

    def test_controller_goal_resume_is_three_evidence_bound_and_zero_effect(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            original_goal = copy.deepcopy(harness.ensure_controller_goal())
            original_outboxes = {
                field: copy.deepcopy(harness.state()[field])
                for field in state_runtime_module.OUTBOX_FIELDS.values()
            }
            original_external_actions = harness.state()["external_action_count"]
            claim = harness.acquire()
            mutation, artifacts = controller_goal_resume_request(harness, claim)
            response = harness.apply(mutation, artifacts=artifacts)
            self.assertTrue(response["ok"], response)
            self.assertEqual(
                response["operation_status"],
                "CONTROLLER_GOAL_RESUME_RECORDED",
            )
            state = harness.state()
            self.assertEqual(state["controller_goal"], original_goal)
            self.assertEqual(state["external_action_count"], original_external_actions)
            self.assertIsNone(state["controller_lease"])
            self.assertEqual(
                state["routing_action_ledger"][claim["lease_id"]]["route_action"],
                {
                    "action_type": "CONTROLLER_GOAL_RESUME",
                    "action_id": mutation["resume_id"],
                },
            )
            for field, value in original_outboxes.items():
                self.assertEqual(state[field], value)
            receipt = state["controller_goal_resume_receipt"]
            self.assertEqual(receipt["native_goal_observed_status"], "BLOCKED")
            self.assertEqual(receipt["goal_id"], original_goal["goal_id"])

            second_claim = harness.acquire()
            second, second_artifacts = controller_goal_resume_request(
                harness,
                second_claim,
                resume_id="controller-goal-resume-2",
            )
            before = persisted_snapshot(root)
            rejected = harness.apply(second, artifacts=second_artifacts)
            self.assertEqual(
                rejected["status"], "CONTROLLER_GOAL_RESUME_ALREADY_RECORDED"
            )
            self.assertEqual(persisted_snapshot(root), before)

    def test_controller_goal_resume_rejects_identity_timeline_and_missing_evidence(
        self,
    ) -> None:
        cases = ("identity", "timeline", "missing")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                harness = Harness(root)
                harness.initialize()
                harness.ensure_controller_goal()
                claim = harness.acquire()
                mutation, artifacts = controller_goal_resume_request(harness, claim)
                if case == "identity":
                    payload = json.loads(artifacts[2]["content"])
                    payload["threadId"] = "another-goal"
                    content = json.dumps(payload, sort_keys=True, separators=(",", ":"))
                    artifacts[2]["content"] = content
                    artifacts[2]["digest"] = digest(content)
                    mutation["post_resume_observation_digest"] = digest(content)
                    expected = "CONTROLLER_GOAL_RESUME_OBSERVATION_INVALID"
                elif case == "timeline":
                    payload = json.loads(artifacts[1]["content"])
                    payload["authorized_at"] = T0
                    content = json.dumps(payload, sort_keys=True, separators=(",", ":"))
                    artifacts[1]["content"] = content
                    artifacts[1]["digest"] = digest(content)
                    mutation["resume_authorization_digest"] = digest(content)
                    expected = "CONTROLLER_GOAL_RESUME_TIMELINE_INVALID"
                else:
                    artifacts.pop()
                    expected = "CONTROLLER_GOAL_RESUME_EVIDENCE_SET_INVALID"
                before = persisted_snapshot(root)
                rejected = harness.apply(mutation, artifacts=artifacts)
                self.assertEqual(rejected["status"], expected)
                self.assertEqual(persisted_snapshot(root), before)

    def test_legacy_v57_shape_defaults_resume_receipt_before_next_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            state = harness.state()
            state.pop("controller_goal_resume_receipt")
            harness.runtime.state_path.write_bytes(harness.runtime._render_state(state))
            legacy = AdaptiveStateRuntime(root).read_state()
            assert legacy is not None
            self.assertNotIn("controller_goal_resume_receipt", legacy)
            harness.acquire()
            self.assertIsNone(harness.state()["controller_goal_resume_receipt"])

    def test_mark_sent_requires_archived_json_send_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            claim = harness.acquire()
            prepared, payload = harness.prepare_outbox(
                claim,
                "GOAL",
                "goal-send-evidence-required",
                {"action": "CREATE"},
                target_id="controller-1",
            )
            self.assertTrue(prepared["ok"], prepared)
            mutation = {
                "type": "MARK_OUTBOX_SENT",
                "lease_claim": claim,
                "observed_at": T1,
                "outbox_kind": "GOAL",
                "outbox_id": "goal-send-evidence-required",
                "payload_digest": payload,
                "target_id": "controller-1",
                "send_evidence_paths": [
                    ".codex-loop/reports/unarchived-goal-send.json"
                ],
            }
            before = persisted_snapshot(root)
            rejected = harness.apply(mutation)
            self.assertEqual(rejected["status"], "OUTBOX_SEND_EVIDENCE_UNARCHIVED")
            self.assertEqual(persisted_snapshot(root), before)

            content = json.dumps(
                {"observation_kind": "EXTERNAL_SEND"},
                sort_keys=True,
                separators=(",", ":"),
            )
            artifact = read_evidence_artifact(
                "duplicate-goal-send-evidence", content
            )
            duplicate = copy.deepcopy(mutation)
            duplicate["send_evidence_paths"] = [
                artifact["path"],
                artifact["path"],
            ]
            duplicate_rejected = harness.apply(duplicate, artifacts=[artifact])
            self.assertEqual(duplicate_rejected["status"], "REQUEST_SCHEMA_INVALID")
            self.assertEqual(persisted_snapshot(root), before)

    def test_mark_sent_evidence_is_strict_and_identity_bound(self) -> None:
        invalid_cases: dict[str, Any] = {
            "invalid-json": "not-json",
            "extra-field": {"extra": True},
            "outbox-kind": {"outbox_kind": "THREAD"},
            "outbox-id": {"outbox_id": "another-outbox"},
            "payload": {"payload_digest": digest("another-payload")},
            "target": {"target_id": "another-target"},
        }
        for case, change in invalid_cases.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                harness = Harness(root)
                harness.initialize()
                claim = harness.acquire()
                outbox_id = f"goal-send-invalid-{case}"
                prepared, payload = harness.prepare_outbox(
                    claim,
                    "GOAL",
                    outbox_id,
                    {"action": "CREATE"},
                    target_id="controller-1",
                )
                self.assertTrue(prepared["ok"], prepared)
                observation: Any = {
                    "observation_kind": "EXTERNAL_SEND",
                    "outbox_kind": "GOAL",
                    "outbox_id": outbox_id,
                    "payload_digest": payload,
                    "target_id": "controller-1",
                }
                if isinstance(change, str):
                    content = change
                else:
                    observation.update(change)
                    content = json.dumps(
                        observation, sort_keys=True, separators=(",", ":")
                    )
                artifact = read_evidence_artifact(
                    f"{outbox_id}-invalid-send", content
                )
                mutation = {
                    "type": "MARK_OUTBOX_SENT",
                    "lease_claim": claim,
                    "observed_at": T1,
                    "outbox_kind": "GOAL",
                    "outbox_id": outbox_id,
                    "payload_digest": payload,
                    "target_id": "controller-1",
                    "send_evidence_paths": [artifact["path"]],
                }
                before = persisted_snapshot(root)
                rejected = harness.apply(mutation, artifacts=[artifact])
                self.assertEqual(rejected["status"], "OUTBOX_SEND_EVIDENCE_INVALID")
                self.assertEqual(persisted_snapshot(root), before)

    def test_mark_sent_accepts_app_message_and_control_tool_shapes(self) -> None:
        supported = {
            "CODEX_MESSAGE_SEND": {
                "target_thread_id": "controller-1",
                "status": "SENT",
            },
            "CODEX_TOOL_RESULT": {
                "target_id": "controller-1",
                "result": {"tool_call_id": "call-1", "ok": True},
            },
        }
        for observation_kind, shape in supported.items():
            with self.subTest(
                observation_kind=observation_kind
            ), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                harness = Harness(root)
                harness.initialize()
                claim = harness.acquire()
                outbox_id = f"goal-send-{observation_kind.lower()}"
                prepared, payload = harness.prepare_outbox(
                    claim,
                    "GOAL",
                    outbox_id,
                    {"action": "CREATE"},
                    target_id="controller-1",
                )
                self.assertTrue(prepared["ok"], prepared)
                observation = {
                    "observation_kind": observation_kind,
                    "outbox_kind": "GOAL",
                    "outbox_id": outbox_id,
                    "payload_digest": payload,
                    **shape,
                }
                content = json.dumps(
                    observation, sort_keys=True, separators=(",", ":")
                )
                artifact = read_evidence_artifact(f"{outbox_id}-send", content)
                sent = harness.apply(
                    {
                        "type": "MARK_OUTBOX_SENT",
                        "lease_claim": claim,
                        "observed_at": T1,
                        "outbox_kind": "GOAL",
                        "outbox_id": outbox_id,
                        "payload_digest": payload,
                        "target_id": "controller-1",
                        "send_evidence_paths": [artifact["path"]],
                    },
                    artifacts=[artifact],
                )
                self.assertEqual(sent["operation_status"], "GOAL_OUTBOX_SENT")

    def test_emulated_goal_create_uses_direct_ack_and_early_update_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize(native_goal_policy="advisory")
            claim = harness.acquire()
            prepared, payload = harness.prepare_outbox(
                claim,
                "GOAL",
                "emulated-goal-create",
                {"action": "CREATE"},
                target_id="controller-1",
            )
            self.assertTrue(prepared["ok"])
            identity = harness.state()["controller_goal_outbox"][
                "emulated-goal-create"
            ]["identity"]
            result = {
                **identity,
                "goal_id": "emulated-goal-1",
                "status": "EMULATED_SINGLE_ACTIVE_MILESTONE",
            }
            mutation = {
                "type": "ACK_OUTBOX",
                "lease_claim": claim,
                "observed_at": T1,
                "outbox_kind": "GOAL",
                "outbox_id": "emulated-goal-create",
                "payload_digest": payload,
                "target_id": "controller-1",
                "ack_evidence_paths": [
                    ".codex-loop/reports/native_goal_unavailable.json"
                ],
                "result": result,
            }
            before = persisted_snapshot(root)
            rejected = harness.apply(mutation)
            self.assertEqual(
                rejected["status"], "EMULATED_GOAL_EVIDENCE_UNBOUND"
            )
            self.assertEqual(persisted_snapshot(root), before)

            created = harness.ack_outbox(
                claim,
                "GOAL",
                "emulated-goal-create",
                payload,
                target_id="controller-1",
                result=result,
            )
            self.assertEqual(created["operation_status"], "GOAL_OUTBOX_ACKED")
            self.assertEqual(
                harness.state()["controller_goal"]["status"],
                "EMULATED_SINGLE_ACTIVE_MILESTONE",
            )

            update_claim = harness.acquire()
            prepared, _ = harness.prepare_outbox(
                update_claim,
                "GOAL",
                "emulated-goal-update",
                {
                    "action": "UPDATE",
                    "goal_id": "emulated-goal-1",
                },
                target_id="controller-1",
            )
            self.assertEqual(
                prepared["status"], "CONTROLLER_GOAL_EARLY_TERMINATION"
            )

    def test_native_goal_policy_gates_tool_send_and_emulated_ack(self) -> None:
        for policy in ("disabled", "advisory", "required"):
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                harness = Harness(root)
                harness.initialize(native_goal_policy=policy)
                claim = harness.acquire()
                outbox_id = f"{policy}-goal-create"
                prepared, payload = harness.prepare_outbox(
                    claim,
                    "GOAL",
                    outbox_id,
                    {"action": "CREATE"},
                    target_id="controller-1",
                )
                self.assertTrue(prepared["ok"], prepared)
                identity = harness.state()["controller_goal_outbox"][outbox_id][
                    "identity"
                ]
                before = persisted_snapshot(root)

                if policy == "required":
                    emulated = harness.ack_outbox(
                        claim,
                        "GOAL",
                        outbox_id,
                        payload,
                        target_id="controller-1",
                        result={
                            **identity,
                            "goal_id": f"{policy}-goal",
                            "status": "EMULATED_SINGLE_ACTIVE_MILESTONE",
                        },
                    )
                    self.assertEqual(
                        emulated["status"], "NATIVE_GOAL_EMULATION_FORBIDDEN"
                    )
                    self.assertEqual(persisted_snapshot(root), before)
                    sent = harness.mark_sent(
                        claim,
                        "GOAL",
                        outbox_id,
                        payload,
                        target_id="controller-1",
                    )
                    self.assertEqual(sent["operation_status"], "GOAL_OUTBOX_SENT")
                else:
                    sent = harness.mark_sent(
                        claim,
                        "GOAL",
                        outbox_id,
                        payload,
                        target_id="controller-1",
                    )
                    self.assertEqual(
                        sent["status"], "NATIVE_GOAL_TOOL_CALL_FORBIDDEN"
                    )
                    self.assertEqual(persisted_snapshot(root), before)
                    emulated = harness.ack_outbox(
                        claim,
                        "GOAL",
                        outbox_id,
                        payload,
                        target_id="controller-1",
                        result={
                            **identity,
                            "goal_id": f"{policy}-goal",
                            "status": "EMULATED_SINGLE_ACTIVE_MILESTONE",
                        },
                    )
                    self.assertEqual(
                        emulated["operation_status"], "GOAL_OUTBOX_ACKED"
                    )
                    self.assertEqual(
                        harness.state()["controller_goal"]["status"],
                        "EMULATED_SINGLE_ACTIVE_MILESTONE",
                    )

    def test_closeout_capability_binds_loop_pack_and_finalized_version(self) -> None:
        common = {
            "loop_id": "loop-a",
            "controller_pack_digest": digest("pack-a"),
            "finalization_id": "finalization-1",
            "finalized_state_version": 17,
            "controller_goal_id": "goal-1",
            "controller_goal_target_status": "COMPLETE",
            "automation_id": "heartbeat-1",
            "native_goal_policy": "required",
        }
        baseline = state_runtime_module._closeout_capability(**common)
        for changed in (
            {**common, "loop_id": "loop-b"},
            {**common, "controller_pack_digest": digest("pack-b")},
            {**common, "finalized_state_version": 18},
        ):
            self.assertNotEqual(
                baseline,
                state_runtime_module._closeout_capability(**changed),
            )

    def test_emulated_goal_update_is_allowed_after_cross_milestone_revision(self) -> None:
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
                native_goal_policy="advisory",
            )
            create_claim = harness.acquire()
            prepared, payload = harness.prepare_outbox(
                create_claim,
                "GOAL",
                "emulated-cross-milestone-create",
                {"action": "CREATE"},
                target_id="controller-1",
            )
            self.assertTrue(prepared["ok"], prepared)
            create_identity = harness.state()["controller_goal_outbox"][
                "emulated-cross-milestone-create"
            ]["identity"]
            created = harness.ack_outbox(
                create_claim,
                "GOAL",
                "emulated-cross-milestone-create",
                payload,
                target_id="controller-1",
                result={
                    **create_identity,
                    "goal_id": "emulated-cross-goal",
                    "status": "EMULATED_SINGLE_ACTIVE_MILESTONE",
                },
            )
            self.assertTrue(created["ok"], created)

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
                    proposal_id="emulated-cross-proposal",
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
                    reason_code="EMULATED_CROSS_MILESTONE",
                ),
            )
            revision_claim = harness.acquire()
            revision = {
                "type": "ROADMAP_REVISION",
                "lease_claim": revision_claim,
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
                "projection_digest": digest("emulated-cross-projection"),
                "reason_code": "EMULATED_CROSS_MILESTONE",
            }
            harness.bind_roadmap_revision(revision, roadmap_audit)
            revision["projection_digest"] = expected_projection_digest(
                harness.state(), revision
            )
            self.assertTrue(harness.apply(revision)["ok"])

            update_claim = harness.acquire()
            current_goal = harness.state()["controller_goal"]
            prepared, update_payload = harness.prepare_outbox(
                update_claim,
                "GOAL",
                "emulated-cross-milestone-complete",
                {
                    "action": "UPDATE",
                    "goal_id": "emulated-cross-goal",
                    "milestone_id": current_goal["milestone_id"],
                    "objective_digest": current_goal["objective_digest"],
                    "marker": current_goal["marker"],
                    "target_status": "COMPLETE",
                },
                target_id="controller-1",
            )
            self.assertTrue(prepared["ok"], prepared)
            update_identity = harness.state()["controller_goal_outbox"][
                "emulated-cross-milestone-complete"
            ]["identity"]
            completed = harness.ack_outbox(
                update_claim,
                "GOAL",
                "emulated-cross-milestone-complete",
                update_payload,
                target_id="controller-1",
                result={**update_identity, "status": "COMPLETE"},
            )
            self.assertTrue(completed["ok"], completed)
            self.assertEqual(harness.state()["controller_goal"]["status"], "COMPLETE")

    def test_new_milestone_goal_create_clears_prior_goal_resume_receipt(self) -> None:
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
            harness.ensure_controller_goal("m1")
            resume_claim = harness.acquire()
            resume, resume_artifacts = controller_goal_resume_request(
                harness, resume_claim
            )
            self.assertTrue(harness.apply(resume, artifacts=resume_artifacts)["ok"])

            worker = harness.worker_pass("g1")
            code_review = harness.review("CODE_REVIEW", "REVIEW_PASS", worker)
            next_milestones = [
                milestone("m1", "COMPLETE"),
                milestone("m2", "ACTIVE", depends_on=["m1"]),
            ]
            next_queue = [
                queue_entry("g2", "m2", "READY", 2, depends_on=["g1"])
            ]
            audit = harness.review(
                "ROADMAP_AUDIT",
                "ROADMAP_AUDIT_PASS",
                worker,
                code_review_id=code_review,
                roadmap_plan=roadmap_plan(
                    proposal_id="resume-cross-milestone-proposal",
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
                    reason_code="RESUME_CROSS_MILESTONE",
                ),
            )
            revision_claim = harness.acquire()
            revision = {
                "type": "ROADMAP_REVISION",
                "lease_claim": revision_claim,
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
                "projection_digest": digest("resume-cross-projection"),
                "reason_code": "RESUME_CROSS_MILESTONE",
            }
            harness.bind_roadmap_revision(revision, audit)
            revision["projection_digest"] = expected_projection_digest(
                harness.state(), revision
            )
            self.assertTrue(harness.apply(revision)["ok"])
            harness.complete_controller_goal()
            self.assertIsNotNone(
                harness.state()["controller_goal_resume_receipt"]
            )
            next_goal = harness.ensure_controller_goal("m2")
            self.assertEqual(next_goal["milestone_id"], "m2")
            self.assertIsNone(harness.state()["controller_goal_resume_receipt"])

    def test_controller_goal_is_singleton_source_bound_and_path_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            marker_claim = harness.acquire()
            before = persisted_snapshot(root)
            invalid_marker, _ = harness.prepare_outbox(
                marker_claim,
                "GOAL",
                "native-goal-create-invalid-marker",
                {
                    "action": "CREATE",
                    "marker": "[CODEX_LOOP_MILESTONE wrong-pack-and-milestone]",
                },
                target_id="controller-1",
            )
            self.assertEqual(
                invalid_marker["status"], "CONTROLLER_GOAL_IDENTITY_INVALID"
            )
            self.assertEqual(persisted_snapshot(root), before)
            self.assertTrue(
                harness.apply(
                    {
                        "type": "RELEASE_LEASE",
                        "lease_claim": marker_claim,
                        "observed_at": T1,
                        "reason_code": "INVALID_GOAL_MARKER_REJECTED",
                    }
                )["ok"]
            )
            harness.register_control_result(
                "GOAL",
                "native-goal-create",
                "controller-1",
                {"action": "CREATE"},
                {"goal_id": "native-goal-1", "status": "ACTIVE"},
            )
            claim = harness.acquire()
            before = persisted_snapshot(root)
            duplicate, _ = harness.prepare_outbox(
                claim,
                "GOAL",
                "native-goal-create-duplicate",
                {"action": "CREATE"},
                target_id="controller-1",
            )
            self.assertEqual(duplicate["status"], "CONTROLLER_GOAL_ALREADY_EXISTS")
            self.assertEqual(persisted_snapshot(root), before)
            unrelated, _ = harness.prepare_outbox(
                claim,
                "GOAL",
                "native-goal-update-unrelated",
                {"action": "UPDATE", "goal_id": "unrelated-goal"},
                target_id="controller-1",
            )
            self.assertEqual(unrelated["status"], "CONTROLLER_GOAL_SOURCE_MISMATCH")
            self.assertEqual(persisted_snapshot(root), before)
            released = harness.apply(
                {
                    "type": "RELEASE_LEASE",
                    "lease_claim": claim,
                    "observed_at": T1,
                    "reason_code": "GOAL_NEGATIVE_TEST_COMPLETE",
                }
            )
            self.assertTrue(released["ok"], released)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            claim = harness.acquire()
            prepared, payload = harness.prepare_outbox(
                claim,
                "GOAL",
                "sent-native-goal-create",
                {"action": "CREATE"},
                target_id="controller-1",
            )
            self.assertTrue(prepared["ok"])
            self.assertTrue(
                harness.mark_sent(
                    claim,
                    "GOAL",
                    "sent-native-goal-create",
                    payload,
                    target_id="controller-1",
                )["ok"]
            )
            identity = harness.state()["controller_goal_outbox"][
                "sent-native-goal-create"
            ]["identity"]
            before = persisted_snapshot(root)
            emulated_after_send = harness.ack_outbox(
                claim,
                "GOAL",
                "sent-native-goal-create",
                payload,
                target_id="controller-1",
                result={
                    **identity,
                    "goal_id": "controller-1",
                    "status": "EMULATED_SINGLE_ACTIVE_MILESTONE",
                },
            )
            self.assertEqual(
                emulated_after_send["status"],
                "CONTROLLER_GOAL_RESULT_INVALID",
            )
            self.assertEqual(persisted_snapshot(root), before)
            native_ack = harness.ack_outbox(
                claim,
                "GOAL",
                "sent-native-goal-create",
                payload,
                target_id="controller-1",
                result={
                    **identity,
                    "goal_id": "controller-1",
                    "status": "ACTIVE",
                },
            )
            self.assertTrue(native_ack["ok"], native_ack)

    def test_read_only_delegation_is_budgeted_archived_and_acknowledged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            definitions = {"g1": goal("g1", "m1")}
            milestones = [milestone("m1", "ACTIVE")]
            authorization = authorization_envelope(definitions, milestones)
            authorization["delegation_policy"] = {
                "mode": "auto_read_only",
                "max_concurrent": 1,
                "max_lifetime_runs": 2,
                "retry_limit_per_exploration": 1,
                "max_depth": 1,
            }
            initialized, _ = harness.initialize(
                definitions=definitions,
                milestones=milestones,
                authorization=authorization,
            )
            self.assertTrue(initialized["ok"])
            claim = harness.acquire()
            identity = {
                "exploration_id": "explore-1",
                "attempt_id": "explore-1-attempt-1",
                "prompt_digest": digest("read-only prompt"),
                "scope_digest": digest("src/**"),
                "source_goal_id": "g1",
                "source_roadmap_version": 1,
                "max_depth": 1,
            }
            prepared, payload = harness.prepare_outbox(
                claim,
                "DELEGATION",
                "delegation-explore-1-attempt-1",
                identity,
                target_id="explore-1",
            )
            self.assertTrue(prepared["ok"])
            sent = harness.mark_sent(
                claim,
                "DELEGATION",
                "delegation-explore-1-attempt-1",
                payload,
                target_id="explore-1",
            )
            self.assertTrue(sent["ok"])
            report_content = '{"finding":"bounded read-only evidence"}'
            report_digest = digest(report_content)
            result = {
                **identity,
                "agent_id": "agent-explore-1",
                "status": "COMPLETED",
                "report_digest": report_digest,
            }
            before = persisted_snapshot(root)
            rejected = harness.ack_outbox(
                claim,
                "DELEGATION",
                "delegation-explore-1-attempt-1",
                payload,
                target_id="explore-1",
                result=result,
                report_content=report_content,
                attach_report=False,
            )
            self.assertEqual(rejected["status"], "REPORT_ARTIFACT_UNBOUND")
            self.assertEqual(persisted_snapshot(root), before)
            acked = harness.ack_outbox(
                claim,
                "DELEGATION",
                "delegation-explore-1-attempt-1",
                payload,
                target_id="explore-1",
                result=result,
                report_content=report_content,
            )
            self.assertEqual(acked["operation_status"], "DELEGATION_OUTBOX_ACKED")
            state = harness.state()
            self.assertEqual(
                state["delegation_ledger"]["delegation-explore-1-attempt-1"][
                    "status"
                ],
                "ACKED",
            )
            self.assertEqual(
                state["subagent_attempt_ledger"]["explore-1"][0]["status"],
                "COMPLETED",
            )
            self.assertIsNone(state["controller_lease"])
            claim = harness.acquire()
            before = persisted_snapshot(root)
            repeated, _ = harness.prepare_outbox(
                claim,
                "DELEGATION",
                "delegation-explore-1-attempt-2",
                {
                    **identity,
                    "attempt_id": "explore-1-attempt-2",
                },
                target_id="explore-1",
            )
            self.assertEqual(repeated["status"], "DELEGATION_ALREADY_COMPLETED")
            self.assertEqual(persisted_snapshot(root), before)
            self.assertTrue(
                harness.apply(
                    {
                        "type": "RELEASE_LEASE",
                        "lease_claim": claim,
                        "observed_at": T1,
                        "reason_code": "DELEGATION_COMPLETE",
                    }
                )["ok"]
            )

    def test_delegation_ack_does_not_block_roadmap_revision(self) -> None:
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
            authorization = authorization_envelope(definitions, milestones)
            authorization["delegation_policy"] = {
                "mode": "auto_read_only",
                "max_concurrent": 1,
                "max_lifetime_runs": 2,
                "retry_limit_per_exploration": 1,
                "max_depth": 1,
            }
            harness.initialize(
                definitions=definitions,
                milestones=milestones,
                queue=[
                    queue_entry("g1", "m1", "READY", 1),
                    queue_entry("g2", "m2", "PLANNED", 1, depends_on=["g1"]),
                ],
                authorization=authorization,
            )
            claim = harness.acquire()
            delegation_identity = {
                "exploration_id": "roadmap-exploration",
                "attempt_id": "roadmap-exploration-1",
                "prompt_digest": digest("roadmap prompt"),
                "scope_digest": digest("src/**"),
                "source_goal_id": "g1",
                "source_roadmap_version": 1,
                "max_depth": 1,
            }
            prepared, payload = harness.prepare_outbox(
                claim,
                "DELEGATION",
                "roadmap-delegation",
                delegation_identity,
                target_id="roadmap-exploration",
            )
            self.assertTrue(prepared["ok"])
            self.assertTrue(
                harness.mark_sent(
                    claim,
                    "DELEGATION",
                    "roadmap-delegation",
                    payload,
                    target_id="roadmap-exploration",
                )["ok"]
            )
            report = '{"finding":"roadmap evidence"}'
            acked = harness.ack_outbox(
                claim,
                "DELEGATION",
                "roadmap-delegation",
                payload,
                target_id="roadmap-exploration",
                result={
                    **delegation_identity,
                    "agent_id": "agent-roadmap",
                    "status": "COMPLETED",
                    "report_digest": digest(report),
                },
                report_content=report,
            )
            self.assertTrue(acked["ok"], acked)

            worker = harness.worker_pass("g1")
            code_review = harness.review("CODE_REVIEW", "REVIEW_PASS", worker)
            next_milestones = [
                milestone("m1", "COMPLETE"),
                milestone("m2", "ACTIVE", depends_on=["m1"]),
            ]
            next_queue = [
                queue_entry("g2", "m2", "READY", 2, depends_on=["g1"])
            ]
            plan = roadmap_plan(
                proposal_id="delegation-roadmap-proposal",
                operations=[
                    {
                        "operation": "UPDATE_MILESTONE",
                        "milestone_id": "m1",
                        "reason": "Complete the evidenced source milestone",
                    },
                    {
                        "operation": "UPDATE_MILESTONE",
                        "milestone_id": "m2",
                        "reason": "Activate the dependency-ready milestone",
                    },
                ],
                milestones=next_milestones,
                goal_definition_registry=definitions,
                goal_queue=next_queue,
                authorization_envelope=authorization,
                next_goal_id="g2",
                reason_code="DELEGATION_EVIDENCE_APPLIED",
            )
            roadmap_audit = harness.review(
                "ROADMAP_AUDIT",
                "ROADMAP_AUDIT_PASS",
                worker,
                code_review_id=code_review,
                roadmap_plan=plan,
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
                "authorization_envelope": authorization,
                "next_goal_id": "g2",
                "projection_digest": digest("placeholder"),
                "reason_code": "DELEGATION_EVIDENCE_APPLIED",
            }
            harness.bind_roadmap_revision(revision, roadmap_audit)
            revision["projection_digest"] = expected_projection_digest(
                harness.state(), revision
            )
            applied = harness.apply(revision)
            self.assertEqual(applied["operation_status"], "ROADMAP_REVISION_APPLIED")

    def test_delegation_retry_and_lifetime_budgets_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            definitions = {"g1": goal("g1", "m1")}
            milestones = [milestone("m1", "ACTIVE")]
            authorization = authorization_envelope(definitions, milestones)
            authorization["delegation_policy"] = {
                "mode": "auto_read_only",
                "max_concurrent": 1,
                "max_lifetime_runs": 2,
                "retry_limit_per_exploration": 1,
                "max_depth": 1,
            }
            harness.initialize(
                definitions=definitions,
                milestones=milestones,
                authorization=authorization,
            )

            def run_attempt(attempt_id: str, status: str) -> None:
                claim = harness.acquire()
                identity = {
                    "exploration_id": "retry-exploration",
                    "attempt_id": attempt_id,
                    "prompt_digest": digest("retry prompt"),
                    "scope_digest": digest("src/**"),
                    "source_goal_id": "g1",
                    "source_roadmap_version": 1,
                    "max_depth": 1,
                }
                outbox_id = f"delegation-{attempt_id}"
                prepared, payload = harness.prepare_outbox(
                    claim,
                    "DELEGATION",
                    outbox_id,
                    identity,
                    target_id="retry-exploration",
                )
                self.assertTrue(prepared["ok"], prepared)
                self.assertTrue(
                    harness.mark_sent(
                        claim,
                        "DELEGATION",
                        outbox_id,
                        payload,
                        target_id="retry-exploration",
                    )["ok"]
                )
                report = json.dumps({"status": status})
                result = harness.ack_outbox(
                    claim,
                    "DELEGATION",
                    outbox_id,
                    payload,
                    target_id="retry-exploration",
                    result={
                        **identity,
                        "agent_id": f"agent-{attempt_id}",
                        "status": status,
                        "report_digest": digest(report),
                    },
                    report_content=report,
                )
                self.assertTrue(result["ok"], result)

            run_attempt("attempt-1", "INTERRUPTED")
            run_attempt("attempt-2", "DROPPED")

            claim = harness.acquire()
            retry_identity = {
                "exploration_id": "retry-exploration",
                "attempt_id": "attempt-3",
                "prompt_digest": digest("retry prompt"),
                "scope_digest": digest("src/**"),
                "source_goal_id": "g1",
                "source_roadmap_version": 1,
                "max_depth": 1,
            }
            before = persisted_snapshot(root)
            exhausted, _ = harness.prepare_outbox(
                claim,
                "DELEGATION",
                "delegation-attempt-3",
                retry_identity,
                target_id="retry-exploration",
            )
            self.assertEqual(
                exhausted["status"], "DELEGATION_RETRY_BUDGET_EXHAUSTED"
            )
            self.assertEqual(persisted_snapshot(root), before)
            other = {
                **retry_identity,
                "exploration_id": "other-exploration",
                "attempt_id": "other-attempt-1",
            }
            lifetime, _ = harness.prepare_outbox(
                claim,
                "DELEGATION",
                "delegation-other-attempt-1",
                other,
                target_id="other-exploration",
            )
            self.assertEqual(lifetime["status"], "DELEGATION_RUN_BUDGET_EXHAUSTED")
            self.assertEqual(persisted_snapshot(root), before)

    def test_delegation_is_denied_when_policy_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            claim = harness.acquire()
            before = persisted_snapshot(root)
            rejected, _ = harness.prepare_outbox(
                claim,
                "DELEGATION",
                "disabled-delegation",
                {
                    "exploration_id": "disabled-explore",
                    "attempt_id": "disabled-attempt",
                    "prompt_digest": digest("prompt"),
                    "scope_digest": digest("scope"),
                    "source_goal_id": "g1",
                    "source_roadmap_version": 1,
                    "max_depth": 1,
                },
                target_id="disabled-explore",
            )
            self.assertEqual(rejected["status"], "DELEGATION_NOT_AUTHORIZED")
            self.assertEqual(persisted_snapshot(root), before)

    def test_release_lease_rejects_reserved_or_active_route_without_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            claim = harness.acquire(owner_kind="HEARTBEAT")
            prepared, _ = harness.prepare_outbox(
                claim,
                "THREAD",
                "thread-create-release-test",
                {"role_kind": "WORKER"},
            )
            self.assertTrue(prepared["ok"])
            before = persisted_snapshot(root)
            response = harness.apply(
                {
                    "type": "RELEASE_LEASE",
                    "lease_claim": claim,
                    "observed_at": T1,
                    "reason_code": "WAITING_ACTIVE",
                }
            )
            self.assertEqual(response["status"], "LEASE_RELEASE_ROUTE_RESERVED")
            self.assertEqual(persisted_snapshot(root), before)

    def test_registered_reviewer_and_worker_report_identity_are_mandatory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            worker = harness.worker_pass()
            claim = harness.acquire()
            identity = {
                "review_kind": "CODE_REVIEW",
                "goal_id": "g1",
                "worker_dispatch_id": worker["dispatch_id"],
                "worker_report_digest": worker["report_digest"],
                "artifact_digest": worker["artifact_digest"],
            }
            before = persisted_snapshot(root)
            rejected, _ = harness.prepare_outbox(
                claim,
                "ASSURANCE",
                "fake-reviewer-dispatch",
                identity,
                target_id="controller-1",
            )
            self.assertEqual(rejected["status"], "REVIEWER_IDENTITY_MISMATCH")
            self.assertEqual(persisted_snapshot(root), before)

            released = harness.apply(
                {
                    "type": "RELEASE_LEASE",
                    "lease_claim": claim,
                    "observed_at": T1,
                    "reason_code": "REVIEWER_NOT_REGISTERED",
                }
            )
            self.assertTrue(released["ok"])
            harness.register_control_result(
                "THREAD",
                "reviewer-identity-test-create",
                "controller-1",
                {"role_kind": "REVIEWER"},
                {
                    "thread_id": "reviewer-1",
                    "role_kind": "REVIEWER",
                    "worktree_path": ".",
                },
            )
            claim = harness.acquire()

            wrong_report = {
                **identity,
                "worker_report_digest": digest("wrong-report"),
            }
            before = persisted_snapshot(root)
            rejected, _ = harness.prepare_outbox(
                claim,
                "ASSURANCE",
                "wrong-worker-report-dispatch",
                wrong_report,
                target_id="reviewer-1",
            )
            self.assertEqual(
                rejected["status"], "WORKER_REPORT_IDENTITY_MISMATCH"
            )
            self.assertEqual(persisted_snapshot(root), before)

    def test_worker_repair_budget_is_enforced_by_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            definitions = {"g1": goal("g1", "m1")}
            milestones = [milestone("m1", "ACTIVE")]
            authorization = authorization_envelope(definitions, milestones)
            authorization["repair_policy"] = {
                "max_repair_attempts_per_goal": 5
            }
            harness.initialize(
                definitions=definitions,
                milestones=milestones,
                authorization=authorization,
            )
            harness.ensure_controller_goal()
            harness.register_control_result(
                "THREAD",
                "repair-worker-create",
                "controller-1",
                {"role_kind": "WORKER"},
                {
                    "thread_id": "worker-1",
                    "role_kind": "WORKER",
                    "worktree_path": ".",
                },
            )

            def run_worker_attempt(index: int, status: str) -> None:
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
                    target_id="worker-1",
                )
                self.assertTrue(prepared["ok"], prepared)
                self.assertTrue(
                    harness.mark_sent(
                        claim,
                        "DISPATCH",
                        outbox_id,
                        payload,
                        target_id="worker-1",
                    )["ok"]
                )
                artifact_digest = digest(f"repair-artifact-{index}")
                report_result = {
                    "status": status,
                    "artifact_digest": artifact_digest,
                }
                report_content = harness.formal_report_content(
                    "DISPATCH", outbox_id, report_result
                )
                acked = harness.ack_outbox(
                    claim,
                    "DISPATCH",
                    outbox_id,
                    payload,
                    target_id="worker-1",
                    result={
                        **report_result,
                        "report_digest": digest(report_content),
                    },
                    report_content=report_content,
                )
                self.assertTrue(acked["ok"], acked)

            run_worker_attempt(1, "FAIL")
            for index in range(2, 7):
                run_worker_attempt(index, "BLOCKED")
            claim = harness.acquire()
            before = persisted_snapshot(root)
            exhausted, _ = harness.prepare_outbox(
                claim,
                "DISPATCH",
                "repair-dispatch-7",
                {
                    "goal_id": "g1",
                    "goal_definition_digest": definitions["g1"][
                        "payload_template_digest"
                    ],
                },
                target_id="worker-1",
            )
            self.assertEqual(exhausted["status"], "REPAIR_BUDGET_EXHAUSTED")
            self.assertEqual(persisted_snapshot(root), before)

    def test_scope_control_caps_and_planned_milestone_dispatch_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            definitions = {"g1": goal("g1", "m1")}
            milestones = [milestone("m1", "ACTIVE")]
            authorization = authorization_envelope(definitions, milestones)
            authorization["delegation_policy"]["max_concurrent"] = 1
            response, _ = harness.initialize(
                definitions=definitions,
                milestones=milestones,
                authorization=authorization,
            )
            self.assertEqual(response["status"], "AUTHORIZATION_BOUNDARY_VIOLATION")
            self.assertEqual(persisted_snapshot(root), {})

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            escaped = goal("g1", "m1")
            escaped["allowed_write_scope"] = ["secrets/**"]
            escaped["payload_template_digest"] = goal_definition_digest(escaped)
            response, _ = harness.initialize(
                definitions={"g1": escaped},
                authorization=authorization_envelope(
                    {"g1": escaped}, [milestone("m1", "ACTIVE")]
                ),
            )
            self.assertEqual(response["status"], "AUTHORIZATION_BOUNDARY_VIOLATION")

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
            authorization = authorization_envelope(definitions, milestones)
            response, _ = harness.initialize(
                definitions=definitions,
                milestones=milestones,
                queue=[
                    queue_entry("g1", "m1", "READY", 1),
                    queue_entry("g2", "m2", "READY", 1, depends_on=["g1"]),
                ],
                authorization=authorization,
            )
            self.assertEqual(
                response["status"], "PLANNED_MILESTONE_GOAL_NOT_PLANNED"
            )

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
            authorization = authorization_envelope(definitions, milestones)
            authorization["control_plane_caps"]["thread_create"] = False
            response, _ = harness.initialize(
                definitions=definitions,
                milestones=milestones,
                queue=[
                    queue_entry("g1", "m1", "READY", 1),
                    queue_entry("g2", "m2", "PLANNED", 1, depends_on=["g1"]),
                ],
                authorization=authorization,
            )
            self.assertTrue(response["ok"], response)
            claim = harness.acquire()
            denied, _ = harness.prepare_outbox(
                claim,
                "THREAD",
                "denied-worker-create",
                {"role_kind": "WORKER"},
                target_id="controller-1",
            )
            self.assertEqual(denied["status"], "AUTHORIZATION_BOUNDARY_VIOLATION")

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
                definitions=definitions,
                milestones=milestones,
                queue=[
                    queue_entry("g1", "m1", "READY", 1),
                    queue_entry("g2", "m2", "PLANNED", 1, depends_on=["g1"]),
                ],
            )
            harness.register_control_result(
                "THREAD",
                "planned-worker-thread-create",
                "controller-1",
                {"role_kind": "WORKER"},
                {
                    "thread_id": "worker-1",
                    "role_kind": "WORKER",
                    "worktree_path": ".",
                },
            )
            claim = harness.acquire()
            before = persisted_snapshot(root)
            rejected, _ = harness.prepare_outbox(
                claim,
                "DISPATCH",
                "planned-goal-dispatch",
                {
                    "goal_id": "g2",
                    "goal_definition_digest": definitions["g2"][
                        "payload_template_digest"
                    ],
                },
                target_id="worker-1",
            )
            self.assertEqual(rejected["status"], "DISPATCH_GOAL_IDENTITY_INVALID")
            self.assertEqual(persisted_snapshot(root), before)

    def test_prepared_outbox_can_be_cancelled_but_sent_outbox_cannot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            harness.ensure_controller_goal()
            harness.register_control_result(
                "THREAD",
                "worker-thread-cancel-create",
                "controller-1",
                {"role_kind": "WORKER"},
                {
                    "thread_id": "worker-1",
                    "role_kind": "WORKER",
                    "worktree_path": ".",
                },
            )
            claim = harness.acquire()
            identity = {
                "goal_id": "g1",
                "goal_definition_digest": harness.definitions["g1"][
                    "payload_template_digest"
                ],
            }
            prepared, payload = harness.prepare_outbox(
                claim,
                "DISPATCH",
                "dispatch-cancel",
                identity,
                target_id="worker-1",
            )
            self.assertTrue(prepared["ok"])
            cancelled = harness.apply(
                {
                    "type": "CANCEL_OUTBOX",
                    "lease_claim": claim,
                    "observed_at": T1,
                    "outbox_kind": "DISPATCH",
                    "outbox_id": "dispatch-cancel",
                    "payload_digest": payload,
                    "target_id": "worker-1",
                    "cancel_reason_code": "TARGET_TASK_UNRECOVERABLE",
                    "recovery_evidence_paths": ["evidence/worker-missing.json"],
                }
            )
            self.assertEqual(cancelled["operation_status"], "DISPATCH_OUTBOX_CANCELLED")
            state = harness.state()
            self.assertEqual(state["dispatch_outbox"]["dispatch-cancel"]["status"], "CANCELLED")
            self.assertEqual(state["goal_execution_ledger"]["g1"]["status"], "READY")
            self.assertIsNone(state["controller_lease"])

            next_claim = harness.acquire()
            prepared, next_payload = harness.prepare_outbox(
                next_claim,
                "DISPATCH",
                "dispatch-sent-no-cancel",
                identity,
                target_id="worker-1",
            )
            self.assertTrue(prepared["ok"])
            self.assertTrue(
                harness.mark_sent(
                    next_claim,
                    "DISPATCH",
                    "dispatch-sent-no-cancel",
                    next_payload,
                    target_id="worker-1",
                )["ok"]
            )
            before = persisted_snapshot(root)
            rejected = harness.apply(
                {
                    "type": "CANCEL_OUTBOX",
                    "lease_claim": next_claim,
                    "observed_at": T1,
                    "outbox_kind": "DISPATCH",
                    "outbox_id": "dispatch-sent-no-cancel",
                    "payload_digest": next_payload,
                    "target_id": "worker-1",
                    "cancel_reason_code": "TOO_LATE",
                    "recovery_evidence_paths": ["evidence/already-sent.json"],
                }
            )
            self.assertEqual(rejected["status"], "OUTBOX_CANCELLATION_NOT_SAFE")
            self.assertEqual(persisted_snapshot(root), before)
