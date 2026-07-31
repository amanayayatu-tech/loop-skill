"""Pure projections over canonical exports and capability observations.

These views are disposable: deleting them loses no canonical state and replaying
them from the same bytes returns the same digest.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any, Mapping, Sequence

from loop_architect.v4_alpha.protocol import canonical_bytes, domain_digest


class ProjectionError(Exception):
    pass


_RISK_RULES = (
    ("PRIVATE_KEY", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("GITHUB_TOKEN", re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("OPENAI_TOKEN", re.compile(rb"sk-[A-Za-z0-9]{20,}")),
    ("AWS_ACCESS_KEY", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("EMAIL_ADDRESS", re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
)


def _decode_export(value: bytes) -> dict[str, Any]:
    try:
        decoded = json.loads(value.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectionError("canonical export is invalid") from exc
    if not isinstance(decoded, dict) or canonical_bytes(decoded) != value:
        raise ProjectionError("canonical export is not canonical")
    return decoded


def status_projection(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    execution = snapshot.get("execution", {})
    effects = snapshot.get("external_effects", {})
    deliveries = snapshot.get("deliveries", {})
    uncertain = sum(
        item.get("state") in {"UNKNOWN", "UNVERIFIABLE"}
        for item in (*effects.values(), *deliveries.values())
    )
    state = execution.get("state")
    if state == "TERMINAL":
        progress = "Finished"
        result = execution.get("disposition") or "Unknown"
        next_action = None
    elif state == "PAUSED":
        progress = "Paused"
        result = "Pending"
        next_action = "Review the pause reason and choose whether to resume."
    elif uncertain:
        progress = "Needs attention"
        result = "Pending"
        next_action = "Wait for authoritative readback or close with a limitation."
    else:
        progress = "Active"
        result = "Pending"
        next_action = "Continue the displayed current Goal action."
    return {
        "progress": progress,
        "result": result,
        "limitations": (
            ["External state is UNKNOWN or UNVERIFIABLE."] if uncertain else []
        ),
        "next_action": next_action,
    }


def audit_index(export_bytes: bytes) -> dict[str, Any]:
    exported = _decode_export(export_bytes)
    entries: list[dict[str, Any]] = []
    previous = "0" * 64
    for operation in exported.get("operations", exported.get("accepted", [])):
        entry = {
            "accepted": operation.get("accepted", True),
            "loop_ref": operation.get("loop_ref"),
            "operation_id": operation.get("operation_id"),
            "request_digest": operation.get("request_digest"),
        }
        digest = domain_digest(
            "loopskill-audit-chain-v1\n", {"entry": entry, "previous": previous}
        )
        entries.append({**entry, "entry_digest": digest, "previous_digest": previous})
        previous = digest
    for rejection in exported.get("rejected", []):
        entry = {
            "accepted": False,
            "loop_ref": rejection.get("loop_ref"),
            "operation_id": rejection.get("operation_id"),
            "request_digest": rejection.get("request_digest"),
        }
        digest = domain_digest(
            "loopskill-audit-chain-v1\n", {"entry": entry, "previous": previous}
        )
        entries.append({**entry, "entry_digest": digest, "previous_digest": previous})
        previous = digest
    return {
        "artifact": "loopskill-v4-audit-index-v1",
        "entries": entries,
        "head_digest": previous,
        "rebuildable": True,
        "runtime_authority": False,
    }


def archive_manifest(export_bytes: bytes) -> dict[str, Any]:
    exported = _decode_export(export_bytes)
    snapshots = exported.get("loops", exported.get("snapshots", {}))
    events = exported.get("events", {})
    if isinstance(snapshots, list):
        loop_refs = sorted(
            item.get("loop_ref") for item in snapshots if isinstance(item, dict)
        )
    else:
        loop_refs = sorted(snapshots)
    event_count = (
        len(events)
        if isinstance(events, list)
        else sum(len(items) for items in events.values())
    )
    body = {
        "canonical_export_sha256": hashlib.sha256(export_bytes).hexdigest(),
        "event_count": event_count,
        "loop_count": len(loop_refs),
        "loop_ref_digests": [
            domain_digest("loopskill-archive-loop-ref-v1\n", loop_ref)
            for loop_ref in loop_refs
        ],
        "rebuildable": True,
        "runtime_authority": False,
    }
    return {
        "artifact": "loopskill-v4-archive-manifest-v1",
        **body,
        "manifest_digest": domain_digest("loopskill-archive-manifest-v1\n", body),
    }


def privacy_export(export_bytes: bytes) -> dict[str, Any]:
    exported = _decode_export(export_bytes)
    snapshots = exported.get("loops", exported.get("snapshots", {}))
    if isinstance(snapshots, list):
        snapshot_values = [item.get("snapshot", {}) for item in snapshots]
    else:
        snapshot_values = list(snapshots.values())
    execution_states = Counter(
        snapshot.get("execution", {}).get("state", "UNKNOWN")
        for snapshot in snapshot_values
    )
    assurance_states = Counter(
        snapshot.get("closure_assurance", {}).get("strength", "NONE")
        for snapshot in snapshot_values
    )
    operations = exported.get("operations", exported.get("accepted", []))
    accepted = sum(operation.get("accepted", True) is True for operation in operations)
    rejected = sum(operation.get("accepted") is False for operation in operations)
    rejected += len(exported.get("rejected", []))
    plans = []
    for snapshot in snapshot_values:
        plan = snapshot.get("goal_plan")
        if not isinstance(plan, Mapping):
            continue
        if plan.get("storage_mode") == "CONTENT_ADDRESSED_V1":
            plans.append(
                {
                    "active_index": plan.get("active_index"),
                    "capacity_contract_version": plan.get(
                        "capacity_contract_version"
                    ),
                    "goal_count": plan.get("goal_count"),
                    "order_digest": domain_digest(
                        "loopskill-public-plan-order-v1\n",
                        {
                            "goal_ids": list(plan.get("ordered_goal_ids", ())),
                            "slice_digests": list(
                                plan.get("ordered_goal_slice_digests", ())
                            ),
                        },
                    ),
                    "plan_digest": plan.get("plan_digest"),
                    "plan_index_digest": plan.get("plan_index_digest"),
                    "revision": plan.get("revision"),
                    "schema": "loopskill-plan-v1",
                    "storage_mode": "CONTENT_ADDRESSED_V1",
                }
            )
    body = {
        "accepted_operation_count": accepted,
        "assurance_counts": dict(sorted(assurance_states.items())),
        "canonical_export_digest": hashlib.sha256(export_bytes).hexdigest(),
        "execution_state_counts": dict(sorted(execution_states.items())),
        "loop_count": len(snapshot_values),
        "plans": sorted(plans, key=lambda item: str(item["plan_digest"])),
        "rejected_operation_count": rejected,
    }
    return {
        "artifact": "loopskill-v4-privacy-aggregate-v1",
        **body,
        "aggregate_digest": domain_digest("loopskill-privacy-aggregate-v1\n", body),
        "excluded": [
            "prompt",
            "chat",
            "task_identity",
            "thread_identity",
            "filesystem_path",
            "personal_data",
            "credential",
            "raw_log",
        ],
    }


def risk_scan(artifacts: Mapping[str, bytes]) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    for location, content in sorted(artifacts.items()):
        if not isinstance(location, str) or not isinstance(content, bytes):
            raise ProjectionError("risk scan input is invalid")
        for rule_id, pattern in _RISK_RULES:
            for match in pattern.finditer(content):
                findings.append(
                    {
                        "artifact_digest": hashlib.sha256(content).hexdigest(),
                        "finding_digest": hashlib.sha256(match.group(0)).hexdigest(),
                        "location_digest": domain_digest(
                            "loopskill-risk-location-v1\n", location
                        ),
                        "rule_id": rule_id,
                    }
                )
    return {
        "artifact": "loopskill-v4-risk-scan-v1",
        "finding_count": len(findings),
        "findings": findings,
        "raw_values_included": False,
    }


def metrics_projection(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    names = (
        "host_interactions",
        "protocol_calls",
        "local_writes",
        "latency_ns",
        "unknown_count",
        "repair_count",
        "human_interventions",
    )
    totals: dict[str, int | str] = {}
    for name in names:
        values = [sample.get(name) for sample in samples if name in sample]
        if not values:
            totals[name] = "UNMETERED"
        elif any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
            raise ProjectionError("invalid metric sample")
        else:
            totals[name] = sum(values)
    return {
        "artifact": "loopskill-v4-metrics-projection-v1",
        "sample_count": len(samples),
        "totals": totals,
        "routing_authority": False,
    }


def doctor_projection(
    *,
    source_identity: str,
    installed_identity: str | None,
    capabilities: Mapping[str, str],
    diagnostics: bool = False,
) -> dict[str, Any]:
    drift = installed_identity is not None and installed_identity != source_identity
    blockers = sorted(
        name
        for name, status in capabilities.items()
        if status not in {"AVAILABLE", "UNAVAILABLE", "UNVERIFIABLE"}
    )
    status = "BLOCKED" if drift or blockers else "READY"
    result: dict[str, Any] = {
        "status": status,
        "blockers": (
            (["source/install identity drift"] if drift else [])
            + [f"invalid capability observation: {name}" for name in blockers]
        ),
        "next_action": (
            "Inspect diagnostics and repair the isolated installation."
            if status == "BLOCKED"
            else "Continue with the displayed capability limitations."
        ),
    }
    if diagnostics:
        result["diagnostics"] = {
            "capabilities": dict(sorted(capabilities.items())),
            "installed_identity": installed_identity,
            "source_identity": source_identity,
        }
    return result
