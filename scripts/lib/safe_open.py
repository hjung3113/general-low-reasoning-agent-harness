"""
scripts/lib/safe_open.py — Race-safe path-open primitive (§12.2).

Exports:
  safe_open(path, mode, *, anchor) -> int  (file descriptor)
  FenceError, FenceSymlinkRejected, FenceAnchorEscape,
  FenceWindowsUnsupported, FenceWindowsReparsePointRefused

Design (POSIX):
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

Design (Windows — §12.2):
  Uses CreateFileW with FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS
  to obtain a handle WITHOUT following reparse points (junctions, mount points,
  symlinks).  os.lstat().st_file_attributes is checked for FILE_ATTRIBUTE_REPARSE_POINT;
  if set, FenceWindowsReparsePointRefused is raised.  GetFinalPathNameByHandle
  canonicalizes the path and verifies it remains inside the anchor root.
  All subsequent I/O uses the already-open handle — no re-CreateFile TOCTOU window.

Exit codes (§3.4):
  FenceError                      → exit_code = 4  (scope_violation)
  FenceWindowsUnsupported         → exit_code = 11 (windows_containment_degraded)
  FenceWindowsReparsePointRefused → exit_code = 11 (windows_containment_degraded)
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
    "FenceWindowsReparsePointRefused",
    "safe_open",
]

# ---------------------------------------------------------------------------
# Module-level constant used by tests to patch Windows detection without
# globally replacing os.name (which would break stdlib internals).
# ---------------------------------------------------------------------------
_IS_WINDOWS: bool = os.name == "nt"

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
    """Windows safe_open ctypes wiring unavailable (non-CPython or stripped build).
    Caller must accept degraded posture or skip.  exit_code=11 (windows_containment_degraded)."""
    exit_code = 11


class FenceWindowsReparsePointRefused(FenceError):
    """Reparse point (junction, mount point, symlink) encountered on Windows.
    The path is refused to prevent sandbox escape.  exit_code=11."""
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
# Windows implementation — §12.2
# ---------------------------------------------------------------------------

def _windows_open(
    path: PathLike,
    mode: str = "r",
    *,
    anchor: PathLike,
) -> int:
    """Windows-specific safe_open using CreateFileW + GetFinalPathNameByHandle.

    Steps:
      1. Resolve the full target path (anchor / path).
      2. Reject any '..' components (defence-in-depth).
      3. Open with CreateFileW using FILE_FLAG_OPEN_REPARSE_POINT |
         FILE_FLAG_BACKUP_SEMANTICS — this does NOT follow reparse points.
      4. Check os.lstat().st_file_attributes for FILE_ATTRIBUTE_REPARSE_POINT;
         refuse with FenceWindowsReparsePointRefused if set.
      5. GetFinalPathNameByHandle → canonicalize → verify still inside anchor.
      6. Return an fd via msvcrt.open_osfhandle (or keep the HANDLE open
         and return it cast to int if msvcrt unavailable).

    Raises FenceWindowsUnsupported if ctypes kernel32 wiring is absent
    (non-CPython / stripped build).
    """
    import stat as _stat
    from pathlib import PureWindowsPath

    # ---- Validate anchor using Windows-aware path parsing ----
    # Use PureWindowsPath so that Windows drive-letter paths like C:\sandbox
    # are correctly identified as absolute even when running on POSIX (tests).
    anchor_str = str(anchor).replace("/", "\\")
    anchor_win = PureWindowsPath(anchor_str)
    if not anchor_win.is_absolute():
        raise ValueError(f"safe_open: anchor must be absolute, got {anchor!r}")
    # Use pathlib.Path for filesystem operations on the actual platform
    anchor_path = Path(anchor_str)

    # ---- Reject '..' and absolute path argument ----
    path_str = str(path).replace("/", "\\")
    rel_win = PureWindowsPath(path_str)
    if rel_win.is_absolute():
        raise ValueError(
            f"safe_open: path must be relative, got {str(path)!r}"
        )
    parts = [p for p in rel_win.parts if p not in ("", "\\", "/")]
    if not parts:
        raise ValueError("safe_open: path must not be empty")
    for part in parts:
        if part == "..":
            raise FenceAnchorEscape(
                f"safe_open: path {str(path)!r} contains '..' component"
            )

    rel = Path(*parts) if len(parts) > 1 else Path(parts[0])
    target = anchor_path / rel

    # ---- Import ctypes wiring (raises FenceWindowsUnsupported if absent) ----
    try:
        import ctypes
        import ctypes.wintypes as _wt
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except (ImportError, AttributeError) as exc:
        raise FenceWindowsUnsupported(
            "safe_open: ctypes.windll.kernel32 unavailable on this Python build — "
            "Windows containment degraded. exit_code=11"
        ) from exc

    # ---- Win32 constants ----
    GENERIC_READ             = 0x80000000
    GENERIC_WRITE            = 0x40000000
    FILE_SHARE_READ          = 0x00000001
    FILE_SHARE_WRITE         = 0x00000002
    FILE_SHARE_DELETE        = 0x00000004
    OPEN_EXISTING            = 3
    CREATE_ALWAYS            = 2
    OPEN_ALWAYS              = 4
    FILE_FLAG_OPEN_REPARSE_POINT  = 0x00200000
    FILE_FLAG_BACKUP_SEMANTICS    = 0x02000000
    INVALID_HANDLE_VALUE     = ctypes.c_void_p(-1).value
    FILE_ATTRIBUTE_REPARSE_POINT  = 0x00000400
    FILE_NAME_NORMALIZED     = 0x0

    # ---- Translate mode to Win32 desired-access + creation-disposition ----
    core_mode = mode.replace("b", "")
    _MODE_MAP = {
        "r":  (GENERIC_READ,  OPEN_EXISTING),
        "w":  (GENERIC_WRITE, CREATE_ALWAYS),
        "a":  (GENERIC_WRITE, OPEN_ALWAYS),
        "r+": (GENERIC_READ | GENERIC_WRITE, OPEN_EXISTING),
        "w+": (GENERIC_READ | GENERIC_WRITE, CREATE_ALWAYS),
    }
    if core_mode not in _MODE_MAP:
        raise ValueError(
            f"safe_open: unsupported mode {mode!r}. "
            f"Supported: r, rb, w, wb, a, ab, r+, rb+, w+, wb+"
        )
    desired_access, creation_disposition = _MODE_MAP[core_mode]

    # ---- CreateFileW — opens WITHOUT following reparse points ----
    flags = FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS
    share = FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
    handle = kernel32.CreateFileW(
        str(target),          # lpFileName
        desired_access,       # dwDesiredAccess
        share,                # dwShareMode
        None,                 # lpSecurityAttributes
        creation_disposition, # dwCreationDisposition
        flags,                # dwFlagsAndAttributes
        None,                 # hTemplateFile
    )

    # INVALID_HANDLE_VALUE check — ctypes may return signed or unsigned int
    handle_invalid = (
        handle == INVALID_HANDLE_VALUE
        or handle == -1
        or handle == 0xFFFFFFFF
        or handle == 0xFFFFFFFFFFFFFFFF
    )
    if handle_invalid:
        last_err = kernel32.GetLastError()
        raise FenceWindowsUnsupported(
            f"safe_open: CreateFileW failed for {str(target)!r} "
            f"— GetLastError()={last_err:#010x}. exit_code=11"
        )

    try:
        # ---- Reparse-point check via lstat ----
        try:
            lst = os.lstat(str(target))
            fa = getattr(lst, "st_file_attributes", 0)
            if fa & FILE_ATTRIBUTE_REPARSE_POINT:
                raise FenceWindowsReparsePointRefused(
                    f"safe_open: reparse point (junction/mount/symlink) at "
                    f"{str(target)!r} — refused. exit_code=11"
                )
        except FenceWindowsReparsePointRefused:
            raise
        except OSError:
            pass  # lstat failure non-fatal here; GetFinalPathNameByHandle provides containment

        # ---- GetFinalPathNameByHandle → containment check ----
        buf_size = 1024
        buf = ctypes.create_unicode_buffer(buf_size)
        ret = kernel32.GetFinalPathNameByHandleW(handle, buf, buf_size, FILE_NAME_NORMALIZED)
        if ret == 0 or ret > buf_size:
            # Retry with larger buffer
            if ret > buf_size:
                buf_size = ret + 2
                buf = ctypes.create_unicode_buffer(buf_size)
                ret = kernel32.GetFinalPathNameByHandleW(handle, buf, buf_size, FILE_NAME_NORMALIZED)
            if ret == 0:
                last_err = kernel32.GetLastError()
                raise FenceWindowsUnsupported(
                    f"safe_open: GetFinalPathNameByHandleW failed — "
                    f"GetLastError()={last_err:#010x}. exit_code=11"
                )

        resolved_raw = buf.value
        # Strip \\?\ UNC prefix that GetFinalPathNameByHandle adds
        if resolved_raw.startswith("\\\\?\\"):
            resolved_raw = resolved_raw[4:]

        # Containment check using PureWindowsPath so it works on POSIX test
        # environments too (cross-platform string comparison, case-insensitive).
        resolved_win = PureWindowsPath(resolved_raw)
        anchor_win_resolved = PureWindowsPath(anchor_str)

        try:
            resolved_win.relative_to(anchor_win_resolved)
        except ValueError:
            raise FenceAnchorEscape(
                f"safe_open: resolved path {str(resolved_win)!r} escapes anchor "
                f"{str(anchor_win_resolved)!r} — refused"
            )

        # ---- Convert HANDLE to Python fd via msvcrt ----
        try:
            import msvcrt  # type: ignore[import]
            # os_flags mirrors mode: O_RDONLY, O_WRONLY, O_RDWR + O_APPEND
            import os as _os
            os_flags = _os.O_RDONLY
            if core_mode in ("w", "a", "w+"):
                os_flags = _os.O_WRONLY
            if core_mode in ("r+", "w+"):
                os_flags = _os.O_RDWR
            if core_mode == "a":
                os_flags |= _os.O_APPEND
            if "b" in mode:
                os_flags |= getattr(_os, "O_BINARY", 0)
            fd = msvcrt.open_osfhandle(handle, os_flags)
            # msvcrt.open_osfhandle takes ownership; handle will be closed with fd
            handle = None  # sentinel: do not CloseHandle in finally
            return fd
        except ImportError:
            # msvcrt not available — return handle as int (caller closes via CloseHandle)
            fd = handle
            handle = None
            return fd

    finally:
        if handle is not None:
            kernel32.CloseHandle(handle)


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
    # 0. Windows path — §12.2 CreateFileW + GetFinalPathNameByHandle
    # -----------------------------------------------------------------------
    if _IS_WINDOWS:
        return _windows_open(path, mode, anchor=anchor)

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

    # RACE NOTE (macOS O_PATH fallback): On macOS, between the failed open()
    # call (ENOTDIR) and the subsequent os.lstat() call below, there is a
    # single-syscall window during which an attacker who has write access to a
    # sibling directory could swap the path component (e.g., replace a symlink
    # with a real directory or vice versa). This means the lstat-based symlink
    # confirmation is NOT strictly TOCTOU-free on macOS.
    #
    # Practical risk assessment:
    #   - The window is extremely small (one syscall gap, ~microseconds).
    #   - Exploitability requires LOCAL filesystem write access to a sibling
    #     directory (i.e., the attacker already has significant access).
    #   - The worst-case outcome is a false-negative: a symlink is NOT detected,
    #     and ENOTDIR propagates as-is (the write still fails at the OS level).
    #   - There is no false-positive risk (we never allow an unsafe write;
    #     an undetected symlink causes a write failure, not a bypass).
    #
    # Strict §12.2 TOCTOU-freedom requires Linux O_PATH (which gives a
    # race-free fd for the component WITHOUT following symlinks, allowing
    # fstat() on the fd). On macOS, this code provides best-effort detection
    # with the above documented limitation. Full TOCTOU-free coverage on macOS
    # is deferred to S10d when the PATH-prepend installer is shipped.
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
        # See RACE NOTE in docstring for macOS TOCTOU limitation.
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
