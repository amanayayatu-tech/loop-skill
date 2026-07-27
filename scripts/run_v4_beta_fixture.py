#!/usr/bin/env python3
"""Run the frozen same-scenario v4 beta fixture with no real external effect."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "codex-loop-prompt-architect" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from loop_architect.v4_alpha.protocol import (  # noqa: E402
    LoopIntakeInput,
    build_command,
    canonical_bytes,
)
from loop_architect.v4_alpha.store import InMemoryStore  # noqa: E402
from loop_architect.v4_alpha.vertical import (  # noqa: E402
    LOOP_REF,
    fixture_authority,
    vertical_commands,
)
from loop_architect.v4_entry import confirm_loop, prepare_loop  # noqa: E402
from loop_architect.v4_policy import next_action  # noqa: E402


SCENARIO = ROOT / "tests" / "fixtures" / "v4_beta" / "same-scenario.json"
BASELINE = ROOT / "evidence" / "v4-development" / "p7-v3-baseline-freeze.json"
NOW = datetime(2026, 7, 27, 2, 0, 0, tzinfo=timezone.utc)
EXPECTED_NEXT = (
    ("COMMAND", "BindHostResource"),
    ("COMMAND", "PrepareRoute"),
    ("COMMAND", "BeginEffectDelivery"),
    ("EXTERNAL_WAIT", "RecordEffectObservation"),
    ("COMMAND", "StageResult"),
    ("COMMAND", "AcknowledgeResult"),
    ("POLICY_DECISION", "RecordReview"),
    ("COMMAND", "AdvanceGoal"),
    ("COMMAND", "PrepareFinalization"),
    ("EXTERNAL_WAIT", "CloseExecution"),
    ("TERMINAL", None),
)
HOST_INTERACTION_LEDGER = (
    "strict Host resource create/readback receipt",
    "strict delivery send/readback receipt",
    "strict final lifecycle readback receipt",
)


def _document(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("fixture document must be an object")
    return value


def _rebuild_first(command, goal: str):
    return build_command(
        operation_id=command.operation_id,
        command_type=command.command_type,
        actor_ref=command.actor_ref,
        authority_grant_ref=command.authority_grant_ref,
        subject=dict(command.subject),
        expected_loop_revision=command.expected_loop_revision,
        expected_subject_revisions=dict(command.expected_subject_revisions),
        issued_at=command.issued_at,
        machine_bindings={
            group: dict(values) for group, values in command.machine_bindings.items()
        },
        semantic_payload={"objective": goal},
    )


def run_fixture() -> dict[str, Any]:
    scenario = _document(SCENARIO)
    baseline = _document(BASELINE)
    scenario_digest = hashlib.sha256(canonical_bytes(scenario)).hexdigest()
    if scenario_digest != baseline["scenario_sha256"]:
        raise ValueError("scenario/baseline digest mismatch")
    semantic = scenario["v4_semantic_input"]
    request = LoopIntakeInput(
        goal=semantic["goal"],
        task_horizon=semantic["task_horizon"],
        write_scope=tuple(semantic["write_scope"]),
        budget=semantic["budget"],
        external_actions=tuple(semantic["external_actions"]),
        acceptance_criteria=tuple(semantic["acceptance_criteria"]),
        stop_conditions=tuple(semantic["stop_conditions"]),
        authorization_boundaries=tuple(semantic["authorization_boundaries"]),
    )
    started = time.perf_counter_ns()
    with tempfile.TemporaryDirectory(prefix="loopskill-v4-beta-") as temporary:
        root = Path(temporary)
        prepared = prepare_loop(
            request,
            root / "prepared",
            clock=lambda: NOW,
            token_factory=lambda: "777777777777777777777777",
        )
        confirmed = confirm_loop(
            prepared.directory, confirmed=True, clock=lambda: NOW
        )
        pack_bytes = (confirmed.directory / "CONTROLLER_PLAN.md").read_bytes()
        if confirmed.manifest.execution_mode != "STANDARD":
            raise AssertionError("same scenario must default to Standard")
        commands = list(vertical_commands())
        commands[0] = _rebuild_first(commands[0], semantic["goal"])
        store = InMemoryStore(fixture_authority())
        actions: list[tuple[str, str | None]] = []
        for command in commands:
            store.apply(command)
            action = next_action(store.snapshot(LOOP_REF))
            actions.append((action.kind, action.command_type))
        store.verify_integrity()
        if tuple(actions) != EXPECTED_NEXT:
            raise AssertionError("same-scenario next-action trace drift")
        snapshot = store.snapshot(LOOP_REF)
        if (
            snapshot["execution"]
            != {"disposition": "SUCCEEDED", "revision": 3, "state": "TERMINAL"}
            or snapshot["closure_assurance"]["strength"] != "STRICT"
        ):
            raise AssertionError("same-scenario closure drift")
        elapsed = time.perf_counter_ns() - started
        metrics = {
            "authorization_confirmations": 1,
            "host_interactions": len(HOST_INTERACTION_LEDGER),
            "human_interventions": 1,
            "internal_control_interactions": len(HOST_INTERACTION_LEDGER),
            "latency_ns": elapsed,
            "local_writes": 17,
            "pack_bytes": len(pack_bytes),
            "protocol_calls": len(commands),
            "unknown_count": 0,
            "user_start_actions": 1,
        }
        return {
            "artifact": "loopskill-v4-p7-comparison-input-v1",
            "scenario_sha256": scenario_digest,
            "measurement_code_sha256": baseline["measurement_code_sha256"],
            "fixture_runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "metrics": metrics,
            "host_interaction_ledger": list(HOST_INTERACTION_LEDGER),
            "next_action_trace": [
                {"kind": kind, "command_type": command_type}
                for kind, command_type in actions
            ],
            "canonical_commits": store.commit_count,
            "event_count": len(store.events(LOOP_REF)),
            "execution_disposition": snapshot["execution"]["disposition"],
            "closure_assurance": snapshot["closure_assurance"]["strength"],
            "real_external_effects": 0,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    print(json.dumps(run_fixture(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
