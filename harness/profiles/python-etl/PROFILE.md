# python-etl profile

Stack-aware harness preset for Python ETL / data pipeline projects.

## When to use

- The repository hosts one or more ETL jobs implemented in Python.
- Database is selected separately at install time.

## Activations

- Default packs: `workflow-core`, `workflow-etl`, `tech-python`.
- Augment rules:
  - `etl-tdd` (tdd-code)
  - `restart-idempotency` (ops-observability)
  - `data-bug-trace` (diagnose)
  - `etl-review` (review)
