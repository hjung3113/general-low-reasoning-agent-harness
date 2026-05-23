"""Audit log writer — plain JSONL per ADR-0005.

Each lifecycle write appends one JSON line to ``.harness/audit.jsonl``.
Lines are bounded at ``AUDIT_MAX_LINE_BYTES`` (1024 bytes). When the
encoded line exceeds the budget, the ``args`` payload is replaced with
``{"truncated": true}`` and the full record is archived to
``.harness/audit.overflow/<index>.json``.

No hash chain, no entry_hash, no rotation seam entry. ADR-0005: plain JSONL.
ADR-0004: atomic write + primary lock only. ADR-0002: no external attacker.

Rotation triggers at ``ROTATION_BYTES`` OR ``ROTATION_ENTRIES`` (whichever
first); the rotated files are renamed under the held ``flock`` (POSIX
rename is atomic, and ``flock`` survives the rename because the fd points
at the same inode). At most ``ROTATION_KEEP`` (5) rotated files are
retained.

The append uses ``O_WRONLY|O_APPEND|O_CREAT|O_NOFOLLOW|O_CLOEXEC`` +
``fcntl.flock(LOCK_EX)``.
"""

from __future__ import annotations

import datetime
import errno
import hashlib
import json
import os
from pathlib import Path

# Conditional locking primitives so the audit module (transitively imported by
# nearly every CLI surface) is importable on Windows. POSIX uses fcntl.flock;
# Windows uses msvcrt.locking byte-range locks.
if os.name == "posix":
    import fcntl as _fcntl  # type: ignore[import]
    _msvcrt = None  # type: ignore[assignment]
else:
    _fcntl = None  # type: ignore[assignment]
    try:
        import msvcrt as _msvcrt  # type: ignore[import]
    except ImportError:  # pragma: no cover
        _msvcrt = None  # type: ignore[assignment]

from typing import Optional


def _audit_lock(fd: int, *, mode: str) -> None:
    """Acquire ('ex') or release ('un') an exclusive lock on ``fd``.

    POSIX: fcntl.flock(LOCK_EX|LOCK_UN). Windows: msvcrt.locking on the
    [0, 1) byte range as a coarse whole-file mutex. Best-effort on platforms
    that lack both primitives.
    """
    if _fcntl is not None:
        if mode == "ex":
            _fcntl.flock(fd, _fcntl.LOCK_EX)
        else:
            _fcntl.flock(fd, _fcntl.LOCK_UN)
        return
    if _msvcrt is not None:
        cur = os.lseek(fd, 0, os.SEEK_CUR)
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            if mode == "ex":
                _msvcrt.locking(fd, _msvcrt.LK_LOCK, 1)
            else:
                _msvcrt.locking(fd, _msvcrt.LK_UNLCK, 1)
        finally:
            try:
                os.lseek(fd, cur, os.SEEK_SET)
            except OSError:
                pass


AUDIT_MAX_LINE_BYTES = 1024
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


def _rotate(audit_path: Path, *, fd: int) -> None:
    """Rename audit.log → audit.log.1 under the held flock.

    No seam entry is written (ADR-0005: plain JSONL, no hash chain).
    Steps (all under the already-held flock on ``fd``):
      1. Shift existing rotation files (N → N+1) then rename current → .1.
      2. fsync parent dir.

    Callers MUST hold the flock on ``fd`` before calling this function.
    POSIX ``rename`` is atomic; ``flock`` binds the inode so the lock
    survives the rename.
    """
    oldest = audit_path.with_name(f"{audit_path.name}.{ROTATION_KEEP}")
    if oldest.exists():
        oldest.unlink()
    for n in range(ROTATION_KEEP - 1, 0, -1):
        src = audit_path.with_name(f"{audit_path.name}.{n}")
        dst = audit_path.with_name(f"{audit_path.name}.{n + 1}")
        if src.exists():
            os.rename(src, dst)
    os.rename(audit_path, audit_path.with_name(f"{audit_path.name}.1"))

    try:
        parent_fd = os.open(str(audit_path.parent), os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except OSError:
        pass


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


# ---------------------------------------------------------------------------
# P5-P2-1 (cycle-1 review fix): §12.7 verb registry
# ---------------------------------------------------------------------------

KNOWN_VERBS: frozenset = frozenset([
    # Phase lifecycle verbs
    "phase.set",
    "phase.set.noop",
    "phase.set.idempotent-noop",
    "phase.approve",
    "phase.reopen",
    # Audit infrastructure verbs
    "audit.rotated",
    "audit.repair",
    # CLI / session verbs
    "approve_nonce.mint",
    "session.unlock",
    "lock.recovered",
    # Migration / CI verbs
    "migrate.state_v2",
    "ci.oidc.jti.consumed",
    "ci.oidc.jti.replay",
    "ci.oidc.jti.store_rotated",
    "ci.oidc.jti.dir_override",
    # FSD dashboard verbs (slash-command wrappers)
    "fsd-run-all",
    "fsd-run-phase",
    # Install bootstrap verbs (T7 / NEW-1)
    "install_record.bootstrap",
    # Install recovery verbs (T14b)
    "install.recovery.finished",
    "install.recovery.rolled_back",
    "install.recovery.quarantined",
    "install.recovery.noop",
])


def audit_append(entry: dict, *, audit_path: Path) -> int:
    """Append one JSON-line audit entry. Returns the assigned index.

    Stamps schema_version=1, index, and at (if absent) on every entry.
    No hash chain fields. ADR-0005: plain JSONL.

    P5-P2-1: validates entry verb against KNOWN_VERBS. In strict mode
    (HARNESS_STRICT_VERB_REGISTRY=1) an unknown verb raises SystemExit(10).
    In permissive mode (default) a WARNING is printed to stderr.
    """
    # Verb registry check (P5-P2-1)
    verb = entry.get("verb", "")
    if verb not in KNOWN_VERBS:
        import sys as _sys
        msg = (
            f"audit_append: unknown verb {verb!r} not in KNOWN_VERBS registry "
            f"(§12.7). Add it to KNOWN_VERBS in scripts/lib/audit.py."
        )
        if os.environ.get("HARNESS_STRICT_VERB_REGISTRY") == "1":
            _sys.stderr.write(f"error: {msg}\n")
            raise SystemExit(10)
        else:
            _sys.stderr.write(f"WARNING: {msg}\n")

    audit_path = Path(audit_path)
    audit_path.parent.mkdir(parents=True, exist_ok=True)

    fd = _open_append_fd(audit_path)
    try:
        _audit_lock(fd, mode="ex")

        # Rotation pre-check under the held flock.
        st_size = os.fstat(fd).st_size
        last_idx = _read_last_index(audit_path)
        if st_size >= ROTATION_BYTES or last_idx >= ROTATION_ENTRIES:
            _rotate(audit_path, fd=fd)
            # Open the new (empty) audit.log. The old fd (still flocked)
            # now refers to audit.log.1; closing it releases the old-inode
            # lock. We acquire the new-inode lock BEFORE closing the old
            # fd so any racing acquirer that beats us to the new file
            # serializes correctly.
            new_fd = _open_append_fd(audit_path)
            _audit_lock(new_fd, mode="ex")
            try:
                _audit_lock(fd, mode="un")
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass
            fd = new_fd
            last_idx = 0

        index = last_idx + 1
        now_iso = (
            datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

        full_entry = dict(entry)
        full_entry["index"] = index
        full_entry.setdefault("schema_version", 1)
        full_entry.setdefault("at", now_iso)

        line = json.dumps(full_entry, separators=(",", ":"), sort_keys=True) + "\n"
        if len(line.encode("utf-8")) > AUDIT_MAX_LINE_BYTES:
            _write_overflow(audit_path, index, full_entry)
            truncated = dict(entry)
            truncated["index"] = index
            truncated["schema_version"] = full_entry["schema_version"]
            truncated["at"] = full_entry["at"]
            truncated["args"] = {"truncated": True}
            line = (
                json.dumps(truncated, separators=(",", ":"), sort_keys=True) + "\n"
            )

        encoded = line.encode("utf-8")
        if len(encoded) > AUDIT_MAX_LINE_BYTES:
            # Last-resort minimal fallback. Keep identity discriminators
            # (by_source, confirmation_kind) truncation-resilient per §12.5 #1.
            minimal = {
                "index": index,
                "verb": entry.get("verb", "unknown"),
                "schema_version": 1,
                "args": {"truncated": True},
                "at": entry.get("at", now_iso),
                "by": entry.get("by"),
                "by_source": entry.get("by_source"),
                "confirmation_kind": entry.get("confirmation_kind"),
            }
            if minimal["by_source"] is None:
                del minimal["by_source"]
            if minimal["confirmation_kind"] is None:
                del minimal["confirmation_kind"]
            if minimal["by"] is None:
                del minimal["by"]
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
            _audit_lock(fd, mode="un")
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
    "KNOWN_VERBS",
    "audit_append",
    "read_last_entry",
    "compute_state_hash",
]
