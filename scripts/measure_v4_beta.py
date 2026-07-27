#!/usr/bin/env python3
"""Freeze the exact v3 baseline, then evaluate a separately produced v4 receipt.

This is build-time measurement code.  It is not a runtime writer, policy,
adapter, recovery process, or source of protocol authority.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIO = ROOT / "tests" / "fixtures" / "v4_beta" / "same-scenario.json"
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024


class MeasurementFailure(Exception):
    pass


def _strict_json(path: Path) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise MeasurementFailure(f"non-finite JSON value: {value}")

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise MeasurementFailure(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8", "strict")
        value = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
            parse_float=lambda _: (_ for _ in ()).throw(
                MeasurementFailure("floating-point JSON values are forbidden")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MeasurementFailure(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise MeasurementFailure(f"expected JSON object: {path}")
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _run(*command: str, cwd: Path = ROOT) -> bytes:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise MeasurementFailure("command failed: " + " ".join(command)) from exc


def _safe_extract(archive: bytes, destination: Path) -> None:
    if len(archive) > MAX_ARCHIVE_BYTES:
        raise MeasurementFailure("v3 archive exceeds measurement bound")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        members = bundle.getmembers()
        for member in members:
            relative = Path(member.name)
            if relative.is_absolute() or ".." in relative.parts:
                raise MeasurementFailure("unsafe path in v3 archive")
            if member.issym() or member.islnk() or member.isdev():
                raise MeasurementFailure("unsupported entry in v3 archive")
        bundle.extractall(destination, members=members)


def freeze_v3(scenario_path: Path) -> dict[str, Any]:
    scenario = _strict_json(scenario_path)
    if scenario.get("schema_version") != "loopskill-v4-beta-same-scenario-v1":
        raise MeasurementFailure("scenario schema drift")
    v3 = scenario.get("v3")
    thresholds = scenario.get("thresholds")
    if not isinstance(v3, dict) or not isinstance(thresholds, dict):
        raise MeasurementFailure("scenario baseline fields missing")
    commit = str(v3.get("source_commit", ""))
    tag = str(v3.get("source_tag", ""))
    resolved = _run("git", "rev-parse", f"{tag}^{{commit}}").decode("ascii").strip()
    if resolved != commit:
        raise MeasurementFailure("v3 tag/commit drift")
    archive = _run("git", "archive", commit)
    with tempfile.TemporaryDirectory(prefix="loopskill-v3-baseline-") as temporary:
        checkout = Path(temporary)
        _safe_extract(archive, checkout)
        source = checkout / str(v3["input_path"])
        generator = checkout / str(v3["generator_path"])
        pack = checkout / "baseline-controller-pack.md"
        guide = checkout / "baseline-usage.md"
        _run(
            sys.executable,
            str(generator),
            "--input",
            str(v3["input_path"]),
            "--mode",
            str(v3["mode"]),
            "--controller-pack-output",
            pack.name,
            "--user-guide-output",
            guide.name,
            cwd=checkout,
        )
        pack_bytes = pack.read_bytes()
        guide_bytes = guide.read_bytes()
        source_bytes = source.read_bytes()
    interactions = v3.get("internal_control_interactions")
    if not isinstance(interactions, list) or not interactions:
        raise MeasurementFailure("v3 interaction ledger missing")
    ids: set[str] = set()
    for item in interactions:
        if not isinstance(item, dict) or set(item) != {
            "id",
            "kind",
            "marker",
            "description",
        }:
            raise MeasurementFailure("v3 interaction entry shape drift")
        identity = item["id"]
        marker = item["marker"]
        if not isinstance(identity, str) or identity in ids:
            raise MeasurementFailure("duplicate v3 interaction identity")
        if not isinstance(marker, str) or marker.encode("utf-8") not in pack_bytes:
            raise MeasurementFailure(f"v3 interaction marker absent: {identity}")
        ids.add(identity)
    baseline_count = len(interactions)
    reduction_numerator = thresholds.get(
        "internal_control_interaction_reduction_min_numerator"
    )
    reduction_denominator = thresholds.get(
        "internal_control_interaction_reduction_min_denominator"
    )
    pack_limit = thresholds.get("pack_bytes_max")
    if (
        reduction_numerator != 1
        or reduction_denominator != 2
        or pack_limit != 32768
    ):
        raise MeasurementFailure("author-approved candidate threshold drift")
    maximum_v4_interactions = (
        baseline_count * (reduction_denominator - reduction_numerator)
    ) // reduction_denominator
    return {
        "artifact": "loopskill-v4-p7-v3-baseline-v1",
        "status": "BASELINE_FROZEN_PRE_V4_COMPARISON",
        "scenario_id": scenario["scenario_id"],
        "scenario_sha256": _sha256_bytes(_canonical(scenario)),
        "measurement_code_sha256": _sha256_file(Path(__file__)),
        "v3_source_tag": tag,
        "v3_source_commit": commit,
        "v3_input_path": v3["input_path"],
        "v3_input_bytes": len(source_bytes),
        "v3_input_sha256": _sha256_bytes(source_bytes),
        "v3_pack_bytes": len(pack_bytes),
        "v3_pack_sha256": _sha256_bytes(pack_bytes),
        "v3_guide_bytes": len(guide_bytes),
        "v3_guide_sha256": _sha256_bytes(guide_bytes),
        "v3_user_start_actions": v3["user_start_actions"],
        "v3_authorization_confirmations": v3["authorization_confirmations"],
        "v3_internal_control_interactions": baseline_count,
        "v3_interaction_ids": [item["id"] for item in interactions],
        "counting_boundary": scenario["counting_boundary"],
        "blocking_thresholds": {
            "v4_pack_bytes_max": pack_limit,
            "v4_internal_control_interactions_max": maximum_v4_interactions,
            "internal_control_interaction_reduction_min": "1/2",
        },
        "prior_v4_diagnostic_disclosure": "P5.1 recorded a nonblocking default-path diagnostic before this freeze; the two threshold values were author-fixed before both that diagnostic and this P7 comparison, and no P7 v4 comparison receipt has been consumed.",
        "real_external_effects": 0,
    }


def compare_v4(
    scenario_path: Path, baseline_path: Path, receipt_path: Path
) -> dict[str, Any]:
    scenario = _strict_json(scenario_path)
    baseline = _strict_json(baseline_path)
    receipt = _strict_json(receipt_path)
    scenario_digest = _sha256_bytes(_canonical(scenario))
    code_digest = _sha256_file(Path(__file__))
    if (
        baseline.get("status") != "BASELINE_FROZEN_PRE_V4_COMPARISON"
        or baseline.get("scenario_sha256") != scenario_digest
        or baseline.get("measurement_code_sha256") != code_digest
    ):
        raise MeasurementFailure("baseline identity drift")
    if (
        receipt.get("artifact") != "loopskill-v4-p7-comparison-input-v1"
        or receipt.get("scenario_sha256") != scenario_digest
        or receipt.get("measurement_code_sha256") != code_digest
    ):
        raise MeasurementFailure("v4 comparison receipt identity drift")
    metrics = receipt.get("metrics")
    if not isinstance(metrics, dict):
        raise MeasurementFailure("v4 comparison metrics missing")
    required = {
        "pack_bytes",
        "internal_control_interactions",
        "user_start_actions",
        "authorization_confirmations",
        "host_interactions",
        "protocol_calls",
        "local_writes",
        "latency_ns",
        "unknown_count",
        "human_interventions",
    }
    if set(metrics) != required or any(
        isinstance(metrics[key], bool)
        or not isinstance(metrics[key], int)
        or metrics[key] < 0
        for key in required
    ):
        raise MeasurementFailure("v4 comparison metric shape drift")
    thresholds = baseline["blocking_thresholds"]
    pack_pass = metrics["pack_bytes"] <= thresholds["v4_pack_bytes_max"]
    interaction_pass = (
        metrics["internal_control_interactions"]
        <= thresholds["v4_internal_control_interactions_max"]
    )
    return {
        "artifact": "loopskill-v4-p7-comparison-result-v1",
        "status": "PASS" if pack_pass and interaction_pass else "FAIL",
        "scenario_sha256": scenario_digest,
        "measurement_code_sha256": code_digest,
        "baseline_sha256": _sha256_bytes(_canonical(baseline)),
        "v4_receipt_sha256": _sha256_bytes(_canonical(receipt)),
        "metrics": metrics,
        "thresholds": thresholds,
        "pack_gate": "PASS" if pack_pass else "FAIL",
        "internal_control_interaction_gate": (
            "PASS" if interaction_pass else "FAIL"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("freeze-v3")
    compare = subcommands.add_parser("compare-v4")
    compare.add_argument("--baseline", type=Path, required=True)
    compare.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "freeze-v3":
            result = freeze_v3(args.scenario)
        else:
            result = compare_v4(args.scenario, args.baseline, args.receipt)
    except MeasurementFailure as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
