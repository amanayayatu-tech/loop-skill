# LoopSkill 4.1.0 release-candidate notes

Status: `V4_1_RC_READY_AWAITING_AUTHOR_RELEASE_AUTHORIZATION` is the only
pre-publication completion state. These notes do not claim a tag, GitHub
Release, installation, deployment, or supported public line.

## User-visible changes

- Start from one sentence, pasted PRD text, or one explicitly authorized UTF-8
  text/Markdown file. Ordinary users do not write JSON.
- Conversational intake retains confirmed answers for the current session and
  asks at most three questions that truly block preparation.
- PREPARE shows the confirmed boundary, plan summary, and capacity report.
  `START THIS LOOP` remains an exact, independent user confirmation.
- One confirmed plan may contain 1–32 Goals. Only the current Goal is activated;
  subsequent Goals reuse the existing atomic `AdvanceGoal` transition.

## Capacity and compatibility

- Canonical PlanDocument: at most 128 KiB.
- Explicit UTF-8 text/Markdown source: at most 256 KiB.
- CreateLoop release target: 8 KiB / 64 members; hard limit remains 16 KiB /
  128 members.
- Materialized Host prompt target: 24 KiB; hard limit remains 32 KiB. Overflow
  is rejected before Host execution and is never truncated.
- New Loops use `CONTENT_ADDRESSED_V1`. Existing `EAGER_V4_0` stores support
  status, export, and original-reducer continuation only. There is no migration,
  rewrite, or dual write.

## Safety boundary

LoopSkill still uses one canonical Store writer, at-most-one automatic Attempt
per activation, bounded foreground Codex execution, and honest `UNKNOWN` /
`UNVERIFIABLE` outcomes. It does not register MCP, edit Codex configuration,
require an App restart, start a daemon, restore v3 runtime, promise cross-system
exactly-once, or claim proven long-horizon superiority.

The local release gate requires deterministic matrices plus a fresh 2-Goal and,
only after it passes, a fresh 8-Goal real Host canary on the same exact clean
candidate. Those 10 invocations are product validation, not research evidence.
