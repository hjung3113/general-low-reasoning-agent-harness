---
name: workflow-tdd
description: Use for behavior changes where tests can define the expected result before implementation.
reads:
  - codebase.testing.frameworks
  - codebase.testing.commands
  - codebase.testing.scopes
  - codebase.testing.fixtures
  - codebase.testing.known_failures
---

# Workflow TDD

Use this skill for bug fixes and features with testable behavior.

## Low-Reasoning Contract

Do not implement first. A low-reasoning model needs a visible red/green trail.

Before starting: grep `.planning/codebase/TESTING.md` for `[codebase.testing.commands]` — that anchor is the contract for which test command to run. If absent, run `harness recon` first.

## Activation Evidence

- user asks for a feature or bug fix
- existing test framework is present
- behavior can be observed through unit, integration, smoke, or snapshot tests

## Stop Conditions

- no test command is known
- behavior is not specified enough to assert
- test requires unavailable external services
- approved phase gate does not allow test or source paths

## Workflow

1. State the smallest behavior being changed.
2. Grep `.planning/codebase/TESTING.md` for `[codebase.testing.commands]`. That is the test command. If empty, find the nearest existing test style and command yourself, then update the anchor.
3. Add or update one focused failing test.
4. Run the focused test and record the failing signal.
5. Implement the smallest change.
6. Run focused test, then broader verification from the plan.
7. Refactor only after green.

## Output Contract

```yaml
behavior: ""
test_file: ""
focused_command: ""
red_evidence: ""
implementation_files: []
green_evidence: ""
broader_verification: []
```

## Worked Example

For an installer flag bug, add a unit test in `scripts/test_harness.py`, run that test and capture the failure, patch `scripts/harness.py`, then run the focused test plus `python3 -m unittest scripts/test_harness.py`.

