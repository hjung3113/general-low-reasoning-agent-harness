"""Malformed-state diagnostic helper (T1-M).

Plan: .planning/phases/02b-hardening/plans/02b-09-T1-M-PLAN.md
Contract: .planning/phases/02b-hardening/CONTRACT-PIN.md §1, §4, §5.1, §6.3
ADR: docs/adr/2026-05-16-hardening-bundle.md (ADR-005, ADR-003a Artifact 1)

The sole sanctioned reader for managed harness state files
(`.scratch/phase-state.json`, `.harness/installed-manifest.json`) plus the
managed-block / frontmatter wrapper for `.planning/STATE.md` and
`.planning/ROADMAP.md`.

Contract:
- Malformed input never surfaces as an uncaught `JSONDecodeError`,
  `ValueError`, or `KeyError` traceback to the operator.
- Every failure raises `SystemExit(EXIT_UNPARSEABLE_JSON)` (code 5) AFTER
  writing a single-line `error:` diagnostic to stderr that names the file
  path and (when available) line:column, with a one-line remediation hint.
- Remediation hint precedence (most-specific first):
    1. If a sidecar `<basename>.pre-repair.*.bak.resume.json` exists under
       `.harness/backups/`, recommend `harness migrate state --resume`.
    2. Else if at least one `<basename>.pre-repair.*.bak` exists under
       `.harness/backups/`, recommend restoring from the newest backup.
    3. Else use the ADR-005 / ADR-003a Artifact 1 default template.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from lib.exitcodes import EXIT_UNPARSEABLE_JSON


__all__ = [
    "UnparseableStateError",
    "load_state_json",
    "parse_state_markdown",
    "ParsedStateDoc",
]


# ---------------------------------------------------------------------------
# Exception type (per CONTRACT-PIN §5.1: T0-5 imports this to wrap into
# RepairRefusedError; T1-M itself raises SystemExit(5) at the helper boundary).
# ---------------------------------------------------------------------------


class UnparseableStateError(Exception):
    """Raised internally by helpers before being translated to SystemExit(5).

    Attributes per CONTRACT-PIN §5.1:
      - path: Path of the offending file.
      - json_decode_error: the underlying JSONDecodeError (or None for
        non-JSON failures such as empty file).
    """

    def __init__(
        self,
        message: str,
        *,
        path: Path,
        json_decode_error: json.JSONDecodeError | None = None,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.json_decode_error = json_decode_error


# ---------------------------------------------------------------------------
# Diagnostic formatting
# ---------------------------------------------------------------------------


_DEFAULT_HINT = (
    "fix the JSON or restore from a backup before retrying."
)


def _backups_dir_for(path: Path) -> Path:
    """Resolve the `.harness/backups/` directory peer for a state file.

    State files live at e.g. `<repo>/.scratch/phase-state.json` or
    `<repo>/.harness/installed-manifest.json`. The backups directory is
    always `<repo>/.harness/backups/`. We resolve by walking up to find a
    `.harness/` peer of the file's parent, falling back to
    `<file.parent>/.harness/backups/` for repo-rooted tests.
    """
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    for ancestor in (resolved.parent, *resolved.parents):
        candidate = ancestor / ".harness" / "backups"
        if candidate.is_dir():
            return candidate
        # Stop at the apparent repo root (parent of .scratch or .harness).
        if (ancestor / ".scratch").exists() or (ancestor / ".harness").exists():
            return candidate
    return resolved.parent / ".harness" / "backups"


def _remediation_hint(path: Path) -> str:
    """Return the remediation-hint sentence (no leading newline)."""
    backups_dir = _backups_dir_for(path)
    if not backups_dir.is_dir():
        return _DEFAULT_HINT
    basename = path.name
    sidecar_glob = f"{basename}.pre-repair.*.bak.resume.json"
    bak_glob = f"{basename}.pre-repair.*.bak"
    try:
        sidecars = sorted(backups_dir.glob(sidecar_glob))
    except OSError:
        sidecars = []
    if sidecars:
        return (
            "run 'harness migrate state --resume' to continue from the most "
            "recent in-progress migration."
        )
    try:
        baks = sorted(p for p in backups_dir.glob(bak_glob) if not p.name.endswith(".resume.json"))
    except OSError:
        baks = []
    if baks:
        newest = baks[-1].name
        return f"restore from .harness/backups/{newest}"
    return _DEFAULT_HINT


def _emit_and_exit(path: Path, summary: str, *, hint: str | None = None) -> None:
    """Write the diagnostic line(s) to stderr and SystemExit(5)."""
    if hint is None:
        hint = _remediation_hint(path)
    line = f"error: {summary}; {hint}"
    print(line, file=sys.stderr)
    raise SystemExit(EXIT_UNPARSEABLE_JSON)


# ---------------------------------------------------------------------------
# load_state_json
# ---------------------------------------------------------------------------


def load_state_json(path: Path) -> dict:
    """Read and parse a managed-state JSON file.

    On success returns the parsed object (typically a dict). On failure
    writes a single-line `error:` diagnostic to stderr and raises
    `SystemExit(EXIT_UNPARSEABLE_JSON)` (exit code 5).
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        _emit_and_exit(
            path,
            f"{path} could not be read ({exc.__class__.__name__}: {exc})",
        )
    if text == "":
        _emit_and_exit(path, f"{path} is unparseable (empty file)")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        summary = (
            f"{path} is unparseable at line {exc.lineno}:col {exc.colno}: {exc.msg}"
        )
        _emit_and_exit(path, summary)
    except UnicodeDecodeError as exc:
        _emit_and_exit(path, f"{path} is unparseable (invalid UTF-8: {exc.reason})")
    # Unreachable: _emit_and_exit always raises.
    raise AssertionError("unreachable")  # pragma: no cover


# ---------------------------------------------------------------------------
# parse_state_markdown (managed-block + frontmatter wrapper) — populated by
# subsequent commits (duplicate-slug, frontmatter). Stub now so importers
# can rely on the symbol.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedStateDoc:
    """Result of `parse_state_markdown` — frontmatter + block index."""

    frontmatter: dict
    blocks: dict  # slug -> ParsedBlock (from managed_block)
    text: str


def parse_state_markdown(path: Path) -> ParsedStateDoc:  # pragma: no cover - filled later
    raise NotImplementedError(
        "parse_state_markdown is wired by subsequent T1-M commits"
    )
