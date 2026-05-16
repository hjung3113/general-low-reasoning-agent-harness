#!/usr/bin/env python3
"""Tests for scripts/lib/state_diagnostics.py (T1-M malformed-state helper).

Plan: .planning/phases/02b-hardening/plans/02b-09-T1-M-PLAN.md
Contract: .planning/phases/02b-hardening/CONTRACT-PIN.md §1, §3, §4, §5.1, §7
ADR: docs/adr/2026-05-16-hardening-bundle.md (ADR-005, ADR-003a Artifact 1)
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import state_diagnostics  # noqa: E402
from lib.exitcodes import EXIT_UNPARSEABLE_JSON  # noqa: E402


# ---------------------------------------------------------------------------
# load_state_json: happy + empty + truncated (plan tests 1-3)
# ---------------------------------------------------------------------------


class TestLoadStateJsonHappyPath(unittest.TestCase):
    def test_returns_dict_on_valid_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "phase-state.json"
            payload = {"phase": "discuss", "approved": False}
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = state_diagnostics.load_state_json(path)
            self.assertEqual(result, payload)


class TestLoadStateJsonTruncated(unittest.TestCase):
    def test_truncated_raises_systemexit_5_with_file_line_col(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "phase-state.json"
            # Truncated JSON: open string, no close brace.
            path.write_text('{"phase": "exec', encoding="utf-8")
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    state_diagnostics.load_state_json(path)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            err = buf.getvalue()
            self.assertIn(str(path), err)
            # JSONDecodeError supplies line + col; the diagnostic surfaces them.
            self.assertRegex(err, r"line\s+\d+")
            self.assertRegex(err, r"col\s*\d+|column\s*\d+")
            # Remediation hint sentence per ADR-003a / ADR-005.
            self.assertIn("fix the JSON", err)


class TestLoadStateJsonEmptyFile(unittest.TestCase):
    def test_empty_file_raises_systemexit_5(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "phase-state.json"
            path.write_text("", encoding="utf-8")
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    state_diagnostics.load_state_json(path)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            err = buf.getvalue()
            self.assertIn(str(path), err)
            self.assertIn("empty file", err.lower())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
