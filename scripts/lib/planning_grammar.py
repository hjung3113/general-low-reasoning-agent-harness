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
