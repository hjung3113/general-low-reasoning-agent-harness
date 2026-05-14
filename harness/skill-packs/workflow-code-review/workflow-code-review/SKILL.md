---
name: workflow-code-review
description: Use for reviewing a diff, branch, implementation plan, or release candidate for defects and missing verification.
---

# Workflow Code Review

Use this skill when the task is to review work or when a broad change is about to merge.

## Low-Reasoning Contract

Findings first. Do not summarize effort before checking for behavioral risk.

## Review Lenses

- correctness and regressions
- missing tests or weak verification
- scope drift beyond approved paths
- security, privacy, and data handling
- client-neutral and stack-neutral boundaries
- low-reasoning usability: concrete steps, stop signals, evidence fields

## Workflow

1. Identify the base, changed files, and intended behavior.
2. Read tests and implementation together.
3. Check whether verification covers each requirement.
4. Report only actionable findings with path references.
5. Separate blocking findings from residual risk.

## Output Contract

```yaml
verdict: PASS
findings:
  - severity: P1
    path: ""
    issue: ""
    fix: ""
missing_tests: []
residual_risk: []
```

## Worked Example

For a harness release, review `harness/manifest.json`, `scripts/harness.py`, `scripts/test_harness.py`, README examples, and `.planning/*VERIFICATION.md`; a missing manifest entry for a new skill is P1 because install targets silently omit it.

