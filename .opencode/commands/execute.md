# OpenCode Execute

Use this command only after the live gate is already approved.

Before editing, verify `.scratch/phase-state.json` has:

- `phase=execute`
- `approved=true`
- matching `plan_id`
- non-empty `allowed_paths`
- non-empty `verification`
- durable planning pointers
- approval provenance

Stop if requested work falls outside `allowed_paths` or if phase, checkpoint, plan, or allowed paths changed during the session.

Before committing, run:

```bash
python3 scripts/harness.py check --worktree
```

Run `python3 scripts/harness.py check --worktree` before committing.
