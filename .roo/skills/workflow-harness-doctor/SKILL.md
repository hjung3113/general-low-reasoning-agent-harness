---
name: workflow-harness-doctor
trigger: Use when the user invokes /doctor or asks for harness diagnostics, document/Roo drift, DB context readiness, or mutation-readiness checks.
description: Runs read-only harness diagnostics for planning, Roo command/mode, DB context config, and diff-before-mutation readiness.
---

# Workflow: Harness Doctor

Apply `.roo/rules-orchestrator/rules.md` before this workflow.

## Purpose

Use this workflow to diagnose harness drift before repair work starts. It is read-only and must not mutate files.

## Steps

1. Read `AGENTS.md`, `.planning/STATE.md`, `.planning/ROADMAP.md`, the active checkpoint, `.planning/codebase/**`, active phase docs, and `.scratch/phase-state.json`.
2. Run `harness doctor` or `harness doctor --format json`.
3. Report findings using the script vocabulary: `severity`, `code`, `path`, `cause`, `impact`, `fix`, `evidence`, and `connects_to_db`.
4. Treat P0/P1 findings as blockers before PR, merge, or implementation.
5. For any repair, run or describe a diff-before-mutation path first, such as `harness upgrade --target <path> --dry-run` and `git diff`.

## Stop Conditions

- Do not edit files from `/doctor`.
- Do not connect to a database.
- Do not treat a P3 diff-before-mutation advisory as failure by itself.
- If the user asks to apply fixes, route to the owning workflow and require an approved phase gate when files will be edited.


## Canonical CLI Invocation

Advance the phase lifecycle via the CLI; do NOT direct-edit `.scratch/phase-state.json`. See `.roo/skills/workflow-phase-gate/SKILL.md#canonical-phase-done-example-post-cli` for the G3-A canonical `phase=done` shape.

```text
harness phase set <discuss|plan|execute|done>
harness phase approve  # Do not run this yourself if the harness prompts [y/N]; ask the user.
```

If the harness prints a `[y/N]` prompt, stop and ask the user to confirm from their own terminal. Do not answer the prompt yourself — speed-bump is the user's checkpoint.
