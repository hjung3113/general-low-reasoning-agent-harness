# Roo Slash Commands

These commands are the user-facing entry points for the template.

## Fresh Target First Actions

Before planning hydration finishes, keep the visible command set small:

- `/phase-discuss planning-hydration` for the first repository inventory and alignment pass.
- `/simple` for one or two known files when there are no application code edits and verification is obvious.
- `/review` for read-only consistency checks.
- `/doctor` for read-only harness diagnostics.

| Command | Mode | Purpose |
| --- | --- | --- |
| `/simple` | `orchestrator` | Run the lightweight path for focused questions, small low-risk edits, docs tweaks, harmless command runs, mechanical cleanup, and tiny locally verified changes. |
| `/feature` | `orchestrator` | Route ordinary application behavior or refactoring into the TDD workflow when no narrower owner applies. |
| `/bugfix` | `orchestrator` | Run the root-cause workflow for broken behavior, failing tests, wrong output, regressions, or unknown cause. |
| `/etl` | `orchestrator` | Run the ETL workflow for parser, normalization, correction, state, matching, merge, buffering, writer flow, replay, or restart safety. |
| `/db` | `orchestrator` | Run the DB workflow for MSSQL schema, EF migration, SQL, indexes, transactions, Dapper, `SqlBulkCopy`, `MERGE`, or persistence migrations. |
| `/ops` | `orchestrator` | Route operational work for logs, metrics, processing events, retry boundaries, worker polling, graceful shutdown, dashboards, or runbooks. |
| `/adr` | `architect` | Run the architecture workflow for durable design decisions, boundaries, state models, tradeoffs, or implementation planning. |
| `/review` | `review` | Run the read-only review workflow for code, SQL, ETL, tests, performance, or operations risk. |
| `/issues` | `docs-issues` | Convert docs and plans into PRDs, local tracker issues, acceptance criteria, and implementation slices. |
| `/doctor` | `orchestrator` | Run `workflow-harness-doctor` for read-only harness diagnostics covering planning, Roo command/mode, DB context config, and diff-before-mutation readiness. |
| `/phase-discuss` | `architect` | Run the phase-gate discuss step only: read-only discovery, alignment, constraints, and open questions. |
| `/phase-plan` | `architect` | Run the phase-gate plan step only: plan docs, scope, acceptance criteria, verification, and approval request. |
| `/phase-execute` | `orchestrator` | Verify an approved execute gate and hand off implementation to the owning mode; the orchestrator does not implement inline. |
| `/fsd-phase` | `orchestrator` | Recommended one-command phase entry; routes discuss -> plan -> execute through the canonical phase gate and subtask handoffs. |

Slash commands stay thin. Use `.roo/rules-orchestrator/rules.md` for exclusive routing and tie breakers; use the workflow skill or owning mode for the actual sequence.

## Automation Flags

Any workflow that uses the phase gate may receive these prompt flags:

- `--auto`: select recommended low-risk defaults, record auditable `auto_selected` entries, and stop for destructive, external, security-sensitive, irreversible, broad-scope, or ambiguous product-direction choices.
- `--chain`: request one phase's reviewed `discuss -> plan -> execute` path with recommended defaults. The canonical conditions live in `workflow-phase-gate` Automation Flags and Stop Conditions and must not be weakened by command files.

Flags do not skip phase-local `discuss`, alignment summary, adversarial review, plan approval evidence, execute handoff, or verification.

## Phase Command Usage

- Manual step-by-step: `/phase-discuss` -> `/phase-plan` -> `/phase-execute`.
- One-pass automation: use `/fsd-phase <phase> --chain` or another phase-gated workflow command with `--chain`.
- Execute remains subtask-first: the orchestrator verifies the gate, creates the owning-mode handoff packet, and stops if `new_task` is unavailable.
- `--chain` does not skip gate safety checks; if canonical conditions fail, stop before execute.
