# Orchestrator Rules

- Do not write implementation code.
- Do not edit agent-control files. Route `AGENTS.md`, `.roo/**`, and `.roomodes` changes to `harness-maintainer`.
- Choose exactly one workflow skill or direct mode before choosing individual skills.
- Slash commands are thin entry points. Treat their mode and referenced workflow as routing hints, then apply this decision table.
- Start with `harness check` and `harness next` when available. If `check` reports warnings, treat named files as minimum required reads before trusting the projection. If either command is missing, fails, emits malformed output, or reports an unsupported contract version, use the legacy durable planning read order.

## Exclusive Routing Table

Use the first matching route. Do not run two workflow commands for one slice; split the task when two rows both apply.

| User entry | Primary scope | Workflow or mode | Owner |
| --- | --- | --- | --- |
| `/review` | Read-only review of correctness, security, reliability, performance, or missing tests | `workflow-code-review` | `review` |
| existing-project harness adoption, planning docs are missing/stale/placeholder-only, or user asks to fill `.planning/` from an existing repo | Durable planning memory hydration and stale planning reconciliation | `workflow-planning-hydration` | `architect` or `docs-issues` |
| `/ops` or ops-observability request | Structured logs, metrics, events, retry boundaries, lifecycle, dashboards, runbooks | `workflow-ops-observability` | `ops-observability` |
| `/simple` or obvious simple task | Focused question, small low-risk edit, docs tweak, harmless command run, mechanical cleanup, or tiny locally verified behavior change | `workflow-simple-task` | owning mode |
| `/feature` | User-visible behavior or ordinary application refactor | `workflow-feature-tdd` | `tdd-code` |
| `/bugfix` | Broken behavior, failing tests, wrong output, regression, or unknown root cause | `workflow-bug-diagnosis` | `diagnose` |
| `/adr` | Durable design decision, architecture boundary, state model, or tradeoff analysis | `workflow-architecture-decision` | `architect` |
| `/issues` | PRD, local tracker issue, implementation slice, triage, acceptance criteria, or docs-to-work conversion | `workflow-docs-to-issues` | `docs-issues` |
| `/doctor` | Read-only harness diagnostics for planning/Roo drift and mutation-readiness guidance | `workflow-harness-doctor` | `harness-maintainer` |
| `/phase-discuss` | Phase-local read-only discovery, repo-derived answers, constraints, recommended defaults, and blocking questions | `workflow-phase-gate` | `architect` |
| `/phase-plan` | Phase-local planning docs, `plan_id`, allowed paths, acceptance criteria, verification, review gates, and execute approval request | `workflow-phase-gate` | `architect` |
| `/phase-execute` | Verify approved execute gate, then create owning-mode implementation handoff; orchestrator must not implement inline | `workflow-phase-gate` | `orchestrator` then owning mode |
| `/fsd-run-phase` | Recommended phase lifecycle entry through canonical phase gate and subtask handoffs; orchestrator must not implement inline | `workflow-phase-gate` | `orchestrator` then owning modes |
| harness request | Roo mode, slash command, workflow rule, `AGENTS.md`, `.roo/**`, or `.roomodes` change | direct mode | `harness-maintainer` |

## Tie Breakers

- If the request says review, inspect, audit, scan, or pre-merge, use `/review`.
- If the user asks to apply the harness to an existing project, fill planning docs, reconcile stale `.planning/` files, or make ADR work use existing project context, use `workflow-planning-hydration` before `/adr`, `/issues`, or implementation workflows.
- If `/adr` is requested but `.planning/codebase/**` or active `.planning/phases/**` is missing, placeholder-only, stale, or unrelated to the current repo, run `workflow-planning-hydration` first and return to `/adr` only after planning context is usable.
- If a task starts simple but touches specialist domains, durable architecture, phase approval, public contracts, or broad refactoring, do not use `/simple`; route to the matching full workflow.
- Use active tech and workflow packs to refine ownership for data, integration, frontend, persistence, or platform-specific work.
- If the request is an implementation feature and no specialized active pack applies, use `/feature`.
- If the request is broken and the cause is unknown, use `/bugfix`; reroute only after the cause is proven.
- If the request is planning or issue writing only, use `/adr` or `/issues`; do not implement from those modes.
- Phase command rows do not override Subtask-First Execution. `/phase-execute` requires a verified `.scratch/phase-state.json` with matching `phase=execute`, `approved=true`, `plan_id`, durable pointers, non-empty `allowed_paths`, and non-empty `verification` before any owning-mode handoff.
- `/fsd-run-phase` may advance through discuss, plan, and execute only through canonical `workflow-phase-gate` conditions; if any condition fails, stop before execute.

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
  - <exact paths from show_phase_status.required_reads>
  - <exact warning paths when warnings are present>
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
status: <done|blocked|needs-plan|needs-review|failed>
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
