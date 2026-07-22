"""Privacy-safe scanner that distinguishes identifiers from credentials."""

from __future__ import annotations

import fnmatch
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


PATTERNS = {
    "AWS_ACCESS_KEY": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GITHUB_TOKEN": re.compile(r"\bgh[opsu]_[A-Za-z0-9]{30,}\b"),
    "OPENAI_API_KEY": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "PRIVATE_KEY": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "SHA256": re.compile(r"(?<![A-Fa-f0-9])[a-f0-9]{64}(?![A-Fa-f0-9])"),
}
PLACEHOLDER_RE = re.compile(
    r"(?:REDACTED|PLACEHOLDER|FIXTURE|EXAMPLE|SAMPLE|<your-[^>]+>|\$\{[A-Z0-9_]+\})",
    re.IGNORECASE,
)
CREDENTIAL_KINDS = frozenset(PATTERNS) - {"SHA256"}


class RiskScannerError(ValueError):
    pass


@dataclass(frozen=True)
class AllowRule:
    rule_id: str
    path_glob: str
    kind: str
    reason: str

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in self.__dict__.values()):
            raise RiskScannerError("ALLOW_RULE_INVALID")
        if self.kind not in {*PATTERNS, "PLACEHOLDER", "FIXTURE"}:
            raise RiskScannerError("ALLOW_RULE_KIND_INVALID")


def scan(root: Path, allowlist: tuple[AllowRule, ...] = ()) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or ".git" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        relative = path.relative_to(root).as_posix()
        for line_number, line in enumerate(text.splitlines(), 1):
            placeholder_line = PLACEHOLDER_RE.search(line) is not None
            if placeholder_line:
                findings.append(_finding(relative, line_number, "PLACEHOLDER", line, allowlist))
            for kind, pattern in PATTERNS.items():
                for match in pattern.finditer(line):
                    classified = "FIXTURE" if placeholder_line and kind in CREDENTIAL_KINDS else kind
                    findings.append(_finding(relative, line_number, classified, match.group(0), allowlist))
    return findings


def _finding(
    path: str, line: int, kind: str, value: str,
    allowlist: tuple[AllowRule, ...],
) -> dict[str, object]:
    matched = next(
        (rule for rule in allowlist if rule.kind == kind and fnmatch.fnmatchcase(path, rule.path_glob)),
        None,
    )
    return {
        "allow_rule_id": matched.rule_id if matched else None,
        "allowed": matched is not None,
        "kind": kind,
        "line": line,
        "path": path,
        "risky": kind in CREDENTIAL_KINDS and matched is None,
        "value_digest": "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest(),
    }


def unallowed_credentials(findings: list[dict[str, object]]) -> list[dict[str, object]]:
    return [finding for finding in findings if finding["risky"] is True]


__all__ = [
    "AllowRule", "CREDENTIAL_KINDS", "RiskScannerError", "scan",
    "unallowed_credentials",
]
