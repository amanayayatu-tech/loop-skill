# LoopSkill 5 quickstart

LoopSkill 5 is the repository's independent two-file Codex Skill product. The root `VERSION=4.2.0` and `scripts/install.sh` belong to the preserved LoopSkill 4.2 runtime; do not use them to install v5.

## Install

First confirm that GitHub Releases contains a public, non-prerelease `v5.0.0` Release. Then invoke the system Skill Installer in Codex:

```text
Use $skill-installer to install https://github.com/amanayayatu-tech/loop-skill/tree/v5.0.0/loopskill5
```

The destination is `${CODEX_HOME:-$HOME/.codex}/skills/loopskill5` and must contain only:

- `SKILL.md`
- `agents/openai.yaml`

The system installer refuses to overwrite an existing destination. Do not overlay new bytes on an old directory; inspect the existing install and move it out recoverably with the steps below.

In a new Codex turn after installation, invoke the Skill explicitly:

```text
Use $loopskill5. Investigate this long task proactively and show the farthest-safe 12-item Launch Contract; do not START yet.
```

Review the final intent, committed result, authority, real acceptance, recovery limits, business Gates, emergency stops, and unattended window. Only then send one separate `START` for that exact contract.

## Recoverable uninstall

The commands below delete nothing. They move only the exact v5 Skill directory to an owner-only backup outside `skills`. They do not touch `loopskill4`, the root `VERSION`, v4 receipts, or any v3/v4 data.

```bash
set -eu
loopskill5_home="${CODEX_HOME:-$HOME/.codex}"
loopskill5_dir="$loopskill5_home/skills/loopskill5"
loopskill5_backup_root="$loopskill5_home/uninstalled-skills"

test -d "$loopskill5_dir"
test ! -L "$loopskill5_dir"
test -O "$loopskill5_dir"
test -f "$loopskill5_dir/SKILL.md"
test ! -L "$loopskill5_dir/SKILL.md"
test -O "$loopskill5_dir/SKILL.md"
test -d "$loopskill5_dir/agents"
test ! -L "$loopskill5_dir/agents"
test -O "$loopskill5_dir/agents"
test -f "$loopskill5_dir/agents/openai.yaml"
test ! -L "$loopskill5_dir/agents/openai.yaml"
test -O "$loopskill5_dir/agents/openai.yaml"
test "$(find "$loopskill5_dir" -type f | wc -l | tr -d ' ')" = 2
test "$(find "$loopskill5_dir" -type d | wc -l | tr -d ' ')" = 2
test -z "$(find "$loopskill5_dir" -type l -print)"

umask 077
mkdir -p "$loopskill5_backup_root"
test -d "$loopskill5_backup_root"
test ! -L "$loopskill5_backup_root"
test -O "$loopskill5_backup_root"
chmod 700 "$loopskill5_backup_root"
loopskill5_backup="$loopskill5_backup_root/loopskill5-$(date -u +%Y%m%dT%H%M%SZ)"
test ! -e "$loopskill5_backup"
mv "$loopskill5_dir" "$loopskill5_backup"

test ! -e "$loopskill5_dir"
test -f "$loopskill5_backup/SKILL.md"
test -f "$loopskill5_backup/agents/openai.yaml"
printf 'LoopSkill 5 moved recoverably to %s\n' "$loopskill5_backup"
```

If the directory has extra files, a symlink, uncertain identity, or another writer, stop and review it first. Do not hide drift with recursive deletion.

## Product boundary

- Ordinary users do not fill in JSON, internal IDs, digests, receipts, or recovery commands.
- After START, PATH, ports, scratch, Verifier restarts, and contract-authorized local permission repairs are not user Gates.
- New authority, secrets, cost, public publication, deployment, deletion, or other authority expansion remains a true business Gate.
- Codex Host-required model/control-plane traffic is reported separately from task business-tool network effects.
- v5 never reads, migrates, revives, or dual-writes v3/v4 data.
- Sleep or operating-system shutdown recovery is not a v5.0.0 hard promise; a multiday claim depends on the formal 48-hour journey evidence.
