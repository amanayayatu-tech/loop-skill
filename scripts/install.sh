#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
PYTHON_BIN="${PYTHON:-python3}"
SKILLS_DIR="$CODEX_HOME_DIR/skills"
SOURCE_DIR="$ROOT_DIR/codex-loop-prompt-architect"
TARGET_DIR="$SKILLS_DIR/codex-loop-prompt-architect"
STATE_RUNTIME="$SOURCE_DIR/scripts/adaptive_state_runtime.py"
STATE_MCP="$SOURCE_DIR/scripts/adaptive_state_mcp.py"
STATE_SCHEMA="$SOURCE_DIR/references/adaptive-state.schema.json"
MUTATION_SCHEMA="$SOURCE_DIR/references/adaptive-mutation.schema.json"
BACKUP_ROOT="$CODEX_HOME_DIR/skill-backups/codex-loop-prompt-architect"
STAGING_ROOT="$CODEX_HOME_DIR/install-staging"
STAMP="$(date +%Y%m%d%H%M%S)-$$"
STAGING_DIR="$STAGING_ROOT/codex-loop-prompt-architect-$STAMP"
BACKUP_DIR="$BACKUP_ROOT/$STAMP"
RUNTIME_SMOKE_ROOT="$STAGING_ROOT/runtime-smoke-$STAMP"
backup_created=""
install_complete=0

cleanup() {
  if [[ "$install_complete" != "1" && -n "$backup_created" && ! -e "$TARGET_DIR" && -e "$backup_created" ]]; then
    mv "$backup_created" "$TARGET_DIR"
    echo "Installation interrupted; restored previous skill from $backup_created" >&2
  fi
  rm -rf "$STAGING_DIR"
  rm -rf "$RUNTIME_SMOKE_ROOT"
}
trap cleanup EXIT

if [[ ! -f "$SOURCE_DIR/SKILL.md" ]]; then
  echo "Missing skill source: $SOURCE_DIR/SKILL.md" >&2
  exit 1
fi

for required_file in "$STATE_RUNTIME" "$STATE_MCP" "$STATE_SCHEMA" "$MUTATION_SCHEMA"; do
  if [[ ! -f "$required_file" ]]; then
    echo "Missing Adaptive state runtime artifact: $required_file" >&2
    exit 1
  fi
done

if ! "$PYTHON_BIN" -c "import jsonschema" >/dev/null 2>&1; then
  echo "Missing Python dependency: jsonschema. Install requirements-test.txt before installing this skill." >&2
  exit 1
fi

"$PYTHON_BIN" "$SOURCE_DIR/scripts/validate_skill.py"

VALIDATOR="$CODEX_HOME_DIR/skills/.system/skill-creator/scripts/quick_validate.py"
if [[ -f "$VALIDATOR" ]]; then
  "$PYTHON_BIN" "$VALIDATOR" "$SOURCE_DIR"
fi

mkdir -p "$SKILLS_DIR" "$BACKUP_ROOT" "$STAGING_ROOT"

# Older installers left discoverable copies beside the live skill. Move them
# outside the skills scan root so Codex sees exactly one installed skill.
for legacy_backup in "$SKILLS_DIR"/codex-loop-prompt-architect.backup.*; do
  [[ -e "$legacy_backup" ]] || continue
  legacy_name="$(basename "$legacy_backup")"
  legacy_target="$BACKUP_ROOT/$legacy_name"
  if [[ -e "$legacy_target" ]]; then
    legacy_target="$BACKUP_ROOT/$legacy_name-$STAMP"
  fi
  mv "$legacy_backup" "$legacy_target"
  echo "Migrated legacy backup to $legacy_target"
done

cp -R "$SOURCE_DIR" "$STAGING_DIR"
chmod +x "$STAGING_DIR/scripts/loop_prompt_scaffold.py"
chmod +x "$STAGING_DIR/scripts/validate_skill.py"
chmod +x "$STAGING_DIR/scripts/adaptive_state_runtime.py"
chmod +x "$STAGING_DIR/scripts/adaptive_state_mcp.py"
mkdir -p "$RUNTIME_SMOKE_ROOT"
"$PYTHON_BIN" "$STAGING_DIR/scripts/adaptive_state_runtime.py" \
  --root "$RUNTIME_SMOKE_ROOT" --recover </dev/null >/dev/null
rm -rf "$RUNTIME_SMOKE_ROOT"
find "$STAGING_DIR" -name ".DS_Store" -delete
find "$STAGING_DIR" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "$STAGING_DIR" -type f -name "*.pyc" -delete

if [[ -e "$TARGET_DIR" ]]; then
  mv "$TARGET_DIR" "$BACKUP_DIR"
  backup_created="$BACKUP_DIR"
  echo "Backed up existing skill to $BACKUP_DIR"
fi

if ! mv "$STAGING_DIR" "$TARGET_DIR"; then
  if [[ -n "$backup_created" && ! -e "$TARGET_DIR" ]]; then
    mv "$backup_created" "$TARGET_DIR"
  fi
  echo "Installation failed; restored the previous skill when possible" >&2
  exit 1
fi

install_complete=1
trap - EXIT
echo "Installed codex-loop-prompt-architect to $TARGET_DIR"
echo "Backups are stored outside the skills scan root at $BACKUP_ROOT"
echo "Open a new Codex App thread, then invoke: Use \$codex-loop-prompt-architect"
