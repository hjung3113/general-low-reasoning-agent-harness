---
name: workflow-bug-diagnosis
trigger: Use when something is broken, a test is failing, output is wrong, performance regressed, or the user invokes /bugfix.
description: Runs the standard root-cause workflow for bugs, failing tests, wrong data, and performance regressions. Use when something is broken or when the user invokes /bugfix.
---

# Workflow: Bug Diagnosis


## Execution Model

When invoked from `orchestrator`, do not execute this workflow inline.

The orchestrator must create a focused subtask in the owning mode and pass the required handoff packet from `.roo/rules-orchestrator/rules.md`.

The owning mode must reload durable context from `.planning/` and `.scratch/phase-state.json`, perform only its owned work, and return the required structured result.

If the task cannot proceed because planning context is missing, stale, placeholder-only, or outside the approved phase gate, return `needs-plan` instead of guessing.

## Steps

1. Reproduce.
   - Run `workflow-phase-gate` first. Stop before implementation unless phase state is `execute`, `approved=true`, and tied to the approved `plan_id`.
   - Capture the failing command, input, log, test, or data example.
   - If reproduction is unclear, inspect existing tests and logs before asking.
   - Stop if there is no observable failure yet; ask for the missing reproduction detail.

2. Minimize.
   - Reduce to the smallest failing test, file, query, or pipeline stage.
   - For ETL bugs, trace the record through source -> parse -> normalize -> state -> merge -> buffer -> write -> observe.

3. Hypothesize.
   - State the most likely cause and what evidence would prove it.
   - Instrument only where observation is missing.
   - Do not change code before the hypothesis matches the evidence.

4. Red.
   - Add a regression test that fails for the bug before production edits.
   - Record red evidence: command, failing test name, and failure reason.
   - Use xUnit + FluentAssertions for code behavior.
   - Use `testcontainers-dotnet` with real MSSQL containers for SQL, EF Core query, Dapper query, migration, writer, restart-safety, idempotency, and transaction behavior.
   - Use NSubstitute only when the bug is outside real persistence/integration behavior.
   - Do not use mocks, in-memory providers, or SQLite as proof for MSSQL behavior.
   - Stop if no red evidence exists; there is no "tests later" path for bug fixes.

5. Fix.
   - Make the smallest change that addresses the verified cause.
   - Avoid broad rewrites.

6. Verify.
   - Run regression tests and impacted suites.
   - Verify the original reproduction path is fixed.
   - Record green evidence for the regression test before refactoring.
   - Refactor only after green evidence exists, then rerun focused tests.
   - Report Cause, Evidence, Fix, Files affected, and Tests run.

## Routing

- Use `diagnose` by default.
- Use `db-migration` for SQL/schema root causes.
- Use `etl-pipeline` for ordering, state, merge, or write path causes.

## Stop Conditions

- Do not convert this workflow into feature work unless the root cause is proven and covered by a regression test.
- Do not implement sample or domain code when the user is only configuring Roo workflows.
- Do not edit production code without a failing reproduction or red regression test.
