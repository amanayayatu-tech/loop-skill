"""Adaptive runtime forecast helpers."""

from __future__ import annotations

import json
import re
from typing import Any


def duration_minutes(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    text = value.lower().strip()
    match = re.search(
        r"(?:max(?:imum)?\s*[:=]?\s*)?(\d+(?:\.\d+)?)\s*"
        r"(minutes?|mins?|分钟|hours?|hrs?|小时|天|days?)",
        text,
    )
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2)
    if unit in {"天", "day", "days"}:
        return amount * 24 * 60
    if unit in {"hour", "hours", "hr", "hrs", "小时"}:
        return amount * 60
    return amount


def _duration_hours(value: Any) -> float | None:
    minutes = duration_minutes(value)
    return None if minutes is None else minutes / 60


def dashboard_required(data: dict[str, Any], milestone_count: int) -> bool:
    policy = data.get("dashboard_policy", "auto")
    if policy == "required":
        return True
    if policy == "disabled":
        return False
    if milestone_count > 3:
        return True
    hours = _duration_hours(data.get("time_max"))
    threshold = data.get("dashboard_threshold_hours", 12)
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold <= 0:
        threshold = 12
    return hours is not None and hours > threshold


def estimate_confidence(data: dict[str, Any]) -> str:
    explicit = all(data.get(key) for key in ("time_min", "time_typical", "time_max"))
    blockers = data.get("runtime_blockers")
    if explicit and blockers:
        return "MEDIUM"
    return "LOW"


def local_verifier_needed(data: dict[str, Any]) -> bool:
    policy = data.get("local_verification_policy", "not_required")
    if policy == "required":
        return True
    if policy == "not_required":
        return False
    text = json.dumps(
        {
            key: data.get(key)
            for key in ("objective", "acceptance_criteria", "milestones", "connectors", "runtime_blockers")
        },
        ensure_ascii=False,
    ).lower()
    phrases = (
        "authenticated browser",
        "browser verification",
        "browser smoke",
        "chrome extension",
        "macos permission",
        "xcode",
        "simulator",
        "physical device",
        "real device",
        "local hardware",
        "camera permission",
        "bluetooth",
        "真实浏览器",
        "本机权限",
        "浏览器验证",
        "浏览器 smoke",
        "真机",
        "模拟器",
        "本地硬件",
    )
    return any(phrase in text for phrase in phrases)
