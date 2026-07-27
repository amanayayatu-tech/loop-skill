from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/validate_v4_rc.py"
SPEC = importlib.util.spec_from_file_location("validate_v4_rc", MODULE_PATH)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)

RUNNER_PATH = ROOT / "scripts/run_v4_conformance.py"
RUNNER_SPEC = importlib.util.spec_from_file_location("run_v4_conformance_for_rc_test", RUNNER_PATH)
assert RUNNER_SPEC and RUNNER_SPEC.loader
runner = importlib.util.module_from_spec(RUNNER_SPEC)
RUNNER_SPEC.loader.exec_module(runner)


def canary(candidate: str) -> dict:
    value = {
        "artifact": "loopskill-v4-disposable-app-canary-v1",
        "candidate_sha": candidate,
        "canary_output_sha256": "b" * 64,
        "confirmation_count": 1,
        "confirmation_digest_bound": True,
        "config_bytes_changed": 0,
        "entry": "loopskill4",
        "finalization": "ACKNOWLEDGED",
        "fresh_until": "2026-07-27T13:22:46Z",
        "host_receipt_issuer": validator.CANARY_ISSUER,
        "host_receipt_trust": validator.CANARY_TRUST,
        "host_task_create_count": 1,
        "host_task_identity_digest": "c" * 64,
        "host_task_readback_count": 1,
        "intake_external_effects": 0,
        "intake_heartbeat_count": 0,
        "intake_host_task_count": 0,
        "intake_loop_count": 0,
        "issued_at": "2026-07-27T13:12:46Z",
        "loopskill_mcp_registration_count": 0,
        "machine_owned_identity": True,
        "manual_control_identity_count": 0,
        "observed_at": "2026-07-27T13:12:46Z",
        "app_restart_count": 0,
        "prepare_delivery_count": 0,
        "prepare_heartbeat_count": 0,
        "prepare_host_effects": 0,
        "prepare_host_task_count": 0,
        "private_data_used": False,
        "provider_resend_count": 0,
        "research_scored": False,
        "result": "ACKNOWLEDGED",
        "review": "PASS",
        "status": "PASS",
        "thread_content_retained": False,
        "unknown_preserved": True,
        "v3_bytes_changed": 0,
    }
    value["provenance_digest"] = validator._domain_digest(
        validator.CANARY_PROVENANCE_DOMAIN, value
    )
    value["host_receipt_digest"] = value["provenance_digest"]
    return value


class V4RcAcceptanceTests(unittest.TestCase):
    def test_final_cli_requires_canary_conformance_and_author_packet(self) -> None:
        stream = StringIO()
        with mock.patch.object(
            validator,
            "static_receipt",
            return_value={"artifact": "loopskill-v4-publication-static-receipt-v1"},
        ), redirect_stderr(stream):
            result = validator.main(
                ["--root", str(ROOT), "--candidate", "a" * 40, "--allow-non-head"]
            )
        self.assertEqual(result, 1)
        self.assertIn("RC_FINAL_RECEIPTS_REQUIRED", stream.getvalue())

    def test_bilingual_v4_docs_examples_and_release_boundary_are_present(self) -> None:
        chinese = (ROOT / "docs/v4/quickstart.zh-CN.md").read_text(encoding="utf-8")
        english = (ROOT / "docs/v4/quickstart.en.md").read_text(encoding="utf-8")
        migration = (ROOT / "docs/v4/migration-and-rollback.md").read_text(encoding="utf-8")
        limitations = (ROOT / "docs/v4/known-limitations.md").read_text(encoding="utf-8")
        release_notes = (ROOT / "docs/v4/release-notes.md").read_text(encoding="utf-8")
        self.assertIn("INTAKE → PREPARE → CONFIRM → START", chinese)
        self.assertIn("INTAKE → PREPARE → CONFIRM → START", english)
        self.assertIn("does not ship v3 read/shadow/import", migration)
        self.assertIn("automatically migrate v3", release_notes)
        self.assertIn("patch-success superiority", limitations)
        self.assertIn("release notes for LoopSkill 4.0.0", release_notes)
        self.assertIn("docs/v4/quickstart.zh-CN.md", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("docs/v4/quickstart.en.md", (ROOT / "README.en.md").read_text(encoding="utf-8"))
        self.assertEqual(
            len(list((ROOT / "examples").glob("v4-*-input.json"))), 2
        )

    def test_canary_receipt_is_minimized_and_fail_closed(self) -> None:
        candidate = "a" * 40
        validator.validate_canary_receipt(canary(candidate), candidate)
        for field, invalid in (
            ("confirmation_count", 0),
            ("confirmation_digest_bound", False),
            ("config_bytes_changed", 1),
            ("host_task_create_count", 2),
            ("intake_loop_count", 1),
            ("loopskill_mcp_registration_count", 1),
            ("manual_control_identity_count", 1),
            ("app_restart_count", 1),
            ("prepare_delivery_count", 1),
            ("private_data_used", True),
            ("provider_resend_count", 1),
            ("v3_bytes_changed", 1),
            ("finalization", "UNKNOWN"),
            ("host_receipt_issuer", "self-asserted"),
            ("host_receipt_trust", "untrusted"),
            ("fresh_until", "2026-07-27T14:12:46Z"),
        ):
            with self.subTest(field=field):
                value = canary(candidate)
                value[field] = invalid
                with self.assertRaisesRegex(
                    validator.RcValidationError, "RC_CANARY_RECEIPT_INVALID"
                ):
                    validator.validate_canary_receipt(value, candidate)
        value = canary(candidate)
        value["thread_id"] = "raw-host-identity"
        with self.assertRaisesRegex(
            validator.RcValidationError, "RC_CANARY_RECEIPT_SHAPE_INVALID"
        ):
            validator.validate_canary_receipt(value, candidate)

    def test_publication_packet_requires_exact_files_and_zero_prior_release_effects(self) -> None:
        candidate = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {}
            for index in range(12):
                relative = f"safe/file-{index}.txt"
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"safe-{index}\n", encoding="utf-8")
                files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
            packet = {
                "artifact": "loopskill-v4-publication-packet-v1",
                "candidate_sha": candidate,
                "files": files,
                "public_release_effects": 0,
                "real_v3_loop_migrations": 0,
                "status": "PUBLICATION_CANDIDATE_VALIDATED",
            }
            validator.validate_author_packet(packet, candidate, root)
            packet["public_release_effects"] = 1
            with self.assertRaisesRegex(
                validator.RcValidationError, "RC_AUTHOR_PACKET_INVALID"
            ):
                validator.validate_author_packet(packet, candidate, root)

    def test_conformance_receipt_requires_all_343_canonical_results(self) -> None:
        candidate = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canary.json"
            path.write_text(json.dumps(canary(candidate)), encoding="utf-8")
            with mock.patch.object(
                runner,
                "_run_test",
                side_effect=lambda test_id: {
                    "assertion_test_id": test_id,
                    "result_digest": hashlib.sha256(
                        validator._canonical(
                            {"assertion_test_id": test_id, "status": "PASS", "tests_run": 1}
                        )
                    ).hexdigest(),
                    "status": "PASS",
                    "tests_run": 1,
                },
            ):
                value = runner.run(ROOT, candidate, path)
        validator.validate_conformance_receipt(value, candidate, ROOT)
        value["case_results"][0]["case_id"] = "CASE-NOT-IN-FROZEN-CATALOG"
        value["case_results_digest"] = hashlib.sha256(
            validator._canonical(value["case_results"])
        ).hexdigest()
        value["case_results"][0]["status"] = "FAIL"
        with self.assertRaisesRegex(
            validator.RcValidationError, "RC_CONFORMANCE_RECEIPT_INVALID"
        ):
            validator.validate_conformance_receipt(value, candidate, ROOT)

    def test_static_gate_binds_exact_clean_sha_tree_sbom_and_scans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Fixture"], cwd=repo, check=True)
            (repo / "protocol/v4").mkdir(parents=True)
            (repo / "protocol/v4/loopskill-v4.protocol.json").write_text(
                json.dumps(
                    {
                        "capability_names": ["c"],
                        "commands": {"C": {}},
                        "errors": ["E"],
                        "events": {"V": {}},
                    }
                ),
                encoding="utf-8",
            )
            (repo / "LICENSE").write_text("MIT License\n", encoding="utf-8")
            (repo / "VERSION").write_text("4.0.0\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
            sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            dependencies = [
                {"distribution": "fixture", "license": "MIT", "version": "1"}
            ]
            with mock.patch.object(
                validator, "_dependency_inventory", return_value=dependencies
            ), mock.patch.object(
                validator,
                "_runtime_identity",
                return_value={"runtime_identity_digest": "d" * 64},
            ):
                receipt = validator.static_receipt(repo, sha)
            self.assertEqual(receipt["candidate_sha"], sha)
            self.assertEqual(receipt["dependency_inventory"], dependencies)
            self.assertEqual(receipt["secret_findings"], [])
            self.assertEqual(receipt["stale_production_findings"], [])
            self.assertEqual(receipt["sbom"]["spdxVersion"], "SPDX-2.3")
            self.assertEqual(receipt["sbom"]["packages"][0]["versionInfo"], "4.0.0")
            self.assertEqual(
                receipt["sbom_sha256"],
                hashlib.sha256(validator._canonical(receipt["sbom"])).hexdigest(),
            )
            self.assertEqual(receipt["public_effects"], 0)
            (repo / "dirty").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(
                validator.RcValidationError, "NOT_EXACT_CLEAN_HEAD"
            ):
                validator.static_receipt(repo, sha)

            (repo / "dirty").unlink()
            retired = repo / "codex-loop-prompt-architect/scripts/runtime.py"
            retired.parent.mkdir(parents=True)
            retired.write_text("COMMAND = 'ImportV3Snapshot'\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "retired runtime"], cwd=repo, check=True)
            stale_sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            with mock.patch.object(
                validator, "_dependency_inventory", return_value=dependencies
            ), mock.patch.object(
                validator,
                "_runtime_identity",
                return_value={"runtime_identity_digest": "d" * 64},
            ), self.assertRaisesRegex(
                validator.RcValidationError, "STALE_V3_PRODUCTION_SCAN_FAILED"
            ):
                validator.static_receipt(repo, stale_sha)


if __name__ == "__main__":
    unittest.main()
