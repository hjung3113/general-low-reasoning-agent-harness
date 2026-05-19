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

## 2026-05-19 v0.8.2 Evidence

- Specialist reviews completed for workflow/protocol, UX/docs, and low-reasoning model burden. Summary recorded in `.planning/phases/02-v0.8.0-minimal-workflow/02-ADVERSARIAL-REVIEW-v0.8.2.md`.
- Claude adversarial review completed after fixes -> no blockers; warning-path `next_steps` test coverage added.
- `python3 -m unittest scripts/test_show_phase_status.py` -> PASS, 14 tests.
- `python3 -m unittest scripts/test_adapter_contract_docs.py` -> PASS, 2 tests.
- `python3 -m unittest scripts/test_harness.py` -> PASS, 228 tests.
- `python3 scripts/harness.py check` -> PASS.
- `python3 scripts/harness.py check --worktree` -> PASS.
- `PATH=/tmp/harness-v082-venv/bin:$PATH /tmp/harness-v082-venv/bin/python scripts/release_smoke_test.py` -> PASS.
- Source verification was run before local tag creation because `test_harness.py` includes fake-version upgrade scenarios that intentionally conflict with an exact local release tag.
- After commit/tag, `python3 scripts/harness.py release-check --expected-version v0.8.2` -> PASS.
- The local `v0.8.2` tag is annotated but not SSH-signed because this checkout has no configured release signing key and `docs/trust/allowed-signers` remains a placeholder trust root.

## Completion Rule

Do not mark Phase 2 complete unless every objective requirement maps to concrete evidence and no ship blocker remains unresolved.
