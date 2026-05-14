# Low-Reasoning Agent Harness Project

This repository has been initialized with the generalized low-reasoning agent harness.

## Start Here

1. Read `AGENTS.md`.
2. Read `.planning/STATE.md`.
3. Read `.planning/ROADMAP.md`.
4. Read `.planning/codebase/**`.
5. Read the active phase checkpoint.
6. Read active phase docs when present.
7. Read `.scratch/phase-state.json`.

> Fresh target first action: run the installed client's discuss workflow for `planning-hydration --pass 0` to inventory the repository, update only the pass-0 planning files, record open questions, and stop for review before any implementation.

`AGENTS.md` includes the default Karpathy-Inspired Coding Guidelines from `multica-ai/andrej-karpathy-skills`.

## Harness Commands

```bash
python3 scripts/harness.py check
python3 scripts/harness.py doctor
```

To generate a local HTML status dashboard:

```bash
python3 scripts/project_dashboard.py
```

The dashboard reads `.planning/**`, `.scratch/**`, `docs/**`, `README.md`, and `AGENTS.md`, then writes `.scratch/reports/project-dashboard.html`. The generated report is local output; regenerate it whenever planning documents change.

`check` is the strict validation path. `doctor` is read-only diagnostics for planning/Roo/DB context drift; it reports severity, cause, impact, fix, evidence, and diff-before-mutation guidance without changing files.

The harness-owned files define client adapters, rules, commands, profiles, skill packs, and reusable workflows. Project-owned planning files describe this repository and should be hydrated from the actual project before implementation work starts.

Workflow skills are installed as composable plugins under `.agents/skills/`. The default `workflow-core` pack is stack-neutral: it helps agents research repository evidence, compose the right skills for the phase, define verification, review risk, reason about data movement, and handle integration boundaries. Profiles describe confirmed project facts; skills are selected from installed plugins to match the current request and constraints. Do not mention, run, scaffold, or recommend commands from inactive profiles or unselected skills.

Before ROADMAP phases, phase folders, ADR decisions, or phase success criteria are created, align with the user first. Ask one question at a time, include the recommended answer and reason, inspect the repository instead of asking when the repository can answer, and record an alignment summary with confirmed facts, inferred facts, user preferences, recommended defaults, open questions, and blocked decisions.

Every phase starts with its own `discuss` pass before `plan` or `execute`. Review phase and ADR drafts with two adversarial expert roles and three lenses each, including whether the questions are concrete enough for low-reasoning models. Use `--auto` only for recommended low-risk defaults with auditable `auto_selected` entries. Use `--chain` only for one reviewed phase after `.scratch/phase-state.json` is verified or written with `phase=execute`, matching `plan_id`, `approved=true`, `automation_mode=chain`, durable pointers, allowed paths, and verification.

To upgrade later, run the newer harness source against this project:

```bash
python3 /path/to/newer-harness/scripts/harness.py upgrade --target .
```

## Workflow Prompts

Use explicit prompts when adopting the harness in an existing project. State the analysis scope, editable files, expected planning output, and stop conditions.

### Full Existing-Project Hydration

```text
I want to apply this Roo/Codex harness to this existing repository.
Do not implement yet. Run the planning hydration workflow first.
Inventory README, build/test configuration, src/tests, docs, ADRs, existing .planning, and .scratch state.
Hydrate .planning/codebase/** and active phase documents from the real repository.
Ask only for product intent or phase-boundary decisions the repo cannot answer.
Classify stale/template/previous-project planning files as keep/archive/delete candidate/needs-human, but do not delete them.
```

### Limited-Scope Hydration

```text
Apply the harness first to <scope>, not the entire repository.
Limit analysis to <example: ingestion pipeline, billing module, docs/adr only, src/Foo plus tests/FooTests>.
Read files outside that scope only to understand ownership, dependencies, or risk.
Record confirmed scope and unknown scope separately in .planning/codebase/**.
Propose the first phase as the smallest usable slice inside that scope.
```

### Existing Planning May Be Stale

```text
This repository already has .planning/ and .scratch/phase-state.json, but I do not know whether they are current.
Do not implement. Reconcile planning only.
Classify the planning state as absent/template-only/stale/partial/usable.
Find statements that conflict with repository evidence.
Separate safe documentation repairs from decisions that need human confirmation.
Do not change phase-state to execute until I explicitly approve it.
```

### Design Document Already Exists

```text
Use <document path> as the input for planning.
Split it into fixed requirements, decisions, open questions, and implementation slice candidates.
If .planning/codebase/** is missing or stale, return to repository hydration first.
Do not implement. Produce a phase-local discuss summary and a first plan candidate for /issues or /adr.
Attach owner workflow, allowed_paths candidates, and verification candidates to each slice.
```

### Skill Plugin Composition

```text
This project request appears to involve <data workflow / integration boundary / verification design / risk review / other concern>.
Do not assume a tech stack. Use repository-evidence-research first.
Then use skill-plugin-composition to select the smallest set of installed workflow skills for this phase.
Record active skills, evidence paths, rejected skills, and blocked decisions in the active phase context.
```

### Small Docs-Only Harness Change

```text
This is a small docs-only harness change, not an application behavior change.
Use the simple workflow. Read AGENTS.md, .planning/STATE.md, active checkpoint, and .scratch/phase-state.json.
Edit only allowed documentation or harness paths.
After the change, verify that README, AGENTS, planning docs, and workflow names still agree.
```

### Read-Only Harness Review

```text
This request is read-only review.
Do not modify files.
Check whether AGENTS.md, README.md, .planning/STATE.md, .planning/ROADMAP.md,
.planning/codebase/**, active phase docs, and .scratch/phase-state.json point to the same current state.
Report findings by severity with file and line evidence.
```
