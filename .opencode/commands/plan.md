# OpenCode Plan

Use this command for `phase=plan` work only.

1. Verify the current work is still in `discuss` or `plan`.
2. Read durable planning memory before `.scratch/phase-state.json`.
3. Write or update the phase plan, allowed path candidates, verification candidates, and review checks.
4. Request execute approval instead of self-approving.

Do not write `phase=execute` unless explicit approval provenance exists:

- `plan_id`
- `approved_by`
- `approved_at`
- non-empty `allowed_paths`
- non-empty `verification`
- durable `state_path`, `plan_path`, and `checkpoint_path`

