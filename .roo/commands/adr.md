---
description: Run the architecture decision workflow
argument-hint: <decision, tradeoff, or design question>
mode: architect
---

Use the `workflow-architecture-decision` skill for $ARGUMENTS.

Apply `.roo/rules-orchestrator/rules.md` first. Stay on `/adr` only for durable design decisions, boundaries, state models, tradeoffs, or implementation planning. Before writing ADR decisions or phase commitments, align with the user one question at a time and record the alignment summary required by `workflow-architecture-decision`.

When an ADR adds, deletes, renumbers, inserts, completes, or reopens a roadmap phase, update `.planning/ROADMAP.md`, `.planning/STATE.md`, the active phase `*-CHECKPOINTS.md`, and `.scratch/phase-state.json` in the same change so the roadmap/state sync invariant remains checkable.
