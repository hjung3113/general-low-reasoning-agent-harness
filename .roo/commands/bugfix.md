---
description: Run the root-cause bugfix workflow
argument-hint: <bug report, failing test, log, or issue path>
mode: orchestrator
---

Use the `workflow-bug-diagnosis` skill for $ARGUMENTS.

Apply `.roo/rules-orchestrator/rules.md` and `.roo/rules/phase-gate.md` first. Stay on `/bugfix` only when behavior is broken, tests fail, output is wrong, performance regressed, or the root cause is unknown.
