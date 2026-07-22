#!/usr/bin/env python3
"""Unified preflight, compiler, canary verifier, and audit CLI for LoopSkill."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import os
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from loop_architect.recovery_registry import recovery_for, registry_document
from loop_architect.rejection_journal import read_rejections
from loop_architect.capability_envelope import (
    CapabilityEnvelope,
    CapabilityEnvelopeError,
)
from loop_architect.p1_runtime import privacy_safe_export
from loop_architect.archive_manifest_v2 import (
    ArchiveManifestError,
    build_manifest,
    write_manifest,
)
from loop_architect.risky_artifact_scanner import scan, unallowed_credentials


SKILL_NAME = "codex-loop-prompt-architect"
COMPILED_MANIFEST_VERSION = "loop-compiled-manifest-v1"
DOCTOR_RECEIPT_VERSION = "loop-doctor-receipt-v1"
CANARY_RECEIPT_VERSION = "loop-disposable-canary-v1"
CANARY_STAGES = (
    "INITIALIZE",
    "ROLE_RECEIPT",
    "HEARTBEAT",
    "ROUTE",
    "SEND",
    "STAGE",
    "ACK",
    "REVIEW",
    "REPAIR",
    "CLOSEOUT",
    "TRANSPORT_RECOVERY",
    "FINALIZATION",
)
MCP_LIFECYCLE_CAPABILITIES = (
    "install",
    "server_restart",
    "client_reconnect",
    "schema_refresh",
    "app_refresh",
)
PROJECT_DIR = Path(__file__).resolve().parents[1]
HEARTBEAT_RRULE_RE = re.compile(
    r"(?:FREQ=MINUTELY;INTERVAL=[1-9][0-9]{0,3}|"
    r"FREQ=HOURLY(?:;INTERVAL=[1-9][0-9]{0,3})?)\Z"
)
DIGEST_RE = re.compile(r"sha256:[a-f0-9]{64}\Z")


class LoopctlError(ValueError):
    def __init__(self, code: str, path: str = "/", details: Any = None) -> None:
        super().__init__(code)
        self.code = code
        self.path = path
        self.details = details if details is not None else {}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Any) -> str:
    payload = value if isinstance(value, bytes) else _canonical(value)
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _read_document(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LoopctlError("INPUT_UNAVAILABLE", "/input", {"path": str(path)}) from exc
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            value = json.loads(text)
        elif suffix in {".yaml", ".yml"}:
            value = importlib.import_module("yaml").safe_load(text)
        elif suffix == ".toml":
            try:
                toml = importlib.import_module("tomllib")
            except ModuleNotFoundError:
                toml = importlib.import_module("tomli")
            value = toml.loads(text)
        else:
            raise LoopctlError("INPUT_FORMAT_UNSUPPORTED", "/input")
    except LoopctlError:
        raise
    except (ValueError, TypeError) as exc:
        raise LoopctlError(
            "INPUT_DOCUMENT_INVALID", "/input", {"error_type": type(exc).__name__}
        ) from exc
    if not isinstance(value, dict):
        raise LoopctlError("INPUT_DOCUMENT_INVALID", "/input")
    return value


def _git(root: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _file_digest(path: Path) -> str | None:
    try:
        return _digest(path.read_bytes())
    except OSError:
        return None


def _tree_manifest_digest(root: Path) -> str | None:
    if not root.is_dir() or root.is_symlink():
        return None
    files: list[dict[str, Any]] = []
    try:
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if (
                any(part in {".DS_Store", "__pycache__"} for part in relative.parts)
                or path.suffix == ".pyc"
            ):
                continue
            if path.is_symlink():
                return None
            if path.is_file():
                files.append(
                    {
                        "path": relative.as_posix(),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "executable": bool(stat.S_IMODE(path.stat().st_mode) & 0o111),
                    }
                )
    except OSError:
        return None
    return hashlib.sha256(_canonical(files)).hexdigest() if files else None


def _verified_receipt(value: Any, *, schema_version: str, path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != schema_version:
        raise LoopctlError("HOST_RECEIPT_INVALID", path)
    claimed = value.get("receipt_digest")
    body = dict(value)
    body.pop("receipt_digest", None)
    if claimed != _digest(body):
        raise LoopctlError("HOST_RECEIPT_DIGEST_MISMATCH", f"{path}/receipt_digest")
    return value


def _identity_requirement(source: dict[str, Any]) -> dict[str, str]:
    values: dict[str, list[str]] = {"required_model": [], "required_reasoning": []}
    scopes = [source, *source.get("goals", [])]
    for field in values:
        for index, scope in enumerate(scopes):
            if not isinstance(scope, dict):
                continue
            value = scope.get(field, "UNSPECIFIED")
            if not isinstance(value, str) or not value:
                raise LoopctlError("MODEL_IDENTITY_POLICY_INVALID", f"/{field}/{index}")
            if value != "UNSPECIFIED":
                values[field].append(value)
        if len(set(values[field])) > 1:
            raise LoopctlError("MODEL_IDENTITY_POLICY_CONFLICT", f"/{field}")
    required_model = values["required_model"][0] if values["required_model"] else "UNSPECIFIED"
    required_reasoning = (
        values["required_reasoning"][0]
        if values["required_reasoning"]
        else "UNSPECIFIED"
    )
    return {
        "model_identity_requirement": (
            "REQUIRED"
            if required_model != "UNSPECIFIED" or required_reasoning != "UNSPECIFIED"
            else "NOT_REQUIRED"
        ),
        "required_model": required_model,
        "required_reasoning": required_reasoning,
    }


def _validate_role_receipts(
    roles: list[Any], *, required_model: str, required_reasoning: str
) -> None:
    seen: set[tuple[str, str]] = set()
    for index, role in enumerate(roles):
        path = f"/roles/{index}"
        if not isinstance(role, dict):
            raise LoopctlError("ROLE_RECEIPT_INVALID", path)
        receipt = _verified_receipt(
            role.get("host_receipt"),
            schema_version="host-role-model-receipt-v1",
            path=f"{path}/host_receipt",
        )
        expected = {
            "role": role.get("role"),
            "model": role.get("model"),
            "reasoning": role.get("reasoning"),
        }
        if (
            receipt.get("issuer") != "CODEX_APP_HOST"
            or receipt.get("evidence_model") != "HOST_COOPERATIVE"
            or any(receipt.get(key) != value for key, value in expected.items())
            or not isinstance(receipt.get("task_id"), str)
            or not isinstance(receipt.get("thread_id"), str)
            or not isinstance(receipt.get("app_build"), str)
        ):
            raise LoopctlError("ROLE_RECEIPT_IDENTITY_MISMATCH", f"{path}/host_receipt")
        if (
            (required_model != "UNSPECIFIED" and receipt.get("model") != required_model)
            or (
                required_reasoning != "UNSPECIFIED"
                and receipt.get("reasoning") != required_reasoning
            )
        ):
            raise LoopctlError("ROLE_RECEIPT_IDENTITY_MISMATCH", f"{path}/host_receipt")
        identity = (receipt["task_id"], receipt["thread_id"])
        if identity in seen:
            raise LoopctlError("ROLE_RECEIPT_REPLAY", f"{path}/host_receipt")
        seen.add(identity)


def _latest_json(directory: Path) -> Path | None:
    if not directory.is_dir():
        return None
    candidates = sorted(directory.glob("*.json"), key=lambda item: item.stat().st_mtime)
    return candidates[-1] if candidates else None


def run_doctor(
    *,
    source: Path = PROJECT_DIR,
    codex_home: Path | None = None,
    target: str = "local",
    host_receipt_path: Path | None = None,
    model_identity_requirement: str = "NOT_REQUIRED",
    write_cache: bool = True,
) -> dict[str, Any]:
    if model_identity_requirement not in {"NOT_REQUIRED", "REQUIRED"}:
        raise LoopctlError("MODEL_IDENTITY_POLICY_INVALID", "/model_identity_requirement")
    source = source.expanduser().resolve(strict=False)
    codex_home = (codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))).expanduser().resolve(strict=False)
    checks: list[dict[str, Any]] = []
    remediations: list[str] = []
    missing_python_packages: list[str] = []

    def record(name: str, ok: bool, **details: Any) -> None:
        checks.append({"name": name, "ok": ok, **details})

    python_path = Path(sys.executable).resolve(strict=False)
    record(
        "python",
        python_path.is_absolute() and sys.version_info >= (3, 9),
        executable=str(python_path),
        version=".".join(str(value) for value in sys.version_info[:3]),
    )
    for module_name, package_name in (
        ("jsonschema", "jsonschema"),
        ("yaml", "PyYAML"),
    ):
        try:
            module = importlib.import_module(module_name)
            record(f"python_module:{module_name}", True, path=str(Path(module.__file__).resolve()))
        except (ModuleNotFoundError, AttributeError):
            record(f"python_module:{module_name}", False)
            missing_python_packages.append(package_name)
    try:
        toml = importlib.import_module("tomllib")
        toml_name = "tomllib"
    except ModuleNotFoundError:
        try:
            toml = importlib.import_module("tomli")
            toml_name = "tomli"
        except ModuleNotFoundError:
            toml = None
            toml_name = "tomli"
    record(
        "python_module:toml_reader",
        toml is not None,
        module=toml_name,
    )
    if toml is None:
        missing_python_packages.append("tomli")
    if missing_python_packages:
        runtime_venv = codex_home / "runtime" / SKILL_NAME
        packages = " ".join(dict.fromkeys(missing_python_packages))
        remediations.append(
            f'"{python_path}" -m venv "{runtime_venv}" && '
            f'"{runtime_venv / "bin" / "python"}" -m pip install {packages}'
        )

    git_root = _git(source, "rev-parse", "--show-toplevel")
    head = _git(source, "rev-parse", "HEAD")
    branch = _git(source, "branch", "--show-current")
    remote = _git(source, "remote", "get-url", "origin")
    dirty_text = _git(source, "status", "--porcelain=v1", "--untracked-files=all")
    record(
        "git",
        git_root is not None and head is not None,
        root=git_root,
        branch=branch or "DETACHED_HEAD",
        head=head,
        remote=remote,
        dirty=bool(dirty_text),
        worktree=str(source),
    )
    if git_root is None:
        remediations.append("Install Git and run doctor from a Git worktree.")

    installed = codex_home / "skills" / SKILL_NAME
    install_receipt = _latest_json(codex_home / "install-receipts" / SKILL_NAME)
    receipt: dict[str, Any] | None = None
    if install_receipt is not None:
        try:
            receipt = json.loads(install_receipt.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            receipt = None
    record(
        "install_receipt",
        receipt is not None,
        path=str(install_receipt) if install_receipt else None,
        manifest_digest=receipt.get("manifest_digest") if receipt else None,
    )
    if receipt is None:
        remediations.append(f"bash {source.parent / 'scripts' / 'install.sh'}")
    source_manifest = receipt.get("source_manifest_digest") if receipt else None
    installed_manifest = receipt.get("installed_manifest_digest") if receipt else None
    actual_source_manifest = _tree_manifest_digest(source)
    actual_installed_manifest = _tree_manifest_digest(installed)
    drift_free = bool(
        receipt
        and source_manifest == installed_manifest
        and actual_source_manifest == source_manifest
        and actual_installed_manifest == installed_manifest
        and receipt.get("source_install_drift") == []
        and installed.is_dir()
    )
    record(
        "source_install_manifest",
        drift_free,
        source_digest=source_manifest,
        installed_digest=installed_manifest,
        actual_source_digest=actual_source_manifest,
        actual_installed_digest=actual_installed_manifest,
        installed_path=str(installed),
    )

    config = codex_home / "config.toml"
    config_digest = _file_digest(config)
    registration = receipt.get("mcp_registration") if receipt else None
    registration_ok = bool(
        isinstance(registration, dict)
        and Path(registration.get("command", "")).is_absolute()
        and all(Path(arg).is_absolute() for arg in registration.get("args", []))
        and Path(registration.get("config_path", "")).expanduser().resolve(strict=False)
        == config
        and registration.get("config_readback") is True
    )
    record(
        "mcp_registration",
        registration_ok,
        command=registration.get("command") if isinstance(registration, dict) else None,
        args=registration.get("args") if isinstance(registration, dict) else None,
        config_digest=config_digest,
    )
    schema_paths = (
        source / "references" / "adaptive-state.schema.json",
        source / "references" / "adaptive-mutation.schema.json",
        source / "references" / "recovery-registry-v1.json",
    )
    schema_values = []
    schema_ok = True
    for path in schema_paths:
        try:
            schema_values.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            schema_ok = False
    schema_digest = _digest(schema_values) if schema_ok else None
    record("mcp_schema", schema_ok, digest=schema_digest)

    host_receipt: dict[str, Any] | None = None
    if host_receipt_path is not None:
        try:
            host_receipt = json.loads(host_receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            host_receipt = None
    host_receipt_digest_ok = False
    if isinstance(host_receipt, dict):
        claimed = host_receipt.get("receipt_digest")
        body = dict(host_receipt)
        body.pop("receipt_digest", None)
        host_receipt_digest_ok = claimed == _digest(body)
    lifecycle = host_receipt.get("mcp_lifecycle") if isinstance(host_receipt, dict) else None
    lifecycle_ok = bool(
        isinstance(lifecycle, dict)
        and all(lifecycle.get(name, {}).get("status") == "SUPPORTED" for name in MCP_LIFECYCLE_CAPABILITIES)
    )
    base_host_ok = bool(
        isinstance(host_receipt, dict)
        and host_receipt.get("schema_version") == "host-capability-receipt-v1"
        and host_receipt_digest_ok
        and isinstance(host_receipt.get("app_build"), str)
        and host_receipt.get("app_readback") is True
        and lifecycle_ok
        and host_receipt.get("heartbeat_readback") is True
    )
    model_identity_status = (
        "NOT_APPLICABLE"
        if model_identity_requirement == "NOT_REQUIRED"
        else (
            "VERIFIED"
            if base_host_ok and host_receipt.get("role_model_receipts") is True
            else "HOST_BLOCKED"
        )
    )
    host_ok = base_host_ok and model_identity_status != "HOST_BLOCKED"
    record(
        "host_capabilities",
        host_ok if target == "formal" else True,
        observed=host_receipt is not None,
        status="SUPPORTED" if host_ok else "UNSUPPORTED_BY_HOST",
        target=target,
        model_identity_requirement=model_identity_requirement,
        model_identity_status=model_identity_status,
    )

    identity = {
        "source_sha": head,
        "install_manifest_digest": receipt.get("manifest_digest") if receipt else None,
        "python": str(python_path),
        "python_version": sys.version,
        "config_digest": config_digest,
        "app_build": host_receipt.get("app_build") if host_receipt else None,
        "host_receipt_digest": (
            host_receipt.get("receipt_digest") if host_receipt else None
        ),
        "model_identity_requirement": model_identity_requirement,
        "mcp_schema_digest": schema_digest,
    }
    receipt_key = _digest(identity).removeprefix("sha256:")
    cache_path = codex_home / "doctor-receipts" / SKILL_NAME / f"{receipt_key}.json"
    cache_hit = cache_path.is_file()
    ok = all(item["ok"] for item in checks)
    result: dict[str, Any] = {
        "ok": ok,
        "status": "DOCTOR_PASS" if ok else "DOCTOR_FAILED",
        "schema_version": DOCTOR_RECEIPT_VERSION,
        "target": target,
        "identity": identity,
        "identity_digest": _digest(identity),
        "checks": checks,
        "remediations": list(dict.fromkeys(remediations)),
        "cache": {"hit": cache_hit, "path": str(cache_path)},
        "formal_ready": ok and host_ok,
        "model_identity_requirement": model_identity_requirement,
        "model_identity_status": model_identity_status,
    }
    if ok and write_cache and not cache_hit:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_name(f".{cache_path.name}.{os.getpid()}.tmp")
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, cache_path)
    return result


def compile_manifest(source: dict[str, Any]) -> dict[str, Any]:
    required = {"loop_id", "root", "controller", "roles", "goals", "heartbeat"}
    missing = sorted(required - set(source))
    if missing:
        raise LoopctlError("COMPILE_INPUT_INCOMPLETE", "/", {"missing": missing})
    root = source["root"]
    if not isinstance(root, str) or not Path(root).is_absolute():
        raise LoopctlError("COMPILE_ROOT_INVALID", "/root")
    if source.get("mode", "DISPOSABLE") not in {"DISPOSABLE", "FORMAL"}:
        raise LoopctlError("COMPILE_MODE_INVALID", "/mode")
    roles = source["roles"]
    goals = source["goals"]
    if not isinstance(roles, list) or not roles or not isinstance(goals, list) or not goals:
        raise LoopctlError("COMPILE_REGISTRY_EMPTY", "/roles")
    role_names = [item.get("role") for item in roles if isinstance(item, dict)]
    if set(role_names) != {"CONTROLLER", "WORKER", "REVIEWER"}:
        raise LoopctlError("COMPILE_ROLE_REGISTRY_INVALID", "/roles")
    identity_policy = _identity_requirement(source)
    identity_status = "NOT_APPLICABLE"
    if identity_policy["model_identity_requirement"] == "REQUIRED":
        if any(not isinstance(role, dict) or "host_receipt" not in role for role in roles):
            identity_status = "HOST_BLOCKED"
        else:
            _validate_role_receipts(
                roles,
                required_model=identity_policy["required_model"],
                required_reasoning=identity_policy["required_reasoning"],
            )
            identity_status = "VERIFIED"
    heartbeat = source["heartbeat"]
    required_heartbeat = {
        "automation_id", "target", "rrule", "prompt_digest", "purpose", "status"
    }
    if not isinstance(heartbeat, dict) or set(heartbeat) != required_heartbeat:
        raise LoopctlError("COMPILE_HEARTBEAT_INVALID", "/heartbeat")
    if (
        not isinstance(heartbeat["rrule"], str)
        or HEARTBEAT_RRULE_RE.fullmatch(heartbeat["rrule"]) is None
        or not isinstance(heartbeat["prompt_digest"], str)
        or DIGEST_RE.fullmatch(heartbeat["prompt_digest"]) is None
        or heartbeat["status"] not in {"ACTIVE", "PAUSED"}
    ):
        raise LoopctlError("COMPILE_HEARTBEAT_INVALID", "/heartbeat")
    compiled_goals = copy.deepcopy(goals)
    goal_ids: list[str] = []
    for goal in compiled_goals:
        if not isinstance(goal, dict) or not isinstance(goal.get("goal_id"), str):
            raise LoopctlError("COMPILE_GOAL_REGISTRY_INVALID", "/goals")
        goal_ids.append(goal["goal_id"])
        goal.setdefault("required_completion_class", "COMPLETE_ARTIFACT")
        goal.setdefault(
            "closeout_required", source.get("mode", "DISPOSABLE") == "FORMAL"
        )
    if len(goal_ids) != len(set(goal_ids)):
        raise LoopctlError("COMPILE_GOAL_REGISTRY_INVALID", "/goals")
    p1_source = source.get("p1", {"enabled": False})
    if not isinstance(p1_source, dict) or type(p1_source.get("enabled")) is not bool:
        raise LoopctlError("COMPILE_P1_CONFIG_INVALID", "/p1")
    p1_enabled = p1_source["enabled"]
    expected_p1_keys = (
        {"enabled", "supervisor_capability_envelope", "model_canaries"}
        if p1_enabled
        else {"enabled"}
    )
    if set(p1_source) != expected_p1_keys:
        raise LoopctlError("COMPILE_P1_CONFIG_INVALID", "/p1")
    supervisor_envelope = None
    model_canaries: dict[str, Any] = {}
    if p1_enabled:
        try:
            supervisor_envelope = CapabilityEnvelope.from_dict(
                p1_source["supervisor_capability_envelope"]
            ).to_dict()
        except (CapabilityEnvelopeError, KeyError, TypeError) as exc:
            raise LoopctlError(
                "COMPILE_SUPERVISOR_CAPABILITY_INVALID",
                "/p1/supervisor_capability_envelope",
            ) from exc
        raw_canaries = p1_source["model_canaries"]
        if not isinstance(raw_canaries, dict) or set(raw_canaries) != {
            "CONTROLLER", "WORKER", "REVIEWER"
        }:
            raise LoopctlError("COMPILE_MODEL_CANARY_INVALID", "/p1/model_canaries")
        for role, record in raw_canaries.items():
            if (
                not isinstance(record, dict)
                or set(record) != {"status", "task_digest", "result_digest"}
                or record.get("status") not in {"PASS", "FAIL", "UNMETERED"}
                or any(
                    value != "UNMETERED"
                    and (not isinstance(value, str) or DIGEST_RE.fullmatch(value) is None)
                    for value in (record.get("task_digest"), record.get("result_digest"))
                )
            ):
                raise LoopctlError(
                    "COMPILE_MODEL_CANARY_INVALID", f"/p1/model_canaries/{role}"
                )
            model_canaries[role] = copy.deepcopy(record)
        if source.get("mode", "DISPOSABLE") == "FORMAL" and any(
            record["status"] != "PASS" for record in model_canaries.values()
        ):
            raise LoopctlError("COMPILE_MODEL_CANARY_FAILED", "/p1/model_canaries")
        if source.get("mode", "DISPOSABLE") == "DISPOSABLE":
            if goal_ids != ["D0-control-plane-self-test"]:
                raise LoopctlError("COMPILE_CP0_REGISTRY_INVALID", "/goals")
        elif "D0-control-plane-self-test" in goal_ids:
            raise LoopctlError("COMPILE_GOAL_REGISTRY_INVALID", "/goals")
    compiled_roles = copy.deepcopy(roles)
    if identity_policy["model_identity_requirement"] == "NOT_REQUIRED":
        for role in compiled_roles:
            role["model"] = "UNSPECIFIED"
            role["reasoning"] = "UNSPECIFIED"
            role.pop("host_receipt", None)
    compiled = {
        "schema_version": COMPILED_MANIFEST_VERSION,
        "mode": source.get("mode", "DISPOSABLE"),
        "loop_id": source["loop_id"],
        "root": root,
        "git": source.get("git", {}),
        "controller": source["controller"],
        "registry": {"roles": compiled_roles, "goals": compiled_goals},
        "permissions": source.get(
            "permissions",
            {
                "controller": ["CONTROL_PLANE"],
                "worker": ["PRODUCT_SCOPE"],
                "reviewer": ["READ_ONLY_REVIEW"],
                "supervisor": [],
            },
        ),
        "heartbeat": copy.deepcopy(heartbeat),
        "recovery_registry": registry_document(),
        "completion_classes": [
            "COMPLETE_ARTIFACT",
            "COMPLETE_WITH_LIMITATION",
            "EMPIRICAL_RESULT_OBSERVED",
            "FORMAL_ACCEPTED",
            "PUBLIC_RELEASED",
        ],
        "host_requirements": {
            "role_model_receipts": identity_policy["model_identity_requirement"] == "REQUIRED",
            "heartbeat_readback": True,
            "mcp_lifecycle": list(MCP_LIFECYCLE_CAPABILITIES),
        },
        "model_identity_policy": {
            **identity_policy,
            "model_identity_status": identity_status,
        },
        "p1_runtime": {
            "enabled": p1_enabled,
            "supervisor_capability_envelope": supervisor_envelope,
            "model_canaries": model_canaries,
            "goal_registry": {
                "mode": source.get("mode", "DISPOSABLE"),
                "goal_ids": goal_ids,
                "migration_status": "LOCKED_UNTIL_SAFE_POINT",
            },
        },
        "formal_ready": identity_status != "HOST_BLOCKED",
        "canary_receipt": source.get("canary_receipt"),
        "source_digest": _digest(
            {key: value for key, value in source.items() if key != "canary_receipt"}
        ),
    }
    # The canary is a receipt over the compiled plan.  Exclude it from the
    # manifest identity so a later real-host receipt cannot create a digest
    # cycle or silently change the plan it claims to verify.
    body = dict(compiled)
    body.pop("canary_receipt", None)
    compiled["manifest_digest"] = _digest(body)
    return compiled


def verify_canary(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema_version") != COMPILED_MANIFEST_VERSION:
        raise LoopctlError("CANARY_MANIFEST_INVALID", "/schema_version")
    identity_policy = manifest.get("model_identity_policy", {})
    if (
        identity_policy.get("model_identity_requirement") == "REQUIRED"
        and identity_policy.get("model_identity_status") != "VERIFIED"
    ):
        raise LoopctlError("BLOCKED_BY_APP_ATTESTATION", "/model_identity_policy")
    receipt = manifest.get("canary_receipt")
    if not isinstance(receipt, dict):
        raise LoopctlError("CANARY_RECEIPT_REQUIRED", "/canary_receipt")
    if receipt.get("schema_version") != CANARY_RECEIPT_VERSION:
        raise LoopctlError("CANARY_RECEIPT_INVALID", "/canary_receipt/schema_version")
    if receipt.get("root_disposition") != "DISPOSABLE":
        raise LoopctlError("CANARY_ROOT_NOT_DISPOSABLE", "/canary_receipt/root_disposition")
    if receipt.get("manifest_digest") != manifest.get("manifest_digest"):
        raise LoopctlError("CANARY_MANIFEST_DIGEST_MISMATCH", "/canary_receipt/manifest_digest")
    lanes = receipt.get("lanes")
    if not isinstance(lanes, list):
        raise LoopctlError("CANARY_LANES_INVALID", "/canary_receipt/lanes")
    by_stage = {
        item.get("stage"): item
        for item in lanes
        if isinstance(item, dict) and isinstance(item.get("stage"), str)
    }
    if len(lanes) != len(CANARY_STAGES) or set(by_stage) != set(CANARY_STAGES):
        raise LoopctlError("CANARY_LANES_INVALID", "/canary_receipt/lanes")
    for stage in CANARY_STAGES:
        lane = by_stage.get(stage)
        if not isinstance(lane, dict) or lane.get("status") != "PASS":
            raise LoopctlError("CANARY_LANE_FAILED", f"/canary_receipt/lanes/{stage}")
        claimed = lane.get("receipt_digest")
        lane_body = dict(lane)
        lane_body.pop("receipt_digest", None)
        evidence = lane.get("evidence")
        if (
            not isinstance(claimed, str)
            or set(lane)
            != {"stage", "status", "manifest_digest", "evidence", "receipt_digest"}
            or not DIGEST_RE.fullmatch(claimed)
            or claimed != _digest(lane_body)
            or lane.get("manifest_digest") != manifest.get("manifest_digest")
            or not isinstance(evidence, dict)
            or set(evidence) != {"kind", "identity_digest"}
            or not isinstance(evidence.get("kind"), str)
            or not evidence["kind"]
            or not isinstance(evidence.get("identity_digest"), str)
            or not DIGEST_RE.fullmatch(evidence["identity_digest"])
        ):
            raise LoopctlError("CANARY_LANE_FAILED", f"/canary_receipt/lanes/{stage}")
    if receipt.get("final_status") != "FINALIZATION_ACKED":
        raise LoopctlError("CANARY_FINALIZATION_REQUIRED", "/canary_receipt/final_status")
    lifecycle = receipt.get("mcp_lifecycle")
    if not isinstance(lifecycle, dict):
        raise LoopctlError("CANARY_MCP_LIFECYCLE_REQUIRED", "/canary_receipt/mcp_lifecycle")
    for capability in MCP_LIFECYCLE_CAPABILITIES:
        value = lifecycle.get(capability)
        lifecycle_body = dict(value) if isinstance(value, dict) else {}
        lifecycle_digest = lifecycle_body.pop("receipt_digest", None)
        if (
            not isinstance(value, dict)
            or set(value)
            != {
                "status",
                "capability",
                "manifest_digest",
                "active_call_count_before",
                "active_call_count_after",
                "before_identity",
                "after_identity",
                "receipt_digest",
            }
            or value.get("capability") != capability
            or value.get("manifest_digest") != manifest.get("manifest_digest")
            or value.get("status") != "SUPPORTED"
            or value.get("active_call_count_before") != 0
            or value.get("active_call_count_after") != 0
            or not isinstance(value.get("before_identity"), str)
            or not value["before_identity"]
            or not isinstance(value.get("after_identity"), str)
            or not value["after_identity"]
            or not isinstance(lifecycle_digest, str)
            or not DIGEST_RE.fullmatch(lifecycle_digest)
            or lifecycle_digest != _digest(lifecycle_body)
        ):
            raise LoopctlError(
                "CANARY_MCP_LIFECYCLE_FAILED",
                f"/canary_receipt/mcp_lifecycle/{capability}",
            )
    negative = receipt.get("negative_evidence")
    if not isinstance(negative, list):
        raise LoopctlError("CANARY_NEGATIVE_EVIDENCE_REQUIRED", "/canary_receipt/negative_evidence")
    return {
        "ok": True,
        "status": "DISPOSABLE_CANARY_VERIFIED",
        "manifest_digest": manifest["manifest_digest"],
        "final_status": receipt["final_status"],
        "lane_count": len(CANARY_STAGES),
        "negative_evidence_count": len(negative),
        "formal_initialization_allowed": True,
        "model_identity_requirement": identity_policy.get(
            "model_identity_requirement", "NOT_REQUIRED"
        ),
        "model_identity_status": identity_policy.get(
            "model_identity_status", "NOT_APPLICABLE"
        ),
    }


def audit_root(root: Path) -> dict[str, Any]:
    control = root.expanduser().resolve(strict=False) / ".codex-loop"
    events_path = control / "LOOP_EVENTS.jsonl"
    accepted: list[dict[str, Any]] = []
    if events_path.exists():
        try:
            for line_number, line in enumerate(events_path.read_text(encoding="utf-8").splitlines(), 1):
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError
                accepted.append(
                    {
                        "kind": "ACCEPTED",
                        "timestamp": value.get("occurred_at") or value.get("timestamp"),
                        "sequence": line_number,
                        "record": value,
                    }
                )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise LoopctlError("AUDIT_EVENT_LOG_INVALID", "/LOOP_EVENTS.jsonl") from exc
    try:
        rejected_values = read_rejections(control / "LOOP_REJECTIONS.jsonl")
    except OSError as exc:
        raise LoopctlError("AUDIT_REJECTION_LOG_INVALID", "/LOOP_REJECTIONS.jsonl") from exc
    rejected = [
        {
            "kind": "REJECTED",
            "timestamp": item["timestamp"],
            "sequence": item["sequence"],
            "record": item,
        }
        for item in rejected_values
    ]
    timeline = sorted(
        [*accepted, *rejected],
        key=lambda item: (item.get("timestamp") or "", item["kind"], item["sequence"]),
    )
    return {
        "ok": True,
        "status": "AUDIT_COMPLETE",
        "root": str(root.expanduser().resolve(strict=False)),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "timeline": timeline,
    }


def export_metrics(root: Path) -> dict[str, Any]:
    """Return only the canonical aggregate measurement allowlist."""

    from loop_architect.state_runtime import AdaptiveStateRuntime

    state = AdaptiveStateRuntime(root.expanduser().resolve(strict=False)).read_state()
    if state is None:
        raise LoopctlError("METRICS_STATE_NOT_INITIALIZED", "/root")
    result = privacy_safe_export(state)
    audit = audit_root(root)
    mutation_types = [
        str(item.get("record", {}).get("mutation_type", ""))
        for item in audit["timeline"]
        if item.get("kind") == "ACCEPTED"
    ]
    result.update(
        accepted_count=audit["accepted_count"],
        rejected_count=audit["rejected_count"],
        human_intervention_count=sum(
            "DECISION" in mutation or "HUMAN" in mutation
            for mutation in mutation_types
        ),
        supervisor_intervention_count=sum(
            "SUPERVISOR" in mutation for mutation in mutation_types
        ),
    )
    digest_body = dict(result)
    digest_body.pop("export_digest", None)
    result["export_digest"] = _digest(digest_body)
    return {"ok": True, "status": "PRIVACY_SAFE_METRICS_EXPORTED", **result}


def archive_root(root: Path, reason: str) -> dict[str, Any]:
    """Build a v2 archive inventory without copying private payload bytes."""

    from loop_architect.state_runtime import AdaptiveStateRuntime

    resolved = root.expanduser().resolve(strict=False)
    state = AdaptiveStateRuntime(resolved).read_state()
    if state is None:
        raise LoopctlError("ARCHIVE_STATE_NOT_INITIALIZED", "/root")
    control = resolved / ".codex-loop"
    files: list[dict[str, Any]] = []
    for path in sorted(control.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        payload = path.read_bytes()
        files.append(
            {
                "digest": _digest(payload),
                "path": path.relative_to(resolved).as_posix(),
                "privacy_classification": "PRIVATE",
                "size": len(payload),
            }
        )
    outboxes = [
        {"kind": field, "id": outbox_id, "status": record.get("status")}
        for field in (
            "dispatch_outbox",
            "assurance_dispatch_outbox",
            "local_verification_outbox",
            "automation_outbox",
            "controller_goal_outbox",
            "thread_creation_outbox",
        )
        for outbox_id, record in state.get(field, {}).items()
    ]
    remote = _git(resolved, "remote", "get-url", "origin")
    manifest = build_manifest(
        reason=reason,
        root=str(resolved),
        git={
            "branch": _git(resolved, "branch", "--show-current"),
            "head": _git(resolved, "rev-parse", "HEAD"),
            "remote_configured": remote is not None,
            "remote_digest": _digest(remote.encode("utf-8")) if remote else None,
        },
        state={
            "schema_version": state.get("schema_version"),
            "state_version": state.get("state_version"),
            "terminal_status": state.get("terminal_status"),
        },
        events=[
            {
                "event_id": event_id,
                "mutation_type": record.get("mutation_type"),
                "state_version": record.get("applied_state_version"),
            }
            for event_id, record in sorted(state.get("event_ledger", {}).items())
        ],
        outboxes=outboxes,
        roles=[
            {
                "role": record.get("role"),
                "status": record.get("status"),
                "thread_digest": _digest(thread_id.encode("utf-8")),
            }
            for thread_id, record in sorted(state.get("thread_registry", {}).items())
        ],
        heartbeat={
            key: value
            for key, value in (state.get("heartbeat_prompt_identity") or {}).items()
            if key not in {"target_thread_id", "prompt"}
        },
        files=files,
        privacy_classification="PRIVATE",
    )
    return {"ok": True, "status": "ARCHIVE_MANIFEST_READY", "manifest": manifest}


def risk_scan_root(root: Path) -> dict[str, Any]:
    candidate = root.expanduser()
    if candidate.is_symlink() or not candidate.exists() or not candidate.is_dir():
        raise LoopctlError("RISK_SCAN_ROOT_INVALID", "/root")
    findings = scan(candidate.resolve(strict=True))
    unsafe = unallowed_credentials(findings)
    if unsafe:
        raise LoopctlError(
            "RISK_SCAN_CREDENTIAL_FOUND",
            "/root",
            {"finding_count": len(unsafe), "findings": unsafe},
        )
    return {
        "ok": True,
        "status": "RISK_SCAN_PASS",
        "finding_count": len(findings),
        "findings": findings,
    }


def _error(exc: LoopctlError) -> dict[str, Any]:
    recovery = recovery_for(exc.code)
    return {
        "ok": False,
        "status": exc.code,
        "error": {"code": exc.code, "path": exc.path, "details": exc.details},
        "recovery": recovery,
        "next_operation_template": copy.deepcopy(recovery["next_operation"]),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="loopctl")
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor")
    doctor.add_argument("--check", action="store_true")
    doctor.add_argument("--emit", action="store_true")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--source", type=Path, default=PROJECT_DIR)
    doctor.add_argument("--codex-home", type=Path)
    doctor.add_argument("--target", choices=("local", "formal"), default="local")
    doctor.add_argument("--host-receipt", type=Path)
    doctor.add_argument(
        "--model-identity-requirement",
        choices=("NOT_REQUIRED", "REQUIRED"),
        default="NOT_REQUIRED",
    )
    compile_command = subparsers.add_parser("compile")
    compile_command.add_argument("--input", required=True, type=Path)
    compile_command.add_argument("--check", action="store_true")
    compile_command.add_argument("--emit", type=Path)
    compile_command.add_argument("--json", action="store_true")
    canary = subparsers.add_parser("canary")
    canary.add_argument("--input", required=True, type=Path)
    canary.add_argument("--check", action="store_true")
    canary.add_argument("--emit", action="store_true")
    canary.add_argument("--json", action="store_true")
    audit = subparsers.add_parser("audit")
    audit.add_argument("--root", required=True, type=Path)
    audit.add_argument("--check", action="store_true")
    audit.add_argument("--emit", action="store_true")
    audit.add_argument("--json", action="store_true")
    metrics = subparsers.add_parser("metrics-export")
    metrics.add_argument("--root", required=True, type=Path)
    metrics.add_argument("--check", action="store_true")
    metrics.add_argument("--emit", action="store_true")
    metrics.add_argument("--json", action="store_true")
    archive = subparsers.add_parser("archive")
    archive.add_argument("--root", required=True, type=Path)
    archive.add_argument("--reason", required=True)
    archive.add_argument("--check", action="store_true")
    archive.add_argument("--emit", type=Path)
    archive.add_argument("--json", action="store_true")
    risk_scan = subparsers.add_parser("risk-scan")
    risk_scan.add_argument("--root", required=True, type=Path)
    risk_scan.add_argument("--check", action="store_true")
    risk_scan.add_argument("--emit", action="store_true")
    risk_scan.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "doctor":
            result = run_doctor(
                source=args.source,
                codex_home=args.codex_home,
                target=args.target,
                host_receipt_path=args.host_receipt,
                model_identity_requirement=args.model_identity_requirement,
            )
        elif args.command == "compile":
            result = compile_manifest(_read_document(args.input))
            # Legacy compile accepted --check together with --emit PATH.  Keep
            # that one-cycle compatibility surface while newer commands use
            # boolean --emit.
            if args.emit:
                args.emit.write_bytes(_canonical(result) + b"\n")
            result = {"ok": True, "status": "COMPILE_PASS", "compiled_manifest": result}
        elif args.command == "canary":
            result = verify_canary(_read_document(args.input))
        elif args.command == "audit":
            result = audit_root(args.root)
        elif args.command == "metrics-export":
            result = export_metrics(args.root)
        elif args.command == "archive":
            result = archive_root(args.root, args.reason)
            if args.emit and not args.check:
                try:
                    write_manifest(args.emit, result["manifest"])
                except ArchiveManifestError as exc:
                    raise LoopctlError(
                        "ARCHIVE_MANIFEST_WRITE_FAILED",
                        "/emit",
                        {"error_type": type(exc).__name__},
                    ) from exc
        else:
            result = risk_scan_root(args.root)
    except LoopctlError as exc:
        result = _error(exc)
    result.setdefault("cli_envelope_version", "loopctl-envelope-v1")
    result.setdefault("command", args.command)
    result.setdefault("mode", "CHECK" if getattr(args, "check", False) else "EMIT")
    result.setdefault("exit_code", 0 if result.get("ok") else 1)
    print(json.dumps(result, sort_keys=True) if getattr(args, "json", False) else result["status"])
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
