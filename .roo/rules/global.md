# Global Rules

- Roo is an adapter. Shared project truth lives in `AGENTS.md`, `.planning/**`, and `.scratch/phase-state.json`.
- Start with `harness check` when available. If it reports warnings, treat named files as minimum required reads before trusting the projection. If it is missing, fails, emits malformed output, or reports an unsupported contract version, use the legacy durable planning read order.
- Check `.roo/rules/phase-gate.md` before implementation workflows; no editable implementation work starts unless the status projection has `projected_execute_gate_valid=true`, no blocking warnings, and canonical files confirm approval provenance, acceptance criteria, durable pointers, allowed paths, and verification.
- Use the generic profile until repository evidence or explicit user input confirms a stack-specific profile.
- Do not mention, run, scaffold, or recommend commands from inactive profiles.
- Do not assume a programming language, runtime, database, architecture, test framework, package manager, or deployment target.
- Follow TDD for implementation when changing behavior: red evidence before production edits, smallest green change, record green evidence, then refactor.
- Do not defer tests for later when changing behavior unless the approved plan explicitly records why verification is impossible.
- Do not implement domain code when the request is to configure adapters, modes, skills, profiles, or workflow orchestration.
- Keep changes scoped to the requested workflow and approved paths.
