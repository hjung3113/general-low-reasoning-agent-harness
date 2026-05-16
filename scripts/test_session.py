#!/usr/bin/env python3
"""Tests for scripts/lib/session.py — session lockfile (T0-3 G1-B)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.session import acquire_lock, release_lock, read_lock_payload, is_pid_alive, LockfileExists, read_boot_id  # noqa: E402
from lib import session as session_mod  # noqa: E402


class LockfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.lock_path = self.tmp / ".harness" / "session.lock"

    def test_acquire_creates_lockfile_with_payload(self) -> None:
        with acquire_lock(lock_path=self.lock_path):
            self.assertTrue(self.lock_path.exists())
            payload = json.loads(self.lock_path.read_text())
            self.assertEqual(payload["pid"], os.getpid())
            self.assertIn("hostname", payload)
            self.assertIn("started_at_utc", payload)
            self.assertIn("harness_version", payload)
            self.assertIn("boot_id", payload)

    def test_release_removes_file(self) -> None:
        with acquire_lock(lock_path=self.lock_path):
            pass
        self.assertFalse(self.lock_path.exists())

    def test_concurrent_acquire_raises_lockfile_exists(self) -> None:
        with acquire_lock(lock_path=self.lock_path):
            with self.assertRaises(LockfileExists):
                with acquire_lock(lock_path=self.lock_path):
                    pass  # pragma: no cover

    def test_is_pid_alive_self(self) -> None:
        self.assertTrue(is_pid_alive(os.getpid()))

    def test_is_pid_alive_nonexistent(self) -> None:
        self.assertFalse(is_pid_alive(999999))

    def test_read_lock_payload_roundtrip(self) -> None:
        with acquire_lock(lock_path=self.lock_path):
            payload = read_lock_payload(self.lock_path)
            self.assertEqual(payload["pid"], os.getpid())

    def test_atexit_cleans_lock_on_normal_exit(self) -> None:
        # T0-3 amendment #4: assert atexit-path removes lockfile on clean exit.
        script = (
            "import sys\n"
            f"sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n"
            "from lib.session import acquire_lock\n"
            "cm = acquire_lock.__wrapped__ if hasattr(acquire_lock, '__wrapped__') else None\n"
            "lp = " + repr(str(self.lock_path)) + "\n"
            "from pathlib import Path\n"
            "with acquire_lock(lock_path=Path(lp)):\n"
            "    pass\n"
        )
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(self.lock_path.exists())

    def test_read_boot_id_linux_unchanged(self) -> None:
        """M1: Linux path still reads /proc/sys/kernel/random/boot_id."""
        from unittest import mock
        with mock.patch.object(session_mod.platform, "system", return_value="Linux"):
            with mock.patch.object(
                session_mod.Path, "read_text", return_value="deadbeef-1234\n"
            ):
                self.assertEqual(read_boot_id(), "deadbeef-1234")

    def test_read_boot_id_macos_returns_sysctl_parsed(self) -> None:
        """M1: macOS parses 'kern.boottime' sysctl into darwin-boot-{sec}."""
        from unittest import mock

        class FakeCompleted:
            returncode = 0
            stdout = "{ sec = 1777386969, usec = 3543 } Tue Apr 28 23:36:09 2026\n"

        with mock.patch.object(session_mod.platform, "system", return_value="Darwin"):
            with mock.patch.object(
                session_mod.subprocess, "run", return_value=FakeCompleted()
            ):
                self.assertEqual(read_boot_id(), "darwin-boot-1777386969")

    def test_acquire_lock_unlinks_on_write_failure(self) -> None:
        """M2: a write failure during acquire_lock must remove the partial lockfile."""
        from unittest import mock

        real_write = os.write
        call_count = {"n": 0}

        def failing_write(fd, data):
            call_count["n"] += 1
            raise OSError(28, "No space left on device")

        with mock.patch.object(os, "write", side_effect=failing_write):
            with self.assertRaises(OSError):
                with acquire_lock(lock_path=self.lock_path):
                    pass  # pragma: no cover
        self.assertFalse(
            self.lock_path.exists(),
            "lockfile must be removed when payload write fails",
        )

    def test_read_boot_id_other_returns_none(self) -> None:
        from unittest import mock
        with mock.patch.object(session_mod.platform, "system", return_value="FreeBSD"):
            self.assertIsNone(read_boot_id())

    def test_sigint_during_acquire_releases_lock(self) -> None:
        script = (
            "import sys, time\n"
            f"sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n"
            "from pathlib import Path\n"
            "from lib.session import acquire_lock\n"
            "lp = Path(" + repr(str(self.lock_path)) + ")\n"
            "with acquire_lock(lock_path=lp):\n"
            "    time.sleep(30)\n"
        )
        proc = subprocess.Popen([sys.executable, "-c", script])
        for _ in range(80):
            if self.lock_path.exists():
                break
            time.sleep(0.05)
        self.assertTrue(self.lock_path.exists(), "lockfile never appeared")
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=5)
        self.assertFalse(self.lock_path.exists(), "SIGINT did not clean up lockfile")


if __name__ == "__main__":
    unittest.main()
