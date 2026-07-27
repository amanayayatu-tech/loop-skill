from __future__ import annotations

import ast
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "codex-loop-prompt-architect" / "scripts"
ENTRY = SCRIPTS / "loopskill4"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from loop_architect.v4_alpha.kernel import AuthorityContext  # noqa: E402
from loop_architect.v4_alpha.protocol import (  # noqa: E402
    CAPABILITY_NAMES,
    InjectedCrash,
    LoopIntakeInput,
    Receipt,
)
from loop_architect.v4_adapters.codex.adapter import HOST_SCHEMA_VERSION  # noqa: E402
from loop_architect.v4_alpha.vertical import (  # noqa: E402
    LOOP_REF,
    fixture_authority,
    vertical_commands,
)
from loop_architect.v4_entry import (  # noqa: E402
    EntryError,
    confirm_loop,
    diagnostics,
    intake_report_loop,
    prepare_loop,
    record_external_observation,
    start_loop,
    status,
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
    def __init__(self):
        self.invoke_count = 0
        self.records = {}

    def capability_snapshot(self):
        now = datetime.now(timezone.utc)
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
            "state": "ACTIVE",
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
        task_horizon=horizon,
        write_scope=("synthetic-workspace",),
        budget="10 minutes; 1 Host create attempt",
        external_actions=(),
        acceptance_criteria=("one canonical startup Attempt",),
        stop_conditions=("stop on UNKNOWN",),
        authorization_boundaries=("no commit, push, publish, or deploy",),
    )


def prepare_confirm(root, goal="Ship a bounded public change", *, token="000000000000000000000001"):
    prepared = prepare_loop(
        ready_request(goal),
        Path(root) / "prepared",
        clock=lambda: NOW,
        token_factory=lambda: token,
    )
    return confirm_loop(prepared.directory, confirmed=True, clock=lambda: NOW)


def load_cli_module():
    loader = importlib.machinery.SourceFileLoader("loopskill4_test_cli", str(ENTRY))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def changed_authority_with_delivery(*, outcome, trust_class):
    base = fixture_authority()
    receipts = dict(base.receipts)
    receipts["receipt-delivery-0001"] = replace(
        receipts["receipt-delivery-0001"],
        outcome=outcome,
        trust_class=trust_class,
    )
    return AuthorityContext(
        actors=base.actors,
        grants=base.grants,
        receipts=receipts,
        trusted_actor_issuers=base.trusted_actor_issuers,
        trusted_grant_issuers=base.trusted_grant_issuers,
        trusted_receipt_issuers=base.trusted_receipt_issuers,
    )


class V4SingleEntryUXTests(unittest.TestCase):
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
            self.assertEqual(len(tuple(prepared.directory.iterdir())), 5)
            self.assertFalse((root / "data").exists())
            self.assertEqual(set(boundary_display(prepared)), {
                "acceptance_criteria",
                "authorization_boundaries",
                "budget",
                "external_actions",
                "execution_mode",
                "goal",
                "selection_reason",
                "stop_conditions",
                "write_scope",
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
            self.assertEqual(len(tuple(prepared.directory.iterdir())), 6)
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
            self.assertEqual(len(tuple(prepared.iterdir())), 5)
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

    def test_minimal_profile_runs_without_policy_and_compat_runtime_absent(self):
        original_import = __import__

        def deny_optional(name, globals=None, locals=None, fromlist=(), level=0):
            if name.startswith("loop_architect.v4_policy"):
                raise ImportError("optional module unavailable")
            return original_import(name, globals, locals, fromlist, level)

        with tempfile.TemporaryDirectory() as temporary, mock.patch(
            "builtins.__import__", side_effect=deny_optional
        ):
            root = Path(temporary)
            prepared = prepare_confirm(
                root,
                "Minimal profile loop",
                token="444444444444444444444444",
            )
            data = root / "data"
            start_loop(prepared, root=data, clock=lambda: NOW)
            self.assertEqual(status(root=data).progress, "Starting")
            with SQLiteStore(data / STORE_FILENAME) as store:
                attempt = store.ready_effect_attempts()[0]
            receipt = Receipt(
                receipt_ref="receipt-minimal-profile-unknown",
                issuer_ref="loopskill-codex-adapter-v1",
                issuer_trust="local-codex-adapter",
                trust_class="cooperative",
                action=attempt.action,
                loop_ref=attempt.loop_ref,
                subject_ref=attempt.subject_ref,
                attempt_ref=attempt.attempt_ref,
                target_ref=attempt.target_ref,
                request_digest=attempt.provider_request_digest,
                provider_idempotency_key=attempt.provider_idempotency_key,
                provider_resource_ref=None,
                outcome="unknown",
                issued_at=NOW.isoformat().replace("+00:00", "Z"),
                expires_at=(NOW + timedelta(minutes=5)).isoformat().replace(
                    "+00:00", "Z"
                ),
                evidence_digest="minimal-profile-no-readback",
            )
            unknown = record_external_observation(receipt, root=data)
            self.assertEqual(unknown.progress, "Needs attention")
            self.assertIn("unknown", unknown.limitations[0].lower())
            self.assertNotIn("resend", " ".join(unknown.next_actions).lower())
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
                self.assertEqual(len(store.authority.actors), 2)
                self.assertEqual(len(store.authority.grants), 2)
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
            with mock.patch.object(cli, "CodexAppServerProvider", return_value=provider), mock.patch.object(sys.stdin, "isatty", return_value=True), mock.patch(
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
            self.assertTrue((data / STORE_FILENAME).is_file())
            self.assertTrue((prepared / CONFIRMATION_FILENAME).is_file())

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

    def test_unknown_and_unverifiable_are_visible_without_resend_controls(self):
        for outcome, trust_class, word in (
            ("unknown", "cooperative", "unknown"),
            ("responded", "cooperative", "cannot be verified"),
        ):
            with self.subTest(outcome=outcome):
                with tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / STORE_FILENAME
                    authority = changed_authority_with_delivery(
                        outcome=outcome, trust_class=trust_class
                    )
                    with SQLiteStore(path, authority) as store:
                        for command in vertical_commands()[:5]:
                            store.apply(command)
                    view = status(root=temporary)
                    self.assertEqual(view.progress, "Needs attention")
                    self.assertIn(word, view.limitations[0].lower())
                    self.assertNotIn("resend", " ".join(view.next_actions).lower())

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
            "loop_architect.v4_artifacts",
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
                        exact_pre = subject.canonical_export()
                    with SQLiteStore(clean_path, authority) as clean:
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
