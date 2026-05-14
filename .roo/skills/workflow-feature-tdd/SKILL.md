---
name: workflow-feature-tdd
trigger: Use when the user asks to add or intentionally change application behavior, or invokes /feature.
description: Runs the standard feature implementation workflow for C#/.NET 10 projects. Use when adding new behavior, changing existing behavior intentionally, or when the user invokes /feature.
---

# Workflow: Feature TDD

Default workflow for application feature work.


## Execution Model

When invoked from `orchestrator`, do not execute this workflow inline.

The orchestrator must create a focused subtask in the owning mode and pass the required handoff packet from `.roo/rules-orchestrator/rules.md`.

The owning mode must reload durable context from `.planning/` and `.scratch/phase-state.json`, perform only its owned work, and return the required structured result.

If the task cannot proceed because planning context is missing, stale, placeholder-only, or outside the approved phase gate, return `needs-plan` instead of guessing.

## Steps

1. Scope the behavior.
   - Run `workflow-phase-gate` first. Stop before implementation unless phase state is `execute`, `approved=true`, and tied to the approved `plan_id`.
   - Read AGENTS.md, relevant docs, existing tests, and nearby code.
   - Identify observable behavior and acceptance criteria.
   - If the request is too broad, split it into vertical slices.
   - If the user only wants planning, review, or explanation, stop and route to the matching workflow.

2. Choose the owner before coding.
   - Use `tdd-code` for ordinary .NET 10 application code.
   - Hand off to `etl-pipeline` for parsing, normalization, state, merge, buffering, or bulk-write flow changes.
   - Hand off to `db-migration` for MSSQL schema, query, index, or transaction changes.
   - Keep EF Core as the default persistence path.
   - Use Dapper only for a documented complex or performance-sensitive read-query exception.

3. Red.
   - Write or identify the failing xUnit test first and run it before production edits.
   - Record red evidence: command, failing test name, and failure reason.
   - Use FluentAssertions for assertions.
   - Use NSubstitute only for collaborators that do not require real integration.
   - Use `testcontainers-dotnet` with real MSSQL containers for SQL, EF Core query, Dapper query, migration, writer, restart-safety, idempotency, and transaction behavior.
   - Do not use mocks, in-memory providers, or SQLite as proof for MSSQL behavior.
   - Stop if no red evidence exists; there is no "tests later" path for behavior changes.

4. Green.
   - Implement the smallest change that passes.
   - Follow .NET 10, async, DI, pipeline-first Clean Architecture, and local project conventions.
   - Run the focused test and record green evidence.

5. Refactor.
   - Refactor only after green evidence exists.
   - Remove duplication only inside the touched behavior.
   - Keep public contracts and domain vocabulary stable.
   - Do not fold unrelated cleanup into the feature.
   - Rerun focused tests after refactoring.

6. Verify.
   - Run the focused tests.
   - Run broader tests when shared behavior changed.
   - Confirm the red test now passes and report the red -> green evidence.
   - Summarize changed files, behavior, and tests.

## Stop Conditions

- Do not implement when the request only asks for design, review, or explanation.
- Do not start domain implementation when the user is configuring Roo workflows.
- Stop and split the work when one request mixes feature code, ETL internals, and database changes that need separate ownership.
- Stop when production edits have started without red evidence; restore the workflow by adding/running the missing failing test before continuing.
