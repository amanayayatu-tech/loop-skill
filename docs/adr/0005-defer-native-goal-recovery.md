# ADR 0005: Defer lost native Goal generation recovery

- Status: Accepted
- Date: 2026-07-16

## Context

The current Codex App does not expose a create-paused, restore, resume, or rebind
operation that can safely commit recovery state before a recreated Goal starts
automatic work. A substitute Goal would not preserve the original identity.

## Decision

Keep the capability `DEFERRED`. Legacy CLI, runtime, and MCP entrypoints return
`NATIVE_GOAL_GENERATION_RECOVERY_UNAVAILABLE` with `side_effects=NONE`. Preserve
historical fields and blocker receipts, keep the exact heartbeat paused, and do
not create replacement Goals, tasks, sessions, Controllers, or heartbeats.

## Consequences

A Loop that requires the lost native identity remains blocked, while unrelated
supported features and releases are not blocked by the deferred capability.

## Evolution

Supersede this ADR only when the host exposes same-identity recovery primitives
and a reviewed exact-SHA App test proves atomic recovery before dispatch.
