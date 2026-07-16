# ADR 0007: Represent unavailable negotiated MCP protocol explicitly

- Status: Accepted
- Date: 2026-07-16

## Context

The App host may not expose the initialize exchange. A client-requested version
and a server-supported set are separately sourced observations, not proof of the
negotiated result.

## Decision

The App receipt records either a host-verified negotiated value or
`UNAVAILABLE_BY_HOST` with a null value. Client and installed-server observations
remain separate and source-qualified. Host unavailability alone is not a
release blocker when all behavioral and identity gates pass.

## Consequences

Receipts do not guess a version or overstate compatibility. Consumers must
distinguish verified negotiation from declared/requested capabilities.

## Evolution

If a future App exposes the exchange, use the verified branch of the versioned
receipt schema. New observation sources require explicit provenance and tests.
