"""Schema constants for Standard and Adaptive loop generation."""

from __future__ import annotations

from .human_control import VALIDATION_DIMENSIONS


COORDINATION_MODES = {"standard", "adaptive"}

ADAPTIVE_WORKER_ENVELOPE = "WORKER_DISPATCH"
ADAPTIVE_REVIEW_ENVELOPE = "REVIEW_DISPATCH"
ADAPTIVE_STATE_MUTATION_ENVELOPE = "STATE_MUTATION"
ADAPTIVE_RUNTIME_HANDOFF_MARKER = "ADAPTIVE_RUNTIME_HANDOFF_V1"
ADAPTIVE_HEARTBEAT_PROMPT_MARKER = "ADAPTIVE_HEARTBEAT_PROMPT_V1"

SAFE_GOAL_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$"
SAFE_MILESTONE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
SAFE_ID_PATTERN = SAFE_MILESTONE_ID_PATTERN

ROLE_KINDS = {
    "implementation",
    "code_reviewer",
    "state_writer",
    "local_verifier",
    "triage",
    "explorer",
}

ROADMAP_OPERATIONS = {
    "ADD_MILESTONE",
    "UPDATE_MILESTONE",
    "REORDER_FUTURE_MILESTONES",
    "SUPERSEDE_MILESTONE",
}

DELEGATION_POLICIES = {
    "disabled",
    "explicit_read_only",
    "auto_read_only",
}

LOCAL_VERIFICATION_POLICIES = {
    "not_required",
    "auto_if_required",
    "required",
}

DASHBOARD_POLICIES = {
    "auto",
    "disabled",
    "required",
}

NATIVE_GOAL_POLICIES = {
    "disabled",
    "advisory",
    "required",
}

MILESTONE_STATUSES = {
    "PLANNED",
    "ACTIVE",
    "BLOCKED",
    "COMPLETE",
    "SUPERSEDED",
}

MILESTONE_FIELDS = {
    "milestone_id",
    "outcome",
    "scope",
    "decisions",
    "blockers",
    "required_evidence",
    "status",
    "depends_on",
    "references",
}

ADAPTIVE_STATE_SCHEMA_TYPES = {
    "controller_pack_identity": "closed object with archived Pack path, exact SHA-256, media type, and bootstrap prompt digests",
    "dashboard_required": "boolean fixed at initialization",
    "artifact_ledger": "object keyed by safe workspace-relative artifact path with immutable digest and media type",
    "roadmap_version": "integer >= 1",
    "milestones": "array",
    "active_milestone_id": "string or null",
    "goal_definition_registry": "object keyed by stable goal_id with immutable executable payload template, worker_role_kind, and full SHA-256 digest",
    "goal_execution_ledger": "object keyed by goal_id with attempts, current dispatch, artifact/report identities, and READY/IN_PROGRESS/WORKER_PASS/REPAIR_AUTHORIZED/COMPLETE state",
    "authorization_envelope": "closed canonical object for objective, paths, top-level permission ceiling, per-milestone/per-goal permission caps, budget, connectors, side effects, evidence, claims, production, and secrets",
    "roadmap_change_outbox": "object of APPLIED ROADMAP_REVISION receipts; the durable structured proposal is the acknowledged ROADMAP_AUDIT report",
    "controller_goal": "closed object or null with action, loop/Pack/milestone/objective identity, final-line marker, goal id, optional update target, and observed status",
    "native_goal_policy": "disabled/advisory/required external adapter policy; omitted legacy state means required",
    "thread_registry": "closed records binding bootstrap_role_kind to deterministic formal role_kind plus exact project/task/bootstrap/worktree identity",
    "controller_goal_outbox": "generic GOAL outbox keyed by create/update action id with PREPARED/SENT/ACKED identity and exact native-or-emulated result",
    "controller_lease": "object or null with lease_epoch, never-reused lease_id, owner_kind, owner_identity as the exact registered real Controller threadId string, acquired_at, expires_at, intended_transition, and route actions",
    "routing_turn_count": "integer >= 0 shared by native Goal continuations and heartbeat wakes",
    "routing_turn_ledger": "object keyed by never-reused routing_turn_id with immutable event_id and owner identity",
    "lease_epoch_counter": "integer >= 0",
    "consumed_controller_lease_ids": "array",
    "assurance_ledger": "object keyed by review_kind, milestone, roadmap revision, dispatch, artifact, source Worker dispatch/report, and linked report identities",
    "assurance_dispatch_outbox": "object keyed by CODE_REVIEW/ROADMAP_AUDIT/FINAL_AUDIT dispatch id with PREPARED/SENT/ACKED/COMPLETED identity",
    "goal_queue_history": "array",
    "roadmap_projection": "object or null",
    "local_verification_queue": "array of milestone/goal/verification/local-dispatch/thread/artifact-bound records",
    "local_verification_outbox": "object keyed by local dispatch id with PREPARED/SENT/COMPLETED identity",
    "estimate_history": "array",
    "delegation_ledger": "generic DELEGATION outbox keyed by stable attempt outbox id with PREPARED/SENT/ACKED identity and archived result digest",
    "subagent_attempt_ledger": "object keyed by exploration_id with bounded attempts, payload/report digests, agent identity, and terminal status",
    "finalization_outbox": "null or PREPARED finalization action binding exact Controller Goal and business heartbeat identities",
    "finalization_receipt": "null or evidence-bound ACK proving the exact Goal observation and PAUSED automation observation",
    "run_control": "RUNNING/PAUSE_REQUESTED/PAUSED_AT_SAFE_POINT with effective state version",
    "steering_queue": "ordered classified Steering records",
    "steering_ledger": "idempotent message/turn-bound Steering identity map",
    "active_steering_id": "safe id or null",
    "pending_decisions": "scoped Decision Cards with context digest and preauthorized options",
    "failure_history": "per-Goal deterministic fingerprint history that survives redispatch",
    "failure_policy": "materialized same-strategy threshold 2-3",
    "context_freshness_ledger": "identity deltas and deterministic/judgment classifications",
    "validation_requirements": "per-Goal materialized Validation Matrix",
    "validation_results": "per-Goal acknowledged dimension results",
    "validation_evidence_identity": "exact evidence and artifact digests per dimension",
    "validation_gate_status": "PENDING/PASS/FAIL/PASS_WITH_LIMITATION",
    "status_projection_target": "derived STATUS.md target state version, digest, and render contract",
    "human_control_policy": "canonical switches for optional Steering/STATUS/Decision UX; failure fingerprint, freshness, and evidence safety gates remain mandatory",
}

ADAPTIVE_RUNTIME_MUTATIONS = (
    "INITIALIZE",
    "MIGRATE_V1_TO_V2",
    "MIGRATE_V2_TO_V3",
    "STATE_GATEWAY",
    "PREPARE_CONTROLLER_PACK_MIGRATION",
    "MIGRATE_CONTROLLER_PACK",
    "ROLLBACK_CONTROLLER_PACK_MIGRATION",
    "PREPARE_NATIVE_GOAL_GENERATION_MIGRATION",
    "COMMIT_NATIVE_GOAL_GENERATION_MIGRATION",
    "ROLLBACK_NATIVE_GOAL_GENERATION_MIGRATION",
    "RECORD_HEARTBEAT_OBSERVATION",
    "RECONCILE_WORKER_EXECUTION_CLASSIFICATION",
    "RECORD_STEERING",
    "RESOLVE_STEERING",
    "SET_RUN_CONTROL",
    "REGISTER_DECISION",
    "RECORD_DECISION_RESPONSE",
    "RECORD_FAILURE",
    "RECORD_VALIDATION",
    "RECORD_CONTEXT_FRESHNESS",
    "RECORD_CONTROLLER_GOAL_RESUME",
    "ACQUIRE_LEASE",
    "RELEASE_LEASE",
    "RENEW_LEASE",
    "TAKEOVER_LEASE",
    "PREPARE_OUTBOX",
    "CANCEL_OUTBOX",
    "MARK_OUTBOX_SENT",
    "ACK_OUTBOX",
    "RECORD_REVIEW",
    "ROADMAP_REVISION",
    "FINALIZE_LOOP",
    "STOP_LOOP",
    "ACK_FINALIZATION",
)

ADAPTIVE_OUTBOX_KINDS = (
    "DISPATCH",
    "AUTOMATION",
    "GOAL",
    "THREAD",
    "ASSURANCE",
    "LOCAL",
    "DELEGATION",
)

ADAPTIVE_REVIEW_DECISIONS = (
    "REVIEW_PASS",
    "REVIEW_PASS_WITH_LIMITATION",
    "REVIEW_NEEDS_REPAIR",
    "REVIEW_ARTIFACT_UNAVAILABLE",
    "ROADMAP_AUDIT_PASS",
    "ROADMAP_CHANGE_PROPOSED",
    "ROADMAP_AUDIT_PASS_FINAL_CANDIDATE",
    "ROADMAP_AUDIT_NEEDS_REPAIR",
    "FINAL_REVIEW_PASS",
    "FINAL_REVIEW_PASS_WITH_LIMITATION",
    "FINAL_REVIEW_NEEDS_REPAIR",
)

ADAPTIVE_RUNTIME_SUCCESS_CODES = (
    "LOOP_INITIALIZED",
    "CONTROLLER_LEASE_ACQUIRED",
    "CONTROLLER_LEASE_RELEASED",
    "SAME_OWNER_LEASE_RENEWED",
    "EXPIRED_LEASE_TAKEN_OVER",
    "OUTBOX_ALREADY_PREPARED",
    "OUTBOX_ALREADY_SENT",
    "ROADMAP_REVISION_APPLIED",
    "FINALIZE_LOOP_APPLIED",
    "STOP_LOOP_APPLIED",
    "FINALIZATION_ACKED",
    "IDEMPOTENT_REPLAY",
    "SCHEMA_V2_MIGRATED",
    "SCHEMA_V2_ALREADY_APPLIED",
    "CONTROLLER_PACK_MIGRATION_PREPARED",
    "CONTROLLER_PACK_MIGRATED",
    "CONTROLLER_PACK_MIGRATION_ROLLED_BACK",
    "HEARTBEAT_OBSERVATION_RECORDED",
    "HEARTBEAT_ACTIVE_WHILE_CANONICAL_PAUSED",
    "WORKER_EXECUTION_CLASSIFICATION_RECONCILED",
    "STEERING_CLASSIFIED",
    "STEERING_ALREADY_RECORDED",
    "STEERING_ALREADY_RESOLVED",
    "STEERING_APPLIED",
    "STEERING_DEFERRED",
    "STEERING_CONFLICT",
    "PAUSE_REQUESTED",
    "PAUSED_AT_SAFE_POINT",
    "RUNNING",
    "DECISION_REGISTERED",
    "DECISION_ALREADY_REGISTERED",
    "DECISION_RESPONSE_APPLIED",
    "DECISION_RESPONSE_ALREADY_APPLIED",
    "FAILURE_RECORDED",
    "VALIDATION_RECORDED",
    "CONTEXT_FRESHNESS_RECORDED",
    "CONTEXT_CHECK_ALREADY_RECORDED",
)

DEFAULT_ADAPTIVE_VALUES = {
    "coordination_mode": "standard",
    "delegation_policy": "disabled",
    "max_read_only_subagents": 0,
    "max_read_only_subagent_runs": 0,
    "subagent_retry_limit": 0,
    "subagent_input_policy": "workspace paths and redacted logs only; no secrets or private credentials",
    "subagent_max_depth": 1,
    "local_verification_policy": "not_required",
    "dashboard_policy": "auto",
    "native_goal_policy": "required",
    "dashboard_threshold_hours": 12,
    "human_steering_policy": "auto",
    "status_projection": "enabled",
    "decision_card_policy": "on_real_gate",
    "failure_fingerprint_policy": {"enabled": True},
    "context_freshness_policy": "required_at_gates",
    "review_evidence_policy": "deterministic_first",
    "state_gateway_mode": "MCP_CANONICAL_WRITER",
}

STATE_GATEWAY_MODES = {"MCP_CANONICAL_WRITER", "LEGACY_STATE_WRITER"}


REQUIRED = [
    "objective",
    "repo",
    "repo_mode",
    "workers",
    "permissions",
    "allowed",
    "forbidden",
    "validation",
    "acceptance_criteria",
    "evidence",
    "claim",
    "state",
    "source_artifacts",
]

OPTIONAL = [
    "coordination_mode",
    "adaptive_reason",
    "milestones",
    "delegation_policy",
    "max_read_only_subagents",
    "max_read_only_subagent_runs",
    "subagent_retry_limit",
    "subagent_input_policy",
    "subagent_max_depth",
    "local_verification_policy",
    "dashboard_policy",
    "native_goal_policy",
    "dashboard_threshold_hours",
    "human_steering_policy",
    "status_projection",
    "decision_card_policy",
    "failure_fingerprint_policy",
    "context_freshness_policy",
    "review_evidence_policy",
    "state_gateway_mode",
    "surface",
    "project_name",
    "project_root",
    "workspace_setup",
    "branch",
    "base_branch",
    "target_branch",
    "goals",
    "cost_cap_usd",
    "call_cap",
    "token_cap",
    "controller_goal_token_budget",
    "metered_runtime_policy",
    "human_approval_policy",
    "commit_policy",
    "source_promotion_policy",
    "loop_state_git_policy",
    "thread_topology",
    "max_child_threads",
    "max_repair_attempts_per_goal",
    "runtime_blockers",
    "runtime_readiness",
    "runtime_retry_attempts",
    "runtime_retry_total_minutes",
    "runtime_retry_attempt_timeout_minutes",
    "runtime_retry_no_progress_minutes",
    "time_min",
    "time_typical",
    "time_max",
    "time_factors",
    "automation",
    "cadence",
    "heartbeat_interval_minutes",
    "max_wakeups",
    "max_idle_wakeups",
    "active_stale_after_minutes",
    "discovery",
    "triage_output",
    "connectors",
    "worktree_policy",
    "review",
]

VALID_PERMISSIONS = {"read_only", "workspace_write", "state_write_only"}
VALID_REPO_MODES = {"existing_git", "new_git", "non_git"}
VALID_SURFACES = {"codex_project_auto", "codex_app_auto", "ui_manual"}
VALID_EVIDENCE = {
    "local checks",
    "smoke evidence",
    "long-run/formal acceptance",
    "science/public claim",
}

STATE_SCHEMA_FIELDS = [
    "loop_id",
    "controller_pack_identity",
    "state_version",
    "repo_identity",
    "source_artifacts",
    "current_phase",
    "goal_queue",
    "goal_status_by_id",
    "active_goal",
    "baseline_artifact_identity",
    "current_artifact_identity",
    "integration_workspace_or_worktree_path",
    "dispatch_outbox",
    "inflight_dispatch",
    "thread_creation_outbox",
    "thread_registry",
    "completed_goals",
    "failed_goals",
    "open_blockers",
    "evidence_artifacts",
    "last_processed_event_id",
    "last_state_request_id",
    "last_committed_transaction_id",
    "repair_attempts_by_goal",
    "runtime_retry_attempts_by_goal",
    "wake_count",
    "consecutive_idle_wakeups",
    "automation_outbox",
    "automation",
    "budget_ledger",
    "approval_ledger",
    "next_action",
    "terminal_status",
]

STATE_SCHEMA_TYPES = {
    "loop_id": "string",
    "controller_pack_identity": "object",
    "state_version": "integer >= 0",
    "repo_identity": "object",
    "source_artifacts": "array",
    "current_phase": "string or null",
    "goal_queue": "array",
    "goal_status_by_id": "object",
    "active_goal": "object or null",
    "baseline_artifact_identity": "object or null",
    "current_artifact_identity": "object or null",
    "integration_workspace_or_worktree_path": "string or null",
    "dispatch_outbox": "object",
    "inflight_dispatch": "object or null",
    "thread_creation_outbox": "object",
    "thread_registry": "object",
    "completed_goals": "array",
    "failed_goals": "array",
    "open_blockers": "array",
    "evidence_artifacts": "array",
    "last_processed_event_id": "string or null",
    "last_state_request_id": "string or null",
    "last_committed_transaction_id": "string or null",
    "repair_attempts_by_goal": "object",
    "runtime_retry_attempts_by_goal": "object",
    "wake_count": "integer >= 0",
    "consecutive_idle_wakeups": "integer >= 0",
    "automation_outbox": "object",
    "automation": "object or null",
    "budget_ledger": "object",
    "approval_ledger": "object",
    "next_action": "string or null",
    "terminal_status": "string or null",
}

EVENT_SCHEMA_FIELDS = [
    "event_id",
    "timestamp",
    "actor",
    "thread_id",
    "thread_title",
    "goal_id",
    "dispatch_id",
    "event_type",
    "status",
    "state_version_before",
    "state_version_after",
    "evidence_refs",
    "state_request_id",
    "next_action",
]

EVENT_SCHEMA_TYPES = {
    "event_id": "string",
    "timestamp": "RFC3339 string",
    "actor": "string",
    "thread_id": "string or null",
    "thread_title": "string or null",
    "goal_id": "string or null",
    "dispatch_id": "string or null",
    "event_type": "string",
    "status": "string",
    "state_version_before": "integer >= 0",
    "state_version_after": "integer >= 0",
    "evidence_refs": "array",
    "state_request_id": "string",
    "next_action": "string or null",
}

PHASE_PERMISSION_FIELDS = [
    "git_init",
    "branch_create",
    "local_commit",
    "stage",
    "pr_create",
    "push",
    "merge",
    "deploy",
    "source_promotion",
    "gitignore_hygiene",
    "external_write",
]

FORECAST_FIELDS = (
    "objective",
    "allowed",
    "validation",
    "acceptance_criteria",
    "connectors",
    "automation",
    "discovery",
    "review",
)

WORKER_FIELDS = {
    "role",
    "role_kind",
    "scope",
    "responsibility",
    "permission",
    "sandbox",
    "allowed",
    "validation",
}

GOAL_FIELDS = {
    "goal_id",
    "milestone_id",
    "phase",
    "worker_role",
    "role",
    "objective",
    "success_criteria",
    "validation",
    "allowed_write_scope",
    "allowed",
    "depends_on",
    "dispatch_when",
    "phase_permissions",
    "validation_matrix",
    "review_surface",
}

STRING_OPTIONAL_FIELDS = (
    "coordination_mode",
    "adaptive_reason",
    "delegation_policy",
    "subagent_input_policy",
    "local_verification_policy",
    "dashboard_policy",
    "native_goal_policy",
    "human_steering_policy",
    "status_projection",
    "decision_card_policy",
    "context_freshness_policy",
    "review_evidence_policy",
    "state_gateway_mode",
    "project_name",
    "project_root",
    "workspace_setup",
    "branch",
    "base_branch",
    "target_branch",
    "metered_runtime_policy",
    "human_approval_policy",
    "commit_policy",
    "source_promotion_policy",
    "loop_state_git_policy",
    "thread_topology",
    "runtime_readiness",
    "time_min",
    "time_typical",
    "time_max",
    "automation",
    "cadence",
    "discovery",
    "triage_output",
    "connectors",
    "worktree_policy",
    "review",
)


def _build_input_schema() -> dict:
    string_or_array = {
        "oneOf": [
            {"type": "string", "minLength": 1},
            {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
        ]
    }
    scope_schema = {
        "oneOf": [
            {"type": "string", "minLength": 1},
            {"type": "array", "items": {"type": "string", "minLength": 1}},
        ]
    }
    dependency_schema = {
        "oneOf": [
            {"type": "string", "minLength": 1},
            {
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
        ]
    }
    phase_permissions = {
        "type": "object",
        "additionalProperties": False,
        "properties": {field: {"type": "boolean"} for field in PHASE_PERMISSION_FIELDS},
    }
    validation_rule = {
        "type": "object",
        "required": ["required"],
        "additionalProperties": False,
        "properties": {
            "required": {"type": "boolean"},
            "evidence": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "reason": {"type": "string", "minLength": 1},
        },
        "allOf": [
            {
                "if": {"properties": {"required": {"const": True}}},
                "then": {"required": ["evidence"], "properties": {"evidence": {"minItems": 1}}},
            },
            {
                "if": {"properties": {"required": {"const": False}}},
                "then": {"required": ["reason"]},
            },
        ],
    }
    validation_matrix = {
        "type": "object",
        "additionalProperties": False,
        "required": list(VALIDATION_DIMENSIONS),
        "properties": {
            name: validation_rule
            for name in VALIDATION_DIMENSIONS
        },
    }
    review_surface = {
        "type": "object",
        "required": [
            "required",
            "type",
            "artifact_path",
            "preview_url",
            "evidence_refs",
            "review_questions",
            "decision_gate_id",
        ],
        "additionalProperties": False,
        "properties": {
            "required": {"type": "boolean"},
            "type": {"enum": ["browser_preview", "screenshot", "markdown", "tabular_data", "pdf", "slides", "diff", "other_artifact", "NOT_APPLICABLE"]},
            "artifact_path": {"type": ["string", "null"]},
            "preview_url": {"type": ["string", "null"]},
            "evidence_refs": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "review_questions": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "decision_gate_id": {
                "oneOf": [
                    {"type": "null"},
                    {"type": "string", "pattern": SAFE_ID_PATTERN},
                ]
            },
            "reason": {"type": "string", "minLength": 1},
        },
        "allOf": [
            {
                "if": {"properties": {"required": {"const": True}}},
                "then": {
                    "required": ["decision_gate_id"],
                    "properties": {
                        "decision_gate_id": {
                            "type": "string",
                            "pattern": SAFE_ID_PATTERN,
                        },
                        "review_questions": {"minItems": 1},
                    },
                    "anyOf": [
                        {"properties": {"artifact_path": {"type": "string", "minLength": 1}}},
                        {"properties": {"preview_url": {"type": "string", "minLength": 1}}},
                    ],
                },
            },
            {
                "if": {"properties": {"type": {"const": "NOT_APPLICABLE"}}},
                "then": {
                    "required": ["reason"],
                    "properties": {"required": {"const": False}},
                },
            },
        ],
    }
    worker = {
        "type": "object",
        "required": ["role"],
        "additionalProperties": False,
        "properties": {
            "role": {"type": "string", "minLength": 1},
            "role_kind": {"enum": sorted(ROLE_KINDS)},
            "scope": {"type": "string"},
            "responsibility": {"type": "string"},
            "permission": {"enum": sorted(VALID_PERMISSIONS)},
            "sandbox": {"enum": sorted(VALID_PERMISSIONS)},
            "allowed": scope_schema,
            "validation": string_or_array,
        },
    }
    goal = {
        "type": "object",
        "required": ["goal_id", "objective", "success_criteria"],
        "anyOf": [{"required": ["worker_role"]}, {"required": ["role"]}],
        "additionalProperties": False,
        "properties": {
            "goal_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 80,
                "pattern": SAFE_GOAL_ID_PATTERN,
            },
            "milestone_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": SAFE_MILESTONE_ID_PATTERN,
            },
            "phase": {"type": "string", "minLength": 1},
            "worker_role": {"type": "string", "minLength": 1},
            "role": {"type": "string", "minLength": 1},
            "objective": {"type": "string", "minLength": 1},
            "success_criteria": string_or_array,
            "validation": string_or_array,
            "allowed_write_scope": scope_schema,
            "allowed": scope_schema,
            "depends_on": dependency_schema,
            "dispatch_when": {"type": "string", "minLength": 1},
            "phase_permissions": phase_permissions,
            "validation_matrix": validation_matrix,
            "review_surface": review_surface,
        },
    }
    milestone = {
        "type": "object",
        "required": ["milestone_id", "outcome", "scope", "required_evidence", "status"],
        "additionalProperties": False,
        "properties": {
            "milestone_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": SAFE_MILESTONE_ID_PATTERN,
            },
            "outcome": {"type": "string", "minLength": 1},
            "scope": string_or_array,
            "decisions": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "blockers": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "required_evidence": string_or_array,
            "status": {"enum": sorted(MILESTONE_STATUSES)},
            "depends_on": {
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
            "references": {
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
        },
    }
    positive_integer = {
        "oneOf": [
            {"type": "integer", "minimum": 1},
            {"type": "string", "pattern": "^[1-9][0-9]*$"},
        ]
    }
    bounded_integer_rules = {
        "runtime_retry_attempts": (10, 100),
        "runtime_retry_total_minutes": (10, 1440),
        "runtime_retry_attempt_timeout_minutes": (1, 240),
        "runtime_retry_no_progress_minutes": (1, 120),
        "heartbeat_interval_minutes": (1, 1440),
        "max_wakeups": (1, 10000),
        "max_idle_wakeups": (1, 1000),
        "active_stale_after_minutes": (5, 10080),
        "max_child_threads": (2, 32),
        "max_repair_attempts_per_goal": (0, 20),
    }
    adaptive_properties = {
        "workers": {
            "type": "array",
            "minItems": 1,
            "items": {"allOf": [worker, {"required": ["role_kind"]}]},
        },
        "goals": {
            "type": "array",
            "minItems": 1,
            "items": {"allOf": [goal, {"required": ["milestone_id"]}]},
        },
        "call_cap": {"type": "integer", "minimum": 1},
        "token_cap": {"type": "integer", "minimum": 1},
    }
    adaptive_properties.update(
        {
            field: {"type": "integer", "minimum": minimum, "maximum": maximum}
            for field, (minimum, maximum) in bounded_integer_rules.items()
        }
    )
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Codex Loop Prompt Scaffold Input",
        "type": "object",
        "required": REQUIRED,
        "additionalProperties": False,
        "properties": {
            "objective": {"type": "string", "minLength": 1},
            "repo": {"type": "string", "minLength": 1},
            "repo_mode": {"enum": sorted(VALID_REPO_MODES)},
            "workers": {
                "oneOf": [
                    {"type": "string", "minLength": 1},
                    {"type": "array", "minItems": 1, "items": {"oneOf": [worker, {"type": "string", "minLength": 1}]}},
                ]
            },
            "permissions": {
                "oneOf": [
                    {"type": "string", "minLength": 1},
                    {"type": "object", "additionalProperties": {"enum": sorted(VALID_PERMISSIONS)}},
                ]
            },
            "allowed": scope_schema,
            "forbidden": string_or_array,
            "validation": string_or_array,
            "acceptance_criteria": string_or_array,
            "evidence": {"enum": sorted(VALID_EVIDENCE)},
            "claim": {"type": "string", "minLength": 1},
            "state": {"type": "string", "minLength": 1},
            "source_artifacts": string_or_array,
            "goals": {"type": "array", "minItems": 1, "items": goal},
            "coordination_mode": {"enum": sorted(COORDINATION_MODES)},
            "adaptive_reason": {"type": "string", "minLength": 1},
            "milestones": {"type": "array", "minItems": 1, "items": milestone},
            "delegation_policy": {"enum": sorted(DELEGATION_POLICIES)},
            "max_read_only_subagents": {"type": "integer", "minimum": 0, "maximum": 2},
            "max_read_only_subagent_runs": {"type": "integer", "minimum": 0, "maximum": 16},
            "subagent_retry_limit": {"type": "integer", "minimum": 0, "maximum": 2},
            "subagent_input_policy": {"type": "string", "minLength": 1},
            "subagent_max_depth": {"const": 1},
            "local_verification_policy": {"enum": sorted(LOCAL_VERIFICATION_POLICIES)},
            "dashboard_policy": {"enum": sorted(DASHBOARD_POLICIES)},
            "native_goal_policy": {"enum": sorted(NATIVE_GOAL_POLICIES)},
            "dashboard_threshold_hours": {"type": "integer", "minimum": 1},
            "human_steering_policy": {"enum": ["auto", "enabled", "disabled"]},
            "status_projection": {"enum": ["enabled", "disabled"]},
            "decision_card_policy": {"enum": ["on_real_gate", "disabled"]},
            "failure_fingerprint_policy": {
                "type": "object",
                "required": ["enabled"],
                "additionalProperties": False,
                "properties": {"enabled": {"type": "boolean"}},
            },
            "context_freshness_policy": {"enum": ["required_at_gates", "disabled"]},
            "review_evidence_policy": {"enum": ["deterministic_first"]},
            "state_gateway_mode": {"enum": sorted(STATE_GATEWAY_MODES)},
        },
        "allOf": [
            {
                "if": {"properties": {"coordination_mode": {"const": "adaptive"}}, "required": ["coordination_mode"]},
                "then": {
                    "required": ["adaptive_reason", "milestones", "goals"],
                    "properties": adaptive_properties,
                },
            }
        ],
    }
    for field in OPTIONAL:
        schema["properties"].setdefault(field, {"type": ["string", "number", "integer", "array", "object"]})
    schema["properties"]["surface"] = {"enum": sorted(VALID_SURFACES)}
    for field in STRING_OPTIONAL_FIELDS:
        schema["properties"][field] = {"type": "string", "minLength": 1}
    schema["properties"]["coordination_mode"] = {"enum": sorted(COORDINATION_MODES)}
    schema["properties"]["delegation_policy"] = {"enum": sorted(DELEGATION_POLICIES)}
    schema["properties"]["local_verification_policy"] = {"enum": sorted(LOCAL_VERIFICATION_POLICIES)}
    schema["properties"]["dashboard_policy"] = {"enum": sorted(DASHBOARD_POLICIES)}
    schema["properties"]["native_goal_policy"] = {"enum": sorted(NATIVE_GOAL_POLICIES)}
    schema["properties"]["human_steering_policy"] = {"enum": ["auto", "enabled", "disabled"]}
    schema["properties"]["status_projection"] = {"enum": ["enabled", "disabled"]}
    schema["properties"]["decision_card_policy"] = {"enum": ["on_real_gate", "disabled"]}
    schema["properties"]["context_freshness_policy"] = {"enum": ["required_at_gates", "disabled"]}
    schema["properties"]["review_evidence_policy"] = {"enum": ["deterministic_first"]}
    schema["properties"]["state_gateway_mode"] = {"enum": sorted(STATE_GATEWAY_MODES)}
    schema["properties"]["failure_fingerprint_policy"] = {
        "type": "object",
        "required": ["enabled"],
        "additionalProperties": False,
        "properties": {"enabled": {"type": "boolean"}},
    }
    for field in ("runtime_blockers", "time_factors"):
        schema["properties"][field] = string_or_array
    for field in (
        "call_cap",
        "token_cap",
    ):
        schema["properties"][field] = positive_integer
    for field, (minimum, maximum) in bounded_integer_rules.items():
        schema["properties"][field] = {
            "oneOf": [
                {"type": "integer", "minimum": minimum, "maximum": maximum},
                {"type": "string", "pattern": "^[1-9][0-9]*$"},
            ]
        }
    schema["properties"]["controller_goal_token_budget"] = {
        "type": "integer",
        "minimum": 1,
    }
    for field, maximum in (
        ("max_read_only_subagents", 2),
        ("max_read_only_subagent_runs", 16),
        ("subagent_retry_limit", 2),
    ):
        schema["properties"][field] = {"type": "integer", "minimum": 0, "maximum": maximum}
    schema["properties"]["cost_cap_usd"] = {
        "oneOf": [
            {"type": "number", "exclusiveMinimum": 0},
            {"type": "string", "pattern": "^(?:[1-9][0-9]*(?:\\.[0-9]+)?|0\\.(?:0*[1-9][0-9]*))$"},
        ]
    }
    return schema


INPUT_SCHEMA = _build_input_schema()
