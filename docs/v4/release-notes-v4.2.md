# LoopSkill 4.2.0 release notes

Status: publication is established only by the public v4.2.0 tag and GitHub
Release readback.

LoopSkill 4.2.0 turns the v4.1 bounded single-Attempt path into a recoverable
long-horizon Build Loop while retaining the explicit
`INTAKE → PREPARE → CONFIRM → START` boundary and v4-only hard break.

## What changed

- PlanDocument and PlanIndex v2 declare requirements, worker profile,
  capabilities, independent verifiers, human/time gates, optional Goals,
  failure policy, replay safety, recovery policy, and at most three Attempts.
- `loopskill4 list`, `status --loop`, `run`, `continue`, `pause`, and the
  `WAITING_BUDGET`-only `budget-extend` make
  multiple per-Loop Stores discoverable without creating a second state writer.
- A foreground run continues across Goals until completion or an actual human,
  time, budget, repeated-failure, or unsafe-replay waiting boundary.
- Attempt timeout configuration has one source and permits 1–30000 seconds.
  Plan v2 sessions are non-ephemeral; owner-only evidence binds input, PID,
  session, JSONL, result controls, elapsed time, and terminal result.
- A restart reads back a completed Attempt. An interrupted replay-safe session
  may consume one recorded `codex exec resume`; a live process is never resent.
  PID plus process-start identity prevents PID reuse from impersonating it, and
  the macOS token is locale/timezone independent. Initial and resumed deadlines
  survive controller restart, and interrupted resume compute remains charged.
- Independent verification now supports exact argv commands, loopback HTTP
  routes, file existence/change/SHA-256, human approval, real-time gates, and
  optional capability skip-with-evidence.
- Repairable failures stay in the same Loop. Attempt counts and repeated
  failure fingerprints are scoped per Goal; a repeated fingerprint waits with
  a concrete recovery action instead of terminalizing the PRD.
- Plan v2 supports 1–128 Goals and a 512 KiB canonical Plan while sending only
  the current Goal and referenced requirements to Host.
- Receipt-valid v4.1.1 installs upgrade transactionally to v4.2.0. The installer
  preserves config, Store data, old receipts, and exact rollback bytes until
  the new active pointer commits.
- Public discovery and status projections open Stores read-only. Human and time
  waits require an exact Goal-bound gate digest; generic resume cannot bypass
  those gates.
- Command verifier output is bounded while being read. Loopback HTTP verification
  rejects a preoccupied port, disables ambient proxies, and cannot block on an
  undrained server-output pipe.

## Safety boundary

LoopSkill still does not register MCP, does not require an App restart, does
not require a Codex App restart, and does not import v3
state, expose credential values, or authorize automatic publication. Remote
cross-system actions are not claimed exactly-once. Unknown external outcomes
remain visible and are never converted into success. This release does not
support multiple Hosts.

The Codex Host subprocess receives only the minimal runtime environment needed
to locate its executable, configured Codex home, user home, locale, timezone,
and temporary directory. Ambient project variables and credential values are
not inherited.

The independent v3 fallback remains
[v3.3.8](https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8).

The release Gate includes Linux/macOS × Python 3.11–3.14, coverage at least
80%, real v4.1.1 upgrade and rollback boundaries, long-horizon state-machine
regressions, three disposable canary layers, and exact merged-SHA/tag/release
readback. These checks prove the bound scenarios; they do not prove arbitrary
patch-success, long-horizon superiority, or a fault-free Host.
