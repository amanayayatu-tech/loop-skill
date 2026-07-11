from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "codex-loop-prompt-architect" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from loop_architect.schema import INPUT_SCHEMA  # noqa: E402
import loop_prompt_scaffold as scaffold  # noqa: E402


class PublicDraft202012SchemaTests(unittest.TestCase):
    @staticmethod
    def runtime_payload(payload: dict) -> dict:
        runtime_payload = dict(payload)
        provided = set(runtime_payload)
        for key, value in scaffold.DEFAULTS.items():
            runtime_payload.setdefault(key, value)
        runtime_payload["_provided_keys"] = sorted(provided)
        runtime_payload["_unknown_keys"] = []
        return runtime_payload

    def test_schema_is_valid_draft_2020_12(self) -> None:
        Draft202012Validator.check_schema(INPUT_SCHEMA)

    def test_all_committed_example_inputs_validate(self) -> None:
        validator = Draft202012Validator(INPUT_SCHEMA)
        paths = sorted((ROOT / "examples").glob("*-input.json"))
        self.assertEqual(len(paths), 3)
        for path in paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
            self.assertEqual(
                errors,
                [],
                f"{path.name}: " + "; ".join(error.message for error in errors),
            )

    def test_empty_dependency_arrays_are_schema_valid(self) -> None:
        payload = json.loads(
            (ROOT / "examples" / "03-adaptive-passkey-input.json").read_text(
                encoding="utf-8"
            )
        )
        payload["goals"][0]["depends_on"] = []
        payload["milestones"][0]["depends_on"] = []
        errors = list(Draft202012Validator(INPUT_SCHEMA).iter_errors(payload))
        self.assertEqual(errors, [])

    def test_empty_permissions_object_matches_runtime_when_workers_are_explicit(self) -> None:
        payload = json.loads(
            (ROOT / "examples" / "03-adaptive-passkey-input.json").read_text(
                encoding="utf-8"
            )
        )
        payload["permissions"] = {}
        schema_errors = list(Draft202012Validator(INPUT_SCHEMA).iter_errors(payload))
        self.assertEqual(schema_errors, [])
        runtime_payload = dict(payload)
        provided = set(runtime_payload)
        for key, value in scaffold.DEFAULTS.items():
            runtime_payload.setdefault(key, value)
        runtime_payload["_provided_keys"] = sorted(provided)
        runtime_payload["_unknown_keys"] = []
        self.assertEqual(scaffold.validation_errors(runtime_payload), [])

    def test_bounded_numeric_schema_matches_runtime_validation(self) -> None:
        payload = json.loads(
            (ROOT / "examples" / "03-adaptive-passkey-input.json").read_text(
                encoding="utf-8"
            )
        )
        validator = Draft202012Validator(INPUT_SCHEMA)
        payload["runtime_retry_attempts"] = 1
        self.assertTrue(list(validator.iter_errors(payload)))
        self.assertIn(
            "runtime_retry_attempts:must_be_between_10_and_100",
            scaffold.validation_errors(payload),
        )
        payload["runtime_retry_attempts"] = "10"
        self.assertTrue(list(validator.iter_errors(payload)))
        self.assertIn(
            "runtime_retry_attempts:must_be_integer",
            scaffold.validation_errors(payload),
        )
        payload["runtime_retry_attempts"] = 10
        payload["controller_goal_token_budget"] = "1000"
        self.assertTrue(list(validator.iter_errors(payload)))
        self.assertIn(
            "controller_goal_token_budget:must_be_positive_integer",
            scaffold.validation_errors(payload),
        )

    def test_standard_numeric_strings_are_compatible_but_adaptive_is_strict(self) -> None:
        validator = Draft202012Validator(INPUT_SCHEMA)
        standard = json.loads(
            (ROOT / "examples" / "01-passkey-login-input.json").read_text(
                encoding="utf-8"
            )
        )
        standard["heartbeat_interval_minutes"] = "15"
        self.assertEqual(list(validator.iter_errors(standard)), [])
        self.assertNotIn(
            "heartbeat_interval_minutes:must_be_integer",
            scaffold.validation_errors(self.runtime_payload(standard)),
        )

        adaptive = json.loads(
            (ROOT / "examples" / "03-adaptive-passkey-input.json").read_text(
                encoding="utf-8"
            )
        )
        adaptive["heartbeat_interval_minutes"] = "15"
        self.assertTrue(list(validator.iter_errors(adaptive)))
        self.assertIn(
            "heartbeat_interval_minutes:must_be_integer",
            scaffold.validation_errors(self.runtime_payload(adaptive)),
        )

    def test_public_schema_and_runtime_reject_non_ascii_safe_ids(self) -> None:
        validator = Draft202012Validator(INPUT_SCHEMA)
        standard = json.loads(
            (ROOT / "examples" / "01-passkey-login-input.json").read_text(
                encoding="utf-8"
            )
        )
        standard["goals"][0]["goal_id"] = "目标一"
        self.assertTrue(list(validator.iter_errors(standard)))
        self.assertIn(
            "goals:1:invalid_goal_id",
            scaffold.validation_errors(self.runtime_payload(standard)),
        )

        adaptive = json.loads(
            (ROOT / "examples" / "03-adaptive-passkey-input.json").read_text(
                encoding="utf-8"
            )
        )
        adaptive["milestones"][0]["milestone_id"] = "里程碑一"
        adaptive["goals"][0]["milestone_id"] = "里程碑一"
        self.assertTrue(list(validator.iter_errors(adaptive)))
        self.assertIn(
            "milestones:1:unsafe_milestone_id",
            scaffold.validation_errors(self.runtime_payload(adaptive)),
        )


if __name__ == "__main__":
    unittest.main()
