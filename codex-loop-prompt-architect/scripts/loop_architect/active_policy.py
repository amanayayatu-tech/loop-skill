"""Keep active prompt policy separate from retained historical evidence."""

from __future__ import annotations

import copy
from typing import Any


HISTORICAL_PROMPT_KEYS = frozenset(
    {
        "heartbeat_policy_history",
        "historical_evidence",
        "historical_heartbeat_policy",
        "historical_model_policy",
        "model_policy_history",
    }
)


def active_prompt_source(source: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(source, dict):
        raise TypeError("prompt source must be an object")

    def cleanse(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: cleanse(item)
                for key, item in value.items()
                if key not in HISTORICAL_PROMPT_KEYS
            }
        if isinstance(value, list):
            return [cleanse(item) for item in value]
        return copy.deepcopy(value)

    return cleanse(source)


def split_policy_evidence(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(source, dict):
        raise TypeError("policy source must be an object")

    def collect(value: Any) -> Any:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                if key in HISTORICAL_PROMPT_KEYS:
                    result[key] = copy.deepcopy(item)
                    continue
                nested = collect(item)
                if nested is not None:
                    result[key] = nested
            return result or None
        if isinstance(value, list):
            items = [collect(item) for item in value]
            return items if any(item is not None for item in items) else None
        return None

    return {
        "active_policy": active_prompt_source(source),
        "historical_evidence": collect(source) or {},
    }


__all__ = ["HISTORICAL_PROMPT_KEYS", "active_prompt_source", "split_policy_evidence"]
