# Phase 2 Verification - v0.8.0 Minimal Workflow Release

## Required Commands

```bash
python3 -m unittest scripts/test_cli_contract.py
python3 -m unittest scripts/test_harness.py
pytest
python3 scripts/harness.py check
python3 scripts/harness.py check --worktree
python3 scripts/release_smoke_test.py
python3 scripts/harness.py release-check --expected-version v0.8.0
```

## Required Evidence

- High-level JSON golden diffs reviewed.
- Normal command output scrub evidence recorded.
- Adapter prompt scrub evidence recorded.
- README/manual/UML doc review recorded.
- Specialist adversarial reviews recorded under `.review/`.
- Claude combined ship-blocker review recorded.
- Release-check, smoke, and test output recorded.

## 2026-05-19 Evidence

- `python3 -m unittest scripts/test_cli_contract.py scripts/test_harness.py` -> PASS, 238 tests.
- `python3 scripts/harness.py check` -> PASS.
- `python3 scripts/harness.py check --worktree` -> PASS after adding `pyproject.toml` to Phase 2 allowed paths.
- `/tmp/harness-v080-venv/bin/python scripts/release_smoke_test.py` with runtime deps -> PASS.
- Claude adversarial review initially returned NO-GO; follow-up fixes landed for machine `check` diagnostics, machine contract documentation, and normal `harness run` internal-error scrubbing.

## Completion Rule

Do not mark Phase 2 complete unless every objective requirement maps to concrete evidence and no ship blocker remains unresolved.
