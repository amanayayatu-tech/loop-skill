from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "loopskill5"


class LoopSkill5SurfaceTest(unittest.TestCase):
    def test_natural_language_autonomy_surface_is_complete_and_isolated(self) -> None:
        inventory = sorted(
            path.relative_to(SKILL_ROOT).as_posix()
            for path in SKILL_ROOT.rglob("*")
            if path.is_file()
        )
        self.assertEqual(inventory, ["SKILL.md", "agents/openai.yaml"])

        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        metadata = (SKILL_ROOT / "agents/openai.yaml").read_text(encoding="utf-8")

        frontmatter = skill.split("---", 2)[1].strip().splitlines()
        self.assertEqual(
            [line.split(":", 1)[0] for line in frontmatter],
            ["name", "description"],
        )
        self.assertEqual(frontmatter[0], "name: loopskill5")
        self.assertIn("natural language or a PRD", frontmatter[1])

        self.assertEqual(
            metadata,
            'interface:\n'
            '  display_name: "LoopSkill 5"\n'
            '  short_description: "主动调查并准备长程任务，一次确认后自主推进到真实结果"\n'
            '  default_prompt: "Use $loopskill5：先主动调查并给出最远安全 Launch Contract，只集中询问真正阻断项，等待我一次确认 START 后再自主执行。"\n',
        )
        self.assertNotIn("$loopskill4", metadata)

        contract_items = re.findall(r"^\d+\. \*\*(.+?)\*\* —", skill, re.MULTILINE)
        self.assertEqual(
            contract_items,
            [
                "你的最终意图",
                "本次承诺结果",
                "为何这是最远安全结果",
                "推荐路线",
                "已验证条件",
                "授权范围与外部效果",
                "验收与证据",
                "自动恢复",
                "会找你的业务 Gate",
                "紧急停止",
                "无人值守预期",
                "START",
            ],
        )

        required_surface = (
            "Never require the user to write JSON, IDs, digests",
            "Investigate proactively",
            "Recommend the farthest safe result",
            "Ask once for true blockers",
            "Start only after the user sends a new, explicit confirmation",
            "Treat START-after technical intervention as a product failure",
            "Use the current Codex task/thread as the business execution identity",
            "Host-native heartbeat scheduling and same-thread turn reentry",
            "at most one owner-only, human-readable effect fact",
            "Host idle/active is not a business state",
            "Stop only at a true business Gate",
            "contract-authorized local permission repair",
            "New permissions, external authorization, or any expansion of authority",
            "distinguish Codex Host-required control-plane/model traffic from task business-tool network effects",
            "Use emergency stop as the safety brake",
            "Report the business result first",
            "loopskill5-private",
            "never replace or modify the `loopskill4` Skill",
            "never invoke, copy, or wrap the fixed GJ-1 DEVELOPMENT harness",
            "Do not add or depend on a LoopSkill-owned Controller",
        )
        normalized_surface = " ".join(skill.split())
        for phrase in required_surface:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized_surface)


if __name__ == "__main__":
    unittest.main()
