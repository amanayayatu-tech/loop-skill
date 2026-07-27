#!/usr/bin/env python3
"""Fail-closed validator for the v3.3.8 to v4 preservation register.

This tool is a release-time design/conformance check.  It is not a runtime
writer, migration utility, recovery process, or source of protocol authority.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, Iterable


REGISTRY_RELATIVE = Path(
    "docs/architecture/v3-to-v4-capability-preservation-register.json"
)
REGISTER_DOC_RELATIVE = Path(
    "docs/architecture/v3-to-v4-capability-preservation-register.md"
)
ADR_RELATIVE = Path("docs/adr/0011-loopskill-4-compatible-kernel-refactor.md")
CORPUS_RELATIVE = Path(
    "docs/conformance/loopskill-4-conformance-corpus-design.md"
)
PROTOCOL_MANIFEST_RELATIVE = Path("protocol/v4/loopskill-v4.protocol.json")
ANTI_BLOAT_EVIDENCE_RELATIVE = Path(
    "evidence/v4-development/p5.1-native-entry-and-anti-bloat-evidence.json"
)

ALLOWED_DISPOSITIONS = {
    "RETAIN_CORE",
    "RETAIN_ENTRY",
    "RETAIN_LIBRARY",
    "MOVE_TO_ADAPTER",
    "MOVE_TO_POLICY",
    "COMPAT_ONLY",
    "DEPRECATE",
}
ALLOWED_LEVELS = {
    "PUBLIC_STABLE",
    "PUBLIC_PROVISIONAL",
    "INTERNAL_STABLE",
    "INTERNAL_PROVISIONAL",
}
BASELINE_CLOSED_SET = {
    "public_flows": {
        "count": 18,
        "sha256": "b35373d127958a24c546da9ac447cda034811c9212d24fd13e4b6c34081c3121",
    },
    "public_schemas": {
        "count": 8,
        "sha256": "082d9946ff263b0d5d31234277a243cd34e7f897a8183e911e1182d933b15570",
    },
    "release_install_contracts": {
        "count": 12,
        "sha256": "3c7c4ef5a09a6a14e6fc681a1be2053262ec2bbbe4386e36c83961b41521e79a",
    },
}
REQUIRED_CAPABILITY_FIELDS = {
    "capability_id",
    "name",
    "user_value",
    "level",
    "disposition",
    "v3_sources",
    "test_identities",
    "v4_owner",
    "v4_api",
    "v4_schema",
    "conformance_families",
    "migration",
    "rollback",
    "user_visible_change",
    "rc_blocking",
    "acceptance_evidence",
    "acceptance_case_ids",
    "covers",
}
ANTI_BLOAT_METRICS = {
    "loaded_modules",
    "dependency_edges",
    "command_count",
    "event_count",
    "error_count",
    "user_start_actions",
    "authorization_confirmations",
    "host_interactions",
    "protocol_calls",
    "local_writes",
    "entry_bytes",
    "pack_bytes",
    "latency",
    "unknown_count",
    "human_interventions",
}
PRESERVATION_CASE_FAMILIES = (
    "CAP-INTAKE",
    "CAP-ENTRY",
    "CAP-MODES",
    "CAP-ROLES",
    "CAP-HUMAN",
    "CAP-REPAIR",
    "CAP-OPERABILITY",
    "CAP-AUDIT",
    "CAP-PRIVACY",
    "CAP-COMPAT",
    "CAP-DISTRIBUTION",
    "CAP-DOCS",
    "CAP-RELEASE",
    "CAP-ARTIFACT",
    "CAP-ARCHITECTURE",
)
EXACT_CASE_CATALOG_COUNT = 343
EXACT_CASE_CATALOG_SHA256 = (
    "74333342633ccf0383a7adc9c07e469d5e04765298f8fa92f13fe16c004ba856"
)
PRESERVATION_BINDING_COUNT = 317
PRESERVATION_BINDING_SHA256 = (
    "40901870b48ef657bc6651d94bef221ce24660c8e1079efbc63b7c0341297514"
)
CORPUS_ROW = re.compile(
    r"^\|\s*`(?P<case>[A-Z][A-Z0-9-]+)`\s*\|(?P<body>.*)"
    r"\|\s*(?P<stage>[^|]+)\s*\|"
    r"\s*(?P<count>[0-9]+)\s*\|\s*$"
)


class ValidationFailure(RuntimeError):
    pass


def _embedded_json(text: str, marker: str) -> Any:
    match = re.search(
        rf"<!-- {re.escape(marker)}-BEGIN -->\s*```json\s*(.*?)\s*```\s*"
        rf"<!-- {re.escape(marker)}-END -->",
        text,
        re.DOTALL,
    )
    if match is None:
        raise ValidationFailure(f"missing embedded JSON block: {marker}")
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ValidationFailure(f"invalid embedded JSON block: {marker}") from exc


def _domain_digest(domain: bytes, value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(domain + encoded).hexdigest()


def _exact_case_catalog(corpus: str) -> tuple[set[str], dict[str, set[str]]]:
    catalog = _embedded_json(corpus, "CORPUS-EXACT-CASE-CATALOG")
    if set(catalog) != {
        "schema_version",
        "parameterized_families",
        "preservation_declarations",
    }:
        raise ValidationFailure("exact case catalog shape drift")
    if catalog["schema_version"] != "loopskill-v4-exact-case-catalog-v1":
        raise ValidationFailure("exact case catalog version drift")
    expansions = catalog["parameterized_families"]
    declarations = catalog["preservation_declarations"]
    if not isinstance(expansions, dict) or not isinstance(declarations, list):
        raise ValidationFailure("exact case catalog type drift")

    by_family: dict[str, set[str]] = {}
    exact: list[str] = []
    for family, parameters in expansions.items():
        if (
            not isinstance(family, str)
            or not isinstance(parameters, list)
            or not parameters
            or parameters != list(dict.fromkeys(parameters))
            or not all(isinstance(parameter, str) and parameter for parameter in parameters)
        ):
            raise ValidationFailure(f"invalid case parameter expansion: {family}")
        cases = {f"{family}-{parameter}" for parameter in parameters}
        by_family[family] = cases
        exact.extend(cases)
    if (
        declarations != list(dict.fromkeys(declarations))
        or not all(isinstance(case_id, str) and case_id.startswith("CAP-") for case_id in declarations)
    ):
        raise ValidationFailure("invalid preservation case declarations")
    for family in PRESERVATION_CASE_FAMILIES:
        by_family.setdefault(family, set())
    for case_id in declarations:
        owners = [
            family
            for family in PRESERVATION_CASE_FAMILIES
            if case_id.startswith(family + "-")
        ]
        if len(owners) != 1:
            raise ValidationFailure(f"preservation case declaration owner drift: {case_id}")
        by_family.setdefault(owners[0], set()).add(case_id)
        exact.append(case_id)
    if len(exact) != len(set(exact)):
        raise ValidationFailure("duplicate exact case identity")
    canonical = sorted(exact)
    if len(canonical) != EXACT_CASE_CATALOG_COUNT:
        raise ValidationFailure("exact case catalog count drift")
    digest = _domain_digest(
        b"loopskill.v4.corpus.exact-case-catalog.v1\0", canonical
    )
    if digest != EXACT_CASE_CATALOG_SHA256:
        raise ValidationFailure("exact case catalog digest drift")
    return set(canonical), by_family


def _run(root: Path, *args: str) -> bytes:
    return subprocess.check_output(args, cwd=root)


def _git_text(root: Path, revision: str, path: str) -> str:
    return _run(root, "git", "show", f"{revision}:{path}").decode("utf-8")


def _git_bytes(root: Path, revision: str, path: str) -> bytes:
    return _run(root, "git", "show", f"{revision}:{path}")


def _git_tree(root: Path, revision: str, prefix: str) -> list[str]:
    raw = _run(root, "git", "ls-tree", "-r", "--name-only", revision, prefix)
    return raw.decode("utf-8").splitlines()


def _strict_json(path: Path) -> Any:
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValidationFailure(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationFailure(f"cannot load {path}: {exc}") from exc


def _sha256_lines(values: Iterable[str]) -> str:
    payload = "\n".join(sorted(values)) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _test_methods(root: Path, revision: str, paths: Iterable[str]) -> list[str]:
    identities: list[str] = []
    for path in paths:
        tree = ast.parse(_git_text(root, revision, path), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
                "test_"
            ):
                identities.append(f"{path}::{node.name}")
    return sorted(identities)


def _loopctl_commands(root: Path, revision: str) -> list[str]:
    path = "codex-loop-prompt-architect/scripts/loopctl.py"
    tree = ast.parse(_git_text(root, revision, path), filename=path)
    commands: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_parser" or not node.args:
            continue
        value = node.args[0]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            commands.append(value.value)
    return sorted(commands)


def _schema_symbols(root: Path, revision: str, paths: Iterable[str]) -> list[str]:
    symbols: list[str] = []

    def walk(value: Any, pointer: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                escaped = key.replace("~", "~0").replace("/", "~1")
                child_pointer = f"{pointer}/{escaped}"
                if key == "enum" and isinstance(child, list):
                    for member in child:
                        encoded = json.dumps(
                            member, ensure_ascii=False, separators=(",", ":")
                        )
                        symbols.append(f"{child_pointer}={encoded}")
                elif key == "const":
                    encoded = json.dumps(
                        child, ensure_ascii=False, separators=(",", ":")
                    )
                    symbols.append(f"{child_pointer}={encoded}")
                walk(child, child_pointer)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{pointer}/{index}")

    for path in paths:
        document = json.loads(_git_bytes(root, revision, path))
        walk(document, path)

    package_name = "_loopskill_preservation_v3"
    package = types.ModuleType(package_name)
    package.__path__ = []  # type: ignore[attr-defined]
    human_name = f"{package_name}.human_control"
    schema_name = f"{package_name}.schema"
    previous = {
        name: sys.modules.get(name)
        for name in (package_name, human_name, schema_name)
    }
    try:
        sys.modules[package_name] = package
        human = types.ModuleType(human_name)
        human.__package__ = package_name
        sys.modules[human_name] = human
        human_path = (
            "codex-loop-prompt-architect/scripts/loop_architect/human_control.py"
        )
        exec(
            compile(_git_bytes(root, revision, human_path), human_path, "exec"),
            human.__dict__,
        )
        schema = types.ModuleType(schema_name)
        schema.__package__ = package_name
        sys.modules[schema_name] = schema
        schema_path = "codex-loop-prompt-architect/scripts/loop_architect/schema.py"
        exec(
            compile(_git_bytes(root, revision, schema_path), schema_path, "exec"),
            schema.__dict__,
        )
        walk(schema.INPUT_SCHEMA, f"{schema_path}#INPUT_SCHEMA")
    finally:
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    return sorted(symbols)


def _inventory(root: Path, registry: dict[str, Any]) -> tuple[dict[str, list[str]], list[str]]:
    source = registry["source_identity"]
    revision = source["commit"]
    references = sorted(
        _git_tree(root, revision, "codex-loop-prompt-architect/references")
    )
    modules = sorted(
        path
        for path in _git_tree(
            root, revision, "codex-loop-prompt-architect/scripts/loop_architect"
        )
        if path.endswith(".py")
    )
    test_files = sorted(
        path
        for path in _git_tree(root, revision, "tests")
        if re.fullmatch(r"tests/test_[^/]+\.py", path)
    )
    test_methods = _test_methods(root, revision, test_files)
    invariant_text = _git_text(root, revision, "docs/spec/invariants.yaml")
    invariants = sorted(re.findall(r"^  - id: (\S+)", invariant_text, re.MULTILINE))
    commands = _loopctl_commands(root, revision)
    recovery_path = (
        "codex-loop-prompt-architect/references/recovery-registry-v1.json"
    )
    errors = sorted(json.loads(_git_bytes(root, revision, recovery_path))["entries"])
    schema_paths = sorted(
        path for path in references if path.endswith(".schema.json")
    )
    schema_symbols = _schema_symbols(root, revision, schema_paths)
    inventories = {
        "references": references,
        "modules": modules,
        "test_files": test_files,
        "test_methods": test_methods,
        "invariants": invariants,
        "commands": commands,
        "errors": errors,
        "schema_symbols": schema_symbols,
    }
    required_items = [f"invariant:{item}" for item in invariants]
    required_items += [f"command:{item}" for item in commands]
    required_items += [f"schema_symbol:{item}" for item in schema_symbols]
    required_items += [f"reference:{item}" for item in references]
    required_items += [f"module:{item}" for item in modules]
    required_items += [f"test_file:{item}" for item in test_files]
    return inventories, required_items


def _validate_source_identity(root: Path, registry: dict[str, Any]) -> None:
    source = registry["source_identity"]
    commit = source["commit"]
    resolved = _run(root, "git", "rev-parse", f"{source['tag']}^{{}}").decode().strip()
    if resolved != commit:
        raise ValidationFailure(
            f"tag/commit mismatch: {source['tag']} -> {resolved}, expected {commit}"
        )
    public_main = _run(root, "git", "rev-parse", "origin/main").decode().strip()
    if public_main != commit:
        raise ValidationFailure(
            f"origin/main drift: {public_main}, expected public baseline {commit}"
        )
    treatment = _run(
        root, "git", "rev-parse", f"{source['paper_reference_tag']}^{{}}"
    ).decode().strip()
    if treatment != source["paper_reference_commit"]:
        raise ValidationFailure("paper treatment provenance mismatch")


def _validate_inventory_expectations(
    inventories: dict[str, list[str]], registry: dict[str, Any]
) -> None:
    expected = registry["inventory_expectations"]
    for name, values in inventories.items():
        item = expected.get(name)
        if not isinstance(item, dict):
            raise ValidationFailure(f"missing inventory expectation: {name}")
        actual_count = len(values)
        actual_digest = _sha256_lines(values)
        if item.get("count") != actual_count or item.get("sha256") != actual_digest:
            raise ValidationFailure(
                f"inventory drift {name}: count={actual_count} sha256={actual_digest}"
            )


def _validate_declared_surfaces(
    root: Path, registry: dict[str, Any], required_items: list[str]
) -> None:
    revision = registry["source_identity"]["commit"]
    for section, prefix in (
        ("public_flows", "flow"),
        ("public_schemas", "schema"),
        ("release_install_contracts", "release"),
    ):
        seen: set[str] = set()
        identities: list[str] = []
        for item in registry[section]:
            identifier = item["id"]
            if identifier in seen:
                raise ValidationFailure(f"duplicate {section} id: {identifier}")
            seen.add(identifier)
            path = item["path"]
            content = _git_text(root, revision, path)
            anchor = item["anchor"]
            if anchor not in content:
                raise ValidationFailure(
                    f"missing provenance anchor for {identifier}: {path}::{anchor}"
                )
            identities.append(f"{identifier}|{path}|{anchor}")
            required_items.append(f"{prefix}:{identifier}")
        actual = {"count": len(identities), "sha256": _sha256_lines(identities)}
        expected = BASELINE_CLOSED_SET[section]
        declared = registry["inventory_expectations"].get(section)
        if actual != expected or declared != expected:
            raise ValidationFailure(
                f"closed public surface drift {section}: actual={actual} expected={expected} declared={declared}"
            )


def _validate_error_ownership(
    registry: dict[str, Any], errors: list[str], required_items: list[str]
) -> None:
    ownership = registry.get("error_ownership")
    if not isinstance(ownership, dict) or not ownership:
        raise ValidationFailure("missing explicit error ownership")
    capability_ids = {
        capability["capability_id"] for capability in registry["capabilities"]
    }
    seen: dict[str, str] = {}
    for capability_id, codes in ownership.items():
        if capability_id not in capability_ids:
            raise ValidationFailure(f"unknown error owner: {capability_id}")
        if not isinstance(codes, list) or not codes:
            raise ValidationFailure(f"empty error ownership group: {capability_id}")
        if codes != sorted(codes) or len(codes) != len(set(codes)):
            raise ValidationFailure(f"non-canonical error ownership: {capability_id}")
        for code in codes:
            previous = seen.get(code)
            if previous is not None:
                raise ValidationFailure(
                    f"duplicate error ownership: {code} -> {previous}, {capability_id}"
                )
            seen[code] = capability_id
            required_items.append(f"error_owner:{capability_id}:{code}")
    expected = set(errors)
    actual = set(seen)
    if actual != expected:
        missing = sorted(expected - actual)
        foreign = sorted(actual - expected)
        raise ValidationFailure(
            f"error ownership mismatch: missing={missing[:20]} foreign={foreign[:20]}"
        )


def _validate_anti_bloat_contract(registry: dict[str, Any]) -> None:
    contract = registry.get("anti_bloat_contract")
    if not isinstance(contract, dict):
        raise ValidationFailure("missing anti-bloat contract")
    required = {
        "composition",
        "canonical_authority",
        "wire_authority",
        "kernel_forbidden_dependencies",
        "optional_isolation",
        "compatibility_boundary",
        "semantic_compression",
        "capability_group_count",
        "legacy_inventory_runtime_branch_count",
        "canonical_writer_count",
        "port_independence",
        "import_graph",
        "minimal_profile_required_flow",
        "default_path_growth_rule",
        "rc_receipt_role",
        "measurement_order",
        "candidate_thresholds",
        "no_arbitrary_size_cap",
        "default_path_metrics",
    }
    missing = required - set(contract)
    if missing:
        raise ValidationFailure(f"anti-bloat contract missing fields: {sorted(missing)}")
    if contract["capability_group_count"] != 24 or len(registry["capabilities"]) != 24:
        raise ValidationFailure("anti-bloat semantic capability group count must remain 24")
    if contract["legacy_inventory_runtime_branch_count"] != 0:
        raise ValidationFailure("legacy inventory may not define v4 runtime branches")
    if contract["canonical_writer_count"] != 1:
        raise ValidationFailure("canonical writer count drift")
    if contract["port_independence"] != {
        "store_may_call_host": False,
        "artifact_may_write_canonical_state": False,
        "adapter_may_write_canonical_state": False,
    }:
        raise ValidationFailure("port independence contract drift")
    if contract["import_graph"] != {
        "scope": "all loop_architect.v4_* modules",
        "acyclic": True,
        "kernel_allowed_local_roots": [
            "loop_architect.v4_alpha.generated_protocol",
            "loop_architect.v4_alpha.protocol",
            "loop_architect.v4_alpha.store_port",
        ],
    }:
        raise ValidationFailure("v4 import graph contract drift")
    if contract["minimal_profile_required_flow"] != [
        "intake",
        "prepare",
        "confirm",
        "start",
        "status",
        "UNKNOWN",
        "UNVERIFIABLE",
    ]:
        raise ValidationFailure("minimal-profile required flow drift")
    if set(contract["default_path_metrics"]) != ANTI_BLOAT_METRICS:
        raise ValidationFailure("anti-bloat default-path metric set drift")
    thresholds = contract["candidate_thresholds"]
    if thresholds != {
        "pack_bytes_max": 32768,
        "internal_control_interaction_reduction_min": 0.5,
        "status": "candidate until pre-observation baseline freeze",
    }:
        raise ValidationFailure("anti-bloat candidate threshold drift")
    forbidden = set(contract["kernel_forbidden_dependencies"])
    if forbidden != {
        "Codex",
        "App",
        "Host enum",
        "policy",
        "compat/importer",
        "UI/CLI",
        "Git",
        "subprocess",
        "filesystem mutation",
        "SQLite concrete",
        "Pack renderer",
        "paper/Oracle apparatus",
    }:
        raise ValidationFailure("anti-bloat Kernel forbidden-dependency set drift")


def _v4_module_name(package_root: Path, source: Path) -> str:
    relative = source.relative_to(package_root)
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(("loop_architect", *parts))


def _v4_import_graph(root: Path) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    package_root = (
        root / "codex-loop-prompt-architect" / "scripts" / "loop_architect"
    )
    sources = sorted(
        source
        for source in package_root.rglob("*.py")
        if any(part.startswith("v4_") for part in source.relative_to(package_root).parts)
    )
    modules = {_v4_module_name(package_root, source): source for source in sources}
    graph: dict[str, set[str]] = {module: set() for module in modules}
    raw_imports: dict[str, set[str]] = {module: set() for module in modules}

    def local_target(name: str) -> str | None:
        candidate = name
        while candidate.startswith("loop_architect.v4_"):
            if candidate in modules:
                return candidate
            if "." not in candidate:
                break
            candidate = candidate.rsplit(".", 1)[0]
        return None

    for module, source in modules.items():
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        is_package = source.name == "__init__.py"
        package = module if is_package else module.rsplit(".", 1)[0]
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package.split(".")
                    keep = len(base) - (node.level - 1)
                    if keep < 1:
                        raise ValidationFailure(f"invalid relative import: {source}")
                    prefix = ".".join(base[:keep])
                    if node.module:
                        names.append(f"{prefix}.{node.module}")
                    else:
                        names.extend(f"{prefix}.{alias.name}" for alias in node.names)
                elif node.module:
                    names.append(node.module)
            for name in names:
                raw_imports[module].add(name)
                target = local_target(name)
                if target is not None and target != module:
                    graph[module].add(target)
    return graph, raw_imports


def _validate_architecture_fitness(root: Path, registry: dict[str, Any]) -> dict[str, int]:
    graph, imports = _v4_import_graph(root)
    contract = registry["anti_bloat_contract"]
    allowed_kernel = set(contract["import_graph"]["kernel_allowed_local_roots"])
    kernel_modules = {
        "loop_architect.v4_alpha.generated_protocol",
        "loop_architect.v4_alpha.protocol",
        "loop_architect.v4_alpha.kernel",
        "loop_architect.v4_alpha.store_port",
    }
    forbidden_roots = {
        "codex",
        "git",
        "http",
        "os",
        "pathlib",
        "requests",
        "socket",
        "sqlite3",
        "subprocess",
        "urllib",
    }
    forbidden_local = (
        "loop_architect.v4_adapters",
        "loop_architect.v4_artifacts",
        "loop_architect.v4_entry",
        "loop_architect.v4_persistence",
        "loop_architect.v4_policy",
        "loop_architect.v4_compat",
    )
    violations: list[str] = []
    for module in kernel_modules:
        for imported in imports.get(module, set()):
            if imported.split(".", 1)[0] in forbidden_roots:
                violations.append(f"kernel:{module}->{imported}")
            if any(
                imported == denied or imported.startswith(denied + ".")
                for denied in forbidden_local
            ):
                violations.append(f"kernel:{module}->{imported}")
        for target in graph.get(module, set()):
            if target not in kernel_modules and target not in allowed_kernel:
                violations.append(f"kernel-local:{module}->{target}")

    independent_ports = {
        "loop_architect.v4_persistence": (
            "loop_architect.v4_adapters",
            "loop_architect.v4_artifacts",
            "loop_architect.v4_entry",
        ),
        "loop_architect.v4_artifacts": (
            "loop_architect.v4_adapters",
            "loop_architect.v4_persistence",
            "loop_architect.v4_entry",
        ),
        "loop_architect.v4_adapters": (
            "loop_architect.v4_artifacts",
            "loop_architect.v4_persistence",
            "loop_architect.v4_entry",
            "loop_architect.v4_alpha.kernel",
            "loop_architect.v4_alpha.store",
        ),
    }
    for source_prefix, denied_prefixes in independent_ports.items():
        for module, imported_names in imports.items():
            if module != source_prefix and not module.startswith(source_prefix + "."):
                continue
            for imported in imported_names:
                if any(
                    imported == denied or imported.startswith(denied + ".")
                    for denied in denied_prefixes
                ):
                    violations.append(f"port:{module}->{imported}")
    if violations:
        raise ValidationFailure(f"anti-bloat dependency violation: {sorted(violations)}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module: str, path: tuple[str, ...]) -> None:
        if module in visiting:
            raise ValidationFailure(
                "cyclic v4 import graph: " + " -> ".join((*path, module))
            )
        if module in visited:
            return
        visiting.add(module)
        for target in sorted(graph[module]):
            visit(target, (*path, module))
        visiting.remove(module)
        visited.add(module)

    for module in sorted(graph):
        visit(module, ())
    _run(root, sys.executable, "scripts/generate_v4_protocol.py", "--check")
    return {
        "v4_module_count": len(graph),
        "v4_dependency_edge_count": sum(len(targets) for targets in graph.values()),
    }


def _validate_anti_bloat_evidence_value(root: Path, evidence: dict[str, Any]) -> None:
    if evidence.get("artifact") != "loopskill-v4-p5.1-native-entry-and-anti-bloat-evidence-v1":
        raise ValidationFailure("anti-bloat evidence artifact drift")
    if (
        evidence.get("status") != "PASS"
        or evidence.get("runtime_authority") is not False
        or evidence.get("real_external_effects") != 0
    ):
        raise ValidationFailure("anti-bloat evidence status/authority drift")
    head = _run(root, "git", "rev-parse", "HEAD").decode("ascii").strip()
    if evidence.get("source_head") != head:
        raise ValidationFailure("anti-bloat evidence HEAD drift")
    preservation = evidence.get("preservation_gate", {})
    if {
        "reviewer_verdict": preservation.get("reviewer_verdict"),
        "capability_groups": preservation.get("capability_groups"),
        "mapped_v3_identities": preservation.get("mapped_v3_identities"),
        "corpus_families": preservation.get("corpus_families"),
        "corpus_instances": preservation.get("corpus_instances"),
        "preservation_case_bindings": preservation.get("preservation_case_bindings"),
    } != {
        "reviewer_verdict": "PASS",
        "capability_groups": 24,
        "mapped_v3_identities": 1766,
        "corpus_families": 101,
        "corpus_instances": 343,
        "preservation_case_bindings": 317,
    }:
        raise ValidationFailure("anti-bloat preservation evidence drift")
    architecture = evidence.get("architecture_gates", {})
    if (
        architecture.get("typed_protocol_generation") != "PASS"
        or architecture.get("canonical_writer_count") != 1
        or architecture.get("full_v4_module_count") != 19
        or architecture.get("full_v4_dependency_edge_count") != 27
        or architecture.get("full_v4_import_graph_acyclic") is not True
        or architecture.get("kernel_forbidden_import_scan") != "PASS"
        or architecture.get("independent_store_artifact_adapter_ports") != "PASS"
        or architecture.get("minimal_profile_policy_unavailable") != "PASS"
        or architecture.get("minimal_profile_compat_unavailable") != "PASS"
    ):
        raise ValidationFailure("anti-bloat architecture evidence drift")
    metrics = evidence.get("default_path_measurement", {})
    expected_metrics = {
        "loaded_v4_modules": 13,
        "loaded_v4_dependency_edges": 17,
        "manifest_command_count": 16,
        "manifest_event_count": 33,
        "manifest_error_count": 40,
        "user_start_actions": 1,
        "authorization_confirmations": 1,
        "host_interactions": 0,
        "protocol_calls": 1,
        "canonical_commits": 1,
        "prepare_local_writes": 5,
        "confirm_local_writes": 1,
        "entry_bytes": 11125,
        "pack_bytes": 627,
        "prepared_artifact_bytes": 2817,
        "unknown_count": 0,
        "human_interventions": 1,
        "startup_attempts": 1,
        "startup_events": 5,
        "startup_effect_state": "ATTEMPT_COMMITTED",
    }
    if any(metrics.get(key) != value for key, value in expected_metrics.items()):
        raise ValidationFailure("anti-bloat default-path evidence drift")
    tests = evidence.get("tests", {})
    if (tests.get("total"), tests.get("passed"), tests.get("failed"), tests.get("errors")) != (
        96,
        96,
        0,
        0,
    ):
        raise ValidationFailure("anti-bloat test evidence drift")
    thresholds = evidence.get("candidate_thresholds", {})
    if (
        thresholds.get("pack_bytes_max") != 32768
        or thresholds.get("internal_control_interaction_reduction_min") != 0.5
        or not str(thresholds.get("status", "")).startswith("not yet blocking")
    ):
        raise ValidationFailure("anti-bloat candidate threshold evidence drift")
    digests = evidence.get("file_sha256")
    if not isinstance(digests, dict) or not digests:
        raise ValidationFailure("anti-bloat file digest evidence missing")
    for relative, expected in digests.items():
        path = root / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValidationFailure(f"anti-bloat file digest drift: {relative}")


def _validate_anti_bloat_evidence(root: Path) -> None:
    _validate_anti_bloat_evidence_value(
        root, _strict_json(root / ANTI_BLOAT_EVIDENCE_RELATIVE)
    )


def _validate_case_bindings(root: Path, registry: dict[str, Any]) -> tuple[int, int]:
    bindings = registry.get("capability_case_bindings")
    requirements = registry.get("capability_acceptance_requirements")
    capabilities = {
        capability["capability_id"]: capability
        for capability in registry["capabilities"]
    }
    if not isinstance(bindings, dict) or set(bindings) != set(capabilities):
        raise ValidationFailure("capability case binding owner set drift")
    if not isinstance(requirements, dict) or set(requirements) != set(capabilities):
        raise ValidationFailure("capability acceptance requirement owner set drift")

    corpus = (root / CORPUS_RELATIVE).read_text(encoding="utf-8")
    exact_catalog, _ = _exact_case_catalog(corpus)
    index = _embedded_json(corpus, "PRESERVATION-CASE-BINDING-INDEX")
    if not isinstance(index, list) or index != sorted(set(index)):
        raise ValidationFailure("preservation case binding index is not canonical")
    if len(index) != PRESERVATION_BINDING_COUNT:
        raise ValidationFailure("preservation case binding count drift")
    unknown = sorted(set(index) - exact_catalog)
    if unknown:
        raise ValidationFailure(f"case binding absent from exact catalog: {unknown[:20]}")
    if _domain_digest(
        b"loopskill.v4.preservation.case-bindings.v1\0", index
    ) != PRESERVATION_BINDING_SHA256:
        raise ValidationFailure("preservation case binding digest drift")
    bound_union = sorted({case for cases in bindings.values() for case in cases})
    if index != bound_union:
        raise ValidationFailure("preservation case binding index drift")

    variants = registry.get("conformance_family_variants")
    families = set(registry["conformance_families"])
    if not isinstance(variants, dict) or set(variants) != families:
        raise ValidationFailure("conformance family variant owner set drift")
    for family, family_variants in variants.items():
        if set(family_variants) != {"normal", "reject", "boundary", "zero_effect"}:
            raise ValidationFailure(f"conformance family variant set drift: {family}")
        allowed = {
            case_id
            for capability in capabilities.values()
            if family in capability["conformance_families"]
            for case_id in bindings[capability["capability_id"]]
        }
        if not set(family_variants.values()).issubset(allowed):
            raise ValidationFailure(f"conformance family variant binding drift: {family}")

    claim_ids: set[str] = set()
    for capability_id, capability in capabilities.items():
        cases = bindings[capability_id]
        if not isinstance(cases, list) or not cases or cases != list(dict.fromkeys(cases)):
            raise ValidationFailure(f"invalid acceptance case binding: {capability_id}")
        if capability["acceptance_case_ids"] != cases:
            raise ValidationFailure(f"acceptance case binding mismatch: {capability_id}")
        linked: list[str] = []
        claims = requirements[capability_id]
        if not isinstance(claims, list) or not claims:
            raise ValidationFailure(f"missing acceptance requirements: {capability_id}")
        for claim in claims:
            if set(claim) != {"claim_id", "claim", "case_ids"}:
                raise ValidationFailure(f"invalid acceptance requirement: {capability_id}")
            claim_id = claim["claim_id"]
            if claim_id in claim_ids:
                raise ValidationFailure(f"duplicate acceptance claim: {claim_id}")
            claim_ids.add(claim_id)
            if not isinstance(claim["claim"], str) or not claim["claim"].strip():
                raise ValidationFailure(f"empty acceptance claim: {claim_id}")
            if not claim["case_ids"]:
                raise ValidationFailure(f"unbound acceptance claim: {claim_id}")
            linked.extend(claim["case_ids"])
        if set(linked) != set(cases):
            raise ValidationFailure(f"acceptance claim coverage mismatch: {capability_id}")
        unknown_cases = sorted(set(cases) - exact_catalog)
        if unknown_cases:
            raise ValidationFailure(
                f"case binding absent from exact catalog: {unknown_cases[:20]}"
            )
    required_entry_summary = (
        "`UX-001-a..b`, `UX-012-a..c`, `UX-013-a..d`, "
        "`UX-014-a..d`, `UX-015-a..c`, `UX-016-a`"
    )
    if required_entry_summary not in corpus:
        raise ValidationFailure("CAP-ENTRY summary binding drift")
    return len(registry["conformance_families"]), len(index)


def _validate_p5_wire_literals(root: Path) -> None:
    manifest = _strict_json(root / PROTOCOL_MANIFEST_RELATIVE)
    commands = set(manifest.get("commands", {}))
    events = set(manifest.get("events", []))
    required = {
        "LoopCreated",
        "GoalRegistered",
        "GoalActivated",
        "StartAuthorized",
        "ExternalEffectPrepared",
        "ExternalEffectObserved",
        "HostResourceBound",
        "ExternalEffectUnknown",
    }
    if "CreateLoop" not in commands or not required.issubset(events):
        raise ValidationFailure("P5.1 typed manifest wire literals are incomplete")
    forbidden_parallel = {
        "StartupAttemptPrepared",
        "PreparationRecorded",
        "ReviewRequested",
        "ReviewInvalidated",
        "HumanDecisionAccepted",
        "RepairAuthorized",
        "RepairExhausted",
        "FinalizationAcknowledged",
    }
    corpus = (root / CORPUS_RELATIVE).read_text(encoding="utf-8")
    registry = (root / REGISTRY_RELATIVE).read_text(encoding="utf-8")
    leaked = sorted(
        literal
        for literal in forbidden_parallel
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(literal)}(?![A-Za-z0-9_])", corpus)
        or re.search(rf"(?<![A-Za-z0-9_]){re.escape(literal)}(?![A-Za-z0-9_])", registry)
    )
    if leaked:
        raise ValidationFailure(f"parallel untyped event literals: {leaked}")


def _validate_capabilities(
    root: Path,
    registry: dict[str, Any],
    inventories: dict[str, list[str]],
    required_items: list[str],
) -> tuple[int, int]:
    revision = registry["source_identity"]["commit"]
    methods = set(inventories["test_methods"])
    capability_ids: set[str] = set()
    matchers: list[tuple[str, re.Pattern[str]]] = []
    families = set(registry["conformance_families"])
    for capability in registry["capabilities"]:
        missing = REQUIRED_CAPABILITY_FIELDS - set(capability)
        if missing:
            raise ValidationFailure(
                f"{capability.get('capability_id', '<unknown>')} missing fields: {sorted(missing)}"
            )
        capability_id = capability["capability_id"]
        if capability_id in capability_ids:
            raise ValidationFailure(f"duplicate capability id: {capability_id}")
        capability_ids.add(capability_id)
        if capability["level"] not in ALLOWED_LEVELS:
            raise ValidationFailure(f"invalid level for {capability_id}")
        if capability["disposition"] not in ALLOWED_DISPOSITIONS:
            raise ValidationFailure(f"invalid disposition for {capability_id}")
        if capability["rc_blocking"] is not True:
            raise ValidationFailure(f"preservation capability must block RC: {capability_id}")
        if not capability["conformance_families"] or not set(
            capability["conformance_families"]
        ).issubset(families):
            raise ValidationFailure(f"invalid conformance family for {capability_id}")
        if capability["disposition"] == "DEPRECATE":
            if not capability.get("replacement") or not capability.get(
                "deprecation_rationale"
            ):
                raise ValidationFailure(
                    f"deprecated capability lacks replacement/rationale: {capability_id}"
                )
        for source in capability["v3_sources"]:
            content = _git_text(root, revision, source["path"])
            if source["anchor"] not in content:
                raise ValidationFailure(
                    f"missing source anchor for {capability_id}: {source}"
                )
        for identity in capability["test_identities"]:
            if identity not in methods:
                raise ValidationFailure(
                    f"unknown exact test identity for {capability_id}: {identity}"
                )
        for expression in capability["covers"]:
            try:
                matcher = re.compile(expression)
            except re.error as exc:
                raise ValidationFailure(
                    f"invalid coverage expression for {capability_id}: {exc}"
                ) from exc
            matchers.append((capability_id, matcher))

    unmapped: list[str] = []
    duplicated: list[str] = []
    for item in required_items:
        owners = {
            capability_id
            for capability_id, matcher in matchers
            if matcher.fullmatch(item)
        }
        if not owners:
            unmapped.append(item)
        elif len(owners) != 1:
            duplicated.append(f"{item} -> {sorted(owners)}")
    if unmapped:
        raise ValidationFailure(f"unmapped preservation items: {unmapped[:20]}")
    if duplicated:
        raise ValidationFailure(f"multiply mapped preservation items: {duplicated[:20]}")

    docs = [
        root / REGISTER_DOC_RELATIVE,
        root / ADR_RELATIVE,
        root / CORPUS_RELATIVE,
    ]
    for path in docs:
        text = path.read_text(encoding="utf-8")
        missing_ids = sorted(item for item in capability_ids if item not in text)
        if path in (root / REGISTER_DOC_RELATIVE, root / ADR_RELATIVE) and missing_ids:
            raise ValidationFailure(
                f"{path.relative_to(root)} omits capability ids: {missing_ids}"
            )
    return len(capability_ids), len(required_items)


def _validate_corpus(root: Path, registry: dict[str, Any]) -> tuple[int, int]:
    text = (root / CORPUS_RELATIVE).read_text(encoding="utf-8")
    exact_catalog, catalog_by_family = _exact_case_catalog(text)
    rows: dict[str, tuple[str, int]] = {}
    for line in text.splitlines():
        match = CORPUS_ROW.match(line)
        if not match:
            continue
        case_id = match.group("case")
        if case_id in rows:
            raise ValidationFailure(f"duplicate corpus family: {case_id}")
        rows[case_id] = (match.group("body"), int(match.group("count")))
    for family in registry["conformance_families"]:
        if family not in rows:
            raise ValidationFailure(f"missing preservation corpus family: {family}")
    missing_catalog_families = sorted(set(rows) - set(catalog_by_family))
    extra_catalog_families = sorted(set(catalog_by_family) - set(rows))
    if missing_catalog_families or extra_catalog_families:
        raise ValidationFailure(
            "exact case catalog family drift: "
            f"missing={missing_catalog_families[:20]} "
            f"extra={extra_catalog_families[:20]}"
        )
    count_drift = {
        family: (rows[family][1], len(catalog_by_family[family]))
        for family in rows
        if rows[family][1] != len(catalog_by_family[family])
    }
    if count_drift:
        raise ValidationFailure(f"exact case family count drift: {count_drift}")
    if sum(count for _, count in rows.values()) != len(exact_catalog):
        raise ValidationFailure("corpus instance count does not match exact catalog")
    return len(rows), len(exact_catalog)


def _scan_stale(root: Path) -> None:
    paths = [
        root / REGISTRY_RELATIVE,
        root / REGISTER_DOC_RELATIVE,
        root / ADR_RELATIVE,
        root / CORPUS_RELATIVE,
    ]
    stale = re.compile(r"\b(?:TBD|TODO|FIXME)\b", re.IGNORECASE)
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if stale.search(text):
            raise ValidationFailure(f"stale placeholder in {path.relative_to(root)}")


def _reject_placeholders(value: Any, location: str = "registry") -> None:
    stale = re.compile(r"\b(?:TBD|TODO|FIXME)\b", re.IGNORECASE)
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_placeholders(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_placeholders(child, f"{location}[{index}]")
    elif isinstance(value, str) and stale.search(value):
        raise ValidationFailure(f"stale placeholder in {location}")


def validate(root: Path) -> dict[str, Any]:
    registry = _strict_json(root / REGISTRY_RELATIVE)
    if registry.get("schema_version") != "loopskill-v4-preservation-v1":
        raise ValidationFailure("unsupported preservation registry schema")
    _reject_placeholders(registry)
    _validate_source_identity(root, registry)
    _validate_anti_bloat_contract(registry)
    architecture_metrics = _validate_architecture_fitness(root, registry)
    _validate_p5_wire_literals(root)
    inventories, required_items = _inventory(root, registry)
    _validate_inventory_expectations(inventories, registry)
    _validate_declared_surfaces(root, registry, required_items)
    _validate_error_ownership(registry, inventories["errors"], required_items)
    preservation_family_count, preservation_binding_count = _validate_case_bindings(
        root, registry
    )
    capability_count, mapped_count = _validate_capabilities(
        root, registry, inventories, required_items
    )
    family_count, instance_count = _validate_corpus(root, registry)
    _validate_anti_bloat_evidence(root)
    _scan_stale(root)
    return {
        "status": "PASS",
        "source_commit": registry["source_identity"]["commit"],
        "capability_count": capability_count,
        "mapped_required_items": mapped_count,
        "inventory_counts": {key: len(value) for key, value in inventories.items()},
        "corpus_family_count": family_count,
        "corpus_instance_count": instance_count,
        "preservation_family_count": preservation_family_count,
        "preservation_case_binding_count": preservation_binding_count,
        "architecture_fitness": architecture_metrics,
        "runtime_authority": False,
        "external_effects": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = validate(args.root.resolve())
    except (ValidationFailure, subprocess.CalledProcessError, OSError) as exc:
        failure = {"status": "FAIL", "error": str(exc), "external_effects": 0}
        if args.json:
            print(json.dumps(failure, ensure_ascii=False, sort_keys=True))
        else:
            print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
