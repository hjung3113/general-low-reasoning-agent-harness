# Hardening Slice Design Spec

Date: 2026-05-16
Author: Protocol Architect
Type: Design specification (gates ADRs, plans, and code)
Audience: harness maintainers, ADR authors, plan authors
Revision: r2 (post 3-persona adversarial review: Protocol Architect, Low-Reasoning Realist, Ops/Supply-Chain Hawk)

---

## 1. Status & Supersession

This document is the authoritative design input for the **production-internal hardening milestone** of the general low-reasoning agent harness.

It **supersedes** `docs/reviews/2026-05-16-final-tiered-actions-v2.md` (hereafter "v2 backlog") as the binding design source. The v2 backlog remains valid as raw triage notes, but every divergence between v2 and this spec is resolved in favor of this spec.

Downstream documents must consume this spec, not v2:

- ADR-001, ADR-002, ADR-003a, ADR-003b, ADR-004, ADR-005 (per §6) MUST cite this spec.
- The Phase 2b implementation plan (per §5) MUST cite this spec and the six ADRs.
- Issue Shape v2 (§11) replaces the Required Issue Shape in v2 backlog lines 493-536.

This spec does not authorize code changes by itself. Code work is gated on: this spec accepted, then six ADRs locked (single bundled session, see §6), then implementation plan approved through the standard `discuss -> plan -> execute -> done` flow.

---

## 2. Production-Internal Milestone Target

The hardening tag is a **production-internal milestone**, not a publicly-installable commercial release. "Production-internal" means: the harness is reliable enough for the maintainers and adjacent teams to depend on within this repository's workflow, with a documented internal contract, internal recovery posture, and internal upgrade story. It does NOT mean the artifact is packaged, licensed, or signed for third-party consumption.

The acceptance properties below are non-negotiable for the hardening tag. Properties intentionally deferred to the later `02c-hardening` slice (LICENSE, Windows launcher, packaging, supply chain) are listed in §2.7 and §12.

### 2.1 Correctness posture

- The live gate (`.scratch/phase-state.json`) is internally consistent: schema, checker, examples, docs, and shipped state agree on `phase=done` semantics. The current contradiction is documented in §3 and is a release blocker.
- Scope enforcement (`allowed_paths`, `blocked_paths`) has a single documented semantic and either implements it or explicitly rejects unsupported pattern forms with an actionable error. Silent mismatch is treated as a correctness defect, not a UX defect.
- Phase transitions cannot be performed by free-form file edits without the system either rejecting them or producing a loud, auditable warning. Self-attestation through `.scratch/phase-state.json` editing is removed from the default trust path (subject to ADR-003a's chosen variant; a "warn-not-fail" variant is on the ballot to preserve weak-model muscle memory).
- Free-text verification entries that do not execute anything are rejected as machine verification. Human review is a separate, typed evidence object.
- `state_repair` does not silently delete user content outside the managed `## Phases` block. Data preservation is a hard property; silent deletion is treated as data loss.
- `state_repair` MUST refuse to rewrite when `phase-state.json` is unparseable. The current code at `scripts/lib/state_repair.py:197` swallows `JSONDecodeError` and proceeds with an empty dict; that is the defect, not a feature.

### 2.2 Recovery posture

- A malformed `phase-state.json`, a duplicated managed-block slug, or an unparseable roadmap MUST produce a diagnostic exit, not an uncaught traceback.
- Recovery instructions for each diagnostic class are reachable from the diagnostic message (file path + recovery verb), not only from external README sections.
- Backward compatibility is bounded by the `state_schema_version` field. The field is INTRODUCED in T0-1 (sub-requirement) with initial value `1`. Only the enforcement guard ("refuse to operate on newer versions") is deferred to `02c-hardening`. ADR-001 MUST pick a version-bump value (e.g., `2`) for the new `done` shape.
- All managed JSON state writes (live gate, migration artifacts, audit sidecars) MUST use the atomic write primitive defined in T0-A.

### 2.3 Supply-chain posture (deferred from this slice but constrained)

- This slice does NOT add Cosign, SLSA, or signed release infrastructure (see §4). It DOES forbid regressions that would make future supply-chain hardening impossible (e.g., no new mutable network-side defaults).
- `installed-manifest.json` based upgrade flows are not extended in this slice. Their trust model is frozen pending a separate ADR outside this spec. See §2.8 Known residual risks.

### 2.4 Breaking-change policy

- The hardening slice is permitted to introduce breaking changes to (a) the `phase=done` contract, (b) verification field shape, (c) scope-pattern syntax, and (d) the direct-edit trust model.
- All four are pre-1.0 contract changes. The repository remains in 0.x and SemVer 0.x rules apply: minor version bumps may break.
- Migration tooling is REQUIRED for the live `.scratch/phase-state.json` (see §9 backward-compat criteria and T0-1 sub-requirements). Migration tooling for `.planning/**` content is NOT required if no schema is published over it.
- Each breaking change MUST be enumerated in CHANGELOG under a `Breaking` heading. The `Breaking` heading requirement applies ONLY to the `## [Unreleased]` (or equivalent unreleased) section as of this slice; backfilling `Breaking` subsections into historical released versions is out of scope and remains deferred to T3 / `02c-hardening`. CHANGELOG format itself is out of this slice (T3) but the discipline of listing each break under the unreleased section is in scope, and T0-1 creates the minimal `### Breaking` subsection skeleton under `## [Unreleased]` if not already present (see §7 T0-1 sub-requirements).

### 2.5 Support window

- This slice commits to one supported version line: the released hardening tag and `main`. There is no LTS, no backport policy, and no parallel stable line.
- Adopters on prior releases are expected to upgrade. There is no obligation to ship security fixes against prior tags.
- This is sufficient for an internal milestone. Multi-line support is explicitly a non-goal (see §4).

### 2.6 Quality bar discipline

- Every T0 and in-scope T1 row in §7 MUST land with: a regression test, a doc paragraph in `docs/protocol-spec.md`, and an end-to-end smoke that exercises core CLI plus both first-class adapters (see §10).
- T0-3 OWNS the creation of `docs/protocol-spec.md`. If the file does not exist when T0-3 begins (it does not as of this revision), T0-3 creates it; all other rows write paragraphs into the file that T0-3 produced.
- "Works on my Roo" is not acceptance. Acceptance requires the §10 verification protocol to pass on the same commit.

### 2.7 Public-installable status

This slice does NOT make the harness publicly installable. Specifically:

- No LICENSE file is added. Without a LICENSE, the repository is not legally redistributable; this is acknowledged and intentional for the internal milestone.
- No packaging metadata (`pyproject.toml` console entry points, sdist/wheel build, PyPI registration) is added.
- No Windows launcher, no CRLF normalization, no cross-OS launcher script. Documented canonical interpreter is `python3` on POSIX.
- No signed release artifacts (Cosign / SLSA / sigstore).

All four items are deferred to the `02c-hardening` slice. A downstream reader who needs a public-installable release MUST wait for `02c`, not retrofit this slice.

**On-disk footprint note (per ADR-bundle commit `b57250f`):** the hardening slice introduces operational state under `.harness/` — specifically `.harness/audit.log` (newline-delimited JSON), `.harness/session.lock`, and `.harness/backups/` (timestamped `.bak` artifacts, capped at 10 per original). These paths are enumerated by `OPERATIONAL_PATHS` (ADR-003a artifact) and MUST appear in the project `.gitignore` template. They are NOT packaging metadata and do not change the public-installable status; they are listed here so a downstream operator knows new directories will appear on disk after first lifecycle verb invocation.

### 2.8 Known residual risks

Carried forward without fix in this slice. Each is documented so adopters and future-`02c` planners do not rediscover them.

- **R-1: `installed-manifest.json` source RCE.** The upgrade path consumes a manifest from a mutable tag, and the manifest can name arbitrary source URLs. Threat model: an attacker who can write to the source mutable tag can execute code as the upgrading user. Mitigating fact: any file-write attacker already has code execution; the mutable-tag risk is the residual delta. This slice does NOT add SHA-pinning, signed manifests, or tag-immutability checks. Tracked for `02c-hardening`.
- **R-2: `state_schema_version` enforcement guard absent.** The field is introduced in T0-1 but older code that encounters a newer version will not refuse cleanly until `02c-hardening` adds the guard. Mitigating fact: only one schema version exists in the wild before this slice; the migration tool covers the immediate forward path.
- **R-3: Non-lifecycle adapter commands unverified.** §10.2 exercises only the 4 lifecycle commands per adapter; the 9 Roo non-lifecycle commands (e.g., `adr`, `bugfix`, `feature`) are quarantined. A static grep gate (see §10.2) prevents them from regressing the live-gate write paths, but their semantics are not part of this slice's acceptance.

---

## 3. Problem Statement

The current `main` branch ships a harness whose advertised contract is internally inconsistent and self-attesting in three ways at once.

- **Inverted `done` semantics.** `.scratch/phase-state.schema.json:347-399` declares that `phase=done` requires `approved=true`. `scripts/lib/check.py:431` reads `if state.get("approved") is not False:` and uses that condition to REJECT the record. Because `not False` is true for `True`, `None`, missing, and every non-`False` value, the checker rejects exactly the schema-valid case (`approved=true`) and accepts the schema-invalid cases. The paraphrase "checker requires `approved=false`" understates the defect: the checker's predicate is inverted relative to the schema's intent, so the only safely-shippable live state today is the schema-invalid `approved=false` recorded at `.scratch/phase-state.json:3`.
- **Dead glob import / silent zero-match.** `scripts/lib/worktree.py:1-90` imports `fnmatch` (line 4) but never calls it; `matches_any` at `scripts/lib/worktree.py:76-84` performs prefix-or-exact matching only, so any pattern containing `*` silently matches zero paths.
- **Self-attestation by construction.** The live state file at `.scratch/phase-state.json:20` ships `.scratch/phase-state.json` itself inside `allowed_paths`, meaning the default trust model permits an agent to author its own approval.
- **Free-text verification false positive.** `scripts/lib/check.py:99-111` declares `VERIFICATION_PREFIXES` containing `"Confirm "`, `"Review "`, `"Inspect "`, `"Validate "`, and bare `"Roo"`, so the string `"Room is great"` passes machine verification.

Together these defects mean the harness's three public promises (consistent live gate, enforced scope, non-self-attested approval) are currently false on the default install. A production-internal milestone cannot ship with these properties.

---

## 4. Non-Goals

This slice explicitly does NOT deliver, and any in-slice work that drifts toward these MUST be deferred:

- **MCP server / MCP transition tool.** Out of scope. A core CLI transition primitive is in scope (§6, ADR-003a); an MCP wrapper around it is not.
- **Signed releases (Cosign, sigstore, SLSA).** Out of scope. The slice MUST NOT regress against later signing.
- **Multi-tenant or hosted operation.** Out of scope. The harness is a per-repo CLI.
- **GUI, web UI, dashboard.** Out of scope.
- **Multi-line support / LTS.** See §2.5.
- **Cross-OS hardening (Windows launcher, CRLF normalization).** v2 T1-5/T1-6. Deferred to `02c-hardening`. Slice MAY document `python3` as canonical and explicitly mark Windows as unsupported in the supported matrix.
- **LICENSE, CONTRIBUTING, CODE_OF_CONDUCT, README split, CHANGELOG backfill.** v2 T2/T3 governance and DX. Deferred to `02c-hardening` (§2.7, §12).
- **Skill-pack content rewrites, SKILL length caps, few-shot expansion.** v2 T1-9/T1-10. Deferred. Note: T1-S (this slice) performs SURFACE-touch alignment of 3-5 SKILL files only, with no length cap and no few-shot expansion; that is not a content rewrite.
- **`installed-manifest.json` trust model rework, `--repo` URL pinning, supply-chain.** v2 T1-6, T2-5. Deferred. See §2.8 R-1.
- **OpenCode command parity with Roo.** v2 T3-14. Symmetry is semantic, not lexical (§10).
- **Profile/mode redesign, `.roomodes` rework.** v2 T3-12. Deferred.
- **Pyproject packaging, console entry points, mypy/ruff, CI matrix.** v2 T2-3/T2-4. Deferred.
- **Non-lifecycle adapter command behavior.** The 9 Roo commands outside the 4 lifecycle verbs (`discuss`, `plan`, `execute`, `done`) are not exercised by §10 and not part of this slice's acceptance. A static grep gate (§10.2) prevents them from regressing live-gate write paths; their semantics remain frozen at pre-slice behavior.

If a downstream plan finds it cannot complete an in-scope row without a non-goal, it MUST stop and request a spec amendment, not silently expand scope.

---

## 5. Resolution of Phase 2 Conflict

The repository currently has `.planning/phases/02-skill-pack-expansion/02-01-DISCUSS.md` recorded with an open scope on skill-pack expansion. `.planning/STATE.md:32` already says "No active Phase 1 release work remains. Start a new phase for further pack expansion." The recorded Phase 2 direction (skill-pack expansion) is incompatible with the work this spec authorizes (core hardening), because:

- Skill-pack expansion writes into `harness/skill-packs/**` and adapter overlays.
- The hardening slice writes into `scripts/lib/**`, `scripts/harness.py`, `.scratch/phase-state.schema.json`, and the live state file.
- The two scopes do not share files but do share the live gate. Running both in parallel would interleave breaking gate-contract changes with pack content changes, and the pack tests would be evaluating an unstable gate.

### Decision

Fork a new phase **`02b-hardening`** rooted at `.planning/phases/02b-hardening/`. Leave `02-skill-pack-expansion` in `discuss` status, **paused**. Do not delete or rename its directory.

Rationale:

- Numbering `02b` keeps the existing `02-skill-pack-expansion` directory untouched, preserving the recorded DISCUSS artifact as durable memory.
- The hardening work targets the same release window as Phase 2 would have, so renumbering it as Phase 3 would misrepresent priority.
- A separate phase ID isolates the live gate transitions of the hardening work from any future resumption of skill-pack expansion.
- Resumption path for `02-skill-pack-expansion` is unchanged: after `02b-hardening` is `done`, run a fresh `discuss` pass on `02` against the new gate contract.

Phase 2b inherits this spec as its discuss artifact equivalent (specifically: this spec replaces the standard `02b-01-DISCUSS.md` requirement for the initial pass; the planning step still produces `02b-01-PLAN.md` per the normal flow).

Paused-phase representation MUST be defined in `.planning/STATE.md` as a first-class state BEFORE T0-5 lands. `state_repair` (T0-5) MUST treat a paused phase as preserved-and-labeled, not as orphan content to delete. See T0-5 sub-requirements in §7.

---

## 6. Six Locked-Decision Targets (ADR-001, 002, 003a, 003b, 004, 005)

Every Decision-required row in §7 traces to exactly one ADR below. No implementation may begin on any §7 row until its referenced ADR is locked. ADRs are decided in one bundled session, not six sequential sessions (rationale: five of the six are coupled through the live state contract; deciding them in isolation produces inconsistent answers).

Each ADR below states the decision question and the candidate options. This spec does NOT pick. The ADR session picks.

### ADR-001 - `phase=done` Contract Semantics

Decision question: What does `phase=done` mean with respect to approval, and which field carries that meaning?

Candidate options:

1. `done` requires `approved=true` with `approved_by` and `approved_at`; schema is right, checker is wrong. Bump `state_schema_version` from 1 to 2 to mark the corrected interpretation.
2. `done` requires `approved=false` because `done` itself encodes a closed gate distinct from `execute` approval; checker is right, schema is wrong. Bump `state_schema_version` to 2.
3. **Drop the `approved` constraint from the `done` branch of the schema entirely.** Rationale: `approved` is per-transition state (it gates `execute` entry), not terminal state. `done` is the terminal state. Conflating them is the root of the inconsistency. Bump `state_schema_version` to 2. This option aligns naturally with the `state_schema_version` introduction in T0-1 and fits the weak-model muscle memory of "approval is something I do once on the way in, not something the closed phase keeps remembering".

Sub-decision (mandatory regardless of option): ADR-001 MUST name the new `state_schema_version` value the migration writes.

Sub-decision (mandatory IF option 3 is selected): the `--reverse` migrator (T0-1) MUST re-introduce a value for `approved` on the v1 → v0 downgrade path to satisfy the older schema's `done`-branch constraint. ADR-001 MUST pick exactly one of the following:

- **(3a)** `approved=false` — preserves the current live-state value byte-for-byte; the downgraded record will be schema-invalid under the OLD schema's stated intent but identical to what shipped pre-slice (matches the §3 `approved=false recorded at .scratch/phase-state.json:3` reality).
- **(3b)** `approved=true` — interprets `done` as approved completion; the downgraded record is schema-valid under the OLD schema's stated intent but does not round-trip an existing pre-slice file's `approved=false` value.
- **(3c)** Refuse downgrade with a documented error citing the dropped-field semantics and instructing the operator to hand-edit if downgrade is genuinely required.

If option 1 or option 2 is selected, this sub-decision does not apply (the field is retained on the `done` branch and the `--reverse` value is determined by the source record).

Decision-source: T0-1 in §7.

### ADR-002 - Scope Pattern Syntax

Decision question: What syntax does `allowed_paths` / `blocked_paths` accept, and what happens to inputs outside that syntax?

Candidate options:

1. Prefix + exact-only (current behavior). Patterns containing glob metacharacters (`*`, `?`, `[`, `]`, `**`) are rejected at load time with a clear error pointing at the offending entry.
2. Full glob via `fnmatch` (matches the dead import in `scripts/lib/worktree.py:4`). Documented behavior for `**`, `*.md`, `dir/`, trailing slash.
3. `pathspec`-style gitignore semantics, including negation. Strictly stronger than option 2.
4. Two-field split: `allowed_prefixes` (current semantic) and `allowed_globs` (new, opt-in).

Sub-decision (mandatory): blocked-vs-allowed precedence rule. Pick one:

- **(a) Entry-level precedence**: `blocked_paths` always overrides `allowed_paths` when both match the same path.
- **(b) Longest-match**: the more specific entry (longer literal prefix, or more anchored glob) wins, regardless of which list it appears in.
- **(c) Order-of-declaration**: later entries override earlier entries within the union of both lists.

Spec preference is (a) for low-reasoning agent legibility, but the ADR session decides.

Decision-source: T0-2 in §7.

### ADR-003a - Transition Primitive (CLI verbs + trust model + direct-edit policy)

Decision question: How does a phase transition (e.g., `plan` -> `execute` with approval) happen, and what is the trust model for direct edits to `.scratch/phase-state.json`?

Hard constraints on the candidate option set:

- **≤2 lifecycle verbs + ≤1 operational verb** (e.g., `harness phase set`, `harness phase approve` as lifecycle verbs; `harness session unlock` as an operational verb for lockfile-staleness recovery). The operational verb MUST NOT write `.scratch/phase-state.json`; it manipulates only operational state (e.g., `.harness/session.lock`). Per ADR-bundle commit `b57250f` (revision note G1-B), the lifecycle/operational distinction is explicit: lifecycle verbs advance phase state; the operational verb is a recovery utility.
- **Zero required flags** on the lifecycle path. Optional flags allowed. Rationale: a low-reasoning agent that cannot remember a flag fails the transition; muscle memory should be "type the verb, answer the prompt".
- Cryptographic signing is OUT (already out of scope per §4); it is removed from this ballot.

Candidate options:

1. **CLI-only**: the new CLI is the only sanctioned path; direct edits to `.scratch/phase-state.json` cause the checker to hard-fail with a diagnostic naming the CLI verb that would have worked.
2. **CLI + warn**: the new CLI is sanctioned, direct edits still pass the checker but produce a high-severity warning naming the missing audit sidecar entry.
3. **Thin wrapper CLI + direct-edit allowed with confirmation**: the new CLI exists, AND direct file edits remain a first-class path subject to a single confirmation prompt at next check (e.g., "Detected manual edit to `.scratch/phase-state.json`; record as audited? [y/N]"). Checker WARNS but does not fail. Rationale: preserves the muscle memory of every existing SKILL and adapter command without forcing rewrites; meets Realist concern about weak-model fit.

Sub-decisions (mandatory):

- **Session lockfile.** ADR-003a establishes `.harness/session.lock` as the convention for an active session lockfile. The lockfile is touched by the CLI on entry and removed on clean exit. The upgrade path (per D2) detects this file and refuses to proceed mid-session with a clear instruction to finish or kill the session. The chosen transition primitive MUST be compatible with this convention.
- **State file location.** If the chosen option moves the state file out of the working tree (e.g., to `.harness/state.json`), `--remove-install-state` MUST handle BOTH the legacy `.scratch/phase-state.json` path AND the new path, or REFUSE with a diagnostic naming both paths. No silent partial cleanup.
- **`STATE_FILE_PATHS` artifact (mandatory).** ADR-003a's locked output MUST include the post-decision authoritative list of state file paths, named `STATE_FILE_PATHS` (a tuple/list of relative paths). This list is the single source of truth that the §10.2 grep gate, T1-S SKILL updates, and the uninstall flow (`--remove-install-state`) MUST track. If the ADR keeps the legacy path, `STATE_FILE_PATHS = (".scratch/phase-state.json",)`. If the ADR relocates, the list contains both the new path and any legacy path that remains in scope for migration/uninstall. The list is published as part of the CLI contract document (see "Critical artifact" below) so downstream rows do not re-derive it.

Decision-source: T0-3 in §7. ADR-003a constrains the option space of ADR-003b.

### ADR-003b - Field Ownership Matrix

Decision question: For each field in the `phase-state.json` schema, who may write it (user, CLI, system), and under which phase?

Output: a matrix with rows = field names (`phase`, `approved`, `approved_by`, `approved_at`, `notes`, `summary`, `acceptance_criteria`, `verification`, `state_schema_version`, etc.), columns = (user-editable, CLI-only, system-only, phase-restricted), cells = yes/no + phase scope.

ADR-003b's option space is constrained by ADR-003a's chosen trust model: option-3 of ADR-003a (allow direct edits with confirmation) forces more fields into the user-editable column; option-1 (CLI-only) allows ADR-003b to lock more fields to CLI-only.

Decision-source: T0-3 in §7 (shares the row; field-ownership is the second half of the transition primitive's contract).

### ADR-004 - Verification Contract Shape

Decision question: How does the schema distinguish runnable machine verification from human review evidence, and what shape does each take?

Candidate options:

1. Two fields: `verification` (machine, array of strings matching a tightened allowlist that requires an executable prefix and a registered command verb) and `review` (human, array of objects with `actor`, `at`, `evidence_path`, `summary`).
2. One field with discriminated union: each entry is either `{type: "command", cmd: "..."}` or `{type: "review", actor, at, evidence_path, summary}`.
3. Tighten the string allowlist in place (remove `"Confirm "`, `"Review "`, `"Inspect "`, `"Validate "`, `"Roo"` from `scripts/lib/check.py:99-111`), and add a parallel `review_evidence` field for human notes. Example tightened allowlist (per ADR-bundle commit `b57250f`, D-G4): **7 verbs** — `python3`, `git`, `jq`, `npx`, `pytest`, `harness`, `make`. `bash ` is explicitly EXCLUDED because a bare `bash ` prefix permits arbitrary shell content; entries previously using `bash scripts/foo.sh` migrate to `make foo` or `python3 scripts/foo.py`.
4. Move command allowlist into a config file (`.harness/verification-prefixes.json`) and require the schema to point at a versioned allowlist.

Hard sub-constraints on whichever option wins:

- (i) The rejection diagnostic for a non-conforming verification entry MUST enumerate the allowed verbs INLINE in the error message. The agent reading the error must not have to open another file to learn the legal set.
- (ii) The allowlist MUST contain ≤ 8 verbs. Adding a 9th requires a separate ADR. Rationale: a low-reasoning agent cannot reliably select from a longer menu.
- (iii) The error message MUST cite the path/doc where the allowlist is defined (e.g., `docs/protocol-spec.md#verification-allowlist`), so an agent that wants to extend the allowlist knows where to file the change.

Decision-source: T0-4 in §7.

### ADR-005 - `state_repair` Preservation Policy

Decision question: When `state_repair` encounters content outside the managed `## Phases` block in `.planning/STATE.md` (or other managed files), what does it do?

Candidate options:

1. Preserve verbatim outside the managed markers; never rewrite non-managed regions.
2. Refuse to operate when non-managed content is detected; require the user to first remove or relocate it.
3. Preserve verbatim AND write a backup file (`.bak` with timestamp) before any rewrite. **Backup location (per ADR-bundle commit `b57250f` revision G1-D): `.harness/backups/<basename>.pre-repair.<ISO-8601-nanos>.<pid>.bak`** — RELOCATED out of `.planning/` (which is user-edit territory and frequently `git add .`-ed) into operational state under `.harness/` (covered by `OPERATIONAL_PATHS` and the project `.gitignore` template). The `.bak` write uses the T0-A atomic primitive AND `O_EXCL`; if the target `.bak` path already exists the write aborts before touching the original. **Retention cap: 10 most recent per original**, auto-pruned on each `state repair` write after successful new-backup creation.
4. Detect content outside markers as a recoverable error class, route through a new `state repair --interactive` flow that asks the user.

Sub-decision (mandatory if option 3 is selected): backup path policy. ADR-005 MUST select between:
- **(3-loc-a)** `.planning/`-co-located backups (`.planning/<basename>.<timestamp>.bak`). Simpler but at risk of accidental `git add`.
- **(3-loc-b)** `.harness/backups/`-relocated backups (per ADR-bundle G1-D). Scoped operational state, gitignored by default. **Spec preference** post-bundle revision.

Decision-source: T0-5 in §7. This is a new T0 promoted from v2 T1-4 / v2 backlog footnote because it represents silent data loss, not recovery.

### ADR session protocol

The six ADRs MUST be decided in a single bundled session producing six files under `docs/adr/` (path naming left to plan). The session order is: ADR-001, ADR-002, ADR-004, ADR-003a, ADR-003b, ADR-005.

Rationale for order: state semantics (001) before transition tooling that mutates state; verification shape (004) before transition tooling that records it; ADR-003a before ADR-003b because the trust model constrains the field-ownership matrix; preservation policy (005) last because it is orthogonal to the live gate.

**Critical artifact**: ADR-003a + ADR-003b MUST produce, as part of the ADR session output (not later in T0-3 implementation), a written **CLI contract document** containing:

- Final verb names.
- Input JSON shape per verb (stdin or args).
- Output JSON shape per verb (stdout).
- Exit codes per verb, named (e.g., `0 = ok`, `2 = invalid state`, `3 = lockfile present`).
- Canonical error message strings (rejection diagnostics, lockfile-refuse message).

The §10.1 smoke golden file is DERIVED FROM this contract, not from running the implementation. This is what breaks the circular dependency in §10.

The session output is a single PR that lands all six ADRs + the CLI contract together. Partial ADR landing is forbidden.

---

## 7. Hardening Slice Scope

The slice covers exactly the rows below. No additions without a spec amendment.

| ID | Title | Layer | ADR dep | Size | Risk | Reversibility |
|---|---|---|---|---|---|---|
| T0-A | Atomic write primitive for all managed JSON state | core | none | S | low | yes |
| T0-1 | `phase=done` contract aligned across schema, checker, live state, docs, tests; introduce `state_schema_version`; migrator with `--reverse` | core | ADR-001 | M | med | partial |
| T0-2 | Scope pattern syntax decided, implemented, tested; unsupported patterns fail loudly | core | ADR-002 | M | med | yes |
| T0-3 | Core CLI phase-transition primitive; direct-edit trust model per ADR-003a; field ownership per ADR-003b; create `docs/protocol-spec.md` | core | ADR-003a, ADR-003b | L | high | partial |
| T0-4 | Verification contract split: machine commands vs human evidence; free-text rejected; inline-enumerated diagnostic | core | ADR-004 | M | med | yes |
| T0-5 | `state_repair` preserves non-managed content per ADR-005; paused-phase first-class; refuse on unparseable input | core | ADR-005 | S | low | yes |
| T1-1 | `check --worktree` wired as required step at the workflow boundary chosen by ADR-003a | core/adapter | ADR-003a | S | low | yes |
| T1-S | SKILL surface alignment: update the 3-5 SKILL files referencing `.scratch/phase-state.json` direct-edit or old `approved` semantics; surface-touch only, no length cap, no few-shot expansion | skill-pack | T0-3 contract | S | low | yes |
| T1-M | Malformed state recovery: `phase-state.json` parse failures, duplicate slugs, broken roadmap produce diagnostic exit not traceback; `state_repair` refuses on unparseable input | core | none | M | low | yes |

Layer legend: `core` = `scripts/`, `.scratch/` schema, `docs/protocol-spec.md`. `adapter` = `.roo/commands/`, `.opencode/commands/`. `core/adapter` = primary change in core, mirrored hooks in adapters. `skill-pack` = `harness/skill-packs/**`.

Size legend: S = under 1 day of focused work, M = 1-3 days, L = 3-5 days. These are scoping estimates, not commitments.

Risk legend:
- low = isolated, well-understood, no live-gate semantics change.
- med = touches the live-gate contract; existing Phase 1 records may need migration.
- high = changes how transitions happen at all; user muscle memory and adapter commands depend on it.

Reversibility legend:
- yes = a follow-up release can restore prior behavior without data migration.
- partial = follow-up can restore behavior but recorded state from the new version cannot be downgraded except via the row's `--reverse` migrator.
- no = irreversible (none in this slice).

### Per-row notes & sub-requirements

**T0-A (atomic write primitive).**

- Scope: replace all `path.write_text(...)` calls that target managed JSON state with `NamedTemporaryFile(dir=parent) + fsync + os.replace`. Parent-dir same-filesystem requirement enforced by the helper.
- Migration writes (T0-1) MUST write the new path BEFORE unlinking the legacy path. No window where neither file exists.
- T0-A is dependency-zero. It can land FIRST and SHOULD land first. All other T0 rows depend on T0-A for state writes; the §8 graph is updated accordingly.
- Acceptance: a single helper `scripts/lib/atomic.py:write_json_atomic(path, data)` exists; every site that previously called `path.write_text` for managed JSON is migrated; a regression test injects a crash between write and replace and asserts the legacy file is intact.
- Acceptance (grep gate cross-reference): the §11 T0-A worked example's grep gate iterates over BOTH the `STATE_FILE_PATHS` list AND the `OPERATIONAL_PATHS` tuple defined by ADR-003a (see §6 ADR-003a sub-decisions). Per ADR-bundle commit `b57250f` (revision G1-C), `OPERATIONAL_PATHS = (".harness/audit.log", ".harness/session.lock", ".harness/backups/")` enumerates operational state that is also written atomically (or with `O_EXCL` discipline) and must be covered by the same grep gate. T0-A MAY land before ADR-003a locks by using the pre-decision defaults `STATE_FILE_PATHS = (".scratch/phase-state.json",)` and `OPERATIONAL_PATHS = ()`; once ADR-003a locks, the grep gate, T1-S, and the uninstall flow MUST be updated in lockstep to the ADR-003a-published lists.

**T0-1 (`phase=done` contract).**

- Sub-requirement: introduce the `state_schema_version` field in the schema with initial value `1`. The ADR-001 chosen `done` shape bumps the value (e.g., to `2`). The ENFORCEMENT GUARD (refuse newer versions) is NOT in this row; it is deferred to `02c-hardening`. See §2.2.
- Sub-requirement: the migrator writes `.scratch/phase-state.json.pre-<old-schema-version>.bak` BEFORE calling `os.replace`. The backup is byte-identical to the pre-migration file.
- Sub-requirement: the migrator supports `--reverse` for at least the version 1 → 0 downgrade path (where "0" is the pre-`state_schema_version` shape, treated as version 0 for the purpose of migration arithmetic). The downgrade path MAY drop fields the older shape did not understand; it MUST not silently corrupt. The value the reverse migrator writes for `approved` (if ADR-001 option 3 is selected and the field was dropped from the `done` branch) is dictated by the ADR-001 sub-decision (3a / 3b / 3c); if option 1 or 2 is selected, the value round-trips from the source record.
- Sub-requirement: all state writes performed by the migrator use the T0-A primitive.
- Sub-requirement: the existing test that asserts "`done` requires `approved=false`" (currently in `scripts/test_harness.py`) MUST be deleted or rewritten. Deleting a passing test is normally a smell; this is intentional and is noted in the PR description.
- T0-1 is `partial` reversible because the live state is rewritten to the new shape; the `--reverse` migrator and the `.pre-*.bak` artifact are the mitigations.
- Sub-requirement (migrator order-of-operations, per ADR-bundle commit `b57250f`): the migrator MUST follow this numbered protocol on every forward and reverse migration:
  1. Write `.harness/backups/<basename>.pre-repair.<ISO-8601-nanos>.<pid>.bak.resume.json` sidecar containing `{pre_hash, expected_post_hash, target_path, migrator_version, started_at}` via T0-A atomic-write.
  2. Write `.harness/backups/<basename>.pre-repair.<ISO-8601-nanos>.<pid>.bak` (byte-identical copy of the pre-migration target) using `os.open(..., O_WRONLY | O_CREAT | O_EXCL, 0o644)`. On `FileExistsError`, abort with a diagnostic instructing the operator to run `harness migrate state --resume` or to remove the stale backup.
  3. Write the new target shape via the T0-A atomic-write primitive.
  4. Delete the sidecar `.resume.json` (signaling clean completion).

  Recovery: `harness migrate state --resume` reads any surviving sidecar to determine which step crashed and resumes from the recorded state. A sidecar present on a clean tree indicates an incomplete prior migration; the resume verb is the only sanctioned recovery path. The retention cap (10 per original) applies to the `.bak` artifacts; sidecars are not retained beyond the lifetime of the migration they describe.
- Sub-requirement (CHANGELOG `Breaking` skeleton): T0-1 MUST ensure `CHANGELOG.md` exists at repo root and contains a `## [Unreleased]` (or already-present equivalent unreleased) section with a `### Breaking` subsection skeleton. If the file already exists with an unreleased section but no `### Breaking` subsection, T0-1 adds the subsection. T0-1 appends the entry for the `done` contract change (and any other breaking change it introduces, e.g., `state_schema_version` introduction if interpreted as breaking) under that subsection. Backfilling `Breaking` subsections into historical released versions is OUT of scope per §2.4.

**T0-3 (CLI transition primitive).**

- Highest-risk row in the slice. Changes the workflow ergonomics every adapter, every SKILL pack, and every human contributor has internalized.
- T0-3 OWNS `docs/protocol-spec.md`. If absent, T0-3 creates it.
- Acceptance row (LOCKED D2, **session lockfile refuse**): the CLI MUST detect `.harness/session.lock` and refuse to apply a mid-session upgrade with a clear diagnostic naming the lockfile path and recovery verb. No atomic file-swap engineering is required in this slice.
- Implementation begins ONLY after the ADR-003a + ADR-003b session output (including the CLI contract document) is locked.

**T0-5 (`state_repair` preservation).**

- Sub-requirement: `state_repair` MUST represent paused phases (e.g., `02-skill-pack-expansion`) as a FIRST-CLASS state, not as orphan content to delete. The paused-phase representation MUST be defined in `.planning/STATE.md` before T0-5 lands.
- Sub-requirement: `state_repair` MUST refuse to rewrite when `phase-state.json` is unparseable. Today, `scripts/lib/state_repair.py:197` swallows `JSONDecodeError` and proceeds with an empty dict; the row is not done until that branch raises a diagnostic exit and `state_repair` aborts cleanly.

**T1-1 (`check --worktree` wiring).**

- Depends on T0-3 because "wired at the workflow boundary" presupposes a defined boundary; ADR-003a defines whether the boundary is the CLI verb, a hook, or both.

**T1-S (SKILL surface alignment).**

- Scope: the 3-5 SKILL files in `harness/skill-packs/**` that reference direct-edit of `.scratch/phase-state.json` or the old `approved` semantics. Update each to reflect the ADR-003a/003b transition primitive and ADR-001 `done` shape.
- NO length cap. NO few-shot expansion. NO content rewrites. Surface-touch only: rename verbs, update example snippets, fix outdated `approved` references.
- Dependency: T0-3 contract artifact (the CLI contract document produced by the ADR session). T1-S MAY begin once the contract is locked, in parallel with T0-3 implementation.
- Reversibility: yes (text edits in SKILL files; revertable in a follow-up PR).

**T1-M (malformed state recovery).**

- No ADR dependency: "do not crash on malformed input" is not a decision; only the diagnostic copy is, and diagnostic copy does not gate code.
- Acceptance: `state_repair` MUST refuse to rewrite when `phase-state.json` is unparseable (current code at `scripts/lib/state_repair.py:197` swallows `JSONDecodeError` and proceeds with empty dict — that is the defect). This acceptance is shared with T0-5.

### Out of slice (deferred to `02c-hardening`)

v2 T1-2 (approval metadata trust level), T1-3 (`state_schema_version` enforcement guard), `installed-manifest.json` SHA-pinning, LICENSE, Windows launcher, packaging, signed releases. Both v2 T1-2 and T1-3 are real but neither blocks the §3 problem.

---

## 8. Execution Order with Rationale

The slice executes as a dependency graph, not a queue. Independent rows MAY proceed in parallel under the §10 verification protocol; dependent rows MUST wait.

```
                        T0-A  (atomic write primitive, dependency-zero, lands FIRST)
                          |
                          v
                [ADR session: 001, 002, 003a, 003b, 004, 005
                 + CLI contract artifact]
                                       |
              +------------+-----------+-----------+------------+
              |            |           |           |            |
            T0-1         T0-2        T0-4        T0-5         T1-M
         (ADR-001)    (ADR-002)   (ADR-004)   (ADR-005)    (no ADR)
              |            |           |
              +-----+------+-----------+
                    |
                  T0-3  (ADR-003a + ADR-003b; needs T0-1 + T0-4 landed first)
                    |
              +-----+-----+
              |           |
            T1-1         T1-S
        (wires CLI)  (SKILL surface)
```

**Critical path (explicit):**

```
ADR session (incl. CLI contract artifact)
   -> T0-1 + T0-4 (parallel)
   -> T0-3
   -> T1-1
   -> §9.1 low-reasoning agent harness run
```

T0-A precedes the ADR session as a sequencing convenience; it is not on the critical path of decision-making, but every state-writing row depends on it, so landing it first removes a class of conflicts.

Rationale:

- **T0-A first.** Dependency-zero, low-risk, removes a class of partial-write defects from every later row's failure modes.
- **ADR session is a single hard barrier.** No row begins until all six ADRs land AND the CLI contract artifact is written. This is enforced because ADR-003a changes the workflow boundary that every other row's tests will run through, and the contract is what the §10 smoke golden file is derived from.
- **T0-1, T0-2, T0-4, T0-5, T1-M run in parallel after the ADR session.** None mutates the others' code surface. T0-1 touches schema + checker + live state. T0-2 touches `worktree.py` + schema. T0-4 touches checker + schema. T0-5 touches `state_repair.py`. T1-M touches input boundaries (`json.loads` call sites, managed-block parser).
- **T0-3 sequences after T0-1 and T0-4.** T0-3 introduces a CLI that *sets* `phase` and *writes* verification entries. Building that CLI against a still-ambiguous `done` semantic or a still-loose verification shape would force rewrites mid-row. T0-3 depends on T0-1 + T0-4 OUTPUTS but its CONTRACT exists at end of ADR session; SKILL alignment (T1-S) can therefore begin in parallel with T0-3 implementation as soon as the contract is locked.
- **T1-1 sequences after T0-3.** "Wire `check --worktree` to the workflow boundary" requires the workflow boundary to exist.
- **T1-S sequences after the CLI contract artifact (not after T0-3 implementation).** SKILL files reference verbs and shapes; once verbs and shapes are locked, SKILLs can be aligned. They are re-verified against the running T0-3 in §10.
- **T1-M is independent of all the above.** It targets failure modes that exist regardless of contract shape. It SHOULD land early because it makes every other row's failure modes more debuggable.

Adapter mirroring (updating `.roo/commands/*.md` and `.opencode/commands/*.md` to call the new CLI) is part of T0-3 and T1-1, not a separate row.

---

## 9. Quantified Pass Criteria

### 9.1 Low-reasoning agent fit (actor model)

"Low-reasoning agent" in this spec is operationalized as: Anthropic Claude Haiku (4.5 or successor), single-turn or short-chain, no system prompt augmentation beyond what an adapter ships, no human-in-the-loop correction during execution.

**Pass criteria for the slice as a whole:**

- A fixed scenario script (`scripts/smoke/low_reasoning_scenario.py`, to be created by the implementation plan, not by this spec) executes the four canonical flows: `discuss -> plan`, `plan -> execute`, `execute -> done`, and `state repair after corruption`.
- The scenario runs **N = 50 trials per flow** (200 total). Pass rate per flow MUST be **≥ 80% (40/50)**.
- A trial passes iff: the agent reaches the next phase OR explicitly raises a `needs-info` request grounded in the actual diagnostic.
- A trial fails iff the agent loops, fabricates approval, or proceeds despite a gate rejection.

**Determinism & flake controls (mandatory):**

- Temperature = 0 OR seed-fixed (whichever the SDK supports; spec accepts either).
- Deterministic fixtures: fixture repo state byte-identical across trials; no clock-dependent assertions in pass condition.
- Flake-retry policy: max 2 retries per failed trial. Retries are recorded in the trial log (raw fail count, retry pass count) and the per-flow pass rate is computed on the FINAL outcome. A trial that needed retries is still recorded as a "noisy" trial.
- Per-trial budget cap: 60 seconds wall-clock AND 20k input tokens AND 4k output tokens. A trial that exceeds any cap is recorded as a failure (not a timeout-skip).

**Alternative framing (recorded baseline):** the implementation plan MAY substitute "no regression vs recorded baseline ≥ X%" where X is captured on the pre-slice harness against the same scenario script. If chosen, the baseline MUST be captured and committed BEFORE the slice's first code change lands.

The 80% threshold (or the no-regression equivalent) is a release blocker for the hardening tag, not for individual row merges.

**Trial logs** are committed under `.planning/phases/02b-hardening/evidence/` for the release record.

**Budget escape clause:** if the scenario harness itself cannot be built within the slice budget, the slice MUST land with a documented gap and a deferred row in `02c-hardening`, NOT with a silent unmeasured "feels better" claim. The spec rejects "we didn't measure but it seemed fine" as acceptance evidence.

### 9.2 Backward-compat criteria for Phase 1 records

The existing Phase 1 records (`.planning/phases/01-generalized-harness-release/`, `.planning/STATE.md`, the historical `.scratch/phase-state.json` snapshot at `done` recorded 2026-05-15) MUST remain readable and re-checkable after the slice lands.

Concretely:

- A `harness migrate state` command (verb name left to plan; see T0-1) MUST convert the live `.scratch/phase-state.json` from its current shape (`phase=done, approved=false`) to whatever shape ADR-001 picks, idempotently.
- Running `harness check` against the migrated file MUST pass without manual edits.
- The migrator MUST write a `.pre-<old-schema-version>.bak` artifact before `os.replace` (T0-1 sub-requirement) and MUST use the T0-A atomic primitive.
- The migrator MUST support `--reverse` for at least the version 1 → 0 downgrade (T0-1 sub-requirement).
- Existing checkpoint files, plan files, and DISCUSS artifacts under `.planning/phases/01-*/` MUST NOT require edits.
- A regression test fixture (a captured pre-slice snapshot under the test tree; exact path left to the implementation plan) captures the pre-slice live state byte-for-byte; a test asserts the migrator converts it to a post-slice-valid state without loss of `plan_id`, `approved_by`, `approved_at`, `summary`, `state_path`, `plan_path`, `checkpoint_path`, `current_checkpoint`, `next_action`, `acceptance_criteria`, `verification`, `notes`, `updated_at`, `updated_by`.

### 9.3 Adapter-neutral pass criteria

The §10 smoke MUST pass on the same commit for: core CLI directly, Roo adapter commands (lifecycle 4 only of the 13 files in `.roo/commands/`), and OpenCode adapter commands (the 4 files in `.opencode/commands/`).

"Roo first-class" and "OpenCode first-class" remain the only two adapter targets in scope. Adding a third adapter is out of slice.

### 9.4 Regression test coverage floor

- T0-A: at least 1 test injecting a crash between temp-write and `os.replace` and asserting the original file is intact; 1 test asserting same-filesystem invariant; 1 test asserting the helper rejects non-managed paths.
- T0-1: at least 1 test asserting the new `done` semantic accepts a valid record; 1 asserting it rejects an invalid one; 1 asserting the migrator handles the legacy fixture; 1 asserting the migrator writes the `.pre-*.bak` BEFORE `os.replace`; 1 asserting `--reverse` round-trips losslessly for the documented downgrade scope.
- T0-2: at least 4 tests covering: prefix match, blocked overriding allowed (per ADR-002 sub-decision), the syntax decided by ADR-002 (positive case), and the rejection path for unsupported syntax (negative case).
- T0-3: at least 1 test asserting the CLI transition succeeds on a valid input; 1 asserting it refuses an invalid input; 1 asserting the direct-edit detection or warning per ADR-003a; 1 asserting the session-lockfile refuse path (per LOCKED D2); 1 asserting `--remove-install-state` handles both legacy and new state paths if ADR-003a moves the file.
- T0-4: at least 1 test per accepted verification form, plus 1 asserting `"Room is great"` (the canonical false-positive from §3) is rejected, plus 1 asserting the rejection diagnostic enumerates the allowed verbs inline.
- T0-5: at least 1 test asserting non-managed content outside `## Phases` is preserved per ADR-005; 1 asserting backup is created if ADR-005 picks option 3; 1 asserting paused phases are represented as first-class state, not deleted as orphan content; 1 asserting `state_repair` refuses on unparseable input.
- T1-M: at least 1 test per failure class (malformed JSON, duplicate managed-block slug, unparseable roadmap heading).
- T1-1: at least 1 test asserting `check --worktree` runs at the chosen boundary and fails CI when a forbidden path changes.
- T1-S: at least 1 lint/grep test asserting no SKILL file in the updated set still references the old direct-edit verb pattern or the old `approved` semantic.

The existing test that asserts `done requires approved=false` (currently in `scripts/test_harness.py`) MUST be deleted or rewritten as part of T0-1; this is called out because deleting a passing test is normally a smell and reviewers should know it is intentional here.

---

## 10. Adapter-Neutral Verification Protocol

### 10.1 The circular dependency, and how the CLI contract artifact breaks it

A naive reading of v2 backlog produces a circular dependency: "core-only smoke" implies a core invocation path, but the only core invocation path today is "edit JSON files and call `harness check`", which is exactly the trust model T0-3 changes. If "core-only smoke" requires the new CLI, but the new CLI is itself the deliverable being smoked, the smoke cannot validate the deliverable.

**Resolution (no sleight of hand):** the ADR session (ADR-003a + ADR-003b) produces a written **CLI contract document** as part of its session output, BEFORE any T0-3 implementation begins. The contract defines verbs, input/output JSON shapes, exit codes, and canonical error message strings (see §6 ADR session protocol).

The §10.2 smoke harness's golden file is DERIVED FROM the CLI contract document, not from running the implementation. The smoke therefore validates that the implementation matches the contract, rather than validating that the implementation matches itself. The circle is broken because the contract precedes the implementation and the test.

### 10.2 Smoke stages

The smoke harness (`scripts/release_smoke_test.py`, extended; this file already exists per Phase 1 verification record) gains three sequential stages:

1. **Core-only stage:** invoke the new CLI directly with no adapter context. Run a scripted `discuss -> plan -> execute -> done` flow against a fixture repository under `tmp/`. Pass criteria: every transition succeeds, every check passes, and the resulting state matches the golden file derived from the CLI contract.
2. **Roo stage:** invoke the same scripted flow through ONLY the 4 lifecycle commands in `.roo/commands/` (`discuss`, `plan`, `execute`, `done`). The other 9 Roo commands (`adr`, `bugfix`, `feature`, etc.) are NOT exercised; they are quarantined. Each lifecycle Roo command MUST resolve to the same core CLI verb the core-only stage used. Pass criteria: same as core-only.
3. **OpenCode stage:** invoke the same flow through `.opencode/commands/*.md` (4 commands: `discuss`, `plan`, `execute`, `done`). Pass criteria: same as core-only.

**Static grep gate** (mandatory, runs as a CI step before the smoke stages): no non-lifecycle adapter command file may reference `.scratch/phase-state.json` (or the post-ADR-003a state file path, if moved) on any write path. The grep is conservative: it greps for the file path appearing in the same file as a `>`, `write`, `replace`, or similar write verb. The grep gate's allowlist is exactly the files touched by T1-S; an entry outside that allowlist fails CI. This prevents the quarantined commands from regressing the live-gate write paths while the slice is in flight.

Any of the three smoke stages failing fails the slice acceptance.

### 10.3 Why this breaks the circle

The new CLI does not need to exist to define what "core-only" means; the CLI contract document defines it, and the contract is part of the ADR session output, not a side effect of implementation. The CLI's implementation is verified by the same smoke that verifies the adapters, against the same fixture, against the same contract-derived golden file.

Adapter symmetry becomes a property ("the adapter resolves to the same core verb defined in the contract"), not a count ("the adapter has the same number of commands").

### 10.4 What "adapter symmetry" means after this spec

- Both adapters MUST expose the four lifecycle verbs: discuss, plan, execute, done.
- Each lifecycle verb in each adapter MUST resolve to a single core CLI invocation, exactly as defined in the ADR-003a/003b CLI contract.
- Adapters MAY expose additional commands beyond the lifecycle four. Roo currently does (13 total in `.roo/commands/`); OpenCode currently does not (4 total in `.opencode/commands/`). Neither asymmetry is a defect.
- Adapter command count parity is explicitly NOT a release criterion.
- Semantic symmetry over lexical symmetry: same lifecycle behavior under the same CLI verb, not same name count.

---

## 11. Required Issue Shape v2

Every implementation issue under `02b-hardening` MUST include the fields below inline. The v2 backlog's Issue Shape (lines 493-536) is REPLACED by this version. The four new fields (Reversibility, Migration, Estimate, Decision-source) are non-optional.

```md
## Problem
One concrete defect or ambiguity. Cite file:line for every claim.

## Layer
core | adapter-roo | adapter-opencode | skill-pack | docs | governance | security

## Decision-source
ADR-001 | ADR-002 | ADR-003a | ADR-003b | ADR-004 | ADR-005 | none (state explicitly if no ADR governs)

## Decision
The selected policy (copy the locked answer from the ADR; do not paraphrase).

## Target Files
- path/to/file:line-range

## Required Behavior
- Exact rule 1.
- Exact rule 2.

## Examples
- Input: ...
- Expected: ...

## Acceptance Criteria
- Criterion 1.
- Criterion 2.

## Verification
- `python3 ...` (must match a §10 stage or a row-specific regression test)

## Reversibility
yes | partial | no
If partial or no, name the artifact that cannot be reverted (e.g., "migrated phase-state.json").

## Migration
- For each pre-slice artifact this row breaks, describe the migration path (tool, command, or manual step).
- If no migration is required, state "none required" with the reason.

## Estimate
S | M | L (matching §7 definitions). State assumptions.

## Out Of Scope
- Related work intentionally deferred. Cite §4 or §12 if applicable.
```

### Authoritative worked example (T0-A)

The following is the canonical filled-in form. Downstream issues MUST follow this shape exactly.

```md
## Problem
Managed JSON state files are written via `path.write_text(json.dumps(...))` at multiple
sites (e.g., `scripts/lib/state_repair.py`, `scripts/harness.py`). A crash or power loss
between the open() and close() leaves a partially-written file that subsequent `json.loads`
calls cannot parse. This regresses to the §3 self-attestation surface because
`state_repair` then proceeds with an empty dict (`scripts/lib/state_repair.py:197`).

## Layer
core

## Decision-source
none (T0-A is policy, not a decision question)

## Decision
All managed JSON state writes use a single helper that performs
`NamedTemporaryFile(dir=parent) + fsync + os.replace`. Parent dir must be on the
same filesystem as the target.

## Target Files
- scripts/lib/atomic.py (new)
- scripts/lib/state_repair.py:* (all write sites)
- scripts/harness.py:* (all write sites)
- scripts/lib/check.py:* (audit sidecar writes if any)

## Required Behavior
- `write_json_atomic(path: Path, data: dict) -> None` writes `data` to a temp file
  in `path.parent`, calls `fsync`, then `os.replace(temp, path)`.
- Helper raises if `path.parent` does not exist or is on a different filesystem
  than the temp file (detected via `os.stat().st_dev` comparison).
- No other site in the repo calls `path.write_text` for a managed JSON state file.

## Examples
- Input: write_json_atomic(Path(".scratch/phase-state.json"), {"phase": "execute"})
- Expected: file replaced atomically; no observable intermediate state.

## Acceptance Criteria
- Helper exists and is the only writer for managed JSON.
- Crash-injection test: kill between temp-write and replace; original file unchanged.
- Cross-fs test: helper raises with a clear message naming both st_dev values.
- Grep gate: no `path.write_text` against a managed JSON path remains in `scripts/`.

## Verification
- `python3 -m pytest scripts/tests/test_atomic.py -v`
- Grep gate iterates over BOTH the `STATE_FILE_PATHS` list AND the `OPERATIONAL_PATHS` tuple published by ADR-003a (see §6 ADR-003a sub-decisions; per ADR-bundle commit `b57250f` revision G1-C). Reference shape:
  ```sh
  # Both tuples are sourced from the ADR-003a-locked CLI contract document.
  # Pre-ADR-003a defaults:
  #   STATE_FILE_PATHS=(".scratch/phase-state.json")
  #   OPERATIONAL_PATHS=()  # populated post-ADR with .harness/audit.log, .harness/session.lock, .harness/backups/
  STATE_FILE_PATHS=(".scratch/phase-state.json")
  OPERATIONAL_PATHS=(".harness/audit.log" ".harness/session.lock" ".harness/backups/")
  for p in "${STATE_FILE_PATHS[@]}" "${OPERATIONAL_PATHS[@]}"; do
    ! grep -rn "write_text" scripts/ | grep -F "$p"
  done
  ```
- Note: the grep gate is the same gate referenced by §10.2 static grep gate and the §7 T1-S allowlist; all three MUST track the same `STATE_FILE_PATHS` list. ADR-003a's locked output is the single source of truth (see §6 ADR-003a "`STATE_FILE_PATHS` artifact" sub-decision).

## Reversibility
yes (helper can be deleted; sites can be reverted to `write_text`).

## Migration
- none required. The helper is additive; no on-disk format changes.

## Estimate
S. Assumes no platform-specific tempfile quirks (Linux, macOS only; Windows OOS per §4).

## Out Of Scope
- Atomic writes for `.planning/STATE.md` (not JSON; managed by state_repair separately).
- fsync of the parent directory (POSIX-portable but adds latency; defer to 02c).
```

### Field rules

- `Decision-source` MUST cite an ADR or explicitly say `none`. "TBD" is rejected.
- `Reversibility` MUST match the §7 row's reversibility unless this issue is a strict subset; in that case justify the deviation.
- `Migration` MUST be present even when empty (`none required` + reason). Empty fields are rejected at review.
- `Estimate` is a planning aid; missing it blocks the issue from being scheduled.

---

## 12. Out Of This Spec

The following items from the v2 backlog are NOT in this slice and NOT promoted to ADRs. They are recorded here so downstream readers do not re-litigate.

- **T1-2 approval metadata trust level.** Deferred to `02c-hardening`. Rationale: the §3 problem is satisfied by ADR-003a deciding the direct-edit trust model; whether `approved_by` is provenance vs UX can be answered later without re-opening the live gate.
- **T1-3 `state_schema_version` enforcement guard.** Deferred to `02c-hardening`. The field is INTRODUCED in T0-1 of this slice; only the "refuse newer versions" guard is deferred. Rationale: only matters once a second schema version is in the wild and an older client is plausible.
- **T1-5 cross-OS launcher / `python3` portability.** Deferred to `02c-hardening`. Rationale: no `python3`-only failure mode is in §3. Slice MAY document that Windows is unsupported until `02c`; doing so is a doc change, not a code change.
- **T1-6 CRLF/byte-hash.** Deferred with T1-5. Rationale: same.
- **T1-9 SKILL splitting / few-shot expansion.** Deferred. Rationale: T1-S (in slice) is surface-touch only; deeper SKILL restructuring waits until adoption signal post-tag.
- **T1-10 `needs-info` evidence + self-correction.** Deferred. Rationale: depends on the agent-fit scenario in §9.1; iterate there first.
- **T1-11 crash-resistance on malformed state.** PROMOTED into the slice as T1-M (§7).
- **`installed-manifest.json` SHA-pinning / signed manifests / source RCE fix.** Deferred to `02c-hardening`. See §2.8 R-1. Carried as known residual risk.
- **LICENSE, packaging, console entry points, Windows launcher, signed releases.** Deferred to `02c-hardening`. See §2.7.
- **All other T2 robustness / distribution items** (CI matrix, secret scan, subprocess timeouts). Deferred. Rationale: §4 non-goals.
- **All T3 governance items** (README split, CHANGELOG, governance docs, adapter polish, dead-file cleanup). Deferred. Rationale: §4 non-goals.
- **`02-skill-pack-expansion`.** Paused (§5). Resumption requires a fresh discuss pass against the post-slice gate contract.
- **MCP server / signed releases / GUI / multi-tenant / LTS.** Deferred indefinitely; not on any roadmap. See §4.

---

## 13. Acceptance of This Spec

This spec is accepted when:

1. The six §6 ADRs (001, 002, 003a, 003b, 004, 005) are scheduled into a single bundled session, with the CLI contract artifact named as an explicit session deliverable.
2. `02b-hardening` is created as a paused-then-discuss phase per §5, and paused-phase representation is defined in `.planning/STATE.md` before T0-5 begins.
3. No row in §7 has been started in code. The full row set is: **T0-A, T0-1, T0-2, T0-3, T0-4, T0-5, T1-1, T1-S, T1-M.**
4. The §10 smoke harness change (three stages + static grep gate) is scoped into the implementation plan as a known cost.
5. T0-A is scheduled to land FIRST among code rows, before any state-writing row.
6. T1-S is scheduled to begin no earlier than the CLI contract artifact lock, and to complete before §10 smoke runs.
7. Downstream documents (plans, ADRs, issues) cite this spec by path.
8. §2.7 (Public-installable status) and §2.8 (Known residual risks) are acknowledged in the implementation plan introduction.
9. `CHANGELOG.md` exists at repo root with a `## [Unreleased]` (or existing equivalent unreleased) section containing a `### Breaking` subsection. As of T0-1 completion, the `done` contract change is enumerated under that subsection. Historical-version backfill is NOT required (per §2.4).

If any of the nine conditions is not met before code work begins (or, for condition 9, before T0-1 lands), this spec has been violated and the slice MUST be re-spec'd, not silently expanded.

---

## 14. Revision History

### r2 (2026-05-16) — post adversarial review

This revision integrates findings from three adversarial reviews (Protocol Architect, Low-Reasoning Realist, Ops/Supply-Chain Hawk) and three locked user decisions (D1 publishing posture, D2 mid-session upgrade, D3 installed-manifest source RCE).

**Reframed sections:**

- §1 supersession updated to reference six ADRs (001, 002, 003a, 003b, 004, 005) instead of five.
- §2 retitled "Commercial-Grade Target" → "Production-Internal Milestone Target". LICENSE / Windows / packaging / signed releases deferred to `02c-hardening` per D1.
- §2.7 "Public-installable status" added per D1, explicitly stating the slice is NOT publicly installable.
- §2.8 "Known residual risks" added per D3, naming R-1 (installed-manifest source RCE), R-2 (state_schema_version guard absent), R-3 (non-lifecycle adapter commands unverified).
- §3 `done` defect rewritten to describe the actual inverted predicate (`approved is not False`) instead of the prior misparaphrase.
- §6 ADR-001 candidate list pruned (removed `closure` object option and `done_pending_review`/`done_closed` split) and replaced with a new option 3: drop the `approved` constraint from the `done` branch entirely. Every option now names the `state_schema_version` bump.
- §6 ADR-003 SPLIT into ADR-003a (transition primitive: CLI verbs + trust model + direct-edit policy) and ADR-003b (field ownership matrix). ADR-003a constrains ADR-003b's option space.
- §6 ADR-003a ballot constrained to ≤2 CLI verbs, zero required flags; cryptographic signing removed; new option 3 (thin wrapper + direct-edit-with-confirmation) added to preserve weak-model muscle memory. Session-lockfile convention (`.harness/session.lock`) named per D2. `--remove-install-state` interaction with moved state file named.
- §6 ADR-004 hard sub-constraints added: inline-enumerated verbs in diagnostic, ≤8 verbs, citation of allowlist location.
- §6 ADR session protocol now mandates a **written CLI contract document** (verbs, I/O JSON shapes, exit codes, error strings) as part of session output, before T0-3 implementation. §10 golden file derives from this.

**New §7 rows:**

- **T0-A** (atomic write primitive, dependency-zero, lands first).
- **T1-S** (SKILL surface alignment, surface-touch only, depends on CLI contract artifact).

**§7 row sub-requirements expanded:**

- T0-1 now owns `state_schema_version` field introduction (value `1`), the migrator's `.pre-*.bak` artifact written BEFORE `os.replace`, and `--reverse` for v1 → v0 downgrade.
- T0-3 explicitly owns creation of `docs/protocol-spec.md` and the session-lockfile-refuse acceptance row (per D2).
- T0-5 + T1-M now require `state_repair` to refuse on unparseable input (the `scripts/lib/state_repair.py:197` defect) and to represent paused phases as first-class state.

**§8 critical path** now explicit: `ADR session (incl. contract) → T0-1 + T0-4 parallel → T0-3 → T1-1 → §9.1 harness`. T0-A precedes the ADR session as a sequencing convenience.

**§9.1 hardened:** N=50 trials per flow (200 total), ≥80% pass per flow, temperature=0 or seed-fixed, deterministic fixtures, max 2 retries recorded, per-trial budget cap (60s / 20k input / 4k output). Alternative no-regression-vs-baseline framing allowed. Budget escape clause requires documented gap, not silent unmeasured claim.

**§9.2 fixture path** abstracted ("a captured pre-slice snapshot under the test tree") per reviewer feedback.

**§10.2** explicitly limits adapter exercise to the 4 lifecycle commands; 9 Roo non-lifecycle commands quarantined; static grep gate added to prevent non-lifecycle commands from regressing live-gate write paths.

**§11** now includes a fully filled-in worked example for T0-A as the authoritative template form.

**§13** acceptance conditions expanded from 5 to 8 to cover T0-A first-landing, T1-S contract-gated start, paused-phase representation, and §2.7/§2.8 acknowledgment.

### r1 (2026-05-16) — initial spec

Original publication; superseded by r2 above.
