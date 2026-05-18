#!/usr/bin/env python3
"""Tests for replace_with_retry DurableFsError → exit-3 mapping (02d Group β fix β-3)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import durable_fs, exitcodes, phase_autopilot, phase_txn  # noqa: E402

# Access the private helper under test.
_run_crash_recovery = phase_autopilot._run_crash_recovery


class TestReplaceWithRetryExitMapping(unittest.TestCase):
    """DurableFsError raised by phase_txn.recover → AutopilotResult(exit_code=3)."""

    def test_durable_fs_error_maps_to_exit3_state_replace_blocked(self) -> None:
        """Monkeypatch phase_txn.recover to raise DurableFsError; verify exit 3."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scratch = Path(tmpdir)
            audit_path = scratch / "audit.log"
            audit_path.touch()

            # Simulate a DurableFsError from inside phase_txn.recover.
            def raise_durable_fs_error(*args: object, **kwargs: object) -> None:
                raise durable_fs.DurableFsError("simulated AV pin exhaustion")

            with patch.object(phase_txn, "recover", side_effect=raise_durable_fs_error):
                result = _run_crash_recovery(
                    scratch=scratch,
                    audit_path=audit_path,
                    lock=object(),  # any sentinel — lock contract check is in phase_txn
                )

            self.assertIsNotNone(result)
            assert result is not None  # mypy narrowing
            self.assertEqual(result.exit_code, exitcodes.EXIT_SESSION_LOCKED)  # 3
            self.assertEqual(result.sub_reason, "state_replace_blocked")

    def test_non_durable_error_still_maps_to_exit14(self) -> None:
        """Generic exceptions still map to exit 14 crash_recovery_error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scratch = Path(tmpdir)
            audit_path = scratch / "audit.log"
            audit_path.touch()

            def raise_runtime_error(*args: object, **kwargs: object) -> None:
                raise RuntimeError("unexpected generic error")

            with patch.object(phase_txn, "recover", side_effect=raise_runtime_error):
                result = _run_crash_recovery(
                    scratch=scratch,
                    audit_path=audit_path,
                    lock=object(),
                )

            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result.exit_code, 14)
            self.assertEqual(result.sub_reason, "crash_recovery_error")


if __name__ == "__main__":
    unittest.main()
