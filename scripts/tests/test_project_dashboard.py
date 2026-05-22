#!/usr/bin/env python3
"""Tests for the static project dashboard generator."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.project_dashboard import core as project_dashboard
from lib.project_dashboard import renderer as dashboard_renderer
from lib.project_dashboard import server as dashboard_server


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
            self.assertFalse(any(w.code == "phase_folder_not_in_roadmap" for w in data.warnings))
            self.assertTrue(any(w.code == "stale_execute_approval" and w.severity == "blocking" for w in data.warnings))

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

            self.assertTrue(any(w.code == "projection_failed" for w in data.warnings))

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
        entrypoint = Path(__file__).resolve().parents[1] / "project_dashboard.py"
        line_count = len(entrypoint.read_text(encoding="utf-8").splitlines())

        self.assertLessEqual(line_count, 40)

    def test_dashboard_json_contains_three_page_inputs_and_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture_repository(root)

            payload = project_dashboard.dashboard_data_to_json(project_dashboard.load_dashboard_data(root))

            self.assertEqual("Example milestone", payload["project"]["milestone_name"])
            self.assertEqual("done", payload["gate"]["phase"])
            self.assertEqual(2, len(payload["roadmap"]))
            self.assertTrue(any(action["id"] == "check" for action in payload["actions"]))
            self.assertTrue(any(action["id"] == "run" and action["confirmation"] for action in payload["actions"]))

    def test_dashboard_assets_are_present_for_dynamic_routes(self) -> None:
        asset_dir = Path(__file__).resolve().parents[1] / "lib/project_dashboard/assets"

        html = (asset_dir / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn('<html lang="en">', html)
        self.assertIn(">Overview<", html)
        self.assertIn(">Progress<", html)
        self.assertIn(">Actions<", html)
        self.assertIn("/assets/dashboard.css", html)
        self.assertIn("/assets/dashboard.js", html)
        self.assertNotIn("dashboard-token", html)
        self.assertIn("renderOverview", (asset_dir / "dashboard.js").read_text(encoding="utf-8"))
        self.assertIn("renderProgress", (asset_dir / "dashboard.js").read_text(encoding="utf-8"))
        self.assertIn("renderActions", (asset_dir / "dashboard.js").read_text(encoding="utf-8"))

    def test_dashboard_action_rejects_unknown_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(ValueError):
                dashboard_server.run_dashboard_action(root=Path(tmpdir), action_id="rm-rf")

    def test_dashboard_action_requires_confirmation_for_mutating_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(ValueError):
                dashboard_server.run_dashboard_action(root=Path(tmpdir), action_id="run")

    def test_dashboard_action_uses_allowlisted_argv_without_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            completed = mock.Mock(returncode=0, stdout="ok\n")

            with mock.patch.object(dashboard_server.subprocess, "run", return_value=completed) as run_mock:
                result = dashboard_server.run_dashboard_action(root=root, action_id="check")

            self.assertTrue(result["ok"])
            self.assertEqual(f"{sys.executable} scripts/harness.py check", result["command"])
            _, kwargs = run_mock.call_args
            self.assertEqual([sys.executable, "scripts/harness.py", "check"], run_mock.call_args.args[0])
            self.assertEqual(root, kwargs["cwd"])
            self.assertFalse(kwargs.get("shell", False))
            self.assertEqual(dashboard_server.COMMAND_TIMEOUT_SECONDS, kwargs["timeout"])

    def test_dashboard_action_truncates_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            completed = mock.Mock(returncode=0, stdout="x" * (dashboard_server.MAX_OUTPUT_CHARS + 100))

            with mock.patch.object(dashboard_server.subprocess, "run", return_value=completed):
                result = dashboard_server.run_dashboard_action(root=Path(tmpdir), action_id="check")

            self.assertLessEqual(len(result["output"]), dashboard_server.MAX_OUTPUT_CHARS + 64)
            self.assertIn("output truncated", result["output"])

    def test_dashboard_refuses_non_local_bind_addresses(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(SystemExit):
                dashboard_server.serve_dashboard(root=Path(tmpdir), host="0.0.0.0", port=0)

    def test_dashboard_host_parser_accepts_ipv6_loopback_host_header(self) -> None:
        self.assertEqual("::1", dashboard_server.host_without_port("[::1]:8765"))
        self.assertEqual("127.0.0.1", dashboard_server.host_without_port("127.0.0.1:8765"))

    def test_manifest_installs_dashboard_runtime_files(self) -> None:
        manifest = json.loads((Path(__file__).resolve().parents[1] / "harness/manifest.json").read_text(encoding="utf-8"))
        paths = {entry["path"] for entry in manifest["files"]}

        self.assertIn("scripts/project_dashboard.py", paths)
        self.assertIn("scripts/lib/project_dashboard/core.py", paths)
        self.assertIn("scripts/lib/project_dashboard/server.py", paths)
        self.assertIn("scripts/lib/project_dashboard/assets/dashboard.html", paths)
        self.assertIn("scripts/lib/project_dashboard/assets/dashboard.css", paths)
        self.assertIn("scripts/lib/project_dashboard/assets/dashboard.js", paths)


def write_fixture_repository(root: Path) -> None:
    (root / ".planning/phases/01-first").mkdir(parents=True)
    (root / ".planning/codebase").mkdir(parents=True)
    (root / ".scratch/example/issues").mkdir(parents=True)
    (root / "docs/agents").mkdir(parents=True)
    (root / ".scratch").mkdir(exist_ok=True)

    (root / ".planning/STATE.md").write_text(
        """---
planning_doc_schema_version: 1
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


def test_dashboard_warning_dataclass_round_trip():
    from lib.project_dashboard.models import DashboardWarning
    w = DashboardWarning(code="x", severity="warning", message="hello", paths=[".planning/STATE.md"])
    assert w.code == "x"
    assert w.severity == "warning"


def test_roadmap_phase_has_phase_id_field():
    from lib.project_dashboard.models import RoadmapPhase
    p = RoadmapPhase(title="Phase 1: x", summary="", completed=False, raw_line="...")
    assert p.phase_id == ""
    p2 = RoadmapPhase(title="Phase 2b: y", summary="", completed=False, raw_line="...", phase_id="02b")
    assert p2.phase_id == "02b"


def test_dashboard_recognises_letter_suffix_phase_no_phantom_warning(tmp_path):
    from tests._helpers.planning_repo import make_minimal_planning_repo
    root = make_minimal_planning_repo(tmp_path)
    from lib.project_dashboard.core import load_dashboard_data
    data = load_dashboard_data(root)
    # 02b is now declared in the ROADMAP fixture, so no "not in ROADMAP" warning:
    assert not any(w.code == "phase_folder_not_in_roadmap" for w in data.warnings)
    # And no grammar-invalid warning:
    assert not any(w.code == "phase_folder_grammar_invalid" for w in data.warnings)


def test_dashboard_emits_actionable_warning_when_phase_folder_missing_from_roadmap(tmp_path):
    from tests._helpers.planning_repo import make_minimal_planning_repo
    root = make_minimal_planning_repo(tmp_path)
    # Add an extra phase folder NOT declared in ROADMAP — simulating 02b-hardening on the live repo today:
    (root / ".planning/phases/02c-followup").mkdir()
    from lib.project_dashboard.core import load_dashboard_data
    data = load_dashboard_data(root)
    matched = [w for w in data.warnings if w.code == "phase_folder_not_in_roadmap"]
    assert len(matched) == 1
    assert "02c-followup" in matched[0].message
    assert "ROADMAP" in matched[0].message
    assert matched[0].severity == "warning"


def test_load_phase_documents_includes_nested_plan_files(tmp_path):
    phase = tmp_path / ".planning/phases/02b-hardening"
    (phase / "plans").mkdir(parents=True)
    (phase / "README.md").write_text("# README\n")
    (phase / "plans" / "02b-01-T0-A-PLAN.md").write_text("# T0-A\n")
    (phase / "plans" / "02b-02-T0-1-PLAN.md").write_text("# T0-1\n")
    (phase / "plans" / "scratch.md").write_text("# not a plan\n")  # excluded
    from lib.project_dashboard.core import load_phase_documents
    docs = load_phase_documents(tmp_path)
    files = docs[0].files
    assert "02b-01-T0-A-PLAN.md" in files
    assert "02b-02-T0-1-PLAN.md" in files
    assert "scratch.md" not in files  # only *-PLAN.md included
    assert files["02b-01-T0-A-PLAN.md"].endswith("plans/02b-01-T0-A-PLAN.md")


def test_load_phase_documents_top_level_wins_on_name_collision(tmp_path):
    phase = tmp_path / ".planning/phases/02b-hardening"
    (phase / "plans").mkdir(parents=True)
    (phase / "duplicate.md").write_text("# top\n")
    (phase / "plans" / "duplicate.md").write_text("# nested\n")
    from lib.project_dashboard.core import load_phase_documents
    docs = load_phase_documents(tmp_path)
    files = docs[0].files
    assert files["duplicate.md"].endswith(".planning/phases/02b-hardening/duplicate.md")


def test_malformed_phase_state_emits_single_structured_warning(tmp_path):
    from tests._helpers.planning_repo import make_minimal_planning_repo
    root = make_minimal_planning_repo(tmp_path)
    (root / ".scratch/phase-state.json").write_text("{not json")
    from lib.project_dashboard.core import load_dashboard_data
    data = load_dashboard_data(root)
    malformed = [w for w in data.warnings if w.code == "phase_state_malformed_json"]
    assert len(malformed) == 1
    # secondary checks must not pile on:
    assert not any(w.code == "phase_state_missing_path_ref" for w in data.warnings)
    assert not any(w.code == "state_checkpoint_drift" for w in data.warnings)


if __name__ == "__main__":
    unittest.main()
