---
name: tech-mssql
description: Use when Microsoft SQL Server is confirmed. Keeps SQL Server-specific assumptions out of core and inside explicit pack scope.
---

# Tech MSSQL

Use only after Microsoft SQL Server is confirmed.

## Evidence

Look for SQL Server connection strings, T-SQL scripts, migrations, SQL Server docs, container setup, or user confirmation.

## Rules

- Do not assume ORM, migration tool, schema ownership, or container availability.
- Identify transaction boundaries, idempotency, locking, and rollback expectations before execute.
- Use parameterized SQL for application queries.
- Verification must use the repository's approved SQL Server strategy or explicitly document why it cannot.
- For SQL Server persistence behavior, SQLite, in-memory providers, and mocked repositories are not sufficient proof unless the approved plan explicitly limits scope to non-SQL behavior.
- For confirmed ETL bulk writes, prefer staging plus set-based merge/upsert; row-by-row writes require documented approval.
- If schema context is missing for DB-backed work, return `needs-db-context`.

## Verification

Use existing integration tests, migration checks, container tests, or approved dry-run scripts.
