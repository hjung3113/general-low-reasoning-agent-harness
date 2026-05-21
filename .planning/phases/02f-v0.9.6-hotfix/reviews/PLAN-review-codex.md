# Codex Plan Review — v0.9.7

Verdict: BLOCK

## CRIT (block release)
- C-1: State-stamp recovery anchor is still wrong
  Evidence: Plan says the batch completes before `installed-manifest.json` is written last (`PLAN.md:64-68`). But `atomic_install_batch` removes the staging dir on full success (`scripts/lib/atomic_io.py:465-468`) and removes the journal (`scripts/lib/atomic_io.py:471-473`). If SIGTERM lands after those deletes and before `write_install_state(...)`, recovery sees no staging dir/journal. Current init stamps state only after copies (`scripts/lib/install.py:299-310`); current upgrade stamps metadata after writes (`scripts/lib/upgrade.py:755-820`).
  Fix: Make the two-phase state explicit: keep a durable sibling journal/commit marker until `installed-manifest.json` is atomically written, and make `install_recovery` finish/re-stamp when it sees "renames complete but manifest stale/missing". Add a kill-window test for post-batch/pre-manifest.

- C-2: Plan journal path does not match T14b recovery
  Evidence: Plan sample uses `journal_path = staging_dir / "journal.jsonl"` (`PLAN.md:127-138`). T14b recovery derives a sibling path: `staging_dir.parent / (staging_dir.name + ".journal.jsonl")` (`scripts/lib/install_recovery.py:117-119`) and then reads that path (`scripts/lib/install_recovery.py:170-172`). With the Plan path, recovery reads an empty/missing journal.
  Fix: Amend §7.1 to use one canonical journal path, preferably the existing T14b sibling convention, or update `install_recovery` and tests together.

- C-3: Fixture determinism claim is false once `.harness/` is included
  Evidence: Plan claims v0.9.4 `.harness/installed-manifest.json` is deterministic (`PLAN.md:71-76`). The builder currently runs live `harness init` without a fixed env (`scripts/build_v094_fixture.py:162-171`). v0.9.4 install state records current timestamps per file (`git show v0.9.4:scripts/lib/state.py:177-182`) and absolute source root (`git show v0.9.4:scripts/lib/state.py:263-269`). The builder normalizes tar metadata (`scripts/build_v094_fixture.py:119-135`) but not manifest content.
  Fix: Before removing `.harness` from `EXCLUDE_NAMES`, make v0.9.4 fixture generation content-deterministic: set `HARNESS_FIXED_NOW_ISO`, use stable worktree/target source strings or scrub allowed host fields, and assert two rebuilds in different temp roots produce identical sha256.

- C-4: REV-1 still accepts synthetic v0.9.4 state in the tests it says will be real-fixture tests
  Evidence: Plan success criterion says the T15 tests "drop synthetic seeds and use the real .harness state from the tarball" (`PLAN.md:41-42`, `PLAN.md:74-76`). Current clean fixture still calls `_seed_v094_manifest(extract_dir)` after extraction (`tests/test_upgrade_from_v094_clean.py:187-193`), and that helper writes stub hashes (`tests/test_upgrade_from_v094_clean.py:108-179`). Workaround tests still call `_seed_v094_manifest` and `_seed_v094_full_manifest` (`tests/test_upgrade_from_v094_with_workaround.py:276-299`), including tarball-derived synthetic manifest construction (`tests/test_upgrade_from_v094_with_workaround.py:179-248`).
  Fix: Amend T3 to delete all `_seed_v094*` helpers from these tests and fail if extracted fixtures lack `.harness/installed-manifest.json`.

- C-5: KNOWN_FAILING_TESTS drift mitigation is identity-blind
  Evidence: Plan mitigation is count-only: "pytest baseline maintained <=76 failures" and "`KNOWN_FAILING_TESTS.md` count matches actual" (`PLAN.md:44-45`, `PLAN.md:97`, `PLAN.md:213-214`). Same count can hide one known failure passing while a new unrelated test fails.
  Fix: Use structured test node IDs and compare the actual failing node-id set to the known set. Gate on `new_failures == empty`; separately report fixed known failures.

## MAJOR (must address before release)
- M-1: Atomic wire-in completeness is under-scoped for upgrade
  Evidence: Plan §3.1 scopes files to `install.py` and `atomic_io.py` only (`PLAN.md:60-63`) but success criterion includes upgrade "where applicable" (`PLAN.md:39`) and §7.1 says `upgrade.py:755-758 similar` (`PLAN.md:146`). Current upgrade still calls `write_copy(source, destination)` for harness-owned writes (`scripts/lib/upgrade.py:755-758`) and conflict copies (`scripts/lib/upgrade.py:738-740`, `scripts/lib/upgrade.py:791-794`).
  Fix: Put `scripts/lib/upgrade.py` explicitly in scope for harness-owned destination writes. Decide whether conflict sidecars stay direct-copy; document if out of scope.

- M-2: `harness check` staging detection is absent and must be precise
  Evidence: Plan makes check warning a success item (`PLAN.md:68-69`, `PLAN.md:95`). Current `check_installed_target` has no `.staging-*` scan in its installed-target path (`scripts/lib/check.py:599-734`); recovery is only wired through `state repair` (`scripts/lib/state_repair.py:212-218`).
  Fix: Add a single-target scan of `target/.harness/.staging-*` with journal/sentinel recognition. Warn only for directories matching the harness journal convention to avoid unrelated `.staging-*` false positives.

- M-3: Q1 default-on fallback can silently reintroduce torn writes
  Evidence: Plan risk row says cross-filesystem failures should fall back to `shutil.copyfile + log warning` (`PLAN.md:91-92`). That is exactly the old non-atomic behavior on the path this hotfix is meant to harden.
  Fix: Default-on is acceptable only if staging is under `$TARGET/.harness` and same-device is enforced before copying. If `CrossFilesystemError` occurs, fail with an actionable message unless the user explicitly opts into non-atomic fallback.

- M-4: Skip-upgrade UX is cheap enough to include now
  Evidence: Plan defers v0.9.4 skip-upgrade detection to later and documents workaround only (`PLAN.md:96`, `PLAN.md:101-104`). `upgrade.py` already has the prior installed state in hand (`scripts/lib/upgrade.py:667`) and writes the new version later (`scripts/lib/upgrade.py:806`); it also already carries v0.9.4-specific remediation logic (`scripts/lib/upgrade.py:453-455`).
  Fix: Add a small guard/hint when prior version is `0.9.4`/`v0.9.4` and target release is v0.9.7: print the intermediate v0.9.5 procedure or refuse with that fix text if the skip path is known unsafe.

- M-5: CHANGELOG honesty needs exact release wording
  Evidence: Plan only says honest partial coverage (`PLAN.md:91`) and later still says `CHANGELOG v0.9.6` despite target now being v0.9.7 (`PLAN.md:206`).
  Fix: Use this one-liner or stricter: `v0.9.7 hardens harness-owned init/upgrade file replacement with resumable per-file atomic staging; managed-append and composed write_text_file updates remain in-place and are deferred.` Rename all v0.9.6 release rows to v0.9.7.

## MINOR (nice-to-have)
- m-1: Scope-out integrity is defensible only with wording. `write_text_file` documents why SKILL-pack content writes are excluded (`scripts/lib/install.py:450-465`), but managed-append uses in-place composed text in upgrade (`scripts/lib/upgrade.py:704-719`, `scripts/lib/upgrade.py:771-783`). Plan should say these paths are user-content conflict-managed, not crash-safe, and v0.9.7 does not claim otherwise.
- m-2: Plan §7.1 stages with `shutil.copyfile(source, staged)` (`PLAN.md:133-136`). That direct copy is fine only because the destination is staging, not final target. Say that explicitly so future grep gates do not treat it as a regression.
- m-3: Recovery latency needs a number. `install_recovery._is_stale` is mtime-threshold based when no `.aborted` sentinel exists (`scripts/lib/install_recovery.py:105-114`); Plan should state the threshold or add journal-present detection.

## CONFIRMATIONS (REV-1 closures that actually hold)
- Managed-append and `write_text_file` are correctly scoped out for v0.9.7 only if CHANGELOG says partial coverage; current helper comments support that limited claim (`scripts/lib/install.py:450-465`).
- T14a is a real per-file atomic helper, not a fake batch transaction. Its docstring correctly states "per-file atomic, NOT whole-batch atomic" (`scripts/lib/atomic_io.py:283-289`).
- `state repair` does invoke `install_recovery.recover_aborted_install` before planning-state repair (`scripts/lib/state_repair.py:212-218`).
- Non-force workaround tests do exercise the quarantine branch at `upgrade.py:732` (`tests/test_upgrade_from_v094_with_workaround.py:444-489`), but they still depend on synthetic manifest seeding and therefore do not satisfy the real-fixture requirement.

## Recommended Plan amendments
- Replace §7.1 with a two-phase protocol: stage harness-owned files, rename via `atomic_install_batch`, persist a durable completion marker, atomically write `installed-manifest.json`, then remove journal/staging markers.
- Align journal path between Plan, `atomic_install_batch`, and `install_recovery`; add a contract test for the exact path.
- Add fixture determinism gates: fixed env, scrubbed host-specific manifest fields, and two-build sha256 equality.
- Require T15 tests to consume `.harness/installed-manifest.json` from fixtures and delete synthetic seed helpers.
- Replace count-only known-failure gating with node-id set comparison.
- Add explicit v0.9.4 skip-upgrade hint in `upgrade.py` now; this is small and the detection inputs already exist.
