---
name: workflow-db-context
description: Use when database-backed work needs schema, routine, job, migration, or persistence context before planning or execution.
---

# Workflow DB Context

Use this skill when work depends on database shape or behavior.

## Workflow

1. Check whether the repository has a current DB context snapshot or documented substitute.
2. Record the snapshot path, source environment, freshness, and scope.
3. If the snapshot is missing or insufficient, return `needs-db-context` instead of guessing schema, routines, jobs, indexes, or persistence behavior.
4. For write paths, record transaction boundaries, rollback, idempotency, replay, and restart expectations.
5. Pair with a database tech pack such as `tech-mssql` or `tech-postgresql` only when the database is confirmed.

## Stop Conditions

- no schema evidence
- unknown migration owner
- unknown transaction boundary
- unknown restart or replay behavior
- verification requires an unapproved database connection

