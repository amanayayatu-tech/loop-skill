"""Required release smoke for the three incident-derived P0 boundaries.

The authoritative server runs this exact file during quick preflight.  Keep the
list small, semantic, and negative: each selected test exercises runtime
behavior and durable side-effect checks rather than searching generated text.
"""

from __future__ import annotations

import unittest

import test_adaptive_runtime_transport as transport_tests
import test_control_plane_reliability_baseline as control_plane_tests
import test_real_incident_regression as incident_tests


REQUIRED_P0_TESTS = (
    (
        transport_tests,
        "AdaptiveRuntimeTransportTests.test_partial_open_pipe_times_out",
    ),
    (
        transport_tests,
        "AdaptiveRuntimeTransportTests.test_invalid_utf8_is_rejected_immediately",
    ),
    (
        control_plane_tests,
        "UnclosedControlPlaneFindingTests.test_route_without_trusted_app_metadata_fails_closed",
    ),
    (
        control_plane_tests,
        "UnclosedControlPlaneFindingTests.test_same_real_turn_cannot_route_twice_with_different_claimed_ids",
    ),
    (
        control_plane_tests,
        "UnclosedControlPlaneFindingTests.test_external_receipt_requires_canonical_route_and_provider_identity",
    ),
    (
        control_plane_tests,
        "UnclosedControlPlaneFindingTests.test_external_receipt_rejects_pass_with_nonzero_exit",
    ),
    (
        incident_tests,
        "DurableExternalReceiptTests.test_started_recovery_is_conservative_and_forbids_provider_retry",
    ),
    (
        incident_tests,
        "DurableExternalReceiptTests.test_completed_receipt_survives_lost_stdout_and_is_idempotent",
    ),
)


def load_tests(
    loader: unittest.TestLoader,
    standard_tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    del standard_tests, pattern
    suite = unittest.TestSuite()
    for module, qualified_name in REQUIRED_P0_TESTS:
        suite.addTests(loader.loadTestsFromName(qualified_name, module))
    return suite


if __name__ == "__main__":
    unittest.main()
