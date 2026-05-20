"""Audit log writer per ADR-003a G1-A + S06 chain stamping (design §2.2).

Owning plan: .planning/phases/02b-hardening/plans/02b-04-T0-3-PLAN.md
Contract pin: .planning/phases/02b-hardening/CONTRACT-PIN.md §1.

Each lifecycle write appends one JSON line to ``.harness/audit.log``.
Lines are bounded at ``AUDIT_MAX_LINE_BYTES`` (1024 bytes — raised from
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
                # LK_LOCK blocks (retries) until acquired; matches POSIX
                # LOCK_EX (blocking) semantics used by audit append path.
                _msvcrt.locking(fd, _msvcrt.LK_LOCK, 1)
            else:
                _msvcrt.locking(fd, _msvcrt.LK_UNLCK, 1)
        finally:
            try:
                os.lseek(fd, cur, os.SEEK_SET)
            except OSError:
                pass
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


def _rotate(audit_path: Path, *, fd: int) -> str:
    """Emit audit.rotated seam entry, then rename audit.log → audit.log.1.

    §2.5 requires the LAST entry of the rotated-out file to be
    ``verb=audit.rotated`` with ``next_file_seed_previous_entry_hash`` so
    verifiers and the new-file opener can walk across the rotation boundary
    without out-of-band metadata.

    Steps (all under the already-held flock on ``fd``):
      1. Read current chain tip to get tip_hash, tip_seq, tip_seq_global.
      2. Build and stamp the ``audit.rotated`` seam entry (chained).
      3. Write + fsync the seam entry to ``audit.log`` via ``fd``.
      4. fsync parent dir.
      5. Shift existing rotation files (N → N+1) then rename current → .1.
      6. Return ``next_file_seed_previous_entry_hash`` for the new file's
         first entry.

    Callers MUST hold the flock on ``fd`` before calling this function.
    POSIX ``rename`` is atomic; ``flock`` binds the inode so the lock
    survives the rename.
    """
    import datetime
    from .audit_chain import stamp_chain_fields

    # Step 1 — read current tip
    prev_hash, last_seq, last_seq_global = _read_chain_tip(audit_path)

    # Step 2 — build seam entry
    # The seam entry is a normal chained entry (entry_hash covers all fields
    # except entry_hash and previous_entry_hash per the ADR D-3 formula).
    # next_file_seed_previous_entry_hash is set to the seam entry's own
    # entry_hash so the verifier and next-file opener can find the seed
    # without recomputing.  The new file's first entry uses this value as
    # its previous_entry_hash.
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    seam_seq = last_seq + 1
    seam_seq_global = last_seq_global + 1
    seam_draft = {
        "verb": "audit.rotated",
        "at": now,
        "index": _read_last_index(audit_path) + 1,
    }
    # Stamp to get the chained entry_hash
    seam_entry = stamp_chain_fields(
        seam_draft,
        previous_entry_hash=prev_hash,
        seq=seam_seq,
        seq_global=seam_seq_global,
    )
    # Store the seam entry's entry_hash as the seed for the new file's first
    # entry.  This field is metadata (forward-pointer) and is NOT included in
    # the seam entry's own hash computation (entry_hash was already finalized).
    seed_hash = seam_entry["entry_hash"]
    seam_entry["next_file_seed_previous_entry_hash"] = seed_hash

    # Step 3 — write seam entry to current audit.log via the held fd
    line = json.dumps(seam_entry, separators=(",", ":"), sort_keys=True) + "\n"
    os.write(fd, line.encode("utf-8"))
    os.fsync(fd)

    # Step 4 — fsync parent directory
    try:
        parent_fd = os.open(str(audit_path.parent), os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except OSError:
        pass  # Best-effort; main fsync already done above

    # Step 5 — shift and rename
    oldest = audit_path.with_name(f"{audit_path.name}.{ROTATION_KEEP}")
    if oldest.exists():
        oldest.unlink()
    for n in range(ROTATION_KEEP - 1, 0, -1):
        src = audit_path.with_name(f"{audit_path.name}.{n}")
        dst = audit_path.with_name(f"{audit_path.name}.{n + 1}")
        if src.exists():
            os.rename(src, dst)
    os.rename(audit_path, audit_path.with_name(f"{audit_path.name}.1"))

    return seed_hash


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


# ---------------------------------------------------------------------------
# P5-P2-1 (cycle-1 review fix): §12.7 verb registry
#
# KNOWN_VERBS is the authoritative table of all verb literals emitted by
# scripts/lib/.  In HARNESS_STRICT_VERB_REGISTRY=1 mode, audit_append
# rejects unknown verbs with exit 10.  In the default (permissive) mode,
# an unknown verb logs a WARNING to stderr but still appends (new verbs may
# be added intentionally during development without needing to update this
# table first).
#
# When adding a new verb to scripts/lib/ ALSO add it here.
# Spec: §12.7 verb registry.
# ---------------------------------------------------------------------------

KNOWN_VERBS: frozenset = frozenset([
    # Phase lifecycle verbs
    "phase.set",
    "phase.set.noop",
    "phase.set.idempotent-noop",  # T13 NEW-5: done→done byte-identical noop
    "phase.approve",
    "phase.reopen",
    # Autopilot verbs
    "phase.autopilot.start",
    "phase.autopilot.stop",
    "phase.autopilot.halt",
    "phase.autopilot.halt.budget",            # budget-halt alias (txn verb)
    "phase.autopilot.start_hash_finalized",   # hash committed after start
    "phase.autopilot.start.refused",          # start refused (budget/preflight)
    "phase.autopilot.start.recover_pending",  # recovery path from pending start
    # Budget verbs
    "phase.budget.halt",                      # budget exhausted halt (txn verb)
    # Audit infrastructure verbs
    "audit.rotated",
    "audit.repair",
    # Halt diary verbs
    "halt_diary.clear",
    # Fence / network guard verbs
    "autopilot.fence.deny",
    "autopilot.network.deny",
    # CLI / session verbs
    "approve_nonce.mint",
    "cli.deprecated_flag",
    "session.unlock",
    "lock.recovered",
    # Migration / CI verbs
    "migrate.state_v2",
    "ci.oidc.jti.consumed",
    "ci.oidc.jti.replay",
    "ci.oidc.jti.store_rotated",   # P2-A5: corrupted JTI store rotation event
    "ci.oidc.jti.dir_override",    # C-4 (Cycle-2): HARNESS_JTI_DIR env override detected
    "audit.secret_key.rotated",    # B3-Fix-7: corrupt secret.key rotated aside
    # FSD dashboard verbs (slash-command wrappers)
    "fsd-run-all",
    "fsd-run-phase",
    # Release trust verbs (§6, Group δ fix-pass)
    "release.trust.verified",   # SSH-signed tag verified successfully
    "release.trust.bypassed",   # HARNESS_ALLOW_UNSIGNED_DEV=1 bypass taken
    "release.trust.refused",    # exit-15 refusal (downgrade / missing trust / corrupted manifest)
    "release.trust.rechained",  # T16: chain hash changed during upgrade; cause classified
    # Install bootstrap verbs (T7 / NEW-1)
    "install_record.bootstrap", # fresh init wrote .harness/install-record.json
])


def audit_append(entry: dict, *, audit_path: Path) -> int:
    """Append one JSON-line audit entry with S06 chain fields. Returns the assigned index.

    S06: stamps schema_version=2, seq, seq_global, previous_entry_hash,
    entry_hash on every new entry before serialization.

    P5-P2-1: validates entry verb against KNOWN_VERBS.  In strict mode
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
        rotation_seed_hash: Optional[str] = None
        if st_size >= ROTATION_BYTES or last_idx >= ROTATION_ENTRIES:
            # _rotate emits the audit.rotated seam entry (§2.5 P1-3) under
            # the held flock, then renames audit.log → audit.log.1.
            # audit_append holds flock on the file via audit_append's flock
            # protocol; _rotate is race-safe via the file lock.
            rotation_seed_hash = _rotate(audit_path, fd=fd)
            rotated = True
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

        # S06: read chain tip to stamp chain fields.
        # After rotation, use the seam entry's entry_hash as previous_entry_hash
        # for the new file's first entry (§2.5 seam seed wiring).
        if rotated and rotation_seed_hash is not None:
            prev_hash = rotation_seed_hash
            last_seq = 0
            # seq_global: read from the rotated file's seam entry
            rotated_file = audit_path.with_name(f"{audit_path.name}.1")
            seam_entry_last = read_last_entry(rotated_file)
            last_seq_global = seam_entry_last.get("seq_global", 0) if seam_entry_last else 0
        else:
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
            #
            # P3-P1-A fix: by_source and confirmation_kind are the
            # truncation-resilient identity discriminators (§12.5 #1 +
            # S05 override-identity audit shape). The phase_approve.py
            # comment calls by_source the "truncation-resilient discriminator"
            # — that contract was FALSE under the old minimal-fallback.
            # Both fields are short strings (~30 bytes total) well within
            # the 1024-byte budget.
            #
            # IMPORTANT: Future updates to this fallback list MUST preserve
            # by_source and confirmation_kind. These two fields allow
            # forensic analysis to determine the identity and authorization
            # pathway even when the full args payload is stripped.
            minimal = {
                "index": index,
                "verb": entry.get("verb", "unknown"),
                "args": {"truncated": True},
                "at": entry.get("at"),
                "by": entry.get("by"),
                # Identity discriminators — truncation-resilient (§12.5 #1 + S05)
                "by_source": entry.get("by_source"),
                "confirmation_kind": entry.get("confirmation_kind"),
                # Chain fields are preserved per §12.5 #1
                "previous_entry_hash": prev_hash,
                "seq": seq,
                "seq_global": seq_global,
                "schema_version": 2,
            }
            # Drop None values for by_source / confirmation_kind to keep the
            # record compact — they are only present when the entry has them.
            if minimal["by_source"] is None:
                del minimal["by_source"]
            if minimal["confirmation_kind"] is None:
                del minimal["confirmation_kind"]
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
            _audit_lock(fd, mode="un")
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
    "KNOWN_VERBS",
    "audit_append",
    "read_last_entry",
    "compute_state_hash",
]
