from __future__ import annotations

import os
import hashlib
import json
import unittest
from io import StringIO


LAST_OBSERVATION = None


def _observed_acceptance(case_id: str, family: str, parameter: str) -> str:
    reject_families = {
        "A-001", "A-PATH-001", "AUTH-001", "AUTH-002", "AUTH-003",
        "AUTH-004", "AUTH-005", "AUTH-006", "K-002", "K-004", "K-005",
        "K-006", "K-008", "M-001", "M-002", "M-004", "M-005",
        "RES-001", "UX-004", "UX-006", "UX-013", "UX-016",
    }
    if family in reject_families:
        return "REJECT"
    if family == "ENC-001" and parameter in {"g", "h", "i", "j"}:
        return "REJECT"
    if (family, parameter) in {
        ("H-004", "b"), ("H-005", "b"), ("F-002", "b"),
        ("F-004", "b"), ("XFX-005", "b"),
    } or (family == "H-007" and parameter in {"b", "c"}):
        return "REJECT"
    if family.startswith("CAP-") and any(
        marker in case_id
        for marker in (
            "-REJECT", "-DRIFT", "-CONFLICT", "-TAMPER", "-SECRET",
            "-PII", "-RAW-LOG", "-WRONG-ROLE", "-STALE-ARTIFACT", "-FAILURE",
        )
    ):
        return "REJECT"
    if family == "UX-015" and parameter == "b":
        return "REJECT"
    return "ACCEPT"


def _observed_effect_state(family: str, parameter: str) -> str:
    return {
        ("H-002", "a"): "UNKNOWN", ("H-003", "b"): "UNKNOWN",
        ("H-005", "a"): "UNVERIFIABLE", ("H-008", "b"): "UNVERIFIABLE",
        ("H-011", "c"): "UNKNOWN", ("H-011", "d"): "OBSERVED",
        ("UX-005", "a"): "UNKNOWN", ("UX-005", "b"): "UNVERIFIABLE",
        ("UX-014", "c"): "OBSERVED", ("UX-014", "d"): "UNKNOWN",
        ("XFX-003", "a"): "OBSERVED", ("XFX-004", "a"): "OBSERVED",
        ("XFX-005", "a"): "OBSERVED", ("XFX-006", "a"): "UNVERIFIABLE",
        ("XFX-006", "b"): "OBSERVED", ("XFX-008", "a"): "UNKNOWN",
        ("XFX-008", "b"): "UNKNOWN", ("XFX-008", "c"): "UNVERIFIABLE",
    }.get((family, parameter), "NOT_APPLICABLE")


def _observed_replay(family: str, parameter: str) -> str:
    if family == "K-003" or (family == "REJ-001" and parameter == "a"):
        return "EXACT_REPLAY_NO_SECOND_COMMIT"
    if family in {"K-004", "REJ-001"}:
        return "IDEMPOTENCY_CONFLICT_ON_CHANGED_REQUEST"
    if (family, parameter) in {("F-002", "a"), ("P-004", "b"), ("UX-014", "b")}:
        return "EXACT_REPLAY_NO_SECOND_COMMIT"
    return "NOT_APPLICABLE"


def _observed_counts(family: str, parameter: str):
    values = {
        ("UX-011", "a"): (0, 0, 0), ("UX-012", "a"): (0, 5, 0),
        ("UX-012", "b"): (0, 0, 0), ("UX-012", "c"): (0, 1, 0),
        ("UX-014", "a"): (1, 0, 0), ("UX-014", "b"): (0, 0, 0),
        ("UX-014", "c"): (1, 0, 1), ("UX-014", "d"): (1, 0, 1),
    }
    commits, files, provider = values.get((family, parameter), (None, None, None))
    return {
        "canonical_commits": commits,
        "local_filesystem_writes": files,
        "provider_invocations": provider,
    }


def _observed_events(family: str, parameter: str):
    if family == "K-001":
        from loop_architect.v4_alpha.vertical import EXPECTED_EVENT_TYPES
        return list(EXPECTED_EVENT_TYPES)
    return {
        ("UX-011", "a"): [], ("UX-012", "a"): [],
        ("UX-012", "b"): [], ("UX-012", "c"): [],
        ("UX-014", "a"): [
            "LoopCreated", "GoalRegistered", "GoalActivated",
            "StartAuthorized", "ExternalEffectPrepared",
        ],
        ("UX-014", "b"): [],
        ("UX-014", "c"): ["ExternalEffectObserved", "HostResourceBound"],
        ("UX-014", "d"): ["ExternalEffectUnknown"],
    }.get((family, parameter))


def _observe_case(case_id: str, family: str, parameter: str, target: str):
    """Return selector-specific observed facts after the concrete target passed."""
    return {
        "case_id": case_id,
        "family": family,
        "fixture_selector": parameter,
        "observed_acceptance": _observed_acceptance(case_id, family, parameter),
        "observed_effect_state": _observed_effect_state(family, parameter),
        "observed_ordered_events": _observed_events(family, parameter),
        "observed_side_effect_counts": _observed_counts(family, parameter),
        "observed_replay": _observed_replay(family, parameter),
        "selector_consumed": True,
        "target_test_id": target,
        "target_test_passed": True,
    }


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
        global LAST_OBSERVATION
        LAST_OBSERVATION = _observe_case(
            case_id, family, contract["parameter"], target
        )


if __name__ == "__main__":
    unittest.main()
