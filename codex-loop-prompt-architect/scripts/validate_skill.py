#!/usr/bin/env python3
"""Validate the local codex-loop-prompt-architect skill package."""

from __future__ import annotations

import json
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
        skill_dir / "scripts" / "loop_prompt_scaffold.py",
        skill_dir / "scripts" / "validate_skill.py",
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
    try:
        compile(scaffold.read_text(encoding="utf-8"), str(scaffold), "exec")
    except SyntaxError as exc:
        errors.append(f"scaffold syntax compile failed: {exc}")
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
