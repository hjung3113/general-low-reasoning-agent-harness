#!/usr/bin/env python3
"""Target-safe smoke tests for initialized low-reasoning harness projects."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


class TargetHarnessSmokeTests(unittest.TestCase):
    def installed(self) -> dict:
        return json.loads(Path(".harness/installed-manifest.json").read_text(encoding="utf-8"))

    def test_harness_check_passes_in_target(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/harness.py", "check"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_phase_state_is_discuss_and_unapproved(self) -> None:
        state = json.loads(Path(".scratch/phase-state.json").read_text(encoding="utf-8"))

        self.assertEqual("discuss", state["phase"])
        self.assertFalse(state["approved"])

    def test_show_phase_status_preflight_has_no_blocking_warnings(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/show_phase_status.py"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual("phase-status.v1", payload["contract_version"])
        self.assertFalse(
            [warning for warning in payload["warnings"] if warning["severity"] == "blocking"],
            payload["warnings"],
        )

    def test_harness_doctor_has_no_p1_or_p2_findings(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/harness.py", "doctor", "--format", "json"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        severe = [finding for finding in payload["findings"] if finding["severity"] in {"P1", "P2"}]
        self.assertFalse(severe, severe)

    def test_required_target_files_exist(self) -> None:
        state = json.loads(Path(".scratch/phase-state.json").read_text(encoding="utf-8"))
        checkpoint_path = state.get("checkpoint_path")
        self.assertIsInstance(checkpoint_path, str)
        required = [
            "AGENTS.md",
            "README.md",
            checkpoint_path,
            "scripts/harness.py",
        ]
        adapters = set(self.installed().get("adapters", []))
        packs = set(self.installed().get("packs", []))
        if "roo" in adapters:
            required.extend(
                [
                    ".roo/commands/README.md",
                    ".roo/skills/workflow-phase-gate/SKILL.md",
                ]
            )
        if "opencode" in adapters:
            required.append(".opencode/commands/plan.md")
        if "workflow-core" in packs:
            required.append(".agents/skills/skill-plugin-composition/SKILL.md")
        for pack in sorted(packs - {"workflow-core"}):
            required.append(f".agents/skills/{pack}/SKILL.md")
        for relative in required:
            self.assertTrue(Path(relative).exists(), relative)


if __name__ == "__main__":
    unittest.main()
