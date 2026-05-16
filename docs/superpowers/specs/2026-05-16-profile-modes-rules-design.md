# Profile Unification, Per-Profile Roo Modes, and Adapter-Scoped Augment Rules

Status: Draft (design approved 2026-05-16)
Owner: harness-maintainer

## Goals

1. Unify the installer "preset" concept and the manifest "profile" concept into a single first-class abstraction. The same name a user types in the installer is the same name that appears in `harness.py init --profiles <name>` and in `installed-manifest.json`.
2. Add stack-specific guidance to the harness via per-profile augment rules that drop into existing Roo mode rule directories and into a new OpenCode rules directory. New rules are installed only when the corresponding profile is selected and only for the adapters that the user installed.
3. Introduce exactly one new Roo mode (`ui-engineer`) where existing universal modes do not cover the verification model well (browser/UI). All other profile-specific guidance is delivered as augment rules, not as new modes.
4. Make Database selection optional, scoped to the installer flow, and free of profile name explosion.
5. Keep the `generic` profile untouched: a user who picks `generic` (or who installs no profile) sees zero domain-specific files anywhere in `.roo/`, `.opencode/`, or `.agents/`.

## Non-goals

- Replacing skill packs. Tech packs (`tech-mssql`, `tech-python`, etc.) keep their current responsibilities.
- Adding modes to OpenCode. OpenCode remains command-only.
- Introducing a new client adapter.
- Reworking the discuss/plan/execute/done state machine or the `.scratch/phase-state.json` contract.

## Final profile set

| Profile | Replaces | Default packs |
| --- | --- | --- |
| `generic` | (kept) | `workflow-core` |
| `dotnet-etl` | `dotnet-etl-mssql` profile | `workflow-core`, `workflow-etl`, `tech-csharp` |
| `python-etl` | new | `workflow-core`, `workflow-etl`, `tech-python` |
| `react-web` | new | `workflow-core`, `workflow-web-development`, `tech-react`, `tech-typescript`, `tech-tailwind` |

Retired:

- Installer preset `full`. No replacement. A user who wants every pack can list packs explicitly via `--packs`.
- Installer preset `minimal`. `generic` is the minimal profile.
- Manifest profile `dotnet-etl-mssql`. Migration handler converts existing installs to `dotnet-etl` + `tech-mssql`.

`KNOWN_PROFILES` in `scripts/harness.py` becomes:

```python
KNOWN_PROFILES = {"generic", "dotnet-etl", "python-etl", "react-web"}
LEGACY_PROFILE_ALIASES = {"dotnet-etl-mssql": "dotnet-etl"}  # warn + remap; remove in v0.8
```

## Database handling

Profile dirs no longer fork by database. Stack and DB are independent axes.

Interactive installer flow after profile selection (only when profile != `generic`):

```
Which database does this project use?
  1) mssql
  2) postgresql
  3) none
```

Result mapping:

- `mssql` → add `tech-mssql` and `workflow-db-context` to the install pack list.
- `postgresql` → add `tech-postgresql` and `workflow-db-context`.
- `none` → no DB packs are added.

Non-interactive equivalent on `harness.py init`:

```
--db {mssql|postgresql|none}
```

`--db` is ignored (with a single-line notice) when the chosen profile is `generic`. Default for the interactive flow when the user presses enter is `none`. For non-interactive, omitting `--db` is equivalent to `none`.

## New Roo mode: `ui-engineer`

Reason for a new mode (instead of an augment rule on `tdd-code`):

- UI work is not "tests green ⇒ done". The completion contract includes browser verification, responsive behavior, and accessibility, which require a different set of allowed tools and a different ending checklist than `tdd-code`.
- Putting browser-first instructions inside `tdd-code` would either weaken `tdd-code` for non-UI projects or require runtime branching the model cannot reliably do.

Definition (mirrors existing mode shape in `.roomodes`):

```json
{
  "slug": "ui-engineer",
  "name": "UI Engineer",
  "description": "Implements UI behavior with browser-first verification.",
  "whenToUse": "Use for component, page, layout, styling, and client-state changes in a React/TypeScript/Tailwind web app.",
  "roleDefinition": "You are a frontend engineer. You implement UI through small, verifiable changes and confirm behavior in the browser before declaring done.",
  "customInstructions": "Plan UI work as Red (state the visible behavior change), Green (implement smallest change), Verify (browser check the golden path and the most likely regression). Do not declare done without a browser verification note. Follow Tailwind and TypeScript conventions confirmed by repository evidence.",
  "groups": [
    "read",
    ["edit", { "fileRegex": "<see below>", "description": "UI implementation edits only; durable planning, tracker, agent-control, harness, and docs files are owned by other modes" }],
    "browser",
    "command",
    "mcp"
  ],
  "source": "project"
}
```

File regex starts as a copy of the `tdd-code` exclusion pattern (deny agent-control, durable planning, tracker, docs, README). It does not further restrict to a `src/` prefix because the harness is stack-neutral and real React projects vary (`src/`, `app/`, `apps/`, `packages/`). The deny-list is sufficient.

Install rules:

- Only added to `.roomodes` when `react-web` profile is selected AND adapter includes `roo`.
- Managed via a marker block inside `.roomodes` (see Managed `.roomodes` section).

OpenCode does not get a corresponding mode. UI guidance for OpenCode lives in `.opencode/profile-rules/react-web-*.md`.

## Per-profile augment rules

Canonical source layout (one set of rule files per profile, with frontmatter that drives placement):

```
harness/profiles/<profile>/
  PROFILE.md
  rules/
    <slug>.md
  modes/
    <mode-slug>.json    # only present where a profile contributes a Roo mode (react-web → ui-engineer.json)
```

Rule file frontmatter:

```yaml
---
roo_mode: tdd-code        # required if installable into Roo; one of the existing rules-<mode> directories, or "ui-engineer"
opencode: true            # required; if true the same file is installed under .opencode/profile-rules/
title: ETL restart and idempotency  # human-facing label, surfaced by doctor
---
```

Install targets derived from frontmatter and from the user's adapter selection:

- adapter includes `roo` AND `roo_mode` set → `harness/profiles/<profile>/rules/<slug>.md` is installed at `.roo/rules-<roo_mode>/<profile>-<slug>.md`.
- adapter includes `opencode` AND `opencode: true` → same source installed at `.opencode/profile-rules/<profile>-<slug>.md`.
- adapter `none` → only `PROFILE.md` is installed; no rules are placed under `.roo/` or `.opencode/`.

Manifest entries for these files set `owner: profile:<name>` so uninstall and upgrade can drop them cleanly when the profile is removed.

Initial rule catalog (content drafted in the implementation phase):

- `dotnet-etl/rules/restart-idempotency.md` — roo_mode `ops-observability`.
- `dotnet-etl/rules/etl-tdd.md` — roo_mode `tdd-code`.
- `dotnet-etl/rules/data-bug-trace.md` — roo_mode `diagnose`.
- `dotnet-etl/rules/etl-review.md` — roo_mode `review`.
- `python-etl/rules/restart-idempotency.md` — roo_mode `ops-observability`.
- `python-etl/rules/etl-tdd.md` — roo_mode `tdd-code`.
- `python-etl/rules/data-bug-trace.md` — roo_mode `diagnose`.
- `python-etl/rules/etl-review.md` — roo_mode `review`.
- `react-web/rules/ui-tdd.md` — roo_mode `tdd-code`.
- `react-web/rules/ui-review.md` — roo_mode `review`.
- `react-web/rules/ui-engineer-extras.md` — roo_mode `ui-engineer`.

`generic` ships no augment rules.

## OpenCode wiring

OpenCode has no auto-loaded rules directory analogous to Roo's `rules-<mode>/`. Augment files in `.opencode/profile-rules/` only take effect if the core commands tell the agent to read them.

Each of `.opencode/commands/{discuss,plan,execute,done}.md` gains a single line near the top (after the existing preflight pointers):

> "Before proceeding, read every file in `.opencode/profile-rules/` in alphabetical order, if the directory exists. Skip silently if it is missing or empty."

This keeps the line load-bearing in OpenCode installs and a no-op in installs that did not install a profile.

## Managed `.roomodes`

`.roomodes` becomes a managed file with a marker block. Pseudocode of the file layout:

```jsonc
{
  "customModes": [
    /* BEGIN harness:base-modes (managed) */
    { "slug": "orchestrator", ... },
    { "slug": "architect", ... },
    { "slug": "tdd-code", ... },
    { "slug": "diagnose", ... },
    { "slug": "review", ... },
    { "slug": "docs-issues", ... },
    { "slug": "ops-observability", ... },
    { "slug": "harness-maintainer", ... }
    /* END harness:base-modes */

    /* BEGIN harness:profile-modes (managed) */
    , { "slug": "ui-engineer", ... }  /* present only if react-web profile installed */
    /* END harness:profile-modes */
  ]
}
```

Marker semantics:

- `init`, `upgrade`, and profile add/remove operations rewrite each block in place. Anything between markers is harness-owned. Anything outside markers is project-owned and preserved.
- If the file has no markers (legacy installs), `upgrade` migrates it: it rewrites the entire `customModes` array from the manifest if and only if the array matches the harness baseline; otherwise it records a conflict file in `.harness/conflicts/` and stops.
- `check` fails if the profile-modes block is out of sync with currently installed profiles (e.g. `ui-engineer` present but `react-web` not in `init_options.profiles`).

## Installer UX

`scripts/install_harness.py --interactive`:

1. Target absolute path.
2. Adapter: `roo` / `opencode` / `both` / `none`.
3. Profile (single choice): `generic` / `dotnet-etl` / `python-etl` / `react-web`.
4. Database, only if profile != `generic`: `mssql` / `postgresql` / `none`.
5. Additional packs (preselect = profile defaults + DB packs; user can add more from the unselected list).
6. Confirm summary → install.

`scripts/harness.py init`:

- `--profiles <one>` (single value; comma-form still accepted for one entry; passing two profiles is rejected with an explicit error).
- `--db {mssql|postgresql|none}` (optional; ignored with one-line notice for `generic`).
- `--packs` continues to accept an explicit list. Default packs come from profile + DB resolution if `--packs` is not given.

Source pruning:

- Delete `harness/profiles/dotnet-etl-mssql/` from source.
- Add `harness/profiles/{dotnet-etl,python-etl,react-web}/PROFILE.md` and rule files.

## Migration of existing installs

`scripts/upgrade_harness.py` runs the following pre-upgrade transformation on `installed-manifest.json`:

- If `init_options.profiles` contains `dotnet-etl-mssql`:
  - Replace with `dotnet-etl`.
  - Ensure `tech-mssql` and `workflow-db-context` appear in the packs list (add if missing).
  - Record the change in the upgrade summary so the user can see it before applying.
- If the install history records the `full` preset (we keep a `init_options.preset` field for one release to detect this), expand it to the equivalent explicit packs list and record the change.

Dry-run prints the migration intent. Real upgrade applies it and proceeds. Both modes refuse to overwrite a `.roomodes` whose base block has diverged from the harness baseline outside markers.

`LEGACY_PROFILE_ALIASES` issues a deprecation warning on direct CLI use:

```
WARN: profile name "dotnet-etl-mssql" is deprecated; using "dotnet-etl" plus tech-mssql instead. This alias will be removed in v0.8.
```

## Verification

Source-repo tests (added in `scripts/test_harness.py`):

- For each profile in `{generic, dotnet-etl, python-etl, react-web}`:
  - Install with `--adapters roo` only. Assert expected `.roo/rules-*/<profile>-*.md` files exist and no `.opencode/` files appear.
  - Install with `--adapters opencode` only. Assert expected `.opencode/profile-rules/<profile>-*.md` files exist and no `.roo/` rule files appear.
  - Install with `--adapters both`. Assert both sets appear.
  - Install with `--adapters none`. Assert no augment files appear; only `PROFILE.md` is written.
- For `react-web` with adapter `roo` or `both`: assert `.roomodes` profile-modes block contains `ui-engineer`. Uninstall the profile and assert it is removed.
- For `dotnet-etl` with each of `--db mssql`, `--db postgresql`, `--db none`: assert the appropriate tech pack files are or are not present.
- Migration: synthesize a v0.6.0-style install with `dotnet-etl-mssql` and run upgrade in dry-run and apply modes. Assert manifest is rewritten correctly and rule files are placed under the new layout.

Release smoke (`scripts/release_smoke_test.py`):

- One pass per profile against `--adapters both`. Sample, not full matrix, to keep runtime bounded.

`harness.py check` additions:

- Fail if `.roomodes` profile-modes block lists a mode whose owning profile is not in `init_options.profiles`.
- Warn if `.opencode/commands/{discuss,plan,execute,done}.md` are present but missing the profile-rules read line.

`harness.py doctor` additions:

- Surface installed augment file titles (from frontmatter `title`) so the user can see what extra rules are active.
- Warn (not fail) when adapter is `opencode` and `.opencode/profile-rules/` directory is empty while a non-generic profile is installed (suggests a packaging bug).

## Files changed (source repo)

- `harness/manifest.json` — replace `dotnet-etl-mssql` entries; add per-profile rule and mode entries with `owner: profile:*`.
- `harness/profiles/dotnet-etl-mssql/` — deleted.
- `harness/profiles/dotnet-etl/`, `python-etl/`, `react-web/` — new dirs with `PROFILE.md`, `rules/*.md`, and for `react-web` a `modes/ui-engineer.json`.
- `.opencode/commands/{discuss,plan,execute,done}.md` — add profile-rules read instruction.
- `.roomodes` — wrap baseline modes in marker blocks; no behavior change for installs that pick zero profile-contributed modes.
- `scripts/harness.py` — `KNOWN_PROFILES`, `LEGACY_PROFILE_ALIASES`, `--db`, profile→pack resolution, `.roomodes` marker-block writer, profile-modes/profile-rules sync check.
- `scripts/install_harness.py` — drop `PRESETS` table; rewrite interactive prompts (profile single-select, optional DB).
- `scripts/upgrade_harness.py` — legacy-profile migration; `full`-preset migration; refusal-on-divergence for unmanaged `.roomodes`.
- `scripts/uninstall_harness.py` — ensure profile-scope removal also clears `.roomodes` profile-modes entries and `.opencode/profile-rules/` files.
- `scripts/test_harness.py` — new test cases listed in Verification.
- `scripts/release_smoke_test.py` — adjust matrix.
- `README.md` — preset/profile unification; `dotnet-etl-mssql` and `full` retired; `--db` documented; ui-engineer documented.
- `docs/profiles/*.md` — generated from `PROFILE.md` for each of the four profiles.

## Open questions to resolve in writing-plans phase

- Exact text of each augment rule (`etl-tdd.md`, `ui-tdd.md`, etc.). Content drafting is a planning-phase deliverable, not a design-phase one.
- Whether `LEGACY_PROFILE_ALIASES` should also accept `dotnet-etl-postgresql` defensively even though it never shipped.
- Whether `doctor` should fail (not just warn) when the profile-rules read line is missing from OpenCode commands.
