---
name: workflow-code-review
trigger: Use when the user asks for a review, PR review, risk scan, or invokes /review.
description: Runs the review workflow for C#/.NET, async, SQL, ETL correctness, tests, performance, and operations risks. Use for reviews or when the user invokes /review.
---

# Workflow: Code Review


## Execution Model

When invoked from `orchestrator`, do not execute this workflow inline.

The orchestrator must create a focused subtask in the owning mode and pass the required handoff packet from `.roo/rules-orchestrator/rules.md`.

The owning mode must reload durable context from `.planning/` and `.scratch/phase-state.json`, perform only its owned work, and return the required structured result.

If the task cannot proceed because planning context is missing, stale, placeholder-only, or outside the approved phase gate, return `needs-plan` instead of guessing.

## DB Context Snapshot

When the review depends on actual MSSQL schema, table/column names, indexes, foreign keys, stored procedures, functions, views, triggers, SQL Agent jobs, writer behavior, MERGE keys, idempotency, or restart-safety, read `.db-context/latest.json` before making findings.

Use `.db-context/routines.index.json` to locate stored procedures, functions, and views. Use `.db-context/routines.sql` for exact SQL control-flow review. Use `.db-context/jobs.md` when SQL Agent jobs or schedules affect the reviewed behavior and the snapshot was refreshed with `--include-agent-jobs`.

Do not connect to the database by default. If `.db-context/` exists, use it as the source of truth. Review mode does not own command execution; when fresh DB context is explicitly required, return `needs-db-context` so a command-capable mode or human can run `python3 scripts/db_context_snapshot.py --refresh`.

If DB context is required but missing, stale, or insufficient, return `needs-db-context` instead of guessing or refreshing automatically.

The expected database model is one master database and many process databases. Process databases are expected to share the same schema shape; check `process_database_comparison` before assuming a process DB schema is representative.

## Steps

1. Identify review scope.
   - Read changed files, tests, and relevant docs.
   - Determine whether the change touches C#, ETL, MSSQL, operations, or docs.
   - Read DB context snapshot files when actual DB shape or SQL routines are needed to validate the change.
   - Stop if the user actually wants implementation instead of review.

2. Review correctness.
   - Check behavior, edge cases, cancellation, concurrency, idempotency, restart safety, and source traceability.
   - For ETL changes, verify the canonical flow: source -> parse -> normalize -> state -> merge -> buffer -> write -> observe.
   - Check backpressure, bounded buffers, duplicate handling, replay behavior, and failure visibility.

3. Review SQL and persistence.
   - Check EF Core usage by default and Dapper only for documented complex or performance-sensitive read-query exceptions.
   - Check parameterized SQL, injection risk, bulk write safety, staging tables, indexes, transactions, MERGE semantics, and non-sargable predicates.
   - Check SqlBulkCopy into staging plus set-based MERGE/upsert for high-volume ETL writes.
   - Flag row-by-row ETL writes unless there is a documented reviewer-approved exception with volume limits and rationale.
   - Cross-check referenced tables, columns, indexes, routines, and SQL Agent jobs against `.db-context/` when available.

4. Review tests.
   - Check for missing red evidence before production edits, missing green evidence after implementation, weak assertions, excessive mocks, and refactor-before-green work.
   - Confirm xUnit + FluentAssertions usage is clear and NSubstitute is not replacing required integration coverage.
   - Confirm `testcontainers-dotnet` with real MSSQL containers covers SQL, EF Core query, Dapper query, migration, writer, restart-safety, idempotency, and transaction behavior.
   - Treat mocks, in-memory providers, SQLite, or unit-only tests as insufficient proof for MSSQL behavior.

5. Review operations.
   - Check logs, metrics, processing events, retry boundaries, and shutdown behavior.
   - Check SQL Agent job schedule and job-step implications through `.db-context/jobs.md` when relevant.

6. Report findings.
   - Lead with findings ordered by severity.
   - Include file/line references when possible.
   - Keep summary secondary.
   - If the review depends on missing DB context, report `needs-db-context` instead of speculative findings.

## Routing

- Primary owner: `review`.
- Route implementation requests discovered during review to the correct implementation workflow instead of fixing them inside the review.

## Hard Rules

- Do not rewrite code unless explicitly asked.
- If no findings exist, state residual risks and test gaps.
- Do not expand the task into feature implementation or sample project construction.
- Do not refresh DB context from review mode; return `needs-db-context` when a command-capable refresh is required.
