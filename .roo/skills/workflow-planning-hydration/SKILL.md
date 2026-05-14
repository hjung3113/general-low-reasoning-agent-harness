---
name: workflow-planning-hydration
trigger: Use when applying this harness to an existing repository, when planning docs are missing/stale/placeholder-only, when ADR work needs project context first, or when the user asks to fill `.planning/` from an existing project.
description: Hydrates durable `.planning/` memory for an existing repository without overlapping with generic project init. It inventories the repo, fills codebase notes, creates or reconciles phase docs, updates state/roadmap pointers, and classifies stale planning artifacts before ADR or implementation work continues.
---

# Workflow: Planning Hydration

This workflow is the existing-repository adoption path. It is intentionally **not** named `project init` because it does not create a brand-new project. It hydrates and reconciles `.planning/` from a repository that already exists.

## Goal

Make the repository self-resumable before ADR, issue planning, or implementation work continues.

After this workflow, a fresh agent should be able to read:

1. `AGENTS.md`
2. `.planning/STATE.md`
3. `.planning/ROADMAP.md`
4. `.planning/codebase/**`
5. the active `.planning/phases/**` document set
6. `.scratch/phase-state.json`

…and understand the current project, current phase, next action, verification expectations, and stale artifact status without chat history.

## When to Use

Use this workflow when any of these are true:

- A user says this harness was applied to an existing project.
- A user asks for ADR work but `.planning/codebase/**` or `.planning/phases/**` is missing, stale, or placeholder-only.
- `.planning/STATE.md`, `.planning/ROADMAP.md`, or `.scratch/phase-state.json` points to template content or a previous project.
- Existing planning files are present but appear unrelated to the current repo.
- The task looks like `project init`, but the repository already has code, docs, ADRs, issues, or planning history.

Do not use this workflow for a truly empty repository where no project context exists yet. In that case, use the normal planning/ADR flow to discover the project first.

## Inputs to Read

Read in this order:

1. `AGENTS.md`
2. `README.md`
3. Build/test/package files, such as solution files, project files, package manifests, lockfiles, Docker/CI files, or scripts.
4. Source and test folder names.
5. Existing docs: `CONTEXT.md`, `CONTEXT-MAP.md`, `docs/**`, `docs/adr/**`.
6. Existing `.planning/**` and `.scratch/phase-state.json`.
7. Recent issue/PR notes if available in `.scratch/**`.

## Output Files

### Pass 0 Low-Reasoning Limit

Pass 0 is intentionally narrow. Write or update only:

- `.planning/PROJECT.md`
- `.planning/STATE.md`
- `.planning/ROADMAP.md`
- `.planning/codebase/STRUCTURE.md`
- `.planning/phases/00-planning-hydration/00-CHECKPOINTS.md`

During Pass 0, record open questions and stop for review. Do not hydrate every codebase note, create a real implementation phase, or mark planning context usable until that review is complete.

Hydrate or create these files when they are missing or placeholder-only:

- `.planning/PROJECT.md`
- `.planning/REQUIREMENTS.md`
- `.planning/ROADMAP.md`
- `.planning/STATE.md`
- `.planning/DECISIONS.md`
- `.planning/VERIFICATION.md`
- `.planning/codebase/ARCHITECTURE.md`
- `.planning/codebase/STACK.md`
- `.planning/codebase/STRUCTURE.md`
- `.planning/codebase/CONVENTIONS.md`
- `.planning/codebase/TESTING.md`
- `.planning/codebase/INTEGRATIONS.md`
- `.planning/codebase/CONCERNS.md`
- `.planning/phases/<NN-current-phase>/NN-CONTEXT.md`
- `.planning/phases/<NN-current-phase>/NN-01-PLAN.md`
- `.planning/phases/<NN-current-phase>/NN-CHECKPOINTS.md`
- `.planning/phases/<NN-current-phase>/NN-REVIEW.md`
- `.planning/phases/<NN-current-phase>/NN-VERIFICATION.md`
- `.planning/phases/<NN-current-phase>/NN-01-SUMMARY.md`

Update `.scratch/phase-state.json` only when the user explicitly asks for harness/planning-control changes or when the current task is already scoped to phase-state repair. Keep it in `discuss` or `plan` unless implementation has been explicitly approved.


## Execution Model

When invoked from `orchestrator`, do not execute this workflow inline.

The orchestrator must create a focused subtask in the owning mode and pass the required handoff packet from `.roo/rules-orchestrator/rules.md`.

The owning mode must reload durable context from `.planning/` and `.scratch/phase-state.json`, perform only its owned work, and return the required structured result.

If the task cannot proceed because planning context is missing, stale, placeholder-only, or outside the approved phase gate, return `needs-plan` instead of guessing.

## Steps

### 1. Inventory the repository

Create a concise inventory:

- project name and repository path
- detected language/runtime/frameworks
- source directories
- test directories and test runner
- build, lint, and verification commands if discoverable
- docs and ADR locations
- external services, databases, queues, APIs, or deployment surfaces
- current `.planning/` and `.scratch/` state

Do not invent missing commands. Mark them as unknown when the repo does not prove them.

### 2. Align with the user before creating phases

Before creating or reshaping `.planning/ROADMAP.md`, `.planning/STATE.md`, or `.planning/phases/**`, run a `grill-me` style alignment pass:

- Ask one question at a time and include your recommended answer with the reason.
- If the repository can answer the question, inspect the repository instead of asking.
- Cover at least: project purpose, target user, current pain, desired outcome, non-goals, hard constraints, acceptable tradeoffs, phase granularity, first useful phase, success criteria, verification evidence, and explicitly unwanted work.
- Record an alignment summary in the active phase context or `.planning/PROJECT.md`: confirmed facts, repository-derived facts, user-stated preferences, recommended defaults, open questions, and decisions blocked by those questions.
- Do not convert guesses into phases. If the user has not confirmed a preference and the repository does not prove it, keep it as an open question or recommended default.
- Use the concrete phase-local question template from `workflow-phase-gate`. Each template question must have `repo_answer`, `user_answer`, or `open_blocker` before this workflow may create or reshape phase plans.

Stop with `needs-info` when the next phase boundary or first useful slice depends on an unresolved user preference.

### 3. Run adversarial review before phase commitments

Before writing final ROADMAP phases, active phase plans, or phase success criteria:

- Select two adversarial expert roles relevant to the project. If the domain is unclear, use:
  - Product/user expert with lenses: question concreteness for low-reasoning models, user value, non-goals/scope creep.
  - Architecture/operations expert with lenses: first usable slice, boundary correctness, verification/failure risk.
- Expert 1 lens 1 must be: are the alignment questions concrete enough for a low-reasoning model to ask the right questions and choose recommended defaults safely?
- Record each finding as `critique`, `reinforcement point`, and `change made`.
- Apply each reinforcement point before marking planning context usable, or record it as `deferred`/`rejected` with a reason.

Do not mark planning context usable while P1 adversarial findings remain unresolved.

### 4. Apply automation flags

- `--auto`: choose recommended defaults only for documentation wording, ordering, naming, or repo-proven defaults inside allowed paths; record auditable `auto_selected` entries.
- `--chain`: continue from phase-local `discuss` to `plan` and then `execute` only when the generated plan has a concrete first slice, non-empty verification, non-empty allowed paths, current durable planning pointers, no unresolved P1 adversarial finding, and `.scratch/phase-state.json` has been verified or written with `phase=execute`, matching `plan_id`, `approved=true`, and `automation_mode=chain`.
- Stop for user input on destructive, external, secret-bearing, deployment, deletion, irreversible, broad-scope, or ambiguous product-direction choices.

### 5. Detect planning state

Classify existing planning memory as one of:

- `absent`: files are missing
- `template-only`: files exist but still contain placeholders
- `stale`: files describe a previous project or old phase
- `partial`: some files are valid but required sections are missing
- `usable`: files describe the current project and can be updated incrementally

### 6. Hydrate codebase notes

Populate `.planning/codebase/**` from observed repository facts.

Minimum expectations:

- `ARCHITECTURE.md`: system overview, ownership boundaries, known flows
- `STACK.md`: runtime, frameworks, package/build/test tooling
- `STRUCTURE.md`: major directories and responsibilities
- `CONVENTIONS.md`: naming, testing, branching, doc, and phase conventions
- `TESTING.md`: known commands, test gaps, external dependencies
- `INTEGRATIONS.md`: databases, APIs, queues, files, auth, CI/CD
- `CONCERNS.md`: risks, unknowns, migration hazards, operational concerns

### 7. Hydrate phase docs

Ensure there is exactly one active phase folder for the current work.

Every active phase folder begins with phase-local `discuss`, then proceeds to `plan`, `execute`, and `done`. Do not create only a plan file for a new phase without recording the phase-local discussion context.

Required pattern:

```text
.planning/phases/<NN-phase-slug>/
  NN-CONTEXT.md
  NN-01-PLAN.md
  NN-CHECKPOINTS.md
  NN-REVIEW.md
  NN-VERIFICATION.md
  NN-01-SUMMARY.md
```

For adoption work, prefer a phase name like:

```text
01-existing-project-planning-hydration
```

Do not overwrite valuable historical phase evidence. Move stale content to an archive candidate list unless the user explicitly requests deletion.

### 8. Reconcile stale artifacts

Create a reconciliation section in the active phase review or context with three buckets:

- `keep`: valid project memory
- `archive`: old but useful historical evidence
- `delete candidate`: template residue or unrelated previous-project content
- `needs-human`: ambiguous files that require confirmation

Never silently delete ambiguous planning files.

### 9. Sync state and roadmap

Update:

- `.planning/STATE.md`: current phase, checkpoint, blocker, next action, files of record
- `.planning/ROADMAP.md`: phase list and success criteria
- `.planning/DECISIONS.md`: decisions already in force
- `.planning/VERIFICATION.md`: known commands and evidence gaps
- `.scratch/phase-state.json`: only when explicitly in scope

### 10. Stop before implementation

This workflow is planning-only. It can prepare implementation plans, but it must not modify application behavior.

If implementation is needed, produce the next workflow route and required approval state.

## Adversarial Verification

Before finishing, challenge the result with these checks:

1. **Wrong-project check**: Do any `.planning/**` files still name a previous project, template-only project, or unrelated phase?
2. **Placeholder check**: Do required planning docs still contain `<name>`, empty success criteria, or generic template text where repository-specific facts are available?
3. **ADR bypass check**: Could `/adr` proceed without reading `.planning/codebase/**` and active phase docs?
4. **Phase bypass check**: Could `phase=execute` be accepted while active phase docs are missing, stale, or empty?
5. **Permission check**: Are implementation modes still prevented from editing `.planning/**`?
6. **Deletion safety check**: Were ambiguous legacy planning files preserved or marked `needs-human` instead of silently deleted?
7. **Idempotency check**: If this workflow runs again, will it converge without duplicating sections or recreating archived stale content?
8. **Verification honesty check**: Are missing commands marked unknown instead of invented?
9. **Resume check**: Can a new session follow `AGENTS.md -> STATE -> ROADMAP -> codebase -> active phase -> phase-state` and continue?

Record failed checks in the active phase review with owner and next action.

## Output Format

When reporting completion, include:

```text
status: <done|needs-info>
phase: plan
planning_context: <absent|template-only|stale|partial|usable> -> <usable|needs-human>
active_phase: <path>
updated_files:
  - <path>
stale_artifacts:
  keep:
  archive:
  delete_candidate:
  needs_human:
next_step: <one concrete action>
```

## Routing

- Primary owner: `architect` or `docs-issues`.
- Route changes to `.roo/**`, `.roomodes`, `AGENTS.md`, or `CLAUDE.md` to `harness-maintainer`.
- Route application implementation to the narrowest implementation workflow only after phase-gate approval.

## Hard Rules

- Do not call this `project init` in user-facing instructions.
- Do not implement application code.
- Do not overwrite or delete historical planning artifacts without classification.
- Do not mark planning context usable while codebase notes or active phase docs are placeholder-only.
- Do not invent repository facts that were not observed.
- Do not create or reshape phase boundaries from unconfirmed model assumptions.
- Do not mark planning context usable while adversarial review has unresolved P1 findings.
- Do not let `--auto` or `--chain` bypass phase-local discuss, adversarial review, durable planning pointers, allowed paths, or verification.
