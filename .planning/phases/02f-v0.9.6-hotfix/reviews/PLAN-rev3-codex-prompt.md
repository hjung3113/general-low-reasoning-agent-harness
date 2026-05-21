# Codex CLI Plan Review (REV-3) — v0.9.7 Hotfix

Final adversarial pass on PLAN.md after REV-3 addressed your REV-2 review's 2 PARTIAL (C-1, C-3) + 1 NEW (N-1).

## Read

- `.planning/phases/02f-v0.9.6-hotfix/plans/PLAN.md` (now REV-3 — see top of file for delta summary)
- `.planning/phases/02f-v0.9.6-hotfix/reviews/PLAN-review-codex-rev2.md`
- v0.9.4 schema: `git show v0.9.4:scripts/lib/state.py` (specifically `file_state` and `write_install_state`)
- Current `scripts/lib/atomic_io.py` for `atomic_install_batch` cleanup semantics
- Current `scripts/lib/install_recovery.py` for existing recovery interface

## Specifically verify closure of:

- **C-1 PARTIAL**: REV-3 introduces a *pending-manifest sidecar* written durably BEFORE the batch. Final `os.replace(pending, installed-manifest.json)` is the boundary. Does this fully address the post-batch / pre-stamp crash window? Examine §3.1, §7.1, §7.2.
- **C-3 PARTIAL**: REV-3 §3.2 + §7.3 normalize the actual v0.9.4 schema fields (`source`, `files.*.installed_at`, `git_user_email_at_install_sha256`, `source_provenance`). Does this scrub every host-specific field that exists in the v0.9.4 manifest payload? Cross-check `write_install_state` (v0.9.4) field by field.
- **N-1**: §3.1 + §7.1 now say `defer_cleanup` default = **False** (legacy behavior preserved), new callers pass `True`. Unambiguous?

## Also surface any NEW issue REV-3 introduced

E.g. ordering bugs in the recovery scan; race between `recover_pending_manifest` and a concurrent in-progress install (probably not an issue per repo-local internal-only threat model, but flag if you spot one); audit-row durability gaps.

## Output

Write `.planning/phases/02f-v0.9.6-hotfix/reviews/PLAN-review-codex-rev3.md`:

```
# Codex Plan Review REV-3 — v0.9.7

Verdict: [PASS | PASS-WITH-CONDITIONS | BLOCK]

## Closure
| Prior | REV-3 Status | Note |
| C-1 | ... | ... |
| C-3 | ... | ... |
| N-1 | ... | ... |

## NEW (if any)

## Recommended next step
```

Terse. If PASS or PASS-WITH-CONDITIONS, Plan moves to ImplPlan.
