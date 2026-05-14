# TDD Code Rules

- Start with red evidence before production edits: a new failing xUnit test, a clearly identified existing failing test, or a captured failing reproduction converted into a regression test.
- Do not edit production code until the red test has been run and its failure is recorded.
- Use FluentAssertions for assertions.
- Use NSubstitute for collaborators when mocking is appropriate.
- NSubstitute must not replace persistence correctness, SQL behavior, migration behavior, transaction behavior, or ETL writer behavior.
- Use `testcontainers-dotnet` with real MSSQL containers for SQL, EF Core query, Dapper query, migration, writer, restart-safety, idempotency, and transaction behavior.
- Do not use in-memory providers, mocked repositories, or SQLite as proof for MSSQL behavior.
- Keep production changes as small as possible until the test passes.
- After the implementation, run the focused test and record green evidence.
- Refactor only after green evidence exists, then rerun the focused tests.
- There is no "tests later" exception for behavior changes.
- Do not mix unrelated refactors into feature work.
