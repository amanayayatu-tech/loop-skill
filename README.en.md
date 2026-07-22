# Codex Loop Prompt Architect

[简体中文](README.md) | English

[![Compatibility CI](https://github.com/amanayayatu-tech/loop-skill/actions/workflows/compatibility.yml/badge.svg)](https://github.com/amanayayatu-tech/loop-skill/actions/workflows/compatibility.yml)
[![Release](https://img.shields.io/github/v/release/amanayayatu-tech/loop-skill?display_name=tag)](https://github.com/amanayayatu-tech/loop-skill/releases)

**Turn a complex task that could drift across long chats into a Codex App workflow that can be handed off, reviewed, verified, and decisively closed.**

![Xiaohei carries a durable case of task records, checkpoints, and evidence through temporary chat rooms that close behind him](docs/readme-assets/durable-handoff.png)

Chats end. Windows refresh. The work rarely ends at the same moment. The hardest part of a long-running job is often not whether a model can write code, but whether scope drifts, evidence scatters across tasks, failures trigger duplicate work, and “done” becomes nothing more than a confident sentence.

`codex-loop-prompt-architect` designs Controller Packs for that kind of work in the **Codex macOS App**. It first checks whether the request deserves a Loop, then turns objectives, roles, permissions, evidence, repair limits, and completion rules into a validated operating contract.

It **designs the Loop and generates the Pack**. It does not implement the target project for you, and one invocation does not silently launch an unattended run.

## OpenAI Build Week 2026

LoopSkill had a foundation before the event and was meaningfully extended with **Codex and GPT-5.6** from July 13–17, 2026. Codex was the primary engineering environment for this work, with GPT-5.6 used across implementation, incident analysis, test design, documentation, review, and release hardening.

The Build Week work added or strengthened bilingual onboarding, an evolvable project specification and validator, sharded compatibility CI, typed MCP runtime payloads, historical-state repair protections, and the fail-closed retirement of an unavailable native Goal recovery path. The public history records **75 commits across 102 changed files** during the period, culminating in [`v3.2.8`](https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.2.8).

## 30-second quickstart

Requirements: macOS, Codex App, Git, and Python 3.9+.

```bash
git clone https://github.com/amanayayatu-tech/loop-skill.git
cd loop-skill
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
./scripts/install.sh
```

If an existing `codex-loop-state` entry points to the same installed skill
bridge, the installer retains that registered absolute Python runtime and
atomically replaces the skill. A different bridge, extra execution fields, or
an invalid runtime remains a conflict and rolls back; do not hand-edit config
to bypass it.

Open a new task in Codex App after installation. Start with a read-only intake:

```text
Use $codex-loop-prompt-architect in intake-only mode.
Decide whether the requirement below is ready for a Loop, ask only the
highest-priority blockers, and do not generate a Controller Pack yet:
...
```

When the requirement is ready, generate the Pack:

```text
Use $codex-loop-prompt-architect to design a Loop for the long-running task
below. Run the Intake Gate first; ask me about missing information, and only
generate the Controller Pack after READY_FOR_LOOP:
...
```

Starting the work is an explicit three-step handoff:

1. **The skill generates the Pack**: one self-contained Controller Pack Markdown file and a separate Simplified Chinese usage guide.
2. **You confirm the boundary**: review the objective, write scope, budget, external actions, acceptance criteria, and stop conditions.
3. **You start the real Loop**: create a real Controller task in Codex App and use the Pack as its launch input. Actual orchestration begins only here.

If Intake returns `DIRECT_TASK_RECOMMENDED`, asking Codex to do the task directly is usually faster. A Loop is not a ceremony every task must endure.

## Startup gate for a formal long-running Loop

On the first intake or generate invocation in each new session, the skill runs a read-only doctor. The same checks are available directly:

```bash
scripts/loopctl doctor --check --json
scripts/loopctl compile --input loop-source.json --check --json
scripts/loopctl canary --input compiled-manifest.json --json
scripts/loopctl audit --root /absolute/loop/root --json
```

`doctor` verifies the actual Python interpreter and dependencies, Git/worktree identity, source/install manifests, MCP configuration and schemas, and observable App/host capabilities. Its receipt cache is content-addressed by those identities and invalidates on any drift. Failure returns an exact error and remediation without creating canonical state, roles, or a heartbeat. `compile` defaults CP0 to disposable. Formal initialization additionally requires a complete registry, task/thread and heartbeat readback, five MCP lifecycle receipts, and a real disposable canary covering initialization through `FINALIZATION_ACKED`. A host model receipt is mandatory only when `required_model` or `required_reasoning` is explicit. Every canary lane and lifecycle receipt is manifest-bound and self-digest-checked; the MCP Gateway materializes the formal startup receipt from a root-confined source path instead of trusting inline request bytes.

After an App restart, the read-only MCP `host_lifecycle_readback` derives all five lifecycle receipts from the validated install receipt, exact current server registration, OpenAI-signed App parent, and current server/client/schema identities. Active-call counts come from the serial stdio dispatcher itself and exclude the readback call; the model cannot submit or self-attest zero. Install drift, an unobserved restart, concurrent calls, or an unavailable App build fails closed.

Every recoverable runtime code is mapped by one recovery registry entry to one legal next operation; `WAIT` alone is never recovery. Rejected requests are separately appended to the hash-chained, fsynced `.codex-loop/LOOP_REJECTIONS.jsonl`. It stores a request digest and minimum audit fields, never prompts, chat, credentials, or the full request. “Zero side effects” means zero canonical, product, and external effects; the declared rejection-journal append is an allowed audit effect.

A formal Goal can require a Git closeout saga. `PREPARE_GOAL_CLOSEOUT` locks the reviewed artifact, HEAD, branch, paths, and a one-use capability; `ACK_GOAL_CLOSEOUT` relies on Git readback after commit/push. `NO_COMMIT` is legal only when HEAD is unchanged and the index/worktree is completely clean. Crash recovery reuses the original closeout record, while HEAD drift, out-of-scope paths, or a remote-ref mismatch fail closed. Policy migrations use a generic descriptor and retained history while legacy repair-budget effects remain readable. Starting with `status-v5`, STATUS and the dashboard show workflow state separately from evidence completion: `COMPLETE_ARTIFACT`, `COMPLETE_WITH_LIMITATION`, `EMPIRICAL_RESULT_OBSERVED`, `FORMAL_ACCEPTED`, or `PUBLIC_RELEASED`.

## Intake before Loop generation

### Correct invocations

- `intake-only` performs read-only requirement review and returns the stable seven-part report. When status is `READY_FOR_LOOP`, section 7 includes a validated `LOOP_INPUT_JSON`, but no Controller Pack is generated.
- `generate` runs the same Intake Gate and creates a Pack only after both `READY_FOR_LOOP` and a real `--check-only` pass.
- Confirmed facts can carry forward within the same task; they should not be mechanically re-asked.
- A new task does not silently inherit the previous task. Bring the complete `LOOP_INPUT_JSON`, or the original requirement plus confirmed boundaries.

### Invocations to avoid

- Do not call `$loop-readiness-gate`; that skill does not exist, and this repository maintains no second readiness skill.
- Do not turn `NEEDS_CLARIFICATION`, `BLOCKED`, or `DIRECT_TASK_RECOMMENDED` into “ready with assumptions.”
- Do not ask intake-only mode to generate a Pack, start a Loop, create role tasks, or create a heartbeat.

The sole public Intake contract is [references/loop-intake-gate.md](codex-loop-prompt-architect/references/loop-intake-gate.md), with regression coverage in [test_loop_intake_gate.py](tests/test_loop_intake_gate.py).

## What it does

![A simplified path from request and Intake through a human-confirmed Controller Pack to execution, review, verification, and final acknowledgement](docs/readme-assets/loop-workflow.png)

A prepared Loop follows a path like this:

1. **Request**: capture the objective, scope, sources, constraints, and definition of done.
2. **Intake Gate**: separate answerable gaps, hard blockers, and small tasks that should be executed directly.
3. **Controller Pack**: define roles, Goals, permissions, evidence, retries, repair, and finalization.
4. **Human Confirm**: the user confirms the control-plane and product side effects that are actually allowed.
5. **Execute / Review / Verify**: real Workers execute, Reviewers inspect the exact artifact, and a Local Verifier checks machine-local facts when needed.
6. **Bounded Repair**: repair has a hard limit; exhaustion pauses or stops instead of spinning mechanically.
7. **Finalization**: only canonical `FINALIZATION_ACKED` closes the Loop.

The result is more than a longer prompt. It is an operating package for a Controller:

- one self-contained `<project>-codex-loop-controller-pack.md`;
- a separate guide explaining how to launch, observe, pause, and recognize abnormal behavior;
- either a fixed Standard Goal Queue or an Adaptive milestone roadmap with canonical state rules;
- explicit roles, permissions, evidence, budgets, retries, repair, STOP, and completion boundaries.

## Where it fits—and where it does not

Use it when:

- the work spans many turns, several real Codex App tasks, or more than half a day;
- Workers, a Reviewer, the MCP State Gateway, and a Local Verifier need distinct responsibilities;
- file writes, pushes, external calls, paid resources, or local verification need precise boundaries;
- results must bind a specific artifact, test run, identity, and review record;
- later evidence may change the roadmap without erasing history.

Do not use it when:

- one task, one small edit, or one direct query is enough;
- there is no testable definition of done, only a wish for the system to “keep trying”;
- the work depends on bypassing approval, secret boundaries, or third-party permissions;
- you expect absolute reliability, zero failures, or fully unattended operation.

## Standard and Adaptive

| | Standard | Adaptive |
| --- | --- | --- |
| Best for | Stable objectives and known ordering | Multiple milestones whose plan may change with evidence |
| Route | Fixed dependency-ordered Goal Queue | One Active milestone plus audited Roadmap Revision |
| State | Versioned state and events | Deterministic runtime, leases, outboxes, projections, and a full audit chain |
| Selection | Default for ready inputs | Explicitly requested or selected when Adaptive conditions apply |
| Shared boundary | Real task identity, read-only Controller, serial canonical writes, bounded repair, per-Goal review, final audit | Same |

Output detail—`compact`, `full`, or `minimal_patch`—and coordination mode—`standard` or `adaptive`—are independent axes.

## Adaptive v3.3.3: who writes state and who advances a route

New Adaptive Packs default to schema v3. They do not create a session State-Writer task. The installed MCP `state_gateway({root, request})` is the sole canonical writer. The Controller remains read-only, Workers perform product work, Reviewer/Local Verifier tasks submit evidence, and an outer Supervisor is not a product role.

**Current platform boundary:** schema v3 uses **host-cooperative evidence**. It does not claim Byzantine resistance to a malicious Controller that can forge every App call. The Gateway binds one real App task/thread, automation, send-return target, or PAUSED readback to the current host-attested turn, one PREPARED outbox, and the registered heartbeat; it derives the canonical payload digest itself, and a send observation never produces PASS. This protects against crashes, duplicate sends, stale/mismatched/replayed reports, wrong artifact/dispatch, and premature terminal projection. A normal Loop does not pin a model: it records `model_identity_requirement=NOT_REQUIRED`, `model_identity_status=NOT_APPLICABLE`, and `UNSPECIFIED` model/reasoning values without implying verification. The strict identity gate is enabled only when a manifest or Goal declares `required_model` or `required_reasoning`. In that mode the App must inject a `THREAD_CREATE_OR_READ` receipt through the non-argument `_meta.x-codex-app-action-receipt-v1` carrier; an unsupported host yields `HOST_BLOCKED`. The v1 contract accepts accurately labelled `HOST_COOPERATIVE` injected evidence only; an ordinary digest must never claim `APP_SIGNED`.

```text
Controller (read-only)
  -> State Gateway: PREPARE_ROUTE
  -> runtime_codec: MATERIALIZE_DISPATCH
  -> App send once -> RECORD_ROUTE_SENT
  -> role-owned STAGE_REPORT -> ACK_ROUTE_RESULT
```

When a formal Worker PASS cites validation files from the current run, the
target-owned `STAGE_REPORT` supplies their exact source path, SHA-256, and media
type. Runtime reads bytes only from the registered Worker's worktree and first
places them in immutable staging; the Gateway then archives those same bytes
atomically with the formal report on the original outbox. Missing, wrong-digest,
wrong-thread, unreferenced, or stale-artifact evidence rejects with zero
canonical side effects. The Controller neither copies test output nor reuses a
send receipt as validation evidence. One report may introduce at most 15
validation files, and every case-insensitive `.codex-loop/**` control-source
alias is rejected.

The Gateway derives the lease, repository snapshot, freshness, validation matrix, review handoff, current artifact, and outbox from canonical state. The Controller does not copy those objects. A PASS projection requires all three current identities for one Goal: **current artifact + current Worker dispatch + PASS formal report**. A `BLOCKED` report, stale artifact, or stale dispatch cannot become PASS.

Real user Decision Cards also go only through the Gateway. `REGISTER_DECISION`
derives the source version and context digest from current canonical state;
`RECORD_DECISION_RESPONSE` binds the selection to the current host-attested
Controller turn and stores only the supplied summary and normalized response digest. A required
browser review surface may move ports because of a local collision only when
the explicit loopback host, scheme, and path are unchanged and neither URL has
credentials, query, or fragment. Goal, Worker dispatch, artifact, configured
URL, and observed URL remain in the decision context. Wrong options, stale
artifacts, wrong paths, and replayed response identities reject with zero side
effect.

After a Worker PASS, the route is Code Review, required Local Verification, then Roadmap Audit. A nonfinal audit PASS can only use `ADVANCE_ROADMAP` over the unchanged canonical registry. A final candidate needs Final Audit, `PREPARE_FINALIZATION`, one real `automation_update` pause and matching PAUSED readback, and `ACK_FINALIZATION` before `FINALIZATION_ACKED`. Schema v3 disables the native Goal adapter and records the local `GATEWAY_NO_NATIVE_GOAL` sentinel; it is not an external Goal-tool receipt. The Gateway never manufactures `PAUSED` heartbeat evidence or accepts Controller JSON that does not exactly match the registered heartbeat. After every target Worker/Reviewer/Verifier MCP-attested stage, the runtime writes a read-only target-stage sidecar derived from the SENT outbox and report digest; the Controller can only derive and validate that proof, never forward or forge it in parameters. When stdout or task indexing is lost, `REPORT_RECOVERY` ACKs the original outbox; it never creates a second product dispatch, and the same target role can re-stage to recover cross-bridge proof.

Schema v1/v2 and `route_state_mutation` / State-Writer remain compatibility-only, with explicit `MIGRATE_V2_TO_V3`. Migration requires a PAUSED, lease-free, outbox-quiescent safe point. A terminal predecessor is immutable; continuation uses `INITIALIZE_SUCCESSOR` in a fresh root.

## Reading normal slowness, transport degradation, and terminal state

- **Normal slowness**: the same SENT outbox still has an active role or fresh evidence. Observe that route; do not dispatch again.
- **Transport degradation**: a real registered-heartbeat observation of the matching outbox/fingerprint failure is bound to the current host turn before entering canonical state. The first failure preserves the original outbox. Two natural heartbeats or fifteen minutes enter `WAITING_TRANSPORT_RECOVERY`. Canonical routing stops immediately; `ACK_TRANSPORT_PAUSE` needs a real pause followed by PAUSED readback for that exact heartbeat. After the original outbox completes or recovers, only a real ACTIVE update/readback for that same heartbeat lets `ACK_TRANSPORT_RECOVERY` atomically restore `RUNNING`; it cannot add a dispatch or repair attempt or create PASS by itself. On rejection, re-pause only if post-call canonical is still WAITING/PAUSED; an already HEALTHY/RUNNING recovery must stay ACTIVE, while unreadable state is reconciled before any route.
- **True terminal state**: only canonical `FINALIZATION_ACKED`, or evidence-backed `LOOP_BLOCKED`. A stale derived `RUNNING` field cannot revive a terminal loop.

`LOOP_METRICS.json` is derived observation only: per-Goal elapsed time, separately observed Worker, Reviewer, and Local Verifier windows, control-plane wait, dispatch/review/rejection counts, message faults, Steering, and available token usage. It is not a second canonical source and cannot authorize a route.

## A short, complete example

Suppose an existing web project needs Passkey login, and the code, migration, browser behavior, and security review must all remain traceable.

You could ask:

```text
Use $codex-loop-prompt-architect to design a Standard Loop for Passkey login.
Allow code writes only under app/auth/** and tests/auth/**. Forbid push, merge,
deploy, and production writes. Completion requires unit tests, browser
verification, code review, and a final integrated audit. If facts are missing,
return NEEDS_CLARIFICATION instead of inventing permissions.
```

Intake first checks the project location, repository mode, existing implementation, acceptance criteria, permissions, and local verification needs. It generates a dispatchable Pack only after `READY_FOR_LOOP` and a real scaffold `--check-only` pass.

During the real run, “the code is written” does not unlock the next step. The exact Worker artifact enters canonical records, the Reviewer examines the corresponding diff, and machine-local facts go to a Local Verifier when required. If a repair changes the artifact, the old review cannot be reused. The Loop still needs a final audit and finalization.

## Why completion is more trustworthy

![Xiaohei adds artifact, test, identity, and review evidence to a mechanical balance before the closing door can latch](docs/readme-assets/evidence-before-closure.png)

Trust does not come from a green UI or a role saying “done.” It comes from constraints users can feel:

| User benefit | Mechanism underneath |
| --- | --- |
| Old results cannot prove a new change | Reviews and validations bind the exact artifact, command, environment, and configuration identity |
| Lost tool output does not trigger a blind external retry | Durable receipts distinguish STARTED from COMPLETED and forbid automatic resend after lost stdout |
| Two Controller turns cannot advance the same route | Canonical leases, real App-turn binding, and one route per turn |
| State conflicts are not resolved by model guesswork | Deterministic runtime, CAS, journals, outboxes, and idempotent replay |
| Repair cannot run forever | Repair beyond the initial execution has a hard cap; exhaustion pauses, asks, or stops |
| “Done” has one auditable gate | v3 `PREPARE_FINALIZATION` is not closure; only `FINALIZATION_ACKED` is |

Real identity cannot be established by model prose, a task title, environment variable, or random UUID. Adaptive routing accepts only validated host-provided App metadata and process identity. If it cannot prove that identity, it fails closed.

## Safety and permission boundary

Generating a Pack never silently authorizes:

- push, merge, deploy, release, or production writes;
- writes to external systems, paid providers, secrets, or credentials;
- destructive operations, wider file scope, or extra infrastructure;
- promoting local tests, a green GitHub check, or historical smoke evidence into a release PASS for a new candidate.

Sending a reviewed Pack authorizes only the bounded control-plane actions it explicitly declares, such as creating the agreed real role tasks, sending specified messages, and maintaining one heartbeat. It does not expand product write access or replace explicit approval for push, merge, deploy, paid calls, or external writes.

Read-only Intake does not mutate the product repository, canonical state, tasks, Goals, or heartbeat. It may create one disposable generator input under a temporary directory only for `--check-only`.

Old evidence cannot unlock a new artifact. When the artifact, code, configuration, App build, Pack, or installation identity changes, identity-bound review and compatibility evidence must be renewed.

## Current limitations

### Native Goal generation recovery: `DEFERRED_UNAVAILABLE`

v3.2.8 does not recover a lost native Goal identity. The current Codex App has no public create-paused, resume, restore, or rebind interface that can preserve the same identity, so generated Packs do not include this recovery path. New schema-v3 Packs go further and disable the native Goal adapter; the required-mode wording below applies only to readable v1/v2 compatibility state. v3.2.7 reached repository `main` but never received a tag or GitHub Release; v3.2.8 formally closes that deferred work without rewriting history.

Legacy CLI and MCP recovery surfaces reject with `NATIVE_GOAL_GENERATION_RECOVERY_UNAVAILABLE` and `side_effects=NONE`. If required mode observes `NATIVE_CONTROLLER_GOAL_IDENTITY_LOST`, canonical state stays unchanged, the same heartbeat stays paused, and no substitute Goal, Controller, thread, session, or heartbeat is created. Historical BLOCKED receipts remain BLOCKED evidence; they cannot become PASS.

### App messaging and process transport

New Adaptive Packs pass structured parameters through the installed MCP `runtime_codec` for dispatch materialization and verification, formal-report and external-receipt staging, fingerprint normalization, and `CAPTURE_COMPLETE_DIFF`. They no longer assume that a `tty:false` process exposes a session stdin that remains available for a later `write_stdin` call. The runtime captures binary Git patches as raw bytes, reverse-validates them, and records a manifest. A Worker PASS may cite only digest-only `CAPTURED_GIT_DIFF_V1`; the runtime derives and rechecks the capture path, and models carry neither patch bytes nor a `.codex-loop` path.

CLI stdin remains only for legacy State-Writer and compatibility calls. EOF before the first frame returns `INPUT_TRANSPORT_EOF_BEFORE_FRAME`; an unavailable codec returns `RUNTIME_CODEC_TOOL_UNAVAILABLE`. Both stop with zero side effects and must not be bypassed with a PTY, heredoc, pipeline, or hand-built digest.

### App and protocol identity

This skill targets the Codex macOS App. It does not claim support for every platform, and it does not claim to fix Codex app-server process reaping or Goal persistence.

A real App receipt records observable client and server protocol information separately. When the host does not expose the negotiated MCP protocol version, it must record:

```text
negotiated_protocol_version_status = UNAVAILABLE_BY_HOST
negotiated_protocol_version = null
```

That means “the host did not expose it,” not “the version was verified.” The unknown field alone does not block release when the independent connection, identity, route, zero-side-effect, receipt, and finalization gates all pass.

## Intake outcomes

- `READY_FOR_LOOP`: every applicable gate passes and a real scaffold `--check-only` succeeds.
- `NEEDS_CLARIFICATION`: the user can supply missing facts, constraints, or permissions.
- `BLOCKED`: a hard feasibility, safety, resource, or authorization conflict remains.
- `DIRECT_TASK_RECOMMENDED`: the request is clear but does not justify Loop overhead.

There is no `READY_WITH_ASSUMPTIONS`. Unknown facts remain `UNKNOWN`, and proposed defaults require confirmation.

## Scripted generation

Validate an input without writing outputs:

```bash
python3 ~/.codex/skills/codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --input examples/01-passkey-login-input.json \
  --check-only
```

Generate a Pack and usage guide:

```bash
python3 ~/.codex/skills/codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --input examples/01-passkey-login-input.json \
  --controller-pack-output /tmp/controller-pack.md \
  --user-guide-output /tmp/usage.md
```

Generate Full Mode:

```bash
python3 ~/.codex/skills/codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --input examples/03-adaptive-passkey-input.json \
  --mode full \
  --controller-pack-output /tmp/adaptive-controller-pack.md
```

Print the input schema:

```bash
python3 ~/.codex/skills/codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --print-schema
```

The generator rejects incomplete input and duplicate JSON keys by default. Use `--allow-draft` only when you explicitly need a non-dispatchable draft; it is marked `NON_DISPATCHABLE_DRAFT`.

Repository modes:

- `existing_git`: verify root, branch, base SHA, dirty state, remotes, and worktrees first.
- `new_git`: let the first authorized Worker initialize Git; Git init and branch creation are separate permissions.
- `non_git`: use before/after manifests, content digests, and a diff digest instead of invented Git identity.

## Three examples

- [Passkey login (Standard)](examples/01-passkey-login-input.json)
- [Daily CI Triage (Standard)](examples/02-daily-ci-triage-input.json)
- [Adaptive Passkey](examples/03-adaptive-passkey-input.json)

<details>
<summary><strong>Validation and evidence boundary</strong></summary>

Fast local regression:

```bash
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -W error -m unittest discover -s tests -v
.venv/bin/python codex-loop-prompt-architect/scripts/validate_skill.py
bash -n scripts/install.sh
```

The complete release process also covers branch coverage across every shipped Python entrypoint, two independent 5000-case fuzz lanes, isolated install/rollback, zero source/install drift, security checks, and a real same-SHA App canary. A v3 canary must also prove no State-Writer task, Gateway one-route-per-turn, original-outbox recovery after lost stdout, transport pausing, successor handoff, and `FINALIZATION_ACKED`. The current main Mac's structured receipt uses `evidence_layer=local-main-mac`.

GitHub Actions is a compatibility mirror, not release acceptance. Historical E2E records are bounded smoke evidence for their recorded machine, App build, and artifact; they do not prove cross-version, production, long-run, or public acceptance. See the [release process](docs/RELEASING.md) and [evidence index](evidence/README.md) for exact boundaries.

</details>

## Learn more

- [Project specification and safe-evolution rules](SPEC.md)
- [Skill instructions](codex-loop-prompt-architect/SKILL.md)
- [Intake Gate contract](codex-loop-prompt-architect/references/loop-intake-gate.md)
- [Standard Loop contract](codex-loop-prompt-architect/references/loop-contract.md)
- [Adaptive Loop contract](codex-loop-prompt-architect/references/adaptive-loop-contract.md)
- [Human steering and convergence](codex-loop-prompt-architect/references/human-steering-and-convergence.md)
- [Release process](docs/RELEASING.md)
- [Changelog](CHANGELOG.md)
- [Historical evidence index](evidence/README.md)

## License

MIT. See [LICENSE](LICENSE).
