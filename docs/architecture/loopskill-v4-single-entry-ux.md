# LoopSkill 4 single-entry UX boundary

## Public contract

The v4 command name is `loopskill4`. The installer publishes this one entry
under the distinct v4 Skill root. Its native flow is
`INTAKE → PREPARE → CONFIRM → START`. A complete semantic input can enter the
whole flow with one invocation:

```text
loopskill4 start goal.json
```

The command prints a stable seven-section intake report, writes five owner-only
preparation artifacts, displays Goal/scope/budget/external actions/acceptance/
stop/authorization boundaries, and pauses for exact interactive confirmation.
A non-interactive invocation stops after PREPARE and directs the user to the
explicit `confirm` action; piped input, `--yes`, defaults, and vague continuation
cannot become start authority. Equivalent explicit actions are:

```text
loopskill4 intake goal.json
loopskill4 prepare goal.json --output prepared-loop
loopskill4 confirm prepared-loop
loopskill4 start prepared-loop
```

One public start invocation is one user start action; mandatory human
confirmation is measured separately. START atomically persists one canonical
loop with Goal and Execution ACTIVE plus one startup `ExternalEffect`,
`Attempt`, and outbox descriptor. “Started” means the local lifecycle and the
machine-owned Host-start request are durable; it does not claim that a Host task
was created or that the effect was observed. Host work remains visibly
`Starting` until the Codex Adapter provides evidence.

The user supplies semantic requirements only. INTAKE asks at most three
highest-priority missing questions and returns exactly one of
`READY_FOR_LOOP`, `NEEDS_CLARIFICATION`, `BLOCKED`, or
`DIRECT_TASK_RECOMMENDED`; the last outcome creates no loop. The command accepts
no thread, task, route, effect, Artifact, Review, Finalization, Actor, Grant,
operation, revision, receipt, digest, Host enum, heartbeat, retry, capture
algorithm, or policy-pack input. All control identity and command-envelope
fields are allocated and bound by the local machine-authority service. Goal
text containing an identifier-like token remains inert text.

No policy pack is installed, selected, or required by the minimal path. Entry
is the composition root over generated protocol records, Kernel, independent
Store/Artifact/Host ports, and the selected implementations. Store never calls
Host, and Artifact/Host never write canonical state. The facade never allocates
a second Attempt or retries an uncertain effect. It is not a Supervisor, retry
controller, second writer, or second control plane.

## Intake, preparation, and storage

A literal argument or strict UTF-8 text file is accepted as an incomplete
semantic request and normally produces clarification questions. A complete
JSON input contains only `goal`, `task_horizon`, `write_scope`, `budget`,
`external_actions`, `acceptance_criteria`, `stop_conditions`, and
`authorization_boundaries`. Unknown/control fields, invalid UTF-8/JSON, a
missing file, and input over 32 KiB fail before preparation or store creation.

INTAKE performs zero writes and zero Loop/Host/task/heartbeat/effect actions.
PREPARE writes exactly five local files in a new owner-only empty directory:
the typed manifest, boundary summary, human Controller Plan, Chinese
instructions, and digest bundle. It performs zero canonical/Host/execution
effects. Markdown is a review/export view; the typed manifest is machine truth.
CONFIRM writes one local receipt bound to the manifest, boundary, and bundle
digests with a bounded lifetime. Missing, expired, forged, wrong-scope, or
content-stale confirmation makes START fail before creating the v4 store.

The source-tree command accepts an optional `--root` for isolated development
and testing. The default is the platform LoopSkill 4 data root. The root and
SQLite file must be owner-only, regular, and non-symlinked. One P5.1 root
contains one loop; exact replay of the same prepared start returns the prior
accepted result without a second commit/event/Attempt/Host call, while a
different prepared loop fails. Plain `status` and diagnostics are read-only
and never create an absent store. `status --refresh` is the explicit
machine-owned recovery action. When the durable Attempt has not been claimed,
it may acquire execution ownership and perform the unique first foreground
Codex invocation. Once an invocation started, there is no cross-process Host
readback or resume: lost evidence remains `UNKNOWN`, and refresh never performs
a second spawn.

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

## v4-only promise and intentional changes

Yes: an ordinary user can still start with one file or one command, and the
number of user-supplied control identities is exactly zero. v4 promises no
increase in default startup action count, no leaked control-plane choreography,
and no implicit v3 migration.

Intentional major-version improvements are visible UNKNOWN/UNVERIFIABLE,
machine-bound identity, an owner-only new v4 store/root, stable recovery text,
and diagnostics that are opt-in. v4 does not preserve byte-identical Controller
Packs, old Pack identity, v3 CLI flags, MCP state, or identical wording. It has
no v3 importer, repair/open operation, existing-Pack mode, compact/full legacy
export, compatibility facade, or automatic migration.

A recognized v3 root/state/Pack receives stable
`USER_UNSUPPORTED_LEGACY_VERSION`, a direct v3.3.8 release reference, and zero
writes. The independent v3 runtime and bytes remain the only path for old data.
A ready durable v4 input defaults to Standard; only an explicit adaptive
horizon selects Adaptive. Optional policy execution is not loaded by the
minimal startup path. Entry-byte, action-count, and internal-interaction budgets
remain release gates; installation and a real new-user canary bind the final
exact SHA.

## P5.1 evidence boundary

P5.1 tests cover `UX-001`, `UX-010..016`, `CAP-INTAKE`, `CAP-ENTRY`, and
`CAP-ARCHITECTURE` at the local source-entry level: four intake outcomes, seven
report sections, zero-effect intake, five-file preparation, digest-bound
confirmation, stale/expired/forged rejection, one canonical start, exact
replay, non-interactive no-bypass, and policy-unavailable minimal-profile
isolation. They retain P5 coverage of `UX-002..005`, `UX-007`, and
`H-011-a..d`: atomic startup-subject creation, exact strict Host binding,
UNKNOWN without resend/binding, and cooperative-to-late-strict observation on
the same Attempt. All provider behavior in these tests is synthetic. P5.1 does
not claim `UX-006`, `UX-008`, or `UX-009`, installed usability, real Host
completion, public release, or support for v3 data.
