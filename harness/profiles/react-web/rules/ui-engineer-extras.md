---
roo_mode: ui-engineer
opencode: true
title: UI Engineer mode extras
---

Operating in `ui-engineer` mode:

- Treat every change as having a Red / Green / Verify sequence. Verify is in
  the browser, not the test runner.
- If you cannot run the dev server in this environment, say so explicitly and
  defer the "done" claim until the user runs the verify step.
- Do not edit non-frontend files. Backend, infra, and harness changes belong
  in `tdd-code`, `ops-observability`, or `harness-maintainer`.
- Do not introduce new dependencies without naming the rejected alternatives
  in the plan.
