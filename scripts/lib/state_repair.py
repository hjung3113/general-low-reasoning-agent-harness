"""Repair managed marker blocks in ROADMAP.md and STATE.md.

Source of truth for the MVP is whatever the legacy strict-regex parsers can
extract from the current files plus `.scratch/phase-state.json`. The repair
step re-renders the managed-block payload in canonical form.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from lib.managed_block import (
    BEGIN_MARKER_FMT,
    END_MARKER_FMT,
    MissingBlockError,
    parse_blocks,
    render_block,
    replace_block,
)
from lib.roadmap_state import (
    RoadmapPhase,
    parse_frontmatter,
    parse_roadmap_phases,
    parse_state_snapshot,
)


ROADMAP_PATH = ".planning/ROADMAP.md"
STATE_PATH = ".planning/STATE.md"
PHASE_STATE_PATH = ".scratch/phase-state.json"

ROADMAP_PHASES_SLUG = "roadmap-phases"
STATE_CURRENT_SLUG = "state-current"


@dataclass
class RepairReport:
    files_updated: list[str] = field(default_factory=list)
    markers_added: list[str] = field(default_factory=list)
    payloads_canonicalized: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def canonical_roadmap_phases_payload(phases: list[RoadmapPhase]) -> str:
    lines = []
    for phase in phases:
        mark = "x" if phase.completed else " "
        lines.append(f"- [{mark}] **Phase {phase.number}: {phase.title}**\n")
    return "".join(lines)


def canonical_state_current_payload(
    *,
    phase: int | None,
    phase_title: str,
    checkpoint: str | None,
    checkpoint_path: str | None,
) -> str:
    lines = ["## Current Position\n\n"]
    if phase is not None:
        title_suffix = f" - {phase_title}" if phase_title else ""
        lines.append(f"- **Phase**: {phase}{title_suffix}\n")
    lines.append("\n## Active Checkpoint\n\n")
    if checkpoint:
        lines.append(f"- **Checkpoint**: {checkpoint}\n")
    if checkpoint_path:
        lines.append(f"- **Checkpoint file**: `{checkpoint_path}`\n")
    return "".join(lines)


def repair(root: Path) -> RepairReport:  # noqa: ARG001 - implemented in Task 4
    raise NotImplementedError
