---
description: Close out a completed phase (read + summarize; no implementation)
argument-hint: <completed plan_id or phase identifier>
mode: orchestrator
---

Use the `workflow-phase-gate` skill for $ARGUMENTS.

Apply `.roo/rules-orchestrator/rules.md` and `.roo/rules/phase-gate.md` first.

Use `/done` to close a completed phase:

1. Start with `python3 scripts/show_phase_status.py` when available. If it reports warnings, treat named files as minimum required reads before trusting the projection. If it is missing, fails, emits malformed output, or reports an unsupported contract version, use the legacy durable planning read order.
2. Re-read the live gate and active checkpoint.
3. Confirm verification evidence exists in the phase verification file or final summary.
4. Summarize completed work, changed paths, verification, residual risks, and follow-ups.
5. Update durable planning docs only when the phase completion criteria are actually met.
6. Do not start new implementation work from `done`. New work begins from `discuss` or `plan`.

Preflight checklist:

- [ ] The phase implementation work is already finished.
- [ ] Verification evidence exists in the phase verification file or final summary.
- [ ] No new implementation scope is being added.
- [ ] Any `python3 scripts/harness.py check --worktree` run in `phase=done` is treated as post-completion audit only.

Run `python3 scripts/harness.py check --worktree` before marking done.

Advance the lifecycle via the CLI; do NOT direct-edit `.scratch/phase-state.json`:

```text
python3 scripts/harness.py phase set done                        # execute → done (CLI preserves approved fields verbatim, G2-C)
python3 scripts/harness.py phase set discuss --reset-approval    # from done, start a new cycle (safety prompt required)
```

`python3 scripts/harness.py phase approve` in `phase=done` is a no-op error (exit 6 / `EXIT_WRONG_PHASE_FOR_VERB`, G2-C). Do NOT re-issue it.

Done output checklist:

- [ ] completed acceptance criteria
- [ ] verification evidence
- [ ] changed paths
- [ ] residual risks
- [ ] follow-up candidates
- [ ] next action starts from `discuss` or `plan`
