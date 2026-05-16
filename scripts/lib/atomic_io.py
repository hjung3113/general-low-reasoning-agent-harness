"""Atomic I/O primitives for managed state and operational logs.

Owning plan: .planning/phases/02b-hardening/plans/02b-01-T0-A-PLAN.md (T0-A)
Contract pin: .planning/phases/02b-hardening/CONTRACT-PIN.md §1
ADR: docs/adr/2026-05-16-hardening-bundle.md (Artifact 2, G1-A, G1-D)

Exports (skeleton — bodies filled in subsequent commits per plan task order):
- atomic_write_text(path, content, *, mode=0o644)
- atomic_append_log(path, line, *, max_bytes_per_line=512)
"""

from __future__ import annotations

import fcntl
import os
import tempfile
from pathlib import Path


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
            os.fsync(tmp.fileno())
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
        os.replace(tmp_name, path)
    except BaseException:
        # Clean up orphan tempfile on any failure (incl. OSError, RuntimeError,
        # KeyboardInterrupt).
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
    os.chmod(path, mode)


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
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        # flock(LOCK_EX) serializes writers across processes. POSIX O_APPEND
        # already gives <PIPE_BUF atomicity but flock guards against non-POSIX
        # FS variants and ensures the documented semantics hold portably.
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            os.write(fd, encoded)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
