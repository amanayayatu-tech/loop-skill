from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts/validate_spec.py"
SPEC = importlib.util.spec_from_file_location("validate_spec", VALIDATOR)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SpecGovernanceTests(unittest.TestCase):
    def test_repository_index_is_structurally_valid(self) -> None:
        self.assertEqual(MODULE.validate(ROOT), [])

    def test_duplicate_id_and_missing_core_test_are_rejected(self) -> None:
        source = yaml.safe_load((ROOT / "docs/spec/invariants.yaml").read_text())
        source["invariants"][1]["id"] = source["invariants"][0]["id"]
        source["invariants"][0]["test_surfaces"] = []
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invariants.yaml"
            path.write_text(yaml.safe_dump(source), encoding="utf-8")
            errors = MODULE.validate(ROOT, path)
        self.assertTrue(any("duplicate_id" in error for error in errors))
        self.assertTrue(any("active_contract_requires_test_surface" in error for error in errors))

    def test_bad_reference_and_dependency_cycle_are_rejected(self) -> None:
        source = yaml.safe_load((ROOT / "docs/spec/invariants.yaml").read_text())
        first, second = source["invariants"][:2]
        first["authoritative_sources"] = ["missing-contract.md"]
        first["depends_on"] = [second["id"]]
        second["depends_on"] = [first["id"]]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invariants.yaml"
            path.write_text(yaml.safe_dump(source), encoding="utf-8")
            errors = MODULE.validate(ROOT, path)
        self.assertTrue(any("missing-contract.md" in error for error in errors))
        self.assertTrue(any("dependency_cycle" in error for error in errors))

    def test_validator_does_not_bind_functions_or_require_adrs(self) -> None:
        source = yaml.safe_load((ROOT / "docs/spec/invariants.yaml").read_text())
        repair = next(item for item in source["invariants"] if item["id"] == "INV-REPAIR-001")
        repair["implementation_surfaces"] = []
        self.assertEqual(repair["adr"], [])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invariants.yaml"
            path.write_text(yaml.safe_dump(source), encoding="utf-8")
            errors = MODULE.validate(ROOT, path)
        self.assertEqual(errors, [])

    def test_orphan_adr_is_rejected(self) -> None:
        source = yaml.safe_load((ROOT / "docs/spec/invariants.yaml").read_text())
        for invariant in source["invariants"]:
            invariant["adr"] = [
                path for path in invariant["adr"]
                if path != "docs/adr/0001-bounded-non-pty-input.md"
            ]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invariants.yaml"
            path.write_text(yaml.safe_dump(source), encoding="utf-8")
            errors = MODULE.validate(ROOT, path)
        self.assertIn(
            "index:orphan_adr:docs/adr/0001-bounded-non-pty-input.md",
            errors,
        )

    def test_adr_status_and_sections_are_structurally_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = "docs/adr/0099-invalid.md"
            path = root / relative
            path.parent.mkdir(parents=True)
            path.write_text(
                "# ADR 0099: Invalid fixture\n\n- Status: Unknown\n\n## Context\n\nFixture.\n",
                encoding="utf-8",
            )
            errors = MODULE.validate_adr(root, relative)
        self.assertIn(f"adr:invalid_status:{relative}", errors)
        self.assertIn(f"adr:missing_section:{relative}:Decision", errors)
        self.assertIn(f"adr:missing_section:{relative}:Evolution", errors)

    def test_superseded_adr_requires_a_real_nonself_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = "docs/adr/0099-old.md"
            path = root / relative
            path.parent.mkdir(parents=True)
            path.write_text(
                "# ADR 0099: Old decision\n\n"
                "- Status: Superseded\n"
                "- Superseded by: docs/adr/0099-old.md\n\n"
                "## Context\n\nOld.\n\n## Decision\n\nOld.\n\n"
                "## Consequences\n\nOld.\n\n## Evolution\n\nReplace.\n",
                encoding="utf-8",
            )
            errors = MODULE.validate_adr(root, relative)
        self.assertIn(f"adr:self_replacement:{relative}", errors)

    def test_fragment_only_reference_is_rejected(self) -> None:
        source = yaml.safe_load((ROOT / "docs/spec/invariants.yaml").read_text())
        source["invariants"][0]["authoritative_sources"] = ["#section"]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invariants.yaml"
            path.write_text(yaml.safe_dump(source), encoding="utf-8")
            errors = MODULE.validate(ROOT, path)
        self.assertTrue(any("invalid_reference:#section" in error for error in errors))

    def test_active_public_contract_requires_sources_and_tests(self) -> None:
        source = yaml.safe_load((ROOT / "docs/spec/invariants.yaml").read_text())
        public = next(item for item in source["invariants"] if item["level"] == "PUBLIC_CONTRACT")
        public["authoritative_sources"] = []
        public["test_surfaces"] = []
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invariants.yaml"
            path.write_text(yaml.safe_dump(source), encoding="utf-8")
            errors = MODULE.validate(ROOT, path)
        self.assertIn(
            f"{public['id']}:active_contract_requires_authoritative_source",
            errors,
        )
        self.assertIn(f"{public['id']}:active_contract_requires_test_surface", errors)

    def test_scalar_dependency_is_rejected(self) -> None:
        source = yaml.safe_load((ROOT / "docs/spec/invariants.yaml").read_text())
        source["invariants"][0]["depends_on"] = source["invariants"][1]["id"]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invariants.yaml"
            path.write_text(yaml.safe_dump(source), encoding="utf-8")
            errors = MODULE.validate(ROOT, path)
        self.assertTrue(any("depends_on_must_be_list_of_ids" in error for error in errors))

    def test_duplicate_yaml_key_is_rejected(self) -> None:
        source = (ROOT / "docs/spec/invariants.yaml").read_text()
        duplicate = source.replace("schema_version: 1", "schema_version: 1\nschema_version: 1", 1)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invariants.yaml"
            path.write_text(duplicate, encoding="utf-8")
            errors = MODULE.validate(ROOT, path)
        self.assertTrue(any("duplicate key 'schema_version'" in error for error in errors))

    def test_adr_supersession_cycle_is_rejected(self) -> None:
        source = yaml.safe_load((ROOT / "docs/spec/invariants.yaml").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "docs/spec").mkdir(parents=True)
            (root / "docs/adr").mkdir(parents=True)
            for number, target in (("0001", "0002"), ("0002", "0001")):
                relative = f"docs/adr/{number}-decision.md"
                (root / relative).write_text(
                    f"# ADR {number}: Decision\n\n- Status: Superseded\n"
                    f"- Superseded by: docs/adr/{target}-decision.md\n\n"
                    "## Context\n\nContext.\n\n## Decision\n\nDecision.\n\n"
                    "## Consequences\n\nConsequences.\n\n## Evolution\n\nEvolution.\n",
                    encoding="utf-8",
                )
            source["invariants"] = source["invariants"][:2]
            for invariant, number in zip(source["invariants"], ("0001", "0002")):
                invariant["adr"] = [f"docs/adr/{number}-decision.md"]
                for field in MODULE.PATH_FIELDS - {"adr"}:
                    invariant[field] = []
                invariant["level"] = "PROVISIONAL"
            index = root / "docs/spec/invariants.yaml"
            index.write_text(yaml.safe_dump(source), encoding="utf-8")
            errors = MODULE.validate(root, index)
        self.assertTrue(any("adr:supersession_cycle" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
