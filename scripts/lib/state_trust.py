"""State-trust preflight (design §2.6) — slice S01-E.

Every CLI command that reads or mutates `.scratch/phase-state.json` MUST
call `preflight()` under the primary lock before trusting any field on
the on-disk state. The preflight protects against silent post-install
edits (e.g. hand-flipping `approved: false` → `true` or switching
`execution_mode` to an autopilot variant) by requiring that the
canonical state bytes hash matches the latest `after_sha256` recorded
in the audit tail.

Spec: `docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md`
§2.6 "State trust preflight".

Public surface
--------------
    StateTrustError                       -- base OSError subclass
    StateTrustLockMissingError            -- caller did not hold a live lock
    StateAuditMismatchError               -- exit 10 fault class
    preflight(scratch, *, audit_path, lock) -> None

`preflight()` does NOT mutate state, does NOT append to the audit log,
and does NOT release the lock; it only inspects. Audit-chain validation
(per-entry hash chain, rotation seam, BOM in audit) is S06 scope and
intentionally left out here — this module only re-uses the last
well-formed entry's `after_sha256` as the trust oracle. Audit-tip anchor
verification (out-of-repo) is S00.7's `audit_anchor` module and is also
out of scope for the preflight: if the anchor module's pre-check has
already passed, the entries returned by `_audit_tail_entry` can be
trusted as the tip.

Failure modes
-------------
    * State file absent ............................ no-op (nothing to trust).
    * State present + audit absent or empty ........ StateAuditMismatchError.
    * State present + audit tail lacks after_sha256  StateAuditMismatchError.
    * State present + sha mismatch ................. StateAuditMismatchError.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional, Union

from . import phase_lock as _phase_lock
from . import phase_txn as _phase_txn


STATE_NAME = _phase_txn.STATE_NAME


class StateTrustError(OSError):
    """Base class for state-trust preflight failures."""


class StateTrustLockMissingError(StateTrustError):
    """Caller invoked preflight without an acquired LockHandle."""


class StateAuditMismatchError(StateTrustError):
    """Exit 10 — `state_audit_tip_mismatch`. The on-disk state bytes
    do not hash to the latest audit tail's `after_sha256`, OR the audit
    tail has no `after_sha256` to compare against while a state file is
    present. The CLI MUST emit no mutation and print the documented
    `Fix: run harness verify --audit` recovery line."""

    exit_code = 10


def _check_lock(lock: Optional[_phase_lock.LockHandle], scratch: Path) -> None:
    """Same shape as `phase_txn._check_lock` — kept local to avoid a
    cross-module private import and to keep the error class distinct."""
    if lock is None:
        raise StateTrustLockMissingError(
            "preflight requires an acquired phase_lock.LockHandle"
        )
    if getattr(lock, "_released", False):
        raise StateTrustLockMissingError(
            "preflight was passed an already-released LockHandle"
        )
    expected = scratch / _phase_lock.PRIMARY_NAME
    if Path(lock.path) != expected:
        raise StateTrustLockMissingError(
            f"LockHandle path {lock.path!r} does not match expected {expected!r}"
        )


def preflight(
    scratch: Union[str, "os.PathLike[str]"],
    *,
    audit_path: Union[str, "os.PathLike[str]"],
    lock: Optional[_phase_lock.LockHandle],
) -> None:
    """Verify on-disk state bytes hash to the audit tail's `after_sha256`.

    Returns `None` on success. Raises `StateAuditMismatchError` (exit 10)
    on mismatch, or `StateTrustLockMissingError` if the caller is not
    holding the primary lock on `scratch`.

    No-op when the state file does not exist — there is nothing to
    trust, so nothing to refuse. Callers that require state presence
    must enforce that separately (preflight only governs trust).
    """
    scratch = Path(scratch)
    audit_path = Path(audit_path)
    _check_lock(lock, scratch)

    state_path = scratch / STATE_NAME
    if not state_path.exists():
        return None

    state_bytes = state_path.read_bytes()
    state_sha = hashlib.sha256(state_bytes).hexdigest()

    tail = _phase_txn._audit_tail_entry(audit_path)
    if tail is None:
        raise StateAuditMismatchError(
            "state file present but audit log has no entries to corroborate it; "
            "Fix: run harness verify --audit"
        )
    audit_after_sha = tail.get("after_sha256")
    if not audit_after_sha:
        raise StateAuditMismatchError(
            "audit tail entry lacks after_sha256; cannot trust state. "
            "Fix: run harness verify --audit"
        )
    if state_sha != audit_after_sha:
        raise StateAuditMismatchError(
            f"state file sha256 {state_sha} does not match audit tail "
            f"after_sha256 {audit_after_sha}; Fix: run harness verify --audit"
        )
    return None


__all__ = [
    "StateTrustError",
    "StateTrustLockMissingError",
    "StateAuditMismatchError",
    "preflight",
]
