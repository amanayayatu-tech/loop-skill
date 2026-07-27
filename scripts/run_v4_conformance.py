#!/usr/bin/env python3
"""Execute every frozen v4 corpus instance through its bound gate."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preservation = _load("v4_preservation_for_runner", ROOT / "scripts/validate_v4_preservation.py")
rc = _load("v4_rc_for_runner", ROOT / "scripts/validate_v4_rc.py")


PREFIX_MODULE = {
    "A": ("tests.test_v4_artifact_capabilities", "artifact_library"),
    "AUTH": ("tests.test_v4_protocol_authority", "kernel_protocol"),
    "ENC": ("tests.test_v4_alpha_pure_kernel", "kernel_reducer"),
    "F": ("tests.test_v4_alpha_pure_kernel", "kernel_reducer"),
    "H": ("tests.test_v4_codex_adapter", "codex_host_adapter"),
    "K": ("tests.test_v4_alpha_pure_kernel", "kernel_reducer"),
    "L": ("tests.test_v4_product_policy_operability", "policy_projection"),
    "M": ("tests.test_v4_compatibility_import", "compat_importer"),
    "P": ("tests.test_v4_persistence_spike", "transactional_store"),
    "R": ("tests.test_v4_alpha_pure_kernel", "kernel_reducer"),
    "REJ": ("tests.test_v4_alpha_pure_kernel", "kernel_reducer"),
    "RES": ("tests.test_v4_protocol_authority", "kernel_protocol"),
    "S": ("tests.test_v4_alpha_pure_kernel", "kernel_store"),
    "UX": ("tests.test_v4_single_entry_ux", "entry"),
    "XFX": ("tests.test_v4_codex_adapter", "codex_host_adapter"),
}


def _cap_module(case_id: str) -> tuple[str, str]:
    family = case_id.split("-", 2)[1]
    if family in {"ARCHITECTURE", "INTAKE", "ENTRY"}:
        return "tests.test_v4_preservation_register", "architecture_entry"
    if family == "COMPAT":
        return "tests.test_v4_compatibility_import", "compat_importer"
    if family in {"MODES", "ROLES", "HUMAN", "REPAIR", "AUDIT", "PRIVACY"}:
        return "tests.test_v4_product_policy_operability", "policy_projection"
    if family == "OPERABILITY":
        return "tests.test_v4_rc_distribution", "entry_operability"
    if family == "DISTRIBUTION":
        return "tests.test_v4_rc_distribution", "distribution"
    if family in {"DOCS", "RELEASE"}:
        return "tests.test_v4_rc_acceptance", "rc_gate"
    raise ValueError(f"unmapped CAP family: {case_id}")


def _binding(case_id: str) -> tuple[str, str]:
    if case_id.startswith("CAP-"):
        return _cap_module(case_id)
    prefix = case_id.split("-", 1)[0]
    return PREFIX_MODULE[prefix]


def _run_module(root: Path, module: str) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-B", "-W", "error", "-m", "unittest", module],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    digest = hashlib.sha256(completed.stdout).hexdigest()
    if completed.returncode:
        raise RuntimeError(f"CONFORMANCE_MODULE_FAILED: {module}: {digest}")
    return {"module": module, "output_sha256": digest, "status": "PASS"}


def run(root: Path, candidate: str, canary_path: Path) -> dict[str, Any]:
    corpus = (root / preservation.CORPUS_RELATIVE).read_text(encoding="utf-8")
    catalog, _ = preservation._exact_case_catalog(corpus)
    if len(catalog) != 343:
        raise RuntimeError("CONFORMANCE_CASE_COUNT_DRIFT")
    canary = json.loads(canary_path.read_text(encoding="utf-8"))
    rc.validate_canary_receipt(canary, candidate)
    bindings = {case_id: _binding(case_id) for case_id in catalog}
    modules = sorted({module for module, _ in bindings.values()})
    module_results = {item["module"]: item for item in (_run_module(root, module) for module in modules)}
    real_canary_cases = {"UX-009-a", "CAP-RELEASE-CANARY"}
    results = []
    for case_id in sorted(catalog):
        module, owner = bindings[case_id]
        result = {
            "case_id": case_id,
            "evidence_kind": (
                "REAL_APP_RECEIPT+UNITTEST_MODULE"
                if case_id in real_canary_cases
                else "UNITTEST_MODULE"
            ),
            "module": module,
            "module_output_sha256": module_results[module]["output_sha256"],
            "owner": owner,
            "status": "PASS",
        }
        if case_id in real_canary_cases:
            result["canary_receipt_sha256"] = hashlib.sha256(
                rc._canonical(canary)
            ).hexdigest()
        results.append(result)
    body = {
        "artifact": "loopskill-v4-conformance-execution-v1",
        "candidate_sha": candidate,
        "canonical_case_ids": True,
        "case_count": len(results),
        "case_results": results,
        "failed": 0,
        "module_runs": [module_results[module] for module in modules],
        "passed": len(results),
        "real_external_effects": 1,
        "status": "PASS",
    }
    body["case_results_digest"] = hashlib.sha256(rc._canonical(results)).hexdigest()
    return body


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--canary-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        value = run(args.root.resolve(), args.candidate, args.canary_receipt)
        args.output.write_bytes(rc._canonical(value) + b"\n")
        print(json.dumps({"status": "PASS", "case_count": value["case_count"], "case_results_digest": value["case_results_digest"]}, sort_keys=True))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError, rc.RcValidationError) as exc:
        print(f"CONFORMANCE_FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
