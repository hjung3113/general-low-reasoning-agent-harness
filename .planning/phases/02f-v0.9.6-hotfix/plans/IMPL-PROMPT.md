# v0.9.7 Hotfix Implementation Brief

You implement T1-T12 from `.planning/phases/02f-v0.9.6-hotfix/plans/IMPL-PLAN.md` (REV-2).

## Working directory
`/Users/hyojung/Desktop/2026/general-low-reasoning-agent-harness`

## Branch
`develop` (already checked out; HEAD is the planning commit `2122f18`)

## Workflow rules
- **Per-task atomic commits.** Each Tn becomes a single commit. Conventional commit prefix `feat(install-atomic):`, `refactor(state):`, `test(...)`, `docs(...)`, etc.
- **Tests first when reasonable.** For T1, T1.5, T2 write the new test file before the implementation. For T3-T8 implementation can precede tests if needed by complexity.
- **Pytest baseline.** Before T11 ships, full pytest failing-set must be ⊆ KNOWN_FAILING_TESTS.md.
- **Per-task verification.** Run `pytest <new test file>` after each task; do NOT mark task done until green.
- **Honest deviations.** If IMPL-PLAN spec needs adjustment during impl (e.g., function signature you discover doesn't exist as expected), note it in a comment in the commit message AND append a note to `.planning/phases/02f-v0.9.6-hotfix/evidence/impl-deviations.md`.
- **Do not skip T8 triage.** When T8 tests surface real upgrade bugs, populate `.planning/phases/02f-v0.9.6-hotfix/evidence/T8-triage.md`. T11 must wait.
- **No release.** Stop after T12 smoke evidence is captured. Do NOT tag or push v0.9.7 — release is user-gated per the workflow.

## Source files you will modify
- `scripts/lib/atomic_io.py`
- `scripts/lib/install_recovery.py`
- `scripts/lib/install.py`
- `scripts/lib/upgrade.py`
- `scripts/lib/state.py`
- `scripts/lib/check.py`
- `scripts/build_v094_fixture.py`
- `tests/test_upgrade_from_v094_clean.py`
- `tests/test_upgrade_from_v094_with_workaround.py`
- `docs/USER_MANUAL.md`, `docs/site/manual.html`
- `CHANGELOG.md` + version-ref locations enumerated in T11
- `.gitignore`

## New files to create
- `tests/test_atomic_install_batch_defer_cleanup.py` (T1)
- `tests/test_state_staged_hash.py` (T1.5)
- `tests/test_install_recovery_pending_manifest.py` (T2)
- `tests/test_install_atomic_wire.py` (T3)
- `tests/test_upgrade_atomic_wire.py` (T4)
- `tests/test_check_staging_detection.py` (T5)
- `tests/test_skip_upgrade_guard.py` (T6)
- `tests/test_fixture_determinism.py` (T7)
- `tests/KNOWN_FAILING_TESTS.md` (T9)
- `tests/test_known_failures_drift.py` (T9)
- `scripts/refresh_known_failures.sh` (T9)
- `.planning/phases/02f-v0.9.6-hotfix/evidence/T8-triage.md`
- `.planning/phases/02f-v0.9.6-hotfix/evidence/smoke-2026-05-21.md` (T12)
- `.planning/phases/02f-v0.9.6-hotfix/evidence/impl-deviations.md`

## Approach per task

Read the corresponding Tn section in IMPL-PLAN.md before starting. Implement EXACTLY the contract described — phase order, naming convention, error message text, exit codes are all pinned.

Important pinned contracts you must NOT deviate on without recording in impl-deviations.md:
- `runid = f"{os.getpid()}-{iso_compact}-{secrets.token_hex(3)}"` format
- Sentinel write via fsync(tmp_fd) + os.replace + fsync(parent_dir_fd)
- Sentinel + `.aborted` coexistence: `.aborted` wins (rollback) — check BEFORE sentinel in `_recover_pending_manifest`
- Bilingual error messages with `python3 scripts/harness.py state repair` invocation string
- `harness state repair` exit codes: 0 / 1 / 2

## Pitfalls flagged by reviewers (read before T3/T4)

- Architect C-1: `state.file_state` currently hashes destination — refactor in T1.5 BEFORE T3 needs it
- Architect C-3 / Codex MAJOR-1: `upgrade.py` builds manifest mid-loop — T4 must split into Pass A (plan, no writes) + Pass B (stage+batch+finalize)
- Hawk C-3: `.complete.tmp` orphan cleanup must run during `_recover_pending_manifest` scan
- LRR C-2 / v0.9.5 NEW-3: `state repair` exit code 0 on all errors is the previous-release trap; pin rc=1 for quarantine and rc=2 for catastrophic

## When you finish all tasks

Append a one-line summary per Tn (commit sha + tests-passing count) to `.planning/phases/02f-v0.9.6-hotfix/evidence/impl-summary.md`. Then return.

Do NOT proceed past T12. The user reviews T12 smoke evidence + adversarial diff review before tagging.
