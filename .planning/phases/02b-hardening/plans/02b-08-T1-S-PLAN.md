# Plan — T1-S SKILL Surface Alignment to New CLI

Phase: `02b-hardening` (slice T1-S, depends on T0-3 CLI contract artifact)
Spec: `docs/superpowers/specs/2026-05-16-hardening-slice-design.md` §7 T1-S row (size bumped to **M** per ADR-bundle revisor — actual file count is 18 including the new `.roo/commands/done.md`, not the 3–5 placeholder), §10.2 (static grep gate), §10.3 (quarantine rationale), §9.1 (Haiku-4.5 trial harness this row feeds).
Contract: `.planning/phases/02b-hardening/CONTRACT-PIN.md` §1 (path tuples sourced from `scripts/lib/operational_paths.py` — any STATE_FILE_PATHS reference imports from there), §5.2 (`.roo/commands/done.md` creation assigned HERE — adapter parity gap, see Task 14a below), §7 (ledger L20 in FIRST commit), §8.1/§8.2 (N=50 acceptance lives in `02b-10-PHASE-E-HARNESS-PLAN.md`; T1-S's V8–V11 5-trial smokes are ADVISORY).
ADR: `docs/adr/2026-05-16-hardening-bundle.md` — Artifact 1 (CLI verb contract; canonical `done` few-shot G3-A), ADR-001 transition table, ADR-003a (CLI + warn; verbs `harness phase set <X>` and `harness phase approve`), ADR-003b (field ownership; G2-B transition table, G2-C `done.approved` no-op clarification), ADR-004 (7-verb verification allowlist; removed prefixes `Confirm`, `Validate`, `Review`, `Inspect`, `Roo`, `core-only`, `OpenCode-only`, `bash`).

## Goal (one sentence)

Replace every direct-edit-of-`.scratch/phase-state.json` instruction and every removed-verification-prefix reference in `.roo/skills/**/SKILL.md` and in the 7 lifecycle-4 adapter command files (3 Roo + 4 OpenCode) with the ADR-003a CLI invocations (`harness phase set <phase>` + `harness phase approve`) and the ADR-004 7-verb allowlist, append one canonical post-CLI few-shot per SKILL drawn from the G3-A `done`-shape artifact, and prove the change holds with one static grep-gate test and one Haiku-4.5 smoke pass.

## Acceptance (copied verbatim from spec §7 T1-S row and §9.4)

- Scope: the SKILL files in `harness/skill-packs/**` AND `.roo/skills/**` that reference direct-edit of `.scratch/phase-state.json` or the old `approved` semantics. Update each to reflect the ADR-003a/003b transition primitive and ADR-001 `done` shape.
- NO length cap. NO few-shot expansion. NO content rewrites. Surface-touch only: rename verbs, update example snippets, fix outdated `approved` references.
- Dependency: T0-3 contract artifact (the CLI contract document produced by the ADR session). T1-S MAY begin once the contract is locked, in parallel with T0-3 implementation.
- Reversibility: yes (text edits in SKILL files; revertable in a follow-up PR).
- §9.4 coverage floor: at least 1 lint/grep test asserting no SKILL file in the updated set still references the old direct-edit verb pattern or the old `approved` semantic.
- §10.2 static grep gate: `grep -l "write.*phase-state.json" .roo/commands/{adr,bugfix,feature,doctor,issues,ops,fsd-phase,review,simple}.md` MUST return empty (verified pre-slice and re-verified post-slice).

## Out of scope

- The 9 Roo non-lifecycle commands (`adr.md`, `bugfix.md`, `feature.md`, `doctor.md`, `issues.md`, `ops.md`, `fsd-phase.md`, `review.md`, `simple.md`) are quarantined per spec §10.3. They MUST NOT be touched unless they introduce a new write path against `.scratch/phase-state.json`. The pre-slice grep-gate check above shows they currently do not; if that changes during the slice, the violation fixes are in scope but limited to the line that introduced the write.
- New few-shot expansion beyond the **one** canonical post-CLI example per SKILL file. No re-illustration of `discuss`/`plan`/`execute` shapes — the G3-A artifact only provides the `done` shape, so each SKILL gets at most the one `done` shape example or a one-line CLI invocation reference, not a sequence.
- SKILL length-cap enforcement (deferred to v2 T1-9).
- Content rewrites beyond surface replacement (deferred to v2 T1-10). If a SKILL's prose explanation of WHY the phase-state matters becomes wrong post-CLI, fix only the load-bearing sentence; do NOT restructure the section.
- `harness/skill-packs/**/SKILL.md` files that mention `approved` only as English prose (not as JSON field name in a `.scratch/phase-state.json` edit instruction) are out of scope. The grep audit in Step 0 distinguishes these.
- Adapter commands outside the lifecycle 4 (the 9 quarantined Roo commands; any future adapter pack additions).
- The `harness session unlock` operational verb. T1-S does not surface it in SKILL files; recovery-from-stale-lock is operator-facing and lives in `docs/protocol-spec.md` (owned by T0-3).
- `harness phase approve` in `phase=done` (G2-C no-op exit-6 path). SKILLs MUST NOT instruct the model to call `approve` after `set done`; the canonical chain is `set execute → approve → set done` and `approve` is never re-issued post-`done`.
- The Haiku-4.5 simulator scenario script itself (`scripts/smoke/low_reasoning_scenario.py`). T1-S only consumes it once it exists (per spec §9.1, the script is built by a separate slice task); the manual smoke in Step 3 below uses a paste-into-simulator workflow until the scripted harness lands.
- CHANGELOG entry for the SKILL prose change. T1-S is a behavior-preserving surface alignment; no `### Breaking` entry is required (no field or verb name a downstream agent depended on disappears in a way the CLI does not handle — the CLI is the replacement for the disappearing direct-edit instruction).

## Verification list (write the grep gates and the manual smoke FIRST, then edit)

Each item below is one numbered task. Markdown files are not executable, so "verification" replaces "test"; each verification is either a `grep` invocation with a documented expected exit code or a manual paste-into-Haiku check with a documented pass criterion.

1. **V1 `grep_no_skill_writes_phase_state_json`** — run `grep -nE "(write|edit|update|modify|set)[^\n]{0,40}\.scratch/phase-state\.json" .roo/skills/*/SKILL.md harness/skill-packs/**/SKILL.md` AND `grep -nE "\.scratch/phase-state\.json[^\n]{0,40}(write|edit|update|modify|=)" .roo/skills/*/SKILL.md harness/skill-packs/**/SKILL.md`. Both MUST return exit 1 (no matches) after the slice. Pre-slice: at least one match per .roo SKILL file (10 expected). Post-slice: zero matches across both invocations.
2. **V2 `grep_no_skill_old_approved_semantic`** — run `grep -nE "approved=true|approved.*true|approved.*provenance|approved_by.*approved_at" .roo/skills/*/SKILL.md harness/skill-packs/**/SKILL.md`. Each remaining match MUST be either (a) inside the canonical G3-A `done`-shape few-shot block clearly labelled as "post-CLI state" or (b) a description of the G2-C no-op behavior ("`approve` is a no-op in `phase=done`"). Any other match fails the gate. The verification is partly manual because the regex cannot distinguish prose contexts; the task records the line numbers and the reviewer signs off in the PR.
3. **V3 `grep_no_removed_verification_prefixes_in_skills`** — run `grep -nE "verification.*\b(Confirm|Validate|Review|Inspect|Roo|core-only|OpenCode-only|bash)\b" .roo/skills/*/SKILL.md harness/skill-packs/**/SKILL.md` AND `grep -nE "^[[:space:]]*[-*][[:space:]]+(Confirm|Validate|Review|Inspect|Roo|core-only|OpenCode-only|bash)\b" .roo/skills/*/SKILL.md harness/skill-packs/**/SKILL.md` (the second targets bullet-list verification entries). Both MUST return exit 1 OR every match MUST be a prose use ("confirm the diff" / "inspect the file" — not a verification[*] string). The task records each line and the PR description annotates each match's classification.
4. **V4 `grep_no_lifecycle_command_writes_phase_state_json`** — run `grep -nE "(write|edit|>) .*\.scratch/phase-state\.json" .roo/commands/phase-discuss.md .roo/commands/phase-plan.md .roo/commands/phase-execute.md .opencode/commands/discuss.md .opencode/commands/plan.md .opencode/commands/execute.md .opencode/commands/done.md`. Pre-slice: matches expected in `phase-execute.md` and `execute.md` (the "verify `.scratch/phase-state.json` directly" step). Post-slice: exit 1 (zero matches). The replacement is `harness phase set <X>` / `harness phase approve` invocations.
5. **V5 `grep_gate_quarantined_commands_still_clean`** — re-run the spec §10.3 quarantine gate: `grep -l "write.*phase-state.json" .roo/commands/{adr,bugfix,feature,doctor,issues,ops,fsd-phase,review,simple}.md`. MUST return empty BOTH before and after the slice (verified pre-slice in Step 0; verified again post-slice as a regression check that no edit accidentally moved a write-instruction into a quarantined file). This is the spec-mandated M5 gate.
6. **V6 `grep_each_updated_skill_cites_cli_verb_once`** — run `grep -lE "harness phase (set|approve)" .roo/skills/*/SKILL.md`. The output set MUST equal exactly the set of SKILL files the slice updates (enumerated in Step 0). If a SKILL file in the updated set is missing from this output, that SKILL did not receive the canonical CLI-invocation few-shot — fail. If a SKILL outside the updated set appears, the slice over-touched — fail.
7. **V7 `grep_canonical_done_few_shot_present_in_phase_gate_skill`** — run `grep -c "state_schema_version.*2" .roo/skills/workflow-phase-gate/SKILL.md`. MUST return ≥ 1. The phase-gate SKILL is the single canonical anchor for the G3-A `done` few-shot; other SKILLs reference it by file path rather than re-pasting the JSON (this preserves the "no few-shot expansion beyond canonical one" rule). Other updated SKILLs MAY include the one-line `harness phase set X && harness phase approve` invocation as their canonical example, but they MUST NOT duplicate the JSON block.
8. **V8 `manual_smoke_haiku_4_5_discuss_to_plan`** — paste the updated `.roo/skills/workflow-phase-gate/SKILL.md` plus the updated `.roo/commands/phase-discuss.md` into a Haiku-4.5 prompt simulator with a fixture repo state of `phase=discuss`. Prompt: "I want to start planning the next slice." Pass criterion: the model emits `harness phase set plan` (NOT a JSON edit instruction, NOT `Edit .scratch/phase-state.json`). Trial budget: 5 runs; pass rate ≥ 4/5 (80%, matching spec §9.1 per-flow floor).
9. **V9 `manual_smoke_haiku_4_5_plan_to_execute`** — same as V8 but for `plan → execute`. Fixture: `phase=plan, plan_id=test-1, approved=false`. Prompt: "Approve the plan and start executing." Pass criterion: the model emits `harness phase approve` followed by `harness phase set execute` (order matters: approve happens in `plan`, then `set execute`; per ADR-003a, the approval is a prerequisite of the transition).
10. **V10 `manual_smoke_haiku_4_5_execute_to_done`** — same as V8 but for `execute → done`. Fixture: `phase=execute, approved=true`, all verification passing. Prompt: "Verification is green. Close out the phase." Pass criterion: the model emits `harness phase set done` and does NOT emit a follow-up `harness phase approve` (G2-C: approve in done is exit-6). Pass rate ≥ 4/5.
11. **V11 `manual_smoke_haiku_4_5_done_to_new_cycle`** — fixture: `phase=done`. Prompt: "Start the next slice." Pass criterion: the model emits `harness phase set discuss --reset-approval` (per ADR-001 transition table footnote: `done→discuss` requires `--reset-approval` as the safety prompt). Pass rate ≥ 4/5.
12. **V12 `grep_each_updated_command_cites_cli_verb_once`** — run `grep -lE "harness phase (set|approve)" .roo/commands/phase-discuss.md .roo/commands/phase-plan.md .roo/commands/phase-execute.md .opencode/commands/discuss.md .opencode/commands/plan.md .opencode/commands/execute.md .opencode/commands/done.md`. MUST return ALL 7 files. Pre-slice: expected to return 0 files. Post-slice: 7/7.
13. **V13 `grep_no_show_phase_status_drift`** — `grep -nE "show_phase_status\.py" .roo/skills/*/SKILL.md .roo/commands/*.md .opencode/commands/*.md`. Existing references MUST be preserved (this is the read-side projector, unaffected by ADR-003a). Pre-slice and post-slice counts MUST match; the slice MUST NOT remove an existing `show_phase_status.py` reference. This catches over-aggressive surface edits.

## Step 0 — Enumerate exact files to touch (recorded in the plan)

The grep audit below was run on `develop` as of 2026-05-16; the result list is the immutable file scope for the slice. Adding or removing a file from this list requires a spec amendment.

### Step 0 audit commands (recorded for reproducibility)

```bash
grep -lE "phase-state\.json" .roo/skills/*/SKILL.md
grep -lE "phase-state\.json" harness/skill-packs/**/*/SKILL.md
grep -lE "\.scratch/phase-state\.json" .roo/commands/phase-*.md .opencode/commands/*.md
```

### Enumerated file list (Step 0 result — 17 files in scope)

`.roo/skills/` (10 SKILL files, all reference `.scratch/phase-state.json` for direct-edit or read-then-classify):

- `.roo/skills/workflow-phase-gate/SKILL.md` — **anchor SKILL**, owns the G3-A canonical `done` few-shot. Largest surface-touch. Lines 13, 20, 23, 24, 92, 93, 161, 250.
- `.roo/skills/workflow-architecture-decision/SKILL.md` — references state file in the ADR-changes-roadmap context.
- `.roo/skills/workflow-bug-diagnosis/SKILL.md` — references state file in the diagnosis-as-discuss-mode context.
- `.roo/skills/workflow-code-review/SKILL.md` — references state file in the review-as-read-only context.
- `.roo/skills/workflow-docs-to-issues/SKILL.md` — references state file in the issue-emission-from-plan context.
- `.roo/skills/workflow-feature-tdd/SKILL.md` — references state file in the execute-with-approved-plan context.
- `.roo/skills/workflow-harness-doctor/SKILL.md` — references state file in the diagnostic-read context.
- `.roo/skills/workflow-ops-observability/SKILL.md` — references state file in the ops-as-execute-subset context.
- `.roo/skills/workflow-planning-hydration/SKILL.md` — references state file in the existing-repo-adoption context.
- `.roo/skills/workflow-simple-task/SKILL.md` — references state file in the small-edit-bypass-acknowledgement context.

`harness/skill-packs/` (0 files in scope — Step 0 confirmed):

- The pack SKILLs that surfaced in the broad `grep -l "approved"` (`workflow-etl`, `tech-postgresql`, etc.) use `approved` only as English prose ("approved migration plan", "approved by reviewer") and do NOT reference `.scratch/phase-state.json` or instruct direct-edit. They are out of scope.
- If a future review finds a pack SKILL that instructs phase-state edits, that fix becomes a follow-up PR under v2 T1-9, not this slice.

`.roo/commands/` lifecycle 4 (3 files exist; the 4th is intentionally absent — see Note A below):

- `.roo/commands/phase-discuss.md`
- `.roo/commands/phase-plan.md`
- `.roo/commands/phase-execute.md` — contains the "verify `.scratch/phase-state.json` directly" instruction at line 13; this is the primary direct-edit substitution site.

`.opencode/commands/` (4 files):

- `.opencode/commands/discuss.md`
- `.opencode/commands/plan.md` — contains the "do not write `phase=execute`" guard at lines 21–28 that lists field-by-field provenance the user must hand-write; this becomes "use `harness phase set execute && harness phase approve`" (CLI writes the provenance).
- `.opencode/commands/execute.md` — contains the "verify `.scratch/phase-state.json` has `phase=execute, approved=true`" instruction at lines 11–28; the verification stays (it is a precondition check, not a write), but the "phase-state updates made, if any" checklist item at line 45 must reference the CLI verb.
- `.opencode/commands/done.md` — contains the "Re-read the live gate" instruction (read-only, no surface change needed for ADR-003a) but the post-done invocation MUST cite `harness phase set discuss --reset-approval` for the new-cycle path.

**Note A — `.roo/commands/done.md` ownership (UPDATED per CONTRACT-PIN §5.2):** The 4-lifecycle-commands-per-adapter rule in spec §10.2 expects `discuss`, `plan`, `execute`, `done` in `.roo/commands/`. Roo currently ships only the first three as `phase-*.md`. **T1-S NOW OWNS** creating `.roo/commands/done.md` per CONTRACT-PIN §5.2 (re-assignment from "T0-3 adapter mirroring" to T1-S explicitly). The file mirrors `.opencode/commands/done.md` with the documented `.roo` frontmatter conventions. See new Task 14a below. With this addition T1-S touches 18 files (3+1 Roo lifecycle + 4 OpenCode lifecycle + 10 SKILLs).

**Note B — `.roo/skills/` vs `harness/skill-packs/`:** The spec §7 row says "the 3–5 SKILL files in `harness/skill-packs/**`". The actual count is 10 in `.roo/skills/` and 0 in `harness/skill-packs/`. The size estimate is therefore bumped from S to M per the ADR-bundle revisor note (referenced in this plan's header). The location discrepancy is because the Phase 1 workflow SKILLs live under `.roo/skills/` (Roo adapter–native) and the pack SKILLs under `harness/skill-packs/` are tech-stack SKILLs that do not gate on phase state. T1-S touches the workflow SKILLs; the pack SKILLs are correctly left alone.

## Worked examples of the substitution (illustrative, not prescriptive)

The examples below show exactly what a Rule R1 + R4 edit looks like on a specific line of `.roo/skills/workflow-phase-gate/SKILL.md`. They are recorded to anchor reviewer expectations; the per-file tasks below MAY produce slightly different prose as long as the rules hold.

### Example E1 — `.roo/skills/workflow-phase-gate/SKILL.md:92` (R1 direct-edit → CLI invocation)

Pre-slice (line 92, inside the `--chain` rules block):

> Before implementation, verify or write `.scratch/phase-state.json` with `phase=execute`, the same `plan_id`, `approved=true`, non-empty `allowed_paths`, non-empty `verification`, durable planning pointers, and recorded `automation_mode=chain`.

Post-slice:

> Before implementation, ensure the live gate reads `phase=execute, approved=true` with the same `plan_id`. Reach that state via `harness phase approve && harness phase set execute` (the CLI writes `approved_by`, `approved_at`, and re-stamps `updated_at`). Pre-conditions the CLI does NOT set — `allowed_paths`, `verification`, durable planning pointers, `automation_mode=chain` — remain user-editable; verify them with `harness check` before invoking `set execute`.

### Example E2 — `.roo/skills/workflow-phase-gate/SKILL.md:93` (R6 approval-provenance defer to CLI)

Pre-slice (line 93):

> Any `phase=execute` state with `approved=true`, including `automation_mode=manual`, must also record non-empty `approved_by` and `approved_at` provenance.

Post-slice:

> Any `phase=execute` state with `approved=true` carries `approved_by` and `approved_at` provenance set by `harness phase approve` (stamped from `git config user.email` and `time.time_ns()` per ADR-003a Verb 2). Manual mode and chain mode produce identical provenance shape.

### Example E3 — `.opencode/commands/execute.md:11-15` (R1 + R4 collapse)

Pre-slice (lines 11–15, the preflight checklist):

> - [ ] `.scratch/phase-state.json` says `phase=execute`.
> - [ ] `.scratch/phase-state.json` says `approved=true`.
> - [ ] `plan_id` matches the plan being executed.
> - [ ] `allowed_paths` is non-empty.
> - [ ] `verification` is non-empty.

Post-slice (the assertion stays as a read-side check; the write side moves to the CLI invocation block at the bottom of the file):

> - [ ] `harness check` exits 0 with `phase=execute, approved=true` and the expected `plan_id`.
> - [ ] `allowed_paths` is non-empty.
> - [ ] `verification` is non-empty.

(plus the new R4 block at the end of the file:)

```text
# To advance lifecycle without direct-editing .scratch/phase-state.json:
harness phase approve               # in phase=plan or execute
harness phase set <discuss|plan|execute|done>
```

### Example E4 — `.roo/skills/workflow-feature-tdd/SKILL.md` (R3 verification-prefix cleanup)

Hypothetical pre-slice bullet (illustrative — the actual line numbers vary):

> - [ ] Confirm the failing test reproduces the bug.
> - [ ] Validate the fix against the existing suite.
> - [ ] Review the diff with the architecture mode.
> - [ ] bash pytest scripts/

Post-slice (Rule R3):

> - [ ] Reproduce the failing test (move "confirm" to prose — this is a verification-step description, not a verification[*] string).
> - [ ] `pytest scripts/` (allowlisted verb; `bash ` prefix dropped per D-G4).
> - [ ] Architecture-mode review (move to `review[*]` field at completion; ADR-004 `review` shape is `{actor, at, evidence_path, summary}`).

The grep-gate V3 then sees zero matches for the removed prefixes in a verification context, because the words either moved to prose or to the `review` field that V3 does not scan.

## Surface-touch substitution rules (per-file mechanical pattern)

For every file in the enumerated list, the edit applies the rules below verbatim. No prose rewrites beyond the rules.

### Rule R1 — Direct-edit instruction replacement

Find any sentence-or-bullet-list-item shaped like:

> "verify `.scratch/phase-state.json` has `phase=X`, `approved=true`, ..."

OR

> "write `.scratch/phase-state.json` with `phase=execute`, ..."

OR

> "update `.scratch/phase-state.json` to ..."

Replace with the CLI invocation that produces the same end state:

- `phase=discuss` target: `harness phase set discuss`
- `phase=plan` target: `harness phase set plan`
- `phase=execute` target (which requires prior approval): `harness phase approve && harness phase set execute`
- `phase=done` target: `harness phase set done`
- New-cycle (from `done`): `harness phase set discuss --reset-approval`

The verification clause (the "has X, Y, Z" part) becomes a `harness check` invocation if it was an assertion, or is dropped if it was a setup-write. The grep-gate V4 catches misses.

### Rule R2 — Read-then-classify instructions are preserved

Sentences that READ `.scratch/phase-state.json` to derive a classification (e.g., "if `phase=plan` and `approved=true`, proceed to execute") are NOT touched. The read side of the contract is unchanged in ADR-003a; only the write side is gated by the CLI. The grep gate V4 specifically targets write verbs (`write|edit|>`), not read verbs (`verify|check|read|identify`).

### Rule R3 — Removed verification prefixes excised from verification[*] strings

Any bullet-list item that looks like a verification[*] entry (i.e., it appears inside a section titled "Verification", "verification commands", or is a bare bullet shaped like a shell command in a checklist) starting with `Confirm `, `Validate `, `Review `, `Inspect `, `Roo`, `core-only `, `OpenCode-only `, or `bash ` is rewritten:

- `Confirm X` → if X is a check, becomes `harness check` or `python3 scripts/harness.py check`; if X is human review prose, moves to the `review` field (annotated as such in the surrounding text, not a JSON edit).
- `Validate X` / `Inspect X` / `Review X` → same treatment.
- `bash <cmd>` → bare `<cmd>` if `<cmd>` already starts with an allowlisted verb (`python3`, `git`, `jq`, `npx`, `pytest`, `harness`, `make`); else dropped with a comment pointer to `docs/protocol-spec.md#verification-allowlist`.
- `Roo<anything>` → dropped; the false-positive root cause is removed.

Prose uses of these words (e.g., "Inspect the file before editing" in a phase-discuss instruction) are NOT verification[*] strings and are preserved. The grep-gate V3 records each match's classification.

### Rule R4 — One canonical CLI invocation per SKILL

Each updated SKILL file gains exactly ONE new code block (≤3 lines) of the form:

```text
# Move forward in the phase lifecycle:
harness phase set <phase>          # discuss | plan | execute | done
harness phase approve              # only in phase=plan or phase=execute; no-op error in done
```

This block lives near the existing "Required State Check" or "Stop Conditions" section of each SKILL. No other example is added. This satisfies the "one canonical few-shot per SKILL" requirement in the user prompt without expanding the SKILL surface.

### Rule R5 — Anchor-SKILL exception (workflow-phase-gate only)

`workflow-phase-gate/SKILL.md` is the single SKILL that includes the full G3-A `done` JSON few-shot (verified by V7). The block is added as a fenced JSON code block under a new heading `## Canonical `phase=done` Example (post-CLI)` placed after the existing `## Low-Reasoning Checklist` section. The block is byte-identical to the JSON in `docs/adr/2026-05-16-hardening-bundle.md` lines 599–640 (Artifact 1 G3-A). Other SKILLs reference this section via the path `.roo/skills/workflow-phase-gate/SKILL.md#canonical-phase-done-example-post-cli` instead of re-pasting.

### Rule R6 — Approval provenance instructions defer to CLI

Sentences instructing the model to "record `approved_by` and `approved_at`" (e.g., `.roo/skills/workflow-phase-gate/SKILL.md:93`, `.opencode/commands/plan.md:24-26`) are replaced with "run `harness phase approve` (the CLI stamps `approved_by` from `git config user.email` and `approved_at` to nanosecond precision per ADR-003a Verb 2)". The grep V2 catches any leftover `approved_by.*approved_at` instruction outside a few-shot block.

### Rule R7 — `phase=done` approval clarification

Per G2-C, `harness phase approve` is a no-op (exit 6) in `phase=done`. SKILL prose that previously said "in done, ensure `approved` is set" is replaced with "in done, `approved`/`approved_by`/`approved_at` are preserved verbatim from the prior `execute→done` transition; do NOT re-issue `harness phase approve`." This rule applies primarily to `workflow-phase-gate/SKILL.md` `### done` section (lines 198–220) and the OpenCode `done.md`.

## Implementation tasks (in order)

**Task 0 (FIRST commit per CONTRACT-PIN §7)**: `docs(changelog)!: Breaking entry L20 (SKILL surface CLI alignment; adapter command files use new verbs) (T1-S)`. Append L20 row under `## Unreleased (develop)` → `### Breaking` before any verification-gate or SKILL-edit commit.

**Task 14a (NEW per CONTRACT-PIN §5.2)**: create `.roo/commands/done.md` mirroring `.opencode/commands/done.md` with Roo frontmatter conventions. Apply Rules R1, R4, R7. Land in the same commit as the other Roo lifecycle edits (task 14) OR a dedicated commit `feat(.roo/commands/done.md): add Roo lifecycle done command per CONTRACT-PIN §5.2`. With this addition the Roo lifecycle set is 4 files (discuss, plan, execute, done); the V6 / V12 grep gates update to expect 4 Roo + 4 OpenCode = 8 lifecycle files (was 3 + 4 = 7).

Tasks 1–4 land the verification gates and the manual-smoke fixtures BEFORE any SKILL edit (verification-list-first discipline, the markdown analogue of TDD). Tasks 5–14 apply the per-file surface edits. Tasks 15–17 run the post-edit verification suite. Task 18 records the slice summary.

1. **Add the V1/V2/V3/V4/V6/V7/V12/V13 grep commands as a shell script** at `scripts/verify_t1s_skill_surface.sh` (or a Python module if a shell helper convention exists; check `scripts/` for prior art). The script exits non-zero on any verification failure and prints the violating lines. Pre-slice: run it against `develop` HEAD and record the baseline match counts (expected: V1 matches >0, V4 matches >0, V6 returns empty set, V7 returns 0). Commit the script with the baseline counts in a comment block.
2. **Capture the V5 pre-slice grep-gate output** (`grep -l "write.*phase-state.json" .roo/commands/{adr,bugfix,feature,doctor,issues,ops,fsd-phase,review,simple}.md`) and assert it is empty. If it is non-empty, the slice cannot begin — open a follow-up issue and pause. (Pre-slice run on develop returned empty; documented in the slice summary.)
3. **Stand up the V8/V9/V10/V11 manual smoke fixtures** under `scripts/smoke/t1s_haiku_fixtures/` as four small JSON files representing the four pre-prompt phase states. The fixtures do not yet have a runner (the `low_reasoning_scenario.py` script is built in a parallel slice task per spec §9.1); for T1-S the runner is "paste into Haiku-4.5 web playground or the SDK Python REPL" and the pass criterion is recorded by hand in the PR description.
4. **Pre-edit dry-run of the anchor SKILL only:** edit `.roo/skills/workflow-phase-gate/SKILL.md` first (Rule R1 + R4 + R5 + R6 + R7 applied), run V1+V2+V3+V6+V7 against that single file, fix any rule-application mistakes, then commit. This is the prototype edit; the remaining 9 SKILLs follow the same shape with minor per-file variation.
5. **Edit `.roo/skills/workflow-architecture-decision/SKILL.md`** — apply Rules R1, R3, R4. Skip R5 (no anchor JSON), R6 (no approval-provenance prose). Re-run V1+V6 against the edited file.
6. **Edit `.roo/skills/workflow-bug-diagnosis/SKILL.md`** — apply Rules R1, R4. The diagnosis SKILL is read-mostly; the write site is the "if confirmed, escalate to plan" instruction.
7. **Edit `.roo/skills/workflow-code-review/SKILL.md`** — apply Rules R1, R3, R4. The R3 application targets the review verification checklist where bare `Review` and `Inspect` bullets currently double as verification[*] candidates.
8. **Edit `.roo/skills/workflow-docs-to-issues/SKILL.md`** — apply Rules R1, R4. The write site is the "emit issue list and transition to plan" instruction.
9. **Edit `.roo/skills/workflow-feature-tdd/SKILL.md`** — apply Rules R1, R3, R4. The TDD SKILL contains the most verification[*] surface; R3 application is highest density here.
10. **Edit `.roo/skills/workflow-harness-doctor/SKILL.md`** — apply Rules R1, R4. The doctor SKILL also contains a `description` frontmatter line referencing "Roo command/mode" (line 4 in the read); confirm this is prose-Roo (referring to the Roo adapter as a system name) not the bare-`Roo` verification prefix. It is the former; leave the frontmatter alone. Document this in the PR.
11. **Edit `.roo/skills/workflow-ops-observability/SKILL.md`** — apply Rules R1, R3, R4. Ops SKILL has bare `Confirm` / `Validate` bullets in its instrumentation-readiness checklist.
12. **Edit `.roo/skills/workflow-planning-hydration/SKILL.md`** — apply Rules R1, R4. The hydration SKILL writes `.planning/codebase/**` but READS `.scratch/phase-state.json`; the R1 application is minimal (one bullet).
13. **Edit `.roo/skills/workflow-simple-task/SKILL.md`** — apply Rules R1, R4. The "simple task bypass" SKILL still acknowledges the live gate; the bypass remains direct-edit-or-CLI (per ADR-003a option 2's "warn but do not fail" policy).
14. **Edit the 3 Roo lifecycle command files** (`phase-discuss.md`, `phase-plan.md`, `phase-execute.md`) — apply Rules R1, R3 (verification bullets in the execute output checklist), R4 (CLI invocation block at the bottom of each file). Most surface load is on `phase-execute.md` step 1.
15. **Edit the 4 OpenCode lifecycle command files** (`discuss.md`, `plan.md`, `execute.md`, `done.md`) — apply Rules R1, R3, R4, R6 (especially `plan.md` lines 21–28 and `execute.md` line 45), R7 (especially `done.md` post-transition guidance). The OpenCode files are denser with field-level provenance prose than the Roo files; R6 application is highest here.
16. **Run the full V1–V7 + V12–V13 grep gate** (`bash scripts/verify_t1s_skill_surface.sh`). Expected: all gates pass (exit 0). If V2 or V3 reports a match the slice classifies as legitimate prose (per the rules), annotate the script's allowlist with the specific file:line pair and re-run. The allowlist MUST be small (≤5 entries total across the 17 files) and each entry MUST cite the rule (R2 prose preservation) that justifies it.
17. **Run V8–V11 manual smoke** against the edited SKILLs + adapter commands. Record per-trial pass/fail in `.planning/phases/02b-hardening/evidence/t1s-haiku-smoke.md` (one row per (flow, trial) pair, 5 trials × 4 flows = 20 rows). Slice acceptance requires ≥ 4/5 per flow, matching the spec §9.1 80% floor scaled to the 5-trial T1-S budget. If the model emits a direct-edit instruction in any trial, that is a fail; record the prompt and the model output verbatim.
18. **Re-run V5 post-edit** as a regression check that no quarantined Roo command file picked up a write-instruction during the slice. Expected: empty output. If non-empty, the slice has accidentally over-touched; revert the offending hunk and re-run.
19. **Write the slice summary** (`.planning/phases/02b-hardening/plans/02b-08-T1-S-SUMMARY.md`) including: the file list (17 files), the V1–V13 final pass/fail status, the V8–V11 trial log link, the V2/V3 allowlist entries (with rule citation each), and the `.roo/commands/done.md` absence note (Note A above) flagged as a follow-up for T0-3 adapter mirroring.

## Dependency on other slices

- Consumes: T0-3 CLI contract artifact (Artifact 1 in the ADR bundle: verb names, arg shapes, exit codes, transition table, G2-C `done.approve` no-op). T0-3 implementation does NOT need to be merged before T1-S begins; only the contract document does (per spec §8 "T1-S sequences after the CLI contract artifact (not after T0-3 implementation)"). The contract is locked in `docs/adr/2026-05-16-hardening-bundle.md`.
- Consumes: T0-1 done shape (ADR-001: `done` drops the `approved` constraint; `state_schema_version` bumps to 2). The canonical G3-A few-shot embedded by Rule R5 contains `state_schema_version: 2` and `phase: done` with `approved: true` (preserved from the prior execute→done transition). This is the shape T0-1 produces.
- Consumes: T0-4 verification allowlist (ADR-004: 7 verbs — `python3`, `git`, `jq`, `npx`, `pytest`, `harness`, `make`). Rule R3 is derived directly from this.
- Provides: aligned weak-model instructions for the Phase E Haiku trial harness (spec §9.1). V8–V11 are a 5-trial-per-flow preview; the full 50-trial-per-flow harness (`scripts/smoke/low_reasoning_scenario.py`) is a separate slice task and consumes the SKILL surface T1-S produces.
- Provides (negative space): assurance to T1-1 (`check --worktree` wiring) that the SKILL surface will not instruct the model to bypass the CLI. T1-1 can rely on "the SKILL says `harness phase set X`" as a precondition.

## Open questions deferred to PR review (NOT decision-blockers)

The following surfaced during plan drafting and are recorded so the reviewer can confirm or override during PR. None gate the slice from starting.

- **Q1 — `.roo/skills/workflow-harness-doctor/SKILL.md` frontmatter `Roo` mentions.** Lines 3–4 mention "Roo" as the adapter system name (e.g., "Roo command/mode"). This is prose-Roo, not the bare-`Roo` verification prefix that ADR-004 removes. The slice preserves these. The reviewer is asked to confirm no other SKILL frontmatter has a similar ambiguity.
- **Q2 — `.roo/commands/done.md` parity gap.** As noted in Note A, Roo lacks a `done.md` lifecycle command file. T1-S documents the gap but does not create the file. The reviewer is asked to confirm this is owned by T0-3 / T1-1 adapter mirroring, not by T1-S.
- **Q3 — `workflow-simple-task/SKILL.md` bypass acknowledgement.** The simple-task SKILL exists to acknowledge that small edits MAY bypass the full phase gate. Post-ADR-003a, the bypass is "direct edit + accept the drift-warning"; the slice surfaces this in the SKILL but does NOT remove the bypass entirely. The reviewer is asked to confirm this matches ADR-003a's "warn but do not fail" policy intent.
- **Q4 — Pack SKILLs (`harness/skill-packs/**`) with prose-`approved`.** The Step 0 audit excluded these because they do not instruct phase-state edits. The reviewer is asked to spot-check 2–3 pack SKILLs to confirm the exclusion is correct.
- **Q5 — V8–V11 trial count (5 vs 50). RESOLVED per CONTRACT-PIN §8.1.** V8–V11 are ADVISORY 5-trial preview smokes only; they do NOT gate slice acceptance. The N=50 acceptance lives in `02b-10-PHASE-E-HARNESS-PLAN.md`. Failure of V8–V11 at the row level emits a follow-up note for 02b-10 but does NOT block T1-S merge. The slice ships if V1–V7 and V12–V13 (grep gates) and Task 14a (`.roo/commands/done.md`) all pass; V8–V11 results are recorded as evidence for the downstream 02b-10 plan.

## Per-file estimated edit sizes (LOC change estimate, for sequencing)

The numbers below are pre-edit estimates from the Step 0 grep audit. They drive the commit ordering (heaviest first to surface rule-application bugs early).

| File | Approx LOC touched | Rules applied |
|---|---|---|
| `.roo/skills/workflow-phase-gate/SKILL.md` | 25–35 (+ ~40 for G3-A few-shot block) | R1, R4, R5, R6, R7 |
| `.roo/skills/workflow-feature-tdd/SKILL.md` | 8–12 | R1, R3, R4 |
| `.roo/skills/workflow-ops-observability/SKILL.md` | 6–10 | R1, R3, R4 |
| `.roo/skills/workflow-code-review/SKILL.md` | 5–8 | R1, R3, R4 |
| `.roo/skills/workflow-architecture-decision/SKILL.md` | 3–5 | R1, R3, R4 |
| `.roo/skills/workflow-bug-diagnosis/SKILL.md` | 3–5 | R1, R4 |
| `.roo/skills/workflow-docs-to-issues/SKILL.md` | 3–5 | R1, R4 |
| `.roo/skills/workflow-harness-doctor/SKILL.md` | 3–5 | R1, R4 |
| `.roo/skills/workflow-planning-hydration/SKILL.md` | 2–4 | R1, R4 |
| `.roo/skills/workflow-simple-task/SKILL.md` | 2–4 | R1, R4 |
| `.roo/commands/phase-execute.md` | 5–8 | R1, R3, R4 |
| `.roo/commands/phase-plan.md` | 2–4 | R1, R4 |
| `.roo/commands/phase-discuss.md` | 1–3 | R1, R4 |
| `.opencode/commands/execute.md` | 8–12 | R1, R3, R4 |
| `.opencode/commands/plan.md` | 6–10 | R1, R4, R6 |
| `.opencode/commands/done.md` | 4–6 | R1, R4, R7 |
| `.opencode/commands/discuss.md` | 2–4 | R1, R4 |

Total estimate: 90–150 LOC of net text change across 17 files, plus the ~40-line G3-A few-shot block in the anchor SKILL. Well within the "surface-touch, no rewrite" envelope.

## Verification commands

Run from repo root.

- `bash scripts/verify_t1s_skill_surface.sh` — runs V1–V7 + V12–V13 grep gates; exits 0 iff every gate passes.
- `grep -l "write.*phase-state.json" .roo/commands/{adr,bugfix,feature,doctor,issues,ops,fsd-phase,review,simple}.md` — the spec §10.2 / M5 quarantine gate (V5); MUST be empty.
- Manual smoke V8–V11: paste each `(SKILL.md, command.md)` pair into Haiku-4.5 with the recorded fixture state and prompt; record pass/fail in the evidence file.
- `python3 scripts/harness.py check` — sanity check that the unchanged read side of phase-state.json still passes the checker after the slice. (This is a regression sanity, not a T1-S acceptance.)

## Commits (atomic, in order)

One commit per task or per tight task cluster; squash only on review request.

1. `chore(t1s): grep-gate script for SKILL surface alignment` (task 1 + task 2)
2. `chore(t1s): Haiku-4.5 smoke fixtures for 4 lifecycle flows` (task 3)
3. `refactor(skill,phase-gate): CLI verbs replace direct-edit; G3-A canonical done few-shot` (task 4 — anchor SKILL prototype)
4. `refactor(skill,architecture-decision): CLI verb invocations` (task 5)
5. `refactor(skill,bug-diagnosis): CLI verb invocations` (task 6)
6. `refactor(skill,code-review): CLI verb invocations + R3 verification-prefix cleanup` (task 7)
7. `refactor(skill,docs-to-issues): CLI verb invocations` (task 8)
8. `refactor(skill,feature-tdd): CLI verb invocations + R3 verification-prefix cleanup` (task 9)
9. `refactor(skill,harness-doctor): CLI verb invocations` (task 10)
10. `refactor(skill,ops-observability): CLI verb invocations + R3 verification-prefix cleanup` (task 11)
11. `refactor(skill,planning-hydration): CLI verb invocations` (task 12)
12. `refactor(skill,simple-task): CLI verb invocations` (task 13)
13. `refactor(.roo/commands): lifecycle 3 (discuss/plan/execute) call harness phase verbs` (task 14)
14. `refactor(.opencode/commands): lifecycle 4 (discuss/plan/execute/done) call harness phase verbs` (task 15)
15. `chore(t1s): full grep gate green; allowlist annotated for R2 prose matches` (task 16)
16. `docs(t1s): Haiku-4.5 smoke trial log + slice summary` (tasks 17 + 18 + 19)

## Risk + reversibility

- Risk: **L–M (low to medium)** — text-only edits, but the surface area is 17 files and the changes affect every weak-model lifecycle prompt. The mitigation is the V8–V11 Haiku smoke catching any prompt that no longer steers the model to the CLI.
- Reversibility: **yes** — every edit is a text revert. No on-disk state changes shape. SKILL files and adapter commands have no persistent state; an adapter re-install picks up the prior shape.
- Migration: **none required** for installed adapters in the wild. The CLI verbs (`harness phase set`, `harness phase approve`) are the canonical path post-slice; users with pre-slice SKILL caches still issue direct edits that the CLI's drift-warning mechanism (ADR-003a) handles gracefully. Upgrade-path users get the new SKILLs on the next `harness install` or `harness upgrade`.
- Sequencing safety: T1-S lands after the ADR bundle locks (which the spec §8 graph already enforces) and in parallel with T0-3 implementation. T0-3 may iterate on CLI internal details without breaking T1-S because T1-S consumes only the locked contract surface (verb names, exit codes, transition table — none of which T0-3 can change without re-opening the ADR).
- Failure mode if smoke V8–V11 fails: the SKILL prose is steering the model away from the CLI. The fix is per-file text iteration on the offending SKILL until the model emits the canonical CLI invocation in ≥ 4/5 trials. The slice does NOT block T0-3 implementation on this; if the smoke fails after 2 prose iterations, the slice ships with a documented gap recorded under `02c-hardening` per spec §9.1 budget escape clause.
