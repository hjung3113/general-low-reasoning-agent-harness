# Phase 1 Context - Generalized Harness Release

## Confirmed Direction

- Preserve the existing workflow discipline.
- Remove project-specific assumptions from core.
- Treat OpenCode as a first-class adapter.
- Use generic, composable workflow skill plugins instead of hard-coded tech-stack skill bundles.
- Recreate old specialized C#/.NET + MSSQL + ETL behavior through `dotnet-etl-mssql` plus selected packs, not through core defaults.

## Expert Review Themes

- Add concrete phase checklists and release gates.
- Make OpenCode-only targets valid.
- Keep profiles evidence-based.
- Keep installer/check/upgrade behavior aligned with documented CLI.
- Prevent stale Roo or stack-specific guardrails from leaking into core.
