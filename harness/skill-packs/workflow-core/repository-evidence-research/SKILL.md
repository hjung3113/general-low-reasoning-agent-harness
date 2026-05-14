---
name: repository-evidence-research
description: Use during discuss or hydration to discover project facts before selecting profiles, tools, workflows, or implementation slices.
---

# Repository Evidence Research

Use this skill before making project-specific claims.

## Workflow

1. Inspect repository evidence: README, package/build files, source layout, tests, docs, CI, scripts, and existing planning docs.
2. Record confirmed facts with file paths.
3. Separate inferred facts from confirmed facts.
4. List unknowns that require user confirmation.
5. List rejected assumptions that must not be used by downstream skills.

## Output

Write findings into the active phase context or `.planning/codebase/**`:

- confirmed facts
- inferred facts
- rejected assumptions
- open questions
- recommended active profiles or skill plugins

Do not modify application code.

