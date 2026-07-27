# LoopSkill 4.0.0 release notes — draft, not released

LoopSkill 4 replaces the v3 control protocol, persistence model and Codex
boundary while retaining evidence binding, deterministic replay, bounded
repair, artifact correctness, explicit finalization, path safety and
conflict-safe distribution.

User-visible changes:

- one goal file or one main command remains the default entry;
- `INTAKE → PREPARE → CONFIRM → START` is explicit and cannot be bypassed for
  meaningful side effects;
- users no longer copy thread/task/route/outbox IDs, SHA, receipts, schemas,
  App enums, heartbeat/readback or retry parameters;
- `UNKNOWN` and `UNVERIFIABLE` are visible honest outcomes, with no blind
  automatic resend;
- internal identity appears only in diagnostics/export;
- v3 loops remain unchanged and readable; migration is previewed, explicitly
  confirmed, cancellable and written to a new v4 root;
- Standard is the default bounded long-task mode; Adaptive and advanced review
  policy are optional and do not enlarge the minimal path.

Compatibility does not promise identical old flags, wording, Controller Pack
bytes, the v3 97-field write API, Markdown Pack as execution truth, State-
Writer, Supervisor, dual write, or Host enums in Kernel.

Publication checklist remains intentionally empty. A future release requires a
separate author approval after reviewing the exact-SHA RC packet.
