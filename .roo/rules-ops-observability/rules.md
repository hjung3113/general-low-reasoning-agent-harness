# Ops Observability Rules

- Every operational workflow needs structured logs, stable fields, and failure signals.
- Prefer explicit processing events for operator-visible failures.
- Define retry ownership and boundaries.
- Start operational implementation with red evidence before production edits.
- Record green evidence after implementation and refactor only after green.
- Make graceful shutdown behavior testable; if a behavior cannot be tested, document the reason and review it explicitly.
- Avoid unbounded queues, unbounded retries, and silent drops.
- Include metrics for throughput, latency, failures, retries, and backlog where relevant.
