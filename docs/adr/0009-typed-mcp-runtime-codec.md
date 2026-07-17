# ADR 0009: Use a typed MCP runtime codec

- Status: Accepted
- Date: 2026-07-17

## Context

Codex App may start a non-PTY command with stdin already at EOF and therefore
return no writable session. Generated Packs nevertheless required a later
same-session stdin write as their only payload materialization, verification,
and report-staging path. That mechanism made a host process detail a liveness
dependency even though the installed MCP server already provides a bounded,
typed request channel.

## Decision

Expose `runtime_codec` from `codex-loop-state` with five closed operations:
`MATERIALIZE_DISPATCH`, `VERIFY_DISPATCH`, `STAGE_REPORT`,
`STAGE_EXTERNAL_RECEIPT`, and `NORMALIZE_FINGERPRINT`. Each operation uses a
strict `oneOf` schema, bounded structured arguments, strict UTF-8 strings, and
fail-closed validation. Generated Packs use this tool and stop with
`RUNTIME_CODEC_TOOL_UNAVAILABLE` when it is absent. Legacy CLI stdin modes stay
available for compatibility and return `INPUT_TRANSPORT_EOF_BEFORE_FRAME` when
EOF arrives before any frame bytes.

## Consequences

Codec work no longer depends on a shell session id or writable child-process
stdin. The MCP server remains the authenticated installed process boundary.
Report and external-receipt staging still writes only runtime-owned confined
spool paths. State mutation remains on its existing v3.2 compatibility path;
v3.3 moves canonical writes to a separate State Gateway decision.

## Evolution

The MCP SDK, internal function layout, and CLI adapter may change. Replacements
must preserve a bounded single-frame contract, strict UTF-8, exact string
semantics, closed typed operations, and zero-side-effect failure.
