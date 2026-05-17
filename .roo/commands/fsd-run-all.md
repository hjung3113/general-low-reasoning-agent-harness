---
description: Chain roadmap phases under chain_autopilot until next-pending is empty
argument-hint:
mode: orchestrator
---

`/fsd-run-all` takes NO positional argument. First phase from `next-pending`.

Run exactly:

`harness fsd-run-all`

**Chain-driver responsibilities (agent — NOT shell loop)**:

1. Run `harness status --json` and confirm `.execution_mode == "chain_autopilot"`. If not, surface the `Fix:` line and stop.
2. Drive current phase to done. Honor every halt condition.
3. `harness phase set done` → `harness phase next-pending`.
4. Empty result → `harness phase autopilot stop` and exit.
5. New slug → `harness phase set <slug>` and loop to 2. **Do NOT recursively invoke `/fsd-run-all`.**
6. After every CLI call, run `harness next --json` and read `requires_human`. If `true`, surface the human-readable `command` to the user; do NOT execute it. Stop the chain.

Halt on ADR-001 reject, approve exit 8, audit-chain break, budget exhausted. On halt: `execution_mode` flips to manual; halt diary populated; report and stop.
