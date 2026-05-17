"""
scripts/lib/safe_open.py — POSIX race-safe path-open primitive (§12.2).

Exports:
  safe_open(path, mode, *, anchor) -> int  (file descriptor)
  FenceError, FenceSymlinkRejected, FenceAnchorEscape, FenceWindowsUnsupported

Design:
  Every open walks path components from `anchor` using O_NOFOLLOW|O_DIRECTORY|O_PATH
  (one fd per component) so no symlink traversal can occur at any step.  The
  final component is opened with O_NOFOLLOW|O_CLOEXEC plus mode-derived flags.

  O_NOFOLLOW causes open() to fail with ELOOP if the target is a symlink, which
  we convert to FenceSymlinkRejected.

  '..' components at the walk level are caught before the OS call and raise
  FenceAnchorEscape (defence-in-depth; O_NOFOLLOW already stops symlinks but
  does not prevent '..' traversal out of the anchor).

  Hardlinks: safe_open does NOT reject hardlinks.  A hardlink is a regular
  directory entry; the path remains within the anchor.  Content aliasing is
  a separate concern; if hardlink-aware enforcement is ever required, implement
  it in a higher-level layer (see future-work note in §12.2).

Windows: raises FenceWindowsUnsupported.  Full implementation deferred to S10d.

Exit codes (§3.4):
  FenceError              → exit_code = 4  (scope_violation)
  FenceWindowsUnsupported → exit_code = 11 (windows_containment_degraded)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path, PurePosixPath
from typing import Union

__all__ = [
    "FenceError",
    "FenceSymlinkRejected",
    "FenceAnchorEscape",
    "FenceWindowsUnsupported",
    "safe_open",
]

# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

class FenceError(OSError):
    """Base for fence-related failures. exit_code=4 (scope_violation)."""
    exit_code = 4


class FenceSymlinkRejected(FenceError):
    """Symlink encountered in path resolution."""


class FenceAnchorEscape(FenceError):
    """Resolved path escapes the anchor directory (e.g., '..' traversal)."""


class FenceWindowsUnsupported(FenceError):
    """Windows safe_open is deferred to S10d.  Caller must accept degraded
    posture or skip.  exit_code=11 (windows_containment_degraded)."""
    exit_code = 11


# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

PathLike = Union[str, "os.PathLike[str]"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# O_PATH: obtain a fd without actually opening the file for I/O.
# Available on Linux and macOS >= 10.12.  We check at runtime.
_HAS_O_PATH = hasattr(os, "O_PATH")
_O_PATH: int = getattr(os, "O_PATH", 0)


def _mode_to_flags(mode: str) -> int:
    """Translate an stdlib open() mode string to OS-level open flags.

    Supported modes: "r", "rb", "w", "wb", "a", "ab", "r+", "rb+", "w+", "wb+"
    Raises ValueError for unsupported modes (e.g. "x").
    """
    # Normalise: strip 'b' for flag logic (binary vs text doesn't affect OS flags)
    core = mode.replace("b", "")

    _MAP = {
        "r":  os.O_RDONLY,
        "w":  os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        "a":  os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        "r+": os.O_RDWR,
        "w+": os.O_RDWR  | os.O_CREAT | os.O_TRUNC,
    }

    flags = _MAP.get(core)
    if flags is None:
        raise ValueError(
            f"safe_open: unsupported mode {mode!r}. "
            f"Supported: r, rb, w, wb, a, ab, r+, rb+, w+, wb+"
        )
    return flags | os.O_CLOEXEC


def _validate_anchor(anchor: PathLike) -> Path:
    """Return a validated, absolute, real-directory Path for anchor.

    Raises:
      ValueError          – anchor is not absolute
      FileNotFoundError   – anchor does not exist
      FenceSymlinkRejected– anchor itself is a symlink
      NotADirectoryError  – anchor exists but is not a directory
    """
    anchor_path = Path(anchor)

    if not anchor_path.is_absolute():
        raise ValueError(f"safe_open: anchor must be absolute, got {anchor!r}")

    # Check existence and type without following symlinks where we can.
    try:
        lstat = anchor_path.lstat()
    except FileNotFoundError:
        raise FileNotFoundError(
            f"safe_open: anchor does not exist: {anchor!r}"
        ) from None

    import stat as _stat
    if _stat.S_ISLNK(lstat.st_mode):
        raise FenceSymlinkRejected(
            f"safe_open: anchor must not be a symlink: {anchor!r}"
        )

    if not _stat.S_ISDIR(lstat.st_mode):
        raise NotADirectoryError(
            f"safe_open: anchor must be a directory: {anchor!r}"
        )

    return anchor_path


def _decompose(path: PathLike) -> list[str]:
    """Break path into non-empty components, rejecting absolute paths.

    Returns a list of component strings; raises ValueError for absolute paths.
    '..' components are returned as-is so the walk can detect them.
    """
    p = Path(path)
    if p.is_absolute():
        raise ValueError(
            f"safe_open: path must be relative (it is the caller's responsibility "
            f"to supply a path relative to anchor), got {str(path)!r}"
        )
    # Filter empty parts (consecutive slashes, etc.) but keep '.'  and '..'
    parts = [part for part in p.parts if part != ""]
    return parts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def safe_open(
    path: PathLike,
    mode: str = "r",
    *,
    anchor: PathLike,
) -> int:
    """Race-safely open `path` (relative to `anchor`) refusing any symlink.

    Returns a raw file descriptor (int).  The caller is responsible for
    closing it (os.close) or wrapping it (os.fdopen).

    See module docstring for full semantics.
    """
    # -----------------------------------------------------------------------
    # 0. Windows guard — deferred to S10d
    # -----------------------------------------------------------------------
    if sys.platform == "win32":
        raise FenceWindowsUnsupported(
            "safe_open: Windows implementation deferred to S10d. "
            "exit_code=11 (windows_containment_degraded)"
        )

    # -----------------------------------------------------------------------
    # 1. Validate inputs
    # -----------------------------------------------------------------------
    anchor_path = _validate_anchor(anchor)
    parts = _decompose(path)  # raises ValueError for absolute path

    # Translate mode → OS flags (raises ValueError for unsupported modes)
    file_flags = _mode_to_flags(mode)

    # -----------------------------------------------------------------------
    # 2. Reject any '..' component outright (defence-in-depth).
    #    Even if the net result would stay inside the anchor, '..' in a
    #    path is a code-smell / potential TOCTOU vector — we reject it
    #    unconditionally to keep the security invariant simple and auditable.
    # -----------------------------------------------------------------------
    for part in parts:
        if part == "..":
            raise FenceAnchorEscape(
                f"safe_open: path {str(path)!r} contains '..' component — "
                f"all relative traversal is rejected by safe_open"
            )

    # -----------------------------------------------------------------------
    # 3. Walk intermediate directory components with O_NOFOLLOW|O_DIRECTORY
    #    to obtain parent_fd for each step.
    # -----------------------------------------------------------------------
    if not parts:
        raise ValueError("safe_open: path must not be empty")

    dir_parts = parts[:-1]
    file_part = parts[-1]

    # Open anchor directory itself
    try:
        anchor_fd = os.open(str(anchor_path), os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError as exc:
        _rethrow_eloop(exc, str(anchor_path))
        raise

    parent_fd = anchor_fd
    fds_to_close: list[int] = [anchor_fd]

    try:
        # Walk each intermediate directory component
        for component in dir_parts:
            if component == "." :
                continue  # skip no-op components
            # component == ".." was already caught above by depth check,
            # but guard here too for robustness.
            if component == "..":
                raise FenceAnchorEscape(
                    f"safe_open: '..' in intermediate component {component!r}"
                )

            try:
                # Use O_PATH when available (Linux); fall back to O_RDONLY on macOS.
                # O_NOFOLLOW on the intermediate directory ensures we reject symlinked dirs.
                dir_open_flags = (
                    _O_PATH | os.O_NOFOLLOW | os.O_DIRECTORY | os.O_CLOEXEC
                    if _HAS_O_PATH
                    else os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY | os.O_CLOEXEC
                )
                new_fd = os.open(component, dir_open_flags, dir_fd=parent_fd)
            except OSError as exc:
                _rethrow_eloop(exc, component, dir_fd=parent_fd)
                raise

            fds_to_close.append(new_fd)
            parent_fd = new_fd

        # -----------------------------------------------------------------------
        # 4. Open the final component
        # -----------------------------------------------------------------------
        # Remove O_NOFOLLOW from dir_flags to get the final flags — we add it back
        final_flags = file_flags | os.O_NOFOLLOW  # type: ignore[attr-defined]

        # Default permission bits for created files (caller's umask applies)
        mode_bits = 0o666

        try:
            result_fd = os.open(file_part, final_flags, mode_bits, dir_fd=parent_fd)
        except OSError as exc:
            _rethrow_eloop(exc, file_part, dir_fd=parent_fd)
            raise

        return result_fd

    finally:
        # Close all intermediate directory fds (not the result fd)
        for fd in fds_to_close:
            try:
                os.close(fd)
            except OSError:
                pass


def _rethrow_eloop(exc: OSError, component: str, *, dir_fd: int = -1) -> None:
    """Re-raise exc as FenceSymlinkRejected if it indicates a symlink was hit.

    POSIX ELOOP is the canonical signal when O_NOFOLLOW encounters a symlink.
    macOS additionally returns ENOTDIR when O_NOFOLLOW|O_DIRECTORY is used on
    a symlink-to-directory.  In that case we confirm via lstat (relative to
    dir_fd when provided) before converting.
    """
    import errno as _errno
    import stat as _stat

    if exc.errno == _errno.ELOOP:
        raise FenceSymlinkRejected(
            f"safe_open: symlink encountered at {component!r} (ELOOP)"
        ) from exc

    if exc.errno == _errno.ENOTDIR:
        # macOS: O_NOFOLLOW|O_DIRECTORY on a symlink yields ENOTDIR.
        # Verify the target really is a symlink before converting.
        try:
            if dir_fd >= 0:
                st = os.lstat(component, dir_fd=dir_fd)
            else:
                st = os.lstat(component)
        except OSError:
            pass  # Cannot stat; propagate original ENOTDIR
        else:
            if _stat.S_ISLNK(st.st_mode):
                raise FenceSymlinkRejected(
                    f"safe_open: symlink encountered at {component!r} (ENOTDIR/macOS)"
                ) from exc
