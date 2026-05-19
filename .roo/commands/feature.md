---
description: Run the feature TDD workflow
argument-hint: <feature request or issue path>
mode: orchestrator
---

Use the `workflow-feature-tdd` skill for $ARGUMENTS.

Apply `.roo/rules-orchestrator/rules.md` and `.roo/rules/phase-gate.md` first. Stay on `/feature` only when the work is ordinary application behavior or refactoring not owned by `/etl`, `/db`, `/review`, `ops-observability`, `/adr`, `/issues`, or `harness-maintainer`.

If the harness prints a `[y/N]` prompt, stop and ask the user to confirm from their own terminal. Do not answer the prompt yourself — speed-bump is the user's checkpoint.
