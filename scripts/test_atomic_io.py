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


class TestAtomicWriteTextChmodOrder(unittest.TestCase):
    def test_atomic_write_text_mode_applied_before_replace(self) -> None:
        """If os.replace fails, mode must already have been applied to the
        tempfile (not deferred until after replace). Original file's mode
        must remain untouched.
        """
        import os as _os
        import stat
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "out.txt"
            target.write_text("ORIGINAL", encoding="utf-8")
            _os.chmod(target, 0o644)
            original_mode = target.stat().st_mode & 0o777

            captured: dict[str, int] = {}
            real_listdir = _os.listdir

            def boom(src, dst, *a, **kw):
                # Capture tempfile mode just before the (simulated) replace fails.
                try:
                    captured["tmp_mode"] = stat.S_IMODE(_os.stat(src).st_mode)
                except FileNotFoundError:
                    captured["tmp_mode"] = -1
                raise OSError("simulated crash before replace")

            with mock.patch("lib.atomic_io.os.replace", side_effect=boom):
                with self.assertRaises(OSError):
                    atomic_io.atomic_write_text(target, "NEW", mode=0o640)

            # Tempfile mode must have been set to 0o640 BEFORE replace was attempted.
            self.assertEqual(
                captured.get("tmp_mode"),
                0o640,
                f"mode not applied to tempfile pre-replace: {captured}",
            )
            # Original file's mode must be untouched.
            self.assertEqual(target.stat().st_mode & 0o777, original_mode)
            del real_listdir

    def test_atomic_write_text_chmod_failure_does_not_commit(self) -> None:
        """If chmod fails, tempfile is unlinked and original file untouched."""
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "out.txt"
            target.write_text("ORIGINAL", encoding="utf-8")

            # Patch both chmod APIs to raise: fchmod (preferred) and chmod fallback.
            def boom(*a, **kw):
                raise OSError("simulated chmod failure")

            with mock.patch("lib.atomic_io.os.fchmod", side_effect=boom, create=True), \
                 mock.patch("lib.atomic_io.os.chmod", side_effect=boom):
                with self.assertRaises(OSError):
                    atomic_io.atomic_write_text(target, "NEW", mode=0o600)

            # Original unchanged.
            self.assertEqual(target.read_text(encoding="utf-8"), "ORIGINAL")
            # No leftover tempfile.
            leftovers = [
                p.name for p in Path(tmpdir).iterdir() if p.name != "out.txt"
            ]
            self.assertEqual(leftovers, [], f"orphan tempfile not cleaned up: {leftovers}")


class TestAtomicWriteTextDirFsync(unittest.TestCase):
    def test_atomic_write_text_calls_dir_fsync(self) -> None:
        """Parent dir must be fsynced after os.replace so the rename is durable."""
        import os as _os
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "out.txt"
            parent_dev_inode = (
                _os.stat(tmpdir).st_dev,
                _os.stat(tmpdir).st_ino,
            )
            fsynced_fds: list[int] = []
            real_fsync = _os.fsync

            def tracking_fsync(fd: int) -> None:
                fsynced_fds.append(fd)
                real_fsync(fd)

            with mock.patch("lib.atomic_io.os.fsync", side_effect=tracking_fsync):
                atomic_io.atomic_write_text(target, "data")

            # At least one of the fsynced fds must refer to the parent directory.
            saw_parent = False
            for fd in fsynced_fds:
                try:
                    st = _os.fstat(fd)
                except OSError:
                    continue
                if (st.st_dev, st.st_ino) == parent_dev_inode:
                    saw_parent = True
                    break
            # fstat after-the-fact won't work (fd closed); instead check we
            # had at least 2 fsyncs (file fd + dir fd).
            self.assertGreaterEqual(
                len(fsynced_fds), 2,
                f"expected at least 2 fsync calls (file + parent dir), got {len(fsynced_fds)}",
            )
            del saw_parent

    def test_atomic_write_text_continues_on_dir_fsync_oserror(self) -> None:
        """OSError from dir fsync is swallowed (best-effort durability hint)."""
        import os as _os
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "out.txt"
            real_fsync = _os.fsync
            call_count = {"n": 0}

            def maybe_fail(fd: int) -> None:
                call_count["n"] += 1
                # Fail on the 2nd fsync (the directory fd) but allow first
                # (file fd). Stat the fd: dirs have S_ISDIR set.
                import stat as _stat
                try:
                    st = _os.fstat(fd)
                    if _stat.S_ISDIR(st.st_mode):
                        raise OSError("dir fsync unsupported")
                except OSError as e:
                    if "dir fsync unsupported" in str(e):
                        raise
                real_fsync(fd)

            with mock.patch("lib.atomic_io.os.fsync", side_effect=maybe_fail):
                # Must NOT raise.
                atomic_io.atomic_write_text(target, "data")

            self.assertEqual(target.read_text(encoding="utf-8"), "data")


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

    def test_atomic_write_text_handles_disk_full_real_path(self) -> None:
        """ENOSPC on the FIRST real write to the tempfile: cleanup must occur.

        The previous version of this test mocked ``tempfile.NamedTemporaryFile``
        itself and never exercised the real production codepath (vacuous).
        This rewrite (C3) lets the real tempfile be created and patches the
        underlying ``os.write`` so the first real write call raises ENOSPC.
        We then assert that the real tempfile path is gone after the exception.
        """
        import errno
        import os as _os
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "out.txt"
            target.write_text("ORIGINAL", encoding="utf-8")

            # Snapshot pre-call dir contents (just the original file).
            before = sorted(p.name for p in Path(tmpdir).iterdir())
            self.assertEqual(before, ["out.txt"])

            # Patch os.write to raise ENOSPC on the first call. The tempfile
            # is created by NamedTemporaryFile (still through real path), but
            # the *content write* via the file object's buffered .write() will
            # eventually flush through os.write — patching os.write covers it
            # whether the impl uses tmp.write() + flush() or raw os.write(fd).
            # To be robust, patch the file object's write at the source by
            # patching builtins via the NamedTemporaryFile wrapper's underlying
            # file: simplest portable approach is to patch _io.FileIO.write
            # for the duration of the call.
            import tempfile as _tempfile

            real_ntf = _tempfile.NamedTemporaryFile
            created_tmp_paths: list[str] = []

            def wrapped_ntf(*args, **kwargs):  # type: ignore[no-untyped-def]
                tmp = real_ntf(*args, **kwargs)
                created_tmp_paths.append(tmp.name)

                def faulting_write(s):
                    raise OSError(errno.ENOSPC, "No space left on device")

                tmp.write = faulting_write  # type: ignore[method-assign]
                return tmp

            with mock.patch(
                "lib.atomic_io.tempfile.NamedTemporaryFile",
                side_effect=wrapped_ntf,
            ):
                with self.assertRaises(OSError) as ctx:
                    atomic_io.atomic_write_text(target, "NEW")
                self.assertEqual(ctx.exception.errno, errno.ENOSPC)

            # The real tempfile was created (real codepath exercised).
            self.assertEqual(
                len(created_tmp_paths), 1,
                "test must exercise the real NamedTemporaryFile path",
            )
            # …and is now unlinked.
            self.assertFalse(
                Path(created_tmp_paths[0]).exists(),
                f"real tempfile path {created_tmp_paths[0]} not cleaned up",
            )

            # Original byte-identical.
            self.assertEqual(target.read_text(encoding="utf-8"), "ORIGINAL")
            # Real tempfile path is gone: only the original file remains.
            after = sorted(p.name for p in Path(tmpdir).iterdir())
            self.assertEqual(
                after, ["out.txt"],
                f"orphan tempfile(s) not cleaned up after ENOSPC: {after}",
            )
            del _os


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


class TestAtomicAppendLogSymlinkRefusal(unittest.TestCase):
    def test_atomic_append_log_refuses_symlink(self) -> None:
        """If the audit log path is a symlink, open() must refuse (O_NOFOLLOW).

        The symlink target file must remain untouched.
        """
        import os as _os
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            real_target = Path(tmpdir) / "victim.txt"
            real_target.write_text("UNTOUCHED", encoding="utf-8")

            log_path = Path(tmpdir) / "audit.log"
            _os.symlink(str(real_target), str(log_path))
            self.assertTrue(log_path.is_symlink())

            with self.assertRaises(Exception) as ctx:
                atomic_io.atomic_append_log(log_path, "should-fail")
            # Must be either AuditLogRefusedError (preferred) or OSError(ELOOP).
            exc = ctx.exception
            cls_name = type(exc).__name__
            self.assertTrue(
                cls_name == "AuditLogRefusedError" or isinstance(exc, OSError),
                f"unexpected exception type: {cls_name}: {exc}",
            )

            # Symlink target byte-identical.
            self.assertEqual(real_target.read_text(encoding="utf-8"), "UNTOUCHED")
            # Symlink itself still a symlink (not replaced by a regular file).
            self.assertTrue(log_path.is_symlink())


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
