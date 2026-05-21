# Codex CLI ImplPlan REV-2 Review — v0.9.7

REV-2 of IMPL-PLAN addresses your prior 1 CRIT + 4 MAJOR + 4 MINOR AND the Opus 3-panel's 13 CRITs across Architect/Hawk/LRR.

## Read

- `.planning/phases/02f-v0.9.6-hotfix/plans/IMPL-PLAN.md` (REV-2 — top of file has delta summary)
- `.planning/phases/02f-v0.9.6-hotfix/reviews/IMPL-PLAN-review-codex.md` (your REV-1)
- `.planning/phases/02f-v0.9.6-hotfix/reviews/IMPL-PLAN-review-architect.md`
- `.planning/phases/02f-v0.9.6-hotfix/reviews/IMPL-PLAN-review-ops-hawk.md`
- `.planning/phases/02f-v0.9.6-hotfix/reviews/IMPL-PLAN-review-lrr.md`

## Verify

Closure table for:
- Your REV-1: CRIT-1 (pid collision), MAJOR-1 (upgrade wire-in), MAJOR-2 (pending atomicity), MAJOR-3 (sentinel durability), MAJOR-4 (drift gate cache policy)
- Architect REV-1: C-1 (`file_state` pre-batch hash), C-2 (`pairs=` arg), C-3 (upgrade loop-derived), C-4 (sentinel fsync)
- Hawk REV-1: C-1 (pid collision), C-2 (post-finalize sanity), C-3 (.complete.tmp orphans), C-4 (sentinel+.aborted coexist), C-5 (resume idempotency torn-state)
- LRR REV-1: C-1 (InstallFailed pointer), C-2 (exit codes), C-3 (3x idempotency), C-4 (bilingual)

Mark each CLOSED / PARTIAL / OPEN with one-line justification.

Also surface any NEW issue introduced by REV-2 (especially around T1.5 file_state refactor; T4 two-pass; runid format).

## Output

Write `.planning/phases/02f-v0.9.6-hotfix/reviews/IMPL-PLAN-review-codex-rev2.md`:

```
# Codex ImplPlan Review REV-2

Verdict: [PASS | PASS-WITH-CONDITIONS | BLOCK]

## Closure
| Prior | Status | Note |

## NEW (if any)

## Recommended next step
```

Terse.
