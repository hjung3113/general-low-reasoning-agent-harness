# Changelog

## Unreleased (develop)

### Breaking

- **phase=done contract**: `state_schema_version` 2 makes `phase=done` terminal. Backward migration via `--resume` only (ADR Ledger L12).
- **7-verb verification allowlist** (ADR Ledger L5 + L19): only `python3`, `git`, `jq`, `npx`, `pytest`, `harness`, `make` accepted as verification prefixes.
- Autopilot scaffolding removed (Phase 2 Item 7): `execution_mode` collapses to `manual`; exit code 18 (`EXIT_NO_ACTION_DURING_AUTOPILOT`) dropped.
- State migration v0↔v2 removed (Phase 2 Item 1): all state files now born at `state_schema_version=2`.
