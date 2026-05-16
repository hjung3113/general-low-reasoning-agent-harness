# General Low-Reasoning Agent Harness Protocol

## Purpose

This protocol lets weak or low-reasoning agents work safely across many repositories without binding the workflow to one stack, database, editor, or client.

The invariant is:

```text
one canonical planning memory
one live gate
many adapters
composable skill plugins
optional project profiles and packs
```

## Core Protocol

The core protocol is client-neutral and stack-neutral.

Agents must follow:

1. `discuss`
2. `plan`
3. `execute`
4. `done`

Fresh sessions must start with the status projection when it is installed:

Start with `python3 scripts/show_phase_status.py` when available. If it reports warnings, treat named files as minimum required reads before trusting the projection. If it is missing, fails, emits malformed output, or reports an unsupported contract version, use the legacy durable planning read order.

`.planning/**` explains the project. `.scratch/phase-state.json` only approves or blocks the current work.

Resolve active phase docs deterministically:

1. Prefer explicit pointers in `.scratch/phase-state.json`: `checkpoint_path`, `plan_path`, and `state_path`.
2. If pointers are missing during `discuss`, choose the highest numbered directory under `.planning/phases/**`.
3. Within a phase directory, read matching files in this order: `*-CONTEXT.md`, `*-PLAN.md`, `*-REVIEW.md`, `*-VERIFICATION.md`, `*-SUMMARY.md`, `*-CHECKPOINTS.md`.
4. If an expected file is absent, record that it is absent. Do not infer hidden requirements from a missing file.

## Phase Rules

### Discuss

Allowed:

- inspect repository evidence
- ask one concrete question at a time
- record alignment notes when requested
- propose active skills and profiles

Forbidden:

- application-code edits
- execute approval
- unconfirmed stack-specific commands

Exit criteria:

- confirmed facts, inferred facts, rejected assumptions, open questions, and recommended next phase are recorded.

### Plan

Allowed:

- write phase plans
- define allowed path candidates
- define verification commands
- run adversarial review

Forbidden:

- application-code edits
- self-approval for execute

Exit criteria:

- `plan_id`, allowed paths, blocked paths or omission reason, verification, review checks, and approval request are ready.

### Execute

Allowed:

- edit only approved paths
- run approved verification
- update evidence

Forbidden:

- edits outside `allowed_paths`
- changing phase scope silently
- continuing after phase-gate drift

Required live gate fields:

- `phase=execute`
- `approved=true`
- `plan_id`
- `allowed_paths`
- `verification`
- `state_path`
- `plan_path`
- `checkpoint_path`
- `approved_by`
- `approved_at`

### Done

Allowed:

- summarize completed work
- record verification evidence
- record residual risk and follow-ups

Forbidden:

- starting new implementation work

## Adapter Contract

Each adapter must define:

- installed files
- command or mode names
- phase mapping
- restart read order
- execute approval checks
- allowed-path behavior
- verification recording
- stale-file and retired-file handling

Adapters must not own project truth. Roo, OpenCode, Codex, or future clients all read the same `.planning/**` and `.scratch/phase-state.json`.

## OpenCode Compatibility

OpenCode is a first-class adapter target.

Valid target shapes:

- core only
- core + Roo
- core + OpenCode
- core + Roo + OpenCode

`check --target` validates core plus installed adapters. `check --target --adapter opencode` validates OpenCode without requiring Roo files. Missing uninstalled Roo files are not findings.

OpenCode intentionally ships phase primitives: `discuss`, `plan`, `execute`, and `done`. Workflow specialization comes from installed `.agents/skills/**` packs, not from duplicating every Roo slash command under `.opencode/commands/**`.

## Skill Plugins

Skills are composable plugins selected per request, not hard-coded tech-stack presets.

The default `workflow-core` pack includes:

- `repository-evidence-research`
- `skill-plugin-composition`
- `ecosystem-skill-research`
- `verification-contract`
- `risk-review`
- `multi-agent-review`
- `release-readiness-audit`
- `data-workflow`
- `integration-boundary`

Additional shipped tech packs:

- `tech-python`
- `tech-react`
- `tech-typescript`
- `tech-tailwind`
- `tech-csharp`
- `tech-mssql`
- `tech-postgresql`

Additional shipped workflow packs:

- `workflow-data-analysis`
- `workflow-data-processing`
- `workflow-etl`
- `workflow-db-context`
- `workflow-web-development`
- `workflow-tdd`
- `workflow-debugging`
- `workflow-code-review`
- `workflow-skill-authoring`
- `workflow-security-review`

Selection rules:

- use repository evidence first
- activate the smallest useful skill set
- record active skills and rejected skills
- do not use inactive profile commands
- create project-specific skills only after constraints are known

## Specialization By Composition

Specialized harness behavior must be reproduced through explicit profile and pack composition, not through core defaults.

Example: a C#/.NET + MSSQL + ETL target uses:

```bash
python3 scripts/harness.py init \
  --target /path/to/dotnet-etl-project \
  --adapters roo,opencode \
  --profiles generic,dotnet-etl-mssql \
  --packs workflow-core,tech-csharp,tech-mssql,workflow-etl,workflow-db-context
```

This composition must install:

- `docs/profiles/dotnet-etl-mssql.md`
- `.agents/skills/tech-csharp/SKILL.md`
- `.agents/skills/tech-mssql/SKILL.md`
- `.agents/skills/workflow-etl/SKILL.md`
- `.agents/skills/workflow-db-context/SKILL.md`
- verification and risk-review skills from `workflow-core`

It must carry guardrails for .NET version confirmation, SQL Server persistence verification, DB context gating, row-by-row ETL write prohibition, transaction boundaries, restart/idempotency/replay, and `needs-db-context`.

## Profiles

Profiles describe confirmed project facts and defaults. They do not change the phase lifecycle.

Unknown project shape means generic profile only.

Shipped profiles:

- `generic`
- `dotnet-etl-mssql`

Profile records should include:

- `selected_by`
- `evidence_paths`
- `confirmed_by`
- `confidence`
- `inactive_profiles_rejected`
- `open_questions`

## Manifest And Upgrade

Manifest entries must identify ownership:

- core
- adapter
- profile
- pack
- project

The installer and upgrader must support selected adapters and packs. Retired files are removed only when unmodified; modified retired files become conflicts.

## Release Gate

Before pushing a generalized harness release:

1. Run unit tests.
2. Run source `check`.
3. Run source `check --worktree` before commit.
4. Init and check core-only target.
5. Init and check OpenCode-only target.
6. Init and check Roo target.
7. Init and check combined Roo + OpenCode target.
8. Run the installed target smoke suite in each release-matrix target.
9. Init and check target with default `workflow-core` skill pack.
10. Confirm the README and clean skeleton are stack-neutral.
11. Confirm stack-specific docs are adapter, profile, pack, or example material only.
12. Record command results, target paths, timestamp, adversarial review result, commit, and pushed branch in the phase verification ledger.

## CLI Verbs

The phase lifecycle CLI verbs are defined by ADR-003a Artifact 1 and implemented in `scripts/lib/phase_cli.py`.

### `harness phase set <phase>`

- Positional `phase` ∈ {`discuss`, `plan`, `execute`, `done`}.
- Optional flags: `--plan-id <id>`, `--summary <text>`, `--reset-approval`, `--stdin-json`.
- Stdin: when `--stdin-json` is passed, reads a JSON object whose allowlisted keys are written to the state file.
- Stdout: JSON object `{ok, verb, previous_phase, phase, state_path, audit_entry_index, updated_at, updated_by}`.
- Stderr: human-readable diagnostics on failure.

### `harness phase approve`

- Optional flags: `--by <identifier>`, `--at <ISO-8601 nanos>`, `--stdin-json`.
- Stdout: JSON object `{ok, verb, phase, approved, approved_by, approved_at, state_path, audit_entry_index, updated_at, updated_by}`.

### `harness session unlock`

- Optional flags: `--force`, `--print`.
- Default behaviour: refuse if the recorded PID is alive; remove if dead or if host has rebooted (Linux `boot_id` comparison).

## Exit Codes

| Code | Name | Meaning |
|---|---|---|
| 0 | `EXIT_OK` | success |
| 1 | `EXIT_OPERATIONAL` | I/O / permissions / generic write failure |
| 2 | `EXIT_INVALID_TRANSITION` | violates ADR-001 transition table |
| 3 | `EXIT_SESSION_LOCKED` | `.harness/session.lock` held |
| 4 | `EXIT_SCOPE_VIOLATION` | write outside `allowed_paths` (T1-1) |
| 5 | `EXIT_UNPARSEABLE_JSON` | state file or stdin failed `json.loads` |
| 6 | `EXIT_WRONG_PHASE_FOR_VERB` | verb invoked in a phase that does not accept it |
| 7 | `EXIT_STALE_UNCERTAIN` | `session unlock` staleness uncertain |
| 8 | `EXIT_TIMESTAMP_OUT_OF_RANGE` | `--at` value not within 24h of current UTC |

Constants live in `scripts/lib/exitcodes.py`.

## Audit Log Format

Path: `.harness/audit.log`. One JSON line per lifecycle write, encoded with `json.dumps(..., separators=(",",":"), sort_keys=True)`.

```json
{"index":1,"verb":"phase.set","args":{"phase":"discuss"},"before_sha256":"...","after_sha256":"...","at":"2026-05-16T19:30:45.123456789Z","by":"user@example"}
```

- Each line is ≤512 bytes (PIPE_BUF-safe). Oversize `args` payloads are replaced with `{"truncated": true}`; the full record is archived to `.harness/audit.overflow/<index>.json`.
- Rotation triggers at 10 MiB OR 10 000 entries (whichever first). Rotated files: `audit.log.1` … `audit.log.5` (keeping the last five).
- Append uses `O_WRONLY|O_APPEND|O_CREAT|O_NOFOLLOW|O_CLOEXEC` + `fcntl.flock(LOCK_EX)`.
- Allowed writers: `scripts/lib/audit.py` only.

## Session Lockfile

Path: `.harness/session.lock`. Payload (JSON object):

```json
{"pid":12345,"hostname":"laptop.local","started_at_utc":"2026-05-16T19:30:45.123456789Z","harness_version":"0.7.0","boot_id":null}
```

- Acquisition: `O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC` + `fcntl.flock(LOCK_EX|LOCK_NB)`.
- Release: explicit unlink on context exit + `atexit` registration + SIGINT/SIGTERM handlers.
- Recovery: `harness session unlock` checks `os.kill(pid, 0)` and (on Linux) `/proc/sys/kernel/random/boot_id`; refuses live PIDs unless `--force`.

## Field Ownership

Per ADR-003b Artifact 3 the `.scratch/phase-state.json` fields fall into three buckets:

| Bucket | Fields | Writers |
|---|---|---|
| `cli` | `phase`, `approved`, `approved_by`, `approved_at`, `updated_at`, `updated_by` | `harness phase set`, `harness phase approve` |
| `cli-opt-in` | `plan_id`, `summary`, plus stdin-allowlisted `next_action`, `current_checkpoint`, `checkpoint_path`, `state_path`, `plan_path` | same CLI verbs when explicit flag/stdin is passed |
| `user` | `verification`, `review`, `acceptance_criteria`, `allowed_paths`, `blocked_paths`, `automation_mode`, `auto_selected`, `notes` | editor / planning agent only — CLI verbs MUST NOT modify |

## Drift Warning

`harness check` compares the live `.scratch/phase-state.json` SHA-256 against the last audit entry's `after_sha256`. On mismatch a stderr warning is emitted (exit code unchanged):

```
warning: .scratch/phase-state.json sha256 (<actual>) does not match the last audit entry's after_sha256 (<expected>) at index <N>. Drift detected. To restore audit baseline, re-run the last CLI verb that should have produced this state (typically 'harness phase set <phase>' or 'harness phase approve'). Manual edits are not currently tracked.
```

First-write / empty-log cases are suppressed.

## Verification Allowlist

This anchor is owned by T0-4. See the `verification` field documentation under "Field Ownership". The seven allowed verb prefixes are: `python3 `, `git `, `jq `, `npx `, `pytest `, `harness `, `make `.

## Scope Enforcement

`python3 scripts/harness.py check --worktree` is the single enforcement primitive for `allowed_paths` / `blocked_paths` (anchor: `#scope-enforcement`, owning slice: T1-1).

Exit codes (consume from `scripts/lib/exitcodes.py`; no numeric literals in source):

| Code | Meaning |
|---|---|
| `0` | clean tree, OR scope check not applicable in the current phase (e.g. `phase=plan`). |
| `4` | scope violation — at least one worktree path matched `blocked_paths` or fell outside `allowed_paths`. Names every violating file. |
| `1` | argparse / invocation error / catastrophic failure. |

Pre-commit hook lifecycle:

- Install: `python3 scripts/harness.py install --pre-commit --target <path>`. Writes `<target>/.git/hooks/pre-commit` (or merges into an existing user-authored hook via the `# HARNESS:scope-check-begin` / `# HARNESS:scope-check-end` marker envelope so the install is idempotent and composes with user content).
- Uninstall: `python3 scripts/harness.py uninstall --pre-commit --target <path>`. Removes the marker envelope; deletes the hook file when nothing else remains. Manual fallback: `rm <target>/.git/hooks/pre-commit` (the installer never touches `git config core.hooksPath`).
- Hook body: shells out to `python3 scripts/harness.py check --worktree` from the repo root resolved via `git rev-parse --show-toplevel`. When `scripts/harness.py` or `.scratch/phase-state.json` are absent (e.g. harness not installed in the target), the hook emits a non-fatal warning to stderr and exits 0 — never silently passes through without a visible reason.

Failure-message contract (printed to stderr by the library on exit 4):

```
harness: scope violation (exit 4)
Files outside allowed_paths:
  <path1>
  <path2>
Remediation:
  - Move the change out of the commit, OR
  - Add the path/glob to .scratch/phase-state.json `allowed_paths`, OR
  - Remove a matching entry from `blocked_paths`.
See docs/protocol-spec.md#scope-enforcement.
```

Adapter symmetry (spec §10.4): both `.opencode/commands/execute.md` and `.roo/commands/phase-execute.md` MUST instruct the agent to run `python3 scripts/harness.py check --worktree` as a numbered pre-commit step, AND MUST NOT instruct `git commit --no-verify` to bypass exit 4. A regression in `scripts/test_hooks.py::AdapterCommandFileMirrorTests` enforces both rules.

Cross-reference: ADR-003a Artifact 1 exit-code table (this slice claims row "4 — `EXIT_SCOPE_VIOLATION`", lifting the original "schema-version refusal" reservation; see ledger entry L16 in CHANGELOG and the ADR amendment commit `docs(adr): assign exit code 4 to SCOPE_VIOLATION`).
