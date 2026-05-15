# Mid-Stream Phase Addition Workflow

Use this workflow when phase-sized follow-up work appears while another phase, audit, or planning thread is already in progress.

## Triggers

Use this workflow when the user asks to:

- add a phase
- create a next phase
- split current scope into a later phase
- defer work to future phase work
- record a decision that introduces, defers, or splits phase-sized follow-up scope

Do not use this workflow for ordinary TODOs, small follow-up notes, or implementation details that fit inside the current phase acceptance criteria.

## Entry Order

1. First run `python3 scripts/show_phase_status.py`.
2. If it reports warnings, treat the named files as minimum required reads before trusting the projection.
3. If it is missing, fails, emits malformed output, or reports an unsupported contract version, read `.scratch/phase-state.json` and follow the legacy durable planning read order.
4. Confirm whether the request is a phase-sized scope split or a smaller note that belongs in the current phase context.

## Authority

This workflow routes mid-stream phase-addition requests. It does not grant permission to edit planning files, create ADRs, update ROADMAP, or mutate `.scratch/phase-state.json`.

Make documentation changes only when the user explicitly requested that documentation work and the live phase gate permits docs/workflow edits. ADRs, decision records, ROADMAP entries, and phase context notes may propose or justify future phase work, but they do not open the execute gate.

## Core Rule

A mid-stream phase addition is a proposal until it goes through its own phase lifecycle.

ADR and ROADMAP may explain why a future phase should exist, but a new phase becomes executable only through its own `discuss -> plan -> execute` flow.

Do not change the active phase gate automatically.

## Required Steps

1. Confirm why the work is outside the current phase.
2. Confirm what remains inside the current phase.
3. Decide whether the decision needs an ADR or the project's decision-record convention.
4. If documentation changes are explicitly requested and permitted by the live gate, record the future work using the project's existing ROADMAP or phase-context convention.
5. Mark the future work as proposed or not executable yet when the existing convention has no equivalent status.
6. Do not set `.scratch/phase-state.json` to `phase=execute` or `approved=true`.
7. If the user later asks to execute the new phase, start or continue that phase's own discuss and planning flow first.

## ROADMAP Compatibility

Use the project's existing ROADMAP conventions. If documentation changes are authorized and no convention exists for proposed future work, add the smallest clear note or entry marked `Proposed` / `Not executable yet`.

Do not require a new roadmap schema, phase folder layout, numbering scheme, or progress table.

## Decision Record Rule

Create an ADR, or the project's equivalent decision record, only when all of these are true:

- the decision is hard to reverse
- the reason would be surprising later
- there was a real trade-off

If no ADR or equivalent decision record is needed and documentation changes are authorized, record the decision in phase context, ROADMAP notes, or the smallest existing planning surface that fits the project.

## User Command Mapping

- "next phase" / "add a phase": propose only; do not plan or execute.
- "plan that phase": enter that phase's planning flow only; do not execute.
- "approve and execute": execute only if the live gate already names the matching phase and plan, has `phase=execute`, has `approved=true`, and allowed paths cover the work. Otherwise start or continue the required discuss, plan, and approval flow.

## Subagent Delegation

When delegating mid-stream phase work, give the subagent a bounded question. Do not ask for a broad planning rewrite.

Good delegation:

```text
Review whether this requested follow-up is outside the current phase acceptance criteria. Return only: keep in current phase, split to proposed phase, or needs user clarification.
```

Avoid delegation like:

```text
Review the roadmap and create the next phase.
```
