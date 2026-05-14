# Roo Template Overview

This repository is a cloneable Roo Code orchestration template for low-reasoning in-house models working on C#/.NET 10 MSSQL ETL systems.

It configures Roo workflows, modes, rules, slash commands, and workflow skills. It does not implement NewParser or any domain code.

## Intended Entry Points

- Use `/simple` for focused questions, small low-risk edits, docs tweaks, harmless command runs, mechanical cleanup, and tiny locally verified changes that do not need the full phase workflow.
- Use `/feature` for ordinary implementation work.
- Use `/bugfix` when behavior is broken, tests fail, or a regression needs a root-cause pass.
- Use `/etl` for parser, normalization, state, merge, buffering, backpressure, and write orchestration.
- Use `/db` for MSSQL schema, migration, SQL implementation, index, `SqlBulkCopy`, staging, `MERGE`, and bulk-write mechanics.
- Use `/ops` for logs, metrics, processing events, retry boundaries, worker lifecycle, graceful shutdown, dashboards, and runbooks.
- Use `/adr` for architecture decisions and durable design changes.
- Use `/review` for code, SQL, ETL, test, and operations review.
- Use `/issues` to turn docs or plans into PRDs and implementation slices.
- Use `harness-maintainer` for Roo modes, slash commands, workflow rules, `AGENTS.md`, `CLAUDE.md`, `.roo/**`, and `.roomodes`.

## Modes

| Mode | Purpose |
| --- | --- |
| `orchestrator` | Route work to the right workflow without writing implementation code. |
| `architect` | Frame decisions, boundaries, ADRs, and implementation plans. |
| `tdd-code` | Implement C#/.NET 10 behavior through red-green-refactor. |
| `etl-pipeline` | Work on parser, normalization, state, merge, buffering, and write logic. |
| `db-migration` | Handle MSSQL schema, migrations, indexes, queries, and bulk persistence. |
| `diagnose` | Reproduce bugs, minimize failures, and isolate root cause. |
| `review` | Review code, SQL, tests, performance, and operations risk. |
| `docs-issues` | Convert docs and plans into PRDs and implementation issues. |
| `ops-observability` | Implement logs, metrics, processing events, and shutdown behavior. |
| `harness-maintainer` | Maintain Roo orchestration, mode permissions, slash commands, workflow rules, and agent-control files. |

## Routing Boundaries

- `/review` is read-only and has no shell command access.
- `architect` and `docs-issues` can write only `docs/`, `.planning/`, and `.scratch/` tracker files; agent-control files and `.scratch/phase-state*.json` are excluded.
- General implementation modes cannot edit docs, durable planning files, tracker files, phase state, `AGENTS.md`, `CLAUDE.md`, `.roo/**`, `.roomodes`, `README.md`, or `.rooignore`.
- `harness-maintainer` is the only mode intended to edit Roo harness, phase approval state, and agent-control files.
- Slash commands are entry points only. Keep sequence and tie breakers in `.roo/rules-orchestrator/rules.md` and workflow skills.
- `/simple` still respects owner permissions, specialist routing, and focused verification; it only shortens the process for qualifying low-risk tasks.

See the sibling READMEs for the command and workflow-skill catalogs.
