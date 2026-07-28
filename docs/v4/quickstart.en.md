# LoopSkill 4 quickstart

This document describes LoopSkill 4.0.0. See GitHub Releases for the public
versions currently available.

## Install

Requirements: macOS or Linux, Git, and Python 3.11–3.14. Runtime dependencies
are standard-library only. Version 4.0.0 may be published only after all eight
Linux/macOS × Python 3.11, 3.12, 3.13, and 3.14 release-CI
runtime/distribution lanes pass.

```bash
git clone --branch v4.0.0 --depth 1 https://github.com/amanayayatu-tech/loop-skill.git
cd loop-skill
bash scripts/install.sh
LOOPSKILL4="${CODEX_HOME:-$HOME/.codex}/skills/loopskill4/scripts/loopskill4"
"$LOOPSKILL4" --help
```

The installer writes only `$CODEX_HOME/skills/loopskill4` and its v4-owned
receipt/staging paths. It reads `config.toml` only to verify the before/after
byte hash and does not modify it, register MCP, overwrite an independent v3
installation, or require a Codex restart for LoopSkill 4.

The installer and uninstaller do not edit Codex configuration. On the first
real official Codex Host invocation in a fresh workspace, the Host may append
one `trust_level = "trusted"` record for that workspace at the end of its
configuration. LoopSkill measures this separately as a Host-owned effect: only
one EOF append for the exact machine-generated canonical workspace is allowed,
and the real nonzero changed-byte count is retained. Every other configuration
change, or any auth change, fails closed.

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
4. `START`: accepts only an unchanged valid confirmation and launches at most
   one machine-owned foreground Codex invocation.

One entry does not mean silent authorization. A non-interactive session stops
after PREPARE. Changed boundaries, expired confirmation, or vague “continue”
fail closed.

The ordinary entry runs one official `codex exec --json --output-schema --output-last-message`
process in the
foreground for at most 300 seconds and reaps its process group on success,
failure, timeout, or interruption. This is the observation window, not the task
budget. A complete terminal JSONL lifecycle, zero exit, exactly one machine-controlled
result-file object valid against the typed-manifest-derived closed outcome/summary schema, and artifact
verification are all required. Lost or invalid evidence becomes `UNKNOWN`;
LoopSkill does not derive Result from `agent_message`, has no prose-marker fallback,
never resends, and never runs `codex exec resume`. Bounded stderr is private digest-only
diagnostic evidence; overflow fails closed.
The 4.0.0 ordinary entry supports only an individual Host task expected to
finish within this window. Longer single Host executions are outside this
release's public support boundary.

The Codex Desktop folder-open → `list_projects` → `projectId` → `create_thread`
route has 23/23 provisioning receipts, but it is not wired into 4.0.0. The
ordinary entry uses a cwd-bound foreground `codex exec` invocation and does not
promise a Desktop-visible saved project/task.

## Explicit phases

```bash
"$LOOPSKILL4" intake examples/v4-standard-input.json
"$LOOPSKILL4" prepare examples/v4-standard-input.json --output ./prepared-loop
"$LOOPSKILL4" confirm ./prepared-loop
"$LOOPSKILL4" start ./prepared-loop --root ./loopskill4-data
"$LOOPSKILL4" status --root ./loopskill4-data
"$LOOPSKILL4" status --refresh --root ./loopskill4-data
```

`confirm` requires an exact interactive confirmation. Plain status is local
and read-only. If a crash occurred after the local Attempt commit but before
execution ownership was claimed, `status --refresh` may perform that Attempt's
one first invocation. Once a process started, there is no cross-process
readback or automatic resume; lost evidence remains `UNKNOWN`. It never
performs a second spawn or resend. Normal status hides internal
identity; add `--diagnostics` for diagnostic evidence.
`UNKNOWN`/`UNVERIFIABLE` are intentional visible limitations, not success, and
never trigger blind resend.

## v3

v4 does not open, import, repair, or run v3 loop/Pack/state data. It performs
zero writes on v3 input and links to
[v3.3.8](https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8).
There is no automatic migration; continue using v3.3.8 independently when old
data is required.

## Uninstall

The uninstaller machine-resolves the active receipt bound at installation;
ordinary users do not fill in a receipt:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/install-receipts/loopskill4/uninstall_v4.py" --codex-home "${CODEX_HOME:-$HOME/.codex}"
```

The digest-bound management entry remains outside the removed installation, so
the same command safely returns `ALREADY_UNINSTALLED` on replay. Missing or
drifted receipt evidence fails closed; `config.toml`, v3 installs, and real
loops remain untouched.
