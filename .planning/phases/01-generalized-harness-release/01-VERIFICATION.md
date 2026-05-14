# Phase 1 Verification

Required before push:

- `python3 -m unittest scripts/test_harness.py`
- `python3 scripts/harness.py check`
- core-only init/check/target smoke
- OpenCode-only init/check/target smoke
- Roo+OpenCode init/check/target smoke
- `dotnet-etl-mssql` profile plus `tech-csharp`, `tech-mssql`, `workflow-etl`, and `workflow-db-context` composition smoke
- all representative tech/workflow pack install smoke
