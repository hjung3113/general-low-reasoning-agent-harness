# OpenCode Plan

Use this command for `phase=plan` work only.

Preflight checklist:

- [ ] The current work is in `discuss` or `plan`.
- [ ] Durable planning memory has been read before `.scratch/phase-state.json`.
- [ ] The requested scope is clear enough to define allowed paths and verification.
- [ ] Any unresolved product or safety question is listed instead of silently defaulted.

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

Plan output checklist:

- [ ] `plan_id`
- [ ] acceptance criteria
- [ ] allowed paths
- [ ] blocked paths, or explicit reason there are none
- [ ] verification commands and required pass/fail signals
- [ ] rollback or stop condition
- [ ] adversarial review findings or explicit review request
- [ ] low-reasoning ambiguity risks
