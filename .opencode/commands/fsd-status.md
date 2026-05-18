# fsd-status

Run exactly:

`harness check`

Then run:

`HARNESS_MACHINE=1 harness next`

If `.requires_user_approval == true`, surface `.next_user_prompt` to the user and stop. If `.next_command` is non-null, surface it; do not execute mutating lifecycle commands from this status command.

Respond with this template:

- phase:
- approved:
- plan_id:
- next_command:
- next_user_prompt:
- stop_reason:

If `HARNESS_MACHINE=1 harness next` refuses to produce JSON, run `python3 scripts/show_phase_status.py` once and summarize `phase`, `approved`, `plan_id`, `next_steps.read_next`, and warnings. Do not mutate lifecycle state from `/fsd-status`.
