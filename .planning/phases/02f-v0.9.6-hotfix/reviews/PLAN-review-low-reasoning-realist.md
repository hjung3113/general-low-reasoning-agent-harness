# PLAN review — Low-Reasoning Realist lens

Plan: `/Users/hyojung/Desktop/2026/general-low-reasoning-agent-harness/.planning/phases/02f-v0.9.6-hotfix/plans/PLAN.md`
Date: 2026-05-21
Reviewer: Low-Reasoning Realist (Opus)

## Verdict: **FLAG**

The plan correctly closes the three v0.9.5 deferred items at engineering level, but its UX/docs posture is too thin for the low-reasoning-agent target audience. Three findings rise to CRITICAL because they make user-visible failures invisible or unrecoverable without operator knowledge that the plan refuses to document. None of these require schema/contract changes; all are doc + small-code adjustments. Plan is shippable after addressing the CRITICAL items and at least the first two MAJOR items.

Core tension: §4 ("no doc rewrites beyond CHANGELOG + 1-line What's-new note") directly contradicts §5 ("`harness check` could detect staging dirs and recommend `state repair`; document recovery flow in USER_MANUAL"). One of those statements has to give. Documentation IS the product for a low-reasoning-agent harness — agents run docs verbatim. Treating docs as gold-plating breaks the user contract.

---

## CRITICAL

### CRIT-1 — Recovery UX is unreachable from any doc surface (Plan §3.2 + §5 row 6 vs §4)
Plan §5 mitigation row 6 says `harness check` "could" detect staging dirs and recommend `state repair`, "document recovery flow in USER_MANUAL". Plan §4 says "no documentation rewrites beyond CHANGELOG v0.9.6 + a 1-line note in USER_MANUAL". These are mutually exclusive.

Today (`scripts/lib/check.py`), `check` has no staging-dir detection (verified: only mention of `state repair` is line 444, unrelated managed-block path). After v0.9.6, low-reasoning agents will:
1. Run `harness init`, kernel sends SIGTERM (CI timeout, Ctrl-C, OOM).
2. Re-run `harness init` next morning — likely succeeds writing OVER the partial install, but `.staging-<pid>/` remains in `.harness/`.
3. Daily-four (`init → next → run → check`) never surfaces the staging dir until 10 min `STAGING_AGE_THRESHOLD_SECS` elapses, and even then only if the agent runs `harness state repair` — which no doc tells them to do.

`install_recovery.recover_aborted_install` is excellent code, but only `state repair` invokes it (per T14b delegation). Agents reading `USER_MANUAL` will not type `state repair` unprompted; the verb is listed at line 371/1088 only as a managed-block repair tool.

**Recommendation (BLOCKING):**
- Plan §3.2: add concrete deliverable "`check.py` adds a `_check_orphan_staging` rule that surfaces `.harness/.staging-*` directories as a WARNING-class finding with remediation string `run \`harness state repair\``."
- Plan §4: amend to "USER_MANUAL §troubleshooting gains an 'Interrupted install recovery' subsection (≤20 lines)" — this is not gold-plating, this is closing the recovery loop the plan itself opened.
- Success criterion 2 should add: "After SIGTERM + re-run, `harness check` exits non-zero with a message naming `state repair`."

### CRIT-2 — v0.9.4 → v0.9.6 skip-upgrade path: error UX undefined
§2 criterion 6 promises "v0.9.4 → v0.9.6 in-place upgrade … works correctly with rechain audit row". §5 row 5 says "record_rechain handles cause classification (`v094_manifest_gap_remediation`)". But v0.9.4 ships with the 35-module manifest gap (per memory [[v094-install-broken]]); a real v0.9.4 user doing `git pull && python3 harness.py upgrade --target ...` runs *the broken v0.9.4 upgrade.py*, not v0.9.6's. Their first command crashes with `ModuleNotFoundError` (NEW-3 class, since the v0.9.4 process is the one resolving the import path).

The plan does not specify whether the entrypoint shim (`harness.py`) survives the v0.9.4 broken state OR whether the user must `git pull && pip install` something first. For a low-reasoning agent reading USER_MANUAL §upgrade, the procedure has to be exactly one copy-paste block.

**Recommendation:**
- §3 should add a sub-bullet under §3.1 or §3.3: "Document the canonical v0.9.4-broken→v0.9.6 escape hatch (likely: fresh clone + `harness init --reuse-state .harness/` or equivalent). If that path requires a new flag, list it."
- §2 criterion 6: tighten "works correctly" → "produces rc=0 and prints exactly one user-actionable line if it cannot complete (no traceback)."
- If the escape hatch is "delete `.harness/` and reinit", say so — current Plan implies seamless upgrade, which is implausible given the v0.9.4 import-crash surface.

### CRIT-3 — Pre-existing 76 failures are a permanent agent-visible red wall (Plan §2 criterion 7)
§2 criterion 7 reads "≤76 failures (v0.9.5 baseline); no new regressions". A low-reasoning agent running `pytest` after a clean clone sees 76 RED tests and has no way to know that's expected. There is no `KNOWN_FAILING_TESTS.md`, no pytest `xfail` markers, no `conftest.py` annotation. Agents reading "test failure = stop and fix" runbooks will halt the workflow.

Plan defers this to v0.9.7. That's defensible for the *fix*, but not for the *signal*. The cost of adding `@pytest.mark.xfail(reason="pre-existing v0.9.5 baseline, tracked in #N")` to the 76 is small and lets CI go green.

**Recommendation:**
- Add to §3 (in-scope, not §3.4 secondary): "Annotate the 76 baseline failures with `xfail` + tracking issue OR commit `docs/known-test-failures.md` enumerating them by nodeid. Agents must be able to distinguish pre-existing vs. new failures by reading repo state alone."
- §2 criterion 7 should be replaced by: "pytest run yields 0 unexpected failures; baseline-76 either pass, are marked xfail, or are listed in `docs/known-test-failures.md` with rationale."

---

## MAJOR

### MAJ-1 — CHANGELOG-only release notes are agent-hostile jargon (§4)
The plan's §3.1 default ("reuse `release.trust.rechained` with payload field `trust_origin=dev_unsigned`") produces a CHANGELOG line that reads like "release.trust.rechained now carries trust_origin=dev_unsigned on HARNESS_ALLOW_UNSIGNED_DEV path." A low-reasoning agent reading that string verbatim has no idea what action, if any, is required.

**Recommendation:** CHANGELOG entry for the dev-unsigned fix MUST include a "How to verify" line: e.g. `python3 scripts/harness.py verify --audit | grep release.trust.rechained` and the expected JSON shape. Same pattern for the atomic wire-in: include "If install was interrupted, run `python3 scripts/harness.py state repair`."

### MAJ-2 — Atomic install perf delta unquantified (Plan §5 lacks row, Plan §3.2)
Stage-then-rename doubles I/O during install (write to `.staging-<pid>/`, then `os.rename`). On same-FS it's near-free; on cross-FS (network shares, encrypted volumes, Docker bind mounts, macOS user-volume → APFS-snapshot) `os.rename` falls back to copy+unlink and triples I/O. Plan picks "default-on" (Q3) without any measurement.

For a small target like `.harness/` (single-digit MB) this is irrelevant on local disk, but the failure mode on cross-FS is `OSError: [Errno 18] Invalid cross-device link`. `atomic_install_batch` must guarantee staging is on the same filesystem as target — and the plan does not enumerate that requirement.

**Recommendation:**
- §3.2 add: "Verify staging dir is created under `$TARGET/.harness/.staging-<pid>/`, i.e. same FS as final install path. Reject (with friendly error pointing at `--staging-dir` override or `--no-atomic` fallback) if `os.statvfs` differs."
- §5 add new risk row: "Cross-FS staging: `EXDEV` on `os.rename`. Mitigation: same-FS guard + clear error."
- §6 Q3 should add option (c) "default-on with `--no-atomic` opt-out flag" — this is the actual safest landing.

### MAJ-3 — SIGTERM mid-install error message UX unspecified (§2 criterion 2)
Criterion 2 says "Kill-mid-install (SIGTERM during the batch) leaves staging dir + journal intact" — but does not say what stdout/stderr the user sees on the NEXT `harness init`. If next-run hits the orphan and bypasses it silently because age < 10 min, the user has no signal. If it errors hard with a traceback, low-reasoning agents loop.

**Recommendation:** Add success criterion 2a: "Next `harness init`/`upgrade` invocation detects `.staging-<pid>` (regardless of age) and emits exactly one line: `Previous install interrupted. Run \`harness state repair\` to recover, or pass --force to overwrite.` rc=`EXIT_OPERATIONAL`." Override `STAGING_AGE_THRESHOLD_SECS` for the same-process re-entry case OR add a "force kill detected" marker.

### MAJ-4 — v0.9.5→v0.9.6 fixture/manifest hash bump leaves users with mismatch report
§3.3 regenerates fixture `.sha256`. But existing v0.9.5 installs (the population the plan plans to upgrade) have `installed-manifest.json` pinned to v0.9.5 hashes. When v0.9.6 upgrade runs `_stamp_installed_manifest_v2`, the chain extends — fine. But T15's *real* upgrade test now runs against the new fixture; older CI caches will keep v0.9.5 fixture sha256 → CI break window.

**Recommendation:** §3.3 add "Bump fixture filename to `v094-with-harness-<sha>.tar.gz` so old-fixture references fail loudly rather than silently picking a stale tarball from a CI cache." Same commit ships both old + new for one release.

---

## MINOR

### MIN-1 — Q2 audit-verb decision documented but verb collision unchecked
Default is "reuse `release.trust.rechained` with `trust_origin` field". `KNOWN_VERBS` in `lib.audit` should be greped to confirm `release.trust.rechained` is the only `rechained` verb. Add a one-liner in T2 deliverables: "Confirm `grep -rn rechained scripts/lib/audit.py` returns the single existing verb."

### MIN-2 — §6 Q1 default "3 deferred items only" but §3.4 leaves room for ambiguity
The "only if Q1=yes" gating is fine, but T6 in §7 lists 3 new test files; if Q1=yes there's no T-number for failure triage. Either add T6b or explicitly say "Q1=yes adds T8 (BUG-4) + T9 (failure triage)" to keep sequencing unambiguous.

### MIN-3 — `What's new in v0.9.5` heading in USER_MANUAL will become stale
USER_MANUAL §1 line 70 reads "What's new in v0.9.5". Plan §4 promises only a 1-line What's-new note for v0.9.6 — but no instruction on whether to APPEND below v0.9.5 or REPLACE. Low-reasoning agents reading the manual will see v0.9.5 framing as current.

**Recommendation:** §4 amend: "USER_MANUAL header version bump to v0.9.6 + 'What's new in v0.9.6' subsection added ABOVE the v0.9.5 subsection (which is retained for one release as 'Previously')."

### MIN-4 — `docs/site/index.html` + `docs/site/manual.html` not in scope
HTML mirrors typically lag the markdown. Plan §4 makes no claim about them. If they're regen'd from markdown via a build step, say so; otherwise they'll display v0.9.5 framing post-release.

### MIN-5 — "1-line What's-new note" undersized
A line is not enough room to cover three behavior changes (manifest update, atomic wire-in, fixture rebuild). Realistically need 3-5 lines. Don't pre-commit to a length that forces hand-waving.

### MIN-6 — Recovery sentinel age threshold is hidden tunable
`STAGING_AGE_THRESHOLD_SECS = 600` (install_recovery.py:46) is not surfaced to USER_MANUAL. If an agent runs `state repair` 5 minutes after a kill, it's a no-op and the agent sees `staging_dirs_found=0` — confusing. Either lower the default to 60 s, or have `state repair` accept `--force`/`--all` to override age.

### MIN-7 — `release.trust.rechained_unsigned` (Q2 alternate) unexplored cost
Plan recommends reusing the verb. If a downstream consumer (dashboard, audit walker) special-cases `release.trust.rechained` to "production rechain", reusing the verb leaks dev events into production telemetry. The trade-off is one sentence in §3.1; current plan only argues the upside.

### MIN-8 — Plan §5 risk for "real-upgrade fails IS the bug v0.9.6 supposed to expose" lacks abort criteria
If T4 surfaces a release-blocker class, the plan does not say whether to extend v0.9.6 scope, downscope to v0.9.7, or pause the release. Add a decision rule: "If T4 reveals a state-corruption-class bug, defer atomic wire-in to v0.9.7 and ship v0.9.6 as fixture+dev-unsigned-only."

---

## PASS items (positive observations)

- §3.2 keeping `installed-manifest.json` write LAST after batch commit is the right invariant. Don't lose it.
- §3.3 deleting synthetic `_seed_v094_full_manifest` is exactly the right unblock for T15 MAJOR-2.
- §6 Q5 "per-task atomic commits" is correct for bisectability.
- §7 sequencing puts T1 trace before T2 fix — good discipline. Don't let Opus's reinforce pass collapse those.
- Success criterion 1 offering EITHER `trust_origin` field OR new verb keeps optionality until codex review — appropriate.

---

## Required actions before this plan exits review

1. Resolve §4-vs-§5 doc contradiction. Add USER_MANUAL troubleshooting subsection to scope (CRIT-1).
2. Specify v0.9.4-broken→v0.9.6 user procedure end-to-end (CRIT-2).
3. Add xfail or known-failures doc for the 76 baseline (CRIT-3).
4. Quantify cross-FS staging behavior + add same-FS guard (MAJ-2).
5. Define exact one-line user message after SIGTERM mid-install (MAJ-3).
6. CHANGELOG entries must include verification commands, not just verb names (MAJ-1).

After those land, this plan is shippable. The engineering shape is correct; the user-facing surface is what needs hardening.

— end review —
