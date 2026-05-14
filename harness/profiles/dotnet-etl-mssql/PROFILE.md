# Dotnet ETL MSSQL Profile

Use this profile only when the target project is explicitly a C#/.NET ETL project backed by Microsoft SQL Server.

This profile recreates the old specialized harness behavior through an opt-in profile instead of core defaults.

## Activation Evidence

At least one of these must be true:

- user explicitly selects `--profiles dotnet-etl-mssql`
- repository has confirmed `.sln` or `.csproj` files plus SQL Server persistence evidence plus ETL/data movement scope
- an approved hydration summary confirms C#/.NET, MSSQL, and ETL

## Guardrails

- Target .NET 10 unless repository evidence or the user explicitly overrides it.
- Target Microsoft SQL Server for persistence unless repository evidence or the user explicitly overrides it.
- Use pipeline-first ETL reasoning: source -> extract -> transform -> validate -> stage -> load -> observe.
- DB behavior requires SQL Server-backed verification. SQLite, in-memory providers, and mocked repositories are not sufficient proof for SQL Server behavior.
- Prefer Testcontainers or the repository's approved real SQL Server verification strategy for persistence, migration, query, writer, restart, idempotency, and transaction behavior.
- Row-by-row ETL writes are forbidden by default. Prefer staging plus set-based merge/upsert; exceptions require documented approval with volume limits and rationale.
- Define transaction boundaries, restart behavior, idempotency, replay behavior, and backfill behavior before execute.
- DB-backed ETL work without a usable DB context snapshot must return `needs-db-context` instead of guessing.

## Required Packs

- `workflow-core`
- `tech-csharp`
- `tech-mssql`
- `workflow-etl`
- `workflow-db-context`

