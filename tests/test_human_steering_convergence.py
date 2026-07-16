from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "codex-loop-prompt-architect" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from loop_architect.human_control import (  # noqa: E402
    build_failure_fingerprint,
    canonical_digest,
    classify_failure_progress,
    derive_validation_matrix,
    normalize_failure_lines,
    scope_matches_path,
    validate_review_surface,
)
from loop_architect.state_runtime import (  # noqa: E402
    AdaptiveStateRuntime,
    InjectedCrash,
    PERSISTENT_STAGES,
    RuntimeRejection,
    STATUS_PROJECTION_STAGES,
)
from tests.state_runtime_support import (  # noqa: E402
    Harness,
    authorization_envelope,
    complete_validation_matrix,
    context_identity_delta,
    digest,
    goal,
    goal_definition_digest,
    milestone,
    persisted_snapshot,
    queue_entry,
)
import loop_prompt_scaffold as scaffold  # noqa: E402


class HumanControlHelperTests(unittest.TestCase):
    def test_authorization_objectives_require_security_evidence(self) -> None:
        for objective in (
            "Change authorization middleware",
            "Change access control rules",
            "Add authz checks",
            "修改授权策略",
        ):
            with self.subTest(objective=objective):
                matrix = derive_validation_matrix(
                    objective=objective,
                    validation_commands=["pytest"],
                    has_review_surface=False,
                )
                self.assertTrue(matrix["security"]["required"])

    def test_review_surface_scope_matching_supports_recursive_globs(self) -> None:
        self.assertTrue(scope_matches_path("**/*", "public/reports/a.md"))
        self.assertTrue(
            scope_matches_path("public/**/*.md", "public/reports/a.md")
        )
        self.assertTrue(scope_matches_path("public/**", "public/reports/a.md"))
        self.assertFalse(scope_matches_path("src/**/*.py", "public/reports/a.md"))
        self.assertTrue(scope_matches_path("docs", "docs/review.md"))

    def test_failure_normalization_removes_volatile_and_sensitive_values(self) -> None:
        left = normalize_failure_lines(
            ["2026-01-01T00:00:00Z pid=123 http://localhost:49152 token=secret boom"]
        )
        right = normalize_failure_lines(
            ["2027-02-02T01:01:01Z pid=999 http://localhost:3000 token=other boom"]
        )
        self.assertEqual(left, right)
        self.assertNotIn("token=secret", left[0])
        self.assertNotEqual(
            normalize_failure_lines(["src/a.py:12: AssertionError"]),
            normalize_failure_lines(["src/a.py:34: AssertionError"]),
        )

    def test_failure_classification_is_deterministic(self) -> None:
        current = build_failure_fingerprint(
            command="pytest",
            exit_code=1,
            output_lines=["FAILED test_x"],
            failing_test_ids=["test_x"],
            changed_files=["src/x.py"],
            diff_digest=digest("diff"),
            strategy_id="strategy-a",
            hypothesis_digest=digest("hypothesis"),
            raw_log_digest=digest("raw"),
        )
        self.assertEqual(
            classify_failure_progress([current], current, same_strategy_threshold=2),
            "THRASHING_DETECTED",
        )
        regressed = {**current, "previously_passing_tests_regressed": ["test_old"]}
        self.assertEqual(
            classify_failure_progress([], regressed, same_strategy_threshold=2),
            "REGRESSION_INTRODUCED",
        )
        different_command = {**current, "command_digest": digest("different-command")}
        self.assertEqual(
            classify_failure_progress([current], different_command, same_strategy_threshold=2),
            "PROGRESSING",
        )
        unrelated = {**current, "normalized_lines_digest": digest("other-failure")}
        self.assertEqual(
            classify_failure_progress(
                [current, unrelated], current, same_strategy_threshold=2
            ),
            "POSSIBLE_STRATEGY_REPEAT",
        )
        changed_diff = {
            **current,
            "diff_digest": digest("different-diff"),
            "changed_files": ["src/y.py"],
        }
        self.assertEqual(
            classify_failure_progress(
                [current], changed_diff, same_strategy_threshold=2
            ),
            "POSSIBLE_STRATEGY_REPEAT",
        )
        self.assertEqual(
            classify_failure_progress(
                [current],
                current,
                same_strategy_threshold=2,
                strategy_budget_exhausted=True,
            ),
            "STRATEGY_EXHAUSTED",
        )

    def test_validation_matrix_risk_escalation(self) -> None:
        matrix = derive_validation_matrix(
            objective="Change auth API and frontend interaction",
            validation_commands=["pytest"],
            has_review_surface=True,
        )
        self.assertTrue(matrix["security"]["required"])
        self.assertTrue(matrix["compatibility"]["required"])
        self.assertTrue(matrix["user_experience"]["required"])
        plain = derive_validation_matrix(
            objective="Maintain build requirements and explain details",
            validation_commands=["pytest"],
            has_review_surface=False,
        )
        self.assertFalse(plain["security"]["required"])
        self.assertFalse(plain["compatibility"]["required"])
        self.assertFalse(plain["user_experience"]["required"])
        for objective in ("Security hardening", "安全加固"):
            with self.subTest(objective=objective):
                direct = derive_validation_matrix(
                    objective=objective,
                    validation_commands=["pytest"],
                    has_review_surface=False,
                )
                self.assertTrue(direct["security"]["required"])
        for objective in ("Optimize the hot loop", "检查热路径性能"):
            with self.subTest(objective=objective):
                direct = derive_validation_matrix(
                    objective=objective,
                    validation_commands=["pytest"],
                    has_review_surface=False,
                )
                self.assertTrue(direct["performance"]["required"])

    def test_review_surface_rejects_escape_and_secret_url(self) -> None:
        with self.assertRaises(ValueError):
            validate_review_surface(
                {"type": "markdown", "artifact_path": "../secret"}, ["docs/**"]
            )
        with self.assertRaises(ValueError):
            validate_review_surface(
                {"type": "browser_preview", "preview_url": "http://localhost:3000/?token=x"},
                ["docs/**"],
            )
        with self.assertRaisesRegex(ValueError, "artifact_path or preview_url"):
            validate_review_surface(
                {
                    "required": True,
                    "type": "markdown",
                    "artifact_path": None,
                    "preview_url": None,
                    "evidence_refs": [],
                    "review_questions": ["Is this acceptable?"],
                    "decision_gate_id": "decision-1",
                },
                ["docs/**"],
            )
        with self.assertRaisesRegex(ValueError, "safe ID"):
            validate_review_surface(
                {
                    "required": True,
                    "type": "markdown",
                    "artifact_path": "docs/review.md",
                    "preview_url": None,
                    "evidence_refs": [],
                    "review_questions": ["Is this acceptable?"],
                    "decision_gate_id": "decision with spaces",
                },
                ["docs/**"],
            )
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            docs = Path(root) / "docs"
            docs.mkdir()
            (docs / "escape").symlink_to(Path(outside), target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink escapes repo root"):
                validate_review_surface(
                    {
                        "required": True,
                        "type": "markdown",
                        "artifact_path": "docs/escape/review.md",
                        "preview_url": None,
                        "evidence_refs": [],
                        "review_questions": ["Is this acceptable?"],
                        "decision_gate_id": "decision-symlink",
                    },
                    ["docs/**"],
                    root,
                )
            (docs / "loop").symlink_to("loop")
            with self.assertRaisesRegex(ValueError, "symlink cannot be resolved"):
                validate_review_surface(
                    {
                        "required": True,
                        "type": "markdown",
                        "artifact_path": "docs/loop/review.md",
                        "preview_url": None,
                        "evidence_refs": [],
                        "review_questions": ["Is this acceptable?"],
                        "decision_gate_id": "decision-symlink-loop",
                    },
                    ["docs/**"],
                    root,
                )
            (docs / "missing").symlink_to("does-not-exist")
            with self.assertRaisesRegex(ValueError, "symlink cannot be resolved"):
                validate_review_surface(
                    {
                        "required": True,
                        "type": "markdown",
                        "artifact_path": "docs/missing/review.md",
                        "preview_url": None,
                        "evidence_refs": [],
                        "review_questions": ["Is this acceptable?"],
                        "decision_gate_id": "decision-symlink-missing",
                    },
                    ["docs/**"],
                    root,
                )

    def test_scaffold_rejects_incomplete_v32_goal_contracts(self) -> None:
        payload = json.loads(
            (ROOT / "examples" / "03-adaptive-passkey-input.json").read_text()
        )
        payload["goals"][1]["review_surface"] = {"required": True}
        errors = scaffold.validation_errors(payload)
        self.assertTrue(
            any("review_surface:missing fields" in error for error in errors), errors
        )

        payload = json.loads(
            (ROOT / "examples" / "03-adaptive-passkey-input.json").read_text()
        )
        payload["goals"][1]["validation_matrix"] = {
            "functional": {"required": True}
        }
        errors = scaffold.validation_errors(payload)
        self.assertTrue(
            any("validation_matrix:missing_dimension" in error for error in errors),
            errors,
        )
        self.assertIn(
            "goals:2:validation_matrix:functional:evidence_required", errors
        )

        payload = json.loads(
            (ROOT / "examples" / "03-adaptive-passkey-input.json").read_text()
        )
        payload["goals"][1]["review_surface"]["decision_gate_id"] = (
            "decision with spaces"
        )
        errors = scaffold.validation_errors(payload)
        self.assertTrue(
            any("decision_gate_id must be a safe ID" in error for error in errors),
            errors,
        )

        payload = json.loads(
            (ROOT / "examples" / "03-adaptive-passkey-input.json").read_text()
        )
        duplicate_surface = copy.deepcopy(payload["goals"][1]["review_surface"])
        payload["goals"][2]["review_surface"] = duplicate_surface
        errors = scaffold.validation_errors(payload)
        self.assertTrue(
            any("duplicate_decision_gate_id" in error for error in errors), errors
        )

    def test_not_applicable_review_surface_does_not_require_ux(self) -> None:
        payload = json.loads(
            (ROOT / "examples" / "03-adaptive-passkey-input.json").read_text()
        )
        payload["goals"][0]["review_surface"] = {
            "required": False,
            "type": "NOT_APPLICABLE",
            "artifact_path": None,
            "preview_url": None,
            "evidence_refs": [],
            "review_questions": [],
            "decision_gate_id": None,
            "reason": "contract-only Goal has no visual surface",
        }
        workers = scaffold.normalize_workers(payload)
        goals = scaffold.normalize_goals(payload, workers)
        self.assertFalse(goals[0]["validation_matrix"]["user_experience"]["required"])

    def test_review_surface_uses_inherited_worker_scope(self) -> None:
        payload = json.loads(
            (ROOT / "examples" / "03-adaptive-passkey-input.json").read_text()
        )
        payload["allowed"] = ["docs/**"]
        payload["workers"][0]["allowed"] = ["app/**"]
        payload["goals"][1]["allowed_write_scope"] = []
        payload["goals"][1]["review_surface"] = {
            "required": True,
            "type": "markdown",
            "artifact_path": "app/review.md",
            "preview_url": None,
            "evidence_refs": [".codex-loop/reports/review.json"],
            "review_questions": ["Is the UI correct?"],
            "decision_gate_id": "decision-inherited-scope",
        }
        errors = scaffold.validation_errors(payload)
        self.assertFalse(
            any("review surface path is outside allowed scope" in error for error in errors),
            errors,
        )

        payload["goals"][1]["objective"] = (
            "Change auth permissions, API compatibility, frontend UI, and performance"
        )
        payload["goals"][1]["validation_matrix"] = {
            dimension: {"required": False, "reason": "attempted downgrade"}
            for dimension in (
                "functional",
                "regression",
                "static_quality",
                "compatibility",
                "security",
                "performance",
                "user_experience",
                "change_impact",
            )
        }
        errors = scaffold.validation_errors(payload)
        for dimension in (
            "functional",
            "regression",
            "static_quality",
            "compatibility",
            "security",
            "performance",
            "user_experience",
            "change_impact",
        ):
            self.assertIn(
                f"goals:2:validation_matrix:{dimension}:required_gate_cannot_be_disabled",
                errors,
            )

        payload = json.loads(
            (ROOT / "examples" / "03-adaptive-passkey-input.json").read_text()
        )
        payload["goals"][1]["objective"] = "安全加固"
        payload["goals"][1]["validation_matrix"] = complete_validation_matrix(
            required_dimensions=("functional", "regression", "static_quality", "change_impact")
        )
        payload["goals"][1]["validation_matrix"]["security"] = {
            "required": False,
            "reason": "attempted direct-word downgrade",
        }
        errors = scaffold.validation_errors(payload)
        self.assertIn(
            "goals:2:validation_matrix:security:required_gate_cannot_be_disabled",
            errors,
        )

    def test_adaptive_safety_policies_cannot_be_disabled(self) -> None:
        payload = json.loads(
            (ROOT / "examples" / "03-adaptive-passkey-input.json").read_text()
        )
        payload["failure_fingerprint_policy"] = {"enabled": False}
        payload["context_freshness_policy"] = "disabled"
        errors = scaffold.validation_errors(payload)
        self.assertIn(
            "failure_fingerprint_policy:adaptive_safety_gate_cannot_be_disabled",
            errors,
        )
        self.assertIn(
            "context_freshness_policy:adaptive_safety_gate_cannot_be_disabled",
            errors,
        )

    @mock.patch.dict("os.environ", {"CODEX_HOME": "/workspace/.codex"})
    def test_adaptive_pack_contains_v327_contract_with_bounded_growth(self) -> None:
        input_path = ROOT / "examples" / "03-adaptive-passkey-input.json"
        args = scaffold.build_parser().parse_args(["--input", str(input_path)])
        payload = scaffold.load_payload(args)
        pack = scaffold.render_controller_pack(payload, "full").rstrip() + "\n"
        for token in (
            "Human Steering And Convergence",
            "MIGRATE_V1_TO_V2",
            "MIGRATE_CONTROLLER_PACK",
            "STATUS_QUERY",
            "PAUSE_REQUESTED",
            "Decision Cards",
            "review_surface",
            "THRASHING_DETECTED",
            "Validation Matrix",
            "RECORD_CONTEXT_FRESHNESS",
            "EVIDENCE_CONFLICT",
        ):
            self.assertIn(token, pack)
        # v3.2.6 budget: 213556 bytes/2640 lines; tracked predecessor: 217477/2622.
        # Deduplicated v3.2.7 recovery contract: 222707/2637 (+4.285% vs budget,
        # +2.405% vs predecessor). One-percent headroom keeps later growth bounded.
        self.assertLessEqual(len(pack.encode("utf-8")), int(222707 * 1.01))
        self.assertLessEqual(len(pack.splitlines()), int(2637 * 1.01))

    def test_skill_links_one_layer_v32_reference_and_stays_bounded(self) -> None:
        skill = (ROOT / "codex-loop-prompt-architect" / "SKILL.md").read_text()
        self.assertIn("references/human-steering-and-convergence.md", skill)
        self.assertIn("references/loop-intake-gate.md", skill)
        self.assertIn("READY_FOR_LOOP", skill)
        self.assertNotIn("## Clarification Gate", skill)
        self.assertLessEqual(len(skill.splitlines()), 500)

    def test_adaptive_input_with_one_repair_keeps_fingerprint_compatibility(self) -> None:
        payload = json.loads(
            (ROOT / "examples" / "03-adaptive-passkey-input.json").read_text()
        )
        payload["max_repair_attempts_per_goal"] = 1
        errors = scaffold.validation_errors(payload)
        self.assertFalse(
            any(error.startswith("max_repair_attempts_per_goal:") for error in errors),
            errors,
        )
        definitions = {"g1": goal("g1", "m1")}
        milestones = [milestone("m1", "ACTIVE")]
        authorization = authorization_envelope(definitions, milestones)
        authorization["repair_policy"]["max_repair_attempts_per_goal"] = 1
        runtime_response, _ = self.harness_for_compatibility().initialize(
            definitions=definitions,
            milestones=milestones,
            authorization=authorization,
        )
        self.assertTrue(runtime_response["ok"], runtime_response)

    def harness_for_compatibility(self) -> Harness:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return Harness(Path(temp.name))


class HumanControlRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.harness = Harness(Path(self.temp.name))

    def request(self, mutation: dict[str, object], *, expected: int | None = None) -> dict[str, object]:
        return self.harness.apply(mutation, expected=expected)

    def test_runtime_schema_rejects_partial_validation_matrix(self) -> None:
        definition = goal("g1", "m1")
        definition["validation_matrix"] = {
            "functional": {"required": True, "evidence": ["pytest"]}
        }
        definition["payload_template_digest"] = goal_definition_digest(definition)
        response, _ = self.harness.initialize(definitions={"g1": definition})
        self.assertEqual(response["error"]["code"], "REQUEST_SCHEMA_INVALID")

    def test_runtime_rejects_review_surface_symlink_scope_escape(self) -> None:
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        source = Path(self.temp.name) / "src"
        source.mkdir()
        (source / "escape").symlink_to(
            Path(outside.name), target_is_directory=True
        )
        definition = goal("g1", "m1")
        definition["review_surface"] = {
            "required": True,
            "type": "markdown",
            "artifact_path": "src/escape/review.md",
            "preview_url": None,
            "evidence_refs": [],
            "review_questions": ["Is this acceptable?"],
            "decision_gate_id": "decision-symlink-runtime",
        }
        definition["payload_template_digest"] = goal_definition_digest(definition)
        response, _ = self.harness.initialize(definitions={"g1": definition})
        self.assertEqual(response["error"]["code"], "PATH_SCOPE_ESCAPE")
        self.assertFalse(self.harness.runtime.state_path.exists())

    def test_fresh_v2_initialize_requires_complete_validation_matrix(self) -> None:
        definition = goal("g1", "m1")
        definition.pop("validation_matrix")
        definition["payload_template_digest"] = goal_definition_digest(definition)
        response, _ = self.harness.initialize(definitions={"g1": definition})
        self.assertEqual(response["error"]["code"], "V2_VALIDATION_MATRIX_REQUIRED")
        self.assertFalse(self.harness.runtime.state_path.exists())

    def test_v2_initialize_and_status_projection(self) -> None:
        response, _ = self.harness.initialize()
        self.assertTrue(response["ok"], response)
        state = self.harness.runtime.read_state()
        self.assertEqual(state["schema_version"], 2)
        self.assertEqual(
            state["status_projection_target"]["render_contract_version"],
            "status-v3",
        )
        status = (Path(self.temp.name) / ".codex-loop" / "STATUS.md").read_text()
        self.assertIn("## What's done", status)
        self.assertIn(f"State version: `{state['state_version']}`", status)
        for label in (
            "Projected state version",
            "Control phase",
            "Last meaningful progress",
            "Role status",
            "Goal objective",
            "Next action",
            "Next heartbeat",
            "Blockers or limitations",
            "Key reports/artifacts",
            "Active task last observed at",
            "Projection freshness",
        ):
            self.assertIn(label, status)
        self.assertEqual(state["status_projection_target"]["target_digest"], digest(status))
        journals = list(
            (Path(self.temp.name) / ".codex-loop" / "projection-transactions").glob("status-v*.json")
        )
        self.assertEqual(len(journals), 1)
        state_bytes = self.harness.runtime.state_path.read_bytes()
        event_bytes = self.harness.runtime.events_path.read_bytes()
        transaction_count = len(list(self.harness.runtime.transactions_dir.glob("*.json")))
        self.harness.runtime.read_state()  # STATUS_QUERY uses this read-only path.
        self.assertEqual(self.harness.runtime.state_path.read_bytes(), state_bytes)
        self.assertEqual(self.harness.runtime.events_path.read_bytes(), event_bytes)
        self.assertEqual(
            len(list(self.harness.runtime.transactions_dir.glob("*.json"))),
            transaction_count,
        )
        self.harness.register_control_result(
            "THREAD",
            "worker-status-only",
            "controller-1",
            {"role_kind": "WORKER"},
            {"thread_id": "worker-status-only", "role_kind": "WORKER", "worktree_path": "."},
        )
        idle_status = (Path(self.temp.name) / ".codex-loop" / "STATUS.md").read_text()
        self.assertIn("Status: `RUNNING_PROGRESS`", idle_status)
        self.assertIn("Projection freshness: `CURRENT`", idle_status)

    def test_legacy_status_v1_projection_is_verified_then_upgraded(self) -> None:
        initialized, _ = self.harness.initialize()
        self.assertTrue(initialized["ok"], initialized)
        runtime = self.harness.runtime
        state = runtime.read_state()
        legacy_payload = runtime._render_status(
            state, contract_version="status-v1"
        )
        self.assertIsNotNone(legacy_payload)
        legacy_digest = digest(legacy_payload.decode("utf-8"))
        state["status_projection_target"] = {
            "path": ".codex-loop/STATUS.md",
            "target_state_version": state["state_version"],
            "target_digest": legacy_digest,
            "render_contract_version": "status-v1",
        }
        runtime.state_path.write_bytes(runtime._render_state(state))
        runtime.status_path.write_bytes(legacy_payload)
        journal_path = (
            runtime.projection_transactions_dir
            / f"status-v{state['state_version']}.json"
        )
        journal_path.write_text(
            json.dumps(
                {
                    "journal_version": 1,
                    "status": "APPLIED",
                    "target_state_version": state["state_version"],
                    "target_digest": legacy_digest,
                    "render_contract_version": "status-v1",
                    "projected_digest": legacy_digest,
                    "readback_digest": legacy_digest,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )

        upgraded = self.request(
            {
                "type": "RECORD_STEERING",
                "steering_id": "upgrade-status-v1",
                "steering_type": "CORRECTION",
                "normalized_digest": digest("upgrade status projection"),
                "identity_algorithm": "message-item-v1",
                "message_item_id": "upgrade-status-message",
                "summary": "upgrade status projection",
                "classification_reason": "backward compatibility test",
            }
        )
        self.assertTrue(upgraded["ok"], upgraded)
        current = runtime.read_state()
        self.assertEqual(
            current["status_projection_target"]["render_contract_version"],
            "status-v3",
        )
        self.assertIn("Control phase", runtime.status_path.read_text())

    def test_previous_status_v2_projection_is_verified_then_upgraded(self) -> None:
        initialized, _ = self.harness.initialize()
        self.assertTrue(initialized["ok"], initialized)
        runtime = self.harness.runtime
        state = runtime.read_state()
        previous_payload = runtime._render_status(
            state, contract_version="status-v2"
        )
        self.assertIsNotNone(previous_payload)
        previous_digest = digest(previous_payload.decode("utf-8"))
        state["status_projection_target"] = {
            "path": ".codex-loop/STATUS.md",
            "target_state_version": state["state_version"],
            "target_digest": previous_digest,
            "render_contract_version": "status-v2",
        }
        runtime.state_path.write_bytes(runtime._render_state(state))
        runtime.status_path.write_bytes(previous_payload)
        journal_path = (
            runtime.projection_transactions_dir
            / f"status-v{state['state_version']}.json"
        )
        journal_path.write_text(
            json.dumps(
                {
                    "journal_version": 1,
                    "status": "APPLIED",
                    "target_state_version": state["state_version"],
                    "target_digest": previous_digest,
                    "render_contract_version": "status-v2",
                    "projected_digest": previous_digest,
                    "readback_digest": previous_digest,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        upgraded = self.request(
            {
                "type": "RECORD_STEERING",
                "steering_id": "upgrade-status-v2",
                "steering_type": "CORRECTION",
                "normalized_digest": digest("upgrade status v2 projection"),
                "identity_algorithm": "message-item-v1",
                "message_item_id": "upgrade-status-v2-message",
                "summary": "upgrade status v2 projection",
                "classification_reason": "preserve old reader compatibility",
            }
        )
        self.assertTrue(upgraded["ok"], upgraded)
        self.assertEqual(
            runtime.read_state()["status_projection_target"][
                "render_contract_version"
            ],
            "status-v3",
        )

    def test_tampered_legacy_status_v1_projection_is_rejected_without_side_effects(self) -> None:
        initialized, _ = self.harness.initialize()
        self.assertTrue(initialized["ok"], initialized)
        runtime = self.harness.runtime
        state = runtime.read_state()
        state["status_projection_target"] = {
            "path": ".codex-loop/STATUS.md",
            "target_state_version": state["state_version"],
            "target_digest": digest("tampered legacy status"),
            "render_contract_version": "status-v1",
        }
        runtime.state_path.write_bytes(runtime._render_state(state))
        before = persisted_snapshot(Path(self.temp.name))
        rejected = self.request(
            {
                "type": "RECORD_STEERING",
                "steering_id": "reject-tampered-status-v1",
                "steering_type": "CORRECTION",
                "normalized_digest": digest("reject tampered status"),
                "identity_algorithm": "message-item-v1",
                "message_item_id": "reject-tampered-status-message",
                "summary": "reject tampered status",
                "classification_reason": "backward compatibility test",
            },
            expected=state["state_version"],
        )
        self.assertEqual(rejected["error"]["code"], "STATUS_PROJECTION_TARGET_INVALID")
        self.assertEqual(persisted_snapshot(Path(self.temp.name)), before)

    def test_decision_response_requires_specialized_mutation(self) -> None:
        self.harness.initialize()
        response = self.request(
            {
                "type": "RECORD_STEERING",
                "steering_id": "decision-generic",
                "steering_type": "DECISION_RESPONSE",
                "normalized_digest": digest("decision-generic"),
                "identity_algorithm": "message-item-v1",
                "message_item_id": "decision-message",
                "summary": "choose one option",
                "classification_reason": "decision response",
            }
        )
        self.assertEqual(response["error"]["code"], "REQUEST_SCHEMA_INVALID")
        self.assertNotIn(
            "decision-generic", self.harness.runtime.read_state()["steering_ledger"]
        )

    def test_steering_idempotency_pause_and_resume(self) -> None:
        self.harness.initialize()
        mutation = {
            "type": "RECORD_STEERING",
            "steering_id": "steer-1",
            "steering_type": "PAUSE",
            "normalized_digest": digest("pause"),
            "identity_algorithm": "message-item-v1",
            "message_item_id": "message-1",
            "summary": "pause at safe point",
            "classification_reason": "explicit pause request",
        }
        first = self.request(mutation)
        self.assertEqual(first["operation_status"], "STEERING_CLASSIFIED")
        replay = self.request(mutation)
        self.assertEqual(replay["operation_status"], "STEERING_ALREADY_RECORDED")
        duplicate_identity = self.request({**mutation, "steering_id": "steer-duplicate"})
        self.assertEqual(
            duplicate_identity["operation_status"], "STEERING_ALREADY_RECORDED"
        )
        self.assertEqual(
            duplicate_identity["result"]["steering_id"], "steer-1"
        )
        changed_same_message = self.request(
            {
                **mutation,
                "steering_id": "steer-same-message-changed-digest",
                "normalized_digest": digest("different normalization"),
            }
        )
        self.assertEqual(
            changed_same_message["error"]["code"], "STEERING_IDENTITY_CONFLICT"
        )
        conflict = self.request({**mutation, "normalized_digest": digest("changed")})
        self.assertFalse(conflict["ok"])
        self.assertEqual(conflict["error"]["code"], "STEERING_IDENTITY_CONFLICT")
        bypass = self.request(
            {
                "type": "RESOLVE_STEERING",
                "steering_id": "steer-1",
                "resolution_status": "APPLIED",
                "resolution": "incorrect generic pause resolution",
                "next_action_code": "NONE",
            }
        )
        self.assertEqual(
            bypass["error"]["code"], "STEERING_REQUIRES_SPECIALIZED_RESOLVER"
        )
        paused = self.request({"type": "SET_RUN_CONTROL", "steering_id": "steer-1", "requested_status": "PAUSE"})
        self.assertEqual(paused["operation_status"], "PAUSED_AT_SAFE_POINT")
        blocked_lease = self.harness.apply(
            {
                "type": "ACQUIRE_LEASE",
                "routing_turn_id": "turn-paused",
                "lease_id": "lease-paused",
                "owner_kind": "HEARTBEAT",
                "owner_identity": "controller-1",
                "observed_at": "2026-01-01T00:01:00Z",
                "expires_at": "2026-01-01T01:00:00Z",
            }
        )
        self.assertEqual(blocked_lease["error"]["code"], "LOOP_PAUSED")
        resume_steering = {
            **mutation,
            "steering_id": "steer-2",
            "steering_type": "RESUME",
            "normalized_digest": digest("resume"),
            "message_item_id": "message-2",
            "summary": "resume same loop",
            "classification_reason": "explicit resume request",
        }
        self.assertTrue(self.request(resume_steering)["ok"])
        resumed = self.request({"type": "SET_RUN_CONTROL", "steering_id": "steer-2", "requested_status": "RESUME"})
        self.assertEqual(resumed["operation_status"], "RUNNING")

    def test_steering_fallback_identity_and_algorithm_are_closed(self) -> None:
        self.harness.initialize()
        base = {
            "type": "RECORD_STEERING",
            "steering_id": "steer-cursor-1",
            "steering_type": "CONSTRAINT",
            "normalized_digest": digest("do not change schema"),
            "identity_algorithm": "turn-cursor-v1",
            "observed_turn_cursor": "turn-17",
            "summary": "do not change schema",
            "classification_reason": "explicit constraint",
        }
        self.assertTrue(self.request(base)["ok"])
        different_turn = self.request(
            {
                **base,
                "steering_id": "steer-cursor-2",
                "observed_turn_cursor": "turn-18",
            }
        )
        self.assertTrue(different_turn["ok"])
        mismatch = self.request(
            {
                **base,
                "steering_id": "steer-mismatch",
                "identity_algorithm": "message-item-v1",
            }
        )
        self.assertFalse(mismatch["ok"])
        self.assertIn(
            mismatch["error"]["code"],
            {"REQUEST_SCHEMA_INVALID", "STEERING_IDENTITY_ALGORITHM_MISMATCH"},
        )

    def test_pause_with_sent_worker_waits_for_safe_point(self) -> None:
        self.harness.initialize()
        self.harness.ensure_controller_goal("m1")
        self.harness.register_control_result(
            "THREAD",
            "worker-create-pause",
            "controller-1",
            {"role_kind": "WORKER"},
            {"thread_id": "worker-1", "role_kind": "WORKER", "worktree_path": "."},
        )
        claim = self.harness.acquire()
        definition = self.harness.definitions["g1"]
        prepared, payload = self.harness.prepare_outbox(
            claim,
            "DISPATCH",
            "dispatch-pause",
            {"goal_id": "g1", "goal_definition_digest": definition["payload_template_digest"]},
            target_id="worker-1",
        )
        self.assertTrue(prepared["ok"], prepared)
        sent = self.harness.mark_sent(
            claim, "DISPATCH", "dispatch-pause", payload, target_id="worker-1"
        )
        self.assertTrue(sent["ok"], sent)
        correction = self.request(
            {
                "type": "RECORD_STEERING",
                "steering_id": "steer-inflight-correction",
                "steering_type": "CORRECTION",
                "normalized_digest": digest("change button color"),
                "identity_algorithm": "message-item-v1",
                "message_item_id": "message-inflight-correction",
                "summary": "change button color at safe point",
                "classification_reason": "explicit correction",
                "target_goal_id": "g1",
                "target_dispatch_id": "dispatch-pause",
            }
        )
        self.assertTrue(correction["ok"], correction)
        unsafe_apply = self.request(
            {"type": "RESOLVE_STEERING", "steering_id": "steer-inflight-correction", "resolution_status": "APPLIED", "resolution": "change current payload", "next_action_code": "NONE"}
        )
        self.assertEqual(unsafe_apply["error"]["code"], "INFLIGHT_STEERING_MUST_DEFER")
        deferred = self.request(
            {"type": "RESOLVE_STEERING", "steering_id": "steer-inflight-correction", "resolution_status": "DEFERRED", "resolution": "wait for Worker safe point", "next_action_code": "WAIT_SAFE_POINT"}
        )
        self.assertEqual(deferred["operation_status"], "STEERING_DEFERRED")
        self.assertTrue(
            self.request(
                {
                    "type": "RECORD_STEERING",
                    "steering_id": "steer-active-pause",
                    "steering_type": "PAUSE",
                    "normalized_digest": digest("active-pause"),
                    "identity_algorithm": "message-item-v1",
                    "message_item_id": "message-active-pause",
                    "summary": "pause after current worker",
                    "classification_reason": "explicit pause request",
                }
            )["ok"]
        )
        paused = self.request(
            {"type": "SET_RUN_CONTROL", "steering_id": "steer-active-pause", "requested_status": "PAUSE", "reason": "user request"}
        )
        self.assertEqual(paused["operation_status"], "PAUSE_REQUESTED")
        self.assertEqual(
            self.harness.runtime.read_state()["dispatch_outbox"]["dispatch-pause"]["status"],
            "SENT",
        )
        artifact_digest = digest("pause-worker-artifact")
        report_result = {"status": "PASS", "artifact_digest": artifact_digest}
        report_content = self.harness.formal_report_content(
            "DISPATCH", "dispatch-pause", report_result
        )
        report_digest = digest(report_content)
        acked = self.harness.ack_outbox(
            claim,
            "DISPATCH",
            "dispatch-pause",
            payload,
            target_id="worker-1",
            result={**report_result, "report_digest": report_digest},
            report_content=report_content,
        )
        self.assertTrue(acked["ok"], acked)
        safe = self.request(
            {"type": "SET_RUN_CONTROL", "steering_id": "steer-active-pause", "requested_status": "SAFE_POINT_REACHED"}
        )
        self.assertEqual(safe["operation_status"], "PAUSED_AT_SAFE_POINT")

    def test_pause_allows_transactional_sent_record_after_external_send(self) -> None:
        self.harness.initialize()
        self.harness.ensure_controller_goal("m1")
        self.harness.register_control_result(
            "THREAD",
            "worker-create-pause-race",
            "controller-1",
            {"role_kind": "WORKER"},
            {"thread_id": "worker-1", "role_kind": "WORKER", "worktree_path": "."},
        )
        claim = self.harness.acquire()
        definition = self.harness.definitions["g1"]
        prepared, payload = self.harness.prepare_outbox(
            claim,
            "DISPATCH",
            "dispatch-pause-race",
            {
                "goal_id": "g1",
                "goal_definition_digest": definition["payload_template_digest"],
            },
            target_id="worker-1",
        )
        self.assertTrue(prepared["ok"], prepared)
        self.assertTrue(
            self.request(
                {
                    "type": "RECORD_STEERING",
                    "steering_id": "steer-pause-race",
                    "steering_type": "PAUSE",
                    "normalized_digest": digest("pause after external send"),
                    "identity_algorithm": "message-item-v1",
                    "message_item_id": "message-pause-race",
                    "summary": "pause while sent bookkeeping is pending",
                    "classification_reason": "explicit pause request",
                }
            )["ok"]
        )
        paused = self.request(
            {
                "type": "SET_RUN_CONTROL",
                "steering_id": "steer-pause-race",
                "requested_status": "PAUSE",
                "reason": "user request",
            }
        )
        self.assertEqual(paused["operation_status"], "PAUSE_REQUESTED")
        sent = self.harness.mark_sent(
            claim,
            "DISPATCH",
            "dispatch-pause-race",
            payload,
            target_id="worker-1",
        )
        self.assertTrue(sent["ok"], sent)
        self.assertEqual(
            self.harness.runtime.read_state()["dispatch_outbox"][
                "dispatch-pause-race"
            ]["status"],
            "SENT",
        )

    def test_pause_with_existing_lease_blocks_new_routing_until_release(self) -> None:
        self.harness.initialize()
        claim = self.harness.acquire()
        self.assertTrue(
            self.request(
                {
                    "type": "RECORD_STEERING",
                    "steering_id": "pause-existing-lease",
                    "steering_type": "PAUSE",
                    "normalized_digest": digest("pause existing lease"),
                    "identity_algorithm": "message-item-v1",
                    "message_item_id": "pause-existing-lease-message",
                    "summary": "pause before dispatch",
                    "classification_reason": "explicit pause request",
                }
            )["ok"]
        )
        paused = self.request(
            {
                "type": "SET_RUN_CONTROL",
                "steering_id": "pause-existing-lease",
                "requested_status": "PAUSE",
            }
        )
        self.assertEqual(paused["operation_status"], "PAUSE_REQUESTED")
        blocked, _ = self.harness.prepare_outbox(
            claim,
            "AUTOMATION",
            "blocked-after-pause",
            {},
        )
        self.assertEqual(blocked["error"]["code"], "LOOP_PAUSED")
        released = self.request(
            {
                "type": "RELEASE_LEASE",
                "lease_claim": claim,
                "observed_at": "2026-01-01T00:01:00Z",
                "reason_code": "USER_PAUSE_SAFE_POINT",
            }
        )
        self.assertEqual(released["operation_status"], "CONTROLLER_LEASE_RELEASED")
        safe = self.request(
            {
                "type": "SET_RUN_CONTROL",
                "steering_id": "pause-existing-lease",
                "requested_status": "SAFE_POINT_REACHED",
            }
        )
        self.assertEqual(safe["operation_status"], "PAUSED_AT_SAFE_POINT")

    def test_decision_binding_and_stale_rejection(self) -> None:
        self.harness.initialize()
        state = self.harness.runtime.read_state()
        card = {
            "type": "REGISTER_DECISION",
            "decision_id": "dec-1",
            "decision_context_digest": digest("placeholder"),
            "source_state_version": state["state_version"],
            "valid_through_state_version": state["state_version"] + 1,
            "options": [
                {"option_id": "allow", "option_effect": "CONTINUE", "preauthorized_capability": "none"},
                {"option_id": "wait", "option_effect": "WAIT", "preauthorized_capability": "none"},
            ],
            "scope": {"repository": "owner/repo", "branch": "feature/x"},
            "exclusions": ["merge", "deploy"],
        }
        card["decision_context_digest"] = self.harness.runtime._decision_context_digest(
            state, card
        )
        registered = self.request(card)
        self.assertTrue(registered["ok"])
        self.assertIn("## 需要你决定", registered["result"]["decision_card"])
        self.assertIn("明确不包含：merge, deploy", registered["result"]["decision_card"])
        stale = self.request(
            {
                "type": "RECORD_DECISION_RESPONSE",
                "steering_id": "decision-response-stale",
                "normalized_digest": digest("stale response"),
                "identity_algorithm": "message-item-v1",
                "message_item_id": "decision-message-stale",
                "summary": "choose allow",
                "classification_reason": "explicit decision response",
                "decision_id": "dec-1",
                "option_id": "allow",
                "decision_context_digest": digest("wrong"),
            }
        )
        self.assertFalse(stale["ok"])
        self.assertEqual(stale["error"]["code"], "DECISION_STALE")
        current = self.harness.runtime.read_state()
        unauthorized = {
            **card,
            "decision_id": "dec-2",
            "source_state_version": current["state_version"],
            "valid_through_state_version": current["state_version"] + 1,
            "options": [
                {"option_id": "pr", "option_effect": "CREATE_DRAFT_PR", "preauthorized_capability": "pr_create"},
                {"option_id": "wait", "option_effect": "WAIT", "preauthorized_capability": "none"},
            ],
        }
        unauthorized["decision_context_digest"] = self.harness.runtime._decision_context_digest(
            current, unauthorized
        )
        denied = self.request(unauthorized)
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error"]["code"], "DECISION_CAPABILITY_NOT_AUTHORIZED")
        current = self.harness.runtime.read_state()
        duplicate_options = {
            **card,
            "decision_id": "dec-duplicate-options",
            "source_state_version": current["state_version"],
            "valid_through_state_version": current["state_version"] + 1,
            "options": [
                {"option_id": "same", "option_effect": "CONTINUE", "preauthorized_capability": "none"},
                {"option_id": "same", "option_effect": "WAIT", "preauthorized_capability": "none"},
            ],
        }
        duplicate_options["decision_context_digest"] = (
            self.harness.runtime._decision_context_digest(current, duplicate_options)
        )
        duplicate_rejected = self.request(duplicate_options)
        self.assertEqual(
            duplicate_rejected["error"]["code"], "DECISION_OPTION_ID_CONFLICT"
        )
        current = self.harness.runtime.read_state()
        valid = {
            **card,
            "decision_id": "dec-3",
            "source_state_version": current["state_version"],
            "valid_through_state_version": current["state_version"] + 1,
        }
        valid["decision_context_digest"] = self.harness.runtime._decision_context_digest(
            current, valid
        )
        self.assertTrue(self.request(valid)["ok"])
        applied = self.request(
            {
                "type": "RECORD_DECISION_RESPONSE",
                "steering_id": "decision-response-valid",
                "normalized_digest": digest("valid response"),
                "identity_algorithm": "message-item-v1",
                "message_item_id": "decision-message-valid",
                "summary": "choose allow",
                "classification_reason": "explicit decision response",
                "decision_id": "dec-3",
                "option_id": "allow",
                "decision_context_digest": valid["decision_context_digest"],
            }
        )
        self.assertEqual(applied["next_action_code"], "CONTINUE")
        applied_state = self.harness.runtime.read_state()
        self.assertEqual(
            applied_state["steering_ledger"]["decision-response-valid"]["status"],
            "APPLIED",
        )
        duplicate = self.request(
            {
                "type": "RECORD_DECISION_RESPONSE",
                "steering_id": "decision-response-valid-retry",
                "normalized_digest": digest("valid response"),
                "identity_algorithm": "message-item-v1",
                "message_item_id": "decision-message-valid",
                "summary": "choose allow",
                "classification_reason": "explicit decision response",
                "decision_id": "dec-3",
                "option_id": "allow",
                "decision_context_digest": valid["decision_context_digest"],
            }
        )
        self.assertEqual(
            duplicate["operation_status"], "DECISION_RESPONSE_ALREADY_APPLIED"
        )

    def test_decision_registration_requires_post_registration_validity(self) -> None:
        self.harness.initialize()
        state = self.harness.runtime.read_state()
        card = {
            "type": "REGISTER_DECISION",
            "decision_id": "expires-on-register",
            "decision_context_digest": digest("placeholder"),
            "source_state_version": state["state_version"],
            "valid_through_state_version": state["state_version"],
            "options": [
                {"option_id": "continue", "option_effect": "CONTINUE", "preauthorized_capability": "none"},
                {"option_id": "wait", "option_effect": "WAIT", "preauthorized_capability": "none"},
            ],
            "scope": {"goal_id": "g1"},
            "exclusions": ["merge"],
        }
        card["decision_context_digest"] = self.harness.runtime._decision_context_digest(
            state, card
        )
        rejected = self.request(card)
        self.assertEqual(rejected["error"]["code"], "DECISION_STATE_RANGE_INVALID")

    def test_new_worker_artifact_stales_and_refreshes_same_decision_gate(self) -> None:
        definition = goal("g1", "m1")
        definition["review_surface"] = {
            "required": True,
            "type": "markdown",
            "artifact_path": "src/result.txt",
            "preview_url": None,
            "evidence_refs": [".codex-loop/reports/review-surface.json"],
            "review_questions": ["Is this exact artifact acceptable?"],
            "decision_gate_id": "surface-gate",
        }
        definition["payload_template_digest"] = goal_definition_digest(definition)
        self.harness.initialize(definitions={"g1": definition})
        first_worker = self.harness.worker_pass("g1")
        state = self.harness.runtime.read_state()
        card = {
            "type": "REGISTER_DECISION",
            "decision_id": "surface-gate",
            "decision_context_digest": digest("placeholder"),
            "source_state_version": state["state_version"],
            "valid_through_state_version": state["state_version"] + 20,
            "options": [
                {
                    "option_id": "accept",
                    "option_effect": "REVIEW_SURFACE_ACCEPTED",
                    "preauthorized_capability": "none",
                },
                {
                    "option_id": "wait",
                    "option_effect": "WAIT",
                    "preauthorized_capability": "none",
                },
            ],
            "scope": {
                "goal_id": "g1",
                "dispatch_id": first_worker["dispatch_id"],
                "artifact_digest": first_worker["artifact_digest"],
                "artifact_path": "src/result.txt",
            },
            "exclusions": ["merge", "deploy"],
        }
        card["decision_context_digest"] = self.harness.runtime._decision_context_digest(
            state, card
        )
        incomplete = copy.deepcopy(card)
        incomplete["scope"].pop("dispatch_id")
        incomplete["scope"].pop("artifact_digest")
        incomplete["decision_context_digest"] = (
            self.harness.runtime._decision_context_digest(state, incomplete)
        )
        before_incomplete = persisted_snapshot(Path(self.temp.name))
        incomplete_rejected = self.request(incomplete)
        self.assertEqual(
            incomplete_rejected["error"]["code"],
            "REVIEW_SURFACE_DECISION_IDENTITY_MISMATCH",
        )
        self.assertEqual(
            persisted_snapshot(Path(self.temp.name)), before_incomplete
        )
        self.assertTrue(self.request(card)["ok"])
        applied = self.request(
            {
                "type": "RECORD_DECISION_RESPONSE",
                "steering_id": "surface-gate-response-1",
                "normalized_digest": digest("accept first surface"),
                "identity_algorithm": "message-item-v1",
                "message_item_id": "surface-gate-message-1",
                "summary": "accept first surface",
                "classification_reason": "explicit surface decision",
                "decision_id": "surface-gate",
                "option_id": "accept",
                "decision_context_digest": card["decision_context_digest"],
            }
        )
        self.assertTrue(applied["ok"], applied)

        self.harness.review("CODE_REVIEW", "REVIEW_NEEDS_REPAIR", first_worker)
        second_worker = self.harness.worker_pass("g1")
        self.assertNotEqual(
            first_worker["artifact_digest"], second_worker["artifact_digest"]
        )
        stale_state = self.harness.runtime.read_state()
        self.assertEqual(
            stale_state["pending_decisions"]["surface-gate"]["status"],
            "STALE",
        )

        hijacked = {
            **card,
            "source_state_version": stale_state["state_version"],
            "valid_through_state_version": stale_state["state_version"] + 20,
            "scope": {
                **card["scope"],
                "dispatch_id": second_worker["dispatch_id"],
                "artifact_digest": second_worker["artifact_digest"],
                "artifact_path": "src/other.txt",
            },
        }
        hijacked["decision_context_digest"] = (
            self.harness.runtime._decision_context_digest(stale_state, hijacked)
        )
        rejected = self.request(hijacked)
        self.assertEqual(
            rejected["error"]["code"],
            "REVIEW_SURFACE_DECISION_IDENTITY_MISMATCH",
        )

        refreshed = {
            **card,
            "source_state_version": stale_state["state_version"],
            "valid_through_state_version": stale_state["state_version"] + 20,
            "scope": {
                **card["scope"],
                "dispatch_id": second_worker["dispatch_id"],
                "artifact_digest": second_worker["artifact_digest"],
            },
        }
        refreshed["decision_context_digest"] = (
            self.harness.runtime._decision_context_digest(stale_state, refreshed)
        )
        registered = self.request(refreshed)
        self.assertTrue(registered["ok"], registered)
        current = self.harness.runtime.read_state()["pending_decisions"][
            "surface-gate"
        ]
        self.assertEqual(current["status"], "PENDING")
        self.assertEqual(
            current["scope"]["artifact_digest"], second_worker["artifact_digest"]
        )

    def test_legacy_unbound_surface_decision_stales_and_rebinds(self) -> None:
        definition = goal("g1", "m1")
        definition["review_surface"] = {
            "required": True,
            "type": "markdown",
            "artifact_path": "src/result.txt",
            "preview_url": None,
            "evidence_refs": [".codex-loop/reports/review-surface.json"],
            "review_questions": ["Is this exact artifact acceptable?"],
            "decision_gate_id": "surface-gate",
        }
        definition["payload_template_digest"] = goal_definition_digest(definition)
        self.harness.initialize(definitions={"g1": definition})
        worker_a = self.harness.worker_pass("g1")
        state = self.harness.runtime.read_state()
        legacy_card = {
            "decision_id": "surface-gate",
            "decision_context_digest": digest("placeholder"),
            "source_state_version": state["state_version"],
            "valid_through_state_version": state["state_version"] + 20,
            "options": [
                {
                    "option_id": "accept",
                    "option_effect": "REVIEW_SURFACE_ACCEPTED",
                    "preauthorized_capability": "none",
                },
                {
                    "option_id": "wait",
                    "option_effect": "WAIT",
                    "preauthorized_capability": "none",
                },
            ],
            "scope": {"goal_id": "g1", "artifact_path": "src/result.txt"},
            "exclusions": ["merge", "deploy"],
            "status": "APPLIED",
            "selected_option_id": "accept",
            "applied_state_version": state["state_version"],
        }
        legacy_card["decision_context_digest"] = (
            self.harness.runtime._decision_context_digest(state, legacy_card)
        )
        state["pending_decisions"]["surface-gate"] = legacy_card
        artifact_b = digest("legacy-repair-artifact-b")
        self.harness.runtime._record_worker_result(
            state,
            {
                "identity": {"goal_id": "g1"},
                "outbox_id": "legacy-repair-dispatch",
                "roadmap_version": state["roadmap_version"],
                "ack_evidence_paths": [".codex-loop/reports/legacy-repair.json"],
            },
            {
                "status": "PASS",
                "report_digest": digest("legacy-repair-report"),
                "artifact_digest": artifact_b,
            },
            review_handoff=copy.deepcopy(
                state["goal_execution_ledger"]["g1"]["latest_worker"][
                    "review_handoff"
                ]
            ),
        )
        self.harness.runtime._refresh_decision_staleness(state)
        self.assertEqual(
            state["pending_decisions"]["surface-gate"]["status"], "STALE"
        )
        refreshed = {
            "type": "REGISTER_DECISION",
            "decision_id": "surface-gate",
            "decision_context_digest": digest("placeholder"),
            "source_state_version": state["state_version"],
            "valid_through_state_version": state["state_version"] + 20,
            "options": copy.deepcopy(legacy_card["options"]),
            "scope": {
                "goal_id": "g1",
                "dispatch_id": "legacy-repair-dispatch",
                "artifact_digest": artifact_b,
                "artifact_path": "src/result.txt",
            },
            "exclusions": copy.deepcopy(legacy_card["exclusions"]),
        }
        refreshed["decision_context_digest"] = (
            self.harness.runtime._decision_context_digest(state, refreshed)
        )
        result = self.harness.runtime._register_decision(
            state,
            {"actor": "CONTROLLER", "thread_id": "controller-1"},
            refreshed,
        )
        self.assertEqual(result["next_action_code"], "WAIT_DECISION")
        self.assertEqual(
            state["pending_decisions"]["surface-gate"]["status"], "PENDING"
        )

    def test_decision_response_rejects_later_freshness_change(self) -> None:
        self.harness.initialize()
        state = self.harness.runtime.read_state()
        card = {
            "type": "REGISTER_DECISION",
            "decision_id": "freshness-bound-decision",
            "decision_context_digest": digest("placeholder"),
            "source_state_version": state["state_version"],
            "valid_through_state_version": state["state_version"] + 10,
            "options": [
                {"option_id": "continue", "option_effect": "CONTINUE", "preauthorized_capability": "none"},
                {"option_id": "wait", "option_effect": "WAIT", "preauthorized_capability": "none"},
            ],
            "scope": {"goal_id": "g1"},
            "exclusions": ["merge"],
        }
        card["decision_context_digest"] = self.harness.runtime._decision_context_digest(
            state, card
        )
        self.assertTrue(self.request(card)["ok"])
        delta = context_identity_delta(
            changed_paths=["src/auth.py"], head_sha_changed=True, scope_overlap=True
        )
        changed = self.request(
            {
                "type": "RECORD_CONTEXT_FRESHNESS",
                "checkpoint_id": "decision-context-changed",
                "checkpoint": "STEERING_SCOPE",
                "goal_id": "g1",
                "observed_identity_delta": delta,
                "observed_identity_digest": canonical_digest(delta),
                "classification": "HARD_BLOCK",
                "classification_source": "DETERMINISTIC_IDENTITY",
            }
        )
        self.assertTrue(changed["ok"], changed)
        response = self.request(
            {
                "type": "RECORD_DECISION_RESPONSE",
                "steering_id": "freshness-bound-response",
                "normalized_digest": digest("continue despite changed context"),
                "identity_algorithm": "message-item-v1",
                "message_item_id": "freshness-bound-response-message",
                "summary": "continue",
                "classification_reason": "decision reply",
                "decision_id": "freshness-bound-decision",
                "option_id": "continue",
                "decision_context_digest": card["decision_context_digest"],
            }
        )
        self.assertEqual(response["error"]["code"], "DECISION_STALE")

    def test_decision_response_rejects_message_reused_by_other_steering(self) -> None:
        self.harness.initialize()
        shared_message = "shared-steering-message"
        self.assertTrue(
            self.request(
                {
                    "type": "RECORD_STEERING",
                    "steering_id": "existing-constraint",
                    "steering_type": "CONSTRAINT",
                    "normalized_digest": digest("do not deploy"),
                    "identity_algorithm": "message-item-v1",
                    "message_item_id": shared_message,
                    "summary": "do not deploy",
                    "classification_reason": "explicit constraint",
                }
            )["ok"]
        )
        state = self.harness.runtime.read_state()
        card = {
            "type": "REGISTER_DECISION",
            "decision_id": "cross-type-message-decision",
            "decision_context_digest": digest("placeholder"),
            "source_state_version": state["state_version"],
            "valid_through_state_version": state["state_version"] + 2,
            "options": [
                {"option_id": "continue", "option_effect": "CONTINUE", "preauthorized_capability": "none"},
                {"option_id": "wait", "option_effect": "WAIT", "preauthorized_capability": "none"},
            ],
            "scope": {"goal_id": "g1"},
            "exclusions": ["deploy"],
        }
        card["decision_context_digest"] = self.harness.runtime._decision_context_digest(
            state, card
        )
        self.assertTrue(self.request(card)["ok"])
        response = self.request(
            {
                "type": "RECORD_DECISION_RESPONSE",
                "steering_id": "cross-type-message-response",
                "normalized_digest": digest("do not deploy"),
                "identity_algorithm": "message-item-v1",
                "message_item_id": shared_message,
                "summary": "continue",
                "classification_reason": "incorrect reuse",
                "decision_id": "cross-type-message-decision",
                "option_id": "continue",
                "decision_context_digest": card["decision_context_digest"],
            }
        )
        self.assertEqual(response["error"]["code"], "STEERING_IDENTITY_CONFLICT")

    def test_decision_capability_honors_goal_and_milestone_caps(self) -> None:
        definitions = {
            "g1": goal("g1", "m1"),
            "g2": goal("g2", "m1", phase_permissions={"pr_create": True}),
        }
        milestones = [milestone("m1", "ACTIVE")]
        queue = [
            queue_entry("g1", "m1", "READY", 1),
            queue_entry("g2", "m1", "READY", 1),
        ]
        initialized, _ = self.harness.initialize(
            definitions=definitions, milestones=milestones, queue=queue
        )
        self.assertTrue(initialized["ok"], initialized)
        state = self.harness.runtime.read_state()
        self.assertTrue(state["authorization_envelope"]["phase_permissions"]["pr_create"])
        card = {
            "type": "REGISTER_DECISION",
            "decision_id": "borrowed-pr-capability",
            "decision_context_digest": digest("placeholder"),
            "source_state_version": state["state_version"],
            "valid_through_state_version": state["state_version"] + 1,
            "options": [
                {"option_id": "pr", "option_effect": "CREATE_DRAFT_PR", "preauthorized_capability": "pr_create"},
                {"option_id": "wait", "option_effect": "WAIT", "preauthorized_capability": "none"},
            ],
            "scope": {"goal_id": "g1"},
            "exclusions": ["merge", "deploy"],
        }
        card["decision_context_digest"] = self.harness.runtime._decision_context_digest(
            state, card
        )
        rejected = self.request(card)
        self.assertEqual(
            rejected["error"]["code"], "DECISION_CAPABILITY_NOT_AUTHORIZED"
        )

    def test_disabled_ux_policies_are_persisted_and_enforced(self) -> None:
        policy = {
            "human_steering_enabled": False,
            "status_projection_enabled": False,
            "decision_cards_enabled": False,
            "failure_fingerprint_enabled": True,
            "context_freshness_required": True,
            "review_evidence_policy": "deterministic_first",
        }
        initialized, _ = self.harness.initialize(human_control_policy=policy)
        self.assertTrue(initialized["ok"], initialized)
        state = self.harness.runtime.read_state()
        self.assertEqual(state["human_control_policy"], policy)
        self.assertIsNone(state["status_projection_target"])
        self.assertFalse(
            (Path(self.temp.name) / ".codex-loop" / "STATUS.md").exists()
        )
        steering = self.request(
            {
                "type": "RECORD_STEERING",
                "steering_id": "disabled-steering",
                "steering_type": "PAUSE",
                "normalized_digest": digest("disabled-steering"),
                "identity_algorithm": "message-item-v1",
                "message_item_id": "disabled-message",
                "summary": "pause",
                "classification_reason": "policy test",
            }
        )
        self.assertEqual(steering["error"]["code"], "HUMAN_STEERING_DISABLED")
        current = self.harness.runtime.read_state()
        card = {
            "type": "REGISTER_DECISION",
            "decision_id": "disabled-decision",
            "decision_context_digest": digest("placeholder"),
            "source_state_version": current["state_version"],
            "valid_through_state_version": current["state_version"] + 1,
            "options": [
                {"option_id": "continue", "option_effect": "CONTINUE", "preauthorized_capability": "none"},
                {"option_id": "wait", "option_effect": "WAIT", "preauthorized_capability": "none"},
            ],
            "scope": {"goal_id": "g1"},
            "exclusions": ["merge"],
        }
        card["decision_context_digest"] = self.harness.runtime._decision_context_digest(
            current, card
        )
        decision = self.request(card)
        self.assertEqual(decision["error"]["code"], "DECISION_CARDS_DISABLED")

    def test_missing_status_projection_requires_recovery_before_next_mutation(self) -> None:
        initialized, _ = self.harness.initialize()
        self.assertTrue(initialized["ok"], initialized)
        status_path = Path(self.temp.name) / ".codex-loop" / "STATUS.md"
        status_path.unlink()
        before_version = self.harness.version()
        response = self.harness.apply(
            {
                "type": "ACQUIRE_LEASE",
                "routing_turn_id": "projection-turn",
                "lease_id": "projection-lease",
                "owner_kind": "GOAL_TURN",
                "owner_identity": "controller-1",
                "observed_at": "2026-01-01T00:01:00Z",
                "expires_at": "2026-01-01T01:00:00Z",
            }
        )
        self.assertEqual(response["error"]["code"], "RECOVERY_REQUIRED")
        self.assertEqual(self.harness.version(), before_version)
        recovered = self.harness.runtime.recover()
        self.assertTrue(recovered["ok"], recovered)
        self.assertTrue(status_path.exists())
        self.assertIn(f"State version: `{before_version}`", status_path.read_text())

    def test_missing_status_projection_journal_requires_recovery(self) -> None:
        initialized, _ = self.harness.initialize()
        self.assertTrue(initialized["ok"], initialized)
        before_version = self.harness.version()
        journal = (
            Path(self.temp.name)
            / ".codex-loop"
            / "projection-transactions"
            / f"status-v{before_version}.json"
        )
        journal.unlink()
        response = self.harness.apply(
            {
                "type": "ACQUIRE_LEASE",
                "routing_turn_id": "missing-status-journal-turn",
                "lease_id": "missing-status-journal-lease",
                "owner_kind": "GOAL_TURN",
                "owner_identity": "controller-1",
                "observed_at": "2026-01-01T00:01:00Z",
                "expires_at": "2026-01-01T01:00:00Z",
            }
        )
        self.assertEqual(response["error"]["code"], "RECOVERY_REQUIRED")
        self.assertEqual(self.harness.version(), before_version)
        recovered = self.harness.runtime.recover()
        self.assertTrue(recovered["ok"], recovered)
        restored = json.loads(journal.read_text())
        self.assertEqual(restored["status"], "APPLIED")
        self.assertEqual(restored["target_state_version"], before_version)

    def test_surface_acceptance_is_artifact_bound_and_retired_goals_are_skipped(self) -> None:
        surface = {
            "required": True,
            "type": "markdown",
            "artifact_path": "src/review.md",
            "preview_url": None,
            "evidence_refs": [".codex-loop/reports/surface.json"],
            "review_questions": ["Is the exact artifact acceptable?"],
            "decision_gate_id": "surface-decision",
        }
        definitions = {
            "g1": goal("g1", "m1"),
            "g-retired": goal("g-retired", "m1"),
        }
        for goal_id, definition in definitions.items():
            definition["review_surface"] = copy.deepcopy(surface)
            definition["review_surface"]["decision_gate_id"] = (
                f"surface-decision-{goal_id}"
            )
            definition["payload_template_digest"] = goal_definition_digest(
                definition
            )
        self.harness.initialize(
            definitions=definitions,
            queue=[
                queue_entry("g1", "m1", "READY", 1),
                queue_entry("g-retired", "m1", "PLANNED", 1),
            ],
        )
        state = self.harness.runtime.read_state()
        state["goal_execution_ledger"]["g1"].update(
            {
                "status": "COMPLETE",
                "latest_worker": {
                    "dispatch_id": "worker-g1",
                    "status": "PASS",
                    "report_digest": digest("worker-report-g1"),
                    "artifact_digest": digest("artifact-g1"),
                    "roadmap_version": 1,
                    "evidence_paths": [".codex-loop/reports/worker-g1.json"],
                },
            }
        )
        state["goal_execution_ledger"]["g-retired"]["status"] = "RETIRED"
        decision = {
            "decision_id": "surface-decision-g1",
            "decision_context_digest": digest("placeholder"),
            "source_state_version": state["state_version"],
            "valid_through_state_version": state["state_version"] + 10,
            "status": "APPLIED",
            "selected_option_id": "accept",
            "applied_state_version": state["state_version"],
            "options": [
                {
                    "option_id": "accept",
                    "option_effect": "REVIEW_SURFACE_ACCEPTED",
                    "preauthorized_capability": "none",
                },
                {
                    "option_id": "wait",
                    "option_effect": "WAIT",
                    "preauthorized_capability": "none",
                },
            ],
            "scope": {
                "goal_id": "g1",
                "dispatch_id": "worker-g1",
                "artifact_digest": digest("wrong-artifact"),
                "artifact_path": "src/review.md",
            },
            "exclusions": ["merge", "deploy"],
        }
        decision["decision_context_digest"] = (
            self.harness.runtime._decision_context_digest(state, decision)
        )
        state["pending_decisions"]["surface-decision-g1"] = decision
        self.assertEqual(
            AdaptiveStateRuntime._missing_required_surface_decisions(state), ["g1"]
        )
        state["pending_decisions"]["surface-decision-g1"]["scope"][
            "artifact_digest"
        ] = digest("artifact-g1")
        state["pending_decisions"]["surface-decision-g1"][
            "decision_context_digest"
        ] = self.harness.runtime._decision_context_digest(
            state, state["pending_decisions"]["surface-decision-g1"]
        )
        self.assertEqual(
            AdaptiveStateRuntime._missing_required_surface_decisions(state), []
        )
        validation_state = {
            "goal_execution_ledger": {
                "g1": {
                    "status": "COMPLETE",
                    "latest_worker": {
                        "artifact_digest": digest("validation-artifact")
                    },
                },
                "g-retired": {"status": "RETIRED"},
            },
            "validation_requirements": {
                "g1": {"functional": {"required": True}},
                "g-retired": {"functional": {"required": True}},
            },
            "validation_results": {"g1": {"functional": "PASS"}},
            "validation_evidence_identity": {
                "g1": {
                    "functional": {
                        "artifact_digest": digest("validation-artifact")
                    }
                }
            },
            "validation_gate_status": "PENDING",
        }
        AdaptiveStateRuntime._refresh_validation_gate_status(validation_state)
        self.assertEqual(validation_state["validation_gate_status"], "PASS")

    def test_required_review_surface_needs_bound_acceptance_decision(self) -> None:
        definition = goal("g1", "m1")
        definition["review_surface"] = {
            "required": True,
            "type": "markdown",
            "artifact_path": "src/review.md",
            "preview_url": None,
            "evidence_refs": [".codex-loop/reports/review-surface.json"],
            "review_questions": ["Does the artifact match the accepted scope?"],
            "decision_gate_id": "surface-decision-1",
        }
        definition["payload_template_digest"] = goal_definition_digest(definition)
        self.harness.initialize(definitions={"g1": definition})
        claim = self.harness.acquire()
        rejected = self.harness.apply(
            {
                "type": "FINALIZE_LOOP",
                "lease_claim": claim,
                "observed_at": "2026-01-01T00:01:00Z",
                "base_roadmap_version": 1,
                "final_goal_id": "g1",
                "worker_dispatch_id": "missing-worker",
                "artifact_digest": digest("missing-artifact"),
                "code_review_id": "missing-code-review",
                "roadmap_audit_id": "missing-roadmap-audit",
                "final_audit_id": "missing-final-audit",
                "terminal_status": "LOOP_COMPLETE",
                "projection_digest": digest("missing-projection"),
                "finalization_id": "surface-finalization",
                "controller_goal_id": "missing-controller-goal",
                "automation_id": "missing-heartbeat",
            }
        )
        self.assertEqual(
            rejected["error"]["code"], "REQUIRED_REVIEW_SURFACE_NOT_ACCEPTED"
        )

    def test_failure_validation_and_freshness_ledgers(self) -> None:
        definition = goal("g1", "m1")
        definition["validation_matrix"] = complete_validation_matrix()
        definition["payload_template_digest"] = goal_definition_digest(definition)
        self.harness.initialize(definitions={"g1": definition})
        before_worker = self.request(
            {
                "type": "RECORD_VALIDATION",
                "goal_id": "g1",
                "dimension": "functional",
                "status": "PASS",
                "evidence_digest": digest("premature"),
                "artifact_digest": digest("premature-artifact"),
            }
        )
        self.assertEqual(
            before_worker["error"]["code"], "VALIDATION_WORKER_ARTIFACT_REQUIRED"
        )
        worker = self.harness.worker_pass()
        fingerprint = build_failure_fingerprint(
            command="pytest", exit_code=1, output_lines=["FAILED test_x"],
            failing_test_ids=["test_x"], changed_files=["src/x.py"],
            diff_digest=digest("diff"), strategy_id="strategy-a",
            hypothesis_digest=digest("hypothesis"), raw_log_digest=digest("raw"),
        )
        first = self.request({"type": "RECORD_FAILURE", "goal_id": "g1", "fingerprint": fingerprint})
        second = self.request({"type": "RECORD_FAILURE", "goal_id": "g1", "fingerprint": fingerprint})
        self.assertEqual(first["next_action_code"], "PROGRESSING")
        self.assertEqual(second["next_action_code"], "THRASHING_DETECTED")
        state = self.harness.runtime.read_state()
        self.assertEqual(
            state["goal_execution_ledger"]["g1"]["status"],
            "THRASHING_DETECTED",
        )
        claim = self.harness.acquire()
        blocked, _ = self.harness.prepare_outbox(
            claim,
            "DISPATCH",
            "dispatch-after-thrashing",
            {
                "goal_id": "g1",
                "goal_definition_digest": definition["payload_template_digest"],
            },
            target_id="worker-1",
        )
        self.assertEqual(
            blocked["error"]["code"], "FAILURE_CONVERGENCE_BLOCKED"
        )
        released = self.harness.apply(
            {
                "type": "RELEASE_LEASE",
                "lease_claim": claim,
                "observed_at": "2026-01-01T00:01:00Z",
                "reason_code": "CONVERGENCE_BLOCKED",
            }
        )
        self.assertTrue(released["ok"], released)
        validation_content = '{"status":"PASS","test":"pytest"}'
        validation_path = ".codex-loop/reports/validation-functional.json"
        validation_request = self.harness.make_request(
            {"type": "RECORD_VALIDATION", "goal_id": "g1", "dimension": "functional", "status": "PASS", "evidence_digest": digest(validation_content), "artifact_digest": worker["artifact_digest"]},
            evidence_paths=[validation_path],
            artifacts=[{"path": validation_path, "content": validation_content, "digest": digest(validation_content), "media_type": "application/json"}],
        )
        validation = self.harness.runtime.apply(validation_request)
        self.assertEqual(validation["next_action_code"], "PASS")
        delta = context_identity_delta(
            worker_report_digest=worker["report_digest"],
            artifact_digest=worker["artifact_digest"],
            diff_digest=digest("worker-diff"),
        )
        freshness = self.request(
            {"type": "RECORD_CONTEXT_FRESHNESS", "checkpoint_id": "fresh-1", "checkpoint": "CODE_REVIEW", "goal_id": "g1", "dispatch_id": worker["dispatch_id"], "artifact_digest": worker["artifact_digest"], "observed_identity_delta": delta, "observed_identity_digest": canonical_digest(delta), "classification": "FRESH", "classification_source": "DETERMINISTIC_IDENTITY"}
        )
        self.assertEqual(freshness["next_action_code"], "FRESH")
        incomplete_delta = {"head_sha_changed": False}
        incomplete = self.request(
            {
                "type": "RECORD_CONTEXT_FRESHNESS",
                "checkpoint_id": "fresh-incomplete",
                "checkpoint": "CODE_REVIEW",
                "goal_id": "g1",
                "dispatch_id": worker["dispatch_id"],
                "artifact_digest": worker["artifact_digest"],
                "observed_identity_delta": incomplete_delta,
                "observed_identity_digest": canonical_digest(incomplete_delta),
                "classification": "FRESH",
                "classification_source": "DETERMINISTIC_IDENTITY",
            }
        )
        self.assertEqual(incomplete["error"]["code"], "REQUEST_SCHEMA_INVALID")
        changed_delta = context_identity_delta(
            worker_report_digest=worker["report_digest"],
            artifact_digest=worker["artifact_digest"],
            diff_digest=digest("worker-diff"),
            changed_paths=["src/x.py"],
            head_sha_changed=True,
            artifact_digest_changed=True,
        )
        unproven_fresh = self.request(
            {"type": "RECORD_CONTEXT_FRESHNESS", "checkpoint_id": "fresh-unproven", "checkpoint": "CODE_REVIEW", "goal_id": "g1", "dispatch_id": worker["dispatch_id"], "artifact_digest": worker["artifact_digest"], "observed_identity_delta": changed_delta, "observed_identity_digest": canonical_digest(changed_delta), "classification": "FRESH", "classification_source": "MODEL_JUDGMENT_REQUIRED"}
        )
        self.assertEqual(
            unproven_fresh["error"]["code"], "CONTEXT_CLASSIFICATION_UNPROVEN"
        )
        reload_safe_delta = context_identity_delta(
            worker_report_digest=worker["report_digest"],
            artifact_digest=worker["artifact_digest"],
            diff_digest=digest("worker-diff"),
            reload_completed=True,
        )
        safe_reload = self.request(
            {
                "type": "RECORD_CONTEXT_FRESHNESS",
                "checkpoint_id": "reload-safe",
                "checkpoint": "CODE_REVIEW",
                "goal_id": "g1",
                "dispatch_id": worker["dispatch_id"],
                "artifact_digest": worker["artifact_digest"],
                "observed_identity_delta": reload_safe_delta,
                "observed_identity_digest": canonical_digest(reload_safe_delta),
                "classification": "RELOAD_SAFE",
                "classification_source": "DETERMINISTIC_IDENTITY",
            }
        )
        self.assertEqual(safe_reload["next_action_code"], "RELOAD_SAFE")
        reload_changed_delta = context_identity_delta(
            worker_report_digest=worker["report_digest"],
            artifact_digest=worker["artifact_digest"],
            diff_digest=digest("worker-diff"),
            changed_paths=["src/x.py"],
            head_sha_changed=True,
            artifact_digest_changed=True,
            diff_digest_changed=True,
            reload_completed=True,
        )
        unsafe_reload = self.request(
            {
                "type": "RECORD_CONTEXT_FRESHNESS",
                "checkpoint_id": "reload-unsafe",
                "checkpoint": "CODE_REVIEW",
                "goal_id": "g1",
                "dispatch_id": worker["dispatch_id"],
                "artifact_digest": worker["artifact_digest"],
                "observed_identity_delta": reload_changed_delta,
                "observed_identity_digest": canonical_digest(reload_changed_delta),
                "classification": "RELOAD_SAFE",
                "classification_source": "DETERMINISTIC_IDENTITY",
            }
        )
        self.assertEqual(
            unsafe_reload["error"]["code"],
            "CONTEXT_CLASSIFICATION_UNPROVEN",
        )
        mismatched_observed_artifact = context_identity_delta(
            worker_report_digest=worker["report_digest"],
            artifact_digest=digest("different-observed-artifact"),
            diff_digest=digest("worker-diff"),
        )
        stale_observation = self.request(
            {
                "type": "RECORD_CONTEXT_FRESHNESS",
                "checkpoint_id": "reload-stale-observation",
                "checkpoint": "CODE_REVIEW",
                "goal_id": "g1",
                "dispatch_id": worker["dispatch_id"],
                "artifact_digest": worker["artifact_digest"],
                "observed_identity_delta": mismatched_observed_artifact,
                "observed_identity_digest": canonical_digest(
                    mismatched_observed_artifact
                ),
                "classification": "FRESH",
                "classification_source": "DETERMINISTIC_IDENTITY",
            }
        )
        self.assertEqual(
            stale_observation["error"]["code"],
            "CONTEXT_ARTIFACT_IDENTITY_MISMATCH",
        )
        changed_fingerprint = build_failure_fingerprint(
            command="pytest",
            exit_code=1,
            output_lines=["FAILED test_after_freshness"],
            failing_test_ids=["test_after_freshness"],
            changed_files=["src/x.py"],
            diff_digest=digest("changed-after-freshness"),
            strategy_id="strategy-b",
            hypothesis_digest=digest("hypothesis-b"),
            raw_log_digest=digest("raw-b"),
        )
        self.assertTrue(
            self.request(
                {"type": "RECORD_FAILURE", "goal_id": "g1", "fingerprint": changed_fingerprint}
            )["ok"]
        )
        with self.assertRaisesRegex(AssertionError, "CONTEXT_FRESHNESS_REQUIRED"):
            self.harness.review(
                "CODE_REVIEW", "REVIEW_PASS", worker, record_freshness=False
            )
        stale_delta = context_identity_delta(
            worker_report_digest=worker["report_digest"],
            artifact_digest=digest("different"),
            diff_digest=digest("worker-diff"),
        )
        stale_identity = self.request(
            {"type": "RECORD_CONTEXT_FRESHNESS", "checkpoint_id": "fresh-stale", "checkpoint": "CODE_REVIEW", "goal_id": "g1", "dispatch_id": worker["dispatch_id"], "artifact_digest": digest("different"), "observed_identity_delta": stale_delta, "observed_identity_digest": canonical_digest(stale_delta), "classification": "FRESH", "classification_source": "DETERMINISTIC_IDENTITY"}
        )
        self.assertEqual(
            stale_identity["error"]["code"], "CONTEXT_ARTIFACT_IDENTITY_MISMATCH"
        )
        irrelevant_delta = context_identity_delta(
            changed_paths=["src/x.py"], scope_overlap=True
        )
        unproven = self.request(
            {"type": "RECORD_CONTEXT_FRESHNESS", "checkpoint_id": "fresh-2", "checkpoint": "STEERING_SCOPE", "goal_id": "g1", "observed_identity_delta": irrelevant_delta, "observed_identity_digest": canonical_digest(irrelevant_delta), "classification": "CHANGED_IRRELEVANT", "classification_source": "DETERMINISTIC_SCOPE_RULE"}
        )
        self.assertFalse(unproven["ok"])
        self.assertEqual(unproven["error"]["code"], "CONTEXT_CLASSIFICATION_UNPROVEN")

    def test_runtime_marks_strategy_exhausted_after_last_repair_attempt(self) -> None:
        definition = goal("g1", "m1")
        milestones = [milestone("m1", "ACTIVE")]
        authorization = authorization_envelope({"g1": definition}, milestones)
        authorization["repair_policy"]["max_repair_attempts_per_goal"] = 1
        initialized, _ = self.harness.initialize(
            definitions={"g1": definition},
            milestones=milestones,
            authorization=authorization,
        )
        self.assertTrue(initialized["ok"], initialized)
        self.harness.ensure_controller_goal("m1")
        self.harness.register_control_result(
            "THREAD",
            "worker-thread-create-exhaustion",
            "controller-1",
            {"role_kind": "WORKER"},
            {
                "thread_id": "worker-1",
                "role_kind": "WORKER",
                "worktree_path": ".",
            },
        )

        for attempt in (1, 2):
            claim = self.harness.acquire()
            dispatch_id = f"dispatch-exhaustion-{attempt}"
            prepared, payload = self.harness.prepare_outbox(
                claim,
                "DISPATCH",
                dispatch_id,
                {
                    "goal_id": "g1",
                    "goal_definition_digest": definition["payload_template_digest"],
                },
                target_id="worker-1",
            )
            self.assertTrue(prepared["ok"], prepared)
            sent = self.harness.mark_sent(
                claim,
                "DISPATCH",
                dispatch_id,
                payload,
                target_id="worker-1",
            )
            self.assertTrue(sent["ok"], sent)
            result = {
                "status": "FAIL",
                "artifact_digest": digest(f"artifact-exhaustion-{attempt}"),
            }
            report_content = self.harness.formal_report_content(
                "DISPATCH", dispatch_id, result
            )
            acked = self.harness.ack_outbox(
                claim,
                "DISPATCH",
                dispatch_id,
                payload,
                target_id="worker-1",
                result={
                    **result,
                    "report_digest": digest(report_content),
                },
                report_content=report_content,
            )
            self.assertTrue(acked["ok"], acked)
            fingerprint = build_failure_fingerprint(
                command="pytest",
                exit_code=1,
                output_lines=["FAILED test_x"],
                failing_test_ids=["test_x"],
                changed_files=["src/x.py"],
                diff_digest=digest("same-diff"),
                strategy_id="same-strategy",
                hypothesis_digest=digest("same-hypothesis"),
                raw_log_digest=digest(f"raw-{attempt}"),
            )
            recorded = self.request(
                {
                    "type": "RECORD_FAILURE",
                    "goal_id": "g1",
                    "fingerprint": fingerprint,
                }
            )
            expected = "PROGRESSING" if attempt == 1 else "STRATEGY_EXHAUSTED"
            self.assertEqual(recorded["next_action_code"], expected)

        state = self.harness.runtime.read_state()
        self.assertEqual(
            state["goal_execution_ledger"]["g1"]["status"],
            "STRATEGY_EXHAUSTED",
        )

    def test_later_freshness_blocker_invalidates_review_checkpoint(self) -> None:
        definition = goal("g1", "m1")
        definition["validation_matrix"] = complete_validation_matrix()
        definition["payload_template_digest"] = goal_definition_digest(definition)
        self.harness.initialize(definitions={"g1": definition})
        worker = self.harness.worker_pass()
        content = '{"status":"PASS","test":"pytest"}'
        path = ".codex-loop/reports/freshness-validation.json"
        recorded = self.harness.runtime.apply(
            self.harness.make_request(
                {
                    "type": "RECORD_VALIDATION",
                    "goal_id": "g1",
                    "dimension": "functional",
                    "status": "PASS",
                    "evidence_digest": digest(content),
                    "artifact_digest": worker["artifact_digest"],
                },
                evidence_paths=[path],
                artifacts=[
                    {
                        "path": path,
                        "content": content,
                        "digest": digest(content),
                        "media_type": "application/json",
                    }
                ],
            )
        )
        self.assertTrue(recorded["ok"], recorded)
        delta = context_identity_delta(
            worker_report_digest=worker["report_digest"],
            artifact_digest=worker["artifact_digest"],
            diff_digest=digest("freshness-diff"),
        )
        for checkpoint_id, checkpoint, classification in (
            ("review-fresh", "CODE_REVIEW", "FRESH"),
            ("later-block", "WORKER_RECOVERY", "HARD_BLOCK"),
        ):
            result = self.request(
                {
                    "type": "RECORD_CONTEXT_FRESHNESS",
                    "checkpoint_id": checkpoint_id,
                    "checkpoint": checkpoint,
                    "goal_id": "g1",
                    "dispatch_id": worker["dispatch_id"],
                    "artifact_digest": worker["artifact_digest"],
                    "observed_identity_delta": delta,
                    "observed_identity_digest": canonical_digest(delta),
                    "classification": classification,
                    "classification_source": "DETERMINISTIC_IDENTITY",
                }
            )
            self.assertTrue(result["ok"], result)
        with self.assertRaisesRegex(AssertionError, "CONTEXT_FRESHNESS_REQUIRED"):
            self.harness.review(
                "CODE_REVIEW", "REVIEW_PASS", worker, record_freshness=False
            )

    def test_changed_irrelevant_requires_unchanged_critical_identity(self) -> None:
        self.harness.initialize()
        changed_head = context_identity_delta(
            changed_paths=["docs/other.md"], head_sha_changed=True
        )
        rejected = self.request(
            {
                "type": "RECORD_CONTEXT_FRESHNESS",
                "checkpoint_id": "irrelevant-changed-head",
                "checkpoint": "STEERING_SCOPE",
                "goal_id": "g1",
                "observed_identity_delta": changed_head,
                "observed_identity_digest": canonical_digest(changed_head),
                "classification": "CHANGED_IRRELEVANT",
                "classification_source": "DETERMINISTIC_SCOPE_RULE",
            }
        )
        self.assertEqual(
            rejected["error"]["code"], "CONTEXT_CLASSIFICATION_UNPROVEN"
        )
        unrelated_dirty = context_identity_delta(
            changed_paths=["docs/other.md"], dirty_boundary_changed=True
        )
        accepted = self.request(
            {
                "type": "RECORD_CONTEXT_FRESHNESS",
                "checkpoint_id": "irrelevant-unrelated-dirty",
                "checkpoint": "STEERING_SCOPE",
                "goal_id": "g1",
                "observed_identity_delta": unrelated_dirty,
                "observed_identity_digest": canonical_digest(unrelated_dirty),
                "classification": "CHANGED_IRRELEVANT",
                "classification_source": "DETERMINISTIC_SCOPE_RULE",
            }
        )
        self.assertEqual(accepted["next_action_code"], "CHANGED_IRRELEVANT")

    def test_context_checkpoint_semantic_retry_is_idempotent(self) -> None:
        self.harness.initialize()
        delta = context_identity_delta()
        mutation = {
            "type": "RECORD_CONTEXT_FRESHNESS",
            "checkpoint_id": "idempotent-checkpoint",
            "checkpoint": "GOAL_DISPATCH",
            "goal_id": "g1",
            "observed_identity_delta": delta,
            "observed_identity_digest": canonical_digest(delta),
            "classification": "FRESH",
            "classification_source": "DETERMINISTIC_IDENTITY",
        }
        first = self.request(mutation)
        replay = self.request(mutation)
        self.assertEqual(first["operation_status"], "CONTEXT_FRESHNESS_RECORDED")
        self.assertEqual(
            replay["operation_status"], "CONTEXT_CHECK_ALREADY_RECORDED"
        )

    def test_required_validation_failure_sets_failed_gate(self) -> None:
        definition = goal("g1", "m1")
        definition["validation_matrix"] = complete_validation_matrix()
        definition["payload_template_digest"] = goal_definition_digest(definition)
        self.harness.initialize(definitions={"g1": definition})
        worker = self.harness.worker_pass()
        content = '{"status":"FAIL","test":"pytest"}'
        path = ".codex-loop/reports/validation-fail.json"
        failed = self.harness.runtime.apply(
            self.harness.make_request(
                {
                    "type": "RECORD_VALIDATION",
                    "goal_id": "g1",
                    "dimension": "functional",
                    "status": "FAIL",
                    "evidence_digest": digest(content),
                    "artifact_digest": worker["artifact_digest"],
                },
                evidence_paths=[path],
                artifacts=[
                    {
                        "path": path,
                        "content": content,
                        "digest": digest(content),
                        "media_type": "application/json",
                    }
                ],
            )
        )
        self.assertEqual(failed["next_action_code"], "FAIL")
        self.assertEqual(
            self.harness.runtime.read_state()["validation_gate_status"], "FAIL"
        )

    def test_status_projection_prefers_goal_with_sent_dispatch(self) -> None:
        definitions = {"g1": goal("g1", "m1"), "g2": goal("g2", "m1")}
        queue = [
            queue_entry("g1", "m1", "READY", 1),
            queue_entry("g2", "m1", "READY", 1),
        ]
        initialized, _ = self.harness.initialize(definitions=definitions, queue=queue)
        self.assertTrue(initialized["ok"], initialized)
        self.harness.ensure_controller_goal("m1")
        self.harness.register_control_result(
            "THREAD",
            "worker-thread-status",
            "controller-1",
            {"role_kind": "WORKER"},
            {"thread_id": "worker-status", "role_kind": "WORKER", "worktree_path": "."},
        )
        claim = self.harness.acquire()
        prepared, payload = self.harness.prepare_outbox(
            claim,
            "DISPATCH",
            "dispatch-g2-status",
            {
                "goal_id": "g2",
                "goal_definition_digest": definitions["g2"]["payload_template_digest"],
            },
            target_id="worker-status",
        )
        self.assertTrue(prepared["ok"], prepared)
        sent = self.harness.mark_sent(
            claim,
            "DISPATCH",
            "dispatch-g2-status",
            payload,
            target_id="worker-status",
        )
        self.assertTrue(sent["ok"], sent)
        status = (Path(self.temp.name) / ".codex-loop" / "STATUS.md").read_text()
        self.assertIn("Active Goal: `g2`", status)

    def test_worker_ack_replaces_validation_evidence_for_previous_artifact(self) -> None:
        definition = goal("g1", "m1")
        definition["validation_matrix"] = complete_validation_matrix()
        definition["payload_template_digest"] = goal_definition_digest(definition)
        self.harness.initialize(definitions={"g1": definition})
        first_worker = self.harness.worker_pass("g1")
        content = '{"status":"PASS","attempt":1}'
        path = ".codex-loop/reports/validation-first-worker.json"
        recorded = self.harness.runtime.apply(
            self.harness.make_request(
                {
                    "type": "RECORD_VALIDATION",
                    "goal_id": "g1",
                    "dimension": "functional",
                    "status": "PASS",
                    "evidence_digest": digest(content),
                    "artifact_digest": first_worker["artifact_digest"],
                },
                evidence_paths=[path],
                artifacts=[
                    {
                        "path": path,
                        "content": content,
                        "digest": digest(content),
                        "media_type": "application/json",
                    }
                ],
            )
        )
        self.assertEqual(recorded["next_action_code"], "PASS")
        delta = context_identity_delta(
            worker_report_digest=first_worker["report_digest"],
            artifact_digest=first_worker["artifact_digest"],
            diff_digest=digest("first-worker-diff"),
        )
        self.assertTrue(
            self.request(
                {
                    "type": "RECORD_CONTEXT_FRESHNESS",
                    "checkpoint_id": "repair-review-freshness",
                    "checkpoint": "CODE_REVIEW",
                    "goal_id": "g1",
                    "dispatch_id": first_worker["dispatch_id"],
                    "artifact_digest": first_worker["artifact_digest"],
                    "observed_identity_delta": delta,
                    "observed_identity_digest": canonical_digest(delta),
                    "classification": "FRESH",
                    "classification_source": "DETERMINISTIC_IDENTITY",
                }
            )["ok"]
        )
        self.harness.review("CODE_REVIEW", "REVIEW_NEEDS_REPAIR", first_worker)
        second_worker = self.harness.worker_pass("g1")
        self.assertNotEqual(
            first_worker["artifact_digest"], second_worker["artifact_digest"]
        )
        state = self.harness.runtime.read_state()
        self.assertEqual(state["validation_gate_status"], "PASS")
        evidence = state["validation_evidence_identity"]["g1"]["functional"]
        self.assertEqual(evidence["artifact_digest"], second_worker["artifact_digest"])
        self.assertEqual(evidence["worker_dispatch_id"], second_worker["dispatch_id"])
        self.assertNotEqual(evidence["artifact_digest"], first_worker["artifact_digest"])
        second_delta = context_identity_delta(
            worker_report_digest=second_worker["report_digest"],
            artifact_digest=second_worker["artifact_digest"],
            diff_digest=digest("second-worker-diff"),
        )
        self.assertTrue(
            self.request(
                {
                    "type": "RECORD_CONTEXT_FRESHNESS",
                    "checkpoint_id": "second-worker-review-freshness",
                    "checkpoint": "CODE_REVIEW",
                    "goal_id": "g1",
                    "dispatch_id": second_worker["dispatch_id"],
                    "artifact_digest": second_worker["artifact_digest"],
                    "observed_identity_delta": second_delta,
                    "observed_identity_digest": canonical_digest(second_delta),
                    "classification": "FRESH",
                    "classification_source": "DETERMINISTIC_IDENTITY",
                }
            )["ok"]
        )
        review_id = self.harness.review("CODE_REVIEW", "REVIEW_PASS", second_worker)
        self.assertIsInstance(review_id, str)

    def test_explicit_v1_to_v2_migration(self) -> None:
        self.harness.initialize()
        runtime = self.harness.runtime
        state = runtime.read_state()
        for key in runtime._empty_v2_fields(state["state_version"]):
            state.pop(key, None)
        state["schema_version"] = 1
        runtime.status_path.unlink(missing_ok=True)
        runtime.state_path.write_bytes(runtime._render_state(state))
        source_digest = "sha256:" + hashlib.sha256(runtime.state_path.read_bytes()).hexdigest()
        legacy_bytes = runtime.state_path.read_bytes()
        migration_required = self.request(
            {
                "type": "RECORD_STEERING",
                "steering_id": "legacy-steering",
                "steering_type": "PAUSE",
                "normalized_digest": digest("legacy-steering"),
                "identity_algorithm": "message-item-v1",
                "message_item_id": "legacy-message",
                "summary": "pause legacy state",
                "classification_reason": "migration test",
            },
            expected=state["state_version"],
        )
        self.assertEqual(
            migration_required["error"]["code"], "STATE_MIGRATION_REQUIRED"
        )
        self.assertEqual(runtime.state_path.read_bytes(), legacy_bytes)
        unauthorized_request = self.harness.make_request(
            {"type": "MIGRATE_V1_TO_V2", "source_state_digest": source_digest},
            expected=state["state_version"],
        )
        unauthorized_request["actor"] = "WORKER"
        unauthorized_request["thread_id"] = "unregistered-worker"
        unauthorized = runtime.apply(unauthorized_request)
        self.assertEqual(unauthorized["error"]["code"], "STEERING_ACTOR_INVALID")
        self.assertEqual(runtime.state_path.read_bytes(), legacy_bytes)
        response = self.request(
            {"type": "MIGRATE_V1_TO_V2", "source_state_digest": source_digest},
            expected=state["state_version"],
        )
        self.assertEqual(response["operation_status"], "SCHEMA_V2_MIGRATED")
        self.assertEqual(runtime.read_state()["schema_version"], 2)
        self.assertEqual(
            runtime.read_state()["worker_validation_projection_contract_version"],
            0,
        )
        state_bytes = runtime.state_path.read_bytes()
        repeated = self.request(
            {"type": "MIGRATE_V1_TO_V2", "source_state_digest": digest("already-v2")}
        )
        self.assertEqual(repeated["operation_status"], "SCHEMA_V2_ALREADY_APPLIED")
        self.assertEqual(runtime.state_path.read_bytes(), state_bytes)

    def test_schema_v2_missing_review_contract_requires_explicit_migration(self) -> None:
        self.harness.initialize()
        runtime = self.harness.runtime
        state = runtime.read_state()
        state.pop("review_contract_version")
        legacy_bytes = runtime._render_state(state)
        source_digest = "sha256:" + hashlib.sha256(legacy_bytes).hexdigest()
        runtime.state_path.write_bytes(legacy_bytes)

        with self.assertRaisesRegex(
            RuntimeRejection, "CANONICAL_STATE_SCHEMA_INVALID"
        ):
            runtime.read_state()

        before = persisted_snapshot(Path(self.temp.name))
        wrong_digest = runtime.apply(
            self.harness.make_request(
                {
                    "type": "MIGRATE_V1_TO_V2",
                    "source_state_digest": digest("wrong-review-contract-source"),
                },
                expected=state["state_version"],
            )
        )
        self.assertEqual(
            wrong_digest["error"]["code"], "MIGRATION_SOURCE_DIGEST_MISMATCH"
        )
        self.assertEqual(persisted_snapshot(Path(self.temp.name)), before)

        migrated = runtime.apply(
            self.harness.make_request(
                {
                    "type": "MIGRATE_V1_TO_V2",
                    "source_state_digest": source_digest,
                },
                expected=state["state_version"],
            )
        )
        self.assertTrue(migrated["ok"], migrated)
        self.assertEqual(
            migrated["operation_status"], "REVIEW_CONTRACT_V2_MIGRATED"
        )
        migrated_state = runtime.read_state()
        self.assertEqual(migrated_state["review_contract_version"], 2)
        self.assertEqual(migrated_state["state_version"], state["state_version"] + 1)

    def test_populated_v1_assurance_migration_requires_revalidation(self) -> None:
        self.harness.initialize()
        worker = self.harness.worker_pass()
        code_review_id = self.harness.review(
            "CODE_REVIEW", "REVIEW_PASS", worker
        )
        roadmap_audit_id = self.harness.review(
            "ROADMAP_AUDIT",
            "ROADMAP_AUDIT_PASS_FINAL_CANDIDATE",
            worker,
            code_review_id=code_review_id,
        )
        final_audit_id = self.harness.review(
            "FINAL_AUDIT",
            "FINAL_REVIEW_PASS",
            worker,
            code_review_id=code_review_id,
            roadmap_audit_id=roadmap_audit_id,
        )

        runtime = self.harness.runtime
        state = runtime.read_state()
        for key in runtime._empty_v2_fields(state["state_version"]):
            state.pop(key, None)
        state["schema_version"] = 1
        state["assurance_ledger"][roadmap_audit_id].pop("code_review_id", None)
        state["assurance_ledger"][roadmap_audit_id].pop(
            "estimate_revision", None
        )
        for key in (
            "code_review_id",
            "roadmap_audit_id",
            "final_audit_context_digest",
        ):
            state["assurance_ledger"][final_audit_id].pop(key, None)
        runtime.status_path.unlink(missing_ok=True)
        legacy_bytes = runtime._render_state(state)
        runtime.state_path.write_bytes(legacy_bytes)
        source_digest = "sha256:" + hashlib.sha256(legacy_bytes).hexdigest()

        migrated = self.request(
            {
                "type": "MIGRATE_V1_TO_V2",
                "source_state_digest": source_digest,
            },
            expected=state["state_version"],
        )
        self.assertTrue(migrated["ok"], migrated)
        migrated_state = runtime.read_state()
        self.assertEqual(migrated_state["review_contract_version"], 2)
        self.assertTrue(
            all(
                review.get("legacy_revalidation_required") is True
                for review in migrated_state["assurance_ledger"].values()
            )
        )
        migrated_roadmap = migrated_state["assurance_ledger"][roadmap_audit_id]
        migrated_final = migrated_state["assurance_ledger"][final_audit_id]
        self.assertEqual(migrated_roadmap["code_review_id"], code_review_id)
        self.assertNotIn("estimate_revision", migrated_roadmap)
        self.assertEqual(migrated_final["code_review_id"], code_review_id)
        self.assertEqual(
            migrated_final["roadmap_audit_id"], roadmap_audit_id
        )
        self.assertNotIn("final_audit_context_digest", migrated_final)
        with self.assertRaisesRegex(RuntimeRejection, "REVIEW_CHAIN_INVALID"):
            runtime._require_review(
                migrated_state,
                code_review_id,
                "CODE_REVIEW",
                worker["goal_id"],
                worker["dispatch_id"],
                worker["artifact_digest"],
                {"REVIEW_PASS"},
            )

    def test_runtime_rejects_duplicate_review_surface_decision_ids(self) -> None:
        surface = {
            "required": True,
            "type": "markdown",
            "artifact_path": "src/review.md",
            "preview_url": None,
            "evidence_refs": [".codex-loop/reports/review.json"],
            "review_questions": ["Is this acceptable?"],
            "decision_gate_id": "shared-surface-decision",
        }
        first = goal("g1", "m1")
        second = goal("g2", "m1")
        for definition in (first, second):
            definition["review_surface"] = copy.deepcopy(surface)
            definition["payload_template_digest"] = goal_definition_digest(definition)
        result, _ = self.harness.initialize(
            definitions={"g1": first, "g2": second},
            queue=[
                queue_entry("g1", "m1", "READY", 1),
                queue_entry("g2", "m1", "READY", 1),
            ],
        )
        self.assertEqual(
            result["error"]["code"], "REVIEW_SURFACE_DECISION_ID_CONFLICT"
        )

    def test_migrated_v1_state_requires_freshness_before_review(self) -> None:
        self.harness.initialize()
        runtime = self.harness.runtime
        state = runtime.read_state()
        for key in runtime._empty_v2_fields(state["state_version"]):
            state.pop(key, None)
        state["schema_version"] = 1
        runtime.status_path.unlink(missing_ok=True)
        runtime.state_path.write_bytes(runtime._render_state(state))
        source_digest = "sha256:" + hashlib.sha256(
            runtime.state_path.read_bytes()
        ).hexdigest()
        migrated = self.request(
            {"type": "MIGRATE_V1_TO_V2", "source_state_digest": source_digest},
            expected=state["state_version"],
        )
        self.assertTrue(migrated["ok"], migrated)
        worker = self.harness.worker_pass()
        with self.assertRaisesRegex(AssertionError, "CONTEXT_FRESHNESS_REQUIRED"):
            self.harness.review(
                "CODE_REVIEW", "REVIEW_PASS", worker, record_freshness=False
            )

    def test_status_projection_crash_stages_recover_from_canonical_state(self) -> None:
        for stage in STATUS_PROJECTION_STAGES:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                harness = Harness(Path(directory))
                harness.runtime = AdaptiveStateRuntime(directory, crash_at=stage)
                with self.assertRaises(InjectedCrash):
                    harness.initialize()
                runtime = AdaptiveStateRuntime(directory)
                recovered = runtime.recover()
                self.assertTrue(recovered["ok"], recovered)
                state = runtime.read_state()
                status = (Path(directory) / ".codex-loop" / "STATUS.md").read_text()
                self.assertIn(f"State version: `{state['state_version']}`", status)

    def test_v1_to_v2_migration_recovers_at_every_persistence_stage(self) -> None:
        for stage in PERSISTENT_STAGES:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                harness = Harness(Path(directory))
                harness.initialize(dashboard_required=True)
                state = harness.runtime.read_state()
                for key in harness.runtime._empty_v2_fields(state["state_version"]):
                    state.pop(key, None)
                state["schema_version"] = 1
                harness.runtime.status_path.unlink(missing_ok=True)
                harness.runtime.state_path.write_bytes(harness.runtime._render_state(state))
                source_digest = "sha256:" + hashlib.sha256(
                    harness.runtime.state_path.read_bytes()
                ).hexdigest()
                harness.runtime = AdaptiveStateRuntime(directory, crash_at=stage)
                with self.assertRaises(InjectedCrash):
                    harness.apply(
                        {"type": "MIGRATE_V1_TO_V2", "source_state_digest": source_digest},
                        expected=state["state_version"],
                    )
                runtime = AdaptiveStateRuntime(directory)
                recovered = runtime.recover()
                self.assertTrue(recovered["ok"], recovered)
                if runtime.read_state()["schema_version"] == 1:
                    replay = runtime.apply(
                        harness.make_request(
                            {"type": "MIGRATE_V1_TO_V2", "source_state_digest": source_digest},
                            expected=state["state_version"],
                        )
                    )
                    self.assertTrue(replay["ok"], replay)
                self.assertEqual(runtime.read_state()["schema_version"], 2)

    def test_fingerprint_cli_is_json_only_and_deterministic(self) -> None:
        payload = {
            "command": "pytest",
            "exit_code": 1,
            "output_lines": ["2026-01-01T00:00:00Z FAILED test_x token=secret"],
            "failing_test_ids": ["test_x"],
            "changed_files": ["src/x.py"],
            "diff_digest": digest("diff"),
            "strategy_id": "strategy-a",
            "hypothesis_digest": digest("hypothesis"),
            "raw_log_digest": digest("raw"),
        }
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "adaptive_state_runtime.py"), "--fingerprint-normalize"],
            input=json.dumps(payload), text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertEqual(response["status"], "FAILURE_FINGERPRINT_NORMALIZED")
        self.assertNotIn("secret", json.dumps(response["fingerprint"]))


if __name__ == "__main__":
    unittest.main()
