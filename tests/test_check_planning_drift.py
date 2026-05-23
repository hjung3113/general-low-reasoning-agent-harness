"""Tests for planning-drift propagation in harness check (Task 6.2).

Verifies that harness.check() raises SystemExit when the dashboard --check
finds a blocking warning, and completes normally when the fixture is clean or
only has non-blocking (severity="warning") dashboard warnings.

Fixture design notes
--------------------
check_installed_target() requires:
- .harness/installed-manifest.json  (schema_version=2, version, empty files)
- AGENTS.md  (with managed-append block containing the required guardrail phrases)
- .scratch/phase-state.json  (if present, must pass check_phase_state_semantics)
- .planning/  (needed for _check_planning_drift to run)

roadmap_state_sync_applicable() skips the sync check when STATE.md, ROADMAP.md,
or phase-state.json are absent.  We omit STATE.md from the planning dir so that
the roadmap/state sync check is bypassed entirely, keeping the fixture minimal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure scripts/ is on sys.path so `import harness` resolves correctly.
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import harness  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture factory
# ---------------------------------------------------------------------------

_AGENTS_BLOCK = (
    "# AGENTS\n\n"
    "# >>> low-reasoning-harness:AGENTS.md v0.0.0-dev+unknown\n"
    "Karpathy-Inspired Coding Guidelines\n\n"
    "If `.scratch/phase-state.json` is not `phase=execute` with `approved=true`\n\n"
    "Every roadmap phase starts with its own `discuss` pass\n"
    "# <<< low-reasoning-harness:AGENTS.md\n"
)


def _make_check_fixture(root: Path) -> Path:
    """Create a minimal directory that passes check_installed_target cleanly.

    The .planning/ directory exists (so _check_planning_drift can run), but
    STATE.md is deliberately absent so roadmap_state_sync_applicable() returns
    False and the roadmap/phase-state sync check is skipped.
    """
    # .harness/installed-manifest.json
    harness_dir = root / ".harness"
    harness_dir.mkdir()
    (harness_dir / "installed-manifest.json").write_text(
        json.dumps({
            "schema_version": 2,
            "version": "0.0.0-dev+unknown",
            "adapters": [],
            "profiles": [],
            "packs": [],
            "files": {},
        }),
        encoding="utf-8",
    )

    # AGENTS.md — managed-append block with required guardrail phrases.
    (root / "AGENTS.md").write_text(_AGENTS_BLOCK, encoding="utf-8")

    # .scratch/phase-state.json — must satisfy check_phase_state_semantics.
    scratch = root / ".scratch"
    scratch.mkdir()
    (scratch / "phase-state.json").write_text(
        json.dumps({
            "state_schema_version": 2,
            "phase": "discuss",
            "approved": False,
            "current_checkpoint": "CP-01-01",
            "checkpoint_path": ".planning/milestones/01-init/01-CHECKPOINTS.md",
            "state_path": ".planning/STATE.md",
            "automation_mode": "manual",
            "auto_selected": [],
            "updated_at": "2026-05-20T00:00:00.000000000Z",
            "updated_by": "test",
        }),
        encoding="utf-8",
    )

    # .planning/ — present so _check_planning_drift can invoke the dashboard.
    planning = root / ".planning"
    planning.mkdir()
    phases = planning / "phases"
    phases.mkdir()
    # One valid phase folder referenced by phase-state.json.
    phase_dir = phases / "01-init"
    phase_dir.mkdir()
    cp_file = ".planning/milestones/01-init/01-CHECKPOINTS.md"
    (phase_dir / "01-CHECKPOINTS.md").write_text(
        "## CP-01-01 - smoke\n- **Status**: in_progress\n", encoding="utf-8"
    )
    (planning / "ROADMAP.md").write_text(
        "## Phases\n- [ ] **Phase 1: Init** - intern\n", encoding="utf-8"
    )
    # STATE.md — required by dashboard (missing_active_file is blocking).
    # Must include planning_doc_schema_version frontmatter, active phase, and
    # active checkpoint matching phase-state.json's current_checkpoint.
    (planning / "STATE.md").write_text(
        "---\nplanning_doc_schema_version: 1\n"
        "progress:\n  total_phases: 1\n  completed_phases: 0\n  percent: 0\n---\n"
        "# STATE\n\n## Current Position\n- **Phase**: 1 - Init.\n\n"
        "## Active Checkpoint\n- **Checkpoint**: CP-01-01 - smoke.\n"
        f"- **Checkpoint file**: `{cp_file}`.\n",
        encoding="utf-8",
    )

    return root


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_check_clean_fixture_exits_zero(tmp_path):
    """A clean minimal fixture should pass harness.check() without raising SystemExit."""
    root = _make_check_fixture(tmp_path)
    # Should not raise
    harness.check(root=root)


def test_check_exits_nonzero_on_blocking_planning_drift(tmp_path):
    """harness.check raises SystemExit when dashboard --check finds a blocking warning.

    A phase folder whose name does not match the NN[a-z]?-slug grammar triggers
    phase_folder_grammar_invalid (severity="blocking") in the dashboard.
    """
    root = _make_check_fixture(tmp_path)
    # Phase folder with no numeric prefix — triggers phase_folder_grammar_invalid.
    (root / ".planning/milestones/bad-phase-name").mkdir()
    with pytest.raises(SystemExit) as exc_info:
        harness.check(root=root)
    exit_code = exc_info.value.code
    assert exit_code != 0, f"Expected nonzero exit, got {exit_code!r}"
    assert "planning-drift" in str(exit_code), (
        f"Expected 'planning-drift' in SystemExit message, got: {exit_code!r}"
    )


def test_check_exits_zero_on_non_blocking_planning_warning(tmp_path):
    """harness.check() passes when dashboard finds only non-blocking warnings.

    An extra valid-grammar phase folder not listed in ROADMAP triggers
    phase_folder_not_in_roadmap (severity="warning"), which is non-blocking.
    harness check should still return normally (exit 0).
    """
    root = _make_check_fixture(tmp_path)
    # Valid grammar, not in ROADMAP — non-blocking warning only.
    (root / ".planning/milestones/03-extra-phase").mkdir()
    # Should not raise
    harness.check(root=root)
