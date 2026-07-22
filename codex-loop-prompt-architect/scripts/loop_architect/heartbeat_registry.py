"""Single-source heartbeat registry (P1-8).

The registry makes the automation ID, target, RRULE, prompt digest,
purpose, and status of a heartbeat a single source of truth. The
existing dispatch code reads the registry; nothing else in the runtime
is allowed to invent or override the values. The registry is content-
addressed: the SHA-256 of the canonical record is the canonical
identity, and the runtime must reject any heartbeat that disagrees.

The module is pure-Python and does not depend on ``state_runtime``.
It accepts a JSONL file path and writes one record per heartbeat
event (``REGISTER``, ``PAUSE``, ``RESUME``, ``OBSERVE``). Updates are
appended, never overwritten; the active record is the one with the
highest ``sequence`` for the given ``automation_id``.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

#: Allowed event types. Adding a kind here requires a CI guard test.
EVENT_TYPES: frozenset[str] = frozenset({"REGISTER", "PAUSE", "RESUME", "OBSERVE"})

#: Allowed statuses. ``ACTIVE`` and ``PAUSED`` mirror the existing
#: schema-v3 states; ``RETIRED`` is a terminal state.
STATUSES: frozenset[str] = frozenset({"ACTIVE", "PAUSED", "RETIRED"})

#: Maximum automation identifier length, mirroring the schema-v3 48
#: character bound from the existing transport layer.
MAX_AUTOMATION_ID_LEN = 48

#: Conservative character class for an automation id.
_AUTOMATION_ID_RE = re.compile(r"^[A-Za-z0-9._:@<>-]{1,48}$")


class HeartbeatRegistryError(ValueError):
    """Raised on schema violation, ledger corruption, or
    registry drift."""


@dataclass(frozen=True)
class HeartbeatRecord:
    automation_id: str
    target: str
    rrule: str
    prompt_digest: str
    purpose: str
    status: str
    event_type: str
    sequence: int
    timestamp: str
    note: str = ""

    def __post_init__(self) -> None:
        if not _AUTOMATION_ID_RE.match(self.automation_id):
            raise HeartbeatRegistryError(
                f"automation_id {self.automation_id!r} invalid"
            )
        if self.event_type not in EVENT_TYPES:
            raise HeartbeatRegistryError(
                f"event_type {self.event_type!r} not in {sorted(EVENT_TYPES)}"
            )
        if self.status not in STATUSES:
            raise HeartbeatRegistryError(
                f"status {self.status!r} not in {sorted(STATUSES)}"
            )
        if self.sequence < 1:
            raise HeartbeatRegistryError(
                f"sequence must be >= 1 (got {self.sequence})"
            )
        if len(self.prompt_digest) != 64:
            raise HeartbeatRegistryError(
                "prompt_digest must be a 64-character SHA-256"
            )

    def canonical(self) -> bytes:
        return json.dumps(
            {
                "automation_id": self.automation_id,
                "target": self.target,
                "rrule": self.rrule,
                "prompt_digest": self.prompt_digest,
                "purpose": self.purpose,
                "status": self.status,
                "event_type": self.event_type,
                "sequence": self.sequence,
                "timestamp": self.timestamp,
                "note": self.note,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    def digest(self) -> str:
        return hashlib.sha256(self.canonical()).hexdigest()


class HeartbeatRegistry:
    """JSONL-backed append-only registry.

    The active record for an ``automation_id`` is the record with the
    highest ``sequence``. Drift detection is implemented by comparing
    the prompt_digest against a caller-supplied expected value.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._latest: dict[str, HeartbeatRecord] = {}
        self._by_id: dict[str, list[HeartbeatRecord]] = {}
        if path.exists():
            self._reload()

    def _reload(self) -> None:
        last_seq: dict[str, int] = {}
        for line_number, raw in enumerate(self.path.read_text().splitlines(), start=1):
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise HeartbeatRegistryError(
                    f"registry {self.path} line {line_number} invalid JSON: {exc}"
                ) from exc
            record = HeartbeatRecord(
                automation_id=str(entry["automation_id"]),
                target=str(entry["target"]),
                rrule=str(entry["rrule"]),
                prompt_digest=str(entry["prompt_digest"]),
                purpose=str(entry.get("purpose", "")),
                status=str(entry["status"]),
                event_type=str(entry["event_type"]),
                sequence=int(entry["sequence"]),
                timestamp=str(entry["timestamp"]),
                note=str(entry.get("note", "")),
            )
            bucket = self._by_id.setdefault(record.automation_id, [])
            bucket.append(record)
            if record.sequence >= last_seq.get(record.automation_id, 0):
                self._latest[record.automation_id] = record
                last_seq[record.automation_id] = record.sequence

    def append(self, record: HeartbeatRecord) -> str:
        """Append ``record`` to the registry, returning its digest.

        The sequence must be strictly greater than the current
        sequence for the same ``automation_id``; out-of-order writes
        are rejected.
        """
        existing = self._by_id.get(record.automation_id, ())
        if existing and record.sequence <= existing[-1].sequence:
            raise HeartbeatRegistryError(
                f"sequence {record.sequence} not greater than last "
                f"{existing[-1].sequence} for {record.automation_id!r}"
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {
            "automation_id": record.automation_id,
            "target": record.target,
            "rrule": record.rrule,
            "prompt_digest": record.prompt_digest,
            "purpose": record.purpose,
            "status": record.status,
            "event_type": record.event_type,
            "sequence": record.sequence,
            "timestamp": record.timestamp,
            "note": record.note,
            "digest": record.digest(),
        }
        with tmp.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
            handle.flush()
            import os as _os
            _os.fsync(handle.fileno())
        _os.replace(tmp, self.path)
        bucket = self._by_id.setdefault(record.automation_id, [])
        bucket.append(record)
        self._latest[record.automation_id] = record
        return record.digest()

    def latest(self, automation_id: str) -> HeartbeatRecord | None:
        return self._latest.get(automation_id)

    def history(self, automation_id: str) -> tuple[HeartbeatRecord, ...]:
        return tuple(self._by_id.get(automation_id, ()))

    def assert_drift_free(
        self, automation_id: str, *, expected_prompt_digest: str
    ) -> HeartbeatRecord:
        """Return the latest record, or raise if the prompt digest
        disagrees with the caller's expected value.
        """
        latest = self.latest(automation_id)
        if latest is None:
            raise HeartbeatRegistryError(
                f"no record for {automation_id!r}"
            )
        if latest.prompt_digest != expected_prompt_digest:
            raise HeartbeatRegistryError(
                f"prompt_drift for {automation_id!r}: "
                f"expected {expected_prompt_digest!r}, "
                f"registry holds {latest.prompt_digest!r}"
            )
        return latest

    def all_automation_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._latest.keys()))


def new_heartbeat_record(
    *,
    automation_id: str,
    target: str,
    rrule: str,
    prompt_text: str,
    purpose: str,
    status: str,
    event_type: str,
    sequence: int,
    note: str = "",
    timestamp: str | None = None,
) -> HeartbeatRecord:
    """Convenience builder that hashes ``prompt_text`` for the caller.

    The function never stores ``prompt_text``; only the SHA-256 digest
    ends up in the record. This is the privacy boundary for the
    registry.
    """
    if not target:
        raise HeartbeatRegistryError("target is required")
    if not rrule:
        raise HeartbeatRegistryError("rrule is required")
    if not purpose:
        raise HeartbeatRegistryError("purpose is required")
    prompt_digest = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
    return HeartbeatRecord(
        automation_id=automation_id,
        target=target,
        rrule=rrule,
        prompt_digest=prompt_digest,
        purpose=purpose,
        status=status,
        event_type=event_type,
        sequence=sequence,
        timestamp=timestamp or _now_iso(),
        note=note,
    )


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "EVENT_TYPES",
    "HeartbeatRecord",
    "HeartbeatRegistry",
    "HeartbeatRegistryError",
    "MAX_AUTOMATION_ID_LEN",
    "STATUSES",
    "new_heartbeat_record",
]
