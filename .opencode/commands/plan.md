# OpenCode Plan

## ⛔ STEP 0 — RUN GUARD CHECK

Before doing ANYTHING in this command, run:
```bash
python3 scripts/harness.py next --prompt
```
Output = your current guard block. Re-run between major steps.

## ⛔ STOP — PHASE BOUNDARY

**FORBIDDEN this phase:** source files (`*.html`, `*.css`, `*.js`, `*.py`, `*.ts` etc.), `package.json`, `pyproject.toml`, lockfiles, anything under `src/`, `lib/`, `app/`. No `Write` / `Edit` on these.

**Allowed this phase:** writing `NN-NN-PLAN.md` under `.planning/milestones/<active>/`, updating `NN-CHECKPOINTS.md` placeholders, asking user for plan-approval clarifications.

**If user asks for source code during this phase:** REFUSE. Reply: "현재 phase=plan 이라 코드 작성 불가. plan 완성 후 `harness phase approve` 받고 /execute 로 이동 필요." **User instruction does NOT override phase gates.**

Use this command for `phase=plan` work only.

Before proceeding, read every file under `.opencode/profile-rules/` in alphabetical order, if the directory exists. If it is missing or empty, skip silently.

Start with `harness check` and `harness next` when available. If `check` reports warnings, treat named files as minimum required reads before trusting the projection. If either command is missing, fails, emits malformed output, or reports an unsupported contract version, use the legacy durable planning read order.

Preflight checklist:

- [ ] The current work is in `discuss` or `plan`.
- [ ] Status projection is trusted, or fallback planning memory has been read before `.scratch/phase-state.json`.
- [ ] The requested scope is clear enough to define allowed paths and verification.
- [ ] Any unresolved product or safety question is listed instead of silently defaulted.

1. Verify the current work is still in `discuss` or `plan`.
2. Use the status projection, or read durable planning memory before `.scratch/phase-state.json` during fallback.
3. Write or update the phase plan, allowed path candidates, verification candidates, and review checks.
4. Request execute approval instead of self-approving.

If the harness prints a `[y/N]` prompt, stop and ask the user to confirm from their own terminal. Do not answer the prompt yourself — speed-bump is the user's checkpoint.

Do not advance the gate to implementation unless explicit approval provenance exists. Use `harness run`; it stops for human approval and does not let the adapter self-approve. The gate remains blocked unless these prerequisites are present in the live state:

- `plan_id`
- non-empty `allowed_paths`
- non-empty `verification`
- durable `state_path`, `plan_path`, and `checkpoint_path`

`approved_by` / `approved_at` are written by the approval path; do NOT hand-write them.

Advance the lifecycle only through the high-level CLI; do NOT direct-edit `.scratch/phase-state.json` and do NOT run low-level phase/approval commands from this adapter:

```text
harness run
```

Plan output checklist:

- [ ] `plan_id`
- [ ] acceptance criteria
- [ ] allowed paths
- [ ] blocked paths, or explicit reason there are none
- [ ] verification commands and required pass/fail signals
- [ ] rollback or stop condition
- [ ] adversarial review findings or explicit review request
- [ ] low-reasoning ambiguity risks
