---
name: workflow-docs-to-issues
trigger: Use when the user asks to convert requirements, notes, or plans into a PRD or executable issue list, or invokes /issues.
description: Converts requirements, design notes, and plans into PRDs and independently implementable issues. Use for planning from docs or when the user invokes /issues.
---

# Workflow: Docs To Issues


## Execution Model

When invoked from `orchestrator`, do not execute this workflow inline.

The orchestrator must create a focused subtask in the owning mode and pass the required handoff packet from `.roo/rules-orchestrator/rules.md`.

The owning mode must reload durable context from `.planning/` and `.scratch/phase-state.json`, perform only its owned work, and return the required structured result.

If the task cannot proceed because planning context is missing, stale, placeholder-only, or outside the approved phase gate, return `needs-plan` instead of guessing.

## Steps

1. Read source documents.
   - Read AGENTS.md and docs/agents conventions first.
   - Read requirements, design docs, ADRs, and CONTEXT.md when present.
   - Stop if the source docs are missing or contradictory; list the gap first.

2. Extract product shape.
   - Identify goals, non-goals, users, data contracts, constraints, and unresolved decisions.
   - Separate fixed constraints from open questions.

3. Draft or update PRD.
   - Use clear acceptance criteria.
   - Keep implementation details only where they constrain behavior.
   - Do not write sample implementation steps into the PRD.

4. Create vertical slices.
   - Each issue should be independently implementable.
   - Avoid layer-only tickets unless infrastructure must land first.
   - Give each slice one clear owner or mode where useful.

5. Add execution metadata.
   - Status label
   - Dependencies
   - Recommended mode
   - Test expectations, including xUnit TDD and MSSQL `testcontainers-dotnet` coverage when database behavior is part of the slice
   - Done criteria
   - State whether the slice is app code, ETL, DB, review, or architecture work.

## Routing

- Keep ownership with planning while drafting the PRD and issue set.
- Route implementation slices to `tdd-code`, `etl-pipeline`, or `db-migration` only after the issue is written.
- Route review-only work to `review` and design-only work to `architecture-decision`.

## Local Tracker

When this repo uses the default local tracker, create files under:

```text
.scratch/<feature-slug>/PRD.md
.scratch/<feature-slug>/issues/<NN>-<slug>.md
```

## Stop Conditions

- Do not implement the issues in this workflow.
- Do not invent domain/sample project work that is not grounded in the source documents.
