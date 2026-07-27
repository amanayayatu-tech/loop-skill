from __future__ import annotations

import os
import unittest
from io import StringIO


class V4AtomicConformanceTests(unittest.TestCase):
    """Execute one catalog parameter through its frozen concrete test binding."""

    def test_case(self) -> None:
        case_id = os.environ.get("LOOPSKILL4_CONFORMANCE_CASE_ID", "")
        target = os.environ.get("LOOPSKILL4_CONFORMANCE_TARGET", "")
        family = os.environ.get("LOOPSKILL4_CONFORMANCE_FAMILY", "")
        if not (case_id or target or family):
            self.assertNotIn("LOOPSKILL4_CONFORMANCE_CASE_ID", os.environ)
            return
        self.assertTrue(case_id and target and family)
        self.assertTrue(case_id.startswith(family + "-"))
        self.assertNotIn("test_v4_atomic_conformance", target)
        suite = unittest.defaultTestLoader.loadTestsFromName(target)
        self.assertEqual(suite.countTestCases(), 1)
        stream = StringIO()
        result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
        self.assertEqual(result.testsRun, 1)
        self.assertFalse(result.skipped)
        self.assertTrue(result.wasSuccessful(), stream.getvalue())


if __name__ == "__main__":
    unittest.main()
