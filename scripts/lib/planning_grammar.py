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
