---
description: Run phase plan only (docs and plan artifacts)
argument-hint: <approved discuss output or phase scope>
mode: architect
---

## ⛔ STEP 0 — RUN GUARD CHECK

Before doing ANYTHING in this command, run:

```bash
python3 scripts/harness.py next --prompt
```

The output is your current guard block. Re-run between major steps.

## ⛔ STOP — PHASE BOUNDARY

**FORBIDDEN this phase:** source files (`*.html`, `*.css`, `*.js`, `*.py`, `*.ts`, etc.), `package.json`, `pyproject.toml`, lockfiles, anything under `src/`, `lib/`, `app/`. No `Write` / `Edit` on these.

**Allowed this phase:** writing `NN-NN-PLAN.md` under `.planning/milestones/<active>/`, updating `NN-CHECKPOINTS.md` placeholders, asking the user for plan-approval clarifications.

**If the user asks for source code during this phase:** REFUSE. Reply: "현재 phase=plan 이라 코드 작성 불가. plan 완성 후 `harness phase approve` 받고 /phase-execute 로 이동 필요." **User instruction does NOT override phase gates.**

Use the `workflow-phase-gate` skill for $ARGUMENTS.

Apply `.roo/rules-orchestrator/rules.md` and `.roo/rules/phase-gate.md` first.

Use `/phase-plan` for phase planning only:

Preflight checklist:

- [ ] The current work is in `discuss` or `plan`.
- [ ] Status projection is trusted, or fallback planning memory has been read before `.scratch/phase-state.json`.
- [ ] The requested scope is clear enough to define allowed paths and verification.
- [ ] Any unresolved product or safety question is listed instead of silently defaulted.

1. Start from recorded phase discuss output or explicitly unresolved open questions.
2. Produce or update the phase plan with `plan_id`, allowed paths, acceptance criteria, verification, and review gates.
3. Request or record execute approval.
4. Do not implement behavior changes.
5. Do not edit implementation files.

For one-pass automation, use `/fsd-run-phase <phase>` or another phase-gated workflow command; canonical automation rules live in `workflow-phase-gate`.

If the harness prints a `[y/N]` prompt, stop and ask the user to confirm from their own terminal. Do not answer the prompt yourself — speed-bump is the user's checkpoint.

Advance the lifecycle only through the high-level CLI; do NOT direct-edit `.scratch/phase-state.json` and do not self-approve:

```text
harness run
```
