---
description: Run a single phase end-to-end via the canonical phase gate (autopilot, mode=phase)
argument-hint: [phase-slug]
mode: orchestrator
---

`/fsd-run-phase` runs ONE phase under `execution_mode=phase_autopilot`. For chaining, use `/fsd-run-all`.

Run exactly:

`harness fsd-run-phase $ARGUMENTS`

Do not pass `--allow-network`. Do not run shell snippets or parse the slug yourself; the CLI wrapper validates `$ARGUMENTS`, resolves empty input through `next-pending`, starts `phase_autopilot`, and prints the selected phase.

After start, follow the phase lifecycle in order:
1. Run `harness status` and confirm `Execution mode: phase_autopilot`.
2. Drive the selected phase through discuss/plan/execute using the owning implementation mode.
3. Before code execution, run `harness check`, then `python3 scripts/show_phase_status.py`. Verify `projected_execute_gate_valid=true`, `next_steps.may_edit=true`, no blocking warnings, non-empty `allowed_paths`, and non-empty `verification`; otherwise surface `projected_execute_gate_reason`, `next_steps.read_next`, or warnings and stop.
4. Run the phase verification commands.
5. Run `harness phase set done`.
6. On any non-zero exit, run `harness status`, surface `Halt diary` and `Next action`, then stop. Do not retry or recursively invoke `/fsd-run-phase`.
7. After every CLI call within the phase, run `HARNESS_MACHINE=1 harness next` and read `requires_user_approval`. If `true`, surface `next_user_prompt` to the user; do NOT approve on their behalf. Stop the phase run.
