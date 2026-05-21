# v0.9.6 Hotfix Plan (REV-1, post Opus 3-panel)

Date: 2026-05-21
Predecessor: v0.9.5 (`54ec5c1` signed; HEAD `528d2c8` after docs)
Status: REV-1 — reinforced after Architect/Hawk/LRR review (9 CRIT total). Codex CLI pending.

Review docs:
- `.planning/phases/02f-v0.9.6-hotfix/reviews/PLAN-review-architect.md` (3 CRIT, 5 MAJOR)
- `.planning/phases/02f-v0.9.6-hotfix/reviews/PLAN-review-ops-hawk.md` (3 CRIT, 6 MAJOR)
- `.planning/phases/02f-v0.9.6-hotfix/reviews/PLAN-review-low-reasoning-realist.md` (3 CRIT, 5 MAJOR)

## Conductor's verification before reinforce

Per Architect C-1, I re-ran the dev-unsigned upgrade smoke with proper isolation:

```
BEFORE: files=94, chain=fb55030d, trust_origin=signed_tag, version=0.0.0-dev+unknown
upgrade --target X --adapters none with HARNESS_ALLOW_UNSIGNED_DEV=1: rc=15
AFTER: files=94, chain=fb55030d  (unchanged)
audit row: release.trust.refused (seq=1)
```

The v0.9.4 install I'd been testing has `trust_origin: signed_tag` (because v0.9.4 IS a real signed tag, and the worktree-based v0.9.4 init resolves to it). Trying to upgrade to HEAD (dev_unsigned) triggers `trust_downgrade_refused` at `upgrade.py:288-299` — **CORRECT BEHAVIOR per ADR**. My original Plan §1 issue #1 was a smoke-read error.

**Net effect on scope:** Plan §3.1 (dev-unsigned manifest fix) is REMOVED. The "bug" doesn't exist; the system correctly refuses trust downgrade.

## 1. Problem statement (REV-1)

Two real deferred items from v0.9.5 remain. They are scoped narrowly to avoid hotfix scope creep per Hawk M5 + Architect M3 warnings:

1. **T14a `atomic_install_batch` helper unwired.** `scripts/lib/atomic_io.py` exposes the helper (verified via T14a tests) but `install.py` and `upgrade.py` still use direct `shutil.copyfile` loops. Kill-mid-install scenarios produce partial writes; `install_recovery` (T14b) is unreachable in practice.

2. **v094 fixture `.harness/` exclusion** at `scripts/build_v094_fixture.py:37 EXCLUDE_NAMES`. Tarballs omit `installed-manifest.json`, forcing T15 upgrade tests to synthesize in-test seeds (T15 review MAJOR-2). Real-upgrade code paths are untested.

## 2. Success criteria (REV-1)

After v0.9.6:

1. **Atomic install wire-in:** `harness init` (and `upgrade` where applicable) routes harness-owned file writes through `atomic_install_batch`. Managed-append and write_text_file content-mutating paths NOT wired (per Architect C-2; out of scope for v0.9.6).
2. **Crash safety:** SIGTERM during init → staging dir + journal preserved → `harness state repair` invokes `install_recovery.recover_aborted_install` → reaches completion or rollback.
3. **Fixture `.harness/` inclusion:** `build_v094_fixture.py` includes `.harness/installed-manifest.json` + `.harness/audit.log`. Tarball sha256 still deterministic via Python `tarfile` recipe.
4. **Real-fixture upgrade tests:** `tests/test_upgrade_from_v094_clean.py` + `tests/test_upgrade_from_v094_with_workaround.py` drop synthetic seeds and use the real .harness state from the tarball.
5. **Recovery doc:** USER_MANUAL gains a "Interrupted install recovery" note pointing to `harness state repair`.
6. **Pre-existing failure signal:** `tests/KNOWN_FAILING_TESTS.md` enumerates the 76 pre-existing failures with notes; CI can use this to distinguish new vs known failures. (Per LRR C-3.)
7. **No regressions:** pytest baseline maintained ≤76 failures; new T6 tests green.
8. **v0.9.5 → v0.9.6 in-place upgrade:** preserves state; chain extends if manifest changes; no spurious rechain rows otherwise.

Items explicitly NOT in v0.9.6:
- Managed-append / write_text_file content-mutating staging (Architect C-2 — needs full T15 redesign)
- Symlink-aware staging (Hawk M2)
- Windows support for staging (Hawk M1)
- Signal handlers in install.py for race-free SIGTERM (Hawk M3 — `.aborted` sentinel falls back to mtime threshold; acceptable for v0.9.6)
- HARNESS_ALLOW_UNSIGNED_DEV "fix" (dropped — not a bug)
- BUG-4 release-check rc=0 (dropped — v0.9.7)
- Pre-existing failure triage (dropped — v0.9.7)
- Skip-version upgrade UX (LRR C-2 — document only, no code change in v0.9.6)

## 3. Scope (in) — REV-1 narrow

### 3.1 Atomic install wire-in (partial)
- **Files in scope:** `scripts/lib/install.py` (init flow), `scripts/lib/atomic_io.py` (extend helper if needed)
- **In scope:** harness-owned policy file writes (pure copy `shutil.copyfile` → stage + `os.replace`). 
- **Out of scope (per Architect C-2):** managed-append (content rendered), write_text_file (content composed), symlinks
- **State-stamp ordering (per Hawk C2 + Architect C-2):** `installed-manifest.json` write is the JOURNAL ANCHOR, not part of the batch. Two-phase contract:
  1. Stage all harness-owned files into `.staging-<pid>/`
  2. Atomic-rename one file at a time to final destinations (per-file atomic; whole-batch resumable via journal)
  3. Write `installed-manifest.json` LAST to a temp + atomic-replace (single `os.replace` finalizes the upgrade)
- **Recovery contract:** `install_recovery` detects `.staging-<pid>/` + journal; finishes or rolls back per existing T14b
- **`harness check` integration:** add staging-dir detection (warning, not error). Per LRR CRIT-1 — make recovery flow discoverable.

### 3.2 Fixture builder includes .harness/
- `scripts/build_v094_fixture.py:EXCLUDE_NAMES` — remove `.harness` from the set
- Regenerate `tests/fixtures/v094-*.tar.gz.sha256` pinned files
- Per Hawk C3 chicken-egg: the FIXTURE's `.harness/installed-manifest.json` content IS deterministic — it's `harness init` output from v0.9.4 worktree at a fixed commit (`bd5fa83`). What's nondeterministic is mtime/uid/gid metadata in the tarball — already handled by tarfile recipe (FIXED_MTIME, uid=0).
- Update `tests/test_upgrade_from_v094_*.py` to use the real .harness state (drop `_seed_v094_full_manifest` synthetic seeds).
- **Risk acknowledged:** removing synthetic seeds may expose real upgrade bugs. Per Plan §5 risk row 4 (REV-0), this is in-scope — if real upgrade fails, that IS the bug to fix.

### 3.3 Recovery doc + known-failures signal
- `docs/USER_MANUAL.md`: add a §X "Interrupted install recovery" subsection with concrete command (`harness state repair`) and explanation of staging dir
- `tests/KNOWN_FAILING_TESTS.md` (NEW): enumerate the 76 pre-existing failures with one-line cause per group (e.g. "5x test_release_flag.py — pre-existing")
- `docs/site/manual.html` regenerated to match USER_MANUAL.md

## 4. Scope (out)

Per §2 explicit list.

## 5. Risks (REV-1)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Atomic wire-in for harness-owned only (partial coverage) → false confidence | Medium | Medium | CHANGELOG honest: "partial atomic wire-in; managed-append still in-place"; track v0.9.7 follow-up |
| `os.replace` across same-FS staging vs target works on macOS APFS + Linux ext4 (verified by T14a tests). Cross-filesystem rename fails on rare setups (eCryptfs, NFS-mounted /tmp) | Low | Medium | T14a already detects EXDEV and raises CrossFilesystemError; install.py fall back to shutil.copyfile + log warning |
| Fixture rebuild changes sha256 — invalidates pinned files; CI rebuilds from script (per T15a design) | Confirmed | Low | Update pinned `.sha256` in same commit |
| Real-fixture tests expose latent upgrade bugs → blocks release | Medium | High | Accept as in-scope; fix-or-defer per finding |
| `harness check` adds staging detection — may increase check latency on systems with many .harness/ dirs | Low | Low | scan only `.harness/.staging-*` (specific glob); O(1) cost |
| LRR CRIT-2 v0.9.4→v0.9.6 skip-upgrade still buggy | Confirmed not-in-scope | Medium | DOC the workaround: run v0.9.5 upgrade first, then v0.9.6. CHANGELOG entry. |
| KNOWN_FAILING_TESTS.md drifts | Medium | Low | Add a test that asserts pytest failure count ≤ len(KNOWN_FAILING_TESTS); fails on drift |

## 6. Open decisions

- **Q1 Atomic wire-in default:** opt-in env (`HARNESS_ATOMIC_INSTALL=1`) OR default-on?
  - Default recommendation: **default-on for harness-owned writes only** (per §3.1 scope). LRR CRIT-1 closing requires it to be effective, not opt-in.
- **Q2 v0.9.4→v0.9.6 skip-upgrade UX (LRR CRIT-2):** Document workaround vs implement detection?
  - Default recommendation: **document workaround in CHANGELOG + USER_MANUAL**. Detection logic = v0.9.7 scope.
- **Q3 KNOWN_FAILING_TESTS.md format:** structured YAML/JSON vs markdown table?
  - Default recommendation: **markdown table** with columns: test path, failure type, since, notes. Human-readable, agent-readable.
- **Q4 Commit shape:** per-task atomic (matching v0.9.5 pattern) OR bundled feat commit?
  - Default recommendation: **per-task atomic.**
- **Q5 Release version semantics:** Patch v0.9.6 OR minor v0.10.0 since we're adding new file (KNOWN_FAILING_TESTS.md)?
  - Default recommendation: **patch v0.9.6**. New test infra file is not breaking.

## 7. Specifications

### 7.1 Atomic wire-in (harness-owned only)

`install.py:300-310` (write_copy loop) changes:

Before:
```python
for entry in entries:
    if entry.policy == "harness-owned":
        write_copy(source, destination)
```

After:
```python
staging_dir = target / ".harness" / f".staging-{os.getpid()}"
staging_dir.mkdir(parents=True, exist_ok=True)
journal_path = staging_dir / "journal.jsonl"
batch: list[tuple[Path, Path]] = []
for entry in entries:
    if entry.policy == "harness-owned":
        staged = staging_dir / entry.path
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, staged)
        batch.append((staged, destination))
# Then:
result = atomic_install_batch(staging_dir, target, journal_path)
if result.aborted:
    # Caller logs; install_recovery picks up on next state repair
    ...
# State stamp LAST
write_install_state(...)
```

`upgrade.py:755-758` similar; only the harness-owned branch.

### 7.2 Fixture builder change

```python
EXCLUDE_NAMES = {"__pycache__", ".git", ".pytest_cache", ".DS_Store"}
# .harness/ removed
```

After regeneration:
- `tests/fixtures/v094-clean.tar.gz.sha256` updated to new hash
- `tests/fixtures/v094-with-workaround.tar.gz.sha256` updated

### 7.3 KNOWN_FAILING_TESTS.md format

```markdown
# Known Pre-Existing Test Failures (as of v0.9.6)

This file documents pre-existing pytest failures inherited from v0.9.4/v0.9.5
baselines. CI gates compare current failure count against this list.

Last verified: 2026-05-21 against pytest tests/ scripts/test_*.py

| Test | Failure type | Since | Notes |
|---|---|---|---|
| tests/release_smoke/test_release_flag.py::* | smoke test pinning | v0.9.4 | grep-gate assertions |
| ... |

Total: 76 entries.
```

### 7.4 USER_MANUAL recovery section (LRR CRIT-1)

New subsection in USER_MANUAL.md (Korean primary; English aside):

```
## 중단된 설치 복구 (Interrupted install recovery)

`harness init` or `harness upgrade` 도중에 인터럽트(Ctrl+C, SIGTERM, 시스템 종료)가
발생한 경우, 타겟의 `.harness/.staging-<pid>/` 디렉터리에 부분 상태가 남습니다.

복구:
```bash
python3 scripts/harness.py state repair
```

이 명령은 자동으로 staging 디렉터리를 감지하고, 부분 rename을 완료하거나 백업
파일에서 원래 상태로 복원합니다. 복구 행위는 `release.trust.rechained` 류와 마찬가지로
`.harness/audit.log`에 `install.recovery.*` audit row로 기록됩니다.
```

## 8. Sequencing

1. T1: Atomic install wire-in (`install.py` harness-owned only) + journal detection in `harness check`
2. T2: Fixture builder `.harness/` inclusion + regenerate fixtures + update pinned sha256
3. T3: Real-fixture upgrade tests (rewrite `tests/test_upgrade_from_v094_*.py`) → may surface real bugs
4. T4 (only if T3 surfaces bugs): fix real-upgrade bugs
5. T5: Recovery doc + KNOWN_FAILING_TESTS.md
6. T6: Regenerate `docs/site/manual.html`
7. Final smoke: fresh init → SIGTERM → state repair → completion; upgrade tests green
8. CHANGELOG v0.9.6 + USER_MANUAL update + push develop → main → tag

Critical path: T1 → T3 (may unblock or block T4) → T5 → T6 → release.

## 9. Done definition

- T1-T6 land; all new tests green
- pytest ≤76 failures (current baseline preserved)
- `KNOWN_FAILING_TESTS.md` count matches actual
- USER_MANUAL recovery section present
- Real-fixture upgrade tests pass (no synthetic seeds)
- Atomic kill-mid-install scenario: SIGTERM during init → `state repair` recovers cleanly
- v0.9.5 → v0.9.6 in-place upgrade preserves state
- v0.9.4 → v0.9.6: documented as needs v0.9.5 first (workaround, not fix)
- Final Opus 3-panel pass on diff
- Codex CLI pass on diff (if available; Opus-as-codex fallback)
- Signed tag `v0.9.6` pushed; GitHub release published

## 10. Notes for codex review

Codex review must specifically attack:
- T1 atomic wire-in: did harness-owned branch fully transition? Any direct shutil.copyfile remaining for harness-owned?
- Fixture rebuild determinism: does running build_v094_fixture.py twice from different machines produce identical bytes?
- T3 real-fixture tests: do they actually exercise the upgrade code path differently from the synthetic seed version?
- KNOWN_FAILING_TESTS.md: does the count assertion catch regressions or only count-changes?
- Atomic + state stamp ordering: if SIGTERM arrives between batch finish and state stamp write, what does recovery see?
