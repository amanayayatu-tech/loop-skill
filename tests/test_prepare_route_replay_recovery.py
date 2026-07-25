from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from state_runtime_support import *  # noqa: F403
from test_adaptive_state_mcp import (  # noqa: E402
    McpHarness,
    call_runtime_codec,
    call_state_gateway,
    mcp,
    synthetic_host_attestation,
)


class PrepareRouteReplayRecoveryTests(unittest.TestCase):
    def _run_worker_route(self, *, discard_first_response: bool) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = Harness(root)  # noqa: F405
            initialized, _ = state.initialize(
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

            prepare_request = {
                "request_id": "prepared-route-recovery-prepare",
                "operation": "PREPARE_ROUTE",
                "occurred_at": T1,  # noqa: F405
                "parameters": {
                    "route_id": "prepared-route-recovery-worker-route",
                    "goal_id": "g1",
                    "route_kind": "WORKER",
                    "target_thread_id": "worker-1",
                    "observed_at": T1,  # noqa: F405
                },
            }
            first = call_state_gateway(server, root, prepare_request)
            self.assertTrue(first["ok"], first)
            self.assertEqual(first["operation_status"], "GATEWAY_ROUTE_PREPARED")
            first_result = copy.deepcopy(first["result"])
            state_after_prepare = copy.deepcopy(state.state())
            persisted_after_prepare = persisted_snapshot(root)  # noqa: F405

            if discard_first_response:
                recovered = call_state_gateway(server, root, prepare_request)
                self.assertTrue(recovered["ok"], recovered)
                self.assertEqual(
                    recovered["operation_status"], "IDEMPOTENT_REPLAY"
                )
                self.assertEqual(recovered["result"], first_result)
                self.assertEqual(
                    recovered["next_action_code"], "MATERIALIZE_AND_SEND_ONCE"
                )
                self.assertEqual(state.state(), state_after_prepare)
                self.assertEqual(
                    persisted_snapshot(root), persisted_after_prepare  # noqa: F405
                )
                route_result = recovered["result"]
            else:
                route_result = first_result

            current = state.state()
            self.assertEqual(len(current["gateway_route_ledger"]), 1)
            self.assertEqual(len(current["dispatch_outbox"]), 1)
            self.assertEqual(current["routing_turn_count"], 1)
            self.assertEqual(current["lease_epoch_counter"], 1)
            self.assertEqual(
                len(current["goal_execution_ledger"]["g1"]["attempts"]), 0
            )

            specification = route_result["payload_specification"]
            materialized = mcp.execute_runtime_codec(
                "MATERIALIZE_DISPATCH", request=specification
            )
            self.assertTrue(materialized["ok"], materialized)
            self.assertEqual(
                materialized["payload_digest"], route_result["payload_digest"]
            )

            app_send_calls: list[dict[str, str]] = []

            def app_send_once(transport_text: str, target_thread_id: str) -> str:
                app_send_calls.append(
                    {
                        "transport_text": transport_text,
                        "target_thread_id": target_thread_id,
                    }
                )
                return target_thread_id

            returned_thread_id = app_send_once(
                materialized["transport_text"], "worker-1"
            )
            self.assertEqual(returned_thread_id, "worker-1")
            self.assertEqual(len(app_send_calls), 1)
            sent = call_state_gateway(
                server,
                root,
                {
                    "request_id": "prepared-route-recovery-send",
                    "operation": "RECORD_ROUTE_SENT",
                    "occurred_at": T2,  # noqa: F405
                    "parameters": {
                        "route_id": "prepared-route-recovery-worker-route",
                        "message_id": "prepared-route-recovery-message",
                        "target_thread_id": returned_thread_id,
                        "observed_at": T2,  # noqa: F405
                    },
                },
            )
            self.assertTrue(sent["ok"], sent)
            self.assertEqual(len(app_send_calls), 1)
            verified = mcp.execute_runtime_codec(
                "VERIFY_DISPATCH",
                root=str(root),
                transport_text=materialized["transport_text"],
            )
            self.assertTrue(verified["ok"], verified)

            worker_result = {
                "status": "PASS",
                "artifact_digest": digest("prepared-route-recovery-artifact"),  # noqa: F405
            }
            staged = call_runtime_codec(
                server,
                {
                    "operation": "STAGE_REPORT",
                    "root": str(root),
                    "request": {
                        "outbox_id": "prepared-route-recovery-worker-route",
                        "result": worker_result,
                        "report_text": state.formal_report_content(
                            "DISPATCH",
                            "prepared-route-recovery-worker-route",
                            worker_result,
                        ),
                    },
                },
                thread_id="worker-1",
                turn_id="prepared-route-recovery-worker-stage",
            )
            self.assertTrue(staged["ok"], staged)
            acknowledged = call_state_gateway(
                server,
                root,
                {
                    "request_id": "prepared-route-recovery-ack",
                    "operation": "ACK_ROUTE_RESULT",
                    "occurred_at": T3,  # noqa: F405
                    "parameters": {
                        "route_id": "prepared-route-recovery-worker-route",
                        "staged_report": {
                            **staged["artifact"],
                            "result": staged["result"],
                        },
                    },
                },
            )
            self.assertTrue(acknowledged["ok"], acknowledged)
            closed = state.state()
            self.assertEqual(
                closed["gateway_route_ledger"]
                ["prepared-route-recovery-worker-route"]["status"],
                "ACKED",
            )
            self.assertEqual(
                closed["dispatch_outbox"]
                ["prepared-route-recovery-worker-route"]["status"],
                "COMPLETED",
            )
            self.assertEqual(
                len(closed["goal_execution_ledger"]["g1"]["attempts"]), 1
            )
            self.assertEqual(len(app_send_calls), 1)

    def test_first_prepare_response_follows_normal_full_route_closure(self) -> None:
        self._run_worker_route(discard_first_response=False)

    def test_discarded_prepare_response_recovers_and_follows_full_route_closure(
        self,
    ) -> None:
        self._run_worker_route(discard_first_response=True)


if __name__ == "__main__":
    unittest.main()
