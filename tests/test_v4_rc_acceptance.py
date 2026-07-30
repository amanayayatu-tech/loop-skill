from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest import mock

from tests.test_v4_author_packet import receipt_for


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/validate_v4_rc.py"
SPEC = importlib.util.spec_from_file_location("validate_v4_rc", MODULE_PATH)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)

RUNNER_PATH = ROOT / "scripts/run_v4_conformance.py"
RUNNER_SPEC = importlib.util.spec_from_file_location("run_v4_conformance_for_rc_test", RUNNER_PATH)
assert RUNNER_SPEC and RUNNER_SPEC.loader
runner = importlib.util.module_from_spec(RUNNER_SPEC)
RUNNER_SPEC.loader.exec_module(runner)


def live_observation(candidate: str) -> dict:
    return {
        "artifact_state": "VERIFIED",
        "assurance": "STRICT",
        "canary_output_sha256": validator.CANARY_OUTPUT_SHA256,
        "candidate_goal_digest": "e" * 64,
        "candidate_sha": candidate,
        "execution_disposition": "SUCCEEDED",
        "execution_state": "TERMINAL",
        "finalization_state": "EXECUTION_CLOSED",
        "host_task_identity_digest": "c" * 64,
        "lifecycle_state": "TERMINAL",
        "result_digest": "b" * 64,
        "result_outcome": "PASS",
        "result_state": "ACKNOWLEDGED",
        "report_state": "ACCEPTED",
        "review_state": "PASS",
        "snapshot_digest": "d" * 64,
    }


def provider_diagnostic() -> dict:
    empty = hashlib.sha256(b"").hexdigest()
    result = b'{"outcome":"PASS","summary":"complete"}'
    return {
        "artifact": "loopskill-codex-exec-terminal-diagnostic-v1",
        "code": "PASS",
        "primary_code": None,
        "result_bytes": len(result),
        "result_control_digest": hashlib.sha256(result).hexdigest(),
        "result_sha256": hashlib.sha256(result).hexdigest(),
        "returncode_class": "ZERO",
        "schema_control_digest": "6" * 64,
        "stderr_bytes": 0,
        "stderr_sha256": empty,
        "stdout_bytes": 100,
        "stdout_sha256": "7" * 64,
        "terminal_event_count": 1,
        "terminal_event_type": "turn.completed",
    }


def canary(
    candidate: str,
    *,
    goal_count: int = 1,
    route_digit: str | None = None,
    issued: datetime | None = None,
) -> dict:
    if goal_count not in {1, 2, 8}:
        raise AssertionError(goal_count)
    if route_digit is None:
        route_digit = str(goal_count)
    live = live_observation(candidate)
    live["host_task_identity_digest"] = (
        "c" * 64 if goal_count == 1 else route_digit * 64
    )
    issued = (issued or datetime.now(timezone.utc)).replace(microsecond=0)
    fresh_until = issued + timedelta(minutes=5 if goal_count == 1 else 60)
    issued_text = issued.isoformat().replace("+00:00", "Z")
    fresh_text = fresh_until.isoformat().replace("+00:00", "Z")
    candidate_provenance = {
        "candidate_execution_mode": "CLEAN_GIT_WORKTREE",
        "candidate_sha": candidate,
        "candidate_tree_sha": candidate,
    }
    diagnostic_evidence = (
        provider_diagnostic()
        if goal_count == 1
        else [provider_diagnostic() for _ in range(goal_count)]
    )
    value = {
        "artifact": validator.CANARY_ARTIFACT,
        **candidate_provenance,
        "candidate_provenance_digest": validator._domain_digest(
            validator.CANARY_CANDIDATE_PROVENANCE_DOMAIN,
            candidate_provenance,
        ),
        "candidate_sha": candidate,
        "candidate_goal_digest": live["candidate_goal_digest"],
        "canary_output_sha256": live["canary_output_sha256"],
        "confirmation_count": 1,
        "confirmation_digest_bound": True,
        "allowed_host_managed_delta_count": 0,
        "canary_workspace_identity_digest": route_digit * 64,
        "entry": "loopskill4",
        "finalization": "ACKNOWLEDGED",
        "fresh_until": fresh_text,
        "host_auth_after_digest": "1" * 64,
        "host_auth_before_digest": "1" * 64,
        "host_config_after_digest": "2" * 64,
        "host_config_before_digest": "2" * 64,
        "host_config_delta_kind": validator.HOST_CONFIG_DELTA_NONE,
        "host_receipt_issuer": validator.CANARY_ISSUER,
        "host_receipt_trust": validator.CANARY_TRUST,
        "host_create_readback_count": goal_count,
        "host_lifecycle_readback_count": 1,
        "host_result_digest": live["result_digest"],
        "host_task_create_count": goal_count,
        "host_task_identity_digest": live["host_task_identity_digest"],
        "host_task_readback_count": goal_count,
        "host_terminal_wait_readback_count": goal_count,
        "host_total_read_count": 3 * goal_count + 1,
        "intake_external_effects": 0,
        "intake_heartbeat_count": 0,
        "intake_host_task_count": 0,
        "intake_loop_count": 0,
        "issued_at": issued_text,
        "integrity_measurement_digest": "4" * 64,
        "loopskill_mcp_registration_count": 0,
        "machine_owned_identity": True,
        "manual_control_identity_count": 0,
        "observed_at": issued_text,
        "observed_host_auth_changed_bytes": 0,
        "observed_host_config_changed_bytes": 0,
        "app_restart_count": 0,
        "prepare_delivery_count": 0,
        "prepare_heartbeat_count": 0,
        "prepare_host_effects": 0,
        "prepare_host_task_count": 0,
        "private_data_used": False,
        "provider_resend_count": 0,
        "provider_terminal_diagnostic_digest": validator._domain_digest(
            validator.CANARY_PROVIDER_DIAGNOSTIC_DOMAIN, diagnostic_evidence
        ),
        "research_scored": False,
        "result": "ACKNOWLEDGED",
        "review": "PASS",
        "status": "PASS",
        "thread_content_retained": False,
        "unknown_preserved": True,
        "unexpected_changed_input_count": 0,
        "v3_bytes_changed": 0,
    }
    value["provenance_digest"] = validator._domain_digest(
        validator.CANARY_PROVENANCE_DOMAIN, value
    )
    value["host_receipt_digest"] = validator._domain_digest(
        validator.CANARY_LIVE_DOMAIN, live
    )
    return value


def write_integrity_evidence(
    root: Path,
    value: dict,
    candidate: str,
    *,
    trust_append: bool = False,
    goal_count: int = 1,
) -> tuple[dict, dict]:
    workspace = root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    diagnostic_paths = (
        (root / validator.CANARY_PROVIDER_DIAGNOSTIC_FILENAME,)
        if goal_count == 1
        else tuple(
            root / f"canary-provider-diagnostic-{index:02d}.json"
            for index in range(1, goal_count + 1)
        )
    )
    for diagnostic_path in diagnostic_paths:
        diagnostic_path.write_bytes(validator._canonical(provider_diagnostic()))
    identity, stanza = validator._canary_workspace_contract(root.resolve())
    config = b'model = "synthetic"\n'
    prefix_digest = hashlib.sha256(
        validator.CANARY_CONFIG_PREFIX_DOMAIN + config
    ).hexdigest()
    delta = stanza if trust_append else b""
    before_inputs = {
        "host_auth": {"digest": "1" * 64, "presence": "FILE", "size": 10},
        "host_config": {
            "digest": "2" * 64,
            "presence": "FILE",
            "size": len(config),
        },
    }
    after_inputs = {
        "host_auth": dict(before_inputs["host_auth"]),
        "host_config": {
            "digest": "5" * 64 if trust_append else "2" * 64,
            "presence": "FILE",
            "size": len(config) + len(delta),
        },
    }
    classification = {
        "after_prefix_digest": prefix_digest,
        "after_workspace_key_count": int(trust_append),
        "allowed_host_managed_delta_count": int(trust_append),
        "before_prefix_digest": prefix_digest,
        "before_workspace_key_count": 0,
        "delta_kind": (
            validator.HOST_CONFIG_DELTA_TRUST_APPEND
            if trust_append
            else validator.HOST_CONFIG_DELTA_NONE
        ),
        "observed_delta_bytes": len(delta),
        "observed_delta_digest": hashlib.sha256(
            validator.CANARY_CONFIG_DELTA_DOMAIN + delta
        ).hexdigest(),
        "unexpected_changed_input_count": 0,
        "workspace_identity_digest": identity,
    }
    before = {
        "artifact": "loopskill-v4-canary-integrity-before-v1",
        "candidate_execution_mode": value["candidate_execution_mode"],
        "candidate_provenance_digest": value["candidate_provenance_digest"],
        "candidate_sha": candidate,
        "candidate_tree_sha": value["candidate_tree_sha"],
        "inputs": before_inputs,
        "issued_at": value["issued_at"],
        "workspace_identity_digest": identity,
    }
    final = {
        "after": after_inputs,
        "artifact": "loopskill-v4-canary-integrity-measurement-v1",
        "before": before_inputs,
        "candidate_sha": candidate,
        "changed_bytes": {"host_auth": 0, "host_config": len(delta)},
        "changed_input_count": int(trust_append),
        "host_config_delta": classification,
        "observed_at": value["observed_at"],
        "total_changed_bytes": len(delta),
    }
    final["measurement_digest"] = validator._domain_digest(
        validator.CANARY_INTEGRITY_MEASUREMENT_DOMAIN, final
    )
    value.update(
        {
            "allowed_host_managed_delta_count": int(trust_append),
            "canary_workspace_identity_digest": identity,
            "host_auth_after_digest": after_inputs["host_auth"]["digest"],
            "host_auth_before_digest": before_inputs["host_auth"]["digest"],
            "host_config_after_digest": after_inputs["host_config"]["digest"],
            "host_config_before_digest": before_inputs["host_config"]["digest"],
            "host_config_delta_kind": classification["delta_kind"],
            "integrity_measurement_digest": final["measurement_digest"],
            "observed_host_auth_changed_bytes": 0,
            "observed_host_config_changed_bytes": len(delta),
            "unexpected_changed_input_count": 0,
        }
    )
    provenance = dict(value)
    provenance.pop("provenance_digest")
    provenance.pop("host_receipt_digest")
    value["provenance_digest"] = validator._domain_digest(
        validator.CANARY_PROVENANCE_DOMAIN, provenance
    )
    (root / validator.CANARY_INTEGRITY_BEFORE_FILENAME).write_bytes(
        validator._canonical(before)
    )
    (root / validator.CANARY_INTEGRITY_FILENAME).write_bytes(
        validator._canonical(final)
    )
    return before, final


class V4RcAcceptanceTests(unittest.TestCase):
    def test_final_cli_requires_canary_conformance_and_author_packet(self) -> None:
        stream = StringIO()
        with mock.patch.object(
            validator,
            "static_receipt",
            return_value={"artifact": "loopskill-v4-publication-static-receipt-v1"},
        ), redirect_stderr(stream):
            result = validator.main(["--root", str(ROOT), "--candidate", "a" * 40])
        self.assertEqual(result, 1)
        self.assertIn("RC_FINAL_RECEIPTS_REQUIRED", stream.getvalue())

    def test_self_asserted_canary_json_cannot_replace_bound_store_evidence(self) -> None:
        candidate = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = []
            for name, payload in (
                ("canary.json", canary(candidate)),
                ("conformance.json", {}),
                ("packet.json", {}),
            ):
                path = root / name
                path.write_text(json.dumps(payload), encoding="utf-8")
                paths.append(path)
            stream = StringIO()
            with mock.patch.object(
                validator,
                "static_receipt",
                return_value={
                    "artifact": "loopskill-v4-publication-static-receipt-v1"
                },
            ), redirect_stderr(stream):
                result = validator.main(
                    [
                        "--root",
                        str(ROOT),
                        "--candidate",
                        candidate,
                        "--canary-2-receipt",
                        str(paths[0]),
                        "--conformance-receipt",
                        str(paths[1]),
                        "--author-packet",
                        str(paths[2]),
                    ]
                )
            self.assertEqual(result, 1)
            self.assertIn("RC_FINAL_RECEIPTS_REQUIRED", stream.getvalue())

    def test_bilingual_v4_docs_examples_and_release_boundary_are_present(self) -> None:
        chinese = (ROOT / "docs/v4/quickstart.zh-CN.md").read_text(encoding="utf-8")
        english = (ROOT / "docs/v4/quickstart.en.md").read_text(encoding="utf-8")
        migration = (ROOT / "docs/v4/migration-and-rollback.md").read_text(encoding="utf-8")
        limitations = (ROOT / "docs/v4/known-limitations.md").read_text(encoding="utf-8")
        release_notes = (ROOT / "docs/v4/release-notes.md").read_text(encoding="utf-8")
        self.assertIn("INTAKE → PREPARE → CONFIRM → START", chinese)
        self.assertIn("INTAKE → PREPARE → CONFIRM → START", english)
        self.assertIn("does not ship v3 read/shadow/import", migration)
        self.assertIn("automatically migrate v3", release_notes)
        self.assertIn("patch-success superiority", limitations)
        self.assertIn("release notes for LoopSkill 4.0.0", release_notes)
        self.assertIn("docs/v4/quickstart.zh-CN.md", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("docs/v4/quickstart.en.md", (ROOT / "README.en.md").read_text(encoding="utf-8"))
        self.assertEqual(
            len(list((ROOT / "examples").glob("v4-*-input.json"))), 2
        )

    def test_canary_receipt_is_minimized_and_fail_closed(self) -> None:
        candidate = "a" * 40
        validator.validate_canary_receipt(canary(candidate), candidate)
        for field, invalid in (
            ("confirmation_count", 0),
            ("confirmation_digest_bound", False),
            ("observed_host_auth_changed_bytes", 1),
            ("host_task_create_count", 2),
            ("host_create_readback_count", 4),
            ("host_lifecycle_readback_count", 2),
            ("host_terminal_wait_readback_count", 0),
            ("host_total_read_count", 5),
            ("intake_loop_count", 1),
            ("loopskill_mcp_registration_count", 1),
            ("manual_control_identity_count", 1),
            ("app_restart_count", 1),
            ("prepare_delivery_count", 1),
            ("private_data_used", True),
            ("provider_resend_count", 1),
            ("unexpected_changed_input_count", 1),
            ("v3_bytes_changed", 1),
            ("finalization", "UNKNOWN"),
            ("host_receipt_issuer", "self-asserted"),
            ("host_receipt_trust", "untrusted"),
            (
                "fresh_until",
                (datetime.now(timezone.utc) + timedelta(hours=1))
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
            ),
        ):
            with self.subTest(field=field):
                value = canary(candidate)
                value[field] = invalid
                with self.assertRaisesRegex(
                    validator.RcValidationError, "RC_CANARY_RECEIPT_INVALID"
                ):
                    validator.validate_canary_receipt(value, candidate)
        value = canary(candidate)
        value["thread_id"] = "raw-host-identity"
        with self.assertRaisesRegex(
            validator.RcValidationError, "RC_CANARY_RECEIPT_SHAPE_INVALID"
        ):
            validator.validate_canary_receipt(value, candidate)
        historical = canary(candidate)
        old = datetime(2020, 1, 1, tzinfo=timezone.utc)
        historical["issued_at"] = old.isoformat().replace("+00:00", "Z")
        historical["observed_at"] = (old + timedelta(minutes=2)).isoformat().replace(
            "+00:00", "Z"
        )
        historical["fresh_until"] = (old + timedelta(minutes=5)).isoformat().replace(
            "+00:00", "Z"
        )
        provenance = dict(historical)
        provenance.pop("provenance_digest")
        provenance.pop("host_receipt_digest")
        historical["provenance_digest"] = validator._domain_digest(
            validator.CANARY_PROVENANCE_DOMAIN, provenance
        )
        validator.validate_canary_receipt(historical, candidate)

        for issued_offset, observed_offset, fresh_offset in (
            (2, 1, 5),
            (0, 6, 5),
            (0, 1, 11),
        ):
            value = canary(candidate)
            origin = datetime(2020, 1, 1, tzinfo=timezone.utc)
            value["issued_at"] = (
                origin + timedelta(minutes=issued_offset)
            ).isoformat().replace("+00:00", "Z")
            value["observed_at"] = (
                origin + timedelta(minutes=observed_offset)
            ).isoformat().replace("+00:00", "Z")
            value["fresh_until"] = (
                origin + timedelta(minutes=fresh_offset)
            ).isoformat().replace("+00:00", "Z")
            provenance = dict(value)
            provenance.pop("provenance_digest")
            provenance.pop("host_receipt_digest")
            value["provenance_digest"] = validator._domain_digest(
                validator.CANARY_PROVENANCE_DOMAIN, provenance
            )
            with self.assertRaisesRegex(
                validator.RcValidationError, "RC_CANARY_RECEIPT_INVALID: freshness"
            ):
                validator.validate_canary_receipt(value, candidate)

    def test_canary_pair_requires_order_same_candidate_and_distinct_routes(self) -> None:
        candidate = "a" * 40
        issued = datetime.now(timezone.utc).replace(microsecond=0)
        two = canary(candidate, goal_count=2, route_digit="2", issued=issued)
        eight = canary(
            candidate,
            goal_count=8,
            route_digit="8",
            issued=issued + timedelta(minutes=1),
        )
        validator.validate_canary_pair(two, eight, candidate)
        exact_budget = canary(
            candidate,
            goal_count=8,
            route_digit="8",
            issued=issued + timedelta(seconds=7_200),
        )
        validator.validate_canary_pair(two, exact_budget, candidate)
        over_budget = canary(
            candidate,
            goal_count=8,
            route_digit="8",
            issued=issued + timedelta(seconds=7_201),
        )
        with self.assertRaisesRegex(
            validator.RcValidationError, "RC_CANARY_SEQUENCE_INVALID"
        ):
            validator.validate_canary_pair(two, over_budget, candidate)
        for mutation in ("sequence", "tree", "workspace", "task"):
            with self.subTest(mutation=mutation):
                changed = dict(eight)
                if mutation == "sequence":
                    changed["issued_at"] = (
                        issued - timedelta(minutes=1)
                    ).isoformat().replace("+00:00", "Z")
                elif mutation == "tree":
                    changed["candidate_tree_sha"] = "b" * 40
                elif mutation == "workspace":
                    changed["canary_workspace_identity_digest"] = two[
                        "canary_workspace_identity_digest"
                    ]
                else:
                    changed["host_task_identity_digest"] = two[
                        "host_task_identity_digest"
                    ]
                if mutation in {"sequence", "tree", "workspace", "task"}:
                    provenance = dict(changed)
                    provenance.pop("provenance_digest")
                    provenance.pop("host_receipt_digest")
                    changed["provenance_digest"] = validator._domain_digest(
                        validator.CANARY_PROVENANCE_DOMAIN, provenance
                    )
                with self.assertRaises(validator.RcValidationError):
                    validator.validate_canary_pair(two, changed, candidate)

    def test_canary_integrity_measurement_missing_mutated_and_mismatched_fail(self) -> None:
        candidate = "a" * 40
        value = canary(candidate)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "workspace").mkdir()
            with self.assertRaisesRegex(
                validator.RcValidationError, "RC_CANARY_INTEGRITY_BEFORE_INVALID"
            ):
                validator._validate_canary_integrity_evidence(value, candidate, root)
            before, final = write_integrity_evidence(root, value, candidate)
            validator._validate_canary_integrity_evidence(value, candidate, root)
            final["host_config_delta"]["unexpected_changed_input_count"] = 1
            final["measurement_digest"] = validator._domain_digest(
                validator.CANARY_INTEGRITY_MEASUREMENT_DOMAIN,
                {key: item for key, item in final.items() if key != "measurement_digest"},
            )
            (root / validator.CANARY_INTEGRITY_FILENAME).write_bytes(
                validator._canonical(final)
            )
            with self.assertRaisesRegex(
                validator.RcValidationError, "RC_CANARY_INTEGRITY_CHANGED"
            ):
                validator._validate_canary_integrity_evidence(value, candidate, root)
            before, final = write_integrity_evidence(root, value, candidate)
            final["after"]["host_config"]["digest"] = "3" * 64
            final["measurement_digest"] = validator._domain_digest(
                validator.CANARY_INTEGRITY_MEASUREMENT_DOMAIN,
                {key: item for key, item in final.items() if key != "measurement_digest"},
            )
            (root / validator.CANARY_INTEGRITY_FILENAME).write_bytes(
                validator._canonical(final)
            )
            with self.assertRaisesRegex(
                validator.RcValidationError, "RC_CANARY_INTEGRITY_CHANGED"
            ):
                validator._validate_canary_integrity_evidence(value, candidate, root)

    def test_exact_trust_append_and_binding_mutations_are_recomputed(self) -> None:
        candidate = "a" * 40
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            value = canary(candidate)
            _, final = write_integrity_evidence(
                root, value, candidate, trust_append=True
            )
            validator.validate_canary_receipt(value, candidate)
            validator._validate_canary_integrity_evidence(value, candidate, root)
            self.assertGreater(value["observed_host_config_changed_bytes"], 0)
            self.assertEqual(value["allowed_host_managed_delta_count"], 1)
            self.assertEqual(value["unexpected_changed_input_count"], 0)
            for field, replacement in (
                ("candidate_sha", "b" * 40),
                ("measurement_digest", "f" * 64),
            ):
                with self.subTest(field=field):
                    mutated = dict(final)
                    mutated[field] = replacement
                    (root / validator.CANARY_INTEGRITY_FILENAME).write_bytes(
                        validator._canonical(mutated)
                    )
                    with self.assertRaises(validator.RcValidationError):
                        validator._validate_canary_integrity_evidence(
                            value, candidate, root
                        )
            for field, replacement in (
                ("after_workspace_key_count", 2),
                ("allowed_host_managed_delta_count", 0),
                ("before_prefix_digest", "f" * 64),
                ("observed_delta_bytes", 0),
                ("observed_delta_digest", "f" * 64),
                ("unexpected_changed_input_count", 1),
            ):
                with self.subTest(classification_field=field):
                    _, mutated = write_integrity_evidence(
                        root, value, candidate, trust_append=True
                    )
                    mutated["host_config_delta"][field] = replacement
                    mutated["measurement_digest"] = validator._domain_digest(
                        validator.CANARY_INTEGRITY_MEASUREMENT_DOMAIN,
                        {
                            key: item
                            for key, item in mutated.items()
                            if key != "measurement_digest"
                        },
                    )
                    (root / validator.CANARY_INTEGRITY_FILENAME).write_bytes(
                        validator._canonical(mutated)
                    )
                    with self.assertRaises(validator.RcValidationError):
                        validator._validate_canary_integrity_evidence(
                            value, candidate, root
                        )
            write_integrity_evidence(root, value, candidate, trust_append=True)
            value["canary_workspace_identity_digest"] = "f" * 64
            with self.assertRaisesRegex(
                validator.RcValidationError,
                "RC_CANARY_INTEGRITY_RECEIPT_MISMATCH",
            ):
                validator._validate_canary_integrity_evidence(value, candidate, root)

    def test_live_canary_requires_same_process_receipt_and_exact_store_bindings(self) -> None:
        candidate = "a" * 40
        value = canary(candidate)
        with mock.patch.object(
            validator,
            "_live_canary_observation",
            return_value=live_observation(candidate),
        ), mock.patch.object(
            validator, "_validate_canary_integrity_evidence"
        ) as readback, mock.patch.object(
            validator, "_run", return_value=(candidate + "\n").encode()
        ):
            digest = validator.validate_live_canary(
                value,
                candidate,
                ROOT,
                Path("synthetic-live-store"),
            )
        self.assertEqual(
            digest,
            validator._domain_digest(
                validator.CANARY_LIVE_DOMAIN, live_observation(candidate)
            ),
        )
        readback.assert_called_once()
        for field in (
            "host_receipt_digest",
            "host_task_identity_digest",
            "host_result_digest",
            "candidate_goal_digest",
        ):
            with self.subTest(field=field), mock.patch.object(
                validator,
                "_live_canary_observation",
                return_value=live_observation(candidate),
            ), mock.patch.object(validator, "_validate_canary_integrity_evidence"):
                changed = canary(candidate)
                changed[field] = "f" * 64
                if field != "host_receipt_digest":
                    provenance = dict(changed)
                    provenance.pop("provenance_digest")
                    provenance.pop("host_receipt_digest")
                    changed["provenance_digest"] = validator._domain_digest(
                        validator.CANARY_PROVENANCE_DOMAIN, provenance
                    )
                with self.assertRaisesRegex(
                    validator.RcValidationError,
                    "RC_CANARY_LIVE_BINDING_INVALID",
                ):
                    with mock.patch.object(
                        validator, "_run", return_value=(candidate + "\n").encode()
                    ):
                        validator.validate_live_canary(
                            changed,
                            candidate,
                            ROOT,
                            Path("synthetic-live-store"),
                        )

    def test_publication_packet_requires_exact_files_evidence_and_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as evidence_directory:
            root = Path(directory)
            evidence_root = Path(evidence_directory)
            subprocess.run(("git", "init", "--quiet"), cwd=root, check=True)
            builder_path = root / "scripts/build_v4_author_packet.py"
            builder_path.parent.mkdir(parents=True)
            builder_path.write_bytes(
                (ROOT / "scripts/build_v4_author_packet.py").read_bytes()
            )
            builder = validator._load_author_packet_builder(root)
            for index, relative in enumerate(builder.REQUIRED_TRACKED_FILES):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"public fixture {index}: {relative}\n", encoding="utf-8")
            subprocess.run(("git", "add", "."), cwd=root, check=True)
            subprocess.run(
                (
                    "git",
                    "-c",
                    "commit.gpgsign=false",
                    "-c",
                    "user.name=LoopSkill Test",
                    "-c",
                    "user.email=loopskill-test@example.invalid",
                    "commit",
                    "--quiet",
                    "-m",
                    "fixture",
                ),
                cwd=root,
                check=True,
            )
            candidate = subprocess.check_output(
                ("git", "rev-parse", "HEAD"), cwd=root, text=True
            ).strip()
            subprocess.run(
                ("git", "update-ref", "refs/remotes/origin/main", candidate),
                cwd=root,
                check=True,
            )
            subprocess.run(("git", "tag", "v3.3.8", candidate), cwd=root, check=True)
            subprocess.run(
                ("git", "tag", "paper-treatment-v3.3.12", candidate),
                cwd=root,
                check=True,
            )
            evidence = {}
            for index, key in enumerate(builder.REQUIRED_EVIDENCE_RECEIPTS):
                path = evidence_root / f"receipt-{index}.json"
                receipt = receipt_for(key, candidate)
                if key == "release_identity_preflight":
                    receipt.update(
                        {
                            "origin_main_commit": candidate,
                            "paper_reference_commit": candidate,
                            "v3_baseline_commit": candidate,
                        }
                    )
                path.write_text(
                    json.dumps(receipt),
                    encoding="utf-8",
                )
                evidence[key] = path
            packet = builder.build_packet(root, candidate, evidence)
            fault_contract = mock.patch.object(
                validator, "_fault_contract_counts", return_value=(3, 9, 11)
            )
            fault_contract.start()
            self.addCleanup(fault_contract.stop)
            validator.validate_author_packet(packet, candidate, root, evidence)
            changed = dict(packet)
            changed["public_release_effects"] = 1
            with self.assertRaisesRegex(
                validator.RcValidationError, "RC_AUTHOR_PACKET_INVALID"
            ):
                validator.validate_author_packet(changed, candidate, root, evidence)
            changed = dict(packet)
            changed["evidence_receipts"] = dict(packet["evidence_receipts"])
            changed["evidence_receipts"].pop("coverage")
            with self.assertRaisesRegex(
                validator.RcValidationError, "RC_AUTHOR_PACKET_EVIDENCE_INVALID"
            ):
                validator.validate_author_packet(changed, candidate, root, evidence)
            forged = dict(packet)
            forged["evidence_receipts"] = {
                key: "f" * 64 for key in packet["evidence_receipts"]
            }
            forged_body = {
                key: item for key, item in forged.items() if key != "packet_digest"
            }
            forged["packet_digest"] = builder._packet_digest(forged_body)
            with self.assertRaisesRegex(
                validator.RcValidationError,
                "RC_AUTHOR_PACKET_EVIDENCE_DIGEST_MISMATCH",
            ):
                validator.validate_author_packet(forged, candidate, root, evidence)

    def test_conformance_receipt_requires_all_349_canonical_results(self) -> None:
        candidate = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        with tempfile.TemporaryDirectory() as directory:
            issued = datetime.now(timezone.utc).replace(microsecond=0)
            path_2 = Path(directory) / "canary-2.json"
            path_8 = Path(directory) / "canary-8.json"
            path_2.write_bytes(
                validator._canonical(
                    canary(candidate, goal_count=2, route_digit="2", issued=issued)
                )
            )
            path_8.write_bytes(
                validator._canonical(
                    canary(
                        candidate,
                        goal_count=8,
                        route_digit="8",
                        issued=issued + timedelta(minutes=1),
                    )
                )
            )
            with mock.patch.object(
                runner,
                "_run_test",
                side_effect=lambda test_id: {
                    "assertion_test_id": test_id,
                    "result_digest": hashlib.sha256(
                        validator._canonical(
                            {"assertion_test_id": test_id, "status": "PASS", "tests_run": 1}
                        )
                    ).hexdigest(),
                    "status": "PASS",
                    "tests_run": 1,
                },
            ):
                value = runner.run(ROOT, candidate, path_2, path_8)
        validator.validate_conformance_receipt(value, candidate, ROOT)
        changed_profile = dict(value)
        changed_profile["evidence_profile"] = "SELECTOR_SPECIFIC_OBSERVATIONS"
        with self.assertRaisesRegex(
            validator.RcValidationError, "RC_CONFORMANCE_RECEIPT_INVALID"
        ):
            validator.validate_conformance_receipt(changed_profile, candidate, ROOT)
        changed_profile = dict(value)
        changed_profile["independent_case_observation_claimed"] = True
        with self.assertRaisesRegex(
            validator.RcValidationError, "RC_CONFORMANCE_RECEIPT_INVALID"
        ):
            validator.validate_conformance_receipt(changed_profile, candidate, ROOT)
        changed_count = dict(value)
        changed_count["test_method_count"] = 73
        with self.assertRaisesRegex(
            validator.RcValidationError, "RC_CONFORMANCE_RECEIPT_INVALID"
        ):
            validator.validate_conformance_receipt(changed_count, candidate, ROOT)
        changed_mapping_count = dict(value)
        changed_mapping_count["semantic_coverage_mapping_count"] = 348
        with self.assertRaisesRegex(
            validator.RcValidationError, "RC_CONFORMANCE_RECEIPT_INVALID"
        ):
            validator.validate_conformance_receipt(
                changed_mapping_count, candidate, ROOT
            )
        value["case_results"][0]["case_id"] = "CASE-NOT-IN-FROZEN-CATALOG"
        value["case_results_digest"] = hashlib.sha256(
            validator._canonical(value["case_results"])
        ).hexdigest()
        value["case_results"][0]["status"] = "FAIL"
        with self.assertRaisesRegex(
            validator.RcValidationError, "RC_CONFORMANCE_RECEIPT_INVALID"
        ):
            validator.validate_conformance_receipt(value, candidate, ROOT)

    def test_static_gate_binds_exact_clean_sha_tree_sbom_and_scans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Fixture"], cwd=repo, check=True)
            (repo / "protocol/v4").mkdir(parents=True)
            (repo / "protocol/v4/loopskill-v4.protocol.json").write_text(
                json.dumps(
                    {
                        "capability_names": ["c"],
                        "commands": {"C": {}},
                        "errors": ["E"],
                        "events": {"V": {}},
                    }
                ),
                encoding="utf-8",
            )
            (repo / "LICENSE").write_text("MIT License\n", encoding="utf-8")
            (repo / "VERSION").write_text("4.1.0\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
            sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            dependencies = [
                {"distribution": "fixture", "license": "MIT", "version": "1"}
            ]
            with mock.patch.object(
                validator, "_dependency_inventory", return_value=dependencies
            ), mock.patch.object(
                validator,
                "_runtime_identity",
                return_value={"runtime_identity_digest": "d" * 64},
            ):
                receipt = validator.static_receipt(repo, sha)
            self.assertEqual(receipt["candidate_sha"], sha)
            self.assertEqual(receipt["dependency_inventory"], dependencies)
            self.assertEqual(receipt["secret_findings"], [])
            self.assertEqual(receipt["stale_production_findings"], [])
            self.assertEqual(receipt["distribution_archive"]["findings"], [])
            self.assertEqual(receipt["distribution_archive"]["file_count"], 3)
            self.assertEqual(receipt["sbom"]["spdxVersion"], "SPDX-2.3")
            self.assertEqual(receipt["sbom"]["packages"][0]["versionInfo"], "4.1.0")
            self.assertEqual(
                receipt["sbom_sha256"],
                hashlib.sha256(validator._canonical(receipt["sbom"])).hexdigest(),
            )
            self.assertEqual(receipt["public_effects"], 0)
            (repo / "dirty").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(
                validator.RcValidationError, "NOT_EXACT_CLEAN_HEAD"
            ):
                validator.static_receipt(repo, sha)

            (repo / "dirty").unlink()
            retired = repo / "codex-loop-prompt-architect/scripts/runtime.py"
            retired.parent.mkdir(parents=True)
            retired.write_text("COMMAND = 'ImportV3Snapshot'\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "retired runtime"], cwd=repo, check=True)
            stale_sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            with mock.patch.object(
                validator, "_dependency_inventory", return_value=dependencies
            ), mock.patch.object(
                validator,
                "_runtime_identity",
                return_value={"runtime_identity_digest": "d" * 64},
            ), self.assertRaisesRegex(
                validator.RcValidationError, "STALE_V3_PRODUCTION_SCAN_FAILED"
            ):
                validator.static_receipt(repo, stale_sha)

            retired.unlink()
            retired_doc = repo / "P0-CLOSURE.md"
            retired_doc.write_text("retired v3 current-product narrative\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "retired docs"], cwd=repo, check=True)
            stale_doc_sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            with mock.patch.object(
                validator, "_dependency_inventory", return_value=dependencies
            ), mock.patch.object(
                validator,
                "_runtime_identity",
                return_value={"runtime_identity_digest": "d" * 64},
            ), self.assertRaisesRegex(
                validator.RcValidationError, "STALE_V3_PRODUCTION_SCAN_FAILED"
            ):
                validator.static_receipt(repo, stale_doc_sha)

    def test_distribution_archive_rejects_unsafe_members(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "fixture@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Fixture"],
                cwd=repo,
                check=True,
            )
            (repo / "safe.txt").write_text("safe\n", encoding="utf-8")
            (repo / "unsafe-link").symlink_to("safe.txt")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
            sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            with self.assertRaisesRegex(
                validator.RcValidationError,
                "RC_DISTRIBUTION_ARCHIVE_SCAN_FAILED",
            ):
                validator._distribution_archive_receipt(repo, sha)


if __name__ == "__main__":
    unittest.main()
