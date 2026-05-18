# fsd-run-all

This command takes NO positional argument under OpenCode. Ignore any trailing tokens.

Run exactly:

`harness fsd-run-all`

**Chain-driver responsibilities (agent — NOT shell)**:

1. Run `harness status` and confirm `Execution mode: chain_autopilot`. If not, surface the fix guidance and stop.
2. Drive phase via `.opencode/commands/{discuss,plan,execute,done}.md`.
3. `harness phase set done` → `harness phase next-pending`.
4. Empty → `harness phase autopilot stop`; exit.
5. New slug → `harness phase set <slug>`; loop. **Never re-invoke `/fsd-run-all`.**
6. After every CLI call, run `HARNESS_MACHINE=1 harness next` and read `requires_user_approval`. If `true`, surface `next_user_prompt` to the user; do NOT approve on their behalf. Stop the chain.

Halt: report and stop. Manual handoff per §5.3.
