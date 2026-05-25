"""Tests for issue #23: suppress first-run state-sync invariant on fresh harness init.

Two scenarios are tested:

1. Template-only .planning/ state (fresh harness init, no user edits):
   - harness check must NOT raise "Roadmap/state sync invariant failed".
   - Other invariants (e.g. import smoke, installed-manifest checks) still run.

2. Real milestone + state transition (user has seeded their project):
   - harness check MUST enforce the roadmap/state sync invariant.
   - A deliberate mismatch (STATE progress.total_phases != ROADMAP count) fires.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.roadmap_state import (  # noqa: E402
    is_uninitialized_planning_state,
    roadmap_state_sync_applicable,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_AGENTS_BLOCK = (
    "# AGENTS\n\n"
    "# >>> low-reasoning-harness:AGENTS.md v0.0.0-dev+unknown\n"
    "Karpathy-Inspired Coding Guidelines\n\n"
    "If `.scratch/phase-state.json` is not `phase=execute` with `approved=true`\n\n"
    "Every roadmap phase starts with its own `discuss` pass\n"
    "# <<< low-reasoning-harness:AGENTS.md\n"
)

_INSTALLED_MANIFEST = {
    "schema_version": 2,
    "version": "0.0.0-dev+unknown",
    "adapters": [],
    "profiles": [],
    "packs": [],
    "files": {},
}

# phase-state.json as written by harness init (epoch sentinel).
_INIT_PHASE_STATE = {
    "phase": "discuss",
    "state_schema_version": 2,
    "plan_id": None,
    "approved": False,
    "summary": "Roo harness initialized; project planning memory needs hydration.",
    "plan_path": None,
    "state_path": ".planning/STATE.md",
    "checkpoint_path": ".planning/milestones/00-orientation/00-CHECKPOINTS.md",
    "current_checkpoint": "CP-00-01",
    "next_action": "Hydrate .planning documents from the target repository before implementation.",
    "automation_mode": "manual",
    "auto_selected": [],
    "updated_at": "1970-01-01T00:00:00Z",
    "updated_by": "harness-init",
}

# Template-only STATE.md — milestone: m0 (the init skeleton sentinel).
_INIT_STATE_MD = """\
---
planning_doc_schema_version: "1"
gsd_state_version: 1.0
milestone: m0
milestone_name: harness adoption
status: initialized
progress:
  total_phases: 1
  completed_phases: 0
  percent: 0
---

# STATE - Project Harness Adoption

<!-- HARNESS:BEGIN managed:state-current v1 -->
## Current Position

- **Phase**: 0 - Planning Hydration

## Active Checkpoint

- **Checkpoint**: CP-00-01
- **Checkpoint file**: `.planning/milestones/00-orientation/00-CHECKPOINTS.md`
<!-- HARNESS:END managed:state-current -->
"""

# Template-only ROADMAP.md — only the skeleton Phase 0 bullet.
_INIT_ROADMAP_MD = """\
# ROADMAP - Project Harness Adoption

## Phases

<!-- HARNESS:BEGIN managed:roadmap-phases v1 -->
- [ ] **Phase 0: Planning Hydration**
<!-- HARNESS:END managed:roadmap-phases -->
"""

_INIT_CHECKPOINTS_MD = """\
## CP-00-01 - Hydrate planning memory
- **Status**: in_progress
"""


def _make_base_target(root: Path) -> Path:
    """Minimal installed-target scaffolding (installed-manifest + AGENTS.md)."""
    harness_dir = root / ".harness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    (harness_dir / "installed-manifest.json").write_text(
        json.dumps(_INSTALLED_MANIFEST), encoding="utf-8"
    )
    (root / "AGENTS.md").write_text(_AGENTS_BLOCK, encoding="utf-8")
    return root


def _make_scratch(root: Path, phase_state: dict) -> None:
    scratch = root / ".scratch"
    scratch.mkdir(exist_ok=True)
    (scratch / "phase-state.json").write_text(
        json.dumps(phase_state), encoding="utf-8"
    )


def _make_planning_init(root: Path) -> None:
    """Write the template-only .planning/ tree (post-harness-init, pre-user-edits)."""
    planning = root / ".planning"
    planning.mkdir(exist_ok=True)
    (planning / "STATE.md").write_text(_INIT_STATE_MD, encoding="utf-8")
    (planning / "ROADMAP.md").write_text(_INIT_ROADMAP_MD, encoding="utf-8")
    phase_dir = planning / "phases" / "00-orientation"
    phase_dir.mkdir(parents=True, exist_ok=True)
    (phase_dir / "00-CHECKPOINTS.md").write_text(_INIT_CHECKPOINTS_MD, encoding="utf-8")


def _make_planning_real(root: Path, *, break_sync: bool = False) -> None:
    """Write a .planning/ tree with a real user milestone seeded.

    If break_sync=True, deliberately mismatch STATE total_phases so the
    invariant fires.
    """
    planning = root / ".planning"
    planning.mkdir(exist_ok=True)

    total = 2 if not break_sync else 99  # 99 != actual ROADMAP count (1)
    state_md = f"""\
---
planning_doc_schema_version: "1"
milestone: m1
milestone_name: real project launch
status: in_progress
progress:
  total_phases: {total}
  completed_phases: 0
  percent: 0
---
# STATE

<!-- HARNESS:BEGIN managed:state-current v1 -->
## Current Position

- **Phase**: 1 - Bootstrap

## Active Checkpoint

- **Checkpoint**: CP-01-01
- **Checkpoint file**: `.planning/milestones/01-bootstrap/01-CHECKPOINTS.md`
<!-- HARNESS:END managed:state-current -->
"""
    roadmap_md = """\
# ROADMAP

## Phases

<!-- HARNESS:BEGIN managed:roadmap-phases v1 -->
- [ ] **Phase 1: Bootstrap** - get the repo scaffolded
- [ ] **Phase 2: Launch** - ship the first release
<!-- HARNESS:END managed:roadmap-phases -->
"""
    (planning / "STATE.md").write_text(state_md, encoding="utf-8")
    (planning / "ROADMAP.md").write_text(roadmap_md, encoding="utf-8")
    phase_dir = planning / "phases" / "01-bootstrap"
    phase_dir.mkdir(parents=True, exist_ok=True)
    (phase_dir / "01-CHECKPOINTS.md").write_text(
        "## CP-01-01 - scaffold\n- **Status**: in_progress\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Tests — predicate unit tests
# ---------------------------------------------------------------------------


def test_is_uninitialized_planning_state_fresh(tmp_path):
    """is_uninitialized_planning_state returns True for a fresh harness init."""
    _make_base_target(tmp_path)
    _make_scratch(tmp_path, _INIT_PHASE_STATE)
    _make_planning_init(tmp_path)

    assert is_uninitialized_planning_state(tmp_path) is True


def test_is_uninitialized_planning_state_real_milestone(tmp_path):
    """is_uninitialized_planning_state returns False after user seeds a real milestone."""
    _make_base_target(tmp_path)
    # phase-state still shows harness-init sentinel (user hasn't run phase set yet)
    # but STATE.md has a real milestone — predicate must return False.
    _make_scratch(tmp_path, _INIT_PHASE_STATE)
    _make_planning_real(tmp_path)

    assert is_uninitialized_planning_state(tmp_path) is False


def test_is_uninitialized_planning_state_real_phase_state(tmp_path):
    """is_uninitialized_planning_state returns False when phase-state has been touched."""
    _make_base_target(tmp_path)
    # Simulate user ran 'harness phase set discuss' — epoch sentinel is gone.
    real_phase_state = {**_INIT_PHASE_STATE, "updated_by": "user", "updated_at": "2026-01-01T00:00:00Z"}
    _make_scratch(tmp_path, real_phase_state)
    _make_planning_init(tmp_path)

    assert is_uninitialized_planning_state(tmp_path) is False


# ---------------------------------------------------------------------------
# Tests — roadmap_state_sync_applicable gating
# ---------------------------------------------------------------------------


def test_sync_not_applicable_on_fresh_init(tmp_path):
    """roadmap_state_sync_applicable returns False on template-only .planning/."""
    _make_base_target(tmp_path)
    _make_scratch(tmp_path, _INIT_PHASE_STATE)
    _make_planning_init(tmp_path)

    assert roadmap_state_sync_applicable(tmp_path) is False


def test_sync_applicable_after_real_milestone(tmp_path):
    """roadmap_state_sync_applicable returns True after user seeds a real milestone + phase-state."""
    _make_base_target(tmp_path)
    real_phase_state = {
        **_INIT_PHASE_STATE,
        "updated_by": "developer",
        "updated_at": "2026-06-01T10:00:00Z",
        "current_checkpoint": "CP-01-01",
        "checkpoint_path": ".planning/milestones/01-bootstrap/01-CHECKPOINTS.md",
        "state_path": ".planning/STATE.md",
    }
    _make_scratch(tmp_path, real_phase_state)
    _make_planning_real(tmp_path)

    assert roadmap_state_sync_applicable(tmp_path) is True


# ---------------------------------------------------------------------------
# Tests — end-to-end harness.check() integration
# ---------------------------------------------------------------------------


def test_harness_check_no_sync_error_on_fresh_init(tmp_path):
    """harness.check() must NOT raise 'Roadmap/state sync invariant failed' on fresh init.

    This is the regression test for issue #23.
    """
    import harness  # noqa: PLC0415

    _make_base_target(tmp_path)
    _make_scratch(tmp_path, _INIT_PHASE_STATE)
    _make_planning_init(tmp_path)

    # Must not raise at all (or at least not the state-sync error).
    try:
        harness.check(root=tmp_path)
    except SystemExit as exc:
        msg = str(exc.code or "")
        assert "Roadmap/state sync invariant failed" not in msg, (
            f"harness.check() raised state-sync error on fresh init: {msg!r}"
        )


def test_harness_check_enforces_sync_after_real_milestone(tmp_path):
    """harness.check() MUST enforce the sync invariant after a real milestone is declared.

    We deliberately break STATE.progress.total_phases so the invariant fires.
    """
    import harness  # noqa: PLC0415

    _make_base_target(tmp_path)
    real_phase_state = {
        **_INIT_PHASE_STATE,
        "updated_by": "developer",
        "updated_at": "2026-06-01T10:00:00Z",
        "current_checkpoint": "CP-01-01",
        "checkpoint_path": ".planning/milestones/01-bootstrap/01-CHECKPOINTS.md",
        "state_path": ".planning/STATE.md",
    }
    _make_scratch(tmp_path, real_phase_state)
    # break_sync=True makes STATE.total_phases=99 but ROADMAP has 2 phases.
    _make_planning_real(tmp_path, break_sync=True)

    with pytest.raises(SystemExit) as exc_info:
        harness.check(root=tmp_path)

    msg = str(exc_info.value.code or "")
    assert "Roadmap/state sync invariant failed" in msg, (
        f"Expected state-sync error to fire after real milestone, got: {msg!r}"
    )
