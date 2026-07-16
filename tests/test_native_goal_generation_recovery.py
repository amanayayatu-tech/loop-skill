from __future__ import annotations

import hashlib
import subprocess
import sys

from state_runtime_support import *  # noqa: F403

import loop_architect.native_goal_observer as native_goal_observer  # noqa: E402
from loop_architect.native_goal_observer import (  # noqa: E402
    NativeGoalObservationError,
    observe_native_goal_rollout,
    write_observation,
)


T5 = "2026-01-01T02:00:00Z"


class NativeGoalRolloutFixture:
    def __init__(self, root: Path, thread_id: str = "controller-1") -> None:
        self.root = root
        self.thread_id = thread_id
        self.path = root / f"rollout-{thread_id}.jsonl"
        self.call_counter = 0
        self._append(
            {
                "timestamp": T0,
                "type": "session_meta",
                "payload": {"id": thread_id},
            }
        )

    def _append(self, event: dict[str, Any]) -> None:
        payload = json.dumps(
            event,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(payload + "\n")

    @staticmethod
    def _tool_output(result: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {"type": "input_text", "text": "Script completed"},
            {
                "type": "input_text",
                "text": json.dumps(
                    result,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            },
        ]

    def add_get_goal(
        self,
        turn_id: str,
        goal: dict[str, Any] | None,
        *,
        direct_text: bool = False,
    ) -> str:
        self.call_counter += 1
        call_id = f"call-get-{self.call_counter}"
        self._append(
            {
                "timestamp": T1,
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": turn_id},
            }
        )
        self._append(
            {
                "timestamp": T1,
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": call_id,
                    "status": "completed",
                    "input": (
                        "const result = await tools.get_goal({});\n"
                        + (
                            "text(result);"
                            if direct_text
                            else "text(JSON.stringify(result));"
                        )
                    ),
                },
            }
        )
        self._append(
            {
                "timestamp": T1,
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": call_id,
                    "output": self._tool_output(
                        {
                            "goal": goal,
                            "remainingTokens": None,
                            "completionBudgetReport": None,
                        }
                    ),
                },
            }
        )
        self._append(
            {
                "timestamp": T1,
                "type": "event_msg",
                "payload": {"type": "task_complete", "turn_id": turn_id},
            }
        )
        return call_id

    def add_create_goal(
        self,
        turn_id: str,
        objective: str,
        goal: dict[str, Any],
        *,
        include_output: bool = True,
        ambiguous_source: bool = False,
        direct_text: bool = False,
    ) -> str:
        self.call_counter += 1
        call_id = f"call-create-{self.call_counter}"
        arguments = json.dumps(
            {"objective": objective},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        source = (
            f"const result = await tools.create_goal({arguments});\n"
            + (
                "text(result);"
                if direct_text
                else "text(JSON.stringify(result));"
            )
        )
        if ambiguous_source:
            source = f"const fake = 'tools.create_goal';\n{source}"
        self._append(
            {
                "timestamp": T3,
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": turn_id},
            }
        )
        self._append(
            {
                "timestamp": T3,
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": call_id,
                    "status": "completed",
                    "input": source,
                },
            }
        )
        if include_output:
            self._append(
                {
                    "timestamp": T3,
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call_output",
                        "call_id": call_id,
                        "output": self._tool_output(
                            {
                                "goal": goal,
                                "remainingTokens": None,
                                "completionBudgetReport": None,
                            }
                        ),
                    },
                }
            )
        self._append(
            {
                "timestamp": T3,
                "type": "event_msg",
                "payload": {"type": "task_complete", "turn_id": turn_id},
            }
        )
        return call_id

    def add_raw_tool_call(
        self,
        turn_id: str,
        *,
        source: str,
        result: dict[str, Any] | None = None,
        tool_name: str = "exec",
        start_turn: bool = True,
        complete_turn: bool = True,
    ) -> str:
        """Append one synthetic call without interpreting its JavaScript source."""

        self.call_counter += 1
        call_id = f"call-raw-{self.call_counter}"
        if start_turn:
            self._append(
                {
                    "timestamp": T3,
                    "type": "event_msg",
                    "payload": {"type": "task_started", "turn_id": turn_id},
                }
            )
        call_payload: dict[str, Any] = {
            "type": "custom_tool_call",
            "name": tool_name,
            "call_id": call_id,
            "status": "completed",
        }
        if tool_name == "exec" or source:
            call_payload["input"] = source
        self._append(
            {
                "timestamp": T3,
                "type": "response_item",
                "payload": call_payload,
            }
        )
        if result is not None:
            self._append(
                {
                    "timestamp": T3,
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call_output",
                        "call_id": call_id,
                        "output": self._tool_output(result),
                    },
                }
            )
        if complete_turn:
            self._append(
                {
                    "timestamp": T3,
                    "type": "event_msg",
                    "payload": {"type": "task_complete", "turn_id": turn_id},
                }
            )
        return call_id

    def observation_artifact(
        self,
        *,
        root: Path,
        stem: str,
        mode: str,
        observed_at: str,
        scan_start_offset: int = 0,
        expected_objective_digest: str | None = None,
        expected_objective_bytes_digest: str | None = None,
        control_suffix_start_offset: int | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        observation = observe_native_goal_rollout(
            rollout_path=self.path,
            controller_thread_id=self.thread_id,
            mode=mode,
            scan_start_offset=scan_start_offset,
            expected_objective_digest=expected_objective_digest,
            expected_objective_bytes_digest=expected_objective_bytes_digest,
            control_suffix_start_offset=control_suffix_start_offset,
            observed_at=observed_at,
            trusted_rollout_roots=(self.root.resolve(),),
        )
        relative_path = f".codex-loop/reports/{stem}.json"
        path, observation_digest = write_observation(
            root=root,
            relative_path=relative_path,
            observation=observation,
        )
        content = path.read_text(encoding="utf-8")
        return observation, {
            "path": relative_path,
            "content": content,
            "digest": observation_digest,
            "media_type": "application/json",
        }


class NativeGoalGenerationRecoveryTests(AdaptiveStateRuntimeTestCase):  # noqa: F405
    """Audit the retired transaction logic behind a test-only dispatch bypass."""

    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.object(  # noqa: F405
            state_runtime_module,  # noqa: F405
            "_requests_deferred_native_goal_recovery",
            return_value=False,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _rewrite_as_legacy_with_real_create_receipt(
        harness: Harness,
        *,
        created_at: int = 100,
    ) -> tuple[dict[str, Any], str]:
        state = harness.state()
        goal = copy.deepcopy(state["controller_goal"])
        assert isinstance(goal, dict)
        objective = f"goal-objective:{goal['milestone_id']}\n{goal['marker']}"
        create_observation = {
            "observation_kind": "CODEX_TOOL_RESULT",
            "outbox_id": "legacy-native-goal-create",
            "outbox_kind": "GOAL",
            "payload_digest": goal["objective_digest"],
            "result": {
                "completionBudgetReport": None,
                "goal": {
                    "createdAt": created_at,
                    "objective": objective,
                    "status": "active",
                    "threadId": "controller-1",
                    "timeUsedSeconds": 17,
                    "tokensUsed": 41,
                    "updatedAt": created_at,
                },
                "remainingTokens": None,
            },
            "target_id": "controller-1",
        }
        content = json.dumps(
            create_observation,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        artifact = read_evidence_artifact(
            "legacy-native-goal-create-result", content
        )
        target = harness.root / artifact["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        state["artifact_ledger"][artifact["path"]] = {
            "path": artifact["path"],
            "digest": artifact["digest"],
            "media_type": "application/json",
            "archived_state_version": state["state_version"],
        }
        outbox = state["controller_goal_outbox"][
            "legacy-native-goal-create"
        ]
        outbox["payload_digest"] = goal["objective_digest"]
        outbox["sent_evidence_paths"] = [artifact["path"]]
        state.pop("native_goal_generation_contract_version", None)
        state.pop("native_goal_generation_ledger", None)
        state.pop("native_goal_generation_migration", None)
        state.pop("native_goal_generation_migration_history", None)
        goal = state["controller_goal"]
        assert isinstance(goal, dict)
        goal.pop("current_generation_id", None)
        harness.runtime._refresh_status_projection_target(state)
        harness.runtime.state_path.write_bytes(harness.runtime._render_state(state))
        harness.runtime.goals_path.write_bytes(harness.runtime._render_goals(state))
        harness.runtime._write_status_projection_locked(state)
        dashboard_bytes = harness.runtime._render_dashboard(state)
        if dashboard_bytes is not None:
            harness.runtime.dashboard_path.write_bytes(dashboard_bytes)
        return artifact, objective

    @staticmethod
    def _pause(harness: Harness) -> None:
        steering_id = "native-generation-pause"
        recorded = harness.apply(
            {
                "type": "RECORD_STEERING",
                "steering_id": steering_id,
                "steering_type": "PAUSE",
                "normalized_digest": digest(steering_id),
                "identity_algorithm": "message-item-v1",
                "message_item_id": "native-generation-pause-message",
                "summary": "pause for native Goal generation recovery",
                "classification_reason": "generation migration safe point",
            }
        )
        assert recorded["ok"], recorded
        paused = harness.apply(
            {
                "type": "SET_RUN_CONTROL",
                "steering_id": steering_id,
                "requested_status": "PAUSE",
                "reason": "native Goal generation recovery",
            }
        )
        assert paused["ok"], paused

    @staticmethod
    def _authorize(harness: Harness) -> tuple[str, str]:
        authorization_id = "native-goal-generation-recovery-authorization"
        authorization_digest = digest(
            "explicit generation recovery authorization"
        )
        recorded = harness.apply(
            {
                "type": "RECORD_STEERING",
                "steering_id": authorization_id,
                "steering_type": "CORRECTION",
                "normalized_digest": authorization_digest,
                "identity_algorithm": "message-item-v1",
                "message_item_id": "native-goal-generation-authorization-message",
                "summary": "authorize one exact same-thread native Goal generation",
                "classification_reason": (
                    "NATIVE_GOAL_GENERATION_RECOVERY_AUTHORIZED"
                ),
            }
        )
        assert recorded["ok"], recorded
        resolved = harness.apply(
            {
                "type": "RESOLVE_STEERING",
                "steering_id": authorization_id,
                "resolution_status": "APPLIED",
                "resolution": "one exact native Goal generation",
                "next_action_code": "NONE",
            }
        )
        assert resolved["ok"], resolved
        return authorization_id, authorization_digest

    def _fixture(self, root: Path) -> dict[str, Any]:
        harness = Harness(root)
        initialized, _ = harness.initialize()
        self.assertTrue(initialized["ok"], initialized)
        harness.ensure_all_roles()
        harness.ensure_heartbeat()
        harness.register_control_result(
            "GOAL",
            "legacy-native-goal-create",
            "controller-1",
            {"action": "CREATE", "milestone_id": "m1"},
            {"goal_id": "controller-1", "status": "ACTIVE"},
        )
        create_artifact, objective = (
            self._rewrite_as_legacy_with_real_create_receipt(harness)
        )
        legacy_goal_outbox = copy.deepcopy(
            harness.state()["controller_goal_outbox"][
                "legacy-native-goal-create"
            ]
        )
        legacy_heartbeat_outbox = copy.deepcopy(
            harness.state()["automation_outbox"]["heartbeat-create-1"]
        )
        self._pause(harness)
        migration = harness.prepare_pack_migration(
            content="# v3.2.7 native Goal recovery test pack",
            target_prompt="Resolve canonical Pack path and remain paused.",
            migration_id="pack-to-v327",
        )
        self.assertTrue(migration["response"]["ok"], migration["response"])
        migrated = harness.commit_pack_migration(migration)
        self.assertTrue(migrated["ok"], migrated)
        baseline_state = harness.state()
        baseline_id = baseline_state["controller_goal"]["current_generation_id"]
        self.assertTrue(baseline_id.startswith("ngen-"))
        authorization_id, authorization_digest = self._authorize(harness)
        rollout = NativeGoalRolloutFixture(root)
        rollout.add_get_goal("null-turn-one", None)
        _, null_one = rollout.observation_artifact(
            root=root,
            stem="native-goal-null-one",
            mode="GET_GOAL",
            observed_at=T1,
        )
        rollout.add_get_goal("null-turn-two", None)
        _, null_two = rollout.observation_artifact(
            root=root,
            stem="native-goal-null-two",
            mode="GET_GOAL",
            observed_at=T2,
        )
        return {
            "harness": harness,
            "rollout": rollout,
            "objective": objective,
            "create_artifact": create_artifact,
            "legacy_goal_outbox": legacy_goal_outbox,
            "legacy_heartbeat_outbox": legacy_heartbeat_outbox,
            "null_artifacts": [null_one, null_two],
            "authorization_id": authorization_id,
            "authorization_digest": authorization_digest,
            "migration_id": "native-goal-generation-migration-1",
        }

    def _heartbeat_artifact(
        self,
        harness: Harness,
        *,
        stem: str,
        observed_at: str,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        identity = harness.state()["heartbeat_prompt_identity"]
        return harness.heartbeat_observation_artifact(
            prompt_digest=identity["prompt_digest"],
            status="PAUSED",
            stem=stem,
            observed_at=observed_at,
        )

    def _acquire_recovery(
        self,
        fixture: dict[str, Any],
        *,
        scope: str,
        turn_id: str,
        observed_at: str,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        request, heartbeat_artifact = self._recovery_acquire_request(
            fixture,
            scope=scope,
            turn_id=turn_id,
            observed_at=observed_at,
        )
        response = fixture["harness"].runtime.apply(
            request,
            trusted_turn_metadata=trusted_metadata_for_request(
                request, turn_id=turn_id
            ),
        )
        return response, heartbeat_artifact

    def _recovery_acquire_request(
        self,
        fixture: dict[str, Any],
        *,
        scope: str,
        turn_id: str,
        observed_at: str,
        state_writer_thread_id: str = "state-writer-1",
        authorization_steering_id: str | None = None,
        authorization_digest: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        harness: Harness = fixture["harness"]
        heartbeat, heartbeat_artifact = self._heartbeat_artifact(
            harness,
            stem=f"{scope.lower()}-{turn_id}",
            observed_at=observed_at,
        )
        lease_expiry = {
            T3: "2026-01-01T00:04:00Z",
            T4: "2026-01-01T01:04:00Z",
            "2026-01-01T01:02:00Z": "2026-01-01T01:04:00Z",
        }[observed_at]
        mutation = {
            "type": "ACQUIRE_LEASE",
            "routing_turn_id": f"route-{turn_id}",
            "lease_id": f"lease-{turn_id}",
            "owner_kind": "GOAL_TURN",
            "owner_identity": "controller-1",
            "observed_at": observed_at,
            "expires_at": lease_expiry,
            "controller_turn_id": turn_id,
            "recovery_scope": scope,
            "migration_id": fixture["migration_id"],
            "state_writer_thread_id": state_writer_thread_id,
            "controller_pack_digest": harness.state()[
                "controller_pack_identity"
            ]["digest"],
            "authorization_steering_id": (
                authorization_steering_id or fixture["authorization_id"]
            ),
            "authorization_digest": (
                authorization_digest or fixture["authorization_digest"]
            ),
            "heartbeat_observation": heartbeat,
            "automation_observation_path": heartbeat_artifact["path"],
            "automation_observation_digest": heartbeat_artifact["digest"],
        }
        request = harness.make_request(
            mutation,
            evidence_paths=[heartbeat_artifact["path"]],
            artifacts=[heartbeat_artifact],
        )
        request["occurred_at"] = observed_at
        return request, heartbeat_artifact

    @staticmethod
    def _state_writer_apply(
        harness: Harness,
        mutation: dict[str, Any],
        *,
        occurred_at: str,
        artifacts: list[dict[str, str]],
        expected: int | None = None,
        runtime: AdaptiveStateRuntime | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        request = harness.make_request(
            mutation,
            expected=expected,
            evidence_paths=[artifact["path"] for artifact in artifacts],
            artifacts=artifacts,
        )
        request["thread_id"] = "state-writer-1"
        request["actor"] = "STATE_WRITER"
        request["occurred_at"] = occurred_at
        return (runtime or harness.runtime).apply(request), request

    def _prepare_request(
        self,
        fixture: dict[str, Any],
    ) -> dict[str, Any]:
        harness: Harness = fixture["harness"]
        acquired, _ = self._acquire_recovery(
            fixture,
            scope="NATIVE_GOAL_GENERATION_PREPARE",
            turn_id="prepare-turn-a",
            observed_at=T3,
        )
        self.assertTrue(acquired["ok"], acquired)
        claim = acquired["result"]["lease_claim"]
        _, heartbeat_artifact = self._heartbeat_artifact(
            harness,
            stem="state-writer-prepare-heartbeat",
            observed_at=T3,
        )
        heartbeat = json.loads(heartbeat_artifact["content"])
        mutation = {
            "type": "PREPARE_NATIVE_GOAL_GENERATION_MIGRATION",
            "lease_claim": claim,
            "migration_id": fixture["migration_id"],
            "target_controller_thread_id": "controller-1",
            "null_observation_paths": [
                artifact["path"] for artifact in fixture["null_artifacts"]
            ],
            "heartbeat_observation": heartbeat,
            "automation_observation_path": heartbeat_artifact["path"],
            "automation_observation_digest": heartbeat_artifact["digest"],
            "create_outbox_id": "native-goal-generation-create-1",
            "expires_at": T5,
            "observed_at": T3,
        }
        request = harness.make_request(
            mutation,
            evidence_paths=[
                *(item["path"] for item in fixture["null_artifacts"]),
                heartbeat_artifact["path"],
            ],
            artifacts=[*fixture["null_artifacts"], heartbeat_artifact],
        )
        request["thread_id"] = "state-writer-1"
        request["actor"] = "STATE_WRITER"
        request["occurred_at"] = T3
        return request

    def _prepare(self, fixture: dict[str, Any]) -> dict[str, Any]:
        request = self._prepare_request(fixture)
        response = fixture["harness"].runtime.apply(request)
        self.assertTrue(response["ok"], response)
        return response

    def _active_goal(
        self,
        fixture: dict[str, Any],
        created_at: int = 200,
        *,
        objective: str | None = None,
    ) -> dict[str, Any]:
        return {
            "createdAt": created_at,
            "objective": objective or fixture["objective"],
            "status": "active",
            "threadId": "controller-1",
            "timeUsedSeconds": 0,
            "tokensUsed": 0,
            "updatedAt": created_at,
        }

    def _append_recovery_control_suffix(
        self,
        fixture: dict[str, Any],
        *,
        scope: str,
        turn_id: str,
        lease_claim: dict[str, Any],
        handoff_mutation: dict[str, Any],
        route_scope_override: str | None = None,
        target_override: str | None = None,
        extra_get_goal: bool = False,
    ) -> None:
        route_mutation = {
            "type": "ACQUIRE_LEASE",
            **{
                key: lease_claim[key]
                for key in (
                    "authorization_digest",
                    "authorization_steering_id",
                    "controller_pack_digest",
                    "lease_id",
                    "migration_id",
                    "recovery_scope",
                    "routing_turn_id",
                    "state_writer_thread_id",
                )
            },
        }
        if route_scope_override is not None:
            route_mutation["recovery_scope"] = route_scope_override
        elif route_mutation["recovery_scope"] != scope:
            self.fail("fixture recovery scope mismatch")
        fixture["rollout"].add_raw_tool_call(
            turn_id,
            source=json.dumps(
                {
                    "root": str(fixture["harness"].runtime.root),
                    "request": {"mutation": route_mutation},
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            tool_name="route_state_mutation",
            complete_turn=False,
        )
        if extra_get_goal:
            fixture["rollout"].add_raw_tool_call(
                turn_id,
                source=(
                    "const result = await tools.get_goal({});\n"
                    "text(JSON.stringify(result));"
                ),
                result={"goal": None},
                start_turn=False,
                complete_turn=False,
            )
        normalized_mutation = {
            key: handoff_mutation[key]
            for key in sorted(
                native_goal_observer.NATIVE_GOAL_HANDOFF_FIELDS
            )
            if key in handoff_mutation
        }
        prompt = json.dumps(
            {"mutation": normalized_mutation},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        fixture["rollout"].add_raw_tool_call(
            turn_id,
            source=json.dumps(
                {
                    "target": target_override or "state-writer-1",
                    "message": prompt,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            tool_name="send_message_to_thread",
            start_turn=False,
        )

    def _commit(
        self,
        fixture: dict[str, Any],
        *,
        lost_stdout: bool = False,
        create_count: int = 1,
        phase_b_turn_id: str = "phase-b-create-turn",
        readback_turn_id: str = "readback-turn-c",
        commit_turn_id: str = "commit-route-turn-d",
        create_observation_after_readback: bool = False,
        second_create_after_observation: bool = False,
        second_create_after_readback: bool = False,
        created_at: int = 200,
        objective: str | None = None,
        runtime: AdaptiveStateRuntime | None = None,
        control_route_scope: str | None = None,
        control_target: str | None = None,
        control_boundary_shift: int = 0,
        extra_control_get_goal: bool = False,
    ) -> dict[str, Any]:
        harness: Harness = fixture["harness"]
        prepared = harness.state()["native_goal_generation_migration"]
        outbox = prepared["create_outbox"]
        goal = self._active_goal(
            fixture,
            created_at,
            objective=objective,
        )
        for index in range(create_count):
            fixture["rollout"].add_create_goal(
                (
                    phase_b_turn_id
                    if index == 0
                    else f"{phase_b_turn_id}-{index + 1}"
                ),
                goal["objective"],
                goal,
                include_output=not lost_stdout,
            )
        rollout_artifact = None
        if not create_observation_after_readback:
            _, rollout_artifact = fixture["rollout"].observation_artifact(
                root=harness.root,
                stem="native-goal-create-rollout",
                mode="CREATE_GOAL",
                observed_at=T4,
                scan_start_offset=outbox["prepare_high_watermark"],
                expected_objective_digest=outbox["payload_digest"],
                expected_objective_bytes_digest=outbox[
                    "objective_bytes_digest"
                ],
            )
        if second_create_after_observation:
            fixture["rollout"].add_create_goal(
                "hidden-second-create-turn",
                goal["objective"],
                goal,
                include_output=not lost_stdout,
            )
        fixture["rollout"].add_get_goal(readback_turn_id, goal)
        if create_observation_after_readback:
            _, rollout_artifact = fixture["rollout"].observation_artifact(
                root=harness.root,
                stem="native-goal-create-rollout",
                mode="CREATE_GOAL",
                observed_at=T4,
                scan_start_offset=outbox["prepare_high_watermark"],
                expected_objective_digest=outbox["payload_digest"],
                expected_objective_bytes_digest=outbox[
                    "objective_bytes_digest"
                ],
            )
        assert rollout_artifact is not None
        readback_anchor = observe_native_goal_rollout(
            rollout_path=fixture["rollout"].path,
            controller_thread_id="controller-1",
            mode="GET_GOAL",
            scan_start_offset=outbox["prepare_high_watermark"],
            observed_at=T4,
            trusted_rollout_roots=(harness.root.resolve(),),
        )
        acquired, _ = self._acquire_recovery(
            fixture,
            scope="NATIVE_GOAL_GENERATION_COMMIT",
            turn_id=commit_turn_id,
            observed_at=T4,
        )
        self.assertTrue(acquired["ok"], acquired)
        goal_observation_path = (
            ".codex-loop/reports/native-goal-active-readback.json"
        )
        handoff_mutation = {
            "type": "COMMIT_NATIVE_GOAL_GENERATION_MIGRATION",
            "lease_claim": acquired["result"]["lease_claim"],
            "migration_id": fixture["migration_id"],
            "goal_observation_path": goal_observation_path,
            "rollout_observation_path": rollout_artifact["path"],
            "observed_at": T4,
        }
        self._append_recovery_control_suffix(
            fixture,
            scope="NATIVE_GOAL_GENERATION_COMMIT",
            turn_id=commit_turn_id,
            lease_claim=acquired["result"]["lease_claim"],
            handoff_mutation=handoff_mutation,
            route_scope_override=control_route_scope,
            target_override=control_target,
            extra_get_goal=extra_control_get_goal,
        )
        _, goal_artifact = fixture["rollout"].observation_artifact(
            root=harness.root,
            stem="native-goal-active-readback",
            mode="GET_GOAL",
            observed_at=T4,
            scan_start_offset=outbox["prepare_high_watermark"],
            expected_objective_digest=outbox["payload_digest"],
            expected_objective_bytes_digest=outbox[
                "objective_bytes_digest"
            ],
            control_suffix_start_offset=(
                readback_anchor["turn_end_offset"] + control_boundary_shift
            ),
        )
        if second_create_after_readback:
            fixture["rollout"].add_create_goal(
                "post-readback-hidden-create",
                goal["objective"],
                goal,
                include_output=False,
            )
        _, heartbeat_artifact = self._heartbeat_artifact(
            harness,
            stem="state-writer-commit-heartbeat",
            observed_at=T4,
        )
        mutation = {
            "type": "COMMIT_NATIVE_GOAL_GENERATION_MIGRATION",
            "lease_claim": acquired["result"]["lease_claim"],
            "migration_id": fixture["migration_id"],
            "goal_observation_path": goal_artifact["path"],
            "rollout_observation_path": rollout_artifact["path"],
            "heartbeat_observation": json.loads(
                heartbeat_artifact["content"]
            ),
            "automation_observation_path": heartbeat_artifact["path"],
            "automation_observation_digest": heartbeat_artifact["digest"],
            "observed_at": T4,
        }
        response, _ = self._state_writer_apply(
            harness,
            mutation,
            occurred_at=T4,
            artifacts=[
                rollout_artifact,
                goal_artifact,
                heartbeat_artifact,
            ],
            runtime=runtime,
        )
        return response

    def _rollback(
        self,
        fixture: dict[str, Any],
        *,
        add_started_create: bool = False,
        add_create_after_observation: bool = False,
        add_create_after_final_null: bool = False,
        runtime: AdaptiveStateRuntime | None = None,
        return_request: bool = False,
    ) -> dict[str, Any] | tuple[dict[str, Any], dict[str, Any]]:
        harness: Harness = fixture["harness"]
        prepared = harness.state()["native_goal_generation_migration"]
        outbox = prepared["create_outbox"]
        if add_started_create:
            fixture["rollout"].add_create_goal(
                "rollback-started-create",
                fixture["objective"],
                self._active_goal(fixture),
                include_output=False,
            )
        _, rollout_artifact = fixture["rollout"].observation_artifact(
            root=harness.root,
            stem="native-goal-rollback-rollout",
            mode="CREATE_GOAL",
            observed_at="2026-01-01T01:02:00Z",
            scan_start_offset=outbox["prepare_high_watermark"],
            expected_objective_digest=outbox["payload_digest"],
            expected_objective_bytes_digest=outbox[
                "objective_bytes_digest"
            ],
        )
        if add_create_after_observation:
            fixture["rollout"].add_create_goal(
                "rollback-hidden-create",
                fixture["objective"],
                self._active_goal(fixture),
                include_output=False,
            )
        fixture["rollout"].add_get_goal("rollback-null-one", None)
        _, null_one = fixture["rollout"].observation_artifact(
            root=harness.root,
            stem="native-goal-rollback-null-one",
            mode="GET_GOAL",
            observed_at="2026-01-01T01:00:30Z",
            scan_start_offset=outbox["prepare_high_watermark"],
        )
        fixture["rollout"].add_get_goal("rollback-null-two", None)
        null_anchor = observe_native_goal_rollout(
            rollout_path=fixture["rollout"].path,
            controller_thread_id="controller-1",
            mode="GET_GOAL",
            scan_start_offset=outbox["prepare_high_watermark"],
            observed_at="2026-01-01T01:01:00Z",
            trusted_rollout_roots=(harness.root.resolve(),),
        )
        acquired, _ = self._acquire_recovery(
            fixture,
            scope="NATIVE_GOAL_GENERATION_ROLLBACK",
            turn_id="rollback-turn-c",
            observed_at="2026-01-01T01:02:00Z",
        )
        self.assertTrue(acquired["ok"], acquired)
        null_two_path = (
            ".codex-loop/reports/native-goal-rollback-null-two.json"
        )
        handoff_mutation = {
            "type": "ROLLBACK_NATIVE_GOAL_GENERATION_MIGRATION",
            "lease_claim": acquired["result"]["lease_claim"],
            "migration_id": fixture["migration_id"],
            "null_observation_paths": [null_one["path"], null_two_path],
            "rollout_observation_path": rollout_artifact["path"],
            "rollback_reason": "stable evidence proves create was not invoked",
            "observed_at": "2026-01-01T01:02:00Z",
        }
        self._append_recovery_control_suffix(
            fixture,
            scope="NATIVE_GOAL_GENERATION_ROLLBACK",
            turn_id="rollback-turn-c",
            lease_claim=acquired["result"]["lease_claim"],
            handoff_mutation=handoff_mutation,
        )
        _, null_two = fixture["rollout"].observation_artifact(
            root=harness.root,
            stem="native-goal-rollback-null-two",
            mode="GET_GOAL",
            observed_at="2026-01-01T01:01:00Z",
            scan_start_offset=outbox["prepare_high_watermark"],
            expected_objective_digest=outbox["payload_digest"],
            expected_objective_bytes_digest=outbox[
                "objective_bytes_digest"
            ],
            control_suffix_start_offset=null_anchor["turn_end_offset"],
        )
        if add_create_after_final_null:
            fixture["rollout"].add_create_goal(
                "rollback-post-null-hidden-create",
                fixture["objective"],
                self._active_goal(fixture),
                include_output=False,
            )
        _, heartbeat_artifact = self._heartbeat_artifact(
            harness,
            stem="state-writer-rollback-success-heartbeat",
            observed_at="2026-01-01T01:02:00Z",
        )
        mutation = {
            "type": "ROLLBACK_NATIVE_GOAL_GENERATION_MIGRATION",
            "lease_claim": acquired["result"]["lease_claim"],
            "migration_id": fixture["migration_id"],
            "null_observation_paths": [null_one["path"], null_two["path"]],
            "rollout_observation_path": rollout_artifact["path"],
            "heartbeat_observation": json.loads(
                heartbeat_artifact["content"]
            ),
            "automation_observation_path": heartbeat_artifact["path"],
            "automation_observation_digest": heartbeat_artifact["digest"],
            "rollback_reason": "stable evidence proves create was not invoked",
            "observed_at": "2026-01-01T01:02:00Z",
        }
        response, request = self._state_writer_apply(
            harness,
            mutation,
            occurred_at="2026-01-01T01:02:00Z",
            artifacts=[
                rollout_artifact,
                null_one,
                null_two,
                heartbeat_artifact,
            ],
            runtime=runtime,
        )
        return (response, request) if return_request else response

    def test_pack_migration_derives_legacy_generation_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self._fixture(Path(temporary))
            state = fixture["harness"].state()
            generation_id = state["controller_goal"]["current_generation_id"]
            generation = state["native_goal_generation_ledger"][generation_id]
            self.assertEqual(generation["created_at"], 100)
            self.assertEqual(generation["usage"]["tokens_used"], 41)
            self.assertEqual(
                generation["create_observation_path"],
                fixture["create_artifact"]["path"],
            )
            expected = hashlib.sha256(
                b"native-goal-generation-v1\0"
                + b"controller-1\0"
                + b"100\0"
                + generation["objective_digest"].encode("utf-8")
            ).hexdigest()[:32]
            self.assertEqual(generation_id, f"ngen-{expected}")
            goal_outbox = state["controller_goal_outbox"][
                "legacy-native-goal-create"
            ]
            self.assertEqual(goal_outbox, fixture["legacy_goal_outbox"])
            heartbeat_outbox = state["automation_outbox"][
                "heartbeat-create-1"
            ]
            for field in (
                "outbox_id",
                "identity",
                "sent_evidence_paths",
                "ack_evidence_paths",
            ):
                self.assertEqual(
                    heartbeat_outbox[field],
                    fixture["legacy_heartbeat_outbox"][field],
                )

    def test_ordinary_native_goal_create_derives_real_generation_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            self.assertTrue(harness.initialize()[0]["ok"])
            harness.register_control_result(
                "GOAL",
                "ordinary-native-goal-create",
                "controller-1",
                {"action": "CREATE", "milestone_id": "m1"},
                {"goal_id": "controller-1", "status": "ACTIVE"},
            )
            state = harness.state()
            generation_id = state["controller_goal"][
                "current_generation_id"
            ]
            generation = state["native_goal_generation_ledger"][
                generation_id
            ]
            self.assertEqual(generation["created_at"], 100)
            self.assertEqual(generation["usage"]["tokens_used"], 0)
            self.assertTrue(generation["usage"]["tokens_complete"])
            self.assertNotEqual(
                generation["create_observation_path"],
                generation["ack_observation_path"],
            )
            for path_field, digest_field in (
                ("create_observation_path", "create_observation_digest"),
                ("ack_observation_path", "ack_observation_digest"),
            ):
                payload = (root / generation[path_field]).read_bytes()
                self.assertEqual(
                    "sha256:" + hashlib.sha256(payload).hexdigest(),
                    generation[digest_field],
                )

    def test_prepare_rejects_caller_supplied_generation_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = self._fixture(root)
            acquired, heartbeat_artifact = self._acquire_recovery(
                fixture,
                scope="NATIVE_GOAL_GENERATION_PREPARE",
                turn_id="caller-generation-turn",
                observed_at=T3,
            )
            self.assertTrue(acquired["ok"], acquired)
            mutation = {
                "type": "PREPARE_NATIVE_GOAL_GENERATION_MIGRATION",
                "lease_claim": acquired["result"]["lease_claim"],
                "migration_id": fixture["migration_id"],
                "target_controller_thread_id": "controller-1",
                "source_generation_id": "caller-chosen-source",
                "null_observation_paths": [
                    item["path"] for item in fixture["null_artifacts"]
                ],
                "heartbeat_observation": json.loads(
                    heartbeat_artifact["content"]
                ),
                "automation_observation_path": heartbeat_artifact["path"],
                "automation_observation_digest": heartbeat_artifact["digest"],
                "create_outbox_id": "caller-generation-outbox",
                "expires_at": T5,
                "observed_at": T3,
            }
            before = persisted_snapshot(root)
            rejected, _ = self._state_writer_apply(
                fixture["harness"],
                mutation,
                occurred_at=T3,
                artifacts=[*fixture["null_artifacts"], heartbeat_artifact],
            )
            self.assertEqual(rejected["status"], "REQUEST_SCHEMA_INVALID")
            self.assertEqual(persisted_snapshot(root), before)

    def test_pack_migration_baseline_missing_receipt_is_zero_effect(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            self.assertTrue(harness.initialize()[0]["ok"])
            harness.ensure_all_roles()
            harness.ensure_heartbeat()
            harness.register_control_result(
                "GOAL",
                "legacy-native-goal-create",
                "controller-1",
                {"action": "CREATE", "milestone_id": "m1"},
                {"goal_id": "controller-1", "status": "ACTIVE"},
            )
            self._rewrite_as_legacy_with_real_create_receipt(harness)
            state = harness.state()
            sent_path = state["controller_goal_outbox"][
                "legacy-native-goal-create"
            ]["sent_evidence_paths"][0]
            (root / sent_path).unlink()
            self._pause(harness)
            prepared = harness.prepare_pack_migration(
                content="# target pack",
                target_prompt="target prompt",
                migration_id="missing-baseline-receipt",
            )
            self.assertTrue(prepared["response"]["ok"])
            before = persisted_snapshot(root)
            rejected = harness.commit_pack_migration(prepared)
            self.assertEqual(
                rejected["status"],
                "NATIVE_GOAL_GENERATION_BASELINE_EVIDENCE_INVALID",
            )
            self.assertEqual(persisted_snapshot(root), before)

    def test_pack_migration_baseline_digest_mismatch_is_zero_effect(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            self.assertTrue(harness.initialize()[0]["ok"])
            harness.ensure_all_roles()
            harness.ensure_heartbeat()
            harness.register_control_result(
                "GOAL",
                "legacy-native-goal-create",
                "controller-1",
                {"action": "CREATE", "milestone_id": "m1"},
                {"goal_id": "controller-1", "status": "ACTIVE"},
            )
            self._rewrite_as_legacy_with_real_create_receipt(harness)
            state = harness.state()
            sent_path = state["controller_goal_outbox"][
                "legacy-native-goal-create"
            ]["sent_evidence_paths"][0]
            (root / sent_path).write_text("{}", encoding="utf-8")
            self._pause(harness)
            prepared = harness.prepare_pack_migration(
                content="# target pack",
                target_prompt="target prompt",
                migration_id="mismatched-baseline-receipt",
            )
            self.assertTrue(prepared["response"]["ok"])
            before = persisted_snapshot(root)
            rejected = harness.commit_pack_migration(prepared)
            self.assertEqual(
                rejected["status"],
                "NATIVE_GOAL_GENERATION_BASELINE_EVIDENCE_INVALID",
            )
            self.assertEqual(persisted_snapshot(root), before)

    def test_regular_paused_lease_still_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self._fixture(Path(temporary))
            rejected = fixture["harness"].apply(
                {
                    "type": "ACQUIRE_LEASE",
                    "routing_turn_id": "ordinary-paused-route",
                    "lease_id": "ordinary-paused-lease",
                    "owner_kind": "GOAL_TURN",
                    "owner_identity": "controller-1",
                    "observed_at": T3,
                    "expires_at": T5,
                    "controller_turn_id": "ordinary-paused-turn",
                }
            )
            self.assertEqual(rejected["status"], "LOOP_PAUSED")

    def test_recovery_lease_binds_state_writer_and_trusted_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = self._fixture(root)
            before = persisted_snapshot(root)
            acquired, _ = self._acquire_recovery(
                fixture,
                scope="NATIVE_GOAL_GENERATION_PREPARE",
                turn_id="prepare-turn-a",
                observed_at=T3,
            )
            self.assertTrue(acquired["ok"], acquired)
            self.assertEqual(
                acquired["result"]["lease_claim"]["state_writer_thread_id"],
                "state-writer-1",
            )
            self.assertNotEqual(persisted_snapshot(root), before)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = self._fixture(root)
            heartbeat, artifact = self._heartbeat_artifact(
                fixture["harness"], stem="wrong-state-writer", observed_at=T3
            )
            mutation = {
                "type": "ACQUIRE_LEASE",
                "routing_turn_id": "route-wrong-writer",
                "lease_id": "lease-wrong-writer",
                "owner_kind": "GOAL_TURN",
                "owner_identity": "controller-1",
                "observed_at": T3,
                "expires_at": T5,
                "controller_turn_id": "turn-wrong-writer",
                "recovery_scope": "NATIVE_GOAL_GENERATION_PREPARE",
                "migration_id": fixture["migration_id"],
                "state_writer_thread_id": "worker-1",
                "controller_pack_digest": fixture["harness"].state()[
                    "controller_pack_identity"
                ]["digest"],
                "authorization_steering_id": fixture["authorization_id"],
                "authorization_digest": fixture["authorization_digest"],
                "heartbeat_observation": heartbeat,
                "automation_observation_path": artifact["path"],
                "automation_observation_digest": artifact["digest"],
            }
            request = fixture["harness"].make_request(
                mutation,
                evidence_paths=[artifact["path"]],
                artifacts=[artifact],
            )
            request["occurred_at"] = T3
            before = persisted_snapshot(root)
            rejected = fixture["harness"].runtime.apply(
                request,
                trusted_turn_metadata=trusted_metadata_for_request(request),
            )
            self.assertEqual(
                rejected["status"],
                "NATIVE_GOAL_GENERATION_STATE_WRITER_IDENTITY_INVALID",
            )
            self.assertEqual(persisted_snapshot(root), before)

    def test_recovery_scope_authorization_and_metadata_fail_closed(self) -> None:
        cases = (
            ("invalid-scope", "NOT_A_RECOVERY_SCOPE"),
            ("missing-authorization", "NATIVE_GOAL_GENERATION_PREPARE"),
            ("wrong-turn-metadata", "NATIVE_GOAL_GENERATION_PREPARE"),
        )
        for case, scope in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = self._fixture(root)
                request, _ = self._recovery_acquire_request(
                    fixture,
                    scope=scope,
                    turn_id=f"{case}-turn",
                    observed_at=T3,
                    authorization_steering_id=(
                        "missing-authorization"
                        if case == "missing-authorization"
                        else None
                    ),
                    authorization_digest=(
                        digest("missing-authorization")
                        if case == "missing-authorization"
                        else None
                    ),
                )
                before = persisted_snapshot(root)
                metadata_turn = (
                    "different-real-turn"
                    if case == "wrong-turn-metadata"
                    else f"{case}-turn"
                )
                rejected = fixture["harness"].runtime.apply(
                    request,
                    trusted_turn_metadata=trusted_metadata_for_request(
                        request,
                        turn_id=metadata_turn,
                    ),
                )
                expected = {
                    "invalid-scope": "REQUEST_SCHEMA_INVALID",
                    "missing-authorization": (
                        "NATIVE_GOAL_GENERATION_AUTHORIZATION_INVALID"
                    ),
                    "wrong-turn-metadata": (
                        "CONTROLLER_TURN_ATTESTATION_MISMATCH"
                    ),
                }[case]
                self.assertEqual(rejected["status"], expected)
                self.assertEqual(persisted_snapshot(root), before)

    def test_recovery_lease_is_single_use_and_real_turn_is_single_route(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = self._fixture(root)
            self._prepare(fixture)
            state = fixture["harness"].state()
            self.assertIn(
                "lease-prepare-turn-a",
                state["consumed_controller_lease_ids"],
            )
            claim = {
                "lease_epoch": state["lease_epoch_counter"],
                "lease_id": "lease-prepare-turn-a",
                "routing_turn_id": "route-prepare-turn-a",
                "owner_kind": "GOAL_TURN",
                "owner_identity": "controller-1",
                "intended_transition": "ROUTE_ONE_TRANSITION",
                "recovery_scope": "NATIVE_GOAL_GENERATION_PREPARE",
                "migration_id": fixture["migration_id"],
                "state_writer_thread_id": "state-writer-1",
                "controller_pack_digest": state[
                    "controller_pack_identity"
                ]["digest"],
                "authorization_steering_id": fixture["authorization_id"],
                "authorization_digest": fixture["authorization_digest"],
            }
            before = persisted_snapshot(root)
            stale = fixture["harness"].apply(
                {
                    "type": "RELEASE_LEASE",
                    "lease_claim": claim,
                    "observed_at": T3,
                    "reason_code": "RECOVERY_LEASE_REPLAY",
                }
            )
            self.assertEqual(
                stale["status"], "STALE_OR_MISSING_CONTROLLER_LEASE"
            )
            self.assertEqual(persisted_snapshot(root), before)

            request, _ = self._recovery_acquire_request(
                fixture,
                scope="NATIVE_GOAL_GENERATION_COMMIT",
                turn_id="prepare-turn-a",
                observed_at=T4,
            )
            second_route = fixture["harness"].runtime.apply(
                request,
                trusted_turn_metadata=trusted_metadata_for_request(
                    request,
                    turn_id="prepare-turn-a",
                ),
            )
            self.assertEqual(
                second_route["status"], "CONTROLLER_TURN_ALREADY_ROUTED"
            )
            self.assertEqual(persisted_snapshot(root), before)

    def test_prepare_consumes_recovery_lease_and_authorizes_unused_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self._fixture(Path(temporary))
            self._prepare(fixture)
            state = fixture["harness"].state()
            prepared = state["native_goal_generation_migration"]
            self.assertIsNone(state["controller_lease"])
            self.assertEqual(prepared["status"], "PREPARED")
            self.assertEqual(
                prepared["create_outbox"]["status"], "AUTHORIZED_UNUSED"
            )
            self.assertEqual(
                prepared["prepared_controller_turn_id"], "prepare-turn-a"
            )
            self.assertIsNone(prepared["readback_controller_turn_id"])

    def test_prepare_replay_is_exact_identity_bound(self) -> None:
        for wrong_paths in (False, True):
            with self.subTest(wrong_paths=wrong_paths), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = self._fixture(root)
                self._prepare(fixture)
                acquired, _ = self._acquire_recovery(
                    fixture,
                    scope="NATIVE_GOAL_GENERATION_PREPARE",
                    turn_id=(
                        "prepare-replay-wrong-turn"
                        if wrong_paths
                        else "prepare-replay-turn"
                    ),
                    observed_at=T4,
                )
                self.assertTrue(acquired["ok"], acquired)
                _, heartbeat_artifact = self._heartbeat_artifact(
                    fixture["harness"],
                    stem=(
                        "state-writer-prepare-replay-wrong-heartbeat"
                        if wrong_paths
                        else "state-writer-prepare-replay-heartbeat"
                    ),
                    observed_at=T4,
                )
                null_paths = [
                    item["path"] for item in fixture["null_artifacts"]
                ]
                if wrong_paths:
                    null_paths = list(reversed(null_paths))
                mutation = {
                    "type": "PREPARE_NATIVE_GOAL_GENERATION_MIGRATION",
                    "lease_claim": acquired["result"]["lease_claim"],
                    "migration_id": fixture["migration_id"],
                    "target_controller_thread_id": "controller-1",
                    "null_observation_paths": null_paths,
                    "heartbeat_observation": json.loads(
                        heartbeat_artifact["content"]
                    ),
                    "automation_observation_path": heartbeat_artifact["path"],
                    "automation_observation_digest": heartbeat_artifact[
                        "digest"
                    ],
                    "create_outbox_id": "native-goal-generation-create-1",
                    "expires_at": T5,
                    "observed_at": T4,
                }
                before = persisted_snapshot(root)
                replay, _ = self._state_writer_apply(
                    fixture["harness"],
                    mutation,
                    occurred_at=T4,
                    artifacts=[
                        *fixture["null_artifacts"],
                        heartbeat_artifact,
                    ],
                )
                if wrong_paths:
                    self.assertEqual(
                        replay["status"],
                        "NATIVE_GOAL_GENERATION_PREPARE_REPLAY_IDENTITY_MISMATCH",
                    )
                    self.assertEqual(persisted_snapshot(root), before)
                else:
                    self.assertTrue(replay["ok"], replay)
                    self.assertEqual(
                        replay["operation_status"],
                        "NATIVE_GOAL_GENERATION_MIGRATION_ALREADY_PREPARED",
                    )
                    state = fixture["harness"].state()
                    self.assertIsNone(state["controller_lease"])
                    self.assertEqual(
                        len(state["native_goal_generation_ledger"]), 1
                    )

    def test_prepare_crash_recovery_and_cas_conflict_are_fail_closed(self) -> None:
        for stage in (
            "NATIVE_GOAL_GENERATION_PREPARED_PROJECTED",
            "STATE_REPLACED",
        ):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = self._fixture(root)
                request = self._prepare_request(fixture)
                crashing = state_runtime_module.AdaptiveStateRuntime(
                    root,
                    crash_at=stage,
                    native_goal_rollout_roots=(root.resolve(),),
                )
                with self.assertRaises(state_runtime_module.InjectedCrash):
                    crashing.apply(copy.deepcopy(request))
                recovered = state_runtime_module.AdaptiveStateRuntime(
                    root,
                    native_goal_rollout_roots=(root.resolve(),),
                )
                self.assertTrue(recovered.recover()["ok"])
                replay = recovered.apply(copy.deepcopy(request))
                self.assertTrue(replay["ok"], replay)
                state = recovered.read_state()
                assert state is not None
                self.assertEqual(
                    state["native_goal_generation_migration"]["status"],
                    "PREPARED",
                )
                self.assertIsNone(state["controller_lease"])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = self._fixture(root)
            request = self._prepare_request(fixture)
            intervening = fixture["harness"].apply(
                {
                    "type": "RECORD_STEERING",
                    "steering_id": "intervening-cas-steering",
                    "steering_type": "CONSTRAINT",
                    "normalized_digest": digest("intervening CAS write"),
                    "identity_algorithm": "message-item-v1",
                    "message_item_id": "intervening-cas-message",
                    "summary": "force a stale State-Writer CAS",
                    "classification_reason": "recovery CAS regression",
                }
            )
            self.assertTrue(intervening["ok"], intervening)
            before = persisted_snapshot(root)
            stale = fixture["harness"].runtime.apply(request)
            self.assertEqual(stale["status"], "STATE_VERSION_CONFLICT")
            self.assertEqual(persisted_snapshot(root), before)
            self.assertIsNone(
                fixture["harness"].state()[
                    "native_goal_generation_migration"
                ]
            )

    def test_state_writer_without_recovery_lease_cannot_prepare(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self._fixture(Path(temporary))
            harness = fixture["harness"]
            heartbeat, artifact = self._heartbeat_artifact(
                harness, stem="no-lease-prepare", observed_at=T3
            )
            fake_claim = {
                "lease_epoch": 999,
                "lease_id": "missing-lease",
                "routing_turn_id": "missing-route",
                "owner_kind": "GOAL_TURN",
                "owner_identity": "controller-1",
                "intended_transition": "ROUTE_ONE_TRANSITION",
                "recovery_scope": "NATIVE_GOAL_GENERATION_PREPARE",
                "migration_id": fixture["migration_id"],
                "state_writer_thread_id": "state-writer-1",
                "controller_pack_digest": harness.state()[
                    "controller_pack_identity"
                ]["digest"],
                "authorization_steering_id": fixture["authorization_id"],
                "authorization_digest": fixture["authorization_digest"],
            }
            mutation = {
                "type": "PREPARE_NATIVE_GOAL_GENERATION_MIGRATION",
                "lease_claim": fake_claim,
                "migration_id": fixture["migration_id"],
                "target_controller_thread_id": "controller-1",
                "null_observation_paths": [
                    item["path"] for item in fixture["null_artifacts"]
                ],
                "heartbeat_observation": heartbeat,
                "automation_observation_path": artifact["path"],
                "automation_observation_digest": artifact["digest"],
                "create_outbox_id": "unused-outbox",
                "expires_at": T5,
                "observed_at": T3,
            }
            rejected, _ = self._state_writer_apply(
                harness,
                mutation,
                occurred_at=T3,
                artifacts=[*fixture["null_artifacts"], artifact],
            )
            self.assertEqual(
                rejected["status"], "STALE_OR_MISSING_CONTROLLER_LEASE"
            )

    def test_state_writer_without_scoped_lease_cannot_commit_or_rollback(self) -> None:
        for scope, mutation_type in (
            (
                "NATIVE_GOAL_GENERATION_COMMIT",
                "COMMIT_NATIVE_GOAL_GENERATION_MIGRATION",
            ),
            (
                "NATIVE_GOAL_GENERATION_ROLLBACK",
                "ROLLBACK_NATIVE_GOAL_GENERATION_MIGRATION",
            ),
        ):
            with self.subTest(scope=scope), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = self._fixture(root)
                self._prepare(fixture)
                harness = fixture["harness"]
                _, heartbeat_artifact = self._heartbeat_artifact(
                    harness,
                    stem=f"no-{scope.lower()}-heartbeat",
                    observed_at=T4,
                )
                fake_claim = {
                    "lease_epoch": 999,
                    "lease_id": f"missing-{scope.lower()}-lease",
                    "routing_turn_id": f"missing-{scope.lower()}-route",
                    "owner_kind": "GOAL_TURN",
                    "owner_identity": "controller-1",
                    "intended_transition": "ROUTE_ONE_TRANSITION",
                    "recovery_scope": scope,
                    "migration_id": fixture["migration_id"],
                    "state_writer_thread_id": "state-writer-1",
                    "controller_pack_digest": harness.state()[
                        "controller_pack_identity"
                    ]["digest"],
                    "authorization_steering_id": fixture[
                        "authorization_id"
                    ],
                    "authorization_digest": fixture[
                        "authorization_digest"
                    ],
                }
                common = {
                    "type": mutation_type,
                    "lease_claim": fake_claim,
                    "migration_id": fixture["migration_id"],
                    "heartbeat_observation": json.loads(
                        heartbeat_artifact["content"]
                    ),
                    "automation_observation_path": heartbeat_artifact["path"],
                    "automation_observation_digest": heartbeat_artifact[
                        "digest"
                    ],
                    "observed_at": T4,
                }
                if scope == "NATIVE_GOAL_GENERATION_COMMIT":
                    common.update(
                        {
                            "goal_observation_path": fixture[
                                "null_artifacts"
                            ][-1]["path"],
                            "rollout_observation_path": fixture[
                                "null_artifacts"
                            ][-1]["path"],
                        }
                    )
                else:
                    common.update(
                        {
                            "null_observation_paths": [
                                item["path"]
                                for item in fixture["null_artifacts"]
                            ],
                            "rollout_observation_path": fixture[
                                "null_artifacts"
                            ][-1]["path"],
                            "rollback_reason": "negative lease test",
                        }
                    )
                before = persisted_snapshot(root)
                rejected, _ = self._state_writer_apply(
                    harness,
                    common,
                    occurred_at=T4,
                    artifacts=[
                        *fixture["null_artifacts"],
                        heartbeat_artifact,
                    ],
                )
                self.assertEqual(
                    rejected["status"], "STALE_OR_MISSING_CONTROLLER_LEASE"
                )
                self.assertEqual(persisted_snapshot(root), before)

    def test_commit_completed_rollout_switches_generation_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self._fixture(Path(temporary))
            self._prepare(fixture)
            before = fixture["harness"].state()
            source_id = before["controller_goal"]["current_generation_id"]
            committed = self._commit(fixture)
            self.assertTrue(committed["ok"], committed)
            state = fixture["harness"].state()
            migration = state["native_goal_generation_migration"]
            target_id = migration["target_generation_id"]
            self.assertEqual(migration["status"], "COMMITTED")
            self.assertEqual(
                migration["readback_controller_turn_id"], "readback-turn-c"
            )
            self.assertEqual(
                migration["commit_controller_turn_id"], "commit-route-turn-d"
            )
            self.assertEqual(state["controller_goal"]["current_generation_id"], target_id)
            self.assertEqual(
                state["native_goal_generation_ledger"][source_id]["status"],
                "LOST_UPSTREAM",
            )
            self.assertEqual(
                state["native_goal_generation_ledger"][target_id]["status"],
                "ACTIVE",
            )
            self.assertIsNone(state["controller_lease"])

    def test_commit_lost_stdout_adopts_active_readback_without_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self._fixture(Path(temporary))
            self._prepare(fixture)
            committed = self._commit(fixture, lost_stdout=True)
            self.assertTrue(committed["ok"], committed)
            self.assertTrue(committed["result"]["lost_stdout_adopted"])
            outbox = fixture["harness"].state()[
                "native_goal_generation_migration"
            ]["create_outbox"]
            self.assertEqual(outbox["create_attempt_count"], 1)

    def test_commit_validates_readback_and_create_window_from_one_snapshot(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self._fixture(Path(temporary))
            self._prepare(fixture)
            with mock.patch.object(
                state_runtime_module,
                "observe_native_goal_rollout",
                wraps=state_runtime_module.observe_native_goal_rollout,
            ) as observer:
                committed = self._commit(fixture)
            self.assertTrue(committed["ok"], committed)
            # One replay validates the Phase B receipt. One current-EOF read
            # atomically validates both the Goal readback and create window.
            # A third rollout open would reintroduce the inter-read TOCTOU.
            self.assertEqual(observer.call_count, 2)

    def test_commit_binds_control_boundary_scope_and_state_writer_target(
        self,
    ) -> None:
        cases = (
            {"control_boundary_shift": 1},
            {"control_route_scope": "NATIVE_GOAL_GENERATION_ROLLBACK"},
            {"control_target": "worker-1"},
            {"extra_control_get_goal": True},
        )
        for options in cases:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temporary:
                fixture = self._fixture(Path(temporary))
                self._prepare(fixture)
                rejected = self._commit(fixture, **options)
                self.assertEqual(
                    rejected["status"],
                    "NATIVE_GOAL_CONTROL_SUFFIX_IDENTITY_INVALID",
                )
                self.assertEqual(
                    fixture["harness"].state()[
                        "native_goal_generation_migration"
                    ]["status"],
                    "PREPARED",
                )

    def test_commit_rejects_zero_or_multiple_create_invocations(self) -> None:
        for create_count in (0, 2):
            with self.subTest(create_count=create_count), tempfile.TemporaryDirectory() as temporary:
                fixture = self._fixture(Path(temporary))
                self._prepare(fixture)
                rejected = self._commit(
                    fixture,
                    create_count=create_count,
                )
                self.assertEqual(
                    rejected["status"],
                    "NATIVE_GOAL_CREATE_INVOCATION_RECEIPT_INVALID",
                )
                migration = fixture["harness"].state()[
                    "native_goal_generation_migration"
                ]
                self.assertEqual(migration["status"], "PREPARED")
                self.assertEqual(
                    migration["create_outbox"]["create_attempt_count"], 0
                )

    def test_commit_rejects_turn_objective_and_created_at_identity_drift(self) -> None:
        cases = (
            {"phase_b_turn_id": "prepare-turn-a"},
            {"readback_turn_id": "prepare-turn-a"},
            {"phase_b_turn_id": "commit-route-turn-d"},
            {"create_observation_after_readback": True},
            {"second_create_after_observation": True},
            {"second_create_after_readback": True},
            {"objective": "different body\n[different marker]"},
            {"created_at": 100},
        )
        for options in cases:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temporary:
                fixture = self._fixture(Path(temporary))
                self._prepare(fixture)
                rejected = self._commit(fixture, **options)
                self.assertIn(
                    rejected["status"],
                    {
                        "NATIVE_GOAL_CREATE_INVOCATION_RECEIPT_INVALID",
                        "NATIVE_GOAL_CONTROL_SUFFIX_IDENTITY_INVALID",
                        "NATIVE_GOAL_GENERATION_READBACK_IDENTITY_MISMATCH",
                        "NATIVE_GOAL_ROLLOUT_FINAL_EOF_CHANGED",
                    },
                )
                self.assertEqual(
                    fixture["harness"].state()[
                        "native_goal_generation_migration"
                    ]["status"],
                    "PREPARED",
                )

        with tempfile.TemporaryDirectory() as temporary:
            fixture = self._fixture(Path(temporary))
            self._prepare(fixture)
            with self.assertRaises(NativeGoalObservationError) as caught:
                self._commit(
                    fixture,
                    readback_turn_id="commit-route-turn-d",
                )
            self.assertEqual(
                caught.exception.code,
                "NATIVE_GOAL_GET_GOAL_OBSERVATION_UNAVAILABLE",
            )
            self.assertEqual(
                fixture["harness"].state()[
                    "native_goal_generation_migration"
                ]["status"],
                "PREPARED",
            )

        with tempfile.TemporaryDirectory() as temporary:
            fixture = self._fixture(Path(temporary))
            self._prepare(fixture)
            with self.assertRaises(NativeGoalObservationError) as caught:
                self._commit(
                    fixture,
                    readback_turn_id="phase-b-create-turn",
                )
            self.assertEqual(
                caught.exception.code,
                "NATIVE_GOAL_GET_GOAL_OBSERVATION_UNAVAILABLE",
            )
            self.assertEqual(
                fixture["harness"].state()[
                    "native_goal_generation_migration"
                ]["status"],
                "PREPARED",
            )

    def test_commit_replay_is_identity_bound_and_keeps_loop_paused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = self._fixture(root)
            self._prepare(fixture)
            committed = self._commit(fixture)
            self.assertTrue(committed["ok"], committed)
            state = fixture["harness"].state()
            self.assertEqual(
                state["run_control"]["status"], "PAUSED_AT_SAFE_POINT"
            )
            self.assertEqual(
                state["heartbeat_live_observation"]["status"], "PAUSED"
            )
            prepared = state["native_goal_generation_migration"]
            target = state["native_goal_generation_ledger"][
                prepared["target_generation_id"]
            ]
            acquired, _ = self._acquire_recovery(
                fixture,
                scope="NATIVE_GOAL_GENERATION_COMMIT",
                turn_id="commit-replay-turn",
                observed_at="2026-01-01T01:02:00Z",
            )
            self.assertTrue(acquired["ok"], acquired)
            _, heartbeat_artifact = self._heartbeat_artifact(
                fixture["harness"],
                stem="state-writer-commit-replay-heartbeat",
                observed_at="2026-01-01T01:02:00Z",
            )
            mutation = {
                "type": "COMMIT_NATIVE_GOAL_GENERATION_MIGRATION",
                "lease_claim": acquired["result"]["lease_claim"],
                "migration_id": fixture["migration_id"],
                "goal_observation_path": target["ack_observation_path"],
                "rollout_observation_path": prepared["create_outbox"][
                    "result_observation_path"
                ],
                "heartbeat_observation": json.loads(
                    heartbeat_artifact["content"]
                ),
                "automation_observation_path": heartbeat_artifact["path"],
                "automation_observation_digest": heartbeat_artifact["digest"],
                "observed_at": "2026-01-01T01:02:00Z",
            }
            replayed, _ = self._state_writer_apply(
                fixture["harness"],
                mutation,
                occurred_at="2026-01-01T01:02:00Z",
                artifacts=[heartbeat_artifact],
            )
            self.assertTrue(replayed["ok"], replayed)
            self.assertEqual(
                replayed["operation_status"],
                "NATIVE_GOAL_GENERATION_MIGRATION_ALREADY_COMMITTED",
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = self._fixture(root)
            self._prepare(fixture)
            self.assertTrue(self._commit(fixture)["ok"])
            acquired, _ = self._acquire_recovery(
                fixture,
                scope="NATIVE_GOAL_GENERATION_COMMIT",
                turn_id="wrong-commit-replay-turn",
                observed_at="2026-01-01T01:02:00Z",
            )
            _, heartbeat_artifact = self._heartbeat_artifact(
                fixture["harness"],
                stem="wrong-commit-replay-heartbeat",
                observed_at="2026-01-01T01:02:00Z",
            )
            mutation = {
                "type": "COMMIT_NATIVE_GOAL_GENERATION_MIGRATION",
                "lease_claim": acquired["result"]["lease_claim"],
                "migration_id": fixture["migration_id"],
                "goal_observation_path": ".codex-loop/reports/wrong.json",
                "rollout_observation_path": ".codex-loop/reports/wrong.json",
                "heartbeat_observation": json.loads(
                    heartbeat_artifact["content"]
                ),
                "automation_observation_path": heartbeat_artifact["path"],
                "automation_observation_digest": heartbeat_artifact["digest"],
                "observed_at": "2026-01-01T01:02:00Z",
            }
            before = persisted_snapshot(root)
            rejected, _ = self._state_writer_apply(
                fixture["harness"],
                mutation,
                occurred_at="2026-01-01T01:02:00Z",
                artifacts=[heartbeat_artifact],
            )
            self.assertEqual(
                rejected["status"],
                "NATIVE_GOAL_GENERATION_COMMIT_REPLAY_IDENTITY_MISMATCH",
            )
            self.assertEqual(persisted_snapshot(root), before)

    def test_rollback_success_preserves_source_identity_and_prepared_blocks_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = self._fixture(root)
            before_prepare = fixture["harness"].state()
            protected_before = fixture[
                "harness"
            ].runtime._native_goal_protected_state_digest(before_prepare)
            self._prepare(fixture)
            resume_id = "resume-before-generation-commit"
            self.assertTrue(
                fixture["harness"].apply(
                    {
                        "type": "RECORD_STEERING",
                        "steering_id": resume_id,
                        "steering_type": "RESUME",
                        "normalized_digest": digest(resume_id),
                        "identity_algorithm": "message-item-v1",
                        "message_item_id": "resume-before-generation-message",
                        "summary": "resume before recovery commit",
                        "classification_reason": "negative recovery gate test",
                    }
                )["ok"]
            )
            before_resume = persisted_snapshot(root)
            blocked = fixture["harness"].apply(
                {
                    "type": "SET_RUN_CONTROL",
                    "steering_id": resume_id,
                    "requested_status": "RESUME",
                    "reason": "must remain paused",
                }
            )
            self.assertEqual(
                blocked["status"],
                "NATIVE_GOAL_GENERATION_RECONCILIATION_REQUIRED",
            )
            self.assertEqual(persisted_snapshot(root), before_resume)
            prepared_source_heartbeat = copy.deepcopy(
                fixture["harness"].state()[
                    "native_goal_generation_migration"
                ]["source_heartbeat_live_observation"]
            )
            rolled_back = self._rollback(fixture)
            self.assertTrue(rolled_back["ok"], rolled_back)
            state = fixture["harness"].state()
            self.assertIsNone(state["native_goal_generation_migration"])
            self.assertIsNone(state["controller_lease"])
            self.assertEqual(
                state["controller_goal"], before_prepare["controller_goal"]
            )
            self.assertEqual(
                state["native_goal_generation_ledger"],
                before_prepare["native_goal_generation_ledger"],
            )
            self.assertEqual(
                state["heartbeat_routing_gate_enforced"],
                before_prepare["heartbeat_routing_gate_enforced"],
            )
            self.assertEqual(
                state["heartbeat_live_observation"],
                prepared_source_heartbeat,
            )
            self.assertEqual(
                state["native_goal_generation_migration_history"][-1][
                    "outcome"
                ],
                "ROLLED_BACK",
            )
            self.assertEqual(
                fixture[
                    "harness"
                ].runtime._native_goal_protected_state_digest(state),
                protected_before,
            )

    def test_rollback_same_request_replay_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = self._fixture(root)
            self._prepare(fixture)
            rolled_back, request = self._rollback(
                fixture,
                return_request=True,
            )
            self.assertTrue(rolled_back["ok"], rolled_back)
            before_replay = persisted_snapshot(root)
            replay = fixture["harness"].runtime.apply(copy.deepcopy(request))
            self.assertTrue(replay["ok"], replay)
            self.assertEqual(replay["status"], "STATE_WRITE_ALREADY_APPLIED")
            self.assertEqual(persisted_snapshot(root), before_replay)
            history = fixture["harness"].state()[
                "native_goal_generation_migration_history"
            ]
            self.assertEqual(
                [item["migration_id"] for item in history].count(
                    fixture["migration_id"]
                ),
                1,
            )

    def test_commit_and_rollback_crash_recovery_are_atomic(self) -> None:
        cases = (
            ("COMMIT", "NATIVE_GOAL_GENERATION_COMMITTED_PROJECTED"),
            ("COMMIT", "STATE_REPLACED"),
            ("ROLLBACK", "NATIVE_GOAL_GENERATION_ROLLBACK_PROJECTED"),
            ("ROLLBACK", "STATE_REPLACED"),
        )
        for operation, stage in cases:
            with self.subTest(operation=operation, stage=stage), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = self._fixture(root)
                self._prepare(fixture)
                crashing = state_runtime_module.AdaptiveStateRuntime(
                    root,
                    crash_at=stage,
                    native_goal_rollout_roots=(root.resolve(),),
                )
                captured: dict[str, Any] = {}
                original_apply = crashing.apply

                def capturing_apply(
                    request: dict[str, Any],
                    **kwargs: Any,
                ) -> dict[str, Any]:
                    captured["request"] = copy.deepcopy(request)
                    return original_apply(request, **kwargs)

                crashing.apply = capturing_apply  # type: ignore[method-assign]
                with self.assertRaises(state_runtime_module.InjectedCrash):
                    if operation == "COMMIT":
                        self._commit(fixture, runtime=crashing)
                    else:
                        self._rollback(fixture, runtime=crashing)
                recovered = state_runtime_module.AdaptiveStateRuntime(
                    root,
                    native_goal_rollout_roots=(root.resolve(),),
                )
                self.assertTrue(recovered.recover()["ok"])
                replay = recovered.apply(captured["request"])
                self.assertTrue(replay["ok"], replay)
                state = recovered.read_state()
                assert state is not None
                self.assertIsNone(state["controller_lease"])
                if operation == "COMMIT":
                    self.assertEqual(
                        state["native_goal_generation_migration"]["status"],
                        "COMMITTED",
                    )
                else:
                    self.assertIsNone(
                        state["native_goal_generation_migration"]
                    )
                    self.assertEqual(
                        state["native_goal_generation_migration_history"][-1][
                            "outcome"
                        ],
                        "ROLLED_BACK",
                    )

    def test_rollback_rejects_any_started_create_invocation(self) -> None:
        for options in (
            {"add_started_create": True},
            {"add_create_after_observation": True},
            {"add_create_after_final_null": True},
        ):
            with (
                self.subTest(options=options),
                tempfile.TemporaryDirectory() as temporary,
            ):
                fixture = self._fixture(Path(temporary))
                self._prepare(fixture)
                rejected = self._rollback(fixture, **options)
                self.assertIn(
                    rejected["status"],
                    {
                        "NATIVE_GOAL_GENERATION_ROLLBACK_INVOCATION_UNCERTAIN",
                        "NATIVE_GOAL_ROLLOUT_FINAL_EOF_CHANGED",
                    },
                )
                self.assertEqual(
                    fixture["harness"].state()[
                        "native_goal_generation_migration"
                    ]["status"],
                    "PREPARED",
                )

    def test_rollout_started_with_null_goal_is_outcome_unknown_not_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self._fixture(Path(temporary))
            self._prepare(fixture)
            harness = fixture["harness"]
            prepared = harness.state()["native_goal_generation_migration"]
            outbox = prepared["create_outbox"]
            fixture["rollout"].add_create_goal(
                "phase-b-create-turn",
                fixture["objective"],
                self._active_goal(fixture),
                include_output=False,
            )
            _, rollout_artifact = fixture["rollout"].observation_artifact(
                root=harness.root,
                stem="started-unknown-rollout",
                mode="CREATE_GOAL",
                observed_at=T4,
                scan_start_offset=outbox["prepare_high_watermark"],
                expected_objective_digest=outbox["payload_digest"],
                expected_objective_bytes_digest=outbox[
                    "objective_bytes_digest"
                ],
            )
            fixture["rollout"].add_get_goal("rollback-null-one", None)
            _, null_one = fixture["rollout"].observation_artifact(
                root=harness.root,
                stem="rollback-null-one",
                mode="GET_GOAL",
                observed_at=T4,
                scan_start_offset=outbox["prepare_high_watermark"],
            )
            fixture["rollout"].add_get_goal("rollback-null-two", None)
            _, null_two = fixture["rollout"].observation_artifact(
                root=harness.root,
                stem="rollback-null-two",
                mode="GET_GOAL",
                observed_at=T5,
                scan_start_offset=outbox["prepare_high_watermark"],
            )
            acquired, _ = self._acquire_recovery(
                fixture,
                scope="NATIVE_GOAL_GENERATION_ROLLBACK",
                turn_id="rollback-turn-c",
                observed_at=T4,
            )
            self.assertTrue(acquired["ok"], acquired)
            _, heartbeat_artifact = self._heartbeat_artifact(
                harness,
                stem="state-writer-rollback-heartbeat",
                observed_at=T4,
            )
            mutation = {
                "type": "ROLLBACK_NATIVE_GOAL_GENERATION_MIGRATION",
                "lease_claim": acquired["result"]["lease_claim"],
                "migration_id": fixture["migration_id"],
                "null_observation_paths": [null_one["path"], null_two["path"]],
                "rollout_observation_path": rollout_artifact["path"],
                "heartbeat_observation": json.loads(
                    heartbeat_artifact["content"]
                ),
                "automation_observation_path": heartbeat_artifact["path"],
                "automation_observation_digest": heartbeat_artifact["digest"],
                "rollback_reason": "must not be accepted",
                "observed_at": T4,
            }
            rejected, _ = self._state_writer_apply(
                harness,
                mutation,
                occurred_at=T4,
                artifacts=[
                    rollout_artifact,
                    null_one,
                    null_two,
                    heartbeat_artifact,
                ],
            )
            self.assertEqual(
                rejected["status"],
                "NATIVE_GOAL_GENERATION_ROLLBACK_INVOCATION_UNCERTAIN",
            )
            self.assertEqual(
                harness.state()["native_goal_generation_migration"]["status"],
                "PREPARED",
            )

    def test_rollout_observer_rejects_ambiguous_create_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rollout = NativeGoalRolloutFixture(root)
            objective = "body\nmarker"
            rollout.add_create_goal(
                "ambiguous-turn",
                objective,
                {
                    "createdAt": 1,
                    "objective": objective,
                    "status": "active",
                    "threadId": "controller-1",
                    "timeUsedSeconds": 0,
                    "tokensUsed": 0,
                    "updatedAt": 1,
                },
                ambiguous_source=True,
            )
            observed = observe_native_goal_rollout(
                rollout_path=rollout.path,
                controller_thread_id="controller-1",
                mode="CREATE_GOAL",
                expected_objective_digest=digest("body"),
                expected_objective_bytes_digest=digest(objective),
                trusted_rollout_roots=(root.resolve(),),
            )
            self.assertEqual(observed["invocation_state"], "AMBIGUOUS")

    def test_rollout_observer_treats_exact_wrong_objective_as_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rollout = NativeGoalRolloutFixture(root)
            wrong_objective = "wrong body\n[wrong marker]"
            rollout.add_create_goal(
                "wrong-objective-turn",
                wrong_objective,
                {
                    "createdAt": 2,
                    "objective": wrong_objective,
                    "status": "active",
                    "threadId": "controller-1",
                    "timeUsedSeconds": 0,
                    "tokensUsed": 0,
                    "updatedAt": 2,
                },
            )
            observed = observe_native_goal_rollout(
                rollout_path=rollout.path,
                controller_thread_id="controller-1",
                mode="CREATE_GOAL",
                expected_objective_digest=digest("expected body"),
                expected_objective_bytes_digest=digest(
                    "expected body\n[expected marker]"
                ),
                trusted_rollout_roots=(root.resolve(),),
            )
            self.assertEqual(observed["matching_invocation_count"], 0)
            self.assertEqual(observed["invocation_state"], "AMBIGUOUS")
            self.assertEqual(observed["invocations"], [])

    def test_rollback_refuses_exact_create_with_wrong_objective(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self._fixture(Path(temporary))
            self._prepare(fixture)
            wrong_objective = "wrong body\n[wrong marker]"
            fixture["rollout"].add_create_goal(
                "wrong-objective-create",
                wrong_objective,
                self._active_goal(fixture, objective=wrong_objective),
            )
            rejected = self._rollback(fixture)
            self.assertEqual(
                rejected["status"],
                "NATIVE_GOAL_GENERATION_ROLLBACK_INVOCATION_UNCERTAIN",
            )
            self.assertEqual(
                fixture["harness"].state()[
                    "native_goal_generation_migration"
                ]["status"],
                "PREPARED",
            )

    def test_rollout_observer_accepts_exec_text_object_for_goal_tools(self) -> None:
        """Accept both exact result serializers emitted by Codex exec."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rollout = NativeGoalRolloutFixture(root)
            rollout.add_get_goal("get-real-wrapper", None, direct_text=True)
            get_observation = observe_native_goal_rollout(
                rollout_path=rollout.path,
                controller_thread_id="controller-1",
                mode="GET_GOAL",
                observed_at=T4,
                trusted_rollout_roots=(root.resolve(),),
            )
            self.assertIsNone(get_observation["goal"])
            self.assertEqual(get_observation["turn_id"], "get-real-wrapper")

            objective = "body\n[marker]"
            rollout.add_create_goal(
                "create-real-wrapper",
                objective,
                {
                    "createdAt": 200,
                    "objective": objective,
                    "status": "active",
                    "threadId": "controller-1",
                    "timeUsedSeconds": 0,
                    "tokensUsed": 0,
                    "updatedAt": 200,
                },
                direct_text=True,
            )
            create_observation = observe_native_goal_rollout(
                rollout_path=rollout.path,
                controller_thread_id="controller-1",
                mode="CREATE_GOAL",
                expected_objective_digest=digest("body"),
                expected_objective_bytes_digest=digest(objective),
                observed_at=T4,
                trusted_rollout_roots=(root.resolve(),),
            )
            self.assertEqual(create_observation["invocation_state"], "COMPLETED")
            self.assertEqual(create_observation["matching_invocation_count"], 1)

    def test_post_readback_control_tool_names_are_exact_not_suffixes(self) -> None:
        route_arguments = {
            "root": "/tmp/project",
            "request": {
                "mutation": {
                    "type": "ACQUIRE_LEASE",
                    "authorization_digest": digest("authorization"),
                    "authorization_steering_id": "steering-1",
                    "controller_pack_digest": digest("pack"),
                    "lease_id": "lease-1",
                    "migration_id": "migration-1",
                    "recovery_scope": "NATIVE_GOAL_GENERATION_COMMIT",
                    "routing_turn_id": "route-1",
                    "state_writer_thread_id": "state-writer-1",
                }
            },
        }
        for tool_name, expected_state in (
            ("route_state_mutation", "NONE"),
            ("mcp__codex_loop_state__route_state_mutation", "NONE"),
            ("arbitrary_route_state_mutation", "AMBIGUOUS"),
        ):
            with self.subTest(tool_name=tool_name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                rollout = NativeGoalRolloutFixture(root)
                objective = "body\n[marker]"
                rollout.add_get_goal("readback-turn", None)
                readback = observe_native_goal_rollout(
                    rollout_path=rollout.path,
                    controller_thread_id="controller-1",
                    mode="GET_GOAL",
                    observed_at=T4,
                    trusted_rollout_roots=(root.resolve(),),
                )
                rollout.add_raw_tool_call(
                    "control-turn",
                    source=json.dumps(
                        route_arguments, sort_keys=True, separators=(",", ":")
                    ),
                    tool_name=tool_name,
                )
                observed = observe_native_goal_rollout(
                    rollout_path=rollout.path,
                    controller_thread_id="controller-1",
                    mode="GET_GOAL",
                    scan_start_offset=0,
                    control_suffix_start_offset=readback["turn_end_offset"],
                    expected_objective_digest=digest("body"),
                    expected_objective_bytes_digest=digest(objective),
                    observed_at=T4,
                    trusted_rollout_roots=(root.resolve(),),
                )
                self.assertEqual(
                    observed["create_window"]["invocation_state"],
                    expected_state,
                )

    def test_post_readback_exec_wrapper_tool_name_is_exact_not_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rollout = NativeGoalRolloutFixture(root)
            objective = "body\n[marker]"
            rollout.add_get_goal("readback-turn", None)
            readback = observe_native_goal_rollout(
                rollout_path=rollout.path,
                controller_thread_id="controller-1",
                mode="GET_GOAL",
                observed_at=T4,
                trusted_rollout_roots=(root.resolve(),),
            )
            rollout.add_raw_tool_call(
                "control-turn",
                source=(
                    "const result = await "
                    "tools.arbitrary_route_state_mutation({});\n"
                    "text(JSON.stringify(result));"
                ),
            )
            observed = observe_native_goal_rollout(
                rollout_path=rollout.path,
                controller_thread_id="controller-1",
                mode="GET_GOAL",
                control_suffix_start_offset=readback["turn_end_offset"],
                expected_objective_digest=digest("body"),
                expected_objective_bytes_digest=digest(objective),
                observed_at=T4,
                trusted_rollout_roots=(root.resolve(),),
            )
            self.assertEqual(
                observed["create_window"]["invocation_state"],
                "AMBIGUOUS",
            )

    def test_capture_rejects_historical_cutoff_and_replay_binds_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rollout = NativeGoalRolloutFixture(root)
            objective = "body\n[marker]"
            goal = {
                "createdAt": 200,
                "objective": objective,
                "status": "active",
                "threadId": "controller-1",
                "timeUsedSeconds": 0,
                "tokensUsed": 0,
                "updatedAt": 200,
            }
            rollout.add_create_goal("phase-b", objective, goal)
            captured = observe_native_goal_rollout(
                rollout_path=rollout.path,
                controller_thread_id="controller-1",
                mode="CREATE_GOAL",
                expected_objective_digest=digest("body"),
                expected_objective_bytes_digest=digest(objective),
                observed_at=T4,
                trusted_rollout_roots=(root.resolve(),),
            )
            rollout.add_get_goal("phase-c", goal)
            with self.assertRaises(NativeGoalObservationError) as caught:
                observe_native_goal_rollout(
                    rollout_path=rollout.path,
                    controller_thread_id="controller-1",
                    mode="CREATE_GOAL",
                    scan_end_offset=captured["scan_end_offset"],
                    expected_objective_digest=digest("body"),
                    expected_objective_bytes_digest=digest(objective),
                    observed_at=T4,
                    trusted_rollout_roots=(root.resolve(),),
                )
            self.assertEqual(
                caught.exception.code,
                "NATIVE_GOAL_ROLLOUT_HISTORICAL_CUTOFF_FORBIDDEN",
            )
            replayed = observe_native_goal_rollout(
                rollout_path=rollout.path,
                controller_thread_id="controller-1",
                mode="CREATE_GOAL",
                scan_end_offset=captured["scan_end_offset"],
                historical_replay_snapshot_digest=captured[
                    "snapshot_digest"
                ],
                expected_objective_digest=digest("body"),
                expected_objective_bytes_digest=digest(objective),
                observed_at=T4,
                trusted_rollout_roots=(root.resolve(),),
            )
            self.assertEqual(replayed, captured)

            with self.assertRaises(NativeGoalObservationError) as caught:
                observe_native_goal_rollout(
                    rollout_path=rollout.path,
                    controller_thread_id="controller-1",
                    mode="CREATE_GOAL",
                    scan_end_offset=captured["scan_end_offset"],
                    historical_replay_snapshot_digest=digest("wrong prefix"),
                    expected_objective_digest=digest("body"),
                    expected_objective_bytes_digest=digest(objective),
                    observed_at=T4,
                    trusted_rollout_roots=(root.resolve(),),
                )
            self.assertEqual(
                caught.exception.code,
                "NATIVE_GOAL_ROLLOUT_APPEND_ONLY_CONTINUITY_INVALID",
            )

    def test_rollout_observer_rejects_non_exact_javascript_wrappers(self) -> None:
        objective = "body\n[marker]"
        unsafe_sources = {
            "promise-all": (
                "const result = await Promise.all([tools.get_goal({}),"
                "tools.create_goal({\"objective\":\"body\\n[marker]\"})]);\n"
                "text(result);"
            ),
            "multiple-goal-calls": (
                "const first = await tools.get_goal({});\n"
                "const result = await tools.create_goal("
                "{\"objective\":\"body\\n[marker]\"});\ntext(result);"
            ),
            "alias": (
                "const create = tools.create_goal;\n"
                "const result = await create("
                "{\"objective\":\"body\\n[marker]\"});\ntext(result);"
            ),
            "computed-property": (
                "const result = await tools['create_goal']("
                "{\"objective\":\"body\\n[marker]\"});\ntext(result);"
            ),
            "dynamic-call": (
                "const name = 'create_goal';\n"
                "const result = await tools[name]("
                "{\"objective\":\"body\\n[marker]\"});\ntext(result);"
            ),
            "extra-statement": (
                "const audit = 'extra';\n"
                "const result = await tools.create_goal("
                "{\"objective\":\"body\\n[marker]\"});\ntext(result);"
            ),
            "extra-side-effect": (
                "const result = await tools.create_goal("
                "{\"objective\":\"body\\n[marker]\"});\n"
                "notify('side-effect');\ntext(result);"
            ),
            "string-only": "text('tools.create_goal({})');",
            "comment-only": (
                "// tools.create_goal({})\n"
                "const result = await tools.get_goal({});\ntext(result);"
            ),
        }
        for name, source in unsafe_sources.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                rollout = NativeGoalRolloutFixture(root)
                rollout.add_raw_tool_call(
                    f"unsafe-{name}",
                    source=source,
                    result={"goal": None},
                )
                observed = observe_native_goal_rollout(
                    rollout_path=rollout.path,
                    controller_thread_id="controller-1",
                    mode="CREATE_GOAL",
                    expected_objective_digest=digest("body"),
                    expected_objective_bytes_digest=digest(objective),
                    trusted_rollout_roots=(root.resolve(),),
                )
                self.assertEqual(observed["invocation_state"], "AMBIGUOUS")
                with self.assertRaises(NativeGoalObservationError) as caught:
                    observe_native_goal_rollout(
                        rollout_path=rollout.path,
                        controller_thread_id="controller-1",
                        mode="GET_GOAL",
                        trusted_rollout_roots=(root.resolve(),),
                    )
                self.assertEqual(
                    caught.exception.code,
                    "NATIVE_GOAL_GET_GOAL_OBSERVATION_UNAVAILABLE",
                )

    def test_rollout_observer_rejects_non_strict_or_unauthorized_arguments(self) -> None:
        objective = "body\n[marker]"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rollout = NativeGoalRolloutFixture(root)
            rollout.add_raw_tool_call(
                "non-strict-json",
                source=(
                    "const result = await tools.create_goal("
                    "{objective:'body\\n[marker]'});\ntext(result);"
                ),
            )
            with self.assertRaises(NativeGoalObservationError) as caught:
                observe_native_goal_rollout(
                    rollout_path=rollout.path,
                    controller_thread_id="controller-1",
                    mode="CREATE_GOAL",
                    trusted_rollout_roots=(root.resolve(),),
                )
            self.assertEqual(
                caught.exception.code,
                "NATIVE_GOAL_CREATE_INVOCATION_INVALID",
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rollout = NativeGoalRolloutFixture(root)
            arguments = json.dumps(
                {"objective": objective, "token_budget": 1},
                separators=(",", ":"),
            )
            rollout.add_raw_tool_call(
                "unauthorized-token-budget",
                source=(
                    f"const result = await tools.create_goal({arguments});\n"
                    "text(result);"
                ),
            )
            observed = observe_native_goal_rollout(
                rollout_path=rollout.path,
                controller_thread_id="controller-1",
                mode="CREATE_GOAL",
                expected_objective_digest=digest("body"),
                expected_objective_bytes_digest=digest(objective),
                trusted_rollout_roots=(root.resolve(),),
            )
            self.assertEqual(observed["invocation_state"], "AMBIGUOUS")

    def test_rollout_observer_requires_one_goal_call_per_real_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rollout = NativeGoalRolloutFixture(root)
            get_source = (
                "const result = await tools.get_goal({});\n"
                "text(JSON.stringify(result));"
            )
            result = {
                "goal": None,
                "remainingTokens": None,
                "completionBudgetReport": None,
            }
            rollout.add_raw_tool_call(
                "two-tools",
                source=get_source,
                result=result,
                complete_turn=False,
            )
            rollout.add_raw_tool_call(
                "two-tools",
                source=get_source,
                result=result,
                start_turn=False,
            )
            with self.assertRaises(NativeGoalObservationError) as caught:
                observe_native_goal_rollout(
                    rollout_path=rollout.path,
                    controller_thread_id="controller-1",
                    mode="GET_GOAL",
                    trusted_rollout_roots=(root.resolve(),),
                )
            self.assertEqual(
                caught.exception.code,
                "NATIVE_GOAL_GET_GOAL_OBSERVATION_UNAVAILABLE",
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rollout = NativeGoalRolloutFixture(root)
            rollout.add_raw_tool_call(
                "missing-turn",
                source=(
                    "const result = await tools.get_goal({});\n"
                    "text(result);"
                ),
                result={"goal": None},
                start_turn=False,
            )
            with self.assertRaises(NativeGoalObservationError) as caught:
                observe_native_goal_rollout(
                    rollout_path=rollout.path,
                    controller_thread_id="controller-1",
                    mode="GET_GOAL",
                    trusted_rollout_roots=(root.resolve(),),
                )
            self.assertEqual(
                caught.exception.code,
                "NATIVE_GOAL_GET_GOAL_OBSERVATION_UNAVAILABLE",
            )

    def test_rollout_observer_rejects_direct_goal_tool_call(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rollout = NativeGoalRolloutFixture(root)
            rollout.add_raw_tool_call(
                "direct-create",
                source="",
                tool_name="create_goal",
            )
            observed = observe_native_goal_rollout(
                rollout_path=rollout.path,
                controller_thread_id="controller-1",
                mode="CREATE_GOAL",
                trusted_rollout_roots=(root.resolve(),),
            )
            self.assertEqual(observed["invocation_state"], "AMBIGUOUS")

    def test_rollout_observer_persists_started_and_completed_invocations(self) -> None:
        for include_output, expected in (
            (False, "STARTED_UNKNOWN"),
            (True, "COMPLETED"),
        ):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                rollout = NativeGoalRolloutFixture(root)
                objective = "body\n[marker]"
                rollout.add_create_goal(
                    "phase-b-real-turn",
                    objective,
                    {
                        "createdAt": 200,
                        "objective": objective,
                        "status": "active",
                        "threadId": "controller-1",
                        "timeUsedSeconds": 0,
                        "tokensUsed": 0,
                        "updatedAt": 200,
                    },
                    include_output=include_output,
                )
                observed = observe_native_goal_rollout(
                    rollout_path=rollout.path,
                    controller_thread_id="controller-1",
                    mode="CREATE_GOAL",
                    expected_objective_digest=digest("body"),
                    expected_objective_bytes_digest=digest(objective),
                    observed_at=T4,
                    trusted_rollout_roots=(root.resolve(),),
                )
                self.assertEqual(observed["invocation_state"], expected)
                self.assertEqual(observed["matching_invocation_count"], 1)
                observed_again = observe_native_goal_rollout(
                    rollout_path=rollout.path,
                    controller_thread_id="controller-1",
                    mode="CREATE_GOAL",
                    expected_objective_digest=digest("body"),
                    expected_objective_bytes_digest=digest(objective),
                    observed_at=T4,
                    trusted_rollout_roots=(root.resolve(),),
                )
                self.assertEqual(observed_again, observed)

    def test_synthetic_restart_readback_remains_auditable_but_cli_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / "codex-home"
            rollout_root = codex_home / "sessions"
            rollout_root.mkdir(parents=True)
            rollout = NativeGoalRolloutFixture(rollout_root)
            objective = "private objective body\n[private marker]"
            goal = {
                "createdAt": 200,
                "objective": objective,
                "status": "active",
                "threadId": "controller-1",
                "timeUsedSeconds": 3,
                "tokensUsed": 7,
                "updatedAt": 201,
            }
            rollout.add_get_goal("post-restart-readback", goal)
            first = observe_native_goal_rollout(
                rollout_path=rollout.path,
                controller_thread_id="controller-1",
                mode="GET_GOAL",
                observed_at=T4,
                trusted_rollout_roots=(rollout_root.resolve(),),
            )
            second = observe_native_goal_rollout(
                rollout_path=rollout.path,
                controller_thread_id="controller-1",
                mode="GET_GOAL",
                observed_at=T4,
                trusted_rollout_roots=(rollout_root.resolve(),),
            )
            self.assertEqual(first, second)
            with mock.patch.dict(
                os.environ, {"CODEX_HOME": str(codex_home)}
            ):
                default_root_observation = observe_native_goal_rollout(
                    rollout_path=rollout.path,
                    controller_thread_id="controller-1",
                    mode="GET_GOAL",
                    observed_at=T4,
                )
            self.assertEqual(default_root_observation, first)
            request = {
                "rollout_path": str(rollout.path),
                "controller_thread_id": "controller-1",
                "observation_mode": "GET_GOAL",
                "expected_objective_digest": digest("private objective body"),
                "expected_objective_bytes_digest": digest(objective),
                "observed_at": T4,
                "observation_path": (
                    ".codex-loop/reports/cli-native-goal-readback.json"
                ),
            }
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "adaptive_state_runtime.py"),
                    "--native-goal-observe",
                    "--root",
                    str(root),
                ],
                input=json.dumps(request, separators=(",", ":")),
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
                env={**os.environ, "CODEX_HOME": str(codex_home)},
            )
            self.assertNotEqual(completed.returncode, 0)
            response = json.loads(completed.stdout)
            self.assertEqual(
                response["status"],
                "NATIVE_GOAL_GENERATION_RECOVERY_UNAVAILABLE",
            )
            self.assertEqual(
                response["error"]["details"],
                {
                    "availability": "DEFERRED_UNAVAILABLE",
                    "side_effects": "NONE",
                },
            )
            self.assertFalse((root / request["observation_path"]).exists())
            self.assertNotIn(objective, completed.stdout)

    def test_rollout_observer_rejects_symlink_and_partial_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rollout = NativeGoalRolloutFixture(root)
            symlink = root / "rollout-link.jsonl"
            symlink.symlink_to(rollout.path)
            with self.assertRaises(NativeGoalObservationError) as caught:
                observe_native_goal_rollout(
                    rollout_path=symlink,
                    controller_thread_id="controller-1",
                    mode="GET_GOAL",
                    trusted_rollout_roots=(root.resolve(),),
                )
            self.assertEqual(caught.exception.code, "NATIVE_GOAL_ROLLOUT_PATH_INVALID")
            trusted_root = root / "trusted-rollouts"
            trusted_root.mkdir()
            with self.assertRaises(NativeGoalObservationError) as caught:
                observe_native_goal_rollout(
                    rollout_path=rollout.path,
                    controller_thread_id="controller-1",
                    mode="GET_GOAL",
                    trusted_rollout_roots=(trusted_root.resolve(),),
                )
            self.assertEqual(
                caught.exception.code,
                "NATIVE_GOAL_ROLLOUT_PATH_INVALID",
            )
            with rollout.path.open("ab") as handle:
                handle.write(b'{"type":')
            with self.assertRaises(NativeGoalObservationError) as caught:
                observe_native_goal_rollout(
                    rollout_path=rollout.path,
                    controller_thread_id="controller-1",
                    mode="GET_GOAL",
                    trusted_rollout_roots=(root.resolve(),),
                )
            self.assertEqual(
                caught.exception.code, "NATIVE_GOAL_ROLLOUT_PARSE_INCOMPLETE"
            )

    def test_rollout_open_rejects_final_component_symlink_swap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            rollout = NativeGoalRolloutFixture(root)
            rollout.add_get_goal("stable-get", None)
            original = rollout.path.with_suffix(".original")
            real_open = os.open
            swapped = False

            def swap_before_final_open(
                path: str | bytes,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal swapped
                if path == rollout.path.name and dir_fd is not None and not swapped:
                    swapped = True
                    rollout.path.rename(original)
                    rollout.path.symlink_to(original.name)
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch.object(
                native_goal_observer.os,
                "open",
                side_effect=swap_before_final_open,
            ):
                with self.assertRaises(NativeGoalObservationError) as caught:
                    observe_native_goal_rollout(
                        rollout_path=rollout.path,
                        controller_thread_id="controller-1",
                        mode="GET_GOAL",
                        trusted_rollout_roots=(root,),
                    )
            self.assertTrue(swapped)
            self.assertEqual(
                caught.exception.code,
                "NATIVE_GOAL_ROLLOUT_PATH_INVALID",
            )

    def test_rollout_observer_rejects_concurrent_append_owner_and_thread_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rollout = NativeGoalRolloutFixture(root)
            rollout.add_get_goal("stable-get", None)
            real_fstat = os.fstat
            fstat_calls = 0

            def append_before_second_fstat(fd: int) -> os.stat_result:
                nonlocal fstat_calls
                fstat_calls += 1
                if fstat_calls == 2:
                    with rollout.path.open("ab") as handle:
                        handle.write(b'{"payload":{},"type":"event_msg"}\n')
                return real_fstat(fd)

            with mock.patch.object(
                native_goal_observer.os,
                "fstat",
                side_effect=append_before_second_fstat,
            ):
                with self.assertRaises(NativeGoalObservationError) as caught:
                    observe_native_goal_rollout(
                        rollout_path=rollout.path,
                        controller_thread_id="controller-1",
                        mode="GET_GOAL",
                        trusted_rollout_roots=(root.resolve(),),
                    )
            self.assertEqual(
                caught.exception.code,
                "NATIVE_GOAL_ROLLOUT_CONCURRENT_CHANGE",
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rollout = NativeGoalRolloutFixture(root)
            with mock.patch.object(
                native_goal_observer.os,
                "getuid",
                return_value=os.getuid() + 1,
            ):
                with self.assertRaises(NativeGoalObservationError) as caught:
                    observe_native_goal_rollout(
                        rollout_path=rollout.path,
                        controller_thread_id="controller-1",
                        mode="GET_GOAL",
                        trusted_rollout_roots=(root.resolve(),),
                    )
            self.assertEqual(
                caught.exception.code,
                "NATIVE_GOAL_ROLLOUT_IDENTITY_INVALID",
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rollout = NativeGoalRolloutFixture(root, thread_id="controller-1")
            with self.assertRaises(NativeGoalObservationError) as caught:
                observe_native_goal_rollout(
                    rollout_path=rollout.path,
                    controller_thread_id="wrong-controller",
                    mode="GET_GOAL",
                    trusted_rollout_roots=(root.resolve(),),
                )
            self.assertEqual(
                caught.exception.code,
                "NATIVE_GOAL_ROLLOUT_THREAD_IDENTITY_INVALID",
            )


if __name__ == "__main__":
    unittest.main()
