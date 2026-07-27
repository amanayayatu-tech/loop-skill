#!/usr/bin/env python3
"""Execute every frozen v4 corpus instance through its bound gate."""

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
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))


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
M = "test_v4_compatibility_import"
PS = "test_v4_persistence_spike"
PR = "test_v4_preservation_register"
PP = "test_v4_product_policy_operability"
PA = "test_v4_protocol_authority"
RC = "test_v4_rc_acceptance"
RD = "test_v4_rc_distribution"
UX = "test_v4_single_entry_ux"


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
    "CAP-COMPAT": _test(M, "V4LegacyEntryCompatibilityTests", "test_compact_full_and_minimal_patch_views_preserve_zero_start"),
    "CAP-DISTRIBUTION": _test(RD, "V4RcDistributionTests", "test_isolated_install_contains_v4_entry_and_zero_drift"),
    "CAP-DOCS": _test(RC, "V4RcAcceptanceTests", "test_bilingual_v4_docs_examples_and_release_boundary_are_present"),
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
    "M-001": _test(M, "V4CompatibilityImportTests", "test_shadow_preview_is_read_only_and_cancel_creates_no_destination"),
    "M-002": _test(M, "V4CompatibilityImportTests", "test_confirm_import_is_one_way_paused_and_exactly_replayable"),
    "M-003": _test(M, "V4CompatibilityImportTests", "test_schema2_standard_state_is_readable_by_v3_but_not_shape_copied"),
    "M-004": _test(M, "V4CompatibilityImportTests", "test_nonpaused_active_lease_and_nonquiescent_outbox_fail_closed"),
    "M-005": _test(M, "V4CompatibilityImportTests", "test_destination_nonempty_and_overlapping_roots_are_rejected"),
    "P-001": _test(PP, "V4ProductPolicyTests", "test_repair_is_bounded_and_same_failure_routes_to_human"),
    "P-002": _test(PP, "V4ProductPolicyTests", "test_repair_is_bounded_and_same_failure_routes_to_human"),
    "P-003": _test(PP, "V4ProductPolicyTests", "test_standard_is_fixed_dependency_order_and_adaptive_is_bounded"),
    "P-004": _test(PP, "V4ProductPolicyTests", "test_uncertain_repair_paused_and_cooperative_states_are_not_dead"),
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
    "UX-006": _test(M, "V4CompatibilityImportTests", "test_shadow_preview_is_read_only_and_cancel_creates_no_destination"),
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
    "CAP-COMPAT-SUNSET": _test(
        UX,
        "V4SingleEntryUXTests",
        "test_installed_skill_routes_explicit_v4_before_legacy_doctor",
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


def run(root: Path, candidate: str, canary_path: Path) -> dict[str, Any]:
    corpus = rc._run(
        root, "git", "show", f"{candidate}:{preservation.CORPUS_RELATIVE}"
    ).decode("utf-8", "strict")
    catalog, by_family = preservation._exact_case_catalog(corpus)
    if len(catalog) != 343:
        raise RuntimeError("CONFORMANCE_CASE_COUNT_DRIFT")
    canary = json.loads(canary_path.read_text(encoding="utf-8"))
    rc.validate_canary_receipt(canary, candidate)
    concrete_families = {family for family, cases in by_family.items() if cases}
    if set(FAMILY_TEST_BINDINGS) != concrete_families:
        raise RuntimeError("CONFORMANCE_FAMILY_BINDING_DRIFT")
    if not set(CASE_TEST_OVERRIDES) <= catalog:
        raise RuntimeError("CONFORMANCE_CASE_OVERRIDE_DRIFT")
    bindings = {
        case_id: (
            _family(case_id, by_family),
            CASE_TEST_OVERRIDES.get(
                case_id, FAMILY_TEST_BINDINGS[_family(case_id, by_family)]
            ),
        )
        for case_id in catalog
    }
    test_ids = sorted({test_id for _, test_id in bindings.values()})
    test_results = {test_id: _run_test(test_id) for test_id in test_ids}
    real_canary_cases = {"UX-009-a", "CAP-RELEASE-CANARY"}
    corpus_digest = hashlib.sha256(corpus.encode("utf-8")).hexdigest()
    results = []
    for case_id in sorted(catalog):
        family, test_id = bindings[case_id]
        parameter = case_id[len(family) + 1 :]
        contract = {
            "case_id": case_id,
            "corpus_sha256": corpus_digest,
            "family": family,
            "parameter": parameter,
            "test_id": test_id,
        }
        result = {
            "assertion_count": 1,
            "assertion_test_id": test_id,
            "case_id": case_id,
            "case_contract_digest": hashlib.sha256(rc._canonical(contract)).hexdigest(),
            "evidence_kind": (
                "REAL_APP_RECEIPT+UNITTEST_METHOD_PARAMETER"
                if case_id in real_canary_cases
                else "UNITTEST_METHOD_PARAMETER"
            ),
            "family": family,
            "parameter": parameter,
            "status": "PASS",
            "test_result_digest": test_results[test_id]["result_digest"],
        }
        if case_id in real_canary_cases:
            result["canary_receipt_sha256"] = hashlib.sha256(
                rc._canonical(canary)
            ).hexdigest()
        results.append(result)
    body = {
        "artifact": "loopskill-v4-conformance-execution-v1",
        "candidate_sha": candidate,
        "case_catalog_digest": preservation.EXACT_CASE_CATALOG_SHA256,
        "canonical_case_ids": True,
        "case_count": len(results),
        "case_results": results,
        "failed": 0,
        "corpus_sha256": corpus_digest,
        "passed": len(results),
        "real_external_effects": 1,
        "status": "PASS",
        "test_method_count": len(test_results),
        "test_method_results": [test_results[test_id] for test_id in test_ids],
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--canary-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        value = run(args.root.resolve(), args.candidate, args.canary_receipt)
        args.output.write_bytes(rc._canonical(value) + b"\n")
        print(json.dumps({"status": "PASS", "case_count": value["case_count"], "case_results_digest": value["case_results_digest"]}, sort_keys=True))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError, rc.RcValidationError) as exc:
        print(f"CONFORMANCE_FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
