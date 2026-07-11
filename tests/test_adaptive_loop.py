from __future__ import annotations

import hashlib
import json
import re
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_loop_prompt_scaffold import base_payload, scaffold


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "codex-loop-prompt-architect" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from loop_architect.forecast import dashboard_required, local_verifier_needed
from loop_architect.state_runtime import (
    AdaptiveStateRuntime,
    materialize_dispatch_payload,
    verify_dispatch_payload,
)


def adaptive_payload() -> dict:
    payload = base_payload()
    payload.update(
        {
            "coordination_mode": "adaptive",
            "adaptive_reason": "Two product milestones may change after exact browser evidence",
            "acceptance_criteria": [
                "Feature behavior is covered by tests",
                "Authenticated browser smoke confirms the local flow",
            ],
            "delegation_policy": "auto_read_only",
            "max_read_only_subagents": 2,
            "max_read_only_subagent_runs": 4,
            "subagent_retry_limit": 1,
            "subagent_input_policy": "workspace paths and redacted logs only; no secrets or private credentials",
            "subagent_max_depth": 1,
            "local_verification_policy": "auto_if_required",
            "dashboard_policy": "auto",
            "dashboard_threshold_hours": 12,
            "time_min": "4 hours",
            "time_typical": "10 hours",
            "time_max": "18 hours",
            "workers": [
                {
                    "role": "implementation",
                    "role_kind": "implementation",
                    "scope": "write the scoped feature",
                    "permission": "workspace_write",
                    "allowed": ["src/**", "tests/**"],
                }
            ],
            "milestones": [
                {
                    "milestone_id": "M1",
                    "outcome": "Implement the local feature contract",
                    "scope": ["src/**", "tests/**"],
                    "decisions": ["Keep external calls disabled"],
                    "blockers": [],
                    "required_evidence": ["unit tests", "exact diff review"],
                    "status": "ACTIVE",
                    "depends_on": [],
                    "references": ["G1"],
                },
                {
                    "milestone_id": "M2",
                    "outcome": "Validate the integrated behavior",
                    "scope": ["src/**", "tests/**"],
                    "decisions": [],
                    "blockers": [],
                    "required_evidence": ["integration checks", "roadmap audit"],
                    "status": "PLANNED",
                    "depends_on": ["M1"],
                    "references": ["G2"],
                },
            ],
            "goals": [
                {
                    "goal_id": "G1",
                    "milestone_id": "M1",
                    "worker_role": "implementation",
                    "objective": "Implement one scoped feature",
                    "success_criteria": ["Feature behavior is covered by tests"],
                    "phase_permissions": {"branch_create": True},
                },
                {
                    "goal_id": "G2",
                    "milestone_id": "M2",
                    "worker_role": "implementation",
                    "objective": "Validate the integrated behavior",
                    "success_criteria": ["Integration behavior is evidenced"],
                    "depends_on": ["G1"],
                },
            ],
            "max_child_threads": 4,
        }
    )
    payload["_provided_keys"] = sorted(key for key in payload if not key.startswith("_"))
    return payload


class AdaptiveValidationTests(unittest.TestCase):
    def test_valid_adaptive_payload(self) -> None:
        self.assertEqual(scaffold.validation_errors(adaptive_payload()), [])

    def test_adaptive_requires_explicit_role_kind(self) -> None:
        payload = adaptive_payload()
        payload["workers"][0].pop("role_kind")
        self.assertIn("workers:1:role_kind_required_for_adaptive", scaffold.validation_errors(payload))

    def test_adaptive_rejects_legacy_worker_string(self) -> None:
        payload = adaptive_payload()
        payload["workers"] = "implementation: scoped feature"
        self.assertIn("workers:structured_objects_required_for_adaptive", scaffold.validation_errors(payload))

    def test_local_verifier_role_kind_must_be_read_only(self) -> None:
        payload = adaptive_payload()
        payload["workers"].append(
            {
                "role": "machine-check",
                "role_kind": "local_verifier",
                "scope": "verify local UI",
                "permission": "workspace_write",
            }
        )
        self.assertIn("workers:2:local_verifier_must_be_read_only", scaffold.validation_errors(payload))

    def test_top_level_permissions_cannot_bypass_role_kind_matrix(self) -> None:
        payload = adaptive_payload()
        payload["workers"].append({
            "role": "machine-check",
            "role_kind": "local_verifier",
            "scope": "verify local UI",
        })
        payload["permissions"] = {
            "implementation": "workspace_write",
            "machine-check": "state_write_only",
        }
        errors = scaffold.validation_errors(payload)
        self.assertIn("workers:2:local_verifier_must_be_read_only", errors)
        self.assertIn("workers:2:state_write_only_reserved_for_state_writer", errors)
        normalized = scaffold.normalize_workers(payload)
        self.assertTrue(any(worker["role_kind"] == "state_writer" for worker in normalized))

    def test_local_verifier_cannot_own_adaptive_goal(self) -> None:
        payload = adaptive_payload()
        payload["workers"].append({
            "role": "machine-check",
            "role_kind": "local_verifier",
            "scope": "verify local UI",
            "permission": "read_only",
        })
        payload["goals"][0]["worker_role"] = "machine-check"
        errors = scaffold.validation_errors(payload)
        self.assertIn(
            "goals:1:invalid_adaptive_execution_role_kind:local_verifier", errors
        )
        self.assertIn("goals:G1:invalid_execution_role:machine-check", errors)

    def test_adaptive_always_materializes_reviewer_even_if_input_says_no_review(self) -> None:
        payload = adaptive_payload()
        payload["review"] = "review not required because no diff"
        workers = scaffold.normalize_workers(payload)
        self.assertEqual(
            len([worker for worker in workers if worker["role_kind"] == "code_reviewer"]),
            1,
        )

    def test_auto_roles_remain_unique_when_user_roles_use_reserved_names(self) -> None:
        payload = adaptive_payload()
        for role in ("reviewer", "state-writer", "local-verifier"):
            payload["workers"].append(
                {
                    "role": role,
                    "role_kind": "implementation",
                    "scope": f"write scoped files as {role}",
                    "permission": "workspace_write",
                    "allowed": ["src/**", "tests/**"],
                }
            )
        payload["max_child_threads"] = 8
        self.assertEqual(scaffold.validation_errors(payload), [])
        workers = scaffold.normalize_workers(payload)
        role_keys = [scaffold.role_key(worker["role"]) for worker in workers]
        placeholders = [
            scaffold.thread_placeholder(worker["role"], worker["role_kind"])
            for worker in workers
        ]
        self.assertEqual(len(role_keys), len(set(role_keys)))
        self.assertEqual(len(placeholders), len(set(placeholders)))
        for kind in ("code_reviewer", "state_writer", "local_verifier"):
            matches = [worker for worker in workers if worker["role_kind"] == kind]
            self.assertEqual(len(matches), 1)
            self.assertTrue(matches[0]["role"].startswith("loop-"))
        pack = scaffold.render_controller_pack(payload, "compact")
        headings = [
            line.removeprefix("### Worker Prompt - ")
            for line in pack.splitlines()
            if line.startswith("### Worker Prompt - ")
        ]
        self.assertEqual(len(headings), len(set(headings)))

    def test_read_only_adaptive_milestone_does_not_require_write_scope(self) -> None:
        payload = adaptive_payload()
        payload["allowed"] = []
        payload["workers"][0]["permission"] = "read_only"
        payload["permissions"] = {"implementation": "read_only"}
        payload["workers"][0]["allowed"] = []
        payload["acceptance_criteria"] = ["Read-only findings are reviewed"]
        payload["local_verification_policy"] = "not_required"
        payload["connectors"] = "Codex App task tools only"
        payload["runtime_blockers"] = []
        payload["review"] = "review required for read-only evidence"
        self.assertEqual(scaffold.validation_errors(payload), [])

    def test_exactly_one_active_milestone(self) -> None:
        payload = adaptive_payload()
        payload["milestones"][1]["status"] = "ACTIVE"
        self.assertIn("milestones:exactly_one_active_required", scaffold.validation_errors(payload))

    def test_goal_must_reference_known_milestone(self) -> None:
        payload = adaptive_payload()
        payload["goals"][1]["milestone_id"] = "MISSING"
        self.assertIn("goals:2:valid_milestone_id_required_for_adaptive", scaffold.validation_errors(payload))

    def test_milestone_dependency_cycle_is_rejected(self) -> None:
        payload = adaptive_payload()
        payload["milestones"][0]["depends_on"] = ["M2"]
        self.assertIn("milestones:dependency_cycle", scaffold.validation_errors(payload))

    def test_local_verifier_does_not_satisfy_code_review(self) -> None:
        workers = scaffold.normalize_workers(adaptive_payload())
        local = next(worker for worker in workers if worker["role_kind"] == "local_verifier")
        reviewer = next(worker for worker in workers if worker["role_kind"] == "code_reviewer")
        self.assertFalse(scaffold.is_review_role(local))
        self.assertTrue(scaffold.is_review_role(reviewer))
        self.assertEqual(scaffold.thread_placeholder(local["role"], local["role_kind"]), "<MATERIALIZE_REAL_THREAD_ID_FOR_LOCAL_VERIFIER>")

    def test_subagent_depth_and_concurrency_are_bounded(self) -> None:
        payload = adaptive_payload()
        payload["max_read_only_subagents"] = 3
        payload["subagent_max_depth"] = 2
        errors = scaffold.validation_errors(payload)
        self.assertIn("max_read_only_subagents:must_be_integer_0_to_2", errors)
        self.assertIn("subagent_max_depth:must_equal_1", errors)

    def test_subagent_delegation_requires_explicit_bounded_authorization(self) -> None:
        payload = adaptive_payload()
        payload["_provided_keys"].remove("delegation_policy")
        payload["_provided_keys"].remove("subagent_input_policy")
        errors = scaffold.validation_errors(payload)
        self.assertIn("delegation_policy:explicit_authorization_required", errors)
        self.assertIn("subagent_input_policy:explicit_nonempty_policy_required", errors)
        self.assertEqual(scaffold.DEFAULTS["delegation_policy"], "disabled")
        self.assertEqual(scaffold.DEFAULTS["max_read_only_subagents"], 0)

    def test_adaptive_types_and_scope_are_not_silently_normalized(self) -> None:
        payload = adaptive_payload()
        payload["goals"][0]["milestone_id"] = {"not": "a string"}
        payload["milestones"][0]["scope"] = [{"not": "a path"}]
        payload["milestones"][1]["required_evidence"] = [{"not": "evidence"}]
        errors = scaffold.validation_errors(payload)
        self.assertIn("goals:1:valid_milestone_id_required_for_adaptive", errors)
        self.assertIn("milestones:1:scope:must_be_string_or_string_array", errors)
        self.assertIn("milestones:2:required_evidence:must_be_string_or_string_array", errors)

    def test_adaptive_milestone_scope_cannot_escape_global_scope(self) -> None:
        payload = adaptive_payload()
        payload["milestones"][0]["scope"] = ["/etc/**"]
        self.assertIn("milestones:1:scope_outside_repo:/etc/**", scaffold.validation_errors(payload))

    def test_active_milestone_dependencies_must_be_complete(self) -> None:
        payload = adaptive_payload()
        payload["milestones"][0]["depends_on"] = ["M2"]
        errors = scaffold.validation_errors(payload)
        self.assertIn("milestones:M1:active_dependency_not_complete:M2", errors)

    def test_active_milestone_needs_an_initially_dispatchable_goal(self) -> None:
        payload = adaptive_payload()
        payload["goals"][0]["depends_on"] = ["G2"]
        errors = scaffold.validation_errors(payload)
        self.assertIn("milestones:M1:no_initial_dependency_free_goal", errors)

    def test_first_goal_is_selected_from_active_milestone_not_input_order(self) -> None:
        payload = adaptive_payload()
        payload["goals"][1]["depends_on"] = []
        payload["goals"].reverse()
        self.assertEqual(scaffold.validation_errors(payload), [])
        pack = scaffold.render_controller_pack(payload, "compact")
        first_goal = pack.split("## First Goal", 1)[1].split(
            "## Remaining Goal Queue Templates", 1
        )[0]
        self.assertIn('"goal_id": "G1"', first_goal)
        self.assertNotIn('"goal_id": "G2"', first_goal)
        self.assertIn("| 2 | G1 | M1 | 1 | READY |", pack)
        self.assertIn("### Queued Goal Template - G2", pack)

    def test_milestone_required_arrays_and_dependencies_are_strict(self) -> None:
        payload = adaptive_payload()
        payload["milestones"][0]["scope"] = []
        payload["milestones"][0]["required_evidence"] = []
        payload["milestones"][1]["depends_on"] = ["M1", "M1"]
        errors = scaffold.validation_errors(payload)
        self.assertIn("milestones:1:scope:must_be_string_or_string_array", errors)
        self.assertIn("milestones:1:required_evidence:must_be_string_or_string_array", errors)
        self.assertIn("milestones:2:depends_on:duplicates_not_allowed", errors)

    def test_goal_dependencies_cannot_repeat(self) -> None:
        payload = adaptive_payload()
        payload["goals"][1]["depends_on"] = ["G1", "G1"]
        self.assertIn(
            "goals:2:depends_on:duplicates_not_allowed",
            scaffold.validation_errors(payload),
        )

    def test_invalid_dashboard_threshold_can_still_render_a_draft(self) -> None:
        payload = adaptive_payload()
        payload["dashboard_threshold_hours"] = "bad"
        self.assertIn(
            "dashboard_threshold_hours:must_be_positive_integer",
            scaffold.validation_errors(payload),
        )
        self.assertIn("NON_DISPATCHABLE_DRAFT", scaffold.render_controller_pack(payload, "compact"))

    def test_heartbeat_budget_must_cover_adaptive_time_max(self) -> None:
        payload = adaptive_payload()
        payload["heartbeat_interval_minutes"] = 15
        payload["max_wakeups"] = 6
        payload["time_max"] = "6 hours"
        self.assertIn(
            "heartbeat:coverage_below_time_max",
            scaffold.validation_errors(payload),
        )
        payload["max_wakeups"] = 24
        self.assertNotIn(
            "heartbeat:coverage_below_time_max",
            scaffold.validation_errors(payload),
        )

    def test_adaptive_integer_fields_reject_numeric_strings(self) -> None:
        payload = adaptive_payload()
        payload["heartbeat_interval_minutes"] = "15"
        payload["call_cap"] = "25"
        errors = scaffold.validation_errors(payload)
        self.assertIn("heartbeat_interval_minutes:must_be_integer", errors)
        self.assertIn("call_cap:must_be_positive", errors)

    def test_public_schema_requires_adaptive_role_kind_and_milestone_id(self) -> None:
        adaptive_then = scaffold.INPUT_SCHEMA["allOf"][0]["then"]
        worker_items = adaptive_then["properties"]["workers"]["items"]["allOf"][1]
        goal_items = adaptive_then["properties"]["goals"]["items"]["allOf"][1]
        self.assertEqual(worker_items["required"], ["role_kind"])
        self.assertEqual(goal_items["required"], ["milestone_id"])

    def test_controller_goal_budget_is_separate_and_strictly_typed(self) -> None:
        payload = adaptive_payload()
        payload["controller_goal_token_budget"] = "1000"
        self.assertIn(
            "controller_goal_token_budget:must_be_positive_integer",
            scaffold.validation_errors(payload),
        )
        payload["controller_goal_token_budget"] = 1000
        self.assertEqual(scaffold.validation_errors(payload), [])
        args = scaffold.build_parser().parse_args(
            ["--controller-goal-token-budget", "1000", "--max-wakeups", "64"]
        )
        self.assertEqual(args.controller_goal_token_budget, 1000)
        self.assertEqual(args.max_wakeups, 64)

    def test_project_root_may_contain_target_repo_but_not_the_reverse(self) -> None:
        payload = adaptive_payload()
        payload["project_root"] = "/tmp"
        payload["_provided_keys"].append("project_root")
        self.assertEqual(scaffold.validation_errors(payload), [])
        pack = scaffold.render_controller_pack(payload, "compact")
        self.assertIn("Codex Project whose root is /tmp", pack)
        self.assertIn("declared contained subdirectory /tmp/example-repo", pack)
        payload["project_root"] = "/tmp/another-project"
        self.assertIn("repo:must_be_inside_project_root", scaffold.validation_errors(payload))

    def test_dashboard_trigger_uses_milestones_or_duration(self) -> None:
        payload = adaptive_payload()
        self.assertTrue(dashboard_required(payload, 2))
        payload["time_max"] = "8 hours"
        self.assertFalse(dashboard_required(payload, 2))
        self.assertTrue(dashboard_required(payload, 4))

    def test_auto_local_verifier_is_added_only_when_evidence_requires_it(self) -> None:
        payload = adaptive_payload()
        self.assertTrue(local_verifier_needed(payload))
        payload["objective"] = "Refactor a pure parser"
        payload["acceptance_criteria"] = ["Unit tests pass"]
        payload["milestones"][0]["required_evidence"] = ["unit tests"]
        payload["milestones"][1]["required_evidence"] = ["unit tests"]
        payload["connectors"] = "Codex App task tools only"
        payload["runtime_blockers"] = []
        self.assertFalse(local_verifier_needed(payload))
        workers = scaffold.normalize_workers(payload)
        self.assertFalse(any(worker["role_kind"] == "local_verifier" for worker in workers))


class AdaptiveGeneratedPackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = adaptive_payload()
        self.pack = scaffold.render_controller_pack(self.payload, "compact")

    def test_pack_separates_worker_goal_from_controller_goal(self) -> None:
        self.assertIn("Single Active Milestone And Native Goal", self.pack)
        self.assertIn('"envelope_type": "WORKER_DISPATCH"', self.pack)
        self.assertIn("get_goal/create_goal", self.pack)
        self.assertIn("EMULATED_SINGLE_ACTIVE_MILESTONE", self.pack)
        self.assertIn("Do not claim they can programmatically pause, resume, edit, or clear", self.pack)
        self.assertIn("PREPARE_OUTBOX(kind=GOAL, action=CREATE)", self.pack)
        self.assertIn("direct-ACK the exact PREPARED GOAL outbox", self.pack)
        self.assertIn("generic DELEGATION outbox", self.pack)

    def test_generated_initial_state_payload_is_accepted_by_runtime(self) -> None:
        workers = scaffold.normalize_workers(self.payload)
        goals = scaffold.normalize_goals(self.payload, workers)
        definitions = scaffold.adaptive_goal_definition_registry(goals)
        authorization = scaffold.adaptive_authorization_envelope(self.payload, goals)
        active_milestone_id = next(
            milestone["milestone_id"]
            for milestone in self.payload["milestones"]
            if milestone["status"] == "ACTIVE"
        )
        queue = [
            {
                "goal_id": goal["goal_id"],
                "milestone_id": goal["milestone_id"],
                "roadmap_version": 1,
                "status": (
                    "READY"
                    if goal["milestone_id"] == active_milestone_id
                    and not goal["depends_on"]
                    else "PLANNED"
                ),
                "depends_on": goal["depends_on"],
            }
            for goal in goals
        ]
        with tempfile.TemporaryDirectory() as directory:
            pack_digest = "sha256:" + hashlib.sha256(
                self.pack.encode("utf-8")
            ).hexdigest()
            response = AdaptiveStateRuntime(directory).apply(
                {
                    "controller_approved": True,
                    "state_request_id": "generator-runtime-init",
                    "event_id": "generator-runtime-event",
                    "expected_state_version": 0,
                    "actor": "CONTROLLER",
                    "thread_id": "controller-1",
                    "occurred_at": "2026-01-01T00:00:00Z",
                    "evidence_paths": ["evidence/init.json"],
                    "artifacts": [
                        {
                            "path": ".codex-loop/sources/CONTROLLER_PACK.md",
                            "content": self.pack,
                            "digest": pack_digest,
                            "media_type": "text/markdown",
                        }
                    ],
                    "mutation": {
                        "type": "INITIALIZE",
                        "loop_id": "generator-runtime-loop",
                        "project_id": "test-project",
                        "controller_pack_digest": pack_digest,
                        "controller_thread_id": "controller-1",
                        "controller_bootstrap_prompt_digest": "sha256:" + "1" * 64,
                        "state_writer_thread_id": "state-writer-1",
                        "state_writer_bootstrap_prompt_digest": "sha256:" + "2" * 64,
                        "dashboard_required": dashboard_required(
                            self.payload, len(self.payload["milestones"])
                        ),
                        "milestones": self.payload["milestones"],
                        "goal_definition_registry": definitions,
                        "goal_queue": queue,
                        "authorization_envelope": authorization,
                        "local_verification_required_goal_ids": [
                            goal["goal_id"] for goal in goals
                        ],
                        "max_routing_turns": 10,
                    },
                }
            )
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["operation_status"], "LOOP_INITIALIZED")

    def test_adaptive_uses_non_slash_runtime_envelopes(self) -> None:
        self.assertIn(
            "Adaptive Runtime Handoff Marker: ADAPTIVE_RUNTIME_HANDOFF_V1",
            self.pack,
        )
        first_goal = self.pack.split("## First Goal", 1)[1].split("## Remaining", 1)[0]
        self.assertRegex(first_goal, r"```(?:text)?\nPAYLOAD_MATERIALIZATION_SPEC\n\{")
        self.assertIn("closed tagged REVIEW_DISPATCH", self.pack)
        self.assertIn("Execute only STATE_MUTATION", self.pack)
        self.assertIn("scripts/adaptive_state_runtime.py", self.pack)
        self.assertIn("references/adaptive-mutation.schema.json", self.pack)
        self.assertIn("verify `python3 -c 'import jsonschema'` succeeds", self.pack)
        self.assertIn("never hand-writes canonical state/events/journals", self.pack)
        self.assertIn("Do not manually create, patch, append, or rewrite", self.pack)
        self.assertIsNone(
            re.search(
                r"(?<![A-Za-z0-9_])/(?:goal|review|state_update)(?![A-Za-z0-9_])",
                self.pack,
            )
        )
        full_pack = scaffold.render_controller_pack(self.payload, "full")
        self.assertIsNone(
            re.search(
                r"(?<![A-Za-z0-9_])/(?:goal|review|state_update)(?![A-Za-z0-9_])",
                full_pack,
            )
        )
        self.assertIn("get_goal({})", self.pack)
        self.assertIn("create_goal(objective=", self.pack)
        self.assertIn('update_goal(status="complete" or status="blocked")', self.pack)

    def test_first_goal_is_executable_by_runtime_payload_codec(self) -> None:
        first_goal = self.pack.split("## First Goal", 1)[1].split("## Remaining", 1)[0]
        specification_text = first_goal.split("PAYLOAD_MATERIALIZATION_SPEC\n", 1)[1].split(
            "```",
            1,
        )[0].strip()
        specification = json.loads(specification_text)
        payload = specification["payload"]
        payload["roadmap_version"] = 1
        payload["dispatch_id"] = "dispatch-g1-001"
        payload["dispatch_lease_claim"] = {
            "lease_epoch": 1,
            "lease_id": "lease-g1-001",
            "routing_turn_id": "turn-g1-001",
            "owner_kind": "GOAL_TURN",
            "owner_identity": "controller-thread-001",
            "intended_transition": "ROUTE_ONE_TRANSITION",
        }
        payload["canonical_state_snapshot"] = {
            "loop_id": "loop-1",
            "state_version": 8,
            "roadmap_version": 1,
            "active_milestone_id": "M1",
            "controller_lease": {
                "claim": payload["dispatch_lease_claim"],
                "routing_turn_id": "turn-g1-001",
                "acquired_at": "2026-01-01T00:00:00Z",
                "expires_at": "2026-01-01T01:00:00Z",
                "route_action": None,
            },
        }
        payload["parent_dispatch_id"] = None
        payload["target_thread_id"] = "worker-thread-001"
        self.assertNotIn("MATERIALIZE_", json.dumps(specification, ensure_ascii=False))
        materialized = materialize_dispatch_payload(specification)
        self.assertEqual(materialized["status"], "PAYLOAD_MATERIALIZED")
        verified = verify_dispatch_payload(materialized["transport_text"])
        self.assertEqual(verified["status"], "PAYLOAD_BYTES_VERIFIED")

    def test_pack_enforces_semantic_payload_roles_jit_and_blocker_gate(self) -> None:
        self.assertIn("--root CANONICAL_REPO_ROOT --payload-verify", self.pack)
        self.assertIn("PAYLOAD_BYTES_VERIFIED alone is never execution permission", self.pack)
        self.assertIn("bootstrap_role_kind", self.pack)
        self.assertIn("formal_role_kind", self.pack)
        self.assertIn("implementation|triage|explorer -> WORKER", self.pack)
        self.assertIn("If no compatible registered Reviewer exists", self.pack)
        self.assertIn("If no compatible registered Local Verifier exists", self.pack)
        self.assertIn("last three genuine consecutive Goal turns", self.pack)
        self.assertIn("blocker code, fingerprint, and Controller Goal identity", self.pack)
        self.assertNotIn("keeps the original dispatch claim inside its immutable identity", self.pack)

    def test_reviewer_report_repeats_source_identity_at_top_level(self) -> None:
        reviewer = self.pack.split("### Worker Prompt - reviewer", 1)[1].split(
            "### Worker Prompt - ", 1
        )[0]
        self.assertIn("- source_worker_dispatch_id", reviewer)
        self.assertIn("- source_worker_report_digest", reviewer)
        self.assertIn("- worker_thread_id", reviewer)
        self.assertIn("- source_artifact_digest", reviewer)
        self.assertIn(
            "Nested copies in state_change_request, findings, or evidence_artifacts do not satisfy",
            reviewer,
        )

    def test_pack_contains_adaptive_closed_state_schema(self) -> None:
        for key in (
            "roadmap_version",
            "active_milestone_id",
            "goal_definition_registry",
            "goal_execution_ledger",
            "authorization_envelope",
            "roadmap_change_outbox",
            "controller_goal",
            "controller_goal_outbox",
            "controller_lease",
            "routing_turn_count",
            "routing_turn_ledger",
            "consumed_controller_lease_ids",
            "assurance_dispatch_outbox",
            "local_verification_queue",
            "local_verification_outbox",
            "estimate_history",
            "delegation_ledger",
            "subagent_attempt_ledger",
        ):
            self.assertIn(f"- {key}:", self.pack)

    def test_pack_reuses_reviewer_for_three_acknowledged_stages(self) -> None:
        self.assertIn("CODE_REVIEW, ROADMAP_AUDIT, and final FINAL_AUDIT", self.pack)
        self.assertIn("CODE_REVIEW report ACK", self.pack)
        self.assertIn("Reviewer is reused for ROADMAP_AUDIT and final FINAL_AUDIT", self.pack)
        self.assertNotIn("Worker Prompt - roadmap-auditor", self.pack.lower())

    def test_pack_enforces_authorization_envelope(self) -> None:
        self.assertIn("ROADMAP_CHANGE_REQUIRES_APPROVAL", self.pack)
        self.assertIn("Any expansion persists", self.pack)
        self.assertIn("never mutates the roadmap", self.pack)
        self.assertIn("computes the result against immutable canonical authorization_envelope", self.pack)
        self.assertIn("Caller booleans are assertions only", self.pack)
        self.assertIn("MILESTONE_REGISTRY_JSON_BEGIN", self.pack)
        self.assertIn("controller_pack_digest", self.pack)

    def test_heartbeat_uses_controller_lease(self) -> None:
        heartbeat = self.pack.split("HEARTBEAT_PROMPT_BEGIN\n", 1)[1].split("HEARTBEAT_PROMPT_END", 1)[0]
        self.assertIn("begin this wake with one ACQUIRE_LEASE mutation", heartbeat)
        self.assertIn("WAITING_CONTROLLER_LEASE", heartbeat)
        self.assertIn("ROADMAP_AUDIT", heartbeat)
        self.assertIn("full lease_claim", heartbeat)
        self.assertIn("send RELEASE_LEASE", heartbeat)
        self.assertIn("shared Goal/heartbeat routing budget", heartbeat)
        self.assertIn("ROUTING_BUDGET_EXHAUSTED", heartbeat)
        self.assertIn("RENEW_LEASE", heartbeat)
        self.assertIn("ACTIVE_SAME_OWNER", heartbeat)
        self.assertIn("atomically rebind only the same PREPARED/SENT record", heartbeat)
        self.assertIn("never resend the dispatch", heartbeat)
        self.assertIn("TAKEOVER_LEASE", heartbeat)
        self.assertNotIn("ROUTING_TURN_STARTED", heartbeat)
        self.assertNotIn("HEARTBEAT_WAKE", heartbeat)

    def test_adaptive_heartbeat_prompt_has_one_canonical_byte_identity(self) -> None:
        self.assertIn(
            "Adaptive Heartbeat Prompt Identity: ADAPTIVE_HEARTBEAT_PROMPT_V1",
            self.pack,
        )
        body = scaffold.extract_heartbeat_prompt_body(self.pack)
        self.assertTrue(body.startswith("Continue this Codex Loop"))
        self.assertFalse(body.endswith(("\n", "\r")))
        digest = "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
        self.assertIn(f"Canonical Prompt Digest: {digest}", self.pack)

        persisted_readback = json.loads(json.dumps(body, ensure_ascii=False))
        self.assertEqual(scaffold.normalize_heartbeat_prompt_readback(persisted_readback), body)
        crlf_readback = body.replace("\n", "\r\n")
        normalized_readback = scaffold.normalize_heartbeat_prompt_readback(crlf_readback)
        self.assertEqual(normalized_readback, body)
        self.assertEqual(scaffold.heartbeat_prompt_digest(normalized_readback), digest)
        self.assertNotEqual(scaffold.heartbeat_prompt_digest(body + "\n"), digest)

    def test_local_verifier_is_real_and_requires_retest(self) -> None:
        self.assertIn("Worker Prompt - local-verifier", self.pack)
        self.assertIn("real Codex App project task created just in time", self.pack)
        self.assertIn("requires a retest of that exact item", self.pack)

    def test_subagents_are_read_only_sidecars_not_formal_roles(self) -> None:
        self.assertIn("authorization_concurrency_ceiling: 2; max_lifetime_runs: 4; retry_limit_per_exploration: 1; max_depth: 1", self.pack)
        self.assertIn("deterministic router serializes one active DELEGATION outbox per lease", self.pack)
        self.assertIn("never replace Controller, implementation Worker, Reviewer, State-Writer, or Local Verifier", self.pack)
        self.assertIn("Before spawning, acquire a fresh route lease", self.pack)
        self.assertIn("PREPARE_OUTBOX(kind=DELEGATION)", self.pack)
        self.assertIn("Inspect the actually exposed collaboration/subagent tool name and schema", self.pack)
        self.assertIn("do not assume a fixed tool name or parameter set", self.pack)
        self.assertNotIn("When allowed, multi_agent_v1__spawn_agent may be used", self.pack)
        formal_role_blocks = self.pack.split("### Worker Prompt - ")[1:]
        self.assertTrue(formal_role_blocks)
        for block in formal_role_blocks:
            self.assertIn(
                "This real project task must perform its assigned State-Writer, Worker, Reviewer, or Local Verifier work directly",
                block,
            )
            self.assertIn("Never call any subagent/collaboration spawn tool", block)
            self.assertIn("Only the Controller may use", block)

    def test_pack_uses_fenced_lease_and_versioned_goal_queue(self) -> None:
        self.assertIn("monotonically increasing lease_epoch", self.pack)
        self.assertIn("STALE_OR_MISSING_CONTROLLER_LEASE", self.pack)
        self.assertIn('"roadmap_version": "<MATERIALIZE_ROADMAP_VERSION_FOR_G1>"', self.pack)
        self.assertIn(
            '"dispatch_lease_claim": "<MATERIALIZE_CONTROLLER_LEASE_CLAIM_FOR_G1>"',
            self.pack,
        )
        self.assertIn('"dispatch_payload_digest": "PAYLOAD_DIGEST_PLACEHOLDER"', self.pack)
        self.assertIn("PAYLOAD_DIGEST_PLACEHOLDER", self.pack)
        self.assertIn("--payload-materialize", self.pack)
        self.assertIn("--payload-verify", self.pack)
        self.assertIn("exact received codexDelegation.input body", self.pack)
        self.assertNotIn("Recompute the PAYLOAD_DIGEST_PLACEHOLDER form", self.pack)
        self.assertIn(
            "prepared_state_version == snapshot.state_version + 1",
            self.pack,
        )
        self.assertIn(
            "do not reject it merely because PREPARE and SENT advanced the latest state_version",
            self.pack,
        )
        self.assertIn(
            "dispatch_lease_claim: lease_epoch, lease_id, routing_turn_id, owner_kind, owner_identity, intended_transition",
            self.pack,
        )
        self.assertIn("dispatch_payload_digest", self.pack)
        self.assertIn("target_thread_id", self.pack)
        self.assertIn(
            "non_git current_branch/base_sha/head_sha are literal NOT_APPLICABLE (never null)",
            self.pack,
        )
        self.assertIn("changed_files are repo-relative POSIX paths", self.pack)
        self.assertIn("report_digest set to the literal PENDING_CONTROLLER_ARCHIVE", self.pack)
        self.assertIn("REPORT_ARTIFACT_UNBOUND", self.pack)
        self.assertIn("archived `application/json` report artifact", self.pack)
        self.assertIn("reusing only an epoch or lease id is invalid", self.pack)
        self.assertIn("dispatch_id + exact payload_digest + target_thread_id + immutable Goal definition digest", self.pack)
        self.assertIn(
            "ROADMAP_REVISION rejects every remaining PREPARED, SENT, ACKED-assurance, or in-progress versioned outbox",
            self.pack,
        )
        self.assertIn("Reject release while a matching Worker/review/local/delegation", self.pack)
        self.assertIn("mismatched reuse is rejected without advancing state", self.pack)
        self.assertIn("One claim reserves exactly one route action", self.pack)
        self.assertIn("replayed event_id must match its original immutable domain identity", self.pack)
        self.assertIn("Worker FAIL/BLOCKED", self.pack)
        self.assertIn("fresh lease for every", self.pack)
        self.assertIn("complete Goal definition registry and execution ledger", self.pack)
        self.assertIn("safe in-repo scope with no `..` or `.codex-loop`", self.pack)
        self.assertIn("Every returned Goal status, including complete", self.pack)
        self.assertIn("COMPLETE_CURRENT_CONTROLLER_GOAL", self.pack)
        self.assertIn(
            "Controller Goal is missing, non-active, or bound to another milestone",
            self.pack,
        )
        self.assertIn(
            "completed assurance outboxes and the assurance ledger are a one-to-one invariant",
            self.pack,
        )

    def test_adaptive_pack_uses_only_supported_roadmap_mutation(self) -> None:
        self.assertIn("one dedicated ROADMAP_REVISION CAS", self.pack)
        self.assertNotIn("ROADMAP_CHANGE_PREPARED", self.pack)
        self.assertNotIn("pending RoadmapRevision", self.pack)

    def test_adaptive_startup_initializes_full_state_then_acquires_lease_before_outboxes(self) -> None:
        startup = self.pack.split("Startup Transaction Gate:", 1)[1].split(
            "Worker Routing:", 1
        )[0]
        ordered = (
            "mutation.type is INITIALIZE",
            "Every routing turn starts with exactly one ACQUIRE_LEASE mutation",
            "Worker task creation uses one complete lease cycle",
            "Heartbeat creation uses a fresh complete lease cycle",
            "Controller Goal creation uses another fresh complete lease cycle",
            "First Goal dispatch uses a fourth fresh complete lease cycle",
        )
        positions = [startup.index(marker) for marker in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("MILESTONE_REGISTRY_JSON", startup)
        self.assertIn("controller_pack_digest", startup)
        self.assertNotIn("send a separate ROUTING_TURN_STARTED mutation", startup)

    def test_adaptive_bootstrap_requires_full_exact_role_prompt_and_digest(self) -> None:
        self.assertIn("ROLE_KIND is the exact literal", self.pack)
        self.assertIn("never use the display Role, task title, inferred slug", self.pack)
        self.assertIn("LOOP_ID|ROLE_KIND|PACK_SHA256", self.pack)
        self.assertIn("ROLE_PROMPT_BEGIN: state_writer", self.pack)
        self.assertIn("ROLE_PROMPT_END: state_writer", self.pack)
        self.assertIn("ROLE_PROMPT_BEGIN: implementation", self.pack)
        self.assertIn("ROLE_PROMPT_END: code_reviewer", self.pack)
        self.assertNotIn("BOOTSTRAP_MARKER is LOOP_ID + role + PACK_SHA256", self.pack)
        self.assertIn(
            "A file path, heading, line range, excerpt, summary, or loader instruction is not the prompt",
            self.pack,
        )
        self.assertIn("sha256:<64 hex> over those exact bytes", self.pack)
        self.assertIn("with no trailing LF", self.pack)
        self.assertIn("record E2E_PROTOCOL_VIOLATION", self.pack)
        startup = self.pack.split("Startup Transaction Gate:", 1)[1].split(
            "Worker Routing:", 1
        )[0]
        self.assertIn("byte-for-byte entire generated State-Writer Prompt", startup)
        self.assertIn("Never replace it with a Pack path", startup)

    def test_adaptive_bootstrap_tolerates_bounded_thread_visibility_delay(self) -> None:
        self.assertIn("Adaptive post-create visibility gate", self.pack)
        self.assertIn("after 1, 2, 4, 8, and 16 seconds", self.pack)
        self.assertIn("Retain that exact returned threadId", self.pack)
        self.assertIn("never create a replacement during this bounded window", self.pack)
        self.assertIn("A readable prompt/marker/project/cwd mismatch is E2E_PROTOCOL_VIOLATION", self.pack)
        self.assertIn("THREAD_IDENTITY_PROPAGATION_TIMEOUT", self.pack)
        startup = self.pack.split("Startup Transaction Gate:", 1)[1].split(
            "Worker Routing:", 1
        )[0]
        self.assertIn("Do not classify not found alone as a prompt mismatch", startup)
        self.assertIn("never create a replacement", startup)

    def test_adaptive_bootstrap_active_queue_is_nonterminal(self) -> None:
        self.assertIn("Adaptive bootstrap-start gate", self.pack)
        self.assertIn("applies only while the returned threadId itself remains unreadable/not found", self.pack)
        self.assertIn("an empty active/pending initial turn or missing READY reply is WAITING_BOOTSTRAP_ACTIVE", self.pack)
        self.assertIn("use WAITING_QUOTA_RECOVERY", self.pack)
        self.assertIn("do not return a terminal/final result", self.pack)
        self.assertIn("THREAD_BOOTSTRAP_FAILED", self.pack)
        startup = self.pack.split("Startup Transaction Gate:", 1)[1].split(
            "Worker Routing:", 1
        )[0]
        self.assertIn("This is not propagation timeout or idle", startup)
        self.assertIn("keep the Controller turn nonterminal", startup)

    def test_adaptive_controller_owner_uses_real_current_thread_id(self) -> None:
        self.assertIn("source_thread_id is the upstream parent task, never the current Controller", self.pack)
        self.assertIn("stop CONTROLLER_THREAD_ID_UNRESOLVED", self.pack)
        self.assertIn("can never substitute for lease owner identity", self.pack)
        self.assertIn("owner_identity is the exact real current CONTROLLER_THREAD_ID string", self.pack)
        self.assertIn("register both real project-task identities", self.pack)
        self.assertIn("owner_identity is the registered real Controller threadId", self.pack)
        self.assertIn("controller_bootstrap_prompt_digest", self.pack)
        startup = self.pack.split("Startup Transaction Gate:", 1)[1].split(
            "Worker Routing:", 1
        )[0]
        self.assertIn("Treat codex_delegation source_thread_id as parent metadata only", startup)
        self.assertIn("do not use fallback identity for routing or leases", startup)

    def test_pack_bootstraps_executable_goal_definition_registry(self) -> None:
        registry = self.pack.split("GOAL_DEFINITION_REGISTRY_JSON_BEGIN\n", 1)[1].split(
            "\nGOAL_DEFINITION_REGISTRY_JSON_END", 1
        )[0]
        parsed = json.loads(registry)
        self.assertEqual(set(parsed), {"G1", "G2"})
        for goal_id, definition in parsed.items():
            self.assertEqual(definition["goal_id"], goal_id)
            self.assertIn(
                definition["worker_role_kind"], {"implementation", "triage", "explorer"}
            )
            self.assertRegex(definition["payload_template_digest"], r"^sha256:[0-9a-f]{64}$")
            self.assertTrue(definition["validation"])
        self.assertIn('"goal_definition_digest": "sha256:', self.pack)

    def test_pack_preserves_complete_milestone_registry(self) -> None:
        raw = self.pack.split("MILESTONE_REGISTRY_JSON_BEGIN\n", 1)[1].split(
            "\nMILESTONE_REGISTRY_JSON_END", 1
        )[0]
        self.assertEqual(json.loads(raw), self.payload["milestones"])
        for field in (
            "scope",
            "decisions",
            "blockers",
            "required_evidence",
            "depends_on",
            "references",
        ):
            self.assertIn(field, json.loads(raw)[0])

    def test_pack_bootstraps_closed_canonical_authorization_envelope(self) -> None:
        payload = adaptive_payload()
        payload["goals"][1]["phase_permissions"] = {"deploy": True}
        pack = scaffold.render_controller_pack(payload, "compact")
        raw = pack.split("AUTHORIZATION_ENVELOPE_JSON_BEGIN\n", 1)[1].split(
            "\nAUTHORIZATION_ENVELOPE_JSON_END", 1
        )[0]
        parsed = json.loads(raw)
        self.assertEqual(
            set(parsed),
            {
                "objective_id",
                "allowed_write_scope",
                "phase_permissions",
                "phase_permission_caps",
                "control_plane_caps",
                "control_plane_limits",
                "delegation_policy",
                "repair_policy",
                "budget_caps",
                "connectors",
                "side_effects",
                "evidence_policy",
                "claim_boundary",
                "production_access",
                "secrets_access",
            },
        )
        self.assertEqual(parsed["allowed_write_scope"], ["src/**", "tests/**"])
        self.assertFalse(parsed["secrets_access"])
        self.assertEqual(
            parsed["repair_policy"]["max_repair_attempts_per_goal"], 3
        )
        self.assertTrue(parsed["phase_permissions"]["branch_create"])
        self.assertTrue(parsed["phase_permissions"]["deploy"])
        milestone_caps = parsed["phase_permission_caps"]["by_milestone"]
        goal_caps = parsed["phase_permission_caps"]["by_goal"]
        self.assertTrue(milestone_caps["M1"]["branch_create"])
        self.assertFalse(milestone_caps["M1"]["deploy"])
        self.assertFalse(milestone_caps["M2"]["branch_create"])
        self.assertTrue(milestone_caps["M2"]["deploy"])
        self.assertEqual(goal_caps["G1"]["milestone_id"], "M1")
        self.assertFalse(goal_caps["G1"]["phase_permissions"]["deploy"])
        self.assertEqual(goal_caps["G2"]["milestone_id"], "M2")
        self.assertTrue(goal_caps["G2"]["phase_permissions"]["deploy"])
        self.assertIn("top-level hard ceiling, not a grant", pack)
        self.assertIn("never borrows from another Goal or milestone", pack)

    def test_review_and_finalization_are_bound_to_worker_execution(self) -> None:
        self.assertIn("source Worker dispatch id, source Worker report digest", self.pack)
        self.assertIn("durably COMPLETED/PASS", self.pack)
        self.assertIn(
            "reject every non-retired, non-superseded Goal that was never executed and assured",
            self.pack,
        )
        self.assertIn("Never mark the remaining queue complete in bulk", self.pack)
        self.assertIn("latest durably COMPLETED/PASS dispatch", self.pack)
        self.assertIn("assurance_dispatch_outbox PREPARED", self.pack)
        self.assertIn("Worker, assurance, or Local Verifier outbox", self.pack)
        self.assertIn("REVIEW_ARTIFACT_UNAVAILABLE closes the outbox as a non-PASS blocker", self.pack)
        self.assertIn("one bounded repair authorization ledger", self.pack)

    def test_pack_handles_current_queued_task_identity_and_separate_goal_budget(self) -> None:
        self.assertIn("pendingWorktreeId or clientThreadId", self.pack)
        payload = adaptive_payload()
        payload["token_cap"] = 999999
        pack = scaffold.render_controller_pack(payload, "compact")
        goal_line = next(
            line for line in pack.splitlines() if "create_goal(objective=" in line
        )
        self.assertIn("OMIT_TOKEN_BUDGET_ARGUMENT", goal_line)
        self.assertNotIn("999999", goal_line)
        payload["controller_goal_token_budget"] = 12345
        pack = scaffold.render_controller_pack(payload, "compact")
        goal_line = next(
            line for line in pack.splitlines() if "create_goal(objective=" in line
        )
        self.assertIn("token_budget=12345", goal_line)

    def test_native_goal_identity_is_loop_and_pack_scoped(self) -> None:
        self.assertIn(
            "[CODEX_LOOP_MILESTONE loop_id=<LOOP_ID> pack_sha256=<FULL_64_HEX_SHA256>",
            self.pack,
        )
        self.assertIn("PREPARE_OUTBOX(kind=GOAL, action=CREATE)", self.pack)
        self.assertIn("marker alone is untrusted", self.pack)

    def test_pack_has_tagged_review_union_and_one_operation_enum(self) -> None:
        reviewer = self.pack.split("### Worker Prompt - reviewer", 1)[1].split(
            "### Worker Prompt -", 1
        )[0]
        self.assertIn(
            "review_kind=CODE_REVIEW, review_kind=ROADMAP_AUDIT, or review_kind=FINAL_AUDIT",
            reviewer,
        )
        self.assertIn("ROADMAP_AUDIT", reviewer)
        self.assertIn("FINAL_AUDIT is a third tagged dispatch", reviewer)
        for operation in (
            "ADD_MILESTONE",
            "UPDATE_MILESTONE",
            "REORDER_FUTURE_MILESTONES",
            "SUPERSEDE_MILESTONE",
        ):
            self.assertIn(operation, self.pack)
        self.assertNotIn("Permitted operations are add, update, reorder", self.pack)

    def test_pack_requires_separate_final_audit_and_finalization(self) -> None:
        self.assertIn("ROADMAP_AUDIT_PASS_FINAL_CANDIDATE", self.pack)
        self.assertIn("FINALIZE_LOOP is a separate CAS", self.pack)
        self.assertIn("STOP_LOOP", self.pack)
        self.assertIn("Only on the next dedicated Goal turn may STOP_LOOP", self.pack)
        self.assertIn("Never manufacture wakeups or backfill an observation", self.pack)
        self.assertIn("never use ROADMAP_REVISION as a terminal shortcut", self.pack)

    def test_goals_and_dashboard_are_state_writer_owned(self) -> None:
        self.assertIn("/tmp/example-repo/.codex-loop/GOALS.md", self.pack)
        self.assertIn("/tmp/example-repo/.codex-loop/progress-dashboard.html", self.pack)
        state_writer = self.pack.split("### Worker Prompt - state-writer", 1)[1]
        self.assertIn("GOALS projection", state_writer)
        self.assertIn("derived progress dashboard", state_writer)

    def test_user_guide_explains_adaptive_observability(self) -> None:
        guide = scaffold.render_user_guide(self.payload, "/tmp/adaptive-pack.md")
        self.assertIn("## Adaptive 模式怎么回查", guide)
        self.assertIn("GOALS.md", guide)
        self.assertIn("What's done / What's next / Any blockers", guide)

    def test_cli_writes_pack_and_user_guide_to_distinct_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pack_path = Path(directory) / "pack.md"
            guide_path = Path(directory) / "usage.md"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "codex-loop-prompt-architect" / "scripts" / "loop_prompt_scaffold.py"),
                    "--input",
                    str(ROOT / "examples" / "03-adaptive-passkey-input.json"),
                    "--controller-pack-output",
                    str(pack_path),
                    "--user-guide-output",
                    str(guide_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Adaptive Coordination Mode", pack_path.read_text(encoding="utf-8"))
            self.assertIn("Adaptive 模式怎么回查", guide_path.read_text(encoding="utf-8"))

    def test_cli_accepts_strict_structured_workers_json(self) -> None:
        input_path = ROOT / "examples" / "03-adaptive-passkey-input.json"
        workers = json.loads(input_path.read_text(encoding="utf-8"))["workers"]
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "codex-loop-prompt-architect" / "scripts" / "loop_prompt_scaffold.py"),
                "--input",
                str(input_path),
                "--workers-json",
                json.dumps(workers),
                "--check-only",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("semantic invariants are valid", result.stdout)

    def test_cli_rejects_malformed_or_non_array_workers_json(self) -> None:
        input_path = ROOT / "examples" / "03-adaptive-passkey-input.json"
        script = ROOT / "codex-loop-prompt-architect" / "scripts" / "loop_prompt_scaffold.py"
        for value, marker in (("[{", "Input error"), ('{"role":"implementation"}', "must be a JSON array")):
            with self.subTest(value=value):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(script),
                        "--input",
                        str(input_path),
                        "--workers-json",
                        value,
                        "--check-only",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn(marker, result.stderr)

    def test_cli_rejects_same_pack_and_guide_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "same.md"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "codex-loop-prompt-architect" / "scripts" / "loop_prompt_scaffold.py"),
                    "--input",
                    str(ROOT / "examples" / "03-adaptive-passkey-input.json"),
                    "--controller-pack-output",
                    str(output),
                    "--user-guide-output",
                    str(output),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("must be distinct", result.stderr)

    def test_standard_adaptive_and_compact_full_axes_are_independent(self) -> None:
        standard = base_payload()
        adaptive = adaptive_payload()
        for output_mode in ("compact", "full"):
            standard_pack = scaffold.render_controller_pack(standard, output_mode)
            adaptive_pack = scaffold.render_controller_pack(adaptive, output_mode)
            self.assertNotIn("Adaptive Coordination Mode", standard_pack)
            self.assertIn("Adaptive Coordination Mode", adaptive_pack)
            if output_mode == "full":
                self.assertIn("L1", standard_pack)
                self.assertIn("L1", adaptive_pack)
            else:
                self.assertNotIn("## L1-L12 Diagnosis", standard_pack)
