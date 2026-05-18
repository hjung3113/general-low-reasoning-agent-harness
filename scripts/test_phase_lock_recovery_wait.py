#!/usr/bin/env python3
"""Tests for acquire_primary max_recovery_wait_s kwarg (02d Group β fix β-1)."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import phase_lock  # noqa: E402


class TestMaxRecoveryWaitKwarg(unittest.TestCase):
    """Verify max_recovery_wait_s defaulting and override behaviour."""

    def _make_scratch(self, tmp_path: Path) -> Path:
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        return scratch

    def test_default_uses_min_of_timeout_and_cap(self) -> None:
        """Omitting max_recovery_wait_s with timeout_s=5 → effective cap=5 in error msg."""
        import tempfile

        # Each fake sleep returns a value large enough to push recovery_seen
        # past the effective cap (min(5, 30)==5) in a single call.
        def fake_sleep(secs: float) -> None:  # noqa: ANN001
            pass  # no-op; recovery_seen accumulates via backoff doubling

        with tempfile.TemporaryDirectory() as tmpdir:
            scratch = Path(tmpdir)
            recovery = scratch / phase_lock.RECOVERY_NAME
            recovery.touch()

            # Make backoff large so recovery_seen exceeds cap quickly.
            _orig_backoff_max = phase_lock.BACKOFF_MAX_S

            with patch.object(phase_lock, "BACKOFF_INITIAL_S", 6.0), patch.object(
                phase_lock, "BACKOFF_MAX_S", 6.0
            ), patch.object(time, "sleep", fake_sleep):
                with self.assertRaises(phase_lock.LockTimeoutError) as ctx:
                    phase_lock.acquire_primary(scratch, timeout_s=60.0)

            # Effective cap = min(60, 30) = 30; error message must mention 30.0.
            err = str(ctx.exception)
            self.assertIn("30.0", err)

    def test_default_smaller_timeout_caps_recovery_wait(self) -> None:
        """With timeout_s=5 (< 30), effective cap is 5.0."""
        import tempfile

        def fake_sleep(secs: float) -> None:  # noqa: ANN001
            pass

        with tempfile.TemporaryDirectory() as tmpdir:
            scratch = Path(tmpdir)
            recovery = scratch / phase_lock.RECOVERY_NAME
            recovery.touch()

            with patch.object(phase_lock, "BACKOFF_INITIAL_S", 6.0), patch.object(
                phase_lock, "BACKOFF_MAX_S", 6.0
            ), patch.object(time, "sleep", fake_sleep):
                with self.assertRaises(phase_lock.LockTimeoutError) as ctx:
                    phase_lock.acquire_primary(scratch, timeout_s=5.0)

            # Effective cap = min(5.0, 30.0) = 5.0; error message mentions 5.0.
            err = str(ctx.exception)
            self.assertIn("5.0", err)

    def test_explicit_max_recovery_wait_overrides_timeout(self) -> None:
        """Explicit max_recovery_wait_s=2 with timeout_s=10 → cap is 2."""
        import tempfile

        sleep_calls: list[float] = []

        def fake_sleep(secs: float) -> None:  # noqa: ANN001
            sleep_calls.append(secs)

        with tempfile.TemporaryDirectory() as tmpdir:
            scratch = Path(tmpdir)
            recovery = scratch / phase_lock.RECOVERY_NAME
            recovery.touch()

            _start = time.monotonic()

            def fake_monotonic() -> float:  # noqa: ANN001
                if sleep_calls:
                    return _start + 3.0  # within timeout_s=10 but after 1 sleep
                return _start

            with patch.object(time, "sleep", fake_sleep), patch.object(
                time, "monotonic", fake_monotonic
            ):
                with self.assertRaises(phase_lock.LockTimeoutError) as ctx:
                    phase_lock.acquire_primary(
                        scratch, timeout_s=10.0, max_recovery_wait_s=2.0
                    )

            # The effective cap is 2.0; error message must mention it.
            self.assertIn("2.0", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
