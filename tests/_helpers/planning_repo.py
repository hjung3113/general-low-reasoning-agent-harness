"""Shared minimal planning-repo factory for parser-unification tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def make_minimal_planning_repo(
    tmp_path: Path,
    *,
    phase_id: str = "02b",
    phase_folder: str = "02b-hardening",
    roadmap_title: str = "Hardening",
    checkpoint_id: str = "CP-02b-01",
    schema_version_line: str = "planning_doc_schema_version: 1\n",
    phase_state_overrides: dict[str, Any] | None = None,
) -> Path:
    (tmp_path / ".planning").mkdir()
    (tmp_path / f".planning/milestones/{phase_folder}").mkdir(parents=True)
    (tmp_path / ".planning/STATE.md").write_text(
        f"---\n{schema_version_line}---\n"
        "# STATE\n"
        "## Current Position\n"
        f"- **Phase**: {phase_id.lstrip('0') or phase_id} - {roadmap_title}.\n"
        "## Active Checkpoint\n"
        f"- **Checkpoint**: {checkpoint_id} - smoke.\n"
        f"- **Checkpoint file**: `.planning/milestones/{phase_folder}/{phase_id}-CHECKPOINTS.md`.\n",
        encoding="utf-8",
    )
    cp_text = f"## {checkpoint_id} - smoke\n- **Status**: in_progress\n"
    (tmp_path / f".planning/milestones/{phase_folder}/{phase_id}-CHECKPOINTS.md").write_text(cp_text, encoding="utf-8")
    (tmp_path / f".planning/milestones/{phase_folder}/{phase_id}-VERIFICATION.md").write_text("# Verification\n")
    (tmp_path / ".planning/ROADMAP.md").write_text(
        f"## Phases\n- [ ] **Phase {phase_id.lstrip('0') or phase_id}: {roadmap_title}** - intern\n",
        encoding="utf-8",
    )
    (tmp_path / ".scratch").mkdir()
    base_state = {
        "state_schema_version": 2,
        "phase": "discuss",
        "current_checkpoint": checkpoint_id,
        "checkpoint_path": f".planning/milestones/{phase_folder}/{phase_id}-CHECKPOINTS.md",
        "state_path": ".planning/STATE.md",
        "automation_mode": "manual",
        "updated_at": "2026-05-20T00:00:00.000000000Z",
        "updated_by": "test",
    }
    if phase_state_overrides:
        base_state.update(phase_state_overrides)
    (tmp_path / ".scratch/phase-state.json").write_text(json.dumps(base_state), encoding="utf-8")
    return tmp_path
