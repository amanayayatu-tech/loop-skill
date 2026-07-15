from __future__ import annotations

from state_runtime_support import *  # noqa: F403


class ControllerPackMigrationReconciliationTests(AdaptiveStateRuntimeTestCase):  # noqa: F405
    @staticmethod
    def _pause(harness: Harness) -> None:
        steering_id = harness.next_id("migration-pause")
        recorded = harness.apply(
            {
                "type": "RECORD_STEERING",
                "steering_id": steering_id,
                "steering_type": "PAUSE",
                "normalized_digest": digest(steering_id),
                "identity_algorithm": "message-item-v1",
                "message_item_id": harness.next_id("migration-pause-message"),
                "summary": "pause for migration",
                "classification_reason": "external automation reconciliation",
            }
        )
        assert recorded["ok"], recorded
        paused = harness.apply(
            {
                "type": "SET_RUN_CONTROL",
                "steering_id": steering_id,
                "requested_status": "PAUSE",
                "reason": "pack migration",
            }
        )
        assert paused["ok"], paused
        assert paused["operation_status"] == "PAUSED_AT_SAFE_POINT", paused

    def _prepared_fixture(
        self,
        root: Path,
    ) -> tuple[Harness, dict[str, Any], dict[str, Any]]:
        harness = Harness(root)
        initialized, _ = harness.initialize()
        self.assertTrue(initialized["ok"], initialized)
        harness.ensure_all_roles()
        harness.worker_pass()
        harness.ensure_heartbeat()
        self._pause(harness)
        before = harness.state()
        preserved = copy.deepcopy(
            {
                key: before[key]
                for key in (
                    "thread_registry",
                    "goal_execution_ledger",
                    "failure_history",
                    "validation_results",
                    "validation_evidence_identity",
                    "local_verification_ledger",
                    "finalization_receipt",
                )
            }
        )
        prepared = harness.prepare_pack_migration(
            content="# Controller Pack\n\nreconciled migration fixture\n",
            target_prompt="resolve controller_pack_identity.path from canonical state",
            migration_id="migration-reconciliation-1",
        )
        self.assertTrue(prepared["response"]["ok"], prepared["response"])
        return harness, prepared, preserved

    @staticmethod
    def _commit_request(
        harness: Harness,
        prepared: dict[str, Any],
    ) -> dict[str, Any]:
        plan = prepared["mutation"]
        observation, observation_artifact = harness.heartbeat_observation_artifact(
            prompt_digest=prepared["target_prompt_identity"]["digest"],
            status="PAUSED",
            stem=f"{plan['migration_id']}-fault-commit",
            observed_at=T2,
        )
        pack_artifact = {
            "path": plan["target_pack_path"],
            "content": prepared["content"],
            "digest": plan["target_pack_digest"],
            "media_type": "text/markdown",
        }
        return harness.make_request(
            {
                "type": "MIGRATE_CONTROLLER_PACK",
                "migration_id": plan["migration_id"],
                "source_pack_digest": plan["source_pack_digest"],
                "target_pack_digest": plan["target_pack_digest"],
                "target_pack_path": plan["target_pack_path"],
                "migration_reason": plan["migration_reason"],
                "heartbeat_observation": observation,
                "automation_observation_path": observation_artifact["path"],
                "automation_observation_digest": observation_artifact["digest"],
            },
            evidence_paths=[pack_artifact["path"], observation_artifact["path"]],
            artifacts=[pack_artifact, observation_artifact],
        )

    def test_migration_commits_same_heartbeat_and_preserves_role_identities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness, prepared, preserved = self._prepared_fixture(Path(temporary))
            migration = harness.commit_pack_migration(prepared)
            self.assertTrue(migration["ok"], migration)
            state = harness.state()
            for key, value in preserved.items():
                self.assertEqual(state[key], value, key)
            self.assertIsNone(state["controller_pack_migration"])
            self.assertEqual(
                state["controller_pack_identity"]["digest"],
                prepared["mutation"]["target_pack_digest"],
            )
            self.assertEqual(
                state["heartbeat_prompt_identity"]["automation_id"],
                "heartbeat-1",
            )
            self.assertEqual(
                state["heartbeat_live_observation"]["status"], "PAUSED"
            )
            self.assertEqual(
                state["controller_pack_migration_history"][-1]["outcome"],
                "COMPLETED",
            )
            self.assertTrue(state["heartbeat_routing_gate_enforced"])

    def test_prepare_derives_prompt_identity_from_canonical_source_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            harness.ensure_all_roles()
            harness.ensure_heartbeat()
            self._pause(harness)
            prompt = "resolve the active Pack from canonical controller_pack_identity.path"
            prepared = harness.prepare_pack_migration(
                content="# Controller Pack\n\ncanonical prompt source fixture\n",
                target_prompt=prompt,
                migration_id="canonical-prompt-source",
                apply_request=False,
            )

            wrong_path_request = copy.deepcopy(prepared["request"])
            prompt_artifact = next(
                artifact
                for artifact in wrong_path_request["artifacts"]
                if artifact["media_type"] == "text/plain"
            )
            prompt_artifact["path"] = (
                ".codex-loop/sources/HEARTBEAT_PROMPT."
                f"{digest(prompt).removeprefix('sha256:')}.txt"
            )
            before = persisted_snapshot(root)
            wrong_path = harness.runtime.apply(wrong_path_request)
            self.assertEqual(
                wrong_path["status"], "PACK_MIGRATION_PROMPT_ARTIFACT_INVALID"
            )
            self.assertEqual(persisted_snapshot(root), before)

            caller_digest_request = copy.deepcopy(prepared["request"])
            caller_digest_request["mutation"]["target_prompt_digest"] = digest(
                "caller-selected identity"
            )
            rejected = harness.runtime.apply(caller_digest_request)
            self.assertEqual(rejected["status"], "REQUEST_SCHEMA_INVALID")
            self.assertEqual(persisted_snapshot(root), before)

            accepted = harness.runtime.apply(copy.deepcopy(prepared["request"]))
            self.assertTrue(accepted["ok"], accepted)
            identity = harness.state()["controller_pack_migration"][
                "target_prompt_identity"
            ]
            self.assertEqual(identity, prepared["target_prompt_identity"])
            self.assertEqual(identity["digest"], digest(prompt))
            self.assertEqual(
                (root / identity["path"]).read_bytes(), prompt.encode("utf-8")
            )

    def test_migration_does_not_rewrite_historical_acked_automation_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            harness.ensure_all_roles()
            harness.ensure_heartbeat()
            self._pause(harness)
            historical_outbox = copy.deepcopy(harness.state()["automation_outbox"])
            prepared = harness.prepare_pack_migration(
                content="# Controller Pack\n\nimmutable outbox fixture\n",
                target_prompt="canonical dynamic Pack heartbeat",
                migration_id="immutable-automation-outbox",
            )
            self.assertTrue(prepared["response"]["ok"], prepared["response"])
            self.assertEqual(harness.state()["automation_outbox"], historical_outbox)
            migrated = harness.commit_pack_migration(prepared)
            self.assertTrue(migrated["ok"], migrated)
            self.assertEqual(harness.state()["automation_outbox"], historical_outbox)

    def test_rollback_restores_prepared_source_heartbeat_routing_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness, first, _ = self._prepared_fixture(root)
            first_migration = harness.commit_pack_migration(first)
            self.assertTrue(first_migration["ok"], first_migration)
            self.assertTrue(harness.state()["heartbeat_routing_gate_enforced"])

            second = harness.prepare_pack_migration(
                content="# Controller Pack\n\nsecond migration rollback fixture\n",
                target_prompt="second canonical dynamic Pack heartbeat",
                migration_id="restore-true-routing-gate",
            )
            self.assertTrue(second["response"]["ok"], second["response"])
            prepared_state = harness.state()
            self.assertTrue(
                prepared_state["controller_pack_migration"][
                    "source_heartbeat_routing_gate_enforced"
                ]
            )
            source_identity = prepared_state["controller_pack_migration"][
                "source_heartbeat_identity"
            ]
            observation, artifact = harness.heartbeat_observation_artifact(
                prompt_digest=source_identity["prompt_digest"],
                status="PAUSED",
                stem="restore-true-routing-gate-rollback",
                observed_at=T2,
            )
            rolled_back = harness.apply(
                {
                    "type": "ROLLBACK_CONTROLLER_PACK_MIGRATION",
                    "migration_id": second["mutation"]["migration_id"],
                    "heartbeat_observation": observation,
                    "automation_observation_path": artifact["path"],
                    "automation_observation_digest": artifact["digest"],
                    "rollback_reason": "verify exact source gate restoration",
                },
                evidence_paths=[artifact["path"]],
                artifacts=[artifact],
            )
            self.assertTrue(rolled_back["ok"], rolled_back)
            state = harness.state()
            self.assertTrue(state["heartbeat_routing_gate_enforced"])
            self.assertTrue(
                state["controller_pack_migration_history"][-1][
                    "source_heartbeat_routing_gate_enforced"
                ]
            )

    def test_prepare_requires_all_five_existing_role_identities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = Harness(Path(temporary))
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            harness.ensure_heartbeat()
            self._pause(harness)
            before = persisted_snapshot(Path(temporary))
            prepared = harness.prepare_pack_migration(
                content="# Controller Pack\n\nmissing roles\n",
                target_prompt="missing-role target prompt",
                migration_id="missing-role-migration",
            )
            self.assertEqual(
                prepared["response"]["status"],
                "PACK_MIGRATION_ROLE_IDENTITY_INCOMPLETE",
            )
            self.assertEqual(persisted_snapshot(Path(temporary)), before)

    def test_migration_readback_mismatch_is_zero_effect_then_can_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness, prepared, _ = self._prepared_fixture(Path(temporary))
            request = self._commit_request(harness, prepared)
            request["mutation"]["heartbeat_observation"]["automation_id"] = (
                "replacement-heartbeat"
            )
            content = json.dumps(
                request["mutation"]["heartbeat_observation"],
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            observation_artifact = request["artifacts"][1]
            observation_artifact["content"] = content
            observation_artifact["digest"] = digest(content)
            request["mutation"]["automation_observation_digest"] = digest(content)
            before = persisted_snapshot(Path(temporary))
            rejected = harness.runtime.apply(request)
            self.assertEqual(
                rejected["status"],
                "PACK_MIGRATION_AUTOMATION_READBACK_MISMATCH",
            )
            self.assertEqual(persisted_snapshot(Path(temporary)), before)

            plan = prepared["mutation"]
            observation, artifact = harness.heartbeat_observation_artifact(
                prompt_digest=harness.state()["heartbeat_prompt_identity"][
                    "prompt_digest"
                ],
                status="PAUSED",
                stem="migration-rollback-readback",
                observed_at=T2,
            )
            rolled_back = harness.apply(
                {
                    "type": "ROLLBACK_CONTROLLER_PACK_MIGRATION",
                    "migration_id": plan["migration_id"],
                    "heartbeat_observation": observation,
                    "automation_observation_path": artifact["path"],
                    "automation_observation_digest": artifact["digest"],
                    "rollback_reason": "external update did not converge",
                },
                evidence_paths=[artifact["path"]],
                artifacts=[artifact],
            )
            self.assertTrue(rolled_back["ok"], rolled_back)
            state = harness.state()
            self.assertIsNone(state["controller_pack_migration"])
            self.assertEqual(
                state["controller_pack_migration_history"][-1]["outcome"],
                "ROLLED_BACK",
            )
            self.assertEqual(state["run_control"]["status"], "PAUSED_AT_SAFE_POINT")

    def test_migration_candidate_and_journal_faults_keep_heartbeat_paused(self) -> None:
        stages = (
            *state_runtime_module.PACK_MIGRATION_CANDIDATE_STAGES[1:],
            *(
                stage
                for stage in state_runtime_module.PERSISTENT_STAGES
                if not stage.startswith("DASHBOARD_")
            ),
        )
        for stage in stages:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                harness, prepared, _ = self._prepared_fixture(root)
                request = self._commit_request(harness, prepared)
                crashing = state_runtime_module.AdaptiveStateRuntime(
                    root,
                    crash_at=stage,
                )
                with self.assertRaises(state_runtime_module.InjectedCrash):
                    crashing.apply(copy.deepcopy(request))
                recovered = state_runtime_module.AdaptiveStateRuntime(root)
                recovery = recovered.recover()
                self.assertTrue(recovery["ok"], recovery)
                replay = recovered.apply(copy.deepcopy(request))
                self.assertTrue(replay["ok"], replay)
                state = recovered.read_state()
                assert state is not None
                self.assertIsNone(state["controller_pack_migration"])
                self.assertEqual(
                    state["heartbeat_live_observation"]["status"], "PAUSED"
                )
                self.assertEqual(
                    state["controller_pack_migration_history"][-1]["outcome"],
                    "COMPLETED",
                )

    def test_prepare_candidate_fault_replays_to_durable_paused_journal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            harness.ensure_all_roles()
            harness.ensure_heartbeat()
            self._pause(harness)
            prepared = harness.prepare_pack_migration(
                content="# Controller Pack\n\nprepare crash fixture\n",
                target_prompt="prepare crash target prompt",
                migration_id="prepare-crash-migration",
                apply_request=False,
            )
            crashing = state_runtime_module.AdaptiveStateRuntime(
                root,
                crash_at="PACK_MIGRATION_PREPARED_PROJECTED",
            )
            with self.assertRaises(state_runtime_module.InjectedCrash):
                crashing.apply(copy.deepcopy(prepared["request"]))
            recovered = state_runtime_module.AdaptiveStateRuntime(root)
            self.assertTrue(recovered.recover()["ok"])
            replay = recovered.apply(copy.deepcopy(prepared["request"]))
            self.assertTrue(replay["ok"], replay)
            state = recovered.read_state()
            assert state is not None
            self.assertEqual(
                state["controller_pack_migration"]["status"], "PREPARED"
            )
            self.assertEqual(state["heartbeat_live_observation"]["status"], "PAUSED")

    def test_resume_requires_paused_readback_then_routing_requires_active_readback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness, prepared, _ = self._prepared_fixture(Path(temporary))
            committed = harness.commit_pack_migration(prepared)
            self.assertTrue(committed["ok"], committed)
            resume_id = "migration-resume"
            recorded = harness.apply(
                {
                    "type": "RECORD_STEERING",
                    "steering_id": resume_id,
                    "steering_type": "RESUME",
                    "normalized_digest": digest(resume_id),
                    "identity_algorithm": "message-item-v1",
                    "message_item_id": "migration-resume-message",
                    "summary": "resume migrated loop",
                    "classification_reason": "same heartbeat remains paused",
                }
            )
            self.assertTrue(recorded["ok"], recorded)
            resumed = harness.apply(
                {
                    "type": "SET_RUN_CONTROL",
                    "steering_id": resume_id,
                    "requested_status": "RESUME",
                    "reason": "migration reconciled",
                }
            )
            self.assertTrue(resumed["ok"], resumed)
            before_route = persisted_snapshot(Path(temporary))
            blocked = harness.apply(
                {
                    "type": "ACQUIRE_LEASE",
                    "routing_turn_id": "migration-blocked-route",
                    "lease_id": "migration-blocked-lease",
                    "owner_kind": "GOAL_TURN",
                    "owner_identity": "controller-1",
                    "observed_at": T2,
                    "expires_at": T4,
                    "controller_turn_id": "migration-blocked-app-turn",
                }
            )
            self.assertEqual(blocked["status"], "HEARTBEAT_ACTIVE_READBACK_REQUIRED")
            self.assertEqual(persisted_snapshot(Path(temporary)), before_route)

            identity = harness.state()["heartbeat_prompt_identity"]
            observation, artifact = harness.heartbeat_observation_artifact(
                prompt_digest=identity["prompt_digest"],
                status="ACTIVE",
                stem="migration-active-readback",
                observed_at=T3,
            )
            observed = harness.apply(
                {
                    "type": "RECORD_HEARTBEAT_OBSERVATION",
                    "heartbeat_observation": observation,
                    "automation_observation_path": artifact["path"],
                    "automation_observation_digest": artifact["digest"],
                },
                evidence_paths=[artifact["path"]],
                artifacts=[artifact],
            )
            self.assertTrue(observed["ok"], observed)
            lease = harness.acquire(observed_at=T3, expires_at=T4)
            self.assertEqual(lease["owner_identity"], "controller-1")

    def test_status_uses_live_readback_not_automation_creation_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = Harness(Path(temporary))
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            harness.ensure_heartbeat()
            status = harness.runtime.status_path.read_text(encoding="utf-8")
            self.assertIn("Next heartbeat: `UNKNOWN_NOT_OBSERVED`", status)
            self._pause(harness)
            observation, artifact = harness.heartbeat_observation_artifact(
                prompt_digest=harness.state()["automation_outbox"][
                    "heartbeat-create-1"
                ]["identity"]["prompt_digest"],
                status="ACTIVE",
                stem="paused-active-safety-readback",
            )
            recorded = harness.apply(
                {
                    "type": "RECORD_HEARTBEAT_OBSERVATION",
                    "heartbeat_observation": observation,
                    "automation_observation_path": artifact["path"],
                    "automation_observation_digest": artifact["digest"],
                },
                evidence_paths=[artifact["path"]],
                artifacts=[artifact],
            )
            self.assertEqual(
                recorded["operation_status"],
                "HEARTBEAT_ACTIVE_WHILE_CANONICAL_PAUSED",
            )
            status = harness.runtime.status_path.read_text(encoding="utf-8")
            self.assertIn("HEARTBEAT_ACTIVE_WHILE_CANONICAL_PAUSED", status)
            self.assertIn("Next action: `PAUSE_SAME_HEARTBEAT`", status)


if __name__ == "__main__":
    unittest.main()
