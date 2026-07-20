from __future__ import annotations

import copy
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "codex-loop-prompt-architect" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import loopctl  # noqa: E402
import build_recovery_registry  # noqa: E402
import loop_architect.state_runtime as state_runtime_module  # noqa: E402
import loop_architect.recovery_registry as recovery_registry_module  # noqa: E402
from loop_architect.recovery_registry import load_recovery_registry  # noqa: E402
from loop_architect.rejection_journal import read_rejections  # noqa: E402
from loop_architect.state_runtime import AdaptiveStateRuntime  # noqa: E402


class LoopctlEntrypointTests(unittest.TestCase):
    def test_wrapper_reuses_installed_dependency_complete_interpreter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt_dir = (
                root / "install-receipts" / "codex-loop-prompt-architect"
            )
            receipt_dir.mkdir(parents=True)
            interpreter = root / "managed-python"
            interpreter.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$0\" \"$@\"\n",
                encoding="utf-8",
            )
            interpreter.chmod(0o700)
            (receipt_dir / "20260101000000-1.json").write_text(
                json.dumps(
                    {"mcp_registration": {"command": str(interpreter)}}
                )
                + "\n",
                encoding="utf-8",
            )
            environment = {"CODEX_HOME": str(root), "PATH": "/usr/bin:/bin"}
            result = subprocess.run(
                [str(SCRIPTS / "loopctl"), "doctor", "--check", "--json"],
                text=True,
                capture_output=True,
                env=environment,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            lines = result.stdout.splitlines()
            self.assertEqual(str(interpreter), lines[0])
            self.assertEqual(str(SCRIPTS / "loopctl.py"), lines[1])
            self.assertEqual(["doctor", "--check", "--json"], lines[2:])


class RecoveryRegistryTests(unittest.TestCase):
    def test_checked_in_registry_covers_every_literal_and_never_waits(self) -> None:
        self.assertEqual(
            0,
            loopctl.subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "build_recovery_registry.py"),
                    "--check",
                    "--json",
                ],
                cwd=REPO_ROOT,
                check=False,
            ).returncode,
        )
        entries = load_recovery_registry()
        self.assertGreater(len(entries), 500)
        for code, descriptor in entries.items():
            with self.subTest(code=code):
                self.assertIn(
                    descriptor["classification"],
                    {"RECOVERABLE", "HUMAN_GATED", "TERMINAL", "NON_RETRYABLE"},
                )
                self.assertNotEqual("WAIT", descriptor["operation"])
                self.assertEqual(
                    descriptor["operation"],
                    descriptor["next_operation"]["operation"],
                )

        heartbeat_recovery = entries["STATE_GATEWAY_HEARTBEAT_UNREGISTERED"]
        self.assertEqual("RECOVERABLE", heartbeat_recovery["classification"])
        self.assertEqual(
            "REGISTER_HEARTBEAT_FROM_APP_READBACK",
            heartbeat_recovery["operation"],
        )

    def test_gateway_helper_literals_are_in_recovery_coverage(self) -> None:
        codes = build_recovery_registry.extract_codes()
        self.assertIn("STATE_GATEWAY_HEARTBEAT_UNREGISTERED", codes)
        self.assertIn("STATE_GATEWAY_REQUEST_INVALID", codes)

    def test_generator_entrypoint_emits_checks_and_detects_stale_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "registry.json"
            with mock.patch.object(build_recovery_registry, "OUTPUT", output):
                with mock.patch.object(sys, "argv", ["build", "--emit", "--json"]):
                    self.assertEqual(0, build_recovery_registry.main())
                self.assertIn("RECOVERY_REQUIRED", output.read_text(encoding="utf-8"))
                with mock.patch.object(sys, "argv", ["build", "--check", "--json"]):
                    self.assertEqual(0, build_recovery_registry.main())
                output.write_text("{}\n", encoding="utf-8")
                with mock.patch.object(sys, "argv", ["build", "--check"]):
                    self.assertEqual(1, build_recovery_registry.main())

    def test_registry_validation_and_unregistered_fallback_fail_closed(self) -> None:
        self.assertFalse(recovery_registry_module.recovery_for("UNKNOWN_NEW_CODE")["registered"])
        with tempfile.TemporaryDirectory() as temporary:
            invalid = Path(temporary) / "registry.json"
            invalid.write_text('{"schema_version":"wrong","entries":{}}\n', encoding="utf-8")
            recovery_registry_module.load_recovery_registry.cache_clear()
            with mock.patch.object(recovery_registry_module, "REGISTRY_PATH", invalid):
                with self.assertRaisesRegex(
                    recovery_registry_module.RecoveryRegistryError,
                    "schema invalid",
                ):
                    recovery_registry_module.load_recovery_registry()
            recovery_registry_module.load_recovery_registry.cache_clear()


class RejectionJournalTests(unittest.TestCase):
    @staticmethod
    def _invalid_request(index: int, *, secret: str | None = None) -> dict[str, object]:
        request: dict[str, object] = {
            "actor": "CONTROLLER",
            "state_request_id": f"reject-{index}",
            "event_id": f"reject-event-{index}",
            "mutation": {"type": "UNKNOWN_OPERATION"},
        }
        if secret is not None:
            request["raw_prompt"] = secret
        return request

    def test_concurrent_rejections_are_hash_chained_and_privacy_minimized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            secret = "sk-live-must-never-appear"

            def reject(index: int) -> dict[str, object]:
                return AdaptiveStateRuntime(root).apply(
                    self._invalid_request(index, secret=secret)
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                responses = list(pool.map(reject, range(24)))
            self.assertTrue(all(not response["ok"] for response in responses))
            self.assertTrue(
                all(response["rejection_journal"]["status"] == "APPENDED" for response in responses)
            )
            path = root / ".codex-loop" / "LOOP_REJECTIONS.jsonl"
            entries = read_rejections(path)
            self.assertEqual(24, len(entries))
            self.assertEqual(list(range(1, 25)), [entry["sequence"] for entry in entries])
            self.assertNotIn(secret, path.read_text(encoding="utf-8"))
            self.assertNotIn("raw_prompt", path.read_text(encoding="utf-8"))
            self.assertTrue(all(entry["side_effects"]["canonical"] == "NONE" for entry in entries))
            audit = loopctl.audit_root(root)
            self.assertEqual(0, audit["accepted_count"])
            self.assertEqual(24, audit["rejected_count"])

    def test_journal_failure_is_fail_closed_without_hiding_original_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = AdaptiveStateRuntime(temporary)
            with mock.patch.object(
                state_runtime_module,
                "append_rejection",
                side_effect=OSError("disk full"),
            ):
                response = runtime.apply(self._invalid_request(1))
            self.assertEqual("REQUEST_SCHEMA_INVALID", response["status"])
            self.assertEqual("WRITE_FAILED", response["rejection_journal"]["status"])
            self.assertEqual(
                "STOP_AND_REPAIR_REJECTION_JOURNAL",
                response["recovery"]["operation"],
            )

    def test_tampered_hash_chain_is_rejected_by_audit_and_future_append(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = AdaptiveStateRuntime(root)
            self.assertFalse(runtime.apply(self._invalid_request(1))["ok"])
            path = root / ".codex-loop" / "LOOP_REJECTIONS.jsonl"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["error_code"] = "TAMPERED"
            path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(loopctl.LoopctlError, "AUDIT_REJECTION_LOG_INVALID"):
                loopctl.audit_root(root)
            response = runtime.apply(self._invalid_request(2))
            self.assertEqual("WRITE_FAILED", response["rejection_journal"]["status"])


class LoopctlCompilerAndCanaryTests(unittest.TestCase):
    def _source(self, root: str) -> dict[str, object]:
        return {
            "mode": "DISPOSABLE",
            "loop_id": "loop-canary",
            "root": root,
            "controller": {"task_id": "controller-task"},
            "roles": [
                {"role": "CONTROLLER", "model": "model-a", "reasoning": "high"},
                {"role": "WORKER", "model": "model-b", "reasoning": "high"},
                {"role": "REVIEWER", "model": "model-c", "reasoning": "high"},
            ],
            "goals": [{"goal_id": "G0", "required_completion_class": "COMPLETE_ARTIFACT"}],
            "heartbeat": {
                "automation_id": "heartbeat-1",
                "target": "controller-task",
                "rrule": "FREQ=HOURLY",
                "prompt_digest": "sha256:" + "a" * 64,
                "purpose": "route",
                "status": "ACTIVE",
            },
        }

    def test_compile_requires_full_role_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = self._source(temporary)
            source["roles"] = source["roles"][:-1]
            with self.assertRaisesRegex(loopctl.LoopctlError, "COMPILE_ROLE_REGISTRY_INVALID"):
                loopctl.compile_manifest(source)

    def test_compile_accepts_hourly_heartbeat_and_rejects_unsupported_rrule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = self._source(temporary)
            compiled = loopctl.compile_manifest(source)
            self.assertEqual("FREQ=HOURLY", compiled["heartbeat"]["rrule"])
            source["heartbeat"]["rrule"] = "FREQ=DAILY"
            with self.assertRaisesRegex(loopctl.LoopctlError, "COMPILE_HEARTBEAT_INVALID"):
                loopctl.compile_manifest(source)

    def test_canary_requires_all_real_receipt_lanes_and_finalization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = self._source(temporary)
            manifest = loopctl.compile_manifest(source)
            source["canary_receipt"] = {
                "schema_version": loopctl.CANARY_RECEIPT_VERSION,
                "root_disposition": "DISPOSABLE",
                "manifest_digest": manifest["manifest_digest"],
                "lanes": [
                    {
                        "stage": stage,
                        "status": "PASS",
                        "receipt_digest": "sha256:" + f"{index:064x}",
                    }
                    for index, stage in enumerate(loopctl.CANARY_STAGES, 1)
                ],
                "negative_evidence": [{"stage": "SEND", "status": "PRESERVED"}],
                "final_status": "FINALIZATION_ACKED",
                "mcp_lifecycle": {
                    name: {
                        "status": "SUPPORTED",
                        "active_call_count_before": 0,
                        "active_call_count_after": 0,
                        "before_identity": f"before-{name}",
                        "after_identity": f"after-{name}",
                        "receipt_digest": "sha256:" + "b" * 64,
                    }
                    for name in loopctl.MCP_LIFECYCLE_CAPABILITIES
                },
            }
            compiled = loopctl.compile_manifest(source)
            self.assertEqual(manifest["manifest_digest"], compiled["manifest_digest"])
            result = loopctl.verify_canary(compiled)
            self.assertTrue(result["formal_initialization_allowed"])
            self.assertEqual("NOT_REQUIRED", result["model_identity_requirement"])
            self.assertEqual("NOT_APPLICABLE", result["model_identity_status"])
            failed = copy.deepcopy(compiled)
            failed["canary_receipt"]["lanes"][3]["status"] = "FAIL"
            with self.assertRaisesRegex(loopctl.LoopctlError, "CANARY_LANE_FAILED"):
                loopctl.verify_canary(failed)

    def test_canary_rejects_lifecycle_refresh_with_active_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = self._source(temporary)
            base = loopctl.compile_manifest(source)
            source["canary_receipt"] = {
                "schema_version": loopctl.CANARY_RECEIPT_VERSION,
                "root_disposition": "DISPOSABLE",
                "manifest_digest": base["manifest_digest"],
                "lanes": [
                    {"stage": stage, "status": "PASS", "receipt_digest": "sha256:" + "a" * 64}
                    for stage in loopctl.CANARY_STAGES
                ],
                "negative_evidence": [],
                "final_status": "FINALIZATION_ACKED",
                "mcp_lifecycle": {
                    name: {
                        "status": "SUPPORTED",
                        "active_call_count_before": 0,
                        "active_call_count_after": 0,
                        "before_identity": "before",
                        "after_identity": "after",
                        "receipt_digest": "sha256:" + "b" * 64,
                    }
                    for name in loopctl.MCP_LIFECYCLE_CAPABILITIES
                },
            }
            manifest = loopctl.compile_manifest(source)
            manifest["canary_receipt"]["mcp_lifecycle"]["schema_refresh"][
                "active_call_count_before"
            ] = 1
            with self.assertRaisesRegex(loopctl.LoopctlError, "CANARY_MCP_LIFECYCLE_FAILED"):
                loopctl.verify_canary(manifest)

    def test_formal_compile_rejects_role_identity_mismatch_and_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = self._source(temporary)
            source["mode"] = "FORMAL"
            source["required_model"] = source["roles"][0]["model"]
            source["required_reasoning"] = source["roles"][0]["reasoning"]
            for role in source["roles"]:
                role["model"] = source["required_model"]
            for index, role in enumerate(source["roles"]):
                receipt = {
                    "schema_version": "host-role-model-receipt-v1",
                    "issuer": "CODEX_APP_HOST",
                    "evidence_model": "HOST_COOPERATIVE",
                    "task_id": f"task-{index}",
                    "thread_id": f"thread-{index}",
                    "role": role["role"],
                    "model": role["model"],
                    "reasoning": role["reasoning"],
                    "app_build": "Codex-test",
                }
                receipt["receipt_digest"] = loopctl._digest(receipt)
                role["host_receipt"] = receipt
            mismatch = copy.deepcopy(source)
            mismatch["roles"][0]["model"] = "wrong-model"
            with self.assertRaisesRegex(loopctl.LoopctlError, "ROLE_RECEIPT_IDENTITY_MISMATCH"):
                loopctl.compile_manifest(mismatch)
            replay = copy.deepcopy(source)
            replay["roles"][1]["host_receipt"]["task_id"] = "task-0"
            replay["roles"][1]["host_receipt"]["thread_id"] = "thread-0"
            body = dict(replay["roles"][1]["host_receipt"])
            body.pop("receipt_digest")
            replay["roles"][1]["host_receipt"]["receipt_digest"] = loopctl._digest(body)
            with self.assertRaisesRegex(loopctl.LoopctlError, "ROLE_RECEIPT_REPLAY"):
                loopctl.compile_manifest(replay)

            unsigned_label = copy.deepcopy(source)
            unsigned_label["roles"][0]["host_receipt"]["evidence_model"] = "APP_SIGNED"
            body = dict(unsigned_label["roles"][0]["host_receipt"])
            body.pop("receipt_digest")
            unsigned_label["roles"][0]["host_receipt"]["receipt_digest"] = (
                loopctl._digest(body)
            )
            with self.assertRaisesRegex(
                loopctl.LoopctlError, "ROLE_RECEIPT_IDENTITY_MISMATCH"
            ):
                loopctl.compile_manifest(unsigned_label)

    def test_model_identity_is_opt_in_and_strict_mode_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = self._source(temporary)
            source["mode"] = "FORMAL"
            compiled = loopctl.compile_manifest(source)
            self.assertTrue(compiled["formal_ready"])
            self.assertEqual(
                {
                    "model_identity_requirement": "NOT_REQUIRED",
                    "model_identity_status": "NOT_APPLICABLE",
                    "required_model": "UNSPECIFIED",
                    "required_reasoning": "UNSPECIFIED",
                },
                compiled["model_identity_policy"],
            )
            self.assertTrue(
                all(
                    role["model"] == role["reasoning"] == "UNSPECIFIED"
                    and "host_receipt" not in role
                    for role in compiled["registry"]["roles"]
                )
            )

            strict = copy.deepcopy(source)
            strict["required_model"] = "required-model"
            blocked = loopctl.compile_manifest(strict)
            self.assertFalse(blocked["formal_ready"])
            self.assertEqual("REQUIRED", blocked["model_identity_policy"]["model_identity_requirement"])
            self.assertEqual("HOST_BLOCKED", blocked["model_identity_policy"]["model_identity_status"])
            strict["canary_receipt"] = {"schema_version": loopctl.CANARY_RECEIPT_VERSION}
            blocked = loopctl.compile_manifest(strict)
            with self.assertRaisesRegex(loopctl.LoopctlError, "BLOCKED_BY_APP_ATTESTATION"):
                loopctl.verify_canary(blocked)


class LoopctlDoctorTests(unittest.TestCase):
    def _codex_home(self, root: Path) -> tuple[Path, Path]:
        codex_home = root / "codex-home"
        installed = codex_home / "skills" / loopctl.SKILL_NAME
        shutil.copytree(loopctl.PROJECT_DIR, installed)
        config = codex_home / "config.toml"
        config.write_text("[mcp_servers.codex-loop-state]\ncommand='/usr/bin/python3'\nargs=['/tmp/server.py']\n", encoding="utf-8")
        receipt_dir = codex_home / "install-receipts" / loopctl.SKILL_NAME
        receipt_dir.mkdir(parents=True)
        manifest_digest = loopctl._tree_manifest_digest(installed)
        receipt = {
            "manifest_digest": "a" * 64,
            "source_manifest_digest": manifest_digest,
            "installed_manifest_digest": manifest_digest,
            "source_install_drift": [],
            "mcp_registration": {
                "command": "/usr/bin/python3",
                "args": ["/tmp/server.py"],
                "config_path": str(config),
                "config_readback": True,
            },
        }
        (receipt_dir / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        host = root / "host.json"
        host_receipt = {
            "schema_version": "host-capability-receipt-v1",
            "app_build": "Codex-2026.7.20",
            "app_readback": True,
            "role_model_receipts": True,
            "heartbeat_readback": True,
            "mcp_lifecycle": {
                name: {"status": "SUPPORTED"}
                for name in loopctl.MCP_LIFECYCLE_CAPABILITIES
            },
        }
        host_receipt["receipt_digest"] = loopctl._digest(host_receipt)
        host.write_text(json.dumps(host_receipt), encoding="utf-8")
        return codex_home, host

    def test_doctor_caches_by_complete_identity_and_invalidates_on_config_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home, host = self._codex_home(root)
            first = loopctl.run_doctor(
                source=loopctl.PROJECT_DIR,
                codex_home=codex_home,
                target="formal",
                host_receipt_path=host,
            )
            self.assertTrue(first["ok"])
            self.assertTrue(first["formal_ready"])
            self.assertFalse(first["cache"]["hit"])
            second = loopctl.run_doctor(
                source=loopctl.PROJECT_DIR,
                codex_home=codex_home,
                target="formal",
                host_receipt_path=host,
            )
            self.assertTrue(second["cache"]["hit"])
            (codex_home / "config.toml").write_text("# changed\n", encoding="utf-8")
            third = loopctl.run_doctor(
                source=loopctl.PROJECT_DIR,
                codex_home=codex_home,
                target="formal",
                host_receipt_path=host,
            )
            self.assertFalse(third["cache"]["hit"])
            self.assertNotEqual(first["identity_digest"], third["identity_digest"])

    def test_formal_doctor_fails_closed_without_host_and_on_install_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home, _ = self._codex_home(root)
            missing_host = loopctl.run_doctor(
                source=loopctl.PROJECT_DIR,
                codex_home=codex_home,
                target="formal",
                write_cache=False,
            )
            self.assertFalse(missing_host["ok"])
            self.assertFalse(missing_host["formal_ready"])
            installed = codex_home / "skills" / loopctl.SKILL_NAME
            (installed / "SKILL.md").write_text("drift\n", encoding="utf-8")
            drift = loopctl.run_doctor(
                source=loopctl.PROJECT_DIR,
                codex_home=codex_home,
                target="local",
                write_cache=False,
            )
            manifest_check = next(
                item for item in drift["checks"] if item["name"] == "source_install_manifest"
            )
            self.assertFalse(manifest_check["ok"])
            self.assertFalse(drift["ok"])

    def test_doctor_requires_role_model_capability_only_in_strict_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home, host = self._codex_home(root)
            receipt = json.loads(host.read_text(encoding="utf-8"))
            receipt["role_model_receipts"] = False
            receipt.pop("receipt_digest")
            receipt["receipt_digest"] = loopctl._digest(receipt)
            host.write_text(json.dumps(receipt), encoding="utf-8")
            ordinary = loopctl.run_doctor(
                source=loopctl.PROJECT_DIR,
                codex_home=codex_home,
                target="formal",
                host_receipt_path=host,
                write_cache=False,
            )
            self.assertTrue(ordinary["formal_ready"], ordinary)
            self.assertEqual("NOT_APPLICABLE", ordinary["model_identity_status"])
            strict = loopctl.run_doctor(
                source=loopctl.PROJECT_DIR,
                codex_home=codex_home,
                target="formal",
                host_receipt_path=host,
                model_identity_requirement="REQUIRED",
                write_cache=False,
            )
            self.assertFalse(strict["formal_ready"])
            self.assertEqual("HOST_BLOCKED", strict["model_identity_status"])
            self.assertNotEqual(
                ordinary["identity_digest"], strict["identity_digest"]
            )


class LoopctlCliTests(unittest.TestCase):
    def test_compile_audit_and_error_envelopes_use_stable_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = {
                "mode": "DISPOSABLE",
                "loop_id": "cli-loop",
                "root": str(root),
                "controller": {"task_id": "controller"},
                "roles": [
                    {"role": role, "model": "model", "reasoning": "high"}
                    for role in ("CONTROLLER", "WORKER", "REVIEWER")
                ],
                "goals": [{"goal_id": "G0"}],
                "heartbeat": {
                    "automation_id": "heartbeat",
                    "target": "controller",
                    "rrule": "FREQ=HOURLY",
                    "prompt_digest": "sha256:" + "a" * 64,
                    "purpose": "route",
                    "status": "ACTIVE",
                },
            }
            input_path = root / "source.json"
            output_path = root / "compiled.json"
            input_path.write_text(json.dumps(source), encoding="utf-8")
            stdout = io.StringIO()
            with mock.patch("sys.stdout", stdout):
                self.assertEqual(
                    0,
                    loopctl.main(
                        [
                            "compile", "--input", str(input_path), "--check",
                            "--emit", str(output_path), "--json",
                        ]
                    ),
                )
            self.assertTrue(json.loads(stdout.getvalue())["ok"])
            self.assertTrue(output_path.is_file())
            stdout = io.StringIO()
            with mock.patch("sys.stdout", stdout):
                self.assertEqual(
                    1,
                    loopctl.main(["canary", "--input", str(output_path), "--json"]),
                )
            self.assertEqual("CANARY_RECEIPT_REQUIRED", json.loads(stdout.getvalue())["status"])
            stdout = io.StringIO()
            with mock.patch("sys.stdout", stdout):
                self.assertEqual(
                    0, loopctl.main(["audit", "--root", str(root), "--json"])
                )
            self.assertEqual("AUDIT_COMPLETE", json.loads(stdout.getvalue())["status"])

    def test_input_readers_and_doctor_cli_cover_supported_and_failed_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "value.yaml").write_text("name: loop\n", encoding="utf-8")
            (root / "value.toml").write_text('name = "loop"\n', encoding="utf-8")
            (root / "value.txt").write_text("name=loop\n", encoding="utf-8")
            self.assertEqual("loop", loopctl._read_document(root / "value.yaml")["name"])
            self.assertEqual("loop", loopctl._read_document(root / "value.toml")["name"])
            with self.assertRaisesRegex(loopctl.LoopctlError, "INPUT_FORMAT_UNSUPPORTED"):
                loopctl._read_document(root / "value.txt")
            stdout = io.StringIO()
            with mock.patch("sys.stdout", stdout):
                self.assertEqual(
                    1,
                    loopctl.main(
                        [
                            "doctor", "--check", "--json", "--target", "formal",
                            "--codex-home", str(root / "codex-home"),
                        ]
                    ),
                )
            result = json.loads(stdout.getvalue())
            self.assertEqual("DOCTOR_FAILED", result["status"])
            self.assertFalse(result["formal_ready"])


if __name__ == "__main__":
    unittest.main()
