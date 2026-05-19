# v0.8.2 Adversarial Review Record

Date: 2026-05-19

## Specialist Delegation

- Workflow/protocol review identified low-risk improvements in CLI help, `show_phase_status.py`, silent `harness check` documentation, adapter preflight parity, and command matrices.
- UX/docs review identified stale v0.8.1 examples, early low-level state guidance, copy-paste prompt gaps, missing approval action, missing `next_user_prompt`, and stale adapter machine fields.
- Low-reasoning burden review identified dense status projection output, missing script-running guidance in root `AGENTS.md`, status response templates, and deterministic workflow checklists.

## Implemented Scope

- Added `next_steps` to `show_phase_status.py` output through `scripts/lib/planning_status.py`.
- Added positive and warning-path tests for `next_steps`.
- Updated adapter commands to use current `HARNESS_MACHINE=1 harness next` fields and stronger execute preflight via `harness check` plus `show_phase_status.py`.
- Added adapter contract doc tests for stale machine field regressions and projection-gate requirements.
- Clarified approval boundary and `next_user_prompt` handling in use-case docs.
- Updated README, manual, UML workflow docs, script-oriented contract docs, changelog, and package version for v0.8.2.

## Adversarial Findings And Resolution

- P1: Adapter execute guard weakened by using `may_edit` alone. Fixed by requiring `harness check`, `show_phase_status.py`, `projected_execute_gate_valid=true`, no blocking warnings, non-empty `allowed_paths`, and non-empty `verification` before edits.
- P1: `release-check --expected-version v0.8.2` cannot pass before the v0.8.2 tag exists. Treated as a release-stage gate after commit/tag, not as pre-tag implementation evidence.
- P2: `phase-status.v1` docs did not include `next_steps`. Fixed in `docs/script-oriented-harness-workflow.md`.
- Claude adversarial review after fixes reported no blockers. It requested warning-path `next_steps` coverage, which was added.

## Verification

- `python3 -m unittest scripts/test_show_phase_status.py` -> PASS, 14 tests.
- `python3 -m unittest scripts/test_adapter_contract_docs.py` -> PASS, 2 tests.
- `python3 -m unittest scripts/test_harness.py` -> PASS, 228 tests.
- `python3 scripts/harness.py check` -> PASS.
- `python3 scripts/harness.py check --worktree` -> PASS.
- `PATH=/tmp/harness-v082-venv/bin:$PATH /tmp/harness-v082-venv/bin/python scripts/release_smoke_test.py` -> PASS.
- After commit/tag, `python3 scripts/harness.py release-check --expected-version v0.8.2` -> PASS.

## Known Non-Blocking Environment Note

- System `python3` is 3.9.6 and cannot install this project because `pyproject.toml` requires Python >=3.11.
- Release smoke was verified in a temporary Python 3.12 virtual environment with editable install.
- The local `v0.8.2` tag is annotated but not SSH-signed because this checkout has no configured release signing key and `docs/trust/allowed-signers` remains a placeholder trust root.
