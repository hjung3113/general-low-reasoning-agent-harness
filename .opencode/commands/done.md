# OpenCode Done

Use this command to close a completed phase.

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

Done output checklist:

- [ ] completed acceptance criteria
- [ ] verification evidence
- [ ] changed paths
- [ ] residual risks
- [ ] follow-up candidates
- [ ] next action starts from `discuss` or `plan`
