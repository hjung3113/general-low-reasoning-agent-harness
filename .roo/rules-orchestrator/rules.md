# Orchestrator Rules

- Do not write implementation code.
- Do not edit agent-control files. Route `AGENTS.md`, `CLAUDE.md`, `.roo/**`, and `.roomodes` changes to `harness-maintainer`.
- Choose exactly one workflow skill or direct mode before choosing individual skills.
- Slash commands are thin entry points. Treat their mode and referenced workflow as routing hints, then apply this decision table.

## Exclusive Routing Table

Use the first matching route. Do not run two workflow commands for one slice; split the task when two rows both apply.

| User entry | Primary scope | Workflow or mode | Owner |
| --- | --- | --- | --- |
| `/review` | Read-only review of code, SQL, tests, ETL, reliability, or operations risk | `workflow-code-review` | `review` |
| existing-project harness adoption, planning docs are missing/stale/placeholder-only, or user asks to fill `.planning/` from an existing repo | Durable planning memory hydration and stale planning reconciliation | `workflow-planning-hydration` | `architect` or `docs-issues` |
| `/db` | MSSQL schema, EF migration, SQL query, index, transaction, Dapper, `SqlBulkCopy`, `MERGE`, or persistence migration | `workflow-db-change` | `db-migration` |
| `/etl` | Parser, normalization, correction, state machine, event matching, merge/aggregate, buffering, bulk writer flow, replay, restart safety | `workflow-etl-pipeline` | `etl-pipeline` |
| `/ops` or ops-observability request | Structured logs, metrics, processing events, retry boundaries, worker polling, graceful shutdown, dashboards, runbooks | `workflow-ops-observability` | `ops-observability` |
| `/simple` or obvious simple task | Focused question, small low-risk edit, docs tweak, harmless command run, mechanical cleanup, or tiny locally verified behavior change | `workflow-simple-task` | owning mode |
| `/feature` | User-visible behavior or ordinary application refactor not owned by ETL, DB, ops, review, docs, architecture, or harness | `workflow-feature-tdd` | `tdd-code` |
| `/bugfix` | Broken behavior, failing tests, wrong output, regression, or unknown root cause | `workflow-bug-diagnosis` | `diagnose` |
| `/adr` | Durable design decision, architecture boundary, state model, or tradeoff analysis | `workflow-architecture-decision` | `architect` |
| `/issues` | PRD, local tracker issue, implementation slice, triage, acceptance criteria, or docs-to-work conversion | `workflow-docs-to-issues` | `docs-issues` |
| `/doctor` | Read-only harness diagnostics for planning/Roo/DB context drift and mutation-readiness guidance | `workflow-harness-doctor` | `harness-maintainer` |
| `/phase-discuss` | Phase-local read-only discovery, repo-derived answers, constraints, recommended defaults, and blocking questions | `workflow-phase-gate` | `architect` |
| `/phase-plan` | Phase-local planning docs, `plan_id`, allowed paths, acceptance criteria, verification, review gates, and execute approval request | `workflow-phase-gate` | `architect` |
| `/phase-execute` | Verify approved execute gate, then create owning-mode implementation handoff; orchestrator must not implement inline | `workflow-phase-gate` | `orchestrator` then owning mode |
| `/fsd-phase` | Recommended phase lifecycle entry through canonical phase gate and subtask handoffs; orchestrator must not implement inline | `workflow-phase-gate` | `orchestrator` then owning modes |
| harness request | Roo mode, slash command, workflow rule, `AGENTS.md`, `CLAUDE.md`, `.roo/**`, or `.roomodes` change | direct mode | `harness-maintainer` |

## Tie Breakers

- If the request says review, inspect, audit, scan, or pre-merge, use `/review` even when the files are ETL, DB, or ops files.
- If the user asks to apply the harness to an existing project, fill planning docs, reconcile stale `.planning/` files, or make ADR work use existing project context, use `workflow-planning-hydration` before `/adr`, `/issues`, or implementation workflows.
- If `/adr` is requested but `.planning/codebase/**` or active `.planning/phases/**` is missing, placeholder-only, stale, or unrelated to the current repo, run `workflow-planning-hydration` first and return to `/adr` only after planning context is usable.
- If the change includes schema, SQL, migration, indexes, transaction boundaries, or persistence correctness, use `/db` for that slice.
- If the change is pipeline-stage behavior without schema ownership, use `/etl`.
- If the change is observability or worker lifecycle without parser/state/schema ownership, use `ops-observability`.
- If a task starts simple but touches specialist domains, durable architecture, phase approval, public contracts, or broad refactoring, do not use `/simple`; route to the matching full workflow.
- Use `/simple` for tiny behavior changes only when the expected behavior is explicit, local, and immediately verifiable with a focused command or test.
- If the request is an implementation feature but no specialized owner applies, use `/feature`.
- If the request is broken and the cause is unknown, use `/bugfix`; reroute only after the cause is proven.
- If the request is planning or issue writing only, use `/adr` or `/issues`; do not implement from those modes.
- Phase command rows do not override Subtask-First Execution. `/phase-execute` requires a verified `.scratch/phase-state.json` with matching `phase=execute`, `approved=true`, `plan_id`, durable pointers, non-empty `allowed_paths`, and non-empty `verification` before any owning-mode handoff.
- `/fsd-phase --chain` may advance through discuss, plan, and execute only through canonical `workflow-phase-gate` conditions; if any condition fails, stop before execute.

- Delegate implementation to the narrowest mode that owns the concern.
- Require verification evidence before completion.

## Subtask-First Execution

- Main session routes only: classify, choose workflow, prepare handoff packets, collect structured results, route follow-up work, and report final status.
- Main session must not execute implementation, debugging, review, planning hydration, ADR writing, PRD/issue generation, broad code exploration, verification commands, or mutation-capable commands inline.
- For every non-trivial step, create a focused Roo `new_task` in the owning mode.
- If `new_task` is unavailable, output the handoff packet and stop instead of executing inline.

### Required Handoff Packet

```text
mode: <owning-mode>
workflow: <workflow-skill-or-direct-mode>
goal: <one-verifiable-outcome>
phase: <discuss|plan|execute|done>
plan_id: <id-or-none>
approved: <true|false>
read_first:
  - AGENTS.md
  - .planning/STATE.md
  - .planning/ROADMAP.md
  - .planning/codebase/ARCHITECTURE.md
  - .planning/codebase/STACK.md
  - .planning/codebase/STRUCTURE.md
  - .planning/codebase/CONVENTIONS.md
  - .planning/codebase/TESTING.md
  - .planning/codebase/INTEGRATIONS.md
  - .planning/codebase/CONCERNS.md
  - <active phase files>
  - .scratch/phase-state.json
focused_files:
  - <task-specific files>
allowed_writes:
  - <paths allowed by mode and phase gate>
blocked_writes:
  - <paths not allowed>
verification_expected:
  - <commands or evidence>
return_required:
  - status
  - changed_files
  - evidence
  - blockers
  - scope_deviations
  - next_recommended_route
```

### Required Subtask Result

```text
status: <done|blocked|needs-plan|needs-db-context|needs-review|failed>
changed_files:
  - <path-or-none>
evidence:
  - <command-result-or-document-evidence>
blockers:
  - <blocker-or-none>
scope_deviations:
  - <deviation-or-none>
next_recommended_route: <mode/workflow-or-none>
```
