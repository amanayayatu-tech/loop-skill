# ADR 0002: Allow one route per real host turn

- Status: Accepted
- Date: 2026-07-16

## Context

Goal continuation, automatic wakeups, and recovery can overlap. Model-authored
ids cannot prove which App turn owns a mutation, and allowing a turn to reacquire
after release permits duplicate business routes.

## Decision

Derive route identity from validated host-owned MCP metadata delivered by the
trusted direct app-server parent. Record every attested turn in a durable ledger
and allow it to reserve only one business route, even after its lease is
released or completed. A second route fails before side effects.

## Consequences

Session and thread identities remain useful context but do not replace turn
identity. Missing host attestation disables mutation routing while leaving
read-only inspection available.

## Evolution

A future host channel may replace current metadata parsing if it provides equal
or stronger provenance. Lease storage and timing may change without weakening
the one-turn/one-route property.
