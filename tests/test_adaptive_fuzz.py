from __future__ import annotations

import copy
import json
import os
import random
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "codex-loop-prompt-architect" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import loop_prompt_scaffold as scaffold


class AdaptiveMalformedInputFuzzTests(unittest.TestCase):
    def test_malformed_nested_values_never_crash_validation_or_render(self) -> None:
        source = json.loads((ROOT / "examples" / "03-adaptive-passkey-input.json").read_text())
        randomizer = random.Random(20260710)
        mutations = [None, True, False, 0, -1, "", [], {}, ["x"], {"x": 1}, "TODO", "../escape"]
        paths = [
            ("workers",),
            ("goals",),
            ("milestones",),
            ("objective",),
            ("coordination_mode",),
            ("max_child_threads",),
            ("max_read_only_subagents",),
            ("max_read_only_subagent_runs",),
            ("subagent_retry_limit",),
            ("subagent_max_depth",),
            ("local_verification_policy",),
            ("dashboard_threshold_hours",),
            ("validation",),
            ("source_artifacts",),
            ("workers", 0, "role_kind"),
            ("workers", 0, "permission"),
            ("goals", 0, "milestone_id"),
            ("milestones", 0, "status"),
            ("milestones", 0, "depends_on"),
            ("milestones", 0, "required_evidence"),
        ]
        accepted = 0
        case_count = int(os.environ.get("ADAPTIVE_FUZZ_CASES", "1000"))
        for _ in range(case_count):
            payload = copy.deepcopy(source)
            for _ in range(randomizer.randint(1, 5)):
                path = randomizer.choice(paths)
                value = copy.deepcopy(randomizer.choice(mutations))
                cursor = payload
                try:
                    for part in path[:-1]:
                        cursor = cursor[part]
                    cursor[path[-1]] = value
                except (KeyError, IndexError, TypeError):
                    pass
            data = self._prepare(payload)
            errors = scaffold.validation_errors(data)
            pack = scaffold.render_controller_pack(data, "compact")
            scaffold.render_user_guide(data, "/tmp/controller-pack.md")
            if not errors:
                accepted += 1
                self.assertNotIn("NON_DISPATCHABLE_DRAFT", pack)
            else:
                self.assertIn("NON_DISPATCHABLE_DRAFT", pack)
        self.assertGreater(accepted, 0)

    @staticmethod
    def _prepare(payload: dict) -> dict:
        data = copy.deepcopy(payload)
        provided = set(data).intersection(scaffold.REQUIRED + scaffold.OPTIONAL)
        unknown = set(data).difference(scaffold.REQUIRED + scaffold.OPTIONAL)
        for key, value in scaffold.DEFAULTS.items():
            data.setdefault(key, copy.deepcopy(value))
        data.setdefault("cadence", scaffold.heartbeat_cadence(data))
        data["_provided_keys"] = sorted(provided)
        data["_unknown_keys"] = sorted(unknown)
        return data


if __name__ == "__main__":
    unittest.main()
