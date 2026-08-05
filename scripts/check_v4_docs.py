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


STALE_CURRENT_PRODUCT = (
    "scripts/loopctl",
    "$codex-loop-prompt-architect",
    "MCP_CANONICAL_WRITER",
    "READY_WITH_ASSUMPTIONS",
    ".codex-loop/LOOP_STATE",
    "Use $codex-loop-prompt-architect",
    "schema-v3 canonical",
)
QUICKSTART_COMMON_CLAIMS = (
    "4.2.0",
    "1–128",
    "CONTENT_ADDRESSED_V1",
    "EAGER_V4_0",
    "INTAKE",
    "PREPARE",
    "CONFIRM",
    "START",
    "UNKNOWN",
    "UNVERIFIABLE",
    "https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8",
)
QUICKSTART_CANDIDATE_STATUS_ZH = "本文档对应 LoopSkill 4.2.0 发布候选，正在等待作者发布授权；当前可用的公开版本仍以 GitHub Releases 页面为准"
QUICKSTART_CANDIDATE_STATUS_EN = "This document describes the LoopSkill 4.2.0 release candidate, which is awaiting\nauthor release authorization. See GitHub Releases for the public versions currently available."
SECURITY_CANDIDATE_STATUS = "describes the LoopSkill 4.2.0 release-candidate security boundary"
RELEASE_NOTES_CANDIDATE_STATUS = "Status: `V4_2_RC_READY_AWAITING_AUTHOR_RELEASE_AUTHORIZATION` is the only\npre-publication completion state."
QUICKSTART_RELEASE_STATUS_ZH = "本文档对应 LoopSkill 4.2.0；当前可用的公开版本以 GitHub Releases 页面为准"
QUICKSTART_RELEASE_STATUS_EN = "This document describes LoopSkill 4.2.0. See GitHub Releases for the public versions currently available."
SECURITY_RELEASE_STATUS = "When GitHub Releases lists LoopSkill 4.2.0, it is the supported public v4 line."
RELEASE_NOTES_RELEASE_STATUS = "Status: publication is established only by the public v4.2.0 tag and GitHub\nRelease readback."
SECURITY_STATUS = "Security support follows the versions listed on GitHub Releases."
QUICKSTART_CANARY_STATUS_ZH = "并要求三层有序的一次性 canary。"
QUICKSTART_CANARY_STATUS_EN = "and requires three ordered one-shot canary layers."
class DocsError(ValueError):
    pass


def _blocks(text: str, language: str) -> tuple[str, ...]:
    return tuple(
        match.strip() for match in re.findall(
            rf"```{re.escape(language)}\n(.*?)\n```", text, re.DOTALL
        )
    )


def _links(text: str) -> collections.Counter[str]:
    values = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
    return collections.Counter(values)


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
            "capacity-report.json",
            "loop-manifest.json",
            "plan-document.json",
            "plan-index.json",
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
    quickstart_zh = (root / "docs/v4/quickstart.zh-CN.md").read_text(encoding="utf-8")
    quickstart_en = (root / "docs/v4/quickstart.en.md").read_text(encoding="utf-8")
    releasing = (root / "docs/RELEASING.md").read_text(encoding="utf-8")
    release_notes_v42 = (root / "docs/v4/release-notes-v4.2.md").read_text(
        encoding="utf-8"
    )
    security = (root / "SECURITY.md").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if version != "4.2.0":
        raise DocsError("DOC_VERSION_DRIFT")
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
        "--candidate-root",
        "scripts/build_v4_author_packet.py",
        "--canary-2-store",
        "--canary-8-store",
        "349 semantic mappings to 74",
        "canary-environment-integrity.json",
        "Host config/auth",
        "CODEX_WORKSPACE_TRUST_APPEND_V1",
        "observed_host_config_changed_bytes",
        "unexpected_changed_input_count",
        'trust_level = "trusted"',
    ):
        if literal not in releasing:
            raise DocsError(f"DOC_RELEASE_RUNBOOK_INCOMPLETE:{literal}")
    for literal in (
        "`INTAKE → PREPARE → CONFIRM → START`",
        "v4-only hard break",
        "https://github.com/amanayayatu-tech/loop-skill/releases/tag/v3.3.8",
        "does not register MCP",
        "require an App restart",
        "cross-system",
        "exactly-once",
        "support multiple Hosts",
        "patch-success",
        "long-horizon superiority",
    ):
        if literal not in release_notes_v42:
            raise DocsError(f"DOC_RELEASE_NOTES_INCOMPLETE:{literal}")
    for claim in QUICKSTART_COMMON_CLAIMS:
        if claim not in quickstart_zh or claim not in quickstart_en:
            raise DocsError(f"DOC_CLAIM_PARITY_DRIFT:{claim}")
    if (
        "不注册 MCP" not in quickstart_zh
        or "does not modify it, register MCP" not in quickstart_en
    ):
        raise DocsError("DOC_MCP_CLAIM_DRIFT")
    if "不要求为了 LoopSkill 4 重启 Codex" not in quickstart_zh:
        raise DocsError("DOC_RESTART_CLAIM_DRIFT:zh")
    if "or require a Codex restart for LoopSkill 4" not in quickstart_en:
        raise DocsError("DOC_RESTART_CLAIM_DRIFT:en")
    if (
        "Host 自身可能" not in quickstart_zh
        or "真实非零" not in quickstart_zh
        or "the host may append" not in quickstart_en.lower()
        or "real nonzero" not in quickstart_en
    ):
        raise DocsError("DOC_HOST_TRUST_DELTA_CLAIM_DRIFT")
    for literal in STALE_CURRENT_PRODUCT:
        if literal in quickstart_zh or literal in quickstart_en:
            raise DocsError(f"DOC_STALE_V3_CURRENT_PRODUCT:{literal}")
    public_entry_docs = (quickstart_zh, quickstart_en)
    if any("<receipt>" in text or " --receipt " in text for text in public_entry_docs):
        raise DocsError("DOC_MANUAL_RECEIPT_TRANSPORT")
    if (
        "codex login status 2>&1 | grep -F 'Logged in'" not in releasing
        or "codex login status | grep -F 'Logged in'" in releasing
    ):
        raise DocsError("DOC_CANARY_LOGIN_STREAM_DRIFT")
    if (
        "控制证据持久保存在" not in quickstart_zh
        or "`codex exec resume`" not in quickstart_zh
        or "persists the session and terminal controls" not in quickstart_en
        or "`codex exec resume`" not in quickstart_en
    ):
        raise DocsError("DOC_RECOVERY_ATTEMPT_SEMANTICS_DRIFT")
    ux_contract = (root / "docs/architecture/loopskill-v4-single-entry-ux.md").read_text(
        encoding="utf-8"
    )
    for literal in (
        "owner-only child root",
        "persists input/session/process/terminal",
        "same-session resume",
        "Non-replayable actions wait",
    ):
        if literal not in ux_contract:
            raise DocsError(f"DOC_RECOVERY_ATTEMPT_SEMANTICS_DRIFT:{literal}")
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
    candidate_status = (
        QUICKSTART_CANDIDATE_STATUS_ZH in quickstart_zh
        and QUICKSTART_CANDIDATE_STATUS_EN in quickstart_en
        and SECURITY_CANDIDATE_STATUS in security
        and RELEASE_NOTES_CANDIDATE_STATUS in release_notes_v42
    )
    release_status = (
        QUICKSTART_RELEASE_STATUS_ZH in quickstart_zh
        and QUICKSTART_RELEASE_STATUS_EN in quickstart_en
        and SECURITY_RELEASE_STATUS in security
        and RELEASE_NOTES_RELEASE_STATUS in release_notes_v42
    )
    if (
        QUICKSTART_CANARY_STATUS_ZH not in quickstart_zh
        or QUICKSTART_CANARY_STATUS_EN not in quickstart_en
    ):
        raise DocsError("DOC_CANARY_CLAIM_DRIFT")
    if (
        SECURITY_STATUS not in security
        or (mode == "candidate" and not candidate_status)
        or (mode == "release" and not release_status)
        or (mode == "auto" and candidate_status == release_status)
    ):
        raise DocsError("DOC_RELEASE_STATUS_PARITY_DRIFT")
    premature = (
        "稳定发行",
        "尚未发布",
        "stable release",
        "not yet published",
    )
    if any(
        literal in text
        for literal in premature
        for text in (quickstart_zh, quickstart_en, security, release_notes_v42)
    ):
        raise DocsError("DOC_RELEASE_STATUS_PREMATURE_OR_AMBIGUOUS")
    if candidate_status and "## [4.2.0] - Unreleased" not in changelog:
        raise DocsError("DOC_RELEASE_STATUS_NOT_CANDIDATE")
    if mode == "release" and (
        re.search(r"^## \[4\.2\.0\] - 20[0-9]{2}-[0-9]{2}-[0-9]{2}$", changelog, re.MULTILINE)
        is None
        or "## [4.2.0] - Unreleased" in changelog
    ):
        raise DocsError("DOC_RELEASE_STATUS_NOT_STABLE")
    return {
        "quickstart_bash_command_blocks": len(quickstart_zh_bash),
        "quickstart_link_targets": sum(_links(quickstart_zh).values()),
        "release_bash_command_blocks": len(releasing_bash),
        "release_mode": mode,
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
