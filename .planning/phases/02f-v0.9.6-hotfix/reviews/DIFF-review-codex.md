# Codex Final Diff Review — v0.9.7

Verdict: BLOCK

## CRIT (block tag)

- `harness state repair` does not implement the pinned 0/1/2 contract. IMPL-PLAN says `1` = quarantine and `2` = catastrophic (`.planning/phases/02f-v0.9.6-hotfix/plans/IMPL-PLAN.md:37`), but `run_repair` returns `EXIT_UNPARSEABLE_JSON` for `RepairRefusedError` (`scripts/lib/state_cli.py:110`) and returns `0` after warnings (`scripts/lib/state_cli.py:134`, `scripts/lib/state_cli.py:140`). Quarantine is only appended as a warning (`scripts/lib/state_repair.py:218`) and never maps to rc=1.

- KNOWN_FAILING_TESTS stale-cache gate does not fail by default. The test doc says stale cache skips unless strict (`tests/test_known_failures_drift.py:11`), and implementation calls `pytest.skip(msg)` unless `HARNESS_KNOWN_FAILURES_STRICT=1` (`tests/test_known_failures_drift.py:225`, `tests/test_known_failures_drift.py:231`). Requested contract was rc=1 on stale cache unless `HARNESS_KNOWN_FAILURES_ALLOW_STALE=1`.

## MAJOR (fix before tag)

- Upgrade Pass A is not write-free. It mutates managed-append targets before pending sidecar / batch (`scripts/lib/upgrade.py:795`) and deletes retired files before Pass B (`scripts/lib/upgrade.py:875`). This violates IMPL-PLAN Pass A "no target writes" (`.planning/phases/02f-v0.9.6-hotfix/plans/IMPL-PLAN.md:34`).

- Upgrade finalization does not use pending sidecar as the final manifest source. Pass B writes pending (`scripts/lib/upgrade.py:1008`) but later writes `installed-manifest.json` with `write_json(final_path, installed)` (`scripts/lib/upgrade.py:1042`) and only unlinks pending afterward (`scripts/lib/upgrade.py:1056`). This diverges from install's `os.replace(pending_path, final_path)` path (`scripts/lib/install.py:375`) and the plan's pending -> finalize contract.

- Version refs still point users at v0.9.6 outside clear historical context. Generated manual release commands still tag/push/verify `v0.9.6` (`docs/site/manual.html:1004`, `docs/site/manual.html:1009`), and use-cases intro says `v0.9.6` as the current principle (`docs/use-cases/README.md:3`).

- Test coverage labels SIGTERM/crash scenarios but does not actually terminate a process. Recovery tests hand-create pending/staging/sentinel files (`tests/test_install_atomic_wire.py:178`, `tests/test_install_atomic_wire.py:208`, `tests/test_upgrade_atomic_wire.py:173`) and call `recover_aborted_install` in-process (`tests/test_install_atomic_wire.py:187`, `tests/test_upgrade_atomic_wire.py:188`). Useful unit coverage, not crash-window proof.

## MINOR

- CHANGELOG claims `harness state repair` rc 0/1/2 (`CHANGELOG.md:27`) and "CI gate" for known failures (`CHANGELOG.md:33`), but both are overstated until the CRIT items are fixed.

## Confirmed correct implementations

- Sentinel durability is present: tmp fd fsync before replace (`scripts/lib/atomic_io.py:286`), then parent directory fsync after replace (`scripts/lib/atomic_io.py:300`).

- Runid format is collision-resistant for install/upgrade sidecars: pid + compact UTC iso + `token_hex(3)` (`scripts/lib/install.py:307`, `scripts/lib/install.py:308`, `scripts/lib/upgrade.py:762`, `scripts/lib/upgrade.py:763`).

- `.aborted` precedence is correct: `_recover_pending_manifest` checks `.aborted` before sentinel (`scripts/lib/install_recovery.py:256`, `scripts/lib/install_recovery.py:284`).

- `file_state(staged=...)` preserves legacy default and hashes staged harness-owned files when passed (`scripts/lib/state.py:168`, `scripts/lib/state.py:193`); `build_install_state_payload` passes staged paths through (`scripts/lib/state.py:285`).

- Install phase order matches REV-2 for harness-owned files: stage (`scripts/lib/install.py:314`), compose payload (`scripts/lib/install.py:331`), pending sidecar (`scripts/lib/install.py:342`), batch (`scripts/lib/install.py:345`), finalize (`scripts/lib/install.py:372`), verify (`scripts/lib/install.py:377`), cleanup (`scripts/lib/install.py:388`).

- CHANGELOG is honest about atomic scope: harness-owned only, managed-append/write_text_file deferred (`CHANGELOG.md:19`, `CHANGELOG.md:23`, `CHANGELOG.md:39`).

## Recommended next step

Fix rc mapping + tests for `state repair`, make stale known-failures cache fail by default, move upgrade managed-append/retirement writes out of Pass A or document the narrower guarantee, finalize upgrade from pending with `os.replace`, regenerate docs/version refs, then rerun focused recovery + drift-gate tests.
