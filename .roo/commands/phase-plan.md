---
description: Run phase plan only (docs and plan artifacts)
argument-hint: <approved discuss output or phase scope>
mode: architect
---

Use the `workflow-phase-gate` skill for $ARGUMENTS.

Apply `.roo/rules-orchestrator/rules.md` and `.roo/rules/phase-gate.md` first.

Use `/phase-plan` for phase planning only:

1. Start from recorded phase discuss output or explicitly unresolved open questions.
2. Produce or update the phase plan with `plan_id`, allowed paths, acceptance criteria, verification, and review gates.
3. Request or record execute approval.
4. Do not implement behavior changes.
5. Do not edit implementation files.

For one-pass automation, use `/fsd-phase <phase> --chain` or another phase-gated workflow command with `--chain`; canonical automation rules live in `workflow-phase-gate`.
