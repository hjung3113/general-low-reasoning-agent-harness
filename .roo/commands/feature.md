---
description: Run the feature TDD workflow
argument-hint: <feature request or issue path>
mode: orchestrator
---

Use the `workflow-feature-tdd` skill for $ARGUMENTS.

Apply `.roo/rules-orchestrator/rules.md` and `.roo/rules/phase-gate.md` first. Stay on `/feature` only when the work is ordinary application behavior or refactoring not owned by `/etl`, `/db`, `/review`, `ops-observability`, `/adr`, `/issues`, or `harness-maintainer`.
