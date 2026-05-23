---
name: repository-evidence-research
description: Use during discuss or hydration to discover project facts before selecting profiles, tools, workflows, or implementation slices.
reads:
  - codebase.stack.*
  - codebase.structure.*
  - codebase.summary.*
  - codebase.testing.commands
  - codebase.concerns.open_questions
---

# Repository Evidence Research

Use this skill before making project-specific claims.

## Low-Reasoning Contract

Do not summarize from memory. Build a small evidence ledger and keep each claim tied to a path, command, or user statement.

Start by checking `.planning/codebase/SUMMARY.md` and `STACK.md`. If they have `status: current` and recent `updated_at`, use their anchors as confirmed facts. If empty or stale, run `harness recon` (auto fills STACK/STRUCTURE/TESTING) and then invoke `workflow-codebase-recon` for the judgment files.

Stop and mark `blocked_until` when:

- the repo lacks enough evidence to select a tech pack
- the task depends on a hidden service, database, credential, or deployment target
- two files disagree about the project stack, command, or current phase
- a requested assumption would make the core harness stack-specific

## Workflow

1. Inspect repository evidence: README, package/build files, source layout, tests, docs, CI, scripts, and existing planning docs.
2. Record confirmed facts with file paths.
3. Separate inferred facts from confirmed facts.
4. List unknowns that require user confirmation.
5. List rejected assumptions that must not be used by downstream skills.
6. Recommend the smallest active profile and skill-plugin set.

## Evidence Ledger

Use this shape in the active phase context:

```yaml
confirmed:
  - fact: ""
    evidence: ""
inferred:
  - inference: ""
    basis: ""
unknowns:
  - question: ""
    blocks: ""
rejected_assumptions:
  - assumption: ""
    reason: ""
recommended_plugins:
  - skill: ""
    reason: ""
blocked_until: ""
```

## Output

Write findings into the active phase context or `.planning/codebase/**`:

- confirmed facts
- inferred facts
- rejected assumptions
- open questions
- recommended active profiles or skill plugins

Do not modify application code.
