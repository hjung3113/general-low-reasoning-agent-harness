---
name: workflow-phase-gate
trigger: Use before any implementation workflow, when the user asks to gate work through discuss, plan, execute, or done phases, or when a task references phase-state approval.
description: Runs the external phase gate for low-reasoning models: discuss is read-only discovery, plan is docs or issue-plan only, execute requires approved plan_id, approved allowed_paths, verification, and phase=execute, and done records verification.
---

# Workflow: Phase Gate

Use this workflow before implementation to prevent accidental work before the user or orchestrator has approved a plan.

State lives outside the prompt in `.scratch/phase-state.json` or another file that follows `.scratch/phase-state.schema.json`. Durable project memory lives under `.planning/`; the live state file is a gate pointer, not the source of planning context.

## Required State Check

Before doing any work:

1. Read `AGENTS.md`.
2. Read `.planning/STATE.md`.
3. Read `.planning/ROADMAP.md`.
4. Read the active phase checkpoint file named in `.planning/STATE.md`.
5. Read `.planning/codebase/ARCHITECTURE.md`, `STACK.md`, `STRUCTURE.md`, `CONVENTIONS.md`, `TESTING.md`, `INTEGRATIONS.md`, and `CONCERNS.md` when they exist.
6. Read the active phase context, plan, review, verification, and summary files under `.planning/phases/` when they exist.
7. Read the phase state file if one exists.
8. Identify `phase`, `plan_id`, `approved`, `state_path`, `plan_path`, `checkpoint_path`, `current_checkpoint`, `allowed_paths`, and `verification`.
9. For `plan`, `execute`, and `done`, read `state_path`, `plan_path`, and `checkpoint_path` before classifying allowed work. If any pointer is missing or stale, treat the state as incomplete and return to `plan`.
10. If `.planning/codebase/**` or the active phase document set is missing, placeholder-only, or stale for the current repository, treat the gate as incomplete for existing-repository adoption and return to `plan` to hydrate planning memory.
11. Confirm roadmap/state sync: ROADMAP phase checklist totals and completion count must match STATE frontmatter progress, STATE active phase/checkpoint must match the active roadmap phase, and `.scratch/phase-state.json` must point to the same STATE and checkpoint.
12. Identify `automation_mode` from `.scratch/phase-state.json` or the user's command flags. Default to `manual`.
13. If there is no state file, start in `discuss`.
14. Do only the work allowed by the current phase and automation mode.

## Phase-Local Lifecycle

Every roadmap phase starts with its own `discuss` pass. Do not create a phase plan just because a previous phase ended.

For each phase:

```text
phase-N discuss -> phase-N plan -> phase-N execute -> phase-N done
```

The phase-local `discuss` pass must identify:

- the problem this phase solves
- target user or operator affected by the phase
- non-goals and explicitly unwanted work
- first usable slice
- questions the repository can answer without asking the user
- choices that require user preference
- recommended defaults
- verification evidence available for the phase

Use this concrete question template. Each row must have `repo_answer`, `user_answer`, or `open_blocker` before entering `plan`.

| Question | Recommended default when repo is silent |
| --- | --- |
| Who is blocked by this phase? | Name the primary user/operator from the request; otherwise ask. |
| What is the smallest observable result after this phase? | Choose the first slice that can be verified independently. |
| What must not change in this phase? | Exclude deployment, broad refactors, unrelated cleanup, and external systems unless requested. |
| Which files or areas may change? | Use the narrowest paths proven by current docs or code. |
| What command or artifact proves completion? | Prefer an existing focused test/check; otherwise define document evidence and mark the test gap. |
| Which answers came from repo evidence, and which need user preference? | Treat unproven product direction as `open_blocker`. |

Only after those items are summarized may the workflow enter `plan`.

## Automation Flags

Automation flags change how choices are resolved. They do not weaken the phase gate.

### manual

Default mode. Ask the user for choices that affect scope, phase boundaries, acceptance criteria, or implementation authority.

### `--auto`

Use the recommended answer for non-blocking choices.

Rules:

- Inspect the repository instead of asking when repository evidence can answer the question.
- Auto-select the recommended answer only for documentation wording, ordering, naming, or repo-proven defaults inside the current allowed work.
- Record each automatic choice in `auto_selected` or the active phase context.
- Each `auto_selected` entry must record `choice`, `selected_value`, `reason`, `evidence_path`, `risk_level`, `reversible`, `inside_allowed_paths`, and `stop_conditions_checked`.
- Never auto-select product scope, user audience, phase boundary, external integration, auth/security, deployment, data deletion, dependency addition, verification removal, or anything outside allowed paths.
- Stop and ask the user when the choice affects destructive actions, external systems, secrets, deployment, purchase, deletion, broad scope, phase boundaries with multiple plausible product directions, or missing verification.

### `--chain`

Run `discuss -> plan -> execute` automatically using recommended answers, but only inside one coherent phase and one approved plan.

Rules:

- Perform the phase-local `discuss` summary.
- Write the plan with `plan_id`, `allowed_paths`, acceptance criteria, and verification.
- Treat the user's `--chain` request as permission to prepare approval state for the generated plan, not as permission to bypass the execute gate.
- Before implementation, verify or write `.scratch/phase-state.json` with `phase=execute`, the same `plan_id`, `approved=true`, non-empty `allowed_paths`, non-empty `verification`, durable planning pointers, and recorded `automation_mode=chain`.
- Any `phase=execute` state with `approved=true`, including `automation_mode=manual`, must also record non-empty `approved_by` and `approved_at` provenance.
- If phase state cannot be updated or verified, stop before implementation.
- Stop before execute if the plan lacks verification, `allowed_paths`, durable planning pointers, or a concrete first slice.
- Stop during execute if implementation exceeds the plan, verification fails outside approved scope, or adversarial review finds a P1 blocker.

`--chain` is not permission for unrelated follow-up phases. New work starts a new phase-local `discuss`.

## Phase Rules

### discuss

Allowed:

- Read files.
- Search the codebase.
- Ask clarifying questions.
- Summarize current behavior, risks, and options.

Forbidden:

- Editing files.
- Creating issue plans.
- Running formatters, migrations, generators, or tests that write files.
- Starting implementation.

Output:

- Findings.
- Open questions.
- Recommended next phase.
- If `--auto` or `--chain` is active, list recommended defaults selected and any stop conditions checked.

Next step:

- If enough is known, ask to move to `plan`.
- If `--auto` is active and no blocking preference remains, move to `plan` using recommended defaults.
- If `--chain` is active and no stop condition remains, continue into `plan` using recommended defaults.
- If not enough is known, stay in `discuss` and ask the smallest blocking question.

### plan

Allowed:

- Write or update docs, PRDs, ADRs, checklists, or local issue-plan files.
- Hydrate `.planning/codebase/**` and active `.planning/phases/**` documents from the real repository during `project init` or existing-repository adoption.
- Define acceptance criteria.
- Define test strategy and verification commands.
- Define exact implementation scope and file ownership.

Forbidden:

- Changing application behavior.
- Editing source code, migrations, generated artifacts, or tests unless the user explicitly classifies the test file as planning documentation.
- Installing dependencies.
- Running code generators that alter implementation files.

Output:

- A concrete plan with `plan_id`.
- Scope, non-goals, touched paths, acceptance criteria, and verification.
- Planning-memory updates made or required, including `.planning/codebase/**` and active phase files.
- Approval request to enter `execute`.
- If `--auto` or `--chain` is active, `auto_selected` entries and the stop-condition check.

Next step:

- Stop and ask for approval. Do not execute until state has `phase=execute`, the same `plan_id`, and `approved=true`.
- With `--chain`, continue to `execute` only when the user requested chaining, the generated plan is concrete, verification is non-empty, allowed paths are non-empty, and no stop condition remains.
- Also verify `.scratch/phase-state.json` has `phase=execute`, matching `plan_id`, `approved=true`, `automation_mode=chain`, non-empty `allowed_paths`, and non-empty `verification` before any implementation under `--chain`.

### execute

Allowed:

- Implement only the approved plan.
- Add or update tests required by the plan.
- Run verification commands.
- Update execution notes that cite the approved plan.

Required:

- Every execute response must cite `phase=execute`.
- Every execute response must cite the approved `plan_id`.
- Confirm the requested edits are inside `allowed_paths`.
- Confirm `verification` is non-empty before editing.
- Confirm `.planning/codebase/**` and the active phase docs are not stale relative to the approved plan.
- If implementation scope changes, stop and return to `plan`.

Forbidden:

- Implementing work not covered by the approved `plan_id`.
- Reusing stale approval from a different plan.
- Silently expanding scope.

Output:

- Changed paths.
- Verification evidence.
- Any scope deviations, or `none`.

Next step:

- If verification passes and the work is complete, move to `done`.
- If verification fails, stay in `execute` and fix only issues inside the approved plan.

### done

Allowed:

- Summarize results.
- Record final verification.
- Identify follow-up work as new discuss or plan candidates.
- Update `.planning/STATE.md`, the active phase checkpoint, and verification/summary docs to make the next session resumable.

Forbidden:

- More implementation under the completed `plan_id`.

Output:

- Final changed paths.
- Rationale.
- Verification.
- Follow-up candidates, if any.

Next step:

- Start a new `discuss` phase for new work.

## Low-Reasoning Checklist

Use this checklist at the top of every response:

```text
phase: <discuss|plan|execute|done>
plan_id: <id or none>
approved: <true|false>
allowed_work: <read-only|docs-plan-only|implementation|summary-only>
planning_context: <complete|needs-codebase-hydration|needs-phase-hydration|stale>
automation_mode: <manual|auto|chain>
auto_selected: <none|summary>
next_step: <one concrete next action>
```

## Stop Conditions

- Stop before editing if `phase=discuss`.
- Stop before implementation if `phase=plan`.
- Stop before implementation if `phase=execute` but `approved` is not `true`.
- Stop before implementation if `phase=execute` but `plan_id` is missing.
- Stop before implementation if `phase=execute` but `allowed_paths` is empty.
- Stop before implementation if `phase=execute` but `verification` is empty.
- Stop before implementation if existing-repository planning context is missing or stale.
- Stop before `plan` if phase-local `discuss` has not identified the first usable slice, non-goals, recommended defaults, and verification evidence.
- Stop before auto-selection if the choice is high-risk, destructive, external, security-sensitive, or not reversible.
- Stop before chained execute if adversarial review reports an unresolved P1 blocker.
- Stop if the requested change is outside the approved plan.
- Stop if ROADMAP, STATE, the active checkpoint file, and `.scratch/phase-state.json` disagree about phase progress or the active checkpoint.
