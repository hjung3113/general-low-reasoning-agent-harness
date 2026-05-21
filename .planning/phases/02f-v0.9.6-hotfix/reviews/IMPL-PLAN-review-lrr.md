# Low-Reasoning Realist ImplPlan Review — v0.9.7

Verdict: BLOCK

The stressed user at 2 AM ran `harness init`, hit Ctrl+C halfway, sees half a `.harness/` dir and a scary error. Will this plan actually help them?

## CRIT (block)

### C-1: User does not know to run `harness state repair`
USER_MANUAL gets a new "중단된 설치 복구" subsection (T10). The `InstallFailed` error that fires after an aborted batch (`install.py`, PLAN §7.1 phase 2 "raise InstallFailed(...)") — IMPL-PLAN does NOT specify the error message text. Is the message going to say "run python3 scripts/harness.py state repair"? PLAN §7.6 doc body says it, but the failure-path error message itself is unspecified. Without that pointer, the user at 2 AM searches Korean docs they may not read fluently and gives up. Spec: T3 acceptance must include "InstallFailed message contains the exact `state repair` invocation string". Add a test that greps the exception message.

### C-2: `state repair` exit code on partial recovery is unspecified
If `_recover_pending_manifest` orphans 1 pending sidecar and finalizes 1 other, what's the rc? `harness state repair` exit code drives shell/CI gates. If rc=0 on "quarantined" outcomes, users think they're fine when files are in `.harness/conflicts/`. Plan §7.2 doesn't pin exit codes. IMPL-PLAN T2 acceptance doesn't either. v0.9.5 had a "rc=0 on all errors" P0 (per memory `project_v095_hotfix_scope` NEW-3) — same trap here.

### C-3: SIGTERM tests in T3 are crash-testing but `state repair` is never run before "test passes"
T3 test #2 says "SIGTERM after stage, before finalize: `state repair` re-runs and finalizes". Who runs `state repair`? The test? Or do they EXPECT the user to run it? If the test runs `state repair` and asserts the outcome, fine. The IMPL-PLAN says "manifest matches what would have been written" — that's an *outcome* check. But what about idempotency: a panicked user runs `state repair` THREE times in a row. Does it crash on the 2nd/3rd run? T2 has an "idempotency" test (test #6) for `_recover_pending_manifest` unit-level but T3 SIGTERM smoke doesn't repeat the recovery to confirm. The 2 AM user retries. Add: "run `state repair` 3x; assert all rc=0; final state identical".

### C-4: Skip-upgrade guard error message is in English only
T6 wording: "Skip-upgrade from v0.9.4 directly to v0.9.7 is unsupported. Run v0.9.5 first, then v0.9.7." Korean operators (target audience per repo) won't get the same UX as Korean-localized USER_MANUAL. Plan does not require bilingual messages. Either commit to Korean-only error strings (matching `중단된 설치 복구` doc style) or bilingual. Pick one and apply consistently across all v0.9.7 error messages added in T3/T4/T6.

## MAJOR (must fix before impl)

### M-1: Happy-path test "produces same on-disk state as v0.9.6 baseline" is hand-wavy
T3 test #1: "Happy path: `harness init` produces same on-disk state as v0.9.6 baseline (file count + manifest content)". File count is easy. "Manifest content" — same SHAs? Same `installed_at`? Same `source_provenance`? If the new pending-sidecar dance changes timestamps or content ordering, this test will be flaky. Pin the exact comparison: "manifest.json bytes equal modulo `installed_at`, `source`, `git_user_email_at_install_sha256`". Otherwise this test passes today and fails next week for unrelated reasons.

### M-2: T8 ("delete synthetic seeders") will surface real bugs — but the IMPL-PLAN has no schedule slack
"If tests surface real upgrade bugs, fix in T4 or surgically defer (file an issue + add xfail with TODO)". This is the "we'll deal with it when we get there" entry in the plan. 2 AM user gets the deferred xfail and the bug bites in production. v0.9.5 lesson (per memory `project_v094_install_broken`) was that smoke surfaced 8 bugs post-impl. Same risk here. Spec: T8 must run BEFORE T11 (CHANGELOG/version bump) so any surfaced bug is either fixed in v0.9.7 or *explicitly listed in CHANGELOG as deferred*. IMPL-PLAN dependency graph has T8 → T11, good. But there's no "freeze T11 until T8 results triaged" gate.

### M-3: `harness check` warning doesn't tell user what to do
T5 warning row text: "Aborted install detected; run `harness state repair`". Decent. But if `state repair` also exits with a generic message, the user is in a loop. Spec: warning row should include the exact `pid` / `staging-dir` name so the user can `ls` it and see what's there. Otherwise it's a black box.

### M-4: T9 KNOWN_FAILING_TESTS.md "drift gate" is hostile to PR authors
A PR fixing 1 known failing test now fails CI (`known - current` non-empty) until the author updates KNOWN_FAILING_TESTS.md. This is correct behavior but adds friction. T9 must include a `--update` mode or a clear error message ("Test X passed; remove it from KNOWN_FAILING_TESTS.md") so 2 AM contributors don't fight the gate.

### M-5: USER_MANUAL Korean text in PLAN §7.6 uses passive "복구 결과는 `.harness/audit.log` 에 ... 기록" — user can't tell SUCCESS from FAILURE
T10 doc body needs an explicit "성공 출력 예시" and "실패 출력 예시". Currently §7.6 only describes the mechanism. A 2 AM user wants "여기 이거 보이면 OK, 이거 보이면 다시 시도".

### M-6: T6 override env var name is `HARNESS_ALLOW_SKIP_UPGRADE` — discoverability
Users who hit the refuse error try Google → find nothing (private repo) → maybe find the CHANGELOG line. CHANGELOG hardening bullet (T11) mentions the env var name. Acceptable. But the error message ITSELF should print "Override (not recommended): HARNESS_ALLOW_SKIP_UPGRADE=1" — PLAN §3.5 has this; IMPL-PLAN T6 has this. Good. Confirm tests assert the override string is in the error.

## MINOR

### m-1: T11 acceptance "version constants match tag; CHANGELOG renders cleanly" — no actual rendering check
`CHANGELOG renders cleanly` is not a test. Either commit to "no `pandoc CHANGELOG.md` warning" or drop the phrase.

### m-2: T2 test #5 "orphan → quarantined" doesn't assert audit row
The audit-row contract `install.recovery.pending_orphaned` is the user's only sign that something was quarantined. Assert it in the test, not just the side-effect.

### m-3: No "user re-runs harness init after failed install" test
After abort + repair → orphaned state, user re-runs `harness init` (impatient). Does it complete cleanly or trip over residual artifacts? Add smoke.

### m-4: T1 test naming
`test_atomic_install_batch_defer_cleanup.py` is fine. But T1 test #5 (`positional call raises TypeError`) is a Python-API smoke not a user-facing concern. Keep it but downgrade priority.

## Recommended amendments

1. **Spec all error messages**: T3, T4, T6 must include the exact error-message text in IMPL-PLAN and assert via test. Include `state repair` invocation pointer in InstallFailed message.
2. **Pin exit codes**: `state repair` rc table — 0 (no-op or full recovery), 1 (partial recovery with quarantine), 2 (catastrophic). Match `harness check`.
3. **Bilingual or Korean-only**: pick a language convention for v0.9.7 error strings and apply uniformly.
4. **T3 idempotency smoke**: run `state repair` 3x consecutively.
5. **T5 warning verbosity**: include staging-dir name + age in the warning row.
6. **T9 drift gate error UX**: print actionable "Test X newly passing; remove from KNOWN_FAILING_TESTS.md".
7. **T8 freeze gate**: T11 must not commit until T8 triage report (one of: fixed-in-T4, xfail+issue-#, ok-as-is) lands as a planning note.
8. **T10 USER_MANUAL success/failure example output**: paste real stderr output from a smoke run.
9. **Re-init after abort smoke**: add to §8 sequencing step 12.
10. **Pin "happy path bit-equality" comparison fields** in T3 test #1 — explicit allowlist of fields-that-may-differ.
