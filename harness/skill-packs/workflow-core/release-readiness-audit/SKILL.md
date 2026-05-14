---
name: release-readiness-audit
description: Use before declaring a harness, adapter, profile, or skill-pack release complete.
---

# Release Readiness Audit

Use this skill before commit, push, or completion claims.

## Low-Reasoning Contract

Do not use "tests passed" as a proxy for completion. Map every prompt requirement to concrete evidence.

## Audit Steps

1. Restate the objective as concrete deliverables.
2. Build a prompt-to-artifact checklist.
3. Verify each artifact exists in the current worktree.
4. Verify tests or scripts cover the changed behavior.
5. Verify manifest entries install every new harness-owned file.
6. Verify README examples match real install commands.
7. Verify git state, commit, and remote synchronization when push is required.
8. Mark incomplete requirements as blocking.

## Output

```yaml
objective_deliverables:
  - ""
checklist:
  - requirement: ""
    evidence: ""
    status: PASS
missing_or_weak:
  - ""
verification:
  - command: ""
    result: ""
release_decision: PASS
```

