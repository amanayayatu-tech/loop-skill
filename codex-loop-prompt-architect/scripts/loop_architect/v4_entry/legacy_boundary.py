"""Read-only v3 boundary detection; never a decoder or migration surface."""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path


V3_RELEASE_URL = (
    "https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8"
)
LEGACY_ERROR_CODE = "USER_UNSUPPORTED_LEGACY_VERSION"

_LEGACY_BASENAMES = {
    "LOOP_EVENTS.jsonl",
    "LOOP_REJECTIONS.jsonl",
    "LOOP_STATE.md",
}
_LEGACY_BYTE_MARKERS = (
    b"# Codex Loop Controller Pack",
    b"$codex-loop-prompt-architect",
    b"codex-loop-state",
)


def is_legacy_input(
    path: Path,
    payload: bytes | None = None,
    *,
    path_kind: str | None = None,
    directory_entries: Collection[str] = (),
) -> bool:
    """Recognize only stable public v3 markers without parsing legacy state."""

    if path.name in _LEGACY_BASENAMES or path.name == ".codex-loop":
        return True
    is_directory = path.is_dir() if path_kind is None else path_kind == "directory"
    if is_directory:
        if path_kind is None:
            marker_root = path / ".codex-loop"
            directory_entries = {
                name
                for name in (".codex-loop", *_LEGACY_BASENAMES)
                if (
                    marker_root.is_dir()
                    if name == ".codex-loop"
                    else (path / name).exists()
                )
            }
        if ".codex-loop" in directory_entries or any(
            name in directory_entries for name in _LEGACY_BASENAMES
        ):
            return True
    if payload is not None:
        prefix = payload[:32768]
        return any(marker in prefix for marker in _LEGACY_BYTE_MARKERS)
    return False


def unsupported_legacy_error() -> tuple[str, str, str]:
    return (
        LEGACY_ERROR_CODE,
        "LoopSkill 4 cannot open, import, repair, or run LoopSkill 3 data or Packs.",
        f"Use the independent LoopSkill v3.3.8 release for that data: {V3_RELEASE_URL}",
    )
