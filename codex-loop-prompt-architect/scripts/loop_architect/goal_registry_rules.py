"""Goal registry initialization rules (P1-11).

The rules module encodes the "CP0 disposable, formal registry
one-shot" discipline the closure matrix relies on. A formal
initialization must register the entire goal set in one call; a
disposable initialization may register a single goal (typically
``D0-control-plane-self-test``).

Registry migrations are also first-class: a formal registry that
needs to add or retire a goal after initialization must go through
the ``GoalRegistryMigration`` descriptor, which carries the same
fields the policy-migration framework uses (``source_value``,
``target_value``, ``bounds``, ``approval``, ``safe_point``).

The module is pure-Python. It does not import from ``state_runtime``
so a follow-up commit can wire the runtime through it without
entangling this commit.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

#: Marker goal id reserved for the disposable CP0 self-test.
DISPOSABLE_CP0_GOAL_ID: str = "D0-control-plane-self-test"

#: Bound on the number of goals a formal registry may carry in a
#: single initialization. The cap mirrors
#: :data:`manifest_compiler.MAX_GOALS` so the two layers agree.
FORMAL_REGISTRY_GOAL_CAP = 64

#: Allowed migration kinds. ``REGISTER`` adds a new goal, ``RETIRE``
#: marks an existing goal as terminal-and-inactive, ``RENUMBER``
#: changes a goal's id while keeping its history. Anything else
#: must be approved by the human supervisor.
ALLOWED_MIGRATION_KINDS: frozenset[str] = frozenset({"REGISTER", "RETIRE", "RENUMBER"})

#: Required safe-point statuses for a migration. ``PAUSED`` is the
#: only allowed state for a formal registry migration; a
#: ``RUNNING`` registry cannot be migrated.
ALLOWED_SAFE_POINT_STATUSES: frozenset[str] = frozenset({"PAUSED", "INITIALIZING"})


class GoalRegistryError(ValueError):
    """Raised on invalid registry shapes, migration descriptors, or
    rule violations."""


@dataclass(frozen=True)
class GoalDefinition:
    goal_id: str
    objective: str
    required_completion_class: str
    depends_on: tuple[str, ...] = ()
    disposable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "objective": self.objective,
            "required_completion_class": self.required_completion_class,
            "depends_on": list(self.depends_on),
            "disposable": self.disposable,
        }


@dataclass
class GoalRegistry:
    goals: dict[str, GoalDefinition] = field(default_factory=dict)
    disposable: bool = False

    def initialize(self, goals: Sequence[Mapping[str, Any]]) -> None:
        """Register ``goals`` as the formal registry, replacing any
        prior state.

        A disposable registry accepts only :data:`DISPOSABLE_CP0_GOAL_ID`.
        A formal registry accepts any number of goals up to
        :data:`FORMAL_REGISTRY_GOAL_CAP` and requires a non-disposable
        flag on every goal.
        """
        if self.goals:
            raise GoalRegistryError(
                "initialize called twice; use apply_migration instead"
            )
        if not goals:
            raise GoalRegistryError("at least one goal is required")
        if self.disposable:
            self._initialize_disposable(goals)
            return
        self._initialize_formal(goals)

    def apply_migration(
        self, migration: "GoalRegistryMigration", *, current_status: str
    ) -> None:
        """Apply ``migration`` to the registry, returning the new
        digest of the registry.

        The migration must come from an audited safe-point; a
        registry in a non-allowed status (anything outside
        :data:`ALLOWED_SAFE_POINT_STATUSES`) cannot be migrated.
        """
        if current_status not in ALLOWED_SAFE_POINT_STATUSES:
            raise GoalRegistryError(
                f"registry in {current_status!r} cannot be migrated; "
                f"allowed: {sorted(ALLOWED_SAFE_POINT_STATUSES)}"
            )
        if migration.kind == "REGISTER":
            self._register_goal(migration.target_goal)
        elif migration.kind == "RETIRE":
            self._retire_goal(migration.source_value)
        elif migration.kind == "RENUMBER":
            self._renumber_goal(migration.source_value, migration.target_value)
        else:
            raise GoalRegistryError(
                f"unknown migration kind {migration.kind!r}"
            )

    def digest(self) -> str:
        ordered = [self.goals[key].to_dict() for key in sorted(self.goals)]
        encoded = json.dumps(ordered, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _initialize_disposable(
        self, goals: Sequence[Mapping[str, Any]]
    ) -> None:
        if len(goals) != 1:
            raise GoalRegistryError(
                "disposable registry must contain exactly one goal"
            )
        goal = goals[0]
        goal_id = str(goal.get("goal_id", ""))
        if goal_id != DISPOSABLE_CP0_GOAL_ID:
            raise GoalRegistryError(
                f"disposable registry may only register "
                f"{DISPOSABLE_CP0_GOAL_ID!r} (got {goal_id!r})"
            )
        definition = _build_goal_definition(goal, disposable=True)
        self.goals[goal_id] = definition

    def _initialize_formal(
        self, goals: Sequence[Mapping[str, Any]]
    ) -> None:
        if len(goals) > FORMAL_REGISTRY_GOAL_CAP:
            raise GoalRegistryError(
                f"formal registry has {len(goals)} goals, exceeds cap {FORMAL_REGISTRY_GOAL_CAP}"
            )
        seen: set[str] = set()
        for goal in goals:
            goal_id = str(goal.get("goal_id", ""))
            if not goal_id:
                raise GoalRegistryError("goal missing 'goal_id'")
            if goal_id in seen:
                raise GoalRegistryError(f"duplicate goal id {goal_id!r}")
            seen.add(goal_id)
            if goal_id == DISPOSABLE_CP0_GOAL_ID:
                raise GoalRegistryError(
                    f"{DISPOSABLE_CP0_GOAL_ID!r} is reserved for disposable registries"
                )
            definition = _build_goal_definition(goal, disposable=False)
            self.goals[goal_id] = definition
        _validate_dependency_closure(self.goals)

    def _register_goal(self, goal: Mapping[str, Any]) -> None:
        if len(self.goals) >= FORMAL_REGISTRY_GOAL_CAP:
            raise GoalRegistryError(
                f"registry at cap {FORMAL_REGISTRY_GOAL_CAP}"
            )
        goal_id = str(goal.get("goal_id", ""))
        if not goal_id:
            raise GoalRegistryError("goal missing 'goal_id'")
        if goal_id in self.goals:
            raise GoalRegistryError(f"goal {goal_id!r} already registered")
        if goal_id == DISPOSABLE_CP0_GOAL_ID:
            raise GoalRegistryError(
                f"{DISPOSABLE_CP0_GOAL_ID!r} is disposable only"
            )
        self.goals[goal_id] = _build_goal_definition(goal, disposable=False)
        _validate_dependency_closure(self.goals)

    def _retire_goal(self, goal_id: str) -> None:
        if goal_id not in self.goals:
            raise GoalRegistryError(f"goal {goal_id!r} not in registry")
        del self.goals[goal_id]

    def _renumber_goal(self, source_id: str, target_id: str) -> None:
        if source_id not in self.goals:
            raise GoalRegistryError(f"goal {source_id!r} not in registry")
        if target_id in self.goals:
            raise GoalRegistryError(f"target {target_id!r} already exists")
        if not target_id:
            raise GoalRegistryError("renumber target id is empty")
        definition = self.goals.pop(source_id)
        # Rewrite any sibling dependency that pointed at the old id
        # *before* the new id lands, so the dependency-closure
        # validator never sees a half-applied registry.
        rewrites: dict[str, GoalDefinition] = {
            goal_id: GoalDefinition(
                goal_id=defn.goal_id,
                objective=defn.objective,
                required_completion_class=defn.required_completion_class,
                depends_on=tuple(
                    target_id if dep == source_id else dep
                    for dep in defn.depends_on
                ),
                disposable=defn.disposable,
            )
            for goal_id, defn in self.goals.items()
            if source_id in defn.depends_on
        }
        for goal_id, defn in rewrites.items():
            self.goals[goal_id] = defn
        self.goals[target_id] = GoalDefinition(
            goal_id=target_id,
            objective=definition.objective,
            required_completion_class=definition.required_completion_class,
            depends_on=tuple(
                target_id if dep == source_id else dep
                for dep in definition.depends_on
            ),
            disposable=definition.disposable,
        )
        _validate_dependency_closure(self.goals)


@dataclass(frozen=True)
class GoalRegistryMigration:
    kind: str
    source_value: str
    target_value: str
    target_goal: Mapping[str, Any]
    bounds: str
    approval: str
    safe_point: str
    timestamp: str

    def __post_init__(self) -> None:
        if self.kind not in ALLOWED_MIGRATION_KINDS:
            raise GoalRegistryError(
                f"migration kind {self.kind!r} not in {sorted(ALLOWED_MIGRATION_KINDS)}"
            )
        if not self.bounds:
            raise GoalRegistryError("migration bounds is required")
        if not self.approval:
            raise GoalRegistryError("migration approval is required")
        if self.safe_point not in ALLOWED_SAFE_POINT_STATUSES:
            raise GoalRegistryError(
                f"migration safe_point {self.safe_point!r} not in {sorted(ALLOWED_SAFE_POINT_STATUSES)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source_value": self.source_value,
            "target_value": self.target_value,
            "target_goal": dict(self.target_goal),
            "bounds": self.bounds,
            "approval": self.approval,
            "safe_point": self.safe_point,
            "timestamp": self.timestamp,
        }


def build_migration(
    *,
    kind: str,
    source_value: str,
    target_value: str,
    target_goal: Mapping[str, Any],
    bounds: str = "lenient",
    approval: str = "supervisor",
    safe_point: str = "PAUSED",
    timestamp: str | None = None,
) -> GoalRegistryMigration:
    return GoalRegistryMigration(
        kind=kind,
        source_value=source_value,
        target_value=target_value,
        target_goal=target_goal,
        bounds=bounds,
        approval=approval,
        safe_point=safe_point,
        timestamp=timestamp or _now_iso(),
    )


def _build_goal_definition(
    goal: Mapping[str, Any], *, disposable: bool
) -> GoalDefinition:
    goal_id = str(goal.get("goal_id", ""))
    objective = str(goal.get("objective", ""))
    if not objective:
        raise GoalRegistryError(f"goal {goal_id!r} missing 'objective'")
    completion = str(goal.get("required_completion_class", ""))
    if completion not in {
        "COMPLETE_ARTIFACT",
        "COMPLETE_WITH_LIMITATION",
        "EMPIRICAL_RESULT_OBSERVED",
        "FORMAL_ACCEPTED",
        "PUBLIC_RELEASED",
    }:
        raise GoalRegistryError(
            f"goal {goal_id!r} required_completion_class invalid: {completion!r}"
        )
    depends_on = tuple(str(value) for value in goal.get("depends_on", ()))
    return GoalDefinition(
        goal_id=goal_id,
        objective=objective,
        required_completion_class=completion,
        depends_on=depends_on,
        disposable=disposable,
    )


def _validate_dependency_closure(goals: Mapping[str, GoalDefinition]) -> None:
    for definition in goals.values():
        for dep in definition.depends_on:
            if dep == definition.goal_id:
                raise GoalRegistryError(
                    f"goal {definition.goal_id!r} depends on itself"
                )
            if dep not in goals:
                raise GoalRegistryError(
                    f"goal {definition.goal_id!r} depends on missing {dep!r}"
                )


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_registry(path: Path, registry: GoalRegistry) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "disposable": registry.disposable,
        "digest": registry.digest(),
        "goals": [registry.goals[key].to_dict() for key in sorted(registry.goals)],
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    import os as _os
    _os.replace(tmp, path)


__all__ = [
    "ALLOWED_MIGRATION_KINDS",
    "ALLOWED_SAFE_POINT_STATUSES",
    "DISPOSABLE_CP0_GOAL_ID",
    "FORMAL_REGISTRY_GOAL_CAP",
    "GoalDefinition",
    "GoalRegistry",
    "GoalRegistryError",
    "GoalRegistryMigration",
    "build_migration",
    "write_registry",
]
