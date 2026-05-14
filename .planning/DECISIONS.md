# DECISIONS - Roo Harness Planning

Status values: `Proposed`, `Accepted`, `Locked`, `Superseded`.

| ID | Status | Decision | Source | Scope |
| --- | --- | --- | --- | --- |
| DEC-0001 | Accepted | `.planning/` is canonical project memory. | `.planning/PROJECT.md` | All phases |
| DEC-0002 | Accepted | `.scratch/phase-state.json` is a gate, not the plan. | `.planning/PROJECT.md`, `docs/phase-gate-harness.md` | Phase gate |
| DEC-0003 | Accepted | Every phase closes with summary and verification evidence. | `.planning/PROJECT.md`, `.planning/phases/01-document-centered-phase-continuity/01-CHECKPOINTS.md` | All phases |
| DEC-0004 | Accepted | New sessions start at `.planning/STATE.md`, then read live phase state. | `.planning/HANDOFF-PROTOCOL.md`, `AGENTS.md` | Continuity |
| DEC-0005 | Accepted | Phase 3 adds mechanical checks for phase-state validity, allowed-path drift, harness ownership, and clean-skeleton contamination. | `.planning/ROADMAP.md`, `scripts/harness.py` | Enforcement |
| DEC-0006 | Accepted | Target projects consume the harness through a clean skeleton plus manifest-based init/upgrade; live project planning state is project-owned and not overwritten by upgrade. | `harness/manifest.json`, `harness/skeleton/clean/` | Distribution |
| DEC-0007 | Accepted | `AGENTS.md` and `README.md` should use managed-block merge semantics for harness-owned sections: initial install creates the full files, while upgrade refreshes only marked harness blocks and preserves target-repo edits outside those blocks. Until the merge algorithm exists, `managed` remains file-level conflict behavior and docs must not claim automatic block merging is implemented. | `harness/manifest.json`, `README.md`, Issue #16 design review | Distribution |

## Promotion Rule

When a phase-local decision affects more than one phase, promote it here or into `docs/adr/` if it needs a full ADR.
