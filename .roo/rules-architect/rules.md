# Architect Rules

- Do not write implementation code.
- Prefer ADRs for durable decisions.
- Name the pipeline stages and state boundaries before proposing code structure.
- For ETL systems, decide restart, idempotency, ordering, buffering, and observability up front.
- Include test strategy in every implementation plan.
- Avoid introducing MediatR, CQRS, or complex frameworks unless the project has a concrete need.

