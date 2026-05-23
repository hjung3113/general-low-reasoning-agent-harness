---
name: workflow-codebase-recon
description: Use at the start of a session on an unknown codebase to populate .planning/codebase/ — the structured orientation directory other skill-packs read.
writes:
  - codebase.summary.*
  - codebase.conventions.*
  - codebase.concerns.*
  - codebase.architecture.*
reads:
  - codebase.stack.*
  - codebase.structure.*
  - codebase.testing.*
  - codebase.integrations.*
---

# Workflow Codebase Recon

Use this skill before writing any code on an unfamiliar codebase.

## Low-Reasoning Contract

`.planning/codebase/` is split into 8 files. The harness CLI handles the auto-detectable ones; you handle the judgment ones.

| File | Owner | What you do |
|------|-------|-------------|
| `STACK.md` | `harness recon` | Run the CLI; do not edit by hand. |
| `STRUCTURE.md` | `harness recon` | Run the CLI; do not edit by hand. |
| `TESTING.md` | `harness recon` (frameworks/commands) + you (scopes/repro) | Run CLI first; fill agent-owned anchors. |
| `INTEGRATIONS.md` | `harness recon` | Only present if external integrations detected. |
| `SUMMARY.md` | **you** | Hand-write 1-page entrypoint after others are filled. |
| `CONVENTIONS.md` | **you** | Naming, formatting, imports, errors — read the configs, write the contract. |
| `CONCERNS.md` | **you** | Tech debt, high-risk paths, flaky tests, security. |
| `ARCHITECTURE.md` | **you** (optional) | Skip for tiny single-package repos. |

## Stop Conditions

- you are already familiar with the codebase from prior context
- all agent-owned files (`SUMMARY`, `CONVENTIONS`, `CONCERNS`) have `status: current` in frontmatter and `updated_at` is within the last 7 days
- the codebase requires credentials or a running service to observe its structure

## Constraints

- **Time-box**: finish in ~10 minutes for a medium repo.
- **Read-only on code**: no source-file modifications during recon.
- **Anchor IDs are contracts**: do not rename `[codebase.<file>.<key>]` headers. Other skill-packs grep these.
- **No assumptions**: if unsure, leave the section as `<!-- TODO -->` or write into `codebase.concerns.open_questions`.

## Workflow

1. **Run `harness recon`** first. This populates `STACK.md`, `STRUCTURE.md`, `TESTING.md` (frameworks + commands), and `INTEGRATIONS.md` (if applicable).

2. **Fill `CONVENTIONS.md`** — read lint configs (`.eslintrc`, `pyproject.toml`, `prettier`), grep for common patterns (naming, imports), check a sample of 3-5 files. For each anchor:
   - `codebase.conventions.formatting` — Prettier/black/gofmt config highlights
   - `codebase.conventions.naming` — file/function/var/type rules from grep evidence
   - `codebase.conventions.imports` — ordering, aliases, banned imports
   - `codebase.conventions.errors` — throw vs Result; custom error types
   - `codebase.conventions.logging` — library, levels, structured-vs-string
   - `codebase.conventions.git` — branch model, commit format, PR template
   - `codebase.conventions.review` — what reviewers check, CI gates

3. **Fill `CONCERNS.md`** — grep TODO/FIXME, scan flaky-test markers, check security-sensitive paths (auth, migrations, secrets). For each anchor:
   - `codebase.concerns.high_risk` — paths to never touch without asking
   - `codebase.concerns.tech_debt` — known shortcuts with owners
   - `codebase.concerns.flaky_tests` — list with retry policy
   - `codebase.concerns.security` — secrets handling, threat surfaces
   - `codebase.concerns.performance` — hotspots, slow tests
   - `codebase.concerns.open_questions` — TODO items for the user

4. **Fill agent-owned anchors in `TESTING.md`**:
   - `codebase.testing.scopes` — unit/integration/e2e split
   - `codebase.testing.fixtures` — where fixtures live, parity rules
   - `codebase.testing.repro` — how to reproduce a bug locally
   - `codebase.testing.known_failures` — flaky/skipped tests

5. **Optionally fill `ARCHITECTURE.md`** — only for non-trivial repos. ASCII diagram + components table. Skip if it would be guesswork.

6. **Fill `SUMMARY.md` last** — pulls highlights from the others. Anchors:
   - `codebase.summary.identity` — 2-3 sentences, what + who
   - `codebase.summary.quickstart` — install + run cmd
   - `codebase.summary.test` — single test cmd (copy from `codebase.testing.commands`)
   - `codebase.summary.map` — 3-5 key edit paths
   - `codebase.summary.concerns` — top 3, link to CONCERNS anchors
   - `codebase.summary.links` — link to all other files (already in template)

7. **Update frontmatter**: each file you edit should have `status: current` and `updated_at: <today>`. Set `ownership: agent` and `source: human` where appropriate.

## Output Contract

All files live under `.planning/codebase/`. Each file:
- Has YAML frontmatter with `schema_version`, `artifact_type`, `generated_by`, `updated_at`, `ownership`, `source`, `refresh_policy`, `status`.
- Uses anchor headers `## [codebase.<file>.<key>] Title` exclusively for sections.
- Never renames anchor IDs (downstream skill-packs grep them).

## Worked Example

Python repo with `pytest`. Step 1: run `harness recon` — fills STACK with `[runtime: Python]`, STRUCTURE with depth-2 tree, TESTING frameworks with `pytest`, TESTING commands with `pytest`. Step 2-7: read `pyproject.toml` for ruff/black config → fill CONVENTIONS formatting/naming; grep `TODO` → fill CONCERNS tech_debt; write SUMMARY identity = "VOC management API, internal tool, 4 user roles", quickstart = `make dev`, test = `pytest`, map = `src/`, `tests/`, `migrations/`, concerns = (top 3 from CONCERNS).
