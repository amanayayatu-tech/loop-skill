"""Manifest compiler (P1-10) and effective-config diff (P1-10).

A user writes a small JSON or YAML source configuration; the compiler
produces a single machine-readable manifest containing the role list,
the goal registry, the heartbeat configuration, the policy migration
allowlist, and the recovery-registry references. The diff between
two compiled manifests is the "effective config diff" the runtime
displays when the user asks why a particular capability is or is not
active.

The compiler does not read free-form text. The source is a strict
JSON / YAML mapping with a known schema. This is the design point
that makes the manifest a *compiled artifact* rather than a
hand-maintained manifest.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

#: Maximum number of goals the compiler will accept. The cap exists
#: so a misconfigured source cannot blow up the manifest size.
MAX_GOALS = 64

#: Maximum number of roles the compiler will accept.
MAX_ROLES = 16

#: Required top-level keys in the source configuration.
REQUIRED_SOURCE_KEYS: frozenset[str] = frozenset(
    {"schema_version", "roles", "goals", "heartbeat", "policy"}
)

#: Allowed policy migration kinds. Mirrors the schema in
#: ``recovery_registry.py`` so the runtime can use the same
#: descriptor shape.
ALLOWED_POLICY_KINDS: frozenset[str] = frozenset(
    {
        "INCREASE_REPAIR_BUDGET",
        "INCREASE_REPAIR_BUDGET_TO_5",
        "INCREASE_REPAIR_BUDGET_TO_20",
        "REGISTER_HEARTBEAT",
        "ADVANCE_ROADMAP",
        "MIGRATE_V2_TO_V3",
    }
)


class ManifestCompilerError(ValueError):
    """Raised on invalid source configurations, missing keys, or
    schema mismatches."""


@dataclass
class CompiledManifest:
    schema_version: str
    roles: tuple[Mapping[str, Any], ...]
    goals: tuple[Mapping[str, Any], ...]
    heartbeat: Mapping[str, Any]
    policy: Mapping[str, Any]
    digest: str = ""
    source_digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "roles": [dict(role) for role in self.roles],
            "goals": [dict(goal) for goal in self.goals],
            "heartbeat": dict(self.heartbeat),
            "policy": dict(self.policy),
            "digest": self.digest,
            "source_digest": self.source_digest,
        }

    def to_canonical_bytes(self) -> bytes:
        return json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":")
        ).encode()

    def to_digest_bytes(self) -> bytes:
        """Return the canonical content-address payload.

        The advertised digest field is excluded so verification is finite and
        reproducible: consumers hash this payload and compare it with
        ``digest``.
        """
        payload = self.to_dict()
        payload.pop("digest")
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def compile_manifest(source: Mapping[str, Any]) -> CompiledManifest:
    """Compile ``source`` into a :class:`CompiledManifest`.

    The compiler is pure: no I/O, no clock, no randomness. The same
    input always produces the same output bytes, so the runtime can
    content-address the manifest and detect drift.
    """
    if not isinstance(source, Mapping):
        raise ManifestCompilerError("source must be a mapping")
    missing = REQUIRED_SOURCE_KEYS - set(source.keys())
    if missing:
        raise ManifestCompilerError(
            f"source missing required keys: {sorted(missing)}"
        )
    schema_version = str(source["schema_version"])
    if schema_version != "loop-source-v1":
        raise ManifestCompilerError(
            f"unknown schema_version {schema_version!r}"
        )
    roles = tuple(_expect_list_of_mappings(source["roles"], "roles", MAX_ROLES))
    goals = tuple(_expect_list_of_mappings(source["goals"], "goals", MAX_GOALS))
    heartbeat = _expect_mapping(source["heartbeat"], "heartbeat")
    policy = _expect_mapping(source["policy"], "policy")

    _validate_roles(roles)
    _validate_goals(goals)
    _validate_heartbeat(heartbeat)
    _validate_policy(policy)

    source_digest = hashlib.sha256(
        json.dumps(source, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest = CompiledManifest(
        schema_version=schema_version,
        roles=roles,
        goals=goals,
        heartbeat=heartbeat,
        policy=policy,
        source_digest=source_digest,
    )
    manifest.digest = hashlib.sha256(manifest.to_digest_bytes()).hexdigest()
    return manifest


def diff_manifests(
    before: CompiledManifest, after: CompiledManifest
) -> dict[str, Any]:
    """Return a stable diff between two compiled manifests.

    The diff never includes the role or goal bodies; only their
    identifiers and a digest of their content. This is the privacy
    boundary: a logged diff does not leak the user's policy text.
    """
    before_role_ids = {str(role.get("id", "")) for role in before.roles}
    after_role_ids = {str(role.get("id", "")) for role in after.roles}
    before_goal_ids = {str(goal.get("id", "")) for goal in before.goals}
    after_goal_ids = {str(goal.get("id", "")) for goal in after.goals}
    return {
        "before_digest": before.digest,
        "after_digest": after.digest,
        "roles_added": sorted(after_role_ids - before_role_ids),
        "roles_removed": sorted(before_role_ids - after_role_ids),
        "goals_added": sorted(after_goal_ids - before_goal_ids),
        "goals_removed": sorted(before_goal_ids - after_goal_ids),
        "heartbeat_changed": before.heartbeat != after.heartbeat,
        "policy_changed": before.policy != after.policy,
    }


def write_compiled_manifest(path: Path, manifest: CompiledManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(manifest.to_dict(), sort_keys=True, indent=2) + "\n"
    )
    import os as _os
    _os.replace(tmp, path)


def _expect_list_of_mappings(
    value: Any, name: str, max_items: int
) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise ManifestCompilerError(f"{name!r} must be a list")
    if len(value) > max_items:
        raise ManifestCompilerError(
            f"{name!r} has {len(value)} items, exceeds cap {max_items}"
        )
    result: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ManifestCompilerError(
                f"{name!r}[{index}] must be a mapping"
            )
        result.append(item)
    return result


def _expect_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestCompilerError(f"{name!r} must be a mapping")
    return value


def _validate_roles(roles: Sequence[Mapping[str, Any]]) -> None:
    seen: set[str] = set()
    for role in roles:
        role_id = str(role.get("id", ""))
        if not role_id:
            raise ManifestCompilerError("role missing 'id'")
        if role_id in seen:
            raise ManifestCompilerError(f"duplicate role id {role_id!r}")
        seen.add(role_id)
        if "model" not in role:
            raise ManifestCompilerError(
                f"role {role_id!r} missing 'model'"
            )
        if "responsibilities" not in role:
            raise ManifestCompilerError(
                f"role {role_id!r} missing 'responsibilities'"
            )


def _validate_goals(goals: Sequence[Mapping[str, Any]]) -> None:
    seen: set[str] = set()
    for goal in goals:
        goal_id = str(goal.get("id", ""))
        if not goal_id:
            raise ManifestCompilerError("goal missing 'id'")
        if goal_id in seen:
            raise ManifestCompilerError(f"duplicate goal id {goal_id!r}")
        seen.add(goal_id)
        if "objective" not in goal:
            raise ManifestCompilerError(
                f"goal {goal_id!r} missing 'objective'"
            )
        completion = goal.get("required_completion_class")
        if completion not in {
            "COMPLETE_ARTIFACT",
            "COMPLETE_WITH_LIMITATION",
            "EMPIRICAL_RESULT_OBSERVED",
            "FORMAL_ACCEPTED",
            "PUBLIC_RELEASED",
        }:
            raise ManifestCompilerError(
                f"goal {goal_id!r} required_completion_class invalid: {completion!r}"
            )


def _validate_heartbeat(heartbeat: Mapping[str, Any]) -> None:
    if "rrule" not in heartbeat:
        raise ManifestCompilerError("heartbeat missing 'rrule'")
    if "target" not in heartbeat:
        raise ManifestCompilerError("heartbeat missing 'target'")
    if "prompt_digest" not in heartbeat:
        raise ManifestCompilerError("heartbeat missing 'prompt_digest'")


def _validate_policy(policy: Mapping[str, Any]) -> None:
    migrations = policy.get("migrations")
    if migrations is None:
        return
    if not isinstance(migrations, list):
        raise ManifestCompilerError("policy.migrations must be a list")
    for index, migration in enumerate(migrations):
        if not isinstance(migration, Mapping):
            raise ManifestCompilerError(
                f"policy.migrations[{index}] must be a mapping"
            )
        kind = migration.get("kind")
        if kind not in ALLOWED_POLICY_KINDS:
            raise ManifestCompilerError(
                f"policy.migrations[{index}].kind {kind!r} not in "
                f"{sorted(ALLOWED_POLICY_KINDS)}"
            )


__all__ = [
    "ALLOWED_POLICY_KINDS",
    "CompiledManifest",
    "MAX_GOALS",
    "MAX_ROLES",
    "ManifestCompilerError",
    "REQUIRED_SOURCE_KEYS",
    "compile_manifest",
    "diff_manifests",
    "write_compiled_manifest",
]
