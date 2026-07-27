"""Deterministic reducer for the bounded LoopSkill 4.0 alpha slice."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from .protocol import (
    MAX_EVENTS_PER_COMMAND,
    ActorRef,
    AuthorityGrant,
    CommandEnvelope,
    ProtocolRejection,
    Receipt,
    authority_grant_digest,
    domain_digest,
    raw_domain_digest,
    validate_command,
    validate_event_type,
    validate_receipt_size,
)


@dataclass(frozen=True)
class AuthorityContext:
    actors: Mapping[str, ActorRef]
    grants: Mapping[str, AuthorityGrant]
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
    if reference == snapshot.get("loop_ref"):
        return {"revision": snapshot["loop_revision"]}
    for collection in _COLLECTIONS.values():
        records = snapshot.get(collection, {})
        if reference in records:
            return records[reference]
    raise ProtocolRejection("FOREIGN_REFERENCE", reference)


def validate_authority(command: CommandEnvelope, context: AuthorityContext) -> None:
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
    if grant.exact_subjects and subject_ref not in grant.exact_subjects:
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
    result_ref, result = _only_record(snapshot, "results")
    report_ref = result["report_ref"]
    artifact_ref = result["artifact_ref"]
    attempt_ref = result["attempt_ref"]
    delivery_ref = result["delivery_ref"]
    route_ref = result["route_ref"]
    goal_ref = snapshot["routes"][route_ref]["goal_ref"]
    return {
        "artifact_ref": artifact_ref,
        "artifact_revision": snapshot["artifacts"][artifact_ref]["revision"],
        "attempt_ref": attempt_ref,
        "attempt_revision": snapshot["attempts"][attempt_ref]["revision"],
        "delivery_ref": delivery_ref,
        "delivery_revision": snapshot["deliveries"][delivery_ref]["revision"],
        "goal_ref": goal_ref,
        "goal_revision": snapshot["goals"][goal_ref]["revision"],
        "report_ref": report_ref,
        "report_revision": snapshot["reports"][report_ref]["revision"],
        "result_ref": result_ref,
        "result_revision": result["revision"],
        "route_ref": route_ref,
        "route_revision": snapshot["routes"][route_ref]["revision"],
    }


def _final_chain(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    chain = _result_chain(snapshot)
    review_ref, review = _only_record(snapshot, "reviews")
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
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    validate_command(command)
    validate_authority(command, context)
    if snapshot is None and command.command_type not in {
        "CreateLoop",
        "ImportV3Snapshot",
    }:
        raise ProtocolRejection("INVALID_TRANSITION", "loop does not exist")
    validate_references(snapshot, command)
    reducer = _REDUCERS.get(command.command_type)
    if reducer is None:
        raise ProtocolRejection("INVALID_COMMAND", command.command_type)
    new_snapshot, events, response = reducer(
        copy.deepcopy(snapshot) if snapshot is not None else None,
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
        provider_request = {"goal": objective, "target_ref": target_ref}
        provider_digest = domain_digest(
            "loopskill-provider-request-v1\n", provider_request
        )
        state["external_effects"] = {
            external_effect_ref: {
                "action": action,
                "attempt_ref": attempt_ref,
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


def _import_v3_snapshot(
    snapshot: dict[str, Any] | None,
    command: CommandEnvelope,
    context: AuthorityContext,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Create one paused v4 loop from a machine-read v3.3.8 safe point.

    The compatibility reader owns v3 shape validation.  Core accepts only the
    small typed projection and never imports v3 runtime or schema code.
    """

    if snapshot is not None or command.expected_loop_revision != 0:
        raise ProtocolRejection("INVALID_TRANSITION", "loop already exists")
    payload = command.semantic_payload
    required = {
        "objective",
        "source_goal_id",
        "source_loop_id",
        "source_product_version",
        "source_schema_version",
        "source_state_digest",
        "source_state_version",
    }
    if set(payload) != required:
        raise ProtocolRejection("INVALID_COMMAND", "incomplete v3 import projection")
    if payload["source_product_version"] != "v3.3.8":
        raise ProtocolRejection(
            "MIGRATION_SOURCE_INVALID", "unsupported v3 product version"
        )
    if payload["source_schema_version"] != 3:
        raise ProtocolRejection(
            "MIGRATION_SOURCE_INVALID", "unsupported v3 schema version"
        )
    if (
        isinstance(payload["source_state_version"], bool)
        or not isinstance(payload["source_state_version"], int)
        or payload["source_state_version"] < 1
    ):
        raise ProtocolRejection("MIGRATION_SOURCE_INVALID", "invalid state version")
    source_digest = payload["source_state_digest"]
    if (
        not isinstance(source_digest, str)
        or not source_digest.startswith("sha256:")
        or len(source_digest) != 71
        or any(character not in "0123456789abcdef" for character in source_digest[7:])
    ):
        raise ProtocolRejection("MIGRATION_SOURCE_INVALID", "invalid source digest")
    if not isinstance(payload["source_goal_id"], str) or not payload["source_goal_id"]:
        raise ProtocolRejection("MIGRATION_SOURCE_INVALID", "invalid source Goal")
    if not isinstance(payload["source_loop_id"], str) or not payload["source_loop_id"]:
        raise ProtocolRejection("MIGRATION_SOURCE_INVALID", "invalid source loop")

    state, _, response = _create_loop(snapshot, command, context)
    goal_ref = response["goal_ref"]
    state["goals"][goal_ref]["state"] = "READY"
    state["execution"] = {"disposition": None, "revision": 1, "state": "PAUSED"}
    state["import_provenance"] = {
        "source_goal_id": payload["source_goal_id"],
        "source_loop_id": payload["source_loop_id"],
        "source_product_version": payload["source_product_version"],
        "source_schema_version": payload["source_schema_version"],
        "source_state_digest": source_digest,
        "source_state_version": payload["source_state_version"],
    }
    events = [
        _event("LoopCreated", loop_ref=state["loop_ref"]),
        _event("GoalRegistered", goal_ref=goal_ref),
        _event("V3SnapshotImported", source_state_digest=source_digest),
        _event("LoopPaused", reason="V3_IMPORT_SAFE_POINT"),
    ]
    return state, events, {
        "goal_ref": goal_ref,
        "loop_ref": state["loop_ref"],
        "source_state_digest": source_digest,
    }


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
    outcome = command.semantic_payload.get("outcome")
    summary = command.semantic_payload.get("summary")
    if outcome != "PASS" or summary != "bounded result complete":
        raise ProtocolRejection("INVALID_COMMAND", "unexpected result payload")
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
    receipt = _receipt(
        command,
        context,
        action="verify-artifact",
        subject_ref=artifact_ref,
    )
    snapshot["artifacts"][artifact_ref] = {
        "content_digest": receipt.evidence_digest,
        "receipt_ref": receipt.receipt_ref,
        "result_ref": result_ref,
        "revision": 1,
        "state": "VERIFIED",
    }
    report.update({"revision": report["revision"] + 1, "state": "ACCEPTED"})
    result.update(
        {
            "artifact_ref": artifact_ref,
            "revision": result["revision"] + 1,
            "state": "ACKNOWLEDGED",
        }
    )
    return snapshot, [
        _event("ArtifactCaptured", artifact_ref=artifact_ref),
        _event("ArtifactVerified", artifact_ref=artifact_ref),
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
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    assert snapshot is not None
    goal_ref = str(command.subject["subject_ref"])
    review_ref = _binding(command, "resolved_refs", "review_ref")
    disposition = command.semantic_payload.get("disposition")
    if disposition != "DONE" or snapshot["reviews"][review_ref]["state"] != "PASS":
        raise ProtocolRejection("INVALID_TRANSITION", "Goal cannot advance")
    goal = snapshot["goals"][goal_ref]
    goal.update({"revision": goal["revision"] + 1, "state": "DONE"})
    return snapshot, [_event("GoalAdvanced", goal_ref=goal_ref)], {
        "goal_state": "DONE"
    }


def _prepare_finalization(
    snapshot: dict[str, Any] | None,
    command: CommandEnvelope,
    _: AuthorityContext,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    assert snapshot is not None
    chain = _final_chain(snapshot)
    review = snapshot["reviews"][chain["review_ref"]]
    disposition = command.semantic_payload.get("disposition")
    if snapshot["goals"][chain["goal_ref"]]["state"] != "DONE":
        raise ProtocolRejection(
            "FINALIZATION_PRECONDITION_FAILED", "current chain incomplete"
        )
    delivery_state = snapshot["deliveries"][chain["delivery_ref"]]["state"]
    if disposition == "SUCCEEDED":
        if review["state"] != "PASS" or delivery_state != "OBSERVED":
            raise ProtocolRejection(
                "FINALIZATION_PRECONDITION_FAILED", "strict success unavailable"
            )
    elif disposition != "LIMITATION":
        raise ProtocolRejection("INVALID_COMMAND", "invalid terminal disposition")
    finalization_ref = _binding(
        command, "allocate_refs", "new_finalization_ref"
    )
    chain_digest = domain_digest("loopskill-subject-chain-v1\n", chain)
    result = snapshot["results"][chain["result_ref"]]
    snapshot["finalizations"][finalization_ref] = {
        "artifact_ref": result["artifact_ref"],
        "assurance_strength": "NONE",
        "attempt_ref": result["attempt_ref"],
        "delivery_ref": result["delivery_ref"],
        "disposition": disposition,
        "goal_ref": chain["goal_ref"],
        "report_ref": result["report_ref"],
        "result_ref": chain["result_ref"],
        "review_ref": chain["review_ref"],
        "revision": 1,
        "route_ref": result["route_ref"],
        "state": "PREPARED",
        "subject_chain_digest": chain_digest,
    }
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
    if finalization["disposition"] == "SUCCEEDED" and not strict:
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


_REDUCERS = {
    "CreateLoop": _create_loop,
    "ImportV3Snapshot": _import_v3_snapshot,
    "BindHostResource": _bind_host_resource,
    "RecordExternalEffectObservation": _observe_external_effect,
    "PrepareRoute": _prepare_route,
    "BeginEffectDelivery": _begin_delivery,
    "RecordEffectObservation": _observe_delivery,
    "StageResult": _stage_result,
    "AcknowledgeResult": _acknowledge_result,
    "RecordReview": _record_review,
    "AdvanceGoal": _advance_goal,
    "PrepareFinalization": _prepare_finalization,
    "CloseExecution": _close_execution,
}


def artifact_fixture_digest() -> str:
    return raw_domain_digest(
        "loopskill-artifact-v1\n", b"conformance-artifact-v1\n"
    )
