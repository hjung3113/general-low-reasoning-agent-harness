# v0.9.7 Pre-Tag Fix Brief

Adversarial review on `develop` diff found real CRITs. Apply these surgical fixes before tag.

Working dir: `/Users/hyojung/Desktop/2026/general-low-reasoning-agent-harness`
Branch: `develop` (current HEAD `3a6fa70`)

## Source reviews (read in full)
- `.planning/phases/02f-v0.9.6-hotfix/reviews/DIFF-review-codex.md`
- `.planning/phases/02f-v0.9.6-hotfix/reviews/DIFF-review-architect.md`
- `.planning/phases/02f-v0.9.6-hotfix/reviews/DIFF-review-ops-hawk.md`
- `.planning/phases/02f-v0.9.6-hotfix/reviews/DIFF-review-lrr.md`

## Fix tasks (per-task atomic commits)

### FIX-1: state_cli rc=1/rc=2 implementation [CRIT — v0.9.5 NEW-3 repeat]
**File:** `scripts/lib/state_cli.py` (`run_repair`)
**Change:** After `state_repair.repair(root)` call, inspect `RecoveryResult` (or whatever `repair()` returns). If `len(recovery.quarantined) > 0` → return 1. If `repair()` raises a non-RepairRefused exception → return 2 (catastrophic). Otherwise return 0.
**Possible refactor:** `state_repair.repair()` may need to surface the RecoveryResult; check `_recover_aborted_installs` callee and propagate counts up.
**Test:** add CLI-level assertion (subprocess) in `tests/test_install_recovery_pending_manifest.py` OR new `tests/test_state_repair_exit_codes.py`:
  - rc=0 on no-op
  - rc=0 on clean finalize
  - rc=1 on orphan-pending quarantine
  - rc=2 on catastrophic (mock raise)

### FIX-2: Drift gate stale cache semantic [CRIT]
**File:** `tests/test_known_failures_drift.py`
**Current:** stale cache `pytest.skip` unless `HARNESS_KNOWN_FAILURES_STRICT=1`
**Required:** stale cache `pytest.fail` (or assert False) by default; bypass via `HARNESS_KNOWN_FAILURES_ALLOW_STALE=1`
**Update:** docstring + `scripts/refresh_known_failures.sh` documentation comment

### FIX-3: Upgrade finalize via os.replace(pending, final) + post-batch payload regeneration [CRIT — Architect C-1/C-2, Codex MAJOR-2]
**File:** `scripts/lib/upgrade.py` (`run_upgrade` around lines 1011-1060)
**Current:** Step B5 writes final via `write_json(final_path, installed)` AFTER mutating `installed["files"][".roomodes"]` post-batch. Pending sidecar has STALE pre-batch content.
**Fix (pick (a) — simpler):** Move the `.roomodes` hash patch + any other post-batch mutations BEFORE writing the pending sidecar. Then:
  - Step B2 writes pending with FINAL payload (post-mutation)
  - Step B5 becomes `os.replace(str(pending_path), str(final_path))` — same as install.py:375
  - Step B6 (verify): re-read final, assert version
  - Step B7 (cleanup): unlink sentinel/journal, rmtree staging
**Test:** add assertion in `tests/test_upgrade_atomic_wire.py` that pending sidecar bytes equal final manifest bytes (IMPL-PLAN T4 test #4 — currently missing).

### FIX-4: Upgrade Pass A write-free [MAJOR — Codex MAJOR-1]
**File:** `scripts/lib/upgrade.py`
**Current:** Pass A mutates managed-append targets (line ~795) and deletes retired files (line ~875). This is BEFORE pending sidecar is written.
**Fix:** Move managed-append write + retired-file deletion to AFTER pending sidecar is written AND after the atomic batch completes. Pass A computes the plan only.
**Alternative if move is risky:** Narrow IMPL-PLAN claim — document in CHANGELOG that managed-append + retired-file deletion remain in-place (not atomic). This is what M-1 from Codex said; "narrow the claim". Pick whichever is simpler — if Pass A restructuring is touchy, narrow the claim. Document the choice in `impl-deviations.md`.

### FIX-5: Version refs v0.9.6 → v0.9.7 [MAJOR — Codex MAJOR-3]
**Files:**
- `docs/site/manual.html:1004` (tag command), `:1009` (push/verify)
- `docs/use-cases/README.md:3` (intro)
- Any other matches from `git grep -nE 'v?0\.9\.6' -- ':!CHANGELOG.md' ':!.planning'`
**Caveat:** preserve INTENTIONAL historical references (e.g., "upgraded from v0.9.6 to v0.9.7" is fine if it's describing the upgrade).

### FIX-6: USER_MANUAL examples ↔ actual code output sync [MAJOR — LRR M-3]
**File:** `docs/USER_MANUAL.md` recovery section (around line 1093-1136)
**Approach (pick whichever is faster):**
(a) Add the documented output lines as actual print/log statements in `state_cli.run_repair` (mirror the audit verb to stdout)
(b) Replace the manual examples with the ACTUAL output `state_cli.run_repair` produces — paste real CLI session (run it!)
**Regen** `docs/site/manual.html` after.

### FIX-7: Smoke evidence regen with real CLI output [LRR C-2, Hawk C-1]
**File:** `.planning/phases/02f-v0.9.6-hotfix/evidence/smoke-2026-05-21.md`
**Current:** Scenarios 2/3/5 contain unit-test reformatted output.
**Fix:** For each scenario, run an actual scripted reproduction:
  - Scenario 2: in a tempdir, do `harness init`, then write `.aborted` to staging (simulating mid-batch abort), then run `state repair` via subprocess and paste real stdout
  - Scenario 3: simulate post-batch (sentinel exists, staging gone) via shell commands, run repair, paste
  - Scenario 5: simulate orphan-pending (write pending file only), run repair, paste rc=1 output
**Acceptance:** smoke evidence file shows REAL CLI stdout/stderr lines, NOT `RecoveryResult(...)` repr.

### FIX-8: KNOWN_FAILING_TESTS env documentation [MINOR — LRR M-4]
**File:** `tests/KNOWN_FAILING_TESTS.md`
**Current:** "Python 3.9.6 (system)"
**Action:** if reseed under 3.14 is fast, do it. If not, amend IMPL-PLAN.md to admit the actual seed env. Document in CHANGELOG that Python 3.9-3.14 baseline diverges and the seed reflects 3.9.6.

## Out of scope (deferred to v0.9.8)
- Concurrent install vs `state repair` lock (Hawk M-2 — repo-local internal-only acceptable)
- Test-seam for CLI SIGTERM (Hawk C-1 alt) — already deferred via FIX-7 evidence regen
- False-quarantine 35-files UX (Hawk M-3 — already in T8-triage)
- M-4 audit row for tmp_orphan cleanup (Hawk M-4 — nice-to-have)
- M-5 `_atomic_write_json_fsync` vs `atomic_write_text` consolidation (Hawk M-5 — refactor risk)
- Architect M-3 wrapper destination-hash fallback documentation (Architect M-3 — docstring)
- Architect M-2 resume overwrite contract (Architect M-2 — comment + test)
- LRR M-1 bilingual line breaks (LRR M-1 — UX polish)
- LRR M-2 check warning rate limit (LRR M-2 — UX polish)

## Workflow
- Per-fix atomic commit. Commit message format `fix(v0.9.7): <fix-id> — <summary>`.
- Run focused tests after each fix. Full pytest after all fixes.
- Update `.planning/phases/02f-v0.9.6-hotfix/evidence/impl-deviations.md` with any deviation from the fix brief.
- Do NOT tag or push. Stop after FIX-8 with a summary message listing commit shas.
