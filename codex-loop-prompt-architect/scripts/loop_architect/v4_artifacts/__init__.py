"""Fail-closed artifact capability libraries for LoopSkill 4."""

from .capture import (
    ArtifactBaseline,
    ArtifactCapture,
    NonGitBaseline,
    capture_artifact_transition,
    capture_existing_git,
    capture_existing_git_state,
    capture_non_git_baseline,
    capture_non_git_delta,
    detect_artifact_profile,
    initialize_new_git,
    load_artifact_baseline,
    persist_baseline_blobs,
    persist_capture_blobs,
    prepare_artifact_baseline,
    workspace_identity,
)
from .paths import ArtifactCaptureError
from .verifier import LocalVerification, verifier_capability, verify_artifact

__all__ = [
    "ArtifactBaseline",
    "ArtifactCapture",
    "ArtifactCaptureError",
    "NonGitBaseline",
    "LocalVerification",
    "capture_artifact_transition",
    "capture_existing_git",
    "capture_existing_git_state",
    "capture_non_git_baseline",
    "capture_non_git_delta",
    "detect_artifact_profile",
    "initialize_new_git",
    "load_artifact_baseline",
    "persist_baseline_blobs",
    "persist_capture_blobs",
    "prepare_artifact_baseline",
    "verifier_capability",
    "verify_artifact",
    "workspace_identity",
]
