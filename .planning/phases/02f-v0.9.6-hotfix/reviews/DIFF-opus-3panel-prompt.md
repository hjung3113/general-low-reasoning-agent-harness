# Opus 3-Panel Final Diff Review — v0.9.7

Final adversarial pass on the v0.9.7 implementation diff. Three personas, three independent reviews.

## Personas

1. **Architect** — design integrity, contract preservation, refactor safety
2. **Ops Hawk** — crash windows, races, recovery edge cases, durability
3. **Low-Reasoning Realist (LRR)** — will this actually help the stressed user at 2am? UX, error messages, exit codes, doc clarity

## Diff scope

- Branch `develop` vs `main` — 14 commits, 54 files, +5440 / -515
- Range: `git log --oneline main..develop`
- Planning ground truth: `.planning/phases/02f-v0.9.6-hotfix/plans/IMPL-PLAN.md` (REV-2)
- Implementation summary: `.planning/phases/02f-v0.9.6-hotfix/evidence/impl-summary.md`
- Deviations: `.planning/phases/02f-v0.9.6-hotfix/evidence/impl-deviations.md`
- T8 triage: `.planning/phases/02f-v0.9.6-hotfix/evidence/T8-triage.md`
- T12 smoke: `.planning/phases/02f-v0.9.6-hotfix/evidence/smoke-2026-05-21.md`

## Attack per persona

### Architect
- Does the actual `_recover_pending_manifest` implementation match the REV-5 decision matrix?
- Does T4's "two-pass" truly avoid target writes in Pass A?
- Does `file_state(staged=)` cover ALL the chain-hash inputs needed (Architect's REV-1 C-1 concern)?
- Are there refactor side-effects in `state.py` that affect non-install callers (audit, planning, dashboard, etc.)?

### Ops Hawk
- Is sentinel write actually atomic (open + fsync + os.replace + parent_dir fsync)?
- Are `.complete.tmp` orphans actually cleaned up in `_recover_pending_manifest`?
- Does T8 deviation (xfail) hide a real bug or correctly defer? Re-evaluate.
- T12 deviation: scenarios 2/3/5 via unit tests instead of CLI SIGTERM — does the unit layer actually cover the same code path?
- Any race between `_recover_pending_manifest` pending scan and a concurrent in-progress install?

### LRR
- Read the actual bilingual error messages — do they make sense to a Korean-first operator at 2am?
- Read `docs/USER_MANUAL.md` recovery section — does it match the exit code contract?
- Will `harness check` warning text help a user identify what to do, or is it noise?
- Are the smoke evidence outputs realistic-looking (real CLI output) or hand-waved?

## Output

Three independent review files:
1. `.planning/phases/02f-v0.9.6-hotfix/reviews/DIFF-review-architect.md`
2. `.planning/phases/02f-v0.9.6-hotfix/reviews/DIFF-review-ops-hawk.md`
3. `.planning/phases/02f-v0.9.6-hotfix/reviews/DIFF-review-lrr.md`

Format per persona:

```
# <Persona> Final Diff Review — v0.9.7

Verdict: [PASS | PASS-WITH-CONDITIONS | BLOCK]

## CRIT (block tag)
## MAJOR (must fix before tag)
## MINOR
## Confirmations (correctly implemented)
## Recommended next step
```

Terse. Quote file:line evidence. Threat model: repo-local internal-only.
