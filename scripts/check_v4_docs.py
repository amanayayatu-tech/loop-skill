#!/usr/bin/env python3
"""Fail-closed parity and stale-product checks for public v4 documentation."""

from __future__ import annotations

import argparse
import collections
import hashlib
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
    "4.1.1",
    "1–32",
    "CONTENT_ADDRESSED_V1",
    "EAGER_V4_0",
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
README_CANDIDATE_STATUS_ZH = "本文档对应 LoopSkill 4.1.1 发布候选，正在等待作者发布授权；当前可用的公开版本仍以"
README_CANDIDATE_STATUS_EN = "This document describes the LoopSkill 4.1.1 release candidate, which is awaiting author release authorization. See"
QUICKSTART_CANDIDATE_STATUS_ZH = "本文档对应 LoopSkill 4.1.1 发布候选，正在等待作者发布授权；当前可用的公开版本仍以 GitHub Releases 页面为准"
QUICKSTART_CANDIDATE_STATUS_EN = "This document describes the LoopSkill 4.1.1 release candidate, which is awaiting\nauthor release authorization. See GitHub Releases for the public versions currently available."
SECURITY_CANDIDATE_STATUS = "describes the LoopSkill 4.1.1 release-candidate security boundary"
RELEASE_NOTES_CANDIDATE_STATUS = "Status: `V4_1_RC_READY_AWAITING_AUTHOR_RELEASE_AUTHORIZATION` is the only\npre-publication completion state."
README_RELEASE_STATUS_ZH = "本文档对应 LoopSkill 4.1.1；当前可用的公开版本以"
README_RELEASE_STATUS_EN = "This document describes LoopSkill 4.1.1. See"
QUICKSTART_RELEASE_STATUS_ZH = "本文档对应 LoopSkill 4.1.1；当前可用的公开版本以 GitHub Releases 页面为准"
QUICKSTART_RELEASE_STATUS_EN = "This document describes LoopSkill 4.1.1. See GitHub Releases for the public versions currently available."
SECURITY_RELEASE_STATUS = "LoopSkill 4.1.1 is the currently supported public line."
RELEASE_NOTES_RELEASE_STATUS = "Status: LoopSkill 4.1.1 is the current public v4 release."
SECURITY_STATUS = "Security support follows the versions listed on GitHub Releases."
README_ASSETS = (
    (
        "docs/readme-assets/durable-handoff.png",
        "f75273951962563c96fc85d0c237eedd791dcb63",
        "99d89f8e7a3ae08e35282ed1275e0d35882a96759fffa6a3efe32523cd7dc1a6",
    ),
    (
        "docs/readme-assets/evidence-before-closure.png",
        "766b631dfd889352664d3f112df43048278f8518",
        "e9088274d7745679a8563ba6baef2db2c47b11a792b978fb15de03b5ceb1cdd0",
    ),
)


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


def _images(text: str) -> tuple[tuple[str, str], ...]:
    return tuple(re.findall(r"!\[([^\]]+)\]\(([^)]+)\)", text))


def _check_readme_assets(root: Path, zh: str, en: str) -> None:
    zh_images = tuple(
        image for image in _images(zh) if image[1].startswith("docs/readme-assets/")
    )
    en_images = tuple(
        image for image in _images(en) if image[1].startswith("docs/readme-assets/")
    )
    expected = tuple(path for path, _, _ in README_ASSETS)
    if tuple(target for _, target in zh_images) != expected:
        raise DocsError("DOC_IMAGE_TARGET_DRIFT:zh")
    if tuple(target for _, target in en_images) != expected:
        raise DocsError("DOC_IMAGE_TARGET_DRIFT:en")
    if any(len(alt.strip()) < 12 for alt, _ in zh_images + en_images):
        raise DocsError("DOC_IMAGE_ALT_MISSING")
    if any(zh_alt == en_alt for (zh_alt, _), (en_alt, _) in zip(zh_images, en_images)):
        raise DocsError("DOC_IMAGE_ALT_PARITY_DRIFT")
    for relative, expected_blob, expected_sha256 in README_ASSETS:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise DocsError(f"DOC_IMAGE_UNSAFE:{relative}")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise DocsError(f"DOC_IMAGE_BYTES_DRIFT:{relative}")
        blob_digest = hashlib.sha1(
            f"blob {len(raw)}\0".encode("ascii") + raw
        ).hexdigest()
        if blob_digest != expected_blob:
            raise DocsError(f"DOC_IMAGE_BLOB_DRIFT:{relative}")
        if not (root / ".git").exists():
            continue
        try:
            blob = subprocess.check_output(
                ["git", "rev-parse", f"v3.3.8:{relative}"], cwd=root, text=True
            ).strip()
        except subprocess.CalledProcessError as exc:
            raise DocsError(f"DOC_IMAGE_PROVENANCE_MISSING:{relative}") from exc
        if blob != expected_blob:
            raise DocsError(f"DOC_IMAGE_PROVENANCE_DRIFT:{relative}")


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
    zh = (root / "README.md").read_text(encoding="utf-8")
    en = (root / "README.en.md").read_text(encoding="utf-8")
    quickstart_zh = (root / "docs/v4/quickstart.zh-CN.md").read_text(encoding="utf-8")
    quickstart_en = (root / "docs/v4/quickstart.en.md").read_text(encoding="utf-8")
    releasing = (root / "docs/RELEASING.md").read_text(encoding="utf-8")
    release_notes_v41 = (root / "docs/v4/release-notes-v4.1.md").read_text(
        encoding="utf-8"
    )
    security = (root / "SECURITY.md").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if version != "4.1.1":
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
    _check_readme_assets(root, zh, en)
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
        if literal not in release_notes_v41:
            raise DocsError(f"DOC_RELEASE_NOTES_INCOMPLETE:{literal}")
    for claim in COMMON_CLAIMS:
        if claim not in zh or claim not in en:
            raise DocsError(f"DOC_CLAIM_PARITY_DRIFT:{claim}")
    if "不注册 MCP" not in zh or "does not register MCP" not in en:
        raise DocsError("DOC_MCP_CLAIM_DRIFT")
    if "不要求为安装或使用 LoopSkill 4 重启" not in zh:
        raise DocsError("DOC_RESTART_CLAIM_DRIFT:zh")
    if "or require a Codex App restart" not in en:
        raise DocsError("DOC_RESTART_CLAIM_DRIFT:en")
    if (
        "Host 自身可能" not in zh
        or "真实非零" not in zh
        or "Host itself may" not in en
        or "real nonzero" not in en
        or "Host 自身可能" not in quickstart_zh
        or "真实非零" not in quickstart_zh
        or "the Host may append" not in quickstart_en
        or "real nonzero" not in quickstart_en
    ):
        raise DocsError("DOC_HOST_TRUST_DELTA_CLAIM_DRIFT")
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
    candidate_status = (
        README_CANDIDATE_STATUS_ZH in zh
        and README_CANDIDATE_STATUS_EN in en
        and QUICKSTART_CANDIDATE_STATUS_ZH in quickstart_zh
        and QUICKSTART_CANDIDATE_STATUS_EN in quickstart_en
        and SECURITY_CANDIDATE_STATUS in security
        and RELEASE_NOTES_CANDIDATE_STATUS in release_notes_v41
    )
    release_status = (
        README_RELEASE_STATUS_ZH in zh
        and README_RELEASE_STATUS_EN in en
        and QUICKSTART_RELEASE_STATUS_ZH in quickstart_zh
        and QUICKSTART_RELEASE_STATUS_EN in quickstart_en
        and SECURITY_RELEASE_STATUS in security
        and RELEASE_NOTES_RELEASE_STATUS in release_notes_v41
    )
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
        for text in (zh, en, quickstart_zh, quickstart_en, security, release_notes_v41)
    ):
        raise DocsError("DOC_RELEASE_STATUS_PREMATURE_OR_AMBIGUOUS")
    if candidate_status and "## [4.1.1] - Unreleased" not in changelog:
        raise DocsError("DOC_RELEASE_STATUS_NOT_CANDIDATE")
    if mode == "release" and (
        re.search(r"^## \[4\.1\.1\] - 20[0-9]{2}-[0-9]{2}-[0-9]{2}$", changelog, re.MULTILINE)
        is None
        or "## [4.1.1] - Unreleased" in changelog
    ):
        raise DocsError("DOC_RELEASE_STATUS_NOT_STABLE")
    return {
        "bash_command_blocks": len(zh_bash),
        "link_targets": sum(_links(zh).values()),
        "readme_asset_count": len(README_ASSETS),
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
