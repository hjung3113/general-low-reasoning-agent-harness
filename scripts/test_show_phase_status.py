#!/usr/bin/env python3
"""Tests for the phase status projection and JSON CLI."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts/show_phase_status.py"


class ShowPhaseStatusProjectionTests(unittest.TestCase):
    def test_projection_reads_execute_gate_identity_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture_repository(root)

            from scripts.lib.planning_status import CONTRACT_VERSION, load_projection, projection_to_dict

            payload = projection_to_dict(load_projection(root))

            self.assertEqual(CONTRACT_VERSION, payload["contract_version"])
            self.assertEqual("execute", payload["phase"])
            self.assertEqual("02", payload["phase_id"])
            self.assertEqual("Status Projection", payload["phase_title"])
            self.assertEqual("CP-02-01", payload["active_checkpoint_id"])
            self.assertEqual("Execute ready", payload["active_checkpoint_title"])
            self.assertEqual("Ready for execute", payload["active_checkpoint_status"])
            self.assertEqual(".planning/phases/02-status-projection", payload["active_phase_folder"])
            self.assertEqual(".planning/phases/02-status-projection/02-CHECKPOINTS.md", payload["checkpoint_path"])
            self.assertEqual(".planning/phases/02-status-projection/02-01-PLAN.md", payload["plan_path"])
            self.assertTrue(payload["projected_execute_gate_valid"])
            self.assertEqual([], payload["warnings"])
            self.assertIn(".planning/STATE.md", payload["required_reads"])
            self.assertIn(".scratch/phase-state.json", payload["required_reads"])

    def test_projection_reports_blocking_warning_for_checkpoint_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture_repository(root, phase_state_checkpoint="CP-02-99")

            from scripts.lib.planning_status import load_projection, projection_to_dict

            payload = projection_to_dict(load_projection(root))

            warning = only_warning(payload, "state_checkpoint_drift")
            self.assertEqual("blocking", warning["severity"])
            self.assertTrue(warning["required_read"])
            self.assertIn(".planning/STATE.md", warning["paths"])
            self.assertIn(".scratch/phase-state.json", warning["paths"])
            self.assertFalse(payload["projected_execute_gate_valid"])

    def test_projection_distinguishes_active_docs_from_historical_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture_repository(root)
            historical = root / ".planning/phases/01-old/01-VERIFICATION.md"
            historical.parent.mkdir(parents=True)
            historical.write_text("# Old verification\n", encoding="utf-8")

            from scripts.lib.planning_status import load_projection, projection_to_dict

            payload = projection_to_dict(load_projection(root))

            self.assertIn(".planning/phases/02-status-projection/02-VERIFICATION.md", payload["required_reads"])
            self.assertNotIn(".planning/phases/01-old/01-VERIFICATION.md", payload["required_reads"])

    def test_phase_done_stale_approval_is_not_execute_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture_repository(root, phase="done", approved=True)

            from scripts.lib.planning_status import load_projection, projection_to_dict

            payload = projection_to_dict(load_projection(root))

            self.assertFalse(payload["projected_execute_gate_valid"])
            self.assertIn("phase is done", payload["projected_execute_gate_reason"])
            warning = only_warning(payload, "stale_execute_approval")
            self.assertEqual("blocking", warning["severity"])

    def test_done_without_approval_is_not_a_projection_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture_repository(root, phase="done", approved=False)

            from scripts.lib.planning_status import load_projection, projection_to_dict

            payload = projection_to_dict(load_projection(root))

            self.assertFalse(payload["projected_execute_gate_valid"])
            self.assertFalse(any(warning["code"] == "stale_execute_approval" for warning in payload["warnings"]))

    def test_execute_against_completed_checkpoint_is_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture_repository(root, checkpoint_status="Complete")

            from scripts.lib.planning_status import load_projection, projection_to_dict

            payload = projection_to_dict(load_projection(root))

            warning = only_warning(payload, "completed_checkpoint_execute_approval")
            self.assertEqual("blocking", warning["severity"])
            self.assertFalse(payload["projected_execute_gate_valid"])

    def test_roadmap_progress_drift_is_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture_repository(root, roadmap_extra_phase=True)

            from scripts.lib.planning_status import load_projection, projection_to_dict

            payload = projection_to_dict(load_projection(root))

            warning = only_warning(payload, "roadmap_total_phases_drift")
            self.assertEqual("blocking", warning["severity"])
            self.assertFalse(payload["projected_execute_gate_valid"])

    def test_missing_active_files_are_structured_blocking_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture_repository(root)
            (root / ".planning/phases/02-status-projection/02-CHECKPOINTS.md").unlink()

            from scripts.lib.planning_status import load_projection, projection_to_dict

            payload = projection_to_dict(load_projection(root))

            warning = only_warning(payload, "missing_active_file")
            self.assertEqual("blocking", warning["severity"])
            self.assertIn(".planning/phases/02-status-projection/02-CHECKPOINTS.md", warning["paths"])
            self.assertIn(".planning/phases/02-status-projection/02-CHECKPOINTS.md", payload["required_reads"])
            self.assertFalse(payload["projected_execute_gate_valid"])

    def test_discuss_phase_does_not_require_future_verification_doc(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture_repository(root, phase="discuss", approved=False)
            (root / ".planning/phases/02-status-projection/02-VERIFICATION.md").unlink()

            from scripts.lib.planning_status import load_projection, projection_to_dict

            payload = projection_to_dict(load_projection(root))

            self.assertFalse(any(warning["code"] == "missing_active_file" for warning in payload["warnings"]))
            self.assertEqual("", payload["verification_path"])

    def test_stale_plan_checkpoint_mismatch_blocks_execute_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture_repository(root, phase_state_plan_id="old-plan", plan_id="current-plan")

            from scripts.lib.planning_status import load_projection, projection_to_dict

            payload = projection_to_dict(load_projection(root))

            warning = only_warning(payload, "plan_id_drift")
            self.assertEqual("blocking", warning["severity"])
            self.assertIn(".planning/phases/02-status-projection/02-01-PLAN.md", warning["paths"])
            self.assertFalse(payload["projected_execute_gate_valid"])

    def test_plan_specific_summary_path_is_preferred_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture_repository(root)
            (root / ".planning/phases/02-status-projection/02-01-SUMMARY.md").write_text(
                "# Plan-specific summary\n",
                encoding="utf-8",
            )

            from scripts.lib.planning_status import load_projection, projection_to_dict

            payload = projection_to_dict(load_projection(root))

            self.assertEqual(".planning/phases/02-status-projection/02-01-SUMMARY.md", payload["summary_path"])
            self.assertIn(".planning/phases/02-status-projection/02-01-SUMMARY.md", payload["required_reads"])


class ShowPhaseStatusCliTests(unittest.TestCase):
    def test_cli_emits_single_json_object_on_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture_repository(root)

            completed = run_cli(root)

            self.assertEqual(0, completed.returncode, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual("phase-status.v1", payload["contract_version"])
            self.assertEqual("", completed.stderr)
            self.assertEqual(completed.stdout.strip(), json.dumps(payload, sort_keys=True, separators=(",", ":")))

    def test_cli_has_no_markdown_or_prose_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture_repository(root)

            completed = run_cli(root)

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertTrue(completed.stdout.startswith("{"))
            self.assertFalse(completed.stdout.startswith("#"))
            self.assertNotIn("```", completed.stdout)
            self.assertNotIn("Phase status", completed.stdout)

    def test_cli_exits_nonzero_for_malformed_phase_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture_repository(root)
            (root / ".scratch/phase-state.json").write_text("{not json", encoding="utf-8")

            completed = run_cli(root)

            self.assertNotEqual(0, completed.returncode)
            self.assertEqual("", completed.stdout)
            self.assertIn(".scratch/phase-state.json", completed.stderr)


def run_cli(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        check=False,
        capture_output=True,
        text=True,
    )


def only_warning(payload: dict[str, object], code: str) -> dict[str, object]:
    warnings = [warning for warning in payload["warnings"] if warning["code"] == code]
    if len(warnings) != 1:
        raise AssertionError(f"Expected one warning {code!r}, got {warnings!r}")
    return warnings[0]


def write_fixture_repository(
    root: Path,
    *,
    phase: str = "execute",
    approved: bool = True,
    phase_state_checkpoint: str = "CP-02-01",
    phase_state_plan_id: str = "projection-02-01",
    plan_id: str = "projection-02-01",
    checkpoint_status: str = "Ready for execute",
    roadmap_extra_phase: bool = False,
) -> None:
    phase_dir = root / ".planning/phases/02-status-projection"
    phase_dir.mkdir(parents=True)
    (root / ".planning/codebase").mkdir(parents=True)
    (root / ".scratch").mkdir()

    (root / ".planning/STATE.md").write_text(
        """---
progress:
  total_phases: 2
  completed_phases: 1
  percent: 50
---

# STATE

## Current Position

- **Phase**: 2 - Status Projection.
- **Status**: Execute approved.

## Active Checkpoint

- **Checkpoint**: CP-02-01 - Execute ready.
- **Checkpoint file**: `.planning/phases/02-status-projection/02-CHECKPOINTS.md`.
""",
        encoding="utf-8",
    )
    extra_phase = "- [ ] **Phase 3: Extra Phase** - Drift.\n" if roadmap_extra_phase else ""
    (root / ".planning/ROADMAP.md").write_text(
        """# ROADMAP

## Phases

- [x] **Phase 1: Old Phase** - Completed.
- [ ] **Phase 2: Status Projection** - Build status projection.
""" + extra_phase,
        encoding="utf-8",
    )
    (root / ".planning/codebase/ARCHITECTURE.md").write_text("# Architecture\n", encoding="utf-8")
    (phase_dir / "02-CHECKPOINTS.md").write_text(
        f"""# Phase 2 Checkpoints

## CP-02-01 - Execute ready

- **Status**: {checkpoint_status}.
""",
        encoding="utf-8",
    )
    (phase_dir / "02-01-PLAN.md").write_text(
        f"""---
plan_id: {plan_id}
---

# Projection Plan
""",
        encoding="utf-8",
    )
    (phase_dir / "02-VERIFICATION.md").write_text("# Verification\n", encoding="utf-8")
    (phase_dir / "02-SUMMARY.md").write_text("# Summary\n", encoding="utf-8")
    (root / ".scratch/phase-state.json").write_text(
        json.dumps(
            {
                "phase": phase,
                "approved": approved,
                "approved_by": "tester",
                "approved_at": "2026-05-15T00:00:00Z",
                "plan_id": phase_state_plan_id,
                "automation_mode": "manual",
                "state_path": ".planning/STATE.md",
                "plan_path": ".planning/phases/02-status-projection/02-01-PLAN.md",
                "checkpoint_path": ".planning/phases/02-status-projection/02-CHECKPOINTS.md",
                "current_checkpoint": phase_state_checkpoint,
                "allowed_paths": ["scripts/"],
                "blocked_paths": ["src/"],
                "acceptance_criteria": ["Projection contract is stable."],
                "verification": ["python3 -m unittest scripts/test_show_phase_status.py"],
                "next_action": "Implement status projection.",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
