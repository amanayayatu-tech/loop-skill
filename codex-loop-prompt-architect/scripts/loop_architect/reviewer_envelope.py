"""Reviewer envelope enforcing same-round sibling disclosure (P1-2)
and the third-same-family return auto-escalation (P1-3).

The runtime never invents a Reviewer verdict. Instead, every Reviewer
return passes through :class:`ReviewerEnvelope` so the same defect
shape is exposed in the same round and a third return against the
same family triggers an escalation instead of another point repair.

The module is pure-Python: it accepts the family's digest (computed
elsewhere) and the same-round search evidence, and refuses envelopes
that hide siblings, hide unchecked surfaces, or claim
``POINT_REPAIR`` after the third return.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

#: Same-round disclosure required for the Reviewer to be considered
#: honest. Hidden siblings and unchecked surfaces must be enumerated
#: explicitly so the next round cannot silently re-discover them.
REQUIRED_DISCLOSURE_FIELDS: tuple[str, ...] = (
    "searched_files",
    "searched_patterns",
    "unchecked_surfaces",
    "siblings",
)

#: Closure actions available on the third return. Anything outside
#: this set is rejected; "POINT_REPAIR" is in here only as the first
#: two returns, never the third.
ALLOWED_FIRST_RETURNS: frozenset[str] = frozenset({"POINT_REPAIR", "PASS"})
ALLOWED_ESCALATION_RETURNS: frozenset[str] = frozenset(
    {"REFACTOR", "GOAL_SPLIT", "CLAIM_NARROWING", "LIMITATION"}
)

#: The numeric threshold at which a same-family return flips from
#: ``POINT_REPAIR``-capable to escalation-only.
THIRD_RETURN_THRESHOLD = 3


class ReviewerEnvelopeError(ValueError):
    """Raised when a Reviewer envelope violates the contract."""


@dataclass(frozen=True)
class ReviewerEnvelope:
    """One Reviewer return, after disclosure normalization.

    The runtime builds the envelope from the Reviewer's raw output plus
    the parent's catalog and discovery state; downstream callers see
    only the validated envelope.
    """

    verdict: str
    defect_family_id: str
    defect_family_digest: str
    searched_files: tuple[str, ...]
    searched_patterns: tuple[str, ...]
    unchecked_surfaces: tuple[str, ...]
    siblings: tuple[str, ...]
    return_number: int
    remediation: str = ""
    evidence_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "verdict": self.verdict,
            "defect_family_id": self.defect_family_id,
            "defect_family_digest": self.defect_family_digest,
            "searched_files": list(self.searched_files),
            "searched_patterns": list(self.searched_patterns),
            "unchecked_surfaces": list(self.unchecked_surfaces),
            "siblings": list(self.siblings),
            "return_number": self.return_number,
        }
        if self.remediation:
            result["remediation"] = self.remediation
        if self.evidence_paths:
            result["evidence_paths"] = list(self.evidence_paths)
        return result

    def digest(self) -> str:
        """Return the SHA-256 of the canonical envelope."""
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass
class ReviewerReturnCounter:
    """Per-family return counter for the escalation trigger."""

    counts: dict[str, int] = field(default_factory=dict)

    def observe(self, family_id: str) -> int:
        """Increment the counter for ``family_id`` and return the new
        value. Reviewers must call this once per envelope, in the
        same order the envelopes are produced.
        """
        next_value = self.counts.get(family_id, 0) + 1
        self.counts[family_id] = next_value
        return next_value

    def is_at_threshold(self, family_id: str) -> bool:
        return self.counts.get(family_id, 0) >= THIRD_RETURN_THRESHOLD


def validate_envelope(envelope: ReviewerEnvelope) -> None:
    """Raise :class:`ReviewerEnvelopeError` if the envelope hides
    siblings, hides unchecked surfaces, or mis-classifies a return.

    The same call must reject POINT_REPAIR on the third return and
    must require every disclosure field to be present even when the
    sibling list is empty.
    """
    missing = [
        field_name
        for field_name in REQUIRED_DISCLOSURE_FIELDS
        if getattr(envelope, field_name, None) is None
    ]
    if missing:
        raise ReviewerEnvelopeError(
            f"envelope missing required disclosure fields: {missing}"
        )
    if not envelope.defect_family_id:
        raise ReviewerEnvelopeError("defect_family_id must be non-empty")
    if not envelope.defect_family_digest:
        raise ReviewerEnvelopeError("defect_family_digest must be non-empty")
    if envelope.return_number < 1:
        raise ReviewerEnvelopeError(
            f"return_number must be >= 1 (got {envelope.return_number})"
        )
    if envelope.return_number >= THIRD_RETURN_THRESHOLD:
        if envelope.verdict not in ALLOWED_ESCALATION_RETURNS:
            raise ReviewerEnvelopeError(
                f"return {envelope.return_number} for family "
                f"{envelope.defect_family_id!r} must be one of "
                f"{sorted(ALLOWED_ESCALATION_RETURNS)} (got {envelope.verdict!r})"
            )
    elif envelope.verdict not in ALLOWED_FIRST_RETURNS:
        raise ReviewerEnvelopeError(
            f"return {envelope.return_number} for family "
            f"{envelope.defect_family_id!r} must be one of "
            f"{sorted(ALLOWED_FIRST_RETURNS)} or escalate (got {envelope.verdict!r})"
        )


def build_envelope(
    *,
    verdict: str,
    defect_family_id: str,
    defect_family_digest: str,
    searched_files: Sequence[str],
    searched_patterns: Sequence[str],
    unchecked_surfaces: Sequence[str],
    siblings: Sequence[str],
    return_number: int,
    remediation: str = "",
    evidence_paths: Sequence[str] = (),
) -> ReviewerEnvelope:
    """Build and validate a :class:`ReviewerEnvelope` in one call.

    The wrapper is the only public way to construct an envelope, so
    any future field additions stay in lock-step with
    :func:`validate_envelope`.
    """
    envelope = ReviewerEnvelope(
        verdict=verdict,
        defect_family_id=defect_family_id,
        defect_family_digest=defect_family_digest,
        searched_files=tuple(searched_files),
        searched_patterns=tuple(searched_patterns),
        unchecked_surfaces=tuple(unchecked_surfaces),
        siblings=tuple(siblings),
        return_number=return_number,
        remediation=remediation,
        evidence_paths=tuple(evidence_paths),
    )
    validate_envelope(envelope)
    return envelope


def envelope_from_mapping(
    payload: Mapping[str, Any],
    *,
    return_counter: ReviewerReturnCounter | None = None,
) -> ReviewerEnvelope:
    """Re-hydrate a Reviewer envelope from a JSON-stable mapping.

    When ``return_counter`` is provided, the envelope's
    ``return_number`` is filled from the counter (the next integer
    for the family), and the counter is then advanced. When
    ``return_counter`` is None, ``return_number`` must be present in
    the payload.
    """
    if not isinstance(payload, Mapping):
        raise ReviewerEnvelopeError("envelope payload must be a mapping")
    family_id = str(payload.get("defect_family_id", ""))
    if return_counter is not None and family_id:
        return_number = return_counter.observe(family_id)
    else:
        return_number = int(payload.get("return_number", 0))
    return build_envelope(
        verdict=str(payload.get("verdict", "")),
        defect_family_id=family_id,
        defect_family_digest=str(payload.get("defect_family_digest", "")),
        searched_files=tuple(str(value) for value in payload.get("searched_files", ())),
        searched_patterns=tuple(
            str(value) for value in payload.get("searched_patterns", ())
        ),
        unchecked_surfaces=tuple(
            str(value) for value in payload.get("unchecked_surfaces", ())
        ),
        siblings=tuple(str(value) for value in payload.get("siblings", ())),
        return_number=return_number,
        remediation=str(payload.get("remediation", "")),
        evidence_paths=tuple(str(value) for value in payload.get("evidence_paths", ())),
    )


__all__ = [
    "ALLOWED_ESCALATION_RETURNS",
    "ALLOWED_FIRST_RETURNS",
    "REQUIRED_DISCLOSURE_FIELDS",
    "ReviewerEnvelope",
    "ReviewerEnvelopeError",
    "ReviewerReturnCounter",
    "THIRD_RETURN_THRESHOLD",
    "build_envelope",
    "envelope_from_mapping",
    "validate_envelope",
]
