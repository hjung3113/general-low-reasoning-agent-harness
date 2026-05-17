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

    def test_drift_silent_when_state_trivial_and_audit_missing(self) -> None:
        """No audit.log + trivial init-shaped state -> silent (fresh repo)."""
        state_path = self.tmp / ".scratch" / "phase-state.json"
        state_path.write_text(
            json.dumps(
                {
                    "phase": "discuss",
                    "state_schema_version": 2,
                    "approved": False,
                    "updated_at": "1970-01-01T00:00:00Z",
                    "updated_by": "harness-init",
                    "automation_mode": "manual",
                    "auto_selected": [],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        out = self._call_drift()
        self.assertEqual(out, "")

    def test_drift_warns_when_audit_log_missing_and_state_nontrivial(self) -> None:
        """No audit.log + non-trivial state -> WARNING about disabled drift detection."""
        state_path = self.tmp / ".scratch" / "phase-state.json"
        state_path.write_text(
            json.dumps(
                {
                    "phase": "discuss",
                    "state_schema_version": 2,
                    "approved": False,
                    "summary": "hand-edited",
                    "updated_at": "2026-05-16T12:34:56.000000000Z",
                    "updated_by": "human@example",
                    "automation_mode": "manual",
                    "auto_selected": [],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        out = self._call_drift()
        self.assertIn("audit log missing", out)
        self.assertIn("drift detection disabled", out)
        self.assertIn("harness phase set", out)

    def test_drift_warns_when_audit_log_empty_and_state_nontrivial(self) -> None:
        """Empty audit.log treated same as missing."""
        (self.tmp / ".harness" / "audit.log").write_text("")
        state_path = self.tmp / ".scratch" / "phase-state.json"
        state_path.write_text(
            json.dumps(
                {
                    "phase": "plan",
                    "state_schema_version": 2,
                    "approved": False,
                    "summary": "edited",
                    "updated_at": "2026-05-16T12:34:56.000000000Z",
                    "updated_by": "human@example",
                    "automation_mode": "manual",
                    "auto_selected": [],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        out = self._call_drift()
        self.assertIn("audit log missing", out)


if __name__ == "__main__":
    unittest.main()
