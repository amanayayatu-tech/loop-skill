# ADR 0004: Migrate Packs without replacing Controller or heartbeat identity

- Status: Accepted
- Date: 2026-07-16

## Context

Controller Pack bytes can evolve during a long Loop. Replacing the Controller
or heartbeat would split history, route authority, and recovery identity.

## Decision

Migrate Pack identity only at a paused safe point through a journaled prepare,
exact same-heartbeat prompt update/readback, and commit. Preserve the Controller,
automation id, role registry, predecessor Pack history, and rollback evidence.
Routing resumes only after the target prompt is observed active on that same
heartbeat.

## Consequences

Migration is deliberately stricter than ordinary code rollout and may remain
paused when App readback is unavailable. Historical identities are immutable.

## Evolution

Archival layout and transaction steps may change. Equivalent designs must keep
one Controller, one heartbeat, exact target readback, and auditable rollback.
