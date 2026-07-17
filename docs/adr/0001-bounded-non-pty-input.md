# ADR 0001: Use bounded direct non-PTY input

- Status: Superseded
- Superseded by: docs/adr/0009-typed-mcp-runtime-codec.md
- Date: 2026-07-16

## Context

Adaptive runtime modes receive structured frames from an App-controlled process
surface. Waiting for EOF can retain a process when the writer remains open, and
shell or PTY framing can change bytes and cleanup behavior.

## Decision

Launch the runtime directly with a writable non-PTY stdin pipe. Accept one
strict UTF-8 JSON frame within explicit time and size bounds and finish as soon
as the complete frame is available. Reject malformed, duplicate, non-finite,
multi-frame, trailing, oversized, invalid-encoding, or timed-out input with a
structured failure and no state mutation.

## Consequences

Callers need a process API that supports direct argv and same-session stdin.
Temporary-file redirection and shell framing are not equivalent evidence. The
runtime can still support closed-pipe EOF for compatibility.

## Evolution

The parser, process library, and numeric bounds may change. A replacement must
preserve bounded completion, exact framing, cleanup, and fail-closed behavior.
v3.2.8 adopts that allowed evolution through the typed MCP runtime codec in
[ADR 0009](0009-typed-mcp-runtime-codec.md). Direct stdin remains a legacy CLI
compatibility mechanism, not a generated-Pack requirement.
