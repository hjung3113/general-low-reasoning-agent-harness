# fsd-run-phase

This command takes NO positional argument under OpenCode (positional substitution unsupported — empirical finding). Ignore any tokens that appear after `/fsd-run-phase` in the user message.

Run exactly:

`harness fsd-run-phase`

Do not pass `--allow-network`. Do not run shell snippets. Do not parse or forward trailing tokens; OpenCode positional substitution is unsupported, so the CLI wrapper must receive no slug and will choose `next-pending`.

After start, follow the phase lifecycle in order:
1. Run `harness status` and confirm `Execution mode: phase_autopilot`.
2. Drive the selected phase via `.opencode/commands/{discuss,plan,execute,done}.md`.
3. Before code execution, verify `harness status --json` reports `can_enter_execute=true` or stop and surface the `Fix:` line.
4. Run the phase verification commands.
5. Run `harness phase set done`.
6. On any non-zero exit, run `harness status`, surface `Halt diary` and `Next action`, then stop.
