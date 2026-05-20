# Planning-Doc Dialect Grammar

This document is the authoritative reference for the planning-document dialect
used by the general low-reasoning agent harness. It answers one question:
**how do you write or edit `.planning/**` files without triggering a drift
warning from `python3 scripts/project_dashboard.py --check`?**

---

## 1. Why a Dialect Exists; What the Grammar Module Owns

The harness cross-validates three sources of truth:

| Source | Role |
|---|---|
| `.planning/STATE.md` | Durable narrative — current phase, active checkpoint, decisions |
| `.planning/ROADMAP.md` | Canonical list of phases; completion marks |
| `.planning/phases/<folder>/` | Per-phase documents and plans |

Keeping those three sources consistent is the job of
`scripts/lib/planning_grammar.py`. That module owns:

- The regex primitives that parse phase folder names, STATE lines, ROADMAP
  bullets, and planning-doc front-matter.
- The `PLANNING_DOC_SCHEMA_VERSION` constant.
- The heading-match logic used to navigate within planning docs.

**What the grammar module does NOT own.** The live execute gate lives in
`.scratch/phase-state.json` and is governed by its own `state_schema_version`
field and schema. The two version numbers are unrelated. See
[ADR-001](adr/2026-05-16-hardening-bundle.md) for the `state_schema_version`
history and `.scratch/phase-state.json` field ownership.

---

## 2. Required Planning Files and Per-File Grammar Rules

### 2.1 `.planning/STATE.md`

**Required fields** (YAML front-matter at file top):

```
planning_doc_schema_version: 1
progress:
  total_phases: 2
  completed_phases: 1
  percent: 50
```

**Positive example** (real `.planning/STATE.md` excerpt):

```markdown
---
planning_doc_schema_version: 1
progress:
  total_phases: 2
  completed_phases: 1
  percent: 50
---

# STATE - General Low-Reasoning Agent Harness

## Current Position

- **Phase**: 2 - v0.8.0 Minimal Workflow Release.

## Active Checkpoint

- **Checkpoint**: CP-02-02 - contract and behavior.
- **Checkpoint file**: `.planning/phases/02-v0.8.0-minimal-workflow/02-CHECKPOINTS.md`.
```

**Negative example — unsupported schema version** → `planning_doc_schema_version_unsupported` (**blocking**):

```markdown
---
planning_doc_schema_version: 99      # ← only version 1 is supported
progress:
  total_phases: 2
  completed_phases: 1
  percent: 50
---
```

`planning_doc_schema_version_unsupported` is raised by
`extract_planning_doc_schema_version()` and treated as blocking by
`--check`.

**Negative example — missing schema version line** → `planning_doc_schema_version_missing` (**warning**, non-blocking):

```markdown
---
progress:
  total_phases: 2       # ← planning_doc_schema_version absent from front-matter
  completed_phases: 1
  percent: 50
---
```

### 2.2 `.planning/ROADMAP.md`

Each phase must appear as a bullet in the `## Phases` section using the
canonical format matched by `ROADMAP_BULLET_RE`:

```
- [x] **Phase N[a-z]?: Title** - Optional summary sentence.
```

**Positive example** (real `.planning/ROADMAP.md` excerpt):

```markdown
## Phases

- [x] **Phase 1: Generalized Harness Release** - Publish the stack-neutral harness with OpenCode compatibility and composable workflow skill packs.
- [ ] **Phase 2: v0.8.0 Minimal Workflow Release** - Ship the four-command navigator workflow while preserving approval, adapter, JSON, release, and security boundaries.
```

**Negative example — total_phases mismatch** → `roadmap_total_phases_drift` (**blocking**):

```markdown
## Phases

- [x] **Phase 1: Generalized Harness Release** - Description.
- [ ] **Phase 2: v0.8.0 Minimal Workflow Release** - Description.
- [ ] **Phase 3: Future Work** - Description.
```

```markdown
# STATE
progress:
  total_phases: 2       # ← STATE says 2 but ROADMAP now lists 3 phases
```

STATE's `progress.total_phases` must equal the number of bullets in
ROADMAP's `## Phases` section.

### 2.3 `.planning/phases/<folder>/`

Each subfolder under `.planning/phases/` is a phase folder. Grammar rules:

1. The folder name must satisfy `PHASE_FOLDER_REGEX` (see §8).
2. Each phase folder must correspond to a phase listed in `ROADMAP.md`.

**Positive example:**

```
.planning/phases/
  01-generalized-harness-release/
  02-v0.8.0-minimal-workflow/
  02b-hardening/
```

`02b-hardening` is a valid name (`02b` matches `\d+[a-z]?`). However, it
also must be listed in ROADMAP — see the negative examples below.

**Negative example — folder not in ROADMAP** → `phase_folder_not_in_roadmap` (**warning**, non-blocking):

```
.planning/phases/
  02b-hardening/          # ← exists on disk but ROADMAP has no "Phase 2b" bullet
```

Fix: add `- [ ] **Phase 2b: Hardening** - Description.` to ROADMAP, or move
the folder to `.planning/archive/` if the phase has already shipped.

**Negative example — folder name violates grammar** → `phase_folder_grammar_invalid` (**blocking**):

```
.planning/phases/
  scratch-junk/           # ← no leading digits; does not match NN[a-z]?-slug
```

---

## 3. Phase Folder Name Grammar

### Folder name pattern

```
NN[a-z]?-slug
```

Where:

- `NN` is one or more decimal digits (zero-padded to at least two when
  stored canonically, e.g. `01`, `02`, `02b`).
- `[a-z]?` is an optional single lowercase letter suffix (for sub-phases such
  as `02b`).
- `-slug` is a hyphen followed by any non-slash characters describing the
  phase (e.g. `-v0.8.0-minimal-workflow`).

The canonical regex is `PHASE_FOLDER_REGEX` in
`scripts/lib/planning_grammar.py`:

```python
PHASE_FOLDER_REGEX = re.compile(r"(?:^|/)(?P<id>\d+[a-z]?)-[^/]+$")
```

Examples of valid folder names:

| Folder | Canonical id |
|---|---|
| `01-generalized-harness-release` | `01` |
| `02-v0.8.0-minimal-workflow` | `02` |
| `02b-hardening` | `02b` |

### Nested plan files

Phase-level plan files live under a `plans/` subdirectory and must follow
the `*-PLAN.md` suffix convention:

```
.planning/phases/02b-hardening/plans/
  02b-01-T0-A-PLAN.md
  02b-02-T0-1-PLAN.md
```

The dashboard loader (`load_phase_documents` in
`scripts/lib/project_dashboard/core.py`) picks up files matching
`plans/*-PLAN.md` within each phase folder.

### Archived phases

Phases that have shipped and whose folders are no longer listed in ROADMAP
should be moved to `.planning/archive/`. Folders under `.planning/archive/`
are not scanned by the dashboard and do not trigger
`phase_folder_not_in_roadmap`.

---

## 4. `planning_doc_schema_version: 1`

The front-matter key `planning_doc_schema_version` (integer) appears in
`.planning/STATE.md` (and optionally other top-level planning docs). The only
supported value is **`1`**.

```markdown
---
planning_doc_schema_version: 1
progress:
  total_phases: 2
  completed_phases: 1
  percent: 50
---
```

This version is **completely separate** from `.scratch/phase-state.json`'s
`state_schema_version` field.

| Field | File | Governs |
|---|---|---|
| `planning_doc_schema_version` | `.planning/STATE.md` | Planning-doc dialect version |
| `state_schema_version` | `.scratch/phase-state.json` | Live gate schema version |

Cross-reference: `state_schema_version` history is documented in
[ADR-001](adr/2026-05-16-hardening-bundle.md). The current `state_schema_version`
is `2` (bumped by ADR-001 when `approved` was dropped from the `done` branch).

The grammar constant is:

```python
PLANNING_DOC_SCHEMA_VERSION = 1  # in scripts/lib/planning_grammar.py
```

Parsing and validation are performed by
`extract_planning_doc_schema_version(text)` in the same module.

---

## 5. Heading Match Policy

The harness resolves heading references to planning-doc sections using the
`heading_matches(heading, target)` function in `scripts/lib/planning_grammar.py`.

A heading is considered to match a target when either of the following is true
(case-insensitive):

1. **Exact match**: `heading.strip().lower() == target.strip().lower()`
2. **Prefix match**: `heading` begins with `target` and the next character
   starts one of the recognized separator sequences:

| Separator | Example |
|---|---|
| `' '` (space) | `"Current Position Notes"` matches target `"Current Position"` |
| `' -'` | `"Phase 2 - v0.8.0"` matches target `"Phase 2"` |
| `' —'` | `"Phase 2 — v0.8.0"` matches target `"Phase 2"` |
| `' /'` | `"State / Summary"` matches target `"State"` |
| `' ('` | `"Phase 2 (WIP)"` matches target `"Phase 2"` |
| `' {'` | `"Phase 2 {draft}"` matches target `"Phase 2"` |

The separator list is `_HEADING_SEPARATORS` in `planning_grammar.py`:

```python
_HEADING_SEPARATORS = (" ", " -", " —", " /", " (", " {")
```

This means heading-targeted reads like `## Current Position` will match
`## Current Position - Updated 2026-05-20` without requiring an exact title.

---

## 6. Exit Code `EXIT_PLANNING_DRIFT = 12`

`python3 scripts/project_dashboard.py --check` exits with **12** when any
blocking warning is present.

```python
# scripts/lib/exitcodes.py
EXIT_PLANNING_DRIFT = 12  # dashboard --check detected drift between planning docs and live gate
```

The check command emits JSON to stdout:

```json
{
  "status": "drift",
  "warnings": [
    {
      "code": "state_checkpoint_drift",
      "severity": "blocking",
      "message": "STATE active checkpoint differs from phase-state current_checkpoint: ...",
      "paths": []
    }
  ]
}
```

Exit 0 (`EXIT_OK`) means all warnings are non-blocking (severity `"warning"`).

**Warning severity summary:**

| Warning code | Severity | Exits 12? |
|---|---|---|
| `phase_folder_grammar_invalid` | blocking | yes |
| `state_checkpoint_drift` | blocking | yes |
| `roadmap_total_phases_drift` | blocking | yes |
| `planning_doc_schema_version_unsupported` | blocking | yes |
| `phase_folder_not_in_roadmap` | warning | no |
| `planning_doc_schema_version_missing` | warning | no |

---

## 7. Local Validation

To validate planning docs locally before pushing:

```bash
python3 scripts/project_dashboard.py --check
```

The command prints JSON and exits 0 on clean or non-blocking warnings, 12 on
any blocking drift.

To read the full dashboard output (HTML), omit `--check`:

```bash
python3 scripts/project_dashboard.py
# output: .scratch/reports/project-dashboard.html
```

The harness `check` subcommand also runs the dashboard check internally:

```bash
python3 scripts/harness.py check
```

If `--check` exits 12, fix the drift in the relevant planning file before
pushing. Blocking warning messages identify which files and which fields are
inconsistent.

---

## 8. Grammar Constant Reference Table

All constants and regexes live in `scripts/lib/planning_grammar.py`.

| Constant | Type | Purpose |
|---|---|---|
| `PHASE_FOLDER_REGEX` | `re.Pattern` | Validates phase folder names; captures `id` group (`\d+[a-z]?`). Full pattern: `(?:^|/)(?P<id>\d+[a-z]?)-[^/]+$` |
| `STATE_PHASE_RE` | `re.Pattern` | Parses the `- **Phase**: N - Title.` line in STATE.md; captures `number` and `title` groups |
| `STATE_CHECKPOINT_RE` | `re.Pattern` | Parses the `- **Checkpoint**: CP-NN-NN - Title.` line in STATE.md; captures `id` and `title` groups |
| `ROADMAP_BULLET_RE` | `re.Pattern` | Parses `- [x] **Phase N: Title** - Summary` bullets in ROADMAP.md; captures `mark`, `number`, `title`, `summary` groups |
| `PLANNING_DOC_SCHEMA_VERSION` | `int` | The only accepted value of `planning_doc_schema_version` in STATE.md front-matter; currently `1` |

### Quick grep targets

```bash
# Find all places that reference planning grammar constants:
grep -r "PHASE_FOLDER_REGEX\|STATE_PHASE_RE\|STATE_CHECKPOINT_RE\|ROADMAP_BULLET_RE\|PLANNING_DOC_SCHEMA_VERSION" scripts/
```

---

*Cross-reference: `docs/phase-gate-harness.md` covers the live gate
(`.scratch/phase-state.json`). `AGENTS.md` §Planning State covers when to
read planning docs vs. the live gate.*
