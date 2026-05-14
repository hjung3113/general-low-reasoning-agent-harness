---
description: Run the lightweight simple-task workflow
argument-hint: <focused question, small edit, command, cleanup, or tiny verified change>
mode: orchestrator
---

Use the `workflow-simple-task` skill for $ARGUMENTS.

Apply `.roo/rules-orchestrator/rules.md` first. Stay on `/simple` only when the task is small, low-risk, and has an obvious verification step. If the request touches persistence, ETL flow, ops, security, architecture, phase state, broad refactoring, or ambiguous behavior, route to the narrower workflow instead.
