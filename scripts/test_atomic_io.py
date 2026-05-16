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


class TestAtomicAppendLogBasic(unittest.TestCase):
    def test_atomic_append_log_creates_file_if_missing(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "audit.log"
            atomic_io.atomic_append_log(target, "first-line")
            self.assertTrue(target.exists())
            self.assertEqual(target.stat().st_mode & 0o777, 0o644)
            self.assertEqual(target.read_text(encoding="utf-8"), "first-line\n")

    def test_atomic_append_log_appends_without_truncating(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "audit.log"
            atomic_io.atomic_append_log(target, "A")
            atomic_io.atomic_append_log(target, "B")
            self.assertEqual(target.read_text(encoding="utf-8"), "A\nB\n")


class TestAtomicAppendLogErrors(unittest.TestCase):
    def test_atomic_append_log_refuses_oversized_line(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "audit.log"
            # 600 bytes payload (>512 even before trailing newline).
            payload = "x" * 600
            with self.assertRaises(ValueError) as ctx:
                atomic_io.atomic_append_log(target, payload)
            msg = str(ctx.exception)
            self.assertIn("512", msg)
            self.assertIn("601", msg)  # 600 + newline = 601
            # Log file must be unchanged (and not created).
            self.assertFalse(target.exists())

    def test_atomic_append_log_releases_lock_on_exception(self) -> None:
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "audit.log"
            atomic_io.atomic_append_log(target, "seed")
            # Make os.write raise; assert flock released and follow-up works.
            with mock.patch("lib.atomic_io.os.write", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    atomic_io.atomic_append_log(target, "should-fail")
            # Follow-up append succeeds (flock released).
            atomic_io.atomic_append_log(target, "after")
            contents = target.read_text(encoding="utf-8")
            self.assertIn("seed\n", contents)
            self.assertIn("after\n", contents)
            self.assertNotIn("should-fail", contents)


class TestAtomicAppendLogConcurrency(unittest.TestCase):
    def test_atomic_append_log_concurrent_writes_dont_tear(self) -> None:
        """N=8 threads x K=50 iterations each — every line structurally intact."""
        import tempfile
        import threading

        N = 8
        K = 50

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "audit.log"

            def worker(tag: int) -> None:
                for i in range(K):
                    # Each line uniquely tagged + checksum boundary tokens.
                    line = f"<tag={tag:02d}><i={i:03d}>" + ("." * 30) + "<end>"
                    atomic_io.atomic_append_log(target, line)

            threads = [threading.Thread(target=worker, args=(t,)) for t in range(N)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            lines = target.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), N * K, f"expected {N*K} lines, got {len(lines)}")
            # Every line is structurally intact: starts with <tag= and ends with <end>.
            for ln in lines:
                self.assertTrue(
                    ln.startswith("<tag=") and ln.endswith("<end>"),
                    f"torn line detected: {ln!r}",
                )

    def test_atomic_append_log_subprocess_sigkill_preserves_committed_lines(self) -> None:
        """Out-of-process integration test: SIGKILL mid-batch leaves valid lines parseable.

        Skipped on platforms without fork().
        """
        import os as _os
        import platform
        import signal
        import subprocess
        import sys as _sys
        import tempfile
        import time

        if platform.system() == "Windows":  # pragma: no cover
            self.skipTest("fork()/SIGKILL not available on Windows")

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "audit.log"
            scripts_dir = Path(__file__).resolve().parent
            child_prog = (
                "import sys, time\n"
                f"sys.path.insert(0, {str(scripts_dir)!r})\n"
                "from lib import atomic_io\n"
                "from pathlib import Path\n"
                f"target = Path({str(target)!r})\n"
                "for i in range(10000):\n"
                "    atomic_io.atomic_append_log(target, f'<i={i:05d}><end>')\n"
            )
            proc = subprocess.Popen([_sys.executable, "-c", child_prog])
            # Let the child make some progress.
            time.sleep(0.3)
            proc.send_signal(signal.SIGKILL)
            proc.wait()

            self.assertTrue(target.exists(), "child must have written at least once before SIGKILL")
            lines = target.read_text(encoding="utf-8").splitlines()
            self.assertGreater(len(lines), 0)
            for ln in lines:
                self.assertTrue(
                    ln.startswith("<i=") and ln.endswith("<end>"),
                    f"torn line after SIGKILL: {ln!r}",
                )


class TestGrepGate(unittest.TestCase):
    """Grep gate: no write_text() against managed state / operational paths in scripts/.

    Reads STATE_FILE_PATHS, OPERATIONAL_PATHS, INSTALL_PATHS from
    scripts/lib/operational_paths.py (sole declaration site per
    CONTRACT-PIN §2). Scans scripts/ recursively for lines matching
    `.write_text(` AND containing any tracked path literal. Each match
    is a violation.
    """

    @staticmethod
    def _gate_scan(scripts_root: Path, tracked_paths: tuple[str, ...]) -> list[str]:
        import re

        pattern = re.compile(r"\.write_text\(")
        violations: list[str] = []
        for py_path in scripts_root.rglob("*.py"):
            # Skip test files: they write fixture state under tempdirs, NOT
            # the real on-disk state paths. The atomicity contract applies
            # only to production writers (scripts/lib/*.py and CLI entries).
            # The synthetic-fixture test (test 13) exercises the gate against
            # a planted file in a temp scripts/ tree to prove the gate works.
            if py_path.name.startswith("test_"):
                continue
            try:
                text = py_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if not pattern.search(line):
                    continue
                for tracked in tracked_paths:
                    if tracked in line:
                        violations.append(f"{py_path}:{lineno}: {line.strip()} (matches {tracked})")
        return violations

    def test_grep_gate_clean_against_live_tree(self) -> None:
        from lib.operational_paths import (
            INSTALL_PATHS,
            OPERATIONAL_PATHS,
            STATE_FILE_PATHS,
        )

        tracked = STATE_FILE_PATHS + OPERATIONAL_PATHS + INSTALL_PATHS
        scripts_root = Path(__file__).resolve().parent
        violations = self._gate_scan(scripts_root, tracked)
        self.assertEqual(violations, [], f"grep-gate violations: {violations}")

    def test_grep_gate_fails_when_write_text_added_against_state_path(self) -> None:
        """Plant a synthetic violation in a temp scripts/ tree; gate must flag it."""
        import tempfile

        from lib.operational_paths import (
            INSTALL_PATHS,
            OPERATIONAL_PATHS,
            STATE_FILE_PATHS,
        )

        tracked = STATE_FILE_PATHS + OPERATIONAL_PATHS + INSTALL_PATHS

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_scripts = Path(tmpdir) / "scripts"
            fake_scripts.mkdir()
            planted = fake_scripts / "bad.py"
            planted.write_text(
                'from pathlib import Path\n'
                'Path(".scratch/phase-state.json").write_text("x")\n',
                encoding="utf-8",
            )
            violations = self._gate_scan(fake_scripts, tracked)
            self.assertTrue(violations, "grep gate failed to detect planted violation")
            self.assertTrue(
                any(".scratch/phase-state.json" in v for v in violations),
                f"expected violation naming the tracked path, got: {violations}",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
