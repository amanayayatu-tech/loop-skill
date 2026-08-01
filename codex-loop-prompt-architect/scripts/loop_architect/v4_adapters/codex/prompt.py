"""One deterministic Codex Host prompt materializer for PREPARE and invoke."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from loop_architect.v4_alpha.generated_protocol import CAPACITY_CONTRACT
from loop_architect.v4_alpha.protocol import canonical_bytes


LEGACY_PAYLOAD_FIELDS = frozenset(
    {
        "acceptance_criteria",
        "authorization_boundaries",
        "budget",
        "execution_mode",
        "external_actions",
        "goal",
        "stop_conditions",
        "target_ref",
        "write_scope",
    }
)
CONTENT_PAYLOAD_FIELDS = LEGACY_PAYLOAD_FIELDS | {
    "artifact_digest",
    "goal_id",
    "prior_disposition",
    "workspace_digest",
}
V2_CONTENT_PAYLOAD_FIELDS = CONTENT_PAYLOAD_FIELDS | {
    "capabilities",
    "goal_policy",
    "requirements",
    "verifiers",
    "worker_profile",
}
MAX_PROMPT_BYTES = int(CAPACITY_CONTRACT["host_prompt_hard_bytes"])
TARGET_PROMPT_BYTES = int(CAPACITY_CONTRACT["host_prompt_target_bytes"])


class PromptMaterializationError(ValueError):
    pass


def materialize_prompt(payload: Mapping[str, Any], operation_id: str) -> str:
    fields = set(payload)
    if fields not in {
        LEGACY_PAYLOAD_FIELDS,
        CONTENT_PAYLOAD_FIELDS,
        V2_CONTENT_PAYLOAD_FIELDS,
    }:
        raise PromptMaterializationError("provider payload shape drift")
    request_marker = hashlib.sha256(
        b"loopskill-codex-exec-request-v1\n" + operation_id.encode("utf-8")
    ).hexdigest()
    document = {key: payload[key] for key in sorted(fields - {"target_ref"})}
    prompt = (
        "LoopSkill 4.2 machine-started foreground task. Treat the following JSON as "
        "the confirmed semantic boundary; do not broaden it. The request marker is "
        "correlation-only and grants no authority.\n"
        f"LOOPSKILL4_REQUEST={request_marker}\n"
        + canonical_bytes(document).decode("utf-8")
        + "\nReturn one concise semantic result according to the evidence. The "
        "machine-supplied output schema is authoritative. Do not include control "
        "identities."
    )
    if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise PromptMaterializationError("confirmed request exceeds hard prompt limit")
    return prompt


def prompt_bytes(payload: Mapping[str, Any], operation_id: str) -> int:
    return len(materialize_prompt(payload, operation_id).encode("utf-8"))
