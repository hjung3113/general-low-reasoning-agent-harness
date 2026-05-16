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


class TestAtomicWriteTextMode(unittest.TestCase):
    def test_atomic_write_text_default_mode_is_0o644(self) -> None:
        import stat
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "out.txt"
            atomic_io.atomic_write_text(target, "x")
            self.assertEqual(target.stat().st_mode & 0o777, 0o644)
            # Explicit mode override honored.
            target2 = Path(tmpdir) / "out2.txt"
            atomic_io.atomic_write_text(target2, "x", mode=0o600)
            self.assertEqual(target2.stat().st_mode & 0o777, 0o600)


class TestAtomicWriteTextPreconditions(unittest.TestCase):
    def test_atomic_write_text_rejects_missing_parent_directory(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "does-not-exist" / "out.txt"
            with self.assertRaises(Exception) as ctx:
                atomic_io.atomic_write_text(target, "x")
            # Message should name the missing parent dir.
            self.assertIn("does-not-exist", str(ctx.exception))

    def test_atomic_write_text_rejects_cross_filesystem_parent(self) -> None:
        """Spec §11 Required Behavior: detect parent on different filesystem via st_dev."""
        import os as _os
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "out.txt"
            real_stat = _os.stat
            parent_str = str(Path(tmpdir))

            def fake_stat(p, *a, **kw):
                result = real_stat(p, *a, **kw)
                # Pretend the temp file lives on a different device than the parent.
                if str(p) == parent_str:
                    class FakeStat:
                        st_dev = 999
                        st_mode = result.st_mode
                    return FakeStat()
                if str(p).startswith(parent_str + "/") and str(p).endswith(".tmp"):
                    class FakeStat2:
                        st_dev = 1
                        st_mode = result.st_mode
                    return FakeStat2()
                return result

            with mock.patch("lib.atomic_io.os.stat", side_effect=fake_stat):
                with self.assertRaises(RuntimeError) as ctx:
                    atomic_io.atomic_write_text(target, "x")
            msg = str(ctx.exception)
            self.assertIn("999", msg)
            self.assertIn("1", msg)

    def test_atomic_write_text_handles_disk_full_oserror(self) -> None:
        import errno
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "out.txt"
            target.write_text("ORIGINAL", encoding="utf-8")

            real_open = open

            def enospc_open(*args, **kwargs):
                f = real_open(*args, **kwargs)
                orig_write = f.write

                def faulting_write(s):
                    raise OSError(errno.ENOSPC, "No space left on device")

                f.write = faulting_write  # type: ignore[method-assign]
                return f

            with mock.patch("lib.atomic_io.tempfile.NamedTemporaryFile") as nt:
                # Build a real tempfile then wrap its write method.
                import tempfile as _tf

                def factory(**kw):
                    real = _tf._TemporaryFileWrapper(  # type: ignore[attr-defined]
                        file=open(Path(tmpdir) / "fake.tmp", "w", encoding="utf-8"),
                        name=str(Path(tmpdir) / "fake.tmp"),
                        delete=False,
                    )
                    real.write = lambda s: (_ for _ in ()).throw(  # type: ignore[assignment]
                        OSError(errno.ENOSPC, "No space left on device")
                    )
                    return real

                nt.side_effect = factory
                with self.assertRaises(OSError) as ctx:
                    atomic_io.atomic_write_text(target, "NEW")
                self.assertEqual(ctx.exception.errno, errno.ENOSPC)

            # Original unchanged.
            self.assertEqual(target.read_text(encoding="utf-8"), "ORIGINAL")
            # No leftover tempfile artifacts in parent dir.
            leftovers = [
                p.name for p in Path(tmpdir).iterdir() if p.name != "out.txt"
            ]
            self.assertEqual(leftovers, [], f"orphan tempfile not cleaned up: {leftovers}")
            # silence unused
            del enospc_open


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
