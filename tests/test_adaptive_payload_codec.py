from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "codex-loop-prompt-architect" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from loop_architect.state_runtime import (  # noqa: E402
    PAYLOAD_DIGEST_PLACEHOLDER,
    RuntimeRejection,
    materialize_dispatch_payload,
    verify_dispatch_payload,
)


CLI = SCRIPTS / "adaptive_state_runtime.py"


class AdaptivePayloadCodecTests(unittest.TestCase):
    def specification(self) -> dict[str, object]:
        claim = {
            "lease_epoch": 7,
            "lease_id": "lease-review-7",
            "routing_turn_id": "turn-review-7",
            "owner_kind": "GOAL_TURN",
            "owner_identity": "controller-1",
            "intended_transition": "ROUTE_ONE_TRANSITION",
        }
        return {
            "envelope_type": "REVIEW_DISPATCH",
            "payload": {
                "artifact_identity": {"kind": "NO_DIFF"},
                "canonical_state_snapshot": {
                    "active_milestone_id": "m1",
                    "controller_lease": {
                        "claim": claim,
                        "routing_turn_id": "turn-review-7",
                        "acquired_at": "2026-01-01T00:00:00Z",
                        "expires_at": "2026-01-01T01:00:00Z",
                        "route_action": None,
                    },
                    "loop_id": "loop-1",
                    "roadmap_version": 3,
                    "state_version": 41,
                },
                "code_review_id": None,
                "decision_contract": {
                    "allowed": ["REVIEW_PASS"],
                    "transport_probe": "<tag>&中文 &lt;literal",
                },
                "dispatch_lease_claim": claim,
                "dispatch_payload_digest": PAYLOAD_DIGEST_PLACEHOLDER,
                "evidence_refs": [".codex-loop/reports/worker.json"],
                "goal_id": "g1",
                "local_verification_ack_identity": None,
                "milestone_id": "m1",
                "review_dispatch_id": "review-code-m1-001",
                "review_kind": "CODE_REVIEW",
                "roadmap_audit_id": None,
                "roadmap_version": 3,
                "source_artifact_digest": "sha256:" + "a" * 64,
                "source_worker_dispatch_id": "dispatch-g1-001",
                "source_worker_report_digest": "sha256:" + "b" * 64,
                "target_thread_id": "reviewer-1",
            },
        }

    def test_materialize_and_verify_round_trip(self) -> None:
        result = materialize_dispatch_payload(self.specification())
        self.assertEqual(result["status"], "PAYLOAD_MATERIALIZED")
        self.assertFalse(result["transport_text"].endswith("\n"))
        self.assertNotIn("<", result["transport_text"])
        self.assertNotIn(">", result["transport_text"])
        self.assertNotIn("&", result["transport_text"])
        verified = verify_dispatch_payload(result["transport_text"])
        self.assertEqual(verified["status"], "PAYLOAD_BYTES_VERIFIED")
        self.assertEqual(verified["verification_mode"], "STRICT_SEMANTIC_CANONICAL_V1")
        self.assertEqual(verified["payload_digest"], result["payload_digest"])
        self.assertEqual(
            verified["canonical_byte_count"], result["canonical_byte_count"]
        )

    def test_old_angle_bracket_interpretation_is_not_the_protocol(self) -> None:
        result = materialize_dispatch_payload(self.specification())
        transport = result["transport_text"]
        declared = result["payload_digest"]
        old_canonical = transport.replace(
            declared.removeprefix("sha256:"),
            f"<{PAYLOAD_DIGEST_PLACEHOLDER}>",
        )
        old_digest = "sha256:" + hashlib.sha256(old_canonical.encode("utf-8")).hexdigest()
        self.assertNotEqual(old_digest, declared)
        malformed = transport.replace(declared, old_digest)
        with self.assertRaisesRegex(RuntimeRejection, "DISPATCH_PAYLOAD_DIGEST_MISMATCH"):
            verify_dispatch_payload(malformed)

    def test_limited_line_ending_normalization_and_duplicate_key_rejection(self) -> None:
        result = materialize_dispatch_payload(self.specification())
        transport = result["transport_text"]
        for variant in (
            transport + "\n",
            transport.replace("\n", "\r\n", 1),
            transport.replace("\n", "\r\n", 1) + "\r\n",
        ):
            verified = verify_dispatch_payload(variant)
            self.assertEqual(verified["payload_digest"], result["payload_digest"])
            self.assertTrue(verified["transport_normalized"])
        for malformed in (transport + "\n\n", transport.replace("\n", "\r", 1)):
            with self.assertRaisesRegex(
                RuntimeRejection, "DISPATCH_PAYLOAD_NONCANONICAL"
            ):
                verify_dispatch_payload(malformed)
        duplicate = (
            'REVIEW_DISPATCH\n{"dispatch_payload_digest":"sha256:'
            + "0" * 64
            + '","dispatch_payload_digest":"sha256:'
            + "0" * 64
            + '"}'
        )
        with self.assertRaisesRegex(RuntimeRejection, "DISPATCH_PAYLOAD_JSON_INVALID"):
            verify_dispatch_payload(duplicate)

    def test_transport_safe_escapes_preserve_semantics_and_entities_do_not(self) -> None:
        result = materialize_dispatch_payload(self.specification())
        transport = result["transport_text"]
        self.assertIn("\\u003ctag\\u003e\\u0026", transport)
        self.assertIn("\\u4e2d\\u6587", transport)
        self.assertIn("\\u0026lt;literal", transport)
        self.assertEqual(
            verify_dispatch_payload(transport)["payload_digest"],
            result["payload_digest"],
        )

        envelope, payload_text = transport.split("\n", 1)
        payload = json.loads(payload_text)
        legacy_literal = envelope + "\n" + json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(
            verify_dispatch_payload(legacy_literal)["payload_digest"],
            result["payload_digest"],
        )

        entity_changed = transport.replace("\\u003c", "&lt;", 1)
        with self.assertRaisesRegex(
            RuntimeRejection, "DISPATCH_PAYLOAD_DIGEST_MISMATCH"
        ):
            verify_dispatch_payload(entity_changed)

    def test_materializer_requires_exact_placeholder_and_closed_input(self) -> None:
        wrong = self.specification()
        wrong["payload"]["dispatch_payload_digest"] = "<PAYLOAD_DIGEST_PLACEHOLDER>"  # type: ignore[index]
        with self.assertRaisesRegex(RuntimeRejection, "DISPATCH_PAYLOAD_PLACEHOLDER_INVALID"):
            materialize_dispatch_payload(wrong)
        extra = self.specification()
        extra["extra"] = True
        with self.assertRaisesRegex(RuntimeRejection, "DISPATCH_MATERIALIZATION_INPUT_INVALID"):
            materialize_dispatch_payload(extra)

    def test_cli_materialize_and_verify_requires_canonical_root(self) -> None:
        materialized = subprocess.run(
            [sys.executable, str(CLI), "--payload-materialize"],
            input=json.dumps(self.specification(), ensure_ascii=False),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(materialized.returncode, 0, materialized.stdout)
        result = json.loads(materialized.stdout)
        verified = subprocess.run(
            [sys.executable, str(CLI), "--payload-verify"],
            input=result["transport_text"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(verified.returncode, 2, verified.stdout)
        self.assertEqual(json.loads(verified.stdout)["status"], "CLI_ARGUMENT_INVALID")

    def test_cli_verify_with_root_requires_canonical_state(self) -> None:
        materialized = materialize_dispatch_payload(self.specification())
        result = subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--root",
                str(ROOT),
                "--payload-verify",
            ],
            input=materialized["transport_text"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout)["status"], "DISPATCH_CANONICAL_STATE_MISSING"
        )

    def test_minimal_self_consistent_payload_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeRejection, "DISPATCH_PAYLOAD_SCHEMA_INVALID"):
            materialize_dispatch_payload(
                {
                    "envelope_type": "REVIEW_DISPATCH",
                    "payload": {
                        "dispatch_payload_digest": PAYLOAD_DIGEST_PLACEHOLDER,
                    },
                }
            )


if __name__ == "__main__":
    unittest.main()
