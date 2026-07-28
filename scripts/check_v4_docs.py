#!/usr/bin/env python3
"""Fail-closed parity and stale-product checks for public v4 documentation."""

from __future__ import annotations

import argparse
import collections
import os
import re
import subprocess
import sys
import tempfile
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
    "scripts/generate_v4_protocol.py --check",
    "scripts/check_v4_docs.py",
)
LOCAL_LINK_EXCLUSIONS = {"README.md", "README.en.md"}
README_CANDIDATE_ZH = "4.0.0 候选正在接受发行门禁；尚未发布"
README_CANDIDATE_EN = "4.0.0 candidate is undergoing release validation and is not yet published"
README_STABLE_ZH = "此源码树是 LoopSkill 4.0.0 稳定发行"
README_STABLE_EN = "This source tree is the LoopSkill 4.0.0 stable release"
QUICKSTART_CANDIDATE_ZH = "LoopSkill 4.0.0 候选正在接受发行门禁，尚未发布"
QUICKSTART_CANDIDATE_EN = "LoopSkill 4.0.0 candidate is undergoing release validation and is not yet"
QUICKSTART_STABLE_ZH = "此源码树是 LoopSkill 4.0.0 稳定发行"
QUICKSTART_STABLE_EN = "This source tree is the LoopSkill 4.0.0 stable release"


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


def _check_local_links(root: Path, text: str, name: str, base: Path | None = None) -> None:
    base = root if base is None else base
    for target in _links(text):
        if target.startswith(("https://", "http://", "#")):
            continue
        path_text = target.split("#", 1)[0]
        if not path_text or Path(path_text).is_absolute():
            raise DocsError(f"DOC_LINK_UNSAFE:{name}:{target}")
        try:
            resolved = (base / path_text).resolve()
            resolved.relative_to(root)
        except ValueError as exc:
            raise DocsError(f"DOC_LINK_UNSAFE:{name}:{target}") from exc
        if not resolved.exists():
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


def smoke_public_commands(root: Path) -> dict[str, object]:
    """Execute the side-effect-free public command boundary in a temp root."""

    root = root.resolve()
    entry = root / "codex-loop-prompt-architect/scripts/loopskill4"
    example = root / "examples/v4-standard-input.json"
    if not entry.is_file() or entry.is_symlink() or not example.is_file():
        raise DocsError("DOC_COMMAND_SMOKE_SOURCE_MISSING")
    with tempfile.TemporaryDirectory() as temporary:
        sandbox = Path(temporary)
        prepared = sandbox / "prepared"
        one_entry_prepared = sandbox / "one-entry-prepared"
        data = sandbox / "data"
        environment = {
            **os.environ,
            "CODEX_HOME": str(sandbox / "codex-home"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }

        def run(*arguments: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(entry), *arguments],
                cwd=sandbox,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

        help_result = run("--help")
        intake = run("intake", str(example))
        prepare = run("prepare", str(example), "--output", str(prepared))
        compile_result = run("compile", str(prepared))
        start_boundary = run(
            "start",
            str(example),
            "--root",
            str(data),
            "--prepared-output",
            str(one_entry_prepared),
        )
        expected_prepared = {
            "CONTROLLER_PLAN.md",
            "boundary-summary.json",
            "loop-manifest.json",
            "prepared-bundle.json",
            "使用说明.md",
        }
        if (
            help_result.returncode != 0
            or "intake" not in help_result.stdout
            or "start" not in help_result.stdout
            or intake.returncode != 0
            or "READY_FOR_LOOP" not in intake.stdout
            or prepare.returncode != 0
            or {path.name for path in prepared.iterdir()} != expected_prepared
            or compile_result.returncode != 0
            or '"status":"PREPARED_VALID"' not in compile_result.stdout
            or start_boundary.returncode != 2
            or "USER_CONFIRMATION_REQUIRED" not in start_boundary.stderr
            or data.exists()
            or {path.name for path in one_entry_prepared.iterdir()} != expected_prepared
        ):
            raise DocsError("DOC_COMMAND_SMOKE_FAILED")
    return {
        "command_count": 5,
        "external_effect_count": 0,
        "status": "PASS",
    }


def validate(root: Path, *, mode: str = "auto") -> dict[str, object]:
    if mode not in {"auto", "candidate", "release"}:
        raise DocsError("DOC_RELEASE_MODE_INVALID")
    root = root.resolve()
    zh = (root / "README.md").read_text(encoding="utf-8")
    en = (root / "README.en.md").read_text(encoding="utf-8")
    quickstart_zh = (root / "docs/v4/quickstart.zh-CN.md").read_text(encoding="utf-8")
    quickstart_en = (root / "docs/v4/quickstart.en.md").read_text(encoding="utf-8")
    releasing = (root / "docs/RELEASING.md").read_text(encoding="utf-8")
    security = (root / "SECURITY.md").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
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
    quickstart_zh_bash = _blocks(quickstart_zh, "bash")
    quickstart_en_bash = _blocks(quickstart_en, "bash")
    if quickstart_zh_bash != quickstart_en_bash:
        raise DocsError("DOC_QUICKSTART_COMMAND_PARITY_DRIFT")
    _check_bash(quickstart_zh_bash, "quickstart")
    if _links(quickstart_zh) != _links(quickstart_en):
        raise DocsError("DOC_QUICKSTART_LINK_PARITY_DRIFT")
    quickstart_base = root / "docs/v4"
    _check_local_links(root, quickstart_zh, "quickstart.zh-CN", quickstart_base)
    _check_local_links(root, quickstart_en, "quickstart.en", quickstart_base)
    releasing_bash = _blocks(releasing, "bash")
    _check_bash(releasing_bash, "RELEASING")
    for literal in (
        "requirements-test.txt",
        "coverage report --fail-under=80",
        "loopskill4 canary",
        "scripts/build_v4_author_packet.py",
        "--canary-store",
        "349 semantic mappings to 74",
        "canary-environment-integrity.json",
        "Host config/auth",
    ):
        if literal not in releasing:
            raise DocsError(f"DOC_RELEASE_RUNBOOK_INCOMPLETE:{literal}")
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
        if literal in zh or literal in en or literal in quickstart_zh or literal in quickstart_en:
            raise DocsError(f"DOC_STALE_V3_CURRENT_PRODUCT:{literal}")
    public_entry_docs = (zh, en, quickstart_zh, quickstart_en)
    if any("<receipt>" in text or " --receipt " in text for text in public_entry_docs):
        raise DocsError("DOC_MANUAL_RECEIPT_TRANSPORT")
    if (
        "codex login status 2>&1 | grep -F 'Logged in'" not in releasing
        or "codex login status | grep -F 'Logged in'" in releasing
    ):
        raise DocsError("DOC_CANARY_LOGIN_STREAM_DRIFT")
    if (
        "唯一首次 invocation" not in zh
        or "第二次 spawn" not in zh
        or "one first invocation" not in en
        or "second spawn" not in en
    ):
        raise DocsError("DOC_REFRESH_ATTEMPT_SEMANTICS_DRIFT")
    ux_contract = (root / "docs/architecture/loopskill-v4-single-entry-ux.md").read_text(
        encoding="utf-8"
    )
    for literal in (
        "durable Attempt has not been claimed",
        "unique first foreground",
        "no cross-process Host",
        "never performs\na second spawn",
    ):
        if literal not in ux_contract:
            raise DocsError(f"DOC_REFRESH_ATTEMPT_SEMANTICS_DRIFT:{literal}")
    retired_canary_literals = (
        "loopskill-v4-disposable-app-canary-v1",
        "codex-app-task-readback-v1",
        "host-tool-observed",
    )
    current_canary_sources = (
        releasing,
        ux_contract,
        (root / "codex-loop-prompt-architect/scripts/loop_architect/v4_entry/canary.py").read_text(
            encoding="utf-8"
        ),
        (root / "scripts/validate_v4_rc.py").read_text(encoding="utf-8"),
    )
    for literal in retired_canary_literals:
        if any(literal in text for text in current_canary_sources):
            raise DocsError(f"DOC_RETIRED_CANARY_IDENTITY:{literal}")
    candidate_zh = README_CANDIDATE_ZH in zh
    candidate_en = README_CANDIDATE_EN in en
    stable_zh = README_STABLE_ZH in zh
    stable_en = README_STABLE_EN in en
    quick_candidate_zh = QUICKSTART_CANDIDATE_ZH in quickstart_zh
    quick_candidate_en = QUICKSTART_CANDIDATE_EN in quickstart_en
    quick_stable_zh = QUICKSTART_STABLE_ZH in quickstart_zh
    quick_stable_en = QUICKSTART_STABLE_EN in quickstart_en
    if (
        candidate_zh != candidate_en
        or stable_zh != stable_en
        or candidate_zh != quick_candidate_zh
        or stable_zh != quick_stable_zh
        or quick_candidate_zh != quick_candidate_en
        or quick_stable_zh != quick_stable_en
    ):
        raise DocsError("DOC_RELEASE_STATUS_PARITY_DRIFT")
    if mode == "release":
        if (
            not stable_zh
            or candidate_zh
            or "尚未发布" in zh
            or "尚未发布" in quickstart_zh
            or "not yet published" in en
            or "not yet published" in quickstart_en
            or "LoopSkill 4.0.0 is the currently supported public line." not in security
            or "## [4.0.0] - 2026-07-28" not in changelog
        ):
            raise DocsError("DOC_RELEASE_STATUS_NOT_STABLE")
    elif mode == "candidate" and (
        not candidate_zh
        or stable_zh
        or "after public release" not in security
    ):
        raise DocsError("DOC_RELEASE_STATUS_PREMATURE_OR_AMBIGUOUS")
    elif mode == "auto" and candidate_zh == stable_zh:
        raise DocsError("DOC_RELEASE_STATUS_MISSING_OR_AMBIGUOUS")
    return {
        "bash_command_blocks": len(zh_bash),
        "link_targets": sum(_links(zh).values()),
        "quickstart_bash_command_blocks": len(quickstart_zh_bash),
        "release_bash_command_blocks": len(releasing_bash),
        "release_mode": mode,
        "section_count": len(EXPECTED_SECTIONS),
        "status": "PASS",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--candidate", action="store_true")
    modes.add_argument("--release", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        mode = "release" if args.release else "candidate" if args.candidate else "auto"
        result = validate(args.root, mode=mode)
        if args.smoke:
            result["command_smoke"] = smoke_public_commands(args.root)["status"]
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
