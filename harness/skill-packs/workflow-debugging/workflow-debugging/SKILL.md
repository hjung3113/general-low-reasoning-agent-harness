---
name: workflow-debugging
description: Use when something fails, regresses, throws, times out, or behaves differently than expected.
reads:
  - codebase.testing.commands
  - codebase.testing.repro
  - codebase.testing.known_failures
  - codebase.concerns.high_risk
  - codebase.concerns.flaky_tests
  - codebase.concerns.performance
---

# Workflow Debugging

Use this skill before proposing a fix for a failure.

## Low-Reasoning Contract

Do not guess the cause from symptoms. Reproduce, minimize, instrument, then fix.

Before reproducing: grep `.planning/codebase/CONCERNS.md` for `[codebase.concerns.flaky_tests]` and `[codebase.concerns.known_failures]` — if the failure matches a known flake, do not chase a root-cause fix. Grep `[codebase.testing.repro]` in TESTING.md for the project's standard repro setup.

## Stop Conditions

- the failure cannot be reproduced and no logs or command output exist
- the failing command is destructive or requires production credentials
- the observed failure contradicts the user's reported failure
- the fix would change unrelated behavior

## Workflow

1. Capture the exact failing command, input, or user path.
2. Reproduce once without code changes.
3. Minimize to the smallest failing case.
4. State one hypothesis and the observation that would disprove it.
5. Add temporary instrumentation only if needed.
6. Patch the cause, not the symptom.
7. Add or update a regression test.
8. Run the original failing path and the regression test.

## Output Contract

```yaml
failure: ""
repro_command: ""
minimal_case: ""
hypothesis: ""
disproof_check: ""
fix_files: []
regression_test: ""
verification: []
```

## Worked Example

If `check --target --adapter opencode` fails because Roo files are absent, reproduce the OpenCode-only target, confirm the checker incorrectly requires Roo ownership, patch adapter filtering, then add a regression test for OpenCode without `.roo/**`.

