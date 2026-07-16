from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "codex-loop-prompt-architect/scripts/validate_app_canary_receipt.py"
SCHEMA = ROOT / "codex-loop-prompt-architect/references/app-canary-receipt.schema.json"
SPEC = importlib.util.spec_from_file_location("validate_app_canary_receipt", SCRIPT)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class AppCanaryReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "receipt.json"
        checks = {
            "mcp_startup_ready": True,
            "route_tool_visible": True,
            "signed_direct_parent": True,
            "metadata_parser_negative_cases": True,
            "first_route_succeeded": True,
            "same_turn_second_route_rejected_before_side_effect": True,
            "same_turn_second_route_zero_effect": True,
            "next_turn_route_succeeded": True,
            "partial_frame_process_cleanup": True,
            "control_plane_responsive_after_partial_frame": True,
            "lost_stdout_recovered_without_second_send": True,
            "pack_migration_same_heartbeat_reconciled": True,
            "native_goal_generation_recovery_status": "DEFERRED_UNAVAILABLE",
            "native_goal_generation_recovery_cli": {
                "status": "NATIVE_GOAL_GENERATION_RECOVERY_UNAVAILABLE",
                "side_effects": "NONE",
                "before_state_digest": "1" * 64,
                "after_state_digest": "1" * 64,
                "evidence_digest": "2" * 64,
            },
            "native_goal_generation_recovery_mcp": {
                "status": "NATIVE_GOAL_GENERATION_RECOVERY_UNAVAILABLE",
                "side_effects": "NONE",
                "before_state_digest": "3" * 64,
                "after_state_digest": "3" * 64,
                "evidence_digest": "4" * 64,
            },
            "finalization_acked": True,
        }
        self.receipt = {
            "schema_version": "app-canary-receipt-v4",
            "evidence_layer": "local-main-mac",
            "status": "PASS",
            "started_at": "2026-07-15T15:00:00+08:00",
            "finished_at": "2026-07-15T15:03:00+08:00",
            "timezone": "Asia/Shanghai",
            "repo_commit": "a" * 40,
            "tracked_tree_digest": "f" * 64,
            "pack_digest": "sha256:" + "b" * 64,
            "installed_manifest_digest": "c" * 64,
            "local_pre_canary_gate": {
                "targeted_checks_passed": True,
                "full_unittest_passed": True,
                "branch_coverage_passed": True,
                "branch_coverage_percent": 81.25,
                "generator_fuzz_cases": 5000,
                "generator_fuzz_passed": True,
                "state_fuzz_cases": 5000,
                "state_fuzz_passed": True,
                "isolated_install_rollback_passed": True,
                "security_risky_artifact_passed": True,
                "source_install_drift": [],
            },
            "app": {"version": "1.2.3", "build": "456", "bundle_identifier": "com.openai.chat"},
            "app_server": {
                "executable_path": "/Applications/ChatGPT.app/Contents/Resources/codex",
                "codesign_verified": True,
                "identifier": "codex",
                "team_identifier": "2DC432GLL2",
                "cdhash": "d" * 40,
            },
            "mcp": {
                "negotiated_protocol_version_status": "UNAVAILABLE_BY_HOST",
                "negotiated_protocol_version": None,
                "negotiated_protocol_version_evidence_source": (
                    "HOST_DOES_NOT_EXPOSE_INITIALIZE_EXCHANGE"
                ),
                "client_protocol_observation": {
                    "status": "REQUESTED_VERSION_UNAVAILABLE_BY_HOST",
                    "requested_version": None,
                    "evidence_source": "APP_BUILD_AND_REAL_REQUEST_META",
                    "evidence_digest": "7" * 64,
                },
                "server_protocol_observation": {
                    "status": "DECLARED_BY_INSTALLED_SERVER",
                    "supported_versions": [
                        "2025-11-25",
                        "2025-06-18",
                        "2024-11-05",
                    ],
                    "evidence_source": "INSTALLED_SERVER_MCP_PROTOCOL_VERSIONS",
                    "evidence_digest": "8" * 64,
                    "installed_script_sha256": "e" * 64,
                },
                "config_schema_version": "codex-cli-mcp-stdio-v1",
                "request_meta_shape": {
                    "outer_keys": ["progressToken", "threadId", "x-codex-turn-metadata"],
                    "turn_metadata_keys": ["session_id", "thread_id", "turn_id"],
                },
                "identity_relations": {
                    "session_equals_thread": False,
                    "thread_equals_outer": True,
                    "turn_is_independent": True,
                    "next_turn_id_changed": True,
                },
                "registration": {
                    "server_name": "codex-loop-state",
                    "python_executable": "/stable/python",
                    "installed_script_path": "/Users/test/.codex/skills/codex-loop-prompt-architect/scripts/adaptive_state_mcp.py",
                    "installed_script_sha256": "e" * 64,
                    "config_readback": True,
                    "source_install_drift": [],
                    "app_refresh_or_restart": "RESTART",
                },
            },
            "checks": checks,
            "error_classification": None,
            "contains_sensitive_content": False,
        }
        self._seal()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _seal(self) -> None:
        self.receipt.pop("compatibility_identity_digest", None)
        self.receipt.pop("receipt_digest", None)
        self.receipt["compatibility_identity_digest"] = validator._digest(validator.compatibility_identity(self.receipt))
        self.receipt["receipt_digest"] = validator._digest(self.receipt)
        self.path.write_text(json.dumps(self.receipt), encoding="utf-8")

    def _restore(self, receipt: dict[str, object]) -> None:
        self.receipt = copy.deepcopy(receipt)
        self._seal()

    def test_valid_pass_binds_exact_release_and_app_identity(self) -> None:
        result = validator.validate_receipt(
            self.path,
            SCHEMA,
            expected_commit="a" * 40,
            expected_tracked_tree_digest="f" * 64,
            expected_manifest_digest="c" * 64,
            expected_pack_digest="sha256:" + "b" * 64,
            expected_compatibility_identity_digest=self.receipt[
                "compatibility_identity_digest"
            ],
            expected_app_version="1.2.3",
            expected_app_build="456",
            expected_bundle_identifier="com.openai.chat",
        )
        self.assertEqual(result["status"], "PASS")

    def test_tracked_tree_is_required_and_bound_to_the_exact_candidate(self) -> None:
        self.receipt.pop("tracked_tree_digest")
        self._seal()
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate_receipt(self.path, SCHEMA)

        self.receipt["tracked_tree_digest"] = "f" * 64
        self._seal()
        with self.assertRaisesRegex(
            validator.CanaryReceiptError, "CANARY_TRACKED_TREE_MISMATCH"
        ):
            validator.validate_receipt(
                self.path,
                SCHEMA,
                expected_tracked_tree_digest="0" * 64,
            )

    def test_app_or_metadata_change_invalidates_old_receipt(self) -> None:
        with self.assertRaisesRegex(validator.CanaryReceiptError, "CANARY_APP_BUILD_MISMATCH"):
            validator.validate_receipt(self.path, SCHEMA, expected_app_build="457")
        with self.assertRaisesRegex(validator.CanaryReceiptError, "CANARY_CURRENT_APP_IDENTITY_MISMATCH"):
            validator.validate_receipt(
                self.path,
                SCHEMA,
                expected_compatibility_identity_digest="f" * 64,
            )
        self.receipt["mcp"]["server_protocol_observation"][
            "supported_versions"
        ].append("2026-01-01")
        self.path.write_text(json.dumps(self.receipt), encoding="utf-8")
        with self.assertRaisesRegex(validator.CanaryReceiptError, "CANARY_COMPATIBILITY_IDENTITY_MISMATCH"):
            validator.validate_receipt(self.path, SCHEMA)

    def test_host_unavailable_negotiated_version_is_explicit_and_can_pass(self) -> None:
        result = validator.validate_receipt(self.path, SCHEMA)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(
            result["mcp"]["negotiated_protocol_version_status"],
            "UNAVAILABLE_BY_HOST",
        )
        self.assertIsNone(result["mcp"]["negotiated_protocol_version"])

    def test_negotiated_status_and_value_must_form_a_valid_branch(self) -> None:
        baseline = copy.deepcopy(self.receipt)
        cases = (
            (
                "unavailable-with-value",
                {
                    "negotiated_protocol_version_status": "UNAVAILABLE_BY_HOST",
                    "negotiated_protocol_version": "2025-11-25",
                    "negotiated_protocol_version_evidence_source": (
                        "HOST_DOES_NOT_EXPOSE_INITIALIZE_EXCHANGE"
                    ),
                },
            ),
            (
                "verified-with-null",
                {
                    "negotiated_protocol_version_status": "VERIFIED_BY_HOST_EXCHANGE",
                    "negotiated_protocol_version": None,
                    "negotiated_protocol_version_evidence_source": (
                        "HOST_INITIALIZE_EXCHANGE"
                    ),
                },
            ),
            (
                "verified-with-readback-source",
                {
                    "negotiated_protocol_version_status": "VERIFIED_BY_HOST_EXCHANGE",
                    "negotiated_protocol_version": "2025-11-25",
                    "negotiated_protocol_version_evidence_source": (
                        "INSTALLED_SERVER_MCP_PROTOCOL_VERSIONS"
                    ),
                },
            ),
        )
        for name, updates in cases:
            with self.subTest(name=name):
                self.receipt["mcp"].update(updates)
                self._seal()
                with self.assertRaises(jsonschema.ValidationError):
                    validator.validate_receipt(self.path, SCHEMA)
                self._restore(baseline)

    def test_verified_negotiated_version_requires_host_exchange_and_server_support(self) -> None:
        self.receipt["mcp"].update(
            {
                "negotiated_protocol_version_status": "VERIFIED_BY_HOST_EXCHANGE",
                "negotiated_protocol_version": "2025-11-25",
                "negotiated_protocol_version_evidence_source": "HOST_INITIALIZE_EXCHANGE",
            }
        )
        self._seal()
        self.assertEqual(validator.validate_receipt(self.path, SCHEMA)["status"], "PASS")

        self.receipt["mcp"]["negotiated_protocol_version"] = "2026-01-01"
        self._seal()
        with self.assertRaisesRegex(
            validator.CanaryReceiptError,
            "CANARY_NEGOTIATED_PROTOCOL_SERVER_UNSUPPORTED",
        ):
            validator.validate_receipt(self.path, SCHEMA)

    def test_client_and_server_observations_are_constrained_and_identity_bound(self) -> None:
        baseline = copy.deepcopy(self.receipt)
        for field, value in (
            ("client_protocol_observation", {
                "status": "REQUESTED_VERSION_UNAVAILABLE_BY_HOST",
                "requested_version": None,
                "evidence_source": "CALLER_ASSERTION",
                "evidence_digest": "7" * 64,
            }),
            ("server_protocol_observation", {
                "status": "DECLARED_BY_INSTALLED_SERVER",
                "supported_versions": ["2025-11-25"],
                "evidence_source": "CALLER_ASSERTION",
                "evidence_digest": "8" * 64,
                "installed_script_sha256": "e" * 64,
            }),
        ):
            with self.subTest(field=field):
                self.receipt["mcp"][field] = value
                self._seal()
                with self.assertRaises(jsonschema.ValidationError):
                    validator.validate_receipt(self.path, SCHEMA)
                self._restore(baseline)

        self.receipt["mcp"]["server_protocol_observation"][
            "installed_script_sha256"
        ] = "9" * 64
        self._seal()
        with self.assertRaisesRegex(
            validator.CanaryReceiptError,
            "CANARY_SERVER_PROTOCOL_SCRIPT_IDENTITY_MISMATCH",
        ):
            validator.validate_receipt(self.path, SCHEMA)

    def test_every_protocol_observation_is_compatibility_identity_bound(self) -> None:
        baseline = copy.deepcopy(self.receipt)
        mutations = (
            ("negotiated-status", lambda receipt: receipt["mcp"].update({
                "negotiated_protocol_version_status": "VERIFIED_BY_HOST_EXCHANGE",
                "negotiated_protocol_version": "2025-11-25",
                "negotiated_protocol_version_evidence_source": "HOST_INITIALIZE_EXCHANGE",
            })),
            ("client-observation", lambda receipt: receipt["mcp"][
                "client_protocol_observation"
            ].update({
                "status": "REQUESTED_VERSION_OBSERVED",
                "requested_version": "2025-11-25",
                "evidence_source": "HOST_INITIALIZE_REQUEST",
            })),
            ("server-observation", lambda receipt: receipt["mcp"][
                "server_protocol_observation"
            ]["supported_versions"].append("2026-01-01")),
        )
        for name, mutate in mutations:
            with self.subTest(name=name):
                self._restore(baseline)
                stale_digest = self.receipt["compatibility_identity_digest"]
                mutate(self.receipt)
                self.path.write_text(json.dumps(self.receipt), encoding="utf-8")
                with self.assertRaisesRegex(
                    validator.CanaryReceiptError,
                    "CANARY_COMPATIBILITY_IDENTITY_MISMATCH",
                ):
                    validator.validate_receipt(
                        self.path,
                        SCHEMA,
                        expected_compatibility_identity_digest=stale_digest,
                    )

    def test_v3_receipt_is_not_silently_accepted_by_v4_schema(self) -> None:
        self.receipt["schema_version"] = "app-canary-receipt-v3"
        self.receipt["mcp"]["protocol_version"] = "2025-11-25"
        for field in (
            "negotiated_protocol_version_status",
            "negotiated_protocol_version",
            "negotiated_protocol_version_evidence_source",
            "client_protocol_observation",
            "server_protocol_observation",
        ):
            self.receipt["mcp"].pop(field)
        self.path.write_text(json.dumps(self.receipt), encoding="utf-8")
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate_receipt(self.path, SCHEMA)

    def test_pass_requires_complete_local_main_mac_pre_canary_gate(self) -> None:
        self.receipt["local_pre_canary_gate"]["generator_fuzz_cases"] = 4999
        self._seal()
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate_receipt(self.path, SCHEMA)

        self.receipt["local_pre_canary_gate"]["generator_fuzz_cases"] = 5000
        self.receipt["local_pre_canary_gate"]["source_install_drift"] = [
            "unexpected.py"
        ]
        self._seal()
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate_receipt(self.path, SCHEMA)

    def test_remote_or_legacy_evidence_layer_is_rejected(self) -> None:
        for layer in ("mac-app-smoke", "independent-host", "remote-attestation"):
            with self.subTest(layer=layer):
                self.receipt["evidence_layer"] = layer
                self._seal()
                with self.assertRaises(jsonschema.ValidationError):
                    validator.validate_receipt(self.path, SCHEMA)

    def test_session_and_thread_may_differ_but_raw_identities_are_forbidden(self) -> None:
        self.assertFalse(self.receipt["mcp"]["identity_relations"]["session_equals_thread"])
        self.receipt["session_id"] = "secret-session"
        self.path.write_text(json.dumps(self.receipt), encoding="utf-8")
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate_receipt(self.path, SCHEMA)

    def test_pass_requires_every_real_canary_and_no_error(self) -> None:
        baseline = copy.deepcopy(self.receipt)
        for check in (
            "signed_direct_parent",
            "metadata_parser_negative_cases",
            "first_route_succeeded",
            "same_turn_second_route_zero_effect",
            "finalization_acked",
        ):
            with self.subTest(check=check):
                self._restore(baseline)
                self.receipt["checks"][check] = False
                self._seal()
                with self.assertRaisesRegex(
                    validator.CanaryReceiptError,
                    "CANARY_PASS_INCOMPLETE",
                ):
                    validator.validate_receipt(self.path, SCHEMA)

    def test_pass_requires_native_goal_recovery_to_be_explicitly_unavailable(self) -> None:
        self.receipt["checks"].pop("native_goal_generation_recovery_status")
        self._seal()
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate_receipt(self.path, SCHEMA)

        self.receipt["checks"]["native_goal_generation_recovery_status"] = (
            "DEFERRED_UNAVAILABLE"
        )
        self.receipt["checks"].pop("native_goal_generation_recovery_cli")
        self._seal()
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate_receipt(self.path, SCHEMA)

        self.receipt["checks"]["native_goal_generation_recovery_cli"] = {
            "status": "NATIVE_GOAL_GENERATION_RECOVERY_UNAVAILABLE",
            "side_effects": "NONE",
            "before_state_digest": "1" * 64,
            "after_state_digest": "1" * 64,
            "evidence_digest": "2" * 64,
        }
        self.receipt["checks"]["native_goal_generation_recovery_status"] = "PASS"
        self._seal()
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate_receipt(self.path, SCHEMA)

    def test_recovery_surface_receipts_bind_zero_state_drift(self) -> None:
        self.receipt["checks"]["native_goal_generation_recovery_cli"][
            "after_state_digest"
        ] = "9" * 64
        self._seal()
        with self.assertRaisesRegex(
            validator.CanaryReceiptError,
            "CANARY_RECOVERY_SURFACE_SIDE_EFFECT",
        ):
            validator.validate_receipt(self.path, SCHEMA)

    def test_blocked_receipt_requires_precise_classification(self) -> None:
        self.receipt["status"] = "BLOCKED"
        self.receipt["checks"]["mcp_startup_ready"] = False
        self.receipt["error_classification"] = "MCP_REGISTRATION_INVALID"
        self._seal()
        self.assertEqual(validator.validate_receipt(self.path, SCHEMA)["status"], "BLOCKED")
        self.receipt["error_classification"] = None
        self._seal()
        with self.assertRaisesRegex(validator.CanaryReceiptError, "CANARY_FAILURE_CLASSIFICATION_MISSING"):
            validator.validate_receipt(self.path, SCHEMA)

    def test_secret_bearing_field_or_bearer_value_is_rejected(self) -> None:
        receipt = copy.deepcopy(self.receipt)
        receipt["app"]["version"] = "Bearer abc.def"
        self.path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(validator.CanaryReceiptError, "CANARY_RECEIPT_AUTHORIZATION_VALUE"):
            validator.validate_receipt(self.path, SCHEMA)


if __name__ == "__main__":
    unittest.main()
