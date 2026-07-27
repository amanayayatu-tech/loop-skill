"""Git, non-Git, and new-Git artifact capability profiles."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from loop_architect.v4_alpha.protocol import (
    canonical_bytes,
    domain_digest,
    parse_json_bytes,
    raw_domain_digest,
)

from .paths import (
    MAX_CAPTURE_BYTES,
    ArtifactCaptureError,
    enumerate_regular_files,
    normalize_relative_path,
    reject_casefold_collisions,
    secure_read_regular,
)


GIT_TIMEOUT_SECONDS = 60
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


@dataclass(frozen=True)
class NonGitBaseline:
    root_digest: str
    entries: tuple[Mapping[str, Any], ...]
    blobs: Mapping[str, bytes]


@dataclass(frozen=True)
class ArtifactCapture:
    profile: str
    base_identity: str
    manifest: tuple[Mapping[str, Any], ...]
    manifest_digest: str
    artifact_digest: str
    bundle_blob_digest: str
    blobs: Mapping[str, bytes]
    empty: bool


@dataclass(frozen=True)
class ArtifactBaseline:
    """Immutable pre-effect artifact identity stored by digest in the canonical store."""

    profile: str
    workspace_identity_digest: str
    base_identity: str
    entries: tuple[Mapping[str, Any], ...]
    capture_digest: str
    descriptor_blob: bytes
    blobs: Mapping[str, bytes]


@dataclass(frozen=True)
class NewGitInitialization:
    baseline_digest: str
    base_commit: str
    branch: str


def _blob_digest(content: bytes) -> str:
    return raw_domain_digest("loopskill-blob-v1\n", content)


def workspace_identity(root: Path | str, profile: str) -> str:
    root_path = Path(root)
    if root_path.is_symlink() or not root_path.is_dir():
        raise ArtifactCaptureError("PATH_CONFINEMENT_VIOLATION", "invalid workspace root")
    try:
        resolved = root_path.resolve(strict=True)
    except OSError as exc:
        raise ArtifactCaptureError(
            "PATH_CONFINEMENT_VIOLATION", "workspace root cannot be resolved"
        ) from exc
    return domain_digest(
        "loopskill-workspace-identity-v1\n",
        {"profile": profile, "resolved_root": str(resolved)},
    )


def detect_artifact_profile(root: Path | str) -> str:
    """Select a read-only default profile; new-Git always needs explicit authority."""
    root_path = Path(root)
    if root_path.is_symlink() or not root_path.is_dir():
        raise ArtifactCaptureError("PATH_CONFINEMENT_VIOLATION", "invalid workspace root")
    try:
        inside = _git(
            root_path,
            ["rev-parse", "--is-inside-work-tree"],
            accepted=frozenset({0, 128}),
        ).strip()
    except ArtifactCaptureError:
        inside = b""
    return "existing_git" if inside == b"true" else "non_git"


def _finalize_capture(
    *,
    profile: str,
    base_identity: str,
    manifest: tuple[Mapping[str, Any], ...],
    blobs: Mapping[str, bytes],
    identity: Mapping[str, Any],
) -> ArtifactCapture:
    bundle_bytes = canonical_bytes(identity)
    bundle_blob_digest = _blob_digest(bundle_bytes)
    complete_blobs = dict(blobs)
    complete_blobs[bundle_blob_digest] = bundle_bytes
    return ArtifactCapture(
        profile=profile,
        base_identity=base_identity,
        manifest=manifest,
        manifest_digest=domain_digest(
            "loopskill-artifact-manifest-v1\n", manifest
        ),
        artifact_digest=domain_digest("loopskill-artifact-bundle-v1\n", identity),
        bundle_blob_digest=bundle_blob_digest,
        blobs=complete_blobs,
        empty=not manifest,
    )


def _git_environment() -> dict[str, str]:
    return {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }


def _git(
    root: Path,
    arguments: list[str],
    *,
    input_bytes: bytes | None = None,
    accepted: frozenset[int] = frozenset({0}),
    extra_environment: Mapping[str, str] | None = None,
) -> bytes:
    environment = _git_environment()
    if extra_environment:
        environment.update(extra_environment)
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ArtifactCaptureError("ARTIFACT_IDENTITY_MISMATCH", "Git invocation failed") from exc
    if completed.returncode not in accepted:
        stderr_digest = _blob_digest(completed.stderr)
        raise ArtifactCaptureError(
            "ARTIFACT_IDENTITY_MISMATCH",
            f"Git rejected operation; stderr_digest={stderr_digest}",
        )
    return completed.stdout


def _capture_files(root: Path, paths: tuple[str, ...]) -> tuple[dict[str, bytes], dict[str, dict[str, Any]]]:
    blobs: dict[str, bytes] = {}
    identities: dict[str, dict[str, Any]] = {}
    total = 0
    for path in paths:
        content = secure_read_regular(root, path)
        total += len(content)
        if total > MAX_CAPTURE_BYTES:
            raise ArtifactCaptureError(
                "ARTIFACT_IDENTITY_MISMATCH", "capture byte bound exceeded"
            )
        digest = _blob_digest(content)
        blobs[digest] = content
        identities[path] = {
            "blob_digest": digest,
            "bytes": len(content),
        }
    return blobs, identities


def capture_non_git_baseline(root: Path | str) -> NonGitBaseline:
    root_path = Path(root)
    paths = enumerate_regular_files(root_path)
    blobs, identities = _capture_files(root_path, paths)
    entries = tuple(
        {
            "blob_digest": identities[path]["blob_digest"],
            "bytes": identities[path]["bytes"],
            "path": path,
        }
        for path in paths
    )
    return NonGitBaseline(
        root_digest=domain_digest("loopskill-non-git-baseline-v1\n", entries),
        entries=entries,
        blobs=blobs,
    )


def capture_non_git_delta(
    root: Path | str, baseline: NonGitBaseline
) -> ArtifactCapture:
    root_path = Path(root)
    current = capture_non_git_baseline(root_path)
    before = {str(entry["path"]): entry for entry in baseline.entries}
    after = {str(entry["path"]): entry for entry in current.entries}
    paths = reject_casefold_collisions(set(before) | set(after))
    manifest = []
    blobs = {}
    for path in paths:
        old = before.get(path)
        new = after.get(path)
        if old is None:
            status = "A"
        elif new is None:
            status = "D"
        elif old["blob_digest"] != new["blob_digest"]:
            status = "M"
        else:
            continue
        manifest.append(
            {
                "after_digest": None if new is None else new["blob_digest"],
                "before_digest": None if old is None else old["blob_digest"],
                "path": path,
                "status": status,
            }
        )
        if new is not None:
            blobs[str(new["blob_digest"])] = current.blobs[str(new["blob_digest"])]
    manifest_tuple = tuple(manifest)
    identity = {
        "after_root_digest": current.root_digest,
        "before_root_digest": baseline.root_digest,
        "manifest": manifest_tuple,
        "profile": "non_git",
    }
    return _finalize_capture(
        profile="non_git",
        base_identity=baseline.root_digest,
        manifest=manifest_tuple,
        blobs=blobs,
        identity=identity,
    )


def _git_changed_entries(root: Path, base_commit: str) -> tuple[dict[str, str], bytes]:
    product_pathspec = [".", ":(exclude).codex-loop/**"]
    names = _git(
        root,
        [
            "diff",
            "--no-renames",
            "--name-status",
            "-z",
            base_commit,
            "--",
            *product_pathspec,
        ],
    )
    tokens = [token.decode("utf-8", "strict") for token in names.split(b"\0") if token]
    if len(tokens) % 2:
        raise ArtifactCaptureError("ARTIFACT_IDENTITY_MISMATCH", "invalid Git name-status")
    entries = {}
    for index in range(0, len(tokens), 2):
        status, path = tokens[index], normalize_relative_path(tokens[index + 1])
        if status not in {"A", "M", "D", "T", "U"}:
            raise ArtifactCaptureError(
                "ARTIFACT_IDENTITY_MISMATCH", f"unsupported Git status: {status}"
            )
        entries[path] = status
    patch = _git(
        root,
        ["diff", "--binary", "--no-ext-diff", base_commit, "--", *product_pathspec],
    )
    return entries, patch


def _git_untracked(root: Path) -> tuple[str, ...]:
    raw = _git(
        root,
        [
            "ls-files",
            "-z",
            "--others",
            "--exclude-standard",
            "--",
            ".",
            ":(exclude).codex-loop/**",
        ],
    )
    paths = tuple(token.decode("utf-8", "strict") for token in raw.split(b"\0") if token)
    return reject_casefold_collisions(paths)


def capture_existing_git(
    root: Path | str,
    *,
    base_ref: str,
    allowed_untracked_paths: tuple[str, ...],
) -> ArtifactCapture:
    root_path = Path(root)
    if root_path.is_symlink() or not root_path.is_dir():
        raise ArtifactCaptureError("PATH_CONFINEMENT_VIOLATION", "invalid Git root")
    if "\x00" in base_ref or not base_ref:
        raise ArtifactCaptureError("ARTIFACT_IDENTITY_MISMATCH", "invalid base ref")
    if _git(root_path, ["rev-parse", "--is-inside-work-tree"]).strip() != b"true":
        raise ArtifactCaptureError("ARTIFACT_IDENTITY_MISMATCH", "Git worktree required")
    base_commit = _git(
        root_path, ["rev-parse", "--verify", f"{base_ref}^{{commit}}"]
    ).decode("ascii", "strict").strip()
    allowed = reject_casefold_collisions(allowed_untracked_paths)
    observed_untracked = _git_untracked(root_path)
    if observed_untracked != allowed:
        raise ArtifactCaptureError(
            "ARTIFACT_IDENTITY_MISMATCH", "untracked boundary mismatch"
        )
    tracked, patch = _git_changed_entries(root_path, base_commit)
    all_paths = reject_casefold_collisions((*tracked, *observed_untracked))
    existing_paths = tuple(
        path for path in all_paths if tracked.get(path) != "D"
    )
    blobs, identities = _capture_files(root_path, existing_paths)
    untracked_second = _git_untracked(root_path)
    tracked_second, patch_second = _git_changed_entries(root_path, base_commit)
    if (
        observed_untracked != untracked_second
        or tracked != tracked_second
        or patch != patch_second
    ):
        raise ArtifactCaptureError("ARTIFACT_STALE", "Git boundary changed during capture")
    second_blobs, second_identities = _capture_files(root_path, existing_paths)
    if identities != second_identities or blobs != second_blobs:
        raise ArtifactCaptureError("ARTIFACT_STALE", "file changed during capture")
    if patch:
        _git(
            root_path,
            ["apply", "--check", "--reverse", "--binary", "-"],
            input_bytes=patch,
        )
        patch_digest = _blob_digest(patch)
        blobs[patch_digest] = patch
    else:
        patch_digest = _blob_digest(b"")
    manifest = []
    for path in all_paths:
        status = "A" if path in observed_untracked else tracked[path]
        identity = identities.get(path)
        manifest.append(
            {
                "blob_digest": None if identity is None else identity["blob_digest"],
                "bytes": None if identity is None else identity["bytes"],
                "path": path,
                "status": status,
            }
        )
    manifest_tuple = tuple(manifest)
    identity = {
        "base_commit": base_commit,
        "manifest": manifest_tuple,
        "profile": "existing_git",
        "tracked_patch_digest": patch_digest,
    }
    return _finalize_capture(
        profile="existing_git",
        base_identity=base_commit,
        manifest=manifest_tuple,
        blobs=blobs,
        identity=identity,
    )


def capture_existing_git_state(
    root: Path | str, *, base_ref: str = "HEAD"
) -> ArtifactCapture:
    """Capture one exact Git state while machine-owning the untracked boundary."""
    root_path = Path(root)
    return capture_existing_git(
        root_path,
        base_ref=base_ref,
        allowed_untracked_paths=_git_untracked(root_path),
    )


def _transition_capture(
    before: ArtifactCapture, after: ArtifactCapture
) -> ArtifactCapture:
    if before.profile != "existing_git" or after.profile != "existing_git":
        raise ArtifactCaptureError(
            "ARTIFACT_IDENTITY_MISMATCH", "Git transition profile mismatch"
        )
    if before.base_identity != after.base_identity:
        raise ArtifactCaptureError(
            "ARTIFACT_IDENTITY_MISMATCH", "Git transition base changed"
        )
    before_entries = {str(item["path"]): item for item in before.manifest}
    after_entries = {str(item["path"]): item for item in after.manifest}
    manifest = []
    for path in reject_casefold_collisions(set(before_entries) | set(after_entries)):
        old = before_entries.get(path)
        new = after_entries.get(path)
        if old == new:
            continue
        manifest.append(
            {
                "after_digest": None if new is None else new.get("blob_digest"),
                "before_digest": None if old is None else old.get("blob_digest"),
                "path": path,
                "status": "A" if old is None else "D" if new is None else "M",
            }
        )
    manifest_tuple = tuple(manifest)
    identity = {
        "after_capture_digest": after.artifact_digest,
        "base_commit": before.base_identity,
        "before_capture_digest": before.artifact_digest,
        "manifest": manifest_tuple,
        "profile": "existing_git",
    }
    return _finalize_capture(
        profile="existing_git",
        base_identity=before.artifact_digest,
        manifest=manifest_tuple,
        blobs=after.blobs,
        identity=identity,
    )


def prepare_artifact_baseline(
    root: Path | str,
    *,
    expected_profile: str,
    expected_workspace_identity_digest: str,
) -> ArtifactBaseline:
    """Capture the pre-provider state without mutating the workspace."""
    root_path = Path(root)
    observed_profile = detect_artifact_profile(root_path)
    observed_workspace = workspace_identity(root_path, observed_profile)
    if (
        observed_profile != expected_profile
        or observed_workspace != expected_workspace_identity_digest
    ):
        raise ArtifactCaptureError(
            "ARTIFACT_IDENTITY_MISMATCH", "prepared workspace binding changed"
        )
    blobs: dict[str, bytes]
    if observed_profile == "existing_git":
        capture = capture_existing_git_state(root_path)
        base_identity = capture.base_identity
        entries = capture.manifest
        capture_digest = capture.artifact_digest
        blobs = dict(capture.blobs)
    elif observed_profile == "non_git":
        baseline = capture_non_git_baseline(root_path)
        base_identity = baseline.root_digest
        entries = baseline.entries
        capture_digest = baseline.root_digest
        blobs = dict(baseline.blobs)
    else:
        raise ArtifactCaptureError(
            "CAPABILITY_UNAVAILABLE", "explicit new-Git baseline is required"
        )
    descriptor = canonical_bytes(
        {
            "base_identity": base_identity,
            "capture_digest": capture_digest,
            "entries": list(entries),
            "profile": observed_profile,
            "workspace_identity_digest": observed_workspace,
        }
    )
    blobs[_blob_digest(descriptor)] = descriptor
    return ArtifactBaseline(
        profile=observed_profile,
        workspace_identity_digest=observed_workspace,
        base_identity=base_identity,
        entries=entries,
        capture_digest=capture_digest,
        descriptor_blob=descriptor,
        blobs=blobs,
    )


def load_artifact_baseline(raw: bytes) -> ArtifactBaseline:
    value = parse_json_bytes(raw)
    if not isinstance(value, Mapping) or set(value) != {
        "base_identity",
        "capture_digest",
        "entries",
        "profile",
        "workspace_identity_digest",
    }:
        raise ArtifactCaptureError(
            "ARTIFACT_IDENTITY_MISMATCH", "invalid baseline descriptor"
        )
    if value["profile"] not in {"existing_git", "non_git"}:
        raise ArtifactCaptureError(
            "ARTIFACT_IDENTITY_MISMATCH", "unsupported baseline profile"
        )
    entries = value["entries"]
    if not isinstance(entries, list) or not all(isinstance(item, Mapping) for item in entries):
        raise ArtifactCaptureError(
            "ARTIFACT_IDENTITY_MISMATCH", "invalid baseline entries"
        )
    return ArtifactBaseline(
        profile=str(value["profile"]),
        workspace_identity_digest=str(value["workspace_identity_digest"]),
        base_identity=str(value["base_identity"]),
        entries=tuple(entries),
        capture_digest=str(value["capture_digest"]),
        descriptor_blob=raw,
        blobs={},
    )


def capture_artifact_transition(
    root: Path | str, baseline: ArtifactBaseline
) -> ArtifactCapture:
    observed_workspace = workspace_identity(root, baseline.profile)
    if observed_workspace != baseline.workspace_identity_digest:
        raise ArtifactCaptureError(
            "ARTIFACT_IDENTITY_MISMATCH", "workspace identity changed"
        )
    if baseline.profile == "non_git":
        return capture_non_git_delta(
            root,
            NonGitBaseline(
                root_digest=baseline.base_identity,
                entries=baseline.entries,
                blobs={},
            ),
        )
    before = ArtifactCapture(
        profile="existing_git",
        base_identity=baseline.base_identity,
        manifest=baseline.entries,
        manifest_digest=domain_digest(
            "loopskill-artifact-manifest-v1\n", baseline.entries
        ),
        artifact_digest=baseline.capture_digest,
        bundle_blob_digest="",
        blobs={},
        empty=not baseline.entries,
    )
    after = capture_existing_git_state(root, base_ref=baseline.base_identity)
    return _transition_capture(before, after)


def persist_baseline_blobs(store: Any, baseline: ArtifactBaseline) -> str:
    for digest, content in sorted(baseline.blobs.items()):
        if store.put_blob(content) != digest:
            raise ArtifactCaptureError(
                "ARTIFACT_IDENTITY_MISMATCH", "baseline blob identity changed"
            )
    descriptor_digest = _blob_digest(baseline.descriptor_blob)
    if store.get_blob(descriptor_digest) != baseline.descriptor_blob:
        raise ArtifactCaptureError(
            "ARTIFACT_IDENTITY_MISMATCH", "baseline descriptor was not persisted"
        )
    return descriptor_digest


def initialize_new_git(
    root: Path | str,
    *,
    allow_init: bool,
    allow_branch_create: bool,
    branch: str = "loopskill-v4",
) -> NewGitInitialization:
    root_path = Path(root)
    if not allow_init or not allow_branch_create:
        raise ArtifactCaptureError(
            "CAPABILITY_UNAVAILABLE", "new_git requires explicit init and branch grants"
        )
    if not BRANCH_RE.fullmatch(branch) or ".." in branch or "//" in branch:
        raise ArtifactCaptureError("ARTIFACT_IDENTITY_MISMATCH", "invalid branch")
    if (root_path / ".git").exists():
        raise ArtifactCaptureError("ARTIFACT_IDENTITY_MISMATCH", "Git already initialized")
    baseline = capture_non_git_baseline(root_path)
    _git(root_path, ["init", "-q", "-b", branch])
    _git(root_path, ["add", "--all"])
    fixed = {
        "GIT_AUTHOR_DATE": "2026-07-27T00:00:00Z",
        "GIT_AUTHOR_EMAIL": "loopskill-v4@example.invalid",
        "GIT_AUTHOR_NAME": "LoopSkill v4",
        "GIT_COMMITTER_DATE": "2026-07-27T00:00:00Z",
        "GIT_COMMITTER_EMAIL": "loopskill-v4@example.invalid",
        "GIT_COMMITTER_NAME": "LoopSkill v4",
    }
    _git(root_path, ["commit", "-q", "--no-gpg-sign", "-m", "v4 baseline"], extra_environment=fixed)
    base_commit = _git(root_path, ["rev-parse", "--verify", "HEAD^{commit}"]).decode().strip()
    return NewGitInitialization(
        baseline_digest=baseline.root_digest,
        base_commit=base_commit,
        branch=branch,
    )


def persist_capture_blobs(store: Any, capture: ArtifactCapture) -> tuple[str, ...]:
    persisted = []
    for digest, content in sorted(capture.blobs.items()):
        actual = store.put_blob(content)
        if actual != digest:
            raise ArtifactCaptureError(
                "ARTIFACT_IDENTITY_MISMATCH", "blob store changed content identity"
            )
        persisted.append(actual)
    return tuple(persisted)
