#!/usr/bin/env python3
"""Fail-closed parity and stale-product checks for the public v4 READMEs."""

from __future__ import annotations

import argparse
import collections
import re
import subprocess
import sys
from pathlib import Path


EXPECTED_SECTIONS = (
    "identity",
    "break",
    "changes",
    "install",
    "usage",
    "no-control",
    "status",
    "policy",
    "architecture",
    "safety",
    "evidence",
    "v3",
    "uninstall",
    "limitations",
    "contributor",
    "release",
)
STALE_CURRENT_PRODUCT = (
    "scripts/loopctl",
    "$codex-loop-prompt-architect",
    "MCP_CANONICAL_WRITER",
    "READY_WITH_ASSUMPTIONS",
    ".codex-loop/LOOP_STATE",
    "Use $codex-loop-prompt-architect",
    "schema-v3 canonical",
)
COMMON_CLAIMS = (
    "4.0.0",
    "INTAKE",
    "PREPARE",
    "CONFIRM",
    "START",
    "USER_UNSUPPORTED_LEGACY_VERSION",
    "UNKNOWN",
    "UNVERIFIABLE",
    "https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8",
    "python3 scripts/generate_v4_protocol.py --check",
    "python3 scripts/check_v4_docs.py",
)
LOCAL_LINK_EXCLUSIONS = {"README.md", "README.en.md"}


class DocsError(ValueError):
    pass


def _markers(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"^<!-- parity: ([a-z0-9-]+) -->$", text, re.MULTILINE))


def _blocks(text: str, language: str) -> tuple[str, ...]:
    return tuple(
        match.strip() for match in re.findall(
            rf"```{re.escape(language)}\n(.*?)\n```", text, re.DOTALL
        )
    )


def _links(text: str) -> collections.Counter[str]:
    values = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
    return collections.Counter(value for value in values if value not in LOCAL_LINK_EXCLUSIONS)


def _check_local_links(root: Path, text: str, name: str) -> None:
    for target in _links(text):
        if target.startswith(("https://", "http://", "#")):
            continue
        path_text = target.split("#", 1)[0]
        if not path_text or Path(path_text).is_absolute() or ".." in Path(path_text).parts:
            raise DocsError(f"DOC_LINK_UNSAFE:{name}:{target}")
        if not (root / path_text).exists():
            raise DocsError(f"DOC_LINK_MISSING:{name}:{target}")


def _check_bash(blocks: tuple[str, ...], name: str) -> None:
    for index, block in enumerate(blocks, 1):
        result = subprocess.run(
            ["bash", "-n"],
            input=block.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode:
            raise DocsError(f"DOC_COMMAND_SYNTAX:{name}:{index}")


def validate(root: Path, *, release: bool = False) -> dict[str, object]:
    root = root.resolve()
    zh = (root / "README.md").read_text(encoding="utf-8")
    en = (root / "README.en.md").read_text(encoding="utf-8")
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if version != "4.0.0":
        raise DocsError("DOC_VERSION_DRIFT")
    if _markers(zh) != EXPECTED_SECTIONS or _markers(en) != EXPECTED_SECTIONS:
        raise DocsError("DOC_SECTION_PARITY_DRIFT")
    zh_bash = _blocks(zh, "bash")
    en_bash = _blocks(en, "bash")
    if zh_bash != en_bash:
        raise DocsError("DOC_COMMAND_PARITY_DRIFT")
    _check_bash(zh_bash, "README")
    if _links(zh) != _links(en):
        raise DocsError("DOC_LINK_PARITY_DRIFT")
    _check_local_links(root, zh, "README")
    _check_local_links(root, en, "README.en")
    for claim in COMMON_CLAIMS:
        if claim not in zh or claim not in en:
            raise DocsError(f"DOC_CLAIM_PARITY_DRIFT:{claim}")
    if "不注册 MCP" not in zh or "does not register MCP" not in en:
        raise DocsError("DOC_MCP_CLAIM_DRIFT")
    if "不要求为安装或使用 LoopSkill 4 重启" not in zh:
        raise DocsError("DOC_RESTART_CLAIM_DRIFT:zh")
    if "or require a Codex App restart" not in en:
        raise DocsError("DOC_RESTART_CLAIM_DRIFT:en")
    for literal in STALE_CURRENT_PRODUCT:
        if literal in zh or literal in en:
            raise DocsError(f"DOC_STALE_V3_CURRENT_PRODUCT:{literal}")
    candidate_zh = "4.0.0 候选正在接受发行门禁" in zh
    candidate_en = "4.0.0 candidate is passing release gates" in en
    stable_zh = "4.0.0 稳定版" in zh
    stable_en = "4.0.0 stable release" in en
    if candidate_zh != candidate_en or stable_zh != stable_en:
        raise DocsError("DOC_RELEASE_STATUS_PARITY_DRIFT")
    if release:
        if not stable_zh or candidate_zh:
            raise DocsError("DOC_RELEASE_STATUS_NOT_STABLE")
    elif not ((candidate_zh and not stable_zh) or (stable_zh and not candidate_zh)):
        raise DocsError("DOC_RELEASE_STATUS_AMBIGUOUS")
    return {
        "bash_command_blocks": len(zh_bash),
        "link_targets": sum(_links(zh).values()),
        "release_mode": release,
        "section_count": len(EXPECTED_SECTIONS),
        "status": "PASS",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = validate(args.root, release=args.release)
    except (OSError, UnicodeDecodeError, DocsError) as exc:
        print(f"V4_DOCS_FAIL:{exc}", file=sys.stderr)
        return 1
    print(
        "V4_DOCS_PASS "
        + " ".join(f"{key}={value}" for key, value in sorted(result.items()))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
