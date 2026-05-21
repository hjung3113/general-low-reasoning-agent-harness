# v0.9.6 Plan Review — Protocol Architect

Reviewer: Opus (Protocol Architect lens)
Date: 2026-05-21
Plan reviewed: `.planning/phases/02f-v0.9.6-hotfix/plans/PLAN.md` (commit-tree state)
Method: full plan read → ground-truth each cited path → cross-check ADR + KNOWN_VERBS + existing tests.

## Verdict summary
- CRITICAL: 3
- MAJOR: 5
- MINOR: 3

---

## CRITICAL findings

### C-1 §1 issue #1 root-cause is not located — Plan jumps to a fix sketch without a confirmed trace
- Where in plan: §1 (lines 12) and §3.1 (lines 49–52)
- Evidence:
  - `scripts/lib/upgrade.py:308–374` — both signed and dev paths converge on a single `_build_release_manifest_v2(...)` call (line 830) which returns `release_manifest` with `trust_origin` set ("signed_tag" or "dev_unsigned"); only the *file-hash source* diverges (`file_sha256_at_commit` vs `file_hash(src)` at lines 409–422).
  - `_stamp_installed_manifest_v2` is called *unconditionally* at `upgrade.py:900`.
  - The rechain emit at `upgrade.py:627` ("`previous_chain_hash and new_chain_hash and previous_chain_hash != new_chain_hash`") is also unconditional.
  - The wire-in at `upgrade.py:907–924` pops `_pending_rechain` regardless of trust_origin.
- Why critical: The plan asserts "the dev-bypass path doesn't update manifest" but the code as written has **no branch that skips manifest update for dev_unsigned**. Either (a) the smoke observation in §1 was misread, or (b) the bug is elsewhere (e.g. the dev path's `file_hash(src)` returns the SAME shas as the v0.9.4 baseline because the working tree hasn't changed, so `installed_files_chain_hash` is byte-identical → no rechain → no audit row, but `files` count SHOULD still grow if new modules exist). T1 is listed as a "gate-blocker investigation" but the plan's own §3.1 then prescribes a fix (`_stamp_installed_manifest_v2` on both paths) that the code already does.
- Recommendation: Make T1's exit-criterion an evidence file at `.planning/phases/02f-v0.9.6-hotfix/evidence/dev-unsigned-trace.md` that pins the actual divergence line range. Do not authorize T2 until that file lists a real line:line target. Remove §3.1's prescriptive "Ensure both paths execute `_stamp_installed_manifest_v2`" until the bug is located — the prescription is already true in v0.9.5.

### C-2 Success criterion #2 (atomic batch) is not satisfied by current `atomic_install_batch` API for the largest call site (managed-append + write_text_file)
- Where in plan: §2 criterion 2 (lines 31–34) and §3.2 (lines 55–57)
- Evidence:
  - `scripts/lib/atomic_io.py:276–339` — `atomic_install_batch` is a **rename-only** primitive: it requires files already materialised in `staging_dir` and only does `os.replace`.
  - `scripts/lib/install.py:300–307` — install writes mix three different operations: `write_managed_append` (renders + injects a block, line 303), early-return on existing `project-owned` (line 304), and `write_copy` (line 307).
  - `scripts/lib/upgrade.py:704–763` — upgrade additionally does `plan_managed_append` then `write_text_file(destination, result.updated_text)` (line 719) which is a **content-mutating** write, not a copy.
  - `scripts/lib/install.py:310` and trust-origin/install-record writes at lines 315–329 also occur OUTSIDE the per-file loop and depend on `target/.harness/` already being a real directory.
- Why critical: Plan §3.2 says "replace `write_copy` and `write_text_file` calls with a staged-then-batch approach" — but `atomic_install_batch` is not a drop-in replacement. Callers must (a) pre-render managed-append output into staging, (b) decide what to do with `project-owned` skip cases, (c) sequence the install-record + trust-origin stamping so they don't observe a half-staged tree. None of this restructuring is scoped in §3.2 or §7. Plan §5 risk row "may surface latent bugs" treats it as a risk, but it is a *known* design gap, not a risk.
- Recommendation: Either (a) downgrade scope to "atomic for harness-owned copy writes only; managed-append + write_text_file remain non-atomic, documented as v0.9.7 follow-up", or (b) add T5a "design + spec stage-pipeline for managed-append/write_text_file" with explicit return-shape and a codex-gate before T5 implementation. Without this, T5 is open-ended and will spill the LOC budget.

### C-3 Plan §6 Q3 "Default-on" atomic wire-in violates the v0.9.6 hotfix scope discipline
- Where in plan: §6 Q3 (lines 96–97) and risk table row 1 (line 83)
- Evidence:
  - The risk row itself says "make atomicity opt-in if needed, default off in v0.9.6, full migration in v0.9.7" — directly contradicting Q3's "Default recommendation: Default-on".
  - `scripts/lib/install.py:300–329` shows fresh-init also invokes `write_install_record` and `_stamp_install_trust_origin` post-loop; flipping the loop atomic semantics changes when these post-conditions become observable to recovery code (`install_recovery.recover_aborted_install` at `install_recovery.py:265`).
  - No fresh-install integration test currently exercises a SIGTERM during a partial managed-append render.
- Why critical: A hotfix release should not change *default* behaviour of fresh-init writes the day after v0.9.5 stabilised install-record bootstrap (ADR `docs/adr/2026-05-21-init-bootstraps-install-record.md`). The plan author's own risk row says default-off; Q3 says default-on. Internal inconsistency must be resolved before review→codex hand-off.
- Recommendation: Set Q3 to **opt-in via `HARNESS_ATOMIC_INSTALL=1`** for v0.9.6 (matching the risk-row mitigation). Reserve default-on for v0.9.7 with a real fresh-install kill-mid-install integration test on macOS+Linux. Update §2 criterion 2 accordingly: "When `HARNESS_ATOMIC_INSTALL=1`, init/upgrade route writes through staging" rather than unconditional.

---

## MAJOR findings

### M-1 §2 criterion 5 ("chain extends, not re-anchors") is testable only if v0.9.5→v0.9.6 actually changes chain inputs
- Where in plan: §2 criterion 5 (line 42)
- Evidence: `scripts/lib/upgrade.py:594–633` — rechain emit fires only when `previous_chain_hash != new_chain_hash`. Chain input at line 609 covers `release_commit`, `release_tag`, `schema_version`, `harness_version`, `files` (with sha256 pairs), `trust_origin`. If v0.9.6 ships with the same set of lib modules and same shas as v0.9.5, `harness_version` change alone WILL change the chain (line 613). Good — but only if `harness_version` actually differs.
- Why major: If a developer tests v0.9.5→v0.9.6 from a HARNESS_VERSION-pinned dev fixture where the version string didn't get bumped, no audit row fires and criterion 5 trivially fails. The plan does not list "bump harness_version BEFORE rechain test" as a precondition.
- Recommendation: Add explicit step to §7 T7: "verify `harness_version` in source tree is v0.9.6 before running upgrade rechain test." Or: extend the test fixture path to assert `release.trust.rechained` row exists *and* args show prev/new chain hashes differ, with a clear failure message.

### M-2 Plan §6 Q2 "reuse `release.trust.rechained` with `trust_origin` field" requires KNOWN_VERBS-adjacent contract changes the plan doesn't enumerate
- Where in plan: §3.1 (line 51), §6 Q2 (lines 94–95)
- Evidence:
  - `scripts/lib/release_trust.py:278–336` — `record_rechain` signature has NO `trust_origin` kwarg today; entry args at line 326–331 are a fixed dict.
  - `scripts/lib/audit.py:317–367` — KNOWN_VERBS is a frozenset; the verb is allowed but args payload shape is implicit contract.
  - `tests/test_release_trust_rechain.py:108–125` — asserts args contain `previous_chain_hash`, `new_chain_hash`, `cause`, `module_count_added` (no strict equality, additive-safe).
- Why major: Adding `trust_origin` is additive on tests, but:
  1. `record_rechain` signature must grow a kwarg AND default it (else upgrade.py:914 call breaks).
  2. The new field must be propagated from `_emit_rechain_audit` (`upgrade.py:442–528`) which currently has no access to `release_manifest`/`installed["trust_origin"]` — it receives only `installed` dict (line 444). `installed["trust_origin"]` is set at line 604 BEFORE `_emit_rechain_audit` is called, so it IS reachable, but plan doesn't say so.
  3. Audit chain consumers (audit_verify_cli, audit_chain) treat args as opaque, so safe — but any external dashboard parsing args is now contract-coupled to the new field. ADR or CHANGELOG must note this.
- Recommendation: In T2, explicit subtask: "extend `record_rechain` signature with `trust_origin: str | None = None`; thread from `installed.get('trust_origin')` in `_emit_rechain_audit`; add 1 new test in `test_release_trust_rechain.py` asserting the field on both signed and dev-unsigned cases." Add CHANGELOG entry under "audit row schema additions".

### M-3 §3.3 fixture rewrite + §3.4 "out of scope" + §2 criterion 7 form a contradictory triangle
- Where in plan: §3.3 (lines 60–64), §3.4 (lines 66–68), §2 criterion 7 (line 44), risk row 4 (line 86)
- Evidence:
  - §3.3: "Remove `.harness` from EXCLUDE_NAMES … drop synthetic seeds → T15 will then exercise the actual upgrade code path."
  - Risk row 4: "may surface latent bugs in upgrade code path … treat as in-scope (release-blocker)".
  - §3.4: "Triage 5-10 quick-win failures from the 76 baseline" — explicitly OUT unless Q1=yes.
  - §2 criterion 7: "≤76 failures (v0.9.5 baseline); no new regressions".
- Why major: If T4 fixture rewrite exposes 2+ real-upgrade bugs that fail tests, criterion 7 ("no new regressions") is violated — but those failures are NEW TESTS, not regressions from existing tests. The plan conflates "tests added that fail" with "regression". Worse: risk row 4 says treat such failures as in-scope and release-blocking, but §3.4 says pre-existing failures are out-of-scope.
- Recommendation: Distinguish in §2: criterion 7a "no existing-test regressions (count of failures in tests that passed in v0.9.5 ≤ 0)" and criterion 7b "new test_upgrade_from_v094_* failures introduced by §3.3 must be either (i) fixed in this release or (ii) skipped with an XFAIL tagged `v0.9.7-deferred`". Without this, T4 has ambiguous exit criteria.

### M-4 install_recovery delegation claim "T14b is already wired" is true only for `state repair`, not for `harness check`
- Where in plan: §3.2 (line 57), risk row 6 (line 88)
- Evidence:
  - `scripts/lib/state_repair.py:217` calls `_ir.recover_aborted_install(root)` — confirmed wire.
  - `scripts/lib/check.py:444` only references a string suggestion to run `state repair`; no scan for `.staging-<pid>/` directories.
  - Risk row 6 itself says "`harness check` could detect staging dirs" — future tense.
- Why major: Plan §3.2 final sentence reads as if the recovery story is complete. It is not — `check` will rc=0 with a half-installed tree if no other check trips. Default-on atomic wire-in (C-3) compounds this because users may not know `state repair` is what they need.
- Recommendation: Add T5b (1-task): "in `lib/check.py`, scan target for `.harness/.staging-*/` directories; report under existing dashboard; non-zero exit code if found and `--strict` is set." Add 1 unit test.

### M-5 v0.9.4 → v0.9.6 skip-version upgrade (criterion 6) uses `_V094_MISSING_MODULES` table that has not been re-validated against the v0.9.6 lib delta
- Where in plan: §2 criterion 6 (line 43), risk row 5 (line 87)
- Evidence: `scripts/lib/release_trust.py:255–275` — `classify_rechain_cause` checks `_V094_MISSING_MODULES`. The constant was authored for v0.9.5's gap remediation. Any new lib module added between v0.9.5 and v0.9.6 is NOT in that table, so `cause` falls through to `manifest_evolution` even though the user is going from v0.9.4 baseline.
- Why major: A skip-version upgrade test will likely still pass (audit row exists), but the cause classification will mis-attribute the chain delta when *both* v0.9.5 gap modules AND v0.9.6 new modules were added. Forensics value of the audit row drops.
- Recommendation: T2 must include: "audit `_V094_MISSING_MODULES` against current `scripts/lib/` listing; if any v0.9.6-new modules are present, document the policy: either extend the constant (preferred) or accept dual-cause classification by changing `classify_rechain_cause` return type to list of (cause, count) tuples." Pick one before implementation.

---

## MINOR findings

### m-1 §3.1 audit verb decision is described as "default recommendation" but Q2 in §6 marks it as still-open
- Where in plan: §3.1 line 52 vs §6 Q2 lines 94–95
- Recommendation: resolve before codex review per §6 header (line 90). Pick one and remove the alternate verb from the plan body.

### m-2 §7 sequencing "T3 → T4 in parallel with T5" is risky given T4 may discover bugs requiring T5-shaped fixes
- Where in plan: §7 line 114
- Recommendation: Sequence T4 before T5; T5 is the larger and more invasive change. If T4 exposes a real-upgrade bug it may pre-empt T5's design.

### m-3 §8 done-definition omits explicit "manifest_v2 schema unchanged" assertion
- Where in plan: §8 lines 116–127
- Evidence: §4 says "No state schema changes" but §8 lacks a measurable check.
- Recommendation: Add bullet "diff of `schema_version` field across v0.9.5 and v0.9.6 installed-manifest is zero". This is a 1-line grep, cheap insurance.

---

## Items VERIFIED CORRECT
- `lib/state_repair.py:217` already delegates to `install_recovery.recover_aborted_install` — §3.2 claim accurate for that surface.
- `release.trust.rechained` is in `KNOWN_VERBS` at `scripts/lib/audit.py:361` — adding `trust_origin` as a payload field does NOT require a new verb registration (Q2's "reuse" path is verb-registry-safe).
- `scripts/build_v094_fixture.py:37` shows `EXCLUDE_NAMES = {…, ".harness"}` — §3.3 evidence accurate; removal will indeed include `.harness/` in tarballs.
- `_stamp_installed_manifest_v2` is called unconditionally for both signed and dev paths (`upgrade.py:900`) — confirms that ANY proposed fix in §3.1 must be more surgical than "ensure both paths execute it".
- `tests/test_release_trust_rechain.py` does not use strict dict-equality on args — additive payload changes are non-breaking. M-2's risk is implementation-side, not test-side.

---

## Questions for the plan author
1. **C-1**: What is the actual line in `upgrade.py` (or downstream module) where the dev-unsigned smoke produced a no-op? The plan asserts the bug but does not cite a line. Without a real trace, T1's exit criterion is unfalsifiable.
2. **C-2**: How will `write_managed_append` and `write_text_file` outputs be staged for `atomic_install_batch`? These are content-mutating, not pure copy. Is the intent to render to `staging_dir/<rel_path>` first, then batch-rename? If so, that's a separate, larger refactor.
3. **C-3 / Q3**: The risk row says default-off, the open decision says default-on. Which is authoritative? A v0.9.6 *hotfix* with default-on changes to fresh-init write semantics seems out of character for a hotfix.
4. **M-2 / Q2**: Will `record_rechain` get a new `trust_origin` kwarg? If yes, will old callers (zero — only `upgrade.py:914` exists today) be updated atomically in the same commit?
5. **M-3**: If T4's real-fixture tests fail because of a v0.9.4-era bug that v0.9.5 already shipped (i.e. user-visible since v0.9.5 release), is the v0.9.6 hotfix the right place to fix it, or do we ship the failing test as XFAIL and address in v0.9.7?
6. **M-5**: Was `_V094_MISSING_MODULES` audited against `scripts/lib/` for v0.9.6-new additions? If new lib modules ship in v0.9.6, the cause classification for a v0.9.4→v0.9.6 jump becomes ambiguous.
7. §7: Why is T3 (fixture rebuild) parallelizable with T5 (atomic wire-in) but not with T2? T3 only touches build_v094_fixture.py + `.sha256` pinned files — it should be parallelizable with T1/T2 as well, shortening critical path.

---

End of review.
