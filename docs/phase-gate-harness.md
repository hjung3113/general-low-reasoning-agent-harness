# Phase Gate Harness

This harness gives Roo agents a small external state machine for work that must move through discussion, planning, execution, and completion without skipping approval. Implementation commands in this template must check the phase gate before editable work starts.

## State File

Use `.scratch/phase-state.schema.json` to validate phase state. A typical live state file should be named `.scratch/phase-state.json`. See `.scratch/phase-state.example.json` for a complete example.

The live state file is a gate, not the full project memory. Fresh sessions must read `.planning/STATE.md` first, then `.planning/ROADMAP.md`, then the active phase checkpoint file. The live state must point back to durable docs with:

- `state_path`
- `plan_path`
- `checkpoint_path`
- `current_checkpoint`
- `next_action`

## Roadmap/State Sync Invariant

The roadmap is the source for phase count and completion. Any ADR, phase plan, or checkpoint update that adds, deletes, inserts, renumbers, completes, or reopens a roadmap phase must update these files together:

- `.planning/ROADMAP.md`
- `.planning/STATE.md`
- the active phase `*-CHECKPOINTS.md`
- `.scratch/phase-state.json`

Keep these fields aligned:

- ROADMAP `## Phases` checklist total -> STATE frontmatter `progress.total_phases`
- ROADMAP completed checklist items -> STATE frontmatter `progress.completed_phases`
- ROADMAP completion percentage -> STATE frontmatter `progress.percent`
- first incomplete ROADMAP phase -> STATE `Current Position` active phase
- STATE active checkpoint and checkpoint file -> `.scratch/phase-state.json` `current_checkpoint` and `checkpoint_path`
- `.scratch/phase-state.json` `state_path` -> `.planning/STATE.md`

Run `python3 scripts/harness.py check` before handing off phase or ADR changes. The check is read-only and fails strict on drift.

Run `python3 scripts/harness.py doctor` when a low-reasoning agent needs repair guidance before mutation. Doctor is also read-only, but it reports structured severity, cause, impact, fix, evidence, and diff-before-mutation guidance instead of failing at the first strict check.

The four phases are:

| Phase | Allowed work | Next step |
| --- | --- | --- |
| `discuss` | Read-only discovery: inspect files, search, ask questions, summarize options | Move to `plan` when enough is known |
| `plan` | Docs, ADRs, PRDs, checklists, and issue-plan files only | Ask for approval to enter `execute` |
| `execute` | Implementation and verification for the approved plan only | Move to `done` after verification |
| `done` | Final summary, rationale, verification, and follow-up candidates | Start a new `discuss` for new work |

Each roadmap phase has its own lifecycle:

```text
phase-N discuss -> phase-N plan -> phase-N execute -> phase-N done
```

A new phase must not skip directly to `plan`. Its phase-local `discuss` pass records the phase problem, target user/operator, non-goals, first usable slice, repo-derived answers, user-preference questions, recommended defaults, and verification evidence candidates.

## Automation Flags

Automation flags may be passed in the user's Roo command or prompt. They change how choices are resolved, not what the gate allows.

- `manual`: default. Ask the user for choices that affect scope, phase boundaries, acceptance criteria, or implementation authority.
- `--auto`: use recommended answers only for documentation wording, ordering, naming, or repo-proven defaults inside current allowed paths. Record auditable automatic choices in `auto_selected` or the active phase context.
- `--chain`: run one phase's `discuss -> plan -> execute` path using recommended answers when the generated plan has `plan_id`, durable pointers, non-empty `allowed_paths`, non-empty `verification`, no unresolved P1 adversarial findings, and `.scratch/phase-state.json` has been verified or written with `phase=execute`, the same `plan_id`, `approved=true`, and `automation_mode=chain`.

Both `--auto` and `--chain` must stop for destructive, external, secret-bearing, deployment, deletion, irreversible, broad-scope, or ambiguous product-direction choices.

## Adversarial Review

Before final ADR decisions, ROADMAP phases, phase plans, or success criteria are treated as executable, run an adversarial review:

1. Select two expert roles relevant to the work.
2. Give each expert three review lenses.
3. Include one mandatory lens: whether the questions are concrete enough for a low-reasoning model to align with the user's intent.
4. Convert findings into reinforcement points.
5. Apply each point or record it as deferred/rejected with a reason.

Unreviewed plans remain drafts.

## Execute Gate

Execution is allowed only when all of these are true:

- `phase` is `execute`.
- `approved` is `true`.
- `plan_id` is present.
- `state_path`, `plan_path`, `checkpoint_path`, `current_checkpoint`, and `next_action` are present.
- `allowed_paths` is non-empty.
- `verification` is non-empty.
- The requested implementation is inside the approved plan.

Every execute response must cite both:

```text
phase=execute
plan_id=<approved plan id>
```

If the work no longer matches the approved plan, stop implementation and return to `plan`.

## What Roo Can Enforce

The current Roo harness can mechanically help by:

- Loading workflow instructions from `.roo/skills/workflow-phase-gate/SKILL.md`.
- Loading prompt rules from `.roo/rules/phase-gate.md` when included by the mode or operator.
- Making low-reasoning models follow a visible checklist.
- Requiring the agent to state the current phase, plan id, approval status, allowed work, and next step.
- Making phase violations reviewable in the transcript.

## What Roo Cannot Enforce Alone

Roo skills and rules are not a file-system lock or policy engine. By themselves, they cannot:

- Stop a model or human from editing files during `discuss`.
- Reject a commit when `phase` is not `execute`.
- Validate JSON state against the schema.
- Confirm that changed paths match the approved plan unless an external diff checker is added.
- Prove that approval came from the intended human or system.

For hard enforcement, add separate tooling: JSON Schema validation, pre-commit checks, CI diff checks against `allowed_paths`, branch protection, or repository permissions.

This harness includes `scripts/harness.py check` for local structure checks, phase-state automation semantics, and optional changed-path enforcement. Continue to run AJV schema validation as part of PR verification.

## Document-Centered Continuity

Use this restart order after any session reset:

1. `AGENTS.md`
2. `.planning/STATE.md`
3. `.planning/ROADMAP.md`
4. `.planning/codebase/ARCHITECTURE.md`, `STACK.md`, `STRUCTURE.md`, `CONVENTIONS.md`, `TESTING.md`, `INTEGRATIONS.md`, and `CONCERNS.md` when they exist
5. Active phase `*-CHECKPOINTS.md`
6. Active phase `*-CONTEXT.md`, `*-PLAN.md`, `*-REVIEW.md`, `*-VERIFICATION.md`, and `*-SUMMARY.md` when they exist
7. `.scratch/phase-state.json`

For `plan`, `execute`, and `done`, the phase-state schema requires enough pointers to resume from durable docs. If those pointers are missing, treat the state as incomplete and return to `plan`.

## Low-Reasoning Model Checklist

At the start of gated work, the agent should fill this in:

```text
phase: <discuss|plan|execute|done>
plan_id: <id or none>
approved: <true|false>
allowed_work: <read-only|docs-plan-only|implementation|summary-only>
automation_mode: <manual|auto|chain>
auto_selected: <none|summary>
next_step: <one concrete next action>
```

Then follow only the matching phase rules.
