# Phase Gate Hardening — Design (2026-05-17)

**Status**: design baseline, post-Round-7. Ready for implementation entry (S00 → S00.5 → S00.7 → S01 → …).

**Origin**: Phase E IDE dogfood (Roo Code adapter) — haiku agent rocketed `discuss → plan → execute → done` in one turn. ADR-001 didn't gate; `automation_mode` field unread; `--chain`/`--auto` doc-fiction.

**Goal**: phase gate enforced by code, not suggestion text. No `--yes` learnable flag, no agent-spawnable TTY prompt, no env-only authorization.

**Failure model (Round-5 Model B)**: autopilot halt = manual handoff. No auto-resume / auto-rollback / commit-per-phase. Halt diary records `{run_id, mode, phase_slug, last_successful_transition, halt_reason, halt_at_iso, suggested_next_command, suggested_next_command_requires_human}`; user reads `harness status` and `harness next` to proceed.

**Project model**: single-user / single-machine. Multi-user collaboration out of scope (§10).

**Review history**: 7 adversarial rounds, all BLOCK on first pass, all addressed inline. Round 1-6 condensed in §11; Round-7 spec additions in §12.

---

## Table of contents

| §  | Section |
|---|---|
| 0  | Core principle — Agent never approves |
| 1  | State schema delta |
| 2  | Audit log delta (chains, BOM, rotation, trust preflight) |
| 3  | CLI changes (`phase approve`, `reopen`, `autopilot start\|stop`, exit codes, transaction protocol, `status`/`next`) |
| 4  | Slash commands (`/fsd-run-phase`, `/fsd-run-all`, `/fsd-status` — exact bodies §4.3a/b, §4.4a/b, §12.11) |
| 5  | Best-effort guards (filesystem fence, network deny, halt handoff) |
| 6  | Installed-manifest v2 + `install-record.json` |
| 7  | CI / release-smoke contract (+ §7.1 release matrix, §7.5 no-git mode) |
| 8  | Required ADRs |
| 9  | Slice plan S00..S16 (+ §9.1 fixtures, §9.2 evidence contract) |
| 10 | Out of scope |
| 11 | Review history (Rounds 1-6 condensed) |
| 21 | Round-7 BLOCK ledger + new spec content (audit-tip anchor §12.1, safe-open §12.2, wrapper CLI §12.3, OIDC pinning §12.4, …) |
| 13 | Source of truth |

Cross-cutting: every CLI verb is registered in §12.7; every audit `verb=...` literal in §12.7. Exit codes in §3.4. Slice IDs are stable; reordering never renumbers.

---

## 0. Core principle — Agent never approves

**Only humans run `harness phase approve`.** The agent's only job is to read `state.execution_mode` and either proceed (within the bounds it permits) or stop and tell the user the exact command to run.

This collapses three potential failure modes into one:
- No TTY-prompt-in-IDE footgun (we never prompt from agent-spawned processes).
- No "agent learned `--yes`" arms race (the flag does not exist).
- No double-confirmation UX (user runs one command in one place).

Slash commands change `state.execution_mode`; they do **not** approve. Approval is always a separate, human-initiated `phase approve` invocation.

**Critical clarification**: Slash-command files are Markdown *instructions to the agent*, not executables. The agent must NOT direct-edit `.scratch/phase-state.json` to flip `execution_mode`. Mutation goes through CLI only: adapter Markdown calls wrapper verbs (`harness fsd-run-phase` / `harness fsd-run-all`), and those wrappers call `harness phase autopilot start --phase <slug>` / `harness phase autopilot stop` internally. The mutation path is atomic, audited (`verb=phase.autopilot.start` / `.stop`), and provenance-checked. Nothing else changes `execution_mode`. See §3.5.

---

## 1. State schema delta

### 1.1 `.scratch/phase-state.json`

| Field | Type | Default | Semantics |
|---|---|---|---|
| `execution_mode` | enum | `"manual"` | `"manual"` \| `"phase_autopilot"` \| `"chain_autopilot"`. Single source of truth. Set ONLY by `phase autopilot start|stop` (§3.5); read by transition validator. **Never** by `phase approve`. **Never trusted after a direct state-file edit**: every CLI command verifies the current canonical state hash against the latest valid audit tail before using any state field (§2.3). |
| `autopilot_run_id` | uuid4 \| null | `null` | **Round-4 BLOCK fix #5** — set by `phase autopilot start`, cleared by `phase autopilot stop`. Persists across CLI invocations so each `phase set` can verify it belongs to the same autopilot run (locks are per-critical-section; identity must live in state). |
| `autopilot_mode` | enum \| null | `null` | `"phase"` \| `"chain"`. Matches `execution_mode` semantics; explicit copy for forensic clarity. |
| `autopilot_phase_slug` | string \| null | `null` | The phase scope the autopilot was started for. Transition validator refuses transitions outside this slug under autopilot. |
| `autopilot_start_entry_hash` | sha256 hex \| null | `null` | The `entry_hash` of the `verb=phase.autopilot.start` audit entry. State write transactions for autopilot transitions reference this to anchor the run identity. |
| `cli_budgets_remaining` | object \| null | `null` | `{"shell_invocations": N, "file_mutation_ops": N, "wall_seconds": N}`. Capability-neutral counters. Adapter/tool-specific names (`Bash`, `Edit`, `Write`, etc.) are mapped to these capabilities only in adapter contracts; core state never stores adapter tool names. **Hard-stop** for `harness`-mediated subprocesses + `phase set` / `phase autopilot *` transitions. **Advisory** for raw adapter tools (no enforcement hook until v0.8). Decremented under state lock. |
| `last_halt` | object \| null | `null` | Round-5 Model B halt diary. Set on any autopilot halt; cleared when user starts a new autopilot run or runs `harness halt-diary clear`. Contains `{run_id, mode, phase_slug, last_successful_transition, halt_reason, halt_at_iso, suggested_next_command, suggested_next_command_requires_human, acknowledged_at}`. **Round-7 BLOCK fix (Adapter C-19)**: `suggested_next_command_requires_human: bool` flags whether the suggested command hits a TTY-only verb (`phase approve`, `phase reopen`); agents MUST surface to user, not execute. `acknowledged_at: iso8601 \| null` is set by user-initiated mutating verbs (`phase reopen`, `phase autopilot start`, `halt-diary clear`); §3.6 refuses `phase set done` while non-null `last_halt` has `acknowledged_at=null`. **Read-only documentation**, NOT a resumable checkpoint. |
| `last_halt_history` | array | `[]` | Capped at last 5 halts for forensic context. |
| `autopilot_allow_network` | bool | `false` | Echoed from start invocation; audited; influences whether deny-list guard short-circuits. |
| `execute_attempt_started_at` | iso8601 \| null | `null` | **Round-4 P1 fix — renamed from `attempt_started_at`**: stamped ONLY after a successful, approval-validated `plan → execute` transition. `phase reopen --to plan` resets it for the next execute entry. NOT updated on `phase set done`. Stale-approval checks in §3.6 require `approved_at >= plan_finalized_at` before entering execute and `approved_at >= execute_attempt_started_at` before marking done. |
| `plan_finalized_at` | iso8601 \| null | `null` | **Round-7 BLOCK fix (Coherence E-33)**: stamped on successful `(discuss \| execute) → plan` transition once both `verification` and `allowed_paths` are populated and validated under the state lock. Cleared (set to null) on `phase reopen --to discuss`. Read by §3.6 `(plan → execute)` validator: `approved_at >= plan_finalized_at` MUST hold, ensuring approval was issued against the current plan content, not a stale earlier version. |
| `draft_verification` | array | `null` | Holds previous phase's `verification` after `phase reopen` so user can revise in discuss/plan. NOT consulted by autopilot fence. (Round-3 reopen-scope fix.) |
| `draft_allowed_paths` | array | `null` | Same as above for `allowed_paths`. |
| `state_schema_version` | int | `2` (existing) | unchanged |
| (existing) `automation_mode` | enum | — | **deprecated**; v0.7.0 reads it as alias if `execution_mode` absent; v0.8.0 removes. Skills no longer reference it. |

### 1.2 Migration on read

If `execution_mode` is absent and `automation_mode` is present, coerce as:
- `automation_mode=manual` → `execution_mode=manual`
- `automation_mode=chain` → `execution_mode=phase_autopilot`
- `automation_mode=auto` → `execution_mode=chain_autopilot`

Write back on next mutation. Audit one-time `verb=migrate.state_v2` with `before_sha256`/`after_sha256` so the migration is provenance-tracked.

If both fields absent (v0.6.1 install): default `manual`, write back, audit.

---

## 2. Audit log delta

### 2.1 New optional fields

| Field | Source | Semantics |
|---|---|---|
| `schema_version` | CLI | `2` for new entries; absent on legacy entries (read as `1`). |
| `confirmation_kind` | **derived by CLI** | `"human_cli"` (default — a human ran `phase approve` directly), `"cascade_phase_autopilot"`, `"cascade_chain_autopilot"`, `"override_identity"`. **NEVER accepted as user input.** Forging detection: CLI writes this in the same code path that performs the action; reviewers grep for any code path that sets it from user-supplied data. |
| `by_source` | derived | `"install_record"` \| `"gitconfig"` \| `"env_override"` \| `"override_identity"` — which source the `--by` email matched. |

### 2.2 Hash-chain invariant (pinned) — **Round-3 BLOCK fix: per-entry chain added**

Two complementary hash chains exist post-Round-3:

**(A) State-content chain (unchanged from Round-1/2)**: each audit entry carries `before_sha256` / `after_sha256` of the state-file content surrounding the action. Proves "state transitioned from X to Y." Adding optional audit fields does **not** invalidate these hashes. Survives audit-log rotation trivially.

**(B) Entry chain (NEW Round-3)**: each audit entry carries an `entry_hash` field computed as:

```
entry_hash = sha256(canonical_json(entry_minus_entry_hash) || previous_entry_hash)
```

Where `previous_entry_hash` is the `entry_hash` of the immediately prior entry (across rotation: first entry of `audit.log` references last entry of `audit.log.1`; rotation header records `seed_previous_entry_hash`). First-ever entry uses `previous_entry_hash = "0" * 64`. Verifier (`harness verify --audit`, NEW slice — promoted from §10 "future" to in-scope per Round-3) walks the entire history (incl. rotated files) and confirms chain integrity. Exit 10 on mismatch (§3.4).

**Tamper-detection scope (Round-4 BLOCK fix #8 — downgraded claim, honest)**: the per-entry chain detects **incomplete or accidental edits** — partial deletion, single-field rewrite, truncation, rotation-seam corruption. It does **NOT** make the log tamper-evident against a repo-local attacker who can rewrite all of `audit.log*` and recompute every `entry_hash`. That class of attacker requires an **anchored tip outside the mutable repo** (signed `audit.log.sig`, external timestamping, or system-keychain-stored verifier key) — tracked as a future Nice-to-have in §10, not in v0.7 scope. The claim in this doc is therefore: "audit chain is integrity-checked, not signature-tamper-evident."

`entry_hash` and `previous_entry_hash` are themselves excluded from the canonical input (otherwise self-referential). All other fields including newly added optional ones participate — schema evolution naturally extends the chain.

Golden-fixture regression test (slice 6) MUST exercise: (i) v1+v2 mixed schema, (ii) rotation boundary, (iii) tampered byte at random offset rejected by verifier.

### 2.3 Canonicalization — **Round-3 fix: name the function**

JSON canonicalization for hashing uses the `rfc8785` PyPI library (RFC 8785 — JSON Canonicalization Scheme): sorted keys, UTF-8 no-BOM, no insignificant whitespace, normalized number serialization. `docs/adr/2026-05-17-audit-canonicalization-locking-and-state-trust.md` pins the library version and provides 4 golden vectors (state file mid-transition; audit entry with `previous_entry_hash`; entry across rotation boundary; entry with unicode/control-character `--reason` post-sanitization). On Windows, the CLI MUST normalize CRLF→LF on read **before** invoking the canonicalizer.

**Round-2 BLOCK fix — write-time line endings**: All harness-managed JSON files (state, audit, manifest, install-record, checkpoint) are written with `open(..., newline='\n')` and an explicit `\n` writer. These paths are added to `.gitattributes` with `text eol=lf` so `core.autocrlf=true` cannot mangle them on Windows checkouts. Audit fields emitted via `json.dumps` exclusively — never string interpolation (prevents quote-injection from adversarial `HARNESS_BY_TRUST` / `--reason` values).

**Round-2 BLOCK fix — path canonicalization**: All path strings in audit/manifest/state entries use forward-slash POSIX form (`pathlib.PurePosixPath`), never `os.path.normpath`. Writers reject backslashes at the write boundary. Hashing operates on the canonicalized POSIX form so Linux and Windows produce byte-identical hashes for the same logical content.

### 2.4 BOM handling

All harness-managed JSON/JSONL files MUST be UTF-8 **without** BOM. **Write**: canonicalizer never emits BOM, files opened with `encoding="utf-8"` not `utf-8-sig`. **Read**: every reader rejects files starting with `0xEF 0xBB 0xBF` and exits 5 with hint `run 'harness repair --strip-bom <path>' to migrate`. `harness repair --strip-bom` rewrites under state lock, appends `verb=repair.bom_stripped` audit entry. `.gitattributes` ships `*.json text eol=lf working-tree-encoding=UTF-8` to prevent re-introduction. S14 grep-gate forbids BOM byte sequence in fixtures.

### 2.5 Audit-log rotation across two chains (Round-4 BLOCK fix #9 — rewritten to match per-entry chain):

Both chains (A) state-content and (B) per-entry survive rotation. Specifics:

- **Rotated-file ordering**: `audit.log.N` (oldest) … `audit.log.2`, `audit.log.1`, `audit.log` (current tip). Numbering is contiguous; gaps fail verification.
- **Seed across rotation**: when rotation happens, the first entry of the new `audit.log` (rotated from prior `audit.log`) has its `previous_entry_hash` field set to the **last entry's `entry_hash`** of the rotated-out file. The rotation event itself emits a `verb=audit.rotated` entry as the LAST entry of the rotated-out file, carrying `next_file_seed_previous_entry_hash` so the verifier can walk forward without out-of-band metadata.
- **Index reset**: post-rotate, `seq` (per-file sequence) resets to 1 in the new file. A monotonic global `seq_global` field is added in Round-4 so verifiers don't need to compute it; gaps in `seq_global` fail verification.
- **Failure modes detected by `harness verify --audit`**:
  - Missing rotated file → exit 10 `audit_chain_gap`.
  - Duplicate `seq_global` → exit 10 `audit_chain_duplicate`.
  - Truncated tail (last entry's `entry_hash` does not match journal's recorded tip) → exit 10 `audit_chain_truncation`.
  - `previous_entry_hash` mismatch at rotation seam → exit 10 `audit_chain_rotation_seam`.
- Regression fixture (slice 6) MUST exercise all four failure modes plus a clean cross-rotation walk.

Earlier Round-2 wording ("not entry-chained, so rotation does not invalidate") is **removed** — superseded by Round-3 per-entry chain (§2.2 above). Round-4 reviewer correctly flagged the contradiction.

### 2.6 State trust preflight

Every CLI command that reads or mutates `.scratch/phase-state.json` MUST perform this preflight under the state lock before trusting any state field:

1. Read state bytes, reject BOM/CRLF violations per §2.3/§2.4, and canonicalize.
2. Walk the current audit tail far enough to identify the latest valid entry with `after_sha256`.
3. Compare `sha256(canonical_state_bytes)` to that latest `after_sha256`.
4. If mismatch: exit 10 `state_audit_tip_mismatch`, emit no mutation, and print `Fix: run harness verify --audit` plus the manual repair path.

This is the hard defense against direct `Edit`/`Write` mutation of `.scratch/phase-state.json`. The lock and transaction journal protect harness-managed writes; the state trust preflight protects reads after out-of-band edits. Regression tests MUST hand-edit `approved=true` and `execution_mode=chain_autopilot` without an audit entry and assert that `harness phase set`, `harness phase autopilot start|stop`, `harness status --json`, and `harness next --json` all fail closed before using the forged value.

---

## 3. CLI changes

### 3.1 `phase approve` — human-only gate

```
harness phase approve [--by <email>] [--at <iso>]
```

**`--by` is now optional** (Round-4 UX simplification — user request). `.harness/install-record.json approvers[]` is the canonical identity source. `git config user.email` is only an install-time / approve-time discovery provider for the single default approver; it is never the authority by itself. `--by` exists as an explicit selector for unusual cases (multiple-identity user, no-gitconfig environment).

**Order of operations** (any failure → exit 6 immediately):

1. **TTY gate**: `os.isatty(sys.stdin.fileno())` MUST be True. Non-TTY callers (agent-spawned subprocesses have piped stdin) rejected with exit 6 `non_tty_approval_blocked`. No env, no flag, no override unlocks it. (Round-3.) **`HARNESS_BY_TRUST` is NOT consulted here at all** (Round-4 BLOCK fix #2 — env identity is for `phase autopilot start` only; `phase approve` has zero env-trust path).
2. **Identity resolution** (Round-4):
   - If `--by` provided → use that.
   - Else → read `git config user.email` as a convenience discovery value. If empty → exit 6 with message "set `git config user.email` or pass `--by <email>`". If no git repo at all → see no-git mode (§7.5).
3. **Identity verification against `.harness/install-record.json`**:
   - Resolved identity MUST match `install-record.approvers[]` (single entry in single-user mode; auto-populated at install — see §6 Round-4).
   - Mismatch → exit 6 with `--override-identity --reason <text>` hint.
4. `--override-identity --reason <text>`: bypasses step 3, logs `confirmation_kind=override_identity`, `by_source=override_identity`, `override_reason=<sanitized>` to audit.
5. **NO stdin prompt** (we *read* isatty but never `input()`; IDE-captured-prompt footgun avoided). Nonce discovery is filesystem-based (§3.1.1), not an interactive prompt.
6. `confirmation_kind` auto-derived:
   - `state.execution_mode == manual` → `"human_cli"`.
   - Else → exit 8 ("agents do not approve during autopilot").
7. **Human-presence proof (Round-5 BLOCK #2)** — see §3.1.1 below. TTY alone is downgraded to "blocks non-PTY subprocesses"; real human proof requires either an out-of-project nonce or an OS credential prompt.
8. State + audit mutation through the transaction protocol (§3.8).

### 3.1.1 Human-presence proof (Round-5 BLOCK #2)

`os.isatty(stdin)` is retained as a cheap first gate but its claim is downgraded: it **blocks non-PTY subprocesses only**. A PTY-capable agent (pexpect, `script(1)`, `unbuffer`) could allocate a TTY. Real human proof needs one of two primitives.

**Primary: out-of-project approval nonce (default).**

The harness writes single-use nonces to a directory OUTSIDE any project root (Roo/OpenCode file-tool sandboxes are project-scoped and cannot read it):

- POSIX: `~/.harness/approval-nonces/` (0700)
- Windows: `%LOCALAPPDATA%\Harness\approval-nonces\` (user ACL)

Flow:

```
$ harness approve-nonce mint --audience phase.approve
nonce minted for phase.approve; expires in 120s
$ harness phase approve
[harness] ok - phase approved by alice@x
```

`harness approve-nonce mint` (run by human in a different terminal):
- Generates 64-bit token → 8-char base32 code.
- Writes `~/.harness/approval-nonces/<code>.json`: `{minted_at, expires_at = minted_at + 120s, minter_tty, audience: "phase.approve"}`, mode 0600.
- Prints the code to its own TTY. Never to project tree, never to logs.

`phase approve` consumes the newest valid nonce for `audience="phase.approve"` automatically: reads candidate files, verifies expiry, verifies `minter_tty != consumer_tty` (defeats "agent runs both in same PTY"), deletes the consumed file (single-use), proceeds. It never asks the caller to type or paste the nonce. Audit: `confirmation_kind=human_nonce`, `nonce_id`, `nonce_minted_at`, `nonce_consumed_at`, `nonce_minter_tty`, `nonce_consumer_tty`.

**Fallback: OS credential prompt.** macOS `security`/Touch ID, Linux `pinentry`, Windows `CredUIPromptForWindowsCredentials`. Activated via `harness install --human-proof credential`. Audit: `confirmation_kind=os_credential`, `credential_backend`.

User picks one at install time. Default = nonce (works on headless Linux, SSH).

**Exit codes (additions to §3.4)**:

| Code | Symbol | Trigger |
|---|---|---|
| 6 | `non_tty_approval_blocked` | isatty False (first gate). |
| 6 | `human_proof_missing` | TTY ok but no nonce in 60s and `--prompt-credential` not requested. |
| 6 | `human_proof_nonce_expired` | Nonce expired. |
| 6 | `human_proof_nonce_same_tty` | Minter+consumer same TTY. |
| 6 | `human_proof_credential_denied` | OS credential prompt declined. |
| 6 | `human_proof_nonce_audience_mismatch` | Nonce minted for different verb. |

**Threat model — what this does NOT defend**:
- A shell agent with unrestricted Bash on same user account can `cat` the nonce file. Mitigation: 120s TTL (configurable down to 30s). Trade-off documented; not silently relied on.
- User confused-deputy (socially engineered into minting). User training; visible verb in prompt.
- Compromised OS keychain. Out-of-scope (broader OS-trust assumption).

What it **does** defend: adapters that satisfy the approval-proof capability contract: project-scoped file tools only, no read access to the nonce directory, no ability to script the user's separate terminal, and no ability to trigger or answer OS credential prompts. Roo/OpenCode currently fit this contract. Any future adapter with broader filesystem, desktop automation, or terminal-control capability MUST be marked `approval_proof=unsupported` and run manual-only unless it provides a stronger proof.

**Audit `by_source` values**: `"gitconfig_auto"` | `"explicit_by_flag"` | `"override_identity"`.

**`--by` / `--reason` / `--override-reason` sanitization** (Round-2 + cycle-1 amendment): max 1024 chars; literal newlines + all C0 control chars (U+0000–U+001F) + DEL (U+007F) REJECTED with exit 6 sub\_reason=invalid\_reason\_chars (defense-in-depth; rejection is safer than escape replacement — the earlier "literal newlines replaced with `\n` token" wording was aspirational; the implementation has always rejected them, which is the correct behavior). Unicode bidi/isolate controls, zero-width joiners, variation selectors, tag characters, and unpaired surrogates are also rejected. Input is NFKC-normalized before the forbidden-char scan so Math Alphanumeric and other compatibility forms are folded to ASCII in the audit log, removing homograph spoofs. Same rules apply to `phase reopen --reason` and all identity fields written to audit (`HARNESS_BY_TRUST`, `HARNESS_AUTOMATION` at autopilot-start time). **Spec amendment note (P3-P1-B, cycle-1):** spec previously read "literal newlines replaced with `\n` token"; corrected to match implementation.

### 3.2 `phase reopen` (NEW verb) — TTY-only

`harness phase reopen --to <discuss|plan> [--by <email>] --reason <text>`

**TTY gate applies identically to `phase approve`**: non-TTY callers exit 6. Otherwise an agent could reset approvals or disrupt autopilot. Identity resolution identical to §3.1 (gitconfig auto-read; `--by` optional override).

Use cases: mind-change mid-flow ("wait, let's also do X"); recovery from a hung autopilot.

- Resets approval (`approved=false`, `approved_by=null`, `approved_at=null`).
- Resets phase to target. `--to plan` permitted from execute/done; `--to discuss` permitted from any phase.
- Audit entry `verb=phase.reopen` with `from_phase`, `to_phase`, `reason`, `preserved_as_draft=true` (Round-3 BLOCK refinement: `verification` array and `allowed_paths` are **moved to draft slots** — `state.draft_verification`, `state.draft_allowed_paths` — NOT carried forward as active. Reaching `execute` again requires re-confirming them in `plan` exit; weak agents cannot rely on stale code-now-changed allowed_paths fence. Original Round-2 wording "preserved" was too strong per Round-3 reviewer P1).
- Provenance check identical to `phase approve`.
- Halts autopilot if `execution_mode != manual` at call time (sets execution_mode back to manual, audits `verb=phase.autopilot.halt, halt_reason=reopen`).

Replaces hand-editing of `phase-state.json` (which would corrupt audit chain).

### 3.5.1 Non-TTY CI authorization predicate (Round-5 BLOCK #1)

`HARNESS_BY_TRUST + HARNESS_AUTOMATION` env pair alone is **insufficient** for `phase autopilot start` from a non-TTY caller — an agent shell can set both. Non-TTY autopilot start requires a **CI provenance predicate** that an agent shell cannot satisfy.

**Algorithm** (under state lock, before mutation):

```
if stdin_is_tty() and TTY_human_proof_satisfied (§3.1.1):
    authorization_source = "cli_tty_human"
elif ci_predicate_satisfied():
    authorization_source = "ci_<provider>"
else:
    exit 6 non_tty_authorization_unverified
```

`ci_predicate_satisfied()`:
1. `HARNESS_AUTOMATION ∈ {"phase","chain"}` present.
2. `HARNESS_BY_TRUST` present, non-empty, sanitized; NOT equal to any `install-record.approvers[]` entry (else exit 6 `ci_bot_identity_overlaps_human_approver`).
3. Exactly ONE provider signature in the cryptographic allowlist below validates. Two markers set → exit 6 `ci_provider_ambiguous`.
4. Provider attestation MUST be cryptographically verified: fetch/validate OIDC or verify a signed CI token, then match claims to repo/ref/sha/run id. Network failure, missing token, claim mismatch, or env-only provider → exit 6. There is no regex-only authorization path in v0.7.

**Provider allowlist**:

| Provider | Marker | Required vars | Required proof |
|---|---|---|---|
| `github_actions` | `GITHUB_ACTIONS=true` | `GITHUB_RUN_ID`, `GITHUB_REPOSITORY`, `GITHUB_SHA`, `GITHUB_WORKFLOW`, `GITHUB_RUN_ATTEMPT` | Fetch OIDC via `ACTIONS_ID_TOKEN_REQUEST_URL` + `_TOKEN`; verify issuer/audience/signature; match repository, sha, workflow, run id. |
| `gitlab_ci` | `GITLAB_CI=true` | `CI_JOB_ID`, `CI_PIPELINE_ID`, `CI_PROJECT_PATH`, `CI_COMMIT_SHA`, `CI_RUNNER_ID` | Verify `CI_JOB_JWT_V2` signature and claims; env-only audit is rejected. |
| `buildkite` | `BUILDKITE=true` | `BUILDKITE_BUILD_ID`, `BUILDKITE_JOB_ID`, `BUILDKITE_PIPELINE_SLUG`, `BUILDKITE_COMMIT`, `BUILDKITE_AGENT_ID` | Verify Buildkite OIDC token signature and claims; env-only audit is rejected. |

`circleci` and `jenkins` are deliberately absent in v0.7 because the design has no mandatory cryptographic proof for them. They may be added later through the CI provider registry only when their proof contract is explicit. Regex checks remain input hygiene only; they never authorize non-TTY autopilot by themselves. Negative tests spoof every provider marker locally and assert exit 6 unless a valid token is present.

`--allow-network` follows the same predicate independently (per-flag re-evaluation). `HARNESS_ALLOW_NETWORK=1` alone is insufficient — CI signature must also validate.

**Audit fields** added to `verb=phase.autopilot.start`:
- `authorization_source` ∈ `{"cli_tty_human", "ci_github_actions", "ci_gitlab_ci", ...}`
- `ci_signature` — full snapshot of provider's required vars (verbatim), or null
- `ci_oidc_verified` — bool
- `ci_oidc_claims` — `{iss, sub, repository, ref, sha}` subset or null
- `bot_identity` — `HARNESS_BY_TRUST` value
- `bot_identity_distinct_from_approvers` — bool, must be true

**Exit codes** (additions to §3.4):

| Code | Symbol |
|---|---|
| 6 | `non_tty_authorization_unverified` |
| 6 | `ci_bot_identity_overlaps_human_approver` |
| 6 | `ci_provider_ambiguous` |
| 6 | `ci_oidc_unreachable` |
| 6 | `ci_oidc_claim_mismatch` |

### 3.5.2 Active-autopilot re-entry (Round-5 Model B simplification)

Under Model B, `phase autopilot start` is **not idempotent**. Active autopilot detection:

- Under state lock, after crash recovery (§3.8).
- `execution_mode == manual` → start new run.
- `execution_mode != manual` → **exit 15 `autopilot_already_active`**, message names existing `autopilot_run_id`, `autopilot_mode`, `autopilot_phase_slug`, and instructs:
  > Run `harness status` to inspect. Then choose exactly one path: let the current autopilot continue, or run `harness phase autopilot stop --reason "<text>"` to return to manual mode. Only after stop may you use manual `harness phase set <next>` or start a new autopilot run.

No `chain --resume`. No silent retry. Re-entry is always an explicit human decision after reading status. This matches Model B's "halt → manual handoff" principle: interruption is not a failure to auto-recover from; it is a hand-off to the human.

`next-pending` acquires the state lock briefly (consistent-snapshot read after running crash recovery), then releases. Pure read otherwise. Empty result → exit 0 with message "all phases done".

### 3.7 Cross-platform lock protocol

Round-3 reviewer flagged: mtime + `psutil.pid_exists` is unsafe — wall-clock mtime, PID reuse, race between recoverers, Windows delete-while-open differs from POSIX. Replacement protocol:

Lockfile path: `.scratch/phase-state.json.lock`. Created via `os.open(path, O_CREAT|O_EXCL|O_WRONLY)` (atomic on both POSIX and Windows). Content (JSON, written immediately after acquire):

```json
{
  "pid": 12345,
  "hostname": "alice-laptop",
  "process_start_time": 173456789.123,
  "boot_id": "550e8400-e29b-41d4-a716-446655440000",
  "monotonic_acquired_at": 12345.678,
  "acquired_iso": "2026-05-17T03:14:15Z",
  "owner_token": "<128-bit hex random>"
}
```

`boot_id` source: Linux `/proc/sys/kernel/random/boot_id`; macOS `sysctl -n kern.boottime` parsed; Windows `WMI Win32_OperatingSystem.LastBootUpTime` (or `GetTickCount64()` since boot as ms-precision fallback).

Recovery decision matrix (when O_EXCL acquire fails):
- Different `hostname` → never force-stale. Other machine may be working. exit 3.
- Same `hostname` + `boot_id` differs from current → reboot happened → safe to recover.
- Same `hostname` + `boot_id` matches + `pid` alive + `process_start_time` matches /proc/<pid>/stat → genuinely held. exit 3.
- Same `hostname` + `boot_id` matches + (`pid` dead OR `process_start_time` mismatched) → stale, recover.
- Ambiguous (e.g. unable to read /proc on container) → require `harness lock recover --force`.

**Round-5 BLOCK #3 — recovery-mutex acquisition ordering**: every primary-lock acquire MUST first check for `.lock.recovery` and back off while it exists. Otherwise a normal waiter could grab the primary in the window between stale-detect and unlink, letting the recoverer delete a live lock.

Acquire algorithm (`scripts/lib/phase_lock.py`):

```python
PRIMARY  = scratch / "phase-state.json.lock"
RECOVERY = scratch / "phase-state.json.lock.recovery"
MAX_RECOVERY_WAIT_S = 30.0
BACKOFF_INITIAL_S   = 0.05
BACKOFF_MAX_S       = 1.0

def acquire_primary(timeout_s: float = 10.0):
    deadline = time.monotonic() + timeout_s
    recovery_seen = 0.0
    backoff = BACKOFF_INITIAL_S
    while True:
        # STEP A — recovery-mutex check MUST precede every O_EXCL attempt.
        if RECOVERY.exists():
            recovery_seen += backoff
            if recovery_seen > MAX_RECOVERY_WAIT_S:
                sys.exit(3)
            time.sleep(backoff); backoff = min(backoff * 2, BACKOFF_MAX_S); continue

        # STEP B — atomic O_EXCL.
        try:
            fd = os.open(PRIMARY, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            _write_owner_record(fd); os.fsync(fd); fsync_parent_dir(PRIMARY.parent)
            return LockHandle(fd=fd, ...)
        except FileExistsError:
            pass

        # STEP C — classify existing primary.
        verdict = classify(_read_owner_record(PRIMARY))
        if verdict in ("live", "foreign_host"):
            if time.monotonic() >= deadline: sys.exit(3)
            time.sleep(backoff); backoff = min(backoff * 2, BACKOFF_MAX_S); continue
        if verdict == "ambiguous":
            sys.exit(3)  # require `harness lock recover --force`
        if verdict == "stale":
            try_recover(observed_token=...)  # STEP D
            backoff = BACKOFF_INITIAL_S; continue  # always re-enter STEP A
```

Recover algorithm (single attempt; caller loops via STEP A):

```python
def try_recover(observed_token):
    # 1. Acquire recovery mutex atomically.
    try:
        rfd = os.open(RECOVERY, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return  # another recoverer; STEP A will see it
    try:
        # 2. Validation point (i).
        try: record_i = _read_owner_record(PRIMARY)
        except FileNotFoundError: return  # clean release happened
        if record_i["owner_token"] != observed_token: return
        if classify(record_i) != "stale": return

        # 3. Validation point (ii) — IMMEDIATELY before unlink.
        try: record_ii = _read_owner_record(PRIMARY)
        except FileNotFoundError: return
        if record_ii["owner_token"] != record_i["owner_token"]: return

        # 4. Safe to unlink.
        try:
            os.unlink(PRIMARY); fsync_parent_dir(PRIMARY.parent)
        except PermissionError:
            sys.exit(3)  # Windows open-handle case
        audit_emit(verb="lock.recovered", reclaimed_owner_token=record_ii["owner_token"])
    finally:
        # 5. Release recovery mutex AFTER unlink decision.
        os.close(rfd)
        try: os.unlink(RECOVERY); fsync_parent_dir(RECOVERY.parent)
        except FileNotFoundError: pass
```

**Invariants** (`tests/phase_lock/test_invariants.py`):
1. No code path acquires primary without first stat'ing recovery (STEP A).
2. Recoverer NEVER replaces primary; only `os.unlink()` after two-point token validation.
3. `try_recover` releases recovery mutex on every return path.
4. After recovery, recoverer re-enters STEP A (does NOT inherit lock).

Spell out in `docs/adr/2026-05-17-audit-canonicalization-locking-and-state-trust.md`.

### 3.8 Crash-safe state+audit transaction protocol

Holding a lock prevents concurrent writers; it does NOT make two-file (state + audit) mutation crash-atomic. A power loss between `os.replace(state)` and audit append, or between audit append and state replace, can leave state and audit divergent. Since per-entry audit hashes are now used as evidence (§2.2), divergence cannot be tolerated.

Protocol (under state lock; journal at `.scratch/phase-state.json.journal`). Round-5 BLOCK #4 inserts an explicit parent-dir fsync between staging and audit so the tmp's directory entry is durable BEFORE audit references it.

| # | Step | Durability | Why |
|---|---|---|---|
| 1 | Write journal `{txn_id, action, before_sha256, after_sha256, audit_entry_draft, started_at_monotonic}` | `fsync(journal_fd)`; `fsync_parent_dir(scratch)` | Journal entry durable before any observer can see state intent. |
| 2 | Write `state.json.tmp` | `fsync(tmp_fd)`; **`fsync_parent_dir(scratch)` — NEW Round-5** | Temp directory entry durable so recovery can find it. |
| 3 | Append audit entry (with `txn_id`, chained `entry_hash`) to `audit.log` | `fsync(audit_fd)` | Audit becomes recovery oracle only after tmp is durable. |
| 4 | `os.replace(state.json.tmp, state.json)` | `fsync_parent_dir(scratch)` | Atomic rename + dir fsync. |
| 5 | `os.unlink(journal)` | `fsync_parent_dir(scratch)` | Journal removal durable. |

**Recovery decision matrix** (run at every CLI start and at `harness verify --audit`). Let J = journal exists, T = state.json.tmp exists, A = audit tail's `txn_id` matches journal.

| # | J | T | A | state-on-disk hash | Decision | Exit |
|---|---|---|---|---|---|---|
| 1 | 0 | 0 | 0 | any | Quiescent. | 0 |
| 2 | 0 | 1 | 0 | any | Orphan tmp; unlink. | 0 |
| 3 | 0 | 0 | 1 | == after | Accept (S5 deferred). | 0 |
| 4 | 0 | 1 | 1 | == after | Unlink tmp; accept. | 0 |
| 5 | 1 | 0 | 0 | == before | Rollback: unlink(journal). | 0 |
| 6 | 1 | 1 | 0 | == before | Rollback: unlink(tmp); unlink(journal). | 0 |
| 7 | 1 | 1 | 1 | == before AND sha(tmp) == after | **Roll forward**: replace(tmp, state); fsync_parent_dir; unlink(journal). | 0 |
| 8a | 1 | 0 | 1 | == after | Finalize: unlink(journal). | 0 |
| 8b | 1 | 1 | 1 | == after | Finalize: unlink(tmp); unlink(journal). | 0 |
| 9 | 1 | * | 1 | ∉ {before, after} | Undecidable. | **14** |
| 10 | 1 | 1 | 0 | != before | Corruption. | **14** |
| 11 | 1 | 0 | 0 | != before | Corruption. | **14** |

Crash fixtures (pinned, see §9.1) cover all rows.

Recovery (run at every CLI start and at `harness verify --audit`):
- If `journal` exists: read `txn_id`. Two cases:
  - Audit tail's `txn_id` matches journal AND state-on-disk hash equals journal's `after_sha256` → step 5 was the only thing left; remove journal.
  - Audit tail's `txn_id` matches journal AND state hash equals `before_sha256` (state replace did not happen) → roll forward via `os.replace(state.json.tmp, state.json)` if `state.json.tmp` exists with correct hash, else exit 14 (`crash_recovery_undecidable`) and require human action.
  - Audit tail's `txn_id` does not match journal → step 3 did not complete: audit entry was never written. Delete `state.json.tmp` (if exists) and journal. State remains as `before`. The action effectively did not happen.

Exit 14 `crash_recovery_undecidable` — see §3.4. Harness fails closed; user runs `harness lock recover --force` after inspection.

`harness verify --audit` (slice S06) detects orphan `txn_id`s in audit without a corresponding state-content chain step and flags them.

### 3.8.1 Cross-platform directory durability (Round-5 BLOCK #5)

`fsync(parent_dir)` is POSIX-only. Windows needs `CreateFileW` + `FlushFileBuffers`. Module: `scripts/lib/durable_fs.py`. Exports `fsync_parent_dir(path)`.

**POSIX**:
```python
def _fsync_parent_dir_posix(parent):
    fd = os.open(str(parent), os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)
```

**Windows** (ctypes wrapper):
```python
import ctypes
from ctypes import wintypes
_k = ctypes.WinDLL("kernel32", use_last_error=True)
_k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
_k.CreateFileW.restype = wintypes.HANDLE
_k.FlushFileBuffers.argtypes = [wintypes.HANDLE]
_k.CloseHandle.argtypes = [wintypes.HANDLE]
FILE_LIST_DIRECTORY = 0x0001
FILE_SHARE_R_W_D    = 0x00000001 | 0x00000002 | 0x00000004
OPEN_EXISTING       = 3
BACKUP_SEMANTICS    = 0x02000000
INVALID = wintypes.HANDLE(-1).value

def _fsync_parent_dir_windows(parent):
    h = _k.CreateFileW(str(parent), FILE_LIST_DIRECTORY, FILE_SHARE_R_W_D,
                       None, OPEN_EXISTING, BACKUP_SEMANTICS, None)
    if h == INVALID:
        raise DurableFsError(f"CreateFileW: WinError {ctypes.get_last_error()}")
    try:
        if not _k.FlushFileBuffers(h):
            raise DurableFsError(f"FlushFileBuffers: WinError {ctypes.get_last_error()}")
    finally:
        _k.CloseHandle(h)
```

Dispatch by `os.name`. Failure → `DurableFsError` → caller exits 14 before mutating further.

### 3.9 UX surface — `harness status` + `harness next` + `Fix:` error standard

User reviewer (UX pass) recommended these be promoted from v0.8 into v0.7. Model B handoff is unusable without them: if every halt drops the user back to manual mode, the user must have a single command that tells them "where am I, what now?"

**Important UX principle (Round-5)**: don't add more CLI verbs. The pair `status` + `next` covers 100% of "what do I do now" queries. Both are **terminal CLI commands** AND **safe for agents/IDE to invoke** (read-only, no TTY required, no lock contention) — this is the key distinction from `phase approve`.

**Execution-surface contract**:

| Command | Caller | Safe for agent? | Why |
|---|---|---|---|
| `harness phase approve` | User in terminal | **NO** — TTY-only gate | Human consent. |
| `harness phase reopen` | User in terminal | **NO** — TTY-only gate | Human-initiated state mutation. |
| `harness status` | User in terminal OR agent via `/fsd-status` slash | **YES** — read-only | Snapshot. |
| `harness next` | User in terminal OR agent | **YES** — read-only | Output is a *recommendation*, not an action. |
| `harness phase set <slug>` | Agent typically | yes (gated by ADR-001 + autopilot identity) | Mutation but gate-enforced. |
| `harness phase autopilot start \| stop` | Agent (via slash) OR CI bot | yes (gated by §3.5.1 predicate) | Mutation but predicate-enforced. |

**Critical rule on `harness next`**: if the output line is `harness phase approve` (or any TTY-only verb), the agent MUST surface it to the user as a "please run this in your terminal" message, NOT execute it. Slash command bodies that call `harness next` MUST include this routing logic in their Markdown text. Failure mode: agent passes the line directly to its Bash tool, hits the TTY gate, exits 6 — surfaces error harmlessly but defeats the UX point.

**Reference flow (user-visible)**:

```
[in IDE]   /fsd-status
[agent]    runs `harness status` internally
[IDE shows] Phase: execute
            Next action: harness phase set done

[agent]    runs `harness phase set done` (allowed; gated by ADR-001)
[agent]    runs `harness next` internally
[output]   harness phase approve
[agent]    surfaces to user: "터미널에서 실행해주세요: harness phase approve"
[user in terminal] harness phase approve
[CLI]      TTY gate passes → human-proof nonce path → approved.
```


**`harness status`** — read-only, no lock contention (consistent-snapshot read after running crash recovery once). Output (human-friendly):

```
$ harness status
Phase           : execute (entered 2026-05-17T10:30Z, 24m ago)
Approved        : yes (alice@x at 10:20Z, source=gitconfig_auto)
Execution mode  : manual
Autopilot       : inactive
Halt diary      : (none recent)
Next action     : harness phase set done    (when execute is complete)
```

With recent halt:
```
$ harness status
Phase           : execute (entered 2026-05-17T10:30Z)
Approved        : yes (alice@x)
Execution mode  : manual                           [reverted from phase_autopilot]
Halt diary      : run_id=8f6c..., halted 2m ago
                  reason=verification_failed
                  last successful: phase-02c:plan→execute
Next action     : harness phase reopen --to plan --reason "fix verification"
```

Machine-readable: `harness status --json` for scripting. Auditless (does not write).

**`harness next`** — human-readable next action. It is safe for low-reasoning agents because it never prints a human-only command to stdout as an executable success result:

```
$ harness next
harness phase set done
```

If next requires TTY (e.g. approve): exits 17 and prints the human action only as explanatory text, never as shell-capturable stdout. If no action (e.g. autopilot mid-run): prints `no action - autopilot active` and exits non-zero so shell aliases do not accidentally do something.

Machine-safe forms:
- `harness next --shell`: exits 0 and prints stdout only for agent-safe commands. If next action requires a human (`phase approve`, `phase reopen`, credential prompt, nonce mint), prints nothing to stdout and exits 17 `human_action_required`.
- `harness next --json`: always prints structured data: `{ "requires_human": bool, "agent_safe": bool, "command": string|null, "reason": string }`.

**`Fix:` error standard (S16)** — every non-zero exit MUST emit `Fix: <command>` line to stderr. Examples:

```
Error (exit 6): no gitconfig user.email and --by not provided.
Fix: run `git config user.email <your-email>` or `harness phase approve --by <your-email>`

Error (exit 8): cannot approve during autopilot.
Fix: run `harness phase autopilot stop --reason "<text>"` first, then re-approve.

Error (exit 12): chain mode requires git repo.
Fix: run `git init` in this project, or use `--mode phase --accept-no-git-degraded`.

Error (exit 15): autopilot already active for run_id=8f6c...
Fix: run `harness status` to inspect, then `harness phase autopilot stop --reason "<text>"` before starting a new run.
```

Verification (`scripts/smoke/verify_fix_lines.py`): walks every exit code in §3.4 table, triggers each path under a fixture, asserts stderr contains `Fix: ` literal. Missing `Fix:` is a release-blocker.

**`/fsd-status` slash command (S15)** — IDE-side phase visibility. Slash command body just runs `harness status` and surfaces output. Read-only, no TTY required. Both adapters identical body.

### 3.6 ADR-001 transition validator extension

The Round-2 Realist observed that `scripts/lib/transition.py::validate_transition` only checks `approved=true` for `(execute → done)`. A weak agent in `manual` mode could otherwise enter `execute` before a human approval, perform code work, and only hit approval at `done`. Extension:

- For ANY transition under `execution_mode != manual`: reject (exit 2) unless **all of the following hold under the state lock** (Round-4 BLOCK fix #5 — locks are per-critical-section, so autopilot context must be persisted in state, not derived from prior audit entry):
  - `state.autopilot_run_id` is non-null,
  - `state.autopilot_phase_slug` equals the phase being transitioned (or its current phase under `chain_autopilot`),
  - The audit entry referenced by `state.autopilot_start_entry_hash` exists and verifies under the per-entry chain (Round-3 §2.2),
  - `state.cli_budgets_remaining` for the corresponding counter is > 0 (post-decrement).
- For `(plan → execute)` under `manual`: require `approved=true`, `approved_at >= plan_finalized_at`, and active `verification` / `allowed_paths` values to be present. Only after these checks pass may the CLI stamp `execute_attempt_started_at`. This is the primary "no code-executing phase without prior human approval" invariant.
- For `(execute → done)` under `manual`: keep the existing `approved=true` check, but also require `approved_at >= execute_attempt_started_at` so a later `reopen --to plan` invalidates stale approvals for completion.
- `phase status --json` exposes `projected_execute_gate_valid = (phase == "execute" && approved == true && approved_at >= execute_attempt_started_at)` and a separate `can_enter_execute` value while still in `plan`. Weak agents must read these booleans rather than infer from prose.
- This is a hard-gate at `phase set`, not advisory. Lands in slice 3 alongside the exit 8 work.

### 3.5 `phase autopilot start | stop` (NEW verb — Round-2 BLOCK fix)

Single CLI surface that **slash commands invoke** to mutate `execution_mode`:

```
harness phase autopilot start --phase <slug> [--mode phase|chain] [--budget shell_invocations=N] [--allow-network]
harness phase autopilot stop  [--reason <text>]
harness phase next-pending                    # NEW Round-4 — print next roadmap phase slug, no mutation
harness fsd-run-phase [<slug>]                # adapter-safe wrapper; validates args then calls autopilot start
harness fsd-run-all                           # adapter-safe wrapper; selects next-pending then calls autopilot start --mode chain
```

- `start`: atomically validates that the named phase exists in roadmap, **populates state autopilot identity fields** (`autopilot_run_id` = new uuid4, `autopilot_mode`, `autopilot_phase_slug`, `autopilot_start_entry_hash` = hash of this audit entry, `cli_budgets_remaining`, `autopilot_allow_network`), sets `execution_mode`, audits `verb=phase.autopilot.start` with `mode`, `phase_slug`, `budgets`, `allow_network`, `allow_network_by_source`. Provenance for caller: TTY human proof OR cryptographically verified CI predicate (§3.5.1). Env pairs alone never authorize.
- `stop`: clears all autopilot identity fields, sets `execution_mode=manual`, audits `verb=phase.autopilot.stop` with reason. Idempotent.
- `next-pending`: returns the next roadmap phase whose state is not `done` — used by `/fsd-run-all`. Pure read; no mutation; no lock contention.

**`--allow-network` provenance**: audits `allow_network_by_source` ∈ `{"cli_tty_human", "ci_oidc_verified"}`. Slash-command Markdown files (`.{roo,opencode}/commands/fsd-run-*.md`) MUST NOT contain `--allow-network` (grep-gate enforced). Agents that try to pass `--allow-network` themselves are rejected unless the same TTY human proof or cryptographically verified CI predicate used for `phase autopilot start` succeeds. `HARNESS_ALLOW_NETWORK=1` alone is input metadata, not authorization.

- Slash command Markdown files MUST call only the cross-platform wrapper verbs (`harness fsd-run-phase` / `harness fsd-run-all`). Shell snippets, command substitution, `sed`, `grep`, `set -eu`, and direct `harness phase autopilot start` calls are forbidden in adapter Markdown. The wrappers own slug parsing, `next-pending`, and autopilot start semantics.

**Adapter command contract (Round-6 — core-neutral wrapper model)**:

Empirical: read of `.opencode/commands/{discuss,plan,execute,done}.md` (existing 4 files) found **zero** positional substitution tokens (`$ARGUMENTS`/`$1`/`{1}`). OpenCode does not support positional substitution in command bodies. Core stays neutral by exposing CLI wrappers; adapter Markdown only tells the agent which wrapper to invoke.

| Aspect | Contract |
|---|---|
| Canonical slug regex | `^[a-z0-9][a-z0-9-]{0,63}$` — CLI rejects non-matching with exit 2. |
| Roo `/fsd-run-phase <slug>` | Adapter passes `$ARGUMENTS` to `harness fsd-run-phase "$ARGUMENTS"` if available. Wrapper behavior: empty → `next-pending`; single-token + regex match → use; multi-token → exit 2; regex mismatch → exit 2. |
| OpenCode `/fsd-run-phase` | **No-arg form only** (positional support absent). Adapter runs `harness fsd-run-phase` with no argument. Body MUST instruct agent to ignore any trailing tokens after `/fsd-run-phase` in the user message. **`state.current_phase` fallback DELETED.** Negative smoke (S13): `/fsd-run-phase phase-x` in OpenCode → wrapper receives no arg, `autopilot_phase_slug == next-pending result` (NOT `"phase-x"`); transcript contains the no-args acknowledgement. |
| Cross-adapter parity | Both adapters route through `next-pending` when no arg supplied. Only Roo additionally honors per-slug positional. OpenCode positional support deferred (out-of-scope OOS-OC-POS, §10). |

Exact command bodies are pinned in §4.3a/b and §4.4a/b below.

Functional smoke (slice 13): split by adapter. Roo asserts `/fsd-run-phase phase-x` causes `state.autopilot_phase_slug == "phase-x"`, `/fsd-run-phase` no-arg uses `next-pending`, and `/fsd-run-phase phase X` rejects before mutation. OpenCode asserts `/fsd-run-phase` no-arg uses `next-pending`, and `/fsd-run-phase phase-x` is a negative positional case: trailing tokens are ignored by the command body, wrapper receives no arg, and `state.autopilot_phase_slug == next-pending result`.
- Lives in the §9 slice plan as a new slice (**7-prep**, before 8a — Round-3 fix for slice-id inconsistency) — must land before the slash-command slices can be tested.

**Round-3 BLOCK fix — Windows containment enforcement at THIS entrypoint**:

`phase autopilot start` itself (not `harness preflight --autopilot`) detects Windows and rejects with exit code 11 (`windows_containment_degraded`) unless one of:
- `--accept-degraded-windows-containment` flag passed (audits `network_guard_posture="windows_audit_guard_degraded", accepted_by_caller=true`), OR
- `--allow-network` flag passed (containment is then irrelevant; audits `allow_network=true`).

`harness preflight --autopilot` remains as an advisory check, but the hard-gate is at `phase autopilot start` so a user/agent skipping preflight cannot enter degraded autopilot silently.

**Round-3 BLOCK fix — `HARNESS_AUTOMATION` is authorization, NOT state**:

`HARNESS_AUTOMATION=chain` in CI grants permission to **invoke** `harness phase autopilot start --mode chain`. That invocation writes `state.execution_mode = chain_autopilot` under the lock and emits `verb=phase.autopilot.start, automation_source=env`. After that, **every** transition validator reads `state.execution_mode` from the locked state file ONLY — env is no longer consulted for phase decisions. Audit entry for each transition records `state_source=lock` to make this provable forensically.

This eliminates the dual-source-of-truth ambiguity. Env grants permission to acquire state; state alone gates transitions.

### 3.3 Drop `--chain` / `--auto` flags

Skill/rule text already references these but no CLI consumes them. Removal path:
- v0.7.0: flags accepted at argparse level only to produce a deterministic halt. Emit exit 13 `deprecated_flag`, stderr `Fix: run /fsd-run-phase or /fsd-run-all`, and append `verb=cli.deprecated_flag, args={"flag":"--chain"|"--auto"}` to audit log. Never continue execution after these flags; weak agents must see a single replacement command.
- v0.8.0: remove entirely.
- Skill/rule files updated in v0.7.0 to remove all references (manifest reconciliation handles file replacement — see §6).

### 3.4 Exit codes

| Code | Meaning |
|---|---|
| 0 | OK |
| 2 | invalid transition (ADR-001) — unchanged |
| 3 | session lock contention — unchanged |
| 4 | scope violation — unchanged |
| 5 | unparseable state — unchanged |
| 6 | provenance mismatch — formerly only for approve-in-done, now also for `--by` no-match |
| 7 | non-interactive context with no env override (kept as documented exit; rarely triggered now since we no longer rely on TTY) |
| 8 | `phase approve` invoked while `execution_mode != manual` (NEW — "agents do not approve") |
| 9 | stale or mismatched autopilot run identity (NEW Round-3; no checkpoint/resume semantics) |
| 10 | audit chain or state trust verification failed (NEW Round-3/Round-6) |
| 11 | Windows containment degraded; pass `--accept-degraded-windows-containment` or `--allow-network` (NEW Round-3) |
| 12 | git repo required for autopilot/chain operations (NEW Round-4 — no-git mode §7.5) |
| 13 | deprecated flag (`--chain` / `--auto`) halted with replacement command |
| 14 | Crash recovery undecidable; human action required (NEW Round-4 — §3.8). Also reused for `audit_partial_write` (Round-7) — sub-reason field disambiguates. |
| 15 | `release_trust_invalid` (§6) — `tag_signature_invalid`, `trust_downgrade_refused`, `target_manifest_corrupted`, `allowed_signers_outside_repo` (Cycle-1 fix: moved from 17 which is reserved for human_action_required). |
| 16 | `chain_start_dirty_tree` — chain mode rejected dirty working tree (Round-4 §7.5; **Round-7 BLOCK fix Coherence E-34** — now canonical). |
| 17 | human action required; no shell-safe `harness next --shell` output (kept — distinct from release-trust exit 15). |
| 18 | `no_action_during_autopilot` — `harness next` printed advisory while autopilot active; not an error (Round-7 BLOCK fix Coherence P1-6). |

---

## 4. Slash commands

### 4.1 Naming (post-review)

To eliminate prefix collision and tab-completion confusion:

| Old (rejected) | New |
|---|---|
| `/fsd-phase` | `/fsd-run-phase` |
| `/fsd-chain-phase` | `/fsd-run-all` |

The existing `/fsd-phase` router file in `.roo/commands/` gets renamed in v0.7.0 (manifest tracks the rename via `removed_in_v0.7.0`).

### 4.2 Default (no slash command, plain conversation)

`state.execution_mode = manual`. Agent reads state, sees `manual`, stops at every phase boundary, tells the user the exact `harness phase approve --by <email>` (or `harness phase set <next>`) command to run. Agent NEVER runs `phase approve` itself.

If the agent fails to obey and runs `phase approve` anyway (Round-3 simplified):
- Agent-spawned subprocess has piped stdin → `os.isatty(stdin)` is False → **exit 6 `non_tty_approval_blocked`** before any other check. There is no env or flag to bypass.
- Even if an agent could somehow attach a TTY, in autopilot mode exit 8 fires.
- Agent surfaces the error; user becomes aware.

### 4.3 `/fsd-run-phase <phase-slug>`

Sets `state.execution_mode = phase_autopilot`. Agent cascades through the L3 lifecycle for the named phase only.

Hard-stop conditions (any one halts the cascade and reverts to `manual`):
- `verification` command non-zero exit
- `allowed_paths` violation by any harness-mediated write or transition. Raw adapter `Edit`/`Write` tools remain outside the v0.7 control plane (§5) and are not claimed as hard-stopped.
- ADR-001 transition rejection (see §3.6 — extended to enforce `execution_mode` requirement on cascading transitions)
- Per-phase budget exceeded:
  - **Shell invocations**: ≤ 50 (configurable via `phase autopilot start --budget shell_invocations=N`)
  - **Wall-clock**: ≤ 5 minutes — **enforcement clarification**: not OS signal-based. Implemented as a `time.monotonic()` check polled between tool-call boundaries inside the CLI; works on POSIX and Windows alike (no `SIGALRM`). Documented as "between-tool-call wall-clock", not "interrupt-driven."
  - **File mutation operations**: ≤ 100 files touched
- Network deny-list breach (see §5).

On hard-stop: `state.execution_mode` set to `manual`; audit `verb=phase.autopilot.halt` with `halt_reason`; user manually `phase reopen` or `phase approve` to resume.

At successful `phase set done`:
- If `execution_mode == phase_autopilot`: restored to `manual` automatically.
- If `execution_mode == chain_autopilot`: **NOT** restored (Round-2 BLOCK fix — the chain driver retains autopilot for the next phase; auto-restore would race the cascade). The chain driver itself flips to `manual` at the final phase done, on hard-stop, or at `--max-phases` ceiling.

### 4.3a `.roo/commands/fsd-run-phase.md` (exact body — Round-5)

````markdown
---
description: Run a single phase end-to-end via the canonical phase gate (autopilot, mode=phase)
argument-hint: [phase-slug]
mode: orchestrator
---

`/fsd-run-phase` runs ONE phase under `execution_mode=phase_autopilot`. For chaining, use `/fsd-run-all`.

Run exactly:

`harness fsd-run-phase $ARGUMENTS`

Do not pass `--allow-network`. Do not run shell snippets or parse the slug yourself; the CLI wrapper validates `$ARGUMENTS`, resolves empty input through `next-pending`, starts `phase_autopilot`, and prints the selected phase.

After start, follow the phase lifecycle in order:
1. Run `harness status` and confirm `Execution mode: phase_autopilot`.
2. Drive the selected phase through discuss/plan/execute using the owning implementation mode.
3. Before code execution, verify `harness status --json` reports `can_enter_execute=true` or stop and surface the `Fix:` line.
4. Run the phase verification commands.
5. Run `harness phase set done`.
6. On any non-zero exit, run `harness status`, surface `Halt diary` and `Next action`, then stop. Do not retry or recursively invoke `/fsd-run-phase`.
````

### 4.3b `.opencode/commands/fsd-run-phase.md` (exact body — Round-5)

````markdown
# fsd-run-phase

This command takes NO positional argument under OpenCode (positional substitution unsupported — empirical finding). Ignore any tokens that appear after `/fsd-run-phase` in the user message.

Run exactly:

`harness fsd-run-phase`

Do not pass `--allow-network`. Do not run shell snippets. Do not parse or forward trailing tokens; OpenCode positional substitution is unsupported, so the CLI wrapper must receive no slug and will choose `next-pending`.

After start, follow the phase lifecycle in order:
1. Run `harness status` and confirm `Execution mode: phase_autopilot`.
2. Drive the selected phase via `.opencode/commands/{discuss,plan,execute,done}.md`.
3. Before code execution, verify `harness status --json` reports `can_enter_execute=true` or stop and surface the `Fix:` line.
4. Run the phase verification commands.
5. Run `harness phase set done`.
6. On any non-zero exit, run `harness status`, surface `Halt diary` and `Next action`, then stop.
````

### 4.4 `/fsd-run-all` — chain mode (Model B simplified)

Sets `execution_mode = chain_autopilot`. **No checkpoint, no `chain --resume`, no `chain --abort`, no `last_good_commit_sha`, no commit-per-phase model.** Model B: best-effort cascade; on halt, hand off to manual.

- **`--max-phases-attempted N`** (default **3**) — caps automatic phase entries. Semantics: halts AFTER N phases enter execute, regardless of completion. With 3-phase roadmap and N=3, all three complete.
- **Heartbeat** every phase boundary, written to two sinks: (a) stderr line, (b) append to `.harness/heartbeat.log`. S13 smoke verifies both sinks on Roo and OpenCode.
- All `/fsd-run-phase` budgets apply per phase.
- **Halt → manual handoff (§5.3 Round-5)**: any halt reverts `execution_mode → manual`, populates halt diary fields in state, writes audit. User runs `harness status` to see diary, then continues with manual commands.

### 4.4a `.roo/commands/fsd-run-all.md` (exact body — Round-5)

````markdown
---
description: Chain roadmap phases under chain_autopilot until next-pending is empty
argument-hint:
mode: orchestrator
---

`/fsd-run-all` takes NO positional argument. First phase from `next-pending`.

Run exactly:

`harness fsd-run-all`

**Chain-driver responsibilities (agent — NOT shell loop)**:

1. Run `harness status --json` and confirm `.execution_mode == "chain_autopilot"`. If not, surface the `Fix:` line and stop.
2. Drive current phase to done. Honor every halt condition.
3. `harness phase set done` → `harness phase next-pending`.
4. Empty result → `harness phase autopilot stop` and exit.
5. New slug → `harness phase set <slug>` and loop to 2. **Do NOT recursively invoke `/fsd-run-all`.**
6. After every CLI call, run `harness next --json` and read `requires_human`. If `true`, surface the human-readable `command` to the user; do NOT execute it. Stop the chain.

Halt on ADR-001 reject, approve exit 8, audit-chain break, budget exhausted. On halt: `execution_mode` flips to manual; halt diary populated; report and stop.
````

### 4.4b `.opencode/commands/fsd-run-all.md` (exact body — Round-5)

````markdown
# fsd-run-all

This command takes NO positional argument under OpenCode. Ignore any trailing tokens.

Run exactly:

`harness fsd-run-all`

**Chain-driver responsibilities (agent — NOT shell)**:

1. Run `harness status --json` and confirm `.execution_mode == "chain_autopilot"`. If not, surface the `Fix:` line and stop.
2. Drive phase via `.opencode/commands/{discuss,plan,execute,done}.md`.
3. `harness phase set done` → `harness phase next-pending`.
4. Empty → `harness phase autopilot stop`; exit.
5. New slug → `harness phase set <slug>`; loop. **Never re-invoke `/fsd-run-all`.**
6. After every CLI call, run `harness next --json` and read `requires_human`. If `true`, surface the human-readable `command` to the user; do NOT execute it. Stop the chain.

Halt: report and stop. Manual handoff per §5.3.
````

### 4.5 Empty-bucket carve-out (Round-2 BLOCK fix — scope narrowed)

Fresh install (no `.scratch/phase-state.json` yet): **only the literal `None → discuss` transition** is exempt from the approval gate. Once state exists, every subsequent transition follows normal `manual`/autopilot rules. Specifically:
- Phase 1's `plan → execute`, `execute → done` require either explicit `phase approve` (manual) or an active autopilot context (slash-command).
- Fresh install + `/fsd-run-all` is NOT a wildcard — the carve-out covers exactly one transition; the remainder of phase 1 and all of phases 2..N require the chain_autopilot context (whose entry was itself logged via `harness phase autopilot start`).

Regression test (slice 1 + slice 9a/9b): fresh install + `/fsd-run-all` must produce audit entries with `confirmation_kind=cascade_chain_autopilot` for every transition after the first, NOT a single `verb=phase.empty_bucket` for all of them.

Explicitly documented in `workflow-planning-hydration` SKILL.md.

---

## 5. Best-effort guards for autopilot modes

**Round-4 BLOCK fix #10 — enforcement reality**: budgets and filesystem fences can only be enforced where the harness CLI sits in the call path. Slash commands are Markdown text consumed by the IDE; agent tool calls (Bash, Edit, Write) do NOT necessarily route through the harness. Round-4 reviewer correctly flagged this as a control-plane mismatch.

**Concrete enforcement scope**:
- **CLI-invoked subprocesses** (anything the user/agent runs as `harness ...` → guarded reliably).
- **`autopilot_guard.py` PATH-prepend shim** (POSIX) and `autopilot_guard.ps1` (Windows): wrap the most common deny-listed verbs at the shell level. Bypassable by absolute paths or language runtimes; treat as **best-effort audit guards**, not containment (already conceded in §5.2).
- **Adapter-side wrappers**: NOT present in v0.7. Roo/OpenCode tool calls do not pass through the harness. Therefore:
  - **File mutation operation budget**: enforced only inside `harness` CLI calls (which usually means file changes the agent attributes to `harness ...` operations, not raw editor tool calls). Practical effect: budget catches CLI-driven mass-rewrites; it does NOT cap arbitrary agent edits.
  - **Shell invocation budget**: same — counts only `harness`-invoked subprocesses.
  - **Wall-clock budget**: enforced at every `harness` CLI invocation that is in autopilot mode; checks `state.cli_budgets_remaining.wall_seconds` against `time.monotonic()` since `phase.autopilot.start`. Halts the autopilot if exceeded.
  - **Filesystem fence**: applies to `harness phase set` / `harness phase autopilot *` / `harness phase reopen` writes only. Raw `Edit` tool calls go around it.

Section retitled "best-effort guards" precisely because of this. v0.8 future work: adapter hook (`pre_tool_call` callback) to make budgets and fences true hard-stops — out of scope here. Tracked in §10.

**`containment_layer` field name**: renamed to `network_guard_posture` everywhere in audit (Round-3 leaked "containment" wording). Posture values: `"posix_audit_guard"` | `"windows_audit_guard_degraded"` | `"network_allowed"`.

**Round-3 BLOCK fix**: this entire section was previously titled "Containment". Round-3 reviewer correctly observed that the proposed shims are bypassable on POSIX too (`python -c "import socket"`, `/dev/tcp`, copied `curl`, `openssl s_client`, language-runtime HTTP libs). Renamed to **"best-effort audit guards"** to remove the false safety claim. Real isolation requires a container or network namespace; that is the future `--isolation=container` mode tracked in §10. For v0.7, the guards exist to:
- Detect the simplest deny-listed verbs and audit them (forensic value).
- Refuse trivial-pattern violations so the average weak agent halts rather than fetches arbitrary URLs.
- Make policy decisions visible (audit entries with `verb=autopilot.network.deny`).

They do **NOT** constitute containment. Slash-command Markdown files may not add `--allow-network` autonomously — Round-3 P1 grep-gate addition: `.{roo,opencode}/commands/fsd-run-{phase,all}.md` MUST NOT contain the string `--allow-network`; that flag must come from a human at slash-command invocation time.

### 5.0 Guard subsections (formerly "containment")

### 5.1 Filesystem fence (existing, extended)

SecM2 already refuses symlink targets and escape paths in `prepare_scratch`. Extend to all harness-managed writes during `phase_autopilot` and `chain_autopilot`: every file mutation operation performed by the `harness` CLI MUST resolve to a real path under `cwd` and then satisfy `allowed_paths`. Audit any rejection as `verb=autopilot.fence.deny`. Raw adapter tool calls are not covered until adapter pre-tool hooks exist (§10).

### 5.2 Network deny-list (best-effort audit guard — Round-3 rename)

In autopilot modes, the CLI sets `HARNESS_AUTOPILOT_NETWORK=deny`.

**POSIX (Linux/macOS)**: shim `scripts/lib/autopilot_guard.py` wraps Bash; refuses:
- `curl`, `wget`, `nc`, `ssh`, `scp`, `rsync`
- `git push`, `git pull`, `git fetch`, `git clone`, `git remote update`, `git submodule update --remote`
- `gh`, `glab`

**Windows (PowerShell / cmd.exe — Round-2 BLOCK fix)**: A Bash-only shim is trivially bypassed by `pwsh -Command "Invoke-WebRequest ..."` or `Start-Process curl`. Two-track mitigation:
- **v0.7.0 declared posture**: autopilot modes (`phase_autopilot` / `chain_autopilot`) emit a hard WARN on Windows: "network deny-list is best-effort on Windows; for hard isolation use a Linux container or WSL." `harness preflight --autopilot` exits non-zero on Windows unless `--accept-degraded` is passed.
- **v0.7.0 best-effort**: ship `scripts/lib/autopilot_guard.ps1` (PowerShell profile hook) and PATH-prepend wrapper executables (`curl.cmd`, `gh.cmd`, `git.cmd` shim) inside the harness session's PATH so the most common cases are caught. Audit entries record `network_guard_posture="windows_audit_guard_degraded"` so reviewers can see the degraded posture.
- **Future**: `--isolation=container` mode (out of scope §10) for hard isolation.

**Atomicity contract for the shim**: shim refusal exits non-zero AND audits `verb=autopilot.network.deny, command=<argv>` BEFORE the subprocess call. Cannot be bypassed by piping (`curl ... | bash`) because the shim wraps argv[0].

**File-system `os.path.normpath` vs Windows junctions/reparse points**: SecM2 fence uses `os.lstat(path).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT` on Windows AND `os.path.islink` on POSIX. Junctions and reparse points are refused identically to symlinks.

Override: `phase autopilot start --allow-network` flag at slash-command invocation; logged in audit with `allow_network=true`.

### 5.3 Halt → manual handoff (Round-5 Model B)

**Model B principle**: autopilot interruption is **manual handoff**, not failure. The harness provides no `chain --resume`, no `chain --abort`, no `last_good_commit_sha`, no commit-per-phase auto-creation. On any halt the user takes over with `harness status` and standard manual verbs.

**On halt** (any of: ADR-001 reject, verification non-zero, allowed_paths violation, budget exhausted, network deny breach, manual `phase autopilot stop`):

1. Under the state lock + transaction protocol (§3.8):
   - Set `execution_mode = manual`.
   - Populate **halt diary fields** in state:
     - `last_halt.run_id` = the previous `autopilot_run_id`
     - `last_halt.mode` = previous `autopilot_mode`
     - `last_halt.phase_slug` = `autopilot_phase_slug`
     - `last_halt.last_successful_transition` = e.g. `"phase-02c:plan→execute"`
     - `last_halt.halt_reason` = enum (`adr001_reject`, `verification_failed`, `budget_exhausted`, `network_deny`, `manual_stop`, `crash_recovery`, ...)
     - `last_halt.halt_at_iso` = timestamp
     - `last_halt.suggested_next_command` = e.g. `"harness phase reopen --to plan --reason 'fix X'"` or `"harness phase set discuss"` etc.
   - Clear `autopilot_*` identity fields (run_id, mode, phase_slug, start_entry_hash, budgets, allow_network).
   - Audit `verb=phase.autopilot.halt` with all halt-diary fields.
2. Print halt summary to stderr with the suggested next command.

**User flow after halt**:
- `harness status` prints current phase + halt diary (if recent halt unprocessed) + suggested next command.
- User decides: resume via standard manual verbs (`phase reopen`, `phase set <next>`, `phase approve`), OR start fresh autopilot via `phase autopilot start` (which writes a NEW run_id; old halt diary moves to historical record).
- No automatic re-entry into autopilot from a halt diary.

**Halt diary is read-only documentation, not a resumable checkpoint.** It exists for forensic clarity and to make the next manual command obvious. The diary is cleared (or moved to `last_halt_history[]` capped at last 5) when the user starts a new autopilot run or runs `harness halt-diary clear`.

`phase reopen --to plan` clears `last_halt` because the user has explicitly handled it.

ADR-001 does **not** gain a `failed` substate.

---

## 6. Installed-manifest v2

Existing `installed-manifest.json` tracks installed paths. v2 additions:

| Field | Semantics |
|---|---|
| `harness_version` | exact version string at install time (e.g. `"v0.7.0"`) |
| Per-entry `installed_sha256` | hash at install time |
| Per-entry `current_sha256` | hash at last-known-good state (updated on upgrade) |
| `removed_in_version` | top-level list of paths removed by version (e.g. `[{"path": ".roo/commands/fsd-phase.md", "removed_in": "v0.7.0", "replaced_by": ".roo/commands/fsd-run-phase.md"}]`) |
| `adapters` | list of adapter slugs this manifest covers (`["roo", "opencode"]` or subset). Round-2 BLOCK fix: clarifies that `.harness/install-record.json` and `installed-manifest.json` are **repo-root-scoped, shared across adapters**, not per-adapter. Dual-install in same repo updates both manifest entries against the single record. |

Upgrade reconciliation logic (Round-4 P1 — manifest is audit input, NOT trust root):
- The reconciler **recomputes disk hashes** at upgrade time, NOT trusting `current_sha256` blindly (a repo-local attacker could rewrite both `installed_sha256` and the file to make malicious content appear blessed). The release-bundled manifest's `installed_sha256` (immutable, comes from the harness release tarball) is the trust anchor; repo-local `installed-manifest.json` is treated as audit metadata.
- If recomputed disk hash == release-bundled `installed_sha256`: file is unchanged from install → safe replace.
- If recomputed disk hash != release-bundled `installed_sha256` but == prior `current_sha256` recorded in a previous upgrade: user has not modified since last upgrade → safe replace.
- Else (recomputed hash diverged): file was user-edited; record `user_modified=true`, quarantine the old file to `.harness/conflicts/<path>.<ts>`, install the new file, WARN. **No silent overwrite of user edits.**

Idempotency test (`release_smoke_test` extension): run `init` twice in the same target, diff manifest — must be byte-identical.

### 6.1 `.harness/install-record.json` (Round-4 — gitconfig auto-read, no prompt)

Written by `scripts/install_harness.py` at install. Read by `phase approve` (§3.1) and `phase autopilot start` (§3.5) for identity verification.

Schema:

```json
{
  "harness_version": "v0.7.0",
  "installed_at": "2026-05-17T03:14:15Z",
  "adapters": ["roo", "opencode"],
  "git_present_at_install": true,
  "approvers": [
    {"email": "alice@example.com", "added_at": "2026-05-17T03:14:15Z", "source": "gitconfig_auto"}
  ]
}
```

Install-time behavior (Round-4 — auto-read, single-user model per §10):
- If `git config user.email` returns a value → populate `approvers[0]` with `source="gitconfig_auto"`. **No prompt.**
- If empty AND git repo exists → exit install with a single prompt: "git config user.email is unset. Enter approver email:" (TTY-only; install must run from a real terminal regardless). Audit `source="install_prompt"`.
- If no git repo at all → see §7.5 no-git mode. Install remains TTY-only and must collect exactly one approver email via `--approver <email>` or a one-time install prompt. `approvers=[]` is invalid in v0.7 because approver-management verbs are out of scope (§10).
- File mode: `0o600` on POSIX; on Windows the bits are stored but the file is non-secret (it's an email, not a credential). NTFS ACL hardening is optional and not part of v0.7.

Multi-user collaboration is **out of scope** (§10) — `approvers` list is single-entry in practice. Field-level structure leaves room for future multi-user without schema migration.

---

## 7. CI / release-smoke contract

CI and any other non-interactive caller invokes the autopilot CLI verb explicitly. Cryptographically verified CI provenance grants permission; env vars provide candidate metadata only. State alone gates transitions after the start entry is written.

Contract (concrete invocation):

```sh
export HARNESS_AUTOMATION=chain
export HARNESS_BY_TRUST=<bot-email>
# Provider-specific OIDC/JWT variables must also be present and verifiable.
harness phase autopilot start --mode chain --phase "$(harness phase next-pending)"
# ... agent now runs the cascade; every transition reads state under lock ...
```

Semantics:
- Env vars do **not** authorize by themselves. They are validated inputs to the CI proof in §3.5.1.
- A verified CI proof authorizes the `phase autopilot start` invocation only.
- That invocation writes autopilot identity fields (§1.1) into state, audits `verb=phase.autopilot.start` with `automation_source=env`, then exits.
- Subsequent `phase set` / `phase autopilot stop` calls read state under lock ONLY. Env is not re-consulted for transitions. Audit each transition with `state_source=lock`.

**Negative smoke test (Round-4 mandatory)**: `release_smoke_test.py` must include a case where `HARNESS_AUTOMATION=chain` is set but `phase autopilot start` is NOT called; a subsequent `phase set plan` MUST fail with exit 2 (no autopilot context in state). This pins env-as-state-elimination as a tested invariant.

Grep-gate (in `release_smoke_test.py`) additions:
- Forbid the strings `--chain`, `--auto` in any installed artifact (catches doc-fiction regressions).
- Forbid `--yes` (catches accidental reintroduction).
- Forbid `automation_mode` in any newly written skill/rule text (forces use of `execution_mode`).
- Forbid `--allow-network` in any `.{roo,opencode}/commands/*.md`.
- Forbid shell-script-only constructs in adapter command Markdown: fenced `sh` blocks, `set -eu`, `sed`, `grep`, command substitution, and direct `harness phase autopilot start`.
- Forbid alternative launchers in slash-command bodies: `python3 scripts/harness.py`, `python scripts/harness.py`, `py scripts/harness.py`, and `scripts/show_phase_status.py`.
- **Require**: `.roo/commands/fsd-run-phase.md` and `.opencode/commands/fsd-run-phase.md` contain literal `harness fsd-run-phase`. Same for `fsd-run-all.md` with literal `harness fsd-run-all`.
- **Require**: backslash `\` not present in any path field of `installed-manifest.json` (POSIX-canonical paths).

---

### 7.5 No-git mode (Round-4 — user-requested)

The harness is git-agnostic at the state/audit/manifest layer (those are JSON files). Under Model B (Round-5) chain mode does NOT auto-commit, does NOT track `last_good_commit_sha`, and does NOT offer `chain --resume`/`--abort`. Git is no longer a hard dependency for chain mode itself; however, `git status --porcelain` is still consulted at `phase autopilot start --mode chain` to refuse dirty trees (exit 16 `chain_start_dirty_tree` — user controls their own commits/stashes).

Behavior matrix:

| Feature | Git present | Git absent |
|---|---|---|
| Install | OK | OK if a TTY human supplies one approver email via `--approver <email>` or install prompt (`install-record.git_present_at_install=false`, WARN) |
| `phase set` | OK | OK |
| `phase approve` (manual mode) | OK (gitconfig discovery, install-record authority) | OK if `--by` matches install-record approver; else exit 6 with hint |
| `phase reopen` | OK | OK |
| `phase autopilot start --mode phase` | OK | OK |
| `phase autopilot start --mode chain` | OK if working tree clean (exit 16 if dirty) | OK (no clean-tree check); user owns rollback if anything goes wrong |

`harness verify --audit` works in both modes.

Effect: a no-git project gets the **core safety value** (human-only approve, agent-can't-cascade) while losing the cascade rollback safety net. That trade-off is made explicit at the entrypoint, not silently degraded.

### 7.1 Release matrix

S13 release-gate per row:

| OS | Python | Launcher | Shell | Required? |
|---|---|---|---|---|
| `ubuntu-latest` | 3.11 | `python3` | bash | release-gate |
| `ubuntu-latest` | 3.12 | `python3` | bash | release-gate |
| `macos-latest` | 3.11 | `python3` | zsh | release-gate |
| `macos-latest` | 3.12 | `python3` | zsh | release-gate |
| `windows-latest` | 3.11 | `py -3.11` | pwsh | release-gate |
| `windows-latest` | 3.12 | `py -3.12` | pwsh | release-gate |
| `windows-latest` | 3.12 | `py -3.12` | cmd | release-gate |
| `ubuntu-latest` | 3.11 | `python3` | zsh | nice-to-have |
| `windows-latest` | 3.12 | `py -3.12` | Git Bash | nice-to-have |
| `macos-latest` | 3.12 | `python3` | bash | nice-to-have |

S10d (Windows degraded) counts as passing if at least one Windows pwsh row green; cmd is allowed `network_guard_posture: degraded` without failing.

S13 implementation MUST update `.github/workflows/release.yml` from the current single Ubuntu release job to a `strategy.matrix` that covers every `release-gate` row above. Each row must:
- install the requested Python version via `actions/setup-python` or the platform-native launcher under test,
- run the row-specific launcher/shell command,
- publish a row-named required check,
- upload smoke logs and release evidence artifacts even on failure.

## 8. ADRs required before code lands

1. `docs/adr/2026-05-17-approver-provenance-and-execution-mode.md` — Approver provenance and `execution_mode` promotion. Identity binding, install-record authority, `phase approve` exit 8 rule, `phase reopen` verb, `automation_mode` deprecation.
2. `docs/adr/2026-05-17-audit-canonicalization-locking-and-state-trust.md` — Audit canonicalization, locking, and state trust. RFC 8785 sorted keys, UTF-8, LF, what gets hashed, state trust preflight (§2.6), regression fixture format.
3. `docs/adr/2026-05-17-autopilot-guards-and-manual-handoff.md` — Autopilot guards and Model B manual handoff. Slash command wrapper → execution_mode mapping, network deny-list, filesystem fence extension, capability-neutral budget mechanism, halt diary/manual handoff. No checkpoint, no resume, no abort.

All three ADRs MUST exist with `Status: Accepted` before any code slice begins. `scripts/verify_adrs_accepted.py` is part of `S00-adr-prep` and CI must fail if any required ADR is missing or has a different status.

---

## 9. Slice plan (TDD, conductor-driven, ~16 slices)

Each slice is RED → GREEN → review (3-persona) → fix → commit.

**Stable slice IDs**: each slice has a stable identifier; reordering or renumbering never changes an existing slice's id. `depends_on` is explicit. `verify` is the single command that must pass for the slice to be considered done.

| ID | Title | depends_on | verify |
|---|---|---|---|
| `S00-adr-prep` | Land the three real ADR files in §8 as **Status: Accepted** and add `scripts/verify_adrs_accepted.py`. | — | `python scripts/verify_adrs_accepted.py docs/adr/2026-05-17-approver-provenance-and-execution-mode.md docs/adr/2026-05-17-audit-canonicalization-locking-and-state-trust.md docs/adr/2026-05-17-autopilot-guards-and-manual-handoff.md` |
| `S00.5-launcher` | Cross-platform `harness` console-script via `pyproject.toml [project.scripts]`. Full adapter command sweep replaces executable `python3 scripts/harness.py` / `python scripts/harness.py` / `py scripts/harness.py` / `scripts/show_phase_status.py` references with console-script usage before grep-gate runs. | `S00` | `python scripts/smoke/verify_launcher_matrix.py && python scripts/smoke/grep_gate_stale_terms.py --launcher-only` |
| `S01-schema` | State schema: `execution_mode`, `autopilot_*` identity fields, `execute_attempt_started_at`, `draft_verification`, `draft_allowed_paths`, `cli_budgets_remaining`, `last_halt`, `last_halt_history`. `automation_mode` migration. O_EXCL lock + transaction journal skeleton (§3.7, §3.8). State trust preflight (§2.6). `scripts/lib/durable_fs.py`. | `S00.5-launcher` | `pytest tests/phase_state/ tests/durable_fs/ tests/phase_lock/test_invariants.py tests/phase_state/test_state_trust_preflight.py -q` |
| `S02-approve-provenance` | `phase approve` TTY gate + human-presence proof (§3.1.1 nonce default) + gitconfig auto-read + `install-record.approvers` match. Env identity removed from this verb. | `S01` | `pytest tests/phase_approve/ -q` |
| `S03-stale-approval` | `(plan→execute)` validator requires fresh human approval before code execution; `(execute→done)` validator requires `approved_at >= execute_attempt_started_at`. ADR-001 extension for `execution_mode != manual`. | `S01, S02` | `pytest tests/phase_set_execute/ tests/phase_set_done/ -q` |
| `S04-reopen` | `phase reopen` (TTY-only). Resets `execute_attempt_started_at` (target == plan). Moves `verification`/`allowed_paths` → `draft_*`. Halts active autopilot, populates `last_halt`. | `S01` | `pytest tests/phase_reopen/ -q` |
| `S05-override` | `--override-identity --reason` + sanitization. | `S02` | `pytest tests/phase_approve/test_override.py -q` |
| `S06-audit-chain` | `schema_version: 2`, `confirmation_kind`, per-entry hash chain (§2.2), rotation seam, `harness verify --audit`, crash recovery matrix tests (§3.8). | `S01` | `pytest tests/audit/test_chain_verifier.py tests/audit/test_rotation_seam.py tests/crash/test_recovery_matrix.py -q && harness verify --audit --fixture tests/fixtures/audit/mixed_v1_v2_rotation_ok` |
| `S07-deprecation` | `--chain`/`--auto` halt-with-replacement-command (exit 13) + `verb=cli.deprecated_flag` audit. | `S01` | `pytest tests/cli/test_deprecated_flags.py -q` |
| `S07-prep-autopilot-cli` | `phase autopilot start | stop`, `phase next-pending`, `harness fsd-run-phase`, and `harness fsd-run-all` (§3.5). CI provenance predicate (§3.5.1) rejects env-only spoofing. Active-autopilot exit 15 (§3.5.2). Windows degraded exit 11 here. `--allow-network` source check. | `S01, S06` | `pytest tests/phase_autopilot/ tests/ci_provenance/ tests/fsd_wrappers/ -q` |
| `S08a-slash-roo-runphase` | `.roo/commands/fsd-run-phase.md` rename + exact prompt body (§4.3a). Roo skill/rule text sweep. | `S07-prep-autopilot-cli` | `python scripts/smoke/grep_gate_slash_rename.py && python scripts/release_smoke_test.py --adapter roo --case run-phase && python scripts/release_smoke_test.py --adapter roo --case run-phase-empty-arg && python scripts/release_smoke_test.py --adapter roo --case run-phase-multi-arg-fail` |
| `S08b-slash-opencode-runphase` | `.opencode/commands/fsd-run-phase.md` NET-NEW (§4.3b). No-arg form only; no positional fallback. | `S07-prep-autopilot-cli` | `python scripts/smoke/grep_gate_slash_rename.py && python scripts/release_smoke_test.py --adapter opencode --case run-phase && python scripts/release_smoke_test.py --adapter opencode --case run-phase-missing-positional-negative` |
| `S09a-slash-roo-runall` | `.roo/commands/fsd-run-all.md` rename + exact prompt body (§4.4a). | `S07-prep-autopilot-cli` | `python scripts/release_smoke_test.py --adapter roo --case run-all && python scripts/release_smoke_test.py --adapter roo --case run-all-empty-roadmap` |
| `S09b-slash-opencode-runall` | `.opencode/commands/fsd-run-all.md` NET-NEW (§4.4b). | `S07-prep-autopilot-cli` | `python scripts/release_smoke_test.py --adapter opencode --case run-all && python scripts/release_smoke_test.py --adapter opencode --case run-all-empty-roadmap` |
| `S10a-budgets` | `cli_budgets_remaining` decrement per harness-mediated CLI call using capability-neutral keys (`shell_invocations`, `file_mutation_ops`, `wall_seconds`). `time.monotonic()` between-call wall-clock. Halt → §5.3 manual handoff. | `S07-prep-autopilot-cli` | `pytest tests/autopilot/budgets/ -q` |
| `S10b-fs-fence` | **Harness-managed write fence only** (Round-5 P1 rename). Race-safe open POSIX (O_NOFOLLOW + dir_fd) + Windows (`CreateFileW` + `GetFinalPathNameByHandle`) per §5.1.1. | `S07-prep-autopilot-cli` | `pytest tests/autopilot/fence/ tests/safe_open/ -q` |
| `S10c-net-posix` | `autopilot_guard.py` shim (best-effort audit guard). `verb=autopilot.network.deny`. | `S07-prep-autopilot-cli` | `pytest tests/autopilot/network/test_posix_guard.py -q && python scripts/release_smoke_test.py --case net-deny-curl-posix` |
| `S10d-net-windows` | Windows degraded + `autopilot_guard.ps1` + PATH-prepend wrappers. `network_guard_posture` audit field. | `S07-prep-autopilot-cli` | `pytest tests/autopilot/network/test_windows_degraded.py -q` (Windows CI rows per §7.1) |
| `S11-halt-diary` | **Round-5 Model B collapse of S11a/b/c**: write `last_halt` diary on any autopilot halt; clear on autopilot restart or `harness halt-diary clear`. NO checkpoint, NO `chain --resume`, NO `chain --abort`. | `S07-prep-autopilot-cli, S06` | `pytest tests/halt_diary/ -q && python scripts/release_smoke_test.py --case halt-handoff-flow` |
| `S12-manifest` | `installed-manifest.json` v2 + Round-4 reconciliation (recompute disk hashes vs release-bundled trust root). Manifest hash chain. Quarantine user-modified deprecated paths. | `S00.5-launcher` | `pytest tests/install/test_manifest.py -q` |
| `S13-smoke` | `release_smoke_test.py`: env-only spoof must NOT cascade; OIDC/JWT proof required; grep-gate; functional smoke 8a/8b/9a/9b/Windows-exit-11/`phase autopilot stop`/deny-listed verb/halt-handoff. OS/Python matrix per §7.1. Also updates `.github/workflows/release.yml` to run every release-gate row with row-named checks and uploaded smoke logs. | all above | `python scripts/release_smoke_test.py --release` (per §7.1 matrix row in CI) |
| `S14-sweep` | Residual text sweep: `automation_mode` / `--chain` / `--auto` / `HARNESS_HUMAN` / `containment_*` / `last_good_commit_sha` / `chain --resume` / `chain --abort` / `autopilot_budgets_remaining` / alternative launchers in slash commands. | all above | `python scripts/smoke/grep_gate_stale_terms.py` |
| `S15-status-next` | **Round-5 UX promotion from v0.8**: `harness status` + `harness next` verbs (§3.9). `/fsd-status` slash for both adapters. Required for Model B handoff usability. | `S11-halt-diary` | `pytest tests/cli/test_status.py tests/cli/test_next.py -q && python scripts/release_smoke_test.py --case status-after-halt && python scripts/release_smoke_test.py --case fsd-status-roo --adapter roo && python scripts/release_smoke_test.py --case fsd-status-opencode --adapter opencode` |
| `S16-error-fix-standard` | **Round-5 UX promotion**: every non-zero exit prints `Fix: <command>` line. Cross-cutting; touches every exit path. | `S15-status-next` | `python scripts/smoke/verify_fix_lines.py` |

Reordering note: slices `S08a..S09b` independent (may parallel); `S10a..S10d` similar; `S11-halt-diary` no longer chained sub-slices. `S15`+`S16` are UX promotions from v0.8 needed for Model B usability.

### 9.1 Pinned fixture paths

| Path | Description | Used by |
|---|---|---|
| `tests/fixtures/audit/mixed_v1_v2_rotation_ok/audit.log` + `audit.log.1` | Current-tip v2 chained on v1; rotation seam well-formed. | S06 |
| `tests/fixtures/audit/tampered_tail.jsonl` | Last entry mutated; verifier flags. | S06 |
| `tests/fixtures/audit/missing_rotation_gap.jsonl` | Gap in `seq_global` across rotation. | S06 |
| `tests/fixtures/audit/rotation_seam_mismatch.jsonl` | Seam hash mismatch. | S06 |
| `tests/fixtures/audit/duplicate_seq_global.jsonl` | Duplicate global seq. | S06 |
| `tests/fixtures/audit/bom_in_audit/audit.log` | UTF-8 BOM prefix; reader exits 5. | S06, S14 |
| `tests/fixtures/crash/01_quiescent/`, `02_orphan_tmp/`, `03_state_accepted_audit_durable/`, `04_tmp_present_audit_durable/`, `05_journal_only_before/`, `06_journal_and_tmp_before/`, `07_roll_forward/`, `08a_finalize_no_tmp/`, `08b_finalize_with_tmp/`, `09_undecidable_state_hash/`, `10_corrupt_journal_tmp/`, `11_corrupt_journal_only/`, `12_audit_partial_write/` | Full §3.8 recovery matrix (11 baseline rows + Round-7 partial-write row 12). Each directory contains pre-crash `state.json`, `state.json.tmp` (when applicable), `state.json.journal` (when applicable), `audit.log`. Round-7 BLOCK fix Release D-24. | S06 |
| `tests/fixtures/lock/stale_owner_alive/` | Owner PID alive; never auto-recover. | S01 |
| `tests/fixtures/lock/recovery_mutex_held/` | Recovery mutex present; primary acquire must wait. | S01 |
| `tests/fixtures/manifest/disk_hash_diverged_from_release/` | install-record vs release-bundled mismatch. | S12 |
| `tests/fixtures/manifest/install_record_tampered_approvers/` | Approvers post-install mutation. | S12 |
| `tests/fixtures/manifest/install_record_bom/` | BOM in install-record. | S12, S14 |
| `tests/fixtures/state/v061_no_execution_or_automation/` | v0.6.1 state with both fields absent; migrates to `execution_mode=manual`, writes exactly one `migrate.state_v2`. | S01 |
| `tests/fixtures/state/v070_automation_manual_only/` | Legacy `automation_mode=manual`; read migration is idempotent and preserves user fields. | S01 |
| `tests/fixtures/state/v070_automation_chain/` | Legacy `automation_mode=chain`; migrates to `phase_autopilot` only through documented compatibility path. | S01 |
| `tests/fixtures/state/v070_automation_auto/` | Legacy `automation_mode=auto`; migrates to `chain_autopilot` only through documented compatibility path. | S01 |
| `tests/fixtures/state/tampered_approved_true/` | State hand-edited to `approved=true`; state trust preflight rejects before transition. | S01, S03 |
| `tests/fixtures/state/tampered_chain_autopilot/` | State hand-edited to `execution_mode=chain_autopilot`; state trust preflight rejects before transition. | S01, S07-prep |
| `tests/fixtures/no_git/` | No `.git/`; chain mode still works but no clean-tree check. | S07-prep, S11 |
| `tests/fixtures/windows_degraded/junction_reparse/` | Junction in path; fence refuses. | S10b |
| `tests/fixtures/windows_degraded/network_guard_posture/` | Captured posture audit. | S10d |
| `tests/fixtures/slash/roo_run_phase_empty_arg/` | Empty `$ARGUMENTS` → `next-pending`. | S08a |
| `tests/fixtures/slash/roo_run_phase_multi_arg/` | Multi-token → exit 2. | S08a |
| `tests/fixtures/slash/opencode_no_positional/` | OpenCode trailing token → ignored, no fallback. | S08b |
| `tests/fixtures/halt_diary/recent_halt/` | `last_halt` populated after halt; status surfaces it. | S11, S15 |
| `tests/fixtures/halt_diary/cleared_on_restart/` | New autopilot start clears `last_halt`. | S11 |

---

### 9.2 Release evidence contract

Each slice must leave durable evidence under `.planning/phases/<phase-id>/evidence/<slice-id>/` before it can be marked complete:

| File | Required content |
|---|---|
| `result.json` | `{slice_id, commit_sha, started_at, finished_at, commands:[{cmd, exit_code, os, python, shell}], reviewer_outcome, artifact_paths}` |
| `review.md` | 3-persona review summary, findings, and disposition. |
| `red-green.md` | RED command/output summary, GREEN command/output summary, and any skipped test rationale. |
| `artifacts/` | Smoke logs, CI row logs, generated manifests, and fixture output needed to reproduce the result. |

S13 CI must upload the evidence directory per matrix row. Release approval requires every S00-S16 `result.json` to have `exit_code=0` for its verify command and a non-empty `reviewer_outcome`.

---

## 10. Out of scope (explicit)

- TTY interactive confirmation (rejected by Realist+Hawk review — IDE captures it).
- `--yes` flag (rejected — agent will learn it; no defense holds).
- Per-phase wall-clock timeout enforcement at OS level (deferred; budgets are tool-call counts).
- HMAC-signed audit.log.sig tip pointer + external anchor (Nice-to-have from Hawk; future). Tamper-evidence against repo-local attacker requires this; Round-4 explicitly downgrades the v0.7 claim to "integrity-checked, not signature-tamper-evident".
- **Multi-user collaboration** (Round-4 — explicitly out of scope per user direction). Project model assumption: a single user clones the harness-augmented repo onto one machine and operates it themselves; the harness directory is NOT pushed to a shared remote where multiple humans approve concurrently. Multi-approver list, `harness approver add|remove|list` verbs, git merge driver for `phase-state.json` / `audit.log` — all deferred to a separate future phase. `.harness/install-record.json` `approvers` field uses an array structure so future expansion does not require a schema migration.
- **Adapter-side `pre_tool_call` hook for true budget/fence enforcement** — would make Edit/Write/Bash budgets hard-stops rather than CLI-only counters. Requires upstream adapter API (Roo, OpenCode). Tracked.
- ~~`harness verify --audit` re-walk subcommand~~ — **promoted to in-scope by Round-3** (slice 6).
- `--isolation=container` mode (real network/fs isolation via container/netns). Future.
- **Strong auto-resume / auto-rollback** (`chain --resume`, `chain --abort`, `last_good_commit_sha`, commit-per-phase model) — Round-5 Model B explicitly REMOVES these from scope. Halt → manual handoff (§5.3) replaces them. Cheaper to implement, easier to explain, fits low-reasoning agent model better.
- OOS-OC-POS: OpenCode positional argument support — deferred until OpenCode adds positional substitution to command bodies.
- `harness doctor --repair` for orphan approvals (referenced by Architect; deferred until first real orphan is observed).
- Adopt-existing flow provenance — kept lenient (`provenance: adopted_unverified`) per Hawk recommendation.

---

## 11. Review history (Rounds 1-6, condensed)

Round-7 ledger lives in §21 (active spec content). Earlier rounds collapsed here.

| Round | Personas | Verdict | BLOCK count | Key outcomes | Detailed file |
|---|---|---|---|---|---|
| 1 | Protocol Architect, Low-Reasoning Realist, Ops & Supply-Chain Hawk | BLOCK | 7 convergent | Core principle "Agent never approves" adopted; `--yes` killed; `execution_mode` field; `phase reopen` verb; empty-bucket carve-out; schema_version + hash-chain; CI env contract; Windows TTY/CRLF; manifest v2. | (inline original) |
| 2 | Cross-Platform Compat Hawk, Adapter Integration & Workflow Realist | BLOCK | 7+6 | `os.replace` Windows atomicity; O_EXCL lock mandate; audit+state under same lock; Bash-shim Windows bypass; `phase set done` race; empty-bucket scope; adapter file asymmetry; argument convention; `execution_mode` write path defined; ADR-001 extension; `HARNESS_BY_TRUST` manual-mode hole; gitconfig weakness. | (inline original) |
| 3 | Comprehensive single-persona | BLOCK | 10 | `HARNESS_HUMAN` removed (env forgeable); per-entry audit hash chain; env-vs-state SoT resolved; adapter arg contract; Windows enforce at autopilot start; deny-list relabeled "best-effort audit guard"; lock protocol with owner token + boot_id; checkpoint identity; slice order fixed. | `2026-05-17-phase-gate-hardening-adversarial-review.md` |
| 4 | Comprehensive second-pass (5 sub-lenses) | BLOCK | 10 | §7 env-as-state contradiction resolved; `phase approve` stops consulting `HARNESS_BY_TRUST`; crash-safe transaction §3.8 added; recovery-mutex rewrite §3.7; autopilot identity in state; OpenCode fallback removed; `next-pending` verb; audit chain claim downgraded to "integrity-checked, not signature-tamper-evident"; rotation paragraph rewritten; budget/fence enforcement scope honesty. | `2026-05-17-phase-gate-hardening-second-pass-review.md` |
| 5 | Third-pass + UX consult + Model B pivot | BLOCK | 10 | CI provenance predicate §3.5.1 (5-provider allowlist + OIDC); human-presence primitive §3.1.1 (nonce default); recovery mutex STEP-A ordering; tmp dir durable before audit; `durable_fs.py` ctypes; OpenCode positional empirically verified absent; exact slash bodies pinned §4.3a/b §4.4a/b; runnable verify per slice; `verify_adrs_accepted.py`. **Model B pivot**: removed chain --resume/--abort/checkpoint; added halt diary §5.3. **UX promotion v0.8 → v0.7**: `harness status`/`next` + `Fix:` line standard (§3.9). | `2026-05-17-phase-gate-hardening-third-pass-review.md` |
| 6 | Five expert sub-personas (core neutrality, state-machine, adapter, low-reasoning UX, verification) | BLOCK | 8 | CI authorization no longer env-only (cryptographic attestation required); direct state edits fail closed via §2.6 state-trust preflight; approval moved to execute entry (`plan → execute` requires fresh approval); core no longer leaks adapter tool names (capability-neutral budgets); slash commands became wrapper-only prompts; OpenCode positional contradictions removed; human-only next actions not shell-capturable; release/ADR evidence machine-checkable §9.2. | `2026-05-17-phase-gate-hardening-round6-review-notes.md` |

Conventions: all rounds executed 2026-05-17. Convergent BLOCK reasons across rounds resolved inline in the relevant spec sections. Round-by-round inline `(Round-N BLOCK fix #X)` markers throughout earlier sections trace each finding to its addressing edit.

## 12. Round-7 BLOCK ledger (2026-05-17 — five expert sub-personas)

Five specialized adversarial sub-agents reviewed the Round-6 design: **Authorization/Provenance Hawk**, **Crash-Safety/Concurrency Hawk**, **Adapter/Low-Reasoning Realist**, **Release/Verification Hawk**, **Spec Coherence Inspector**. All five returned BLOCK. User accepted scope (B): apply critical BLOCK fixes; defer pure-polish to in-slice cleanup.

The following sub-sections define the new content introduced by Round-7 fixes; in-place edits elsewhere in the doc cross-reference these IDs.

### 12.1 Out-of-repo audit-tip anchor (R7-BLOCK A-3, A-6, P1-3, B-14)

The §2.6 state-trust preflight, §3.8 crash recovery, and §6.1 install-record integrity all depend on a chain anchor that a repo-local attacker cannot also rewrite. Repo-local audit + state can be edited together to produce a self-consistent forgery; the anchor lives outside the repo.

**Path**:
- POSIX: `~/.harness/audit-tip/<repo-id>.json`, mode `0o600`.
- Windows: `%LOCALAPPDATA%\Harness\audit-tip\<repo-id>.json`, user ACL.

`<repo-id>` is `sha256(canonical_absolute_path_of_repo_root)[:16]`. The full path is recorded in the anchor body so cross-repo replay is detectable.

**Schema**:

```json
{
  "anchor_schema_version": 1,
  "repo_root_canonical": "/Users/.../project",
  "harness_version": "v0.7.0",
  "install_id": "<uuid4 minted at install time>",
  "install_record_sha256": "<sha256 of canonical install-record.json bytes>",
  "audit_tip_entry_hash": "<latest entry_hash of audit.log tail>",
  "audit_tip_seq_global": 1234,
  "updated_at_iso": "2026-05-17T03:14:15Z",
  "anchor_signature": "<HMAC-SHA256 of all above fields, keyed by ~/.harness/secret.key>"
}
```

`~/.harness/secret.key` (POSIX 0600 / Windows user-ACL): 256-bit random key minted at install, never written into the repo, never logged. Used both for anchor signing and §3.1.1 nonce HMAC.

**Update protocol**: every audit append under §3.8 transaction protocol MUST, after step 5 (journal removed), atomically rewrite the anchor file via `tmp + fsync + os.replace + fsync_parent_dir` to reflect the new tip. The anchor write is OUTSIDE the §3.8 transaction journal (because the journal protects the repo, not the home dir). Failure to update the anchor is logged at exit 14 `anchor_update_failed`; recovery is `harness verify --audit` followed by `harness anchor repair` (admin-only verb; idempotent).

**Verification points**:
- §2.6 state-trust preflight: on every CLI start, the preflight (a) verifies `anchor_signature` using `secret.key`; (b) verifies `audit_tip_entry_hash` matches the live `audit.log` tail's `entry_hash`; (c) verifies `install_record_sha256` matches live `install-record.json`. Any mismatch → exit 10 with sub-reason (`anchor_signature_invalid`, `audit_tail_diverged_from_anchor`, `install_record_mutated_post_install`).
- §3.8 crash recovery (Round-7 ordering fix): the anchor check runs BEFORE roll-forward (row 7). If `audit_tip_entry_hash` does not include the journal's `txn_id`, roll-forward is refused and exit 14 `anchor_predates_journal` fires.
- §6.1 install: anchor minted at install time with `install_record_sha256` of the just-written record. The install verb writes both files under the same transaction-style ordering.

**Attacker model defended**: a project-scoped file-tool attacker (Roo/OpenCode Bash + Edit + Write inside the repo) cannot write `~/.harness/audit-tip/` or `~/.harness/secret.key` if adapter permissions deny those globs (§12.6). An attacker with unrestricted user-account access defeats this; that class is documented out-of-scope (matches §3.1.1 threat model footnote).

**Not defended**: anchor rollback by an attacker with home-directory access. Mitigation: anchors include `audit_tip_seq_global`, which monotonically increases; verifier rejects anchors with `seq_global` less than any previously seen value (cached in `~/.harness/audit-tip/.seen.json`).

### 12.2 Safe-open semantics — §5.1.1 (R7-BLOCK Coherence E-35)

§5.1 filesystem fence requires race-safe path resolution; the prior doc referenced §5.1.1 in S10b verify but never defined the section. Pinned here:

**POSIX**: every fence-checked open MUST use `os.open(path, O_NOFOLLOW | O_CLOEXEC, dir_fd=parent_fd)` where `parent_fd` was obtained by walking the path components one at a time with `O_NOFOLLOW | O_DIRECTORY | O_PATH` from a known anchor under `cwd`. Symlinks anywhere in the path → `OSError(ELOOP)` → `verb=autopilot.fence.deny`, exit 4.

**Windows**: open via `CreateFileW(..., FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS, ...)` then `GetFinalPathNameByHandle(h, ..., VOLUME_NAME_DOS)` and confirm the resolved path stays under `cwd`'s canonical form. Junctions or reparse points anywhere in the resolved path → exit 4 `path_reparse_refused`. ToCToU attacks are mitigated by performing all subsequent reads/writes via the handle (`h`), never by re-`CreateFile`-ing the path.

`scripts/lib/safe_open.py` exports `safe_open(path, mode, *, anchor)`; tests in `tests/safe_open/` cover absolute symlinks, relative symlinks, hardlink-to-out-of-tree, Windows directory junctions, Windows mount points, and concurrent rename of an intermediate component during open.

### 12.3 Wrapper CLI contract — `harness fsd-run-phase` / `harness fsd-run-all` (R7-BLOCK Adapter C-22)

`harness fsd-run-phase [<slug>]`:

- Argparse: zero or one positional. More than one → exit 2 `multi_arg_rejected` with `Fix: harness fsd-run-phase <single-phase-slug>`.
- Empty positional: invoke `harness phase next-pending` internally; treat its stdout as the slug.
- `next-pending` empty (no pending phases) → exit 0, stdout `no pending phases`, no state mutation, no audit entry beyond `verb=fsd_run_phase.noop`.
- Non-empty slug: validate against canonical slug regex (§3.5). Regex miss → exit 2.
- Then invoke `harness phase autopilot start --phase <slug> --mode phase` internally. Authorization predicate (§3.5.1) applies. Re-entry into active autopilot → exit 15 (§3.5.2).
- On success: print to stdout `started phase_autopilot for <slug>`; exit 0. Side effect: `state.execution_mode=phase_autopilot`, identity fields populated, `verb=phase.autopilot.start` audit emitted with `wrapper=fsd_run_phase`.

`harness fsd-run-all`:

- Argparse: zero positional. Trailing tokens accepted but logged at `verb=fsd_run_all.ignored_args` and ignored (OpenCode tolerance).
- Pre-flight: §7.5 dirty-tree check (if git present, mode=chain). Exit 16 on dirty.
- `harness phase next-pending` → if empty, exit 0 `no pending phases`.
- Invoke `harness phase autopilot start --phase <slug> --mode chain` internally. Exit 15 on re-entry.
- Stdout `started chain_autopilot for <slug>`; exit 0.

**JSON form**: both wrappers accept `--json` and emit `{wrapper, slug, started: bool, exit_code, audit_entry_hash, autopilot_run_id, message}`.

**`--help`**: both wrappers print synopsis + the exact slash-command body that invokes them.

**Fresh-state init**: if `.scratch/phase-state.json` does not exist, the wrapper invokes `harness init --quiet` first (creates state with `execution_mode=manual`, all `autopilot_*` null, audits `verb=harness.init`). `harness init` is added to §3 verb registry (§12.7). Roadmap source is `.planning/phases/*/PLAN.md` glob in roadmap-order; `harness phase next-pending` returns the slug of the first phase directory whose `state.json` does not record `done`. If `.planning/phases/` is absent or empty → `next-pending` returns empty string + exit 0.

### 12.4 OIDC claim pinning — §3.5.1 sub-table (R7-BLOCK Auth A-4)

Every CI provider in the §3.5.1 allowlist MUST satisfy the per-provider verification spec below. `aud` (audience) is **harness-minted at install time** as `harness:install:<install_id>` (from §12.1); the CI workflow author MUST request that audience explicitly. This binds tokens to a specific install and prevents cross-install replay.

| Provider | `iss` exact | `aud` required | `sub` regex (anchored) | JWKS URL | `alg` allowlist | Clock skew | Replay defense |
|---|---|---|---|---|---|---|---|
| GitHub Actions | `https://token.actions.githubusercontent.com` | `harness:install:<install_id>` | `^repo:[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+:(ref:refs/heads/[^:]+|ref:refs/tags/[^:]+|pull_request|environment:[^:]+)$` | `https://token.actions.githubusercontent.com/.well-known/jwks` | `RS256` only | ±60s | reject `jti` already in audit within token `exp` window |
| GitLab CI | `https://gitlab.com` (or self-hosted base URL pinned at install) | `harness:install:<install_id>` | `^project_path:[^:]+:ref_type:(branch|tag):ref:[^:]+$` | `<iss>/oauth/discovery/keys` | `RS256` only | ±60s | reject `jti` replay; require `CI_JOB_JWT_V2` (V1 rejected) |
| Buildkite | `https://agent.buildkite.com` | `harness:install:<install_id>` | `^organization_slug:[A-Za-z0-9_\-]+:pipeline_slug:[A-Za-z0-9_\-]+$` | `https://agent.buildkite.com/.well-known/jwks` | `RS256` only | ±60s | reject `jti` replay |

**Common rules**:
- `alg=none`, HMAC algorithms (`HS*`), and any non-allowlisted alg → exit 6 `oidc_alg_rejected`.
- `exp` MUST be in the future after skew; `iat` MUST not be in the future after skew; `nbf` (if present) MUST be in the past after skew.
- JWKS fetched fresh on every verification (no caching in v0.7); HTTP failure → exit 6 `ci_oidc_unreachable`.
- ToCToU: verify signature first, then claims, then write audit BEFORE any state mutation.
- `jti` values consumed by the current install are recorded in audit with `verb=ci_oidc_consumed_jti`; a subsequent attempt with the same `jti` exits 6 `ci_oidc_replay`.
- Substring matches forbidden; `iss`/`sub` require exact-match / anchored-regex respectively.

`HARNESS_BY_TRUST` value MUST satisfy RFC 5321 addr-spec + NFC normalization + ASCII-only local-part (R7 A-5); failure exits 6 `bot_identity_malformed`.

### 12.5 Crash-recovery ordering + durability (R7-BLOCK Crash B-7, B-8, B-9, B-10, B-11, B-12)

The §3.8 transaction protocol gains the following enforced rules:

1. **Anchor-check before recovery**: every CLI start (including `harness verify --audit`) reads the §12.1 anchor first. If the anchor's `audit_tip_entry_hash` references an entry NOT present in live `audit.log*`, the harness exits 10 `audit_truncated_after_anchor` and refuses to read state. Roll-forward (matrix row 7) is gated on: (a) anchor verified, (b) journal's `txn_id` is referenced by live audit tail, (c) live audit tail's `entry_hash` equals or is a descendant of anchor's tip.
2. **Audit partial-write row (matrix row 12)**: if live audit tail's last record fails JSON-parse OR fails `entry_hash` verification, exit 14 `audit_partial_write` with `Fix:` line `harness verify --audit --repair-tail`. Row predicate `A` is NOT classified as 0 or 1 in this case.
3. **Audit-log parent-dir fsync (step 3 amendment)**: after `fsync(audit_fd)`, the harness MUST `fsync_parent_dir(scratch)` before proceeding to step 4. Documented as Round-7 amendment to §3.8 table row 3.
4. **APFS `F_FULLFSYNC` + Windows file-handle flush (§3.8.1 amendment)**: `durable_fs.py` exports `fsync_file_durable(fd)` in addition to `fsync_parent_dir(path)`. POSIX non-macOS: `os.fsync(fd)`. macOS: `fcntl.fcntl(fd, fcntl.F_FULLFSYNC)` (fall back to `os.fsync(fd)` if EINVAL). Windows: re-open the file with `CreateFileW(GENERIC_WRITE, FILE_SHARE_READ, ..., OPEN_EXISTING, 0, ...)` + `FlushFileBuffers(h)` after `os.replace`. Step 4 of §3.8 now requires `fsync_file_durable` of the renamed `state.json` AND `fsync_parent_dir(scratch)`.
5. **`os.replace` retry**: step 4 retries `os.replace` up to 5 times with exponential backoff (50ms, 100ms, 200ms, 400ms, 800ms) on `PermissionError` (Windows AV holding handle). Persistent failure → leave journal+tmp in place, exit 3 `state_replace_blocked`. Next CLI start performs roll-forward.
6. **`CloseHandle` / `FlushFileBuffers` return-value checks**: §3.8.1 wrapper raises `DurableFsError` on any zero return. `CloseHandle` failure → `WIN32_LAST_ERROR` recorded in `verb=durable_fs.close_failed`.
7. **NFS/SMB substrate warning**: at every CLI start, the harness detects `.scratch/`'s filesystem (POSIX `statvfs` + `/proc/mounts`; Windows `GetVolumeInformationW` + `FILE_REMOTE_DEVICE`). If remote (NFS, SMB, CIFS, FUSE), exit 3 `unsupported_substrate` with `Fix:` line referencing migration to local disk. Override flag `--accept-remote-substrate-best-effort` available but logs `verb=harness.substrate.degraded`.
8. **Migration write-back inside transaction (§1.2 amendment)**: legacy-schema migration on read MUST acquire the state lock and use the full §3.8 transaction protocol. Reads that do not have write permission (`harness status`/`harness next` agent-safe paths) defer migration; they read legacy fields in-memory and never write back. The first mutating verb after a legacy-state detection performs the migration.
9. **Rotation lock**: audit-log rotation MUST acquire the state lock; rotation is forbidden while a journal exists. Recovery looks for the journal's `txn_id` in BOTH `audit.log` and `audit.log.1`.

### 12.6 Human-presence proof tightening (R7-BLOCK Auth A-1, A-2, A-5; Coherence P1-7, P1-9, P1-10)

`§3.1.1` is amended in-place by the following invariants:

1. **Nonce TTL pinned**: 120 seconds, no other value cited. Earlier "60s" and "30s" mentions are typos; the canonical value is 120s, configurable at install via `harness install --nonce-ttl-seconds 60|90|120` (range 30..600).
2. **Nonce HMAC**: every nonce JSON file under `~/.harness/approval-nonces/` is signed via HMAC-SHA256 keyed by `~/.harness/secret.key` (§12.1). Consumers reject unsigned/badly-signed nonces with exit 6 `nonce_signature_invalid`. The signature is over `{nonce_code, audience, minter_tty, minted_at, expires_at}`.
3. **Controlling terminal binding**: the nonce records the minter's *controlling terminal device* (POSIX: `st_dev`+`st_rdev` of `os.ttyname(0)`; Windows: `GetConsoleWindow()` HWND + `GetWindowThreadProcessId`'s shell process ID). Consumer compares: same device → exit 6 `human_proof_same_controlling_terminal`. This defeats `script -q` / `pty.spawn` allocating a fresh pts inside the agent's process tree.
4. **Adapter permissions contract**: an adapter claims `approval_proof=supported` only by declaring deny-globs for `~/.harness/approval-nonces/**`, `~/.harness/secret.key`, `~/.harness/audit-tip/**`, AND deny-write for `git config --global user.email *` and `git config user.email *`. The contract is satisfied for Roo by `permissions.deny: ["Bash(cat ~/.harness/**)", "Bash(ls ~/.harness/**)", "Read(~/.harness/**)", "Bash(git config user.email *)", "Bash(git config --global user.email *)"]`. For OpenCode the equivalent permission-DSL entries are TBD per OpenCode tooling spec; if absent, the harness defaults that adapter to `approval_proof=unsupported` and `phase approve` exits 6 `adapter_approval_proof_unsupported` unless `--prompt-credential` is passed and OS credential is configured. **Install records `approval_proof` per adapter** (§6.1 amendment).
5. **gitconfig fingerprint**: `install-record.json` gains `git_user_email_at_install_sha256` (or null). `phase approve` step 2 reads current `git config user.email`; if its sha256 differs from the recorded fingerprint AND `--by` is not explicitly passed, exit 6 `gitconfig_mutated_post_install` with `Fix: pass --by <email> or re-run harness install`.
6. **`--prompt-credential`** is added to §3.1 synopsis: `harness phase approve [--by <email>] [--at <iso>] [--prompt-credential]`. When set, skips nonce flow and invokes OS credential prompt regardless of install default.

### 12.7 CLI verb registry (R7-BLOCK Coherence P1-11)

Canonical list of `harness` verbs in v0.7 (each defined elsewhere in §3 or §22):

| Verb | Section | TTY-only? | Mutating? |
|---|---|---|---|
| `harness init` | §12.3 | no | yes (state fresh init only) |
| `harness install` | §6.1 | yes | yes |
| `harness phase set <slug>` | §3.6 | no | yes |
| `harness phase approve` | §3.1 | **yes** | yes |
| `harness phase reopen` | §3.2 | **yes** | yes |
| `harness phase autopilot start \| stop` | §3.5 | no (TTY or CI predicate) | yes |
| `harness phase next-pending` | §3.5 | no | no |
| `harness fsd-run-phase` | §3.5, §12.3 | no | yes (via autopilot start) |
| `harness fsd-run-all` | §3.5, §12.3 | no | yes (via autopilot start) |
| `harness status [--json]` | §3.9, §12.8 | no | no |
| `harness next [--json] [--shell]` | §3.9 | no | no |
| `harness verify --audit [--fixture <path>] [--repair-tail]` | §2.2, §12.9 | no | no (read-only; repair-tail variant mutates audit only) |
| `harness preflight --autopilot` | §5.2 | no | no |
| `harness halt-diary clear` | §5.3 | no | yes |
| `harness lock recover --force` | §3.7 | yes | yes (admin) |
| `harness repair --strip-bom <path>` | §2.4 | no | yes |
| `harness approve-nonce mint` | §3.1.1 | yes | no (writes home dir, not repo) |
| `harness anchor repair` | §12.1 | yes | yes (admin; rebuilds anchor from current audit tail) |

Audit verb registry (every `verb=...` emitted into `audit.log`):

| Verb | Description | Added |
|---|---|---|
| `phase.set` | Phase transition (any slug) | Round-1 |
| `phase.set.noop` | Phase set no-op (slug unchanged) | S01 |
| `phase.approve` | Human approval gate passed | Round-1 |
| `phase.reopen` | Phase re-opened after approval | Round-1 |
| `phase.autopilot.start` | Autopilot mode started | Round-3 |
| `phase.autopilot.stop` | Autopilot mode stopped | Round-3 |
| `phase.autopilot.halt` | Autopilot halted (budget/error) | Round-3 |
| `phase.autopilot.start_hash_finalized` | Post-start hash committed to state | S01-A (Group A) |
| `phase.autopilot.start.refused` | Start refused (budget/preflight failure) | S01-A (Group A) |
| `phase.autopilot.start.recover_pending` | Recovery path from interrupted start | S01-A (Group A) |
| `halt_diary.clear` | halt diary cleared by operator | S11 (Group A) |
| `audit.rotated` | Audit log rotation seam entry | S06 |
| `audit.repair` | Audit log repaired (repair-tail) | S06 |
| `autopilot.fence.deny` | Write path denied by fs fence | S10b |
| `autopilot.network.deny` | Network call denied by guard | S10c |
| `cli.deprecated_flag` | Deprecated CLI flag used | S03 |
| `session.unlock` | Session lock released by operator | S01-C (Group A) |
| `lock.recovered` | Lock recovered after stale detection | S01-C (Group A) |
| `migrate.state_v2` | State schema migrated to v2 | S00.7 |
| `ci.oidc.jti.consumed` | CI OIDC JTI token consumed | S08 |
| `ci.oidc.jti.replay` | CI OIDC JTI replay attempt detected | S08 |
| `ci.oidc.jti.store_rotated` | JTI store corrupted and rotated | S06 (Group δ) |
| `fsd-run-all` | fsd-run-all slash command executed | S12 |
| `fsd-run-phase` | fsd-run-phase slash command executed | S12 |
| `approve_nonce.mint` | Approval nonce minted by operator | S00.5 (Group α) |
| `release.trust.verified` | SSH-signed release tag verified successfully | S15 (Group δ) |
| `release.trust.bypassed` | Unsigned release accepted via HARNESS_ALLOW_UNSIGNED_DEV | S15 (Group δ) |
| `release.trust.refused` | Release rejected (downgrade/missing trust/corrupted manifest) | S15 (Group δ) |
| `audit.secret_key.rotated` | Corrupted ~/.harness/secret.key rotated aside | 02d Cycle-2 |

**Cycle-1 amendment (P5-P2-1):** The following verbs were emitted by code but absent from this table prior to cycle-1 review: `halt_diary.clear`, `phase.autopilot.start_hash_finalized`, `phase.autopilot.start.refused`, `phase.autopilot.start.recover_pending`, `phase.set.noop`, `session.unlock`, `lock.recovered`. A machine-readable `KNOWN_VERBS` frozenset is maintained in `scripts/lib/audit.py`; `HARNESS_STRICT_VERB_REGISTRY=1` enables rejection of unknown verbs at append time.

**Cycle-2 amendment (02d Cycle-2):** `audit.secret_key.rotated` added to table above. `ci.oidc.jti.dir_override` added to `KNOWN_VERBS` for `HARNESS_JTI_DIR` env override forensic logging. `release.trust.bypassed` now also emitted at install time when stamping `trust_origin=dev_unsigned` via install path.

Legacy verbs (deprecated, no longer emitted in new code): `repair.bom_stripped`, `ci_oidc_consumed_jti` (replaced by `ci.oidc.jti.consumed`), `fsd_run_phase.noop`, `fsd_run_all.ignored_args`, `harness.init`, `harness.substrate.degraded`, `durable_fs.close_failed`, `anchor.repaired`.

`phase.empty_bucket` (legacy) is **deprecated** and forbidden in new code; §4.5 carve-out emits `phase.set` with `confirmation_kind=empty_bucket_bootstrap` instead.

### 12.8 Consistent-snapshot read for `harness status` / `harness next` (R7-BLOCK Crash B-7)

The §2.6 preflight ("MUST take state lock") applies only to MUTATING verbs. Read-only verbs use **consistent-snapshot read**:

1. Read `state.json` bytes.
2. Read audit tail (last entry only).
3. Compute `sha256(state_bytes)`; compare to audit tail's `after_sha256`. Match → return snapshot.
4. Mismatch → retry up to 3 times with 70ms / 140ms / 280ms backoff (covers max `os.replace` window observed in §12.5 retry loop).
5. Persistent mismatch → return snapshot with `state_audit_tip_mismatch=true` field in `--json`; human form prints WARN `state-audit mismatch; run 'harness verify --audit'`. Exit 0 still (status/next must remain low-noise).

This avoids lock contention for IDE polling while still surfacing mid-transaction races.

### 12.9 `harness verify --audit --fixture <dir>` grammar (R7-BLOCK Release D-25)

`--fixture <dir>`: overrides `.scratch/audit.log` source with `<dir>/audit.log` plus any `<dir>/audit.log.<N>` rotation files. State file is read from `<dir>/state.json` if present; otherwise the verifier operates audit-only. Anchor file is read from `<dir>/.audit-tip.json` (in-fixture stub) if present; otherwise anchor checks are skipped with `anchor_skipped=true` in the report. `--fixture` implies `--no-network` and refuses to run with `--release`.

`--repair-tail`: read-write variant that truncates the audit log to the last verifiable entry and rewrites the anchor. Refuses to run without `--by <email>` (TTY-only). Used by row 12 recovery.

### 12.10 Release smoke case catalogue — §9.3 (R7-BLOCK Release D-26)

Each `release_smoke_test.py --case <name>` invocation drives a documented scenario. Adapter-specific cases simulate slash-command body execution by parsing the literal Markdown body, extracting the `harness ...` invocations, and running them under a controlled environment with `HARNESS_TEST_FIXTURE_ADAPTER=<roo|opencode>` set.

| Case | Preconditions | Asserted exit | Asserted state/audit |
|---|---|---|---|
| `run-phase` | clean repo, S00.5 launcher installed, no autopilot active | 0 | `state.execution_mode=phase_autopilot`, `verb=phase.autopilot.start` with `wrapper=fsd_run_phase` |
| `run-phase-empty-arg` | as above; invoke wrapper with no slug | 0 | wrapper invoked `next-pending`; selected slug audited |
| `run-phase-multi-arg-fail` | invoke `harness fsd-run-phase a b` | 2 | no state mutation; stderr contains `Fix: harness fsd-run-phase <single-phase-slug>` |
| `run-phase-missing-positional-negative` | OpenCode body executed with trailing token | 0 | trailing token ignored; `fsd_run_all.ignored_args` NOT emitted (this is fsd-run-phase variant) |
| `run-all` | clean repo, non-empty roadmap, clean git tree | 0 | `state.execution_mode=chain_autopilot` |
| `run-all-empty-roadmap` | no phases under `.planning/phases/` | 0 | stdout `no pending phases`; no state mutation |
| `net-deny-curl-posix` | active phase_autopilot; agent attempts `curl ...` | 1 (shim exit) | `verb=autopilot.network.deny` recorded |
| `halt-handoff-flow` | autopilot active; force verification failure | non-zero from halting transition | `state.execution_mode=manual`, `last_halt` populated, `suggested_next_command_requires_human` set per command type |
| `status-after-halt` | as above, then `harness status` | 0 | stdout contains `Halt diary`, `Next action`, halt summary |
| `fsd-status-roo` | install Roo adapter; execute `.roo/commands/fsd-status.md` body | 0 | stdout from `harness status` surfaced |
| `fsd-status-opencode` | install OpenCode adapter; execute `.opencode/commands/fsd-status.md` body | 0 | same |
| `env-only-spoof-rejected` | set `HARNESS_AUTOMATION=chain` + `HARNESS_BY_TRUST=bot@x`; do NOT call autopilot start; run `harness phase set plan` | 2 | no autopilot context in state |
| `oidc-jti-replay` | start autopilot with valid OIDC; capture `jti`; mint second token with same `jti`; replay | 6 | `verb=ci_oidc_consumed_jti` recorded once; replay rejected |
| `anchor-tampered` | mutate `~/.harness/audit-tip/<repo-id>.json` `audit_tip_entry_hash`; run any verb | 10 | `anchor_signature_invalid` or `audit_tail_diverged_from_anchor` |
| `gitconfig-rotated` | mutate `git config user.email` post-install; run `harness phase approve` without `--by` | 6 | `gitconfig_mutated_post_install` |

### 12.11 `/fsd-status` slash bodies (R7-BLOCK Adapter C-23)

`.roo/commands/fsd-status.md`:

````markdown
---
description: Show current phase, halt diary, and next action via the harness state machine
argument-hint:
mode: ask
---

Run exactly:

`harness status`

Then run:

`harness next --json`

If `.requires_human == true` in the JSON output, surface the value of `.command` to the user with the prefix "please run this in your terminal:" — do not execute it. Otherwise execute `.command` only if it is read-only (`.agent_safe == true`); else surface and stop.
````

`.opencode/commands/fsd-status.md`:

````markdown
# fsd-status

Run exactly:

`harness status`

Then run:

`harness next --json`

If `.requires_human == true` in the JSON output, surface the value of `.command` to the user with the prefix "please run this in your terminal:" — do not execute it. Otherwise execute `.command` only if `.agent_safe == true`; else surface and stop.
````

S15 verify command runs these bodies against release smoke cases `fsd-status-roo` and `fsd-status-opencode` (§12.10).

### 12.12 §3.6 `phase set done` halt-diary guard (R7-BLOCK Adapter C-21)

Add to §3.6 transition validator: `(execute → done)` MUST refuse with exit 2 `last_halt_unacknowledged` if `state.last_halt` is non-null AND `state.last_halt.acknowledged_at` is null. User-initiated mutating verbs (`phase reopen`, `phase autopilot start`, `harness halt-diary clear`) set `acknowledged_at` as part of their transaction. `Fix:` line: `harness halt-diary clear` (or `harness phase reopen --to plan --reason "..."`).

### 12.13 §7.1 Windows cmd row resolution (R7-BLOCK Release D-28)

Row "windows-latest 3.12 py cmd" is downgraded from `release-gate` to `degraded-tolerant`: it runs on every release matrix invocation but failure does NOT block release if at least one Windows pwsh row passes AND the cmd-row failure is in a deny-list shim only. Required-check name `release-smoke (windows-latest, 3.12, py, cmd)` is published with annotation `degraded-tolerant`; branch protection MUST NOT require it.

### 12.14 §7 S14 sweep glob expansion (R7-BLOCK Release D-29)

The S14 residual-text sweep glob is pinned as:

```
.{roo,opencode}/commands/*.md
.{roo,opencode}/skills/**/*.md
docs/superpowers/skills/**/*.md
docs/superpowers/rules/**/*.md
docs/adr/*.md
.planning/**/*.md
CLAUDE.md
AGENTS.md
GEMINI.md
README.md
scripts/**/*.py
```

`grep_gate_stale_terms.py` walks every file matching the glob; any forbidden string (§7 grep-gate list) → exit non-zero with file:line citation.

### 12.15 §9 slice plan amendments

Add new slice **S00.7-anchor**: lands §12.1 audit-tip anchor + `~/.harness/secret.key` minting + `harness anchor repair` verb. `depends_on: S00, S00.5-launcher`. Verify: `pytest tests/anchor/ -q && python scripts/smoke/anchor_attacker_replay.py`.

Update S01-schema to include `plan_finalized_at`, `last_halt.suggested_next_command_requires_human`, `last_halt.acknowledged_at`.

Update S06-audit-chain to include row-12 partial-write fixture (§9.1 amendment above).

Update S07-prep-autopilot-cli to include §12.3 wrapper argparse + §12.4 OIDC pinning + §12.5 substrate-detection.

Update S15-status-next to include §12.8 consistent-snapshot read protocol + `/fsd-status` body landings (§12.11).

Update S13-smoke to include §12.10 case catalogue + S13 declared as **terminal release-gate slice** (re-runs after S15+S16 land; `depends_on` clarified to mean ordering, not numeric position).

### 12.16 Round-7 verdict + open items

Verdict after fixes: ACCEPT for implementation entry. Round-7 surfaced no fundamental design rework — every BLOCK reduces to either a new sub-section (§12.1, §12.2, §12.3, §12.4, §12.8, §12.9, §12.10, §12.11) or an amendment to an existing section (§1.1, §3.4, §3.5, §3.6, §3.8, §3.8.1, §6.1, §7, §7.1, §9, §9.1).

Polish items deferred to in-slice cleanup (not BLOCK for implementation start):
- §3 sub-section ordering reshuffle (Coherence P1-3).
- Stale "S00..S14" range in §17 narrative (Coherence P1-2).
- Stale "slice 11a" references in §15 narrative (Coherence P1-1).
- §2.1 audit field table additions for `automation_source` / `state_source` (Coherence P2-3, P2-4).
- `halt_reason` enum extension `agent_approve_attempt` (Coherence P1-13).

Out-of-scope additions still rejected (would require new design rounds, not fixes):
- True container/network namespace isolation (§10).
- Multi-user collaboration (§10).
- Adapter pre-tool hooks (§10).

Implementation begins at S00-adr-prep → S00.5-launcher → S00.7-anchor → S01-schema → ... per §9 (Round-7 amended).

---

## 13. Source of truth

This document is the design baseline for **phase 02c-phase-gate-hardening** after Round-7 hardening. It supersedes ad-hoc `--chain` / `--auto` references in current installed artifacts. Implementation begins after:

1. User reviews this Round-6-revised doc.
2. ADR-prep slice (`S00`) lands the three concrete ADR files listed in §8 as `Status: Accepted`.
3. Phase tracking is set up (this project skips the `.planning/phases/0X/` directory convention per user direction; prompt-driven phase tracking is sufficient).

**Project model (Round-4+5)**: single-user / single-machine. Harness install is treated as local repo augmentation, not a shared team artifact. Multi-user collaboration is explicitly out of scope (§10).

**Failure-handling model (Round-5 Model B)**: autopilot interruption is **manual handoff**, not failure. No `chain --resume`, no `chain --abort`, no commit-per-phase auto-creation. On halt, harness records a halt diary and surrenders control to the user via `harness status` / `harness next`.

**UX surface (Round-5)**: two read-only verbs cover "what now?" — `harness status` (snapshot + halt diary) and `harness next` (exact next command). Both safe for agent/IDE to invoke. Mutating verbs (`phase approve`, `phase reopen`) remain TTY-only.
