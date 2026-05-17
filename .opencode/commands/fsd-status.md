# fsd-status

Run exactly:

`harness status`

Then run:

`harness next --json`

If `.requires_human == true` in the JSON output, surface the value of `.command` to the user with the prefix "please run this in your terminal:" — do not execute it. Otherwise execute `.command` only if `.agent_safe == true`; else surface and stop.
