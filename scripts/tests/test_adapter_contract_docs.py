#!/usr/bin/env python3
"""Contract checks for adapter command docs."""

from __future__ import annotations

import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


class AdapterContractDocsTests(unittest.TestCase):
    def test_autopilot_command_docs_use_current_machine_contract(self) -> None:
        command_files = [
            REPO / ".opencode/commands/fsd-run-all.md",
            REPO / ".opencode/commands/fsd-run-phase.md",
            REPO / ".roo/commands/fsd-run-all.md",
            REPO / ".roo/commands/fsd-run-phase.md",
        ]
        for path in command_files:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertNotIn("requires_human", text)
                self.assertNotIn("can_enter_execute", text)
                self.assertNotIn("harness next --json", text)

    def test_phase_run_docs_require_projection_gate_before_edits(self) -> None:
        for path in [
            REPO / ".opencode/commands/fsd-run-phase.md",
            REPO / ".roo/commands/fsd-run-phase.md",
        ]:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertIn("harness check", text)
                self.assertIn("python3 scripts/show_phase_status.py", text)
                self.assertIn("projected_execute_gate_valid=true", text)
                self.assertIn("non-empty `allowed_paths`", text)
                self.assertIn("non-empty `verification`", text)


if __name__ == "__main__":
    unittest.main()
