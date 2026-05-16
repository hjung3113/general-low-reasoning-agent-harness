---
roo_mode: tdd-code
opencode: true
title: UI TDD discipline
---

When changing visible UI behavior:

1. Phrase the red test as a user-visible behavior: "clicking the submit button
   with an empty form shows the inline error message", not "calls
   `validateForm`".
2. Use the project's existing test runner and rendering library. If the
   repository has no component test infrastructure yet, add it as a separate
   prerequisite task before continuing.
3. After implementing the smallest passing change, open the browser, exercise
   the golden path manually, and check at least one likely regression (e.g.
   resize to narrow viewport, tab through focus order).
4. A passing unit test alone is not "done" for UI work; a recorded browser
   verification note is.
