# general-low-reasoning-agent-harness

A Python CLI that installs a workflow-enforcement scaffold (`harness`) into a target repo so that low-reasoning coding agents follow a `discuss → plan → execute → done` loop with approval gates.

Internal tool. Trusted developers, trusted machines, no external attacker (see [`docs/adr/0002-internal-tool-threat-model.md`](docs/adr/0002-internal-tool-threat-model.md)).

For the meaning of "harness", "skeleton", "skill-pack", "phase", "milestone", etc., see [`CONTEXT.md`](CONTEXT.md). For how to use an installed harness day-to-day, see [`MANUAL.md`](MANUAL.md).

한국어: [`README.ko.md`](README.ko.md) · [`MANUAL.ko.md`](MANUAL.ko.md).

## What you get when you install the harness

| Path in target | Owner | Purpose |
|---|---|---|
| `.harness/` | harness-generated | runtime: install-record, audit log |
| `.scratch/` | harness-generated | runtime: phase state, locks, session files |
| `.planning/ROADMAP.md`, `.planning/STATE.md` | target-owned | human-authored roadmap + current state |
| `.planning/phases/NN-*/` | target-owned | per-milestone planning artifacts |
| `AGENTS.md` | mixed (managed block + project-owned) | agent-facing rules + project-specific notes |
| `README.md` | seeded once, then target-owned | project README starter |
| `.roo/`, `.opencode/` (optional) | adapter-owned | editor/agent integration adapters |

The full file list, generated from `harness/manifest.json`, lives in [`docs/ARTIFACTS.md`](docs/ARTIFACTS.md).

## Install

### From a clone

```bash
git clone https://github.com/hjung3113/general-low-reasoning-agent-harness.git
cd general-low-reasoning-agent-harness
pip install -e .
```

This installs the `harness` console script.

### Init into a target project

```bash
harness init --target /path/to/your/project \
  --profiles generic \
  --adapters none
```

`--profiles` and `--adapters` are optional. Defaults: `generic` profile, no editor adapters. Profiles and packs work like this:

```
profile (one)  →  default skill-packs (N)
db (optional)  →  db skill-packs (M)
--packs flag   →  manual extras (K)
Final set = union of all three (additive — `--packs` does NOT replace defaults).
```

Available profiles: `generic`, `dotnet-etl`, `python-etl`, `react-web`.
Available DB packs: `mssql`, `postgresql`, `none`.

### First-run TTY confirmation

`harness init` is interactive by default. You'll see a `[y/N]` prompt that records *who* initialized the harness in `.harness/install-record.json`. This is attribution, not an authorization list — there's no approver allowlist (see [`docs/adr/0002-internal-tool-threat-model.md`](docs/adr/0002-internal-tool-threat-model.md)).

### Verify the install

```bash
cd /path/to/your/project
harness check
harness status
```

`check` validates structure + policy. `status` shows current phase, next action, any halts.

## Upgrade

When a newer version of the harness ships:

```bash
cd /path/to/your/project
harness upgrade
```

`upgrade` is a no-op when versions match. To force-apply the manifest at the same version, pass `--force`. Files marked `upgrade_action: delete` in `manifest.removed_in_version` will be removed; files with `warn` policy will print a stderr warning but be preserved. The harness never auto-deletes project-owned files (see [`docs/adr/0006-install-upgrade-adoption-flow-predicates.md`](docs/adr/0006-install-upgrade-adoption-flow-predicates.md)).

## Adoption

If you previously dropped skeleton files manually (no `.harness/install-record.json` present), use:

```bash
harness upgrade --adopt-existing
```

This treats the existing files as the starting point for an install and writes the install record. The harness refuses to auto-route ambiguous / partial states — you have to opt in.

## Agent-driven workflows

The harness exists to give low-reasoning agents a structured workflow they can follow: the agent does the work (`discuss`, `plan`, `execute`), and a supervising human approves transitions at each gate.

**The approval gate is a human checkpoint, not an authorization system.** `harness phase approve` is TTY-only by design (see [`docs/adr/0007-tty-approval-is-human-checkpoint.md`](docs/adr/0007-tty-approval-is-human-checkpoint.md)). The agent prepares work and requests approval; the human runs the interactive command from a real terminal to advance the phase. The audit log (`.harness/audit.jsonl`) records who approved each transition.

**Exit code 17 is correct behavior.** If you're an agent reading this and `phase approve` exits with code 17, you're not on a TTY — that's the intended checkpoint. Hand the session back to your supervising human; they will run the approval from an interactive shell.

**Integration with agent harnesses.** To run this with Claude Code, Codex, Cursor, or other agent harnesses, ensure the supervising human has a real shell open with the project as the current working directory to handle the approval prompt when the agent reaches a gate.

## Uninstall

```bash
harness uninstall --target /path/to/your/project --select 1,2,3,4,5
```

Removes harness-owned files. Use `--select` with comma-separated numeric codes: `1`=roo, `2`=opencode, `3`=runtime, `4`=core, `5`=docs. For example, `--select 3,4` removes runtime and core only.

## CLI quick reference

| Command | Use |
|---|---|
| `harness init` | Fresh install into a target |
| `harness upgrade` | Update harness-owned files |
| `harness check` | Validate structure + policy |
| `harness status` | Phase + next action |
| `harness next` | Recommended next action |
| `harness uninstall` | Remove harness scopes |
| `harness doctor` | Read-only drift diagnostic |

Full CLI reference: [`docs/CLI.md`](docs/CLI.md).

## Troubleshooting

If `harness phase approve` exits with code 17, you're not on a real terminal — run from an interactive shell, not CI (see [`MANUAL.md`](MANUAL.md)).

`harness check` may warn about a stale skeleton phase (`00-planning-hydration`) on a brand-new install. That's expected: the skeleton seeds template planning files that you replace once you declare your first real milestone. Add a bullet to `.planning/ROADMAP.md` and stamp it in `.planning/STATE.md`, then `harness check` quiets down.

## Project layout

```
.
├── harness_cli.py          # console-script entry
├── pyproject.toml          # package metadata
├── scripts/                # all Python logic
│   ├── harness.py          # CLI dispatcher
│   └── lib/                # 50 modules
├── harness/
│   ├── skeleton/clean/     # template files (AGENTS.md, README.md)
│   ├── profiles/           # generic, dotnet-etl, python-etl, react-web
│   ├── skill-packs/        # 14 packs: 4 tech-* + 10 workflow-*
│   └── manifest.json       # source of truth for installed/removed files
├── CONTEXT.md              # glossary
├── docs/
│   ├── ARTIFACTS.md        # generated from manifest
│   ├── ARCHITECTURE.md
│   ├── CLI.md
│   ├── WORKFLOW.md
│   ├── INSTALL-MODEL.md
│   └── adr/                # 6 ADRs (standing decisions)
└── tests/                  # full test suite
```

## Contributing

Workflow milestones are tracked as GitHub milestones + issues on this repo (`hjung3113/general-low-reasoning-agent-harness`). See [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md) and [`docs/agents/triage-labels.md`](docs/agents/triage-labels.md). Per-milestone plans live under [`.planning/phases/NN-*/`](.planning/phases/).

Decision history: [`docs/adr/`](docs/adr/).
