"""Frozen, side-effect-free fixture for the corrected alpha vertical trace."""

from __future__ import annotations

from typing import Any, Mapping

from .kernel import AuthorityContext, artifact_fixture_digest
from .protocol import (
    ActorRef,
    AuthorityGrant,
    CommandEnvelope,
    Receipt,
    authority_grant_digest,
    build_command,
    canonical_bytes,
    snapshot_digest,
)


LOOP_REF = "loop-0001"
FIXTURE_NOT_BEFORE = "2026-07-27T00:00:00Z"
FIXTURE_EXPIRES_AT = "2026-07-27T00:01:00Z"
EXPECTED_SNAPSHOT_BYTES = 2890
EXPECTED_SNAPSHOT_DIGEST = (
    "c9be6833249f3538bf379c7ed7c5ba564ffe97a87f239e861a715d167189a9a9"
)
EXPECTED_EVENT_TYPES = (
    "LoopCreated",
    "GoalRegistered",
    "GoalActivated",
    "HostResourceBound",
    "RoutePrepared",
    "DeliveryAttemptCommitted",
    "DeliveryObserved",
    "ResultStaged",
    "ReportStaged",
    "ArtifactCaptured",
    "ArtifactVerified",
    "ReportAccepted",
    "ResultAcknowledged",
    "ReviewRecorded",
    "GoalAdvanced",
    "FinalizationPrepared",
    "ExecutionFinalized",
    "StrictFinalizationAcknowledged",
)

# One line, no trailing newline. This is deliberately independent from reducer
# construction so the fixture detects omitted bindings and accidental state.
EXPECTED_CANONICAL_SNAPSHOT = b'{"artifacts":{"artifact-0001":{"content_digest":"52f71f6c1d592908c2902907fc674a225f3d04030ef6d9b4dedd9ede4b677fe7","receipt_ref":"receipt-artifact-0001","result_ref":"result-0001","revision":1,"state":"VERIFIED"}},"attempts":{"attempt-0001":{"automatic_budget_consumed":true,"delivery_ref":"delivery-0001","executor_actor_ref":"actor-executor-0001","executor_grant_ref":"grant-executor-0001","observation_receipt_ref":"receipt-delivery-0001","ordinal":1,"provider_idempotency_key":"effect-0001","provider_request_digest":"fce45c1a21cfc670d0007e468a04d665c96620e2027208fcaa70061c9544663d","revision":2,"state":"OBSERVED","target_ref":"host-target-0001"}},"closure_assurance":{"finalization_ref":"finalization-0001","receipt_ref":"receipt-finalize-0001","revision":1,"strength":"STRICT"},"deliveries":{"delivery-0001":{"attempt_ref":"attempt-0001","automatic_attempt_budget":1,"automatic_attempts_consumed":1,"revision":3,"route_ref":"route-0001","state":"OBSERVED","target_ref":"host-target-0001"}},"execution":{"disposition":"SUCCEEDED","revision":3,"state":"TERMINAL"},"finalizations":{"finalization-0001":{"artifact_ref":"artifact-0001","assurance_strength":"STRICT","attempt_ref":"attempt-0001","delivery_ref":"delivery-0001","disposition":"SUCCEEDED","goal_ref":"goal-0001","report_ref":"report-0001","result_ref":"result-0001","review_ref":"review-0001","revision":2,"route_ref":"route-0001","state":"EXECUTION_CLOSED","subject_chain_digest":"ff690e9ec52836b8c5d657fc0d5c71d94a83498a20ee4f10f354f34c4e907062"}},"goals":{"goal-0001":{"objective_digest":"353bd5cb07f8fc0496eace49934e6b13238fb34cd287c31a04897b9d22a5f8ec","revision":2,"state":"DONE"}},"host_resources":{"host-target-0001":{"receipt_ref":"receipt-bind-0001","revision":1,"state":"BOUND"}},"loop_ref":"loop-0001","loop_revision":11,"reports":{"report-0001":{"author_actor_ref":"actor-worker-0001","content_digest":"261f2ba50f8d3a03e41d86837f4dcba8b580b2629bd2e9726c641ed50c8ec74a","result_ref":"result-0001","revision":2,"state":"ACCEPTED"}},"results":{"result-0001":{"artifact_ref":"artifact-0001","attempt_ref":"attempt-0001","delivery_ref":"delivery-0001","outcome":"PASS","report_ref":"report-0001","revision":2,"route_ref":"route-0001","state":"ACKNOWLEDGED"}},"reviews":{"review-0001":{"artifact_ref":"artifact-0001","report_ref":"report-0001","result_ref":"result-0001","reviewer_actor_ref":"actor-reviewer-0001","revision":1,"state":"PASS","subject_chain_digest":"c8a7794089c17bfbacb33ea413bc3f22bb81c7646336bf5bec8dddd05303b94b"}},"routes":{"route-0001":{"delivery_ref":"delivery-0001","goal_ref":"goal-0001","intent_digest":"4f8294df9f9485909e7d478819bcfb0aae91c3685864946c1bdea3c0451148b3","revision":1,"target_ref":"host-target-0001"}}}'
EXPECTED_CANONICAL_SNAPSHOT = EXPECTED_CANONICAL_SNAPSHOT.replace(
    b'{"artifacts":{"artifact-0001":{"content_digest":"52f71f6c1d592908c2902907fc674a225f3d04030ef6d9b4dedd9ede4b677fe7","receipt_ref":"receipt-artifact-0001","result_ref":"result-0001","revision":1,"state":"VERIFIED"}}',
    b'{"artifacts":{"artifact-0001":{"capture_state":"CAPTURED","content_digest":"52f71f6c1d592908c2902907fc674a225f3d04030ef6d9b4dedd9ede4b677fe7","manifest_digest":"fixture-manifest-digest","profile":"non_git","receipt_ref":"receipt-artifact-0001","result_ref":"result-0001","revision":1,"state":"VERIFIED","verification_digest":"fixture-verification-digest","verification_state":"VERIFIED"}}',
)


def _grant(
    grant_ref: str,
    actor_ref: str,
    commands: tuple[str, ...],
    kinds: tuple[str, ...],
    subjects: tuple[str, ...],
) -> AuthorityGrant:
    provisional = AuthorityGrant(
        grant_ref=grant_ref,
        actor_ref=actor_ref,
        issuer_actor_ref="actor-system-0001",
        issuer_trust="trusted-fixture",
        allowed_commands=commands,
        loop_scope=LOOP_REF,
        subject_kinds=kinds,
        exact_subjects=subjects,
        not_before=FIXTURE_NOT_BEFORE,
        expires_at=FIXTURE_EXPIRES_AT,
        nonce=f"nonce-{grant_ref}",
        canonical_digest="",
    )
    return replace_grant_digest(provisional)


def replace_grant_digest(grant: AuthorityGrant) -> AuthorityGrant:
    values = dict(grant.__dict__)
    values["canonical_digest"] = authority_grant_digest(grant)
    return AuthorityGrant(**values)


def _receipt(
    receipt_ref: str,
    *,
    action: str,
    subject_ref: str,
    attempt_ref: str | None = None,
    target_ref: str | None = None,
    request_digest: str | None = None,
    provider_idempotency_key: str | None = None,
    outcome: str = "acknowledged",
    trust_class: str = "strict",
    evidence_digest: str = "fixture-evidence",
    issuer_ref: str = "actor-system-0001",
) -> Receipt:
    return Receipt(
        receipt_ref=receipt_ref,
        issuer_ref=issuer_ref,
        issuer_trust="trusted-fixture",
        trust_class=trust_class,
        action=action,
        loop_ref=LOOP_REF,
        subject_ref=subject_ref,
        attempt_ref=attempt_ref,
        target_ref=target_ref,
        request_digest=request_digest,
        provider_idempotency_key=provider_idempotency_key,
        provider_resource_ref=("synthetic-provider-resource" if outcome == "observed" else None),
        outcome=outcome,
        issued_at=FIXTURE_NOT_BEFORE,
        expires_at=FIXTURE_EXPIRES_AT,
        evidence_digest=evidence_digest,
    )


def fixture_authority() -> AuthorityContext:
    actors = {
        actor_ref: ActorRef(
            actor_ref=actor_ref,
            loop_namespace=LOOP_REF,
            actor_kind=actor_ref.removeprefix("actor-").removesuffix("-0001"),
            identity_digest=f"fixture-identity-{actor_ref}",
            issuer_ref="conformance-fixture",
            issuer_trust="trusted-fixture",
        )
        for actor_ref in (
            "actor-author-0001",
            "actor-executor-0001",
            "actor-reviewer-0001",
            "actor-system-0001",
            "actor-verifier-0001",
            "actor-worker-0001",
        )
    }
    grants = {
        "grant-create-0001": _grant(
            "grant-create-0001",
            "actor-author-0001",
            ("CreateLoop",),
            ("LoopRef",),
            (LOOP_REF,),
        ),
        "grant-system-0001": _grant(
            "grant-system-0001",
            "actor-system-0001",
            ("BindHostResource", "CloseExecution"),
            ("LoopRef", "FinalizationRef"),
            (LOOP_REF, "finalization-0001"),
        ),
        "grant-author-0001": _grant(
            "grant-author-0001",
            "actor-author-0001",
            (
                "PrepareRoute",
                "AdvanceGoal",
                "PrepareFinalization",
                "StopLoop",
            ),
            ("GoalRef", "ResultRef", "LoopRef"),
            ("goal-0001", "result-0001", LOOP_REF),
        ),
        "grant-executor-0001": _grant(
            "grant-executor-0001",
            "actor-executor-0001",
            ("BeginEffectDelivery", "RecordEffectObservation"),
            ("DeliveryRef", "AttemptRef"),
            ("delivery-0001", "attempt-0001"),
        ),
        "grant-worker-0001": _grant(
            "grant-worker-0001",
            "actor-worker-0001",
            ("StageResult",),
            ("RouteRef",),
            ("route-0001",),
        ),
        "grant-reviewer-0001": _grant(
            "grant-reviewer-0001",
            "actor-reviewer-0001",
            ("RecordReview",),
            ("ResultRef",),
            ("result-0001",),
        ),
        "grant-verifier-0001": _grant(
            "grant-verifier-0001",
            "actor-verifier-0001",
            ("AcknowledgeResult",),
            ("ResultRef",),
            ("result-0001",),
        ),
    }
    receipts = {
        "receipt-bind-0001": _receipt(
            "receipt-bind-0001", action="bind", subject_ref="host-target-0001"
        ),
        "receipt-delivery-0001": _receipt(
            "receipt-delivery-0001",
            action="send",
            subject_ref="delivery-0001",
            attempt_ref="attempt-0001",
            target_ref="host-target-0001",
            request_digest=(
                "fce45c1a21cfc670d0007e468a04d665c96620e2027208fcaa70061c9544663d"
            ),
            provider_idempotency_key="effect-0001",
            outcome="observed",
        ),
        "receipt-artifact-0001": _receipt(
            "receipt-artifact-0001",
            action="verify-artifact",
            subject_ref="artifact-0001",
            request_digest="fixture-verification-digest",
            outcome="observed",
            evidence_digest=artifact_fixture_digest(),
            issuer_ref="actor-verifier-0001",
        ),
        "receipt-finalize-0001": _receipt(
            "receipt-finalize-0001",
            action="lifecycle-readback",
            subject_ref="finalization-0001",
            request_digest=(
                "ff690e9ec52836b8c5d657fc0d5c71d94a83498a20ee4f10f354f34c4e907062"
            ),
        ),
    }
    return AuthorityContext(
        actors=actors,
        grants=grants,
        receipts=receipts,
        trusted_actor_issuers={"conformance-fixture": "trusted-fixture"},
        trusted_grant_issuers={"actor-system-0001": "trusted-fixture"},
        trusted_receipt_issuers={
            "actor-system-0001": "trusted-fixture",
            "actor-verifier-0001": "trusted-fixture",
        },
    )


def _bindings(
    *,
    resolved: Mapping[str, str] | None = None,
    allocate: Mapping[str, str] | None = None,
    receipts: Mapping[str, str] | None = None,
) -> dict[str, dict[str, str]]:
    return {
        "resolved_refs": dict(resolved or {}),
        "allocate_refs": dict(allocate or {}),
        "receipt_refs": dict(receipts or {}),
    }


def _subject(kind: str, reference: str) -> dict[str, str]:
    return {
        "loop_ref": LOOP_REF,
        "subject_kind": kind,
        "subject_ref": reference,
    }


def _command(
    step: int,
    command_type: str,
    actor_ref: str,
    grant_ref: str,
    subject: Mapping[str, Any],
    expected: Mapping[str, int],
    bindings: Mapping[str, Mapping[str, str]],
    payload: Mapping[str, Any],
) -> CommandEnvelope:
    return build_command(
        operation_id=f"op-{step:04d}",
        command_type=command_type,
        actor_ref=actor_ref,
        authority_grant_ref=grant_ref,
        subject=subject,
        expected_loop_revision=step - 1,
        expected_subject_revisions=expected,
        issued_at=f"2026-07-27T00:00:{step - 1:02d}Z",
        machine_bindings=bindings,
        semantic_payload=payload,
    )


def vertical_commands() -> tuple[CommandEnvelope, ...]:
    chain_at_step_10 = {
        "artifact-0001": 1,
        "attempt-0001": 2,
        "delivery-0001": 3,
        "goal-0001": 2,
        "report-0001": 2,
        "result-0001": 2,
        "review-0001": 1,
        "route-0001": 1,
    }
    return (
        _command(
            1,
            "CreateLoop",
            "actor-author-0001",
            "grant-create-0001",
            _subject("LoopRef", LOOP_REF),
            {},
            _bindings(allocate={"new_goal_ref": "goal-0001"}),
            {
                "acceptance_criteria": (),
                "authorization_boundaries": (),
                "budget": "fixture-only",
                "execution_mode": "STANDARD",
                "external_actions": (),
                "goal_plan": ("conformance bounded change",),
                "max_roadmap_revisions": 1,
                "objective": "conformance bounded change",
                "stop_conditions": (),
                "write_scope": (),
            },
        ),
        _command(
            2,
            "BindHostResource",
            "actor-system-0001",
            "grant-system-0001",
            _subject("LoopRef", LOOP_REF),
            {"execution": 1},
            _bindings(
                allocate={"new_host_resource_ref": "host-target-0001"},
                receipts={"receipt": "receipt-bind-0001"},
            ),
            {"role": "worker"},
        ),
        _command(
            3,
            "PrepareRoute",
            "actor-author-0001",
            "grant-author-0001",
            _subject("GoalRef", "goal-0001"),
            {"goal-0001": 1, "host-target-0001": 1},
            _bindings(
                resolved={
                    "goal_ref": "goal-0001",
                    "target_ref": "host-target-0001",
                },
                allocate={
                    "new_delivery_ref": "delivery-0001",
                    "new_route_ref": "route-0001",
                },
            ),
            {"intent": "produce bounded result"},
        ),
        _command(
            4,
            "BeginEffectDelivery",
            "actor-executor-0001",
            "grant-executor-0001",
            _subject("DeliveryRef", "delivery-0001"),
            {
                "delivery-0001": 1,
                "host-target-0001": 1,
                "route-0001": 1,
            },
            _bindings(
                allocate={
                    "new_attempt_ref": "attempt-0001",
                    "provider_idempotency_key": "effect-0001",
                }
            ),
            {},
        ),
        _command(
            5,
            "RecordEffectObservation",
            "actor-executor-0001",
            "grant-executor-0001",
            _subject("AttemptRef", "attempt-0001"),
            {"attempt-0001": 1, "delivery-0001": 2},
            _bindings(receipts={"receipt": "receipt-delivery-0001"}),
            {},
        ),
        _command(
            6,
            "StageResult",
            "actor-worker-0001",
            "grant-worker-0001",
            _subject("RouteRef", "route-0001"),
            {"attempt-0001": 2, "delivery-0001": 3, "route-0001": 1},
            _bindings(
                allocate={
                    "new_report_ref": "report-0001",
                    "new_result_ref": "result-0001",
                }
            ),
            {"outcome": "PASS", "summary": "bounded result complete"},
        ),
        _command(
            7,
            "AcknowledgeResult",
            "actor-verifier-0001",
            "grant-verifier-0001",
            _subject("ResultRef", "result-0001"),
            {
                "attempt-0001": 2,
                "delivery-0001": 3,
                "report-0001": 1,
                "result-0001": 1,
            },
            _bindings(
                allocate={"new_artifact_ref": "artifact-0001"},
                receipts={"receipt": "receipt-artifact-0001"},
                resolved={
                    "artifact_digest": artifact_fixture_digest(),
                    "artifact_profile": "non_git",
                    "capture_state": "CAPTURED",
                    "manifest_digest": "fixture-manifest-digest",
                    "verification_digest": "fixture-verification-digest",
                    "verification_state": "VERIFIED",
                },
            ),
            {},
        ),
        _command(
            8,
            "RecordReview",
            "actor-reviewer-0001",
            "grant-reviewer-0001",
            _subject("ResultRef", "result-0001"),
            {"artifact-0001": 1, "report-0001": 2, "result-0001": 2},
            _bindings(allocate={"new_review_ref": "review-0001"}),
            {"verdict": "PASS"},
        ),
        _command(
            9,
            "AdvanceGoal",
            "actor-author-0001",
            "grant-author-0001",
            _subject("GoalRef", "goal-0001"),
            {"goal-0001": 1, "review-0001": 1},
            _bindings(resolved={"review_ref": "review-0001"}),
            {"disposition": "DONE"},
        ),
        _command(
            10,
            "PrepareFinalization",
            "actor-author-0001",
            "grant-author-0001",
            _subject("LoopRef", LOOP_REF),
            chain_at_step_10,
            _bindings(allocate={"new_finalization_ref": "finalization-0001"}),
            {"disposition": "SUCCEEDED"},
        ),
        _command(
            11,
            "CloseExecution",
            "actor-system-0001",
            "grant-system-0001",
            _subject("FinalizationRef", "finalization-0001"),
            {**chain_at_step_10, "finalization-0001": 1},
            _bindings(receipts={"receipt": "receipt-finalize-0001"}),
            {},
        ),
    )


def run_vertical():
    """Run the fixed trace in a fresh in-memory store and return its evidence."""
    from .store import InMemoryStore

    store = InMemoryStore(fixture_authority())
    results = tuple(store.apply(command) for command in vertical_commands())
    return store.snapshot(LOOP_REF), tuple(store.events(LOOP_REF)), results


def verified_vertical_evidence() -> dict[str, Any]:
    """Return identity-free evidence only after the frozen trace self-validates."""

    snapshot, events, results = run_vertical()
    encoded = canonical_bytes(snapshot)
    event_types = tuple(event["type"] for event in events)
    digest = snapshot_digest(snapshot)
    if (
        encoded != EXPECTED_CANONICAL_SNAPSHOT
        or len(encoded) != EXPECTED_SNAPSHOT_BYTES
        or digest != EXPECTED_SNAPSHOT_DIGEST
        or event_types != EXPECTED_EVENT_TYPES
        or len(results) != 11
        or len(events) != 18
    ):
        raise RuntimeError("VERTICAL_FIXTURE_DRIFT")
    result = snapshot["results"]["result-0001"]["state"]
    review = snapshot["reviews"]["review-0001"]["state"]
    assurance = snapshot["closure_assurance"]["strength"]
    finalization = (
        "ACKNOWLEDGED"
        if event_types[-1] == EXPECTED_EVENT_TYPES[-1]
        and snapshot["finalizations"]["finalization-0001"]["state"]
        == "EXECUTION_CLOSED"
        else "UNKNOWN"
    )
    if (result, review, finalization, assurance) != (
        "ACKNOWLEDGED",
        "PASS",
        "ACKNOWLEDGED",
        "STRICT",
    ):
        raise RuntimeError("VERTICAL_CLOSURE_DRIFT")
    return {
        "assurance": assurance,
        "event_count": len(events),
        "final_event_from_typed_fixture": event_types[-1],
        "finalization": finalization,
        "operation_count": len(results),
        "result": result,
        "review": review,
        "snapshot_bytes": len(encoded),
        "snapshot_digest": digest,
    }
