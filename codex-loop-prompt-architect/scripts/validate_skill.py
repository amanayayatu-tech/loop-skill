#!/usr/bin/env python3
"""Validate the local codex-loop-prompt-architect skill package."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def parse_frontmatter(skill_file: Path) -> dict[str, str]:
    lines = skill_file.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("SKILL.md must start with YAML frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError("SKILL.md frontmatter is not closed") from exc
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"invalid frontmatter line: {line}")
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def validate(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    skill_file = skill_dir / "SKILL.md"
    required_files = [
        skill_file,
        skill_dir / "agents" / "openai.yaml",
        skill_dir / "references" / "loop-contract.md",
        skill_dir / "references" / "loop-intake-gate.md",
        skill_dir / "references" / "adaptive-loop-contract.md",
        skill_dir / "references" / "adaptive-state.schema.json",
        skill_dir / "references" / "adaptive-mutation.schema.json",
        skill_dir / "references" / "install-manifest.schema.json",
        skill_dir / "references" / "app-canary-receipt.schema.json",
        skill_dir / "scripts" / "adaptive_state_runtime.py",
        skill_dir / "scripts" / "adaptive_state_mcp.py",
        skill_dir / "scripts" / "configure_mcp.py",
        skill_dir / "scripts" / "verify_installation.py",
        skill_dir / "scripts" / "validate_app_canary_receipt.py",
        skill_dir / "scripts" / "loop_prompt_scaffold.py",
        skill_dir / "scripts" / "validate_skill.py",
        skill_dir / "scripts" / "loop_architect" / "schema.py",
        skill_dir / "scripts" / "loop_architect" / "validation.py",
        skill_dir / "scripts" / "loop_architect" / "forecast.py",
        skill_dir / "scripts" / "loop_architect" / "protocol_model.py",
        skill_dir / "scripts" / "loop_architect" / "state_runtime.py",
        skill_dir / "scripts" / "loop_architect" / "standard_renderer.py",
        skill_dir / "scripts" / "loop_architect" / "adaptive_renderer.py",
    ]
    for path in required_files:
        if not path.is_file():
            errors.append(f"missing required file: {path.relative_to(skill_dir)}")
    if errors:
        return errors

    try:
        fields = parse_frontmatter(skill_file)
    except ValueError as exc:
        errors.append(str(exc))
        fields = {}
    if set(fields) != {"name", "description"}:
        errors.append("SKILL.md frontmatter must contain only name and description")
    if fields.get("name") != skill_dir.name:
        errors.append("frontmatter name must match the skill directory")
    if not fields.get("description"):
        errors.append("frontmatter description is required")
    if len(skill_file.read_text(encoding="utf-8").splitlines()) > 500:
        errors.append("SKILL.md must stay at or below 500 lines")

    openai_yaml = (skill_dir / "agents" / "openai.yaml").read_text(encoding="utf-8")
    if "$codex-loop-prompt-architect" not in openai_yaml:
        errors.append("agents/openai.yaml default_prompt must mention $codex-loop-prompt-architect")

    scaffold = skill_dir / "scripts" / "loop_prompt_scaffold.py"
    state_runtime = skill_dir / "scripts" / "adaptive_state_runtime.py"
    for script in sorted((skill_dir / "scripts").rglob("*.py")):
        try:
            compile(script.read_text(encoding="utf-8"), str(script), "exec")
        except SyntaxError as exc:
            errors.append(f"script syntax compile failed for {script.relative_to(skill_dir)}: {exc}")
    schema_result = subprocess.run(
        [sys.executable, str(scaffold), "--print-schema"],
        text=True,
        capture_output=True,
        check=False,
    )
    if schema_result.returncode:
        errors.append(f"--print-schema failed: {schema_result.stderr.strip()}")
    else:
        try:
            schema = json.loads(schema_result.stdout)
        except json.JSONDecodeError as exc:
            errors.append(f"--print-schema returned invalid JSON: {exc}")
        else:
            if schema.get("title") != "Codex Loop Prompt Scaffold Input":
                errors.append("unexpected scaffold schema title")

    try:
        import jsonschema
    except ImportError:
        errors.append("missing runtime dependency: jsonschema")
    else:
        for schema_name in (
            "adaptive-state.schema.json",
            "adaptive-mutation.schema.json",
            "install-manifest.schema.json",
            "app-canary-receipt.schema.json",
        ):
            schema_path = skill_dir / "references" / schema_name
            try:
                runtime_schema = json.loads(schema_path.read_text(encoding="utf-8"))
                jsonschema.Draft202012Validator.check_schema(runtime_schema)
            except (OSError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
                errors.append(f"invalid Adaptive runtime schema {schema_name}: {exc}")

    with tempfile.TemporaryDirectory() as runtime_root:
        runtime_result = subprocess.run(
            [sys.executable, str(state_runtime), "--root", runtime_root, "--recover"],
            input="",
            text=True,
            capture_output=True,
            check=False,
        )
        try:
            runtime_response = json.loads(runtime_result.stdout)
        except json.JSONDecodeError as exc:
            errors.append(f"Adaptive state runtime returned invalid JSON: {exc}")
        else:
            if (
                runtime_result.returncode != 0
                or runtime_response.get("status") != "RECOVERY_COMPLETE"
                or runtime_response.get("external_action_count") != 0
                or runtime_response.get("external_actions") != []
            ):
                errors.append("Adaptive state runtime recovery smoke failed")

    smoke_payload = {
        "objective": "Validate one scoped local change",
        "repo": "/tmp/codex-loop-validator-repo",
        "repo_mode": "existing_git",
        "branch": "codex/validator-smoke",
        "base_branch": "main",
        "target_branch": "codex/validator-smoke",
        "workers": [
            {
                "role": "implementation",
                "scope": "validator smoke",
                "permission": "workspace_write",
                "allowed": ["src/**"],
            }
        ],
        "permissions": {"implementation": "workspace_write"},
        "allowed": ["src/**"],
        "forbidden": ["secrets", "deploy"],
        "validation": ["printf ok"],
        "acceptance_criteria": ["The generated pack is structurally complete"],
        "goals": [
            {
                "goal_id": "SMOKE-G1",
                "worker_role": "implementation",
                "objective": "Generate a smoke Controller Pack",
                "success_criteria": ["Pack generation succeeds"],
                "phase_permissions": {"branch_create": True},
            }
        ],
        "evidence": "local checks",
        "claim": "generator smoke only",
        "state": ".codex-loop/LOOP_STATE.md",
        "source_artifacts": ["SELF_CONTAINED"],
    }
    with tempfile.TemporaryDirectory() as directory:
        input_path = Path(directory) / "smoke-input.json"
        input_path.write_text(json.dumps(smoke_payload), encoding="utf-8")
        check_result = subprocess.run(
            [sys.executable, str(scaffold), "--input", str(input_path), "--check-only"],
            text=True,
            capture_output=True,
            check=False,
        )
        if check_result.returncode:
            errors.append(f"scaffold semantic smoke failed: {check_result.stdout}{check_result.stderr}")
        full_result = subprocess.run(
            [sys.executable, str(scaffold), "--input", str(input_path), "--mode", "full"],
            text=True,
            capture_output=True,
            check=False,
        )
        required_markers = (
            "# Codex Loop Controller Pack",
            "HEARTBEAT_PROMPT_BEGIN",
            "THREAD_CREATE_PREPARED",
            "DISPATCH_PREPARED",
            "## Loop Diagnosis",
            "Loop Integrity Score: 12/12",
        )
        if full_result.returncode or any(marker not in full_result.stdout for marker in required_markers):
            errors.append("scaffold Full Mode smoke did not produce all required protocol markers")

        adaptive_payload = dict(smoke_payload)
        adaptive_payload.update(
            {
                "coordination_mode": "adaptive",
                "adaptive_reason": "Validator exercises milestone adaptation",
                "workers": [
                    {
                        "role": "implementation",
                        "role_kind": "implementation",
                        "scope": "validator smoke",
                        "permission": "workspace_write",
                        "allowed": ["src/**"],
                    }
                ],
                "milestones": [
                    {
                        "milestone_id": "M1",
                        "outcome": "Generate the adaptive smoke pack",
                        "scope": ["src/**"],
                        "decisions": [],
                        "blockers": [],
                        "required_evidence": ["validator markers"],
                        "status": "ACTIVE",
                        "depends_on": [],
                        "references": ["SMOKE-G1"],
                    }
                ],
                "goals": [
                    {
                        "goal_id": "SMOKE-G1",
                        "milestone_id": "M1",
                        "worker_role": "implementation",
                        "objective": "Generate an adaptive smoke Controller Pack",
                        "success_criteria": ["Adaptive Pack generation succeeds"],
                        "phase_permissions": {"branch_create": True},
                    }
                ],
                "delegation_policy": "auto_read_only",
                "max_read_only_subagents": 2,
                "max_read_only_subagent_runs": 4,
                "subagent_retry_limit": 1,
                "subagent_input_policy": "workspace paths and redacted logs only; no secrets or private credentials",
                "subagent_max_depth": 1,
                "local_verification_policy": "required",
                "dashboard_policy": "auto",
                "dashboard_threshold_hours": 12,
                "max_child_threads": 4,
            }
        )
        adaptive_path = Path(directory) / "adaptive-input.json"
        adaptive_path.write_text(json.dumps(adaptive_payload), encoding="utf-8")
        adaptive_result = subprocess.run(
            [sys.executable, str(scaffold), "--input", str(adaptive_path)],
            text=True,
            capture_output=True,
            check=False,
        )
        adaptive_markers = (
            "Adaptive Coordination Mode",
            "GOALS.md",
            "controller_lease",
            "goal_definition_registry",
            "MILESTONE_REGISTRY_JSON_BEGIN",
            "AUTHORIZATION_ENVELOPE_JSON_BEGIN",
            "GOAL_DEFINITION_REGISTRY_JSON_BEGIN",
            "PREPARE_OUTBOX(kind=GOAL, action=CREATE)",
            '"dispatch_lease_claim"',
            "assurance_dispatch_outbox",
            "source Worker dispatch id, source Worker report digest",
            "ROADMAP_AUDIT",
            "review_kind=FINAL_AUDIT",
            "FINALIZE_LOOP",
            "ACK_FINALIZATION",
            "FINALIZATION_ACKED",
            "reusing only an epoch or lease id is invalid",
            "EMULATED_SINGLE_ACTIVE_MILESTONE",
            "Worker Prompt - local-verifier",
            "mutation.type is INITIALIZE",
            "controller_bootstrap_prompt_digest",
            "ROUTING_BUDGET_EXHAUSTED",
            "Every routing turn starts with exactly one ACQUIRE_LEASE mutation",
            "RENEW_LEASE",
            "TAKEOVER_LEASE",
            "MIGRATE_CONTROLLER_PACK",
            "Native Controller Goal Generation Recovery: DEFERRED/UNAVAILABLE",
            "NATIVE_GOAL_GENERATION_RECOVERY_UNAVAILABLE",
            "keep the exact heartbeat PAUSED",
            "do not create a replacement Goal, Controller, thread, session, or heartbeat",
            "PREPARE_CONTROLLER_PACK_MIGRATION",
            "ROLLBACK_CONTROLLER_PACK_MIGRATION",
            "controller_pack_identity.path",
            "UNKNOWN_NOT_OBSERVED",
            "controller_pack_digest",
            "controller_turn_id",
            "STAGE_EXTERNAL_RECEIPT",
            "execution_started=false",
            "ACTIVE_SAME_OWNER",
            "PREPARE_OUTBOX(kind=GOAL, action=CREATE)",
            "direct-ACK the exact PREPARED GOAL outbox",
            "generic DELEGATION outbox",
            "Worker, assurance, or Local Verifier outbox",
            "mismatched reuse is rejected without advancing state",
            "Worker FAIL/BLOCKED",
            "fresh lease for every",
            "Only the Controller may invoke an explicitly authorized read-only sidecar",
            "Never call any subagent/collaboration spawn tool",
            "ROLE_KIND is the exact literal",
            "LOOP_ID|ROLE_KIND|PACK_SHA256",
            "ROLE_PROMPT_BEGIN: state_writer",
            "ROLE_PROMPT_END: state_writer",
            "A file path, heading, line range, excerpt, summary, or loader instruction is not the prompt",
            "sha256:<64 hex> over those exact bytes",
            "complete Goal definition registry and execution ledger",
            "safe in-repo scope with no `..` or `.codex-loop`",
            "Adaptive Runtime Handoff Marker: ADAPTIVE_RUNTIME_HANDOFF_V1",
            "scripts/adaptive_state_runtime.py",
            "route_state_mutation",
            "omit controller_turn_id",
            "external_call_authorization",
            "EXTERNAL_CALL_OUTCOME_UNKNOWN",
            "report_text",
            "provided_report_digest",
            "provided_digest/computed_digest",
            "canonical_pack_digest/loaded_pack_digest",
            "runtime_codec",
            "MATERIALIZE_DISPATCH",
            "VERIFY_DISPATCH",
            "RUNTIME_CODEC_TOOL_UNAVAILABLE",
            "Runtime transport contract",
            "Projection-first observation contract",
            "canonical `LOOP_STATE.md` mtime/size",
            "projected `STATUS.md` state version",
            "read_thread(threadId=..., turnLimit=1, includeOutputs=false)",
            "one in-flight read per target",
            "30/60/120-second backoff",
            "Validation identity dedupe",
            "bounded typed channel",
            "EOF-before-frame",
            "TERM -> bounded wait -> KILL -> waitpid",
            "lost stdout never authorizes an external retry",
            "PAYLOAD_MATERIALIZATION_SPEC",
            "STOP_LOOP",
            "references/adaptive-mutation.schema.json",
            "Execute only STATE_MUTATION",
            "Do not manually create, patch, append, or rewrite",
            "Adaptive Heartbeat Prompt Identity: ADAPTIVE_HEARTBEAT_PROMPT_V1",
            "LF_NORMALIZED_NO_TRAILING_NEWLINE",
            "excluding the LF adjacent to each delimiter",
        )
        if adaptive_result.returncode or any(marker not in adaptive_result.stdout for marker in adaptive_markers):
            errors.append("scaffold Adaptive Mode smoke did not produce all required protocol markers")
        try:
            from loop_architect.protocol_model import (
                forbidden_rendered_tokens,
                validate_protocol_sources,
            )

            errors.extend(
                f"Adaptive protocol source drift: {finding}"
                for finding in validate_protocol_sources()
            )
            forbidden = forbidden_rendered_tokens(adaptive_result.stdout)
            if forbidden:
                errors.append(
                    "scaffold Adaptive Mode smoke emitted non-runtime protocol tokens: "
                    + ", ".join(forbidden)
                )
        except (ImportError, OSError, ValueError, KeyError) as exc:
            errors.append(f"Adaptive protocol catalog validation failed: {exc}")
        if re.search(
            r"(?<![A-Za-z0-9_])/(?:goal|review|state_update)(?![A-Za-z0-9_])",
            adaptive_result.stdout,
        ):
            errors.append("scaffold Adaptive Mode smoke retained a reserved slash envelope")
        for removed_mutation in ("ROUTING_TURN_STARTED", "HEARTBEAT_WAKE"):
            if removed_mutation in adaptive_result.stdout:
                errors.append(
                    f"scaffold Adaptive Mode smoke retained removed mutation {removed_mutation}"
                )
    return errors


def main() -> int:
    skill_dir = Path(__file__).resolve().parents[1]
    errors = validate(skill_dir)
    if errors:
        print("Skill validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Skill validation passed: {skill_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
