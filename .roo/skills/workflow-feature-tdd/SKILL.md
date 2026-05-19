---
name: workflow-feature-tdd
trigger: Use when the user asks to add or intentionally change application behavior, or invokes /feature.
description: Runs the standard feature implementation workflow. Use when adding new behavior, changing existing behavior intentionally, or when the user invokes /feature.
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
   - Use `tdd-code` for ordinary application behavior.
   - Use active `tech-*` and `workflow-*` packs to identify specialized concerns.
   - Do not assume a language, framework, database, package manager, or test framework unless repository evidence or active packs confirm it.

3. Red.
   - Write or identify the failing test or reproduction first and run it before production edits.
   - Record red evidence: command, failing test name, and failure reason.
   - Use the target repository's existing test framework and assertion style.
   - Stop if no red evidence exists; there is no "tests later" path for behavior changes.

4. Green.
   - Implement the smallest change that passes.
   - Follow local project conventions and active pack guidance.
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
- Do not start implementation when the user is configuring Roo workflows.
- Stop and split the work when one request mixes unrelated ownership boundaries.
- Stop when production edits have started without red evidence; restore the workflow by adding/running the missing failing test before continuing.



## Canonical CLI Invocation

Advance the phase lifecycle via the CLI; do NOT direct-edit `.scratch/phase-state.json`. See `.roo/skills/workflow-phase-gate/SKILL.md#canonical-phase-done-example-post-cli` for the G3-A canonical `phase=done` shape.

```text
harness phase set <discuss|plan|execute|done>
harness phase approve  # Do not run this yourself if the harness prompts [y/N]; ask the user.
```

If the harness prints a `[y/N]` prompt, stop and ask the user to confirm from their own terminal. Do not answer the prompt yourself — speed-bump is the user's checkpoint.
