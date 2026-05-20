---
planning_doc_schema_version: 1
progress:
  total_phases: 2
  completed_phases: 1
  percent: 50
---

# STATE - General Low-Reasoning Agent Harness

## Current Position

- **Phase**: 2 - v0.8.0 Minimal Workflow Release.
- **Plan**: Phase 1 implementation is complete. Phase 2 has a four-command navigator workflow design and implementation plan prepared.
- **Status**: Phase 1 release work is complete. Phase 2 is entering execute based on the user's explicit instruction to reduce the exact-phrase approval deadlock and proceed.
- **Progress**: Phase 1: 1/1 plan complete; Phase 2: 0/1 plan executed; 1/2 phases complete overall.

## Active Checkpoint

- **Checkpoint**: CP-02-02 - contract and behavior.
- **Checkpoint file**: `.planning/phases/02-v0.8.0-minimal-workflow/02-CHECKPOINTS.md`.
- **Restart instruction**: Read this file, `ROADMAP.md`, `.planning/codebase/**`, `.planning/phases/02-v0.8.0-minimal-workflow/02-CONTEXT.md`, `.planning/phases/02-v0.8.0-minimal-workflow/02-01-PLAN.md`, then `.scratch/phase-state.json`. Continue only if the live gate names Phase 2 with `phase=execute` and `approved=true`.

## Decisions In Force

- Core protocol is client-neutral and stack-neutral.
- Roo and OpenCode are adapters.
- Skill packs are generic plugins selected per request.
- Stack-specific assumptions are not core.
- v0.8.0 normal user-facing workflow is capped at `harness`, `harness next`, `harness run`, and `harness check`.
- `HARNESS_MACHINE=1` is the v0.8 adapter/machine trigger for high-level JSON contracts.

## Next Action

Finish Phase 2 execute gate setup, then start implementation Task 1: high-level `HARNESS_MACHINE=1 harness next/run/check` JSON contract goldens.
