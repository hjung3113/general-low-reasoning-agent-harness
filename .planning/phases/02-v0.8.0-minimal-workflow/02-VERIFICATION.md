# Phase 02 — Verification

## Commands

- `python3 -m unittest scripts.tests.test_harness` — test suite (currently has known failures post-strip; tracked as follow-up).
- `python3 scripts/harness.py check` — manifest + state invariants. Pass.
- `python3 scripts/harness.py check --worktree` — worktree-aware variant. Pass.

## Evidence

Commits `e61fe22`, `ce62ed9`, `eedef26`, `ffddf34`, `752ad68`, `8d23817`, `92679f6`, `eeab5b4`.
