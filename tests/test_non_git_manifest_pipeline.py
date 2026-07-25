from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from state_runtime_support import *  # noqa: F403
from test_adaptive_state_mcp import (  # noqa: E402
    McpHarness,
    call_runtime_codec,
    call_state_gateway,
    mcp,
    synthetic_host_attestation,
)
from test_loop_prompt_scaffold import base_payload, scaffold  # noqa: E402

import adaptive_state_runtime as runtime_codec_module  # noqa: E402


ARTIFACT_PATH = "loopskill-synthetic-canary.txt"
ARTIFACT_BYTES = b"LOOPSKILL_EFFECTIVENESS_V1_SYNTHETIC_CANARY_OK\n"
ARTIFACT_SHA256 = (
    "275c22e606b28226dd190509e6d74912279f714b1f193114ca9dcd2645ef417f"
)


def non_git_scaffold_payload(root: Path) -> dict[str, Any]:  # noqa: F405
    payload = base_payload()
    payload.update(
        {
            "repo": str(root),
            "repo_mode": "non_git",
            "coordination_mode": "adaptive",
            "adaptive_reason": "One durable non-Git route must yield a reviewable artifact",
            "allowed": [ARTIFACT_PATH],
            "workers": [
                {
                    "role": "implementation",
                    "role_kind": "implementation",
                    "scope": "create the frozen synthetic artifact",
                    "permission": "workspace_write",
                    "allowed": [ARTIFACT_PATH],
                }
            ],
            "goals": [
                {
                    "goal_id": "G1",
                    "milestone_id": "M1",
                    "worker_role": "implementation",
                    "objective": "Create the frozen synthetic artifact",
                    "success_criteria": ["The exact 47-byte artifact exists"],
                    "phase_permissions": {"branch_create": False},
                }
            ],
            "milestones": [
                {
                    "milestone_id": "M1",
                    "outcome": "Produce one reviewable artifact",
                    "scope": [ARTIFACT_PATH],
                    "decisions": [],
                    "blockers": [],
                    "required_evidence": ["strict runtime manifest"],
                    "status": "ACTIVE",
                    "depends_on": [],
                    "references": ["G1"],
                }
            ],
        }
    )
    for field in ("branch", "base_branch", "target_branch"):
        payload.pop(field, None)
    payload["_provided_keys"] = sorted(
        key for key in payload if not key.startswith("_")
    )
    return payload


class NonGitManifestPipelineTests(unittest.TestCase):
    def test_official_non_git_pack_reaches_reviewable_pass_without_git_capture(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "non-git-project"
            root.mkdir()
            git_probe = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(git_probe.returncode, 0, git_probe.stdout)
            scaffold_payload = non_git_scaffold_payload(root)
            self.assertEqual(scaffold.validation_errors(scaffold_payload), [])
            pack = scaffold.render_controller_pack(scaffold_payload, "compact")
            self.assertIn("runtime_codec CAPTURE_MANIFEST_DELTA", pack)
            self.assertIn(
                "Do not call runtime_codec CAPTURE_COMPLETE_DIFF in repo_mode=non_git",
                pack,
            )

            definition = goal(  # noqa: F405
                "g1",
                "m1",
                objective="Create the frozen synthetic artifact",
            )
            definition["success_criteria"] = [
                "The exact 47-byte artifact exists"
            ]
            definition["allowed_write_scope"] = [ARTIFACT_PATH]
            definition["payload_template_digest"] = goal_definition_digest(  # noqa: F405
                definition
            )
            milestone_definition = milestone("m1", "ACTIVE")  # noqa: F405
            milestone_definition["scope"] = [ARTIFACT_PATH]
            authorization = authorization_envelope(  # noqa: F405
                {"g1": definition}, [milestone_definition]
            )
            authorization["allowed_write_scope"] = [ARTIFACT_PATH]
            state = Harness(root)  # noqa: F405
            initialized, _ = state.initialize(
                definitions={"g1": definition},
                milestones=[milestone_definition],
                authorization=authorization,
                state_gateway=True,
                bootstrap_threads=[
                    {
                        "thread_id": "worker-1",
                        "role_kind": "WORKER",
                        "bootstrap_role_kind": "implementation",
                        "bootstrap_prompt_digest": digest("worker-bootstrap"),  # noqa: F405
                        "worktree_path": str(root.resolve()),
                    }
                ],
            )
            self.assertTrue(initialized["ok"], initialized)
            server = mcp.AdaptiveStateMcpServer(synthetic_host_attestation())
            server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": "init",
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"},
                }
            )
            prepared = call_state_gateway(
                server,
                root,
                {
                    "request_id": "non-git-prepare",
                    "operation": "PREPARE_ROUTE",
                    "occurred_at": T1,  # noqa: F405
                    "parameters": {
                        "route_id": "non-git-worker-route",
                        "goal_id": "g1",
                        "route_kind": "WORKER",
                        "target_thread_id": "worker-1",
                        "observed_at": T1,  # noqa: F405
                    },
                },
            )
            self.assertTrue(prepared["ok"], prepared)
            baseline = prepared["result"]["manifest_before_snapshot"]
            self.assertIsInstance(baseline, dict)
            self.assertTrue(
                (root / baseline["receipt_path"]).is_file(), baseline
            )
            specification = prepared["result"]["payload_specification"]
            self.assertEqual(specification["payload"]["repo_mode"], "non_git")
            materialized = mcp.execute_runtime_codec(
                "MATERIALIZE_DISPATCH", request=specification
            )
            self.assertTrue(materialized["ok"], materialized)
            sent = call_state_gateway(
                server,
                root,
                {
                    "request_id": "non-git-send",
                    "operation": "RECORD_ROUTE_SENT",
                    "occurred_at": T2,  # noqa: F405
                    "parameters": {
                        "route_id": "non-git-worker-route",
                        "message_id": "non-git-worker-message",
                        "target_thread_id": "worker-1",
                        "observed_at": T2,  # noqa: F405
                    },
                },
            )
            self.assertTrue(sent["ok"], sent)
            verified = mcp.execute_runtime_codec(
                "VERIFY_DISPATCH",
                root=str(root),
                transport_text=materialized["transport_text"],
            )
            self.assertTrue(verified["ok"], verified)

            with mock.patch.object(
                runtime_codec_module,
                "capture_complete_diff",
                side_effect=AssertionError("Git-only capture must not run"),
            ):
                before = call_runtime_codec(
                    server,
                    {
                        "operation": "CAPTURE_MANIFEST_DELTA",
                        "root": str(root),
                        "request": {
                            "phase": "BEFORE",
                            "outbox_id": "non-git-worker-route",
                            "approved_product_paths": [ARTIFACT_PATH],
                        },
                    },
                    thread_id="worker-1",
                    turn_id="worker-before",
                )
                self.assertTrue(before["ok"], before)
                artifact = root / ARTIFACT_PATH
                artifact.write_bytes(ARTIFACT_BYTES)
                self.assertEqual(artifact.stat().st_size, 47)
                self.assertEqual(
                    hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    ARTIFACT_SHA256,
                )
                after = call_runtime_codec(
                    server,
                    {
                        "operation": "CAPTURE_MANIFEST_DELTA",
                        "root": str(root),
                        "request": {
                            "phase": "AFTER",
                            "outbox_id": "non-git-worker-route",
                            "approved_product_paths": [ARTIFACT_PATH],
                            "before_snapshot_sha256": before[
                                "snapshot_sha256"
                            ],
                        },
                    },
                    thread_id="worker-1",
                    turn_id="worker-after",
                )
            self.assertTrue(after["ok"], after)
            self.assertEqual(
                after["complete_diff_reference"]["kind"],
                "MANIFEST_DELTA_V1",
            )
            worker_result = {
                "status": "PASS",
                "artifact_digest": after["artifact_digest"],
            }
            evidence_path = (
                ".codex-loop/reports/non-git-worker-validation.txt"
            )
            evidence_digest = "sha256:" + ARTIFACT_SHA256
            report = json.loads(
                state.formal_report_content(
                    "DISPATCH", "non-git-worker-route", worker_result
                )
            )
            report.update(
                {
                    "before_snapshot_sha256": after[
                        "before_snapshot_sha256"
                    ],
                    "after_snapshot_sha256": after[
                        "after_snapshot_sha256"
                    ],
                    "current_branch": after["current_branch"],
                    "base_sha": after["base_sha"],
                    "head_sha": after["head_sha"],
                    "changed_files": after["changed_files"],
                    "diff_sha256": after["diff_sha256"],
                    "complete_diff_reference": after[
                        "complete_diff_reference"
                    ],
                    "evidence_artifacts": [
                        {
                            "path": evidence_path,
                            "size_bytes": 47,
                            "digest": evidence_digest,
                            "media_type": "text/plain",
                        }
                    ],
                }
            )
            report_text = json.dumps(
                report,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            staged = call_runtime_codec(
                server,
                {
                    "operation": "STAGE_REPORT",
                    "root": str(root),
                    "request": {
                        "outbox_id": "non-git-worker-route",
                        "result": worker_result,
                        "report_text": report_text,
                        "evidence_sources": [
                            {
                                "path": evidence_path,
                                "source_path": str(artifact.resolve()),
                                "digest": evidence_digest,
                                "media_type": "text/plain",
                            }
                        ],
                    },
                },
                thread_id="worker-1",
                turn_id="worker-stage",
            )
            self.assertTrue(staged["ok"], staged)
            acknowledged = call_state_gateway(
                server,
                root,
                {
                    "request_id": "non-git-ack",
                    "operation": "ACK_ROUTE_RESULT",
                    "occurred_at": T3,  # noqa: F405
                    "parameters": {
                        "route_id": "non-git-worker-route",
                        "staged_report": {
                            **staged["artifact"],
                            "result": staged["result"],
                            "evidence_artifacts": staged[
                                "evidence_artifacts"
                            ],
                        },
                    },
                },
            )
            self.assertTrue(acknowledged["ok"], acknowledged)
            latest = state.state()["goal_execution_ledger"]["g1"][
                "latest_worker"
            ]
            self.assertEqual(latest["status"], "PASS")
            self.assertEqual(
                latest["review_handoff"]["evidence_refs"],
                [evidence_path],
            )
            self.assertEqual(
                state.state()["artifact_ledger"][evidence_path]["digest"],
                evidence_digest,
            )
            self.assertEqual(
                latest["review_handoff"]["artifact_identity"]
                ["complete_diff_reference"]["kind"],
                "MANIFEST_DELTA_V1",
            )
            self.assertEqual(
                (root / evidence_path).read_bytes(), ARTIFACT_BYTES
            )
            self.assertFalse(
                (root / ".codex-loop" / "diff-captures").exists()
            )


if __name__ == "__main__":
    unittest.main()
