#!/usr/bin/env python3
"""Tests for drift warning emission in harness check (T0-3 Task 8)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HARNESS = REPO / "scripts" / "harness.py"


def _env() -> dict:
    e = dict(os.environ)
    e["HARNESS_USER"] = "t@e"
    return e


def run_harness(args, cwd, stdin=None):
    return subprocess.run(
        [sys.executable, str(HARNESS), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        input=stdin,
        env=_env(),
    )


class DriftTemplateTests(unittest.TestCase):
    """The drift detector is exposed via the harness check codepath.

    For test simplicity (and because the existing harness check runs many
    other checks against the repo root that are not relevant here), we
    exercise the drift detector directly through ``lib.check_drift``.
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".scratch").mkdir()
        (self.tmp / ".harness").mkdir()
        sys.path.insert(0, str(Path(__file__).resolve().parent))

    def _call_drift(self):
        from lib.check import check_drift
        import io
        buf = io.StringIO()
        check_drift(self.tmp, stderr=buf)
        return buf.getvalue()

    def test_first_write_no_drift_warning(self) -> None:
        out = self._call_drift()
        self.assertNotIn("Drift detected", out)

    def test_no_state_no_drift_warning(self) -> None:
        (self.tmp / ".harness" / "audit.log").write_text(
            json.dumps({"index": 1, "after_sha256": "x" * 64}) + "\n"
        )
        out = self._call_drift()
        self.assertNotIn("Drift detected", out)

    def test_drift_warning_emitted_after_manual_edit(self) -> None:
        run_harness(["phase", "set", "discuss"], cwd=self.tmp)
        state_path = self.tmp / ".scratch" / "phase-state.json"
        d = json.loads(state_path.read_text())
        d["summary"] = "edited by hand"
        state_path.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")
        out = self._call_drift()
        self.assertIn("Drift detected", out)
        self.assertIn("does not match the last audit entry", out)

    def test_drift_template_no_phase_audit_reference(self) -> None:
        run_harness(["phase", "set", "discuss"], cwd=self.tmp)
        state_path = self.tmp / ".scratch" / "phase-state.json"
        d = json.loads(state_path.read_text())
        d["summary"] = "x"
        state_path.write_text(json.dumps(d, sort_keys=True))
        out = self._call_drift()
        self.assertIn("Drift detected", out)
        self.assertNotIn("harness phase audit", out)
        self.assertIn("harness phase set", out)

    def test_matching_sha256_no_drift(self) -> None:
        run_harness(["phase", "set", "discuss"], cwd=self.tmp)
        out = self._call_drift()
        self.assertNotIn("Drift detected", out)


if __name__ == "__main__":
    unittest.main()
