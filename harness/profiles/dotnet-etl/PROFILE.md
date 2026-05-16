# dotnet-etl profile

Stack-aware harness preset for .NET / C# ETL projects. Stack is fixed; database
selection is independent and is set at install time via `--db`.

## When to use

- The repository hosts one or more ETL jobs implemented in C# / .NET.
- The database backing those jobs is selected separately (mssql, postgresql, none).

## What this profile activates

- Default packs: `workflow-core`, `workflow-etl`, `tech-csharp`.
- Augment rules under `.roo/rules-<mode>/` and `.opencode/profile-rules/`:
  - `etl-tdd` (tdd-code)
  - `restart-idempotency` (ops-observability)
  - `data-bug-trace` (diagnose)
  - `etl-review` (review)

## What this profile does not do

- It does not pick a database engine. Use `--db mssql` or `--db postgresql` to
  add the corresponding `tech-*` and `workflow-db-context` packs.
- It does not select a test runner. The TDD augment rule defers to repository
  evidence.
