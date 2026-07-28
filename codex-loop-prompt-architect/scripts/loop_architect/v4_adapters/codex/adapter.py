"""Codex-specific Host behavior isolated behind generated protocol records."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from loop_architect.v4_alpha.protocol import (
    CAPABILITY_NAMES,
    CapabilityRecord,
    EffectAttempt,
    ProtocolRejection,
    Receipt,
    domain_digest,
    result_payload_schema,
    validate_result_payload,
    validate_capability_record,
)

from .contract import AttemptClaimPort, CodexProviderPort


HOST_SCHEMA_VERSION = "codex-host-v1"
HOST_ACTIONS = frozenset(
    {
        "register_project",
        "create_task",
        "create_thread",
        "send",
        "heartbeat",
    }
)
HOST_RESOURCE_KINDS = frozenset({"project", "task", "thread", "message", "lifecycle"})
HOST_STATUSES = frozenset({"ACCEPTED", "OBSERVED", "PENDING", "NOT_FOUND"})
ACTION_CAPABILITIES = {
    "register_project": "project_registration",
    "create_task": "task_create",
    "create_thread": "thread_create",
    "send": "message_send",
    "heartbeat": "heartbeat",
}
REQUIRED_STRICT_CAPABILITIES = frozenset(
    {
        "project_registration",
        "task_create",
        "thread_create",
        "resource_read",
        "message_send",
        "lifecycle_readback",
        "trust_receipt",
    }
)


class HostResponseLost(RuntimeError):
    """Provider accepted or may have accepted, but its response was lost."""


class HostUnavailable(RuntimeError):
    """Provider invocation/readback is temporarily unavailable."""


def _machine_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _host_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Host time is not a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Host time lacks timezone")
    return parsed.astimezone(timezone.utc)


class CodexHostAdapter:
    """Translate Codex Host receipts without leaking Host enums into Core."""

    def __init__(
        self,
        provider: CodexProviderPort,
        claims: AttemptClaimPort,
        *,
        executor_ref: str,
        issuer_ref: str,
        issuer_trust: str,
        clock: Callable[[], datetime] = _machine_now,
        max_readback_observations: int = 3,
    ) -> None:
        if max_readback_observations < 1 or max_readback_observations > 16:
            raise ValueError("readback observation bound must be 1..16")
        if not executor_ref or not issuer_ref or not issuer_trust:
            raise ValueError("executor and receipt issuer identity must be machine-bound")
        self.provider = provider
        self.claims = claims
        self.executor_ref = executor_ref
        self.issuer_ref = issuer_ref
        self.issuer_trust = issuer_trust
        self.clock = clock
        self.max_readback_observations = max_readback_observations

    def capabilities(self) -> tuple[CapabilityRecord, ...]:
        raw = self.provider.capability_snapshot()
        if not isinstance(raw, Mapping) or set(raw) != {
            "capabilities",
            "schema_version",
        }:
            self._schema_drift("capability snapshot fields")
        if raw["schema_version"] != HOST_SCHEMA_VERSION:
            self._schema_drift("capability schema version")
        rows = raw["capabilities"]
        if not isinstance(rows, list):
            self._schema_drift("capabilities must be array")
        records = []
        seen = set()
        for row in rows:
            if not isinstance(row, Mapping) or set(row) != {
                "assurance",
                "availability",
                "details",
                "name",
                "receipt_ref",
            }:
                self._schema_drift("capability record fields")
            name = row["name"]
            if name in seen or name not in CAPABILITY_NAMES:
                self._schema_drift("capability name")
            if not isinstance(row["details"], Mapping):
                self._schema_drift("capability details")
            details = row["details"]
            if set(details) != {
                "expires_at",
                "identity_ref",
                "issuer_ref",
                "issuer_trust",
                "observed_at",
                "source",
            }:
                self._schema_drift("capability receipt fields")
            if not isinstance(row["receipt_ref"], str) or not row["receipt_ref"]:
                self._schema_drift("capability receipt identity")
            if (
                details["issuer_ref"] != self.issuer_ref
                or details["issuer_trust"] != self.issuer_trust
            ):
                raise ProtocolRejection(
                    "RECEIPT_ISSUER_UNTRUSTED", "capability receipt issuer"
                )
            try:
                observed_at = _host_time(details["observed_at"])
                expires_at = _host_time(details["expires_at"])
            except (TypeError, ValueError):
                self._schema_drift("capability receipt time")
            now = self.clock().astimezone(timezone.utc)
            if now < observed_at or now > expires_at:
                raise ProtocolRejection(
                    "RECEIPT_EXPIRED", "capability receipt freshness"
                )
            if row["availability"] == "AVAILABLE" and not details["identity_ref"]:
                raise ProtocolRejection(
                    "RECEIPT_IDENTITY_MISMATCH", "available capability identity"
                )
            seen.add(name)
            record = CapabilityRecord(
                capability=name,
                availability=row["availability"],
                assurance=row["assurance"],
                issuer_ref=self.issuer_ref,
                receipt_ref=row["receipt_ref"],
                details=dict(row["details"]),
            )
            try:
                validate_capability_record(record)
            except ProtocolRejection:
                self._schema_drift("capability enum")
            records.append(record)
        if seen != set(CAPABILITY_NAMES):
            self._schema_drift("capability set is incomplete")
        return tuple(sorted(records, key=lambda item: item.capability))

    def assurance_tier(self) -> str:
        records = {record.capability: record for record in self.capabilities()}
        strict = all(
            name in records
            and records[name].availability == "AVAILABLE"
            and records[name].assurance == "STRICT"
            for name in REQUIRED_STRICT_CAPABILITIES
        )
        return "STRICT" if strict else "COOPERATIVE"

    def guarantee_vocabulary(self) -> str:
        """Return the strongest allowed delivery wording for this profile."""
        records = {record.capability: record for record in self.capabilities()}
        prerequisites = ("provider_idempotency", "lifecycle_readback")
        if all(
            records[name].availability == "AVAILABLE"
            and records[name].assurance == "STRICT"
            for name in prerequisites
        ):
            return "effectively-once"
        return "at-most-one automatic attempt; outcome may be UNKNOWN"

    def execute(self, attempt: EffectAttempt) -> Receipt:
        self._validate_attempt(attempt)
        capabilities = {
            record.capability: record for record in self.capabilities()
        }
        row = self.claims.outbox_attempt(attempt.attempt_ref)
        if row is None:
            raise ProtocolRejection("FOREIGN_REFERENCE", attempt.attempt_ref)
        expected = {
            "delivery_ref": attempt.delivery_ref or "",
            "loop_ref": attempt.loop_ref,
            "provider_idempotency_key": attempt.provider_idempotency_key,
            "provider_request_digest": attempt.provider_request_digest,
            "subject_kind": attempt.subject_kind,
            "subject_ref": attempt.subject_ref,
            "target_ref": attempt.target_ref,
        }
        if any(row.get(key) != value for key, value in expected.items()):
            raise ProtocolRejection(
                "RECEIPT_IDENTITY_MISMATCH", "Attempt/outbox identity mismatch"
            )
        action_capability = capabilities[ACTION_CAPABILITIES[attempt.action]]
        if action_capability.availability != "AVAILABLE":
            return self._receipt(
                attempt,
                {
                    "action": attempt.action,
                    "idempotency_key": attempt.provider_idempotency_key,
                    "provider_id": None,
                    "schema_version": HOST_SCHEMA_VERSION,
                    "status": "NOT_FOUND",
                    "subject_id": None,
                    "trust": "none",
                },
                capabilities=capabilities,
                trust_class="cooperative",
                outcome="unknown",
            )
        acquired = self.claims.claim_attempt(attempt.attempt_ref, self.executor_ref)
        response = None
        response_lost = False
        if acquired:
            try:
                response = self.provider.invoke(
                    attempt.action,
                    attempt.payload,
                    attempt.provider_idempotency_key,
                )
                self._validate_observation(response, attempt)
            except HostResponseLost:
                response_lost = True
            except HostUnavailable:
                response_lost = True

        observed = self._bounded_readback(attempt)
        if observed is not None:
            authoritative = (
                observed["trust"] == "authoritative"
                and self._strict_observation_allowed(attempt.action, capabilities)
            )
            return self._receipt(
                attempt,
                observed,
                capabilities=capabilities,
                trust_class="strict" if authoritative else "cooperative",
                outcome="observed" if authoritative else "responded",
            )
        if response is not None and not response_lost:
            return self._receipt(
                attempt,
                response,
                capabilities=capabilities,
                trust_class="cooperative",
                outcome="responded",
            )
        return self._receipt(
            attempt,
            {
                "action": attempt.action,
                "idempotency_key": attempt.provider_idempotency_key,
                "provider_id": None,
                "schema_version": HOST_SCHEMA_VERSION,
                "status": "NOT_FOUND",
                "subject_id": None,
                "trust": "none",
            },
            capabilities=capabilities,
            trust_class="cooperative",
            outcome="unknown",
        )

    def read_resource(self, resource_kind: str, provider_id: str) -> Mapping[str, Any]:
        if resource_kind not in HOST_RESOURCE_KINDS or not provider_id:
            raise ProtocolRejection("INVALID_COMMAND", "invalid Host resource read")
        response = self.provider.read_resource(resource_kind, provider_id)
        self._validate_resource(response, resource_kind, provider_id)
        return dict(response)

    def read_task_result(self, provider_id: str) -> Mapping[str, Any]:
        if not provider_id:
            raise ProtocolRejection("INVALID_COMMAND", "missing Host task identity")
        response = self.provider.read_task_result(provider_id)
        if not isinstance(response, Mapping) or set(response) != {
            "provider_id",
            "result",
            "result_digest",
            "result_schema_digest",
            "schema_version",
            "status",
            "trust",
        }:
            self._schema_drift("task result fields")
        if response["schema_version"] != HOST_SCHEMA_VERSION:
            self._schema_drift("task result schema version")
        if response["provider_id"] != provider_id:
            raise ProtocolRejection(
                "RECEIPT_IDENTITY_MISMATCH", "task result Host identity"
            )
        if response["status"] not in {"PENDING", "COMPLETED", "FAILED"}:
            self._schema_drift("task result status")
        if response["trust"] != "authoritative":
            raise ProtocolRejection("RECEIPT_ISSUER_UNTRUSTED", "task result trust")
        result = response["result"]
        digest = response["result_digest"]
        schema_digest = response["result_schema_digest"]
        expected_schema_digest = domain_digest(
            "loopskill-codex-result-schema-v1\n", result_payload_schema()
        )
        try:
            result = validate_result_payload(result)
        except ProtocolRejection:
            self._schema_drift("task result payload")
        if (
            not isinstance(digest, str)
            or not isinstance(schema_digest, str)
            or schema_digest != expected_schema_digest
            or digest
            != domain_digest(
                "loopskill-host-result-v1\n",
                {"result": result, "result_schema_digest": schema_digest},
            )
        ):
            raise ProtocolRejection("RECEIPT_IDENTITY_MISMATCH", "task result digest")
        return dict(response)

    def observe_finalization(
        self,
        *,
        loop_ref: str,
        finalization_ref: str,
        provider_id: str,
        subject_chain_digest: str,
    ) -> Receipt:
        """Translate exact lifecycle readback into a finalization receipt."""
        if not all((loop_ref, finalization_ref, provider_id, subject_chain_digest)):
            raise ProtocolRejection("INVALID_COMMAND", "incomplete finalization readback")
        capabilities = {
            record.capability: record for record in self.capabilities()
        }
        observation = self.read_resource("lifecycle", provider_id)
        acknowledged = observation["state"] == "TERMINAL"
        strict = (
            acknowledged
            and observation["trust"] == "authoritative"
            and self._strict_capability(capabilities["lifecycle_readback"])
        )
        outcome = "acknowledged" if acknowledged else "unknown"
        evidence = {
            "capability_receipts": {
                name: record.receipt_ref for name, record in sorted(capabilities.items())
            },
            "finalization_ref": finalization_ref,
            "observation": observation,
            "subject_chain_digest": subject_chain_digest,
        }
        evidence_digest = domain_digest(
            "loopskill-codex-finalization-observation-v1\n", evidence
        )
        receipt_ref = "receipt-" + domain_digest(
            "loopskill-receipt-ref-v1\n",
            {
                "evidence_digest": evidence_digest,
                "outcome": outcome,
                "subject_ref": finalization_ref,
            },
        )[:24]
        now = self.clock()
        return Receipt(
            receipt_ref=receipt_ref,
            issuer_ref=self.issuer_ref,
            issuer_trust=self.issuer_trust,
            trust_class="strict" if strict else "cooperative",
            action="lifecycle-readback",
            loop_ref=loop_ref,
            subject_ref=finalization_ref,
            attempt_ref=None,
            target_ref=provider_id,
            request_digest=subject_chain_digest,
            provider_idempotency_key=None,
            provider_resource_ref=provider_id,
            outcome=outcome,
            issued_at=_iso(now),
            expires_at=_iso(now + timedelta(minutes=5)),
            evidence_digest=evidence_digest,
        )

    def _bounded_readback(self, attempt: EffectAttempt) -> Mapping[str, Any] | None:
        for _ in range(self.max_readback_observations):
            try:
                response = self.provider.readback(
                    attempt.action, attempt.provider_idempotency_key
                )
            except HostUnavailable:
                return None
            if response is None:
                continue
            self._validate_observation(response, attempt)
            if response["status"] in {"ACCEPTED", "OBSERVED"}:
                return response
            if response["status"] == "NOT_FOUND":
                continue
        return None

    @staticmethod
    def _strict_capability(record: CapabilityRecord) -> bool:
        return record.availability == "AVAILABLE" and record.assurance == "STRICT"

    def _strict_observation_allowed(
        self, action: str, capabilities: Mapping[str, CapabilityRecord]
    ) -> bool:
        return self._strict_capability(
            capabilities[ACTION_CAPABILITIES[action]]
        ) and self._strict_capability(
            capabilities["lifecycle_readback"]
        )

    def _validate_attempt(self, attempt: EffectAttempt) -> None:
        if attempt.action not in HOST_ACTIONS:
            self._schema_drift("unknown Host action")
        expected_digest = domain_digest(
            "loopskill-provider-request-v1\n", attempt.payload
        )
        if expected_digest != attempt.provider_request_digest:
            raise ProtocolRejection(
                "RECEIPT_IDENTITY_MISMATCH", "provider request digest mismatch"
            )
        if not all(
            (
                attempt.attempt_ref,
                attempt.loop_ref,
                attempt.subject_kind,
                attempt.subject_ref,
                attempt.target_ref,
                attempt.provider_idempotency_key,
            )
        ):
            raise ProtocolRejection("INVALID_COMMAND", "incomplete effect attempt")
        if attempt.subject_kind not in {"DeliveryRef", "ExternalEffectRef"}:
            raise ProtocolRejection("WRONG_REFERENCE_KIND", attempt.subject_kind)
        if (
            attempt.subject_kind == "DeliveryRef"
            and attempt.delivery_ref != attempt.subject_ref
        ):
            raise ProtocolRejection(
                "RECEIPT_IDENTITY_MISMATCH", "Delivery subject identity mismatch"
            )

    def _validate_observation(
        self, response: Mapping[str, Any], attempt: EffectAttempt
    ) -> None:
        if not isinstance(response, Mapping) or set(response) != {
            "action",
            "idempotency_key",
            "provider_id",
            "schema_version",
            "status",
            "subject_id",
            "trust",
        }:
            self._schema_drift("observation fields")
        if response["schema_version"] != HOST_SCHEMA_VERSION:
            self._schema_drift("observation schema version")
        if response["status"] not in HOST_STATUSES:
            self._schema_drift("observation status enum")
        if response["trust"] not in {"authoritative", "cooperative", "none"}:
            self._schema_drift("observation trust enum")
        if response["status"] in {"ACCEPTED", "OBSERVED"} and (
            not response["provider_id"] or not response["subject_id"]
        ):
            self._schema_drift("accepted observation identity")
        if (
            response["action"] != attempt.action
            or response["idempotency_key"] != attempt.provider_idempotency_key
        ):
            raise ProtocolRejection(
                "RECEIPT_IDENTITY_MISMATCH", "Host observation identity mismatch"
            )

    def _validate_resource(
        self, response: Mapping[str, Any], resource_kind: str, provider_id: str
    ) -> None:
        if not isinstance(response, Mapping) or set(response) != {
            "provider_id",
            "resource_kind",
            "schema_version",
            "state",
            "trust",
        }:
            self._schema_drift("resource fields")
        if response["schema_version"] != HOST_SCHEMA_VERSION:
            self._schema_drift("resource schema version")
        if response["resource_kind"] != resource_kind or response["provider_id"] != provider_id:
            raise ProtocolRejection(
                "RECEIPT_IDENTITY_MISMATCH", "Host resource identity mismatch"
            )
        if response["state"] not in {"ACTIVE", "PAUSED", "TERMINAL", "NOT_FOUND"}:
            self._schema_drift("resource state enum")
        if response["trust"] not in {"authoritative", "cooperative", "none"}:
            self._schema_drift("resource trust enum")

    def _receipt(
        self,
        attempt: EffectAttempt,
        observation: Mapping[str, Any],
        *,
        capabilities: Mapping[str, CapabilityRecord],
        trust_class: str,
        outcome: str,
    ) -> Receipt:
        now = self.clock()
        evidence_digest = domain_digest(
            "loopskill-codex-observation-v1\n",
            {
                "capability_receipts": {
                    name: record.receipt_ref
                    for name, record in sorted(capabilities.items())
                },
                "observation": dict(observation),
            },
        )
        receipt_ref = "receipt-" + domain_digest(
            "loopskill-receipt-ref-v1\n",
            {
                "attempt_ref": attempt.attempt_ref,
                "evidence_digest": evidence_digest,
                "outcome": outcome,
            },
        )[:24]
        return Receipt(
            receipt_ref=receipt_ref,
            issuer_ref=self.issuer_ref,
            issuer_trust=self.issuer_trust,
            trust_class=trust_class,
            action=attempt.action,
            loop_ref=attempt.loop_ref,
            subject_ref=attempt.subject_ref,
            attempt_ref=attempt.attempt_ref,
            target_ref=attempt.target_ref,
            request_digest=attempt.provider_request_digest,
            provider_idempotency_key=attempt.provider_idempotency_key,
            provider_resource_ref=observation["provider_id"],
            outcome=outcome,
            issued_at=_iso(now),
            expires_at=_iso(now + timedelta(minutes=5)),
            evidence_digest=evidence_digest,
        )

    @staticmethod
    def _schema_drift(detail: str) -> None:
        raise ProtocolRejection("ADAPTER_SCHEMA_DRIFT", detail)
