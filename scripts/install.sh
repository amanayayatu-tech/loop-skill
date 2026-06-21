#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
SKILLS_DIR="$CODEX_HOME_DIR/skills"
SOURCE_DIR="$ROOT_DIR/codex-loop-prompt-architect"
TARGET_DIR="$SKILLS_DIR/codex-loop-prompt-architect"

if [[ ! -f "$SOURCE_DIR/SKILL.md" ]]; then
  echo "Missing skill source: $SOURCE_DIR/SKILL.md" >&2
  exit 1
fi

mkdir -p "$SKILLS_DIR"

if [[ -e "$TARGET_DIR" ]]; then
  BACKUP_DIR="${TARGET_DIR}.backup.$(date +%Y%m%d%H%M%S)"
  mv "$TARGET_DIR" "$BACKUP_DIR"
  echo "Backed up existing skill to $BACKUP_DIR"
fi

cp -R "$SOURCE_DIR" "$TARGET_DIR"
find "$TARGET_DIR" -name ".DS_Store" -delete
chmod +x "$TARGET_DIR/scripts/loop_prompt_scaffold.py" 2>/dev/null || true

echo "Installed codex-loop-prompt-architect to $TARGET_DIR"
echo "Open a new Codex App thread, then invoke: Use \$codex-loop-prompt-architect"
