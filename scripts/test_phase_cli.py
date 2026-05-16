#!/usr/bin/env python3
"""End-to-end tests for harness phase set / phase approve / session unlock (T0-3)."""

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


def run_harness(args, cwd, stdin=None):
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


class PhaseSetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".scratch").mkdir()
        (self.tmp / ".harness").mkdir()

    def test_set_discuss_from_none_succeeds_and_writes_audit(self) -> None:
        r = run_harness(["phase", "set", "discuss"], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["ok"], True)
        self.assertEqual(out["phase"], "discuss")
        self.assertIsNone(out["previous_phase"])
        self.assertEqual(out["audit_entry_index"], 1)
        audit_lines = (self.tmp / ".harness" / "audit.log").read_text().splitlines()
        self.assertEqual(len(audit_lines), 1)
        entry = json.loads(audit_lines[0])
        self.assertEqual(entry["verb"], "phase.set")
        self.assertEqual(entry["args"]["phase"], "discuss")

    def test_plan_to_execute_without_approval_exits_2(self) -> None:
        run_harness(["phase", "set", "discuss"], cwd=self.tmp)
        run_harness(["phase", "set", "plan"], cwd=self.tmp)
        r = run_harness(["phase", "set", "execute"], cwd=self.tmp)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("approve", r.stderr.lower())

    def test_plan_to_execute_with_approval_ok(self) -> None:
        run_harness(["phase", "set", "discuss"], cwd=self.tmp)
        run_harness(["phase", "set", "plan"], cwd=self.tmp)
        ap = run_harness(["phase", "approve"], cwd=self.tmp)
        self.assertEqual(ap.returncode, 0, ap.stderr)
        r = run_harness(["phase", "set", "execute"], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["phase"], "execute")

    def test_concurrent_phase_set_exits_3(self) -> None:
        lock = self.tmp / ".harness" / "session.lock"
        lock.write_text(json.dumps(
            {"pid": os.getpid(), "hostname": "h", "started_at_utc": "x",
             "harness_version": "v", "boot_id": None}
        ))
        r = run_harness(["phase", "set", "discuss"], cwd=self.tmp)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("active session detected", r.stderr)
        self.assertIn("harness session unlock", r.stderr)

    def test_unparseable_state_exits_5(self) -> None:
        (self.tmp / ".scratch" / "phase-state.json").write_text("not json")
        r = run_harness(["phase", "set", "discuss"], cwd=self.tmp)
        self.assertEqual(r.returncode, 5, r.stderr)
        self.assertIn("unparseable", r.stderr.lower())

    def test_unparseable_stdin_exits_5(self) -> None:
        run_harness(["phase", "set", "discuss"], cwd=self.tmp)
        r = run_harness(["phase", "set", "plan", "--stdin-json"], cwd=self.tmp, stdin="not json")
        self.assertEqual(r.returncode, 5, r.stderr)

    def test_stdin_json_writes_user_fields(self) -> None:
        run_harness(["phase", "set", "discuss"], cwd=self.tmp)
        r = run_harness(
            ["phase", "set", "plan", "--stdin-json"], cwd=self.tmp,
            stdin=json.dumps({"next_action": "Write tests"}),
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        state = json.loads((self.tmp / ".scratch" / "phase-state.json").read_text())
        self.assertEqual(state["next_action"], "Write tests")

    def test_summary_flag_writes_user_field(self) -> None:
        r = run_harness(["phase", "set", "discuss", "--summary", "new summary"], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        state = json.loads((self.tmp / ".scratch" / "phase-state.json").read_text())
        self.assertEqual(state["summary"], "new summary")


class PhaseApproveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".scratch").mkdir()
        (self.tmp / ".harness").mkdir()
        run_harness(["phase", "set", "discuss"], cwd=self.tmp)
        run_harness(["phase", "set", "plan"], cwd=self.tmp)

    def test_approve_in_plan_succeeds(self) -> None:
        r = run_harness(["phase", "approve"], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertTrue(out["approved"])
        self.assertIn("approved_at", out)
        self.assertIn("approved_by", out)
        state = json.loads((self.tmp / ".scratch" / "phase-state.json").read_text())
        self.assertTrue(state["approved"])

    def test_approve_in_done_exits_6(self) -> None:
        run_harness(["phase", "approve"], cwd=self.tmp)
        run_harness(["phase", "set", "execute"], cwd=self.tmp)
        run_harness(["phase", "approve"], cwd=self.tmp)
        run_harness(["phase", "set", "done"], cwd=self.tmp)
        r = run_harness(["phase", "approve"], cwd=self.tmp)
        self.assertEqual(r.returncode, 6, r.stderr)
        self.assertIn("cannot approve phase=done", r.stderr)

    def test_approve_in_discuss_exits_6(self) -> None:
        # Reset back to discuss using --reset-approval.
        run_harness(["phase", "set", "discuss", "--reset-approval"], cwd=self.tmp)
        r = run_harness(["phase", "approve"], cwd=self.tmp)
        self.assertEqual(r.returncode, 6, r.stderr)

    def test_approve_timestamp_out_of_range_exits_8(self) -> None:
        r = run_harness(
            ["phase", "approve", "--at", "2000-01-01T00:00:00.000000000Z"],
            cwd=self.tmp,
        )
        self.assertEqual(r.returncode, 8, r.stderr)
        self.assertIn("not within 24h", r.stderr)


class SessionUnlockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".harness").mkdir()
        self.lock = self.tmp / ".harness" / "session.lock"

    def test_no_lockfile_exits_0_silently(self) -> None:
        r = run_harness(["session", "unlock"], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "")

    def test_live_pid_refused_exit_3(self) -> None:
        self.lock.write_text(json.dumps(
            {"pid": os.getpid(), "hostname": "h", "started_at_utc": "x",
             "harness_version": "v", "boot_id": None}
        ))
        r = run_harness(["session", "unlock"], cwd=self.tmp)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertTrue(self.lock.exists())

    def test_force_removes_regardless(self) -> None:
        self.lock.write_text(json.dumps(
            {"pid": os.getpid(), "hostname": "h", "started_at_utc": "x",
             "harness_version": "v", "boot_id": None}
        ))
        r = run_harness(["session", "unlock", "--force"], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.lock.exists())

    def test_dead_pid_removes(self) -> None:
        self.lock.write_text(json.dumps(
            {"pid": 999999, "hostname": "h", "started_at_utc": "x",
             "harness_version": "v", "boot_id": None}
        ))
        r = run_harness(["session", "unlock"], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.lock.exists())

    def test_unparseable_lockfile_exits_5(self) -> None:
        self.lock.write_text("not json")
        r = run_harness(["session", "unlock"], cwd=self.tmp)
        self.assertEqual(r.returncode, 5, r.stderr)

    def test_print_does_not_remove(self) -> None:
        payload = {"pid": os.getpid(), "hostname": "h", "started_at_utc": "x",
                   "harness_version": "v", "boot_id": None}
        self.lock.write_text(json.dumps(payload))
        r = run_harness(["session", "unlock", "--print"], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(str(os.getpid()), r.stdout)
        self.assertTrue(self.lock.exists())

    def test_missing_pid_exits_7(self) -> None:
        self.lock.write_text(json.dumps(
            {"hostname": "h", "started_at_utc": "x", "harness_version": "v", "boot_id": None}
        ))
        r = run_harness(["session", "unlock"], cwd=self.tmp)
        self.assertEqual(r.returncode, 7, r.stderr)


if __name__ == "__main__":
    unittest.main()
