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
