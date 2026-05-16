"""Repair managed marker blocks in ROADMAP.md and STATE.md.

Source of truth for the MVP is whatever the legacy strict-regex parsers can
extract from the current files plus `.scratch/phase-state.json`. The repair
step re-renders the managed-block payload in canonical form.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from lib.atomic_io import atomic_write_text
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

# Regex that matches a phase checkbox line anywhere in plain text.
_PHASE_LINE_RE = re.compile(
    r"^-\s+\[[ xX]\]\s+\*\*Phase\s+\d+:\s*[^*]+\*\*",
    re.MULTILINE,
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


def _wrap_section_in_block(
    text: str,
    *,
    slug: str,
    section_start: str,
    section_end_markers: tuple[str, ...],
    payload: str,
) -> tuple[str, bool]:
    """Insert a managed block in place of `section_start`..(next of section_end_markers).

    Returns (new_text, added_or_replaced).
    """
    blocks = parse_blocks(text)
    if slug in blocks:
        new_text = replace_block(text, slug, payload)
        return new_text, new_text != text

    start_idx = text.find(section_start)
    if start_idx < 0:
        # Append at end if section absent.
        rendered = render_block(slug, payload)
        if not text.endswith("\n"):
            text = text + "\n"
        return text + "\n" + rendered, True

    # Find end of the section: first occurrence of any end marker AFTER start_idx,
    # else end of file.
    payload_start = text.find("\n", start_idx)
    payload_start = payload_start + 1 if payload_start >= 0 else len(text)
    end_idx = len(text)
    for marker in section_end_markers:
        candidate = text.find(marker, payload_start)
        if candidate >= 0 and candidate < end_idx:
            end_idx = candidate

    rendered = render_block(slug, payload)
    new_text = (
        text[: payload_start]
        + rendered
        + text[end_idx:]
    )
    return new_text, True


def _phases_inside_block(text: str, slug: str) -> list[RoadmapPhase] | None:
    """Return phases parsed ONLY from the managed block's payload, or None if block absent.

    The block payload contains raw phase checkbox lines without a ``## Phases``
    heading, so we match them directly with the phase-line regex rather than
    delegating to ``parse_roadmap_phases`` (which requires a section heading).
    """
    blocks = parse_blocks(text)
    if slug not in blocks:
        return None
    payload = blocks[slug].payload
    pattern = re.compile(
        r"^-\s+\[(?P<mark>[ xX])\]\s+\*\*Phase\s+(?P<number>\d+):\s*(?P<title>[^*]+)\*\*",
        re.MULTILINE,
    )
    phases: list[RoadmapPhase] = []
    for match in pattern.finditer(payload):
        phases.append(
            RoadmapPhase(
                number=int(match.group("number")),
                title=match.group("title").strip(),
                completed=match.group("mark").lower() == "x",
            )
        )
    return phases


def _orphan_phase_lines(text: str, slug: str) -> list[str]:
    """Return phase-pattern lines that exist OUTSIDE the managed block."""
    blocks = parse_blocks(text)
    if slug not in blocks:
        return []
    block = blocks[slug]
    # Remove the block region from the text before scanning.
    remainder = text[: block.start] + text[block.end :]
    return _PHASE_LINE_RE.findall(remainder)


def _phase_title_lookup(phases: list[RoadmapPhase], number: int | None) -> str:
    if number is None:
        return ""
    for phase in phases:
        if phase.number == number:
            return phase.title
    return ""


def repair(root: Path) -> RepairReport:
    report = RepairReport()
    roadmap_path = root / ROADMAP_PATH
    state_path = root / STATE_PATH
    phase_state_path = root / PHASE_STATE_PATH

    for path in (roadmap_path, state_path, phase_state_path):
        if not path.exists():
            report.warnings.append(f"{path.relative_to(root).as_posix()} missing")

    if not roadmap_path.exists() or not state_path.exists():
        return report

    roadmap_text = roadmap_path.read_text(encoding="utf-8")
    state_text = state_path.read_text(encoding="utf-8")

    # Use phases inside the block when it already exists, to avoid pulling in
    # orphan phase lines from elsewhere in the file.
    phases_from_block = _phases_inside_block(roadmap_text, ROADMAP_PHASES_SLUG)
    if phases_from_block is not None:
        phases = phases_from_block
    else:
        phases = parse_roadmap_phases(roadmap_text)
    snapshot = parse_state_snapshot(state_text)
    phase_state: dict = {}
    if phase_state_path.exists():
        try:
            phase_state = json.loads(phase_state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            report.warnings.append(f"phase-state.json invalid: {exc}")

    roadmap_payload = canonical_roadmap_phases_payload(phases)

    # Warn about orphan phase lines that sit outside the managed block.
    for orphan_line in _orphan_phase_lines(roadmap_text, ROADMAP_PHASES_SLUG):
        report.warnings.append(
            f"roadmap phase line outside managed block: {orphan_line}; "
            "move it inside or delete it"
        )
    new_roadmap, roadmap_changed = _wrap_section_in_block(
        roadmap_text,
        slug=ROADMAP_PHASES_SLUG,
        section_start="## Phases",
        section_end_markers=("\n## ",),
        payload=roadmap_payload,
    )

    state_payload = canonical_state_current_payload(
        phase=snapshot.active_phase,
        phase_title=_phase_title_lookup(phases, snapshot.active_phase),
        checkpoint=snapshot.checkpoint or phase_state.get("current_checkpoint"),
        checkpoint_path=snapshot.checkpoint_path or phase_state.get("checkpoint_path"),
    )

    blocks = parse_blocks(state_text)
    if STATE_CURRENT_SLUG in blocks:
        new_state = replace_block(state_text, STATE_CURRENT_SLUG, state_payload)
        state_changed = new_state != state_text
    else:
        new_state, state_changed = _wrap_section_in_block(
            state_text,
            slug=STATE_CURRENT_SLUG,
            section_start="## Current Position",
            section_end_markers=("\n## Session Continuity", "\n## Notes", "\n---\n"),
            payload=state_payload,
        )
        if state_changed:
            report.markers_added.append(STATE_PATH)

    if roadmap_changed:
        # T0-A atomic write: tempfile + fsync + os.replace.
        atomic_write_text(roadmap_path, new_roadmap)
        report.files_updated.append(ROADMAP_PATH)
        if ROADMAP_PHASES_SLUG not in parse_blocks(roadmap_text):
            report.markers_added.append(ROADMAP_PATH)
        else:
            report.payloads_canonicalized.append(ROADMAP_PATH)

    if state_changed:
        # T0-A atomic write: tempfile + fsync + os.replace.
        atomic_write_text(state_path, new_state)
        if STATE_PATH not in report.files_updated:
            report.files_updated.append(STATE_PATH)
        if STATE_CURRENT_SLUG in blocks:
            report.payloads_canonicalized.append(STATE_PATH)

    return report
