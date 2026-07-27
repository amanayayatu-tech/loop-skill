from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from dataclasses import fields
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "codex-loop-prompt-architect" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

GENERATOR_PATH = ROOT / "scripts" / "generate_v4_protocol.py"
GENERATOR_SPEC = importlib.util.spec_from_file_location(
    "generate_v4_protocol", GENERATOR_PATH
)
assert GENERATOR_SPEC and GENERATOR_SPEC.loader
GENERATOR = importlib.util.module_from_spec(GENERATOR_SPEC)
GENERATOR_SPEC.loader.exec_module(GENERATOR)

from loop_architect.v4_alpha.generated_protocol import (  # noqa: E402
    MANIFEST_SHA256,
    ActorRef,
    ApplyResult,
    AuthorityGrant,
    CapabilityRecord,
    CommandEnvelope,
    Receipt,
    Reference,
)
from loop_architect.v4_alpha.kernel import _REDUCERS  # noqa: E402
from loop_architect.v4_alpha.protocol import (  # noqa: E402
    COMMAND_TYPES,
    ERROR_CODES,
    EVENT_TYPES,
    PROTOCOL_MANIFEST,
    ProtocolRejection,
    validate_capability_record,
    validate_command,
    validate_event_type,
    validate_reference,
    with_command_change,
)
from loop_architect.v4_alpha.vertical import vertical_commands  # noqa: E402


class V4ProtocolAuthorityTests(unittest.TestCase):
    def assert_rejected(self, code, callable_):
        with self.assertRaises(ProtocolRejection) as caught:
            callable_()
        self.assertEqual(caught.exception.code, code)

    def test_manifest_digest_and_all_generated_artifacts_are_exact(self):
        manifest = GENERATOR.load_manifest()
        digest = hashlib.sha256(GENERATOR.canonical(manifest)).hexdigest()
        self.assertEqual(digest, MANIFEST_SHA256)
        self.assertEqual(PROTOCOL_MANIFEST["manifest_sha256"], digest)
        for path, expected in GENERATOR.outputs().items():
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertEqual(path.read_bytes(), expected)
                self.assertNotEqual(path.read_bytes() + b"mutation", expected)

    def test_generated_dataclass_fields_are_manifest_derived(self):
        classes = {
            "ActorRef": ActorRef,
            "ApplyResult": ApplyResult,
            "AuthorityGrant": AuthorityGrant,
            "CapabilityRecord": CapabilityRecord,
            "CommandEnvelope": CommandEnvelope,
            "Receipt": Receipt,
            "Reference": Reference,
        }
        manifest = GENERATOR.load_manifest()
        for name, type_ in classes.items():
            with self.subTest(type=name):
                expected = [field[0] for field in manifest["wire_types"][name]]
                self.assertEqual([field.name for field in fields(type_)], expected)

    def test_manifest_unknown_key_duplicate_and_duplicate_value_fail_closed(self):
        manifest = GENERATOR.load_manifest()
        unknown = copy.deepcopy(manifest)
        unknown["parallel_schema"] = {}
        with self.assertRaises(GENERATOR.ManifestError):
            GENERATOR.validate_manifest(unknown)

        duplicate = copy.deepcopy(manifest)
        duplicate["errors"].append(duplicate["errors"][0])
        with self.assertRaises(GENERATOR.ManifestError):
            GENERATOR.validate_manifest(duplicate)

        with self.assertRaises(GENERATOR.ManifestError):
            GENERATOR.parse_manifest('{"protocol_version":"a","protocol_version":"b"}')

    def test_semantic_payload_shape_enum_and_protocol_drift_reject(self):
        base = vertical_commands()[0]
        cases = (
            ({}, "INVALID_COMMAND"),
            ({"objective": "x", "manual_schema": "forbidden"}, "INVALID_COMMAND"),
            ({"objective": 7}, "INVALID_COMMAND"),
        )
        for payload, code in cases:
            command = with_command_change(
                base, lambda values, payload=payload: values.update(semantic_payload=payload)
            )
            with self.subTest(payload=payload):
                self.assert_rejected(code, lambda command=command: validate_command(command))

        unknown_command = with_command_change(
            base, lambda values: values.update(command_type="ManualDuplicateCommand")
        )
        self.assert_rejected(
            "INVALID_COMMAND", lambda: validate_command(unknown_command)
        )
        wrong_version = with_command_change(
            base, lambda values: values.update(protocol_version="4.0-manual")
        )
        self.assert_rejected(
            "UNSUPPORTED_PROTOCOL_VERSION", lambda: validate_command(wrong_version)
        )

    def test_event_error_reference_and_capability_unknowns_fail_closed(self):
        self.assert_rejected(
            "INVALID_COMMAND", lambda: validate_event_type("ManualEvent")
        )
        with self.assertRaises(ValueError):
            ProtocolRejection("MANUAL_ERROR", "not in manifest")
        self.assert_rejected(
            "WRONG_REFERENCE_KIND",
            lambda: validate_reference(
                Reference(kind="ManualRef", value="x", loop_ref="loop-0001")
            ),
        )
        self.assert_rejected(
            "CAPABILITY_UNAVAILABLE",
            lambda: validate_capability_record(
                CapabilityRecord(
                    capability="manual_capability",
                    availability="AVAILABLE",
                    assurance="LOCAL",
                    issuer_ref="fixture",
                    receipt_ref=None,
                    details={},
                )
            ),
        )

    def test_reducer_dispatch_and_emitted_literals_conform_to_manifest(self):
        manifest = GENERATOR.load_manifest()
        reserved = {
            name
            for name, specification in manifest["commands"].items()
            if "reserved_until" in specification
        }
        self.assertEqual(set(_REDUCERS), set(COMMAND_TYPES) - reserved)
        self.assertEqual(
            reserved,
            {
                "ImportV3Snapshot",
                "PauseLoop",
                "ResumeLoop",
                "StrengthenClosureAssurance",
            },
        )
        kernel = (
            SCRIPTS / "loop_architect" / "v4_alpha" / "kernel.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(kernel)
        emitted = {
            node.args[0].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_event"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        }
        errors = {
            node.args[0].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ProtocolRejection"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        }
        self.assertLessEqual(emitted, set(EVENT_TYPES))
        self.assertLessEqual(errors, set(ERROR_CODES))

    def test_no_parallel_wire_dataclasses_or_manifest_assignments(self):
        package = SCRIPTS / "loop_architect" / "v4_alpha"
        protected_classes = {
            "ActorRef",
            "ApplyResult",
            "AuthorityGrant",
            "CapabilityRecord",
            "CommandEnvelope",
            "Receipt",
            "Reference",
        }
        protected_assignments = {
            "COMMAND_TYPES",
            "ERROR_CODES",
            "EVENT_TYPES",
            "REFERENCE_KINDS",
            "SEMANTIC_PAYLOAD_SPECS",
        }
        violations = []
        for source in sorted(package.glob("*.py")):
            if source.name == "generated_protocol.py":
                continue
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name in protected_classes:
                    violations.append(f"{source.name}:{node.lineno}:class:{node.name}")
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id in protected_assignments:
                            violations.append(
                                f"{source.name}:{node.lineno}:assignment:{target.id}"
                            )
        self.assertEqual(violations, [])

    def test_kernel_import_graph_remains_host_and_io_free(self):
        forbidden = {
            "codex",
            "git",
            "http",
            "os",
            "pathlib",
            "requests",
            "socket",
            "sqlite3",
            "subprocess",
            "urllib",
        }
        for filename in ("generated_protocol.py", "protocol.py", "kernel.py"):
            source = SCRIPTS / "loop_architect" / "v4_alpha" / filename
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            imported = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.append(node.module)
            self.assertEqual(
                [name for name in imported if name.split(".", 1)[0] in forbidden],
                [],
                filename,
            )


if __name__ == "__main__":
    unittest.main()
