#!/usr/bin/env python3
"""Validate the v4-only LoopSkill package with standard-library checks."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


REQUIRED_DIRS = (
    "scripts/loop_architect/v4_adapters",
    "scripts/loop_architect/v4_alpha",
    "scripts/loop_architect/v4_artifacts",
    "scripts/loop_architect/v4_entry",
    "scripts/loop_architect/v4_operability",
    "scripts/loop_architect/v4_persistence",
    "scripts/loop_architect/v4_policy",
)
RETIRED_PATHS = (
    "references/adaptive-state.schema.json",
    "scripts/adaptive_state_mcp.py",
    "scripts/adaptive_state_runtime.py",
    "scripts/configure_mcp.py",
    "scripts/loop_prompt_scaffold.py",
    "scripts/loopctl",
    "scripts/loopctl.py",
    "scripts/loop_architect/v4_compat",
)
FORBIDDEN_RUNTIME_LITERALS = (
    "ImportV3Snapshot",
    "V3SnapshotImported",
    "MIGRATION_",
    "[mcp_servers.",
    "adaptive_state_mcp",
    "configure_mcp",
    "codex-loop-state",
    "loop_architect.v4_compat",
    "State-Writer",
)


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


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


def protocol_path(skill_dir: Path) -> Path:
    installed = skill_dir / "protocol/v4/loopskill-v4.protocol.json"
    if installed.is_file():
        return installed
    repository = skill_dir.parent / "protocol/v4/loopskill-v4.protocol.json"
    if repository.is_file():
        return repository
    raise ValueError("missing typed protocol manifest")


def version_path(skill_dir: Path) -> Path:
    installed = skill_dir / "VERSION"
    if installed.is_file():
        return installed
    repository = skill_dir.parent / "VERSION"
    if repository.is_file():
        return repository
    raise ValueError("missing VERSION")


def validate(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    required_files = (
        "SKILL.md",
        "agents/openai.yaml",
        "scripts/loopskill4",
        "scripts/validate_skill.py",
        "scripts/verify_installation.py",
        "scripts/loop_architect/__init__.py",
    )
    for relative in required_files:
        if not (skill_dir / relative).is_file():
            errors.append(f"missing required file: {relative}")
    for relative in REQUIRED_DIRS:
        if not (skill_dir / relative).is_dir():
            errors.append(f"missing required directory: {relative}")
    for relative in RETIRED_PATHS:
        if (skill_dir / relative).exists():
            errors.append(f"retired v3 runtime surface present: {relative}")
    if errors:
        return errors

    try:
        fields = parse_frontmatter(skill_dir / "SKILL.md")
    except ValueError as exc:
        errors.append(str(exc))
        fields = {}
    if set(fields) != {"name", "description"}:
        errors.append("SKILL.md frontmatter must contain only name and description")
    if fields.get("name") != "loopskill4":
        errors.append("SKILL.md name must be loopskill4")
    if not fields.get("description"):
        errors.append("SKILL.md description is required")
    agent = (skill_dir / "agents/openai.yaml").read_text(encoding="utf-8")
    if "$loopskill4" not in agent or "$codex-loop-prompt-architect" in agent:
        errors.append("agent metadata must route only to $loopskill4")

    for script in sorted((skill_dir / "scripts").rglob("*.py")):
        try:
            compile(script.read_text(encoding="utf-8"), str(script), "exec")
        except SyntaxError as exc:
            errors.append(f"syntax compile failed for {script.relative_to(skill_dir)}: {exc}")
        relative = script.relative_to(skill_dir).as_posix()
        if relative not in {
            "scripts/validate_skill.py",
            "scripts/loop_architect/v4_entry/legacy_boundary.py",
        }:
            source = script.read_text(encoding="utf-8")
            for literal in FORBIDDEN_RUNTIME_LITERALS:
                if literal in source:
                    errors.append(f"retired runtime literal {literal!r} in {relative}")

    try:
        manifest = json.loads(protocol_path(skill_dir).read_text(encoding="utf-8"))
        generated_path = skill_dir / "scripts/loop_architect/v4_alpha/generated_protocol.py"
        generated = generated_path.read_text(encoding="utf-8")
        digest = hashlib.sha256(canonical(manifest)).hexdigest()
        if f"MANIFEST_SHA256 = '{digest}'" not in generated:
            errors.append("generated protocol digest drift")
        if "ImportV3Snapshot" in manifest.get("commands", {}):
            errors.append("legacy import command is forbidden")
        if "USER_UNSUPPORTED_LEGACY_VERSION" not in manifest.get("errors", []):
            errors.append("stable legacy-version error is missing")
        if any(str(code).startswith("MIGRATION_") for code in manifest.get("errors", [])):
            errors.append("legacy migration errors are forbidden")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"protocol validation failed: {exc}")
    try:
        if version_path(skill_dir).read_text(encoding="utf-8").strip() != "4.1.1":
            errors.append("VERSION must be 4.1.1")
    except (OSError, ValueError) as exc:
        errors.append(str(exc))

    smoke = subprocess.run(
        [sys.executable, str(skill_dir / "scripts/loopskill4"), "--help"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if smoke.returncode != 0:
        errors.append("loopskill4 --help smoke failed")
    return errors


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    skill_dir = Path(args[0]).resolve() if args else Path(__file__).resolve().parents[1]
    errors = validate(skill_dir)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("LoopSkill 4 package validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
