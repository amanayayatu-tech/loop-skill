# LoopSkill 4 quickstart

Status: 4.0.0 candidate. It is not a published stable release until the tag and
GitHub Release exist.

## Install

Requirements: macOS or Linux, Git, and Python 3.11–3.14. Runtime dependencies
are standard-library only.

```bash
git clone --branch v4.0.0 --depth 1 https://github.com/amanayayatu-tech/loop-skill.git
cd loop-skill
bash scripts/install.sh
LOOPSKILL4="${CODEX_HOME:-$HOME/.codex}/skills/loopskill4/scripts/loopskill4"
"$LOOPSKILL4" --help
```

The installer writes only `$CODEX_HOME/skills/loopskill4` and its v4-owned
receipt/staging paths. It does not read or write `config.toml`, register MCP,
overwrite an independent v3 installation, or require a Codex restart for
LoopSkill 4.

## One goal, one entry, four visible phases

The normative order is `INTAKE → PREPARE → CONFIRM → START`.

Copy the [v4 Standard example](../../examples/v4-standard-input.json), or
create UTF-8 JSON containing semantic requirements only. The count of
user-supplied control identities must be zero.

```bash
"$LOOPSKILL4" start examples/v4-standard-input.json
```

The entry performs:

1. `INTAKE`: strictly read-only; returns `READY_FOR_LOOP`,
   `NEEDS_CLARIFICATION`, `BLOCKED`, or `DIRECT_TASK_RECOMMENDED`.
2. `PREPARE`: writes a typed manifest, human plan, Chinese instructions, and
   boundary summary with 0 Host tasks, 0 heartbeats, and 0 delivery.
3. `CONFIRM`: displays Goal, write scope, budget, external actions, acceptance,
   stop, and publication boundaries; confirmation binds every prepared digest.
4. `START`: accepts only an unchanged valid confirmation and machine-creates
   and reads back at most one Host resource.

One entry does not mean silent authorization. A non-interactive session stops
after PREPARE. Changed boundaries, expired confirmation, or vague “continue”
fail closed.

## Explicit phases

```bash
"$LOOPSKILL4" intake examples/v4-standard-input.json
"$LOOPSKILL4" prepare examples/v4-standard-input.json --output ./prepared-loop
"$LOOPSKILL4" confirm ./prepared-loop
"$LOOPSKILL4" start ./prepared-loop --root ./loopskill4-data
"$LOOPSKILL4" status --root ./loopskill4-data
```

`confirm` requires an exact interactive confirmation. Normal status hides
internal identity; add `--diagnostics` for diagnostic evidence.
`UNKNOWN`/`UNVERIFIABLE` are intentional visible limitations, not success, and
never trigger blind resend.

## v3

v4 does not open, import, repair, or run v3 loop/Pack/state data. It performs
zero writes on v3 input and links to
[v3.3.8](https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8).
There is no automatic migration; continue using v3.3.8 independently when old
data is required.
