# Codex Loop Prompt Architect

[简体中文](README.md) | English

[![Test](https://github.com/amanayayatu-tech/loop-skill/actions/workflows/test.yml/badge.svg)](https://github.com/amanayayatu-tech/loop-skill/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/amanayayatu-tech/loop-skill?display_name=tag)](https://github.com/amanayayatu-tech/loop-skill/releases)

`codex-loop-prompt-architect` is a skill for the Codex macOS App. It quality-gates
rough ideas and PRDs, then turns only `READY_FOR_LOOP` requirements into a
validated Standard or Adaptive Controller Pack. It designs the loop; it does not
implement the target PRD by itself.

## Quick start

Requirements: macOS, Codex App, Git, and Python 3.9 or newer.

```bash
git clone https://github.com/amanayayatu-tech/loop-skill.git
cd loop-skill
python3 -m pip install -r requirements-test.txt
./scripts/install.sh
```

Open a new Codex App task after installation.

To assess a requirement without generating a Controller Pack:

```text
Use $codex-loop-prompt-architect in intake-only mode. Check whether this
requirement is ready for a Loop, ask only the highest-priority blockers, and do
not create a Controller Pack: ...
```

To generate a validated Pack:

```text
Use $codex-loop-prompt-architect to loop this requirement. Run the Intake Gate
first; if information is missing, ask me before generating the Pack: ...
```

The skill creates one self-contained Controller Pack Markdown file plus separate
Simplified Chinese usage instructions. It never silently authorizes push, merge,
deploy, destructive operations, external writes, secrets, or paid runtime.

### v3.2.4 canonical schema hotfix

`DISPATCH_VALIDATION_MATRIX_MISMATCH` is now present in the runtime allowlist,
mutation schema, and canonical state schema. A zero-execution validation-matrix
rejection proved by the archived report can be reconciled at a paused safe point
without a second schema rejection.

### v3.2.3 Worker classification hotfix

`--report-stage` now binds top-level Worker `execution_started` and
`blocker_code` fields from the formal report into the ACK-ready result, so an
omitted handle field cannot silently default to product execution. For an
already misprojected ACK, `RECONCILE_WORKER_EXECUTION_CLASSIFICATION` is allowed
only at canonical `PAUSED_AT_SAFE_POINT` with no lease or active outbox. It
verifies the exact archived report and corrects only the existing
attempt/latest-worker classification without deleting history, clearing repair
counters, or changing Pack identity.

### v3.2.2 real-incident fixes

The direct non-PTY contract now covers every runtime mode: launch the runtime
itself with `tty:false`, then write one compact JSON frame once. Generated Packs
reject pre-runtime stdin helpers, `tty:true`, `dd`/`stty`, fixed-byte readers,
heredocs, and shell pipelines.

External model calls and Local Verification now bind route, Pack, Goal, lease,
target, provider/model, request digest, and call index through the existing LOCAL
outbox `external_call_authorization`, then use sanitized immutable
`STARTED`/`COMPLETED` receipts. Runtime validates time ordering, PASS/exit
consistency, read-only artifact digests, and token arithmetic. If deferred
execution loses stdout, the Controller recovers COMPLETED without another
provider call; a lone STARTED returns `EXTERNAL_CALL_OUTCOME_UNKNOWN`, counts one
call conservatively, and keeps unknown tokens `null` with `complete=false`.
Worker reports distinguish actual product
execution from deterministic control-plane rejection. Only an approved blocker
with `execution_started=false` avoids repair consumption.

Pack changes require atomic `MIGRATE_CONTROLLER_PACK` at a paused safe point and
retain immutable revision history; an unmigrated digest has no routing authority.
The Controller invokes `ACQUIRE_LEASE` / `TAKEOVER_LEASE` only through the
installed `route_state_mutation` MCP tool and omits `controller_turn_id` from
model arguments. The bridge verifies Codex-injected turn metadata and its direct
OpenAI-signed app-server parent before injecting the real turn id. A second route
in the same App turn is rejected without side effects; all other mutations still
use the existing State-Writer. Release closure still requires a real App
two-route canary.

Generated Adaptive Packs also use projection-first observation: compare the
`LOOP_STATE.md` mtime/size and projected `STATUS.md` state version, then parse
canonical state only after a change or before a mutation. `STATUS.md` remains an
observation surface. Task reads are one-target/one-in-flight
`read_thread(turnLimit=1, includeOutputs=false)` calls with 30/60/120-second
backoff, reduced to status, timestamps, item types, and the final bounded
message. Validation is deduplicated by exact artifact, command,
environment/toolchain, and config identity; narrow changes get narrow tests and
the final artifact gets one full gate. Child processes and sessions use the same
non-PTY session, bounded waits, and TERM-to-wait-to-KILL-to-waitpid cleanup;
durable receipts recover lost stdout without retrying an external call. These
constraints change no schema, state, migration, repair cap, or completion
semantics.
Stdin modes must select a native process API that launches the runtime by direct
argv and exposes a writable non-PTY pipe. A shell exec that closes stdin at
launch is ineligible, and `/tmp` file redirection is not a fallback. An applied
scoped correction may audit a replacement Goal only after an acknowledged Local
`FAIL`/`BLOCKED` for that exact Worker artifact; the original history is retained
and retired, while missing evidence still requires Local PASS.

### v3.2.1 hotfix

Every Adaptive runtime stdin mode now uses a bounded frame reader: 30 seconds,
4 MB, and strict UTF-8. A complete top-level JSON object is processed without
waiting for the writer to close. Generated Packs require a direct `tty:false`
invocation, one compact JSON write, same-session polling, and no `dd`, `stty`,
fixed-byte reader, heredoc, or extra shell pipeline. Materialization is sendable
only after `exit_code=0`, session termination, and one
`PAYLOAD_MATERIALIZED` stdout object.

New Packs default to five repairs beyond the initial execution; explicit 0–20
values remain valid. Exhaustion forbids further dispatch. With Decision Cards,
the Controller registers one stop-or-remain-paused-for-scoped-correction card
and pauses the heartbeat; without cards, it may deterministic-fast-stop on the
next dedicated Goal turn. `STOP_LOOP.stop_basis` separately validates ordinary
three-observation blockers, deterministic exhaustion, and a user stop Decision
bound to its response Steering. Frozen authorization values in old Packs are
not silently rewritten.

## Readiness outcomes

- `READY_FOR_LOOP`: all applicable gates pass and a real scaffold `--check-only`
  succeeds.
- `NEEDS_CLARIFICATION`: the user can provide missing facts or permissions.
- `BLOCKED`: a hard feasibility, safety, resource, or authorization conflict
  prevents generation.
- `DIRECT_TASK_RECOMMENDED`: the request is clear but does not justify a loop.

There is no `READY_WITH_ASSUMPTIONS`. Unknown facts remain `UNKNOWN`, and proposed
defaults require confirmation before a request can become ready.

## Standard and Adaptive modes

Standard mode uses a fixed, dependency-ordered Goal Queue. It is the default for
stable work whose acceptance criteria are known in advance.

Adaptive mode uses a mutable milestone roadmap backed by a deterministic state
runtime. Prefer it when the user explicitly requests it, the work has several
real milestones, evidence may change later goals, machine-local verification is
required, or the run is expected to exceed half a day.

Both modes preserve real Codex App task identities, Controller read-only
behavior, serial canonical state writes, bounded retries and heartbeats,
exact-artifact review, and explicit evidence/claim boundaries.

## Repository modes

- `existing_git`: verify the existing repository, branch, base SHA, dirty state,
  remotes, and worktrees before dispatch.
- `new_git`: let the first authorized Worker initialize Git and the initial
  branch before any worktree-dependent flow.
- `non_git`: use deterministic before/after manifests and content digests instead
  of inventing Git identities.

## Deterministic generation

Validate an input without writing outputs:

```bash
python3 codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --input examples/01-passkey-login-input.json \
  --check-only
```

Generate a Pack and user guide:

```bash
python3 codex-loop-prompt-architect/scripts/loop_prompt_scaffold.py \
  --input examples/01-passkey-login-input.json \
  --controller-pack-output /tmp/controller-pack.md \
  --user-guide-output /tmp/usage.md
```

See [`examples/`](examples/) for Standard and Adaptive input/output fixtures.

## Validation

Fast local regression:

```bash
python3 -m pip install -r requirements-test.txt
python3 -W error -m unittest discover -s tests -v
python3 codex-loop-prompt-architect/scripts/validate_skill.py
bash -n scripts/install.sh
```

Full release fuzz gate:

```bash
ADAPTIVE_FUZZ_CASES=5000 ADAPTIVE_STATE_FUZZ_CASES=5000 \
  python3 -W error -m unittest discover -s tests -q
```

Coverage baseline:

```bash
coverage run -m unittest discover -s tests
coverage report
```

## Documentation map

- [Chinese complete manual](README.md)
- [Skill instructions](codex-loop-prompt-architect/SKILL.md)
- [Intake Gate contract](codex-loop-prompt-architect/references/loop-intake-gate.md)
- [Standard loop contract](codex-loop-prompt-architect/references/loop-contract.md)
- [Adaptive loop contract](codex-loop-prompt-architect/references/adaptive-loop-contract.md)
- [Human steering and convergence](codex-loop-prompt-architect/references/human-steering-and-convergence.md)
- [Evidence timeline](evidence/README.md)
- [Release process](docs/RELEASING.md)
- [Changelog](CHANGELOG.md)

## Evidence boundary

The repository preserves failed and successful bounded Codex App runs. These are
environment-specific smoke evidence, not production, long-run, cross-version,
formal, science, or public acceptance. See the [evidence index](evidence/README.md)
for the exact timeline and limitations.

## License

MIT. See [LICENSE](LICENSE).
