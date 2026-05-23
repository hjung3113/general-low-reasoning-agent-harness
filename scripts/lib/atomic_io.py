"""Atomic I/O primitives for managed state and operational logs.

Owning plan: .planning/milestones/02b-hardening/plans/02b-01-T0-A-PLAN.md (T0-A)
Contract pin: .planning/milestones/02b-hardening/CONTRACT-PIN.md §1
ADR: docs/adr/2026-05-16-hardening-bundle.md (Artifact 2, G1-A, G1-D)

Exports (skeleton — bodies filled in subsequent commits per plan task order):
- atomic_write_text(path, content, *, mode=0o644)
- atomic_append_log(path, line, *, max_bytes_per_line=512)
- atomic_install_batch(staging_dir, target, journal_path, *, sort_key=None)
"""

from __future__ import annotations

import datetime
import errno
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

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


# ---------------------------------------------------------------------------
# atomic_install_batch — per-file atomic rename with journal (T14a)
# ---------------------------------------------------------------------------


class CrossFilesystemError(OSError):
    """Raised when staging_dir and target reside on different filesystems.

    ``os.replace`` is only atomic within a single filesystem. The caller is
    responsible for co-locating the staging dir with the target (e.g. under
    ``$TARGET/.harness/.staging-<pid>/``).
    """


@dataclass
class AtomicInstallResult:
    """Outcome of :func:`atomic_install_batch`.

    ``completed``  — relative paths successfully renamed into ``target``.
    ``failed_entry`` — relative path of the entry that raised, or ``None``.
    ``aborted``    — ``True`` when a rename failed and ``.aborted`` sentinel
                     was written into the staging dir.
    """

    completed: List[str] = field(default_factory=list)
    failed_entry: Optional[str] = None
    aborted: bool = False


def _write_completion_sentinel(staging_dir: Path) -> None:
    """Write a durable completion sentinel alongside *staging_dir*.

    Sentinel path: ``staging_dir.parent / (staging_dir.name + ".complete")``
    Written via fsync(tmp_fd) + os.replace + fsync(parent_dir_fd) for
    durability.  The ``.complete.tmp`` intermediate is always unlinked (either
    by os.replace on success, or explicitly on failure).
    """
    sentinel_path = staging_dir.parent / (staging_dir.name + ".complete")
    sentinel_tmp = staging_dir.parent / (staging_dir.name + ".complete.tmp")
    fd = os.open(str(sentinel_tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.replace(str(sentinel_tmp), str(sentinel_path))
    except BaseException:
        # If os.replace fails, clean up the tmp file so it doesn't linger.
        try:
            os.unlink(str(sentinel_tmp))
        except FileNotFoundError:
            pass
        raise
    parent_fd = os.open(str(sentinel_path.parent), os.O_RDONLY)
    try:
        try:
            os.fsync(parent_fd)
        except OSError:
            pass  # best-effort on platforms that reject dir fsync
    finally:
        os.close(parent_fd)


def _cleanup_staging_and_journal(staging_dir: Path, journal_path: Path) -> None:
    """Best-effort cleanup of staging directory and journal file."""
    try:
        _rmdir_recursive(staging_dir)
    except OSError:
        pass
    try:
        journal_path.unlink()
    except FileNotFoundError:
        pass


def atomic_install_batch(
    staging_dir: Path,
    target: Path,
    journal_path: Path,
    *,
    sort_key: Optional[Callable[[str], object]] = None,
    defer_cleanup: bool = False,
    progress: Optional[Callable[[int, int], None]] = None,
) -> AtomicInstallResult:
    """Rename files from ``staging_dir`` into ``target`` via ``os.replace``.

    Per-file atomic, NOT whole-batch atomic
    ----------------------------------------
    Each ``os.replace`` call is atomic on POSIX (same filesystem).  The *batch
    as a whole* is **not** atomic: a process kill between renames leaves some
    files already installed and some still in the staging dir.

    Recovery contract
    -----------------
    On partial failure the staging dir is left intact (not cleaned up) so that
    ``install_recovery`` (T14b) can resume.  Callers must NOT delete the
    staging dir on a non-zero result.

    Journal format
    --------------
    One JSON-line per completed rename::

        {"src_rel": "lib/foo.py", "dst_rel": "scripts/lib/foo.py", "rename_at_iso": "..."}

    On failure an additional line records the error::

        {"src_rel": "lib/bar.py", "error": "..."}

    Idempotency
    -----------
    If a file appears in the journal as already completed AND the corresponding
    source in ``staging_dir`` is absent (it was moved on a prior run), that
    entry is skipped.  Re-running on a partially-completed staging dir resumes
    from the first unprocessed entry.

    Parameters
    ----------
    staging_dir:
        Directory whose contents will be renamed into ``target``.  Must be on
        the same filesystem as ``target``.
    target:
        Destination root.  Subdirectories are created as needed.
    journal_path:
        File that records completed renames.  May already exist (idempotent
        resume from prior run).
    sort_key:
        Optional callable to derive the sort key from a relative-path string.
        Defaults to identity (lexicographic order).

    Returns
    -------
    AtomicInstallResult
        ``completed`` lists every relative path successfully renamed.
        ``failed_entry`` is set if any rename raised.  ``aborted`` is
        ``True`` when a ``.aborted`` sentinel was written.

    Raises
    ------
    CrossFilesystemError
        If ``staging_dir`` and ``target`` are on different filesystems.
    """
    staging_dir = Path(staging_dir)
    target = Path(target)
    journal_path = Path(journal_path)

    # Same-filesystem requirement: verify before any work.
    staging_dev = os.stat(str(staging_dir)).st_dev
    target_dev = os.stat(str(target)).st_dev
    if staging_dev != target_dev:
        raise CrossFilesystemError(
            errno.EXDEV,
            (
                f"atomic_install_batch: staging_dir st_dev={staging_dev} differs "
                f"from target st_dev={target_dev}; cross-filesystem rename is not "
                f"atomic.  Co-locate staging_dir under target "
                f"(e.g. $TARGET/.harness/.staging-<pid>/)."
            ),
        )

    # ------------------------------------------------------------------
    # Collect all relative paths in staging_dir.
    # ------------------------------------------------------------------
    rel_paths: List[str] = []
    for dirpath, _dirs, filenames in os.walk(str(staging_dir)):
        for fname in filenames:
            abs_src = Path(dirpath) / fname
            rel = str(abs_src.relative_to(staging_dir))
            rel_paths.append(rel)

    # Deterministic order.
    rel_paths.sort(key=sort_key)

    # ------------------------------------------------------------------
    # Load already-completed entries from an existing journal (idempotent).
    # ------------------------------------------------------------------
    already_completed: set[str] = set()
    if journal_path.exists():
        with open(str(journal_path), encoding="utf-8") as jf:
            for raw_line in jf:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    rec = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if "error" not in rec and "src_rel" in rec:
                    already_completed.add(rec["src_rel"])

    # ------------------------------------------------------------------
    # Open journal for appending (create if absent).
    # ------------------------------------------------------------------
    result = AtomicInstallResult()
    result.completed = list(already_completed)  # carry forward prior completions

    journal_path.parent.mkdir(parents=True, exist_ok=True)

    _total = len(rel_paths)
    _done = len(already_completed)
    if progress is not None:
        try:
            progress(_done, _total)
        except Exception:
            pass  # progress is advisory; never abort install for a callback bug

    with open(str(journal_path), "a", encoding="utf-8") as jf:
        for rel in rel_paths:
            src = staging_dir / rel
            dst = target / rel

            # Skip entries already handled in a prior (or earlier) run.
            if rel in already_completed:
                continue

            # Source may have already been moved if we are re-entering after a
            # crash mid-loop.
            if not src.exists():
                # Treat as completed if dst already exists.
                if dst.exists():
                    result.completed.append(rel)
                    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    jf.write(
                        json.dumps(
                            {"src_rel": rel, "dst_rel": rel, "rename_at_iso": ts}
                        )
                        + "\n"
                    )
                    jf.flush()
                    _done += 1
                    if progress is not None:
                        try:
                            progress(_done, _total)
                        except Exception:
                            pass
                # If neither src nor dst exists, silently skip (entry vanished).
                continue

            # Ensure destination parent directory exists.
            dst.parent.mkdir(parents=True, exist_ok=True)

            try:
                # v0.9.11: route through replace_with_retry so Windows
                # AV/indexer transient PermissionError on individual files
                # gets the same 100/250/500/1000/2000/4000 ms backoff as
                # atomic_write_text. Previously this raw os.replace would
                # fail the entire batch on the first locked file.
                from .durable_fs import replace_with_retry as _rwr
                _rwr(str(src), str(dst))
            except OSError as exc:
                # Record the failure in the journal.
                jf.write(
                    json.dumps({"src_rel": rel, "error": str(exc)}) + "\n"
                )
                jf.flush()

                # Write .aborted sentinel into staging_dir.
                sentinel = staging_dir / ".aborted"
                try:
                    sentinel.write_text(
                        json.dumps(
                            {
                                "failed_rel": rel,
                                "error": str(exc),
                                "aborted_at_iso": datetime.datetime.now(
                                    datetime.timezone.utc
                                ).isoformat(),
                            }
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                except OSError:
                    pass  # Best-effort sentinel; don't mask the real error.

                result.failed_entry = rel
                result.aborted = True
                return result

            # Rename succeeded — append to journal BEFORE moving on.
            ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
            jf.write(
                json.dumps({"src_rel": rel, "dst_rel": rel, "rename_at_iso": ts}) + "\n"
            )
            jf.flush()
            result.completed.append(rel)
            _done += 1
            if progress is not None:
                try:
                    progress(_done, _total)
                except Exception:
                    pass

    # Success path: cleanup or defer (write sentinel).
    if not result.aborted:
        if defer_cleanup:
            _write_completion_sentinel(staging_dir)
        else:
            _cleanup_staging_and_journal(staging_dir, journal_path)

    return result


def _rmdir_recursive(path: Path) -> None:
    """Remove ``path`` and all its contents (best-effort helper)."""
    for child in path.iterdir():
        if child.is_dir():
            _rmdir_recursive(child)
        else:
            child.unlink()
    path.rmdir()


# ---------------------------------------------------------------------------
# Journal reader helper (T14b — used by install_recovery)
# ---------------------------------------------------------------------------


def read_install_journal(journal_path: Path) -> List[dict]:
    """Parse an install journal file into a list of record dicts.

    Each JSONL line is returned as a dict; malformed lines are silently
    skipped (journal may be partially-written after a crash).

    Returns an empty list when the journal does not exist.
    """
    journal_path = Path(journal_path)
    if not journal_path.exists():
        return []
    records: List[dict] = []
    with open(str(journal_path), encoding="utf-8") as jf:
        for raw in jf:
            raw = raw.strip()
            if not raw:
                continue
            try:
                records.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return records
