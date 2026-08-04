# LoopSkill v5.0.0 release notes

Publication is established only by the public annotated `v5.0.0` tag, its peeled merged-main commit, green main/tag CI, the matching latest non-prerelease GitHub Release, and final public readback. This file or a branch alone is not a release claim.

## What is new

- A natural-language Codex Skill that prepares long local, single-user tasks before one explicit START.
- Proactive investigation and concrete recommendations that extend the unattended span.
- A 12-item human Launch Contract covering the real result, authority, acceptance, recovery, business Gates, emergency stops, timing, and external effects.
- Host-native task/thread continuation and bounded heartbeat reentry for natural waits, with one minimal effect fact rather than a LoopSkill-owned control plane.
- Business-first reporting that distinguishes artifacts, test results, fixture approvals, Owner decisions, and public publication.

## Distribution identity

The v5 product consists of exactly:

- `loopskill5/SKILL.md`
- `loopskill5/agents/openai.yaml`

Install those files with the system Codex Skill Installer from the exact `loopskill5` path at tag `v5.0.0`. The installer refuses to overwrite an existing install. Uninstallation moves only the exact `loopskill5` directory recoverably outside `skills`.

The root `VERSION=4.2.0`, `scripts/install.sh`, `loopskill4`, old tags/Releases, and old data remain the independent v4 runtime identity. v5 does not import, migrate, repair, revive, or dual-write v3/v4 data.

## Deliberate non-features

v5.0.0 does not add a LoopSkill-owned Controller, state machine, schema, database, daemon, queue, router, general Host adapter, general retry system, compatibility layer, or migration path. Development-only test harnesses are not release artifacts.

## Claim limits

- Local, single-user Codex Host is the first-release surface.
- The verified release claim is limited to a scheduled exit in the same Codex task, at least two Host-native same-thread reentries, and safe continuation in each formal pre-merge and merged-main journey of at least 60 minutes.
- Before START, the bounded or automatically expiring heartbeat must be persisted and read back with enough recurrence capacity for the eligible reentries, final readback, and measured scheduling jitter. Terminal acceptance requires accurate business facts, no repeated effect, `next_run_at=NULL`, and observation past expiry with no future delivery; physical identity deletion is best-effort housekeeping rather than a business PASS Gate.
- Multiday endurance remains post-release validation and is not claimed by v5.0.0.
- Sleep and operating-system shutdown recovery are not promised.
- Fixture approvals do not represent Owner endorsement of public content.
- No cross-system exactly-once, multi-host, arbitrary task-crash recovery, provider-wide publication, or automatic secret/permission expansion is claimed.
- Private run paths, task/thread/session identities, raw transcripts, secrets, and private evidence are not release artifacts.
