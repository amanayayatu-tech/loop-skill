from __future__ import annotations

import ast
import hashlib
import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "codex-loop-prompt-architect" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from loop_architect.v4_alpha.kernel import AuthorityContext  # noqa: E402
from loop_architect.v4_alpha.protocol import (  # noqa: E402
    PROTOCOL_MANIFEST,
    InjectedCrash,
    ProtocolRejection,
    canonical_bytes,
    parse_json_bytes,
    with_command_change,
)
from loop_architect.v4_alpha.store import (  # noqa: E402
    FAULT_BOUNDARIES,
    InMemoryStore,
)
from loop_architect.v4_alpha.vertical import (  # noqa: E402
    EXPECTED_CANONICAL_SNAPSHOT,
    EXPECTED_EVENT_TYPES,
    EXPECTED_SNAPSHOT_BYTES,
    EXPECTED_SNAPSHOT_DIGEST,
    LOOP_REF,
    fixture_authority,
    replace_grant_digest,
    run_vertical,
    vertical_commands,
    verified_vertical_evidence,
)


def changed(command, **updates):
    def apply(values):
        values.update(updates)

    return with_command_change(command, apply)


def changed_authority(
    authority: AuthorityContext,
    *,
    actors=None,
    grants=None,
    receipts=None,
) -> AuthorityContext:
    return AuthorityContext(
        actors=dict(authority.actors) if actors is None else actors,
        grants=dict(authority.grants) if grants is None else grants,
        receipts=dict(authority.receipts) if receipts is None else receipts,
        trusted_actor_issuers=dict(authority.trusted_actor_issuers),
        trusted_grant_issuers=dict(authority.trusted_grant_issuers),
        trusted_receipt_issuers=dict(authority.trusted_receipt_issuers),
    )


class V4AlphaPureKernelTests(unittest.TestCase):
    def assert_rejected(self, code, callable_):
        with self.assertRaises(ProtocolRejection) as caught:
            callable_()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def store_after(self, count, authority=None):
        store = InMemoryStore(authority or fixture_authority())
        commands = vertical_commands()
        for command in commands[:count]:
            store.apply(command)
        return store

    def test_manifest_freezes_slice_and_per_loop_cas(self):
        self.assertEqual(PROTOCOL_MANIFEST["protocol_version"], "4.1.0")
        self.assertEqual(PROTOCOL_MANIFEST["write_cas"], "per_loop_revision")
        self.assertEqual(len(PROTOCOL_MANIFEST["commands"]), 19)
        self.assertNotIn("RegisterGoalPlan", PROTOCOL_MANIFEST["commands"])
        reserved = {
            name
            for name, specification in PROTOCOL_MANIFEST[
                "semantic_payload_specs"
            ].items()
            if "reserved_until" in specification
        }
        self.assertEqual(len(set(PROTOCOL_MANIFEST["commands"]) - reserved), 19)
        self.assertEqual(reserved, set())
        self.assertIn("UNKNOWN", PROTOCOL_MANIFEST["delivery_states"])
        self.assertIn("UNVERIFIABLE", PROTOCOL_MANIFEST["delivery_states"])
        self.assertNotIn("store_version", PROTOCOL_MANIFEST)

    def test_canonical_encoder_all_ten_instances(self):
        vectors = (
            (
                {"b": "x", "a": 1},
                b'{"a":1,"b":"x"}',
                "72b469858b6fc86a27886bd3a124d2f786cbd13b49f832066bfdd02a8e29e5c9",
            ),
            (
                {"文本": "循环", "a": "é"},
                '{"a":"é","文本":"循环"}'.encode(),
                "0c1a46d9b0f72a73d77d1eb258162f91abace9bd8f9b02f12c55de628aa715f9",
            ),
            (
                {"s": "é"},
                '{"s":"é"}'.encode(),
                "5e82ac250d21f269ef0533ef3d3f666d63cc4a38f189b1bd9726e387155560e3",
            ),
            (
                {"s": "e\u0301"},
                '{"s":"é"}'.encode(),
                "57722ecfcbc5a2f3702e509f9f9650ac5ed391c711b7ea311b48fbf675929afd",
            ),
            (
                {"s": '"\b\f\n\r\t\\'},
                b'{"s":"\\"\\b\\f\\n\\r\\t\\\\"}',
                "007f283d289bc702edf5a6819a4e9a6ac52a06061862edcee10dceec775825e5",
            ),
            (
                {"\ue000": 4, "中": 3, "é": 2, "A": 1},
                '{"A":1,"é":2,"中":3,"\ue000":4}'.encode(),
                "be4430d368dbd602ae91ae7e69c40ac01145d2172b5fbfb02228cd5271790ad1",
            ),
        )
        domain = b"loopskill-canonical-vector-v1\n"
        for index, (value, expected, digest) in enumerate(vectors, 1):
            with self.subTest(instance=f"ENC-001-{index}"):
                actual = canonical_bytes(value)
                self.assertEqual(actual, expected)
                self.assertEqual(len(actual), len(expected))
                self.assertEqual(hashlib.sha256(domain + actual).hexdigest(), digest)

        invalid = (
            (b'"\xff"', "INVALID_UTF8"),
            (b'{"a":1,"a":2}', "INVALID_COMMAND"),
            (b'{"n":1.0}', "INVALID_COMMAND"),
            (b'{"n":1e2}', "INVALID_COMMAND"),
            (b'{"n":-0}', "INVALID_COMMAND"),
            (b'{"n":9223372036854775808}', "RESOURCE_LIMIT_EXCEEDED"),
        )
        for raw, code in invalid:
            with self.subTest(raw=raw):
                self.assert_rejected(code, lambda raw=raw: parse_json_bytes(raw))

    def test_corrected_vertical_exact_snapshot_events_and_replay(self):
        store = InMemoryStore(fixture_authority())
        event_offset = 0
        for command in vertical_commands():
            result = store.apply(command)
            commit_count = store.commit_count
            events = store.events(LOOP_REF)
            replay = store.apply(command)
            self.assertTrue(replay.replayed)
            self.assertEqual(replay.response, result.response)
            self.assertEqual(replay.snapshot_digest, result.snapshot_digest)
            self.assertEqual(store.commit_count, commit_count)
            self.assertEqual(store.events(LOOP_REF), events)
            event_offset += len(result.event_types)
            self.assertEqual(len(events), event_offset)

        snapshot = store.snapshot(LOOP_REF)
        raw = canonical_bytes(snapshot)
        self.assertEqual(raw, EXPECTED_CANONICAL_SNAPSHOT)
        self.assertEqual(len(raw), EXPECTED_SNAPSHOT_BYTES)
        self.assertEqual(result.snapshot_digest, EXPECTED_SNAPSHOT_DIGEST)
        self.assertEqual(
            tuple(event["type"] for event in store.events(LOOP_REF)),
            EXPECTED_EVENT_TYPES,
        )
        self.assertEqual(store.commit_count, 11)

        runner_snapshot, runner_events, runner_results = run_vertical()
        self.assertEqual(runner_snapshot, snapshot)
        self.assertEqual(runner_events, tuple(store.events(LOOP_REF)))
        self.assertEqual(runner_results[-1].snapshot_digest, EXPECTED_SNAPSHOT_DIGEST)

    def test_failed_limitation_and_stopped_are_honest_terminal_paths(self):
        chains = (
            ("FAILED", "LIMITATION", "FAILED", "FAILED"),
            ("UNVERIFIABLE", "LIMITATION", "LIMITATION", "LIMITATION"),
        )
        commands = vertical_commands()
        for outcome, verdict, goal_disposition, final_disposition in chains:
            with self.subTest(outcome=outcome):
                store = self.store_after(5)
                tail = (
                    changed(
                        commands[5],
                        semantic_payload={
                            "outcome": outcome,
                            "summary": f"honest {outcome.lower()} result",
                        },
                    ),
                    commands[6],
                    changed(commands[7], semantic_payload={"verdict": verdict}),
                    changed(
                        commands[8],
                        semantic_payload={"disposition": goal_disposition},
                    ),
                    changed(
                        commands[9],
                        semantic_payload={"disposition": final_disposition},
                    ),
                    commands[10],
                )
                for command in tail:
                    store.apply(command)
                snapshot = store.snapshot(LOOP_REF)
                self.assertEqual(snapshot["execution"]["state"], "TERMINAL")
                self.assertEqual(
                    snapshot["execution"]["disposition"], final_disposition
                )
                self.assertEqual(snapshot["results"]["result-0001"]["outcome"], outcome)
                self.assertEqual(
                    snapshot["goals"]["goal-0001"]["state"], goal_disposition
                )

        stop = changed(
            commands[0],
            operation_id="operation-stop-0001",
            command_type="StopLoop",
            protocol_version="4.0.0",
            actor_ref="actor-author-0001",
            authority_grant_ref="grant-author-0001",
            expected_loop_revision=1,
            expected_subject_revisions={"execution": 1, "goal-0001": 1},
            machine_bindings={
                "allocate_refs": {},
                "receipt_refs": {},
                "resolved_refs": {},
            },
            semantic_payload={"reason": "author requested a bounded stop"},
        )
        store = self.store_after(1)
        result = store.apply(stop)
        snapshot = store.snapshot(LOOP_REF)
        self.assertEqual(result.event_types, ("GoalAdvanced", "LoopStopped"))
        self.assertEqual(snapshot["execution"]["disposition"], "STOPPED")
        self.assertEqual(snapshot["goals"]["goal-0001"]["state"], "STOPPED")
        self.assertTrue(store.apply(stop).replayed)

    def test_stop_loop_cas_authority_and_unresolved_effect_are_honest(self):
        commands = vertical_commands()

        def stop_for(revision, *, operation="operation-stop-gate", expected=None):
            return changed(
                commands[0],
                operation_id=operation,
                command_type="StopLoop",
                protocol_version="4.0.0",
                actor_ref="actor-author-0001",
                authority_grant_ref="grant-author-0001",
                expected_loop_revision=revision,
                expected_subject_revisions=expected
                or {"execution": 1, "goal-0001": 1},
                machine_bindings={
                    "allocate_refs": {},
                    "receipt_refs": {},
                    "resolved_refs": {},
                },
                semantic_payload={"reason": "bounded author stop"},
            )

        store = self.store_after(1)
        command = stop_for(1)
        store.apply(command)
        self.assertTrue(store.apply(command).replayed)

        stale_store = self.store_after(1)
        stale = stop_for(0, operation="operation-stop-stale")
        self.assert_rejected("STALE_LOOP_REVISION", lambda: stale_store.apply(stale))

        forged_store = self.store_after(1)
        forged = changed(
            stop_for(1, operation="operation-stop-forged"),
            actor_ref="actor-forged-0001",
        )
        self.assert_rejected("INVALID_AUTHORITY", lambda: forged_store.apply(forged))

        base = fixture_authority()
        unknown_receipt = replace(
            base.receipts["receipt-delivery-0001"], outcome="unknown"
        )
        authority = changed_authority(
            base,
            receipts={**base.receipts, unknown_receipt.receipt_ref: unknown_receipt},
        )
        unresolved = self.store_after(4, authority)
        unresolved.apply(commands[4])
        stop_after_unknown = stop_for(
            5,
            operation="operation-stop-after-unknown",
            expected={"execution": 1, "goal-0001": 1, "attempt-0001": 2},
        )
        unresolved.apply(stop_after_unknown)
        snapshot = unresolved.snapshot(LOOP_REF)
        self.assertEqual(snapshot["attempts"]["attempt-0001"]["state"], "UNKNOWN")
        self.assertEqual(snapshot["execution"]["disposition"], "STOPPED")

    def test_verified_vertical_evidence_is_identity_free_and_exact(self):
        self.assertEqual(
            verified_vertical_evidence(),
            {
                "assurance": "STRICT",
                "event_count": 18,
                "final_event_from_typed_fixture": EXPECTED_EVENT_TYPES[-1],
                "finalization": "ACKNOWLEDGED",
                "operation_count": 11,
                "result": "ACKNOWLEDGED",
                "review": "PASS",
                "snapshot_bytes": EXPECTED_SNAPSHOT_BYTES,
                "snapshot_digest": EXPECTED_SNAPSHOT_DIGEST,
            },
        )

    def test_changed_accepted_and_rejected_operations_conflict(self):
        command = vertical_commands()[0]
        store = InMemoryStore(fixture_authority())
        store.apply(command)
        modified = changed(
            command, semantic_payload={"objective": "different objective"}
        )
        self.assert_rejected("IDEMPOTENCY_CONFLICT", lambda: store.apply(modified))

        store = self.store_after(1)
        rejected = changed(vertical_commands()[1], actor_ref="actor-forged-0001")
        first = self.assert_rejected("INVALID_AUTHORITY", lambda: store.apply(rejected))
        rejection_count = store.rejection_count
        second = self.assert_rejected("INVALID_AUTHORITY", lambda: store.apply(rejected))
        self.assertEqual(second.detail, first.detail)
        self.assertEqual(store.rejection_count, rejection_count)
        changed_rejection = changed(
            rejected, semantic_payload={"role": "different-role"}
        )
        self.assert_rejected(
            "IDEMPOTENCY_CONFLICT", lambda: store.apply(changed_rejection)
        )

    def test_stale_loop_and_subject_revisions_are_pure_rejections(self):
        store = self.store_after(1)
        stale_loop = changed(vertical_commands()[1], expected_loop_revision=0)
        before = store.snapshot(LOOP_REF), store.events(LOOP_REF), store.commit_count
        self.assert_rejected("STALE_LOOP_REVISION", lambda: store.apply(stale_loop))
        self.assertEqual(
            (store.snapshot(LOOP_REF), store.events(LOOP_REF), store.commit_count),
            before,
        )

        store = self.store_after(2)
        stale_subject = changed(
            vertical_commands()[2],
            expected_subject_revisions={
                "goal-0001": 0,
                "host-target-0001": 1,
            },
        )
        before = store.snapshot(LOOP_REF), store.events(LOOP_REF), store.commit_count
        self.assert_rejected(
            "STALE_SUBJECT_REVISION", lambda: store.apply(stale_subject)
        )
        self.assertEqual(
            (store.snapshot(LOOP_REF), store.events(LOOP_REF), store.commit_count),
            before,
        )

    def test_wrong_kind_and_foreign_references_fail_closed(self):
        base_authority = fixture_authority()
        grant = base_authority.grants["grant-author-0001"]
        grants = dict(base_authority.grants)
        grants[grant.grant_ref] = replace_grant_digest(
            replace(
                grant,
                exact_subjects=grant.exact_subjects
                + ("host-target-0001", "goal-foreign-0001"),
            )
        )
        authority = changed_authority(base_authority, grants=grants)

        store = self.store_after(2, authority)
        wrong_kind = changed(
            vertical_commands()[2],
            subject={
                "loop_ref": LOOP_REF,
                "subject_kind": "GoalRef",
                "subject_ref": "host-target-0001",
            },
        )
        self.assert_rejected("WRONG_REFERENCE_KIND", lambda: store.apply(wrong_kind))

        store = self.store_after(2, authority)
        foreign = changed(
            vertical_commands()[2],
            subject={
                "loop_ref": LOOP_REF,
                "subject_kind": "GoalRef",
                "subject_ref": "goal-foreign-0001",
            },
        )
        self.assert_rejected("FOREIGN_REFERENCE", lambda: store.apply(foreign))

    def test_all_llm_control_field_injections_fail_closed(self):
        fields = (
            "handle",
            "receipt_ref",
            "actor_ref",
            "authority_grant_ref",
            "timestamp",
            "protocol_version",
            "expected_loop_revision",
            "command_type",
        )
        store = self.store_after(1)
        base = vertical_commands()[1]
        before = store.snapshot(LOOP_REF)
        for index, field in enumerate(fields):
            command = changed(
                base,
                operation_id=f"op-injection-{index:02d}",
                semantic_payload={field: "model-supplied-control"},
            )
            with self.subTest(field=field):
                self.assert_rejected(
                    "CONTROL_FIELD_INJECTION", lambda command=command: store.apply(command)
                )
                self.assertEqual(store.snapshot(LOOP_REF), before)

    def test_actor_and_grant_authority_failures(self):
        base = fixture_authority()
        command = vertical_commands()[1]
        system_grant = base.grants["grant-system-0001"]
        cases = []
        cases.append(
            (
                "forged-actor",
                base,
                changed(command, actor_ref="actor-forged-0001"),
                "INVALID_AUTHORITY",
            )
        )
        actors = dict(base.actors)
        actors["actor-system-0001"] = replace(
            actors["actor-system-0001"], issuer_trust="untrusted"
        )
        cases.append(
            (
                "untrusted-actor-issuer",
                changed_authority(base, actors=actors),
                command,
                "INVALID_AUTHORITY",
            )
        )
        replacements = (
            (
                "expired",
                replace_grant_digest(
                    replace(system_grant, expires_at="2026-07-26T23:59:59Z")
                ),
                "AUTHORITY_EXPIRED",
            ),
            (
                "not-yet-valid",
                replace_grant_digest(
                    replace(system_grant, not_before="2026-07-27T00:00:30Z")
                ),
                "AUTHORITY_EXPIRED",
            ),
            (
                "cross-loop",
                replace_grant_digest(
                    replace(system_grant, loop_scope="loop-foreign-0001")
                ),
                "AUTHORITY_SCOPE_MISMATCH",
            ),
            (
                "wrong-command",
                replace_grant_digest(
                    replace(system_grant, allowed_commands=("CloseExecution",))
                ),
                "AUTHORITY_SCOPE_MISMATCH",
            ),
            (
                "wrong-kind",
                replace_grant_digest(
                    replace(system_grant, subject_kinds=("FinalizationRef",))
                ),
                "AUTHORITY_SCOPE_MISMATCH",
            ),
            (
                "wrong-exact-subject",
                replace_grant_digest(
                    replace(system_grant, exact_subjects=("finalization-0001",))
                ),
                "AUTHORITY_SCOPE_MISMATCH",
            ),
            (
                "tampered-grant-digest",
                replace(system_grant, canonical_digest="tampered"),
                "INVALID_AUTHORITY",
            ),
        )
        for name, grant, code in replacements:
            grants = dict(base.grants)
            grants[grant.grant_ref] = grant
            cases.append((name, changed_authority(base, grants=grants), command, code))

        for name, authority, candidate, code in cases:
            with self.subTest(name=name):
                store = self.store_after(1, authority)
                before = store.snapshot(LOOP_REF)
                self.assert_rejected(code, lambda: store.apply(candidate))
                self.assertEqual(store.snapshot(LOOP_REF), before)

    def test_receipt_trust_freshness_and_identity_failures(self):
        base = fixture_authority()
        bind = base.receipts["receipt-bind-0001"]
        cases = (
            (
                "issuer-untrusted",
                "RECEIPT_ISSUER_UNTRUSTED",
                replace(bind, issuer_trust="untrusted"),
            ),
            (
                "expired",
                "RECEIPT_EXPIRED",
                replace(bind, expires_at="2026-07-27T00:00:00Z"),
            ),
            (
                "wrong-subject",
                "RECEIPT_IDENTITY_MISMATCH",
                replace(bind, subject_ref="host-target-foreign"),
            ),
            (
                "wrong-action",
                "RECEIPT_IDENTITY_MISMATCH",
                replace(bind, action="send"),
            ),
        )
        for name, code, receipt in cases:
            with self.subTest(name=name):
                receipts = dict(base.receipts)
                receipts[receipt.receipt_ref] = receipt
                authority = changed_authority(base, receipts=receipts)
                store = self.store_after(1, authority)
                self.assert_rejected(code, lambda: store.apply(vertical_commands()[1]))

        delivery = base.receipts["receipt-delivery-0001"]
        for name, receipt in (
            ("wrong-attempt", replace(delivery, attempt_ref="attempt-foreign")),
            ("wrong-request", replace(delivery, request_digest="wrong-digest")),
        ):
            with self.subTest(name=name):
                receipts = dict(base.receipts)
                receipts[receipt.receipt_ref] = receipt
                authority = changed_authority(base, receipts=receipts)
                store = self.store_after(4, authority)
                self.assert_rejected(
                    "RECEIPT_IDENTITY_MISMATCH",
                    lambda: store.apply(vertical_commands()[4]),
                )

    def test_all_33_declared_transaction_fault_boundaries(self):
        commands = vertical_commands()
        for index, command in enumerate(commands):
            for boundary in FAULT_BOUNDARIES:
                with self.subTest(operation=command.operation_id, boundary=boundary):
                    store = self.store_after(index)
                    clean = self.store_after(index)
                    expected_result = clean.apply(command)
                    expected_post = (
                        clean.snapshot(LOOP_REF),
                        clean.events(LOOP_REF),
                        clean.commit_count,
                    )
                    exact_pre = (
                        store.snapshot(LOOP_REF),
                        store.events(LOOP_REF),
                        store.commit_count,
                    )
                    with self.assertRaises(InjectedCrash):
                        store.apply(command, fault_at=boundary)
                    actual = (
                        store.snapshot(LOOP_REF),
                        store.events(LOOP_REF),
                        store.commit_count,
                    )
                    if boundary == "after_commit_before_response":
                        self.assertEqual(actual, expected_post)
                        replay = store.apply(command)
                        self.assertTrue(replay.replayed)
                        self.assertEqual(replay.snapshot_digest, expected_result.snapshot_digest)
                        self.assertEqual(
                            (
                                store.snapshot(LOOP_REF),
                                store.events(LOOP_REF),
                                store.commit_count,
                            ),
                            expected_post,
                        )
                    else:
                        self.assertEqual(actual, exact_pre)
                        recovered = store.apply(command)
                        self.assertEqual(
                            recovered.snapshot_digest, expected_result.snapshot_digest
                        )
                        self.assertEqual(
                            (
                                store.snapshot(LOOP_REF),
                                store.events(LOOP_REF),
                                store.commit_count,
                            ),
                            expected_post,
                        )

    def test_attempt_commit_consumes_budget_and_forbids_resend(self):
        command = vertical_commands()[3]
        store = self.store_after(3)
        pre = store.snapshot(LOOP_REF)
        with self.assertRaises(InjectedCrash):
            store.apply(command, fault_at="after_reduce_before_commit")
        self.assertEqual(store.snapshot(LOOP_REF), pre)
        self.assertNotIn("attempt-0001", store.snapshot(LOOP_REF)["attempts"])

        with self.assertRaises(InjectedCrash):
            store.apply(command, fault_at="after_commit_before_response")
        committed = store.snapshot(LOOP_REF)
        self.assertTrue(
            committed["attempts"]["attempt-0001"]["automatic_budget_consumed"]
        )
        self.assertEqual(
            committed["deliveries"]["delivery-0001"]["automatic_attempts_consumed"],
            1,
        )
        self.assertTrue(store.apply(command).replayed)

        resend = changed(
            command,
            operation_id="op-resend-0001",
            expected_loop_revision=4,
            expected_subject_revisions={
                "delivery-0001": 2,
                "host-target-0001": 1,
                "route-0001": 1,
            },
        )
        self.assert_rejected("ATTEMPT_ALREADY_CONSUMED", lambda: store.apply(resend))
        self.assertEqual(store.snapshot(LOOP_REF), committed)

    def test_unknown_and_unverifiable_allow_exact_late_observation_only(self):
        base = fixture_authority()
        original = base.receipts["receipt-delivery-0001"]
        for initial_state, initial_receipt in (
            ("UNKNOWN", replace(original, outcome="unknown")),
            (
                "UNVERIFIABLE",
                replace(original, trust_class="cooperative", outcome="responded"),
            ),
        ):
            with self.subTest(initial_state=initial_state):
                late = replace(
                    original,
                    receipt_ref=f"receipt-late-{initial_state.lower()}",
                    issued_at="2026-07-27T00:00:05Z",
                )
                receipts = dict(base.receipts)
                receipts[initial_receipt.receipt_ref] = initial_receipt
                receipts[late.receipt_ref] = late
                authority = changed_authority(base, receipts=receipts)
                store = self.store_after(4, authority)
                store.apply(vertical_commands()[4])
                self.assertEqual(
                    store.snapshot(LOOP_REF)["attempts"]["attempt-0001"]["state"],
                    initial_state,
                )
                late_command = changed(
                    vertical_commands()[4],
                    operation_id=f"op-late-{initial_state.lower()}",
                    expected_loop_revision=5,
                    expected_subject_revisions={
                        "attempt-0001": 2,
                        "delivery-0001": 3,
                    },
                    issued_at="2026-07-27T00:00:05Z",
                    machine_bindings={
                        "resolved_refs": {},
                        "allocate_refs": {},
                        "receipt_refs": {"receipt": late.receipt_ref},
                    },
                )
                result = store.apply(late_command)
                self.assertEqual(result.event_types, ("LateDeliveryObserved",))
                self.assertEqual(
                    store.snapshot(LOOP_REF)["attempts"]["attempt-0001"]["state"],
                    "OBSERVED",
                )

    def test_cooperative_fixture_terminates_with_limitation_not_strict_claim(self):
        base = fixture_authority()
        receipts = dict(base.receipts)
        receipts["receipt-delivery-0001"] = replace(
            receipts["receipt-delivery-0001"],
            trust_class="cooperative",
            outcome="responded",
        )
        receipts["receipt-finalize-0001"] = replace(
            receipts["receipt-finalize-0001"], trust_class="cooperative"
        )
        store = InMemoryStore(changed_authority(base, receipts=receipts))
        commands = list(vertical_commands())
        commands[9] = changed(
            commands[9], semantic_payload={"disposition": "LIMITATION"}
        )
        for command in commands:
            result = store.apply(command)
        snapshot = store.snapshot(LOOP_REF)
        self.assertEqual(snapshot["execution"]["state"], "TERMINAL")
        self.assertEqual(snapshot["execution"]["disposition"], "LIMITATION")
        self.assertEqual(snapshot["closure_assurance"]["strength"], "COOPERATIVE")
        self.assertNotIn("StrictFinalizationAcknowledged", result.event_types)
        self.assertNotIn(
            "StrictFinalizationAcknowledged",
            tuple(event["type"] for event in store.events(LOOP_REF)),
        )

    def test_finalization_receipt_binds_exact_subject_chain_digest(self):
        base = fixture_authority()
        receipts = dict(base.receipts)
        receipts["receipt-finalize-0001"] = replace(
            receipts["receipt-finalize-0001"], request_digest="foreign-chain"
        )
        authority = changed_authority(base, receipts=receipts)
        store = self.store_after(10, authority)
        self.assert_rejected(
            "RECEIPT_IDENTITY_MISMATCH",
            lambda: store.apply(vertical_commands()[10]),
        )

    def test_v4_alpha_has_no_forbidden_runtime_dependencies(self):
        package = SCRIPTS / "loop_architect" / "v4_alpha"
        forbidden = {
            "codex",
            "git",
            "http",
            "os",
            "pathlib",
            "requests",
            "socket",
            "sqlite3",
            "subprocess",
            "urllib",
        }
        violations = []
        for source in sorted(package.glob("*.py")):
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            for node in ast.walk(tree):
                imported = []
                if isinstance(node, ast.Import):
                    imported = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported = [node.module]
                for name in imported:
                    root = name.split(".", 1)[0]
                    if root in forbidden:
                        violations.append(f"{source.name}:{node.lineno}:{name}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
