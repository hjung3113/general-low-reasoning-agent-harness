# Ops Hawk ImplPlan Review — v0.9.7

Verdict: BLOCK

## CRIT (block)

### C-1: Concurrent `init` / `state repair` on same target — pid collision recovery
PLAN §7.1 names sidecars by `os.getpid()`: `installed-manifest.json.pending-<pid>`, `.staging-<pid>/`, `.staging-<pid>.journal.jsonl`, `.staging-<pid>.complete`. PIDs wrap (Linux default `kernel.pid_max=4194304`, can be much lower on macOS — `99999`). A long-uninstalled target carrying an orphan `pending-12345` will collide with any future process that happens to get pid 12345. Recovery (`_recover_pending_manifest` in §7.2) cannot distinguish "fresh sidecar from this process" vs "stale sidecar from killed earlier run" — both have the same name. Result: the live install would overwrite/collide with recovery operations. IMPL-PLAN T3 silently inherits this. Mitigation: include monotonic timestamp suffix (`pending-<pid>-<iso>`) AND have caller check for self-owned sidecar via lockfile or in-process registry.

### C-2: `os.replace(pending, final)` over existing `installed-manifest.json` clobbers v0.9.6→v0.9.7 upgrade record
On `harness upgrade`, the existing `installed-manifest.json` is loaded, mutated (`installed["version"] = harness_version` etc — `upgrade.py:806-808`), and re-written. PLAN §7.1 phase-3 `os.replace(pending_manifest_path, final_manifest_path)` blindly overwrites. If a SIGTERM lands after `os.replace` but before journal/staging cleanup, the next `state repair` sees: no pending sidecar (gone, became final), residual journal + staging + sentinel. `_recover_pending_manifest` does not run (no pending file). `_recover_one` legacy path runs against the residual staging+journal — finds sentinel absent for that codepath (because sentinel is only written by NEW defer_cleanup callers), attempts resume of an already-completed batch. Files in staging are gone (already renamed pre-finalize). `atomic_install_batch` walks empty staging, returns success, cleans up. OK in this case. **But**: if any retry of `os.replace` reads-then-writes (e.g., race in finalize), the install record can be silently downgraded. IMPL-PLAN does not include a "post-finalize sanity check" (verify manifest version matches pending content) before deleting journal+staging.

### C-3: `.staging-<pid>.complete.tmp` orphans on crash, not cleaned by recovery
Sentinel write path: `sentinel_tmp.write_bytes(b"")` → `os.replace(sentinel_tmp, sentinel_path)`. SIGKILL between these two calls leaves `.staging-<pid>.complete.tmp` permanently. `_recover_pending_manifest` looks only at `.complete`. The .tmp orphan never gets reaped. After many install cycles, `.harness/` accumulates these. IMPL-PLAN T1 does not list a cleanup pass for `.complete.tmp` files older than threshold.

### C-4: Sentinel write happens INSIDE `atomic_install_batch`, but journal cleanup conditional logic creates `.aborted`+sentinel both-present window
Re-read `scripts/lib/atomic_io.py:425-455` flow: on per-file rename failure inside the loop, `.aborted` is written into `staging_dir/.aborted` AND `result.aborted=True` is returned BEFORE the new defer_cleanup sentinel block. Good. **But** the new code per PLAN §7.1:
```
if not result.aborted:
    if defer_cleanup:
        write sentinel
    else:
        cleanup
```
Aborted-path bypass leaves `.aborted` present and **no sentinel**. `_recover_pending_manifest` decision matrix handles this (`.aborted` → explicit rollback). Fine. **But** what if `.aborted` is written and then a *different* concurrent recovery resumes the batch, completing it, writing sentinel? Sentinel and `.aborted` would coexist. `_recover_pending_manifest`'s `if sentinel_path.exists()` check fires FIRST → finalize → but `.aborted` lingers. Future recoveries on the same staging dir (now empty post-finalize cleanup) become no-ops. OK functionally, but the `.aborted` was an explicit "this aborted, do not finalize" signal that's now silently overruled by a fresh sentinel. Concurrency-disallowed-by-threat-model gets us out of this, but spec must say so.

### C-5: `state repair` resume path inside `_recover_pending_manifest` is not idempotent under partial failure
PLAN §7.2 resume branch:
```python
batch_result = atomic_install_batch(staging_dir, target, journal_path, defer_cleanup=True)
...
if not batch_result.aborted and sentinel_path.exists():
    return _finalize()
return _explicit_rollback()
```
Suppose resume completes 3 of 5 remaining files, then fails. `result.aborted=True`, sentinel not written. We fall into `_explicit_rollback()`. Rollback iterates `_journal_completed(records)` and restores from backups OR quarantines. But the *3 just-completed-in-this-resume* files have backups from the ORIGINAL install (pre-aborted-batch). Restoring them undoes the original install too, leaving 3 files in pre-install state and 2 files in original-installed state. The manifest pending sidecar describes "all 5 installed" → deleted by rollback. End state: torn. Architecturally consistent ("rolled back to pre-install"), but if the user runs `state repair` twice (transient OSError on first resume → re-run), the second resume sees fewer files in staging and the journal mix gets weirder. Add explicit "do not resume on a journal that already shows post-original-batch entries unless the staging dir matches the pending sidecar's file-list" check.

## MAJOR (must fix before impl)

### M-1: `harness check` warning has no rate-limit and no dedupe
T5 scans `.harness/.staging-*` every `check` invocation. If user routinely runs `check` from CI on multiple machines or in tight loop, warning floods stderr. Acceptable for v0.9.7, but spec should say "warning emitted at most once per `check` invocation regardless of staging-dir count" — IMPL-PLAN T5 test #4 says "one warning per dir" which is the OPPOSITE. Pick one.

### M-2: T4 SIGTERM mid-upgrade test does not specify state of in-place v0.9.6 → v0.9.7 manifest
"SIGTERM mid-upgrade: `state repair` recovers" — recovers to v0.9.6 (rollback) or v0.9.7 (finalize)? Tests must assert exact recovered version. IMPL-PLAN does not specify.

### M-3: Recovery on Linux with EXT4 + delayed allocation — sentinel could exist with zero blocks
`os.replace(sentinel_tmp, sentinel_path)` on ext4 with `data=writeback` or `data=ordered` (default) doesn't guarantee the data is durable post-crash. Sentinel could appear (rename committed) while content is missing — but content is `b""` so zero-byte file = "complete". This is fine because the check is existence, not content. **However** parent dir must be fsynced too, else the rename itself isn't durable. IMPL-PLAN T1 does not require parent-dir fsync. Add it or accept "best-effort sentinel; final atomic guarantee is the `os.replace(pending, final)`".

### M-4: No timeout on `_recover_pending_manifest` resume call
If staging dir has 10000 files and one rename hangs on NFS (despite same-FS check — bind mounts can cross), recovery hangs forever. PLAN says no Windows / no NFS, but operator running `state repair` interactively expects bounded latency. Document maximum staging size or add file-count guard.

### M-5: `_recover_pending_manifest` runs BEFORE legacy `_find_staging_dirs` scan — order matters
"Existing T14b in-batch recovery (staging present without pending sidecar — legacy callers) unchanged." If a staging dir has BOTH a pending sidecar AND happens to be picked up by both scans (pending-loop touches `_recover_pending_manifest`; legacy loop touches `_recover_one`), we get double-processing. IMPL-PLAN T2 ("before existing `.staging-*` scan, scan `.pending-*`") implies sequential — verify that pending-loop deletes journal/staging on success so legacy loop sees nothing. Spec it.

### M-6: T9 drift gate `current = parse cached junit.xml` — junit.xml can be stale
If junit cache is hours old and code has changed since, gate is checking against the wrong set. IMPL-PLAN T9: "If missing → skip with 'run pytest --junitxml=...' first". But if PRESENT and stale → false-green. Add mtime check (cache must be newer than HEAD modification time of `scripts/` or `tests/`).

### M-7: T7 fixture builder runs `harness init` via subprocess that *may exit non-zero* (`run_v094_init` line 173-180 warns but continues). Non-deterministic install state could be tarballed with no error.
Existing builder swallows init failure. T7 normalization runs AFTER. If init exit non-zero AND `installed-manifest.json` was never written, `_normalize_v094_install_state` raises `FixtureBuildError` → good. But if init partially completed (manifest written, some files missing), fixture is silently broken. Add explicit file-count assertion in `_normalize_v094_install_state` (expected vs actual).

## MINOR

### m-1: T10 USER_MANUAL update doesn't include `harness state repair --help` output
Recovery section should pin the exact `--help` text to ensure docs and CLI stay in sync.

### m-2: T11 CHANGELOG missing "what's new for users" wording
"`harness state repair`" is mentioned in CHANGELOG hardening line but USER_MANUAL Korean subsection is new and should be flagged.

### m-3: No smoke for "user runs `state repair` on a v0.9.6-only install"
Pure v0.9.6 install has no pending sidecars (legacy installer). Recovery should be a no-op. Add test.

### m-4: No SIGSTOP smoke
PLAN mentions SIGTERM extensively; SIGSTOP+SIGKILL combo (kernel OOM killer, etc.) deserves at least one acknowledgment. Probably out of scope but flag it.

## Recommended amendments

1. **Sidecar naming**: `pending-<pid>-<iso>` (or `-<rand>`) to defeat pid reuse. Update §7.1 + T1 + T2 + T3.
2. **Cleanup `.complete.tmp` orphans**: add to `_recover_pending_manifest` scan.
3. **fsync parent dir** around sentinel `os.replace` AND `pending` `os.replace`. Spec in T1 + T3.
4. **Post-finalize sanity check**: after `os.replace(pending, final)`, re-read final, assert version matches expected, before cleanup.
5. **Rate-limit `check` warning**: at most one warning row regardless of staging-dir count; or test #4 fixed to "single warning with N reported".
6. **Explicit upgrade-recovery test matrix**: SIGTERM at each phase boundary asserts exact recovered manifest version (v0.9.6 OR v0.9.7, not "either").
7. **Resume idempotency guard**: in `_recover_pending_manifest` resume branch, verify journal records are consistent with pending sidecar file-list before resuming.
8. **junit cache freshness gate** in T9.
9. **Fixture init exit-code gate**: T7 must fail fixture build if `harness init` returns non-zero (do not "warn but continue" — that's how non-determinism enters).
10. **No-op recovery smoke**: clean v0.9.7 install, run `state repair`, assert zero audit rows beyond `recovery.noop`.
