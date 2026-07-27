from __future__ import annotations

import os
import hashlib
import json
import unittest
from io import StringIO


class V4AtomicConformanceTests(unittest.TestCase):
    """Execute one catalog parameter through its frozen concrete test binding."""

    def test_case(self) -> None:
        case_id = os.environ.get("LOOPSKILL4_CONFORMANCE_CASE_ID", "")
        target = os.environ.get("LOOPSKILL4_CONFORMANCE_TARGET", "")
        family = os.environ.get("LOOPSKILL4_CONFORMANCE_FAMILY", "")
        contract_raw = os.environ.get("LOOPSKILL4_CONFORMANCE_CONTRACT", "")
        contract_digest = os.environ.get(
            "LOOPSKILL4_CONFORMANCE_CONTRACT_DIGEST", ""
        )
        if not (case_id or target or family):
            self.assertNotIn("LOOPSKILL4_CONFORMANCE_CASE_ID", os.environ)
            return
        self.assertTrue(case_id and target and family and contract_raw and contract_digest)
        self.assertEqual(
            hashlib.sha256(contract_raw.encode("utf-8")).hexdigest(),
            contract_digest,
        )
        contract = json.loads(contract_raw)
        self.assertEqual(
            set(contract),
            {
                "capability_profile",
                "case_id",
                "expected_acceptance",
                "expected_effect_state",
                "expected_ordered_events",
                "expected_side_effect_counts",
                "family",
                "family_spec_digest",
                "fixture_selector",
                "parameter",
                "precondition",
                "replay_expectation",
                "schema_version",
                "stimulus",
                "target_test_id",
            },
        )
        self.assertEqual(contract["schema_version"], "loopskill-v4-executable-case-contract-v1")
        self.assertEqual(contract["case_id"], case_id)
        self.assertEqual(contract["family"], family)
        self.assertEqual(contract["target_test_id"], target)
        self.assertEqual(contract["parameter"], case_id[len(family) + 1 :])
        self.assertEqual(contract["fixture_selector"], contract["parameter"])
        self.assertEqual(contract["stimulus"], f"{family}:{contract['parameter']}")
        self.assertTrue(contract["precondition"])
        self.assertRegex(contract["family_spec_digest"], r"^[0-9a-f]{64}$")
        self.assertIn(contract["expected_acceptance"], {"ACCEPT", "REJECT"})
        self.assertIn(
            contract["expected_effect_state"],
            {"NOT_APPLICABLE", "OBSERVED", "UNKNOWN", "UNVERIFIABLE"},
        )
        self.assertIn(
            contract["replay_expectation"],
            {
                "NOT_APPLICABLE",
                "EXACT_REPLAY_NO_SECOND_COMMIT",
                "IDEMPOTENCY_CONFLICT_ON_CHANGED_REQUEST",
            },
        )
        events = contract["expected_ordered_events"]
        self.assertTrue(events is None or all(isinstance(item, str) for item in events))
        counts = contract["expected_side_effect_counts"]
        self.assertEqual(
            set(counts),
            {"canonical_commits", "local_filesystem_writes", "provider_invocations"},
        )
        self.assertTrue(
            all(value is None or isinstance(value, int) for value in counts.values())
        )
        self.assertTrue(case_id.startswith(family + "-"))
        self.assertNotIn("test_v4_atomic_conformance", target)
        suite = unittest.defaultTestLoader.loadTestsFromName(target)
        self.assertEqual(suite.countTestCases(), 1)
        stream = StringIO()
        result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
        self.assertEqual(result.testsRun, 1)
        self.assertFalse(result.skipped)
        self.assertTrue(result.wasSuccessful(), stream.getvalue())


if __name__ == "__main__":
    unittest.main()
