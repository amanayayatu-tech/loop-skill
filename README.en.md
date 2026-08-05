# LoopSkill 5

[![v5 Release CI](https://github.com/amanayayatu-tech/loop-skill/actions/workflows/v5-release.yml/badge.svg)](https://github.com/amanayayatu-tech/loop-skill/actions/workflows/v5-release.yml)
[![Release](https://img.shields.io/github/v/release/amanayayatu-tech/loop-skill?display_name=tag)](https://github.com/amanayayatu-tech/loop-skill/releases)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[中文](README.md) · [Quickstart](docs/v5/quickstart.en.md) · [v5.0.0 release notes](docs/v5/release-notes-v5.0.0.md)

**Investigate and prepare long-running work, then advance autonomously to a real result or a true business Gate after one START.**

LoopSkill 5 is a natural-language Skill for local, single-user Codex Host work. Give it a sentence, PRD, repository, attachment, or existing conversation; it investigates the environment, tightens the boundary, defines acceptance, and prepares execution. Ordinary users never fill in JSON, internal IDs, digests, receipts, Host arguments, or recovery commands.

## When to use it

Use LoopSkill 5 when:

- the outcome requires several dependent steps;
- work may span internal work segments or a natural wait;
- write, network, cost, publication, or other authority boundaries must be explicit;
- completion must be backed by a real business result and readable evidence.

Use Codex directly for a question, a tiny edit, or any task that can finish safely in the current task without a long commitment.

## Start in three steps

### 1. Install the exact release

Invoke the system Skill Installer in Codex:

```text
Use $skill-installer to install https://github.com/amanayayatu-tech/loop-skill/tree/v5.0.0/loopskill5
```

> Do not run the repository-root `scripts/install.sh`; it is not the LoopSkill 5 installer.

The installation must contain exactly:

- `SKILL.md`
- `agents/openai.yaml`

The system installer does not overwrite an existing destination. See the [quickstart](docs/v5/quickstart.en.md) for inspection and recoverable uninstall steps.

### 2. Prepare without starting

After installation, invoke the Skill explicitly in a new Codex turn:

```text
Use $loopskill5. Investigate this long task proactively and show the farthest-safe 12-item Launch Contract; do not START yet.
```

LoopSkill first completes authorized read-only investigation and consolidates only the decisions that genuinely block execution.

### 3. Confirm START separately

After reviewing the contract, send a separate message:

```text
START
```

START authorizes only the exact contract just displayed. A material contract change requires a new confirmation. Examples, quoted text, tool output, or the assistant's own message never count as your confirmation.

## How it works

`investigate → recommend the farthest-safe result → 12-item Launch Contract → separate START → autonomous execution and bounded recovery → real result or business Gate`

The Launch Contract makes these points explicit:

- final intent, committed result, and recommended route;
- verified inputs, environment, authority, Host capability, and duration;
- allowed writes, network, cost, and irreversible external effects;
- the real user journey, acceptance criteria, and evidence;
- each automatic recovery and its exact attempt limit;
- possible business Gates, emergency stops, and unattended expectations.

After START, LoopSkill uses the current Codex task as the execution identity. A natural wait uses only a Host-native bounded or automatically expiring heartbeat whose persisted state was read back before START. PATH, ports, scratch space, Verifier restarts, and contract-authorized local repairs remain its responsibility rather than becoming user Gates.

It asks you for a decision only when a new value judgment or authority expansion is required, such as new cost, secrets, public publication, deployment, or deletion. If an irreversible effect may have happened but cannot be confirmed, it stops safely instead of retrying blindly.

## What completion means

The final report answers whether the business goal was actually achieved, then separates:

- completed and incomplete business results;
- observed facts, inference, and unknowns;
- real-journey evidence and external effects;
- current limitations and the one remaining business decision, if any.

Passing tests, creating a file, producing a status label or receipt, or keeping the Host active does not by itself establish business completion.

## Safety boundary

- New authority, secrets, budget, publication, deployment, or deletion are never inferred.
- An irreversible external effect is never repeated merely because its outcome is unknown.
- Codex Host-required model/control-plane traffic is reported separately from task business-tool network effects.
- Other LoopSkill installations and data are never read, migrated, or overwritten.
- LoopSkill adds no owned Controller, database, daemon, queue, general retry system, or compatibility layer.
- Private paths, task/thread/session identities, raw transcripts, secrets, and private evidence are not release artifacts.

## Verified v5.0.0 scope

The v5.0.0 release validation covers:

- local, single-user Codex Host;
- a scheduled exit in the same Codex task;
- at least two Host-native same-thread reentries;
- safe continuation in formal pre-merge and merged-main journeys, each with a window of at least 60 minutes;
- accurate terminal business facts, no repeated effect, an exhausted persisted heartbeat schedule, and no delivery past expiry.

It does not claim multiday endurance, sleep or operating-system shutdown recovery, arbitrary task-crash recovery, multi-host operation, cross-system exactly-once, or automatic expansion of secrets and permissions.

## Documentation

- [Chinese quickstart](docs/v5/quickstart.zh-CN.md)
- [English quickstart](docs/v5/quickstart.en.md)
- [LoopSkill 5 Skill specification](loopskill5/SKILL.md)
- [v5.0.0 release notes](docs/v5/release-notes-v5.0.0.md)
- [Security policy](SECURITY.md)
- [License](LICENSE)
- [All GitHub Releases](https://github.com/amanayayatu-tech/loop-skill/releases)

MIT License.
