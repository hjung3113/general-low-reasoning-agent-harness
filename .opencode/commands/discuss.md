# OpenCode Discuss

Use this command for `phase=discuss` work only.

Preflight checklist:

- [ ] `.scratch/phase-state.json` is `phase=discuss`, or the user explicitly asked for read-only planning discovery from another non-execute state.
- [ ] No application-code edits are needed for this command.
- [ ] Any stack/profile/tool recommendation will be backed by repository evidence or explicit user input.

1. Read `AGENTS.md`.
2. Read `.planning/STATE.md`.
3. Read `.planning/ROADMAP.md`.
4. Read `.planning/codebase/**`.
5. Read the active phase checkpoint under `.planning/phases/**`.
6. Read active phase context, plan, review, verification, and summary files when present.
7. Read `.scratch/phase-state.json` last.

Resolve active phase docs in this order:

1. Follow explicit `checkpoint_path`, `plan_path`, and `state_path` pointers in `.scratch/phase-state.json` when present.
2. If pointers are empty during a new discussion, choose the highest numbered `.planning/phases/**` directory.
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

Output checklist:

- [ ] confirmed facts with evidence paths
- [ ] inferred facts with basis
- [ ] rejected assumptions
- [ ] open questions
- [ ] recommended next phase or stop condition
