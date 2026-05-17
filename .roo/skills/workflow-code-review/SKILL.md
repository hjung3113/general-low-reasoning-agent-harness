---
name: workflow-code-review
trigger: Use when the user asks for a review, PR review, risk scan, or invokes /review.
description: Runs the read-only review workflow. Use for reviews or when the user invokes /review.
---

# Workflow: Code Review

## Execution Model

When invoked from `orchestrator`, do not execute this workflow inline.

The orchestrator must create a focused subtask in the owning mode and pass the required handoff packet from `.roo/rules-orchestrator/rules.md`.

The owning mode must reload durable context from `.planning/` and `.scratch/phase-state.json`, perform only its owned work, and return the required structured result.

If the task cannot proceed because planning context is missing, stale, placeholder-only, or outside the approved phase gate, return `needs-plan` instead of guessing.

## Steps

1. Identify review scope.
   - Read changed files, tests, and relevant docs.
   - Determine active tech and workflow packs.
   - Stop if the user actually wants implementation instead of review.

2. Review correctness.
   - Check behavior, edge cases, cancellation, concurrency, idempotency, restart safety, and source traceability where relevant.
   - Apply specialized pack rules only when those packs are installed and relevant.

3. Review integration and persistence.
   - Check external boundaries, parameterization, transaction expectations, rollback, and failure handling when applicable.
   - If database context is required but missing, stale, or insufficient, return `needs-db-context` instead of guessing.

4. Review tests.
   - Check for missing red evidence before production edits, missing green evidence after implementation, weak assertions, excessive mocks, and refactor-before-green work.
   - Use the target repository's verification strategy.

5. Review operations.
   - Check logs, metrics, events, retry boundaries, lifecycle, and shutdown behavior where applicable.

6. Report findings.
   - Lead with findings ordered by severity.
   - Include file/line references when possible.
   - Keep summary secondary.

## Hard Rules

- Do not rewrite code unless explicitly asked.
- If no findings exist, state residual risks and test gaps.
- Do not expand the task into feature implementation or sample project construction.



## Canonical CLI Invocation

Advance the phase lifecycle via the CLI; do NOT direct-edit `.scratch/phase-state.json`. See `.roo/skills/workflow-phase-gate/SKILL.md#canonical-phase-done-example-post-cli` for the G3-A canonical `phase=done` shape.

```text
harness phase set <discuss|plan|execute|done>
harness phase approve
```
