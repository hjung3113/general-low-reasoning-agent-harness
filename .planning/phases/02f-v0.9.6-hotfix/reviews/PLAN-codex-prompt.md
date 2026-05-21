# Codex CLI Plan Review — v0.9.7 Hotfix (formerly tagged 02f-v0.9.6-hotfix)

You are an adversarial reviewer (low-reasoning realist + ops hawk hybrid). Target version is **v0.9.7** (v0.9.6 already shipped as docs-only).

## Context

- Repo: `general-low-reasoning-agent-harness` (internal-only tool, repo-local threat model — sandboxed users only)
- Predecessor: `v0.9.6` (`06241f8`, docs-only)
- Substantive deferred items from v0.9.5/v0.9.6 carrying forward
- Plan REV-1 has already passed Opus 3-panel (Architect, Ops Hawk, Low-Reasoning Realist). 9 CRITs were closed by REV-1 reinforcement. Codex is the final external check before ImplPlan.

## Read these files

1. `.planning/phases/02f-v0.9.6-hotfix/plans/PLAN.md` (REV-1)
2. `.planning/phases/02f-v0.9.6-hotfix/reviews/PLAN-review-architect.md`
3. `.planning/phases/02f-v0.9.6-hotfix/reviews/PLAN-review-ops-hawk.md`
4. `.planning/phases/02f-v0.9.6-hotfix/reviews/PLAN-review-low-reasoning-realist.md`
5. `scripts/lib/atomic_io.py` (T14a helper to be wired)
6. `scripts/lib/install.py` (init flow, lines ~300-310 per Plan §7.1)
7. `scripts/lib/upgrade.py` (upgrade flow, lines ~755-758)
8. `scripts/build_v094_fixture.py` (EXCLUDE_NAMES at line 37)
9. `tests/test_upgrade_from_v094_clean.py`
10. `tests/test_upgrade_from_v094_with_workaround.py`

## Attack vectors (specifically address Plan §10)

1. **Atomic wire-in completeness**: Will any direct `shutil.copyfile` remain on the harness-owned write path after T1? Audit `install.py` + `upgrade.py` line by line.
2. **State-stamp ordering**: If SIGTERM lands BETWEEN per-file atomic rename batch completion AND `installed-manifest.json` write, what does `install_recovery` observe? Plan §7.1 claims journal anchors; is this true with current T14a + T14b code?
3. **Fixture determinism**: Will `build_v094_fixture.py` produce identical bytes across machines/runs after `.harness/` inclusion? Audit `installed-manifest.json` content for embedded host-specific fields (paths, timestamps, hashes of host-specific paths).
4. **Real-fixture test value**: Do the rewritten T15 tests actually exercise upgrade code paths the synthetic-seed version skipped? Or do they just shift the seed location?
5. **KNOWN_FAILING_TESTS.md drift**: Plan §5 mitigation is "count assertion". Does count-only catch regression where a previously-failing test PASSES and a different one starts failing (same count, different identity)?
6. **`harness check` staging detection**: Latency cost on real repos? False positives (e.g., a stale `.staging-*` from an unrelated tool)?
7. **Q1 default-on atomic**: Risk of breaking existing user installs that have non-default filesystems (eCryptfs, NFS-mounted target)?
8. **Scope-out integrity**: Are managed-append + write_text_file genuinely safe to leave non-atomic for v0.9.7? Plan §3.1 defers them; defend or attack.
9. **CHANGELOG honesty**: Plan §5 row 1 commits to honest CHANGELOG. Draft the exact CHANGELOG one-liner that would satisfy this — does the current Plan support it?
10. **Skip-upgrade UX (LRR CRIT-2)**: Plan documents v0.9.4→v0.9.7 skip as "needs intermediate v0.9.5". Are there detection hooks already present in `upgrade.py` that could cheaply emit a UX hint? If yes, defer-to-v0.9.8 is wrong.

## Output format

Produce `.planning/phases/02f-v0.9.6-hotfix/reviews/PLAN-review-codex.md` with:

```
# Codex Plan Review — v0.9.7

Verdict: [PASS | PASS-WITH-CONDITIONS | BLOCK]

## CRIT (block release)
- C-N: <title>
  Evidence: <file:line or test output>
  Fix: <concrete action>

## MAJOR (must address before release)
## MINOR (nice-to-have)
## CONFIRMATIONS (REV-1 closures that actually hold)
## Recommended Plan amendments
```

Be terse. Quote exact code/lines. No platitudes. Attack mercilessly — repo-local threat model means we don't care about external attackers, but we DO care about correctness, race conditions, kill-mid-install integrity, and dev-fixture determinism.

Stay within the existing scope-out list unless you find a CRIT that requires expanding it.
