"""Deterministic reducer for the bounded LoopSkill 4 runtime."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from .protocol import (
    CONTENT_STORAGE_MODE,
    LEGACY_ABSENT_STORAGE_MODE,
    MAX_EVENTS_PER_COMMAND,
    PROTOCOL_VERSION,
    ActorRef,
    AuthorityGrant,
    AuthorityGrantV2,
    CommandEnvelope,
    ProtocolRejection,
    Receipt,
    authority_grant_digest,
    domain_digest,
    derive_loop_plan_ref,
    derive_plan_ref,
    goal_chain,
    raw_domain_digest,
    validate_command,
    validate_event_type,
    validate_receipt_size,
    validate_result_payload,
)


@dataclass(frozen=True)
class AuthorityContext:
    actors: Mapping[str, ActorRef]
    grants: Mapping[str, AuthorityGrant | AuthorityGrantV2]
    receipts: Mapping[str, Receipt]
    trusted_actor_issuers: Mapping[str, str] = field(default_factory=dict)
    trusted_grant_issuers: Mapping[str, str] = field(default_factory=dict)
    trusted_receipt_issuers: Mapping[str, str] = field(default_factory=dict)


_COLLECTIONS = {
    "GoalRef": "goals",
    "HostResourceRef": "host_resources",
    "ExternalEffectRef": "external_effects",
    "RouteRef": "routes",
    "DeliveryRef": "deliveries",
    "AttemptRef": "attempts",
    "ResultRef": "results",
    "ReportRef": "reports",
    "ArtifactRef": "artifacts",
    "ReviewRef": "reviews",
    "FinalizationRef": "finalizations",
}

_PREFIX_KIND = {
    "loop-": "LoopRef",
    "goal-": "GoalRef",
    "host-target-": "HostResourceRef",
    "external-effect-": "ExternalEffectRef",
    "route-": "RouteRef",
    "delivery-": "DeliveryRef",
    "attempt-": "AttemptRef",
    "result-": "ResultRef",
    "report-": "ReportRef",
    "artifact-": "ArtifactRef",
    "review-": "ReviewRef",
    "finalization-": "FinalizationRef",
}


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProtocolRejection("INVALID_COMMAND", "invalid trusted timestamp") from exc


def _kind_for_ref(reference: str) -> str | None:
    for prefix, kind in _PREFIX_KIND.items():
        if reference.startswith(prefix):
            return kind
    return None


def _subject_record(snapshot: Mapping[str, Any], reference: str) -> Mapping[str, Any]:
    if reference == "execution":
        return snapshot["execution"]
    if reference == "closure_assurance":
        return snapshot["closure_assurance"]
    if reference == "goal_plan":
        plan = snapshot.get("goal_plan")
        if not isinstance(plan, Mapping):
            raise ProtocolRejection("FOREIGN_REFERENCE", reference)
        return plan
    if reference == snapshot.get("loop_ref"):
        return {"revision": snapshot["loop_revision"]}
    for collection in _COLLECTIONS.values():
        records = snapshot.get(collection, {})
        if reference in records:
            return records[reference]
    raise ProtocolRejection("FOREIGN_REFERENCE", reference)


def _validate_plan_selector(
    grant: AuthorityGrantV2,
    command: CommandEnvelope,
    snapshot: Mapping[str, Any] | None,
) -> None:
    selector = grant.subject_selector
    if set(selector) != {
        "goal_index_max",
        "goal_index_min",
        "include_loop_scope",
        "mode",
        "plan_digest",
    } or (
        selector.get("mode") != "PLAN_DERIVED_V1"
        or selector.get("goal_index_min") != 0
        or not isinstance(selector.get("goal_index_max"), int)
        or not isinstance(selector.get("include_loop_scope"), bool)
    ):
        raise ProtocolRejection("INVALID_AUTHORITY", "invalid plan selector")
    loop_ref = str(command.subject.get("loop_ref", ""))
    subject_kind = str(command.subject.get("subject_kind", ""))
    subject_ref = str(command.subject.get("subject_ref", ""))
    if snapshot is None:
        payload = command.semantic_payload
        if (
            command.command_type != "CreateLoop"
            or payload.get("storage_mode") != CONTENT_STORAGE_MODE
            or payload.get("plan_digest") != selector["plan_digest"]
            or payload.get("goal_count") != selector["goal_index_max"] + 1
            or subject_kind != "LoopRef"
            or subject_ref != loop_ref
            or selector["include_loop_scope"] is not True
        ):
            raise ProtocolRejection(
                "AUTHORITY_SCOPE_MISMATCH", "CreateLoop plan selector"
            )
        return
    plan = snapshot.get("goal_plan")
    if (
        not isinstance(plan, Mapping)
        or plan.get("storage_mode") != CONTENT_STORAGE_MODE
        or plan.get("plan_digest") != selector["plan_digest"]
        or int(plan.get("goal_count", -1)) != selector["goal_index_max"] + 1
    ):
        raise ProtocolRejection("AUTHORITY_SCOPE_MISMATCH", "snapshot plan selector")
    if subject_kind == "LoopRef":
        if not selector["include_loop_scope"] or subject_ref != loop_ref:
            raise ProtocolRejection("AUTHORITY_SCOPE_MISMATCH", "loop selector")
        return
    if subject_kind == "FinalizationRef":
        expected = derive_loop_plan_ref(loop_ref, str(plan["plan_digest"]), subject_kind)
        if not selector["include_loop_scope"] or subject_ref != expected:
            raise ProtocolRejection("AUTHORITY_SCOPE_MISMATCH", "loop-derived selector")
        return
    ids = list(plan.get("ordered_goal_ids", ()))
    digests = list(plan.get("ordered_goal_slice_digests", ()))
    if len(ids) != len(digests) or len(ids) != int(plan.get("goal_count", -1)):
        raise ProtocolRejection("INTERNAL_INVARIANT_VIOLATION", "plan index drift")
    matched = False
    for index, (goal_id, slice_digest) in enumerate(zip(ids, digests)):
        if not selector["goal_index_min"] <= index <= selector["goal_index_max"]:
            continue
        try:
            expected = derive_plan_ref(
                loop_ref,
                str(plan["plan_digest"]),
                str(goal_id),
                str(slice_digest),
                subject_kind,
            )
        except ValueError:
            continue
        if subject_ref == expected:
            matched = True
            break
    if not matched and plan.get("capacity_contract_version") == "loopskill-capacity-v2":
        repair_prefix = {
            "ArtifactRef": "artifact-",
            "AttemptRef": "attempt-",
            "ExternalEffectRef": "external-effect-",
            "HostResourceRef": "host-target-",
            "ReportRef": "report-",
            "ResultRef": "result-",
            "ReviewRef": "review-",
        }.get(subject_kind)
        if repair_prefix is not None:
            for goal_ref, goal in snapshot.get("goals", {}).items():
                goal_id = goal.get("goal_id")
                if not isinstance(goal_id, str):
                    continue
                for repair_ordinal in range(1, int(goal.get("max_attempts", 1))):
                    repair_identity = domain_digest(
                        "loopskill-repair-chain-v1\n",
                        {
                            "goal_id": goal_id,
                            "goal_ref": goal_ref,
                            "loop_ref": loop_ref,
                            "plan_digest": plan["plan_digest"],
                            "repair_ordinal": repair_ordinal,
                        },
                    )
                    if subject_ref == repair_prefix + repair_identity[:24]:
                        matched = True
                        break
                if matched:
                    break
    if not matched:
        raise ProtocolRejection("AUTHORITY_SCOPE_MISMATCH", "plan-derived subject")


def validate_authority(
    command: CommandEnvelope,
    context: AuthorityContext,
    snapshot: Mapping[str, Any] | None = None,
) -> None:
    actor = context.actors.get(command.actor_ref)
    if actor is None or (
        context.trusted_actor_issuers.get(actor.issuer_ref) != actor.issuer_trust
    ):
        raise ProtocolRejection("INVALID_AUTHORITY", "unknown or untrusted Actor")
    if actor.actor_ref != command.actor_ref:
        raise ProtocolRejection("INVALID_AUTHORITY", "Actor registry key mismatch")
    if actor.loop_namespace != str(command.subject.get("loop_ref", "")):
        raise ProtocolRejection("AUTHORITY_SCOPE_MISMATCH", "Actor loop namespace")
    grant = context.grants.get(command.authority_grant_ref)
    if grant is None or grant.actor_ref != command.actor_ref:
        raise ProtocolRejection("INVALID_AUTHORITY", "Grant does not bind Actor")
    if (
        context.trusted_grant_issuers.get(grant.issuer_actor_ref)
        != grant.issuer_trust
    ):
        raise ProtocolRejection("INVALID_AUTHORITY", "Grant issuer is untrusted")
    if grant.issuer_actor_ref not in context.actors:
        raise ProtocolRejection("INVALID_AUTHORITY", "Grant issuer is unknown")
    if grant.canonical_digest != authority_grant_digest(grant):
        raise ProtocolRejection("INVALID_AUTHORITY", "Grant digest mismatch")
    now = _parse_time(command.issued_at)
    if now < _parse_time(grant.not_before) or now > _parse_time(grant.expires_at):
        raise ProtocolRejection("AUTHORITY_EXPIRED", "Grant is not currently valid")
    loop_ref = str(command.subject.get("loop_ref", ""))
    subject_kind = str(command.subject.get("subject_kind", ""))
    subject_ref = str(command.subject.get("subject_ref", loop_ref))
    if grant.loop_scope != loop_ref:
        raise ProtocolRejection("AUTHORITY_SCOPE_MISMATCH", "Grant loop scope")
    if command.command_type not in grant.allowed_commands:
        raise ProtocolRejection("AUTHORITY_SCOPE_MISMATCH", "Grant command scope")
    if subject_kind not in grant.subject_kinds:
        raise ProtocolRejection("AUTHORITY_SCOPE_MISMATCH", "Grant subject kind")
    if isinstance(grant, AuthorityGrantV2):
        if grant.schema != "loopskill-authority-grant-v2":
            raise ProtocolRejection("INVALID_AUTHORITY", "Grant schema mismatch")
        _validate_plan_selector(grant, command, snapshot)
    elif grant.exact_subjects and subject_ref not in grant.exact_subjects:
        raise ProtocolRejection("AUTHORITY_SCOPE_MISMATCH", "Grant exact subject")


def validate_references(
    snapshot: Mapping[str, Any] | None, command: CommandEnvelope
) -> None:
    loop_ref = str(command.subject.get("loop_ref", ""))
    subject_ref = str(command.subject.get("subject_ref", loop_ref))
    subject_kind = str(command.subject.get("subject_kind", ""))
    inferred = _kind_for_ref(subject_ref)
    if inferred is None or inferred != subject_kind:
        raise ProtocolRejection("WRONG_REFERENCE_KIND", subject_ref)
    if subject_kind == "LoopRef":
        if subject_ref != loop_ref:
            raise ProtocolRejection("FOREIGN_REFERENCE", subject_ref)
    elif snapshot is None:
        raise ProtocolRejection("FOREIGN_REFERENCE", subject_ref)
    else:
        collection = _COLLECTIONS.get(subject_kind)
        if collection is None or subject_ref not in snapshot.get(collection, {}):
            raise ProtocolRejection("FOREIGN_REFERENCE", subject_ref)
    if snapshot is not None:
        allocated = command.machine_bindings.get("allocate_refs", {})
        for reference, expected in command.expected_subject_revisions.items():
            actual = _subject_record(snapshot, reference).get("revision")
            if actual != expected:
                raise ProtocolRejection(
                    "STALE_SUBJECT_REVISION",
                    f"{reference}: expected {expected}, actual {actual}",
                )
        for group in command.machine_bindings.values():
            for name, reference in group.items():
                if name.startswith("new_") or name in {
                    "provider_idempotency_key",
                    "receipt",
                }:
                    continue
                if reference.startswith("receipt-"):
                    continue
                if (
                    name == "target_ref"
                    and reference == allocated.get("new_host_resource_ref")
                ):
                    continue
                if _kind_for_ref(reference) and reference != loop_ref:
                    _subject_record(snapshot, reference)


def _receipt(
    command: CommandEnvelope,
    context: AuthorityContext,
    *,
    action: str,
    subject_ref: str,
    attempt_ref: str | None = None,
    target_ref: str | None = None,
    request_digest: str | None = None,
) -> Receipt:
    receipt_ref = command.machine_bindings["receipt_refs"].get("receipt")
    if not receipt_ref:
        raise ProtocolRejection("RECEIPT_REQUIRED", action)
    receipt = context.receipts.get(receipt_ref)
    if receipt is None:
        raise ProtocolRejection("RECEIPT_REQUIRED", receipt_ref)
    validate_receipt_size(receipt)
    if context.trusted_receipt_issuers.get(receipt.issuer_ref) != receipt.issuer_trust:
        raise ProtocolRejection("RECEIPT_ISSUER_UNTRUSTED", receipt_ref)
    now = _parse_time(command.issued_at)
    if now < _parse_time(receipt.issued_at) or now > _parse_time(receipt.expires_at):
        raise ProtocolRejection("RECEIPT_EXPIRED", receipt_ref)
    expected = (
        receipt.action == action
        and receipt.loop_ref == command.subject["loop_ref"]
        and receipt.subject_ref == subject_ref
        and (attempt_ref is None or receipt.attempt_ref == attempt_ref)
        and (target_ref is None or receipt.target_ref == target_ref)
        and (request_digest is None or receipt.request_digest == request_digest)
    )
    if not expected:
        raise ProtocolRejection("RECEIPT_IDENTITY_MISMATCH", receipt_ref)
    return receipt


def _binding(command: CommandEnvelope, group: str, name: str) -> str:
    try:
        return command.machine_bindings[group][name]
    except KeyError as exc:
        raise ProtocolRejection(
            "INVALID_COMMAND", f"missing machine binding {group}.{name}"
        ) from exc


def _event(event_type: str, **body: Any) -> dict[str, Any]:
    validate_event_type(event_type)
    return {"body": body, "type": event_type}


def _only_record(
    snapshot: Mapping[str, Any], collection: str
) -> tuple[str, Mapping[str, Any]]:
    records = snapshot[collection]
    if len(records) != 1:
        raise ProtocolRejection(
            "INTERNAL_INVARIANT_VIOLATION",
            f"alpha slice requires one current {collection} record",
        )
    return next(iter(records.items()))


def _result_chain(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    current_ref = snapshot.get("current_result_ref")
    if isinstance(current_ref, str):
        result_ref = current_ref
        result = snapshot["results"][result_ref]
    else:
        result_ref, result = _only_record(snapshot, "results")
    report_ref = result["report_ref"]
    artifact_ref = result["artifact_ref"]
    attempt_ref = result["attempt_ref"]
    chain = {
        "artifact_ref": artifact_ref,
        "artifact_revision": snapshot["artifacts"][artifact_ref]["revision"],
        "attempt_ref": attempt_ref,
        "attempt_revision": snapshot["attempts"][attempt_ref]["revision"],
        "report_ref": report_ref,
        "report_revision": snapshot["reports"][report_ref]["revision"],
        "result_ref": result_ref,
        "result_revision": result["revision"],
    }
    if "delivery_ref" in result:
        delivery_ref = result["delivery_ref"]
        route_ref = result["route_ref"]
        goal_ref = snapshot["routes"][route_ref]["goal_ref"]
        chain.update(
            {
                "delivery_ref": delivery_ref,
                "delivery_revision": snapshot["deliveries"][delivery_ref]["revision"],
                "route_ref": route_ref,
                "route_revision": snapshot["routes"][route_ref]["revision"],
            }
        )
    else:
        external_effect_ref = result["external_effect_ref"]
        effect = snapshot["external_effects"][external_effect_ref]
        goal_ref = result.get("goal_ref")
        if goal_ref not in snapshot["goals"]:
            goal_ref, _ = _only_record(snapshot, "goals")
        chain.update(
            {
                "external_effect_ref": external_effect_ref,
                "external_effect_revision": effect["revision"],
                "host_resource_ref": effect["host_resource_ref"],
                "host_resource_revision": snapshot["host_resources"]
                [effect["host_resource_ref"]]["revision"],
            }
        )
    chain["goal_ref"] = goal_ref
    chain["goal_revision"] = snapshot["goals"][goal_ref]["revision"]
    return chain


def policy_context(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Canonical freshness surface for optional human-policy decisions."""
    goals = sorted(snapshot.get("goals", {}).items())
    artifacts = sorted(snapshot.get("artifacts", {}).items())
    reviews = sorted(snapshot.get("reviews", {}).items())
    active = [item for item in goals if item[1].get("state") == "ACTIVE"]
    if len(active) == 1 and isinstance(active[0][1].get("chain_refs"), Mapping):
        chain = active[0][1]["chain_refs"]
        goal_entry = active[0]
        artifact = snapshot.get("artifacts", {}).get(chain.get("artifact_ref"))
        review = snapshot.get("reviews", {}).get(chain.get("review_ref"))
        artifact_entry = (
            (str(chain["artifact_ref"]), artifact)
            if isinstance(artifact, Mapping)
            else None
        )
        review_entry = (
            (str(chain["review_ref"]), review)
            if isinstance(review, Mapping)
            else None
        )
    else:
        goal_entry = None if not goals else goals[-1]
        artifact_entry = None if not artifacts else artifacts[-1]
        review_entry = None if not reviews else reviews[-1]
    return {
        "artifact": None
        if artifact_entry is None
        else {
            "ref": artifact_entry[0],
            "revision": artifact_entry[1]["revision"],
            "state": artifact_entry[1]["state"],
        },
        "execution": {
            "revision": snapshot["execution"]["revision"],
            "state": snapshot["execution"]["state"],
        },
        "goal": None
        if goal_entry is None
        else {
            "ref": goal_entry[0],
            "revision": goal_entry[1]["revision"],
            "state": goal_entry[1]["state"],
        },
        "loop_ref": snapshot["loop_ref"],
        "loop_revision": snapshot["loop_revision"],
        "review": None
        if review_entry is None
        else {
            "ref": review_entry[0],
            "revision": review_entry[1]["revision"],
            "state": review_entry[1]["state"],
        },
    }


def policy_context_digest(snapshot: Mapping[str, Any]) -> str:
    return domain_digest("loopskill-human-context-v1\n", policy_context(snapshot))


def _final_chain(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    chain = _result_chain(snapshot)
    matches = [
        (review_ref, review)
        for review_ref, review in snapshot["reviews"].items()
        if review.get("result_ref") == chain["result_ref"]
    ]
    if len(matches) != 1:
        raise ProtocolRejection(
            "INTERNAL_INVARIANT_VIOLATION", "current Review is unavailable"
        )
    review_ref, review = matches[0]
    if review["result_ref"] != chain["result_ref"]:
        raise ProtocolRejection(
            "INTERNAL_INVARIANT_VIOLATION", "Review does not bind current Result"
        )
    chain["review_ref"] = review_ref
    chain["review_revision"] = review["revision"]
    return chain


def _increment_loop(snapshot: dict[str, Any], command: CommandEnvelope) -> None:
    snapshot["loop_revision"] = command.expected_loop_revision + 1


def reduce_command(
    snapshot: Mapping[str, Any] | None,
    command: CommandEnvelope,
    context: AuthorityContext,
    *,
    expected_protocol_version: str = PROTOCOL_VERSION,
    persisted_storage_mode: str = CONTENT_STORAGE_MODE,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    validate_command(
        command, expected_protocol_version=expected_protocol_version
    )
    validate_authority(command, context, snapshot)
    if snapshot is None and command.command_type != "CreateLoop":
        raise ProtocolRejection("INVALID_TRANSITION", "loop does not exist")
    validate_references(snapshot, command)
    reducer = _REDUCERS.get(command.command_type)
    if reducer is None:
        raise ProtocolRejection("INVALID_COMMAND", command.command_type)
    reducer_snapshot = copy.deepcopy(snapshot) if snapshot is not None else None
    if reducer is _advance_goal:
        new_snapshot, events, response = _advance_goal(
            reducer_snapshot,
            command,
            context,
            persisted_storage_mode=persisted_storage_mode,
        )
    else:
        new_snapshot, events, response = reducer(
            reducer_snapshot,
            command,
            context,
        )
    if len(events) > MAX_EVENTS_PER_COMMAND:
        raise ProtocolRejection("RESOURCE_LIMIT_EXCEEDED", "too many events")
    _increment_loop(new_snapshot, command)
    return new_snapshot, events, response


def _create_loop(
    snapshot: dict[str, Any] | None,
    command: CommandEnvelope,
    context: AuthorityContext,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    if snapshot is not None or command.expected_loop_revision != 0:
        raise ProtocolRejection("INVALID_TRANSITION", "loop already exists")
    loop_ref = str(command.subject["loop_ref"])
    goal_ref = _binding(command, "allocate_refs", "new_goal_ref")
    objective = command.semantic_payload.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        raise ProtocolRejection("INVALID_COMMAND", "objective must not be empty")
    objectives = command.semantic_payload.get("goal_plan")
    mode = command.semantic_payload.get("execution_mode")
    max_revisions = command.semantic_payload.get("max_roadmap_revisions")
    storage_mode = command.semantic_payload.get("storage_mode")
    if storage_mode != CONTENT_STORAGE_MODE:
        raise ProtocolRejection(
            "INVALID_COMMAND",
            "v4 CreateLoop requires CONTENT_ADDRESSED_V1 storage",
        )
    common_invalid = (
        not isinstance(objectives, (list, tuple))
        or len(objectives) != 1
        or not all(isinstance(item, str) and item.strip() for item in objectives)
        or len({item.strip() for item in objectives}) != len(objectives)
        or objectives[0].strip() != objective.strip()
        or mode not in {"STANDARD", "ADAPTIVE"}
        or isinstance(max_revisions, bool)
        or not isinstance(max_revisions, int)
        or not 1 <= max_revisions <= 17
        or (mode == "STANDARD" and max_revisions != 1)
    )
    if common_invalid:
        raise ProtocolRejection("INVALID_COMMAND", "invalid confirmed Goal plan")
    goal_count = command.semantic_payload.get("goal_count")
    active_index = command.semantic_payload.get("active_index")
    plan_revision = command.semantic_payload.get("plan_revision")
    goal_id = command.semantic_payload.get("goal_id")
    slice_digest = command.semantic_payload.get("goal_slice_digest")
    ordered_ids = command.semantic_payload.get("ordered_goal_ids")
    ordered_digests = command.semantic_payload.get(
        "ordered_goal_slice_digests"
    )
    plan_identity = command.semantic_payload.get("plan_digest")
    index_identity = command.semantic_payload.get("plan_index_digest")
    authority_digest = command.semantic_payload.get("authority_digest")
    workspace_binding = command.semantic_payload.get("workspace_binding")
    max_host_invocations = command.semantic_payload.get(
        "max_host_invocations"
    )
    wall_clock_seconds = command.semantic_payload.get("wall_clock_seconds")
    max_cost_minor_units = command.semantic_payload.get(
        "max_cost_minor_units"
    )
    stop_policy_digest = command.semantic_payload.get("stop_policy_digest")
    goal_requirement = command.semantic_payload.get("goal_requirement", "required")
    max_attempts = command.semantic_payload.get("max_attempts", 1)
    capacity_version = command.semantic_payload.get("capacity_contract_version")
    goal_limit = 128 if capacity_version == "loopskill-capacity-v2" else 32
    if (
        isinstance(goal_count, bool)
        or not isinstance(goal_count, int)
        or not 1 <= goal_count <= goal_limit
        or active_index != 0
        or plan_revision != 0
        or not isinstance(goal_id, str)
        or not isinstance(slice_digest, str)
        or not isinstance(ordered_ids, (list, tuple))
        or not isinstance(ordered_digests, (list, tuple))
        or len(ordered_ids) != goal_count
        or len(ordered_digests) != goal_count
        or len(set(ordered_ids)) != goal_count
        or goal_id != ordered_ids[0]
        or slice_digest != ordered_digests[0]
        or any(
            not isinstance(value, str) or len(value) != 64
            for value in (
                plan_identity,
                index_identity,
                authority_digest,
                workspace_binding,
                *ordered_digests,
                stop_policy_digest,
            )
        )
        or isinstance(max_host_invocations, bool)
        or not isinstance(max_host_invocations, int)
        or max_host_invocations < goal_count
        or isinstance(wall_clock_seconds, bool)
        or not isinstance(wall_clock_seconds, int)
        or wall_clock_seconds < 1
        or isinstance(max_cost_minor_units, bool)
        or not isinstance(max_cost_minor_units, int)
        or max_cost_minor_units < 0
        or capacity_version not in {"loopskill-capacity-v1", "loopskill-capacity-v2"}
        or goal_requirement not in {"required", "optional"}
        or isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or not 1 <= max_attempts <= 3
        or (
            capacity_version == "loopskill-capacity-v1"
            and (goal_requirement != "required" or max_attempts != 1)
        )
    ):
        raise ProtocolRejection("INVALID_COMMAND", "content plan identity drift")
    objective_digest = domain_digest("loopskill-goal-objective-v1\n", objective)
    state = {
        "artifacts": {},
        "attempts": {},
        "closure_assurance": {"revision": 0, "strength": "NONE"},
        "deliveries": {},
        "execution": {"disposition": None, "revision": 1, "state": "ACTIVE"},
        "finalizations": {},
        "goals": {
            goal_ref: {
                "objective_digest": objective_digest,
                "revision": 1,
                "state": "ACTIVE",
            }
        },
        "host_resources": {},
        "loop_ref": loop_ref,
        "loop_revision": 0,
        "reports": {},
        "results": {},
        "reviews": {},
        "routes": {},
    }
    events = [
        _event("LoopCreated", loop_ref=loop_ref),
        _event("GoalRegistered", goal_ref=goal_ref),
        _event("GoalActivated", goal_ref=goal_ref),
    ]
    response = {"goal_ref": goal_ref, "loop_ref": loop_ref}
    assert isinstance(goal_id, str)
    assert isinstance(slice_digest, str)
    assert isinstance(plan_identity, str)
    chain = goal_chain(loop_ref, plan_identity, goal_id, slice_digest)
    expected = {
        "new_attempt_ref": chain["attempt_ref"],
        "new_external_effect_ref": chain["external_effect_ref"],
        "new_goal_ref": chain["goal_ref"],
        "new_host_resource_ref": chain["host_resource_ref"],
        "provider_idempotency_key": chain["provider_key"],
    }
    if any(
        command.machine_bindings["allocate_refs"].get(name) != value
        for name, value in expected.items()
    ) or command.machine_bindings["resolved_refs"].get(
        "target_ref"
    ) != chain["provider_target"]:
        raise ProtocolRejection(
            "INVALID_COMMAND", "current Goal derivation mismatch"
        )
    state["goals"][goal_ref].update(
        {
            "chain_refs": chain,
            "depends_on": None,
            "goal_id": goal_id,
            "goal_slice_digest": slice_digest,
            "max_attempts": max_attempts,
            "objective": objective.strip(),
            "order": 0,
            "requirement": goal_requirement,
        }
    )
    state["goal_plan"] = {
        "active_goal_ref": goal_ref,
        "active_index": 0,
        "authority_digest": authority_digest,
        "budget": {
            "max_cost_minor_units": max_cost_minor_units,
            "max_host_invocations": max_host_invocations,
            "wall_clock_seconds": wall_clock_seconds,
        },
        "capacity_contract_version": capacity_version,
        "goal_count": goal_count,
        "max_roadmap_revisions": max_revisions,
        "mode": mode,
        "ordered_goal_ids": list(ordered_ids),
        "ordered_goal_slice_digests": list(ordered_digests),
        "plan_digest": plan_identity,
        "plan_index_digest": index_identity,
        "revision": plan_revision,
        "storage_mode": CONTENT_STORAGE_MODE,
        "stop_policy_digest": stop_policy_digest,
        "workspace_binding": workspace_binding,
    }
    events.append(
        _event(
            "GoalPlanRegistered",
            mode=mode,
            plan_digest=plan_identity,
            plan_index_digest=index_identity,
        )
    )
    startup_allocate = {
        "new_attempt_ref",
        "new_external_effect_ref",
        "new_host_resource_ref",
        "provider_idempotency_key",
    }
    startup_resolved = {"provider_action", "target_ref"}
    allocate = command.machine_bindings["allocate_refs"]
    resolved = command.machine_bindings["resolved_refs"]
    startup_present = bool(startup_allocate & set(allocate)) or bool(
        startup_resolved & set(resolved)
    )
    if startup_present:
        if not startup_allocate <= set(allocate) or not startup_resolved <= set(resolved):
            raise ProtocolRejection(
                "INVALID_COMMAND", "incomplete startup external effect bindings"
            )
        manifest_digest = resolved.get("prepared_manifest_digest")
        boundary_digest = resolved.get("boundary_digest")
        bundle_digest = resolved.get("prepared_bundle_digest")
        if not all((manifest_digest, boundary_digest, bundle_digest)):
            raise ProtocolRejection(
                "USER_CONFIRMATION_REQUIRED",
                "startup requires a digest-bound prepared bundle",
            )
        confirmation = _receipt(
            command,
            context,
            action="confirm_start",
            subject_ref=loop_ref,
            target_ref=boundary_digest,
            request_digest=manifest_digest,
        )
        if (
            confirmation.trust_class != "strict"
            or confirmation.outcome != "observed"
            or confirmation.evidence_digest != bundle_digest
        ):
            raise ProtocolRejection(
                "USER_CONFIRMATION_STALE",
                "confirmation does not bind the current prepared bundle",
            )
        state["start_authorization"] = {
            "boundary_digest": boundary_digest,
            "bundle_digest": bundle_digest,
            "manifest_digest": manifest_digest,
            "receipt_ref": confirmation.receipt_ref,
        }
        events.append(
            _event("StartAuthorized", receipt_ref=confirmation.receipt_ref)
        )
        external_effect_ref = allocate["new_external_effect_ref"]
        attempt_ref = allocate["new_attempt_ref"]
        host_resource_ref = allocate["new_host_resource_ref"]
        provider_key = allocate["provider_idempotency_key"]
        action = resolved["provider_action"]
        target_ref = resolved["target_ref"]
        artifact_binding_names = {
            "artifact_baseline_blob_digest",
            "artifact_profile",
            "workspace_identity_digest",
        }
        artifact_binding_present = bool(artifact_binding_names & set(resolved))
        if artifact_binding_present and not artifact_binding_names <= set(resolved):
            raise ProtocolRejection(
                "INVALID_COMMAND", "incomplete startup artifact binding"
            )
        if artifact_binding_present and resolved["artifact_profile"] not in {
            "existing_git",
            "non_git",
            "new_git",
        }:
            raise ProtocolRejection(
                "INVALID_COMMAND", "invalid startup artifact profile"
            )
        if not all(
            (
                external_effect_ref,
                attempt_ref,
                host_resource_ref,
                provider_key,
                action,
                target_ref,
            )
        ):
            raise ProtocolRejection("INVALID_COMMAND", "empty startup effect identity")
        provider_digest = resolved.get("provider_request_digest")
        if not isinstance(provider_digest, str) or len(provider_digest) != 64:
            raise ProtocolRejection(
                "INVALID_COMMAND", "provider request digest is absent"
            )
        provider_request = {
            "active_index": 0,
            "artifact_digest": resolved.get(
                "artifact_baseline_blob_digest", "UNBOUND"
            ),
            "goal_id": command.semantic_payload["goal_id"],
            "goal_slice_digest": command.semantic_payload[
                "goal_slice_digest"
            ],
            "plan_digest": command.semantic_payload["plan_digest"],
            "plan_index_digest": command.semantic_payload[
                "plan_index_digest"
            ],
            "prior_disposition": "",
            "storage_mode": CONTENT_STORAGE_MODE,
            "target_ref": target_ref,
            "workspace_binding": command.semantic_payload[
                "workspace_binding"
            ],
        }
        state["external_effects"] = {
            external_effect_ref: {
                "action": action,
                **(
                    {
                        "artifact_baseline_blob_digest": resolved[
                            "artifact_baseline_blob_digest"
                        ],
                        "artifact_profile": resolved["artifact_profile"],
                        "workspace_identity_digest": resolved[
                            "workspace_identity_digest"
                        ],
                    }
                    if artifact_binding_present
                    else {}
                ),
                "attempt_ref": attempt_ref,
                "goal_ref": goal_ref,
                "host_resource_ref": host_resource_ref,
                "revision": 1,
                "state": "ATTEMPT_COMMITTED",
                "target_ref": target_ref,
            }
        }
        state["attempts"][attempt_ref] = {
            "action": action,
            "automatic_budget_consumed": True,
            "executor_actor_ref": command.actor_ref,
            "executor_grant_ref": command.authority_grant_ref,
            "external_effect_ref": external_effect_ref,
            "ordinal": 1,
            "provider_idempotency_key": provider_key,
            "provider_request": provider_request,
            "provider_request_digest": provider_digest,
            "revision": 1,
            "state": "COMMITTED",
            "subject_kind": "ExternalEffectRef",
            "subject_ref": external_effect_ref,
            "target_ref": target_ref,
        }
        events.append(
            _event("ExternalEffectPrepared", external_effect_ref=external_effect_ref)
        )
        response["external_effect_ref"] = external_effect_ref
    return state, events, response


def _revise_goal_plan(
    snapshot: dict[str, Any] | None,
    command: CommandEnvelope,
    _: AuthorityContext,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Reorder only the existing Adaptive author envelope; never mint a Goal."""
    assert snapshot is not None
    plan = snapshot.get("goal_plan")
    order = command.semantic_payload.get("objective_order")
    reason = command.semantic_payload.get("reason")
    if not isinstance(plan, dict) or plan.get("mode") != "ADAPTIVE":
        raise ProtocolRejection("INVALID_TRANSITION", "Adaptive plan is unavailable")
    if plan.get("storage_mode") == CONTENT_STORAGE_MODE:
        ids = command.semantic_payload.get("ordered_goal_ids")
        digests = command.semantic_payload.get("ordered_goal_slice_digests")
        new_index_digest = command.semantic_payload.get("plan_index_digest")
        new_revision = command.semantic_payload.get("plan_revision")
        current_ids = list(plan.get("ordered_goal_ids", ()))
        current_digests = list(plan.get("ordered_goal_slice_digests", ()))
        active_index = int(plan.get("active_index", -1))
        if (
            not isinstance(ids, (list, tuple))
            or not isinstance(digests, (list, tuple))
            or list(ids[: active_index + 1])
            != current_ids[: active_index + 1]
            or list(digests[: active_index + 1])
            != current_digests[: active_index + 1]
            or len(ids) != len(current_ids)
            or len(digests) != len(current_digests)
            or set(ids) != set(current_ids)
            or len(set(ids)) != len(ids)
            or {
                str(goal_id): str(slice_digest)
                for goal_id, slice_digest in zip(ids, digests)
            }
            != {
                str(goal_id): str(slice_digest)
                for goal_id, slice_digest in zip(current_ids, current_digests)
            }
            or isinstance(new_revision, bool)
            or not isinstance(new_revision, int)
            or new_revision != int(plan.get("revision", -1)) + 1
            or new_revision >= int(plan.get("max_roadmap_revisions", 0))
            or not isinstance(new_index_digest, str)
            or len(new_index_digest) != 64
            or not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > 512
        ):
            raise ProtocolRejection("INVALID_COMMAND", "invalid PlanIndex revision")
        plan.update(
            {
                "ordered_goal_ids": list(ids),
                "ordered_goal_slice_digests": list(digests),
                "plan_index_digest": new_index_digest,
                "revision": new_revision,
            }
        )
        positions = {str(goal_id): index for index, goal_id in enumerate(ids)}
        for goal in snapshot["goals"].values():
            if goal.get("goal_id") in positions:
                goal["order"] = positions[str(goal["goal_id"])]
        reason_digest = domain_digest(
            "loopskill-roadmap-reason-v1\n", reason.strip()
        )
        return snapshot, [
            _event(
                "RoadmapRevised",
                plan_digest=plan["plan_digest"],
                plan_index_digest=new_index_digest,
                reason_digest=reason_digest,
                revision=new_revision,
            )
        ], {"plan_revision": new_revision}
    if int(plan.get("revision", 0)) >= int(plan.get("max_roadmap_revisions", 0)):
        raise ProtocolRejection("INVALID_TRANSITION", "roadmap revision budget exhausted")
    if (
        not isinstance(order, list)
        or not all(isinstance(item, str) and item.strip() for item in order)
        or len(order) != len(plan["ordered_goal_refs"])
        or len(set(item.strip() for item in order)) != len(order)
        or not isinstance(reason, str)
        or not reason.strip()
        or len(reason) > 512
    ):
        raise ProtocolRejection("INVALID_COMMAND", "invalid roadmap revision")
    by_digest = {
        goal["objective_digest"]: goal_ref
        for goal_ref, goal in snapshot["goals"].items()
    }
    digests = [
        domain_digest("loopskill-goal-objective-v1\n", item.strip()) for item in order
    ]
    if set(digests) != set(by_digest) or len(digests) != len(by_digest):
        raise ProtocolRejection("AUTHORITY_SCOPE_MISMATCH", "roadmap left author envelope")
    refs = [by_digest[digest] for digest in digests]
    if refs[0] != plan["active_goal_ref"]:
        raise ProtocolRejection("INVALID_TRANSITION", "active Goal cannot be reordered")
    previous = None
    for index, goal_ref in enumerate(refs):
        goal = snapshot["goals"][goal_ref]
        goal.update({"depends_on": previous, "order": index})
        previous = goal_ref
    revision = int(plan["revision"]) + 1
    plan_digest = domain_digest(
        "loopskill-goal-plan-v1\n",
        {
            "max_roadmap_revisions": int(plan["max_roadmap_revisions"]),
            "mode": "ADAPTIVE",
            "objectives": [item.strip() for item in order],
        },
    )
    plan.update(
        {
            "ordered_goal_refs": refs,
            "plan_digest": plan_digest,
            "revision": revision,
        }
    )
    reason_digest = domain_digest("loopskill-roadmap-reason-v1\n", reason.strip())
    return snapshot, [
        _event(
            "RoadmapRevised",
            plan_digest=plan_digest,
            reason_digest=reason_digest,
            revision=revision,
        )
    ], {"plan_revision": revision}


def _bind_host_resource(
    snapshot: dict[str, Any] | None,
    command: CommandEnvelope,
    context: AuthorityContext,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    assert snapshot is not None
    target_ref = _binding(command, "allocate_refs", "new_host_resource_ref")
    receipt = _receipt(
        command, context, action="bind", subject_ref=target_ref
    )
    snapshot["host_resources"][target_ref] = {
        "receipt_ref": receipt.receipt_ref,
        "revision": 1,
        "state": "BOUND",
    }
    return snapshot, [_event("HostResourceBound", target_ref=target_ref)], {
        "host_resource_ref": target_ref
    }


def _observe_external_effect(
    snapshot: dict[str, Any] | None,
    command: CommandEnvelope,
    context: AuthorityContext,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    assert snapshot is not None
    external_effect_ref = str(command.subject["subject_ref"])
    effect = snapshot["external_effects"][external_effect_ref]
    attempt_ref = effect["attempt_ref"]
    attempt = snapshot["attempts"][attempt_ref]
    prior_state = attempt["state"]
    receipt = _receipt(
        command,
        context,
        action=attempt["action"],
        subject_ref=external_effect_ref,
        attempt_ref=attempt_ref,
        target_ref=attempt["target_ref"],
        request_digest=attempt["provider_request_digest"],
    )
    if receipt.provider_idempotency_key != attempt["provider_idempotency_key"]:
        raise ProtocolRejection("RECEIPT_IDENTITY_MISMATCH", receipt.receipt_ref)
    if receipt.outcome == "observed" and not receipt.provider_resource_ref:
        raise ProtocolRejection(
            "RECEIPT_IDENTITY_MISMATCH",
            "observed Host receipt lacks provider resource identity",
        )
    events = []
    if receipt.outcome == "observed" and receipt.trust_class == "strict":
        new_state = "OBSERVED"
        events.append(
            _event(
                "LateExternalEffectObserved"
                if prior_state in {"UNKNOWN", "UNVERIFIABLE"}
                else "ExternalEffectObserved",
                external_effect_ref=external_effect_ref,
            )
        )
        host_resource_ref = effect["host_resource_ref"]
        existing = snapshot["host_resources"].get(host_resource_ref)
        if existing is None:
            snapshot["host_resources"][host_resource_ref] = {
                "provider_resource_ref": receipt.provider_resource_ref,
                "receipt_ref": receipt.receipt_ref,
                "revision": 1,
                "state": "BOUND",
            }
            events.append(
                _event("HostResourceBound", target_ref=host_resource_ref)
            )
        elif existing["receipt_ref"] != receipt.receipt_ref:
            raise ProtocolRejection(
                "RECEIPT_IDENTITY_MISMATCH", "Host resource already bound"
            )
    elif receipt.outcome == "unknown":
        if prior_state != "COMMITTED":
            raise ProtocolRejection("INVALID_TRANSITION", "late unknown")
        new_state = "UNKNOWN"
        events.append(
            _event("ExternalEffectUnknown", external_effect_ref=external_effect_ref)
        )
    elif receipt.trust_class == "cooperative":
        if prior_state != "COMMITTED":
            raise ProtocolRejection("INVALID_TRANSITION", "late cooperative")
        new_state = "UNVERIFIABLE"
        events.append(
            _event(
                "ExternalEffectUnverifiable",
                external_effect_ref=external_effect_ref,
            )
        )
    else:
        raise ProtocolRejection("RECEIPT_ISSUER_UNTRUSTED", receipt.receipt_ref)
    attempt.update(
        {
            "observation_receipt_ref": receipt.receipt_ref,
            "revision": attempt["revision"] + 1,
            "state": new_state,
        }
    )
    effect.update(
        {
            "observation_receipt_ref": receipt.receipt_ref,
            "revision": effect["revision"] + 1,
            "state": new_state,
        }
    )
    return snapshot, events, {
        "external_effect_state": new_state,
        "host_resource_ref": effect["host_resource_ref"] if new_state == "OBSERVED" else None,
    }


def _prepare_route(
    snapshot: dict[str, Any] | None,
    command: CommandEnvelope,
    _: AuthorityContext,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    assert snapshot is not None
    goal_ref = _binding(command, "resolved_refs", "goal_ref")
    target_ref = _binding(command, "resolved_refs", "target_ref")
    route_ref = _binding(command, "allocate_refs", "new_route_ref")
    delivery_ref = _binding(command, "allocate_refs", "new_delivery_ref")
    if snapshot["goals"][goal_ref]["state"] != "ACTIVE":
        raise ProtocolRejection("INVALID_TRANSITION", "Goal is not active")
    intent = command.semantic_payload.get("intent")
    if not isinstance(intent, str) or not intent.strip():
        raise ProtocolRejection("INVALID_COMMAND", "route intent must not be empty")
    intent_digest = domain_digest("loopskill-route-intent-v1\n", intent)
    snapshot["routes"][route_ref] = {
        "delivery_ref": delivery_ref,
        "goal_ref": goal_ref,
        "intent_digest": intent_digest,
        "revision": 1,
        "target_ref": target_ref,
    }
    snapshot["deliveries"][delivery_ref] = {
        "automatic_attempt_budget": 1,
        "automatic_attempts_consumed": 0,
        "revision": 1,
        "route_ref": route_ref,
        "state": "PREPARED",
        "target_ref": target_ref,
    }
    return snapshot, [_event("RoutePrepared", route_ref=route_ref)], {
        "delivery_ref": delivery_ref,
        "route_ref": route_ref,
    }


def _begin_delivery(
    snapshot: dict[str, Any] | None,
    command: CommandEnvelope,
    _: AuthorityContext,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    assert snapshot is not None
    delivery_ref = str(command.subject["subject_ref"])
    delivery = snapshot["deliveries"][delivery_ref]
    if delivery["state"] != "PREPARED" or delivery["automatic_attempts_consumed"]:
        raise ProtocolRejection("ATTEMPT_ALREADY_CONSUMED", delivery_ref)
    route = snapshot["routes"][delivery["route_ref"]]
    attempt_ref = _binding(command, "allocate_refs", "new_attempt_ref")
    provider_key = _binding(
        command, "allocate_refs", "provider_idempotency_key"
    )
    provider_request = {
        "intent_digest": route["intent_digest"],
        "target_ref": route["target_ref"],
    }
    provider_digest = domain_digest(
        "loopskill-provider-request-v1\n", provider_request
    )
    delivery.update(
        {
            "attempt_ref": attempt_ref,
            "automatic_attempts_consumed": 1,
            "revision": delivery["revision"] + 1,
            "state": "ATTEMPT_COMMITTED",
        }
    )
    snapshot["attempts"][attempt_ref] = {
        "automatic_budget_consumed": True,
        "delivery_ref": delivery_ref,
        "executor_actor_ref": command.actor_ref,
        "executor_grant_ref": command.authority_grant_ref,
        "ordinal": 1,
        "provider_idempotency_key": provider_key,
        "provider_request_digest": provider_digest,
        "revision": 1,
        "state": "COMMITTED",
        "target_ref": route["target_ref"],
    }
    return snapshot, [
        _event("DeliveryAttemptCommitted", attempt_ref=attempt_ref)
    ], {
        "attempt_ref": attempt_ref,
        "provider_idempotency_key": provider_key,
        "provider_request_digest": provider_digest,
    }


def _observe_delivery(
    snapshot: dict[str, Any] | None,
    command: CommandEnvelope,
    context: AuthorityContext,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    assert snapshot is not None
    attempt_ref = str(command.subject["subject_ref"])
    attempt = snapshot["attempts"][attempt_ref]
    delivery = snapshot["deliveries"][attempt["delivery_ref"]]
    prior_state = attempt["state"]
    receipt = _receipt(
        command,
        context,
        action="send",
        subject_ref=attempt["delivery_ref"],
        attempt_ref=attempt_ref,
        target_ref=attempt["target_ref"],
        request_digest=attempt["provider_request_digest"],
    )
    if receipt.provider_idempotency_key != attempt["provider_idempotency_key"]:
        raise ProtocolRejection("RECEIPT_IDENTITY_MISMATCH", receipt.receipt_ref)
    if receipt.outcome == "observed" and receipt.trust_class == "strict":
        new_state = "OBSERVED"
        event_type = (
            "LateDeliveryObserved"
            if prior_state in {"UNKNOWN", "UNVERIFIABLE"}
            else "DeliveryObserved"
        )
    elif receipt.outcome == "unknown":
        if prior_state != "COMMITTED":
            raise ProtocolRejection("INVALID_TRANSITION", "late unknown")
        new_state = "UNKNOWN"
        event_type = "DeliveryUnknown"
    elif receipt.trust_class == "cooperative":
        if prior_state != "COMMITTED":
            raise ProtocolRejection("INVALID_TRANSITION", "late cooperative")
        new_state = "UNVERIFIABLE"
        event_type = "DeliveryUnverifiable"
    else:
        raise ProtocolRejection("RECEIPT_ISSUER_UNTRUSTED", receipt.receipt_ref)
    attempt.update(
        {
            "observation_receipt_ref": receipt.receipt_ref,
            "revision": attempt["revision"] + 1,
            "state": new_state,
        }
    )
    delivery.update(
        {"revision": delivery["revision"] + 1, "state": new_state}
    )
    return snapshot, [_event(event_type, attempt_ref=attempt_ref)], {
        "attempt_state": new_state,
        "delivery_state": new_state,
    }


def _stage_result(
    snapshot: dict[str, Any] | None,
    command: CommandEnvelope,
    _: AuthorityContext,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    assert snapshot is not None
    route_ref = str(command.subject["subject_ref"])
    route = snapshot["routes"][route_ref]
    delivery = snapshot["deliveries"][route["delivery_ref"]]
    if delivery["state"] not in {"OBSERVED", "UNKNOWN", "UNVERIFIABLE"}:
        raise ProtocolRejection("INVALID_TRANSITION", "Delivery not observed")
    result_ref = _binding(command, "allocate_refs", "new_result_ref")
    report_ref = _binding(command, "allocate_refs", "new_report_ref")
    result_payload = validate_result_payload(command.semantic_payload)
    outcome = result_payload["outcome"]
    summary = result_payload["summary"]
    report_content = {"outcome": outcome, "summary": summary}
    report_digest = domain_digest("loopskill-report-v1\n", report_content)
    snapshot["results"][result_ref] = {
        "attempt_ref": delivery["attempt_ref"],
        "delivery_ref": route["delivery_ref"],
        "outcome": outcome,
        "report_ref": report_ref,
        "revision": 1,
        "route_ref": route_ref,
        "state": "STAGED",
    }
    snapshot["reports"][report_ref] = {
        "author_actor_ref": command.actor_ref,
        "content_digest": report_digest,
        "result_ref": result_ref,
        "revision": 1,
        "state": "STAGED",
    }
    if "goal_plan" in snapshot:
        snapshot["current_result_ref"] = result_ref
    return snapshot, [
        _event("ResultStaged", result_ref=result_ref),
        _event("ReportStaged", report_ref=report_ref),
    ], {"report_ref": report_ref, "result_ref": result_ref}


def _stage_external_result(
    snapshot: dict[str, Any] | None,
    command: CommandEnvelope,
    _: AuthorityContext,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    assert snapshot is not None
    external_effect_ref = str(command.subject["subject_ref"])
    effect = snapshot["external_effects"][external_effect_ref]
    if effect["state"] not in {"OBSERVED", "UNKNOWN", "UNVERIFIABLE"}:
        raise ProtocolRejection("INVALID_TRANSITION", "External effect is unresolved")
    result_ref = _binding(command, "allocate_refs", "new_result_ref")
    report_ref = _binding(command, "allocate_refs", "new_report_ref")
    source_observation_digest = _binding(
        command, "resolved_refs", "source_observation_digest"
    )
    if len(source_observation_digest) != 64 or any(
        character not in "0123456789abcdef"
        for character in source_observation_digest
    ):
        raise ProtocolRejection(
            "RECEIPT_IDENTITY_MISMATCH", "invalid Host result observation digest"
        )
    result_payload = validate_result_payload(command.semantic_payload)
    outcome = result_payload["outcome"]
    summary = result_payload["summary"]
    report_digest = domain_digest(
        "loopskill-report-v1\n", {"outcome": outcome, "summary": summary}
    )
    active_goals = [
        goal_ref
        for goal_ref, goal in snapshot["goals"].items()
        if goal.get("state") == "ACTIVE"
    ]
    if len(active_goals) != 1:
        raise ProtocolRejection("INVALID_TRANSITION", "active Goal is unavailable")
    snapshot["results"][result_ref] = {
        "attempt_ref": effect["attempt_ref"],
        "external_effect_ref": external_effect_ref,
        "goal_ref": active_goals[0],
        "outcome": outcome,
        "report_ref": report_ref,
        "revision": 1,
        "source_observation_digest": source_observation_digest,
        "state": "STAGED",
    }
    snapshot["reports"][report_ref] = {
        "author_actor_ref": command.actor_ref,
        "content_digest": report_digest,
        "result_ref": result_ref,
        "revision": 1,
        "state": "STAGED",
    }
    if "goal_plan" in snapshot:
        snapshot["current_result_ref"] = result_ref
    return snapshot, [
        _event("ResultStaged", result_ref=result_ref),
        _event("ReportStaged", report_ref=report_ref),
    ], {"report_ref": report_ref, "result_ref": result_ref}


def _acknowledge_result(
    snapshot: dict[str, Any] | None,
    command: CommandEnvelope,
    context: AuthorityContext,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    assert snapshot is not None
    result_ref = str(command.subject["subject_ref"])
    result = snapshot["results"][result_ref]
    report = snapshot["reports"][result["report_ref"]]
    if result["state"] != "STAGED" or report["state"] != "STAGED":
        raise ProtocolRejection("INVALID_TRANSITION", "Result not staged")
    artifact_ref = _binding(command, "allocate_refs", "new_artifact_ref")
    artifact_digest = _binding(command, "resolved_refs", "artifact_digest")
    capture_state = _binding(command, "resolved_refs", "capture_state")
    artifact_profile = _binding(command, "resolved_refs", "artifact_profile")
    manifest_digest = _binding(command, "resolved_refs", "manifest_digest")
    verification_digest = _binding(
        command, "resolved_refs", "verification_digest"
    )
    verification_state = _binding(command, "resolved_refs", "verification_state")
    receipt = _receipt(
        command,
        context,
        action="verify-artifact",
        subject_ref=artifact_ref,
        request_digest=verification_digest,
    )
    if receipt.evidence_digest != artifact_digest:
        raise ProtocolRejection(
            "RECEIPT_IDENTITY_MISMATCH", "artifact receipt evidence"
        )
    if capture_state not in {"CAPTURED", "UNAVAILABLE"}:
        raise ProtocolRejection("INVALID_COMMAND", "invalid artifact capture state")
    if verification_state not in {"VERIFIED", "FAILED", "UNVERIFIABLE"}:
        raise ProtocolRejection("INVALID_COMMAND", "invalid local verification state")
    if receipt.trust_class == "strict" and receipt.outcome == "observed":
        artifact_state = "VERIFIED"
        verification_event = "ArtifactVerified"
    elif receipt.trust_class == "cooperative" and receipt.outcome == "unverifiable":
        artifact_state = "UNVERIFIABLE"
        verification_event = "ArtifactUnverifiable"
    else:
        raise ProtocolRejection(
            "RECEIPT_IDENTITY_MISMATCH", "artifact receipt assurance"
        )
    if artifact_state == "VERIFIED" and capture_state != "CAPTURED":
        raise ProtocolRejection(
            "RECEIPT_IDENTITY_MISMATCH", "verified artifact was not captured"
        )
    snapshot["artifacts"][artifact_ref] = {
        "content_digest": artifact_digest,
        "capture_state": capture_state,
        "manifest_digest": manifest_digest,
        "profile": artifact_profile,
        "receipt_ref": receipt.receipt_ref,
        "result_ref": result_ref,
        "revision": 1,
        "state": artifact_state,
        "verification_digest": verification_digest,
        "verification_state": verification_state,
    }
    report.update({"revision": report["revision"] + 1, "state": "ACCEPTED"})
    result.update(
        {
            "artifact_ref": artifact_ref,
            "revision": result["revision"] + 1,
            "state": "ACKNOWLEDGED",
        }
    )
    artifact_events = []
    if capture_state == "CAPTURED":
        artifact_events.append(_event("ArtifactCaptured", artifact_ref=artifact_ref))
    artifact_events.append(_event(verification_event, artifact_ref=artifact_ref))
    return snapshot, artifact_events + [
        _event("ReportAccepted", report_ref=result["report_ref"]),
        _event("ResultAcknowledged", result_ref=result_ref),
    ], {"artifact_ref": artifact_ref, "result_ref": result_ref}


def _record_review(
    snapshot: dict[str, Any] | None,
    command: CommandEnvelope,
    _: AuthorityContext,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    assert snapshot is not None
    result_ref = str(command.subject["subject_ref"])
    result = snapshot["results"][result_ref]
    if result["state"] != "ACKNOWLEDGED":
        raise ProtocolRejection("INVALID_TRANSITION", "Result not acknowledged")
    verdict = command.semantic_payload.get("verdict")
    if verdict not in {"PASS", "REPAIR", "LIMITATION"}:
        raise ProtocolRejection("INVALID_COMMAND", "invalid review verdict")
    review_ref = _binding(command, "allocate_refs", "new_review_ref")
    chain_digest = domain_digest(
        "loopskill-subject-chain-v1\n", _result_chain(snapshot)
    )
    snapshot["reviews"][review_ref] = {
        "artifact_ref": result["artifact_ref"],
        "report_ref": result["report_ref"],
        "result_ref": result_ref,
        "reviewer_actor_ref": command.actor_ref,
        "revision": 1,
        "state": verdict,
        "subject_chain_digest": chain_digest,
    }
    return snapshot, [_event("ReviewRecorded", review_ref=review_ref)], {
        "review_ref": review_ref,
        "verdict": verdict,
    }


def _advance_goal(
    snapshot: dict[str, Any] | None,
    command: CommandEnvelope,
    _: AuthorityContext,
    *,
    persisted_storage_mode: str = CONTENT_STORAGE_MODE,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    assert snapshot is not None
    goal_ref = str(command.subject["subject_ref"])
    review_ref = _binding(command, "resolved_refs", "review_ref")
    disposition = command.semantic_payload.get("disposition")
    goal = snapshot["goals"].get(goal_ref)
    review = snapshot["reviews"].get(review_ref)
    if not isinstance(goal, Mapping) or not isinstance(review, Mapping):
        raise ProtocolRejection("INVALID_TRANSITION", "Goal review is unavailable")
    result_ref = review.get("result_ref")
    if not isinstance(result_ref, str):
        raise ProtocolRejection("INVALID_TRANSITION", "Goal result is unavailable")
    result = snapshot["results"].get(result_ref)
    if not isinstance(result, Mapping):
        raise ProtocolRejection("INVALID_TRANSITION", "Goal result is unavailable")
    if goal.get("state") != "ACTIVE":
        raise ProtocolRejection("INVALID_TRANSITION", "Goal is not active")
    if (
        result.get("state") != "ACKNOWLEDGED"
        or review.get("report_ref") != result.get("report_ref")
        or review.get("artifact_ref") != result.get("artifact_ref")
    ):
        raise ProtocolRejection(
            "INVALID_TRANSITION", "Review does not bind an acknowledged Result"
        )
    bound_goal_refs: list[str] = []
    if isinstance(result.get("goal_ref"), str):
        bound_goal_refs.append(str(result["goal_ref"]))
    route_ref = result.get("route_ref")
    if isinstance(route_ref, str):
        route = snapshot["routes"].get(route_ref)
        if not isinstance(route, Mapping) or not isinstance(route.get("goal_ref"), str):
            raise ProtocolRejection(
                "INVALID_TRANSITION", "Result route does not bind a Goal"
            )
        bound_goal_refs.append(str(route["goal_ref"]))
    effect_ref = result.get("external_effect_ref")
    if isinstance(effect_ref, str):
        effect = snapshot["external_effects"].get(effect_ref)
        if not isinstance(effect, Mapping):
            raise ProtocolRejection(
                "INVALID_TRANSITION", "Result effect does not bind a Goal"
            )
        effect_goal_ref = effect.get("goal_ref")
        if isinstance(effect_goal_ref, str):
            bound_goal_refs.append(effect_goal_ref)
        elif (
            persisted_storage_mode != LEGACY_ABSENT_STORAGE_MODE
            or "goal_ref" in effect
        ):
            raise ProtocolRejection(
                "INVALID_TRANSITION", "Result effect does not bind a Goal"
            )
    if not bound_goal_refs or any(reference != goal_ref for reference in bound_goal_refs):
        raise ProtocolRejection(
            "INVALID_TRANSITION", "Review Result does not bind the subject Goal"
        )
    allowed = {
        "DONE": result.get("outcome") == "PASS"
        and review.get("state") == "PASS",
        "FAILED": result.get("outcome") == "FAILED"
        and review.get("state") in {"PASS", "LIMITATION"},
        "LIMITATION": review.get("state") == "LIMITATION",
        "SKIPPED": goal.get("requirement") == "optional"
        and review.get("state") == "LIMITATION"
        and result.get("outcome") in {"BLOCKED", "LIMITATION", "UNVERIFIABLE"},
    }
    if disposition not in allowed or not allowed[disposition]:
        raise ProtocolRejection("INVALID_TRANSITION", "Goal cannot advance")
    goal.update({"revision": goal["revision"] + 1, "state": disposition})
    events = [_event("GoalAdvanced", goal_ref=goal_ref)]
    plan = snapshot.get("goal_plan")
    next_goal_ref = None
    if (
        disposition in {"DONE", "SKIPPED"}
        and isinstance(plan, dict)
        and plan.get("storage_mode") == CONTENT_STORAGE_MODE
    ):
        active_index = int(plan.get("active_index", -1))
        ordered_ids = list(plan.get("ordered_goal_ids", ()))
        ordered_digests = list(plan.get("ordered_goal_slice_digests", ()))
        if (
            active_index < 0
            or active_index >= len(ordered_ids)
            or len(ordered_ids) != int(plan.get("goal_count", -1))
            or len(ordered_digests) != len(ordered_ids)
            or plan.get("active_goal_ref") != goal_ref
        ):
            raise ProtocolRejection(
                "INTERNAL_INVARIANT_VIOLATION", "active plan index drift"
            )
        next_index = active_index + 1
        if next_index < len(ordered_ids):
            next_goal_id = str(ordered_ids[next_index])
            next_slice_digest = str(ordered_digests[next_index])
            chain = goal_chain(
                str(snapshot["loop_ref"]),
                str(plan["plan_digest"]),
                next_goal_id,
                next_slice_digest,
            )
            allocate = command.machine_bindings["allocate_refs"]
            expected_allocate = {
                "new_attempt_ref": chain["attempt_ref"],
                "new_external_effect_ref": chain["external_effect_ref"],
                "new_goal_ref": chain["goal_ref"],
                "new_host_resource_ref": chain["host_resource_ref"],
                "provider_idempotency_key": chain["provider_key"],
            }
            resolved = command.machine_bindings["resolved_refs"]
            try:
                next_max_attempts = int(resolved.get("next_max_attempts", "1"))
            except ValueError as exc:
                raise ProtocolRejection(
                    "INVALID_COMMAND", "next Goal max attempts is invalid"
                ) from exc
            if (
                any(allocate.get(name) != value for name, value in expected_allocate.items())
                or resolved.get("next_goal_id") != next_goal_id
                or resolved.get("next_goal_slice_digest") != next_slice_digest
                or resolved.get("provider_target") != chain["provider_target"]
                or resolved.get("plan_digest") != plan["plan_digest"]
                or resolved.get("plan_index_digest") != plan["plan_index_digest"]
                or resolved.get("workspace_identity_digest")
                != plan["workspace_binding"]
                or resolved.get("next_goal_requirement", "required")
                not in {"required", "optional"}
                or not 1 <= next_max_attempts <= 3
            ):
                raise ProtocolRejection(
                    "INVALID_TRANSITION", "next Goal descriptor drift"
                )
            objective_digest = resolved.get("next_objective_digest")
            provider_digest = resolved.get("provider_request_digest")
            baseline_names = {
                "artifact_baseline_blob_digest",
                "artifact_profile",
                "workspace_identity_digest",
            }
            if (
                not isinstance(objective_digest, str)
                or len(objective_digest) != 64
                or not isinstance(provider_digest, str)
                or len(provider_digest) != 64
                or not baseline_names <= set(resolved)
                or resolved["artifact_profile"]
                not in {"existing_git", "non_git", "new_git"}
                or chain["goal_ref"] in snapshot["goals"]
                or chain["attempt_ref"] in snapshot["attempts"]
                or chain["external_effect_ref"] in snapshot["external_effects"]
            ):
                raise ProtocolRejection(
                    "INVALID_COMMAND", "next Goal materialization is incomplete"
                )
            snapshot["goals"][chain["goal_ref"]] = {
                "chain_refs": chain,
                "depends_on": goal_ref,
                "goal_id": next_goal_id,
                "goal_slice_digest": next_slice_digest,
                "max_attempts": next_max_attempts,
                "objective_digest": objective_digest,
                "order": next_index,
                "requirement": resolved.get("next_goal_requirement", "required"),
                "revision": 1,
                "state": "ACTIVE",
            }
            descriptor = {
                "active_index": next_index,
                "artifact_digest": resolved["artifact_baseline_blob_digest"],
                "goal_id": next_goal_id,
                "goal_slice_digest": next_slice_digest,
                "plan_digest": plan["plan_digest"],
                "plan_index_digest": plan["plan_index_digest"],
                "prior_disposition": disposition,
                "storage_mode": CONTENT_STORAGE_MODE,
                "target_ref": chain["provider_target"],
                "workspace_binding": plan["workspace_binding"],
            }
            snapshot["external_effects"][chain["external_effect_ref"]] = {
                "action": "create_task",
                "artifact_baseline_blob_digest": resolved[
                    "artifact_baseline_blob_digest"
                ],
                "artifact_profile": resolved["artifact_profile"],
                "attempt_ref": chain["attempt_ref"],
                "goal_ref": chain["goal_ref"],
                "host_resource_ref": chain["host_resource_ref"],
                "revision": 1,
                "state": "ATTEMPT_COMMITTED",
                "target_ref": chain["provider_target"],
                "workspace_identity_digest": resolved[
                    "workspace_identity_digest"
                ],
            }
            snapshot["attempts"][chain["attempt_ref"]] = {
                "action": "create_task",
                "automatic_budget_consumed": True,
                "executor_actor_ref": command.actor_ref,
                "executor_grant_ref": command.authority_grant_ref,
                "external_effect_ref": chain["external_effect_ref"],
                "ordinal": next_index + 1,
                "provider_idempotency_key": chain["provider_key"],
                "provider_request": descriptor,
                "provider_request_digest": provider_digest,
                "revision": 1,
                "state": "COMMITTED",
                "subject_kind": "ExternalEffectRef",
                "subject_ref": chain["external_effect_ref"],
                "target_ref": chain["provider_target"],
            }
            plan["active_goal_ref"] = chain["goal_ref"]
            plan["active_index"] = next_index
            next_goal_ref = chain["goal_ref"]
            events.append(_event("GoalRegistered", goal_ref=chain["goal_ref"]))
            events.append(_event("GoalActivated", goal_ref=chain["goal_ref"]))
            events.append(
                _event(
                    "ExternalEffectPrepared",
                    external_effect_ref=chain["external_effect_ref"],
                )
            )
    elif disposition in {"DONE", "SKIPPED"} and isinstance(plan, dict):
        ordered = list(plan["ordered_goal_refs"])
        position = ordered.index(goal_ref)
        if position + 1 < len(ordered):
            candidate = ordered[position + 1]
            next_goal = snapshot["goals"][candidate]
            if next_goal.get("depends_on") != goal_ref or next_goal["state"] != "PENDING":
                raise ProtocolRejection(
                    "INTERNAL_INVARIANT_VIOLATION", "Goal dependency order drift"
                )
            next_goal.update(
                {"revision": next_goal["revision"] + 1, "state": "ACTIVE"}
            )
            chain = next_goal.get("chain_refs")
            if not isinstance(chain, dict):
                raise ProtocolRejection(
                    "INTERNAL_INVARIANT_VIOLATION", "next Goal chain is absent"
                )
            required_chain = {
                "attempt_ref",
                "external_effect_ref",
                "host_resource_ref",
                "provider_key",
                "provider_target",
            }
            if not required_chain <= set(chain):
                raise ProtocolRejection(
                    "INTERNAL_INVARIANT_VIOLATION", "next Goal chain is incomplete"
                )
            attempt_ref = str(chain["attempt_ref"])
            effect_ref = str(chain["external_effect_ref"])
            if attempt_ref in snapshot["attempts"] or effect_ref in snapshot["external_effects"]:
                raise ProtocolRejection(
                    "ATTEMPT_ALREADY_CONSUMED", "next Goal Attempt already exists"
                )
            previous_attempt = snapshot["attempts"][result["attempt_ref"]]
            provider_request = dict(previous_attempt["provider_request"])
            provider_request.update(
                {
                    "goal": next_goal["objective"],
                    "target_ref": chain["provider_target"],
                }
            )
            provider_digest = domain_digest(
                "loopskill-provider-request-v1\n", provider_request
            )
            baseline_names = {
                "artifact_baseline_blob_digest",
                "artifact_profile",
                "workspace_identity_digest",
            }
            resolved = command.machine_bindings["resolved_refs"]
            if not baseline_names <= set(resolved) or resolved["artifact_profile"] not in {
                "existing_git",
                "non_git",
                "new_git",
            }:
                raise ProtocolRejection(
                    "INVALID_COMMAND", "next Goal artifact baseline is incomplete"
                )
            snapshot["external_effects"][effect_ref] = {
                "action": previous_attempt["action"],
                "artifact_baseline_blob_digest": resolved[
                    "artifact_baseline_blob_digest"
                ],
                "artifact_profile": resolved["artifact_profile"],
                "attempt_ref": attempt_ref,
                "goal_ref": candidate,
                "host_resource_ref": chain["host_resource_ref"],
                "revision": 1,
                "state": "ATTEMPT_COMMITTED",
                "target_ref": chain["provider_target"],
                "workspace_identity_digest": resolved["workspace_identity_digest"],
            }
            snapshot["attempts"][attempt_ref] = {
                "action": previous_attempt["action"],
                "automatic_budget_consumed": True,
                "executor_actor_ref": command.actor_ref,
                "executor_grant_ref": command.authority_grant_ref,
                "external_effect_ref": effect_ref,
                "ordinal": position + 2,
                "provider_idempotency_key": chain["provider_key"],
                "provider_request": provider_request,
                "provider_request_digest": provider_digest,
                "revision": 1,
                "state": "COMMITTED",
                "subject_kind": "ExternalEffectRef",
                "subject_ref": effect_ref,
                "target_ref": chain["provider_target"],
            }
            plan["active_goal_ref"] = candidate
            next_goal_ref = candidate
            events.append(_event("GoalActivated", goal_ref=candidate))
            events.append(_event("ExternalEffectPrepared", external_effect_ref=effect_ref))
    if disposition == "SKIPPED":
        events.append(_event("GoalSkipped", goal_ref=goal_ref))
    return snapshot, events, {
        "goal_state": disposition,
        "next_goal_ref": next_goal_ref,
    }


def _record_policy_decision(
    snapshot: dict[str, Any] | None,
    command: CommandEnvelope,
    _: AuthorityContext,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    assert snapshot is not None
    decision = command.semantic_payload.get("decision")
    fingerprint = command.semantic_payload.get("failure_fingerprint")
    if decision not in {"CONTINUE_REPAIR", "WAIT", "STOP"}:
        raise ProtocolRejection("INVALID_COMMAND", "invalid policy decision")
    if not isinstance(fingerprint, str) or len(fingerprint) > 512:
        raise ProtocolRejection("INVALID_COMMAND", "invalid failure fingerprint")
    context_digest = _binding(command, "resolved_refs", "context_digest")
    card_digest = _binding(command, "resolved_refs", "decision_card_digest")
    if context_digest != policy_context_digest(snapshot) or not card_digest:
        raise ProtocolRejection("STALE_SUBJECT_REVISION", "policy context changed")
    policy = snapshot.setdefault(
        "policy",
        {
            "decision_revision": 0,
            "repair_attempts": 0,
            "same_failure_count": 0,
            "state": "IDLE",
        },
    )
    events = [
        _event(
            "HumanDecisionRecorded",
            decision=decision,
            decision_card_digest=card_digest,
        )
    ]
    response: dict[str, Any] = {"decision": decision}
    if decision == "CONTINUE_REPAIR":
        active_goals = [
            (goal_ref, goal)
            for goal_ref, goal in snapshot["goals"].items()
            if goal.get("state") == "ACTIVE"
        ]
        if len(active_goals) != 1:
            raise ProtocolRejection(
                "INVALID_TRANSITION", "repair requires one active Goal"
            )
        goal_ref, _ = active_goals[0]
        chain = active_goals[0][1].get("chain_refs")
        current_review = (
            snapshot.get("reviews", {}).get(chain.get("review_ref"))
            if isinstance(chain, Mapping)
            else None
        )
        if (
            not isinstance(current_review, Mapping)
            or current_review.get("state") != "REPAIR"
            or not fingerprint
        ):
            raise ProtocolRejection(
                "INVALID_TRANSITION", "repair requires the current REPAIR review"
            )
        if policy.get("goal_ref") != goal_ref:
            policy.update(
                {
                    "goal_ref": goal_ref,
                    "last_failure_digest": None,
                    "repair_attempts": 0,
                    "same_failure_count": 0,
                }
            )
        try:
            repair_budget = int(_binding(command, "resolved_refs", "repair_budget"))
            same_budget = int(
                _binding(command, "resolved_refs", "same_failure_budget")
            )
        except ValueError as exc:
            raise ProtocolRejection("INVALID_COMMAND", "invalid repair budget") from exc
        if not (1 <= repair_budget <= 3 and 1 <= same_budget <= 2):
            raise ProtocolRejection("INVALID_COMMAND", "repair budget exceeds Core cap")
        failure_digest = domain_digest("loopskill-failure-fingerprint-v1\n", fingerprint)
        same_count = (
            int(policy.get("same_failure_count", 0)) + 1
            if policy.get("last_failure_digest") == failure_digest
            else 1
        )
        attempts = int(policy.get("repair_attempts", 0))
        exhausted = attempts >= repair_budget or same_count >= same_budget
        policy.update(
            {
                "decision_card_digest": card_digest,
                "decision_revision": int(policy.get("decision_revision", 0)) + 1,
                "last_decision": decision,
                "last_failure_digest": failure_digest,
                "same_failure_count": same_count,
                "state": "EXHAUSTED" if exhausted else "AUTHORIZED",
            }
        )
        if not exhausted:
            policy["repair_attempts"] = attempts + 1
            events.append(_event("RepairAuthorized", attempt_ordinal=attempts + 1))
            allocate = command.machine_bindings["allocate_refs"]
            if allocate:
                plan = snapshot.get("goal_plan")
                if (
                    not isinstance(plan, Mapping)
                    or plan.get("storage_mode") != CONTENT_STORAGE_MODE
                    or len(active_goals) != 1
                ):
                    raise ProtocolRejection(
                        "INVALID_TRANSITION", "repair scheduling requires one active content Goal"
                    )
                goal_ref, goal = active_goals[0]
                goal_id = str(goal.get("goal_id", ""))
                repair_ordinal = attempts + 1
                repair_identity = domain_digest(
                    "loopskill-repair-chain-v1\n",
                    {
                        "goal_id": goal_id,
                        "goal_ref": goal_ref,
                        "loop_ref": snapshot["loop_ref"],
                        "plan_digest": plan["plan_digest"],
                        "repair_ordinal": repair_ordinal,
                    },
                )
                suffix = repair_identity[:24]
                expected_allocate = {
                    "new_artifact_ref": f"artifact-{suffix}",
                    "new_attempt_ref": f"attempt-{suffix}",
                    "new_external_effect_ref": f"external-effect-{suffix}",
                    "new_host_resource_ref": f"host-target-{suffix}",
                    "new_report_ref": f"report-{suffix}",
                    "new_result_ref": f"result-{suffix}",
                    "new_review_ref": f"review-{suffix}",
                    "provider_idempotency_key": domain_digest(
                        "loopskill-provider-idempotency-v1\n",
                        {"repair_chain": repair_identity},
                    ),
                }
                if dict(allocate) != expected_allocate:
                    raise ProtocolRejection(
                        "INVALID_COMMAND", "repair chain identity drift"
                    )
                resolved = command.machine_bindings["resolved_refs"]
                target_ref = f"host-target-{suffix}"
                required_resolved = {
                    "artifact_baseline_blob_digest",
                    "artifact_profile",
                    "provider_request_digest",
                    "target_ref",
                    "workspace_identity_digest",
                }
                if (
                    not required_resolved <= set(resolved)
                    or resolved["target_ref"] != target_ref
                    or resolved["workspace_identity_digest"] != plan["workspace_binding"]
                    or resolved["artifact_profile"]
                    not in {"existing_git", "non_git", "new_git"}
                    or any(
                        not isinstance(resolved[name], str) or len(resolved[name]) != 64
                        for name in (
                            "artifact_baseline_blob_digest",
                            "provider_request_digest",
                            "workspace_identity_digest",
                        )
                    )
                    or expected_allocate["new_attempt_ref"] in snapshot["attempts"]
                    or expected_allocate["new_external_effect_ref"]
                    in snapshot["external_effects"]
                ):
                    raise ProtocolRejection(
                        "INVALID_COMMAND", "repair materialization is incomplete"
                    )
                chain = {
                    "artifact_ref": expected_allocate["new_artifact_ref"],
                    "attempt_ref": expected_allocate["new_attempt_ref"],
                    "external_effect_ref": expected_allocate["new_external_effect_ref"],
                    "goal_ref": goal_ref,
                    "host_resource_ref": expected_allocate["new_host_resource_ref"],
                    "provider_key": expected_allocate["provider_idempotency_key"],
                    "provider_target": target_ref,
                    "report_ref": expected_allocate["new_report_ref"],
                    "result_ref": expected_allocate["new_result_ref"],
                    "review_ref": expected_allocate["new_review_ref"],
                }
                goal["chain_refs"] = chain
                effect_ref = chain["external_effect_ref"]
                attempt_ref = chain["attempt_ref"]
                snapshot["external_effects"][effect_ref] = {
                    "action": "create_task",
                    "artifact_baseline_blob_digest": resolved[
                        "artifact_baseline_blob_digest"
                    ],
                    "artifact_profile": resolved["artifact_profile"],
                    "attempt_ref": attempt_ref,
                    "goal_ref": goal_ref,
                    "host_resource_ref": chain["host_resource_ref"],
                    "revision": 1,
                    "state": "ATTEMPT_COMMITTED",
                    "target_ref": target_ref,
                    "workspace_identity_digest": resolved[
                        "workspace_identity_digest"
                    ],
                }
                snapshot["attempts"][attempt_ref] = {
                    "action": "create_task",
                    "automatic_budget_consumed": True,
                    "executor_actor_ref": command.actor_ref,
                    "executor_grant_ref": command.authority_grant_ref,
                    "external_effect_ref": effect_ref,
                    "ordinal": len(snapshot["attempts"]) + 1,
                    "provider_idempotency_key": chain["provider_key"],
                    "provider_request": {
                        "active_index": int(plan["active_index"]),
                        "artifact_digest": resolved[
                            "artifact_baseline_blob_digest"
                        ],
                        "goal_id": goal_id,
                        "goal_slice_digest": goal["goal_slice_digest"],
                        "plan_digest": plan["plan_digest"],
                        "plan_index_digest": plan["plan_index_digest"],
                        "prior_disposition": "REPAIR",
                        "storage_mode": CONTENT_STORAGE_MODE,
                        "target_ref": target_ref,
                        "workspace_binding": plan["workspace_binding"],
                    },
                    "provider_request_digest": resolved["provider_request_digest"],
                    "revision": 1,
                    "state": "COMMITTED",
                    "subject_kind": "ExternalEffectRef",
                    "subject_ref": effect_ref,
                    "target_ref": target_ref,
                }
                policy["state"] = "REPAIR_SCHEDULED"
                events.append(
                    _event(
                        "RepairAttemptScheduled",
                        attempt_ref=attempt_ref,
                        goal_ref=goal_ref,
                    )
                )
        else:
            events.append(_event("RepairExhausted"))
        response.update(
            {
                "repair_authorized": not exhausted,
                "repair_state": policy["state"],
            }
        )
    else:
        policy.update(
            {
                "decision_card_digest": card_digest,
                "decision_revision": int(policy.get("decision_revision", 0)) + 1,
                "last_decision": decision,
                "state": "EXECUTION_PENDING",
            }
        )
    return snapshot, events, response


def _pause_loop(
    snapshot: dict[str, Any] | None,
    command: CommandEnvelope,
    _: AuthorityContext,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    assert snapshot is not None
    execution = snapshot["execution"]
    if execution["state"] != "ACTIVE":
        raise ProtocolRejection("INVALID_TRANSITION", "only an active loop can pause")
    reason = command.semantic_payload.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 512:
        raise ProtocolRejection("INVALID_COMMAND", "pause reason is invalid")
    wait_kind = command.semantic_payload.get("wait_kind")
    if wait_kind is not None and wait_kind not in {
        "BLOCKED",
        "BUDGET",
        "FAILURE",
        "HUMAN",
        "REPAIR",
        "TIME",
    }:
        raise ProtocolRejection("INVALID_COMMAND", "pause wait kind is invalid")
    reason_digest = domain_digest("loopskill-pause-reason-v1\n", reason)
    paused = {
        "pause_reason_digest": reason_digest,
        "revision": execution["revision"] + 1,
        "state": "PAUSED",
    }
    if wait_kind is not None:
        paused["wait_kind"] = wait_kind
    execution.update(paused)
    events = [_event("LoopPaused", reason_digest=reason_digest)]
    if wait_kind == "BUDGET":
        events.insert(0, _event("BudgetWaiting"))
    return snapshot, events, {"execution_state": "PAUSED"}


def _resume_loop(
    snapshot: dict[str, Any] | None,
    command: CommandEnvelope,
    _: AuthorityContext,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    assert snapshot is not None
    execution = snapshot["execution"]
    if execution["state"] != "PAUSED":
        raise ProtocolRejection("INVALID_TRANSITION", "only a paused loop can resume")
    payload = command.semantic_payload
    wait_kind = execution.get("wait_kind")
    if wait_kind == "BUDGET":
        required = {
            "new_max_host_invocations",
            "new_wall_clock_seconds",
            "prior_budget_digest",
            "reason_digest",
        }
        if set(payload) != required:
            raise ProtocolRejection(
                "INVALID_COMMAND", "budget waiting requires one bound extension"
            )
        plan = snapshot.get("goal_plan")
        if (
            not isinstance(plan, dict)
            or plan.get("storage_mode") != CONTENT_STORAGE_MODE
            or not isinstance(plan.get("budget"), Mapping)
        ):
            raise ProtocolRejection(
                "INVALID_TRANSITION", "budget extension requires a Plan v2 Loop"
            )
        budget = dict(plan["budget"])
        current_max = budget.get("max_host_invocations")
        current_wall = budget.get("wall_clock_seconds")
        new_max = payload["new_max_host_invocations"]
        new_wall = payload["new_wall_clock_seconds"]
        reason_digest = payload["reason_digest"]
        if (
            isinstance(current_max, bool)
            or not isinstance(current_max, int)
            or isinstance(current_wall, bool)
            or not isinstance(current_wall, int)
            or isinstance(new_max, bool)
            or not isinstance(new_max, int)
            or isinstance(new_wall, bool)
            or not isinstance(new_wall, int)
            or not current_max <= new_max <= 384
            or not current_wall <= new_wall <= 2_592_000
            or (new_max == current_max and new_wall == current_wall)
            or not isinstance(reason_digest, str)
            or len(reason_digest) != 64
            or any(character not in "0123456789abcdef" for character in reason_digest)
        ):
            raise ProtocolRejection("INVALID_COMMAND", "budget extension is invalid")
        expected_prior = domain_digest(
            "loopskill-runtime-budget-v1\n",
            {
                "max_host_invocations": current_max,
                "wall_clock_seconds": current_wall,
            },
        )
        if payload["prior_budget_digest"] != expected_prior:
            raise ProtocolRejection(
                "STALE_SUBJECT_REVISION", "runtime budget changed before extension"
            )
        budget.update(
            {
                "max_host_invocations": new_max,
                "wall_clock_seconds": new_wall,
            }
        )
        plan["budget"] = budget
        extension_digest = domain_digest(
            "loopskill-budget-extension-v1\n",
            {
                "loop_ref": snapshot["loop_ref"],
                "new_max_host_invocations": new_max,
                "new_wall_clock_seconds": new_wall,
                "prior_budget_digest": expected_prior,
                "reason_digest": reason_digest,
            },
        )
        plan["budget_extension"] = {
            "extension_digest": extension_digest,
            "reason_digest": reason_digest,
            "revision": int(plan.get("budget_extension", {}).get("revision", 0))
            + 1,
        }
        events = [_event("BudgetExtended", extension_digest=extension_digest)]
    elif wait_kind in {"HUMAN", "TIME"}:
        if set(payload) != {"gate_digest"}:
            raise ProtocolRejection(
                "INVALID_COMMAND", "controller gate waiting requires bound evidence"
            )
        gate_digest = payload["gate_digest"]
        if (
            not isinstance(gate_digest, str)
            or len(gate_digest) != 64
            or any(character not in "0123456789abcdef" for character in gate_digest)
        ):
            raise ProtocolRejection(
                "INVALID_COMMAND", "controller gate digest is invalid"
            )
        events = [_event("ControllerGateSatisfied", gate_digest=gate_digest)]
    elif payload:
        raise ProtocolRejection(
            "INVALID_COMMAND", "budget fields are invalid outside budget waiting"
        )
    else:
        events = []
    execution.pop("pause_reason_digest", None)
    execution.pop("wait_kind", None)
    execution.update(
        {"revision": execution["revision"] + 1, "state": "ACTIVE"}
    )
    events.append(_event("LoopResumed"))
    return snapshot, events, {"execution_state": "ACTIVE"}


def _stop_loop(
    snapshot: dict[str, Any] | None,
    command: CommandEnvelope,
    _: AuthorityContext,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    assert snapshot is not None
    execution = snapshot["execution"]
    if execution["state"] not in {"ACTIVE", "PAUSED"}:
        raise ProtocolRejection("INVALID_TRANSITION", "only a live loop can stop")
    reason = command.semantic_payload.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 512:
        raise ProtocolRejection("INVALID_COMMAND", "stop reason is invalid")
    active = [
        (goal_ref, goal)
        for goal_ref, goal in snapshot["goals"].items()
        if goal.get("state") == "ACTIVE"
    ]
    if len(active) != 1:
        raise ProtocolRejection("INVALID_TRANSITION", "active Goal is unavailable")
    goal_ref, goal = active[0]
    if goal["state"] != "ACTIVE":
        raise ProtocolRejection("INVALID_TRANSITION", "active Goal is unavailable")
    reason_digest = domain_digest("loopskill-stop-reason-v1\n", reason)
    goal.update({"revision": goal["revision"] + 1, "state": "STOPPED"})
    execution.update(
        {
            "disposition": "STOPPED",
            "revision": execution["revision"] + 1,
            "state": "TERMINAL",
            "stop_reason_digest": reason_digest,
        }
    )
    snapshot["closure_assurance"] = {
        "revision": snapshot["closure_assurance"]["revision"] + 1,
        "strength": "LOCAL",
    }
    return snapshot, [
        _event("GoalAdvanced", goal_ref=goal_ref),
        _event("LoopStopped", reason_digest=reason_digest),
    ], {"disposition": "STOPPED", "execution_state": "TERMINAL"}


def _prepare_finalization(
    snapshot: dict[str, Any] | None,
    command: CommandEnvelope,
    _: AuthorityContext,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    assert snapshot is not None
    chain = _final_chain(snapshot)
    review = snapshot["reviews"][chain["review_ref"]]
    disposition = command.semantic_payload.get("disposition")
    goal_state = snapshot["goals"][chain["goal_ref"]]["state"]
    unfinished = [
        goal_ref
        for goal_ref, goal in snapshot["goals"].items()
        if goal.get("state")
        not in {"DONE", "SKIPPED", "FAILED", "LIMITATION", "STOPPED"}
    ]
    if unfinished:
        raise ProtocolRejection(
            "FINALIZATION_PRECONDITION_FAILED", "Goal plan is not terminal"
        )
    result_outcome = snapshot["results"][chain["result_ref"]]["outcome"]
    if goal_state not in {"DONE", "SKIPPED", "FAILED", "LIMITATION"}:
        raise ProtocolRejection(
            "FINALIZATION_PRECONDITION_FAILED", "current chain incomplete"
        )
    subject_state = (
        snapshot["deliveries"][chain["delivery_ref"]]["state"]
        if "delivery_ref" in chain
        else snapshot["external_effects"][chain["external_effect_ref"]]["state"]
    )
    if disposition == "SUCCEEDED":
        if (
            goal_state != "DONE"
            or result_outcome != "PASS"
            or review["state"] != "PASS"
            or subject_state != "OBSERVED"
        ):
            raise ProtocolRejection(
                "FINALIZATION_PRECONDITION_FAILED", "strict success unavailable"
            )
    elif disposition == "SUCCEEDED_WITH_LIMITATIONS":
        if (
            not any(goal.get("state") == "SKIPPED" for goal in snapshot["goals"].values())
            or goal_state not in {"DONE", "SKIPPED"}
            or subject_state != "OBSERVED"
        ):
            raise ProtocolRejection(
                "FINALIZATION_PRECONDITION_FAILED",
                "success-with-limitations chain is inconsistent",
            )
    elif disposition == "FAILED":
        if goal_state != "FAILED" or result_outcome != "FAILED":
            raise ProtocolRejection(
                "FINALIZATION_PRECONDITION_FAILED", "failure chain is inconsistent"
            )
    elif disposition == "LIMITATION":
        if goal_state == "FAILED":
            raise ProtocolRejection(
                "FINALIZATION_PRECONDITION_FAILED", "failed Goal is not a limitation"
            )
    else:
        raise ProtocolRejection("INVALID_COMMAND", "invalid terminal disposition")
    finalization_ref = _binding(
        command, "allocate_refs", "new_finalization_ref"
    )
    chain_digest = domain_digest("loopskill-subject-chain-v1\n", chain)
    result = snapshot["results"][chain["result_ref"]]
    finalization = {
        "artifact_ref": result["artifact_ref"],
        "assurance_strength": "NONE",
        "attempt_ref": result["attempt_ref"],
        "disposition": disposition,
        "goal_ref": chain["goal_ref"],
        "report_ref": result["report_ref"],
        "result_ref": chain["result_ref"],
        "review_ref": chain["review_ref"],
        "revision": 1,
        "state": "PREPARED",
        "subject_chain_digest": chain_digest,
    }
    if "delivery_ref" in result:
        finalization.update(
            {
                "delivery_ref": result["delivery_ref"],
                "route_ref": result["route_ref"],
            }
        )
    else:
        finalization["external_effect_ref"] = result["external_effect_ref"]
    snapshot["finalizations"][finalization_ref] = finalization
    execution = snapshot["execution"]
    execution.update({"revision": execution["revision"] + 1, "state": "FINALIZING"})
    return snapshot, [
        _event("FinalizationPrepared", finalization_ref=finalization_ref)
    ], {"finalization_ref": finalization_ref}


def _close_execution(
    snapshot: dict[str, Any] | None,
    command: CommandEnvelope,
    context: AuthorityContext,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    assert snapshot is not None
    finalization_ref = str(command.subject["subject_ref"])
    finalization = snapshot["finalizations"][finalization_ref]
    if finalization["state"] != "PREPARED":
        raise ProtocolRejection("INVALID_TRANSITION", "Finalization not prepared")
    receipt = _receipt(
        command,
        context,
        action="lifecycle-readback",
        subject_ref=finalization_ref,
        request_digest=finalization["subject_chain_digest"],
    )
    current_chain = domain_digest(
        "loopskill-subject-chain-v1\n", _final_chain(snapshot)
    )
    if current_chain != finalization["subject_chain_digest"]:
        raise ProtocolRejection(
            "FINALIZATION_PRECONDITION_FAILED", "subject chain changed"
        )
    strict = receipt.trust_class == "strict" and receipt.outcome == "acknowledged"
    if finalization["disposition"] in {
        "SUCCEEDED",
        "SUCCEEDED_WITH_LIMITATIONS",
    } and not strict:
        raise ProtocolRejection(
            "FINALIZATION_PRECONDITION_FAILED", "strict receipt required"
        )
    assurance = "STRICT" if strict else "COOPERATIVE"
    finalization.update(
        {
            "assurance_strength": assurance,
            "revision": finalization["revision"] + 1,
            "state": "EXECUTION_CLOSED",
        }
    )
    execution = snapshot["execution"]
    execution.update(
        {
            "disposition": finalization["disposition"],
            "revision": execution["revision"] + 1,
            "state": "TERMINAL",
        }
    )
    snapshot["closure_assurance"] = {
        "finalization_ref": finalization_ref,
        "receipt_ref": receipt.receipt_ref,
        "revision": 1,
        "strength": assurance,
    }
    events = [
        _event(
            "ExecutionFinalized",
            disposition=finalization["disposition"],
            finalization_ref=finalization_ref,
        )
    ]
    if strict:
        events.append(
            _event(
                "StrictFinalizationAcknowledged",
                finalization_ref=finalization_ref,
            )
        )
    return snapshot, events, {
        "assurance": assurance,
        "disposition": finalization["disposition"],
    }


def _strengthen_closure_assurance(
    snapshot: dict[str, Any] | None,
    command: CommandEnvelope,
    context: AuthorityContext,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    assert snapshot is not None
    finalization_ref = str(command.subject["subject_ref"])
    finalization = snapshot["finalizations"][finalization_ref]
    assurance = snapshot["closure_assurance"]
    if (
        snapshot["execution"]["state"] != "TERMINAL"
        or finalization["state"] != "EXECUTION_CLOSED"
        or finalization["assurance_strength"] != "COOPERATIVE"
        or assurance.get("strength") != "COOPERATIVE"
        or assurance.get("finalization_ref") != finalization_ref
    ):
        raise ProtocolRejection(
            "INVALID_TRANSITION", "closure assurance cannot be strengthened"
        )
    receipt = _receipt(
        command,
        context,
        action="lifecycle-readback",
        subject_ref=finalization_ref,
        request_digest=finalization["subject_chain_digest"],
    )
    if receipt.trust_class != "strict" or receipt.outcome != "acknowledged":
        raise ProtocolRejection(
            "FINALIZATION_PRECONDITION_FAILED", "strict receipt required"
        )
    finalization.update(
        {
            "assurance_strength": "STRICT",
            "revision": finalization["revision"] + 1,
        }
    )
    snapshot["closure_assurance"] = {
        "finalization_ref": finalization_ref,
        "receipt_ref": receipt.receipt_ref,
        "revision": assurance["revision"] + 1,
        "strength": "STRICT",
    }
    return snapshot, [
        _event(
            "ClosureAssuranceStrengthened",
            finalization_ref=finalization_ref,
            strength="STRICT",
        ),
        _event(
            "StrictFinalizationAcknowledged",
            finalization_ref=finalization_ref,
        ),
    ], {"assurance": "STRICT", "disposition": finalization["disposition"]}


_REDUCERS = {
    "CreateLoop": _create_loop,
    "BindHostResource": _bind_host_resource,
    "RecordExternalEffectObservation": _observe_external_effect,
    "PrepareRoute": _prepare_route,
    "BeginEffectDelivery": _begin_delivery,
    "RecordEffectObservation": _observe_delivery,
    "StageResult": _stage_result,
    "StageExternalResult": _stage_external_result,
    "AcknowledgeResult": _acknowledge_result,
    "RecordReview": _record_review,
    "RecordPolicyDecision": _record_policy_decision,
    "AdvanceGoal": _advance_goal,
    "PauseLoop": _pause_loop,
    "ResumeLoop": _resume_loop,
    "ReviseGoalPlan": _revise_goal_plan,
    "StopLoop": _stop_loop,
    "PrepareFinalization": _prepare_finalization,
    "CloseExecution": _close_execution,
    "StrengthenClosureAssurance": _strengthen_closure_assurance,
}


def artifact_fixture_digest() -> str:
    return raw_domain_digest(
        "loopskill-artifact-v1\n", b"conformance-artifact-v1\n"
    )
