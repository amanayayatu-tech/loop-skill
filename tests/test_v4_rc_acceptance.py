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


def canary(candidate: str) -> dict:
    return {
        "artifact": "loopskill-v4-disposable-app-canary-v1",
        "candidate_sha": candidate,
        "confirmation_count": 1,
        "finalization": "ACKNOWLEDGED",
        "host_receipt_digest": "a" * 64,
        "host_task_create_count": 1,
        "host_task_readback_count": 1,
        "intake_external_effects": 0,
        "machine_owned_identity": True,
        "manual_control_identity_count": 0,
        "prepare_host_effects": 0,
        "private_data_used": False,
        "provider_resend_count": 0,
        "research_scored": False,
        "result": "ACKNOWLEDGED",
        "review": "PASS",
        "status": "PASS",
        "thread_content_retained": False,
        "unknown_preserved": True,
    }


class V4RcAcceptanceTests(unittest.TestCase):
    def test_final_cli_requires_canary_conformance_and_author_packet(self) -> None:
        stream = StringIO()
        with mock.patch.object(
            validator,
            "static_receipt",
            return_value={"artifact": "loopskill-v4-rc-static-receipt-v1"},
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
        draft = (ROOT / "docs/v4/release-notes-draft.md").read_text(encoding="utf-8")
        self.assertIn("INTAKE → PREPARE → CONFIRM → START", chinese)
        self.assertIn("INTAKE → PREPARE → CONFIRM → START", english)
        self.assertIn("No real v3 loop", migration)
        self.assertIn("does not prove improved patch success", limitations)
        self.assertIn("draft, not released", draft)
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
            ("host_task_create_count", 2),
            ("manual_control_identity_count", 1),
            ("private_data_used", True),
            ("provider_resend_count", 1),
            ("finalization", "UNKNOWN"),
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

    def test_conformance_receipt_requires_all_343_canonical_results(self) -> None:
        results = [
            {"case_id": f"CASE-{number:03d}", "status": "PASS"}
            for number in range(343)
        ]
        value = {
            "artifact": "loopskill-v4-conformance-execution-v1",
            "candidate_sha": "a" * 40,
            "canonical_case_ids": True,
            "case_count": 343,
            "case_results": results,
            "case_results_digest": hashlib.sha256(
                validator._canonical(results)
            ).hexdigest(),
            "failed": 0,
            "passed": 343,
            "real_external_effects": 1,
            "status": "PASS",
        }
        validator.validate_conformance_receipt(value, "a" * 40)
        value["case_results"][0]["status"] = "FAIL"
        with self.assertRaisesRegex(
            validator.RcValidationError, "RC_CONFORMANCE_RECEIPT_INVALID"
        ):
            validator.validate_conformance_receipt(value, "a" * 40)

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
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
            sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            dependencies = [
                {"distribution": "fixture", "license": "MIT", "version": "1"}
            ]
            with mock.patch.object(validator, "_dependency_inventory", return_value=dependencies):
                receipt = validator.static_receipt(repo, sha)
            self.assertEqual(receipt["candidate_sha"], sha)
            self.assertEqual(receipt["dependency_inventory"], dependencies)
            self.assertEqual(receipt["secret_findings"], [])
            self.assertEqual(receipt["public_effects"], 0)
            (repo / "dirty").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(
                validator.RcValidationError, "NOT_EXACT_CLEAN_HEAD"
            ):
                validator.static_receipt(repo, sha)


if __name__ == "__main__":
    unittest.main()
