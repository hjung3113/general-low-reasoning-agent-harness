# v0.9.7 Hotfix Implementation Plan (REV-2)

Date: 2026-05-21
Derived from: PLAN.md REV-5
Status: REV-2 — addresses 4-panel BLOCK (Architect 4 CRIT, Hawk 5 CRIT, LRR 4 CRIT, Codex 1 CRIT + 4 MAJOR)
Predecessor tag: `v0.9.6` (`06241f8`)
Target tag: `v0.9.7`
Commit shape: per-task atomic

## REV-1 → REV-2 deltas (critical changes)

**Architectural pivot (Architect C-1, C-3):** Phase order revised. Pending-manifest sidecar is composed and written AFTER staging is complete but BEFORE the atomic rename batch. Staging hashes are used for per-file `sha256`/`installed_sha256`/`current_sha256` (durability property "sidecar exists before any target write" preserved — staging dir is under `.harness/`, not target body).

**New phase order (replaces PLAN §7.1 phase 1/2 sequence):**
1. Stage all harness-owned files to `.staging-<runid>/` (target body untouched)
2. Compose `installed-manifest.json` payload using STAGED file hashes (managed-append still hashes destination as today, project-owned skipped)
3. Write payload to `installed-manifest.json.pending-<runid>` via atomic temp+fsync+os.replace
4. `atomic_install_batch(..., defer_cleanup=True)` — per-file rename + journal + completion sentinel
5. Sanity check: re-read sentinel exists, then `os.replace(pending, final)` (atomic finalize)
6. Post-finalize verify: re-read `installed-manifest.json`, assert `version == harness_version`; raise if not
7. Cleanup: delete sentinel + journal + staging dir + any `.complete.tmp` orphans

**Naming nonce (Codex CRIT, Hawk C-1):** All sidecar/staging/journal/sentinel artifacts use `runid = f"{os.getpid()}-{iso_compact}-{secrets.token_hex(3)}"` instead of bare pid. Format: `.staging-<runid>/`, `.staging-<runid>.journal.jsonl`, `.staging-<runid>.complete`, `installed-manifest.json.pending-<runid>`.

**`file_state` refactor (Architect C-1):** Add optional `staged: Path | None = None` to `state.file_state`. When provided AND policy is harness-owned, hash `staged` instead of `destination`. Existing callers unaffected (param defaults None → legacy behavior).

**Drop `pairs=` arg (Architect C-2):** `atomic_install_batch` keeps its existing signature; it walks the staging tree. Removed misleading `pairs=` from PLAN snippet.

**Sentinel durability (Architect C-4, Hawk M-3):** Sentinel write uses `fsync(tmp_fd)` + `os.replace` + `fsync(parent_dir_fd)`. Same discipline for pending sidecar.

**Sentinel .tmp orphan cleanup (Hawk C-3):** `_recover_pending_manifest` scans `.harness/.staging-*.complete.tmp` and unlinks any older than 60 seconds (cheap heuristic; repo-local threat model means no need for stricter).

**Upgrade two-pass (Architect C-3, Codex M-1):** T4 splits upgrade into:
- Pass A: dry-run-equivalent plan computation; populate `installed` dict with hashes from staged files (no target writes)
- Pass B: write pending sidecar, atomic batch, finalize

**Exit codes (LRR C-2, v0.9.5 NEW-3 repeat):** `harness state repair` exit codes pinned:
- `0` — recovery completed cleanly OR no work to do
- `1` — partial recovery with quarantine (`.harness/conflicts/` has files); user must inspect
- `2` — catastrophic (recovery itself raised)

**Error message texts (LRR C-1, C-4):** All v0.9.7 user-facing errors are bilingual (Korean primary + English bracketed). Each error message pins the next-action command (e.g., `python3 scripts/harness.py state repair`).

**Idempotency smoke (LRR C-3):** T3 + T4 add a "run `state repair` 3x consecutively" assertion.

**T8 → T11 gate (LRR M-2):** Sequencing reorders T11 to land AFTER T8 surfaces any real upgrade bugs.

**Drift gate UX (LRR M-4):** T9 emits actionable diff in failure message.

## Tasks (T1–T12)

### T1 — `atomic_install_batch`: defer_cleanup + completion sentinel + fsync

**Files:**
- `scripts/lib/atomic_io.py` — extend signature; conditional cleanup; sentinel write with fsync
- `tests/test_atomic_install_batch_defer_cleanup.py` (NEW)

**Changes:**
- Add `defer_cleanup: bool = False` keyword-only param (legacy default False preserved)
- Aborted-path cleanup unchanged
- Success-path:
  ```python
  if not result.aborted:
      if defer_cleanup:
          _write_completion_sentinel(staging_dir)  # fsync-safe
      else:
          _cleanup_staging_and_journal(staging_dir, journal_path)
  return result
  ```
- `_write_completion_sentinel(staging_dir)`:
  ```python
  sentinel_path = staging_dir.parent / (staging_dir.name + ".complete")
  sentinel_tmp = staging_dir.parent / (staging_dir.name + ".complete.tmp")
  fd = os.open(sentinel_tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
  try:
      os.fsync(fd)
  finally:
      os.close(fd)
  os.replace(sentinel_tmp, sentinel_path)
  parent_fd = os.open(sentinel_path.parent, os.O_RDONLY)
  try:
      os.fsync(parent_fd)
  finally:
      os.close(parent_fd)
  ```

**Tests (7 cases):**
1. `defer_cleanup=False` default: success → staging+journal removed (legacy parity)
2. `defer_cleanup=True`, success → staging+journal preserved, sentinel exists, sentinel is 0-byte file
3. `defer_cleanup=True`, success → sentinel.tmp does not linger
4. `defer_cleanup=True`, aborted (induced mid-batch) → no sentinel, journal+staging+.aborted preserved
5. `defer_cleanup=True`, kwarg-only (positional fails with TypeError)
6. Sentinel + simultaneous `.aborted` in staging (corrupted state) → batch result distinguishes via own return value (does NOT trust filesystem state)
7. Crash-during-sentinel-write smoke (write tmp, kill before os.replace) → sentinel.tmp exists, sentinel does NOT; recovery cleanup removes the .tmp

**Acceptance:** all 7 + existing atomic_io tests green.

### T1.5 — `state.file_state` staged-hash refactor

**Files:**
- `scripts/lib/state.py` — add `staged: Path | None = None` param to `file_state`
- `tests/test_state_staged_hash.py` (NEW)

**Changes:**
- `file_state(*, root, target, entry, source, applied_sha256=None, staged=None)`:
  - When `staged is not None` AND `entry.policy == "harness-owned"`: hash `staged` for `sha256`, `installed_sha256`, `current_sha256` fields (single source-of-truth, since staged content IS what `os.replace` will land)
  - When `staged is None` or other policy: legacy destination-hash behavior
- `build_install_state_payload(root, target, entries, ..., staging_map: dict[Path, Path] | None = None)`: new function that composes the manifest dict; accepts optional `entry.path → staged_path` map; passes through to `file_state`
- Existing `write_install_state(...)` becomes a thin wrapper: `build_install_state_payload(...)` + `write_json(installed_manifest_path, payload)`

**Tests (4 cases):**
1. `staged=None` → identical bytes to legacy `file_state` output (golden file)
2. `staged=<path with content X>` for harness-owned → sha256(X) appears in output
3. `staged=<path>` for managed-append → ignored (destination still hashed)
4. `build_install_state_payload(staging_map=...)` → produced dict equals legacy `write_install_state` post-mutation dict (modulo `installed_at` timestamp)

**Acceptance:** new tests green; full pytest baseline unchanged on legacy callers.

### T2 — `install_recovery._recover_pending_manifest` (sentinel + nonce + .tmp cleanup)

**Files:**
- `scripts/lib/install_recovery.py` — new `_recover_pending_manifest` + scan integration + .tmp orphan cleanup
- `tests/test_install_recovery_pending_manifest.py` (NEW)

**Changes:**
- Add `_recover_pending_manifest(target, pending_path) -> RecoveryAction` per PLAN §7.2 REV-5
- `recover_aborted_install` order: (1) scan `installed-manifest.json.pending-*` and dispatch to `_recover_pending_manifest`; (2) clean up `.staging-*.complete.tmp` orphans (older than 60s); (3) legacy `.staging-*`-only scan for any leftover non-pending state
- Pending → staging/journal/sentinel paths derived from suffix after `pending-` (the `runid`)
- Post-finalize sanity inside `_finalize()`: after `os.replace`, re-read final manifest, assert `version == expected_version_from_pending_content`; raise on mismatch (rc=2 path)

**Tests (8 cases):**
1. Sentinel present → finalize; manifest bytes equal pending content
2. `.aborted` marker (no sentinel) → explicit rollback; backups restored; pending removed
3. Journal+staging, no sentinel, no `.aborted` → resume via batch; sentinel appears mid-recovery; finalize fires
4. Journal+staging, resume fails → explicit rollback
5. Pending sidecar only (no journal/staging) → orphan → quarantined to `.harness/conflicts/`; audit row `install.recovery.pending_orphaned` asserted
6. Idempotent: run recovery 3x; first does work, 2nd+3rd are no-ops; rc=0 each time
7. `.complete.tmp` orphan older than 60s → unlinked during scan
8. Two pending sidecars with different runids → each processed independently
9. **Sentinel + `.aborted` coexistence precedence** (Codex NEW-1): `_recover_pending_manifest` prefers `.aborted` over sentinel when both present — outcome is EXPLICIT ROLLBACK, not finalize. Rationale: `.aborted` is an explicit operator/atomic-batch failure signal; a fresh sentinel in same staging would imply concurrent recovery which our threat model forbids. Decision matrix update: check `.aborted` BEFORE sentinel in `_recover_pending_manifest`

**Acceptance:** all 8 + existing install_recovery tests green.

### T3 — `install.py` init wire-in (new phase order)

**Files:**
- `scripts/lib/install.py` — refactor `init` write loop per new phase order
- `tests/test_install_atomic_wire.py` (NEW)

**Changes:** per "REV-2 deltas / New phase order" above. Detailed phase pseudocode:

```python
import secrets, datetime

target.mkdir(parents=True, exist_ok=True)
harness_dir = target / ".harness"
harness_dir.mkdir(parents=True, exist_ok=True)

runid = f"{os.getpid()}-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
staging_dir = harness_dir / f".staging-{runid}"
staging_dir.mkdir(parents=True, exist_ok=True)
journal_path = staging_dir.parent / f"{staging_dir.name}.journal.jsonl"
pending_path = harness_dir / f"installed-manifest.json.pending-{runid}"

# Phase 1: stage harness-owned; managed-append + project-owned handled in-place
staging_map: dict[Path, Path] = {}  # entry.path -> staged path
for entry, source, destination in destinations:
    if entry.policy == "managed-append":
        write_managed_append(source=source, destination=destination, entry=entry)
    elif entry.policy == "project-owned" and destination.exists():
        continue
    else:  # harness-owned
        staged = staging_dir / entry.path
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, staged)
        staging_map[entry.path] = staged

# Phase 2: compose payload from staged hashes
payload = build_install_state_payload(
    root=root, target=target, entries=entries,
    adapters=adapters, profiles=profiles, packs=packs,
    staging_map=staging_map,
)

# Phase 3: write pending sidecar (atomic + fsync)
_atomic_write_json_fsync(pending_path, payload)

# Phase 4: atomic batch
try:
    result = atomic_install_batch(staging_dir, target, journal_path, defer_cleanup=True)
except CrossFilesystemError:
    if not os.environ.get("HARNESS_ALLOW_NONATOMIC_INSTALL"):
        raise InstallFailed(
            "타겟 파일시스템이 atomic rename 을 지원하지 않습니다. "
            "복구 명령: python3 scripts/harness.py state repair  "
            "(또는 HARNESS_ALLOW_NONATOMIC_INSTALL=1 로 비-atomic 강제 — 권장하지 않음) "
            "[Target filesystem does not support atomic rename. "
            "Recover with: python3 scripts/harness.py state repair "
            "or set HARNESS_ALLOW_NONATOMIC_INSTALL=1 to force non-atomic install (not recommended)]"
        )
    _fallback_direct_copy(staging_map)  # log warning; skip pending sidecar dance

if result.aborted:
    raise InstallFailed(
        f"설치 중단됨 (runid={runid}). 복구: python3 scripts/harness.py state repair "
        f"[Install aborted (runid={runid}). Recover with: python3 scripts/harness.py state repair]"
    )

# Phase 5: finalize
sync_roomodes_profile_modes(target=target, profiles=profiles, source_root=root)
final_path = harness_dir / "installed-manifest.json"
os.replace(pending_path, final_path)
# Phase 6: post-finalize verify
with open(final_path, encoding="utf-8") as fh:
    verify = json.load(fh)
expected_version = payload["version"]
if verify.get("version") != expected_version:
    raise InstallFailed(
        f"finalize 검증 실패 (expected={expected_version}, got={verify.get('version')}). "
        f"복구: python3 scripts/harness.py state repair "
        f"[Finalize verification failed; recover with: python3 scripts/harness.py state repair]"
    )

# Phase 7: cleanup (best-effort)
sentinel_path = staging_dir.parent / f"{staging_dir.name}.complete"
sentinel_path.unlink(missing_ok=True)
journal_path.unlink(missing_ok=True)
_rmdir_recursive_quiet(staging_dir)

_stamp_install_trust_origin(root=root, target=target, harness_version=harness_version)
```

**Tests (7 cases):**
1. Happy path: produced `installed-manifest.json` bytes equal what v0.9.6 baseline produces, modulo allowlist fields `{installed_at, source, git_user_email_at_install_sha256}` (pin the allowlist; pin a byte-equality assert on the rest)
2. SIGTERM after Phase 1, before Phase 3 → no pending, no journal; recovery is no-op; user re-runs init → succeeds
3. SIGTERM after Phase 3, before Phase 4 batch starts → pending exists, no journal; recovery quarantines pending (orphan path); rc=1
4. SIGTERM mid-batch (Phase 4) → pending+journal+staging present, no sentinel; `state repair` resumes; finalize; rc=0
5. SIGTERM after sentinel (between Phase 4 and Phase 5) → `state repair` finalizes; rc=0
6. SIGTERM after `os.replace` (Phase 5), before cleanup → manifest is correct; recovery cleans up; rc=0
7. Idempotency: run `state repair` 3x after each scenario; all rc=0 (or expected rc=1 for orphan); state invariant after first repair

**Acceptance:** all 7 + existing init tests green.

### T4 — `upgrade.py` two-pass wire-in

**Files:**
- `scripts/lib/upgrade.py` — split harness-owned path into Pass A (plan) + Pass B (stage+finalize)
- `tests/test_upgrade_atomic_wire.py` (NEW)

**Changes:**
- Pass A: refactor existing in-flight `installed` dict mutations to populate a `plan: UpgradePlan` namedtuple (entries, conflict_decisions, file_state per entry from staging hashes, retired managed-appends). NO target writes in Pass A.
- Pass B: write pending sidecar from `plan.installed`, atomic batch on staged files, finalize, verify.
- Conflict copies (lines 738-740, 791-794) continue in-place — documented out-of-scope in CHANGELOG.
- Managed-append continues in-place (per PLAN §4).
- Skip-upgrade guard (T6) runs in Pass A BEFORE any state composition.

**Tests (5 cases):**
1. v0.9.6 → v0.9.7 in-place: same outcome (manifest bytes-equal modulo allowlist) with/without crash
2. SIGTERM mid-upgrade at each phase boundary → `state repair` recovers to a CONSISTENT version FOR HARNESS-OWNED FILES + MANIFEST (manifest version = either v0.9.6 fully OR v0.9.7 fully; harness-owned files match the recovered manifest's hashes; managed-append + conflict-copy files are best-effort per scope-out documented in CHANGELOG and out of this consistency claim). Assert exact recovered `version` value per scenario
3. Idempotency: `state repair` 3x after upgrade abort
4. Two-pass dry-run: Pass A's `plan.installed` payload bit-equal to Pass B's pending-sidecar content
5. v0.9.4 → v0.9.7 → blocked by skip-upgrade guard BEFORE any Pass A computation (test asserts no `.staging-*` created)

**Acceptance:** all 5 + existing upgrade tests green.

### T5 — `harness check` staging detection (age-gated, dedupe'd)

**Files:**
- `scripts/lib/check.py` — extend with stale-staging detection using `install_recovery._is_stale`
- `tests/test_check_staging_detection.py` (NEW)

**Changes:**
- New helper `_scan_stale_staging_dirs(target) -> list[Path]`:
  - Iterate `target/.harness/.staging-*`
  - Require sibling `.staging-<name>.journal.jsonl`
  - AND `install_recovery._is_stale(staging_dir) is True` (reuse existing 600s threshold or `.aborted` marker)
- Warning row text (bilingual): `중단된 설치 감지 (runid=<name>, age=<sec>s). 복구: python3 scripts/harness.py state repair [Aborted install detected; recover with state repair]`
- One warning row per stale staging dir (per LRR M-3 — needs identifying info)

**Tests (5):**
1. No staging → no warning
2. Fresh staging (age < 600s, no `.aborted`) → no warning (live-install false-positive guard per Hawk M-1)
3. Stale staging + journal → warning emitted with runid + age
4. `.aborted` marker present → warning regardless of age
5. Multiple stale dirs → one warning per dir; output has all runids

**Acceptance:** all 5 tests green.

### T6 — Skip-upgrade guard with bilingual error + missing-version safety

**Files:**
- `scripts/lib/upgrade.py` — guard in Pass A
- `tests/test_skip_upgrade_guard.py` (NEW)

**Changes:**
```python
prior_version_raw = prior_state.get("version") or prior_state.get("harness_version") or ""
prior_version = prior_version_raw.lstrip("v")
target_version_raw = harness_version.lstrip("v")

if prior_version in {"", "unknown"}:
    # Defensive: if state is corrupted, refuse rather than silent bypass (Codex MINOR-3)
    raise UpgradeRefused(
        "이전 설치 버전을 확인할 수 없습니다. python3 scripts/harness.py state show 로 상태 점검 후 진행 "
        "[Cannot determine prior install version; run state show to inspect]"
    )

if prior_version == "0.9.4" and _semver_ge(target_version_raw, "0.9.7"):
    if not os.environ.get("HARNESS_ALLOW_SKIP_UPGRADE"):
        raise UpgradeRefused(
            "v0.9.4 → v0.9.7 직접 업그레이드는 지원되지 않습니다. "
            "먼저 v0.9.5 로 업그레이드 후 다시 시도하세요. "
            "Override (권장하지 않음): HARNESS_ALLOW_SKIP_UPGRADE=1 "
            "[Skip-upgrade from v0.9.4 directly to v0.9.7 unsupported. "
            "Upgrade to v0.9.5 first. Override: HARNESS_ALLOW_SKIP_UPGRADE=1]"
        )
```

**Tests (5):**
1. v0.9.4 → v0.9.7 no env → UpgradeRefused raised; error message contains both Korean + English + override hint
2. v0.9.4 → v0.9.7 with `HARNESS_ALLOW_SKIP_UPGRADE=1` → proceeds (downstream may fail; guard doesn't block)
3. v0.9.5 → v0.9.7 → no guard
4. v0.9.6 → v0.9.7 → no guard
5. Missing/empty `version` → UpgradeRefused (defensive)

**Acceptance:** all 5 green.

### T7 — Fixture builder normalization + determinism + non-zero init fail-fast

**Files:**
- `scripts/build_v094_fixture.py` — `EXCLUDE_NAMES` minus `.harness`; `_normalize_v094_install_state`; `HARNESS_FIXED_NOW_ISO` env; determinism self-check; fail on `harness init` non-zero
- `tests/test_fixture_determinism.py` (NEW)
- `tests/fixtures/v094-clean.tar.gz` + `.sha256` (REGENERATED)
- `tests/fixtures/v094-with-workaround.tar.gz` + `.sha256` (REGENERATED)

**Changes per PLAN §7.3 (REV-3 schema-correct)** plus:
- `run_v094_init`: change "WARNING but continue" to `raise FixtureBuildError` on non-zero exit (Hawk M-7)
- `_normalize_v094_install_state`: assert post-normalize file count matches expected v0.9.4 manifest count (defensive)
- Manifest_sha256 handling: v0.9.4's `manifest_sha256` is computed from the SOURCE manifest YAML (not the installed payload) — verified via `git show v0.9.4:scripts/lib/state.py` calls to `manifest_sha256(root)`. Source manifest content is deterministic at v0.9.4 tag → no recompute needed. (Architect M-3 closed: this is a documented fact, not a hand-wave.)
- Determinism self-check at end of `main()`: build twice in separate temp dirs, assert sha256 equality before writing pinned files

**Tests (3):**
1. `test_fixture_determinism.py` — script in tempdir twice, sha256 equal
2. Forced `harness init` non-zero (e.g., bad env) → script raises FixtureBuildError
3. Pinned `.sha256` matches tarball (existing check, extended)

**Acceptance:** 3 + existing fixture tests green.

### T8 — Real-fixture upgrade tests + bug triage gate

**Files:**
- `tests/test_upgrade_from_v094_clean.py` — delete `_seed_v094_manifest`
- `tests/test_upgrade_from_v094_with_workaround.py` — delete `_seed_v094_manifest` + `_seed_v094_full_manifest`
- Both: assertion `assert (extracted/".harness"/"installed-manifest.json").exists()` after extraction
- `.planning/phases/02f-v0.9.6-hotfix/evidence/T8-triage.md` (NEW — created when running tests; documents any surfaced bugs)

**Changes:** delete helpers + reorganize fixtures-setup; tests now consume tarball `.harness/` directly.

**Gate:** T11 (CHANGELOG + tag) is BLOCKED until `T8-triage.md` is filled with one of:
- "All tests green; no bugs surfaced" → proceed
- "Bugs surfaced: <list>; fixed in T4 commit <sha>" → proceed
- "Bugs surfaced: <list>; deferred to v0.9.8 as xfail with TODO at <test>" → proceed + CHANGELOG mentions

**Acceptance:** triage file exists and decision is recorded.

### T9 — KNOWN_FAILING_TESTS.md (node-id set) + drift gate with actionable UX

**Files:**
- `tests/KNOWN_FAILING_TESTS.md` (NEW — populated from CLEAN container/pinned-venv run, NOT local dev)
- `tests/test_known_failures_drift.py` (NEW)
- `Makefile` or `scripts/refresh_known_failures.sh` (NEW) — explicit seeding command

**Changes:**
- KNOWN_FAILING_TESTS.md header documents exact pytest invocation + venv:
  ```
  # Known Pre-Existing Test Failures (as of v0.9.7)
  # Last verified: 2026-05-21
  # Generated by: scripts/refresh_known_failures.sh
  # Environment: Python 3.14 (homebrew), pinned dev requirements
  ```
- `.harness-test-cache/` added to `.gitignore` (junit cache NOT committed per Codex MAJOR-4)
- `scripts/refresh_known_failures.sh`: runs full pytest with `--junitxml=.harness-test-cache/junit.xml`, then a parser writes the node-id set into KNOWN_FAILING_TESTS.md
- Drift gate test:
  - Read `.harness-test-cache/junit.xml`; skip with actionable message if missing: `"Run scripts/refresh_known_failures.sh first"`
  - Cache freshness check (Hawk M-6 + Codex REV-2 NEW-2): junit.xml mtime must be newer than newest mtime in `scripts/` and `tests/`. **STALE = FAIL** by default (rc=1) with message "Cache stale; run scripts/refresh_known_failures.sh". Bypass: `HARNESS_KNOWN_FAILURES_ALLOW_STALE=1` (for emergency local dev only).
  - Compare current failing-set vs KNOWN; on diff, raise with actionable message:
    ```
    "Known-failures drift detected.
     NEW failures (add to KNOWN_FAILING_TESTS.md or fix):
       - <node-id-1>
     FIXED knowns (REMOVE from KNOWN_FAILING_TESTS.md):
       - <node-id-2>
     Refresh: scripts/refresh_known_failures.sh"
    ```

**Tests (3):**
1. Missing cache → drift test skipped with seeding instruction
2. Cache matches known set → drift test green
3. Cache differs from known set → drift test red with actionable diff message

**Acceptance:** 3 tests + `.gitignore` updated; seed script committed.

### T10 — USER_MANUAL recovery section + manual.html regen

**Files:**
- `docs/USER_MANUAL.md` — new subsection per PLAN §7.6 + success/failure example output blocks (LRR M-5)
- `docs/site/manual.html` — regenerated

**Doc body additions:**
- "성공 출력 예시": paste real smoke run output for sentinel-finalize case
- "실패 출력 예시": paste real output for orphan-pending case + interpretation note ("rc=1 일 때 `.harness/conflicts/` 확인")
- "Exit codes" subsection: 0 / 1 / 2 table

**Acceptance:** rendered html shows section; doctest passes; example outputs match smoke results.

### T11 — CHANGELOG v0.9.7 + version bumps (full enumeration)

**Files (enumerated per Codex MINOR-4):**
- `CHANGELOG.md` — v0.9.7 entry
- `scripts/lib/version.py` (if version constant; else `VERSION` file)
- `README.md:225` — version ref
- `docs/site/index.html:6-7` — version ref
- `docs/site/use-cases.html:18` — version ref
- `docs/USER_MANUAL.md:1` — version ref header
- Other locations found by `git grep -nE 'v?0\.9\.6'` at impl time (re-run; allow only intentional historical references in CHANGELOG)

**CHANGELOG entry text** (matches PLAN §2.10 + REV-2 deltas):
```markdown
## v0.9.7 (2026-05-21)

### Hardening
- harness init/upgrade harness-owned file replacement now uses resumable per-file
  atomic staging with a pending-manifest sidecar, completion sentinel, and runid
  collision-resistant naming (`scripts/lib/atomic_io.py` + `install_recovery.py`).
  Crashes mid-install (SIGTERM, power loss, manual abort) are recoverable via
  `harness state repair`. Managed-append and composed write_text_file updates
  remain in-place and are deferred to a later release.
- Skip-upgrade guard refuses v0.9.4 → v0.9.7 with an actionable bilingual message
  (override: `HARNESS_ALLOW_SKIP_UPGRADE=1`).
- `harness state repair` exit codes: 0 (clean / no-op), 1 (quarantined partial),
  2 (catastrophic).
- `harness check` now warns when a stale aborted-install staging directory is
  detected (age ≥ 600s OR `.aborted` marker).
- Test fixture: v0.9.4 tarball includes deterministic `.harness/` state; upgrade
  tests now exercise real upgrade paths (synthetic seeders removed).
- `tests/KNOWN_FAILING_TESTS.md` enumerates pre-existing failing node-ids; CI
  gate via `tests/test_known_failures_drift.py`.

### Docs
- USER_MANUAL: new "중단된 설치 복구" subsection with success/failure example output.

### Deferred to v0.9.8
- Managed-append + `write_text_file` content-mutating atomic staging
- Pre-existing test failure triage (76 tests)
- BUG-4 release-check rc=0
- Symlink-aware staging; Windows support
```

**Acceptance:** acceptance gate is `git grep -nE 'v?0\.9\.6' -- ':!CHANGELOG.md'` returns no unintentional matches; version constant updated everywhere; doctest / link check passes.

### T12 — Pre-release smoke

**Files:**
- `.planning/phases/02f-v0.9.6-hotfix/evidence/smoke-2026-05-21.md` (NEW)

**Scenarios (all must pass and outputs pasted to evidence file):**
1. Fresh init → verify final manifest + audit row
2. Fresh init → SIGTERM mid-batch → `state repair` 3x → final manifest correct, rc=0
3. Fresh init → SIGTERM post-batch pre-stamp → `state repair` → finalize, rc=0
4. v0.9.6 → v0.9.7 upgrade → verify version field
5. v0.9.6 → v0.9.7 upgrade → SIGTERM → `state repair` → recovers to consistent version
6. v0.9.4 → v0.9.7 → refused with bilingual message
7. Full pytest run with `--junitxml=.harness-test-cache/junit.xml` → drift gate green
8. `harness check` with stale staging → warning emitted with runid

**Acceptance:** all 8 scenarios pasted to evidence; release proceeds only on green.

## Sequencing + dependencies

```
T1 ──┬──→ T2 ──┬──→ T3 ──┬──→ T4 ──┬──→ T8 ──┬──→ T11 ──→ T12
T1.5 ┘        │         │         │        │
              T5 ───────┘         │        │
              T6 ─────────────────┘        │
              T7 ─────────────────→ T8     │
              T9 ────────────────────────  │
              T10 ───────────────────────  │
```

Critical path: T1 → T1.5 → T2 → T3 → T4 → T8 (triage) → T11 → T12.

## Done definition

- T1-T12 commits land on develop
- Full pytest: failing-set ⊆ KNOWN_FAILING_TESTS.md (exact match via drift gate)
- 8 smoke scenarios in T12 green; evidence file populated
- T8 triage decision recorded
- Codex CLI + Opus 3-panel review on full diff
- Signed tag `v0.9.7` ready (release pending user approval per workflow)

## Risks (impl-specific REV-2)

| Risk | Mitigation |
|---|---|
| T1.5 `file_state(staged=)` changes hash semantics → breaks chain-hash | Add explicit golden test that v0.9.7 produces same chain-hash as v0.9.6 for identical content; if diverges, investigate before T3 |
| Pass A / Pass B upgrade payload divergence (T4) | T4 test #4 asserts dry-run vs real bytes-equal |
| `fsync(parent_dir_fd)` macOS APFS behavior — some kernels noop | Document; macOS APFS is internal-only target; accept best-effort |
| `runid` IS suffix sortable; sort order matters for recovery? | No — recovery scans all matching pending-* regardless of order; runid is for uniqueness only |
| T8 surfaces real bug ≥ T4 wire-in | Triage file gates T11; bug becomes either T4 fix or v0.9.8 |
| KNOWN_FAILING_TESTS.md initial seed contains operator-only failures | Seed script must be run on clean checkout; document in script header |

## Notes for adversarial review

- Confirm phase order (stage → compose → pending → batch → finalize) actually preserves "no target write before pending durable"
- Confirm `file_state(staged=)` covers all the chain-hash inputs needed
- Confirm two-pass upgrade plan equals single-pass output bit-by-bit
- Confirm runid format defeats pid collision AND is filesystem-safe (no `:` etc)
- Confirm fsync calls land on every durable-write path
- Confirm exit code 1 fires for quarantine; not 0
- Confirm bilingual error messages render correctly in non-UTF-8 terminals (best-effort note)
