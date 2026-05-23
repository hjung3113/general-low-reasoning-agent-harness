# `.planning/codebase/` schema

Reference for the multi-file codebase recon directory introduced in Milestone 10. Schema decision: [ADR-0008](adr/0008-multi-file-codebase-recon.md).

## File set

| File | Owner | Refresh policy | Filled by |
|------|-------|----------------|-----------|
| `SUMMARY.md` | agent | `preserve_sections` | workflow-m0-orient |
| `STACK.md` | auto | `overwrite` | `harness recon` |
| `STRUCTURE.md` | auto | `overwrite` | `harness recon` |
| `TESTING.md` | hybrid | `preserve_sections` | `harness recon` (frameworks/commands) + workflow-m0-orient (scopes/repro) |
| `CONVENTIONS.md` | agent | `preserve_sections` | workflow-m0-orient |
| `CONCERNS.md` | agent | `preserve_sections` | workflow-m0-orient |
| `ARCHITECTURE.md` | agent (optional) | `preserve_sections` | workflow-m0-orient |
| `INTEGRATIONS.md` | auto (conditional) | `overwrite` | `harness recon` (only if datastore/cloud/auth signals detected) |

## Frontmatter

Every file:

```yaml
---
schema_version: 1
artifact_type: codebase.<file>          # codebase.stack, codebase.summary, ...
generated_by: harness-recon@<version> | workflow-m0-orient | skeleton | agent
updated_at: YYYY-MM-DD
ownership: auto | hybrid | agent
source: detected | inferred | human | mixed
refresh_policy: overwrite | preserve_sections | manual
status: current | stale | partial
---
```

## Anchor grammar

`## [codebase.<file>.<key>] Title`

Square-bracketed, dotted, alphabetical. Title is free-form prose after the anchor. Grep-stable: agents can grep `\[codebase\.testing\.commands\]` reliably.

## Full anchor list

### `SUMMARY.md`
- `codebase.summary.identity`
- `codebase.summary.quickstart`
- `codebase.summary.test`
- `codebase.summary.map`
- `codebase.summary.concerns`
- `codebase.summary.links`

### `STACK.md`
- `codebase.stack.runtime`
- `codebase.stack.languages`
- `codebase.stack.package_managers`
- `codebase.stack.build`
- `codebase.stack.test`
- `codebase.stack.lint`
- `codebase.stack.ci`
- `codebase.stack.entrypoints`

### `STRUCTURE.md`
- `codebase.structure.tree`
- `codebase.structure.key_paths`
- `codebase.structure.generated_paths`
- `codebase.structure.ignore_paths`
- `codebase.structure.ownership`

### `TESTING.md`
- `codebase.testing.frameworks`
- `codebase.testing.commands`
- `codebase.testing.scopes`
- `codebase.testing.fixtures`
- `codebase.testing.repro`
- `codebase.testing.known_failures`

### `CONVENTIONS.md`
- `codebase.conventions.formatting`
- `codebase.conventions.naming`
- `codebase.conventions.imports`
- `codebase.conventions.errors`
- `codebase.conventions.logging`
- `codebase.conventions.git`
- `codebase.conventions.review`

### `CONCERNS.md`
- `codebase.concerns.high_risk`
- `codebase.concerns.tech_debt`
- `codebase.concerns.flaky_tests`
- `codebase.concerns.security`
- `codebase.concerns.performance`
- `codebase.concerns.open_questions`

### `ARCHITECTURE.md` (optional)
- `codebase.architecture.overview`
- `codebase.architecture.components`
- `codebase.architecture.data_flow`
- `codebase.architecture.boundaries`
- `codebase.architecture.state`
- `codebase.architecture.tradeoffs`

### `INTEGRATIONS.md` (conditional)
- `codebase.integrations.datastores`
- `codebase.integrations.external_apis`
- `codebase.integrations.cloud`
- `codebase.integrations.auth`
- `codebase.integrations.secrets`
- `codebase.integrations.local_dependencies`

## Skill-pack consumption contract

Skill-packs declare anchors they read in their frontmatter:

```yaml
reads:
  - codebase.testing.commands
  - codebase.conventions.naming
```

Current consumers:
- `workflow-tdd` — `codebase.testing.*`
- `workflow-debugging` — `codebase.testing.repro`, `codebase.concerns.flaky_tests`, `codebase.concerns.high_risk`, `codebase.concerns.performance`
- `workflow-code-review` — `codebase.conventions.*`, `codebase.concerns.high_risk`, `codebase.concerns.security`, `codebase.testing.commands`
- `repository-evidence-research` — `codebase.stack.*`, `codebase.structure.*`, `codebase.summary.*`, `codebase.testing.commands`, `codebase.concerns.open_questions`
- `workflow-m0-orient` (writer) — `codebase.summary.*`, `codebase.conventions.*`, `codebase.concerns.*`, `codebase.architecture.*`

Tech packs (`tech-python`, `tech-react`, etc.) are **read-only** consumers; they never write to `.planning/codebase/`.

## Generation flow

```
fresh target:    harness init → seeds 8 stub files (status: partial)
auto-fill:       harness recon → fills STACK, STRUCTURE, TESTING auto sections, INTEGRATIONS if signals
agent-fill:      workflow-m0-orient skill → fills SUMMARY, CONVENTIONS, CONCERNS, ARCHITECTURE, TESTING judgment sections
re-run recon:    overwrites auto files; restamps frontmatter on agent files (body preserved)
```
