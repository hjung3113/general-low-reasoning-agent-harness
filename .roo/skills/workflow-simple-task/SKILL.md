---
name: workflow-simple-task
trigger: Use when the user asks a small question, requests a small low-risk edit, cleanup, docs tweak, typo fix, harmless command run, mechanical refactor, or tiny test-backed code change that does not need a full phase plan.
description: Handles small, reversible tasks without the full discuss -> plan -> execute workflow while preserving ownership, scope control, and verification.
---

# Workflow: Simple Task

Lightweight path for small tasks where a full phase plan would add more overhead than safety. This workflow is not a loophole around ownership, tests, or specialist workflows.

## Qualifying Tasks

Use this workflow only when all are true:

- The request is narrow and can be completed in one short pass.
- The expected answer or change is easy to inspect.
- The task does not change data contracts, persistence, ETL ordering, security posture, deployment behavior, or architecture.
- The task does not require a durable decision, new issue, migration, broad refactor, or multi-file design.
- Verification is obvious: answer from local context, read the changed text, inspect a targeted diff, run a syntax check, run a focused test, or run a single command.

## Simple Task Types

## Execution Model

`answer-only` simple tasks may stay inline in the orchestrator.

All other simple task types must still respect owner mode boundaries. If the task edits files, runs commands, changes behavior, or updates harness/planning state, create a subtask in the owning mode.

When no subtask tooling is available, a simple task may proceed without subtask tooling only if all of these are true:

- no application code edits
- one or two known files
- verification is obvious and run before reporting completion
- phase gate and allowed paths are clear

Stop instead of proceeding if any condition is unclear.

- `answer-only`: Answer a focused question, explain a nearby file, locate a setting, or give a short recommendation. No file edits.
- `docs-only`: Fix typos, stale references, headings, README notes, comments, or harness documentation.
- `command-only`: Run a harmless command and report the output. Do not run mutating generators, dependency installs, migrations, or deploy commands.
- `mechanical-code`: Make behavior-preserving code cleanup such as removing unused imports, renaming a private helper for clarity, or applying a tiny local formatting fix.
- `tiny-behavior`: Make a very small behavior change only when the expected behavior is explicit, the blast radius is local, and a focused existing or new test can verify it immediately.

Good examples:

- Fix a typo or stale reference.
- Add a short README note.
- Run a harmless repository script and report its output.
- Rename a heading or clarify a sentence.
- Make a small harness documentation sync requested by the user.
- Remove an unused import or dead private helper after verifying it is unused.
- Answer "where is this configured?" with file references.
- Add a tiny guard or display tweak covered by a focused test.

Do not use this workflow for:

- Ambiguous feature work, unknown-cause bug fixes, or behavior changes without immediate focused verification.
- SQL, migration, ETL, ops, authentication, authorization, or data-processing changes.
- Generated files, dependency changes, or broad formatting.
- Tasks that touch many files or require coordination with `.scratch/phase-state.json`.
- Public API changes, data contract changes, cross-module refactors, or durable design choices.

## Steps

1. Classify the task.
   - Name the type: `answer-only`, `docs-only`, `command-only`, `mechanical-code`, or `tiny-behavior`.
   - If it fails any qualifying condition, route to the correct full workflow.
   - If a user explicitly asks for the full phase process, do not use this workflow.

2. Pick the owner.
   - Use the existing mode that owns the file type.
   - For `.roo/**`, `.roomodes`, `AGENTS.md`, `CLAUDE.md`, and harness docs, use `harness-maintainer`.
   - For planning or issue docs, use `architect` or `docs-issues`.
   - Do not bypass mode ownership just because the task is small.

3. Execute minimally.
   - Read only the nearby context needed for the edit.
   - Change only the requested lines and any directly required reference.
   - Do not perform opportunistic cleanup.
   - Do not update `.planning/STATE.md` or phase checkpoints unless the user explicitly asks or the phase/checkpoint/next action actually changes.
   - For `tiny-behavior`, write or identify the focused verification before changing production code.

4. Verify.
   - For `answer-only`, cite the file or command output used when applicable.
   - For edits, inspect the diff.
   - Run the smallest relevant validation command when one exists.
   - For `mechanical-code`, run a syntax, type, lint, or focused test check when available.
   - For `tiny-behavior`, run the focused test or reproduction that proves the change.
   - If no command is meaningful for a docs-only change, state that the diff was reviewed.

5. Report.
   - Summarize the exact files changed.
   - State the verification performed.
   - Mention the simple-task type when it clarifies why the full phase gate was not used.

## Escalation Triggers

Stop and route to a full workflow when the task grows beyond the original scope, requires design judgment, touches specialist domains, lacks focused verification, or creates disagreement between README, `.roo/**`, `.planning/**`, and `.scratch/phase-state.json`.
