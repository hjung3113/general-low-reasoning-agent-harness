# Architect Final Diff Review — v0.9.7

Verdict: PASS-WITH-CONDITIONS

Scope: `git diff main..develop` (14 commits, 54 files); design contract: IMPL-PLAN REV-2.

## CRIT (block tag)

### C-1: Upgrade Pass B does NOT finalize via `os.replace(pending, final)` — phase order violated
`scripts/lib/upgrade.py:1042-1060` (Step B5): the upgrade path writes the final manifest with `write_json(final_path, installed)` (line 1044) and then unlinks the pending sidecar (line 1058). The IMPL-PLAN REV-2 phase order (lines 19-22) and the new-phase-order pseudocode pin "5. Sanity check: re-read sentinel exists, then `os.replace(pending, final)` (atomic finalize)". The install path honors this (`scripts/lib/install.py:374-375` does `os.replace(str(pending_path), str(final_path))`), but upgrade does not.

Why this matters (durability):
- After Step B3 the batch is committed and the completion sentinel is on disk.
- Between B3 and B5 the in-memory `installed` dict is MUTATED to patch `.roomodes` hashes (`upgrade.py:1031-1040`).
- So the on-disk pending sidecar content (written at B2 from `installed` BEFORE the mutation) NO LONGER matches the dict that B5 writes via `write_json`.
- A crash between B3 and B5 leaves: sentinel present, pending sidecar present with STALE content, final not written. `_recover_pending_manifest` (`install_recovery.py:285-294`) will see sentinel → call `_finalize_pending_manifest` → `os.replace(pending → final)` and stamp the STALE pending content (missing post-sync `.roomodes` hash patch) as final.

Fix options (pick one; either ok):
(a) Write pending sidecar AFTER the roomodes patch (move B2 between B4 and B5). Then keep `os.replace(pending → final)` discipline.
(b) Recompute `.roomodes` in staging (stage `.roomodes` post-sync into the same staging dir as `.roomodes.tmp`, then patch into the same atomic batch).

Test gap: `tests/test_upgrade_atomic_wire.py` does not exercise this divergence — `_atomic_write_json_fsync(pending) → mutate installed → write_json(final)` is not bit-equality asserted. IMPL-PLAN T4 test #4 ("Pass A's `plan.installed` payload bit-equal to Pass B's pending-sidecar content") is not satisfied as implemented.

### C-2: `_recover_pending_manifest` resume branch finalizes via STALE pending content
`scripts/lib/install_recovery.py:296-316`: when journal+staging are present (no sentinel, no .aborted), the resume path calls `atomic_install_batch(..., defer_cleanup=True)` then `_finalize_pending_manifest(pending_path, final_path, target)`. The pending sidecar was written by install/upgrade in Phase 3 / Step B2 from the *intended* `installed` payload. For upgrade, this misses the post-batch `.roomodes` hash patch (see C-1). Recovery therefore finalizes a manifest whose `files[".roomodes"]["installed_sha256"]` mismatches the actual file on disk. Subsequent `harness check` will spot the drift.

Confluent with C-1. Both close together by Fix-(a) above.

## MAJOR (must fix before tag)

### M-1: `state file_state(staged=)` not threaded into the upgrade `installed_sha256` / `current_sha256` chain inputs uniformly
`scripts/lib/state.py:243-352` `build_install_state_payload` correctly threads `staging_map` and for harness-owned policy uses `file_hash(staged_path)` for both `installed_sha256` and `current_sha256` (lines 299-309). However in the upgrade path (`upgrade.py:836-842`) `file_state(... staged=staged)` is called directly, but the surrounding `installed["files"][str(entry.path)] = file_state(...)` record returns `state["sha256"]` from `file_hash(staged)` (correct) — yet `installed_sha256` and `current_sha256` are NOT set by `file_state` itself (it only sets `sha256`, `source_sha256`). They are set later only when `build_install_state_payload` is the composer. Upgrade does NOT call `build_install_state_payload`; it composes `installed` in-place. Result: upgrade's payload may lack `installed_sha256` / `current_sha256` derived from staging hashes, and the `installed_files_chain_hash` stamping at `_stamp_installed_manifest_v2` uses whatever the v2 reconciler writes.

Action: explicit golden assertion (T4 test #4) that upgrade's pending sidecar `files[*].installed_sha256` equals `sha256(staged_file)` for every harness-owned entry. If the v2 reconciler is the actual stamper, document it; do not leave the dual-write ambiguous.

### M-2: `atomic_install_batch` resume path can silently overwrite when src+dst both exist with non-batch origin
`scripts/lib/atomic_io.py:451-473`: if `src.exists()` is True and `dst.exists()` is True, the code skips the early-return branch (which requires `not src.exists()`) and falls through to `os.replace(src, dst)`, overwriting `dst` with `src` unconditionally. Resume after a partial-but-unjournaled rename is fine for v0.9.7 because nothing else writes inside the staging tree, but the contract is not defended in code — a future change that drops a sidecar file under `.harness/.staging-<runid>/` would silently overwrite the install target. Test `tests/test_atomic_install_batch_defer_cleanup.py` does not exercise this.

Action: either reject the case (raise if `dst` exists and `rel` is not in `already_completed`) or add an explicit comment + test pinning the overwrite-is-intentional contract.

### M-3: Refactor side-effect: `write_install_state` is now a wrapper but legacy non-staging callers still hash destinations that may not exist
`scripts/lib/state.py:355-380`: thin wrapper around `build_install_state_payload`. In the install fast path, when `entry.policy == "harness-owned"` and `staged_path is None` and `destination.exists()` is False, `build_install_state_payload` falls through to `disk_sha = file_hash(source)` (line 305). That is a behavior CHANGE from pre-v0.9.7 `file_state` (which would have raised on a missing destination). Not necessarily wrong — but consult the audit and planning callers (audit module, dashboard, phase tooling) that may have relied on the legacy raise to detect a corrupted install. No test asserts the new fallback intent. Pin with a docstring + test.

## MINOR

- IMPL-PLAN T1 test 7 (crash-during-sentinel-write smoke) is implemented at `tests/test_atomic_install_batch_defer_cleanup.py` but the orphan `.complete.tmp` cleanup in `install_recovery._cleanup_sentinel_tmp_orphans` uses 60s threshold (`install_recovery.py:175`). A `state repair` run within 60s of the crash will leave the orphan. Acceptable; document in USER_MANUAL.
- `install.py:308` runid format `f"{os.getpid()}-{iso_compact}-{secrets.token_hex(3)}"`: no colons; safe on POSIX and Windows. Good.
- `install.py:359-364` `CrossFilesystemError` fallback copies directly from staging_map but does NOT write the pending sidecar / final manifest — relies on the `_atomic_write_json_fsync(pending_path, payload)` call already having written pending, then `os.replace(pending → final)` at line 375. OK, but the comment "Fallback: copy directly without staging dance" misleads; the pending-sidecar dance still occurs.

## Confirmations (correctly implemented)

- T1 sentinel write discipline: `atomic_io.py:276-307` does fsync(tmp_fd) → os.replace → fsync(parent_dir_fd) per IMPL-PLAN T1. `.complete.tmp` cleaned up on `os.replace` failure (line 295-298).
- T1.5 `file_state(staged=)` correctly gated on `entry.policy == "harness-owned"` (`state.py:193-196`); managed-append destination-hash semantics preserved.
- T2 `_recover_pending_manifest` decision matrix matches REV-2: `.aborted` checked BEFORE sentinel (`install_recovery.py:256-282`).
- T2 `.complete.tmp` orphan scan at `install_recovery.py:199-225` with 60s threshold per REV-2.
- T3 install phase order matches REV-2 phases 1-7 (`install.py:303-407`).
- T6 skip-upgrade guard with defensive missing-version branch (`upgrade.py:108-126`) + bilingual error.
- runid format defeats pid collision; filesystem-safe (no `:`, no `/`).

## Recommended next step

Block tag pending C-1 fix (upgrade pending sidecar consistency) and golden bit-equality assert for upgrade pending content vs final manifest. C-2 closes automatically once C-1 lands. M-1 is closely related — verify staged hashes flow into the chain-hash inputs.
