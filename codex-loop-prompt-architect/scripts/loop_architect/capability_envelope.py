"""Supervisor and host capability envelope (P1-9).

A capability envelope is the structured replacement for the long
natural-language authorization paragraphs that currently live in the
heartbeat prompt. Each capability is one ``(name, scope, action,
constraint)`` tuple; an envelope is the ordered set of capabilities
plus an explicit allow/deny decision for a given operation.

The envelope is content-addressed and JSON-stable, so a future
runtime can compare a Supervisor's effective capabilities against the
caller's request without parsing free-form text.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

#: Names of the host capabilities the canary contract requires
#: (``P0-8``). Mirrored here so the runtime can compare a live
#: envelope against the contract without a second source of truth.
REQUIRED_HOST_CAPABILITIES: tuple[str, ...] = (
    "host.install",
    "host.server_restart",
    "host.client_reconnect",
    "host.schema_refresh",
    "host.app_refresh",
    "host.closeout.prepare",
    "host.closeout.ack",
    "host.action_receipt",
)

#: Operations the envelope is allowed to authorize. Anything outside
#: this set is rejected at envelope-construction time.
ALLOWED_OPERATIONS: frozenset[str] = frozenset(
    {
        "canary.run",
        "loop.initialize",
        "loop.finalize",
        "loop.heartbeat_register",
        "loop.heartbeat_pause",
        "loop.heartbeat_resume",
        "loop.review",
        "loop.repair",
        "loop.closeout",
        "policy.migrate",
    }
)

#: Conservative name pattern for a capability.
_CAPABILITY_NAME_RE = re.compile(r"^[a-z][a-z0-9._]{2,63}$")


class CapabilityEnvelopeError(ValueError):
    """Raised on invalid envelopes, scope mismatches, or denials."""


@dataclass(frozen=True)
class Capability:
    name: str
    scope: str
    action: str
    constraint: str

    def __post_init__(self) -> None:
        if not _CAPABILITY_NAME_RE.match(self.name):
            raise CapabilityEnvelopeError(
                f"capability name {self.name!r} invalid"
            )
        if not self.scope:
            raise CapabilityEnvelopeError(
                f"capability {self.name!r} scope is required"
            )
        if not self.action:
            raise CapabilityEnvelopeError(
                f"capability {self.name!r} action is required"
            )
        if self.action not in ALLOWED_OPERATIONS:
            raise CapabilityEnvelopeError(
                f"capability {self.name!r} action {self.action!r} not in "
                f"{sorted(ALLOWED_OPERATIONS)}"
            )
        if not self.constraint:
            raise CapabilityEnvelopeError(
                f"capability {self.name!r} constraint is required"
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "scope": self.scope,
            "action": self.action,
            "constraint": self.constraint,
        }


@dataclass(frozen=True)
class CapabilityEnvelope:
    """The structured authorization for a Supervisor or host turn.

    The envelope is immutable: any change produces a new envelope with
    a new digest. The runtime reads the envelope once per turn and
    never invents capabilities not present in the envelope.
    """

    owner: str
    role: str
    capabilities: tuple[Capability, ...]
    denials: tuple[str, ...] = ()
    issued_at: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if not self.owner:
            raise CapabilityEnvelopeError("owner is required")
        if not self.role:
            raise CapabilityEnvelopeError("role is required")
        for capability in self.capabilities:
            if capability.action not in ALLOWED_OPERATIONS:
                raise CapabilityEnvelopeError(
                    f"capability {capability.name!r} action "
                    f"{capability.action!r} not in {sorted(ALLOWED_OPERATIONS)}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "role": self.role,
            "capabilities": [capability.to_dict() for capability in self.capabilities],
            "denials": list(self.denials),
            "issued_at": self.issued_at,
            "note": self.note,
        }

    def digest(self) -> str:
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def has_capability(
        self, capability_name: str, *, scope_prefix: str | None = None
    ) -> bool:
        for capability in self.capabilities:
            if capability.name != capability_name:
                continue
            if scope_prefix and not capability.scope.startswith(scope_prefix):
                continue
            return True
        return False

    def authorize(self, operation: str, *, scope_prefix: str | None = None) -> bool:
        """Return True when the envelope authorizes ``operation``."""
        if operation in self.denials:
            return False
        for capability in self.capabilities:
            if capability.action != operation:
                continue
            if scope_prefix and not capability.scope.startswith(scope_prefix):
                continue
            return True
        return False

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CapabilityEnvelope":
        if not isinstance(payload, Mapping):
            raise CapabilityEnvelopeError("envelope payload must be a mapping")
        capabilities = tuple(
            Capability(
                name=str(entry["name"]),
                scope=str(entry["scope"]),
                action=str(entry["action"]),
                constraint=str(entry["constraint"]),
            )
            for entry in payload.get("capabilities", ())
        )
        return cls(
            owner=str(payload.get("owner", "")),
            role=str(payload.get("role", "")),
            capabilities=capabilities,
            denials=tuple(str(value) for value in payload.get("denials", ())),
            issued_at=str(payload.get("issued_at", "")),
            note=str(payload.get("note", "")),
        )


def write_envelope(path: Path, envelope: CapabilityEnvelope) -> None:
    """Persist ``envelope`` to ``path`` in JSON-stable form."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = envelope.to_dict()
    payload["digest"] = envelope.digest()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    import os as _os
    _os.replace(tmp, path)


def diff_envelopes(
    before: CapabilityEnvelope, after: CapabilityEnvelope
) -> dict[str, Any]:
    """Return a JSON-stable diff between two envelopes.

    The diff is the canonical input to a "show effective config"
    display; the diff never includes the capability constraints
    verbatim, only their stable hash, so a diff logged at WARNING
    level does not leak the exact authorization text.
    """
    before_names = {capability.name for capability in before.capabilities}
    after_names = {capability.name for capability in after.capabilities}
    return {
        "added": sorted(after_names - before_names),
        "removed": sorted(before_names - after_names),
        "before_digest": before.digest(),
        "after_digest": after.digest(),
        "denials_added": sorted(set(after.denials) - set(before.denials)),
        "denials_removed": sorted(set(before.denials) - set(after.denials)),
    }


def required_host_envelope(
    owner: str = "codex-app", role: str = "host"
) -> CapabilityEnvelope:
    """Return the canonical host capability envelope.

    Every capability corresponds to one item on the canary contract's
    host capability inventory. The envelope is the same object the
    formal initialization gate compares the live App readback against.
    """
    capabilities = (
        Capability(
            name=capability_name,
            scope="mcp:codex-loop-state",
            action="canary.run",
            constraint="active_call_count_excluding_readback==0",
        )
        for capability_name in REQUIRED_HOST_CAPABILITIES
    )
    return CapabilityEnvelope(
        owner=owner,
        role=role,
        capabilities=tuple(capabilities),
        denials=("loop.push", "loop.merge", "loop.release"),
    )


__all__ = [
    "ALLOWED_OPERATIONS",
    "Capability",
    "CapabilityEnvelope",
    "CapabilityEnvelopeError",
    "REQUIRED_HOST_CAPABILITIES",
    "diff_envelopes",
    "required_host_envelope",
    "write_envelope",
]
