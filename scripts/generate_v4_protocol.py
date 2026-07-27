#!/usr/bin/env python3
"""Generate deterministic LoopSkill 4 wire artifacts from one manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "protocol" / "v4" / "loopskill-v4.protocol.json"
GENERATED_PY = (
    ROOT
    / "codex-loop-prompt-architect"
    / "scripts"
    / "loop_architect"
    / "v4_alpha"
    / "generated_protocol.py"
)
GENERATED_SCHEMA = ROOT / "protocol" / "v4" / "generated" / "loopskill-v4.schema.json"
GENERATED_SUMMARY = ROOT / "protocol" / "v4" / "generated" / "api-summary.json"


class ManifestError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def parse_manifest(raw: str) -> dict[str, Any]:
    def reject_duplicate(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ManifestError(f"duplicate manifest key: {key}")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=reject_duplicate)
    return validate_manifest(value)


def validate_manifest(value: dict[str, Any]) -> dict[str, Any]:
    required = {
        "assurance_strengths",
        "capability_names",
        "commands",
        "delivery_states",
        "errors",
        "events",
        "protocol_version",
        "reference_kinds",
        "result_states",
        "wire_types",
        "write_cas",
    }
    if set(value) != required:
        raise ManifestError(f"manifest top-level drift: {sorted(set(value) ^ required)}")
    for key in (
        "assurance_strengths",
        "capability_names",
        "delivery_states",
        "errors",
        "events",
        "reference_kinds",
        "result_states",
    ):
        if len(value[key]) != len(set(value[key])):
            raise ManifestError(f"duplicate value in {key}")
    if set(value["commands"]) & set(value["events"]):
        raise ManifestError("command/event names overlap")
    for type_name, fields in value["wire_types"].items():
        names = [field[0] for field in fields]
        if len(names) != len(set(names)):
            raise ManifestError(f"duplicate field in {type_name}")
        for field in fields:
            if len(field) not in (3, 4):
                raise ManifestError(f"invalid field tuple: {type_name}.{field[0]}")
    return value


def load_manifest() -> dict[str, Any]:
    return parse_manifest(MANIFEST.read_text(encoding="utf-8"))


def python_tuple(values: list[str]) -> str:
    body = "\n".join(f"    {value!r}," for value in values)
    return f"(\n{body}\n)"


def generate_python(manifest: dict[str, Any], digest: str) -> bytes:
    lines = [
        '"""Generated from protocol/v4/loopskill-v4.protocol.json; do not edit."""',
        "",
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass",
        "from typing import Any, Mapping",
        "",
        f"MANIFEST_SHA256 = {digest!r}",
        f"PROTOCOL_VERSION = {manifest['protocol_version']!r}",
        f"COMMAND_TYPES = {python_tuple(list(manifest['commands']))}",
        f"EVENT_TYPES = {python_tuple(manifest['events'])}",
        f"ERROR_CODES = {python_tuple(manifest['errors'])}",
        f"REFERENCE_KINDS = {python_tuple(manifest['reference_kinds'])}",
        f"CAPABILITY_NAMES = {python_tuple(manifest['capability_names'])}",
        f"DELIVERY_STATES = {python_tuple(manifest['delivery_states'])}",
        f"RESULT_STATES = {python_tuple(manifest['result_states'])}",
        f"ASSURANCE_STRENGTHS = {python_tuple(manifest['assurance_strengths'])}",
        f"WRITE_CAS = {manifest['write_cas']!r}",
        f"SEMANTIC_PAYLOAD_SPECS = {manifest['commands']!r}",
        "",
    ]
    for type_name, fields in manifest["wire_types"].items():
        lines.extend(["@dataclass(frozen=True)", f"class {type_name}:"])
        for field in fields:
            default = " = False" if len(field) == 4 and field[3] is False else ""
            lines.append(f"    {field[0]}: {field[1]}{default}")
        lines.append("")
    return "\n".join(lines).encode("utf-8")


def generate_schema(manifest: dict[str, Any], digest: str) -> bytes:
    definitions = {}
    for type_name, fields in manifest["wire_types"].items():
        definitions[type_name] = {
            "additionalProperties": False,
            "properties": {field[0]: field[2] for field in fields},
            "required": [field[0] for field in fields if len(field) == 3],
            "type": "object",
        }
    schema = {
        "$defs": definitions,
        "$id": "https://loopskill.local/protocol/v4/loopskill-v4.schema.json",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "manifest_sha256": digest,
        "title": "LoopSkill 4 protocol wire shapes",
    }
    return (json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def generate_summary(manifest: dict[str, Any], digest: str) -> bytes:
    summary = {
        "capabilities": manifest["capability_names"],
        "commands": manifest["commands"],
        "errors": manifest["errors"],
        "events": manifest["events"],
        "manifest_sha256": digest,
        "protocol_version": manifest["protocol_version"],
        "reference_kinds": manifest["reference_kinds"],
        "wire_types": {
            name: [field[0] for field in fields]
            for name, fields in manifest["wire_types"].items()
        },
        "write_cas": manifest["write_cas"],
    }
    return (json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def outputs() -> dict[Path, bytes]:
    manifest = load_manifest()
    digest = hashlib.sha256(canonical(manifest)).hexdigest()
    return {
        GENERATED_PY: generate_python(manifest, digest),
        GENERATED_SCHEMA: generate_schema(manifest, digest),
        GENERATED_SUMMARY: generate_summary(manifest, digest),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        generated = outputs()
        for path, expected in generated.items():
            if args.write:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(expected)
            elif not path.is_file() or path.read_bytes() != expected:
                raise ManifestError(f"generated artifact drift: {path.relative_to(ROOT)}")
        digest = hashlib.sha256(canonical(load_manifest())).hexdigest()
        print(f"V4_PROTOCOL_GENERATION_{'WRITE' if args.write else 'CHECK'}_PASS sha256={digest}")
        return 0
    except (OSError, json.JSONDecodeError, ManifestError) as exc:
        print(f"V4_PROTOCOL_GENERATION_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
