# Codex App controller-turn attestation integration gate

## Release status

Codex app-server already injects trusted turn metadata into every MCP tool call.
The repository now ships a narrow STDIO MCP bridge that consumes that metadata,
attests its direct signed app-server parent, and exposes only route lease and
takeover mutations. P0 remains open until the exact release candidate passes a
real App two-route canary; synthetic tests alone are not closure.

## Observed boundary

On 2026-07-15, the running Codex App and the official Codex source both showed
that MCP requests receive `x-codex-turn-metadata.turn_id` plus a host-owned
thread id after model arguments are parsed. A direct shell child does not own
that boundary. The standalone runtime therefore stays fail-closed; only the
dedicated bridge may construct trusted runtime metadata.

Copying the MCP value into mutation JSON, argv, a shell environment variable,
task title, prompt marker, timestamp, or UUID does not solve the problem: all of
those surfaces remain writable or selectable by the Controller.

## Repository behavior

- `adaptive_state_mcp.py` exposes only `route_state_mutation` over STDIO MCP.
- It verifies the direct parent command, strict macOS code signature, identifier
  `codex`, OpenAI Team ID `2DC432GLL2`, and Codex-owned MCP request metadata.
- Model arguments omit `controller_turn_id`; the bridge injects the attested id
  and rejects any conflicting explicit claim.
- `ACQUIRE_LEASE` and `TAKEOVER_LEASE` require metadata thread id to equal the
  outer request `threadId`; session id remains required but may differ after
  fork/resume. The independent turn id owns the canonical one-route ledger.
- Missing metadata returns `BLOCKED_BY_APP_ATTESTATION`.
- Invalid or mismatched metadata is rejected with zero durable side effects.
- Exact idempotent replay may return the stored result without creating another
  route or requiring a second attestation.
- The standalone CLI has no trusted metadata channel, so route creation through
  it is intentionally blocked.

Tests may construct the in-process metadata object to verify runtime semantics.
The Python value type does not authenticate its own provenance. A shell-launched
bridge is also rejected because its parent is not the signed app-server. Neither
synthetic path is App attestation evidence; trust is established only by the
real MCP process boundary and its release-candidate canary.

## Remaining real App gate

The repository installer now atomically registers the bridge as the direct-command
`codex-loop-state` STDIO server, rejects wrappers/extra execution semantics,
verifies exact command/args and installed SHA, and writes a zero-drift manifest.
That implementation and its isolated tests are not proof that the current App
has refreshed and launched it. The exact release candidate still needs a real
App canary proving that one Controller turn cannot acquire a second route while
a later real turn can route. Until the same-SHA receipt and server release gate
pass, real installation, Controller Pack migration, heartbeat resume, and the
paused production Loop remain prohibited.

## Evidence hygiene

This report intentionally excludes raw rollout records, user payloads,
canonical project state, databases, credentials, generated Packs, and provider
receipts. The boundary observation and synthetic regression tests are
sufficient to describe the upstream requirement.
