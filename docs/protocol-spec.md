# General Low-Reasoning Agent Harness Protocol

## Purpose

This protocol lets weak or low-reasoning agents work safely across many repositories without binding the workflow to one stack, database, editor, or client.

The invariant is:

```text
one canonical planning memory
one live gate
many adapters
composable skill plugins
optional project profiles and packs
```

## Core Protocol

The core protocol is client-neutral and stack-neutral.

Agents must follow:

1. `discuss`
2. `plan`
3. `execute`
4. `done`

Fresh sessions must start with the status projection when it is installed:

Start with `python3 scripts/show_phase_status.py` when available. If it reports warnings, treat named files as minimum required reads before trusting the projection. If it is missing, fails, emits malformed output, or reports an unsupported contract version, use the legacy durable planning read order.

`.planning/**` explains the project. `.scratch/phase-state.json` only approves or blocks the current work.

Resolve active phase docs deterministically:

1. Prefer explicit pointers in `.scratch/phase-state.json`: `checkpoint_path`, `plan_path`, and `state_path`.
2. If pointers are missing during `discuss`, choose the highest numbered directory under `.planning/phases/**`.
3. Within a phase directory, read matching files in this order: `*-CONTEXT.md`, `*-PLAN.md`, `*-REVIEW.md`, `*-VERIFICATION.md`, `*-SUMMARY.md`, `*-CHECKPOINTS.md`.
4. If an expected file is absent, record that it is absent. Do not infer hidden requirements from a missing file.

## Phase Rules

### Discuss

Allowed:

- inspect repository evidence
- ask one concrete question at a time
- record alignment notes when requested
- propose active skills and profiles

Forbidden:

- application-code edits
- execute approval
- unconfirmed stack-specific commands

Exit criteria:

- confirmed facts, inferred facts, rejected assumptions, open questions, and recommended next phase are recorded.

### Plan

Allowed:

- write phase plans
- define allowed path candidates
- define verification commands
- run adversarial review

Forbidden:

- application-code edits
- self-approval for execute

Exit criteria:

- `plan_id`, allowed paths, blocked paths or omission reason, verification, review checks, and approval request are ready.

### Execute

Allowed:

- edit only approved paths
- run approved verification
- update evidence

Forbidden:

- edits outside `allowed_paths`
- changing phase scope silently
- continuing after phase-gate drift

Required live gate fields:

- `phase=execute`
- `approved=true`
- `plan_id`
- `allowed_paths`
- `verification`
- `state_path`
- `plan_path`
- `checkpoint_path`
- `approved_by`
- `approved_at`

### Done

Allowed:

- summarize completed work
- record verification evidence
- record residual risk and follow-ups

Forbidden:

- starting new implementation work

## Adapter Contract

Each adapter must define:

- installed files
- command or mode names
- phase mapping
- restart read order
- execute approval checks
- allowed-path behavior
- verification recording
- stale-file and retired-file handling

Adapters must not own project truth. Roo, OpenCode, Codex, or future clients all read the same `.planning/**` and `.scratch/phase-state.json`.

## OpenCode Compatibility

OpenCode is a first-class adapter target.

Valid target shapes:

- core only
- core + Roo
- core + OpenCode
- core + Roo + OpenCode

`check --target` validates core plus installed adapters. `check --target --adapter opencode` validates OpenCode without requiring Roo files. Missing uninstalled Roo files are not findings.

OpenCode intentionally ships phase primitives: `discuss`, `plan`, `execute`, and `done`. Workflow specialization comes from installed `.agents/skills/**` packs, not from duplicating every Roo slash command under `.opencode/commands/**`.

## Skill Plugins

Skills are composable plugins selected per request, not hard-coded tech-stack presets.

The default `workflow-core` pack includes:

- `repository-evidence-research`
- `skill-plugin-composition`
- `ecosystem-skill-research`
- `verification-contract`
- `risk-review`
- `multi-agent-review`
- `release-readiness-audit`
- `data-workflow`
- `integration-boundary`

Additional shipped tech packs:

- `tech-python`
- `tech-react`
- `tech-typescript`
- `tech-tailwind`
- `tech-csharp`
- `tech-mssql`
- `tech-postgresql`

Additional shipped workflow packs:

- `workflow-data-analysis`
- `workflow-data-processing`
- `workflow-etl`
- `workflow-db-context`
- `workflow-web-development`
- `workflow-tdd`
- `workflow-debugging`
- `workflow-code-review`
- `workflow-skill-authoring`
- `workflow-security-review`

Selection rules:

- use repository evidence first
- activate the smallest useful skill set
- record active skills and rejected skills
- do not use inactive profile commands
- create project-specific skills only after constraints are known

## Specialization By Composition

Specialized harness behavior must be reproduced through explicit profile and pack composition, not through core defaults.

Example: a C#/.NET + MSSQL + ETL target uses:

```bash
python3 scripts/harness.py init \
  --target /path/to/dotnet-etl-project \
  --adapters roo,opencode \
  --profiles generic,dotnet-etl-mssql \
  --packs workflow-core,tech-csharp,tech-mssql,workflow-etl,workflow-db-context
```

This composition must install:

- `docs/profiles/dotnet-etl-mssql.md`
- `.agents/skills/tech-csharp/SKILL.md`
- `.agents/skills/tech-mssql/SKILL.md`
- `.agents/skills/workflow-etl/SKILL.md`
- `.agents/skills/workflow-db-context/SKILL.md`
- verification and risk-review skills from `workflow-core`

It must carry guardrails for .NET version confirmation, SQL Server persistence verification, DB context gating, row-by-row ETL write prohibition, transaction boundaries, restart/idempotency/replay, and `needs-db-context`.

## Profiles

Profiles describe confirmed project facts and defaults. They do not change the phase lifecycle.

Unknown project shape means generic profile only.

Shipped profiles:

- `generic`
- `dotnet-etl-mssql`

Profile records should include:

- `selected_by`
- `evidence_paths`
- `confirmed_by`
- `confidence`
- `inactive_profiles_rejected`
- `open_questions`

## Manifest And Upgrade

Manifest entries must identify ownership:

- core
- adapter
- profile
- pack
- project

The installer and upgrader must support selected adapters and packs. Retired files are removed only when unmodified; modified retired files become conflicts.

## Release Gate

Before pushing a generalized harness release:

1. Run unit tests.
2. Run source `check`.
3. Run source `check --worktree` before commit.
4. Init and check core-only target.
5. Init and check OpenCode-only target.
6. Init and check Roo target.
7. Init and check combined Roo + OpenCode target.
8. Run the installed target smoke suite in each release-matrix target.
9. Init and check target with default `workflow-core` skill pack.
10. Confirm the README and clean skeleton are stack-neutral.
11. Confirm stack-specific docs are adapter, profile, pack, or example material only.
12. Record command results, target paths, timestamp, adversarial review result, commit, and pushed branch in the phase verification ledger.
