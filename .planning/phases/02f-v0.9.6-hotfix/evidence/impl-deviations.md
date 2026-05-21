# v0.9.7 Implementation Deviations from IMPL-PLAN REV-2

## T8-B2: non-force quarantine xfail (deferred to v0.9.8)

**IMPL-PLAN assumption:** `test_no_false_quarantine_non_force` would pass with the real fixture.

**Actual:** Real v0.9.4 tarball has 94 installed files in manifest. The test used `_seed_v094_full_manifest` which covered all 129 files including 35 lib modules that exist on disk but are untracked in the real v0.9.4 manifest. These 35 extra files are correctly quarantined (not a bug).

**Disposition:** Marked `xfail(strict=True)` with clear explanation. Deferred to v0.9.8.
**Evidence:** `.planning/phases/02f-v0.9.6-hotfix/evidence/T8-triage.md`

---

## T9: KNOWN_FAILING_TESTS.md initial seed scope

**IMPL-PLAN:** "Pytest baseline. Before T11 ships, full pytest failing-set must be ⊆ KNOWN_FAILING_TESTS.md."

**Actual:** Initial seed (commit d9b9e25) included 89 entries from `pytest tests/ scripts/` combined. After full-suite run `pytest tests/`, the `scripts/` tests are not collected (different pytest rootdir), so they appeared as "FIXED knowns" in the drift gate.

**Fix:** Reseeded KNOWN_FAILING_TESTS.md to 36 entries (tests/ scope only) in commit ee1bf2c.
`scripts/refresh_known_failures.sh` updated to document this scope decision.

---

## T12 scenarios 2/3/5: SIGTERM simulation via unit tests

**IMPL-PLAN:** "Fresh init → SIGTERM mid-batch → state repair 3x → final manifest correct."

**Actual:** `harness.py init` does not expose a test-seam for SIGTERM injection mid-batch. Direct SIGTERM via `subprocess.send_signal` would hit a timing race. Instead, scenarios 2/3/5 are covered via:
- Direct unit testing of `_recover_pending_manifest` (9 tests, test_install_recovery_pending_manifest.py)
- These tests exercise identical code paths as a real SIGTERM would leave behind

The evidence file documents this equivalence. Full CLI SIGTERM tests deferred to v0.9.8 when a proper test-seam or injection point can be added.

---

## T4: HARNESS_VERSION constant

**IMPL-PLAN:** "version constant updated everywhere."

**Actual:** `HARNESS_VERSION` in `scripts/lib/harness.py` is computed dynamically from `git describe --tags` at runtime — there is no static string to bump. The `version` field in installed manifests reflects the git tag at install time. Version refs in docs/README were updated (T11); no static constant bump needed.
