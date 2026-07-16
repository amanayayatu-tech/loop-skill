# ADR 0008: Close a Loop only at FINALIZATION_ACKED

- Status: Accepted
- Date: 2026-07-16

## Context

Worker PASS, review PASS, `FINALIZE_LOOP`, and core state closeout each prove
only part of completion. External Goal and heartbeat observations can still be
missing or mismatched.

## Decision

Canonical `FINALIZATION_ACKED` is the sole closeout gate. It consumes the exact
one-use finalization capability and binds the review chain, final artifact,
Controller Goal outcome, paused heartbeat observation, and receipt identity.
Intermediate statuses remain nonterminal evidence.

## Consequences

The system may report pending external synchronization after all product work
passes. Blocked closeout remains distinct from successful completion.

## Evolution

Adapters and receipt fields may evolve through compatible schema changes. The
atomic evidence-bound acknowledgement cannot be replaced by prose or a weaker
intermediate state.
