# ADR: Approver Provenance and `execution_mode` Promotion — 2026-05-17

## Status

Accepted. Bound to **phase 02c-phase-gate-hardening**, design baseline `docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md` (Round-7).

Locks the identity-binding, approval-gate, and `automation_mode → execution_mode` migration contract for v0.7.0. Implementation begins at S01 (state schema) after this ADR plus ADR-2 and ADR-3 are landed `Accepted`.

## Context

Phase E IDE dogfood (Roo Code adapter) revealed the haiku-class agent rocketed through `discuss → plan → execute → done` in a single turn. ADR-001 transition validation accepted the cascade because nothing prevented the agent from self-approving: the existing `automation_mode` field was unread by code, `--chain` / `--auto` flags referenced throughout skills/rules were doc-fiction (never wired), and `phase approve` had no human-presence proof beyond a `confirmation_kind` field the agent itself could populate.

Two failure modes recurred across seven adversarial review rounds:

1. **Agent self-approval**: any approval gate placed AFTER the code-executing phase (i.e. only at `execute → done`) is reachable by an agent that has already mutated the repo. The gate must attach at `plan → execute`.
2. **Provenance forgery**: `HARNESS_BY_TRUST`, env vars, gitconfig values, and `confirmation_kind` are all writable by an agent with shell + edit tools on the same user account. None of them is a human-presence proof on its own.

The design splits the problem into a CLI surface that the agent NEVER calls (`phase approve`, `phase reopen` — TTY-only) and a CLI surface that the agent MAY call but cannot use to forge approvals (`phase set`, `phase autopilot start|stop`, state-trust preflight). The `execution_mode` field replaces `automation_mode` to remove the dual-source-of-truth ambiguity that earlier rounds repeatedly tripped on.

## Decision

### D-1. `execution_mode` replaces `automation_mode`

`execution_mode ∈ {"manual", "phase_autopilot", "chain_autopilot"}` is the single canonical field for autopilot state. Writes to `execution_mode` are gated to two CLI verbs only: `harness phase autopilot start` and `harness phase autopilot stop`. `phase approve` never writes `execution_mode`.

Legacy `automation_mode` (v0.6.1 schema) is read once at CLI start if `execution_mode` is absent and coerced via §1.2 of the design doc; the migration emits a one-time `verb=migrate.state_v2` audit entry, then `automation_mode` is never read again. The field is removed entirely in v0.8.0.

### D-2. Approval attaches at `(plan → execute)`, not `(execute → done)`

`ADR-001` transition validator is extended (design doc §3.6):

- `(plan → execute)` under `execution_mode=manual`: requires `approved=true`, `approved_at >= plan_finalized_at` (the moment the plan was finalized with `verification` and `allowed_paths`), and presence of both arrays. Only after these checks pass does the CLI stamp `execute_attempt_started_at`.
- `(execute → done)` under `execution_mode=manual`: requires `approved=true` AND `approved_at >= execute_attempt_started_at` so a later `phase reopen --to plan` invalidates stale approvals.
- Any transition under `execution_mode != manual`: requires `state.autopilot_run_id` non-null, `state.autopilot_phase_slug` matching the phase, audit entry referenced by `state.autopilot_start_entry_hash` verifying under per-entry chain, and `state.cli_budgets_remaining[counter] > 0`.

The shift from `(execute → done)` gate to `(plan → execute)` gate is the primary "no code-executing phase without prior human approval" invariant.

### D-3. Human-presence proof — TTY gate + nonce default + credential fallback

`phase approve` and `phase reopen` are TTY-only verbs (design doc §3.1, §3.2). `os.isatty(stdin)` is the cheap first gate but is downgraded to "blocks non-PTY subprocesses only" because pexpect / `script -q` / `pty.spawn` can allocate a fresh PTY inside an agent process tree.

Real human proof requires one of:

- **Nonce default** (design doc §3.1.1, §12.6): `harness approve-nonce mint` writes an HMAC-signed nonce to `~/.harness/approval-nonces/<code>.json` (POSIX 0600 / Windows user ACL). `phase approve` consumes the newest valid nonce automatically. The HMAC is keyed by `~/.harness/secret.key` (256-bit, minted at install). The nonce records the minter's **controlling terminal device** (POSIX `st_dev`+`st_rdev` / Windows `GetConsoleWindow` HWND+process); the consumer rejects nonces minted in the same device.
- **OS credential fallback**: macOS Touch ID / `security`, Linux `pinentry`, Windows `CredUIPromptForWindowsCredentials`. Selected at install via `harness install --human-proof credential`. Recorded in `install-record.approval_proof`.

`--prompt-credential` flag on `phase approve` forces the credential path regardless of install default.

### D-4. Identity binding to `install-record.approvers[]`

`.harness/install-record.json` is the canonical identity source (design doc §6.1). Populated at install from `git config user.email` (auto-read, no prompt unless empty). Multi-user collaboration is explicitly out of scope; `approvers[]` is a single-entry array in v0.7 but uses array shape so future expansion does not require schema migration.

`phase approve` step 2 reads `git config user.email` only as a convenience discovery value. If the current value's sha256 does not match `install-record.git_user_email_at_install_sha256` AND `--by` is not explicitly passed, exit 6 `gitconfig_mutated_post_install`. This defends against agent-driven `git config --global user.email <approver>` rewrites.

`--by` is optional. `HARNESS_BY_TRUST` is NEVER consulted by `phase approve` — env identity is for `phase autopilot start` only (design doc §3.5.1).

### D-5. Override path

`--override-identity --reason <text>` bypasses the install-record identity match, emits `confirmation_kind=override_identity`, `by_source=override_identity`, sanitized `override_reason` to audit. Sanitization rules: max 1024 chars, control characters rejected, literal newlines replaced with `\n` token.

### D-6. Agent-approval rejection (`exit 8`)

`phase approve` invoked while `execution_mode != manual` exits 8 (`agents do not approve during autopilot`). This is the explicit hard-rule that an agent cannot launder approval through an active autopilot.

### D-7. `phase reopen` (NEW verb) — TTY-only

`harness phase reopen --to <discuss|plan> [--by <email>] --reason <text>` (design doc §3.2). TTY-gated identically to `phase approve`. Resets approval (`approved=false`, `approved_by=null`, `approved_at=null`). Resets phase to target. `verification` / `allowed_paths` are moved to draft slots (`state.draft_verification`, `state.draft_allowed_paths`); reaching `execute` again requires re-confirming them. Halts active autopilot, populates halt diary.

Replaces hand-editing of `phase-state.json` (which would otherwise corrupt the audit chain).

## Consequences

**Positive**:

- Agent cannot enter `execute` without prior human approval (gate moved to `plan → execute`).
- TTY+nonce+device-binding combination defeats every shell-only forgery path the seven review rounds raised.
- `execution_mode` single source of truth removes the dual-source ambiguity (`automation_mode` vs ad-hoc env reads).
- Mid-flow course corrections via `phase reopen` are first-class instead of corrupting the audit chain through hand edits.
- Adapter-side enforcement of `permissions.deny` for `~/.harness/**`, `git config user.email *`, and `~/.harness/secret.key` becomes a checkable contract (`install-record.approval_proof=supported`).

**Negative**:

- Adapters that do not support permission DSL deny-globs (or that allow desktop automation) are marked `approval_proof=unsupported` and force `--prompt-credential` use. Roo and OpenCode fit the contract today; future adapters require explicit assessment.
- One-time migration cost for v0.6.1 installs (state schema bump, `migrate.state_v2` audit entry).
- TTY-only constraint on `phase approve` and `phase reopen` means IDE shells that pipe stdin must explicitly route the user to an OS terminal. The slash bodies (design doc §4.3a/b, §4.4a/b, §12.11) document this routing.
- Single-user / single-machine assumption is explicit; multi-user collaboration is deferred to a future phase with its own ADR.

## Alternatives considered

- **`--yes` flag** (rejected, Round-1): an agent will mechanically learn to pass it; no defense holds.
- **Interactive TTY prompt** (rejected, Round-1, Round-3): IDE shells capture stdin; agent fills the prompt.
- **`HARNESS_HUMAN=1` env gate** (rejected, Round-3): env is forgeable by any agent shell.
- **`HARNESS_BY_TRUST` as identity authority for `phase approve`** (rejected, Round-4): conflates CI bot identity with human approver and gives the agent a forgeable path. Restricted to `phase autopilot start` only with CI proof.
- **Per-entry signed audit tip stored in repo** (rejected, Round-4): a repo-local attacker rewrites both the entry and the signature. Out-of-repo anchor at `~/.harness/audit-tip/` (design doc §12.1, ADR-2) is the chosen alternative.

## Cross-references

- Design doc: `docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md` §0, §1.1, §1.2, §3.1, §3.1.1, §3.2, §3.6, §6.1, §12.6.
- ADR-2 `2026-05-17-audit-canonicalization-locking-and-state-trust.md`: chain, lock, transaction protocol that the audit entries written here ride on.
- ADR-3 `2026-05-17-autopilot-guards-and-manual-handoff.md`: `phase autopilot start|stop` verbs that mutate `execution_mode`.
- Slice S01 (state schema), S02 (approve provenance), S03 (stale approval validator), S04 (reopen), S05 (override-identity).


---

## Supersession Notice (2026-05-19)

This ADR's threat model and mitigations remain in force for the **release path** (release verb, signed tags, OIDC, release_trust). The **phase.approve scope** is superseded by `2026-05-19-phase-approve-speed-bump.md` (v0.9.0): the HMAC-nonce / audience / TTL / consumer-tty defense is replaced by an interactive `[y/N]` workflow speed bump. See the v0.9.0 ADR for rationale.
