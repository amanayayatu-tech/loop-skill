#!/usr/bin/env python3
"""Exact-SHA gates and privacy-minimized receipts for v4 publication."""

from __future__ import annotations

import argparse
import hashlib
import io
import importlib.util
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import tarfile
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


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
CANARY_LIVE_DOMAIN = b"loopskill.v4.app-canary.live-readback.v1\0"
CANARY_HOST_ID_DOMAIN = b"loopskill.v4.app-canary.host-identity.v1\0"
CANARY_OUTPUT_FILENAME = "canary-output.txt"
CANARY_OUTPUT_BYTES = b"LOOPSKILL4_CANARY_OK\n"
CANARY_OUTPUT_SHA256 = "8d23b5e88d9fb86f366700a6267f29b46bcca5cd45a59ed27afbbd04860eb638"
RETIRED_PRODUCTION_PATHS = (
    "codex-loop-prompt-architect/scripts/adaptive_state_mcp.py",
    "codex-loop-prompt-architect/scripts/adaptive_state_runtime.py",
    "codex-loop-prompt-architect/scripts/configure_mcp.py",
    "codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py",
    "codex-loop-prompt-architect/scripts/loop_architect/v4_compat/",
    "codex-loop-prompt-architect/scripts/loop_architect/v4_adapters/codex/app_server_provider.py",
    "codex-loop-prompt-architect/scripts/loopctl",
)
RETIRED_PUBLIC_SOURCE_PATHS = (
    "P0-CLOSURE.md",
    "P0-P2-CLOSURE.md",
    "docs/codex-app-controller-turn-attestation-blocker.md",
    "docs/codex-app-process-reaping-report.md",
    "docs/readme-assets/",
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
    b"CodexAppServerProvider",
    b"app_server_provider",
    b"app-server --stdio",
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


def _load_author_packet_builder(root: Path):
    path = root / "scripts/build_v4_author_packet.py"
    spec = importlib.util.spec_from_file_location("v4_author_packet_for_rc", path)
    if spec is None or spec.loader is None:
        raise RcValidationError("RC_AUTHOR_PACKET_BUILDER_UNAVAILABLE")
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


def _distribution_archive_receipt(root: Path, candidate: str) -> dict[str, Any]:
    payload = _run(root, "git", "archive", "--format=tar", candidate)
    findings: list[dict[str, str]] = []
    files = []
    total_bytes = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
            for member in archive.getmembers():
                name = member.name
                path = Path(name)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or member.issym()
                    or member.islnk()
                    or member.isdev()
                    or member.isfifo()
                ):
                    findings.append(
                        {
                            "path_digest": hashlib.sha256(name.encode()).hexdigest(),
                            "rule": "unsafe_archive_member",
                        }
                    )
                    continue
                if member.isdir():
                    continue
                if not member.isfile() or member.size > MAX_TRACKED_ARTIFACT_BYTES:
                    findings.append(
                        {
                            "path_digest": hashlib.sha256(name.encode()).hexdigest(),
                            "rule": "invalid_archive_file",
                        }
                    )
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    findings.append(
                        {
                            "path_digest": hashlib.sha256(name.encode()).hexdigest(),
                            "rule": "archive_file_unreadable",
                        }
                    )
                    continue
                content = extracted.read(MAX_TRACKED_ARTIFACT_BYTES + 1)
                if len(content) != member.size:
                    findings.append(
                        {
                            "path_digest": hashlib.sha256(name.encode()).hexdigest(),
                            "rule": "archive_size_mismatch",
                        }
                    )
                    continue
                for rule, pattern in (*SECRET_PATTERNS, *PRIVATE_TEXT_PATTERNS):
                    if pattern.search(content):
                        findings.append(
                            {
                                "path_digest": hashlib.sha256(name.encode()).hexdigest(),
                                "rule": rule,
                            }
                        )
                total_bytes += len(content)
                files.append(
                    {
                        "path_digest": hashlib.sha256(name.encode()).hexdigest(),
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "size": len(content),
                    }
                )
    except (tarfile.TarError, OSError) as exc:
        raise RcValidationError("RC_DISTRIBUTION_ARCHIVE_INVALID") from exc
    if findings:
        raise RcValidationError("RC_DISTRIBUTION_ARCHIVE_SCAN_FAILED")
    return {
        "archive_sha256": hashlib.sha256(payload).hexdigest(),
        "file_count": len(files),
        "file_manifest_digest": hashlib.sha256(_canonical(files)).hexdigest(),
        "findings": findings,
        "total_file_bytes": total_bytes,
    }


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
            for retired in RETIRED_PUBLIC_SOURCE_PATHS
        ):
            findings.append(
                {
                    "path_digest": hashlib.sha256(path.encode()).hexdigest(),
                    "rule": "retired_public_source_path",
                }
            )
            continue
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
    archive_receipt = _distribution_archive_receipt(root, candidate)
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
        "distribution_archive": archive_receipt,
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


def validate_canary_receipt(
    value: dict[str, Any],
    candidate: str,
    *,
    now: datetime | None = None,
) -> None:
    expected_keys = {
        "artifact",
        "candidate_sha",
        "candidate_goal_digest",
        "confirmation_count",
        "confirmation_digest_bound",
        "config_bytes_changed",
        "entry",
        "finalization",
        "host_receipt_digest",
        "host_receipt_issuer",
        "host_receipt_trust",
        "host_create_readback_count",
        "host_lifecycle_readback_count",
        "host_result_digest",
        "host_task_identity_digest",
        "host_task_create_count",
        "host_task_readback_count",
        "host_terminal_wait_readback_count",
        "host_total_read_count",
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
        "host_lifecycle_readback_count": 1,
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
    create_readbacks = value.get("host_create_readback_count")
    if (
        isinstance(create_readbacks, bool)
        or not isinstance(create_readbacks, int)
        or create_readbacks not in {1, 2, 3}
    ):
        raise RcValidationError("RC_CANARY_RECEIPT_INVALID: host_create_readback_count")
    terminal_readbacks = value.get("host_terminal_wait_readback_count")
    total_readbacks = value.get("host_total_read_count")
    if (
        isinstance(terminal_readbacks, bool)
        or not isinstance(terminal_readbacks, int)
        or not 1 <= terminal_readbacks <= 1_200
        or isinstance(total_readbacks, bool)
        or not isinstance(total_readbacks, int)
        or total_readbacks
        != create_readbacks
        + terminal_readbacks
        + value["host_task_readback_count"]
        + value["host_lifecycle_readback_count"]
    ):
        raise RcValidationError("RC_CANARY_RECEIPT_INVALID: host readback counts")
    digest = value.get("host_receipt_digest")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise RcValidationError("RC_CANARY_RECEIPT_INVALID: host_receipt_digest")
    if value.get("canary_output_sha256") != CANARY_OUTPUT_SHA256:
        raise RcValidationError("RC_CANARY_RECEIPT_INVALID: canary_output_sha256")
    for field in ("host_task_identity_digest", "host_result_digest"):
        if not isinstance(value.get(field), str) or not re.fullmatch(r"[0-9a-f]{64}", value[field]):
            raise RcValidationError(f"RC_CANARY_RECEIPT_INVALID: {field}")
    try:
        observed = datetime.fromisoformat(value["observed_at"].replace("Z", "+00:00"))
        issued = datetime.fromisoformat(value["issued_at"].replace("Z", "+00:00"))
        fresh_until = datetime.fromisoformat(value["fresh_until"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise RcValidationError("RC_CANARY_RECEIPT_INVALID: freshness") from exc
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    issued_utc = issued.astimezone(timezone.utc)
    fresh_until_utc = fresh_until.astimezone(timezone.utc)
    if (
        observed.tzinfo is None
        or issued.tzinfo is None
        or fresh_until.tzinfo is None
        or observed.astimezone(timezone.utc) != issued_utc
        or not issued_utc < fresh_until_utc
        or (fresh_until_utc - issued_utc).total_seconds() > 600
        or issued_utc > current + timedelta(seconds=30)
        or current > fresh_until_utc
    ):
        raise RcValidationError("RC_CANARY_RECEIPT_INVALID: freshness")
    if not isinstance(value.get("candidate_goal_digest"), str) or not re.fullmatch(
        r"[0-9a-f]{64}", value["candidate_goal_digest"]
    ):
        raise RcValidationError("RC_CANARY_RECEIPT_INVALID: candidate_goal_digest")
    provenance = dict(value)
    claimed_provenance = provenance.pop("provenance_digest", None)
    claimed_host = provenance.pop("host_receipt_digest", None)
    expected_provenance = _domain_digest(CANARY_PROVENANCE_DOMAIN, provenance)
    if claimed_provenance != expected_provenance:
        raise RcValidationError("RC_CANARY_RECEIPT_INVALID: provenance_digest")


def _live_canary_observation(
    root: Path,
    candidate: str,
    store_root: Path,
) -> dict[str, Any]:
    scripts = root / "codex-loop-prompt-architect" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        from loop_architect.v4_alpha.protocol import snapshot_digest
        from loop_architect.v4_entry.service import STORE_FILENAME
        from loop_architect.v4_persistence.sqlite_store import SQLiteStore
    except ImportError as exc:
        raise RcValidationError("RC_CANARY_LIVE_RUNTIME_UNAVAILABLE") from exc

    evidence_root = store_root.parent
    workspace = evidence_root / "workspace"
    output = workspace / CANARY_OUTPUT_FILENAME
    try:
        workspace_metadata = workspace.lstat()
        entries = list(workspace.iterdir())
        output_metadata = output.lstat()
        if (
            workspace.is_symlink()
            or not workspace.is_dir()
            or workspace_metadata.st_uid != os.getuid()
            or workspace_metadata.st_mode & 0o077
            or len(entries) != 1
            or entries[0].name != CANARY_OUTPUT_FILENAME
            or stat.S_ISLNK(output_metadata.st_mode)
            or not stat.S_ISREG(output_metadata.st_mode)
            or output_metadata.st_size != len(CANARY_OUTPUT_BYTES)
        ):
            raise OSError("invalid canary output")
        descriptor = os.open(output, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(descriptor)
            raw = os.read(descriptor, len(CANARY_OUTPUT_BYTES) + 1)
            if (
                not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino)
                != (output_metadata.st_dev, output_metadata.st_ino)
                or raw != CANARY_OUTPUT_BYTES
            ):
                raise OSError("canary output changed during read")
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise RcValidationError("RC_CANARY_LIVE_OUTPUT_INVALID") from exc

    store_path = store_root / STORE_FILENAME
    if not store_path.is_file() or store_path.is_symlink():
        raise RcValidationError("RC_CANARY_LIVE_STORE_INVALID")
    with SQLiteStore(store_path) as store:
        store.verify_integrity()
        descriptors = store.loop_descriptors()
        if len(descriptors) != 1 or candidate not in descriptors[0]["goal"]:
            raise RcValidationError("RC_CANARY_LIVE_CANDIDATE_BINDING_INVALID")
        loop_ref = descriptors[0]["loop_ref"]
        snapshot = store.snapshot(loop_ref)
        if snapshot is None or len(snapshot["external_effects"]) != 1:
            raise RcValidationError("RC_CANARY_LIVE_STATE_INVALID")
        effect = next(iter(snapshot["external_effects"].values()))
        host_resource = snapshot["host_resources"].get(effect["host_resource_ref"])
        provider_id = None if host_resource is None else host_resource.get(
            "provider_resource_ref"
        )
        if not isinstance(provider_id, str) or not provider_id:
            raise RcValidationError("RC_CANARY_LIVE_HOST_IDENTITY_INVALID")
        results = list(snapshot["results"].values())
        reports = list(snapshot["reports"].values())
        reviews = list(snapshot["reviews"].values())
        finalizations = list(snapshot["finalizations"].values())
        artifacts = list(snapshot["artifacts"].values())
        if (
            len(results) != 1
            or results[0].get("state") != "ACKNOWLEDGED"
            or results[0].get("outcome") != "PASS"
            or len(reports) != 1
            or reports[0].get("state") != "ACCEPTED"
            or len(artifacts) != 1
            or artifacts[0].get("state") != "VERIFIED"
            or len(reviews) != 1
            or reviews[0].get("state") != "PASS"
            or len(finalizations) != 1
            or finalizations[0].get("state") != "EXECUTION_CLOSED"
            or snapshot["execution"].get("state") != "TERMINAL"
            or snapshot["execution"].get("disposition") != "SUCCEEDED"
            or snapshot["closure_assurance"].get("strength") != "STRICT"
        ):
            raise RcValidationError("RC_CANARY_LIVE_CLOSURE_INVALID")
        return {
            "artifact_state": artifacts[0]["state"],
            "assurance": snapshot["closure_assurance"]["strength"],
            "canary_output_sha256": CANARY_OUTPUT_SHA256,
            "candidate_goal_digest": descriptors[0]["goal_digest"],
            "candidate_sha": candidate,
            "execution_disposition": snapshot["execution"]["disposition"],
            "execution_state": snapshot["execution"]["state"],
            "finalization_state": finalizations[0]["state"],
            "host_task_identity_digest": _domain_digest(
                CANARY_HOST_ID_DOMAIN, provider_id
            ),
            "lifecycle_state": "TERMINAL",
            "result_digest": results[0]["source_observation_digest"],
            "result_outcome": results[0]["outcome"],
            "result_state": results[0]["state"],
            "report_state": reports[0]["state"],
            "review_state": reviews[0]["state"],
            "snapshot_digest": snapshot_digest(snapshot),
        }


def validate_live_canary(
    value: dict[str, Any],
    candidate: str,
    root: Path,
    store_root: Path,
) -> str:
    """Bind the receipt to the closed same-process transcript and local state."""
    validate_canary_receipt(value, candidate)
    observation = _live_canary_observation(root, candidate, store_root)
    digest = _domain_digest(CANARY_LIVE_DOMAIN, observation)
    if (
        value["host_receipt_digest"] != digest
        or value["host_task_identity_digest"]
        != observation["host_task_identity_digest"]
        or value["canary_output_sha256"] != observation["canary_output_sha256"]
        or value["host_result_digest"] != observation["result_digest"]
        or value["candidate_goal_digest"]
        != observation["candidate_goal_digest"]
    ):
        raise RcValidationError("RC_CANARY_LIVE_BINDING_INVALID")
    return digest


def validate_conformance_receipt(
    value: dict[str, Any],
    candidate: str,
    root: Path,
    *,
    expected_canary_sha256: str | None = None,
) -> None:
    if (
        value.get("artifact") != "loopskill-v4-conformance-execution-v2"
        or value.get("candidate_sha") != candidate
        or value.get("status") != "PASS"
        or value.get("case_count") != 349
        or value.get("mapped") != 349
        or value.get("semantic_coverage_mapping_count") != 349
        or value.get("passed_test_methods") != 74
        or value.get("failed") != 0
        or value.get("real_external_effects") != 1
        or value.get("canonical_case_ids") is not True
        or value.get("evidence_profile")
        != "SEMANTIC_MAPPINGS_TO_UNIQUE_EXECUTED_ASSERTIONS"
        or value.get("independent_case_observation_claimed") is not False
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
    if (
        not isinstance(test_results, list)
        or value.get("test_method_count") != len(test_results)
        or len(test_results) != 74
    ):
        raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
    tests_by_id: dict[str, dict[str, Any]] = {}
    for item in test_results:
        if not isinstance(item, dict):
            raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
        test_id = item.get("assertion_test_id")
        deterministic = {
            "assertion_test_id": test_id,
            "status": item.get("status"),
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
        contract = item.get("case_contract")
        if (
            item.get("status") != "COVERED_BY_PASSING_TEST"
            or item.get("coverage_mapping_count") != 1
            or not isinstance(family, str)
            or case_id != f"{family}-{parameter}"
            or test_id not in tests_by_id
            or test_id != target_test_id
            or item.get("target_test_result_digest") != tests_by_id[test_id]["result_digest"]
            or not isinstance(contract, dict)
            or contract.get("case_id") != case_id
            or contract.get("family") != family
            or contract.get("parameter") != parameter
            or contract.get("target_test_id") != target_test_id
            or contract.get("fixture_selector") != item.get("fixture_selector")
            or contract.get("expected_acceptance") != item.get("expected_acceptance")
            or contract.get("expected_effect_state") != item.get("expected_effect_state")
            or contract.get("replay_expectation") != item.get("replay_expectation")
            or item.get("case_contract_digest") != hashlib.sha256(_canonical(contract)).hexdigest()
        ):
            raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
        mapping = {
            "assertion_test_id": target_test_id,
            "case_id": case_id,
            "case_contract_digest": item["case_contract_digest"],
            "coverage_status": "COVERED_BY_PASSING_TEST",
            "family": family,
            "fixture_selector": item.get("fixture_selector"),
            "target_test_id": target_test_id,
            "target_test_result_digest": item.get("target_test_result_digest"),
        }
        if item.get("coverage_mapping_digest") != hashlib.sha256(
            _canonical(mapping)
        ).hexdigest():
            raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
        expected_kind = (
            "REAL_APP_RECEIPT+TEST_COVERAGE_MAPPING"
            if case_id in {"UX-009-a", "CAP-RELEASE-CANARY"}
            else "TEST_COVERAGE_MAPPING"
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
    if (
        set(tests_by_id) != {item["assertion_test_id"] for item in results}
        or value.get("passed_test_methods") != len(tests_by_id)
        or (
            expected_canary_sha256 is not None
            and canary_sha != expected_canary_sha256
        )
    ):
        raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
    if value.get("binding_manifest_digest") != hashlib.sha256(_canonical(binding_rows)).hexdigest():
        raise RcValidationError("RC_CONFORMANCE_RECEIPT_INVALID")
    claimed = value.get("case_results_digest")
    if claimed != hashlib.sha256(_canonical(results)).hexdigest():
        raise RcValidationError("RC_CONFORMANCE_RECEIPT_DIGEST_INVALID")


def _fault_contract_counts(root: Path) -> tuple[int, int, int]:
    scripts = root / "codex-loop-prompt-architect" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        from loop_architect.v4_alpha.store import FAULT_BOUNDARIES
        from loop_architect.v4_alpha.vertical import vertical_commands
        from loop_architect.v4_persistence.sqlite_store import (
            DURABLE_FAULT_BOUNDARIES,
        )
    except ImportError as exc:
        raise RcValidationError("RC_AUTHOR_PACKET_FAULT_CONTRACT_UNAVAILABLE") from exc
    return len(FAULT_BOUNDARIES), len(DURABLE_FAULT_BOUNDARIES), len(vertical_commands())


def validate_author_packet(
    value: dict[str, Any],
    candidate: str,
    root: Path,
    evidence_paths: Mapping[str, Path],
) -> dict[str, dict[str, Any]]:
    builder = _load_author_packet_builder(root)
    if (
        set(value)
        != {
            "artifact",
            "candidate_sha",
            "evidence_receipts",
            "packet_digest",
            "public_release_effects",
            "real_v3_loop_migrations",
            "status",
            "tracked_files",
        }
        or value.get("artifact") != builder.ARTIFACT
        or value.get("candidate_sha") != candidate
        or value.get("status") != builder.STATUS
        or value.get("public_release_effects") != 0
        or value.get("real_v3_loop_migrations") != 0
    ):
        raise RcValidationError("RC_AUTHOR_PACKET_INVALID")
    files = value.get("tracked_files")
    if not isinstance(files, dict) or set(files) != set(builder.REQUIRED_TRACKED_FILES):
        raise RcValidationError("RC_AUTHOR_PACKET_INCOMPLETE")
    for relative in builder.REQUIRED_TRACKED_FILES:
        expected = files.get(relative)
        if (
            not isinstance(expected, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected)
            or hashlib.sha256(_run(root, "git", "show", f"{candidate}:{relative}")).hexdigest()
            != expected
        ):
            raise RcValidationError(f"RC_AUTHOR_PACKET_FILE_DRIFT: {relative}")
    evidence = value.get("evidence_receipts")
    if (
        not isinstance(evidence, dict)
        or set(evidence) != set(builder.REQUIRED_EVIDENCE_RECEIPTS)
        or any(
            not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            for digest in evidence.values()
        )
    ):
        raise RcValidationError("RC_AUTHOR_PACKET_EVIDENCE_INVALID")
    if set(evidence_paths) != set(builder.REQUIRED_EVIDENCE_RECEIPTS):
        raise RcValidationError("RC_AUTHOR_PACKET_EVIDENCE_PATH_SET_INVALID")
    evidence_values: dict[str, dict[str, Any]] = {}
    try:
        for key in builder.REQUIRED_EVIDENCE_RECEIPTS:
            receipt_value, receipt_digest = builder._read_evidence(
                key, Path(evidence_paths[key]), candidate
            )
            builder.validate_evidence_receipt(key, receipt_value, candidate)
            if receipt_digest != evidence[key]:
                raise RcValidationError(
                    f"RC_AUTHOR_PACKET_EVIDENCE_DIGEST_MISMATCH: {key}"
                )
            evidence_values[key] = receipt_value
    except builder.AuthorPacketError as exc:
        raise RcValidationError(f"RC_AUTHOR_PACKET_EVIDENCE_INVALID: {exc}") from exc
    preflight = evidence_values["release_identity_preflight"]
    try:
        origin_main = _run(
            root, "git", "rev-parse", "refs/remotes/origin/main^{commit}"
        ).decode("ascii", "strict").strip()
        v3 = _run(root, "git", "rev-parse", "v3.3.8^{commit}").decode(
            "ascii", "strict"
        ).strip()
        paper = _run(
            root, "git", "rev-parse", "paper-treatment-v3.3.12^{commit}"
        ).decode("ascii", "strict").strip()
        _run(root, "git", "merge-base", "--is-ancestor", origin_main, candidate)
        local_v4_tag = _run(root, "git", "tag", "--list", "v4.0.0").strip()
    except UnicodeDecodeError as exc:
        raise RcValidationError("RC_AUTHOR_PACKET_PREFLIGHT_IDENTITY_INVALID") from exc
    if (
        preflight.get("origin_main_commit") != origin_main
        or preflight.get("v3_baseline_commit") != v3
        or preflight.get("paper_reference_commit") != paper
        or local_v4_tag
    ):
        raise RcValidationError("RC_AUTHOR_PACKET_PREFLIGHT_IDENTITY_DRIFT")

    in_memory_boundaries, sqlite_boundaries, operations = _fault_contract_counts(root)
    matrix = evidence_values["test_fault_matrix"]
    if (
        matrix.get("in_memory_boundary_count") != in_memory_boundaries
        or matrix.get("sqlite_boundary_count") != sqlite_boundaries
        or matrix.get("vertical_operation_count") != operations
        or matrix.get("vertical_fault_instance_count")
        != in_memory_boundaries * operations
    ):
        raise RcValidationError("RC_AUTHOR_PACKET_FAULT_CONTRACT_DRIFT")
    body = {key: item for key, item in value.items() if key != "packet_digest"}
    if value.get("packet_digest") != builder._packet_digest(body):
        raise RcValidationError("RC_AUTHOR_PACKET_DIGEST_INVALID")
    return evidence_values


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--canary-receipt", type=Path)
    parser.add_argument("--canary-store", type=Path)
    parser.add_argument("--conformance-receipt", type=Path)
    parser.add_argument("--author-packet", type=Path)
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--static-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        receipt = static_receipt(args.root, args.candidate, require_clean_head=True)
        exact_static_receipt = dict(receipt)
        exact_static_receipt["gate_status"] = "PRE_CANARY_STATIC_ONLY"
        exact_static_receipt.pop("receipt_digest", None)
        exact_static_receipt["receipt_digest"] = hashlib.sha256(
            _canonical(exact_static_receipt)
        ).hexdigest()
        if args.static_only:
            if (
                args.canary_receipt
                or args.canary_store
                or args.conformance_receipt
                or args.author_packet
                or args.evidence
            ):
                raise RcValidationError("RC_STATIC_ONLY_WITH_FINAL_RECEIPT")
            receipt["gate_status"] = "PRE_CANARY_STATIC_ONLY"
        else:
            if (
                not args.canary_receipt
                or not args.canary_store
                or not args.conformance_receipt
                or not args.author_packet
                or not args.evidence
            ):
                raise RcValidationError("RC_FINAL_RECEIPTS_REQUIRED")
            canary_raw = args.canary_receipt.read_bytes()
            canary = json.loads(canary_raw.decode("utf-8", "strict"))
            if canary_raw != _canonical(canary):
                raise RcValidationError("RC_CANARY_RECEIPT_NOT_CANONICAL")
            live_digest = validate_live_canary(
                canary,
                args.candidate,
                args.root,
                args.canary_store,
            )
            canary_digest = hashlib.sha256(canary_raw).hexdigest()
            receipt["canary_receipt_digest"] = canary_digest
            receipt["live_canary_attestation_digest"] = live_digest
            conformance_raw = args.conformance_receipt.read_bytes()
            conformance = json.loads(conformance_raw.decode("utf-8", "strict"))
            validate_conformance_receipt(
                conformance,
                args.candidate,
                args.root,
                expected_canary_sha256=canary_digest,
            )
            receipt["conformance_receipt_digest"] = hashlib.sha256(
                conformance_raw
            ).hexdigest()
            packet_raw = args.author_packet.read_bytes()
            packet = json.loads(packet_raw.decode("utf-8", "strict"))
            builder = _load_author_packet_builder(args.root)
            try:
                evidence_paths = builder.parse_evidence_assignments(
                    args.evidence, args.root.resolve(strict=True)
                )
            except builder.AuthorPacketError as exc:
                raise RcValidationError(
                    f"RC_AUTHOR_PACKET_EVIDENCE_ARGUMENT_INVALID: {exc}"
                ) from exc
            evidence_values = validate_author_packet(
                packet, args.candidate, args.root, evidence_paths
            )
            if (
                evidence_values["app_canary"] != canary
                or evidence_values["final_conformance"] != conformance
                or evidence_values["static_validation"] != exact_static_receipt
            ):
                raise RcValidationError("RC_AUTHOR_PACKET_PRIMARY_EVIDENCE_MISMATCH")
            receipt["author_packet_digest"] = hashlib.sha256(packet_raw).hexdigest()
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
