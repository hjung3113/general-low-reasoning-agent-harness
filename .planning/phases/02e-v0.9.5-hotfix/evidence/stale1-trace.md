# STALE-1 Trace Report: init/upgrade planned_writes desync

**Date:** 2026-05-21  
**Investigator:** T1 sub-agent (Sonnet)  
**Bug:** `harness init` reports N planned writes; immediately running `harness upgrade --dry-run` reports N-27  
**Plan ref:** `/tmp/v095-PLAN.md` REV-2 §3.1; `/tmp/v095-IMPL.md` REV-4 T1  
**Architect hypothesis (C-3):** install.py:122-133 doesn't call `file_state` for harness-owned entries — TESTED and REFUTED (see §4)

---

## 1. Methodology

Fresh smoke target created:

```
mkdir /tmp/stale1-trace
cd /tmp/stale1-trace && git init -q && git commit --allow-empty -m i -q
```

Baseline init run (no instrumentation needed — analysis is code-reading + Python REPL simulation):

```
HARNESS_ADVANCED=1 HARNESS_ALLOW_UNSIGNED_DEV=1 \
  python3 scripts/harness.py init --target /tmp/stale1-trace --adapters none
# → "129 planned writes"

HARNESS_ADVANCED=1 HARNESS_ALLOW_UNSIGNED_DEV=1 \
  python3 scripts/harness.py upgrade --target /tmp/stale1-trace --dry-run
# → planned_writes=102
```

Delta: 129 − 102 = **27**.

The v0.9.4 smoke report (STALE-1) showed 94/67 (delta=27). The delta is identical; the absolute values are smaller because BUG-1 (35 missing `scripts/lib/*.py` manifest entries) reduces both counters by 35 symmetrically. Once BUG-1 is fixed the numbers become 129/102.

The investigation proceeded by:
1. Reading `scripts/lib/install.py`, `scripts/lib/upgrade.py`, `scripts/lib/state.py`, `scripts/lib/manifest.py` to understand the counter logic
2. Simulating the selection and counter logic via Python REPL against the live installed manifest at `/tmp/stale1-trace/.harness/installed-manifest.json`
3. Verifying the architect's hypothesis (C-3) against the actual install state
4. Confirming an additional finding (secondary bug) about upgrade always rewriting harness-owned files

---

## 2. Per-entry-class delta table

Scope: `adapters=none (empty set), profiles=generic, packs=workflow-core` — the same scope stored by init and read back by upgrade.

| Class | Count | Policy | Install counts? | Upgrade counts? | Root cause (file:line) |
|---|---|---|---|---|---|
| project-owned entries | 25 | `project-owned` | YES | NO | `upgrade.py:583–585`: `if entry.policy not in {"harness-owned","managed","managed-append"}: continue` — project-owned is always skipped |
| managed-append, no content change | 2 | `managed-append` | YES | NO | `upgrade.py:607–608`: `if result.updated_text is not None: planned_writes += 1` — only counts when block needs updating |
| **TOTAL DELTA** | **27** | | | | |

### How each counter works

**install.py:118** (dry-run path):
```python
print(f"planned_writes={len(destinations)}")
```
where `destinations` (lines 93–101) is:
```python
destinations = [
    (entry, source_path(root, entry), destination_path(target, entry))
    for entry in entries
    if entry.policy != "exclude"
]
```
This includes **all non-exclude policies**: `harness-owned` (102) + `managed-append` (2) + `project-owned` (25) = **129**.

Note: the actual write loop (lines 122–130) correctly skips `project-owned` entries where the destination already exists, and calls `write_managed_append` for managed-append. The counter is semantically incorrect — it over-reports.

**upgrade.py:579** — counter is initialized to 0 and incremented only for actual writes:

- Line 583–585: `if entry.policy not in {"harness-owned", "managed", "managed-append"}: continue` — project-owned entries never reach the increment
- Line 607–608: managed-append increments only when `result.updated_text is not None`
- Line 630: harness-owned/managed increments unconditionally after passing the conflict check

Result: **102** (all 102 harness-owned entries pass the conflict check after fresh init, because sha256 matches).

---

## 3. Named root cause

**Root cause:** `install.py:118` computes `planned_writes = len(destinations)` where `destinations` is ALL non-exclude entries, while `upgrade.py:579–638` computes `planned_writes` as an incremental counter that excludes `project-owned` entries entirely and skips `managed-append` entries with no content change.

The two counters have **different semantics** and are never expected to agree:
- install's counter means "files touched in this operation including user scaffold files"
- upgrade's counter means "harness-managed files that will be overwritten"

This semantic mismatch is the STALE-1 root cause. There is no code bug in the write logic itself — files are written correctly by both commands. The mismatch is purely in what the `planned_writes` output line reports.

---

## 4. Architect hypothesis C-3: REFUTED

Architect C-3 hypothesized that `install.py:122-133` does not call `file_state(...)` for harness-owned entries where destination exists, while `upgrade.py:633-638` does — causing upgrade to "see" those entries as needing writes.

**Verification:** `write_install_state` (state.py:223–303) iterates ALL selected entries regardless of policy and records `file_state` for each. After fresh init, the installed manifest at `/tmp/stale1-trace/.harness/installed-manifest.json` contains:

```
harness-owned:   102 entries with sha256
managed-append:    2 entries with sha256
project-owned:    25 entries with sha256
```

All 129 entries have `sha256` recorded. The `old_hash` check in upgrade.py:620 (`installed_paths.get(str(entry.path), {}).get("sha256")`) returns a value for all installed entries. There are zero entries where `not old_hash` is true for a fresh install.

The hypothesis is incorrect. The mismatch is in counter semantics, not in file_state recording.

---

## 5. Secondary finding: upgrade always rewrites harness-owned even when source unchanged

After fresh init, `upgrade --dry-run` reports `planned_writes=102` even though all 102 harness-owned files were just written by init. This is because `upgrade.py:619–638` checks:

```python
if destination.exists() and not force:
    old_hash = installed_paths.get(str(entry.path), {}).get("sha256")
    current_hash = file_hash(destination)
    if not old_hash or current_hash != old_hash:
        conflicts += 1
        ...
        continue

planned_writes += 1   # reached even when hashes match
```

It compares `old_hash` (on-disk sha256 at install time) vs `current_hash` (on-disk sha256 now). When they match, it does NOT conflict — but still counts as a planned write and overwrites the file. There is NO check against `source_sha256` (hash of the source file). So even when the source has not changed since init, upgrade plans to re-write all 102 files.

T5 goal requires `planned_writes=0` after fresh init. This requires adding a source-sha256 comparison.

---

## 6. Proposed fix shape for T5

**Fix: add source sha256 unchanged check in `upgrade.py` (approx. 5 LOC)**

In `upgrade.py` around line 619, after retrieving `old_hash` and `current_hash`, add:

```python
# T5-fix: skip write if source hasn't changed since install
new_hash = file_hash(source)
installed_info = installed_paths.get(str(entry.path), {})
installed_src_sha = installed_info.get("source_sha256") or installed_info.get("installed_sha256")
if installed_src_sha and installed_src_sha == new_hash:
    # Source unchanged since install — no write needed
    continue
```

This skips the `planned_writes += 1` increment when the source file hash matches what was recorded at install time. For the fresh-init case, all 102 harness-owned entries would be skipped, yielding `planned_writes=0`.

**Verification:** After fresh init, `installed_info.get("source_sha256")` returns the source sha256 recorded by `write_install_state` (state.py:248, 257). All 102 harness-owned source files are unchanged, so all 102 would be skipped. Confirmed via Python simulation: `skippable=102, must_write=0`.

**Option comparison:**

| Option | Description | LOC | Risk |
|---|---|---|---|
| A (recommended) | Add `source_sha256` unchanged check in upgrade.py before `planned_writes += 1` | ~5 | Behavior change: upgrade no longer overwrites unchanged harness-owned files. For idempotent upgrades this is correct. |
| B | Align install.py counter: subtract project-owned + managed-append-no-change from `len(destinations)` | ~10 | Cosmetic only — doesn't fix T5 goal of planned_writes=0 |
| C | Extract shared predicate `should_write(entry, installed_info, source_sha) -> bool` to `lib/manifest.py` | ~30 | Cleanest API; defers the source-sha check to the new predicate; both init and upgrade use it |

**Recommendation: Option A** for T5 (minimal, targeted, passes the stated test). Option C is the right long-term refactor if further policy logic is needed.

**Note on `install.py` counter:** `install.py:118` over-reporting is a separate cosmetic issue. For a fresh empty target, all 129 entries ARE written, so `len(destinations)=129` is technically accurate for init (project-owned files DO get written on fresh install). The semantic mismatch only matters if someone compares the two numbers, or if `upgrade --dry-run` is used as an idempotency probe. A comment at install.py:118 explaining the over-count would prevent future confusion, but no code change is needed.

---

## 7. Manifest note

The v0.9.4 smoke values (init=94, upgrade=67) are explained as follows:
- BUG-1 (35 missing `scripts/lib/*.py` manifest entries) reduces both counters by 35
- 94 = 129 − 35; 67 = 102 − 35; delta = 27 in both cases

Once BUG-1 (T3) is applied, the baseline becomes 129/102/delta=27. After T5 fix, baseline becomes 129/0/delta=129 (upgrade reports 0 planned writes on same-version no-source-change target).

---

## 8. Cleanup note

`/tmp/stale1-trace` left in place for reference. Remove with `rm -rf /tmp/stale1-trace` when no longer needed.
