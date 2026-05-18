---
description: Close out a completed phase (read + summarize; no implementation)
argument-hint: <completed plan_id or phase identifier>
mode: orchestrator
---

Use the `workflow-phase-gate` skill for $ARGUMENTS.

Apply `.roo/rules-orchestrator/rules.md` and `.roo/rules/phase-gate.md` first.

Use `/done` to close a completed phase:

1. Run `harness check`. If it prints `warning:` lines naming specific files, treat those files as minimum required reads before trusting the projection. If exit is non-zero, the binary is missing, output is malformed, or it reports an unsupported contract version, fall back to the legacy durable planning read order.
2. Re-read the live gate and active checkpoint.
3. Confirm verification evidence exists in the phase verification file or final summary.
4. Summarize completed work, changed paths, verification, residual risks, and follow-ups.
5. Update durable planning docs only when the phase completion criteria are actually met.
6. Do not start new implementation work from `done`. New work begins from `discuss` or `plan`.

Preflight checklist:

- [ ] The phase implementation work is already finished.
- [ ] Verification evidence exists in the phase verification file or final summary.
- [ ] No new implementation scope is being added.
- [ ] Any `harness check` run in `phase=done` is treated as post-completion audit only.

Run `harness check` before closing the phase.

Advance the lifecycle through the high-level CLI; do NOT direct-edit `.scratch/phase-state.json`:

```text
harness run
```

Do not re-issue approval in `phase=done`.

Done output checklist:

- [ ] completed acceptance criteria
- [ ] verification evidence
- [ ] changed paths
- [ ] residual risks
- [ ] follow-up candidates
- [ ] next action starts from `discuss` or `plan`
