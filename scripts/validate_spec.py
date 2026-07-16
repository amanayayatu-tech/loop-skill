#!/usr/bin/env python3
"""Structural validator for docs/spec/invariants.yaml."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml


LEVELS = {"CORE_INVARIANT", "PUBLIC_CONTRACT", "PROVISIONAL", "IMPLEMENTATION_NOTE", "DEFERRED"}
STATUSES = {"ACTIVE", "DEFERRED", "SUPERSEDED"}
ADR_STATUSES = {"Accepted", "Superseded", "Provisional", "Deferred"}
ADR_REQUIRED_SECTIONS = {"Context", "Decision", "Consequences", "Evolution"}
REQUIRED_FIELDS = {
    "id", "title", "level", "status", "scope", "rationale",
    "normative_statement", "non_goals", "allowed_evolution",
    "authoritative_sources", "implementation_surfaces", "schema_surfaces",
    "test_surfaces", "evidence_surfaces", "adr", "introduced_version",
}
PATH_FIELDS = {
    "authoritative_sources", "implementation_surfaces", "schema_surfaces",
    "test_surfaces", "evidence_surfaces", "adr",
}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _repo_path(root: Path, reference: str) -> Path:
    return root / reference.split("#", 1)[0]


def validate_adr(root: Path, relative: str) -> list[str]:
    errors: list[str] = []
    path = root / relative
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"adr:unreadable:{relative}:{exc}"]
    filename_match = re.fullmatch(r"(\d{4})-[a-z0-9-]+\.md", path.name)
    title_match = re.search(r"^# ADR (\d{4}): \S.+$", content, re.MULTILINE)
    if filename_match is None:
        errors.append(f"adr:invalid_filename:{relative}")
    if title_match is None:
        errors.append(f"adr:invalid_title:{relative}")
    elif filename_match is not None and title_match.group(1) != filename_match.group(1):
        errors.append(f"adr:number_mismatch:{relative}")
    status_match = re.search(r"^- Status: (\S+)$", content, re.MULTILINE)
    if status_match is None or status_match.group(1) not in ADR_STATUSES:
        errors.append(f"adr:invalid_status:{relative}")
        status = None
    else:
        status = status_match.group(1)
    headings = set(re.findall(r"^## (.+)$", content, re.MULTILINE))
    for section in sorted(ADR_REQUIRED_SECTIONS - headings):
        errors.append(f"adr:missing_section:{relative}:{section}")
    replacement_match = re.search(
        r"^- Superseded by: (docs/adr/[a-z0-9-]+\.md)$",
        content,
        re.MULTILINE,
    )
    if status == "Superseded":
        if replacement_match is None:
            errors.append(f"adr:superseded_without_replacement:{relative}")
        else:
            replacement = replacement_match.group(1)
            if replacement == relative:
                errors.append(f"adr:self_replacement:{relative}")
            elif not (root / replacement).is_file():
                errors.append(f"adr:missing_replacement:{relative}:{replacement}")
    elif replacement_match is not None:
        errors.append(f"adr:replacement_requires_superseded_status:{relative}")
    return errors


def validate(root: Path, index_path: Path | None = None) -> list[str]:
    root = root.resolve()
    index_path = index_path or root / "docs/spec/invariants.yaml"
    errors: list[str] = []
    try:
        document = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [f"index:unreadable:{exc}"]
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        errors.append("index:schema_version_must_be_1")
    entries = document.get("invariants") if isinstance(document, dict) else None
    if not isinstance(entries, list) or not entries:
        return errors + ["index:invariants_must_be_nonempty_list"]

    seen_ids: set[str] = set()
    referenced_adrs: set[str] = set()
    dependencies: dict[str, list[str]] = {}
    for position, entry in enumerate(entries, 1):
        prefix = f"invariant:{position}"
        if not isinstance(entry, dict):
            errors.append(f"{prefix}:must_be_mapping")
            continue
        missing = sorted(REQUIRED_FIELDS - set(entry))
        if missing:
            errors.append(f"{prefix}:missing:{','.join(missing)}")
        invariant_id = entry.get("id")
        if not isinstance(invariant_id, str) or not invariant_id:
            errors.append(f"{prefix}:invalid_id")
            continue
        prefix = invariant_id
        if invariant_id in seen_ids:
            errors.append(f"{prefix}:duplicate_id")
        seen_ids.add(invariant_id)
        if entry.get("level") not in LEVELS:
            errors.append(f"{prefix}:invalid_level")
        if entry.get("status") not in STATUSES:
            errors.append(f"{prefix}:invalid_status")
        for field in ("title", "rationale", "normative_statement", "introduced_version"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                errors.append(f"{prefix}:{field}_must_be_nonempty_string")
        for field in ("scope", "non_goals", "allowed_evolution"):
            if not _as_list(entry.get(field)):
                errors.append(f"{prefix}:{field}_must_be_nonempty_list")
        for field in PATH_FIELDS:
            values = entry.get(field)
            if not isinstance(values, list):
                errors.append(f"{prefix}:{field}_must_be_list")
                continue
            seen_refs: set[str] = set()
            for reference in values:
                if not isinstance(reference, str) or not reference:
                    errors.append(f"{prefix}:{field}_invalid_reference")
                    continue
                path_text = reference.split("#", 1)[0]
                if path_text.startswith("/") or ".." in Path(path_text).parts:
                    errors.append(f"{prefix}:{field}_unsafe_reference:{reference}")
                    continue
                if not _repo_path(root, reference).exists():
                    errors.append(f"{prefix}:{field}_missing:{reference}")
                if reference in seen_refs:
                    errors.append(f"{prefix}:{field}_duplicate:{reference}")
                seen_refs.add(reference)
                if field == "adr":
                    referenced_adrs.add(path_text)
        if entry.get("level") == "CORE_INVARIANT" and entry.get("status") == "ACTIVE":
            if not _as_list(entry.get("authoritative_sources")):
                errors.append(f"{prefix}:core_requires_authoritative_source")
            if not _as_list(entry.get("test_surfaces")):
                errors.append(f"{prefix}:core_requires_test_surface")
        dependencies[invariant_id] = _as_list(entry.get("depends_on"))

    for invariant_id, refs in dependencies.items():
        for ref in refs:
            if ref not in seen_ids:
                errors.append(f"{invariant_id}:unknown_dependency:{ref}")

    for adr_path in sorted((root / "docs/adr").glob("*.md")):
        relative = adr_path.relative_to(root).as_posix()
        if relative not in referenced_adrs:
            errors.append(f"index:orphan_adr:{relative}")
    seen_adr_numbers: dict[str, str] = {}
    for relative in sorted(referenced_adrs):
        errors.extend(validate_adr(root, relative))
        number = Path(relative).name.split("-", 1)[0]
        previous = seen_adr_numbers.get(number)
        if previous is not None and previous != relative:
            errors.append(f"adr:duplicate_number:{number}:{previous}:{relative}")
        seen_adr_numbers[number] = relative

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            errors.append(f"{node}:dependency_cycle")
            return
        if node in visited:
            return
        visiting.add(node)
        for child in dependencies.get(node, []):
            if child in dependencies:
                visit(child)
        visiting.remove(node)
        visited.add(node)

    for invariant_id in dependencies:
        visit(invariant_id)
    return sorted(set(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--index", type=Path)
    args = parser.parse_args(argv)
    errors = validate(args.root, args.index)
    if errors:
        print("SPEC_INVALID")
        for error in errors:
            print(error)
        return 1
    print("SPEC_VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main())
