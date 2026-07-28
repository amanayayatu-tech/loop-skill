from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/build_v4_author_packet.py"
SPEC = importlib.util.spec_from_file_location("build_v4_author_packet", MODULE_PATH)
assert SPEC and SPEC.loader
packet_builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packet_builder)


def run_git(root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=root,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def receipt_for(key: str, candidate: str) -> dict:
    digest = "d" * 64
    common = {
        "artifact": packet_builder._EVIDENCE_ARTIFACTS[key],
        "candidate_sha": candidate,
    }
    if key == "app_canary":
        return {
            **common,
            "app_restart_count": 0,
            "candidate_goal_digest": digest,
            "canary_output_sha256": digest,
            "confirmation_count": 1,
            "confirmation_digest_bound": True,
            "config_bytes_changed": 0,
            "entry": "loopskill4",
            "finalization": "ACKNOWLEDGED",
            "host_create_readback_count": 1,
            "host_lifecycle_readback_count": 1,
            "host_receipt_digest": digest,
            "host_receipt_issuer": "codex-app-task-readback-v1",
            "host_receipt_trust": "host-tool-observed",
            "host_result_digest": digest,
            "host_task_create_count": 1,
            "host_task_identity_digest": digest,
            "host_task_readback_count": 1,
            "host_terminal_wait_readback_count": 1,
            "host_total_read_count": 4,
            "intake_external_effects": 0,
            "intake_heartbeat_count": 0,
            "intake_host_task_count": 0,
            "intake_loop_count": 0,
            "loopskill_mcp_registration_count": 0,
            "machine_owned_identity": True,
            "manual_control_identity_count": 0,
            "prepare_delivery_count": 0,
            "prepare_heartbeat_count": 0,
            "prepare_host_effects": 0,
            "prepare_host_task_count": 0,
            "private_data_used": False,
            "provenance_digest": digest,
            "provider_resend_count": 0,
            "research_scored": False,
            "result": "ACKNOWLEDGED",
            "review": "PASS",
            "status": "PASS",
            "thread_content_retained": False,
            "unknown_preserved": True,
            "v3_bytes_changed": 0,
        }
    if key == "coverage":
        return {
            **common,
            "covered_branches": 1200,
            "line_and_branch_percent": 80.5,
            "num_branches": 1400,
            "status": "PASS",
        }
    if key == "distribution":
        return {
            **common,
            "config_bytes_changed": 0,
            "distribution_log_sha256": digest,
            "mcp_entries_added": 0,
            "real_v3_loop_migrations": 0,
            "status": "PASS",
            "test_count": 12,
        }
    if key == "final_conformance":
        return {
            **common,
            "binding_manifest_digest": digest,
            "canonical_case_ids": True,
            "case_catalog_digest": digest,
            "case_count": 349,
            "case_results": [{} for _ in range(349)],
            "case_results_digest": digest,
            "corpus_sha256": digest,
            "evidence_profile": packet_builder._PROFILE_A,
            "failed": 0,
            "independent_case_observation_claimed": False,
            "mapped": 349,
            "passed_test_methods": 74,
            "real_external_effects": 1,
            "semantic_coverage_mapping_count": 349,
            "status": "PASS",
            "test_method_count": 74,
            "test_method_results": [{} for _ in range(74)],
        }
    if key == "hosted_conformance":
        return {
            **common,
            "case_catalog_digest": digest,
            "case_count": 349,
            "corpus_sha256": digest,
            "deterministic_assertion_method_count": 74,
            "deterministic_assertion_results_digest": digest,
            "evidence_profile": packet_builder._PROFILE_A,
            "independent_case_observation_claimed": False,
            "local_exact_sha_app_case_ids": ["CAP-RELEASE-CANARY", "UX-009-a"],
            "real_external_effects": 0,
            "semantic_coverage_mapping_count": 349,
            "semantic_coverage_mapping_digest": digest,
            "status": "PASS_LOCAL_APP_GATE_REQUIRED",
        }
    if key == "independent_review":
        return {
            **common,
            "open_finding_count": 0,
            "report_digest": digest,
            "review_scope_count": 8,
            "status": "PASS",
        }
    if key == "release_identity_preflight":
        return {
            **common,
            "feature_contains_origin_main": True,
            "origin_main_commit": candidate,
            "paper_reference_commit": candidate,
            "public_release_effects": 0,
            "status": "PASS",
            "v3_baseline_commit": candidate,
            "v4_release_exists": False,
            "v4_tag_exists": False,
        }
    if key == "static_validation":
        value = {
            **common,
            "distribution_archive": {
                "archive_sha256": digest,
                "file_manifest_digest": digest,
                "findings": [],
            },
            "evidence_privacy_findings": [],
            "gate_status": "PRE_CANARY_STATIC_ONLY",
            "large_artifact_findings": [],
            "public_effects": 0,
            "publication_ready": False,
            "sbom_sha256": digest,
            "secret_findings": [],
            "stale_production_findings": [],
            "tracked_blob_count": 100,
            "tracked_tree_digest": digest,
        }
        value["receipt_digest"] = hashlib.sha256(
            packet_builder._canonical(value)
        ).hexdigest()
        return value
    if key == "test_fault_matrix":
        return {
            **common,
            "full_test_count": 182,
            "in_memory_boundary_count": 3,
            "sqlite_boundary_count": 9,
            "status": "PASS",
            "suite_log_sha256": digest,
            "vertical_fault_instance_count": 33,
            "vertical_operation_count": 11,
        }
    raise AssertionError(key)


class PacketFixture:
    def __init__(self, tracked_count: int | None = None) -> None:
        self.repository_temp = tempfile.TemporaryDirectory()
        self.evidence_temp = tempfile.TemporaryDirectory()
        self.root = Path(self.repository_temp.name)
        self.evidence_root = Path(self.evidence_temp.name)
        run_git(self.root, "init", "--quiet")
        files = packet_builder.REQUIRED_TRACKED_FILES
        if tracked_count is not None:
            files = files[:tracked_count]
        for index, relative in enumerate(files):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"public fixture {index}: {relative}\n".encode("utf-8"))
        run_git(self.root, "add", ".")
        run_git(
            self.root,
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
        )
        self.candidate = run_git(self.root, "rev-parse", "HEAD")
        self.evidence: dict[str, Path] = {}
        for index, key in enumerate(packet_builder.REQUIRED_EVIDENCE_RECEIPTS):
            path = self.evidence_root / f"receipt-{index}.json"
            path.write_bytes(
                json.dumps(
                    receipt_for(key, self.candidate),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            self.evidence[key] = path

    def close(self) -> None:
        self.evidence_temp.cleanup()
        self.repository_temp.cleanup()


class V4AuthorPacketTests(unittest.TestCase):
    def fixture(self, tracked_count: int | None = None) -> PacketFixture:
        value = PacketFixture(tracked_count)
        self.addCleanup(value.close)
        return value

    def test_exact_tracked_closure_and_deterministic_packet(self) -> None:
        fixture = self.fixture()
        first = packet_builder.build_packet(
            fixture.root, fixture.candidate, fixture.evidence
        )
        second = packet_builder.build_packet(
            fixture.root, fixture.candidate, dict(reversed(tuple(fixture.evidence.items())))
        )
        self.assertEqual(packet_builder._canonical(first), packet_builder._canonical(second))
        self.assertEqual(first["artifact"], "loopskill-v4-publication-packet-v2")
        self.assertEqual(first["candidate_sha"], fixture.candidate)
        self.assertEqual(first["status"], "PUBLICATION_CANDIDATE_VALIDATED")
        self.assertEqual(first["public_release_effects"], 0)
        self.assertEqual(first["real_v3_loop_migrations"], 0)
        self.assertEqual(
            set(first["tracked_files"]), set(packet_builder.REQUIRED_TRACKED_FILES)
        )
        self.assertEqual(
            set(first["evidence_receipts"]),
            set(packet_builder.REQUIRED_EVIDENCE_RECEIPTS),
        )
        body = {key: value for key, value in first.items() if key != "packet_digest"}
        self.assertEqual(first["packet_digest"], packet_builder._packet_digest(body))
        for relative, digest in first["tracked_files"].items():
            blob = subprocess.run(
                ("git", "show", f"{fixture.candidate}:{relative}"),
                cwd=fixture.root,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout
            self.assertEqual(digest, hashlib.sha256(blob).hexdigest())

    def test_cli_emits_only_compact_canonical_packet(self) -> None:
        fixture = self.fixture()
        command = [
            "python3",
            str(MODULE_PATH),
            "--root",
            str(fixture.root),
            "--candidate",
            fixture.candidate,
        ]
        for key, path in fixture.evidence.items():
            command.extend(("--evidence", f"{key}={path}"))
        completed = subprocess.run(
            command,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        packet = json.loads(completed.stdout.decode("utf-8", "strict"))
        self.assertEqual(completed.stdout, packet_builder._canonical(packet))
        for path in fixture.evidence.values():
            self.assertNotIn(str(path).encode("utf-8"), completed.stdout)

    def test_arbitrary_twelve_tracked_files_cannot_pass(self) -> None:
        fixture = self.fixture(tracked_count=12)
        with self.assertRaisesRegex(
            packet_builder.AuthorPacketError,
            "AUTHOR_PACKET_REQUIRED_TRACKED_FILE_MISSING",
        ):
            packet_builder.build_packet(
                fixture.root, fixture.candidate, fixture.evidence
            )

    def test_missing_extra_and_duplicate_evidence_fail_closed(self) -> None:
        fixture = self.fixture()
        missing = dict(fixture.evidence)
        missing.pop(next(iter(missing)))
        with self.assertRaisesRegex(
            packet_builder.AuthorPacketError, "AUTHOR_PACKET_EVIDENCE_SET_INVALID"
        ):
            packet_builder.build_packet(fixture.root, fixture.candidate, missing)

        extra = dict(fixture.evidence)
        extra["unexpected"] = next(iter(extra.values()))
        with self.assertRaisesRegex(
            packet_builder.AuthorPacketError, "AUTHOR_PACKET_EVIDENCE_SET_INVALID"
        ):
            packet_builder.build_packet(fixture.root, fixture.candidate, extra)

        assignments = [f"{key}={path}" for key, path in fixture.evidence.items()]
        assignments.append(assignments[0])
        with self.assertRaisesRegex(
            packet_builder.AuthorPacketError,
            "AUTHOR_PACKET_EVIDENCE_ARGUMENT_INVALID",
        ):
            packet_builder.parse_evidence_assignments(assignments, fixture.root)

    def test_each_receipt_requires_its_typed_artifact_and_pass_state(self) -> None:
        fixture = self.fixture()
        status_fields = {
            "app_canary": ("status", "FAIL"),
            "coverage": ("status", "FAIL"),
            "distribution": ("status", "FAIL"),
            "final_conformance": ("status", "FAIL"),
            "hosted_conformance": ("status", "FAIL"),
            "independent_review": ("status", "FAIL"),
            "release_identity_preflight": ("status", "FAIL"),
            "static_validation": ("gate_status", "FAIL"),
            "test_fault_matrix": ("status", "FAIL"),
        }
        for key in packet_builder.REQUIRED_EVIDENCE_RECEIPTS:
            with self.subTest(key=key, mutation="artifact"):
                value = receipt_for(key, fixture.candidate)
                value["artifact"] = "foreign-receipt-v1"
                fixture.evidence[key].write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaisesRegex(
                    packet_builder.AuthorPacketError,
                    "AUTHOR_PACKET_EVIDENCE_TYPE_INVALID",
                ):
                    packet_builder.build_packet(
                        fixture.root, fixture.candidate, fixture.evidence
                    )
            with self.subTest(key=key, mutation="status"):
                value = receipt_for(key, fixture.candidate)
                field, invalid = status_fields[key]
                value[field] = invalid
                fixture.evidence[key].write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaisesRegex(
                    packet_builder.AuthorPacketError,
                    "AUTHOR_PACKET_EVIDENCE_SEMANTICS_INVALID",
                ):
                    packet_builder.build_packet(
                        fixture.root, fixture.candidate, fixture.evidence
                    )
            fixture.evidence[key].write_text(
                json.dumps(receipt_for(key, fixture.candidate)), encoding="utf-8"
            )

    def test_fixed_counts_zero_effects_and_digest_shapes_fail_closed(self) -> None:
        fixture = self.fixture()
        mutations = (
            ("app_canary", "provider_resend_count", 1),
            ("app_canary", "host_task_create_count", 2),
            ("app_canary", "host_terminal_wait_readback_count", 0),
            ("app_canary", "host_total_read_count", 5),
            ("coverage", "line_and_branch_percent", 79.99),
            ("coverage", "covered_branches", 1401),
            ("distribution", "config_bytes_changed", 1),
            ("distribution", "mcp_entries_added", 1),
            ("hosted_conformance", "case_count", 348),
            ("hosted_conformance", "real_external_effects", 1),
            ("final_conformance", "passed_test_methods", 73),
            ("final_conformance", "real_external_effects", 0),
            ("independent_review", "open_finding_count", 1),
            ("release_identity_preflight", "feature_contains_origin_main", False),
            ("release_identity_preflight", "v4_tag_exists", True),
            ("static_validation", "secret_findings", [{"rule": "secret"}]),
            ("test_fault_matrix", "sqlite_boundary_count", 8),
            ("test_fault_matrix", "vertical_fault_instance_count", 34),
        )
        for key, field, invalid in mutations:
            with self.subTest(key=key, field=field):
                value = receipt_for(key, fixture.candidate)
                value[field] = invalid
                fixture.evidence[key].write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaisesRegex(
                    packet_builder.AuthorPacketError,
                    "AUTHOR_PACKET_EVIDENCE_SEMANTICS_INVALID",
                ):
                    packet_builder.build_packet(
                        fixture.root, fixture.candidate, fixture.evidence
                    )
                fixture.evidence[key].write_text(
                    json.dumps(receipt_for(key, fixture.candidate)), encoding="utf-8"
                )

        invalid_digest = receipt_for("distribution", fixture.candidate)
        invalid_digest["distribution_log_sha256"] = "not-a-digest"
        fixture.evidence["distribution"].write_text(
            json.dumps(invalid_digest), encoding="utf-8"
        )
        with self.assertRaisesRegex(
            packet_builder.AuthorPacketError,
            "AUTHOR_PACKET_EVIDENCE_DIGEST_INVALID",
        ):
            packet_builder.build_packet(
                fixture.root, fixture.candidate, fixture.evidence
            )
        fixture.evidence["distribution"].write_text(
            json.dumps(receipt_for("distribution", fixture.candidate)),
            encoding="utf-8",
        )
        invalid_static = receipt_for("static_validation", fixture.candidate)
        invalid_static["receipt_digest"] = "f" * 64
        fixture.evidence["static_validation"].write_text(
            json.dumps(invalid_static), encoding="utf-8"
        )
        with self.assertRaisesRegex(
            packet_builder.AuthorPacketError,
            "AUTHOR_PACKET_EVIDENCE_DIGEST_INVALID",
        ):
            packet_builder.build_packet(
                fixture.root, fixture.candidate, fixture.evidence
            )

    def test_private_evidence_keys_paths_and_secrets_fail_closed(self) -> None:
        fixture = self.fixture()
        key = packet_builder.REQUIRED_EVIDENCE_RECEIPTS[0]
        path = fixture.evidence[key]
        invalid_values = (
            {"thread_id": "raw-task-identity"},
            {"provider_resource_ref": "provider-resource-raw"},
            {"provider_host_identity": "raw-host-identity"},
            {"artifact_path": "relative/private/receipt.json"},
            {"summary": "stored at /Users/example/private/receipt.json"},
            {"summary": "stored at (/private/var/folders/private/receipt.json)"},
            {"summary": r"stored at C:\\Users\\example\\private.json"},
            {"summary": "Bearer abcdefghijklmnopqrstuvwxyz"},
        )
        for invalid in invalid_values:
            with self.subTest(invalid=invalid):
                value = {
                    "artifact": "synthetic-private-receipt-v1",
                    "candidate_sha": fixture.candidate,
                    "status": "PASS",
                    **invalid,
                }
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaisesRegex(
                    packet_builder.AuthorPacketError,
                    "AUTHOR_PACKET_EVIDENCE_PRIVATE_(?:KEY|VALUE)",
                ):
                    packet_builder.build_packet(
                        fixture.root, fixture.candidate, fixture.evidence
                    )

    def test_receipt_candidate_and_repository_candidate_drift_fail_closed(self) -> None:
        fixture = self.fixture()
        key = packet_builder.REQUIRED_EVIDENCE_RECEIPTS[0]
        fixture.evidence[key].write_text(
            json.dumps(
                {
                    "artifact": "wrong-candidate-receipt-v1",
                    "candidate_sha": "0" * 40,
                    "status": "PASS",
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            packet_builder.AuthorPacketError,
            "AUTHOR_PACKET_EVIDENCE_CANDIDATE_MISMATCH",
        ):
            packet_builder.build_packet(
                fixture.root, fixture.candidate, fixture.evidence
            )

        marker = fixture.root / "new-head.txt"
        marker.write_text("new head\n", encoding="utf-8")
        run_git(fixture.root, "add", "new-head.txt")
        run_git(
            fixture.root,
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=LoopSkill Test",
            "-c",
            "user.email=loopskill-test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "candidate drift",
        )
        with self.assertRaisesRegex(
            packet_builder.AuthorPacketError,
            "AUTHOR_PACKET_CANDIDATE_NOT_EXACT_HEAD",
        ):
            packet_builder.build_packet(
                fixture.root, fixture.candidate, fixture.evidence
            )

    def test_dirty_worktree_and_non_object_json_fail_closed(self) -> None:
        fixture = self.fixture()
        (fixture.root / "dirty.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(
            packet_builder.AuthorPacketError, "AUTHOR_PACKET_WORKTREE_NOT_CLEAN"
        ):
            packet_builder.build_packet(
                fixture.root, fixture.candidate, fixture.evidence
            )
        (fixture.root / "dirty.txt").unlink()

        key = packet_builder.REQUIRED_EVIDENCE_RECEIPTS[0]
        fixture.evidence[key].write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(
            packet_builder.AuthorPacketError, "AUTHOR_PACKET_EVIDENCE_NOT_OBJECT"
        ):
            packet_builder.build_packet(
                fixture.root, fixture.candidate, fixture.evidence
            )


if __name__ == "__main__":
    unittest.main()
