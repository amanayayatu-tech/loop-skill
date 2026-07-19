#!/usr/bin/env python3
"""Fail-closed planning, sharding, and final-gate helpers for Compatibility CI."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = 1
PLAN_NAME = "plan-v1.json"
INVENTORY_NAME = "inventory-v1.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
ALLOWED_CHANGE_STATUSES = {"A", "M"}
LIGHT_PATHS = {"README.md", "README.en.md"}
LIGHT_PATTERNS = ("docs/readme-assets/*.png",)
RELEASE_PATHS = {
    "CHANGELOG.md",
    "VERSION",
    "docs/RELEASING.md",
    "pyproject.toml",
    "requirements-test.txt",
    "scripts/check_release_identity.py",
    "scripts/check_whitespace_range.py",
    "scripts/install.sh",
    "codex-loop-prompt-architect/references/install-manifest.schema.json",
    "codex-loop-prompt-architect/scripts/validate_skill.py",
    "codex-loop-prompt-architect/scripts/verify_installation.py",
    "tests/test_app_canary_receipt.py",
    "tests/test_install_manifest.py",
    "tests/test_installer_contract.py",
    "tests/test_release_contract.py",
    "tests/test_release_identity.py",
    "tests/test_runtime_python_binding.py",
    "tests/test_whitespace_range.py",
}
STATE_TOKENS = (
    "adaptive-mutation",
    "adaptive-state",
    "control_plane",
    "control-plane",
    "finalization",
    "human_steering",
    "mcp",
    "mutation",
    "native_goal",
    "native-goal",
    "real_incident",
    "receipt",
    "recovery",
    "repair_exhaustion",
    "state",
)
GENERATOR_TOKENS = (
    "adaptive-loop",
    "adaptive_fuzz",
    "adaptive_loop",
    "digest_error",
    "forecast",
    "human_control",
    "loop-contract",
    "loop-intake",
    "loop_intake",
    "payload",
    "protocol",
    "public_schema",
    "renderer",
    "scaffold",
    "schema.py",
    "validation",
)
EXPECTED_GATE_JOBS = {
    "plan",
    "quick",
    "full",
    "fuzz-generator",
    "fuzz-state",
    "coverage",
    "install-linux",
    "macos-install",
    "tag-identity",
}
FUZZ_EXPECTATIONS = {
    "fuzz-generator": ("5000", "20260710"),
    "fuzz-state": ("5000", "20260711"),
}


class CompatibilityError(RuntimeError):
    """Raised when CI control data is malformed or incomplete."""


def _run_git(
    repo: Path,
    argv: Sequence[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *argv],
        cwd=repo,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _validate_sha(value: object, field: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise CompatibilityError(f"{field} must be a full hexadecimal Git object id")
    return value


def _commit_oid(repo: Path, value: str) -> str | None:
    result = _run_git(repo, ["rev-parse", "--verify", f"{value}^{{commit}}"], check=False)
    if result.returncode != 0:
        return None
    resolved = result.stdout.strip()
    return resolved if SHA_RE.fullmatch(resolved) else None


def _event_value(event: Mapping[str, Any], *path: str) -> object:
    current: object = event
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            raise CompatibilityError(f"event payload is missing {'.'.join(path)}")
        current = current[key]
    return current


def _changed_entries(repo: Path, base: str, head: str) -> list[dict[str, Any]]:
    if _commit_oid(repo, base) is None:
        raise CompatibilityError(f"pull request base is unavailable: {base}")
    if _commit_oid(repo, head) is None:
        raise CompatibilityError(f"pull request head is unavailable: {head}")
    merge_base_result = _run_git(repo, ["merge-base", base, head], check=False)
    merge_base = merge_base_result.stdout.strip()
    if merge_base_result.returncode != 0 or not SHA_RE.fullmatch(merge_base):
        raise CompatibilityError("pull request merge base is unavailable")
    result = subprocess.run(
        ["git", "diff", "--name-status", "-z", "--find-renames", f"{merge_base}...{head}"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    fields = result.stdout.decode("utf-8", errors="strict").split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    entries: list[dict[str, Any]] = []
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        path_count = 2 if status.startswith(("R", "C")) else 1
        if index + path_count > len(fields):
            raise CompatibilityError("git diff returned a truncated name-status record")
        paths = fields[index : index + path_count]
        index += path_count
        if not status or any(not path for path in paths):
            raise CompatibilityError("git diff returned an empty status or path")
        entries.append({"status": status, "paths": paths})
    if not entries:
        raise CompatibilityError("pull request diff is empty")
    return entries


def _is_light_path(path: str) -> bool:
    return path in LIGHT_PATHS or any(fnmatch.fnmatchcase(path, pattern) for pattern in LIGHT_PATTERNS)


def _is_release_path(path: str) -> bool:
    return path.startswith(".github/") or path in RELEASE_PATHS


def _is_state_path(path: str) -> bool:
    lowered = path.lower()
    return any(token in lowered for token in STATE_TOKENS)


def _is_generator_path(path: str) -> bool:
    lowered = path.lower()
    return any(token in lowered for token in GENERATOR_TOKENS)


def _is_known_standard_path(path: str) -> bool:
    return (
        path in LIGHT_PATHS
        or path == "SPEC.md"
        or path == "scripts/validate_spec.py"
        or path.startswith("docs/")
        or path.startswith("evidence/")
        or path.startswith("examples/")
        or path.startswith("tests/")
        or path.startswith("codex-loop-prompt-architect/references/")
    )


def _plan(
    *,
    tier: str,
    event_name: str,
    reasons: Sequence[str],
    base_sha: str = "",
    head_sha: str = "",
    merge_sha: str = "",
    entries: Sequence[Mapping[str, Any]] = (),
    run_full: bool,
    run_state_fuzz: bool,
    run_generator_fuzz: bool,
    run_install: bool,
    run_tag_identity: bool,
    run_quick: bool = True,
    main_proof: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "tier": tier,
        "event_name": event_name,
        "reasons": list(reasons),
        "base_sha": base_sha,
        "head_sha": head_sha,
        "merge_sha": merge_sha,
        "changed_entries": [dict(entry) for entry in entries],
        "run_quick": run_quick,
        "run_full": run_full,
        "run_state_fuzz": run_state_fuzz,
        "run_generator_fuzz": run_generator_fuzz,
        "run_install": run_install,
        "run_tag_identity": run_tag_identity,
        "main_proof": dict(main_proof or {"verified": False, "reason": "not-applicable"}),
    }


def _release_plan(
    event_name: str,
    reason: str,
    *,
    base_sha: str = "",
    head_sha: str = "",
    merge_sha: str = "",
    entries: Sequence[Mapping[str, Any]] = (),
    tag_identity: bool = False,
) -> dict[str, Any]:
    return _plan(
        tier="release",
        event_name=event_name,
        reasons=[reason],
        base_sha=base_sha,
        head_sha=head_sha,
        merge_sha=merge_sha,
        entries=entries,
        run_full=True,
        run_state_fuzz=True,
        run_generator_fuzz=True,
        run_install=True,
        run_tag_identity=tag_identity,
    )


def classify_entries(
    entries: Sequence[Mapping[str, Any]],
    *,
    event_name: str = "pull_request",
    base_sha: str = "",
    head_sha: str = "",
    merge_sha: str = "",
) -> dict[str, Any]:
    """Classify a validated PR diff. Unknown or structural changes fail closed."""

    if not entries:
        return _release_plan(event_name, "empty-change-set", base_sha=base_sha, head_sha=head_sha, merge_sha=merge_sha)
    normalized_paths: list[str] = []
    for entry in entries:
        status = str(entry.get("status", ""))
        paths = entry.get("paths", [])
        if status not in ALLOWED_CHANGE_STATUSES or not isinstance(paths, list) or len(paths) != 1:
            return _release_plan(
                event_name,
                f"structural-change:{status or '<empty>'}",
                base_sha=base_sha,
                head_sha=head_sha,
                merge_sha=merge_sha,
                entries=entries,
            )
        normalized_paths.append(str(paths[0]))
    if all(_is_light_path(path) for path in normalized_paths):
        return _plan(
            tier="light",
            event_name=event_name,
            reasons=[f"light-allowlist:{len(normalized_paths)}"],
            base_sha=base_sha,
            head_sha=head_sha,
            merge_sha=merge_sha,
            entries=entries,
            run_full=False,
            run_state_fuzz=False,
            run_generator_fuzz=False,
            run_install=False,
            run_tag_identity=False,
        )

    release_paths = [path for path in normalized_paths if _is_release_path(path)]
    if release_paths:
        return _release_plan(
            event_name,
            "release-path:" + ",".join(sorted(release_paths)),
            base_sha=base_sha,
            head_sha=head_sha,
            merge_sha=merge_sha,
            entries=entries,
        )

    state_paths = [path for path in normalized_paths if _is_state_path(path)]
    generator_paths = [path for path in normalized_paths if _is_generator_path(path)]
    known_paths = {
        path
        for path in normalized_paths
        if _is_known_standard_path(path) or _is_state_path(path) or _is_generator_path(path)
    }
    unknown_paths = sorted(set(normalized_paths).difference(known_paths))
    if unknown_paths:
        return _release_plan(
            event_name,
            "unknown-path:" + ",".join(unknown_paths),
            base_sha=base_sha,
            head_sha=head_sha,
            merge_sha=merge_sha,
            entries=entries,
        )
    reasons = [f"standard-change-set:{len(normalized_paths)}"]
    if state_paths:
        reasons.append(f"state-risk:{len(state_paths)}")
    if generator_paths:
        reasons.append(f"generator-risk:{len(generator_paths)}")
    return _plan(
        tier="standard",
        event_name=event_name,
        reasons=reasons,
        base_sha=base_sha,
        head_sha=head_sha,
        merge_sha=merge_sha,
        entries=entries,
        run_full=True,
        run_state_fuzz=bool(state_paths),
        run_generator_fuzz=bool(generator_paths),
        run_install=True,
        run_tag_identity=False,
    )


def build_plan(
    repo: Path,
    event_name: str,
    event: Mapping[str, Any],
    github_sha: str,
    manual_profile: str,
    main_proof: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a plan from a GitHub event, escalating malformed evidence to release."""

    safe_merge_sha = github_sha if SHA_RE.fullmatch(github_sha or "") else ""
    if event_name == "pull_request":
        base_raw = _event_value(event, "pull_request", "base", "sha") if "pull_request" in event else ""
        head_raw = _event_value(event, "pull_request", "head", "sha") if "pull_request" in event else ""
        base_display = base_raw if isinstance(base_raw, str) and SHA_RE.fullmatch(base_raw) else ""
        head_display = head_raw if isinstance(head_raw, str) and SHA_RE.fullmatch(head_raw) else ""
        try:
            base = _validate_sha(base_raw, "pull_request.base.sha")
            head = _validate_sha(head_raw, "pull_request.head.sha")
            merge = _validate_sha(github_sha, "GITHUB_SHA")
            entries = _changed_entries(repo, base, head)
        except (CompatibilityError, OSError, subprocess.SubprocessError, UnicodeError) as exc:
            return _release_plan(
                event_name,
                f"classification-error:{type(exc).__name__}:{exc}",
                base_sha=base_display,
                head_sha=head_display,
                merge_sha=safe_merge_sha,
            )
        return classify_entries(
            entries,
            event_name=event_name,
            base_sha=base,
            head_sha=head,
            merge_sha=merge,
        )

    if not safe_merge_sha:
        return _release_plan(event_name, "classification-error:invalid-GITHUB_SHA")

    if event_name == "workflow_dispatch":
        inputs = event.get("inputs", {})
        event_profile = inputs.get("profile") if isinstance(inputs, Mapping) else None
        profile = str(event_profile or manual_profile or "release")
        if profile == "quick":
            return _plan(
                tier="quick",
                event_name=event_name,
                reasons=["manual-profile:quick"],
                head_sha=safe_merge_sha,
                merge_sha=safe_merge_sha,
                run_full=False,
                run_state_fuzz=False,
                run_generator_fuzz=False,
                run_install=False,
                run_tag_identity=False,
            )
        if profile == "full":
            return _plan(
                tier="standard",
                event_name=event_name,
                reasons=["manual-profile:full"],
                head_sha=safe_merge_sha,
                merge_sha=safe_merge_sha,
                run_full=True,
                run_state_fuzz=False,
                run_generator_fuzz=False,
                run_install=True,
                run_tag_identity=False,
            )
        return _release_plan(event_name, f"manual-profile:{profile}", head_sha=safe_merge_sha, merge_sha=safe_merge_sha)

    if event_name == "schedule":
        return _release_plan(event_name, "scheduled-weekly-release-profile", head_sha=safe_merge_sha, merge_sha=safe_merge_sha)

    if event_name == "push":
        ref = event.get("ref", "")
        tag_identity = isinstance(ref, str) and ref.startswith("refs/tags/v")
        if tag_identity:
            if (
                isinstance(main_proof, Mapping)
                and main_proof.get("verified") is True
                and main_proof.get("head_sha") == safe_merge_sha
            ):
                return _plan(
                    tier="release",
                    event_name=event_name,
                    reasons=[f"tag-reuses-successful-main-run:{main_proof.get('run_id')}"],
                    head_sha=safe_merge_sha,
                    merge_sha=safe_merge_sha,
                    run_quick=False,
                    run_full=False,
                    run_state_fuzz=True,
                    run_generator_fuzz=True,
                    run_install=False,
                    run_tag_identity=True,
                    main_proof=main_proof,
                )
            return _release_plan(
                event_name,
                "tag-push-release-profile",
                head_sha=safe_merge_sha,
                merge_sha=safe_merge_sha,
                tag_identity=True,
            )
        return _plan(
            tier="standard",
            event_name=event_name,
            reasons=["main-push-full-without-fuzz"],
            head_sha=safe_merge_sha,
            merge_sha=safe_merge_sha,
            run_full=True,
            run_state_fuzz=False,
            run_generator_fuzz=False,
            run_install=True,
            run_tag_identity=False,
        )

    return _release_plan(event_name, f"unsupported-event:{event_name or '<empty>'}", head_sha=safe_merge_sha, merge_sha=safe_merge_sha)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompatibilityError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CompatibilityError(f"JSON root must be an object: {path}")
    return value


def _append_outputs(path: Path | None, values: Mapping[str, object]) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            if isinstance(value, bool):
                rendered = "true" if value else "false"
            else:
                rendered = str(value)
            if "\n" in rendered:
                raise CompatibilityError(f"GitHub output {key} contains a newline")
            handle.write(f"{key}={rendered}\n")


def _plan_markdown(plan: Mapping[str, Any]) -> str:
    reasons = ", ".join(str(reason) for reason in plan.get("reasons", []))
    return "\n".join(
        [
            "## Compatibility plan",
            "",
            f"- Tier: `{plan.get('tier', '<missing>')}`",
            f"- Event: `{plan.get('event_name', '<missing>')}`",
            f"- Reasons: {reasons or '<missing>'}",
            f"- Head SHA: `{plan.get('head_sha') or '<none>'}`",
            f"- Merge SHA: `{plan.get('merge_sha') or '<none>'}`",
            f"- Quick / full / generator fuzz / state fuzz / install / tag identity: "
            f"`{plan.get('run_quick')}` / `{plan.get('run_full')}` / `{plan.get('run_generator_fuzz')}` / "
            f"`{plan.get('run_state_fuzz')}` / `{plan.get('run_install')}` / "
            f"`{plan.get('run_tag_identity')}`",
            "",
        ]
    )


def _load_manifest(path: Path) -> dict[str, Any]:
    manifest = _load_json(path)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise CompatibilityError("test shard manifest schema_version must be 1")
    shards = manifest.get("shards")
    dedicated = manifest.get("dedicated_only")
    if not isinstance(shards, dict) or set(shards) != {"1", "2", "3", "4"}:
        raise CompatibilityError("test shard manifest must define shards 1 through 4")
    if not isinstance(dedicated, dict) or not dedicated:
        raise CompatibilityError("test shard manifest dedicated_only must be a non-empty object")
    return manifest


def _flatten_suite(suite: unittest.TestSuite) -> list[unittest.TestCase]:
    tests: list[unittest.TestCase] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            tests.extend(_flatten_suite(item))
        else:
            tests.append(item)
    return tests


def _module_test_data(repo: Path, modules: Sequence[str]) -> tuple[unittest.TestSuite, list[str]]:
    # Legacy discovery uses ``-s tests``.  Keep both import roots so modules that
    # intentionally share helpers such as ``state_runtime_support`` behave the
    # same way under the explicit shard runner.
    for import_root in (repo / "tests", repo):
        import_root_text = str(import_root)
        if import_root_text not in sys.path:
            sys.path.insert(0, import_root_text)
    combined = unittest.TestSuite()
    ids: list[str] = []
    for module in modules:
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromName(module)
        if loader.errors:
            raise CompatibilityError(f"cannot load {module}: {' | '.join(loader.errors)}")
        module_tests = _flatten_suite(suite)
        module_ids = [test.id() for test in module_tests]
        if len(module_ids) != len(set(module_ids)):
            raise CompatibilityError(f"module contains duplicate test ids: {module}")
        combined.addTests(module_tests)
        ids.extend(module_ids)
    return combined, ids


def build_inventory(repo: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = _load_manifest(manifest_path)
    shards = manifest["shards"]
    dedicated = manifest["dedicated_only"]
    actual_modules = {
        f"tests.{path.stem}" for path in (repo / "tests").glob("test_*.py") if path.is_file()
    }
    assigned: list[str] = []
    for modules in shards.values():
        if not isinstance(modules, list) or not all(isinstance(module, str) for module in modules):
            raise CompatibilityError("every shard must be a list of module names")
        assigned.extend(modules)
    assigned.extend(dedicated.keys())
    if len(assigned) != len(set(assigned)):
        raise CompatibilityError("a test module is assigned more than once")
    if set(assigned) != actual_modules:
        missing = sorted(actual_modules.difference(assigned))
        extra = sorted(set(assigned).difference(actual_modules))
        raise CompatibilityError(f"test module inventory mismatch missing={missing} extra={extra}")

    expected_counts = manifest.get("expected_shard_counts")
    if not isinstance(expected_counts, dict):
        raise CompatibilityError("expected_shard_counts must be an object")
    inventory_shards: dict[str, Any] = {}
    all_ids: set[str] = set()
    for shard, modules in shards.items():
        _, test_ids = _module_test_data(repo, modules)
        overlap = all_ids.intersection(test_ids)
        if overlap:
            raise CompatibilityError(f"test ids overlap across shards: {sorted(overlap)}")
        all_ids.update(test_ids)
        expected = expected_counts.get(shard)
        if expected != len(test_ids):
            raise CompatibilityError(f"shard {shard} expected {expected} tests but loaded {len(test_ids)}")
        inventory_shards[shard] = {
            "modules": modules,
            "test_count": len(test_ids),
            "test_ids": test_ids,
        }

    expected_total = manifest.get("expected_total_tests")
    if expected_total != len(all_ids):
        raise CompatibilityError(f"expected_total_tests={expected_total} but loaded {len(all_ids)}")
    dedicated_inventory: dict[str, Any] = {}
    for module, lane in dedicated.items():
        _, test_ids = _module_test_data(repo, [module])
        dedicated_inventory[module] = {"lane": lane, "test_count": len(test_ids), "test_ids": test_ids}
    return {
        "schema_version": SCHEMA_VERSION,
        "expected_total_tests": expected_total,
        "shards": inventory_shards,
        "dedicated_only": dedicated_inventory,
    }


def run_shard(
    repo: Path,
    manifest_path: Path,
    shard: str,
    tested_sha: str,
    output: Path,
) -> int:
    started = time.perf_counter()
    execution: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "shard": shard,
        "tested_sha": tested_sha,
        "successful": False,
        "modules": [],
        "test_ids": [],
        "expected_tests": 0,
        "tests_run": 0,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
    }
    try:
        expected_sha = _validate_sha(tested_sha, "tested_sha")
        actual_sha = _commit_oid(repo, "HEAD")
        if actual_sha != expected_sha:
            raise CompatibilityError(f"checkout SHA mismatch expected={expected_sha} actual={actual_sha}")
        inventory = build_inventory(repo, manifest_path)
        shard_data = inventory["shards"].get(shard)
        if not isinstance(shard_data, dict):
            raise CompatibilityError(f"unknown shard: {shard}")
        modules = shard_data["modules"]
        suite, test_ids = _module_test_data(repo, modules)
        execution.update(
            {
                "modules": modules,
                "test_ids": test_ids,
                "expected_tests": len(test_ids),
            }
        )
        result = unittest.TextTestRunner(verbosity=2, failfast=False, durations=20).run(suite)
        execution.update(
            {
                "successful": result.wasSuccessful(),
                "tests_run": result.testsRun,
                "failures": len(result.failures),
                "errors": len(result.errors),
                "skipped": len(result.skipped),
                "unexpected_successes": len(result.unexpectedSuccesses),
            }
        )
        returncode = 0 if result.wasSuccessful() and result.testsRun == len(test_ids) else 1
    except Exception as exc:  # The execution manifest must survive controlled runner failures.
        execution["runner_error"] = f"{type(exc).__name__}: {exc}"
        print(f"CI_SHARD_FAILED: {execution['runner_error']}", file=sys.stderr)
        returncode = 1
    finally:
        execution["duration_seconds"] = round(time.perf_counter() - started, 6)
        _write_json(output, execution)
    return returncode


def verify_shard_artifacts(
    repo: Path,
    manifest_path: Path,
    artifact_dir: Path,
    tested_sha: str,
) -> dict[str, Any]:
    expected_sha = _validate_sha(tested_sha, "tested_sha")
    inventory = build_inventory(repo, manifest_path)
    observed_ids: set[str] = set()
    shard_summaries: dict[str, Any] = {}
    for shard in ("1", "2", "3", "4"):
        path = artifact_dir / f".ci-shard-{shard}.json"
        execution = _load_json(path)
        expected = inventory["shards"][shard]
        if execution.get("schema_version") != SCHEMA_VERSION or execution.get("shard") != shard:
            raise CompatibilityError(f"invalid execution manifest identity for shard {shard}")
        if execution.get("tested_sha") != expected_sha:
            raise CompatibilityError(f"shard {shard} tested the wrong SHA")
        if execution.get("successful") is not True:
            raise CompatibilityError(f"shard {shard} did not report success")
        if execution.get("modules") != expected["modules"]:
            raise CompatibilityError(f"shard {shard} module list does not match the reviewed manifest")
        if execution.get("test_ids") != expected["test_ids"]:
            raise CompatibilityError(f"shard {shard} test ids do not match the canonical inventory")
        if execution.get("expected_tests") != expected["test_count"] or execution.get("tests_run") != expected["test_count"]:
            raise CompatibilityError(f"shard {shard} test count is incomplete")
        overlap = observed_ids.intersection(execution["test_ids"])
        if overlap:
            raise CompatibilityError(f"shard {shard} overlaps prior shards: {sorted(overlap)}")
        observed_ids.update(execution["test_ids"])
        coverage_files = sorted(path.name for path in artifact_dir.glob(f".coverage.shard-{shard}.*"))
        if not coverage_files:
            raise CompatibilityError(f"shard {shard} coverage data is missing")
        shard_summaries[shard] = {
            "test_count": expected["test_count"],
            "duration_seconds": execution.get("duration_seconds"),
            "coverage_files": coverage_files,
        }
    if len(observed_ids) != inventory["expected_total_tests"]:
        raise CompatibilityError("combined shard test ids do not equal the canonical inventory")
    return {
        "schema_version": SCHEMA_VERSION,
        "tested_sha": expected_sha,
        "total_tests": len(observed_ids),
        "shards": shard_summaries,
    }


def coverage_summary(
    coverage_json: Path,
    expected_minimum: float = 80.0,
    baseline: float | None = None,
    tolerance: float = 0.01,
) -> dict[str, Any]:
    data = _load_json(coverage_json)
    totals = data.get("totals")
    if not isinstance(totals, Mapping):
        raise CompatibilityError("coverage JSON is missing totals")
    percent = totals.get("percent_covered")
    if not isinstance(percent, (int, float)):
        raise CompatibilityError("coverage JSON percent_covered is missing")
    if float(percent) < expected_minimum:
        raise CompatibilityError(f"coverage {percent:.2f}% is below {expected_minimum:.2f}%")
    if baseline is not None and abs(float(percent) - baseline) > tolerance + 1e-9:
        raise CompatibilityError(
            f"coverage {percent:.2f}% differs from shadow baseline {baseline:.2f}% by more than {tolerance:.2f}pp"
        )
    return {
        "coverage_percent": f"{float(percent):.2f}",
        "coverage_baseline": "" if baseline is None else f"{baseline:.2f}",
        "coverage_delta_pp": "" if baseline is None else f"{float(percent) - baseline:+.2f}",
        "covered_lines": totals.get("covered_lines"),
        "num_statements": totals.get("num_statements"),
        "covered_branches": totals.get("covered_branches"),
        "num_branches": totals.get("num_branches"),
    }


def verify_successful_main_run(
    *, repository: str, workflow: str, tested_sha: str, token: str
) -> dict[str, Any]:
    """Return exact-SHA successful-main evidence, or a fail-closed negative result."""

    sha = _validate_sha(tested_sha, "tested_sha")
    negative: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "verified": False,
        "head_sha": sha,
        "reason": "successful-main-run-not-proven",
    }
    if not repository or not token:
        negative["reason"] = "repository-or-token-missing"
        return negative
    query = urllib.parse.urlencode(
        {"branch": "main", "event": "push", "status": "success", "head_sha": sha, "per_page": "20"}
    )
    workflow_id = urllib.parse.quote(Path(workflow).name, safe="")
    url = f"https://api.github.com/repos/{repository}/actions/workflows/{workflow_id}/runs?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "loop-skill-compatibility-ci",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        negative["reason"] = f"github-api-unavailable:{type(exc).__name__}"
        return negative
    runs = payload.get("workflow_runs") if isinstance(payload, Mapping) else None
    if not isinstance(runs, list):
        negative["reason"] = "github-api-response-invalid"
        return negative
    for run in runs:
        if not isinstance(run, Mapping):
            continue
        path = str(run.get("path", "")).lstrip("/")
        if (
            run.get("head_sha") == sha
            and run.get("head_branch") == "main"
            and run.get("event") == "push"
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
            and path == workflow
            and isinstance(run.get("id"), int)
        ):
            return {
                "schema_version": SCHEMA_VERSION,
                "verified": True,
                "head_sha": sha,
                "run_id": run["id"],
                "html_url": run.get("html_url", ""),
                "workflow_path": path,
                "reason": "exact-sha-successful-main-push",
            }
    return negative


def canonical_coverage(
    repo: Path,
    manifest_path: Path,
    artifact_dir: Path,
    tested_sha: str,
    *,
    mode: str,
    shard: str = "",
    minimum: float = 80.0,
    github_output: Path | None = None,
) -> dict[str, Any]:
    """Run or combine the exact canonical coverage contract used locally and in CI."""

    repo = repo.resolve()
    manifest_path = manifest_path.resolve()
    artifact_dir = artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    if mode == "all":
        generated = {
            artifact_dir / ".coverage",
            artifact_dir / "coverage.json",
            artifact_dir / "coverage.xml",
            artifact_dir / "coverage-evidence-v1.json",
            *(artifact_dir.glob(".coverage.shard-*")),
            *(artifact_dir.glob(".ci-shard-*.json")),
        }
        for candidate in generated:
            if candidate.is_dir() and not candidate.is_symlink():
                raise CompatibilityError(
                    f"canonical coverage generated path is a directory: {candidate.name}"
                )
            candidate.unlink(missing_ok=True)
    sha = _validate_sha(tested_sha, "tested_sha")
    if _commit_oid(repo, "HEAD") != sha:
        raise CompatibilityError("canonical coverage checkout SHA does not match tested_sha")
    if mode in {"all", "shard"}:
        selected = (shard,) if mode == "shard" else ("1", "2", "3", "4")
        if any(value not in {"1", "2", "3", "4"} for value in selected):
            raise CompatibilityError("canonical coverage shard must be 1 through 4")
        helper = repo / ".github" / "ci" / "compatibility.py"
        for value in selected:
            env = {
                **os.environ,
                "COVERAGE_FILE": str(artifact_dir / f".coverage.shard-{value}"),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            completed = subprocess.run(
                [
                    sys.executable,
                    "-W",
                    "error",
                    "-m",
                    "coverage",
                    "run",
                    "--parallel-mode",
                    str(helper),
                    "run-shard",
                    "--repo",
                    str(repo),
                    "--manifest",
                    str(manifest_path),
                    "--shard",
                    value,
                    "--tested-sha",
                    sha,
                    "--output",
                    str(artifact_dir / f".ci-shard-{value}.json"),
                ],
                cwd=repo,
                env=env,
            )
            if completed.returncode:
                raise CompatibilityError(f"canonical shard {value} failed")
        if mode == "shard":
            execution = _load_json(artifact_dir / f".ci-shard-{shard}.json")
            return {"tested_sha": sha, "shard": shard, "tests_run": execution.get("tests_run")}

    verified = verify_shard_artifacts(repo, manifest_path, artifact_dir, sha)
    data_file = artifact_dir / ".coverage"
    env = {**os.environ, "COVERAGE_FILE": str(data_file)}
    commands = (
        [sys.executable, "-m", "coverage", "combine", str(artifact_dir)],
        [sys.executable, "-m", "coverage", "report", "--fail-under=0"],
        [sys.executable, "-m", "coverage", "json", "--fail-under=0", "-o", str(artifact_dir / "coverage.json")],
        [sys.executable, "-m", "coverage", "xml", "--fail-under=0", "-o", str(artifact_dir / "coverage.xml")],
    )
    for command in commands:
        subprocess.run(command, cwd=repo, env=env, check=True)
    coverage_data = _load_json(artifact_dir / "coverage.json")
    summary = coverage_summary(artifact_dir / "coverage.json", expected_minimum=0)
    totals = coverage_data.get("totals", {})
    raw_percent = totals.get("percent_covered") if isinstance(totals, Mapping) else None
    if not isinstance(raw_percent, (int, float)):
        raise CompatibilityError("coverage JSON raw percent_covered is missing")
    files = coverage_data.get("files", {})
    top_uncovered: list[dict[str, Any]] = []
    if isinstance(files, Mapping):
        for path, data in files.items():
            file_summary = data.get("summary", {}) if isinstance(data, Mapping) else {}
            missing_lines = int(file_summary.get("missing_lines", 0) or 0)
            missing_branches = int(file_summary.get("missing_branches", 0) or 0)
            top_uncovered.append(
                {
                    "path": path,
                    "missing_lines": missing_lines,
                    "missing_branches": missing_branches,
                    "missing_units": missing_lines + missing_branches,
                    "percent_covered": file_summary.get("percent_covered"),
                }
            )
    top_uncovered.sort(key=lambda item: (-item["missing_units"], item["path"]))
    evidence = {
        "schema_version": SCHEMA_VERSION,
        "tested_sha": sha,
        "total_tests": verified["total_tests"],
        "shards": verified["shards"],
        **summary,
        "coverage_percent_raw": raw_percent,
        "minimum_percent": minimum,
        "gate_passed": float(raw_percent) >= minimum,
        "top_uncovered_files": top_uncovered[:10],
    }
    _write_json(artifact_dir / "coverage-evidence-v1.json", evidence)
    _append_outputs(
        github_output,
        {"total_tests": verified["total_tests"], "coverage_percent": f"{float(raw_percent):.6f}"},
    )
    print(
        "CANONICAL_COVERAGE "
        f"tests={verified['total_tests']} "
        + " ".join(f"shard_{key}={value['test_count']}" for key, value in verified["shards"].items())
        + f" lines={summary['covered_lines']}/{summary['num_statements']}"
        + f" branches={summary['covered_branches']}/{summary['num_branches']}"
        + f" coverage={float(raw_percent):.6f}%"
    )
    print("CANONICAL_TOP_UNCOVERED")
    for item in evidence["top_uncovered_files"]:
        print(
            f"  {item['path']} missing_lines={item['missing_lines']} "
            f"missing_branches={item['missing_branches']} "
            f"coverage={float(item['percent_covered'] or 0):.2f}%"
        )
    if not evidence["gate_passed"]:
        raise CompatibilityError(
            f"coverage {float(raw_percent):.6f}% is below {minimum:.2f}%"
        )
    return evidence


def gate_report(plan: Mapping[str, Any], needs: Mapping[str, Any]) -> tuple[list[str], str]:
    errors: list[str] = []
    if plan.get("schema_version") != SCHEMA_VERSION:
        errors.append("plan schema_version is not 1")
    if plan.get("tier") not in {"light", "quick", "standard", "release"}:
        errors.append("plan tier is missing or invalid")
    if not isinstance(plan.get("reasons"), list) or not plan.get("reasons"):
        errors.append("plan reasons are missing")
    for field in (
        "run_quick",
        "run_full",
        "run_state_fuzz",
        "run_generator_fuzz",
        "run_install",
        "run_tag_identity",
    ):
        if not isinstance(plan.get(field), bool):
            errors.append(f"plan {field} is missing or invalid")
    event_name = plan.get("event_name")
    sha_fields = ("base_sha", "head_sha", "merge_sha") if event_name == "pull_request" else ("head_sha", "merge_sha")
    for field in sha_fields:
        if not isinstance(plan.get(field), str) or not SHA_RE.fullmatch(str(plan.get(field, ""))):
            errors.append(f"plan {field} is missing or invalid")
    expected_total_tests = plan.get("expected_total_tests")
    if (
        not isinstance(expected_total_tests, int)
        or isinstance(expected_total_tests, bool)
        or expected_total_tests <= 0
    ):
        errors.append("plan expected_total_tests is missing or invalid")
    missing_jobs = sorted(EXPECTED_GATE_JOBS.difference(needs))
    if missing_jobs:
        errors.append(f"needs JSON is missing jobs: {missing_jobs}")
    expected_results = {
        "plan": "success",
        "quick": "success" if plan.get("run_quick") is True else "skipped",
        "full": "success" if plan.get("run_full") is True else "skipped",
        "coverage": "success" if plan.get("run_full") is True else "skipped",
        "fuzz-generator": "success" if plan.get("run_generator_fuzz") is True else "skipped",
        "fuzz-state": "success" if plan.get("run_state_fuzz") is True else "skipped",
        "install-linux": "success" if plan.get("run_install") is True else "skipped",
        "macos-install": "success" if plan.get("run_install") is True else "skipped",
        "tag-identity": "success" if plan.get("run_tag_identity") is True else "skipped",
    }
    rows: list[str] = []
    failure_classes: list[str] = []
    for job, expected in expected_results.items():
        job_data = needs.get(job, {})
        actual = job_data.get("result") if isinstance(job_data, Mapping) else None
        rows.append(f"| `{job}` | `{expected}` | `{actual or '<missing>'}` |")
        if actual != expected:
            errors.append(f"job {job} expected {expected} but was {actual or '<missing>'}")
            if actual == "cancelled":
                if event_name == "pull_request":
                    failure_classes.append(f"{job}: timeout or superseded PR cancellation")
                else:
                    failure_classes.append(
                        f"{job}: timeout/external cancellation; non-PR concurrency groups are unique"
                    )
            elif actual == "skipped":
                failure_classes.append(f"{job}: unexpected skipped lane")
            elif job == "coverage":
                failure_classes.append("coverage: threshold or canonical artifact failure")
            elif job in {"quick", "full", "fuzz-generator", "fuzz-state"}:
                failure_classes.append(f"{job}: product test or lane configuration failure")
            else:
                failure_classes.append(f"{job}: infrastructure or contract failure")

    coverage_outputs = needs.get("coverage", {}).get("outputs", {}) if isinstance(needs.get("coverage"), Mapping) else {}
    if plan.get("run_full") is True and expected_results["coverage"] == "success":
        expected_total = str(plan.get("expected_total_tests", ""))
        if str(coverage_outputs.get("total_tests", "")) != expected_total:
            errors.append(
                f"coverage total_tests expected {expected_total} but was {coverage_outputs.get('total_tests', '<missing>')}"
            )
        try:
            percent = float(coverage_outputs.get("coverage_percent", ""))
        except (TypeError, ValueError):
            errors.append("coverage_percent output is missing or invalid")
        else:
            if percent < 80.0:
                errors.append(f"coverage_percent {percent:.2f} is below 80.00")

    for job, (case_count, seed) in FUZZ_EXPECTATIONS.items():
        if expected_results[job] != "success":
            continue
        outputs = needs.get(job, {}).get("outputs", {}) if isinstance(needs.get(job), Mapping) else {}
        if str(outputs.get("case_count", "")) != case_count:
            errors.append(f"{job} case_count is not {case_count}")
        if str(outputs.get("seed", "")) != seed:
            errors.append(f"{job} seed is not {seed}")

    status = "PASS" if not errors else "FAIL"
    generator_outputs = needs.get("fuzz-generator", {}).get("outputs", {}) if isinstance(needs.get("fuzz-generator"), Mapping) else {}
    state_outputs = needs.get("fuzz-state", {}).get("outputs", {}) if isinstance(needs.get("fuzz-state"), Mapping) else {}
    markdown = "\n".join(
        [
            f"## Compatibility CI final gate: {status}",
            "",
            f"- Tier: `{plan.get('tier', '<missing>')}`",
            f"- Reasons: {', '.join(str(value) for value in plan.get('reasons', [])) or '<missing>'}",
            f"- Head SHA: `{plan.get('head_sha') or '<none>'}`",
            f"- Merge SHA: `{plan.get('merge_sha') or '<none>'}`",
            f"- Canonical shard tests: `{coverage_outputs.get('total_tests') or ('skipped' if not plan.get('run_full') else '<missing>')}`",
            f"- Branch coverage: `{coverage_outputs.get('coverage_percent') or ('skipped' if not plan.get('run_full') else '<missing>')}%`",
            f"- Generator fuzz cases / seed: `{generator_outputs.get('case_count') or 'skipped'}` / `{generator_outputs.get('seed') or 'skipped'}`",
            f"- State fuzz cases / seed: `{state_outputs.get('case_count') or 'skipped'}` / `{state_outputs.get('seed') or 'skipped'}`",
            "",
            "| Job | Expected | Actual |",
            "| --- | --- | --- |",
            *rows,
            "",
            "### Failure classification",
            "",
            *(f"- {value}" for value in failure_classes),
            *(["- None"] if not failure_classes else []),
            "",
            "### Errors",
            "",
            *(f"- {error}" for error in errors),
            *( ["- None"] if not errors else [] ),
            "",
        ]
    )
    return errors, markdown


def _path_or_none(value: str) -> Path | None:
    return Path(value) if value else None


def _inventory_total(path: Path) -> int:
    inventory = _load_json(path)
    total = inventory.get("expected_total_tests")
    shards = inventory.get("shards")
    if (
        inventory.get("schema_version") != SCHEMA_VERSION
        or not isinstance(total, int)
        or isinstance(total, bool)
        or total <= 0
        or not isinstance(shards, dict)
        or set(shards) != {"1", "2", "3", "4"}
    ):
        raise CompatibilityError("validated inventory identity is missing or invalid")
    observed_total = 0
    for shard in shards.values():
        if not isinstance(shard, dict) or not isinstance(shard.get("test_count"), int):
            raise CompatibilityError("validated inventory shard count is missing or invalid")
        observed_total += shard["test_count"]
    if observed_total != total:
        raise CompatibilityError(
            f"validated inventory total={total} but shard counts sum to {observed_total}"
        )
    return total


def _cmd_classify(args: argparse.Namespace) -> int:
    event = _load_json(Path(args.event_path))
    main_proof = _load_json(Path(args.main_proof)) if args.main_proof else None
    plan = build_plan(
        Path(args.repo).resolve(),
        args.event_name,
        event,
        args.github_sha,
        args.manual_profile,
        main_proof,
    )
    plan["expected_total_tests"] = _inventory_total(Path(args.inventory))
    output = Path(args.output)
    _write_json(output, plan)
    _append_outputs(
        _path_or_none(args.github_output),
        {
            "tier": plan["tier"],
            "run_quick": plan["run_quick"],
            "run_full": plan["run_full"],
            "run_state_fuzz": plan["run_state_fuzz"],
            "run_generator_fuzz": plan["run_generator_fuzz"],
            "run_install": plan["run_install"],
            "run_tag_identity": plan["run_tag_identity"],
        },
    )
    if args.summary:
        with Path(args.summary).open("a", encoding="utf-8") as handle:
            handle.write(_plan_markdown(plan))
    print(json.dumps(plan, sort_keys=True))
    return 0


def _cmd_main_proof(args: argparse.Namespace) -> int:
    event = _load_json(Path(args.event_path))
    ref = event.get("ref", "")
    if args.event_name == "push" and isinstance(ref, str) and ref.startswith("refs/tags/v"):
        proof = verify_successful_main_run(
            repository=args.repository,
            workflow=args.workflow,
            tested_sha=args.github_sha,
            token=args.token,
        )
    else:
        proof = {
            "schema_version": SCHEMA_VERSION,
            "verified": False,
            "head_sha": args.github_sha if SHA_RE.fullmatch(args.github_sha or "") else "",
            "reason": "not-a-version-tag",
        }
    _write_json(Path(args.output), proof)
    print(json.dumps(proof, sort_keys=True))
    return 0


def _cmd_validate_manifest(args: argparse.Namespace) -> int:
    inventory = build_inventory(Path(args.repo).resolve(), Path(args.manifest))
    _write_json(Path(args.output), inventory)
    print(
        "CI_INVENTORY_OK "
        f"total={inventory['expected_total_tests']} "
        + " ".join(
            f"shard_{shard}={data['test_count']}" for shard, data in inventory["shards"].items()
        )
    )
    return 0


def _cmd_run_shard(args: argparse.Namespace) -> int:
    return run_shard(
        Path(args.repo).resolve(),
        Path(args.manifest),
        args.shard,
        args.tested_sha,
        Path(args.output),
    )


def _cmd_verify_artifacts(args: argparse.Namespace) -> int:
    summary = verify_shard_artifacts(
        Path(args.repo).resolve(),
        Path(args.manifest),
        Path(args.artifact_dir),
        args.tested_sha,
    )
    _write_json(Path(args.output), summary)
    _append_outputs(_path_or_none(args.github_output), {"total_tests": summary["total_tests"]})
    print(f"CI_SHARDS_OK total={summary['total_tests']} tested_sha={summary['tested_sha']}")
    return 0


def _cmd_coverage_summary(args: argparse.Namespace) -> int:
    summary = coverage_summary(Path(args.coverage_json), args.minimum, args.baseline, args.tolerance)
    _append_outputs(_path_or_none(args.github_output), summary)
    print(json.dumps(summary, sort_keys=True))
    return 0


def _cmd_canonical_coverage(args: argparse.Namespace) -> int:
    tested_sha = args.tested_sha or _commit_oid(Path(args.repo).resolve(), "HEAD")
    canonical_coverage(
        Path(args.repo),
        Path(args.manifest),
        Path(args.artifact_dir),
        tested_sha,
        mode=args.mode,
        shard=args.shard,
        minimum=args.minimum,
        github_output=_path_or_none(args.github_output),
    )
    return 0


def _cmd_verify_gate(args: argparse.Namespace) -> int:
    try:
        plan = _load_json(Path(args.plan))
        needs = json.loads(args.needs_json)
        if not isinstance(needs, dict):
            raise CompatibilityError("needs JSON root must be an object")
        errors, markdown = gate_report(plan, needs)
    except (CompatibilityError, json.JSONDecodeError, OSError) as exc:
        errors = [f"gate input failure: {type(exc).__name__}: {exc}"]
        markdown = "## Compatibility CI final gate: FAIL\n\n" + "\n".join(f"- {error}" for error in errors) + "\n"
    if args.summary:
        with Path(args.summary).open("a", encoding="utf-8") as handle:
            handle.write(markdown)
    print(markdown)
    return 1 if errors else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    classify = subparsers.add_parser("classify")
    classify.add_argument("--repo", default=".")
    classify.add_argument("--event-name", required=True)
    classify.add_argument("--event-path", required=True)
    classify.add_argument("--github-sha", required=True)
    classify.add_argument("--manual-profile", default="release")
    classify.add_argument("--main-proof", default="")
    classify.add_argument("--inventory", required=True)
    classify.add_argument("--output", default=PLAN_NAME)
    classify.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    classify.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY", ""))
    classify.set_defaults(func=_cmd_classify)

    main_proof = subparsers.add_parser("main-proof")
    main_proof.add_argument("--event-name", required=True)
    main_proof.add_argument("--event-path", required=True)
    main_proof.add_argument("--github-sha", required=True)
    main_proof.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    main_proof.add_argument("--workflow", default=".github/workflows/compatibility.yml")
    main_proof.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    main_proof.add_argument("--output", default="main-proof-v1.json")
    main_proof.set_defaults(func=_cmd_main_proof)

    validate_manifest = subparsers.add_parser("validate-manifest")
    validate_manifest.add_argument("--repo", default=".")
    validate_manifest.add_argument("--manifest", required=True)
    validate_manifest.add_argument("--output", default=INVENTORY_NAME)
    validate_manifest.set_defaults(func=_cmd_validate_manifest)

    shard = subparsers.add_parser("run-shard")
    shard.add_argument("--repo", default=".")
    shard.add_argument("--manifest", required=True)
    shard.add_argument("--shard", required=True, choices=("1", "2", "3", "4"))
    shard.add_argument("--tested-sha", required=True)
    shard.add_argument("--output", required=True)
    shard.set_defaults(func=_cmd_run_shard)

    verify_artifacts = subparsers.add_parser("verify-artifacts")
    verify_artifacts.add_argument("--repo", default=".")
    verify_artifacts.add_argument("--manifest", required=True)
    verify_artifacts.add_argument("--artifact-dir", required=True)
    verify_artifacts.add_argument("--tested-sha", required=True)
    verify_artifacts.add_argument("--output", default="shard-summary-v1.json")
    verify_artifacts.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    verify_artifacts.set_defaults(func=_cmd_verify_artifacts)

    summarize = subparsers.add_parser("coverage-summary")
    summarize.add_argument("--coverage-json", required=True)
    summarize.add_argument("--minimum", type=float, default=80.0)
    summarize.add_argument("--baseline", type=float)
    summarize.add_argument("--tolerance", type=float, default=0.01)
    summarize.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    summarize.set_defaults(func=_cmd_coverage_summary)

    canonical = subparsers.add_parser("canonical-coverage")
    canonical.add_argument("--repo", default=".")
    canonical.add_argument("--manifest", default=".github/ci/test-shards.json")
    canonical.add_argument("--artifact-dir", default=".ci-canonical-coverage")
    canonical.add_argument("--tested-sha", default="")
    canonical.add_argument("--mode", choices=("all", "shard", "combine"), default="all")
    canonical.add_argument("--shard", default="")
    canonical.add_argument("--minimum", type=float, default=80.0)
    canonical.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    canonical.set_defaults(func=_cmd_canonical_coverage)

    gate = subparsers.add_parser("verify-gate")
    gate.add_argument("--plan", required=True)
    gate.add_argument("--needs-json", required=True)
    gate.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY", ""))
    gate.set_defaults(func=_cmd_verify_gate)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return args.func(args)
    except (CompatibilityError, OSError, subprocess.SubprocessError, UnicodeError) as exc:
        print(f"COMPATIBILITY_CI_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
