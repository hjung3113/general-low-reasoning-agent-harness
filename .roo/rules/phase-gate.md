# Phase Gate Rule

Use `.scratch/phase-state.schema.json` for external phase state. Durable phase memory lives under `.planning/`; fresh sessions read `.planning/STATE.md`, `.planning/ROADMAP.md`, `.planning/codebase/**`, and the active phase checkpoint before trusting the live gate file. Implementation workflows must pass this gate before editable work starts.

## Required Behavior

- Default to `discuss` when no phase state is present.
- Treat `.planning/STATE.md`, `.planning/ROADMAP.md`, `.planning/codebase/**`, and the active `.planning/phases/*/*-CHECKPOINTS.md` as the restart source of truth; `.scratch/phase-state.json` is only the live gate pointer.
- During existing-repository adoption or `project init`, treat missing, placeholder-only, or stale `.planning/codebase/**` and active `.planning/phases/**` files as an incomplete gate that must return to `plan` for hydration.
- Treat `discuss` as read-only discovery.
- Treat `plan` as documentation, ADR, PRD, checklist, issue-plan, or planning-memory hydration work only.
- Treat `execute` as implementation only after the state cites the approved `plan_id`, has `approved=true`, defines non-empty `allowed_paths`, and defines non-empty `verification`.
- Treat `done` as summary and verification only, including updates to `.planning/STATE.md`, active checkpoints, and verification/summary docs.
- Start every roadmap phase with a phase-local `discuss` pass before writing that phase's plan. A new phase must not jump directly from the previous phase's `done` into the next phase's `plan`.
- Honor `--auto` by accepting recommended non-blocking defaults only when they are reversible, low risk, inside the current allowed work, and recorded in `auto_selected` or the active phase context.
- Honor `--chain` by running recommended `discuss -> plan -> execute` only for one concrete phase and one approved plan. Stop before execute when verification, allowed paths, durable planning pointers, or the first usable slice are missing.
- `/feature`, `/bugfix`, `/etl`, `/db`, and `/ops` must check this gate before implementation.
- `/adr` and `project init` must check and maintain `.planning/codebase/**` and `.planning/phases/**` when the decision or initialization affects durable project context.
- Every execute response must explicitly cite `phase=execute` and the approved `plan_id`.
- If requested work exceeds the approved plan, stop and return to `plan`.

## Planning Context Completeness

For an existing repository, the planning context is complete only when:

- `.planning/STATE.md` names the current phase, checkpoint, next action, and relevant files of record.
- `.planning/ROADMAP.md` reflects the current project roadmap, not a generic template or unrelated previous project.
- `.planning/codebase/` captures the current repository's architecture, stack, structure, conventions, testing approach, integrations, and concerns.
- `.planning/phases/` has an active phase folder with context, plan, checkpoints, review, verification, and summary files relevant to the current project.
- `.scratch/phase-state.json` points to current planning files and does not reference stale or unrelated phase artifacts.

If any item is missing or stale, do not proceed to implementation. Hydrate or reconcile planning memory in `plan` first.

## Adversarial Review Before Commitment

Before finalizing ADR decisions, ROADMAP phases, phase plans, or phase success criteria:

- Pick two adversarial expert roles relevant to the requested work.
- Give each expert three explicit review lenses.
- Include one mandatory lens: whether the questions are concrete enough for a low-reasoning model to align with the user's intent.
- Convert findings into reinforcement points.
- Apply the reinforcement points or record them as deferred/rejected with reasons.

Unreviewed phase plans are drafts, not executable plans.

## Mechanical Limits

Roo skills and rules are prompt-level controls. They can instruct, route, and checklist model behavior, but they do not by themselves lock files, reject commits, validate JSON, or prevent another actor from editing implementation files.

For mechanical enforcement, add external tooling such as:

- JSON Schema validation for `.scratch/phase-state.json`.
- A pre-commit hook that rejects implementation diffs unless `phase=execute`, `approved=true`, and `plan_id` is present.
- CI checks that compare changed paths against the approved `allowed_paths`.
- Repository permissions or branch protection for human approval.
