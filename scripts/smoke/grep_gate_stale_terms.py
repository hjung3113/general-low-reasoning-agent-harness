#!/usr/bin/env python3
"""Grep-gate: consolidated stale-term sweep (S14, §9 line 1117).

Modes
-----
``--launcher-only``
    Legacy S00.5 mode. Walks only adapter command files
    (``.roo/commands/*.md``, ``.opencode/commands/*.md``) and forbids
    the alternative launcher strings declared in §7 + §12.14:

      python3 scripts/harness.py
      python scripts/harness.py
      py scripts/harness.py
      scripts/show_phase_status.py

(default / ``--full``)
    S14 full sweep. Applies every forbidden-term category to its
    designated scope (see CATEGORIES below). Different term categories
    have different scopes — some are checked only in adapter-facing
    files; others extend to ``scripts/lib/`` and ``docs/superpowers/``.

Exit codes
----------
``0`` — no forbidden strings found.
``1`` — one or more matches; prints ``file:line: <pattern>`` on stderr.

Usage
-----
    python scripts/smoke/grep_gate_stale_terms.py                  # full
    python scripts/smoke/grep_gate_stale_terms.py --full           # full (explicit)
    python scripts/smoke/grep_gate_stale_terms.py --launcher-only  # legacy S00.5

Scoping rationale (§C of S14)
------------------------------
* ``automation_mode`` — legitimately referenced by legacy-validation code
  (``scripts/lib/phase_state.py``, ``scripts/lib/check.py``). Checked only in
  adapter-facing files (``.roo/``, ``.opencode/``, ``docs/superpowers/``
  minus exempted specs).

* ``--chain`` / ``--auto`` (deprecated harness CLI flags) — Roo workflow
  skills, rules, and plans legitimately describe these flags as
  *prompt-level controls* (NOT as harness CLI invocations). Checked only
  in slash-command Markdown files (``.roo/commands/*.md``,
  ``.opencode/commands/*.md``).

* ``containment_`` — uses word-boundary regex so ``windows_containment_*``
  sub-reason values (inside ``scripts/lib/safe_open.py``,
  ``scripts/lib/phase_autopilot.py``) are NOT false-positives.

* ``HARNESS_HUMAN`` — explicitly documented as forbidden in adapter files
  (``scripts/lib/phase_approve.py`` references it only in security-comment
  context explaining it is NOT consulted; ``scripts/release_smoke_test.py``
  uses ``pop("HARNESS_HUMAN", None)`` in test isolation). Checked in
  adapter-facing files plus ``scripts/lib/`` minus the above exemptions.

* Launcher strings (``python3 scripts/harness.py`` etc.) — checked in
  slash-command Markdown only (adapter commands), NOT in historical
  planning docs.

Consolidation (§A of S14)
--------------------------
This file is the *single source of truth* for all stale-term categories.
``grep_gate_slash_rename.py`` continues to own its slash-command-rename
regex logic (word-boundary ``/fsd-phase`` / ``/fsd-chain-phase``).
``grep_gate_release_terms.py`` continues its narrow adapter-only sweep
(enforced in CI step before release). Both remain as independent scripts
for backward compatibility of CI invocations.

Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md §9
Slice: S14-sweep
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Path globs
# ---------------------------------------------------------------------------

# Slash-command Markdown files only (adapter entry points).
SLASH_CMD_GLOBS: tuple[str, ...] = (
    ".roo/commands/*.md",
    ".opencode/commands/*.md",
)

# All adapter-facing files: slash commands + skills + rules + superpowers docs.
ADAPTER_GLOBS: tuple[str, ...] = (
    ".roo/commands/*.md",
    ".roo/skills/**/*.md",
    ".roo/rules/**/*.md",
    ".roo/rules-orchestrator/**/*.md",
    ".opencode/commands/*.md",
    "docs/superpowers/skills/**/*.md",
    "docs/superpowers/rules/**/*.md",
)

# Production scripts: lib + smoke + harness entry point.
SCRIPTS_GLOBS: tuple[str, ...] = (
    "scripts/lib/**/*.py",
    "scripts/smoke/**/*.py",
    "scripts/harness.py",
)

# Docs (adapter-facing + scripts).
ALL_GLOBS: tuple[str, ...] = SLASH_CMD_GLOBS + ADAPTER_GLOBS + SCRIPTS_GLOBS

# Launcher-only mode (legacy S00.5).
LAUNCHER_GLOBS: tuple[str, ...] = SLASH_CMD_GLOBS

# ---------------------------------------------------------------------------
# Forbidden alternative launcher strings (checked in --launcher-only AND
# in SLASH_CMD_GLOBS during --full sweep).
# ---------------------------------------------------------------------------
LAUNCHER_TERMS: tuple[str, ...] = (
    "python3 scripts/harness.py",
    "python scripts/harness.py",
    "py scripts/harness.py",
    "scripts/show_phase_status.py",
)

# ---------------------------------------------------------------------------
# Full stale-term categories (S14 §9 line 1117 list).
# Each entry: (term_or_pattern, use_regex, scope_globs, human_label)
# ---------------------------------------------------------------------------

# Scope: adapter files where these deprecated env / field names must not appear.
_ADAPTER_SCOPE = ADAPTER_GLOBS

# Scope: slash-command Markdown only (harness CLI flag references in commands).
_SLASH_SCOPE = SLASH_CMD_GLOBS

# ---------------------------------------------------------------------------
# Files whose entire purpose is documenting the forbidden terms; exempt from
# any sweep. Add sparingly. Path is relative to repo root.
# ---------------------------------------------------------------------------
EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        # This gate script itself
        "scripts/smoke/grep_gate_stale_terms.py",
        # Sibling gate scripts (not adapter artifacts)
        "scripts/smoke/grep_gate_release_terms.py",
        "scripts/smoke/grep_gate_slash_rename.py",
        # Design spec — intentionally documents both old and new names in
        # transition tables (§9, §12.14 etc.)
        "docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md",
        # Round-6 review notes — historical review document
        "docs/superpowers/specs/2026-05-17-phase-gate-hardening-round6-review-notes.md",
        # ADRs — contain transition tables with old names; historical context.
        "docs/adr/2026-05-17-approver-provenance-and-execution-mode.md",
        "docs/adr/2026-05-17-audit-canonicalization-locking-and-state-trust.md",
        "docs/adr/2026-05-17-autopilot-guards-and-manual-handoff.md",
        # phase_approve.py — HARNESS_HUMAN appears only in security comments
        # explicitly stating the env var is NOT consulted (Round-4 BLOCK fix).
        "scripts/lib/phase_approve.py",
        # v0.8.0_todo ux-polish spec — forward-looking note that mentions
        # the old slash name as a problem statement; deferred/historical.
        "docs/superpowers/specs/v0.8.0_todo/2026-05-17-ux-polish.md",
    }
)

# Additional per-term exemptions: {term -> frozenset of rel paths exempt for
# that term only}.  Used when a file is mostly clean but has one legitimate
# reference to a single term.
TERM_EXEMPT_PATHS: dict[str, frozenset[str]] = {
    # automation_mode: legacy-validation/coercion code that MUST reference
    # the old field name to handle pre-v2 state files.
    "automation_mode": frozenset(
        {
            "scripts/lib/phase_state.py",      # _load_state: legacy coercion §1.1
            "scripts/lib/check.py",            # legacy validator (automation_mode field)
            "scripts/lib/planning_status.py",  # display: reads legacy field
            "scripts/lib/project_dashboard/renderer.py",  # display: reads legacy field
        }
    ),
    # --auto / --chain: Roo workflow prompt-level flags (NOT harness CLI flags).
    # .roo/commands/README.md and phase-execute.md are the canonical reference
    # docs that DEFINE these Roo prompt flags (§4 Automation Flags).
    "--auto": frozenset(
        {
            ".roo/commands/README.md",
            ".roo/commands/phase-execute.md",
        }
    ),
    "--chain": frozenset(
        {
            ".roo/commands/README.md",
            ".roo/commands/phase-execute.md",
        }
    ),
}


# ---------------------------------------------------------------------------
# Scan helpers
# ---------------------------------------------------------------------------

class _TermCheck:
    """Encapsulates one forbidden-term check with optional regex matching."""

    def __init__(
        self,
        term: str,
        pattern: re.Pattern | None = None,
    ) -> None:
        self.term = term
        self._pattern = pattern

    def found_in(self, line: str) -> bool:
        if self._pattern is not None:
            return bool(self._pattern.search(line))
        return self.term in line


def _make_checks(terms: tuple[str, ...]) -> list[_TermCheck]:
    checks = []
    for term in terms:
        if term == "containment_":
            # Word-boundary: must not be preceded by [A-Za-z0-9_] so that
            # 'windows_containment_degraded' is NOT matched.
            checks.append(
                _TermCheck(term, re.compile(r"(?<![A-Za-z0-9_])containment_"))
            )
        elif term == "--auto":
            # Must not be followed by [a-z] to avoid matching --autopilot-guards
            checks.append(_TermCheck(term, re.compile(r"--auto(?![a-zA-Z])")))
        elif term == "--chain":
            # Must not be followed by [-\w] to avoid matching --chain-phase
            checks.append(_TermCheck(term, re.compile(r"--chain(?![-\w])")))
        else:
            checks.append(_TermCheck(term))
    return checks


def collect_files(globs: tuple[str, ...]) -> list[Path]:
    seen: set[Path] = set()
    for glob in globs:
        for path in REPO_ROOT.glob(glob):
            if path.is_file() and (path.suffix in (".md", ".py")):
                seen.add(path.resolve())
    return sorted(seen)


def scan_category(
    files: list[Path],
    checks: list[_TermCheck],
    extra_exempt: frozenset[str] | None = None,
) -> list[tuple[Path, int, str]]:
    """Scan *files* for *checks*; return (path, lineno, term) triples."""
    hits: list[tuple[Path, int, str]] = []
    for path in files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in EXEMPT_PATHS:
            continue
        if extra_exempt and rel in extra_exempt:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for check in checks:
                # Per-term exemption check
                term_exempt = TERM_EXEMPT_PATHS.get(check.term)
                if term_exempt and rel in term_exempt:
                    continue
                if check.found_in(line):
                    hits.append((path, lineno, check.term))
    return hits


# ---------------------------------------------------------------------------
# Mode: --launcher-only
# ---------------------------------------------------------------------------

def run_launcher_only() -> int:
    files = collect_files(LAUNCHER_GLOBS)
    checks = _make_checks(LAUNCHER_TERMS)
    hits = scan_category(files, checks)
    if hits:
        sys.stderr.write(f"FAIL grep-gate (launcher-only): {len(hits)} forbidden-term hit(s)\n")
        for path, lineno, term in hits:
            rel = path.relative_to(REPO_ROOT).as_posix()
            sys.stderr.write(f"  {rel}:{lineno}: {term!r}\n")
        sys.stderr.write(
            "\nFix: remove the listed alternative launcher strings from adapter command files.\n"
            "Alternative launchers MUST NOT ship in slash-command bodies after S00.5-launcher.\n"
        )
        return 1
    sys.stdout.write(
        f"OK grep-gate (launcher-only): scanned {len(files)} file(s); 0 forbidden terms.\n"
    )
    return 0


# ---------------------------------------------------------------------------
# Mode: --full (default)
# ---------------------------------------------------------------------------

# Category definitions: (label, term_tuple, scope_globs)
# Each category is scanned independently with its own scope.
_FULL_CATEGORIES: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    # 1. Alternative launchers in slash-command Markdown.
    (
        "alt-launchers-in-slash-cmds",
        LAUNCHER_TERMS,
        SLASH_CMD_GLOBS,
    ),
    # 2. Deprecated CLI flags — only in slash-command Markdown.
    (
        "deprecated-cli-flags-in-slash-cmds",
        ("--chain", "--auto"),
        SLASH_CMD_GLOBS,
    ),
    # 3. Deprecated field names — adapter-facing files only.
    #    (migration code in scripts/lib/ is per-term exempted)
    (
        "deprecated-fields-in-adapters",
        (
            "automation_mode",
            "containment_",
            "last_good_commit_sha",
            "autopilot_budgets_remaining",
        ),
        ADAPTER_GLOBS,
    ),
    # 4. Deprecated verbs — adapter-facing files.
    (
        "deprecated-verbs-in-adapters",
        ("chain --resume", "chain --abort"),
        ADAPTER_GLOBS,
    ),
    # 5. Deprecated env var — adapter-facing files.
    #    (phase_approve.py is globally exempted; it references HARNESS_HUMAN
    #     only in security comments stating it is NOT consulted)
    (
        "deprecated-env-in-adapters",
        ("HARNESS_HUMAN",),
        ADAPTER_GLOBS,
    ),
]


def run_full() -> int:
    all_hits: list[tuple[Path, int, str]] = []
    total_files: set[Path] = set()

    for label, terms, globs in _FULL_CATEGORIES:
        files = collect_files(globs)
        total_files.update(files)
        checks = _make_checks(terms)
        hits = scan_category(files, checks)
        all_hits.extend(hits)

    if all_hits:
        sys.stderr.write(f"FAIL grep-gate (full): {len(all_hits)} forbidden-term hit(s)\n")
        for path, lineno, term in all_hits:
            rel = path.relative_to(REPO_ROOT).as_posix()
            sys.stderr.write(f"  {rel}:{lineno}: {term!r}\n")
        sys.stderr.write(
            "\nFix: remove the listed strings from the installed artifacts.\n"
            "See design §9 line 1117 for the canonical forbidden-term list.\n"
            "Terms renamed: automation_mode→execution_mode, "
            "containment_*→network_guard_*, "
            "autopilot_budgets_remaining→cli_budgets_remaining, "
            "HARNESS_HUMAN→gitconfig-based identity.\n"
            "Alternative launchers must not appear in adapter slash-command bodies.\n"
        )
        return 1

    sys.stdout.write(
        f"OK grep-gate (full): scanned {len(total_files)} unique file(s); "
        "0 forbidden terms.\n"
    )
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--launcher-only",
        action="store_true",
        help="Legacy S00.5 mode: sweep only adapter command files for forbidden launcher strings.",
    )
    group.add_argument(
        "--full",
        action="store_true",
        help="S14 full sweep: all forbidden-term categories in their designated scopes (default).",
    )
    args = parser.parse_args(argv)

    if args.launcher_only:
        return run_launcher_only()
    # --full is the default (even without the flag)
    return run_full()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
