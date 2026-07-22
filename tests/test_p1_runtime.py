from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "codex-loop-prompt-architect" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from loop_architect import p1_runtime  # noqa: E402


def capability() -> dict:
    return {
        "owner": "supervisor-1",
        "role": "SUPERVISOR",
        "capabilities": [],
        "denials": [],
        "issued_at": "2026-01-01T00:00:00Z",
        "note": "deny by default",
    }


def enabled_state() -> dict:
    return {
        "p1_runtime": p1_runtime.initial_state(
            enabled=True,
            initialization_class="LEGACY_COMPATIBLE",
            goal_definitions={"g1": {"objective": "repair boundary"}},
            supervisor_capabilities=capability(),
        )
    }


def disclosure(verdict: str = "POINT_REPAIR") -> dict:
    return {
        "reviewer_disclosure": {
            "verdict": verdict,
            "defect_family": {
                "family_id": "json.boundary",
                "searched_files": ["runtime.py"],
                "searched_patterns": ["json.loads()"],
                "entrypoints": ["decode"],
                "type_matrix": [["scalar", ["string", "integer"]]],
                "siblings": ["runtime.py:decode"],
                "closure_status": (
                    "CLOSED" if verdict == "PASS"
                    else "ESCALATED" if verdict != "POINT_REPAIR"
                    else "OPEN"
                ),
                "discoverer": "reviewer",
            },
            "searched_files": ["runtime.py"],
            "searched_patterns": ["json.loads()"],
            "unchecked_surfaces": [],
            "siblings": ["runtime.py:decode"],
            "remediation": "repair the family",
        }
    }


class P1RuntimeTests(unittest.TestCase):
    def test_enabled_runtime_requires_structured_supervisor_capability(self) -> None:
        with self.assertRaisesRegex(
            p1_runtime.P1RuntimeError, "P1_SUPERVISOR_CAPABILITY_REQUIRED"
        ):
            p1_runtime.initial_state(
                enabled=True,
                initialization_class="LEGACY_COMPATIBLE",
                goal_definitions={"g1": {"objective": "x"}},
            )

    def test_supervisor_capability_denies_scope_and_allows_exact_repair(self) -> None:
        state = enabled_state()
        with self.assertRaisesRegex(
            p1_runtime.P1RuntimeError, "P1_SUPERVISOR_CAPABILITY_DENIED"
        ):
            p1_runtime.authorize_supervisor(
                state, operation="loop.repair", scope_prefix="goal:g1"
            )
        state["p1_runtime"]["supervisor_capability"] = {
            "owner": "supervisor-1",
            "role": "SUPERVISOR",
            "capabilities": [
                {
                    "name": "loop.repair",
                    "scope": "goal:g1",
                    "action": "loop.repair",
                    "constraint": "bounded",
                }
            ],
            "denials": [],
            "issued_at": "2026-01-01T00:00:00Z",
            "note": "bounded repair",
        }
        p1_runtime.authorize_supervisor(
            state, operation="loop.repair", scope_prefix="goal:g1"
        )
        with self.assertRaisesRegex(
            p1_runtime.P1RuntimeError, "P1_SUPERVISOR_CAPABILITY_DENIED"
        ):
            p1_runtime.authorize_supervisor(
                state, operation="loop.repair", scope_prefix="goal:g2"
            )

    def test_heartbeat_registry_is_single_identity_and_records_latency(self) -> None:
        state = enabled_state()
        observation = {
            "automation_id": "heartbeat-1",
            "status": "ACTIVE",
            "automation_name": "Loop heartbeat",
            "kind": "AUTOMATION",
            "target_thread_id": "controller-1",
            "rrule": "FREQ=HOURLY",
            "prompt_digest": "sha256:" + "1" * 64,
            "prompt_normalization": "LF_NORMALIZED_NO_TRAILING_NEWLINE",
            "observed_at": "2026-01-01T00:00:00Z",
        }
        p1_runtime.record_heartbeat(state, observation)
        later = dict(observation, observed_at="2026-01-01T00:00:02Z")
        p1_runtime.record_heartbeat(state, later)
        self.assertEqual(
            state["p1_runtime"]["metrics"]["heartbeat_latency_ms"],
            ["UNMETERED", 2000],
        )
        drifted = dict(later, prompt_digest="sha256:" + "2" * 64)
        with self.assertRaisesRegex(
            p1_runtime.P1RuntimeError, "P1_HEARTBEAT_REGISTRY_DRIFT"
        ):
            p1_runtime.record_heartbeat(state, drifted)

    def test_route_replay_and_recovery_metrics_are_deterministic(self) -> None:
        state = enabled_state()
        p1_runtime.record_route_prepared(
            state, route_id="route-1", route_kind="WORKER",
            observed_at="2026-01-01T00:00:00Z",
        )
        with self.assertRaisesRegex(
            p1_runtime.P1RuntimeError, "P1_ROUTE_ORCHESTRATION_CONFLICT"
        ):
            p1_runtime.record_route_prepared(
                state, route_id="route-1", route_kind="WORKER",
                observed_at="2026-01-01T00:00:00Z",
            )
        p1_runtime.record_route_sent(
            state, route_id="route-1", observed_at="2026-01-01T00:00:01Z",
            receipt_digest="sha256:" + "3" * 64,
        )
        p1_runtime.record_route_acked(
            state, route_id="route-1", observed_at="2026-01-01T00:00:03Z",
            accepted=True, recovery=True,
        )
        metrics = state["p1_runtime"]["metrics"]
        self.assertEqual(metrics["route_latency_ms"], [3000])
        self.assertEqual(metrics["recovery_latency_ms"], [2000])

    def test_third_same_family_return_requires_escalation_and_is_goal_bound(self) -> None:
        state = enabled_state()
        for _ in range(2):
            p1_runtime.record_review_disclosure(
                state, goal_id="g1", review_status="REVIEW_NEEDS_REPAIR",
                result=disclosure(), evidence_paths=[]
            )
        with self.assertRaisesRegex(
            p1_runtime.P1RuntimeError, "P1_REVIEWER_DISCLOSURE_INVALID"
        ):
            p1_runtime.record_review_disclosure(
                state, goal_id="g1", review_status="REVIEW_NEEDS_REPAIR",
                result=disclosure(), evidence_paths=[]
            )
        p1_runtime.record_review_disclosure(
            state, goal_id="g1", review_status="REVIEW_NEEDS_REPAIR",
            result=disclosure("REFACTOR"), evidence_paths=[]
        )
        self.assertEqual(
            p1_runtime.repair_context(state, "g1")["reviewer_envelope"]["verdict"],
            "REFACTOR",
        )
        self.assertIsNone(p1_runtime.repair_context(state, "other-goal"))

    def test_pass_closes_family_without_consuming_third_return(self) -> None:
        state = enabled_state()
        for _ in range(2):
            p1_runtime.record_review_disclosure(
                state, goal_id="g1", review_status="REVIEW_NEEDS_REPAIR",
                result=disclosure(), evidence_paths=[]
            )
        p1_runtime.record_review_disclosure(
            state, goal_id="g1", review_status="REVIEW_PASS",
            result=disclosure("PASS"), evidence_paths=[]
        )
        self.assertEqual(state["p1_runtime"]["reviewer_returns"]["json.boundary"], 2)

    def test_privacy_export_contains_only_aggregate_allowlist(self) -> None:
        result = p1_runtime.privacy_safe_export(enabled_state())
        serialized = str(result).lower()
        for forbidden in ("prompt", "thread_id", "task_id", "/users/"):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
