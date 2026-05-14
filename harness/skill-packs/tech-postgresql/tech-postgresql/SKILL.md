---
name: tech-postgresql
description: Use when PostgreSQL is confirmed. Keeps PostgreSQL-specific assumptions explicit and verified.
---

# Tech PostgreSQL

Use only after PostgreSQL is confirmed.

## Evidence

Look for PostgreSQL connection strings, migrations, SQL files, Docker Compose services, extensions, or user confirmation.

## Rules

- Do not assume ORM, migration tool, extension availability, schema ownership, or local database access.
- Identify transaction, isolation, migration, and rollback expectations before execute.
- Use parameterized SQL for application queries.
- Verification must use the repository's approved PostgreSQL strategy or explicitly document why it cannot.

## Verification

Use existing integration tests, migration checks, container tests, or approved dry-run scripts.

