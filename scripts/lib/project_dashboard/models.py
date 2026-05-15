"""Data models for the static project dashboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class StateSummary:
    milestone: str = "Unknown milestone"
    milestone_name: str = "Unknown milestone"
    status: str = "Unknown status"
    last_updated: str = "Unknown"
    progress_percent: int = 0
    total_phases: int = 0
    completed_phases: int = 0
    active_checkpoint: str = "Unknown checkpoint"
    checkpoint_file: str = ""
    blockers: list[str] = field(default_factory=list)
    next_action: str = "No next action recorded."


@dataclass
class RoadmapPhase:
    title: str
    summary: str
    completed: bool
    raw_line: str


@dataclass
class PhaseDocument:
    phase_dir: str
    files: dict[str, str]
    headings: list[str]


@dataclass
class IssueCard:
    title: str
    path: str
    labels: list[str]


@dataclass
class DocumentLink:
    title: str
    path: str
    category: str


@dataclass
class RequirementCard:
    requirement_id: str
    summary: str


@dataclass
class DecisionRecord:
    decision_id: str
    status: str
    decision: str
    source: str
    scope: str


@dataclass
class VerificationRecord:
    date: str
    phase: str
    check: str
    result: str
    notes: str


@dataclass
class ProjectMemory:
    one_liner: str = "No project one-liner recorded."
    scope: list[str] = field(default_factory=list)
    requirements: list[RequirementCard] = field(default_factory=list)
    decisions: list[DecisionRecord] = field(default_factory=list)
    verification: list[VerificationRecord] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)


@dataclass
class DashboardData:
    root: Path
    state: StateSummary
    roadmap_phases: list[RoadmapPhase]
    phase_documents: list[PhaseDocument]
    phase_state: dict[str, object]
    issues: list[IssueCard]
    documents: list[DocumentLink]
    memory: ProjectMemory
    warnings: list[str]
    active_checkpoint: str
