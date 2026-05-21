# Codex CLI ImplPlan Review — v0.9.7

Adversarially review the implementation plan for v0.9.7 hotfix.

## Read

- `.planning/phases/02f-v0.9.6-hotfix/plans/IMPL-PLAN.md` (just authored — T1-T11)
- `.planning/phases/02f-v0.9.6-hotfix/plans/PLAN.md` (REV-5 — design contract)
- Source files referenced in IMPL-PLAN tasks: `scripts/lib/atomic_io.py`, `scripts/lib/install_recovery.py`, `scripts/lib/install.py`, `scripts/lib/upgrade.py`, `scripts/lib/state.py`, `scripts/lib/check.py`, `scripts/build_v094_fixture.py`, existing test files mentioned

## Attack vectors

1. **T1 sentinel write**: Is the sentinel write `os.replace(sentinel_tmp, sentinel_path)` safe if `sentinel_tmp` already exists from a prior failed run? Does the sequence guarantee sentinel appears AFTER last journal flush?
2. **T2 decision matrix**: Are all 4 branches in `_recover_pending_manifest` truly exhaustive? Any state combination not covered? (e.g. sentinel present + .aborted simultaneously; sentinel present + journal incomplete)
3. **T3 phase ordering**: Pending sidecar must be written via temp+replace (atomic). Does the IMPL-PLAN specify this in the `write_install_state_to` extraction, or is it implicit? Risk: if the sidecar is partially written and a crash occurs, recovery finalizes a torn manifest.
4. **T3 state.py refactor**: Does the `write_install_state` → `build_install_state_payload` split risk breaking existing callers (e.g. upgrade.py, repair.py)? Are all callers identified?
5. **T4 upgrade wire-in**: Does upgrade have any pre-existing pending sidecar OR `.complete` sentinel from a prior install that recovery might collide with mid-upgrade? Cleanup ordering ok?
6. **T5 staging detection**: A `.staging-*` directory created by a CURRENTLY-RUNNING install would trip the check warning. Should check warn or skip in-progress installs? IMPL-PLAN doesn't say.
7. **T6 skip-upgrade**: When is `prior_state.get("version")` available? Could it be missing on corrupted installs and bypass the guard?
8. **T7 fixture determinism**: Will `harness_version` field in v0.9.4 manifest content match across machines? It uses `_active_harness_version()` which reads VERSION file — at v0.9.4 tag, fixed. But does any computed `installed_files_chain_hash` depend on host-specific paths?
9. **T8 real-fixture**: If T8 surfaces a real upgrade bug, the IMPL-PLAN says "fix in T4 if scope-internal". What if it's a state.py bug not in upgrade flow? Plan loop.
10. **T9 drift gate**: The plan reads `.harness-test-cache/junit.xml`. Is this committed (bad — large + churn) or generated (better, but skip-message UX needed)?
11. **T11 version bump**: Are there hidden version-ref locations the plan doesn't enumerate (e.g. docs/site/index.html footer, manifest.json scaffold)?

## Output

Write `.planning/phases/02f-v0.9.6-hotfix/reviews/IMPL-PLAN-review-codex.md`:

```
# Codex ImplPlan Review — v0.9.7

Verdict: [PASS | PASS-WITH-CONDITIONS | BLOCK]

## CRIT
## MAJOR
## MINOR
## Recommended amendments
```

Terse. Quote exact file:line evidence.
