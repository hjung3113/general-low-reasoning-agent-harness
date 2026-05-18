---
description: Route approved phase execute work to the owning implementation mode
argument-hint: <approved plan_id and implementation task>
mode: orchestrator
---

Use the `workflow-phase-gate` skill for $ARGUMENTS.

Apply `.roo/rules-orchestrator/rules.md` and `.roo/rules/phase-gate.md` first.

Use `/phase-execute` only for approved execute handoff:

1. Verify the live gate via `harness check` reports `phase=execute`, `approved=true`, the same `plan_id`, durable pointers, non-empty `allowed_paths`, and non-empty `verification`. Reach that state through `harness run` plus explicit human approval; do NOT direct-edit `.scratch/phase-state.json`.
2. Choose the narrowest owning mode for the approved paths and concern.
3. Create the required handoff packet from `.roo/rules-orchestrator/rules.md`.
4. Do not implement inline from orchestrator.
5. If `new_task` is unavailable, output the handoff packet and stop.

Do not restate or weaken `--chain` safety rules here. The canonical conditions are the `workflow-phase-gate` Automation Flags and Stop Conditions.

Move forward in the phase lifecycle through the high-level CLI:

```text
harness run
```

## Pre-commit (REQUIRED — symmetric with `.opencode/commands/execute.md`)

Before the owning mode commits:

1. Run `harness check`.
2. On exit 4 (scope violation): the command names every violating file
   and points at `docs/protocol-spec.md#scope-enforcement`. Reduce the
   commit (e.g. `git restore --staged <file>`) OR stop and ask the user to
   return to planning, expand `allowed_paths`, approve again, and re-enter
   execute. Do NOT use `git commit --no-verify`.
3. On exit 0: proceed with the commit.

The pre-commit hook installable via `harness install
--pre-commit` enforces the same contract from the git-hook boundary
(spec §10.4 adapter mirroring).
