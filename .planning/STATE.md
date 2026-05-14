---
progress:
  total_phases: 1
  completed_phases: 0
  percent: 0
---

# STATE - General Low-Reasoning Agent Harness

## Current Position

- **Phase**: 1 - Generalized Harness Release.
- **Plan**: Working implementation for stack-neutral core, OpenCode compatibility, and composable skill packs.
- **Status**: Execute work is in progress; pack catalog, dotnet-etl-mssql composition, Korean README, and second-pass review are being verified.
- **Progress**: Phase 1: 0/1 plan complete; 0/1 phases complete overall.

## Active Checkpoint

- **Checkpoint**: CP-01-02 - implementation and verification in progress.
- **Checkpoint file**: `.planning/phases/01-generalized-harness-release/01-CHECKPOINTS.md`.
- **Restart instruction**: Read this file, `ROADMAP.md`, `.planning/codebase/**`, the active checkpoint, then `.scratch/phase-state.json`. Continue verification before push.

## Decisions In Force

- Core protocol is client-neutral and stack-neutral.
- Roo and OpenCode are adapters.
- Skill packs are generic plugins selected per request.
- Stack-specific assumptions are not core.

## Next Action

Run final release verification, commit, push, and complete the audit.
