# Profile Unification, Per-Profile Roo Modes, and Adapter-Scoped Augment Rules — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse installer presets and manifest profiles into a single concept (`generic`, `dotnet-etl`, `python-etl`, `react-web`), make DB an optional installer axis, add the `ui-engineer` Roo mode for `react-web`, and ship profile-scoped augment rule files that install conditionally into `.roo/rules-<mode>/` and `.opencode/profile-rules/` based on the selected adapters.

**Architecture:** Profile dirs under `harness/profiles/<name>/` contain a `PROFILE.md`, a `rules/` folder of augment markdown files, and an optional `modes/` folder for Roo mode JSON. Each augment rule file is declared explicitly in `harness/manifest.json` once per adapter target (Roo and/or OpenCode), tagged with both `profile` and `adapter` keys, so the existing manifest resolver installs it only when the user selected that profile and that adapter. `.roomodes` is rewritten as a marker-block file so profile-contributed modes can be added or removed independently of the base 8 modes. `scripts/install_harness.py` replaces its preset table with a profile single-select followed by an optional database question that maps to packs.

**Tech Stack:** Python 3 (stdlib only — no new deps). `unittest`. Existing `harness.manifest` resolver. JSON for `.roomodes`. Markdown with YAML frontmatter for augment rules (frontmatter is metadata only — the resolver does not parse it; placement is encoded in manifest entries).

---

## File Structure

**Created:**
- `harness/profiles/dotnet-etl/PROFILE.md`
- `harness/profiles/dotnet-etl/rules/etl-tdd.md`
- `harness/profiles/dotnet-etl/rules/restart-idempotency.md`
- `harness/profiles/dotnet-etl/rules/data-bug-trace.md`
- `harness/profiles/dotnet-etl/rules/etl-review.md`
- `harness/profiles/python-etl/PROFILE.md`
- `harness/profiles/python-etl/rules/etl-tdd.md`
- `harness/profiles/python-etl/rules/restart-idempotency.md`
- `harness/profiles/python-etl/rules/data-bug-trace.md`
- `harness/profiles/python-etl/rules/etl-review.md`
- `harness/profiles/react-web/PROFILE.md`
- `harness/profiles/react-web/rules/ui-tdd.md`
- `harness/profiles/react-web/rules/ui-review.md`
- `harness/profiles/react-web/rules/ui-engineer-extras.md`
- `harness/profiles/react-web/modes/ui-engineer.json`

**Deleted:**
- `harness/profiles/dotnet-etl-mssql/` (entire directory)

**Modified:**
- `harness/manifest.json` — replace `dotnet-etl-mssql` profile entry; add per-profile rule entries with `profile` + `adapter`; add `react-web` mode entry.
- `.roomodes` — wrap baseline modes in marker block; managed by `scripts/lib/roomodes_writer.py`.
- `.opencode/commands/{discuss,plan,execute,done}.md` — add profile-rules read instruction.
- `scripts/harness.py` — `KNOWN_PROFILES`, `LEGACY_PROFILE_ALIASES`, `--db`, profile→pack resolution, profile-modes sync check, `.roomodes` marker-block plumbing.
- `scripts/install_harness.py` — drop `PROFILE_PRESETS`; rewrite interactive flow (profile single-select + optional DB).
- `scripts/upgrade_harness.py` — legacy-profile + `full`-preset migration.
- `scripts/uninstall_harness.py` — clear profile-modes block entries and `.opencode/profile-rules/` when their owning profile is removed.
- `scripts/test_harness.py` — new test cases.
- `scripts/release_smoke_test.py` — adjust matrix.
- `scripts/lib/roomodes_writer.py` — **created**: read/write `.roomodes` with managed marker blocks for `base-modes` and `profile-modes`.
- `README.md` — preset/profile unification; `--db` flag; `ui-engineer` mode; retired `full` and `dotnet-etl-mssql`.

**Generated docs (manifest-installed):**
- `docs/profiles/dotnet-etl.md` (replaces `dotnet-etl-mssql.md`)
- `docs/profiles/python-etl.md`
- `docs/profiles/react-web.md`

---

## Pre-flight

- [ ] **Step 0.1: Branch + baseline tests green**

```bash
git checkout -b feat/profile-unification
python3 -m unittest scripts/test_harness.py
python3 scripts/harness.py check
```

Expected: all green. If anything fails on `main`, stop and report.

---

## Task 1: Marker-block writer for `.roomodes`

`.roomodes` is currently a static JSON file owned by the Roo adapter. We need to insert and remove profile-contributed modes without disturbing the base 8. JSON has no comment syntax in standard parsers, so we treat `.roomodes` as a text file with two well-known sentinel comment lines that are JSON-illegal but recognized by our writer; for parser compatibility we emit a real JSON file by re-rendering the whole array on each write. The "marker block" is internal bookkeeping in the writer, not on disk.

**Files:**
- Create: `scripts/lib/roomodes_writer.py`
- Test: `scripts/test_harness.py` (new `RoomodesWriterTests` class)

- [ ] **Step 1.1: Write failing test for read of baseline `.roomodes`**

Add to `scripts/test_harness.py`:

```python
class RoomodesWriterTests(unittest.TestCase):
    def test_read_baseline_returns_eight_base_modes(self):
        from scripts.lib import roomodes_writer
        baseline = roomodes_writer.read(REPO_ROOT / ".roomodes")
        self.assertEqual(
            [m["slug"] for m in baseline.base_modes],
            [
                "orchestrator",
                "architect",
                "tdd-code",
                "diagnose",
                "review",
                "docs-issues",
                "ops-observability",
                "harness-maintainer",
            ],
        )
        self.assertEqual(baseline.profile_modes, [])
```

(Define `REPO_ROOT = Path(__file__).resolve().parent.parent` at top if missing — check existing file first; if a similar constant already exists, reuse it.)

- [ ] **Step 1.2: Run test, expect ImportError**

```bash
python3 -m unittest scripts.test_harness.RoomodesWriterTests -v
```

Expected: ModuleNotFoundError for `scripts.lib.roomodes_writer`.

- [ ] **Step 1.3: Create `scripts/lib/roomodes_writer.py`**

```python
"""Read and write `.roomodes` with a logical base/profile split.

`.roomodes` on disk is plain JSON of shape `{"customModes": [ ... ]}`. We do
not embed marker strings in the file (they would be invalid JSON). Instead the
writer recognizes the eight harness-baseline modes by slug and treats every
other entry whose `slug` is in `KNOWN_PROFILE_MODE_SLUGS` as profile-owned.
Any third mode it cannot classify is preserved as `unmanaged_modes` so a
later upgrade refuses to overwrite project-owned customizations.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

BASE_MODE_SLUGS = (
    "orchestrator",
    "architect",
    "tdd-code",
    "diagnose",
    "review",
    "docs-issues",
    "ops-observability",
    "harness-maintainer",
)

KNOWN_PROFILE_MODE_SLUGS = frozenset({"ui-engineer"})


@dataclass
class RoomodesContent:
    base_modes: list[dict] = field(default_factory=list)
    profile_modes: list[dict] = field(default_factory=list)
    unmanaged_modes: list[dict] = field(default_factory=list)


def read(path: Path) -> RoomodesContent:
    data = json.loads(path.read_text(encoding="utf-8"))
    modes = data.get("customModes", [])
    base, profile, unmanaged = [], [], []
    for mode in modes:
        slug = mode.get("slug")
        if slug in BASE_MODE_SLUGS:
            base.append(mode)
        elif slug in KNOWN_PROFILE_MODE_SLUGS:
            profile.append(mode)
        else:
            unmanaged.append(mode)
    # preserve the canonical baseline order
    base.sort(key=lambda m: BASE_MODE_SLUGS.index(m["slug"]))
    return RoomodesContent(base_modes=base, profile_modes=profile, unmanaged_modes=unmanaged)


def write(path: Path, content: RoomodesContent) -> None:
    modes = list(content.base_modes) + list(content.profile_modes) + list(content.unmanaged_modes)
    payload = {"customModes": modes}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def set_profile_modes(path: Path, profile_modes: list[dict]) -> None:
    current = read(path)
    current.profile_modes = profile_modes
    write(path, current)
```

- [ ] **Step 1.4: Run test, expect pass**

```bash
python3 -m unittest scripts.test_harness.RoomodesWriterTests -v
```

Expected: 1 test passes.

- [ ] **Step 1.5: Add round-trip test**

Add to `RoomodesWriterTests`:

```python
def test_set_profile_modes_round_trip(self):
    from scripts.lib import roomodes_writer
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / ".roomodes"
        target.write_text((REPO_ROOT / ".roomodes").read_text(encoding="utf-8"), encoding="utf-8")
        ui_engineer = {"slug": "ui-engineer", "name": "UI Engineer"}
        roomodes_writer.set_profile_modes(target, [ui_engineer])
        again = roomodes_writer.read(target)
        self.assertEqual(len(again.base_modes), 8)
        self.assertEqual([m["slug"] for m in again.profile_modes], ["ui-engineer"])
        roomodes_writer.set_profile_modes(target, [])
        again2 = roomodes_writer.read(target)
        self.assertEqual(again2.profile_modes, [])
        self.assertEqual(len(again2.base_modes), 8)
```

Run: `python3 -m unittest scripts.test_harness.RoomodesWriterTests -v` — expected: 2 passes.

- [ ] **Step 1.6: Add unmanaged-preservation test**

```python
def test_unmanaged_modes_preserved(self):
    from scripts.lib import roomodes_writer
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / ".roomodes"
        target.write_text(json.dumps({"customModes": [
            {"slug": "orchestrator"},
            {"slug": "tdd-code"},
            {"slug": "my-custom-mode", "name": "Project-owned"},
        ]}), encoding="utf-8")
        c = roomodes_writer.read(target)
        self.assertEqual([m["slug"] for m in c.unmanaged_modes], ["my-custom-mode"])
        roomodes_writer.set_profile_modes(target, [{"slug": "ui-engineer"}])
        c2 = roomodes_writer.read(target)
        self.assertEqual([m["slug"] for m in c2.unmanaged_modes], ["my-custom-mode"])
```

Run + expect pass.

- [ ] **Step 1.7: Commit**

```bash
git add scripts/lib/roomodes_writer.py scripts/test_harness.py
git commit -m "feat(harness): roomodes writer with base/profile split"
```

---

## Task 2: Profile dirs and rule content (sources only, no install wiring yet)

Create profile directories and `PROFILE.md`/`rules/` content. No manifest changes in this task — purely source files.

**Files:**
- Create: 15 source files listed in File Structure.

- [ ] **Step 2.1: Write `harness/profiles/dotnet-etl/PROFILE.md`**

```markdown
# dotnet-etl profile

Stack-aware harness preset for .NET / C# ETL projects. Stack is fixed; database
selection is independent and is set at install time via `--db`.

## When to use

- The repository hosts one or more ETL jobs implemented in C# / .NET.
- The database backing those jobs is selected separately (mssql, postgresql, none).

## What this profile activates

- Default packs: `workflow-core`, `workflow-etl`, `tech-csharp`.
- Augment rules under `.roo/rules-<mode>/` and `.opencode/profile-rules/`:
  - `etl-tdd` (tdd-code)
  - `restart-idempotency` (ops-observability)
  - `data-bug-trace` (diagnose)
  - `etl-review` (review)

## What this profile does not do

- It does not pick a database engine. Use `--db mssql` or `--db postgresql` to
  add the corresponding `tech-*` and `workflow-db-context` packs.
- It does not select a test runner. The TDD augment rule defers to repository
  evidence.
```

- [ ] **Step 2.2: Write `harness/profiles/dotnet-etl/rules/etl-tdd.md`**

```markdown
---
roo_mode: tdd-code
opencode: true
title: ETL TDD discipline
---

When implementing or modifying ETL behavior in this repository, follow these
rules in addition to the universal TDD workflow:

1. Phrase each red test as a row-level or batch-level invariant ("input batch
   {X} produces stage {Y} with row count {Z} and no duplicates"), not as a
   line-of-code assertion.
2. Use the smallest data fixture that can fail meaningfully. Prefer in-memory
   fakes; only touch a real database when the assertion is about engine
   behavior the fake cannot reproduce (e.g. unique-constraint conflicts).
3. Every load step must have at least one test that runs the same input twice
   in a row and asserts the load is idempotent (rerun produces no duplicates,
   no orphaned staging rows).
4. Every transform must have at least one test for the empty-input case.
5. Do not declare a step done without verifying the regression test fails on a
   reverted implementation.
```

- [ ] **Step 2.3: Write `harness/profiles/dotnet-etl/rules/restart-idempotency.md`**

```markdown
---
roo_mode: ops-observability
opencode: true
title: ETL restart and idempotency
---

For any ETL pipeline change, treat the pipeline as restartable from any prior
checkpoint state.

- Every staging table or intermediate artifact must have a documented "what
  happens on restart" answer in the plan: cleared, upserted, appended with a
  watermark, or treated as immutable.
- Loads into target tables must be expressible as "merge by natural key" or
  "append with deduplication"; raw appends without a dedup story require an
  explicit decision note.
- Add structured log fields `job_id`, `run_id`, `step`, `rows_in`, `rows_out`,
  `outcome` (`ok|skipped|partial|failed`) at every step boundary.
- Failures should write enough state that a rerun can resume; never leave a
  partially-written target table without a recovery path.
```

- [ ] **Step 2.4: Write `harness/profiles/dotnet-etl/rules/data-bug-trace.md`**

```markdown
---
roo_mode: diagnose
opencode: true
title: Data bug tracing
---

For data correctness bugs (wrong row counts, wrong values, duplicates,
missing rows):

1. Identify the smallest reproducing input. If the symptom is at the load
   step, trace one example row backwards through each confirmed stage.
2. At every stage, print or persist that one row's projection. Do not skip a
   stage because "it should be fine"; that is the stage most likely to be
   wrong.
3. Distinguish three failure shapes before proposing a fix:
   - Wrong source data (fix at extract, add validation).
   - Wrong transform (fix transform, add invariant test).
   - Correct transform applied to wrong scope (fix predicate, add scoping test).
4. Do not patch the symptom at the load step if the cause is upstream.
```

- [ ] **Step 2.5: Write `harness/profiles/dotnet-etl/rules/etl-review.md`**

```markdown
---
roo_mode: review
opencode: true
title: ETL review checklist
---

Reviewing ETL changes, prioritize in this order:

1. Idempotency: can the change run twice without duplicating or corrupting?
2. Failure recovery: where can it crash, and what is the recovery path?
3. Schema drift: does the change tolerate the source adding or renaming a
   column?
4. Observability: are log fields sufficient for an operator to find a failed
   run?
5. Performance: only flag if the change demonstrably regresses runtime or
   memory; do not speculate.
6. Test coverage gaps: name them explicitly, do not generalize.
```

- [ ] **Step 2.6: Write `harness/profiles/python-etl/PROFILE.md` and its four rule files**

Same structure as dotnet-etl, but Python-flavored:

`PROFILE.md` body:

```markdown
# python-etl profile

Stack-aware harness preset for Python ETL / data pipeline projects.

## When to use

- The repository hosts one or more ETL jobs implemented in Python.
- Database is selected separately at install time.

## Activations

- Default packs: `workflow-core`, `workflow-etl`, `tech-python`.
- Augment rules:
  - `etl-tdd` (tdd-code)
  - `restart-idempotency` (ops-observability)
  - `data-bug-trace` (diagnose)
  - `etl-review` (review)
```

For `python-etl/rules/etl-tdd.md`, copy the dotnet-etl version verbatim and replace `title:` value with `Python ETL TDD discipline`; the body text is stack-neutral and applies as-is. Same for `restart-idempotency.md`, `data-bug-trace.md`, `etl-review.md` — the content is engine-agnostic. (DRY: we accept verbatim duplication here because the files install into different paths and we want one canonical text to evolve per profile, not a shared include that would need a new build step.)

- [ ] **Step 2.7: Write `harness/profiles/react-web/PROFILE.md`**

```markdown
# react-web profile

Stack-aware harness preset for React / TypeScript / Tailwind web apps.

## When to use

- The repository builds a web UI with React.
- TypeScript and Tailwind are in use or planned.

## Activations

- Default packs: `workflow-core`, `workflow-web-development`, `tech-react`,
  `tech-typescript`, `tech-tailwind`.
- Roo mode: `ui-engineer` (browser-first UI implementation).
- Augment rules:
  - `ui-tdd` (tdd-code)
  - `ui-review` (review)
  - `ui-engineer-extras` (ui-engineer)
```

- [ ] **Step 2.8: Write `harness/profiles/react-web/rules/ui-tdd.md`**

```markdown
---
roo_mode: tdd-code
opencode: true
title: UI TDD discipline
---

When changing visible UI behavior:

1. Phrase the red test as a user-visible behavior: "clicking the submit button
   with an empty form shows the inline error message", not "calls
   `validateForm`".
2. Use the project's existing test runner and rendering library. If the
   repository has no component test infrastructure yet, add it as a separate
   prerequisite task before continuing.
3. After implementing the smallest passing change, open the browser, exercise
   the golden path manually, and check at least one likely regression (e.g.
   resize to narrow viewport, tab through focus order).
4. A passing unit test alone is not "done" for UI work; a recorded browser
   verification note is.
```

- [ ] **Step 2.9: Write `harness/profiles/react-web/rules/ui-review.md`**

```markdown
---
roo_mode: review
opencode: true
title: UI review checklist
---

Reviewing UI changes, prioritize:

1. Behavior correctness on the golden path.
2. Responsive behavior at the project's documented breakpoints (or at least
   one narrow viewport if no breakpoint doc exists).
3. Keyboard focus order and visible focus indicator.
4. Empty, loading, error, and disabled states for every new interactive
   element.
5. Tailwind class hygiene: no inline arbitrary-value classes that duplicate an
   existing utility; no class strings that exceed the team's readability bar.
6. TypeScript: no `any` introduced without an explanatory comment.
```

- [ ] **Step 2.10: Write `harness/profiles/react-web/rules/ui-engineer-extras.md`**

```markdown
---
roo_mode: ui-engineer
opencode: true
title: UI Engineer mode extras
---

Operating in `ui-engineer` mode:

- Treat every change as having a Red / Green / Verify sequence. Verify is in
  the browser, not the test runner.
- If you cannot run the dev server in this environment, say so explicitly and
  defer the "done" claim until the user runs the verify step.
- Do not edit non-frontend files. Backend, infra, and harness changes belong
  in `tdd-code`, `ops-observability`, or `harness-maintainer`.
- Do not introduce new dependencies without naming the rejected alternatives
  in the plan.
```

- [ ] **Step 2.11: Write `harness/profiles/react-web/modes/ui-engineer.json`**

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
    ["edit", { "fileRegex": "^(?!(?:\\.roomodes(?:$|\\.)|\\.roo(?:/|$)|\\.scratch(?:/|$)|\\.planning(?:/|$)|docs(?:/|$)|README\\.md$|\\.rooignore$|(?:^|.*/)(?:AGENTS|CLAUDE)\\.md$)).+$", "description": "UI implementation edits only; docs, durable planning, tracker, phase state, and agent-control files are owned by other modes" }],
    "browser",
    "command",
    "mcp"
  ],
  "source": "project"
}
```

- [ ] **Step 2.12: Delete `harness/profiles/dotnet-etl-mssql/`**

```bash
git rm -r harness/profiles/dotnet-etl-mssql
```

- [ ] **Step 2.13: Commit**

```bash
git add harness/profiles/
git commit -m "feat(harness): add dotnet-etl, python-etl, react-web profile sources"
```

---

## Task 3: Manifest update for new profile entries

Add per-rule, per-adapter manifest entries. Each rule file produces 0, 1, or 2 manifest entries based on `roo_mode` and `opencode` frontmatter. Because the manifest is static, we hand-author these entries here (the resolver does not parse frontmatter).

**Files:**
- Modify: `harness/manifest.json`

- [ ] **Step 3.1: Write failing test that asserts new manifest entries exist**

Add to `scripts/test_harness.py`:

```python
class ManifestProfileEntriesTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((REPO_ROOT / "harness/manifest.json").read_text(encoding="utf-8"))
        self.entries = self.manifest["files"]

    def _entry(self, path):
        for e in self.entries:
            if e["path"] == path:
                return e
        self.fail(f"manifest entry missing: {path}")

    def test_legacy_dotnet_etl_mssql_profile_doc_removed(self):
        paths = {e["path"] for e in self.entries}
        self.assertNotIn("docs/profiles/dotnet-etl-mssql.md", paths)

    def test_new_profile_docs_present(self):
        for path in (
            "docs/profiles/dotnet-etl.md",
            "docs/profiles/python-etl.md",
            "docs/profiles/react-web.md",
        ):
            e = self._entry(path)
            self.assertEqual(e["owner"], f"profile:{path.split('/')[-1].removesuffix('.md')}")

    def test_dotnet_etl_etl_tdd_installs_into_roo_and_opencode(self):
        roo = self._entry(".roo/rules-tdd-code/dotnet-etl-etl-tdd.md")
        self.assertEqual(roo["profile"], "dotnet-etl")
        self.assertEqual(roo["adapter"], "roo")
        self.assertEqual(roo["owner"], "profile:dotnet-etl")
        oc = self._entry(".opencode/profile-rules/dotnet-etl-etl-tdd.md")
        self.assertEqual(oc["adapter"], "opencode")
        self.assertEqual(oc["profile"], "dotnet-etl")

    def test_react_web_ui_engineer_extras_targets_ui_engineer_rules_dir(self):
        roo = self._entry(".roo/rules-ui-engineer/react-web-ui-engineer-extras.md")
        self.assertEqual(roo["profile"], "react-web")
        self.assertEqual(roo["adapter"], "roo")
```

Run: `python3 -m unittest scripts.test_harness.ManifestProfileEntriesTests -v`
Expected: 4 fails.

- [ ] **Step 3.2: Edit `harness/manifest.json` — remove the `dotnet-etl-mssql` profile doc entry**

Delete the entry whose `path` is `docs/profiles/dotnet-etl-mssql.md`.

- [ ] **Step 3.3: Add three new profile-doc entries**

After the `generic` profile doc entry, insert:

```json
{
  "path": "docs/profiles/dotnet-etl.md",
  "source": "harness/profiles/dotnet-etl/PROFILE.md",
  "policy": "harness-owned",
  "owner": "profile:dotnet-etl",
  "profile": "dotnet-etl"
},
{
  "path": "docs/profiles/python-etl.md",
  "source": "harness/profiles/python-etl/PROFILE.md",
  "policy": "harness-owned",
  "owner": "profile:python-etl",
  "profile": "python-etl"
},
{
  "path": "docs/profiles/react-web.md",
  "source": "harness/profiles/react-web/PROFILE.md",
  "policy": "harness-owned",
  "owner": "profile:react-web",
  "profile": "react-web"
},
```

- [ ] **Step 3.4: Add Roo rule entries for each profile-rule combination**

For each profile × each rule file, append a manifest entry with `adapter: "roo"`. Concrete list to append (all under `files[]`):

```json
{ "path": ".roo/rules-tdd-code/dotnet-etl-etl-tdd.md",
  "source": "harness/profiles/dotnet-etl/rules/etl-tdd.md",
  "policy": "harness-owned", "owner": "profile:dotnet-etl",
  "profile": "dotnet-etl", "adapter": "roo" },
{ "path": ".roo/rules-ops-observability/dotnet-etl-restart-idempotency.md",
  "source": "harness/profiles/dotnet-etl/rules/restart-idempotency.md",
  "policy": "harness-owned", "owner": "profile:dotnet-etl",
  "profile": "dotnet-etl", "adapter": "roo" },
{ "path": ".roo/rules-diagnose/dotnet-etl-data-bug-trace.md",
  "source": "harness/profiles/dotnet-etl/rules/data-bug-trace.md",
  "policy": "harness-owned", "owner": "profile:dotnet-etl",
  "profile": "dotnet-etl", "adapter": "roo" },
{ "path": ".roo/rules-review/dotnet-etl-etl-review.md",
  "source": "harness/profiles/dotnet-etl/rules/etl-review.md",
  "policy": "harness-owned", "owner": "profile:dotnet-etl",
  "profile": "dotnet-etl", "adapter": "roo" },

{ "path": ".roo/rules-tdd-code/python-etl-etl-tdd.md",
  "source": "harness/profiles/python-etl/rules/etl-tdd.md",
  "policy": "harness-owned", "owner": "profile:python-etl",
  "profile": "python-etl", "adapter": "roo" },
{ "path": ".roo/rules-ops-observability/python-etl-restart-idempotency.md",
  "source": "harness/profiles/python-etl/rules/restart-idempotency.md",
  "policy": "harness-owned", "owner": "profile:python-etl",
  "profile": "python-etl", "adapter": "roo" },
{ "path": ".roo/rules-diagnose/python-etl-data-bug-trace.md",
  "source": "harness/profiles/python-etl/rules/data-bug-trace.md",
  "policy": "harness-owned", "owner": "profile:python-etl",
  "profile": "python-etl", "adapter": "roo" },
{ "path": ".roo/rules-review/python-etl-etl-review.md",
  "source": "harness/profiles/python-etl/rules/etl-review.md",
  "policy": "harness-owned", "owner": "profile:python-etl",
  "profile": "python-etl", "adapter": "roo" },

{ "path": ".roo/rules-tdd-code/react-web-ui-tdd.md",
  "source": "harness/profiles/react-web/rules/ui-tdd.md",
  "policy": "harness-owned", "owner": "profile:react-web",
  "profile": "react-web", "adapter": "roo" },
{ "path": ".roo/rules-review/react-web-ui-review.md",
  "source": "harness/profiles/react-web/rules/ui-review.md",
  "policy": "harness-owned", "owner": "profile:react-web",
  "profile": "react-web", "adapter": "roo" },
{ "path": ".roo/rules-ui-engineer/react-web-ui-engineer-extras.md",
  "source": "harness/profiles/react-web/rules/ui-engineer-extras.md",
  "policy": "harness-owned", "owner": "profile:react-web",
  "profile": "react-web", "adapter": "roo" }
```

- [ ] **Step 3.5: Add OpenCode rule entries**

For each rule file above, append the mirror under `.opencode/profile-rules/<profile>-<slug>.md` with `adapter: "opencode"`. Concrete entries:

```json
{ "path": ".opencode/profile-rules/dotnet-etl-etl-tdd.md",
  "source": "harness/profiles/dotnet-etl/rules/etl-tdd.md",
  "policy": "harness-owned", "owner": "profile:dotnet-etl",
  "profile": "dotnet-etl", "adapter": "opencode" },
{ "path": ".opencode/profile-rules/dotnet-etl-restart-idempotency.md",
  "source": "harness/profiles/dotnet-etl/rules/restart-idempotency.md",
  "policy": "harness-owned", "owner": "profile:dotnet-etl",
  "profile": "dotnet-etl", "adapter": "opencode" },
{ "path": ".opencode/profile-rules/dotnet-etl-data-bug-trace.md",
  "source": "harness/profiles/dotnet-etl/rules/data-bug-trace.md",
  "policy": "harness-owned", "owner": "profile:dotnet-etl",
  "profile": "dotnet-etl", "adapter": "opencode" },
{ "path": ".opencode/profile-rules/dotnet-etl-etl-review.md",
  "source": "harness/profiles/dotnet-etl/rules/etl-review.md",
  "policy": "harness-owned", "owner": "profile:dotnet-etl",
  "profile": "dotnet-etl", "adapter": "opencode" },

{ "path": ".opencode/profile-rules/python-etl-etl-tdd.md",
  "source": "harness/profiles/python-etl/rules/etl-tdd.md",
  "policy": "harness-owned", "owner": "profile:python-etl",
  "profile": "python-etl", "adapter": "opencode" },
{ "path": ".opencode/profile-rules/python-etl-restart-idempotency.md",
  "source": "harness/profiles/python-etl/rules/restart-idempotency.md",
  "policy": "harness-owned", "owner": "profile:python-etl",
  "profile": "python-etl", "adapter": "opencode" },
{ "path": ".opencode/profile-rules/python-etl-data-bug-trace.md",
  "source": "harness/profiles/python-etl/rules/data-bug-trace.md",
  "policy": "harness-owned", "owner": "profile:python-etl",
  "profile": "python-etl", "adapter": "opencode" },
{ "path": ".opencode/profile-rules/python-etl-etl-review.md",
  "source": "harness/profiles/python-etl/rules/etl-review.md",
  "policy": "harness-owned", "owner": "profile:python-etl",
  "profile": "python-etl", "adapter": "opencode" },

{ "path": ".opencode/profile-rules/react-web-ui-tdd.md",
  "source": "harness/profiles/react-web/rules/ui-tdd.md",
  "policy": "harness-owned", "owner": "profile:react-web",
  "profile": "react-web", "adapter": "opencode" },
{ "path": ".opencode/profile-rules/react-web-ui-review.md",
  "source": "harness/profiles/react-web/rules/ui-review.md",
  "policy": "harness-owned", "owner": "profile:react-web",
  "profile": "react-web", "adapter": "opencode" },
{ "path": ".opencode/profile-rules/react-web-ui-engineer-extras.md",
  "source": "harness/profiles/react-web/rules/ui-engineer-extras.md",
  "policy": "harness-owned", "owner": "profile:react-web",
  "profile": "react-web", "adapter": "opencode" }
```

- [ ] **Step 3.6: Run tests, expect pass**

```bash
python3 -m unittest scripts.test_harness.ManifestProfileEntriesTests -v
python3 -m unittest scripts.test_harness -v
```

Expected: `ManifestProfileEntriesTests` passes; full suite stays green except for tests that hardcode old profile names — fix those inline (e.g., references to `dotnet-etl-mssql` in existing tests get updated to `dotnet-etl`).

- [ ] **Step 3.7: Commit**

```bash
git add harness/manifest.json scripts/test_harness.py
git commit -m "feat(harness): manifest entries for new profile rules + docs"
```

---

## Task 4: Resolver wiring — `KNOWN_PROFILES`, legacy aliases, profile→pack defaults

**Files:**
- Modify: `scripts/harness.py`

- [ ] **Step 4.1: Write failing test**

Add `ProfileResolutionTests` to `scripts/test_harness.py`:

```python
class ProfileResolutionTests(unittest.TestCase):
    def test_known_profiles(self):
        from scripts import harness as h
        self.assertEqual(h.KNOWN_PROFILES, {"generic", "dotnet-etl", "python-etl", "react-web"})

    def test_legacy_alias_maps(self):
        from scripts import harness as h
        self.assertEqual(h.LEGACY_PROFILE_ALIASES["dotnet-etl-mssql"], "dotnet-etl")

    def test_default_packs_for_dotnet_etl(self):
        from scripts import harness as h
        packs = h.default_packs_for_profile("dotnet-etl")
        self.assertEqual(set(packs), {"workflow-core", "workflow-etl", "tech-csharp"})

    def test_db_packs_postgresql(self):
        from scripts import harness as h
        self.assertEqual(
            set(h.db_packs("postgresql")),
            {"tech-postgresql", "workflow-db-context"},
        )

    def test_db_packs_none_returns_empty(self):
        from scripts import harness as h
        self.assertEqual(h.db_packs("none"), [])
```

Run: expected 5 fails.

- [ ] **Step 4.2: Edit `scripts/harness.py`**

Replace `KNOWN_PROFILES = {"generic", "dotnet-etl-mssql"}` with:

```python
KNOWN_PROFILES = {"generic", "dotnet-etl", "python-etl", "react-web"}
LEGACY_PROFILE_ALIASES = {"dotnet-etl-mssql": "dotnet-etl"}

_PROFILE_DEFAULT_PACKS = {
    "generic": ("workflow-core",),
    "dotnet-etl": ("workflow-core", "workflow-etl", "tech-csharp"),
    "python-etl": ("workflow-core", "workflow-etl", "tech-python"),
    "react-web": (
        "workflow-core",
        "workflow-web-development",
        "tech-react",
        "tech-typescript",
        "tech-tailwind",
    ),
}

_DB_PACKS = {
    "mssql": ("tech-mssql", "workflow-db-context"),
    "postgresql": ("tech-postgresql", "workflow-db-context"),
    "none": (),
}


def default_packs_for_profile(profile: str) -> list[str]:
    return list(_PROFILE_DEFAULT_PACKS.get(profile, ("workflow-core",)))


def db_packs(db: str) -> list[str]:
    if db not in _DB_PACKS:
        raise ValueError(f"unknown db: {db!r}; expected one of mssql, postgresql, none")
    return list(_DB_PACKS[db])
```

- [ ] **Step 4.3: Run tests — expect pass**

```bash
python3 -m unittest scripts.test_harness.ProfileResolutionTests -v
```

- [ ] **Step 4.4: Add legacy alias resolution to the profile parser**

Find the function in `scripts/harness.py` that parses `--profiles` (look for use of `KNOWN_PROFILES`). Update the validator so that:

- An input matching a `LEGACY_PROFILE_ALIASES` key is silently replaced with the alias target, and a deprecation warning is printed to stderr:

```python
def normalize_profiles(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        if raw in LEGACY_PROFILE_ALIASES:
            target = LEGACY_PROFILE_ALIASES[raw]
            print(
                f"WARN: profile name {raw!r} is deprecated; using {target!r}. "
                f"This alias will be removed in v0.8.",
                file=sys.stderr,
            )
            out.append(target)
        elif raw in KNOWN_PROFILES:
            out.append(raw)
        else:
            raise SystemExit(f"unknown profile: {raw!r}")
    return out
```

Wire this into the existing `--profiles` argument flow. Search for prior validation; replace the inline `if x not in KNOWN_PROFILES` check with a call to `normalize_profiles`.

- [ ] **Step 4.5: Add legacy alias test**

```python
def test_normalize_profiles_handles_legacy_alias(self):
    from scripts import harness as h
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        result = h.normalize_profiles(["dotnet-etl-mssql", "generic"])
    self.assertEqual(result, ["dotnet-etl", "generic"])
    self.assertIn("deprecated", buf.getvalue())
```

Run + expect pass.

- [ ] **Step 4.6: Commit**

```bash
git add scripts/harness.py scripts/test_harness.py
git commit -m "feat(harness): KNOWN_PROFILES, legacy alias, profile/db pack resolution"
```

---

## Task 5: `--db` CLI flag and pack defaulting

**Files:**
- Modify: `scripts/harness.py`

- [ ] **Step 5.1: Failing test**

```python
class DbFlagTests(unittest.TestCase):
    def test_init_with_db_adds_db_packs(self):
        # uses subprocess; place near existing init tests
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            subprocess.run(
                [
                    sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                    "init",
                    "--target", str(target),
                    "--adapters", "roo",
                    "--profiles", "dotnet-etl",
                    "--db", "mssql",
                ],
                check=True,
            )
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertIn("tech-mssql", installed["packs"])
            self.assertIn("workflow-db-context", installed["packs"])

    def test_init_db_none_does_not_add_db_packs(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            subprocess.run(
                [
                    sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                    "init",
                    "--target", str(target),
                    "--adapters", "roo",
                    "--profiles", "dotnet-etl",
                    "--db", "none",
                ],
                check=True,
            )
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertNotIn("tech-mssql", installed["packs"])
            self.assertNotIn("tech-postgresql", installed["packs"])
```

- [ ] **Step 5.2: Add `--db` argument**

Locate the `init` subparser. Add:

```python
init_parser.add_argument(
    "--db",
    choices=("mssql", "postgresql", "none"),
    default=None,
    help="Optional database axis. Ignored when profile is 'generic'.",
)
```

- [ ] **Step 5.3: Pack-list assembly**

Locate where `init` builds the final pack list. Adjust so that when `--packs` is not provided:

```python
profiles_resolved = normalize_profiles(args.profiles or ["generic"])
auto_packs: set[str] = set()
for profile in profiles_resolved:
    auto_packs.update(default_packs_for_profile(profile))

if args.db is not None:
    if profiles_resolved == ["generic"]:
        print("NOTE: --db is ignored for the 'generic' profile.", file=sys.stderr)
    else:
        auto_packs.update(db_packs(args.db))

packs_resolved = sorted(auto_packs) if args.packs is None else parse_packs_arg(args.packs)
```

(Replace whatever shape the existing code uses; preserve `--packs` explicit precedence.)

- [ ] **Step 5.4: Run tests + expect pass**

```bash
python3 -m unittest scripts.test_harness.DbFlagTests -v
python3 -m unittest scripts.test_harness -v
```

- [ ] **Step 5.5: Commit**

```bash
git add scripts/harness.py scripts/test_harness.py
git commit -m "feat(harness): --db flag with mssql/postgresql/none"
```

---

## Task 6: `.roomodes` integration during init/upgrade/uninstall

When `react-web` is installed with adapter `roo` (or `both`), append the `ui-engineer` mode to `.roomodes`. When removed, drop it.

**Files:**
- Modify: `scripts/harness.py` (init and upgrade paths), `scripts/uninstall_harness.py`.
- Reads: `harness/profiles/react-web/modes/ui-engineer.json`.

- [ ] **Step 6.1: Failing test**

```python
class RoomodesProfileSyncTests(unittest.TestCase):
    def test_react_web_install_adds_ui_engineer(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                 "init", "--target", str(target),
                 "--adapters", "roo", "--profiles", "react-web"],
                check=True,
            )
            roomodes = json.loads((target / ".roomodes").read_text(encoding="utf-8"))
            slugs = [m["slug"] for m in roomodes["customModes"]]
            self.assertIn("ui-engineer", slugs)
            self.assertEqual(slugs[:8], list(roomodes_writer.BASE_MODE_SLUGS))

    def test_dotnet_etl_install_does_not_add_ui_engineer(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                 "init", "--target", str(target),
                 "--adapters", "roo", "--profiles", "dotnet-etl"],
                check=True,
            )
            roomodes = json.loads((target / ".roomodes").read_text(encoding="utf-8"))
            slugs = [m["slug"] for m in roomodes["customModes"]]
            self.assertNotIn("ui-engineer", slugs)

    def test_opencode_only_install_does_not_create_roomodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                 "init", "--target", str(target),
                 "--adapters", "opencode", "--profiles", "react-web"],
                check=True,
            )
            self.assertFalse((target / ".roomodes").exists())
```

Run, expect 3 fails (likely because the file is copied verbatim and contains no `ui-engineer` for the first test).

- [ ] **Step 6.2: Implement post-install `.roomodes` sync**

After the manifest copier writes `.roomodes` for a Roo install, call:

```python
def sync_roomodes_profile_modes(target: Path, profiles: list[str]) -> None:
    from scripts.lib import roomodes_writer
    roomodes_path = target / ".roomodes"
    if not roomodes_path.exists():
        return  # opencode-only install; nothing to do
    profile_modes: list[dict] = []
    for profile in profiles:
        modes_dir = REPO_ROOT / "harness/profiles" / profile / "modes"
        if not modes_dir.exists():
            continue
        for mode_file in sorted(modes_dir.glob("*.json")):
            profile_modes.append(json.loads(mode_file.read_text(encoding="utf-8")))
    roomodes_writer.set_profile_modes(roomodes_path, profile_modes)
```

Call this at the end of the `init` flow when `adapter` includes `roo`. Also call from `upgrade` after re-copying files.

- [ ] **Step 6.3: Implement reverse for uninstall**

In `scripts/uninstall_harness.py`, after removing profile-owned manifest entries, recompute the residual profile list from `installed-manifest.json` and call the same sync. If no Roo adapter remains installed, no action is needed (the file is gone).

- [ ] **Step 6.4: Run tests, expect pass**

```bash
python3 -m unittest scripts.test_harness.RoomodesProfileSyncTests -v
```

- [ ] **Step 6.5: Add uninstall test**

```python
def test_uninstall_react_web_removes_ui_engineer(self):
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "proj"
        target.mkdir()
        subprocess.run([sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                        "init", "--target", str(target),
                        "--adapters", "roo", "--profiles", "react-web"], check=True)
        # uninstall just the profile by re-running upgrade with --profiles generic
        subprocess.run([sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                        "upgrade", "--target", str(target),
                        "--profiles", "generic"], check=True)
        roomodes = json.loads((target / ".roomodes").read_text(encoding="utf-8"))
        slugs = [m["slug"] for m in roomodes["customModes"]]
        self.assertNotIn("ui-engineer", slugs)
```

(If the existing `upgrade` command doesn't currently support changing profile set, add `--profiles` re-resolve to it as part of this step.)

Run + expect pass.

- [ ] **Step 6.6: Commit**

```bash
git add scripts/harness.py scripts/uninstall_harness.py scripts/test_harness.py
git commit -m "feat(harness): sync .roomodes profile-modes block on init/upgrade/uninstall"
```

---

## Task 7: OpenCode commands — read profile-rules directory

**Files:**
- Modify: `.opencode/commands/discuss.md`, `plan.md`, `execute.md`, `done.md`

- [ ] **Step 7.1: Failing test**

```python
class OpencodeCommandsProfileRulesTests(unittest.TestCase):
    def test_each_command_references_profile_rules_dir(self):
        for name in ("discuss.md", "plan.md", "execute.md", "done.md"):
            text = (REPO_ROOT / ".opencode/commands" / name).read_text(encoding="utf-8")
            self.assertIn(".opencode/profile-rules/", text, msg=name)
            self.assertIn("alphabetical", text.lower(), msg=name)
```

- [ ] **Step 7.2: Edit all four command files**

Add this paragraph near the top of each file (after the title and one-line summary, before any preflight checklist):

> Before proceeding, read every file under `.opencode/profile-rules/` in alphabetical order, if the directory exists. If it is missing or empty, skip silently.

- [ ] **Step 7.3: Run test + expect pass; commit**

```bash
python3 -m unittest scripts.test_harness.OpencodeCommandsProfileRulesTests -v
git add .opencode/commands/
git commit -m "feat(opencode): commands read .opencode/profile-rules/ at start"
```

---

## Task 8: Installer UX — profile single-select + DB prompt

**Files:**
- Modify: `scripts/install_harness.py`
- Possibly modify: `scripts/test_harness.py` (the existing `resolve_profile_preset` tests reference removed preset names — update them to the new shape, see Step 8.6)

- [ ] **Step 8.1: Failing test for new prompts**

```python
class InstallerInteractiveTests(unittest.TestCase):
    def test_interactive_prompts_for_profile_then_db(self):
        from scripts import install_harness
        prompts: list[str] = []
        answers = iter(["/tmp/example", "roo", "dotnet-etl", "mssql", ""])
        def fake_input(prompt):
            prompts.append(prompt)
            return next(answers)
        # mock prompt_value/prompt_existing_absolute_target via monkey patch:
        with mock.patch("builtins.input", side_effect=fake_input):
            with mock.patch("pathlib.Path.exists", return_value=True):
                with mock.patch("pathlib.Path.is_dir", return_value=True):
                    selection = install_harness.run_interactive_dry_run()
        self.assertEqual(selection["profile"], "dotnet-etl")
        self.assertEqual(selection["db"], "mssql")
        self.assertIn("tech-mssql", selection["packs"])
```

The test requires `install_harness` to expose `run_interactive_dry_run()` that returns the resolved selection without performing an install. Adding this entry point is part of Step 8.2.

- [ ] **Step 8.2: Replace PROFILE_PRESETS with a single profile selector**

In `scripts/install_harness.py`:

```python
# Delete PROFILE_PRESETS entirely.

PROFILE_OPTIONS = (
    ("generic", "Stack-neutral baseline."),
    ("dotnet-etl", ".NET/C# ETL projects."),
    ("python-etl", "Python ETL/data pipeline projects."),
    ("react-web", "React + TypeScript + Tailwind web apps."),
)

DB_OPTIONS = (
    ("mssql", "SQL Server."),
    ("postgresql", "PostgreSQL."),
    ("none", "No database / not applicable."),
)


def prompt_profile() -> str:
    return prompt_choice("Profile", list(PROFILE_OPTIONS), default="generic")


def prompt_db(profile: str) -> str:
    if profile == "generic":
        return "none"
    return prompt_choice("Database", list(DB_OPTIONS), default="none")
```

- [ ] **Step 8.3: Add `run_interactive_dry_run`**

```python
def run_interactive_dry_run() -> dict:
    """Walk the prompts and return the resolved install plan without installing."""
    target = prompt_existing_absolute_target()
    adapter = prompt_choice("Adapter", list(ADAPTER_OPTIONS), default="roo")
    profile = prompt_profile()
    db = prompt_db(profile)
    auto_packs = set(harness.default_packs_for_profile(profile))
    if profile != "generic":
        auto_packs.update(harness.db_packs(db))
    extras = prompt_additional_packs(sorted(auto_packs))
    packs = sorted(auto_packs | set(extras))
    return {
        "target": str(target),
        "adapter": adapter,
        "profile": profile,
        "db": db,
        "packs": packs,
    }
```

Where `prompt_additional_packs` is the existing helper (rename or refactor as needed) that asks "which extra packs do you want", excluding ones already in `auto_packs`. If no such helper exists, add a thin stub that returns `()` for dry-run and is replaced by the real prompt in production.

- [ ] **Step 8.4: Rewrite the existing `main` to call `run_interactive_dry_run` then perform install**

```python
def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.interactive:
        plan = run_interactive_dry_run()
        return harness.run_init(
            target=Path(plan["target"]),
            adapters=plan["adapter"],
            profiles=[plan["profile"]],
            db=plan["db"],
            packs=plan["packs"],
        )
    return harness.run_init(...)  # delegate to non-interactive path as before
```

Adjust `harness.run_init` signature if needed; alternatively shell out to `harness.py init` with the resolved args, which matches the current architecture more closely. Pick whichever the existing code uses.

- [ ] **Step 8.5: Run new tests, expect pass**

```bash
python3 -m unittest scripts.test_harness.InstallerInteractiveTests -v
```

- [ ] **Step 8.6: Update broken preset-era tests**

Find and edit:

```
scripts/test_harness.py:503-505  (references to install_harness.resolve_profile_preset)
scripts/test_harness.py:2789-2790 (README assertion strings)
```

Replace `resolve_profile_preset(...)` references with assertions against the new entry points. For the README assertions, see Task 11 — they will be updated together with the README rewrite.

Run: `python3 -m unittest scripts.test_harness -v` — fix any remaining preset-era failures.

- [ ] **Step 8.7: Commit**

```bash
git add scripts/install_harness.py scripts/test_harness.py
git commit -m "feat(installer): profile single-select + optional DB prompt"
```

---

## Task 9: Upgrade migration

**Files:**
- Modify: `scripts/upgrade_harness.py`, `scripts/harness.py` (whichever owns the `upgrade` command)

- [ ] **Step 9.1: Failing test**

```python
class UpgradeMigrationTests(unittest.TestCase):
    def test_upgrade_migrates_dotnet_etl_mssql_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            (target / ".harness").mkdir()
            (target / ".harness/installed-manifest.json").write_text(json.dumps({
                "version": "v0.6.0",
                "init_options": {
                    "adapters": ["roo"],
                    "profiles": ["dotnet-etl-mssql"],
                    "packs": ["workflow-core", "workflow-etl", "tech-csharp"],
                },
                "profiles": ["dotnet-etl-mssql"],
                "packs": ["workflow-core", "workflow-etl", "tech-csharp"],
            }), encoding="utf-8")
            # Run upgrade.
            subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                 "upgrade", "--target", str(target)],
                check=True,
            )
            installed = json.loads((target / ".harness/installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(installed["init_options"]["profiles"], ["dotnet-etl"])
            self.assertIn("tech-mssql", installed["packs"])
            self.assertIn("workflow-db-context", installed["packs"])
```

- [ ] **Step 9.2: Implement migration**

In the upgrade entry point, before applying the manifest, run:

```python
def migrate_install_state(state: dict) -> dict:
    options = state.setdefault("init_options", {})
    profiles = options.get("profiles", []) or []
    new_profiles: list[str] = []
    added_packs: set[str] = set()
    for p in profiles:
        if p == "dotnet-etl-mssql":
            new_profiles.append("dotnet-etl")
            added_packs.update(("tech-mssql", "workflow-db-context"))
        elif p in LEGACY_PROFILE_ALIASES:
            new_profiles.append(LEGACY_PROFILE_ALIASES[p])
        else:
            new_profiles.append(p)
    if new_profiles != profiles:
        options["profiles"] = new_profiles
        state["profiles"] = new_profiles
    packs = set(state.get("packs", []) or [])
    packs.update(added_packs)
    state["packs"] = sorted(packs)
    options["packs"] = sorted(set(options.get("packs", []) or []) | added_packs)
    return state
```

Apply, write back, then proceed with the normal upgrade.

- [ ] **Step 9.3: Dry-run output**

When `--dry-run` is set, print the migration intent before printing the file plan:

```
MIGRATION:
  profile rename: dotnet-etl-mssql -> dotnet-etl
  packs added: tech-mssql, workflow-db-context
```

- [ ] **Step 9.4: Run test + expect pass**

```bash
python3 -m unittest scripts.test_harness.UpgradeMigrationTests -v
```

- [ ] **Step 9.5: Commit**

```bash
git add scripts/harness.py scripts/upgrade_harness.py scripts/test_harness.py
git commit -m "feat(upgrade): migrate dotnet-etl-mssql installs to dotnet-etl + tech-mssql"
```

---

## Task 10: `check` and `doctor` updates

**Files:**
- Modify: `scripts/harness.py` (check), `scripts/doctor_harness.py` or wherever `doctor` lives.

- [ ] **Step 10.1: Failing test for `check`**

```python
class CheckProfileSyncTests(unittest.TestCase):
    def test_check_fails_when_ui_engineer_present_without_react_web(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj"
            target.mkdir()
            subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                 "init", "--target", str(target),
                 "--adapters", "roo", "--profiles", "react-web"], check=True)
            # remove the profile from manifest but leave ui-engineer in .roomodes
            installed_path = target / ".harness/installed-manifest.json"
            installed = json.loads(installed_path.read_text(encoding="utf-8"))
            installed["init_options"]["profiles"] = ["generic"]
            installed["profiles"] = ["generic"]
            installed_path.write_text(json.dumps(installed), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/harness.py"),
                 "check", "--target", str(target)],
                capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ui-engineer", result.stdout + result.stderr)
```

- [ ] **Step 10.2: Implement check rule**

In the `check` command:

```python
def _check_roomodes_profile_sync(target: Path, installed: dict) -> list[str]:
    from scripts.lib import roomodes_writer
    roomodes_path = target / ".roomodes"
    if not roomodes_path.exists():
        return []
    profile_modes = roomodes_writer.read(roomodes_path).profile_modes
    installed_profiles = set(installed.get("init_options", {}).get("profiles") or [])
    errs: list[str] = []
    profile_mode_owners = {"ui-engineer": "react-web"}
    for mode in profile_modes:
        slug = mode.get("slug")
        owner = profile_mode_owners.get(slug)
        if owner and owner not in installed_profiles:
            errs.append(f".roomodes contains {slug!r} but profile {owner!r} not installed")
    return errs
```

Wire it into the existing check failure aggregator.

- [ ] **Step 10.3: Doctor warning for missing profile-rules read**

In `doctor`:

```python
def _doctor_opencode_profile_rules_line(target: Path) -> list[str]:
    warnings: list[str] = []
    for name in ("discuss.md", "plan.md", "execute.md", "done.md"):
        path = target / ".opencode/commands" / name
        if not path.exists():
            continue
        if ".opencode/profile-rules/" not in path.read_text(encoding="utf-8"):
            warnings.append(f"{path} is missing the profile-rules read instruction")
    return warnings
```

- [ ] **Step 10.4: Run tests + expect pass; commit**

```bash
python3 -m unittest scripts.test_harness.CheckProfileSyncTests -v
git add scripts/harness.py scripts/doctor_harness.py scripts/test_harness.py
git commit -m "feat(check/doctor): profile-mode and opencode-rules sync checks"
```

---

## Task 11: README and profile docs

**Files:**
- Modify: `README.md`
- Modify: `harness/skeleton/clean/README.md` (target README template) if it mentions presets.
- Profile docs `docs/profiles/*.md` are generated by manifest install — no manual edits.

- [ ] **Step 11.1: Update preset table in `README.md`**

Find the "Interactive profile presets" paragraph (around line 66-72 in current README) and replace with:

```markdown
The installer accepts a single profile (`generic`, `dotnet-etl`, `python-etl`,
`react-web`). When the profile is not `generic`, the installer asks which
database to wire in (`mssql`, `postgresql`, `none`). Profile names are also
valid values for `scripts/harness.py init --profiles`. The `dotnet-etl-mssql`
profile is deprecated; existing installs upgrade automatically to `dotnet-etl`
plus `tech-mssql`.

- `generic`: stack-neutral planning guardrails plus `workflow-core`.
- `dotnet-etl`: .NET/C# ETL packs. Pair with `--db` if a database engine is used.
- `python-etl`: Python ETL/data pipeline packs.
- `react-web`: React, TypeScript, and Tailwind web workflow packs. Adds the
  `ui-engineer` Roo mode when the Roo adapter is installed.
```

- [ ] **Step 11.2: Update the scenario table**

Replace the rows that say `installer preset dotnet-etl`, `python-etl`, etc., with the unified profile names. Add a row documenting `--db`.

- [ ] **Step 11.3: Add `ui-engineer` documentation under "Skill packs" → adjacent "Modes" section**

Insert a short section above "Skill packs":

```markdown
### Roo modes

The harness ships 8 base modes (`orchestrator`, `architect`, `tdd-code`,
`diagnose`, `review`, `docs-issues`, `ops-observability`, `harness-maintainer`).
Profile-contributed modes are added on top:

- `ui-engineer` (added by `react-web` profile when Roo is installed): browser-
  first UI implementation. Drops out automatically when the profile is removed.
```

- [ ] **Step 11.4: Update the assertion strings in `scripts/test_harness.py:2789-2790`**

The previous assertions check that the README mentions `installer preset 'dotnet-etl'` etc. Update them to check the new sentences instead:

```python
self.assertIn("`dotnet-etl`", readme_text)
self.assertIn("`react-web`", readme_text)
self.assertIn("`--db`", readme_text)
```

- [ ] **Step 11.5: Commit**

```bash
git add README.md scripts/test_harness.py
git commit -m "docs: README reflects unified profile model and --db flag"
```

---

## Task 12: Release smoke + final harness checks

**Files:**
- Modify: `scripts/release_smoke_test.py`

- [ ] **Step 12.1: Update smoke matrix**

Replace `dotnet-etl-mssql` matrix entries with `dotnet-etl` and a `--db mssql` flag. Add a `react-web` scenario asserting that `.roomodes` contains `ui-engineer` and `.roo/rules-tdd-code/react-web-ui-tdd.md` exists.

Concrete diff sketch:

```python
SCENARIOS = [
    {"name": "generic-roo", "adapters": "roo", "profiles": "generic", "db": None,
     "expect_present": [".roo/README.md"],
     "expect_absent":  [".opencode/profile-rules"]},
    {"name": "dotnet-etl-mssql-both", "adapters": "both", "profiles": "dotnet-etl", "db": "mssql",
     "expect_present": [".roo/rules-tdd-code/dotnet-etl-etl-tdd.md",
                        ".opencode/profile-rules/dotnet-etl-etl-tdd.md"]},
    {"name": "python-etl-opencode-pg", "adapters": "opencode", "profiles": "python-etl", "db": "postgresql",
     "expect_present": [".opencode/profile-rules/python-etl-etl-tdd.md"],
     "expect_absent":  [".roo/rules-tdd-code/python-etl-etl-tdd.md"]},
    {"name": "react-web-roo-nodb", "adapters": "roo", "profiles": "react-web", "db": "none",
     "expect_present": [".roo/rules-ui-engineer/react-web-ui-engineer-extras.md",
                        ".roomodes"]},
]
```

Adjust the existing iteration loop to pass `--db` when the scenario sets one.

- [ ] **Step 12.2: Run smoke**

```bash
python3 scripts/release_smoke_test.py
```

Expected: all scenarios pass.

- [ ] **Step 12.3: Full test suite**

```bash
python3 -m unittest scripts/test_harness.py
python3 scripts/harness.py check
python3 scripts/harness.py check --worktree
python3 scripts/release_smoke_test.py
```

Fix anything that breaks. Re-run until green.

- [ ] **Step 12.4: Commit**

```bash
git add scripts/release_smoke_test.py
git commit -m "test(release): cover new profile/db matrix incl. react-web ui-engineer"
```

---

## Task 13: Final verification + push readiness

- [ ] **Step 13.1: Self-check ramp**

```bash
python3 -m unittest scripts/test_harness.py
python3 scripts/harness.py check
python3 scripts/harness.py check --worktree
python3 scripts/release_smoke_test.py
python3 scripts/harness.py release-check --expected-version v0.6.0
```

- [ ] **Step 13.2: Manual sanity install on a scratch dir**

```bash
mkdir -p /tmp/smoke-profile && python3 scripts/harness.py init --target /tmp/smoke-profile --adapters both --profiles react-web --db none
ls /tmp/smoke-profile/.roo/rules-ui-engineer/
ls /tmp/smoke-profile/.opencode/profile-rules/
grep -c '"slug": "ui-engineer"' /tmp/smoke-profile/.roomodes
```

Expected: rule files present in both locations; one `ui-engineer` entry in `.roomodes`.

- [ ] **Step 13.3: Push readiness audit**

Re-read the spec at `docs/superpowers/specs/2026-05-16-profile-modes-rules-design.md` and confirm every Files-changed item in the spec is reflected in commits. Note in the PR description any spec "Open question" left unresolved (acceptable; resolve later or in follow-up).

- [ ] **Step 13.4: Open PR**

PR title: `feat(harness): unify profile + preset, add profile-scoped rules and ui-engineer mode`. Body links the spec doc.

---

## Self-Review notes

- Each augment rule text content is concrete (Steps 2.2–2.10) — no "TBD".
- The `ui-engineer` mode JSON, the manifest entries, and the `--db` resolver code are all written out fully.
- Task 8 leaves the precise call shape of `harness.run_init` flexible because the existing code path differs slightly between the interactive installer and the CLI; the engineer should match whichever pattern is already in place rather than introducing a new one.
- The OpenCode profile-rules read instruction is the same wording across all four commands (Step 7.2) and the test in Step 7.1 verifies both the path string and the "alphabetical" keyword to catch lazy paraphrases.
- Legacy alias migration is implemented twice — once in `normalize_profiles` (CLI input) and once in `migrate_install_state` (upgrade-time stored state). Both are needed.
- `react-web/modes/ui-engineer.json` and the rule file `ui-engineer-extras.md` cross-reference each other only by mode slug; the manifest entry places the rule under `.roo/rules-ui-engineer/` to match.
