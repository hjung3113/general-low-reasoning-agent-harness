# Script-Oriented Preflight Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first script-oriented workflow slice: a shared read-only planning parser and JSON-only `show_phase_status.py` projection that reduces restart context without replacing `.planning/**` or `.scratch/phase-state.json`.

**Architecture:** Introduce `scripts/lib/planning_status.py` as the single parser/projection layer for planning state, then make `scripts/show_phase_status.py`, `scripts/harness.py`, and `scripts/project_dashboard.py` consume that layer. Install only the status script and helper library in this slice, while updating manifest-installed instructions atomically so every adapter starts with the same preflight rule and falls back to the legacy durable planning read order.

**Tech Stack:** Python standard library, `unittest`, existing manifest-driven harness installer, Markdown instruction files, JSON stdout contract `phase-status.v1`.

---

## File Map

- Create: `scripts/lib/__init__.py` - marks shared script helpers as an importable package.
- Create: `scripts/lib/planning_status.py` - read-only parser, projection model, structured warnings, and JSON contract builder.
- Create: `scripts/show_phase_status.py` - thin CLI wrapper that prints one JSON object to stdout.
- Modify: `scripts/harness.py` - import the shared planning parser for check/doctor drift logic and include new installed files in manifest validation.
- Modify: `scripts/project_dashboard.py` - replace independent planning parsing with the shared parser while keeping dashboard presentation logic local.
- Modify: `harness/manifest.json` - install `scripts/show_phase_status.py` and `scripts/lib/**` as harness-owned files.
- Modify: active instruction surfaces listed in `docs/script-oriented-harness-workflow.md` - use the same preflight/fallback wording.
- Modify: `.roo/skills/README.md`, `.roo/skills/*/SKILL.md`, `.agents/skills/**` installed outputs, and `harness/profiles/*/PROFILE.md` where they mention restart order, phase-state, active phase docs, allowed paths, or verification.
- Modify: workflow-entrypoint matrix data used by tests, covering OpenCode commands, Roo commands, always-on Roo rules, Roo skills, `--auto`, `--chain`, and upgraded target smoke.
- Test: `scripts/test_show_phase_status.py` - contract and parser tests for the new projection.
- Test: `scripts/test_harness.py` - manifest, workflow-entrypoint matrix, contradictory instruction detection, upgrade compatibility, conflict, legacy fallback, and check/doctor integration tests.
- Test: `scripts/test_project_dashboard.py` - proves dashboard uses shared semantics and remains self-contained HTML.
- Test fixtures: add adversarial planning fixtures under `scripts/fixtures/planning-status/` only if inline test setup becomes too large.

## Contract Constants

Use these names consistently:

```python
CONTRACT_VERSION = "phase-status.v1"
LEGACY_READ_ORDER = [
    ".planning/STATE.md",
    ".planning/ROADMAP.md",
    ".planning/codebase/**",
    "<active checkpoint file>",
    "<active phase docs>",
    ".scratch/phase-state.json",
]
```

Warning objects must use this shape:

```python
{
    "code": "state_checkpoint_drift",
    "severity": "blocking",
    "message": "STATE active checkpoint differs from phase-state current_checkpoint.",
    "paths": [".planning/STATE.md", ".scratch/phase-state.json"],
    "required_read": True,
}
```

---

### Task 1: Shared Read-Only Planning Parser

**Files:**
- Create: `scripts/lib/__init__.py`
- Create: `scripts/lib/planning_status.py`
- Test: `scripts/test_show_phase_status.py`

- [ ] **Step 1: Write failing parser tests**

Add `scripts/test_show_phase_status.py` with these tests:

- `test_projection_reads_execute_gate_identity_and_paths`
- `test_projection_reports_blocking_warning_for_checkpoint_drift`
- `test_projection_distinguishes_active_docs_from_historical_evidence`

Fixture setup should create `.planning/STATE.md`, `.planning/ROADMAP.md`, `.planning/codebase/ARCHITECTURE.md`, `.planning/phases/01-example/01-CHECKPOINTS.md`, `.planning/phases/01-example/01-01-PLAN.md`, `.planning/phases/01-example/01-VERIFICATION.md`, and `.scratch/phase-state.json`.

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
python3 -m unittest scripts/test_show_phase_status.py
```

Expected: FAIL because `scripts.lib.planning_status` does not exist.

- [ ] **Step 3: Implement dataclasses and parser**

Implement `scripts/lib/planning_status.py` with:

```python
@dataclass(frozen=True)
class PlanningWarning:
    code: str
    severity: str
    message: str
    paths: list[str]
    required_read: bool

@dataclass(frozen=True)
class PlanningProjection:
    contract_version: str
    phase: str
    phase_id: str
    phase_title: str
    approved: bool
    plan_id: str | None
    automation_mode: str
    projected_execute_gate_valid: bool
    projected_execute_gate_reason: str
    active_phase_folder: str
    active_checkpoint_id: str
    active_checkpoint_title: str
    active_checkpoint_status: str
    state_path: str
    roadmap_path: str
    checkpoint_path: str
    plan_path: str
    verification_path: str
    summary_path: str
    allowed_paths: list[str]
    blocked_paths: list[str]
    acceptance_criteria: list[str]
    verification: list[str]
    warnings: list[PlanningWarning]
    required_reads: list[str]
    suggested_next_read: str

```

Expose `load_projection(root: Path) -> PlanningProjection`,
`projection_to_dict(projection: PlanningProjection) -> dict[str, object]`, and
`projection_to_json(projection: PlanningProjection) -> str`.

Parser rules:

- read `.scratch/phase-state.json` as the live gate
- read `.planning/STATE.md` and `.planning/ROADMAP.md` as durable active state
- resolve explicit `state_path`, `checkpoint_path`, and `plan_path` from phase-state first
- derive `phase_id` from the active phase folder prefix such as `01`
- derive `active_checkpoint_id` from `current_checkpoint` or STATE checkpoint text
- emit `blocking` warnings for missing active files, checkpoint drift, missing approval metadata in execute, empty allowed paths, empty acceptance criteria, or empty verification
- include historical `.planning/phases/**` files in no required reads unless they are active pointers

- [ ] **Step 4: Run parser tests to green**

Run:

```bash
python3 -m unittest scripts/test_show_phase_status.py
```

Expected: PASS.

### Task 2: JSON-Only `show_phase_status.py`

**Files:**
- Create: `scripts/show_phase_status.py`
- Test: `scripts/test_show_phase_status.py`

- [ ] **Step 1: Add failing CLI contract tests**

Add these tests:

- `test_cli_emits_single_json_object_on_stdout`
- `test_cli_has_no_markdown_or_prose_prefix`
- `test_cli_exits_nonzero_for_malformed_phase_state`

Use `subprocess.run([sys.executable, str(script), "--root", str(root)], capture_output=True, text=True)`.

- [ ] **Step 2: Run focused CLI tests**

Run:

```bash
python3 -m unittest scripts.test_show_phase_status.ShowPhaseStatusCliTests
```

Expected: FAIL because the script does not exist.

- [ ] **Step 3: Implement thin CLI**

`scripts/show_phase_status.py` should:

- accept `--root`, defaulting to current working directory
- call `load_projection(root)`
- print `projection_to_json(projection)` to stdout
- exit `0` when projection succeeds, even with warnings
- print only stderr diagnostics and exit nonzero when required files cannot be parsed as expected
- avoid any text output mode in v1

- [ ] **Step 4: Verify CLI tests**

Run:

```bash
python3 -m unittest scripts.test_show_phase_status.ShowPhaseStatusCliTests
```

Expected: PASS.

### Task 3: Mandatory Shared Parsing for Existing Scripts

**Files:**
- Modify: `scripts/harness.py`
- Modify: `scripts/project_dashboard.py`
- Test: `scripts/test_harness.py`
- Test: `scripts/test_project_dashboard.py`

- [ ] **Step 1: Write failing integration tests**

Add focused tests:

- `test_harness_doctor_uses_shared_checkpoint_drift_warning`
- `test_dashboard_uses_shared_active_checkpoint_identity`

The expected warning code should be `state_checkpoint_drift`, and the dashboard active checkpoint should match `PlanningProjection.active_checkpoint_id`.

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
python3 -m unittest scripts.test_harness.HarnessToolTests.test_harness_doctor_uses_shared_checkpoint_drift_warning
python3 -m unittest scripts.test_project_dashboard.ProjectDashboardTests.test_dashboard_uses_shared_active_checkpoint_identity
```

Expected: FAIL until both scripts import shared parsing.

- [ ] **Step 3: Refactor consumers**

Update `scripts/harness.py` and `scripts/project_dashboard.py` to import from `scripts/lib/planning_status.py`. Keep command names and output formats stable. Do not move dashboard HTML rendering into the shared library.

- [ ] **Step 4: Verify focused integrations**

Run the two focused unittest commands again.

Expected: PASS.

### Task 4: Manifest Installation and Upgrade Compatibility

**Files:**
- Modify: `harness/manifest.json`
- Modify: `scripts/harness.py` if manifest validation needs package-file handling
- Test: `scripts/test_harness.py`

- [ ] **Step 1: Add failing install and upgrade tests**

Add tests named:

- `test_init_installs_show_phase_status_and_shared_lib`
- `test_upgrade_dry_run_reports_new_status_script_and_lib`
- `test_upgrade_conflicts_on_preexisting_target_local_status_script`
- `test_older_target_without_status_script_still_checks`
- `test_stale_project_owned_readme_is_preserved_and_reports_instruction_drift`

- [ ] **Step 2: Run focused tests to verify red**

Run:

```bash
python3 -m unittest scripts.test_harness.HarnessToolTests.test_init_installs_show_phase_status_and_shared_lib
python3 -m unittest scripts.test_harness.HarnessToolTests.test_upgrade_dry_run_reports_new_status_script_and_lib
python3 -m unittest scripts.test_harness.HarnessToolTests.test_upgrade_conflicts_on_preexisting_target_local_status_script
```

Expected: FAIL until manifest entries and conflict behavior are implemented.

- [ ] **Step 3: Add manifest entries**

Add harness-owned entries for:

```json
{
  "path": "scripts/show_phase_status.py",
  "source": "scripts/show_phase_status.py",
  "policy": "harness-owned"
}
```

and each concrete helper file under `scripts/lib/`.

- [ ] **Step 4: Preserve upgrade safety**

Ensure upgrade dry-run reports new files before mutation, real upgrade installs them, and preexisting target-local `scripts/show_phase_status.py` or `scripts/lib/planning_status.py` conflicts unless the existing file matches the manifest source.

- [ ] **Step 5: Verify manifest tests**

Run:

```bash
python3 -m unittest scripts/test_harness.py
```

Expected: PASS.

### Task 5: Atomic Instruction Updates

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/protocol-spec.md`
- Modify: `docs/phase-gate-harness.md`
- Modify: `docs/agents/domain.md` if it contains active phase context instructions
- Modify: `docs/agents/issue-tracker.md` if it contains active phase context instructions
- Modify: `harness/skeleton/clean/AGENTS.md`
- Modify: `harness/skeleton/clean/README.md`
- Modify: `harness/skeleton/clean/.planning/HANDOFF-PROTOCOL.md`
- Modify: `harness/skeleton/clean/.planning/STATE.md`
- Modify: current operating skeleton `.planning/**` files that mention restart order, active phase context, verification, source of truth, or phase-state behavior
- Modify: `.opencode/commands/discuss.md`, `plan.md`, `execute.md`, `done.md`
- Modify: `.roo/README.md`, `.roo/commands/README.md`, relevant `.roo/commands/*.md`
- Modify: `.roo/rules/**/*.md` and `.roo/rules-*/rules.md` when they mention planning, gate, or verification behavior
- Modify: `.roo/skills/README.md` and `.roo/skills/*/SKILL.md` when they read or write planning state
- Modify: `harness/profiles/*/PROFILE.md` when they mention restart order, phase gate, allowed paths, or verification
- Test: `scripts/test_harness.py`

- [ ] **Step 1: Add failing instruction-surface test**

Add a test that scans manifest-installed active instruction files for the required wording:

```text
Start with `python3 scripts/show_phase_status.py` when available. If it reports warnings, treat named files as minimum required reads before trusting the projection. If it is missing, fails, emits malformed output, or reports an unsupported contract version, use the legacy durable planning read order.
```

The test should exclude historical evidence under `.planning/phases/**` and `docs/superpowers/**`.

- [ ] **Step 2: Add failing workflow-entrypoint matrix test**

Add a matrix-driven test that names every workflow entrypoint that must share
the preflight/fallback rule. The matrix must include these rows:

```python
WORKFLOW_ENTRYPOINT_MATRIX = [
    ("opencode-discuss", ".opencode/commands/discuss.md", "projection before broad hydration"),
    ("opencode-plan", ".opencode/commands/plan.md", "projection locates active docs before canonical plan writes"),
    ("opencode-execute", ".opencode/commands/execute.md", "projection first, canonical execute gate before edits"),
    ("opencode-done", ".opencode/commands/done.md", "projection locates verification evidence before completion"),
    ("roo-phase-discuss", ".roo/commands/phase-discuss.md", "fresh phase discuss pass"),
    ("roo-phase-plan", ".roo/commands/phase-plan.md", "canonical plan and approval request"),
    ("roo-phase-execute", ".roo/commands/phase-execute.md", "canonical execute gate"),
    ("roo-fsd-phase", ".roo/commands/fsd-phase.md", "continuous discuss-to-done gate preservation"),
    ("roo-simple", ".roo/commands/simple.md", "lightweight path cannot bypass gate"),
    ("roo-review", ".roo/commands/review.md", "projected active scope and verification"),
    ("roo-doctor", ".roo/commands/doctor.md", "reports projection, fallback, and instruction drift"),
    ("roo-feature", ".roo/commands/feature.md", "feature workflow preserves phase-local gates"),
    ("roo-bugfix", ".roo/commands/bugfix.md", "diagnosis and execute approval boundaries"),
    ("roo-adr", ".roo/commands/adr.md", "architecture evidence uses active context"),
    ("roo-issues", ".roo/commands/issues.md", "issue artifacts use active roadmap and phase context"),
    ("roo-ops", ".roo/commands/ops.md", "ops work uses active scope and verification"),
    ("roo-always-on-global", ".roo/rules/global.md", "always-on shared preflight rule"),
    ("roo-always-on-phase-gate", ".roo/rules/phase-gate.md", "always-on canonical gate"),
    ("roo-skills-readme", ".roo/skills/README.md", "skills start with projection then canonical writes"),
    ("roo-skill-phase-gate", ".roo/skills/workflow-phase-gate/SKILL.md", "skill gate agrees with commands"),
    ("roo-auto", ".roo/commands/README.md", "--auto cannot skip warnings, fallback, allowed paths, or verification"),
    ("roo-chain", ".roo/commands/README.md", "--chain reruns preflight at each boundary and does not reuse stale approval"),
]
```

The test should assert each path exists or is intentionally optional with an
explicit skip reason, contains the exact shared preflight/fallback wording, and
contains its row-specific phrase or equivalent required behavior. It should also
scan all matrix files for contradictory phrases such as "read all planning docs
before running the status script", "ignore warnings", "projection authorizes
edits", or "approval persists across reopened phases".

- [ ] **Step 3: Run instruction and matrix tests to verify red**

Run:

```bash
python3 -m unittest scripts.test_harness.HarnessToolTests.test_instruction_surfaces_share_show_phase_status_preflight
python3 -m unittest scripts.test_harness.HarnessToolTests.test_workflow_entrypoint_matrix_shares_show_phase_status_preflight
python3 -m unittest scripts.test_harness.HarnessToolTests.test_workflow_entrypoint_matrix_rejects_contradictory_preflight_instructions
```

Expected: FAIL until instruction files are updated.

- [ ] **Step 4: Update active instruction surfaces**

Apply the exact preflight/fallback wording to all active surfaces. Keep historical evidence unchanged unless it is installed into new targets as current operating guidance.

- [ ] **Step 5: Verify instruction consistency and entrypoint coverage**

Run:

```bash
python3 -m unittest scripts.test_harness.HarnessToolTests.test_instruction_surfaces_share_show_phase_status_preflight
python3 -m unittest scripts.test_harness.HarnessToolTests.test_workflow_entrypoint_matrix_shares_show_phase_status_preflight
python3 -m unittest scripts.test_harness.HarnessToolTests.test_workflow_entrypoint_matrix_rejects_contradictory_preflight_instructions
```

Expected: PASS.

### Task 6: Adversarial Fixtures for Deferred Transitions

**Files:**
- Create: `scripts/fixtures/planning-status/phase-insert-drift/`
- Create: `scripts/fixtures/planning-status/phase-rename-stable-id/`
- Create: `scripts/fixtures/planning-status/reopen-clears-approval/`
- Create: `scripts/fixtures/planning-status/chain-new-phase-clears-approval/`
- Create: `scripts/fixtures/planning-status/chain-reshaped-phase-clears-approval/`
- Create: `scripts/fixtures/planning-status/complete-missing-verification/`
- Test: `scripts/test_show_phase_status.py`

- [ ] **Step 1: Add fixture tests**

Add tests proving the read-only projection reports structured blocking warnings for the deferred transition cases. These tests must not introduce transition scripts.

The tests must include continuous-flow cases for `fsd-phase` and `--chain`.
They must prove that a new, reopened, renamed, inserted, or reshaped phase
cannot carry stale approval from the previous phase shape. Approval must match
the current `phase_id`, `active_checkpoint_id`, `plan_id`, and approved scope.

- [ ] **Step 2: Run fixture tests to verify red**

Run:

```bash
python3 -m unittest scripts.test_show_phase_status.ShowPhaseStatusAdversarialFixtureTests
```

Expected: FAIL until fixtures and parser warnings exist.

- [ ] **Step 3: Add minimal fixture repositories**

Each fixture should include only the planning files needed to trigger the warning. Keep fixtures small and documented with a `README.md` in each fixture directory.

- [ ] **Step 4: Verify fixture tests**

Run:

```bash
python3 -m unittest scripts.test_show_phase_status.ShowPhaseStatusAdversarialFixtureTests
```

Expected: PASS.

### Task 7: Full Verification and Target Smoke

**Files:**
- No new implementation files unless earlier tasks revealed missing active surfaces.

- [ ] **Step 1: Run focused test suite**

Run:

```bash
python3 -m unittest scripts/test_show_phase_status.py
python3 -m unittest scripts/test_project_dashboard.py
python3 -m unittest scripts/test_harness.py
```

Expected: all commands exit `0`.

- [ ] **Step 2: Run source checks**

Run:

```bash
python3 scripts/show_phase_status.py
python3 scripts/harness.py check
python3 scripts/harness.py check --worktree
python3 scripts/project_dashboard.py --root . --output .scratch/reports/project-dashboard.html
```

Expected: status emits parseable JSON with `contract_version` set to `phase-status.v1`; harness checks exit `0`; dashboard writes HTML.

- [ ] **Step 3: Run release smoke**

Run:

```bash
python3 scripts/release_smoke_test.py
```

Expected: exit `0`, including target install/check coverage for the new status script.

- [ ] **Step 4: Run upgraded target entrypoint smoke**

Add or run a target smoke check that validates the installed workflow-entrypoint
matrix after upgrade. The smoke must cover OpenCode discuss/plan/execute/done;
Roo phase-discuss/phase-plan/phase-execute/fsd-phase/simple/review/doctor/
feature/bugfix/adr/issues/ops; always-on Roo rules; Roo skills; `--auto`;
`--chain`; and the target's post-upgrade `show_phase_status.py` plus
`harness.py check` commands.

The smoke must fail when:

- any entrypoint gives contradictory preflight or fallback instructions
- `--auto` skips projection warnings, fallback, allowed paths, or verification
- `fsd-phase` or `--chain` carries execute approval into a new, reopened,
  renamed, inserted, or reshaped phase

- [ ] **Step 5: Run `../New project` application test**

Run the source-side upgrade pattern:

```bash
python3 scripts/harness.py upgrade --target "../New project" --dry-run
python3 scripts/harness.py upgrade --target "../New project"
python3 "../New project/scripts/show_phase_status.py" --root "../New project"
python3 "../New project/scripts/harness.py" check --target "../New project"
```

Expected: dry-run reports intended additions; real upgrade installs status script and shared helpers; status emits JSON only; target check exits `0`. If `../New project` has explicit adapter/profile/pack scope, rerun both upgrade commands with that exact scope instead of relying on defaults.

- [ ] **Step 6: Audit changed files**

Run:

```bash
git status --short
git diff --stat
```

Expected: changes are limited to the planned implementation files and active instruction surfaces. No application code outside harness scripts, tests, docs, manifest, adapters, profiles, and installed skill outputs is touched.
