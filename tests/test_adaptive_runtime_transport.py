from __future__ import annotations

import os
import pty
import hashlib
import subprocess
import sys
import tempfile
import unittest
import json
from contextlib import contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "codex-loop-prompt-architect" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import adaptive_state_runtime as runtime  # noqa: E402
from adaptive_state_runtime import (  # noqa: E402
    InputTransportError,
    _load_request,
    _read_bounded_stdin,
)


@contextmanager
def stdin_from_fd(fd: int):
    stream = os.fdopen(fd, "r", encoding="utf-8", closefd=True)
    try:
        with patch.object(sys, "stdin", stream):
            yield
    finally:
        stream.close()


class AdaptiveRuntimeTransportTests(unittest.TestCase):
    def test_complete_json_returns_without_eof(self) -> None:
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, b'{"request_id":"ready"}')
            with stdin_from_fd(read_fd):
                value = _read_bounded_stdin("apply", timeout_seconds=0.2)
            self.assertEqual(value, '{"request_id":"ready"}')
        finally:
            os.close(write_fd)

    def test_every_json_stdin_mode_completes_without_eof(self) -> None:
        for mode in (
            "apply",
            "payload-materialize",
            "report-stage",
            "external-receipt-stage",
            "fingerprint-normalize",
        ):
            with self.subTest(mode=mode):
                read_fd, write_fd = os.pipe()
                try:
                    os.write(write_fd, b'{"request_id":"ready"}')
                    with stdin_from_fd(read_fd):
                        value = _read_bounded_stdin(mode, timeout_seconds=0.2)
                    self.assertEqual(value, '{"request_id":"ready"}')
                finally:
                    os.close(write_fd)

    def test_cli_process_exits_and_is_reaped_while_stdin_stays_open(self) -> None:
        payload = {
            "command": "pytest",
            "exit_code": 1,
            "output_lines": ["FAILED synthetic"],
            "failing_test_ids": ["synthetic"],
            "changed_files": ["synthetic.py"],
            "diff_digest": "sha256:" + "1" * 64,
            "strategy_id": "strategy-a",
            "hypothesis_digest": "sha256:" + "2" * 64,
            "raw_log_digest": "sha256:" + "3" * 64,
        }
        process = subprocess.Popen(
            [
                sys.executable,
                str(SCRIPTS / "adaptive_state_runtime.py"),
                "--fingerprint-normalize",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertIsNotNone(process.stdin)
        self.assertIsNotNone(process.stdout)
        self.assertIsNotNone(process.stderr)
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        process.stdin.write(json.dumps(payload, separators=(",", ":")))
        process.stdin.flush()
        process.wait(timeout=2)
        stdout = process.stdout.read()
        stderr = process.stderr.read()
        process.stdin.close()
        process.stdout.close()
        process.stderr.close()
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(
            json.loads(stdout)["status"],
            "FAILURE_FINGERPRINT_NORMALIZED",
        )
        with self.assertRaises(ProcessLookupError):
            os.kill(process.pid, 0)

    def test_closed_pipe_remains_compatible(self) -> None:
        read_fd, write_fd = os.pipe()
        os.write(write_fd, b'{"request_id":"legacy"')
        os.close(write_fd)
        with stdin_from_fd(read_fd):
            value = _read_bounded_stdin("apply", timeout_seconds=0.2)
        self.assertEqual(value, '{"request_id":"legacy"')

    def test_partial_open_pipe_times_out(self) -> None:
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, b'{"request_id":')
            with stdin_from_fd(read_fd):
                with self.assertRaisesRegex(
                    InputTransportError, "INPUT_TRANSPORT_TIMEOUT"
                ) as raised:
                    _read_bounded_stdin("apply", timeout_seconds=0.05)
            self.assertGreater(raised.exception.details["bytes_received"], 0)
        finally:
            os.close(write_fd)

    def test_canonical_pty_without_newline_times_out(self) -> None:
        master_fd, slave_fd = pty.openpty()
        try:
            os.write(master_fd, b'{"request_id":"buffered"}')
            with stdin_from_fd(slave_fd):
                with self.assertRaisesRegex(
                    InputTransportError, "INPUT_TRANSPORT_TIMEOUT"
                ) as raised:
                    _read_bounded_stdin("apply", timeout_seconds=0.05)
            self.assertEqual(raised.exception.details["bytes_received"], 0)
        finally:
            os.close(master_fd)

    def test_input_limit_is_enforced(self) -> None:
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, b'{"payload":"0123456789"}')
            with stdin_from_fd(read_fd):
                with self.assertRaisesRegex(
                    InputTransportError, "INPUT_TRANSPORT_TOO_LARGE"
                ):
                    _read_bounded_stdin("apply", timeout_seconds=0.2, max_bytes=8)
        finally:
            os.close(write_fd)

    def test_exact_four_megabytes_is_allowed_and_plus_one_is_rejected(self) -> None:
        for size, accepted in ((4_000_000, True), (4_000_001, False)):
            with self.subTest(size=size), tempfile.TemporaryFile() as source:
                payload = b'{"p":"' + (b"x" * (size - 8)) + b'"}'
                self.assertEqual(len(payload), size)
                source.write(payload)
                source.seek(0)
                with stdin_from_fd(os.dup(source.fileno())):
                    if accepted:
                        value = _read_bounded_stdin("apply")
                        self.assertEqual(len(value.encode("utf-8")), size)
                    else:
                        with self.assertRaisesRegex(
                            InputTransportError,
                            "INPUT_TRANSPORT_TOO_LARGE",
                        ):
                            _read_bounded_stdin("apply")

    def test_invalid_utf8_is_rejected_immediately(self) -> None:
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, b"\xff")
            with stdin_from_fd(read_fd):
                with self.assertRaisesRegex(
                    InputTransportError, "INPUT_TRANSPORT_UTF8_INVALID"
                ):
                    _read_bounded_stdin("apply", timeout_seconds=0.2)
        finally:
            os.close(write_fd)

    def test_strict_loader_rejects_duplicate_nonfinite_and_extra_frames(self) -> None:
        for payload in (
            '{"duplicate":1,"duplicate":2}',
            '{"value":NaN}',
            '{}{}',
            '{} trailing',
        ):
            with self.subTest(payload=payload), self.assertRaises(
                (json.JSONDecodeError, ValueError)
            ):
                _load_request(payload)

    def test_transport_fixture_digest_matches_exact_frame(self) -> None:
        fixture_path = (
            ROOT / "tests" / "fixtures" / "control_plane_reliability" / "transport-8265.json"
        )
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        payload = fixture["frame"].encode("utf-8")
        self.assertEqual(len(payload), 8265)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), fixture["frame_sha256"])

    def test_payload_verify_frame_completes_without_eof(self) -> None:
        read_fd, write_fd = os.pipe()
        try:
            frame = 'WORKER_DISPATCH\n{"dispatch_payload_digest":"sha256:' + "a" * 64 + '"}'
            os.write(write_fd, frame.encode("utf-8"))
            with stdin_from_fd(read_fd):
                value = _read_bounded_stdin("payload-verify", timeout_seconds=0.2)
            self.assertEqual(value, frame)
        finally:
            os.close(write_fd)

    def test_cli_transport_errors_are_structured(self) -> None:
        for status in (
            "INPUT_TRANSPORT_TIMEOUT",
            "INPUT_TRANSPORT_TOO_LARGE",
            "INPUT_TRANSPORT_UTF8_INVALID",
        ):
            with self.subTest(status=status), patch.object(
                runtime,
                "_read_bounded_stdin",
                side_effect=InputTransportError(status, bytes_received=17),
            ):
                output = StringIO()
                with redirect_stdout(output):
                    exit_code = runtime.main(["--payload-materialize"])
                response = json.loads(output.getvalue())
                self.assertEqual(exit_code, 1)
                self.assertEqual(response["status"], status)
                self.assertEqual(response["error"]["path"], "/stdin")
                self.assertEqual(
                    response["error"]["details"]["bytes_received"], 17
                )


if __name__ == "__main__":
    unittest.main()
