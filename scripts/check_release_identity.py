#!/usr/bin/env python3
"""Fail closed unless a version tag names the exact protected-main commit."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Sequence


SHA_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
TAG_RE = re.compile(r"^v([0-9]+\.[0-9]+\.[0-9]+)$")


class ReleaseIdentityError(ValueError):
    pass


def _git(repo: Path, *argv: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *argv],
        cwd=repo,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _commit(repo: Path, revision: str) -> str:
    result = _git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}", check=False)
    value = result.stdout.strip()
    if result.returncode != 0 or not SHA_RE.fullmatch(value):
        raise ReleaseIdentityError(f"RELEASE_OBJECT_UNAVAILABLE: {revision}")
    return value


def check_release_identity(repo: Path, expected_sha: str, tag: str, main_ref: str) -> dict[str, str]:
    if not SHA_RE.fullmatch(expected_sha):
        raise ReleaseIdentityError("RELEASE_EXPECTED_SHA_INVALID")
    tag_match = TAG_RE.fullmatch(tag)
    if tag_match is None:
        raise ReleaseIdentityError("RELEASE_TAG_INVALID")
    if not re.fullmatch(r"refs/remotes/[A-Za-z0-9._/-]+", main_ref) or ".." in main_ref:
        raise ReleaseIdentityError("RELEASE_MAIN_REF_INVALID")
    expected_commit = _commit(repo, expected_sha)
    tag_commit = _commit(repo, f"refs/tags/{tag}")
    main_commit = _commit(repo, main_ref)
    if expected_commit != tag_commit:
        raise ReleaseIdentityError("RELEASE_TAG_COMMIT_MISMATCH")
    ancestor = _git(repo, "merge-base", "--is-ancestor", expected_commit, main_commit, check=False)
    if ancestor.returncode != 0:
        raise ReleaseIdentityError("RELEASE_COMMIT_NOT_ON_PROTECTED_MAIN")
    version = (repo / "VERSION").read_text(encoding="utf-8").strip()
    if version != tag_match.group(1):
        raise ReleaseIdentityError("RELEASE_VERSION_TAG_MISMATCH")
    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## [{version}]" not in changelog or f"/releases/tag/{tag}" not in changelog:
        raise ReleaseIdentityError("RELEASE_CHANGELOG_IDENTITY_MISSING")
    return {
        "tag": tag,
        "commit": expected_commit,
        "protected_main_commit": main_commit,
        "version": version,
    }


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--main-ref", default="refs/remotes/origin/main")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = check_release_identity(args.repo.resolve(), args.expected_sha, args.tag, args.main_ref)
    except (OSError, subprocess.SubprocessError, ReleaseIdentityError) as exc:
        print(f"RELEASE_IDENTITY_FAILED: {exc}", file=sys.stderr)
        return 1
    print("RELEASE_IDENTITY " + " ".join(f"{key}={value}" for key, value in sorted(result.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
