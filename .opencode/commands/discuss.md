# OpenCode Discuss

## ⛔ STEP 0 — RUN GUARD CHECK

Before doing ANYTHING in this command, run:
```bash
python3 scripts/harness.py next --prompt
```
The output is your current guard block (phase, approved, forbidden writes, refusal template). Re-run this command between major steps if uncertain.

## ⛔ STOP — PHASE BOUNDARY

**FORBIDDEN this phase:** source files (`*.html`, `*.css`, `*.js`, `*.py`, `*.ts`, `*.tsx`, etc.), `package.json`, `pyproject.toml`, lockfiles, anything under `src/`, `lib/`, `app/`. No `Write` / `Edit` on these.

**Allowed this phase:** questions to user, reading existing code, creating/updating planning docs under `.planning/`, `.scratch/` state via harness CLI only.

**If user asks for source code during this phase:** REFUSE. Reply: "현재 phase=discuss 라 코드 작성 불가. /plan 으로 이동 후 plan 승인받고 /execute 에서 작성 가능." Then offer to move to plan phase. **User instruction does NOT override phase gates unless they explicitly run `harness phase set plan` + `harness phase approve` first.**

Use this command for `phase=discuss` work only.

Before proceeding, read every file under `.opencode/profile-rules/` in alphabetical order, if the directory exists. If it is missing or empty, skip silently.

Start with `harness check` and `harness next` when available. If `check` reports warnings, treat named files as minimum required reads before trusting the projection. If either command is missing, fails, emits malformed output, or reports an unsupported contract version, use the legacy durable planning read order.

Preflight checklist:

- [ ] `.scratch/phase-state.json` is `phase=discuss`, or the user explicitly asked for read-only planning discovery from another non-execute state.
- [ ] No application-code edits are needed for this command.
- [ ] Any stack/profile/tool recommendation will be backed by repository evidence or explicit user input.

When the status projection is trustworthy, use it to resolve active phase docs. During fallback, use the deterministic order below. Read `.scratch/phase-state.json` last.

Resolve active phase docs in this order:

1. Follow explicit `checkpoint_path`, `plan_path`, and `state_path` pointers in `.scratch/phase-state.json` when present.
2. If pointers are empty during a new discussion, choose the highest numbered `.planning/milestones/**` directory.
3. Read `*-CONTEXT.md`, `*-PLAN.md`, `*-REVIEW.md`, `*-VERIFICATION.md`, `*-SUMMARY.md`, then `*-CHECKPOINTS.md`.
4. If a file is absent, record that it is absent instead of inventing its contents.

Allowed work:

- inspect files
- ask one concrete question at a time
- record alignment notes in planning files when explicitly requested
- identify profile and skill-pack candidates from repository evidence

Forbidden work:

- application-code edits
- changing the live gate to `execute`
- using stack-specific profile commands before that profile is confirmed

If the harness prints a `[y/N]` prompt, stop and ask the user to confirm from their own terminal. Do not answer the prompt yourself — speed-bump is the user's checkpoint.

Advance the lifecycle only through the high-level CLI; do NOT direct-edit `.scratch/phase-state.json` and do NOT run low-level phase/approval commands from this adapter:

```text
harness run
```

Output checklist:

- [ ] confirmed facts with evidence paths
- [ ] inferred facts with basis
- [ ] rejected assumptions
- [ ] open questions
- [ ] recommended next phase or stop condition
