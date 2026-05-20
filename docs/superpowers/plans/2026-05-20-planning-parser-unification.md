# Planning Parser Unification Implementation Plan (v1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Revision history

- **v0 → v1 (2026-05-20):** Reconciled findings from parallel codex (gpt-default) + Opus adversarial reviews. Both reviewers independently flagged 7 CRIT / 10 HIGH issues with strong overlap. Major v1 changes:
  1. **Field rename to avoid collision.** v0 added `state_schema_version: 2` to `.planning/STATE.md` frontmatter. That key is already the contract field for `.scratch/phase-state.json` enforced by `scripts/lib/check.py:462`, `scripts/lib/phase_cli.py:120`, `scripts/lib/state_migrate.py`, `scripts/lib/manifest_v2.py`, and `scripts/lib/smoke_lifecycle.py:599`. **v1 renames the STATE.md field to `planning_doc_schema_version` and uses `1` as the initial value** so the two namespaces never alias.
  2. **Dedicated exit code.** v0 used `2` for dashboard `--check` drift. `scripts/lib/exitcodes.py:16` already binds `EXIT_INVALID_TRANSITION = 2`. **v1 introduces `EXIT_PLANNING_DRIFT = 12` in `exitcodes.py`** (slot currently free) and routes `--check` through it.
  3. **The "02b phantom" is NOT phantom.** v0.9.3 has shipped (`git tag v0.9.3` present, commit `21258e8`), `CHANGELOG.md` confirms 02b hardening shipped under v0.7.0, but `.planning/ROADMAP.md` still lists only Phase 1 and Phase 2 and `.planning/STATE.md` still names Phase 2 v0.8.0 as the active phase. **v1 does NOT silence the warning** — it upgrades grammar recognition for `02b` so the warning becomes an actionable, grammar-aware "phase folder exists but is missing from ROADMAP; add it or move to `.planning/archive/`" message. The ROADMAP / STATE reconciliation itself is OUT OF SCOPE and tracked as a follow-up plan.
  4. **Heading matching is prefix-with-separator, not strict exact.** v0's strict exact match broke real headings like `# CONCERNS - General Harness` (in `.planning/codebase/CONCERNS.md`) which the dashboard already reads via `parse_section_bullets(concerns_text, "CONCERNS")`. **v1 accepts heading text whose normalized form equals the target OR begins with `target` followed by a separator (` `, ` -`, ` —`, ` /`, ` (`).** A real-file regression test pins this against `PROJECT.md`, `CONCERNS.md`, and `STATE.md`.
  5. **Adapter for `parse_roadmap_phases`.** v0 deleted `core.parse_roadmap_phases` but the dashboard renderer (`renderer.py:282`, `:295`, `:322`) still consumes `RoadmapPhase` objects. **v1 keeps the public function, adds a `phase_id` field to `RoadmapPhase`, and the body delegates to `parse_roadmap_phase_bullets` from the grammar module** — the dataclass contract holds.
  6. **`StateSchemaVersionError` subclasses `ProjectionError`.** v0 raised an unrelated exception that `core.load_dashboard_data` would not catch, crashing dashboard generation. **v1 makes the new error a `ProjectionError` subclass** so the existing `try / except ProjectionError` at `core.py:158` continues to work as a single funnel.
  7. **Structured `DashboardWarning` type from the start.** v0 left dashboard warnings as free-text strings and added a hand-wavy `_warning_code` extractor for `--check`. v1 introduces `DashboardWarning(code, severity, message, paths)` as the single warning carrier; `--check` and renderer both consume the structured type.
  8. **Slice 5 STATE.md edit guarded.** v0 used a blind string-replace template. **v1 reads STATE.md, detects existing schema-version key, performs anchored insert under the frontmatter top, refuses if the file does not start with `---`.** No second mutation if the field is already present.
  9. **Shared fixture factory.** v0 had three near-duplicate inline fixtures across Slices 2.1, 3.1, 8.1. **v1 introduces `tests/_helpers/planning_repo.py::make_minimal_planning_repo(tmp_path, **overrides)`** that builds a valid baseline (STATE + ROADMAP + phase folder + phase-state.json with all `check_phase_state_semantics`-required keys) and returns it; per-test variation goes through kwargs.
  10. **Slice 0 baseline command corrected.** v0 invoked `python3 scripts/show_phase_status.py --format json` — that flag does not exist (script only accepts `--root`). v1 drops the flag; the script already prints JSON.
  11. **Import path policy decision recorded.** Existing dashboard tests use `from lib.project_dashboard import core` (no `scripts.` prefix; pytest auto-injects scripts/ into sys.path). Existing `tests/`-dir tests use `from scripts.lib import X`. **v1 keeps the convention split: tests under `scripts/test_*.py` use `from lib.X import ...`; tests under `tests/test_*.py` use `from scripts.lib.X import ...`.** No production import migration.
  12. **Canonical vs display phase IDs.** v1 makes `phase_id_from_folder` return the canonical id (`02b`, leading zero preserved) and `normalize_phase_id` is renamed to `display_phase_id` and is documented as **presentation-only**. All comparisons, dict keys, set membership use canonical IDs.
  13. **`load_phase_state` failure path skips dependent checks.** When phase-state.json is malformed, the new tuple return causes `check_consistency` to skip phase-state-derived sub-checks (state_path / plan_path / checkpoint_path existence checks) so we don't emit cascading misleading warnings.
  14. **Slice 8.2 (`harness check` integration) becomes mandatory, not optional.** Without it, parser drift can ship outside the dashboard's own test surface. The optional/required distinction was the v0 escape hatch.

Open questions left intentionally for the executing engineer: see "Open questions" section at the end.

---

**Status:** v1 — ready for execution; bar for further revision is concrete blocker not yet listed.

**Goal:** Collapse the two competing planning-doc parsers (one in `scripts/lib/project_dashboard/core.py`, one in `scripts/lib/planning_status.py`) into a single shared grammar; emit grammar-aware, structured, actionable warnings; introduce a CI-friendly `--check` mode with a dedicated exit code; document the dialect; **do not silence the v0.9.3-era ROADMAP staleness signal — surface it as an explicit follow-up.**

**Architecture:**
1. New `scripts/lib/planning_grammar.py` owns every regex and dataclass for planning-doc parsing (frontmatter, STATE phase/checkpoint, ROADMAP bullet, phase-folder name, schema version, heading normalizer).
2. `planning_status.py` consumes the grammar module for its primitives (no more inline regex).
3. `project_dashboard/core.py` consumes `PlanningProjection` for every cross-checked field, consumes `parse_roadmap_phase_bullets` via a thin adapter that produces `RoadmapPhase` (adding a new `phase_id` field — backwards-compatible because `phase_id` is a new attribute, not a rename).
4. New structured `DashboardWarning(code, severity, message, paths)` replaces the free-text strings in `DashboardData.warnings`.
5. New `EXIT_PLANNING_DRIFT = 12` in `exitcodes.py`. Dashboard `--check` returns `EXIT_OK` on no drift, `EXIT_PLANNING_DRIFT` on any blocking warning. Non-blocking warnings (e.g. `planning_doc_schema_version_missing`) do not flip the exit code.
6. `harness check` (in `scripts/lib/check.py`) gains a mandatory sub-check that invokes the dashboard projection and propagates `EXIT_PLANNING_DRIFT` into its aggregate failure list.
7. `.planning/STATE.md` gains `planning_doc_schema_version: 1` frontmatter.
8. `docs/planning-grammar.md` formally documents the dialect with positive + negative real-repo examples.

**Tech Stack:** Python 3.11+, pytest, existing dashboard server (`scripts/lib/project_dashboard/server.py`).

**Spec:** None; this plan is the spec.

---

## File structure

**New:**
- `scripts/lib/planning_grammar.py`
- `tests/_helpers/__init__.py`, `tests/_helpers/planning_repo.py`
- `tests/test_planning_grammar.py`
- `tests/test_planning_grammar_real_files.py` (real-repo regression)
- `docs/planning-grammar.md`

**Modified:**
- `scripts/lib/exitcodes.py` — add `EXIT_PLANNING_DRIFT = 12`.
- `scripts/lib/planning_status.py` — delegate primitives to grammar; introduce `StateSchemaVersionError(ProjectionError)`; widen letter-suffix support in CP and phase regexes; expand `_warnings()` signature to receive `state_text`.
- `scripts/lib/project_dashboard/models.py` — add `phase_id: str = ""` field to `RoadmapPhase`; add `DashboardWarning` dataclass; change `DashboardData.warnings` from `list[str]` to `list[DashboardWarning]`.
- `scripts/lib/project_dashboard/core.py` — remove duplicate `parse_frontmatter`, `parse_state_summary` phase/checkpoint regex internals (delegate); `parse_roadmap_phases` keeps signature but delegates; `parse_section_*` use grammar's prefix-with-separator matcher; `load_phase_state` returns `(dict, DashboardWarning | None)`; `check_consistency` skips phase-state-dependent sub-checks when load failed; phase-folder consistency uses grammar phase IDs; nested `plans/*-PLAN.md` glob; emit structured warnings.
- `scripts/lib/project_dashboard/renderer.py` — consume `RoadmapPhase.phase_id` (display prefix); render structured warnings.
- `scripts/lib/check.py` — add mandatory dashboard-projection drift sub-check.
- `scripts/project_dashboard.py` — `--check` flag.
- `.planning/STATE.md` — add `planning_doc_schema_version: 1` line under existing frontmatter (no other change).
- `AGENTS.md` — link to `docs/planning-grammar.md`.

---

## Slice 0 — Pre-flight

### Task 0.1: Capture baseline + decide reserved EXIT code is unused

**Files:** none modified.

- [ ] **Step 1: Capture dashboard baseline**

Run: `python3 scripts/project_dashboard.py --output /tmp/baseline-dashboard.html 2>/tmp/baseline-dashboard-warnings.txt; cat /tmp/baseline-dashboard-warnings.txt`
Expected stderr contains exactly: `warning: Phase folder is present but not listed in ROADMAP: .planning/phases/02b-hardening` (and possibly missing core-document warnings; record full file). If it does NOT contain this 02b warning, stop and report — the repo state has drifted from what this plan was authored against.

- [ ] **Step 2: Capture projection baseline**

Run: `python3 scripts/show_phase_status.py > /tmp/baseline-projection.json`
(Script already emits JSON; no `--format` flag exists.)

- [ ] **Step 3: Run existing dashboard + show-phase-status tests green**

Run: `python3 -m pytest scripts/test_project_dashboard.py scripts/test_show_phase_status.py -q`
Expected: PASS. If any failure, stop.

- [ ] **Step 4: Verify exit code 12 is currently unused**

Run: `grep -nE "= 12\b|EXIT_.*= 12" scripts/lib/exitcodes.py`
Expected: zero matches. If a downstream commit between plan authoring and execution has claimed 12, pick the next free code from this lookup and update every appearance of `12` in this plan to that value.

- [ ] **Step 5: Commit baseline snapshots**

```bash
mkdir -p .scratch/parser-unification-baseline
cp /tmp/baseline-dashboard.html /tmp/baseline-dashboard-warnings.txt /tmp/baseline-projection.json .scratch/parser-unification-baseline/
git add .scratch/parser-unification-baseline
git commit -m "chore: capture baseline before planning-parser unification"
```

### Task 0.2: Reserve `EXIT_PLANNING_DRIFT = 12`

**Files:**
- Modify: `scripts/lib/exitcodes.py`
- Modify: `tests/test_exitcodes_symbols.py`

- [ ] **Step 1: Read existing exitcodes.py to find the right insertion point**

Run: `grep -n "EXIT_TIMESTAMP_OUT_OF_RANGE\|EXIT_WINDOWS_CONTAINMENT_DEGRADED" scripts/lib/exitcodes.py`
Insert between code 8 and code 11.

- [ ] **Step 2: Add a failing test asserting the symbol exists with value 12**

```python
# append to tests/test_exitcodes_symbols.py
def test_exit_planning_drift_is_12():
    from scripts.lib import exitcodes
    assert exitcodes.EXIT_PLANNING_DRIFT == 12
```

- [ ] **Step 3: Run, expect failure**

Run: `python3 -m pytest tests/test_exitcodes_symbols.py::test_exit_planning_drift_is_12 -q`
Expected: AttributeError.

- [ ] **Step 4: Add the constant**

```python
# scripts/lib/exitcodes.py — insert after EXIT_TIMESTAMP_OUT_OF_RANGE = 8
EXIT_PLANNING_DRIFT = 12  # dashboard --check detected drift between planning docs and live gate
```

- [ ] **Step 5: Verify green**

Run: `python3 -m pytest tests/test_exitcodes_symbols.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/exitcodes.py tests/test_exitcodes_symbols.py
git commit -m "feat(exitcodes): reserve EXIT_PLANNING_DRIFT=12 for dashboard drift"
```

---

## Slice 1 — Shared grammar module

### Task 1.1: Frontmatter parser + module skeleton

**Files:**
- Create: `scripts/lib/planning_grammar.py`
- Create: `tests/test_planning_grammar.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_planning_grammar.py
import pytest
from scripts.lib.planning_grammar import parse_frontmatter


def test_parse_frontmatter_flat_keys():
    text = "---\nfoo: bar\nbaz: qux\n---\nbody\n"
    assert parse_frontmatter(text) == {"foo": "bar", "baz": "qux"}


def test_parse_frontmatter_nested_dotted_keys():
    text = "---\nprogress:\n  percent: 50\n  total_phases: 2\n---\n"
    fm = parse_frontmatter(text)
    assert fm["progress.percent"] == "50"
    assert fm["progress.total_phases"] == "2"


def test_parse_frontmatter_value_with_colon_preserved():
    assert parse_frontmatter("---\nurl: https://example.com/foo\n---\n")["url"] == "https://example.com/foo"


def test_parse_frontmatter_no_frontmatter_returns_empty():
    assert parse_frontmatter("# Title\n") == {}
```

- [ ] **Step 2: Run, expect failure**

Run: `python3 -m pytest tests/test_planning_grammar.py -q`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# scripts/lib/planning_grammar.py
"""Shared planning-document grammar primitives.

Single source of truth for parsing `.planning/STATE.md`, `ROADMAP.md`,
phase folders, and related docs. Both `planning_status.py` and the
dashboard depend on this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    values: dict[str, str] = {}
    parents: list[tuple[int, str]] = []
    for line in text.splitlines()[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        key, sep, value = line.strip().partition(":")
        if not sep:
            continue
        while parents and parents[-1][0] >= indent:
            parents.pop()
        clean = value.strip().strip('"').strip("'")
        full = ".".join([p[1] for p in parents] + [key.strip()])
        if clean:
            values[full] = clean
        else:
            parents.append((indent, key.strip()))
    return values
```

- [ ] **Step 4: Verify green**

Run: `python3 -m pytest tests/test_planning_grammar.py -q` → 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/planning_grammar.py tests/test_planning_grammar.py
git commit -m "feat(planning): grammar module with frontmatter primitive"
```

### Task 1.2: Phase-folder grammar (canonical + display)

**Files:**
- Modify: `scripts/lib/planning_grammar.py`
- Modify: `tests/test_planning_grammar.py`

- [ ] **Step 1: Failing tests**

```python
from scripts.lib.planning_grammar import (
    PHASE_FOLDER_REGEX,
    canonical_phase_id,
    display_phase_id,
)


def test_canonical_phase_id_plain_numeric():
    assert canonical_phase_id(".planning/phases/02-foo") == "02"


def test_canonical_phase_id_letter_suffix():
    assert canonical_phase_id(".planning/phases/02b-hardening") == "02b"


def test_canonical_phase_id_two_digit():
    assert canonical_phase_id(".planning/phases/10-release") == "10"


def test_canonical_phase_id_non_phase_folder_returns_empty():
    assert canonical_phase_id(".planning/phases/scratch-junk") == ""


def test_canonical_phase_id_no_slash_just_folder_name():
    assert canonical_phase_id("02c-extra") == "02c"


def test_display_phase_id_strips_leading_zero():
    assert display_phase_id("02b") == "2b"
    assert display_phase_id("02") == "2"
    assert display_phase_id("10") == "10"
    assert display_phase_id("") == ""


def test_display_phase_id_non_digit_input_returns_input():
    assert display_phase_id("xy") == "xy"
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Implement**

```python
# append to scripts/lib/planning_grammar.py
PHASE_FOLDER_REGEX = re.compile(r"(?:^|/)(?P<id>\d+[a-z]?)-[^/]+$")


def canonical_phase_id(folder: str) -> str:
    """Return the canonical phase id (leading zero preserved) from a folder name or path."""
    match = PHASE_FOLDER_REGEX.search(folder)
    if not match:
        return ""
    raw = match.group("id")
    digits_match = re.match(r"\d+", raw)
    if not digits_match:
        return ""
    digits = digits_match.group(0)
    suffix = raw[len(digits):]
    return digits.zfill(2) + suffix


def display_phase_id(phase_id: str) -> str:
    """Return the human-display form (leading zero stripped). Presentation-only."""
    if not phase_id:
        return ""
    digits_match = re.match(r"\d+", phase_id)
    if not digits_match:
        return phase_id
    digits = digits_match.group(0)
    suffix = phase_id[len(digits):]
    return str(int(digits)) + suffix
```

- [ ] **Step 4: Verify green**

Run: `python3 -m pytest tests/test_planning_grammar.py -q` → 11 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/planning_grammar.py tests/test_planning_grammar.py
git commit -m "feat(planning): phase-folder grammar with canonical/display split"
```

### Task 1.3: STATE / ROADMAP regex primitives + heading normalizer

**Files:**
- Modify: `scripts/lib/planning_grammar.py`
- Modify: `tests/test_planning_grammar.py`

- [ ] **Step 1: Failing tests covering STATE phase line, STATE checkpoint line, ROADMAP bullets, heading prefix matcher**

```python
from scripts.lib.planning_grammar import (
    parse_state_phase_line,
    parse_state_checkpoint_line,
    parse_roadmap_phase_bullets,
    heading_matches,
)


def test_parse_state_phase_line_trailing_period():
    text = "- **Phase**: 2 - v0.8.0 Minimal Workflow Release.\n"
    assert parse_state_phase_line(text) == ("02", "v0.8.0 Minimal Workflow Release")


def test_parse_state_phase_line_no_period():
    assert parse_state_phase_line("- **Phase**: 2 - v0.8.0 Minimal Workflow Release\n") == (
        "02", "v0.8.0 Minimal Workflow Release",
    )


def test_parse_state_phase_line_letter_suffix():
    assert parse_state_phase_line("- **Phase**: 2b - Hardening.\n") == ("02b", "Hardening")


def test_parse_state_phase_line_strips_trailing_bold():
    text = "- **Phase**: 2 - v0.8.0 **(in progress)**.\n"
    pid, title = parse_state_phase_line(text)
    assert pid == "02"
    assert title == "v0.8.0"  # trailing bold annotation stripped


def test_parse_state_checkpoint_line_numeric():
    pid, title = parse_state_checkpoint_line("- **Checkpoint**: CP-02-02 - contract and behavior.\n")
    assert pid == "CP-02-02"
    assert title == "contract and behavior"


def test_parse_state_checkpoint_line_letter_suffix():
    pid, title = parse_state_checkpoint_line("- **Checkpoint**: CP-02b-01 - foo.\n")
    assert pid == "CP-02b-01"
    assert title == "foo"


def test_parse_roadmap_phase_bullets_basic():
    text = (
        "- [x] **Phase 1: Generalized Harness Release** - one\n"
        "- [ ] **Phase 2: v0.8.0** - two\n"
    )
    bullets = parse_roadmap_phase_bullets(text)
    assert [(b.phase_id, b.completed, b.title) for b in bullets] == [
        ("01", True, "Generalized Harness Release"),
        ("02", False, "v0.8.0"),
    ]


def test_parse_roadmap_phase_bullets_letter_suffix():
    bullets = parse_roadmap_phase_bullets("- [ ] **Phase 2b: Hardening** - p\n")
    assert bullets[0].phase_id == "02b"
    assert bullets[0].title == "Hardening"


def test_heading_matches_exact():
    assert heading_matches("Blockers", "Blockers")


def test_heading_matches_separator():
    assert heading_matches("CONCERNS - General Harness", "CONCERNS")
    assert heading_matches("One-Liner — short", "One-Liner")
    assert heading_matches("Blockers (active)", "Blockers")
    assert heading_matches("Scope / extras", "Scope")


def test_heading_matches_case_insensitive():
    assert heading_matches("blockers", "Blockers")


def test_heading_matches_rejects_superstring_without_separator():
    assert not heading_matches("BlockersResolved", "Blockers")


def test_heading_matches_rejects_substring_inside_phrase():
    assert not heading_matches("Known Blockers", "Blockers")
    assert not heading_matches("Concerns / Blockers", "Blockers")
```

- [ ] **Step 2: Run, expect failures**

- [ ] **Step 3: Implement**

```python
# append to scripts/lib/planning_grammar.py
STATE_PHASE_RE = re.compile(
    r"-\s*\*\*Phase\*\*:\s*(?P<number>\d+[a-z]?)\s*-\s*(?P<title>[^\n]+?)\.?\s*$",
    re.MULTILINE,
)

STATE_CHECKPOINT_RE = re.compile(
    r"-\s*\*\*Checkpoint\*\*:\s*(?P<id>CP-\d+[a-z]?(?:-\d+)?)\s*(?:-\s*(?P<title>[^\n]+?))?\.?\s*$",
    re.MULTILINE,
)

ROADMAP_BULLET_RE = re.compile(
    r"^- \[(?P<mark>[ xX])\] \*\*Phase\s+(?P<number>\d+[a-z]?):\s*(?P<title>[^*]+)\*\*"
    r"(?:\s*-\s*(?P<summary>.*))?$",
    re.MULTILINE,
)

_TRAILING_BOLD_RE = re.compile(r"\s+\*\*[^*]+\*\*\s*$")
_HEADING_SEPARATORS = (" ", " -", " —", " /", " (", " {")


@dataclass(frozen=True)
class RoadmapBullet:
    phase_id: str
    title: str
    summary: str
    completed: bool
    raw_line: str


def parse_state_phase_line(text: str) -> tuple[str, str]:
    match = STATE_PHASE_RE.search(text)
    if not match:
        return "", ""
    title = _TRAILING_BOLD_RE.sub("", match.group("title").strip())
    return _zero_pad(match.group("number")), title.strip()


def parse_state_checkpoint_line(text: str) -> tuple[str, str]:
    match = STATE_CHECKPOINT_RE.search(text)
    if not match:
        return "", ""
    return match.group("id"), (match.group("title") or "").strip()


def parse_roadmap_phase_bullets(text: str) -> list[RoadmapBullet]:
    rows: list[RoadmapBullet] = []
    for m in ROADMAP_BULLET_RE.finditer(text):
        rows.append(
            RoadmapBullet(
                phase_id=_zero_pad(m.group("number")),
                title=m.group("title").strip(),
                summary=(m.group("summary") or "").strip(),
                completed=m.group("mark").lower() == "x",
                raw_line=m.group(0),
            )
        )
    return rows


def heading_matches(heading: str, target: str) -> bool:
    """True if `heading` exactly equals `target` or begins with `target<separator>...` (case-insensitive)."""
    h = heading.strip().lower()
    t = target.strip().lower()
    if h == t:
        return True
    if not h.startswith(t):
        return False
    rest = h[len(t):]
    return any(rest.startswith(sep) for sep in _HEADING_SEPARATORS)


def _zero_pad(raw: str) -> str:
    digits_match = re.match(r"\d+", raw)
    if not digits_match:
        return raw
    digits = digits_match.group(0)
    return digits.zfill(2) + raw[len(digits):]
```

- [ ] **Step 4: Verify green**

Run: `python3 -m pytest tests/test_planning_grammar.py -q` → ~24 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/planning_grammar.py tests/test_planning_grammar.py
git commit -m "feat(planning): STATE/ROADMAP regex + heading-prefix matcher"
```

### Task 1.4: Schema version primitive

**Files:**
- Modify: `scripts/lib/planning_grammar.py`
- Modify: `tests/test_planning_grammar.py`

- [ ] **Step 1: Failing tests**

```python
from scripts.lib.planning_grammar import (
    PLANNING_DOC_SCHEMA_VERSION,
    extract_planning_doc_schema_version,
    PlanningDocSchemaVersionError,
)


def test_planning_doc_schema_constant_is_1():
    assert PLANNING_DOC_SCHEMA_VERSION == 1


def test_extract_planning_doc_schema_version_present():
    text = "---\nplanning_doc_schema_version: 1\n---\n"
    assert extract_planning_doc_schema_version(text) == 1


def test_extract_planning_doc_schema_version_missing_returns_none():
    assert extract_planning_doc_schema_version("---\nfoo: bar\n---\n") is None


def test_extract_planning_doc_schema_version_wrong_raises():
    with pytest.raises(PlanningDocSchemaVersionError):
        extract_planning_doc_schema_version("---\nplanning_doc_schema_version: 99\n---\n")


def test_extract_planning_doc_schema_version_non_integer_raises():
    with pytest.raises(PlanningDocSchemaVersionError):
        extract_planning_doc_schema_version("---\nplanning_doc_schema_version: oops\n---\n")
```

- [ ] **Step 2: Failure**

- [ ] **Step 3: Implement**

```python
# append to scripts/lib/planning_grammar.py
PLANNING_DOC_SCHEMA_VERSION = 1


class PlanningDocSchemaVersionError(ValueError):
    """Raised when STATE.md (or other planning doc) declares an unsupported schema version."""


def extract_planning_doc_schema_version(text: str) -> int | None:
    fm = parse_frontmatter(text)
    raw = fm.get("planning_doc_schema_version")
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise PlanningDocSchemaVersionError(
            f"planning_doc_schema_version is not an integer: {raw!r}"
        ) from exc
    if value != PLANNING_DOC_SCHEMA_VERSION:
        raise PlanningDocSchemaVersionError(
            f"planning_doc_schema_version={value} unsupported "
            f"(this build expects {PLANNING_DOC_SCHEMA_VERSION})"
        )
    return value
```

(Note: deliberately distinct from `.scratch/phase-state.json`'s `state_schema_version` — two namespaces.)

- [ ] **Step 4: Verify green**

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/planning_grammar.py tests/test_planning_grammar.py
git commit -m "feat(planning): planning_doc_schema_version primitive (distinct from phase-state state_schema_version)"
```

---

## Slice 2 — `planning_status.py` consumes grammar

### Task 2.1: Delegate primitives + widen CP regex + introduce StateSchemaVersionError

**Files:**
- Modify: `scripts/lib/planning_status.py`
- Create: `tests/_helpers/__init__.py`, `tests/_helpers/planning_repo.py`
- Create: `tests/test_planning_status_regression.py`

- [ ] **Step 1: Author the fixture factory**

```python
# tests/_helpers/__init__.py — empty
# tests/_helpers/planning_repo.py
"""Shared minimal planning-repo factory for parser-unification tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def make_minimal_planning_repo(
    tmp_path: Path,
    *,
    phase_id: str = "02b",
    phase_folder: str = "02b-hardening",
    roadmap_title: str = "Hardening",
    checkpoint_id: str = "CP-02b-01",
    schema_version_line: str = "planning_doc_schema_version: 1\n",
    phase_state_overrides: dict[str, Any] | None = None,
) -> Path:
    (tmp_path / ".planning").mkdir()
    (tmp_path / f".planning/phases/{phase_folder}").mkdir(parents=True)
    (tmp_path / ".planning/STATE.md").write_text(
        f"---\n{schema_version_line}---\n"
        "# STATE\n"
        "## Current Position\n"
        f"- **Phase**: {phase_id.lstrip('0') or phase_id} - {roadmap_title}.\n"
        "## Active Checkpoint\n"
        f"- **Checkpoint**: {checkpoint_id} - smoke.\n"
        f"- **Checkpoint file**: `.planning/phases/{phase_folder}/{phase_id}-CHECKPOINTS.md`.\n",
        encoding="utf-8",
    )
    cp_text = f"## {checkpoint_id} - smoke\n- **Status**: in_progress\n"
    (tmp_path / f".planning/phases/{phase_folder}/{phase_id}-CHECKPOINTS.md").write_text(cp_text, encoding="utf-8")
    (tmp_path / f".planning/phases/{phase_folder}/{phase_id}-VERIFICATION.md").write_text("# Verification\n")
    (tmp_path / ".planning/ROADMAP.md").write_text(
        f"## Phases\n- [ ] **Phase {phase_id.lstrip('0') or phase_id}: {roadmap_title}** - intern\n",
        encoding="utf-8",
    )
    (tmp_path / ".scratch").mkdir()
    base_state = {
        "state_schema_version": 2,
        "phase": "discuss",
        "current_checkpoint": checkpoint_id,
        "checkpoint_path": f".planning/phases/{phase_folder}/{phase_id}-CHECKPOINTS.md",
        "state_path": ".planning/STATE.md",
        "automation_mode": "manual",
        "updated_at": "2026-05-20T00:00:00.000000000Z",
        "updated_by": "test",
    }
    if phase_state_overrides:
        base_state.update(phase_state_overrides)
    (tmp_path / ".scratch/phase-state.json").write_text(json.dumps(base_state), encoding="utf-8")
    return tmp_path
```

- [ ] **Step 2: Failing regression test**

```python
# tests/test_planning_status_regression.py
from tests._helpers.planning_repo import make_minimal_planning_repo


def test_projection_recognizes_letter_suffix_phase(tmp_path):
    root = make_minimal_planning_repo(tmp_path)
    from scripts.lib.planning_status import load_projection
    proj = load_projection(root)
    assert proj.phase_id == "02b"
    assert proj.active_checkpoint_id == "CP-02b-01"
    assert proj.verification_path == ".planning/phases/02b-hardening/02b-VERIFICATION.md"
    assert proj.active_checkpoint_status == "in_progress"


def test_projection_phase_title_strips_trailing_bold(tmp_path):
    root = make_minimal_planning_repo(tmp_path, roadmap_title="Hardening **(in progress)**")
    from scripts.lib.planning_status import load_projection
    proj = load_projection(root)
    assert proj.phase_id == "02b"
    # Roadmap title is the source of truth here; STATE title parser strips trailing bold.
    assert "**" not in proj.phase_title
```

- [ ] **Step 3: Run, expect failures**

- [ ] **Step 4: Refactor `planning_status.py`**

Add import:

```python
from scripts.lib.planning_grammar import (
    canonical_phase_id,
    extract_planning_doc_schema_version,
    parse_frontmatter,
    parse_roadmap_phase_bullets,
    parse_state_checkpoint_line,
    parse_state_phase_line,
    PlanningDocSchemaVersionError,
)
```

Make `StateSchemaVersionError` a subclass of the existing `ProjectionError`:

```python
class StateSchemaVersionError(ProjectionError):
    """Raised when STATE.md declares an unsupported planning_doc_schema_version."""
```

Replace the bodies of `_frontmatter_values` → `return parse_frontmatter(text)`; `_phase_id_from_folder` → `return canonical_phase_id(folder)`; rewrite `_parse_state_metadata`, `_parse_checkpoint_metadata` (widen its regex to allow letter-suffix CPs via `STATE_CHECKPOINT_RE` for the heading match too — i.e. accept `CP-02b-01` in `^##` heading regex), `_parse_roadmap_metadata`, `_roadmap_phase_title` to delegate to grammar primitives.

In `_parse_checkpoint_metadata`, change the heading regex to accept `[a-z]?` suffix:

```python
heading = re.search(r"^##\s+(CP-\d+[a-z]?(?:-\d+)?)\s*(?:-\s*(.+))?$", text, re.MULTILINE)
```

Also widen `_summary_doc_path`'s `CP-(\d+)-(\d+)` regex to `CP-(\d+[a-z]?)-(\d+)`.

In `_warnings()`, extend signature with `state_text: str` (caller passes the already-read text); add the schema-version block (and skip the wrap so it bubbles through `load_projection`'s try-block as appropriate):

```python
try:
    extract_planning_doc_schema_version(state_text)
except PlanningDocSchemaVersionError as exc:
    warnings.append(
        PlanningWarning(
            code="planning_doc_schema_version_unsupported",
            severity="blocking",
            message=str(exc),
            paths=[state_path],
            required_read=True,
        )
    )
else:
    version = extract_planning_doc_schema_version(state_text)
    if version is None:
        warnings.append(
            PlanningWarning(
                code="planning_doc_schema_version_missing",
                severity="warning",
                message="STATE.md does not declare planning_doc_schema_version; assuming 1.",
                paths=[state_path],
                required_read=False,
            )
        )
```

Update `load_projection` to pass `state_text` through to `_warnings` (and to read STATE.md exactly once).

- [ ] **Step 5: Verify green**

Run: `python3 -m pytest tests/test_planning_grammar.py tests/test_planning_status_regression.py scripts/test_show_phase_status.py -q`
Expected: all pass; in particular the existing `show_phase_status` tests still pass (the canonical phase id form `02` is unchanged for them).

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/planning_status.py tests/_helpers tests/test_planning_status_regression.py
git commit -m "refactor(planning_status): delegate to grammar; widen letter-suffix CP/phase regex"
```

---

## Slice 3 — Dashboard: structured warnings + projection-driven cross-checks

### Task 3.1: Introduce `DashboardWarning` and add `phase_id` to `RoadmapPhase`

**Files:**
- Modify: `scripts/lib/project_dashboard/models.py`
- Modify: `scripts/lib/project_dashboard/core.py`
- Modify: `scripts/lib/project_dashboard/renderer.py`
- Modify: `scripts/test_project_dashboard.py`

- [ ] **Step 1: Failing tests**

```python
# scripts/test_project_dashboard.py — append
def test_dashboard_warning_dataclass_round_trip():
    from lib.project_dashboard.models import DashboardWarning
    w = DashboardWarning(code="x", severity="warning", message="hello", paths=[".planning/STATE.md"])
    assert w.code == "x"
    assert w.severity == "warning"


def test_roadmap_phase_has_phase_id_field():
    from lib.project_dashboard.models import RoadmapPhase
    p = RoadmapPhase(title="Phase 1: x", summary="", completed=False, raw_line="...")
    assert p.phase_id == ""
    p2 = RoadmapPhase(title="Phase 2b: y", summary="", completed=False, raw_line="...", phase_id="02b")
    assert p2.phase_id == "02b"
```

- [ ] **Step 2: Failure**

- [ ] **Step 3: Modify models**

```python
# scripts/lib/project_dashboard/models.py — additions
@dataclass(frozen=True)
class DashboardWarning:
    code: str
    severity: str  # "blocking" | "warning"
    message: str
    paths: list[str]


# add field to RoadmapPhase (default empty preserves caller compat):
@dataclass
class RoadmapPhase:
    title: str
    summary: str
    completed: bool
    raw_line: str
    phase_id: str = ""
```

Change `DashboardData.warnings` type to `list[DashboardWarning]`.

- [ ] **Step 4: Update `core.py` to emit DashboardWarning**

Replace every `warnings.append(f"...")` with `warnings.append(DashboardWarning(code=..., severity=..., message=..., paths=[...]))`.

Concrete code-to-severity mapping:
| existing string prefix | new code | severity |
|---|---|---|
| `Missing optional file:` | `missing_optional_file` | warning |
| `phase-state references missing` | `phase_state_missing_path_ref` | blocking |
| `STATE active checkpoint differs` | `state_checkpoint_drift` | blocking |
| `STATE progress total_phases` | `roadmap_total_phases_drift` | blocking |
| `STATE progress completed_phases` | `roadmap_completed_phases_drift` | blocking |
| `Phase folder is present but not listed` | `phase_folder_not_in_roadmap` | warning |
| `Phase folder name does not match grammar` | `phase_folder_grammar_invalid` | blocking |
| `Issue files are present but no phase documents` | `issues_without_phase_docs` | warning |
| `Referenced core document is missing` | `core_document_missing` | warning |
| `phase-status <severity> <code>:` (from projection) | extract code from string | severity from middle word |

Update `format_projection_warnings` to return `list[DashboardWarning]` directly:

```python
def format_projection_warnings(projection: dict[str, object]) -> list[DashboardWarning]:
    out: list[DashboardWarning] = []
    for w in projection.get("warnings") or []:
        if not isinstance(w, dict):
            continue
        out.append(
            DashboardWarning(
                code=str(w.get("code", "unknown_projection_warning")),
                severity=str(w.get("severity", "warning")),
                message=str(w.get("message", "Planning projection warning.")),
                paths=[str(p) for p in (w.get("paths") or [])],
            )
        )
    return out
```

Update `dashboard_data_to_json` to serialize warnings as `[{"code": ..., "severity": ..., "message": ..., "paths": [...]}]`.

Update `generate_dashboard`'s print loop to print `"warning: {w.code}: {w.message}"`.

Update `renderer.py` warning rendering to show severity + code as a chip alongside the message text. (Keep cosmetics minimal; the structural change is the contract.)

- [ ] **Step 5: Verify green**

Run: `python3 -m pytest scripts/test_project_dashboard.py -q`
Expected: PASS. Adjust existing tests that assert on warning string content to match the new code/message shape; capture and re-run.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/project_dashboard/models.py scripts/lib/project_dashboard/core.py scripts/lib/project_dashboard/renderer.py scripts/test_project_dashboard.py
git commit -m "feat(dashboard): structured DashboardWarning + phase_id on RoadmapPhase"
```

### Task 3.2: Dashboard delegates to grammar + projection; consistency check uses canonical phase IDs

**Files:**
- Modify: `scripts/lib/project_dashboard/core.py`
- Modify: `scripts/test_project_dashboard.py`

- [ ] **Step 1: Failing test**

```python
def test_dashboard_recognises_letter_suffix_phase_no_phantom_warning(tmp_path):
    from tests._helpers.planning_repo import make_minimal_planning_repo
    root = make_minimal_planning_repo(tmp_path)
    from lib.project_dashboard.core import load_dashboard_data
    data = load_dashboard_data(root)
    # 02b is now declared in the ROADMAP fixture, so no "not in ROADMAP" warning:
    assert not any(w.code == "phase_folder_not_in_roadmap" for w in data.warnings)
    # And no grammar-invalid warning:
    assert not any(w.code == "phase_folder_grammar_invalid" for w in data.warnings)


def test_dashboard_emits_actionable_warning_when_phase_folder_missing_from_roadmap(tmp_path):
    from tests._helpers.planning_repo import make_minimal_planning_repo
    root = make_minimal_planning_repo(tmp_path)
    # Add an extra phase folder NOT declared in ROADMAP — simulating 02b-hardening on the live repo today:
    (root / ".planning/phases/02c-followup").mkdir()
    from lib.project_dashboard.core import load_dashboard_data
    data = load_dashboard_data(root)
    matched = [w for w in data.warnings if w.code == "phase_folder_not_in_roadmap"]
    assert len(matched) == 1
    assert "02c-followup" in matched[0].message
    assert "ROADMAP" in matched[0].message
    assert matched[0].severity == "warning"
```

- [ ] **Step 2: Failure**

- [ ] **Step 3: Rewrite `check_consistency`**

Replace the `phase_number = phase_slug.split(...)` block with grammar-based logic:

```python
roadmap_phase_ids = {b.phase_id for b in parse_roadmap_phase_bullets(roadmap_text)}
for document in phase_documents:
    pid = canonical_phase_id(document.phase_dir)
    if not pid:
        warnings.append(DashboardWarning(
            code="phase_folder_grammar_invalid",
            severity="blocking",
            message=f"Phase folder name does not match grammar (expected NN[a-z]?-slug): {document.phase_dir}",
            paths=[document.phase_dir],
        ))
        continue
    if pid not in roadmap_phase_ids:
        warnings.append(DashboardWarning(
            code="phase_folder_not_in_roadmap",
            severity="warning",
            message=(
                f"Phase folder {document.phase_dir} (id={pid}) is not listed in ROADMAP.md. "
                "Add a corresponding Phase entry to ROADMAP, or move the folder to .planning/archive/ if the phase has already shipped."
            ),
            paths=[document.phase_dir, ".planning/ROADMAP.md"],
        ))
```

Cache `roadmap_text` once at the top of `load_dashboard_data` and pass through.

Replace `parse_roadmap_phases` body (keep the function signature for backwards compatibility):

```python
def parse_roadmap_phases(text: str) -> list[RoadmapPhase]:
    return [
        RoadmapPhase(
            title=f"Phase {display_phase_id(b.phase_id)}: {b.title}",
            summary=b.summary,
            completed=b.completed,
            raw_line=b.raw_line,
            phase_id=b.phase_id,
        )
        for b in parse_roadmap_phase_bullets(text)
    ]
```

Replace `parse_section_bullets`, `parse_section_paragraph`, `parse_section_until_heading` heading match with `heading_matches(head_text, target)` from grammar.

Delete `core.parse_frontmatter` body and replace with `from scripts.lib.planning_grammar import parse_frontmatter as parse_frontmatter` re-export (preserves existing tests that import it from core).

- [ ] **Step 4: Verify green**

Run: `python3 -m pytest scripts/test_project_dashboard.py -q`

- [ ] **Step 5: Manual sanity on real repo**

Run: `python3 scripts/project_dashboard.py 2>&1 | grep -E "02b|phase_folder"`
Expected: a warning whose code is `phase_folder_not_in_roadmap` and whose message starts with `Phase folder .planning/phases/02b-hardening (id=02b) is not listed in ROADMAP.md. Add ...`. The warning is now actionable, not phantom.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/project_dashboard/core.py scripts/test_project_dashboard.py
git commit -m "refactor(dashboard): consistency checks use canonical phase IDs; parse_roadmap_phases delegates"
```

### Task 3.3: Nested `plans/*-PLAN.md` inventory

**Files:**
- Modify: `scripts/lib/project_dashboard/core.py`
- Modify: `scripts/test_project_dashboard.py`

- [ ] **Step 1: Failing test**

```python
def test_load_phase_documents_includes_nested_plan_files(tmp_path):
    phase = tmp_path / ".planning/phases/02b-hardening"
    (phase / "plans").mkdir(parents=True)
    (phase / "README.md").write_text("# README\n")
    (phase / "plans" / "02b-01-T0-A-PLAN.md").write_text("# T0-A\n")
    (phase / "plans" / "02b-02-T0-1-PLAN.md").write_text("# T0-1\n")
    (phase / "plans" / "scratch.md").write_text("# not a plan\n")  # excluded
    from lib.project_dashboard.core import load_phase_documents
    docs = load_phase_documents(tmp_path)
    files = docs[0].files
    assert "02b-01-T0-A-PLAN.md" in files
    assert "02b-02-T0-1-PLAN.md" in files
    assert "scratch.md" not in files  # only *-PLAN.md included
    assert files["02b-01-T0-A-PLAN.md"].endswith("plans/02b-01-T0-A-PLAN.md")


def test_load_phase_documents_top_level_wins_on_name_collision(tmp_path):
    phase = tmp_path / ".planning/phases/02b-hardening"
    (phase / "plans").mkdir(parents=True)
    (phase / "duplicate.md").write_text("# top\n")
    (phase / "plans" / "duplicate.md").write_text("# nested\n")
    from lib.project_dashboard.core import load_phase_documents
    docs = load_phase_documents(tmp_path)
    files = docs[0].files
    assert files["duplicate.md"].endswith(".planning/phases/02b-hardening/duplicate.md")
```

- [ ] **Step 2: Failure**

- [ ] **Step 3: Implement**

```python
for path in sorted(phase_dir.glob("plans/*-PLAN.md")):
    relative = path.relative_to(root).as_posix()
    if path.name in files:
        continue  # top-level dominant
    files[path.name] = relative
    headings.extend(parse_headings(path.read_text(encoding="utf-8"))[:2])
```

Loop after the existing `phase_dir.glob("*.md")` loop.

- [ ] **Step 4: Verify green**

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/project_dashboard/core.py scripts/test_project_dashboard.py
git commit -m "feat(dashboard): include nested plans/*-PLAN.md in phase inventory"
```

---

## Slice 4 — JSON gate hardness

### Task 4.1: `load_phase_state` returns (data, warning) and downstream checks skip cleanly

**Files:**
- Modify: `scripts/lib/project_dashboard/core.py`
- Modify: `scripts/test_project_dashboard.py`

- [ ] **Step 1: Failing tests**

```python
def test_malformed_phase_state_emits_single_structured_warning(tmp_path):
    from tests._helpers.planning_repo import make_minimal_planning_repo
    root = make_minimal_planning_repo(tmp_path)
    (root / ".scratch/phase-state.json").write_text("{not json")
    from lib.project_dashboard.core import load_dashboard_data
    data = load_dashboard_data(root)
    malformed = [w for w in data.warnings if w.code == "phase_state_malformed_json"]
    assert len(malformed) == 1
    # secondary checks must not pile on:
    assert not any(w.code == "phase_state_missing_path_ref" for w in data.warnings)
    assert not any(w.code == "state_checkpoint_drift" for w in data.warnings)
```

- [ ] **Step 2: Failure**

- [ ] **Step 3: Implement**

```python
def load_phase_state(path: Path) -> tuple[dict[str, object], DashboardWarning | None]:
    if not path.exists():
        return {}, None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {}, DashboardWarning(
            code="phase_state_malformed_json",
            severity="blocking",
            message=f"phase-state.json is malformed JSON: {exc.msg} (line {exc.lineno}, col {exc.colno})",
            paths=[".scratch/phase-state.json"],
        )
    if not isinstance(loaded, dict):
        return {}, DashboardWarning(
            code="phase_state_not_object",
            severity="blocking",
            message="phase-state.json must contain a JSON object",
            paths=[".scratch/phase-state.json"],
        )
    return loaded, None
```

In `load_dashboard_data`:

```python
phase_state, ps_warning = load_phase_state(phase_state_path)
phase_state_usable = ps_warning is None
if ps_warning is not None:
    warnings.append(ps_warning)
```

In `check_consistency`, gate phase-state-dependent checks behind `phase_state_usable` (pass it in as an arg).

- [ ] **Step 4: Verify green**

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/project_dashboard/core.py scripts/test_project_dashboard.py
git commit -m "fix(dashboard): structured malformed-JSON warning + skip dependent consistency checks"
```

---

## Slice 5 — STATE.md schema-version stamp (guarded)

### Task 5.1: Stamp `planning_doc_schema_version: 1` into live STATE.md

**Files:**
- Modify: `.planning/STATE.md`

- [ ] **Step 1: Verify STATE.md starts with frontmatter and does NOT already carry the key**

Run: `head -10 .planning/STATE.md`
Expected: starts with `---\nprogress:\n  total_phases: 2\n  completed_phases: 1\n  percent: 50\n---`. If `planning_doc_schema_version` already appears anywhere in `.planning/STATE.md`, skip this slice entirely and proceed to Slice 6.

- [ ] **Step 2: Anchored insert**

Use the Edit tool against the literal frontmatter block. Replace:

```
---
progress:
```

with:

```
---
planning_doc_schema_version: 1
progress:
```

(Only one such occurrence in the file — Edit will fail loudly if the assumption breaks.)

- [ ] **Step 3: Verify projection still loads with no schema_version warning**

Run: `python3 scripts/show_phase_status.py | python3 -c "import json,sys;data=json.load(sys.stdin);print([w for w in data['warnings'] if 'planning_doc_schema' in w['code']])"`
Expected: empty list `[]`.

- [ ] **Step 4: Run full dashboard + show-phase-status suites**

Run: `python3 -m pytest scripts/test_project_dashboard.py scripts/test_show_phase_status.py tests/test_planning_grammar.py tests/test_planning_status_regression.py -q`

- [ ] **Step 5: Commit**

```bash
git add .planning/STATE.md
git commit -m "chore(planning): stamp planning_doc_schema_version=1 in STATE.md"
```

---

## Slice 6 — `--check` mode + harness integration

### Task 6.1: `project_dashboard.py --check`

**Files:**
- Modify: `scripts/lib/project_dashboard/core.py`
- Modify: `scripts/project_dashboard.py` (no change needed — `core.run` is the entry)
- Create: `scripts/test_project_dashboard_check.py`

- [ ] **Step 1: Failing tests**

```python
import json, subprocess, sys
from pathlib import Path
from tests._helpers.planning_repo import make_minimal_planning_repo

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(root):
    return subprocess.run(
        [sys.executable, "scripts/project_dashboard.py", "--check", "--root", str(root)],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )


def test_check_exit_zero_on_clean_fixture(tmp_path):
    root = make_minimal_planning_repo(tmp_path)
    result = _run(root)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert all(w["severity"] != "blocking" for w in payload["warnings"])


def test_check_exit_drift_on_extra_undeclared_phase(tmp_path):
    from scripts.lib.exitcodes import EXIT_PLANNING_DRIFT
    root = make_minimal_planning_repo(tmp_path)
    (root / ".planning/phases/02c-extra").mkdir()
    result = _run(root)
    assert result.returncode == EXIT_PLANNING_DRIFT
    payload = json.loads(result.stdout)
    assert payload["status"] == "drift"
    assert any(w["code"] == "phase_folder_not_in_roadmap" for w in payload["warnings"])


def test_check_exit_drift_on_blocking_warning(tmp_path):
    from scripts.lib.exitcodes import EXIT_PLANNING_DRIFT
    root = make_minimal_planning_repo(tmp_path)
    (root / ".scratch/phase-state.json").write_text("{bad")
    result = _run(root)
    assert result.returncode == EXIT_PLANNING_DRIFT
    payload = json.loads(result.stdout)
    assert any(w["code"] == "phase_state_malformed_json" and w["severity"] == "blocking" for w in payload["warnings"])
```

- [ ] **Step 2: Failure (argparse rejects --check)**

- [ ] **Step 3: Implement**

In `core.py`:

```python
def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--check", action="store_true",
                        help="Validate planning docs; print JSON; exit EXIT_PLANNING_DRIFT on any blocking warning.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_DASHBOARD_PORT)
    return parser.parse_args(argv)


def run(argv=None):
    from scripts.lib.exitcodes import EXIT_OK, EXIT_PLANNING_DRIFT
    args = parse_args(argv)
    root = args.root.resolve()
    if args.check:
        data = load_dashboard_data(root)
        blocking = [w for w in data.warnings if w.severity == "blocking"]
        payload = {
            "status": "drift" if blocking else "ok",
            "warnings": [{"code": w.code, "severity": w.severity, "message": w.message, "paths": w.paths} for w in data.warnings],
        }
        print(json.dumps(payload, indent=2))
        return EXIT_PLANNING_DRIFT if blocking else EXIT_OK
    if args.serve:
        from scripts.lib.project_dashboard.server import serve_dashboard
        serve_dashboard(root=root, host=args.host, port=args.port)
        return EXIT_OK
    output = args.output if args.output.is_absolute() else (root / args.output)
    generate_dashboard(root=root, output=output)
    return EXIT_OK
```

(Note: `status == "ok"` is allowed to coexist with non-blocking `warning` severity entries — that is intentional and matches the planning_doc_schema_version_missing soft-warning case.)

- [ ] **Step 4: Verify green**

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/project_dashboard/core.py scripts/test_project_dashboard_check.py
git commit -m "feat(dashboard): --check mode with EXIT_PLANNING_DRIFT"
```

### Task 6.2: Wire `--check` into `harness check`

**Files:**
- Modify: `scripts/lib/check.py`
- Modify: appropriate existing test in `scripts/test_*.py` or `tests/test_*.py`

- [ ] **Step 1: Locate the aggregator entry point**

Run: `grep -nE "def (run_check|cli_check|cmd_check|main)\b|harness check" scripts/lib/check.py | head -20`
Read the relevant function and note where existing sub-checks return their results into the aggregator's failure list.

- [ ] **Step 2: Failing test — when an extra undeclared phase folder exists, `harness check` returns nonzero**

(Concrete shape depends on existing test infra; mirror the closest existing `harness check` test under `scripts/`/`tests/` and adapt the assertion to expect drift propagation. If no analogous test exists, create `tests/test_check_planning_drift.py` driving `subprocess.run([sys.executable, "scripts/harness.py", "check"], cwd=fixture_root)` and asserting nonzero exit when fixture has undeclared phase folder.)

- [ ] **Step 3: Implement**

Inside the aggregator, after existing sub-checks:

```python
from scripts.lib.project_dashboard.core import run as dashboard_run
drift_exit = dashboard_run(["--check", "--root", str(root)])
if drift_exit != EXIT_OK:
    failures.append(("planning-drift", "dashboard --check detected drift; run `python3 scripts/project_dashboard.py --check` for details"))
```

(Adapt to actual aggregator API — variable names will differ.)

- [ ] **Step 4: Verify green**

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/check.py scripts/test_check.py  # or wherever the new test lives
git commit -m "feat(check): include dashboard planning-drift in harness check"
```

---

## Slice 7 — Documentation

### Task 7.1: `docs/planning-grammar.md`

**Files:**
- Create: `docs/planning-grammar.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Author the doc**

Sections:
1. Why a dialect exists; what the grammar module owns; what it does NOT own (phase-state.json schema is separate, see ADR-001).
2. Required planning files and per-file grammar rules. For each: a positive example block copied from the repo's real files, and 1-2 negative examples annotated with the resulting warning code (`phase_folder_grammar_invalid`, `phase_folder_not_in_roadmap`, `state_checkpoint_drift`, `roadmap_total_phases_drift`, `planning_doc_schema_version_unsupported`, etc.).
3. Phase folder name grammar (`NN[a-z]?-slug`); nested `plans/*-PLAN.md` convention; archived phases under `.planning/archive/`.
4. `planning_doc_schema_version: 1` — distinct from `.scratch/phase-state.json`'s `state_schema_version`. Cross-link.
5. Heading match policy: target equals heading text after `#` strip OR target is a prefix followed by separator (`' '`, `' -'`, `' —'`, `' /'`, `' ('`, `' {'`).
6. `EXIT_PLANNING_DRIFT = 12`.
7. How to validate locally: `python3 scripts/project_dashboard.py --check`.
8. Reference table mapping each grammar constant in `scripts/lib/planning_grammar.py` to its purpose: `PHASE_FOLDER_REGEX`, `STATE_PHASE_RE`, `STATE_CHECKPOINT_RE`, `ROADMAP_BULLET_RE`, `PLANNING_DOC_SCHEMA_VERSION`.

- [ ] **Step 2: Cross-reference from AGENTS.md**

Append to the planning section:

```markdown
Planning-doc dialect is defined in [`docs/planning-grammar.md`](docs/planning-grammar.md). Run `python3 scripts/project_dashboard.py --check` before pushing planning edits. Drift exits with `EXIT_PLANNING_DRIFT = 12`.
```

- [ ] **Step 3: Commit**

```bash
git add docs/planning-grammar.md AGENTS.md
git commit -m "docs(planning): formal grammar dialect doc"
```

### Task 7.2: Real-file regression test for the prefix-with-separator matcher

**Files:**
- Create: `tests/test_planning_grammar_real_files.py`

- [ ] **Step 1: Write the regression**

```python
"""Real-file regressions: the prefix-with-separator heading matcher MUST work on these live docs."""

from pathlib import Path
import pytest
from scripts.lib.planning_grammar import heading_matches

REPO = Path(__file__).resolve().parent.parent


def _first_line_heading(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()
    pytest.skip(f"no heading in {path}")


def test_concerns_md_heading_matches_target():
    path = REPO / ".planning/codebase/CONCERNS.md"
    if not path.exists():
        pytest.skip("CONCERNS.md not present")
    assert heading_matches(_first_line_heading(path), "CONCERNS")


def test_project_md_section_one_liner():
    path = REPO / ".planning/PROJECT.md"
    assert path.exists()
    # The dashboard's load_project_memory calls parse_section_paragraph(text, "One-Liner");
    # ensure that heading matcher finds the section heading.
    heading_line = next(l for l in path.read_text(encoding="utf-8").splitlines() if l.startswith("## "))
    assert heading_matches(heading_line.lstrip("#").strip(), "One-Liner") \
        or heading_matches(heading_line.lstrip("#").strip(), "One Liner")  # tolerate either canonical form


def test_state_md_active_checkpoint_heading():
    path = REPO / ".planning/STATE.md"
    text = path.read_text(encoding="utf-8")
    assert any(
        heading_matches(line.lstrip("#").strip(), "Active Checkpoint")
        for line in text.splitlines() if line.startswith("#")
    )
```

- [ ] **Step 2: Verify green; if it fails, fix the matcher OR fix the doc (in this slice)**

- [ ] **Step 3: Commit**

```bash
git add tests/test_planning_grammar_real_files.py
git commit -m "test(planning): real-file heading-matcher regression"
```

---

## Verification gate

Before declaring the plan complete:

- [ ] `python3 -m pytest tests/test_planning_grammar.py tests/test_planning_status_regression.py tests/test_planning_grammar_real_files.py scripts/test_project_dashboard.py scripts/test_project_dashboard_check.py scripts/test_show_phase_status.py tests/test_exitcodes_symbols.py -q` — all green.
- [ ] `python3 scripts/project_dashboard.py --check` on the live repo — exit code is `EXIT_PLANNING_DRIFT (12)` because `02b-hardening` is undeclared in ROADMAP; JSON output shows exactly one `phase_folder_not_in_roadmap` warning naming `02b-hardening`, plus the projection's own warnings for the still-current Phase 2 v0.8.0 active checkpoint.
- [ ] `git grep -n 'state_schema_version' .planning/STATE.md` — no match. The STATE.md uses `planning_doc_schema_version`, not the phase-state.json field.
- [ ] `git grep -n 'EXIT_PLANNING_DRIFT' scripts/lib/exitcodes.py scripts/lib/check.py scripts/lib/project_dashboard/core.py` — three or more matches (definition + consumer + propagator).
- [ ] Full pytest sweep: `python3 -m pytest scripts/ tests/ -q` — pass count >= baseline; any newly-failing test must be a deliberate v1 contract change, with rationale in the commit message.
- [ ] Manual dashboard render: `python3 scripts/project_dashboard.py && open .scratch/reports/project-dashboard.html` — Phase 02b plans appear under the phase inventory; warning panel shows the structured warning with code chip.

---

## Out of scope (deferred to follow-up plans)

- **ROADMAP / STATE.md reconciliation for v0.9.x.** This plan deliberately surfaces the existing drift via the actionable `phase_folder_not_in_roadmap` warning. Reconciling the planning docs to the shipped reality (v0.9.3, phases 02b/02c/02d) belongs in a separate plan whose scope is planning-doc content, not parser code.
- **DECISIONS.md heading vs table dual sourcing.** PROJECT.md uses `### DEC-id` headings while DECISIONS.md is a pipe table; the dashboard parses the latter only. Single-source migration is its own design.
- **Issue label parser robustness.** `"- label:"` prefix matching in `core.load_issues` is fragile; tracked separately.
- **Markdown emphasis stripping in DECISIONS table cells.** Bold/italic/links currently render raw.
- **Server-side projection caching / live reload.**
- **`.scratch/**/issues/` path generalisation.**

---

## Open questions for the executing engineer

1. **Phase counting semantics.** Should `Phase 2b` count toward `progress.total_phases`? v1 grammar lets the warning emerge naturally either way — the executing engineer should decide and document in `docs/planning-grammar.md`. Default recommendation: each letter-suffix variant is a separate phase for counting purposes (1 + 2 + 2b + 2c + 2d = 5).
2. **`harness check` blocking severity.** Slice 6.2 propagates `EXIT_PLANNING_DRIFT` to `harness check` failures. Should non-blocking drift (e.g. `phase_folder_not_in_roadmap` with severity `warning`) propagate too? Default in v1: only `severity=="blocking"` triggers the non-zero exit; warnings show in the JSON but do not fail check.
3. **Renderer adoption rate.** Slice 3.1 changes `DashboardData.warnings` to a structured list. Does the existing renderer fully consume the structured form, or are there call sites that still expect `list[str]`? Verify with `grep -rn "data\.warnings" scripts/lib/project_dashboard/` and adapt before committing Slice 3.1.
4. **Archive convention.** The actionable warning suggests moving shipped phases to `.planning/archive/`. Does that directory convention exist or should it be introduced separately? v1 only mentions it in the warning text; if the convention doesn't yet exist, soften the wording or create a tiny ADR.

---

## Reviewer audit trail

- v0 review files: `/tmp/codex-review.log` (codex non-interactive, 2026-05-20) and the Opus subagent transcript (recorded inline above as part of the v0→v1 reconciliation in the calling session).
- All CRIT findings from both reviewers are resolved or explicitly accepted with rationale in the revision history at the top of this file.
- HIGH findings: 11/12 resolved; 1 (#3 — ROADMAP staleness) deliberately deferred to a follow-up plan rather than silenced.
- MED/LOW findings: incorporated where they removed silent failures; LOW cosmetic items deferred where they did not affect correctness.
