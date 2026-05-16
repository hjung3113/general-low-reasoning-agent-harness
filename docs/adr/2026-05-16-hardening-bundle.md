# Hardening Bundle ADR — 2026-05-16

## Status

Accepted (bundled session). This document locks ADR-001, ADR-002, ADR-003a, ADR-003b, ADR-004, ADR-005 and the six mandated artifacts in a single PR. Partial landing of any subset is forbidden per spec §6 ("ADR session protocol").

- Spec: `docs/superpowers/specs/2026-05-16-hardening-slice-design.md` (commit `7622aba`, 740 lines).
- Decided in session order (per spec §6 directive): 001, 002, 004, 003a, 003b, 005.
- Bound to `02b-hardening` phase (per spec §5).
- No code change is authorized by this document. Implementation begins on row T0-A first, then ADR-bound rows after the §10 verification protocol is scoped into the implementation plan.

## Context

The current `main` ships three internal inconsistencies (spec §3): the `done` predicate in `scripts/lib/check.py:431` (`approved is not False`) inverts schema intent; `scripts/lib/worktree.py` imports `fnmatch` but performs only prefix/exact matching, silently zero-matching globs; the verification allowlist accepts `"Room is great"` because of the bare `"Roo"` prefix; the live state self-attests by listing `.scratch/phase-state.json` inside `allowed_paths`; `scripts/lib/state_repair.py:197` swallows `JSONDecodeError`. The hardening slice (§7) cannot begin code until six ADRs lock these contracts in one bundled session. The CLI contract artifact (§10.1) is what breaks the smoke-vs-CLI circular dependency; it is therefore produced here, not in T0-3 implementation.

## Decision Summary Table

| ADR | One-line decision |
|---|---|
| ADR-001 | Adopt option **3** (drop `approved` from the `done` branch); bump `state_schema_version` from `1` to `2`; pick sub-decision **3a** (`--reverse` writes `approved=false`) to round-trip the existing live fixture byte-for-byte. |
| ADR-002 | Adopt option **2** (full `fnmatch` glob, activating the dead import); precedence rule **(a)** — `blocked_paths` always overrides `allowed_paths`. |
| ADR-003a | Adopt option **2** (CLI + warn): two verbs `harness phase set` and `harness phase approve`; zero required flags; direct edits warn but do not fail; state file stays at `.scratch/phase-state.json`; session lockfile `.harness/session.lock`. |
| ADR-003b | Field ownership matrix: `phase`, `approved`, `approved_by`, `approved_at`, `state_schema_version`, `updated_at`, `updated_by` are CLI-only-preferred (direct-edit warns); narrative fields (`summary`, `notes`, `acceptance_criteria`, `verification`, `allowed_paths`, `blocked_paths`, `plan_path`, `state_path`, `checkpoint_path`, `current_checkpoint`, `next_action`, `plan_id`) remain user-editable. |
| ADR-004 | Adopt option **1** (two fields): `verification` (machine, ≤8-verb allowlist) and `review` (human, array of `{actor, at, evidence_path, summary}`); rejection diagnostic enumerates verbs inline and cites `docs/protocol-spec.md#verification-allowlist`. |
| ADR-005 | Adopt option **3** (preserve verbatim + write `.bak`): non-managed content outside `## Phases` is preserved byte-for-byte; a timestamped `.bak` is written before rewrite; paused phases are first-class; unparseable `phase-state.json` aborts with diagnostic exit. |

---

## ADR-001: `phase=done` Contract

### Context

The schema (`.scratch/phase-state.schema.json:347-399`) declares `done` requires `approved=true`. The checker (`scripts/lib/check.py:431`) reads `if state.get("approved") is not False:` and uses that to REJECT the record — the inverse of the schema. The only currently-shippable live state is the schema-invalid `approved=false` at `.scratch/phase-state.json:3`. Spec §6 ADR-001 offers three options and (if option 3 chosen) sub-decisions 3a/3b/3c for the `--reverse` migrator.

### Options Considered

- **Option 1** (`done` requires `approved=true`; fix checker). Rejected: `approved` semantically gates `execute` entry, not terminal closure; conflating them keeps the per-transition flag bleeding into terminal state. Also: under this option, the existing live record (`approved=false`) round-trips as schema-invalid and forces a non-trivial migration interpretation ("was this approved?" — we cannot answer truthfully from the existing record).
- **Option 2** (`done` requires `approved=false`; fix schema, keep checker). Rejected: contradicts the only natural English reading of `approved=true`/`done`; spec §3 explicitly calls the checker's predicate "inverted relative to the schema's intent".
- **Option 3** (drop `approved` from `done` branch). **SELECTED.** `approved` is per-transition state and `done` is terminal; the conflation is the root defect. Aligns with `state_schema_version` introduction in T0-1. Weak-model muscle memory fits: "approval is something I do once on the way in".

### Decision

Adopt option **3**. Drop the `approved` constraint from the `done` branch of `.scratch/phase-state.schema.json`. The field remains in the top-level `properties` (still required at top level, since other phases use it), but the `if/then` block for `done` has no `approved` constant.

Bump `state_schema_version` from `1` (the value T0-1 introduces) to `2` for the new `done` shape. Pre-T0-1 records (which have no `state_schema_version` field) are treated as version `0`.

### Sub-decisions

- **3a SELECTED**: `--reverse` migrator (v1 → v0) writes `approved=false` for `done` records. Rationale: byte-for-byte preserves the existing live fixture (`.scratch/phase-state.json:3` is `approved=false`); the round-trip property "v0 → v2 → v0 produces the original file" holds for the only pre-slice fixture that exists. The reverse-migrated record is schema-invalid under the OLD schema's stated intent (which required `approved=true` for `done`) — but it is identical to what shipped, and the old schema was never honored in practice (the inverted checker accepted it). Reviewers must read this carefully: we are choosing fidelity-to-shipped-reality over fidelity-to-old-schema-intent because no v0 record with `approved=true` and `phase=done` has ever existed.
- Rejected **3b** (`approved=true` on reverse): would write a value that has never existed in any pre-slice record; breaks the existence-preservation property; offers no benefit because the old `done` branch was never the safely-shippable case.
- Rejected **3c** (refuse downgrade): forces operators to hand-edit; defeats the "at least one prior version" reversibility requirement (spec hard constraint).

### Consequences

- **Breaking**: `done` records that previously included `approved=true` or `approved=false` will be ACCEPTED by the v2 checker regardless of value (the constraint is dropped on the `done` branch only). Records that previously failed the inverted checker (i.e., `approved=true done`) now pass.
- **Migration**: T0-1 migrator adds `state_schema_version: 2`. The migrator does NOT delete `approved` from `done` records (the field still exists at top level); it only ensures the record is consistent with v2 rules.
- **`--reverse`**: writes `state_schema_version: 0` (i.e., removes the field), and writes `approved=false` if missing.
- **Weak-model fit**: the rejection diagnostic for any phase ≠ `done` mentioning `approved` is unchanged. The `done` case becomes "anything goes for `approved`", which a Haiku-class agent learns as "I don't have to remember the value for done".
- **Test churn**: the test in `scripts/test_harness.py` asserting `done requires approved=false` is deleted; replacement asserts the new shape (per spec §9.4).

---

## ADR-002: Scope Matching Syntax

### Context

`scripts/lib/worktree.py:4` imports `fnmatch` but never calls it; `matches_any` at lines 76-84 performs prefix/exact match only. Any pattern containing `*`, `?`, `[`, `]` silently matches zero paths. Spec §3 calls this a correctness defect. Spec §6 ADR-002 offers four options plus a precedence sub-decision.

### Options Considered

- **Option 1** (prefix + exact only; reject globs at load time). Rejected: the dead `fnmatch` import is a clear "intent was glob" signal; reverting to literal-only after promising globs is a UX regression for anyone who has written `**/*.md`-style entries in their planning notes.
- **Option 2** (full `fnmatch`). **SELECTED.** Activates the dead import. `fnmatch` is stdlib (no new dep). Documented behavior: `*` matches across separators in `fnmatch`-default mode; for low-reasoning-agent legibility, the implementation MUST normalize trailing slashes (`dir/` → `dir/*`) and document `**` as equivalent to `*` (not gitignore semantics — that is option 3).
- **Option 3** (`pathspec` gitignore). Rejected: adds a new dependency; spec hard constraint forbids new deps.
- **Option 4** (two-field split). Rejected: doubles the schema surface for a single field that low-reasoning agents already confuse with `blocked_paths`; spec §9.1 prioritizes weak-model success.

### Decision

Adopt option **2**: `allowed_paths` and `blocked_paths` accept `fnmatch`-style globs. Patterns with no glob metacharacters retain prefix/exact semantics (with trailing-slash → directory prefix). `matches_any` calls `fnmatch.fnmatchcase(path, pattern)` and ALSO the existing prefix/exact branch; either match returns true.

### Sub-decisions

- **(a) SELECTED**: entry-level precedence. `blocked_paths` always overrides `allowed_paths` when both match the same path. Rationale: spec §6 ADR-002 explicitly states "Spec preference is (a) for low-reasoning agent legibility". The rule is one sentence ("block beats allow") and an agent can verify it from the field name alone.
- Rejected **(b)** (longest-match): "more specific" requires the agent to count characters; no muscle memory.
- Rejected **(c)** (order-of-declaration): JSON object/array order is fragile under reformatting; round-trip through `json.dumps(..., sort_keys=True)` (used in `scripts/lib/state.py:69`) would change behavior.

### Consequences

- **Breaking**: any consumer who relied on a pattern containing `*` matching zero paths (the dead-import silent behavior) will see those patterns START matching. T0-2 release notes MUST call this out.
- **Migration**: none required at the file level. Each `allowed_paths` entry whose meaning changes will be detected by `harness check --worktree`; if the new behavior is undesired for a specific entry, the user MUST escape it (e.g., add the literal string to `blocked_paths`).
- **Rejection path**: there is no "reject unsupported syntax" path under option 2; everything `fnmatch` understands is supported. Option 2 collapses the v2 backlog "fail loudly on unsupported syntax" requirement into "use fnmatch".

---

## ADR-003a: Phase Transition Primitive

### Context

Spec §6 ADR-003a hard constraints: ≤2 CLI verbs total, zero required flags on the lifecycle path, no signing. Three options on the ballot: CLI-only (option 1), CLI + warn (option 2), thin wrapper + direct-edit-with-confirmation (option 3). Spec §3 names self-attestation as a release blocker. Spec D2 locks `.harness/session.lock` as the session lockfile convention.

### Options Considered

- **Option 1** (CLI-only, hard-fail on direct edit). Rejected: every existing `.roo/commands/*.md` and `.opencode/commands/*.md` instructs the agent to read/verify `.scratch/phase-state.json` and (in some cases) edit it. Hard-fail on direct edit forces a same-PR rewrite of all adapter commands AND all SKILL files. Spec §9.1 requires N=50 trials at ≥80% pass on a Haiku-class agent; cold-flipping the trust model fails this with high probability.
- **Option 2** (CLI + warn). **SELECTED.** CLI is the sanctioned path. Direct edits still pass the checker but produce a high-severity warning naming the missing audit-sidecar entry. Preserves muscle memory while making the CLI the obviously-easier path. Spec §2.1 explicitly lists "warn-not-fail" as an on-ballot variant to preserve weak-model muscle memory.
- **Option 3** (CLI + interactive confirmation prompt). Rejected: interactive prompts break headless CI; the spec's §10.2 smoke harness runs scripted, and the prompt either auto-answers (defeats the purpose) or blocks the smoke (defeats CI).

### Decision

Adopt option **2**.

**Verb shape (≤2 verbs):**
- `harness phase set <phase>` — sets the current phase. Optional flags: `--plan-id`, `--summary`, `--next-action`. No required flags. Verb is positional; the phase name (`discuss`/`plan`/`execute`/`done`) is read from `argv[1]` of the subcommand.
- `harness phase approve` — flips `approved=true` and stamps `approved_by` (from `git config user.email` or `$USER`) and `approved_at` (`now_utc()`). No required flags. Optional flags: `--by`, `--at` (for replay/testing).

Both verbs touch the T0-A atomic-write primitive only. Both write a single-line entry to `.harness/audit.log` (newline-delimited JSON) recording verb, timestamp, before-hash, after-hash.

**Direct-edit policy:** `check` continues to accept `.scratch/phase-state.json` after a direct edit. If the audit log's most recent before-hash for the file does NOT match the current on-disk hash, `check` emits `warning: phase-state.json changed outside CLI; run 'harness phase audit' to record` and exits 0. The warning is high-severity (printed to stderr, prefixed `warning:`).

**State file location:** stays at `.scratch/phase-state.json`. No relocation. Rationale: relocating would force a parallel migration of every adapter command file and SKILL file in the same PR; spec §7 T1-S is scoped as surface-touch only. By keeping the path, T1-S only updates verb references, not paths.

**Uninstall (`--remove-install-state`)**: since the state file path is unchanged, `--remove-install-state` continues to handle the single legacy path. No new logic needed. `STATE_FILE_PATHS = (".scratch/phase-state.json",)`.

**Session lockfile:** `.harness/session.lock`. The CLI `phase set` and `phase approve` verbs touch this file on entry and remove it on clean exit. `harness upgrade` detects the lockfile and refuses with: `error: active session detected at .harness/session.lock; finish the session ('harness phase set done' or 'harness phase approve'), or remove the lockfile manually after confirming no other harness process is running`. Exit code: 3.

### Sub-decisions

- **`STATE_FILE_PATHS` artifact**: `STATE_FILE_PATHS = (".scratch/phase-state.json",)`. Published in Artifact 2 below. This tuple is the source of truth for the §10.2 grep gate, T1-S allowlist, and the uninstall flow.
- **Audit log path**: `.harness/audit.log` (newline-delimited JSON). Not a state file. NOT in `STATE_FILE_PATHS`.
- **Session lockfile path**: `.harness/session.lock`. Not a state file. NOT in `STATE_FILE_PATHS`.

### Consequences

- **Breaking**: agents that wrote `.scratch/phase-state.json` directly will see a stderr warning. CI that greps stderr for `warning:` will need an exemption or a CLI-path migration.
- **Adapter mirror**: `.roo/commands/phase-execute.md` and `.opencode/commands/execute.md` MUST add a line "use `harness phase set execute && harness phase approve` instead of direct edit" — surface-touch under T1-S.
- **Weak-model fit**: two verbs, four lifecycle phases, no required flags. The Haiku menu is six items total (`set discuss`, `set plan`, `set execute`, `set done`, `approve`, plus the direct-edit-with-warning fallback). Within spec §9.1 ergonomic budget.

---

## ADR-003b: Field Ownership Matrix

### Context

ADR-003a chose option 2 (CLI + warn). This means direct edits remain LEGAL but discouraged. ADR-003b's option space is therefore constrained: every field has at minimum a `user` writer (because direct edits are not blocked); the question is which fields are CLI-PREFERRED (i.e., the CLI verb sets them and the audit log records the change) vs CLI-EXCLUSIVE-IN-PRACTICE (the CLI verb is the only path that knows the correct value).

### Options Considered

- **Option A** (every field user-editable, no CLI ownership). Rejected: defeats the warn-on-drift mechanism; no field has a canonical CLI writer for the audit log to reference.
- **Option B** (lifecycle fields CLI-preferred, narrative fields user-editable). **SELECTED.** Splits cleanly along the line "fields that have a single canonical right answer the CLI can compute" vs "fields with content the user authors".
- **Option C** (all fields CLI-only). Rejected: would force CLI surface for `summary`, `acceptance_criteria`, etc., which are paragraph-level content; the CLI verb would devolve into "read multi-line input from stdin" and lose the zero-required-flags property.

### Decision

Adopt option **B**. See Artifact 3 below for the full table.

**CLI-preferred fields** (CLI is the canonical writer; direct edit emits drift warning):
- `phase` — written by `harness phase set <phase>`.
- `approved`, `approved_by`, `approved_at` — written by `harness phase approve`.
- `state_schema_version` — written by `harness migrate state` (T0-1 row's migrator); never user-edited.
- `updated_at`, `updated_by` — re-stamped by both verbs on every write.

**User-editable fields** (CLI does not write these; direct edit is the canonical path):
- `plan_id`, `summary`, `plan_path`, `state_path`, `checkpoint_path`, `current_checkpoint`, `next_action`
- `allowed_paths`, `blocked_paths`
- `acceptance_criteria`, `verification`, `notes`
- `automation_mode`, `auto_selected`

**Optional CLI flags** (CLI MAY write a user-editable field if the flag is given): `harness phase set plan --plan-id X --summary "..."` writes `plan_id` and `summary` as a convenience; this is opt-in, not the canonical path.

### Sub-decisions

- **`review` field** (new, ADR-004): user-editable. Not CLI-written.

### Consequences

- **Breaking**: none in this row alone; the matrix is descriptive, not enforced via schema constraint. Enforcement is via the audit-log warning mechanism (ADR-003a).
- **Documentation**: `docs/protocol-spec.md#field-ownership` MUST contain the table verbatim from Artifact 3.

---

## ADR-004: Verification Field Shape

### Context

`scripts/lib/check.py:99-111` declares `VERIFICATION_PREFIXES` as `("python3 ", "git ", "jq ", "npx ", "Validate ", "Review ", "Inspect ", "Confirm ", "core-only ", "OpenCode-only ", "Roo")`. The bare `"Roo"` prefix means `"Room is great"` passes machine verification (spec §3). The list mixes 4 machine verbs with 6 review/free-text verbs. Spec §6 ADR-004 offers four options and three hard sub-constraints: (i) rejection diagnostic enumerates verbs inline, (ii) ≤8 verbs, (iii) error cites verbs source path.

### Options Considered

- **Option 1** (two fields: `verification` machine + `review` human). **SELECTED.** Clean split. `verification` is `array<string>` (each string must start with a registered command verb); `review` is `array<object>` with typed evidence. Two separate validators; two separate error messages.
- **Option 2** (discriminated union). Rejected: discriminated unions are a known weak-model trap — Haiku produces `{type: "command", cmd: "..."}` vs `{"type":"command","cmd":"..."}` vs forgetting the type. Two fields with simpler types is more legible.
- **Option 3** (tighten allowlist + parallel `review_evidence`). Rejected: structurally identical to option 1 but with a less-clear field name (`review_evidence` vs `review`); pick the clearer name.
- **Option 4** (config-file allowlist). Rejected: spec sub-constraint (iii) requires the error to cite the allowlist location, and a config file at `.harness/verification-prefixes.json` would itself need a schema, recursing the problem.

### Decision

Adopt option **1**. Schema gains:

- `verification`: existing `array<string>`, items MUST start with one of the 8 allowlist verbs (see Artifact 4).
- `review`: new `array<object>`, items have `{actor: string, at: ISO-8601-UTC, evidence_path: string, summary: string}`. All four required.

The allowlist is hard-coded in `scripts/lib/check.py` (constant `VERIFICATION_PREFIXES`) and DOCUMENTED in `docs/protocol-spec.md#verification-allowlist`. The constant is the source of truth; the doc is a mirror generated by T0-3 with a comment pointing at the file:line.

**Rejection diagnostic** (template):

```
error: {path} verification[{index}] = {value!r} does not start with an allowed verb.
Allowed verbs (8): python3, git, jq, npx, pytest, bash, harness, make.
See docs/protocol-spec.md#verification-allowlist (source: scripts/lib/check.py VERIFICATION_PREFIXES).
```

### Sub-decisions

- Constraint **(i) inline-enumerated verbs**: satisfied by the template above; the verbs are printed verbatim.
- Constraint **(ii) ≤8 verbs**: 8 verbs (python3, git, jq, npx, pytest, bash, harness, make). The previous 6 review verbs (`Validate`, `Review`, `Inspect`, `Confirm`, bare `Roo`, `core-only`, `OpenCode-only`) are REMOVED from the machine allowlist; they move to the new `review` field as the `actor` value or `summary` content.
- Constraint **(iii) error cites source path**: the line `See docs/protocol-spec.md#verification-allowlist (source: scripts/lib/check.py VERIFICATION_PREFIXES)` satisfies this.

### Consequences

- **Breaking**: every existing record whose `verification` entry started with `Validate `, `Review `, `Inspect `, `Confirm `, `Roo`, `core-only `, or `OpenCode-only ` will be REJECTED by the v2 checker. The current live fixture `.scratch/phase-state.json:34-39` is safe — all four entries start with `python3 ` (4 entries: `python3 -m unittest...`, `python3 scripts/harness.py check`, `python3 scripts/harness.py check --worktree`, `python3 scripts/release_smoke_test.py`).
- **Migration**: the T0-1 migrator MUST scan `verification` entries and either (a) leave them if they match the new allowlist, or (b) move them to `review` with a synthesized `{actor: <verb>, at: updated_at, evidence_path: "", summary: <full text>}`. The synthesized `evidence_path: ""` is the empty-string sentinel — `review` items with empty `evidence_path` are accepted but flagged by `doctor` as needing manual completion.
- **Doctor**: a new `doctor` finding "review entry has empty evidence_path" is added (T0-4 acceptance).
- **`scripts/release_smoke_test.py`** and `scripts/test_harness.py`: their `verification` entries are all-`python3 ` already; no churn.

---

## ADR-005: `state_repair` Preservation Policy

### Context

`scripts/lib/state_repair.py` rewrites `.planning/STATE.md` and `.planning/ROADMAP.md`. Today it preserves outside-managed-block content via `_wrap_section_in_block` (lines 79-120). Spec §3 cites `scripts/lib/state_repair.py:197` swallowing `JSONDecodeError`. Spec §5 requires paused phases (e.g., `02-skill-pack-expansion`) be first-class. Spec §6 ADR-005 offers four options.

### Options Considered

- **Option 1** (preserve verbatim, no backup). Rejected on its own: no safety net for the case where the canonicalization output is unexpectedly different and the user wants to inspect the pre-rewrite file.
- **Option 2** (refuse on non-managed content). Rejected: users author non-managed content (the spec EXPECTS narrative outside `## Phases`); refusing would break the common case.
- **Option 3** (preserve verbatim + write `.bak` with timestamp). **SELECTED.** Combines the safety of option 1 with a one-time recovery artifact. `.bak` filename: `<original>.pre-repair.<ISO-8601-compact-UTC>.bak`.
- **Option 4** (interactive `state repair --interactive`). Rejected: same headless-CI problem as ADR-003a option 3.

### Decision

Adopt option **3**.

**Behavior:**
1. Before any rewrite of `.planning/STATE.md` or `.planning/ROADMAP.md`, `state_repair` writes `<original>.pre-repair.<timestamp>.bak` via the T0-A atomic primitive. Timestamp format: `20260516T193045Z` (compact ISO 8601, no separators, UTC).
2. Content outside the managed `## Phases` block (and outside any other managed marker block) is preserved BYTE-FOR-BYTE — no whitespace normalization, no trailing-newline addition outside the managed payload.
3. Paused phases (per spec §5) are represented as first-class state in `.planning/STATE.md`. The managed `state-current` block payload gains a `### Paused Phases` subsection listing phases with status `paused` (e.g., `- **Phase 02 - skill-pack-expansion** (status: paused)`). `state_repair` reads paused status from `.planning/STATE.md`'s pre-rewrite `### Paused Phases` subsection inside the managed block, or from the canonical pause-marker file (spec §5 leaves this to T0-5 implementation; the ADR mandates only "first-class, not deleted as orphan content").
4. If `phase-state.json` is unparseable (`JSONDecodeError`), `state_repair` aborts with exit code 2 and the diagnostic: `error: .scratch/phase-state.json is unparseable ({exc}); fix the JSON or restore from a backup before running 'harness state repair'`. No rewrite of `.planning/STATE.md` or `.planning/ROADMAP.md` occurs. This replaces the current swallow at `scripts/lib/state_repair.py:197`.

### Sub-decisions

- **`.bak` retention**: `state_repair` does not auto-delete old `.bak` files. They accumulate in `.planning/`. A future row (`02c-hardening`) may add `--prune-backups`; out of slice here.
- **`.bak` location**: alongside the original (e.g., `.planning/STATE.md.pre-repair.20260516T193045Z.bak`). NOT in `.harness/`.

### Consequences

- **Breaking**: none for content; additive. `.bak` files appear after every repair invocation; `.gitignore` SHOULD be updated to ignore `.planning/*.pre-repair.*.bak` (T0-5 sub-task).
- **Atomic primitive**: `.bak` write goes through T0-A. The original is then written via T0-A. Order: write `.bak` first; if that fails, abort before touching the original. This is the spec §7 T0-A "no window where neither file exists" property applied to the backup case.
- **Paused-phase representation**: T0-5 implementation must edit `.planning/STATE.md` BEFORE T0-5 lands to define the `### Paused Phases` subsection structure. Spec §5 mandates this ordering.

---

## Artifact 1 — CLI Contract

### Verb 1: `harness phase set <phase>`

**Synopsis:**
```
harness phase set discuss|plan|execute|done
                  [--plan-id PLAN_ID]
                  [--summary SUMMARY]
                  [--next-action TEXT]
                  [--checkpoint LABEL]
                  [--checkpoint-path PATH]
                  [--state-path PATH]
                  [--plan-path PATH]
```

**Required positional arg:** `<phase>` ∈ `{discuss, plan, execute, done}`. No required flags.

**Input (JSON shape, internal representation after argparse):**
```json
{
  "verb": "phase.set",
  "phase": "discuss|plan|execute|done",
  "plan_id": "string|null",
  "summary": "string|null",
  "next_action": "string|null",
  "current_checkpoint": "string|null",
  "checkpoint_path": "string|null",
  "state_path": "string|null",
  "plan_path": "string|null"
}
```

**Output (stdout, JSON):**
```json
{
  "ok": true,
  "verb": "phase.set",
  "previous_phase": "string",
  "phase": "string",
  "state_path": ".scratch/phase-state.json",
  "audit_entry_index": 42,
  "updated_at": "2026-05-16T19:30:45Z",
  "updated_by": "hjung3113@gmail.com"
}
```

**Exit codes:**
- `0` — ok.
- `1` — generic error (write failure, IO).
- `2` — invalid state (e.g., setting `execute` without `approved=true` from a prior `approve` verb; or `phase-state.json` is unparseable).
- `3` — session lockfile present (`.harness/session.lock` exists; another session active).
- `4` — schema-version refusal (reserved for `02c-hardening` guard; not active in this slice).

**Error templates** (printed to stderr):
- Lockfile: `error: active session detected at .harness/session.lock; finish the session ('harness phase set done' or 'harness phase approve'), or remove the lockfile manually after confirming no other harness process is running` → exit 3.
- Invalid transition: `error: cannot set phase={target}; current phase={current} requires approve before execute. Run 'harness phase approve' first.` → exit 2.
- Unparseable state: `error: .scratch/phase-state.json is unparseable ({exc}); fix the JSON or restore from a backup before retrying.` → exit 2.

**Idempotency:** `harness phase set X` when current phase already equals X is a no-op WRT phase value but still re-stamps `updated_at`/`updated_by` and appends an audit-log entry of type `phase.set.noop`. The state file is rewritten only if `updated_at`/`updated_by` differ from the on-disk values (which they always will, since `updated_at` is `now_utc()`). Net: not byte-idempotent, but semantically idempotent.

### Verb 2: `harness phase approve`

**Synopsis:**
```
harness phase approve [--by EMAIL] [--at ISO-8601-UTC]
```

**Required positional arg:** none. No required flags. (`--by` and `--at` are reserved for replay/testing; default to `git config user.email`/`$USER` and `now_utc()`.)

**Input (JSON shape):**
```json
{
  "verb": "phase.approve",
  "by": "string|null",
  "at": "string|null"
}
```

**Output (stdout, JSON):**
```json
{
  "ok": true,
  "verb": "phase.approve",
  "phase": "string",
  "approved": true,
  "approved_by": "hjung3113@gmail.com",
  "approved_at": "2026-05-16T19:30:45Z",
  "state_path": ".scratch/phase-state.json",
  "audit_entry_index": 43,
  "updated_at": "2026-05-16T19:30:45Z",
  "updated_by": "hjung3113@gmail.com"
}
```

**Exit codes:** same as `phase set` (0/1/2/3/4 with same semantics).

**Error templates:**
- Wrong phase: `error: cannot approve phase={current}; approval is only valid in phase=plan (transitions to execute) or phase=execute (re-approval after change). Use 'harness phase set <next>' first.` → exit 2.
- Lockfile: same as `phase set`.

**Idempotency:** `harness phase approve` when `approved=true` is already set is treated as a re-approval: it re-stamps `approved_by`/`approved_at` and writes a new audit entry. Not byte-idempotent.

### Audit log format (`.harness/audit.log`)

Newline-delimited JSON, append-only:
```json
{"index": 42, "verb": "phase.set", "args": {"phase": "execute"}, "before_sha256": "abc...", "after_sha256": "def...", "at": "2026-05-16T19:30:45Z", "by": "hjung3113@gmail.com"}
```

**Path:** `.harness/audit.log`. **Not** a state file; not in `STATE_FILE_PATHS`.

### Drift-warning template (printed by `harness check` to stderr, exit 0):

```
warning: .scratch/phase-state.json sha256 ({current}) does not match the last audit entry's after_sha256 ({expected}) — direct edit detected since audit index {index}. Run 'harness phase audit' to record, or 'harness phase set <phase>' / 'harness phase approve' to restamp through the CLI.
```

(Note: `harness phase audit` is a future row — `02c-hardening`; the warning's mention is forward-looking and acceptable in this slice's drift message.)

---

## Artifact 2 — `STATE_FILE_PATHS`

The post-decision authoritative tuple of state file paths. Single source of truth for the §10.2 grep gate, T1-S SKILL surface allowlist, and the `--remove-install-state` uninstall flow.

```python
STATE_FILE_PATHS = (
    ".scratch/phase-state.json",
)
```

**Not in `STATE_FILE_PATHS`** (intentionally excluded; these are operational/audit, not gate state):
- `.harness/installed-manifest.json` (handled separately by the existing `INSTALL_STATE` constant in `scripts/lib/state.py:32`).
- `.harness/audit.log` (append-only, not a gate file).
- `.harness/session.lock` (presence/absence file, not content).
- `.planning/STATE.md` (markdown durable memory, not the live gate).
- `.planning/ROADMAP.md` (markdown durable memory).
- `.scratch/phase-state.schema.json` (schema, not state).
- `.scratch/phase-state.example.json` (example, not live state).

**Consumers:**
- `scripts/release_smoke_test.py` (§10.2 grep gate) iterates `STATE_FILE_PATHS` for the write-verb grep.
- T1-S SKILL update touches only SKILL files referencing strings in `STATE_FILE_PATHS`.
- `scripts/uninstall_harness.py --remove-install-state` removes each path in `STATE_FILE_PATHS`.

---

## Artifact 3 — Field Ownership Matrix

Rows = field names (per `.scratch/phase-state.schema.json`). Columns = phases. Cells = writer authority: `user` (direct edit canonical), `cli` (CLI verb canonical, direct edit warns), `system` (CLI/migrator writes only, never user), `none` (field MUST be absent or null in this phase). Where a field is CLI-preferred but the CLI accepts the user-provided value via optional flag, the cell is `cli` and the optional flag is noted in parentheses.

| Field | discuss | plan | execute | done |
|---|---|---|---|---|
| `phase` | cli | cli | cli | cli |
| `approved` | cli (=false) | cli (=false) | cli (=true) | cli (any; see ADR-001) |
| `approved_by` | none | none | cli | cli |
| `approved_at` | none | none | cli | cli |
| `plan_id` | none | user | user | user |
| `summary` | user | user | user | user |
| `plan_path` | user | user | user | user |
| `state_path` | user | user | user | user |
| `checkpoint_path` | user | user | user | user |
| `current_checkpoint` | user | user | user | user |
| `next_action` | user | user | user | user |
| `allowed_paths` | user | user | user | user |
| `blocked_paths` | user | user | user | user |
| `acceptance_criteria` | user | user | user | user |
| `verification` | user | user | user | user |
| `review` (new, ADR-004) | user | user | user | user |
| `notes` | user | user | user | user |
| `automation_mode` | user | user | user | user |
| `auto_selected` | user | user | user | user |
| `state_schema_version` | system | system | system | system |
| `updated_at` | cli | cli | cli | cli |
| `updated_by` | cli | cli | cli | cli |

**Notes:**
- `cli` cells: direct edit is not blocked but emits the drift warning (Artifact 1, drift-warning template). The audit log records the canonical CLI write.
- `system` cells: only the migrator (`harness migrate state`) writes `state_schema_version`. The lifecycle CLI verbs do NOT write it. Direct edit emits a warning and `harness check` exit 0 (since the field is required-by-presence, not required-by-value, in v2).
- `none` cells: `harness phase set discuss` clears `approved_by`/`approved_at` to `null` if previously set. Schema allows `null` for these fields.
- `user` cells in the matrix are SET via direct file edit. Optional CLI flags (e.g., `--summary`) are convenience writes that ALSO go through the audit log; using them does not change the field's ownership classification.

---

## Artifact 4 — Allowed Verification Verbs

**Allowlist (8 verbs, in canonical order):**

```python
VERIFICATION_PREFIXES = (
    "python3 ",
    "git ",
    "jq ",
    "npx ",
    "pytest ",
    "bash ",
    "harness ",
    "make ",
)
```

**Canonical source file:** `scripts/lib/check.py` constant `VERIFICATION_PREFIXES`. The tuple is the source of truth.

**Documentation mirror:** `docs/protocol-spec.md#verification-allowlist` (created by T0-3). The doc paragraph cites the file:line of the source constant. T0-3 acceptance includes a regression test that asserts the doc and the constant match byte-for-byte (allowing for surrounding markdown).

**Example values (one per verb):**

| Verb prefix | Example |
|---|---|
| `python3 ` | `python3 -m unittest scripts/test_harness.py` |
| `git ` | `git diff --name-only main...HEAD` |
| `jq ` | `jq -e '.phase == "done"' .scratch/phase-state.json` |
| `npx ` | `npx playwright test --reporter=line` |
| `pytest ` | `pytest scripts/tests/test_atomic.py -v` |
| `bash ` | `bash scripts/smoke/lifecycle.sh` |
| `harness ` | `harness check --worktree` |
| `make ` | `make verify` |

**Removed from previous allowlist** (now belong in the new `review` field as `actor` or `summary`):
- `Validate `, `Review `, `Inspect `, `Confirm ` — these are review prose, not commands. Move to `review[*].summary` and set `review[*].actor` accordingly.
- bare `Roo` — the false-positive root cause (`"Room is great"` passed). Removed.
- `core-only `, `OpenCode-only ` — bespoke per-adapter prefixes; their use cases are now scripted under `bash scripts/smoke/core-only.sh` or invoked as `harness check --adapter opencode`.

**Adding a 9th verb:** spec §6 ADR-004 sub-constraint (ii) requires a separate ADR. The `docs/protocol-spec.md#verification-allowlist` section documents this requirement.

---

## Artifact 5 — Migration Spec

### Pre-slice → post-slice state shape diff

**Removed constraints:**
- Schema `allOf[3].then.properties.approved.const = true` (the `done` branch's `approved=true` constraint). DROPPED per ADR-001 option 3.

**Added fields:**
- `state_schema_version: integer` at the top level. T0-1 introduces with value `1`; this ADR bumps to `2` for new shape. Required as a presence-check; value enforcement is deferred (R-2, spec §2.8).
- `review: array<object>` at the top level. Items: `{actor: string, at: ISO-8601-UTC, evidence_path: string, summary: string}`. Required minItems: 0 (i.e., the field may be empty array; absence is treated as empty).

**Modified constraints:**
- `verification[*]` allowlist tightened to 8 verbs (Artifact 4). Pre-slice entries failing the new allowlist are rewritten into `review[*]` by the migrator (see below).

### Byte-exact `--forward` transformation for `.scratch/phase-state.json` fixture

**Input** (current live state, `.scratch/phase-state.json`, 47 lines per Read above):

```json
{
  "phase": "done",
  "approved": false,
  "approved_by": "user",
  "approved_at": "2026-05-14T15:00:00Z",
  "plan_id": "generalized-harness-release-01",
  "automation_mode": "manual",
  "auto_selected": [],
  "summary": "Generalized harness release work is approved in a separate repository copy.",
  "state_path": ".planning/STATE.md",
  "plan_path": ".planning/phases/01-generalized-harness-release/01-01-PLAN.md",
  "checkpoint_path": ".planning/phases/01-generalized-harness-release/01-CHECKPOINTS.md",
  "current_checkpoint": "CP-01-03",
  "next_action": "Phase 1 release complete. Start a new discuss pass for any further scope.",
  "allowed_paths": [
    "README.md",
    "CHANGELOG.md",
    "AGENTS.md",
    ".planning/",
    ".scratch/phase-state.json",
    ".opencode/",
    ".roo/",
    ".github/",
    "docs/",
    "harness/",
    "scripts/"
  ],
  "blocked_paths": [],
  "acceptance_criteria": [
    "Reviewer P1 findings for adapter alias, gate enforcement, release evidence, and core neutrality are addressed.",
    "README documents post-install commands and ready-to-use prompts.",
    "Release verification evidence records source checks, target matrix smoke, adversarial review, commit, and push."
  ],
  "verification": [
    "python3 -m unittest scripts/test_harness.py",
    "python3 scripts/harness.py check",
    "python3 scripts/harness.py check --worktree",
    "python3 scripts/release_smoke_test.py"
  ],
  "notes": [
    "This is a new repository copy created from the previous harness project.",
    "Core must remain stack-neutral and client-neutral.",
    "Skill packs are generic composable plugins."
  ],
  "updated_at": "2026-05-15T00:00:00Z",
  "updated_by": "codex"
}
```

**Output** (post-`--forward`, written via T0-A atomic primitive after creating `.scratch/phase-state.json.pre-0.bak`):

```json
{
  "phase": "done",
  "approved": false,
  "approved_by": "user",
  "approved_at": "2026-05-14T15:00:00Z",
  "plan_id": "generalized-harness-release-01",
  "automation_mode": "manual",
  "auto_selected": [],
  "summary": "Generalized harness release work is approved in a separate repository copy.",
  "state_path": ".planning/STATE.md",
  "plan_path": ".planning/phases/01-generalized-harness-release/01-01-PLAN.md",
  "checkpoint_path": ".planning/phases/01-generalized-harness-release/01-CHECKPOINTS.md",
  "current_checkpoint": "CP-01-03",
  "next_action": "Phase 1 release complete. Start a new discuss pass for any further scope.",
  "allowed_paths": [
    "README.md",
    "CHANGELOG.md",
    "AGENTS.md",
    ".planning/",
    ".scratch/phase-state.json",
    ".opencode/",
    ".roo/",
    ".github/",
    "docs/",
    "harness/",
    "scripts/"
  ],
  "blocked_paths": [],
  "acceptance_criteria": [
    "Reviewer P1 findings for adapter alias, gate enforcement, release evidence, and core neutrality are addressed.",
    "README documents post-install commands and ready-to-use prompts.",
    "Release verification evidence records source checks, target matrix smoke, adversarial review, commit, and push."
  ],
  "verification": [
    "python3 -m unittest scripts/test_harness.py",
    "python3 scripts/harness.py check",
    "python3 scripts/harness.py check --worktree",
    "python3 scripts/release_smoke_test.py"
  ],
  "review": [],
  "notes": [
    "This is a new repository copy created from the previous harness project.",
    "Core must remain stack-neutral and client-neutral.",
    "Skill packs are generic composable plugins."
  ],
  "state_schema_version": 2,
  "updated_at": "2026-05-15T00:00:00Z",
  "updated_by": "codex"
}
```

**Byte-exact diff:**
- Added `"review": [],` after the `verification` array close (line 39 in the pre, becomes lines 40-41 in the post if formatted with `json.dumps(..., indent=2, sort_keys=False)` preserving insertion order).
- Added `"state_schema_version": 2,` between `notes` close and `updated_at`.
- All other lines BYTE-IDENTICAL.
- Note: `scripts/lib/state.py:69` uses `sort_keys=True`, so the canonical re-emission will alphabetize. The migrator MUST use `sort_keys=True` to match the existing writer; the byte-exact diff above is shown in original-insertion-order for human review. The actual on-disk post-migration file is alphabetized. T0-1 acceptance includes a test asserting the alphabetized form round-trips through `json.loads`/`json.dumps(sort_keys=True)` losslessly.
- `.scratch/phase-state.json.pre-0.bak` is byte-identical to the pre-migration file.

### Byte-exact `--reverse` transformation (v2 → v0)

**Input:** the v2 file above.

**Output:** the original v0 file (byte-identical), achieved by:
1. Remove `"state_schema_version": 2` key.
2. Remove `"review": []` key.
3. Keep `"approved": false` (sub-decision 3a).
4. Re-emit with `sort_keys=True`.

**Result:** byte-identical to the pre-slice `.scratch/phase-state.json`. The round-trip `v0 → v2 → v0` property holds.

### Migrator acceptance tests (T0-1)

1. `--forward` on the current live fixture produces the Output above, and `.scratch/phase-state.json.pre-0.bak` is byte-identical to the Input.
2. `--reverse` on the Output produces a file byte-identical to the Input.
3. `--forward` is idempotent: applying it twice produces the same result as once (the second invocation is a no-op WRT content; `updated_at` is NOT re-stamped by the migrator, only by lifecycle CLI verbs).
4. The migrator uses the T0-A atomic primitive for ALL writes (the `.bak` AND the target file).
5. A `verification` entry not in the new allowlist (e.g., a pre-slice record with `"Validate that the docs look right"`) is moved to `review` with `{actor: "Validate", at: <updated_at>, evidence_path: "", summary: "Validate that the docs look right"}` and removed from `verification`.

---

## Artifact 6 — Breaking Change Ledger

Ready to copy under `CHANGELOG.md` → `## [Unreleased]` → `### Breaking`.

1. **`phase=done` no longer requires a specific `approved` value.** Schema's `done` branch drops the `approved` constant. Checker no longer asserts `approved is not False` for `done`. Records that previously failed under the inverted predicate now pass. Migration: `harness migrate state --forward` is idempotent; live state requires no edit beyond adding `state_schema_version: 2` and an empty `review: []`.
2. **`state_schema_version` field introduced** at top level of `.scratch/phase-state.json`. Value `2` is written by the migrator. Enforcement guard (refuse newer versions) is deferred to `02c-hardening` (R-2). Pre-slice records are treated as version `0`.
3. **`verification` allowlist tightened to 8 verbs**: `python3`, `git`, `jq`, `npx`, `pytest`, `bash`, `harness`, `make`. Removed: `Validate`, `Review`, `Inspect`, `Confirm`, `Roo` (the bare form that caused the `"Room is great"` false positive), `core-only`, `OpenCode-only`. Migrator relocates removed entries into the new `review` field.
4. **`review` field introduced** (new, ADR-004): `array<object>` of `{actor, at, evidence_path, summary}`. Required at top level; minItems 0.
5. **`allowed_paths` / `blocked_paths` accept full `fnmatch` globs.** Patterns containing `*`, `?`, `[`, `]` that previously matched zero paths (dead `fnmatch` import) now match per `fnmatch.fnmatchcase`. Precedence rule: `blocked_paths` always overrides `allowed_paths`.
6. **Direct edits to `.scratch/phase-state.json` emit a high-severity stderr warning** when the on-disk hash drifts from the audit log's last recorded `after_sha256`. The warning does NOT fail `harness check` (exit 0). Workflows that grep stderr for `warning:` need to allowlist this message or migrate to CLI verbs.
7. **New CLI verbs**: `harness phase set <phase>` and `harness phase approve`. Two verbs total on the lifecycle path. Zero required flags.
8. **Session lockfile**: `.harness/session.lock` is created by `phase set` / `phase approve` and removed on clean exit. `harness upgrade` refuses (exit 3) when the lockfile is present.
9. **`state_repair` writes `.bak` before rewriting** `.planning/STATE.md` and `.planning/ROADMAP.md`. Backups are `<original>.pre-repair.<UTC-compact-timestamp>.bak`. Not auto-deleted.
10. **`state_repair` aborts (exit 2) on unparseable `phase-state.json`** instead of swallowing `JSONDecodeError` and proceeding with empty dict.
11. **Paused phases (e.g., `02-skill-pack-expansion`) are first-class** in `.planning/STATE.md`'s managed `state-current` block under a `### Paused Phases` subsection. `state_repair` preserves them; does not delete as orphan content.

---

## Cross-ADR Consistency Check

Self-audit: each ADR's dependencies on other ADRs are satisfied, in this bundle, by the locked decision indicated.

| ADR | Depends on | Dependency satisfied by |
|---|---|---|
| ADR-001 | T0-A atomic primitive (for migrator writes); ADR-003a (since CLI verbs reference `state_schema_version` in audit entries) | T0-A is dependency-zero (spec §7). ADR-003a's CLI verbs do not modify `state_schema_version` (only the migrator does, per ADR-003b Artifact 3 system-only row); no conflict. |
| ADR-002 | none (orthogonal to live-gate semantics; touches `worktree.py` only) | N/A. |
| ADR-003a | ADR-001 (so CLI knows what `done` semantics to write); ADR-004 (so CLI knows verification shape when writing acceptance) | ADR-001's option 3 means `harness phase set done` writes no special `approved` value. ADR-004's split (verification + review) is honored by CLI: `phase set` does not write `verification` or `review` (those are user-editable per Artifact 3). |
| ADR-003b | ADR-003a (option 2 keeps direct-edit legal → most fields stay user-editable) | Matrix in Artifact 3 reflects option 2: lifecycle fields `cli`, narrative fields `user`. |
| ADR-004 | ADR-001 (verification entries are evaluated on every phase; allowlist must agree with `done` records); ADR-003a (CLI's `phase approve` does not write verification, so the contract is one-directional: user authors verification, CLI gates phase) | Current live fixture's verification entries all pass the new allowlist (all `python3 `). |
| ADR-005 | T0-A (atomic primitive for `.bak` + canonical rewrite); ADR-001 (paused phases must survive across schema versions) | T0-A primitive used for both `.bak` and target. Paused-phase representation is in `.planning/STATE.md` (Markdown), not `.scratch/phase-state.json`, so schema-version changes are orthogonal. |

**Critical artifact dependency**: the CLI contract (Artifact 1) is produced by ADR-003a + ADR-003b; the §10.2 smoke harness's golden file is derived from this artifact, not from running the implementation (spec §10.1, "how the CLI contract artifact breaks it"). Smoke can be authored in T0-3 in parallel with implementation.

**STATE_FILE_PATHS dependency**: T0-A's grep gate (spec §11 worked example) iterates `STATE_FILE_PATHS`. Artifact 2 locks the tuple as `(".scratch/phase-state.json",)`. T0-A MAY use this pre-decision default value; this ADR confirms it as the post-decision value, so no lockstep update is needed for the grep gate when ADR-003a lands.

**Spec non-goal compliance**: no MCP server, no signing, no Windows support, no LICENSE introduced by any ADR in this bundle. No new dependencies (`fnmatch` is stdlib; `argparse` is stdlib; `tempfile` is stdlib; `hashlib` is stdlib).

**Backward-compat compliance**: the current live fixture (`phase=done`, `approved=false`) is migratable via `--forward` (Artifact 5) and downgradable via `--reverse` (sub-decision 3a) byte-for-byte.

**Weak-model fit compliance**: ≤2 lifecycle verbs (ADR-003a); ≤8 verification verbs (ADR-004); one precedence rule (ADR-002 (a)); one preservation rule (ADR-005 option 3, "always preserve, always backup"). All four are one-sentence rules a Haiku-class agent can memorize.

**End of bundle.**
