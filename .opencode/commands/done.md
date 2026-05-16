# OpenCode Done

Use this command to close a completed phase.

Before proceeding, read every file under `.opencode/profile-rules/` in alphabetical order, if the directory exists. If it is missing or empty, skip silently.

Start with `python3 scripts/show_phase_status.py` when available. If it reports warnings, treat named files as minimum required reads before trusting the projection. If it is missing, fails, emits malformed output, or reports an unsupported contract version, use the legacy durable planning read order.

Preflight checklist:

- [ ] The phase implementation work is already finished.
- [ ] Verification evidence exists in the phase verification file or final summary.
- [ ] No new implementation scope is being added.
- [ ] Any `check --worktree` run in `phase=done` is treated as post-completion audit only.

1. Re-read the live gate and active checkpoint.
2. Confirm verification evidence exists.
3. Summarize completed work, changed paths, verification, residual risks, and follow-ups.
4. Update durable planning docs only when the phase completion criteria are actually met.

Run `python3 scripts/harness.py check --worktree` before marking done.

Do not start new implementation work from `done`. New work begins from `discuss` or `plan`.

Advance the lifecycle via the CLI; do NOT direct-edit `.scratch/phase-state.json`:

```text
harness phase set done                               # long form: python3 scripts/harness.py phase set done; execute → done (CLI preserves approved fields per G2-C)
harness phase set discuss --reset-approval           # long form: python3 scripts/harness.py phase set discuss --reset-approval; from done, start a new cycle (safety prompt required)
```

`python3 scripts/harness.py phase approve` in `phase=done` is a no-op error (exit 6, G2-C). The `approved`, `approved_by`, and `approved_at` fields are preserved verbatim from the prior `execute→done` transition; do NOT re-issue `phase approve`.

Done output checklist:

- [ ] completed acceptance criteria
- [ ] verification evidence
- [ ] changed paths
- [ ] residual risks
- [ ] follow-up candidates
- [ ] next action starts from `discuss` or `plan`
