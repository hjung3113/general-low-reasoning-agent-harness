"""Crash-safe state+audit transaction — ADR-0004 atomic write + primary lock.

ADR-0004: crash-safety = atomic write + primary lock only.
No journal, no recovery matrix, no audit-tail oracle.

Public surface
--------------
    TxnError                       -- base OSError subclass
    TxnLockMissingError(TxnError)  -- caller did not hold a live LockHandle
    TxnRequest                     -- dataclass(action, before_state,
                                                after_state, audit_entry_draft)
    STATE_NAME                     -- on-disk filename inside `.scratch/`
    commit_transaction(scratch, *, lock, request, audit_path) -> txn_id

The function MUST be called with a live `LockHandle` from
`scripts.lib.phase_lock.acquire_primary`. All steps run while that lock
is held; the caller releases it after the transaction returns.

Protocol (3 steps, ADR-0004):
  1. Write state.json.tmp with after_state canonical bytes;
     fsync(tmp_fd); fsync_parent_dir(scratch).
  2. Append audit entry with txn_id, before/after sha256 to audit.log;
     fsync_parent_dir(scratch).
  3. os.replace(state.json.tmp, state.json); fsync_parent_dir(scratch);
     fsync_file_durable(state.json).

If step 3 fails, state.json remains the old valid value (tmp was never
renamed). The audit row may have been written; a re-try will produce a
second audit row with a new txn_id — acceptable for this internal tool
(ADR-0002: no external attacker).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any, Mapping, Optional, Union

from . import audit as _audit
from . import durable_fs as _durable_fs
from . import phase_lock as _phase_lock


STATE_NAME = "phase-state.json"
TMP_NAME = "phase-state.json.tmp"

# Verbs emitted via commit_transaction (always carry txn_id, after_sha256).
_TXN_VERBS: frozenset[str] = frozenset([
    "phase.approve",
    "phase.reopen",
])


class TxnError(OSError):
    """Base class for phase_txn failures."""


class TxnLockMissingError(TxnError):
    """Caller invoked commit_transaction without an acquired LockHandle."""


@dataclasses.dataclass
class TxnRequest:
    """Inputs to one commit. `before_state` may be `None` for a from-
    nothing insert; `after_state` is the canonical post-state dict.

    Audit drafts: most verbs emit ONE audit entry per transaction
    (`audit_entry_draft`). The plural `audit_entry_drafts` accepts a LIST
    of drafts so a single atomic transaction can emit multiple correlated
    audit rows. The singular `audit_entry_draft` field is the backward-compat
    path; if both are set, the plural list wins. All drafts share the same
    `txn_id` and `before/after_sha256` decorations.
    """

    action: str
    before_state: Optional[Mapping[str, Any]]
    after_state: Mapping[str, Any]
    audit_entry_draft: Optional[Mapping[str, Any]] = None
    audit_entry_drafts: Optional[list] = None

    def resolved_drafts(self) -> list:
        """Return the canonical list of drafts to write. Plural wins over
        singular. Empty/missing -> empty list."""
        if self.audit_entry_drafts:
            return list(self.audit_entry_drafts)
        if self.audit_entry_draft is not None:
            return [self.audit_entry_draft]
        return []


def _canonical_bytes(state: Optional[Mapping[str, Any]]) -> bytes:
    """Canonical serialization for hashing AND for the state file body.

    Pinned to `json.dumps(..., sort_keys=True, indent=2,
    separators=(',', ': '))` with a trailing LF.
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
    """Execute ADR-0004 3-step protocol. Returns the assigned `txn_id`.

    Step 1: write state.json.tmp with `after_state` canonical bytes;
            fsync(tmp_fd); fsync_parent_dir(scratch).
    Step 2: append audit entry with `txn_id` and content sha256s to
            `audit.log` (audit_append fsyncs the fd internally);
            fsync_parent_dir(scratch).
    Step 3: os.replace(state.json.tmp, state.json);
            fsync_parent_dir(scratch);
            fsync_file_durable(state.json).
    """
    scratch = Path(scratch)
    audit_path = Path(audit_path)
    _check_lock(lock, scratch)

    tmp_path = scratch / TMP_NAME
    state_path = scratch / STATE_NAME

    before_bytes = _canonical_bytes(request.before_state)
    after_bytes = _canonical_bytes(request.after_state)
    before_sha = _sha256(before_bytes) if request.before_state is not None else ""
    after_sha = _sha256(after_bytes)
    txn_id = _new_txn_id()

    drafts = request.resolved_drafts()
    if not drafts:
        raise TxnError(
            "commit_transaction requires at least one audit_entry_draft "
            "(set request.audit_entry_draft or request.audit_entry_drafts)"
        )

    # --- Step 1: write state.json.tmp ----------------------------------------
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
    _durable_fs.fsync_parent_dir(scratch)

    # --- Step 2: audit append -------------------------------------------------
    now_iso = _now_iso()
    for draft in drafts:
        entry = dict(draft)
        entry.setdefault("at", now_iso)
        entry["txn_id"] = txn_id
        entry["before_sha256"] = before_sha
        entry["after_sha256"] = after_sha
        _audit.audit_append(entry, audit_path=audit_path)
    _durable_fs.fsync_parent_dir(scratch)

    # --- Step 3: atomic replace -----------------------------------------------
    _durable_fs.replace_with_retry(tmp_path, state_path)
    _durable_fs.fsync_parent_dir(scratch)
    fd = os.open(str(state_path), os.O_RDONLY)
    try:
        _durable_fs.fsync_file_durable(fd, path=state_path)
    finally:
        os.close(fd)

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
    "STATE_NAME",
    "TMP_NAME",
    "commit_transaction",
]
