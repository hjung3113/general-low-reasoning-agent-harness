# Review Rules

- Lead with findings ordered by severity.
- Include file and line references when available.
- Prioritize correctness, data loss, idempotency, SQL safety, performance, async pitfalls, and missing tests.
- Review C# async code for blocking waits, missing cancellation, unbounded concurrency, and swallowed exceptions.
- Review TDD evidence: red evidence before production edits, green evidence after implementation, refactor only after green, and no "tests later" loophole.
- Review database test coverage: SQL, EF Core query, Dapper query, migration, writer, restart, idempotency, and transaction behavior must use `testcontainers-dotnet` with real MSSQL containers.
- Treat in-memory providers, mocked repositories, SQLite, or unit-only tests as insufficient evidence for MSSQL behavior.
- Review SQL for parameterization, injection risk, row-by-row ETL writes, non-sargable predicates, missing indexes, unsafe MERGE behavior, staging correctness, and transaction boundaries.
- Confirm EF Core is the default data access path and Dapper is limited to documented complex or performance-sensitive read-query exceptions.
- Confirm high-volume writes use SqlBulkCopy into staging plus set-based MERGE/upsert.
- Review ETL changes against the canonical flow: source -> parse -> normalize -> state -> merge -> buffer -> write -> observe.
- Check ETL idempotency, restart safety, source traceability, backpressure, bounded buffers, duplicate handling, replay behavior, and bulk-write behavior.
- If no issues are found, state remaining test gaps or residual risk.
