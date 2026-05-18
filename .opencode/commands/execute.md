# OpenCode Execute

Use this command only after the live gate is already approved.

Before proceeding, read every file under `.opencode/profile-rules/` in alphabetical order, if the directory exists. If it is missing or empty, skip silently.

Start with `harness check` and `harness next` when available. If `check` reports warnings, treat named files as minimum required reads before trusting the projection. If either command is missing, fails, emits malformed output, or reports an unsupported contract version, use the legacy durable planning read order. Use `HARNESS_MACHINE=1 harness next` when structured adapter output is needed.

Preflight checklist:

- [ ] `harness check` exits 0 with `phase=execute`, `approved=true`, and the expected `plan_id`.
- [ ] `allowed_paths` is non-empty.
- [ ] `verification` is non-empty.
- [ ] Requested edits are inside `allowed_paths`.
- [ ] Active checkpoint, plan, and allowed paths have not drifted since approval.

Before editing, verify via `harness check` that the live gate has:

- `phase=execute`
- `approved=true`
- matching `plan_id`
- non-empty `allowed_paths`
- non-empty `verification`
- durable planning pointers
- approval provenance recorded by the approval path

Stop if requested work falls outside `allowed_paths` or if phase, checkpoint, plan, or allowed paths changed during the session.

## Pre-commit (REQUIRED — T1-1 scope enforcement)

1. Run: `harness check`.
2. If exit code is 4 (scope violation): the command names the violating
   files and prints a remediation block. Either
   (a) `git restore --staged <file>` and exclude it from the commit, OR
   (b) stop and ask the user to return to planning, expand `allowed_paths`,
       approve again, and re-enter execute.
   Do NOT bypass with `git commit --no-verify`.
3. If exit code is 0: proceed with `git commit`.

The same exit-4 contract is enforced by the pre-commit hook installable
via `harness install --pre-commit`; running the check
yourself here lets you see the diagnostic before the hook fires.

Finish only through the high-level CLI; do NOT direct-edit `.scratch/phase-state.json` and do NOT run low-level phase commands from this adapter:

```text
harness run
```

Execution output checklist:

- [ ] changed paths
- [ ] verification commands run, with exit status
- [ ] failed checks or skipped checks with reason
- [ ] residual risks
- [ ] phase-state updates made via `harness run`, if any
