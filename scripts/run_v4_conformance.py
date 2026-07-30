#!/usr/bin/env python3
"""Map every frozen corpus case to one of 74 actually executed assertions."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import unittest
from io import StringIO
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = ROOT / "tests"
SCRIPTS_ROOT = ROOT / "codex-loop-prompt-architect" / "scripts"
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preservation = _load("v4_preservation_for_runner", ROOT / "scripts/validate_v4_preservation.py")
rc = _load("v4_rc_for_runner", ROOT / "scripts/validate_v4_rc.py")


def _test(module: str, class_name: str, method: str) -> str:
    return f"{module}.{class_name}.{method}"


A = "test_v4_alpha_pure_kernel"
AR = "test_v4_artifact_capabilities"
B = "test_v4_beta_measurement"
H = "test_v4_codex_adapter"
M = "test_v4_legacy_boundary"
PS = "test_v4_persistence_spike"
PR = "test_v4_preservation_register"
PP = "test_v4_product_policy_operability"
PA = "test_v4_protocol_authority"
RC = "test_v4_rc_acceptance"
RD = "test_v4_rc_distribution"
UX = "test_v4_single_entry_ux"
DOC = "test_v4_docs"
APP = "test_v4_exec_provider"

CASE_CONTRACT_VERSION = "loopskill-v4-executable-case-contract-v1"
EVIDENCE_PROFILE = "SEMANTIC_MAPPINGS_TO_UNIQUE_EXECUTED_ASSERTIONS"
EXPECTED_SEMANTIC_MAPPING_COUNT = 349
EXPECTED_EXECUTED_ASSERTION_METHOD_COUNT = 74
CASE_CONTRACT_FIELDS = {
    "capability_profile",
    "case_id",
    "expected_acceptance",
    "expected_effect_state",
    "expected_ordered_events",
    "expected_side_effect_counts",
    "family",
    "family_spec_digest",
    "fixture_selector",
    "parameter",
    "precondition",
    "replay_expectation",
    "schema_version",
    "stimulus",
    "target_test_id",
}
_ACTIVE_CASE_CONTRACTS: dict[str, dict[str, Any]] = {}


def _family_specs(corpus: str) -> dict[str, str]:
    specs: dict[str, str] = {}
    for line in corpus.splitlines():
        match = preservation.CORPUS_ROW.fullmatch(line)
        if match is None:
            continue
        family = match.group("case")
        body = " ".join(match.group("body").split())
        stage = " ".join(match.group("stage").split())
        count = int(match.group("count"))
        value = json.dumps(
            {"body": body, "count": count, "stage": stage},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        previous = specs.get(family)
        if previous is not None and previous != value:
            raise RuntimeError(f"CONFORMANCE_FAMILY_SPEC_DUPLICATE: {family}")
        specs[family] = value
    return specs


def _expected_acceptance(case_id: str, family: str, parameter: str) -> str:
    reject_families = {
        "A-001",
        "A-PATH-001",
        "AUTH-001",
        "AUTH-002",
        "AUTH-003",
        "AUTH-004",
        "AUTH-005",
        "AUTH-006",
        "K-002",
        "K-004",
        "K-005",
        "K-006",
        "K-008",
        "M-001",
        "M-002",
        "M-004",
        "M-005",
        "RES-001",
        "UX-004",
        "UX-006",
        "UX-013",
        "UX-016",
    }
    if family in reject_families:
        return "REJECT"
    if family == "ENC-001" and parameter in {"g", "h", "i", "j"}:
        return "REJECT"
    if family == "H-004" and parameter == "b":
        return "REJECT"
    if family == "H-005" and parameter == "b":
        return "REJECT"
    if family == "H-007" and parameter in {"b", "c"}:
        return "REJECT"
    if family == "F-002" and parameter == "b":
        return "REJECT"
    if family == "F-004" and parameter == "b":
        return "REJECT"
    if family == "XFX-005" and parameter == "b":
        return "REJECT"
    negative_markers = (
        "-REJECT",
        "-DRIFT",
        "-CONFLICT",
        "-TAMPER",
        "-SECRET",
        "-PII",
        "-RAW-LOG",
        "-WRONG-ROLE",
        "-STALE-ARTIFACT",
        "-FAILURE",
    )
    if family.startswith("CAP-") and any(marker in case_id for marker in negative_markers):
        return "REJECT"
    if family == "UX-015" and parameter == "b":
        return "REJECT"
    return "ACCEPT"


def _expected_effect_state(family: str, parameter: str) -> str:
    exact = {
        ("H-002", "a"): "UNKNOWN",
        ("H-003", "b"): "UNKNOWN",
        ("H-005", "a"): "UNVERIFIABLE",
        ("H-008", "b"): "UNVERIFIABLE",
        ("H-011", "c"): "UNKNOWN",
        ("H-011", "d"): "OBSERVED",
        ("UX-005", "a"): "UNKNOWN",
        ("UX-005", "b"): "UNVERIFIABLE",
        ("UX-014", "c"): "OBSERVED",
        ("UX-014", "d"): "UNKNOWN",
        ("XFX-003", "a"): "OBSERVED",
        ("XFX-004", "a"): "OBSERVED",
        ("XFX-005", "a"): "OBSERVED",
        ("XFX-006", "a"): "UNVERIFIABLE",
        ("XFX-006", "b"): "OBSERVED",
        ("XFX-008", "a"): "UNKNOWN",
        ("XFX-008", "b"): "UNKNOWN",
        ("XFX-008", "c"): "UNVERIFIABLE",
    }
    return exact.get((family, parameter), "NOT_APPLICABLE")


def _replay_expectation(family: str, parameter: str) -> str:
    if family == "K-003" or (family == "REJ-001" and parameter == "a"):
        return "EXACT_REPLAY_NO_SECOND_COMMIT"
    if family in {"K-004", "REJ-001"}:
        return "IDEMPOTENCY_CONFLICT_ON_CHANGED_REQUEST"
    if family == "F-002" and parameter == "a":
        return "EXACT_REPLAY_NO_SECOND_COMMIT"
    if family == "P-004" and parameter == "b":
        return "EXACT_REPLAY_NO_SECOND_COMMIT"
    if family == "UX-014" and parameter == "b":
        return "EXACT_REPLAY_NO_SECOND_COMMIT"
    return "NOT_APPLICABLE"


def _side_effect_counts(family: str, parameter: str) -> dict[str, int | None]:
    exact = {
        ("UX-011", "a"): (0, 0, 0),
        ("UX-012", "a"): (0, 5, 0),
        ("UX-012", "b"): (0, 0, 0),
        ("UX-012", "c"): (0, 1, 0),
        ("UX-014", "a"): (1, 0, 0),
        ("UX-014", "b"): (0, 0, 0),
        ("UX-014", "c"): (1, 0, 1),
        ("UX-014", "d"): (1, 0, 1),
    }
    commits, files, provider = exact.get((family, parameter), (None, None, None))
    return {
        "canonical_commits": commits,
        "local_filesystem_writes": files,
        "provider_invocations": provider,
    }


def _expected_events(family: str, parameter: str) -> list[str] | None:
    if family == "K-001":
        from loop_architect.v4_alpha.vertical import EXPECTED_EVENT_TYPES

        return list(EXPECTED_EVENT_TYPES)
    exact = {
        ("UX-011", "a"): [],
        ("UX-012", "a"): [],
        ("UX-012", "b"): [],
        ("UX-012", "c"): [],
        ("UX-014", "a"): [
            "LoopCreated",
            "GoalRegistered",
            "GoalActivated",
            "StartAuthorized",
            "ExternalEffectPrepared",
        ],
        ("UX-014", "b"): [],
        ("UX-014", "c"): ["ExternalEffectObserved", "HostResourceBound"],
        ("UX-014", "d"): ["ExternalEffectUnknown"],
    }
    return exact.get((family, parameter))


def _case_contract(
    *, case_id: str, family: str, target_test_id: str, family_spec: str
) -> dict[str, Any]:
    parameter = case_id[len(family) + 1 :]
    spec_value = json.loads(family_spec)
    contract = {
        "capability_profile": family.split("-", 1)[0],
        "case_id": case_id,
        "expected_acceptance": _expected_acceptance(case_id, family, parameter),
        "expected_effect_state": _expected_effect_state(family, parameter),
        "expected_ordered_events": _expected_events(family, parameter),
        "expected_side_effect_counts": _side_effect_counts(family, parameter),
        "family": family,
        "family_spec_digest": hashlib.sha256(family_spec.encode()).hexdigest(),
        "fixture_selector": parameter,
        "parameter": parameter,
        "precondition": spec_value["body"],
        "replay_expectation": _replay_expectation(family, parameter),
        "schema_version": CASE_CONTRACT_VERSION,
        "stimulus": f"{family}:{parameter}",
        "target_test_id": target_test_id,
    }
    if set(contract) != CASE_CONTRACT_FIELDS:
        raise RuntimeError("CONFORMANCE_CASE_CONTRACT_SHAPE")
    return contract


# Every exact catalog family binds to one concrete unittest method whose
# parameter matrix owns that family's branches.  The per-case parameter below
# is the exact catalog suffix, never an inferred PASS from a module result.
FAMILY_TEST_BINDINGS = {
    "A-001": _test(A, "V4AlphaPureKernelTests", "test_finalization_receipt_binds_exact_subject_chain_digest"),
    "A-GIT-001": _test(AR, "V4ArtifactCapabilityTests", "test_existing_git_binary_untracked_and_control_exclusion"),
    "A-GIT-002": _test(AR, "V4ArtifactCapabilityTests", "test_existing_git_untracked_boundary_is_exact"),
    "A-GIT-003": _test(AR, "V4ArtifactCapabilityTests", "test_existing_git_empty_diff_is_explicit_and_stable"),
    "A-NEWGIT-001": _test(AR, "V4ArtifactCapabilityTests", "test_new_git_full_vertical_requires_grants_and_captures_delta"),
    "A-NONGIT-001": _test(AR, "V4ArtifactCapabilityTests", "test_non_git_manifest_delta_add_modify_delete_and_empty"),
    "A-NONGIT-002": _test(AR, "V4ArtifactCapabilityTests", "test_non_git_manifest_delta_add_modify_delete_and_empty"),
    "A-PATH-001": _test(AR, "V4ArtifactCapabilityTests", "test_symlink_casefold_special_file_and_size_reject"),
    "AUTH-001": _test(A, "V4AlphaPureKernelTests", "test_all_llm_control_field_injections_fail_closed"),
    "AUTH-002": _test(A, "V4AlphaPureKernelTests", "test_actor_and_grant_authority_failures"),
    "AUTH-003": _test(A, "V4AlphaPureKernelTests", "test_actor_and_grant_authority_failures"),
    "AUTH-004": _test(A, "V4AlphaPureKernelTests", "test_wrong_kind_and_foreign_references_fail_closed"),
    "AUTH-005": _test(A, "V4AlphaPureKernelTests", "test_actor_and_grant_authority_failures"),
    "AUTH-006": _test(A, "V4AlphaPureKernelTests", "test_receipt_trust_freshness_and_identity_failures"),
    "CAP-ARCHITECTURE": _test(PR, "V4PreservationRegisterTests", "test_architecture_fitness_passes_current_graph"),
    "CAP-AUDIT": _test(PP, "V4OperabilityProjectionTests", "test_audit_archive_and_status_are_deterministic_read_only_views"),
    "CAP-COMPAT": _test(M, "V4LegacyBoundaryTests", "test_cli_rejects_legacy_pack_with_stable_error_and_zero_writes"),
    "CAP-DISTRIBUTION": _test(RD, "V4RcDistributionTests", "test_isolated_install_is_v4_only_and_config_byte_identical"),
    "CAP-DOCS": _test(DOC, "V4DocsTests", "test_public_docs_pass_parity_commands_links_and_claims"),
    "CAP-INTAKE": _test(UX, "V4SingleEntryUXTests", "test_intake_four_outcomes_seven_sections_and_zero_side_effects"),
    "CAP-MODES": _test(PP, "V4ProductPolicyTests", "test_standard_is_fixed_dependency_order_and_adaptive_is_bounded"),
    "CAP-OPERABILITY": _test(PP, "V4OperabilityProjectionTests", "test_doctor_hides_identity_unless_diagnostics_are_requested"),
    "CAP-PRIVACY": _test(PP, "V4OperabilityProjectionTests", "test_privacy_export_is_aggregate_and_omits_raw_identity"),
    "CAP-RELEASE": _test(RC, "V4RcAcceptanceTests", "test_static_gate_binds_exact_clean_sha_tree_sbom_and_scans"),
    "CAP-ROLES": _test(PP, "V4ProductPolicyTests", "test_roles_are_jit_and_bind_the_current_artifact"),
    "ENC-001": _test(A, "V4AlphaPureKernelTests", "test_canonical_encoder_all_ten_instances"),
    "F-001": _test(A, "V4AlphaPureKernelTests", "test_corrected_vertical_exact_snapshot_events_and_replay"),
    "F-002": _test(A, "V4AlphaPureKernelTests", "test_finalization_receipt_binds_exact_subject_chain_digest"),
    "F-003": _test(A, "V4AlphaPureKernelTests", "test_cooperative_fixture_terminates_with_limitation_not_strict_claim"),
    "F-004": _test(PP, "V4ProductPolicyTests", "test_late_strict_readback_strengthens_terminal_assurance_only"),
    "H-001": _test(H, "V4CodexAdapterTests", "test_all_host_mutations_and_resources_are_closed_and_single_invoke"),
    "H-002": _test(H, "V4CodexAdapterTests", "test_missing_readback_is_unknown_and_never_resends"),
    "H-003": _test(H, "V4CodexAdapterTests", "test_response_lost_then_authoritative_readback_and_eventual_indexing"),
    "H-004": _test(H, "V4CodexAdapterTests", "test_receipt_issuer_trust_and_freshness_are_kernel_authority"),
    "H-005": _test(H, "V4CodexAdapterTests", "test_cooperative_response_is_unverifiable_not_strict"),
    "H-006": _test(H, "V4CodexAdapterTests", "test_capability_profiles_assurance_memory_and_guarantee_vocabulary"),
    "H-007": _test(H, "V4CodexAdapterTests", "test_schema_enum_identity_and_capability_drift_fail_closed"),
    "H-008": _test(H, "V4CodexAdapterTests", "test_final_lifecycle_readback_binds_chain_and_assurance"),
    "H-009": _test(H, "V4CodexAdapterTests", "test_capability_profiles_assurance_memory_and_guarantee_vocabulary"),
    "H-010": _test(H, "V4CodexAdapterTests", "test_all_host_mutations_and_resources_are_closed_and_single_invoke"),
    "H-011": _test(H, "V4CodexAdapterTests", "test_single_entry_startup_effect_runs_through_real_store_and_adapter_contract"),
    "K-001": _test(A, "V4AlphaPureKernelTests", "test_corrected_vertical_exact_snapshot_events_and_replay"),
    "K-002": _test(A, "V4AlphaPureKernelTests", "test_stale_loop_and_subject_revisions_are_pure_rejections"),
    "K-003": _test(A, "V4AlphaPureKernelTests", "test_corrected_vertical_exact_snapshot_events_and_replay"),
    "K-004": _test(A, "V4AlphaPureKernelTests", "test_changed_accepted_and_rejected_operations_conflict"),
    "K-005": _test(A, "V4AlphaPureKernelTests", "test_wrong_kind_and_foreign_references_fail_closed"),
    "K-006": _test(A, "V4AlphaPureKernelTests", "test_finalization_receipt_binds_exact_subject_chain_digest"),
    "K-007": _test(PP, "V4ProductPolicyTests", "test_pause_resume_are_cas_mutations_without_raw_reason"),
    "K-008": _test(PA, "V4ProtocolAuthorityTests", "test_event_error_reference_and_capability_unknowns_fail_closed"),
    "K-009": _test(PP, "V4OperabilityProjectionTests", "test_audit_archive_and_status_are_deterministic_read_only_views"),
    "L-001": _test(PP, "V4ProductPolicyTests", "test_every_vertical_nonterminal_snapshot_has_one_next_action_class"),
    "L-002": _test(B, "V4BetaMeasurementTests", "test_real_local_v4_fixture_passes_frozen_comparator"),
    "M-001": _test(M, "V4LegacyBoundaryTests", "test_v3_root_detection_is_read_only"),
    "M-002": _test(M, "V4LegacyBoundaryTests", "test_rejection_replay_and_changed_pack_remain_zero_write"),
    "M-003": _test(M, "V4LegacyBoundaryTests", "test_stable_external_v3_release_reference"),
    "M-004": _test(M, "V4LegacyBoundaryTests", "test_all_legacy_state_classes_share_one_zero_write_rejection"),
    "M-005": _test(M, "V4LegacyBoundaryTests", "test_production_tree_contains_no_v4_compat_package"),
    "P-001": _test(PP, "V4ProductPolicyTests", "test_repair_is_bounded_and_same_failure_routes_to_human"),
    "P-002": _test(PP, "V4ProductPolicyTests", "test_repair_is_bounded_and_same_failure_routes_to_human"),
    "P-003": _test(PP, "V4ProductPolicyTests", "test_standard_is_fixed_dependency_order_and_adaptive_is_bounded"),
    "P-004": _test(A, "V4AlphaPureKernelTests", "test_stop_loop_cas_authority_and_unresolved_effect_are_honest"),
    "R-001": _test(A, "V4AlphaPureKernelTests", "test_corrected_vertical_exact_snapshot_events_and_replay"),
    "R-002": _test(PP, "V4ProductPolicyTests", "test_repair_is_bounded_and_same_failure_routes_to_human"),
    "R-003": _test(A, "V4AlphaPureKernelTests", "test_cooperative_fixture_terminates_with_limitation_not_strict_claim"),
    "R-004": _test(A, "V4AlphaPureKernelTests", "test_finalization_receipt_binds_exact_subject_chain_digest"),
    "REJ-001": _test(A, "V4AlphaPureKernelTests", "test_changed_accepted_and_rejected_operations_conflict"),
    "RES-001": _test(PA, "V4ProtocolAuthorityTests", "test_semantic_payload_shape_enum_and_protocol_drift_reject"),
    "S-001": _test(A, "V4AlphaPureKernelTests", "test_all_33_declared_transaction_fault_boundaries"),
    "S-002": _test(PS, "V4PersistenceSpikeTests", "test_rejection_replay_and_changed_request_survive_reopen"),
    "S-003": _test(PS, "V4PersistenceSpikeTests", "test_rejection_replay_and_changed_request_survive_reopen"),
    "S-004": _test(PS, "V4PersistenceSpikeTests", "test_backup_restore_is_exact_and_source_remains_live"),
    "S-005": _test(PS, "V4PersistenceSpikeTests", "test_bounded_writer_contention_has_no_partial_state"),
    "S-006": _test(PS, "V4PersistenceSpikeTests", "test_manual_export_and_immutable_blob_are_canonical_and_stable"),
    "UX-001": _test(UX, "V4SingleEntryUXTests", "test_one_input_file_or_main_command_runs_four_phases_with_explicit_confirm"),
    "UX-002": _test(UX, "V4SingleEntryUXTests", "test_default_path_has_zero_control_fields_and_no_policy_pack"),
    "UX-003": _test(UX, "V4SingleEntryUXTests", "test_default_path_has_zero_control_fields_and_no_policy_pack"),
    "UX-004": _test(UX, "V4SingleEntryUXTests", "test_invalid_inputs_are_stable_non_leaking_and_leave_no_store"),
    "UX-005": _test(UX, "V4SingleEntryUXTests", "test_unknown_and_unverifiable_are_visible_without_resend_controls"),
    "UX-006": _test(M, "V4LegacyBoundaryTests", "test_cli_rejects_legacy_root_without_creating_v4_store"),
    "UX-007": _test(UX, "V4SingleEntryUXTests", "test_default_status_hides_internal_identity_diagnostics_is_opt_in"),
    "UX-008": _test(B, "V4BetaMeasurementTests", "test_real_local_v4_fixture_passes_frozen_comparator"),
    "UX-009": _test(RC, "V4RcAcceptanceTests", "test_canary_receipt_is_minimized_and_fail_closed"),
    "UX-010": _test(UX, "V4SingleEntryUXTests", "test_intake_four_outcomes_seven_sections_and_zero_side_effects"),
    "UX-011": _test(UX, "V4SingleEntryUXTests", "test_intake_four_outcomes_seven_sections_and_zero_side_effects"),
    "UX-012": _test(UX, "V4SingleEntryUXTests", "test_prepare_confirm_and_start_have_exact_side_effect_boundaries"),
    "UX-013": _test(UX, "V4SingleEntryUXTests", "test_stale_expired_and_changed_confirmation_fail_closed"),
    "UX-014": _test(UX, "V4SingleEntryUXTests", "test_confirmed_preparation_creates_and_starts_without_control_identity"),
    "UX-015": _test(UX, "V4SingleEntryUXTests", "test_direct_task_recommendation_never_creates_loop_or_preparation"),
    "UX-016": _test(UX, "V4SingleEntryUXTests", "test_noninteractive_main_entry_stops_after_prepare_without_confirmation"),
    "XFX-001": _test(A, "V4AlphaPureKernelTests", "test_attempt_commit_consumes_budget_and_forbids_resend"),
    "XFX-002": _test(A, "V4AlphaPureKernelTests", "test_attempt_commit_consumes_budget_and_forbids_resend"),
    "XFX-003": _test(H, "V4CodexAdapterTests", "test_response_lost_then_authoritative_readback_and_eventual_indexing"),
    "XFX-004": _test(H, "V4CodexAdapterTests", "test_response_lost_then_authoritative_readback_and_eventual_indexing"),
    "XFX-005": _test(A, "V4AlphaPureKernelTests", "test_unknown_and_unverifiable_allow_exact_late_observation_only"),
    "XFX-006": _test(H, "V4CodexAdapterTests", "test_cooperative_response_is_unverifiable_not_strict"),
    "XFX-007": _test(A, "V4AlphaPureKernelTests", "test_attempt_commit_consumes_budget_and_forbids_resend"),
    "XFX-008": _test(A, "V4AlphaPureKernelTests", "test_unknown_and_unverifiable_allow_exact_late_observation_only"),
}

# Case-level overrides are reserved for a branch whose exact regression is
# narrower than the rest of its family. They are still frozen test identities,
# not runtime inference or a second schema.
CASE_TEST_OVERRIDES = {
    "CAP-RELEASE-CANARY": _test(
        A,
        "V4AlphaPureKernelTests",
        "test_verified_vertical_evidence_is_identity_free_and_exact",
    ),
    "CAP-COMPAT-SUNSET": _test(
        M,
        "V4LegacyBoundaryTests",
        "test_public_protocol_has_one_legacy_error_and_no_import_surface",
    ),
    "UX-009-a": _test(
        A,
        "V4AlphaPureKernelTests",
        "test_verified_vertical_evidence_is_identity_free_and_exact",
    ),
    "F-003-c": _test(
        UX,
        "V4SingleEntryUXTests",
        "test_host_failed_result_closes_failed",
    ),
    "F-003-d": _test(
        UX,
        "V4SingleEntryUXTests",
        "test_host_unverifiable_result_closes_limitation",
    ),
    "F-003-e": _test(
        A,
        "V4AlphaPureKernelTests",
        "test_stop_loop_cas_authority_and_unresolved_effect_are_honest",
    ),
    "H-011-e": _test(
        UX,
        "V4SingleEntryUXTests",
        "test_public_host_result_refresh_closes_exact_external_subject_chain",
    ),
    "H-011-f": _test(
        UX,
        "V4SingleEntryUXTests",
        "test_host_result_refresh_recovers_every_local_durable_boundary",
    ),
    "H-011-g": _test(
        APP,
        "ExecProviderTests",
        "test_lost_evidence_consumes_only_spawn_and_duplicate_is_rejected_before_runner",
    ),
}


def _family(case_id: str, by_family: dict[str, set[str]]) -> str:
    owners = [family for family, cases in by_family.items() if case_id in cases]
    if len(owners) != 1:
        raise RuntimeError(f"CONFORMANCE_CASE_OWNER_INVALID: {case_id}")
    return owners[0]


def _run_test(test_id: str) -> dict[str, Any]:
    suite = unittest.defaultTestLoader.loadTestsFromName(test_id)
    if suite.countTestCases() != 1:
        raise RuntimeError(f"CONFORMANCE_TEST_ID_INVALID: {test_id}")
    stream = StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
    if not result.wasSuccessful() or result.testsRun != 1 or result.skipped:
        digest = hashlib.sha256(stream.getvalue().encode()).hexdigest()
        raise RuntimeError(f"CONFORMANCE_TEST_FAILED: {test_id}: {digest}")
    deterministic = {"assertion_test_id": test_id, "status": "PASS", "tests_run": 1}
    return {
        **deterministic,
        "result_digest": hashlib.sha256(rc._canonical(deterministic)).hexdigest(),
    }


def _run_case(
    case_id: str,
    family: str,
    target_test_id: str,
    contract: dict[str, Any] | None = None,
    target_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parameter = case_id[len(family) + 1 :]
    expected_target = CASE_TEST_OVERRIDES.get(
        case_id, FAMILY_TEST_BINDINGS.get(family)
    )
    if (
        contract is None
        or set(contract) != CASE_CONTRACT_FIELDS
        or contract.get("case_id") != case_id
        or contract.get("family") != family
        or contract.get("target_test_id") != target_test_id
        or contract.get("parameter") != parameter
        or _ACTIVE_CASE_CONTRACTS.get(case_id) != contract
        or target_test_id != expected_target
        or contract.get("expected_acceptance")
        != _expected_acceptance(case_id, family, parameter)
        or contract.get("expected_effect_state")
        != _expected_effect_state(family, parameter)
        or contract.get("expected_ordered_events") != _expected_events(family, parameter)
        or contract.get("expected_side_effect_counts")
        != _side_effect_counts(family, parameter)
        or contract.get("replay_expectation")
        != _replay_expectation(family, parameter)
    ):
        raise RuntimeError(f"CONFORMANCE_CASE_CONTRACT_INVALID: {case_id}")
    contract_bytes = rc._canonical(contract)
    contract_digest = hashlib.sha256(contract_bytes).hexdigest()
    target = _run_test(target_test_id) if target_result is None else target_result
    if (
        target.get("assertion_test_id") != target_test_id
        or target.get("status") != "PASS"
        or target.get("tests_run") != 1
    ):
        raise RuntimeError(f"CONFORMANCE_TEST_RESULT_INVALID: {target_test_id}")
    mapping = {
        "assertion_test_id": target_test_id,
        "case_id": case_id,
        "case_contract_digest": contract_digest,
        "coverage_status": "COVERED_BY_PASSING_TEST",
        "family": family,
        "fixture_selector": contract["fixture_selector"],
        "target_test_id": target_test_id,
        "target_test_result_digest": target["result_digest"],
    }
    return {
        **mapping,
        "result_digest": hashlib.sha256(rc._canonical(mapping)).hexdigest(),
        "target_test_result": target,
    }


def _catalog_and_bindings(root: Path, candidate: str):
    corpus = rc._run(
        root, "git", "show", f"{candidate}:{preservation.CORPUS_RELATIVE}"
    ).decode("utf-8", "strict")
    catalog, by_family = preservation._exact_case_catalog(corpus)
    family_specs = _family_specs(corpus)
    if len(catalog) != EXPECTED_SEMANTIC_MAPPING_COUNT:
        raise RuntimeError("CONFORMANCE_CASE_COUNT_DRIFT")
    concrete_families = {family for family, cases in by_family.items() if cases}
    if set(FAMILY_TEST_BINDINGS) != concrete_families:
        raise RuntimeError("CONFORMANCE_FAMILY_BINDING_DRIFT")
    if not set(CASE_TEST_OVERRIDES) <= catalog:
        raise RuntimeError("CONFORMANCE_CASE_OVERRIDE_DRIFT")
    bindings = {}
    for case_id in catalog:
        family = _family(case_id, by_family)
        test_id = CASE_TEST_OVERRIDES.get(
            case_id, FAMILY_TEST_BINDINGS[family]
        )
        if family not in family_specs:
            raise RuntimeError(f"CONFORMANCE_FAMILY_SPEC_MISSING: {family}")
        bindings[case_id] = (
            family,
            test_id,
            _case_contract(
                case_id=case_id,
                family=family,
                target_test_id=test_id,
                family_spec=family_specs[family],
            ),
        )
    _ACTIVE_CASE_CONTRACTS.clear()
    _ACTIVE_CASE_CONTRACTS.update(
        {case_id: value[2] for case_id, value in bindings.items()}
    )
    return corpus, catalog, bindings


def run(
    root: Path,
    candidate: str,
    canary_2_path: Path,
    canary_8_path: Path,
) -> dict[str, Any]:
    corpus, catalog, bindings = _catalog_and_bindings(root, candidate)
    canaries = {}
    canary_sha256 = {}
    for goal_count, path in ((2, canary_2_path), (8, canary_8_path)):
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8", "strict"))
        if raw != rc._canonical(value):
            raise RuntimeError("CONFORMANCE_CANARY_RECEIPT_NOT_CANONICAL")
        rc.validate_canary_receipt(
            value, candidate, expected_goal_count=goal_count
        )
        canaries[goal_count] = value
        canary_sha256[goal_count] = hashlib.sha256(raw).hexdigest()
    rc.validate_canary_pair(canaries[2], canaries[8], candidate)
    real_canary_cases = {"UX-009-a": 2, "CAP-RELEASE-CANARY": 8}
    corpus_digest = hashlib.sha256(corpus.encode("utf-8")).hexdigest()
    results = []
    target_executions: dict[str, dict[str, Any]] = {}
    for case_id in sorted(catalog):
        family, test_id, contract = bindings[case_id]
        execution = _run_case(
            case_id,
            family,
            test_id,
            contract,
            target_executions.get(test_id),
        )
        target_executions.setdefault(test_id, execution["target_test_result"])
        parameter = case_id[len(family) + 1 :]
        receipt_contract = {**contract, "corpus_sha256": corpus_digest}
        result = {
            "coverage_mapping_count": 1,
            "assertion_test_id": execution["assertion_test_id"],
            "case_id": case_id,
            "case_contract_digest": execution["case_contract_digest"],
            "case_contract": contract,
            "evidence_kind": (
                "REAL_APP_RECEIPT+TEST_COVERAGE_MAPPING"
                if case_id in real_canary_cases
                else "TEST_COVERAGE_MAPPING"
            ),
            "family": family,
            "parameter": parameter,
            "status": "COVERED_BY_PASSING_TEST",
            "target_test_id": test_id,
            "coverage_mapping_digest": execution["result_digest"],
            "target_test_result_digest": execution["target_test_result_digest"],
            "expected_acceptance": receipt_contract["expected_acceptance"],
            "expected_effect_state": receipt_contract["expected_effect_state"],
            "fixture_selector": receipt_contract["fixture_selector"],
            "replay_expectation": receipt_contract["replay_expectation"],
        }
        if case_id in real_canary_cases:
            goal_count = real_canary_cases[case_id]
            result["canary_goal_count"] = goal_count
            result["canary_receipt_sha256"] = canary_sha256[goal_count]
        results.append(result)
    test_method_results = [target_executions[key] for key in sorted(target_executions)]
    if len(test_method_results) != EXPECTED_EXECUTED_ASSERTION_METHOD_COUNT:
        raise RuntimeError("CONFORMANCE_EXECUTED_ASSERTION_COUNT_DRIFT")
    body = {
        "artifact": "loopskill-v4-conformance-execution-v2",
        "bound_real_canary_count": 2,
        "bound_real_host_invocations": 10,
        "candidate_sha": candidate,
        "case_catalog_digest": preservation.EXACT_CASE_CATALOG_SHA256,
        "canonical_case_ids": True,
        "case_count": len(results),
        "case_results": results,
        "failed": 0,
        "corpus_sha256": corpus_digest,
        "evidence_profile": EVIDENCE_PROFILE,
        "independent_case_observation_claimed": False,
        "mapped": len(results),
        "passed_test_methods": len(test_method_results),
        "real_external_effects": 0,
        "semantic_coverage_mapping_count": len(results),
        "status": "PASS",
        "test_method_count": len(test_method_results),
        "test_method_results": test_method_results,
    }
    body["case_results_digest"] = hashlib.sha256(rc._canonical(results)).hexdigest()
    body["binding_manifest_digest"] = hashlib.sha256(
        rc._canonical(
            [
                {
                    "case_id": item["case_id"],
                    "case_contract_digest": item["case_contract_digest"],
                    "test_id": item["assertion_test_id"],
                }
                for item in results
            ]
        )
    ).hexdigest()
    return body


def hosted_run(root: Path, candidate: str) -> dict[str, Any]:
    """Run every bound deterministic assertion without pretending to run App."""

    corpus, catalog, bindings = _catalog_and_bindings(root, candidate)
    target_results = {
        test_id: _run_test(test_id)
        for test_id in sorted({value[1] for value in bindings.values()})
    }
    if len(target_results) != EXPECTED_EXECUTED_ASSERTION_METHOD_COUNT:
        raise RuntimeError("CONFORMANCE_EXECUTED_ASSERTION_COUNT_DRIFT")
    mapping_results = [
        _run_case(
            case_id,
            bindings[case_id][0],
            bindings[case_id][1],
            bindings[case_id][2],
            target_results[bindings[case_id][1]],
        )
        for case_id in sorted(catalog)
    ]
    return {
        "artifact": "loopskill-v4-hosted-conformance-v1",
        "candidate_sha": candidate,
        "case_catalog_digest": preservation.EXACT_CASE_CATALOG_SHA256,
        "case_count": len(catalog),
        "corpus_sha256": hashlib.sha256(corpus.encode("utf-8")).hexdigest(),
        "deterministic_assertion_method_count": len(target_results),
        "deterministic_assertion_results_digest": hashlib.sha256(
            rc._canonical([target_results[key] for key in sorted(target_results)])
        ).hexdigest(),
        "evidence_profile": EVIDENCE_PROFILE,
        "independent_case_observation_claimed": False,
        "semantic_coverage_mapping_count": len(mapping_results),
        "semantic_coverage_mapping_digest": hashlib.sha256(
            rc._canonical(mapping_results)
        ).hexdigest(),
        "local_exact_sha_app_case_ids": ["CAP-RELEASE-CANARY", "UX-009-a"],
        "real_external_effects": 0,
        "status": "PASS_LOCAL_APP_GATE_REQUIRED",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--canary-2-receipt", type=Path)
    parser.add_argument("--canary-8-receipt", type=Path)
    parser.add_argument("--hosted-unit-only", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.hosted_unit_only:
            if args.canary_2_receipt or args.canary_8_receipt:
                raise RuntimeError("CONFORMANCE_HOSTED_CANARY_FORBIDDEN")
            value = hosted_run(args.root.resolve(), args.candidate)
        else:
            if (
                not args.canary_2_receipt
                or not args.canary_8_receipt
                or not args.output
            ):
                raise RuntimeError("CONFORMANCE_FINAL_RECEIPTS_REQUIRED")
            value = run(
                args.root.resolve(),
                args.candidate,
                args.canary_2_receipt,
                args.canary_8_receipt,
            )
        if args.output:
            args.output.write_bytes(rc._canonical(value) + b"\n")
        summary = {"status": value["status"], "case_count": value["case_count"]}
        if "case_results_digest" in value:
            summary["case_results_digest"] = value["case_results_digest"]
        print(json.dumps(summary, sort_keys=True))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError, rc.RcValidationError) as exc:
        print(f"CONFORMANCE_FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
