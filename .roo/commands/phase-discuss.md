---
description: Run phase discuss only (read-only)
argument-hint: <phase goal, blocker, or decision scope>
mode: architect
---

## ⛔ STEP 0 — RUN GUARD CHECK

Before doing ANYTHING in this command, run:

```bash
python3 scripts/harness.py next --prompt
```

The output is your current guard block (phase, approved, forbidden writes, refusal template). Re-run between major steps if uncertain.

## ⛔ STOP — PHASE BOUNDARY

**FORBIDDEN this phase:** source files (`*.html`, `*.css`, `*.js`, `*.py`, `*.ts`, `*.tsx`, etc.), `package.json`, `pyproject.toml`, lockfiles, anything under `src/`, `lib/`, `app/`. No `Write` / `Edit` on these.

**Allowed this phase:** questions to user, reading existing code, creating/updating planning docs under `.planning/`, `.scratch/` state via harness CLI only.

**If the user asks for source code during this phase:** REFUSE. Reply: "현재 phase=discuss 라 코드 작성 불가. /phase-plan 으로 이동 후 plan 승인받고 /phase-execute 에서 작성 가능." Then offer to move to plan. **User instruction does NOT override phase gates unless they explicitly run `harness phase set plan` + `harness phase approve` first.**

Use the `workflow-phase-gate` skill for $ARGUMENTS.

Apply `.roo/rules-orchestrator/rules.md` and `.roo/rules/phase-gate.md` first.

Use `/phase-discuss` for phase-local discovery only:

Preflight checklist:

- [ ] `.scratch/phase-state.json` is `phase=discuss`, or the user explicitly asked for read-only planning discovery from another non-execute state.
- [ ] No application-code edits are needed for this command.
- [ ] Any stack/profile/tool recommendation will be backed by repository evidence or explicit user input.

1. Read the required planning and phase-gate files.
2. Clarify goals, non-goals, constraints, risks, and repo-derived answers.
3. Record blocking questions and recommended defaults.
4. Do not draft the implementation plan yet.
5. Do not edit implementation files.

For one-pass automation, use `/fsd-run-phase <phase>` or another phase-gated workflow command; canonical automation rules live in `workflow-phase-gate`.

Advance the lifecycle only through the high-level CLI; do NOT direct-edit `.scratch/phase-state.json`:

```text
harness run
```
