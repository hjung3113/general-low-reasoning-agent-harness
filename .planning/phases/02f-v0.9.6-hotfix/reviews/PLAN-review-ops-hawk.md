# PLAN review — Ops & Supply-Chain Hawk lens

Reviewer: Opus 4.7 (1M) — Ops & Supply-Chain Hawk
Target: `.planning/phases/02f-v0.9.6-hotfix/plans/PLAN.md` @ DRAFT
Repo HEAD: `528d2c8` (develop = main)
Date: 2026-05-21
Scope: release process, fixture/CI supply chain, atomic-install operational reality, cross-OS, audit-chain implications, version pins.

Verdict: PLAN is sound in intent but underspecifies several supply-chain and ops-time invariants that will bite during T3/T5/T7. 3 CRITICAL, 6 MAJOR, 4 MINOR.

---

## CRITICAL

### C1 — Release runner workaround is undocumented in PLAN; v0.9.6 will hit the same wall (PLAN.md §7, §8)
Evidence:
- `scripts/release.py:64-67` builds `env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}`; there is **no built-in PYTHONPATH plumbing or interpreter pinning**. v0.9.0 memory note `project_v090_released` explicitly records that release.py needed a `PYTHONPATH + homebrew python3.14` workaround on the maintainer machine, and v0.9.4/0.9.5 memories repeat this pattern.
- `scripts/release_smoke_test.py:772-776, 1147-1151` only patches `PYTHONPATH` for the autopilot guard subprocess — NOT for `release.py` itself.
- PLAN §7 "Release" is one word. §8 "Done definition" says "Signed tag v0.9.6 pushed" with no ops note.

Impact: Release operator will rediscover the same environment workaround under time pressure (no rollback once a tag is pushed wrong). Hotfix should at minimum (a) document the exact invocation in PLAN §7 / done definition, OR (b) bake the PYTHONPATH into `release.py` so the next release is hermetic. PLAN does neither.

Ask: Add explicit "Release runner prerequisites" subsection (interpreter, PYTHONPATH, env) AND consider an in-scope micro-task to fix `release.py` env construction (3-line change). Without this, v0.9.6 will repeat v0.9.5 release toil.

### C2 — State stamping order vs atomic batch is **circular**; spec does not resolve it (PLAN.md §3.2, line 58)
Evidence:
- PLAN §3.2 line 58: "The state stamp (`installed-manifest.json` write) remains LAST after batch commits."
- But `installed-manifest.json` lives at `$TARGET/.harness/installed-manifest.json` — i.e. **inside** the target tree that the batch is supposed to populate. `scripts/lib/install.py:307` calls `write_copy(source, destination)` for harness-owned files in a loop; the manifest write is at `scripts/lib/install.py:199` via `atomic_write_text`.
- `atomic_io.atomic_install_batch` (lines 276–470) renames everything from `staging_dir` into `target`. If the manifest is staged it gets renamed in the batch; if it is excluded, then the batch result must finalize BEFORE manifest stamping — but the manifest stamping itself is a separate `atomic_write_text` outside the journal, so a crash between "batch complete" and "manifest written" leaves files on disk with stale manifest count (which is exactly the v0.9.4 BUG-1 we are trying to prevent recurring).

Impact: As written, T5 ("install.py routes through staging + atomic_install_batch") has two equally bad interpretations:
- Include the manifest in the batch → success_criteria 2 ("state stamp remains LAST") is violated.
- Exclude it → crash window reintroduced; STALE-3 / STALE-4-class bugs return on signal.

Ask: PLAN must specify the **journal-as-state-anchor** contract:
1. The journal (`*.journal.jsonl`) IS the authoritative completion record during a batch.
2. Manifest stamping is the **second phase** with its own atomic_write_text; on crash between phases, `recover_aborted_install` MUST detect "journal complete + no .aborted + no manifest update" and re-emit the stamp.
Spec this explicitly in §3.2 before T5 starts, or T5 will ship a regression hole.

### C3 — Fixture rebuild `.sha256` rotation has no CI provenance gate (PLAN.md §3.3, §6 Q4; scripts/build_v094_fixture.py:37; tests/fixtures/*.sha256)
Evidence:
- `scripts/build_v094_fixture.py:37`: `EXCLUDE_NAMES = {"__pycache__", ".git", ".pytest_cache", ".DS_Store", ".harness"}`. Removing `.harness` changes contents → tarball sha256 changes deterministically.
- Pinned hashes today: `v094-clean.tar.gz.sha256` = `5d0e3122...` and `v094-with-workaround.tar.gz.sha256` = `9ee297ff...`.
- `tests/fixtures/README.md:45-46` documents `shasum -a 256 -c` verification — i.e. CI/tests treat `.sha256` as trust anchor.
- PLAN §6 Q4 "default recommendation: Update pinned `.sha256` in same commit; CI rebuilds fixture from script anyway." → **two contradictory truths**: either CI rebuilds (then the pinned hash is what CI *publishes*, which is fine), OR CI verifies (then a maintainer running `build_v094_fixture.py` on a different machine MUST produce byte-identical bytes).

Reproducibility risk: the builder pins mtime=0, uid/gid=0, sorts entries — but `.harness/` contents are produced by **running `harness init` against the v0.9.4 source tree** (see `build_v094_fixture.py:213` workflow), which timestamps `installed-manifest.json` via current install code, may include `audit.log` with chain hashes that depend on installer version. **Two different reviewers building the fixture on different days will produce different installed-manifest.json contents → different tarball sha256.**

Impact: pinned `.sha256` will diverge between local-rebuild and CI-rebuild, breaking the supply-chain integrity claim. T3 success criterion 3 ("Tarball sha256 still deterministic across runs") is not achievable without **deterministic install** (which is itself a v0.9.6 goal — the very atomic wire-in being added). Chicken-and-egg.

Ask: PLAN §3.3 must add a deterministic-install pre-step OR pin the *content* of the staged `.harness/` (e.g. ship a captured snapshot) rather than running install live. Otherwise T3 will land flaky and CI will fight every reviewer rebuild.

---

## MAJOR

### M1 — Cross-OS scope is silently "POSIX only"; PLAN does not say so (PLAN.md §5 risks; atomic_io.py:285)
`atomic_io.py:285-289`: "Each os.replace call is atomic on POSIX (same filesystem). The batch as a whole is not atomic". Windows NTFS `os.replace` semantics differ (e.g. open-file replace on Windows raises). PLAN §5 risk table never mentions Windows; success criterion 2 ("Kill-mid-install... leaves staging dir + journal intact") is POSIX-only. v0.9.5 memory notes `internal-only threat model` but this is OS scope, not threat scope.

Ask: Add explicit "Out of scope: Windows" to §4, OR add Windows row to risk table with explicit deferral. Internal tool ≠ POSIX-only by default; a Windows dev hitting this gets cryptic failures.

### M2 — Symlinks in source tree not handled by atomic batch (atomic_io.py walk; install.py:271; PLAN §3.2)
- `atomic_io.atomic_install_batch` walks `staging_dir` via `os.walk(...)` collecting files only (atomic_io.py:362-366). Symlinks staged into `staging_dir` become regular file copies via `shutil.copyfile` in the *current* `install.py:307`, BUT the existing code at `install.py:271` already special-cases `destination.is_symlink()` — meaning the current code is symlink-aware in the destination check.
- After T5, when writes get staged, the staging step must decide: copy symlink target (deref) or recreate symlink (preserve). `atomic_io` has no `os.symlink` handling and there is `# pragma: no cover` paths only for symlink **rejection** (lines 144-161).

Impact: `.agents/` and packs directories may contain symlinks (per memory notes about adapter packs). After T5 wires through atomic_install_batch, behavior changes silently from "copyfile derefs" to undefined. T5 must explicitly state: "symlinks in source → ___ in destination" and add a test.

Ask: Add success criterion or scope note. At minimum: "atomic_install_batch staging step preserves source-tree symlink topology" (or explicit reject + fallback).

### M3 — Signal handling absent; SC2 "kill-mid-install" is testable but not implementable as-written (PLAN.md §2 criterion 2; install.py)
Grep shows **no `signal.` or `atexit` handlers** in `install.py`, `upgrade.py`, or `install_recovery.py`. Success criterion 2 says SIGTERM during the batch "leaves staging dir + journal intact" — this happens *for free* with `atomic_install_batch` because the staging dir is on disk. BUT: subsequent `state repair` invocation relies on `_find_staging_dirs` detecting `.staging-*` directories (`install_recovery.py:87-96`), and **the `.aborted` sentinel is only written when `os.replace` raises** (lines 434-441), NOT on signal.

Gap: SIGKILL/SIGTERM between renames leaves staging dir without sentinel → `_is_stale` (line 105) only flags it via mtime threshold. PLAN §3.2 says "ensure `harness state repair` invokes it" but a fresh-killed install will not be detected as stale by mtime for whatever the threshold is.

Ask: PLAN must specify (a) signal handler that writes `.aborted` on SIGTERM, OR (b) make `_is_stale` recognize "journal exists + staging not empty" as stale regardless of mtime. The current spec produces a recovery hole that the T6 e2e test will hit on first run.

### M4 — Version-pinned smoke assertions will need updating; PLAN doesn't list which (PLAN.md §3.4, success criterion 7)
`scripts/release_smoke_test.py` has hardcoded `sys.executable` invocations of fixture-paths (lines 2289, 2299–2303, 2485, 2505). It does not appear to embed v0.9.4/v0.9.5 version strings directly, but `tests/conftest.py:40-41` pins fixture filenames, and CHANGELOG drives release-check assertions. After T3 changes fixture sha256 + after T4 rewrites synthetic-seed tests, **release_smoke_test.py needs re-baselining** but PLAN has no task for it.

Ask: Add explicit T-task "audit release_smoke_test.py + smoke_lifecycle.py for v0.9.4/v0.9.5 pins; rebaseline as part of T7."

### M5 — Audit chain criterion 5 may be unsatisfiable (PLAN.md §2 criterion 5)
"v0.9.5 → v0.9.6 in-place upgrade preserves all v0.9.5 state; chain extends (not re-anchors); audit row present."
- `upgrade.py:597-628` only emits `release.trust.rechained` when chain hash **changes** (delta detection). If v0.9.6 ships zero new lib files and zero manifest delta (entirely possible for a small hotfix where install/upgrade changes don't add modules), `installed_files_chain_hash` is byte-identical → `_emit_rechain_audit` writes nothing → **no audit row**.
- Criterion 5 says "audit row present" unconditionally.

Impact: A "clean" v0.9.6 (T2 fixes upgrade.py but adds no files; T5 wires atomic but adds zero modules) would FAIL criterion 5 as written.

Ask: Reword criterion 5 to: "Audit row present IFF chain delta exists; otherwise an explicit `release.upgrade.noop` row OR documented absence." Or guarantee a manifest delta (e.g. version-string-only stamp) so chain always advances on every release.

### M6 — CHANGELOG migration discipline missing from PLAN (PLAN.md §8)
PLAN §8 says "CHANGELOG v0.9.6 entry merged" but does not require closing the **deferred items** from v0.9.5's "Known limitations" section (CHANGELOG.md:65). Auditability requires that each deferred item gets a "closes" reference. Without it, in 3 releases nobody will be able to reconstruct which deferred items resolved when.

Ask: Add to §8: "v0.9.6 CHANGELOG explicitly notes each v0.9.5 deferred item being closed (with code-path reference)." Mechanical, but currently absent.

---

## MINOR

### m1 — PLAN §5 "Atomic batch leaves staging on signal kill but state_repair not auto-invoked" lists this as Medium/Medium but offers only "harness check could detect" — vague. Make `check` detection a concrete success criterion (currently aspirational).

### m2 — PLAN §6 Q3 default "Default-on" for atomic wire-in is risky given M1 (Windows) + M3 (signals). Consider opt-in env for v0.9.6 + telemetry, default-on in v0.9.7. (PLAN itself flags this in §5 risk row 1 then overrides in Q3 — internal inconsistency.)

### m3 — `install_recovery._is_stale` (install_recovery.py:105-110) uses an mtime threshold not visible in this review (line 110+ uses `mtime`); PLAN should pin the value or call out "configurable" — operators need to know the recovery latency.

### m4 — PLAN §9 "Notes for downstream" references `/tmp/v095-PLAN.md`. `/tmp` is not durable; reference should be to repo-relative path under `.planning/phases/02e-*/`. Lost trail otherwise.

---

## Recommendations summary

Block-merge if not addressed: C1, C2, C3.
Major-revise: M1, M2, M3, M5.
Track-as-task: M4, M6, m1.
Editorial: m2, m3, m4.

Re-review trigger: after PLAN updates §3.2 (journal-as-anchor), §3.3 (deterministic install pre-step or content snapshot), and §7 (release runner prerequisites). The other items can land in ImplPlan as task-level constraints.
