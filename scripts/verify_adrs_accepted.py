#!/usr/bin/env python3
"""Verify that every ADR file passed on argv is Status: Accepted.

Required by S00-adr-prep slice (phase 02c-phase-gate-hardening). Implements the
machine-checkable gate that blocks code-slice entry until the three Round-7
ADRs are landed Accepted:

  docs/adr/2026-05-17-approver-provenance-and-execution-mode.md
  docs/adr/2026-05-17-audit-canonicalization-locking-and-state-trust.md
  docs/adr/2026-05-17-autopilot-guards-and-manual-handoff.md

Each ADR must contain:
  - a single H1 title line starting with `# ADR`
  - a `## Status` section
  - first non-empty content line under `## Status` matching `^Accepted\\b`
  - a `## Context` section
  - a `## Decision` section
  - a `## Consequences` section

Exit codes:
  0  all ADRs pass
  1  one or more ADRs missing or non-conforming
  2  no ADR paths provided on argv
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REQUIRED_HEADINGS = ["## Status", "## Context", "## Decision", "## Consequences"]
ACCEPTED_LINE_RE = re.compile(r"^Accepted\b")
H1_RE = re.compile(r"^# ADR\b")


def check_adr(path: Path) -> list[str]:
    """Return a list of failure reasons; empty list means pass."""
    failures: list[str] = []

    if not path.exists():
        return [f"file not found: {path}"]
    if not path.is_file():
        return [f"not a regular file: {path}"]

    text = path.read_text(encoding="utf-8")
    if text.startswith("﻿"):
        failures.append("UTF-8 BOM forbidden in ADR file")
    lines = text.splitlines()

    if not lines or not H1_RE.match(lines[0].strip()):
        failures.append("first line must start with `# ADR`")

    for heading in REQUIRED_HEADINGS:
        if not any(line.strip() == heading for line in lines):
            failures.append(f"missing required heading: {heading}")

    status_idx = next(
        (i for i, line in enumerate(lines) if line.strip() == "## Status"),
        None,
    )
    if status_idx is None:
        return failures

    accepted_found = False
    for line in lines[status_idx + 1 :]:
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        if not stripped:
            continue
        if ACCEPTED_LINE_RE.match(stripped):
            accepted_found = True
        break

    if not accepted_found:
        failures.append("first content line under `## Status` must match `^Accepted\\b`")

    return failures


def main(argv: list[str]) -> int:
    if len(argv) <= 1:
        sys.stderr.write(
            "usage: verify_adrs_accepted.py <adr-path> [<adr-path> ...]\n"
            "Fix: pass at least one ADR markdown path.\n"
        )
        return 2

    bad = 0
    for raw_path in argv[1:]:
        path = Path(raw_path)
        failures = check_adr(path)
        if failures:
            bad += 1
            sys.stderr.write(f"FAIL {path}:\n")
            for reason in failures:
                sys.stderr.write(f"  - {reason}\n")
        else:
            sys.stdout.write(f"OK   {path}\n")

    if bad:
        sys.stderr.write(
            f"\n{bad} ADR(s) failed the Status: Accepted contract.\n"
            f"Fix: ensure every required heading is present and the first content line "
            f"under `## Status` matches `^Accepted\\b`.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
