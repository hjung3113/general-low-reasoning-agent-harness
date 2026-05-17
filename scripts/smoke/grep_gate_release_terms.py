#!/usr/bin/env python3
"""Grep-gate: forbid deprecated release terms in adapter commands and installed artifacts.

This gate enforces the S13 step-2 forbidden-term list per design §7 line 1022.
It checks ONLY the adapter-facing command bodies and installed skill/rule files
(NOT planning docs, test files, or migration code — those have intentional
references in transition tables and migration paths).

Forbidden terms (§7 line 1022):
  - HARNESS_HUMAN          — deprecated env var (S14 sweep; never use in commands)
  - automation_mode        — replaced by execution_mode
  - last_good_commit_sha   — removed in Model B
  - chain --resume         — Model B removes resume semantics
  - chain --abort          — Model B removes abort semantics
  - containment_           — any containment_* field (renamed to network_guard_*)
  - autopilot_budgets_remaining — renamed to cli_budgets_remaining

Scanned paths (narrow: adapter-facing artifacts only):
  - .roo/commands/*.md
  - .roo/skills/**/*.md
  - .roo/rules/**/*.md
  - .roo/rules-orchestrator/**/*.md
  - .opencode/commands/*.md
  - docs/superpowers/skills/**/*.md
  - docs/superpowers/rules/**/*.md

Explicitly excluded:
  - This gate script itself
  - Design spec + ADR documents (intentionally reference old names in tables)
  - CHANGELOG / release notes
  - scripts/smoke/grep_gate_stale_terms.py (sibling gate, not an artifact)

Exit codes:
  0 — no forbidden terms found in scanned paths.
  1 — one or more matches; prints file:line: <term> for each hit on stderr.

Usage:
    python scripts/smoke/grep_gate_release_terms.py

Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md §7 line 1022
Slice: S13-smoke step 2
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Terms that require word-boundary matching (identifier-style: must not be
# embedded in a larger identifier word).  E.g. "containment_" should match
# "containment_layer" but NOT "nocontainment_layer".
_WORD_BOUNDARY_TERMS: frozenset[str] = frozenset({"containment_"})
_WB_PATTERNS: dict[str, re.Pattern] = {
    t: re.compile(r"(?<![A-Za-z0-9_])" + re.escape(t)) for t in _WORD_BOUNDARY_TERMS
}


def _term_in_line(term: str, line: str) -> bool:
    """Return True if *term* is present in *line*.

    For terms in _WORD_BOUNDARY_TERMS, uses a word-boundary regex to avoid
    false positives from embedded substrings.  For all other terms, uses a
    plain substring check.
    """
    if term in _WORD_BOUNDARY_TERMS:
        return bool(_WB_PATTERNS[term].search(line))
    return term in line

# Forbidden terms per §7 line 1022 (S13 step-2 mandatory set).
RELEASE_TERMS: tuple[str, ...] = (
    "HARNESS_HUMAN",
    "automation_mode",
    "last_good_commit_sha",
    "chain --resume",
    "chain --abort",
    "containment_",           # identifier prefix — use word-boundary regex (see _term_in_line)
    "autopilot_budgets_remaining",
)

# Globs: adapter command/skill/rule files only (not planning docs or test files).
RELEASE_GLOBS: tuple[str, ...] = (
    ".roo/commands/*.md",
    ".roo/skills/**/*.md",
    ".roo/rules/**/*.md",
    ".roo/rules-orchestrator/**/*.md",
    ".opencode/commands/*.md",
    "docs/superpowers/skills/**/*.md",
    "docs/superpowers/rules/**/*.md",
)

# Files exempt from this sweep. Relative to repo root.
EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        # This gate script
        "scripts/smoke/grep_gate_release_terms.py",
        # Sibling gate (not an adapter artifact)
        "scripts/smoke/grep_gate_stale_terms.py",
        # Design spec — intentionally documents both old and new names
        "docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md",
        "docs/superpowers/specs/2026-05-17-phase-gate-hardening-round6-review-notes.md",
        # ADRs — contain transition tables with old names
        "docs/adr/2026-05-17-approver-provenance-and-execution-mode.md",
        "docs/adr/2026-05-17-audit-canonicalization-locking-and-state-trust.md",
        "docs/adr/2026-05-17-autopilot-guards-and-manual-handoff.md",
    }
)


def collect_files() -> list[Path]:
    seen: set[Path] = set()
    for glob in RELEASE_GLOBS:
        for path in REPO_ROOT.glob(glob):
            if path.is_file():
                seen.add(path.resolve())
    return sorted(seen)


def scan(files: list[Path]) -> list[tuple[Path, int, str]]:
    hits: list[tuple[Path, int, str]] = []
    for path in files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in EXEMPT_PATHS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for term in RELEASE_TERMS:
                if _term_in_line(term, line):
                    hits.append((path, lineno, term))
    return hits


def main() -> int:
    files = collect_files()
    hits = scan(files)

    if hits:
        sys.stderr.write(
            f"FAIL grep-gate-release-terms: {len(hits)} forbidden-term hit(s) "
            f"in adapter command/skill/rule files\n"
        )
        for path, lineno, term in hits:
            rel = path.relative_to(REPO_ROOT).as_posix()
            sys.stderr.write(f"  {rel}:{lineno}: {term!r}\n")
        sys.stderr.write(
            "\nFix: remove the listed deprecated terms from adapter-facing files.\n"
            "See design §7 line 1022 and §12.10 for the canonical term list.\n"
            "Terms renamed: automation_mode→execution_mode, "
            "containment_*→network_guard_*, "
            "autopilot_budgets_remaining→cli_budgets_remaining\n"
        )
        return 1

    sys.stdout.write(
        f"OK grep-gate-release-terms: scanned {len(files)} adapter-facing file(s); "
        "0 forbidden release terms.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
