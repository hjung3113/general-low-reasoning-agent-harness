---
description: Run phase discuss only (read-only)
argument-hint: <phase goal, blocker, or decision scope>
mode: architect
---

Use the `workflow-phase-gate` skill for $ARGUMENTS.

Apply `.roo/rules-orchestrator/rules.md` and `.roo/rules/phase-gate.md` first.

Use `/phase-discuss` for phase-local discovery only:

Preflight checklist:

- [ ] `.scratch/phase-state.json` is `phase=discuss`, or the user explicitly asked for read-only planning discovery from another non-execute state.
- [ ] No application-code edits are needed for this command.
- [ ] Any stack/profile/tool recommendation will be backed by repository evidence or explicit user input.

1. Read the required planning and phase-gate files.
2. Clarify goals, non-goals, constraints, risks, and repo-derived answers.
3. Record blocking questions and recommended defaults.
4. Do not draft the implementation plan yet.
5. Do not edit implementation files.

For one-pass automation, use `/fsd-run-phase <phase>` or another phase-gated workflow command; canonical automation rules live in `workflow-phase-gate`.

Advance the lifecycle only through the high-level CLI; do NOT direct-edit `.scratch/phase-state.json`:

```text
harness run
```
