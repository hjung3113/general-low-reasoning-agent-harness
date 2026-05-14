---
name: verification-contract
description: Use when turning a plan into concrete verification commands, evidence, and done criteria.
---

# Verification Contract

Use this skill before execute approval.

## Workflow

1. Identify the behavior, document, or workflow that must be proven.
2. Choose verification commands that exist in the target repository.
3. Define expected evidence and failure signals.
4. Attach verification to the phase plan and live gate.
5. Reject vague verification such as "test manually" unless the plan explains the exact observable result.

## Execute Gate Requirements

The live gate must include:

- non-empty `verification`
- expected evidence location
- allowed paths
- blocker conditions
- owner of follow-up verification

