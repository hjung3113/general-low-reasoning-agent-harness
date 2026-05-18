# OpenCode Done

Use this command to close a completed phase.

Before proceeding, read every file under `.opencode/profile-rules/` in alphabetical order, if the directory exists. If it is missing or empty, skip silently.

Start with `harness check` and `harness next` when available. If `check` reports warnings, treat named files as minimum required reads before trusting the projection. If either command is missing, fails, emits malformed output, or reports an unsupported contract version, use the legacy durable planning read order.

Preflight checklist:

- [ ] The phase implementation work is already finished.
- [ ] Verification evidence exists in the phase verification file or final summary.
- [ ] No new implementation scope is being added.
- [ ] Any `harness check` run in `phase=done` is treated as post-completion audit only.

1. Re-read the live gate and active checkpoint.
2. Confirm verification evidence exists.
3. Summarize completed work, changed paths, verification, residual risks, and follow-ups.
4. Update durable planning docs only when the phase completion criteria are actually met.

Run `harness check` before closing the phase.

Do not start new implementation work from `done`. New work begins from `discuss` or `plan`.

Advance the lifecycle through the high-level CLI; do NOT direct-edit `.scratch/phase-state.json`:

```text
harness run
```

Do not re-issue approval in `phase=done`. The approval provenance is preserved from the prior execute gate.

Done output checklist:

- [ ] completed acceptance criteria
- [ ] verification evidence
- [ ] changed paths
- [ ] residual risks
- [ ] follow-up candidates
- [ ] next action starts from `discuss` or `plan`
