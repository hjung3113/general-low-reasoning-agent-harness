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
    preflight(scratch, *, audit_path, lock) -> None

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

_FIX_AUDIT = "Fix: inspect .harness/audit.log manually"
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
    artefact, not tampering. Routes to recover, not to audit inspection."""

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


def _scan_file_for_recent_txn_entry(path: Path) -> Optional[dict]:
    """Scan one audit file in reverse for the most recent entry with
    ``after_sha256``. Raises ``StateAuditMismatchError`` if a TXN-verb
    entry is found without ``after_sha256`` (torn-write corruption).
    Returns ``None`` if no usable entry is found in this file.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in reversed(text.splitlines()):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        after_sha = entry.get("after_sha256")
        if after_sha:
            return entry
        verb = entry.get("verb")
        if verb in _phase_txn._TXN_VERBS:
            raise StateAuditMismatchError(
                f"audit TXN-verb entry (verb={verb!r}) is missing after_sha256; "
                f"sub_reason=txn_entry_missing_after_sha256; "
                f"likely torn write or truncation; "
                f"{_FIX_AUDIT}; {_FIX_REPAIR_MANUAL}"
            )
        # Non-TXN telemetry without after_sha256: skip.
    return None


def _most_recent_txn_entry(audit_path: Path) -> Optional[dict]:
    """Return the most recent audit entry that carries an
    ``after_sha256`` field — i.e. the most recent state-mutation
    commit, regardless of verb.

    Walks rotated audit files (``audit.log``, ``audit.log.1``,
    ``audit.log.2``, …) in newest-first order so that legitimate state
    progression preserved in a rotated-out file is still found when the
    current ``audit.log`` contains only telemetry. Reuses
    ``audit_rotation.enumerate_rotated_files`` (which ``audit_chain``
    also uses, via ``audit_chain._enumerate_rotated_files``) for
    consistent file enumeration.

    Telemetry-only verbs (``cli.deprecated_flag``,
    ``ci.oidc.jti.consumed``, ``approve_nonce.mint``, etc.) do not
    carry ``after_sha256`` and are skipped so they don't shadow the
    last legitimate state-commit oracle.

    A TXN-verb entry (verbs in ``phase_txn._TXN_VERBS``) with a
    missing/empty/null ``after_sha256`` is a disk-corruption signal
    (torn write, truncation mid-flush). Surfaced as
    ``StateAuditMismatchError`` rather than silently walking past it.

    Returns ``None`` when the audit log (across all rotations) is
    absent, empty, or contains no entries with ``after_sha256`` (clean
    fresh-install or telemetry-only history).
    """
    from .audit_rotation import enumerate_rotated_files
    # enumerate returns oldest-first ([log.N, …, log.1, log]); reverse
    # to walk newest-first (current log, then log.1, log.2, …).
    files = list(reversed(enumerate_rotated_files(audit_path)))
    for path in files:
        if not path.exists():
            continue
        entry = _scan_file_for_recent_txn_entry(path)
        if entry is not None:
            return entry
    return None


def _is_baseline_state(parsed_state: dict) -> bool:
    """Return True iff ``parsed_state`` matches the fresh-install baseline
    shape written by ``harness install`` (see
    ``harness/skeleton/clean/.scratch/phase-state.json``).

    A baseline state has not yet been approved/advanced/autopiloted, so
    it is legitimate to trust without audit-log corroboration. Any
    deviation (approved=true, plan_id set, advanced phase, autopilot
    active, etc.) indicates real progression that must be backed by
    audit-log TXN entries.
    """
    if not isinstance(parsed_state, dict):
        return False
    # Discriminating fields: each must match the skeleton.
    if parsed_state.get("approved") is not False:
        return False
    if parsed_state.get("phase") != "discuss":
        return False
    if parsed_state.get("plan_id") is not None:
        return False
    if parsed_state.get("automation_mode", "manual") != "manual":
        return False
    if parsed_state.get("execution_mode", "manual") != "manual":
        return False
    # Any of these progression markers being present/set = not baseline.
    progression_markers = (
        "approved_at",
        "approved_by",
        "autopilot_started_at_iso",
        "autopilot_start_entry_hash",
        "autopilot_id",
        "plan_finalized_at",
        "halt_reason",
    )
    for key in progression_markers:
        if parsed_state.get(key):
            return False
    return True


def preflight(
    scratch: Union[str, "os.PathLike[str]"],
    *,
    audit_path: Union[str, "os.PathLike[str]"],
    lock: Optional[_phase_lock.LockHandle],
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

    # Walk back through the audit log to find the most recent state-mutating
    # (TXN-verb) entry; non-TXN telemetry verbs (e.g. cli.deprecated_flag,
    # ci.oidc.jti.consumed) do not carry after_sha256 and must be skipped so
    # they don't shadow the last legitimate state commit.
    tail = _most_recent_txn_entry(audit_path)
    if tail is None:
        # No state-mutating audit entry found. Two valid cases:
        #   (a) State is at the fresh-install baseline shape (phase=discuss,
        #       approved=false, no plan, updated_by=harness-init) — this is
        #       the legitimate first-run path, trust it.
        #   (b) State carries real progression (approved=true, advanced
        #       phase, plan_id set, autopilot active, etc.) — the audit log
        #       must corroborate that progression. Missing audit evidence
        #       here means the audit log was deleted (e.g. `git clean -fd`)
        #       or never existed, and prior approvals are unverifiable.
        try:
            parsed_state = json.loads(canonical_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed_state = None
        if parsed_state is not None and not _is_baseline_state(parsed_state):
            raise StateAuditMismatchError(
                "state file shows progression beyond the fresh-install "
                "baseline, but the audit log has no state-mutating "
                "(TXN-verb) entries to corroborate it; "
                "sub_reason=state_advanced_without_audit_evidence; "
                f"{_FIX_AUDIT}; {_FIX_REPAIR_MANUAL}"
            )
        return None
    audit_after_sha = tail.get("after_sha256")
    if not audit_after_sha:
        # _most_recent_txn_entry only returns entries with after_sha256, so
        # this branch is defensive; treat as no-op (fresh install).
        return None
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
