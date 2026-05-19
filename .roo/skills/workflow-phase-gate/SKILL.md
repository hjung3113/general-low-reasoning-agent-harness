---
name: workflow-phase-gate
trigger: Use before any implementation workflow, when the user asks to gate work through discuss, plan, execute, or done phases, or when a task references phase-state approval.
description: Runs the external phase gate for low-reasoning models: discuss is read-only discovery, plan is docs or issue-plan only, execute requires approved plan_id, approved allowed_paths, verification, and phase=execute, and done records verification.
---

# Workflow: Phase Gate

Use this workflow before implementation to prevent accidental work before the user or orchestrator has approved a plan.

Apply `.roo/rules/phase-gate.md` before this workflow.

State lives outside the prompt in `.scratch/phase-state.json` or another file that follows `.scratch/phase-state.schema.json`. Durable project memory lives under `.planning/`; the live state file is a gate pointer, not the source of planning context.

## Required State Check

Before doing any work:

1. Start with `harness check` when available. If it reports warnings, treat named files as minimum required reads before trusting the projection. If it is missing, fails, emits malformed output, or reports an unsupported contract version, use the legacy durable planning read order.
2. Identify `phase`, `plan_id`, `approved`, `state_path`, `plan_path`, `checkpoint_path`, `current_checkpoint`, `allowed_paths`, and `verification`.
3. For `plan`, `execute`, and `done`, read `state_path`, `plan_path`, and `checkpoint_path` before classifying allowed work. If any pointer is missing or stale, treat the state as incomplete and return to `plan`.
4. If `.planning/codebase/**` or the active phase document set is missing, placeholder-only, or stale for the current repository, treat the gate as incomplete for existing-repository adoption and return to `plan` to hydrate planning memory.
5. Confirm roadmap/state sync: ROADMAP phase checklist totals and completion count must match STATE frontmatter progress, STATE active phase/checkpoint must match the active roadmap phase, and `.scratch/phase-state.json` must point to the same STATE and checkpoint.
6. Identify `execution_mode` from `.scratch/phase-state.json`. Default to `manual`.
7. If there is no state file, start in `discuss`.
8. Do only the work allowed by the current phase and automation mode.

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
- Before implementation, ensure the live gate reads `phase=execute, approved=true` with the same `plan_id`. Reach that state via `harness phase approve` (in `phase=plan`) followed by `harness phase set execute`. The CLI writes `approved_by`, `approved_at`, and re-stamps `updated_at`; pre-conditions the CLI does NOT set — `allowed_paths`, `verification`, durable planning pointers, `execution_mode=chain_autopilot` — remain user-editable and must be present before invoking `phase autopilot start --mode chain`.
- Any `phase=execute` state with `approved=true` carries `approved_by` and `approved_at` provenance set by `harness phase approve` (stamped from `git config user.email` and a nanosecond-precision UTC timestamp per ADR-003a Verb 2). Manual mode and chain mode produce identical provenance shape.
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

- Stop and ask for approval. Do not execute until the live gate has `phase=execute`, the same `plan_id`, and `approved=true`. Reach that state via `harness phase approve && harness phase set execute`.
- With `--chain`, continue to `execute` only when the user requested chaining, the generated plan is concrete, verification is non-empty, allowed paths are non-empty, and no stop condition remains.
- Under `--chain`, verify the live gate via `harness check` reports `phase=execute`, matching `plan_id`, `approved=true`, `execution_mode=chain_autopilot`, non-empty `allowed_paths`, and non-empty `verification` before any implementation.

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

Reach `phase=done` via `harness phase set done`. The CLI re-stamps `updated_at` and preserves `approved`, `approved_by`, `approved_at` verbatim from the prior `execute→done` transition. Do NOT re-issue `harness phase approve` in `done`; per G2-C it exits 6 (`EXIT_WRONG_PHASE_FOR_VERB`).

Allowed:

- Summarize results.
- Record final verification.
- Identify follow-up work as new discuss or plan candidates.
- Update `.planning/STATE.md`, the active phase checkpoint, and verification/summary docs to make the next session resumable.

Forbidden:

- More implementation under the completed `plan_id`.
- Re-issuing `harness phase approve` (no-op exit 6 in `done`).

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
execution_mode: <manual|phase_autopilot|chain_autopilot>
auto_selected: <none|summary>
next_step: <one concrete next action>
```

## Canonical CLI Invocation (post-CLI surface)

Move forward in the phase lifecycle via the CLI; do NOT direct-edit `.scratch/phase-state.json`.

```text
# Advance phase (writes phase, updated_at, updated_by; audits the write):
harness phase set <discuss|plan|execute|done>

# Approve in phase=plan or phase=execute (writes approved=true, approved_by, approved_at):
harness phase approve  # Do not run this yourself if the harness prompts [y/N]; ask the user.

# From phase=done, start a new cycle (safety prompt required):
harness phase set discuss --reset-approval
```

If the harness prints a `[y/N]` prompt, stop and ask the user to confirm from their own terminal. Do not answer the prompt yourself — speed-bump is the user's checkpoint.

`harness phase approve` in `phase=done` is a no-op error (exit 6, G2-C). Direct-editing the state file still works but emits an ADR-003a drift warning on the next `harness check` run.

## Canonical `phase=done` Example (post-CLI)

A valid `phase-state.json` for `phase=done` after the ADR-003a CLI lands. Field-level actor annotations live in `docs/adr/2026-05-16-hardening-bundle.md` Artifact 1 G3-A.

```json
{
  "state_schema_version": 2,
  "phase": "done",
  "approved": true,
  "approved_by": "hjung3113@gmail.com",
  "approved_at": "2026-05-16T19:30:45.123456789Z",
  "plan_id": "hardening-slice-01",
  "execution_mode": "manual",
  "auto_selected": [],
  "summary": "Hardening slice 02b complete: ADRs locked, atomic primitive landed, smoke green.",
  "state_path": ".planning/STATE.md",
  "plan_path": ".planning/phases/02-hardening/02b-PLAN.md",
  "checkpoint_path": ".planning/phases/02-hardening/02b-CHECKPOINTS.md",
  "current_checkpoint": "CP-02b-09",
  "next_action": "Start discuss for 02c-hardening.",
  "allowed_paths": ["scripts/", "docs/adr/", ".planning/"],
  "blocked_paths": [".harness/audit.log", ".harness/session.lock"],
  "acceptance_criteria": [
    "All six ADRs locked in a single PR.",
    "T0-A atomic primitive lands first."
  ],
  "verification": [
    "harness check",
    "pytest scripts/tests/ -v",
    "harness check --worktree"
  ],
  "review": [
    {
      "actor": "hjung3113@gmail.com",
      "at": "2026-05-16T19:00:00.000000000Z",
      "evidence_path": "docs/reviews/02b-architect.md",
      "summary": "Architect review of bundle; G2 items addressed."
    }
  ],
  "notes": [
    "approved fields preserved from execute->done transition; not re-stamped by CLI in done phase (G2-C)."
  ],
  "updated_at": "2026-05-16T19:30:45.123456789Z",
  "updated_by": "hjung3113@gmail.com"
}
```

`approved`/`approved_by`/`approved_at` are preserved verbatim from the prior `execute→done` transition; they are NOT re-stamped by `phase set done`. `phase approve` in `done` exits 6 (G2-C).

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
