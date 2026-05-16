# OpenCode Plan

Use this command for `phase=plan` work only.

Before proceeding, read every file under `.opencode/profile-rules/` in alphabetical order, if the directory exists. If it is missing or empty, skip silently.

Start with `python3 scripts/show_phase_status.py` when available. If it reports warnings, treat named files as minimum required reads before trusting the projection. If it is missing, fails, emits malformed output, or reports an unsupported contract version, use the legacy durable planning read order.

Preflight checklist:

- [ ] The current work is in `discuss` or `plan`.
- [ ] Status projection is trusted, or fallback planning memory has been read before `.scratch/phase-state.json`.
- [ ] The requested scope is clear enough to define allowed paths and verification.
- [ ] Any unresolved product or safety question is listed instead of silently defaulted.

1. Verify the current work is still in `discuss` or `plan`.
2. Use the status projection, or read durable planning memory before `.scratch/phase-state.json` during fallback.
3. Write or update the phase plan, allowed path candidates, verification candidates, and review checks.
4. Request execute approval instead of self-approving.

Do not advance the gate to `phase=execute` unless explicit approval provenance exists. Run `python3 scripts/harness.py phase approve` (which stamps `approved_by` from `git config user.email` and `approved_at` to nanosecond precision per ADR-003a Verb 2), then `python3 scripts/harness.py phase set execute`. The CLI refuses the transition unless these prerequisites are present in the live state:

- `plan_id`
- non-empty `allowed_paths`
- non-empty `verification`
- durable `state_path`, `plan_path`, and `checkpoint_path`

`approved_by` / `approved_at` are written by `python3 scripts/harness.py phase approve`; do NOT hand-write them.

Advance the lifecycle via the CLI; do NOT direct-edit `.scratch/phase-state.json`:

```text
python3 scripts/harness.py phase approve       # plan / execute: writes approved=true, approved_by, approved_at
python3 scripts/harness.py phase set execute   # plan → execute (requires approve first)
```

Plan output checklist:

- [ ] `plan_id`
- [ ] acceptance criteria
- [ ] allowed paths
- [ ] blocked paths, or explicit reason there are none
- [ ] verification commands and required pass/fail signals
- [ ] rollback or stop condition
- [ ] adversarial review findings or explicit review request
- [ ] low-reasoning ambiguity risks
