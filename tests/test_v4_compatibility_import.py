from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "codex-loop-prompt-architect" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))

from loop_architect.state_runtime import (  # noqa: E402
    OPENAI_CODE_SIGN_IDENTIFIER,
    OPENAI_CODE_SIGN_TEAM_ID,
    TRUSTED_HOST_BOUNDARY,
    TrustedHostAttestation,
)
from loop_architect.v4_alpha.protocol import (  # noqa: E402
    InjectedCrash,
    snapshot_digest,
)
from loop_architect.v4_compat import (  # noqa: E402
    V3CompatibilityError,
    cancel_import,
    confirm_import,
    legacy_intake,
    legacy_prepare,
    preview_import,
    shadow_read,
)
from loop_architect.v4_compat import importer  # noqa: E402
from loop_architect.v4_persistence.sqlite_store import (  # noqa: E402
    DURABLE_FAULT_BOUNDARIES,
    SQLiteStore,
)
from state_runtime_support import (  # noqa: E402
    Harness,
    T1,
    T2,
    digest,
    expected_projection_digest,
)


class _AcceptAllValidator:
    @classmethod
    def check_schema(cls, _: object) -> None:
        return None

    def __init__(self, *_: object, **__: object) -> None:
        pass

    def iter_errors(self, _: object) -> tuple[()]:
        return ()


class _FormatChecker:
    pass


@contextmanager
def _public_runtime_without_optional_jsonschema():
    module = types.SimpleNamespace(
        Draft202012Validator=_AcceptAllValidator,
        FormatChecker=_FormatChecker,
    )
    for name in ("adaptive_state_mcp", "verify_installation"):
        sys.modules.pop(name, None)
    with mock.patch.dict(sys.modules, {"jsonschema": module}):
        try:
            yield
        finally:
            for name in ("adaptive_state_mcp", "verify_installation"):
                sys.modules.pop(name, None)


def _host_attestation() -> TrustedHostAttestation:
    return TrustedHostAttestation(
        boundary=TRUSTED_HOST_BOUNDARY,
        parent_pid=4242,
        parent_executable="/Applications/ChatGPT.app/Contents/Resources/codex",
        parent_identifier=OPENAI_CODE_SIGN_IDENTIFIER,
        parent_team_id=OPENAI_CODE_SIGN_TEAM_ID,
        parent_cdhash="b" * 64,
    )


def _gateway_call(
    server: object,
    root: Path,
    request: dict[str, object],
) -> dict[str, object]:
    import adaptive_state_mcp as mcp  # noqa: PLC0415

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": f"gateway-{request['request_id']}",
            "method": "tools/call",
            "params": {
                "name": mcp.MCP_STATE_GATEWAY_TOOL_NAME,
                "_meta": {
                    "threadId": "controller-1",
                    "x-codex-turn-metadata": {
                        "session_id": "controller-1",
                        "thread_id": "controller-1",
                        "turn_id": "real-app-turn-1",
                    },
                },
                "arguments": {"root": str(root), "request": request},
            },
        }
    )
    if response is None:
        raise AssertionError("missing MCP response")
    return response["result"]["structuredContent"]


def _paused_schema3(root: Path, *, objective: str = "Execute g1") -> Harness:
    import adaptive_state_mcp as mcp  # noqa: PLC0415

    harness = Harness(root)
    definition = None
    if objective != "Execute g1":
        from state_runtime_support import goal  # noqa: PLC0415

        definition = {"g1": goal("g1", "m1", objective=objective)}
    initialized, _ = harness.initialize(definitions=definition)
    if not initialized["ok"]:
        raise AssertionError(initialized)
    steering_id = "v4-import-pause"
    recorded = harness.apply(
        {
            "type": "RECORD_STEERING",
            "steering_id": steering_id,
            "steering_type": "PAUSE",
            "normalized_digest": digest(steering_id),
            "identity_algorithm": "message-item-v1",
            "message_item_id": "v4-import-pause-message",
            "summary": "pause for v4 migration preview",
            "classification_reason": "fixture-only safe-point import",
        }
    )
    if not recorded["ok"]:
        raise AssertionError(recorded)
    paused = harness.apply(
        {
            "type": "SET_RUN_CONTROL",
            "steering_id": steering_id,
            "requested_status": "PAUSE",
            "reason": "fixture-only v4 import",
        }
    )
    if paused.get("operation_status") != "PAUSED_AT_SAFE_POINT":
        raise AssertionError(paused)
    server = mcp.AdaptiveStateMcpServer(_host_attestation())
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": "initialize",
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        }
    )
    if response is None or "result" not in response:
        raise AssertionError(response)
    source_digest = "sha256:" + hashlib.sha256(
        harness.runtime._render_state(harness.state())  # noqa: SLF001
    ).hexdigest()
    migrated = _gateway_call(
        server,
        root,
        {
            "request_id": "fixture-v2-to-v3",
            "operation": "MIGRATE_V2_TO_V3",
            "occurred_at": T2,
            "parameters": {"source_state_digest": source_digest},
        },
    )
    if not migrated["ok"]:
        raise AssertionError(migrated)
    state = harness.state()
    if state["schema_version"] != 3 or state["run_control"]["status"] != "PAUSED_AT_SAFE_POINT":
        raise AssertionError(state)
    return harness


def _terminal_v338(root: Path) -> Harness:
    harness = Harness(root)
    initialized, _ = harness.initialize()
    if not initialized["ok"]:
        raise AssertionError(initialized)
    harness.register_control_result(
        "GOAL",
        "terminal-controller-goal-create",
        "controller-1",
        {"action": "CREATE", "marker_digest": digest("goal-marker")},
        {"goal_id": "native-goal-1", "status": "ACTIVE"},
    )
    harness.register_control_result(
        "AUTOMATION",
        "terminal-automation-create",
        "controller-1",
        {"action": "CREATE", "config_digest": digest("automation-config")},
        {"automation_id": "heartbeat-1", "status": "ACTIVE"},
    )
    worker = harness.worker_pass()
    code_review = harness.review("CODE_REVIEW", "REVIEW_PASS", worker)
    roadmap_claim = harness.acquire()
    roadmap_audit = harness.review(
        "ROADMAP_AUDIT",
        "ROADMAP_AUDIT_PASS_FINAL_CANDIDATE",
        worker,
        code_review_id=code_review,
        claim=roadmap_claim,
    )
    final_audit = harness.review(
        "FINAL_AUDIT",
        "FINAL_REVIEW_PASS",
        worker,
        code_review_id=code_review,
        roadmap_audit_id=roadmap_audit,
    )
    mutation = {
        "type": "FINALIZE_LOOP",
        "lease_claim": harness.acquire(),
        "observed_at": T1,
        "base_roadmap_version": 1,
        "final_goal_id": "g1",
        "worker_dispatch_id": worker["dispatch_id"],
        "artifact_digest": worker["artifact_digest"],
        "code_review_id": code_review,
        "roadmap_audit_id": roadmap_audit,
        "final_audit_id": final_audit,
        "terminal_status": "LOOP_COMPLETE",
        "projection_digest": digest("placeholder"),
        "finalization_id": "terminal-finalization-1",
        "controller_goal_id": "native-goal-1",
        "automation_id": "heartbeat-1",
    }
    mutation["projection_digest"] = expected_projection_digest(
        harness.state(), mutation
    )
    finalized = harness.apply(mutation)
    if finalized.get("operation_status") != "FINALIZE_LOOP_APPLIED":
        raise AssertionError(finalized)
    if harness.state()["terminal_status"] != "LOOP_COMPLETE":
        raise AssertionError(harness.state())
    return harness


class V4CompatibilityImportTests(unittest.TestCase):
    def test_public_v338_provenance_is_exact(self) -> None:
        self.assertEqual(
            subprocess.check_output(
                ["git", "rev-parse", "v3.3.8^{}"], cwd=ROOT, text=True
            ).strip(),
            importer.PUBLIC_V3_BASE_SHA,
        )
        paths = {
            "codex-loop-prompt-architect/scripts/loop_architect/state_runtime.py": importer.V3_RUNTIME_BLOB_SHA,
            "codex-loop-prompt-architect/references/adaptive-state.schema.json": importer.V3_STATE_SCHEMA_BLOB_SHA,
            "codex-loop-prompt-architect/references/adaptive-mutation.schema.json": importer.V3_MUTATION_SCHEMA_BLOB_SHA,
        }
        for path, expected in paths.items():
            with self.subTest(path=path):
                actual = subprocess.check_output(
                    ["git", "rev-parse", f"v3.3.8:{path}"], cwd=ROOT, text=True
                ).strip()
                self.assertEqual(actual, expected)

    def test_shadow_preview_is_read_only_and_cancel_creates_no_destination(self) -> None:
        with _public_runtime_without_optional_jsonschema(), tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "v3"
            destination = base / "v4"
            source.mkdir()
            _paused_schema3(source)
            state_path = source / importer.V3_STATE_RELATIVE_PATH
            before = state_path.read_bytes()
            plan = shadow_read(source, destination)
            self.assertFalse(destination.exists())
            self.assertEqual(state_path.read_bytes(), before)
            self.assertEqual(cancel_import(plan), plan.preview)
            self.assertFalse(destination.exists())
            self.assertEqual(state_path.read_bytes(), before)

    def test_confirm_import_is_one_way_paused_and_exactly_replayable(self) -> None:
        with _public_runtime_without_optional_jsonschema(), tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "v3"
            destination = base / "v4"
            source.mkdir()
            harness = _paused_schema3(source)
            state_path = source / importer.V3_STATE_RELATIVE_PATH
            before = state_path.read_bytes()
            plan = preview_import(source, destination)
            first = confirm_import(plan)
            second = confirm_import(plan)
            self.assertFalse(first.replayed)
            self.assertTrue(second.replayed)
            self.assertEqual(first.loop_ref, second.loop_ref)
            self.assertEqual(first.snapshot_digest, second.snapshot_digest)
            self.assertEqual(state_path.read_bytes(), before)
            self.assertEqual(harness.state()["state_version"], plan.preview.source_state_version)
            with SQLiteStore(destination / importer.STORE_FILENAME) as store:
                snapshot = store.snapshot(first.loop_ref)
                self.assertIsNotNone(snapshot)
                self.assertEqual(snapshot["execution"]["state"], "PAUSED")
                self.assertEqual(snapshot["closure_assurance"]["strength"], "NONE")
                self.assertEqual(
                    snapshot["import_provenance"]["source_state_digest"],
                    plan.preview.source_state_digest,
                )
                self.assertEqual(store.commit_count, 1)
                self.assertEqual(store.ready_effect_attempts(), ())
                self.assertEqual(
                    [event["type"] for event in store.events(first.loop_ref)],
                    ["LoopCreated", "GoalRegistered", "V3SnapshotImported", "LoopPaused"],
                )

    def test_nonpaused_active_lease_and_nonquiescent_outbox_fail_closed(self) -> None:
        with _public_runtime_without_optional_jsonschema(), tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "v3"
            source.mkdir()
            harness = Harness(source)
            initialized, _ = harness.initialize(state_gateway=True)
            self.assertTrue(initialized["ok"], initialized)
            with self.assertRaises(V3CompatibilityError) as raised:
                preview_import(source, base / "v4")
            self.assertEqual(raised.exception.code, "MIGRATION_NOT_QUIESCENT")

    def test_schema2_standard_state_is_readable_by_v3_but_not_shape_copied(self) -> None:
        with _public_runtime_without_optional_jsonschema(), tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "v3-standard"
            source.mkdir()
            harness = Harness(source)
            initialized, _ = harness.initialize()
            self.assertTrue(initialized["ok"], initialized)
            self.assertEqual(harness.state()["schema_version"], 2)
            with self.assertRaises(V3CompatibilityError) as raised:
                preview_import(source, base / "v4")
            self.assertEqual(raised.exception.code, "MIGRATION_SOURCE_INVALID")

    def test_terminal_revival_is_rejected_before_goal_projection(self) -> None:
        with _public_runtime_without_optional_jsonschema(), tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "v3"
            source.mkdir()
            harness = _terminal_v338(source)
            state_before = harness.runtime._render_state(harness.state())  # noqa: SLF001
            with self.assertRaises(V3CompatibilityError) as raised:
                preview_import(source, base / "v4")
            self.assertEqual(
                raised.exception.code, "MIGRATION_TERMINAL_REVIVAL_FORBIDDEN"
            )
            self.assertEqual(
                (source / importer.V3_STATE_RELATIVE_PATH).read_bytes(),
                state_before,
            )

    def test_changed_source_after_preview_fails_without_destination_write(self) -> None:
        with _public_runtime_without_optional_jsonschema(), tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "v3"
            destination = base / "v4"
            source.mkdir()
            harness = _paused_schema3(source)
            plan = preview_import(source, destination)
            state = harness.state()
            state["goal_definition_registry"]["g1"]["objective"] = "changed after preview"
            (source / importer.V3_STATE_RELATIVE_PATH).write_bytes(
                harness.runtime._render_state(state)  # noqa: SLF001
            )
            with self.assertRaises(V3CompatibilityError) as raised:
                confirm_import(plan)
            self.assertEqual(raised.exception.code, "MIGRATION_SOURCE_CHANGED")
            self.assertFalse(destination.exists())

    def test_destination_nonempty_and_overlapping_roots_are_rejected(self) -> None:
        with _public_runtime_without_optional_jsonschema(), tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "v3"
            destination = base / "v4"
            source.mkdir()
            _paused_schema3(source)
            destination.mkdir()
            (destination / "foreign.txt").write_text("foreign", encoding="utf-8")
            with self.assertRaises(V3CompatibilityError) as raised:
                preview_import(source, destination)
            self.assertEqual(raised.exception.code, "MIGRATION_DESTINATION_NOT_EMPTY")
            with self.assertRaises(V3CompatibilityError) as overlap:
                preview_import(source, source / "v4")
            self.assertEqual(overlap.exception.code, "DUAL_WRITE_FORBIDDEN")

            empty_destination = base / "planned-v4"
            plan = preview_import(source, empty_destination)
            swapped_target = base / "swapped-target"
            swapped_target.mkdir()
            empty_destination.symlink_to(swapped_target, target_is_directory=True)
            with self.assertRaises(V3CompatibilityError) as swapped:
                confirm_import(plan)
            self.assertEqual(swapped.exception.code, "MIGRATION_SOURCE_CHANGED")
            self.assertEqual(tuple(swapped_target.iterdir()), ())

    def test_import_command_is_atomic_at_every_sqlite_boundary(self) -> None:
        with _public_runtime_without_optional_jsonschema(), tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "v3"
            source.mkdir()
            _paused_schema3(source)
            source_before = (source / importer.V3_STATE_RELATIVE_PATH).read_bytes()
            for boundary in DURABLE_FAULT_BOUNDARIES:
                with self.subTest(boundary=boundary):
                    destination = base / f"v4-{boundary}"
                    plan = preview_import(source, destination)
                    destination.mkdir(mode=0o700)
                    loop_ref, authority, command = importer._import_command(plan)  # noqa: SLF001
                    path = destination / importer.STORE_FILENAME
                    with self.assertRaises(InjectedCrash):
                        with SQLiteStore(path, authority) as store:
                            store.apply(command, fault_at=boundary)
                    with SQLiteStore(path, authority) as recovered:
                        result = recovered.apply(command)
                        snapshot = recovered.snapshot(loop_ref)
                        self.assertIsNotNone(snapshot)
                        self.assertEqual(recovered.commit_count, 1)
                        self.assertEqual(recovered.ready_effect_attempts(), ())
                        self.assertEqual(result.snapshot_digest, snapshot_digest(snapshot))
                    self.assertEqual(
                        (source / importer.V3_STATE_RELATIVE_PATH).read_bytes(),
                        source_before,
                    )


class V4LegacyEntryCompatibilityTests(unittest.TestCase):
    def _example(self, name: str) -> tuple[bytes, dict[str, object]]:
        raw = (ROOT / "examples" / name).read_bytes()
        return raw, json.loads(raw.decode("utf-8"))

    def test_exact_public_standard_and_adaptive_examples_map_to_modes(self) -> None:
        cases = (
            ("01-passkey-login-input.json", "STANDARD_LOOP"),
            ("03-adaptive-passkey-input.json", "ADAPTIVE_LOOP"),
        )
        for name, expected in cases:
            with self.subTest(name=name):
                raw, value = self._example(name)
                blob = subprocess.check_output(
                    ["git", "rev-parse", f"v3.3.8:examples/{name}"], cwd=ROOT, text=True
                ).strip()
                self.assertEqual(
                    subprocess.check_output(
                        ["git", "hash-object", "--stdin"],
                        cwd=ROOT,
                        input=raw,
                    ).decode("ascii").strip(),
                    blob,
                )
                decision = legacy_intake(value)
                self.assertEqual(decision.disposition, "READY_FOR_LOOP")
                self.assertEqual(decision.route, expected)

    def test_compact_full_and_minimal_patch_views_preserve_zero_start(self) -> None:
        _, value = self._example("01-passkey-login-input.json")
        existing = b"# Existing Controller Pack\n\nController instructions.\n"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compact = legacy_prepare(value, root / "compact", output_detail="compact")
            full = legacy_prepare(value, root / "full", output_detail="full")
            patch = legacy_prepare(
                value,
                root / "patch",
                output_detail="minimal_patch",
                existing_pack_bytes=existing,
            )
            self.assertLess(len(compact.export_bytes), len(full.export_bytes))
            self.assertIn(b"legacy Pack repair preview", patch.export_bytes)
            self.assertIn(b"Source Pack mutation: none", patch.export_bytes)
            self.assertEqual(existing, b"# Existing Controller Pack\n\nController instructions.\n")
            for item in (compact, full, patch):
                self.assertIsNone(item.prepared.confirmation)
                self.assertEqual(len(tuple(item.prepared.directory.iterdir())), 5)
                self.assertNotIn(b"threadId", item.export_bytes)

    def test_invalid_existing_pack_rejects_before_prepare_write(self) -> None:
        _, value = self._example("01-passkey-login-input.json")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "prepared"
            with self.assertRaises(ValueError):
                legacy_prepare(
                    value,
                    output,
                    output_detail="minimal_patch",
                    existing_pack_bytes=b"not a controller pack",
                )
            self.assertFalse(output.exists())

    def test_compatibility_sunset_is_explicitly_one_major_cycle(self) -> None:
        registry = json.loads(
            (
                ROOT
                / "docs/architecture/v3-to-v4-capability-preservation-register.json"
            ).read_text(encoding="utf-8")
        )
        capability = next(
            item
            for item in registry["capabilities"]
            if item["capability_id"] == "PRES-COMPAT"
        )
        self.assertEqual(capability["disposition"], "COMPAT_ONLY")
        self.assertIn("One-major-cycle", capability["v4_owner"])
        adr = (
            ROOT / "docs/adr/0011-loopskill-4-compatible-kernel-refactor.md"
        ).read_text(encoding="utf-8")
        self.assertIn("one complete v4 major cycle", adr)


if __name__ == "__main__":
    unittest.main()
