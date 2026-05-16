"""Worktree scope checks: gate by allowed/blocked paths.

Path-matching grammar follows ADR-002 (option 2, G2-E):

- `*` matches any run of characters except `/`.
- `?` matches a single character except `/`.
- `[abc]` and `[!abc]` are POSIX-style character classes. `!` is the ONLY
  negation marker — `^` is treated as a literal class member.
- `**` is NOT a recursive-descent operator; the loader treats it as `*`.
- `/` is the segment separator; `*` and `?` do NOT cross it.
- Matching is case-sensitive on every platform (via `fnmatch.fnmatchcase`).
- Trailing-slash literal patterns (`dir/`) keep the legacy directory-prefix
  semantic (any descendant under `dir/`).
- A pattern that contains none of `*?[!]` falls through to the legacy
  literal-exact branch.
- Precedence (ADR-002 rule (a)): `blocked_paths` always overrides
  `allowed_paths`. See `path_allowed`.
"""
from __future__ import annotations

import subprocess
import sys
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Iterable

from lib.roadmap_state import normalize_path
from lib.state_diagnostics import load_state_json


_GLOB_METACHARS = frozenset("*?[!]")


class ScopePatternError(ValueError):
    """Raised for a malformed scope pattern (e.g., unterminated `[`).

    Surfaced as `SystemExit` by `check_changed_paths` and
    `check_worktree_paths` with field/index/pattern in the message
    (ADR-002 G2-E loud-fail rule).
    """


def _has_glob_metachars(pattern: str) -> bool:
    return any(c in _GLOB_METACHARS for c in pattern)


def _validate_pattern(pattern: str) -> None:
    """Reject malformed glob patterns the stdlib silently swallows.

    Today:
      - unterminated `[` (stdlib `fnmatchcase` treats this as a literal
        `[`, silently zero-matching for patterns the user clearly intended
        as a class).
      - any segment equal to `..` (path-traversal-shaped patterns must not
        appear in scope; T0-2-SecM2). Splits on `/`.

    Raises `ScopePatternError` with the offending pattern in the message.
    """
    # Reject `..` segments first — these have no legitimate use in a
    # repo-relative scope entry and may slip past normalize_path when the
    # `..` is "collapsed" by interior segments (e.g., `docs/../etc`).
    for segment in pattern.split("/"):
        if segment == "..":
            raise ScopePatternError(
                f"unsafe scope pattern (contains '..' segment): {pattern!r}"
            )
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "[":
            # Per fnmatch grammar, the first ']' immediately after `[`
            # or `[!` is a literal class member; subsequent ']' closes.
            j = i + 1
            if j < n and pattern[j] == "!":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                raise ScopePatternError(
                    f"malformed scope pattern (unterminated '['): {pattern!r}"
                )
            i = j + 1
        else:
            i += 1


def _glob_match(path: str, pattern: str) -> bool:
    """Segment-aware fnmatchcase: `*` and `?` never cross `/`.

    `**` is treated as `*` (no recursive descent) — the segment-split
    enforces this automatically because `**` is just `*` inside a single
    segment.
    """
    path_segments = path.split("/")
    pattern_segments = pattern.split("/")
    if len(path_segments) != len(pattern_segments):
        return False
    for path_seg, pat_seg in zip(path_segments, pattern_segments):
        if not fnmatchcase(path_seg, pat_seg):
            return False
    return True


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    """Return True iff `path` matches any entry in `patterns`.

    Total function on the hot path: NEVER raises. Callers MUST call
    `_validate_state_patterns(state)` BEFORE invoking this matcher so any
    malformed pattern surfaces as `SystemExit(5)` at the check boundary
    (T0-2-M2). Eager validation is sufficient; revalidating per call would
    cost O(patterns) per path on every changed-path lookup.
    """
    for pattern in patterns:
        normalized = normalize_path(pattern)
        if normalized.endswith("/"):
            if path.startswith(normalized):
                return True
            # also try as glob "<dir>/*" so trailing-slash entries match
            # single-segment children via the glob branch too (R5 lock).
            if _glob_match(path, normalized + "*"):
                return True
        elif path == normalized:
            return True
        elif _has_glob_metachars(normalized):
            if _glob_match(path, normalized):
                return True
    return False


def path_allowed(path: str, allowed: Iterable[str], blocked: Iterable[str]) -> bool:
    normalized = normalize_path(path)
    # ADR-002 (a): blocked_paths always overrides allowed_paths.
    if matches_any(normalized, blocked):
        return False
    return matches_any(normalized, allowed)


def scan_for_glob_literal_collisions(
    target: Path,
    state: dict,
    stream,
) -> None:
    """ADR-002 G3-B: warn when a globbed entry collides with a real file/dir.

    For each entry in `allowed_paths` / `blocked_paths` that contains glob
    metacharacters (`*?[!]`), check whether a literal file or directory
    exists at the unglobbed path. If so, emit a one-time stderr warning
    per (field, index). Never raises; never affects exit code.
    """
    seen: set[tuple[str, int]] = set()
    for field in ("allowed_paths", "blocked_paths"):
        entries = state.get(field, []) or []
        for index, entry in enumerate(entries):
            if not isinstance(entry, str):
                continue
            if not _has_glob_metachars(entry):
                continue
            try:
                normalized = normalize_path(entry)
            except ValueError:
                continue
            literal = target / normalized.rstrip("/")
            if literal.exists():
                key = (field, index)
                if key in seen:
                    continue
                seen.add(key)
                stream.write(
                    f"warning: {field}[{index}] entry {entry!r} contains "
                    f"glob metacharacters but a literal file or directory "
                    f"exists at {literal}. Escape the metacharacter or "
                    f"remove the entry to silence this warning.\n"
                )


def _run_glob_collision_scan(target: Path, state: dict) -> None:
    scan_for_glob_literal_collisions(target, state, sys.stderr)


def _validate_state_patterns(state: dict) -> None:
    """Apply `_validate_pattern` to every scope entry; surface as SystemExit.

    Validates every entry — even those without glob metachars — so that
    `..` traversal segments (T0-2-SecM2) cannot slip through via literal
    patterns. Patterns whose `normalize_path` raises (e.g., leading `..`)
    are inspected against the RAW entry so the segment-aware check still
    fires.
    """
    for field in ("allowed_paths", "blocked_paths"):
        for index, entry in enumerate(state.get(field, []) or []):
            if not isinstance(entry, str):
                continue
            # Always run the dotdot/glob-shape check against the raw entry;
            # normalize_path would collapse interior `..` and hide them.
            try:
                _validate_pattern(entry)
            except ScopePatternError as exc:
                raise SystemExit(f"{field}[{index}]: {exc}") from exc
            try:
                normalized = normalize_path(entry)
            except ValueError:
                continue
            if _has_glob_metachars(normalized):
                try:
                    _validate_pattern(normalized)
                except ScopePatternError as exc:
                    raise SystemExit(
                        f"{field}[{index}]: {exc}"
                    ) from exc


def check_changed_paths(target: Path, base: str) -> None:
    state_path = target / ".scratch/phase-state.json"
    state = load_state_json(state_path)
    _validate_state_patterns(state)
    _run_glob_collision_scan(target, state)
    if not changed_path_gate_allows_state(state):
        raise SystemExit(
            "Changed-path check requires phase=execute with approved=true or phase=done with approved=false"
        )
    changed = git_changed_paths(target, base)
    denied = [
        path
        for path in changed
        if not path_allowed(path, state.get("allowed_paths", []), state.get("blocked_paths", []))
    ]
    if denied:
        raise SystemExit("Changed paths outside allowed_paths: " + ", ".join(denied))


def check_worktree_paths(target: Path) -> None:
    state = load_state_json(target / ".scratch/phase-state.json")
    _validate_state_patterns(state)
    _run_glob_collision_scan(target, state)
    if not changed_path_gate_allows_state(state):
        raise SystemExit(
            "Worktree changed-path check requires phase=execute with approved=true or phase=done with approved=false"
        )
    changed = sorted(set(git_worktree_paths(target)))
    denied = [
        path
        for path in changed
        if not path_allowed(path, state.get("allowed_paths", []), state.get("blocked_paths", []))
    ]
    if denied:
        raise SystemExit("Worktree paths outside allowed_paths: " + ", ".join(denied))


def changed_path_gate_allows_state(state: dict) -> bool:
    return (state.get("phase") == "execute" and state.get("approved") is True) or (
        state.get("phase") == "done" and state.get("approved") is False
    )


def git_changed_paths(target: Path, base: str) -> list[str]:
    output = subprocess.check_output(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=target,
        text=True,
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def git_worktree_paths(target: Path) -> list[str]:
    outputs = [
        subprocess.check_output(["git", "diff", "--name-only"], cwd=target, text=True),
        subprocess.check_output(["git", "diff", "--cached", "--name-only"], cwd=target, text=True),
        subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=target, text=True),
    ]
    return [line.strip() for output in outputs for line in output.splitlines() if line.strip()]


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def is_text_file(path: Path) -> bool:
    return path.suffix in {".md", ".json", ".txt", ".yml", ".yaml", ".toml", ".sh", ".py"} or path.name in {
        "AGENTS.md",
        ".roomodes",
        ".gitignore",
    }
