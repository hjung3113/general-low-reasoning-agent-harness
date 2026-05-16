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
sys.path.insert(0, str(Path(__file__).resolve().parent))


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


class PhaseSetMalformedStateTests(unittest.TestCase):
    """T1-M-C2: phase verbs must route state reads through load_state_json
    so malformed input exits 5 with the structured diagnostic instead of
    the ad-hoc f-string message."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".scratch").mkdir()
        (self.tmp / ".harness").mkdir()

    def test_phase_set_on_malformed_state_exits_5_with_diagnostic(self) -> None:
        (self.tmp / ".scratch/phase-state.json").write_text(
            '{"phase":', encoding="utf-8"
        )
        r = run_harness(["phase", "set", "discuss"], cwd=self.tmp)
        self.assertEqual(r.returncode, 5, r.stderr)
        # state_diagnostics emits "error: <path> is unparseable at line X:col Y..."
        self.assertIn("is unparseable", r.stderr)
        self.assertIn("phase-state.json", r.stderr)
        # Structured diagnostic format from state_diagnostics: "line N:col M"
        # (the legacy ad-hoc message uses "line N column M" which has no colon).
        self.assertRegex(r.stderr, r"line\s+\d+:col\s*\d+")
        # And remediation hint sentence (default template):
        self.assertIn("fix the JSON", r.stderr)


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

    def test_invalid_transition_message_matches_artifact_1_template(self) -> None:
        """C3: stderr must match Artifact 1 template byte-exactly for all 3 remediations."""
        # Case 1: needs_approval (plan -> execute without approve).
        run_harness(["phase", "set", "discuss"], cwd=self.tmp)
        run_harness(["phase", "set", "plan"], cwd=self.tmp)
        r = run_harness(["phase", "set", "execute"], cwd=self.tmp)
        self.assertEqual(r.returncode, 2)
        expected = (
            "error: cannot set phase=execute from phase=plan "
            "(see ADR-001 transition table). "
            "Run 'harness phase approve' first."
        )
        self.assertEqual(r.stderr.strip(), expected)

        # Case 2: needs_reset (execute -> plan without --reset-approval).
        # Get into execute first.
        run_harness(["phase", "approve"], cwd=self.tmp)
        run_harness(["phase", "set", "execute"], cwd=self.tmp)
        r = run_harness(["phase", "set", "plan"], cwd=self.tmp)
        self.assertEqual(r.returncode, 2)
        expected = (
            "error: cannot set phase=plan from phase=execute "
            "(see ADR-001 transition table). "
            "Pass --reset-approval to clear prior approval and proceed."
        )
        self.assertEqual(r.stderr.strip(), expected)

        # Case 3: undefined (discuss -> done).
        run_harness(["phase", "set", "discuss", "--reset-approval"], cwd=self.tmp)
        r = run_harness(["phase", "set", "done"], cwd=self.tmp)
        self.assertEqual(r.returncode, 2)
        expected = (
            "error: cannot set phase=done from phase=discuss "
            "(see ADR-001 transition table). "
            "Transition is undefined; choose discuss/plan/execute/done as the next step."
        )
        self.assertEqual(r.stderr.strip(), expected)

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

    # ----- C2: session unlock must write an audit entry on every removal path -----

    def _last_audit_entry(self) -> dict:
        audit = self.tmp / ".harness" / "audit.log"
        self.assertTrue(audit.exists(), "audit.log not created by session unlock")
        lines = [ln for ln in audit.read_text().splitlines() if ln.strip()]
        self.assertTrue(lines, "audit.log empty")
        return json.loads(lines[-1])

    def test_session_unlock_audits_normal_path(self) -> None:
        """Dead-pid unlock writes an audit entry with the stolen payload."""
        payload = {"pid": 999999, "hostname": "h", "started_at_utc": "x",
                   "harness_version": "v", "boot_id": None}
        self.lock.write_text(json.dumps(payload))
        r = run_harness(["session", "unlock"], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        entry = self._last_audit_entry()
        self.assertEqual(entry["verb"], "session.unlock")
        self.assertFalse(entry["args"]["force"])
        self.assertEqual(entry["args"]["stolen_payload"]["pid"], 999999)

    def test_session_unlock_audits_force_path(self) -> None:
        """--force unlock writes an audit entry with force=true."""
        payload = {"pid": os.getpid(), "hostname": "h", "started_at_utc": "x",
                   "harness_version": "v", "boot_id": None}
        self.lock.write_text(json.dumps(payload))
        r = run_harness(["session", "unlock", "--force"], cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        entry = self._last_audit_entry()
        self.assertEqual(entry["verb"], "session.unlock")
        self.assertTrue(entry["args"]["force"])
        self.assertEqual(entry["args"]["stolen_payload"]["pid"], os.getpid())

    def test_session_unlock_audits_boot_id_mismatch_path(self) -> None:
        """boot_id-mismatch auto-unlock writes an audit entry."""
        # Use a sentinel boot_id that cannot match any real host.
        payload = {"pid": os.getpid(), "hostname": "h", "started_at_utc": "x",
                   "harness_version": "v", "boot_id": "stale-boot-id-from-old-kernel"}
        self.lock.write_text(json.dumps(payload))
        r = run_harness(["session", "unlock"], cwd=self.tmp)
        # Boot-id mismatch is only meaningful when current boot_id is non-None.
        # On macOS/Linux read_boot_id returns a real value with C5/M1 fixes.
        # Skip silently if current host returns None (cannot trigger this path).
        from lib.session import read_boot_id
        if read_boot_id() is None:
            self.skipTest("current host has no boot_id; mismatch path unreachable")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.lock.exists())
        entry = self._last_audit_entry()
        self.assertEqual(entry["verb"], "session.unlock")
        self.assertEqual(entry["args"]["stolen_payload"]["boot_id"],
                         "stale-boot-id-from-old-kernel")


if __name__ == "__main__":
    unittest.main()
