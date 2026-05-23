# Multi-file `.planning/codebase/` with anchor-ID schema

Codebase orientation lives in a structured 6-to-8 file directory at `.planning/codebase/`, not a single `codebase-recon.md`. Files carry YAML frontmatter and use bracketed dotted anchor IDs (`## [codebase.<file>.<key>] Title`) so workflow skill-packs can grep specific facts without re-reading the whole document or depending on section numbers and prose titles.

The initial harness commit (`4f39d7b`) already shipped this exact structure as skeleton stubs. The nuke commit (`3048847 nuke: wipe all design docs + planning state + memory`) wiped it per a mandate to reset prose for refactor. Milestone 9 reintroduced recon as a single 1-page file, which works for bootstrap but degrades as a stable reference surface — every consumer skill-pack ends up grepping the same large file by section number, sections grow unboundedly on non-trivial codebases, and there is no contract for where a given fact lives. Multi-file with anchor IDs restores grep-stability without restoring the original noise: file count is bounded (6 core, 2 conditional) and each anchor is a stable contract.

The file set is: `SUMMARY.md`, `STACK.md`, `STRUCTURE.md`, `TESTING.md`, `CONVENTIONS.md`, `CONCERNS.md` always; `ARCHITECTURE.md` and `INTEGRATIONS.md` only when the repo is non-trivial or has detected external integrations. `SUMMARY.md` is a one-page entrypoint with identity, primary install/test command, key edit paths, top three concerns, and links to the others — it is not a pure index, because a low-reasoning agent's first question is "what do I run" not "where do I look."

Anchor grammar is `## [codebase.<file>.<key>] Title`. Square-bracketed, dotted, alphabetical. This was chosen over an em-dash separator (Unicode-fragile) and over HTML `<a id>` (renders awkwardly in plain Markdown and adds parse complexity for agents). The exhaustive anchor list per file lives in `docs/ARTIFACTS.md`; ADR fixing the grammar is enough.

Every file carries YAML frontmatter:

```yaml
schema_version: 1
artifact_type: codebase.stack
generated_by: harness-recon@<version>   # or workflow-codebase-recon, agent
updated_at: 2026-05-23
ownership: auto | hybrid | agent
source: detected | inferred | human | mixed
refresh_policy: overwrite | preserve_sections | manual
status: current | stale | partial
```

`ownership` says who is allowed to edit; `refresh_policy` says what the CLI is allowed to overwrite when it runs again. The two are distinct and both matter — agents need to know whether their CONVENTIONS edits survive a `harness recon` re-run (yes: `preserve_sections`) and whether STACK auto-fill will clobber a manual override (no: same `preserve_sections` default).

Generation is hybrid. `harness recon` auto-fills the detectable files — `STACK`, `STRUCTURE`, `TESTING`, `INTEGRATIONS` — by reading lockfiles, dir tree, and package scripts. The `workflow-codebase-recon` skill-pack writes the judgment-heavy files — `CONVENTIONS`, `ARCHITECTURE`, `CONCERNS`, `SUMMARY` — because bad auto-generated architecture is worse than absent architecture. Tech packs (`tech-python`, `tech-react`) read-only; they may propose patches but never write to `.planning/codebase/` directly, to keep ownership unfragmented.

Consumer skill-packs declare `reads: [<anchor>, ...]` in their frontmatter rather than hard-coding grep patterns in each `SKILL.md`. `workflow-tdd` declares `reads: [codebase.testing.commands, codebase.testing.frameworks]`; `workflow-code-review` declares `reads: [codebase.conventions.*, codebase.concerns.*]`. The skill-pack execution layer grep-resolves the anchor to its content. This keeps the reading contract central — when an anchor renames, only the contract changes, not every consumer.

The migration is a clean replace. The old `codebase-recon.md` skeleton and `lib/recon.py` single-file output are deleted in the same milestone. There are no external users; dual-write would add complexity without benefit. Reversing this ADR would mean either collapsing back to a single file (regressing on the scaling problem) or moving to a richer format like SQLite (regressing on grep-friendliness for low-reasoning agents); both are non-trivial and neither has cause yet.
