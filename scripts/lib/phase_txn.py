"""Crash-safe state+audit transaction protocol (design §3.8).

Spec: `docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md`

Holding the state lock prevents concurrent writers; it does NOT make
two-file (state + audit) mutation crash-atomic. A power loss between
`os.replace(state)` and audit append, or between audit append and the
replace, can leave them divergent. This module provides the 5-step
protocol that closes that gap.

Slice S01-D.1 implements `commit_transaction` (steps 1-5). The 12-row
recovery matrix (`recover()`) lives in S01-D.2 and consumes the same
journal/tmp/audit artefacts written here.

Public surface
--------------
    TxnError                       -- base OSError subclass
    TxnLockMissingError(TxnError)  -- caller did not hold a live LockHandle
    TxnRequest                     -- dataclass(action, before_state,
                                                after_state, audit_entry_draft)
    JOURNAL_NAME, TMP_NAME         -- on-disk filenames inside `.scratch/`
    commit_transaction(scratch, *, lock, request, audit_path) -> txn_id

The function MUST be called with a live `LockHandle` from
`scripts.lib.phase_lock.acquire_primary`. All five steps run while that
lock is held; the caller releases it after the transaction returns.
Failure between steps 1-5 leaves the journal+tmp on disk so the recovery
matrix (S01-D.2) can resolve the partial state on next CLI start.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Mapping, Optional, Union

from . import audit as _audit
from . import durable_fs as _durable_fs
from . import phase_lock as _phase_lock


JOURNAL_NAME = "phase-state.json.journal"
TMP_NAME = "phase-state.json.tmp"
STATE_NAME = "phase-state.json"


class TxnError(OSError):
    """Base class for phase_txn failures. Callers map to exit 14
    (`crash_recovery_undecidable` family) unless a more specific
    subclass dictates otherwise."""


class TxnLockMissingError(TxnError):
    """Caller invoked commit_transaction without an acquired LockHandle."""


@dataclasses.dataclass
class TxnRequest:
    """Inputs to one commit. `before_state` may be `None` for a from-
    nothing insert; `after_state` is the canonical post-state dict.
    `audit_entry_draft` is the verb-level payload (`{verb, by, args, ...}`)
    that this module decorates with `txn_id` + sha256 hashes before
    appending to the audit log.
    """

    action: str
    before_state: Optional[Mapping[str, Any]]
    after_state: Mapping[str, Any]
    audit_entry_draft: Mapping[str, Any]


def _canonical_bytes(state: Optional[Mapping[str, Any]]) -> bytes:
    """Canonical serialization for hashing AND for the state file body.

    Pinned to `json.dumps(..., sort_keys=True, indent=2,
    separators=(',', ': '))` with a trailing LF, matching the existing
    `state_migrate.serialize` shape (recovery matrix in S01-D.2 depends
    on byte-equality with prior writes). For audit-chain canonicalization
    (rfc8785) see §2.3 — that lives in S06.
    """
    if state is None:
        return b""
    text = json.dumps(dict(state), sort_keys=True, indent=2, separators=(",", ": "))
    return (text + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _new_txn_id() -> str:
    return secrets.token_hex(16)


def _check_lock(lock: Optional[_phase_lock.LockHandle], scratch: Path) -> None:
    if lock is None:
        raise TxnLockMissingError(
            "commit_transaction requires an acquired phase_lock.LockHandle"
        )
    if getattr(lock, "_released", False):
        raise TxnLockMissingError(
            "commit_transaction was passed an already-released LockHandle"
        )
    expected = scratch / _phase_lock.PRIMARY_NAME
    if Path(lock.path) != expected:
        raise TxnLockMissingError(
            f"LockHandle path {lock.path!r} does not match expected {expected!r}"
        )


def commit_transaction(
    scratch: Union[str, "os.PathLike[str]"],
    *,
    lock: Optional[_phase_lock.LockHandle],
    request: TxnRequest,
    audit_path: Union[str, "os.PathLike[str]"],
) -> str:
    """Execute steps 1-5 of design §3.8 in order. Returns the assigned `txn_id`.

    Step 1: write journal {txn_id, action, before_sha256, after_sha256,
            audit_entry_draft, started_at_monotonic}; fsync(journal_fd);
            fsync_parent_dir(scratch).
    Step 2: write state.json.tmp with `after_state` canonical bytes;
            fsync(tmp_fd); fsync_parent_dir(scratch). (Round-5 BLOCK #4:
            the tmp's parent-dir fsync MUST precede step 3.)
    Step 3: append audit entry with `txn_id` and content sha256s to
            `audit.log` (audit_append fsyncs the fd internally).
    Step 4: os.replace(state.json.tmp, state.json) via replace_with_retry;
            fsync_parent_dir(scratch).
    Step 5: os.unlink(journal); fsync_parent_dir(scratch).
    """
    scratch = Path(scratch)
    audit_path = Path(audit_path)
    _check_lock(lock, scratch)

    journal_path = scratch / JOURNAL_NAME
    tmp_path = scratch / TMP_NAME
    state_path = scratch / STATE_NAME

    before_bytes = _canonical_bytes(request.before_state)
    after_bytes = _canonical_bytes(request.after_state)
    before_sha = _sha256(before_bytes) if request.before_state is not None else ""
    after_sha = _sha256(after_bytes)
    txn_id = _new_txn_id()

    # --- Step 1: journal -----------------------------------------------------
    journal_payload = {
        "txn_id": txn_id,
        "action": request.action,
        "before_sha256": before_sha,
        "after_sha256": after_sha,
        "audit_entry_draft": dict(request.audit_entry_draft),
        "started_at_monotonic": time.monotonic(),
    }
    journal_bytes = (
        json.dumps(journal_payload, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    fd = os.open(
        str(journal_path),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        os.write(fd, journal_bytes)
        os.fsync(fd)
    finally:
        os.close(fd)
    _durable_fs.fsync_parent_dir(scratch)

    # --- Step 2: state.json.tmp ---------------------------------------------
    fd = os.open(
        str(tmp_path),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        os.write(fd, after_bytes)
        os.fsync(fd)
    finally:
        os.close(fd)
    # Round-5 BLOCK #4: tmp directory entry MUST be durable before audit
    # references it (otherwise recovery oracle points at non-existent tmp).
    _durable_fs.fsync_parent_dir(scratch)

    # --- Step 3: audit append ----------------------------------------------
    entry = dict(request.audit_entry_draft)
    entry.setdefault("at", _now_iso())
    entry["txn_id"] = txn_id
    entry["before_sha256"] = before_sha
    entry["after_sha256"] = after_sha
    _audit.audit_append(entry, audit_path=audit_path)
    # §12.5 #3 (Round-7 amendment): after `fsync(audit_fd)` inside
    # `audit_append`, the harness MUST `fsync_parent_dir(scratch)`
    # before proceeding to step 4. Without this the scratch dir entry
    # for tmp could still be undurable in a crash window even though
    # audit already references it.
    _durable_fs.fsync_parent_dir(scratch)

    # --- Step 4: atomic replace --------------------------------------------
    # `replace_with_retry` raises DurableFsError on Windows AV pin
    # exhaustion. The journal + tmp are left in place so the recovery
    # matrix (S01-D.2 rows 7 / 8a / 8b) can resolve on next start.
    _durable_fs.replace_with_retry(tmp_path, state_path)
    _durable_fs.fsync_parent_dir(scratch)
    # §12.5 #4: step 4 now requires `fsync_file_durable` of the renamed
    # state.json IN ADDITION to the directory fsync above. On APFS this
    # promotes the dir fsync to `F_FULLFSYNC` on the file's bytes; on
    # Windows it FlushFileBuffers the file via a re-open. Without this
    # the rename can be durable while the file's data pages still sit
    # in volatile cache, defeating the §3.8 crash guarantee.
    fd = os.open(str(state_path), os.O_RDONLY)
    try:
        _durable_fs.fsync_file_durable(fd, path=state_path)
    finally:
        os.close(fd)

    # --- Step 5: unlink journal --------------------------------------------
    os.unlink(journal_path)
    _durable_fs.fsync_parent_dir(scratch)

    return txn_id


def _now_iso() -> str:
    import datetime

    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


__all__ = [
    "TxnError",
    "TxnLockMissingError",
    "TxnRequest",
    "JOURNAL_NAME",
    "TMP_NAME",
    "STATE_NAME",
    "commit_transaction",
]
