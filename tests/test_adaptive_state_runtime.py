"""Stable CI entrypoint for the state fuzz lane after the test-suite split."""

from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tests.test_state_runtime_finalization import AdaptiveStateRuntimeFinalizationTests


class AdaptiveStateRuntimeTests(unittest.TestCase):
    def test_malformed_and_random_sequences_never_mutate_or_corrupt(self) -> None:
        target = AdaptiveStateRuntimeFinalizationTests(
            "test_malformed_and_random_sequences_never_mutate_or_corrupt"
        )
        target.setUp()
        try:
            target.test_malformed_and_random_sequences_never_mutate_or_corrupt()
        finally:
            target.tearDown()
