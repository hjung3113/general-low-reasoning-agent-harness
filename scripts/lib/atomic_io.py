"""Atomic I/O primitives for managed state and operational logs.

Owning plan: .planning/phases/02b-hardening/plans/02b-01-T0-A-PLAN.md (T0-A)
Contract pin: .planning/phases/02b-hardening/CONTRACT-PIN.md §1
ADR: docs/adr/2026-05-16-hardening-bundle.md (Artifact 2, G1-A, G1-D)

Exports (skeleton — bodies filled in subsequent commits per plan task order):
- atomic_write_text(path, content, *, mode=0o644)
- atomic_append_log(path, line, *, max_bytes_per_line=512)
"""

from __future__ import annotations

import errno
import os
import tempfile
from pathlib import Path

# Conditional import of platform-specific locking primitives so this module is
# importable on Windows. POSIX uses fcntl; Windows uses msvcrt for byte-range
# locks on the audit-append codepath. atomic_write_text does not require any
# locking (relies on the temp+rename atomicity contract).
if os.name == "posix":
    import fcntl as _fcntl  # type: ignore[import]
    _msvcrt = None  # type: ignore[assignment]
else:
    _fcntl = None  # type: ignore[assignment]
    try:
        import msvcrt as _msvcrt  # type: ignore[import]
    except ImportError:  # pragma: no cover — only on exotic non-POSIX/non-Win
        _msvcrt = None  # type: ignore[assignment]


class AuditLogRefusedError(OSError):
    """Raised when atomic_append_log refuses to open the target path.

    Currently raised on symlink detection (O_NOFOLLOW → ELOOP). Inherits
    from OSError so existing ``except OSError`` callers still catch it.
    """


class AuditLogContendedError(OSError):
    """Raised when atomic_append_log cannot acquire the exclusive lock
    immediately (LOCK_EX|LOCK_NB → BlockingIOError). Inherits from
    OSError so existing ``except OSError`` callers still catch it.
    Callers may retry with backoff.
    """


def atomic_write_text(path: Path, content: str, *, mode: int = 0o644) -> None:
    """Write ``content`` to ``path`` atomically.

    Writes ``content`` to a temp file in ``path.parent``, fsyncs the data to
    disk, then ``os.replace``s the temp file over the target. Any leftover
    temp file from a successful replace is gone; failure paths (covered in
    subsequent commits) will unlink the temp file before re-raising.
    """
    path = Path(path)
    parent = path.parent
    if not parent.exists():
        raise FileNotFoundError(
            f"atomic_write_text: parent directory does not exist: {parent}"
        )
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        # newline="" disables platform translation. On Windows, text-mode
        # writes would otherwise translate any embedded "\n" to "\r\n", which
        # corrupts byte-identical audit/state hash invariants.
        newline="",
        dir=str(parent),
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    )
    tmp_name = tmp.name
    try:
        try:
            tmp.write(content)
            tmp.flush()
            tmp_fd = tmp.fileno()
            os.fsync(tmp_fd)
            # Apply mode BEFORE os.replace so a crashed replace cannot leave
            # the target with stale perms, and so chmod failures abort cleanly
            # without committing the new content (fixes C1).
            fchmod = getattr(os, "fchmod", None)
            if fchmod is not None:
                fchmod(tmp_fd, mode)
            else:  # pragma: no cover — fchmod absent only on exotic platforms
                os.chmod(tmp_name, mode)
        finally:
            tmp.close()
        # Same-filesystem invariant: temp and target parent must share st_dev.
        parent_dev = os.stat(str(parent)).st_dev
        tmp_dev = os.stat(tmp_name).st_dev
        if parent_dev != tmp_dev:
            raise RuntimeError(
                f"atomic_write_text: tempfile st_dev={tmp_dev} differs from "
                f"parent st_dev={parent_dev} (cross-filesystem rename unsafe)"
            )
        # Use durable_fs.replace_with_retry so Windows AV/indexer pins on the
        # target file produce a bounded retry instead of an unrecovered
        # PermissionError. On POSIX this delegates to a single os.replace.
        from .durable_fs import replace_with_retry
        replace_with_retry(tmp_name, path)
        # Fsync the parent directory so the rename itself is durable across
        # power loss (C2). Best-effort: some platforms (and some FS types)
        # reject directory fsync — swallow OSError in that case.
        try:
            dir_flags = os.O_RDONLY
            o_directory = getattr(os, "O_DIRECTORY", 0)
            dir_flags |= o_directory
            dir_fd = os.open(str(parent), dir_flags)
            try:
                try:
                    os.fsync(dir_fd)
                except OSError:
                    pass
            finally:
                os.close(dir_fd)
        except OSError:
            # Opening the directory itself failed — also non-fatal.
            pass
    except BaseException:
        # Clean up orphan tempfile on any failure (incl. OSError, RuntimeError,
        # KeyboardInterrupt).
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def _open_audit_log(path: Path) -> int:
    """Open ``path`` for the audit-append codepath, returning the raw fd.

    Flags applied:
    - ``O_WRONLY | O_APPEND | O_CREAT`` — append-only semantics, create if absent.
    - ``O_NOFOLLOW`` (M1) — refuse to follow a symlink at the final component.
      ELOOP → ``AuditLogRefusedError``.
    - ``O_CLOEXEC`` (M2) — fd does not leak into spawned subprocesses.

    Factored out so tests can inspect fd flags before the writer hands the
    fd off. Callers are responsible for ``os.close``.
    """
    open_flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    o_nofollow = getattr(os, "O_NOFOLLOW", 0)
    o_cloexec = getattr(os, "O_CLOEXEC", 0)
    open_flags |= o_nofollow | o_cloexec
    try:
        fd = os.open(str(path), open_flags, 0o644)
    except OSError as e:
        if e.errno == errno.ELOOP:
            raise AuditLogRefusedError(
                e.errno,
                f"atomic_append_log: refusing to follow symlink at {path}",
            ) from e
        raise
    # Belt-and-suspenders for POSIX platforms where O_CLOEXEC is 0 (absent):
    # set FD_CLOEXEC explicitly via fcntl so the test invariant holds portably.
    # On Windows there is no fcntl and inheritance is controlled differently;
    # the audit-append path is not used in production Windows installs yet.
    if not o_cloexec and _fcntl is not None:  # pragma: no cover
        flags = _fcntl.fcntl(fd, _fcntl.F_GETFD)
        _fcntl.fcntl(fd, _fcntl.F_SETFD, flags | _fcntl.FD_CLOEXEC)
    return fd


def atomic_append_log(path: Path, line: str, *, max_bytes_per_line: int = 512) -> None:
    """Append one ``line`` to ``path`` atomically.

    Uses ``O_WRONLY | O_APPEND | O_CREAT`` + a single ``os.write`` of a
    PIPE_BUF-safe (<=512 bytes including trailing newline) payload so
    concurrent writers cannot tear each other's records. ``flock`` is
    added in a subsequent commit to harden against non-POSIX-append FS;
    on Linux/macOS POSIX append already provides the no-tear guarantee
    below 512 bytes.
    """
    path = Path(path)
    payload = line if line.endswith("\n") else line + "\n"
    encoded = payload.encode("utf-8")
    # Precondition: enforce PIPE_BUF-safe budget BEFORE any FS work (no
    # partial state, no log file created on oversize input).
    if len(encoded) > max_bytes_per_line:
        raise ValueError(
            f"atomic_append_log: encoded line length {len(encoded)} exceeds "
            f"max_bytes_per_line={max_bytes_per_line} (PIPE_BUF-safe budget)"
        )
    fd = _open_audit_log(path)
    try:
        # flock(LOCK_EX) serializes writers across processes. POSIX O_APPEND
        # already gives <PIPE_BUF atomicity but flock guards against non-POSIX
        # FS variants and ensures the documented semantics hold portably.
        # M3: non-blocking acquisition. On contention, raise a typed sentinel
        # immediately so the caller can decide retry/backoff policy rather
        # than block this thread indefinitely.
        if _fcntl is not None:
            try:
                _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            except BlockingIOError as e:
                raise AuditLogContendedError(
                    e.errno or errno.EWOULDBLOCK,
                    f"atomic_append_log: lock contended on {path}",
                ) from e
            try:
                os.write(fd, encoded)
            finally:
                _fcntl.flock(fd, _fcntl.LOCK_UN)
        elif _msvcrt is not None:
            # Windows: byte-range lock via msvcrt.locking. LK_NBLCK = non-
            # blocking; mirrors POSIX LOCK_NB semantics. Lock region of 1 byte
            # at the current file position; on append-mode fd the position is
            # at EOF, but msvcrt operates at fd-position which is 0 for a fresh
            # append fd until first write. We seek to 0 first to lock the
            # whole-file logical region [0, 1) as a coarse mutex.
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                _msvcrt.locking(fd, _msvcrt.LK_NBLCK, 1)
            except OSError as e:
                raise AuditLogContendedError(
                    e.errno or errno.EWOULDBLOCK,
                    f"atomic_append_log: lock contended on {path}",
                ) from e
            try:
                # Seek back to EOF for append semantics; O_APPEND on Windows is
                # not guaranteed to atomically reposition on every write, so do
                # it explicitly.
                os.lseek(fd, 0, os.SEEK_END)
                os.write(fd, encoded)
            finally:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    _msvcrt.locking(fd, _msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
        else:  # pragma: no cover — neither fcntl nor msvcrt
            os.write(fd, encoded)
    finally:
        os.close(fd)
