---
name: workflow-etl
description: Use for extract-transform-load or ELT workflows regardless of language, database, or orchestration tool.
---

# Workflow ETL

## Workflow

1. Identify source, extraction method, transform rules, load target, and observability.
2. Record restart, idempotency, deduplication, and backfill behavior.
3. Define schema drift and bad-record handling.
4. Pair with database or language tech packs only when confirmed.
5. Verify with a representative fixture, dry run, or integration test approved by the plan.

## DB-Backed ETL Guardrails

When ETL is database-backed, pair this skill with the confirmed database tech pack and `workflow-db-context`.

- Missing DB context means `needs-db-context`.
- Row-by-row writes are forbidden by default for bulk ETL paths.
- Prefer staging plus set-based merge/upsert when the target database supports it.
- Define restart, idempotency, replay, and backfill before execute.
- Define transaction boundaries before writer or migration changes.

## Compatibility Example

For a C#/.NET 10 + MSSQL ETL target, combine:

- `tech-csharp`
- `tech-mssql`
- `workflow-etl`
- `workflow-db-context`
- `verification-contract`
- `risk-review`

This reproduces the specialized ETL guardrails through pack composition instead of making them core defaults.
