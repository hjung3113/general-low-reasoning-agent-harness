# Codex CLI Final Diff Review — v0.9.7

Final adversarial pass on the v0.9.7 implementation diff before tagging.

## Diff scope

- Branch: `develop` (14 commits ahead of `origin/develop`)
- Range: `main..develop` (54 files, +5440 / -515)
- Planning context: `.planning/phases/02f-v0.9.6-hotfix/plans/IMPL-PLAN.md` (REV-2)

## Inspect

`git log --oneline main..develop` for commit list. Per-task commits T1 through T12.

## Attack

1. **Phase order (T3 install.py + T4 upgrade.py)**: does the actual implementation match IMPL-PLAN's phase order: stage → compose payload (staged hashes) → pending sidecar → batch → finalize → verify → cleanup?
2. **Sentinel durability (T1 atomic_io.py)**: are fsync calls actually present around sentinel write?
3. **Runid format**: is it `pid + iso + token_hex(3)` everywhere, no bare pids?
4. **`.aborted` precedence (T2 install_recovery.py)**: does `_recover_pending_manifest` check `.aborted` BEFORE sentinel?
5. **`file_state(staged=)` (T1.5 state.py)**: does the refactor preserve all legacy callers? Are any callers still hashing destination when they should hash staged?
6. **Two-pass upgrade (T4 upgrade.py)**: is Pass A genuinely write-free? Or does it mutate `installed-manifest.json` mid-flow?
7. **Bilingual error messages**: do raised errors contain `state repair` invocation string?
8. **Exit codes**: does `harness state repair` actually return 0/1/2 per IMPL-PLAN contract?
9. **KNOWN_FAILING_TESTS.md drift gate**: does it actually fail (rc=1) on stale cache without `HARNESS_KNOWN_FAILURES_ALLOW_STALE=1`?
10. **CHANGELOG honesty (T11)**: does the entry truthfully describe what shipped (atomic for harness-owned only; managed-append still in-place)?
11. **Version refs (T11)**: any leftover `v0.9.6` references outside CHANGELOG/historical context?
12. **Test coverage**: does the test diff actually exercise the SIGTERM / crash-window scenarios, or are they bypassed via mocks?

## Output

Write `.planning/phases/02f-v0.9.6-hotfix/reviews/DIFF-review-codex.md`:

```
# Codex Final Diff Review — v0.9.7

Verdict: [PASS | PASS-WITH-CONDITIONS | BLOCK]

## CRIT (block tag)
## MAJOR (fix before tag)
## MINOR
## Confirmed correct implementations
## Recommended next step
```

Terse. Quote file:line evidence. Threat model is repo-local internal-only — do not chase external attackers.
