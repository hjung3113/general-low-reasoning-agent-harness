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

import errno
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from lib.exitcodes import EXIT_UNPARSEABLE_JSON
from lib import managed_block
from lib import roadmap_state


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


_MAX_STATE_FILE_BYTES = 8 * 1024 * 1024


def _enforce_size_cap(path: Path) -> None:
    """Refuse to read state files larger than 8 MiB (T1-M-SecM2).

    Cheap stat() check before the os.open so we don't slurp tens of MiB
    of attacker-planted content into memory. Sparse files count by their
    apparent size (st_size), which matches the test using seek+truncate.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return  # let _read_text_no_symlinks surface the OSError
    if size > _MAX_STATE_FILE_BYTES:
        _emit_and_exit(
            path,
            f"{path} is file too large ({size} bytes > {_MAX_STATE_FILE_BYTES} cap)",
        )


def _read_text_no_symlinks(path: Path) -> str:
    """Read `path` as UTF-8 text, refusing to traverse symlinks (T1-M-SecM1).

    Uses `os.open(path, O_RDONLY | O_NOFOLLOW)` so that an ELOOP fires the
    moment the kernel detects a symlink at the final path component. On
    ELOOP we surface a SystemExit(5) with "symlink not permitted" so the
    operator cannot be fooled into reading attacker-controlled content via
    a planted symlink in `.scratch/` or `.harness/`.
    """
    flags = os.O_RDONLY
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    flags |= nofollow
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            _emit_and_exit(path, f"symlink not permitted at {path}")
        # Re-raise as UnicodeDecodeError-compatible OSError; caller wraps.
        raise
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(fd)
    return b"".join(chunks).decode("utf-8")


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
    _enforce_size_cap(path)
    try:
        text = _read_text_no_symlinks(path)
    except UnicodeDecodeError as exc:
        _emit_and_exit(path, f"{path} is unparseable (invalid UTF-8: {exc.reason})")
        return  # pragma: no cover
    except OSError as exc:
        _emit_and_exit(
            path,
            f"{path} could not be read ({exc.__class__.__name__}: {exc})",
        )
        return  # pragma: no cover
    if text == "":
        _emit_and_exit(path, f"{path} is unparseable (empty file)")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        # Trim "starting at" / "at line N column N" tails from exc.msg since
        # we already render line:col separately — keeps diagnostic under
        # the 200-char operator-fit budget on long paths.
        msg = re.sub(r"\s+(starting at|at line \d+ column \d+).*$", "", exc.msg).strip()
        summary = f"{path} is unparseable at line {exc.lineno}:col {exc.colno}: {msg}"
        _emit_and_exit(path, summary)
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


def _validate_frontmatter_delimiters(path: Path, text: str) -> None:
    """Raise SystemExit(5) if the document opens with `---` but never closes.

    The legacy `parse_frontmatter` returns whatever pairs it managed to read
    when the closing `---` is absent, which hides the corruption from the
    operator. We require a matching close before the first body heading
    (or end of file).
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return  # no frontmatter at all
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return  # well-formed
    _emit_and_exit(
        path,
        (
            f"{path}: unclosed frontmatter delimiter starting at line 1; "
            f"add a closing '---' line before the document body"
        ),
    )


_BEGIN_LINE_RE = re.compile(
    r"^<!-- HARNESS:BEGIN managed:(?P<slug>[^\s]+) v1 -->\s*$",
    re.MULTILINE,
)


def _find_begin_lines(text: str) -> list[tuple[int, str]]:
    """Return [(1-based line number, slug-literal-as-written)] for every
    `<!-- HARNESS:BEGIN managed:<X> v1 -->` line in `text`.

    Note: matches even invalid slugs (e.g., "Foo_BAD") so we can cite the
    line that triggered a slug-rejection.
    """
    out: list[tuple[int, str]] = []
    for match in _BEGIN_LINE_RE.finditer(text):
        # 1-based line number: count newlines before the match start.
        line_no = text.count("\n", 0, match.start()) + 1
        out.append((line_no, match.group("slug")))
    return out


def _find_duplicate_slug_lines(text: str, slug: str) -> list[int]:
    """Return all 1-based BEGIN line numbers where `slug` appears."""
    return [n for n, s in _find_begin_lines(text) if s == slug]


def _classify_managed_block_error(text: str, exc: ValueError) -> str:
    """Translate a `parse_blocks` ValueError into a human summary fragment.

    Returns the trailing portion of the diagnostic (everything after the
    "<path> is unparseable: " prefix), which the caller wraps and emits.
    """
    msg = str(exc)
    if msg.startswith("Duplicate managed-block slug"):
        # Strip the quoted slug literal: "Duplicate managed-block slug: 'foo'"
        slug_match = re.search(r"'([^']+)'", msg)
        slug = slug_match.group(1) if slug_match else "<unknown>"
        lines = _find_duplicate_slug_lines(text, slug)
        line_refs = ", ".join(str(n) for n in lines) if lines else "?"
        return (
            f"duplicate managed-block slug 'managed:{slug}' appears at line(s) "
            f"{line_refs}"
        )
    if msg.startswith("Unbalanced managed-block markers") or msg.startswith(
        "Malformed managed-block"
    ):
        begins = _find_begin_lines(text)
        first_line = begins[0][0] if begins else "?"
        return (
            f"unbalanced managed-block markers; first unmatched BEGIN at line "
            f"{first_line}"
        )
    if msg.startswith("Invalid managed-block slug"):
        # Locate the offending begin line by finding any BEGIN whose slug
        # fails the strict slug regex.
        for line_no, slug in _find_begin_lines(text):
            if not re.fullmatch(r"[a-z][a-z0-9-]*", slug):
                return (
                    f"invalid managed-block slug 'managed:{slug}' at line "
                    f"{line_no} (slugs must match [a-z][a-z0-9-]*)"
                )
        return f"invalid managed-block slug: {msg}"
    # Fallback: emit the raw library message with no line info.
    return f"managed-block parse failed: {msg}"


def parse_state_markdown(path: Path) -> ParsedStateDoc:
    """Parse a STATE.md / ROADMAP.md document with diagnostic exit on failure.

    On success returns a `ParsedStateDoc` carrying the parsed frontmatter,
    managed-block index, and source text. On failure writes a single-line
    `error:` diagnostic to stderr (with file + line citation when available)
    and raises `SystemExit(EXIT_UNPARSEABLE_JSON)`.

    Currently wraps:
      - `managed_block.parse_blocks` (duplicate slug, unbalanced markers,
        invalid slug)
      - `roadmap_state.parse_frontmatter` (best-effort; frontmatter delimiter
        validation is added in a subsequent commit)

    Slug-validation note: `parse_blocks` only rejects invalid slugs when
    `replace_block`/`render_block` is invoked; raw parsing silently skips
    lines that don't match `[a-z][a-z0-9-]*`. We therefore pre-scan for
    BEGIN lines whose slug fails the strict regex and raise here.
    """
    path = Path(path)
    _enforce_size_cap(path)
    try:
        text = _read_text_no_symlinks(path)
    except OSError as exc:
        _emit_and_exit(
            path,
            f"{path} could not be read ({exc.__class__.__name__}: {exc})",
        )
    except UnicodeDecodeError as exc:
        _emit_and_exit(path, f"{path} is unparseable (invalid UTF-8: {exc.reason})")

    # Frontmatter delimiter validation: if the first non-blank line is `---`
    # we require a closing `---` BEFORE any heading or end of file. The
    # legacy parse_frontmatter silently returns partial data on missing
    # close, which hides the corruption.
    _validate_frontmatter_delimiters(path, text)

    # Pre-scan: reject any BEGIN line whose slug fails the strict regex.
    # `parse_blocks` would silently skip these because its regex requires
    # the strict slug shape, leaving an unbalanced-marker error that hides
    # the real cause.
    strict_slug = re.compile(r"[a-z][a-z0-9-]*")
    for line_no, slug in _find_begin_lines(text):
        if not strict_slug.fullmatch(slug):
            _emit_and_exit(
                path,
                (
                    f"{path} contains invalid managed-block slug 'managed:{slug}' "
                    f"at line {line_no} (slugs must match [a-z][a-z0-9-]*)"
                ),
            )

    try:
        blocks = managed_block.parse_blocks(text)
    except ValueError as exc:
        summary = _classify_managed_block_error(text, exc)
        # Acknowledge frontmatter if it parsed cleanly so the operator
        # knows the failure is in the body, not the header.
        prefix = ""
        if text.lstrip().startswith("---"):
            prefix = "frontmatter parsed; body error — "
        _emit_and_exit(path, f"{path}: {prefix}{summary}")

    # Frontmatter: best-effort for now. Stricter delimiter validation lands
    # in a subsequent T1-M commit.
    try:
        frontmatter = roadmap_state.parse_frontmatter(text)
    except Exception as exc:  # defensive: parse_frontmatter is permissive today
        _emit_and_exit(
            path,
            f"{path}: frontmatter parse failed ({exc.__class__.__name__}: {exc})",
        )

    return ParsedStateDoc(frontmatter=frontmatter, blocks=blocks, text=text)
