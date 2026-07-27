#!/usr/bin/env python3
"""Exact-SHA gates and privacy-minimized receipts for v4 publication."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import importlib.metadata
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_TRACKED_ARTIFACT_BYTES = 5 * 1024 * 1024
SECRET_PATTERNS = (
    ("private_key", re.compile(rb"(?m)^-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----$")),
    ("aws_access_key", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("github_token", re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("openai_token", re.compile(rb"sk-[A-Za-z0-9]{20,}")),
)
PRIVATE_TEXT_PATTERNS = (
    (
        "absolute_user_path",
        re.compile(rb"/(?:Users|home)/[A-Za-z0-9._-]+(?:/[^\x00\r\n\t <>\"']*)?"),
    ),
    (
        "raw_host_uuid",
        re.compile(
            rb"(?<![0-9A-Fa-f])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[1-8][0-9A-Fa-f]{3}-[89ABab][0-9A-Fa-f]{3}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f])"
        ),
    ),
)
FORBIDDEN_EVIDENCE_KEYS = {
    "host_id",
    "projectless_root",
    "readback",
    "thread_id",
    "turn_id",
    "worktree",
}
REQUIRED_DISTRIBUTIONS = ("jsonschema", "coverage", "PyYAML")
CANARY_ISSUER = "codex-app-task-readback-v1"
CANARY_TRUST = "host-tool-observed"
CANARY_PROVENANCE_DOMAIN = b"loopskill.v4.app-canary.provenance.v1\0"
RETIRED_PRODUCTION_PATHS = (
    "codex-loop-prompt-architect/scripts/adaptive_state_mcp.py",
    "codex-loop-prompt-architect/scripts/adaptive_state_runtime.py",
    "codex-loop-prompt-architect/scripts/configure_mcp.py",
    "codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py",
    "codex-loop-prompt-architect/scripts/loop_architect/v4_compat/",
    "codex-loop-prompt-architect/scripts/loopctl",
)
RETIRED_RUNTIME_LITERALS = (
    b"ImportV3Snapshot",
    b"V3SnapshotImported",
    b"MIGRATION_",
    b"[mcp_servers.",
    b"adaptive_state_mcp",
    b"codex-loop-state",
    b"loop_architect.v4_compat",
    b"MCP_CANONICAL_WRITER",
    b"State-Writer",
)
RETIRED_LITERAL_ALLOWLIST = {
    "codex-loop-prompt-architect/scripts/validate_skill.py",
    "codex-loop-prompt-architect/scripts/loop_architect/v4_entry/legacy_boundary.py",
}


class RcValidationError(ValueError):
    pass


def _run(root: Path, *argv: str) -> bytes:
    try:
        return subprocess.run(
            argv,
            cwd=root,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise RcValidationError(
            "RC_COMMAND_FAILED: " + " ".join(argv) + ": " + exc.stderr.decode("utf-8", "replace").strip()
        ) from exc


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _domain_digest(domain: bytes, value: Any) -> str:
    return hashlib.sha256(domain + _canonical(value)).hexdigest()


def _load_preservation(root: Path):
    path = root / "scripts/validate_v4_preservation.py"
    spec = importlib.util.spec_from_file_location("v4_preservation_for_rc", path)
    if spec is None or spec.loader is None:
        raise RcValidationError("RC_CASE_CATALOG_VALIDATOR_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _exact_case_catalog(root: Path, candidate: str) -> tuple[list[str], str, str]:
    preservation = _load_preservation(root)
    corpus_path = "docs/conformance/loopskill-4-conformance-corpus-design.md"
    corpus = _run(root, "git", "show", f"{candidate}:{corpus_path}").decode("utf-8", "strict")
    try:
        catalog, _ = preservation._exact_case_catalog(corpus)
    except preservation.ValidationFailure as exc:
        raise RcValidationError(f"RC_CASE_CATALOG_INVALID: {exc}") from exc
    return (
        sorted(catalog),
        preservation.EXACT_CASE_CATALOG_SHA256,
        hashlib.sha256(corpus.encode("utf-8")).hexdigest(),
    )


def _tree_entries(root: Path, candidate: str) -> list[dict[str, Any]]:
    payload = _run(root, "git", "ls-tree", "-rlz", "--full-tree", candidate)
    result = []
    for row in payload.split(b"\0"):
        if not row:
            continue
        metadata, path_bytes = row.split(b"\t", 1)
        mode, kind, object_id, size = metadata.decode("ascii").split()
        path = path_bytes.decode("utf-8", "strict")
        if kind != "blob":
            continue
        result.append(
            {
                "mode": mode,
                "object": object_id,
                "path": path,
                "size": int(size),
            }
        )
    return result


def _dependency_inventory() -> list[dict[str, Any]]:
    installed = {
        (distribution.metadata.get("Name") or "").lower(): distribution
        for distribution in importlib.metadata.distributions()
        if distribution.metadata.get("Name")
    }
    for name in REQUIRED_DISTRIBUTIONS:
        try:
            distribution = installed[name.lower()]
        except KeyError as exc:
            raise RcValidationError(f"RC_DEPENDENCY_UNAVAILABLE: {name}") from exc
        if not distribution.version:
            raise RcValidationError(f"RC_DEPENDENCY_VERSION_UNAVAILABLE: {name}")
    rows = []
    for distribution in installed.values():
        metadata = distribution.metadata
        name = metadata["Name"]
        version = distribution.version
        license_value = metadata.get("License-Expression") or metadata.get("License")
        if not license_value:
            classifiers = metadata.get_all("Classifier") or []
            license_value = ";".join(
                item for item in classifiers if item.startswith("License ::")
            )
        if not license_value:
            raise RcValidationError(f"RC_DEPENDENCY_LICENSE_UNAVAILABLE: {name}")
        rows.append(
            {
                "distribution": name,
                "license": license_value,
                "requires": sorted(distribution.requires or []),
                "version": version,
            }
        )
    return sorted(rows, key=lambda item: item["distribution"].lower())


def _runtime_identity(dependencies: list[dict[str, Any]]) -> dict[str, Any]:
    launcher = Path(sys.executable)
    resolved = launcher.resolve(strict=True)
    if not resolved.is_file():
        raise RcValidationError("RC_RUNTIME_EXECUTABLE_INVALID")
    script = (
        "import importlib.metadata as m,json,sys;"
        "names=('jsonschema','coverage','PyYAML');"
        "print(json.dumps({'isolated_environment':sys.prefix!=sys.base_prefix,"
        "'python':[sys.version_info.major,sys.version_info.minor,sys.version_info.micro],"
        "'required_distributions':{n:m.version(n) for n in names}},"
        "sort_keys=True,separators=(',',':')))"
    )
    try:
        completed = subprocess.run(
            [str(launcher), "-I", "-c", script],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        readback = json.loads(completed.stdout.decode("utf-8", "strict"))
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RcValidationError("RC_RUNTIME_INDEPENDENT_READBACK_FAILED") from exc
    expected_versions = {
        row["distribution"]: row["version"]
        for row in dependencies
        if row["distribution"].lower() in {name.lower() for name in REQUIRED_DISTRIBUTIONS}
    }
    if (
        readback.get("isolated_environment") is not True
        or readback.get("required_distributions") != expected_versions
    ):
        raise RcValidationError("RC_RUNTIME_INDEPENDENT_READBACK_MISMATCH")
    distribution_roots = sorted(
        {
            _domain_digest(
                b"loopskill.v4.runtime.distribution-root.v1\0",
                str(Path(distribution.locate_file("")).resolve()),
            )
            for distribution in importlib.metadata.distributions()
        }
    )
    body = {
        "base_prefix_identity_digest": _domain_digest(
            b"loopskill.v4.runtime.base-prefix.v1\0", sys.base_prefix
        ),
        "distribution_root_count": len(distribution_roots),
        "distribution_root_identity_digests": distribution_roots,
        "isolated_environment": sys.prefix != sys.base_prefix,
        "launcher_identity_digest": _domain_digest(
            b"loopskill.v4.runtime.launcher.v1\0", str(launcher)
        ),
        "prefix_identity_digest": _domain_digest(
            b"loopskill.v4.runtime.prefix.v1\0", sys.prefix
        ),
        "resolved_executable_file_sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
        "runtime_readback": readback,
        "sys_path_identity_digest": _domain_digest(
            b"loopskill.v4.runtime.sys-path.v1\0", sys.path
        ),
    }
    body["runtime_identity_digest"] = _domain_digest(
        b"loopskill.v4.runtime.identity.v1\0", body
    )
    return body


def _tree_privacy_findings(entries: list[dict[str, Any]], root: Path, candidate: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for entry in entries:
        path = entry["path"]
        payload = _run(root, "git", "show", f"{candidate}:{path}")
        if b"\x00" in payload:
            continue
        file_digest = hashlib.sha256(path.encode()).hexdigest()
        for rule, pattern in PRIVATE_TEXT_PATTERNS:
            for match in pattern.finditer(payload):
                findings.append(
                    {
                        "file_digest": file_digest,
                        "finding_digest": hashlib.sha256(match.group(0)).hexdigest(),
                        "rule": rule,
                    }
                )
        if path.startswith("evidence/") and path.endswith(".json"):
            try:
                value = json.loads(payload.decode("utf-8", "strict"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                findings.append({"file_digest": file_digest, "rule": "invalid_json"})
                continue
            stack = [value]
            while stack:
                current = stack.pop()
                if isinstance(current, dict):
                    for key, item in current.items():
                        if key in FORBIDDEN_EVIDENCE_KEYS:
                            findings.append(
                                {"file_digest": file_digest, "rule": "raw_identity_key"}
                            )
                        stack.append(item)
                elif isinstance(current, list):
                    stack.extend(current)
    return findings


def _stale_production_findings(
    entries: list[dict[str, Any]], root: Path, candidate: str
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for entry in entries:
        path = entry["path"]
        if any(
            path == retired or (retired.endswith("/") and path.startswith(retired))
            for retired in RETIRED_PRODUCTION_PATHS
        ):
            findings.append(
                {
                    "path_digest": hashlib.sha256(path.encode()).hexdigest(),
                    "rule": "retired_production_path",
                }
            )
            continue
        is_runtime = (
            path.startswith("codex-loop-prompt-architect/scripts/")
            or path in {"scripts/install.sh", "scripts/uninstall_v4.py"}
        )
        if not is_runtime or path in RETIRED_LITERAL_ALLOWLIST:
            continue
        payload = _run(root, "git", "show", f"{candidate}:{path}")
        for literal in RETIRED_RUNTIME_LITERALS:
            if literal in payload:
                findings.append(
                    {
                        "path_digest": hashlib.sha256(path.encode()).hexdigest(),
                        "rule": "retired_runtime_literal",
                    }
                )
                break
    return findings


def _spdx_sbom(
    root: Path,
    candidate: str,
    dependencies: list[dict[str, Any]],
) -> dict[str, Any]:
    timestamp = _run(root, "git", "show", "-s", "--format=%cI", candidate).decode(
        "ascii", "strict"
    ).strip()
    try:
        created = (
            datetime.fromisoformat(timestamp)
            .astimezone(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )
    except ValueError as exc:
        raise RcValidationError("RC_SBOM_COMMIT_TIME_INVALID") from exc
    packages = [
        {
            "SPDXID": "SPDXRef-Package-LoopSkill-4",
            "copyrightText": "NOASSERTION",
            "downloadLocation": "https://github.com/amanayayatu-tech/loop-skill",
            "filesAnalyzed": False,
            "licenseConcluded": "MIT",
            "licenseDeclared": "MIT",
            "name": "LoopSkill",
            "primaryPackagePurpose": "APPLICATION",
            "versionInfo": "4.0.0",
        }
    ]
    relationships = [
        {
            "relatedSpdxElement": "SPDXRef-Package-LoopSkill-4",
            "relationshipType": "DESCRIBES",
            "spdxElementId": "SPDXRef-DOCUMENT",
        }
    ]
    for index, item in enumerate(dependencies, 1):
        spdx_id = f"SPDXRef-ValidationDependency-{index}"
        packages.append(
            {
                "SPDXID": spdx_id,
                "copyrightText": "NOASSERTION",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": item["license"],
                "licenseDeclared": item["license"],
                "name": item["distribution"],
                "primaryPackagePurpose": "LIBRARY",
                "versionInfo": item["version"],
            }
        )
        relationships.append(
            {
                "comment": "test and release-validation environment only; v4 runtime is standard-library-only",
                "relatedSpdxElement": "SPDXRef-Package-LoopSkill-4",
                "relationshipType": "BUILD_DEPENDENCY_OF",
                "spdxElementId": spdx_id,
            }
        )
    return {
        "SPDXID": "SPDXRef-DOCUMENT",
        "creationInfo": {
            "created": created,
            "creators": ["Tool: LoopSkill-v4-release-gate"],
        },
        "dataLicense": "CC0-1.0",
        "documentNamespace": (
            "https://github.com/amanayayatu-tech/loop-skill/sbom/v4.0.0/"
            + candidate
        ),
        "name": f"LoopSkill-4.0.0-{candidate[:12]}",
        "packages": packages,
        "relationships": relationships,
        "spdxVersion": "SPDX-2.3",
    }


def static_receipt(root: Path, candidate: str, *, require_clean_head: bool = True) -> dict[str, Any]:
    root = root.resolve()
    if not SHA_RE.fullmatch(candidate):
        raise RcValidationError("RC_CANDIDATE_SHA_INVALID")
    resolved = _run(root, "git", "rev-parse", f"{candidate}^{{commit}}").decode("ascii").strip()
    if resolved != candidate:
        raise RcValidationError("RC_CANDIDATE_SHA_MISMATCH")
    if require_clean_head:
        head = _run(root, "git", "rev-parse", "HEAD").decode("ascii").strip()
        status = _run(root, "git", "status", "--porcelain=v1", "--untracked-files=all")
        if head != candidate or status:
            raise RcValidationError("RC_CANDIDATE_WORKTREE_NOT_EXACT_CLEAN_HEAD")
    entries = _tree_entries(root, candidate)
    oversized = [
        {"path_digest": hashlib.sha256(item["path"].encode()).hexdigest(), "size": item["size"]}
        for item in entries
        if item["size"] > MAX_TRACKED_ARTIFACT_BYTES
    ]
    findings = []
    for item in entries:
        payload = _run(root, "git", "show", f"{candidate}:{item['path']}")
        for rule, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(payload):
                findings.append(
                    {
                        "file_digest": hashlib.sha256(item["path"].encode()).hexdigest(),
                        "finding_digest": hashlib.sha256(match.group(0)).hexdigest(),
                        "rule": rule,
                    }
                )
    if findings:
        raise RcValidationError("RC_SECRET_SCAN_FAILED")
    if oversized:
        raise RcValidationError("RC_LARGE_ARTIFACT_SCAN_FAILED")
    evidence_privacy = _tree_privacy_findings(entries, root, candidate)
    if evidence_privacy:
        raise RcValidationError("RC_EVIDENCE_PRIVACY_SCAN_FAILED")
    stale_production = _stale_production_findings(entries, root, candidate)
    if stale_production:
        raise RcValidationError("RC_STALE_V3_PRODUCTION_SCAN_FAILED")
    license_payload = _run(root, "git", "show", f"{candidate}:LICENSE")
    if b"MIT License" not in license_payload:
        raise RcValidationError("RC_PROJECT_LICENSE_INVALID")
    version = _run(root, "git", "show", f"{candidate}:VERSION").decode(
        "utf-8", "strict"
    ).strip()
    if version != "4.0.0":
        raise RcValidationError("RC_VERSION_INVALID")
    dependencies = _dependency_inventory()
    runtime_identity = _runtime_identity(dependencies)
    protocol = json.loads(
        _run(root, "git", "show", f"{candidate}:protocol/v4/loopskill-v4.protocol.json").decode(
            "utf-8", "strict"
        )
    )
    sbom = _spdx_sbom(root, candidate, dependencies)
    body = {
        "artifact": "loopskill-v4-publication-static-receipt-v1",
        "candidate_sha": candidate,
        "dependency_inventory": dependencies,
        "dependency_inventory_scope": "all distributions installed in the exact bound Python runtime",
        "evidence_privacy_findings": evidence_privacy,
        "large_artifact_findings": oversized,
        "max_tracked_artifact_bytes": MAX_TRACKED_ARTIFACT_BYTES,
        "project_license": "MIT",
        "protocol_counts": {
            "capabilities": len(protocol["capability_names"]),
            "commands": len(protocol["commands"]),
            "errors": len(protocol["errors"]),
            "events": len(protocol["events"]),
        },
        "public_effects": 0,
        "runtime_identity": runtime_identity,
        "sbom": sbom,
        "sbom_sha256": hashlib.sha256(_canonical(sbom)).hexdigest(),
        "publication_ready": False,
        "secret_findings": findings,
        "stale_production_findings": stale_production,
        "tracked_blob_count": len(entries),
        "tracked_tree_digest": hashlib.sha256(_canonical(entries)).hexdigest(),
    }
    body["receipt_digest"] = hashlib.sha256(_canonical(body)).hexdigest()
    return body


def validate_canary_receipt(value: dict[str, Any], candidate: str) -> None:
    expected_keys = {
        "artifact",
        "candidate_sha",
        "confirmation_count",
        "confirmation_digest_bound",
        "config_bytes_changed",
        "entry",
        "finalization",
        "host_receipt_digest",
        "host_receipt_issuer",
        "host_receipt_trust",
        "host_task_identity_digest",
        "host_task_create_count",
        "host_task_readback_count",
        "intake_external_effects",
        "intake_heartbeat_count",
        "intake_host_task_count",
        "intake_loop_count",
        "loopskill_mcp_registration_count",
        "machine_owned_identity",
        "manual_control_identity_count",
        "app_restart_count",
        "prepare_delivery_count",
        "prepare_heartbeat_count",
        "prepare_host_effects",
        "prepare_host_task_count",
        "private_data_used",
        "provenance_digest",
        "provider_resend_count",
        "research_scored",
        "result",
        "review",
        "status",
        "canary_output_sha256",
        "issued_at",
        "observed_at",
        "fresh_until",
        "thread_content_retained",
        "unknown_preserved",
        "v3_bytes_changed",
    }
    if set(value) != expected_keys:
        raise RcValidationError("RC_CANARY_RECEIPT_SHAPE_INVALID")
    required = {
        "artifact": "loopskill-v4-disposable-app-canary-v1",
        "candidate_sha": candidate,
        "confirmation_count": 1,
        "confirmation_digest_bound": True,
        "config_bytes_changed": 0,
        "entry": "loopskill4",
        "finalization": "ACKNOWLEDGED",
        "host_task_create_count": 1,
        "host_task_readback_count": 1,
        "host_receipt_issuer": CANARY_ISSUER,
        "host_receipt_trust": CANARY_TRUST,
        "intake_external_effects": 0,
        "intake_heartbeat_count": 0,
        "intake_host_task_count": 0,
        "intake_loop_count": 0,
        "loopskill_mcp_registration_count": 0,
        "machine_owned_identity": True,
        "manual_control_identity_count": 0,
        "app_restart_count": 0,
        "prepare_delivery_count": 0,
        "prepare_heartbeat_count": 0,
        "prepare_host_effects": 0,
        "prepare_host_task_count": 0,
        "private_data_used": False,
        "provider_resend_count": 0,
        "research_scored": False,
        "result": "ACKNOWLEDGED",
        "review": "PASS",
        "status": "PASS",
        "thread_content_retained": False,
        "unknown_preserved": True,
        "v3_bytes_changed": 0,
    }
    for key, expected in required.items():
        if value.get(key) != expected:
            raise RcValidationError(f"RC_CANARY_RECEIPT_INVALID: {key}")
    digest = value.get("host_receipt_digest")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise RcValidationError("RC_CANARY_RECEIPT_INVALID: host_receipt_digest")
    for field in ("host_task_identity_digest", "canary_output_sha256"):
        if not isinstance(value.get(field), str) or not re.fullmatch(r"[0-9a-f]{64}", value[field]):
            raise RcValidationError(f"RC_CANARY_RECEIPT_INVALID: {field}")
    try:
        observed = datetime.fromisoformat(value["observed_at"].replace("Z", "+00:00"))
        issued = datetime.fromisoformat(value["issued_at"].replace("Z", "+00:00"))
        fresh_until = datetime.fromisoformat(value["fresh_until"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise RcValidationError("RC_CANARY_RECEIPT_INVALID: freshness") from exc
    if (
        observed.tzinfo is None
        or issued.tzinfo is None
        or fresh_until.tzinfo is None
        or observed.astimezone(timezone.utc) != issued.astimezone(timezone.utc)
        or not issued < fresh_until
        or (fresh_until - issued).total_seconds() > 600
    ):
        raise RcValidationError("RC_CANARY_RECEIPT_INVALID: freshness")
    provenance = dict(value)
    claimed_provenance = provenance.pop("provenance_digest", None)
    claimed_host = provenance.pop("host_receipt_digest", None)
    expected_provenance = _domain_digest(CANARY_PROVENANCE_DOMAIN, provenance)
    if claimed_provenance != expected_provenance or claimed_host != expected_provenance:
        raise RcValidationError("RC_CANARY_RECEIPT_INVALID: provenance_digest")


def validate_conformance_receipt(value: dict[str, Any], candidate: str, root: Path) -> None:
    if (
        value.get("artifact") != "loopskill-v4-conformance-execution-v1"
        or value.get("candidate_sha") != candidate
        or value.get("status") != "PASS"
        or value.get("case_count") != 349
        or value.get("passed") != 349
        or value.get("failed") != 0
        or value.get("real_external_effects") != 1
        or value.get("canonical_case_ids") is not True
    ):
        raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
    results = value.get("case_results")
    if not isinstance(results, list) or len(results) != 349:
        raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
    ids = [item.get("case_id") for item in results if isinstance(item, dict)]
    exact_ids, exact_digest, corpus_digest = _exact_case_catalog(root, candidate)
    if (
        len(ids) != 349
        or ids != exact_ids
        or value.get("case_catalog_digest") != exact_digest
        or value.get("corpus_sha256") != corpus_digest
    ):
        raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
    test_results = value.get("test_method_results")
    if not isinstance(test_results, list) or value.get("test_method_count") != len(test_results):
        raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
    tests_by_id: dict[str, dict[str, Any]] = {}
    for item in test_results:
        if not isinstance(item, dict):
            raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
        test_id = item.get("assertion_test_id")
        deterministic = {
            "assertion_test_id": test_id,
            "case_id": item.get("case_id"),
            "family": item.get("family"),
            "status": item.get("status"),
            "target_test_id": item.get("target_test_id"),
            "tests_run": item.get("tests_run"),
        }
        if (
            not isinstance(test_id, str)
            or test_id in tests_by_id
            or deterministic["status"] != "PASS"
            or deterministic["tests_run"] != 1
            or item.get("result_digest") != hashlib.sha256(_canonical(deterministic)).hexdigest()
        ):
            raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
        tests_by_id[test_id] = item
    canary_sha = None
    binding_rows = []
    for item in results:
        case_id = item.get("case_id")
        family = item.get("family")
        parameter = item.get("parameter")
        test_id = item.get("assertion_test_id")
        target_test_id = item.get("target_test_id")
        contract = {
            "case_id": case_id,
            "corpus_sha256": corpus_digest,
            "family": family,
            "parameter": parameter,
            "test_id": target_test_id,
        }
        if (
            item.get("status") != "PASS"
            or item.get("assertion_count") != 1
            or not isinstance(family, str)
            or case_id != f"{family}-{parameter}"
            or test_id not in tests_by_id
            or tests_by_id[test_id].get("case_id") != case_id
            or tests_by_id[test_id].get("family") != family
            or tests_by_id[test_id].get("target_test_id") != target_test_id
            or item.get("test_result_digest") != tests_by_id[test_id]["result_digest"]
            or item.get("case_contract_digest") != hashlib.sha256(_canonical(contract)).hexdigest()
        ):
            raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
        expected_kind = (
            "REAL_APP_RECEIPT+PARAMETERIZED_UNITTEST_CASE"
            if case_id in {"UX-009-a", "CAP-RELEASE-CANARY"}
            else "PARAMETERIZED_UNITTEST_CASE"
        )
        if item.get("evidence_kind") != expected_kind:
            raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
        if expected_kind.startswith("REAL_APP"):
            current = item.get("canary_receipt_sha256")
            if not isinstance(current, str) or not re.fullmatch(r"[0-9a-f]{64}", current):
                raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
            if canary_sha is not None and current != canary_sha:
                raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
            canary_sha = current
        elif "canary_receipt_sha256" in item:
            raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
        binding_rows.append(
            {"case_id": case_id, "case_contract_digest": item["case_contract_digest"], "test_id": test_id}
        )
    if set(tests_by_id) != {item["assertion_test_id"] for item in results}:
        raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
    if value.get("binding_manifest_digest") != hashlib.sha256(_canonical(binding_rows)).hexdigest():
        raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
    claimed = value.get("case_results_digest")
    if claimed != hashlib.sha256(_canonical(results)).hexdigest():
        raise RcValidationError("RC_CONFORMANCE_RECEIPT_DIGEST_INVALID")


def validate_author_packet(value: dict[str, Any], candidate: str, root: Path) -> None:
    if (
        value.get("artifact") != "loopskill-v4-publication-packet-v1"
        or value.get("candidate_sha") != candidate
        or value.get("status") != "PUBLICATION_CANDIDATE_VALIDATED"
        or value.get("public_release_effects") != 0
        or value.get("real_v3_loop_migrations") != 0
    ):
        raise RcValidationError("RC_AUTHOR_PACKET_INVALID")
    files = value.get("files")
    if not isinstance(files, dict) or len(files) < 12:
        raise RcValidationError("RC_AUTHOR_PACKET_INCOMPLETE")
    for relative, expected in files.items():
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as exc:
            raise RcValidationError("RC_AUTHOR_PACKET_PATH_INVALID") from exc
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RcValidationError(f"RC_AUTHOR_PACKET_FILE_DRIFT: {relative}")


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--canary-receipt", type=Path)
    parser.add_argument("--conformance-receipt", type=Path)
    parser.add_argument("--author-packet", type=Path)
    parser.add_argument("--static-only", action="store_true")
    parser.add_argument("--allow-non-head", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        receipt = static_receipt(
            args.root, args.candidate, require_clean_head=not args.allow_non_head
        )
        if args.static_only:
            if args.canary_receipt or args.conformance_receipt or args.author_packet:
                raise RcValidationError("RC_STATIC_ONLY_WITH_FINAL_RECEIPT")
            receipt["gate_status"] = "PRE_CANARY_STATIC_ONLY"
        else:
            if not args.canary_receipt or not args.conformance_receipt or not args.author_packet:
                raise RcValidationError("RC_FINAL_RECEIPTS_REQUIRED")
            canary = json.loads(args.canary_receipt.read_text(encoding="utf-8"))
            validate_canary_receipt(canary, args.candidate)
            receipt["canary_receipt_digest"] = hashlib.sha256(
                _canonical(canary)
            ).hexdigest()
            conformance = json.loads(args.conformance_receipt.read_text(encoding="utf-8"))
            validate_conformance_receipt(conformance, args.candidate, args.root)
            receipt["conformance_receipt_digest"] = hashlib.sha256(
                _canonical(conformance)
            ).hexdigest()
            packet = json.loads(args.author_packet.read_text(encoding="utf-8"))
            validate_author_packet(packet, args.candidate, args.root)
            receipt["author_packet_digest"] = hashlib.sha256(
                _canonical(packet)
            ).hexdigest()
            receipt["gate_status"] = "LOOPSKILL_4_0_PUBLICATION_CANDIDATE_VALIDATED"
            receipt["publication_ready"] = True
        receipt.pop("receipt_digest", None)
        receipt["receipt_digest"] = hashlib.sha256(_canonical(receipt)).hexdigest()
        if args.output:
            args.output.write_bytes(_canonical(receipt) + b"\n")
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RcValidationError) as exc:
        print(f"RC_VALIDATION_FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
