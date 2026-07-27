"""Fail-closed artifact capability libraries for LoopSkill 4."""

from .capture import (
    ArtifactCapture,
    NonGitBaseline,
    capture_existing_git,
    capture_non_git_baseline,
    capture_non_git_delta,
    initialize_new_git,
    persist_capture_blobs,
)
from .paths import ArtifactCaptureError

__all__ = [
    "ArtifactCapture",
    "ArtifactCaptureError",
    "NonGitBaseline",
    "capture_existing_git",
    "capture_non_git_baseline",
    "capture_non_git_delta",
    "initialize_new_git",
    "persist_capture_blobs",
]
