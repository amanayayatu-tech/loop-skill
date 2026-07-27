---
name: loopskill4
description: Start and operate a LoopSkill 4 loop through read-only intake, local preparation, explicit boundary confirmation, and one machine-owned start.
---

# LoopSkill 4

## Purpose

Use LoopSkill 4 for durable, multi-step work that benefits from explicit
acceptance criteria, bounded side effects, resumable state, artifact-bound
review, and honest finalization. For a short one-off task, return
`DIRECT_TASK_RECOMMENDED` and do not create a loop.

## Public entry

Use the installed `scripts/loopskill4` entry. A goal may be literal text or one
UTF-8 goal file. The ordinary flow is always:

1. `INTAKE` — read-only quality check; no loop, Host task, heartbeat, or effect.
2. `PREPARE` — write only the declared local manifest, boundary, plan, Chinese
   guide, and bundle; no Host or execution effect.
3. `CONFIRM` — show goal, write scope, budget, external actions, acceptance,
   stop conditions, and commit/push/publish/deploy boundaries. Confirmation is
   explicit and digest-bound; changed preparation invalidates it.
4. `START` — accept only a valid confirmation, commit one canonical startup
   Attempt, and let the Codex Adapter create/read back at most one Host resource.

One `loopskill4 start <goal-or-file>` invocation may conduct the four phases in
one interactive session, but it must stop at the explicit confirmation point.
Never use `--yes`, defaults, or a noninteractive fallback to bypass a
high-impact authorization boundary.

## Authority boundary

The user and model provide semantic intent only. They never supply or become
authority for task/thread/route/effect/artifact/review/finalization IDs,
operation IDs, versions, digests, receipts, Host enums, retry/readback details,
or provider arguments. LoopSkill 4 generates, resolves, and validates those
values mechanically. Ordinary output shows only goal, progress, result,
limitations, and the next action. Internal identity appears only in explicit
diagnostics.

## Safety and liveness

- One typed protocol manifest owns wire literals; one transactional store is
  the canonical writer.
- External effects receive at most one automatic attempt. A lost response with
  no authoritative readback becomes `UNKNOWN`, never a blind resend.
- Cooperative evidence may close work with `LIMITATION` or `UNVERIFIABLE`; it
  must not pretend to be strict Host-attested completion.
- Result, Report, Artifact, Review, Finalization, execution disposition, and
  assurance remain separate.
- Standard and Adaptive coordination, Reviewer, Local Verifier, Decision Card,
  and bounded repair are optional policy capabilities. A minimal loop loads no
  policy pack.

## v3 hard boundary

LoopSkill 4 cannot open, import, repair, or run LoopSkill 3 loops, state, or
Controller Packs. It performs zero writes when it detects them and points to
the independent [v3.3.8 release](https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8).
There is no automatic migration, compatibility facade, State Gateway,
State-Writer, or MCP registration in LoopSkill 4.

## Examples

```text
Use $loopskill4 to intake this goal: update the bilingual API guide and verify every example.
```

```text
Use $loopskill4 with ./goal.json. Prepare the boundary, show it, and wait for my explicit confirmation before START.
```

Do not claim patch-success superiority, cross-system exactly-once, multi-host
support, or long-horizon efficacy. The first release has one Codex Host Adapter.
