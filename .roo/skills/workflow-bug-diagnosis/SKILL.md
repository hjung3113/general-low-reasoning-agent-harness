---
name: workflow-bug-diagnosis
trigger: Use when behavior is broken, tests fail, output is wrong, or the user invokes /bugfix.
description: Reproduce, minimize, diagnose, fix, and regression-test bugs.
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
   - Stop if there is no observable failure yet; ask for the missing reproduction detail.

2. Minimize.
   - Reduce to the smallest failing test, file, query, or processing stage.
   - For data bugs, trace the record through each confirmed processing stage.

3. Hypothesize.
   - State the most likely cause and what evidence would prove it.
   - Instrument only where observation is missing.
   - Do not change code before the hypothesis matches the evidence.

4. Red.
   - Add a regression test that fails for the bug before production edits.
   - Record red evidence: command, failing test name, and failure reason.
   - Use the repository's existing test framework and active pack guidance.
   - Stop if no red evidence exists; there is no "tests later" path for bug fixes.

5. Fix.
   - Make the smallest change that addresses the verified cause.
   - Avoid broad rewrites.

6. Verify.
   - Run regression tests and impacted suites.
   - Verify the original reproduction path is fixed.
   - Record green evidence for the regression test before refactoring.
   - Report Cause, Evidence, Fix, Files affected, and Tests run.

## Routing

- Use `diagnose` by default.
- Use active tech and workflow packs to refine ownership for specialized causes.

## Stop Conditions

- Do not convert this workflow into feature work unless the root cause is proven and covered by a regression test.
- Do not implement sample or domain code when the user is only configuring Roo workflows.
- Do not edit production code without a failing reproduction or red regression test.



## Canonical CLI Invocation

Advance the phase lifecycle via the CLI; do NOT direct-edit `.scratch/phase-state.json`. See `.roo/skills/workflow-phase-gate/SKILL.md#canonical-phase-done-example-post-cli` for the G3-A canonical `phase=done` shape.

```text
harness phase set <discuss|plan|execute|done>     # long form: python3 scripts/harness.py phase set <X>
harness phase approve                              # long form: python3 scripts/harness.py phase approve; only in phase=plan or phase=execute; exit 6 in done (G2-C)
```
