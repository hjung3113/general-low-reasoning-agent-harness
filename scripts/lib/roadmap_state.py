"""Roadmap/state markdown parsing and sync checks."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoadmapPhase:
    number: int
    title: str
    completed: bool


@dataclass(frozen=True)
class StateSnapshot:
    total_phases: int | None
    completed_phases: int | None
    percent: int | None
    active_phase: int | None
    checkpoint: str | None
    checkpoint_path: str | None


# ---------------------------------------------------------------------------
# Path helpers (stdlib-only)
# ---------------------------------------------------------------------------


def normalize_path(path: str) -> str:
    normalized = os.path.normpath(path).replace(os.sep, "/")
    if normalized == "." or normalized.startswith("../") or normalized == "..":
        raise ValueError(f"Unsafe relative path: {path}")
    if path.endswith("/") and not normalized.endswith("/"):
        normalized += "/"
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


# ---------------------------------------------------------------------------
# Markdown/frontmatter parsing
# ---------------------------------------------------------------------------


def split_frontmatter_pair(line: str) -> tuple[str, object]:
    if ":" not in line:
        return line.strip(), ""
    key, raw_value = line.split(":", 1)
    value = raw_value.strip().strip('"')
    parsed: object = int(value) if re.fullmatch(r"-?\d+", value) else value
    return key.strip(), parsed


def int_value(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value):
        return int(value)
    return None


def markdown_section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    next_heading = re.search(r"^##\s+", text[match.end() :], re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[match.end() : end]


def parse_frontmatter(text: str) -> dict[str, object]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    data: dict[str, object] = {}
    current_map: dict[str, object] | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if not line.strip():
            continue
        if not line.startswith(" ") and line.endswith(":"):
            current_map = {}
            data[line[:-1].strip()] = current_map
            continue
        if not line.startswith(" "):
            key, value = split_frontmatter_pair(line)
            data[key] = value
            current_map = None
            continue
        if current_map is not None:
            key, value = split_frontmatter_pair(line.strip())
            current_map[key] = value
    return data


def parse_roadmap_phases(text: str) -> list[RoadmapPhase]:
    section = markdown_section(text, "Phases")
    phases: list[RoadmapPhase] = []
    pattern = re.compile(r"^-\s+\[(?P<mark>[ xX])\]\s+\*\*Phase\s+(?P<number>\d+):\s*(?P<title>[^*]+)\*\*")
    for line in section.splitlines():
        match = pattern.match(line.strip())
        if match:
            phases.append(
                RoadmapPhase(
                    number=int(match.group("number")),
                    title=match.group("title").strip(),
                    completed=match.group("mark").lower() == "x",
                )
            )
    return phases


def parse_state_snapshot(text: str) -> StateSnapshot:
    frontmatter = parse_frontmatter(text)
    progress = frontmatter.get("progress", {})
    checkpoint_match = re.search(r"^-\s+\*\*Checkpoint\*\*:\s*([A-Za-z0-9_-]+)\b", text, re.MULTILINE)
    checkpoint_path_match = re.search(r"^-\s+\*\*Checkpoint file\*\*:\s*`([^`]+)`", text, re.MULTILINE)
    active_phase_match = re.search(r"^-\s+\*\*Phase\*\*:\s*(\d+)\b", text, re.MULTILINE)
    return StateSnapshot(
        total_phases=int_value(progress.get("total_phases")),
        completed_phases=int_value(progress.get("completed_phases")),
        percent=int_value(progress.get("percent")),
        active_phase=int(active_phase_match.group(1)) if active_phase_match else None,
        checkpoint=checkpoint_match.group(1) if checkpoint_match else None,
        checkpoint_path=normalize_path(checkpoint_path_match.group(1)) if checkpoint_path_match else None,
    )


# ---------------------------------------------------------------------------
# Sync checks
# ---------------------------------------------------------------------------


def check_roadmap_state_sync(root: Path) -> None:
    findings = find_roadmap_state_sync_findings(root)
    if findings:
        raise SystemExit("Roadmap/state sync invariant failed: " + "; ".join(findings))


def roadmap_state_sync_applicable(root: Path) -> bool:
    state_path = root / ".planning/STATE.md"
    phase_state_path = root / ".scratch/phase-state.json"
    roadmap_path = root / ".planning/ROADMAP.md"
    if not state_path.exists() or not roadmap_path.exists() or not phase_state_path.exists():
        return False
    state = parse_state_snapshot(state_path.read_text(encoding="utf-8"))
    from lib.state_diagnostics import load_state_json
    phase_state = load_state_json(phase_state_path)
    return any(
        (
            state.total_phases is not None,
            state.completed_phases is not None,
            state.percent is not None,
            state.active_phase is not None,
            state.checkpoint is not None,
            state.checkpoint_path is not None,
            phase_state.get("state_path") is not None,
            phase_state.get("checkpoint_path") is not None,
            phase_state.get("current_checkpoint") is not None,
        )
    )


def find_roadmap_state_sync_findings(root: Path) -> list[str]:
    roadmap_path = root / ".planning/ROADMAP.md"
    state_path = root / ".planning/STATE.md"
    phase_state_path = root / ".scratch/phase-state.json"
    findings: list[str] = []

    for path in (roadmap_path, state_path, phase_state_path):
        if not path.exists():
            findings.append(f"{path.relative_to(root)} is missing")
    if findings:
        return findings

    phases = parse_roadmap_phases(roadmap_path.read_text(encoding="utf-8"))
    state = parse_state_snapshot(state_path.read_text(encoding="utf-8"))
    from lib.state_diagnostics import load_state_json
    phase_state = load_state_json(phase_state_path)

    if not phases:
        findings.append(".planning/ROADMAP.md has no parseable phase checklist under ## Phases")
        return findings

    total_phases = len(phases)
    completed_phases = sum(1 for phase in phases if phase.completed)
    percent = round((completed_phases / total_phases) * 100) if total_phases else 0
    active_phase = next((phase.number for phase in phases if not phase.completed), None)

    if state.total_phases != total_phases:
        findings.append(
            f".planning/STATE.md progress.total_phases={state.total_phases} does not match "
            f".planning/ROADMAP.md total phases={total_phases}"
        )
    if state.completed_phases != completed_phases:
        findings.append(
            f".planning/STATE.md progress.completed_phases={state.completed_phases} does not match "
            f".planning/ROADMAP.md completed phases={completed_phases}"
        )
    if state.percent != percent:
        findings.append(
            f".planning/STATE.md progress.percent={state.percent} does not match "
            f".planning/ROADMAP.md derived percent={percent}"
        )
    if active_phase is not None and state.active_phase != active_phase:
        findings.append(
            f".planning/STATE.md active phase={state.active_phase} does not match "
            f".planning/ROADMAP.md first incomplete phase={active_phase}"
        )

    expected_state_path = ".planning/STATE.md"
    actual_state_path = phase_state.get("state_path")
    if actual_state_path != expected_state_path:
        findings.append(f".scratch/phase-state.json state_path={actual_state_path!r} must be {expected_state_path!r}")
    if state.checkpoint_path and phase_state.get("checkpoint_path") != state.checkpoint_path:
        findings.append(
            f".scratch/phase-state.json checkpoint_path={phase_state.get('checkpoint_path')!r} does not match "
            f".planning/STATE.md checkpoint file={state.checkpoint_path!r}"
        )
    if state.checkpoint and phase_state.get("current_checkpoint") != state.checkpoint:
        findings.append(
            f".scratch/phase-state.json current_checkpoint={phase_state.get('current_checkpoint')!r} does not match "
            f".planning/STATE.md checkpoint={state.checkpoint!r}"
        )

    plan_path = phase_state.get("plan_path")
    if isinstance(plan_path, str) and state.checkpoint_path:
        plan_parent = PurePosixPath(normalize_path(plan_path)).parent
        checkpoint_parent = PurePosixPath(normalize_path(state.checkpoint_path)).parent
        if plan_parent != checkpoint_parent:
            findings.append(
                f".scratch/phase-state.json plan_path={plan_path!r} must point inside active phase folder "
                f"{str(checkpoint_parent)!r}"
            )

    return findings
