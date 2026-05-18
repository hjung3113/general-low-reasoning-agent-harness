---
description: Show current phase, halt diary, and next action via the harness state machine
argument-hint:
mode: ask
---

Run exactly:

`harness check`

Then run:

`HARNESS_MACHINE=1 harness next`

If `.requires_user_approval == true`, surface `.next_user_prompt` to the user and stop. If `.next_command` is non-null, surface it; do not execute mutating lifecycle commands from this status command.
