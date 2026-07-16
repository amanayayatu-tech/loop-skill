# Codex Loop Prompt Architect

[简体中文](README.md) | English

[![Test](https://github.com/amanayayatu-tech/loop-skill/actions/workflows/test.yml/badge.svg)](https://github.com/amanayayatu-tech/loop-skill/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/amanayayatu-tech/loop-skill?display_name=tag)](https://github.com/amanayayatu-tech/loop-skill/releases)

The test badge is a GitHub compatibility mirror. Authoritative release evidence
combines the primary Mac's complete exact-SHA gate and real Codex App canary
with a root-owned/read-only lightweight witness attestation from the Mac mini.

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

### v3.2.7 native Goal generation recovery protocol

If an App restart leaves the original Controller task, heartbeat, and canonical
Loop intact but `get_goal` can no longer read the original native Goal, the new
protocol keeps product routing paused and fails closed. The runtime derives the
legacy generation only by reopening the unique canonical ACKED GOAL CREATE
create/ACK evidence; callers cannot supply objective, createdAt, usage, digest,
call count, or generation identity.

Recovery uses three short-lived scopes. The Controller acquires one
host-attested recovery lease through MCP, while the original State-Writer alone
applies journaled PREPARE, COMMIT, or ROLLBACK. Phase B is a different real App
turn and may call official `create_goal` once with the historical objective
bytes only after the bounded rollout observer proves zero matching invocation
since the PREPARE high-watermark. Any STARTED, COMPLETED, or AMBIGUOUS evidence
forbids another create. Lost stdout can only be adopted in a later turn when the
rollout and active same-thread `get_goal` readback agree.

The observer reads canonical rollouts only from `CODEX_HOME/sessions` or
`archived_sessions`, rejects path escape, symlinks, unstable/incomplete JSONL,
and wrong thread identity, and persists only sanitized receipts. COMMIT and
ROLLBACK keep canonical state and the same heartbeat PAUSED; RESUME and
heartbeat activation remain later independent turns. If the current App lacks
durable invocation evidence, release fails closed as
`UPSTREAM_NATIVE_GOAL_CREATE_INVOCATION_RECEIPT_UNAVAILABLE`. This repository
does not claim to repair Codex App native Goal persistence.

### v3.2.6 interpreter identity hotfix

Generated Adaptive Packs now resolve `RUNTIME_PYTHON` and the sibling runtime
only from the exact installed `codex-loop-state` MCP registration readback. Any
identity, dependency, or path mismatch returns zero-side-effect
`STATE_RUNTIME_UNAVAILABLE`; ambient `python3` is never a fallback.

### v3.2.5 control-plane reliability closure

This release makes the declared safety protocol enforceable. Every stdin mode
uses one bounded semantic reader. Route acquisition trusts only real MCP
`params._meta`, the App `turn_id`, and an OpenAI-signed direct app-server parent.
Durable external receipts bind route/provider/request/call order, usage, result
semantics, and artifact bytes; lost stdout recovers COMPLETED without another
send. Worker required-validation projection, `RECORD_REVIEW` closeout, Pack
migration, and same-heartbeat reconciliation are atomic and replay-safe.

`scripts/install.sh` now atomically registers `codex-loop-state` with an absolute
Python executable and the installed `adaptive_state_mcp.py`. It preserves prior
`config.toml` bytes, rejects a conflicting identity or extra env/cwd/disabled
execution semantics, rolls back skill/config on failure, and writes a
schema-validated manifest proving registration readback and zero source/install
drift.

Release evidence stays layered: local checks, authoritative exact-SHA Mac mini
attestation, a real canary on the current App build, then merge/main/tag/Release.
Any App version/build/bundle, app-server signature/CDHash, MCP protocol/config/
requestMeta shape, or installation identity change invalidates the old receipt.
PASS covers same-turn pre-side-effect rejection, next-turn success, partial-frame
cleanup, lost-stdout recovery, Pack/same-heartbeat migration, and canonical
`FINALIZATION_ACKED`. The repository does not claim to fix upstream app-server
process reaping. The receipt directly binds the exact commit, tracked-tree
SHA-256, Pack digest, and installed-manifest digest; commit identity alone is
not accepted as an implicit substitute for the tested tree.

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

Every generated Adaptive runtime invocation resolves `RUNTIME_PYTHON` from the
exact installed `[mcp_servers.codex-loop-state]` command/args readback and
requires the bridge and runtime to share the installed skill root. It fails
closed instead of falling back to an ambient `python3` without the shipped
dependencies.

Every digest mismatch uses provenance-bearing field pairs: caller assertions use
`provided_digest/computed_digest`, ledger-versus-disk checks use
`ledger_digest/computed_file_digest`, canonical-state comparisons use
`state_digest/mutation_digest`, and Pack comparisons use
`canonical_pack_digest/loaded_pack_digest`. Responses also name SHA-256, UTF-8,
the hashed byte length, and `side_effects=NONE`; digest errors never use the
ambiguous `expected/actual` pair.

Worker, Reviewer, and Local Verifier formal reports pass exact `report_text` to
`--report-stage` inside the target task. Runtime validates the role-authored
UTF-8 JSON framing and semantics, computes the digest and byte count from those
exact bytes, and does not rewrite key order, line endings, or Unicode spelling.
The Controller forwards only the `FORMAL_REPORT_STAGED` handle. Optional
`provided_report_digest` is an assertion, never the identity authority.
New or explicitly migrated Packs also project every required Validation Matrix
dimension in the same Worker PASS ACK, binding the current dispatch/artifact to
already archived evidence path/digest/media type. Any missing, duplicate,
unknown, non-required, stale-artifact, or unarchived item rejects the whole ACK.
`RECORD_VALIDATION` remains only for legacy Packs or independent validation
performed after Worker ACK.
Reviewer `ACK_OUTBOX` still proves only that the report is durable. One following
`RECORD_REVIEW` carries a bounded `freshness_observation`, revalidates the
canonical report, and atomically commits freshness, the validation gate,
assurance ledger, Goal, outbox completion, and lease consumption in one journal
transaction. A new request-id replay of the same review/report/artifact returns
the existing closeout receipt without another event.

Pack changes first persist old/new Pack, the five-role digest, and a PAUSED
readback of the same heartbeat with `PREPARE_CONTROLLER_PACK_MIGRATION`. The
runtime derives the canonical prompt path and digest from exact bytes in a
root-confined source; callers cannot attest an arbitrary prompt digest.
Migration never rewrites the historical ACKED automation outbox, and rollback
restores the routing-gate value journaled at PREPARE. After
updating that heartbeat in place, `MIGRATE_CONTROLLER_PACK` requires a second
PAUSED readback of the same id, target, schedule, and target prompt digest.
Mismatch stays paused and can only converge or explicitly roll back after the
old prompt is read back; replacement heartbeats are forbidden. STATUS v3 uses
only evidence-bound live readback and reports `UNKNOWN_NOT_OBSERVED` otherwise.
Resume requires target PAUSED readback, and routing waits for the same
heartbeat's ACTIVE readback. An unmigrated digest has no routing authority.
The Controller invokes `ACQUIRE_LEASE` / `TAKEOVER_LEASE` only through the
installed `route_state_mutation` MCP tool and omits `controller_turn_id` from
model arguments. The bridge verifies Codex-injected turn metadata and its direct
OpenAI-signed app-server parent, requires metadata `thread_id` to equal outer
request `threadId`, and injects the real `turn_id`. Required `session_id` is the
trusted session-tree identity; it may differ after fork/resume and never replaces
`turn_id`. A second route
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

`requirements-test.txt` pins PyYAML because the installer also executes Codex's
system `quick_validate.py` when that validator is present. A missing YAML
dependency fails before any installation or MCP configuration mutation.

Full release fuzz gate:

```bash
ADAPTIVE_FUZZ_CASES=5000 python3 -W error -m unittest \
  tests.test_adaptive_fuzz.AdaptiveMalformedInputFuzzTests.test_malformed_nested_values_never_crash_validation_or_render -v
ADAPTIVE_STATE_FUZZ_CASES=5000 python3 -W error -m unittest \
  tests.test_adaptive_state_runtime.AdaptiveStateRuntimeTests.test_malformed_and_random_sequences_never_mutate_or_corrupt -v
```

Coverage baseline:

```bash
coverage run -m unittest discover -s tests
coverage report
```

Coverage includes every shipped Python entrypoint and enforces branch coverage
of at least 80%. The full deterministic suite produces coverage data once; the
two 5000-case fuzz lanes do not repeat that suite.

An isolated install also registers `codex-loop-state`, checks exact command/args
readback, writes a schema-validated install manifest, and proves zero
source/install drift. The primary Mac alone runs full tests, branch coverage,
both 5000-case fuzz lanes, and the real App canary. The Mac mini independently
witnesses exact identity, clean checkout, compile/validator, recovery/release
quick tests, macOS 27 installation/drift, and security in a root-owned/read-only
attestation. The combined gate must bind both layers for the same SHA and may
pass only with `release_eligible=true`, no reasons, and disposable canonical
`FINALIZATION_ACKED`. GitHub Actions checks compatibility only. See the
[release process](docs/RELEASING.md).

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
