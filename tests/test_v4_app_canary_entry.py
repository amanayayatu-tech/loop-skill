from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "codex-loop-prompt-architect" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from loop_architect.v4_adapters.codex import (  # noqa: E402
    HostResponseLost,
    HostUnavailable,
)
from loop_architect.v4_adapters.codex.adapter import (  # noqa: E402
    HOST_SCHEMA_VERSION,
)
from loop_architect.v4_alpha.protocol import (  # noqa: E402
    CAPABILITY_NAMES,
    domain_digest,
)
from loop_architect.v4_entry import canary  # noqa: E402
from loop_architect.v4_entry.preparation import (  # noqa: E402
    CONFIRMATION_FILENAME,
    MANIFEST_FILENAME,
)
from loop_architect.v4_entry.service import STORE_FILENAME  # noqa: E402
from loop_architect.v4_persistence.sqlite_store import SQLiteStore  # noqa: E402


VALIDATOR_PATH = ROOT / "scripts" / "validate_v4_rc.py"
VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "validate_v4_rc_for_app_canary_test", VALIDATOR_PATH
)
assert VALIDATOR_SPEC and VALIDATOR_SPEC.loader
validator = importlib.util.module_from_spec(VALIDATOR_SPEC)
VALIDATOR_SPEC.loader.exec_module(validator)

NOW = datetime(2026, 7, 28, 1, 2, 3, tzinfo=timezone.utc)
CANDIDATE = "a" * 40


def integrity_inputs(parent: Path) -> dict[str, Path]:
    root = parent / "host-inputs"
    root.mkdir(exist_ok=True)
    config = root / "config.toml"
    auth = root / "auth.json"
    if not config.exists():
        config.write_bytes(b'model = "synthetic"\n')
    if not auth.exists():
        auth.write_bytes(b'{"auth":"synthetic"}\n')
    return {"host_auth": auth.resolve(), "host_config": config.resolve()}


class FakeCanaryProvider:
    def __init__(self, workspace: Path, *, mode: str = "pass") -> None:
        self.workspace = workspace
        self.mode = mode
        self.provider_id = "raw-disposable-host-task-identity"
        self.task_create_count = 0
        self.task_result_read_count = 0
        self.lifecycle_read_count = 0
        self.delivery_readback_count = 0
        self.duplicate_invoke_rejection_count = 0
        self.provider_resend_count = 0
        self.terminal_wait_read_count = 0
        self.protocol_preflight_count = 0
        self.record = None

    @property
    def metrics(self):
        return {
            "delivery_readback_count": self.delivery_readback_count,
            "duplicate_invoke_rejection_count": self.duplicate_invoke_rejection_count,
            "lifecycle_read_count": self.lifecycle_read_count,
            "provider_resend_count": self.provider_resend_count,
            "task_create_count": self.task_create_count,
            "task_result_read_count": self.task_result_read_count,
            "terminal_wait_read_count": self.terminal_wait_read_count,
        }

    def preflight(self):
        self.protocol_preflight_count += 1
        if self.mode == "protocol-drift":
            raise HostUnavailable("synthetic protocol drift")
        return {"schema_digest": "f" * 64}

    def capability_snapshot(self):
        rows = []
        for name in CAPABILITY_NAMES:
            rows.append(
                {
                    "assurance": "STRICT",
                    "availability": "AVAILABLE",
                    "details": {
                        "expires_at": (NOW + timedelta(minutes=5))
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "identity_ref": f"synthetic-capability-{name}",
                        "issuer_ref": canary.CANARY_ISSUER,
                        "issuer_trust": canary.CANARY_TRUST,
                        "observed_at": NOW.isoformat().replace("+00:00", "Z"),
                        "source": "synthetic-disposable-canary",
                    },
                    "name": name,
                    "receipt_ref": f"synthetic-capability-receipt-{name}",
                }
            )
        return {"capabilities": rows, "schema_version": HOST_SCHEMA_VERSION}

    def invoke(self, action, payload, provider_idempotency_key):
        self.task_create_count += 1
        if self.task_create_count > 1:
            self.duplicate_invoke_rejection_count += 1
        if self.mode != "unknown":
            (self.workspace / canary.CANARY_OUTPUT_FILENAME).write_bytes(
                canary.CANARY_OUTPUT_BYTES
            )
        self.record = {
            "action": action,
            "idempotency_key": provider_idempotency_key,
            "provider_id": self.provider_id,
            "schema_version": HOST_SCHEMA_VERSION,
            "status": "OBSERVED",
            "subject_id": str(payload["target_ref"]),
            "trust": "authoritative",
        }
        if self.mode == "unknown":
            raise HostResponseLost("synthetic response lost")
        return {**self.record, "status": "ACCEPTED", "trust": "cooperative"}

    def readback(self, action, provider_idempotency_key):
        self.delivery_readback_count += 1
        if self.mode == "unknown":
            return None
        assert self.record is not None
        return dict(self.record)

    def read_task_result(self, provider_id):
        self.task_result_read_count += 1
        if provider_id != self.provider_id:
            raise AssertionError("foreign provider identity")
        outcome = "FAILED" if self.mode == "failed" else "PASS"
        text = (
            'LOOPSKILL4_RESULT={"outcome":"'
            + outcome
            + '","summary":"disposable canary completed"}'
        )
        return {
            "provider_id": provider_id,
            "result_digest": domain_digest("loopskill-host-result-v1\n", text),
            "result_text": text,
            "schema_version": HOST_SCHEMA_VERSION,
            "status": "FAILED" if self.mode == "failed" else "COMPLETED",
            "trust": "authoritative",
        }

    def read_resource(self, resource_kind, provider_id):
        if resource_kind != "lifecycle" or provider_id != self.provider_id:
            raise AssertionError("unexpected resource read")
        self.lifecycle_read_count += 1
        return {
            "provider_id": provider_id,
            "resource_kind": resource_kind,
            "schema_version": HOST_SCHEMA_VERSION,
            "state": "TERMINAL",
            "trust": "authoritative",
        }

    def wait_for_terminal(self, *, timeout_seconds=300.0):
        if timeout_seconds <= 0:
            raise ValueError("invalid wait")
        self.terminal_wait_read_count += 1


class V4DisposableExecCanaryEntryTests(unittest.TestCase):
    def run_pass(self, evidence: Path):
        providers = []
        confirmations = []
        waits = []

        def factory(workspace):
            provider = FakeCanaryProvider(workspace)
            providers.append(provider)
            return provider

        def confirm(boundary):
            self.assertEqual(providers, [])
            self.assertFalse((evidence / "store").exists())
            confirmations.append(boundary)
            return True

        def wait(provider, workspace):
            waits.append((provider, workspace))
            self.assertEqual(provider.task_create_count, 1)
            provider.wait_for_terminal(timeout_seconds=300.0)

        receipt = canary.run_canary(
            CANDIDATE,
            evidence,
            confirmation_callback=confirm,
            integrity_inputs=integrity_inputs(evidence.parent),
            provider_factory=factory,
            wait_callback=wait,
            clock=lambda: NOW,
            token_factory=lambda: "000000000000000000000001",
        )
        return receipt, providers[0], confirmations, waits

    def test_pass_uses_real_entry_once_and_emits_closed_minimized_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(
                hashlib.sha256(canary.CANARY_OUTPUT_BYTES).hexdigest(),
                canary.CANARY_OUTPUT_SHA256,
            )
            evidence = Path(temporary) / "evidence"
            with mock.patch.object(
                canary, "start_loop", wraps=canary.start_loop
            ) as start, mock.patch.object(
                canary, "sync_loop", wraps=canary.sync_loop
            ) as sync:
                receipt, provider, confirmations, waits = self.run_pass(evidence)

            start.assert_called_once()
            sync.assert_called_once()
            self.assertEqual(len(confirmations), 1)
            self.assertEqual(len(waits), 1)
            self.assertNotIn("loop_ref", confirmations[0])
            self.assertNotIn("control_namespace", confirmations[0])
            self.assertEqual(provider.task_create_count, 1)
            self.assertEqual(provider.task_result_read_count, 1)
            self.assertEqual(provider.lifecycle_read_count, 1)
            self.assertEqual(provider.provider_resend_count, 0)
            self.assertEqual(provider.duplicate_invoke_rejection_count, 0)
            self.assertEqual(provider.terminal_wait_read_count, 1)
            self.assertEqual(provider.protocol_preflight_count, 1)
            validator.validate_canary_receipt(receipt, CANDIDATE)
            self.assertEqual(
                receipt["canary_output_sha256"], canary.CANARY_OUTPUT_SHA256
            )
            self.assertEqual(receipt["host_create_readback_count"], 1)
            self.assertEqual(receipt["host_lifecycle_readback_count"], 1)
            self.assertEqual(receipt["host_terminal_wait_readback_count"], 1)
            self.assertEqual(receipt["host_total_read_count"], 4)
            self.assertEqual(receipt["config_bytes_changed"], 0)
            self.assertEqual(receipt["host_integrity_changed_input_count"], 0)
            self.assertEqual(
                receipt["host_config_before_digest"],
                receipt["host_config_after_digest"],
            )
            self.assertEqual(
                receipt["host_auth_before_digest"],
                receipt["host_auth_after_digest"],
            )
            self.assertEqual(
                receipt["fresh_until"], "2026-07-28T01:12:03Z"
            )
            self.assertRegex(receipt["host_result_digest"], r"^[0-9a-f]{64}$")

            receipt_path = evidence / canary.CANARY_RECEIPT_FILENAME
            self.assertEqual(json.loads(receipt_path.read_text()), receipt)
            self.assertEqual(stat.S_IMODE(evidence.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(receipt_path.stat().st_mode), 0o600)
            self.assertTrue((evidence / "prepared" / CONFIRMATION_FILENAME).is_file())
            manifest = json.loads(
                (evidence / "prepared" / MANIFEST_FILENAME).read_text(encoding="utf-8")
            )
            self.assertIn(CANDIDATE, manifest["goal"])
            self.assertIn("exactly one LF byte", manifest["goal"])
            self.assertEqual(
                manifest["acceptance_criteria"],
                [
                    "artifact-changed",
                    f"file-exists:{canary.CANARY_OUTPUT_FILENAME}",
                    (
                        f"file-sha256:{canary.CANARY_OUTPUT_FILENAME}="
                        f"{canary.CANARY_OUTPUT_SHA256}"
                    ),
                ],
            )
            self.assertEqual(
                (evidence / "workspace" / canary.CANARY_OUTPUT_FILENAME).read_bytes(),
                canary.CANARY_OUTPUT_BYTES,
            )

            live, _ = canary._live_summary(
                CANDIDATE, evidence / "store", evidence / "workspace"
            )
            self.assertEqual(live["report_state"], "ACCEPTED")
            self.assertEqual(
                receipt["host_receipt_digest"],
                canary._domain_digest(canary.CANARY_LIVE_DOMAIN, live),
            )
            serialized = json.dumps(receipt, sort_keys=True)
            self.assertNotIn(provider.provider_id, serialized)
            self.assertNotIn(str(evidence), serialized)
            self.assertNotIn("thread_id", serialized)
            self.assertNotIn("result_text", serialized)
            with SQLiteStore(evidence / "store" / STORE_FILENAME) as store:
                snapshot = store.snapshot(store.loop_descriptors()[0]["loop_ref"])
                self.assertEqual(snapshot["execution"]["state"], "TERMINAL")
                self.assertEqual(snapshot["execution"]["disposition"], "SUCCEEDED")

    def test_declined_confirmation_has_zero_provider_and_no_pass_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "evidence"
            factory = mock.Mock(side_effect=AssertionError("provider constructed"))
            with mock.patch.object(
                canary, "start_loop", wraps=canary.start_loop
            ) as start, mock.patch.object(
                canary, "sync_loop", wraps=canary.sync_loop
            ) as sync, self.assertRaisesRegex(
                canary.CanaryError, "CANARY_CONFIRMATION_DECLINED"
            ):
                canary.run_canary(
                    CANDIDATE,
                    evidence,
                    confirmation_callback=lambda boundary: False,
                    provider_factory=factory,
                    wait_callback=lambda provider, workspace: None,
                    clock=lambda: NOW,
                    token_factory=lambda: "000000000000000000000002",
                )
            factory.assert_not_called()
            start.assert_not_called()
            sync.assert_not_called()
            self.assertTrue((evidence / "prepared" / MANIFEST_FILENAME).is_file())
            self.assertFalse((evidence / "store").exists())
            self.assertFalse((evidence / canary.CANARY_RECEIPT_FILENAME).exists())

    def test_protocol_preflight_drift_fails_before_start_or_host_effect(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "evidence"
            providers = []

            def factory(workspace):
                provider = FakeCanaryProvider(workspace, mode="protocol-drift")
                providers.append(provider)
                return provider

            with mock.patch.object(
                canary, "start_loop", wraps=canary.start_loop
            ) as start, mock.patch.object(
                canary, "sync_loop", wraps=canary.sync_loop
            ) as sync, self.assertRaisesRegex(
                canary.CanaryError, "CANARY_HOST_PROTOCOL_INCOMPATIBLE"
            ):
                canary.run_canary(
                    CANDIDATE,
                    evidence,
                    confirmation_callback=lambda boundary: True,
                    integrity_inputs=integrity_inputs(Path(temporary)),
                    provider_factory=factory,
                    wait_callback=lambda provider, workspace: None,
                    clock=lambda: NOW,
                    token_factory=lambda: "000000000000000000000005",
                )
            provider = providers[0]
            start.assert_not_called()
            sync.assert_not_called()
            self.assertEqual(provider.protocol_preflight_count, 1)
            self.assertEqual(provider.task_create_count, 0)
            self.assertFalse((evidence / "store").exists())
            self.assertFalse((evidence / canary.CANARY_RECEIPT_FILENAME).exists())

    def test_unknown_and_failed_outcomes_do_not_retry_or_emit_pass(self):
        for mode, task_reads, lifecycle_reads in (
            ("unknown", 0, 0),
            ("failed", 1, 1),
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                evidence = Path(temporary) / "evidence"
                providers = []

                def factory(workspace):
                    provider = FakeCanaryProvider(workspace, mode=mode)
                    providers.append(provider)
                    return provider

                with mock.patch.object(
                    canary, "start_loop", wraps=canary.start_loop
                ) as start, mock.patch.object(
                    canary, "sync_loop", wraps=canary.sync_loop
                ) as sync, self.assertRaisesRegex(
                    canary.CanaryError, "CANARY_OUTCOME_NOT_PASS"
                ):
                    canary.run_canary(
                        CANDIDATE,
                        evidence,
                        confirmation_callback=lambda boundary: True,
                        integrity_inputs=integrity_inputs(Path(temporary)),
                        provider_factory=factory,
                        wait_callback=lambda provider, workspace: None,
                        clock=lambda: NOW,
                        token_factory=lambda: "000000000000000000000003",
                    )
                provider = providers[0]
                start.assert_called_once()
                sync.assert_called_once()
                self.assertEqual(provider.task_create_count, 1)
                self.assertEqual(provider.task_result_read_count, task_reads)
                self.assertEqual(provider.lifecycle_read_count, lifecycle_reads)
                self.assertEqual(provider.provider_resend_count, 0)
                self.assertFalse((evidence / canary.CANARY_RECEIPT_FILENAME).exists())
                self.assertTrue((evidence / "store" / STORE_FILENAME).is_file())

    def test_candidate_and_evidence_root_validation_fail_before_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            invalid = parent / "invalid-candidate"
            with self.assertRaisesRegex(
                canary.CanaryError, "CANARY_CANDIDATE_SHA_INVALID"
            ):
                canary.run_canary(
                    "A" * 40,
                    invalid,
                    confirmation_callback=lambda boundary: True,
                    provider_factory=lambda workspace: FakeCanaryProvider(workspace),
                    wait_callback=lambda provider, workspace: None,
                )
            self.assertFalse(invalid.exists())

            nonempty = parent / "nonempty"
            nonempty.mkdir(mode=0o700)
            (nonempty / "foreign").write_text("do not touch", encoding="utf-8")
            with self.assertRaisesRegex(
                canary.CanaryError, "CANARY_EVIDENCE_ROOT_INVALID"
            ):
                canary.run_canary(
                    CANDIDATE,
                    nonempty,
                    confirmation_callback=lambda boundary: True,
                    provider_factory=lambda workspace: FakeCanaryProvider(workspace),
                    wait_callback=lambda provider, workspace: None,
                )
            self.assertEqual((nonempty / "foreign").read_text(), "do not touch")

    def test_local_safety_helpers_fail_closed_without_host_effects(self):
        self.assertIsNotNone(canary._now().tzinfo)
        self.assertRegex(canary._token(), r"^[0-9a-f]{24}$")
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            empty = parent / "empty"
            empty.mkdir(mode=0o700)
            self.assertEqual(canary._ensure_empty_private_root(empty), empty)

            exposed = parent / "exposed"
            exposed.mkdir(mode=0o700)
            exposed.chmod(0o750)
            with self.assertRaisesRegex(
                canary.CanaryError, "CANARY_EVIDENCE_ROOT_INVALID"
            ):
                canary._ensure_empty_private_root(exposed)

            workspace = parent / "workspace"
            workspace.mkdir()
            with self.assertRaisesRegex(canary.CanaryError, "CANARY_OUTPUT_INVALID"):
                canary._verify_workspace(workspace)
            output = workspace / canary.CANARY_OUTPUT_FILENAME
            output.write_bytes(b"wrong")
            with self.assertRaisesRegex(canary.CanaryError, "CANARY_OUTPUT_INVALID"):
                canary._verify_workspace(workspace)
            output.unlink()
            output.mkdir()
            with self.assertRaisesRegex(canary.CanaryError, "CANARY_OUTPUT_INVALID"):
                canary._verify_workspace(workspace)

            wait_workspace = parent / "wait"
            wait_workspace.mkdir()
            waiter = mock.Mock()
            canary._default_wait(
                SimpleNamespace(wait_for_terminal=waiter),
                wait_workspace,
                timeout_seconds=0.1,
            )
            waiter.assert_called_once_with(timeout_seconds=0.1)
            with self.assertRaisesRegex(
                canary.CanaryError, "CANARY_TERMINAL_WAIT_UNAVAILABLE"
            ):
                canary._default_wait(object(), wait_workspace, timeout_seconds=0.1)

        valid_metrics = {
            "delivery_readback_count": 1,
            "duplicate_invoke_rejection_count": 0,
            "lifecycle_read_count": 1,
            "provider_resend_count": 0,
            "task_create_count": 1,
            "task_result_read_count": 1,
            "terminal_wait_read_count": 1,
        }
        self.assertEqual(
            canary._provider_metrics(SimpleNamespace(metrics=lambda: valid_metrics)),
            valid_metrics,
        )
        eventual_metrics = {**valid_metrics, "delivery_readback_count": 3}
        self.assertEqual(
            canary._provider_metrics(SimpleNamespace(metrics=eventual_metrics)),
            eventual_metrics,
        )
        for raw, code in (
            (None, "CANARY_PROVIDER_METRICS_UNAVAILABLE"),
            ({**valid_metrics, "task_create_count": True}, "CANARY_PROVIDER_METRICS_INVALID"),
            ({**valid_metrics, "task_create_count": 2}, "CANARY_PROVIDER_METRICS_INVALID"),
            ({**valid_metrics, "delivery_readback_count": 4}, "CANARY_PROVIDER_METRICS_INVALID"),
            ({**valid_metrics, "terminal_wait_read_count": 0}, "CANARY_PROVIDER_METRICS_INVALID"),
        ):
            with self.subTest(metrics=raw), self.assertRaisesRegex(
                canary.CanaryError, code
            ):
                canary._provider_metrics(SimpleNamespace(metrics=raw))
        with self.assertRaisesRegex(canary.CanaryError, "SINGLE_INVALID"):
            canary._single({}, "SINGLE_INVALID")
        with self.assertRaisesRegex(canary.CanaryError, "SINGLE_INVALID"):
            canary._single({"one": 1}, "SINGLE_INVALID")

    def test_integrity_inputs_are_required_and_mutation_is_persisted_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            missing_evidence = parent / "missing-evidence"
            factory = mock.Mock(side_effect=AssertionError("provider constructed"))
            with self.assertRaisesRegex(
                canary.CanaryError, "CANARY_INTEGRITY_INPUTS_MISSING"
            ):
                canary.run_canary(
                    CANDIDATE,
                    missing_evidence,
                    confirmation_callback=lambda boundary: True,
                    provider_factory=factory,
                    clock=lambda: NOW,
                )
            factory.assert_not_called()

            inputs = integrity_inputs(parent)
            evidence = parent / "mutated-evidence"

            def mutate_after_wait(provider, workspace):
                provider.wait_for_terminal(timeout_seconds=1)
                inputs["host_config"].write_bytes(b'model = "changed"\n')

            with self.assertRaisesRegex(
                canary.CanaryError, "CANARY_HOST_INTEGRITY_CHANGED"
            ):
                canary.run_canary(
                    CANDIDATE,
                    evidence,
                    confirmation_callback=lambda boundary: True,
                    integrity_inputs=inputs,
                    provider_factory=lambda workspace: FakeCanaryProvider(workspace),
                    wait_callback=mutate_after_wait,
                    clock=lambda: NOW,
                    token_factory=lambda: "000000000000000000000006",
                )
            measurement = json.loads(
                (evidence / canary.CANARY_INTEGRITY_FILENAME).read_text()
            )
            self.assertEqual(measurement["changed_input_count"], 1)
            self.assertGreater(measurement["total_changed_bytes"], 0)
            self.assertFalse((evidence / canary.CANARY_RECEIPT_FILENAME).exists())

    def test_auth_mutation_is_measured_and_cannot_mint_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            inputs = integrity_inputs(parent)
            evidence = parent / "auth-mutated-evidence"

            def mutate_after_wait(provider, workspace):
                provider.wait_for_terminal(timeout_seconds=1)
                inputs["host_auth"].write_bytes(b'{"changed":true}\n')

            with self.assertRaisesRegex(
                canary.CanaryError, "CANARY_HOST_INTEGRITY_CHANGED"
            ):
                canary.run_canary(
                    CANDIDATE,
                    evidence,
                    confirmation_callback=lambda boundary: True,
                    integrity_inputs=inputs,
                    provider_factory=lambda workspace: FakeCanaryProvider(workspace),
                    wait_callback=mutate_after_wait,
                    clock=lambda: NOW,
                    token_factory=lambda: "000000000000000000000007",
                )
            measurement = json.loads(
                (evidence / canary.CANARY_INTEGRITY_FILENAME).read_text()
            )
            self.assertGreater(measurement["changed_bytes"]["host_auth"], 0)
            self.assertEqual(measurement["changed_bytes"]["host_config"], 0)
            self.assertFalse((evidence / canary.CANARY_RECEIPT_FILENAME).exists())

    def test_default_provider_construction_occurs_only_after_confirmation(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "evidence"
            providers = []

            def construct(workspace, **kwargs):
                self.assertTrue((evidence / "prepared" / CONFIRMATION_FILENAME).is_file())
                self.assertEqual(kwargs["issuer_ref"], canary.CANARY_ISSUER)
                self.assertEqual(kwargs["issuer_trust"], canary.CANARY_TRUST)
                provider = FakeCanaryProvider(workspace)
                providers.append(provider)
                return provider

            with mock.patch.object(
                canary, "CodexExecProvider", side_effect=construct
            ) as constructor, mock.patch.object(
                canary, "_default_wait", wraps=canary._default_wait
            ) as wait:
                receipt = canary.run_canary(
                    CANDIDATE,
                    evidence,
                    confirmation_callback=lambda boundary: True,
                    integrity_inputs=integrity_inputs(Path(temporary)),
                    clock=lambda: NOW,
                    token_factory=lambda: "000000000000000000000004",
                )
            constructor.assert_called_once()
            wait.assert_called_once_with(providers[0], evidence / "workspace")
            self.assertEqual(providers[0].terminal_wait_read_count, 1)
            self.assertEqual(providers[0].protocol_preflight_count, 1)
            self.assertEqual(receipt["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
