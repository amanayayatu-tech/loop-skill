# LoopSkill 4 single-entry UX boundary

## Public contract

The first v4 command name is `loopskill4`. It is currently a source-tree entry
and is not installed or published. Its default happy path is one invocation:

```text
loopskill4 start "one semantic goal"
loopskill4 start goal.txt
loopskill4 start goal.json
```

Each form is exactly one user-visible action. A successful action atomically
persists one canonical loop with Goal and Execution ACTIVE plus one startup
`ExternalEffect`, `Attempt`, and outbox descriptor. “Started” means the local
lifecycle and the machine-owned Host-start request are durable; it does not
claim that a Host task was created or that the effect was observed. Host work
remains visibly `Starting` until the Codex Adapter provides evidence.

The only required user value is semantic goal text. The command accepts no
thread, task, route, effect, Artifact, Review, Finalization, Actor, Grant,
operation, revision, receipt, digest, Host enum, heartbeat, retry, capture
algorithm, or policy-pack input. All control identity and command-envelope
fields are allocated and bound by the local machine-authority service. Goal
text containing an identifier-like token remains inert text.

No policy pack is installed, selected, or required. The entry is a thin
application service over generated protocol records, the Kernel reducer, the
single SQLite canonical writer, and an injected Host provider port when one is
available. The public action may synchronously ask the Codex Adapter to claim
and execute the already-durable startup Attempt. The facade never calls a
provider directly, allocates a second Attempt, or retries an uncertain effect.
It is not a Supervisor, retry controller, second writer, or second control
plane.

## Input and storage

A literal argument, strict UTF-8 text file, strict one-field JSON object, or
standard input may provide the goal. JSON accepts only `{"goal":"..."}`.
Empty input, invalid UTF-8/JSON, extra fields, a missing file, and input over
4096 UTF-8 bytes fail before a store is created.

The source-tree command accepts an optional `--root` for isolated development
and testing. The default is the platform LoopSkill 4 data root. The root and
SQLite file must be owner-only, regular, and non-symlinked. One P5 root contains
one loop; a duplicate start fails without a second operation or loop. Status
and diagnostics are read-only and never create an absent store.

SQLite schema v4 stores the user-visible goal descriptor plus immutable Actor,
Grant, receipt, and trust-root registries in the same canonical database as the
loop. CreateLoop commits its operation/result/events/snapshot and startup
ExternalEffect/Attempt/outbox atomically. Reopening the store reconstructs
machine authority without user or model transcription. These registries remain
reducer input; they do not become semantic payload or a second writer.

## User-visible status and errors

Default output contains only:

- goal;
- progress;
- result;
- limitations; and
- one actionable next action.

Internal references, revisions, receipt identities, schema versions, and
snapshot digests are absent. `--diagnostics` is explicit opt-in and emits a
bounded internal view. UNKNOWN is rendered as an unknown external outcome;
UNVERIFIABLE is rendered as an outcome that cannot be verified. Neither output
offers or triggers automatic resend.

Public errors use the manifest-generated `UserFacingError` shape and stable
`USER_*` codes. Normal error text never echoes supplied control-like options,
handles, receipts, schemas, or tracebacks.

## Compatibility promise and intentional changes

Yes: an ordinary user can still start with one file or one command, and the
number of user-supplied control identities is exactly zero. v4 promises no
increase in default startup action count, no leaked control-plane choreography,
and no implicit v3 migration.

Intentional major-version improvements are visible UNKNOWN/UNVERIFIABLE,
machine-bound identity, an owner-only new v4 store/root, stable recovery text,
and diagnostics that are opt-in. v4 does not promise byte-identical Controller
Packs, old Pack identity, every v3 CLI flag, or identical wording. The v3
compatibility facade and explicit preview/confirm/cancel import remain P6 gates;
entry-byte and action-count budgets remain P7 gates; installation and a real
new-user canary remain P8 gates.

## P5 evidence boundary

P5 tests cover `UX-001-a..b`, `UX-002`, `UX-003`, `UX-004-a..c`,
`UX-005-a..b`, and `UX-007-a..b` at the local source-entry level. They also
cover `H-011-a..d`: atomic startup-subject creation, exact strict Host binding,
UNKNOWN without resend/binding, and cooperative-to-late-strict observation on
the same Attempt. All provider behavior in these P5 tests is synthetic. P5 does
not claim `UX-006`, `UX-008`, or `UX-009`, installed usability, real Host
completion, v3 migration safety, or release readiness.
