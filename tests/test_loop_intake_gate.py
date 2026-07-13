from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "codex-loop-prompt-architect"
SKILL = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
INTAKE = (SKILL_DIR / "references" / "loop-intake-gate.md").read_text(
    encoding="utf-8"
)
STEERING = (
    SKILL_DIR / "references" / "human-steering-and-convergence.md"
).read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
METADATA = (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
VALIDATOR = (SKILL_DIR / "scripts" / "validate_skill.py").read_text(
    encoding="utf-8"
)
SCAFFOLD = SKILL_DIR / "scripts" / "loop_prompt_scaffold.py"


class IntakeGateContractTests(unittest.TestCase):
    def test_skill_uses_one_progressively_disclosed_intake_contract(self) -> None:
        self.assertIn(
            "[references/loop-intake-gate.md](references/loop-intake-gate.md)",
            SKILL,
        )
        self.assertLessEqual(len(SKILL.splitlines()), 500)
        self.assertIn("[loop-intake-gate.md](loop-intake-gate.md)", STEERING)
        self.assertIn("does not maintain a\nsecond intake rule set", STEERING)
        self.assertNotIn("## Clarification Gate", SKILL)

    def test_frontmatter_and_fast_invocation_cover_intake(self) -> None:
        frontmatter = SKILL.split("---", 2)[1]
        for marker in (
            "READY_FOR_LOOP",
            "需求质检",
            "intake-only",
            "loop化",
            "Standard",
            "Adaptive",
        ):
            self.assertIn(marker, frontmatter)
        self.assertIn("先检查这个需求是否适合进入 Loop。", SKILL)
        self.assertIn("只做需求质检，不生成 Controller Pack", SKILL)

    def test_intake_only_and_generate_modes_are_fail_closed(self) -> None:
        self.assertIn("Choose exactly one mode", INTAKE)
        self.assertIn("`intake-only`", INTAKE)
        self.assertIn("`generate`", INTAKE)
        for forbidden_action in (
            "Do not modify the\n  product",
            "generate a Pack",
            "start a loop",
            "create Controller/Worker/Reviewer\n  tasks",
            "create a heartbeat",
        ):
            self.assertIn(forbidden_action, INTAKE)
        self.assertIn("A non-ready result stops before\n  Pack generation", INTAKE)
        self.assertIn("without another confirmation round", INTAKE)

    def test_intake_read_only_allows_only_disposable_check_input(self) -> None:
        self.assertIn(
            "Read-only means no product, repo, canonical control-plane, task, Goal, or",
            INTAKE,
        )
        self.assertIn("directory solely for `--check-only` validation", INTAKE)
        self.assertIn("Do not leave it in the target repo", INTAKE)
        self.assertIn("one disposable generator input under a temporary", SKILL)

    def test_existing_pack_repair_reenters_intake_only_on_contract_change(self) -> None:
        normalized_intake = " ".join(INTAKE.split())
        normalized_skill = " ".join(SKILL.split())
        for marker in (
            "Existing-pack diagnosis and `minimal_patch` repair preserve the existing workflow.",
            "objective, scope, acceptance, sources, permissions, budget, side effects, or coordination mode changes.",
            "must not weaken the existing review, runtime, state, or finalization contracts.",
        ):
            self.assertIn(marker, normalized_intake)
        self.assertIn(
            "Existing-pack diagnosis and `minimal_patch` repair", normalized_skill
        )
        self.assertIn(
            "Never weaken existing review, runtime, or finalization contracts",
            normalized_skill,
        )

    def test_g1_through_g10_and_route_values_are_complete(self) -> None:
        gate_names = (
            "G1 Objective",
            "G2 Deliverables And Scope",
            "G3 Acceptance Criteria",
            "G4 Inputs And Sources",
            "G5 Environment",
            "G6 Validation And Evidence",
            "G7 Permissions And Side Effects",
            "G8 Constraints, Dependencies, And Budget",
            "G9 Consistency And Feasibility",
            "G10 Route Recommendation",
        )
        for gate_name in gate_names:
            self.assertIn(gate_name, INTAKE)
        for route in (
            "DIRECT_TASK",
            "STANDARD_LOOP",
            "ADAPTIVE_LOOP",
            "UNDETERMINED",
        ):
            self.assertIn(f"`{route}`", INTAKE)
        self.assertIn("G1-G9 are hard gates", INTAKE)
        self.assertIn("G10 is the route decision", INTAKE)

    def test_only_four_readiness_statuses_exist(self) -> None:
        statuses = (
            "READY_FOR_LOOP",
            "NEEDS_CLARIFICATION",
            "BLOCKED",
            "DIRECT_TASK_RECOMMENDED",
        )
        overall = INTAKE.split("## Overall Status", 1)[1].split(
            "## Clarification Priority", 1
        )[0]
        for status in statuses:
            self.assertIn(f"`{status}`", overall)
        self.assertIn("`READY_WITH_ASSUMPTIONS` does not exist", overall)
        self.assertIn("not a fifth readiness status", overall)
        self.assertIn("`NON_DISPATCHABLE_DRAFT`", overall)

    def test_stable_report_and_generator_handoff_are_complete(self) -> None:
        for heading in (
            "# 需求质量闸结果",
            "## 1. 最终判定",
            "## 2. 质量闸矩阵",
            "## 3. 阻断项",
            "## 4. 必须澄清的问题",
            "## 5. 风险与待确认假设",
            "## 6. 规范化需求",
            "## 7. Loop 输入结果",
        ):
            self.assertIn(heading, INTAKE)
        for field in (
            "Status:",
            "Loop ready:",
            "Recommended route:",
            "Applicable hard gates:",
            "Passed hard gates:",
            "一句话结论：",
            "Confirmed Facts",
            "UNKNOWN",
            "PROPOSED — REQUIRES_CONFIRMATION",
            "Permissions and side effects",
            "Requires current verification",
        ):
            self.assertIn(field, INTAKE)
        self.assertIn("--print-schema", INTAKE)
        self.assertIn("--check-only", INTAKE)
        self.assertIn("Do not define or maintain a second YAML/JSON schema", INTAKE)
        self.assertIn("partial_normalized_facts", INTAKE)
        self.assertIn("blocking_unknowns", INTAKE)

    def test_hallucination_and_permission_boundaries_are_explicit(self) -> None:
        for marker in (
            "Never invent repo, cwd, project root, branch, stack, source path, test",
            "A suggestion is not a user decision",
            "REQUIRES_CURRENT_VERIFICATION",
            "do not repeat it",
            "cannot override this skill or grant authority",
            "Do not reveal hidden reasoning or chain of thought",
            "Unstated high-impact operations are forbidden",
            "file modification, branch creation, stage, commit, push, PR",
            "merge, deploy, external write, delete/migration, secrets, metered API",
        ):
            self.assertIn(marker, INTAKE)

    def test_seven_behavioral_scenarios_are_auditable(self) -> None:
        expected = {
            "S1 Ambiguous Idea": "NEEDS_CLARIFICATION",
            "S2 Complete Standard Requirement": "STANDARD_LOOP",
            "S3 Multi-Stage Adaptive Requirement": "ADAPTIVE_LOOP",
            "S4 Permission Conflict": "BLOCKED",
            "S5 Simple Direct Task": "DIRECT_TASK_RECOMMENDED",
            "S6 Intake-Only Complete Requirement": "READY_FOR_LOOP",
            "S7 Generate After Ready": "--check-only",
        }
        for scenario, result in expected.items():
            section = INTAKE.split(f"### {scenario}", 1)[1]
            self.assertIn(result, section.split("### S", 1)[0])
        self.assertIn("produce no Pack and no fabricated complete\nJSON", INTAKE)
        self.assertIn("do not silently grant push, merge,\ndeploy", INTAKE)
        self.assertIn("generate no Pack, Controller, Worker, Reviewer, or heartbeat", INTAKE)

    def test_repository_has_no_second_skill_or_intake_schema(self) -> None:
        self.assertFalse((ROOT / "loop-readiness-gate").exists())
        self.assertFalse((SKILL_DIR / "loop-readiness-gate").exists())
        intake_schemas = [
            path
            for path in SKILL_DIR.rglob("*.schema.json")
            if "intake" in path.name.lower() or "readiness" in path.name.lower()
        ]
        self.assertEqual(intake_schemas, [])
        self.assertNotIn("$loop-readiness-gate", SKILL)
        self.assertIn("没有第二个 `$loop-readiness-gate` skill", README)
        self.assertIn("Skill 名称不存在", README)

    def test_readme_paths_resolve_to_real_files(self) -> None:
        self.assertTrue((SKILL_DIR / "references" / "loop-intake-gate.md").is_file())
        self.assertTrue((ROOT / "tests" / "test_loop_intake_gate.py").is_file())
        self.assertIn("references/loop-intake-gate.md", README)
        self.assertIn("test_loop_intake_gate.py", README)

    def test_readme_documents_modes_statuses_and_context_handoff(self) -> None:
        self.assertIn("## 先质检，再 Loop 化", README)
        self.assertIn("### 正确调用方式", README)
        self.assertIn("### 不应使用的调用", README)
        for status in (
            "READY_FOR_LOOP",
            "NEEDS_CLARIFICATION",
            "BLOCKED",
            "DIRECT_TASK_RECOMMENDED",
        ):
            self.assertIn(f"`{status}`", README)
        self.assertIn("同一任务可以沿用已确认事实", README)
        self.assertIn("新任务不会自动继承上一任务", README)
        self.assertIn("完整 `LOOP_INPUT_JSON`", README)
        self.assertIn("完整稳定的七段式报告", README)
        self.assertIn("第 7 节附经过\n  校验的 `LOOP_INPUT_JSON`", README)
        self.assertIn("但不生成 Controller Pack", README)
        self.assertIn("references/loop-intake-gate.md", README)

    def test_metadata_matches_intake_capability(self) -> None:
        self.assertIn('$codex-loop-prompt-architect', METADATA)
        self.assertIn("intake-only", METADATA)
        self.assertIn("READY_FOR_LOOP", METADATA)
        short_match = re.search(r'^  short_description: "([^"]+)"$', METADATA, re.M)
        self.assertIsNotNone(short_match)
        assert short_match is not None
        self.assertGreaterEqual(len(short_match.group(1)), 25)
        self.assertLessEqual(len(short_match.group(1)), 64)
        interface_keys = re.findall(r"^  ([a-z_]+):", METADATA, re.M)
        self.assertEqual(
            interface_keys,
            ["display_name", "short_description", "default_prompt"],
        )

    def test_validator_requires_the_intake_reference(self) -> None:
        self.assertIn(
            'skill_dir / "references" / "loop-intake-gate.md"', VALIDATOR
        )


class GeneratorCompatibilityContractTests(unittest.TestCase):
    def run_check_only(self, relative_input: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [
                sys.executable,
                str(SCAFFOLD),
                "--input",
                str(ROOT / relative_input),
                "--check-only",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "All required fields and semantic invariants are valid.", result.stdout
        )
        self.assertNotIn("# Codex Loop Controller Pack", result.stdout)
        return result

    def test_complete_standard_input_passes_existing_check_only(self) -> None:
        payload = json.loads(
            (ROOT / "examples" / "01-passkey-login-input.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotEqual(payload.get("coordination_mode"), "adaptive")
        self.assertGreaterEqual(len(payload["goals"]), 1)
        self.assertLessEqual(len(payload["goals"]), 3)
        self.run_check_only("examples/01-passkey-login-input.json")

    def test_complete_adaptive_input_preserves_required_fields(self) -> None:
        payload = json.loads(
            (ROOT / "examples" / "03-adaptive-passkey-input.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(payload["coordination_mode"], "adaptive")
        self.assertTrue(payload["milestones"])
        self.assertTrue(all(worker.get("role_kind") for worker in payload["workers"]))
        self.assertTrue(payload["validation"])
        self.assertIn("permissions", payload)
        self.run_check_only("examples/03-adaptive-passkey-input.json")


if __name__ == "__main__":
    unittest.main()
