#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
PYTHON_BIN="${PYTHON:-python3}"
SOURCE_DIR="$ROOT_DIR/codex-loop-prompt-architect"
SKILLS_ROOT="$CODEX_HOME_DIR/skills"
TARGET_DIR="$SKILLS_ROOT/loopskill4"
LEGACY_TARGET="$SKILLS_ROOT/codex-loop-prompt-architect"
STAGING_ROOT="$CODEX_HOME_DIR/install-staging"
INSTALL_RECEIPTS_ROOT="$CODEX_HOME_DIR/install-receipts"
RECEIPT_ROOT="$INSTALL_RECEIPTS_ROOT/loopskill4"
UNINSTALL_STAGING_ROOT="$CODEX_HOME_DIR/uninstall-staging"
MANAGEMENT_UNINSTALLER="$RECEIPT_ROOT/uninstall_v4.py"
ACTIVE_POINTER="$RECEIPT_ROOT/active-receipt"
ACTIVE_TRANSACTION="$RECEIPT_ROOT/active-transaction.json"
VERSION="$(tr -d '[:space:]' <"$ROOT_DIR/VERSION")"

if [[ "${1:-}" != "--loopskill4-internal-locked" ]]; then
  if [[ "$#" != "0" ]]; then
    echo "V4_INSTALL_ARGUMENT_INVALID" >&2
    exit 1
  fi
  exec "$PYTHON_BIN" - "$0" "$CODEX_HOME_DIR" <<'PY'
from pathlib import Path
import fcntl
import os
import stat
import subprocess
import sys

script = Path(sys.argv[1]).resolve(strict=True)
home = Path(sys.argv[2])
if not home.is_absolute() or ".." in home.parts or home == Path(home.anchor):
    raise SystemExit("V4_INSTALL_CODEX_HOME_INVALID")
cursor = Path(home.anchor)
for part in home.parts[1:]:
    cursor /= part
    if not os.path.lexists(cursor):
        break
    if stat.S_ISLNK(cursor.lstat().st_mode):
        raise SystemExit("V4_INSTALL_CODEX_HOME_SYMLINK_FORBIDDEN")
parent = home.parent
metadata = parent.lstat()
if (
    not stat.S_ISDIR(metadata.st_mode)
    or metadata.st_uid != os.getuid()
    or metadata.st_mode & 0o022
):
    raise SystemExit("V4_INSTALL_CODEX_HOME_PARENT_UNSAFE")
descriptor = os.open(
    parent,
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0),
)
try:
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    environment = {
        **os.environ,
        "CODEX_HOME": str(home),
        "LOOPSKILL4_MANAGEMENT_LOCK_FD": str(descriptor),
    }
    raise SystemExit(
        subprocess.call(
            [str(script), "--loopskill4-internal-locked"],
            env=environment,
            pass_fds=(descriptor,),
        )
    )
finally:
    os.close(descriptor)
PY
fi
shift

"$PYTHON_BIN" - "$CODEX_HOME_DIR" "${LOOPSKILL4_MANAGEMENT_LOCK_FD:-}" <<'PY'
from pathlib import Path
import fcntl
import os
import stat
import sys

home = Path(sys.argv[1])
try:
    descriptor = int(sys.argv[2])
    descriptor_metadata = os.fstat(descriptor)
    parent_metadata = home.parent.lstat()
except (OSError, ValueError) as exc:
    raise SystemExit("V4_INSTALL_LOCK_INVALID") from exc
if (
    not stat.S_ISDIR(descriptor_metadata.st_mode)
    or (descriptor_metadata.st_dev, descriptor_metadata.st_ino)
    != (parent_metadata.st_dev, parent_metadata.st_ino)
):
    raise SystemExit("V4_INSTALL_LOCK_INVALID")
fcntl.flock(descriptor, fcntl.LOCK_EX)
PY

transaction=""
receipt=""
pointer_preexisted=0
journal_created=0

path_was_absent() {
  if [[ -e "$1" || -L "$1" ]]; then
    printf '0\n'
  else
    printf '1\n'
  fi
}

created_codex_home="$(path_was_absent "$CODEX_HOME_DIR")"
created_skills_root="$(path_was_absent "$SKILLS_ROOT")"
created_staging_root="$(path_was_absent "$STAGING_ROOT")"
created_install_receipts_root="$(path_was_absent "$INSTALL_RECEIPTS_ROOT")"
created_receipt_root="$(path_was_absent "$RECEIPT_ROOT")"
created_uninstall_staging_root="$(path_was_absent "$UNINSTALL_STAGING_ROOT")"

safe_remove_tree() {
  "$PYTHON_BIN" - "$1" "$2" <<'PY'
from pathlib import Path
import os
import shutil
import stat
import sys

target = Path(sys.argv[1])
parent = Path(sys.argv[2]).resolve(strict=True)
if not os.path.lexists(target):
    raise SystemExit(0)
metadata = target.lstat()
if (
    stat.S_ISLNK(metadata.st_mode)
    or not stat.S_ISDIR(metadata.st_mode)
    or target.resolve(strict=True).parent != parent
):
    raise SystemExit("V4_INSTALL_CLEANUP_PATH_INVALID")
shutil.rmtree(target)
PY
}

remove_created_dir() {
  "$PYTHON_BIN" - "$1" <<'PY'
from pathlib import Path
import os
import stat
import sys

target = Path(sys.argv[1])
if not os.path.lexists(target):
    raise SystemExit(0)
metadata = target.lstat()
if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
    raise SystemExit("V4_INSTALL_CLEANUP_PATH_INVALID")
try:
    target.rmdir()
except OSError:
    pass
PY
}

atomic_install_file() {
  "$PYTHON_BIN" - "$1" "$2" "$3" "$4" <<'PY'
from pathlib import Path
import os
import secrets
import stat
import sys

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
mode = int(sys.argv[3], 8)
replace = sys.argv[4] == "replace"
source_metadata = source.lstat()
parent_metadata = destination.parent.lstat()
if stat.S_ISLNK(source_metadata.st_mode) or not stat.S_ISREG(source_metadata.st_mode):
    raise SystemExit("V4_INSTALL_ATOMIC_SOURCE_INVALID")
if (
    stat.S_ISLNK(parent_metadata.st_mode)
    or not stat.S_ISDIR(parent_metadata.st_mode)
    or parent_metadata.st_uid != os.getuid()
    or parent_metadata.st_mode & 0o022
):
    raise SystemExit("V4_INSTALL_ATOMIC_PARENT_INVALID")
if os.path.lexists(destination):
    destination_metadata = destination.lstat()
    if (
        not replace
        or stat.S_ISLNK(destination_metadata.st_mode)
        or not stat.S_ISREG(destination_metadata.st_mode)
        or destination_metadata.st_uid != os.getuid()
        or destination_metadata.st_mode & 0o022
    ):
        raise SystemExit("V4_INSTALL_ATOMIC_DESTINATION_CONFLICT")
temporary = destination.with_name(
    f".{destination.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
)
descriptor = -1
try:
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    view = memoryview(source.read_bytes())
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short atomic write")
        view = view[written:]
    os.fsync(descriptor)
    os.close(descriptor)
    descriptor = -1
    os.chmod(temporary, mode, follow_symlinks=False)
    if replace:
        os.replace(temporary, destination)
    else:
        os.link(temporary, destination, follow_symlinks=False)
        temporary.unlink()
    directory = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
finally:
    if descriptor >= 0:
        os.close(descriptor)
    try:
        temporary.unlink()
    except FileNotFoundError:
        pass
PY
}

recover_install_transaction() {
  "$PYTHON_BIN" - \
    "$CODEX_HOME_DIR" "$STAGING_ROOT" "$RECEIPT_ROOT" "$TARGET_DIR" \
    "$MANAGEMENT_UNINSTALLER" "$ACTIVE_POINTER" "$ACTIVE_TRANSACTION" <<'PY'
from pathlib import Path
import hashlib
import json
import os
import shutil
import stat
import sys

home, staging, receipt_root, target, manager, pointer, journal_path = map(
    Path, sys.argv[1:]
)


def lexists(path: Path) -> bool:
    return os.path.lexists(path)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def ignored(relative: Path) -> bool:
    return (
        "__pycache__" in relative.parts
        or relative.suffix == ".pyc"
        or relative.name == ".DS_Store"
    )


def inventory(root: Path) -> list[dict[str, object]]:
    metadata = root.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o022
    ):
        raise SystemExit("V4_INSTALL_RECOVERY_TARGET_INVALID")
    result: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if ignored(relative):
            continue
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise SystemExit("V4_INSTALL_RECOVERY_SYMLINK_FORBIDDEN")
        if metadata.st_uid != os.getuid() or metadata.st_mode & 0o022:
            raise SystemExit("V4_INSTALL_RECOVERY_TARGET_INVALID")
        if stat.S_ISDIR(metadata.st_mode):
            result.append({"kind": "directory", "path": relative.as_posix()})
        elif stat.S_ISREG(metadata.st_mode):
            result.append(
                {
                    "executable": bool(metadata.st_mode & stat.S_IXUSR),
                    "kind": "file",
                    "path": relative.as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        else:
            raise SystemExit("V4_INSTALL_RECOVERY_SPECIAL_FILE_FORBIDDEN")
    return result


def inventory_digest(root: Path) -> str:
    return hashlib.sha256(canonical(inventory(root))).hexdigest()


def secure_regular(path: Path, parent: Path, error: str) -> bytes:
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o022
        or path.resolve(strict=True).parent != parent
    ):
        raise SystemExit(error)
    return path.read_bytes()


def secure_transaction(path: Path) -> None:
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o022
        or path.resolve(strict=True).parent != staging
    ):
        raise SystemExit("V4_INSTALL_RECOVERY_TRANSACTION_INVALID")


transactions = sorted(
    path for path in staging.iterdir() if path.name.startswith("loopskill4.")
)
if not lexists(journal_path):
    # No visible product mutation occurs before the journal is durable. An
    # interrupted source-image build is therefore safe staging-only garbage.
    for transaction in transactions:
        secure_transaction(transaction)
        shutil.rmtree(transaction)
    if transactions:
        fsync_directory(staging)
    raise SystemExit(0)

raw_journal = secure_regular(
    journal_path, receipt_root, "V4_INSTALL_RECOVERY_JOURNAL_INVALID"
)
try:
    journal = json.loads(raw_journal.decode("utf-8", "strict"))
except (UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("V4_INSTALL_RECOVERY_JOURNAL_INVALID") from exc
required = {
    "artifact",
    "kind",
    "manager_preexisted",
    "manager_sha256",
    "pointer_backup_sha256",
    "pointer_preexisted",
    "receipt",
    "target_manifest_digest",
    "transaction",
}
if (
    not isinstance(journal, dict)
    or set(journal) != required
    or journal["artifact"] != "loopskill4-distribution-transaction-v1"
    or journal["kind"] != "INSTALL"
    or not isinstance(journal["manager_preexisted"], bool)
    or not isinstance(journal["pointer_preexisted"], bool)
    or not isinstance(journal["manager_sha256"], str)
    or len(journal["manager_sha256"]) != 64
    or not isinstance(journal["target_manifest_digest"], str)
    or len(journal["target_manifest_digest"]) != 64
    or not isinstance(journal["receipt"], str)
    or Path(journal["receipt"]).name != journal["receipt"]
    or not journal["receipt"].endswith(".json")
    or not isinstance(journal["transaction"], str)
    or Path(journal["transaction"]).name != journal["transaction"]
    or not journal["transaction"].startswith("loopskill4.")
    or (
        journal["pointer_backup_sha256"] is not None
        and (
            not isinstance(journal["pointer_backup_sha256"], str)
            or len(journal["pointer_backup_sha256"]) != 64
        )
    )
):
    raise SystemExit("V4_INSTALL_RECOVERY_JOURNAL_INVALID")

transaction = staging / journal["transaction"]
if transactions not in ([], [transaction]):
    raise SystemExit("V4_INSTALL_RECOVERY_TRANSACTION_AMBIGUOUS")
if lexists(transaction):
    secure_transaction(transaction)
receipt = receipt_root / journal["receipt"]
receipt_raw = (
    secure_regular(receipt, receipt_root, "V4_INSTALL_RECOVERY_RECEIPT_INVALID")
    if lexists(receipt)
    else None
)
expected_pointer = None
if receipt_raw is not None:
    expected_pointer = canonical(
        {
            "receipt": receipt.name,
            "sha256": hashlib.sha256(receipt_raw).hexdigest(),
        }
    )
pointer_raw = (
    secure_regular(pointer, receipt_root, "V4_INSTALL_RECOVERY_POINTER_INVALID")
    if lexists(pointer)
    else None
)
manager_raw = (
    secure_regular(manager, receipt_root, "V4_INSTALL_RECOVERY_MANAGER_INVALID")
    if lexists(manager)
    else None
)
target_digest = inventory_digest(target) if lexists(target) else None

committed = (
    expected_pointer is not None
    and pointer_raw == expected_pointer
    and manager_raw is not None
    and hashlib.sha256(manager_raw).hexdigest() == journal["manager_sha256"]
    and target_digest == journal["target_manifest_digest"]
)
if committed:
    try:
        receipt_value = json.loads(receipt_raw.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("V4_INSTALL_RECOVERY_RECEIPT_INVALID") from exc
    if receipt_value.get("installed_manifest_digest") != journal["target_manifest_digest"]:
        raise SystemExit("V4_INSTALL_RECOVERY_RECEIPT_INVALID")
    if lexists(transaction):
        shutil.rmtree(transaction)
        fsync_directory(staging)
    journal_path.unlink()
    fsync_directory(receipt_root)
    raise SystemExit(0)

# Pointer not committed: restore only transaction-bound objects.
backup = transaction / "active-receipt.backup"
if journal["pointer_preexisted"]:
    backup_digest = journal["pointer_backup_sha256"]
    if pointer_raw is not None and hashlib.sha256(pointer_raw).hexdigest() == backup_digest:
        pass
    elif expected_pointer is not None and pointer_raw == expected_pointer:
        backup_raw = secure_regular(
            backup, transaction, "V4_INSTALL_RECOVERY_POINTER_BACKUP_INVALID"
        )
        if hashlib.sha256(backup_raw).hexdigest() != backup_digest:
            raise SystemExit("V4_INSTALL_RECOVERY_POINTER_BACKUP_INVALID")
        temporary = pointer.with_name(f".{pointer.name}.{os.getpid()}.recovery")
        temporary.write_bytes(backup_raw)
        os.chmod(temporary, 0o600)
        os.replace(temporary, pointer)
        fsync_directory(receipt_root)
    else:
        raise SystemExit("V4_INSTALL_RECOVERY_POINTER_AMBIGUOUS")
elif pointer_raw is not None:
    if expected_pointer is None or pointer_raw != expected_pointer:
        raise SystemExit("V4_INSTALL_RECOVERY_POINTER_AMBIGUOUS")
    pointer.unlink()
    fsync_directory(receipt_root)

if receipt_raw is not None:
    try:
        receipt_value = json.loads(receipt_raw.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("V4_INSTALL_RECOVERY_RECEIPT_INVALID") from exc
    if receipt_value.get("installed_manifest_digest") != journal["target_manifest_digest"]:
        raise SystemExit("V4_INSTALL_RECOVERY_RECEIPT_INVALID")
    receipt.unlink()
    fsync_directory(receipt_root)
if not journal["manager_preexisted"] and manager_raw is not None:
    if hashlib.sha256(manager_raw).hexdigest() != journal["manager_sha256"]:
        raise SystemExit("V4_INSTALL_RECOVERY_MANAGER_INVALID")
    manager.unlink()
    fsync_directory(receipt_root)
if target_digest is not None:
    if target_digest != journal["target_manifest_digest"] or not lexists(transaction):
        raise SystemExit("V4_INSTALL_RECOVERY_TARGET_AMBIGUOUS")
    rollback_target = transaction / "rollback-target"
    if lexists(rollback_target):
        raise SystemExit("V4_INSTALL_RECOVERY_TARGET_AMBIGUOUS")
    os.replace(target, rollback_target)
    fsync_directory(target.parent)
    fsync_directory(transaction)
if lexists(transaction):
    shutil.rmtree(transaction)
    fsync_directory(staging)
journal_path.unlink()
fsync_directory(receipt_root)
PY
}

cleanup() {
  set +e
  if [[ "$journal_created" == "1" ]]; then
    recover_install_transaction
    recovered=$?
    if [[ "$recovered" == "0" ]]; then
      transaction=""
      journal_created=0
    else
      return
    fi
  fi
  if [[ -n "$transaction" && ( -e "$transaction" || -L "$transaction" ) ]]; then
    safe_remove_tree "$transaction" "$STAGING_ROOT"
  fi
  if [[ "$created_uninstall_staging_root" == "1" ]]; then
    remove_created_dir "$UNINSTALL_STAGING_ROOT"
  fi
  if [[ "$created_receipt_root" == "1" ]]; then
    remove_created_dir "$RECEIPT_ROOT"
  fi
  if [[ "$created_install_receipts_root" == "1" ]]; then
    remove_created_dir "$INSTALL_RECEIPTS_ROOT"
  fi
  if [[ "$created_staging_root" == "1" ]]; then
    remove_created_dir "$STAGING_ROOT"
  fi
  if [[ "$created_skills_root" == "1" ]]; then
    remove_created_dir "$SKILLS_ROOT"
  fi
  if [[ "$created_codex_home" == "1" ]]; then
    remove_created_dir "$CODEX_HOME_DIR"
  fi
}
trap cleanup EXIT

maybe_fault() {
  if [[ "${LOOPSKILL4_TEST_INSTALL_FAULT:-}" == "crash_$1" ]]; then
    echo "V4_INSTALL_TEST_CRASH: $1" >&2
    kill -KILL "$$"
  fi
  if [[ "${LOOPSKILL4_TEST_INSTALL_FAULT:-}" == "$1" ]]; then
    echo "V4_INSTALL_TEST_FAULT: $1" >&2
    return 1
  fi
}

if [[ "$VERSION" != "4.1.1" ]]; then
  echo "V4_VERSION_INVALID: expected 4.1.1, got $VERSION" >&2
  exit 1
fi
for required in \
  "$SOURCE_DIR/SKILL.md" \
  "$SOURCE_DIR/scripts/loopskill4" \
  "$SOURCE_DIR/scripts/validate_skill.py" \
  "$SOURCE_DIR/scripts/verify_installation.py" \
  "$ROOT_DIR/scripts/uninstall_v4.py" \
  "$ROOT_DIR/protocol/v4/loopskill-v4.protocol.json" \
  "$ROOT_DIR/protocol/v4/generated/api-summary.json" \
  "$ROOT_DIR/protocol/v4/generated/loopskill-v4.schema.json"; do
  if [[ ! -f "$required" || -L "$required" ]]; then
    echo "V4_INSTALL_SOURCE_INCOMPLETE: $required" >&2
    exit 1
  fi
done

case "${LOOPSKILL4_TEST_INSTALL_FAULT:-}" in
  ""|after_target|after_manager|after_receipt|after_pointer|\
crash_after_target|crash_after_manager|crash_after_receipt|crash_after_pointer) ;;
  *)
    echo "V4_INSTALL_TEST_FAULT_INVALID" >&2
    exit 1
    ;;
esac

if ! "$PYTHON_BIN" -c 'import sqlite3; assert sqlite3.sqlite_version' >/dev/null 2>&1; then
  echo "V4_PYTHON_SQLITE_UNAVAILABLE" >&2
  exit 1
fi

"$PYTHON_BIN" - "$CODEX_HOME_DIR" <<'PY'
from pathlib import Path
import os
import stat
import sys

raw_home = Path(sys.argv[1])
if not raw_home.is_absolute() or ".." in raw_home.parts or raw_home == Path(raw_home.anchor):
    raise SystemExit("V4_INSTALL_CODEX_HOME_INVALID")


def lexists(path: Path) -> bool:
    return os.path.lexists(path)


def secure_directory(path: Path, home: Path | None, *, create: bool) -> Path:
    if not lexists(path):
        if not create:
            raise SystemExit(f"V4_INSTALL_PATH_MISSING: {path}")
        path.mkdir(mode=0o700)
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o022
    ):
        raise SystemExit(f"V4_INSTALL_PATH_UNSAFE: {path}")
    resolved = path.resolve(strict=True)
    if home is not None:
        try:
            resolved.relative_to(home)
        except ValueError as exc:
            raise SystemExit(f"V4_INSTALL_PATH_OUTSIDE_HOME: {path}") from exc
    return resolved


parent = raw_home.parent
parent_metadata = parent.lstat()
if (
    stat.S_ISLNK(parent_metadata.st_mode)
    or not stat.S_ISDIR(parent_metadata.st_mode)
    or parent_metadata.st_uid != os.getuid()
    or parent_metadata.st_mode & 0o022
):
    raise SystemExit("V4_INSTALL_CODEX_HOME_PARENT_UNSAFE")
if not lexists(raw_home):
    raw_home.mkdir(mode=0o700)
home = secure_directory(raw_home, None, create=False)

owned = (
    home / "skills",
    home / "install-staging",
    home / "install-receipts",
    home / "install-receipts/loopskill4",
    home / "uninstall-staging",
)
for path in owned:
    secure_directory(path, home, create=True)

for path in (home / "skills/loopskill4",):
    if lexists(path):
        secure_directory(path, home, create=False)

config = home / "config.toml"
if lexists(config):
    metadata = config.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SystemExit("V4_INSTALL_CONFIG_INVALID")

for path in (
    home / "install-receipts/loopskill4/uninstall_v4.py",
    home / "install-receipts/loopskill4/active-receipt",
    home / "install-receipts/loopskill4/active-transaction.json",
):
    if lexists(path):
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o022
        ):
            raise SystemExit(f"V4_INSTALL_MANAGEMENT_PATH_UNSAFE: {path}")
PY

if [[ -e "$ACTIVE_TRANSACTION" || -L "$ACTIVE_TRANSACTION" ]]; then
  transaction_kind="$("$PYTHON_BIN" - "$ACTIVE_TRANSACTION" <<'PY'
from pathlib import Path
import json
import sys

try:
    value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("V4_INSTALL_RECOVERY_JOURNAL_INVALID") from exc
kind = value.get("kind") if isinstance(value, dict) else None
if kind not in ("INSTALL", "UNINSTALL"):
    raise SystemExit("V4_INSTALL_RECOVERY_JOURNAL_INVALID")
print(kind)
PY
)"
  if [[ "$transaction_kind" == "UNINSTALL" ]]; then
    if [[ ! -f "$MANAGEMENT_UNINSTALLER" || -L "$MANAGEMENT_UNINSTALLER" ]]; then
      echo "V4_INSTALL_UNINSTALL_RECOVERY_UNAVAILABLE" >&2
      exit 1
    fi
    "$PYTHON_BIN" "$MANAGEMENT_UNINSTALLER" \
      --codex-home "$CODEX_HOME_DIR" --check >/dev/null
  fi
fi
recover_install_transaction

repo_commit="SOURCE_ARCHIVE"
git_source_mode="archive"
git_archive_commit=""
if git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git_top="$(git -C "$ROOT_DIR" rev-parse --show-toplevel)"
  if [[ "$git_top" == "$ROOT_DIR" ]]; then
    git_source_mode="tracked-worktree"
    if [[ -z "$(git -C "$ROOT_DIR" status --porcelain --untracked-files=all)" ]]; then
      git_archive_commit="$(git -C "$ROOT_DIR" rev-parse HEAD)"
      repo_commit="$git_archive_commit"
      git_source_mode="exact-commit"
    fi
  fi
fi
if [[ -n "${LOOP_RELEASE_COMMIT:-}" && "$repo_commit" != "$LOOP_RELEASE_COMMIT" ]]; then
  echo "V4_RELEASE_COMMIT_MISMATCH" >&2
  exit 1
fi

transaction="$(mktemp -d "$STAGING_ROOT/loopskill4.XXXXXX")"
SOURCE_IMAGE="$transaction/source"
INSTALL_IMAGE="$transaction/install"
mkdir -p "$SOURCE_IMAGE" "$INSTALL_IMAGE"
if [[ "$git_source_mode" == "exact-commit" ]]; then
  TRACKED_ARCHIVE="$transaction/tracked"
  TRACKED_ARCHIVE_TAR="$transaction/tracked.tar"
  mkdir -p "$TRACKED_ARCHIVE"
  # Keep archive production and extraction sequential. Some BSD tar builds may
  # close stdin after the end marker, which turns git archive into SIGPIPE 141
  # under pipefail even though extraction completed successfully.
  git -C "$ROOT_DIR" archive --format=tar --output="$TRACKED_ARCHIVE_TAR" \
    "$git_archive_commit" -- \
    codex-loop-prompt-architect \
    protocol/v4/loopskill-v4.protocol.json \
    protocol/v4/generated/api-summary.json \
    protocol/v4/generated/loopskill-v4.schema.json \
    VERSION
  tar -xf "$TRACKED_ARCHIVE_TAR" -C "$TRACKED_ARCHIVE"
  cp -R "$TRACKED_ARCHIVE/codex-loop-prompt-architect/." "$SOURCE_IMAGE/"
  mkdir -p "$SOURCE_IMAGE/protocol/v4/generated"
  cp "$TRACKED_ARCHIVE/protocol/v4/loopskill-v4.protocol.json" "$SOURCE_IMAGE/protocol/v4/"
  cp "$TRACKED_ARCHIVE/protocol/v4/generated/api-summary.json" "$SOURCE_IMAGE/protocol/v4/generated/"
  cp "$TRACKED_ARCHIVE/protocol/v4/generated/loopskill-v4.schema.json" "$SOURCE_IMAGE/protocol/v4/generated/"
  cp "$TRACKED_ARCHIVE/VERSION" "$SOURCE_IMAGE/VERSION"
elif [[ "$git_source_mode" == "tracked-worktree" ]]; then
  "$PYTHON_BIN" - "$ROOT_DIR" "$SOURCE_IMAGE" <<'PY'
from pathlib import Path
import os
import shutil
import stat
import subprocess
import sys

root = Path(sys.argv[1]).resolve(strict=True)
output = Path(sys.argv[2]).resolve(strict=True)
package = Path("codex-loop-prompt-architect")
selected = subprocess.run(
    [
        "git",
        "-C",
        str(root),
        "ls-files",
        "-z",
        "--",
        str(package),
        "protocol/v4/loopskill-v4.protocol.json",
        "protocol/v4/generated/api-summary.json",
        "protocol/v4/generated/loopskill-v4.schema.json",
        "VERSION",
    ],
    check=True,
    stdout=subprocess.PIPE,
).stdout.split(b"\0")
for encoded in selected:
    if not encoded:
        continue
    relative = Path(os.fsdecode(encoded))
    if relative.is_absolute() or ".." in relative.parts:
        raise SystemExit("V4_INSTALL_TRACKED_SOURCE_INVALID")
    source = root / relative
    destination_relative = (
        relative.relative_to(package)
        if relative.parts[:1] == package.parts
        else relative
    )
    destination = output / destination_relative
    metadata = source.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SystemExit("V4_INSTALL_TRACKED_SOURCE_INVALID")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination, follow_symlinks=False)
    os.chmod(destination, stat.S_IMODE(metadata.st_mode), follow_symlinks=False)
PY
else
  cp -R "$SOURCE_DIR/." "$SOURCE_IMAGE/"
  mkdir -p "$SOURCE_IMAGE/protocol/v4/generated"
  cp "$ROOT_DIR/protocol/v4/loopskill-v4.protocol.json" "$SOURCE_IMAGE/protocol/v4/"
  cp "$ROOT_DIR/protocol/v4/generated/api-summary.json" "$SOURCE_IMAGE/protocol/v4/generated/"
  cp "$ROOT_DIR/protocol/v4/generated/loopskill-v4.schema.json" "$SOURCE_IMAGE/protocol/v4/generated/"
  cp "$ROOT_DIR/VERSION" "$SOURCE_IMAGE/VERSION"
fi
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
raise SystemExit(
    0
    if module.file_inventory(Path(sys.argv[2]))
    == module.file_inventory(Path(sys.argv[3]))
    else 1
)
PY
}

sha256_file() {
  "$PYTHON_BIN" - "$1" <<'PY'
from pathlib import Path
import hashlib
import sys

path = Path(sys.argv[1])
print(hashlib.sha256(path.read_bytes()).hexdigest())
PY
}

fsync_directory() {
  "$PYTHON_BIN" - "$1" <<'PY'
from pathlib import Path
import os
import sys

descriptor = os.open(Path(sys.argv[1]), os.O_RDONLY)
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY
}

manager_digest="$(sha256_file "$ROOT_DIR/scripts/uninstall_v4.py")"
manager_present=0
pointer_present=0
if [[ -f "$MANAGEMENT_UNINSTALLER" && ! -L "$MANAGEMENT_UNINSTALLER" ]]; then
  manager_present=1
fi
if [[ -f "$ACTIVE_POINTER" && ! -L "$ACTIVE_POINTER" ]]; then
  pointer_present=1
fi
if [[ "$manager_present" != "$pointer_present" ]]; then
  echo "V4_INSTALL_MANAGEMENT_STATE_AMBIGUOUS" >&2
  exit 1
fi
if [[ "$manager_present" == "1" ]]; then
  if [[ "$(sha256_file "$MANAGEMENT_UNINSTALLER")" != "$manager_digest" ]]; then
    echo "V4_INSTALL_MANAGEMENT_UNINSTALLER_DRIFT" >&2
    exit 1
  fi
  if ! "$PYTHON_BIN" "$MANAGEMENT_UNINSTALLER" \
    --codex-home "$CODEX_HOME_DIR" --check >/dev/null; then
    echo "V4_INSTALL_ACTIVE_RECEIPT_INVALID" >&2
    exit 1
  fi
  pointer_preexisted=1
  "$PYTHON_BIN" - "$ACTIVE_POINTER" "$transaction/active-receipt.backup" <<'PY'
from pathlib import Path
import os
import sys

target = Path(sys.argv[2])
descriptor = os.open(
    target,
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
    0o600,
)
try:
    view = memoryview(Path(sys.argv[1]).read_bytes())
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short pointer backup write")
        view = view[written:]
    os.fsync(descriptor)
finally:
    os.close(descriptor)
directory = os.open(target.parent, os.O_RDONLY)
try:
    os.fsync(directory)
finally:
    os.close(directory)
PY
fi

if [[ -e "$TARGET_DIR" || -L "$TARGET_DIR" ]]; then
  if [[ ! -d "$TARGET_DIR" || -L "$TARGET_DIR" ]]; then
    echo "V4_INSTALL_CONFLICT: target is not a managed directory" >&2
    exit 1
  fi
  if inventory_equal "$SOURCE_IMAGE" "$TARGET_DIR"; then
    if [[ "$manager_present" != "1" ]]; then
      echo "V4_INSTALL_ACTIVE_RECEIPT_INVALID" >&2
      exit 1
    fi
    echo "LoopSkill 4.1.1 is already installed at $TARGET_DIR"
    echo "No files or Codex configuration changed."
    safe_remove_tree "$transaction" "$STAGING_ROOT"
    transaction=""
    trap - EXIT
    exit 0
  fi
  echo "V4_INSTALL_CONFLICT: $TARGET_DIR already exists with different bytes" >&2
  exit 1
fi

receipt_name="$(date -u +%Y%m%dT%H%M%SZ)-$$-$RANDOM.json"
receipt="$RECEIPT_ROOT/$receipt_name"
target_manifest_digest="$("$PYTHON_BIN" - \
  "$SOURCE_IMAGE/scripts/verify_installation.py" "$INSTALL_IMAGE" <<'PY'
import importlib.util
from pathlib import Path
import os
import sys

spec = importlib.util.spec_from_file_location("loopskill4_verify", sys.argv[1])
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
root = Path(sys.argv[2])
for path in sorted(root.rglob("*")):
    if path.is_file() and not path.is_symlink():
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
for path in sorted(
    (value for value in root.rglob("*") if value.is_dir() and not value.is_symlink()),
    key=lambda value: len(value.parts),
    reverse=True,
):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
descriptor = os.open(root, os.O_RDONLY)
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
print(module.digest(module.file_inventory(root)))
PY
)"
pointer_backup_sha256="null"
if [[ "$pointer_preexisted" == "1" ]]; then
  pointer_backup_sha256="\"$(sha256_file "$transaction/active-receipt.backup")\""
fi
staged_journal="$transaction/active-transaction.json"
"$PYTHON_BIN" - \
  "$staged_journal" "$(basename "$transaction")" "$receipt_name" \
  "$manager_present" "$pointer_preexisted" "$manager_digest" \
  "$pointer_backup_sha256" "$target_manifest_digest" <<'PY'
from pathlib import Path
import json
import os
import sys

output = Path(sys.argv[1])
payload = json.dumps(
    {
        "artifact": "loopskill4-distribution-transaction-v1",
        "kind": "INSTALL",
        "manager_preexisted": sys.argv[4] == "1",
        "manager_sha256": sys.argv[6],
        "pointer_backup_sha256": json.loads(sys.argv[7]),
        "pointer_preexisted": sys.argv[5] == "1",
        "receipt": sys.argv[3],
        "target_manifest_digest": sys.argv[8],
        "transaction": sys.argv[2],
    },
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8") + b"\n"
descriptor = os.open(
    output,
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
    0o600,
)
try:
    os.write(descriptor, payload)
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY
atomic_install_file "$staged_journal" "$ACTIVE_TRANSACTION" 0600 create
journal_created=1

config_state() {
  "$PYTHON_BIN" - "$CODEX_HOME_DIR/config.toml" <<'PY'
from pathlib import Path
import hashlib
import os
import stat
import sys

path = Path(sys.argv[1])
if not os.path.lexists(path):
    print("0:" + hashlib.sha256(b"").hexdigest())
else:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SystemExit("V4_INSTALL_CONFIG_INVALID")
    print("1:" + hashlib.sha256(path.read_bytes()).hexdigest())
PY
}

config_before_state="$(config_state)"
config_existed="${config_before_state%%:*}"
config_before="${config_before_state#*:}"

mv "$INSTALL_IMAGE" "$TARGET_DIR"
fsync_directory "$SKILLS_ROOT"
maybe_fault after_target

config_after_state="$(config_state)"
if [[ "$config_before_state" != "$config_after_state" ]]; then
  echo "V4_CODEX_CONFIG_MUTATED" >&2
  exit 1
fi
config_after="${config_after_state#*:}"

staged_receipt="$transaction/receipt.json"
"$PYTHON_BIN" "$TARGET_DIR/scripts/verify_installation.py" \
  --source "$SOURCE_IMAGE" \
  --installed "$TARGET_DIR" \
  --version "$VERSION" \
  --repo-commit "$repo_commit" \
  --management-uninstaller-sha256 "$manager_digest" \
  --config-before-sha256 "$config_before" \
  --config-after-sha256 "$config_after" \
  --config-existed "$config_existed" \
  --output "$staged_receipt" >/dev/null

if [[ "$manager_present" == "0" ]]; then
  atomic_install_file \
    "$ROOT_DIR/scripts/uninstall_v4.py" "$MANAGEMENT_UNINSTALLER" 0755 create
fi
maybe_fault after_manager

atomic_install_file "$staged_receipt" "$receipt" 0600 create
maybe_fault after_receipt

staged_pointer="$transaction/active-receipt.new"
"$PYTHON_BIN" - "$receipt" "$staged_pointer" <<'PY'
from pathlib import Path
import hashlib
import json
import sys

receipt = Path(sys.argv[1])
payload = json.dumps(
    {
        "receipt": receipt.name,
        "sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
    },
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
Path(sys.argv[2]).write_bytes(payload)
PY
atomic_install_file "$staged_pointer" "$ACTIVE_POINTER" 0600 replace
maybe_fault after_pointer

if [[ "$(config_state)" != "$config_before_state" ]]; then
  echo "V4_CODEX_CONFIG_MUTATED" >&2
  exit 1
fi
recover_install_transaction
journal_created=0
transaction=""
if ! "$PYTHON_BIN" "$MANAGEMENT_UNINSTALLER" \
  --codex-home "$CODEX_HOME_DIR" --check >/dev/null; then
  echo "V4_INSTALL_POSTCOMMIT_VALIDATION_FAILED" >&2
  exit 1
fi

if [[ -e "$LEGACY_TARGET" || -L "$LEGACY_TARGET" ]]; then
  legacy_message="An independent v3 installation was detected and left untouched."
else
  legacy_message="No v3 installation was changed or created."
fi
trap - EXIT
echo "Installed LoopSkill 4.1.1 to $TARGET_DIR"
echo "$legacy_message"
echo "Codex config.toml is byte-identical; no MCP entry was registered."
echo "LoopSkill 4 itself does not require a Codex App restart."
echo "Receipt: $receipt"
printf 'Uninstall: %q %q --codex-home %q\n' \
  "$PYTHON_BIN" "$MANAGEMENT_UNINSTALLER" "$CODEX_HOME_DIR"
