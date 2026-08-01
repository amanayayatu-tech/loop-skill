from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "codex-loop-prompt-architect" / "scripts"
ENTRY = SCRIPTS / "loopskill4"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from loop_architect.v4_alpha.protocol import (  # noqa: E402
    CAPACITY_CONTRACT,
    CAPABILITY_NAMES,
    InjectedCrash,
    LoopIntakeInput,
    Receipt,
    canonical_bytes,
    domain_digest,
    result_payload_schema,
)
from loop_architect.v4_adapters.codex.adapter import HOST_SCHEMA_VERSION  # noqa: E402
from loop_architect.v4_entry import (  # noqa: E402
    EntryError,
    confirm_loop,
    control_loop,
    diagnostics,
    extend_budget,
    intake_report_loop,
    prepare_loop,
    policy_view,
    record_external_observation,
    revise_goal_plan,
    satisfy_gate,
    start_loop,
    steer_loop,
    status,
    sync_loop,
    worker_profile,
)
from loop_architect.v4_entry.preparation import (  # noqa: E402
    CONFIRMATION_FILENAME,
    boundary_display,
    load_prepared,
)
from loop_architect.v4_entry.service import STORE_FILENAME, _machine_bootstrap  # noqa: E402
from loop_architect.v4_persistence.sqlite_store import SQLiteStore  # noqa: E402
from loop_architect.v4_persistence.sqlite_store import PersistenceCorruption  # noqa: E402
from loop_architect.v4_persistence.sqlite_store import DURABLE_FAULT_BOUNDARIES  # noqa: E402


NOW = datetime(2026, 7, 27, 1, 0, 0, tzinfo=timezone.utc)


class EntryProviderFixture:
    def __init__(
        self,
        *,
        now=None,
        result_status="COMPLETED",
        result_payload=None,
        lifecycle_state="TERMINAL",
        budget_reason=None,
    ):
        self.invoke_count = 0
        self.result_read_count = 0
        self.records = {}
        self.now = now
        self.result_status = result_status
        self.result_payload = result_payload
        self.lifecycle_state = lifecycle_state
        self.budget_reason = budget_reason

    def budget_block_reason(self, payload):
        del payload
        return self.budget_reason

    def capability_snapshot(self):
        now = self.now or datetime.now(timezone.utc)
        rows = []
        for name in CAPABILITY_NAMES:
            rows.append(
                {
                    "assurance": "STRICT",
                    "availability": "AVAILABLE",
                    "details": {
                        "expires_at": (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
                        "identity_ref": f"synthetic-{name}",
                        "issuer_ref": "loopskill-codex-adapter-v1",
                        "issuer_trust": "local-codex-adapter",
                        "observed_at": (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
                        "source": "synthetic-entry-provider",
                    },
                    "name": name,
                    "receipt_ref": f"synthetic-capability-{name}",
                }
            )
        return {"capabilities": rows, "schema_version": HOST_SCHEMA_VERSION}

    def invoke(self, action, payload, provider_idempotency_key):
        self.invoke_count += 1
        self.records[provider_idempotency_key] = {
            "action": action,
            "idempotency_key": provider_idempotency_key,
            "provider_id": "synthetic-entry-thread",
            "schema_version": HOST_SCHEMA_VERSION,
            "status": "OBSERVED",
            "subject_id": payload["target_ref"],
            "trust": "authoritative",
        }
        return {**self.records[provider_idempotency_key], "status": "ACCEPTED", "trust": "cooperative"}

    def readback(self, action, provider_idempotency_key):
        return self.records.get(provider_idempotency_key)

    def read_resource(self, resource_kind, provider_id):
        return {
            "provider_id": provider_id,
            "resource_kind": resource_kind,
            "schema_version": HOST_SCHEMA_VERSION,
            "state": self.lifecycle_state,
            "trust": "authoritative",
        }

    def read_task_result(self, provider_id):
        self.result_read_count += 1
        result = self.result_payload
        if result is None:
            result = {"outcome": "PASS", "summary": "synthetic task completed"}
        schema_digest = domain_digest(
            "loopskill-codex-result-schema-v1\n", result_payload_schema()
        )
        return {
            "provider_id": provider_id,
            "result": result,
            "result_digest": domain_digest(
                "loopskill-host-result-v1\n",
                {"result": result, "result_schema_digest": schema_digest},
            ),
            "result_schema_digest": schema_digest,
            "schema_version": HOST_SCHEMA_VERSION,
            "status": self.result_status,
            "trust": "authoritative",
        }


def fixed_tokens():
    values = iter(
        (
            "000000000000000000000001",
            "000000000000000000000002",
            "000000000000000000000003",
            "000000000000000000000004",
            "000000000000000000000005",
            "000000000000000000000006",
            "000000000000000000000007",
        )
    )
    return lambda: next(values)


def ready_request(goal="Ship a bounded public change", *, horizon="long"):
    return LoopIntakeInput(
        goal=goal,
        goal_plan=(goal,),
        task_horizon=horizon,
        write_scope=("synthetic-workspace",),
        budget="10 minutes; 1 Host create attempt",
        external_actions=(),
        acceptance_criteria=("no-file-change",),
        stop_conditions=("stop on UNKNOWN",),
        authorization_boundaries=("no commit, push, publish, or deploy",),
    )


def v2_request(goals, *, requirements=None):
    """Build one closed PlanDocument v2 intake for long-horizon regressions."""

    first = goals[0]["objective"]
    plan = {
        "boundaries": {
            "destructive_actions_allowed": False,
            "external_actions": [],
            "forbidden_actions": ["no publish"],
            "forbidden_paths": [],
            "write_scope": ["."],
        },
        "budget": {
            "currency": None,
            "max_cost_minor_units": 0,
            "max_host_invocations": sum(
                goal["max_attempts"] for goal in goals if goal["gate"] == "worker"
            )
            or 1,
            "wall_clock_seconds": 3600,
        },
        "completion_evidence": ["all required Goals independently verified"],
        "goals": goals,
        "objective": first,
        "requirements": requirements or {},
        "roadmap_policy": {"max_reorders": 0, "mode": "STANDARD"},
        "schema": "loopskill-plan-v2",
        "source": {
            "kind": "canonical_plan_json",
            "source_content_retained": False,
            "source_digest": "a" * 64,
        },
        "stop_conditions": ["wait on a repeated failure fingerprint"],
        "worker_profile": {
            "attempt_timeout_seconds": 30_000,
            "local_verification": True,
            "model": "gpt-5.6-sol",
            "network_access": True,
            "reasoning_effort": "medium",
            "sandbox": "workspace-write",
        },
    }
    return LoopIntakeInput(
        goal=first,
        goal_plan=tuple(goal["objective"] for goal in goals),
        task_horizon="long",
        write_scope=(".",),
        budget=json.dumps(plan["budget"], sort_keys=True),
        external_actions=(),
        acceptance_criteria=("all required Goals independently verified",),
        stop_conditions=("wait on a repeated failure fingerprint",),
        authorization_boundaries=("no publish",),
        canonical_plan=plan,
        source_kind="canonical_plan_json",
        source_digest="a" * 64,
        source_bytes=len(canonical_bytes(plan)),
    )


def v2_goal(
    goal_id,
    objective,
    *,
    requirement="required",
    capabilities=(),
    verifiers=("no-file-change",),
    gate="worker",
    on_failure="repair",
    on_blocked="wait",
    recovery_policy="resume",
    replay_safety="file_local",
    max_attempts=3,
):
    return {
        "acceptance_criteria": list(verifiers) or ["bound controller gate"],
        "capabilities": list(capabilities),
        "gate": gate,
        "goal_id": goal_id,
        "max_attempts": max_attempts,
        "objective": objective,
        "on_blocked": on_blocked,
        "on_failure": on_failure,
        "recovery_policy": recovery_policy,
        "replay_safety": replay_safety,
        "requirement": requirement,
        "requirement_refs": [],
        "verifiers": list(verifiers),
    }


def prepare_confirm(
    root,
    goal="Ship a bounded public change",
    *,
    token="000000000000000000000001",
    goal_plan=None,
):
    workspace = Path(root) / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    request = ready_request(goal)
    if goal_plan is not None:
        request = replace(request, goal_plan=tuple(goal_plan))
    prepared = prepare_loop(
        request,
        Path(root) / "prepared",
        clock=lambda: NOW,
        token_factory=lambda: token,
        workspace_root=workspace,
    )
    return confirm_loop(prepared.directory, confirmed=True, clock=lambda: NOW)


def load_cli_module():
    loader = importlib.machinery.SourceFileLoader("loopskill4_test_cli", str(ENTRY))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class V4SingleEntryUXTests(unittest.TestCase):
    def test_v2_optional_capability_skip_advances_and_finishes_with_limitations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            request = v2_request(
                [
                    v2_goal(
                        "g000",
                        "Attempt one optional unavailable integration",
                        requirement="optional",
                        capabilities=("unavailable-image-provider",),
                        on_blocked="skip",
                    ),
                    v2_goal("g001", "Complete the required local stage"),
                ]
            )
            prepared = root / "prepared"
            prepare_loop(
                request,
                prepared,
                clock=lambda: NOW,
                token_factory=lambda: "100000000000000000000001",
                workspace_root=workspace,
            )
            confirm_loop(prepared, confirmed=True, clock=lambda: NOW)
            provider = EntryProviderFixture(now=NOW)
            data = root / "data"
            started = start_loop(
                prepared,
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=workspace,
            )
            self.assertEqual(started.progress, "Starting")
            self.assertEqual(provider.invoke_count, 0)
            closed = sync_loop(
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=workspace,
            )
            self.assertEqual(closed.progress, "Finished")
            self.assertEqual(closed.result, "SUCCEEDED_WITH_LIMITATIONS")
            self.assertEqual(provider.invoke_count, 1)
            with SQLiteStore(data / STORE_FILENAME) as store:
                snapshot = store.snapshot(store.loop_descriptors()[0]["loop_ref"])
                self.assertEqual(
                    {goal["state"] for goal in snapshot["goals"].values()},
                    {"DONE", "SKIPPED"},
                )

    def test_v2_human_gate_waits_without_host_then_accepts_bound_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            request = v2_request(
                [
                    v2_goal(
                        "g000",
                        "Wait for one exact human approval",
                        verifiers=("human-approval",),
                        gate="human",
                        recovery_policy="human",
                        replay_safety="non_replayable",
                    )
                ]
            )
            prepared = root / "prepared"
            prepare_loop(
                request,
                prepared,
                clock=lambda: NOW,
                token_factory=lambda: "100000000000000000000002",
                workspace_root=workspace,
            )
            confirm_loop(prepared, confirmed=True, clock=lambda: NOW)
            provider = EntryProviderFixture(now=NOW)
            data = root / "data"
            waiting = start_loop(
                prepared,
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=workspace,
            )
            self.assertEqual(waiting.result, "WAITING_HUMAN")
            self.assertEqual(provider.invoke_count, 0)
            closed = satisfy_gate(
                root=data,
                workspace_root=workspace,
                approval_digest="b" * 64,
                clock=lambda: NOW,
            )
            self.assertEqual(closed.result, "SUCCEEDED")
            self.assertEqual(provider.invoke_count, 0)

    def test_v2_failure_wait_policy_pauses_instead_of_terminalizing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            request = v2_request(
                [
                    v2_goal(
                        "g000",
                        "Pause safely when the worker reports a failure",
                        on_failure="wait",
                    )
                ]
            )
            prepared = root / "prepared"
            prepare_loop(
                request,
                prepared,
                clock=lambda: NOW,
                token_factory=lambda: "100000000000000000000003",
                workspace_root=workspace,
            )
            confirm_loop(prepared, confirmed=True, clock=lambda: NOW)
            provider = EntryProviderFixture(
                now=NOW,
                result_payload={"outcome": "FAILED", "summary": "synthetic failure"},
            )
            data = root / "data"
            start_loop(
                prepared,
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=workspace,
            )
            waiting = sync_loop(
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=workspace,
            )
            self.assertEqual(waiting.progress, "Waiting")
            self.assertEqual(waiting.result, "WAITING")
            with SQLiteStore(data / STORE_FILENAME) as store:
                snapshot = store.snapshot(store.loop_descriptors()[0]["loop_ref"])
                self.assertEqual(snapshot["execution"]["state"], "PAUSED")
                self.assertEqual(snapshot["execution"]["wait_kind"], "FAILURE")
                self.assertEqual(
                    next(iter(snapshot["goals"].values()))["state"], "ACTIVE"
                )

    def test_v2_budget_exhaustion_enters_distinct_recoverable_wait(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            request = v2_request(
                [v2_goal("g000", "Wait for a digest-bound budget extension")]
            )
            prepared = root / "prepared"
            prepare_loop(
                request,
                prepared,
                clock=lambda: NOW,
                token_factory=lambda: "100000000000000000000007",
                workspace_root=workspace,
            )
            confirm_loop(prepared, confirmed=True, clock=lambda: NOW)
            provider = EntryProviderFixture(
                now=NOW,
                result_payload={
                    "outcome": "LIMITATION",
                    "summary": "The Plan-bound Host invocation budget is exhausted.",
                },
            )
            data = root / "data"
            start_loop(
                prepared,
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=workspace,
            )
            waiting = sync_loop(
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=workspace,
            )
            self.assertEqual(waiting.progress, "Waiting")
            self.assertEqual(waiting.result, "WAITING_BUDGET")
            with SQLiteStore(data / STORE_FILENAME) as store:
                snapshot = store.snapshot(store.loop_descriptors()[0]["loop_ref"])
                self.assertEqual(snapshot["execution"]["state"], "PAUSED")
                self.assertEqual(snapshot["execution"]["wait_kind"], "BUDGET")

    def test_v2_budget_preflight_extends_and_resumes_without_a_blocked_host_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            request = v2_request(
                [v2_goal("g000", "Resume after a bound runtime budget extension")]
            )
            prepared = root / "prepared"
            prepare_loop(
                request,
                prepared,
                clock=lambda: NOW,
                token_factory=lambda: "100000000000000000000008",
                workspace_root=workspace,
            )
            confirm_loop(prepared, confirmed=True, clock=lambda: NOW)
            provider = EntryProviderFixture(
                now=NOW,
                budget_reason="The Plan-bound Host invocation budget is exhausted.",
            )
            data = root / "data"
            waiting = start_loop(
                prepared,
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=workspace,
            )
            self.assertEqual(waiting.result, "WAITING_BUDGET")
            self.assertEqual(provider.invoke_count, 0)
            with self.assertRaises(EntryError):
                control_loop("resume", root=data, clock=lambda: NOW)
            with self.assertRaises(EntryError):
                extend_budget(
                    root=data,
                    new_max_host_invocations=True,
                    new_wall_clock_seconds=7200,
                    reason="invalid boolean budget",
                    clock=lambda: NOW,
                )
            with self.assertRaises(EntryError):
                extend_budget(
                    root=data,
                    new_max_host_invocations=3,
                    new_wall_clock_seconds=3600,
                    reason="unchanged budgets cannot resume a wait",
                    clock=lambda: NOW,
                )
            with self.assertRaises(EntryError):
                extend_budget(
                    root=data,
                    new_max_host_invocations=385,
                    new_wall_clock_seconds=7200,
                    reason="bounded budgets reject oversized requests",
                    clock=lambda: NOW,
                )

            active = extend_budget(
                root=data,
                new_max_host_invocations=4,
                new_wall_clock_seconds=7200,
                reason="Continue the unchanged confirmed Goal.",
                clock=lambda: NOW,
            )
            self.assertIn(active.progress, {"Active", "Starting"})
            profile = worker_profile(root=data)
            self.assertEqual(
                profile["budget_override"],
                {"max_host_invocations": 4, "wall_clock_seconds": 7200},
            )
            provider.budget_reason = None
            closed = sync_loop(
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=workspace,
            )
            self.assertEqual(closed.result, "SUCCEEDED")
            self.assertEqual(provider.invoke_count, 1)
            with SQLiteStore(data / STORE_FILENAME) as store:
                loop_ref = store.loop_descriptors()[0]["loop_ref"]
                events = [event["type"] for event in store.events(loop_ref)]
                self.assertIn("BudgetWaiting", events)
                self.assertIn("BudgetExtended", events)

    def test_v2_repair_stays_in_same_loop_and_can_succeed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            request = v2_request(
                [v2_goal("g000", "Repair one failed worker result in place")]
            )
            prepared = root / "prepared"
            prepare_loop(
                request,
                prepared,
                clock=lambda: NOW,
                token_factory=lambda: "100000000000000000000004",
                workspace_root=workspace,
            )
            confirm_loop(prepared, confirmed=True, clock=lambda: NOW)
            provider = EntryProviderFixture(
                now=NOW,
                result_payload={"outcome": "FAILED", "summary": "first failure"},
            )
            data = root / "data"
            start_loop(
                prepared,
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=workspace,
            )
            repairing = sync_loop(
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=workspace,
            )
            self.assertEqual(repairing.result, "Repair scheduled")
            provider.result_payload = {
                "outcome": "PASS",
                "summary": "repair completed",
            }
            closed = sync_loop(
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=workspace,
            )
            self.assertEqual(closed.result, "SUCCEEDED")
            self.assertEqual(provider.invoke_count, 2)
            with SQLiteStore(data / STORE_FILENAME) as store:
                self.assertEqual(len(store.loop_descriptors()), 1)

    def test_v2_repeated_repair_fingerprint_waits_after_second_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            request = v2_request(
                [v2_goal("g000", "Stop mechanical retries for one repeated failure")]
            )
            prepared = root / "prepared"
            prepare_loop(
                request,
                prepared,
                clock=lambda: NOW,
                token_factory=lambda: "100000000000000000000005",
                workspace_root=workspace,
            )
            confirm_loop(prepared, confirmed=True, clock=lambda: NOW)
            provider = EntryProviderFixture(
                now=NOW,
                result_payload={"outcome": "FAILED", "summary": "same failure"},
            )
            data = root / "data"
            start_loop(
                prepared,
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=workspace,
            )
            sync_loop(
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=workspace,
            )
            waiting = sync_loop(
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=workspace,
            )
            self.assertEqual(waiting.result, "WAITING_REPAIR")
            self.assertEqual(provider.invoke_count, 2)

    def test_v2_time_gate_uses_real_clock_and_never_calls_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            threshold = (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
            request = v2_request(
                [
                    v2_goal(
                        "g000",
                        "Wait for the declared real time",
                        verifiers=("time-after:" + threshold,),
                        gate="time",
                        recovery_policy="human",
                    )
                ]
            )
            prepared = root / "prepared"
            prepare_loop(
                request,
                prepared,
                clock=lambda: NOW,
                token_factory=lambda: "100000000000000000000006",
                workspace_root=workspace,
            )
            confirm_loop(prepared, confirmed=True, clock=lambda: NOW)
            provider = EntryProviderFixture(now=NOW)
            data = root / "data"
            waiting = start_loop(
                prepared,
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=workspace,
            )
            self.assertEqual(waiting.result, "WAITING_TIME")
            still_waiting = satisfy_gate(
                root=data,
                workspace_root=workspace,
                clock=lambda: NOW,
            )
            self.assertEqual(still_waiting.result, "WAITING_TIME")
            closed = satisfy_gate(
                root=data,
                workspace_root=workspace,
                clock=lambda: NOW + timedelta(hours=2),
            )
            self.assertEqual(closed.result, "SUCCEEDED")
            self.assertEqual(provider.invoke_count, 0)

    def test_public_cli_discovers_and_requires_selection_for_multiple_loops(self):
        cli = load_cli_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "store-root"
            loop_refs = []
            for ordinal in range(2):
                prepared = prepare_confirm(
                    root / f"case-{ordinal}",
                    goal=f"Keep loop {ordinal} independently selectable",
                    token=f"20000000000000000000000{ordinal}",
                )
                loop_ref = prepared.manifest.loop_ref
                loop_refs.append(loop_ref)
                start_loop(
                    prepared.directory,
                    root=base / "loops" / loop_ref,
                    clock=lambda: NOW,
                    workspace_root=root / f"case-{ordinal}" / "workspace",
                )

            discovered = cli._discover_loops(base)
            self.assertEqual(
                [item["loop_ref"] for item in discovered], sorted(loop_refs)
            )
            with self.assertRaises(EntryError) as ambiguous:
                cli._selected_loop_root(base, None)
            self.assertEqual(ambiguous.exception.code, "USER_STORE_UNAVAILABLE")
            selected = cli._selected_loop_root(base, loop_refs[1])
            self.assertEqual(selected, base / "loops" / loop_refs[1])

    def test_public_cli_preserves_literal_suffix_and_explicit_path_intent(self):
        cli = load_cli_module()
        literal_requests = (
            "Create and verify release-checklist.md",
            "Create and verify release-checklist.txt",
            "Create and verify release-checklist.json",
            "请创建并验证release-checklist.md",
            "请创建并验证release-checklist.txt",
            "请创建并验证release-checklist.json",
        )
        for request in literal_requests:
            with self.subTest(request=request):
                admitted = cli.read_intake_input(request)
                self.assertEqual(admitted.goal, request)
                self.assertEqual(admitted.source_kind, "literal_text")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = {
                "bare.md": "bare file",
                "with space.txt": "spaced file",
                "需求说明.md": "Unicode file",
            }
            for name, content in sources.items():
                (root / name).write_text(content, encoding="utf-8")
            with contextlib.chdir(root):
                for name, content in sources.items():
                    with self.subTest(source=name):
                        admitted = cli.read_intake_input(name)
                        self.assertEqual(admitted.goal, content)
                        self.assertEqual(admitted.source_kind, "authorized_file")
                with self.assertRaises(EntryError) as missing:
                    cli.read_intake_input("./requirements.md")
                self.assertEqual(missing.exception.code, "USER_INPUT_INVALID")

    def test_public_cli_input_decoding_doctor_and_confirmation_edges(self):
        cli = load_cli_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(cli.read_intake_input("literal goal").goal, "literal goal")

            text = root / "goal.txt"
            text.write_text("UTF-8 goal", encoding="utf-8")
            self.assertEqual(cli.read_intake_input(str(text)).goal, "UTF-8 goal")

            document = root / "goal.json"
            document.write_text(
                json.dumps(
                    {
                        "goal": "JSON goal",
                        "goal_plan": ["first", "second"],
                        "task_horizon": "long",
                    }
                ),
                encoding="utf-8",
            )
            decoded = cli.read_intake_input(str(document))
            self.assertEqual(decoded.goal_plan, ("first", "second"))

            invalid_json = root / "invalid.json"
            invalid_json.write_text("{", encoding="utf-8")
            invalid_utf8 = root / "invalid.txt"
            invalid_utf8.write_bytes(b"\xff")
            oversized = root / "oversized.txt"
            oversized.write_bytes(
                b"g" * (int(CAPACITY_CONTRACT["source_text_max_bytes"]) + 1)
            )
            invalid_list = root / "invalid-list.json"
            invalid_list.write_text(
                json.dumps({"goal": "goal", "write_scope": [1]}),
                encoding="utf-8",
            )
            invalid_scalar = root / "invalid-scalar.json"
            invalid_scalar.write_text(
                json.dumps({"goal": 1}), encoding="utf-8"
            )
            unknown_field = root / "unknown.json"
            unknown_field.write_text(
                json.dumps({"goal": "goal", "thread_id": "model-copy"}),
                encoding="utf-8",
            )
            for source, expected_code in (
                (invalid_json, "USER_INPUT_INVALID"),
                (invalid_utf8, "USER_INPUT_INVALID"),
                (oversized, "RESOURCE_LIMIT_EXCEEDED"),
                (invalid_list, "USER_INPUT_INVALID"),
                (invalid_scalar, "USER_INPUT_INVALID"),
                (unknown_field, "USER_INPUT_INVALID"),
                (root / "missing.json", "USER_INPUT_INVALID"),
            ):
                with self.subTest(source=source.name), self.assertRaises(EntryError) as caught:
                    cli.read_intake_input(str(source))
                self.assertEqual(caught.exception.code, expected_code)

            with mock.patch.dict(os.environ, {"CODEX_HOME": str(root / "codex")}, clear=False):
                view = cli._doctor_view(include_diagnostics=False)
            self.assertIn("status", view)
            receipt_root = root / "codex" / "install-receipts" / "loopskill4"
            receipt_root.mkdir(parents=True)
            (receipt_root / "active-receipt").write_text("{", encoding="utf-8")
            with mock.patch.dict(os.environ, {"CODEX_HOME": str(root / "codex")}, clear=False):
                diagnostic = cli._doctor_view(include_diagnostics=True)
            self.assertEqual(diagnostic["status"], "BLOCKED")
            self.assertEqual(
                diagnostic["diagnostics"]["capabilities"]["install_receipt"],
                "UNVERIFIABLE",
            )

            args = SimpleNamespace(
                goal_file_or_prepared_directory="one-off",
                prepared_output=root / "prepared-direct",
                root=root / "data-direct",
            )
            direct_report = {
                "1 最终判定": {
                    "disposition": "DIRECT_TASK_RECOMMENDED",
                    "reason": "Run directly.",
                }
            }
            with mock.patch.object(cli, "read_intake_input", return_value=object()), mock.patch.object(
                cli, "intake_report_loop", return_value=direct_report
            ), mock.patch.object(cli, "print_intake_report"):
                with self.assertRaises(EntryError) as caught:
                    cli._interactive_start(args)
            self.assertEqual(caught.exception.code, "USER_DIRECT_TASK_RECOMMENDED")

            clarification = {
                "1 最终判定": {
                    "disposition": "NEEDS_CLARIFICATION",
                    "reason": "Clarify boundary.",
                }
            }
            with mock.patch.object(cli, "read_intake_input", return_value=object()), mock.patch.object(
                cli, "intake_report_loop", return_value=clarification
            ), mock.patch.object(cli, "print_intake_report"):
                with self.assertRaises(EntryError) as caught:
                    cli._interactive_start(args)
            self.assertEqual(caught.exception.code, "USER_CLARIFICATION_REQUIRED")

    def test_public_cli_dispatches_every_v4_action_without_hidden_control_input(self):
        cli = load_cli_module()
        visible = SimpleNamespace(
            goal="Visible semantic goal",
            progress="Active",
            result="Pending",
            limitations=(),
            next_actions=("Wait for readback.",),
        )

        def invoke(arguments):
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = cli.main(arguments)
            return code, stdout.getvalue(), stderr.getvalue()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = SimpleNamespace(
                bundle=SimpleNamespace(
                    boundary_digest="b" * 64,
                    manifest_digest="m" * 64,
                )
            )
            report = {"1 最终判定": {"disposition": "READY_FOR_LOOP"}}
            with mock.patch.object(cli, "read_intake_input", return_value=object()), mock.patch.object(
                cli, "intake_report_loop", return_value=report
            ), mock.patch.object(cli, "print_intake_report") as printed:
                self.assertEqual(invoke(["intake", "goal"])[0], 0)
                printed.assert_called_once_with(report)
            with mock.patch.object(cli, "read_intake_input", return_value=object()), mock.patch.object(
                cli, "prepare_loop", return_value=prepared
            ), mock.patch.object(cli, "print_boundary") as boundary:
                self.assertEqual(
                    invoke(["prepare", "goal", "--output", str(root / "prepared")])[0],
                    0,
                )
                boundary.assert_called_once_with(prepared)
            with mock.patch.object(cli, "review_prepared", return_value=prepared):
                code, output, _ = invoke(["compile", str(root / "prepared")])
                self.assertEqual(code, 0)
                self.assertIn('"status":"PREPARED_VALID"', output)
            with mock.patch.object(cli, "_doctor_view", return_value={"status": "READY"}):
                code, output, _ = invoke(["doctor", "--diagnostics"])
                self.assertEqual(code, 0)
                self.assertIn('"status":"READY"', output)
            canary_receipt = {
                "artifact": "loopskill-v4-disposable-codex-exec-canary-v1",
                "status": "PASS",
            }
            with mock.patch.object(
                cli, "_interactive_canary", return_value=canary_receipt
            ) as canary_entry:
                code, output, _ = invoke(
                    [
                        "canary",
                        "--candidate",
                        "a" * 40,
                        "--candidate-root",
                        str(ROOT),
                        "--evidence-root",
                        str(root / "canary"),
                    ]
                )
                self.assertEqual(code, 0)
                self.assertIn('"status":"PASS"', output)
                canary_entry.assert_called_once()
            with mock.patch.object(cli, "policy_view", return_value={"policy": "STANDARD"}):
                self.assertEqual(invoke(["policy", "--root", str(root)])[0], 0)
            with mock.patch.object(
                cli, "revise_goal_plan", return_value={"revision": 2}
            ) as revised:
                self.assertEqual(
                    invoke(
                        [
                            "roadmap-revise",
                            "Goal one",
                            "Goal two",
                            "--reason",
                            "Bounded reorder",
                            "--root",
                            str(root),
                        ]
                    )[0],
                    0,
                )
                revised.assert_called_once()
            with mock.patch.object(cli, "_interactive_start", return_value=visible):
                self.assertEqual(invoke(["start", "goal", "--root", str(root)])[0], 0)
            for action in ("pause", "resume", "stop"):
                with self.subTest(action=action), mock.patch.object(
                    cli, "control_loop", return_value=visible
                ) as controlled:
                    self.assertEqual(invoke([action, "--root", str(root)])[0], 0)
                    controlled.assert_called_once()
            with mock.patch.object(cli, "steer_loop", return_value=visible) as steered:
                self.assertEqual(
                    invoke(
                        [
                            "steer",
                            "wait",
                            "--failure-fingerprint",
                            "same-failure",
                            "--root",
                            str(root),
                        ]
                    )[0],
                    0,
                )
                steered.assert_called_once()
            with mock.patch.object(cli, "status", return_value=visible):
                self.assertEqual(invoke(["status", "--root", str(root)])[0], 0)
            with mock.patch.object(
                cli, "_refresh_with_owned_provider", return_value=visible
            ) as refreshed, mock.patch.object(
                cli, "diagnostics", return_value={"internal": "opt-in"}
            ):
                code, output, _ = invoke(
                    ["status", "--refresh", "--diagnostics", "--root", str(root)]
                )
                self.assertEqual(code, 0)
                self.assertIn("Diagnostics:", output)
                refreshed.assert_called_once_with(root=root)
            with mock.patch.object(
                cli,
                "status",
                side_effect=EntryError(
                    "USER_STORE_UNAVAILABLE", "Stable error.", "Choose another root."
                ),
            ):
                code, _, error = invoke(["status", "--root", str(root)])
                self.assertEqual(code, 2)
                self.assertIn("USER_STORE_UNAVAILABLE", error)
                self.assertNotIn("loop-", error)
            with mock.patch.object(cli, "status", side_effect=RuntimeError("private")):
                code, _, error = invoke(["status", "--root", str(root)])
                self.assertEqual(code, 70)
                self.assertIn("USER_INTERNAL_ERROR", error)
                self.assertNotIn("private", error)
                self.assertIn("do not repeat start blindly", error)
                self.assertNotIn("Retry once", error)

    def test_installed_skill_is_v4_only_and_preserves_four_phase_boundary(self) -> None:
        skill = (ROOT / "codex-loop-prompt-architect/SKILL.md").read_text(
            encoding="utf-8"
        )
        for phase in ("INTAKE", "PREPARE", "CONFIRM", "START"):
            self.assertIn(phase, skill)
        self.assertIn("never supply or become", skill)
        self.assertIn("cannot open, import, repair, or run LoopSkill 3", skill)
        self.assertNotIn("Legacy v3 Mandatory First-Invocation Doctor", skill)
        self.assertNotIn("loopctl", skill)
        self.assertNotIn("adaptive_state_mcp", skill)

    def run_entry(self, *arguments):
        return subprocess.run(
            [str(ENTRY), *map(str, arguments)],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    def test_intake_four_outcomes_seven_sections_and_zero_side_effects(self):
        ready = ready_request()
        clarification = replace(ready, write_scope=(), budget="")
        blocked = replace(
            ready,
            external_actions=("publish",),
            authorization_boundaries=("no publish",),
        )
        direct = replace(
            ready,
            task_horizon="one_off",
            external_actions=(),
        )
        expected = (
            (ready, "READY_FOR_LOOP"),
            (clarification, "NEEDS_CLARIFICATION"),
            (blocked, "BLOCKED"),
            (direct, "DIRECT_TASK_RECOMMENDED"),
        )
        headings = (
            "1 最终判定",
            "2 质量闸矩阵",
            "3 阻断项",
            "4 必须澄清的问题",
            "5 风险与待确认假设",
            "6 规范化需求",
            "7 Loop 输入结果",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = tuple(root.iterdir())
            for request, disposition in expected:
                with self.subTest(disposition=disposition):
                    report = intake_report_loop(request)
                    self.assertEqual(tuple(report), headings)
                    self.assertEqual(
                        report["1 最终判定"]["disposition"], disposition
                    )
                    self.assertLessEqual(
                        len(report["4 必须澄清的问题"]), 3
                    )
            self.assertEqual(tuple(root.iterdir()), before)

    def test_prepare_confirm_and_start_have_exact_side_effect_boundaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = prepare_loop(
                ready_request(),
                root / "prepared",
                clock=lambda: NOW,
                token_factory=lambda: "111111111111111111111111",
            )
            self.assertEqual(len(tuple(prepared.directory.iterdir())), 8)
            self.assertFalse((root / "data").exists())
            self.assertEqual(set(boundary_display(prepared)), {
                "acceptance_criteria",
                "authorization_boundaries",
                "budget",
                "capacity",
                "destructive_actions_allowed",
                "external_actions",
                "execution_mode",
                "forbidden_actions",
                "forbidden_paths",
                "goal",
                "goal_count",
                "plan_revision",
                "selection_reason",
                "stop_conditions",
                "write_scope",
                "workspace_identity_digest",
            })
            with self.assertRaises(EntryError) as unconfirmed:
                start_loop(prepared, root=root / "data", clock=lambda: NOW)
            self.assertEqual(unconfirmed.exception.code, "USER_CONFIRMATION_REQUIRED")
            self.assertFalse((root / "data").exists())
            with self.assertRaises(EntryError) as declined:
                confirm_loop(prepared.directory, confirmed=False, clock=lambda: NOW)
            self.assertEqual(declined.exception.code, "USER_CONFIRMATION_REQUIRED")
            confirmed = confirm_loop(
                prepared.directory, confirmed=True, clock=lambda: NOW
            )
            self.assertEqual(len(tuple(prepared.directory.iterdir())), 9)
            start_loop(confirmed, root=root / "data", clock=lambda: NOW)
            with SQLiteStore(root / "data" / STORE_FILENAME) as store:
                self.assertEqual(store.commit_count, 1)
                self.assertEqual(len(store.ready_effect_attempts()), 1)
                descriptor = store.loop_descriptors()[0]
                self.assertEqual(
                    tuple(event["type"] for event in store.events(descriptor["loop_ref"])),
                    (
                        "LoopCreated",
                        "GoalRegistered",
                        "GoalActivated",
                        "GoalPlanRegistered",
                        "StartAuthorized",
                        "ExternalEffectPrepared",
                    ),
                )

    def test_stale_expired_and_changed_confirmation_fail_closed(self):
        later = datetime(2026, 7, 27, 1, 31, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expired = prepare_confirm(root / "expired", token="222222222222222222222222")
            with self.assertRaises(EntryError) as caught:
                start_loop(expired, root=root / "expired-data", clock=lambda: later)
            self.assertEqual(caught.exception.code, "USER_CONFIRMATION_STALE")
            self.assertFalse((root / "expired-data").exists())

            changed = prepare_confirm(root / "changed", token="333333333333333333333333")
            boundary_path = changed.directory / "boundary-summary.json"
            value = json.loads(boundary_path.read_text(encoding="utf-8"))
            value["budget"] = "changed after confirmation"
            boundary_path.write_text(
                json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            with self.assertRaises(EntryError) as caught:
                start_loop(changed, root=root / "changed-data", clock=lambda: NOW)
            self.assertEqual(caught.exception.code, "USER_CONFIRMATION_STALE")
            self.assertFalse((root / "changed-data").exists())

            forged = prepare_confirm(root / "forged", token="555555555555555555555555")
            confirmation_path = forged.directory / CONFIRMATION_FILENAME
            value = json.loads(confirmation_path.read_text(encoding="utf-8"))
            value["issuer_ref"] = "model-supplied-fake-issuer"
            confirmation_path.write_text(
                json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            with self.assertRaises(EntryError) as caught:
                start_loop(forged, root=root / "forged-data", clock=lambda: NOW)
            self.assertEqual(caught.exception.code, "USER_CONFIRMATION_STALE")
            self.assertFalse((root / "forged-data").exists())

    def test_direct_task_recommendation_never_creates_loop_or_preparation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request = replace(
                ready_request("Answer one bounded question"),
                task_horizon="one_off",
            )
            report = intake_report_loop(request)
            self.assertEqual(
                report["1 最终判定"]["disposition"],
                "DIRECT_TASK_RECOMMENDED",
            )
            with self.assertRaises(EntryError) as caught:
                prepare_loop(request, root / "prepared", clock=lambda: NOW)
            self.assertEqual(caught.exception.code, "USER_DIRECT_TASK_RECOMMENDED")
            self.assertEqual(tuple(root.iterdir()), ())

    def test_noninteractive_main_entry_stops_after_prepare_without_confirmation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "goal.json"
            source.write_text(
                json.dumps(
                    {
                        "goal": "Prepare but do not silently start",
                        "task_horizon": "long",
                        "write_scope": ["synthetic-workspace"],
                        "budget": "10 minutes",
                        "external_actions": [],
                        "acceptance_criteria": ["one startup"],
                        "stop_conditions": ["stop on UNKNOWN"],
                        "authorization_boundaries": ["no publish"],
                    }
                ),
                encoding="utf-8",
            )
            prepared = root / "prepared"
            data = root / "data"
            result = self.run_entry(
                "start",
                source,
                "--root",
                data,
                "--prepared-output",
                prepared,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("USER_CONFIRMATION_REQUIRED", result.stderr)
            self.assertEqual(len(tuple(prepared.iterdir())), 8)
            self.assertFalse((prepared / CONFIRMATION_FILENAME).exists())
            self.assertFalse(data.exists())

    def test_explicit_confirm_displays_boundary_and_requires_interaction(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = prepare_loop(
                ready_request("Explicit confirmation"),
                root / "prepared",
                clock=lambda: NOW,
                token_factory=lambda: "777777777777777777777777",
            )
            noninteractive = self.run_entry("confirm", prepared.directory)
            self.assertEqual(noninteractive.returncode, 2)
            self.assertIn("USER_CONFIRMATION_REQUIRED", noninteractive.stderr)
            self.assertFalse((prepared.directory / CONFIRMATION_FILENAME).exists())

            cli = load_cli_module()
            stdout = io.StringIO()
            with mock.patch.object(sys.stdin, "isatty", return_value=True), mock.patch(
                "builtins.input", return_value="START THIS LOOP"
            ), contextlib.redirect_stdout(stdout):
                result = cli.main(["confirm", str(prepared.directory)])
            self.assertEqual(result, 0)
            self.assertIn("LoopSkill 4 start boundary", stdout.getvalue())
            self.assertIn("Confirmation: accepted", stdout.getvalue())
            self.assertTrue((prepared.directory / CONFIRMATION_FILENAME).is_file())

    def test_standard_two_goal_path_closes_with_optional_modules_unavailable(self):
        original_import = __import__

        def deny_optional(name, globals=None, locals=None, fromlist=(), level=0):
            if name.startswith(("loop_architect.v4_policy", "loop_architect.v4_eager_v40")):
                raise ImportError("optional module unavailable")
            return original_import(name, globals, locals, fromlist, level)

        with tempfile.TemporaryDirectory() as temporary, mock.patch(
            "builtins.__import__", side_effect=deny_optional
        ):
            root = Path(temporary)
            prepared = prepare_confirm(
                root,
                "Minimal profile first goal",
                token="444444444444444444444444",
                goal_plan=(
                    "Minimal profile first goal",
                    "Minimal profile second goal",
                ),
            )
            data = root / "data"
            provider = EntryProviderFixture(now=NOW)
            started = start_loop(
                prepared,
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=root / "workspace",
            )
            self.assertEqual(started.progress, "Active")
            activated_second = sync_loop(
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=root / "workspace",
            )
            self.assertEqual(activated_second.progress, "Starting")
            closed = sync_loop(
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=root / "workspace",
            )
            self.assertEqual(closed.progress, "Finished")
            self.assertEqual(closed.result, "SUCCEEDED")
            self.assertEqual(provider.invoke_count, 2)
            self.assertEqual(provider.result_read_count, 2)
            with SQLiteStore(data / STORE_FILENAME) as store:
                snapshot = store.snapshot(store.loop_descriptors()[0]["loop_ref"])
                self.assertEqual(len(snapshot["goals"]), 2)
                self.assertEqual(len(snapshot["attempts"]), 2)
                self.assertEqual(snapshot["execution"]["state"], "TERMINAL")
            self.assertFalse((SCRIPTS / "loop_architect/v4_compat").exists())

    def test_confirmed_preparation_creates_and_starts_without_control_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            prepared = prepare_confirm(temporary)
            data = Path(temporary) / "data"
            status_view = start_loop(
                prepared,
                root=data,
                clock=lambda: NOW,
            )
            self.assertEqual(status_view.goal, "Ship a bounded public change")
            self.assertEqual(status_view.progress, "Starting")
            self.assertEqual(status_view.result, "Pending")
            self.assertTrue((data / STORE_FILENAME).is_file())
            self.assertEqual(data.stat().st_mode & 0o777, 0o700)

            reopened = status(root=data)
            self.assertEqual(reopened, status_view)
            with SQLiteStore(data / STORE_FILENAME) as store:
                descriptors = store.loop_descriptors()
                self.assertEqual(len(descriptors), 1)
                loop_ref = descriptors[0]["loop_ref"]
                self.assertEqual(store.snapshot(loop_ref)["execution"]["state"], "ACTIVE")
                self.assertEqual(store.commit_count, 1)
                self.assertEqual(len(store.authority.actors), 4)
                self.assertEqual(len(store.authority.grants), 7)
                self.assertEqual(len(store.ready_effect_attempts()), 1)
                self.assertEqual(store.ready_effect_attempts()[0].action, "create_task")
                self.assertNotIn("Ship a bounded public change", store.authority.actors)

    def test_one_input_file_or_main_command_runs_four_phases_with_explicit_confirm(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "goal.json"
            source.write_text(
                json.dumps(
                    {
                        "goal": "Start from one JSON file",
                        "task_horizon": "long",
                        "write_scope": ["synthetic-workspace"],
                        "budget": "10 minutes",
                        "external_actions": [],
                        "acceptance_criteria": ["one startup"],
                        "stop_conditions": ["stop on UNKNOWN"],
                        "authorization_boundaries": ["no publish"],
                    }
                ),
                encoding="utf-8",
            )
            data = root / "data"
            prepared = root / "prepared-output"
            cli = load_cli_module()
            provider = EntryProviderFixture()
            stdout = io.StringIO()
            stderr = io.StringIO()
            with mock.patch.object(cli, "CodexExecProvider", return_value=provider), mock.patch.object(sys.stdin, "isatty", return_value=True), mock.patch(
                "builtins.input", return_value="START THIS LOOP"
            ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = cli.main(
                    [
                        "start",
                        str(source),
                        "--root",
                        str(data),
                        "--prepared-output",
                        str(prepared),
                    ]
                )
            self.assertEqual(result, 0, stderr.getvalue())
            self.assertIn("1 最终判定", stdout.getvalue())
            self.assertIn("LoopSkill 4 start boundary", stdout.getvalue())
            self.assertIn("Progress: Active", stdout.getvalue())
            self.assertEqual(provider.invoke_count, 1)
            loop_directories = tuple((data / "loops").iterdir())
            self.assertEqual(len(loop_directories), 1)
            self.assertTrue((loop_directories[0] / STORE_FILENAME).is_file())
            self.assertTrue((prepared / CONFIRMATION_FILENAME).is_file())

    def test_public_host_result_refresh_closes_exact_external_subject_chain(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = prepare_confirm(
                root,
                "Complete one synthetic Host task",
                token="888888888888888888888888",
            )
            provider = EntryProviderFixture(now=NOW)
            data = root / "data"
            started = start_loop(
                prepared,
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=root / "workspace",
            )
            self.assertEqual(started.progress, "Active")
            closed = sync_loop(
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=root / "workspace",
            )
            self.assertEqual(closed.progress, "Finished")
            self.assertEqual(closed.result, "SUCCEEDED")
            self.assertEqual(provider.invoke_count, 1)
            self.assertEqual(provider.result_read_count, 1)
            with SQLiteStore(data / STORE_FILENAME) as store:
                snapshot = store.snapshot(store.loop_descriptors()[0]["loop_ref"])
                result = next(iter(snapshot["results"].values()))
                finalization = next(iter(snapshot["finalizations"].values()))
                self.assertIn("external_effect_ref", result)
                self.assertNotIn("delivery_ref", result)
                self.assertEqual(result["outcome"], "PASS")
                self.assertEqual(finalization["disposition"], "SUCCEEDED")
                self.assertEqual(snapshot["closure_assurance"]["strength"], "STRICT")
                artifact = next(iter(snapshot["artifacts"].values()))
                review = next(iter(snapshot["reviews"].values()))
                receipt = store.authority.receipts[artifact["receipt_ref"]]
                self.assertEqual(receipt.issuer_ref, "loopskill-local-artifact-verifier-v1")
                self.assertNotEqual(receipt.issuer_ref, "loopskill-codex-adapter-v1")
                self.assertEqual(artifact["capture_state"], "CAPTURED")
                self.assertTrue(review["reviewer_actor_ref"].startswith("actor-reviewer-"))
            replay = sync_loop(
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=root / "workspace",
            )
            self.assertEqual(replay.result, "SUCCEEDED")
            self.assertEqual(provider.result_read_count, 1)

    def test_host_pass_without_artifact_capability_cannot_succeed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = prepare_confirm(
                root,
                "Do not trust Host PASS as artifact proof",
                token="898989898989898989898989",
            )
            provider = EntryProviderFixture(now=NOW)
            data = root / "data"
            start_loop(
                prepared,
                root=data,
                host_provider=provider,
                workspace_root=root / "workspace",
                clock=lambda: NOW,
            )
            closed = sync_loop(root=data, host_provider=provider, clock=lambda: NOW)
            self.assertEqual(closed.result, "LIMITATION")
            with SQLiteStore(data / STORE_FILENAME) as store:
                snapshot = store.snapshot(store.loop_descriptors()[0]["loop_ref"])
                artifact = next(iter(snapshot["artifacts"].values()))
                review = next(iter(snapshot["reviews"].values()))
                self.assertEqual(artifact["capture_state"], "UNAVAILABLE")
                self.assertEqual(artifact["state"], "UNVERIFIABLE")
                self.assertEqual(review["state"], "LIMITATION")
                self.assertEqual(snapshot["execution"]["disposition"], "LIMITATION")

    def test_explicit_local_artifact_criterion_can_support_strict_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            content = b"verified artifact\n"
            request = replace(
                ready_request("Create one verifiable artifact"),
                acceptance_criteria=(
                    "file-sha256:result.txt=" + hashlib.sha256(content).hexdigest(),
                ),
            )
            prepared = prepare_loop(
                request,
                root / "prepared",
                clock=lambda: NOW,
                token_factory=lambda: "878787878787878787878787",
                workspace_root=workspace,
            )
            prepared = confirm_loop(prepared.directory, confirmed=True, clock=lambda: NOW)
            provider = EntryProviderFixture(now=NOW)
            data = root / "data"
            start_loop(
                prepared,
                root=data,
                host_provider=provider,
                workspace_root=workspace,
                clock=lambda: NOW,
            )
            (workspace / "result.txt").write_bytes(content)
            closed = sync_loop(
                root=data,
                host_provider=provider,
                workspace_root=workspace,
                clock=lambda: NOW,
            )
            self.assertEqual(closed.result, "SUCCEEDED")

    def test_host_result_refresh_recovers_every_local_durable_boundary(self):
        operation_types = (
            "StageExternalResult",
            "AcknowledgeResult",
            "RecordReview",
            "AdvanceGoal",
            "PrepareFinalization",
            "CloseExecution",
        )
        original_apply = SQLiteStore.apply
        for operation_type in operation_types:
            for boundary in DURABLE_FAULT_BOUNDARIES:
                with self.subTest(operation_type=operation_type, boundary=boundary):
                    with tempfile.TemporaryDirectory() as temporary:
                        root = Path(temporary)
                        prepared = prepare_confirm(
                            root,
                            "Recover one synthetic Host result",
                            token="999999999999999999999999",
                        )
                        provider = EntryProviderFixture(now=NOW)
                        data = root / "data"
                        start_loop(
                            prepared,
                            root=data,
                            host_provider=provider,
                            clock=lambda: NOW,
                            workspace_root=root / "workspace",
                        )
                        injected = {"value": False}

                        def fault_once(subject, command, *, fault_at=None):
                            if (
                                command.command_type == operation_type
                                and not injected["value"]
                            ):
                                injected["value"] = True
                                return original_apply(
                                    subject,
                                    command,
                                    fault_at=boundary,
                                )
                            return original_apply(subject, command, fault_at=fault_at)

                        with mock.patch.object(SQLiteStore, "apply", new=fault_once):
                            with self.assertRaises(InjectedCrash):
                                sync_loop(
                                    root=data,
                                    host_provider=provider,
                                    clock=lambda: NOW,
                                    workspace_root=root / "workspace",
                                )
                        self.assertTrue(injected["value"])
                        closed = sync_loop(
                            root=data,
                            host_provider=provider,
                            clock=lambda: NOW,
                            workspace_root=root / "workspace",
                        )
                        self.assertEqual(closed.result, "SUCCEEDED")
                        self.assertEqual(provider.invoke_count, 1)
                        with SQLiteStore(data / STORE_FILENAME) as store:
                            store.verify_integrity()
                            snapshot = store.snapshot(
                                store.loop_descriptors()[0]["loop_ref"]
                            )
                            self.assertEqual(
                                snapshot["execution"]["state"], "TERMINAL"
                            )
                            self.assertEqual(len(snapshot["results"]), 1)
                            self.assertEqual(len(snapshot["finalizations"]), 1)

    def assert_host_result_closure(
        self,
        *,
        result_status,
        result_payload,
        expected_outcome,
        expected_disposition,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = prepare_confirm(
                root,
                "Preserve one non-success Host result",
                token="aaaaaaaaaaaaaaaaaaaaaaaa",
            )
            provider = EntryProviderFixture(
                now=NOW,
                result_status=result_status,
                result_payload=result_payload,
            )
            data = root / "data"
            start_loop(
                prepared,
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=root / "workspace",
            )
            closed = sync_loop(
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=root / "workspace",
            )
            self.assertEqual(closed.result, expected_disposition)
            self.assertTrue(closed.limitations)
            self.assertEqual(provider.invoke_count, 1)
            with SQLiteStore(data / STORE_FILENAME) as store:
                snapshot = store.snapshot(store.loop_descriptors()[0]["loop_ref"])
                result = next(iter(snapshot["results"].values()))
                finalization = next(iter(snapshot["finalizations"].values()))
                self.assertEqual(result["outcome"], expected_outcome)
                self.assertEqual(
                    finalization["disposition"], expected_disposition
                )
                self.assertEqual(snapshot["execution"]["state"], "TERMINAL")

    def test_host_failed_result_closes_failed(self):
        self.assert_host_result_closure(
            result_status="FAILED",
            result_payload={
                "outcome": "PASS",
                "summary": "result cannot override failed Host status",
            },
            expected_outcome="FAILED",
            expected_disposition="FAILED",
        )

    def test_host_unverifiable_result_closes_limitation(self):
        self.assert_host_result_closure(
            result_status="COMPLETED",
            result_payload={
                "outcome": "UNVERIFIABLE",
                "summary": "Host evidence was insufficient.",
            },
            expected_outcome="UNVERIFIABLE",
            expected_disposition="LIMITATION",
        )

    def test_host_limitation_result_closes_limitation(self):
        self.assert_host_result_closure(
            result_status="COMPLETED",
            result_payload={"outcome": "LIMITATION", "summary": "bounded evidence only"},
            expected_outcome="LIMITATION",
            expected_disposition="LIMITATION",
        )

    def test_default_path_has_zero_control_fields_and_no_policy_pack(self):
        help_result = self.run_entry("start", "--help")
        self.assertEqual(help_result.returncode, 0)
        for forbidden in (
            "thread-id",
            "task-id",
            "actor",
            "grant",
            "receipt",
            "version",
            "policy-pack",
            "heartbeat",
            "retry",
        ):
            self.assertNotIn(forbidden, help_result.stdout.lower())

        with tempfile.TemporaryDirectory() as temporary:
            prepared = prepare_confirm(
                temporary,
                "threadId=from-model does not grant authority",
            )
            data = Path(temporary) / "data"
            start_loop(prepared, root=data, clock=lambda: NOW)
            result = self.run_entry("status", "--root", data)
            self.assertEqual(result.returncode, 0, result.stderr)
            view = diagnostics(root=data)
            self.assertNotIn("from-model", view["loop_ref"])

    def test_invalid_inputs_are_stable_non_leaking_and_leave_no_store(self):
        instances = (
            ("missing.json", None),
            ("bad.json", "{"),
            ("missing-goal.json", '{"other":"value"}'),
        )
        for name, content in instances:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    source = root / name
                    if content is not None:
                        source.write_text(content, encoding="utf-8")
                    data = root / "data"
                    result = self.run_entry("start", source, "--root", data)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("USER_INPUT_INVALID", result.stderr)
                    self.assertNotIn("loop-", result.stderr)
                    self.assertNotIn("receipt", result.stderr.lower())
                    self.assertNotIn("schema", result.stderr.lower())
                    self.assertFalse((data / STORE_FILENAME).exists())

        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_entry(
                "start",
                "goal",
                "--thread-id",
                "forged",
                "--root",
                temporary,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("USER_INPUT_INVALID", result.stderr)
            self.assertNotIn("forged", result.stderr)

    def test_default_status_hides_internal_identity_diagnostics_is_opt_in(self):
        with tempfile.TemporaryDirectory() as temporary:
            prepared = prepare_confirm(temporary, "Visible goal")
            data = Path(temporary) / "data"
            start_loop(prepared, root=data, clock=lambda: NOW)
            started = self.run_entry("status", "--root", data)
            self.assertEqual(started.returncode, 0, started.stderr)
            for hidden in ("loop-", "receipt", "snapshot_digest", "schema"):
                self.assertNotIn(hidden, started.stdout.lower())

            ordinary = self.run_entry("status", "--root", data)
            self.assertEqual(ordinary.returncode, 0, ordinary.stderr)
            self.assertNotIn("loop-", ordinary.stdout)
            self.assertNotIn("snapshot_digest", ordinary.stdout)

            diagnostic = self.run_entry(
                "status", "--root", data, "--diagnostics"
            )
            self.assertEqual(diagnostic.returncode, 0, diagnostic.stderr)
            self.assertIn("Diagnostics:", diagnostic.stdout)
            self.assertIn('"loop_ref":"loop-', diagnostic.stdout)
            self.assertIn('"snapshot_digest":', diagnostic.stdout)

    def test_public_lifecycle_and_optional_mode_projection_are_reachable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = prepare_confirm(
                root,
                "Exercise public lifecycle controls",
                token="818181818181818181818181",
            )
            data = root / "data"
            start_loop(prepared, root=data, clock=lambda: NOW)
            self.assertEqual(policy_view(root=data)["policy"]["kind"], "STANDARD")
            self.assertEqual(control_loop("pause", root=data, clock=lambda: NOW).progress, "Paused")
            self.assertEqual(control_loop("resume", root=data, clock=lambda: NOW).progress, "Starting")
            self.assertEqual(steer_loop("wait", root=data, clock=lambda: NOW).progress, "Paused")
            self.assertEqual(control_loop("resume", root=data, clock=lambda: NOW).progress, "Starting")
            self.assertEqual(steer_loop("stop", root=data, clock=lambda: NOW).result, "STOPPED")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            request = replace(
                ready_request("Adaptive primary", horizon="adaptive"),
                goal_plan=("Adaptive primary", "Adaptive verify", "Adaptive publish boundary"),
            )
            prepared = prepare_loop(
                request,
                root / "prepared",
                clock=lambda: NOW,
                token_factory=lambda: "828282828282828282828282",
                workspace_root=workspace,
            )
            prepared = confirm_loop(prepared.directory, confirmed=True, clock=lambda: NOW)
            data = root / "data"
            start_loop(prepared, root=data, clock=lambda: NOW)
            projection = policy_view(root=data)
            self.assertEqual(projection["policy"]["kind"], "ADAPTIVE")
            self.assertEqual(projection["policy"]["active_goal_count"], 1)
            self.assertEqual(projection["policy"]["goal_count"], 3)
            self.assertEqual(projection["policy"]["revision"], 0)
            revised = revise_goal_plan(
                (
                    "Adaptive primary",
                    "Adaptive publish boundary",
                    "Adaptive verify",
                ),
                root=data,
                reason="Reorder only pending milestones.",
                clock=lambda: NOW,
            )
            self.assertEqual(revised["policy"]["revision"], 1)
            with self.assertRaises(EntryError):
                revise_goal_plan(
                    ("Adaptive primary", "Outside author envelope", "Adaptive verify"),
                    root=data,
                    reason="Attempt scope expansion.",
                    clock=lambda: NOW,
                )
            self.assertEqual(policy_view(root=data)["policy"]["revision"], 1)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            request = replace(
                ready_request("Standard primary"),
                goal_plan=("Standard primary", "Standard dependent"),
            )
            prepared = prepare_loop(
                request,
                root / "prepared",
                clock=lambda: NOW,
                token_factory=lambda: "829292929292929292929292",
                workspace_root=workspace,
            )
            prepared = confirm_loop(prepared.directory, confirmed=True, clock=lambda: NOW)
            data = root / "data"
            start_loop(prepared, root=data, clock=lambda: NOW)
            projection = policy_view(root=data)
            self.assertEqual(projection["policy"]["kind"], "STANDARD")
            self.assertEqual(projection["policy"]["goal_count"], 2)
            self.assertEqual(projection["policy"]["ordered_states"], ("ACTIVE", "PENDING"))
            with SQLiteStore(data / STORE_FILENAME) as store:
                snapshot = store.snapshot(store.loop_descriptors()[0]["loop_ref"])
                self.assertIsNotNone(snapshot)
                self.assertEqual(len(snapshot["goals"]), 1)
                current = next(iter(snapshot["goals"].values()))
                self.assertEqual(current["goal_id"], "g000")
                self.assertIsNone(current["depends_on"])

    def test_confirmed_goal_plan_is_atomic_bounded_and_runs_two_goal_chains(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            request = replace(
                ready_request("Atomic primary", horizon="adaptive"),
                goal_plan=("Atomic primary", "Atomic dependent"),
            )
            prepared = prepare_loop(
                request,
                root / "prepared",
                clock=lambda: NOW,
                token_factory=lambda: "838484848484848484848484",
                workspace_root=workspace,
            )
            prepared = confirm_loop(prepared.directory, confirmed=True, clock=lambda: NOW)
            data = root / "data"
            original_apply = SQLiteStore.apply
            crashed = False

            def crash_after_create(store, command, *args, **kwargs):
                nonlocal crashed
                result = original_apply(store, command, *args, **kwargs)
                if command.command_type == "CreateLoop" and not crashed:
                    crashed = True
                    raise InjectedCrash("after committed atomic START")
                return result

            with mock.patch.object(SQLiteStore, "apply", crash_after_create):
                with self.assertRaises(InjectedCrash):
                    start_loop(
                        prepared,
                        root=data,
                        clock=lambda: NOW,
                        workspace_root=workspace,
                    )
            with SQLiteStore(data / STORE_FILENAME) as store:
                snapshot = store.snapshot(store.loop_descriptors()[0]["loop_ref"])
                self.assertIsNotNone(snapshot)
                self.assertEqual(len(snapshot["goals"]), 1)
                self.assertEqual(len(snapshot["attempts"]), 1)
                self.assertEqual(snapshot["goal_plan"]["revision"], 0)
                self.assertEqual(snapshot["goal_plan"]["max_roadmap_revisions"], 5)
                self.assertRegex(snapshot["goal_plan"]["plan_digest"], r"^[0-9a-f]{64}$")

            first = ("Atomic primary", "Atomic dependent")
            second = ("Atomic primary", "Atomic dependent")
            third = ("Atomic primary", "Atomic dependent")
            for expected_revision, order in (
                (1, first),
                (2, second),
                (3, third),
                (4, first),
            ):
                projection = revise_goal_plan(
                    order,
                    root=data,
                    reason=f"Bounded revision {expected_revision}.",
                    clock=lambda: NOW,
                )
                self.assertEqual(projection["policy"]["revision"], expected_revision)
            with self.assertRaises(EntryError):
                revise_goal_plan(
                    first,
                    root=data,
                    reason="Attempt revision beyond confirmed envelope.",
                    clock=lambda: NOW,
                )
            self.assertEqual(policy_view(root=data)["policy"]["revision"], 4)

            provider = EntryProviderFixture(now=NOW)
            start_loop(
                prepared,
                root=data,
                clock=lambda: NOW,
                host_provider=provider,
                workspace_root=workspace,
            )
            advance_crashed = False

            def crash_after_advance(store, command, *args, **kwargs):
                nonlocal advance_crashed
                if command.command_type == "AdvanceGoal" and not advance_crashed:
                    advance_crashed = True
                    return original_apply(
                        store,
                        command,
                        *args,
                        fault_at="after_commit_before_response",
                        **kwargs,
                    )
                return original_apply(store, command, *args, **kwargs)

            with mock.patch.object(SQLiteStore, "apply", crash_after_advance):
                with self.assertRaises(InjectedCrash):
                    sync_loop(
                        root=data,
                        host_provider=provider,
                        clock=lambda: NOW,
                        workspace_root=workspace,
                    )
            self.assertEqual(provider.invoke_count, 1)
            with SQLiteStore(data / STORE_FILENAME) as store:
                snapshot = store.snapshot(store.loop_descriptors()[0]["loop_ref"])
                self.assertIsNotNone(snapshot)
                states = {
                    goal["goal_id"]: goal["state"]
                    for goal in snapshot["goals"].values()
                }
                self.assertEqual(states, {"g000": "DONE", "g001": "ACTIVE"})
                self.assertEqual(len(snapshot["attempts"]), 2)
            terminal = sync_loop(
                root=data,
                host_provider=provider,
                clock=lambda: NOW,
                workspace_root=workspace,
            )
            self.assertEqual(terminal.progress, "Finished")
            self.assertEqual(terminal.result, "SUCCEEDED")
            self.assertEqual(provider.invoke_count, 2)
            with SQLiteStore(data / STORE_FILENAME) as store:
                snapshot = store.snapshot(store.loop_descriptors()[0]["loop_ref"])
                self.assertIsNotNone(snapshot)
                self.assertEqual(
                    {
                        goal["goal_id"]: goal["state"]
                        for goal in snapshot["goals"].values()
                    },
                    {"g000": "DONE", "g001": "DONE"},
                )
                for collection in (
                    "artifacts",
                    "attempts",
                    "external_effects",
                    "reports",
                    "results",
                    "reviews",
                ):
                    self.assertEqual(len(snapshot[collection]), 2, collection)

    def test_bounded_repair_decision_exhausts_without_automatic_resend(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            request = replace(
                ready_request("Require a changed artifact"),
                acceptance_criteria=("artifact-changed",),
            )
            prepared = prepare_loop(
                request,
                root / "prepared",
                clock=lambda: NOW,
                token_factory=lambda: "838383838383838383838383",
                workspace_root=workspace,
            )
            prepared = confirm_loop(prepared.directory, confirmed=True, clock=lambda: NOW)
            provider = EntryProviderFixture(now=NOW)
            data = root / "data"
            start_loop(
                prepared,
                root=data,
                host_provider=provider,
                workspace_root=workspace,
                clock=lambda: NOW,
            )
            repair = sync_loop(
                root=data,
                host_provider=provider,
                workspace_root=workspace,
                clock=lambda: NOW,
            )
            self.assertEqual(repair.result, "Repair required")
            first = steer_loop(
                "continue-repair",
                root=data,
                failure_fingerprint="artifact criterion failed",
                clock=lambda: NOW,
            )
            self.assertEqual(first.result, "Repair authorized")
            second = steer_loop(
                "continue-repair",
                root=data,
                failure_fingerprint="artifact criterion failed",
                clock=lambda: NOW,
            )
            self.assertEqual(second.result, "Repair exhausted")
            self.assertEqual(provider.invoke_count, 1)
            self.assertNotIn("CONTINUE_REPAIR", policy_view(root=data)["decision_options"])

    def test_duplicate_start_is_safe_and_does_not_create_a_second_loop(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_prepared = prepare_loop(
                ready_request("First goal"),
                root / "prepared-first",
                clock=lambda: NOW,
                token_factory=lambda: "000000000000000000000001",
            )
            first_prepared = confirm_loop(
                first_prepared.directory, confirmed=True, clock=lambda: NOW
            )
            second_prepared = prepare_loop(
                ready_request("Second goal"),
                root / "prepared-second",
                clock=lambda: NOW,
                token_factory=lambda: "000000000000000000000002",
            )
            second_prepared = confirm_loop(
                second_prepared.directory, confirmed=True, clock=lambda: NOW
            )
            data = root / "data"
            first = start_loop(first_prepared, root=data, clock=lambda: NOW)
            self.assertEqual(first.progress, "Starting")
            replay = start_loop(first_prepared, root=data, clock=lambda: NOW)
            self.assertEqual(replay.progress, "Starting")
            with self.assertRaises(EntryError) as caught:
                start_loop(second_prepared, root=data, clock=lambda: NOW)
            self.assertEqual(caught.exception.code, "USER_LOOP_EXISTS")
            with SQLiteStore(data / STORE_FILENAME) as store:
                self.assertEqual(store.commit_count, 1)
                self.assertEqual(len(store.loop_descriptors()), 1)
                self.assertEqual(store.loop_descriptors()[0]["goal"], "First goal")

    def test_symlinked_data_root_fails_before_store_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.mkdir()
            linked = root / "linked"
            linked.symlink_to(target, target_is_directory=True)
            prepared = prepare_confirm(root / "preparation-parent", "safe goal")
            with self.assertRaises(EntryError) as caught:
                start_loop(
                    prepared,
                    root=linked,
                    clock=lambda: NOW,
                )
            self.assertEqual(caught.exception.code, "USER_STORE_UNAVAILABLE")
            self.assertFalse((target / STORE_FILENAME).exists())

    def test_status_and_diagnostics_never_create_an_absent_store(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "absent"
            with self.assertRaises(EntryError):
                status(root=root)
            with self.assertRaises(EntryError):
                diagnostics(root=root)
            self.assertFalse(root.exists())

    def test_goal_and_authority_registry_corruption_fail_closed(self):
        for target in ("goal", "actor"):
            with self.subTest(target=target):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    prepared = prepare_confirm(root, "Integrity-bound goal")
                    data = root / "data"
                    start_loop(
                        prepared,
                        root=data,
                        clock=lambda: NOW,
                    )
                    path = data / STORE_FILENAME
                    with SQLiteStore(path) as store:
                        if target == "goal":
                            store._connection.execute(
                                "UPDATE loop_descriptors SET goal_digest = 'tampered'"
                            )
                        else:
                            row = store._connection.execute(
                                "SELECT actor_ref, actor_json FROM authority_actors LIMIT 1"
                            ).fetchone()
                            raw = bytes(row["actor_json"]).replace(
                                row["actor_ref"].encode(), b"actor-forged-identity"
                            )
                            store._connection.execute(
                                "UPDATE authority_actors SET actor_json = ? WHERE actor_ref = ?",
                                (raw, row["actor_ref"]),
                            )
                        with self.assertRaises(PersistenceCorruption):
                            store.verify_integrity()

    def test_entry_dependency_graph_has_no_v3_or_uncontrolled_side_effect_modules(self):
        files = (
            SCRIPTS / "loopskill4",
            SCRIPTS / "loop_architect" / "v4_entry" / "service.py",
        )
        forbidden = {
            "git",
            "requests",
            "subprocess",
            "loop_architect.state_runtime",
        }
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            } | {
                node.module or ""
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
            }
            self.assertFalse(
                any(
                    imported == denied or imported.startswith(denied + ".")
                    for imported in imports
                    for denied in forbidden
                ),
                path,
            )

    def test_startup_effect_all_durable_boundaries_are_atomic(self):
        with tempfile.TemporaryDirectory() as temporary:
            prepared = prepare_confirm(
                temporary,
                "Atomic startup effect",
                token="cccccccccccccccccccccccc",
            )
        _, authority, command = _machine_bootstrap(
            prepared,
            now=NOW,
            receipt_trust_roots={},
        )
        for boundary in DURABLE_FAULT_BOUNDARIES:
            with self.subTest(boundary=boundary):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    path = root / "subject.sqlite3"
                    clean_path = root / "clean.sqlite3"
                    with SQLiteStore(path, authority) as subject:
                        subject.put_blob(canonical_bytes(prepared.plan))
                        subject.put_blob(canonical_bytes(prepared.plan_index))
                        exact_pre = subject.canonical_export()
                    with SQLiteStore(clean_path, authority) as clean:
                        clean.put_blob(canonical_bytes(prepared.plan))
                        clean.put_blob(canonical_bytes(prepared.plan_index))
                        clean.apply(command)
                        exact_post = clean.canonical_export()
                    with SQLiteStore(path, authority) as subject:
                        with self.assertRaises(InjectedCrash):
                            subject.apply(command, fault_at=boundary)
                    with SQLiteStore(path, authority) as recovered:
                        if boundary == "after_commit_before_response":
                            self.assertEqual(recovered.canonical_export(), exact_post)
                            self.assertTrue(recovered.apply(command).replayed)
                        else:
                            self.assertEqual(recovered.canonical_export(), exact_pre)
                            recovered.apply(command)
                        self.assertEqual(recovered.canonical_export(), exact_post)
                        self.assertEqual(len(recovered.ready_effect_attempts()), 1)
                        recovered.verify_integrity()


if __name__ == "__main__":
    unittest.main()
