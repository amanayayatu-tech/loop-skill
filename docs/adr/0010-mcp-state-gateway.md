# ADR 0010: MCP State Gateway replaces the session State-Writer for schema v3

- Status: Accepted
- Date: 2026-07-17
- Decision scope: new Adaptive Packs and their schema-v3 canonical state

## Context

The session State-Writer design depended on Controller-to-task message delivery
to wake the one process that could mutate canonical state. The v244 incident
showed that an App routing failure could leave a safe outbox and staged report
durable but prevent that writer from being reawakened. A later transport issue
also showed that a generated Pack must not require a non-PTY shell stdin to
remain writable after process launch.

The existing State-Writer path remains important historical evidence and a
compatibility surface. It is not a safe default for a new loop when the
installed MCP server can perform one atomic, host-attested canonical mutation.

## Decision

Schema v3 makes the installed MCP `state_gateway` the sole canonical writer.
New Packs create no State-Writer task. The Gateway derives leases, repository
identity, freshness, validation, review handoff, current artifact and payload
from canonical state and exposes bounded operations:

- `INITIALIZE` and `INITIALIZE_SUCCESSOR` for fresh roots only;
- bootstrap-only `REGISTER_TASK` and `REGISTER_HEARTBEAT`, plus later
  `RECORD_HEARTBEAT_OBSERVATION` for the one real business heartbeat;
- `PREPARE_ROUTE`, `RECORD_ROUTE_SENT`, and `ACK_ROUTE_RESULT` for one route;
- `REPORT_RECOVERY` for a staged report on the original outbox; and
- `ADVANCE_ROADMAP`, `PREPARE_FINALIZATION`, `ACK_FINALIZATION`,
  `ACK_TRANSPORT_PAUSE`, `ACK_TRANSPORT_RECOVERY`, and bounded transport
  observations.

`PREPARE_FINALIZATION` is a nonterminal reservation. It records a PREPARED
outbox but leaves `terminal_status` null; only `ACK_FINALIZATION`, after an
actual PAUSED automation-update readback bound to the current Controller turn,
projects the terminal state.

The runtime codec remains the typed transport for materialization, verification,
staging, fingerprint normalization and raw complete-diff capture. A binary
Worker PASS carries only a digest-only `CAPTURED_GIT_DIFF_V1` identity; runtime
derives and rechecks its capture rather than accepting patch bytes or a
model-selected control-plane path. A PASS
projection requires the same Goal's current artifact, current Worker dispatch,
and PASS formal report. A `BLOCKED` report is never a PASS input.

Schema v3 disables native Goal adapters. A nonfinal audit can advance only the
unchanged canonical registry, while finalization records the local
`GATEWAY_NO_NATIVE_GOAL` sentinel and a verified pause/readback record rather
than claiming an external Goal-tool outcome. Target report staging is bound to
the host-attested Worker/Reviewer/Verifier identity, not merely Controller text.
For Worker PASS, validation files are captured by that target-owned stage from
the registered worktree, then archived by ACK or REPORT_RECOVERY in the same
canonical transaction as the report. This avoids both a pre-ACK artifact-ledger
cycle and Controller-authored validation evidence.

Schema v1/v2 state remains readable. Moving it to v3 requires explicit
`MIGRATE_V2_TO_V3` at a PAUSED, lease-free, outbox-quiescent safe point. A
terminal predecessor is immutable: a continuation is a new root with
`INITIALIZE_SUCCESSOR`, never a revival.

## Consequences

- App message delivery remains an external dependency for Worker/Reviewer
  dispatch, but it is no longer the only way to wake a canonical writer.
- Generated Packs, README files, canaries, release receipts, schemas and tests
  must distinguish schema-v3 Gateway behavior from legacy State-Writer
  compatibility.
- A matching transport fault retains its original outbox. Two natural
  observations or fifteen minutes stop canonical routing and require one user
  notice; `ACK_TRANSPORT_PAUSE` records the actual business-heartbeat pause
  before it is claimed. Once the retained outbox resolves,
  `ACK_TRANSPORT_RECOVERY` binds the same heartbeat's real ACTIVE readback and
  restores RUNNING in one canonical CAS. An outer Supervisor is not a recovery
  channel.
- `LOOP_METRICS.json` is derived observation only and never a second canonical
  state source; Worker, Reviewer, and Local Verifier windows remain separate.
- Schema v3 is host-cooperative, not Byzantine. It binds a real App return
  value or readback to the current host-attested turn, the prepared outbox and
  the registered task/heartbeat identity. It therefore prevents ordinary
  crashes, duplicate sends, stale/mismatched reports, wrong artifact or
  dispatch, and premature terminal projection; it does not claim to resist a
  malicious Controller that can forge every App invocation. A future
  non-argument `x-codex-app-action-receipt-v1` carrier is optional stronger
  evidence and is strictly verified when present, but lack of that carrier does
  not block a runnable Loop.

## Rejected alternatives

- Keep a State-Writer task and add a second message-based wakeup path: it
  duplicates the same App routing dependency and complicates identity.
- Let Controller patch canonical files when the writer is unavailable: it
  violates the single-writer/evidence boundary.
- Revive or hand-edit a terminal predecessor: it destroys incident evidence.

## Evolution

The MCP SDK, Gateway implementation, route record layout and derived metrics
may change. Replacements must preserve host-attested single-writer mutation,
original-outbox recovery without reexecution, current artifact/dispatch/PASS
binding, explicit-only migration, immutable predecessor evidence, and bounded
transport degradation.
