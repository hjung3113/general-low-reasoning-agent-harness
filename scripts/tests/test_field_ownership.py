#!/usr/bin/env python3
"""Field ownership matrix enforcement (T0-3 Task 9, ADR-003b Artifact 3)."""

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


def run_harness(args, cwd):
    env = dict(os.environ)
    env["HARNESS_USER"] = "t@e"
    return subprocess.run(
        [sys.executable, str(HARNESS), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


class FieldOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".scratch").mkdir()
        (self.tmp / ".harness").mkdir()
        seed = {
            "summary": "original",
            "verification": ["python3 -m pytest"],
            "acceptance_criteria": ["x"],
            "automation_mode": "manual",
            "auto_selected": [],
            "allowed_paths": ["**"],
            "blocked_paths": [],
            "notes": ["n"],
        }
        (self.tmp / ".scratch" / "phase-state.json").write_text(
            json.dumps(seed, indent=2, sort_keys=True) + "\n"
        )

    def test_phase_set_does_not_touch_user_fields(self) -> None:
        r = run_harness(["phase", "set", "discuss"], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        state = json.loads((self.tmp / ".scratch" / "phase-state.json").read_text())
        self.assertEqual(state["summary"], "original")
        self.assertEqual(state["verification"], ["python3 -m pytest"])
        self.assertEqual(state["acceptance_criteria"], ["x"])
        self.assertEqual(state["notes"], ["n"])
        self.assertEqual(state["allowed_paths"], ["**"])

    def test_phase_set_with_summary_flag_opts_in(self) -> None:
        r = run_harness(["phase", "set", "discuss", "--summary", "new summary"], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        state = json.loads((self.tmp / ".scratch" / "phase-state.json").read_text())
        self.assertEqual(state["summary"], "new summary")

    def test_phase_approve_does_not_touch_user_fields(self) -> None:
        run_harness(["phase", "set", "discuss"], cwd=self.tmp)
        run_harness(["phase", "set", "plan"], cwd=self.tmp)
        r = run_harness(["phase", "approve"], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        state = json.loads((self.tmp / ".scratch" / "phase-state.json").read_text())
        self.assertEqual(state["summary"], "original")
        self.assertEqual(state["verification"], ["python3 -m pytest"])


if __name__ == "__main__":
    unittest.main()
