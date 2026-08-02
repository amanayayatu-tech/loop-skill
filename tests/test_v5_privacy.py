from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {
    "local-home-path": re.compile(r"/U[s]ers/"),
    "loopskill-scratch-path": re.compile(r"/tmp/loopsk[i]ll", re.IGNORECASE),
    "codex-task-identity": re.compile(r"019f[c][0-9a-f-]{20,}", re.IGNORECASE),
    "github-token": re.compile(r"(?:g[h]p_|g[h]o_|github_p[a]t_)[A-Za-z0-9_]{20,}"),
    "openai-key": re.compile(r"s[k]-[A-Za-z0-9_-]{20,}"),
    "aws-access-key": re.compile(r"AKI[A][0-9A-Z]{16}"),
    "private-key": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE K[E]Y-----"
    ),
}


class LoopSkill5PrivacyTest(unittest.TestCase):
    def test_release_candidate_has_no_local_identity_or_high_confidence_secret(self) -> None:
        raw_names = subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
        )
        findings: list[str] = []
        for raw_name in raw_names.split(b"\0"):
            if not raw_name:
                continue
            relative = raw_name.decode("utf-8")
            path = ROOT / relative
            if not path.is_file() or path.is_symlink():
                continue
            raw = path.read_bytes()
            if b"\0" in raw:
                continue
            text = raw.decode("utf-8", errors="replace")
            for label, pattern in FORBIDDEN.items():
                if pattern.search(text):
                    findings.append(f"{relative}:{label}")
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
