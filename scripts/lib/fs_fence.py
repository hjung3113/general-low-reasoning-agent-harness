"""Filesystem fence — harness-managed write-path enforcement (design §5.1).

Spec: `docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md`
      §5.0 enforcement scope (harness-mediated writes only, NOT raw agent edits)
      §5.1 filesystem fence + allowed_paths
      §3.4 exit 4 (scope_violation)

Exports:
    FenceDenyError        -- OSError with exit_code=4; raised by enforce_write
    FenceCheckResult      -- dataclass(allowed, reason)
    check_write_path(...) -- pure check, no audit
    enforce_write(...)    -- check + audit emit + raise on deny

The fence applies ONLY to autopilot modes (execution_mode != "manual").
Manual mode is always allowed (fence_disabled_manual_mode).

Fail-closed behavior:
  - If execution_mode is missing (None): denied (execution_mode_missing_fail_closed).
    Corrupt/fresh state with no execution_mode must not allow all writes.
  - If execution_mode != "manual" and allowed_paths is None or []:
    denied (not_in_allowed_paths). No permissive-by-default for autopilot.

Reason values:
  "allowed"                          -- path matches an allowed prefix
  "path_outside_anchor"              -- '..' component detected
  "symlink_in_path"                  -- symlink encountered in path walk
  "not_in_allowed_paths"             -- path doesn't match any allowed prefix,
                                        or allowed_paths is None / []
  "dotfile_component_rejected"       -- path component starts with "." (P3-P2-3)
  "fence_disabled_manual_mode"       -- execution_mode == "manual"
  "execution_mode_missing_fail_closed" -- execution_mode field absent from state

allowed_paths prefix match semantics (§5.1):
  Each entry in state.allowed_paths is a POSIX path prefix string such as
  "scripts/" or ".harness/". A target path is matched if its POSIX-normalized
  form equals the entry (exact match) or starts with the entry stripped of its
  trailing slash plus a "/". For example, "scripts/lib/foo.py" matches prefix
  "scripts/" because it starts with "scripts/". Partial-component matches are
  NOT allowed: "scriptsx/foo.py" does NOT match "scripts/" because the
  prefix check appends "/" to the stripped entry, requiring a full component
  boundary. Callers must ensure allowed_paths entries use forward-slash suffixes
  for directory prefixes.

TODO (S10d/S11): Wire fence_protected_paths into production callers (phase_set,
  phase_approve, etc.). Currently enforce_write is unit-tested but not called
  from production paths. Deciding which absolute paths every command writes
  requires per-command audit of write targets. Tracked as S10d scope; mirror
  the S10a P1-1 production-wiring pattern when implementing.

Slice S10b step 2.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence, Union

from .safe_open import FenceError, FenceAnchorEscape, FenceSymlinkRejected

__all__ = [
    "FenceDenyError",
    "FenceCheckResult",
    "check_write_path",
    "enforce_write",
]

# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


class FenceDenyError(OSError):
    """Fence policy rejected an attempted write path. exit_code=4."""

    exit_code = 4

    def __init__(
        self,
        *,
        path: str,
        reason: str,
        allowed_paths: Sequence[str],
    ) -> None:
        super().__init__(
            f"fence deny: path={path!r} reason={reason} allowed={list(allowed_paths)}"
        )
        self.path = path
        self.reason = reason
        self.allowed_paths = list(allowed_paths)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class FenceCheckResult:
    allowed: bool
    reason: str
    # Reason values:
    # "allowed" | "path_outside_anchor" | "symlink_in_path" |
    # "not_in_allowed_paths" | "dotfile_component_rejected" |
    # "fence_disabled_manual_mode"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _dry_run_resolve(path: Union[str, Path], *, anchor: Union[str, Path]) -> Path:
    """Walk path components from anchor using safe_open primitives.

    Does NOT open the final file (which may not exist yet for a pre-write
    check). Raises FenceError subclasses on symlinks or '..' traversal.

    Returns the resolved absolute Path.
    """
    import os
    import stat as _stat

    from .safe_open import (
        FenceAnchorEscape,
        FenceSymlinkRejected,
        _HAS_O_PATH,
        _O_PATH,
        _validate_anchor,
        _decompose,
    )

    anchor_path = _validate_anchor(anchor)
    parts = _decompose(path)

    # '..' check — defence-in-depth (same as safe_open)
    for part in parts:
        if part == "..":
            raise FenceAnchorEscape(
                f"fs_fence: path {str(path)!r} contains '..' — rejected"
            )

    if not parts:
        raise ValueError("fs_fence: path must not be empty")

    # Walk intermediate directories (all but the last component)
    dir_parts = parts[:-1]
    file_part = parts[-1]

    # We walk using the same O_NOFOLLOW|O_DIRECTORY approach as safe_open,
    # but skip the final component open (file may not exist yet).
    try:
        anchor_fd = os.open(
            str(anchor_path),
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
        )
    except OSError as exc:
        from .safe_open import _rethrow_eloop
        _rethrow_eloop(exc, str(anchor_path))
        raise

    parent_fd = anchor_fd
    fds_to_close: list[int] = [anchor_fd]
    current_path = anchor_path

    try:
        for component in dir_parts:
            if component == ".":
                continue
            if component == "..":
                raise FenceAnchorEscape(
                    f"fs_fence: '..' in intermediate component {component!r}"
                )
            try:
                dir_open_flags = (
                    _O_PATH | os.O_NOFOLLOW | os.O_DIRECTORY | os.O_CLOEXEC
                    if _HAS_O_PATH
                    else os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY | os.O_CLOEXEC
                )
                new_fd = os.open(component, dir_open_flags, dir_fd=parent_fd)
            except OSError as exc:
                from .safe_open import _rethrow_eloop
                _rethrow_eloop(exc, component, dir_fd=parent_fd)
                raise
            fds_to_close.append(new_fd)
            parent_fd = new_fd
            current_path = current_path / component

        # Check the final component via lstat (if it exists) to catch symlinks
        # without opening the file (which may not yet exist).
        final_path = current_path / file_part
        try:
            st = os.lstat(file_part, dir_fd=parent_fd)
            if _stat.S_ISLNK(st.st_mode):
                raise FenceSymlinkRejected(
                    f"fs_fence: symlink at final component {file_part!r}"
                )
        except FileNotFoundError:
            pass  # File doesn't exist yet — that's fine for a pre-write check

        return final_path

    finally:
        for fd in fds_to_close:
            try:
                os.close(fd)
            except OSError:
                pass


def _path_matches_allowed(
    path: str,
    *,
    allowed_paths: list[str],
) -> bool:
    """Return True if `path` starts with any entry in allowed_paths.

    Each allowed_paths entry is a POSIX prefix (e.g. 'scripts/', '.harness/').
    The match is a simple string prefix check on the normalized POSIX form.
    """
    return _find_matching_prefix(path, allowed_paths=allowed_paths) is not None


def _find_matching_prefix(
    path: str,
    *,
    allowed_paths: list[str],
) -> "str | None":
    """Return the first matching allowed_paths entry, or None if no match.

    Each allowed_paths entry is a POSIX prefix (e.g. 'scripts/', '.harness/').
    Returns the raw entry string (as provided in allowed_paths) so the caller
    can compute which suffix components lie beyond the authorized prefix.
    """
    from pathlib import PurePosixPath

    # Normalize to POSIX forward-slash form
    posix_path = PurePosixPath(path).as_posix()

    for entry in allowed_paths:
        # Normalize entry too
        posix_entry = PurePosixPath(entry).as_posix()
        if posix_path == posix_entry or posix_path.startswith(posix_entry.rstrip("/") + "/"):
            return entry
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_write_path(
    path: Union[str, Path],
    *,
    anchor: Union[str, Path],
    state: Mapping,
) -> FenceCheckResult:
    """Pure check — does NOT open the file or emit audit. Returns the verdict.

    Steps:
      1. If state.execution_mode == "manual" → FenceCheckResult(True,
         "fence_disabled_manual_mode"). Fence applies ONLY to autopilot.
      2. Run _dry_run_resolve to verify no symlinks / '..' in path.
         FenceError → FenceCheckResult(False, mapped_reason).
      3. Read state.allowed_paths. None or [] → fail-closed
         (FenceCheckResult(False, "not_in_allowed_paths")).
      4. Match path against allowed_paths prefixes. Match → True/"allowed".
         No match → False/"not_in_allowed_paths".
    """
    path_str = str(path)

    # Step 1 — manual mode bypass (fail-closed on missing execution_mode)
    exec_mode = state.get("execution_mode")
    if exec_mode is None:
        # Fail-closed: corrupt/fresh state with no execution_mode must not allow
        # all writes. Default-to-manual would allow arbitrary writes from a
        # state-less or tampered context. §5.1 fail-closed requirement.
        return FenceCheckResult(allowed=False, reason="execution_mode_missing_fail_closed")
    if exec_mode == "manual":
        return FenceCheckResult(allowed=True, reason="fence_disabled_manual_mode")

    # Step 2 — path safety check (symlinks / '..')
    try:
        _dry_run_resolve(path_str, anchor=anchor)
    except FenceAnchorEscape:
        return FenceCheckResult(allowed=False, reason="path_outside_anchor")
    except FenceSymlinkRejected:
        return FenceCheckResult(allowed=False, reason="symlink_in_path")
    except FenceError:
        # Other fence errors (e.g. FenceWindowsUnsupported) — treat as deny
        return FenceCheckResult(allowed=False, reason="path_outside_anchor")
    except (ValueError, FileNotFoundError, NotADirectoryError):
        # ValueError = relative path error from _decompose / empty
        # FileNotFoundError / NotADirectoryError = intermediate dir doesn't exist
        # For missing intermediate dirs, treat as allowed (path is simply new);
        # the actual write will fail if the anchor isn't satisfied.
        # However if it's a ValueError about '..' we re-raise.
        pass

    # Step 3 — allowed_paths check
    allowed_paths = state.get("allowed_paths")

    # Fail-closed: None or [] → deny
    if not allowed_paths:
        return FenceCheckResult(allowed=False, reason="not_in_allowed_paths")

    # Step 4 — prefix match
    matching_prefix = _find_matching_prefix(path_str, allowed_paths=allowed_paths)
    if matching_prefix is not None:
        # P3-P2-3 (cycle-1 review fix): after prefix match, reject any dotfile
        # component that is NOT covered by the matched allowed_paths prefix.
        # For example, if "scripts/" matched, then "scripts/.git/config" has a
        # dotfile component ".git" that lies WITHIN the allowed prefix and must
        # be denied — an LLM coder could write to .git/hooks/ this way.
        # However, if the allowed prefix is itself ".harness/" and the path is
        # ".harness/audit.log", the dotfile component IS the authorized prefix
        # and must remain allowed (the state's allowed_paths entry is the grant).
        #
        # Implementation: strip the matched prefix from the path, then check
        # for dotfile components in the REMAINING suffix only.
        from pathlib import PurePosixPath as _PPP
        _full_parts = _PPP(path_str).parts
        _prefix_parts = _PPP(matching_prefix.rstrip("/")).parts
        # Suffix components are those beyond the prefix
        _suffix_parts = _full_parts[len(_prefix_parts):]
        for _p in _suffix_parts:
            if _p.startswith(".") and _p not in (".", ".."):
                return FenceCheckResult(
                    allowed=False, reason="dotfile_component_rejected"
                )
        return FenceCheckResult(allowed=True, reason="allowed")

    return FenceCheckResult(allowed=False, reason="not_in_allowed_paths")


def _now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def enforce_write(
    path: Union[str, Path],
    *,
    anchor: Union[str, Path],
    state: Mapping,
    lock_handle,
    audit_path: Union[str, Path],
    actor: str,
) -> None:
    """Convenience wrapper: check_write_path + audit emit + raise on deny.

    On success: returns None (caller proceeds to write).
    On deny: emits verb=autopilot.fence.deny audit row + raises FenceDenyError.
    """
    from . import audit as _audit

    path_str = str(path)

    result = check_write_path(path_str, anchor=anchor, state=state)

    if result.allowed:
        return None

    # Sanitize path for audit — truncate to 256 chars
    audit_path_str = path_str[:256]

    allowed_paths = list(state.get("allowed_paths") or [])

    deny_entry = {
        "verb": "autopilot.fence.deny",
        "path": audit_path_str,
        "reason": result.reason,
        "allowed_paths": allowed_paths,
        "actor": actor,
        "at": _now_iso(),
    }

    _audit.audit_append(deny_entry, audit_path=Path(audit_path))

    raise FenceDenyError(
        path=path_str,
        reason=result.reason,
        allowed_paths=allowed_paths,
    )
