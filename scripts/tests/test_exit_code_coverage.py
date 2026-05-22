#!/usr/bin/env python3
"""Smoke test: exit codes 2/3/5/6/7/8 all reachable per Artifact 1 (T0-3 Task 12)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HARNESS = REPO / "scripts" / "harness.py"


def run(args, cwd, stdin=None):
    env = dict(os.environ)
    env["HARNESS_USER"] = "t@e"
    return subprocess.run(
        [sys.executable, str(HARNESS), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        input=stdin,
        env=env,
    )


class ExitCodeCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".scratch").mkdir()
        (self.tmp / ".harness").mkdir()

    def test_exit_2_invalid_transition(self) -> None:
        run(["phase", "set", "discuss"], cwd=self.tmp)
        run(["phase", "set", "plan"], cwd=self.tmp)
        r = run(["phase", "set", "execute"], cwd=self.tmp)
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_exit_3_lockfile(self) -> None:
        (self.tmp / ".harness" / "session.lock").write_text(json.dumps(
            {"pid": os.getpid(), "hostname": "h", "started_at_utc": "x",
             "harness_version": "v", "boot_id": None}
        ))
        r = run(["phase", "set", "discuss"], cwd=self.tmp)
        self.assertEqual(r.returncode, 3, r.stderr)

    def test_exit_5_unparseable(self) -> None:
        (self.tmp / ".scratch" / "phase-state.json").write_text("not json")
        r = run(["phase", "set", "discuss"], cwd=self.tmp)
        self.assertEqual(r.returncode, 5, r.stderr)

    def test_exit_17_non_tty_approve(self) -> None:
        # v0.9.0 speed-bump: phase approve from non-TTY subprocess now returns
        # EXIT_HUMAN_CONFIRMATION_REQUIRED (17). The TTY gate fires before any
        # phase/identity checks. Prior name was test_exit_6_wrong_phase; that
        # tested the old non-TTY guard which returned 6.
        run(["phase", "set", "discuss"], cwd=self.tmp)
        r = run(["phase", "approve"], cwd=self.tmp)
        self.assertEqual(r.returncode, 17, r.stderr)

    def test_exit_7_staleness_uncertain(self) -> None:
        (self.tmp / ".harness" / "session.lock").write_text(json.dumps(
            {"hostname": "h", "started_at_utc": "x",
             "harness_version": "v", "boot_id": None}
        ))
        r = run(["session", "unlock"], cwd=self.tmp)
        self.assertEqual(r.returncode, 7, r.stderr)

    def test_exit_8_timestamp_out_of_range(self) -> None:
        run(["phase", "set", "discuss"], cwd=self.tmp)
        run(["phase", "set", "plan"], cwd=self.tmp)
        r = run(["phase", "approve", "--at", "2000-01-01T00:00:00.000000000Z"], cwd=self.tmp)
        self.assertEqual(r.returncode, 8, r.stderr)


if __name__ == "__main__":
    unittest.main()
