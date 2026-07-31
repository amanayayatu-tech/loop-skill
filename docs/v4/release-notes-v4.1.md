# LoopSkill 4.1.1 release notes

Status: LoopSkill 4.1.1 is the current public v4 release.

LoopSkill 4.1 helps turn work that can outlive one chat into a bounded process:
state the goal, inspect the scope, confirm once, and check the result against
machine evidence. The visible flow remains
`INTAKE → PREPARE → CONFIRM → START`; it does not silently start a Host task.

## Patch fix

- When the current working directory carries a v3 `.codex-loop` marker, v4.1.1
  stops before `PREPARE`, `START`, or `status --refresh`. It creates no prepared
  artifacts, Store, or Host task, and returns the existing
  `USER_UNSUPPORTED_LEGACY_VERSION` boundary.

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
- LoopSkill 4 is a v4-only hard break. It does not open, import, repair, or
  automatically migrate v3 data. Users who need the historical v3 line can use
  [LoopSkill v3.3.8](https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8).

## Safety boundary

LoopSkill still uses one canonical Store writer, at-most-one automatic Attempt
per activation, bounded foreground Codex execution, and honest `UNKNOWN` /
`UNVERIFIABLE` outcomes. It does not register MCP, edit Codex configuration,
require an App restart, start a daemon, restore v3 runtime, promise cross-system
exactly-once, support multiple Hosts, or claim patch-success or proven
long-horizon superiority.

The original v4.1.0 release used deterministic matrices plus fresh 2-Goal and
8-Goal real Host canaries. For this scoped v4.1.1 boundary hotfix, the author
explicitly replaced a new Host canary with the direct v3-cwd zero-write
regression, the complete deterministic suite, isolated distribution tests, and
exact-SHA pull-request/main/tag CI. A superseded candidate's two semantic Goals
passed before its shared Host config integrity check failed; that failure is
preserved, is not a v4.1.1 release receipt, and no fresh Host canary is claimed.
