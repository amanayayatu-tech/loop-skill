# Upstream Codex App controller-turn attestation blocker

## Release status

`BLOCKED_BY_APP_ATTESTATION` is a P0 release blocker. The repository runtime now
fails closed before a route lease or takeover when trusted caller-turn metadata
is absent. This is mitigation and truthful capability reporting, not closure of
one-route-per-real-App-turn enforcement.

## Observed boundary

On 2026-07-15, Codex App MCP request metadata exposed an
`x-codex-turn-metadata.turn_id` at the trusted tool boundary. A direct shell tool
child for the same task exposed the thread identity but no caller-turn identity.
Consequently, the standalone Python runtime cannot distinguish a real App turn
from a model-generated replacement string.

Copying the MCP value into mutation JSON, argv, a shell environment variable,
task title, prompt marker, timestamp, or UUID does not solve the problem: all of
those surfaces remain writable or selectable by the Controller.

## Repository behavior

- `AdaptiveStateRuntime.apply` accepts trusted metadata only through a separate
  in-process argument, never from the mutation envelope.
- `ACQUIRE_LEASE` and `TAKEOVER_LEASE` compare the claimed thread/turn identities
  with that metadata before consuming the canonical turn ledger.
- Missing metadata returns `BLOCKED_BY_APP_ATTESTATION`.
- Invalid or mismatched metadata is rejected with zero durable side effects.
- Exact idempotent replay may return the stored result without creating another
  route or requiring a second attestation.
- The standalone CLI has no trusted metadata channel, so route creation through
  it is intentionally blocked.

Tests may construct the in-process metadata object to verify runtime semantics.
The Python value type does not authenticate its own provenance. That test
harness is not App attestation evidence and cannot satisfy the release or
canary gate; trust exists only when an upstream host-owned process controls the
call and does not expose the argument to model-directed code.

## Minimum upstream requirement

Codex App/app-server must pass the already-trusted caller thread and turn
identities to the state mutation runtime through a channel the model and shell
command cannot set, replace, or replay. Acceptable shapes include:

1. a dedicated App/MCP state-mutation tool that validates request metadata at
   the server boundary and invokes the runtime in-process; or
2. an authenticated, single-use capability bound by the app-server to the exact
   thread, turn, tool call, and request digest, verified independently of JSON,
   argv, and ordinary environment variables.

The integration must then prove that one real App turn cannot acquire a second
route by changing any payload-controlled identity. Until that canary passes,
release, installation, Controller Pack migration, heartbeat resume, and the
paused production Loop remain prohibited.

## Evidence hygiene

This report intentionally excludes raw rollout records, user payloads,
canonical project state, databases, credentials, generated Packs, and provider
receipts. The boundary observation and synthetic regression tests are
sufficient to describe the upstream requirement.
