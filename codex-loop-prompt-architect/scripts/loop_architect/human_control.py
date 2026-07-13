"""Deterministic helpers for human steering and convergence evidence."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


SECRET_RE = re.compile(
    r"(?i)(?:bearer\s+|api[_-]?key\s*[=:]\s*|(?:access[_-]?|auth[_-]?)?token\s*[=:]\s*|password\s*[=:]\s*|secret\s*[=:]\s*)[^\s&]+"
)
SENSITIVE_URL_QUERY_RE = re.compile(
    r"(?i)([?&](?:token|access_token|api[_-]?key|key|secret|password|signature|sig)=)[^\s&#]+"
)
TIMESTAMP_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ][0-9:.+-]+Z?\b")
HOST_PORT_RE = re.compile(
    r"(?i)(?P<host>(?:https?://[a-z0-9.-]+|localhost|127\.0\.0\.1|"
    r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}|\[[0-9a-f:]+\])):"
    r"(?P<port>[1-9][0-9]{1,4})\b"
)
PID_RE = re.compile(r"\b(?:pid[ =:]*)\d+\b", re.IGNORECASE)
TEMP_PATH_RE = re.compile(r"/(?:private/)?(?:var/)?tmp/[A-Za-z0-9._/-]+")

VALIDATION_DIMENSIONS = (
    "functional",
    "regression",
    "static_quality",
    "compatibility",
    "security",
    "performance",
    "user_experience",
    "change_impact",
)


def scope_matches_path(scope: str, artifact_path: str) -> bool:
    """Match a concrete repo-relative path against the supported scope grammar."""

    scope_parts = PurePosixPath(scope).parts
    path_parts = PurePosixPath(artifact_path).parts
    if not any(
        part == "**" or any(char in part for char in "*?[")
        for part in scope_parts
    ):
        return bool(scope_parts) and path_parts[: len(scope_parts)] == scope_parts

    def matches(scope_index: int, path_index: int) -> bool:
        if scope_index == len(scope_parts):
            return path_index == len(path_parts)
        part = scope_parts[scope_index]
        if part == "**":
            return matches(scope_index + 1, path_index) or (
                path_index < len(path_parts)
                and matches(scope_index, path_index + 1)
            )
        return (
            path_index < len(path_parts)
            and fnmatch.fnmatchcase(path_parts[path_index], part)
            and matches(scope_index + 1, path_index + 1)
        )

    return matches(0, 0)


def canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def normalize_failure_lines(lines: Sequence[str]) -> list[str]:
    """Remove volatile and sensitive values without inventing error semantics."""

    normalized: list[str] = []
    for raw in lines:
        line = SECRET_RE.sub("<redacted-secret>", str(raw))
        line = SENSITIVE_URL_QUERY_RE.sub(r"\1<redacted-secret>", line)
        line = TIMESTAMP_RE.sub("<timestamp>", line)
        line = HOST_PORT_RE.sub(r"\g<host>:<port>", line)
        line = PID_RE.sub("pid=<pid>", line)
        line = TEMP_PATH_RE.sub("<temp-path>", line)
        line = " ".join(line.split())
        if line:
            normalized.append(line[:2048])
    return normalized


def build_failure_fingerprint(
    *,
    command: str,
    exit_code: int,
    output_lines: Sequence[str],
    failing_test_ids: Sequence[str],
    changed_files: Sequence[str],
    diff_digest: str,
    strategy_id: str,
    hypothesis_digest: str,
    raw_log_digest: str,
    regressed_test_ids: Sequence[str] = (),
) -> dict[str, Any]:
    normalized = normalize_failure_lines(output_lines)
    return {
        "command_digest": canonical_digest(command),
        "exit_code": exit_code,
        "normalized_lines_digest": canonical_digest(normalized),
        "failing_test_ids": sorted(set(failing_test_ids)),
        "adapter": "generic-v1",
        "error_class": "UNKNOWN",
        "error_location": "UNKNOWN",
        "changed_files": sorted(set(changed_files)),
        "diff_digest": diff_digest,
        "strategy_id": strategy_id,
        "hypothesis_digest": hypothesis_digest,
        "raw_log_digest": raw_log_digest,
        "previously_passing_tests_regressed": sorted(set(regressed_test_ids)),
    }


def classify_failure_progress(
    history: Sequence[Mapping[str, Any]],
    current: Mapping[str, Any],
    *,
    same_strategy_threshold: int,
    strategy_budget_exhausted: bool = False,
) -> str:
    if current.get("previously_passing_tests_regressed"):
        return "REGRESSION_INTRODUCED"
    if strategy_budget_exhausted:
        return "STRATEGY_EXHAUSTED"
    failure_fields = (
        "command_digest",
        "exit_code",
        "normalized_lines_digest",
        "failing_test_ids",
        "adapter",
        "error_class",
        "error_location",
    )
    deterministic_identity_fields = failure_fields + (
        "changed_files",
        "diff_digest",
    )
    same_failure = [
        item
        for item in history
        if all(item.get(field) == current.get(field) for field in failure_fields)
    ]
    same_identity = [
        item
        for item in same_failure
        if all(
            item.get(field) == current.get(field)
            for field in deterministic_identity_fields
        )
    ]
    consecutive_same_strategy = 0
    for item in reversed(history):
        if not all(
            item.get(field) == current.get(field)
            for field in deterministic_identity_fields
        ):
            break
        if (
            item.get("strategy_id") != current.get("strategy_id")
            or item.get("hypothesis_digest") != current.get("hypothesis_digest")
        ):
            break
        consecutive_same_strategy += 1
    if consecutive_same_strategy + 1 >= same_strategy_threshold:
        return "THRASHING_DETECTED"
    if same_failure:
        if same_identity or any(
            item.get("strategy_id") == current.get("strategy_id")
            and item.get("hypothesis_digest") == current.get("hypothesis_digest")
            for item in same_failure
        ):
            return "POSSIBLE_STRATEGY_REPEAT"
        return "SAME_FAILURE_NEW_STRATEGY"
    return "PROGRESSING"


def validate_review_surface(
    surface: Mapping[str, Any],
    allowed_scopes: Sequence[str],
    repo_root: str | Path | None = None,
) -> None:
    required_fields = {
        "required",
        "type",
        "artifact_path",
        "preview_url",
        "evidence_refs",
        "review_questions",
        "decision_gate_id",
    }
    allowed_fields = required_fields | {"reason"}
    missing = sorted(required_fields - set(surface))
    unknown = sorted(set(surface) - allowed_fields)
    if missing:
        raise ValueError(f"missing fields: {', '.join(missing)}")
    if unknown:
        raise ValueError(f"unknown fields: {', '.join(unknown)}")
    if not isinstance(surface.get("required"), bool):
        raise ValueError("required must be boolean")
    kind = surface.get("type")
    allowed_types = {
        "browser_preview",
        "screenshot",
        "markdown",
        "tabular_data",
        "pdf",
        "slides",
        "diff",
        "other_artifact",
        "NOT_APPLICABLE",
    }
    if kind not in allowed_types:
        raise ValueError("type is invalid")
    for field in ("evidence_refs", "review_questions"):
        value = surface.get(field)
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            raise ValueError(f"{field} must be a string array")
    if surface.get("required") and not (
        isinstance(surface.get("decision_gate_id"), str)
        and surface["decision_gate_id"].strip()
    ):
        raise ValueError("required surface needs decision_gate_id")
    if surface.get("required") and not (
        surface.get("artifact_path") or surface.get("preview_url")
    ):
        raise ValueError("required surface needs artifact_path or preview_url")
    if surface.get("required") and not surface.get("review_questions"):
        raise ValueError("required surface needs review_questions")
    decision_gate_id = surface.get("decision_gate_id")
    if decision_gate_id is not None and (
        not isinstance(decision_gate_id, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", decision_gate_id)
    ):
        raise ValueError("decision_gate_id must be a safe ID")
    if kind == "NOT_APPLICABLE":
        if surface.get("required"):
            raise ValueError("NOT_APPLICABLE cannot be required")
        if not surface.get("reason"):
            raise ValueError("NOT_APPLICABLE requires reason")
        return
    artifact_path = surface.get("artifact_path")
    if artifact_path is not None and not isinstance(artifact_path, str):
        raise ValueError("artifact_path must be string or null")
    if artifact_path:
        path = PurePosixPath(str(artifact_path))
        if path.is_absolute() or ".." in path.parts or ".codex-loop" in path.parts:
            raise ValueError("review surface path escapes scope")
        if not any(scope_matches_path(scope, str(path)) for scope in allowed_scopes):
            raise ValueError("review surface path is outside allowed scope")
        if repo_root is not None:
            try:
                root = Path(repo_root).expanduser().resolve(strict=False)
                resolved = (root / str(path)).resolve(strict=False)
            except (OSError, RuntimeError) as exc:
                raise ValueError("review surface symlink cannot be resolved") from exc
            try:
                resolved_relative = resolved.relative_to(root)
            except ValueError as exc:
                raise ValueError("review surface symlink escapes repo root") from exc
            resolved_path = resolved_relative.as_posix()
            if not any(
                scope_matches_path(scope, resolved_path)
                for scope in allowed_scopes
            ):
                raise ValueError("review surface symlink escapes allowed scope")
    url = surface.get("preview_url")
    if url is not None and not isinstance(url, str):
        raise ValueError("preview_url must be string or null")
    if url and ("@" in url or "token=" in url.lower() or "key=" in url.lower()):
        raise ValueError("review surface URL contains credentials")
    if url and not re.fullmatch(
        r"https?://(?:localhost|127\.0\.0\.1)(?::[0-9]{1,5})?(?:/[^?]*)?",
        url,
    ):
        raise ValueError("preview_url must be a query-free localhost URL")


def derive_validation_matrix(
    *, objective: str, validation_commands: Sequence[str], has_review_surface: bool
) -> dict[str, dict[str, Any]]:
    text = objective.lower()

    def contains_terms(english: Sequence[str], chinese: Sequence[str]) -> bool:
        return any(
            re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", text)
            for term in english
        ) or any(term in text for term in chinese)

    security = contains_terms(
        (
            "auth",
            "authz",
            "authentication",
            "authorization",
            "authorize",
            "access control",
            "permission",
            "secret",
            "crypto",
            "security",
            "secure",
            "hardening",
        ),
        ("认证", "授权", "权限", "密钥", "安全", "加固"),
    )
    performance = contains_terms(
        ("cache", "batch", "query", "performance", "loop", "hot path", "hot loop"),
        ("缓存", "批处理", "性能", "热路径", "热循环"),
    )
    compatibility = contains_terms(
        ("api", "schema", "cli", "generator"),
        ("协议", "生成器"),
    )
    ux = has_review_surface or contains_terms(
        ("ui", "frontend", "page"),
        ("页面", "交互", "文案"),
    )
    commands = list(validation_commands)
    matrix: dict[str, dict[str, Any]] = {}
    for name in VALIDATION_DIMENSIONS:
        required = name in {"functional", "regression", "static_quality", "change_impact"}
        required = required or (name == "security" and security)
        required = required or (name == "performance" and performance)
        required = required or (name == "compatibility" and compatibility)
        required = required or (name == "user_experience" and ux)
        if required:
            evidence = commands if name in {"functional", "regression", "static_quality"} else [f"{name} evidence"]
            matrix[name] = {"required": True, "evidence": evidence}
        else:
            matrix[name] = {"required": False, "reason": "risk trigger not present"}
    return matrix


def render_decision_card(decision: Mapping[str, Any]) -> str:
    """Render one canonical decision identity without adding authority."""

    options = "\n".join(
        f"{index}. {item['option_id']} - {item['option_effect']}"
        for index, item in enumerate(decision["options"], 1)
    )
    exclusions = ", ".join(decision.get("exclusions", [])) or "none"
    scope = json.dumps(
        decision.get("scope", {}), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return (
        "## 需要你决定\n\n"
        f"Decision ID: {decision['decision_id']}\n"
        f"Context digest: {decision['decision_context_digest']}\n"
        f"Valid state range: {decision['source_state_version']}..{decision['valid_through_state_version']}\n\n"
        f"请选择：\n{options}\n\n"
        f"授权范围：{scope}\n"
        f"明确不包含：{exclusions}\n"
        "未选择时：保持暂停或等待，不执行外部动作。\n"
    )
