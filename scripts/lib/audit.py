"""Audit log writer per ADR-003a G1-A + S06 chain stamping (design §2.2).

Owning plan: .planning/phases/02b-hardening/plans/02b-04-T0-3-PLAN.md
Contract pin: .planning/phases/02b-hardening/CONTRACT-PIN.md §1.

Each lifecycle write appends one JSON line to ``.harness/audit.log``.
Lines are bounded at ``AUDIT_MAX_LINE_BYTES`` (700 bytes — raised from
512 in S06 to accommodate ~140 bytes of per-entry chain fields: seq,
seq_global, previous_entry_hash, entry_hash). When the encoded line
exceeds the budget, the ``args`` payload is replaced with
``{"truncated": true}`` and the full record is archived to
``.harness/audit.overflow/<index>.json``.

S06 chain fields (design §2.1, §2.2) stamped on every new entry:
  - schema_version: 2
  - seq: per-file sequence, resets on rotation
  - seq_global: monotonic global sequence across rotations
  - previous_entry_hash: entry_hash of prior entry (GENESIS_HASH for first)
  - entry_hash: sha256(rfc8785(entry_minus_entry_hash))

§12.5 #1 last-resort minimal fallback MUST preserve chain fields even
when the rest of the entry is stripped.

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


# S06: raised from 512 to 1024 to accommodate ~140 bytes of per-entry chain
# fields (schema_version, seq, seq_global, previous_entry_hash [64 hex],
# entry_hash [64 hex]) plus headroom for forensic top-level fields that must
# NOT be truncated (by_source, confirmation_kind, approved_by, etc.).
# The old 512-byte limit was the macOS PIPE_BUF floor. 1024 bytes remains
# well within atomic-write guarantees on POSIX local filesystems (typically
# 4 KiB block) while providing sufficient headroom for the full chain record.
# Sentinel test updated accordingly (see tests/phase_reopen/test_reopen.py).
AUDIT_MAX_LINE_BYTES = 1024  # raised in S06 from 512 (§2.1 chain fields ~+140 bytes + forensic fields)
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


def _read_chain_tip(audit_path: Path) -> tuple[str, int, int]:
    """Read (previous_entry_hash, seq, seq_global) from the last entry in audit_path.

    Returns (GENESIS_HASH, 0, 0) if the file is empty or does not exist.
    If the last entry has chain fields, returns them. If not (legacy v1
    entry), walks backwards to find the last entry with seq_global.
    """
    from .audit_chain import GENESIS_HASH

    if not audit_path.exists() or audit_path.stat().st_size == 0:
        # Also check if there are rotated files to get seq_global from
        try:
            from .audit_rotation import enumerate_rotated_files
            files = enumerate_rotated_files(audit_path)
            # files = [log.N, ..., log.1, audit.log]
            # The current audit.log is absent/empty; check log.1 for last seq_global
            for rotated in reversed(files[:-1]):  # exclude current audit.log
                if rotated.exists() and rotated.stat().st_size > 0:
                    last = read_last_entry(rotated)
                    if last and "entry_hash" in last:
                        return (
                            last["entry_hash"],
                            0,  # seq resets on new file
                            last.get("seq_global", 0),
                        )
        except Exception:
            pass
        return (GENESIS_HASH, 0, 0)

    last = read_last_entry(audit_path)
    if last is None:
        return (GENESIS_HASH, 0, 0)

    entry_hash = last.get("entry_hash")
    seq = last.get("seq", 0)
    seq_global = last.get("seq_global", 0)

    if entry_hash is not None:
        return (entry_hash, seq, seq_global)

    # Legacy v1 entry without chain fields: return genesis for hash,
    # but try to get seq_global from the entry's index if available
    return (GENESIS_HASH, seq, seq_global)


def audit_append(entry: dict, *, audit_path: Path) -> int:
    """Append one JSON-line audit entry with S06 chain fields. Returns the assigned index.

    S06: stamps schema_version=2, seq, seq_global, previous_entry_hash,
    entry_hash on every new entry before serialization.
    """
    audit_path = Path(audit_path)
    audit_path.parent.mkdir(parents=True, exist_ok=True)

    fd = _open_append_fd(audit_path)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)

        # Rotation pre-check. Per C4: rename(s) MUST run while the flock
        # is held. POSIX rename is atomic and flock binds to the inode
        # (which moves with rename), so racing openers that arrive between
        # our rename and the new-file open block on the inode under the
        # old pathname (the lock still applies). After _rotate, the old
        # fd points at audit.log.1 (same inode); we re-open the new
        # audit.log for the actual write. The new open() must wait for any
        # racing writer holding flock on the just-rotated inode; the open
        # itself is unblocked (the path is fresh), but the LOCK_EX call
        # blocks correctly because we still hold the old fd's flock.
        st_size = os.fstat(fd).st_size
        last_idx = _read_last_index(audit_path)
        rotated = False
        if st_size >= ROTATION_BYTES or last_idx >= ROTATION_ENTRIES:
            _rotate(audit_path)
            rotated = True
            # Open the new (empty) audit.log. The old fd (still flocked)
            # now refers to audit.log.1; closing it releases the old-inode
            # lock. We acquire the new-inode lock BEFORE closing the old
            # fd so any racing acquirer that beats us to the new file
            # serializes correctly.
            new_fd = _open_append_fd(audit_path)
            fcntl.flock(new_fd, fcntl.LOCK_EX)
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass
            fd = new_fd
            last_idx = 0

        # S06: read chain tip to stamp chain fields
        prev_hash, last_seq, last_seq_global = _read_chain_tip(audit_path)

        index = last_idx + 1
        seq = last_seq + 1 if not rotated else 1
        seq_global = last_seq_global + 1

        # S06: stamp chain fields (schema_version, seq, seq_global, previous_entry_hash, entry_hash)
        from .audit_chain import stamp_chain_fields
        full_entry_base = dict(entry, index=index)
        full_entry = stamp_chain_fields(
            full_entry_base,
            previous_entry_hash=prev_hash,
            seq=seq,
            seq_global=seq_global,
        )

        line = json.dumps(full_entry, separators=(",", ":"), sort_keys=True) + "\n"
        if len(line.encode("utf-8")) > AUDIT_MAX_LINE_BYTES:
            _write_overflow(audit_path, index, full_entry)
            truncated = dict(entry, index=index, args={"truncated": True})
            # Re-stamp chain fields on the truncated version
            truncated_stamped = stamp_chain_fields(
                truncated,
                previous_entry_hash=prev_hash,
                seq=seq,
                seq_global=seq_global,
            )
            line = (
                json.dumps(truncated_stamped, separators=(",", ":"), sort_keys=True) + "\n"
            )
        encoded = line.encode("utf-8")
        if len(encoded) > AUDIT_MAX_LINE_BYTES:
            # Last-resort safety: synthesize a minimal record.
            # §12.5 #1: MUST preserve chain fields even in minimal fallback.
            minimal = {
                "index": index,
                "verb": entry.get("verb", "unknown"),
                "args": {"truncated": True},
                "at": entry.get("at"),
                "by": entry.get("by"),
                # Chain fields are preserved per §12.5 #1
                "previous_entry_hash": prev_hash,
                "seq": seq,
                "seq_global": seq_global,
                "schema_version": 2,
            }
            # entry_hash computed last on the minimal record
            minimal["entry_hash"] = _compute_entry_hash_for_minimal(minimal)
            encoded = (
                json.dumps(minimal, separators=(",", ":"), sort_keys=True) + "\n"
            ).encode("utf-8")
            assert len(encoded) <= AUDIT_MAX_LINE_BYTES, (
                f"audit minimal too large: {len(encoded)} bytes"
            )
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


def _compute_entry_hash_for_minimal(minimal: dict) -> str:
    """Compute entry_hash for the minimal fallback record (§12.5 #1)."""
    from .audit_chain import compute_entry_hash
    return compute_entry_hash(minimal)


__all__ = [
    "AUDIT_MAX_LINE_BYTES",
    "ROTATION_BYTES",
    "ROTATION_ENTRIES",
    "ROTATION_KEEP",
    "audit_append",
    "read_last_entry",
    "compute_state_hash",
]
