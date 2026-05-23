# general-low-reasoning-agent-harness

Glossary for this repo. A Python CLI that installs a workflow-enforcement scaffold into other repos so that low-reasoning coding agents follow a `discuss → plan → execute → done` loop.

## Language

**Harness installer**:
This repo's Python CLI (`harness` entrypoint). Installs, upgrades, and uninstalls a harness in a target repo.
_Avoid_: harness (ambiguous), tool, framework.

**Harness**:
The installed result in a target repo — `.harness/` runtime, dropped skeleton files, selected skill-packs, and the workflow files under `.planning/` and `.scratch/`. What the installer produces.
_Avoid_: install, deployment.

**Target repo**:
A repo that has (or will have) a harness installed. The audience for workflow enforcement.
_Avoid_: host repo, consumer, downstream, client repo.

**Skeleton**:
Static template files that the installer drops into the target repo (e.g. `AGENTS.md`, `README.md`). Lives under `harness/skeleton/clean/`.
_Avoid_: template, scaffold, boilerplate.

**Skill-pack**:
A reusable bundle of agent instructions selected per profile. Two kinds: `workflow-*` (workflow rules) and `tech-*` (stack-specific guidance). Listed in `harness/skill-packs/` and `harness/manifest.json`.
_Avoid_: pack, plugin, module, extension.

**Profile**:
A named bundle of default skill-packs for a target type (`generic`, `dotnet-etl`, `python-etl`, `react-web`). Selected at install time.
_Avoid_: preset, template.

**Manifest**:
`harness/manifest.json`. Authoritative list of files+packs the installer can place, plus `removed_in_version` records for clean upgrades.
_Avoid_: index, registry, catalog.

**Phase**:
A value of the workflow state machine in a target: one of `discuss`, `plan`, `execute`, `done`. Stored in `.scratch/phase-state.json`. The thing the harness enforces ordering on.
_Avoid_: stage, step, state (when referring to the state machine value).

**Milestone**:
A chunk of work on the harness installer itself (Milestone 1: security strip; Milestone 2: minimal workflow strip; …). Used in installer commit history and roadmap, not in target repos.
_Avoid_: phase (reserved for workflow), epic, release, sprint.

**Planning**:
Target-owned roadmap and state docs at `.planning/ROADMAP.md` + `.planning/STATE.md` + `.planning/phases/`. Human-authored. Parsed by `planning_grammar.py`.
_Avoid_: docs, plan, design.

**Scratch**:
Target-local runtime/ephemeral state at `.scratch/` — `phase-state.json`, locks, journals, session files. Machine-managed.
_Avoid_: state dir, tmp, cache.

**Approval**:
TTY `[y/N]` gate required to move forward on the phase state machine (`plan → execute`, `execute → done`). Backward transitions require `--reset-approval` instead.
_Avoid_: confirmation, sign-off.

**Workflow enforcement**:
What this project exists to do — make a low-reasoning agent follow `discuss → plan → execute → done` order with approvals. Mechanism: phase state machine + planning grammar + approval gates + skeleton `AGENTS.md`.
_Avoid_: governance, gating.

## Example dialogue

> **Dev:** Can we land this without going through `discuss`?
> **Harness:** No — first forward edge needs a phase entry. The harness enforces `discuss → plan → execute → done`.
> **Dev:** What if I'm just bumping a dep in a target repo?
> **Harness:** That's a workflow event in the target. It still needs a phase. The *installer* milestones (Milestone 1, 2 …) are separate — those track work on the harness itself, not work in any target.
> **Dev:** And the skill-packs vs the skeleton — what's the difference?
> **Harness:** Skeleton is the static files (AGENTS.md, README.md) dropped into the target. Skill-packs are the composable instruction bundles selected by profile. Manifest lists both.

## Scope / Non-goals

The harness enforces about 70% of the agent workflow on purpose. The remaining 30% is human judgment and is **not** enforced.

**Enforced (70%):**
- Phase ordering: `discuss → plan → execute → done` cannot be skipped on forward edges.
- Presence of planning artifacts: `ROADMAP.md` and `STATE.md` must exist and parse.
- Approval gates at forward transitions (`plan → execute`, `execute → done`).
- Skeleton presence in target (`AGENTS.md`, selected skill-packs per profile).

**Not enforced (30%):**
- Correctness of the plan — the harness will not judge whether the chosen approach is right.
- Quality of code, docs, or commit messages produced during `execute`.
- Whether tasks listed under a phase are actually the right tasks.
- Strategic direction — the harness does not opine on what to build next.

Threat model is documented in [ADR-0002](docs/adr/0002-internal-tool-threat-model.md): internal tool, no external attacker. Anything assuming an external attacker is out of scope.

## Flagged ambiguities

- **"State"** is used informally for both the workflow state machine value (`phase`) and on-disk install state (`scripts/lib/state.py`). Prefer `phase` for the former and `install state` for the latter.
- **"Pack"** alone is ambiguous between skill-pack and any other bundle. Always say `skill-pack`.
