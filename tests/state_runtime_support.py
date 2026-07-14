from __future__ import annotations

import copy
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "codex-loop-prompt-architect" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from loop_architect.state_runtime import (  # noqa: E402
    ARTIFACT_STAGES,
    PAYLOAD_DIGEST_PLACEHOLDER,
    PERSISTENT_STAGES,
    AdaptiveStateRuntime,
    InjectedCrash,
    goal_definition_payload_digest,
    materialize_dispatch_payload,
    verify_dispatch_payload_against_state,
)
import loop_architect.state_runtime as state_runtime_module  # noqa: E402


T0 = "2026-01-01T00:00:00Z"
T1 = "2026-01-01T00:01:00Z"
T2 = "2026-01-01T00:02:00Z"
T3 = "2026-01-01T00:03:00Z"
T4 = "2026-01-01T01:00:00Z"


def digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def json_digest(value: Any) -> str:
    return digest(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def context_identity_delta(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "repo_mode": "non_git",
        "repo_root_digest": digest("repo-root"),
        "worktree_root_digest": digest("worktree-root"),
        "branch": None,
        "base_sha": None,
        "head_sha": None,
        "dirty_boundary_digest": digest("dirty-boundary"),
        "untracked_boundary_digest": digest("untracked-boundary"),
        "source_artifact_digest": digest("source-artifacts"),
        "target_scope_digest": digest("target-scope"),
        "dependency_interface_digest": digest("dependency-interfaces"),
        "lockfile_digest": digest("lockfile"),
        "generated_config_digest": digest("generated-config"),
        "worker_report_digest": None,
        "artifact_digest": None,
        "diff_digest": None,
        "changed_paths": [],
        "base_sha_changed": False,
        "head_sha_changed": False,
        "dirty_boundary_changed": False,
        "untracked_boundary_changed": False,
        "source_digest_changed": False,
        "target_scope_changed": False,
        "dependency_interface_changed": False,
        "lockfile_digest_changed": False,
        "generated_config_changed": False,
        "worker_report_changed": False,
        "artifact_digest_changed": False,
        "diff_digest_changed": False,
        "scope_overlap": False,
        "symlink_escape": False,
        "wildcard_ambiguity": False,
        "reload_completed": False,
    }
    value.update(overrides)
    return value


def complete_validation_matrix(
    *, required_dimensions: tuple[str, ...] = ("functional",)
) -> dict[str, dict[str, Any]]:
    dimensions = (
        "functional",
        "regression",
        "static_quality",
        "compatibility",
        "security",
        "performance",
        "user_experience",
        "change_impact",
    )
    return {
        dimension: (
            {"required": True, "evidence": [f"{dimension} evidence"]}
            if dimension in required_dimensions
            else {"required": False, "reason": "not required by this fixture"}
        )
        for dimension in dimensions
    }


def read_evidence_artifact(name: str, content: str) -> dict[str, str]:
    return {
        "path": f".codex-loop/reports/{name}.json",
        "content": content,
        "digest": digest(content),
        "media_type": "application/json",
    }


def read_status_evidence(
    name: str, fields: dict[str, str]
) -> tuple[dict[str, str], dict[str, str]]:
    content = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    artifact = read_evidence_artifact(name, content)
    return (
        {
            **fields,
            "read_digest": artifact["digest"],
            "read_evidence_path": artifact["path"],
        },
        artifact,
    )


def expected_projection_digest(
    state: dict[str, Any], mutation: dict[str, Any]
) -> str:
    candidate = copy.deepcopy(state)
    if mutation["type"] == "ROADMAP_REVISION":
        candidate["roadmap_version"] = mutation["base_roadmap_version"] + 1
        candidate["milestones"] = copy.deepcopy(mutation["milestones"])
        candidate["goal_queue"] = copy.deepcopy(mutation["goal_queue"])
        candidate["goal_definition_registry"] = copy.deepcopy(
            mutation["goal_definition_registry"]
        )
        active = [
            item["milestone_id"]
            for item in candidate["milestones"]
            if item["status"] == "ACTIVE"
        ]
        candidate["active_milestone_id"] = active[0] if len(active) == 1 else None
    elif mutation["type"] == "FINALIZE_LOOP":
        candidate["roadmap_version"] = mutation["base_roadmap_version"] + 1
        candidate["active_milestone_id"] = None
        candidate["goal_queue"] = []
        for milestone_record in candidate["milestones"]:
            if milestone_record["status"] == "ACTIVE":
                milestone_record["status"] = "COMPLETE"
    else:
        raise AssertionError("unsupported projection mutation")
    payload = {
        "roadmap_version": candidate["roadmap_version"],
        "active_milestone_id": candidate["active_milestone_id"],
        "milestones": candidate["milestones"],
        "goal_queue": candidate["goal_queue"],
        "goal_definition_registry": candidate["goal_definition_registry"],
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(serialized).hexdigest()


def roadmap_plan(
    *,
    proposal_id: str,
    operations: list[dict[str, Any]],
    milestones: list[dict[str, Any]],
    goal_definition_registry: dict[str, dict[str, Any]],
    goal_queue: list[dict[str, Any]],
    authorization_envelope: dict[str, Any],
    next_goal_id: str,
    reason_code: str,
    estimate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "proposal_id": proposal_id,
        "operations": copy.deepcopy(operations),
        "milestones": copy.deepcopy(milestones),
        "goal_definition_registry": copy.deepcopy(goal_definition_registry),
        "goal_queue": copy.deepcopy(goal_queue),
        "authorization_envelope": copy.deepcopy(authorization_envelope),
        "next_goal_id": next_goal_id,
        "reason_code": reason_code,
    }
    if estimate is not None:
        result["estimate"] = copy.deepcopy(estimate)
    return result


def controller_pack_artifact(content: str = "# Test Controller Pack\n") -> dict[str, str]:
    return {
        "path": ".codex-loop/sources/CONTROLLER_PACK.md",
        "content": content,
        "digest": digest(content),
        "media_type": "text/markdown",
    }


PERMISSION_FIELDS = (
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
)


def goal_definition_digest(definition: dict[str, Any], *, ensure_ascii: bool = False) -> str:
    payload = {
        key: copy.deepcopy(value)
        for key, value in definition.items()
        if key != "payload_template_digest"
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=ensure_ascii,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(serialized).hexdigest()


def milestone(
    milestone_id: str,
    status: str,
    *,
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "milestone_id": milestone_id,
        "outcome": f"Outcome {milestone_id}",
        "scope": ["src/**"],
        "decisions": [],
        "blockers": [],
        "required_evidence": ["unit-test"],
        "status": status,
        "depends_on": list(depends_on or []),
        "references": [],
    }


def goal(
    goal_id: str,
    milestone_id: str,
    *,
    depends_on: list[str] | None = None,
    objective: str | None = None,
    phase_permissions: dict[str, bool] | None = None,
) -> dict[str, Any]:
    definition = {
        "goal_id": goal_id,
        "milestone_id": milestone_id,
        "worker_role": "Worker",
        "worker_role_kind": "implementation",
        "objective": objective or f"Execute {goal_id}",
        "success_criteria": [f"{goal_id} complete"],
        "validation": ["python3 -m unittest"],
        "validation_matrix": complete_validation_matrix(required_dimensions=()),
        "allowed_write_scope": ["src/**"],
        "phase_permissions": {
            **{permission: False for permission in PERMISSION_FIELDS},
            **copy.deepcopy(
                phase_permissions
                if phase_permissions is not None
                else {"local_commit": True}
            ),
        },
        "depends_on": list(depends_on or []),
        "dispatch_when": "dependencies complete",
    }
    definition["payload_template_digest"] = goal_definition_digest(definition)
    return definition


def authorization_envelope(
    definitions: dict[str, dict[str, Any]],
    milestones: list[dict[str, Any]],
) -> dict[str, Any]:
    top = {permission: False for permission in PERMISSION_FIELDS}
    by_milestone = {
        item["milestone_id"]: {permission: False for permission in PERMISSION_FIELDS}
        for item in milestones
    }
    by_goal: dict[str, dict[str, Any]] = {}
    for goal_id, definition in definitions.items():
        milestone_id = definition["milestone_id"]
        permissions = {permission: False for permission in PERMISSION_FIELDS}
        permissions.update(definition["phase_permissions"])
        for permission, value in permissions.items():
            if value:
                top[permission] = True
                by_milestone[milestone_id][permission] = True
        by_goal[goal_id] = {
            "milestone_id": milestone_id,
            "phase_permissions": permissions,
        }
    return {
        "objective_id": digest("test-objective"),
        "allowed_write_scope": ["src/**"],
        "phase_permissions": top,
        "phase_permission_caps": {
            "by_milestone": by_milestone,
            "by_goal": by_goal,
        },
        "control_plane_caps": {
            "thread_create": True,
            "automation_manage": True,
            "goal_manage": True,
            "message_send": True,
            "local_verifier": True,
        },
        "control_plane_limits": {
            "max_child_threads": 4,
            "max_business_heartbeats": 1,
            "allowed_external_worktree_roots": [],
        },
        "delegation_policy": {
            "mode": "disabled",
            "max_concurrent": 0,
            "max_lifetime_runs": 0,
            "retry_limit_per_exploration": 0,
            "max_depth": 1,
        },
        "repair_policy": {"max_repair_attempts_per_goal": 5},
        "budget_caps": {"cost_usd": None, "calls": None, "tokens": None},
        "connectors": [],
        "side_effects": copy.deepcopy(top),
        "evidence_policy": "LOCAL_TEST_EVIDENCE",
        "claim_boundary": "LOCAL_TEST_ONLY",
        "production_access": False,
        "secrets_access": False,
    }


def queue_entry(
    goal_id: str,
    milestone_id: str,
    status: str,
    roadmap_version: int,
    *,
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "goal_id": goal_id,
        "milestone_id": milestone_id,
        "roadmap_version": roadmap_version,
        "status": status,
        "depends_on": list(depends_on or []),
    }


class Harness:
    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.runtime = AdaptiveStateRuntime(self.root)
        self.counter = 0
        self.identity_counter = 0
        self.definitions: dict[str, dict[str, Any]] = {}
        self.authorization: dict[str, Any] = {}

    def next_id(self, prefix: str) -> str:
        self.identity_counter += 1
        return f"{prefix}-{self.identity_counter}"

    def state(self) -> dict[str, Any]:
        state = self.runtime.read_state()
        assert state is not None
        return state

    def version(self) -> int:
        state = self.runtime.read_state()
        return state["state_version"] if state is not None else 0

    def make_request(
        self,
        mutation: dict[str, Any],
        *,
        expected: int | None = None,
        request_id: str | None = None,
        event_id: str | None = None,
        evidence_paths: list[str] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.counter += 1
        request_id = request_id or f"request-{self.counter}"
        event_id = event_id or f"event-{self.counter}"
        request = {
            "controller_approved": True,
            "state_request_id": request_id,
            "event_id": event_id,
            "expected_state_version": self.version() if expected is None else expected,
            "actor": "CONTROLLER",
            "thread_id": "controller-1",
            "occurred_at": T0,
            "evidence_paths": evidence_paths or [f"evidence/{event_id}.json"],
            "mutation": copy.deepcopy(mutation),
        }
        if artifacts is not None:
            request["artifacts"] = copy.deepcopy(artifacts)
        return request

    def apply(
        self,
        mutation: dict[str, Any],
        *,
        expected: int | None = None,
        artifacts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        request = self.make_request(
            mutation,
            expected=expected,
            artifacts=artifacts,
        )
        response = self.runtime.apply(request)
        return response

    def initialize(
        self,
        *,
        milestones: list[dict[str, Any]] | None = None,
        definitions: dict[str, dict[str, Any]] | None = None,
        queue: list[dict[str, Any]] | None = None,
        authorization: dict[str, Any] | None = None,
        local_required_goal_ids: list[str] | None = None,
        dashboard_required: bool = False,
        human_control_policy: dict[str, Any] | None = None,
        native_goal_policy: str = "required",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        definitions = definitions or {"g1": goal("g1", "m1")}
        milestones = milestones or [milestone("m1", "ACTIVE")]
        queue = queue or [queue_entry("g1", "m1", "READY", 1)]
        self.definitions = copy.deepcopy(definitions)
        self.authorization = copy.deepcopy(
            authorization or authorization_envelope(definitions, milestones)
        )
        pack = controller_pack_artifact()
        request = self.make_request(
            {
                "type": "INITIALIZE",
                "loop_id": "loop-1",
                "project_id": "test-project",
                "controller_pack_digest": pack["digest"],
                "controller_thread_id": "controller-1",
                "controller_bootstrap_prompt_digest": digest("controller-bootstrap"),
                "state_writer_thread_id": "state-writer-1",
                "state_writer_bootstrap_prompt_digest": digest("state-writer-bootstrap"),
                "dashboard_required": dashboard_required,
                "native_goal_policy": native_goal_policy,
                "milestones": milestones,
                "goal_definition_registry": definitions,
                "goal_queue": queue,
                "authorization_envelope": self.authorization,
                "local_verification_required_goal_ids": list(
                    local_required_goal_ids or []
                ),
                **(
                    {"human_control_policy": copy.deepcopy(human_control_policy)}
                    if human_control_policy is not None
                    else {}
                ),
            },
            expected=0,
            artifacts=[pack],
        )
        return self.runtime.apply(request), request

    def acquire(
        self,
        *,
        owner_kind: str = "GOAL_TURN",
        observed_at: str = T1,
        expires_at: str = T4,
    ) -> dict[str, Any]:
        lease_id = self.next_id("lease")
        response = self.apply(
            {
                "type": "ACQUIRE_LEASE",
                "routing_turn_id": self.next_id("turn"),
                "lease_id": lease_id,
                "owner_kind": owner_kind,
                "owner_identity": "controller-1",
                "observed_at": observed_at,
                "expires_at": expires_at,
            }
        )
        if not response["ok"]:
            raise AssertionError(response)
        return response["result"]["lease_claim"]

    def prepare_outbox(
        self,
        claim: dict[str, Any],
        kind: str,
        outbox_id: str,
        identity: dict[str, Any],
        *,
        payload_digest: str | None = None,
        target_id: str = "target-1",
        observed_at: str = T1,
    ) -> tuple[dict[str, Any], str]:
        identity = copy.deepcopy(identity)
        payload = payload_digest or digest(f"payload:{outbox_id}")
        if kind == "THREAD":
            formal_role_kind = identity.get(
                "formal_role_kind", identity.get("role_kind", "WORKER")
            )
            bootstrap_role_kind = identity.get(
                "bootstrap_role_kind",
                {
                    "WORKER": "implementation",
                    "REVIEWER": "code_reviewer",
                    "LOCAL_VERIFIER": "local_verifier",
                }[formal_role_kind],
            )
            identity = {
                "project_id": "test-project",
                "task_kind": "PROJECT_TASK",
                "bootstrap_role_kind": bootstrap_role_kind,
                "formal_role_kind": formal_role_kind,
                "bootstrap_prompt_digest": digest(f"bootstrap:{bootstrap_role_kind}"),
                "environment_kind": identity.get("environment_kind", "LOCAL"),
            }
        elif kind == "DISPATCH":
            identity = {
                "dispatch_id": outbox_id,
                "goal_id": identity["goal_id"],
                "goal_definition_digest": identity["goal_definition_digest"],
                "payload_digest": payload,
                "target_thread_id": target_id,
                "worker_role_kind": self.definitions[identity["goal_id"]][
                    "worker_role_kind"
                ],
            }
        elif kind == "ASSURANCE":
            review_kind = identity["review_kind"]
            identity = {
                "review_dispatch_id": outbox_id,
                "review_kind": review_kind,
                "goal_id": identity["goal_id"],
                "milestone_id": self.state()["active_milestone_id"],
                "roadmap_version": self.state()["roadmap_version"],
                "target_reviewer_thread_id": target_id,
                "payload_digest": payload,
                "worker_dispatch_id": identity["worker_dispatch_id"],
                "worker_report_digest": identity["worker_report_digest"],
                "artifact_digest": identity["artifact_digest"],
                **(
                    {"code_review_id": identity["code_review_id"]}
                    if review_kind in {"ROADMAP_AUDIT", "FINAL_AUDIT"}
                    else {}
                ),
                **(
                    {"roadmap_audit_id": identity["roadmap_audit_id"]}
                    if review_kind == "FINAL_AUDIT"
                    else {}
                ),
            }
        elif kind == "LOCAL":
            identity = {
                "local_dispatch_id": outbox_id,
                "verification_id": identity["verification_id"],
                "goal_id": identity["goal_id"],
                "milestone_id": self.state()["active_milestone_id"],
                "roadmap_version": self.state()["roadmap_version"],
                "target_thread_id": target_id,
                "payload_digest": payload,
                "worker_dispatch_id": identity["worker_dispatch_id"],
                "artifact_digest": identity["artifact_digest"],
                "code_review_id": identity["code_review_id"],
            }
        elif kind == "AUTOMATION":
            identity = {
                "automation_name": "test-loop-heartbeat",
                "kind": "HEARTBEAT",
                "target_thread_id": "controller-1",
                "rrule": "FREQ=MINUTELY;INTERVAL=10",
                "prompt_digest": digest("heartbeat-prompt"),
                "prompt_normalization": "LF_NORMALIZED_NO_TRAILING_NEWLINE",
            }
        elif kind == "GOAL":
            action = identity.get("action", "CREATE")
            milestone_id = identity.get(
                "milestone_id", self.state()["active_milestone_id"] or "m1"
            )
            objective_digest = identity.get(
                "objective_digest", digest(f"goal-objective:{milestone_id}")
            )
            marker = identity.get(
                "marker",
                "[CODEX_LOOP_MILESTONE "
                f"loop_id=loop-1 "
                f"pack_sha256={controller_pack_artifact()['digest'].removeprefix('sha256:')} "
                f"milestone_id={milestone_id} "
                f"objective_sha256={objective_digest.removeprefix('sha256:')}]",
            )
            identity = {
                "action": action,
                "loop_id": "loop-1",
                "pack_digest": controller_pack_artifact()["digest"],
                "milestone_id": milestone_id,
                "objective_digest": objective_digest,
                "marker": marker,
                **(
                    {
                        "goal_id": identity.get("goal_id", "native-goal-1"),
                        "target_status": identity.get("target_status", "COMPLETE"),
                    }
                    if action == "UPDATE"
                    else {}
                ),
            }
        response = self.apply(
            {
                "type": "PREPARE_OUTBOX",
                "lease_claim": claim,
                "observed_at": observed_at,
                "outbox_kind": kind,
                "outbox_id": outbox_id,
                "payload_digest": payload,
                "target_id": target_id,
                "identity": identity,
            }
        )
        return response, payload

    def mark_sent(
        self,
        claim: dict[str, Any],
        kind: str,
        outbox_id: str,
        payload: str,
        *,
        target_id: str = "target-1",
        observed_at: str = T1,
    ) -> dict[str, Any]:
        observation = {
            "observation_kind": "EXTERNAL_SEND",
            "outbox_kind": kind,
            "outbox_id": outbox_id,
            "payload_digest": payload,
            "target_id": target_id,
        }
        content = json.dumps(observation, sort_keys=True, separators=(",", ":"))
        artifact = read_evidence_artifact(f"{outbox_id}-send", content)
        return self.apply(
            {
                "type": "MARK_OUTBOX_SENT",
                "lease_claim": claim,
                "observed_at": observed_at,
                "outbox_kind": kind,
                "outbox_id": outbox_id,
                "payload_digest": payload,
                "target_id": target_id,
                "send_evidence_paths": [artifact["path"]],
            },
            artifacts=[artifact],
        )

    def formal_report_content(
        self,
        kind: str,
        outbox_id: str,
        result: dict[str, Any],
        *,
        extra_fields: dict[str, Any] | None = None,
    ) -> str:
        state = self.state()
        field = {
            "DISPATCH": "dispatch_outbox",
            "ASSURANCE": "assurance_dispatch_outbox",
            "LOCAL": "local_verification_outbox",
        }[kind]
        record = state[field][outbox_id]
        identity = record["identity"]
        goal_id = identity["goal_id"]
        milestone_id = (
            state["goal_definition_registry"][goal_id]["milestone_id"]
            if kind == "DISPATCH"
            else identity["milestone_id"]
        )
        report: dict[str, Any] = {
            "status": result["status"],
            "report_digest": "PENDING_CONTROLLER_ARCHIVE",
            "goal_id": goal_id,
            "dispatch_id": outbox_id,
            "milestone_id": milestone_id,
            "roadmap_version": record["roadmap_version"],
            "target_thread_id": record["target_id"],
            "thread_id": record["target_id"],
            "dispatch_payload_digest": record["payload_digest"],
            "source_artifact_digest": result["artifact_digest"],
        }
        if kind == "DISPATCH":
            report["after_snapshot_sha256"] = result[
                "artifact_digest"
            ].removeprefix("sha256:")
            report["source_goal_definition_digest_or_none"] = identity[
                "goal_definition_digest"
            ]
            if result["status"] == "PASS":
                empty_sha256 = hashlib.sha256(b"").hexdigest()
                report.update(
                    {
                        "worktree_path": str(self.root.resolve()),
                        "current_branch": "NOT_APPLICABLE",
                        "base_sha": "NOT_APPLICABLE",
                        "head_sha": "NOT_APPLICABLE",
                        "before_snapshot_sha256": result[
                            "artifact_digest"
                        ].removeprefix("sha256:"),
                        "changed_files": [],
                        "diff_sha256": empty_sha256,
                        "complete_diff_reference": {
                            "kind": "NO_DIFF",
                            "hash_algorithm": "sha256",
                            "sha256": empty_sha256,
                        },
                        "validation_results": [],
                        "evidence_artifacts": [],
                    }
                )
        elif kind == "LOCAL":
            report.update(
                {
                    "source_worker_dispatch_id": identity["worker_dispatch_id"],
                    "verification_id": identity["verification_id"],
                }
            )
        else:
            worker_outbox = state["dispatch_outbox"][identity["worker_dispatch_id"]]
            report.update(
                {
                    "review_kind": identity["review_kind"],
                    "review_dispatch_id": outbox_id,
                    "review_decision": result["status"],
                    "source_worker_dispatch_id": identity["worker_dispatch_id"],
                    "source_worker_report_digest": identity[
                        "worker_report_digest"
                    ],
                    "worker_thread_id": worker_outbox["target_id"],
                }
            )
        if extra_fields:
            report.update(copy.deepcopy(extra_fields))
        return json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def ack_outbox(
        self,
        claim: dict[str, Any],
        kind: str,
        outbox_id: str,
        payload: str,
        *,
        result: dict[str, Any] | None = None,
        target_id: str = "target-1",
        observed_at: str = T1,
        report_content: str | None = None,
        attach_report: bool = True,
    ) -> dict[str, Any]:
        if result is None and kind == "AUTOMATION":
            identity = self.state()["automation_outbox"][outbox_id]["identity"]
            result = {
                **identity,
                "automation_id": "heartbeat-1",
                "status": "ACTIVE",
            }
        mutation: dict[str, Any] = {
            "type": "ACK_OUTBOX",
            "lease_claim": claim,
            "observed_at": observed_at,
            "outbox_kind": kind,
            "outbox_id": outbox_id,
            "payload_digest": payload,
            "target_id": target_id,
            "ack_evidence_paths": [f"evidence/{outbox_id}-ack.json"],
        }
        if result is not None:
            mutation["result"] = result
        artifacts: list[dict[str, str]] = []
        if kind in {"DISPATCH", "ASSURANCE", "LOCAL"} and result is not None and attach_report:
            if report_content is None:
                raise AssertionError("report_content is required for report-bearing ACKs")
            try:
                staged = self.runtime.stage_formal_report(
                    {
                        "outbox_id": outbox_id,
                        "result": {
                            "status": result["status"],
                            "artifact_digest": result["artifact_digest"],
                        },
                        "report": json.loads(report_content),
                    }
                )
            except state_runtime_module.RuntimeRejection as rejection:
                return {
                    "ok": False,
                    "status": rejection.code,
                    "error": {
                        "code": rejection.code,
                        "path": rejection.path,
                        "details": rejection.details,
                    },
                }
            if result.get("report_digest") != staged["report_digest"]:
                raise AssertionError("result report_digest must bind the report artifact")
            mutation["result"] = staged["result"]
            mutation["ack_evidence_paths"] = staged["ack_evidence_paths"]
            artifacts.append(staged["artifact"])
        elif kind == "DELEGATION" and result is not None and attach_report:
            if report_content is None:
                raise AssertionError("report_content is required for report-bearing ACKs")
            report_path = f".codex-loop/reports/{outbox_id}-ack.json"
            mutation["ack_evidence_paths"] = [report_path]
            report_artifact = {
                "path": report_path,
                "content": report_content,
                "digest": digest(report_content),
                "media_type": "application/json",
            }
            if result.get("report_digest") != report_artifact["digest"]:
                raise AssertionError("result report_digest must bind the report artifact")
            artifacts.append(report_artifact)
        elif kind in {"THREAD", "AUTOMATION", "GOAL"} and result is not None:
            state = self.state()
            record = state[
                {
                    "THREAD": "thread_creation_outbox",
                    "AUTOMATION": "automation_outbox",
                    "GOAL": "controller_goal_outbox",
                }[kind]
            ][outbox_id]
            observation = {
                "observation_kind": (
                    "GOAL_TOOL_UNAVAILABLE"
                    if kind == "GOAL" and record["status"] == "PREPARED"
                    else "CODEX_TOOL_RESULT"
                ),
                "outbox_kind": kind,
                "outbox_id": outbox_id,
                "payload_digest": payload,
                "target_id": target_id,
                "result": result,
            }
            content = json.dumps(
                observation,
                sort_keys=True,
                separators=(",", ":"),
            )
            observation_artifact = read_evidence_artifact(
                f"{outbox_id}-tool-observation",
                content,
            )
            mutation["ack_evidence_paths"] = [observation_artifact["path"]]
            artifacts.append(observation_artifact)
        return self.apply(mutation, artifacts=artifacts)

    def worker_pass(self, goal_id: str = "g1") -> dict[str, str]:
        self.ensure_controller_goal(
            self.definitions[goal_id]["milestone_id"]
        )
        if "worker-1" not in self.state()["thread_registry"]:
            self.register_control_result(
                "THREAD",
                self.next_id("worker-thread-create"),
                "controller-1",
                {"role_kind": "WORKER"},
                {
                    "thread_id": "worker-1",
                    "role_kind": "WORKER",
                    "worktree_path": ".",
                },
            )
        claim = self.acquire()
        dispatch_id = self.next_id("dispatch")
        identity = {
            "goal_id": goal_id,
            "goal_definition_digest": self.definitions[goal_id]["payload_template_digest"],
        }
        prepared, payload = self.prepare_outbox(
            claim,
            "DISPATCH",
            dispatch_id,
            identity,
            target_id="worker-1",
        )
        if not prepared["ok"]:
            raise AssertionError(prepared)
        sent = self.mark_sent(
            claim, "DISPATCH", dispatch_id, payload, target_id="worker-1"
        )
        if not sent["ok"]:
            raise AssertionError(sent)
        artifact = digest(f"artifact:{dispatch_id}")
        report_result = {
            "status": "PASS",
            "artifact_digest": artifact,
        }
        report_content = self.formal_report_content(
            "DISPATCH", dispatch_id, report_result
        )
        report = digest(report_content)
        acked = self.ack_outbox(
            claim,
            "DISPATCH",
            dispatch_id,
            payload,
            target_id="worker-1",
            result={
                **report_result,
                "report_digest": report,
            },
            report_content=report_content,
        )
        if not acked["ok"]:
            raise AssertionError(acked)
        return {
            "goal_id": goal_id,
            "dispatch_id": dispatch_id,
            "artifact_digest": artifact,
            "report_digest": report,
        }

    def review(
        self,
        kind: str,
        decision: str,
        worker: dict[str, str],
        *,
        code_review_id: str | None = None,
        roadmap_audit_id: str | None = None,
        claim: dict[str, Any] | None = None,
        roadmap_plan: dict[str, Any] | None = None,
        within_authorized_envelope: bool = True,
        record_freshness: bool = True,
    ) -> str:
        if "reviewer-1" not in self.state()["thread_registry"]:
            self.register_control_result(
                "THREAD",
                self.next_id("reviewer-thread-create"),
                "controller-1",
                {"role_kind": "REVIEWER"},
                {
                    "thread_id": "reviewer-1",
                    "role_kind": "REVIEWER",
                    "worktree_path": ".",
                },
            )
        if record_freshness:
            freshness_delta = context_identity_delta(
                worker_report_digest=worker["report_digest"],
                artifact_digest=worker["artifact_digest"],
                diff_digest=digest(
                    f"auto-review-diff:{kind}:{worker['dispatch_id']}"
                ),
            )
            freshness = self.apply(
                {
                    "type": "RECORD_CONTEXT_FRESHNESS",
                    "checkpoint_id": self.next_id(f"{kind.lower()}-freshness"),
                    "checkpoint": kind,
                    "goal_id": worker["goal_id"],
                    "dispatch_id": worker["dispatch_id"],
                    "artifact_digest": worker["artifact_digest"],
                    "observed_identity_delta": freshness_delta,
                    "observed_identity_digest": json_digest(freshness_delta),
                    "classification": "FRESH",
                    "classification_source": "DETERMINISTIC_IDENTITY",
                }
            )
            if not freshness["ok"]:
                raise AssertionError(freshness)
        claim = claim or self.acquire(owner_kind="HEARTBEAT")
        dispatch_id = self.next_id(f"{kind.lower()}-dispatch")
        review_id = self.next_id(f"{kind.lower()}-review")
        identity: dict[str, Any] = {
            "review_kind": kind,
            "goal_id": worker["goal_id"],
            "worker_dispatch_id": worker["dispatch_id"],
            "worker_report_digest": worker["report_digest"],
            "artifact_digest": worker["artifact_digest"],
        }
        if code_review_id is not None:
            identity["code_review_id"] = code_review_id
        if roadmap_audit_id is not None:
            identity["roadmap_audit_id"] = roadmap_audit_id
        prepared, payload = self.prepare_outbox(
            claim,
            "ASSURANCE",
            dispatch_id,
            identity,
            target_id="reviewer-1",
        )
        if not prepared["ok"]:
            raise AssertionError(prepared)
        if not self.mark_sent(
            claim, "ASSURANCE", dispatch_id, payload, target_id="reviewer-1"
        )["ok"]:
            raise AssertionError("review send failed")
        ack_result = {
            "status": decision,
            "artifact_digest": worker["artifact_digest"],
        }
        extra_fields: dict[str, Any] = {}
        if kind == "ROADMAP_AUDIT":
            extra_fields["estimate_revision"] = {
                "min_minutes": 1,
                "typical_minutes": 2,
                "max_minutes": 5,
                "confidence": "MEDIUM",
                "assumptions": ["No new blocker appears"],
                "excludes": "external waiting time",
            }
        if roadmap_plan is not None:
            proposal = {
                "proposal_id": roadmap_plan["proposal_id"],
                "roadmap_audit_dispatch_id": dispatch_id,
                "base_roadmap_version": self.state()["roadmap_version"],
                "operations": copy.deepcopy(roadmap_plan["operations"]),
                "milestones_digest": json_digest(roadmap_plan["milestones"]),
                "goal_queue_digest": json_digest(roadmap_plan["goal_queue"]),
                "goal_definition_registry_digest": json_digest(
                    roadmap_plan["goal_definition_registry"]
                ),
                "authorization_envelope_digest": json_digest(
                    roadmap_plan["authorization_envelope"]
                ),
                "estimate_digest": (
                    json_digest(roadmap_plan["estimate"])
                    if "estimate" in roadmap_plan
                    else None
                ),
                "next_goal_id": roadmap_plan["next_goal_id"],
                "reason_code": roadmap_plan["reason_code"],
                "within_authorized_envelope": within_authorized_envelope,
            }
            extra_fields.update({
                "roadmap_proposal": proposal,
                "roadmap_proposal_digest": json_digest(proposal),
            })
        review_content = self.formal_report_content(
            "ASSURANCE",
            dispatch_id,
            ack_result,
            extra_fields=extra_fields,
        )
        review_digest = digest(review_content)
        if not self.ack_outbox(
            claim,
            "ASSURANCE",
            dispatch_id,
            payload,
            target_id="reviewer-1",
            result={**ack_result, "report_digest": review_digest},
            report_content=review_content,
        )["ok"]:
            raise AssertionError("review outbox ACK failed")
        response = self.apply(
            {
                "type": "RECORD_REVIEW",
                "lease_claim": claim,
                "observed_at": T1,
                "review_id": review_id,
                "review_kind": kind,
                "review_dispatch_id": dispatch_id,
                "goal_id": worker["goal_id"],
                "worker_dispatch_id": worker["dispatch_id"],
                "worker_report_digest": worker["report_digest"],
                "reviewer_thread_id": "reviewer-1",
                "roadmap_version": self.state()["roadmap_version"],
                "artifact_digest": worker["artifact_digest"],
                "report_digest": review_digest,
                "decision": decision,
                "review_evidence_paths": [
                    f".codex-loop/reports/{dispatch_id}-ack.json"
                ],
            },
        )
        if not response["ok"]:
            raise AssertionError(response)
        return review_id

    def bind_roadmap_revision(
        self,
        mutation: dict[str, Any],
        roadmap_audit_id: str,
    ) -> dict[str, Any]:
        audit = self.state()["assurance_ledger"][roadmap_audit_id]
        proposal = audit.get("roadmap_proposal")
        proposal_digest = audit.get("roadmap_proposal_digest")
        if not isinstance(proposal, dict) or not isinstance(proposal_digest, str):
            raise AssertionError("roadmap audit proposal is missing")
        mutation.update(
            {
                "roadmap_audit_report_digest": audit["report_digest"],
                "roadmap_proposal": copy.deepcopy(proposal),
                "roadmap_proposal_digest": proposal_digest,
            }
        )
        return mutation

    def local_pass(
        self,
        worker: dict[str, str],
        code_review_id: str,
        *,
        claim: dict[str, Any] | None = None,
    ) -> str:
        if "local-verifier-1" not in self.state()["thread_registry"]:
            if claim is not None:
                released = self.apply(
                    {
                        "type": "RELEASE_LEASE",
                        "lease_claim": claim,
                        "observed_at": T1,
                        "reason_code": "CREATE_LOCAL_VERIFIER",
                    }
                )
                if not released["ok"]:
                    raise AssertionError(released)
                claim = None
            self.register_control_result(
                "THREAD",
                self.next_id("local-verifier-thread-create"),
                "controller-1",
                {"role_kind": "LOCAL_VERIFIER"},
                {
                    "thread_id": "local-verifier-1",
                    "role_kind": "LOCAL_VERIFIER",
                    "worktree_path": ".",
                },
            )
        claim = claim or self.acquire()
        dispatch_id = self.next_id("local-dispatch")
        identity = {
            "goal_id": worker["goal_id"],
            "worker_dispatch_id": worker["dispatch_id"],
            "artifact_digest": worker["artifact_digest"],
            "verification_id": self.next_id("verification"),
            "code_review_id": code_review_id,
        }
        prepared, payload = self.prepare_outbox(
            claim,
            "LOCAL",
            dispatch_id,
            identity,
            target_id="local-verifier-1",
        )
        if not prepared["ok"]:
            raise AssertionError(prepared)
        self.mark_sent(
            claim, "LOCAL", dispatch_id, payload, target_id="local-verifier-1"
        )
        local_result = {
            "status": "PASS",
            "artifact_digest": worker["artifact_digest"],
        }
        local_content = self.formal_report_content(
            "LOCAL", dispatch_id, local_result
        )
        response = self.ack_outbox(
            claim,
            "LOCAL",
            dispatch_id,
            payload,
            target_id="local-verifier-1",
            result={
                **local_result,
                "report_digest": digest(local_content),
            },
            report_content=local_content,
        )
        if not response["ok"]:
            raise AssertionError(response)
        return dispatch_id

    def ensure_controller_goal(self, milestone_id: str | None = None) -> dict[str, Any]:
        milestone_id = milestone_id or self.state()["active_milestone_id"]
        if milestone_id is None:
            raise AssertionError("an active milestone is required")
        current = self.state()["controller_goal"]
        if (
            isinstance(current, dict)
            and current["milestone_id"] == milestone_id
            and current["status"]
            in {"ACTIVE", "EMULATED_SINGLE_ACTIVE_MILESTONE"}
        ):
            return current
        if isinstance(current, dict) and current["status"] != "COMPLETE":
            raise AssertionError(f"controller Goal is not transition-ready: {current}")
        native_goal_id = f"native-goal-{milestone_id}"
        self.register_control_result(
            "GOAL",
            self.next_id(f"goal-{milestone_id}-create"),
            "controller-1",
            {"action": "CREATE", "milestone_id": milestone_id},
            {"goal_id": native_goal_id, "status": "ACTIVE"},
        )
        created = self.state()["controller_goal"]
        assert isinstance(created, dict)
        return created

    def complete_controller_goal(self) -> dict[str, Any]:
        current = self.state()["controller_goal"]
        if not isinstance(current, dict):
            raise AssertionError("controller Goal is missing")
        self.register_control_result(
            "GOAL",
            self.next_id(f"goal-{current['milestone_id']}-complete"),
            "controller-1",
            {
                "action": "UPDATE",
                "goal_id": current["goal_id"],
                "milestone_id": current["milestone_id"],
                "objective_digest": current["objective_digest"],
                "marker": current["marker"],
                "target_status": "COMPLETE",
            },
            {"goal_id": current["goal_id"], "status": "COMPLETE"},
        )
        completed = self.state()["controller_goal"]
        assert isinstance(completed, dict)
        return completed

    def register_control_result(
        self,
        kind: str,
        outbox_id: str,
        target_id: str,
        identity: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        if kind == "THREAD":
            formal_role_kind = identity.get(
                "formal_role_kind", identity.get("role_kind", "WORKER")
            )
            bootstrap_role_kind = identity.get(
                "bootstrap_role_kind",
                {
                    "WORKER": "implementation",
                    "REVIEWER": "code_reviewer",
                    "LOCAL_VERIFIER": "local_verifier",
                }[formal_role_kind],
            )
            result = {
                "thread_id": result["thread_id"],
                "project_id": "test-project",
                "task_kind": "PROJECT_TASK",
                "bootstrap_role_kind": bootstrap_role_kind,
                "formal_role_kind": formal_role_kind,
                "bootstrap_prompt_digest": digest(f"bootstrap:{bootstrap_role_kind}"),
                "environment_kind": identity.get("environment_kind", "LOCAL"),
                "worktree_path": result["worktree_path"],
            }
        elif kind == "AUTOMATION":
            result = {
                "automation_name": "test-loop-heartbeat",
                "kind": "HEARTBEAT",
                "target_thread_id": "controller-1",
                "rrule": "FREQ=MINUTELY;INTERVAL=10",
                "prompt_digest": digest("heartbeat-prompt"),
                "prompt_normalization": "LF_NORMALIZED_NO_TRAILING_NEWLINE",
                "automation_id": result["automation_id"],
                "status": result["status"],
            }
        elif kind == "GOAL":
            action = identity.get("action", "CREATE")
            milestone_id = identity.get(
                "milestone_id", self.state()["active_milestone_id"] or "m1"
            )
            objective_digest = identity.get(
                "objective_digest", digest(f"goal-objective:{milestone_id}")
            )
            marker = identity.get(
                "marker",
                "[CODEX_LOOP_MILESTONE "
                f"loop_id=loop-1 "
                f"pack_sha256={controller_pack_artifact()['digest'].removeprefix('sha256:')} "
                f"milestone_id={milestone_id} "
                f"objective_sha256={objective_digest.removeprefix('sha256:')}]",
            )
            result = {
                "action": action,
                "loop_id": "loop-1",
                "pack_digest": controller_pack_artifact()["digest"],
                "milestone_id": milestone_id,
                "objective_digest": objective_digest,
                "marker": marker,
                **(
                    {"target_status": identity.get("target_status", "COMPLETE")}
                    if action == "UPDATE"
                    else {}
                ),
                "goal_id": result["goal_id"],
                "status": result["status"],
            }
        claim = self.acquire()
        prepared, payload = self.prepare_outbox(
            claim,
            kind,
            outbox_id,
            identity,
            target_id=target_id,
        )
        if not prepared["ok"]:
            raise AssertionError(prepared)
        sent = self.mark_sent(claim, kind, outbox_id, payload, target_id=target_id)
        if not sent["ok"]:
            raise AssertionError(sent)
        acked = self.ack_outbox(
            claim,
            kind,
            outbox_id,
            payload,
            target_id=target_id,
            result=result,
        )
        if not acked["ok"]:
            raise AssertionError(acked)


def controller_goal_resume_request(
    harness: Harness,
    claim: dict[str, Any],
    *,
    resume_id: str = "controller-goal-resume-1",
    pre_observed_at: str = T0,
    authorized_at: str = T1,
    post_observed_at: str = T1,
    mutation_observed_at: str = T1,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    current = harness.state()["controller_goal"]
    assert isinstance(current, dict)
    objective = f"goal-objective:{current['milestone_id']}\n{current['marker']}"
    created_at = 1767225600
    updated_at = 1767225600

    def observation(observed_at: str) -> dict[str, Any]:
        return {
            "observation_kind": "CODEX_GOAL_READBACK",
            "threadId": current["goal_id"],
            "objective": objective,
            "status": "blocked",
            "createdAt": created_at,
            "updatedAt": updated_at,
            "observed_at": observed_at,
        }

    authorization = {
        "authorization_kind": "SAME_GOAL_RESUME",
        "source_actor": "USER",
        "source_message_id": f"resume-message-{resume_id}",
        "authorized_at": authorized_at,
        **{
            key: current[key]
            for key in (
                "goal_id",
                "loop_id",
                "pack_digest",
                "milestone_id",
                "objective_digest",
                "marker",
            )
        },
    }
    values = (
        ("pre-blocked", observation(pre_observed_at)),
        ("resume-authorization", authorization),
        ("post-resume", observation(post_observed_at)),
    )
    artifacts = [
        read_evidence_artifact(
            f"{resume_id}-{label}",
            json.dumps(value, sort_keys=True, separators=(",", ":")),
        )
        for label, value in values
    ]
    mutation = {
        "type": "RECORD_CONTROLLER_GOAL_RESUME",
        "lease_claim": claim,
        "observed_at": mutation_observed_at,
        "resume_id": resume_id,
        **{
            key: current[key]
            for key in (
                "goal_id",
                "loop_id",
                "pack_digest",
                "milestone_id",
                "objective_digest",
                "marker",
            )
        },
        "pre_blocked_observation_path": artifacts[0]["path"],
        "pre_blocked_observation_digest": artifacts[0]["digest"],
        "resume_authorization_path": artifacts[1]["path"],
        "resume_authorization_digest": artifacts[1]["digest"],
        "post_resume_observation_path": artifacts[2]["path"],
        "post_resume_observation_digest": artifacts[2]["digest"],
    }
    return mutation, artifacts


def persisted_snapshot(root: Path) -> dict[str, bytes]:
    control = root / ".codex-loop"
    if not control.exists():
        return {}
    snapshot: dict[str, bytes] = {}
    for path in sorted(control.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            snapshot[relative] = b"<SYMLINK>" + os.readlink(path).encode("utf-8")
        elif path.is_dir():
            snapshot[relative + "/"] = b"<DIR>"
        elif path.is_file():
            snapshot[relative] = path.read_bytes()
    return snapshot


def runtime_surface_fingerprint(root: Path) -> dict[str, Any]:
    control = root / ".codex-loop"
    fingerprint: dict[str, Any] = {}
    for name in (
        "LOOP_STATE.md",
        "LOOP_EVENTS.jsonl",
        "GOALS.md",
        "progress-dashboard.html",
    ):
        path = control / name
        fingerprint[name] = path.read_bytes() if path.exists() else None
    for directory in ("transactions", "sources", "reports"):
        base = control / directory
        entries: list[tuple[str, int, int, str]] = []
        if base.exists():
            for path in sorted(base.rglob("*")):
                stat = path.lstat()
                kind = "symlink" if path.is_symlink() else "dir" if path.is_dir() else "file"
                entries.append(
                    (
                        str(path.relative_to(control)),
                        stat.st_size,
                        stat.st_mtime_ns,
                        kind,
                    )
                )
        fingerprint[directory] = entries
    return fingerprint


def event_lines(root: Path) -> list[dict[str, Any]]:
    path = root / ".codex-loop" / "LOOP_EVENTS.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class AdaptiveStateRuntimeTestCase(unittest.TestCase):
    def _prepare_sent_worker(
        self, root: Path, dispatch_id: str = "dispatch-report-stage"
    ) -> tuple[Harness, dict[str, Any], str, str]:
        harness = Harness(root)
        initialized, _ = harness.initialize()
        self.assertTrue(initialized["ok"], initialized)
        harness.ensure_controller_goal()
        harness.register_control_result(
            "THREAD",
            f"{dispatch_id}-worker-create",
            "controller-1",
            {"role_kind": "WORKER"},
            {
                "thread_id": "worker-1",
                "role_kind": "WORKER",
                "worktree_path": ".",
            },
        )
        claim = harness.acquire()
        prepared, payload = harness.prepare_outbox(
            claim,
            "DISPATCH",
            dispatch_id,
            {
                "goal_id": "g1",
                "goal_definition_digest": harness.definitions["g1"][
                    "payload_template_digest"
                ],
            },
            target_id="worker-1",
        )
        self.assertTrue(prepared["ok"], prepared)
        sent = harness.mark_sent(
            claim,
            "DISPATCH",
            dispatch_id,
            payload,
            target_id="worker-1",
        )
        self.assertTrue(sent["ok"], sent)
        return harness, claim, dispatch_id, payload

    def _prepare_sent_code_review(
        self, root: Path
    ) -> tuple[Harness, dict[str, str], dict[str, Any], str, str]:
        harness = Harness(root)
        harness.initialize()
        worker = harness.worker_pass()
        harness.register_control_result(
            "THREAD",
            "reviewer-thread-report-contract",
            "controller-1",
            {"role_kind": "REVIEWER"},
            {
                "thread_id": "reviewer-1",
                "role_kind": "REVIEWER",
                "worktree_path": ".",
            },
        )
        freshness_delta = context_identity_delta(
            worker_report_digest=worker["report_digest"],
            artifact_digest=worker["artifact_digest"],
            diff_digest=digest("review-report-contract-diff"),
        )
        freshness = harness.apply(
            {
                "type": "RECORD_CONTEXT_FRESHNESS",
                "checkpoint_id": "review-report-contract-freshness",
                "checkpoint": "CODE_REVIEW",
                "goal_id": worker["goal_id"],
                "dispatch_id": worker["dispatch_id"],
                "artifact_digest": worker["artifact_digest"],
                "observed_identity_delta": freshness_delta,
                "observed_identity_digest": json_digest(freshness_delta),
                "classification": "FRESH",
                "classification_source": "DETERMINISTIC_IDENTITY",
            }
        )
        self.assertTrue(freshness["ok"], freshness)
        claim = harness.acquire()
        review_dispatch_id = "review-report-contract-1"
        prepared, payload = harness.prepare_outbox(
            claim,
            "ASSURANCE",
            review_dispatch_id,
            {
                "review_kind": "CODE_REVIEW",
                "goal_id": worker["goal_id"],
                "worker_dispatch_id": worker["dispatch_id"],
                "worker_report_digest": worker["report_digest"],
                "artifact_digest": worker["artifact_digest"],
            },
            target_id="reviewer-1",
        )
        self.assertTrue(prepared["ok"], prepared)
        sent = harness.mark_sent(
            claim,
            "ASSURANCE",
            review_dispatch_id,
            payload,
            target_id="reviewer-1",
        )
        self.assertTrue(sent["ok"], sent)
        return harness, worker, claim, review_dispatch_id, payload

    def _ack_code_review_for_canonical_reuse(
        self, root: Path
    ) -> tuple[
        Harness,
        dict[str, str],
        dict[str, Any],
        str,
        str,
        str,
    ]:
        harness, worker, claim, review_dispatch_id, payload = (
            self._prepare_sent_code_review(root)
        )
        result = {
            "status": "REVIEW_PASS",
            "artifact_digest": worker["artifact_digest"],
        }
        report_content = harness.formal_report_content(
            "ASSURANCE", review_dispatch_id, result
        )
        report_digest = digest(report_content)
        acked = harness.ack_outbox(
            claim,
            "ASSURANCE",
            review_dispatch_id,
            payload,
            target_id="reviewer-1",
            result={**result, "report_digest": report_digest},
            report_content=report_content,
        )
        self.assertTrue(acked["ok"], acked)
        return (
            harness,
            worker,
            claim,
            review_dispatch_id,
            report_content,
            report_digest,
        )

    @staticmethod
    def _canonical_reuse_review_mutation(
        harness: Harness,
        worker: dict[str, str],
        claim: dict[str, Any],
        review_dispatch_id: str,
        report_digest: str,
    ) -> dict[str, Any]:
        return {
            "type": "RECORD_REVIEW",
            "lease_claim": claim,
            "observed_at": T1,
            "review_id": "canonical-reuse-review-1",
            "review_kind": "CODE_REVIEW",
            "review_dispatch_id": review_dispatch_id,
            "goal_id": worker["goal_id"],
            "worker_dispatch_id": worker["dispatch_id"],
            "worker_report_digest": worker["report_digest"],
            "reviewer_thread_id": "reviewer-1",
            "roadmap_version": harness.state()["roadmap_version"],
            "artifact_digest": worker["artifact_digest"],
            "report_digest": report_digest,
            "decision": "REVIEW_PASS",
            "review_evidence_paths": [
                f".codex-loop/reports/{review_dispatch_id}-ack.json"
            ],
        }
