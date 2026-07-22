"""Lightweight derived audit index, per-Goal summaries, and timeline."""

from __future__ import annotations

import hashlib
import json
from typing import Any


BUSINESS_ROUTE_KINDS = {
    "WORKER",
    "CODE_REVIEW",
    "ROADMAP_AUDIT",
    "FINAL_AUDIT",
    "LOCAL_VERIFICATION",
}


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def build_audit_views(state: dict[str, Any]) -> dict[str, bytes]:
    routes = list(state.get("gateway_route_ledger", {}).values())
    business_routes = [
        route for route in routes if route.get("route_kind") in BUSINESS_ROUTE_KINDS
    ]
    control_mutations = max(0, len(state.get("event_ledger", {})) - len(business_routes))
    goal_summaries: dict[str, dict[str, Any]] = {}
    for goal_id, ledger in sorted(state.get("goal_execution_ledger", {}).items()):
        matching = [route for route in business_routes if route.get("goal_id") == goal_id]
        goal_summaries[goal_id] = {
            "achieved_completion_class": ledger.get("achieved_completion_class"),
            "attempt_count": len(ledger.get("attempts", [])),
            "required_completion_class": ledger.get("required_completion_class"),
            "route_count": len(matching),
            "status": ledger.get("status"),
        }
    timeline = [
        {
            "acked_at": route.get("acked_at"),
            "goal_id": route.get("goal_id"),
            "prepared_at": route.get("prepared_at"),
            "route_id": route.get("route_id"),
            "route_kind": route.get("route_kind"),
            "sent_at": route.get("sent_at"),
            "status": route.get("status"),
        }
        for route in sorted(
            business_routes,
            key=lambda item: (item.get("prepared_at") or "", item.get("route_id") or ""),
        )
    ]
    summaries_payload = {
        "derived_from_state_version": state.get("state_version"),
        "goals": goal_summaries,
        "schema_version": "loop-goal-summaries-v1",
    }
    timeline_payload = {
        "derived_from_state_version": state.get("state_version"),
        "entries": timeline,
        "schema_version": "loop-business-timeline-v1",
    }
    summary_bytes = canonical_bytes(summaries_payload)
    timeline_bytes = canonical_bytes(timeline_payload)
    index_payload = {
        "business_progress": {
            "goal_count": len(goal_summaries),
            "route_count": len(business_routes),
        },
        "control_plane": {
            "event_count": len(state.get("event_ledger", {})),
            "mutation_count": control_mutations,
        },
        "derived_from_state_version": state.get("state_version"),
        "schema_version": "loop-audit-index-v1",
        "views": {
            "business_timeline": {
                "digest": "sha256:" + hashlib.sha256(timeline_bytes).hexdigest(),
                "path": ".codex-loop/business-timeline.json",
            },
            "goal_summaries": {
                "digest": "sha256:" + hashlib.sha256(summary_bytes).hexdigest(),
                "path": ".codex-loop/goal-summaries.json",
            },
        },
    }
    return {
        "audit-index.json": canonical_bytes(index_payload),
        "business-timeline.json": timeline_bytes,
        "goal-summaries.json": summary_bytes,
    }


__all__ = ["BUSINESS_ROUTE_KINDS", "build_audit_views", "canonical_bytes"]
