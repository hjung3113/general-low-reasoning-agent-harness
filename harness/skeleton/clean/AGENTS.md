## Agent Skills

Project-local workflow skills live under `.agents/skills/` as composable plugins and under adapter-owned folders for client-specific skills. Keep project-specific skills in the target repository instead of installing them globally.

## Planning State

Start with `python3 scripts/show_phase_status.py` when available. If it reports warnings, treat named files as minimum required reads before trusting the projection. If it is missing, fails, emits malformed output, or reports an unsupported contract version, use the legacy durable planning read order.

If `.scratch/phase-state.json` is not `phase=execute` with `approved=true`, do not modify application code. Documentation, harness, and setup changes are allowed only when explicitly requested.

Before creating or reshaping ROADMAP phases, phase folders, ADR decisions, or phase success criteria, run a `grill-me` style alignment pass: ask one question at a time, give the recommended answer and reason, inspect the repo instead of asking when the repo can answer, and record an alignment summary with confirmed facts, inferred facts, user preferences, recommended defaults, open questions, and blocked decisions. Do not turn unconfirmed preferences into phase commitments.

Every roadmap phase starts with its own `discuss` pass before `plan` or `execute`. Before finalizing ADR decisions or phase commitments, run an adversarial review with two relevant expert roles, three lenses each, and the mandatory lens of whether the questions are concrete enough for low-reasoning models. `--auto` may select recommended low-risk defaults and must record auditable `auto_selected` entries. `--chain` may continue through one phase's `discuss -> plan -> execute` only when `.scratch/phase-state.json` is verified or written with `phase=execute`, the same `plan_id`, `approved=true`, `automation_mode=chain`, durable pointers, allowed paths, verification, and review checks.

## Project-Specific Instructions

Project-specific agent instructions belong outside this harness-managed marker block.
Do not edit this marker block manually; use `harness.py upgrade` to update it.

## Skill Plugins

The generic profile is active until repository evidence or explicit user input confirms a more specific project profile. Workflow skills are plugins selected per request, not fixed technology presets.

- Do not mention, run, scaffold, or recommend commands from inactive profiles.
- Do not use a skill just because a file resembles a stack; use repository evidence first.
- Select the smallest set of installed skills that match the phase concern.
- Record active skills, evidence paths, rejected skills, and blocked decisions in the active phase context.
- If a needed skill is missing, document the need and ask before creating or installing a project-specific skill.

## Coding Conduct

These defaults incorporate the Karpathy-Inspired Coding Guidelines from `multica-ai/andrej-karpathy-skills`.

### Think Before Coding

Do not assume silently or hide uncertainty.

- State assumptions explicitly before implementing when they affect the solution.
- If a request has multiple reasonable interpretations, surface them instead of choosing silently.
- If a simpler approach exists, mention it and prefer it unless the project context requires otherwise.
- If the requirement is unclear enough that implementation would be risky, stop and ask a focused question.

### Simplicity First

Use the minimum code needed to solve the requested problem.

- Do not add features beyond what was asked.
- Do not introduce abstractions for single-use code.
- Do not add flexibility, configurability, or defensive handling for scenarios that are not required.
- If the implementation becomes much larger than the problem warrants, simplify before finishing.

### Surgical Changes

Touch only what is needed for the requested outcome.

- Do not refactor, reformat, or improve adjacent code unless it is required for the task.
- Match the existing style and project patterns, even when another style would also be valid.
- If unrelated dead code or cleanup opportunities are found, mention them instead of deleting them.
- Remove imports, variables, functions, and files that become unused because of your own changes.

Every changed line should trace back to the user's request or to verification required by that request.

### Goal-Driven Execution

Turn each task into a verifiable goal and keep working until it is checked.

- For bug fixes, reproduce the bug or add a regression test when practical, then make it pass.
- For validation or behavior changes, cover the changed behavior with focused tests when practical.
- For refactors, verify behavior before and after with the existing relevant checks.
- For multi-step work, keep a brief plan with each step tied to a verification command or observable result.

Weak success criteria such as "make it work" are not enough for larger tasks; define the concrete behavior, check, or artifact that proves completion.
