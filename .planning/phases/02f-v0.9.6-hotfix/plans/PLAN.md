# v0.9.7 Hotfix Plan (REV-5, post Codex REV-4 BLOCK)

Date: 2026-05-21
Target version: **v0.9.7** (v0.9.6 already shipped 2026-05-21 as docs-only at `06241f8`)
Predecessor: v0.9.6 (HEAD `06241f8`)
Status: REV-5 — closes Codex REV-4 N-3 (sentinel-absent recovery semantics).

REV-2 → REV-3 deltas:
- §2.2 + §3.1 + §7.1: replace "rebuild manifest from journal entries" with a **pending-manifest sidecar** contract (the manifest content is staged durably before the batch starts; recovery atomic-renames it to its final name). The journal stops being a manifest-content source-of-truth; it remains a per-file rename log only.
- §3.2 + §7.3: normalize the actual v0.9.4 schema fields (`source`, `files.*`, `source_provenance`, `git_user_email_at_install_sha256`), not REV-2's invented `source_root`/`entries` placeholders.
- §3.1 + §7.1: `defer_cleanup` default = **False** (legacy behavior preserved); new two-phase callers pass `True` explicitly.

REV-3 → REV-4 delta (Codex N-2):
- §3.1 + §7.1 + §7.2: introduce a **batch-complete sentinel** `$TARGET/.harness/.staging-<pid>.complete` written by `atomic_install_batch` AFTER all per-file renames succeed and BEFORE returning when `defer_cleanup=True`. Recovery requires sentinel presence as positive completion proof before finalizing the pending manifest. Without sentinel → rollback or quarantine.

REV-4 → REV-5 delta (Codex N-3):
- §7.2 sentinel-absent + journal/staging-present path now: attempt **resume** via `atomic_install_batch(..., defer_cleanup=True)`. If resume completes (writes sentinel as side-effect) → re-enter finalize branch on the same recovery pass. If resume aborts or `.aborted` sentinel is present → **explicit rollback** (own code, not `_recover_one`), then delete pending sidecar.
- §7.2 explicit rollback path written inline (no longer reuses `_recover_one`'s resume-on-no-sentinel branch).

Review docs:
- `.planning/phases/02f-v0.9.6-hotfix/reviews/PLAN-review-architect.md` (REV-0 → REV-1 closed 3 CRIT)
- `.planning/phases/02f-v0.9.6-hotfix/reviews/PLAN-review-ops-hawk.md` (REV-0 → REV-1 closed 3 CRIT)
- `.planning/phases/02f-v0.9.6-hotfix/reviews/PLAN-review-low-reasoning-realist.md` (REV-0 → REV-1 closed 3 CRIT)
- `.planning/phases/02f-v0.9.6-hotfix/reviews/PLAN-review-codex.md` (REV-1 → REV-2 closes 5 CRIT below)

(Phase dir name keeps `02f-v0.9.6-hotfix` for git history; release target renamed to v0.9.7.)

## Conductor's verification before REV-2

Per Architect C-1 (REV-1), dev-unsigned upgrade smoke re-run with proper isolation: `trust_origin: signed_tag` correctly refused dev_unsigned downgrade. The "v0.9.6 dev-unsigned manifest" item is NOT a bug; v0.9.5 §3.1 entry is dropped.

## 1. Problem statement (REV-2)

Two real deferred items from v0.9.5/v0.9.6 remain. Scoped narrowly per Hawk M5 + Architect M3:

1. **T14a `atomic_install_batch` helper unwired.** `scripts/lib/atomic_io.py:283-477` provides per-file atomic rename + journal, but `install.py:299-310` and `upgrade.py:738-794` still use direct `shutil.copyfile` loops. Crash-mid-install produces torn writes; `install_recovery` (T14b) is unreachable.

2. **v0.9.4 fixture `.harness/` exclusion** at `scripts/build_v094_fixture.py:37 EXCLUDE_NAMES`. Tarballs omit `installed-manifest.json` + `audit.log`, forcing T15 upgrade tests to synthesize seeds via `_seed_v094_manifest` / `_seed_v094_full_manifest` (`tests/test_upgrade_from_v094_clean.py:108-179`, `tests/test_upgrade_from_v094_with_workaround.py:179-248`). Real-upgrade code paths untested.

## 2. Success criteria (REV-2)

After v0.9.7:

1. **Atomic install wire-in (init + upgrade harness-owned destinations).** `install.py` init path and `upgrade.py` harness-owned write branch (lines 738-758 and 791-794) route through `atomic_install_batch`. Managed-append + `write_text_file` content-mutating paths remain in-place and are documented as such. (Codex M-1)
2. **State-stamp via pending-manifest sidecar (durable BEFORE batch).** `atomic_install_batch` gains a `defer_cleanup=False` param (default False — legacy behavior preserved; new callers pass True). Two-phase flow:
   (a) Caller composes the full `installed-manifest.json` payload and writes it to `$TARGET/.harness/installed-manifest.json.pending-<pid>` via temp+`os.replace` (durable BEFORE any target writes).
   (b) Caller invokes `atomic_install_batch(..., defer_cleanup=True)` — per-file rename + journal append.
   (c) On batch success, caller does `os.replace(pending_path, installed_manifest_path)` — single atomic finalizer.
   (d) Cleanup: delete journal + staging dir.
   `install_recovery` extension: if pending-manifest sidecar exists, scan its sibling journal: (i) batch complete → finalize rename (step c); (ii) batch incomplete → roll back via existing T14b path and delete pending sidecar. If pending sidecar is gone and journal+staging both gone, recovery is a no-op. (Closes Codex C-1.)
3. **Journal path convention unified.** Plan uses the *sibling* convention `staging_dir.parent / (staging_dir.name + ".journal.jsonl")` — matches `install_recovery._staging_journal_path` at `scripts/lib/install_recovery.py:117-119`. Contract test asserts the path. (Codex C-2)
4. **Fixture determinism gated by rebuild-twice equality.** `scripts/build_v094_fixture.py` runs v0.9.4 init with normalized env: `HARNESS_FIXED_NOW_ISO`, fixed source-root string, scrubbed absolute paths in the resulting `installed-manifest.json`. After build, the script computes sha256 of both clean + workaround tarballs twice from independent temp dirs and asserts equality before writing. CI test `tests/test_fixture_determinism.py` runs the script in a temp dir and compares sha256 to pinned. (Codex C-3)
5. **Real-fixture upgrade tests, no synthetic seeds.** `_seed_v094_manifest` and `_seed_v094_full_manifest` are deleted from `tests/test_upgrade_from_v094_*.py`. Tests fail loudly if extracted fixtures lack `.harness/installed-manifest.json`. (Codex C-4)
6. **KNOWN_FAILING_TESTS.md = node-id set, not count.** Format is one node-id per line plus a notes column. Drift gate asserts: `current_failing_nodeids == known_set` (exact match); reports both new failures and unexpectedly-passing knowns. (Codex C-5)
7. **`harness check` staging detection (precise).** Scan `target/.harness/.staging-*` AND require a sibling `.staging-*.journal.jsonl` to qualify as a harness staging dir. Avoids false positives from unrelated `.staging-*` artifacts. Warning only. (Codex M-2)
8. **Cross-FS opt-out, not silent fallback.** If `atomic_install_batch` encounters `CrossFilesystemError`, install fails with actionable message: "Target filesystem does not support atomic rename. Set HARNESS_ALLOW_NONATOMIC_INSTALL=1 to fall back to direct copy (NOT crash-safe)." Staging dir is always under `$TARGET/.harness/` to make same-device the default. (Codex M-3)
9. **v0.9.4 → v0.9.7 skip-upgrade explicit guard.** `upgrade.py` detects prior version == "0.9.4" and target ≥ "0.9.7"; refuses with actionable hint: "Skip-upgrade from v0.9.4 directly to v0.9.7 is unsupported; run v0.9.5 first." Bypassable with `HARNESS_ALLOW_SKIP_UPGRADE=1`. (Codex M-4)
10. **CHANGELOG honesty.** Exact entry: `v0.9.7 hardens harness-owned init/upgrade file replacement with resumable per-file atomic staging; managed-append and composed write_text_file updates remain in-place and are deferred to a later release.` Plus skip-upgrade guard line. (Codex M-5)
11. **Recovery doc:** USER_MANUAL "Interrupted install recovery" subsection.
12. **In-place v0.9.6 → v0.9.7 upgrade:** preserves state; chain extends; no spurious rechain.
13. **pytest:** failing node-id set ⊆ KNOWN_FAILING_TESTS.md set; new tests green.

Items explicitly NOT in v0.9.7:
- Managed-append / `write_text_file` content-mutating atomic staging (Architect C-2 — needs T15 redesign; deferred)
- Symlink-aware staging (Hawk M2)
- Windows support for staging (Hawk M1)
- Signal handlers in install.py for race-free SIGTERM (Hawk M3 — `.aborted` sentinel + mtime threshold acceptable)
- HARNESS_ALLOW_UNSIGNED_DEV "fix" (not a bug)
- BUG-4 release-check rc=0 (deferred → v0.9.8)
- Pre-existing failure triage / fixes (deferred → v0.9.8)

## 3. Scope (in) — REV-2

### 3.1 Atomic install wire-in (init + upgrade harness-owned)

Files in scope:
- `scripts/lib/atomic_io.py` — extend `atomic_install_batch` with `defer_cleanup=False` param (**default False** — legacy auto-cleanup preserved; new two-phase callers pass `True`)
- `scripts/lib/install.py:299-310` — wrap harness-owned (else-branch `write_copy`) in pending-manifest + staging+batch pattern
- `scripts/lib/upgrade.py:738-794` — same for upgrade harness-owned writes (conflict copies stay direct-copy and are documented out of scope)
- `scripts/lib/install_recovery.py` — handle pending-manifest sidecar finalization

Two-phase contract with pending-manifest sidecar (per Codex C-1, REV-3):
1. Caller composes full `installed-manifest.json` payload (entries, sha256s, chain, version, source_provenance, etc).
2. Write payload to `$TARGET/.harness/installed-manifest.json.pending-<pid>` via temp+`os.replace`. **Durability boundary BEFORE any target writes.**
3. Stage all harness-owned files to `$TARGET/.harness/.staging-<pid>/` (per Codex M-3, same-device guarantee).
4. Call `atomic_install_batch(staging_dir, target, journal_path, defer_cleanup=True)` — per-file atomic rename + journal append.
5. On batch success: `os.replace(pending_path, installed_manifest_path)` — single atomic finalizer for the install record.
6. Cleanup: delete journal + staging dir + (if all clean) any leftover `.pending-*` from prior aborted attempts.

Recovery contract (per `install_recovery.recover_aborted_install` extension; REV-5):
- Scan `$TARGET/.harness/` for `installed-manifest.json.pending-*` files. For each pending sidecar with pid `P`:
  - Sentinel path: `$TARGET/.harness/.staging-<P>.complete`
  - Journal path: `$TARGET/.harness/.staging-<P>.journal.jsonl`
  - Staging dir: `$TARGET/.harness/.staging-<P>/`
  - **Sentinel present** → FINALIZE: `os.replace(pending, installed-manifest.json)`; emit `install.recovery.manifest_finalized`; delete sentinel + journal + staging dir.
  - **`.aborted` marker present in staging dir** (sentinel absent) → EXPLICIT ROLLBACK: undo completed renames from backups; quarantine on missing backup; delete pending + journal + staging. (Inline implementation in `_recover_pending_manifest`, NOT a call into `_recover_one` resume path.)
  - **Sentinel absent + journal/staging exist + no `.aborted`** → RESUME-THEN-FINALIZE: call `atomic_install_batch(..., defer_cleanup=True)` to finish remaining renames. If resume completes (sentinel appears) → finalize. If resume aborts or sentinel not produced → EXPLICIT ROLLBACK (same inline path).
  - **Sentinel absent + journal absent + staging absent** → ORPHAN PENDING: quarantine pending sidecar to `.harness/conflicts/`; emit `install.recovery.pending_orphaned`.
- Existing T14b in-batch recovery (staging present without pending sidecar — legacy callers) unchanged.

Why a separate `.complete` file rather than scanning the journal: the journal is append-only and a partial fsync could leave the last line truncated; the journal also doesn't carry "expected total" so we can't verify completeness from journal contents alone without a separate batch-plan file. A zero-byte sentinel `os.replace`'d into place after the last journal write is positive proof that `atomic_install_batch` returned successfully.

`harness check` integration (Codex M-2):
- New helper: scan `target/.harness/.staging-*` glob; for each match, verify sibling `.staging-<name>.journal.jsonl` exists
- If qualified staging dir found, emit warning row pointing to `harness state repair`
- Latency: single glob + sibling exists check; O(N) on direct children of `.harness/`, bounded

### 3.2 Fixture builder includes .harness/ with determinism gate (REV-3 — actual v0.9.4 schema)

- `scripts/build_v094_fixture.py:37` — remove `.harness` from `EXCLUDE_NAMES`
- v0.9.4 `installed-manifest.json` schema (verified via `git show v0.9.4:scripts/lib/state.py:160-290`):
  - Top-level: `schema_version`, `state_schema_version`, `harness_version`, `version`, `manifest_sha256`, `source` (absolute path — host-specific), `adapters`, `profiles`, `packs`, `init_options`, `pack_metadata`, `available_scopes`, `files` (dict), `source_provenance` (optional), `git_user_email_at_install_sha256` (host-specific), `installed_files_chain_hash`
  - Per-entry under `files[path]`: `policy`, `version`, `installed_at` (timestamp — host-specific without HARNESS_FIXED_NOW_ISO), `source_sha256`, `sha256`, `owner`, `adapter`, `profile`, `pack`, `installed_sha256`, `current_sha256`
- New `_normalize_v094_install_state(target)` called AFTER `run_v094_init`, BEFORE tarball:
  - Reads `target/.harness/installed-manifest.json`
  - Rewrites top-level `source` → `"<fixture-source-root>"` (was absolute path)
  - Rewrites `git_user_email_at_install_sha256` → `None` (was host-derived)
  - For each `files[path]` entry: rewrite `installed_at` → `FIXED_INSTALL_ISO = "2026-01-01T00:00:00+00:00"` (defensive — `HARNESS_FIXED_NOW_ISO` env should already normalize this, but belt-and-suspenders)
  - Strip `source_provenance` if present (contains git worktree state)
  - Re-serialize with `sort_keys=True, indent=2` + trailing newline
  - Truncate `audit.log` to deterministic single line: `{"verb": "fixture.init", "args": {}, "seq": 1}`
  - Recompute `manifest_sha256` IF it depends on normalized fields (check v0.9.4 `manifest_sha256` source — if it hashes source manifest YAML only, no recompute needed; if it hashes the install record itself, recompute after normalization). Determinism test will catch a mismatch either way.
- Builder runs `HARNESS_FIXED_NOW_ISO="2026-01-01T00:00:00+00:00"` in subprocess env passed to v0.9.4 init
- Builder runs the full build twice (clean + workaround in separate temp dirs), captures sha256s, then re-runs build in a fresh temp tree; aborts with explicit error if sha256s differ between runs
- New test `tests/test_fixture_determinism.py` runs `build_v094_fixture.py --output-dir <tmp>` twice and asserts sha256 equality

Risk acknowledged: removing synthetic seeds will likely surface real upgrade bugs. Per §5 risk row, accept as in-scope — fix or surgically defer per finding.

### 3.3 Real-fixture tests (delete synthetic seeders)

- Delete `_seed_v094_manifest` at `tests/test_upgrade_from_v094_clean.py:108-179`
- Delete `_seed_v094_manifest` + `_seed_v094_full_manifest` at `tests/test_upgrade_from_v094_with_workaround.py:179-299`
- Tests now consume `.harness/` extracted from the tarball directly
- Add assertion at extraction: `assert (extracted / ".harness" / "installed-manifest.json").exists(), "fixture missing .harness; rebuild fixture"`

### 3.4 KNOWN_FAILING_TESTS.md (node-id set)

Format:
```markdown
# Known Pre-Existing Test Failures (as of v0.9.7)

Last verified: 2026-05-21 against pytest tests/ scripts/test_*.py
Gate: tests/test_known_failures_drift.py

## Node IDs (76 entries)

tests/release_smoke/test_release_flag.py::test_release_flag_check_phrase
tests/release_smoke/test_release_flag.py::test_release_flag_compose_phrase
...
```

Drift gate `tests/test_known_failures_drift.py`:
- Runs pytest with `--collect-only -q` + parses live failures, OR reads a cached `current_failing.txt` produced by CI
- Asserts `set(current) == set(known)`; reports `current - known` (new failures) and `known - current` (fixed)

### 3.5 Skip-upgrade guard (v0.9.4 → v0.9.7)

`scripts/lib/upgrade.py` — after prior-version detection (~line 667), before manifest writes:
```python
if prior_version in {"0.9.4", "v0.9.4"} and _semver_ge(target_version, "0.9.7"):
    if not os.environ.get("HARNESS_ALLOW_SKIP_UPGRADE"):
        raise UpgradeRefused(
            "Skip-upgrade from v0.9.4 directly to v0.9.7 is unsupported. "
            "Run v0.9.5 first, then v0.9.7. "
            "Override: HARNESS_ALLOW_SKIP_UPGRADE=1"
        )
```

### 3.6 Recovery doc + manual.html regen

- `docs/USER_MANUAL.md` — new subsection "중단된 설치 복구 (Interrupted install recovery)"
- `docs/site/manual.html` — regenerated to match

## 4. Scope (out)

Per §2 explicit list. Conflict-copy writes in `upgrade.py:738-740,791-794` stay direct (non-atomic, sidecar files, lower risk); documented in CHANGELOG.

## 5. Risks (REV-2)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Atomic wire-in is partial (harness-owned only); managed-append still in-place → false confidence | Medium | Medium | CHANGELOG honest line per §2.10; track v0.9.8 follow-up |
| `os.replace` across FS — same-device enforced by staging under `$TARGET/.harness/` | Low | Medium | If `CrossFilesystemError` occurs, fail loudly per §2.8 (no silent fallback) |
| Fixture rebuild changes sha256 — invalidates pinned files | Confirmed | Low | Update pinned `.sha256` in same commit; determinism test gates regressions |
| Real-fixture tests expose latent upgrade bugs | Medium | High | Accept as in-scope; fix-or-defer per finding |
| `harness check` adds staging scan — latency | Low | Low | Single glob + sibling existence check; O(N) on .harness children |
| v0.9.4 → v0.9.7 skip-upgrade refused → user friction | Medium | Low | Actionable hint + override env var; documented in CHANGELOG |
| KNOWN_FAILING_TESTS.md identity drift | Mitigated | Low | Node-id set comparison catches both new failures AND unexpectedly-passing knowns |
| Post-batch/pre-manifest crash window: journal exists but staging gone | Confirmed | Medium | Recovery extended to re-write manifest from journal entries per §3.1 |

## 6. Open decisions

- **Q1 Atomic default:** default-on for harness-owned writes (no env-flag). LRR CRIT-1 + Codex M-3 confirm. ✓ decided
- **Q2 Skip-upgrade UX:** detect + refuse with override env (per Codex M-4), not document-only. ✓ decided
- **Q3 KNOWN_FAILING_TESTS format:** markdown with one node-id per line, plus header + drift gate test. ✓ decided
- **Q4 Commit shape:** per-task atomic. ✓ decided
- **Q5 Version target:** v0.9.7 patch (v0.9.6 taken). ✓ decided

## 7. Specifications

### 7.1 Atomic wire-in two-phase with pending-manifest sidecar (REV-3)

`install.py` init flow (replaces direct write_copy else-branch):
```python
target.mkdir(parents=True, exist_ok=True)
harness_dir = target / ".harness"
harness_dir.mkdir(parents=True, exist_ok=True)

# Phase 1: compose + durably stage installed-manifest.json content BEFORE any target writes
pending_manifest_path = harness_dir / f"installed-manifest.json.pending-{os.getpid()}"
manifest_payload = build_install_state_payload(  # extracted from write_install_state
    root=root, target=target, entries=entries,
    adapters=adapters, profiles=profiles, packs=packs,
)
_atomic_write_json(pending_manifest_path, manifest_payload)  # temp + os.replace

# Phase 2: stage files
staging_dir = harness_dir / f".staging-{os.getpid()}"
staging_dir.mkdir(parents=True, exist_ok=True)
journal_path = staging_dir.parent / (staging_dir.name + ".journal.jsonl")  # sibling
batch_pairs: list[tuple[Path, Path]] = []
for entry, source, destination in destinations:
    if entry.policy == "managed-append":
        write_managed_append(source=source, destination=destination, entry=entry)
    elif entry.policy == "project-owned" and destination.exists():
        continue
    else:
        staged = staging_dir / entry.path
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, staged)  # dest is staging, not target
        batch_pairs.append((staged, destination))

result = atomic_install_batch(
    staging_dir=staging_dir,
    target=target,
    journal_path=journal_path,
    pairs=batch_pairs,
    defer_cleanup=True,  # NEW — caller owns cleanup
)
if result.aborted:
    # Leave pending sidecar + journal + staging for install_recovery; raise after audit.
    raise InstallFailed(...)

# Phase 3: atomic finalize — single os.replace is the install durability boundary
sync_roomodes_profile_modes(...)
final_manifest_path = harness_dir / "installed-manifest.json"
os.replace(pending_manifest_path, final_manifest_path)

# Phase 4: cleanup AFTER finalize durable
journal_path.unlink(missing_ok=True)
_rmdir_recursive(staging_dir)  # best-effort
```

Note: `write_install_state` is split into `build_install_state_payload` (pure dict construction) + `_atomic_write_json` (existing temp+rename). Existing call sites that want one-shot semantics can call a compat wrapper.

`upgrade.py:738-794` — apply same pattern to harness-owned else-branch only (managed-append + conflict copies stay in-place per §4).

`atomic_install_batch` signature change (`scripts/lib/atomic_io.py`):
```python
def atomic_install_batch(
    staging_dir: Path,
    target: Path,
    journal_path: Path,
    pairs: Iterable[tuple[Path, Path]] | None = None,
    *,
    defer_cleanup: bool = False,  # default preserves legacy behavior
) -> BatchResult:
    ...
    # All renames done successfully here (result.aborted == False)
    if defer_cleanup:
        # REV-4: write completion sentinel via temp+os.replace so its presence is durable proof
        sentinel_path = staging_dir.parent / (staging_dir.name + ".complete")
        sentinel_tmp = staging_dir.parent / (staging_dir.name + ".complete.tmp")
        sentinel_tmp.write_bytes(b"")
        os.replace(sentinel_tmp, sentinel_path)
    else:
        # Legacy: auto-cleanup staging + journal on full success (no sentinel needed)
        _cleanup_staging_and_journal(staging_dir, journal_path)
    return result
```

Phase 3 of §7.1 init flow updated to clean up sentinel on success:
```python
# Phase 3: atomic finalize
os.replace(pending_manifest_path, final_manifest_path)

# Phase 4: cleanup AFTER finalize durable
sentinel_path = staging_dir.parent / (staging_dir.name + ".complete")
sentinel_path.unlink(missing_ok=True)
journal_path.unlink(missing_ok=True)
_rmdir_recursive(staging_dir)  # best-effort
```

### 7.2 `install_recovery` extension (REV-3 — pending-manifest finalizer)

Add to `recover_aborted_install`:
```python
def _recover_pending_manifest(target: Path, pending: Path) -> RecoveryAction:
    """Finalize / resume-then-finalize / rollback / orphan per REV-5 contract.

    Decision matrix:
      sentinel present                          → FINALIZE (positive proof)
      sentinel absent, .aborted in staging       → EXPLICIT ROLLBACK
      sentinel absent, journal+staging present   → RESUME via atomic_install_batch(defer_cleanup=True);
                                                   on success the resume writes the sentinel; we re-enter
                                                   the FINALIZE branch. On resume abort → EXPLICIT ROLLBACK.
      sentinel absent, journal+staging absent    → ORPHAN PENDING (quarantine)
    """
    pid_str = pending.name.removeprefix("installed-manifest.json.pending-")
    harness = target / ".harness"
    staging_dir = harness / f".staging-{pid_str}"
    journal_path = harness / f".staging-{pid_str}.journal.jsonl"
    sentinel_path = harness / f".staging-{pid_str}.complete"

    def _finalize() -> RecoveryAction:
        final_path = harness / "installed-manifest.json"
        os.replace(pending, final_path)
        sentinel_path.unlink(missing_ok=True)
        journal_path.unlink(missing_ok=True)
        if staging_dir.exists():
            _rmdir_recursive(staging_dir)
        _emit_audit(target, "install.recovery.manifest_finalized", {"pid": pid_str})
        return RecoveryAction(kind="manifest_finalized", count=0)

    def _explicit_rollback() -> RecoveryAction:
        # Undo any successful renames recorded in journal using backups; quarantine otherwise.
        # Mirrors the .aborted-sentinel branch of _recover_one but does NOT reuse the resume code path.
        records = read_install_journal(journal_path) if journal_path.exists() else []
        completed_rels = _journal_completed(records)
        backups = _backups_dir(target)
        conflicts = _conflicts_dir(target)
        for rel in completed_rels:
            installed_path = target / rel
            if not installed_path.exists():
                continue
            bak = _find_backup(backups, installed_path.name)
            try:
                if bak is not None:
                    installed_path.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(str(bak), str(installed_path))
                    _emit_audit(target, "install.recovery.rolled_back", {"rel": rel, "backup": str(bak)})
                else:
                    _quarantine_file(installed_path, conflicts, rel, target, _make_result_local())
            except OSError:
                _quarantine_file(installed_path, conflicts, rel, target, _make_result_local())
        # Cleanup all pending-batch state
        if staging_dir.exists():
            shutil.rmtree(str(staging_dir), ignore_errors=True)
        journal_path.unlink(missing_ok=True)
        pending.unlink(missing_ok=True)
        _emit_audit(target, "install.recovery.rolled_back", {"pid": pid_str, "rel_count": len(completed_rels)})
        return RecoveryAction(kind="rolled_back", count=len(completed_rels))

    # FINALIZE (sentinel proven)
    if sentinel_path.exists():
        return _finalize()

    # EXPLICIT ROLLBACK (aborted)
    if (staging_dir / ".aborted").exists():
        return _explicit_rollback()

    # RESUME → FINALIZE or ROLLBACK
    if journal_path.exists() or staging_dir.exists():
        try:
            batch_result = atomic_install_batch(
                staging_dir, target, journal_path, defer_cleanup=True
            )
        except OSError:
            return _explicit_rollback()
        if not batch_result.aborted and sentinel_path.exists():
            return _finalize()
        # Resume failed or sentinel wasn't created → rollback
        return _explicit_rollback()

    # ORPHAN (nothing to resume; pending sidecar alone)
    conflicts = _conflicts_dir(target)
    conflicts.mkdir(parents=True, exist_ok=True)
    pending.rename(conflicts / pending.name)
    _emit_audit(target, "install.recovery.pending_orphaned", {"pid": pid_str})
    return RecoveryAction(kind="pending_orphaned", count=0)
```

`recover_aborted_install` scans `.harness/*.pending-*` first; THEN delegates to existing per-staging-dir loop for any staging-only state without pending (legacy upgrade paths or partial earlier runs).

### 7.3 Fixture normalization (REV-3 — actual v0.9.4 schema)

`build_v094_fixture.py` additions:
```python
FIXED_INSTALL_ISO = "2026-01-01T00:00:00+00:00"
FIXED_SOURCE_PLACEHOLDER = "<fixture-source-root>"

def _normalize_v094_install_state(target: Path) -> None:
    manifest = target / ".harness" / "installed-manifest.json"
    if not manifest.exists():
        raise FixtureBuildError("v0.9.4 init did not produce installed-manifest.json")
    data = json.loads(manifest.read_text())

    # Top-level host-specific fields
    if "source" in data:
        data["source"] = FIXED_SOURCE_PLACEHOLDER
    data["git_user_email_at_install_sha256"] = None
    data.pop("source_provenance", None)  # contains worktree state

    # Per-file installed_at timestamps (defensive — HARNESS_FIXED_NOW_ISO should handle this)
    for path_key, entry in data.get("files", {}).items():
        if isinstance(entry, dict) and "installed_at" in entry:
            entry["installed_at"] = FIXED_INSTALL_ISO

    manifest.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

    # Truncate audit log
    audit = target / ".harness" / "audit.log"
    if audit.exists():
        audit.write_text(json.dumps({"verb": "fixture.init", "args": {}, "seq": 1}) + "\n")
```

In `run_v094_init`, pass env:
```python
env = os.environ.copy()
env["HARNESS_FIXED_NOW_ISO"] = FIXED_INSTALL_ISO
# subprocess.run(..., env=env)
```

After both v0.9.4 inits complete and normalization runs, capture sha256 of each tarball; rebuild once more in a fresh temp tree and assert byte-equality before writing pinned `.sha256` files.

Determinism self-check (in `main`):
```python
sha_first = build_tar_gz(...)
build_tar_gz(...)  # second build to a sibling tmp
sha_second = ...
if sha_first != sha_second:
    raise FixtureBuildError(f"Non-deterministic fixture build: {sha_first} != {sha_second}")
```

### 7.4 KNOWN_FAILING_TESTS.md + drift gate

Header + node-id list per §3.4. Test:
```python
# tests/test_known_failures_drift.py
def test_failing_set_matches_known():
    known = _parse_known_failures("tests/KNOWN_FAILING_TESTS.md")
    current = _collect_current_failures()  # from cached pytest report
    assert current == known, (
        f"New failures: {sorted(current - known)}; "
        f"Fixed (drop from known): {sorted(known - current)}"
    )
```

Collection strategy: read a pytest `--junitxml` report cached in `.harness-test-cache/` during the previous full pytest run. CI step writes the cache before the drift test runs. Locally, dev runs `make test-cache` first. (Avoids re-running 1300 tests inside one test.)

### 7.5 Skip-upgrade guard

Per §3.5 snippet. Add `_semver_ge` helper if not present (or use packaging.version).

### 7.6 USER_MANUAL recovery section

```
## 중단된 설치 복구 (Interrupted install recovery)

`harness init` or `harness upgrade` 도중에 인터럽트(Ctrl+C, SIGTERM, 시스템 종료)가
발생한 경우, 타겟의 `.harness/.staging-<pid>/` 디렉터리 또는 sibling
`.staging-<pid>.journal.jsonl` 파일에 부분 상태가 남습니다.

복구:
    python3 scripts/harness.py state repair

자동으로 staging/journal 을 감지하고:
- 부분 rename 이면 완료 또는 백업에서 롤백
- 모든 rename 완료 후 manifest 작성 전 크래시면 journal 로부터 manifest 재생성
복구 결과는 `.harness/audit.log` 에 `install.recovery.*` audit row 로 기록.
```

## 8. Sequencing

1. T1: `atomic_install_batch` defer_cleanup param + install_recovery orphan-journal handling + contract test for sibling journal path (Codex C-1, C-2)
2. T2: install.py init wire-in (harness-owned only)
3. T3: upgrade.py wire-in (harness-owned else-branch)
4. T4: harness check staging detection + journal-validation (Codex M-2)
5. T5: Fixture normalization (`_normalize_v094_install_state`) + determinism self-check (Codex C-3)
6. T6: Remove `.harness` from EXCLUDE_NAMES + regenerate fixtures + update pinned sha256
7. T7: Rewrite tests/test_upgrade_from_v094_*.py to drop synthetic seeders (Codex C-4)
8. T8: KNOWN_FAILING_TESTS.md node-id set + drift gate test (Codex C-5)
9. T9: Skip-upgrade guard in upgrade.py (Codex M-4)
10. T10: USER_MANUAL recovery section + docs/site/manual.html regen
11. T11: CHANGELOG v0.9.7 entry (Codex M-5)
12. Final smoke: SIGTERM mid-init → state repair → completion; SIGTERM mid-batch and mid-stamp scenarios both recover; in-place v0.9.6 → v0.9.7 upgrade smoke
13. Tag v0.9.7 (release pending user approval per workflow)

Critical path: T1 → T2 → T3 → T5 → T6 → T7 (may surface real bugs) → fix-or-defer → T8-T11 → smoke → release.

## 9. Done definition

- T1-T11 land; all new tests green
- pytest failing set ⊆ KNOWN_FAILING_TESTS.md (exact match via drift gate)
- USER_MANUAL recovery section present; manual.html regenerated
- Real-fixture upgrade tests pass without synthetic seeds
- Three kill-window smokes recover cleanly: mid-stage, mid-batch, post-batch/pre-stamp
- v0.9.6 → v0.9.7 in-place upgrade preserves state
- v0.9.4 → v0.9.7 refused with actionable message
- Final Opus 3-panel + codex CLI pass on diff
- Signed tag `v0.9.7` ready (release on user approval)

## 10. Notes for next codex review (REV-2 → REV-3 if needed)

Attack specifically:
- T1 contract test: does it assert journal sibling path exactly?
- T5 normalization: does it scrub EVERY host-specific field? Run `diff` of manifest content between two builds to catch overlooked fields.
- T7 tests: does any seeding remain (grep `_seed_v094`)?
- T8 drift gate: does it actually fail when set-equality breaks (positive + negative case)?
- T9 skip-upgrade: does override env var truly bypass, or get logged?
- Recovery orphan-journal: does it correctly distinguish "manifest stale" from "manifest correct, journal leftover"?
