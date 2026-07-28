# LoopSkill 4.0.0 release notes

These are the release notes for LoopSkill 4.0.0. Public-release identity is
established only after exact-SHA local gates, v4 PR/main/tag CI, annotated tag
`v4.0.0`, and GitHub Release readback all pass.

LoopSkill 4 is a v4-only breaking release. It replaces the v3 protocol,
persistence model, control identity transport, Pack/MCP execution path, and
Codex boundary with a small deterministic Kernel, one typed wire authority,
one SQLite state authority, capability libraries, and one Codex Host Adapter.
The production Adapter now consumes one foreground official
`codex exec --json --output-schema` invocation instead of owning the experimental external
app-server thread/turn lifecycle.

## User experience

- One goal or goal file enters `INTAKE → PREPARE → CONFIRM → START`.
- Confirmation remains a mandatory human authorization boundary before real
  external effects; “one entry” never means silent permission.
- Users no longer copy thread/task/route/effect IDs, SHA values, receipts,
  Pack identity, Gateway schema, MCP/App enum, heartbeat, readback, or retry
  parameters.
- Normal status shows objective, progress, result, limitations, and next
  action. Internal identities appear only in diagnostics.
- `UNKNOWN` and `UNVERIFIABLE` are visible honest outcomes and never cause a
  blind automatic resend.
- Standard and Adaptive remain optional policy; a minimal task needs no policy
  pack.

## Hard break from v3

LoopSkill 4 cannot open, import, repair, run, or automatically migrate v3
loops, Controller Packs, state, MCP data, or old CLI surfaces. It performs zero
writes and returns `USER_UNSUPPORTED_LEGACY_VERSION`. LoopSkill
[v3.3.8](https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8)
remains independently available and unchanged.

The LoopSkill 4 installer and uninstaller do not register MCP, edit Codex
`config.toml`, or require a Codex App restart. During the first real invocation
in a fresh workspace, the official Codex Host may append one exact workspace
trust record with `trust_level = "trusted"`; this Host-owned effect is measured
separately and is not attributed to installation. LoopSkill installs under a
distinct v4 identity and does not overwrite an existing v3 installation.

## Safety preserved and redesigned

- per-loop CAS, local operation idempotency, one writer, durable outbox, exact
  Attempt identity, honest lost-evidence classification, and no blind resend;
- machine-owned Actor/Grant/handle/version/receipt/digest/Host identity;
- immutable content digests, path confinement, existing-Git/non-Git/new-Git
  capture, exact artifact/report/review/finalization bindings;
- bounded repair, immutable terminal evidence, honest limitations, and
  successor history that cannot rewrite its predecessor;
- rebuildable audit/archive/privacy/metrics projections that never become a
  second state authority.
- one bounded foreground Codex process group, strict JSONL terminal validation,
  a typed-manifest-derived closed outcome/summary schema with no prose-marker
  fallback, same-process result/schema digest binding, and `UNKNOWN` without
  resend when process, stream, schema, or terminal evidence is lost.

## Honest claim boundary

4.0 supports only the Codex Host Adapter. A host-neutral Kernel is not a
multi-host claim. The release does not promise cross-system exactly-once,
empirical patch-success superiority, long-horizon efficacy, or Host memory
isolation beyond what the Host can actually attest.
It does not promise Desktop-visible saved projects/tasks, provider
idempotency, cross-process lifecycle readback, or automatic `exec resume`.

No binary asset is required for installation. Reproducible source from the
annotated tag is the release artifact unless the final release packet lists a
reviewed additional asset with SHA-256.
