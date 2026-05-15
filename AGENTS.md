## Agent Skills

Project-local workflow skills live under `.agents/skills/` as composable plugins. Adapter-specific skills may live under adapter-owned folders such as `.roo/skills/`.

## Planning State

Start with `python3 scripts/show_phase_status.py` when available. If it reports warnings, treat named files as minimum required reads before trusting the projection. If it is missing, fails, emits malformed output, or reports an unsupported contract version, use the legacy durable planning read order.

If `.scratch/phase-state.json` is not `phase=execute` with `approved=true`, do not modify application code. Documentation, harness, adapter, profile, and skill-pack changes are allowed only when explicitly requested.

Every roadmap phase starts with its own `discuss` pass before `plan` or `execute`. Before finalizing phase commitments, run adversarial review and include the mandatory lens of whether the workflow is concrete enough for low-reasoning models.

## Current Repository

This repository is the generalized low-reasoning agent harness source.

- Core protocol must stay client-neutral and stack-neutral.
- Roo and OpenCode are adapters, not sources of truth.
- `.planning/**` is canonical memory.
- `.scratch/phase-state.json` is only the live gate.
- Skill packs are composable workflow plugins selected per request.
- Stack-specific assumptions must live in optional profiles, packs, examples, or project-local skills.

## Coding Conduct

### Think Before Coding

Do not assume silently or hide uncertainty.

- State assumptions explicitly before implementing when they affect the solution.
- If a request has multiple reasonable interpretations, surface them.
- If a simpler approach exists, mention it and prefer it unless project context requires otherwise.
- If implementation would be risky without clarification, ask a focused question.

### Simplicity First

Use the minimum code needed to solve the requested problem.

- Do not add features beyond what was asked.
- Do not introduce abstractions for single-use code.
- Do not add flexibility for scenarios not required.

### Surgical Changes

Touch only what is needed.

- Do not refactor or reformat adjacent code unless required.
- Match existing style.
- Remove unused code created by your own changes.

### Goal-Driven Execution

Turn each task into a verifiable goal.

- For behavior changes, add or run focused tests.
- For refactors, verify behavior before and after.
- For multi-step work, keep a brief plan tied to verification.
