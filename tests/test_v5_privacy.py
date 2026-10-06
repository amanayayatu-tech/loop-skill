from __future__ import annotations

import re
import subprocess
import tempfile
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


def content_text_views(raw: bytes) -> list[str]:
    texts = [raw.decode("utf-8", errors="replace")]
    # UTF-16/32 ASCII markers contain NULs, with or without a BOM. Keep the
    # original binary-safe UTF-8 view and inspect explicit byte orders too.
    if b"\0" in raw:
        for encoding in ("utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"):
            try:
                texts.append(raw.decode(encoding))
            except UnicodeDecodeError:
                continue
    return texts


def scan_repository(root: Path) -> list[str]:
    raw_names = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
    )
    findings: list[str] = []
    for raw_name in raw_names.split(b"\0"):
        if not raw_name:
            continue
        relative = raw_name.decode("utf-8")
        path = root / relative
        if not path.is_file() or path.is_symlink():
            continue
        texts = content_text_views(path.read_bytes())
        for label, pattern in FORBIDDEN.items():
            if any(pattern.search(text) for text in texts):
                findings.append(f"{relative}:{label}")
    return findings


class LoopSkill5PrivacyTest(unittest.TestCase):
    def test_encoded_text_keeps_private_markers_visible(self) -> None:
        # Synthetic fixtures are assembled so this source contains no secrets.
        task_id = "-".join(("019fc123", "abcd", "7abc", "8abc", "abcdef012345"))
        private_text = "\n".join((
            "/U" + "sers/example/private",
            "/tmp/loopsk" + "ill-private",
            task_id,
            "g" + "hp_" + "A" * 24,
            "s" + "k-" + "B" * 24,
            "AKI" + "A" + "C" * 16,
            "-----BEGIN PRIVATE K" + "EY-----",
        ))
        public_id = "-".join(("01a01234", "abcd", "4abc", "8abc", "abcdef012345"))
        public_text = "普通公开文本 / ordinary public text / " + public_id
        encodings = (
            ("utf-16", "utf-16", b""),
            ("utf-16-le", "utf-16-le", b""),
            ("utf-16-be", "utf-16-be", b""),
            ("utf-16-be-bom", "utf-16-be", b"\xfe\xff"),
            ("utf-32", "utf-32", b""),
            ("utf-32-le", "utf-32-le", b""),
            ("utf-32-be", "utf-32-be", b""),
            ("utf-32-be-bom", "utf-32-be", b"\x00\x00\xfe\xff"),
        )
        for label, encoding, bom in encodings:
            with self.subTest(encoding=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                subprocess.run(["git", "init", "--quiet", str(root)], check=True)
                (root / "report.txt").write_bytes(bom + private_text.encode(encoding))
                (root / "ordinary.txt").write_bytes(bom + public_text.encode(encoding))
                expected = [f"report.txt:{label}" for label in FORBIDDEN]
                self.assertEqual(scan_repository(root), expected)
                subprocess.run(["git", "add", "."], cwd=root, check=True)
                self.assertEqual(scan_repository(root), expected)

    def test_utf8_and_malformed_bytes_keep_the_original_text_view(self) -> None:
        private_text = ("/U" + "sers/example/private").encode("utf-8")
        for label, raw in (
            ("utf-8", private_text),
            ("utf-8-bom", b"\xef\xbb\xbf" + private_text),
            ("invalid-utf-8", b"\xff" + private_text + b"\xfe"),
        ):
            with self.subTest(encoding=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                subprocess.run(["git", "init", "--quiet", str(root)], check=True)
                (root / "report.txt").write_bytes(raw)
                (root / "ordinary.bin").write_bytes(b"ordinary\x00bytes\xff")
                self.assertEqual(scan_repository(root), ["report.txt:local-home-path"])

    def test_release_candidate_has_no_local_identity_or_high_confidence_secret(self) -> None:
        self.assertEqual(scan_repository(ROOT), [])


if __name__ == "__main__":
    unittest.main()
