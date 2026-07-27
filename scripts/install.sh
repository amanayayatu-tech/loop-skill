#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
PYTHON_BIN="${PYTHON:-python3}"
SOURCE_DIR="$ROOT_DIR/codex-loop-prompt-architect"
TARGET_DIR="$CODEX_HOME_DIR/skills/loopskill4"
LEGACY_TARGET="$CODEX_HOME_DIR/skills/codex-loop-prompt-architect"
STAGING_ROOT="$CODEX_HOME_DIR/install-staging"
RECEIPT_ROOT="$CODEX_HOME_DIR/install-receipts/loopskill4"
VERSION="$(tr -d '[:space:]' <"$ROOT_DIR/VERSION")"
installed_this_run=0
transaction=""

safe_remove_tree() {
  local target="$1"
  "$PYTHON_BIN" - "$target" <<'PY'
from pathlib import Path
import shutil
import sys

target = Path(sys.argv[1])
if target.exists():
    shutil.rmtree(target)
PY
}

cleanup() {
  if [[ "$installed_this_run" == "1" && -d "$TARGET_DIR" ]]; then
    safe_remove_tree "$TARGET_DIR"
  fi
  if [[ -n "$transaction" && -d "$transaction" ]]; then
    safe_remove_tree "$transaction"
  fi
}
trap cleanup EXIT

if [[ "$VERSION" != "4.0.0" ]]; then
  echo "V4_VERSION_INVALID: expected 4.0.0, got $VERSION" >&2
  exit 1
fi
for required in \
  "$SOURCE_DIR/SKILL.md" \
  "$SOURCE_DIR/scripts/loopskill4" \
  "$SOURCE_DIR/scripts/validate_skill.py" \
  "$SOURCE_DIR/scripts/verify_installation.py" \
  "$ROOT_DIR/protocol/v4/loopskill-v4.protocol.json" \
  "$ROOT_DIR/protocol/v4/generated/api-summary.json" \
  "$ROOT_DIR/protocol/v4/generated/loopskill-v4.schema.json"; do
  if [[ ! -f "$required" ]]; then
    echo "V4_INSTALL_SOURCE_INCOMPLETE: $required" >&2
    exit 1
  fi
done

if ! "$PYTHON_BIN" -c 'import sqlite3; assert sqlite3.sqlite_version' >/dev/null 2>&1; then
  echo "V4_PYTHON_SQLITE_UNAVAILABLE" >&2
  exit 1
fi

mkdir -p "$CODEX_HOME_DIR/skills" "$STAGING_ROOT" "$RECEIPT_ROOT"
transaction="$(mktemp -d "$STAGING_ROOT/loopskill4.XXXXXX")"
SOURCE_IMAGE="$transaction/source"
INSTALL_IMAGE="$transaction/install"
mkdir -p "$SOURCE_IMAGE" "$INSTALL_IMAGE"
cp -R "$SOURCE_DIR/." "$SOURCE_IMAGE/"
mkdir -p "$SOURCE_IMAGE/protocol/v4/generated"
cp "$ROOT_DIR/protocol/v4/loopskill-v4.protocol.json" "$SOURCE_IMAGE/protocol/v4/"
cp "$ROOT_DIR/protocol/v4/generated/api-summary.json" "$SOURCE_IMAGE/protocol/v4/generated/"
cp "$ROOT_DIR/protocol/v4/generated/loopskill-v4.schema.json" "$SOURCE_IMAGE/protocol/v4/generated/"
cp "$ROOT_DIR/VERSION" "$SOURCE_IMAGE/VERSION"
find "$SOURCE_IMAGE" -type f -name '*.pyc' -delete
find "$SOURCE_IMAGE" -type d -name '__pycache__' -empty -delete
find "$SOURCE_IMAGE" -type f -name '.DS_Store' -delete
chmod +x \
  "$SOURCE_IMAGE/scripts/loopskill4" \
  "$SOURCE_IMAGE/scripts/validate_skill.py" \
  "$SOURCE_IMAGE/scripts/verify_installation.py"
cp -R "$SOURCE_IMAGE/." "$INSTALL_IMAGE/"

"$PYTHON_BIN" "$SOURCE_IMAGE/scripts/validate_skill.py" "$SOURCE_IMAGE"
"$PYTHON_BIN" "$SOURCE_IMAGE/scripts/loopskill4" --help >/dev/null

inventory_equal() {
  "$PYTHON_BIN" - "$SOURCE_IMAGE/scripts/verify_installation.py" "$1" "$2" <<'PY'
import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location("loopskill4_verify", sys.argv[1])
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
raise SystemExit(0 if module.file_inventory(Path(sys.argv[2])) == module.file_inventory(Path(sys.argv[3])) else 1)
PY
}

if [[ -e "$TARGET_DIR" ]]; then
  if [[ ! -d "$TARGET_DIR" || -L "$TARGET_DIR" ]]; then
    echo "V4_INSTALL_CONFLICT: target is not a managed directory" >&2
    exit 1
  fi
  if inventory_equal "$SOURCE_IMAGE" "$TARGET_DIR"; then
    echo "LoopSkill 4.0.0 is already installed at $TARGET_DIR"
    echo "No files or Codex configuration changed."
    trap - EXIT
    safe_remove_tree "$transaction"
    exit 0
  fi
  echo "V4_INSTALL_CONFLICT: $TARGET_DIR already exists with different bytes" >&2
  exit 1
fi

config_existed=0
if [[ -f "$CODEX_HOME_DIR/config.toml" ]]; then
  config_existed=1
fi
config_hash() {
  "$PYTHON_BIN" - "$CODEX_HOME_DIR/config.toml" <<'PY'
from pathlib import Path
import hashlib
import sys

path = Path(sys.argv[1])
print(hashlib.sha256(path.read_bytes() if path.is_file() else b"").hexdigest())
PY
}
config_before="$(config_hash)"

mv "$INSTALL_IMAGE" "$TARGET_DIR"
installed_this_run=1
config_after="$(config_hash)"
if [[ "$config_before" != "$config_after" ]]; then
  echo "V4_CODEX_CONFIG_MUTATED" >&2
  exit 1
fi

repo_commit="SOURCE_ARCHIVE"
if git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  repo_commit="$(git -C "$ROOT_DIR" rev-parse HEAD)"
fi
if [[ -n "${LOOP_RELEASE_COMMIT:-}" && "$repo_commit" != "$LOOP_RELEASE_COMMIT" ]]; then
  echo "V4_RELEASE_COMMIT_MISMATCH" >&2
  exit 1
fi
stamp="$(date -u +%Y%m%dT%H%M%SZ)-$$"
receipt="$RECEIPT_ROOT/$stamp.json"
"$PYTHON_BIN" "$TARGET_DIR/scripts/verify_installation.py" \
  --source "$SOURCE_IMAGE" \
  --installed "$TARGET_DIR" \
  --version "$VERSION" \
  --repo-commit "$repo_commit" \
  --config-before-sha256 "$config_before" \
  --config-after-sha256 "$config_after" \
  --config-existed "$config_existed" \
  --output "$receipt" >/dev/null

if [[ -e "$LEGACY_TARGET" ]]; then
  legacy_message="An independent v3 installation was detected and left untouched."
else
  legacy_message="No v3 installation was changed or created."
fi
installed_this_run=0
trap - EXIT
safe_remove_tree "$transaction"
echo "Installed LoopSkill 4.0.0 to $TARGET_DIR"
echo "$legacy_message"
echo "Codex config.toml is byte-identical; no MCP entry was registered."
echo "LoopSkill 4 itself does not require a Codex App restart."
echo "Receipt: $receipt"
