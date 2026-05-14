# General Low-Reasoning Agent Harness

This repository is a generalized workflow harness for low-reasoning AI agents.

It is not tied to one programming language, database, framework, editor, or agent client. The core protocol keeps agents inside an explicit, resumable workflow:

```text
discuss -> plan -> execute -> done
```

The harness separates:

- **core protocol**: planning memory, phase gate, checkpoints, verification, review, restart order
- **client adapters**: Roo, OpenCode, and future clients
- **profiles**: confirmed project facts and defaults
- **skill packs**: composable workflow plugins selected per request
- **optional packs**: capabilities such as database context snapshots

## First Principles

- `.planning/**` is canonical project memory.
- `.scratch/phase-state.json` is only the live gate.
- Fresh sessions read durable planning docs before trusting the live gate.
- No application-code edits start unless the gate is `phase=execute`, `approved=true`, and tied to an approved `plan_id`.
- Unknown repositories start with generic profile plus Phase 0 planning hydration.
- Stack-specific guidance activates only from repository evidence or explicit user confirmation.
- Workflow skills are composable plugins, not fixed tech-stack presets.

## Install Into A Target Project

Default install uses the Roo adapter plus the generic `workflow-core` skill pack:

```bash
python3 scripts/harness.py init --target /path/to/project
```

Core only:

```bash
python3 scripts/harness.py init --target /path/to/project --adapters none
```

OpenCode only:

```bash
python3 scripts/harness.py init --target /path/to/project --adapters opencode
```

Roo and OpenCode:

```bash
python3 scripts/harness.py init --target /path/to/project --adapters roo,opencode
```

Install without the default workflow skill pack:

```bash
python3 scripts/harness.py init --target /path/to/project --packs none
```

## Validate

```bash
python3 scripts/harness.py check
python3 scripts/harness.py doctor
python3 -m unittest scripts/test_harness.py
```

Validate an installed target:

```bash
python3 scripts/harness.py check --target /path/to/project
python3 scripts/harness.py check --target /path/to/project --adapter opencode
```

## Upgrade

```bash
python3 scripts/harness.py upgrade --target /path/to/project
python3 scripts/harness.py upgrade --target /path/to/project --adapters opencode
```

`upgrade` preserves project-owned planning state and updates only selected harness-owned, adapter-owned, profile-owned, or pack-owned files. Modified harness-owned files are written to `.harness/conflicts/**` instead of being overwritten silently.

## Fresh Session Read Order

1. `AGENTS.md`
2. `.planning/STATE.md`
3. `.planning/ROADMAP.md`
4. `.planning/codebase/**`
5. active phase checkpoint under `.planning/phases/**`
6. active phase context, plan, review, verification, and summary files when present
7. `.scratch/phase-state.json`

## Skill Plugins

The default `workflow-core` pack installs stack-neutral skills under `.agents/skills/`:

- `repository-evidence-research`
- `skill-plugin-composition`
- `verification-contract`
- `risk-review`
- `data-workflow`
- `integration-boundary`

These skills are combined per request. For example, a data-heavy project might use `repository-evidence-research`, `data-workflow`, and `verification-contract`; an API integration project might use `repository-evidence-research`, `integration-boundary`, `risk-review`, and `verification-contract`.

Do not hard-code project categories such as Python, .NET, MSSQL, or ETL into core. If a project needs a custom skill, create it as a project-local plugin after the evidence and constraints are known.

## Repository Layout

```text
harness/
  manifest.json
  skeleton/clean/
  profiles/
  skill-packs/
.roo/                  # Roo adapter source
.opencode/             # OpenCode adapter source
scripts/
  harness.py
  test_harness.py
docs/
```

## Design Document

The generalized protocol design is captured in `docs/protocol-spec.md`.

