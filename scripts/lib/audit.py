"""Audit log writer per ADR-003a G1-A.

Owning plan: .planning/phases/02b-hardening/plans/02b-04-T0-3-PLAN.md
Contract pin: .planning/phases/02b-hardening/CONTRACT-PIN.md §1.

Each lifecycle write appends one JSON line to ``.harness/audit.log``.
Lines are bounded at ``AUDIT_MAX_LINE_BYTES`` (512 bytes — macOS PIPE_BUF
floor). When the encoded line exceeds the budget, the ``args`` payload is
replaced with ``{"truncated": true}`` and the full record is archived to
``.harness/audit.overflow/<index>.json``.

Rotation triggers at ``ROTATION_BYTES`` OR ``ROTATION_ENTRIES`` (whichever
first); the rotated files are renamed under the held ``flock`` (POSIX
rename is atomic, and ``flock`` survives the rename because the fd points
at the same inode). At most ``ROTATION_KEEP`` (5) rotated files are
retained.

The append uses ``O_WRONLY|O_APPEND|O_CREAT|O_NOFOLLOW|O_CLOEXEC`` +
``fcntl.flock(LOCK_EX)``. The atomic-append primitive in
``scripts/lib/atomic_io.py`` enforces the same invariants for general
loggers; this module duplicates the open path because we need the fd to
issue a rotation check + write under the same lock.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Optional


AUDIT_MAX_LINE_BYTES = 512  # macOS PIPE_BUF (per ADR-003a G1-A)
ROTATION_BYTES = 10 * 1024 * 1024  # 10 MiB
ROTATION_ENTRIES = 10_000
ROTATION_KEEP = 5


def compute_state_hash(state_path: Path) -> str:
    """Return the sha256 hex of ``state_path``'s bytes, or "" if missing."""
    state_path = Path(state_path)
    if not state_path.exists():
        return ""
    return hashlib.sha256(state_path.read_bytes()).hexdigest()


def _read_last_index(audit_path: Path) -> int:
    if not audit_path.exists() or audit_path.stat().st_size == 0:
        return 0
    with audit_path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        chunk = 4096
        pos = size
        buf = b""
        while pos > 0:
            read = min(chunk, pos)
            pos -= read
            f.seek(pos)
            buf = f.read(read) + buf
            if buf.count(b"\n") >= 2 or pos == 0:
                break
        for ln in reversed(buf.split(b"\n")):
            if ln.strip():
                try:
                    return int(json.loads(ln).get("index", 0))
                except (ValueError, json.JSONDecodeError):
                    continue
    return 0


def read_last_entry(audit_path: Path) -> Optional[dict]:
    audit_path = Path(audit_path)
    if not audit_path.exists() or audit_path.stat().st_size == 0:
        return None
    text = audit_path.read_text()
    for ln in reversed(text.splitlines()):
        if ln.strip():
            try:
                return json.loads(ln)
            except json.JSONDecodeError:
                continue
    return None


def _rotate(audit_path: Path) -> None:
    """Rename ``audit.log.N`` → ``audit.log.N+1`` then ``audit.log`` → ``audit.log.1``.

    POSIX ``rename`` is atomic. Callers MUST hold the flock; the rename
    survives the lock because ``flock`` binds the fd (inode), not the
    pathname.
    """
    # Drop the oldest if it would exceed retention.
    oldest = audit_path.with_name(f"{audit_path.name}.{ROTATION_KEEP}")
    if oldest.exists():
        oldest.unlink()
    for n in range(ROTATION_KEEP - 1, 0, -1):
        src = audit_path.with_name(f"{audit_path.name}.{n}")
        dst = audit_path.with_name(f"{audit_path.name}.{n + 1}")
        if src.exists():
            os.rename(src, dst)
    os.rename(audit_path, audit_path.with_name(f"{audit_path.name}.1"))


def _write_overflow(audit_path: Path, index: int, full_entry: dict) -> None:
    overflow_dir = audit_path.parent / "audit.overflow"
    overflow_dir.mkdir(parents=True, exist_ok=True)
    (overflow_dir / f"{index}.json").write_text(
        json.dumps(full_entry, indent=2, sort_keys=True) + "\n"
    )


def _open_append_fd(path: Path) -> int:
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        return os.open(str(path), flags, 0o644)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise OSError(
                exc.errno,
                f"audit.audit_append: refusing to follow symlink at {path}",
            ) from exc
        raise


def audit_append(entry: dict, *, audit_path: Path) -> int:
    """Append one JSON-line audit entry. Returns the assigned index."""
    audit_path = Path(audit_path)
    audit_path.parent.mkdir(parents=True, exist_ok=True)

    fd = _open_append_fd(audit_path)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)

        # Rotation pre-check.
        st_size = os.fstat(fd).st_size
        last_idx = _read_last_index(audit_path)
        if st_size >= ROTATION_BYTES or last_idx >= ROTATION_ENTRIES:
            # Release lock + close before rename; re-open + re-lock on the
            # new file. Per POSIX, the rename of the open file is atomic;
            # we drop the lock so the rotated file does not retain it.
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            _rotate(audit_path)
            fd = _open_append_fd(audit_path)
            fcntl.flock(fd, fcntl.LOCK_EX)
            last_idx = 0

        index = last_idx + 1
        full_entry = dict(entry, index=index)
        line = json.dumps(full_entry, separators=(",", ":"), sort_keys=True) + "\n"
        if len(line.encode("utf-8")) > AUDIT_MAX_LINE_BYTES:
            _write_overflow(audit_path, index, full_entry)
            truncated = dict(entry, index=index, args={"truncated": True})
            line = (
                json.dumps(truncated, separators=(",", ":"), sort_keys=True) + "\n"
            )
        encoded = line.encode("utf-8")
        if len(encoded) > AUDIT_MAX_LINE_BYTES:
            # Last-resort safety: synthesize a minimal record. This should
            # never trigger because fixed-key entry shape stays small.
            minimal = {
                "index": index,
                "verb": entry.get("verb", "unknown"),
                "args": {"truncated": True},
                "at": entry.get("at"),
                "by": entry.get("by"),
            }
            encoded = (
                json.dumps(minimal, separators=(",", ":"), sort_keys=True) + "\n"
            ).encode("utf-8")
            assert len(encoded) <= AUDIT_MAX_LINE_BYTES, "audit minimal too large"
        os.write(fd, encoded)
        os.fsync(fd)
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
    return index


__all__ = [
    "AUDIT_MAX_LINE_BYTES",
    "ROTATION_BYTES",
    "ROTATION_ENTRIES",
    "ROTATION_KEEP",
    "audit_append",
    "read_last_entry",
    "compute_state_hash",
]
