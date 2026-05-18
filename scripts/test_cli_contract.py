#!/usr/bin/env python3
"""CLI contract golden-file regression (T0-3 Task 11)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HARNESS = REPO / "scripts" / "harness.py"
FIX = Path(__file__).resolve().parent / "fixtures" / "cli_contract"
sys.path.insert(0, str(REPO / "scripts"))

NANOS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{9}Z$")


def _normalize(obj):
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize(v) for v in obj]
    if isinstance(obj, str):
        if NANOS_RE.fullmatch(obj):
            return "<NANOS>"
        if "@" in obj and " " not in obj:
            return "<EMAIL>"
    return obj


def _env(extra: dict[str, str] | None = None) -> dict:
    e = dict(os.environ)
    e["HARNESS_USER"] = "t@e.com"
    if extra:
        e.update(extra)
    return e


class CliContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".scratch").mkdir()
        (self.tmp / ".harness").mkdir()

    def _run(self, args, stdin=None, extra_env: dict[str, str] | None = None):
        return subprocess.run(
            [sys.executable, str(HARNESS), *args],
            cwd=self.tmp,
            capture_output=True,
            text=True,
            input=stdin,
            env=_env(extra_env),
        )

    def test_phase_set_discuss_matches_golden(self) -> None:
        r = self._run(["phase", "set", "discuss"])
        self.assertEqual(r.returncode, 0, r.stderr)
        got = _normalize(json.loads(r.stdout))
        expected = _normalize(json.loads((FIX / "phase_set_discuss.json").read_text()))
        self.assertEqual(got, expected)

    def test_phase_approve_refuses_non_tty_with_guidance(self) -> None:
        self._run(["phase", "set", "discuss"])
        self._run(["phase", "set", "plan"])
        r = self._run(["phase", "approve"])
        self.assertEqual(r.returncode, 6)
        self.assertEqual(r.stdout, "")
        self.assertIn("non-TTY caller", r.stderr)
        self.assertIn("real terminal", r.stderr)

    def test_machine_next_uses_high_level_contract(self) -> None:
        r = self._run(["next"], extra_env={"HARNESS_MACHINE": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(
            got,
            {
                "status": "ok",
                "phase": "discuss",
                "may_edit": False,
                "boundary": "plan-before-edit",
                "requires_user_approval": False,
                "next_command": "harness run",
                "next_user_prompt": None,
                "warnings": [],
            },
        )

    def test_machine_run_uses_high_level_contract(self) -> None:
        r = self._run(["run"], extra_env={"HARNESS_MACHINE": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got["status"], "ok")
        self.assertEqual(got["phase"], "plan")
        self.assertFalse(got["may_edit"])
        self.assertEqual(got["boundary"], "approval-required")
        self.assertTrue(got["requires_user_approval"])
        self.assertEqual(got["next_command"], None)
        self.assertIsInstance(got["next_user_prompt"], str)
        self.assertIn("approve", got["next_user_prompt"].lower())
        self.assertEqual(got["warnings"], [])

    def test_machine_check_uses_high_level_contract(self) -> None:
        r = self._run(["check"], extra_env={"HARNESS_MACHINE": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got["status"], "ok")
        self.assertEqual(got["phase"], "discuss")
        self.assertFalse(got["may_edit"])
        self.assertEqual(got["boundary"], "read-only")
        self.assertFalse(got["requires_user_approval"])
        self.assertEqual(got["next_command"], "harness next")
        self.assertEqual(got["next_user_prompt"], None)
        self.assertEqual(got["warnings"], [])

    def test_help_hides_advanced_commands_by_default(self) -> None:
        r = self._run(["--help"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("harness next", r.stdout)
        self.assertIn("harness run", r.stdout)
        self.assertIn("harness check", r.stdout)
        self.assertNotIn("phase", r.stdout)
        self.assertNotIn("approve-nonce", r.stdout)

    def test_bare_harness_prints_normal_help(self) -> None:
        r = self._run([])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("harness next", r.stdout)
        self.assertIn("harness run", r.stdout)
        self.assertIn("harness check", r.stdout)

    def test_normal_next_hides_phase_internals(self) -> None:
        r = self._run(["next"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("harness run", r.stdout)
        self.assertNotIn("phase", r.stdout)
        self.assertNotIn("approve-nonce", r.stdout)

    def test_normal_run_stops_for_approval_without_phase_command(self) -> None:
        r = self._run(["run"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("approve", r.stdout.lower())
        self.assertNotIn("harness phase", r.stdout)
        self.assertNotIn("approve-nonce", r.stdout)

    def test_machine_may_edit_requires_fresh_execute_approval(self) -> None:
        from lib.status_next_cli import _may_edit

        base = {
            "phase": "execute",
            "approved": True,
            "execute_attempt_started_at": "2026-05-18T10:00:00.000000000Z",
        }
        self.assertTrue(_may_edit({**base, "approved_at": "2026-05-18T10:00:00.000000001Z"}))
        self.assertFalse(_may_edit({**base, "approved_at": "2026-05-18T09:59:59.999999999Z"}))
        self.assertFalse(_may_edit({**base, "phase": "plan"}))


if __name__ == "__main__":
    unittest.main()
