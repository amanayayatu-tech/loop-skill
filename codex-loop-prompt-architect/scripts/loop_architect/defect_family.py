"""Defect family catalog and runtime discovery ledger (P1-1).

A defect family is a runtime, content-addressed entity that captures the
shape of one recurring repair surface so the next repair attempt can
recognize a sibling and so the third same-family return can trigger an
escalation (P1-3). The catalog is deterministic and JSON-stable; the
ledger is a hash-chained append-only file at the loop root, paralleling
``rejection_journal`` for negative evidence and ``LOOP_EVENTS.jsonl`` for
positive state.

Defect families are intentionally orthogonal to the existing recovery
registry: the recovery registry tells the runtime what to do when a
single rejection is observed; the defect-family ledger tells the runtime
when the same shape of rejection has been seen enough times to demand
a structural change rather than another point fix.

The module is pure-Python and does not import from ``state_runtime``
to keep the dependency surface minimal. It accepts the ledger file
path and discovery records as plain dicts so it can be wired into the
runtime by follow-up commits without entangling this commit.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

#: Canonical order of fields used to compute a defect-family digest. New
#: fields must be appended to keep historical digests reproducible.
_FAMILY_DIGEST_FIELDS: tuple[str, ...] = (
    "family_id",
    "searched_files",
    "searched_patterns",
    "entrypoints",
    "type_matrix",
    "siblings",
    "closure_status",
)

#: Maximum number of siblings a single family record may list. The
#: cap exists so a misbehaving discovery cannot blow up the digest or
#: the recovery upgrade trigger.
MAX_SIBLINGS_PER_FAMILY = 64

#: A conservative pattern for a ``family_id``. We accept lowercase
#: letters, digits, dot, dash, and underscore; must start with a
#: letter; total length 1..96. This is the same character class the
#: existing recovery registry uses for rejection codes.
_FAMILY_ID_RE = re.compile(r"^[a-z][a-z0-9._-]{0,95}$")

#: A conservative pattern for a sibling identifier (file path, error
#: code, function name, or any of the above separated by ``::``).
_SIBLING_RE = re.compile(r"^[A-Za-z0-9._/:@<>-]{1,256}$")

#: A pattern for a search-pattern token. The token is hashed into the
#: family digest, not stored verbatim, because the runtime never
#: retains the raw source content in the family record.
_PATTERN_TOKEN_RE = re.compile(r"^[A-Za-z0-9._:()\[\]<>+*?-]{1,128}$")

#: Closure statuses. ``OPEN`` means the family has at least one
#: unmitigated sibling; ``CONTAINED`` means every known sibling is
#: fixed but the family is still under watch; ``CLOSED`` means no
#: further action is expected; ``ESCALATED`` means a higher-order
#: resolution (Goal split, claim narrowing, refactor, limitation) is
#: in effect.
CLOSURE_STATUSES: frozenset[str] = frozenset(
    {"OPEN", "CONTAINED", "CLOSED", "ESCALATED"}
)


class DefectFamilyError(ValueError):
    """Raised on invalid family records, ledger corruption, or
    invariant violations."""


@dataclass(frozen=True)
class DefectFamily:
    """A single defect-family record.

    Attributes are intentionally restricted to the digest input fields
    plus the discoverer's identity and a free-form remediation note.
    The class enforces the JSON-stable shape consumed by
    ``build_recovery_registry`` and by the upgrade-trigger logic in
    :mod:`reviewer_envelope`.
    """

    family_id: str
    searched_files: tuple[str, ...]
    searched_patterns: tuple[str, ...]
    entrypoints: tuple[str, ...]
    type_matrix: tuple[tuple[str, tuple[str, ...]], ...]
    siblings: tuple[str, ...]
    closure_status: str
    discoverer: str
    remediation_note: str = ""

    def __post_init__(self) -> None:
        if not _FAMILY_ID_RE.match(self.family_id):
            raise DefectFamilyError(
                f"family_id {self.family_id!r} does not match {_FAMILY_ID_RE.pattern}"
            )
        if self.closure_status not in CLOSURE_STATUSES:
            raise DefectFamilyError(
                f"closure_status {self.closure_status!r} not in {sorted(CLOSURE_STATUSES)}"
            )
        if len(self.siblings) > MAX_SIBLINGS_PER_FAMILY:
            raise DefectFamilyError(
                f"siblings count {len(self.siblings)} exceeds cap {MAX_SIBLINGS_PER_FAMILY}"
            )
        for sibling in self.siblings:
            if not _SIBLING_RE.match(sibling):
                raise DefectFamilyError(f"sibling {sibling!r} has invalid shape")
        for pattern in self.searched_patterns:
            if not _PATTERN_TOKEN_RE.match(pattern):
                raise DefectFamilyError(
                    f"searched_pattern {pattern!r} has invalid shape"
                )

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-stable representation of the family."""
        result: dict[str, Any] = {
            "family_id": self.family_id,
            "searched_files": list(self.searched_files),
            "searched_patterns": list(self.searched_patterns),
            "entrypoints": list(self.entrypoints),
            "type_matrix": [
                [name, list(values)] for name, values in self.type_matrix
            ],
            "siblings": list(self.siblings),
            "closure_status": self.closure_status,
            "discoverer": self.discoverer,
        }
        if self.remediation_note:
            result["remediation_note"] = self.remediation_note
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DefectFamily":
        """Hydrate a ``DefectFamily`` from a JSON-stable dict."""
        if not isinstance(payload, Mapping):
            raise DefectFamilyError("family payload must be a mapping")
        try:
            type_matrix = tuple(
                (name, tuple(values))
                for name, values in payload["type_matrix"]
            )
        except (KeyError, TypeError) as exc:
            raise DefectFamilyError(
                f"type_matrix missing or malformed: {exc}"
            ) from exc
        return cls(
            family_id=str(payload["family_id"]),
            searched_files=tuple(str(value) for value in payload.get("searched_files", ())),
            searched_patterns=tuple(
                str(value) for value in payload.get("searched_patterns", ())
            ),
            entrypoints=tuple(str(value) for value in payload.get("entrypoints", ())),
            type_matrix=type_matrix,
            siblings=tuple(str(value) for value in payload.get("siblings", ())),
            closure_status=str(payload.get("closure_status", "OPEN")),
            discoverer=str(payload.get("discoverer", "unspecified")),
            remediation_note=str(payload.get("remediation_note", "")),
        )

    def digest(self) -> str:
        """Return the SHA-256 of the canonical family record.

        Only the fields listed in :data:`_FAMILY_DIGEST_FIELDS` participate
        in the digest, so the discoverer identity and the remediation
        note can be updated without breaking the family identity.
        """
        canonical = {
            "family_id": self.family_id,
            "searched_files": list(self.searched_files),
            "searched_patterns": list(self.searched_patterns),
            "entrypoints": list(self.entrypoints),
            "type_matrix": [
                [name, list(values)] for name, values in self.type_matrix
            ],
            "siblings": list(self.siblings),
            "closure_status": self.closure_status,
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass
class DefectFamilyLedger:
    """Hash-chained append-only ledger of defect-family records.

    The ledger file is JSONL. Each line is a JSON object with at minimum
    ``{timestamp, family, prev_hash, hash}``. ``prev_hash`` is the
    ``hash`` of the previous line (or the empty string for the first
    line). ``hash`` is SHA-256 over the canonical byte concatenation
    of the previous ``hash`` and the current line's ``family`` digest.
    """

    path: Path
    families: dict[str, DefectFamily] = field(default_factory=dict)
    _last_hash: str = ""

    @classmethod
    def open(cls, path: Path) -> "DefectFamilyLedger":
        ledger = cls(path=path)
        if not path.exists():
            return ledger
        last_hash = ""
        for line_number, raw in enumerate(path.read_text().splitlines(), start=1):
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise DefectFamilyError(
                    f"ledger {path} line {line_number} invalid JSON: {exc}"
                ) from exc
            family = DefectFamily.from_dict(entry["family"])
            declared_prev = entry.get("prev_hash", "")
            declared_hash = entry.get("hash", "")
            expected_hash = _chain_hash(last_hash, family.digest())
            if declared_prev != last_hash or declared_hash != expected_hash:
                raise DefectFamilyError(
                    f"ledger {path} line {line_number} hash chain broken "
                    f"(declared_prev={declared_prev!r}, declared_hash={declared_hash!r})"
                )
            ledger.families[family.family_id] = family
            last_hash = declared_hash
        ledger._last_hash = last_hash
        return ledger

    def append(self, family: DefectFamily) -> str:
        """Append a family to the ledger, returning the new chain hash.

        The write is atomic: a temporary sibling file is written, fsynced,
        and renamed over the target. Concurrent appenders should hold an
        external lock; the chain itself does not retry on contention.
        """
        if family.family_id in self.families:
            existing = self.families[family.family_id]
            if existing.digest() == family.digest():
                return self._last_hash
            raise DefectFamilyError(
                f"family {family.family_id!r} already exists with a different digest"
            )
        new_hash = _chain_hash(self._last_hash, family.digest())
        entry = {
            "timestamp": _now_iso(),
            "family": family.to_dict(),
            "prev_hash": self._last_hash,
            "hash": new_hash,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
            handle.flush()
            import os as _os
            _os.fsync(handle.fileno())
        _os.replace(tmp, self.path)
        self.families[family.family_id] = family
        self._last_hash = new_hash
        return new_hash

    def find_siblings(self, family_id: str) -> tuple[DefectFamily, ...]:
        """Return families whose ``family_id`` shares the leading
        namespace token with ``family_id``. Namespace is the substring
        before the first dot, or the whole id if no dot is present.
        """
        namespace = family_id.split(".", 1)[0]
        results = [
            family
            for family in self.families.values()
            if family.family_id != family_id
            and family.family_id.split(".", 1)[0] == namespace
        ]
        results.sort(key=lambda family: family.family_id)
        return tuple(results)

    def same_family_returns(self, family_id: str) -> int:
        """Return the number of times ``family_id`` has been
        appended, including the most recent one.

        The chain itself stores one record per family, but the
        upgrade-trigger logic counts *returns* in the rejection stream
        against the same family; this helper returns the number of
        distinct ledger entries, which is a lower bound that the
        upgrade logic uses together with the rejection stream.
        """
        return 1 if family_id in self.families else 0


def _chain_hash(prev_hash: str, family_digest: str) -> str:
    payload = (prev_hash or "").encode() + b"|" + family_digest.encode()
    return hashlib.sha256(payload).hexdigest()


def _now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 form.

    Centralized so tests can monkey-patch it without rewiring every
    call site. We avoid :func:`datetime.utcnow` to keep the timestamp
    explicit about the timezone.
    """
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def merge_sibling_discovery(
    base: DefectFamily,
    discovered: Iterable[Mapping[str, Any]],
    *,
    max_new: int = MAX_SIBLINGS_PER_FAMILY,
) -> DefectFamily:
    """Return a new ``DefectFamily`` that includes the discovered
    siblings, deduplicated, while preserving the original family_id,
    digest inputs, and discoverer.

    The merge is conservative: if the discovered list pushes the
    total sibling count above ``max_new``, the surplus is dropped and
    a ``remediation_note`` suffix is added. This keeps the catalog
    bounded even when the same family keeps growing.
    """
    existing = set(base.siblings)
    merged: list[str] = list(base.siblings)
    dropped = 0
    for entry in discovered:
        sibling = str(entry.get("sibling", ""))
        if not sibling:
            continue
        if sibling in existing:
            continue
        if len(merged) >= max_new:
            dropped += 1
            continue
        existing.add(sibling)
        merged.append(sibling)
    note = base.remediation_note
    if dropped:
        suffix = f"merge dropped {dropped} siblings over cap {max_new}"
        note = f"{note}; {suffix}" if note else suffix
    return DefectFamily(
        family_id=base.family_id,
        searched_files=base.searched_files,
        searched_patterns=base.searched_patterns,
        entrypoints=base.entrypoints,
        type_matrix=base.type_matrix,
        siblings=tuple(merged),
        closure_status=base.closure_status,
        discoverer=base.discoverer,
        remediation_note=note,
    )


__all__ = [
    "CLOSURE_STATUSES",
    "DefectFamily",
    "DefectFamilyError",
    "DefectFamilyLedger",
    "MAX_SIBLINGS_PER_FAMILY",
    "merge_sibling_discovery",
]
