---
description: Show current phase, halt diary, and next action via the harness state machine
argument-hint:
mode: ask
---

Run exactly:

`harness status`

Then run:

`harness next --json`

If `.requires_human == true` in the JSON output, surface the value of `.command` to the user with the prefix "please run this in your terminal:" — do not execute it. Otherwise execute `.command` only if it is read-only (`.agent_safe == true`); else surface and stop.
