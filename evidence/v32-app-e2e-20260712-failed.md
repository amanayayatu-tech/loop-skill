# Loop Skill v3.2 Codex App bounded smoke (frozen failure)

## Evidence boundary

- Evidence layer: one current-machine bounded Codex App smoke.
- Result: `FAIL_PROTOCOL_CONSISTENCY`; this is not long-run/formal acceptance.
- Claim boundary: the run does not prove that every Codex App version or project
  can automatically reach terminal state.
- The run is frozen. Existing tasks and canonical artifacts were preserved; no
  replacement task was created in this run.

## Identity

- Project: `测试 loop`
- Root: `/Users/peachy/Documents/测试 loop/loop-skill-v32-e2e-20260712`
- Pack SHA-256: `dba3a4e5b4ccaa29632568fd91da419e9720a5e5ff6eca17c5bbc3baa5354091`
- Controller: `019f5471-ea81-7093-acf1-f774c23340a0`
- State-Writer: `019f5473-df5d-73a3-8dc5-912c0a17e50f`
- Worker: `019f5480-5bd3-7571-94f3-6dc19cd2d136`
- Reviewer: `019f549e-bb9c-7210-97eb-b92f7dce5ad5`
- Heartbeat: `loop-loop-heartbeat-loop-skill-v32-e2e-559311b1031f119e`
  (`PAUSED`, 10-minute interval, Controller target above)

## Frozen canonical state

- Schema/state version: `2` / `49`
- Routing budget: `8 / 12`
- Run control: `PAUSED_AT_SAFE_POINT`
- Terminal status: none
- Controller Goal in canonical state: `ACTIVE`; the App Goal surface was later
  marked blocked by the global repeated-blocker audit, so these identities are
  not consistent enough for PASS.
- Canonical artifacts:
  - `.codex-loop/LOOP_STATE.md`
  - `.codex-loop/LOOP_EVENTS.jsonl`
  - `.codex-loop/transactions/`
  - `.codex-loop/reports/`
  - `.codex-loop/STATUS.md`

## What the smoke did prove

- The real installed schema-v2 runtime initialized canonical state through the
  State-Writer.
- Controller, State-Writer, one reusable Worker, one just-in-time Reviewer, one
  native Goal, and one business heartbeat used the same Codex Project.
- `STATUS_QUERY` did not route product work.
- A `CORRECTION` received while Worker work was active was deferred.
- `PAUSE` reached `PAUSED_AT_SAFE_POINT` only after the active Worker result was
  durably acknowledged; `RESUME` reused the same task identities and ledgers.
- The first Worker artifact and CODE_REVIEW report were archived with exact
  digests. CODE_REVIEW correctly returned `REVIEW_NEEDS_REPAIR` for the missing
  corrected sentence.
- A rejected repair payload caused zero product-file changes.

## Failure

The installed runtime verified every Worker payload as an initial
`GOAL_DISPATCH`. A legitimate repair payload was bound to the `REPAIR`
freshness checkpoint, parent dispatch, and parent artifact digest, so payload
verification rejected it with `DISPATCH_FRESHNESS_SNAPSHOT_MISMATCH`.

The Pack also set `max_routing_turns=12`. After eight consumed turns, the direct
success path still required repair dispatch, CODE_REVIEW, ROADMAP_AUDIT,
FINAL_AUDIT, and FINALIZE_LOOP. Its declared two-repair policy additionally
required capacity to rerun exact-artifact ROADMAP_AUDIT and FINAL_AUDIT after
each bounded repair, so the deterministic generation floor is 17 routes.
Therefore the Pack could not
legally reach its declared terminal state even after the freshness defect was
fixed.

After the repaired runtime was installed, every explicitly authorized recovery
check reused the same Controller and State-Writer without creating replacement
tasks. Pack identity, installed runtime/schema availability, and source/install
byte identity passed. The first resume mutation was rejected with zero side
effects because state v49
carried a valid `status-v1` projection digest while the new runtime rendered the
expanded status surface under the same contract name. Canonical state remained
v49, the native Goal remained blocked, and the existing heartbeat remained
`PAUSED`. Later installation checks read the same canonical state without
submitting another mutation, acquiring a lease, or resuming the heartbeat. They
also confirmed that the remaining `4` routing
turns cannot cover the required five-step success path, so this run cannot be
relabelled or resumed to PASS.

## Source response

- Repair payload verification now selects `GOAL_DISPATCH` for an initial
  dispatch and `REPAIR` plus exact parent dispatch/artifact identity for a
  repair dispatch.
- Adaptive generation now rejects `max_wakeups` below a deterministic terminal
  route floor derived from Goals, milestones, repair limits, formal tasks,
  required Local Verification, assurance, and finalization.
- The generated heartbeat protocol now forbids treating a deferred Steering
  correction as repair authorization or reserving a speculative repair route.
- Regression tests cover correct repair freshness, stale initial freshness,
  one-Goal route capacity, and required Local Verifier capacity.
- STATUS projection rendering is now explicitly versioned. Existing
  `status-v1` bytes are recomputed with the legacy renderer before acceptance;
  the next successful mutation atomically upgrades the target and projection
  journal to `status-v2`. Unknown or tampered legacy targets remain rejected
  without state, event, journal, or external-action side effects.

These source fixes have local test and fuzz evidence. This frozen run did not
execute the fixed bytes and must not be relabeled PASS.
