# fsd-run-all

This command takes NO positional argument under OpenCode. Ignore any trailing tokens.

Run exactly:

`harness fsd-run-all`

**Chain-driver responsibilities (agent — NOT shell)**:

1. Run `harness status --json` and confirm `.execution_mode == "chain_autopilot"`. If not, surface the `Fix:` line and stop.
2. Drive phase via `.opencode/commands/{discuss,plan,execute,done}.md`.
3. `harness phase set done` → `harness phase next-pending`.
4. Empty → `harness phase autopilot stop`; exit.
5. New slug → `harness phase set <slug>`; loop. **Never re-invoke `/fsd-run-all`.**
6. After every CLI call, run `harness next --json` and read `requires_human`. If `true`, surface the human-readable `command` to the user; do NOT execute it. Stop the chain.

Halt: report and stop. Manual handoff per §5.3.
