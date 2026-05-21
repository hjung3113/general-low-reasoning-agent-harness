# Ops Hawk Final Diff Review — v0.9.7

Verdict: PASS-WITH-CONDITIONS

Scope: `git diff main..develop`; threat: repo-local, internal-only; durability lens.

## CRIT (block tag)

### C-1: T12 scenarios 2/3/5 covered only by unit tests — CLI SIGTERM path NEVER exercised end-to-end
`impl-deviations.md:25-33` admits that smoke scenarios 2, 3, and 5 were NOT run via `subprocess + SIGTERM` against `harness.py init`/`upgrade` because no test-seam exists. Unit tests on `_recover_pending_manifest` exercise the recovery *function*, but they do NOT cover:
- the `harness.py` CLI exit-code path back to the operator (see C-2 below — it's broken)
- the actual signal handling between `atomic_install_batch` mid-loop and the `os.replace(pending → final)` step at `install.py:375`
- the install/upgrade lock release behavior (if any) during forced termination
- whether the SIGTERM arrives between `os.replace(tmp, pending)` and `fsync(parent_dir_fd)` for the pending sidecar in `_atomic_write_json_fsync` (`install.py:535-568`) — the parent_dir fsync is best-effort with `except OSError: pass`, masking real failures.

For a hotfix whose ENTIRE PURPOSE is crash recovery, "tested via unit layer" is insufficient durability evidence. The smoke evidence file `smoke-2026-05-21.md` scenarios 2/3/5 are essentially restatements of unit-test results.

Action: Either (a) add a test seam (`HARNESS_TEST_ABORT_AFTER_PHASE=3` env hook) and re-run scenarios 2/3/5 as CLI subprocess tests, OR (b) explicitly document in CHANGELOG that v0.9.7 crash recovery is verified at the function level only, with full end-to-end SIGTERM evidence deferred to v0.9.8.

### C-2: `harness state repair` exit codes 1 / 2 are NEVER returned — contract documented but not implemented
`scripts/lib/state_cli.py:99-140` `run_repair` always `return 0` after calling `state_repair.repair(root)`. The function reports `recovery.quarantined` count via `report.warnings` (`state_repair.py:218-224`) but does NOT translate that into rc=1. There is no code path that returns 2 for catastrophic recovery failure either.

IMPL-PLAN REV-2 lines 37-41 explicit contract:
- `0` — recovery completed cleanly OR no work to do
- `1` — partial recovery with quarantine
- `2` — catastrophic

`docs/USER_MANUAL.md:1101-1107` documents the contract. `tests/test_install_recovery_pending_manifest.py` likely does NOT assert the CLI rc; it asserts on `RecoveryResult` directly.

Impact on 2am operator: smoke evidence shows `state repair` always returns 0, so a partial-recovery-with-quarantine scenario gives a green CLI but `.harness/conflicts/` accumulates silently. CI guards keyed off rc≠0 will not catch quarantines.

Fix: `state_cli.run_repair` must inspect the `RecoveryResult` (or have `state_repair.repair` propagate it) and:
- `len(recovery.quarantined) > 0` → return 1
- Catastrophic raise → return 2

This is a v0.9.5 NEW-3 (exit-code-0-on-all-errors) recurrence — exactly the regression the IMPL-PLAN was meant to prevent.

## MAJOR (must fix before tag)

### M-1: Upgrade pending sidecar STALE between batch and final write (Architect C-1 echo, ops impact)
See Architect C-1. Operationally: a SIGTERM/power-loss between Step B3 (`atomic_install_batch`) and B5 (`write_json(final)`) in `upgrade.py:1011-1044` leaves a sentinel-present + pending-present + final-absent state. Recovery finalizes from the STALE pending content (lacks post-sync `.roomodes` hash patch). `harness check` will then warn about `.roomodes` drift on next run — but the operator has no way to distinguish "I crashed mid-upgrade and recovered" from "someone tampered with `.roomodes`".

### M-2: Race between `recover_aborted_install` pending scan and concurrent in-progress install
`install_recovery.py:486-536`: scan-then-act, no lock. If `state repair` runs concurrently with `harness init` on the same target:
1. `init` writes pending sidecar (`.pending-<runid_A>`)
2. `init` enters `atomic_install_batch`
3. operator runs `state repair` in another shell
4. `_recover_pending_manifest` sees pending-A, no sentinel-A yet, journal+staging present → enters resume branch → calls `atomic_install_batch` on the SAME staging dir
5. two concurrent atomic_install_batch calls race on `os.replace` of staging files

Per threat model "repo-local internal-only" this is acceptable risk if documented. It is NOT documented in USER_MANUAL or CHANGELOG. The `STAGING_AGE_THRESHOLD_SECS=600` heuristic guards the LEGACY scan branch (`install_recovery.py:513`) but the PENDING scan branch (line 517) iterates `pending_manifests` unconditionally — no age gate on pending sidecars.

Action: gate pending-manifest recovery on `_is_stale(staging_dir)` for the pending's runid (cheap), OR document the no-concurrent-install assumption in USER_MANUAL B2.3a.

### M-3: T8 xfail hides a real fixture-determinism concern, not just an upgrade bug
`T8-triage.md:32-41` justifies xfail for `test_no_false_quarantine_non_force`: real fixture has 94 manifest files but 129 files on disk (35 extra lib modules). The 35 untracked files are quarantined "correctly". But this means an upgrade from a v0.9.4 target that has lib files NOT in v0.9.4's manifest (which is the realistic state — STALE-1 v0.9.4 bug, see MEMORY) will SURPRISE-QUARANTINE 35 lib files on first run. Existing v0.9.4 users with the v0.9.4 install bug will see 35 files moved to `.harness/conflicts/` and the operator will not know why.

The xfail defers the test, but the operational symptom is real. CHANGELOG `Deferred to v0.9.8` mentions "BUG-4 release-check rc=0" but does NOT mention the false-quarantine UX. Add an explicit warning in `upgrade.py` when quarantine count > threshold (e.g., > 5 files), or document in USER_MANUAL.

### M-4: `_cleanup_sentinel_tmp_orphans` is best-effort silent — no audit row
`install_recovery.py:199-225`: removes `.complete.tmp` orphans older than 60s; returns count; the caller (`recover_aborted_install` line 521) drops the return value on the floor. No audit row emitted. Operators investigating post-crash state have no record. Add an `install.recovery.tmp_orphans_cleaned` audit verb when count > 0.

### M-5: `_atomic_write_json_fsync` in install.py vs state.py drift
`scripts/lib/install.py:535-568` defines `_atomic_write_json_fsync` locally. `scripts/lib/state.py:79-84` uses `atomic_write_text` from `atomic_io`. Two atomic-write implementations now coexist. The install one does fsync(tmp_fd), os.replace, fsync(parent_dir_fd). `atomic_write_text` (`atomic_io.py:55-136`) also fsyncs tmp + parent + applies mode via fchmod. Disagreement points:
- install version uses `os.O_CREAT | os.O_TRUNC` directly (no NamedTemporaryFile)
- install version does NOT chmod 0o644 (atomic_write_text does via fchmod)
- install version does NOT verify same-filesystem st_dev before os.replace (atomic_write_text does at line 99-105)

For the pending sidecar specifically the third point matters: a cross-filesystem rename (e.g., target on a different mount than the temp dir's actual location) would degrade atomicity. Recommend reusing `atomic_write_text` directly or factoring a single shared helper.

## MINOR

- `KNOWN_FAILING_TESTS.md:5` says "Environment: Python 3.9.6 (system)" but IMPL-PLAN T9 line 380 mandates "Python 3.14 (homebrew)". Drift-gate seed environment mismatch — a different Python version will produce a different failing set. Reseed under the pinned env OR update IMPL-PLAN.
- `_finalize_pending_manifest` (`install_recovery.py:336-358`): reads `pending_content`, `os.replace(pending → final)`, then re-reads `final_path` for verify. Between the read and the replace, a concurrent writer could swap `pending_path` (repo-local threat model excludes this — fine to leave).
- Drift gate `HARNESS_KNOWN_FAILURES_ALLOW_STALE=1` documented but its usage in CI is undefined. Internal-only is fine.
- Sentinel `.complete` file is 0-byte (`atomic_io.py:286-290`). A future change that puts state INTO the sentinel will silently corrupt on the existing fsync(empty) pattern. Add a TODO or schema-version byte.

## Confirmations (correctly implemented)

- Sentinel write atomic discipline: `atomic_io.py:_write_completion_sentinel` does fsync(tmp_fd) → os.replace → fsync(parent_dir_fd). `.complete.tmp` cleanup on os.replace failure (`atomic_io.py:293-298`).
- `.aborted` precedence over sentinel in `_recover_pending_manifest` (`install_recovery.py:256-282`).
- `.complete.tmp` orphan cleanup with 60s threshold (`install_recovery.py:199-225`).
- Runid format `pid-iso-token_hex(3)` defeats pid reuse + provides naming nonce.
- Idempotent recovery: `_recover_pending_manifest` returns NOOP on subsequent runs after `.aborted` written (smoke evidence scenario 2).
- T5 stale-detection gates on journal-sibling presence + `_is_stale` (`check.py:599-648`) — does not false-positive on live install < 600s old.

## Recommended next step

Block tag pending C-1 (smoke evidence) and C-2 (exit code wiring). C-2 is a 5-line fix in `state_cli.run_repair`. C-1 requires either a test seam (1-2 hours) or an explicit CHANGELOG caveat. M-1 closes with Architect C-1.
