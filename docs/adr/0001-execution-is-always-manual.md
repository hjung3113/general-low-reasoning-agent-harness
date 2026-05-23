# Execution is always manual

The harness has one execution mode: `manual`. A human (or supervising agent) drives the `discuss → plan → execute → done` transitions interactively. There is no autopilot, no chain-autopilot, no budget-bounded auto-execution; legacy values (`phase_autopilot`, `chain_autopilot`, `auto`, `chain`) are coerced to `manual` on read (`scripts/lib/phase_state.py:27-35`).

This is a deliberate tradeoff. Autopilot existed in earlier versions and was removed in Milestone 2 Item 7 (~816 LOC of module code + ~1200 LOC of tests). The harness is an internal tool whose value comes from making low-reasoning agents *pause* at gates, not from running long autonomous chains; the autopilot infrastructure was load-bearing complexity that contradicted the product stance. Reversing this would mean re-introducing budgets, halt-diary tracking, and chain-resumption logic — not impossible, but a meaningful project.
