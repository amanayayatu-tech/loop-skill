#!/usr/bin/env python3
"""Build the privacy-minimized, exact-SHA LoopSkill 4 author packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


ARTIFACT = "loopskill-v4-publication-packet-v2"
STATUS = "PUBLICATION_CANDIDATE_VALIDATED"
PACKET_DIGEST_DOMAIN = b"loopskill.v4.publication-packet.v2\0"
CANARY_CANDIDATE_PROVENANCE_DOMAIN = (
    b"loopskill.v4.exec-canary.candidate-provenance.v1\0"
)
MAX_EVIDENCE_BYTES = 1024 * 1024
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

# This is deliberately an exact, small public packet surface.  It is not a
# general archive of the repository or of local release logs.
REQUIRED_TRACKED_FILES = (
    "CHANGELOG.md",
    "LICENSE",
    "SECURITY.md",
    "VERSION",
    "docs/RELEASING.md",
    "docs/adr/0011-loopskill-4-compatible-kernel-refactor.md",
    "docs/adr/0013-content-addressed-plan-capacity.md",
    "docs/conformance/loopskill-4-conformance-corpus-design.md",
    "docs/v4/architecture-map.md",
    "docs/v4/compatibility-matrix-v4.1.md",
    "docs/v4/known-limitations.md",
    "docs/v4/migration-and-rollback.md",
    "docs/v4/quickstart.en.md",
    "docs/v4/quickstart.zh-CN.md",
    "docs/v4/rc-acceptance.md",
    "docs/v4/release-notes.md",
    "docs/v4/release-notes-v4.1.md",
    "protocol/v4/loopskill-v4.protocol.json",
)

REQUIRED_EVIDENCE_RECEIPTS = (
    "exec_canary_2_goal",
    "exec_canary_8_goal",
    "coverage",
    "distribution",
    "final_conformance",
    "hosted_conformance",
    "independent_review",
    "release_identity_preflight",
    "static_validation",
    "test_fault_matrix",
)

_SAFE_DERIVED_KEY_SUFFIXES = (
    "_available",
    "_changed",
    "_count",
    "_digest",
    "_effects",
    "_enabled",
    "_findings",
    "_preserved",
    "_retained",
    "_sha256",
    "_state",
    "_status",
    "_trust",
    "_used",
)
_RAW_IDENTITY_KEYS = {
    "cwd",
    "host_id",
    "host_identity",
    "host_task_id",
    "project_id",
    "projectless_root",
    "provider_id",
    "provider_resource_ref",
    "receipt_id",
    "resource_id",
    "host_resource_ref",
    "root",
    "task_id",
    "thread_id",
    "turn_id",
    "workspace",
    "worktree",
}
_FORBIDDEN_KEY_TOKENS = frozenset(
    {
        "credential",
        "credentials",
        "log",
        "logs",
        "password",
        "prompt",
        "secret",
        "secrets",
        "task",
        "thread",
        "token",
        "transcript",
        "turn",
    }
)
_PRIVATE_PATH_RE = re.compile(
    r"(?:(?<![A-Za-z0-9])/(?:Users|home|private|tmp|var/folders)(?:/|$)[^\s\"'<>]*"
    r"|~(?:/|$)|(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"'<>]*|file://[^\s\"'<>]*)"
)
_RAW_UUID_RE = re.compile(
    r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[1-8][0-9A-Fa-f]{3}-[89ABab][0-9A-Fa-f]{3}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f])"
)
_SECRET_TEXT_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
)

_EVIDENCE_ARTIFACTS = {
    "exec_canary_2_goal": "loopskill-v4-disposable-codex-exec-canary-v1",
    "exec_canary_8_goal": "loopskill-v4-disposable-codex-exec-canary-v1",
    "coverage": "loopskill-v4-coverage-receipt-v1",
    "distribution": "loopskill-v4-distribution-receipt-v1",
    "final_conformance": "loopskill-v4-conformance-execution-v2",
    "hosted_conformance": "loopskill-v4-hosted-conformance-v1",
    "independent_review": "loopskill-v4-independent-review-receipt-v1",
    "release_identity_preflight": "loopskill-v4-release-identity-preflight-v1",
    "static_validation": "loopskill-v4-publication-static-receipt-v1",
    "test_fault_matrix": "loopskill-v4-test-fault-matrix-receipt-v1",
}
_PROFILE_A = "SEMANTIC_MAPPINGS_TO_UNIQUE_EXECUTED_ASSERTIONS"


class AuthorPacketError(ValueError):
    """A fail-closed author-packet contract violation."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _packet_digest(body: Mapping[str, Any]) -> str:
    return hashlib.sha256(PACKET_DIGEST_DOMAIN + _canonical(body)).hexdigest()


def _run_git(root: Path, *args: str) -> bytes:
    try:
        completed = subprocess.run(
            ("git", *args),
            cwd=root,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AuthorPacketError("AUTHOR_PACKET_GIT_READ_FAILED") from exc
    return completed.stdout


def _validate_exact_candidate(root: Path, candidate: str) -> None:
    if not SHA_RE.fullmatch(candidate):
        raise AuthorPacketError("AUTHOR_PACKET_CANDIDATE_SHA_INVALID")
    try:
        top_level = Path(
            _run_git(root, "rev-parse", "--show-toplevel").decode("utf-8", "strict").strip()
        ).resolve(strict=True)
        resolved = _run_git(root, "rev-parse", f"{candidate}^{{commit}}").decode(
            "ascii", "strict"
        ).strip()
        head = _run_git(root, "rev-parse", "HEAD").decode("ascii", "strict").strip()
    except (UnicodeDecodeError, OSError) as exc:
        raise AuthorPacketError("AUTHOR_PACKET_GIT_IDENTITY_INVALID") from exc
    if top_level != root or resolved != candidate or head != candidate:
        raise AuthorPacketError("AUTHOR_PACKET_CANDIDATE_NOT_EXACT_HEAD")
    if _run_git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise AuthorPacketError("AUTHOR_PACKET_WORKTREE_NOT_CLEAN")


def _git_blob(root: Path, candidate: str, relative: str) -> bytes:
    try:
        return _run_git(root, "show", f"{candidate}:{relative}")
    except AuthorPacketError as exc:
        raise AuthorPacketError("AUTHOR_PACKET_REQUIRED_TRACKED_FILE_MISSING") from exc


def _strict_json_object(payload: bytes) -> dict[str, Any]:
    try:
        text = payload.decode("utf-8", "strict")

        def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_DUPLICATE_JSON_KEY")
                result[key] = value
            return result

        def reject_constant(_: str) -> None:
            raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_NONFINITE_NUMBER")

        value = json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except AuthorPacketError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_NOT_OBJECT")
    return value


def _is_safe_derived_key(key: str) -> bool:
    return key.endswith(_SAFE_DERIVED_KEY_SUFFIXES)


def _validate_evidence_privacy(value: Any) -> None:
    stack: list[tuple[Any, int]] = [(value, 0)]
    visited = 0
    while stack:
        current, depth = stack.pop()
        visited += 1
        if depth > 64 or visited > 100_000:
            raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_RESOURCE_BOUND")
        if isinstance(current, dict):
            for key, item in current.items():
                normalized = key.lower().replace("-", "_")
                tokens = frozenset(filter(None, normalized.split("_")))
                if (
                    normalized in _RAW_IDENTITY_KEYS
                    or normalized in {"path", "paths", "absolute_path", "file_path"}
                    or (
                        normalized.endswith(("_path", "_paths", "_root"))
                        and not _is_safe_derived_key(normalized)
                    )
                    or (
                        normalized.endswith(("_ref", "_refs"))
                        and not _is_safe_derived_key(normalized)
                    )
                    or (
                        "host" in tokens
                        and tokens.intersection({"id", "identity"})
                        and not _is_safe_derived_key(normalized)
                    )
                    or (
                        tokens.intersection(_FORBIDDEN_KEY_TOKENS)
                        and not _is_safe_derived_key(normalized)
                    )
                ):
                    raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_PRIVATE_KEY")
                stack.append((item, depth + 1))
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
        elif isinstance(current, str):
            if (
                current.startswith(("/", "~/", "file://"))
                or _PRIVATE_PATH_RE.search(current)
                or _RAW_UUID_RE.search(current)
                or any(pattern.search(current) for pattern in _SECRET_TEXT_PATTERNS)
            ):
                raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_PRIVATE_VALUE")


def _is_int(value: Any, *, minimum: int = 0) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= minimum


def _is_number(value: Any, *, minimum: float, maximum: float) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and minimum <= value <= maximum
    )


def _require_digest(value: Mapping[str, Any], field: str) -> None:
    current = value.get(field)
    if not isinstance(current, str) or not DIGEST_RE.fullmatch(current):
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_DIGEST_INVALID")


def _require_fields(value: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    if any(value.get(field) != required for field, required in expected.items()):
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_SEMANTICS_INVALID")


def _validate_exec_canary(
    value: Mapping[str, Any], *, expected_goal_count: int
) -> None:
    goal_count = value.get("host_task_create_count")
    if goal_count != expected_goal_count:
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_SEMANTICS_INVALID")
    _require_fields(
        value,
        {
            "app_restart_count": 0,
            "candidate_execution_mode": "CLEAN_GIT_WORKTREE",
            "confirmation_count": 1,
            "confirmation_digest_bound": True,
            "finalization": "ACKNOWLEDGED",
            "entry": "loopskill4",
            "host_lifecycle_readback_count": 1,
            "host_receipt_issuer": "codex-exec-jsonl-v1",
            "host_receipt_trust": "same-process-terminal-observed",
            "host_task_readback_count": goal_count,
            "intake_external_effects": 0,
            "intake_heartbeat_count": 0,
            "intake_host_task_count": 0,
            "intake_loop_count": 0,
            "loopskill_mcp_registration_count": 0,
            "machine_owned_identity": True,
            "manual_control_identity_count": 0,
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
            "unexpected_changed_input_count": 0,
            "v3_bytes_changed": 0,
        },
    )
    config_changed = value.get("observed_host_config_changed_bytes")
    allowed_count = value.get("allowed_host_managed_delta_count")
    delta_kind = value.get("host_config_delta_kind")
    if (
        value.get("observed_host_auth_changed_bytes") != 0
        or not _is_int(config_changed, minimum=0)
        or not _is_int(allowed_count, minimum=0)
        or (delta_kind, allowed_count, config_changed == 0)
        not in {
            ("NONE", 0, True),
            ("CODEX_WORKSPACE_TRUST_APPEND_V1", 1, False),
        }
    ):
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_SEMANTICS_INVALID")
    create_readbacks = value.get("host_create_readback_count")
    if (
        not _is_int(create_readbacks, minimum=1)
        or not goal_count <= create_readbacks <= 3 * goal_count
    ):
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_SEMANTICS_INVALID")
    terminal_readbacks = value.get("host_terminal_wait_readback_count")
    total_readbacks = value.get("host_total_read_count")
    if (
        not _is_int(terminal_readbacks, minimum=1)
        or terminal_readbacks != goal_count
        or not _is_int(total_readbacks, minimum=4)
        or total_readbacks
        != create_readbacks
        + terminal_readbacks
        + value["host_task_readback_count"]
        + value["host_lifecycle_readback_count"]
    ):
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_SEMANTICS_INVALID")
    for field in (
        "candidate_provenance_digest",
        "candidate_goal_digest",
        "canary_workspace_identity_digest",
        "canary_output_sha256",
        "host_receipt_digest",
        "host_auth_after_digest",
        "host_auth_before_digest",
        "host_config_after_digest",
        "host_config_before_digest",
        "integrity_measurement_digest",
        "host_result_digest",
        "host_task_identity_digest",
        "provenance_digest",
    ):
        _require_digest(value, field)
    tree = value.get("candidate_tree_sha")
    if not isinstance(tree, str) or not SHA_RE.fullmatch(tree):
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_SEMANTICS_INVALID")
    candidate_provenance = {
        "candidate_execution_mode": value["candidate_execution_mode"],
        "candidate_sha": value.get("candidate_sha"),
        "candidate_tree_sha": tree,
    }
    if value.get("candidate_provenance_digest") != hashlib.sha256(
        CANARY_CANDIDATE_PROVENANCE_DOMAIN + _canonical(candidate_provenance)
    ).hexdigest():
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_SEMANTICS_INVALID")


def _validate_exec_canary_2_goal(value: Mapping[str, Any]) -> None:
    _validate_exec_canary(value, expected_goal_count=2)


def _validate_exec_canary_8_goal(value: Mapping[str, Any]) -> None:
    _validate_exec_canary(value, expected_goal_count=8)


def _validate_canary_pair(values: Mapping[str, Mapping[str, Any]]) -> None:
    two = values["exec_canary_2_goal"]
    eight = values["exec_canary_8_goal"]
    try:
        two_observed = datetime.fromisoformat(
            str(two["observed_at"]).replace("Z", "+00:00")
        )
        eight_issued = datetime.fromisoformat(
            str(eight["issued_at"]).replace("Z", "+00:00")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthorPacketError(
            "AUTHOR_PACKET_CANARY_SEQUENCE_INVALID"
        ) from exc
    if (
        two_observed.tzinfo is None
        or eight_issued.tzinfo is None
        or two_observed > eight_issued
        or two["host_task_create_count"] + eight["host_task_create_count"] != 10
        or two.get("candidate_tree_sha") != eight.get("candidate_tree_sha")
        or two.get("candidate_provenance_digest")
        != eight.get("candidate_provenance_digest")
        or two.get("canary_workspace_identity_digest")
        == eight.get("canary_workspace_identity_digest")
        or two.get("host_task_identity_digest")
        == eight.get("host_task_identity_digest")
    ):
        raise AuthorPacketError("AUTHOR_PACKET_CANARY_SEQUENCE_INVALID")


def _validate_coverage(value: Mapping[str, Any]) -> None:
    _require_fields(value, {"status": "PASS"})
    covered = value.get("covered_branches")
    total = value.get("num_branches")
    percent = value.get("line_and_branch_percent")
    if (
        not _is_int(covered)
        or not _is_int(total, minimum=1)
        or covered > total
        or not _is_number(percent, minimum=80.0, maximum=100.0)
    ):
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_SEMANTICS_INVALID")


def _validate_distribution(value: Mapping[str, Any]) -> None:
    _require_fields(
        value,
        {
            "config_bytes_changed": 0,
            "mcp_entries_added": 0,
            "real_v3_loop_migrations": 0,
            "status": "PASS",
        },
    )
    if not _is_int(value.get("test_count"), minimum=1):
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_SEMANTICS_INVALID")
    _require_digest(value, "distribution_log_sha256")


def _validate_hosted_conformance(value: Mapping[str, Any]) -> None:
    _require_fields(
        value,
        {
            "case_count": 349,
            "deterministic_assertion_method_count": 74,
            "evidence_profile": _PROFILE_A,
            "independent_case_observation_claimed": False,
            "local_exact_sha_app_case_ids": ["CAP-RELEASE-CANARY", "UX-009-a"],
            "real_external_effects": 0,
            "semantic_coverage_mapping_count": 349,
            "status": "PASS_LOCAL_APP_GATE_REQUIRED",
        },
    )
    for field in (
        "case_catalog_digest",
        "corpus_sha256",
        "deterministic_assertion_results_digest",
        "semantic_coverage_mapping_digest",
    ):
        _require_digest(value, field)


def _validate_final_conformance(value: Mapping[str, Any]) -> None:
    _require_fields(
        value,
        {
            "canonical_case_ids": True,
            "bound_real_canary_count": 2,
            "bound_real_host_invocations": 10,
            "case_count": 349,
            "evidence_profile": _PROFILE_A,
            "failed": 0,
            "independent_case_observation_claimed": False,
            "mapped": 349,
            "passed_test_methods": 74,
            "real_external_effects": 0,
            "semantic_coverage_mapping_count": 349,
            "status": "PASS",
            "test_method_count": 74,
        },
    )
    case_results = value.get("case_results")
    test_results = value.get("test_method_results")
    if (
        not isinstance(case_results, list)
        or len(case_results) != 349
        or not isinstance(test_results, list)
        or len(test_results) != 74
    ):
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_SEMANTICS_INVALID")
    for field in (
        "binding_manifest_digest",
        "case_catalog_digest",
        "case_results_digest",
        "corpus_sha256",
    ):
        _require_digest(value, field)


def _validate_independent_review(value: Mapping[str, Any]) -> None:
    _require_fields(
        value,
        {"open_finding_count": 0, "review_scope_count": 8, "status": "PASS"},
    )
    _require_digest(value, "report_digest")


def _validate_release_identity_preflight(value: Mapping[str, Any]) -> None:
    _require_fields(
        value,
        {
            "feature_contains_origin_main": True,
            "public_release_effects": 0,
            "status": "PASS",
            "v4_release_exists": False,
            "v4_tag_exists": False,
        },
    )
    for field in (
        "origin_main_commit",
        "paper_reference_commit",
        "v3_baseline_commit",
    ):
        current = value.get(field)
        if not isinstance(current, str) or not SHA_RE.fullmatch(current):
            raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_SEMANTICS_INVALID")


def _validate_static_validation(value: Mapping[str, Any]) -> None:
    _require_fields(
        value,
        {
            "evidence_privacy_findings": [],
            "gate_status": "PRE_CANARY_STATIC_ONLY",
            "large_artifact_findings": [],
            "public_effects": 0,
            "publication_ready": False,
            "secret_findings": [],
            "stale_production_findings": [],
        },
    )
    if not _is_int(value.get("tracked_blob_count"), minimum=1):
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_SEMANTICS_INVALID")
    for field in ("receipt_digest", "sbom_sha256", "tracked_tree_digest"):
        _require_digest(value, field)
    archive = value.get("distribution_archive")
    if not isinstance(archive, dict) or archive.get("findings") != []:
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_SEMANTICS_INVALID")
    for field in ("archive_sha256", "file_manifest_digest"):
        _require_digest(archive, field)
    body = dict(value)
    claimed = body.pop("receipt_digest", None)
    if claimed != hashlib.sha256(_canonical(body)).hexdigest():
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_DIGEST_INVALID")


def _validate_test_fault_matrix(value: Mapping[str, Any]) -> None:
    _require_fields(
        value,
        {
            "in_memory_boundary_count": 3,
            "sqlite_boundary_count": 9,
            "status": "PASS",
            "vertical_fault_instance_count": 33,
            "vertical_operation_count": 11,
        },
    )
    if (
        not _is_int(value.get("full_test_count"), minimum=1)
        or value["vertical_fault_instance_count"]
        != value["in_memory_boundary_count"] * value["vertical_operation_count"]
    ):
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_SEMANTICS_INVALID")
    if "sqlite_fault_instance_count" in value and (
        value["sqlite_fault_instance_count"]
        != value["sqlite_boundary_count"] * value["vertical_operation_count"]
    ):
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_SEMANTICS_INVALID")
    _require_digest(value, "suite_log_sha256")


_EVIDENCE_VALIDATORS = {
    "exec_canary_2_goal": _validate_exec_canary_2_goal,
    "exec_canary_8_goal": _validate_exec_canary_8_goal,
    "coverage": _validate_coverage,
    "distribution": _validate_distribution,
    "final_conformance": _validate_final_conformance,
    "hosted_conformance": _validate_hosted_conformance,
    "independent_review": _validate_independent_review,
    "release_identity_preflight": _validate_release_identity_preflight,
    "static_validation": _validate_static_validation,
    "test_fault_matrix": _validate_test_fault_matrix,
}


def validate_evidence_receipt(
    key: str, value: Mapping[str, Any], candidate: str
) -> None:
    expected_artifact = _EVIDENCE_ARTIFACTS.get(key)
    validator = _EVIDENCE_VALIDATORS.get(key)
    if (
        expected_artifact is None
        or validator is None
        or value.get("artifact") != expected_artifact
        or value.get("candidate_sha") != candidate
    ):
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_TYPE_INVALID")
    validator(value)


def _read_evidence(
    key: str, path: Path, candidate: str
) -> tuple[dict[str, Any], str]:
    try:
        if path.is_symlink():
            raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_FILE_INVALID")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_EVIDENCE_BYTES:
                raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_FILE_INVALID")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                payload = stream.read(MAX_EVIDENCE_BYTES + 1)
        finally:
            os.close(descriptor)
    except AuthorPacketError:
        raise
    except OSError as exc:
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_FILE_INVALID") from exc
    if len(payload) > MAX_EVIDENCE_BYTES or len(payload) != metadata.st_size:
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_SIZE_INVALID")
    value = _strict_json_object(payload)
    if value.get("candidate_sha") != candidate:
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_CANDIDATE_MISMATCH")
    _validate_evidence_privacy(value)
    validate_evidence_receipt(key, value, candidate)
    return value, hashlib.sha256(payload).hexdigest()


def parse_evidence_assignments(assignments: Sequence[str], root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for assignment in assignments:
        key, separator, raw_path = assignment.partition("=")
        if not separator or not key or not raw_path or key in result:
            raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_ARGUMENT_INVALID")
        path = Path(raw_path)
        if not path.is_absolute():
            path = root / path
        result[key] = path
    if set(result) != set(REQUIRED_EVIDENCE_RECEIPTS):
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_SET_INVALID")
    return result


def build_packet(
    root: Path,
    candidate: str,
    evidence_paths: Mapping[str, Path],
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    _validate_exact_candidate(root, candidate)
    if set(evidence_paths) != set(REQUIRED_EVIDENCE_RECEIPTS):
        raise AuthorPacketError("AUTHOR_PACKET_EVIDENCE_SET_INVALID")

    tracked_files = {
        relative: hashlib.sha256(_git_blob(root, candidate, relative)).hexdigest()
        for relative in REQUIRED_TRACKED_FILES
    }
    if set(tracked_files) != set(REQUIRED_TRACKED_FILES):  # defensive exact-closure check
        raise AuthorPacketError("AUTHOR_PACKET_TRACKED_FILE_SET_INVALID")

    evidence_receipts: dict[str, str] = {}
    evidence_values: dict[str, dict[str, Any]] = {}
    for key in REQUIRED_EVIDENCE_RECEIPTS:
        value, digest = _read_evidence(key, Path(evidence_paths[key]), candidate)
        evidence_values[key] = value
        evidence_receipts[key] = digest
    _validate_canary_pair(evidence_values)

    body: dict[str, Any] = {
        "artifact": ARTIFACT,
        "candidate_sha": candidate,
        "evidence_receipts": evidence_receipts,
        "public_release_effects": 0,
        "real_v3_loop_migrations": 0,
        "status": STATUS,
        "tracked_files": tracked_files,
    }
    packet = dict(body)
    packet["packet_digest"] = _packet_digest(body)
    if set(packet) != {
        "artifact",
        "candidate_sha",
        "evidence_receipts",
        "packet_digest",
        "public_release_effects",
        "real_v3_loop_migrations",
        "status",
        "tracked_files",
    }:
        raise AuthorPacketError("AUTHOR_PACKET_SHAPE_INVALID")
    return packet


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    try:
        root = args.root.resolve(strict=True)
        evidence = parse_evidence_assignments(args.evidence, root)
        packet = build_packet(root, args.candidate, evidence)
        payload = _canonical(packet)
        if args.output is None:
            sys.stdout.buffer.write(payload)
            sys.stdout.buffer.flush()
        else:
            _write_atomic(args.output, payload)
    except (AuthorPacketError, OSError) as exc:
        message = str(exc) if isinstance(exc, AuthorPacketError) else "AUTHOR_PACKET_IO_FAILED"
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
