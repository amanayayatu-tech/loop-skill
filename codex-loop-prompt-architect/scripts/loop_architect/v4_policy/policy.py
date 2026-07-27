"""Pure optional Standard/Adaptive/review/human/repair policy decisions.

Every function consumes immutable semantic/projection input and returns a
decision.  This package cannot write a store, sign a receipt, call a Host, or
retry an effect.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from loop_architect.v4_alpha.generated_protocol import COMMAND_TYPES
from loop_architect.v4_alpha.protocol import domain_digest


_COMMANDS = frozenset(COMMAND_TYPES)
_MODES = frozenset({"STANDARD", "ADAPTIVE"})
_DECISION_OPTIONS = frozenset({"CONTINUE_REPAIR", "WAIT", "STOP"})


class PolicyError(Exception):
    """Fail-closed policy input rejection, never a protocol receipt."""


@dataclass(frozen=True)
class GoalSpec:
    goal_id: str
    objective: str
    depends_on: tuple[str, ...] = ()
    milestone_id: str = "m1"


@dataclass(frozen=True)
class PolicyEnvelope:
    allowed_goal_ids: tuple[str, ...]
    max_goals: int = 16
    max_roadmap_revisions: int = 4
    max_repair_attempts: int = 3
    max_same_failure: int = 2


@dataclass(frozen=True)
class AdaptiveRoadmap:
    revision: int
    active_goal_id: str
    goals: tuple[GoalSpec, ...]
    roadmap_digest: str


@dataclass(frozen=True)
class RoleRequirement:
    role: str
    artifact_ref: str | None
    reason: str


@dataclass(frozen=True)
class RepairObservation:
    attempt_ref: str
    failure_fingerprint: str


@dataclass(frozen=True)
class DecisionCard:
    card_ref: str
    goal_ref: str
    artifact_ref: str | None
    options: tuple[str, ...]
    context_digest: str
    expires_at: str
    card_digest: str


@dataclass(frozen=True)
class DecisionResponse:
    card_ref: str
    selected_option: str
    context_digest: str
    card_digest: str
    responded_at: str


@dataclass(frozen=True)
class NextAction:
    kind: str
    command_type: str | None
    reason: str


def _time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise PolicyError("invalid policy timestamp") from exc


def validate_manifest_mode(execution_mode: str, task_horizon: str) -> str:
    if execution_mode not in _MODES:
        raise PolicyError("unsupported execution mode")
    expected = "ADAPTIVE" if task_horizon.strip().lower() == "adaptive" else "STANDARD"
    if execution_mode != expected:
        raise PolicyError("execution mode does not match the Intake decision")
    return execution_mode


def _validate_goals(
    goals: Sequence[GoalSpec], envelope: PolicyEnvelope
) -> dict[str, GoalSpec]:
    if not goals or len(goals) > envelope.max_goals:
        raise PolicyError("goal count is outside the policy envelope")
    identifiers = [goal.goal_id for goal in goals]
    if len(set(identifiers)) != len(identifiers):
        raise PolicyError("duplicate goal identity")
    if set(identifiers) - set(envelope.allowed_goal_ids):
        raise PolicyError("goal is outside the author envelope")
    result = {goal.goal_id: goal for goal in goals}
    for goal in goals:
        if not goal.goal_id or not goal.objective.strip() or not goal.milestone_id:
            raise PolicyError("invalid goal definition")
        if goal.goal_id in goal.depends_on or set(goal.depends_on) - set(result):
            raise PolicyError("invalid goal dependency")
    return result


def build_standard_queue(
    goals: Sequence[GoalSpec], envelope: PolicyEnvelope
) -> tuple[GoalSpec, ...]:
    """Freeze the supplied dependency order; no policy-time roadmap mutation."""
    _validate_goals(goals, envelope)
    prior: set[str] = set()
    for goal in goals:
        if not set(goal.depends_on) <= prior:
            raise PolicyError("Standard Goal Queue is not dependency ordered")
        prior.add(goal.goal_id)
    return tuple(goals)


def build_adaptive_roadmap(
    goals: Sequence[GoalSpec],
    envelope: PolicyEnvelope,
    *,
    revision: int,
    active_goal_id: str,
    previous: AdaptiveRoadmap | None = None,
) -> AdaptiveRoadmap:
    definitions = _validate_goals(goals, envelope)
    if revision < 1 or revision > envelope.max_roadmap_revisions:
        raise PolicyError("roadmap revision exceeds the policy envelope")
    if active_goal_id not in definitions:
        raise PolicyError("Adaptive roadmap requires exactly one active Goal")
    if previous is not None:
        if revision != previous.revision + 1:
            raise PolicyError("Adaptive roadmap revision is not contiguous")
        previous_goals = {goal.goal_id: goal for goal in previous.goals}
        for goal_id, old in previous_goals.items():
            if goal_id in definitions and definitions[goal_id] != old:
                raise PolicyError("Adaptive roadmap rewrote an existing Goal")
    body = {
        "active_goal_id": active_goal_id,
        "goals": [
            {
                "depends_on": list(goal.depends_on),
                "goal_id": goal.goal_id,
                "milestone_id": goal.milestone_id,
                "objective": goal.objective,
            }
            for goal in goals
        ],
        "revision": revision,
    }
    return AdaptiveRoadmap(
        revision=revision,
        active_goal_id=active_goal_id,
        goals=tuple(goals),
        roadmap_digest=domain_digest("loopskill-adaptive-roadmap-v1\n", body),
    )


def role_requirements(
    snapshot: Mapping[str, Any], *, local_verification_required: bool
) -> tuple[RoleRequirement, ...]:
    """Return only roles justified by current canonical artifact state."""
    if snapshot.get("execution", {}).get("state") != "ACTIVE":
        return ()
    results = snapshot.get("results", {})
    reviews = snapshot.get("reviews", {})
    if not results:
        return (RoleRequirement("WORKER", None, "current Goal needs a result"),)
    acknowledged = [
        (result_ref, result)
        for result_ref, result in results.items()
        if result.get("state") == "ACKNOWLEDGED"
    ]
    if len(acknowledged) != 1:
        return ()
    result_ref, result = acknowledged[0]
    artifact_ref = result.get("artifact_ref")
    if not isinstance(artifact_ref, str):
        return ()
    if local_verification_required and not snapshot.get("local_verification", {}).get(
        artifact_ref
    ):
        return (
            RoleRequirement(
                "LOCAL_VERIFIER", artifact_ref, "local runtime fact is required"
            ),
        )
    if not any(review.get("result_ref") == result_ref for review in reviews.values()):
        return (
            RoleRequirement("REVIEWER", artifact_ref, "current artifact needs review"),
        )
    return ()


def repair_disposition(
    history: Sequence[RepairObservation], envelope: PolicyEnvelope
) -> str:
    if len(history) >= envelope.max_repair_attempts:
        return "USER_DECISION"
    if history:
        current = history[-1].failure_fingerprint
        same = 0
        for observation in reversed(history):
            if observation.failure_fingerprint != current:
                break
            same += 1
        if same >= envelope.max_same_failure:
            return "USER_DECISION"
    return "REPAIR"


def build_decision_card(
    *,
    card_ref: str,
    goal_ref: str,
    artifact_ref: str | None,
    options: Sequence[str],
    current_context: Mapping[str, Any],
    expires_at: str,
) -> DecisionCard:
    normalized = tuple(options)
    if (
        not card_ref.startswith("decision-")
        or not goal_ref.startswith("goal-")
        or not normalized
        or len(set(normalized)) != len(normalized)
        or not set(normalized) <= _DECISION_OPTIONS
    ):
        raise PolicyError("invalid Decision Card")
    _time(expires_at)
    context_digest = domain_digest(
        "loopskill-human-context-v1\n", dict(current_context)
    )
    body = {
        "artifact_ref": artifact_ref,
        "card_ref": card_ref,
        "context_digest": context_digest,
        "expires_at": expires_at,
        "goal_ref": goal_ref,
        "options": list(normalized),
    }
    return DecisionCard(
        card_ref=card_ref,
        goal_ref=goal_ref,
        artifact_ref=artifact_ref,
        options=normalized,
        context_digest=context_digest,
        expires_at=expires_at,
        card_digest=domain_digest("loopskill-decision-card-v1\n", body),
    )


def apply_decision_response(
    card: DecisionCard,
    response: DecisionResponse,
    *,
    current_context: Mapping[str, Any],
    now: str,
) -> str:
    current_digest = domain_digest(
        "loopskill-human-context-v1\n", dict(current_context)
    )
    if (
        response.card_ref != card.card_ref
        or response.card_digest != card.card_digest
        or response.context_digest != card.context_digest
        or current_digest != card.context_digest
        or response.selected_option not in card.options
        or _time(response.responded_at) > _time(now)
        or _time(now) > _time(card.expires_at)
    ):
        raise PolicyError("stale or mismatched human decision")
    return response.selected_option


def _command_action(command_type: str, reason: str) -> NextAction:
    if command_type not in _COMMANDS:
        raise PolicyError("policy selected an undeclared protocol command")
    return NextAction("COMMAND", command_type, reason)


def next_action(snapshot: Mapping[str, Any]) -> NextAction:
    """Map every supported nonterminal state to one command/wait/decision class."""
    execution = snapshot.get("execution", {})
    state = execution.get("state")
    if state == "TERMINAL":
        assurance = snapshot.get("closure_assurance", {}).get("strength")
        if assurance == "COOPERATIVE":
            return NextAction(
                "EXTERNAL_WAIT",
                "StrengthenClosureAssurance",
                "execution is terminal; strict readback may strengthen assurance",
            )
        return NextAction("TERMINAL", None, "execution is honestly terminal")
    if state == "PAUSED":
        return NextAction("USER_DECISION", "ResumeLoop", "loop is explicitly paused")
    if state == "FINALIZING":
        return NextAction(
            "EXTERNAL_WAIT", "CloseExecution", "finalization awaits lifecycle readback"
        )
    if state != "ACTIVE":
        raise PolicyError("unsupported execution state")
    effects = snapshot.get("external_effects", {})
    if effects:
        effect_states = {item.get("state") for item in effects.values()}
        if effect_states & {"ATTEMPT_COMMITTED", "UNKNOWN", "UNVERIFIABLE"}:
            return NextAction(
                "EXTERNAL_WAIT",
                "RecordExternalEffectObservation",
                "startup effect awaits authoritative observation",
            )
        if effect_states != {"OBSERVED"}:
            raise PolicyError("unsupported external effect state")
    host_resources = snapshot.get("host_resources", {})
    if not host_resources:
        return _command_action("BindHostResource", "startup Host resource is observed")
    routes = snapshot.get("routes", {})
    if not routes:
        return _command_action("PrepareRoute", "active Goal needs one route")
    deliveries = snapshot.get("deliveries", {})
    prepared = [item for item in deliveries.values() if item.get("state") == "PREPARED"]
    if prepared:
        return _command_action("BeginEffectDelivery", "prepared delivery has its one attempt")
    waiting = [
        item
        for item in deliveries.values()
        if item.get("state") in {"ATTEMPT_COMMITTED", "UNKNOWN", "UNVERIFIABLE"}
    ]
    if waiting:
        return NextAction(
            "EXTERNAL_WAIT",
            "RecordEffectObservation",
            "delivery awaits authoritative observation",
        )
    results = snapshot.get("results", {})
    if not results:
        return _command_action("StageResult", "observed delivery awaits a result")
    staged = [item for item in results.values() if item.get("state") == "STAGED"]
    if staged:
        return _command_action("AcknowledgeResult", "staged result awaits artifact acceptance")
    reviews = snapshot.get("reviews", {})
    if not reviews:
        return NextAction("POLICY_DECISION", "RecordReview", "current artifact needs review")
    current_review = list(reviews.values())[-1]
    if current_review.get("state") == "REPAIR":
        return NextAction(
            "POLICY_DECISION",
            None,
            "bounded repair policy must choose repair, wait, successor, or stop",
        )
    goals = snapshot.get("goals", {})
    if any(goal.get("state") == "ACTIVE" for goal in goals.values()):
        if current_review.get("state") == "PASS":
            return _command_action("AdvanceGoal", "review PASS can advance current Goal")
        return NextAction(
            "USER_DECISION",
            "PrepareFinalization",
            "review limitation requires an honest closure decision",
        )
    finalizations = snapshot.get("finalizations", {})
    if not finalizations:
        return _command_action("PrepareFinalization", "all current Goals are done")
    raise PolicyError("nonterminal snapshot has no unique next-action class")
