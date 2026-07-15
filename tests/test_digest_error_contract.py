from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from state_runtime_support import (  # noqa: F401
    AdaptiveStateRuntime,
    Harness,
    digest,
    persisted_snapshot,
    state_runtime_module,
)


class DigestErrorContractTests(unittest.TestCase):
    def assert_digest_details(
        self,
        details: dict[str, object],
        *,
        left_field: str,
        left_digest: str,
        right_field: str,
        right_digest: str,
        byte_length: int,
    ) -> None:
        self.assertEqual(details[left_field], left_digest)
        self.assertEqual(details[right_field], right_digest)
        self.assertEqual(details["algorithm"], "sha256")
        self.assertEqual(details["encoding"], "UTF-8")
        self.assertEqual(details["byte_length"], byte_length)
        self.assertEqual(details["side_effects"], "NONE")
        self.assertNotIn("expected", details)
        self.assertNotIn("actual", details)

    @staticmethod
    def initialization_request(root: Path) -> dict[str, object]:
        template_root = root / "template"
        template_root.mkdir()
        harness = Harness(template_root)
        initialized, request = harness.initialize()
        assert initialized["ok"], initialized
        return copy.deepcopy(request)

    def test_caller_artifact_assertion_names_provided_and_computed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = self.initialization_request(root)
            target_root = root / "target"
            target_root.mkdir()
            provided = digest("incorrect caller assertion")
            request["artifacts"][0]["digest"] = provided  # type: ignore[index]
            before = persisted_snapshot(target_root)
            response = AdaptiveStateRuntime(target_root).apply(request)
            self.assertEqual(response["status"], "ARTIFACT_DIGEST_MISMATCH")
            artifact_bytes = request["artifacts"][0]["content"].encode("utf-8")  # type: ignore[index]
            self.assert_digest_details(
                response["error"]["details"],
                left_field="provided_digest",
                left_digest=provided,
                right_field="computed_digest",
                right_digest=digest(request["artifacts"][0]["content"]),  # type: ignore[index]
                byte_length=len(artifact_bytes),
            )
            self.assertEqual(before, persisted_snapshot(target_root))

    def test_projection_mismatch_names_state_and_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = self.initialization_request(root)
            target_root = root / "target"
            target_root.mkdir()
            mutation_digest = digest("wrong projection")
            request["mutation"]["projection_digest"] = mutation_digest  # type: ignore[index]
            before = persisted_snapshot(target_root)
            response = AdaptiveStateRuntime(target_root).apply(request)
            self.assertEqual(response["status"], "PROJECTION_DIGEST_MISMATCH")
            details = response["error"]["details"]
            self.assert_digest_details(
                details,
                left_field="state_digest",
                left_digest=details["state_digest"],
                right_field="mutation_digest",
                right_digest=mutation_digest,
                byte_length=details["byte_length"],
            )
            self.assertGreater(details["byte_length"], 0)
            self.assertEqual(before, persisted_snapshot(target_root))

    def test_pack_mismatch_names_canonical_and_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = self.initialization_request(root)
            target_root = root / "target"
            target_root.mkdir()
            canonical = digest("different expected Pack")
            loaded = request["artifacts"][0]["digest"]  # type: ignore[index]
            request["mutation"]["controller_pack_digest"] = canonical  # type: ignore[index]
            before = persisted_snapshot(target_root)
            response = AdaptiveStateRuntime(target_root).apply(request)
            self.assertEqual(response["status"], "CONTROLLER_PACK_IDENTITY_MISMATCH")
            pack_bytes = request["artifacts"][0]["content"].encode("utf-8")  # type: ignore[index]
            self.assert_digest_details(
                response["error"]["details"],
                left_field="canonical_pack_digest",
                left_digest=canonical,
                right_field="loaded_pack_digest",
                right_digest=loaded,
                byte_length=len(pack_bytes),
            )
            self.assertEqual(before, persisted_snapshot(target_root))

    def test_ledger_file_mismatch_names_both_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            state = harness.state()
            path = ".codex-loop/reports/digest-observation.json"
            ledger_content = json.dumps(
                {"status": "ledger"}, sort_keys=True, separators=(",", ":")
            )
            file_content = json.dumps(
                {"status": "disk"}, sort_keys=True, separators=(",", ":")
            )
            ledger_digest = digest(ledger_content)
            computed_file_digest = digest(file_content)
            state["artifact_ledger"][path] = {
                "path": path,
                "digest": ledger_digest,
                "media_type": "application/json",
                "archived_state_version": state["state_version"],
            }
            target = root / path
            target.write_text(file_content, encoding="utf-8")
            before = copy.deepcopy(state)
            with self.assertRaises(state_runtime_module.RuntimeRejection) as context:
                harness.runtime._require_existing_json_observation_artifact(
                    state,
                    path,
                    ledger_digest,
                    {"status": "ledger"},
                    state["state_version"],
                    "/observation",
                )
            self.assertEqual(context.exception.code, "ARTIFACT_DIGEST_MISMATCH")
            self.assert_digest_details(
                context.exception.details,
                left_field="ledger_digest",
                left_digest=ledger_digest,
                right_field="computed_file_digest",
                right_digest=computed_file_digest,
                byte_length=len(file_content.encode("utf-8")),
            )
            self.assertEqual(before, state)


if __name__ == "__main__":
    unittest.main()
