---
description: Route one full phase lifecycle through the canonical phase gate
argument-hint: <phase number or phase slug> [--chain]
mode: orchestrator
---

Use the `workflow-phase-gate` skill for $ARGUMENTS.

Apply `.roo/rules-orchestrator/rules.md` and `.roo/rules/phase-gate.md` first.

`/fsd-phase` is the recommended one-command phase entry, but it is a router, not an inline implementation command:

1. Run phase-local `discuss` through the canonical phase gate and hand planning work to the owning planning mode.
2. Run phase `plan` through the canonical phase gate so the plan records `plan_id`, `allowed_paths`, acceptance criteria, verification, and approval evidence.
3. Enter `execute` only when the canonical gate verifies matching `phase=execute`, `approved=true`, `plan_id`, durable pointers, `allowed_paths`, and `verification`.
4. Create the owning-mode handoff packet from `.roo/rules-orchestrator/rules.md`; the orchestrator does not implement inline.
5. If `new_task` is unavailable, output the handoff packet and stop.

Usage examples:

- `/fsd-phase 1 --chain`
- `/fsd-phase 03-harness-distribution-enforcement --chain`

Do not restate or weaken `--chain` safety rules here. The canonical conditions are the `workflow-phase-gate` Automation Flags and Stop Conditions. If any required condition fails, stop before execute and request approval or state correction.
