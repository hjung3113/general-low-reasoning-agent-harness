# Script-Oriented Harness Workflow Design

## Purpose

This note records the safe direction for reducing LLM reasoning in the harness workflow without breaking the phase gate.

The harness should move deterministic work into scripts, but scripts must not become a second source of truth. The canonical project memory remains `.planning/**`. The live gate remains `.scratch/phase-state.json`. Scripts should project, validate, and index that state so agents read less and infer less.

## Problem

The current document-centered workflow preserves continuity, but it asks agents and humans to understand too much before doing simple work:

1. Fresh sessions are told to read `.planning/STATE.md`, `.planning/ROADMAP.md`, `.planning/codebase/**`, active phase files, and `.scratch/phase-state.json`.
2. Agents must compute deterministic state from those files: current phase, active checkpoint, active plan, approval status, allowed paths, and verification commands.
3. `scripts/harness.py` has a coherent maintainer-facing command surface, but it is hard for low-reasoning agents and casual users to pick the right command from a subcommand matrix.

The goal is not to remove durable planning docs. The goal is to stop asking the LLM to compute deterministic state from those docs.

## Principle

Script anything that does not need judgment.

Use LLM reasoning for:

- clarifying user intent
- identifying non-goals
- proposing first usable slices
- choosing between tradeoffs
- adversarial review
- implementation or document drafting

Use scripts for:

- finding the current phase
- resolving active phase documents
- checking phase approval
- checking roadmap/state/checkpoint/live-gate sync
- checking allowed paths
- checking acceptance criteria and verification requirements
- computing phase progress
- producing a small preflight summary for the LLM

## Core Design: Preflight Projection First

The first safe slice is `scripts/show_phase_status.py`.

This script is a deterministic projection of canonical files. It is not a replacement source of truth.

Agents should start with:

```bash
python3 scripts/show_phase_status.py
```

If the script is missing, exits nonzero, emits malformed output, or reports an unsupported output contract version, agents must fall back to the legacy durable planning read order and mention the fallback:

1. `.planning/STATE.md`
2. `.planning/ROADMAP.md`
3. `.planning/codebase/**`
4. active phase checkpoint
5. active phase docs
6. `.scratch/phase-state.json`

If the script reports warnings, agents should treat the named files as the minimum required reads before trusting the projection. Command-specific required reads still apply, especially before `plan`, `execute`, and `done`.

If the script reports no warnings, agents should use the summary as a deterministic index into canonical planning files. For normal orientation, they should read only task-specific files or the exact active files listed by the script. When executing, resolving ambiguity, or changing phase state, they must verify against the referenced canonical files.

This changes durable planning docs from "everything the LLM must read first" into "the canonical database that scripts summarize and point into."

## `show_phase_status.py` Output Contract

The output should be short, stable, and easy for low-reasoning agents to follow.

Version 1 output must be JSON only on stdout: a single JSON object and no
surrounding prose, Markdown, ANSI formatting, headings, or explanatory text.
Human-readable diagnostics may go to stderr only when the command exits
nonzero. Callers must parse stdout as JSON before trusting any field.

Required fields:

- `contract_version`
- `phase`
- `phase_id`
- `phase_title`
- `approved`
- `plan_id`
- `automation_mode`
- `projected_execute_gate_valid`
- `projected_execute_gate_reason`
- `active_phase_folder`
- `active_checkpoint_id`
- `active_checkpoint_title`
- `active_checkpoint_status`
- `state_path`
- `roadmap_path`
- `checkpoint_path`
- `plan_path`
- `verification_path`
- `summary_path`
- `allowed_paths`
- `blocked_paths`
- `acceptance_criteria`
- `verification`
- `warnings`
- `required_reads`
- `suggested_next_read`
- `next_steps`

`next_steps` is a compact additive summary for low-reasoning agents:

- `trusted`: `true` when no warning requires an extra read before trusting the projection.
- `read_next`: the first required planning file to read next.
- `may_edit`: mirrors the projected execute gate; it is not a substitute for `harness check` in adapter workflows.
- `must_verify`: verification commands named by the active phase.

Identity fields must be stable, path-independent identifiers extracted from
canonical planning files, not inferred display labels. At minimum:

- `phase_id` comes from the phase folder prefix or explicit phase metadata when
  introduced.
- `active_checkpoint_id` comes from the checkpoint heading, such as
  `CP-01-03`.
- `plan_id` comes from `.scratch/phase-state.json` or the canonical plan
  metadata, and drift between them is a warning.
- paths are repository-relative strings using `/`, so installed targets and
  adapter prompts can compare them deterministically.

`projected_execute_gate_valid` may be true only when the execute gate appears valid from canonical files:

- `phase=execute`
- `approved=true`
- `plan_id` is present
- approval metadata is present
- durable pointers are present
- `allowed_paths` is non-empty
- `acceptance_criteria` is non-empty
- `verification` is non-empty
- roadmap/state/checkpoint/live-gate pointers are consistent

This field does not authorize edits, transitions, completion, or approval. Before application-code edits, execute workflows must verify the referenced canonical files directly.

Warnings must be structured objects, not free-form strings. Each warning should
have:

- `code`: stable machine-readable code, for example
  `state_checkpoint_drift`
- `severity`: `info`, `warning`, or `blocking`
- `message`: short human-readable explanation
- `paths`: exact repository-relative paths to inspect next
- `required_read`: boolean

A warning should not say "read planning docs"; it should name the relevant path
and reason. `blocking` means the projection was produced, but no workflow may
treat it as sufficient for preflight. In that case, callers must read all
warning paths plus the legacy durable planning read order before proceeding.
Non-blocking warnings still make their `paths` minimum required reads before
trusting the affected part of the projection.

The script should define stable exit semantics:

- `0`: projection produced successfully, even if it contains warnings
- nonzero: projection failed and callers must use the legacy durable planning read order

Callers must treat missing fields, invalid JSON or unsupported text format, and unsupported `contract_version` as fallback conditions.

The first version should use `contract_version: "phase-status.v1"`. Do not add a
text mode in v1. If a later human-readable mode is useful, it must be opt-in and
must not change default stdout semantics.

## Shared Library Requirement

Role-named scripts must not each parse planning files independently.

Add shared read-only planning helpers under `scripts/lib/` before adding more role scripts. `scripts/show_phase_status.py` and `scripts/harness.py` should call the same parsing and validation logic where possible.

The shared helper layer is mandatory for all current and future script surfaces
that inspect planning state. The first implementation must route
`scripts/show_phase_status.py`, `scripts/harness.py`, and
`scripts/project_dashboard.py` through the same read-only parser before any
behavioral divergence. Future transition scripts must also use this library
rather than adding one-off parsing.

The shared helper layer should cover:

- reading `.scratch/phase-state.json`
- parsing ROADMAP phase progress
- parsing STATE active position and checkpoint metadata
- resolving active phase docs from explicit pointers first
- detecting roadmap/state/checkpoint/live-gate drift
- computing exact `required_reads`
- computing `projected_execute_gate_valid` and `projected_execute_gate_reason`
- computing structured warnings, including `blocking` warnings
- exposing stable phase and checkpoint identity fields
- distinguishing active operating docs from historical evidence

Thin wrappers are acceptable. Duplicated gate semantics are not.

`scripts/project_dashboard.py` may keep its own presentation logic, but it must
consume the same parsed planning model. `scripts/test_project_dashboard.py`
should cover that it does not regress to independent parsing or contradictory
phase status semantics.

## Migration Rules

Keep `scripts/harness.py` installed and supported during migration. It remains the compatibility and advanced surface.

The first slice should install only:

- `scripts/show_phase_status.py`
- shared helpers under `scripts/lib/`

These paths become harness-owned installed paths. Upgrade must handle preexisting target-local files at those paths as conflicts, not silent overwrites. `upgrade --dry-run` should report collisions for `scripts/show_phase_status.py` and `scripts/lib/**` before mutation.

Do not introduce the full role-named script set in the first slice. In particular, defer:

- `start_phase.py`
- `pause_phase.py`
- `archive_phase.py`
- `complete_phase.py`
- `reopen_phase.py`
- `check_phase_gate.py`
- `check_harness.py`
- `install_harness.py`
- `upgrade_harness.py`
- dashboard rename aliases

The README can mention the future role-named direction, but executable quick-start commands must match scripts actually installed by the manifest.

Avoid renaming `scripts/project_dashboard.py` in the first pass. Stable installed command names are more useful than perfect names during migration.

Older installed targets must keep working without `show_phase_status.py`. Missing, broken, malformed, or unsupported status output must not block the legacy durable planning workflow.

Installed-output surfaces must also be audited. The first slice must account for
generated or installed copies of:

- `.agents/skills/**` when a target has project-local installed skills
- `.roo/skills/README.md`, not only individual `.roo/skills/*/SKILL.md` files
- `scripts/project_dashboard.py` and `scripts/test_project_dashboard.py`
- every `harness/profiles/*/PROFILE.md`

If `.agents/skills/**` is not present in the source repository, tests should
still cover a target that already has that path, because upgraded projects may
contain installed project-local skills from earlier workflows.

## Instruction Update Scope

Changing the restart order is a protocol change. Update instructions atomically with the first script.

At minimum, the same commit should update:

- root `AGENTS.md`
- `harness/skeleton/clean/AGENTS.md`
- `harness/skeleton/clean/README.md`
- `harness/skeleton/clean/.planning/HANDOFF-PROTOCOL.md`
- `harness/skeleton/clean/.planning/STATE.md`
- root `README.md`
- OpenCode phase commands: `.opencode/commands/discuss.md`, `plan.md`, `execute.md`, and `done.md`
- Roo phase commands: `.roo/commands/phase-discuss.md`, `phase-plan.md`, `phase-execute.md`, `fsd-phase.md`, `simple.md`, and command README material
- other Roo command files that route workflow intent when grep shows planning, gate, or verification language
- Roo rules: `.roo/rules/global.md`, `.roo/rules/phase-gate.md`, `.roo/rules-orchestrator/rules.md`, `.roo/rules-review/rules.md`, and mode-specific rules when they cite planning, gate, or verification behavior
- Roo skills that reload planning context or enforce phase scope
- `docs/protocol-spec.md`
- `docs/phase-gate-harness.md`
- `harness/manifest.json`
- focused tests

The new rule should be:

```text
Start with `python3 scripts/show_phase_status.py` when available. If it reports warnings, treat named files as minimum required reads before trusting the projection. If it is missing, fails, emits malformed output, or reports an unsupported contract version, use the legacy durable planning read order.
```

Do not leave conflicting instructions where one file says to read all planning docs first and another says to start with the status script.

OpenCode must be checked as a complete adapter surface, not only as a README update:

- `discuss.md` should use the status script before broad planning hydration and treat warnings as exact required reads.
- `plan.md` should use the status script to locate active docs, then still write canonical plan, allowed paths, acceptance criteria, verification, and approval request.
- `execute.md` should use the status script as the first execute preflight, but must still enforce the canonical execute gate before edits.
- `done.md` should use the status script to locate verification evidence and active summary targets before marking completion.

Roo must be checked at three layers:

- command files route the user intent
- rules define always-on gate behavior
- skills perform the actual planning, execution, review, doctor, and hydration work

All three layers need the same preflight wording or low-reasoning agents will receive contradictory instructions.

### Workflow Entrypoint Matrix

Instruction updates must be verified per workflow entrypoint, not only by generic
phase-command coverage. The implementation phase must maintain a
workflow-entrypoint matrix with one row per entrypoint and columns for:

- source file or rule surface
- adapter or layer
- workflow intent
- required `show_phase_status.py` preflight wording
- canonical gate fallback
- continuous-flow state carried between steps
- required smoke or contradiction check

The matrix must cover at least:

| Entrypoint | Required verification |
| --- | --- |
| OpenCode `discuss` | Starts with the projection before broad hydration and treats warnings as required reads. |
| OpenCode `plan` | Uses the projection to locate active docs, then writes canonical plan, allowed paths, acceptance criteria, verification, and approval request. |
| OpenCode `execute` | Starts with projection, then rechecks the canonical execute gate before edits. |
| OpenCode `done` | Uses projection to locate active verification evidence and completion targets before status changes. |
| Roo `phase-discuss` | Starts every phase with a fresh discuss pass and cannot reuse execute approval. |
| Roo `phase-plan` | Uses projected active docs while writing durable plan and approval request to canonical files. |
| Roo `phase-execute` | Treats projection as preflight only and enforces `.scratch/phase-state.json` plus canonical docs before edits. |
| Roo `fsd-phase` | Verifies the same preflight and gate behavior across its continuous discuss-to-done flow. |
| Roo `simple` | Uses the projection to select the correct lightweight path without bypassing phase gates. |
| Roo `review` | Reads projected active scope and verification commands before review findings. |
| Roo `doctor` | Reports projection, fallback, and instruction drift without changing canonical state. |
| Roo `feature` | Preserves phase-local discuss, plan, execute, and verification gates across feature scaffolding. |
| Roo `bugfix` | Preserves diagnosis and execute approval boundaries while using projected active scope. |
| Roo `adr` | Uses projection for active context, then writes architectural evidence to canonical docs. |
| Roo `issues` | Uses projection for active roadmap and phase context before creating or updating issue artifacts. |
| Roo `ops` | Uses projection for active scope and verification before ops or observability work. |
| Always-on Roo rules | State the same preflight/fallback rule as commands and do not contradict execute-gate rules. |
| Roo skills | Start with projection when available, then write durable evidence only to canonical planning docs. |
| `--auto` | Proves automation mode does not skip warnings, fallback, allowed paths, or verification requirements. |
| `--chain` | Proves chained workflows re-run preflight at each boundary and do not reuse stale approval. |
| Target smoke after upgrade | Proves an upgraded target can run the projection, legacy check, and scoped entrypoint checks. |

The matrix is also a test fixture. Tests must fail if any entrypoint contains
contradictory preflight instructions, omits the fallback rule, or gives an
adapter-specific gate that diverges from the shared canonical gate.

Continuous workflows need separate proof. Tests for `fsd-phase`, `--auto`, and
`--chain` must show that each new, reopened, renamed, inserted, or reshaped phase
gets a fresh phase gate and cannot inherit approval from an earlier phase shape.
Approval provenance must be tied to the current `phase_id`,
`active_checkpoint_id`, `plan_id`, and approved scope.

## Repository Surface Audit

A repository-wide grep for planning, phase-state, active-doc, scope-gate, and command-surface language found broad impact. Treat the following as the update map for the implementation phase.

Primary live instruction surfaces:

- `AGENTS.md`
- `README.md`
- `docs/protocol-spec.md`
- `docs/phase-gate-harness.md`
- `docs/agents/domain.md`
- `docs/agents/issue-tracker.md` when it describes active phase context

Skeleton target surfaces:

- `harness/skeleton/clean/AGENTS.md`
- `harness/skeleton/clean/README.md`
- `harness/skeleton/clean/.planning/HANDOFF-PROTOCOL.md`
- `harness/skeleton/clean/.planning/STATE.md`
- all skeleton `.planning/**` files that contain operating instructions about restart order, active phase context, verification, source of truth, or phase-state behavior
- phase-0 skeleton docs under `harness/skeleton/clean/.planning/phases/00-planning-hydration/`

OpenCode surfaces:

- `.opencode/commands/discuss.md`
- `.opencode/commands/plan.md`
- `.opencode/commands/execute.md`
- `.opencode/commands/done.md`

Roo command and rule surfaces:

- `.roo/README.md`
- `.roo/commands/README.md`
- `.roo/commands/adr.md`
- `.roo/commands/bugfix.md`
- `.roo/commands/doctor.md`
- `.roo/commands/feature.md`
- `.roo/commands/fsd-run-phase.md`
- `.roo/commands/issues.md`
- `.roo/commands/ops.md`
- `.roo/commands/phase-discuss.md`
- `.roo/commands/phase-plan.md`
- `.roo/commands/phase-execute.md`
- `.roo/commands/review.md`
- `.roo/commands/simple.md`
- `.roo/rules/global.md`
- `.roo/rules/phase-gate.md`
- `.roo/rules-orchestrator/rules.md`
- `.roo/rules-review/rules.md`
- `.roo/rules-architect/rules.md`
- `.roo/rules-diagnose/rules.md`
- `.roo/rules-docs-issues/rules.md`
- `.roo/rules-ops-observability/rules.md`
- `.roo/rules-tdd-code/rules.md`

Roo skill surfaces:

- `.roo/skills/workflow-phase-gate/SKILL.md`
- `.roo/skills/workflow-planning-hydration/SKILL.md`
- `.roo/skills/workflow-harness-doctor/SKILL.md`
- `.roo/skills/workflow-architecture-decision/SKILL.md`
- `.roo/skills/workflow-bug-diagnosis/SKILL.md`
- `.roo/skills/workflow-feature-tdd/SKILL.md`
- `.roo/skills/workflow-code-review/SKILL.md`
- `.roo/skills/workflow-docs-to-issues/SKILL.md`
- `.roo/skills/workflow-ops-observability/SKILL.md`
- `.roo/skills/workflow-simple-task/SKILL.md`

Harness skill-pack surfaces:

- `harness/skill-packs/workflow-core/verification-contract/SKILL.md`
- `harness/skill-packs/workflow-core/repository-evidence-research/SKILL.md`
- workflow packs that define verification, review, debugging, TDD, security, web, data, ETL, DB, and release-readiness behavior
- technology packs only when they cite phase scope, repository-approved verification, or active phase context

Historical planning evidence under `.planning/phases/**`, release plans under `docs/superpowers/**`, and current repository `.planning/**` files may mention the old flow as evidence. Do not rewrite historical evidence just to update instructions. Rewrite only current operating instructions and skeleton files that will be installed into targets.

This distinction is important for low-reasoning agents:

- active operating instructions are files that a fresh or upgraded target should
  follow now
- historical evidence is proof of earlier decisions, verification, release
  checks, or phase work

Scripts may index both, but instruction-update tasks must not normalize
historical evidence just because it mentions the old restart order. A report may
flag historical old wording as evidence, but it should not call it instruction
drift unless that file is still an active operating surface.

## Skill Update Scope

Skills that read or write planning state must change with the preflight script.

The update is not "all skills blindly." It is every skill that does one of these:

- starts a fresh session
- resolves active phase docs
- checks `phase=execute` or `approved=true`
- reads or writes `.scratch/phase-state.json`
- reads or writes ROADMAP/STATE/checkpoint files
- records verification evidence
- uses `allowed_paths`, `blocked_paths`, `acceptance_criteria`, or `verification`

These skills should begin by using `show_phase_status.py` when available, then use the script output to choose exact canonical files to read. They must still write durable evidence to the canonical planning docs, not to the script output.

High-priority skill groups:

- phase gate and planning hydration skills
- plan, execute, done, simple task, review, and doctor adapter skills
- workflow verification and release-readiness skills
- workflow code review, TDD, debugging, security review, and web development skills when they enforce phase scope or verification
- technology skills only when they mention phase gate, allowed paths, or verification commands

Skills that only provide domain guidance and do not touch planning state do not need a behavior change. They may keep pointing to the active phase context supplied by the caller.

Skill wording should avoid broad read instructions such as "read `.planning/**`" unless the status script is missing or reports warnings that require that expansion.

## Deferred Role-Named Scripts

Explicit role-named scripts are still a good later direction, but they need a stronger contract than the original sketch.

Future human-facing commands may include:

```bash
python3 scripts/check_harness.py
python3 scripts/check_phase_gate.py
python3 scripts/start_phase.py "Reduce planning context loading"
python3 scripts/pause_phase.py
python3 scripts/archive_phase.py 02-old-phase
python3 scripts/complete_phase.py
python3 scripts/doctor_harness.py
```

These scripts should be wrappers over shared library logic or over `scripts/harness.py`, not independent implementations.

### Future `check_phase_gate.py`

For `phase=execute`, this script must require:

- schema-valid phase state
- `phase=execute`
- `approved=true`
- `plan_id`
- approval metadata
- durable pointers
- matching checkpoint identity
- non-empty `allowed_paths`
- non-empty `acceptance_criteria`
- non-empty `verification`
- requested changes inside the approved plan
- changed-path validation against `allowed_paths` by default when run in a git worktree

Changed-path enforcement should not be optional for execute safety.

### Future Phase Transition Scripts

Every transition script must preserve the ROADMAP/STATE/checkpoint/phase-state sync invariant and must fail before writing if it cannot update all required files consistently.

Transition scripts must be conservative:

- do not delete phase evidence
- do not carry stale execute approval across reopened or reshaped plans
- do not skip a phase-local `discuss` pass
- do not mark execute approved without explicit approval provenance
- keep adapter behavior neutral

Any script that adds, deletes, inserts, renumbers, completes, pauses, archives, or reopens a phase must account for:

- `.planning/ROADMAP.md`
- `.planning/STATE.md`
- active `*-CHECKPOINTS.md`
- `.scratch/phase-state.json`
- active plan and verification pointers

Completion and reopen semantics are intentionally under-specified today and must
not be implemented until they have explicit contracts. Future designs must
answer at least:

- what exact checkpoint status changes when a phase is completed
- whether completion requires all verification commands to have recorded
  evidence, and where that evidence is read from
- whether reopening creates a new checkpoint, reopens the last checkpoint, or
  creates a new phase-local plan
- which approvals are invalidated by reopen, rename, insert, or scope changes
- how historical summaries remain immutable while active docs become current
  again

Atomic transition semantics are mandatory for any future insert, rename, reopen,
complete, pause, or archive command:

- compute the full new planning model in memory first
- validate stable `phase_id`, `active_checkpoint_id`, and `plan_id`
  relationships before writing
- write all required canonical files or none of them
- never leave `.scratch/phase-state.json` pointing at missing or stale active
  docs
- clear execute approval when a reopened or renamed phase changes scope
- write a transition report only after canonical files are updated

Future transition work should include adversarial fixtures before implementation.
At minimum, fixtures should cover phase insertion between existing phases,
phase-folder rename with stable identity, checkpoint reopen after completion,
completion with missing verification evidence, stale live-gate plan IDs,
historical evidence containing old instructions, and conflicting path updates
that must fail before any file is changed.

## Upgrade Strategy

An installed target cannot know the newest harness behavior by itself. Upgrade needs an external source.

For existing projects, use the newer source-side harness to upgrade:

```bash
python3 /path/to/newer-harness/scripts/harness.py upgrade --target /path/to/project --dry-run
python3 /path/to/newer-harness/scripts/harness.py upgrade --target /path/to/project
```

Do not use stale target-local policy code to infer or install the new preflight behavior. The compatibility command `scripts/harness.py upgrade --target .` may remain supported only if it resolves an external source, such as the recorded `.harness/installed-manifest.json` source, before mutating files.

A target-local `upgrade_harness.py` should be a tiny bootstrapper only. It should locate a source with `--source`, `--version`, or `--repo --ref`, then delegate to the source-side upgrade implementation.

It must not duplicate upgrade policy in the installed target, because installed target scripts can be stale.

When a target-local bootstrapper selects a release, it must pass the selected version to the delegated source command so `.harness/installed-manifest.json` records the intended installed version instead of a dev fallback. Delegated upgrades should also record source provenance such as source kind, ref, and selected version.

Target-local `check_harness.py` is a self-check against the installed manifest. It does not replace source-side `python3 /path/to/newer-harness/scripts/harness.py check --target /path/to/project`, which validates the target against the current source manifest, new files, retired files, and policy changes.

Existing project-owned instruction files must be preserved. In particular, installed target `README.md` may remain stale because it is project-owned. Upgrade should not overwrite it, but should report actionable instruction drift when old README guidance conflicts with upgraded `AGENTS.md`, adapter commands, or installed scripts.

Upgrade must preserve normal legacy operation when the new status script cannot be installed because of conflicts. The target should still be able to use the legacy durable planning read order and `scripts/harness.py check`.

Required compatibility tests:

- older installed target without `scripts/show_phase_status.py` still operates through the legacy durable planning read order
- upgrade dry-run reports the new script and shared library additions
- real upgrade installs `scripts/show_phase_status.py` and `scripts/lib/**`
- preexisting target-local `scripts/show_phase_status.py` or `scripts/lib/**` conflicts safely
- stale project-owned `README.md` is preserved and produces actionable drift guidance
- upgraded target can run `python3 scripts/show_phase_status.py`
- upgraded target can still run `python3 scripts/harness.py check`
- upgraded target entrypoint smoke covers the workflow-entrypoint matrix,
  including continuous `fsd-phase`, `--auto`, and `--chain` behavior when those
  entrypoints are installed for the target
- release or target smoke tests cover the new installed target behavior

The source-side command pattern remains:

```bash
python3 /path/to/newer-harness/scripts/harness.py upgrade --target /path/to/project --dry-run
python3 /path/to/newer-harness/scripts/harness.py upgrade --target /path/to/project
```

## Adapter Neutrality

Scripts must treat adapters as consumers only.

Roo, OpenCode, Codex, and future clients must read the same `.planning/**` and `.scratch/phase-state.json`. No script may make Roo-specific or OpenCode-specific gate semantics the source of truth.

Adapter command files should call or recommend the same core scripts. They should not reimplement phase resolution differently.

## Risks

- A generated summary can accidentally become treated as canonical truth.
- Conflicting restart instructions can increase reasoning instead of reducing it.
- More script files can make `scripts/` look busy.
- Duplicated parsing can create inconsistent gate behavior.
- Phase transition scripts can corrupt planning state if they do not update ROADMAP, STATE, checkpoint, and live gate together.
- Target-local upgrade scripts can become stale if they contain real upgrade policy.

## Recommended Next Phase

Create a dedicated phase for preflight projection.

Suggested first slice:

1. Add shared read-only planning helpers under `scripts/lib/`.
2. Add `scripts/show_phase_status.py`.
3. Install the script and helper files through `harness/manifest.json`.
4. Update restart/preflight instructions atomically across every manifest-installed instruction surface identified by the repository surface audit.
5. Add and enforce the workflow-entrypoint matrix for OpenCode, Roo commands,
   Roo rules, Roo skills, `--auto`, `--chain`, and upgraded target smoke.
6. Keep existing `scripts/harness.py` commands working.
7. Add focused tests proving the output is small, deterministic, adapter-neutral, versioned, and sufficient for phase-gate preflight.
8. Add upgrade compatibility tests for older installed targets, path conflicts, stale project-owned README guidance, post-upgrade `show_phase_status.py` plus `harness.py check`, and entrypoint-level smoke after upgrade.

Do not start with every role-named script. The first useful reduction in LLM context pollution comes from `show_phase_status.py` acting as a safe projection over canonical planning state.
