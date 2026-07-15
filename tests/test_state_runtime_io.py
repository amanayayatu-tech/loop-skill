from __future__ import annotations

from state_runtime_support import *  # noqa: F403


class AdaptiveStateRuntimeIOTests(AdaptiveStateRuntimeTestCase):  # noqa: F405
    def test_initialize_canonical_state_and_json_only_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            response, _ = harness.initialize()
            self.assertEqual(response["operation_status"], "LOOP_INITIALIZED")
            state = harness.state()
            self.assertEqual(state["state_version"], 1)
            self.assertEqual(state["native_goal_policy"], "required")
            self.assertEqual(state["external_action_count"], 0)
            for field in (
                "dispatch_outbox",
                "automation_outbox",
                "controller_goal_outbox",
                "thread_creation_outbox",
                "assurance_dispatch_outbox",
                "local_verification_outbox",
            ):
                self.assertEqual(state[field], {})
            text = (root / ".codex-loop" / "LOOP_STATE.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith("STATE_JSON_BEGIN\n{"))
            self.assertTrue(text.endswith("\nSTATE_JSON_END\n"))
            goals_text = (root / ".codex-loop" / "GOALS.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("state_version: 1", goals_text)
            self.assertIn(state["roadmap_projection"]["projection_digest"], goals_text)
            self.assertEqual(
                state["artifact_ledger"][".codex-loop/sources/CONTROLLER_PACK.md"][
                    "digest"
                ],
                state["controller_pack_identity"]["digest"],
            )
            self.assertFalse((root / ".codex-loop" / "progress-dashboard.html").exists())
            self.assertEqual(len(event_lines(root)), 1)

    def test_initialize_reads_root_confined_pack_source_without_transport_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            _, request = harness.initialize()
            shutil.rmtree(root / ".codex-loop")
            content = "# Local Pack\n\n<identity>must stay literal</identity>\n"
            source = root / "controller-pack.md"
            source.write_text(content, encoding="utf-8")
            artifact = {
                "path": ".codex-loop/sources/CONTROLLER_PACK.md",
                "source_path": str(source),
                "digest": digest(content),
                "media_type": "text/markdown",
            }
            request["artifacts"] = [artifact]
            request["mutation"]["controller_pack_digest"] = artifact["digest"]
            response = AdaptiveStateRuntime(root).apply(copy.deepcopy(request))
            self.assertTrue(response["ok"], response)
            archived = root / ".codex-loop/sources/CONTROLLER_PACK.md"
            self.assertEqual(archived.read_bytes(), source.read_bytes())
            state = AdaptiveStateRuntime(root).read_state()
            assert state is not None
            self.assertEqual(
                state["controller_pack_identity"]["digest"], artifact["digest"]
            )

        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside:
            root = Path(temporary)
            harness = Harness(root)
            _, request = harness.initialize()
            shutil.rmtree(root / ".codex-loop")
            source = Path(outside) / "controller-pack.md"
            source.write_text("# Outside Pack\n", encoding="utf-8")
            request["artifacts"] = [{
                "path": ".codex-loop/sources/CONTROLLER_PACK.md",
                "source_path": str(source),
                "digest": digest("# Outside Pack\n"),
                "media_type": "text/markdown",
            }]
            request["mutation"]["controller_pack_digest"] = request["artifacts"][0]["digest"]
            rejected = AdaptiveStateRuntime(root).apply(request)
            self.assertEqual(rejected["status"], "PATH_SCOPE_ESCAPE")
            self.assertFalse((root / ".codex-loop").exists())

    def test_runtime_stages_identity_bound_formal_report_source_for_ack(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness, claim, dispatch_id, payload = self._prepare_sent_worker(root)
            result = {
                "status": "BLOCKED",
                "artifact_digest": digest("zero-effect-after-snapshot"),
            }
            report = json.loads(
                harness.formal_report_content("DISPATCH", dispatch_id, result)
            )
            report["transport_probe"] = "<tag>&中文 &lt;literal"
            report_text = json.dumps(report, ensure_ascii=False, indent=2)
            stage_input = {
                "outbox_id": dispatch_id,
                "result": result,
                "report_text": report_text,
            }
            staged = harness.runtime.stage_formal_report(stage_input)
            self.assertEqual(staged["status"], "FORMAL_REPORT_STAGED")
            cli = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "adaptive_state_runtime.py"),
                    "--root",
                    str(root),
                    "--report-stage",
                ],
                input=json.dumps(stage_input, ensure_ascii=False),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(cli.returncode, 0, cli.stdout)
            self.assertEqual(json.loads(cli.stdout)["source_path"], staged["source_path"])
            source = Path(staged["source_path"])
            self.assertEqual(
                source.parent,
                root.resolve() / ".codex-loop" / "report-staging",
            )
            self.assertEqual(source.stat().st_mode & 0o777, 0o444)
            self.assertEqual(digest(source.read_text(encoding="utf-8")), staged["report_digest"])
            self.assertIn("<tag>&中文 &lt;literal", source.read_text(encoding="utf-8"))

            mutation = {
                "type": "ACK_OUTBOX",
                "lease_claim": claim,
                "observed_at": T1,
                "outbox_kind": "DISPATCH",
                "outbox_id": dispatch_id,
                "payload_digest": payload,
                "target_id": "worker-1",
                "ack_evidence_paths": staged["ack_evidence_paths"],
                "result": staged["result"],
            }
            ack_request = harness.make_request(
                mutation,
                request_id="request-report-stage-ack",
                event_id="event-report-stage-ack",
                artifacts=[staged["artifact"]],
            )
            acked = harness.runtime.apply(copy.deepcopy(ack_request))
            self.assertTrue(acked["ok"], acked)
            self.assertEqual(
                harness.state()["dispatch_outbox"][dispatch_id]["status"],
                "COMPLETED",
            )
            self.assertEqual(
                harness.state()["goal_execution_ledger"]["g1"]["status"],
                "REPAIR_REQUIRED",
            )
            archived = root / staged["path"]
            self.assertEqual(archived.read_bytes(), source.read_bytes())
            self.assertTrue(source.exists())

            replay = harness.runtime.apply(copy.deepcopy(ack_request))
            self.assertEqual(replay["status"], "STATE_WRITE_ALREADY_APPLIED")
            with self.assertRaisesRegex(
                state_runtime_module.RuntimeRejection,
                "FORMAL_REPORT_OUTBOX_NOT_SENT",
            ):
                harness.runtime.stage_formal_report(stage_input)

    def test_worker_pass_requires_replayable_complete_diff_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness, _, dispatch_id, _ = self._prepare_sent_worker(
                root, "dispatch-missing-complete-diff"
            )
            result = {
                "status": "PASS",
                "artifact_digest": digest("missing-complete-diff-artifact"),
            }
            report = json.loads(
                harness.formal_report_content("DISPATCH", dispatch_id, result)
            )
            report.pop("complete_diff_reference")
            before = persisted_snapshot(root)
            with self.assertRaisesRegex(
                state_runtime_module.RuntimeRejection,
                "WORKER_REVIEW_HANDOFF_MISSING",
            ):
                harness.runtime.stage_formal_report(
                    {"outbox_id": dispatch_id, "result": result, "report": report}
                )
            self.assertEqual(persisted_snapshot(root), before)

    def test_worker_review_handoff_rejects_unarchived_canonical_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness, _, dispatch_id, _ = self._prepare_sent_worker(
                root, "dispatch-unarchived-review-evidence"
            )
            result = {
                "status": "PASS",
                "artifact_digest": digest("unarchived-review-evidence-artifact"),
            }
            report = json.loads(
                harness.formal_report_content("DISPATCH", dispatch_id, result)
            )
            report["evidence_artifacts"] = [
                ".codex-loop/reports/not-archived-send.json"
            ]
            before = persisted_snapshot(root)
            with self.assertRaisesRegex(
                state_runtime_module.RuntimeRejection,
                "WORKER_REVIEW_HANDOFF_EVIDENCE_UNARCHIVED",
            ):
                harness.runtime.stage_formal_report(
                    {"outbox_id": dispatch_id, "result": result, "report": report}
                )
            self.assertEqual(persisted_snapshot(root), before)

        for field, invalid_value in (
            ("path", ".codex-loop/reports/another-send.json"),
            ("media_type", "application/octet-stream"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                dispatch_id = f"dispatch-evidence-ledger-{field}"
                harness, _, _, _ = self._prepare_sent_worker(root, dispatch_id)
                result = {
                    "status": "PASS",
                    "artifact_digest": digest(f"evidence-ledger-{field}"),
                }
                report = json.loads(
                    harness.formal_report_content("DISPATCH", dispatch_id, result)
                )
                evidence_path = f".codex-loop/reports/{dispatch_id}-send.json"
                report["evidence_artifacts"] = [evidence_path]
                state = harness.state()
                state["artifact_ledger"][evidence_path][field] = invalid_value
                with self.assertRaisesRegex(
                    state_runtime_module.RuntimeRejection,
                    "WORKER_REVIEW_HANDOFF_EVIDENCE_UNARCHIVED",
                ):
                    harness.runtime._validate_worker_review_handoff(state, report)

    def test_worker_review_handoff_binds_canonical_evidence_claims(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dispatch_id = "dispatch-canonical-evidence-claims"
            harness, _, _, _ = self._prepare_sent_worker(root, dispatch_id)
            result = {
                "status": "PASS",
                "artifact_digest": digest("canonical-evidence-claims-artifact"),
            }
            report = json.loads(
                harness.formal_report_content("DISPATCH", dispatch_id, result)
            )
            evidence_path = f".codex-loop/reports/{dispatch_id}-send.json"
            evidence_payload = (root / evidence_path).read_bytes()
            evidence_record = harness.state()["artifact_ledger"][evidence_path]
            canonical_claim = {
                "path": evidence_path,
                "media_type": evidence_record["media_type"],
                "digest": evidence_record["digest"],
                "sha256": hashlib.sha256(evidence_payload).hexdigest(),
                "size_bytes": len(evidence_payload),
            }
            report["evidence_artifacts"] = [canonical_claim]
            handoff = harness.runtime._validate_worker_review_handoff(
                harness.state(), report
            )
            self.assertEqual(handoff["evidence_refs"], [evidence_path])

            invalid_claims = {
                "media_type": "text/plain",
                "digest": "sha256:" + "0" * 64,
                "sha256": "0" * 64,
                "size_bytes": len(evidence_payload) + 1,
            }
            for field, invalid_value in invalid_claims.items():
                with self.subTest(field=field):
                    invalid_report = copy.deepcopy(report)
                    invalid_report["evidence_artifacts"][0][field] = invalid_value
                    with self.assertRaisesRegex(
                        state_runtime_module.RuntimeRejection,
                        "WORKER_REVIEW_HANDOFF_EVIDENCE_CLAIM_MISMATCH",
                    ):
                        harness.runtime._validate_worker_review_handoff(
                            harness.state(), invalid_report
                        )

    def test_worker_pass_projects_valid_manifest_delta_and_rejects_tamper(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness, claim, dispatch_id, payload = self._prepare_sent_worker(
                root, "dispatch-manifest-delta"
            )
            artifact = root / "artifact" / "result.md"
            artifact.parent.mkdir()
            artifact.write_text("bounded artifact\n", encoding="utf-8")
            file_bytes = artifact.read_bytes()
            file_sha256 = hashlib.sha256(file_bytes).hexdigest()
            after_manifest = (
                f"artifact/result.md\t{len(file_bytes)}\t{file_sha256}\n"
            )
            after_snapshot = hashlib.sha256(
                after_manifest.encode("utf-8")
            ).hexdigest()
            delta_content = (
                f"A\tartifact/result.md\t{len(file_bytes)}\t{file_sha256}\n"
            )
            diff_sha256 = hashlib.sha256(delta_content.encode("utf-8")).hexdigest()
            result = {
                "status": "PASS",
                "artifact_digest": f"sha256:{after_snapshot}",
            }
            report = json.loads(
                harness.formal_report_content("DISPATCH", dispatch_id, result)
            )
            report.update(
                {
                    "before_snapshot_sha256": hashlib.sha256(b"").hexdigest(),
                    "changed_files": ["artifact/result.md"],
                    "diff_sha256": diff_sha256,
                    "complete_diff_reference": {
                        "kind": "MANIFEST_DELTA_V1",
                        "hash_algorithm": "sha256",
                        "media_type": "text/tab-separated-values",
                        "content": delta_content,
                        "sha256": diff_sha256,
                    },
                    "evidence_artifacts": [
                        {
                            "path": "artifact/result.md",
                            "media_type": "text/markdown",
                            "sha256": file_sha256,
                            "size_bytes": len(file_bytes),
                        },
                        ".codex-loop/reports/dispatch-manifest-delta-send.json",
                    ],
                }
            )

            tampered = copy.deepcopy(report)
            tampered["complete_diff_reference"]["content"] = (
                delta_content + "A\tartifact/extra.md\t0\t" + hashlib.sha256(b"").hexdigest() + "\n"
            )
            before = persisted_snapshot(root)
            with self.assertRaisesRegex(
                state_runtime_module.RuntimeRejection,
                "MANIFEST_DELTA_IDENTITY_MISMATCH",
            ):
                harness.runtime.stage_formal_report(
                    {"outbox_id": dispatch_id, "result": result, "report": tampered}
                )
            self.assertEqual(persisted_snapshot(root), before)

            report_content = json.dumps(
                report,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            report_digest = digest(report_content)
            acked = harness.ack_outbox(
                claim,
                "DISPATCH",
                dispatch_id,
                payload,
                target_id="worker-1",
                result={**result, "report_digest": report_digest},
                report_content=report_content,
            )
            self.assertTrue(acked["ok"], acked)
            latest = harness.state()["goal_execution_ledger"]["g1"][
                "latest_worker"
            ]
            self.assertEqual(
                latest["review_handoff"]["artifact_identity"][
                    "complete_diff_reference"
                ]["content"],
                delta_content,
            )
            self.assertEqual(
                latest["review_handoff"]["evidence_refs"],
                [
                    "artifact/result.md",
                    ".codex-loop/reports/dispatch-manifest-delta-send.json",
                ],
            )

    def test_report_stage_cli_handle_is_transport_safe_and_size_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Project & QA"
            root.mkdir()
            harness, _, dispatch_id, _ = self._prepare_sent_worker(
                root, "dispatch-safe-stage-handle"
            )
            result = {
                "status": "BLOCKED",
                "artifact_digest": digest("safe-stage-handle-artifact"),
            }
            report = json.loads(
                harness.formal_report_content("DISPATCH", dispatch_id, result)
            )
            stage_input = {
                "outbox_id": dispatch_id,
                "result": result,
                "report_text": json.dumps(report, ensure_ascii=False, indent=2),
            }
            cli = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "adaptive_state_runtime.py"),
                    "--root",
                    str(root),
                    "--report-stage",
                ],
                input=json.dumps(stage_input, ensure_ascii=False),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(cli.returncode, 0, cli.stdout)
            self.assertNotIn("&", cli.stdout)
            self.assertNotIn("<", cli.stdout)
            self.assertNotIn(">", cli.stdout)
            self.assertIn("Project & QA", json.loads(cli.stdout)["source_path"])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness, _, dispatch_id, _ = self._prepare_sent_worker(
                root, "dispatch-stage-size-cap"
            )
            result = {
                "status": "BLOCKED",
                "artifact_digest": digest("stage-size-cap-artifact"),
            }
            report = json.loads(
                harness.formal_report_content("DISPATCH", dispatch_id, result)
            )
            report["oversized"] = "x" * 4_000_000
            with self.assertRaisesRegex(
                state_runtime_module.RuntimeRejection,
                "ARTIFACT_CONTENT_TOO_LARGE",
            ):
                harness.runtime.stage_formal_report(
                    {
                        "outbox_id": dispatch_id,
                        "result": result,
                        "report": report,
                    }
                )

    def test_report_stage_retry_and_source_gate_have_no_rejected_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness, claim, dispatch_id, payload = self._prepare_sent_worker(
                root, "dispatch-report-retry"
            )
            result = {
                "status": "PASS",
                "artifact_digest": digest("report-retry-artifact"),
            }
            report = json.loads(
                harness.formal_report_content("DISPATCH", dispatch_id, result)
            )
            stage_input = {"outbox_id": dispatch_id, "result": result, "report": report}
            staged = harness.runtime.stage_formal_report(stage_input)
            source = Path(staged["source_path"])
            source.unlink()
            mutation = {
                "type": "ACK_OUTBOX",
                "lease_claim": claim,
                "observed_at": T1,
                "outbox_kind": "DISPATCH",
                "outbox_id": dispatch_id,
                "payload_digest": payload,
                "target_id": "worker-1",
                "ack_evidence_paths": staged["ack_evidence_paths"],
                "result": staged["result"],
            }
            rejected = harness.apply(mutation, artifacts=[staged["artifact"]])
            self.assertEqual(rejected["status"], "ARTIFACT_SOURCE_UNAVAILABLE")
            self.assertEqual(
                harness.state()["dispatch_outbox"][dispatch_id]["status"], "SENT"
            )

            restaged = harness.runtime.stage_formal_report(stage_input)
            self.assertEqual(restaged["source_path"], staged["source_path"])
            copied = Path(restaged["source_path"]).with_name(
                "wrong." + Path(restaged["source_path"]).name
            )
            shutil.copyfile(restaged["source_path"], copied)
            copied.chmod(0o444)
            invalid_artifact = {**restaged["artifact"], "source_path": str(copied)}
            before = persisted_snapshot(root)
            rejected = harness.apply(mutation, artifacts=[invalid_artifact])
            self.assertEqual(rejected["status"], "ARTIFACT_SOURCE_PATH_NOT_ALLOWED")
            self.assertEqual(persisted_snapshot(root), before)

            acked = harness.apply(mutation, artifacts=[restaged["artifact"]])
            self.assertTrue(acked["ok"], acked)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            staging = root / ".codex-loop" / "report-staging"
            missing = staging / ("missing." + "0" * 64 + ".json")
            rejected = harness.apply(
                {
                    "type": "ACK_OUTBOX",
                    "lease_claim": {
                        "lease_epoch": 1,
                        "lease_id": "missing-lease",
                        "routing_turn_id": "missing-turn",
                        "owner_kind": "GOAL_TURN",
                        "owner_identity": "controller-1",
                        "intended_transition": "ROUTE_ONE_TRANSITION",
                    },
                    "observed_at": T1,
                    "outbox_kind": "DISPATCH",
                    "outbox_id": "missing",
                    "payload_digest": digest("missing-payload"),
                    "target_id": "worker-1",
                    "ack_evidence_paths": [".codex-loop/reports/missing-ack.json"],
                    "result": {
                        "status": "BLOCKED",
                        "artifact_digest": digest("missing-artifact"),
                        "report_digest": "sha256:" + "0" * 64,
                    },
                },
                artifacts=[
                    {
                        "path": ".codex-loop/reports/missing-ack.json",
                        "source_path": str(missing),
                        "digest": "sha256:" + "0" * 64,
                        "media_type": "application/json",
                    }
                ],
            )
            self.assertEqual(rejected["status"], "ARTIFACT_SOURCE_UNAVAILABLE")
            self.assertFalse(staging.exists())

    def test_staged_report_ack_journal_recovers_without_private_artifact_metadata(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness, claim, dispatch_id, payload = self._prepare_sent_worker(
                root, "dispatch-report-crash"
            )
            result = {
                "status": "PASS",
                "artifact_digest": digest("report-crash-artifact"),
            }
            report = json.loads(
                harness.formal_report_content("DISPATCH", dispatch_id, result)
            )
            staged = harness.runtime.stage_formal_report(
                {"outbox_id": dispatch_id, "result": result, "report": report}
            )
            request = harness.make_request(
                {
                    "type": "ACK_OUTBOX",
                    "lease_claim": claim,
                    "observed_at": T1,
                    "outbox_kind": "DISPATCH",
                    "outbox_id": dispatch_id,
                    "payload_digest": payload,
                    "target_id": "worker-1",
                    "ack_evidence_paths": staged["ack_evidence_paths"],
                    "result": staged["result"],
                },
                request_id="request-report-stage-crash",
                event_id="event-report-stage-crash",
                artifacts=[staged["artifact"]],
            )
            with self.assertRaises(InjectedCrash):
                AdaptiveStateRuntime(root, crash_at="STATE_REPLACED").apply(
                    copy.deepcopy(request)
                )
            recovered = AdaptiveStateRuntime(root).recover()
            self.assertTrue(recovered["ok"], recovered)
            state = AdaptiveStateRuntime(root).read_state()
            assert state is not None
            self.assertEqual(state["dispatch_outbox"][dispatch_id]["status"], "COMPLETED")
            journal = json.loads(
                (root / ".codex-loop/transactions/request-report-stage-crash.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                set(journal["artifacts"][0]),
                {"path", "content", "digest", "media_type"},
            )
            replay = AdaptiveStateRuntime(root).apply(copy.deepcopy(request))
            self.assertEqual(replay["status"], "STATE_WRITE_ALREADY_APPLIED")

    def test_initialize_json_only_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            definitions = {"g1": goal("g1", "m1")}
            pack = controller_pack_artifact()
            request = {
                "controller_approved": True,
                "state_request_id": "request-cli",
                "event_id": "event-cli",
                "expected_state_version": 0,
                "actor": "CONTROLLER",
                "thread_id": "controller-1",
                "occurred_at": T0,
                "evidence_paths": ["evidence/cli.json"],
                "mutation": {
                    "type": "INITIALIZE",
                    "loop_id": "loop-cli",
                    "project_id": "test-project",
                    "controller_pack_digest": pack["digest"],
                    "controller_thread_id": "controller-1",
                    "controller_bootstrap_prompt_digest": digest("controller-bootstrap"),
                    "state_writer_thread_id": "state-writer-1",
                    "state_writer_bootstrap_prompt_digest": digest("state-writer-bootstrap"),
                    "dashboard_required": False,
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
            process = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "adaptive_state_runtime.py"),
                    "--root",
                    str(root),
                ],
                input=json.dumps(request),
                text=True,
                capture_output=True,
                check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(process.returncode, 0, process.stdout)
            self.assertEqual(process.stderr, "")
            self.assertEqual(json.loads(process.stdout)["status"], "STATE_WRITE_APPLIED")

    def test_dashboard_is_escaped_atomic_and_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            unsafe = milestone("m1", "ACTIVE")
            unsafe["outcome"] = "<script>alert('x')</script>"
            unsafe["decisions"] = ["<b>keep scope</b>"]
            unsafe["required_evidence"] = ["<img src=x onerror=alert(1)>"]
            response, _ = harness.initialize(
                milestones=[unsafe],
                dashboard_required=True,
            )
            self.assertTrue(response["ok"], response)
            dashboard = root / ".codex-loop" / "progress-dashboard.html"
            content = dashboard.read_text(encoding="utf-8")
            self.assertIn("&lt;script&gt;", content)
            self.assertNotIn("<script>", content)
            self.assertIn("&lt;b&gt;keep scope&lt;/b&gt;", content)
            self.assertNotIn("<b>keep scope</b>", content)
            self.assertIn("&lt;img src=x onerror=alert(1)&gt;", content)
            self.assertIn("<h2>Evidence</h2>", content)
            self.assertIn(
                'href="sources/CONTROLLER_PACK.md">.codex-loop/sources/CONTROLLER_PACK.md</a>',
                content,
            )
            self.assertIn("<h2>Required user decisions</h2><ul><li>None</li>", content)
            self.assertIn('name="codex-loop-state-version" content="1"', content)
            dashboard.unlink()
            recovery = AdaptiveStateRuntime(root).recover()
            self.assertTrue(recovery["ok"], recovery)
            self.assertEqual(dashboard.read_text(encoding="utf-8"), content)

    def test_control_plane_identity_mismatch_is_pure_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            harness.initialize()
            claim = harness.acquire()
            before = persisted_snapshot(root)
            malformed = harness.apply(
                {
                    "type": "PREPARE_OUTBOX",
                    "lease_claim": claim,
                    "observed_at": T1,
                    "outbox_kind": "THREAD",
                    "outbox_id": "malformed-thread-create",
                    "payload_digest": digest("malformed-thread-create"),
                    "target_id": "worker-slot",
                    "identity": {"role_kind": "WORKER"},
                }
            )
            self.assertEqual(malformed["status"], "OUTBOX_IDENTITY_SHAPE_INVALID")
            self.assertEqual(persisted_snapshot(root), before)

            wrong_mapping = harness.apply(
                {
                    "type": "PREPARE_OUTBOX",
                    "lease_claim": claim,
                    "observed_at": T1,
                    "outbox_kind": "THREAD",
                    "outbox_id": "wrong-role-mapping",
                    "payload_digest": digest("wrong-role-mapping"),
                    "target_id": "reviewer-slot",
                    "identity": {
                        "project_id": "test-project",
                        "task_kind": "PROJECT_TASK",
                        "bootstrap_role_kind": "code_reviewer",
                        "formal_role_kind": "WORKER",
                        "bootstrap_prompt_digest": digest("reviewer-bootstrap"),
                        "environment_kind": "LOCAL",
                    },
                }
            )
            self.assertEqual(
                wrong_mapping["status"], "THREAD_ROLE_MAPPING_INVALID"
            )
            self.assertEqual(persisted_snapshot(root), before)

            prepared, payload = harness.prepare_outbox(
                claim,
                "AUTOMATION",
                "automation-identity-test",
                {},
                target_id="controller-1",
            )
            self.assertTrue(prepared["ok"], prepared)
            self.assertTrue(
                harness.mark_sent(
                    claim,
                    "AUTOMATION",
                    "automation-identity-test",
                    payload,
                    target_id="controller-1",
                )["ok"]
            )
            identity = harness.state()["automation_outbox"][
                "automation-identity-test"
            ]["identity"]
            before = persisted_snapshot(root)
            rejected = harness.ack_outbox(
                claim,
                "AUTOMATION",
                "automation-identity-test",
                payload,
                target_id="controller-1",
                result={
                    **identity,
                    "prompt_digest": digest("wrong-prompt"),
                    "automation_id": "heartbeat-1",
                    "status": "ACTIVE",
                },
            )
            self.assertEqual(rejected["status"], "AUTOMATION_RESULT_INVALID")
            self.assertEqual(persisted_snapshot(root), before)

    def test_worker_dispatch_requires_exact_bootstrap_role_kind(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            triage_goal = goal("g1", "m1")
            triage_goal["worker_role_kind"] = "triage"
            triage_goal["payload_template_digest"] = goal_definition_digest(
                triage_goal
            )
            harness.initialize(definitions={"g1": triage_goal})
            harness.ensure_controller_goal()
            harness.register_control_result(
                "THREAD",
                "implementation-thread-create",
                "controller-1",
                {"role_kind": "WORKER"},
                {
                    "thread_id": "implementation-1",
                    "role_kind": "WORKER",
                    "worktree_path": ".",
                },
            )
            claim = harness.acquire()
            before = persisted_snapshot(root)
            rejected, _ = harness.prepare_outbox(
                claim,
                "DISPATCH",
                "triage-dispatch-wrong-target",
                {
                    "goal_id": "g1",
                    "goal_definition_digest": triage_goal[
                        "payload_template_digest"
                    ],
                },
                target_id="implementation-1",
            )
            self.assertEqual(rejected["status"], "DISPATCH_GOAL_IDENTITY_INVALID")
            self.assertEqual(persisted_snapshot(root), before)

            released = harness.apply(
                {
                    "type": "RELEASE_LEASE",
                    "lease_claim": claim,
                    "observed_at": T1,
                    "reason_code": "WRONG_WORKER_ROLE_REJECTED",
                }
            )
            self.assertTrue(released["ok"], released)
            harness.register_control_result(
                "THREAD",
                "triage-thread-create",
                "controller-1",
                {
                    "bootstrap_role_kind": "triage",
                    "formal_role_kind": "WORKER",
                },
                {
                    "thread_id": "triage-1",
                    "worktree_path": ".",
                },
            )
            claim = harness.acquire()
            prepared, _ = harness.prepare_outbox(
                claim,
                "DISPATCH",
                "triage-dispatch-correct-target",
                {
                    "goal_id": "g1",
                    "goal_definition_digest": triage_goal[
                        "payload_template_digest"
                    ],
                },
                target_id="triage-1",
            )
            self.assertTrue(prepared["ok"], prepared)

    def test_cas_and_request_event_idempotency_conflicts_are_pure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            response, request = harness.initialize()
            self.assertTrue(response["ok"])
            before = persisted_snapshot(root)

            duplicate = harness.runtime.apply(copy.deepcopy(request))
            self.assertEqual(duplicate["status"], "STATE_WRITE_ALREADY_APPLIED")
            self.assertEqual(persisted_snapshot(root), before)

            request_conflict = copy.deepcopy(request)
            request_conflict["event_id"] = "event-request-conflict"
            self.assertEqual(
                harness.runtime.apply(request_conflict)["status"],
                "STATE_REQUEST_ID_CONFLICT",
            )
            self.assertEqual(persisted_snapshot(root), before)

            event_conflict = copy.deepcopy(request)
            event_conflict["state_request_id"] = "request-event-conflict"
            event_conflict["expected_state_version"] = 1
            self.assertEqual(
                harness.runtime.apply(event_conflict)["status"], "EVENT_ID_CONFLICT"
            )
            self.assertEqual(persisted_snapshot(root), before)

            wrong_cas = harness.make_request(
                {
                    "type": "ACQUIRE_LEASE",
                    "routing_turn_id": "turn-wrong-cas",
                    "lease_id": "lease-wrong-cas",
                    "owner_kind": "GOAL_TURN",
                    "owner_identity": "controller-1",
                    "observed_at": T1,
                    "expires_at": T4,
                },
                expected=0,
            )
            self.assertEqual(
                harness.runtime.apply(wrong_cas)["status"], "STATE_VERSION_CONFLICT"
            )
            self.assertEqual(persisted_snapshot(root), before)
            self.assertEqual(harness.acquire()["lease_epoch"], 1)
