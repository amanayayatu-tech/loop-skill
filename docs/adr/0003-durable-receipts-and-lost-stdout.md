# ADR 0003: Recover durable receipts instead of retrying lost stdout

- Status: Accepted
- Date: 2026-07-16

## Context

An external call can complete while its stdout is lost. Retrying from transport
uncertainty can duplicate paid work or irreversible effects.

## Decision

Persist route-bound STARTED evidence before sending and immutable COMPLETED
evidence before relying on stdout. Recover a matching COMPLETED receipt without
another send. Treat a lone STARTED receipt as an unknown outcome that consumes
the conservative call allowance and forbids automatic retry.

## Consequences

Receipts require exact provider, request, call index, artifact, route, and Pack
identity. They exclude prompts, responses, credentials, and secrets. Availability
may be sacrificed to preserve at-most-once effects.

## Evolution

Receipt storage and projection may change. Any replacement must retain durable
pre-send identity, immutable completion evidence, and no-retry recovery.
