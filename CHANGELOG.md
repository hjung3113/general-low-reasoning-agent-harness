# Changelog

## Unreleased (develop)

### Breaking

- **phase=done contract** (carried forward from v0.8.0): `state_schema_version` 2 makes `phase=done` terminal. Backward migration via `--resume` only (ADR Ledger L12).
- **7-verb verification allowlist** (ADR Ledger L5 + L19): only `python3`, `git`, `jq`, `npx`, `pytest`, `harness`, `make` accepted as verification prefixes.
- Autopilot scaffolding removed (Milestone 2 Item 7): `execution_mode` collapses to `manual`; exit code 18 (`EXIT_NO_ACTION_DURING_AUTOPILOT`) dropped.
- State migration v0↔v2 removed (Milestone 2 Item 1): all state files now born at `state_schema_version=2`.

## v1.0.1 — 2026-05-25

Hardening release: 5-layer phase-gate defense against CC9 (premature source-code writes), Roo adapter parity with opencode, sample walkthrough, plus four bug fixes around M0 orientation skill deployment.

### Added

- **M11 iter1–4 — CC9 hardening (4-iteration live test with opencode + zai/glm-4.5-flash).** Five-layer defense against agents that obey a "write the code now" request before approval:
  - iter1 — speed-bump STOP banners in `.opencode/commands/{discuss,plan,execute,done}.md` with phase-specific FORBIDDEN/ALLOWED file extension lists.
  - iter2 — `harness next --prompt` CLI flag emits a live guard block (phase, approved, forbidden writes, refusal template); `check_phase_source_drift` invariant added to `harness check` to catch post-hoc source writes outside `.planning/` during `phase ∈ {discuss, plan}`.
  - iter3 — `AGENTS.md` managed phase-guard block (loaded every turn, not just on slash commands); Step 0 guard re-emit added to each `.opencode/commands/*.md`.
  - iter4 — pre-commit hook auto-installed on `harness init` (opt-out via `HARNESS_INIT_SKIP_GIT_HOOK=1`); refusal template fidelity — exact 3-command chain (`phase set plan` → `phase approve` → `phase set execute`) with "do not shorten" warning.
  - Outcome: CC9 prevention conf 90 in iter4 (vs. baseline conf 0). See `.planning/milestones/11-m0-orient-and-rename/` and `docs/examples/calc-walkthrough.html` for the live test trace.
- **M12 — Roo adapter parity + sample walkthrough.** `.roo/rules/phase-gate.md` and `.roo/commands/phase-{discuss,plan,execute}.md` now carry the same STOP banner, STEP 0 guard check, and verbatim refusal template that `.opencode/commands/*.md` got in M11. Either editor delivers equivalent prompt-layer defense against premature source-file writes.
- **Sample walkthrough.** `docs/examples/calc-walkthrough.html` — single-file tutorial built from the M11 calc-iter4 live test. Eight steps from `harness install` to commit, each showing the verbatim user prompt, agent action, and repository-state delta (including the moment the gate refuses a premature code request). Linked from README "Sample walkthrough" and both MANUAL.md / MANUAL.ko.md "에디터 어댑터" sections.

### Fixed

- **`workflow-m0-orient` skill not deployed by default.** M11 declared M0 orientation mandatory, but the skill pack was omitted from every default profile's pack list (`scripts/lib/profiles.py:_PROFILE_DEFAULT_PACKS`). Result: a fresh `harness init` produced no `.agents/skills/workflow-m0-orient/SKILL.md`, so agents had no skill body to follow for the greenfield interview / existing-code detection. Added `workflow-m0-orient` to all four default profiles (`generic`, `dotnet-etl`, `python-etl`, `react-web`).
- **No Roo mirror for `workflow-m0-orient`.** `.opencode/commands/*.md` and `.roo/commands/*.md` were mirrored in M12, but skills were not — Roo loads its skills from `.roo/skills/`, and the M0 skill never landed there. Added a `.roo/skills/workflow-m0-orient/SKILL.md` manifest entry sourced from the same pack file.
- **Uninstall left `.planning/codebase/` behind** when `seed`-policy files were tracked. Added `"seed"` to the policy allowlist in `scripts/uninstall_harness.py:build_removal_plan` so seed-policy files (e.g. `.planning/codebase/STACK.md`) are removed alongside `harness-owned` files.
- **Drift check false-positive in harness-self repo** (`scripts/lib/check.py`): `check_phase_source_drift` previously flagged the harness's own root files (`pyproject.toml`, `harness_cli.py`) when developing the harness itself. Now skipped when `harness/manifest.json` is present (the unambiguous signal that this is the harness source repo, not a target project).

## v1.0.0

### Breaking

- **phase=done contract**: `state_schema_version` 2 makes `phase=done` terminal. Backward migration via `--resume` only (ADR Ledger L12).
- **7-verb verification allowlist** (ADR Ledger L5 + L19): only `python3`, `git`, `jq`, `npx`, `pytest`, `harness`, `make` accepted as verification prefixes.
- Autopilot scaffolding removed (Milestone 2 Item 7): `execution_mode` collapses to `manual`; exit code 18 (`EXIT_NO_ACTION_DURING_AUTOPILOT`) dropped.
- State migration v0↔v2 removed (Milestone 2 Item 1): all state files now born at `state_schema_version=2`.
