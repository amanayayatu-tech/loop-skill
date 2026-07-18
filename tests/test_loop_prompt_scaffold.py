from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "codex-loop-prompt-architect" / "scripts" / "loop_prompt_scaffold.py"
VALIDATOR = ROOT / "codex-loop-prompt-architect" / "scripts" / "validate_skill.py"
INSTALLER = ROOT / "scripts" / "install.sh"
SPEC = importlib.util.spec_from_file_location("loop_prompt_scaffold", SCRIPT)
assert SPEC and SPEC.loader
scaffold = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scaffold)


def base_payload() -> dict:
    payload = {
        "objective": "Implement one scoped feature",
        "repo": "/tmp/example-repo",
        "repo_mode": "existing_git",
        "branch": "codex/example",
        "base_branch": "main",
        "target_branch": "codex/example",
        "workers": [
            {
                "role": "implementation",
                "scope": "write the scoped feature",
                "permission": "workspace_write",
                "allowed": ["src/**", "tests/**"],
            }
        ],
        "permissions": {"implementation": "workspace_write"},
        "allowed": ["src/**", "tests/**"],
        "forbidden": ["secrets", "production deploy"],
        "validation": ["python3 -m unittest"],
        "acceptance_criteria": ["Feature behavior is covered by tests"],
        "goals": [
            {
                "goal_id": "G1",
                "worker_role": "implementation",
                "objective": "Implement one scoped feature",
                "success_criteria": ["Feature behavior is covered by tests"],
                "phase_permissions": {"branch_create": True},
            }
        ],
        "evidence": "local checks",
        "claim": "candidate implementation only",
        "state": ".codex-loop/LOOP_STATE.md",
        "source_artifacts": ["SELF_CONTAINED"],
    }
    payload.update(copy.deepcopy(scaffold.DEFAULTS))
    payload["_provided_keys"] = sorted(key for key in payload if not key.startswith("_"))
    payload["_unknown_keys"] = []
    return payload


class ScaffoldValidationTests(unittest.TestCase):
    def test_valid_base_payload(self) -> None:
        self.assertEqual(scaffold.validation_errors(base_payload()), [])

    def test_chinese_metered_runtime_requires_policy(self) -> None:
        payload = base_payload()
        payload["objective"] = "调用真实大模型接口进行付费评分一百次"
        workers = scaffold.normalize_workers(payload)
        self.assertTrue(scaffold.metered_runtime_requested(payload, workers))
        self.assertIn("cost_cap_usd_or_metered_runtime_policy", scaffold.validation_errors(payload))

    def test_chinese_model_documentation_does_not_trigger_cost_gate(self) -> None:
        payload = base_payload()
        payload["objective"] = "撰写真实大模型行业介绍文档，不运行模型评分"
        workers = scaffold.normalize_workers(payload)
        self.assertFalse(scaffold.metered_runtime_requested(payload, workers))

    def test_fake_word_does_not_bypass_cost_gate(self) -> None:
        payload = base_payload()
        payload["objective"] = "Use a real LLM to detect fake reviews"
        workers = scaffold.normalize_workers(payload)
        self.assertTrue(scaffold.metered_runtime_requested(payload, workers))
        self.assertFalse(scaffold.metered_runtime_policy_supplied(payload, workers))

    def test_explicit_positive_cost_cap_authorizes(self) -> None:
        payload = base_payload()
        payload["objective"] = "运行真实模型评分"
        payload["cost_cap_usd"] = "1000"
        self.assertNotIn("cost_cap_usd_or_metered_runtime_policy", scaffold.validation_errors(payload))

    def test_decimal_cost_cap_matches_public_schema(self) -> None:
        for value in ("1.0", "0.50", 1.0):
            payload = base_payload()
            payload["objective"] = "Run a real LLM evaluation"
            payload["cost_cap_usd"] = value
            self.assertNotIn("cost_cap_usd:must_be_positive", scaffold.validation_errors(payload))

    def test_formatted_or_boolean_structured_caps_are_rejected(self) -> None:
        for key, value in (
            ("cost_cap_usd", "$100"),
            ("cost_cap_usd", True),
            ("call_cap", "1,000"),
            ("token_cap", 1.5),
        ):
            payload = base_payload()
            payload[key] = value
            self.assertIn(f"{key}:must_be_positive", scaffold.validation_errors(payload))

    def test_unbounded_metered_policy_is_rejected(self) -> None:
        payload = base_payload()
        payload["objective"] = "Run a real LLM evaluation"
        payload["metered_runtime_policy"] = "authorized unlimited usage"
        errors = scaffold.validation_errors(payload)
        self.assertIn("metered_runtime_policy:must_defer_forbid_or_bound_usage", errors)
        self.assertIn("cost_cap_usd_or_metered_runtime_policy", errors)

    def test_bound_word_without_positive_amount_is_rejected(self) -> None:
        payload = base_payload()
        payload["objective"] = "Run a real LLM evaluation"
        payload["metered_runtime_policy"] = "at most zero calls"
        self.assertIn(
            "metered_runtime_policy:must_defer_forbid_or_bound_usage",
            scaffold.validation_errors(payload),
        )

    def test_bounded_metered_policy_with_amount_is_accepted(self) -> None:
        payload = base_payload()
        payload["objective"] = "Run a real LLM evaluation"
        payload["metered_runtime_policy"] = "at most 25 calls"
        self.assertNotIn(
            "cost_cap_usd_or_metered_runtime_policy",
            scaffold.validation_errors(payload),
        )

    def test_negated_real_llm_does_not_trigger_cost_gate(self) -> None:
        payload = base_payload()
        payload["objective"] = "Implement a local parser without real LLM calls"
        workers = scaffold.normalize_workers(payload)
        self.assertFalse(scaffold.metered_runtime_requested(payload, workers))

    def test_provider_runtime_action_triggers_cost_gate(self) -> None:
        payload = base_payload()
        payload["objective"] = "Run GPT-5 scoring on the local fixture"
        workers = scaffold.normalize_workers(payload)
        self.assertTrue(scaffold.metered_runtime_requested(payload, workers))
        self.assertIn("cost_cap_usd_or_metered_runtime_policy", scaffold.validation_errors(payload))

    def test_provider_name_in_docs_or_adapter_work_does_not_trigger_cost_gate(self) -> None:
        payload = base_payload()
        payload["objective"] = "Document the OpenAI format and implement a Kimi adapter without live calls"
        workers = scaffold.normalize_workers(payload)
        self.assertFalse(scaffold.metered_runtime_requested(payload, workers))

    def test_named_provider_call_still_triggers_cost_gate(self) -> None:
        payload = base_payload()
        payload["objective"] = "Run Kimi on the evaluation fixture"
        workers = scaffold.normalize_workers(payload)
        self.assertTrue(scaffold.metered_runtime_requested(payload, workers))

    def test_negated_provider_runtime_does_not_trigger_cost_gate(self) -> None:
        payload = base_payload()
        payload["objective"] = "Document the evaluation but do not run GPT-5"
        workers = scaffold.normalize_workers(payload)
        self.assertFalse(scaffold.metered_runtime_requested(payload, workers))

    def test_duration_only_is_not_a_cost_or_usage_cap(self) -> None:
        payload = base_payload()
        payload["objective"] = "Run a real LLM evaluation"
        payload["metered_runtime_policy"] = "at most 1 day"
        self.assertIn(
            "metered_runtime_policy:must_defer_forbid_or_bound_usage",
            scaffold.validation_errors(payload),
        )

    def test_request_cap_is_a_valid_metered_bound(self) -> None:
        payload = base_payload()
        payload["objective"] = "Run a real LLM evaluation"
        payload["metered_runtime_policy"] = "at most 25 requests"
        self.assertNotIn(
            "cost_cap_usd_or_metered_runtime_policy",
            scaffold.validation_errors(payload),
        )

    def test_chinese_call_cap_is_a_valid_metered_bound(self) -> None:
        payload = base_payload()
        payload["objective"] = "运行真实模型评分"
        payload["metered_runtime_policy"] = "最多调用 25 次"
        self.assertNotIn(
            "cost_cap_usd_or_metered_runtime_policy",
            scaffold.validation_errors(payload),
        )

    def test_ambiguous_budget_prose_is_not_treated_as_a_cap(self) -> None:
        payload = base_payload()
        payload["objective"] = "Run a real LLM evaluation"
        payload["metered_runtime_policy"] = "max quality budget report for 5 calls"
        self.assertIn(
            "metered_runtime_policy:must_defer_forbid_or_bound_usage",
            scaffold.validation_errors(payload),
        )

    def test_infinite_cost_cap_is_rejected(self) -> None:
        payload = base_payload()
        payload["cost_cap_usd"] = "Infinity"
        self.assertIn("cost_cap_usd:must_be_positive", scaffold.validation_errors(payload))

    def test_non_positive_limits_are_rejected(self) -> None:
        payload = base_payload()
        payload["cost_cap_usd"] = "-1"
        payload["runtime_retry_attempts"] = "0"
        payload["max_child_threads"] = "0"
        errors = scaffold.validation_errors(payload)
        self.assertIn("cost_cap_usd:must_be_positive", errors)
        self.assertIn("runtime_retry_attempts:must_be_integer", errors)
        self.assertIn("max_child_threads:must_be_integer", errors)

    def test_numeric_limit_strings_follow_the_public_schema(self) -> None:
        payload = base_payload()
        payload["max_wakeups"] = "064"
        payload["max_idle_wakeups"] = True
        errors = scaffold.validation_errors(payload)
        self.assertIn("max_wakeups:must_be_integer", errors)
        self.assertIn("max_idle_wakeups:must_be_integer", errors)

    def test_standard_positive_numeric_limit_strings_remain_compatible(self) -> None:
        fields = (
            "runtime_retry_attempts",
            "runtime_retry_total_minutes",
            "runtime_retry_attempt_timeout_minutes",
            "runtime_retry_no_progress_minutes",
            "heartbeat_interval_minutes",
            "max_wakeups",
            "max_idle_wakeups",
            "active_stale_after_minutes",
            "max_child_threads",
            "max_repair_attempts_per_goal",
        )
        for field in fields:
            with self.subTest(field=field):
                payload = base_payload()
                payload[field] = str(payload[field])
                errors = scaffold.validation_errors(payload)
                self.assertFalse(
                    any(error.startswith(f"{field}:") for error in errors),
                    errors,
                )

    def test_duplicate_roles_are_rejected(self) -> None:
        payload = base_payload()
        payload["workers"] = "implementation:a;implementation:b"
        payload["permissions"] = "implementation:workspace_write"
        self.assertIn("workers:duplicate_roles", scaffold.validation_errors(payload))

    def test_ambiguous_thread_placeholders_are_rejected(self) -> None:
        payload = base_payload()
        payload["workers"] = [
            {"role": "实现一", "scope": "a", "permission": "workspace_write"},
            {"role": "实现二", "scope": "b", "permission": "workspace_write"},
        ]
        payload["permissions"] = {"实现一": "workspace_write", "实现二": "workspace_write"}
        self.assertIn("workers:ambiguous_thread_placeholders", scaffold.validation_errors(payload))

    def test_multiple_state_writers_are_rejected(self) -> None:
        payload = base_payload()
        payload["workers"] = [
            {"role": "implementation", "scope": "work", "permission": "workspace_write"},
            {"role": "state-a", "scope": "state", "permission": "state_write_only"},
            {"role": "state-b", "scope": "state", "permission": "state_write_only"},
        ]
        payload["permissions"] = {
            "implementation": "workspace_write",
            "state-a": "state_write_only",
            "state-b": "state_write_only",
        }
        self.assertIn("workers:multiple_state_writers", scaffold.validation_errors(payload))

    def test_reviewer_must_be_read_only(self) -> None:
        payload = base_payload()
        payload["workers"] = [
            {"role": "implementation", "scope": "work", "permission": "workspace_write"},
            {"role": "reviewer", "scope": "review", "permission": "workspace_write"},
        ]
        payload["permissions"] = {
            "implementation": "workspace_write",
            "reviewer": "workspace_write",
        }
        self.assertIn("reviewer_must_be_read_only:reviewer", scaffold.validation_errors(payload))

    def test_multiple_reviewers_without_assignment_protocol_are_rejected(self) -> None:
        payload = base_payload()
        payload["workers"].extend(
            [
                {"role": "security-reviewer", "scope": "security", "permission": "read_only"},
                {"role": "ux-reviewer", "scope": "ux", "permission": "read_only"},
            ]
        )
        payload["permissions"].update(
            {"security-reviewer": "read_only", "ux-reviewer": "read_only"}
        )
        self.assertIn(
            "workers:multiple_reviewers_without_assignment_protocol",
            scaffold.validation_errors(payload),
        )

    def test_duplicate_permission_declarations_must_agree(self) -> None:
        payload = base_payload()
        payload["permissions"]["implementation"] = "read_only"
        self.assertIn("permissions:mismatch_for:implementation", scaffold.validation_errors(payload))
        payload = base_payload()
        payload["workers"][0]["sandbox"] = "read_only"
        self.assertIn("workers:1:permission_sandbox_mismatch", scaffold.validation_errors(payload))

    def test_duplicate_permission_roles_in_legacy_string_are_rejected(self) -> None:
        payload = base_payload()
        payload["permissions"] = (
            "implementation:workspace_write;implementation:read_only"
        )
        self.assertIn(
            "permissions:duplicate_role:implementation",
            scaffold.validation_errors(payload),
        )

    def test_writable_loop_cannot_disable_review(self) -> None:
        payload = base_payload()
        payload["review"] = "review not required"
        self.assertIn("review:required_for_writable_goals", scaffold.validation_errors(payload))

    def test_read_only_no_diff_loop_can_use_final_read_only_audit(self) -> None:
        payload = base_payload()
        payload["workers"][0]["permission"] = "read_only"
        payload["permissions"]["implementation"] = "read_only"
        payload["allowed"] = []
        payload["workers"][0]["allowed"] = []
        payload["review"] = "review not required because every goal is read-only and no diff"
        self.assertEqual(scaffold.validation_errors(payload), [])
        pack = scaffold.render_controller_pack(payload, "compact")
        self.assertNotIn("### Worker Prompt - reviewer", pack)
        self.assertIn("FINAL_READ_ONLY_AUDIT", pack)

    def test_workspace_write_still_requires_a_nonempty_global_scope(self) -> None:
        payload = base_payload()
        payload["allowed"] = []
        self.assertIn(
            "allowed:required_for_workspace_write",
            scaffold.validation_errors(payload),
        )

    def test_state_writer_name_cannot_have_workspace_write(self) -> None:
        payload = base_payload()
        payload["workers"].append(
            {"role": "state-writer", "scope": "state", "permission": "workspace_write"}
        )
        payload["permissions"]["state-writer"] = "workspace_write"
        self.assertIn(
            "state_writer_must_be_state_write_only:state-writer",
            scaffold.validation_errors(payload),
        )

    def test_chinese_reviewer_is_recognized(self) -> None:
        payload = base_payload()
        payload["workers"] = [
            {"role": "实现", "scope": "写代码", "permission": "workspace_write"},
            {"role": "审查", "scope": "独立审查", "permission": "read_only"},
        ]
        payload["permissions"] = {"实现": "workspace_write", "审查": "read_only"}
        workers = scaffold.normalize_workers(payload)
        reviewers = [worker for worker in workers if scaffold.is_review_role(worker)]
        self.assertEqual([worker["role"] for worker in reviewers], ["审查"])

    def test_audit_logging_scope_does_not_count_as_reviewer(self) -> None:
        payload = base_payload()
        payload["workers"] = [
            {"role": "implementation", "scope": "implement audit logging", "permission": "workspace_write"}
        ]
        workers = scaffold.normalize_workers(payload)
        self.assertTrue(any(worker["role"] == "reviewer" for worker in workers))

    def test_preview_role_does_not_count_as_reviewer(self) -> None:
        payload = base_payload()
        payload["workers"] = [
            {"role": "preview-worker", "scope": "render previews", "permission": "workspace_write"}
        ]
        payload["permissions"] = {"preview-worker": "workspace_write"}
        workers = scaffold.normalize_workers(payload)
        self.assertTrue(any(worker["role"] == "reviewer" for worker in workers))
        self.assertFalse(scaffold.is_review_role(workers[0]))

    def test_multiple_dispatch_workers_require_explicit_goals(self) -> None:
        payload = base_payload()
        payload["workers"] = [
            {"role": "triage", "scope": "discover", "permission": "read_only"},
            {"role": "implementation", "scope": "repair", "permission": "workspace_write"},
        ]
        payload["permissions"] = {"triage": "read_only", "implementation": "workspace_write"}
        payload.pop("goals", None)
        self.assertIn("goals:required_for_multiple_dispatch_workers", scaffold.validation_errors(payload))

    def test_existing_git_requires_branch(self) -> None:
        payload = base_payload()
        payload.pop("branch", None)
        payload.pop("target_branch", None)
        self.assertIn("branch:required_for_existing_git", scaffold.validation_errors(payload))

    def test_existing_git_new_target_requires_branch_create_permission(self) -> None:
        payload = base_payload()
        payload["goals"][0]["phase_permissions"]["branch_create"] = False
        self.assertIn(
            "existing_git:first_writing_goal_requires_branch_create_permission",
            scaffold.validation_errors(payload),
        )

    def test_existing_git_single_existing_branch_does_not_require_creation(self) -> None:
        payload = base_payload()
        payload["branch"] = "main"
        payload.pop("base_branch", None)
        payload.pop("target_branch", None)
        payload["goals"][0]["phase_permissions"]["branch_create"] = False
        self.assertNotIn(
            "existing_git:first_writing_goal_requires_branch_create_permission",
            scaffold.validation_errors(payload),
        )

    def test_new_git_does_not_require_branch(self) -> None:
        payload = base_payload()
        payload["repo_mode"] = "new_git"
        payload.pop("branch", None)
        payload.pop("target_branch", None)
        payload["goals"] = [
            {
                "goal_id": "INIT-G1",
                "worker_role": "implementation",
                "objective": "Initialize and implement",
                "success_criteria": ["Repository and feature exist"],
                "phase_permissions": {"git_init": True, "branch_create": True},
            }
        ]
        self.assertEqual(scaffold.validation_errors(payload), [])

    def test_new_git_requires_explicit_init_permissions(self) -> None:
        payload = base_payload()
        payload["repo_mode"] = "new_git"
        payload.pop("branch", None)
        payload.pop("target_branch", None)
        payload["goals"][0]["phase_permissions"]["branch_create"] = False
        errors = scaffold.validation_errors(payload)
        self.assertIn("new_git:first_writing_goal_requires_git_init_permission", errors)
        self.assertIn("new_git:first_writing_goal_requires_branch_create_permission", errors)

    def test_non_git_rejects_branch_fields_and_uses_local_integration(self) -> None:
        payload = base_payload()
        payload["repo_mode"] = "non_git"
        payload["goals"][0]["phase_permissions"]["branch_create"] = False
        errors = scaffold.validation_errors(payload)
        self.assertIn("non_git:branch_fields_must_be_omitted", errors)
        payload.pop("branch", None)
        payload.pop("base_branch", None)
        payload.pop("target_branch", None)
        self.assertEqual(scaffold.validation_errors(payload), [])
        pack = scaffold.render_controller_pack(payload, "compact")
        self.assertIn("non_git local integration directory only", pack)
        self.assertIn("Use one shared local integration directory", pack)
        self.assertNotIn("Use one shared integration worktree for sequential", pack)

    def test_source_artifacts_are_explicitly_required(self) -> None:
        payload = base_payload()
        payload.pop("source_artifacts")
        self.assertIn("source_artifacts", scaffold.validation_errors(payload))

    def test_placeholder_values_are_not_dispatchable_facts(self) -> None:
        payload = base_payload()
        payload["objective"] = "TBD"
        payload["claim"] = "待定"
        payload["target_branch"] = "<placeholder>"
        payload["human_approval_policy"] = "unknown"
        payload["allowed"] = ["TBD"]
        payload["validation"] = ["TODO"]
        payload["acceptance_criteria"] = ["稍后补充"]
        payload["source_artifacts"] = ["<TBD>"]
        payload["goals"][0]["objective"] = "占位"
        payload["goals"][0]["success_criteria"] = ["?"]
        errors = scaffold.validation_errors(payload)
        for expected in (
            "objective:placeholder_not_allowed",
            "claim:placeholder_not_allowed",
            "target_branch:placeholder_not_allowed",
            "human_approval_policy:placeholder_not_allowed",
            "allowed:scope_outside_repo:TBD",
            "validation:placeholder_not_allowed",
            "acceptance_criteria:placeholder_not_allowed",
            "source_artifacts:invalid_reference:<TBD>",
            "goals:1:objective:placeholder_not_allowed",
            "goals:1:success_criteria:placeholder_not_allowed",
        ):
            self.assertIn(expected, errors)

    def test_repo_control_paths_and_write_scopes_cannot_escape(self) -> None:
        payload = base_payload()
        payload["repo"] = "relative/repo"
        payload["state"] = "../../outside/LOOP_STATE.md"
        payload["allowed"] = ["/etc/**"]
        payload["source_artifacts"] = ["some descriptive prose without a path"]
        errors = scaffold.validation_errors(payload)
        self.assertIn("repo:must_be_absolute_path", errors)
        self.assertIn("state:must_be_inside_repo_codex_loop", errors)
        self.assertIn("allowed:scope_outside_repo:/etc/**", errors)
        self.assertIn(
            "source_artifacts:invalid_reference:some descriptive prose without a path",
            errors,
        )

    def test_product_writers_cannot_own_reserved_control_plane_paths(self) -> None:
        payload = base_payload()
        payload["allowed"] = ["src/**", ".codex-loop/**"]
        payload["workers"][0]["allowed"] = [".codex-loop/reports/**"]
        payload["goals"][0]["allowed_write_scope"] = [".codex-loop/LOOP_STATE.md"]
        errors = scaffold.validation_errors(payload)
        self.assertIn(
            "allowed:reserved_control_plane_scope:.codex-loop/**",
            errors,
        )
        self.assertIn(
            "workers:implementation:reserved_control_plane_scope:.codex-loop/reports/**",
            errors,
        )
        self.assertIn(
            "goals:G1:reserved_control_plane_scope:.codex-loop/LOOP_STATE.md",
            errors,
        )

    def test_worker_and_goal_scopes_can_only_narrow(self) -> None:
        payload = base_payload()
        payload["allowed"] = ["src/auth/**"]
        payload["workers"][0]["allowed"] = ["src/**"]
        payload["goals"][0]["allowed_write_scope"] = ["tests/**"]
        errors = scaffold.validation_errors(payload)
        self.assertIn("workers:implementation:scope_expands_global:src/**", errors)
        self.assertIn("goals:G1:scope_expands_worker:tests/**", errors)

    def test_scope_glob_does_not_cross_directory_segments(self) -> None:
        repo = "/tmp/example-repo"
        self.assertTrue(scaffold.scope_is_within(repo, "src/main.py", "src/*.py"))
        self.assertFalse(scaffold.scope_is_within(repo, "src/nested/main.py", "src/*.py"))
        self.assertTrue(scaffold.scope_is_within(repo, "src/nested/main.py", "src/**/*.py"))
        self.assertTrue(scaffold.scope_is_within(repo, "src/**/*.py", "src/**/*.py"))
        self.assertFalse(scaffold.scope_is_within(repo, "src/nested/*.py", "src/**/*.py"))

    def test_unknown_fields_are_rejected(self) -> None:
        payload = base_payload()
        payload["surprise"] = True
        self.assertIn("unknown_field:surprise", scaffold.validation_errors(payload))

    def test_unsafe_role_and_goal_identifiers_are_rejected(self) -> None:
        payload = base_payload()
        payload["workers"] = [
            {"role": "implementation|spoof", "scope": "work", "permission": "workspace_write"}
        ]
        payload["permissions"] = {"implementation|spoof": "workspace_write"}
        payload["goals"] = [
            {
                "goal_id": "G1|spoof",
                "worker_role": "implementation|spoof",
                "objective": "work",
                "success_criteria": ["done"],
            }
        ]
        errors = scaffold.validation_errors(payload)
        self.assertTrue(any(error.startswith("workers:invalid_role:") for error in errors))
        self.assertIn("goals:1:invalid_goal_id", errors)

    def test_nested_worker_and_goal_unknown_fields_are_rejected(self) -> None:
        payload = base_payload()
        payload["workers"][0]["surprise"] = True
        payload["goals"] = [
            {
                "goal_id": "G1",
                "worker_role": "implementation",
                "objective": "Implement it",
                "success_criteria": ["It works"],
                "mystery": "value",
            }
        ]
        errors = scaffold.validation_errors(payload)
        self.assertIn("workers:1:unknown_field:surprise", errors)
        self.assertIn("goals:1:unknown_field:mystery", errors)

    def test_nested_and_optional_types_are_not_stringified(self) -> None:
        payload = base_payload()
        payload["connectors"] = ["not", "a", "string"]
        payload["runtime_blockers"] = {"unexpected": True}
        payload["time_factors"] = ["valid", 42]
        payload["workers"][0]["scope"] = {"unexpected": True}
        payload["goals"][0]["objective"] = {"unexpected": True}
        errors = scaffold.validation_errors(payload)
        self.assertIn("connectors:must_be_string", errors)
        self.assertIn("runtime_blockers:must_be_string_or_string_array", errors)
        self.assertIn("time_factors:must_be_string_or_string_array", errors)
        self.assertIn("workers:1:scope:must_be_string", errors)
        self.assertIn("goals:1:objective:must_be_string", errors)

    def test_phase_permission_schema_rejects_unknown_and_invalid_values(self) -> None:
        payload = base_payload()
        payload["goals"] = [
            {
                "goal_id": "G1",
                "worker_role": "implementation",
                "objective": "Implement it",
                "success_criteria": ["It works"],
                "phase_permissions": {"deploy": "maybe", "root_shell": True},
            }
        ]
        errors = scaffold.validation_errors(payload)
        self.assertIn("goals:1:phase_permissions:deploy:must_be_boolean", errors)
        self.assertIn("goals:1:phase_permissions:unknown_field:root_shell", errors)
        payload["goals"][0]["phase_permissions"] = {"deploy": "true"}
        self.assertIn(
            "goals:1:phase_permissions:deploy:must_be_boolean",
            scaffold.validation_errors(payload),
        )

    def test_structured_permissions_require_canonical_enum_values(self) -> None:
        payload = base_payload()
        payload["workers"][0]["permission"] = "write"
        payload["permissions"]["implementation"] = "write"
        errors = scaffold.validation_errors(payload)
        self.assertIn("workers:1:permission:invalid", errors)
        self.assertIn("permissions:invalid_for:implementation", errors)

    def test_retry_timeouts_must_be_consistent(self) -> None:
        payload = base_payload()
        payload["runtime_retry_total_minutes"] = 30
        payload["runtime_retry_attempt_timeout_minutes"] = 40
        payload["runtime_retry_no_progress_minutes"] = 45
        errors = scaffold.validation_errors(payload)
        self.assertIn("runtime_retry_attempt_timeout_minutes:must_not_exceed_total_minutes", errors)
        self.assertIn("runtime_retry_no_progress_minutes:must_not_exceed_attempt_timeout", errors)

    def test_retry_total_must_fit_initial_attempt_and_all_retries(self) -> None:
        payload = base_payload()
        payload["runtime_retry_attempts"] = 10
        payload["runtime_retry_total_minutes"] = 100
        payload["runtime_retry_attempt_timeout_minutes"] = 12
        self.assertIn(
            "runtime_retry_total_minutes:must_cover_all_attempt_timeouts:132",
            scaffold.validation_errors(payload),
        )

    def test_review_topology_needs_three_child_threads(self) -> None:
        payload = base_payload()
        payload["max_child_threads"] = 2
        self.assertIn(
            "max_child_threads:must_be_at_least_3_when_review_required",
            scaffold.validation_errors(payload),
        )

    def test_conflicting_topology_and_heartbeat_policies_are_rejected(self) -> None:
        payload = base_payload()
        payload["thread_topology"] = "create all workers at startup"
        payload["automation"] = "no heartbeat; manual only"
        errors = scaffold.validation_errors(payload)
        self.assertIn("thread_topology:conflicts_with_lean_just_in_time_policy", errors)
        self.assertIn("automation:heartbeat_required_for_automatic_loop", errors)

    def test_separate_writing_worktrees_require_integration_goal(self) -> None:
        payload = base_payload()
        payload["workers"].append(
            {"role": "security", "scope": "secure", "permission": "workspace_write"}
        )
        payload["permissions"]["security"] = "workspace_write"
        payload["worktree_policy"] = "one worktree per writing Worker"
        payload["goals"].append(
            {
                "goal_id": "G2",
                "worker_role": "security",
                "objective": "Secure the feature",
                "success_criteria": ["Security checks pass"],
                "depends_on": ["G1"],
            }
        )
        self.assertIn(
            "worktree_policy:separate_writers_require_promotion_or_merge_goal",
            scaffold.validation_errors(payload),
        )

    def test_child_thread_budget_must_cover_declared_roles(self) -> None:
        payload = base_payload()
        payload["workers"] = [
            {"role": "triage", "scope": "read", "permission": "read_only"},
            {"role": "implementation", "scope": "write", "permission": "workspace_write"},
            {"role": "security", "scope": "write security", "permission": "workspace_write"},
        ]
        payload["permissions"] = {
            "triage": "read_only",
            "implementation": "workspace_write",
            "security": "workspace_write",
        }
        payload["max_child_threads"] = 4
        payload["goals"] = [
            {
                "goal_id": "T1",
                "worker_role": "triage",
                "objective": "triage",
                "success_criteria": ["done"],
            },
            {
                "goal_id": "I1",
                "worker_role": "implementation",
                "objective": "implement",
                "success_criteria": ["done"],
                "depends_on": ["T1"],
                "phase_permissions": {"branch_create": True},
            },
            {
                "goal_id": "S1",
                "worker_role": "security",
                "objective": "secure",
                "success_criteria": ["done"],
                "depends_on": ["I1"],
            },
        ]
        self.assertIn(
            "max_child_threads:below_declared_role_count:5",
            scaffold.validation_errors(payload),
        )


class ParsingTests(unittest.TestCase):
    def test_duplicate_json_keys_are_rejected_at_any_depth(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate JSON key: objective"):
            scaffold.strict_json_loads('{"objective":"a","objective":"b"}')
        with self.assertRaisesRegex(ValueError, "duplicate JSON key: role"):
            scaffold.strict_json_loads('{"workers":[{"role":"a","role":"b"}]}')

    def test_validation_pipeline_is_preserved(self) -> None:
        self.assertEqual(
            scaffold.parse_commands("npm test | tee out.log;npm run lint"),
            ["npm test | tee out.log", "npm run lint"],
        )

    def test_quoted_semicolon_is_preserved(self) -> None:
        self.assertEqual(
            scaffold.parse_commands("sh -c 'printf a;b';npm test"),
            ["sh -c 'printf a;b'", "npm test"],
        )

    def test_semicolon_in_worker_scope_is_preserved(self) -> None:
        workers = scaffold.parse_workers("implementation:fix parsing; preserve semicolons in docs")
        self.assertEqual(len(workers), 1)
        self.assertIn("; preserve", workers[0]["scope"])

    def test_url_after_semicolon_does_not_create_fake_worker(self) -> None:
        workers = scaffold.parse_workers("implementation:read spec; https://example.com/spec")
        self.assertEqual(len(workers), 1)
        self.assertIn("https://example.com/spec", workers[0]["scope"])

    def test_json_surface_is_not_overwritten(self) -> None:
        payload = base_payload()
        payload["surface"] = "ui_manual"
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump({key: value for key, value in payload.items() if not key.startswith("_")}, handle)
            input_path = Path(handle.name)
        try:
            args = scaffold.build_parser().parse_args(["--input", str(input_path)])
            loaded = scaffold.load_payload(args)
            self.assertEqual(loaded["surface"], "ui_manual")
        finally:
            input_path.unlink()


class GeneratedPackTests(unittest.TestCase):
    def test_first_goal_has_identity_and_review_fields(self) -> None:
        pack = scaffold.render_controller_pack(base_payload(), "compact")
        first_goal = pack.split("## First Goal", 1)[1]
        self.assertIn("Goal ID: G1", first_goal)
        self.assertIn("Dispatch ID: <MATERIALIZE_DISPATCH_ID_FOR_G1>", first_goal)
        self.assertIn("diff_summary", first_goal)
        self.assertIn("Worker Permission: workspace_write", first_goal)
        self.assertIn("diff_sha256", first_goal)
        self.assertIn("before_snapshot_sha256", first_goal)
        self.assertIn("git_init: false", first_goal)
        self.assertIn("branch_create: true", first_goal)
        self.assertIn("<MATERIALIZE_CURRENT_STATE_SNAPSHOT_FOR_G1>", first_goal)
        self.assertIn("pre-existing dirty-file boundary", first_goal)
        self.assertEqual(
            re.findall(r"<MATERIALIZE_[^>]*\.\.\.[^>]*>", pack),
            [],
        )

    def test_heartbeat_uses_real_tool_schema_and_custom_limits(self) -> None:
        payload = base_payload()
        payload["heartbeat_interval_minutes"] = 7
        payload["max_wakeups"] = 500
        payload["max_idle_wakeups"] = 12
        pack = scaffold.render_controller_pack(payload, "compact")
        self.assertIn('automation_update(mode="create", kind="heartbeat"', pack)
        self.assertIn('rrule="FREQ=MINUTELY;INTERVAL=7"', pack)
        self.assertIn("- max_wakeups: 500", pack)
        self.assertIn("max_consecutive_idle_wakeups: 12", pack)

    def test_create_thread_uses_nested_target_schema(self) -> None:
        pack = scaffold.render_controller_pack(base_payload(), "compact")
        self.assertIn(
            'create_thread(prompt=BOOTSTRAP_PROMPT, target={type:"project", projectId:PROJECT_ID, environment:{type:"local"}})',
            pack,
        )
        self.assertNotIn('create_thread(target.type="project", projectId=', pack)
        self.assertNotIn("prompt=<bootstrap>", pack)

    def test_thread_creation_is_idempotent_and_state_writer_bootstraps_first(self) -> None:
        pack = scaffold.render_controller_pack(base_payload(), "compact")
        for value in (
            "thread_creation_outbox",
            "PACK_SHA256",
            "BOOTSTRAP_MARKER",
            "THREAD_CREATE_PREPARED",
            "THREAD_REGISTERED",
            "list_threads(query=BOOTSTRAP_MARKER)",
        ):
            self.assertIn(value, pack)
        self.assertIn("SHA-256(PROJECT_ID + canonical repo path + PACK_SHA256)", pack)
        self.assertIn("never use a random fallback", pack)
        startup = pack.split("Startup Transaction Gate:", 1)[1].split("Worker Routing:", 1)[0]
        self.assertLess(startup.index("state-writer using"), startup.index("execution Worker"))
        self.assertIn("It never includes First Goal", pack)
        self.assertIn("newer role prompt supersedes inherited conversation instructions", pack)
        child_prompts = pack.split("## Worker Prompt", 1)[1].split("## First Goal", 1)[0]
        self.assertNotRegex(child_prompts, r"<MATERIALIZE_[^>]+>")
        self.assertIn("records the returned real threadId after create/fork", child_prompts)

    def test_pack_itself_authorizes_bounded_control_plane_creation(self) -> None:
        pack = scaffold.render_controller_pack(base_payload(), "compact")
        self.assertIn("act of sending this Controller Pack", pack)
        self.assertIn("Do not ask again for those control-plane actions", pack)
        self.assertIn("does not permit product-file edits by Controller", pack)

    def test_heartbeat_prompt_is_concrete_and_self_contained(self) -> None:
        payload = base_payload()
        payload["automation"] = "Create one bounded heartbeat for this exact queue"
        pack = scaffold.render_controller_pack(payload, "compact")
        self.assertIn("HEARTBEAT_PROMPT_BEGIN", pack)
        self.assertIn("HEARTBEAT_PROMPT_END", pack)
        self.assertIn("prompt=HEARTBEAT_PROMPT", pack)
        self.assertIn(
            "declared_automation_intent: Create one bounded heartbeat for this exact queue",
            pack,
        )
        self.assertNotIn("<self-contained transition prompt>", pack)

    def test_heartbeat_creation_is_idempotent(self) -> None:
        pack = scaffold.render_controller_pack(base_payload(), "compact")
        for value in (
            "automation_outbox",
            "AUTOMATION_CREATE_PREPARED",
            "AUTOMATION_REGISTERED",
            "AUTOMATION_IDENTITY_UNRESOLVED",
            "HEARTBEAT_AUTOMATION_NAME",
            "$CODEX_HOME/automations/*/automation.toml",
            "AUTOMATION_TOOLS_UNAVAILABLE",
        ):
            self.assertIn(value, pack)

    def test_active_worker_never_becomes_terminal_noop(self) -> None:
        pack = scaffold.render_controller_pack(base_payload(), "compact")
        self.assertIn("WAITING_ACTIVE", pack)
        self.assertIn("keep heartbeat ACTIVE", pack)
        self.assertIn("No action now but inflight or queued work remains", pack)
        self.assertIn("WAKE_EVENT_ID", pack)
        self.assertIn("HEARTBEAT_WAKE compare-and-swap", pack)
        self.assertIn("must not increment twice", pack)

    def test_state_protocol_is_versioned_and_idempotent(self) -> None:
        pack = scaffold.render_controller_pack(base_payload(), "compact")
        for value in (
            "state_version",
            "last_processed_event_id",
            "STATE_WRITE_ALREADY_APPLIED",
            "STATE_VERSION_CONFLICT",
            "expected_state_version",
            "dispatch_outbox",
            "DISPATCH_PREPARED",
            "DISPATCH_SENT",
        ):
            self.assertIn(value, pack)
        self.assertIn("expected_state_version=0", pack)
        self.assertIn("LOOP_INITIALIZED", pack)
        self.assertIn("Never overwrite an existing state file during bootstrap", pack)
        self.assertIn("fast-path cursors, not the dedupe set", pack)
        self.assertIn("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", pack)
        self.assertIn("STATE_JSON_BEGIN", pack)
        self.assertIn("one canonical valid JSON object", pack)
        self.assertIn("exactly one valid JSON object per newline", pack)
        self.assertEqual(set(scaffold.STATE_SCHEMA_FIELDS), set(scaffold.STATE_SCHEMA_TYPES))
        self.assertEqual(set(scaffold.EVENT_SCHEMA_FIELDS), set(scaffold.EVENT_SCHEMA_TYPES))
        self.assertIn("controller_pack_identity: object", pack)
        self.assertIn(".codex-loop/sources/CONTROLLER_PACK.md", pack)
        self.assertIn("use the copy in this thread only as corroboration", pack)

    def test_duplicate_dispatch_is_not_reexecuted(self) -> None:
        pack = scaffold.render_controller_pack(base_payload(), "compact")
        self.assertIn("duplicate_dispatch=true", pack)
        self.assertIn("target thread already contains dispatch_id", pack)
        self.assertIn("page read_thread with cursors", pack)
        self.assertIn("checking only the latest turn is insufficient", pack)

    @mock.patch.dict(os.environ, {"CODEX_HOME": "/workspace/.codex"})
    def test_pack_migration_reconciles_the_same_live_heartbeat(self) -> None:
        pack = scaffold.render_controller_pack(
            scaffold.load_payload(
                scaffold.build_parser().parse_args(
                    ["--input", str(ROOT / "examples/03-adaptive-passkey-input.json")]
                )
            ),
            "full",
        )
        for marker in (
            "MIGRATE_V2_TO_V3",
            "paused quiescent v2 state",
            "optional stronger receipt",
            "Do not create a replacement heartbeat",
        ):
            self.assertIn(marker, pack)
        self.assertNotIn("PREPARE_CONTROLLER_PACK_MIGRATION", pack)
        self.assertNotIn("MIGRATE_CONTROLLER_PACK", pack)

    @mock.patch.dict(os.environ, {"CODEX_HOME": "/workspace/.codex"})
    def test_schema_v3_user_guide_uses_host_cooperative_operation_evidence(self) -> None:
        payload = scaffold.load_payload(
            scaffold.build_parser().parse_args(
                ["--input", str(ROOT / "examples/03-adaptive-passkey-input.json")]
            )
        )
        guide = scaffold.render_user_guide(
            payload, "examples/03-adaptive-passkey-controller-pack.md"
        )
        for marker in (
            "host-attested turn",
            "真实 App 返回或 readback",
            "PAUSED readback",
            "REGISTER_TASK` / `REGISTER_HEARTBEAT",
            "PREPARE_FINALIZATION -> PAUSED readback -> ACK_FINALIZATION",
            "Gateway runtime 的 PREPARED/APPLIED 恢复日志",
        ):
            self.assertIn(marker, guide)
        for legacy_instruction in (
            "Adaptive 必须先以 `THREAD` outbox",
            "`AUTOMATION` outbox 的 `PREPARED -> SENT -> ACKED`",
            "Worker 派发使用 `DISPATCH` outbox",
            "等待 `STATE_WRITE_APPLIED`",
            "最终状态写入成功后才是 `LOOP_COMPLETE`",
            "State-Writer 的 PREPARED/APPLIED",
        ):
            self.assertNotIn(legacy_instruction, guide)

    @mock.patch.dict(os.environ, {"CODEX_HOME": "/workspace/.codex"})
    def test_schema_v3_pack_has_no_legacy_completion_or_dispatch_lifecycle(self) -> None:
        payload = scaffold.load_payload(
            scaffold.build_parser().parse_args(
                ["--input", str(ROOT / "examples/03-adaptive-passkey-input.json")]
            )
        )
        pack = scaffold.render_controller_pack(payload, "full")
        for marker in (
            "Controller Canonical Terminal Statuses: FINALIZATION_ACKED | LOOP_BLOCKED",
            "PREPARE_FINALIZATION",
            "ACK_FINALIZATION yields FINALIZATION_ACKED",
            "one Gateway PREPARE_ROUTE owns the only current route",
            "retained outbox storage remains actively written and validated only by State Gateway operations",
            "no terminal status exists before that ACK",
            "two same-fingerprint natural observations or 15 minutes",
        ):
            self.assertIn(marker, pack)
        for legacy_instruction in (
            "before LOOP_COMPLETE",
            "Controller Canonical Terminal Statuses: LOOP_COMPLETE",
            "every outbound message requires a prepared and acknowledged dispatch outbox entry",
            "To stop after terminal completion",
        ):
            self.assertNotIn(legacy_instruction, pack)

    def test_goal_scope_can_narrow_worker_scope(self) -> None:
        payload = base_payload()
        payload["goals"] = [
            {
                "goal_id": "N1",
                "worker_role": "implementation",
                "objective": "Change one file",
                "success_criteria": ["Only src/one.py changes"],
                "allowed_write_scope": ["src/one.py"],
            }
        ]
        pack = scaffold.render_controller_pack(payload, "compact")
        first_goal = pack.split("## First Goal", 1)[1]
        self.assertIn("- src/one.py", first_goal)
        self.assertNotIn("- src/**", first_goal)

    def test_state_writer_scope_is_consistent(self) -> None:
        pack = scaffold.render_controller_pack(base_payload(), "compact")
        implementation_section = pack.split("### Worker Prompt - implementation", 1)[1].split(
            "### Worker Prompt - reviewer", 1
        )[0]
        self.assertIn("EXPLICIT EXCLUSION (State-Writer only)", implementation_section)
        self.assertIn("/tmp/example-repo/.codex-loop/**", implementation_section)
        state_section = pack.split("### Worker Prompt - state-writer", 1)[1]
        self.assertIn("state/event/triage/report/transaction-journal paths", state_section)
        self.assertIn("LOOP_EVENTS.jsonl", state_section)
        self.assertIn("transactions/", state_section)
        self.assertIn("sources/", state_section)
        report_fields = state_section.split("Required Report Fields:", 1)[1].split("Status Vocabulary:", 1)[0]
        self.assertIn("mutation_digest", report_fields)
        self.assertNotIn("base_sha", report_fields)
        self.assertIn("State-Writer applies compare-and-swap", state_section)

    def test_state_writer_has_crash_recovery_journal(self) -> None:
        pack = scaffold.render_controller_pack(base_payload(), "compact")
        self.assertIn("transactions/STATE_REQUEST_ID.json", pack)
        self.assertIn("PREPARED", pack)
        self.assertIn("mark the journal APPLIED", pack)

    def test_worktree_reviewer_mapping_is_explicit(self) -> None:
        pack = scaffold.render_controller_pack(base_payload(), "compact")
        self.assertIn('fork_thread(threadId=WORKER_THREAD_ID, environment={type:"same-directory"})', pack)
        self.assertIn("REVIEW_ARTIFACT_UNAVAILABLE", pack)
        self.assertIn("FINAL_AUDIT", pack)
        self.assertIn("non_git or an uncommitted new_git tree", pack)
        self.assertIn("dedicated code-review tool or installed code-review skill", pack)
        self.assertIn("exclude .codex-loop control files", pack)
        self.assertIn("report the exclusion manifest separately", pack)
        self.assertIn("Controller Pack snapshot/hash identity", pack)

    def test_goal_queue_table_escapes_user_supplied_pipes(self) -> None:
        payload = base_payload()
        payload["goals"] = [
            {
                "goal_id": "G1",
                "worker_role": "implementation",
                "objective": "work",
                "success_criteria": ["done"],
                "dispatch_when": "A | B",
            }
        ]
        pack = scaffold.render_controller_pack(payload, "compact")
        self.assertIn("A \\| B", pack)

    def test_prompt_fence_expands_for_embedded_code_fences(self) -> None:
        payload = base_payload()
        payload["objective"] = "Implement this example:\n```js\nconst x = 1;\n```"
        fence = scaffold.markdown_prompt_fence(payload)
        self.assertEqual(fence, "````")
        pack = scaffold.render_controller_pack(payload, "compact")
        self.assertIn("````text", pack)
        self.assertIn("```js", pack)

    def test_goal_queue_and_triage_transition_are_generated(self) -> None:
        payload = base_payload()
        payload["workers"] = [
            {"role": "triage", "scope": "discover", "permission": "read_only"},
            {"role": "implementation", "scope": "repair", "permission": "workspace_write"},
        ]
        payload["permissions"] = {"triage": "read_only", "implementation": "workspace_write"}
        payload["goals"] = [
            {
                "goal_id": "T1",
                "worker_role": "triage",
                "objective": "Find one concrete failure",
                "success_criteria": ["Return TRIAGE_ACTIONABLE or TRIAGE_NO_ACTION with evidence"],
                "validation": ["inspect logs read-only"],
            },
            {
                "goal_id": "R1",
                "worker_role": "implementation",
                "objective": "Repair the selected finding",
                "depends_on": ["T1"],
                "dispatch_when": "T1 is TRIAGE_ACTIONABLE",
                "success_criteria": ["Selected failure is repaired"],
                "phase_permissions": {"branch_create": True},
            },
        ]
        self.assertEqual(scaffold.validation_errors(payload), [])
        pack = scaffold.render_controller_pack(payload, "compact")
        self.assertIn("| 1 | T1 | triage", pack)
        self.assertIn("| 2 | R1 | implementation | T1", pack)
        self.assertIn("Worker TRIAGE_ACTIONABLE", pack)
        self.assertIn("Worker TRIAGE_NO_ACTION", pack)

    def test_full_mode_is_real(self) -> None:
        pack = scaffold.render_controller_pack(base_payload(), "full")
        for heading in ("## Loop Diagnosis", "Loop Integrity Score:", "## Changelog", "## Flow Map", "## Test Goals", "## Final Next Step"):
            self.assertIn(heading, pack)
        self.assertNotIn("Full-mode note: add", pack)

    def test_key_risks_are_capped_at_three_bullets(self) -> None:
        pack = scaffold.render_controller_pack(base_payload(), "compact")
        risks = pack.split("## 关键风险", 1)[1].split("## Controller Prompt", 1)[0]
        bullets = [line for line in risks.splitlines() if line.startswith("-")]
        self.assertLessEqual(len(bullets), 3)

    def test_attachment_inheritance_warning_is_explicit(self) -> None:
        pack = scaffold.render_controller_pack(base_payload(), "compact")
        self.assertIn("not automatically inherited", pack)

    def test_state_update_ack_precedes_next_goal(self) -> None:
        pack = scaffold.render_controller_pack(base_payload(), "compact")
        self.assertIn("after STATE_WRITE_APPLIED", pack)
        self.assertIn("state update and next goal in parallel", pack)

    def test_limited_completion_has_a_reachable_bounded_transition(self) -> None:
        pack = scaffold.render_controller_pack(base_payload(), "compact")
        self.assertIn("FINAL_REVIEW_PASS_WITH_LIMITATION", pack)
        self.assertIn("terminal_status=LOOP_COMPLETE_WITH_LIMITATION", pack)
        self.assertIn("no unresolved required fix", pack)
        self.assertIn("never silently upgrade it to full completion", pack)

    def test_exhausted_repair_budget_has_an_explicit_terminal_transition(self) -> None:
        pack = scaffold.render_controller_pack(base_payload(), "compact")
        self.assertIn("REPAIR_BUDGET_EXHAUSTED", pack)
        self.assertIn("create a fresh Worker to reset the counter", pack)
        self.assertIn("silently continue repairs", pack)
        self.assertIn("terminal_status=LOOP_STOPPED with USER_CANCELLED", pack)

    def test_blocker_stop_and_resume_reuse_the_same_heartbeat(self) -> None:
        pack = scaffold.render_controller_pack(base_payload(), "compact")
        self.assertIn("STOP means persist the exact non-complete blocker", pack)
        self.assertIn("AWAITING_HUMAN_APPROVAL and no independent pre-authorized Goal remains", pack)
        self.assertIn("reactivate the same automation id", pack)
        self.assertIn("create a second heartbeat", pack)

    def test_reviewer_is_just_in_time_and_writing_workers_are_serial(self) -> None:
        pack = scaffold.render_controller_pack(base_payload(), "compact")
        self.assertIn("Never create Reviewer at startup", pack)
        self.assertIn("max_parallel_execution_workers: 1", pack)
        self.assertIn("one shared integration worktree", pack)
        self.assertIn(
            'fork_thread(threadId=PRIOR_WRITER_THREAD_ID, environment={type:"same-directory"})',
            pack,
        )
        self.assertIn("only after the prior writer is idle and its report/state are acknowledged", pack)
        self.assertIn("WORKTREE_INTEGRATION_PLAN_MISSING", pack)
        self.assertIn("archived tasks still count", pack)
        self.assertIn("THREAD_BUDGET_EXHAUSTED", pack)
        self.assertNotIn("Create Reviewer at startup only", pack)

    def test_completed_threads_archive_only_after_state_ack(self) -> None:
        pack = scaffold.render_controller_pack(base_payload(), "compact")
        self.assertIn("set_thread_archived(threadId=..., archived=true)", pack)
        self.assertIn("archiving must never precede report/state ACK", pack)

    def test_runtime_retry_has_explicit_hard_attempt_timeout(self) -> None:
        payload = base_payload()
        payload["runtime_retry_attempt_timeout_minutes"] = 17
        payload["runtime_retry_total_minutes"] = 240
        pack = scaffold.render_controller_pack(payload, "compact")
        self.assertIn("hard_attempt_timeout_minutes: 17", pack)
        self.assertIn("retry_cap_after_initial_attempt: 10", pack)
        self.assertIn("total_attempt_cap: 11", pack)
        implementation_section = pack.split("### Worker Prompt - implementation", 1)[1].split(
            "### Worker Prompt - reviewer", 1
        )[0]
        self.assertIn("Runtime Dependency Retry Policy:", implementation_section)
        self.assertIn("Honor Retry-After", implementation_section)

    def test_optional_connector_and_claim_boundary_do_not_create_false_blockers(self) -> None:
        payload = base_payload()
        payload["objective"] = "Implement a local login form"
        payload["claim"] = "not production-ready and never deploy"
        payload["connectors"] = "GitHub connector if exposed; otherwise local git evidence"
        workers = scaffold.normalize_workers(payload)
        blockers = "\n".join(scaffold.default_runtime_blockers(payload, workers))
        self.assertNotIn("真实生产副作用", blockers)
        self.assertNotIn("必需 connector", blockers)

    def test_external_reading_and_human_factors_do_not_imply_side_effect_gate(self) -> None:
        payload = base_payload()
        payload["objective"] = "Read local copies of external docs and summarize human factors"
        payload["_provided_keys"] = ["objective"]
        workers = scaffold.normalize_workers(payload)
        self.assertEqual(scaffold.default_runtime_readiness(payload, workers), "READY_LOW_RISK")
        self.assertNotIn(
            "真实生产副作用",
            "\n".join(scaffold.default_runtime_blockers(payload, workers)),
        )

    def test_local_api_implementation_does_not_imply_external_runtime_gate(self) -> None:
        payload = base_payload()
        payload["objective"] = "Implement a local API request parser"
        payload["_provided_keys"] = ["objective"]
        workers = scaffold.normalize_workers(payload)
        self.assertEqual(scaffold.default_runtime_readiness(payload, workers), "READY_LOW_RISK")

    def test_url_only_sources_forecast_connector_gate(self) -> None:
        payload = base_payload()
        payload["source_artifacts"] = ["https://example.com/spec"]
        workers = scaffold.normalize_workers(payload)
        blockers = "\n".join(scaffold.default_runtime_blockers(payload, workers))
        self.assertIn("必需 connector", blockers)

    def test_time_estimate_uses_configured_heartbeat_coverage(self) -> None:
        payload = base_payload()
        payload["heartbeat_interval_minutes"] = 10
        payload["max_wakeups"] = 12
        block = scaffold.time_estimate_block(payload, scaffold.normalize_workers(payload), ["test"])
        self.assertIn("约 2 小时（10 分钟 x 12 次）", block)

    def test_print_schema_has_nested_closed_objects(self) -> None:
        schema = scaffold.INPUT_SCHEMA
        worker_schema = schema["properties"]["workers"]["oneOf"][1]["items"]["oneOf"][0]
        goal_schema = schema["properties"]["goals"]["items"]
        self.assertFalse(worker_schema["additionalProperties"])
        self.assertFalse(goal_schema["additionalProperties"])
        self.assertIn("git_init", goal_schema["properties"]["phase_permissions"]["properties"])


class CliTests(unittest.TestCase):
    def test_legacy_workers_flag_remains_supported(self) -> None:
        args = scaffold.build_parser().parse_args(
            ["--workers", "implementation:scoped feature"]
        )
        payload = scaffold.load_payload(args)
        self.assertEqual(payload["workers"], "implementation:scoped feature")

    def test_skill_validator_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATOR)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Skill validation passed", result.stdout)

    def test_invalid_input_refuses_pack_without_allow_draft(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--objective", "typo"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Refusing to generate", result.stderr)
        self.assertNotIn("# Codex Loop Controller Pack", result.stdout)

    def test_duplicate_input_json_key_is_an_input_error(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            handle.write('{"objective":"a","objective":"b"}')
            input_path = Path(handle.name)
        try:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--input", str(input_path), "--check-only"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("duplicate JSON key: objective", result.stderr)
        finally:
            input_path.unlink()

    def test_allow_draft_is_clearly_non_dispatchable(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--objective", "typo", "--allow-draft"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout.startswith("NON_DISPATCHABLE_DRAFT"))

    def test_full_draft_does_not_claim_twelve_of_twelve(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--objective", "typo", "--allow-draft", "--mode", "full"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Loop Integrity Score: 0/12", result.stdout)
        self.assertNotIn("Loop Integrity Score: 12/12", result.stdout)

    def test_controller_pack_output_is_written_without_temp_residue(self) -> None:
        payload = {key: value for key, value in base_payload().items() if not key.startswith("_")}
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.json"
            output_path = Path(directory) / "pack.md"
            input_path.write_text(json.dumps(payload), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(input_path),
                    "--controller-pack-output",
                    str(output_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output_path.read_text(encoding="utf-8").startswith("# Codex Loop Controller Pack"))
            self.assertEqual(list(Path(directory).glob(".*.tmp-*")), [])

    def test_controller_pack_output_cannot_overwrite_input_json(self) -> None:
        payload = {key: value for key, value in base_payload().items() if not key.startswith("_")}
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.json"
            input_path.write_text(json.dumps(payload), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(input_path),
                    "--controller-pack-output",
                    str(input_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("must not overwrite the input JSON", result.stderr)
            self.assertEqual(json.loads(input_path.read_text(encoding="utf-8")), payload)

    def test_installer_migrates_legacy_backups_and_excludes_caches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory) / ".codex"
            skills = codex_home / "skills"
            live = skills / "codex-loop-prompt-architect"
            legacy = skills / "codex-loop-prompt-architect.backup.legacy"
            live.mkdir(parents=True)
            legacy.mkdir(parents=True)
            (live / "old.txt").write_text("old", encoding="utf-8")
            (legacy / "legacy.txt").write_text("legacy", encoding="utf-8")
            result = subprocess.run(
                ["bash", str(INSTALLER)],
                cwd=ROOT,
                env={
                    **os.environ,
                    "CODEX_HOME": str(codex_home),
                    "PYTHON": sys.executable,
                },
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((live / "SKILL.md").is_file())
            discoverable = list(skills.glob("codex-loop-prompt-architect*"))
            self.assertEqual(discoverable, [live])
            self.assertTrue(any((codex_home / "skill-backups").rglob("legacy.txt")))
            self.assertEqual(list(live.rglob("__pycache__")), [])
            self.assertEqual(list(live.rglob("*.pyc")), [])

    def test_installer_restores_previous_skill_when_final_move_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex_home = root / ".codex"
            live = codex_home / "skills" / "codex-loop-prompt-architect"
            live.mkdir(parents=True)
            (live / "old.txt").write_text("old", encoding="utf-8")
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_mv = fake_bin / "mv"
            fake_mv.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$1\" == *'/install-staging/'* ]]; then exit 73; fi\n"
                "exec /bin/mv \"$@\"\n",
                encoding="utf-8",
            )
            fake_mv.chmod(0o755)
            result = subprocess.run(
                ["bash", str(INSTALLER)],
                cwd=ROOT,
                env={
                    **os.environ,
                    "CODEX_HOME": str(codex_home),
                    "PYTHON": sys.executable,
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                },
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Installation failed", result.stderr)
            self.assertEqual((live / "old.txt").read_text(encoding="utf-8"), "old")
            self.assertFalse((live / "SKILL.md").exists())


class ExampleFixtureTests(unittest.TestCase):
    def test_standard_fixture_hashes_are_stable(self) -> None:
        expected = {
            "01-passkey-login-controller-pack.md": "ab7290617804b460cd84aa8fb67043927b1d191f42c6b90f2588387626941696",
            "01-passkey-login-usage.md": "d8e38f4680a47aed114adf3ddfa20ba9534be7dbfc03fd6a770b345b118f81e4",
            "02-daily-ci-triage-controller-pack.md": "0243aa887f4caae46ee83ab4a4ad7696b3a2cf09d97123799f4098974a7616af",
            "02-daily-ci-triage-usage.md": "cea1c0a82898712685aac818ef3862fe0cbda444967a7e0313592b77ac2eb73a",
        }
        for name, expected_digest in expected.items():
            actual = hashlib.sha256((ROOT / "examples" / name).read_bytes()).hexdigest()
            self.assertEqual(actual, expected_digest, name)

    def test_standard_fixtures_match_generator_byte_for_byte(self) -> None:
        for prefix in ("01-passkey-login", "02-daily-ci-triage"):
            input_path = ROOT / "examples" / f"{prefix}-input.json"
            args = scaffold.build_parser().parse_args(["--input", str(input_path)])
            payload = scaffold.load_payload(args)
            expected_pack = (
                scaffold.render_controller_pack(payload, "compact").rstrip() + "\n"
            ).encode("utf-8")
            pack_path = ROOT / "examples" / f"{prefix}-controller-pack.md"
            self.assertEqual(pack_path.read_bytes(), expected_pack)
            expected_usage = (
                scaffold.render_user_guide(
                    payload, f"examples/{prefix}-controller-pack.md"
                ).rstrip()
                + "\n"
            ).encode("utf-8")
            usage_path = ROOT / "examples" / f"{prefix}-usage.md"
            self.assertEqual(usage_path.read_bytes(), expected_usage)

    @mock.patch.dict(os.environ, {"CODEX_HOME": "/workspace/.codex"})
    def test_adaptive_fixture_cli_outputs_match_renderer_bytes(self) -> None:
        input_path = ROOT / "examples" / "03-adaptive-passkey-input.json"
        args = scaffold.build_parser().parse_args(["--input", str(input_path)])
        payload = scaffold.load_payload(args)
        with tempfile.TemporaryDirectory() as directory:
            pack_path = Path(directory) / "adaptive-pack.md"
            usage_path = Path(directory) / "adaptive-usage.md"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(input_path),
                    "--mode",
                    "full",
                    "--controller-pack-output",
                    str(pack_path),
                    "--user-guide-output",
                    str(usage_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            expected_pack = (
                scaffold.render_controller_pack(payload, "full").rstrip() + "\n"
            ).encode("utf-8")
            expected_usage = (
                scaffold.render_user_guide(payload, str(pack_path)).rstrip() + "\n"
            ).encode("utf-8")
            self.assertEqual(pack_path.read_bytes(), expected_pack)
            self.assertEqual(usage_path.read_bytes(), expected_usage)
            self.assertEqual(
                (ROOT / "examples" / "03-adaptive-passkey-controller-pack.md").read_bytes(),
                expected_pack,
            )
            committed_usage = (
                scaffold.render_user_guide(
                    payload,
                    "examples/03-adaptive-passkey-controller-pack.md",
                ).rstrip()
                + "\n"
            ).encode("utf-8")
            self.assertEqual(
                (ROOT / "examples" / "03-adaptive-passkey-usage.md").read_bytes(),
                committed_usage,
            )


if __name__ == "__main__":
    unittest.main()
