#!/usr/bin/env python3
"""Grep-gate: forbid stale terms in installed artifacts.

Modes
-----
``--launcher-only``
    Required by S00.5-launcher slice (design doc §9). Walks only the adapter
    command files — ``.roo/commands/*.md`` and ``.opencode/commands/*.md`` —
    and forbids the alternative launcher strings declared in §7 + §12.14:

      python3 scripts/harness.py
      python scripts/harness.py
      py scripts/harness.py
      scripts/show_phase_status.py

    Other forbidden strings (`--chain`, `--auto`, `--yes`, ...) are out of
    scope for this slice and are checked at S14 with the full sweep glob.

``--full`` (default)
    Required by S14-sweep slice. Walks the full glob pinned in design doc
    §12.14 and forbids every term in ``FORBIDDEN_STRINGS``.

Exit codes
----------
``0`` — no forbidden strings found.
``1`` — one or more matches; the script prints ``file:line: <pattern>`` for
        each hit on stderr and a remediation hint.

Usage
-----
    python scripts/smoke/grep_gate_stale_terms.py --launcher-only
    python scripts/smoke/grep_gate_stale_terms.py --full
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Forbidden alternative launchers — checked in --launcher-only AND --full mode.
LAUNCHER_TERMS: tuple[str, ...] = (
    "python3 scripts/harness.py",
    "python scripts/harness.py",
    "py scripts/harness.py",
    "scripts/show_phase_status.py",
)

# Additional forbidden strings — checked only in --full mode (S14).
FULL_SWEEP_TERMS: tuple[str, ...] = (
    "--chain",
    "--auto",
    "--yes",
    "automation_mode",
    "containment_layer",
    "containment_posture",
    "last_good_commit_sha",
    "chain --resume",
    "chain --abort",
    "autopilot_budgets_remaining",
    "HARNESS_HUMAN",
)

# Globs (relative to repo root) walked in --launcher-only mode.
LAUNCHER_GLOBS: tuple[str, ...] = (
    ".roo/commands/*.md",
    ".opencode/commands/*.md",
)

# Globs walked in --full mode (design doc §12.14).
FULL_GLOBS: tuple[str, ...] = (
    ".roo/commands/*.md",
    ".roo/skills/**/*.md",
    ".roo/rules/**/*.md",
    ".roo/rules-orchestrator/**/*.md",
    ".opencode/commands/*.md",
    "docs/superpowers/skills/**/*.md",
    "docs/superpowers/rules/**/*.md",
    "docs/adr/*.md",
    ".planning/**/*.md",
    "CLAUDE.md",
    "AGENTS.md",
    "GEMINI.md",
    "README.md",
    "scripts/**/*.py",
)

# Files whose entire purpose is documenting the forbidden terms; exempt from
# any sweep. Add sparingly. Path is relative to repo root.
EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        "scripts/smoke/grep_gate_stale_terms.py",
        "docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md",
        "docs/superpowers/specs/2026-05-17-phase-gate-hardening-round6-review-notes.md",
        "docs/adr/2026-05-17-approver-provenance-and-execution-mode.md",
        "docs/adr/2026-05-17-audit-canonicalization-locking-and-state-trust.md",
        "docs/adr/2026-05-17-autopilot-guards-and-manual-handoff.md",
    }
)


def collect_files(globs: tuple[str, ...]) -> list[Path]:
    seen: set[Path] = set()
    for glob in globs:
        for path in REPO_ROOT.glob(glob):
            if path.is_file() and path.suffix == ".md" or path.suffix == ".py":
                seen.add(path.resolve())
    return sorted(seen)


def scan(files: list[Path], terms: tuple[str, ...]) -> list[tuple[Path, int, str]]:
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
            for term in terms:
                if term in line:
                    hits.append((path, lineno, term))
    return hits


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--launcher-only",
        action="store_true",
        help="Sweep only adapter command files for forbidden launcher strings (S00.5).",
    )
    group.add_argument(
        "--full",
        action="store_true",
        help="Sweep the full §12.14 glob for every forbidden term (S14).",
    )
    args = parser.parse_args(argv)

    if args.launcher_only:
        files = collect_files(LAUNCHER_GLOBS)
        terms = LAUNCHER_TERMS
        mode = "launcher-only"
    else:
        files = collect_files(FULL_GLOBS)
        terms = LAUNCHER_TERMS + FULL_SWEEP_TERMS
        mode = "full"

    hits = scan(files, terms)
    if hits:
        sys.stderr.write(f"FAIL grep-gate ({mode}): {len(hits)} forbidden-term hit(s)\n")
        for path, lineno, term in hits:
            rel = path.relative_to(REPO_ROOT).as_posix()
            sys.stderr.write(f"  {rel}:{lineno}: {term!r}\n")
        sys.stderr.write(
            "\nFix: remove the listed strings from the installed artifacts.\n"
            "Alternative launchers belong to the deprecation window only and "
            "MUST NOT ship in slash-command bodies, skills, or planning files "
            "after S00.5-launcher.\n"
        )
        return 1

    sys.stdout.write(
        f"OK grep-gate ({mode}): scanned {len(files)} file(s); 0 forbidden terms.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
