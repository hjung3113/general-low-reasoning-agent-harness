"""Managed append-block plumbing: parse, render, and merge marker-delimited blocks."""
from __future__ import annotations

import difflib
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from lib.manifest import ManifestEntry

# ---------------------------------------------------------------------------
# Diff cap: when falling back to whole-file diff (malformed markers), we cap
# the diff output at ~200 lines / ~5 KB so a megabyte destination file doesn't
# flood stderr. The managed-block diff (parse succeeds) is uncapped because it
# is already scoped to the block, which is always small.
# ---------------------------------------------------------------------------
_FALLBACK_DIFF_MAX_LINES = 200
_FALLBACK_DIFF_MAX_BYTES = 5_000


# ---------------------------------------------------------------------------
# Runtime version – mirrors the authoritative copy in harness.py via lazy
# lookup so that test patches and run()-time updates are respected.
# ---------------------------------------------------------------------------

def _active_harness_version() -> str:
    harness_mod = sys.modules.get("harness")
    if harness_mod is not None:
        return getattr(harness_mod, "HARNESS_VERSION", "0.0.0-dev+unknown")
    return "0.0.0-dev+unknown"


# ---------------------------------------------------------------------------
# Small utilities (self-contained; duplicated from harness.py to avoid
# circular imports)
# ---------------------------------------------------------------------------

def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_payload(text: str) -> str:
    return text.rstrip("\n") + "\n"


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_text_file(destination: Path, text: str) -> None:
    """Thin wrapper: delegates to harness.write_text_file when available."""
    harness_mod = sys.modules.get("harness")
    if harness_mod is not None:
        harness_mod.write_text_file(destination, text)
        return
    # Fallback (e.g. when run outside the harness context)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AppendBlockPlan:
    updated_text: str | None
    proposed_block: str
    applied_sha256: str | None
    conflict: bool = False


@dataclass(frozen=True)
class ParsedAppendBlock:
    start: int
    end: int
    text: str
    payload: str


# ---------------------------------------------------------------------------
# Marker helpers
# ---------------------------------------------------------------------------

def marker_start(entry: ManifestEntry) -> str:
    return f"# >>> low-reasoning-harness:{entry.path.as_posix()} v{_active_harness_version()}"


def marker_end_for_path(path_text: str) -> str:
    return f"# <<< low-reasoning-harness:{path_text}"


def marker_end(entry: ManifestEntry) -> str:
    return marker_end_for_path(entry.path.as_posix())


# ---------------------------------------------------------------------------
# Render / parse
# ---------------------------------------------------------------------------

def render_append_block(source: Path, entry: ManifestEntry) -> str:
    return (
        marker_start(entry)
        + "\n"
        + normalize_payload(source.read_text(encoding="utf-8"))
        + marker_end(entry)
        + "\n"
    )


def parse_append_block(text: str, path_text: str) -> ParsedAppendBlock | None:
    escaped = re.escape(path_text)
    start_pattern = re.compile(rf"^# >>> low-reasoning-harness:{escaped} v(?P<version>[^\s]+)$")
    end_line = marker_end_for_path(path_text)
    lines = text.splitlines(keepends=True)
    start_indexes: list[int] = []
    end_indexes: list[int] = []
    offset = 0
    for line in lines:
        stripped = line.rstrip("\r\n")
        if start_pattern.fullmatch(stripped):
            start_indexes.append(offset)
        if stripped == end_line:
            end_indexes.append(offset + len(line))
        offset += len(line)
    if not start_indexes and not end_indexes:
        return None
    if len(start_indexes) != 1 or len(end_indexes) != 1 or start_indexes[0] >= end_indexes[0]:
        raise ValueError(f"Malformed managed-append block for {path_text}")
    block_text = text[start_indexes[0] : end_indexes[0]]
    block_lines = block_text.splitlines(keepends=True)
    payload = "".join(block_lines[1:-1])
    return ParsedAppendBlock(start=start_indexes[0], end=end_indexes[0], text=block_text, payload=payload)


# ---------------------------------------------------------------------------
# Merge helpers
# ---------------------------------------------------------------------------

def append_block_to_text(existing: str, block: str) -> str:
    if not existing:
        return block
    separator = "" if existing.endswith("\n\n") else "\n" if existing.endswith("\n") else "\n\n"
    return existing + separator + block


def replace_block(text: str, parsed: ParsedAppendBlock, block: str) -> str:
    return text[: parsed.start] + block + text[parsed.end :]


# ---------------------------------------------------------------------------
# Conflict diff helper
# ---------------------------------------------------------------------------

def _managed_append_conflict_diff(destination: Path, plan: "AppendBlockPlan", entry: "ManifestEntry") -> str:
    """Return a unified-diff string for a managed-append conflict.

    When parse succeeds (destination has a valid managed block), diffs the
    current block text vs the proposed block — scoped, never huge.

    When parse fails (malformed markers), falls back to a whole-file diff
    capped at _FALLBACK_DIFF_MAX_LINES / _FALLBACK_DIFF_MAX_BYTES to avoid
    flooding stderr with multi-megabyte files.
    """
    proposed_lines = plan.proposed_block.splitlines(keepends=True)

    # Try to parse the current block (parse succeeds → scoped diff).
    try:
        dest_text = destination.read_text(encoding="utf-8")
        parsed = parse_append_block(dest_text, entry.path.as_posix())
        if parsed is not None:
            current_lines = parsed.text.splitlines(keepends=True)
            diff = list(difflib.unified_diff(
                current_lines,
                proposed_lines,
                fromfile="current:" + str(destination),
                tofile="proposed:" + str(entry.path),
            ))
            return "".join(diff)
        # No block present — fall through to whole-file fallback.
        current_text = dest_text
        label = "whole-file (no managed block found)"
    except (ValueError, OSError):
        # Malformed markers or unreadable file — fall through to whole-file.
        try:
            current_text = destination.read_text(encoding="utf-8")
        except OSError:
            current_text = ""
        label = "whole-file (malformed markers)"

    # Whole-file fallback: cap to avoid megabyte output.
    current_text_capped = current_text
    truncated = False
    if len(current_text.encode("utf-8")) > _FALLBACK_DIFF_MAX_BYTES:
        current_text_capped = current_text.encode("utf-8")[:_FALLBACK_DIFF_MAX_BYTES].decode("utf-8", errors="replace")
        truncated = True

    current_lines = current_text_capped.splitlines(keepends=True)
    diff_lines = list(difflib.unified_diff(
        current_lines,
        proposed_lines,
        fromfile=f"current ({label}):" + str(destination),
        tofile="proposed:" + str(entry.path),
    ))
    if len(diff_lines) > _FALLBACK_DIFF_MAX_LINES:
        diff_lines = diff_lines[:_FALLBACK_DIFF_MAX_LINES]
        diff_lines.append(f"\n... (diff truncated at {_FALLBACK_DIFF_MAX_LINES} lines)\n")
    elif truncated:
        diff_lines.append(f"\n... (current file truncated at {_FALLBACK_DIFF_MAX_BYTES} bytes for diff)\n")

    return "".join(diff_lines)


# ---------------------------------------------------------------------------
# Write / plan
# ---------------------------------------------------------------------------

def write_managed_append(*, source: Path, destination: Path, entry: ManifestEntry) -> str:
    plan = plan_managed_append(source=source, destination=destination, entry=entry, installed_info={})
    if plan.conflict:
        diff = _managed_append_conflict_diff(destination, plan, entry)
        if diff:
            sys.stderr.write(diff)
            if not diff.endswith("\n"):
                sys.stderr.write("\n")
        raise SystemExit(f"Refusing to write malformed managed-append destination: {entry.path}")
    if plan.updated_text is not None:
        _write_text_file(destination, plan.updated_text)
    return plan.applied_sha256 or sha256_text(plan.proposed_block)


def plan_managed_append(
    *,
    source: Path,
    destination: Path,
    entry: ManifestEntry,
    installed_info: object,
) -> AppendBlockPlan:
    block = render_append_block(source, entry)
    block_hash = sha256_text(block)
    info = installed_info if isinstance(installed_info, dict) else {}
    if not destination.exists():
        return AppendBlockPlan(updated_text=block, proposed_block=block, applied_sha256=block_hash)

    text = destination.read_text(encoding="utf-8")
    try:
        parsed = parse_append_block(text, entry.path.as_posix())
    except ValueError:
        return AppendBlockPlan(updated_text=None, proposed_block=block, applied_sha256=None, conflict=True)

    if parsed is None:
        if info.get("policy") == "managed":
            old_hash = info.get("sha256")
            if old_hash and _file_hash(destination) == old_hash:
                return AppendBlockPlan(updated_text=block, proposed_block=block, applied_sha256=block_hash)
            return AppendBlockPlan(updated_text=None, proposed_block=block, applied_sha256=None, conflict=True)
        return AppendBlockPlan(
            updated_text=append_block_to_text(text, block),
            proposed_block=block,
            applied_sha256=block_hash,
        )

    current_hash = sha256_text(parsed.text)
    old_applied_hash = info.get("applied_sha256")
    if old_applied_hash and current_hash != old_applied_hash:
        return AppendBlockPlan(updated_text=None, proposed_block=block, applied_sha256=None, conflict=True)
    if not old_applied_hash and current_hash != block_hash:
        return AppendBlockPlan(updated_text=None, proposed_block=block, applied_sha256=None, conflict=True)
    if current_hash == block_hash:
        return AppendBlockPlan(updated_text=None, proposed_block=block, applied_sha256=block_hash)
    if normalize_payload(parsed.payload) == normalize_payload(source.read_text(encoding="utf-8")):
        return AppendBlockPlan(updated_text=None, proposed_block=block, applied_sha256=current_hash)
    return AppendBlockPlan(
        updated_text=replace_block(text, parsed, block),
        proposed_block=block,
        applied_sha256=block_hash,
    )


def plan_managed_append_retirement(
    *,
    destination: Path,
    path_text: str,
    installed_info: dict[str, object],
) -> AppendBlockPlan:
    proposed = ""
    if not destination.exists():
        return AppendBlockPlan(updated_text=None, proposed_block=proposed, applied_sha256=None)
    text = destination.read_text(encoding="utf-8")
    try:
        parsed = parse_append_block(text, path_text)
    except ValueError:
        return AppendBlockPlan(updated_text=None, proposed_block=proposed, applied_sha256=None, conflict=True)
    if parsed is None:
        return AppendBlockPlan(updated_text=None, proposed_block=proposed, applied_sha256=None)
    old_applied_hash = installed_info.get("applied_sha256")
    if old_applied_hash and sha256_text(parsed.text) != old_applied_hash:
        return AppendBlockPlan(updated_text=None, proposed_block=parsed.text, applied_sha256=None, conflict=True)
    if not old_applied_hash:
        return AppendBlockPlan(updated_text=None, proposed_block=parsed.text, applied_sha256=None, conflict=True)
    updated = text[: parsed.start] + text[parsed.end :]
    return AppendBlockPlan(updated_text=updated, proposed_block=parsed.text, applied_sha256=None)
