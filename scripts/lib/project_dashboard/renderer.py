"""HTML rendering for the static project dashboard."""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Iterable

from lib.project_dashboard.models import (
    DashboardData,
    DashboardWarning,
    DecisionRecord,
    PhaseDocument,
    ProjectMemory,
    RoadmapPhase,
    VerificationRecord,
)


def render_html(data: DashboardData) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    phase_state = data.phase_state
    approval = "approved" if phase_state.get("approved") is True else "not approved"
    gate_phase = str(phase_state.get("phase", "unknown"))
    verification = as_string_list(phase_state.get("verification"))
    acceptance = as_string_list(phase_state.get("acceptance_criteria"))
    allowed_paths = as_string_list(phase_state.get("allowed_paths"))
    blocked_paths = as_string_list(phase_state.get("blocked_paths"))
    notes = as_string_list(phase_state.get("notes"))

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Project Dashboard</title>
  <style>{CSS}</style>
</head>
<body>
  <header class="hero">
    <div>
      <p class="eyebrow">{escape(data.state.milestone)}</p>
      <h1>{escape(data.state.milestone_name)}</h1>
      <p class="status">{escape(data.state.status)}</p>
    </div>
    <div class="progress-card">
      <div class="progress-value">{data.state.progress_percent}%</div>
      <div class="progress-bar"><span style="width:{bounded_percent(data.state.progress_percent)}%"></span></div>
      <p>{data.state.completed_phases}/{data.state.total_phases} phases complete</p>
    </div>
  </header>

  <main class="layout">
    <aside class="rail">
      <section>
        <h2>Current</h2>
        <dl>
          <dt>Checkpoint</dt><dd>{escape(data.state.active_checkpoint)}</dd>
          <dt>Gate</dt><dd><span class="pill">{escape(gate_phase)}</span> <span class="pill">{escape(approval)}</span></dd>
          <dt>Updated</dt><dd>{escape(data.state.last_updated)}</dd>
          <dt>Generated</dt><dd>{escape(generated_at)}</dd>
        </dl>
      </section>
      <section>
        <h2>Next Action</h2>
        <p>{escape(data.state.next_action)}</p>
      </section>
      <section>
        <h2>Blockers</h2>
        {render_list(data.state.blockers)}
      </section>
    </aside>

    <div class="content">
      {render_warnings(data.warnings)}
      <section class="panel">
        <div class="section-heading">
          <h2>Gate Details</h2>
          <p>Current discuss/plan/execute/done state and approval metadata from .scratch/phase-state.json</p>
        </div>
        {render_gate_details(phase_state)}
      </section>

      <section class="panel">
        <div class="section-heading">
          <h2>Roadmap Kanban</h2>
          <p>Done, in-progress, and remaining phases from .planning/ROADMAP.md</p>
        </div>
        {render_phase_kanban(data.roadmap_phases, gate_phase)}
      </section>

      <section class="panel">
        <div class="section-heading">
          <h2>Project Memory</h2>
          <p>Purpose, scope, and requirements from .planning/PROJECT.md and .planning/REQUIREMENTS.md</p>
        </div>
        {render_project_memory(data.memory)}
      </section>

      <section class="panel">
        <div class="section-heading">
          <h2>Decision Ledger</h2>
          <p>Accepted project decisions from .planning/DECISIONS.md</p>
        </div>
        {render_decisions(data.memory.decisions)}
      </section>

      <section class="panel">
        <div class="section-heading">
          <h2>Verification Ledger</h2>
          <p>Recent verification evidence from .planning/VERIFICATION.md</p>
        </div>
        {render_verification(data.memory.verification)}
      </section>

      <section class="panel">
        <div class="section-heading">
          <h2>Known Concerns</h2>
          <p>Static risk register from .planning/codebase/CONCERNS.md</p>
        </div>
        {render_list(data.memory.concerns)}
      </section>

      <section class="panel">
        <div class="section-heading">
          <h2>Live Gate</h2>
          <p>Allowed paths, blocked paths, acceptance criteria, and verification from .scratch/phase-state.json</p>
        </div>
        <div class="grid-two">
          <div><h3>Acceptance Criteria</h3>{render_list(acceptance)}</div>
          <div><h3>Verification</h3>{render_code_list(verification)}</div>
          <div><h3>Allowed Paths</h3>{render_code_list(allowed_paths)}</div>
          <div><h3>Blocked Paths</h3>{render_code_list(blocked_paths)}</div>
          <div><h3>Notes</h3>{render_list(notes)}</div>
        </div>
      </section>

      <section class="panel">
        <div class="section-heading">
          <h2>Phase Details</h2>
          <p>Available phase documents and headings under .planning/phases/</p>
        </div>
        {render_phase_documents(data.phase_documents)}
      </section>

      <section class="panel">
        <div class="section-heading">
          <h2>Issues</h2>
          <p>Local issue cards under .scratch/**/issues/*.md</p>
        </div>
        <div class="issue-grid">{render_issues(data.issues)}</div>
      </section>

      <section class="panel">
        <div class="section-heading">
          <h2>Documents</h2>
          <p>Inventory from README.md, AGENTS.md, docs/**, and .planning/codebase/**</p>
        </div>
        <div class="issue-grid">{render_documents(data.documents)}</div>
      </section>
    </div>
  </main>
</body>
</html>
"""


def render_gate_details(phase_state: dict[str, object]) -> str:
    details = [
        ("Phase", phase_state.get("phase", "unknown")),
        ("Plan ID", phase_state.get("plan_id", "unknown")),
        ("Approved", "true" if phase_state.get("approved") is True else "false"),
        ("Approved By", phase_state.get("approved_by", "unknown")),
        ("Approved At", phase_state.get("approved_at", "unknown")),
        ("Current Checkpoint", phase_state.get("current_checkpoint", "unknown")),
        ("Automation", phase_state.get("automation_mode", "manual")),
        ("Plan", phase_state.get("plan_path", "unknown")),
        ("State", phase_state.get("state_path", "unknown")),
        ("Checkpoint", phase_state.get("checkpoint_path", "unknown")),
        ("Next Action", phase_state.get("next_action", "unknown")),
    ]
    items = "".join(
        f"<div><dt>{escape(label)}</dt><dd>{escape(display_value(value))}</dd></div>"
        for label, value in details
    )
    return f'<dl class="detail-grid">{items}</dl>'


def display_value(value: object) -> str:
    if value is None:
        return "Not set"
    return str(value)


CSS = """
:root {
  color-scheme: light;
  --ink: #17202a;
  --muted: #5f6b7a;
  --line: #d8dee8;
  --soft: #f5f7fa;
  --panel: #ffffff;
  --accent: #2563eb;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: var(--ink);
  background: #eef2f6;
}
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 24px;
  padding: 32px;
  background: #111827;
  color: white;
}
.eyebrow { margin: 0 0 8px; color: #93c5fd; font-weight: 700; text-transform: uppercase; font-size: 12px; }
h1 { margin: 0; font-size: 34px; line-height: 1.1; letter-spacing: 0; }
.status { max-width: 900px; color: #d1d5db; font-size: 16px; }
.progress-card { background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.18); padding: 18px; border-radius: 8px; }
.progress-value { font-size: 42px; font-weight: 800; }
.progress-bar { height: 10px; background: rgba(255,255,255,.18); border-radius: 999px; overflow: hidden; }
.progress-bar span { display: block; height: 100%; background: #60a5fa; }
.layout { display: grid; grid-template-columns: 320px minmax(0, 1fr); gap: 20px; padding: 20px; }
.rail, .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
.rail { padding: 18px; align-self: start; position: sticky; top: 20px; }
.rail section + section { margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--line); }
h2 { margin: 0 0 12px; font-size: 20px; }
h3 { margin: 0 0 10px; font-size: 15px; }
dt { font-size: 12px; color: var(--muted); font-weight: 700; margin-top: 12px; }
dd { margin: 4px 0 0; }
.pill { display: inline-block; border: 1px solid var(--line); border-radius: 999px; padding: 3px 8px; font-size: 12px; background: var(--soft); margin: 2px 4px 2px 0; }
.content { display: grid; gap: 20px; }
.panel { padding: 20px; }
.section-heading { display: flex; justify-content: space-between; gap: 18px; align-items: start; border-bottom: 1px solid var(--line); padding-bottom: 12px; margin-bottom: 16px; }
.section-heading p { margin: 0; color: var(--muted); font-size: 13px; }
.kanban { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.kanban-column { border: 1px solid var(--line); border-radius: 8px; background: #f8fafc; padding: 12px; min-height: 180px; }
.kanban-column.done { background: #f0fdf4; border-color: #9bd4ae; }
.kanban-column.active { background: #eff6ff; border-color: #93c5fd; }
.kanban-column.remaining { background: #f8fafc; }
.kanban-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 12px; }
.kanban-header h3 { margin: 0; font-size: 16px; }
.kanban-count { min-width: 28px; text-align: center; border-radius: 999px; padding: 3px 8px; background: white; border: 1px solid var(--line); font-weight: 700; font-size: 12px; }
.kanban-stack { display: grid; gap: 10px; }
.phase-card { border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: var(--soft); }
.phase-card.done { border-color: #9bd4ae; background: #effaf3; }
.phase-card.active { border-color: #93c5fd; background: #eff6ff; }
.phase-card.remaining { background: white; }
.phase-card h3 { font-size: 16px; }
.phase-card p { color: var(--muted); font-size: 13px; }
.grid-two { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.span-two { grid-column: 1 / -1; }
.detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px 16px; margin: 0; }
.detail-grid div { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: var(--soft); min-width: 0; }
.detail-grid dd { overflow-wrap: anywhere; }
ul { margin: 0; padding-left: 20px; }
li + li { margin-top: 6px; }
code { background: #edf2f7; border: 1px solid #dbe3ec; padding: 2px 5px; border-radius: 4px; font-size: 12px; }
.phase-doc { border-top: 1px solid var(--line); padding: 14px 0; }
.phase-doc:first-of-type { border-top: 0; }
.doc-links { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.doc-links a { color: var(--accent); text-decoration: none; border: 1px solid var(--line); padding: 5px 8px; border-radius: 6px; }
.issue-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.issue-card { border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: var(--soft); }
.warning { border: 1px solid #f59e0b; background: #fffbeb; color: #78350f; }
@media (max-width: 900px) {
  .hero, .layout, .grid-two, .kanban { grid-template-columns: 1fr; }
  .rail { position: static; }
}
"""


def render_warnings(warnings: list[DashboardWarning]) -> str:
    if not warnings:
        return ""
    items = "".join(
        f'<li><span class="pill">{escape(w.severity)}</span> <code>{escape(w.code)}</code> {escape(w.message)}</li>'
        for w in warnings
    )
    return f'<section class="panel warning"><h2>Warnings</h2><ul>{items}</ul></section>'


def render_phase_kanban(phases: list[RoadmapPhase], gate_phase: str) -> str:
    if not phases:
        return '<p class="muted">No roadmap phases found.</p>'
    columns = group_phases_for_kanban(phases, gate_phase)
    return (
        '<div class="kanban">'
        f'{render_kanban_column("Done", "done", columns["done"])}'
        f'{render_kanban_column("In Progress", "active", columns["active"])}'
        f'{render_kanban_column("Remaining", "remaining", columns["remaining"])}'
        "</div>"
    )


def group_phases_for_kanban(phases: list[RoadmapPhase], gate_phase: str) -> dict[str, list[RoadmapPhase]]:
    columns: dict[str, list[RoadmapPhase]] = {"done": [], "active": [], "remaining": []}
    first_open_seen = False
    has_active_gate = gate_phase in {"discuss", "plan", "execute"}
    for phase in phases:
        if phase.completed:
            columns["done"].append(phase)
        elif has_active_gate and not first_open_seen:
            columns["active"].append(phase)
            first_open_seen = True
        else:
            columns["remaining"].append(phase)
    return columns


def render_kanban_column(title: str, state: str, phases: list[RoadmapPhase]) -> str:
    cards = "".join(render_phase_card(phase, state) for phase in phases)
    if not cards:
        cards = '<p class="muted">No phases.</p>'
    return (
        f'<section class="kanban-column {state}">'
        f'<div class="kanban-header"><h3>{escape(title)}</h3><span class="kanban-count">{len(phases)}</span></div>'
        f'<div class="kanban-stack">{cards}</div>'
        "</section>"
    )


def render_phase_card(phase: RoadmapPhase, state: str) -> str:
    return (
        f'<article class="phase-card {state}"><span class="pill">{escape(state)}</span>'
        f"<h3>{escape(phase.title)}</h3><p>{escape(phase.summary)}</p></article>"
    )


def render_project_memory(memory: ProjectMemory) -> str:
    scope = render_list(memory.scope)
    requirements = "".join(
        f'<article class="issue-card"><h3>{escape(requirement.requirement_id)}</h3>'
        f'<p>{escape(requirement.summary)}</p></article>'
        for requirement in memory.requirements
    )
    if not requirements:
        requirements = "<p>No requirements found.</p>"
    return (
        '<div class="grid-two">'
        f'<div><h3>One-Liner</h3><p>{escape(memory.one_liner)}</p></div>'
        f'<div><h3>Scope</h3>{scope}</div>'
        f'<div class="span-two"><h3>Requirements</h3><div class="issue-grid">{requirements}</div></div>'
        "</div>"
    )


def render_decisions(decisions: list[DecisionRecord]) -> str:
    if not decisions:
        return "<p>No decisions found.</p>"
    cards: list[str] = []
    for decision in decisions:
        cards.append(
            f'<article class="issue-card"><h3>{escape(decision.decision_id)}</h3>'
            f'<span class="pill">{escape(decision.status)}</span> <span class="pill">{escape(decision.scope)}</span>'
            f'<p>{escape(decision.decision)}</p><p><code>{escape(decision.source)}</code></p></article>'
        )
    return f'<div class="issue-grid">{"".join(cards)}</div>'


def render_verification(records: list[VerificationRecord]) -> str:
    if not records:
        return "<p>No verification records found.</p>"
    recent = records[-6:]
    cards: list[str] = []
    for record in reversed(recent):
        cards.append(
            f'<article class="issue-card"><h3>{escape(record.check)}</h3>'
            f'<span class="pill">{escape(record.result)}</span> <span class="pill">{escape(record.date)}</span>'
            f'<p>{escape(record.phase)}</p><p>{escape(record.notes)}</p></article>'
        )
    return f'<div class="issue-grid">{"".join(cards)}</div>'


def render_phase_documents(documents: list[PhaseDocument]) -> str:
    if not documents:
        return "<p>No phase documents found.</p>"
    rendered: list[str] = []
    for document in documents:
        links = "".join(f'<a href="../../{escape(path)}">{escape(name)}</a>' for name, path in sorted(document.files.items()))
        headings = render_list(document.headings[:6])
        rendered.append(
            f'<article class="phase-doc"><h3>{escape(document.phase_dir)}</h3>{headings}'
            f'<div class="doc-links">{links}</div></article>'
        )
    return "".join(rendered)


def render_issues(issues: list[IssueCard]) -> str:
    if not issues:
        return "<p>No local issue cards found.</p>"
    cards: list[str] = []
    for issue in issues:
        labels = " ".join(f'<span class="pill">{escape(label)}</span>' for label in issue.labels)
        cards.append(
            f'<article class="issue-card"><h3>{escape(issue.title)}</h3><p><code>{escape(issue.path)}</code></p>{labels}</article>'
        )
    return "".join(cards)


def render_documents(documents: list[DocumentLink]) -> str:
    if not documents:
        return "<p>No documents found.</p>"
    cards: list[str] = []
    for document in documents:
        cards.append(
            f'<article class="issue-card"><h3>{escape(document.title)}</h3>'
            f'<p><code>{escape(document.path)}</code></p><span class="pill">{escape(document.category)}</span></article>'
        )
    return "".join(cards)


def render_list(items: Iterable[str]) -> str:
    values = list(items)
    if not values:
        return "<p>None recorded.</p>"
    return "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in values) + "</ul>"


def render_code_list(items: Iterable[str]) -> str:
    values = list(items)
    if not values:
        return "<p>None recorded.</p>"
    return "<ul>" + "".join(f"<li><code>{escape(item)}</code></li>" for item in values) + "</ul>"


def as_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value]
    return []


def bounded_percent(value: int) -> int:
    return max(0, min(100, value))


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)
