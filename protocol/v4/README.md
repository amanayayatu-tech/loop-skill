# LoopSkill 4 protocol authority

`loopskill-v4.protocol.json` is the sole source for LoopSkill 4 command,
event, error, reference, capability, receipt, and other wire-record shapes.
Reducer transition invariants remain in the kernel; Host provenance and
readback rules remain in Adapter contracts. JSON Schema is therefore a shape
artifact, not the full protocol semantics.

For v4.2 the same manifest also owns the capacity contract and optional
content-plan command fields. Generated consumers expose the 1–128 Goal,
512 KiB canonical PlanDocument, 256 KiB text/Markdown source, 8 KiB / 64-member
CreateLoop release target, and 24 KiB Host prompt admission target. Runtime code
must not restate those numbers as a parallel authority. `AuthorityGrantV2`,
`PlanDocument`, `PlanIndex`, and `PlanCapacityReport` are generated wire types;
plan semantic canonicalization and reference derivation remain reviewed runtime
invariants rather than a second schema.

Regenerate deterministic consumers with:

```sh
python3 scripts/generate_v4_protocol.py --write
```

CI and local conformance use `--check`. The generated Python records are the
only runtime wire types. The generated JSON Schema and API summary are the only
allowed shape inputs for future MCP, CLI, SDK, and Pack-facing summaries.
Handwritten parallel fields or enum copies fail the drift tests.

Commands carrying `reserved_until` are already named by ADR 0011 but are not
yet implemented. A reducer must fail them closed until the named phase removes
the reservation and adds its conformance cases. Reservation is not a claim of
working product behavior.
