# Hardening Slice Design Spec

Date: 2026-05-16
Author: Protocol Architect
Type: Design specification (gates ADRs, plans, and code)
Audience: harness maintainers, ADR authors, plan authors

---

## 1. Status & Supersession

This document is the authoritative design input for the first **commercial-grade hardening release** of the general low-reasoning agent harness.

It **supersedes** `docs/reviews/2026-05-16-final-tiered-actions-v2.md` (hereafter "v2 backlog") as the binding design source. The v2 backlog remains valid as raw triage notes, but every divergence between v2 and this spec is resolved in favor of this spec.

Downstream documents must consume this spec, not v2:

- ADR-001..ADR-005 (per §6) MUST cite this spec.
- The Phase 2b implementation plan (per §5) MUST cite this spec and the five ADRs.
- Issue Shape v2 (§11) replaces the Required Issue Shape in v2 backlog lines 493-536.

This spec does not authorize code changes by itself. Code work is gated on: this spec accepted, then five ADRs locked, then implementation plan approved through the standard `discuss -> plan -> execute -> done` flow.

---

## 2. Commercial-Grade Target

"Production release" in this repository means the following posture is held by the next tagged release after the hardening slice lands. These are non-negotiable acceptance properties, not aspirations.

### 2.1 Correctness posture

- The live gate (`.scratch/phase-state.json`) is internally consistent: schema, checker, examples, docs, and shipped state agree on `phase=done` semantics. The current contradiction is documented in §3 and is a release blocker.
- Scope enforcement (`allowed_paths`, `blocked_paths`) has a single documented semantic and either implements it or explicitly rejects unsupported pattern forms with an actionable error. Silent mismatch is treated as a correctness defect, not a UX defect.
- Phase transitions cannot be performed by free-form file edits without the system either rejecting them or producing a loud, auditable warning. Self-attestation through `.scratch/phase-state.json` editing is removed from the default trust path.
- Free-text verification entries that do not execute anything are rejected as machine verification. Human review is a separate, typed evidence object.
- `state_repair` does not silently delete user content outside the managed `## Phases` block. Data preservation is a hard property; silent deletion is treated as data loss.

### 2.2 Recovery posture

- A malformed `phase-state.json`, a duplicated managed-block slug, or an unparseable roadmap MUST produce a diagnostic exit, not an uncaught traceback.
- Recovery instructions for each diagnostic class are reachable from the diagnostic message (file path + recovery verb), not only from external README sections.
- Backward compatibility is bounded by the `state_schema_version` field. Older code that encounters a newer `state_schema_version` MUST refuse to operate, not guess.

### 2.3 Supply-chain posture (deferred from this slice but constrained)

- This slice does NOT add Cosign, SLSA, or signed release infrastructure (see §4). It DOES forbid regressions that would make future supply-chain hardening impossible (e.g., no new mutable network-side defaults).
- `installed-manifest.json` based upgrade flows are not extended in this slice. Their trust model is frozen pending a separate ADR outside this spec.

### 2.4 Breaking-change policy

- The hardening slice is permitted to introduce breaking changes to (a) the `phase=done` contract, (b) verification field shape, (c) scope-pattern syntax, and (d) the direct-edit trust model.
- All four are pre-1.0 contract changes. The repository remains in 0.x and SemVer 0.x rules apply: minor version bumps may break.
- Migration tooling is REQUIRED for the live `.scratch/phase-state.json` (see §9 backward-compat criteria). Migration tooling for `.planning/**` content is NOT required if no schema is published over it.
- Each breaking change MUST be enumerated in CHANGELOG under a `Breaking` heading. CHANGELOG format itself is out of this slice (T3) but the discipline of listing each break is in scope.

### 2.5 Support window

- This slice commits to one supported version line: the released hardening tag and `main`. There is no LTS, no backport policy, and no parallel stable line.
- Adopters on prior releases are expected to upgrade. There is no obligation to ship security fixes against prior tags.
- This is sufficient for "commercial-grade for an early-stage harness". Multi-line support is explicitly a non-goal (see §4).

### 2.6 Quality bar discipline

- Every T0 and in-scope T1 row in §7 MUST land with: a regression test, a doc paragraph in `docs/protocol-spec.md` (or successor), and an end-to-end smoke that exercises core CLI plus both first-class adapters (see §10).
- "Works on my Roo" is not acceptance. Acceptance requires the §10 verification protocol to pass on the same commit.

---

## 3. Problem Statement

The current main branch ships a harness whose advertised contract is internally inconsistent and self-attesting in three ways at once. `.scratch/phase-state.schema.json:347-399` declares that `phase=done` requires `approved=true`. `scripts/lib/check.py:420-434` requires `approved is not False`, i.e., it rejects `approved=true` for `done`. The live state file `.scratch/phase-state.json:3` ships `approved=false`. `scripts/lib/worktree.py:1-90` imports `fnmatch` (line 4) but never calls it; `matches_any` at `scripts/lib/worktree.py:76-84` performs prefix-or-exact matching only, so any pattern containing `*` silently matches zero paths. The live state file at `.scratch/phase-state.json:20` ships `.scratch/phase-state.json` itself inside `allowed_paths`, meaning the default trust model permits an agent to author its own approval. `scripts/lib/check.py:99-111` declares `VERIFICATION_PREFIXES` containing `"Confirm "`, `"Review "`, `"Inspect "`, `"Validate "`, and bare `"Roo"`, so the string `"Room is great"` passes machine verification. Together these defects mean the harness's three public promises (consistent live gate, enforced scope, non-self-attested approval) are currently false on the default install. A commercial-grade release cannot ship with these properties.

---

## 4. Non-Goals

This slice explicitly does NOT deliver, and any in-slice work that drifts toward these MUST be deferred:

- **MCP server / MCP transition tool.** Out of scope. A core CLI transition primitive is in scope (§6, ADR-003); an MCP wrapper around it is not.
- **Signed releases (Cosign, sigstore, SLSA).** Out of scope. The slice MUST NOT regress against later signing.
- **Multi-tenant or hosted operation.** Out of scope. The harness is a per-repo CLI.
- **GUI, web UI, dashboard.** Out of scope.
- **Multi-line support / LTS.** See §2.5.
- **Cross-OS hardening (Windows launcher, CRLF normalization).** v2 T1-5/T1-6. Deferred to a later slice. Slice MAY document `python3` as canonical and explicitly mark Windows as unsupported in the supported matrix.
- **LICENSE, CONTRIBUTING, CODE_OF_CONDUCT, README split, CHANGELOG backfill.** v2 T2/T3 governance and DX. Deferred (§12).
- **Skill-pack content rewrites, SKILL length caps, few-shot expansion.** v2 T1-9/T1-10. Deferred unless the §6 ADRs change the protocol surface a SKILL describes.
- **`installed-manifest.json` trust model rework, `--repo` URL pinning, supply-chain.** v2 T1-6, T2-5. Deferred.
- **OpenCode command parity with Roo.** v2 T3-14. Symmetry is semantic, not lexical (§10).
- **Profile/mode redesign, `.roomodes` rework.** v2 T3-12. Deferred.
- **Pyproject packaging, console entry points, mypy/ruff, CI matrix.** v2 T2-3/T2-4. Deferred.

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

---

## 6. Five Locked-Decision Targets (ADR-001..ADR-005)

Every Decision-required row in §7 traces to exactly one ADR below. No implementation may begin on any §7 row until its referenced ADR is locked. ADRs are decided in one bundled session, not five sequential sessions (rationale: four of the five are coupled through the live state contract; deciding them in isolation produces inconsistent answers).

Each ADR below states the decision question and the candidate options. This spec does NOT pick. The ADR session picks.

### ADR-001 - `phase=done` Contract Semantics

Decision question: What does `phase=done` mean with respect to approval, and which field carries that meaning?

Candidate options:

1. `done` requires `approved=true` with `approved_by` and `approved_at`; schema is right, checker is wrong.
2. `done` requires `approved=false` because `done` itself encodes a closed gate distinct from `execute` approval; checker is right, schema is wrong.
3. `done` removes the `approved` field entirely; replace with a typed `closure` object containing `closed_by`, `closed_at`, `closure_reason`.
4. `done` is split into `done_pending_review` and `done_closed`, each with explicit field requirements.

Decision-source: T0-1 in §7.

### ADR-002 - Scope Pattern Syntax

Decision question: What syntax does `allowed_paths` / `blocked_paths` accept, and what happens to inputs outside that syntax?

Candidate options:

1. Prefix + exact-only (current behavior). Patterns containing glob metacharacters (`*`, `?`, `[`, `]`, `**`) are rejected at load time with a clear error pointing at the offending entry.
2. Full glob via `fnmatch` (matches the dead import in `scripts/lib/worktree.py:4`). Documented behavior for `**`, `*.md`, `dir/`, trailing slash.
3. `pathspec`-style gitignore semantics, including negation. Strictly stronger than option 2.
4. Two-field split: `allowed_prefixes` (current semantic) and `allowed_globs` (new, opt-in).

Blocked-vs-allowed precedence is part of this ADR: state explicitly that blocked overrides allowed at the entry level, including when both fields match the same path.

Decision-source: T0-2 in §7.

### ADR-003 - Phase Transition Authority

Decision question: How does a phase transition (e.g., `plan` -> `execute` with approval) happen, and what is the trust model for direct edits to `.scratch/phase-state.json`?

Candidate options:

1. Core CLI verb (`harness phase set`, `harness phase approve`, exact verb names left to plan) is the only sanctioned path; direct edits remain physically possible but the checker emits a high-severity warning when the file's last-modified author cannot be attributed to the CLI (heuristic: presence of a sidecar audit entry).
2. Same CLI, plus the checker hard-fails when `.scratch/phase-state.json` appears inside its own `allowed_paths`.
3. Same CLI, plus `.scratch/phase-state.json` is moved out of the working tree (e.g., `.harness/state.json`) and `allowed_paths` cannot reference it by construction.
4. Same CLI, with cryptographic signing of transitions using a local keypair. (Likely too heavy for this slice; included for completeness.)

This ADR also decides: which fields are user-editable (e.g., `notes`, `summary`, `acceptance_criteria`), and which are CLI-only (`phase`, `approved`, `approved_by`, `approved_at`, `state_schema_version`).

Decision-source: T0-3 in §7. Also drives §10 because the CLI introduced here defines "core-only path".

### ADR-004 - Verification Contract Shape

Decision question: How does the schema distinguish runnable machine verification from human review evidence, and what shape does each take?

Candidate options:

1. Two fields: `verification` (machine, array of strings matching a tightened allowlist that requires an executable prefix and a registered command verb) and `review` (human, array of objects with `actor`, `at`, `evidence_path`, `summary`).
2. One field with discriminated union: each entry is either `{type: "command", cmd: "..."}` or `{type: "review", actor, at, evidence_path, summary}`.
3. Tighten the string allowlist in place (remove `"Confirm "`, `"Review "`, `"Inspect "`, `"Validate "`, `"Roo"` from `scripts/lib/check.py:99-111`), and add a parallel `review_evidence` field for human notes.
4. Move command allowlist into a config file (`.harness/verification-prefixes.json`) and require the schema to point at a versioned allowlist.

Decision-source: T0-4 in §7.

### ADR-005 - `state_repair` Preservation Policy

Decision question: When `state_repair` encounters content outside the managed `## Phases` block in `.planning/STATE.md` (or other managed files), what does it do?

Candidate options:

1. Preserve verbatim outside the managed markers; never rewrite non-managed regions.
2. Refuse to operate when non-managed content is detected; require the user to first remove or relocate it.
3. Preserve verbatim AND write a backup file (`.bak` with timestamp) before any rewrite.
4. Detect content outside markers as a recoverable error class, route through a new `state repair --interactive` flow that asks the user.

Decision-source: T0-5 in §7. This is a new T0 promoted from v2 T1-4 / v2 backlog footnote because it represents silent data loss, not recovery.

### ADR session protocol

The five ADRs MUST be decided in a single bundled session producing five files under `docs/adr/` (path naming left to plan). The session order is: ADR-001, ADR-002, ADR-004, ADR-003, ADR-005. Rationale for order: state semantics before transition tooling that mutates state; verification shape before transition tooling that records it; preservation policy last because it is orthogonal to the live gate.

The session output is a single PR that lands all five ADRs together. Partial ADR landing is forbidden.

---

## 7. Hardening Slice Scope

The slice covers exactly the rows below. No additions without a spec amendment.

| ID | Title | Layer | ADR dep | Size | Risk | Reversibility |
|---|---|---|---|---|---|---|
| T0-1 | `phase=done` contract aligned across schema, checker, live state, docs, tests | core | ADR-001 | M | med | partial |
| T0-2 | Scope pattern syntax decided, implemented, tested; unsupported patterns fail loudly | core | ADR-002 | M | med | yes |
| T0-3 | Core CLI phase-transition primitive; direct-edit trust model enforced or warned per ADR | core | ADR-003 | L | high | partial |
| T0-4 | Verification contract split: machine commands vs human evidence; free-text rejected | core | ADR-004 | M | med | yes |
| T0-5 | `state_repair` preserves non-managed content per ADR-005; no silent deletion | core | ADR-005 | S | low | yes |
| T1-1 | `check --worktree` wired as required step at the workflow boundary chosen by ADR-003 | core/adapter | ADR-003 | S | low | yes |
| T1-M | Malformed state recovery: `phase-state.json` parse failures, duplicate slugs, broken roadmap produce diagnostic exit not traceback | core | none | M | low | yes |

Layer legend: `core` = `scripts/`, `.scratch/` schema, `docs/protocol-spec.md`. `adapter` = `.roo/commands/`, `.opencode/commands/`. `core/adapter` = primary change in core, mirrored hooks in adapters.

Size legend: S = under 1 day of focused work, M = 1-3 days, L = 3-5 days. These are scoping estimates, not commitments.

Risk legend:
- low = isolated, well-understood, no live-gate semantics change.
- med = touches the live-gate contract; existing Phase 1 records may need migration.
- high = changes how transitions happen at all; user muscle memory and adapter commands depend on it.

Reversibility legend:
- yes = a follow-up release can restore prior behavior without data migration.
- partial = follow-up can restore behavior but recorded state from the new version cannot be downgraded.
- no = irreversible (none in this slice).

Notes on individual rows:

- **T0-1** is `partial` reversible because once the live state is rewritten to the new shape, downgrading code requires either preserving the old shape or running a reverse migration. The migration tool from §9 is the mitigation.
- **T0-3** is the highest-risk row in the slice because it changes the workflow ergonomics that every adapter, every SKILL pack, and every human contributor has internalized. The Phase 1 muscle memory was "edit `.scratch/phase-state.json` and re-run check". The new muscle memory is whatever ADR-003 picks. §9 defines the migration story.
- **T1-M** has no ADR dependency because the policy "do not crash on malformed input" is not a decision; only the diagnostic copy is, and diagnostic copy does not gate code.
- **T1-1** depends on ADR-003 because "wired at the workflow boundary" presupposes a defined boundary; ADR-003 is what defines whether the boundary is the CLI verb, a hook, or both.

Out of slice (deferred to a later hardening pass, NOT to T2 or T3 categorically): v2 T1-2 (approval metadata trust level), T1-3 (state_schema_version guard). Both are real but neither blocks the §3 problem. They are tracked as `02c-hardening` candidates.

---

## 8. Execution Order with Rationale

The slice executes as a dependency graph, not a queue. Independent rows MAY proceed in parallel under the §10 verification protocol; dependent rows MUST wait.

```
                        [ADR session: 001, 002, 003, 004, 005]
                                       |
              +------------+-----------+-----------+------------+
              |            |           |           |            |
            T0-1         T0-2        T0-4        T0-5         T1-M
         (ADR-001)    (ADR-002)   (ADR-004)   (ADR-005)    (no ADR)
              |            |           |
              +-----+------+           |
                    |                  |
                  T0-3   <-------------+
                (ADR-003, needs T0-1 + T0-4 landed first)
                    |
                  T1-1
                (depends on T0-3 CLI verb to wire)
```

Rationale:

- **ADR session is a single hard barrier.** No row begins until all five ADRs land. This is enforced because ADR-003 changes the workflow boundary that every other row's tests will run through.
- **T0-1, T0-2, T0-4, T0-5, T1-M run in parallel after the ADR session.** None mutates the others' code surface. T0-1 touches schema + checker + live state. T0-2 touches `worktree.py` + schema. T0-4 touches checker + schema. T0-5 touches `state_repair.py`. T1-M touches input boundaries (`json.loads` call sites, managed-block parser). Parallelism is recommended, not required.
- **T0-3 sequences after T0-1 and T0-4.** Reason: T0-3 introduces a CLI that *sets* `phase` and *writes* verification entries. Building that CLI against a still-ambiguous `done` semantic or a still-loose verification shape would force rewrites mid-row. T0-3 does NOT depend on T0-2 or T0-5.
- **T1-1 sequences after T0-3.** Reason: "wire `check --worktree` to the workflow boundary" requires the workflow boundary to exist. ADR-003 defines the boundary; T0-3 implements it; T1-1 consumes it.
- **T1-M is independent of all the above.** It targets failure modes that exist regardless of contract shape. It SHOULD land early because it makes every other row's failure modes more debuggable.

Adapter mirroring (updating `.roo/commands/*.md` and `.opencode/commands/*.md` to call the new CLI) is part of T0-3 and T1-1, not a separate row.

---

## 9. Quantified Pass Criteria

### 9.1 Low-reasoning agent fit (actor model)

"Low-reasoning agent" in this spec is operationalized as: Anthropic Claude Haiku (4.5 or successor), single-turn or short-chain, no system prompt augmentation beyond what an adapter ships, no human-in-the-loop correction during execution.

Pass criteria for the slice as a whole:

- A fixed scenario script (`scripts/smoke/low_reasoning_scenario.py`, to be created by the implementation plan, not by this spec) executes the four canonical flows: `discuss -> plan`, `plan -> execute`, `execute -> done`, and `state repair after corruption`.
- The scenario runs **N = 20 trials per flow** (80 total). Pass rate per flow MUST be ≥ 16/20 (80%). A trial passes iff: the agent reaches the next phase OR explicitly raises a `needs-info` request grounded in the actual diagnostic; a trial fails iff the agent loops, fabricates approval, or proceeds despite a gate rejection.
- The 80% threshold is a release blocker for the hardening tag, not for individual row merges.
- Trial logs are committed under `.planning/phases/02b-hardening/evidence/` for the release record.

If the scenario harness itself cannot be built within the slice budget, the slice MUST land with a documented gap and a deferred row, NOT with an unmeasured "feels better" claim.

### 9.2 Backward-compat criteria for Phase 1 records

The existing Phase 1 records (`.planning/phases/01-generalized-harness-release/`, `.planning/STATE.md`, the historical `.scratch/phase-state.json` snapshot at `done` recorded 2026-05-15) MUST remain readable and re-checkable after the slice lands.

Concretely:

- A `harness migrate state` command (verb name left to plan) MUST convert the live `.scratch/phase-state.json` from its current shape (`phase=done, approved=false`) to whatever shape ADR-001 picks, idempotently.
- Running `harness check` against the migrated file MUST pass without manual edits.
- Existing checkpoint files, plan files, and DISCUSS artifacts under `.planning/phases/01-*/` MUST NOT require edits.
- A regression test fixture `scripts/test_data/phase1_done_legacy.json` captures the pre-slice live state byte-for-byte; a test asserts the migrator converts it to a post-slice-valid state without loss of `plan_id`, `approved_by`, `approved_at`, `summary`, `state_path`, `plan_path`, `checkpoint_path`, `current_checkpoint`, `next_action`, `acceptance_criteria`, `verification`, `notes`, `updated_at`, `updated_by`.

### 9.3 Adapter-neutral pass criteria

The §10 smoke MUST pass on the same commit for: core CLI directly, Roo adapter commands (the 13 files in `.roo/commands/`), and OpenCode adapter commands (the 4 files in `.opencode/commands/`).

"Roo first-class" and "OpenCode first-class" remain the only two adapter targets in scope. Adding a third adapter is out of slice.

### 9.4 Regression test coverage floor

- T0-1: at least 1 test asserting the new `done` semantic accepts a valid record, 1 asserting it rejects an invalid one, 1 asserting the migrator handles the legacy fixture.
- T0-2: at least 4 tests covering: prefix match, blocked overriding allowed, the syntax decided by ADR-002 (positive case), and the rejection path for unsupported syntax (negative case).
- T0-3: at least 1 test asserting the CLI transition succeeds on a valid input, 1 asserting it refuses an invalid input, 1 asserting the direct-edit detection or warning per ADR-003.
- T0-4: at least 1 test per accepted verification form, plus 1 asserting `"Room is great"` (the canonical false-positive from §3) is rejected.
- T0-5: at least 1 test asserting non-managed content outside `## Phases` is preserved per ADR-005, plus 1 asserting backup is created if ADR-005 picks option 3.
- T1-M: at least 1 test per failure class (malformed JSON, duplicate managed-block slug, unparseable roadmap heading).
- T1-1: at least 1 test asserting `check --worktree` runs at the chosen boundary and fails CI when a forbidden path changes.

The existing test that asserts `done requires approved=false` (currently in `scripts/test_harness.py` per T0-fact, contradicts the schema) MUST be deleted or rewritten as part of T0-1; this is called out because deleting a passing test is normally a smell and reviewers should know it is intentional here.

---

## 10. Adapter-Neutral Verification Protocol

### 10.1 The circular dependency

A naive reading of v2 backlog and the T0-pass definition produces a circular dependency: "core-only smoke" implies a core invocation path, but the only core invocation path today is "edit JSON files and call `harness check`", which is exactly the trust model T0-3 removes. If "core-only smoke" requires the new CLI, but the new CLI is itself the deliverable being smoked, the smoke cannot validate the deliverable.

### 10.2 Resolution

Define "core-only path" as the CLI surface introduced by T0-3. The CLI IS the core protocol surface for transitions; adapters wrap it.

Concretely:

- T0-3 is implemented first among the rows that produce user-facing behavior changes (after parallel rows that only tighten validation).
- The smoke harness (`scripts/release_smoke_test.py`, extended; this file already exists per Phase 1 verification record) gains three sequential stages:
  1. **Core-only stage:** invoke the new CLI directly with no adapter context. Run a scripted `discuss -> plan -> execute -> done` flow against a fixture repository under `tmp/`. Pass criteria: every transition succeeds, every check passes, and the resulting state matches a recorded golden file.
  2. **Roo stage:** invoke the same scripted flow through the `.roo/commands/*.md` command shapes. Each Roo command MUST resolve to the same core CLI verb. Pass criteria: same as core-only.
  3. **OpenCode stage:** invoke the same flow through `.opencode/commands/*.md` (4 commands: `discuss`, `plan`, `execute`, `done`). OpenCode having 4 commands vs Roo having 13 is by design (Roo includes adjacent verbs like `adr`, `bugfix`, `feature`, etc., that are not part of the lifecycle); the smoke only exercises the 4 lifecycle commands. Pass criteria: same as core-only.

Any of the three stages failing fails the slice acceptance.

### 10.3 Why this breaks the circle

The new CLI does not need to exist to define what "core-only" means; this spec defines it. The CLI's implementation is verified by the same smoke that verifies the adapters, against the same fixture. Adapter symmetry becomes a property ("the adapter resolves to the same core verb"), not a count ("the adapter has the same number of commands").

### 10.4 What "adapter symmetry" means after this spec

- Both adapters MUST expose the four lifecycle verbs: discuss, plan, execute, done.
- Each lifecycle verb in each adapter MUST resolve to a single core CLI invocation (decided in ADR-003).
- Adapters MAY expose additional commands beyond the lifecycle four. Roo currently does (13 total in `.roo/commands/`); OpenCode currently does not (4 total in `.opencode/commands/`). Neither asymmetry is a defect.
- Adapter command count parity is explicitly NOT a release criterion.

---

## 11. Required Issue Shape v2

Every implementation issue under `02b-hardening` MUST include the fields below inline. The v2 backlog's Issue Shape (lines 493-536) is REPLACED by this version. The four new fields (Reversibility, Migration, Estimate, Decision-source) are non-optional.

```md
## Problem
One concrete defect or ambiguity. Cite file:line for every claim.

## Layer
core | adapter-roo | adapter-opencode | skill-pack | docs | governance | security

## Decision-source
ADR-001 | ADR-002 | ADR-003 | ADR-004 | ADR-005 | none (state explicitly if no ADR governs)

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

Field rules:

- `Decision-source` MUST cite an ADR or explicitly say `none`. "TBD" is rejected.
- `Reversibility` MUST match the §7 row's reversibility unless this issue is a strict subset; in that case justify the deviation.
- `Migration` MUST be present even when empty (`none required` + reason). Empty fields are rejected at review.
- `Estimate` is a planning aid; missing it blocks the issue from being scheduled.

---

## 12. Out Of This Spec

The following items from the v2 backlog are NOT in this slice and NOT promoted to ADRs. They are recorded here so downstream readers do not re-litigate.

- **T1-2 approval metadata trust level.** Deferred to `02c-hardening`. Rationale: the §3 problem is satisfied by ADR-003 deciding the direct-edit trust model; whether `approved_by` is provenance vs UX can be answered later without re-opening the live gate.
- **T1-3 `state_schema_version` guard.** Deferred. Rationale: only matters once a second schema version exists. ADR-001 may or may not produce one; the guard work is cleaner after that lands.
- **T1-5 cross-OS launcher / `python3` portability.** Deferred. Rationale: no `python3`-only failure mode is in §3. Slice MAY document that Windows is unsupported until a later slice; doing so is a doc change, not a code change.
- **T1-6 CRLF/byte-hash.** Deferred with T1-5. Rationale: same.
- **T1-9 SKILL splitting / few-shot expansion.** Deferred. Rationale: the §6 ADRs will change the protocol surface SKILLs describe; rewriting SKILLs before the ADRs land would force a second rewrite.
- **T1-10 `needs-info` evidence + self-correction.** Deferred. Rationale: depends on the agent-fit scenario in §9.1; iterate there first.
- **T1-11 crash-resistance on malformed state.** PROMOTED into the slice as T1-M (§7).
- **All T2 robustness / distribution items** (atomic writes, LICENSE, pyproject, CI matrix, supply chain, secret scan, subprocess timeouts). Deferred. Rationale: §4 non-goals.
- **All T3 governance items** (README split, CHANGELOG, governance docs, adapter polish, dead-file cleanup). Deferred. Rationale: §4 non-goals.
- **`02-skill-pack-expansion`.** Paused (§5). Resumption requires a fresh discuss pass against the post-slice gate contract.
- **MCP server / signed releases / GUI / multi-tenant / LTS.** Deferred indefinitely; not on any roadmap. See §4.

---

## 13. Acceptance of This Spec

This spec is accepted when:

1. The five §6 ADRs are scheduled into a single bundled session.
2. `02b-hardening` is created as a paused-then-discuss phase per §5.
3. No row in §7 has been started in code.
4. The §10 smoke harness change is scoped into the implementation plan as a known cost.
5. Downstream documents (plans, ADRs, issues) cite this spec by path.

If any of the five conditions is not met before code work begins, this spec has been violated and the slice MUST be re-spec'd, not silently expanded.
