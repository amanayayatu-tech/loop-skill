#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
PYTHON_BIN="${PYTHON:-python3}"
SKILLS_DIR="$CODEX_HOME_DIR/skills"
SOURCE_DIR="$ROOT_DIR/codex-loop-prompt-architect"
TARGET_DIR="$SKILLS_DIR/codex-loop-prompt-architect"
STATE_RUNTIME="$SOURCE_DIR/scripts/adaptive_state_runtime.py"
STATE_MCP="$SOURCE_DIR/scripts/adaptive_state_mcp.py"
MCP_CONFIG_HELPER="$SOURCE_DIR/scripts/configure_mcp.py"
INSTALL_VERIFY="$SOURCE_DIR/scripts/verify_installation.py"
APP_CANARY_VERIFY="$SOURCE_DIR/scripts/validate_app_canary_receipt.py"
STATE_SCHEMA="$SOURCE_DIR/references/adaptive-state.schema.json"
MUTATION_SCHEMA="$SOURCE_DIR/references/adaptive-mutation.schema.json"
INSTALL_SCHEMA="$SOURCE_DIR/references/install-manifest.schema.json"
APP_CANARY_SCHEMA="$SOURCE_DIR/references/app-canary-receipt.schema.json"
BACKUP_ROOT="$CODEX_HOME_DIR/skill-backups/codex-loop-prompt-architect"
STAGING_ROOT="$CODEX_HOME_DIR/install-staging"
STAMP="$(date +%Y%m%d%H%M%S)-$$"
STAGING_DIR="$STAGING_ROOT/codex-loop-prompt-architect-$STAMP"
BACKUP_DIR="$BACKUP_ROOT/$STAMP"
SKILL_BACKUP_DIR="$BACKUP_DIR/skill"
RUNTIME_SMOKE_ROOT="$STAGING_ROOT/runtime-smoke-$STAMP"
INSTALL_RECEIPT_DIR="$CODEX_HOME_DIR/install-receipts/codex-loop-prompt-architect"
INSTALL_RECEIPT="$INSTALL_RECEIPT_DIR/$STAMP.json"
backup_created=""
config_backup=""
config_existed=0
config_registration_attempted=0
target_installed=0
install_complete=0

cleanup() {
  if [[ "$install_complete" != "1" ]]; then
    if [[ "$config_registration_attempted" == "1" ]]; then
      if [[ "$config_existed" == "1" && -f "$config_backup" ]]; then
        cp -p "$config_backup" "$CODEX_HOME_DIR/config.toml"
      elif [[ "$config_existed" == "0" ]]; then
        rm -f "$CODEX_HOME_DIR/config.toml"
      fi
      echo "Installation interrupted; restored the prior MCP configuration" >&2
    fi
    if [[ "$target_installed" == "1" ]]; then
      rm -rf "$TARGET_DIR"
    fi
    if [[ -n "$backup_created" && ! -e "$TARGET_DIR" && -e "$backup_created" ]]; then
      mv "$backup_created" "$TARGET_DIR"
      echo "Installation interrupted; restored previous skill from $backup_created" >&2
    fi
  fi
  rm -rf "$STAGING_DIR"
  rm -rf "$RUNTIME_SMOKE_ROOT"
}
trap cleanup EXIT

if [[ ! -f "$SOURCE_DIR/SKILL.md" ]]; then
  echo "Missing skill source: $SOURCE_DIR/SKILL.md" >&2
  exit 1
fi

for required_file in "$STATE_RUNTIME" "$STATE_MCP" "$MCP_CONFIG_HELPER" "$INSTALL_VERIFY" "$APP_CANARY_VERIFY" "$STATE_SCHEMA" "$MUTATION_SCHEMA" "$INSTALL_SCHEMA" "$APP_CANARY_SCHEMA"; do
  if [[ ! -f "$required_file" ]]; then
    echo "Missing Adaptive state runtime artifact: $required_file" >&2
    exit 1
  fi
done

if ! "$PYTHON_BIN" -c 'import jsonschema, yaml; import importlib.util; assert importlib.util.find_spec("tomllib") or importlib.util.find_spec("tomli")' >/dev/null 2>&1; then
  echo "Missing Python dependencies: jsonschema, PyYAML, and a TOML reader. Install requirements-test.txt before installing this skill." >&2
  exit 1
fi

PYTHON_RESOLVED="$("$PYTHON_BIN" -c 'import os, sys; print(os.path.abspath(sys.executable))')"
if [[ "$PYTHON_RESOLVED" != /* || ! -x "$PYTHON_RESOLVED" ]]; then
  echo "Python executable did not resolve to a stable absolute executable: $PYTHON_RESOLVED" >&2
  exit 1
fi

"$PYTHON_BIN" "$SOURCE_DIR/scripts/validate_skill.py"

VALIDATOR="$CODEX_HOME_DIR/skills/.system/skill-creator/scripts/quick_validate.py"
if [[ -f "$VALIDATOR" ]]; then
  "$PYTHON_BIN" "$VALIDATOR" "$SOURCE_DIR"
fi

mkdir -p "$SKILLS_DIR" "$BACKUP_ROOT" "$STAGING_ROOT" "$BACKUP_DIR"

if [[ -f "$CODEX_HOME_DIR/config.toml" ]]; then
  config_existed=1
  config_backup="$BACKUP_DIR/config.toml.before"
  cp -p "$CODEX_HOME_DIR/config.toml" "$config_backup"
else
  config_backup="$BACKUP_DIR/config.toml.absent"
  : >"$config_backup"
fi

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
chmod +x "$STAGING_DIR/scripts/configure_mcp.py"
chmod +x "$STAGING_DIR/scripts/verify_installation.py"
chmod +x "$STAGING_DIR/scripts/validate_app_canary_receipt.py"
mkdir -p "$RUNTIME_SMOKE_ROOT"
"$PYTHON_BIN" "$STAGING_DIR/scripts/adaptive_state_runtime.py" \
  --root "$RUNTIME_SMOKE_ROOT" --recover </dev/null >/dev/null
rm -rf "$RUNTIME_SMOKE_ROOT"
find "$STAGING_DIR" -name ".DS_Store" -delete
find "$STAGING_DIR" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "$STAGING_DIR" -type f -name "*.pyc" -delete

if [[ -e "$TARGET_DIR" ]]; then
  mv "$TARGET_DIR" "$SKILL_BACKUP_DIR"
  backup_created="$SKILL_BACKUP_DIR"
  echo "Backed up existing skill to $SKILL_BACKUP_DIR"
fi

if ! mv "$STAGING_DIR" "$TARGET_DIR"; then
  if [[ -n "$backup_created" && ! -e "$TARGET_DIR" ]]; then
    mv "$backup_created" "$TARGET_DIR"
  fi
  echo "Installation failed; restored the previous skill when possible" >&2
  exit 1
fi

target_installed=1
config_registration_attempted=1
registration_json="$(
  "$PYTHON_RESOLVED" "$TARGET_DIR/scripts/configure_mcp.py" \
    --config "$CODEX_HOME_DIR/config.toml" \
    --python "$PYTHON_RESOLVED" \
    --script "$TARGET_DIR/scripts/adaptive_state_mcp.py"
)"
"$PYTHON_RESOLVED" "$TARGET_DIR/scripts/configure_mcp.py" \
  --config "$CODEX_HOME_DIR/config.toml" \
  --python "$PYTHON_RESOLVED" \
  --script "$TARGET_DIR/scripts/adaptive_state_mcp.py" \
  --check >/dev/null

repo_commit="${LOOP_RELEASE_COMMIT:-}"
source_head="$(git -C "$ROOT_DIR" rev-parse --verify HEAD 2>/dev/null || true)"
source_clean=0
if [[ -n "$source_head" ]] \
  && git -C "$ROOT_DIR" diff --quiet -- \
  && git -C "$ROOT_DIR" diff --cached --quiet -- \
  && [[ -z "$(git -C "$ROOT_DIR" ls-files --others --exclude-standard)" ]]; then
  source_clean=1
fi
if [[ -n "$repo_commit" && -n "$source_head" ]]; then
  if [[ "$repo_commit" != "$source_head" || "$source_clean" != "1" ]]; then
    echo "LOOP_RELEASE_COMMIT requires the same clean checked-out commit" >&2
    exit 1
  fi
elif [[ -z "$repo_commit" ]]; then
  repo_commit="UNVERIFIED_SOURCE"
  if [[ "$source_clean" == "1" ]]; then
    repo_commit="$source_head"
  fi
fi
if [[ -z "$repo_commit" ]]; then
  repo_commit="UNVERIFIED_SOURCE"
fi
skill_version="$(tr -d '[:space:]' <"$ROOT_DIR/VERSION")"
mkdir -p "$INSTALL_RECEIPT_DIR"
manifest_json="$(
  "$PYTHON_RESOLVED" "$TARGET_DIR/scripts/verify_installation.py" \
    --source "$SOURCE_DIR" \
    --installed "$TARGET_DIR" \
    --config "$CODEX_HOME_DIR/config.toml" \
    --python "$PYTHON_RESOLVED" \
    --script "$TARGET_DIR/scripts/adaptive_state_mcp.py" \
    --schema "$TARGET_DIR/references/install-manifest.schema.json" \
    --version "$skill_version" \
    --repo-commit "$repo_commit" \
    --output "$INSTALL_RECEIPT"
)"

install_complete=1
trap - EXIT
echo "Installed codex-loop-prompt-architect to $TARGET_DIR"
echo "Registered codex-loop-state with exact installed command and args"
echo "$registration_json"
echo "Verified source/install SHA and wrote $INSTALL_RECEIPT"
echo "$manifest_json"
echo "Backups are stored outside the skills scan root at $BACKUP_ROOT"
echo "Refresh or restart Codex App before the real MCP canary, then invoke: Use \$codex-loop-prompt-architect"
