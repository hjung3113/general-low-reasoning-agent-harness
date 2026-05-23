# Harness Manual

How to use an installed harness in a target repo day-to-day.

Audience: developer (or supervising agent) driving the `discuss → plan → execute → done` workflow on a target project that has the harness installed.

For installer setup see [`README.md`](README.md). For term definitions see [`CONTEXT.md`](CONTEXT.md). For the full CLI surface see [`docs/CLI.md`](docs/CLI.md).

## The workflow

Every unit of project work goes through 4 phases in order:

```
discuss → plan → execute → done
```

The harness enforces ordering. Forward edges (`discuss → plan`, `plan → execute`, `execute → done`) require an explicit approval. Backward edges (e.g. `execute → plan`) require `--reset-approval`. There is no skip.

| Phase | What you do | Exits to |
|---|---|---|
| `discuss` | Frame the problem in `.planning/phases/NN-*/NN-CONTEXT.md`. No code changes. | `plan` |
| `plan` | Write `NN-NN-PLAN.md` with concrete steps + acceptance criteria. | `execute` (requires approval) |
| `execute` | Make code changes. Stay inside `draft_allowed_paths` from the plan. | `done` (requires approval) |
| `done` | Write `NN-VERIFICATION.md` and `NN-NN-SUMMARY.md`. No further changes. | next milestone or `discuss` |

## Daily commands

### See where you are

```bash
harness status        # phase + checkpoint + next recommended action
harness next          # just the next action
```

### Move forward

```bash
harness phase set discuss      # enter discuss (no approval needed)
harness phase set plan         # discuss → plan (no approval needed)
harness phase approve          # TTY [y/N] gate
harness phase set execute      # plan → execute (approval required)
harness phase approve          # again, for execute → done
harness phase set done
```

`phase approve` is a TTY-only prompt — it refuses if stdin/stdout isn't a tty (exit 17). Identity is resolved from `git config user.email` by default; override with `--by user@example.com`. Self-approval is normal (this is not two-person control — see [`docs/adr/0002-internal-tool-threat-model.md`](docs/adr/0002-internal-tool-threat-model.md)).

### Move backward (rare)

```bash
harness phase reopen --to plan --reset-approval
```

Backward transitions invalidate the prior approval. Use when the plan needs revision after execute started.

### Helpers

```bash
harness phase next-pending     # slug of next unfinished phase
harness session unlock         # drop a stale session lock (after a crash)
harness state show             # print the parsed phase-state.json
harness state repair           # rebuild the managed AGENTS.md block
harness run                    # execute the next safe step + halt at human gate
```

## Planning docs you maintain

Each milestone lives under `.planning/phases/NN-<slug>/`. The harness reads these to drive its checks. You write them.

```
.planning/
├── ROADMAP.md                  # high-level milestone list (Milestone N: Title)
├── STATE.md                    # current milestone + checkpoint pointers
└── phases/
    └── 03-some-milestone/
        ├── 03-CONTEXT.md       # discuss phase
        ├── 03-CHECKPOINTS.md   # plan phase
        ├── 03-01-PLAN.md       # plan phase
        ├── 03-VERIFICATION.md  # done phase
        ├── 03-REVIEW.md        # optional
        └── 03-01-SUMMARY.md    # done phase
```

Naming rules (enforced by `planning_grammar.py`):
- Bullets in `ROADMAP.md`: `- [ ] **Milestone N: Title** - summary` (legacy `**Phase N:**` also accepted).
- State line in `STATE.md`: `- **Milestone**: N - Title`.
- Phase folder: `NN-slug` where `NN` is zero-padded.

The grammar will reject malformed lines — run `harness check` after edits.

## Approval — how identity is recorded

When you run `harness phase approve`:

1. Resolve identity:
   - `--by user@example.com` if passed
   - else `git config user.email`
2. TTY `[y/N]` prompt. Refusing writes nothing.
3. On `y`: state is stamped with `approved_by` + `approved_at`; one audit row is appended to `.harness/audit.jsonl`.

Environment variables (`HARNESS_BY_TRUST` etc.) do **not** influence identity. There's no override-identity escape hatch.

## Audit log

`.harness/audit.jsonl` is plain JSON-lines. One row per state-mutating verb. No hash chain, no canonicalization — diagnostic, not forensic (see [`docs/adr/0005-audit-log-is-plain-jsonl.md`](docs/adr/0005-audit-log-is-plain-jsonl.md)).

Tail it like any log:

```bash
tail -f .harness/audit.jsonl | python3 -m json.tool
```

Each row has: `at` (ISO timestamp), `verb`, `phase`, `actor`, `target_path`, `outcome`, `txn_id`, `before_sha256`, `after_sha256`.

## When things go wrong

| Symptom | Fix |
|---|---|
| `phase approve` exits 17 "not a TTY" | Run from an interactive shell, not CI |
| `state file present but empty` | `git checkout -- .scratch/phase-state.json`, then retry |
| `session locked: process N alive` | Wait, or `harness session unlock` if you're sure it's dead |
| `Refusing to write malformed managed-append destination` | The error now includes a unified diff of current vs proposed — apply it manually to `AGENTS.md` and retry |
| `unknown pack: workflow-XYZ` | Pack was removed in a previous milestone; pick a current one (run `harness check` for the kept set) |
| `harness check` reports drift | Run `harness state repair` (rebuilds managed block) or `harness doctor` (read-only diagnostic) |

Exit codes are documented in [`docs/error-code-map.md`](docs/error-code-map.md).

## Crash recovery

The harness writes phase state atomically under a primary lock — either the old state or the new state is on disk after a crash, never a half-written file. There is no journal replay, no recovery oracle.

If a crash leaves an orphan session lock:

```bash
harness session unlock
```

That's the only manual recovery step. State-file corruption (rare) is fixed by `git checkout -- .scratch/phase-state.json`.

## Customizing — managed block in AGENTS.md

`AGENTS.md` is split into two regions:

```md
<!-- HARNESS:BEGIN managed:agents-rules v1 -->
... harness-managed content (regenerated on upgrade) ...
<!-- HARNESS:END managed:agents-rules -->

## Your project notes go below this line.
```

The managed block is regenerated when you `harness upgrade`. Edits **inside** the markers will cause a conflict on next upgrade — the harness refuses to overwrite and prints a diff. Edits **outside** the markers are yours forever.

## What the harness will NOT do

- It won't judge whether your plan is *correct* — that's your call.
- It won't enforce code quality / commit-message style / test coverage.
- It won't block bypassing the workflow if you really insist (e.g., git history rewriting).
- It assumes you and your machine are trustworthy. It is not a security boundary.

The 70% / 30% rule (see [`CONTEXT.md`](CONTEXT.md#scope--non-goals)) is the design contract.

## Uninstalling

```bash
harness uninstall --scope all
```

Or to keep your planning docs:

```bash
harness uninstall --scope harness,scratch,agents,adapters
# leaves .planning/ alone
```
