"""Atomic I/O primitives for managed state and operational logs.

Owning plan: .planning/phases/02b-hardening/plans/02b-01-T0-A-PLAN.md (T0-A)
Contract pin: .planning/phases/02b-hardening/CONTRACT-PIN.md §1
ADR: docs/adr/2026-05-16-hardening-bundle.md (Artifact 2, G1-A, G1-D)

Exports (skeleton — bodies filled in subsequent commits per plan task order):
- atomic_write_text(path, content, *, mode=0o644)
- atomic_append_log(path, line, *, max_bytes_per_line=512)
"""

from __future__ import annotations

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
    """Atomic append skeleton — body lands in subsequent GREEN commits."""
    raise NotImplementedError("atomic_append_log body not yet implemented")
