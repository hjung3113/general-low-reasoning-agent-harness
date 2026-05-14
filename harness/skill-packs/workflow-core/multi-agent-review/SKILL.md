---
name: multi-agent-review
description: Use before release, push, or broad workflow changes that need independent adversarial review from multiple expert perspectives.
---

# Multi-Agent Review

Use this skill when one reviewer is not enough.

## Low-Reasoning Contract

Reviewer personas must be concrete and non-overlapping. Do not ask three agents the same vague question.

For each reviewer, define:

- persona
- files or concerns to inspect
- pass/fail criteria
- output format

## Required Reviewer Set

For harness, workflow, or skill-pack releases, use at least:

1. Low-reasoning workflow reviewer: checks concrete steps, stop conditions, and evidence shape.
2. Skill ecosystem reviewer: checks whether external research became useful local workflow, not copied cargo cult.
3. Release engineer: checks installer matrix, manifest ownership, checks, git state, and push readiness.

## Workflow

1. Run local self-review first so reviewers inspect the real current state.
2. Dispatch reviewers in parallel when available.
3. Treat any `NO-PASS` as blocking until addressed or explicitly documented as accepted risk.
4. After fixes, record the reviewer verdicts and evidence in the phase verification file.
5. Do not claim release readiness until local verification also passes.

## Output

```yaml
reviewers:
  - persona: ""
    verdict: PASS
    blocking_findings: []
    addressed_by: []
accepted_risks: []
release_decision: PASS
```

