"""State-trust preflight (design §2.6) — slice S01-E.

Every CLI command that reads or mutates `.scratch/phase-state.json` MUST
call `preflight()` under the primary lock before trusting any field on
the on-disk state. The preflight protects against silent post-install
edits (e.g. hand-flipping `approved: false` → `true` or switching
`execution_mode` to an autopilot variant) by requiring that
`sha256(canonical(state_bytes))` matches the latest audit tail entry's
`after_sha256`.

Spec: `docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md`
§2.6 "State trust preflight", §2.3 (canonicalization + CRLF→LF on
Windows), §2.4 (BOM = exit 5).

Public surface
--------------
    StateTrustError                       -- base OSError subclass
    StateTrustLockMissingError            -- caller did not hold a live lock
    StateBomError                         -- exit 5 (§2.4)
    StateCrlfError                        -- exit 5 (§2.3 line-ending)
    StateMalformedJsonError               -- exit 5 (cannot parse state)
    StateEmptyError                       -- exit 14 (recover-territory)
    StateAuditMismatchError               -- exit 10 fault class
    preflight(scratch, *, audit_path, lock, anchor_verified) -> None

`preflight()` does NOT mutate state, does NOT append to the audit log,
and does NOT release the lock; it only inspects.

Out of scope for S01-E
----------------------
- CLI exit-surface wiring (S02+ consumers translate the raised classes
  into the documented exit codes via `scripts/lib/exitcodes.py`).
- Rotation-seam-aware tail walking (S06 — see `_audit_tail_entry`
  docstring in `phase_txn`).
- §3.9 `Fix:` line standardization smoke (S15/S16) — the messages
  here already include the manual repair path so the cross-cutting
  verifier will accept them.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Optional, Union

from . import phase_lock as _phase_lock
from . import phase_txn as _phase_txn


STATE_NAME = _phase_txn.STATE_NAME
_BOM = b"\xef\xbb\xbf"

_FIX_AUDIT = "Fix: run 'harness verify --audit'"
_FIX_REPAIR_MANUAL = (
    "if the mismatch is intentional, restore via "
    "'git checkout -- .scratch/phase-state.json' or re-run 'harness install'"
)
_FIX_STRIP_BOM = "Fix: run 'harness repair --strip-bom .scratch/phase-state.json'"
_FIX_CRLF = (
    "Fix: re-save .scratch/phase-state.json with LF line endings "
    "(check .gitattributes / editor settings); see design §2.3"
)
_FIX_RECOVER = "Fix: run 'harness recover' before any state-mutating verb"


class StateTrustError(OSError):
    """Base class for state-trust preflight failures."""


class StateTrustLockMissingError(StateTrustError):
    """Caller invoked preflight without an acquired LockHandle."""


class StateBomError(StateTrustError):
    """Exit 5 — state file begins with UTF-8 BOM (§2.4)."""

    exit_code = 5


class StateCrlfError(StateTrustError):
    """Exit 5 — state file contains CRLF line endings (§2.3)."""

    exit_code = 5


class StateMalformedJsonError(StateTrustError):
    """Exit 5 — state file is not parseable as JSON."""

    exit_code = 5


class StateEmptyError(StateTrustError):
    """Exit 14 — state file present but zero bytes; this is a crash
    artefact, not tampering. Routes to recover, not to verify --audit."""

    exit_code = 14


class StateAuditMismatchError(StateTrustError):
    """Exit 10 — `state_audit_mismatch`. The canonical state bytes
    do not hash to the latest audit tail's `after_sha256`, OR the audit
    tail has no `after_sha256` to compare against while a state file is
    present. The CLI MUST emit no mutation."""

    exit_code = 10


def _check_lock(lock: Optional[_phase_lock.LockHandle], scratch: Path) -> None:
    if lock is None:
        raise StateTrustLockMissingError(
            "preflight requires an acquired phase_lock.LockHandle"
        )
    if getattr(lock, "_released", False):
        raise StateTrustLockMissingError(
            "preflight was passed an already-released LockHandle"
        )
    expected = (scratch / _phase_lock.PRIMARY_NAME).resolve()
    actual = Path(lock.path).resolve()
    if actual != expected:
        raise StateTrustLockMissingError(
            f"LockHandle path {actual!r} does not match expected {expected!r}"
        )


def _canonicalize_state_bytes(state_bytes: bytes) -> bytes:
    """§2.6 step 1: reject BOM/CRLF, parse, re-emit via the same
    canonical form `commit_transaction` writes. Returns canonical bytes
    suitable for the sha256 oracle comparison.

    This catches an attacker who reformats state.json with cosmetic
    whitespace but keeps it JSON-equivalent — the cosmetic edit would
    change the raw-byte sha but not the canonical sha. We hash the
    canonical form so legitimate writes (which already arrive in
    canonical form) round-trip identity, while non-canonical edits
    surface as mismatches against the audit oracle's hash of canonical
    bytes (`commit_transaction` writes canonical bytes to disk and
    hashes the same bytes for the audit entry).
    """
    if state_bytes.startswith(_BOM):
        raise StateBomError(
            f"state file begins with UTF-8 BOM (forbidden by §2.4); {_FIX_STRIP_BOM}"
        )
    if b"\r\n" in state_bytes:
        raise StateCrlfError(
            f"state file contains CRLF line endings (forbidden by §2.3); {_FIX_CRLF}"
        )
    try:
        parsed = json.loads(state_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StateMalformedJsonError(
            f"state file not parseable as UTF-8 JSON: {exc}; {_FIX_RECOVER}"
        ) from exc
    return _phase_txn._canonical_bytes(parsed)


def preflight(
    scratch: Union[str, "os.PathLike[str]"],
    *,
    audit_path: Union[str, "os.PathLike[str]"],
    lock: Optional[_phase_lock.LockHandle],
    anchor_verified: bool = True,
) -> None:
    """Verify on-disk state bytes canonically hash to the audit tail's
    `after_sha256`.

    Returns `None` on success.

    Raises:
        StateTrustLockMissingError  -- caller missing/released lock.
        StateBomError / StateCrlfError / StateMalformedJsonError
                                    -- exit 5, state bytes ill-formed.
        StateEmptyError             -- exit 14, state file is 0 bytes
                                        (crash artefact — run recover).
        StateAuditMismatchError     -- exit 10, canonical sha does not
                                        match the audit tail's
                                        `after_sha256`.

    No-op when the state file does not exist (nothing to trust →
    nothing to refuse).

    The `anchor_verified` parameter is retained for backward compatibility
    with callers; it is a no-op (the out-of-repo anchor feature has been removed).
    """
    scratch = Path(scratch)
    audit_path = Path(audit_path)
    _check_lock(lock, scratch)

    state_path = scratch / STATE_NAME
    if not state_path.exists():
        return None

    state_bytes = state_path.read_bytes()
    if len(state_bytes) == 0:
        raise StateEmptyError(
            f"state file present but empty (likely crash artefact); {_FIX_RECOVER}"
        )

    canonical_bytes = _canonicalize_state_bytes(state_bytes)
    state_sha = hashlib.sha256(canonical_bytes).hexdigest()

    tail = _phase_txn._audit_tail_entry(audit_path)
    if tail is None:
        raise StateAuditMismatchError(
            f"state file present but audit log has no entries to corroborate it; "
            f"{_FIX_AUDIT}; {_FIX_REPAIR_MANUAL}"
        )
    audit_after_sha = tail.get("after_sha256")
    if not audit_after_sha:
        raise StateAuditMismatchError(
            f"audit tail entry lacks after_sha256; cannot trust state; "
            f"{_FIX_AUDIT}; {_FIX_REPAIR_MANUAL}"
        )
    if state_sha != audit_after_sha:
        raise StateAuditMismatchError(
            f"state file sha256 {state_sha} does not match audit tail "
            f"after_sha256 {audit_after_sha}; {_FIX_AUDIT}; {_FIX_REPAIR_MANUAL}"
        )

    # P1-1 defense-in-depth: check for PENDING autopilot_start_entry_hash.
    # If recover() ran first (the normal path) this check will never fire.
    # If preflight runs before recover() (unexpected ordering), refuse and
    # direct the operator to run recover — exit 14 (sub_reason documented
    # in the StateAuditMismatchError). The PENDING sentinel means a crash
    # happened between the two-phase autopilot start commits; the state is
    # structurally valid but semantically corrupt (autopilot_start_entry_hash
    # is "PENDING", not a real hash). §12.5 #1 requires recover() runs first;
    # this check is the last line of defense if that ordering is violated.
    try:
        parsed_state = json.loads(canonical_bytes.decode("utf-8"))
        if (
            parsed_state.get("autopilot_start_entry_hash") == "PENDING"
            and parsed_state.get("execution_mode") != "manual"
        ):
            raise StateAuditMismatchError(
                "autopilot_start_entry_hash is 'PENDING' — a crash occurred "
                "between two-phase autopilot start commits; "
                "sub_reason=autopilot_start_hash_pending_after_crash; "
                f"{_FIX_RECOVER}"
            )
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass  # Already validated above; this branch is unreachable in practice

    return None


__all__ = [
    "StateTrustError",
    "StateTrustLockMissingError",
    "StateBomError",
    "StateCrlfError",
    "StateMalformedJsonError",
    "StateEmptyError",
    "StateAuditMismatchError",
    "preflight",
]
