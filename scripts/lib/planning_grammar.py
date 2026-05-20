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


# ---------------------------------------------------------------------------
# STATE / ROADMAP regex primitives
# ---------------------------------------------------------------------------

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
    r"(?:[^\S\n]*-[^\S\n]*(?P<summary>[^\n]*))?$",
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


def _zero_pad(raw: str) -> str:
    digits_match = re.match(r"\d+", raw)
    if not digits_match:
        return raw
    digits = digits_match.group(0)
    return digits.zfill(2) + raw[len(digits):]


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
