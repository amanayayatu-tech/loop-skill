"""Independent, artifact-bound local verification for explicit safe criteria."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from loop_architect.v4_alpha.protocol import domain_digest

from .capture import ArtifactCapture
from .paths import ArtifactCaptureError, normalize_relative_path


_SHA256_RE = re.compile(r"^file-sha256:([^=]+)=([0-9a-f]{64})$")


@dataclass(frozen=True)
class LocalVerification:
    state: str
    evidence_digest: str
    checked_criteria: tuple[str, ...]
    reason: str


def verify_artifact(
    store: Any,
    capture: ArtifactCapture,
    acceptance_criteria: Sequence[str],
) -> LocalVerification:
    """Verify only declared, deterministic local facts; prose stays UNVERIFIABLE."""
    if store.get_blob(capture.bundle_blob_digest) is None:
        raise ArtifactCaptureError(
            "ARTIFACT_IDENTITY_MISMATCH", "artifact bundle blob is absent"
        )
    entries = {str(item["path"]): item for item in capture.manifest}
    checked: list[str] = []
    failures: list[str] = []
    unsupported: list[str] = []
    for raw in acceptance_criteria:
        criterion = raw.strip()
        if criterion == "artifact-changed":
            checked.append(criterion)
            if capture.empty:
                failures.append(criterion)
            continue
        if criterion == "no-file-change":
            checked.append(criterion)
            if not capture.empty:
                failures.append(criterion)
            continue
        if criterion.startswith("file-exists:"):
            try:
                path = normalize_relative_path(criterion[len("file-exists:") :])
            except ArtifactCaptureError:
                failures.append(criterion)
                continue
            checked.append(criterion)
            item = entries.get(path)
            if item is None or item.get("after_digest") is None:
                failures.append(criterion)
            continue
        match = _SHA256_RE.fullmatch(criterion)
        if match:
            try:
                path = normalize_relative_path(match.group(1))
            except ArtifactCaptureError:
                failures.append(criterion)
                continue
            checked.append(criterion)
            item = entries.get(path)
            blob_digest = None if item is None else item.get("after_digest")
            blob = None if not isinstance(blob_digest, str) else store.get_blob(blob_digest)
            if blob is None or hashlib.sha256(blob).hexdigest() != match.group(2):
                failures.append(criterion)
            continue
        unsupported.append(criterion)
    if failures:
        state = "FAILED"
        reason = "One or more explicit local artifact criteria failed."
    elif unsupported or not checked:
        state = "UNVERIFIABLE"
        reason = "The acceptance criteria require an independent verifier not available locally."
    else:
        state = "VERIFIED"
        reason = "All explicit local artifact criteria were verified."
    evidence: Mapping[str, Any] = {
        "artifact_digest": capture.artifact_digest,
        "checked_criteria": checked,
        "failed_criteria": failures,
        "state": state,
        "unsupported_count": len(unsupported),
    }
    return LocalVerification(
        state=state,
        evidence_digest=domain_digest("loopskill-local-verification-v1\n", evidence),
        checked_criteria=tuple(checked),
        reason=reason,
    )
