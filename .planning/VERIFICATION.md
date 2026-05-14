# VERIFICATION - Global Evidence Ledger

| Date | Phase | Check | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-05-11 | Phase 1 | `.planning/` file tree exists | PASS | `find .planning -maxdepth 3 -type f \| sort` |
| 2026-05-11 | Phase 1 | Live phase state validates | PASS | `npx --yes ajv-cli validate --spec=draft2020 -s .scratch/phase-state.schema.json -d .scratch/phase-state.json` |
| 2026-05-11 | Phase 1 | Example phase state validates | PASS | `npx --yes ajv-cli validate --spec=draft2020 -s .scratch/phase-state.schema.json -d .scratch/phase-state.example.json` |
| 2026-05-11 | Phase 1 | Restart references exist | PASS | `rg -n "STATE.md|phase-state|checkpoint" AGENTS.md README.md docs/phase-gate-harness.md .planning` |
| 2026-05-11 | Phase 1 | `/ops` command routing docs aligned | PASS | Stale direct `ops-observability` command-mode references returned no hits in `.roo/commands` and `docs/roo-orchestration-design.md`. |
| 2026-05-11 | Phase 1 follow-up | `.roomodes` parses as JSON | PASS | `jq . .roomodes >/dev/null` |
| 2026-05-11 | Phase 1 follow-up | Roo mode planning ownership regex | PASS | Node regex probe: planning modes can edit `.planning/`; implementation modes cannot. |
| 2026-05-11 | Phase 1 follow-up | Temporary handoff path removed from operational planning evidence | PASS | Phase context, plan, checkpoint, and summary now cite tracked `.planning/` files instead of machine-local temp files. |
| 2026-05-11 | Phase 1 follow-up | Codebase planning docs expanded | PASS | Added harness-focused `ARCHITECTURE`, `STACK`, `TESTING`, `INTEGRATIONS`, and `CONCERNS` docs under `.planning/codebase/`. |
| 2026-05-11 | Phase 1 follow-up | README workflow guide updated | PASS | README now maps slash commands to Roo modes and workflow skills, lists skill purposes, mode ownership, phase gate, and verification commands. |
| 2026-05-11 | Phase 1 follow-up | Korean README zero-to-done workflow added | PASS | README now explains starting from idea or design docs, discuss/plan/execute/review/done flow, skill usage, and document-centered handoff. |
| 2026-05-15 | Phase 1 release | Unit tests | PASS | `python3 -m unittest scripts/test_harness.py` -> 53 tests passed. |
| 2026-05-15 | Phase 1 release | Source checks | PASS | `python3 scripts/harness.py check` and `python3 scripts/harness.py check --worktree` -> exit 0. |
| 2026-05-15 | Phase 1 release | Target release smoke matrix | PASS | `python3 scripts/release_smoke_test.py` covers core, OpenCode, Roo, both, python-analysis, dotnet-etl, web, and all-packs. |
| 2026-05-15 | Phase 1 release | Pre-push adversarial review | BLOCKED THEN ADDRESSED | Subagent `019e2782-6d80-7453-8af9-c20501d1a8d9` found missing ledger evidence, placeholder verification, and missing `check --worktree` tests; follow-up changes addressed all three. |

Add new rows when a phase closes or a cross-phase verification command becomes important.
