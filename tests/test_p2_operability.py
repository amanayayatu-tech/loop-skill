from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from state_runtime_support import Harness

from loop_architect.active_policy import active_prompt_source, split_policy_evidence
from loop_architect.archive_manifest_v2 import (
    ArchiveManifestError,
    build_manifest,
    read_manifest,
    validate_manifest,
    write_manifest,
)
from loop_architect.audit_views import build_audit_views
from loop_architect.content_addressing import (
    ContentAddressedStore,
    ContentAddressingError,
)
from loop_architect.risky_artifact_scanner import (
    AllowRule,
    scan,
    unallowed_credentials,
)
import loopctl


class ContentAddressingTests(unittest.TestCase):
    def test_identical_payloads_share_one_object_and_legacy_facades_remain_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            control = Path(temporary) / ".codex-loop"
            control.mkdir()
            reports = control / "reports"
            reports.mkdir()
            legacy = reports / "legacy.json"
            legacy.write_bytes(b"legacy")
            self.assertEqual(b"legacy", legacy.read_bytes())
            store = ContentAddressedStore(control)
            first = reports / "first.json"
            second = reports / "second.json"
            ref1 = store.replace_facade(
                first, b"same", category="ARTIFACT", transaction_id="one"
            )
            ref2 = store.replace_facade(
                second, b"same", category="ARTIFACT", transaction_id="two"
            )
            self.assertEqual(ref1.digest, ref2.digest)
            self.assertEqual(os.stat(first).st_ino, os.stat(second).st_ino)
            self.assertEqual(b"same", store.read(ref1))
            self.assertEqual(2, len(store.index.read_text(encoding="utf-8").splitlines()))

    def test_object_tamper_and_symlink_facade_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            control = Path(temporary) / ".codex-loop"
            control.mkdir()
            reports = control / "reports"
            reports.mkdir()
            store = ContentAddressedStore(control)
            reference = store.replace_facade(
                reports / "report.json",
                b"report",
                category="ARTIFACT",
                transaction_id="one",
            )
            (control / reference.object_path).chmod(0o600)
            (control / reference.object_path).write_bytes(b"tamper")
            with self.assertRaises(ContentAddressingError):
                store.read(reference)
            target = reports / "target"
            target.write_bytes(b"target")
            linked = reports / "linked"
            linked.symlink_to(target)
            with self.assertRaises(ContentAddressingError):
                store.replace_facade(
                    linked, b"new", category="ARTIFACT", transaction_id="two"
                )


class AuditAndPolicyTests(unittest.TestCase):
    def test_runtime_writes_addressed_audit_views_and_separates_dashboard_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = Harness(root)
            initialized, _ = harness.initialize(
                state_gateway=True, dashboard_required=True
            )
            self.assertTrue(initialized["ok"])
            for name in (
                "audit-index.json",
                "business-timeline.json",
                "goal-summaries.json",
            ):
                self.assertTrue((root / ".codex-loop" / name).is_file())
            dashboard = (root / ".codex-loop/progress-dashboard.html").read_text(
                encoding="utf-8"
            )
            self.assertIn("Business progress", dashboard)
            self.assertIn("Control-plane activity", dashboard)
            index = json.loads((root / ".codex-loop/audit-index.json").read_text())
            self.assertEqual(index["derived_from_state_version"], 1)
            self.assertTrue((root / ".codex-loop/content-addressed/index.jsonl").is_file())

    def test_audit_views_count_business_routes_separately(self) -> None:
        state = {
            "state_version": 4,
            "event_ledger": {"e1": {}, "e2": {}, "e3": {}},
            "goal_execution_ledger": {
                "g1": {
                    "status": "IN_PROGRESS",
                    "attempts": [],
                    "required_completion_class": "COMPLETE_ARTIFACT",
                    "achieved_completion_class": None,
                }
            },
            "gateway_route_ledger": {
                "r1": {
                    "route_id": "r1",
                    "route_kind": "WORKER",
                    "goal_id": "g1",
                    "status": "ACKED",
                    "prepared_at": "2026-01-01T00:00:00Z",
                    "sent_at": None,
                    "acked_at": None,
                }
            },
        }
        index = json.loads(build_audit_views(state)["audit-index.json"])
        self.assertEqual(index["business_progress"]["route_count"], 1)
        self.assertEqual(index["control_plane"]["mutation_count"], 2)

    def test_historical_model_and_heartbeat_text_never_enters_active_source(self) -> None:
        source = {
            "active": "keep",
            "historical_model_policy": "old-model-prompt",
            "nested": {"heartbeat_policy_history": ["old-heartbeat-prompt"]},
        }
        active = active_prompt_source(source)
        self.assertNotIn("historical_model_policy", active)
        self.assertNotIn("heartbeat_policy_history", active["nested"])
        split = split_policy_evidence(source)
        self.assertEqual(split["active_policy"], active)
        self.assertEqual(
            split["historical_evidence"]["historical_model_policy"],
            "old-model-prompt",
        )
        self.assertEqual(
            split["historical_evidence"]["nested"]["heartbeat_policy_history"],
            ["old-heartbeat-prompt"],
        )


class ArchiveAndScannerTests(unittest.TestCase):
    def test_loopctl_archive_check_and_emit_use_v2_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            root.mkdir()
            harness = Harness(root)
            self.assertTrue(harness.initialize(state_gateway=True)[0]["ok"])
            output = Path(temporary) / "archive.json"
            with redirect_stdout(StringIO()):
                checked = loopctl.main(
                    [
                        "archive", "--root", str(root), "--reason", "test",
                        "--check", "--emit", str(output), "--json",
                    ]
                )
            self.assertEqual(0, checked)
            self.assertFalse(output.exists())
            with redirect_stdout(StringIO()):
                emitted = loopctl.main(
                    [
                        "archive", "--root", str(root), "--reason", "test",
                        "--emit", str(output), "--json",
                    ]
                )
            self.assertEqual(0, emitted)
            self.assertEqual(read_manifest(output)["schema_version"], "archive-manifest-v2")

    def test_archive_redacts_remote_credentials_and_recovers_owned_stale_temp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            remote = "https://user:" + "secret-token@example.com/repo.git"
            subprocess.run(
                ["git", "-C", str(root), "remote", "add", "origin", remote],
                check=True,
            )
            harness = Harness(root)
            self.assertTrue(harness.initialize(state_gateway=True)[0]["ok"])
            result = loopctl.archive_root(root, "test")
            encoded = json.dumps(result, sort_keys=True)
            self.assertNotIn(remote, encoded)
            self.assertTrue(result["manifest"]["git"]["remote_configured"])
            self.assertRegex(
                result["manifest"]["git"]["remote_digest"],
                r"^sha256:[a-f0-9]{64}$",
            )
            output = Path(temporary) / "archive.json"
            payload = (
                json.dumps(
                    result["manifest"],
                    ensure_ascii=True,
                    sort_keys=True,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                + b"\n"
            )
            output.with_name(f".{output.name}.tmp").write_bytes(payload)
            write_manifest(output, result["manifest"])
            self.assertEqual(read_manifest(output), result["manifest"])

    def test_archive_temp_error_and_invalid_scan_root_use_cli_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            root.mkdir()
            harness = Harness(root)
            self.assertTrue(harness.initialize(state_gateway=True)[0]["ok"])
            output = Path(temporary) / "archive.json"
            target = Path(temporary) / "target"
            target.write_text("unsafe", encoding="utf-8")
            output.with_name(f".{output.name}.tmp").symlink_to(target)
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = loopctl.main(
                    [
                        "archive", "--root", str(root), "--reason", "test",
                        "--emit", str(output), "--json",
                    ]
                )
            self.assertEqual(1, exit_code)
            self.assertEqual(
                json.loads(stdout.getvalue())["status"],
                "ARCHIVE_MANIFEST_WRITE_FAILED",
            )
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = loopctl.main(
                    ["risk-scan", "--root", str(root / "missing"), "--check", "--json"]
                )
            self.assertEqual(1, exit_code)
            self.assertEqual(
                json.loads(stdout.getvalue())["status"],
                "RISK_SCAN_ROOT_INVALID",
            )

    def test_archive_v2_roundtrip_digest_and_two_legacy_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = build_manifest(
                reason="test archive",
                root="/disposable",
                git={"head": "a" * 40},
                state={"version": 3},
                events=[],
                outboxes=[],
                roles=[],
                heartbeat={"status": "PAUSED"},
                files=[
                    {
                        "digest": "sha256:" + "b" * 64,
                        "path": ".codex-loop/LOOP_STATE.md",
                        "privacy_classification": "PRIVATE",
                        "size": 1,
                    }
                ],
            )
            path = root / "archive-manifest-v2.json"
            write_manifest(path, manifest)
            self.assertEqual(read_manifest(path), manifest)
            tampered = {**manifest, "reason": "changed"}
            with self.assertRaises(ArchiveManifestError):
                validate_manifest(tampered)
            flat = root / "flat.json"
            flat.write_text('{"root":"/old","reason":"old","files":[]}', encoding="utf-8")
            wrapped = root / "wrapped.json"
            wrapped.write_text(
                '{"context":{"root":"/old","reason":"old"},"files":[]}',
                encoding="utf-8",
            )
            self.assertEqual(read_manifest(flat)["legacy_shape"], "FLAT")
            self.assertEqual(read_manifest(wrapped)["legacy_shape"], "CONTEXT_WRAPPED")

    def test_scanner_separates_digest_fixture_placeholder_and_real_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "fixture.txt").write_text(
                "FIXTURE sk-" + "x" * 24 + "\n" + "a" * 64 + "\n",
                encoding="utf-8",
            )
            (root / "secret.txt").write_text("sk-" + "z" * 24, encoding="utf-8")
            findings = scan(
                root,
                (
                    AllowRule(
                        rule_id="DIGEST_FIXTURE",
                        path_glob="fixture.txt",
                        kind="SHA256",
                        reason="test digest",
                    ),
                    AllowRule(
                        rule_id="CREDENTIAL_FIXTURE",
                        path_glob="fixture.txt",
                        kind="FIXTURE",
                        reason="synthetic credential fixture",
                    ),
                ),
            )
            kinds = {finding["kind"] for finding in findings}
            self.assertTrue({"PLACEHOLDER", "FIXTURE", "SHA256", "OPENAI_API_KEY"} <= kinds)
            unsafe = unallowed_credentials(findings)
            self.assertEqual(["secret.txt"], [finding["path"] for finding in unsafe])
            self.assertNotIn("z" * 24, json.dumps(findings))

            (root / "example.txt").write_text(
                "example production key: sk-" + "q" * 24,
                encoding="utf-8",
            )
            unsafe = unallowed_credentials(scan(root))
            self.assertIn("example.txt", [finding["path"] for finding in unsafe])


if __name__ == "__main__":
    unittest.main()
