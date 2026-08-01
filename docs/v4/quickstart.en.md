# LoopSkill 4 quickstart

This document describes LoopSkill 4.2.0. See GitHub Releases for the public versions currently available.

## Install

Requirements: macOS or Linux, Git, and Python 3.11–3.14. Runtime dependencies
are standard-library only. Version 4.2.0 release validation covers the direct
v3-cwd zero-write regression, the complete deterministic suite, and all eight
Linux/macOS × Python 3.11, 3.12, 3.13, and 3.14 release-CI
runtime/distribution lanes and requires three ordered one-shot canary layers.
When GitHub Releases lists v4.2.0, the command below installs that exact tag.

```bash
git clone --branch v4.2.0 --depth 1 https://github.com/amanayayatu-tech/loop-skill.git
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

## One sentence or PRD, one entry, four visible phases

The normative order is `INTAKE → PREPARE → CONFIRM → START`.

Invoke `$loopskill4` in a Codex conversation and provide one sentence, paste a
PRD, or explicitly authorize one UTF-8 `.txt` / `.md` file. Ordinary users do
not write JSON. Each round asks only 1–3 true blockers and retains confirmed
answers for the current session. Experts may still use the
[v4 Standard example](../../examples/v4-standard-input.json) or a canonical
PlanDocument. The count of user-supplied control identities must be zero.

```bash
"$LOOPSKILL4" start ./requirements.md
```

The entry performs:

1. `INTAKE`: strictly read-only; returns `READY_FOR_LOOP`,
   `NEEDS_CLARIFICATION`, `BLOCKED`, or `DIRECT_TASK_RECOMMENDED`.
2. `PREPARE`: writes an owner-only typed manifest, human plan, PlanDocument,
   PlanIndex, capacity report, and boundary summary. It creates no runtime
   Store and has 0 Host tasks, 0 heartbeats, and 0 delivery.
3. `CONFIRM`: displays Goal, write scope, budget, external actions, acceptance,
   stop, and publication boundaries; confirmation binds every prepared digest.
4. `START`: accepts only an unchanged valid confirmation, writes the plan/index
   as content-addressed blobs, creates a compact Loop containing only the current
   Goal, and launches one foreground Codex invocation for that Goal.

One entry does not mean silent authorization. A non-interactive session stops
after PREPARE. Changed boundaries, expired confirmation, or vague “continue”
fail closed.

The ordinary entry runs one official `codex exec --json --output-schema --output-last-message`
process in the
foreground for at most 30000 seconds and reaps its process group on success,
failure, timeout, or interruption. This is the Attempt bound, not the full Loop
budget. A complete terminal JSONL lifecycle, zero exit, exactly one machine-controlled
result-file object valid against the typed-manifest-derived closed outcome/summary schema, and artifact
verification are all required. Lost or invalid evidence becomes `UNKNOWN`;
LoopSkill does not derive Result from `agent_message` and has no prose-marker fallback.
Plan v2 persists the session and terminal controls outside the workspace; restart can
read a completed Attempt or consume one recorded `codex exec resume`. Bounded stderr is private digest-only
diagnostic evidence; overflow fails closed.
Each Goal may use up to three declared Attempts. A confirmed plan may contain
1–128 Goals; `run`/`continue` activate and advance them until a human, time,
budget, or repeated-failure waiting boundary. No unlimited background daemon is promised.

The Codex Desktop folder-open → `list_projects` → `projectId` → `create_thread`
route has historical provisioning receipts, but it is not wired into 4.2.0. The
ordinary entry uses a cwd-bound foreground `codex exec` invocation and does not
promise a Desktop-visible saved project/task.

## Explicit phases

```bash
"$LOOPSKILL4" intake examples/v4-standard-input.json
"$LOOPSKILL4" prepare examples/v4-standard-input.json --output ./prepared-loop
"$LOOPSKILL4" confirm ./prepared-loop
"$LOOPSKILL4" start ./prepared-loop --root ./loopskill4-data
"$LOOPSKILL4" list --root ./loopskill4-data
"$LOOPSKILL4" status --root ./loopskill4-data --loop loop-example
"$LOOPSKILL4" run --root ./loopskill4-data --loop loop-example
"$LOOPSKILL4" continue --root ./loopskill4-data --loop loop-example
"$LOOPSKILL4" budget-extend --root ./loopskill4-data --loop loop-example --max-host-invocations 40 --active-compute-seconds 14400 --reason "Continue the unchanged confirmed scope"
```

`confirm` requires an exact interactive confirmation. `list` and plain status
are local and read-only. `budget-extend` is accepted only from `WAITING_BUDGET`, only
increases invocation/active-compute limits, stores a digest of the reason, and
does not change the confirmed task scope.
`run`/`continue` select one Loop explicitly when more
than one exists. Completed persistent Attempt evidence is reusable after a
restart. One captured non-ephemeral session may be resumed once; a live process
is waited on, and non-replayable actions require a human gate.
`UNKNOWN`/`UNVERIFIABLE` are intentional visible limitations, not success, and
never trigger blind resend.

## Capacity and compatibility

- One explicitly authorized UTF-8 text/Markdown source is at most 256 KiB, a canonical PlanDocument is at most 512 KiB, and a plan contains 1–128 Goals.
- The CreateLoop release target is 8 KiB / 64 members, with 16 KiB / 128 hard limits. The Host prompt target is 24 KiB, with a 32 KiB hard limit. Overflow is blocked before Host execution and never truncated.
- New Loops write only `CONTENT_ADDRESSED_V1`. An old `EAGER_V4_0` store supports status, export, and original-reducer continuation only; there is no migration, rewrite, or dual write.

See the [v4.2 compatibility matrix](compatibility-matrix-v4.2.md).

Run `bash scripts/install.sh` to upgrade an intact receipt-bound v4.1.1 install
transactionally. The old manager, target, receipt pointer, config, and Loop
data remain recoverable until the new pointer commits. Unknown drift fails closed.

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/install-receipts/loopskill4/uninstall_v4.py" --codex-home "${CODEX_HOME:-$HOME/.codex}"
bash scripts/install.sh
```

## v3

v4 does not open, import, repair, or run v3 loop/Pack/state data. It performs
zero writes on v3 input and links to
[v3.3.8](https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8).
There is no automatic migration; continue using v3.3.8 independently when old
data is required.
If the cwd still carries a v3 `.codex-loop` marker, 4.2.0 stops before
PREPARE, START, or workspace-bound execution; it creates no prepared artifacts, Store,
or Host task. Switch to a new v4 workspace first.

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
