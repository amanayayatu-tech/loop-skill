"""Privacy-safe metrics export (P1-6).

The export takes a :class:`MetricsLedger` and produces a JSON object
that contains only aggregated values, the schema version, the source
SHA, the run id, and digests of the by-kind histograms. It explicitly
drops any raw measurement, prompt fragment, chat text, task or
thread identifier, file path, PII, or raw log content.

The export is deterministic: the same ledger produces the same
output bytes given the same export parameters, which is what the
paper project needs to compare runs without leaking the underlying
records.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from loop_architect.metrics_ledger import MEASUREMENT_KINDS, MetricsLedger

EXPORT_SCHEMA_VERSION: str = "privacy-export-v1"

#: Field names that must never appear in the export payload. The
#: enforcement is name-based, not value-based: even a digest of a raw
#: prompt must not be present, so the export cannot accidentally
#: round-trip sensitive data.
FORBIDDEN_TOP_LEVEL_FIELDS: frozenset[str] = frozenset(
    {
        "prompt",
        "prompts",
        "chat",
        "chat_log",
        "raw_prompt",
        "raw_chat",
        "raw_log",
        "task_id",
        "thread_id",
        "route_id",
        "user_id",
        "owner_id",
        "file_path",
        "absolute_path",
        "secret",
        "credentials",
    }
)

#: Field name substrings that must never appear at any depth. The
#: export walks the payload after sanitization and refuses the
#: entire export if any key contains one of these tokens.
FORBIDDEN_KEY_SUBSTRINGS: tuple[str, ...] = (
    "prompt",
    "chat",
    "task_id",
    "thread_id",
    "user_id",
    "owner_id",
    "secret",
    "credential",
    "raw_log",
)


class PrivacyExportError(ValueError):
    """Raised when the export cannot satisfy its privacy contract."""


@dataclass
class PrivacySafeExport:
    """A privacy-safe aggregate view of a metrics ledger."""

    run_id: str
    source_sha: str
    schema_version: str
    total_records: int
    by_kind_counts: dict[str, int]
    by_kind_digests: dict[str, str]
    rejection_rate: float
    intervention_total: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "source_sha": self.source_sha,
            "total_records": self.total_records,
            "by_kind_counts": dict(self.by_kind_counts),
            "by_kind_digests": dict(self.by_kind_digests),
            "rejection_rate": self.rejection_rate,
            "intervention_total": self.intervention_total,
        }

    def to_canonical_bytes(self) -> bytes:
        """Return a deterministic byte representation of the export."""
        return json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":")
        ).encode()

    def digest(self) -> str:
        return hashlib.sha256(self.to_canonical_bytes()).hexdigest()


def export_from_ledger(ledger: MetricsLedger) -> PrivacySafeExport:
    """Build a :class:`PrivacySafeExport` from ``ledger``.

    The function never inspects individual measurement values; it
    only consumes the per-kind counts the ledger maintains. This is
    the privacy boundary: even if a measurement row happened to
    contain a sensitive value, that value never enters the export.
    """
    counts: dict[str, int] = {}
    for kind in MEASUREMENT_KINDS:
        count = ledger.count_of(kind)
        if count:
            counts[kind] = count

    digests: dict[str, str] = {
        kind: hashlib.sha256(f"{kind}:{count}".encode()).hexdigest()[:16]
        for kind, count in counts.items()
    }

    accepted = ledger.sum_of("accepted_count")
    rejected = ledger.sum_of("rejected_count")
    total_routes = accepted + rejected
    rejection_rate = (rejected / total_routes) if total_routes else 0.0

    intervention_total = (
        int(ledger.sum_of("human_intervention_count"))
        + int(ledger.sum_of("supervisor_intervention_count"))
    )

    export = PrivacySafeExport(
        run_id=ledger.run_id,
        source_sha=ledger.source_sha,
        schema_version=EXPORT_SCHEMA_VERSION,
        total_records=ledger.count,
        by_kind_counts=counts,
        by_kind_digests=digests,
        rejection_rate=rejection_rate,
        intervention_total=intervention_total,
    )
    enforce_no_forbidden_fields(export.to_dict())
    return export


def enforce_no_forbidden_fields(payload: Mapping[str, Any]) -> None:
    """Walk ``payload`` and refuse any forbidden key.

    The walker is intentionally strict: it does not allow renaming to
    evade the substring filter, and it descends into lists and dicts
    at any depth. The walk is O(n) in payload size.
    """
    stack: list[Any] = list(payload.items())
    while stack:
        key, value = stack.pop()
        if not isinstance(key, str):
            raise PrivacyExportError(f"non-string key encountered: {key!r}")
        if key in FORBIDDEN_TOP_LEVEL_FIELDS:
            raise PrivacyExportError(
                f"forbidden top-level field {key!r} in privacy export"
            )
        lowered = key.lower()
        for token in FORBIDDEN_KEY_SUBSTRINGS:
            if token in lowered:
                raise PrivacyExportError(
                    f"forbidden key {key!r} (contains {token!r}) in privacy export"
                )
        if isinstance(value, Mapping):
            stack.extend(value.items())
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, Mapping):
                    stack.extend(item.items())
                elif isinstance(item, str):
                    # Values are not keys, but we still flag strings
                    # that look like raw prompts; this is a defensive
                    # backstop, not a primary filter.
                    if len(item) > 4096:
                        raise PrivacyExportError(
                            f"value at index {index} exceeds 4096 char privacy cap"
                        )


__all__ = [
    "EXPORT_SCHEMA_VERSION",
    "FORBIDDEN_KEY_SUBSTRINGS",
    "FORBIDDEN_TOP_LEVEL_FIELDS",
    "PrivacySafeExport",
    "PrivacyExportError",
    "enforce_no_forbidden_fields",
    "export_from_ledger",
]
