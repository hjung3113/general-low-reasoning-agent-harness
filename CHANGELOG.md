# Changelog

## Unreleased (develop)

### Added

- **M12 — Roo adapter parity + sample walkthrough.** `.roo/rules/phase-gate.md` and `.roo/commands/phase-{discuss,plan,execute}.md` now carry the same STOP banner, STEP 0 guard check, and verbatim refusal template that `.opencode/commands/*.md` got in M11. Either editor delivers equivalent prompt-layer defense against premature source-file writes.
- **Sample walkthrough.** `docs/examples/calc-walkthrough.html` — single-file tutorial built from the M11 calc-iter4 live test. Eight steps from `harness install` to commit, each showing the verbatim user prompt, agent action, and repository-state delta (including the moment the gate refuses a premature code request). Linked from README "Sample walkthrough" and both MANUAL.md / MANUAL.ko.md "에디터 어댑터" sections.

### Fixed

- **`workflow-m0-orient` skill not deployed by default.** M11 declared M0 orientation mandatory, but the skill pack was omitted from every default profile's pack list (`scripts/lib/profiles.py:_PROFILE_DEFAULT_PACKS`). Result: a fresh `harness init` produced no `.agents/skills/workflow-m0-orient/SKILL.md`, so agents had no skill body to follow for the greenfield interview / existing-code detection. Added `workflow-m0-orient` to all four default profiles (`generic`, `dotnet-etl`, `python-etl`, `react-web`).
- **No Roo mirror for `workflow-m0-orient`.** `.opencode/commands/*.md` and `.roo/commands/*.md` were mirrored in M12, but skills were not — Roo loads its skills from `.roo/skills/`, and the M0 skill never landed there. Added a `.roo/skills/workflow-m0-orient/SKILL.md` manifest entry sourced from the same pack file.
- **Uninstall left `.planning/codebase/` behind** when `seed`-policy files were tracked. Added `"seed"` to the policy allowlist in `scripts/uninstall_harness.py:build_removal_plan` so seed-policy files (e.g. `.planning/codebase/STACK.md`) are removed alongside `harness-owned` files.
- **Drift check false-positive in harness-self repo** (`scripts/lib/check.py`): `check_phase_source_drift` previously flagged the harness's own root files (`pyproject.toml`, `harness_cli.py`) when developing the harness itself. Now skipped when `harness/manifest.json` is present (the unambiguous signal that this is the harness source repo, not a target project).

### Breaking

- **phase=done contract**: `state_schema_version` 2 makes `phase=done` terminal. Backward migration via `--resume` only (ADR Ledger L12).
- **7-verb verification allowlist** (ADR Ledger L5 + L19): only `python3`, `git`, `jq`, `npx`, `pytest`, `harness`, `make` accepted as verification prefixes.
- Autopilot scaffolding removed (Milestone 2 Item 7): `execution_mode` collapses to `manual`; exit code 18 (`EXIT_NO_ACTION_DURING_AUTOPILOT`) dropped.
- State migration v0↔v2 removed (Milestone 2 Item 1): all state files now born at `state_schema_version=2`.
