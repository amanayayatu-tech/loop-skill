from __future__ import annotations

from state_runtime_support import *  # noqa: F403


class AdaptiveStateRuntimeRecoveryTests(AdaptiveStateRuntimeTestCase):  # noqa: F405
    def test_crash_injection_every_persistent_stage_recovers_once(self) -> None:
        for stage in PERSISTENT_STAGES:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                definitions = {"g1": goal("g1", "m1")}
                pack = controller_pack_artifact()
                request = {
                    "controller_approved": True,
                    "state_request_id": "crash-request",
                    "event_id": "crash-event",
                    "expected_state_version": 0,
                    "actor": "CONTROLLER",
                    "thread_id": "controller-1",
                    "occurred_at": T0,
                    "evidence_paths": ["evidence/crash.json"],
                    "mutation": {
                        "type": "INITIALIZE",
                        "loop_id": "loop-crash",
                        "project_id": "test-project",
                        "controller_pack_digest": pack["digest"],
                        "controller_thread_id": "controller-1",
                        "controller_bootstrap_prompt_digest": digest("controller-bootstrap"),
                        "state_writer_thread_id": "state-writer-1",
                        "state_writer_bootstrap_prompt_digest": digest("state-writer-bootstrap"),
                        "dashboard_required": True,
                        "milestones": [milestone("m1", "ACTIVE")],
                        "goal_definition_registry": definitions,
                        "goal_queue": [queue_entry("g1", "m1", "READY", 1)],
                        "authorization_envelope": authorization_envelope(
                            definitions, [milestone("m1", "ACTIVE")]
                        ),
                        "local_verification_required_goal_ids": [],
                    },
                    "artifacts": [pack],
                }
                runtime = AdaptiveStateRuntime(root, crash_at=stage)
                with self.assertRaises(InjectedCrash):
                    runtime.apply(request)
                recovered_runtime = AdaptiveStateRuntime(root)
                recovery = recovered_runtime.recover()
                self.assertTrue(recovery["ok"], recovery)
                if recovered_runtime.read_state() is None:
                    response = recovered_runtime.apply(request)
                    self.assertTrue(response["ok"], response)
                state = recovered_runtime.read_state()
                assert state is not None
                self.assertEqual(state["state_version"], 1)
                self.assertEqual(len(event_lines(root)), 1)
                journal = json.loads(
                    (root / ".codex-loop" / "transactions" / "crash-request.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(journal["status"], "APPLIED")
                self.assertFalse(list((root / ".codex-loop").glob(".*.tmp")))
                self.assertFalse(list((root / ".codex-loop" / "transactions").glob(".*.tmp")))

    def test_applied_journal_restores_missing_event_and_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            events_path = root / ".codex-loop" / "LOOP_EVENTS.jsonl"
            goals_path = root / ".codex-loop" / "GOALS.md"
            events_path.unlink()
            goals_path.unlink()
            recovery = AdaptiveStateRuntime(root).recover()
            self.assertTrue(recovery["ok"], recovery)
            self.assertEqual(len(event_lines(root)), 1)
            self.assertIn("state_version: 1", goals_path.read_text(encoding="utf-8"))

    def test_applied_journal_reconciles_rolled_back_or_missing_state_before_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            claim = harness.acquire()
            state_path = root / ".codex-loop" / "LOOP_STATE.md"
            before_prepare = state_path.read_bytes()
            mutation = {
                "type": "PREPARE_OUTBOX",
                "lease_claim": claim,
                "observed_at": T1,
                "outbox_kind": "AUTOMATION",
                "outbox_id": "rollback-outbox",
                "payload_digest": digest("rollback-payload"),
                "target_id": "controller-1",
                "identity": {
                    "automation_name": "test-loop-heartbeat",
                    "kind": "HEARTBEAT",
                    "target_thread_id": "controller-1",
                    "rrule": "FREQ=MINUTELY;INTERVAL=10",
                    "prompt_digest": digest("heartbeat-prompt"),
                    "prompt_normalization": "LF_NORMALIZED_NO_TRAILING_NEWLINE",
                },
            }
            request = harness.make_request(
                mutation,
                request_id="rollback-request",
                event_id="rollback-event",
            )
            applied = harness.runtime.apply(request)
            self.assertTrue(applied["ok"], applied)

            state_path.write_bytes(before_prepare)
            before_replay = persisted_snapshot(root)
            replay = harness.runtime.apply(copy.deepcopy(request))
            self.assertEqual(replay["status"], "RECOVERY_REQUIRED")
            self.assertEqual(persisted_snapshot(root), before_replay)

            recovered = harness.runtime.recover()
            self.assertTrue(recovered["ok"], recovered)
            self.assertIn("rollback-outbox", harness.state()["automation_outbox"])
            self.assertEqual(
                harness.runtime.apply(copy.deepcopy(request))["status"],
                "STATE_WRITE_ALREADY_APPLIED",
            )

            state_path.unlink()
            before_second_initialize = persisted_snapshot(root)
            second_initialize, _ = harness.initialize()
            self.assertEqual(second_initialize["status"], "RECOVERY_REQUIRED")
            self.assertEqual(persisted_snapshot(root), before_second_initialize)
            self.assertTrue(harness.runtime.recover()["ok"])
            self.assertIn("rollback-outbox", harness.state()["automation_outbox"])

    def test_rejected_request_never_commits_an_unrelated_prepared_journal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            acquire_request = harness.make_request(
                {
                    "type": "ACQUIRE_LEASE",
                    "routing_turn_id": "prepared-turn",
                    "lease_id": "prepared-lease",
                    "owner_kind": "HEARTBEAT",
                    "owner_identity": "controller-1",
                    "observed_at": T1,
                    "expires_at": T4,
                },
                request_id="prepared-request",
                event_id="prepared-event",
            )
            with self.assertRaises(InjectedCrash):
                AdaptiveStateRuntime(
                    root,
                    crash_at="PREPARED_JOURNAL_DIR_FSYNCED",
                ).apply(acquire_request)
            journal_path = (
                root / ".codex-loop" / "transactions" / "prepared-request.json"
            )
            self.assertEqual(
                json.loads(journal_path.read_text(encoding="utf-8"))["status"],
                "PREPARED",
            )
            unrelated = harness.make_request(
                {
                    "type": "ACQUIRE_LEASE",
                    "routing_turn_id": "unrelated-turn",
                    "lease_id": "unrelated-lease",
                    "owner_kind": "GOAL_TURN",
                    "owner_identity": "controller-1",
                    "observed_at": T1,
                    "expires_at": T4,
                },
                expected=0,
                request_id="unrelated-request",
                event_id="unrelated-event",
            )
            before = persisted_snapshot(root)
            rejected = harness.runtime.apply(unrelated)
            self.assertEqual(rejected["status"], "RECOVERY_REQUIRED")
            self.assertEqual(persisted_snapshot(root), before)
            self.assertEqual(
                json.loads(journal_path.read_text(encoding="utf-8"))["status"],
                "PREPARED",
            )
            self.assertTrue(harness.runtime.recover()["ok"])
            self.assertEqual(harness.state()["controller_lease"]["claim"]["lease_id"], "prepared-lease")

    def test_symlinked_control_plane_is_rejected_without_writing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "redirected-control"
            target.mkdir()
            (root / ".codex-loop").symlink_to(target, target_is_directory=True)
            harness = Harness(root)
            response, _ = harness.initialize()
            self.assertEqual(response["status"], "SYMLINK_NOT_ALLOWED")
            self.assertEqual(list(target.iterdir()), [])

    def test_owner_read_digest_requires_exact_attached_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            claim = harness.acquire()
            turn_id = harness.state()["controller_lease"]["routing_turn_id"]
            before = persisted_snapshot(root)
            response = harness.apply(
                {
                    "type": "RENEW_LEASE",
                    "lease_claim": claim,
                    "new_lease_id": "lease-unbound-read",
                    "observed_at": T1,
                    "expires_at": T4,
                    "owner_evidence": {
                        "status": "ACTIVE_SAME_OWNER",
                        "thread_id": "controller-1",
                        "routing_turn_id": turn_id,
                        "last_activity_at": T1,
                        "read_digest": "sha256:" + "0" * 64,
                        "read_evidence_path": ".codex-loop/reports/unbound-read.json",
                    },
                }
            )
            self.assertEqual(response["status"], "OWNER_READ_EVIDENCE_UNBOUND")
            self.assertEqual(persisted_snapshot(root), before)

            fields = {
                "status": "ACTIVE_SAME_OWNER",
                "thread_id": "controller-1",
                "routing_turn_id": turn_id,
                "last_activity_at": T1,
            }
            content = json.dumps(fields, sort_keys=True, separators=(",", ":"))
            text_artifact = {
                **read_evidence_artifact("owner-read-text", content),
                "media_type": "text/plain",
            }
            text_evidence = {
                **fields,
                "read_digest": text_artifact["digest"],
                "read_evidence_path": text_artifact["path"],
            }
            text_response = harness.apply(
                {
                    "type": "RENEW_LEASE",
                    "lease_claim": claim,
                    "new_lease_id": "lease-text-read",
                    "observed_at": T1,
                    "expires_at": T4,
                    "owner_evidence": text_evidence,
                },
                artifacts=[text_artifact],
            )
            self.assertEqual(
                text_response["status"], "OWNER_READ_EVIDENCE_UNBOUND"
            )
            self.assertEqual(persisted_snapshot(root), before)

            wrong_content = json.dumps(
                {**fields, "thread_id": "different-controller"},
                sort_keys=True,
                separators=(",", ":"),
            )
            wrong_artifact = read_evidence_artifact(
                "owner-read-wrong-content", wrong_content
            )
            mismatch_response = harness.apply(
                {
                    "type": "RENEW_LEASE",
                    "lease_claim": claim,
                    "new_lease_id": "lease-wrong-read-content",
                    "observed_at": T1,
                    "expires_at": T4,
                    "owner_evidence": {
                        **fields,
                        "read_digest": wrong_artifact["digest"],
                        "read_evidence_path": wrong_artifact["path"],
                    },
                },
                artifacts=[wrong_artifact],
            )
            self.assertEqual(
                mismatch_response["status"], "OWNER_READ_EVIDENCE_MISMATCH"
            )
            self.assertEqual(persisted_snapshot(root), before)

    def test_canonical_state_rejects_multiple_active_outboxes_for_one_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            claim = harness.acquire()
            prepared, _ = harness.prepare_outbox(
                claim,
                "AUTOMATION",
                "single-active-outbox",
                {},
                target_id="controller-1",
            )
            self.assertTrue(prepared["ok"])
            state = harness.state()
            duplicate = copy.deepcopy(
                state["automation_outbox"]["single-active-outbox"]
            )
            duplicate["outbox_id"] = "second-active-outbox"
            duplicate["payload_digest"] = digest("second-active-payload")
            state["automation_outbox"]["second-active-outbox"] = duplicate
            renewal_request = harness.make_request(
                {
                    "type": "RENEW_LEASE",
                    "lease_claim": claim,
                    "new_lease_id": "ambiguous-renewal",
                    "observed_at": T1,
                    "expires_at": T4,
                    "owner_evidence": {
                        "status": "ACTIVE_SAME_OWNER",
                        "thread_id": "controller-1",
                        "routing_turn_id": claim["routing_turn_id"],
                        "last_activity_at": T1,
                        "read_digest": "sha256:" + "0" * 64,
                        "read_evidence_path": ".codex-loop/reports/unused.json",
                    },
                }
            )
            state_path = root / ".codex-loop" / "LOOP_STATE.md"
            state_path.write_bytes(harness.runtime._render_state(state))
            before = persisted_snapshot(root)
            rejected = harness.runtime.apply(renewal_request)
            self.assertEqual(
                rejected["status"], "BUSINESS_HEARTBEAT_ALREADY_REGISTERED"
            )
            self.assertEqual(persisted_snapshot(root), before)

    def test_cross_process_flock_allows_only_one_cas_winner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            requests = []
            for index in (1, 2):
                requests.append(
                    {
                        "controller_approved": True,
                        "state_request_id": f"process-race-request-{index}",
                        "event_id": f"process-race-event-{index}",
                        "expected_state_version": 1,
                        "actor": "CONTROLLER",
                        "thread_id": "controller-1",
                        "occurred_at": T0,
                        "evidence_paths": [f"evidence/process-race-{index}.json"],
                        "controller_pack_digest": controller_pack_artifact()["digest"],
                        "mutation": {
                            "type": "ACQUIRE_LEASE",
                            "routing_turn_id": f"process-race-turn-{index}",
                            "lease_id": f"process-race-lease-{index}",
                            "owner_kind": "HEARTBEAT",
                            "owner_identity": "controller-1",
                            "observed_at": T1,
                            "expires_at": T4,
                            "controller_turn_id": f"process-race-app-turn-{index}",
                        },
                    }
                )
            command = [
                sys.executable,
                str(SCRIPTS / "adaptive_state_runtime.py"),
                "--root",
                str(root),
            ]
            processes = [
                subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                )
                for _ in requests
            ]
            results = []
            for process, request in zip(processes, requests):
                stdout, stderr = process.communicate(json.dumps(request), timeout=30)
                self.assertEqual(stderr, "")
                results.append(json.loads(stdout))
            self.assertEqual(
                sorted(result["status"] for result in results),
                ["STATE_VERSION_CONFLICT", "STATE_WRITE_APPLIED"],
            )

    def test_short_event_write_recovers_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            request = harness.initialize()[1]
            control = root / ".codex-loop"
            if control.exists():
                for path in sorted(control.rglob("*"), reverse=True):
                    if path.is_file() or path.is_symlink():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                control.rmdir()
            original_write = state_runtime_module.os.write
            shortened = False

            def short_event_write(descriptor: int, payload: bytes) -> int:
                nonlocal shortened
                raw = bytes(payload)
                if (
                    not shortened
                    and raw.startswith(b"{")
                    and b'"event_type"' in raw
                    and raw.count(b"\n") == 1
                ):
                    shortened = True
                    partial = raw[: max(1, len(raw) // 2)]
                    return original_write(descriptor, partial)
                return original_write(descriptor, payload)

            with mock.patch.object(state_runtime_module.os, "write", short_event_write):
                response = AdaptiveStateRuntime(root).apply(request)
            self.assertTrue(shortened)
            self.assertEqual(response["status"], "RECOVERY_REQUIRED")
            recovery = AdaptiveStateRuntime(root).recover()
            self.assertTrue(recovery["ok"], recovery)
            self.assertEqual(len(event_lines(root)), 1)

    def test_artifact_bundle_is_immutable_and_crash_recoverable(self) -> None:
        content = "# Trusted Controller Pack\n\nexact bytes\n"
        artifact = {
            "path": ".codex-loop/sources/CONTROLLER_PACK.md",
            "content": content,
            "digest": digest(content),
            "media_type": "text/markdown",
        }
        for stage in ARTIFACT_STAGES:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                harness = Harness(root)
                request = harness.initialize()[1]
                request["artifacts"] = [artifact]
                request["mutation"]["controller_pack_digest"] = artifact["digest"]
                shutil_root = root / ".codex-loop"
                if shutil_root.exists():
                    for path in sorted(shutil_root.rglob("*"), reverse=True):
                        if path.is_file():
                            path.unlink()
                        elif path.is_dir():
                            path.rmdir()
                    shutil_root.rmdir()
                runtime = AdaptiveStateRuntime(root, crash_at=stage)
                with self.assertRaises(InjectedCrash):
                    runtime.apply(request)
                recovered = AdaptiveStateRuntime(root)
                self.assertTrue(recovered.recover()["ok"])
                archived = root / artifact["path"]
                self.assertEqual(archived.read_text(encoding="utf-8"), content)
                state = recovered.read_state()
                assert state is not None
                self.assertEqual(
                    state["artifact_ledger"][artifact["path"]]["digest"],
                    artifact["digest"],
                )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            response, request = harness.initialize()
            self.assertTrue(response["ok"])
            before = persisted_snapshot(root)
            conflicting = copy.deepcopy(request)
            conflicting["state_request_id"] = "artifact-conflict-request"
            conflicting["event_id"] = "artifact-conflict-event"
            conflicting["expected_state_version"] = 1
            conflicting["mutation"] = {
                "type": "ACQUIRE_LEASE",
                "routing_turn_id": "artifact-conflict-turn",
                "lease_id": "artifact-conflict-lease",
                "owner_kind": "GOAL_TURN",
                "owner_identity": "controller-1",
                "observed_at": T1,
                "expires_at": T4,
            }
            conflicting["artifacts"] = [
                {
                    **artifact,
                    "digest": digest("wrong bytes"),
                }
            ]
            rejected = harness.runtime.apply(conflicting)
            self.assertEqual(rejected["status"], "ARTIFACT_DIGEST_MISMATCH")
            self.assertEqual(persisted_snapshot(root), before)

    def test_outbox_pre_send_and_post_send_crash_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            harness.ensure_controller_goal()
            harness.register_control_result(
                "THREAD",
                "worker-thread-crash-create",
                "controller-1",
                {"role_kind": "WORKER"},
                {
                    "thread_id": "worker-1",
                    "role_kind": "WORKER",
                    "worktree_path": ".",
                },
            )
            claim = harness.acquire()
            dispatch_id = "dispatch-crash"
            payload = digest("dispatch-crash-payload")
            prepare = harness.make_request(
                {
                    "type": "PREPARE_OUTBOX",
                    "lease_claim": claim,
                    "observed_at": T1,
                    "outbox_kind": "DISPATCH",
                    "outbox_id": dispatch_id,
                    "payload_digest": payload,
                    "target_id": "worker-1",
                    "identity": {
                        "dispatch_id": dispatch_id,
                        "goal_id": "g1",
                        "goal_definition_digest": harness.definitions["g1"]["payload_template_digest"],
                        "payload_digest": payload,
                        "target_thread_id": "worker-1",
                        "worker_role_kind": "implementation",
                    },
                }
            )
            with self.assertRaises(InjectedCrash):
                AdaptiveStateRuntime(root, crash_at="STATE_REPLACED").apply(prepare)
            AdaptiveStateRuntime(root).recover()
            state = harness.state()
            self.assertEqual(state["dispatch_outbox"][dispatch_id]["status"], "PREPARED")
            self.assertEqual(state["external_action_count"], 0)

            send_content = json.dumps(
                {
                    "observation_kind": "EXTERNAL_SEND",
                    "outbox_kind": "DISPATCH",
                    "outbox_id": dispatch_id,
                    "payload_digest": payload,
                    "target_id": "worker-1",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            send_artifact = read_evidence_artifact(
                "dispatch-crash-send", send_content
            )
            mark = harness.make_request(
                {
                    "type": "MARK_OUTBOX_SENT",
                    "lease_claim": claim,
                    "observed_at": T1,
                    "outbox_kind": "DISPATCH",
                    "outbox_id": dispatch_id,
                    "payload_digest": payload,
                    "target_id": "worker-1",
                    "send_evidence_paths": [send_artifact["path"]],
                },
                artifacts=[send_artifact],
            )
            with self.assertRaises(InjectedCrash):
                AdaptiveStateRuntime(root, crash_at="EVENT_APPENDED_FSYNCED").apply(mark)
            AdaptiveStateRuntime(root).recover()
            self.assertEqual(harness.state()["dispatch_outbox"][dispatch_id]["status"], "SENT")
            self.assertEqual(AdaptiveStateRuntime(root).apply(mark)["status"], "STATE_WRITE_ALREADY_APPLIED")
            ids = [event["event_id"] for event in event_lines(root)]
            self.assertEqual(ids.count(mark["event_id"]), 1)

    def test_lease_renewal_one_route_and_outbox_identity_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            claim = harness.acquire()
            outbox_id = "automation-prepare"
            identity = {
                "automation_id": "heartbeat-1",
                "config_digest": digest("heartbeat-config"),
            }
            prepared, payload = harness.prepare_outbox(
                claim, "AUTOMATION", outbox_id, identity, target_id="controller-1"
            )
            self.assertTrue(prepared["ok"])

            replay = harness.prepare_outbox(
                claim,
                "AUTOMATION",
                outbox_id,
                identity,
                payload_digest=payload,
                target_id="controller-1",
            )[0]
            self.assertEqual(replay["operation_status"], "OUTBOX_ALREADY_PREPARED")
            before = persisted_snapshot(root)
            mismatch = harness.prepare_outbox(
                claim,
                "AUTOMATION",
                outbox_id,
                identity,
                payload_digest=digest("different"),
                target_id="controller-1",
            )[0]
            self.assertEqual(mismatch["status"], "OUTBOX_IDENTITY_CONFLICT")
            self.assertEqual(persisted_snapshot(root), before)

            second_route = harness.prepare_outbox(
                claim,
                "DISPATCH",
                "dispatch-forbidden",
                {
                    "goal_id": "g1",
                    "goal_definition_digest": harness.definitions["g1"]["payload_template_digest"],
                },
                target_id="worker-1",
            )[0]
            self.assertEqual(second_route["status"], "ROUTING_ACTION_ALREADY_USED")

            wrong_evidence = {
                "type": "RENEW_LEASE",
                "lease_claim": claim,
                "new_lease_id": "lease-renewed",
                "observed_at": T1,
                "expires_at": T4,
                "owner_evidence": {
                    "status": "ACTIVE_SAME_OWNER",
                    "thread_id": "wrong-controller",
                    "routing_turn_id": harness.state()["controller_lease"]["routing_turn_id"],
                    "last_activity_at": T1,
                    "read_digest": digest("owner-read"),
                    "read_evidence_path": ".codex-loop/reports/wrong-owner-read.json",
                },
            }
            before = persisted_snapshot(root)
            self.assertEqual(harness.apply(wrong_evidence)["status"], "SAME_OWNER_EVIDENCE_MISMATCH")
            self.assertEqual(persisted_snapshot(root), before)

            turn_id = harness.state()["controller_lease"]["routing_turn_id"]
            owner_evidence, owner_read = read_status_evidence(
                "owner-read",
                {
                    "status": "ACTIVE_SAME_OWNER",
                    "thread_id": "controller-1",
                    "routing_turn_id": turn_id,
                    "last_activity_at": T1,
                },
            )
            renewed = harness.apply(
                {
                    "type": "RENEW_LEASE",
                    "lease_claim": claim,
                    "new_lease_id": "lease-renewed",
                    "observed_at": T1,
                    "expires_at": T4,
                    "owner_evidence": owner_evidence,
                },
                artifacts=[owner_read],
            )
            self.assertEqual(renewed["operation_status"], "SAME_OWNER_LEASE_RENEWED")
            new_claim = renewed["result"]["lease_claim"]
            self.assertEqual(new_claim["lease_epoch"], 2)
            self.assertEqual(
                harness.state()["automation_outbox"][outbox_id]["lease_claim"], new_claim
            )
            self.assertTrue(
                harness.mark_sent(
                    new_claim,
                    "AUTOMATION",
                    outbox_id,
                    payload,
                    target_id="controller-1",
                )["ok"]
            )
            owner_evidence_after_sent, owner_read_after_sent = read_status_evidence(
                "owner-read-after-sent",
                {
                    "status": "ACTIVE_SAME_OWNER",
                    "thread_id": "controller-1",
                    "routing_turn_id": turn_id,
                    "last_activity_at": T1,
                },
            )
            sent_renewal = harness.apply(
                {
                    "type": "RENEW_LEASE",
                    "lease_claim": new_claim,
                    "new_lease_id": "lease-renewed-after-sent",
                    "observed_at": T1,
                    "expires_at": T4,
                    "owner_evidence": owner_evidence_after_sent,
                },
                artifacts=[owner_read_after_sent],
            )
            self.assertEqual(
                sent_renewal["operation_status"], "SAME_OWNER_LEASE_RENEWED"
            )
            sent_claim = sent_renewal["result"]["lease_claim"]
            self.assertEqual(
                harness.state()["automation_outbox"][outbox_id]["lease_claim"],
                sent_claim,
            )
            self.assertTrue(
                harness.ack_outbox(
                    sent_claim,
                    "AUTOMATION",
                    outbox_id,
                    payload,
                    target_id="controller-1",
                )["ok"]
            )
            self.assertIsNone(harness.state()["controller_lease"])

    def test_expired_sent_worker_claim_renews_without_redispatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            harness.ensure_controller_goal()
            harness.register_control_result(
                "THREAD",
                "worker-thread-long-create",
                "controller-1",
                {"role_kind": "WORKER"},
                {
                    "thread_id": "worker-1",
                    "role_kind": "WORKER",
                    "worktree_path": ".",
                },
            )
            claim = harness.acquire(observed_at=T1, expires_at=T2)
            dispatch_id = "dispatch-long-worker"
            identity = {
                "goal_id": "g1",
                "goal_definition_digest": harness.definitions["g1"][
                    "payload_template_digest"
                ],
                "dispatch_lease_claim": copy.deepcopy(claim),
            }
            prepared, payload = harness.prepare_outbox(
                claim,
                "DISPATCH",
                dispatch_id,
                identity,
                target_id="worker-1",
                observed_at=T1,
            )
            self.assertTrue(prepared["ok"])
            self.assertTrue(
                harness.mark_sent(
                    claim,
                    "DISPATCH",
                    dispatch_id,
                    payload,
                    target_id="worker-1",
                    observed_at=T1,
                )["ok"]
            )

            owner_evidence, owner_read = read_status_evidence(
                "long-worker-controller-active",
                {
                    "status": "ACTIVE_SAME_OWNER",
                    "thread_id": "controller-1",
                    "routing_turn_id": claim["routing_turn_id"],
                    "last_activity_at": T3,
                },
            )
            renewed = harness.apply(
                {
                    "type": "RENEW_LEASE",
                    "lease_claim": claim,
                    "new_lease_id": "lease-long-worker-renewed",
                    "observed_at": T3,
                    "expires_at": T4,
                    "owner_evidence": owner_evidence,
                },
                artifacts=[owner_read],
            )
            self.assertEqual(
                renewed["operation_status"], "SAME_OWNER_LEASE_RENEWED"
            )
            renewed_claim = renewed["result"]["lease_claim"]
            record = harness.state()["dispatch_outbox"][dispatch_id]
            self.assertEqual(record["status"], "SENT")
            self.assertEqual(record["payload_digest"], payload)
            self.assertEqual(record["lease_claim"], renewed_claim)
            self.assertEqual(record["identity"]["dispatch_id"], dispatch_id)
            self.assertEqual(record["identity"]["payload_digest"], payload)

            long_result = {
                "status": "PASS",
                "artifact_digest": digest("long-worker-artifact"),
            }
            long_report = harness.formal_report_content(
                "DISPATCH", dispatch_id, long_result
            )
            before_unbound_ack = persisted_snapshot(root)
            unbound_ack = harness.ack_outbox(
                renewed_claim,
                "DISPATCH",
                dispatch_id,
                payload,
                target_id="worker-1",
                observed_at=T3,
                result={
                    **long_result,
                    "report_digest": digest(long_report),
                },
                attach_report=False,
            )
            self.assertEqual(unbound_ack["status"], "REPORT_ARTIFACT_UNBOUND")
            self.assertEqual(persisted_snapshot(root), before_unbound_ack)

            ack = harness.ack_outbox(
                renewed_claim,
                "DISPATCH",
                dispatch_id,
                payload,
                target_id="worker-1",
                observed_at=T3,
                result={
                    **long_result,
                    "report_digest": digest(long_report),
                },
                report_content=long_report,
            )
            self.assertTrue(ack["ok"])
            final_state = harness.state()
            self.assertEqual(
                final_state["dispatch_outbox"][dispatch_id]["status"], "COMPLETED"
            )
            self.assertEqual(
                final_state["goal_execution_ledger"]["g1"]["status"], "WORKER_PASS"
            )
            self.assertIsNone(final_state["controller_lease"])

    def test_expiry_and_evidence_backed_takeover(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            harness.ensure_controller_goal()
            harness.register_control_result(
                "THREAD",
                "worker-thread-takeover-create",
                "controller-1",
                {"role_kind": "WORKER"},
                {
                    "thread_id": "worker-1",
                    "role_kind": "WORKER",
                    "worktree_path": ".",
                },
            )
            claim = harness.acquire(observed_at=T1, expires_at=T2)
            dispatch_id = "dispatch-takeover"
            identity = {
                "goal_id": "g1",
                "goal_definition_digest": harness.definitions["g1"]["payload_template_digest"],
            }
            prepared, payload = harness.prepare_outbox(
                claim,
                "DISPATCH",
                dispatch_id,
                identity,
                target_id="worker-1",
                observed_at=T1,
            )
            self.assertTrue(prepared["ok"])
            before = persisted_snapshot(root)
            expired_send = harness.mark_sent(
                claim,
                "DISPATCH",
                dispatch_id,
                payload,
                target_id="worker-1",
                observed_at=T2,
            )
            self.assertEqual(expired_send["status"], "CONTROLLER_LEASE_EXPIRED")
            self.assertEqual(persisted_snapshot(root), before)

            bad = harness.apply(
                {
                    "type": "TAKEOVER_LEASE",
                    "lease_claim": claim,
                    "routing_turn_id": "takeover-turn-bad",
                    "new_lease_id": "takeover-lease-bad",
                    "new_owner_kind": "HEARTBEAT",
                    "new_owner_identity": "controller-1",
                    "observed_at": T3,
                    "expires_at": T4,
                    "takeover_evidence": {
                        "status": "STALE",
                        "thread_id": "wrong-owner",
                        "last_activity_at": T1,
                        "read_digest": digest("stale-read"),
                        "read_evidence_path": ".codex-loop/reports/wrong-stale-read.json",
                    },
                }
            )
            self.assertEqual(bad["status"], "TAKEOVER_EVIDENCE_OWNER_MISMATCH")
            self.assertEqual(persisted_snapshot(root), before)

            takeover_evidence, stale_read = read_status_evidence(
                "stale-read",
                {
                    "status": "STALE",
                    "thread_id": "controller-1",
                    "last_activity_at": T1,
                },
            )
            takeover = harness.apply(
                {
                    "type": "TAKEOVER_LEASE",
                    "lease_claim": claim,
                    "routing_turn_id": "takeover-turn",
                    "new_lease_id": "takeover-lease",
                    "new_owner_kind": "HEARTBEAT",
                    "new_owner_identity": "controller-1",
                    "observed_at": T3,
                    "expires_at": T4,
                    "takeover_evidence": takeover_evidence,
                },
                artifacts=[stale_read],
            )
            self.assertTrue(takeover["ok"], takeover)
            new_claim = takeover["result"]["lease_claim"]
            self.assertEqual(
                harness.state()["dispatch_outbox"][dispatch_id]["lease_claim"], new_claim
            )
            self.assertTrue(
                harness.mark_sent(
                    new_claim,
                    "DISPATCH",
                    dispatch_id,
                    payload,
                    target_id="worker-1",
                    observed_at=T3,
                )["ok"]
            )
            takeover_result = {
                "status": "PASS",
                "artifact_digest": digest("takeover-artifact"),
            }
            takeover_report = harness.formal_report_content(
                "DISPATCH", dispatch_id, takeover_result
            )
            acked = harness.ack_outbox(
                new_claim,
                "DISPATCH",
                dispatch_id,
                payload,
                target_id="worker-1",
                observed_at=T3,
                result={
                    **takeover_result,
                    "report_digest": digest(takeover_report),
                },
                report_content=takeover_report,
            )
            self.assertTrue(acked["ok"], acked)
