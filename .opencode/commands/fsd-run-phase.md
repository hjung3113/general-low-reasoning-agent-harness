# fsd-run-phase

This command takes NO positional argument under OpenCode (positional substitution unsupported — empirical finding). Ignore any tokens that appear after `/fsd-run-phase` in the user message.

Run exactly:

`harness fsd-run-phase`

Do not pass `--allow-network`. Do not run shell snippets. Do not parse or forward trailing tokens; OpenCode positional substitution is unsupported, so the CLI wrapper must receive no slug and will choose `next-pending`.

After start, follow the phase lifecycle in order:
1. Run `harness status` and confirm `Execution mode: phase_autopilot`.
2. Drive the selected phase via `.opencode/commands/{discuss,plan,execute,done}.md`.
3. Before code execution, run `harness check`, then `python3 scripts/show_phase_status.py`. Verify `projected_execute_gate_valid=true`, `next_steps.may_edit=true`, no blocking warnings, non-empty `allowed_paths`, and non-empty `verification`; otherwise surface `projected_execute_gate_reason`, `next_steps.read_next`, or warnings and stop.
4. Run the phase verification commands.
5. Run `harness phase set done`.
6. On any non-zero exit, run `harness status`, surface `Halt diary` and `Next action`, then stop.
7. After every CLI call within the phase, run `HARNESS_MACHINE=1 harness next` and read `requires_user_approval`. If `true`, surface `next_user_prompt` to the user; do NOT approve on their behalf. Stop the phase run.

If the harness prints a `[y/N]` prompt, stop and ask the user to confirm from their own terminal. Do not answer the prompt yourself — speed-bump is the user's checkpoint.
