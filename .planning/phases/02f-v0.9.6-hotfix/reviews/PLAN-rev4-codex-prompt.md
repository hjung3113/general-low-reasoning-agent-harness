# Codex CLI Plan Review (REV-4) — v0.9.7

Final pass. REV-4 addresses your REV-3 N-2 (recovery completion-proof gap) via a `$STAGING.complete` zero-byte sentinel written by `atomic_install_batch` after all renames succeed.

## Read

- `.planning/phases/02f-v0.9.6-hotfix/plans/PLAN.md` (REV-4)
- `.planning/phases/02f-v0.9.6-hotfix/reviews/PLAN-review-codex-rev3.md` (your prior verdict)

## Verify

- Does the sentinel-based recovery contract close N-2?
- Is the sentinel write order correct (after all renames + journal flushes, before `atomic_install_batch` returns)?
- New issues introduced by §7.2's revised decision matrix?

## Output

Write `.planning/phases/02f-v0.9.6-hotfix/reviews/PLAN-review-codex-rev4.md`:

```
# Codex Plan Review REV-4 — v0.9.7

Verdict: [PASS | PASS-WITH-CONDITIONS | BLOCK]

## N-2 status: [CLOSED | PARTIAL | OPEN]

## NEW (if any)

## Recommended next step
```

Terse.
