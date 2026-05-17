# Phase Gate Hardening — Design (2026-05-17)

**Status**: design draft, post 3-persona adversarial review (Protocol Architect / Low-Reasoning Realist / Ops & Supply-Chain Hawk). All three returned **BLOCK** on the initial proposal; this revision incorporates required changes.

**Origin**: Phase E IDE dogfood (Roo Code adapter) revealed that the haiku agent rocketed through `discuss → plan → execute → done` in a single turn. ADR-001 transition validation let it through because nothing prevented agent self-approval. `automation_mode` field exists in state JSON but no code branches on it; `--chain` / `--auto` referenced throughout skills/rules are doc-fiction (never wired).

**Goal**: make the phase gate a *real* gate — enforced by code, not by suggestion text — without destroying CI/release pipelines and without introducing footguns weak models will trip on.

---

## 0. Core principle — Agent never approves

**Only humans run `harness phase approve`.** The agent's only job is to read `state.execution_mode` and either proceed (within the bounds it permits) or stop and tell the user the exact command to run.

This collapses three potential failure modes into one:
- No TTY-prompt-in-IDE footgun (we never prompt from agent-spawned processes).
- No "agent learned `--yes`" arms race (the flag does not exist).
- No double-confirmation UX (user runs one command in one place).

Slash commands change `state.execution_mode`; they do **not** approve. Approval is always a separate, human-initiated `phase approve` invocation.

---

## 1. State schema delta

### 1.1 `.scratch/phase-state.json`

| Field | Type | Default | Semantics |
|---|---|---|---|
| `execution_mode` | enum | `"manual"` | `"manual"` \| `"phase_autopilot"` \| `"chain_autopilot"`. Single source of truth for whether the agent may cascade. Set by slash commands; read by skills/agent. **Never** by `phase approve`. |
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

### 2.2 Hash-chain invariant (pinned)

`before_sha256` / `after_sha256` hash **state-file content only**, never audit-entry fields. Adding optional audit fields does **not** invalidate prior hashes. Add an explicit regression test pinning this (golden fixture: an audit log with v1 entries followed by v2 entries; chain must verify end-to-end).

### 2.3 Canonicalization

JSON canonicalization for hashing is RFC 8785–style: sorted keys, UTF-8 no-BOM, LF line endings, no trailing whitespace. Document this in a new ADR (ADR-00X.2). On Windows, the CLI MUST normalize CRLF→LF before hashing.

---

## 3. CLI changes

### 3.1 `phase approve` — provenance-only gate

Existing: `harness phase approve --by <email> [--at <iso>] [--stdin-json]`.

New behavior:
1. Resolve `<email>` against three sources in order: (a) `HARNESS_BY_TRUST` env var (if set), (b) install-time HARNESS_USER from `.harness/install-record.json` (new file, 0o600 mode, written at install), (c) `git config user.email` of the install directory.
2. On match: log `by_source=<which>`, proceed.
3. On no match in any source: exit 6 with structured message naming all three sources and the `--override-identity --reason <text>` escape hatch.
4. `--override-identity --reason <text>` flag (new): bypasses (a)/(b)/(c) check, logs `confirmation_kind=override_identity`, `by_source=override_identity`, `override_reason=<text>` into audit.
5. **No TTY prompt.** **No `--yes` flag** (does not exist).
6. `confirmation_kind` set automatically:
   - If `state.execution_mode == manual`: `"human_cli"`.
   - Else: rejected with exit 8 (NEW — "approve called during autopilot; only humans approve").
7. After approve, audit entry emitted, state mutation atomic (write tmp file + rename + audit append).

### 3.2 `phase reopen` (NEW verb)

`harness phase reopen --to <discuss|plan> --by <email> --reason <text>`

Use cases: mind-change mid-flow ("wait, let's also do X"); recovery from a hung autopilot.

- Resets approval (`approved=false`, `approved_by=null`, `approved_at=null`).
- Resets phase to target. `--to plan` permitted from execute/done; `--to discuss` permitted from any phase.
- Audit entry `verb=phase.reopen` with `from_phase`, `to_phase`, `reason`.
- Provenance check identical to `phase approve`.

Replaces hand-editing of `phase-state.json` (which would corrupt audit chain).

### 3.3 Drop `--chain` / `--auto` flags

Skill/rule text already references these but no CLI consumes them. Removal path:
- v0.7.0: flags accepted at argparse level, emit `WARN: --chain/--auto deprecated; use slash command /fsd-run-phase or /fsd-run-all` to stderr, then proceed as no-op. Required so any caller that scripted them in pipelines does not hard-fail.
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

If the agent fails to obey this and runs `phase approve` anyway: exit 8 (see §3.4) prevents the mutation. The agent surfaces the error; user is now aware.

### 4.3 `/fsd-run-phase <phase-slug>`

Sets `state.execution_mode = phase_autopilot`. Agent cascades through the L3 lifecycle for the named phase only.

Hard-stop conditions (any one halts the cascade and reverts to `manual`):
- `verification` command non-zero exit
- `allowed_paths` violation by any tool call
- ADR-001 transition rejection
- Per-phase budget exceeded:
  - **Bash tool calls**: ≤ 50 (configurable via `phase autopilot --budget bash=N`)
  - **Wall-clock**: ≤ 5 minutes
  - **Edit/Write calls**: ≤ 100 files touched
- Network deny-list breach (see §5).

On hard-stop: `state.execution_mode` set to `manual`; audit `verb=phase.autopilot.halt` with `halt_reason`; user manually `phase reopen` or `phase approve` to resume.

At successful `phase set done`: `state.execution_mode` restored to `manual` automatically.

### 4.4 `/fsd-run-all`

Sets `state.execution_mode = chain_autopilot`. Cascades L1 (planning hydration) → L2 (roadmap into `.planning/phases/0X/`) → for each phase in roadmap, runs `/fsd-run-phase` equivalent.

Additional safety:
- **`--max-phases N`** (default **3**) — forces user re-engagement after N phases. Continuation requires `phase reopen --to plan --by <email>` or re-invoking `/fsd-run-all --resume`.
- **Checkpoint file** `.scratch/chain-checkpoint.json`: last-good commit SHA, completed phase list, in-progress phase. `harness chain --resume` and `harness chain --abort` (resets working tree to last-good commit, audits abort).
- **Heartbeat** to stderr every phase boundary so a user watching the terminal sees progress vs hung.
- All `/fsd-run-phase` budgets apply per phase.

### 4.5 Empty-bucket carve-out

Fresh install (no `.scratch/phase-state.json` yet): L1 hydration is **exempt** from the approval gate for the first transition. The first `phase set discuss` or any state-creating verb proceeds. After that, normal `manual` rules apply.

Explicitly documented in `workflow-planning-hydration` SKILL.md.

---

## 5. Containment for autopilot modes

### 5.1 Filesystem fence (existing, extended)

SecM2 already refuses symlink targets and escape paths in `prepare_scratch`. Extend to all writes during `phase_autopilot` and `chain_autopilot`: every Edit/Write/Bash mutation MUST resolve to a real path under `cwd`. Audit any rejection as `verb=autopilot.fence.deny`.

### 5.2 Network deny-list

In autopilot modes, the CLI sets an env var `HARNESS_AUTOPILOT_NETWORK=deny`. A new shim (`scripts/lib/autopilot_guard.py`) wraps Bash invocations and refuses commands matching:
- `curl`, `wget`, `nc`, `ssh`, `scp`, `rsync` (network transports)
- `git push`, `git pull`, `git fetch`, `git clone` (remote git)
- `gh`, `glab` (GitHub/GitLab CLIs)

Override: `phase autopilot --allow-network` flag at slash-command invocation; logged in audit.

### 5.3 Resume / abort semantics

Mid-cascade failure leaves state as-is at the failing transition. No automatic rollback. User options:
- `harness chain --resume` — continues from checkpoint after fixing the cause.
- `harness chain --abort` — resets working tree to last-good commit SHA from checkpoint, marks state as `failed_at_phase=<slug>` (audited), restores `execution_mode=manual`.
- `harness phase reopen --to plan --reason "..."` — manual recovery, preserves working tree.

ADR-001 does **not** gain a `failed` substate (per Architect review). Instead the audit log carries `halt_reason` and `failed_at_phase` markers.

---

## 6. Installed-manifest v2

Existing `installed-manifest.json` tracks installed paths. v2 additions:

| Field | Semantics |
|---|---|
| `harness_version` | exact version string at install time (e.g. `"v0.7.0"`) |
| Per-entry `installed_sha256` | hash at install time |
| Per-entry `current_sha256` | hash at last-known-good state (updated on upgrade) |
| `removed_in_version` | top-level list of paths removed by version (e.g. `[{"path": ".roo/commands/fsd-phase.md", "removed_in": "v0.7.0", "replaced_by": ".roo/commands/fsd-run-phase.md"}]`) |

Upgrade reconciliation logic:
- If `current_sha256 == installed_sha256_last_upgrade`: safe replace.
- Else: file was user-edited; conflict prompt OR record `user_modified=true` and skip with WARN.

Idempotency test (`release_smoke_test` extension): run `init` twice in the same target, diff manifest — must be byte-identical.

---

## 7. CI / release-smoke contract

`release_smoke_test.py` and any other non-interactive caller MUST use the env contract, not per-call `--yes` (which does not exist anyway).

Contract:
- Export `HARNESS_AUTOMATION=chain` before invoking the harness.
- The CLI honors this as if state had `execution_mode=chain_autopilot`. Audit emits `confirmation_kind=cascade_chain_autopilot` with `automation_source=env`.
- Provenance is satisfied by `HARNESS_BY_TRUST=<bot-email>` env var.

Grep-gate (in `release_smoke_test.py`) additions:
- Forbid the strings `--chain`, `--auto` in any installed artifact (catches doc-fiction regressions).
- Forbid `--yes` (catches accidental reintroduction).
- Forbid `automation_mode` in any newly written skill/rule text (forces use of `execution_mode`).

---

## 8. ADRs required before code lands

1. **ADR-00X.1 — Approver provenance and `execution_mode` promotion.** Identity binding (three sources + override), state-field semantics, `phase approve` exit 8 rule, `phase reopen` verb, `automation_mode` deprecation.
2. **ADR-00X.2 — Audit canonicalization.** RFC 8785 sorted keys, UTF-8, LF, what gets hashed (state-file content only), regression fixture format.
3. **ADR-00X.3 — Autopilot containment.** Slash command → execution_mode mapping, network deny-list, filesystem fence extension, budget defaults, checkpoint+resume semantics.

---

## 9. Slice plan (TDD, conductor-driven, ~12 slices)

Each slice is RED → GREEN → review (3-persona) → fix → commit.

1. State field `execution_mode` + migration from `automation_mode`.
2. `phase approve` provenance validation (3 sources + audit `by_source`).
3. `phase approve` rejects when `execution_mode != manual` (exit 8).
4. `phase reopen` verb (RED+GREEN).
5. `--override-identity --reason` flag.
6. Audit `schema_version: 2` + `confirmation_kind` derivation + regression test on hash-chain canonicalization.
7. Drop `--chain` / `--auto` with deprecation WARN shim.
8. Slash command `/fsd-run-phase` (rename + state setter) for Roo + OpenCode adapters.
9. Slash command `/fsd-run-all` (rename + state setter + roadmap walk).
10. Autopilot containment: budgets, fs fence extension, network deny shim.
11. Checkpoint `.scratch/chain-checkpoint.json` + `harness chain --resume` / `--abort`.
12. `installed-manifest.json` v2 (current_sha256, removed_in_version), upgrade reconciliation.
13. `release_smoke_test.py` HARNESS_AUTOMATION=chain contract + grep-gate additions.
14. Skill/rule/AGENTS.md text rewrite (agent-never-approves model). Remove all `automation_mode` / `--chain` / `--auto` strings.

(Slices 8 and 9 are large; may split.)

---

## 10. Out of scope (explicit)

- TTY interactive confirmation (rejected by Realist+Hawk review — IDE captures it).
- `--yes` flag (rejected — agent will learn it; no defense holds).
- Per-phase wall-clock timeout enforcement at OS level (deferred; budgets are tool-call counts).
- HMAC-signed audit.log.sig tip pointer (Nice-to-have from Hawk; future).
- `harness verify --audit` re-walk subcommand (Nice-to-have).
- `harness doctor --repair` for orphan approvals (referenced by Architect; deferred until first real orphan is observed).
- Adopt-existing flow provenance — kept lenient (`provenance: adopted_unverified`) per Hawk recommendation.

---

## 11. Review trail

3-persona adversarial review on 2026-05-17. All three returned **BLOCK** on the initial design. Required changes incorporated:

- **Protocol Architect** ([[orchestration-multi-persona-adversarial]]): ADR required; migration semantics; atomicity; deprecation window; rename collision; `failed` substate decision.
- **Low-Reasoning Realist**: agent-never-approves simplification (core principle adopted); kill `--yes`; no TTY prompts; `execution_mode` field; rename; `phase reopen`; empty-bucket exemption.
- **Ops & Supply-Chain Hawk**: schema_version + hash-chain canonicalization; `HARNESS_AUTOMATION=chain` env contract for CI; `by_source` audit; manifest v2; `--adopt-existing` lenience; network deny + budgets + checkpoint+resume; Windows TTY/CRLF gotchas.

Convergent BLOCK reasons across reviewers:
- Agent will learn `--yes` (Realist + Hawk).
- TTY prompt captured by agent (Realist + Hawk).
- Hash-chain breakage on schema bump (Architect + Hawk).
- CI smoke deadlock (all three).
- Provenance too strict (all three).
- `/fsd-chain-phase` blast radius (Realist + Hawk).
- Naming collision (Architect + Realist).

This revision addresses every BLOCK-class concern. Open items now tracked as Out of Scope (§10) or Nice-to-haves are deferred to a later phase.

---

## 12. Source of truth

This document is the design baseline for **phase 02c-phase-gate-hardening**. It supersedes ad-hoc `--chain` / `--auto` references in current installed artifacts. Begin implementation only after this design is reviewed once more by the user, ADRs landed, and a `02c-phase-gate-hardening/` phase directory is bootstrapped via the harness itself.
