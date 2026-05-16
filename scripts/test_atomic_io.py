#!/usr/bin/env python3
"""Tests for the atomic I/O primitives (scripts/lib/atomic_io.py).

Plan: .planning/phases/02b-hardening/plans/02b-01-T0-A-PLAN.md
Contract: .planning/phases/02b-hardening/CONTRACT-PIN.md §1, §2, §3
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import atomic_io  # noqa: E402  (path injection above)


class TestAtomicWriteTextHappyPath(unittest.TestCase):
    def test_atomic_write_text_creates_file_with_content(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "out.txt"
            atomic_io.atomic_write_text(target, "hello\n")
            self.assertTrue(target.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), "hello\n")
            # Default mode 0o644 (verified separately in test 7).


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
