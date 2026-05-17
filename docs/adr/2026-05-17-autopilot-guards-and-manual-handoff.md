# ADR: Autopilot Guards and Model B Manual Handoff — 2026-05-17

## Status

Accepted. Bound to **phase 02c-phase-gate-hardening**, design baseline `docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md` (Round-7).

Locks the slash-command-to-CLI wrapper contract, the capability-neutral budget mechanism, the best-effort filesystem fence and network deny-list, the CI provenance predicate, and the Model B "halt → manual handoff" failure model.

## Context

`automation_mode=chain` / `--chain` / `--auto` flags were referenced throughout skill and rule text but no CLI consumed them. `/fsd-phase` and `/fsd-chain-phase` slash commands had no mutation path other than the agent direct-editing `.scratch/phase-state.json` — which would corrupt the audit chain.

The first three review rounds tried to scope autopilot as a strong contract: checkpoint, `chain --resume`, `chain --abort`, `last_good_commit_sha`, commit-per-phase auto-creation. Round-5 user review concluded this was wrong for a low-reasoning agent model:

- Strong auto-recovery hides failure modes from the user.
- The checkpoint+resume state machine doubles the surface area an agent can corrupt.
- The "agent should never approve" core principle is in tension with auto-recovery: any auto-resume is implicitly a self-approval of the prior state.

Model B pivot: autopilot **halt = manual handoff**, not failure to auto-recover from. The harness records a "halt diary" and surrenders control to the user via `harness status` / `harness next`. Cheaper to implement, easier to explain to weak agents, and a much smaller attack surface.

Round-4 and Round-6 surfaced the second half of the problem: the harness CLI is the ONLY enforcement point. Slash commands are Markdown text consumed by the IDE; raw adapter tool calls (Bash, Edit, Write) do NOT route through the harness. Budgets and fences are therefore best-effort guards on CLI-mediated operations, not containment. Section §5 of the design doc was retitled accordingly.

Round-5 added the CI provenance predicate: env vars alone are forgeable by an agent shell, so non-TTY autopilot start requires cryptographic CI attestation (OIDC/JWT signature + claim match), not just `HARNESS_AUTOMATION=chain`.

## Decision

### D-1. Slash commands are prompts, not shells

Adapter Markdown files (`.{roo,opencode}/commands/fsd-run-{phase,all}.md`, `.{roo,opencode}/commands/fsd-status.md`) instruct the agent to invoke a cross-platform CLI wrapper. They do NOT contain POSIX shell snippets, `set -eu`, `sed`, `grep`, command substitution, or direct `harness phase autopilot start` calls.

Exact bodies pinned at design doc §4.3a/§4.3b (`/fsd-run-phase` Roo / OpenCode), §4.4a/§4.4b (`/fsd-run-all`), §12.11 (`/fsd-status`). Grep-gate forbids:

- `--allow-network` in any slash body (must come from a human at invocation time).
- Alternative launchers (`python3 scripts/harness.py`, `py scripts/harness.py`, `scripts/show_phase_status.py`).
- Shell-script constructs.

OpenCode does not support positional argument substitution (empirically verified). OpenCode bodies use no-arg form only; trailing tokens are ignored. Roo bodies use `$ARGUMENTS` for single-token positional slug; multi-token rejected with exit 2.

### D-2. Wrapper CLI contract — `harness fsd-run-phase` / `harness fsd-run-all`

Defined in design doc §12.3. Both wrappers own slug parsing, `next-pending` resolution, fresh-state init (`harness init --quiet`), and the call into `harness phase autopilot start`. Slash bodies invoke `harness fsd-run-phase` or `harness fsd-run-all`; nothing else.

Exit codes: 0 (started or no-op), 2 (multi-arg / regex miss), 15 (autopilot already active), 16 (chain mode dirty tree). `--json` form for structured output.

### D-3. `phase autopilot start | stop` — `execution_mode` mutation

`harness phase autopilot start --phase <slug> [--mode phase|chain] [--budget shell_invocations=N] [--allow-network]` (design doc §3.5).

Atomically: validates roadmap, mints `autopilot_run_id` (uuid4), records `autopilot_mode`, `autopilot_phase_slug`, `autopilot_start_entry_hash`, `cli_budgets_remaining`, `autopilot_allow_network`, sets `execution_mode`. Audits `verb=phase.autopilot.start` with mode/phase_slug/budgets/allow_network/authorization_source/ci_signature/ci_oidc_verified/ci_oidc_claims/bot_identity.

`stop` clears all identity fields, sets `execution_mode=manual`, audits `verb=phase.autopilot.stop`. Idempotent.

**No idempotent re-entry** (Round-5 Model B): `start` while `execution_mode != manual` exits 15 `autopilot_already_active`. Re-entry is always an explicit human decision after reading status.

### D-4. CI provenance predicate (non-TTY authorization)

Design doc §3.5.1 + §12.4. Non-TTY `phase autopilot start` requires:

```
if stdin_is_tty() and human_proof_satisfied:
    authorization_source = "cli_tty_human"
elif ci_predicate_satisfied:
    authorization_source = "ci_<provider>"
else:
    exit 6 non_tty_authorization_unverified
```

`ci_predicate_satisfied()`:

1. `HARNESS_AUTOMATION ∈ {"phase","chain"}` present.
2. `HARNESS_BY_TRUST` present, non-empty, RFC 5321 + NFC + ASCII local-part validated, NOT equal to any `install-record.approvers[]` entry.
3. Exactly one provider signature in allowlist validates.
4. Provider attestation cryptographically verified: fetch/validate OIDC, match claims to repo/ref/sha/run id.

**Provider allowlist (v0.7)**: `github_actions` (OIDC), `gitlab_ci` (`CI_JOB_JWT_V2` only — V1 rejected), `buildkite` (OIDC). Per-provider claim-pinning table at design doc §12.4 specifies exact `iss`, required `aud` (`harness:install:<install_id>`), `sub` regex anchored, JWKS URL, `RS256` allowlist, ±60s skew, `jti` replay rejection. `circleci` and `jenkins` are deliberately absent until they have explicit proof contracts.

`--allow-network` follows the same predicate independently. `HARNESS_ALLOW_NETWORK=1` alone is insufficient.

### D-5. Capability-neutral budgets

`cli_budgets_remaining` keys (design doc §1.1): `shell_invocations`, `file_mutation_ops`, `wall_seconds`. Capability-neutral; adapter-specific tool names (`Bash`, `Edit`, `Write`) are mapped to these capabilities only in adapter contracts. Core state never stores adapter tool names.

**Enforcement scope (Round-4 honest)**:

- **CLI-invoked subprocesses**: guarded reliably (the `harness ...` call sits in the path).
- **`autopilot_guard.py` PATH-prepend shim** (POSIX) / `autopilot_guard.ps1` (Windows): wraps deny-listed verbs at the shell level. Bypassable by absolute paths and language runtimes; treat as best-effort audit guard.
- **Adapter raw `Edit`/`Write`/`Bash` tool calls**: NOT covered. Adapter pre-tool hooks (`pre_tool_call`) are out of scope (§10) until upstream APIs exist.

`wall_seconds` uses `time.monotonic()` polled at every harness CLI invocation in autopilot mode (no `SIGALRM` — POSIX-only and signal-unsafe).

### D-6. Filesystem fence (best-effort, harness-managed writes only)

Design doc §5.1, §12.2. Every file mutation operation performed by the `harness` CLI MUST resolve to a real path under `cwd` and satisfy `allowed_paths`. Rejection audits `verb=autopilot.fence.deny`.

**Safe-open semantics** (design doc §12.2 / S10b):

- POSIX: `os.open(path, O_NOFOLLOW | O_CLOEXEC, dir_fd=parent_fd)` where `parent_fd` is walked component-by-component from a known anchor under `cwd`. Symlinks → `ELOOP` → exit 4.
- Windows: `CreateFileW(..., FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS)` + `GetFinalPathNameByHandle(VOLUME_NAME_DOS)`. Junctions / reparse points → exit 4 `path_reparse_refused`.

ToCToU: all subsequent reads/writes via the handle, never via re-`CreateFile` of the path.

Raw adapter tool calls are not covered.

### D-7. Network deny-list (best-effort audit guard)

Design doc §5.2. In autopilot modes, the CLI sets `HARNESS_AUTOPILOT_NETWORK=deny`.

POSIX shim refuses: `curl`, `wget`, `nc`, `ssh`, `scp`, `rsync`, `git push|pull|fetch|clone|remote update|submodule update --remote`, `gh`, `glab`.

Windows: PATH-prepend `curl.cmd`, `gh.cmd`, `git.cmd` wrappers. PowerShell profile hook for `Invoke-WebRequest` / `Start-Process curl`. `network_guard_posture` audit field records the degraded posture.

**Section retitled "best-effort audit guards"** (Round-3): not containment. Real isolation requires `--isolation=container` (out of scope §10). Slash-command Markdown files MUST NOT contain `--allow-network` (grep-gate enforced).

### D-8. Model B halt → manual handoff

On any halt (ADR-001 reject, verification non-zero, allowed_paths violation, budget exhausted, network deny breach, manual stop, crash recovery, audit-chain break, agent-approve attempt during autopilot):

1. Under state lock + transaction protocol (ADR-2):
   - Set `execution_mode = manual`.
   - Populate `last_halt` halt diary: `{run_id, mode, phase_slug, last_successful_transition, halt_reason, halt_at_iso, suggested_next_command, suggested_next_command_requires_human, acknowledged_at: null}`.
   - Clear `autopilot_*` identity fields.
   - Audit `verb=phase.autopilot.halt` with all halt-diary fields.
2. Print halt summary to stderr; `harness next` and `harness status` surface the diary.

**Halt diary is read-only documentation, not a resumable checkpoint.** Cleared (moved to `last_halt_history[]`, capped at 5) when user starts a new autopilot run, runs `harness halt-diary clear`, or runs `harness phase reopen`. `acknowledged_at` is stamped by user-initiated mutating verbs; `phase set done` refuses (exit 2 `last_halt_unacknowledged`) while `acknowledged_at` is null (design doc §12.12).

**No `chain --resume`, no `chain --abort`, no `last_good_commit_sha`, no commit-per-phase auto-creation.** ADR-001 does NOT gain a `failed` substate.

### D-9. `harness status` / `harness next` / `Fix:` error standard

UX surface contract (design doc §3.9):

- `harness status` — read-only snapshot (consistent-snapshot read protocol, ADR-2 D-8). Safe for agent/IDE.
- `harness next` — human-readable next action. `--shell` form prints stdout only for agent-safe commands. `--json` form always prints `{requires_human, agent_safe, command, reason}`.
- `Fix: <command>` line — every non-zero exit emits a `Fix:` line to stderr. Verified by `scripts/smoke/verify_fix_lines.py` (S16 release-blocker).
- `/fsd-status` slash body (design doc §12.11) — runs `harness status` + `harness next --json`, routes `requires_human=true` to user, executes `agent_safe=true` only.

The pair `status` + `next` covers 100% of "what now?" queries; no additional CLI verbs added for UX.

## Consequences

**Positive**:

- Slash commands are portable across OS / shell because runnable behavior lives in the CLI wrapper, not in the Markdown body.
- Capability-neutral budgets keep the core client-agnostic; adapter mapping is local contract.
- Model B halt → manual handoff is small (one `last_halt` field, one slice) and matches low-reasoning agent reality (agents do not auto-recover well anyway).
- CI provenance predicate gives a safe non-TTY authorization path without env-only spoof.
- `harness status` + `harness next` close the UX gap that Model B opened (every halt drops back to manual; the user needs a single command to see "where am I, what now?").

**Negative**:

- Budget / fence enforcement on raw adapter tool calls is best-effort only. Adapter pre-tool hooks are out of scope; v0.7 cannot hard-stop arbitrary `Edit` / `Write` / `Bash`.
- `circleci` and `jenkins` are not authorizable in v0.7 (no mandatory cryptographic proof contract). Users on those CIs must add a TTY-equivalent step or wait for the provider registry to grow.
- Halt-diary handoff requires the user to read `harness status` and decide. No auto-retry. For long-running chains, this means more human attention.
- Windows network deny is degraded (PATH-prepend bypassable by absolute paths). `--isolation=container` is the long-term answer; for v0.7 the audit posture flag is the visible signal.
- The slash-body bodies are pinned by exact-string grep-gate; future adapter-side UX changes require ADR amendment.

## Alternatives considered

- **Strong auto-resume / commit-per-phase model** (Round-3, Round-4; rejected Round-5): doubled implementation surface, conflicts with agent-never-approves, hides failures.
- **MCP server for agent-side autopilot control** (parked, `future_undecided/`): weak agent does not reliably honor MCP tool descriptions; covers a use case the browser dashboard (v0.9) already addresses for humans.
- **Per-phase wall-clock timeout via `signal.SIGALRM`** (rejected, Round-2): POSIX-only; Windows has no equivalent. Replaced with `time.monotonic()` polled between tool-call boundaries.
- **`HARNESS_AUTOMATION=chain` as state field** (rejected, Round-3): conflated env-as-permission with env-as-state. `execution_mode` is state; env is permission to acquire state. Audit `state_source=lock` makes this provable forensically.
- **Slash body as shell script** (rejected, Round-2 / Round-3): non-portable to Windows pwsh / cmd. Wrapper CLI owns runnable behavior.

## Cross-references

- Design doc: §1.1, §3.5, §3.5.1, §3.5.2, §3.6, §3.9, §4.3a/b, §4.4a/b, §4.5, §5, §5.1, §5.2, §5.3, §12.3, §12.4, §12.6, §12.11, §12.12, §12.13, §12.14.
- ADR-1 `2026-05-17-approver-provenance-and-execution-mode.md`: `phase approve` exit 8 rule for autopilot-active approval attempts.
- ADR-2 `2026-05-17-audit-canonicalization-locking-and-state-trust.md`: transaction protocol that budget decrements, halt-diary writes, and `phase.autopilot.{start,stop,halt}` audit entries ride on.
- Slices S07-prep (autopilot CLI + CI predicate), S08a/b (Roo+OpenCode `/fsd-run-phase`), S09a/b (`/fsd-run-all`), S10a (budgets), S10b (fence), S10c (POSIX net), S10d (Windows net), S11 (halt diary), S15 (`status`+`next`+`/fsd-status`), S16 (Fix: standard).
