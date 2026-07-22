from __future__ import annotations

from state_runtime_support import *  # noqa: F403
from loop_architect.state_runtime import RuntimeRejection


class FormalStartupReceiptTests(AdaptiveStateRuntimeTestCase):  # noqa: F405
    def _startup_request(
        self, target: Path, *, strict_model_identity: bool = False
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        with tempfile.TemporaryDirectory() as seed:
            _, request = Harness(Path(seed)).initialize()
        role_digests = (
            [digest(f"role-{index}") for index in range(3)]
            if strict_model_identity
            else []
        )
        receipt = {
            "schema_version": "formal-startup-receipt-v1",
            "issuer": "CODEX_APP_HOST",
            "evidence_model": "HOST_COOPERATIVE",
            "compiled_manifest_digest": digest("compiled"),
            "doctor_identity_digest": digest("doctor"),
            "canary_receipt_digest": digest("canary"),
            "canary_final_status": "FINALIZATION_ACKED",
            "host_capability_receipt_digest": digest("host"),
            "role_receipt_digests": role_digests,
            "heartbeat_receipt_digest": digest("heartbeat"),
            "registry_complete": True,
            "mcp_lifecycle_supported": True,
            "model_identity_requirement": (
                "REQUIRED" if strict_model_identity else "NOT_REQUIRED"
            ),
            "model_identity_status": (
                "VERIFIED" if strict_model_identity else "NOT_APPLICABLE"
            ),
            "required_model": "strict-model" if strict_model_identity else "UNSPECIFIED",
            "required_reasoning": "high" if strict_model_identity else "UNSPECIFIED",
        }
        receipt["receipt_digest"] = json_digest(receipt)
        content = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
        artifact = {
            "path": ".codex-loop/sources/STARTUP_RECEIPT.json",
            "content": content,
            "digest": digest(content),
            "media_type": "application/json",
        }
        request["mutation"].update(
            {
                "initialization_class": "FORMAL",
                "startup_receipt_path": artifact["path"],
                "startup_receipt_digest": artifact["digest"],
                "model_identity_requirement": receipt["model_identity_requirement"],
                "required_model": receipt["required_model"],
                "required_reasoning": receipt["required_reasoning"],
            }
        )
        request["artifacts"].append(artifact)
        request["evidence_paths"].append(artifact["path"])
        return request, receipt

    def test_formal_initialization_fails_closed_without_finalized_canary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, _ = self._startup_request(root)
            startup = json.loads(request["artifacts"][1]["content"])
            startup["canary_final_status"] = "FAILED"
            body = dict(startup)
            body.pop("receipt_digest")
            startup["receipt_digest"] = json_digest(body)
            content = json.dumps(startup, sort_keys=True, separators=(",", ":"))
            request["artifacts"][1]["content"] = content
            request["artifacts"][1]["digest"] = digest(content)
            request["mutation"]["startup_receipt_digest"] = digest(content)
            response = AdaptiveStateRuntime(root).apply(request)
            self.assertEqual("FORMAL_STARTUP_RECEIPT_INVALID", response["status"])
            self.assertIsNone(AdaptiveStateRuntime(root).read_state())

    def test_formal_initialization_persists_only_digested_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, receipt = self._startup_request(root)
            response = AdaptiveStateRuntime(root).apply(request)
            self.assertTrue(response["ok"], response)
            state = AdaptiveStateRuntime(root).read_state()
            self.assertEqual("FORMAL", state["initialization_class"])
            self.assertEqual(
                receipt["canary_receipt_digest"],
                state["startup_receipt"]["canary_receipt_digest"],
            )
            self.assertNotIn("raw_prompt", state["startup_receipt"])
            self.assertEqual("NOT_REQUIRED", state["model_identity_requirement"])
            self.assertEqual("NOT_APPLICABLE", state["model_identity_status"])

    def test_formal_default_registers_task_without_model_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, _ = self._startup_request(root)
            runtime = AdaptiveStateRuntime(root)
            initialized = runtime.apply(request)
            self.assertTrue(initialized["ok"], initialized)
            state = runtime.read_state()
            result = runtime._gateway_register_task(
                state,
                {"artifacts": [], "evidence_paths": []},
                {
                    "thread_id": "worker-default",
                    "role_kind": "WORKER",
                    "bootstrap_role_kind": "implementation",
                    "bootstrap_prompt_digest": digest("worker-bootstrap"),
                    "worktree_path": str(root.resolve()),
                },
            )
            self.assertEqual("GATEWAY_TASK_REGISTERED", result["code"])
            record = state["thread_registry"]["worker-default"]
            self.assertEqual("UNSPECIFIED", record["model"])
            self.assertEqual("UNSPECIFIED", record["reasoning"])
            self.assertEqual("NOT_APPLICABLE", record["model_identity_status"])
            status = runtime._render_status(state).decode("utf-8")
            self.assertIn("Model identity requirement: `NOT_REQUIRED`", status)
            self.assertIn("Model identity status: `NOT_APPLICABLE`", status)
            state["dashboard_required"] = True
            dashboard = runtime._render_dashboard(state).decode("utf-8")
            self.assertIn("Model identity requirement:</strong> NOT_REQUIRED", dashboard)
            self.assertIn("Model identity status:</strong> NOT_APPLICABLE", dashboard)

    def test_strict_model_identity_requires_host_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, _ = self._startup_request(root, strict_model_identity=True)
            runtime = AdaptiveStateRuntime(root)
            initialized = runtime.apply(request)
            self.assertTrue(initialized["ok"], initialized)
            state = runtime.read_state()
            with self.assertRaisesRegex(RuntimeRejection, "STATE_GATEWAY_REQUEST_INVALID"):
                runtime._gateway_register_task(
                    state,
                    {"artifacts": [], "evidence_paths": []},
                    {
                        "thread_id": "worker-strict",
                        "role_kind": "WORKER",
                        "bootstrap_role_kind": "implementation",
                        "bootstrap_prompt_digest": digest("worker-bootstrap"),
                        "worktree_path": str(root.resolve()),
                    },
                )

    def test_legacy_formal_receipt_remains_strict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, _ = self._startup_request(root, strict_model_identity=True)
            startup = json.loads(request["artifacts"][1]["content"])
            for field in (
                "model_identity_requirement", "model_identity_status",
                "required_model", "required_reasoning",
            ):
                startup.pop(field)
            body = dict(startup)
            body.pop("receipt_digest")
            startup["receipt_digest"] = json_digest(body)
            content = json.dumps(startup, sort_keys=True, separators=(",", ":"))
            request["artifacts"][1]["content"] = content
            request["artifacts"][1]["digest"] = digest(content)
            request["mutation"]["startup_receipt_digest"] = digest(content)
            for field in (
                "model_identity_requirement", "required_model", "required_reasoning",
            ):
                request["mutation"].pop(field)
            runtime = AdaptiveStateRuntime(root)
            initialized = runtime.apply(request)
            self.assertTrue(initialized["ok"], initialized)
            self.assertEqual("REQUIRED", runtime.read_state()["model_identity_requirement"])

    def test_formal_initialization_rejects_unsigned_app_signed_label(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, _ = self._startup_request(root)
            startup = json.loads(request["artifacts"][1]["content"])
            startup["evidence_model"] = "APP_SIGNED"
            body = dict(startup)
            body.pop("receipt_digest")
            startup["receipt_digest"] = json_digest(body)
            content = json.dumps(startup, sort_keys=True, separators=(",", ":"))
            request["artifacts"][1]["content"] = content
            request["artifacts"][1]["digest"] = digest(content)
            request["mutation"]["startup_receipt_digest"] = digest(content)
            response = AdaptiveStateRuntime(root).apply(request)
            self.assertEqual("FORMAL_STARTUP_RECEIPT_INVALID", response["status"])
            self.assertIsNone(AdaptiveStateRuntime(root).read_state())


class PolicyMigrationFrameworkTests(AdaptiveStateRuntimeTestCase):  # noqa: F405
    @staticmethod
    def _descriptor(source: int, target: int, *, action: str) -> dict[str, Any]:
        return {
            "migration_id": "policy-migration-1",
            "policy_path": "/authorization_envelope/repair_policy/max_repair_attempts_per_goal",
            "value_type": "integer",
            "source_value": source,
            "target_value": target,
            "bounds": {"minimum": 0, "maximum": 20},
            "monotonic": "INCREASE_ONLY" if target > source else "DECREASE_ONLY",
            "reversible": True,
            "required_capability": "none",
            "approval": "DECISION_CARD",
            "safe_point": "NO_ACTIVE_OUTBOX",
            "action": action,
            "rollback_or_stop": "ROLLBACK",
        }

    def test_generic_apply_and_rollback_preserve_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = Harness(Path(temporary))
            response, _ = harness.initialize()
            self.assertTrue(response["ok"], response)
            state = harness.state()
            source = state["authorization_envelope"]["repair_policy"][
                "max_repair_attempts_per_goal"
            ]
            apply_descriptor = self._descriptor(source, 10, action="APPLY")
            AdaptiveStateRuntime._apply_policy_descriptor(
                state, apply_descriptor, decision_id="decision-apply", after_version=2
            )
            self.assertEqual(
                10,
                state["authorization_envelope"]["repair_policy"][
                    "max_repair_attempts_per_goal"
                ],
            )
            rollback = self._descriptor(10, source, action="ROLLBACK")
            AdaptiveStateRuntime._apply_policy_descriptor(
                state, rollback, decision_id="decision-rollback", after_version=3
            )
            self.assertEqual(source, state["authorization_envelope"]["repair_policy"]["max_repair_attempts_per_goal"])
            self.assertEqual(["APPLIED", "ROLLED_BACK"], [item["status"] for item in state["policy_migration_history"]])

    def test_stale_source_and_out_of_bounds_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            harness = Harness(Path(temporary))
            response, _ = harness.initialize()
            self.assertTrue(response["ok"], response)
            state = harness.state()
            current = state["authorization_envelope"]["repair_policy"]["max_repair_attempts_per_goal"]
            with self.assertRaisesRegex(RuntimeRejection, "POLICY_MIGRATION_DESCRIPTOR_INVALID"):
                AdaptiveStateRuntime._validate_policy_descriptor(
                    state, self._descriptor(current + 1, 10, action="APPLY")
                )
            source = current
            invalid = self._descriptor(source, 21, action="APPLY")
            with self.assertRaisesRegex(RuntimeRejection, "POLICY_MIGRATION_BOUNDS_INVALID"):
                AdaptiveStateRuntime._validate_policy_descriptor(state, invalid)


class CompletionClassTests(AdaptiveStateRuntimeTestCase):  # noqa: F405
    def test_historical_complete_states_project_without_rewriting_history(self) -> None:
        state = {
            "terminal_status": "LOOP_COMPLETE",
            "goal_definition_registry": {"g1": {}},
            "goal_execution_ledger": {"g1": {"status": "COMPLETE"}},
            "assurance_ledger": {},
        }
        original = copy.deepcopy(state)
        required, achieved = AdaptiveStateRuntime._completion_projection(
            state, "g1", state["goal_execution_ledger"]["g1"]
        )
        self.assertEqual(("COMPLETE_ARTIFACT", "COMPLETE_ARTIFACT"), (required, achieved))
        self.assertEqual(original, state)
        state["terminal_status"] = "LOOP_COMPLETE_WITH_LIMITATION"
        _, achieved = AdaptiveStateRuntime._completion_projection(
            state, "g1", state["goal_execution_ledger"]["g1"]
        )
        self.assertEqual("COMPLETE_WITH_LIMITATION", achieved)

    def test_formal_class_requires_bound_authority_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = AdaptiveStateRuntime(temporary)
            worker = {
                "dispatch_id": "worker-1",
                "artifact_digest": digest("artifact"),
            }
            state = {
                "goal_definition_registry": {
                    "g1": {"required_completion_class": "FORMAL_ACCEPTED"}
                },
                "assurance_ledger": {},
            }
            with self.assertRaisesRegex(RuntimeRejection, "COMPLETION_CLASS_RECEIPT_REQUIRED"):
                runtime._gateway_completion_class(
                    state,
                    {"artifacts": [], "evidence_paths": []},
                    "g1",
                    worker,
                    {"achieved_completion_class": "FORMAL_ACCEPTED"},
                )
            receipt = {
                "schema_version": "completion-evidence-v1",
                "completion_class": "FORMAL_ACCEPTED",
                "goal_id": "g1",
                "artifact_digest": worker["artifact_digest"],
                "issuer_kind": "FORMAL_AUTHORITY",
                "observed_at": T1,
            }
            receipt["receipt_digest"] = json_digest(receipt)
            content = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
            artifact = read_evidence_artifact("formal-acceptance", content)
            achieved, evidence = runtime._gateway_completion_class(
                state,
                {"artifacts": [artifact], "evidence_paths": [artifact["path"]]},
                "g1",
                worker,
                {
                    "achieved_completion_class": "FORMAL_ACCEPTED",
                    "completion_evidence_path": artifact["path"],
                    "completion_evidence_digest": artifact["digest"],
                },
            )
            self.assertEqual("FORMAL_ACCEPTED", achieved)
            self.assertEqual("FORMAL_AUTHORITY", evidence["issuer_kind"])


class GitCloseoutSagaTests(AdaptiveStateRuntimeTestCase):  # noqa: F405
    def _git_root(self, root: Path) -> tuple[str, str]:
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Loop Test"], check=True)
        (root / "product.txt").write_text("before\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "product.txt"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        return head, "main"

    def test_commit_crash_recovery_reuses_prepared_closeout_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            head, branch = self._git_root(root)
            runtime = AdaptiveStateRuntime(root)
            artifact_digest = digest("reviewed-artifact")
            state = {
                "loop_id": "loop-closeout",
                "logical_time": T0,
                "goal_definition_registry": {"g1": {"closeout_required": True}},
                "goal_execution_ledger": {
                    "g1": {
                        "status": "CODE_REVIEW_PASS",
                        "latest_worker": {
                            "status": "PASS",
                            "dispatch_id": "worker-1",
                            "artifact_digest": artifact_digest,
                            "review_handoff": {
                                "artifact_identity": {
                                    "current_branch": branch,
                                    "head_sha": head,
                                    "changed_files": ["product.txt"],
                                }
                            },
                        },
                    }
                },
                "goal_closeout_ledger": {},
            }
            prepared = runtime._gateway_prepare_goal_closeout(
                state,
                {
                    "closeout_id": "closeout-1",
                    "goal_id": "g1",
                    "artifact_digest": artifact_digest,
                    "allowed_paths": ["product.txt"],
                    "observed_at": T1,
                },
                2,
            )
            self.assertEqual("GOAL_CLOSEOUT_PREPARED", prepared["code"])
            (root / "product.txt").write_text("after\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "product.txt"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "result"], check=True)
            prepare_replay = runtime._gateway_prepare_goal_closeout(
                state,
                {
                    "closeout_id": "closeout-1",
                    "goal_id": "g1",
                    "artifact_digest": artifact_digest,
                    "allowed_paths": ["product.txt"],
                    "observed_at": T2,
                },
                3,
            )
            self.assertEqual("GOAL_CLOSEOUT_ALREADY_PREPARED", prepare_replay["code"])
            commit = runtime._git_readback("rev-parse", "HEAD")
            receipt = {
                "status": "COMMITTED",
                "branch": branch,
                "commit": commit,
                "tree": runtime._git_readback("rev-parse", "HEAD^{tree}"),
                "parent": head,
                "remote_ref": "refs/remotes/origin/main",
                "remote_sha": None,
            }
            request = {
                "closeout_id": "closeout-1",
                "goal_id": "g1",
                "observed_at": T2,
                "git_receipt": receipt,
            }
            ack = runtime._gateway_ack_goal_closeout(state, request, 4)
            self.assertEqual("GOAL_CLOSEOUT_ACKED", ack["code"])
            replay = runtime._gateway_ack_goal_closeout(state, request, 5)
            self.assertEqual("GOAL_CLOSEOUT_ALREADY_ACKED", replay["code"])
            self.assertEqual(commit, state["goal_closeout_ledger"]["g1"]["git_receipt"]["commit"])

    def test_no_commit_closeout_rejects_dirty_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            head, branch = self._git_root(root)
            runtime = AdaptiveStateRuntime(root)
            artifact_digest = digest("reviewed-artifact")
            state = {
                "loop_id": "loop-closeout",
                "logical_time": T0,
                "goal_definition_registry": {"g1": {"closeout_required": True}},
                "goal_execution_ledger": {
                    "g1": {
                        "status": "CODE_REVIEW_PASS",
                        "latest_worker": {
                            "status": "PASS",
                            "dispatch_id": "worker-1",
                            "artifact_digest": artifact_digest,
                            "review_handoff": {
                                "artifact_identity": {
                                    "current_branch": branch,
                                    "head_sha": head,
                                    "changed_files": [],
                                }
                            },
                        },
                    }
                },
                "goal_closeout_ledger": {},
            }
            runtime._gateway_prepare_goal_closeout(
                state,
                {
                    "closeout_id": "closeout-no-commit",
                    "goal_id": "g1",
                    "artifact_digest": artifact_digest,
                    "allowed_paths": ["product.txt"],
                    "observed_at": T1,
                },
                2,
            )
            (root / "product.txt").write_text("dirty-after-prepare\n", encoding="utf-8")
            receipt = {
                "status": "NO_COMMIT",
                "branch": branch,
                "commit": head,
                "tree": runtime._git_readback("rev-parse", "HEAD^{tree}"),
                "parent": None,
                "remote_ref": "refs/remotes/origin/main",
                "remote_sha": None,
            }
            with self.assertRaisesRegex(RuntimeRejection, "GOAL_CLOSEOUT_BASELINE_DRIFT"):
                runtime._gateway_ack_goal_closeout(
                    state,
                    {
                        "closeout_id": "closeout-no-commit",
                        "goal_id": "g1",
                        "observed_at": T2,
                        "git_receipt": receipt,
                    },
                    3,
                )


if __name__ == "__main__":
    unittest.main()
