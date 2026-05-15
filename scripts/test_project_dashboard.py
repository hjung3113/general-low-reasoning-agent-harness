#!/usr/bin/env python3
"""Tests for the static project dashboard generator."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.project_dashboard import core as project_dashboard
from lib.project_dashboard import renderer as dashboard_renderer


class ProjectDashboardTests(unittest.TestCase):
    def test_parse_frontmatter_reads_scalars_and_nested_progress(self) -> None:
        text = """---
gsd_state_version: 1.0
milestone: m1
milestone_name: reusable low-reasoning Roo harness
status: ready for PR
last_updated: "2026-05-14T00:00:00.000Z"
progress:
  total_phases: 5
  completed_phases: 3
  percent: 60
---

# STATE
"""

        frontmatter = project_dashboard.parse_frontmatter(text)

        self.assertEqual("m1", frontmatter["milestone"])
        self.assertEqual("ready for PR", frontmatter["status"])
        self.assertEqual("5", frontmatter["progress.total_phases"])
        self.assertEqual("3", frontmatter["progress.completed_phases"])
        self.assertEqual("60", frontmatter["progress.percent"])

    def test_parse_roadmap_phases_detects_completed_and_open_items(self) -> None:
        text = """# ROADMAP

## Phases

- [x] **Phase 1: Document-Centered Phase Continuity** - Add planning memory.
- [ ] **Phase 2: Template Consumer Onboarding** - Add bootstrap checklist.
"""

        phases = project_dashboard.parse_roadmap_phases(text)

        self.assertEqual(2, len(phases))
        self.assertEqual("Phase 1: Document-Centered Phase Continuity", phases[0].title)
        self.assertTrue(phases[0].completed)
        self.assertEqual("Add bootstrap checklist.", phases[1].summary)
        self.assertFalse(phases[1].completed)

    def test_done_gate_leaves_next_open_phase_in_remaining_column(self) -> None:
        phases = [
            project_dashboard.RoadmapPhase("Phase 1: First", "Done.", True, ""),
            project_dashboard.RoadmapPhase("Phase 2: Second", "Not started.", False, ""),
        ]

        columns = dashboard_renderer.group_phases_for_kanban(phases, "done")

        self.assertEqual(["Phase 1: First"], [phase.title for phase in columns["done"]])
        self.assertEqual([], columns["active"])
        self.assertEqual(["Phase 2: Second"], [phase.title for phase in columns["remaining"]])

    def test_load_dashboard_data_reads_fixture_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture_repository(root)

            data = project_dashboard.load_dashboard_data(root)

            self.assertEqual("ready for PR", data.state.status)
            self.assertEqual("done", data.phase_state["phase"])
            self.assertEqual(2, len(data.roadmap_phases))
            self.assertEqual(1, len(data.issues))
            self.assertEqual(5, len(data.documents))
            self.assertEqual("CP-01", data.active_checkpoint)
            self.assertFalse(any("not listed in ROADMAP" in warning for warning in data.warnings))
            self.assertTrue(any("phase-status blocking stale_execute_approval" in warning for warning in data.warnings))

    def test_dashboard_uses_shared_active_checkpoint_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture_repository(root)

            from lib.planning_status import load_projection

            data = project_dashboard.load_dashboard_data(root)
            projection = load_projection(root)

            self.assertEqual(projection.active_checkpoint_id, data.active_checkpoint)

    def test_malformed_phase_state_becomes_dashboard_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture_repository(root)
            (root / ".scratch/phase-state.json").write_text("{not json", encoding="utf-8")

            data = project_dashboard.load_dashboard_data(root)

            self.assertTrue(any("phase status projection failed" in warning for warning in data.warnings))

    def test_generate_dashboard_writes_self_contained_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture_repository(root)
            output = root / ".scratch/reports/project-dashboard.html"

            written = project_dashboard.generate_dashboard(root=root, output=output)

            html = written.read_text(encoding="utf-8")
            self.assertEqual(output, written)
            self.assertIn("<!doctype html>", html.lower())
            self.assertIn("Example milestone", html)
            self.assertIn("Roadmap Kanban", html)
            self.assertIn("Done", html)
            self.assertIn("In Progress", html)
            self.assertIn("Remaining", html)
            self.assertIn("Phase 1: First", html)
            self.assertIn("Example Issue", html)
            self.assertIn("Phase Gate Harness", html)
            self.assertIn("python3 scripts/harness.py check", html)
            self.assertIn("Gate Details", html)
            self.assertIn("example-01", html)
            self.assertIn("done", html)
            self.assertIn("Automation", html)
            self.assertIn("chain", html)
            self.assertIn("human-chain-request", html)
            self.assertIn("Project Memory", html)
            self.assertIn("REQ-core-protocol", html)
            self.assertIn("Decision Ledger", html)
            self.assertIn("DEC-0001", html)
            self.assertIn("Verification Ledger", html)
            self.assertIn("Unit tests", html)
            self.assertIn("Known Concerns", html)
            self.assertIn("Core docs can drift.", html)

    def test_entrypoint_stays_thin(self) -> None:
        entrypoint = Path(__file__).resolve().parent / "project_dashboard.py"
        line_count = len(entrypoint.read_text(encoding="utf-8").splitlines())

        self.assertLessEqual(line_count, 40)


def write_fixture_repository(root: Path) -> None:
    (root / ".planning/phases/01-first").mkdir(parents=True)
    (root / ".planning/codebase").mkdir(parents=True)
    (root / ".scratch/example/issues").mkdir(parents=True)
    (root / "docs/agents").mkdir(parents=True)
    (root / ".scratch").mkdir(exist_ok=True)

    (root / ".planning/STATE.md").write_text(
        """---
milestone: m1
milestone_name: Example milestone
status: ready for PR
last_updated: "2026-05-14T00:00:00.000Z"
progress:
  total_phases: 2
  completed_phases: 1
  percent: 50
---

# STATE

## Active Checkpoint

- **Checkpoint**: CP-01 - Example checkpoint.
- **Checkpoint file**: `.planning/phases/01-first/01-CHECKPOINTS.md`.

### Blockers

- None active.

## Next Action

Open a PR.
""",
        encoding="utf-8",
    )
    (root / ".planning/ROADMAP.md").write_text(
        """# ROADMAP

## Phases

- [x] **Phase 1: First** - Completed phase.
- [ ] **Phase 2: Second** - Upcoming phase.
""",
        encoding="utf-8",
    )
    (root / ".planning/phases/01-first/01-CHECKPOINTS.md").write_text(
        "# Checkpoints\n\n- [x] CP-01 - Example checkpoint.\n",
        encoding="utf-8",
    )
    (root / ".planning/phases/01-first/01-VERIFICATION.md").write_text(
        "# Verification\n\n```bash\npython3 scripts/harness.py check\n```\n",
        encoding="utf-8",
    )
    (root / ".scratch/phase-state.json").write_text(
        json.dumps(
            {
                "phase": "done",
                "plan_id": "example-01",
                "approved": True,
                "approved_by": "human-chain-request",
                "approved_at": "2026-05-14T00:00:00Z",
                "state_path": ".planning/STATE.md",
                "checkpoint_path": ".planning/phases/01-first/01-CHECKPOINTS.md",
                "current_checkpoint": "CP-01",
                "next_action": "Open a PR.",
                "allowed_paths": [".planning/", ".scratch/"],
                "blocked_paths": ["src/"],
                "acceptance_criteria": ["Dashboard fixture loads."],
                "verification": ["python3 scripts/harness.py check"],
                "automation_mode": "chain",
            }
        ),
        encoding="utf-8",
    )
    (root / ".scratch/example/issues/01-example.md").write_text(
        "# Example Issue\n\n- Label: ready-for-agent\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Example Project\n\nHuman guide.\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("# Agent Instructions\n\nRules.\n", encoding="utf-8")
    (root / "docs/phase-gate-harness.md").write_text("# Phase Gate Harness\n\nDetails.\n", encoding="utf-8")
    (root / "docs/agents/domain.md").write_text("# Domain Docs\n\nDetails.\n", encoding="utf-8")
    (root / ".planning/PROJECT.md").write_text(
        "# PROJECT\n\n## One-Liner\n\nExample harness.\n\n## Scope\n\n- Core protocol.\n",
        encoding="utf-8",
    )
    (root / ".planning/REQUIREMENTS.md").write_text(
        "# REQUIREMENTS\n\n## REQ-core-protocol\n\nPreserve workflow.\n",
        encoding="utf-8",
    )
    (root / ".planning/DECISIONS.md").write_text(
        "# DECISIONS\n\n| ID | Status | Decision | Source | Scope |\n| --- | --- | --- | --- | --- |\n| DEC-0001 | Accepted | Keep planning memory. | `.planning/PROJECT.md` | All phases |\n",
        encoding="utf-8",
    )
    (root / ".planning/VERIFICATION.md").write_text(
        "# VERIFICATION\n\n| Date | Phase | Check | Result | Notes |\n| --- | --- | --- | --- | --- |\n| 2026-05-14 | Phase 1 | Unit tests | PASS | Example. |\n",
        encoding="utf-8",
    )
    (root / ".planning/codebase/CONCERNS.md").write_text(
        "# CONCERNS\n\n- Core docs can drift.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
