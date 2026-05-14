# Roo Adapter Overview

This folder contains the Roo adapter for the generalized low-reasoning harness.

Roo is not the source of truth. Shared project state lives in `AGENTS.md`, `.planning/**`, and `.scratch/phase-state.json`.

## Intended Entry Points

- Use `/simple` for focused questions, small low-risk edits, docs tweaks, harmless command runs, mechanical cleanup, and tiny locally verified changes.
- Use `/feature` for ordinary behavior changes that can be verified by the target project's test strategy.
- Use `/bugfix` when behavior is broken, tests fail, or a regression needs root-cause analysis.
- Use `/ops` for logs, metrics, lifecycle, retry boundaries, dashboards, and runbooks.
- Use `/adr` for architecture decisions and durable design changes.
- Use `/review` for read-only review.
- Use `/issues` to turn docs or plans into PRDs and implementation slices.
- Use `harness-maintainer` for Roo modes, slash commands, workflow rules, `AGENTS.md`, `.roo/**`, and `.roomodes`.

Stack-specific behavior comes from installed skill packs and profiles. For example, database-backed data movement belongs in `workflow-etl`, `workflow-db-context`, and the relevant database tech pack, not in the default Roo adapter.

## Modes

| Mode | Purpose |
| --- | --- |
| `orchestrator` | Route work to the right workflow without writing implementation code. |
| `architect` | Frame decisions, boundaries, ADRs, and implementation plans. |
| `tdd-code` | Implement behavior through red-green-refactor using the target project's conventions. |
| `diagnose` | Reproduce bugs, minimize failures, and isolate root cause. |
| `review` | Review correctness, regressions, security, performance, reliability, and missing tests. |
| `docs-issues` | Convert docs and plans into PRDs and implementation issues. |
| `ops-observability` | Implement logs, metrics, lifecycle, retry boundaries, and operational visibility. |
| `harness-maintainer` | Maintain Roo orchestration, mode permissions, slash commands, workflow rules, and agent-control files. |

## Routing Boundaries

- `/review` is read-only and has no shell command access.
- `architect` and `docs-issues` can write only `docs/`, `.planning/`, and `.scratch/` tracker files; agent-control files and phase approval files are excluded.
- General implementation modes cannot edit docs, durable planning files, tracker files, phase state, `AGENTS.md`, `.roo/**`, `.roomodes`, `README.md`, or `.rooignore`.
- `harness-maintainer` is the only mode intended to edit Roo harness, phase approval state, and agent-control files.
- Slash commands are entry points only. Keep sequence and tie breakers in `.roo/rules-orchestrator/rules.md` and workflow skills.
- `/simple` still respects owner permissions, specialist routing, and focused verification; it only shortens the process for qualifying low-risk tasks.

