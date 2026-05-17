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


def _env() -> dict:
    e = dict(os.environ)
    e["HARNESS_USER"] = "t@e.com"
    return e


class CliContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".scratch").mkdir()
        (self.tmp / ".harness").mkdir()

    def _run(self, args, stdin=None):
        return subprocess.run(
            [sys.executable, str(HARNESS), *args],
            cwd=self.tmp,
            capture_output=True,
            text=True,
            input=stdin,
            env=_env(),
        )

    def test_phase_set_discuss_matches_golden(self) -> None:
        r = self._run(["phase", "set", "discuss"])
        self.assertEqual(r.returncode, 0, r.stderr)
        got = _normalize(json.loads(r.stdout))
        expected = _normalize(json.loads((FIX / "phase_set_discuss.json").read_text()))
        self.assertEqual(got, expected)

    def test_phase_approve_matches_golden(self) -> None:
        self._run(["phase", "set", "discuss"])
        self._run(["phase", "set", "plan"])
        r = self._run(["phase", "approve"])
        self.assertEqual(r.returncode, 0, r.stderr)
        got = _normalize(json.loads(r.stdout))
        expected = _normalize(json.loads((FIX / "phase_approve.json").read_text()))
        self.assertEqual(got, expected)


if __name__ == "__main__":
    unittest.main()
