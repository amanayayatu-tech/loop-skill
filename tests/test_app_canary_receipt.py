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
            "finalization_acked": True,
        }
        self.receipt = {
            "schema_version": "app-canary-receipt-v3",
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
                "protocol_version": "2025-11-25",
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
        self.receipt["mcp"]["protocol_version"] = "changed"
        self.path.write_text(json.dumps(self.receipt), encoding="utf-8")
        with self.assertRaisesRegex(validator.CanaryReceiptError, "CANARY_COMPATIBILITY_IDENTITY_MISMATCH"):
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
        self.receipt["checks"]["finalization_acked"] = False
        self._seal()
        with self.assertRaisesRegex(validator.CanaryReceiptError, "CANARY_PASS_INCOMPLETE"):
            validator.validate_receipt(self.path, SCHEMA)

    def test_pass_requires_native_goal_recovery_to_be_explicitly_unavailable(self) -> None:
        self.receipt["checks"].pop("native_goal_generation_recovery_status")
        self._seal()
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate_receipt(self.path, SCHEMA)

        self.receipt["checks"]["native_goal_generation_recovery_status"] = "PASS"
        self._seal()
        with self.assertRaises(jsonschema.ValidationError):
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
