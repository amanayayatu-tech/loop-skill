from __future__ import annotations

import ast
import sqlite3
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "codex-loop-prompt-architect" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from loop_architect.v4_adapters.codex import (  # noqa: E402
    CodexHostAdapter,
    HostResponseLost,
)
from loop_architect.v4_adapters.codex.adapter import (  # noqa: E402
    HOST_ACTIONS,
    HOST_SCHEMA_VERSION,
)
from loop_architect.v4_alpha.kernel import AuthorityContext  # noqa: E402
from loop_architect.v4_alpha.protocol import (  # noqa: E402
    CAPABILITY_NAMES,
    EffectAttempt,
    ProtocolRejection,
    domain_digest,
    with_command_change,
)
from loop_architect.v4_alpha.vertical import (  # noqa: E402
    LOOP_REF,
    fixture_authority,
    vertical_commands,
)
from loop_architect.v4_persistence.sqlite_store import SQLiteStore  # noqa: E402


NOW = datetime(2026, 7, 27, 0, 0, 4, tzinfo=timezone.utc)
ISSUER_REF = "codex-adapter-issuer-0001"
ISSUER_TRUST = "trusted-adapter"


def request_payload(target_ref="host-target-0001"):
    return {
        "intent_digest": (
            "4f8294df9f9485909e7d478819bcfb0aae91c3685864946c1bdea3c0451148b3"
        ),
        "target_ref": target_ref,
    }


def effect_attempt(
    *,
    action="send",
    attempt_ref="attempt-0001",
    delivery_ref="delivery-0001",
    target_ref="host-target-0001",
    provider_key="effect-0001",
):
    payload = request_payload(target_ref)
    return EffectAttempt(
        attempt_ref=attempt_ref,
        loop_ref=LOOP_REF,
        delivery_ref=delivery_ref,
        target_ref=target_ref,
        provider_idempotency_key=provider_key,
        provider_request_digest=domain_digest(
            "loopskill-provider-request-v1\n", payload
        ),
        action=action,
        payload=payload,
    )


class ClaimFixture:
    def __init__(self, *attempts):
        self.rows = {
            item.attempt_ref: {
                "attempt_ref": item.attempt_ref,
                "attempt_state": "COMMITTED",
                "delivery_ref": item.delivery_ref,
                "executor_ref": None,
                "invocation_state": "READY",
                "loop_ref": item.loop_ref,
                "provider_idempotency_key": item.provider_idempotency_key,
                "provider_request_digest": item.provider_request_digest,
                "target_ref": item.target_ref,
            }
            for item in attempts
        }

    def claim_attempt(self, attempt_ref, executor_ref):
        row = self.rows[attempt_ref]
        if row["attempt_state"] != "COMMITTED" or row["invocation_state"] != "READY":
            return False
        row["invocation_state"] = "STARTED"
        row["executor_ref"] = executor_ref
        return True

    def outbox_attempt(self, attempt_ref):
        row = self.rows.get(attempt_ref)
        return None if row is None else dict(row)


class CodexProviderFixture:
    def __init__(
        self,
        *,
        invoke_mode="response",
        readback_mode="authoritative",
        readback_delay=0,
        capability_overrides=None,
        resource_state="ACTIVE",
        resource_trust="authoritative",
    ):
        self.invoke_mode = invoke_mode
        self.readback_mode = readback_mode
        self.readback_delay = readback_delay
        self.capability_overrides = capability_overrides or {}
        self.resource_state = resource_state
        self.resource_trust = resource_trust
        self.invoke_counts = {}
        self.records = {}
        self.observation_mutation = None

    def capability_snapshot(self):
        rows = []
        for name in CAPABILITY_NAMES:
            availability, assurance = self.capability_overrides.get(
                name, ("AVAILABLE", "STRICT")
            )
            rows.append(
                {
                    "assurance": assurance,
                    "availability": availability,
                    "details": {
                        "expires_at": "2026-07-27T00:01:00Z",
                        "identity_ref": (
                            f"codex-capability-{name}"
                            if availability == "AVAILABLE"
                            else None
                        ),
                        "issuer_ref": ISSUER_REF,
                        "issuer_trust": ISSUER_TRUST,
                        "observed_at": "2026-07-27T00:00:00Z",
                        "source": "synthetic-codex-contract",
                    },
                    "name": name,
                    "receipt_ref": f"capability-receipt-{name}",
                }
            )
        return {"capabilities": rows, "schema_version": HOST_SCHEMA_VERSION}

    def invoke(self, action, payload, provider_idempotency_key):
        self.invoke_counts[provider_idempotency_key] = (
            self.invoke_counts.get(provider_idempotency_key, 0) + 1
        )
        response = {
            "action": action,
            "idempotency_key": provider_idempotency_key,
            "provider_id": f"codex-{action}-0001",
            "schema_version": HOST_SCHEMA_VERSION,
            "status": "ACCEPTED",
            "subject_id": payload["target_ref"],
            "trust": "cooperative",
        }
        self.records[provider_idempotency_key] = {
            **response,
            "status": "OBSERVED",
            "trust": "authoritative",
        }
        if self.invoke_mode == "response_lost":
            raise HostResponseLost("synthetic response loss")
        return self._mutate(response)

    def readback(self, action, provider_idempotency_key):
        if self.readback_delay:
            self.readback_delay -= 1
            return None
        if self.readback_mode == "missing":
            return None
        if self.readback_mode == "cooperative":
            return self._mutate(
                {
                    **self.records[provider_idempotency_key],
                    "trust": "cooperative",
                }
            )
        return self._mutate(self.records.get(provider_idempotency_key))

    def read_resource(self, resource_kind, provider_id):
        return {
            "provider_id": provider_id,
            "resource_kind": resource_kind,
            "schema_version": HOST_SCHEMA_VERSION,
            "state": self.resource_state,
            "trust": self.resource_trust,
        }

    def _mutate(self, response):
        if response is None or self.observation_mutation is None:
            return response
        changed = dict(response)
        self.observation_mutation(changed)
        return changed


def adapter(provider, claims, **changes):
    values = {
        "executor_ref": "executor-codex-0001",
        "issuer_ref": ISSUER_REF,
        "issuer_trust": ISSUER_TRUST,
        "clock": lambda: NOW,
        "max_readback_observations": 3,
    }
    values.update(changes)
    return CodexHostAdapter(provider, claims, **values)


def authority_with_receipt(receipt, *, trusted=True):
    base = fixture_authority()
    trusted_issuers = dict(base.trusted_receipt_issuers)
    if trusted:
        trusted_issuers[receipt.issuer_ref] = receipt.issuer_trust
    return AuthorityContext(
        actors=base.actors,
        grants=base.grants,
        receipts={**base.receipts, receipt.receipt_ref: receipt},
        trusted_receipt_issuers=trusted_issuers,
    )


def observation_command(receipt_ref, *, operation_id="operation-0005"):
    command = vertical_commands()[4]

    def update(values):
        values["operation_id"] = operation_id
        values["machine_bindings"] = {
            **values["machine_bindings"],
            "receipt_refs": {"receipt": receipt_ref},
        }

    return with_command_change(command, update)


class V4CodexAdapterTests(unittest.TestCase):
    def assert_code(self, code, callable_):
        with self.assertRaises(ProtocolRejection) as caught:
            callable_()
        self.assertEqual(caught.exception.code, code)

    def test_capability_profiles_assurance_memory_and_guarantee_vocabulary(self):
        attempt = effect_attempt()
        strict = adapter(CodexProviderFixture(), ClaimFixture(attempt))
        self.assertEqual(len(strict.capabilities()), len(CAPABILITY_NAMES))
        self.assertEqual(strict.assurance_tier(), "STRICT")
        self.assertEqual(strict.guarantee_vocabulary(), "effectively-once")

        for availability in ("UNAVAILABLE", "UNVERIFIABLE"):
            with self.subTest(memory=availability):
                provider = CodexProviderFixture(
                    capability_overrides={"memory": (availability, "NONE")}
                )
                records = {row.capability: row for row in adapter(provider, ClaimFixture(attempt)).capabilities()}
                self.assertEqual(records["memory"].availability, availability)

        cooperative = CodexProviderFixture(
            capability_overrides={"lifecycle_readback": ("UNVERIFIABLE", "NONE")}
        )
        profile = adapter(cooperative, ClaimFixture(attempt))
        self.assertEqual(profile.assurance_tier(), "COOPERATIVE")
        self.assertEqual(
            profile.guarantee_vocabulary(),
            "at-most-one automatic attempt; outcome may be UNKNOWN",
        )
        visibility = CodexProviderFixture(
            capability_overrides={
                "memory": ("UNAVAILABLE", "NONE"),
                "model_receipt": ("UNVERIFIABLE", "NONE"),
                "sandbox_receipt": ("UNVERIFIABLE", "NONE"),
                "trust_receipt": ("UNVERIFIABLE", "NONE"),
            }
        )
        records = {
            row.capability: row
            for row in adapter(visibility, ClaimFixture(attempt)).capabilities()
        }
        self.assertEqual(records["memory"].availability, "UNAVAILABLE")
        for name in ("model_receipt", "sandbox_receipt", "trust_receipt"):
            self.assertEqual(records[name].availability, "UNVERIFIABLE")

    def test_all_host_mutations_and_resources_are_closed_and_single_invoke(self):
        attempts = tuple(
            effect_attempt(
                action=action,
                attempt_ref=f"attempt-{index:04d}",
                delivery_ref=f"delivery-{index:04d}",
                target_ref=f"host-target-{index:04d}",
                provider_key=f"effect-{index:04d}",
            )
            for index, action in enumerate(sorted(HOST_ACTIONS), 1)
        )
        claims = ClaimFixture(*attempts)
        provider = CodexProviderFixture(readback_delay=1)
        host = adapter(provider, claims)
        for item in attempts:
            receipt = host.execute(item)
            self.assertEqual(receipt.trust_class, "strict")
            self.assertEqual(receipt.outcome, "observed")
            self.assertEqual(provider.invoke_counts[item.provider_idempotency_key], 1)
            replay = host.execute(item)
            self.assertEqual(replay.receipt_ref, receipt.receipt_ref)
            self.assertEqual(provider.invoke_counts[item.provider_idempotency_key], 1)

        for kind in ("project", "task", "thread", "message", "lifecycle"):
            resource = host.read_resource(kind, f"codex-{kind}-0001")
            self.assertEqual(resource["state"], "ACTIVE")

    def test_final_lifecycle_readback_binds_chain_and_assurance(self):
        chain_digest = "f" * 64
        strict = adapter(
            CodexProviderFixture(resource_state="TERMINAL"),
            ClaimFixture(effect_attempt()),
        ).observe_finalization(
            loop_ref=LOOP_REF,
            finalization_ref="finalization-0001",
            provider_id="codex-thread-0001",
            subject_chain_digest=chain_digest,
        )
        self.assertEqual((strict.outcome, strict.trust_class), ("acknowledged", "strict"))
        self.assertEqual(strict.request_digest, chain_digest)

        limited = adapter(
            CodexProviderFixture(
                resource_state="TERMINAL",
                resource_trust="cooperative",
            ),
            ClaimFixture(effect_attempt()),
        ).observe_finalization(
            loop_ref=LOOP_REF,
            finalization_ref="finalization-0001",
            provider_id="codex-thread-0001",
            subject_chain_digest=chain_digest,
        )
        self.assertEqual((limited.outcome, limited.trust_class), ("acknowledged", "cooperative"))

        pending = adapter(
            CodexProviderFixture(resource_state="ACTIVE"),
            ClaimFixture(effect_attempt()),
        ).observe_finalization(
            loop_ref=LOOP_REF,
            finalization_ref="finalization-0001",
            provider_id="codex-thread-0001",
            subject_chain_digest=chain_digest,
        )
        self.assertEqual((pending.outcome, pending.trust_class), ("unknown", "cooperative"))

    def test_response_lost_then_authoritative_readback_and_eventual_indexing(self):
        attempt = effect_attempt()
        provider = CodexProviderFixture(
            invoke_mode="response_lost", readback_delay=2
        )
        host = adapter(provider, ClaimFixture(attempt))
        receipt = host.execute(attempt)
        self.assertEqual(receipt.outcome, "observed")
        self.assertEqual(receipt.trust_class, "strict")
        self.assertEqual(provider.invoke_counts["effect-0001"], 1)
        self.assertEqual(host.execute(attempt).receipt_ref, receipt.receipt_ref)
        self.assertEqual(provider.invoke_counts["effect-0001"], 1)

    def test_missing_readback_is_unknown_and_never_resends(self):
        attempt = effect_attempt()
        claims = ClaimFixture(attempt)
        provider = CodexProviderFixture(
            invoke_mode="response_lost", readback_mode="missing"
        )
        host = adapter(provider, claims)
        receipt = host.execute(attempt)
        self.assertEqual((receipt.outcome, receipt.trust_class), ("unknown", "cooperative"))
        self.assertEqual(host.execute(attempt).outcome, "unknown")
        self.assertEqual(provider.invoke_counts["effect-0001"], 1)

        preclaimed = effect_attempt(attempt_ref="attempt-0002", provider_key="effect-0002")
        preclaims = ClaimFixture(preclaimed)
        self.assertTrue(preclaims.claim_attempt(preclaimed.attempt_ref, "dead-executor"))
        never_called = CodexProviderFixture(readback_mode="missing")
        receipt = adapter(never_called, preclaims).execute(preclaimed)
        self.assertEqual(receipt.outcome, "unknown")
        self.assertEqual(never_called.invoke_counts, {})

    def test_cooperative_response_is_unverifiable_not_strict(self):
        attempt = effect_attempt()
        provider = CodexProviderFixture(readback_mode="missing")
        receipt = adapter(provider, ClaimFixture(attempt)).execute(attempt)
        self.assertEqual((receipt.outcome, receipt.trust_class), ("responded", "cooperative"))
        self.assertNotEqual(receipt.trust_class, "strict")

        unavailable = CodexProviderFixture(
            capability_overrides={"message_send": ("UNAVAILABLE", "NONE")}
        )
        claims = ClaimFixture(attempt)
        receipt = adapter(unavailable, claims).execute(attempt)
        self.assertEqual((receipt.outcome, receipt.trust_class), ("unknown", "cooperative"))
        self.assertEqual(unavailable.invoke_counts, {})
        self.assertEqual(claims.rows[attempt.attempt_ref]["invocation_state"], "READY")

    def test_schema_enum_identity_and_capability_drift_fail_closed(self):
        attempt = effect_attempt()
        provider = CodexProviderFixture()
        snapshot = provider.capability_snapshot()
        snapshot["capabilities"].pop()
        provider.capability_snapshot = lambda: snapshot
        self.assert_code(
            "ADAPTER_SCHEMA_DRIFT",
            lambda: adapter(provider, ClaimFixture(attempt)).capabilities(),
        )

        provider = CodexProviderFixture()
        snapshot = provider.capability_snapshot()
        snapshot["capabilities"][0]["availability"] = "NEW_HOST_ENUM"
        provider.capability_snapshot = lambda: snapshot
        self.assert_code(
            "ADAPTER_SCHEMA_DRIFT",
            lambda: adapter(provider, ClaimFixture(attempt)).capabilities(),
        )

        for detail, value, expected in (
            ("identity_ref", None, "RECEIPT_IDENTITY_MISMATCH"),
            ("issuer_trust", "foreign-trust", "RECEIPT_ISSUER_UNTRUSTED"),
            ("expires_at", "2026-07-27T00:00:03Z", "RECEIPT_EXPIRED"),
        ):
            with self.subTest(capability_receipt=detail):
                provider = CodexProviderFixture()
                snapshot = provider.capability_snapshot()
                row = next(
                    item
                    for item in snapshot["capabilities"]
                    if item["name"] == "model_receipt"
                )
                row["details"][detail] = value
                provider.capability_snapshot = lambda snapshot=snapshot: snapshot
                self.assert_code(
                    expected,
                    lambda provider=provider: adapter(
                        provider, ClaimFixture(attempt)
                    ).capabilities(),
                )

        for mutation, expected in (
            (lambda row: row.update(status="NEW_HOST_ENUM"), "ADAPTER_SCHEMA_DRIFT"),
            (lambda row: row.pop("subject_id"), "ADAPTER_SCHEMA_DRIFT"),
            (
                lambda row: row.update(idempotency_key="foreign-effect"),
                "RECEIPT_IDENTITY_MISMATCH",
            ),
            (lambda row: row.update(provider_id=None), "ADAPTER_SCHEMA_DRIFT"),
        ):
            with self.subTest(mutation=mutation):
                provider = CodexProviderFixture()
                provider.observation_mutation = mutation
                self.assert_code(
                    expected,
                    lambda provider=provider: adapter(
                        provider, ClaimFixture(attempt)
                    ).execute(attempt),
                )

        foreign = replace(attempt, target_ref="host-target-foreign")
        self.assert_code(
            "RECEIPT_IDENTITY_MISMATCH",
            lambda: adapter(CodexProviderFixture(), ClaimFixture(attempt)).execute(foreign),
        )

    def test_sqlite_claim_observation_unknown_late_readback_and_receipt_authority(self):
        commands = vertical_commands()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "adapter.sqlite3"
            base = fixture_authority()
            with SQLiteStore(path, base) as store:
                for command in commands[:4]:
                    store.apply(command)
                attempt = effect_attempt()
                provider = CodexProviderFixture(
                    invoke_mode="response_lost", readback_mode="missing"
                )
                host = adapter(provider, store)
                unknown = host.execute(attempt)

                store.authority = authority_with_receipt(unknown)
                store.apply(observation_command(unknown.receipt_ref))
                self.assertEqual(store.snapshot(LOOP_REF)["attempts"]["attempt-0001"]["state"], "UNKNOWN")
                self.assertEqual(store.outbox_attempt("attempt-0001")["invocation_state"], "UNKNOWN")
                self.assertEqual(provider.invoke_counts["effect-0001"], 1)

                provider.readback_mode = "authoritative"
                observed = host.execute(attempt)
                late_authority = authority_with_receipt(observed)
                store.authority = late_authority
                late = observation_command(observed.receipt_ref, operation_id="operation-late-0001")

                def update(values):
                    values["expected_loop_revision"] = 5
                    values["expected_subject_revisions"] = {
                        "attempt-0001": 2,
                        "delivery-0001": 3,
                    }

                late = with_command_change(late, update)
                result = store.apply(late)
                self.assertEqual(result.event_types, ("LateDeliveryObserved",))
                self.assertEqual(store.snapshot(LOOP_REF)["attempts"]["attempt-0001"]["state"], "OBSERVED")
                self.assertEqual(store.outbox_attempt("attempt-0001")["invocation_state"], "OBSERVED")
                self.assertEqual(provider.invoke_counts["effect-0001"], 1)
                store.verify_integrity()

    def test_receipt_issuer_trust_and_freshness_are_kernel_authority(self):
        attempt = effect_attempt()
        receipt = adapter(CodexProviderFixture(), ClaimFixture(attempt)).execute(attempt)
        command = observation_command(receipt.receipt_ref)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "authority.sqlite3"
            with SQLiteStore(path, fixture_authority()) as store:
                for prefix in vertical_commands()[:4]:
                    store.apply(prefix)
                store.authority = authority_with_receipt(receipt, trusted=False)
                self.assert_code(
                    "RECEIPT_ISSUER_UNTRUSTED", lambda: store.apply(command)
                )

        expired = replace(receipt, expires_at="2026-07-27T00:00:03Z")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "freshness.sqlite3"
            with SQLiteStore(path, fixture_authority()) as store:
                for prefix in vertical_commands()[:4]:
                    store.apply(prefix)
                store.authority = authority_with_receipt(expired)
                self.assert_code("RECEIPT_EXPIRED", lambda: store.apply(command))

    def test_store_v1_schema_migrates_transactionally_to_claim_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "v1.sqlite3"
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;
                INSERT INTO metadata VALUES ('schema_version', '1');
                CREATE TABLE outbox (
                    attempt_ref TEXT PRIMARY KEY,
                    loop_ref TEXT NOT NULL,
                    delivery_ref TEXT NOT NULL,
                    provider_idempotency_key TEXT NOT NULL UNIQUE,
                    provider_request_digest TEXT NOT NULL,
                    automatic_budget_consumed INTEGER NOT NULL,
                    attempt_revision INTEGER NOT NULL,
                    attempt_state TEXT NOT NULL
                ) STRICT;
                """
            )
            connection.close()
            path.chmod(0o600)
            with SQLiteStore(path, fixture_authority()) as store:
                columns = {
                    row[1] for row in store._connection.execute("PRAGMA table_info(outbox)")
                }
                self.assertTrue(
                    {"target_ref", "invocation_state", "executor_ref", "observation_receipt_ref"}
                    <= columns
                )
                self.assertEqual(
                    store._connection.execute(
                        "SELECT value FROM metadata WHERE key = 'schema_version'"
                    ).fetchone()[0],
                    "2",
                )

    def test_adapter_and_kernel_import_graph_are_one_way(self):
        package = SCRIPTS / "loop_architect"
        forbidden_core = {
            "loop_architect.v4_adapters",
            "loop_architect.v4_persistence",
            "codex",
            "git",
            "subprocess",
        }
        for path in (package / "v4_alpha").glob("*.py"):
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
                    for denied in forbidden_core
                ),
                path,
            )

        adapter_path = package / "v4_adapters" / "codex" / "adapter.py"
        tree = ast.parse(
            adapter_path.read_text(encoding="utf-8"), filename=str(adapter_path)
        )
        imports = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        self.assertNotIn("loop_architect.v4_alpha.kernel", imports)
        self.assertNotIn("loop_architect.v4_alpha.store", imports)
        self.assertNotIn("loop_architect.v4_persistence.sqlite_store", imports)


if __name__ == "__main__":
    unittest.main()
