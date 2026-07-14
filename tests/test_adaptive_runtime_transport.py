from __future__ import annotations

import os
import pty
import sys
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
