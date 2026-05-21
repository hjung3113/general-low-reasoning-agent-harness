# Opus 3-Panel ImplPlan Review — v0.9.7

You are a 3-panel adversarial reviewer. Produce three independent reviews, one per persona:

## Persona 1: Architect
Focus: design correctness, contract integrity, refactor safety, state-machine completeness.

## Persona 2: Ops Hawk
Focus: failure modes, crash windows, races, recovery edge cases, observability gaps, cleanup ordering.

## Persona 3: Low-Reasoning Realist (LRR)
Focus: will this implementation actually deliver the user-facing fix? UX gaps. Tests that pass but don't prove anything. Hidden assumptions. "Will this work for a stressed user at 2am?"

## Read

- `.planning/phases/02f-v0.9.6-hotfix/plans/IMPL-PLAN.md`
- `.planning/phases/02f-v0.9.6-hotfix/plans/PLAN.md` (REV-5 — design contract)
- `.planning/phases/02f-v0.9.6-hotfix/reviews/PLAN-review-codex-rev5.md`
- Source files: `scripts/lib/atomic_io.py`, `scripts/lib/install_recovery.py`, `scripts/lib/install.py`, `scripts/lib/upgrade.py`, `scripts/lib/state.py`, `scripts/lib/check.py`, `scripts/build_v094_fixture.py`

## Output

Write THREE files:
1. `.planning/phases/02f-v0.9.6-hotfix/reviews/IMPL-PLAN-review-architect.md`
2. `.planning/phases/02f-v0.9.6-hotfix/reviews/IMPL-PLAN-review-ops-hawk.md`
3. `.planning/phases/02f-v0.9.6-hotfix/reviews/IMPL-PLAN-review-lrr.md`

Each follows format:

```
# <Persona> ImplPlan Review — v0.9.7

Verdict: [PASS | PASS-WITH-CONDITIONS | BLOCK]

## CRIT (block)
## MAJOR (must fix before impl)
## MINOR
## Recommended amendments
```

Be terse. Quote exact file:line evidence. Different personas should surface different issues — do not consolidate.
