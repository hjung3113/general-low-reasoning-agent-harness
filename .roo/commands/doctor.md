---
description: Diagnose planning, Roo, DB context, and mutation-readiness drift
argument-hint: [--format json|markdown]
mode: orchestrator
---

Use the `workflow-harness-doctor` skill for $ARGUMENTS.

Apply `.roo/rules-orchestrator/rules.md` first. Stay on `/doctor` for read-only harness diagnostics only. Report findings with severity, cause, impact, fix, evidence, and whether the diagnostic connects to DB. Do not mutate files from this command; use the reported diff-before-mutation guidance before any repair workflow.
