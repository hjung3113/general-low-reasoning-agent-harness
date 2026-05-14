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
| Unit tests | PASS | `python3 -m unittest scripts/test_harness.py` -> 53 tests passed. |
| Source check | PASS | `python3 scripts/harness.py check` -> exit 0. |
| Worktree scope check | PASS | `python3 scripts/harness.py check --worktree` -> exit 0; current changed paths are inside `.scratch/phase-state.json`, `.opencode/`, `README.md`, `docs/`, `harness/`, and `scripts/`. |
| Target release smoke matrix | PASS | `python3 scripts/release_smoke_test.py` covers core, OpenCode, Roo, both, python-analysis, dotnet-etl, web, and all-packs install/check/target-smoke cases. Latest temp matrix: `/var/folders/6t/ddmgth_n47j1dq_mwk8lm6700000gn/T/harness-release-smoke.xgu1qerh`. |
| Pre-push adversarial review | BLOCKED THEN ADDRESSED | Subagent `019e2782-6d80-7453-8af9-c20501d1a8d9` returned NO-PUSH for missing ledger evidence, placeholder verification, and missing `check --worktree` regression tests. Follow-up changes added this ledger, replaced the placeholder with `python3 scripts/release_smoke_test.py`, and added focused worktree tests. |
| Commit | PASS | `8805dc31e8a071a6a643df24ec121fbecfea68bc` (`fix: harden generalized harness release gates`). |
| Push | PENDING | Fill with remote branch after push. |

## Target Matrix Covered By `scripts/release_smoke_test.py`

- core-only: `--adapters none`
- OpenCode-only: `--adapters opencode`
- Roo-only: `--adapters roo`
- Roo+OpenCode: `--adapters both`
- Python analysis: `--adapters opencode --packs workflow-core,tech-python,workflow-data-analysis`
- C#/.NET + MSSQL + ETL composition: `--adapters both --profiles generic,dotnet-etl-mssql --packs workflow-core,tech-csharp,tech-mssql,workflow-etl,workflow-db-context`
- React/TypeScript/Tailwind web composition: `--packs workflow-core,tech-react,tech-typescript,tech-tailwind,workflow-web-development`
- all representative packs together with both adapters
