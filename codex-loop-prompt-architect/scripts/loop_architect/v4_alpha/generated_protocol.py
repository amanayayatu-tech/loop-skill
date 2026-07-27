"""Generated from protocol/v4/loopskill-v4.protocol.json; do not edit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

MANIFEST_SHA256 = 'c0ee416cbf2c1b2b9d89660ffdce74e50256c1f340b409eb49b07d9e47cf25b0'
PROTOCOL_VERSION = '4.0.0'
COMMAND_TYPES = (
    'AcknowledgeResult',
    'AdvanceGoal',
    'BeginEffectDelivery',
    'BindHostResource',
    'CloseExecution',
    'CreateLoop',
    'PauseLoop',
    'PrepareFinalization',
    'PrepareRoute',
    'RecordEffectObservation',
    'RecordExternalEffectObservation',
    'RecordReview',
    'ResumeLoop',
    'StopLoop',
    'StageExternalResult',
    'StageResult',
    'StrengthenClosureAssurance',
)
EVENT_TYPES = (
    'LoopCreated',
    'GoalRegistered',
    'GoalActivated',
    'StartAuthorized',
    'HostResourceBound',
    'ExternalEffectPrepared',
    'ExternalEffectObserved',
    'ExternalEffectUnknown',
    'ExternalEffectUnverifiable',
    'LateExternalEffectObserved',
    'RoutePrepared',
    'DeliveryAttemptCommitted',
    'DeliveryObserved',
    'DeliveryUnknown',
    'DeliveryUnverifiable',
    'LateDeliveryObserved',
    'ResultStaged',
    'ReportStaged',
    'ArtifactCaptured',
    'ArtifactVerified',
    'ArtifactStale',
    'ReportAccepted',
    'ResultAcknowledged',
    'ReviewRecorded',
    'GoalAdvanced',
    'LoopPaused',
    'LoopResumed',
    'LoopStopped',
    'FinalizationPrepared',
    'ExecutionFinalized',
    'StrictFinalizationAcknowledged',
    'ClosureAssuranceStrengthened',
    'OperationRejected',
)
ERROR_CODES = (
    'INVALID_COMMAND',
    'UNSUPPORTED_PROTOCOL_VERSION',
    'RESOURCE_LIMIT_EXCEEDED',
    'INVALID_UTF8',
    'CONTROL_FIELD_INJECTION',
    'INVALID_AUTHORITY',
    'AUTHORITY_EXPIRED',
    'AUTHORITY_SCOPE_MISMATCH',
    'STALE_LOOP_REVISION',
    'STALE_SUBJECT_REVISION',
    'IDEMPOTENCY_CONFLICT',
    'FOREIGN_REFERENCE',
    'WRONG_REFERENCE_KIND',
    'INVALID_TRANSITION',
    'CAPABILITY_UNAVAILABLE',
    'CAPABILITY_UNVERIFIABLE',
    'RECEIPT_REQUIRED',
    'RECEIPT_ISSUER_UNTRUSTED',
    'RECEIPT_EXPIRED',
    'RECEIPT_IDENTITY_MISMATCH',
    'ATTEMPT_ALREADY_CONSUMED',
    'ADAPTER_SCHEMA_DRIFT',
    'ARTIFACT_IDENTITY_MISMATCH',
    'ARTIFACT_STALE',
    'REPORT_IDENTITY_MISMATCH',
    'PATH_CONFINEMENT_VIOLATION',
    'FINALIZATION_PRECONDITION_FAILED',
    'USER_UNSUPPORTED_LEGACY_VERSION',
    'STORE_RECOVERY_REQUIRED',
    'INTERNAL_INVARIANT_VIOLATION',
    'USER_INPUT_INVALID',
    'USER_LOOP_EXISTS',
    'USER_STORE_UNAVAILABLE',
    'USER_INTERNAL_ERROR',
    'USER_CLARIFICATION_REQUIRED',
    'USER_DIRECT_TASK_RECOMMENDED',
    'USER_CONFIRMATION_REQUIRED',
    'USER_CONFIRMATION_STALE',
    'USER_PREPARATION_INVALID',
)
REFERENCE_KINDS = (
    'LoopRef',
    'ActorRef',
    'AuthorityGrantRef',
    'GoalRef',
    'HostResourceRef',
    'ExternalEffectRef',
    'RouteRef',
    'DeliveryRef',
    'AttemptRef',
    'ResultRef',
    'ReportRef',
    'ArtifactRef',
    'ReviewRef',
    'FinalizationRef',
    'ReceiptRef',
)
CAPABILITY_NAMES = (
    'project_registration',
    'task_create',
    'thread_create',
    'resource_read',
    'message_send',
    'eventual_indexing',
    'lifecycle_readback',
    'heartbeat',
    'sandbox_receipt',
    'trust_receipt',
    'model_receipt',
    'memory',
    'provider_idempotency',
    'artifact_existing_git',
    'artifact_non_git',
    'artifact_new_git',
)
DELIVERY_STATES = (
    'PREPARED',
    'ATTEMPT_COMMITTED',
    'OBSERVED',
    'UNKNOWN',
    'UNVERIFIABLE',
)
RESULT_STATES = (
    'STAGED',
    'ACKNOWLEDGED',
    'STALE',
)
ASSURANCE_STRENGTHS = (
    'NONE',
    'LOCAL',
    'COOPERATIVE',
    'STRICT',
)
WRITE_CAS = 'per_loop_revision'
SEMANTIC_PAYLOAD_SPECS = {'AcknowledgeResult': {'semantic_payload': {}}, 'AdvanceGoal': {'semantic_payload': {'disposition': {'enum': ['DONE', 'FAILED', 'LIMITATION'], 'type': 'string'}}}, 'BeginEffectDelivery': {'semantic_payload': {}}, 'BindHostResource': {'semantic_payload': {'role': {'type': 'string'}}}, 'CloseExecution': {'semantic_payload': {}}, 'CreateLoop': {'semantic_payload': {'acceptance_criteria': {'items': {'type': 'string'}, 'type': 'array'}, 'authorization_boundaries': {'items': {'type': 'string'}, 'type': 'array'}, 'budget': {'type': 'string'}, 'execution_mode': {'enum': ['STANDARD', 'ADAPTIVE'], 'type': 'string'}, 'external_actions': {'items': {'type': 'string'}, 'type': 'array'}, 'objective': {'type': 'string'}, 'stop_conditions': {'items': {'type': 'string'}, 'type': 'array'}, 'write_scope': {'items': {'type': 'string'}, 'type': 'array'}}}, 'PauseLoop': {'semantic_payload': {'reason': {'type': 'string'}}}, 'PrepareFinalization': {'semantic_payload': {'disposition': {'enum': ['SUCCEEDED', 'LIMITATION', 'FAILED'], 'type': 'string'}}}, 'PrepareRoute': {'semantic_payload': {'intent': {'type': 'string'}}}, 'RecordEffectObservation': {'semantic_payload': {}}, 'RecordExternalEffectObservation': {'semantic_payload': {}}, 'RecordReview': {'semantic_payload': {'verdict': {'enum': ['PASS', 'REPAIR', 'LIMITATION'], 'type': 'string'}}}, 'ResumeLoop': {'semantic_payload': {}}, 'StopLoop': {'semantic_payload': {'reason': {'type': 'string'}}}, 'StageExternalResult': {'semantic_payload': {'outcome': {'enum': ['PASS', 'FAILED', 'LIMITATION', 'UNVERIFIABLE'], 'type': 'string'}, 'summary': {'type': 'string'}}}, 'StageResult': {'semantic_payload': {'outcome': {'enum': ['PASS', 'FAILED', 'LIMITATION', 'UNVERIFIABLE'], 'type': 'string'}, 'summary': {'type': 'string'}}}, 'StrengthenClosureAssurance': {'semantic_payload': {}}}

@dataclass(frozen=True)
class ActorRef:
    actor_ref: str
    loop_namespace: str
    actor_kind: str
    identity_digest: str
    issuer_ref: str
    issuer_trust: str

@dataclass(frozen=True)
class AuthorityGrant:
    grant_ref: str
    actor_ref: str
    issuer_actor_ref: str
    issuer_trust: str
    allowed_commands: tuple[str, ...]
    loop_scope: str
    subject_kinds: tuple[str, ...]
    exact_subjects: tuple[str, ...]
    not_before: str
    expires_at: str
    nonce: str
    canonical_digest: str

@dataclass(frozen=True)
class Receipt:
    receipt_ref: str
    issuer_ref: str
    issuer_trust: str
    trust_class: str
    action: str
    loop_ref: str
    subject_ref: str
    attempt_ref: str | None
    target_ref: str | None
    request_digest: str | None
    provider_idempotency_key: str | None
    provider_resource_ref: str | None
    outcome: str
    issued_at: str
    expires_at: str
    evidence_digest: str

@dataclass(frozen=True)
class CommandEnvelope:
    operation_id: str
    command_type: str
    protocol_version: str
    actor_ref: str
    authority_grant_ref: str
    subject: Mapping[str, Any]
    expected_loop_revision: int
    expected_subject_revisions: Mapping[str, int]
    issued_at: str
    machine_bindings: Mapping[str, Mapping[str, str]]
    semantic_payload: Mapping[str, Any]
    request_digest: str

@dataclass(frozen=True)
class EffectAttempt:
    attempt_ref: str
    loop_ref: str
    subject_kind: str
    subject_ref: str
    delivery_ref: str | None
    target_ref: str
    provider_idempotency_key: str
    provider_request_digest: str
    action: str
    payload: Mapping[str, Any]

@dataclass(frozen=True)
class LoopStartInput:
    goal: str

@dataclass(frozen=True)
class LoopIntakeInput:
    goal: str
    task_horizon: str
    write_scope: tuple[str, ...]
    budget: str
    external_actions: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    authorization_boundaries: tuple[str, ...]

@dataclass(frozen=True)
class LoopIntakeDecision:
    disposition: str
    route: str
    reason: str
    questions: tuple[str, ...]

@dataclass(frozen=True)
class PreparedLoopManifest:
    manifest_version: str
    control_namespace: str
    loop_ref: str
    goal: str
    task_horizon: str
    execution_mode: str
    selection_reason: str
    write_scope: tuple[str, ...]
    budget: str
    external_actions: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    authorization_boundaries: tuple[str, ...]
    prepared_at: str

@dataclass(frozen=True)
class PreparedLoopBundle:
    manifest_digest: str
    boundary_digest: str
    controller_plan_digest: str
    instructions_digest: str
    bundle_digest: str

@dataclass(frozen=True)
class UserFacingStatus:
    goal: str
    progress: str
    result: str
    limitations: tuple[str, ...]
    next_actions: tuple[str, ...]

@dataclass(frozen=True)
class UserFacingError:
    code: str
    message: str
    next_action: str

@dataclass(frozen=True)
class Reference:
    kind: str
    value: str
    loop_ref: str

@dataclass(frozen=True)
class CapabilityRecord:
    capability: str
    availability: str
    assurance: str
    issuer_ref: str
    receipt_ref: str | None
    details: Mapping[str, Any]

@dataclass(frozen=True)
class ApplyResult:
    operation_id: str
    loop_ref: str
    loop_revision: int
    event_types: tuple[str, ...]
    response: Mapping[str, Any]
    snapshot_digest: str
    replayed: bool = False
