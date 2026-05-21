# v0.9.7 Implementation Summary

Branch: develop
Final HEAD: ee1bf2c

| Task | Commit | Tests Passing |
|---|---|---|
| T1 — atomic_install_batch defer_cleanup + completion sentinel | 5d4c39a | 7 new (test_atomic_install_batch_defer_cleanup.py) |
| T1.5 — file_state staged-hash param + build_install_state_payload | bbd390d | 6 new (test_state_staged_hash.py) |
| T2 — _recover_pending_manifest + sentinel + nonce + .tmp cleanup | 6a5c85c | 9 new (test_install_recovery_pending_manifest.py) |
| T3 — install.py init wire-in with atomic staging phase order | 82f6cef | 7 new (test_install_atomic_wire.py) |
| T4+T6 — two-pass atomic staging + skip-upgrade guard | 869d322 | 5+5 new (test_upgrade_atomic_wire.py, test_skip_upgrade_guard.py) |
| T5 — stale-staging-dir detection with age-gate + bilingual warning | 5c19385 | 6 new (test_check_staging_detection.py) |
| T7 — builder normalization, determinism self-check, fixture regen | 7ade3d1 | 5 new (test_fixture_determinism.py) |
| T8 — real-fixture upgrade tests + bug triage gate | f30f1db | 7+1xfail (test_upgrade_from_v094_clean.py, test_upgrade_from_v094_with_workaround.py) |
| T9 — KNOWN_FAILING_TESTS.md + drift gate + seed script | d9b9e25 | 4 new (test_known_failures_drift.py) |
| T10 — USER_MANUAL recovery section + manual.html | 9718edb | docs-only |
| T11 — CHANGELOG v0.9.7 + version-ref bumps | 665e0bf | docs-only; acceptance gate: `git grep -nE 'v?0\.9\.6' -- ':!CHANGELOG.md'` clean |
| T11 fixup — KNOWN_FAILING_TESTS.md reseed (36 tests, scripts/ removed) | ee1bf2c | drift gate PASS |
| T12 — smoke evidence | smoke-2026-05-21.md | 8/8 scenarios GREEN |

## Deviations from IMPL-PLAN

See `impl-deviations.md` for full list. Key items:
- T8-B2: `test_no_false_quarantine_non_force` xfail(strict=True) — real fixture lacks 35 workaround lib modules; deferred to v0.9.8
- KNOWN_FAILING_TESTS.md initial seed had 89 entries including scripts/ tests; corrected to 36 (tests/ scope only) after full run
- Scenarios 2/3/5 of T12 smoke covered via unit test layer (test_install_recovery_pending_manifest.py) — direct SIGTERM simulation not feasible in harness.py init path without test-seam injection

## Final test counts

```
36 failed (pre-existing, all in KNOWN_FAILING_TESTS.md)
1507 passed
2 skipped
1 xfailed (T8-B2)
```
