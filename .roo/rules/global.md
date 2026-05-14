# Global Rules

- Roo is an adapter. Shared project truth lives in `AGENTS.md`, `.planning/**`, and `.scratch/phase-state.json`.
- Read durable planning state before editing: `AGENTS.md`, `.planning/STATE.md`, `.planning/ROADMAP.md`, `.planning/codebase/**`, the active phase checkpoint, active phase docs, then `.scratch/phase-state.json`.
- Check `.roo/rules/phase-gate.md` before implementation workflows; no editable implementation work starts unless phase state is `execute`, `approved=true`, and tied to an approved `plan_id`.
- Use the generic profile until repository evidence or explicit user input confirms a stack-specific profile.
- Do not mention, run, scaffold, or recommend commands from inactive profiles.
- Do not assume a programming language, runtime, database, architecture, test framework, package manager, or deployment target.
- Follow TDD for implementation when changing behavior: red evidence before production edits, smallest green change, record green evidence, then refactor.
- Do not defer tests for later when changing behavior unless the approved plan explicitly records why verification is impossible.
- Do not implement domain code when the request is to configure adapters, modes, skills, profiles, or workflow orchestration.
- Keep changes scoped to the requested workflow and approved paths.
