# OpenCode Execute

Use this command only after the live gate is already approved.

Before proceeding, read every file under `.opencode/profile-rules/` in alphabetical order, if the directory exists. If it is missing or empty, skip silently.

Start with `python3 scripts/show_phase_status.py` when available. If it reports warnings, treat named files as minimum required reads before trusting the projection. If it is missing, fails, emits malformed output, or reports an unsupported contract version, use the legacy durable planning read order.

Preflight checklist:

- [ ] `python3 scripts/harness.py check` exits 0 with `phase=execute`, `approved=true`, and the expected `plan_id`.
- [ ] `allowed_paths` is non-empty.
- [ ] `verification` is non-empty.
- [ ] Requested edits are inside `allowed_paths`.
- [ ] Active checkpoint, plan, and allowed paths have not drifted since approval.

Before editing, verify via `python3 scripts/harness.py check` that the live gate has:

- `phase=execute`
- `approved=true`
- matching `plan_id`
- non-empty `allowed_paths`
- non-empty `verification`
- durable planning pointers
- approval provenance (set by `python3 scripts/harness.py phase approve`)

Stop if requested work falls outside `allowed_paths` or if phase, checkpoint, plan, or allowed paths changed during the session.

Before committing, run:

```bash
python3 scripts/harness.py check --worktree
```

Run `python3 scripts/harness.py check --worktree` before committing.

Advance the lifecycle via the CLI; do NOT direct-edit `.scratch/phase-state.json`:

```text
harness phase set done                               # long form: python3 scripts/harness.py phase set done; execute → done (CLI preserves approved fields per G2-C)
```

Execution output checklist:

- [ ] changed paths
- [ ] verification commands run, with exit status
- [ ] failed checks or skipped checks with reason
- [ ] residual risks
- [ ] phase-state updates made via `python3 scripts/harness.py phase set/approve`, if any
