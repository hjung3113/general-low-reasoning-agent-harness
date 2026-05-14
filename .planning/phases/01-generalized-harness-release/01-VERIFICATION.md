# Phase 1 Verification

## Required Before Push

- `python3 -m unittest scripts/test_harness.py`
- `python3 scripts/harness.py check`
- `python3 scripts/harness.py check --worktree`
- `python3 scripts/release_smoke_test.py`
- pre-push adversarial subagent review
- git commit
- remote push

## Evidence - 2026-05-15

| Check | Result | Evidence |
| --- | --- | --- |
| Unit tests | PASS | `python3 -m unittest scripts/test_harness.py` -> 55 tests passed. |
| Source check | PASS | `python3 scripts/harness.py check` -> exit 0. |
| Worktree scope check | PASS | `python3 scripts/harness.py check --worktree` -> exit 0; changed paths are inside approved `README.md`, `.planning/`, `docs/`, `harness/`, and `scripts/` scopes. |
| Target release smoke matrix | PASS | `python3 scripts/release_smoke_test.py` covers core, OpenCode, Roo, both, python-analysis, dotnet-etl, web, workflow-quality, and all-packs install/check/target-smoke cases. Post-push rerun also passed. |
| Skill ecosystem review | PASS | `docs/research/skill-ecosystem-review.md` records reviewed sources, accepted patterns, rejected patterns, and future pack candidates. |
| Upgrade remembered init scope | PASS | `scripts/harness.py` now records `init_options`; upgrade defaults to installed `init_options` and explicit upgrade scope refreshes the remembered scope. Covered by `test_init_records_scope_and_upgrade_reuses_it_by_default`. |
| Three expert adversarial reviews | BLOCKED THEN ADDRESSED | `019e278f-cc4e-79f0-8d76-139ebaf19231` flagged core stack leakage and stale review evidence; fixed by making workflow-core examples stack-neutral and documenting 3 reviews. `019e278f-cc82-7450-a9e9-a289b726da27` flagged missing workflow categories, shallow skills, missing research ledger, and missing end-to-end example; fixed with workflow-quality packs, output contracts, README ledger example, and research doc. `019e278f-ccb6-7be2-b8eb-d534c66f70fa` flagged dirty git/stale completion evidence; commit/push evidence must be refreshed after final verification. |
| Diff check | PASS | `git diff --check` -> exit 0. |
| Commit | PASS | Final release candidate committed after verification. |
| Push | PASS | Final release candidate pushed to `origin/main`; clean synchronized branch confirmed by `git status --short --branch`. |

## Prompt-To-Artifact Checklist

| Requirement | Evidence | Status |
| --- | --- | --- |
| Research external skill ecosystems | `docs/research/skill-ecosystem-review.md` covers Anthropic Skills, Claude Agent Skills, official plugins, Superpowers, Everything Claude Code, and Awesome OpenCode. | PASS |
| Broaden tech/workflow/script skill packs | Added workflow-quality packs: `workflow-tdd`, `workflow-debugging`, `workflow-code-review`, `workflow-skill-authoring`, `workflow-security-review`; added core research/review/audit skills. | PASS |
| Keep low-reasoning model customization | New and updated skills include activation evidence, stop conditions, output contracts, and worked examples. | PASS |
| Keep core client-neutral and stack-neutral | Default `workflow-core` example uses generic integration/verification/review only; stack-specific ETL content remains in optional profile/pack docs. | PASS |
| Add representative examples | README includes pack composition examples and an end-to-end evidence -> selected skills -> rejected skills -> verification ledger example. | PASS |
| Add scripts if useful | `scripts/release_smoke_test.py` includes `workflow-quality`; `scripts/harness.py` records and reuses `init_options` for upgrade. | PASS |
| Remember init choices for upgrade | `.harness/installed-manifest.json` records `init_options`; upgrade uses them when scope flags are omitted. | PASS |
| Obtain 3 expert adversarial reviews | Three subagents returned `NO-PASS`; blocking findings were addressed and final commit/push evidence was refreshed. | PASS |
| Update README | README documents new packs, research basis, end-to-end example, release smoke case, and upgrade remembered scope. | PASS |
| Verify before push | Unit tests, source check, worktree check, and release smoke matrix pass before commit. | PASS |

## Target Matrix Covered By `scripts/release_smoke_test.py`

- core-only: `--adapters none`
- OpenCode-only: `--adapters opencode`
- Roo-only: `--adapters roo`
- Roo+OpenCode: `--adapters both`
- Python analysis: `--adapters opencode --packs workflow-core,tech-python,workflow-data-analysis`
- C#/.NET + MSSQL + ETL composition: `--adapters both --profiles generic,dotnet-etl-mssql --packs workflow-core,tech-csharp,tech-mssql,workflow-etl,workflow-db-context`
- React/TypeScript/Tailwind web composition: `--packs workflow-core,tech-react,tech-typescript,tech-tailwind,workflow-web-development`
- Workflow quality composition: `--packs workflow-core,workflow-tdd,workflow-debugging,workflow-code-review,workflow-skill-authoring,workflow-security-review`
- all representative packs together with both adapters
