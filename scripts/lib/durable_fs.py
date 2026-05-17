"""Cross-platform durability primitives (design §3.8.1, §12.5).

Spec: `docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md`

Public surface:
    DurableFsError                  -- exit-14 fault class (OSError subclass)
    fsync_parent_dir(path)          -- POSIX: O_RDONLY|O_DIRECTORY + os.fsync
                                       Windows: CreateFileW + FlushFileBuffers
    fsync_file_durable(fd, *, path) -- POSIX non-darwin: os.fsync
                                       darwin: fcntl.F_FULLFSYNC + EINVAL
                                               fallback to os.fsync
                                       Windows: re-open + FlushFileBuffers
    replace_with_retry(src, dst)    -- os.replace with 5x exponential backoff
                                       (50/100/200/400/800ms) on
                                       PermissionError (Windows AV-holding-
                                       handle). Persistent failure raises
                                       DurableFsError so callers can exit
                                       3 `state_replace_blocked` (§12.5 #5).

This module deliberately exposes nothing about the §3.8 transaction
protocol — it is a flat, side-effect-only set of primitives that lock
(`phase_lock.py`, S01-C) and transaction (`phase_txn.py`, S01-D) layers
build on. It is callable without holding the state lock.
"""

from __future__ import annotations

import errno
import os
import sys
import time
from pathlib import Path
from typing import Union

_OS_KIND = os.name  # "posix" or "nt"; pinned via test_dispatch_constant_matches_os_name

_REPLACE_BACKOFF_SECONDS: tuple[float, ...] = (0.05, 0.10, 0.20, 0.40, 0.80)


class DurableFsError(OSError):
    """Raised when a durability primitive cannot guarantee its contract.

    Callers SHOULD map this to exit 14 (durability fault) per design §12.5,
    except `replace_with_retry` exhaustion which callers map to exit 3
    `state_replace_blocked` (§12.5 #5). The exception itself does not
    encode the exit code — that policy belongs to the verb-level wrapper.
    """


# ---------------------------------------------------------------------------
# fsync_parent_dir
# ---------------------------------------------------------------------------


def fsync_parent_dir(path: Union[str, "os.PathLike[str]"]) -> None:
    """Fsync the directory `path` so its entry-listing is on stable storage.

    POSIX: open `path` with O_RDONLY|O_DIRECTORY and call os.fsync.
    Windows: CreateFileW with FILE_LIST_DIRECTORY + BACKUP_SEMANTICS,
             then FlushFileBuffers (per design §3.8.1).

    On any failure raises DurableFsError; callers exit 14.
    """
    spath = os.fspath(path)
    if _OS_KIND == "posix":
        _fsync_parent_dir_posix(spath)
    elif _OS_KIND == "nt":  # pragma: no cover — exercised on Windows CI rows
        _fsync_parent_dir_windows(spath)
    else:  # pragma: no cover — no other os.name values supported by Python
        raise DurableFsError(f"unsupported os.name={_OS_KIND!r}")


def _fsync_parent_dir_posix(parent: str) -> None:
    try:
        fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as exc:
        raise DurableFsError(f"open({parent!r}, O_RDONLY|O_DIRECTORY): {exc}") from exc
    try:
        try:
            os.fsync(fd)
        except OSError as exc:
            raise DurableFsError(f"fsync({parent!r}): {exc}") from exc
    finally:
        try:
            os.close(fd)
        except OSError:  # pragma: no cover — defensive only
            pass


def _fsync_parent_dir_windows(parent: str) -> None:  # pragma: no cover - windows
    """Windows path — exercised on the S13 release-smoke matrix."""
    import ctypes
    from ctypes import wintypes

    _k = ctypes.WinDLL("kernel32", use_last_error=True)
    _k.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _k.CreateFileW.restype = wintypes.HANDLE
    _k.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    _k.FlushFileBuffers.restype = wintypes.BOOL
    _k.CloseHandle.argtypes = [wintypes.HANDLE]
    _k.CloseHandle.restype = wintypes.BOOL

    FILE_LIST_DIRECTORY = 0x0001
    FILE_SHARE_R_W_D = 0x00000001 | 0x00000002 | 0x00000004
    OPEN_EXISTING = 3
    BACKUP_SEMANTICS = 0x02000000
    INVALID = wintypes.HANDLE(-1).value

    handle = _k.CreateFileW(
        parent,
        FILE_LIST_DIRECTORY,
        FILE_SHARE_R_W_D,
        None,
        OPEN_EXISTING,
        BACKUP_SEMANTICS,
        None,
    )
    if handle == INVALID:
        raise DurableFsError(
            f"CreateFileW({parent!r}): WinError {ctypes.get_last_error()}"
        )
    try:
        if not _k.FlushFileBuffers(handle):
            raise DurableFsError(
                f"FlushFileBuffers({parent!r}): WinError {ctypes.get_last_error()}"
            )
    finally:
        if not _k.CloseHandle(handle):
            # Audit emission of `verb=durable_fs.close_failed` is the caller's
            # responsibility (S01-D wires it). Here we surface as a hard error
            # since silently swallowing a CloseHandle failure violates §12.5 #6.
            raise DurableFsError(
                f"CloseHandle({parent!r}): WinError {ctypes.get_last_error()}"
            )


# ---------------------------------------------------------------------------
# fsync_file_durable
# ---------------------------------------------------------------------------


def fsync_file_durable(fd: int, *, path: Union[str, "os.PathLike[str]"]) -> None:
    """Force `fd`'s pages to *stable* storage.

    POSIX non-darwin: os.fsync(fd).
    macOS:           fcntl.F_FULLFSYNC; if it raises OSError(EINVAL)
                     (substrate doesn't support full-fsync), fall back
                     to os.fsync. Any other OSError is wrapped in
                     DurableFsError.
    Windows:         the `fd` argument is informational (Python's int
                     fds don't map to Win32 HANDLEs cleanly); we re-open
                     `path` via CreateFileW(GENERIC_WRITE, ...) and call
                     FlushFileBuffers (per design §12.5 #4).
    """
    if sys.platform == "darwin":
        _fsync_file_durable_darwin(fd)
        return
    if _OS_KIND == "posix":
        try:
            os.fsync(fd)
        except OSError as exc:
            raise DurableFsError(f"fsync(fd={fd}): {exc}") from exc
        return
    if _OS_KIND == "nt":  # pragma: no cover — windows-only
        _fsync_file_durable_windows(os.fspath(path))
        return
    raise DurableFsError(f"unsupported os.name={_OS_KIND!r}")  # pragma: no cover


def _fsync_file_durable_darwin(fd: int) -> None:
    import fcntl

    try:
        fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
    except OSError as exc:
        if exc.errno == errno.EINVAL:
            # Substrate (e.g. tmpfs in CI) doesn't support F_FULLFSYNC.
            # Per design §12.5 #4 the documented behaviour is silent fall
            # through to os.fsync. The S13 release-smoke row asserts the
            # primary path on real APFS.
            try:
                os.fsync(fd)
            except OSError as fsync_exc:
                raise DurableFsError(
                    f"fsync(fd={fd}) after F_FULLFSYNC EINVAL: {fsync_exc}"
                ) from fsync_exc
            return
        raise DurableFsError(f"F_FULLFSYNC(fd={fd}): {exc}") from exc


def _fsync_file_durable_windows(path: str) -> None:  # pragma: no cover - windows
    import ctypes
    from ctypes import wintypes

    _k = ctypes.WinDLL("kernel32", use_last_error=True)
    _k.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _k.CreateFileW.restype = wintypes.HANDLE
    _k.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    _k.FlushFileBuffers.restype = wintypes.BOOL
    _k.CloseHandle.argtypes = [wintypes.HANDLE]
    _k.CloseHandle.restype = wintypes.BOOL

    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x00000001
    OPEN_EXISTING = 3
    INVALID = wintypes.HANDLE(-1).value

    handle = _k.CreateFileW(
        path,
        GENERIC_WRITE,
        FILE_SHARE_READ,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle == INVALID:
        raise DurableFsError(
            f"CreateFileW({path!r}, GENERIC_WRITE): WinError {ctypes.get_last_error()}"
        )
    try:
        if not _k.FlushFileBuffers(handle):
            raise DurableFsError(
                f"FlushFileBuffers({path!r}): WinError {ctypes.get_last_error()}"
            )
    finally:
        if not _k.CloseHandle(handle):
            raise DurableFsError(
                f"CloseHandle({path!r}): WinError {ctypes.get_last_error()}"
            )


# ---------------------------------------------------------------------------
# replace_with_retry
# ---------------------------------------------------------------------------


def replace_with_retry(src: Union[str, "os.PathLike[str]"], dst: Union[str, "os.PathLike[str]"]) -> None:
    """`os.replace` with 5× exponential backoff on PermissionError.

    Design §12.5 #5: Windows antivirus / search-indexer can transiently
    hold the destination handle and cause `os.replace` to raise
    PermissionError. Retry up to 5 attempts with the documented backoff
    schedule (50, 100, 200, 400, 800 ms). After exhaustion raise
    `DurableFsError` so the caller can exit 3 `state_replace_blocked`
    and leave the journal+tmp in place for next-start roll-forward.

    Any non-PermissionError is propagated unchanged — backoff is the
    documented response to AV/indexer pin only, not a generic catch-all.
    """
    spath_src = os.fspath(src)
    spath_dst = os.fspath(dst)
    last_exc: PermissionError | None = None
    total = len(_REPLACE_BACKOFF_SECONDS)
    for attempt, backoff in enumerate(_REPLACE_BACKOFF_SECONDS, start=1):
        try:
            os.replace(spath_src, spath_dst)
            return
        except PermissionError as exc:
            last_exc = exc
            # S01-B review fix (P2): no point sleeping after the final
            # attempt — there is no retry that follows. The backoff
            # schedule [50, 100, 200, 400, _] thus fires 4 sleeps total
            # across the 5 attempts of an exhaustion run.
            if attempt < total:
                time.sleep(backoff)
    # All attempts exhausted; raise as the documented fault.
    raise DurableFsError(
        f"replace({spath_src!r} -> {spath_dst!r}) blocked after "
        f"{total} PermissionError retries: {last_exc}"
    ) from last_exc


__all__ = [
    "DurableFsError",
    "fsync_parent_dir",
    "fsync_file_durable",
    "replace_with_retry",
]
