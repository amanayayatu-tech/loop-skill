"""Tests for the P1 implementation modules.

Each test class targets one P1 or P2 deliverable:

* :class:`DefectFamilyTests` covers P1-1
* :class:`ReviewerEnvelopeTests` covers P1-2 / P1-3
* :class:`RouteOrchestratorTests` covers P1-4
* :class:`MetricsLedgerTests` covers P1-5
* :class:`PrivacyExportTests` covers P1-6
* :class:`HeartbeatRegistryTests` covers P1-8
* :class:`CapabilityEnvelopeTests` covers P1-9
* :class:`ManifestCompilerTests` covers P1-10
* :class:`GoalRegistryRulesTests` covers P1-11

The tests are pure stdlib and run in <2s. They live under ``tests/``
so the existing ``python3 -m unittest discover`` invocation picks
them up automatically.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "codex-loop-prompt-architect" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import recovery_coverage_check  # noqa: E402

from loop_architect import (  # noqa: E402
    capability_envelope,
    defect_family,
    goal_registry_rules,
    heartbeat_registry,
    manifest_compiler,
    metrics_ledger,
    privacy_export,
    reviewer_envelope,
    route_orchestrator,
)


# ---------------------------------------------------------------------------
# P1-1 Defect family
# ---------------------------------------------------------------------------


class DefectFamilyTests(unittest.TestCase):
    def test_round_trip_to_from_dict(self) -> None:
        family = defect_family.DefectFamily(
            family_id="json.boundary",
            searched_files=("a.py", "b.py"),
            searched_patterns=("json.loads()",),
            entrypoints=("main",),
            type_matrix=(("scalar", ("int", "float")),),
            siblings=("a.py:42", "b.py:7"),
            closure_status="OPEN",
            discoverer="tester",
            remediation_note="seeded",
        )
        payload = family.to_dict()
        restored = defect_family.DefectFamily.from_dict(payload)
        self.assertEqual(restored, family)
        self.assertEqual(len(restored.digest()), 64)

    def test_invalid_family_id_rejected(self) -> None:
        with self.assertRaises(defect_family.DefectFamilyError):
            defect_family.DefectFamily(
                family_id="1-bad",
                searched_files=(),
                searched_patterns=(),
                entrypoints=(),
                type_matrix=(),
                siblings=(),
                closure_status="OPEN",
                discoverer="x",
            )

    def test_external_json_exact_type_matrix_rejected(self) -> None:
        valid = {
            "family_id": "json.boundary",
            "searched_files": ["a.py"],
            "searched_patterns": ["loads()"],
            "entrypoints": ["main"],
            "type_matrix": [["scalar", ["string"]]],
            "siblings": ["a.py:1"],
            "closure_status": "OPEN",
            "discoverer": "reviewer",
        }
        mutations = []
        for field, wrong in (
            ("family_id", 1),
            ("searched_files", "a.py"),
            ("searched_patterns", {"loads()": True}),
            ("entrypoints", [1]),
            ("type_matrix", {"scalar": ["string"]}),
            ("siblings", [False]),
            ("closure_status", ["OPEN"]),
            ("discoverer", None),
        ):
            candidate = dict(valid)
            candidate[field] = wrong
            mutations.append(candidate)
        mutations.extend(
            [
                {**valid, "unexpected": True},
                {key: value for key, value in valid.items() if key != "siblings"},
                {**valid, "type_matrix": [["scalar"]]},
                {**valid, "type_matrix": [["scalar", "string"]]},
            ]
        )
        for candidate in mutations:
            with self.subTest(candidate=candidate):
                with self.assertRaises(defect_family.DefectFamilyError):
                    defect_family.DefectFamily.from_dict(candidate)

    def test_ledger_appends_and_rejects_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            ledger = defect_family.DefectFamilyLedger.open(path)
            family = defect_family.DefectFamily(
                family_id="json.boundary",
                searched_files=(),
                searched_patterns=(),
                entrypoints=(),
                type_matrix=(),
                siblings=("a",),
                closure_status="OPEN",
                discoverer="x",
            )
            first = ledger.append(family)
            # Re-appending the same family is a no-op that returns the
            # existing chain hash; only a same-id, different-digest
            # family is rejected.
            second = ledger.append(family)
            self.assertEqual(first, second)
            altered = defect_family.DefectFamily(
                family_id=family.family_id,
                searched_files=(),
                searched_patterns=(),
                entrypoints=(),
                type_matrix=(),
                siblings=("a", "b"),
                closure_status=family.closure_status,
                discoverer=family.discoverer,
            )
            with self.assertRaises(defect_family.DefectFamilyError):
                ledger.append(altered)

    def test_merge_sibling_discovery_dedupes(self) -> None:
        base = defect_family.DefectFamily(
            family_id="json.boundary",
            searched_files=(),
            searched_patterns=(),
            entrypoints=(),
            type_matrix=(),
            siblings=("a", "b"),
            closure_status="OPEN",
            discoverer="x",
        )
        merged = defect_family.merge_sibling_discovery(
            base, [{"sibling": "b"}, {"sibling": "c"}]
        )
        self.assertEqual(merged.siblings, ("a", "b", "c"))

    def test_invalid_closure_status_rejected(self) -> None:
        with self.assertRaises(defect_family.DefectFamilyError):
            defect_family.DefectFamily(
                family_id="json.boundary",
                searched_files=(),
                searched_patterns=(),
                entrypoints=(),
                type_matrix=(),
                siblings=(),
                closure_status="BOGUS",
                discoverer="x",
            )

    def test_invalid_sibling_rejected(self) -> None:
        with self.assertRaises(defect_family.DefectFamilyError):
            defect_family.DefectFamily(
                family_id="json.boundary",
                searched_files=(),
                searched_patterns=(),
                entrypoints=(),
                type_matrix=(),
                siblings=("a$b",),
                closure_status="OPEN",
                discoverer="x",
            )

    def test_invalid_pattern_rejected(self) -> None:
        with self.assertRaises(defect_family.DefectFamilyError):
            defect_family.DefectFamily(
                family_id="json.boundary",
                searched_files=(),
                searched_patterns=("bad\npattern",),
                entrypoints=(),
                type_matrix=(),
                siblings=(),
                closure_status="OPEN",
                discoverer="x",
            )

    def test_sibling_cap_enforced(self) -> None:
        siblings = tuple(f"a{i}" for i in range(defect_family.MAX_SIBLINGS_PER_FAMILY + 1))
        with self.assertRaises(defect_family.DefectFamilyError):
            defect_family.DefectFamily(
                family_id="json.boundary",
                searched_files=(),
                searched_patterns=(),
                entrypoints=(),
                type_matrix=(),
                siblings=siblings,
                closure_status="OPEN",
                discoverer="x",
            )

    def test_merge_drops_over_cap(self) -> None:
        base = defect_family.DefectFamily(
            family_id="json.boundary",
            searched_files=(),
            searched_patterns=(),
            entrypoints=(),
            type_matrix=(),
            siblings=tuple(f"a{i}" for i in range(defect_family.MAX_SIBLINGS_PER_FAMILY - 1)),
            closure_status="OPEN",
            discoverer="x",
        )
        merged = defect_family.merge_sibling_discovery(
            base,
            [{"sibling": "new1"}, {"sibling": "new2"}, {"sibling": "new3"}],
            max_new=defect_family.MAX_SIBLINGS_PER_FAMILY,
        )
        self.assertIn("merge dropped", merged.remediation_note)
        self.assertEqual(len(merged.siblings), defect_family.MAX_SIBLINGS_PER_FAMILY)

    def test_ledger_corrupt_line_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            path.write_text("{not json\n")
            with self.assertRaises(defect_family.DefectFamilyError):
                defect_family.DefectFamilyLedger.open(path)

    def test_ledger_find_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            ledger = defect_family.DefectFamilyLedger.open(path)
            for idx, fid in enumerate(("json.boundary", "json.other", "yaml.parse"), start=1):
                ledger.append(
                    defect_family.DefectFamily(
                        family_id=fid,
                        searched_files=(),
                        searched_patterns=(),
                        entrypoints=(),
                        type_matrix=(),
                        siblings=(),
                        closure_status="OPEN",
                        discoverer="x",
                    )
                )
            siblings = ledger.find_siblings("json.boundary")
            ids = sorted(family.family_id for family in siblings)
            self.assertEqual(ids, ["json.other"])
            reopened = defect_family.DefectFamilyLedger.open(path)
            reopened_ids = sorted(reopened.families)
            self.assertEqual(
                reopened_ids, ["json.boundary", "json.other", "yaml.parse"]
            )

    def test_ledger_same_family_returns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            ledger = defect_family.DefectFamilyLedger.open(path)
            self.assertEqual(ledger.same_family_returns("nope"), 0)
            ledger.append(
                defect_family.DefectFamily(
                    family_id="json.boundary",
                    searched_files=(),
                    searched_patterns=(),
                    entrypoints=(),
                    type_matrix=(),
                    siblings=(),
                    closure_status="OPEN",
                    discoverer="x",
                )
            )
            self.assertEqual(ledger.same_family_returns("json.boundary"), 1)


# ---------------------------------------------------------------------------
# P1-2 / P1-3 Reviewer envelope
# ---------------------------------------------------------------------------


class ReviewerEnvelopeTests(unittest.TestCase):
    def _digest(self) -> str:
        return "a" * 64

    def test_third_return_must_escalate(self) -> None:
        with self.assertRaises(reviewer_envelope.ReviewerEnvelopeError):
            reviewer_envelope.build_envelope(
                verdict="POINT_REPAIR",
                defect_family_id="json.boundary",
                defect_family_digest=self._digest(),
                searched_files=("a",),
                searched_patterns=(),
                unchecked_surfaces=(),
                siblings=("a:1",),
                return_number=3,
            )

    def test_external_json_scalar_and_container_coercion_rejected(self) -> None:
        valid = {
            "verdict": "POINT_REPAIR",
            "defect_family_id": "json.boundary",
            "defect_family_digest": "sha256:" + "1" * 64,
            "searched_files": ["a.py"],
            "searched_patterns": ["loads()"],
            "unchecked_surfaces": [],
            "siblings": [],
            "return_number": 1,
        }
        for field, wrong in (
            ("verdict", 1),
            ("defect_family_id", False),
            ("searched_files", "a.py"),
            ("searched_patterns", [1]),
            ("unchecked_surfaces", {}),
            ("siblings", [None]),
            ("return_number", "1"),
        ):
            candidate = dict(valid)
            candidate[field] = wrong
            with self.subTest(field=field):
                with self.assertRaises(reviewer_envelope.ReviewerEnvelopeError):
                    reviewer_envelope.envelope_from_mapping(candidate)

    def test_escalation_verdict_accepted(self) -> None:
        env = reviewer_envelope.build_envelope(
            verdict="REFACTOR",
            defect_family_id="json.boundary",
            defect_family_digest=self._digest(),
            searched_files=("a",),
            searched_patterns=(),
            unchecked_surfaces=(),
            siblings=("a:1",),
            return_number=3,
            remediation="split json parsing into per-call sites",
        )
        self.assertEqual(env.return_number, 3)
        self.assertEqual(len(env.digest()), 64)

    def test_counter_advances_and_triggers_at_threshold(self) -> None:
        counter = reviewer_envelope.ReviewerReturnCounter()
        self.assertEqual(counter.observe("json.boundary"), 1)
        self.assertEqual(counter.observe("json.boundary"), 2)
        self.assertFalse(counter.is_at_threshold("json.boundary"))
        counter.observe("json.boundary")
        self.assertTrue(counter.is_at_threshold("json.boundary"))


# ---------------------------------------------------------------------------
# P1-4 Route orchestrator
# ---------------------------------------------------------------------------


class RouteOrchestratorTests(unittest.TestCase):
    def test_three_step_orchestration_completes(self) -> None:
        steps = route_orchestrator.fold_legacy_three_step(
            prepare_payload={"route": "x"},
            send_receipt={"sent": True},
            record_payload={"route": "x"},
        )
        receipts: list[dict] = []
        receipt = route_orchestrator.orchestrate(
            turn_id="t1",
            steps=steps,
            write=lambda step: receipts.append({"op": step.operation}) or {"op": step.operation},
        )
        self.assertEqual(receipt.status, route_orchestrator.STATUS_COMPLETED)
        self.assertEqual(len(receipt.step_receipts), 2)
        self.assertEqual(receipts[0]["op"], "PREPARE_ROUTE")
        self.assertEqual(receipts[1]["op"], "RECORD_ROUTE_SENT")
        self.assertEqual(len(receipt.digest), 64)

    def test_writer_returning_refused_aborts(self) -> None:
        steps = (
            route_orchestrator.OrchestrationStep(
                operation="PREPARE_ROUTE", payload={}
            ),
        )

        def write(step: route_orchestrator.OrchestrationStep):
            return {"status": route_orchestrator.REFUSED_SENTINEL}

        receipt = route_orchestrator.orchestrate(
            turn_id="t2", steps=steps, write=write
        )
        self.assertEqual(receipt.status, route_orchestrator.STATUS_ABORTED)

    def test_empty_steps_rejected(self) -> None:
        with self.assertRaises(route_orchestrator.RouteOrchestrationError):
            route_orchestrator.orchestrate(
                turn_id="t3",
                steps=(),
                write=lambda step: {},
            )

    def test_resume_skips_already_acknowledged_external_step(self) -> None:
        steps = route_orchestrator.fold_legacy_three_step(
            prepare_payload={"route_id": "r1"},
            send_receipt={"message_id": "m1"},
            record_payload={"route_id": "r1"},
        )
        called: list[str] = []
        receipt = route_orchestrator.orchestrate(
            turn_id="turn-resume",
            steps=steps,
            completed_step_receipts=({"status": "PREPARED"},),
            write=lambda step: called.append(step.operation) or {"status": "SENT"},
        )
        self.assertEqual(called, ["RECORD_ROUTE_SENT"])
        self.assertEqual(receipt.status, route_orchestrator.STATUS_COMPLETED)
        self.assertEqual(len(receipt.step_receipts), 2)
        self.assertTrue(steps[1].external_receipt_digest)

    def test_step_identity_binds_external_receipt(self) -> None:
        first = route_orchestrator.fold_legacy_three_step(
            prepare_payload={}, send_receipt={"id": "one"}, record_payload={}
        )
        second = route_orchestrator.fold_legacy_three_step(
            prepare_payload={}, send_receipt={"id": "two"}, record_payload={}
        )
        self.assertNotEqual(first[1].canonical(), second[1].canonical())


# ---------------------------------------------------------------------------
# P1-5 Metrics ledger
# ---------------------------------------------------------------------------


class MetricsLedgerTests(unittest.TestCase):
    def test_record_and_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metrics.jsonl"
            ledger = metrics_ledger.MetricsLedger.open(
                path, run_id="r1", source_sha="abc"
            )
            ledger.record("accepted_count", 5)
            ledger.record("rejected_count", 2)
            ledger.record("token_estimate", metrics_ledger.UNMETERED)
            self.assertEqual(ledger.count_of("accepted_count"), 1)
            self.assertEqual(ledger.count, 3)
            self.assertEqual(len(ledger.last_hash), 64)

    def test_unknown_kind_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = metrics_ledger.MetricsLedger.open(
                Path(tmp) / "m.jsonl", run_id="r", source_sha="x"
            )
            with self.assertRaises(metrics_ledger.MetricsLedgerError):
                ledger.record("nonsense", 1)

    def test_reload_validates_hash_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.jsonl"
            ledger = metrics_ledger.MetricsLedger.open(
                path, run_id="r", source_sha="x"
            )
            ledger.record("accepted_count", 1)
            # Tamper with the file
            text = path.read_text()
            path.write_text(text.replace("accepted_count", "tampered_count"))
            with self.assertRaises(metrics_ledger.MetricsLedgerError):
                metrics_ledger.MetricsLedger.open(
                    path, run_id="r", source_sha="x"
                )

    def test_sum_of_tracks_numeric_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.jsonl"
            ledger = metrics_ledger.MetricsLedger.open(
                path, run_id="r", source_sha="x"
            )
            ledger.record("accepted_count", 5)
            ledger.record("accepted_count", 3)
            ledger.record("rejected_count", 2)
            self.assertEqual(ledger.sum_of("accepted_count"), 8)
            self.assertEqual(ledger.sum_of("rejected_count"), 2)
            self.assertEqual(ledger.sum_of("human_intervention_count"), 0)

    def test_reload_rejects_corrupt_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.jsonl"
            path.write_text("{not json\n")
            with self.assertRaises(metrics_ledger.MetricsLedgerError):
                metrics_ledger.MetricsLedger.open(
                    path, run_id="r", source_sha="x"
                )

    def test_sum_of_unknown_kind_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = metrics_ledger.MetricsLedger.open(
                Path(tmp) / "m.jsonl", run_id="r", source_sha="x"
            )
            with self.assertRaises(metrics_ledger.MetricsLedgerError):
                ledger.sum_of("not_a_kind")

    def test_count_of_unknown_kind_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = metrics_ledger.MetricsLedger.open(
                Path(tmp) / "m.jsonl", run_id="r", source_sha="x"
            )
            with self.assertRaises(metrics_ledger.MetricsLedgerError):
                ledger.count_of("not_a_kind")


# ---------------------------------------------------------------------------
# P1-6 Privacy export
# ---------------------------------------------------------------------------


class PrivacyExportTests(unittest.TestCase):
    def test_export_only_has_aggregates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metrics.jsonl"
            ledger = metrics_ledger.MetricsLedger.open(
                path, run_id="r", source_sha="abc"
            )
            ledger.record("accepted_count", 8)
            ledger.record("rejected_count", 2)
            ledger.record("human_intervention_count", 1)
            export = privacy_export.export_from_ledger(ledger)
            payload = export.to_dict()
            self.assertEqual(payload["total_records"], 3)
            self.assertAlmostEqual(payload["rejection_rate"], 0.2)
            self.assertEqual(payload["intervention_total"], 1)
            for forbidden in privacy_export.FORBIDDEN_TOP_LEVEL_FIELDS:
                self.assertNotIn(forbidden, payload)

    def test_forbidden_field_rejected(self) -> None:
        with self.assertRaises(privacy_export.PrivacyExportError):
            privacy_export.enforce_no_forbidden_fields(
                {"prompt": "secret", "run_id": "r"}
            )

    def test_forbidden_substring_rejected(self) -> None:
        with self.assertRaises(privacy_export.PrivacyExportError):
            privacy_export.enforce_no_forbidden_fields(
                {"ok": True, "metadata": {"raw_prompt_fragment": "x"}}
            )

    def test_digest_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.jsonl"
            ledger = metrics_ledger.MetricsLedger.open(
                path, run_id="r", source_sha="abc"
            )
            ledger.record("accepted_count", 1)
            export_a = privacy_export.export_from_ledger(ledger)
            export_b = privacy_export.export_from_ledger(ledger)
            self.assertEqual(export_a.digest(), export_b.digest())


# ---------------------------------------------------------------------------
# P1-8 Heartbeat registry
# ---------------------------------------------------------------------------


class HeartbeatRegistryTests(unittest.TestCase):
    def test_register_and_assert_drift_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "heartbeat.jsonl"
            registry = heartbeat_registry.HeartbeatRegistry(path)
            record = heartbeat_registry.new_heartbeat_record(
                automation_id="hb-1",
                target="turn-1",
                rrule="FREQ=MINUTELY;INTERVAL=10",
                prompt_text="heartbeat prompt body",
                purpose="canary-watch",
                status="ACTIVE",
                event_type="REGISTER",
                sequence=1,
            )
            registry.append(record)
            latest = registry.assert_drift_free(
                "hb-1", expected_prompt_digest=record.prompt_digest
            )
            self.assertEqual(latest.status, "ACTIVE")

    def test_drift_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "heartbeat.jsonl"
            registry = heartbeat_registry.HeartbeatRegistry(path)
            record = heartbeat_registry.new_heartbeat_record(
                automation_id="hb-1",
                target="t",
                rrule="FREQ=DAILY",
                prompt_text="body",
                purpose="p",
                status="ACTIVE",
                event_type="REGISTER",
                sequence=1,
            )
            registry.append(record)
            with self.assertRaises(heartbeat_registry.HeartbeatRegistryError):
                registry.assert_drift_free("hb-1", expected_prompt_digest="0" * 64)

    def test_out_of_order_sequence_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "heartbeat.jsonl"
            registry = heartbeat_registry.HeartbeatRegistry(path)
            first = heartbeat_registry.new_heartbeat_record(
                automation_id="hb-1",
                target="t",
                rrule="FREQ=DAILY",
                prompt_text="p",
                purpose="p",
                status="ACTIVE",
                event_type="REGISTER",
                sequence=1,
            )
            registry.append(first)
            second = heartbeat_registry.new_heartbeat_record(
                automation_id="hb-1",
                target="t",
                rrule="FREQ=DAILY",
                prompt_text="p",
                purpose="p",
                status="PAUSED",
                event_type="PAUSE",
                sequence=1,
            )
            with self.assertRaises(heartbeat_registry.HeartbeatRegistryError):
                registry.append(second)

    def test_pause_resume_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "heartbeat.jsonl"
            registry = heartbeat_registry.HeartbeatRegistry(path)
            first = heartbeat_registry.new_heartbeat_record(
                automation_id="hb-1",
                target="t",
                rrule="FREQ=DAILY",
                prompt_text="p",
                purpose="p",
                status="ACTIVE",
                event_type="REGISTER",
                sequence=1,
            )
            registry.append(first)
            pause = heartbeat_registry.new_heartbeat_record(
                automation_id="hb-1",
                target="t",
                rrule="FREQ=DAILY",
                prompt_text="p",
                purpose="p",
                status="PAUSED",
                event_type="PAUSE",
                sequence=2,
            )
            registry.append(pause)
            self.assertEqual(registry.latest("hb-1").status, "PAUSED")
            resume = heartbeat_registry.new_heartbeat_record(
                automation_id="hb-1",
                target="t",
                rrule="FREQ=DAILY",
                prompt_text="p",
                purpose="p",
                status="ACTIVE",
                event_type="RESUME",
                sequence=3,
            )
            registry.append(resume)
            self.assertEqual(registry.latest("hb-1").status, "ACTIVE")
            self.assertEqual(len(registry.history("hb-1")), 3)

    def test_missing_record_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "heartbeat.jsonl"
            registry = heartbeat_registry.HeartbeatRegistry(path)
            with self.assertRaises(heartbeat_registry.HeartbeatRegistryError):
                registry.assert_drift_free("nope", expected_prompt_digest="x" * 64)

    def test_invalid_automation_id_rejected(self) -> None:
        with self.assertRaises(heartbeat_registry.HeartbeatRegistryError):
            heartbeat_registry.new_heartbeat_record(
                automation_id="bad id with space",
                target="t",
                rrule="FREQ=DAILY",
                prompt_text="p",
                purpose="p",
                status="ACTIVE",
                event_type="REGISTER",
                sequence=1,
            )

    def test_invalid_event_type_rejected(self) -> None:
        with self.assertRaises(heartbeat_registry.HeartbeatRegistryError):
            heartbeat_registry.new_heartbeat_record(
                automation_id="hb-1",
                target="t",
                rrule="FREQ=DAILY",
                prompt_text="p",
                purpose="p",
                status="ACTIVE",
                event_type="BOGUS",
                sequence=1,
            )

    def test_corrupt_json_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "heartbeat.jsonl"
            path.write_text("{not valid json\n")
            with self.assertRaises(heartbeat_registry.HeartbeatRegistryError):
                heartbeat_registry.HeartbeatRegistry(path)

    def test_all_automation_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "heartbeat.jsonl"
            registry = heartbeat_registry.HeartbeatRegistry(path)
            for idx in range(2):
                record = heartbeat_registry.new_heartbeat_record(
                    automation_id=f"hb-{idx}",
                    target="t",
                    rrule="FREQ=DAILY",
                    prompt_text="p",
                    purpose="p",
                    status="ACTIVE",
                    event_type="REGISTER",
                    sequence=1,
                )
                registry.append(record)
            self.assertEqual(registry.all_automation_ids(), ("hb-0", "hb-1"))


# ---------------------------------------------------------------------------
# P1-9 Capability envelope
# ---------------------------------------------------------------------------


class CapabilityEnvelopeTests(unittest.TestCase):
    def test_authorize_and_deny(self) -> None:
        envelope = capability_envelope.required_host_envelope()
        self.assertTrue(
            envelope.authorize(
                "canary.run", scope_prefix="mcp:codex-loop-state"
            )
        )
        self.assertFalse(envelope.authorize("loop.push"))

    def test_scope_matching_is_delimiter_aware_and_grant_directed(self) -> None:
        envelope = capability_envelope.CapabilityEnvelope(
            owner="supervisor",
            role="SUPERVISOR",
            capabilities=(
                capability_envelope.Capability(
                    name="loop.repair",
                    scope="goal:g1",
                    action="loop.repair",
                    constraint="bounded",
                ),
            ),
        )
        self.assertTrue(envelope.authorize("loop.repair", scope_prefix="goal:g1"))
        self.assertTrue(
            envelope.authorize("loop.repair", scope_prefix="goal:g1:repair")
        )
        self.assertFalse(envelope.authorize("loop.repair", scope_prefix="goal:g10"))

    def test_digest_is_stable(self) -> None:
        a = capability_envelope.required_host_envelope()
        b = capability_envelope.required_host_envelope()
        self.assertEqual(a.digest(), b.digest())

    def test_invalid_action_rejected(self) -> None:
        with self.assertRaises(capability_envelope.CapabilityEnvelopeError):
            capability_envelope.Capability(
                name="weird.action",
                scope="global",
                action="not-allowed",
                constraint="none",
            )

    def test_diff_envelopes(self) -> None:
        before = capability_envelope.required_host_envelope()
        after = capability_envelope.CapabilityEnvelope(
            owner="codex-app",
            role="host",
            capabilities=before.capabilities
            + (
                capability_envelope.Capability(
                    name="extra.capability",
                    scope="mcp:codex-loop-state",
                    action="canary.run",
                    constraint="audit only",
                ),
            ),
        )
        diff = capability_envelope.diff_envelopes(before, after)
        self.assertEqual(diff["added"], ["extra.capability"])
        self.assertEqual(diff["removed"], [])


# ---------------------------------------------------------------------------
# P1-10 Manifest compiler
# ---------------------------------------------------------------------------


class ManifestCompilerTests(unittest.TestCase):
    def _source(self) -> dict:
        return {
            "schema_version": "loop-source-v1",
            "roles": [
                {"id": "controller", "model": "gpt-5.6", "responsibilities": ["decide"]},
            ],
            "goals": [
                {
                    "id": "G0",
                    "objective": "deliver artifact",
                    "required_completion_class": "COMPLETE_ARTIFACT",
                },
            ],
            "heartbeat": {
                "rrule": "FREQ=MINUTELY;INTERVAL=10",
                "target": "t1",
                "prompt_digest": "0" * 64,
            },
            "policy": {"migrations": []},
        }

    def test_compile_succeeds(self) -> None:
        manifest = manifest_compiler.compile_manifest(self._source())
        self.assertEqual(len(manifest.digest), 64)
        self.assertEqual(
            manifest.digest,
            hashlib.sha256(manifest.to_digest_bytes()).hexdigest(),
        )
        self.assertEqual(len(manifest.roles), 1)
        self.assertEqual(len(manifest.goals), 1)

    def test_missing_required_keys_rejected(self) -> None:
        source = self._source()
        source.pop("heartbeat")
        with self.assertRaises(manifest_compiler.ManifestCompilerError):
            manifest_compiler.compile_manifest(source)

    def test_invalid_completion_class_rejected(self) -> None:
        source = self._source()
        source["goals"][0]["required_completion_class"] = "NOPE"
        with self.assertRaises(manifest_compiler.ManifestCompilerError):
            manifest_compiler.compile_manifest(source)

    def test_diff_manifests(self) -> None:
        source = self._source()
        before = manifest_compiler.compile_manifest(source)
        source["goals"].append(
            {
                "id": "G1",
                "objective": "extra",
                "required_completion_class": "COMPLETE_ARTIFACT",
            }
        )
        after = manifest_compiler.compile_manifest(source)
        diff = manifest_compiler.diff_manifests(before, after)
        self.assertEqual(diff["goals_added"], ["G1"])

    def test_unknown_policy_kind_rejected(self) -> None:
        source = self._source()
        source["policy"] = {"migrations": [{"kind": "BOGUS"}]}
        with self.assertRaises(manifest_compiler.ManifestCompilerError):
            manifest_compiler.compile_manifest(source)

    def test_goal_count_cap_rejected(self) -> None:
        source = self._source()
        source["goals"] = [
            {
                "id": f"G{i}",
                "objective": "x",
                "required_completion_class": "COMPLETE_ARTIFACT",
            }
            for i in range(manifest_compiler.MAX_GOALS + 1)
        ]
        with self.assertRaises(manifest_compiler.ManifestCompilerError):
            manifest_compiler.compile_manifest(source)

    def test_role_count_cap_rejected(self) -> None:
        source = self._source()
        source["roles"] = [
            {"id": f"R{i}", "model": "m", "responsibilities": ["x"]}
            for i in range(manifest_compiler.MAX_ROLES + 1)
        ]
        with self.assertRaises(manifest_compiler.ManifestCompilerError):
            manifest_compiler.compile_manifest(source)

    def test_goal_missing_objective_rejected(self) -> None:
        source = self._source()
        source["goals"][0].pop("objective")
        with self.assertRaises(manifest_compiler.ManifestCompilerError):
            manifest_compiler.compile_manifest(source)

    def test_heartbeat_missing_field_rejected(self) -> None:
        source = self._source()
        source["heartbeat"].pop("rrule")
        with self.assertRaises(manifest_compiler.ManifestCompilerError):
            manifest_compiler.compile_manifest(source)

    def test_write_compiled_manifest_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = manifest_compiler.compile_manifest(self._source())
            path = Path(tmp) / "manifest.json"
            manifest_compiler.write_compiled_manifest(path, manifest)
            payload = json.loads(path.read_text())
            self.assertEqual(payload["digest"], manifest.digest)


# ---------------------------------------------------------------------------
# P1-11 Goal registry rules
# ---------------------------------------------------------------------------


class GoalRegistryRulesTests(unittest.TestCase):
    def test_disposable_registry_only_accepts_cp0(self) -> None:
        registry = goal_registry_rules.GoalRegistry(disposable=True)
        registry.initialize(
            [{"goal_id": goal_registry_rules.DISPOSABLE_CP0_GOAL_ID, "objective": "self-test", "required_completion_class": "COMPLETE_ARTIFACT"}]
        )
        self.assertEqual(len(registry.goals), 1)
        with self.assertRaises(goal_registry_rules.GoalRegistryError):
            goal_registry_rules.GoalRegistry(disposable=True).initialize(
                [
                    {
                        "goal_id": "D0-control-plane-self-test",
                        "objective": "self-test",
                        "required_completion_class": "COMPLETE_ARTIFACT",
                    },
                    {
                        "goal_id": "D1",
                        "objective": "x",
                        "required_completion_class": "COMPLETE_ARTIFACT",
                    },
                ]
            )

    def test_formal_registry_cannot_register_cp0(self) -> None:
        registry = goal_registry_rules.GoalRegistry(disposable=False)
        with self.assertRaises(goal_registry_rules.GoalRegistryError):
            registry.initialize(
                [
                    {
                        "goal_id": "D0-control-plane-self-test",
                        "objective": "self-test",
                        "required_completion_class": "COMPLETE_ARTIFACT",
                    },
                ]
            )

    def test_migration_requires_safe_point(self) -> None:
        registry = goal_registry_rules.GoalRegistry(disposable=False)
        registry.initialize(
            [
                {
                    "goal_id": "G0",
                    "objective": "x",
                    "required_completion_class": "COMPLETE_ARTIFACT",
                },
            ]
        )
        migration = goal_registry_rules.build_migration(
            kind="REGISTER",
            source_value="",
            target_value="G1",
            target_goal={
                "goal_id": "G1",
                "objective": "y",
                "required_completion_class": "COMPLETE_ARTIFACT",
            },
        )
        with self.assertRaises(goal_registry_rules.GoalRegistryError):
            registry.apply_migration(migration, current_status="RUNNING")
        registry.apply_migration(migration, current_status="PAUSED")
        self.assertIn("G1", registry.goals)

    def test_self_dependency_rejected(self) -> None:
        registry = goal_registry_rules.GoalRegistry(disposable=False)
        with self.assertRaises(goal_registry_rules.GoalRegistryError):
            registry.initialize(
                [
                    {
                        "goal_id": "G0",
                        "objective": "x",
                        "required_completion_class": "COMPLETE_ARTIFACT",
                        "depends_on": ["G0"],
                    },
                ]
            )

    def test_retire_migration(self) -> None:
        registry = goal_registry_rules.GoalRegistry(disposable=False)
        registry.initialize(
            [
                {
                    "goal_id": "G0",
                    "objective": "x",
                    "required_completion_class": "COMPLETE_ARTIFACT",
                },
            ]
        )
        migration = goal_registry_rules.build_migration(
            kind="RETIRE",
            source_value="G0",
            target_value="",
            target_goal={},
        )
        registry.apply_migration(migration, current_status="PAUSED")
        self.assertNotIn("G0", registry.goals)

    def test_renumber_migration_rewires_dependencies(self) -> None:
        registry = goal_registry_rules.GoalRegistry(disposable=False)
        registry.initialize(
            [
                {
                    "goal_id": "G0",
                    "objective": "x",
                    "required_completion_class": "COMPLETE_ARTIFACT",
                },
                {
                    "goal_id": "G1",
                    "objective": "y",
                    "required_completion_class": "COMPLETE_ARTIFACT",
                    "depends_on": ["G0"],
                },
            ]
        )
        migration = goal_registry_rules.build_migration(
            kind="RENUMBER",
            source_value="G0",
            target_value="G0-renamed",
            target_goal={},
        )
        registry.apply_migration(migration, current_status="INITIALIZING")
        self.assertNotIn("G0", registry.goals)
        self.assertIn("G0-renamed", registry.goals)
        self.assertEqual(registry.goals["G1"].depends_on, ("G0-renamed",))

    def test_migration_kind_validation(self) -> None:
        with self.assertRaises(goal_registry_rules.GoalRegistryError):
            goal_registry_rules.build_migration(
                kind="BOGUS",
                source_value="",
                target_value="",
                target_goal={},
            )

    def test_formal_registry_cap_rejected(self) -> None:
        registry = goal_registry_rules.GoalRegistry(disposable=False)
        goals = [
            {
                "goal_id": f"G{i}",
                "objective": "x",
                "required_completion_class": "COMPLETE_ARTIFACT",
            }
            for i in range(goal_registry_rules.FORMAL_REGISTRY_GOAL_CAP + 1)
        ]
        with self.assertRaises(goal_registry_rules.GoalRegistryError):
            registry.initialize(goals)

    def test_dependency_on_missing_goal_rejected(self) -> None:
        registry = goal_registry_rules.GoalRegistry(disposable=False)
        with self.assertRaises(goal_registry_rules.GoalRegistryError):
            registry.initialize(
                [
                    {
                        "goal_id": "G0",
                        "objective": "x",
                        "required_completion_class": "COMPLETE_ARTIFACT",
                        "depends_on": ["G-missing"],
                    },
                ]
            )


class RecoveryCoverageCheckTests(unittest.TestCase):
    @staticmethod
    def _descriptor(operation: str = "REPORT_RECOVERY") -> dict:
        return {
            "classification": "RECOVERABLE",
            "operation": operation,
            "next_operation": {"operation": operation},
        }

    def _check(self, document: object, expected: set[str]) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with mock.patch.object(
                recovery_coverage_check.build_recovery_registry,
                "extract_codes",
                return_value=expected,
            ):
                return recovery_coverage_check.check(path)

    def test_complete_registry(self) -> None:
        result = self._check({"entries": {"A": self._descriptor()}}, {"A"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "RECOVERY_COVERAGE_COMPLETE")

    def test_missing_stale_and_non_object_descriptors(self) -> None:
        result = self._check(
            {
                "entries": {
                    "B": "not-an-object",
                    "STALE": self._descriptor(),
                }
            },
            {"A", "B"},
        )
        self.assertFalse(result["ok"])
        self.assertIn("missing:A", result["failures"])
        self.assertIn("stale:STALE", result["failures"])
        self.assertIn("B:descriptor-not-object", result["failures"])

    def test_invalid_and_wait_only_recoveries(self) -> None:
        invalid = (
            {**self._descriptor(), "classification": "UNKNOWN"},
            self._descriptor("WAIT"),
            {**self._descriptor(), "next_operation": []},
            {**self._descriptor(), "next_operation": {"operation": "OTHER"}},
            {**self._descriptor(), "operation": ""},
        )
        for descriptor in invalid:
            with self.subTest(descriptor=descriptor):
                result = self._check({"entries": {"A": descriptor}}, {"A"})
                self.assertEqual(
                    result["failures"], ["A:invalid-or-wait-only-recovery"]
                )

    def test_missing_bad_json_and_bad_entries_are_controlled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            with mock.patch.object(
                recovery_coverage_check.build_recovery_registry,
                "extract_codes",
                return_value=set(),
            ):
                missing = recovery_coverage_check.check(path)
                path.write_text("{bad json", encoding="utf-8")
                malformed = recovery_coverage_check.check(path)
        self.assertEqual(missing["status"], "RECOVERY_COVERAGE_REGISTRY_INVALID")
        self.assertEqual(malformed["status"], "RECOVERY_COVERAGE_REGISTRY_INVALID")
        for document in ([], {"entries": []}):
            with self.subTest(document=document):
                result = self._check(document, set())
                self.assertFalse(result["ok"])

    def test_main_emits_json_and_text_with_exit_status(self) -> None:
        complete = {"ok": True, "status": "RECOVERY_COVERAGE_COMPLETE"}
        incomplete = {"ok": False, "status": "RECOVERY_COVERAGE_INCOMPLETE"}
        with mock.patch.object(
            recovery_coverage_check, "check", return_value=complete
        ), mock.patch.object(
            sys, "argv", ["recovery_coverage_check.py", "--json"]
        ), mock.patch(
            "sys.stdout", new_callable=io.StringIO
        ) as output:
            self.assertEqual(recovery_coverage_check.main(), 0)
            self.assertTrue(json.loads(output.getvalue())["ok"])
        with mock.patch.object(
            recovery_coverage_check, "check", return_value=incomplete
        ), mock.patch.object(
            sys, "argv", ["recovery_coverage_check.py", "--check"]
        ), mock.patch(
            "sys.stdout", new_callable=io.StringIO
        ) as output:
            self.assertEqual(recovery_coverage_check.main(), 1)
            self.assertEqual(output.getvalue().strip(), "RECOVERY_COVERAGE_INCOMPLETE")
        with mock.patch.object(
            sys, "argv", ["recovery_coverage_check.py", "--check"]
        ), mock.patch(
            "sys.stdout", new_callable=io.StringIO
        ) as output:
            with self.assertRaises(SystemExit) as exit_context:
                runpy.run_path(
                    str(SCRIPTS / "recovery_coverage_check.py"), run_name="__main__"
                )
            self.assertEqual(exit_context.exception.code, 0)
            self.assertEqual(output.getvalue().strip(), "RECOVERY_COVERAGE_COMPLETE")
