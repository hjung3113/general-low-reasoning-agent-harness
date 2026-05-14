---
name: workflow-architecture-decision
trigger: Use when the user asks for a design decision, ADR, boundary choice, tradeoff analysis, or invokes /adr.
description: Runs the architecture decision workflow for pipeline boundaries, state models, ADRs, and implementation plans. Use for design decisions or when the user invokes /adr.
---

# Workflow: Architecture Decision


## Execution Model

When invoked from `orchestrator`, do not execute this workflow inline.

The orchestrator must create a focused subtask in the owning mode and pass the required handoff packet from `.roo/rules-orchestrator/rules.md`.

The owning mode must reload durable context from `.planning/` and `.scratch/phase-state.json`, perform only its owned work, and return the required structured result.

If the task cannot proceed because planning context is missing, stale, placeholder-only, or outside the approved phase gate, return `needs-plan` instead of guessing.

## Steps

1. Gather context.
   - Read `AGENTS.md`, `.planning/STATE.md`, `.planning/ROADMAP.md`, `.planning/codebase/**`, the active `.planning/phases/**` document set, `CONTEXT.md`, `docs/adr/`, relevant requirements, and current code.
   - Treat `.planning/codebase/**` and `.planning/phases/**` as first-class ADR inputs, not optional extras.
   - When adopting this harness into an existing repository, inspect the actual repository structure, README, build/test files, and existing ADR/planning artifacts before writing or updating decisions.
   - Use project vocabulary.
   - If `.planning/codebase/**` or active `.planning/phases/**` is missing, stale, unrelated to the current repository, or placeholder-only, stop ADR work and run `workflow-planning-hydration` first.
   - Stop if enough context is not available to name the actual decision.

2. Align with the user before phase or ADR commitments.
   - Use a `grill-me` style interview before writing or updating ADRs, ROADMAP phases, phase plans, or success criteria.
   - Ask one question at a time and provide the recommended answer with the reason.
   - If a question can be answered from the repository, answer it by inspecting the repository instead of asking the user.
   - Resolve, or explicitly mark open, these dimensions: target user, real problem, desired outcome, non-goals, constraints, acceptable tradeoffs, phase granularity, first usable slice, success criteria, verification evidence, and out-of-scope work.
   - Write an alignment summary before any durable decision: confirmed facts, inferred facts, user-stated preferences, recommended defaults, open questions, and decisions blocked by those questions.
   - Do not turn inferred preferences into ADR decisions or phase success criteria unless the user accepts them or they are directly proven by repository evidence.
   - Use the concrete question template from `workflow-phase-gate` for phase-local discussions. Do not enter `plan` unless every template question has `repo_answer`, `user_answer`, or `open_blocker`.

3. Review the draft adversarially before commitment.
   - After the alignment summary and before final ADR or phase commitments, select two adversarial expert roles that fit the domain.
   - Give each expert exactly three review lenses.
   - Expert 1 lens 1 must be: are the questions concrete enough for a low-reasoning model to align with the user's intent?
   - Recommended default experts when the domain is unclear:
     - Product/user expert: user value, non-goals/scope creep, first usable slice.
     - Architecture/operations expert: boundary correctness, verification evidence, failure/rollback risk.
   - Capture output as `critique`, `reinforcement point`, and `change made`.
   - Apply each reinforcement point before finalizing, or record `deferred`/`rejected` with a reason.

4. Apply automation flags only within the phase gate.
   - `--auto`: use recommended answers for reversible, low-risk, non-blocking choices and record them as `auto_selected`.
   - `--chain`: continue from discuss to plan to execute using recommended answers only when a concrete plan has non-empty verification, allowed paths, durable planning pointers, no unresolved P1 adversarial finding, and `.scratch/phase-state.json` has been verified or written with `phase=execute`, matching `plan_id`, `approved=true`, and `automation_mode=chain`.
   - Stop and ask the user for high-risk, destructive, external, security-sensitive, irreversible, or product-direction choices.

5. Frame the decision.
   - State the problem, constraints, non-goals, and affected workflows.
   - For ETL, include ordering, state, idempotency, persistence, and operations.
   - State what this workflow will not decide.

6. Compare options.
   - Present 2-4 realistic options with tradeoffs.
   - Recommend one option and say why it fits pipeline-first Clean Architecture.

7. Record the decision.
   - Write or update an ADR when the decision is durable.
   - Include consequences, ownership, and test strategy.
   - Update `.planning/DECISIONS.md` or the active phase context/checkpoint when the decision affects project state.
   - If the ADR adds, deletes, inserts, renumbers, completes, or reopens a roadmap phase, update `.planning/ROADMAP.md`, `.planning/STATE.md`, the active phase `*-CHECKPOINTS.md`, and `.scratch/phase-state.json` together.
   - Keep STATE frontmatter `progress.total_phases`, `progress.completed_phases`, and `progress.percent` derived from the ROADMAP phase checklist.
   - Keep `.scratch/phase-state.json` `state_path`, `checkpoint_path`, and `current_checkpoint` aligned with the active checkpoint recorded in `.planning/STATE.md`.
   - Update the matching `.planning/codebase/**` note when the decision changes architecture, stack, structure, conventions, testing, integrations, or known concerns.
   - Call out when future work needs xUnit coverage or MSSQL integration coverage.
   - Preserve the alignment summary in the ADR or active phase context when it influenced the decision.
   - Preserve adversarial review findings and reinforcement points when they influenced the decision.

8. Convert to implementation work.
   - Produce vertical slices or local issue files when requested.
   - Assign recommended modes for each slice.
   - Keep implementation slices linked from the active phase plan/checkpoint when they belong to the current phase.
   - Do not implement the slices in this workflow.

## Existing Repository Planning Context

Do not fold existing-repository planning hydration into this workflow. Use `workflow-planning-hydration` first, then return to ADR once planning context is usable.

ADR may proceed only when:

- `.planning/codebase/**` describes the current repository.
- `.planning/phases/**` has an active phase document set relevant to the current work.
- `.planning/STATE.md`, `.planning/ROADMAP.md`, and `.scratch/phase-state.json` do not point at unrelated template or previous-project artifacts.

## Routing

- Primary owner: architecture/ADR work.
- Route missing/stale existing-project planning context to `workflow-planning-hydration` before ADR.
- ADR planning-memory work may update `.planning/DECISIONS.md`, active phase docs, and matching `.planning/codebase/**` notes after hydration is complete.
- Route Roo, slash-command, AGENTS.md, CLAUDE.md, `.roo/**`, and `.roomodes` changes to `harness-maintainer`.
- Route follow-up implementation slices to `tdd-code`, `etl-pipeline`, or `db-migration` based on the affected boundary.
- Route review-only follow-up to `review`.

## Hard Rules

- Architect mode does not implement application code.
- Do not skip `.planning/codebase/**` or `.planning/phases/**` during ADR work because those folders are the durable design and phase memory.
- Do not use ADR as a substitute for `workflow-planning-hydration` when the repo planning memory is absent, stale, or placeholder-only.
- Do not create or reshape ROADMAP phases, phase folders, ADR decisions, or success criteria until the alignment interview has produced a written summary and any blocking questions are resolved or explicitly deferred.
- Do not finalize ADR or phase commitments until the two-expert adversarial review has been applied or explicitly deferred with reasons.
- Do not let `--auto` or `--chain` skip alignment, adversarial review, durable planning pointers, allowed paths, or verification.
- Do not adopt frameworks only to make diagrams cleaner.
- Do not turn this workflow into sample project or domain implementation.
