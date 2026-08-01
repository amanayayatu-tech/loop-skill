"""Generated from protocol/v4/loopskill-v4.protocol.json; do not edit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

MANIFEST_SHA256 = '9b52f9db8a15658db40be76930342092b028a7974afda3d24b6d269dc7751b3c'
PROTOCOL_VERSION = '4.2.0'
CAPACITY_CONTRACT = {'array_limits': {'authorization_boundaries': 32, 'completion_evidence': 32, 'external_actions': 16, 'forbidden_actions': 16, 'forbidden_paths': 32, 'goal_acceptance_criteria': 16, 'goal_capabilities': 32, 'goal_requirement_refs': 64, 'goal_verifiers': 32, 'goals': 128, 'requirements': 256, 'stop_conditions': 16, 'write_scope': 32}, 'canonical_plan_max_bytes': 524288, 'collection_hard_items': 128, 'create_loop_hard_bytes': 16384, 'create_loop_target_bytes': 8192, 'create_loop_target_collection_members': 64, 'expert_json_max_bytes': 524288, 'goal_count_max': 128, 'goal_count_min': 1, 'host_prompt_hard_bytes': 32768, 'host_prompt_target_bytes': 24576, 'item_max_bytes': 1024, 'objective_max_bytes': 8192, 'source_text_max_bytes': 262144, 'version': 'loopskill-capacity-v2'}
PLAN_SOURCE_KINDS = (
    'literal_text',
    'pasted_text',
    'authorized_file',
    'expert_semantic_json',
    'canonical_plan_json',
)
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
    'RecordPolicyDecision',
    'RecordReview',
    'ResumeLoop',
    'ReviseGoalPlan',
    'StopLoop',
    'StageExternalResult',
    'StageResult',
    'StrengthenClosureAssurance',
)
EVENT_TYPES = (
    'LoopCreated',
    'GoalRegistered',
    'GoalActivated',
    'GoalPlanRegistered',
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
    'ArtifactUnverifiable',
    'ArtifactStale',
    'ReportAccepted',
    'ResultAcknowledged',
    'ReviewRecorded',
    'HumanDecisionRecorded',
    'RepairAuthorized',
    'RepairAttemptScheduled',
    'RepairExhausted',
    'RoadmapRevised',
    'GoalAdvanced',
    'GoalSkipped',
    'HostSessionBound',
    'VerifierExecuted',
    'BudgetWaiting',
    'BudgetExtended',
    'ControllerGateSatisfied',
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
SEMANTIC_PAYLOAD_SPECS = {'AcknowledgeResult': {'semantic_payload': {}}, 'AdvanceGoal': {'semantic_payload': {'disposition': {'enum': ['DONE', 'FAILED', 'LIMITATION', 'SKIPPED'], 'type': 'string'}}}, 'BeginEffectDelivery': {'semantic_payload': {}}, 'BindHostResource': {'semantic_payload': {'role': {'type': 'string'}}}, 'CloseExecution': {'semantic_payload': {}}, 'CreateLoop': {'semantic_payload': {'acceptance_criteria': {'items': {'type': 'string'}, 'type': 'array'}, 'authorization_boundaries': {'items': {'type': 'string'}, 'type': 'array'}, 'budget': {'type': 'string'}, 'execution_mode': {'enum': ['STANDARD', 'ADAPTIVE'], 'type': 'string'}, 'goal_plan': {'items': {'type': 'string'}, 'type': 'array'}, 'active_index': {'required': False, 'type': 'integer'}, 'authority_digest': {'required': False, 'type': 'string'}, 'capacity_contract_version': {'required': False, 'type': 'string'}, 'goal_count': {'required': False, 'type': 'integer'}, 'goal_id': {'required': False, 'type': 'string'}, 'goal_requirement': {'enum': ['required', 'optional'], 'required': False, 'type': 'string'}, 'goal_slice_digest': {'required': False, 'type': 'string'}, 'max_roadmap_revisions': {'type': 'integer'}, 'max_cost_minor_units': {'required': False, 'type': 'integer'}, 'max_host_invocations': {'required': False, 'type': 'integer'}, 'max_attempts': {'required': False, 'type': 'integer'}, 'ordered_goal_ids': {'items': {'type': 'string'}, 'required': False, 'type': 'array'}, 'ordered_goal_slice_digests': {'items': {'type': 'string'}, 'required': False, 'type': 'array'}, 'plan_digest': {'required': False, 'type': 'string'}, 'plan_index_digest': {'required': False, 'type': 'string'}, 'plan_revision': {'required': False, 'type': 'integer'}, 'storage_mode': {'enum': ['CONTENT_ADDRESSED_V1'], 'type': 'string'}, 'stop_policy_digest': {'required': False, 'type': 'string'}, 'wall_clock_seconds': {'required': False, 'type': 'integer'}, 'workspace_binding': {'required': False, 'type': 'string'}, 'external_actions': {'items': {'type': 'string'}, 'type': 'array'}, 'objective': {'type': 'string'}, 'stop_conditions': {'items': {'type': 'string'}, 'type': 'array'}, 'write_scope': {'items': {'type': 'string'}, 'type': 'array'}}}, 'PauseLoop': {'semantic_payload': {'reason': {'type': 'string'}, 'wait_kind': {'enum': ['BLOCKED', 'BUDGET', 'FAILURE', 'HUMAN', 'REPAIR', 'TIME'], 'required': False, 'type': 'string'}}}, 'PrepareFinalization': {'semantic_payload': {'disposition': {'enum': ['SUCCEEDED', 'SUCCEEDED_WITH_LIMITATIONS', 'LIMITATION', 'FAILED'], 'type': 'string'}}}, 'PrepareRoute': {'semantic_payload': {'intent': {'type': 'string'}}}, 'RecordEffectObservation': {'semantic_payload': {}}, 'RecordExternalEffectObservation': {'semantic_payload': {}}, 'RecordPolicyDecision': {'semantic_payload': {'decision': {'enum': ['CONTINUE_REPAIR', 'WAIT', 'STOP'], 'type': 'string'}, 'failure_fingerprint': {'type': 'string'}}}, 'RecordReview': {'semantic_payload': {'verdict': {'enum': ['PASS', 'REPAIR', 'LIMITATION'], 'type': 'string'}}}, 'ResumeLoop': {'semantic_payload': {'gate_digest': {'required': False, 'type': 'string'}, 'new_max_host_invocations': {'minimum': 1, 'required': False, 'type': 'integer'}, 'new_wall_clock_seconds': {'minimum': 1, 'required': False, 'type': 'integer'}, 'prior_budget_digest': {'required': False, 'type': 'string'}, 'reason_digest': {'required': False, 'type': 'string'}}}, 'ReviseGoalPlan': {'semantic_payload': {'objective_order': {'items': {'type': 'string'}, 'required': False, 'type': 'array'}, 'ordered_goal_ids': {'items': {'type': 'string'}, 'required': False, 'type': 'array'}, 'ordered_goal_slice_digests': {'items': {'type': 'string'}, 'required': False, 'type': 'array'}, 'plan_index_digest': {'required': False, 'type': 'string'}, 'plan_revision': {'required': False, 'type': 'integer'}, 'reason': {'type': 'string'}}}, 'StopLoop': {'semantic_payload': {'reason': {'type': 'string'}}}, 'StageExternalResult': {'semantic_payload': {'outcome': {'enum': ['PASS', 'FAILED', 'LIMITATION', 'UNVERIFIABLE'], 'type': 'string'}, 'summary': {'maxLength': 4096, 'minLength': 1, 'pattern': '\\S', 'type': 'string'}}}, 'StageResult': {'semantic_payload': {'outcome': {'enum': ['PASS', 'FAILED', 'LIMITATION', 'UNVERIFIABLE'], 'type': 'string'}, 'summary': {'maxLength': 4096, 'minLength': 1, 'pattern': '\\S', 'type': 'string'}}}, 'StrengthenClosureAssurance': {'semantic_payload': {}}}

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
class AuthorityGrantV2:
    schema: str
    grant_ref: str
    actor_ref: str
    issuer_actor_ref: str
    issuer_trust: str
    allowed_commands: tuple[str, ...]
    loop_scope: str
    subject_kinds: tuple[str, ...]
    subject_selector: Mapping[str, Any]
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
    goal_plan: tuple[str, ...]
    task_horizon: str
    write_scope: tuple[str, ...]
    budget: str
    external_actions: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    authorization_boundaries: tuple[str, ...]
    canonical_plan: Mapping[str, Any] | None = None
    source_kind: str = 'expert_semantic_json'
    source_digest: str = ''
    source_bytes: int = 0

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
    goal_plan: tuple[str, ...]
    task_horizon: str
    execution_mode: str
    max_roadmap_revisions: int
    selection_reason: str
    write_scope: tuple[str, ...]
    budget: str
    external_actions: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    authorization_boundaries: tuple[str, ...]
    artifact_profile: str
    workspace_identity_digest: str
    prepared_at: str
    plan_storage_mode: str
    plan_digest: str
    plan_index_digest: str
    capacity_report_digest: str
    capacity_contract_version: str
    source_digest: str
    product_version: str
    protocol_manifest_digest: str

@dataclass(frozen=True)
class PreparedLoopBundle:
    manifest_digest: str
    boundary_digest: str
    controller_plan_digest: str
    instructions_digest: str
    bundle_digest: str
    plan_digest: str
    plan_index_digest: str
    capacity_report_digest: str

@dataclass(frozen=True)
class PlanDocument:
    schema: str
    source: Mapping[str, Any]
    objective: str
    boundaries: Mapping[str, Any]
    budget: Mapping[str, Any]
    roadmap_policy: Mapping[str, Any]
    requirements: Mapping[str, str]
    worker_profile: Mapping[str, Any]
    completion_evidence: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    goals: tuple[Mapping[str, Any], ...]

@dataclass(frozen=True)
class PlanIndex:
    schema: str
    plan_digest: str
    goal_count: int
    ordered_goal_ids: tuple[str, ...]
    ordered_goal_slice_digests: tuple[str, ...]
    revision: int
    workspace_binding: str
    authority_digest: str
    capacity_contract_version: str

@dataclass(frozen=True)
class PlanCapacityReport:
    source_kind: str
    source_bytes: int
    source_digest: str
    goal_count: int
    plan_bytes: int
    plan_digest: str
    plan_index_digest: str
    create_loop_command_bytes: int
    create_loop_max_collection_members: int
    max_materialized_goal_prompt_bytes: int
    max_materialized_goal_id: str
    create_loop_byte_headroom: int
    create_loop_collection_headroom: int
    provider_prompt_headroom: int
    capacity_contract_version: str
    capacity_status: str
    blocking_reason: str
    materialized_goal_prompt_bytes: tuple[int, ...]

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
