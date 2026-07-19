from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO = Path(__file__).resolve().parents[3]
HELPER_PATH = REPO / ".github" / "ci" / "compatibility.py"
MANIFEST_PATH = REPO / ".github" / "ci" / "test-shards.json"
SPEC = importlib.util.spec_from_file_location("compatibility_ci", HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
compatibility = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compatibility
SPEC.loader.exec_module(compatibility)
WHITESPACE_SPEC = importlib.util.spec_from_file_location(
    "compatibility_ci_whitespace", REPO / "scripts" / "check_whitespace_range.py"
)
assert WHITESPACE_SPEC is not None and WHITESPACE_SPEC.loader is not None
whitespace = importlib.util.module_from_spec(WHITESPACE_SPEC)
sys.modules[WHITESPACE_SPEC.name] = whitespace
WHITESPACE_SPEC.loader.exec_module(whitespace)


def entry(path: str, status: str = "M") -> dict[str, object]:
    return {"status": status, "paths": [path]}


def needs_for(plan: dict[str, object]) -> dict[str, object]:
    expected = {
        "plan": True,
        "quick": True,
        "full": plan["run_full"],
        "coverage": plan["run_full"],
        "fuzz-generator": plan["run_generator_fuzz"],
        "fuzz-state": plan["run_state_fuzz"],
        "install-linux": plan["run_install"],
        "macos-install": plan["run_install"],
        "tag-identity": plan["run_tag_identity"],
    }
    result: dict[str, object] = {}
    for job, should_run in expected.items():
        outputs: dict[str, str] = {}
        if job == "coverage" and should_run:
            outputs = {"total_tests": "632", "coverage_percent": "80.02"}
        if job == "fuzz-generator" and should_run:
            outputs = {"case_count": "5000", "seed": "20260710"}
        if job == "fuzz-state" and should_run:
            outputs = {"case_count": "5000", "seed": "20260711"}
        result[job] = {"result": "success" if should_run else "skipped", "outputs": outputs}
    return result


class ClassificationTests(unittest.TestCase):
    def test_light_allowlist(self) -> None:
        plan = compatibility.classify_entries([entry("README.md"), entry("docs/readme-assets/demo.png", "A")])
        self.assertEqual(plan["tier"], "light")
        self.assertFalse(plan["run_full"])

    def test_spec_is_standard_without_fuzz(self) -> None:
        plan = compatibility.classify_entries([entry("SPEC.md")])
        self.assertEqual(plan["tier"], "standard")
        self.assertTrue(plan["run_full"])
        self.assertFalse(plan["run_state_fuzz"])
        self.assertFalse(plan["run_generator_fuzz"])

    def test_state_risk(self) -> None:
        plan = compatibility.classify_entries([entry("tests/test_state_runtime_io.py")])
        self.assertTrue(plan["run_state_fuzz"])
        self.assertFalse(plan["run_generator_fuzz"])

    def test_generator_risk(self) -> None:
        plan = compatibility.classify_entries([entry("tests/test_loop_prompt_scaffold.py")])
        self.assertFalse(plan["run_state_fuzz"])
        self.assertTrue(plan["run_generator_fuzz"])

    def test_both_risks_can_run(self) -> None:
        plan = compatibility.classify_entries(
            [entry("tests/test_state_runtime_io.py"), entry("tests/test_loop_prompt_scaffold.py")]
        )
        self.assertTrue(plan["run_state_fuzz"])
        self.assertTrue(plan["run_generator_fuzz"])

    def test_delete_and_rename_fail_closed(self) -> None:
        deleted = compatibility.classify_entries([entry("README.md", "D")])
        renamed = compatibility.classify_entries(
            [{"status": "R100", "paths": ["README.md", "README-new.md"]}]
        )
        self.assertEqual(deleted["tier"], "release")
        self.assertEqual(renamed["tier"], "release")

    def test_unknown_and_ci_paths_fail_closed(self) -> None:
        unknown = compatibility.classify_entries([entry("mystery.bin")])
        ci = compatibility.classify_entries([entry(".github/ci/compatibility.py")])
        self.assertEqual(unknown["tier"], "release")
        self.assertEqual(ci["tier"], "release")

    def test_invalid_sha_and_missing_base_fail_closed(self) -> None:
        invalid = compatibility.build_plan(
            REPO,
            "pull_request",
            {"pull_request": {"base": {"sha": "bad"}, "head": {"sha": "bad"}}},
            "bad",
            "release",
        )
        missing = compatibility.build_plan(
            REPO,
            "pull_request",
            {
                "pull_request": {
                    "base": {"sha": "1" * 40},
                    "head": {"sha": "2" * 40},
                }
            },
            "3" * 40,
            "release",
        )
        self.assertEqual(invalid["tier"], "release")
        self.assertIn("classification-error", invalid["reasons"][0])
        self.assertEqual(missing["tier"], "release")
        self.assertIn("base is unavailable", missing["reasons"][0])

    def test_manual_profiles_and_non_pr_events(self) -> None:
        quick = compatibility.build_plan(REPO, "workflow_dispatch", {"inputs": {"profile": "quick"}}, "a" * 40, "")
        full = compatibility.build_plan(REPO, "workflow_dispatch", {"inputs": {"profile": "full"}}, "a" * 40, "")
        manual_release = compatibility.build_plan(
            REPO, "workflow_dispatch", {"inputs": {"profile": "release"}}, "a" * 40, ""
        )
        scheduled_release = compatibility.build_plan(REPO, "schedule", {}, "a" * 40, "")
        tag = compatibility.build_plan(REPO, "push", {"ref": "refs/tags/v1.2.3"}, "a" * 40, "")
        main = compatibility.build_plan(REPO, "push", {"ref": "refs/heads/main"}, "a" * 40, "")
        self.assertEqual(quick["tier"], "quick")
        self.assertEqual(full["tier"], "standard")
        self.assertEqual(manual_release["tier"], "release")
        self.assertTrue(manual_release["run_state_fuzz"])
        self.assertTrue(manual_release["run_generator_fuzz"])
        self.assertEqual(scheduled_release["tier"], "release")
        self.assertTrue(scheduled_release["run_state_fuzz"])
        self.assertTrue(scheduled_release["run_generator_fuzz"])
        self.assertTrue(tag["run_tag_identity"])
        self.assertTrue(tag["run_state_fuzz"])
        self.assertTrue(tag["run_generator_fuzz"])
        self.assertEqual(main["tier"], "standard")
        self.assertTrue(main["run_full"])
        self.assertTrue(main["run_install"])
        self.assertFalse(main["run_state_fuzz"])
        self.assertFalse(main["run_generator_fuzz"])
        invalid = compatibility.build_plan(REPO, "workflow_dispatch", {"inputs": {"profile": "quick"}}, "bad", "")
        self.assertEqual(invalid["tier"], "release")

    def test_tag_reuses_only_exact_successful_main_proof(self) -> None:
        sha = "a" * 40
        proof = {"verified": True, "head_sha": sha, "run_id": 123}
        tag = compatibility.build_plan(
            REPO, "push", {"ref": "refs/tags/v1.2.3"}, sha, "", proof
        )
        self.assertFalse(tag["run_quick"])
        self.assertFalse(tag["run_full"])
        self.assertFalse(tag["run_install"])
        self.assertTrue(tag["run_state_fuzz"])
        self.assertTrue(tag["run_generator_fuzz"])
        wrong_sha = compatibility.build_plan(
            REPO,
            "push",
            {"ref": "refs/tags/v1.2.3"},
            sha,
            "",
            {**proof, "head_sha": "b" * 40},
        )
        self.assertTrue(wrong_sha["run_quick"])
        self.assertTrue(wrong_sha["run_full"])

    def test_main_proof_requires_exact_successful_main_workflow_identity(self) -> None:
        sha = "a" * 40
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(
            {
                "workflow_runs": [
                    {
                        "id": 123,
                        "head_sha": sha,
                        "head_branch": "main",
                        "event": "push",
                        "status": "completed",
                        "conclusion": "success",
                        "path": ".github/workflows/compatibility.yml",
                        "html_url": "https://github.example/runs/123",
                    }
                ]
            }
        ).encode("utf-8")
        with mock.patch.object(compatibility.urllib.request, "urlopen", return_value=response):
            proof = compatibility.verify_successful_main_run(
                repository="owner/repo",
                workflow=".github/workflows/compatibility.yml",
                tested_sha=sha,
                token="token",
            )
        self.assertTrue(proof["verified"])
        self.assertEqual(proof["run_id"], 123)

        response.read.return_value = json.dumps(
            {"workflow_runs": [{**json.loads(response.read.return_value)["workflow_runs"][0], "path": "other.yml"}]}
        ).encode("utf-8")
        with mock.patch.object(compatibility.urllib.request, "urlopen", return_value=response):
            rejected = compatibility.verify_successful_main_run(
                repository="owner/repo",
                workflow=".github/workflows/compatibility.yml",
                tested_sha=sha,
                token="token",
            )
        self.assertFalse(rejected["verified"])


class ManifestAndArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = compatibility.build_inventory(REPO, MANIFEST_PATH)
        cls.sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, check=True, text=True, capture_output=True
        ).stdout.strip()

    def test_canonical_inventory(self) -> None:
        self.assertEqual(self.inventory["expected_total_tests"], 632)
        self.assertEqual(
            {key: value["test_count"] for key, value in self.inventory["shards"].items()},
            {"1": 180, "2": 168, "3": 142, "4": 142},
        )
        self.assertEqual(set(self.inventory["dedicated_only"]), {
            "tests.test_adaptive_state_runtime",
            "tests.test_incident_p0_negative",
        })
        with tempfile.TemporaryDirectory() as temporary:
            inventory_path = Path(temporary) / "inventory.json"
            inventory_path.write_text(json.dumps(self.inventory), encoding="utf-8")
            self.assertEqual(compatibility._inventory_total(inventory_path), 632)
            malformed = {**self.inventory, "expected_total_tests": 633}
            inventory_path.write_text(json.dumps(malformed), encoding="utf-8")
            with self.assertRaises(compatibility.CompatibilityError):
                compatibility._inventory_total(inventory_path)

    def test_artifact_verifier_accepts_exact_unique_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact_dir = Path(temporary)
            for shard, expected in self.inventory["shards"].items():
                payload = {
                    "schema_version": 1,
                    "shard": shard,
                    "tested_sha": self.sha,
                    "successful": True,
                    "modules": expected["modules"],
                    "test_ids": expected["test_ids"],
                    "expected_tests": expected["test_count"],
                    "tests_run": expected["test_count"],
                    "duration_seconds": 1.0,
                }
                (artifact_dir / f".ci-shard-{shard}.json").write_text(json.dumps(payload), encoding="utf-8")
                (artifact_dir / f".coverage.shard-{shard}.host.1").touch()
            summary = compatibility.verify_shard_artifacts(REPO, MANIFEST_PATH, artifact_dir, self.sha)
        self.assertEqual(summary["total_tests"], 632)

    def test_artifact_verifier_rejects_wrong_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(compatibility.CompatibilityError):
                compatibility.verify_shard_artifacts(REPO, MANIFEST_PATH, Path(temporary), self.sha)

    def test_runner_writes_success_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / ".github" / "ci").mkdir(parents=True)
            (repo / "tests").mkdir()
            (repo / "tests" / "__init__.py").write_text("", encoding="utf-8")
            for index in range(1, 5):
                (repo / "tests" / f"test_s{index}.py").write_text(
                    "import unittest\n\nclass Sample(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                    encoding="utf-8",
                )
            (repo / ".github" / "ci" / "compatibility.py").write_text(
                HELPER_PATH.read_text(encoding="utf-8"), encoding="utf-8"
            )
            manifest = {
                "schema_version": 1,
                "expected_total_tests": 4,
                "expected_shard_counts": {str(index): 1 for index in range(1, 5)},
                "shards": {str(index): [f"tests.test_s{index}"] for index in range(1, 5)},
                "dedicated_only": {"tests.test_dedicated": "quick"},
            }
            (repo / "tests" / "test_dedicated.py").write_text(
                "import unittest\n\nclass Dedicated(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            manifest_path = repo / ".github" / "ci" / "test-shards.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(
                ["git", "-c", "user.name=CI", "-c", "user.email=ci@example.invalid", "commit", "-qm", "fixture"],
                cwd=repo,
                check=True,
            )
            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
            ).stdout.strip()
            output = repo / ".ci-shard-1.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(repo / ".github" / "ci" / "compatibility.py"),
                    "run-shard",
                    "--repo",
                    str(repo),
                    "--manifest",
                    str(manifest_path),
                    "--shard",
                    "1",
                    "--tested-sha",
                    sha,
                    "--output",
                    str(output),
                ],
                cwd=repo,
                text=True,
                capture_output=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            execution = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(execution["successful"])
            self.assertEqual(execution["tests_run"], 1)

    def test_canonical_coverage_excludes_dedicated_only_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / ".github" / "ci").mkdir(parents=True)
            (repo / "tests").mkdir()
            (repo / "tests" / "__init__.py").write_text("", encoding="utf-8")
            for index in range(1, 5):
                (repo / "tests" / f"test_s{index}.py").write_text(
                    "import unittest\n\nclass Sample(unittest.TestCase):\n"
                    "    def test_ok(self):\n        self.assertTrue(True)\n",
                    encoding="utf-8",
                )
            (repo / "tests" / "test_dedicated.py").write_text(
                "import unittest\n\nclass Dedicated(unittest.TestCase):\n"
                "    def test_must_not_run(self):\n        raise RuntimeError('dedicated test ran')\n",
                encoding="utf-8",
            )
            (repo / ".github" / "ci" / "compatibility.py").write_text(
                HELPER_PATH.read_text(encoding="utf-8"), encoding="utf-8"
            )
            manifest = {
                "schema_version": 1,
                "expected_total_tests": 4,
                "expected_shard_counts": {str(index): 1 for index in range(1, 5)},
                "shards": {str(index): [f"tests.test_s{index}"] for index in range(1, 5)},
                "dedicated_only": {"tests.test_dedicated": "state-fuzz"},
            }
            manifest_path = repo / ".github" / "ci" / "test-shards.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(
                ["git", "-c", "user.name=CI", "-c", "user.email=ci@example.invalid", "commit", "-qm", "fixture"],
                cwd=repo,
                check=True,
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(repo / ".github" / "ci" / "compatibility.py"),
                    "canonical-coverage",
                    "--repo",
                    str(repo),
                    "--manifest",
                    str(manifest_path),
                    "--artifact-dir",
                    str(repo / ".ci-canonical-coverage"),
                    "--minimum",
                    "0",
                ],
                cwd=repo,
                text=True,
                capture_output=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            evidence = json.loads(
                (repo / ".ci-canonical-coverage" / "coverage-evidence-v1.json").read_text()
            )
            self.assertEqual(evidence["total_tests"], 4)

    def test_canonical_coverage_all_clears_only_generated_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact_dir = Path(temporary)
            stale = (
                ".coverage",
                ".coverage.shard-1.host.old",
                ".ci-shard-1.json",
                "coverage.json",
                "coverage.xml",
                "coverage-evidence-v1.json",
            )
            for name in stale:
                (artifact_dir / name).write_text("stale", encoding="utf-8")
            sentinel = artifact_dir / "keep-me.txt"
            sentinel.write_text("keep", encoding="utf-8")
            with mock.patch.object(compatibility, "_validate_sha", side_effect=RuntimeError("stop after cleanup")):
                with self.assertRaisesRegex(RuntimeError, "stop after cleanup"):
                    compatibility.canonical_coverage(
                        REPO,
                        MANIFEST_PATH,
                        artifact_dir,
                        self.sha,
                        mode="all",
                    )
            self.assertTrue(sentinel.is_file())
            self.assertTrue(all(not (artifact_dir / name).exists() for name in stale))


class WhitespaceScheduleTests(unittest.TestCase):
    def test_schedule_records_an_explicit_empty_range(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            (repo / "scheduled.txt").write_text("scheduled\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(
                ["git", "-c", "user.name=CI", "-c", "user.email=ci@example.invalid", "commit", "-qm", "scheduled"],
                cwd=repo,
                check=True,
            )
            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
            ).stdout.strip()
            commits, label = whitespace.select_commits(repo, "schedule", {}, sha)
            self.assertEqual(commits, [])
            self.assertEqual(label, f"schedule:{sha}:no-new-commits")


class CoverageAndGateTests(unittest.TestCase):
    def test_coverage_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            coverage_json = Path(temporary) / "coverage.json"
            coverage_json.write_text(json.dumps({"totals": {"percent_covered": 80.43}}), encoding="utf-8")
            self.assertEqual(compatibility.coverage_summary(coverage_json, baseline=80.43)["coverage_percent"], "80.43")
            coverage_json.write_text(json.dumps({"totals": {"percent_covered": 80.45}}), encoding="utf-8")
            with self.assertRaises(compatibility.CompatibilityError):
                compatibility.coverage_summary(coverage_json, baseline=80.43)
            coverage_json.write_text(json.dumps({"totals": {"percent_covered": 79.99}}), encoding="utf-8")
            with self.assertRaises(compatibility.CompatibilityError):
                compatibility.coverage_summary(coverage_json)

    def test_gate_accepts_expected_success_and_skips(self) -> None:
        plan = compatibility.classify_entries(
            [entry("README.md")], base_sha="a" * 40, head_sha="b" * 40, merge_sha="c" * 40
        )
        plan["expected_total_tests"] = 632
        errors, report = compatibility.gate_report(plan, needs_for(plan))
        self.assertEqual(errors, [])
        self.assertIn("PASS", report)

    def test_gate_accepts_dual_fuzz_release(self) -> None:
        plan = compatibility.classify_entries(
            [entry(".github/workflows/compatibility.yml")],
            base_sha="a" * 40,
            head_sha="b" * 40,
            merge_sha="c" * 40,
        )
        plan["expected_total_tests"] = 632
        errors, _ = compatibility.gate_report(plan, needs_for(plan))
        self.assertEqual(errors, [])

    def test_gate_rejects_failure_cancelled_and_unexpected_skip(self) -> None:
        plan = compatibility.classify_entries(
            [entry(".github/workflows/compatibility.yml")],
            base_sha="a" * 40,
            head_sha="b" * 40,
            merge_sha="c" * 40,
        )
        plan["expected_total_tests"] = 632
        for job, result in (("quick", "failure"), ("full", "cancelled"), ("coverage", "skipped")):
            with self.subTest(job=job, result=result):
                needs = needs_for(plan)
                needs[job]["result"] = result
                errors, _ = compatibility.gate_report(plan, needs)
                self.assertTrue(any(job in error for error in errors))

    def test_gate_rejects_unexpected_run(self) -> None:
        plan = compatibility.classify_entries(
            [entry("README.md")], base_sha="a" * 40, head_sha="b" * 40, merge_sha="c" * 40
        )
        plan["expected_total_tests"] = 632
        needs = needs_for(plan)
        needs["fuzz-state"] = {
            "result": "success",
            "outputs": {"case_count": "5000", "seed": "20260711"},
        }
        errors, _ = compatibility.gate_report(plan, needs)
        self.assertTrue(any("fuzz-state" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
