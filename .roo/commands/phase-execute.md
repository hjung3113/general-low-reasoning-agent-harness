---
description: Route approved phase execute work to the owning implementation mode
argument-hint: <approved plan_id and implementation task>
mode: orchestrator
---

Use the `workflow-phase-gate` skill for $ARGUMENTS.

Apply `.roo/rules-orchestrator/rules.md` and `.roo/rules/phase-gate.md` first.

Use `/phase-execute` only for approved execute handoff:

1. Verify the live gate via `python3 scripts/harness.py check` reports `phase=execute`, `approved=true`, the same `plan_id`, durable pointers, non-empty `allowed_paths`, and non-empty `verification`. Reach that state via `python3 scripts/harness.py phase approve && python3 scripts/harness.py phase set execute`; do NOT direct-edit `.scratch/phase-state.json`.
2. Choose the narrowest owning mode for the approved paths and concern.
3. Create the required handoff packet from `.roo/rules-orchestrator/rules.md`.
4. Do not implement inline from orchestrator.
5. If `new_task` is unavailable, output the handoff packet and stop.

Do not restate or weaken `--chain` safety rules here. The canonical conditions are the `workflow-phase-gate` Automation Flags and Stop Conditions.

Move forward in the phase lifecycle via the CLI:

```text
python3 scripts/harness.py phase set <discuss|plan|execute|done>
python3 scripts/harness.py phase approve   # only in phase=plan or phase=execute; exit 6 in done (G2-C)
```
