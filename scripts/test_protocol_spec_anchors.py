#!/usr/bin/env python3
"""Regression test for required anchors in docs/protocol-spec.md (T0-3 Task 10)."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


DOC = Path(__file__).resolve().parents[1] / "docs" / "protocol-spec.md"

REQUIRED_HEADINGS = {
    "cli-verbs": "CLI Verbs",
    "exit-codes": "Exit Codes",
    "audit-log-format": "Audit Log Format",
    "session-lockfile": "Session Lockfile",
    "field-ownership": "Field Ownership",
    "drift-warning": "Drift Warning",
    "verification-allowlist": "Verification Allowlist",
}


class ProtocolSpecAnchorsTests(unittest.TestCase):
    def test_doc_exists(self) -> None:
        self.assertTrue(DOC.exists(), f"{DOC} must exist")

    def test_all_required_headings_present(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        for anchor, heading in REQUIRED_HEADINGS.items():
            pattern = re.compile(
                rf"^#{{1,4}}\s+{re.escape(heading)}\s*$", re.M
            )
            self.assertTrue(
                pattern.search(text),
                msg=f"missing heading for anchor #{anchor}",
            )

    def test_drift_warning_excludes_phase_audit_verb(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        m = re.search(
            r"^##\s+Drift Warning\s*$(.*?)(?=^##\s+|\Z)",
            text,
            re.S | re.M,
        )
        self.assertIsNotNone(m, "Drift Warning section missing")
        self.assertNotIn("harness phase audit", m.group(1))


if __name__ == "__main__":
    unittest.main()
