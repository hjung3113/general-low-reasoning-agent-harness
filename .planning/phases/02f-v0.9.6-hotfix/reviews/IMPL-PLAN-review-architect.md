# Architect ImplPlan Review — v0.9.7

Verdict: BLOCK

## CRIT (block)

### C-1: Pending-manifest content cannot be composed BEFORE batch — `file_state` reads destination sha256
`scripts/lib/state.py:181-189` and `:255-267` compute per-entry `sha256`, `installed_sha256`, `current_sha256` via `file_hash(destination)`. The destination file only exists AFTER `atomic_install_batch` renames staging→target. PLAN §7.1 / IMPL-PLAN T3 step 1 ("compose payload, write to `installed-manifest.json.pending-<pid>` ... durably stage BEFORE batch") is **physically impossible without changing `file_state`'s hashing source from destination to staging**. IMPL-PLAN T3 says "split `write_install_state` into `build_install_state_payload`" but says nothing about rewriting `file_state` to hash the staging path instead. Without this, either:
  (a) payload is written but with wrong/empty hashes → manifest is corrupt on finalize; or
  (b) payload composition is moved AFTER batch → loses the "durable before any target write" property and the entire pending-sidecar contract collapses to "fancy temp file".
Fix: T1 (or new T1.5) must redefine `file_state(source=, staged=)` to hash the staged path (same bytes that `os.replace` will land in destination) for harness-owned policy; managed-append hashing is unaffected. ALSO note `.roomodes` post-processing (`sync_roomodes_profile_modes` at `install.py:309`, called AFTER write loop) intentionally diverges destination from source — PLAN §7.1 puts the finalize `os.replace` BEFORE `sync_roomodes_profile_modes` in one snippet and after in another. Ordering must be pinned, and `.roomodes` hash recomputation strategy must be specified.

### C-2: `atomic_install_batch` signature mismatch — `pairs` parameter does not exist
IMPL-PLAN T3 calls `atomic_install_batch(staging_dir=..., target=..., journal_path=..., pairs=batch_pairs, defer_cleanup=True)` and PLAN §7.1 likewise passes `pairs=`. Current implementation `scripts/lib/atomic_io.py:276-282` only accepts `staging_dir, target, journal_path, *, sort_key`. The function walks the entire staging tree (`os.walk(str(staging_dir))` at `:362`) and renames every file found — there is NO `pairs` filter. IMPL-PLAN T1 ("Changes") lists only `defer_cleanup` addition and does NOT mention adding `pairs`. Either the install loop must stage everything (no pairs filter — fine, since staging dir IS the filter) and T1/T3 must drop the `pairs=` argument, OR T1 must explicitly add `pairs` semantics. Pick one. As written, T3's code does not type-check.

### C-3: Upgrade-path `installed["files"][...] = file_state(...)` interleaving incompatible with pending-sidecar
`scripts/lib/upgrade.py:723-729` and `:758-763` update the in-memory `installed` dict mid-loop (driven by `write_copy` decisions, conflict detection, managed-append retirement). The final `installed` dict is the manifest payload; it cannot be composed before the loop because conflict-counts, planned_writes, planned_removals, and per-file `file_state` records are computed during iteration. IMPL-PLAN T4 says "Apply T3 pattern to upgrade's harness-owned write loop only" but does not address that upgrade's payload is loop-derived. Result: pending sidecar at upgrade time would be incomplete or stale. Architectural fix required: either (a) two-pass upgrade — first pass plans, second pass stages + finalizes; or (b) finalize-time recompute (sidecar contains pre-batch *intent*, finalize swaps in post-batch *actual*). PLAN §7.1 picks neither.

### C-4: Sentinel write itself is not atomic vs. SIGTERM between fsync and rename
PLAN §7.1 / IMPL-PLAN T1 write sentinel as `sentinel_tmp.write_bytes(b"")` + `os.replace(tmp, sentinel)`. SIGTERM between `write_bytes` and `os.replace` leaves `.staging-<pid>.complete.tmp` orphan. Recovery scan in `_recover_pending_manifest` looks only for `.staging-<pid>.complete` — orphan `.tmp` is invisible and pollutes `.harness/`. Minor cleanup gap, but more critically: write_bytes is buffered + flushed by file-object close; no explicit `os.fsync` is specified. On power loss before fsync of the tmp + parent dir, the rename can be journaled with a zero-length file that doesn't survive crash. Spec must mandate fsync of (tmp_fd, parent_dir_fd) before the os.replace, matching `atomic_io._atomic_write_json` discipline. IMPL-PLAN T1 test #3 ("sentinel is zero-byte file") does not exercise crash durability.

## MAJOR (must fix before impl)

### M-1: `_recover_pending_manifest` resume can succeed-but-not-finalize on partial journal
PLAN §7.2 resume branch: `atomic_install_batch(staging_dir, target, journal_path, defer_cleanup=True)`. Current implementation removes journal on full success (`atomic_io.py:472-475`). The proposed `defer_cleanup=True` branch keeps it. Fine. But: if staging dir is half-empty (some files already renamed in the original aborted run), `os.walk(staging_dir)` yields only the *remaining* files. The journal carries entries for the originally-renamed files. Resume completes the remaining renames → sentinel written. So far so good. **Failure mode**: if a remaining staging file's destination already exists (because a prior partial recovery wrote it, then crashed before journal append), the resume tries `os.replace` and succeeds (overwriting) but lacks idempotency assurance for files that were renamed but never journaled. Current code at `atomic_io.py:407-420` handles src-missing+dst-exists by journaling — but the inverse (src-exists+dst-exists from non-this-batch source) silently overwrites. IMPL-PLAN T1 tests do not cover this.

### M-2: `harness check` staging detection does not check stale-age threshold
IMPL-PLAN T5 helper `_scan_staging_dirs` returns any `.staging-*` with sibling journal. `install_recovery._is_stale` (line 105-114) gates on `STAGING_AGE_THRESHOLD_SECS=600` OR `.aborted` marker. A `check` run that races an in-progress `init` (same target, concurrent or pipelined) would warn falsely. PLAN §3.1 docs O(N) latency but says nothing about racing live installs. Add age threshold or "no live install marker" check to the warning gate.

### M-3: T7 `manifest_sha256` recompute hand-wave
PLAN §3.2: "Recompute `manifest_sha256` IF it depends on normalized fields (check v0.9.4 `manifest_sha256` source — ...) Determinism test will catch a mismatch either way." Architect rejects "determinism test will catch": the fixture builder must KNOW whether to recompute, not rely on test failure to detect drift. Verify v0.9.4's `manifest_sha256` semantics BEFORE T7 lands and bake the decision into the normalizer. Otherwise T7 ships either a stale hash or a non-deterministic build.

### M-4: T9 KNOWN_FAILING_TESTS.md seeding is environmental
IMPL-PLAN T9: "Run full pytest with --junitxml=... once locally; populate KNOWN_FAILING_TESTS.md from result." The seed file inherits whatever local-only failures the operator's machine produces (missing rg, missing git, locale, etc.). Drift gate then enforces this snapshot on CI / other devs. Architect: spec must say "run in clean container OR per-test allowlist of skip-reasons" — otherwise the gate codifies one human's broken env as the team baseline.

### M-5: `defer_cleanup` ABI break for `_recover_one` resume path
`install_recovery._recover_one` at line 218 already calls `atomic_install_batch(staging_dir, target, journal_path)` (no `defer_cleanup`). PLAN §7.2 only adds the *new* `_recover_pending_manifest` calling site. Existing `_recover_one` keeps the legacy default-False behavior → on resume success it auto-cleans staging + journal. Fine — but the journal-cleanup-then-no-sentinel sequence means recovery for legacy callers does not produce a sentinel. PLAN spec is consistent (only new pending-sidecar flow writes sentinel), but IMPL-PLAN must document that `_recover_one` is intentionally not migrated and continues to be the path for "staging without pending sidecar" (legacy upgrade or in-progress callers that haven't adopted phase 1 yet).

## MINOR

### m-1: T11 version constant location is unspecified
"`scripts/lib/version.py` (or wherever version constant lives) — bump to `0.9.7`". An impl-plan should already know. Suggests author hasn't run `git grep "0\.9\.6"` to enumerate sites. Will produce missed bumps (cf. v0.9.6 hotfix was *itself* a docs version-ref bump).

### m-2: T10 manual.html regen has no diff-stability guarantee
Manual.html generator may emit non-deterministic ordering (timestamps, etc). If yes, repeat regens churn the diff. Verify before T10.

### m-3: T8 "fix in T4 if scope-internal; xfail + TODO if scope-creep" is undefined
What's the criterion? "Affects atomic wire-in correctness" → fix; "pre-existing upgrade behavior" → xfail. Spec it.

## Recommended amendments

1. **Add T1.5**: refactor `state.file_state` and `write_install_state` so per-file hashing uses a `staged: Path | None = None` parameter (hashes `staged` if provided, falls back to `destination`). Update `write_install_state` to accept a `staging_root: Path | None` so callers can compose payload pre-batch.
2. **Pin T1 signature**: explicitly add `pairs: Iterable[tuple[Path, Path]] | None = None` to `atomic_install_batch` OR remove `pairs=` from T3. Land in T1 with contract test.
3. **T4 upgrade restructure**: split into two-pass — Pass A computes the full new `installed` dict (no writes); Pass B stages + atomically replaces. T4 acceptance must include "upgrade --dry-run output matches non-dry-run installed dict bit-for-bit".
4. **T1 sentinel durability**: spec `os.fsync(tmp_fd)` + `os.fsync(parent_dir_fd)` around sentinel `os.replace`. Add crash-during-sentinel-rename test.
5. **T5 stale-gate**: reuse `_is_stale` from install_recovery for the check warning, OR document age-gate explicitly.
6. **T7 manifest_sha256**: verify v0.9.4 source before T7; remove "test will catch" hedge.
7. **T9 seed**: run pytest in container or pinned venv; document the exact invocation in KNOWN_FAILING_TESTS.md header.
8. **T11 version sweep**: pre-bake `git grep "v0\.9\.6"` output into IMPL-PLAN before impl.
