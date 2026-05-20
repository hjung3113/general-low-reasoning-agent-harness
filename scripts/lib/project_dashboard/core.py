#!/usr/bin/env python3
"""Generate a static HTML dashboard from planning and phase-state documents."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

# dual import: callers use either 'lib.X' (scripts/ via sys.path injection) or 'scripts.lib.X' (pytest from repo root)
try:
    from scripts.lib.planning_grammar import (
        canonical_phase_id,
        display_phase_id,
        heading_matches,
        parse_frontmatter as _parse_frontmatter_grammar,
        parse_roadmap_phase_bullets,
    )
except ModuleNotFoundError:
    from lib.planning_grammar import (  # type: ignore[no-redef]
        canonical_phase_id,
        display_phase_id,
        heading_matches,
        parse_frontmatter as _parse_frontmatter_grammar,
        parse_roadmap_phase_bullets,
    )

try:
    from scripts.lib.planning_status import ProjectionError, load_projection, projection_to_dict
except ModuleNotFoundError:
    from lib.planning_status import ProjectionError, load_projection, projection_to_dict  # type: ignore[no-redef]
try:
    from scripts.lib.project_dashboard.renderer import render_html
except ModuleNotFoundError:
    from lib.project_dashboard.renderer import render_html  # type: ignore[no-redef]
try:
    from scripts.lib.project_dashboard.models import (
        DashboardData,
        DashboardAction,
        DashboardWarning,
        DecisionRecord,
        DocumentLink,
        IssueCard,
        PhaseDocument,
        ProjectMemory,
        RequirementCard,
        RoadmapPhase,
        StateSummary,
        VerificationRecord,
    )
except ModuleNotFoundError:
    from lib.project_dashboard.models import (  # type: ignore[no-redef]
        DashboardData,
        DashboardAction,
        DashboardWarning,
        DecisionRecord,
        DocumentLink,
        IssueCard,
        PhaseDocument,
        ProjectMemory,
        RequirementCard,
        RoadmapPhase,
        StateSummary,
        VerificationRecord,
    )


DEFAULT_OUTPUT = Path(".scratch/reports/project-dashboard.html")

DEFAULT_DASHBOARD_PORT = 8765
DASHBOARD_ACTIONS = [
    DashboardAction(
        action_id="check",
        label="Run Check",
        description="Validate installed harness structure and the current planning gate.",
        command=[sys.executable, "scripts/harness.py", "check"],
        intent="Validate the harness and planning state before edits.",
    ),
    DashboardAction(
        action_id="next",
        label="Show Next",
        description="Ask the harness for the next safe user or agent action.",
        command=[sys.executable, "scripts/harness.py", "next"],
        intent="Inspect the current gate and next action.",
    ),
    DashboardAction(
        action_id="run",
        label="Step Workflow",
        description="Run the safe workflow stepper; it stops when user approval is required.",
        command=[sys.executable, "scripts/harness.py", "run"],
        intent="Advance only harness-approved workflow steps.",
        confirmation="This can advance harness workflow state. Continue?",
    ),
    DashboardAction(
        action_id="doctor",
        label="Run Doctor",
        description="Run read-only diagnostics for planning and harness drift.",
        command=[sys.executable, "scripts/harness.py", "doctor"],
        intent="Diagnose drift without mutating project files.",
    ),
    DashboardAction(
        action_id="snapshot",
        label="Write Snapshot",
        description="Regenerate the local static dashboard snapshot under .scratch/reports/.",
        command=[sys.executable, "scripts/project_dashboard.py"],
        intent="Create a shareable local HTML report.",
        confirmation="This writes .scratch/reports/project-dashboard.html. Continue?",
    ),
]


# Re-export from planning_grammar so existing callers of core.parse_frontmatter keep working.
parse_frontmatter = _parse_frontmatter_grammar


def parse_roadmap_phases(text: str) -> list[RoadmapPhase]:
    return [
        RoadmapPhase(
            title=f"Phase {display_phase_id(b.phase_id)}: {b.title}",
            summary=b.summary,
            completed=b.completed,
            raw_line=b.raw_line,
            phase_id=b.phase_id,
        )
        for b in parse_roadmap_phase_bullets(text)
    ]


def parse_headings(text: str) -> list[str]:
    headings: list[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            if title:
                headings.append(title)
    return headings


def first_heading(text: str, fallback: str) -> str:
    headings = parse_headings(text)
    return headings[0] if headings else fallback


def checkpoint_id(value: str) -> str:
    match = re.search(r"\bCP-[0-9]+(?:-[0-9]+)?\b", value)
    return match.group(0) if match else value


def load_dashboard_data(root: Path) -> DashboardData:
    warnings: list[DashboardWarning] = []
    state_path = root / ".planning/STATE.md"
    roadmap_path = root / ".planning/ROADMAP.md"
    phase_state_path = root / ".scratch/phase-state.json"

    state_text = read_optional_text(state_path, warnings)
    roadmap_text = read_optional_text(roadmap_path, warnings)
    phase_state, ps_warning = load_phase_state(phase_state_path)
    phase_state_usable = ps_warning is None
    if ps_warning is not None:
        warnings.append(ps_warning)

    state = parse_state_summary(state_text)
    roadmap_phases = parse_roadmap_phases(roadmap_text)
    phase_documents = load_phase_documents(root)
    issues = load_issues(root)
    documents = load_documents(root)
    memory = load_project_memory(root)

    projection: dict[str, object] | None = None
    try:
        projection = projection_to_dict(load_projection(root))
    except ProjectionError as exc:
        warnings.append(
            DashboardWarning(
                code="projection_failed",
                severity="blocking",
                message=f"phase status projection failed: {exc}",
                paths=[],
            )
        )

    warnings.extend(check_consistency(root, state, roadmap_phases, phase_documents, phase_state, issues, documents, roadmap_text, phase_state_usable=phase_state_usable))
    if projection is not None:
        warnings.extend(format_projection_warnings(projection))

    return DashboardData(
        root=root,
        state=state,
        roadmap_phases=roadmap_phases,
        phase_documents=phase_documents,
        phase_state=phase_state,
        issues=issues,
        documents=documents,
        memory=memory,
        warnings=warnings,
        active_checkpoint=str(projection.get("active_checkpoint_id") if projection else checkpoint_id(state.active_checkpoint)),
    )


def dashboard_data_to_json(data: DashboardData) -> dict[str, object]:
    phase_state = data.phase_state
    return {
        "project": {
            "root": str(data.root),
            "milestone": data.state.milestone,
            "milestone_name": data.state.milestone_name,
            "status": data.state.status,
            "last_updated": data.state.last_updated,
            "progress_percent": data.state.progress_percent,
            "completed_phases": data.state.completed_phases,
            "total_phases": data.state.total_phases,
            "active_checkpoint": data.active_checkpoint,
            "checkpoint_label": data.state.active_checkpoint,
            "checkpoint_file": data.state.checkpoint_file,
            "next_action": data.state.next_action,
            "blockers": data.state.blockers,
        },
        "gate": {
            "phase": str(phase_state.get("phase", "unknown")),
            "plan_id": str(phase_state.get("plan_id", "unknown")),
            "approved": phase_state.get("approved") is True,
            "approved_by": str(phase_state.get("approved_by", "unknown")),
            "approved_at": str(phase_state.get("approved_at", "unknown")),
            "automation_mode": str(phase_state.get("automation_mode", "manual")),
            "current_checkpoint": str(phase_state.get("current_checkpoint", "unknown")),
            "next_action": str(phase_state.get("next_action", data.state.next_action)),
            "allowed_paths": string_list(phase_state.get("allowed_paths")),
            "blocked_paths": string_list(phase_state.get("blocked_paths")),
            "acceptance_criteria": string_list(phase_state.get("acceptance_criteria")),
            "verification": string_list(phase_state.get("verification")),
        },
        "roadmap": [
            {
                "title": phase.title,
                "summary": phase.summary,
                "completed": phase.completed,
                "raw_line": phase.raw_line,
            }
            for phase in data.roadmap_phases
        ],
        "memory": {
            "one_liner": data.memory.one_liner,
            "scope": data.memory.scope,
            "requirements": [
                {"id": item.requirement_id, "summary": item.summary}
                for item in data.memory.requirements
            ],
            "decisions": [
                {
                    "id": item.decision_id,
                    "status": item.status,
                    "decision": item.decision,
                    "source": item.source,
                    "scope": item.scope,
                }
                for item in data.memory.decisions
            ],
            "verification": [
                {
                    "date": item.date,
                    "phase": item.phase,
                    "check": item.check,
                    "result": item.result,
                    "notes": item.notes,
                }
                for item in data.memory.verification
            ],
            "concerns": data.memory.concerns,
        },
        "phase_documents": [
            {"phase_dir": item.phase_dir, "files": item.files, "headings": item.headings}
            for item in data.phase_documents
        ],
        "issues": [
            {"title": item.title, "path": item.path, "labels": item.labels}
            for item in data.issues
        ],
        "documents": [
            {"title": item.title, "path": item.path, "category": item.category}
            for item in data.documents
        ],
        "warnings": [
            {"code": w.code, "severity": w.severity, "message": w.message, "paths": w.paths}
            for w in data.warnings
        ],
        "actions": [
            {
                "id": action.action_id,
                "label": action.label,
                "description": action.description,
                "command": " ".join(action.command),
                "intent": action.intent,
                "confirmation": action.confirmation,
            }
            for action in DASHBOARD_ACTIONS
        ],
    }


def string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value]
    return []


def read_optional_text(path: Path, warnings: list[DashboardWarning]) -> str:
    if not path.exists():
        warnings.append(
            DashboardWarning(
                code="missing_optional_file",
                severity="warning",
                message=f"Missing optional file: {path}",
                paths=[str(path)],
            )
        )
        return ""
    return path.read_text(encoding="utf-8")


def parse_state_summary(text: str) -> StateSummary:
    frontmatter = parse_frontmatter(text)
    summary = StateSummary(
        milestone=frontmatter.get("milestone", "Unknown milestone"),
        milestone_name=frontmatter.get("milestone_name", "Unknown milestone"),
        status=frontmatter.get("status", "Unknown status"),
        last_updated=frontmatter.get("last_updated", "Unknown"),
        progress_percent=parse_int(frontmatter.get("progress.percent"), 0),
        total_phases=parse_int(frontmatter.get("progress.total_phases"), 0),
        completed_phases=parse_int(frontmatter.get("progress.completed_phases"), 0),
    )

    checkpoint = re.search(r"- \*\*Checkpoint\*\*: (?P<value>.+)", text)
    checkpoint_file = re.search(r"- \*\*Checkpoint file\*\*: `(?P<value>[^`]+)`", text)
    if checkpoint:
        summary.active_checkpoint = checkpoint.group("value").strip()
    if checkpoint_file:
        summary.checkpoint_file = checkpoint_file.group("value").strip()

    summary.blockers = parse_section_bullets(text, "Blockers")
    if not summary.blockers:
        summary.blockers = ["No blockers recorded."]

    next_action = parse_section_paragraph(text, "Next Action")
    if next_action:
        summary.next_action = next_action

    return summary


def parse_int(value: str | None, fallback: int) -> int:
    if value is None:
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback


def parse_section_bullets(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    in_section = False
    bullets: list[str] = []
    for line in lines:
        if line.startswith("#"):
            head_text = line.lstrip("#").strip()
            if heading_matches(head_text, heading):
                in_section = True
            else:
                if in_section:
                    break
                # different heading, not yet in section
            continue
        if in_section and line.strip().startswith("- "):
            bullets.append(line.strip()[2:].strip())
    return bullets


def parse_section_paragraph(text: str, heading: str) -> str:
    lines = text.splitlines()
    in_section = False
    paragraph: list[str] = []
    for line in lines:
        stripped = line.strip()
        if line.startswith("#"):
            head_text = line.lstrip("#").strip()
            if heading_matches(head_text, heading):
                in_section = True
            else:
                if in_section:
                    break
            continue
        if in_section and stripped:
            paragraph.append(stripped)
    return " ".join(paragraph)


def parse_section_until_heading(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    in_section = False
    section: list[str] = []
    for line in lines:
        if line.startswith("#"):
            head_text = line.lstrip("#").strip()
            if heading_matches(head_text, heading):
                in_section = True
            else:
                if in_section:
                    break
            continue
        if in_section:
            section.append(line)
    return section


def parse_markdown_table(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    table_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("|") and line.strip().endswith("|")]
    if len(table_lines) < 2:
        return rows
    headers = [cell.strip() for cell in table_lines[0].strip("|").split("|")]
    for line in table_lines[2:]:
        values = [clean_inline_markdown(cell.strip()) for cell in line.strip("|").split("|")]
        if len(values) != len(headers):
            continue
        rows.append(dict(zip(headers, values)))
    return rows


def clean_inline_markdown(value: str) -> str:
    return value.replace("`", "").replace("\\|", "|")


def load_project_memory(root: Path) -> ProjectMemory:
    project_text = read_text_if_exists(root / ".planning/PROJECT.md")
    requirements_text = read_text_if_exists(root / ".planning/REQUIREMENTS.md")
    decisions_text = read_text_if_exists(root / ".planning/DECISIONS.md")
    verification_text = read_text_if_exists(root / ".planning/VERIFICATION.md")
    concerns_text = read_text_if_exists(root / ".planning/codebase/CONCERNS.md")
    return ProjectMemory(
        one_liner=parse_section_paragraph(project_text, "One-Liner") or "No project one-liner recorded.",
        scope=parse_section_bullets(project_text, "Scope"),
        requirements=parse_requirements(requirements_text),
        decisions=parse_decisions(decisions_text),
        verification=parse_verification(verification_text),
        concerns=parse_section_bullets(concerns_text, "CONCERNS"),
    )


def read_text_if_exists(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def parse_requirements(text: str) -> list[RequirementCard]:
    requirements: list[RequirementCard] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("## "):
            continue
        requirement_id = line.lstrip("#").strip()
        paragraph: list[str] = []
        for following in lines[index + 1 :]:
            if following.startswith("#"):
                break
            if following.strip():
                paragraph.append(following.strip())
        requirements.append(RequirementCard(requirement_id=requirement_id, summary=" ".join(paragraph)))
    return requirements


def parse_decisions(text: str) -> list[DecisionRecord]:
    records: list[DecisionRecord] = []
    for row in parse_markdown_table(text):
        records.append(
            DecisionRecord(
                decision_id=row.get("ID", ""),
                status=row.get("Status", ""),
                decision=row.get("Decision", ""),
                source=row.get("Source", ""),
                scope=row.get("Scope", ""),
            )
        )
    return records


def parse_verification(text: str) -> list[VerificationRecord]:
    records: list[VerificationRecord] = []
    for row in parse_markdown_table(text):
        records.append(
            VerificationRecord(
                date=row.get("Date", ""),
                phase=row.get("Phase", ""),
                check=row.get("Check", ""),
                result=row.get("Result", ""),
                notes=row.get("Notes", ""),
            )
        )
    return records


def load_phase_state(path: Path) -> tuple[dict[str, object], DashboardWarning | None]:
    if not path.exists():
        return {}, None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {}, DashboardWarning(
            code="phase_state_malformed_json",
            severity="blocking",
            message=f"phase-state.json is malformed JSON: {exc.msg} (line {exc.lineno}, col {exc.colno})",
            paths=[".scratch/phase-state.json"],
        )
    if not isinstance(loaded, dict):
        return {}, DashboardWarning(
            code="phase_state_not_object",
            severity="blocking",
            message="phase-state.json must contain a JSON object",
            paths=[".scratch/phase-state.json"],
        )
    return loaded, None


def format_projection_warnings(projection: dict[str, object]) -> list[DashboardWarning]:
    out: list[DashboardWarning] = []
    for w in projection.get("warnings") or []:
        if not isinstance(w, dict):
            continue
        out.append(
            DashboardWarning(
                code=str(w.get("code", "unknown_projection_warning")),
                severity=str(w.get("severity", "warning")),
                message=str(w.get("message", "Planning projection warning.")),
                paths=[str(p) for p in (w.get("paths") or [])],
            )
        )
    return out


def load_phase_documents(root: Path) -> list[PhaseDocument]:
    phases_root = root / ".planning/phases"
    if not phases_root.exists():
        return []
    documents: list[PhaseDocument] = []
    for phase_dir in sorted(item for item in phases_root.iterdir() if item.is_dir()):
        files: dict[str, str] = {}
        headings: list[str] = []
        for path in sorted(phase_dir.glob("*.md")):
            relative = path.relative_to(root).as_posix()
            files[path.name] = relative
            headings.extend(parse_headings(path.read_text(encoding="utf-8"))[:2])
        for path in sorted(phase_dir.glob("plans/*-PLAN.md")):
            relative = path.relative_to(root).as_posix()
            if path.name in files:
                continue  # top-level dominant
            files[path.name] = relative
            headings.extend(parse_headings(path.read_text(encoding="utf-8"))[:2])
        documents.append(PhaseDocument(phase_dir=phase_dir.relative_to(root).as_posix(), files=files, headings=headings))
    return documents


def load_issues(root: Path) -> list[IssueCard]:
    issues: list[IssueCard] = []
    scratch = root / ".scratch"
    if not scratch.exists():
        return issues
    for path in sorted(scratch.glob("**/issues/*.md")):
        text = path.read_text(encoding="utf-8")
        labels = [line.split(":", 1)[1].strip() for line in text.splitlines() if line.lower().startswith("- label:")]
        issues.append(IssueCard(title=first_heading(text, path.stem), path=path.relative_to(root).as_posix(), labels=labels))
    return issues


def load_documents(root: Path) -> list[DocumentLink]:
    candidates: list[Path] = []
    for path in (root / "README.md", root / "AGENTS.md"):
        if path.exists():
            candidates.append(path)
    docs_root = root / "docs"
    if docs_root.exists():
        candidates.extend(sorted(docs_root.glob("**/*.md")))
    codebase_root = root / ".planning/codebase"
    if codebase_root.exists():
        candidates.extend(sorted(codebase_root.glob("*.md")))

    documents: list[DocumentLink] = []
    seen: set[str] = set()
    for path in candidates:
        relative = path.relative_to(root).as_posix()
        if relative in seen:
            continue
        seen.add(relative)
        text = path.read_text(encoding="utf-8")
        documents.append(DocumentLink(title=first_heading(text, path.stem), path=relative, category=document_category(relative)))
    return documents


def document_category(relative_path: str) -> str:
    if relative_path in {"README.md", "AGENTS.md"}:
        return "root"
    if relative_path.startswith(".planning/codebase/"):
        return "codebase"
    if relative_path.startswith("docs/agents/"):
        return "agent docs"
    if relative_path.startswith("docs/"):
        return "docs"
    return "other"


def check_consistency(
    root: Path,
    state: StateSummary,
    roadmap_phases: list[RoadmapPhase],
    phase_documents: list[PhaseDocument],
    phase_state: dict[str, object],
    issues: list[IssueCard],
    documents: list[DocumentLink],
    roadmap_text: str = "",
    *,
    phase_state_usable: bool = True,
) -> list[DashboardWarning]:
    warnings: list[DashboardWarning] = []

    if phase_state_usable:
        for key in ("state_path", "plan_path", "checkpoint_path"):
            value = phase_state.get(key)
            if isinstance(value, str) and not (root / value).exists():
                warnings.append(
                    DashboardWarning(
                        code="phase_state_missing_path_ref",
                        severity="blocking",
                        message=f"phase-state references missing {key}: {value}",
                        paths=[value],
                    )
                )

        checkpoint = phase_state.get("current_checkpoint")
        if isinstance(checkpoint, str) and checkpoint and checkpoint not in state.active_checkpoint:
            warnings.append(
                DashboardWarning(
                    code="state_checkpoint_drift",
                    severity="blocking",
                    message=f"STATE active checkpoint differs from phase-state current_checkpoint: {state.active_checkpoint} vs {checkpoint}",
                    paths=[],
                )
            )

    if roadmap_phases and state.total_phases and len(roadmap_phases) != state.total_phases:
        warnings.append(
            DashboardWarning(
                code="roadmap_total_phases_drift",
                severity="blocking",
                message=f"STATE progress total_phases={state.total_phases} but ROADMAP lists {len(roadmap_phases)} phases",
                paths=[],
            )
        )

    completed_count = sum(1 for phase in roadmap_phases if phase.completed)
    if roadmap_phases and state.completed_phases and completed_count != state.completed_phases:
        warnings.append(
            DashboardWarning(
                code="roadmap_completed_phases_drift",
                severity="blocking",
                message=f"STATE progress completed_phases={state.completed_phases} but ROADMAP marks {completed_count} phases complete",
                paths=[],
            )
        )

    roadmap_phase_ids = {b.phase_id for b in parse_roadmap_phase_bullets(roadmap_text)}
    for document in phase_documents:
        pid = canonical_phase_id(document.phase_dir)
        if not pid:
            warnings.append(DashboardWarning(
                code="phase_folder_grammar_invalid",
                severity="blocking",
                message=f"Phase folder name does not match grammar (expected NN[a-z]?-slug): {document.phase_dir}",
                paths=[document.phase_dir],
            ))
            continue
        if pid not in roadmap_phase_ids:
            warnings.append(DashboardWarning(
                code="phase_folder_not_in_roadmap",
                severity="warning",
                message=(
                    f"Phase folder {document.phase_dir} (id={pid}) is not listed in ROADMAP.md. "
                    "Add a corresponding Phase entry to ROADMAP, or move the folder to .planning/archive/ if the phase has already shipped."
                ),
                paths=[document.phase_dir, ".planning/ROADMAP.md"],
            ))

    if issues and not phase_documents:
        warnings.append(
            DashboardWarning(
                code="issues_without_phase_docs",
                severity="warning",
                message="Issue files are present but no phase documents were found.",
                paths=[],
            )
        )

    document_paths = {document.path for document in documents}
    for required in ("README.md", "AGENTS.md", "docs/phase-gate-harness.md"):
        if required not in document_paths:
            warnings.append(
                DashboardWarning(
                    code="core_document_missing",
                    severity="warning",
                    message=f"Referenced core document is missing from inventory: {required}",
                    paths=[required],
                )
            )

    return warnings


def generate_dashboard(*, root: Path, output: Path) -> Path:
    data = load_dashboard_data(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(data), encoding="utf-8")
    for w in data.warnings:
        print(f"warning: {w.code}: {w.message}")
    print(f"wrote {output}")
    return output


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root to read.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="HTML file to write.")
    parser.add_argument("--serve", action="store_true", help="Start the interactive dashboard server.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate planning docs; print JSON; exit EXIT_PLANNING_DRIFT on any blocking warning.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard server host.")
    parser.add_argument("--port", type=int, default=DEFAULT_DASHBOARD_PORT, help="Dashboard server port.")
    return parser.parse_args(argv)


def run(argv: Iterable[str] | None = None) -> int:
    # dual import for EXIT_* constants
    try:
        from scripts.lib.exitcodes import EXIT_OK, EXIT_PLANNING_DRIFT
    except ModuleNotFoundError:
        from lib.exitcodes import EXIT_OK, EXIT_PLANNING_DRIFT  # type: ignore[no-redef]

    args = parse_args(argv)
    root = args.root.resolve()

    if args.check:
        data = load_dashboard_data(root)
        blocking = [w for w in data.warnings if w.severity == "blocking"]
        payload = {
            "status": "drift" if blocking else "ok",
            "warnings": [
                {"code": w.code, "severity": w.severity, "message": w.message, "paths": w.paths}
                for w in data.warnings
            ],
        }
        print(json.dumps(payload, indent=2))
        return EXIT_PLANNING_DRIFT if blocking else EXIT_OK

    if args.serve:
        try:
            from scripts.lib.project_dashboard.server import serve_dashboard
        except ModuleNotFoundError:
            from lib.project_dashboard.server import serve_dashboard  # type: ignore[no-redef]

        serve_dashboard(root=root, host=args.host, port=args.port)
        return EXIT_OK

    output = args.output
    if not output.is_absolute():
        output = root / output
    generate_dashboard(root=root, output=output)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(run())
