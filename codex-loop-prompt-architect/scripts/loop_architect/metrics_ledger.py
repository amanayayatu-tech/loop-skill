"""Append-only metrics ledger (P1-5).

Records per-loop measurements of route latency, heartbeat latency,
recovery latency, accepted/rejected counts, model/runtime/config
digests, token estimates, and the count of human / Supervisor
interventions. Missing values are written as the literal string
``"UNMETERED"`` so downstream consumers can distinguish "not
measured" from "measured as zero".

The ledger file is JSONL with one record per measurement. The schema
is fixed to keep CI checks simple; new measurement kinds are added
by appending to :data:`MEASUREMENT_KINDS` and bumping
``schema_version`` (handled by a single call site in tests).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

#: Sentinel emitted whenever a measurement was supposed to exist but
#: the runtime never captured it. Distinct from ``0`` and from
#: ``None`` so consumers must treat it explicitly.
UNMETERED: str = "UNMETERED"

#: Allowed measurement kinds. Adding a kind here requires bumping
#: :data:`SCHEMA_VERSION` and a corresponding CI guard test.
MEASUREMENT_KINDS: frozenset[str] = frozenset(
    {
        "route_latency_ms",
        "heartbeat_latency_ms",
        "recovery_latency_ms",
        "accepted_count",
        "rejected_count",
        "model_digest",
        "runtime_digest",
        "config_digest",
        "token_estimate",
        "cost_estimate_usd",
        "human_intervention_count",
        "supervisor_intervention_count",
    }
)

SCHEMA_VERSION: str = "metrics-ledger-v1"


class MetricsLedgerError(ValueError):
    """Raised on schema violation, ledger corruption, or invalid
    kind names."""


@dataclass
class MetricsLedger:
    """Append-only measurement ledger.

    The file is JSONL. Each line is a JSON object with at minimum
    ``{timestamp, kind, value, source_sha, run_id, prev_hash, hash}``.
    The hash chain is over the previous hash and the canonical record,
    identical in spirit to the rejection-journal chain.
    """

    path: Path
    run_id: str
    source_sha: str
    _last_hash: str = ""
    _count: int = 0
    _by_kind: dict[str, int] = field(default_factory=dict)
    _sum_by_kind: dict[str, float] = field(default_factory=dict)

    @classmethod
    def open(
        cls, path: Path, *, run_id: str, source_sha: str
    ) -> "MetricsLedger":
        ledger = cls(path=path, run_id=run_id, source_sha=source_sha)
        if not path.exists():
            return ledger
        last_hash = ""
        count = 0
        by_kind: dict[str, int] = {}
        sum_by_kind: dict[str, float] = {}
        for line_number, raw in enumerate(path.read_text().splitlines(), start=1):
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise MetricsLedgerError(
                    f"ledger {path} line {line_number} invalid JSON: {exc}"
                ) from exc
            declared_prev = entry.get("prev_hash", "")
            declared_hash = entry.get("hash", "")
            payload = {
                "timestamp": entry.get("timestamp"),
                "kind": entry.get("kind"),
                "value": entry.get("value"),
                "source_sha": entry.get("source_sha"),
                "run_id": entry.get("run_id"),
            }
            expected_hash = _chain_hash(last_hash, payload)
            if declared_prev != last_hash or declared_hash != expected_hash:
                raise MetricsLedgerError(
                    f"ledger {path} line {line_number} hash chain broken"
                )
            kind = entry.get("kind", "")
            if kind not in MEASUREMENT_KINDS:
                raise MetricsLedgerError(
                    f"ledger {path} line {line_number} unknown kind {kind!r}"
                )
            count += 1
            by_kind[kind] = by_kind.get(kind, 0) + 1
            if isinstance(entry.get("value"), (int, float)):
                sum_by_kind[kind] = sum_by_kind.get(kind, 0) + entry["value"]
            last_hash = declared_hash
        ledger._last_hash = last_hash
        ledger._count = count
        ledger._by_kind = by_kind
        ledger._sum_by_kind = sum_by_kind
        return ledger

    def record(
        self,
        kind: str,
        value: Any,
        *,
        timestamp: str | None = None,
    ) -> str:
        """Append a measurement to the ledger.

        ``value`` may be a number, a string, or the literal
        :data:`UNMETERED`. Numeric values are encoded as JSON numbers;
        everything else is encoded as a string so the JSON shape stays
        stable.
        """
        if kind not in MEASUREMENT_KINDS:
            raise MetricsLedgerError(f"unknown kind {kind!r}")
        ts = timestamp or _now_iso()
        encoded_value = value if isinstance(value, (int, float)) else str(value)
        payload = {
            "timestamp": ts,
            "kind": kind,
            "value": encoded_value,
            "source_sha": self.source_sha,
            "run_id": self.run_id,
        }
        new_hash = _chain_hash(self._last_hash, payload)
        entry = {
            "schema_version": SCHEMA_VERSION,
            **payload,
            "prev_hash": self._last_hash,
            "hash": new_hash,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        import os as _os
        descriptor = _os.open(
            self.path, _os.O_WRONLY | _os.O_CREAT | _os.O_APPEND, 0o600
        )
        try:
            with _os.fdopen(descriptor, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")
                handle.flush()
                _os.fsync(handle.fileno())
        except Exception:
            try:
                _os.close(descriptor)
            except OSError:
                pass
            raise
        self._last_hash = new_hash
        self._count += 1
        self._by_kind[kind] = self._by_kind.get(kind, 0) + 1
        if isinstance(value, (int, float)):
            self._sum_by_kind[kind] = self._sum_by_kind.get(kind, 0) + value
        return new_hash

    @property
    def count(self) -> int:
        return self._count

    @property
    def last_hash(self) -> str:
        return self._last_hash

    def count_of(self, kind: str) -> int:
        if kind not in MEASUREMENT_KINDS:
            raise MetricsLedgerError(f"unknown kind {kind!r}")
        return self._by_kind.get(kind, 0)

    def sum_of(self, kind: str) -> float:
        """Return the sum of numeric values recorded for ``kind``.

        Non-numeric values (including :data:`UNMETERED`) are ignored.
        Returns ``0`` when no numeric value has been recorded for
        ``kind`` yet.
        """
        if kind not in MEASUREMENT_KINDS:
            raise MetricsLedgerError(f"unknown kind {kind!r}")
        return self._sum_by_kind.get(kind, 0)


def _chain_hash(prev_hash: str, payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256((prev_hash or "").encode() + b"|" + canonical).hexdigest()


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def coerce_or_unmetered(value: Any) -> Any:
    """Return ``value`` if it is a real measurement, or
    :data:`UNMETERED` if it is ``None`` or empty.

    The coercion is intentionally narrow: the caller must already have
    determined the measurement kind. We do not silently coerce
    numbers, since a real ``0`` is meaningful.
    """
    if value is None:
        return UNMETERED
    if isinstance(value, str) and value == "":
        return UNMETERED
    return value


__all__ = [
    "MEASUREMENT_KINDS",
    "MetricsLedger",
    "MetricsLedgerError",
    "SCHEMA_VERSION",
    "UNMETERED",
    "coerce_or_unmetered",
]
