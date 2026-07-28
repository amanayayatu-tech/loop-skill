from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest import mock

from tests.test_v4_author_packet import receipt_for


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


def live_observation(candidate: str) -> dict:
    return {
        "artifact_state": "VERIFIED",
        "assurance": "STRICT",
        "canary_output_sha256": validator.CANARY_OUTPUT_SHA256,
        "candidate_goal_digest": "e" * 64,
        "candidate_sha": candidate,
        "execution_disposition": "SUCCEEDED",
        "execution_state": "TERMINAL",
        "finalization_state": "EXECUTION_CLOSED",
        "host_task_identity_digest": "c" * 64,
        "lifecycle_state": "TERMINAL",
        "result_digest": "b" * 64,
        "result_outcome": "PASS",
        "result_state": "ACKNOWLEDGED",
        "report_state": "ACCEPTED",
        "review_state": "PASS",
        "snapshot_digest": "d" * 64,
    }


def canary(candidate: str) -> dict:
    live = live_observation(candidate)
    issued = datetime.now(timezone.utc).replace(microsecond=0)
    fresh_until = issued + timedelta(minutes=5)
    issued_text = issued.isoformat().replace("+00:00", "Z")
    fresh_text = fresh_until.isoformat().replace("+00:00", "Z")
    value = {
        "artifact": "loopskill-v4-disposable-app-canary-v1",
        "candidate_sha": candidate,
        "candidate_goal_digest": live["candidate_goal_digest"],
        "canary_output_sha256": live["canary_output_sha256"],
        "confirmation_count": 1,
        "confirmation_digest_bound": True,
        "config_bytes_changed": 0,
        "entry": "loopskill4",
        "finalization": "ACKNOWLEDGED",
        "fresh_until": fresh_text,
        "host_receipt_issuer": validator.CANARY_ISSUER,
        "host_receipt_trust": validator.CANARY_TRUST,
        "host_create_readback_count": 1,
        "host_lifecycle_readback_count": 1,
        "host_result_digest": live["result_digest"],
        "host_task_create_count": 1,
        "host_task_identity_digest": live["host_task_identity_digest"],
        "host_task_readback_count": 1,
        "host_terminal_wait_readback_count": 1,
        "host_total_read_count": 4,
        "intake_external_effects": 0,
        "intake_heartbeat_count": 0,
        "intake_host_task_count": 0,
        "intake_loop_count": 0,
        "issued_at": issued_text,
        "loopskill_mcp_registration_count": 0,
        "machine_owned_identity": True,
        "manual_control_identity_count": 0,
        "observed_at": issued_text,
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
    value["host_receipt_digest"] = validator._domain_digest(
        validator.CANARY_LIVE_DOMAIN, live
    )
    return value


class V4RcAcceptanceTests(unittest.TestCase):
    def test_final_cli_requires_canary_conformance_and_author_packet(self) -> None:
        stream = StringIO()
        with mock.patch.object(
            validator,
            "static_receipt",
            return_value={"artifact": "loopskill-v4-publication-static-receipt-v1"},
        ), redirect_stderr(stream):
            result = validator.main(["--root", str(ROOT), "--candidate", "a" * 40])
        self.assertEqual(result, 1)
        self.assertIn("RC_FINAL_RECEIPTS_REQUIRED", stream.getvalue())

    def test_self_asserted_canary_json_cannot_replace_bound_store_evidence(self) -> None:
        candidate = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = []
            for name, payload in (
                ("canary.json", canary(candidate)),
                ("conformance.json", {}),
                ("packet.json", {}),
            ):
                path = root / name
                path.write_text(json.dumps(payload), encoding="utf-8")
                paths.append(path)
            stream = StringIO()
            with mock.patch.object(
                validator,
                "static_receipt",
                return_value={
                    "artifact": "loopskill-v4-publication-static-receipt-v1"
                },
            ), redirect_stderr(stream):
                result = validator.main(
                    [
                        "--root",
                        str(ROOT),
                        "--candidate",
                        candidate,
                        "--canary-receipt",
                        str(paths[0]),
                        "--conformance-receipt",
                        str(paths[1]),
                        "--author-packet",
                        str(paths[2]),
                    ]
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
            ("host_create_readback_count", 4),
            ("host_lifecycle_readback_count", 2),
            ("host_terminal_wait_readback_count", 0),
            ("host_total_read_count", 5),
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
            (
                "fresh_until",
                (datetime.now(timezone.utc) + timedelta(hours=1))
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
            ),
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
        for offset in (timedelta(days=-1), timedelta(minutes=2)):
            with self.subTest(freshness_offset=offset):
                value = canary(candidate)
                observed = datetime.now(timezone.utc).replace(microsecond=0) + offset
                value["issued_at"] = observed.isoformat().replace("+00:00", "Z")
                value["observed_at"] = value["issued_at"]
                value["fresh_until"] = (observed + timedelta(minutes=5)).isoformat().replace(
                    "+00:00", "Z"
                )
                provenance = dict(value)
                provenance.pop("provenance_digest")
                provenance.pop("host_receipt_digest")
                value["provenance_digest"] = validator._domain_digest(
                    validator.CANARY_PROVENANCE_DOMAIN, provenance
                )
                with self.assertRaisesRegex(
                    validator.RcValidationError, "RC_CANARY_RECEIPT_INVALID: freshness"
                ):
                    validator.validate_canary_receipt(value, candidate)

    def test_live_canary_requires_same_process_receipt_and_exact_store_bindings(self) -> None:
        candidate = "a" * 40
        value = canary(candidate)
        with mock.patch.object(
            validator,
            "_live_canary_observation",
            return_value=live_observation(candidate),
        ) as readback:
            digest = validator.validate_live_canary(
                value,
                candidate,
                ROOT,
                Path("synthetic-live-store"),
            )
        self.assertEqual(
            digest,
            validator._domain_digest(
                validator.CANARY_LIVE_DOMAIN, live_observation(candidate)
            ),
        )
        readback.assert_called_once()
        for field in (
            "host_receipt_digest",
            "host_task_identity_digest",
            "host_result_digest",
            "candidate_goal_digest",
        ):
            with self.subTest(field=field), mock.patch.object(
                validator,
                "_live_canary_observation",
                return_value=live_observation(candidate),
            ):
                changed = canary(candidate)
                changed[field] = "f" * 64
                if field != "host_receipt_digest":
                    provenance = dict(changed)
                    provenance.pop("provenance_digest")
                    provenance.pop("host_receipt_digest")
                    changed["provenance_digest"] = validator._domain_digest(
                        validator.CANARY_PROVENANCE_DOMAIN, provenance
                    )
                with self.assertRaisesRegex(
                    validator.RcValidationError,
                    "RC_CANARY_LIVE_BINDING_INVALID",
                ):
                    validator.validate_live_canary(
                        changed,
                        candidate,
                        ROOT,
                        Path("synthetic-live-store"),
                    )

    def test_publication_packet_requires_exact_files_evidence_and_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as evidence_directory:
            root = Path(directory)
            evidence_root = Path(evidence_directory)
            subprocess.run(("git", "init", "--quiet"), cwd=root, check=True)
            builder_path = root / "scripts/build_v4_author_packet.py"
            builder_path.parent.mkdir(parents=True)
            builder_path.write_bytes(
                (ROOT / "scripts/build_v4_author_packet.py").read_bytes()
            )
            builder = validator._load_author_packet_builder(root)
            for index, relative in enumerate(builder.REQUIRED_TRACKED_FILES):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"public fixture {index}: {relative}\n", encoding="utf-8")
            subprocess.run(("git", "add", "."), cwd=root, check=True)
            subprocess.run(
                (
                    "git",
                    "-c",
                    "commit.gpgsign=false",
                    "-c",
                    "user.name=LoopSkill Test",
                    "-c",
                    "user.email=loopskill-test@example.invalid",
                    "commit",
                    "--quiet",
                    "-m",
                    "fixture",
                ),
                cwd=root,
                check=True,
            )
            candidate = subprocess.check_output(
                ("git", "rev-parse", "HEAD"), cwd=root, text=True
            ).strip()
            subprocess.run(
                ("git", "update-ref", "refs/remotes/origin/main", candidate),
                cwd=root,
                check=True,
            )
            subprocess.run(("git", "tag", "v3.3.8", candidate), cwd=root, check=True)
            subprocess.run(
                ("git", "tag", "paper-treatment-v3.3.12", candidate),
                cwd=root,
                check=True,
            )
            evidence = {}
            for index, key in enumerate(builder.REQUIRED_EVIDENCE_RECEIPTS):
                path = evidence_root / f"receipt-{index}.json"
                receipt = receipt_for(key, candidate)
                if key == "release_identity_preflight":
                    receipt.update(
                        {
                            "origin_main_commit": candidate,
                            "paper_reference_commit": candidate,
                            "v3_baseline_commit": candidate,
                        }
                    )
                path.write_text(
                    json.dumps(receipt),
                    encoding="utf-8",
                )
                evidence[key] = path
            packet = builder.build_packet(root, candidate, evidence)
            fault_contract = mock.patch.object(
                validator, "_fault_contract_counts", return_value=(3, 9, 11)
            )
            fault_contract.start()
            self.addCleanup(fault_contract.stop)
            validator.validate_author_packet(packet, candidate, root, evidence)
            changed = dict(packet)
            changed["public_release_effects"] = 1
            with self.assertRaisesRegex(
                validator.RcValidationError, "RC_AUTHOR_PACKET_INVALID"
            ):
                validator.validate_author_packet(changed, candidate, root, evidence)
            changed = dict(packet)
            changed["evidence_receipts"] = dict(packet["evidence_receipts"])
            changed["evidence_receipts"].pop("coverage")
            with self.assertRaisesRegex(
                validator.RcValidationError, "RC_AUTHOR_PACKET_EVIDENCE_INVALID"
            ):
                validator.validate_author_packet(changed, candidate, root, evidence)
            forged = dict(packet)
            forged["evidence_receipts"] = {
                key: "f" * 64 for key in packet["evidence_receipts"]
            }
            forged_body = {
                key: item for key, item in forged.items() if key != "packet_digest"
            }
            forged["packet_digest"] = builder._packet_digest(forged_body)
            with self.assertRaisesRegex(
                validator.RcValidationError,
                "RC_AUTHOR_PACKET_EVIDENCE_DIGEST_MISMATCH",
            ):
                validator.validate_author_packet(forged, candidate, root, evidence)

    def test_conformance_receipt_requires_all_349_canonical_results(self) -> None:
        candidate = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canary.json"
            path.write_bytes(validator._canonical(canary(candidate)))
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
        changed_profile = dict(value)
        changed_profile["evidence_profile"] = "SELECTOR_SPECIFIC_OBSERVATIONS"
        with self.assertRaisesRegex(
            validator.RcValidationError, "RC_CONFORMANCE_RECEIPT_INVALID"
        ):
            validator.validate_conformance_receipt(changed_profile, candidate, ROOT)
        changed_profile = dict(value)
        changed_profile["independent_case_observation_claimed"] = True
        with self.assertRaisesRegex(
            validator.RcValidationError, "RC_CONFORMANCE_RECEIPT_INVALID"
        ):
            validator.validate_conformance_receipt(changed_profile, candidate, ROOT)
        changed_count = dict(value)
        changed_count["test_method_count"] = 73
        with self.assertRaisesRegex(
            validator.RcValidationError, "RC_CONFORMANCE_RECEIPT_INVALID"
        ):
            validator.validate_conformance_receipt(changed_count, candidate, ROOT)
        changed_mapping_count = dict(value)
        changed_mapping_count["semantic_coverage_mapping_count"] = 348
        with self.assertRaisesRegex(
            validator.RcValidationError, "RC_CONFORMANCE_RECEIPT_INVALID"
        ):
            validator.validate_conformance_receipt(
                changed_mapping_count, candidate, ROOT
            )
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
            self.assertEqual(receipt["distribution_archive"]["findings"], [])
            self.assertEqual(receipt["distribution_archive"]["file_count"], 3)
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

            retired.unlink()
            retired_doc = repo / "P0-CLOSURE.md"
            retired_doc.write_text("retired v3 current-product narrative\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "retired docs"], cwd=repo, check=True)
            stale_doc_sha = subprocess.check_output(
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
                validator.static_receipt(repo, stale_doc_sha)

    def test_distribution_archive_rejects_unsafe_members(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "fixture@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Fixture"],
                cwd=repo,
                check=True,
            )
            (repo / "safe.txt").write_text("safe\n", encoding="utf-8")
            (repo / "unsafe-link").symlink_to("safe.txt")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
            sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            with self.assertRaisesRegex(
                validator.RcValidationError,
                "RC_DISTRIBUTION_ARCHIVE_SCAN_FAILED",
            ):
                validator._distribution_archive_receipt(repo, sha)


if __name__ == "__main__":
    unittest.main()
