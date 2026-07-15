#!/usr/bin/env python3
"""Check every commit introduced by a GitHub event for whitespace errors."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


SHA_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
ZERO_SHA_RE = re.compile(r"^0{40}(?:0{24})?$")


class WhitespaceRangeError(RuntimeError):
    """Raised when the event cannot be mapped to a safe deterministic range."""


def _run_git(
    cwd: Path,
    argv: Sequence[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *argv],
        cwd=cwd,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _validate_sha(value: object, field: str, *, allow_zero: bool = False) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise WhitespaceRangeError(f"{field} must be a full hexadecimal Git object id")
    if ZERO_SHA_RE.fullmatch(value) and not allow_zero:
        raise WhitespaceRangeError(f"{field} must not be the all-zero object id")
    return value


def _commit_oid(cwd: Path, oid: str) -> str | None:
    result = _run_git(cwd, ["rev-parse", "--verify", f"{oid}^{{commit}}"], check=False)
    if result.returncode != 0:
        return None
    resolved = result.stdout.strip()
    return resolved if SHA_RE.fullmatch(resolved) else None


def _rev_list(cwd: Path, revision: str) -> list[str]:
    result = _run_git(cwd, ["rev-list", "--reverse", "--topo-order", revision])
    commits = [line for line in result.stdout.splitlines() if line]
    if any(not SHA_RE.fullmatch(commit) for commit in commits):
        raise WhitespaceRangeError("git rev-list returned a non-canonical object id")
    return commits


def _full_history(cwd: Path, head: str, reason: str) -> tuple[list[str], str]:
    commits = _rev_list(cwd, head)
    return commits, f"fallback-full-history:{reason}:{head}"


def _event_object(event: Mapping[str, Any], *path: str) -> object:
    current: object = event
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            raise WhitespaceRangeError(f"event payload is missing {'.'.join(path)}")
        current = current[key]
    return current


def select_commits(
    cwd: Path,
    event_name: str,
    event: Mapping[str, Any],
    github_sha: str,
) -> tuple[list[str], str]:
    """Return every commit whose patch must be checked and a public range label."""

    if event_name == "pull_request":
        base = _validate_sha(_event_object(event, "pull_request", "base", "sha"), "pull_request.base.sha")
        head = _validate_sha(_event_object(event, "pull_request", "head", "sha"), "pull_request.head.sha")
        head_commit = _commit_oid(cwd, head)
        if head_commit is None:
            raise WhitespaceRangeError(f"pull request head is unavailable: {head}")
        base_commit = _commit_oid(cwd, base)
        if base_commit is None:
            return _full_history(cwd, head_commit, "pull-request-base-unavailable")
        merge_base_result = _run_git(cwd, ["merge-base", base_commit, head_commit], check=False)
        merge_base = merge_base_result.stdout.strip()
        if merge_base_result.returncode != 0 or not SHA_RE.fullmatch(merge_base):
            return _full_history(cwd, head_commit, "pull-request-merge-base-unavailable")
        return _rev_list(cwd, f"{merge_base}..{head_commit}"), f"pull-request:{merge_base}..{head_commit}"

    if event_name == "push":
        before = _validate_sha(_event_object(event, "before"), "before", allow_zero=True)
        after = _validate_sha(_event_object(event, "after"), "after", allow_zero=True)
        ref = _event_object(event, "ref")
        valid_ref = (
            isinstance(ref, str)
            and ref.startswith(("refs/heads/", "refs/tags/"))
            and _run_git(cwd, ["check-ref-format", ref], check=False).returncode == 0
        )
        if not valid_ref:
            raise WhitespaceRangeError("push ref is not a safe heads/tags ref")
        if ZERO_SHA_RE.fullmatch(after):
            return [], f"push-deletion:{ref}:no-new-objects"
        after_commit = _commit_oid(cwd, after)
        if after_commit is None:
            raise WhitespaceRangeError(f"push after object is unavailable: {after}")
        if ref.startswith("refs/tags/"):
            return _full_history(cwd, after_commit, f"tag-push:{ref}")
        if ZERO_SHA_RE.fullmatch(before):
            return _full_history(cwd, after_commit, f"zero-before:{ref}")
        before_commit = _commit_oid(cwd, before)
        if before_commit is None:
            return _full_history(cwd, after_commit, f"push-before-unavailable:{ref}")
        return _rev_list(cwd, f"{before_commit}..{after_commit}"), f"push:{ref}:{before_commit}..{after_commit}"

    if event_name == "workflow_dispatch":
        head = _validate_sha(github_sha, "GITHUB_SHA")
        head_commit = _commit_oid(cwd, head)
        if head_commit is None:
            raise WhitespaceRangeError(f"workflow_dispatch head is unavailable: {head}")
        return _full_history(cwd, head_commit, "workflow-dispatch")

    raise WhitespaceRangeError(f"unsupported GitHub event: {event_name or '<empty>'}")


def check_commits(cwd: Path, commits: Sequence[str], label: str) -> None:
    print(f"WHITESPACE_RANGE label={label} commit_count={len(commits)}")
    for commit in commits:
        print(f"WHITESPACE_COMMIT {commit}")
        result = _run_git(
            cwd,
            ["diff-tree", "--check", "--root", "--no-renames", "--no-commit-id", "-r", commit],
            check=False,
        )
        if result.stdout:
            sys.stdout.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)
        if result.returncode != 0:
            raise WhitespaceRangeError(f"whitespace error in commit {commit}")


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    parser.add_argument("--event-path", type=Path, default=Path(os.environ.get("GITHUB_EVENT_PATH", "")))
    parser.add_argument("--github-sha", default=os.environ.get("GITHUB_SHA", ""))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if not args.event_path.is_file():
            raise WhitespaceRangeError(f"event payload is unavailable: {args.event_path}")
        event = json.loads(args.event_path.read_text(encoding="utf-8"))
        if not isinstance(event, dict):
            raise WhitespaceRangeError("event payload must be a JSON object")
        commits, label = select_commits(args.repo.resolve(), args.event_name, event, args.github_sha)
        check_commits(args.repo.resolve(), commits, label)
    except (OSError, json.JSONDecodeError, subprocess.SubprocessError, WhitespaceRangeError) as exc:
        print(f"WHITESPACE_RANGE_FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
