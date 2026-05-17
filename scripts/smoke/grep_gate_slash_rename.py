#!/usr/bin/env python3
"""Grep-gate: forbid old slash-command names after the §4.1 rename.

Searches the working tree for references to the old slash command names:
  - /fsd-phase      (must be /fsd-run-phase)
  - /fsd-chain-phase (must be /fsd-run-all)

Scope: files under .roo/, .opencode/, docs/, scripts/, README*, *.md at root.

Exit codes
----------
0 — no forbidden references found.
1 — one or more matches; prints ``file:line: <match>`` on stderr.

Usage
-----
    python scripts/smoke/grep_gate_slash_rename.py
    python scripts/smoke/grep_gate_slash_rename.py --repo-root /path/to/repo
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Regex patterns for forbidden slash-command names.
# Match /fsd-phase not followed by -run or any other hyphenated continuation
# that would make it part of a legitimate new name.
# Also match /fsd-chain-phase as a forbidden old name.
FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    # (pattern, human-readable name)
    (r"/fsd-phase(?![-\w])", "/fsd-phase (use /fsd-run-phase)"),
    (r"/fsd-chain-phase(?![-\w])", "/fsd-chain-phase (use /fsd-run-all)"),
)

# Globs (relative to repo root) to search.
SEARCH_GLOBS: tuple[str, ...] = (
    ".roo/**/*.md",
    ".roo/**/*.txt",
    ".opencode/**/*.md",
    ".opencode/**/*.txt",
    "docs/**/*.md",
    "scripts/**/*.py",
    "scripts/**/*.md",
    "README*.md",
    "README",
    "*.md",
)


def get_exempt_paths(repo_root: Path) -> frozenset[str]:
    """Return relative paths (POSIX) that are exempt from the sweep."""
    candidates = [
        # Design doc documents the old names in the §4.1 transition table.
        "docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md",
        # This script itself.
        "scripts/smoke/grep_gate_slash_rename.py",
        # CHANGELOG / release notes may mention the rename.
        "CHANGELOG.md",
        "CHANGELOG",
        "docs/CHANGELOG.md",
        # ADR documents historical context (why the rename happened);
        # the mention of /fsd-phase is the problem-statement, not a live reference.
        "docs/adr/2026-05-17-autopilot-guards-and-manual-handoff.md",
        # UX-polish spec documents prior muscle-memory pain; historical record.
        "docs/superpowers/specs/v0.8.0_todo/2026-05-17-ux-polish.md",
    ]
    return frozenset(c for c in candidates if (repo_root / c).exists() or True)


def collect_files(repo_root: Path) -> list[Path]:
    seen: set[Path] = set()
    for glob in SEARCH_GLOBS:
        for path in repo_root.glob(glob):
            if path.is_file():
                seen.add(path.resolve())
    return sorted(seen)


def scan(
    files: list[Path],
    repo_root: Path,
    exempt_paths: frozenset[str],
) -> list[tuple[str, int, str, str]]:
    """Return list of (rel_path, lineno, matched_text, pattern_name) tuples."""
    compiled = [(re.compile(pat), name) for pat, name in FORBIDDEN_PATTERNS]
    hits: list[tuple[str, int, str, str]] = []
    for path in files:
        rel = path.relative_to(repo_root).as_posix()
        if rel in exempt_paths:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for regex, name in compiled:
                if regex.search(line):
                    hits.append((rel, lineno, line.rstrip(), name))
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Override the repo root (default: two levels up from this script).",
    )
    args = parser.parse_args(argv)

    if args.repo_root:
        repo_root = Path(args.repo_root).resolve()
    else:
        repo_root = Path(__file__).resolve().parents[2]

    exempt_paths = get_exempt_paths(repo_root)
    files = collect_files(repo_root)
    hits = scan(files, repo_root, exempt_paths)

    if hits:
        sys.stderr.write(
            f"FAIL slash-rename grep gate: {len(hits)} forbidden reference(s) found\n\n"
        )
        for rel, lineno, line, name in hits:
            sys.stderr.write(f"  {rel}:{lineno}: [{name}] {line}\n")
        sys.stderr.write(
            "\nFix: replace old slash command names with their new equivalents:\n"
            "  /fsd-phase        → /fsd-run-phase\n"
            "  /fsd-chain-phase  → /fsd-run-all\n"
        )
        return 1

    sys.stdout.write(
        f"slash-rename grep gate: 0 forbidden references found "
        f"(scanned {len(files)} file(s))\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
