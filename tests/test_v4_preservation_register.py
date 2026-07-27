from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "scripts" / "validate_v4_preservation.py"
SPEC = importlib.util.spec_from_file_location("validate_v4_preservation", VALIDATOR_PATH)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class V4PreservationRegisterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = json.loads(
            (ROOT / validator.REGISTRY_RELATIVE).read_text(encoding="utf-8")
        )
        cls.inventories, cls.required_items = validator._inventory(
            ROOT, cls.registry
        )
        validator._validate_declared_surfaces(
            ROOT, cls.registry, cls.required_items
        )
        validator._validate_error_ownership(
            cls.registry, cls.inventories["errors"], cls.required_items
        )

    def test_full_register_validator_passes(self) -> None:
        result = validator.validate(ROOT)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["capability_count"], 24)
        self.assertEqual(result["mapped_required_items"], 1766)
        self.assertEqual(result["corpus_family_count"], 101)
        self.assertEqual(result["corpus_instance_count"], 343)
        self.assertEqual(result["preservation_family_count"], 15)
        self.assertEqual(result["preservation_case_binding_count"], 317)

    def test_exact_case_catalog_is_frozen(self) -> None:
        corpus = (ROOT / validator.CORPUS_RELATIVE).read_text(encoding="utf-8")
        exact, _ = validator._exact_case_catalog(corpus)
        self.assertEqual(len(exact), 343)
        self.assertEqual(
            validator._domain_digest(
                b"loopskill.v4.corpus.exact-case-catalog.v1\0", sorted(exact)
            ),
            validator.EXACT_CASE_CATALOG_SHA256,
        )

    def test_bogus_case_suffix_fails_closed(self) -> None:
        registry = copy.deepcopy(self.registry)
        owner = "PRES-KERNEL"
        old_case = "K-002-b"
        bogus_case = "K-002-z-does-not-exist"
        registry["capability_case_bindings"][owner] = [
            bogus_case if case_id == old_case else case_id
            for case_id in registry["capability_case_bindings"][owner]
        ]
        capability = next(
            item for item in registry["capabilities"] if item["capability_id"] == owner
        )
        capability["acceptance_case_ids"] = [
            bogus_case if case_id == old_case else case_id
            for case_id in capability["acceptance_case_ids"]
        ]
        for claim in registry["capability_acceptance_requirements"][owner]:
            claim["case_ids"] = [
                bogus_case if case_id == old_case else case_id
                for case_id in claim["case_ids"]
            ]
        corpus = (ROOT / validator.CORPUS_RELATIVE).read_text(encoding="utf-8")
        real_embedded_json = validator._embedded_json
        real_index = real_embedded_json(corpus, "PRESERVATION-CASE-BINDING-INDEX")
        mutated_index = sorted(
            bogus_case if case_id == old_case else case_id for case_id in real_index
        )

        def embedded_json(text: str, marker: str):
            if marker == "PRESERVATION-CASE-BINDING-INDEX":
                return mutated_index
            return real_embedded_json(text, marker)

        with mock.patch.object(validator, "_embedded_json", embedded_json):
            with self.assertRaisesRegex(
                validator.ValidationFailure, "absent from exact catalog"
            ):
                validator._validate_case_bindings(ROOT, registry)

    def test_unmapped_public_flow_fails_closed(self) -> None:
        registry = copy.deepcopy(self.registry)
        capability = next(
            item
            for item in registry["capabilities"]
            if item["capability_id"] == "PRES-INTAKE"
        )
        capability["covers"] = [
            expression
            for expression in capability["covers"]
            if not expression.startswith("flow:")
        ]
        with self.assertRaisesRegex(
            validator.ValidationFailure, "unmapped preservation items"
        ):
            validator._validate_capabilities(
                ROOT,
                registry,
                self.inventories,
                list(self.required_items),
            )

    def test_duplicate_mapping_fails_closed(self) -> None:
        registry = copy.deepcopy(self.registry)
        capability = next(
            item
            for item in registry["capabilities"]
            if item["capability_id"] == "PRES-ENTRY"
        )
        capability["covers"].append("flow:FLOW-INTAKE-ONLY")
        with self.assertRaisesRegex(
            validator.ValidationFailure, "multiply mapped preservation items"
        ):
            validator._validate_capabilities(
                ROOT,
                registry,
                self.inventories,
                list(self.required_items),
            )

    def test_rc_item_without_conformance_fails_closed(self) -> None:
        registry = copy.deepcopy(self.registry)
        registry["capabilities"][0]["conformance_families"] = []
        with self.assertRaisesRegex(
            validator.ValidationFailure, "invalid conformance family"
        ):
            validator._validate_capabilities(
                ROOT,
                registry,
                self.inventories,
                list(self.required_items),
            )

    def test_stale_placeholder_fails_closed(self) -> None:
        registry = copy.deepcopy(self.registry)
        registry["capabilities"][0]["user_value"] = "TBD"
        with self.assertRaisesRegex(validator.ValidationFailure, "stale placeholder"):
            validator._reject_placeholders(registry)

    def test_deleted_human_confirm_flow_fails_closed(self) -> None:
        registry = copy.deepcopy(self.registry)
        registry["public_flows"] = [
            item
            for item in registry["public_flows"]
            if item["id"] != "FLOW-HUMAN-CONFIRM"
        ]
        with self.assertRaisesRegex(
            validator.ValidationFailure, "closed public surface drift public_flows"
        ):
            validator._validate_declared_surfaces(ROOT, registry, [])

    def test_deleted_app_canary_schema_fails_closed(self) -> None:
        registry = copy.deepcopy(self.registry)
        registry["public_schemas"] = [
            item
            for item in registry["public_schemas"]
            if item["id"] != "APP-CANARY-RECEIPT-SCHEMA"
        ]
        with self.assertRaisesRegex(
            validator.ValidationFailure, "closed public surface drift public_schemas"
        ):
            validator._validate_declared_surfaces(ROOT, registry, [])

    def test_deleted_finalization_release_contract_fails_closed(self) -> None:
        registry = copy.deepcopy(self.registry)
        registry["release_install_contracts"] = [
            item
            for item in registry["release_install_contracts"]
            if item["id"] != "RELEASE-FINALIZATION-ACKED"
        ]
        with self.assertRaisesRegex(
            validator.ValidationFailure,
            "closed public surface drift release_install_contracts",
        ):
            validator._validate_declared_surfaces(ROOT, registry, [])

    def test_missing_error_ownership_fails_closed(self) -> None:
        registry = copy.deepcopy(self.registry)
        owner = next(iter(registry["error_ownership"]))
        registry["error_ownership"][owner].pop()
        with self.assertRaisesRegex(
            validator.ValidationFailure, "error ownership mismatch"
        ):
            validator._validate_error_ownership(
                registry, self.inventories["errors"], []
            )

    def test_duplicate_error_ownership_fails_closed(self) -> None:
        registry = copy.deepcopy(self.registry)
        owners = list(registry["error_ownership"])
        code = registry["error_ownership"][owners[0]][0]
        registry["error_ownership"][owners[1]].append(code)
        registry["error_ownership"][owners[1]].sort()
        with self.assertRaisesRegex(
            validator.ValidationFailure, "duplicate error ownership"
        ):
            validator._validate_error_ownership(
                registry, self.inventories["errors"], []
            )

    def test_acceptance_case_binding_drift_fails_closed(self) -> None:
        registry = copy.deepcopy(self.registry)
        registry["capabilities"][0]["acceptance_case_ids"].pop()
        with self.assertRaisesRegex(
            validator.ValidationFailure, "acceptance case binding mismatch"
        ):
            validator._validate_case_bindings(ROOT, registry)

    def test_unbound_acceptance_claim_fails_closed(self) -> None:
        registry = copy.deepcopy(self.registry)
        registry["capability_acceptance_requirements"]["PRES-INTAKE"][0][
            "case_ids"
        ] = []
        with self.assertRaisesRegex(
            validator.ValidationFailure, "unbound acceptance claim"
        ):
            validator._validate_case_bindings(ROOT, registry)

    def test_acceptance_claim_coverage_drift_fails_closed(self) -> None:
        registry = copy.deepcopy(self.registry)
        registry["capability_acceptance_requirements"]["PRES-MODES"][0][
            "case_ids"
        ].pop()
        with self.assertRaisesRegex(
            validator.ValidationFailure, "acceptance claim coverage mismatch"
        ):
            validator._validate_case_bindings(ROOT, registry)

    def test_family_variant_matrix_drift_fails_closed(self) -> None:
        registry = copy.deepcopy(self.registry)
        registry["conformance_family_variants"]["CAP-ENTRY"].pop("zero_effect")
        with self.assertRaisesRegex(
            validator.ValidationFailure, "conformance family variant set drift"
        ):
            validator._validate_case_bindings(ROOT, registry)

    def test_anti_bloat_metric_drift_fails_closed(self) -> None:
        registry = copy.deepcopy(self.registry)
        registry["anti_bloat_contract"]["default_path_metrics"].remove(
            "dependency_edges"
        )
        with self.assertRaisesRegex(
            validator.ValidationFailure, "default-path metric set drift"
        ):
            validator._validate_anti_bloat_contract(registry)

    def test_architecture_fitness_passes_current_graph(self) -> None:
        metrics = validator._validate_architecture_fitness(ROOT, self.registry)
        self.assertGreater(metrics["v4_module_count"], 0)
        self.assertGreater(metrics["v4_dependency_edge_count"], 0)

    def test_cyclic_v4_import_graph_fails_closed(self) -> None:
        graph = {
            "loop_architect.v4_alpha.kernel": {
                "loop_architect.v4_alpha.protocol"
            },
            "loop_architect.v4_alpha.protocol": {
                "loop_architect.v4_alpha.kernel"
            },
        }
        imports = {module: set(targets) for module, targets in graph.items()}
        with mock.patch.object(
            validator, "_v4_import_graph", return_value=(graph, imports)
        ):
            with self.assertRaisesRegex(
                validator.ValidationFailure, "cyclic v4 import graph"
            ):
                validator._validate_architecture_fitness(ROOT, self.registry)

    def test_adapter_canonical_writer_import_fails_closed(self) -> None:
        graph, imports = validator._v4_import_graph(ROOT)
        imports = copy.deepcopy(imports)
        imports.setdefault("loop_architect.v4_adapters.codex.adapter", set()).add(
            "loop_architect.v4_persistence.sqlite_store"
        )
        with mock.patch.object(
            validator, "_v4_import_graph", return_value=(graph, imports)
        ):
            with self.assertRaisesRegex(
                validator.ValidationFailure, "anti-bloat dependency violation"
            ):
                validator._validate_architecture_fitness(ROOT, self.registry)

    def test_policy_store_import_fails_closed(self) -> None:
        graph, imports = validator._v4_import_graph(ROOT)
        imports = copy.deepcopy(imports)
        imports.setdefault("loop_architect.v4_policy.policy", set()).add(
            "loop_architect.v4_persistence.sqlite_store"
        )
        with mock.patch.object(
            validator, "_v4_import_graph", return_value=(graph, imports)
        ):
            with self.assertRaisesRegex(
                validator.ValidationFailure, "anti-bloat dependency violation"
            ):
                validator._validate_architecture_fitness(ROOT, self.registry)

    def test_legacy_inventory_cannot_become_runtime_branches(self) -> None:
        registry = copy.deepcopy(self.registry)
        registry["anti_bloat_contract"]["legacy_inventory_runtime_branch_count"] = 1766
        with self.assertRaisesRegex(
            validator.ValidationFailure, "may not define v4 runtime branches"
        ):
            validator._validate_anti_bloat_contract(registry)

    def test_anti_bloat_evidence_metric_mutation_fails_closed(self) -> None:
        evidence = json.loads(
            (ROOT / validator.ANTI_BLOAT_EVIDENCE_RELATIVE).read_text(
                encoding="utf-8"
            )
        )
        evidence["default_path_measurement"]["authorization_confirmations"] = 0
        with self.assertRaisesRegex(
            validator.ValidationFailure, "default-path evidence drift"
        ):
            validator._validate_anti_bloat_evidence_value(ROOT, evidence)

    def test_p6_evidence_safety_mutation_fails_closed(self) -> None:
        evidence = json.loads(
            (ROOT / validator.P6_EVIDENCE_RELATIVE).read_text(encoding="utf-8")
        )
        evidence["compatibility_contract"]["source_bytes_unchanged"] = False
        with self.assertRaisesRegex(
            validator.ValidationFailure, "P6 compatibility evidence drift"
        ):
            validator._validate_p6_evidence_value(ROOT, evidence)

    def test_p7_baseline_threshold_mutation_fails_closed(self) -> None:
        evidence = json.loads(
            (ROOT / validator.P7_BASELINE_RELATIVE).read_text(encoding="utf-8")
        )
        evidence["blocking_thresholds"]["v4_pack_bytes_max"] += 1
        with self.assertRaisesRegex(
            validator.ValidationFailure, "P7 frozen baseline drift"
        ):
            validator._validate_p7_baseline_value(ROOT, evidence)


if __name__ == "__main__":
    unittest.main()
