# Milestone 0 — Orientation

This is the mandatory first milestone (ADR-0009). Close M0 by completing codebase orientation: either via auto-detection (`harness recon` + `workflow-m0-orient` skill) for existing code, or via grill-style interview seeded by `workflow-m0-orient` for greenfield projects.

`harness check` refuses to advance to Milestone 1 until M0 done criteria pass:
- All 6 core `.planning/codebase/*.md` have `status: current`
- `.planning/ROADMAP.md` has at least 1 future-milestone bullet
- `.planning/STATE.md` is ready to advance

See [`docs/CODEBASE-SCHEMA.md`](../../docs/CODEBASE-SCHEMA.md) for the orientation file schema and [`docs/adr/0009-m0-as-mandatory-orientation.md`](../../docs/adr/0009-m0-as-mandatory-orientation.md) for the decision rationale.
