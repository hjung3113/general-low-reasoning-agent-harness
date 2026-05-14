# HANDOFF PROTOCOL

Use this protocol after any reset, handoff, or new agent session.

## Fresh Session Start

1. Read `AGENTS.md`.
2. Read `.planning/STATE.md`.
3. Read `.planning/ROADMAP.md`.
4. Read `.planning/codebase/ARCHITECTURE.md`, `STACK.md`, `STRUCTURE.md`, `CONVENTIONS.md`, `TESTING.md`, `INTEGRATIONS.md`, and `CONCERNS.md` when they exist.
5. Read the active phase `*-CHECKPOINTS.md`.
6. Read the active phase context, plan, review, verification, and summary files when they exist.
7. Read `.scratch/phase-state.json` if it exists. If it does not exist, default to `discuss`.
8. Run `git status --short`.
9. Do not edit implementation files unless the live phase state permits it.

## During Work

- Update `.planning/STATE.md` when the current phase, plan, checkpoint, blocker, or next action changes.
- Update the active `*-CHECKPOINTS.md` after each checkpoint.
- Put command results and review outcomes in `*-VERIFICATION.md` or `*-REVIEW.md`.
- Promote durable decisions to `.planning/DECISIONS.md` or an ADR.

## Before Ending A Session

1. Ensure `.planning/STATE.md` has one concrete next action.
2. Ensure live `.scratch/phase-state.json` points to the active plan and checkpoint.
3. Ensure phase summary and verification are current.
4. If a temporary handoff is requested, reference these files instead of duplicating their full contents.

## Subtask Handoff Protocol

### Parent Session Responsibilities

- Classify the request and choose the smallest valid workflow.
- Build a focused handoff packet for the owning mode.
- Create a Roo `new_task` for each non-trivial step.
- Collect the required structured result and synthesize next routing.
- If `new_task` is unavailable, output the handoff packet and stop.

### Subtask Responsibilities

- Reload durable context from `.planning/` and `.scratch/phase-state.json`.
- Stay inside phase gate and owner boundaries.
- Perform only the handed-off scope.
- Return the required structured result without guessing when context is stale.

### Low-Reasoning Checklist

```text
mode:
workflow:
goal:
phase:
plan_id:
approved:
allowed_work:
allowed_writes:
blocked_writes:
verification_expected:
```

### Required Packet Shape

```text
mode: <owning-mode>
workflow: <workflow-skill-or-direct-mode>
goal: <one-verifiable-outcome>
phase: <discuss|plan|execute|done>
plan_id: <id-or-none>
approved: <true|false>
read_first:
  - AGENTS.md
  - .planning/STATE.md
  - .planning/ROADMAP.md
  - .planning/codebase/ARCHITECTURE.md
  - .planning/codebase/STACK.md
  - .planning/codebase/STRUCTURE.md
  - .planning/codebase/CONVENTIONS.md
  - .planning/codebase/TESTING.md
  - .planning/codebase/INTEGRATIONS.md
  - .planning/codebase/CONCERNS.md
  - <active phase files>
  - .scratch/phase-state.json
focused_files:
  - <task-specific files>
allowed_writes:
  - <paths allowed by mode and phase gate>
blocked_writes:
  - <paths not allowed>
verification_expected:
  - <commands or evidence>
return_required:
  - status
  - changed_files
  - evidence
  - blockers
  - scope_deviations
  - next_recommended_route
```

### Required Return Shape

```text
status: <done|blocked|needs-plan|needs-db-context|needs-review|failed>
changed_files:
  - <path-or-none>
evidence:
  - <command-result-or-document-evidence>
blockers:
  - <blocker-or-none>
scope_deviations:
  - <deviation-or-none>
next_recommended_route: <mode/workflow-or-none>
```
