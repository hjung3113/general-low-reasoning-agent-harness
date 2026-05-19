---
description: Chain roadmap phases under chain_autopilot until next-pending is empty
argument-hint:
mode: orchestrator
---

`/fsd-run-all` takes NO positional argument. First phase from `next-pending`.

Run exactly:

`harness fsd-run-all`

**Chain-driver responsibilities (agent — NOT shell loop)**:

1. Run `harness status` and confirm `Execution mode: chain_autopilot`. If not, surface the fix guidance and stop.
2. Drive current phase to done. Honor every halt condition.
3. `harness phase set done` → `harness phase next-pending`.
4. Empty result → `harness phase autopilot stop` and exit.
5. New slug → `harness phase set <slug>` and loop to 2. **Do NOT recursively invoke `/fsd-run-all`.**
6. After every CLI call, run `HARNESS_MACHINE=1 harness next` and read `requires_user_approval`. If `true`, surface `next_user_prompt` to the user; do NOT approve on their behalf. Stop the chain.

If the harness prints a `[y/N]` prompt, stop and ask the user to confirm from their own terminal. Do not answer the prompt yourself — speed-bump is the user's checkpoint.

Halt on ADR-001 reject, approve exit 8, audit-chain break, budget exhausted. On halt: `execution_mode` flips to manual; halt diary populated; report and stop.
