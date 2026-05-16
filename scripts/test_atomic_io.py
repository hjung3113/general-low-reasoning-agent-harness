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

    def test_atomic_write_text_replaces_existing_atomically(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "out.txt"
            target.write_text("old-content", encoding="utf-8")
            atomic_io.atomic_write_text(target, "new-content")
            self.assertEqual(target.read_text(encoding="utf-8"), "new-content")
            # No leftover tempfile artifacts in parent dir.
            leftovers = [
                p.name
                for p in Path(tmpdir).iterdir()
                if p.name != "out.txt"
            ]
            self.assertEqual(leftovers, [], f"unexpected leftover files: {leftovers}")


class TestAtomicWriteTextCrashSafety(unittest.TestCase):
    def test_atomic_write_text_crash_between_temp_and_replace_preserves_original(self) -> None:
        """Spec §10 mandated crash-injection test: original survives a failed os.replace."""
        import os as _os
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "out.txt"
            target.write_text("ORIGINAL", encoding="utf-8")

            real_replace = _os.replace

            def boom(src, dst, *a, **kw):
                # Simulate crash after fsync but before replace lands.
                raise OSError("simulated crash between temp and replace")

            with mock.patch("lib.atomic_io.os.replace", side_effect=boom):
                with self.assertRaises(OSError):
                    atomic_io.atomic_write_text(target, "NEW")

            # Original file byte-identical.
            self.assertEqual(target.read_text(encoding="utf-8"), "ORIGINAL")
            # Orphan tempfile cleaned up.
            leftovers = [
                p.name for p in Path(tmpdir).iterdir() if p.name != "out.txt"
            ]
            self.assertEqual(leftovers, [], f"orphan tempfile not cleaned up: {leftovers}")
            # Silence linter for unused alias.
            del real_replace


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
