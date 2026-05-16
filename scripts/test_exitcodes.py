#!/usr/bin/env python3
"""Tests for scripts/lib/exitcodes.py (T0-3 Task 1).

Contract pin: CONTRACT-PIN §4 — canonical names + numeric values.
"""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))


class ExitCodesTests(unittest.TestCase):
    def test_canonical_constants(self) -> None:
        from lib.exitcodes import (
            EXIT_OK,
            EXIT_OPERATIONAL,
            EXIT_INVALID_TRANSITION,
            EXIT_SESSION_LOCKED,
            EXIT_SCOPE_VIOLATION,
            EXIT_UNPARSEABLE_JSON,
            EXIT_WRONG_PHASE_FOR_VERB,
            EXIT_STALE_UNCERTAIN,
            EXIT_TIMESTAMP_OUT_OF_RANGE,
        )
        self.assertEqual(
            (
                EXIT_OK,
                EXIT_OPERATIONAL,
                EXIT_INVALID_TRANSITION,
                EXIT_SESSION_LOCKED,
                EXIT_SCOPE_VIOLATION,
                EXIT_UNPARSEABLE_JSON,
                EXIT_WRONG_PHASE_FOR_VERB,
                EXIT_STALE_UNCERTAIN,
                EXIT_TIMESTAMP_OUT_OF_RANGE,
            ),
            (0, 1, 2, 3, 4, 5, 6, 7, 8),
        )

    def test_scope_violation_is_4(self) -> None:
        # CONTRACT-PIN §4: reservation lifted; consumed by T1-1.
        from lib.exitcodes import EXIT_SCOPE_VIOLATION
        self.assertEqual(EXIT_SCOPE_VIOLATION, 4)


if __name__ == "__main__":
    unittest.main()
